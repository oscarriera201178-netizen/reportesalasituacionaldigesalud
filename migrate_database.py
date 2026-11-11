import argparse
import os
import sqlite3
import tempfile
from pathlib import Path

from psycopg import sql

from database import DATABASE_ERRORS, TABLES
from store import InventoryError, Store


def migrate(source_path: Path, database_url: str, *, apply: bool = False) -> dict[str, int]:
    """Copy a consistent snapshot into an empty destination, or only preflight it."""
    if not database_url:
        raise InventoryError("Configura DATABASE_URL en una terminal privada.")
    source_path = source_path.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="salud-migracion-") as directory:
        snapshot = Path(directory) / "snapshot.sqlite3"
        with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(snapshot) as target:
                source.backup(target)
        with sqlite3.connect(snapshot) as source:
            if source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise InventoryError("El respaldo SQLite está dañado; no se migró.")
            if source.execute("PRAGMA foreign_key_check").fetchone():
                raise InventoryError("El respaldo tiene referencias inválidas; no se migró.")
            tables = {
                row[0] for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
                )
            }
            if "centers" not in tables or "users" not in tables or tables - set(TABLES):
                raise InventoryError("El archivo no es una base de inventarios compatible.")
        local = Store(snapshot)
        if not local.initialized():
            raise InventoryError("El respaldo no contiene una cuenta administradora.")
        remote = Store(database_url=database_url, require_empty=True)
        counts = {}
        with (
            local.connect() as source,
            remote.transaction() as destination,
            destination.raw.transaction(force_rollback=not apply),
        ):
            for table in TABLES:
                if destination.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    raise InventoryError("La base de destino debe estar vacía; no se sobrescribió información.")
            for table in TABLES:
                columns = source.table_columns(table)
                if columns != destination.table_columns(table):
                    raise InventoryError(f"El esquema de {table} no coincide; no se migró.")
                rows = [dict(row) for row in source.execute(f"SELECT * FROM {table}")]
                counts[table] = len(rows)
                if rows:
                    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(table),
                        sql.SQL(", ").join(map(sql.Identifier, columns)),
                        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                    )
                    with destination.raw.cursor() as cursor:
                        cursor.executemany(statement, [tuple(row[column] for column in columns) for row in rows])
                actual = [dict(row) for row in destination.execute(f"SELECT * FROM {table}")]
                # Compare every value, including IDs, password bytes and timestamps.
                key = lambda row: tuple(repr(row[column]) for column in columns)
                if sorted(rows, key=key) != sorted(actual, key=key):
                    raise InventoryError(f"La verificación de {table} falló; se canceló la migración.")
            if apply:
                for table in TABLES:
                    if "id" in source.table_columns(table):
                        destination.raw.execute(
                            sql.SQL(
                                "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                                "COALESCE((SELECT MAX(id) FROM {}), 0) + 1, false)"
                            ).format(sql.Identifier(table)),
                            (table,),
                        )
        return counts


def main():
    parser = argparse.ArgumentParser(description="Migrar un respaldo privado SQLite a PostgreSQL vacío.")
    parser.add_argument("--source", type=Path, required=True, help="Respaldo SQLite de producción.")
    parser.add_argument("--apply", action="store_true", help="Copiar datos; sin esta opción solo verifica.")
    args = parser.parse_args()
    try:
        counts = migrate(args.source, os.environ.get("DATABASE_URL", ""), apply=args.apply)
    except (InventoryError, *DATABASE_ERRORS, OSError) as error:
        # Driver messages may contain connection details. Never print those.
        message = str(error) if isinstance(error, InventoryError) else "No se pudo migrar. Revisa el archivo y la conexión privada."
        parser.exit(1, message + "\n")
    print("Migración verificada y confirmada." if args.apply else "Verificación previa completada; no se copiaron datos.")
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
