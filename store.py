import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


QUANTITY_CATEGORIES = ("Camas", "Vehículos")
AMBULANCE_TYPES = ("Soporte básico", "Soporte avanzado", "Tácticas")
BED_TYPES = ("Hospitalización", "Observación", "Trauma shock", "UTIA", "UTIP", "UCI")
VEHICLE_TYPES = (
    "Carros / camionetas", "Carga pesada (camiones y gandolas)",
    "Transporte de personal (autobús, van y minivan)", "Motos",
)
VEHICLE_GROUPS = {
    "Ambulancias": AMBULANCE_TYPES,
    "Vehículos protocolares": (VEHICLE_TYPES[0],),
    "Carga pesada (camiones y gandolas)": (VEHICLE_TYPES[1],),
    "Transporte de personal (autobús, van y minivan)": (VEHICLE_TYPES[2],),
    "Motos": (VEHICLE_TYPES[3],),
}
THEATRE_TYPES = ("En pisos", "En emergencias")
SPECIAL_EQUIPMENT_TYPES = (
    "Máquina de anestesia", "Tomógrafo", "Resonador", "Radiología",
    "Ecógrafo", "Arco en C", "Silla odontológica", "Silla para diálisis",
)
REPORT_SECTIONS = (
    "Camas", "Vehículos", "Banco de sangre", "Laboratorio", "Quirófano",
    "Equipos médicos especiales", "Plantas eléctricas",
)
FACILITY_CATEGORIES = ("Banco de sangre", "Laboratorio", "Quirófano")
INVENTORY_QUANTITIES = {
    "Camas": BED_TYPES,
    "Ambulancias": AMBULANCE_TYPES,
    "Vehículos protocolares": VEHICLE_TYPES,
    "Banco de sangre": ("Banco de sangre",),
    "Laboratorio": ("Laboratorio", "Laboratorio de emergencia"),
    "Quirófano": THEATRE_TYPES,
    "Plantas eléctricas": ("Plantas eléctricas",),
}
STATES = ("Operativo", "Fuera de servicio")
IDLE_SECONDS = 30 * 60
SESSION_SECONDS = 8 * 60 * 60
REPORT_COLUMNS = "id, name, location, assigned_username"
REPORT_TIMEZONE = ZoneInfo("America/Caracas")
REPORT_LOADED = (
    "SU REPORTE SEMANAL FUE ENVIADO A LA SALA SITUACIONAL DIGESALUD-MPPD. "
    "ESTE REPORTE SERA ENVIADO AL DIRECTOR DEL CENTRO DE SALUD POR EL DIRECTOR "
    "GENERAL DE DIGESALUD-MPPPD PARA SU CONFIRMACION"
)
REPORT_PENDING = "Pendiente por reportar"
REPORT_SCHEDULE = "Las cargas se habilitan los jueves a las 00:00 y cierran los viernes a las 23:59 (hora de Venezuela)."
REQUIRED_FIELDS = {
    "quantities": {"kind": "tipo"},
    "facility_counts": {"kind": "tipo"},
    "facilities": {"name": "nombre", "kind": "tipo o especialidad"},
    "equipment": {
        "code": "código", "kind": "tipo", "brand": "marca", "model": "modelo", "serial": "número de serie",
    },
}


def load_center_catalog() -> list[dict]:
    try:
        catalog = json.loads(Path(__file__).with_name("centers.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InventoryError("El catálogo de centros no contiene JSON válido.") from error
    if not isinstance(catalog, list):
        raise InventoryError("El catálogo de centros debe ser una lista.")
    return catalog


class InventoryError(ValueError):
    pass


class AccessError(PermissionError):
    pass


def _text(value: str, label: str, limit: int = 160, required: bool = True) -> str:
    value = value.strip()
    if (required and not value) or len(value) > limit:
        raise InventoryError(f"{label}: completa el campo con hasta {limit} caracteres.")
    return value


def _password(password: str) -> None:
    if not 12 <= len(password) <= 128:
        raise InventoryError("La contraseña debe tener entre 12 y 128 caracteres.")


def _username(username: str) -> str:
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,40}", username):
        raise InventoryError("El usuario admite de 3 a 40 letras sin acentos, números, punto, guion o guion bajo.")
    return username


def _catalog_username(username: str) -> str:
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.+-]+@[a-z0-9.-]+\.[a-z]{2,}", username) or len(username) > 80:
        raise InventoryError("Usuario del catálogo no válido; se requiere un correo.")
    return username


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=32768, r=8, p=1,
        dklen=32, maxmem=64 * 1024 * 1024,
    )


def weekly_status(submitted_at: float, now: float) -> dict:
    local = datetime.fromtimestamp(now, REPORT_TIMEZONE)
    start = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    end = start + timedelta(days=7)
    loaded = bool(submitted_at and start.timestamp() <= submitted_at < end.timestamp())
    open_window = start + timedelta(days=3) <= local < start + timedelta(days=5)
    return {
        "submitted_at": submitted_at,
        "period_start": start.timestamp(),
        "loaded": loaded,
        "open": open_window,
        "editable": open_window and not loaded,
        "status": REPORT_LOADED if loaded else REPORT_PENDING,
    }


