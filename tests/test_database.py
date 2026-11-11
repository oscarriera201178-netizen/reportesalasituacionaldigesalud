import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from database import TABLES
from migrate_database import migrate
from store import AccessError, BED_TYPES, InventoryError, REPORT_SECTIONS, Store


PASSWORD = "Test-private-password-123"
TEST_URL = os.environ.get("SALUD_TEST_DATABASE_URL")


class DatabaseConfigurationTests(unittest.TestCase):
    def test_invalid_remote_configuration_never_falls_back_to_sqlite(self):
        for value in ("", "https://example.invalid", 42):
            with self.subTest(value=value), self.assertRaises(InventoryError):
                Store(database_url=value)

    def test_explicit_local_path_ignores_remote_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"DATABASE_URL": "invalid"}):
                local = Store(Path(directory) / "test.sqlite3")
                self.assertIsNone(local.database_url)
                with self.assertRaises(InventoryError):
                    Store()

    def test_local_backup_preserves_accounts_and_data_and_requires_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Store(Path(directory) / "source.sqlite3")
            local.bootstrap("admin", PASSWORD)
            admin = local.login("admin", PASSWORD)
            local.create_center(admin, "Centro", "", "centro", PASSWORD)
            center = local.login("centro", PASSWORD)
            center_id = local.centers(center)[0]["id"]
            local.save_quantity(center, center_id, "Camas", "UCI", 9, 2)
            with self.assertRaises(AccessError):
                local.sqlite_backup(center)
            with self.assertRaises(AccessError):
                local.sqlite_backup("invalid")
            backup = Path(directory) / "backup.sqlite3"
            backup.write_bytes(local.sqlite_backup(admin))
            restored = Store(backup)
            self.assertEqual(restored.inventory(center, center_id), local.inventory(center, center_id))
            self.assertEqual(restored.identity(restored.login("centro", PASSWORD))["center_id"], center_id)
            with sqlite3.connect(backup) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))


