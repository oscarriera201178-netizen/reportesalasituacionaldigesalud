import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from database import SQLiteConnection

from store import (
    AMBULANCE_TYPES, BED_TYPES, AccessError, IDLE_SECONDS, InventoryError, REPORT_LOADED, REPORT_PENDING,
    MILITARY_COMPONENTS, REPORT_TIMEZONE, SESSION_SECONDS, Store, load_center_catalog,
    weekly_status,
)


PASSWORD = "Test-admin-password-123"
TEMPORARY = "Test-center-password-456"
CHANGED = "Test-new-password-789"


class StoreTests(unittest.TestCase):
    def setUp(self):
        clock = patch("store.time.time", return_value=datetime(
            2026, 10, 29, 12, tzinfo=REPORT_TIMEZONE,
        ).timestamp())
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "test.sqlite3")
        self.store.bootstrap("admin", PASSWORD)
        self.admin = self.store.login("admin", PASSWORD)
        self.store.add_equipment_type(self.admin, "Monitor")
        self.store.create_center(self.admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        self.store.create_center(self.admin, "Centro Sur", "Sur", "sur", TEMPORARY)
        self.north, self.south = [row["id"] for row in self.store.centers(self.admin)]
        self.center = self.store.login("norte", TEMPORARY)
        self.store.change_password(self.center, TEMPORARY, CHANGED)
        self.center = self.store.login("norte", CHANGED)

    def test_traffic_validation_persistence_and_separation_from_death_records(self):
        fields = {
            "grade": "CAP", "full_name": "Paciente de prueba", "cedula": "V-12345678",
            "birth_date": "2000-10-16", "attention_date": "2026-10-16",
            "accident_type": "Bicicleta", "patient_condition": "Fallecido",
            "traffic_role": "Peatón", "redi": "REDI Capital", "zodi": "zodi prueba",
            "unit": "unidad prueba", "component": "Armada Bolivariana",
        }
        for field in ("grade", "component", "accident_type", "patient_condition", "traffic_role", "redi"):
            with self.subTest(field=field), self.assertRaises(InventoryError):
                self.store.add_traffic_record(self.center, **{**fields, field: "Otra opción"})
        for value in ("1999-10-15", "2026-02-30", "16/10/2026"):
            with self.subTest(date=value), self.assertRaises(InventoryError):
                self.store.add_traffic_record(self.center, **{**fields, "attention_date": value})
        with self.assertRaises(AccessError):
            self.store.add_traffic_record(self.admin, **fields)
        self.store.create_military_account(
            self.admin, "Guardia Nacional Bolivariana", "guardia", TEMPORARY,
        )
        military = self.store.login("guardia", TEMPORARY)
        with self.assertRaises(AccessError):
            self.store.add_traffic_record(military, **fields)
        with self.assertRaises(AccessError):
            self.store.traffic_records(military)
        self.assertEqual(self.store.traffic_records(self.admin), [])
        self.store.add_traffic_record(self.center, **fields)
        with self.store.connect() as connection:
            path = connection.execute("PRAGMA database_list").fetchone()["file"]
        reopened = Store(Path(path))
        rows = reopened.traffic_records(self.center)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["age"], 26)
        self.assertEqual(rows[0]["patient_condition"], "Fallecido")
        self.assertEqual(rows[0]["center_id"], self.north)
        self.assertEqual(reopened.military_records(self.admin, account_type="health"), [])
        self.assertEqual(reopened.military_records(self.admin), [])

    def test_report_snapshot_batches_tables_for_all_34_centers(self):
        with self.store.transaction() as connection:
            connection.executemany(
                "INSERT INTO centers(name) VALUES(?)",
                [(f"Centro adicional {number:02}",) for number in range(32)],
            )
        self.store.initialize_empty_items(self.center, self.north)
        expected_inventory = self.store.inventory(self.center, self.north)
        statements = []
        execute = SQLiteConnection.execute

        def traced_execute(connection, statement, *args):
            statements.append(statement)
            return execute(connection, statement, *args)

        with patch.object(SQLiteConnection, "execute", traced_execute):
            snapshot = self.store.report_snapshot(self.admin)
        self.assertEqual(len(snapshot), 34)
        table_reads = [
            statement for statement in statements
            if statement.strip().startswith("SELECT * FROM ")
        ]
        self.assertEqual(len(table_reads), 7)
        north = next(inventory for center, inventory in snapshot if center["id"] == self.north)
        for table, rows in north.items():
            self.assertEqual(rows, expected_inventory[table])
        self.assertTrue(all(not rows for center, inventory in snapshot if center["id"] != self.north for rows in inventory.values()))
        self.assertEqual(self.store.report_snapshot(self.center, self.north), [
            (next(center for center, _ in snapshot if center["id"] == self.north), north),
        ])
        with self.assertRaises(AccessError):
            self.store.report_snapshot(self.center)
        with self.assertRaises(AccessError):
            self.store.report_snapshot(self.center, self.south)

    def test_zero_defaults_require_every_section_to_be_loaded_before_submitting(self):
        self.store.initialize_empty_items(self.center, self.north)
        self.assertEqual(self.store.missing_inventory_categories(self.center, self.north), [])
        self.assertEqual(self.store.missing_data(self.center, self.north), [])
        self.assertFalse(any(self.store.section_loads(self.center, self.north).values()))
        with self.assertRaises(InventoryError):
            self.store.submit(self.center, self.north)
        inventory = self.store.inventory(self.center, self.north)
        for table in ("quantities", "facility_counts", "equipment_counts", "plant_counts"):
            self.assertTrue(all(
                row["operational"] == row["unavailable"] == 0 for row in inventory[table]
            ))
        self.store.initialize_empty_items(self.center, self.north)
        self.assertEqual(self.store.inventory(self.center, self.north), inventory)
        self.assertFalse(self.store.submission(self.center, self.north)["loaded"])
        self.store.edit_section(self.center, self.north, "Camas")
        self.store.initialize_empty_items(self.center, self.north)
        self.assertFalse(self.store.section_loads(self.center, self.north)["Camas"])
        with self.assertRaises(InventoryError):
            self.store.submit(self.center, self.north, require_all_categories=True, require_loaded_sections=True)
        values = {kind: (0, 0) for kind in BED_TYPES}
        values["UCI"] = (4, 2)
        self.store.load_section(self.center, self.north, "Camas", values)
        self.store.initialize_empty_items(self.center, self.north)
        self.assertEqual(self.store.summary(self.admin)[0]["Camas"], 6)
        from store import REPORT_SECTIONS
        for section in REPORT_SECTIONS:
            if section == "Camas":
                continue
            with self.assertRaises(InventoryError):
                self.store.submit(self.center, self.north)
            _, kinds = self.store._section_quantity_types(section)
            if section == "Laboratorio":
                self.store.load_laboratories(
                    self.center, self.north, {kind: (0, 0) for kind in kinds}, False, [],
                )
            else:
                self.store.load_section(self.center, self.north, section, {kind: (0, 0) for kind in kinds})
        self.store.submit(self.center, self.north, require_all_categories=True, require_loaded_sections=True)
        inventory = self.store.inventory(self.center, self.north)
        self.store.initialize_empty_items(self.center, self.north)
        self.assertEqual(self.store.inventory(self.center, self.north), inventory)

    def test_automatic_zeros_preserve_existing_data_and_respect_access(self):
        self.store.save_quantity(self.center, self.north, "Camas", "UCI", 7, 3)
        with self.assertRaises(AccessError):
            self.store.initialize_empty_items(self.admin, self.north)
        with self.assertRaises(AccessError):
            self.store.initialize_empty_items(self.center, self.south)
        self.store.initialize_empty_items(self.center, self.north)
        self.assertFalse(self.store.section_loads(self.center, self.north)["Camas"])
        self.assertEqual(self.store.summary(self.admin)[0]["Camas"], 10)
        self.clock.return_value = datetime(2026, 10, 31, 12, tzinfo=REPORT_TIMEZONE).timestamp()
        token = self.store.login("norte", CHANGED)
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM plant_counts WHERE center_id=?", (self.north,))
        self.store.initialize_empty_items(token, self.north)
        plants = self.store.inventory(token, self.north)["plant_counts"]
        self.assertTrue(plants)
        self.assertTrue(all(row["operational"] == row["unavailable"] == 0 for row in plants))

    def test_password_storage_and_bootstrap_are_private(self):
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(InventoryError):
            self.store.bootstrap("other", PASSWORD)
        with self.store.connect() as connection:
            user = connection.execute("SELECT * FROM users WHERE username='admin'").fetchone()
            self.assertNotEqual(user["password_hash"], PASSWORD.encode())
            self.assertEqual(len(user["salt"]), 16)

    def test_center_isolation_for_every_read_and_write(self):
        self.assertEqual([row["id"] for row in self.store.centers(self.center)], [self.north])
        operations = (
            lambda: self.store.inventory(self.center, self.south),
            lambda: self.store.save_quantity(self.center, self.south, "Camas", "UCI", 3, 1),
            lambda: self.store.save_facility(self.center, self.south, "Laboratorio", "Lab", "General", "Operativo"),
            lambda: self.store.save_equipment(self.center, self.south, "E1", "Monitor", "Marca", "Modelo", "Serie", "Operativo"),
            lambda: self.store.create_center(self.center, "Otro", "", "otro", TEMPORARY),
            lambda: self.store.users(self.center),
            lambda: self.store.summary(self.center),
            lambda: self.store.manage_user(self.center, 1, False),
        )
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(AccessError):
                operation()
        self.assertTrue(all(not rows for rows in self.store.inventory(self.admin, self.south).values()))

    def test_military_accounts_are_separate_and_only_see_their_own_records(self):
        self.store.create_military_account(
            self.admin, MILITARY_COMPONENTS[0], "guardia", TEMPORARY,
        )
        self.store.create_military_account(
            self.admin, MILITARY_COMPONENTS[1], "ejercito", TEMPORARY,
        )
        users = self.store.users(self.admin)
        first_user = next(user for user in users if user["username"] == "guardia")
        second_user = next(user for user in users if user["username"] == "ejercito")
        first = self.store.login("guardia", TEMPORARY)
        second = self.store.login("ejercito", TEMPORARY)
        self.store.add_military_record(
            first, "TTE", "Persona Uno", "V-12345678", "2000-10-28",
            "2026-10-28", "Muerte natural", "REDI Capital", "ZODI A", "Unidad A",
        )
        self.store.add_military_record(
            second, "TTE", "Persona Dos", "V-87654321", "2000-10-29",
            "2026-10-29", "Muerte natural", "REDI Central", "ZODI B", "Unidad B",
        )

        self.assertEqual(self.store.centers(first), [])
        self.assertEqual(
            [row["full_name"] for row in self.store.military_records(first)],
            ["PERSONA UNO"],
        )
        self.assertEqual(
            [row["full_name"] for row in self.store.military_records(second)],
            ["PERSONA DOS"],
        )
        self.assertEqual(len(self.store.military_records(self.admin)), 2)
        self.assertEqual(
            self.store.military_records(self.admin)[0]["component"],
            MILITARY_COMPONENTS[1],
        )
        self.assertEqual(self.store.military_records(first)[0]["age"], 26)
        first_record = self.store.military_records(first)[0]
        self.assertEqual(first_record["full_name"], "PERSONA UNO")
        self.assertEqual(first_record["zodi"], "ZODI A")
        self.assertEqual(first_record["unit"], "UNIDAD A")
        with self.assertRaises(AccessError):
            self.store.military_records(self.center)
        with self.assertRaises(AccessError):
            self.store.inventory(first, self.north)
        with self.assertRaises(AccessError):
            self.store.report_snapshot(first)
        with self.assertRaises(InventoryError):
            self.store.create_military_account(
                self.admin, MILITARY_COMPONENTS[0], "otro", TEMPORARY,
            )
        with self.assertRaises(InventoryError):
            self.store.add_military_record(
                first, "TTE", "Nombre", "V-1", "2000-01-01",
                "1999-12-31", "Muerte natural", "REDI Capital", "ZODI", "Unidad",
            )
        valid_record = [
            "TTE", "Nombre", "V-1", "2000-01-01", "2020-01-01",
            "Muerte natural", "REDI Capital", "ZODI", "Unidad",
        ]
        for field_index, invalid_value in ((0, "XX"), (5, "Otra causa"), (6, "REDI Norte")):
            invalid_record = valid_record.copy()
            invalid_record[field_index] = invalid_value
            with self.subTest(field=field_index), self.assertRaises(InventoryError):
                self.store.add_military_record(first, *invalid_record)
        self.assertNotIn(
            first_user["center_id"],
            {center["id"] for center, _ in self.store.report_snapshot(self.admin)},
        )
        self.assertNotIn(
            second_user["center_id"],
            {row["N°"] for row in self.store.summary(self.admin)},
        )

    def test_health_death_registry_enforces_scope_and_retains_center_and_component(self):
        self.store.create_military_account(
            self.admin, MILITARY_COMPONENTS[0], "guardia", TEMPORARY,
        )
        military = self.store.login("guardia", TEMPORARY)
        values = (
            "TTE", "PERSONA DE PRUEBA", "V-1", "1990-01-01",
            "2026-10-15", "Muerte natural", "REDI Capital", "ZODI", "UNIDAD",
        )
        for component in (None, "", "Componente inexistente"):
            with self.subTest(component=component), self.assertRaises(InventoryError):
                self.store.add_military_record(self.center, *values, component=component)
        self.store.add_military_record(
            self.center, *values, component=MILITARY_COMPONENTS[2],
        )
        self.store.add_military_record(military, *values)
        for token, account_type in (
            (self.center, "military"), (military, "health"),
        ):
            with self.subTest(account_type=account_type), self.assertRaises(AccessError):
                self.store.military_records(token, account_type=account_type)
        south = self.store.login("sur", TEMPORARY)
        self.assertEqual(self.store.military_records(south, account_type="health"), [])
        restored = Store(self.store.path)
        rows = restored.military_records(self.center, account_type="health")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["center_name"], "Centro Norte")
        self.assertEqual(rows[0]["component"], MILITARY_COMPONENTS[2])
        self.assertEqual(len(restored.military_records(self.admin)), 1)
        self.assertEqual(len(restored.military_records(self.admin, account_type="health")), 1)

    def test_inventory_creation_update_and_persistence(self):
        self.store.save_quantity(self.center, self.north, "Camas", "UCI", 10, 2)
        self.store.save_quantity(self.center, self.north, "Vehículos", "Ambulancia", 2, 1)
        for category in ("Banco de sangre", "Laboratorio", "Quirófano"):
            self.store.save_facility(self.center, self.north, category, category, "General", "Operativo")
        self.store.save_equipment(self.center, self.north, "MON-01", "Monitor", "Marca", "Modelo", "Serie", "Operativo")
        inventory = self.store.inventory(self.admin, self.north)
        self.assertEqual(len(inventory["quantities"]), 2)
        self.assertEqual(len(inventory["facilities"]), 3)
        self.assertEqual(len(inventory["equipment"]), 1)
        quantity_id = inventory["quantities"][0]["id"]
        facility_id = inventory["facilities"][0]["id"]
        equipment_id = inventory["equipment"][0]["id"]
        self.store.save_quantity(self.center, self.north, "Camas", "UCI", 9, 3, quantity_id)
        self.store.save_facility(self.center, self.north, "Banco de sangre", "Banco", "General", "Fuera de servicio", facility_id)
        self.store.save_equipment(self.center, self.north, "MON-01", "Monitor", "Marca", "Modelo", "Serie", "Fuera de servicio", equipment_id)
        restored = Store(self.store.path).inventory(self.center, self.north)
        self.assertEqual(restored["quantities"][0]["operational"], 9)
        self.assertEqual(restored["facilities"][0]["state"], "Fuera de servicio")
        self.assertEqual(restored["equipment"][0]["state"], "Fuera de servicio")

    def test_ambulance_submission_saves_every_type_and_rejects_incomplete_types(self):
        quantities = {kind: (0, 0) for kind in AMBULANCE_TYPES}
        with self.assertRaises(InventoryError):
            self.store.save_ambulances_and_submit(
                self.center, self.north, {kind: (0, 0) for kind in AMBULANCE_TYPES[:-1]},
            )
        self.assertEqual(
            self.store.save_ambulances_and_submit(self.center, self.north, quantities), [],
        )
        rows = self.store.inventory(self.center, self.north)["quantities"]
        self.assertEqual(
            {row["kind"]: (row["operational"], row["unavailable"]) for row in rows},
            {kind: (0, 0) for kind in AMBULANCE_TYPES},
        )
        self.assertEqual(self.store.submission(self.center, self.north)["status"], REPORT_LOADED)
        with self.assertRaises(InventoryError):
            self.store.save_ambulances_and_submit(self.center, self.north, quantities)

    def test_all_inventory_categories_save_quantities_and_submit(self):
        from store import INVENTORY_QUANTITIES, SPECIAL_EQUIPMENT_TYPES

        self.store.save_category_quantities(
            self.center, self.north, "Equipos médicos especiales",
            {kind: (0, 0) for kind in SPECIAL_EQUIPMENT_TYPES},
        )

        self.store.save_equipment(
            self.center, self.north, "MON-01", "Monitor", "Marca", "Modelo", "Serie", "Operativo",
        )
        for category, kinds in INVENTORY_QUANTITIES.items():
            values = {kind: (0, 0) for kind in kinds}
            missing = self.store.save_category_quantities_and_submit(
                self.center, self.north, category, values,
            )
        self.assertEqual(missing, [])
        inventory = self.store.inventory(self.center, self.north)
        for category, kinds in INVENTORY_QUANTITIES.items():
            rows = (
                inventory["plant_counts"] if category == "Plantas eléctricas"
                else inventory["quantities"] if category in ("Camas", "Ambulancias", "Vehículos protocolares")
                else inventory["facility_counts"]
            )
            expected_category = (
                "Camas" if category == "Camas"
                else "Vehículos" if category in ("Ambulancias", "Vehículos protocolares")
                else category
            )
            actual = {
                row["kind"]: (row["operational"], row["unavailable"])
                for row in rows if row["category"] == expected_category
                and row["kind"] in kinds
            }
            self.assertEqual(actual, {kind: (0, 0) for kind in kinds})
        self.assertEqual(self.store.submission(self.center, self.north)["status"], REPORT_LOADED)

    def test_save_category_quantities_is_atomic_and_does_not_submit(self):
        values = {kind: (0, 0) for kind in BED_TYPES}
        values["UCI"] = (5, 2)
        self.store.save_category_quantities(self.center, self.north, "Camas", values)
        restored = Store(self.store.path)
        rows = restored.inventory(self.center, self.north)["quantities"]
        self.assertEqual(len(rows), len(BED_TYPES))
        self.assertEqual(
            {row["kind"]: (row["operational"], row["unavailable"]) for row in rows},
            values,
        )
        self.assertFalse(restored.submission(self.center, self.north)["loaded"])
        for invalid in (
            {"UCI": (1, 0)},
            {**values, "UCI": (-1, 0)},
            {**values, "UCI": (1.5, 0)},
            {**values, "UCI": (1_000_001, 0)},
            {**values, "UCI": (True, 0)},
            {**values, "Desconocido": (1, 0)},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(InventoryError):
                self.store.save_category_quantities(self.center, self.north, "Camas", invalid)
            self.assertEqual(self.store.inventory(self.center, self.north)["quantities"], rows)
        for token, center_id in ((self.admin, self.north), (self.center, self.south)):
            with self.subTest(center_id=center_id), self.assertRaises(AccessError):
                self.store.save_category_quantities(token, center_id, "Camas", values)
        self.clock.return_value = datetime(
            2026, 10, 31, 0, tzinfo=REPORT_TIMEZONE,
        ).timestamp()
        token = self.store.login("norte", CHANGED)
        self.store.save_category_quantities(token, self.north, "Camas", values)
        self.assertFalse(self.store.submission(token, self.north)["loaded"])
        self.clock.return_value = datetime(
            2026, 11, 5, 12, tzinfo=REPORT_TIMEZONE,
        ).timestamp()
        token = self.store.login("norte", CHANGED)
        self.store.submit(token, self.north)
        with self.assertRaises(InventoryError):
            self.store.save_category_quantities(token, self.north, "Camas", values)

    def test_combined_vehicles_require_all_types_and_preserve_counts_without_submitting(self):
        from store import VEHICLE_TYPES

        values = {kind: (index, index + 1) for index, kind in enumerate((*AMBULANCE_TYPES, *VEHICLE_TYPES))}
        self.store.save_quantity(self.center, self.north, "Vehículos", "Motos", 9, 3)
        for invalid in (
            {kind: pair for kind, pair in values.items() if kind != "Motos"},
            {**values, "Motos": (-1, 0)},
            {**values, "Desconocido": (1, 0)},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(InventoryError):
                self.store.save_category_quantities(self.center, self.north, "Vehículos", invalid)
            rows = self.store.inventory(self.center, self.north)["quantities"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["operational"], 9)
        self.store.save_category_quantities(self.center, self.north, "Vehículos", values)
        rows = Store(self.store.path).inventory(self.center, self.north)["quantities"]
        self.assertEqual({row["category"] for row in rows}, {"Vehículos"})
        self.assertEqual(
            {row["kind"]: (row["operational"], row["unavailable"]) for row in rows}, values,
        )
        self.assertFalse(self.store.submission(self.center, self.north)["loaded"])
        for token, center_id in ((self.admin, self.north), (self.center, self.south)):
            with self.assertRaises(AccessError):
                self.store.save_category_quantities(token, center_id, "Vehículos", values)

    def test_special_laboratories_validation_atomicity_permissions_and_removal(self):
        values = {"Laboratorio": (1, 0), "Laboratorio de emergencia": (0, 0)}
        laboratory = {"slot": 1, "name": "Microbiología", "state": "Operativo"}
        self.store.save_laboratories(self.center, self.north, values, True, [laboratory])
        rows = Store(self.store.path).inventory(self.center, self.north)["special_laboratories"]
        self.assertEqual(rows[0]["name"], "MICROBIOLOGÍA")
        self.assertEqual(self.store.summary(self.admin)[0]["Laboratorios"], 2)
        for invalid in (
            [], [dict(laboratory, name=" ")], [dict(laboratory, state="Desconocido")],
            [dict(laboratory, slot=4)], [laboratory, dict(laboratory, slot=2)],
            [laboratory, dict(laboratory, name="Otro")],
            [dict(laboratory, slot=slot, name=str(slot)) for slot in range(1, 5)],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(InventoryError):
                self.store.save_laboratories(self.center, self.north, values, True, invalid)
            self.assertEqual(self.store.inventory(self.center, self.north)["special_laboratories"], rows)
        for token, center_id in ((self.admin, self.north), (self.center, self.south)):
            with self.assertRaises(AccessError):
                self.store.save_laboratories(token, center_id, values, True, [laboratory])
        self.store.save_laboratories(self.center, self.north, values, False, [])
        self.assertFalse(self.store.inventory(self.center, self.north)["special_laboratories"])
        self.store.submit(self.center, self.north)
        with self.assertRaises(InventoryError):
            self.store.save_laboratories(self.center, self.north, values, True, [laboratory])

    def test_old_combined_vehicles_are_preserved_unassigned_and_require_new_separation(self):
        from store import VEHICLE_TYPES

        values = {kind: (0, 0) for kind in (*AMBULANCE_TYPES, *VEHICLE_TYPES)}
        self.store.load_section(self.center, self.north, "Vehículos", values)
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO quantities(center_id, category, kind, operational, unavailable) VALUES(?, 'Vehículos', ?, ?, ?)",
                (self.north, "Carga pesada / autobús", 8, 3),
            )
        restored = Store(self.store.path)
        inventory = restored.inventory(self.center, self.north)
        self.assertEqual(len(inventory["vehicle_history"]), 1)
        history = inventory["vehicle_history"][0]
        self.assertEqual((history["operational"], history["unavailable"]), (8, 3))
        self.assertFalse(any(row["kind"] == "Carga pesada / autobús" for row in inventory["quantities"]))
        self.assertFalse(restored.section_loads(self.center, self.north)["Vehículos"])
        self.assertEqual(restored.summary(self.admin)[0]["Vehículos"], 0)
        self.assertEqual(
            Store(self.store.path).inventory(self.center, self.north)["vehicle_history"],
            inventory["vehicle_history"],
        )
        values["Carga pesada (camiones y gandolas)"] = (5, 1)
        values["Transporte de personal (autobús, van y minivan)"] = (3, 2)
        restored.load_section(self.center, self.north, "Vehículos", values)
        self.assertEqual(restored.summary(self.admin)[0]["Vehículos"], 11)
        self.assertTrue(restored.section_loads(self.center, self.north)["Vehículos"])
        self.assertEqual(restored.inventory(self.center, self.north)["vehicle_history"], inventory["vehicle_history"])

    def test_plants_are_moved_out_of_equipment_without_losing_counts(self):
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO equipment_counts(center_id, category, kind, operational, unavailable) VALUES(?, ?, ?, ?, ?)",
                (self.north, "Equipos médicos especiales", "Plantas eléctricas", 4, 2),
            )
        restored = Store(self.store.path)
        inventory = restored.inventory(self.center, self.north)
        self.assertFalse(inventory["equipment_counts"])
        self.assertEqual(
            (inventory["plant_counts"][0]["operational"], inventory["plant_counts"][0]["unavailable"]), (4, 2),
        )
        with self.assertRaises(AccessError):
            restored.save_category_quantities(
                self.center, self.south, "Plantas eléctricas", {"Plantas eléctricas": (1, 0)},
            )
        with self.assertRaises(InventoryError):
            restored.save_category_quantities(
                self.center, self.north, "Plantas eléctricas", {"Plantas eléctricas": (-1, 0)},
            )
        self.assertEqual(Store(self.store.path).inventory(self.center, self.north)["plant_counts"], inventory["plant_counts"])

    def test_loaded_sections_lock_edit_reload_and_reset_each_week(self):
        from store import INVENTORY_QUANTITIES, REPORT_SECTIONS, SPECIAL_EQUIPMENT_TYPES

        values = {kind: (0, 0) for kind in BED_TYPES}
        self.store.load_section(self.center, self.north, "Camas", values)
        restored = Store(self.store.path)
        self.assertTrue(restored.section_loads(self.center, self.north)["Camas"])
        for operation in (
            lambda: restored.load_section(self.center, self.north, "Camas", values),
            lambda: restored.save_category_quantities(self.center, self.north, "Camas", values),
            lambda: restored.save_quantity(self.center, self.north, "Camas", "UCI", 1, 0),
        ):
            with self.assertRaisesRegex(InventoryError, "EDITAR"):
                operation()
        with self.assertRaises(AccessError):
            restored.edit_section(self.center, self.south, "Camas")
        with self.assertRaises(AccessError):
            restored.edit_section(self.admin, self.north, "Camas")
        restored.edit_section(self.center, self.north, "Camas")
        self.assertFalse(restored.section_loads(self.center, self.north)["Camas"])
        values["UCI"] = (4, 1)
        restored.load_section(self.center, self.north, "Camas", values)
        for section in REPORT_SECTIONS:
            if section == "Camas":
                continue
            if section == "Laboratorio":
                restored.load_laboratories(
                    self.center, self.north,
                    {kind: (0, 0) for kind in INVENTORY_QUANTITIES[section]}, False, [],
                )
            else:
                kinds = (
                    (*AMBULANCE_TYPES, *INVENTORY_QUANTITIES["Vehículos protocolares"])
                    if section == "Vehículos" else SPECIAL_EQUIPMENT_TYPES
                    if section == "Equipos médicos especiales" else INVENTORY_QUANTITIES[section]
                )
                restored.load_section(self.center, self.north, section, {kind: (0, 0) for kind in kinds})
        restored.edit_section(self.center, self.north, "Laboratorio")
        with self.assertRaises(InventoryError):
            restored.submit(self.center, self.north, require_all_categories=True, require_loaded_sections=True)
        restored.load_laboratories(
            self.center, self.north, {kind: (0, 0) for kind in INVENTORY_QUANTITIES["Laboratorio"]}, False, [],
        )
        restored.submit(self.center, self.north, require_all_categories=True, require_loaded_sections=True)
        with self.assertRaisesRegex(InventoryError, REPORT_LOADED):
            restored.edit_section(self.center, self.north, "Camas")
        self.clock.return_value = datetime(2026, 11, 5, 12, tzinfo=REPORT_TIMEZONE).timestamp()
        token = restored.login("norte", CHANGED)
        self.assertFalse(any(restored.section_loads(token, self.north).values()))
        with self.assertRaises(InventoryError):
            restored.submit(token, self.north, require_all_categories=True, require_loaded_sections=True)
        restored.load_section(token, self.north, "Camas", values)
        self.assertTrue(restored.section_loads(token, self.north)["Camas"])

    def test_equipment_counts_validate_all_types_and_preserve_history(self):
        from store import SPECIAL_EQUIPMENT_TYPES

        self.store.save_equipment(self.center, self.north, "OLD-1", "Monitor", "Marca", "Modelo", "Serie", "Operativo")
        values = {kind: (0, 0) for kind in SPECIAL_EQUIPMENT_TYPES}
        values["Tomógrafo"] = (5, 2)
        for invalid in (
            {"Tomógrafo": (1, 0)},
            {**values, "Otro": (1, 0)},
            {**values, "Tomógrafo": (-1, 0)},
            {**values, "Tomógrafo": (1.5, 0)},
            {**values, "Tomógrafo": (True, 0)},
            {**values, "Tomógrafo": (1_000_001, 0)},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(InventoryError):
                self.store.save_category_quantities(self.center, self.north, "Equipos médicos especiales", invalid)
            self.assertFalse(self.store.inventory(self.center, self.north)["equipment_counts"])
        self.store.save_category_quantities(self.center, self.north, "Equipos médicos especiales", values)
        inventory = Store(self.store.path).inventory(self.center, self.north)
        self.assertEqual(len(inventory["equipment_counts"]), len(SPECIAL_EQUIPMENT_TYPES))
        self.assertEqual(inventory["equipment"][0]["code"], "OLD-1")
        self.assertEqual(self.store.summary(self.admin)[0]["Equipos"], 7)
        self.assertFalse(self.store.submission(self.center, self.north)["loaded"])
        for token, center_id in ((self.admin, self.north), (self.center, self.south)):
            with self.assertRaises(AccessError):
                self.store.save_category_quantities(token, center_id, "Equipos médicos especiales", values)
        self.clock.return_value = datetime(2026, 10, 31, 0, tzinfo=REPORT_TIMEZONE).timestamp()
        token = self.store.login("norte", CHANGED)
        self.store.save_category_quantities(token, self.north, "Equipos médicos especiales", values)
        self.assertFalse(self.store.submission(token, self.north)["loaded"])
        self.clock.return_value = datetime(2026, 11, 5, 12, tzinfo=REPORT_TIMEZONE).timestamp()
        token = self.store.login("norte", CHANGED)
        values["Tomógrafo"] = (0, 0)
        self.store.save_category_quantities(token, self.north, "Equipos médicos especiales", values)
        admin = self.store.login("admin", PASSWORD)
        self.assertEqual(self.store.summary(admin)[0]["Equipos"], 0)
        self.store.submit(token, self.north)
        with self.assertRaises(InventoryError):
            self.store.save_category_quantities(token, self.north, "Equipos médicos especiales", values)

    def test_admin_manages_equipment_type_options_and_removal_preserves_records(self):
        self.store.add_equipment_type(self.admin, "Tomógrafo")
        self.assertIn("Tomógrafo", self.store.equipment_types(self.center))
        with self.assertRaises(AccessError):
            self.store.add_equipment_type(self.center, "Rayos X")
        with self.assertRaises(AccessError):
            self.store.remove_equipment_type(self.center, "Monitor")
        self.store.save_equipment(
            self.center, self.north, "TOM-01", "Tomógrafo", "Marca", "Modelo", "Serie", "Operativo",
        )
        self.store.remove_equipment_type(self.admin, "Tomógrafo")
        with self.assertRaises(InventoryError):
            self.store.save_equipment(
                self.center, self.north, "TOM-02", "Tomógrafo", "Marca", "Modelo", "Serie", "Operativo",
            )
        record = self.store.inventory(self.center, self.north)["equipment"][0]
        self.store.save_equipment(
            self.center, self.north, "TOM-01", "Tomógrafo", "Marca", "Modelo", "Serie",
            "Fuera de servicio", record["id"],
        )
        self.assertEqual(
            self.store.inventory(self.center, self.north)["equipment"][0]["state"],
            "Fuera de servicio",
        )

    def test_legacy_facilities_migrate_to_counts_without_losing_details(self):
        self.store.save_facility(
            self.center, self.north, "Banco de sangre", "Banco central", "General", "Operativo",
        )
        self.store.save_facility(
            self.center, self.north, "Laboratorio", "Lab principal", "General", "Fuera de servicio",
        )
        self.store.save_facility(
            self.center, self.north, "Quirófano", "Q1", "En emergencias", "Operativo",
        )
        restored = Store(self.store.path)
        inventory = restored.inventory(self.admin, self.north)
        self.assertEqual(len(inventory["facilities"]), 3)
        migrated = {
            (row["category"], row["kind"]): (row["operational"], row["unavailable"])
            for row in inventory["facility_counts"]
        }
        self.assertEqual(migrated[("Banco de sangre", "Banco de sangre")], (1, 0))
        self.assertEqual(migrated[("Laboratorio", "Laboratorio")], (0, 1))
        self.assertEqual(migrated[("Quirófano", "En emergencias")], (1, 0))
        self.assertEqual(restored.summary(self.admin)[0]["Bancos de sangre"], 1)
        self.assertEqual(restored.summary(self.admin)[0]["Laboratorios"], 1)
        self.assertEqual(restored.summary(self.admin)[0]["Quirófanos"], 1)

    def test_forged_record_ids_do_not_update_another_center(self):
        self.store.save_quantity(self.admin, self.south, "Camas", "General", 5, 0)
        self.store.save_facility(self.admin, self.south, "Laboratorio", "Lab", "General", "Operativo")
        self.store.save_equipment(self.admin, self.south, "E1", "Monitor", "Marca", "Modelo", "Serie", "Operativo")
        original = self.store.inventory(self.admin, self.south)
        operations = (
            lambda: self.store.save_quantity(self.center, self.north, "Camas", "General", 0, 5, original["quantities"][0]["id"]),
            lambda: self.store.save_facility(self.center, self.north, "Laboratorio", "Otro", "General", "Operativo", original["facilities"][0]["id"]),
            lambda: self.store.save_equipment(self.center, self.north, "E1", "Otro", "Marca", "Modelo", "Serie", "Operativo", original["equipment"][0]["id"]),
        )
        for operation in operations:
            with self.assertRaises(AccessError):
                operation()
        self.assertEqual(self.store.inventory(self.admin, self.south), original)

    def test_invalid_inputs_and_duplicates_are_rejected(self):
        for quantity in (-1, 1.5, True, 1_000_001):
            with self.assertRaises(InventoryError):
                self.store.save_quantity(self.center, self.north, "Camas", "General", quantity, 0)
        with self.assertRaises(InventoryError):
            self.store.save_quantity(self.center, self.north, "Otra", "General", 1, 0)
        with self.assertRaises(InventoryError):
            self.store.save_facility(self.center, self.north, "Laboratorio", "", "General", "Operativo")
        with self.assertRaises(InventoryError):
            self.store.save_equipment(self.center, self.north, "E1", "Monitor", "Marca", "Modelo", "Serie", "Inválido")
        self.store.save_quantity(self.center, self.north, "Camas", "General", 1, 0)
        with self.assertRaises(InventoryError):
            self.store.save_quantity(self.center, self.north, "Camas", "general", 2, 0)

    def test_incomplete_data_cannot_be_saved_or_submitted(self):
        for empty in ((" ", "Modelo", "Serie"), ("Marca", "", "Serie"), ("Marca", "Modelo", "")):
            with self.assertRaises(InventoryError):
                self.store.save_equipment(self.center, self.north, "E1", "Monitor", *empty, "Operativo")
        self.assertEqual(self.store.missing_data(self.center, self.north), ["Todavía no hay datos cargados."])
        with self.assertRaises(InventoryError):
            self.store.submit(self.center, self.north)
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO equipment(center_id,code,kind,brand,model,serial,state) "
                "VALUES(?,?,?,?,?,?,?)", (self.north, "OLD-1", "Monitor", "", "", "", "Operativo"),
            )
        self.assertEqual(
            self.store.missing_data(self.center, self.north),
            ["Todavía no hay datos cargados."],
        )
        with self.assertRaises(InventoryError):
            self.store.submit(self.center, self.north)
        equipment_id = self.store.inventory(self.center, self.north)["equipment"][0]["id"]
        self.store.save_equipment(self.center, self.north, "OLD-1", "Monitor", "Marca", "Modelo", "Serie", "Operativo", equipment_id)
        from store import SPECIAL_EQUIPMENT_TYPES
        self.store.save_category_quantities(
            self.center, self.north, "Equipos médicos especiales",
            {kind: (0, 0) for kind in SPECIAL_EQUIPMENT_TYPES},
        )
        self.assertEqual(self.store.missing_data(self.center, self.north), [])
        with self.assertRaises(AccessError):
            self.store.submit(self.admin, self.north)
        with self.assertRaises(AccessError):
            self.store.submit(self.center, self.south)
        self.store.submit(self.center, self.north)
        self.assertEqual(self.store.summary(self.admin)[0]["Estado"], REPORT_LOADED)
        self.assertEqual(self.store.summary(self.admin)[1]["Estado"], REPORT_PENDING)
        with self.assertRaisesRegex(InventoryError, REPORT_LOADED):
            self.store.save_quantity(self.center, self.north, "Camas", "UCI", 1, 0)

    def test_weekly_window_stays_open_all_week_while_schedule_is_disabled(self):
        cases = (
            "2026-10-26T03:59:59+00:00",
            "2026-10-26T04:00:00+00:00",
            "2026-10-29T03:59:59+00:00",
            "2026-10-29T04:00:00+00:00",
            "2026-10-31T03:59:59+00:00",
            "2026-10-31T04:00:00+00:00",
            "2026-10-31T12:00:00+00:00",
            "2026-11-02T03:59:59+00:00",
            "2026-11-02T04:00:00+00:00",
            "2026-11-05T04:00:00+00:00",
            "2027-01-01T21:59:59+00:00",
            "2027-01-02T03:59:59+00:00",
            "2027-01-02T04:00:00+00:00",
        )
        for date in cases:
            with self.subTest(date=date):
                status = weekly_status(0, datetime.fromisoformat(date).timestamp())
                self.assertTrue(status["open"])
                self.assertTrue(status["editable"])
                self.assertEqual(status["status"], REPORT_PENDING)

    def test_submission_locks_every_write_and_persists_until_next_monday(self):
        self.store.save_quantity(self.center, self.north, "Camas", "UCI", 1, 0)
        self.store.save_facility(self.center, self.north, "Laboratorio", "Lab", "General", "Operativo")
        self.store.save_equipment(self.center, self.north, "E1", "Monitor", "Marca", "Modelo", "Serie", "Operativo")
        original = self.store.inventory(self.center, self.north)
        self.store.submit(self.center, self.north)
        submitted_at = self.store.submission(self.center, self.north)["submitted_at"]
        operations = (
            lambda: self.store.submit(self.center, self.north),
            lambda: self.store.save_quantity(self.center, self.north, "Camas", "UCI", 2, 0, original["quantities"][0]["id"]),
            lambda: self.store.save_quantity(self.center, self.north, "Camas", "Otra", 2, 0),
            lambda: self.store.save_facility(self.center, self.north, "Laboratorio", "Lab", "General", "Fuera de servicio", original["facilities"][0]["id"]),
            lambda: self.store.save_facility(self.center, self.north, "Laboratorio", "Otro", "General", "Operativo"),
            lambda: self.store.save_equipment(self.center, self.north, "E1", "Monitor", "Marca", "Modelo", "Serie", "Fuera de servicio", original["equipment"][0]["id"]),
            lambda: self.store.save_equipment(self.center, self.north, "E2", "Monitor", "Marca", "Modelo", "Serie", "Operativo"),
        )
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaisesRegex(InventoryError, REPORT_LOADED):
                operation()
        self.assertEqual(self.store.inventory(self.center, self.north), original)
        self.assertEqual(Store(self.store.path).submission(self.center, self.north)["submitted_at"], submitted_at)
        for date, loaded in (
            ("2026-11-01T23:59:59-04:00", True),
            ("2026-11-02T00:00:00-04:00", False),
        ):
            self.clock.return_value = datetime.fromisoformat(date).timestamp()
            self.center = self.store.login("norte", CHANGED)
            self.admin = self.store.login("admin", PASSWORD)
            status = self.store.submission(self.center, self.north)
            self.assertEqual(status["loaded"], loaded)
            self.assertEqual(status["editable"], not loaded)
            self.assertEqual(self.store.summary(self.admin)[0]["Estado"], status["status"])
        self.clock.return_value = datetime.fromisoformat("2026-11-05T00:00:00-04:00").timestamp()
        self.center = self.store.login("norte", CHANGED)
        self.admin = self.store.login("admin", PASSWORD)
        self.store.save_quantity(self.center, self.north, "Camas", "UCI", 2, 0, original["quantities"][0]["id"])
        self.store.submit(self.center, self.north)
        self.assertEqual(self.store.summary(self.admin)[0]["Estado"], REPORT_LOADED)

    def test_outside_window_allows_all_writes_and_submission(self):
        self.store.save_quantity(self.center, self.north, "Camas", "UCI", 1, 0)
        self.store.save_facility(self.center, self.north, "Laboratorio", "Lab", "General", "Operativo")
        self.store.save_equipment(self.center, self.north, "E1", "Monitor", "Marca", "Modelo", "Serie", "Operativo")
        for index, date in enumerate((
            "2026-10-31T00:00:00-04:00", "2026-11-01T23:59:59-04:00",
            "2026-11-02T00:00:00-04:00", "2026-11-04T23:59:59-04:00",
        )):
            self.clock.return_value = datetime.fromisoformat(date).timestamp()
            self.center = self.store.login("norte", CHANGED)
            status = self.store.submission(self.center, self.north)
            self.assertTrue(status["open"])
            self.assertTrue(status["editable"])
            self.store.save_quantity(self.center, self.north, "Camas", f"Otra {index}", 1, 0)
        self.store.submit(self.center, self.north)
        self.assertEqual(self.store.submission(self.center, self.north)["status"], REPORT_LOADED)

    def test_concurrent_weekly_submissions_only_accept_one(self):
        self.store.save_quantity(self.center, self.north, "Camas", "UCI", 1, 0)

        def submit():
            try:
                self.store.submit(self.center, self.north)
            except InventoryError as error:
                return str(error)
            return "accepted"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: submit(), range(2)))
        self.assertEqual(results.count("accepted"), 1)
        self.assertEqual(sum(REPORT_LOADED in result for result in results), 1)

    def test_new_account_accesses_data_without_changing_password(self):
        token = self.store.login("sur", TEMPORARY)
        self.assertFalse(self.store.identity(token)["must_change"])
        self.assertEqual(self.store.centers(token)[0]["id"], self.south)
        self.store.inventory(token, self.south)
        self.store.change_password(token, TEMPORARY, CHANGED)
        with self.assertRaises(AccessError):
            self.store.identity(token)

    def test_reset_disable_and_logout_revoke_access(self):
        north_user = next(user for user in self.store.users(self.admin) if user["username"] == "norte")
        self.store.manage_user(self.admin, north_user["id"], True, TEMPORARY)
        with self.assertRaises(AccessError):
            self.store.inventory(self.center, self.north)
        token = self.store.login("norte", TEMPORARY)
        self.assertFalse(self.store.identity(token)["must_change"])
        self.store.manage_user(self.admin, north_user["id"], False)
        with self.assertRaises(AccessError):
            self.store.identity(token)
        with self.assertRaises(AccessError):
            self.store.login("norte", TEMPORARY)
        self.store.logout(self.admin)
        with self.assertRaises(AccessError):
            self.store.centers(self.admin)

    def test_idle_and_absolute_expiration_and_lockout(self):
        now = 100_000
        with patch("store.time.time", return_value=now):
            token = self.store.login("admin", PASSWORD)
        with patch("store.time.time", return_value=now + IDLE_SECONDS):
            with self.assertRaises(AccessError):
                self.store.identity(token)
        with patch("store.time.time", return_value=now + SESSION_SECONDS):
            with self.assertRaises(AccessError):
                self.store.identity(token)
        for _ in range(5):
            with self.assertRaises(AccessError):
                self.store.login("admin", "incorrect-password")
        with self.assertRaises(AccessError):
            self.store.login("admin", PASSWORD)

    def test_center_creation_rolls_back_when_username_is_taken(self):
        with self.assertRaises(InventoryError):
            self.store.create_center(self.admin, "Nuevo", "", "norte", TEMPORARY)
        self.assertEqual(len(self.store.centers(self.admin)), 2)

    def test_more_than_35_centers_can_be_created_concurrently(self):
        with self.store.connect() as connection:
            connection.executemany(
                "INSERT INTO centers(name) VALUES(?)",
                [(f"Centro {index}",) for index in range(34)],
            )
        def create(index):
            try:
                self.store.create_center(self.admin, f"Último {index}", "", f"ultimo{index}", TEMPORARY)
            except InventoryError:
                return False
            return True
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(create, range(2))), 2)
        self.assertEqual(len(self.store.centers(self.admin)), 38)

    def test_admin_can_edit_center_without_losing_inventory_or_weekly_status(self):
        self.store.save_quantity(self.center, self.north, "Camas", "UCI", 4, 1)
        self.store.submit(self.center, self.north)
        original = self.store.inventory(self.center, self.north)
        submitted_at = self.store.submission(self.center, self.north)["submitted_at"]
        self.store.update_center(self.admin, self.north, "Nuevo nombre", "Nueva ubicación", "  NUEVO.USUARIO ")
        with self.assertRaises(AccessError):
            self.store.identity(self.center)
        with self.assertRaises(AccessError):
            self.store.login("norte", CHANGED)
        token = self.store.login("nuevo.usuario", CHANGED)
        self.assertEqual(self.store.inventory(token, self.north), original)
        center = self.store.centers(token)[0]
        self.assertEqual(center["id"], self.north)
        self.assertEqual(center["name"], "Nuevo nombre")
        self.assertEqual(center["location"], "Nueva ubicación")
        self.assertEqual(center["assigned_username"], "nuevo.usuario")
        self.assertEqual(self.store.submission(token, self.north)["submitted_at"], submitted_at)
        self.assertEqual(self.store.summary(self.admin)[0]["N°"], self.north)
        restored = Store(self.store.path)
        self.assertEqual(restored.centers(token)[0], center)
        self.store.update_center(self.admin, self.north, "Otro nombre", "", "nuevo.usuario")
        self.assertEqual(self.store.identity(token)["center_id"], self.north)

    def test_center_edits_require_admin_and_rollback_on_conflicts(self):
        original = self.store.centers(self.admin)
        operations = (
            lambda: self.store.update_center(self.center, self.north, "Otro", "", "otro"),
            lambda: self.store.update_center(self.center, self.south, "Otro", "", "otro"),
        )
        for operation in operations:
            with self.assertRaises(AccessError):
                operation()
        for name, username in (("", "otro"), ("Otro", "no valido"), ("Centro Sur", "otro"), ("Otro", "sur"), ("Otro", "admin")):
            with self.subTest(name=name, username=username), self.assertRaises(InventoryError):
                self.store.update_center(self.admin, self.north, name, "", username)
            self.assertEqual(self.store.centers(self.admin), original)
        with self.assertRaises(InventoryError):
            self.store.update_center(self.admin, 999, "Otro", "", "otro")
        self.assertEqual(self.store.identity(self.center)["center_id"], self.north)

    def test_catalog_center_can_be_edited_without_creating_access_account(self):
        self.store.import_centers(self.admin, load_center_catalog()[:2])
        center, other = self.store.centers(self.admin)[-2:]
        with self.assertRaises(InventoryError):
            self.store.update_center(self.admin, center["id"], "Nuevo", "", other["assigned_username"])
        self.store.update_center(self.admin, center["id"], "Nuevo", "", center["assigned_username"])
        self.assertEqual(self.store.centers(self.admin)[-2]["name"], "Nuevo")
        self.assertEqual(len(self.store.users(self.admin)), 2)

    def test_catalog_center_account_creation_validates_access_and_conflicts(self):
        self.store.import_centers(self.admin, load_center_catalog()[:2])
        center = self.store.centers(self.admin)[-2]
        with self.assertRaises(AccessError):
            self.store.create_account(self.center, center["id"], "nuevo", TEMPORARY)
        for center_id, username, password in (
            (999, "nuevo", TEMPORARY),
            (center["id"], "norte", TEMPORARY),
            (center["id"], "no valido", TEMPORARY),
            (center["id"], "nuevo", "short"),
        ):
            with self.subTest(center_id=center_id, username=username, password=password):
                with self.assertRaises(InventoryError):
                    self.store.create_account(self.admin, center_id, username, password)
        self.assertEqual(len(self.store.users(self.admin)), 2)
        self.store.create_account(self.admin, center["id"], "  NUEVO ", TEMPORARY)
        with self.assertRaises(InventoryError):
            self.store.create_account(self.admin, center["id"], "otro", TEMPORARY)
        token = self.store.login("nuevo", TEMPORARY)
        self.assertFalse(self.store.identity(token)["must_change"])
        self.assertEqual(self.store.identity(token)["center_id"], center["id"])

    def test_unknown_session_never_reads_data(self):
        with self.assertRaises(AccessError):
            self.store.centers("invented-token")

    def test_admin_summary_counts_without_multiplying_joined_rows(self):
        self.store.save_quantity(self.admin, self.north, "Camas", "General", 10, 2)
        self.store.save_quantity(self.admin, self.north, "Camas", "UCI", 3, 1)
        self.store.save_quantity(self.admin, self.north, "Vehículos", "Ambulancia", 1, 1)
        for category in ("Banco de sangre", "Laboratorio", "Quirófano"):
            self.store.save_facility(self.admin, self.north, category, category, "General", "Operativo")
        for code in ("E1", "E2"):
            self.store.save_equipment(self.admin, self.north, code, "Monitor", "Marca", "Modelo", "Serie", "Operativo")
        summary = self.store.summary(self.admin)
        self.assertEqual(summary[0], {
            "N°": self.north, "Centro": "Centro Norte", "Estado": REPORT_PENDING, "Camas": 16, "Vehículos": 2,
            "Bancos de sangre": 1, "Laboratorios": 1, "Quirófanos": 1, "Equipos": 0, "Plantas eléctricas": 0,
        })
        self.assertEqual(summary[1]["Camas"], 0)
        self.assertEqual(summary[1]["Equipos"], 0)

    def test_pdf_catalog_import_is_idempotent_and_creates_no_access_accounts(self):
        store = Store(self.store.path.with_name("catalog.sqlite3"))
        store.bootstrap("admin", PASSWORD)
        token = store.login("admin", PASSWORD)
        catalog = load_center_catalog()
        self.assertEqual(len(catalog), 34)
        self.assertEqual([row["number"] for row in catalog], list(range(1, 35)))
        self.assertEqual(store.import_centers(token, catalog), 34)
        centers = store.centers(token)
        self.assertEqual(len(centers), 34)
        self.assertEqual(len({center["assigned_username"] for center in centers}), 34)
        north = next(center for center in centers if center["assigned_username"] == "centro13@centro.mil.ve")
        self.assertEqual(north["location"], "PUERTO AYACUCHO, EDO. AMAZONAS")
        self.assertFalse(any(center["name"] == "MISION MILAGRA DIGESALUD" for center in centers))
        store.save_quantity(token, north["id"], "Camas", "UCI", 2, 0)
        self.assertEqual(store.import_centers(token, catalog), 0)
        self.assertEqual(store.inventory(token, north["id"])["quantities"][0]["operational"], 2)
        self.assertEqual(store.users(token), [])
        with self.assertRaises(AccessError):
            store.login(north["assigned_username"], PASSWORD)

    def test_bootstrap_catalog_loads_centers_once_without_accounts(self):
        store = Store(self.store.path.with_name("bootstrap_catalog.sqlite3"))
        store.bootstrap("admin", PASSWORD)
        token = store.login("admin", PASSWORD)
        catalog = load_center_catalog()
        store.bootstrap_catalog(catalog)
        self.assertEqual(len(store.centers(token)), len(catalog))
        self.assertEqual(store.users(token), [])
        store.bootstrap_catalog(catalog)
        store.create_center(token, "Centro Nuevo", "Norte", "nuevo", PASSWORD)
        store.bootstrap_catalog(catalog)
        self.assertEqual(len(store.centers(token)), len(catalog) + 1)

    def test_catalog_requires_admin_and_can_exceed_old_limit(self):
        with self.assertRaises(AccessError):
            self.store.import_centers(self.center, load_center_catalog()[:1])
        self.assertEqual(self.store.import_centers(self.admin, load_center_catalog()), 34)
        extra = {"number": 36, "center": "Centro adicional", "username": "extra@example.org"}
        self.assertEqual(self.store.import_centers(self.admin, [extra]), 1)
        self.assertEqual(len(self.store.centers(self.admin)), 37)

    def test_catalog_rejects_password_fields_duplicates_and_conflicts(self):
        catalog = load_center_catalog()
        for invalid in (
            [{**catalog[0], "password": "must-not-import"}],
            [catalog[0], catalog[0]],
            [catalog[0], {**catalog[1], "username": catalog[0]["username"]}],
            [{**catalog[0], "username": "invalid"}],
        ):
            with self.assertRaises(InventoryError):
                self.store.import_centers(self.admin, invalid)
        self.assertEqual(self.store.import_centers(self.admin, catalog[:1]), 1)
        with self.assertRaises(InventoryError):
            self.store.import_centers(self.admin, [{**catalog[0], "username": "another@example.org"}])
        self.assertEqual(len(self.store.centers(self.admin)), 3)

    def test_existing_database_gains_catalog_field_without_losing_data(self):
        old_path = self.store.path.with_name("old.sqlite3")
        with sqlite3.connect(old_path) as connection:
            connection.execute(
                "CREATE TABLE centers(id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, location TEXT NOT NULL DEFAULT '')",
            )
            connection.execute("INSERT INTO centers(name) VALUES('Centro anterior')")
        store = Store(old_path)
        store.bootstrap("admin", PASSWORD)
        token = store.login("admin", PASSWORD)
        center = store.centers(token)[0]
        self.assertEqual(center["name"], "Centro anterior")
        self.assertEqual(center["assigned_username"], "")


if __name__ == "__main__":
    unittest.main()