class Store:
    def __init__(self, path: Path | None = None, *, allow_out_of_schedule: bool = False):
        self.allow_out_of_schedule = allow_out_of_schedule
        directory = Path(os.environ.get(
            "SALUD_DATA_DIR", str(Path(__file__).parent / "data"),
        ))
        self.path = path if path is not None else directory / "inventario.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS centers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    location TEXT NOT NULL DEFAULT '',
                    assigned_username TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'center')),
                    center_id INTEGER UNIQUE REFERENCES centers(id),
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    must_change INTEGER NOT NULL DEFAULT 1,
                    failures INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL NOT NULL DEFAULT 0,
                    CHECK((role = 'admin' AND center_id IS NULL)
                        OR (role = 'center' AND center_id IS NOT NULL))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS single_admin
                    ON users(role) WHERE role = 'admin';
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    created REAL NOT NULL,
                    touched REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quantities (
                    id INTEGER PRIMARY KEY,
                    center_id INTEGER NOT NULL REFERENCES centers(id),
                    category TEXT NOT NULL CHECK(category IN ('Camas', 'Vehículos')),
                    kind TEXT NOT NULL COLLATE NOCASE,
                    operational INTEGER NOT NULL CHECK(operational >= 0),
                    unavailable INTEGER NOT NULL CHECK(unavailable >= 0),
                    UNIQUE(center_id, category, kind)
                );
                CREATE TABLE IF NOT EXISTS facilities (
                    id INTEGER PRIMARY KEY,
                    center_id INTEGER NOT NULL REFERENCES centers(id),
                    category TEXT NOT NULL CHECK(category IN
                        ('Banco de sangre', 'Laboratorio', 'Quirófano')),
                    name TEXT NOT NULL COLLATE NOCASE,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('Operativo', 'Fuera de servicio')),
                    UNIQUE(center_id, category, name)
                );
                CREATE TABLE IF NOT EXISTS facility_counts (
                    id INTEGER PRIMARY KEY,
                    center_id INTEGER NOT NULL REFERENCES centers(id),
                    category TEXT NOT NULL CHECK(category IN
                        ('Banco de sangre', 'Laboratorio', 'Quirófano')),
                    kind TEXT NOT NULL COLLATE NOCASE,
                    operational INTEGER NOT NULL CHECK(operational >= 0),
                    unavailable INTEGER NOT NULL CHECK(unavailable >= 0),
                    UNIQUE(center_id, category, kind)
                );
                CREATE TABLE IF NOT EXISTS migrated_facilities (
                    facility_id INTEGER PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS section_loads (
                    center_id INTEGER NOT NULL REFERENCES centers(id),
                    section TEXT NOT NULL,
                    period_start REAL NOT NULL,
                    loaded INTEGER NOT NULL CHECK(loaded IN (0, 1)),
                    PRIMARY KEY(center_id, section, period_start)
                );
                CREATE TABLE IF NOT EXISTS vehicle_history (
                    id INTEGER PRIMARY KEY,
                    center_id INTEGER NOT NULL REFERENCES centers(id),
                    kind TEXT NOT NULL,
                    operational INTEGER NOT NULL,
                    unavailable INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS special_laboratories (
                    center_id INTEGER NOT NULL REFERENCES centers(id),
                    slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 3),
                    name TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('Operativo', 'Fuera de servicio')),
                    PRIMARY KEY(center_id, slot),
                    UNIQUE(center_id, name COLLATE NOCASE)
                );
                CREATE TABLE IF NOT EXISTS equipment_types (
                    kind TEXT PRIMARY KEY COLLATE NOCASE
                );
                CREATE TABLE IF NOT EXISTS equipment_counts (
                    id INTEGER PRIMARY KEY,
                    center_id INTEGER NOT NULL REFERENCES centers(id),
                    category TEXT NOT NULL CHECK(category='Equipos médicos especiales'),
                    kind TEXT NOT NULL COLLATE NOCASE,
                    operational INTEGER NOT NULL CHECK(operational >= 0),
                    unavailable INTEGER NOT NULL CHECK(unavailable >= 0),
                    UNIQUE(center_id, category, kind)
                );
                CREATE TABLE IF NOT EXISTS plant_counts (
                    id INTEGER PRIMARY KEY,
                    center_id INTEGER NOT NULL REFERENCES centers(id),
                    category TEXT NOT NULL CHECK(category='Plantas eléctricas'),
                    kind TEXT NOT NULL CHECK(kind='Plantas eléctricas'),
                    operational INTEGER NOT NULL CHECK(operational >= 0),
                    unavailable INTEGER NOT NULL CHECK(unavailable >= 0),
                    UNIQUE(center_id, category, kind)
                );
                CREATE TABLE IF NOT EXISTS equipment (
                    id INTEGER PRIMARY KEY,
                    center_id INTEGER NOT NULL REFERENCES centers(id),
                    code TEXT NOT NULL COLLATE NOCASE,
                    kind TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    serial TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('Operativo', 'Fuera de servicio')),
                    UNIQUE(center_id, code)
                );
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(centers)")}
            if "assigned_username" not in columns:
                connection.execute("ALTER TABLE centers ADD COLUMN assigned_username TEXT NOT NULL DEFAULT ''")
            for column in ("submitted_at", "changed_at"):
                if column not in columns:
                    connection.execute(f"ALTER TABLE centers ADD COLUMN {column} REAL NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS assigned_center_user "
                "ON centers(assigned_username COLLATE NOCASE) WHERE assigned_username != ''",
            )
            connection.execute("""
                INSERT INTO facility_counts(center_id, category, kind, operational, unavailable)
                SELECT center_id, category,
                    CASE WHEN category IN ('Banco de sangre', 'Laboratorio')
                        THEN category ELSE kind END,
                    SUM(CASE WHEN state='Operativo' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN state='Fuera de servicio' THEN 1 ELSE 0 END)
                FROM facilities
                WHERE id NOT IN (SELECT facility_id FROM migrated_facilities)
                GROUP BY center_id, category,
                    CASE WHEN category IN ('Banco de sangre', 'Laboratorio')
                        THEN category ELSE kind END
                ON CONFLICT(center_id, category, kind) DO UPDATE SET
                    operational=facility_counts.operational + excluded.operational,
                    unavailable=facility_counts.unavailable + excluded.unavailable
            """)
            connection.execute("""
                INSERT OR IGNORE INTO migrated_facilities(facility_id)
                SELECT id FROM facilities
            """)
            connection.execute("""
                INSERT OR IGNORE INTO equipment_types(kind)
                SELECT DISTINCT TRIM(kind) FROM equipment WHERE TRIM(kind) != ''
            """)
            connection.execute("""
                INSERT OR IGNORE INTO plant_counts(center_id, category, kind, operational, unavailable)
                SELECT center_id, 'Plantas eléctricas', kind, operational, unavailable
                FROM equipment_counts WHERE kind='Plantas eléctricas'
            """)
            connection.execute("DELETE FROM equipment_counts WHERE kind='Plantas eléctricas'")
            connection.execute("""
                UPDATE section_loads SET loaded=0 WHERE section='Vehículos'
                AND center_id IN (
                    SELECT center_id FROM quantities
                    WHERE category='Vehículos' AND kind='Carga pesada / autobús'
                )
            """)
            connection.execute("""
                INSERT INTO vehicle_history(center_id, kind, operational, unavailable)
                SELECT center_id, kind, operational, unavailable FROM quantities
                WHERE category='Vehículos' AND kind='Carga pesada / autobús'
            """)
            connection.execute(
                "DELETE FROM quantities WHERE category='Vehículos' AND kind='Carga pesada / autobús'",
            )
            # El administrador asigna y cambia las claves de los centros: ninguna
            # cuenta de centro debe quedar obligada a cambiar su contraseña.
            connection.execute("UPDATE users SET must_change=0 WHERE role='center'")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def initialized(self) -> bool:
        with self.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM users WHERE role='admin'",
            ).fetchone() is not None

    def _create_user(self, connection, username, password, role, center_id):
        username = _username(username)
        _password(password)
        salt = secrets.token_bytes(16)
        try:
            connection.execute(
                "INSERT INTO users(username,salt,password_hash,role,center_id,must_change) "
                "VALUES(?,?,?,?,?,0)",
                (username, salt, _hash(password, salt), role, center_id),
            )
        except sqlite3.IntegrityError as error:
            raise InventoryError("El usuario o la cuenta del centro ya existe.") from error

    def bootstrap(self, username: str, password: str) -> None:
        with self.transaction() as connection:
            if connection.execute("SELECT 1 FROM users").fetchone():
                raise InventoryError("La cuenta administradora ya existe.")
            self._create_user(connection, username, password, "admin", None)

    def login(self, username: str, password: str) -> str:
        if len(password) > 128:
            raise AccessError("Usuario o contraseña incorrectos, o cuenta bloqueada.")
        now = time.time()
        token = ""
        with self.transaction() as connection:
            user = connection.execute(
                "SELECT * FROM users WHERE username=?", (username.strip().lower(),),
            ).fetchone()
            valid = hmac.compare_digest(
                _hash(password, user["salt"] if user else b"\0" * 16),
                user["password_hash"] if user else b"\0" * 32,
            )
            if user and valid and user["active"] and user["locked_until"] <= now:
                connection.execute(
                    "UPDATE users SET failures=0,locked_until=0 WHERE id=?", (user["id"],),
                )
                connection.execute(
                    "DELETE FROM sessions WHERE created <= ? OR touched <= ?",
                    (now - SESSION_SECONDS, now - IDLE_SECONDS),
                )
                token = secrets.token_urlsafe(32)
                connection.execute(
                    "INSERT INTO sessions VALUES(?,?,?,?)",
                    (hashlib.sha256(token.encode()).hexdigest(), user["id"], now, now),
                )
            elif user and user["active"] and user["locked_until"] <= now:
                failures = user["failures"] + 1
                connection.execute(
                    "UPDATE users SET failures=?,locked_until=? WHERE id=?",
                    (0 if failures >= 5 else failures, now + 900 if failures >= 5 else 0, user["id"]),
                )
        if not token:
            raise AccessError("Usuario o contraseña incorrectos, o cuenta bloqueada.")
        return token

    def _actor(self, connection, token, *, admin=False, allow_password_change=False):
        now = time.time()
        key = hashlib.sha256(token.encode()).hexdigest()
        user = connection.execute(
            "SELECT u.*,s.created,s.touched FROM users u JOIN sessions s ON s.user_id=u.id "
            "WHERE s.token_hash=? AND u.active=1", (key,),
        ).fetchone()
        if not user or now - user["created"] >= SESSION_SECONDS or now - user["touched"] >= IDLE_SECONDS:
            raise AccessError("La sesión no es válida o ha vencido. Inicia sesión nuevamente.")
        if admin and user["role"] != "admin":
            raise AccessError("Esta operación requiere la cuenta administradora.")
        if user["must_change"] and not allow_password_change:
            raise AccessError("Debes cambiar la contraseña temporal antes de consultar datos.")
        connection.execute("UPDATE sessions SET touched=? WHERE token_hash=?", (now, key))
        return user

    def identity(self, token: str) -> dict:
        with self.transaction() as connection:
            user = self._actor(connection, token, allow_password_change=True)
            return {key: user[key] for key in ("id", "username", "role", "center_id", "must_change")}

    def logout(self, token: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),),
            )

    def change_password(self, token: str, current: str, new: str) -> None:
        _password(new)
        with self.transaction() as connection:
            user = self._actor(connection, token, allow_password_change=True)
            if len(current) > 128 or not hmac.compare_digest(_hash(current, user["salt"]), user["password_hash"]):
                raise InventoryError("La contraseña actual no es correcta.")
            if hmac.compare_digest(current, new):
                raise InventoryError("Elige una contraseña diferente de la actual.")
            self._set_password(connection, user["id"], new, must_change=False)

    def _set_password(self, connection, user_id, password, *, must_change):
        _password(password)
        salt = secrets.token_bytes(16)
        connection.execute(
            "UPDATE users SET salt=?,password_hash=?,must_change=?,failures=0,locked_until=0 WHERE id=?",
            (salt, _hash(password, salt), int(must_change), user_id),
        )
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def centers(self, token: str) -> list[dict]:
        with self.transaction() as connection:
            user = self._actor(connection, token)
            if user["role"] == "admin":
                rows = connection.execute("SELECT * FROM centers ORDER BY id").fetchall()
            else:
                rows = connection.execute("SELECT * FROM centers WHERE id=?", (user["center_id"],)).fetchall()
            return [dict(row) for row in rows]

    def create_center(self, token: str, name: str, location: str, username: str, password: str) -> None:
        name = _text(name, "Nombre del centro")
        location = _text(location, "Ubicación", required=False)
        username = _username(username)
        with self.transaction() as connection:
            self._actor(connection, token, admin=True)
            try:
                cursor = connection.execute(
                    "INSERT INTO centers(name,location,assigned_username) VALUES(?,?,?)",
                    (name, location, username),
                )
            except sqlite3.IntegrityError as error:
                raise InventoryError("Ya existe un centro con ese nombre o usuario asignado.") from error
            self._create_user(connection, username, password, "center", cursor.lastrowid)

    def create_account(self, token: str, center_id: int, username: str, password: str) -> None:
        username = _username(username)
        with self.transaction() as connection:
            self._actor(connection, token, admin=True)
            if not connection.execute("SELECT 1 FROM centers WHERE id=?", (center_id,)).fetchone():
                raise InventoryError("El centro seleccionado no existe.")
            self._create_user(connection, username, password, "center", center_id)

    def update_center(self, token: str, center_id: int, name: str, location: str, username: str) -> None:
        name = _text(name, "Nombre del centro")
        location = _text(location, "Ubicación", required=False)
        with self.transaction() as connection:
            self._actor(connection, token, admin=True)
            self._authorize_center(connection, token, center_id)
            account = connection.execute(
                "SELECT id, username FROM users WHERE center_id=?", (center_id,),
            ).fetchone()
            username = _catalog_username(username) if not account and "@" in username else _username(username)
            if connection.execute(
                "SELECT 1 FROM users WHERE username=? AND (center_id IS NULL OR center_id!=?)",
                (username, center_id),
            ).fetchone():
                raise InventoryError("Ese usuario ya pertenece a otra cuenta.")
            try:
                connection.execute(
                    "UPDATE centers SET name=?,location=?,assigned_username=? WHERE id=?",
                    (name, location, username, center_id),
                )
                if account and account["username"] != username:
                    connection.execute("UPDATE users SET username=? WHERE id=?", (username, account["id"]))
                    connection.execute("DELETE FROM sessions WHERE user_id=?", (account["id"],))
            except sqlite3.IntegrityError as error:
                raise InventoryError("Ya existe un centro con ese nombre o usuario asignado.") from error

    def _import_centers(self, connection, catalog: list[dict]) -> int:
        prepared = []
        names = set()
        usernames = set()
        for row in catalog:
            if not isinstance(row, dict) or set(row) != {"number", "center", "username"}:
                raise InventoryError("El catálogo debe contener solo número, centro y usuario; sin contraseñas.")
            if type(row["number"]) is not int or row["number"] < 1:
                raise InventoryError("Número de centro no válido.")
            if not isinstance(row["center"], str) or not isinstance(row["username"], str):
                raise InventoryError("El nombre y usuario deben ser texto.")
            name, _, location = row["center"].partition(" - ")
            name = _text(name, "Nombre del centro")
            location = _text(location, "Ubicación", required=False)
            username = _catalog_username(row["username"])
            if name.casefold() in names or username in usernames:
                raise InventoryError("El catálogo contiene centros o usuarios repetidos.")
            names.add(name.casefold())
            usernames.add(username)
            prepared.append((name, location, username))
        numbers = [row["number"] for row in catalog]
        if len(set(numbers)) != len(numbers):
            raise InventoryError("El catálogo contiene números repetidos.")
        added = 0
        for name, location, username in prepared:
            existing = connection.execute("SELECT * FROM centers WHERE name=?", (name,)).fetchone()
            if existing:
                if existing["location"] != location or existing["assigned_username"] != username:
                    raise InventoryError("El centro existente tiene una ubicación o usuario distinto del catálogo.")
                continue
            try:
                connection.execute(
                    "INSERT INTO centers(name,location,assigned_username) VALUES(?,?,?)",
                    (name, location, username),
                )
            except sqlite3.IntegrityError as error:
                raise InventoryError("El usuario del catálogo ya está asignado a otro centro.") from error
            added += 1
        return added

    def import_centers(self, token: str, catalog: list[dict]) -> int:
        with self.transaction() as connection:
            self._actor(connection, token, admin=True)
            return self._import_centers(connection, catalog)

    def users(self, token: str) -> list[dict]:
        with self.transaction() as connection:
            self._actor(connection, token, admin=True)
            return [dict(row) for row in connection.execute(
                "SELECT u.id,u.username,u.active,u.center_id,c.name AS center,c.location FROM users u "
                "JOIN centers c ON c.id=u.center_id ORDER BY c.id",
            )]

    def summary(self, token: str) -> list[dict]:
        with self.transaction() as connection:
            self._actor(connection, token, admin=True)
            now = time.time()
            rows = [dict(row) for row in connection.execute("""
                SELECT c.id AS "N°", c.name AS Centro, c.submitted_at AS Estado,
                    COALESCE(q.beds, 0) AS Camas,
                    COALESCE(q.vehicles, 0) AS Vehículos,
                    COALESCE(f.banks, 0) AS "Bancos de sangre",
                    COALESCE(f.labs, 0) AS Laboratorios,
                    COALESCE(f.theatres, 0) AS Quirófanos,
                    COALESCE(e.total, 0) AS Equipos,
                    COALESCE(p.total, 0) AS "Plantas eléctricas"
                FROM centers c
                LEFT JOIN (
                    SELECT center_id,
                        SUM(CASE WHEN category='Camas'
                            THEN operational + unavailable ELSE 0 END) AS beds,
                        SUM(CASE WHEN category='Vehículos'
                            THEN operational + unavailable ELSE 0 END) AS vehicles
                    FROM quantities GROUP BY center_id
                ) q ON q.center_id=c.id
                LEFT JOIN (
                    SELECT center_id,
                        SUM(CASE WHEN category='Banco de sangre' THEN units ELSE 0 END) AS banks,
                        SUM(CASE WHEN category='Laboratorio' THEN units ELSE 0 END) AS labs,
                        SUM(CASE WHEN category='Quirófano' THEN units ELSE 0 END) AS theatres
                    FROM (
                        SELECT center_id, category, operational + unavailable AS units
                        FROM facility_counts
                        UNION ALL
                        SELECT center_id, 'Laboratorio', 1 FROM special_laboratories
                        UNION ALL
                        SELECT f.center_id, f.category, 1 AS units
                        FROM facilities f
                        WHERE f.id NOT IN (SELECT facility_id FROM migrated_facilities)
                    ) GROUP BY center_id
                ) f ON f.center_id=c.id
                LEFT JOIN (
                    SELECT center_id, SUM(operational + unavailable) AS total
                    FROM equipment_counts GROUP BY center_id
                ) e ON e.center_id=c.id
                LEFT JOIN (
                    SELECT center_id, SUM(operational + unavailable) AS total
                    FROM plant_counts GROUP BY center_id
                ) p ON p.center_id=c.id
                ORDER BY c.id
            """)]
            for row in rows:
                status = weekly_status(row["Estado"], now)
                row["Estado"] = status["status"]
            return rows

    def manage_user(self, token: str, user_id: int, active: bool, password: str = "") -> None:
        with self.transaction() as connection:
            self._actor(connection, token, admin=True)
            if not connection.execute(
                "SELECT 1 FROM users WHERE id=? AND role='center'", (user_id,),
            ).fetchone():
                raise InventoryError("Selecciona una cuenta de centro válida.")
            if password:
                self._set_password(connection, user_id, password, must_change=False)
            connection.execute("UPDATE users SET active=? WHERE id=?", (int(active), user_id))
            if not active:
                connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def _authorize_center(self, connection, token, center_id):
        user = self._actor(connection, token)
        if user["role"] != "admin" and user["center_id"] != center_id:
            raise AccessError("No tienes permiso para acceder a otro centro.")
        if not connection.execute("SELECT 1 FROM centers WHERE id=?", (center_id,)).fetchone():
            raise InventoryError("El centro seleccionado no existe.")

    def inventory(self, token: str, center_id: int) -> dict[str, list[dict]]:
        with self.transaction() as connection:
            self._authorize_center(connection, token, center_id)
            result = {
                table: [dict(row) for row in connection.execute(
                    f"SELECT * FROM {table} WHERE center_id=? ORDER BY id", (center_id,),
                )]
                for table in ("quantities", "facilities", "equipment")
            }
            result["facility_counts"] = [dict(row) for row in connection.execute(
                "SELECT * FROM facility_counts WHERE center_id=? ORDER BY id", (center_id,),
            )]
            result["special_laboratories"] = [dict(row) for row in connection.execute(
                "SELECT * FROM special_laboratories WHERE center_id=? ORDER BY slot", (center_id,),
            )]
            result["equipment_counts"] = [dict(row) for row in connection.execute(
                "SELECT * FROM equipment_counts WHERE center_id=? ORDER BY id", (center_id,),
            )]
            result["plant_counts"] = [dict(row) for row in connection.execute(
                "SELECT * FROM plant_counts WHERE center_id=? ORDER BY id", (center_id,),
            )]
            result["vehicle_history"] = [dict(row) for row in connection.execute(
                "SELECT * FROM vehicle_history WHERE center_id=? ORDER BY id", (center_id,),
            )]
            return result

    def report_snapshot(self, token: str, center_id: int | None = None):
        with self.transaction() as connection:
            if center_id is None:
                self._actor(connection, token, admin=True)
                centers = connection.execute(f"SELECT {REPORT_COLUMNS} FROM centers ORDER BY name").fetchall()
            else:
                self._authorize_center(connection, token, center_id)
                centers = connection.execute(
                    f"SELECT {REPORT_COLUMNS} FROM centers WHERE id=?", (center_id,),
                ).fetchall()
            return [
                (dict(center), {
                    **{
                        table: [dict(row) for row in connection.execute(
                            (
                                "SELECT * FROM facilities WHERE center_id=? AND id NOT IN "
                                "(SELECT facility_id FROM migrated_facilities) ORDER BY id"
                                if table == "facilities"
                                else f"SELECT * FROM {table} WHERE center_id=? ORDER BY id"
                            ),
                            (center["id"],),
                        )]
                        for table in ("quantities", "facilities", "equipment")
                    },
                    "facility_counts": [dict(row) for row in connection.execute(
                        "SELECT * FROM facility_counts WHERE center_id=? ORDER BY id", (center["id"],),
                    )],
                    "special_laboratories": [dict(row) for row in connection.execute(
                        "SELECT * FROM special_laboratories WHERE center_id=? ORDER BY slot", (center["id"],),
                    )],
                    "equipment_counts": [dict(row) for row in connection.execute(
                        "SELECT * FROM equipment_counts WHERE center_id=? ORDER BY id", (center["id"],),
                    )],
                    "plant_counts": [dict(row) for row in connection.execute(
                        "SELECT * FROM plant_counts WHERE center_id=? ORDER BY id", (center["id"],),
                    )],
                })
                for center in centers
            ]

    def _save(self, token, center_id, table, fields, record_id):
        with self.transaction() as connection:
            self._authorize_center(connection, token, center_id)
            now = time.time()
            self._require_weekly_load(connection, center_id, now)
            self._require_section_editable(connection, center_id, fields.get("category", "Equipos médicos especiales"), now)
            try:
                if record_id is None:
                    columns = ", ".join(fields)
                    placeholders = ", ".join("?" for _ in fields)
                    connection.execute(
                        f"INSERT INTO {table}(center_id,{columns}) VALUES(?,{placeholders})",
                        (center_id, *fields.values()),
                    )
                else:
                    assignments = ", ".join(f"{key}=?" for key in fields)
                    cursor = connection.execute(
                        f"UPDATE {table} SET {assignments} WHERE id=? AND center_id=?",
                        (*fields.values(), record_id, center_id),
                    )
                    if cursor.rowcount != 1:
                        raise AccessError("El registro no pertenece al centro seleccionado o ya no existe.")
            except sqlite3.IntegrityError as error:
                raise InventoryError("Ya existe ese tipo, nombre o código en el centro.") from error
            connection.execute("UPDATE centers SET changed_at=? WHERE id=?", (now, center_id))

    def _missing(self, connection, center_id):
        records = 0
        missing = []
        for table in ("quantities", "facility_counts", "facilities", "equipment_counts", "plant_counts"):
            for row in connection.execute(f"SELECT * FROM {table} WHERE center_id=? ORDER BY id", (center_id,)):
                records += 1
                fields = {"kind": "tipo"} if table in ("equipment_counts", "plant_counts") else REQUIRED_FIELDS[table]
                empty = [label for column, label in fields.items() if not str(row[column]).strip()]
                if empty:
                    name = (
                        row["code"] if table == "equipment"
                        else row["kind"] if table in ("quantities", "facility_counts", "equipment_counts", "plant_counts")
                        else row["name"]
                    )
                    missing.append(f"{name}: falta {', '.join(empty)}.")
        if not records:
            missing.insert(0, "Todavía no hay datos cargados.")
        return missing

    def _missing_inventory_categories(self, connection, center_id):
        missing = []
        categories = {**INVENTORY_QUANTITIES, "Equipos médicos especiales": SPECIAL_EQUIPMENT_TYPES}
        for category, kinds in categories.items():
            stored_category = (
                "Camas" if category == "Camas"
                else "Vehículos" if category in ("Ambulancias", "Vehículos protocolares")
                else category
            )
            table = "facility_counts" if category in FACILITY_CATEGORIES else "quantities"
            if category == "Equipos médicos especiales":
                table = "equipment_counts"
            elif category == "Plantas eléctricas":
                table = "plant_counts"
            existing = {
                row["kind"].casefold() for row in connection.execute(
                    f"SELECT kind FROM {table} WHERE center_id=? AND category=?",
                    (center_id, stored_category),
                )
            }
            for kind in kinds:
                if kind.casefold() not in existing:
                    missing.append(
                        f"{category}: falta cargar {kind}; deja 00 si no tienes unidades."
                    )
        return missing

    def missing_inventory_categories(self, token: str, center_id: int) -> list[str]:
        with self.transaction() as connection:
            self._authorize_center(connection, token, center_id)
            return self._missing_inventory_categories(connection, center_id)

    def missing_data(self, token: str, center_id: int) -> list[str]:
        with self.transaction() as connection:
            self._authorize_center(connection, token, center_id)
            return self._missing(connection, center_id)

    def submission(self, token: str, center_id: int) -> dict:
        with self.transaction() as connection:
            self._authorize_center(connection, token, center_id)
            return self._weekly_status(connection, center_id, time.time())

    def _weekly_status(self, connection, center_id, now):
        row = connection.execute(
            "SELECT submitted_at FROM centers WHERE id=?", (center_id,),
        ).fetchone()
        status = weekly_status(row["submitted_at"], now)
        if self.allow_out_of_schedule:
            status["open"] = True
            status["editable"] = not status["loaded"]
        return status

    def _require_weekly_load(self, connection, center_id, now):
        status = self._weekly_status(connection, center_id, now)
        if status["loaded"]:
            raise InventoryError(f"{REPORT_LOADED}. No se permiten cambios ni nuevos envíos hasta el próximo lunes.")
        if not status["open"]:
            raise InventoryError(REPORT_SCHEDULE)

    def initialize_empty_items(self, token: str, center_id: int) -> None:
        with self.transaction() as connection:
            user = self._actor(connection, token)
            if user["role"] != "center":
                raise AccessError("Solo la cuenta del centro puede completar su inventario.")
            self._authorize_center(connection, token, center_id)
            now = time.time()
            if not self._weekly_status(connection, center_id, now)["editable"]:
                return
            for section in REPORT_SECTIONS:
                connection.execute(
                    "INSERT OR IGNORE INTO section_loads(center_id, section, period_start, loaded) "
                    "VALUES(?, ?, ?, 0)",
                    (center_id, section, weekly_status(0, now)["period_start"]),
                )
                table, kinds = self._section_quantity_types(section)
                for kind in kinds:
                    connection.execute(
                        f"INSERT OR IGNORE INTO {table}(center_id, category, kind, operational, unavailable) "
                        "VALUES(?, ?, ?, 0, 0)",
                        (center_id, section, kind),
                    )

    @staticmethod
    def _section_quantity_types(section):
        if section == "Equipos médicos especiales":
            return "equipment_counts", SPECIAL_EQUIPMENT_TYPES
        if section == "Plantas eléctricas":
            return "plant_counts", INVENTORY_QUANTITIES[section]
        if section in FACILITY_CATEGORIES:
            return "facility_counts", INVENTORY_QUANTITIES[section]
        if section == "Vehículos":
            return "quantities", (*AMBULANCE_TYPES, *VEHICLE_TYPES)
        return "quantities", INVENTORY_QUANTITIES[section]

    def section_loads(self, token: str, center_id: int) -> dict[str, bool]:
        with self.transaction() as connection:
            self._authorize_center(connection, token, center_id)
            return self._section_loads(connection, center_id, time.time())

    def _section_loads(self, connection, center_id, now):
        period = weekly_status(0, now)["period_start"]
        rows = {
            row["section"]: bool(row["loaded"])
            for row in connection.execute(
                "SELECT section, loaded FROM section_loads WHERE center_id=? AND period_start=?",
                (center_id, period),
            )
        }
        return {section: rows.get(section, False) for section in REPORT_SECTIONS}

    def _require_section_editable(self, connection, center_id, section, now):
        if section in ("Ambulancias", "Vehículos protocolares"):
            section = "Vehículos"
        if self._section_loads(connection, center_id, now).get(section):
            raise InventoryError("Esta sección ya fue cargada. Pulsa EDITAR antes de modificarla.")

    def edit_section(self, token: str, center_id: int, section: str) -> None:
        if section not in REPORT_SECTIONS:
            raise InventoryError("Selecciona una sección válida.")
        with self.transaction() as connection:
            user = self._actor(connection, token)
            if user["role"] != "center":
                raise AccessError("Solo la cuenta del centro puede editar su carga.")
            self._authorize_center(connection, token, center_id)
            now = time.time()
            self._require_weekly_load(connection, center_id, now)
            connection.execute(
                "INSERT INTO section_loads(loaded, center_id, section, period_start) VALUES(0, ?, ?, ?) "
                "ON CONFLICT(center_id, section, period_start) DO UPDATE SET loaded=0",
                (center_id, section, weekly_status(0, now)["period_start"]),
            )

    def submit(self, token: str, center_id: int, *, require_all_categories=False, require_loaded_sections=False) -> None:
        with self.transaction() as connection:
            user = self._actor(connection, token)
            if user["role"] != "center":
                raise AccessError("Solo la cuenta del centro puede enviar su inventario.")
            self._authorize_center(connection, token, center_id)
            now = time.time()
            self._require_weekly_load(connection, center_id, now)
            missing = self._missing(connection, center_id)
            if require_all_categories:
                missing.extend(self._missing_inventory_categories(connection, center_id))
            if require_loaded_sections or connection.execute(
                "SELECT 1 FROM section_loads WHERE center_id=? LIMIT 1", (center_id,),
            ).fetchone():
                missing.extend(section for section, loaded in self._section_loads(connection, center_id, now).items() if not loaded)
            if missing:
                raise InventoryError("Completa todos los datos antes de enviar.")
            connection.execute(
                "UPDATE centers SET submitted_at=? WHERE id=?", (now, center_id),
            )

    def save_quantity(self, token, center_id, category, kind, operational, unavailable, record_id=None):
        if category not in QUANTITY_CATEGORIES:
            raise InventoryError("Selecciona Camas o Vehículos.")
        for number in (operational, unavailable):
            if type(number) is not int or not 0 <= number <= 1_000_000:
                raise InventoryError("Las cantidades deben ser enteros entre 0 y 1.000.000.")
        self._save(token, center_id, "quantities", {
            "category": category, "kind": _text(kind, "Tipo"),
            "operational": operational, "unavailable": unavailable,
        }, record_id)

    def save_category_quantities_and_submit(
        self, token: str, center_id: int, category: str, quantities: dict,
        *, require_all_categories: bool = True,
    ) -> list[str]:
        return self._save_category_quantities(
            token, center_id, category, quantities, submit=True,
            require_all_categories=require_all_categories,
        )

    def save_category_quantities(
        self, token: str, center_id: int, category: str, quantities: dict,
    ) -> None:
        self._save_category_quantities(
            token, center_id, category, quantities, submit=False,
        )

    def load_section(self, token: str, center_id: int, category: str, quantities: dict) -> None:
        if category not in REPORT_SECTIONS or category == "Laboratorio":
            raise InventoryError("Selecciona una sección de cantidades válida.")
        self._save_category_quantities(
            token, center_id, category, quantities, submit=False, lock_section=True,
        )

    def _save_category_quantities(
        self, token: str, center_id: int, category: str, quantities: dict,
        *, submit: bool, require_all_categories: bool = True, special_laboratories=None, lock_section=False,
    ) -> list[str]:
        allowed_types = INVENTORY_QUANTITIES.get(category)
        if category == "Vehículos":
            allowed_types = (*AMBULANCE_TYPES, *VEHICLE_TYPES)
        if category == "Equipos médicos especiales":
            allowed_types = SPECIAL_EQUIPMENT_TYPES
        if allowed_types is None:
            raise InventoryError("Selecciona una categoría de inventario válida.")
        if (
            not isinstance(quantities, dict)
            or not set(allowed_types).issubset(quantities)
            or any(not isinstance(kind, str) or not kind.strip() for kind in quantities)
        ):
            raise InventoryError("Completa las cantidades de todos los tipos de la categoría.")
        for values in quantities.values():
            if (
                not isinstance(values, (tuple, list))
                or len(values) != 2
                or any(type(number) is not int or not 0 <= number <= 1_000_000 for number in values)
            ):
                raise InventoryError("Las cantidades deben ser enteros entre 0 y 1.000.000.")
        if category == "Equipos médicos especiales" and set(quantities) != set(SPECIAL_EQUIPMENT_TYPES):
            raise InventoryError("Selecciona únicamente los tipos definidos de equipos médicos especiales.")
        with self.transaction() as connection:
            user = self._actor(connection, token)
            if user["role"] != "center":
                raise AccessError("Solo la cuenta del centro puede enviar su inventario.")
            self._authorize_center(connection, token, center_id)
            now = time.time()
            self._require_weekly_load(connection, center_id, now)
            self._require_section_editable(connection, center_id, category, now)
            stored_category = (
                "Camas" if category == "Camas"
                else "Vehículos" if category in ("Ambulancias", "Vehículos protocolares")
                else category
            )
            table = "facility_counts" if category in FACILITY_CATEGORIES else "quantities"
            if category == "Equipos médicos especiales":
                table = "equipment_counts"
            elif category == "Plantas eléctricas":
                table = "plant_counts"
            extras = set(quantities) - set(allowed_types)
            if extras:
                existing_kinds = {
                    row["kind"] for row in connection.execute(
                        f"SELECT kind FROM {table} WHERE center_id=? AND category=?",
                        (center_id, stored_category),
                    )
                }
                if not extras.issubset(existing_kinds):
                    raise InventoryError("La categoría incluye tipos que no existen en este centro.")
            for kind in quantities:
                operational, unavailable = quantities[kind]
                connection.execute(
                    f"""
                    INSERT INTO {table}(center_id, category, kind, operational, unavailable)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(center_id, category, kind) DO UPDATE SET
                        operational=excluded.operational,
                        unavailable=excluded.unavailable
                    """,
                    (center_id, stored_category, kind, operational, unavailable),
                )
            connection.execute("UPDATE centers SET changed_at=? WHERE id=?", (now, center_id))
            if special_laboratories is not None:
                connection.execute("DELETE FROM special_laboratories WHERE center_id=?", (center_id,))
                connection.executemany(
                    "INSERT INTO special_laboratories(center_id, slot, name, state) VALUES(?, ?, ?, ?)",
                    [(center_id, slot, name, state) for slot, name, state in special_laboratories],
                )
            if lock_section:
                connection.execute(
                    "INSERT INTO section_loads(center_id, section, period_start, loaded) VALUES(?, ?, ?, 1) "
                    "ON CONFLICT(center_id, section, period_start) DO UPDATE SET loaded=1",
                    (center_id, category, weekly_status(0, now)["period_start"]),
                )
            if not submit:
                return []
            missing = self._missing(connection, center_id)
            if require_all_categories:
                missing.extend(self._missing_inventory_categories(connection, center_id))
            if connection.execute(
                "SELECT 1 FROM section_loads WHERE center_id=? LIMIT 1", (center_id,),
            ).fetchone():
                missing.extend(
                    section for section, loaded in self._section_loads(connection, center_id, now).items()
                    if not loaded
                )
            if not missing:
                connection.execute(
                    "UPDATE centers SET submitted_at=? WHERE id=?", (now, center_id),
                )
            return missing

    def save_laboratories(self, token: str, center_id: int, quantities: dict, has_special: bool, laboratories: list, *, lock_section=False) -> None:
        if type(has_special) is not bool or not isinstance(laboratories, list):
            raise InventoryError("Indica si hay laboratorios especiales.")
        if (has_special and not 1 <= len(laboratories) <= 3) or (not has_special and laboratories):
            raise InventoryError("Si hay laboratorios especiales, completa entre uno y tres.")
        validated = []
        names = set()
        slots = set()
        for laboratory in laboratories:
            if not isinstance(laboratory, dict):
                raise InventoryError("Completa el nombre y estado de cada laboratorio especial.")
            slot, name, state = laboratory.get("slot"), laboratory.get("name"), laboratory.get("state")
            if type(slot) is not int or not 1 <= slot <= 3 or slot in slots:
                raise InventoryError("Selecciona hasta tres espacios de laboratorios especiales distintos.")
            if not isinstance(name, str) or state not in STATES:
                raise InventoryError("Completa el nombre y estado de cada laboratorio especial.")
            name = _text(name, "Nombre del laboratorio especial").upper()
            if name.casefold() in names:
                raise InventoryError("Los nombres de laboratorios especiales no deben repetirse.")
            names.add(name.casefold())
            slots.add(slot)
            validated.append((slot, name, state))
        self._save_category_quantities(
            token, center_id, "Laboratorio", quantities, submit=False,
            special_laboratories=validated,
            lock_section=lock_section,
        )

    def load_laboratories(self, token: str, center_id: int, quantities: dict, has_special: bool, laboratories: list) -> None:
        self.save_laboratories(token, center_id, quantities, has_special, laboratories, lock_section=True)

    def save_ambulances_and_submit(self, token: str, center_id: int, quantities: dict) -> list[str]:
        return self.save_category_quantities_and_submit(
            token, center_id, "Ambulancias", quantities, require_all_categories=False,
        )

    def equipment_types(self, token: str) -> list[str]:
        with self.transaction() as connection:
            self._actor(connection, token)
            return [row["kind"] for row in connection.execute(
                "SELECT kind FROM equipment_types ORDER BY kind COLLATE NOCASE",
            )]

    def add_equipment_type(self, token: str, kind: str) -> None:
        kind = _text(kind, "Tipo de equipo")
        with self.transaction() as connection:
            self._actor(connection, token, admin=True)
            try:
                connection.execute("INSERT INTO equipment_types(kind) VALUES(?)", (kind,))
            except sqlite3.IntegrityError as error:
                raise InventoryError("Ese tipo de equipo ya está en la lista.") from error

    def remove_equipment_type(self, token: str, kind: str) -> None:
        with self.transaction() as connection:
            self._actor(connection, token, admin=True)
            cursor = connection.execute("DELETE FROM equipment_types WHERE kind=?", (kind,))
            if cursor.rowcount != 1:
                raise InventoryError("Selecciona un tipo de equipo configurado.")

    def save_facility(self, token, center_id, category, name, kind, state, record_id=None):
        if category not in FACILITY_CATEGORIES or state not in STATES:
            raise InventoryError("Categoría o estado de instalación no válido.")
        self._save(token, center_id, "facilities", {
            "category": category, "name": _text(name, "Nombre"),
            "kind": _text(kind, "Tipo o especialidad"), "state": state,
        }, record_id)

    def save_equipment(self, token, center_id, code, kind, brand, model, serial, state, record_id=None):
        if state not in STATES:
            raise InventoryError("Estado de equipo no válido.")
        fields = {
            "code": _text(code, "Código interno", 60), "kind": _text(kind, "Tipo"),
            "brand": _text(brand, "Marca"),
            "model": _text(model, "Modelo"),
            "serial": _text(serial, "Serie"), "state": state,
        }
        with self.transaction() as connection:
            self._authorize_center(connection, token, center_id)
            now = time.time()
            self._require_weekly_load(connection, center_id, now)
            configured = connection.execute(
                "SELECT 1 FROM equipment_types WHERE kind=?", (fields["kind"],),
            ).fetchone()
            existing = connection.execute(
                "SELECT kind FROM equipment WHERE id=? AND center_id=?",
                (record_id, center_id),
            ).fetchone() if record_id is not None else None
            if record_id is not None and existing is None:
                raise AccessError("El registro no pertenece al centro seleccionado o ya no existe.")
            if not configured and (existing is None or existing["kind"].casefold() != fields["kind"].casefold()):
                raise InventoryError("Selecciona un tipo de equipo configurado por el administrador.")
            try:
                if record_id is None:
                    columns = ", ".join(fields)
                    placeholders = ", ".join("?" for _ in fields)
                    connection.execute(
                        f"INSERT INTO equipment(center_id,{columns}) VALUES(?,{placeholders})",
                        (center_id, *fields.values()),
                    )
                else:
                    assignments = ", ".join(f"{key}=?" for key in fields)
                    cursor = connection.execute(
                        f"UPDATE equipment SET {assignments} WHERE id=? AND center_id=?",
                        (*fields.values(), record_id, center_id),
                    )
                    if cursor.rowcount != 1:
                        raise AccessError("El registro no pertenece al centro seleccionado o ya no existe.")
            except sqlite3.IntegrityError as error:
                raise InventoryError("Ya existe ese código en el centro.") from error
            connection.execute("UPDATE centers SET changed_at=? WHERE id=?", (now, center_id))


def main():
    parser = argparse.ArgumentParser(
        description="Crear la cuenta administradora o importar el catálogo en una terminal privada.",
    )
    parser.add_argument("command", choices=("bootstrap", "import-catalog"))
    args = parser.parse_args()
    if args.command == "bootstrap":
        username = input("Usuario administrador: ")
        password = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
        if password != getpass.getpass("Confirmar contraseña: "):
            parser.exit(1, "Las contraseñas no coinciden.\n")
        try:
            Store().bootstrap(username, password)
        except (InventoryError, sqlite3.Error, OSError) as error:
            parser.exit(1, f"No se pudo crear la cuenta: {error}\n")
        print("Cuenta administradora creada. Ya puedes iniciar sesión.")
    if args.command == "import-catalog":
        try:
            store = Store()
            with store.transaction() as connection:
                added = store._import_centers(connection, load_center_catalog())
        except (InventoryError, sqlite3.Error, OSError) as error:
            parser.exit(1, f"No se pudo importar el catálogo: {error}\n")
        print(f"Catálogo importado: {added} centros nuevos. Los centros existentes se conservaron.")


if __name__ == "__main__":
    main()