@unittest.skipUnless(TEST_URL, "Set SALUD_TEST_DATABASE_URL to an isolated PostgreSQL test server.")
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.name = "salud_test_" + uuid4().hex
        with psycopg.connect(TEST_URL, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.name)))
        self.addCleanup(self.drop_database)
        parts = urlsplit(TEST_URL)
        self.url = f"{parts.scheme}://{parts.netloc}/{self.name}"
        if parts.query:
            self.url += "?" + parts.query
        self.store = Store(database_url=self.url)

    def drop_database(self):
        with psycopg.connect(TEST_URL, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(self.name)))

    def populate(self, store):
        store.bootstrap("admin", PASSWORD)
        admin = store.login("ADMIN", PASSWORD)
        store.create_center(admin, "Centro Norte", "Norte", "norte", PASSWORD)
        store.create_center(admin, "Centro Sur", "Sur", "sur", PASSWORD)
        center = store.login("norte", PASSWORD)
        north, south = [row["id"] for row in store.centers(admin)]
        return admin, center, north, south

    def test_all_sections_reports_persistence_and_access_control(self):
        admin, center, north, south = self.populate(self.store)
        with self.assertRaises(AccessError):
            self.store.inventory(center, south)
        with self.assertRaises(AccessError):
            self.store.load_section(admin, north, "Camas", {kind: (0, 0) for kind in BED_TYPES})
        self.store.initialize_empty_items(center, north)
        with self.assertRaises(InventoryError):
            self.store.submit(center, north, require_loaded_sections=True)
        for section in REPORT_SECTIONS:
            _, kinds = self.store._section_quantity_types(section)
            values = {kind: (3, 1) for kind in kinds}
            if section == "Laboratorio":
                self.store.load_laboratories(center, north, values, True, [
                    {"slot": 1, "name": "microbiología", "state": "Operativo"},
                ])
            else:
                self.store.load_section(center, north, section, values)
        self.assertTrue(all(self.store.section_loads(center, north).values()))
        self.assertEqual(self.store.summary(admin)[0]["Camas"], len(BED_TYPES) * 4)
        self.assertEqual(self.store.summary(admin)[0]["Laboratorios"], 9)
        self.assertEqual(len(self.store.report_snapshot(admin)), 2)
        self.store.submit(center, north, require_all_categories=True, require_loaded_sections=True)
        restored = Store(database_url=self.url)
        self.assertTrue(restored.submission(center, north)["loaded"])
        self.assertEqual(restored.inventory(center, north), self.store.inventory(center, north))
        with self.assertRaises(InventoryError):
            restored.save_quantity(center, north, "Camas", "UCI", 5, 2)

    def test_uniqueness_failure_rolls_back_and_next_transaction_works(self):
        admin, center, north, _ = self.populate(self.store)
        with self.assertRaises(InventoryError):
            self.store.create_center(admin, "centro norte", "", "otro", PASSWORD)
        self.assertEqual(len(self.store.centers(admin)), 2)
        self.store.add_equipment_type(admin, "Monitor")
        with self.assertRaises(InventoryError):
            self.store.add_equipment_type(admin, "monitor")
        self.store.save_equipment(center, north, "E1", "Monitor", "Marca", "Modelo", "Serie", "Operativo")
        self.assertEqual(self.store.equipment_types(center), ["Monitor"])
        self.store.remove_equipment_type(admin, "monitor")
        self.store.change_password(center, PASSWORD, "Test-new-password-456")
        with self.assertRaises(AccessError):
            self.store.identity(center)
        self.assertEqual(self.store.identity(self.store.login("norte", "Test-new-password-456"))["center_id"], north)

    def test_row_level_security_blocks_public_api_roles(self):
        self.populate(self.store)
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT relname, relrowsecurity FROM pg_class "
                "WHERE relnamespace='public'::regnamespace AND relkind='r'",
            ).fetchall()
            self.assertEqual({row["relname"] for row in rows}, set(TABLES))
            self.assertTrue(all(row["relrowsecurity"] for row in rows))
            connection.execute("CREATE ROLE salud_api_test")
            connection.execute("GRANT USAGE ON SCHEMA public TO salud_api_test")
            connection.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO salud_api_test")
            connection.execute("SET LOCAL ROLE salud_api_test")
            self.assertEqual(connection.execute("SELECT * FROM users").fetchall(), [])
            connection.execute("RESET ROLE")
            connection.execute("DROP OWNED BY salud_api_test")
            connection.execute("DROP ROLE salud_api_test")

    def test_failed_logins_commit_lockout_and_concurrent_section_updates_are_serialized(self):
        from concurrent.futures import ThreadPoolExecutor

        admin, center, north, _ = self.populate(self.store)
        for _ in range(5):
            with self.assertRaises(AccessError):
                self.store.login("norte", "incorrect")
        with self.assertRaises(AccessError):
            self.store.login("norte", PASSWORD)
        values = {kind: (2, 1) for kind in BED_TYPES}
        def load():
            try:
                self.store.load_section(center, north, "Camas", values)
                return True
            except InventoryError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(lambda _: load(), range(2))), [False, True])
        self.assertEqual(self.store.summary(admin)[0]["Camas"], len(BED_TYPES) * 3)

    def test_migration_dry_run_copy_exact_values_and_identity_sequences(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            local = Store(source)
            admin, center, north, _ = self.populate(local)
            local.initialize_empty_items(center, north)
            local.load_section(center, north, "Camas", {kind: (7, 2) for kind in BED_TYPES})
            local.save_laboratories(center, north, {"Laboratorio": (1, 0), "Laboratorio de emergencia": (0, 1)}, True, [
                {"slot": 1, "name": "ESPECIAL", "state": "Operativo"},
            ])
            local.add_equipment_type(admin, "Monitor")
            local.save_equipment(center, north, "E1", "Monitor", "Marca", "Modelo", "Serie", "Operativo")
            with local.connect() as connection:
                connection.execute("INSERT INTO vehicle_history(center_id,kind,operational,unavailable) VALUES(?,?,?,?)", (north, "Anterior", 4, 1))
                connection.execute("UPDATE centers SET changed_at=123456.789,submitted_at=234567.891 WHERE id=?", (north,))
            before = source.read_bytes()
            counts = migrate(source, self.url)
            self.assertEqual(counts["users"], 3)
            self.assertFalse(self.store.initialized())
            self.assertEqual(before, source.read_bytes())
            self.assertEqual(migrate(source, self.url, apply=True), counts)
            self.assertEqual(before, source.read_bytes())
            self.assertEqual(self.store.inventory(center, north), local.inventory(center, north))
            self.assertEqual(self.store.centers(admin), local.centers(admin))
            self.assertEqual(self.store.identity(self.store.login("norte", PASSWORD))["center_id"], north)
            self.store.create_center(admin, "Centro Nuevo", "", "nuevo", PASSWORD)
            self.assertEqual([row["id"] for row in self.store.centers(admin)], [1, 2, 3])
            with self.store.connect() as connection:
                connection.execute("UPDATE users SET must_change=1 WHERE username='norte'")
            with self.assertRaisesRegex(InventoryError, "vacía"):
                migrate(source, self.url, apply=True)
            with self.store.connect() as connection:
                self.assertEqual(connection.execute("SELECT must_change FROM users WHERE username='norte'").fetchone()["must_change"], 1)

    def test_migration_failure_rolls_back_all_tables(self):
        from database import PostgresConnection

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            local = Store(source)
            self.populate(local)
            execute = PostgresConnection.execute
            def failing_execute(connection, statement, parameters=None):
                if statement == "SELECT * FROM equipment_counts":
                    raise psycopg.DataError("Test migration verification failure")
                return execute(connection, statement, parameters)
            # Failure after centers and users have been copied must roll them back.
            with patch.object(PostgresConnection, "execute", failing_execute):
                with self.assertRaises(psycopg.Error):
                    migrate(source, self.url, apply=True)
            self.assertFalse(self.store.initialized())


if __name__ == "__main__":
    unittest.main()
