import tempfile
import unittest
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pymupdf
from streamlit.testing.v1 import AppTest

import app as app_module
from store import (
    BED_TYPES, INVENTORY_QUANTITIES, REPORT_SECTIONS, SPECIAL_EQUIPMENT_TYPES, InventoryError,
    REPORT_LOADED, REPORT_PENDING, REPORT_TIMEZONE, Store, load_center_catalog,
)


APP = str(Path(__file__).resolve().parents[1] / "app.py")
PASSWORD = "Testing-admin-password-123"
TEMPORARY = "Testing-center-password-456"
INVENTORY_FORMS = ("quantity_", "facility_", "equipment_")


class AppTests(unittest.TestCase):
    def setUp(self):
        clock = patch("store.time.time", return_value=datetime(
            2026, 10, 29, 12, tzinfo=REPORT_TIMEZONE,
        ).timestamp())
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "test.sqlite3")
        self.patcher = patch("store.Store", return_value=self.store)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        environment = patch.dict(os.environ, {"SALUD_DEVELOPMENT_MODE": "0"})
        environment.start()
        self.addCleanup(environment.stop)

    def confirm_load(self, app, key):
        app.button(key=key).click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("¿Ha editado todos los campos?" in item.value for item in app.warning))
        self.assertEqual(app.button(key=key).label, "CONFIRMAR CARGA")
        app.button(key=key).click().run()

    def test_streamlit_secrets_bootstrap_admin_only_once(self):
        credentials = {"bootstrap_admin": {"username": "admin", "password": PASSWORD}}
        with patch.object(app_module.st, "secrets", credentials):
            app_module.bootstrap_from_secrets(self.store)
            self.assertTrue(self.store.initialized())
            token = self.store.login("admin", PASSWORD)
            self.assertEqual(self.store.identity(token)["role"], "admin")
            app_module.bootstrap_from_secrets(self.store)

    def test_streamlit_secrets_reject_invalid_bootstrap_configuration(self):
        with patch.object(app_module.st, "secrets", {"bootstrap_admin": "invalid"}):
            with self.assertRaisesRegex(InventoryError, "debe ser una tabla"):
                app_module.bootstrap_from_secrets(self.store)

    def test_streamlit_secrets_import_center_catalog_once(self):
        credentials = {"bootstrap_admin": {"username": "admin", "password": PASSWORD}}
        with patch.object(app_module.st, "secrets", credentials):
            app_module.bootstrap_from_secrets(self.store)
            token = self.store.login("admin", PASSWORD)
            catalog = load_center_catalog()
            centers = self.store.centers(token)
            self.assertEqual(len(centers), len(catalog))
            self.assertEqual(centers[0]["assigned_username"], "centro13@centro.mil.ve")
            self.assertFalse(self.store.users(token))
            app_module.bootstrap_from_secrets(self.store)
            self.assertEqual(len(self.store.centers(token)), len(catalog))

    def test_admin_creates_and_manages_center_account_from_same_app(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = admin
        app.run()
        app.radio(key="admin_page").set_value("Cuentas de centros").run()
        self.assertFalse(app.exception)
        app.text_input(key="account_center_name").set_value("Centro Nuevo")
        app.text_input(key="account_center_location").set_value("Norte")
        app.text_input(key="account_username").set_value("nuevo")
        app.text_input(key="account_password").set_value(TEMPORARY)
        app.text_input(key="account_confirmation").set_value("different")
        app.button(key="FormSubmitter:new_center-Crear centro y cuenta").click().run()
        self.assertTrue(any("no coinciden" in error.value for error in app.error))
        self.assertFalse(self.store.users(admin))
        for key, value in (
            ("account_center_name", "Centro Nuevo"), ("account_center_location", "Norte"),
            ("account_username", "nuevo"), ("account_password", TEMPORARY),
            ("account_confirmation", TEMPORARY),
        ):
            app.text_input(key=key).set_value(value)
        app.button(key="FormSubmitter:new_center-Crear centro y cuenta").click().run()
        self.assertFalse(app.exception)
        account = self.store.users(admin)[0]
        center = self.store.centers(admin)[0]
        token = self.store.login("nuevo", TEMPORARY)
        self.assertFalse(self.store.identity(token)["must_change"])
        center_app = AppTest.from_file(APP, default_timeout=30)
        center_app.session_state["token"] = token
        center_app.run()
        self.assertFalse(center_app.exception)
        self.assertFalse(any(item.key == "admin_page" for item in center_app.radio))
        self.assertFalse(any(field.type == "password" for field in center_app.text_input))
        self.assertEqual(self.store.centers(token), [center])
        self.assertTrue(any(button.key == "inventory_category_Camas" for button in center_app.button))
        form = next(form for form in app.get("form") if form.key == f"manage_user_{account['id']}")
        form.text_input[0].set_value("Centro Renombrado")
        form.text_input[1].set_value("Sur")
        app.button(key=f"FormSubmitter:manage_user_{account['id']}-Guardar datos").click().run()
        self.assertFalse(app.exception)
        renamed = self.store.centers(admin)[0]
        self.assertEqual(renamed["name"], "Centro Renombrado")
        self.assertEqual(renamed["location"], "Sur")
        app.button(key=f"deactivate_user_{account['id']}").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(self.store.users(admin)[0]["active"])
        app.button(key=f"activate_user_{account['id']}").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(self.store.users(admin)[0]["active"])
        app.text_input(key=f"account_password_{account['id']}").set_value(PASSWORD)
        app.text_input(key=f"account_confirmation_{account['id']}").set_value(PASSWORD)
        app.button(key=f"FormSubmitter:password_user_{account['id']}-Cambiar contraseña").click().run()
        self.assertFalse(app.exception)
        token = self.store.login("nuevo", PASSWORD)
        self.assertFalse(self.store.identity(token)["must_change"])

    def test_admin_creates_account_for_catalog_center_without_retyping_name(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.import_centers(admin, load_center_catalog()[:2])
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = admin
        app.run()
        app.radio(key="admin_page").set_value("Cuentas de centros").run()
        self.assertFalse(app.exception)
        app.selectbox(key="account_center_id").set_value(2)
        app.text_input(key="account_new_username").set_value("centro2")
        app.text_input(key="account_new_password").set_value(TEMPORARY)
        app.text_input(key="account_new_confirmation").set_value(TEMPORARY)
        app.button(key="FormSubmitter:new_account-Crear cuenta").click().run()
        self.assertFalse(app.exception)
        account = self.store.users(admin)[0]
        center = self.store.centers(admin)[1]
        self.assertEqual(account["username"], "centro2")
        self.assertEqual(account["center_id"], center["id"])
        self.assertEqual(account["center"], center["name"])
        self.assertEqual(account["location"], center["location"])
        token = self.store.login("centro2", TEMPORARY)
        self.assertFalse(self.store.identity(token)["must_change"])

    def test_center_unknown_category_displays_explicit_error(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.session_state["inventory_category"] = "Categoría desconocida"
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Categoría de inventario no válida" in error.value for error in app.error))
        app.button(key="inventory_category_Camas").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(app.number_input)

    def load_remaining_sections(self, token, center_id):
        inventory = self.store.inventory(token, center_id)
        existing = {
            (row["category"], row["kind"]): (row["operational"], row["unavailable"])
            for table in ("quantities", "facility_counts", "equipment_counts", "plant_counts")
            for row in inventory[table]
        }
        for section, loaded in self.store.section_loads(token, center_id).items():
            if loaded:
                continue
            kinds = (
                (*INVENTORY_QUANTITIES["Ambulancias"], *INVENTORY_QUANTITIES["Vehículos protocolares"])
                if section == "Vehículos" else SPECIAL_EQUIPMENT_TYPES
                if section == "Equipos médicos especiales" else INVENTORY_QUANTITIES[section]
            )
            values = {kind: existing.get((section, kind), (0, 0)) for kind in kinds}
            if section == "Laboratorio":
                laboratories = [
                    {key: row[key] for key in ("slot", "name", "state")}
                    for row in inventory["special_laboratories"]
                ]
                self.store.load_laboratories(token, center_id, values, bool(laboratories), laboratories)
            else:
                self.store.load_section(token, center_id, section, values)

    def test_zero_forms_require_loading_every_item_before_sending(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        for category in REPORT_SECTIONS:
            app.button(key=f"inventory_category_{category}").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(all(field.value == 0 for field in app.number_input))
            self.assertTrue(all(field.value == "No" for field in app.radio))
            self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
            load_key = {
                "Camas": "beds", "Vehículos": "vehicles", "Banco de sangre": "blood_bank",
                "Laboratorio": "laboratory", "Quirófano": "theatres",
                "Equipos médicos especiales": "equipment", "Plantas eléctricas": "plants",
            }[category]
            before = self.store.inventory(token, center_id)
            app.button(key=f"load_{load_key}_{center_id}").click().run()
            self.assertEqual(self.store.inventory(token, center_id), before)
            self.assertFalse(self.store.section_loads(token, center_id)[category])
            self.assertTrue(any("¿Ha editado todos los campos?" in item.value for item in app.warning))
            if category == "Camas":
                field_key = f"category_operational_{center_id}_Camas_0"
                app.number_input(key=field_key).set_value(1).run()
                self.assertEqual(app.button(key=f"load_{load_key}_{center_id}").label, "Cargar datos")
                app.number_input(key=field_key).set_value(0).run()
                app.button(key=f"load_{load_key}_{center_id}").click().run()
                app.button(key="inventory_category_Vehículos").click().run()
                app.button(key="inventory_category_Camas").click().run()
                self.assertEqual(app.button(key=f"load_{load_key}_{center_id}").label, "Cargar datos")
                app.button(key=f"load_{load_key}_{center_id}").click().run()
            app.button(key=f"load_{load_key}_{center_id}").click().run()
        self.assertFalse(self.store.submission(token, center_id)["loaded"])
        app.button(key="submit_inventory").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(self.store.submission(token, center_id)["loaded"])
        self.assertFalse(app.number_input)

    def test_send_button_requires_every_saved_item_and_is_available_in_every_section(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        button_style = next(
            item.value for item in app.get("html")
            if ".stFormSubmitButton button" in item.value
        )
        self.assertIn("text-transform: uppercase", button_style)
        self.assertIn("font-weight: 700", button_style)
        self.assertIn(".stButton button", button_style)
        self.assertIn(".stDownloadButton button", button_style)
        self.assertIn(".st-key-inventory_category_Camas button p", button_style)
        self.assertIn("white-space: normal", button_style)
        self.assertIn("height: auto", button_style)
        self.assertIn('[class*="st-key-report_confirmation_"]', button_style)
        self.assertIn("text-align: center", button_style)
        self.assertNotIn("background-color: #b91c1c", button_style)
        self.assertNotIn("background-color: #166534", button_style)
        pending = next(
            block for block in app.get("flex_container") if block.key == "report_pending"
        )
        self.assertEqual(pending.info[0].value, REPORT_PENDING)
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        self.assertFalse(any(self.store.section_loads(token, center_id).values()))
        categories = {**INVENTORY_QUANTITIES, "Equipos médicos especiales": SPECIAL_EQUIPMENT_TYPES}
        for category, kinds in categories.items():
            self.store.save_category_quantities(
                token, center_id, category, {kind: (0, 0) for kind in kinds},
            )
        for section in REPORT_SECTIONS:
            if section == "Laboratorio":
                self.store.load_laboratories(
                    token, center_id, {kind: (0, 0) for kind in INVENTORY_QUANTITIES[section]}, False, [],
                )
            else:
                kinds = (
                    (*INVENTORY_QUANTITIES["Ambulancias"], *INVENTORY_QUANTITIES["Vehículos protocolares"])
                    if section == "Vehículos" else SPECIAL_EQUIPMENT_TYPES
                    if section == "Equipos médicos especiales" else INVENTORY_QUANTITIES[section]
                )
                self.store.load_section(token, center_id, section, {kind: (0, 0) for kind in kinds})
        for table in ("quantities", "facility_counts", "equipment_counts", "plant_counts"):
            with self.store.connect() as connection:
                rows = [dict(row) for row in connection.execute(
                    f"SELECT * FROM {table} WHERE center_id=?", (center_id,),
                )]
            for row in rows:
                with self.subTest(table=table, kind=row["kind"]):
                    with self.store.transaction() as connection:
                        connection.execute(f"DELETE FROM {table} WHERE id=?", (row["id"],))
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertTrue(any(button.key == "submit_inventory" for button in app.button))
                    self.assertEqual(self.store.missing_inventory_categories(token, center_id), [])
        app.run()
        for category in (
            "Camas", "Vehículos", "Banco de sangre", "Laboratorio", "Quirófano",
            "Equipos médicos especiales", "Plantas eléctricas",
        ):
            app.button(key=f"inventory_category_{category}").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.button(key="submit_inventory").label, "ENVIAR A DIGESALUD-MPPD")
            self.assertTrue(any(button.key == f"edit_section_{center_id}_{category}" for button in app.button))
            self.assertFalse(app.number_input)
            self.assertFalse(app.radio)
        app.button(key=f"edit_section_{center_id}_Plantas eléctricas").click().run()
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        app.number_input(key=f"category_operational_{center_id}_Plantas eléctricas_0").set_value(2).run()
        self.confirm_load(app, f"load_plants_{center_id}")
        self.assertEqual(app.button(key="submit_inventory").label, "ENVIAR A DIGESALUD-MPPD")
        self.assertFalse(self.store.submission(token, center_id)["loaded"])
        app.button(key="submit_inventory").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(self.store.submission(token, center_id)["loaded"])
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        self.assertFalse(any((button.key or "").startswith("edit_section_") for button in app.button))
        self.assertTrue(any(REPORT_LOADED in item.value for item in app.success))
        self.assertTrue(any(
            item.value == (
                "SU REPORTE SEMANAL FUE ENVIADO A LA SALA SITUACIONAL DIGESALUD-MPPD, "
                "validar el mismo con el Director del Centro de Salud"
            )
            for item in app.success
        ))
        confirmation = next(
            block for block in app.get("flex_container")
            if block.key == "report_confirmation_status"
        )
        self.assertEqual(confirmation.success[0].value, REPORT_LOADED)

    def test_center_pdf_includes_only_selected_item(self):
        from report import SECTIONS

        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        self.load_remaining_sections(token, center_id)
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        for category, expected_titles, pages in (
            ("Camas", ("CAMAS HOSPITALARIAS",), 1),
            ("Vehículos", (
                "AMBULANCIAS", "VEHÍCULOS PROTOCOLARES",
                "CARGA PESADA (CAMIONES Y GANDOLAS)",
                "TRANSPORTE DE PERSONAL (AUTOBÚS, VAN Y MINIVAN)", "MOTOS",
            ), 5),
            ("Banco de sangre", ("BANCOS DE SANGRE",), 1),
            ("Laboratorio", ("LABORATORIOS",), 1),
            ("Quirófano", ("QUIRÓFANOS",), 1),
            ("Equipos médicos especiales", ("EQUIPOS MÉDICOS ESPECIALES",), 2),
            ("Plantas eléctricas", ("PLANTAS ELÉCTRICAS",), 1),
        ):
            with self.subTest(category=category):
                app.button(key=f"inventory_category_{category}").click().run()
                self.assertEqual(len(app.get("download_button")), 1)
                self.assertEqual(app.get("download_button")[0].label, "DESCARGAR PDF")
                self.assertFalse(any(
                    (button.key or "").startswith("generate_pdf_") for button in app.button
                ))
                self.assertFalse(app.exception)
                self.assertFalse(app.error)
                with pymupdf.open(
                    stream=app.session_state[f"_pdf_export_{center_id}"]["data"], filetype="pdf",
                ) as document:
                    self.assertEqual(len(document), pages)
                    text = "".join(page.get_text() for page in document)
                    for title in expected_titles:
                        self.assertIn(title, text)
                    for title, _groups in SECTIONS:
                        if title not in expected_titles:
                            self.assertNotIn(title, text)

    def test_bed_table_updates_totals_and_only_saves_when_loading(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        for category, kinds in INVENTORY_QUANTITIES.items():
            if category != "Camas":
                self.store.save_category_quantities(
                    token, center_id, category, {kind: (0, 0) for kind in kinds},
                )
        self.store.save_category_quantities(
            token, center_id, "Equipos médicos especiales",
            {kind: (0, 0) for kind in SPECIAL_EQUIPMENT_TYPES},
        )
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.button(key="inventory_category_Camas").label, "**CAMAS HOSPITALARIAS**")
        bed_heading = next(
            item.value for item in app.get("html")
            if ">CAMAS HOSPITALARIAS</div>" in item.value
        )
        self.assertIn("background-color: var(--primary-color, #147d78)", bed_heading)
        self.assertIn("color: #ffffff", bed_heading)
        self.assertEqual(len(app.number_input), 2 * len(BED_TYPES))
        for index, kind in enumerate(BED_TYPES):
            operational = app.number_input(key=f"category_operational_{center_id}_Camas_{index}")
            unavailable = app.number_input(key=f"category_unavailable_{center_id}_Camas_{index}")
            self.assertEqual(operational.label, f"Operativas: {kind}")
            self.assertEqual(unavailable.label, f"Inoperativas: {kind}")
            self.assertEqual((operational.value, unavailable.value), (0, 0))
            self.assertEqual(operational.proto.format, "%02d")
        app.number_input(key=f"category_operational_{center_id}_Camas_0").set_value(10).run()
        app.number_input(key=f"category_unavailable_{center_id}_Camas_0").set_value(2).run()
        app.number_input(key=f"category_operational_{center_id}_Camas_5").set_value(5).run()
        app.number_input(key=f"category_unavailable_{center_id}_Camas_5").set_value(1).run()
        self.assertFalse(app.exception)
        displayed = [item.value for item in app.markdown]
        self.assertIn("12", displayed)
        self.assertIn("06", displayed)
        for total in ("**15**", "**03**", "**18**"):
            self.assertIn(total, displayed)
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        self.assertTrue(all(
            row["operational"] == row["unavailable"] == 0
            for row in self.store.inventory(token, center_id)["quantities"]
            if row["category"] == "Camas"
        ))
        self.confirm_load(app, f"load_beds_{center_id}")
        self.assertFalse(app.exception)
        self.assertTrue(any("Inventario guardado" in item.value for item in app.success))
        beds = {
            row["kind"]: (row["operational"], row["unavailable"])
            for row in Store(self.store.path).inventory(token, center_id)["quantities"]
            if row["category"] == "Camas"
        }
        self.assertEqual(set(beds), set(BED_TYPES))
        self.assertEqual(beds["Hospitalización"], (10, 2))
        self.assertEqual(beds["UCI"], (5, 1))
        self.assertEqual(self.store.missing_inventory_categories(token, center_id), [])
        self.assertFalse(self.store.submission(token, center_id)["loaded"])
        self.assertTrue(self.store.submission(token, center_id)["editable"])
        app.button(key=f"edit_section_{center_id}_Camas").click().run()
        app.number_input(key=f"category_operational_{center_id}_Camas_0").set_value(0).run()
        self.confirm_load(app, f"load_beds_{center_id}")
        beds = [
            row for row in self.store.inventory(token, center_id)["quantities"]
            if row["category"] == "Camas"
        ]
        self.assertEqual(len(beds), len(BED_TYPES))
        self.assertEqual(next(row["operational"] for row in beds if row["kind"] == "Hospitalización"), 0)
        self.assertFalse(self.store.submission(token, center_id)["loaded"])

    def test_blood_bank_presence_and_state_save_without_submission(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.session_state["inventory_category"] = "Banco de sangre"
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.number_input)
        self.assertFalse(app.dataframe)
        self.assertEqual(len(app.radio), 1)
        self.assertEqual(
            app.get("download_button")[0].label,
            "DESCARGAR PDF",
        )
        self.confirm_load(app, f"load_blood_bank_{center_id}")
        self.assertFalse(app.error)
        for presence, state, expected in (
            ("Sí", "Operativo", (1, 0)),
            ("Sí", "Fuera de servicio", (0, 1)),
            ("No", None, (0, 0)),
        ):
            with self.subTest(presence=presence, state=state):
                if any(button.key == f"edit_section_{center_id}_Banco de sangre" for button in app.button):
                    app.button(key=f"edit_section_{center_id}_Banco de sangre").click().run()
                app.radio(key=f"blood_bank_presence_{center_id}").set_value(presence).run()
                if state:
                    app.radio(key=f"blood_bank_state_{center_id}").set_value(state).run()
                else:
                    self.assertEqual(len(app.radio), 1)
                self.confirm_load(app, f"load_blood_bank_{center_id}")
                self.assertFalse(app.exception)
                rows = [
                    row for row in Store(self.store.path).inventory(token, center_id)["facility_counts"]
                    if row["category"] == "Banco de sangre"
                ]
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["operational"], rows[0]["unavailable"]), expected)
                self.assertFalse(self.store.submission(token, center_id)["loaded"])
                app.run()
                export = app.session_state[f"_pdf_export_{center_id}"]
                self.assertEqual(export["category"], "Bancos de sangre")
                with pymupdf.open(stream=export["data"], filetype="pdf") as document:
                    self.assertEqual(len(document), 1)
                    text = document[0].get_text()
                    self.assertIn("BANCOS DE SANGRE", text)
                    for other in ("CAMAS HOSPITALARIAS", "AMBULANCIAS", "LABORATORIO", "QUIRÓFANOS"):
                        self.assertNotIn(other, text)
        app.button(key="inventory_category_Camas").click().run()
        self.assertEqual(len(app.get("download_button")), 1)
        app.run()
        with pymupdf.open(
            stream=app.session_state[f"_pdf_export_{center_id}"]["data"], filetype="pdf",
        ) as document:
            self.assertEqual(len(document), 1)
            self.assertIn("CAMAS HOSPITALARIAS", document[0].get_text())
        app.button(key="inventory_category_Banco de sangre").click().run()
        self.assertEqual(len(app.get("download_button")), 1)
        app.button(key=f"edit_section_{center_id}_Banco de sangre").click().run()
        self.store.save_category_quantities(
            token, center_id, "Banco de sangre", {"Banco de sangre": (2, 1)},
        )
        app.button(key="inventory_category_Camas").click().run()
        app.button(key="inventory_category_Banco de sangre").click().run()
        self.assertTrue(any("cantidades anteriores" in item.value for item in app.warning))
        app.radio(key=f"blood_bank_presence_{center_id}").set_value("Sí").run()
        app.radio(key=f"blood_bank_state_{center_id}").set_value("Fuera de servicio").run()
        self.confirm_load(app, f"load_blood_bank_{center_id}")
        self.load_remaining_sections(token, center_id)
        self.store.submit(token, center_id)
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.radio)
        self.assertFalse(app.dataframe)
        self.assertTrue(any("Fuera de servicio" in item.value for item in app.markdown))

    def test_laboratory_presence_state_and_filtered_pdf(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.session_state["inventory_category"] = "Laboratorio"
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.number_input)
        self.assertFalse(app.dataframe)
        heading = next(item.value for item in app.get("html") if ">LABORATORIO</div>" in item.value)
        self.assertIn("background-color: var(--primary-color, #147d78)", heading)
        self.assertEqual(app.radio(key=f"emergency_laboratory_presence_{center_id}").value, "No")
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        self.assertTrue(all(
            row["operational"] == row["unavailable"] == 0
            for row in self.store.inventory(token, center_id)["facility_counts"]
        ))
        app.radio(key=f"emergency_laboratory_presence_{center_id}").set_value("No").run()
        for presence, state, expected in (
            ("Sí", "Operativo", (1, 0)),
            ("Sí", "Fuera de servicio", (0, 1)),
            ("No", None, (0, 0)),
        ):
            with self.subTest(presence=presence, state=state):
                if any(button.key == f"edit_section_{center_id}_Laboratorio" for button in app.button):
                    app.button(key=f"edit_section_{center_id}_Laboratorio").click().run()
                app.radio(key=f"laboratory_presence_{center_id}").set_value(presence).run()
                if state:
                    app.radio(key=f"laboratory_state_{center_id}").set_value(state).run()
                else:
                    self.assertEqual(len(app.radio), 3)
                self.confirm_load(app, f"load_laboratory_{center_id}")
                self.assertFalse(app.exception)
                row = next(
                    row for row in Store(self.store.path).inventory(token, center_id)["facility_counts"]
                    if row["kind"] == "Laboratorio"
                )
                self.assertEqual((row["operational"], row["unavailable"]), expected)
                self.assertFalse(self.store.submission(token, center_id)["loaded"])
                app.run()
                with pymupdf.open(
                    stream=app.session_state[f"_pdf_export_{center_id}"]["data"], filetype="pdf",
                ) as document:
                    self.assertEqual(len(document), 1)
                    text = document[0].get_text()
                    self.assertIn("LABORATORIOS", text)
                    for other in ("Banco de sangre", "CAMAS HOSPITALARIAS", "AMBULANCIAS"):
                        self.assertNotIn(other, text)
        app.button(key="inventory_category_Banco de sangre").click().run()
        self.assertEqual(len(app.get("download_button")), 1)
        app.radio(key=f"blood_bank_presence_{center_id}").set_value("Sí").run()
        self.confirm_load(app, f"load_blood_bank_{center_id}")
        app.button(key="inventory_category_Laboratorio").click().run()
        app.button(key=f"edit_section_{center_id}_Laboratorio").click().run()
        self.assertEqual(app.radio(key=f"laboratory_presence_{center_id}").value, "No")
        app.radio(key=f"emergency_laboratory_presence_{center_id}").set_value("Sí").run()
        app.radio(key=f"emergency_laboratory_state_{center_id}").set_value("Fuera de servicio").run()
        self.confirm_load(app, f"load_laboratory_{center_id}")
        laboratories = {
            row["kind"]: (row["operational"], row["unavailable"])
            for row in Store(self.store.path).inventory(token, center_id)["facility_counts"]
            if row["category"] == "Laboratorio"
        }
        self.assertEqual(laboratories, {"Laboratorio": (0, 0), "Laboratorio de emergencia": (0, 1)})
        self.load_remaining_sections(token, center_id)
        self.store.submit(token, center_id)
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.radio)
        self.assertFalse(any(button.key == f"load_laboratory_{center_id}" for button in app.button))
        self.assertTrue(any("¿Hay laboratorio central?** No" in item.value for item in app.markdown))
        self.assertTrue(any("¿Hay laboratorio de emergencia?** Sí" in item.value for item in app.markdown))

    def test_plants_have_separate_button_counts_summary_and_pdf(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        app.button(key="inventory_category_Plantas eléctricas").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.number_input), 2)
        app.number_input(key=f"category_operational_{center_id}_Plantas eléctricas_0").set_value(3).run()
        app.number_input(key=f"category_unavailable_{center_id}_Plantas eléctricas_0").set_value(1).run()
        self.confirm_load(app, f"load_plants_{center_id}")
        self.assertFalse(app.exception)
        inventory = Store(self.store.path).inventory(token, center_id)
        self.assertEqual(inventory["plant_counts"][0]["operational"], 3)
        self.assertTrue(all(row["operational"] == row["unavailable"] == 0 for row in inventory["equipment_counts"]))
        self.assertEqual(self.store.summary(admin)[0]["Plantas eléctricas"], 4)
        self.assertEqual(self.store.summary(admin)[0]["Equipos"], 0)
        self.assertFalse(self.store.submission(token, center_id)["loaded"])
        app.run()
        with pymupdf.open(
            stream=app.session_state[f"_pdf_export_{center_id}"]["data"], filetype="pdf",
        ) as document:
            self.assertEqual(len(document), 1)
            self.assertIn("PLANTAS ELÉCTRICAS", document[0].get_text())
            self.assertNotIn("EQUIPOS MÉDICOS", document[0].get_text())
        app.button(key="inventory_category_Equipos médicos especiales").click().run()
        self.assertEqual(len(app.number_input), 16)
        self.assertFalse(any("Plantas" in field.label for field in app.number_input))

    def test_equipment_quantities_archive_history_and_generate_filtered_pdf(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        self.store.add_equipment_type(admin, "Monitor")
        self.store.save_equipment(token, center_id, "OLD-1", "Monitor", "Marca", "Modelo", "Serie", "Operativo")
        for category, kinds in INVENTORY_QUANTITIES.items():
            self.store.save_category_quantities(
                token, center_id, category, {kind: (0, 0) for kind in kinds},
            )
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.session_state["inventory_category"] = "Equipos médicos especiales"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.number_input), 2 * len(SPECIAL_EQUIPMENT_TYPES))
        self.assertFalse(any(form.key.startswith("equipment_") for form in app.get("form")))
        self.assertTrue(any("Historial" in expander.label for expander in app.expander))
        self.assertEqual(self.store.summary(admin)[0]["Equipos"], 0)
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        self.assertTrue(all(
            row["operational"] == row["unavailable"] == 0
            for row in self.store.inventory(token, center_id)["equipment_counts"]
        ))
        for index, kind in enumerate(SPECIAL_EQUIPMENT_TYPES):
            self.assertEqual(
                app.number_input(key=f"category_operational_{center_id}_Equipos médicos especiales_{index}").value, 0,
            )
            self.assertTrue(any(f">{kind}</div>" in item.value for item in app.get("html")))
        app.number_input(key=f"category_operational_{center_id}_Equipos médicos especiales_0").set_value(4).run()
        app.number_input(key=f"category_unavailable_{center_id}_Equipos médicos especiales_0").set_value(2).run()
        self.assertTrue(any(item.value == "**06**" for item in app.markdown))
        self.confirm_load(app, f"load_equipment_{center_id}")
        self.assertFalse(app.exception)
        inventory = Store(self.store.path).inventory(token, center_id)
        self.assertEqual(len(inventory["equipment_counts"]), len(SPECIAL_EQUIPMENT_TYPES))
        self.assertEqual(inventory["equipment"][0]["code"], "OLD-1")
        self.assertEqual(self.store.summary(admin)[0]["Equipos"], 6)
        self.assertFalse(self.store.submission(token, center_id)["loaded"])
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        period_start = self.store.submission(token, center_id)["period_start"]
        for section in REPORT_SECTIONS:
            if section != "Equipos médicos especiales":
                with self.store.transaction() as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO section_loads(center_id, section, period_start, loaded) VALUES(?, ?, ?, 1)",
                        (center_id, section, period_start),
                    )
        app.run()
        app.run()
        with pymupdf.open(
            stream=app.session_state[f"_pdf_export_{center_id}"]["data"], filetype="pdf",
        ) as document:
            text = "".join(page.get_text() for page in document)
            for kind in SPECIAL_EQUIPMENT_TYPES:
                self.assertIn(kind, text)
            for excluded in ("Monitor", "CAMAS HOSPITALARIAS", "LABORATORIOS"):
                self.assertNotIn(excluded, text)
        app.button(key="submit_inventory").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(self.store.submission(token, center_id)["loaded"])
        self.assertFalse(app.number_input)
        self.assertFalse(any(button.key == f"load_equipment_{center_id}" for button in app.button))

    def test_theatre_presence_state_and_filtered_pdf(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.session_state["inventory_category"] = "Quirófano"
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.dataframe)
        self.assertFalse(app.number_input)
        for label in ("QUIRÓFANOS", "QUIRÓFANO EN PISO", "QUIRÓFANO EN EMERGENCIA"):
            banner = next(item.value for item in app.get("html") if f">{label}</div>" in item.value)
            self.assertIn("background-color: var(--primary-color, #147d78)", banner)
        app.radio(key=f"floor_theatre_presence_{center_id}").set_value("Sí").run()
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        self.assertTrue(all(
            row["operational"] == row["unavailable"] == 0
            for row in self.store.inventory(token, center_id)["facility_counts"]
        ))
        app.radio(key=f"emergency_theatre_presence_{center_id}").set_value("Sí").run()
        app.number_input(key=f"emergency_theatre_operational_{center_id}").set_value(2).run()
        app.number_input(key=f"emergency_theatre_unavailable_{center_id}").set_value(1).run()
        self.confirm_load(app, f"load_theatres_{center_id}")
        self.assertFalse(app.exception)
        rows = [
            row for row in Store(self.store.path).inventory(token, center_id)["facility_counts"]
            if row["category"] == "Quirófano"
        ]
        self.assertEqual(
            {row["kind"]: (row["operational"], row["unavailable"]) for row in rows},
            {"En pisos": (1, 0), "En emergencias": (2, 1)},
        )
        self.assertFalse(self.store.submission(token, center_id)["loaded"])
        app.run()
        with pymupdf.open(
            stream=app.session_state[f"_pdf_export_{center_id}"]["data"], filetype="pdf",
        ) as document:
            self.assertEqual(len(document), 1)
            text = document[0].get_text()
            self.assertIn("QUIRÓFANOS", text)
            self.assertNotIn("LABORATORIO", text)
            self.assertNotIn("CAMAS HOSPITALARIAS", text)
        app.button(key=f"edit_section_{center_id}_Quirófano").click().run()
        app.radio(key=f"floor_theatre_presence_{center_id}").set_value("No").run()
        self.confirm_load(app, f"load_theatres_{center_id}")
        rows = self.store.inventory(token, center_id)["facility_counts"]
        self.assertEqual(next(row["operational"] for row in rows if row["kind"] == "En pisos"), 0)
        self.load_remaining_sections(token, center_id)
        self.store.submit(token, center_id)
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.radio)
        self.assertFalse(any(button.key == f"load_theatres_{center_id}" for button in app.button))

    def test_special_laboratories_require_one_allow_three_and_edit_names(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.session_state["inventory_category"] = "Laboratorio"
        app.run()
        app.radio(key=f"laboratory_presence_{center_id}").set_value("No").run()
        app.radio(key=f"emergency_laboratory_presence_{center_id}").set_value("No").run()
        app.radio(key=f"special_laboratories_presence_{center_id}").set_value("Sí").run()
        names = [field for field in app.text_input if (field.key or "").startswith("special_laboratory_name_")]
        self.assertEqual(len(names), 3)
        self.confirm_load(app, f"load_laboratory_{center_id}")
        self.assertFalse(app.exception)
        self.assertTrue(any("entre uno y tres" in item.value for item in app.error))
        self.assertTrue(all(
            row["operational"] == row["unavailable"] == 0
            for row in self.store.inventory(token, center_id)["facility_counts"]
        ))
        app.text_input(key=f"special_laboratory_name_{center_id}_1").set_value("Microbiología").run()
        self.assertEqual(app.text_input(key=f"special_laboratory_name_{center_id}_1").value, "MICROBIOLOGÍA")
        self.confirm_load(app, f"load_laboratory_{center_id}")
        self.assertFalse(app.exception)
        rows = self.store.inventory(token, center_id)["special_laboratories"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "MICROBIOLOGÍA")
        app.button(key=f"edit_section_{center_id}_Laboratorio").click().run()
        for slot, name in ((1, "Toxicología"), (2, "Inmunología"), (3, "Patología")):
            app.text_input(key=f"special_laboratory_name_{center_id}_{slot}").set_value(name)
        app.selectbox(key=f"special_laboratory_state_{center_id}_3").set_value("Fuera de servicio")
        self.confirm_load(app, f"load_laboratory_{center_id}")
        self.assertFalse(app.exception)
        rows = Store(self.store.path).inventory(token, center_id)["special_laboratories"]
        self.assertEqual([row["name"] for row in rows], ["TOXICOLOGÍA", "INMUNOLOGÍA", "PATOLOGÍA"])
        self.assertEqual(rows[2]["state"], "Fuera de servicio")
        self.assertFalse(self.store.submission(token, center_id)["loaded"])
        self.assertEqual(self.store.summary(admin)[0]["Laboratorios"], 3)
        app.run()
        with pymupdf.open(
            stream=app.session_state[f"_pdf_export_{center_id}"]["data"], filetype="pdf",
        ) as document:
            text = "".join(page.get_text() for page in document)
            for name in ("TOXICOLOGÍA", "INMUNOLOGÍA", "PATOLOGÍA"):
                self.assertIn(name, text)
            self.assertNotIn("BANCOS DE SANGRE", text)
        app.button(key="inventory_category_Camas").click().run()
        app.button(key="inventory_category_Laboratorio").click().run()
        app.button(key=f"edit_section_{center_id}_Laboratorio").click().run()
        self.assertEqual(app.text_input(key=f"special_laboratory_name_{center_id}_1").value, "TOXICOLOGÍA")
        self.load_remaining_sections(token, center_id)
        self.store.submit(token, center_id)
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(any((field.key or "").startswith("special_laboratory_name_") for field in app.text_input))
        self.assertTrue(any("PATOLOGÍA: Fuera de servicio" in item.value for item in app.text))

    def test_vehicle_button_groups_existing_counts_and_saves_without_submission(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        for category, kinds in INVENTORY_QUANTITIES.items():
            self.store.save_category_quantities(
                token, center_id, category, {kind: (2, 1) for kind in kinds},
            )
        self.store.save_category_quantities(
            token, center_id, "Equipos médicos especiales",
            {kind: (0, 0) for kind in SPECIAL_EQUIPMENT_TYPES},
        )
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.session_state["inventory_category"] = "Ambulancias"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.button(key="inventory_category_Vehículos").label, "VEHÍCULOS")
        self.assertFalse(any(
            button.key in ("inventory_category_Ambulancias", "inventory_category_Vehículos protocolares")
            for button in app.button
        ))
        banners = [item.value for item in app.get("html") if item.value.startswith("<div")]
        self.assertEqual(len(banners), 5)
        for label in (
            "Ambulancias", "Vehículos protocolares",
            "Carga pesada (camiones y gandolas)",
            "Transporte de personal (autobús, van y minivan)", "Motos",
        ):
            banner = next(banner for banner in banners if f">{label}</div>" in banner)
            self.assertIn("background-color: var(--primary-color, #147d78)", banner)
            self.assertIn("color: #ffffff", banner)
        self.assertEqual(len(app.number_input), 14)
        self.assertEqual([field.value for field in app.number_input], [2, 1] * 7)
        app.number_input(key=f"category_operational_{center_id}_Vehículos_1").set_value(7).run()
        app.number_input(key=f"category_unavailable_{center_id}_Vehículos_6").set_value(4).run()
        displayed = [item.value for item in app.markdown]
        self.assertIn("**19**", displayed)
        self.assertIn("**10**", displayed)
        self.assertIn("**29**", displayed)
        for label, totals in (
            ("AMBULANCIAS", ("11", "03", "14")),
            ("VEHÍCULOS PROTOCOLARES", ("02", "01", "03")),
            ("CARGA PESADA (CAMIONES Y GANDOLAS)", ("02", "01", "03")),
            ("TRANSPORTE DE PERSONAL (AUTOBÚS, VAN Y MINIVAN)", ("02", "01", "03")),
            ("MOTOS", ("02", "04", "06")),
        ):
            start = displayed.index(f"**TOTAL {label}**")
            self.assertEqual(displayed[start + 1:start + 4], [f"**{total}**" for total in totals])
        self.confirm_load(app, f"load_vehicles_{center_id}")
        self.assertFalse(app.exception)
        for table, totals in zip(app.dataframe[:5], ((11, 3, 14), (2, 1, 3), (2, 1, 3), (2, 1, 3), (2, 4, 6))):
            subtotal = table.value.iloc[-1]
            self.assertEqual(subtotal["Tipo de vehículo"], "SUBTOTAL")
            self.assertEqual(tuple(subtotal[column] for column in ("Operativas", "Inoperativas", "Total")), totals)
        rows = {
            row["kind"]: (row["operational"], row["unavailable"])
            for row in Store(self.store.path).inventory(token, center_id)["quantities"]
            if row["category"] == "Vehículos"
        }
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows["Soporte avanzado"], (7, 1))
        self.assertEqual(rows["Motos"], (2, 4))
        self.assertEqual(self.store.missing_inventory_categories(token, center_id), [])
        self.assertFalse(self.store.submission(token, center_id)["loaded"])
        app.button(key="inventory_category_Camas").click().run()
        app.button(key="inventory_category_Vehículos").click().run()
        self.assertFalse(app.exception)
        app.button(key=f"edit_section_{center_id}_Vehículos").click().run()
        self.assertEqual(app.number_input(key=f"category_operational_{center_id}_Vehículos_1").value, 7)
        self.load_remaining_sections(token, center_id)
        self.store.submit(token, center_id, require_all_categories=True)
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(any(button.key == f"load_vehicles_{center_id}" for button in app.button))
        self.assertEqual(
            len([item for item in app.get("html") if item.value.startswith("<div")]), 5,
        )

    def test_development_mode_hides_account_management_and_preserves_real_storage(self):
        from app import development_store
        development_store.clear()
        self.addCleanup(development_store.clear)
        with patch.dict(os.environ, {"SALUD_DEVELOPMENT_MODE": "1"}):
            # Use the real Store for the isolated, temporary development database.
            with patch("store.Store", Store):
                app = AppTest.from_file(APP, default_timeout=30).run()
                self.assertFalse(app.exception)
                self.assertFalse(any(field.type == "password" for field in app.text_input))
                self.assertFalse(any(form.key == "new_center" for form in app.get("form")))
                self.assertEqual(len(app.selectbox(key="summary_center").options), 35)
                self.assertEqual(len(app.tabs), 0)
                self.assertFalse(app.expander)
                self.assertFalse(any(button.label == "Camas hospitalarias" for button in app.button))
                self.assertFalse(any(field.type == "password" for field in app.text_input))
        self.assertFalse(self.store.initialized())

    def test_all_35_centers_share_configuration_and_complete_weekly_workflow(self):
        from store import load_center_catalog

        store = self.store
        store.bootstrap("admin", PASSWORD)
        admin = store.login("admin", PASSWORD)
        store.import_centers(admin, load_center_catalog())
        centers = [(row["id"], row["name"]) for row in store.centers(admin)]
        self.assertEqual(len(centers), 34)
        with store.transaction() as connection:
            for center_id, _ in centers:
                store._create_user(connection, f"test-center-{center_id}", PASSWORD, "center", center_id)
            connection.execute("UPDATE users SET must_change=0")
        load_keys = {
            "Camas": "beds", "Vehículos": "vehicles", "Banco de sangre": "blood_bank",
            "Laboratorio": "laboratory", "Quirófano": "theatres",
            "Equipos médicos especiales": "equipment", "Plantas eléctricas": "plants",
        }
        titles = {
            "Camas": "CAMAS HOSPITALARIAS", "Vehículos": "AMBULANCIAS",
            "Banco de sangre": "BANCOS DE SANGRE", "Laboratorio": "LABORATORIOS",
            "Quirófano": "QUIRÓFANOS",
            "Equipos médicos especiales": "EQUIPOS MÉDICOS ESPECIALES",
            "Plantas eléctricas": "PLANTAS ELÉCTRICAS",
        }
        with patch.dict(os.environ, {"SALUD_DEVELOPMENT_MODE": "0"}):
            baseline_heading_style = None
            for center_id, name in centers:
                with self.subTest(center=name):
                    token = store.login(f"test-center-{center_id}", PASSWORD)
                    app = AppTest.from_file(APP, default_timeout=30)
                    app.session_state["token"] = token
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertFalse(app.error)
                    self.assertEqual(app.title[0].value.replace("\u00a0", " "), name.upper())
                    heading_style = next(
                        item.value for item in app.get("html") if ".st-key-center_heading" in item.value
                    )
                    if baseline_heading_style is None:
                        baseline_heading_style = heading_style
                    self.assertEqual(heading_style, baseline_heading_style)
                    banner = next(
                        block for block in app.get("flex_container") if block.key == "center_banner"
                    )
                    self.assertEqual(len(banner.get("image")), 1)
                    blocks = list(app.main)
                    self.assertLess(
                        next(i for i, block in enumerate(blocks) if block.key == "center_banner"),
                        next(i for i, block in enumerate(blocks) if block.key == "center_heading"),
                    )
                    token = app.session_state["token"]
                    self.assertEqual([row["id"] for row in store.centers(token)], [center_id])
                    self.assertFalse(any(form.key == "new_center" for form in app.get("form")))
                    self.assertFalse(any(store.section_loads(token, center_id).values()))
                    for category in REPORT_SECTIONS:
                        app.button(key=f"inventory_category_{category}").click().run()
                        self.assertFalse(app.exception)
                        self.assertFalse(app.error)
                        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
                        self.assertEqual(len(app.get("download_button")), 1)
                        self.assertEqual(app.get("download_button")[0].label, "DESCARGAR PDF")
                        export = app.session_state[f"_pdf_export_{center_id}"]
                        self.assertEqual([row[0]["id"] for row in export["snapshot"]], [center_id])
                        with pymupdf.open(stream=export["data"], filetype="pdf") as document:
                            self.assertIn(titles[category], document[0].get_text())
                        if category == "Camas":
                            app.number_input(
                                key=f"category_operational_{center_id}_Camas_0",
                            ).set_value(center_id).run()
                        self.confirm_load(app, f"load_{load_keys[category]}_{center_id}")
                        self.assertFalse(app.exception)
                        self.assertFalse(app.error)
                        self.assertTrue(store.section_loads(token, center_id)[category])
                        self.assertFalse(app.number_input)
                        self.assertFalse(app.radio)
                    self.assertTrue(all(store.section_loads(token, center_id).values()))
                    app.button(key="submit_inventory").click().run()
                    self.assertFalse(app.exception)
                    self.assertFalse(app.error)
                    self.assertTrue(store.submission(token, center_id)["loaded"])
                    self.assertTrue(any(item.value == REPORT_LOADED for item in app.success))
                    self.assertFalse(any(
                        button.key == "submit_inventory" or (button.key or "").startswith("edit_section_")
                        for button in app.button
                    ))
            admin = store.login("admin", PASSWORD)
            summary = store.summary(admin)
            self.assertEqual(len(summary), 34)
            self.assertTrue(all(row["Estado"] == REPORT_LOADED for row in summary))
            self.assertEqual(
                {row["Centro"]: row["Camas"] for row in summary},
                {name: center_id for center_id, name in centers},
            )

    def test_development_loads_all_pdf_centers_without_login_or_passwords(self):
        from app import development_store
        development_store.clear()
        self.addCleanup(development_store.clear)
        with patch.dict(os.environ, {"SALUD_DEVELOPMENT_MODE": "1"}), patch("store.Store", Store):
            app = AppTest.from_file(APP, default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.selectbox(key="dev_perspective").options), 35)
            self.assertEqual(len(app.tabs), 0)
            self.assertFalse(any(field.type == "password" for field in app.text_input))
            self.assertFalse(any(form.key == "new_center" for form in app.get("form")))
            summary_center = app.selectbox(key="summary_center")
            self.assertEqual(len(summary_center.options), 35)
            self.assertEqual(summary_center.value, "all")
            self.assertFalse(app.exception)
            self.assertEqual(len(app.error), 1)
            self.assertIn(REPORT_PENDING.upper(), app.error[0].value)
            self.assertEqual(app.error[0].value.count("\n- "), 34)
            self.assertEqual(len(app.get("download_button")), 1)
            self.assertFalse(any(button.key == "generate_pdf_all" for button in app.button))
            app.run()
            self.assertEqual(
                len(app.get("download_button")), 1,
                "El PDF consolidado debe seguir disponible después de actualizar la interfaz.",
            )
            center_name = app.selectbox(key="dev_perspective").options[1]
            self.assertFalse(any(form.key.startswith(INVENTORY_FORMS) for form in app.get("form")))
            self.assertTrue(any(box.label == "Centro de salud" for box in app.selectbox))
            app.selectbox(key="dev_perspective").set_value(
                next(value for value in range(1, 35) if app.selectbox(key="dev_perspective").format_func(value) == center_name)
            ).run()
            center_id = app.selectbox(key="dev_perspective").value
            self.assertFalse(app.exception)
            self.assertEqual(
                app.title[0].value,
                center_name.split('. ', 1)[1].upper(),
            )
            heading_style = next(item.value for item in app.get("html") if ".st-key-center_heading" in item.value)
            self.assertIn("background-color: var(--primary-color, #147d78)", heading_style)
            self.assertIn("color: #ffffff", heading_style)
            self.assertIn("text-align: center", heading_style)
            self.assertFalse(app.expander)
            self.assertFalse(any(box.label == "Centro de salud" for box in app.selectbox))
            self.assertFalse(app.subheader)
            self.assertEqual(len(app.caption) - len(app.sidebar.caption), 2)
            self.assertEqual(app.button(key="inventory_category_Camas").label, "**CAMAS HOSPITALARIAS**")
            app.run()
            self.assertEqual(len(app.get("download_button")), 1)
            app.number_input(key=f"category_operational_{center_id}_Camas_5").set_value(3)
            app.number_input(key=f"category_unavailable_{center_id}_Camas_5").set_value(1)
            self.confirm_load(app, f"load_beds_{center_id}")
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("download_button")), 1)
            updated = app.session_state[f"_pdf_export_{center_id}"]
            uci = next(
                row for row in updated["snapshot"][0][1]["quantities"]
                if row["kind"] == "UCI"
            )
            self.assertEqual((uci["operational"], uci["unavailable"]), (3, 1))
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("download_button")), 1)
            with patch("report.counts", side_effect=InventoryError("Tipo de prueba no clasificado.")):
                del app.session_state[f"_pdf_export_{center_id}"]
                app.run()
                self.assertTrue(app.error)
                self.assertEqual(len(app.get("download_button")), 0)
            app.selectbox(key="dev_perspective").select("admin").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, "SALA SITUACIONAL DIGESALUD-MPPD")
            single_line_style = next(
                item.value for item in app.get("html") if "white-space: nowrap" in item.value
            )
            self.assertIn("font-size: clamp(0.55rem, 3.4vw, 1.65rem)", single_line_style)
            self.assertFalse(any(form.key.startswith(INVENTORY_FORMS) for form in app.get("form")))
            app.selectbox(key="summary_center").set_value(center_id).run()
            app.button(key="inventory_category_Camas").click().run()
            self.assertFalse(app.exception)
            table = app.dataframe[0].value
            self.assertEqual(
                table[table["Tipo"] == "UCI"]["Total"].iloc[0], 4,
                "El administrador debe ver en el resumen lo cargado por el centro.",
            )
            self.assertTrue(any(
                button.key == f"download_pdf_summary_{app.selectbox(key='summary_center').value}"
                for button in app.get("download_button")
            ))
            self.assertFalse(any(
                button.key == f"generate_pdf_summary_{app.selectbox(key='summary_center').value}"
                for button in app.button
            ))
        self.assertFalse(self.store.initialized())

    def test_summary_by_category_and_center(self):
        self.store.bootstrap("admin", PASSWORD)
        token = self.store.login("admin", PASSWORD)
        self.store.create_center(token, "Centro Norte", "Norte", "norte", TEMPORARY)
        self.store.create_center(token, "Centro Sur", "Sur", "sur", TEMPORARY)
        north, south = (center["id"] for center in self.store.centers(token))
        self.store.save_quantity(token, north, "Camas", "UCI", 5, 2)
        self.store.save_quantity(token, south, "Camas", "UCI", 1, 1)
        self.store.save_quantity(token, south, "Vehículos", "Soporte básico", 3, 0)
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(any(
            "Sin datos de pacientes ni donantes" in item.value for item in app.caption
        ))
        self.assertEqual(app.selectbox(key="summary_kind_Camas hospitalarias").options[0], "Todos los tipos")
        self.assertEqual(app.title[0].value, "SALA SITUACIONAL DIGESALUD-MPPD")
        self.assertFalse(any(form.key.startswith(INVENTORY_FORMS) for form in app.get("form")))
        self.assertEqual(sum((button.key or "").startswith("inventory_category_") for button in app.button), 7)
        self.assertNotIn("Centros de salud", [expander.label for expander in app.expander])
        app.button(key="inventory_category_Camas").click().run()
        self.assertFalse(app.exception)
        table = app.dataframe[0].value
        self.assertEqual(table[table["Tipo"] == "UCI"]["Total"].iloc[0], 9)
        self.assertEqual(table[table["Tipo"] == "TOTAL"]["Operativas"].iloc[0], 6)
        app.selectbox(key="summary_center").select(north).run()
        table = app.dataframe[0].value
        self.assertEqual(table[table["Tipo"] == "TOTAL"]["Total"].iloc[0], 7)
        app.button(key="inventory_category_Vehículos").click().run()
        app.selectbox(key="summary_vehicle_group").select("Ambulancias").run()
        table = app.dataframe[0].value
        self.assertEqual(table[table["Tipo"] == "TOTAL"]["Total"].iloc[0], 0)
        app.selectbox(key="summary_center").select(south).run()
        table = app.dataframe[0].value
        self.assertEqual(table[table["Tipo"] == "Soporte básico"]["Operativas"].iloc[0], 3)

    def test_development_center_can_load_and_submit_outside_production_schedule(self):
        import streamlit as st

        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        self.clock.return_value = datetime(
            2026, 10, 27, 12, tzinfo=REPORT_TIMEZONE,
        ).timestamp()
        with patch.dict(os.environ, {"SALUD_DEVELOPMENT_MODE": "1"}), patch("store.Store", Store):
            app = AppTest.from_file(APP, default_timeout=30).run()
            app.selectbox(key="dev_perspective").select(1).run()
            self.assertFalse(app.exception)
            center_id = app.selectbox(key="dev_perspective").value
            for category in (
                "Camas", "Vehículos", "Banco de sangre", "Plantas eléctricas",
                "Laboratorio", "Quirófano",
            ):
                if category != "Camas":
                    app.button(key=f"inventory_category_{category}").click().run()
                if category == "Camas":
                    self.confirm_load(app, f"load_beds_{center_id}")
                elif category == "Vehículos":
                    self.confirm_load(app, f"load_vehicles_{center_id}")
                elif category == "Plantas eléctricas":
                    self.confirm_load(app, f"load_plants_{center_id}")
                elif category == "Banco de sangre":
                    app.radio(key=f"blood_bank_presence_{center_id}").set_value("No").run()
                    self.confirm_load(app, f"load_blood_bank_{center_id}")
                elif category == "Laboratorio":
                    app.radio(key=f"laboratory_presence_{center_id}").set_value("No").run()
                    app.radio(key=f"emergency_laboratory_presence_{center_id}").set_value("No").run()
                    self.confirm_load(app, f"load_laboratory_{center_id}")
                elif category == "Quirófano":
                    app.radio(key=f"floor_theatre_presence_{center_id}").set_value("No").run()
                    app.radio(key=f"emergency_theatre_presence_{center_id}").set_value("No").run()
                    self.confirm_load(app, f"load_theatres_{center_id}")
                else:
                    form = next(
                        form for form in app.get("form")
                        if form.key == f"quantity_{center_id}_{category}"
                    )
                    form.button[0].click().run()
                self.assertFalse(app.exception)
            app.button(key="inventory_category_Equipos médicos especiales").click().run()
            self.confirm_load(app, f"load_equipment_{center_id}")
            app.button(key="submit_inventory").click().run()
            self.assertTrue(any(REPORT_LOADED in item.value for item in app.success))
            self.assertFalse(any(form.key.startswith(INVENTORY_FORMS) for form in app.get("form")))
            self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
            app.selectbox(key="dev_perspective").select("admin").run()
            self.assertFalse(app.exception)
            self.assertTrue(any(REPORT_LOADED in item.value for item in app.success))
        self.assertFalse(self.store.initialized())

    def test_admin_vehicle_group_and_type_filters_reset_incompatible_selection(self):
        from store import VEHICLE_GROUPS

        self.store.bootstrap("admin", PASSWORD)
        token = self.store.login("admin", PASSWORD)
        self.store.create_center(token, "Centro Norte", "", "norte", TEMPORARY)
        self.store.save_quantity(token, 1, "Vehículos", "Soporte básico", 4, 2)
        self.store.save_quantity(token, 1, "Vehículos", "Motos", 9, 0)
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        app.button(key="inventory_category_Vehículos").click().run()
        kind_key = "summary_kind_Todos los vehículos"
        for group, kinds in VEHICLE_GROUPS.items():
            app.selectbox(key="summary_vehicle_group").select(group).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key=kind_key).options, ["Todos los tipos", *kinds])
            app.selectbox(key=kind_key).select(kinds[0]).run()
            table = app.dataframe[0].value
            self.assertEqual(list(table["Tipo"]), [kinds[0], "TOTAL"])
            with pymupdf.open(
                stream=app.session_state["_pdf_export_summary_all"]["data"], filetype="pdf",
            ) as doc:
                self.assertEqual(len(doc), 1)
                self.assertIn(kinds[0].upper(), doc[0].get_text().upper())
        app.selectbox(key="summary_vehicle_group").select("Ambulancias").run()
        self.assertEqual(app.selectbox(key=kind_key).value, "all")
        table = app.dataframe[0].value
        self.assertEqual(table[table["Tipo"] == "TOTAL"]["Total"].iloc[0], 6)
        self.assertNotIn("Motos", list(table["Tipo"]))
        app.selectbox(key="summary_vehicle_group").select("all").run()
        table = app.dataframe[0].value
        self.assertEqual(table[table["Tipo"] == "TOTAL"]["Total"].iloc[0], 15)

    def test_summary_pdf_tracks_category_and_center_filters(self):
        from app import REPORT_CATEGORIES
        from report import SECTIONS

        self.store.bootstrap("admin", PASSWORD)
        token = self.store.login("admin", PASSWORD)
        self.store.create_center(token, "Centro Norte", "Norte", "norte", TEMPORARY)
        self.store.create_center(token, "Centro Sur", "Sur", "sur", TEMPORARY)
        self.store.add_equipment_type(token, "Monitor")
        north = self.store.centers(token)[0]["id"]
        for center in self.store.centers(token):
            self.store.save_equipment(
                token, center["id"], "M1", "Monitor", "Marca", "Modelo", "Serie", "Operativo",
            )
            with self.store.transaction() as connection:
                connection.execute(
                    "INSERT INTO equipment_counts(center_id, category, kind, operational, unavailable) VALUES(?, ?, ?, ?, ?)",
                    (center["id"], "Equipos médicos especiales", "Tomógrafo", 2, 1),
                )
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        categories = (
            ("Camas", SECTIONS[0][0]),
            ("Vehículos", SECTIONS[1][0]),
            ("Banco de sangre", "BANCOS DE SANGRE"),
            ("Laboratorio", "LABORATORIOS"),
            ("Quirófano", SECTIONS[3][0]),
            ("Equipos médicos especiales", SECTIONS[5][0]),
            ("Plantas eléctricas", SECTIONS[6][0]),
        )
        for center_id in ("all", north):
            app.selectbox(key="summary_center").select(center_id).run()
            export_key = f"_pdf_export_summary_{center_id}"
            for category, title in categories:
                with self.subTest(center=center_id, category=category):
                    app.button(key=f"inventory_category_{category}").click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual(len(app.get("download_button")), 1)
                    self.assertEqual(app.get("download_button")[0].label, "GENERAR REPORTE")
                    report_category = REPORT_CATEGORIES[category]
                    app.selectbox(key=f"summary_kind_{report_category}").select("all").run()
                    with pymupdf.open(stream=app.session_state[export_key]["data"], filetype="pdf") as doc:
                        self.assertEqual(len(doc), 5 if category == "Vehículos" else 1)
                        text = "\n".join(page.get_text() for page in doc)
                        self.assertIn(title, text)
                        self.assertIn("Centro Norte", text)
                        self.assertEqual("Centro Sur" in text, center_id == "all")
                        if category == "Banco de sangre":
                            self.assertNotIn("LABORATORIO", text)
                        elif category == "Laboratorio":
                            self.assertNotIn("BANCO DE SANGRE", text)
                    options = app.selectbox(key=f"summary_kind_{report_category}").options
                    for kind in options[1:]:
                        app.selectbox(key=f"summary_kind_{report_category}").select(kind).run()
                        self.assertFalse(app.exception)
                        self.assertEqual(app.session_state[export_key]["kind"], kind)
                        table = app.dataframe[0].value
                        self.assertEqual(list(table["Tipo"]), [kind, "TOTAL"])
                        with pymupdf.open(stream=app.session_state[export_key]["data"], filetype="pdf") as doc:
                            self.assertEqual(len(doc), 1)
                            text = doc[0].get_text()
                            self.assertIn("Centro Norte", text)
                            self.assertEqual("Centro Sur" in text, center_id == "all")

    def test_no_public_bootstrap_or_inventory(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.text_input)
        self.assertFalse(app.tabs)
        self.assertTrue(app.info)
        self.assertFalse(app.error)
        self.assertFalse(app.subheader)

    def test_admin_weekly_status_is_visible_red_and_independent_of_filters(self):
        self.store.bootstrap("admin", PASSWORD)
        token = self.store.login("admin", PASSWORD)
        for name, username in (("Centro Norte", "norte"), ("Centro Sur", "sur")):
            self.store.create_center(token, name, "", username, TEMPORARY)
        north = self.store.centers(token)[0]["id"]
        center_token = self.store.login("norte", TEMPORARY)
        self.store.change_password(center_token, TEMPORARY, PASSWORD)
        center_token = self.store.login("norte", PASSWORD)
        self.store.save_quantity(center_token, north, "Camas", "UCI", 1, 0)
        self.store.submit(center_token, north)
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        self.assertFalse(app.exception)
        heading = next(
            item.value for item in app.get("html")
            if "RESUMEN DE LOS CENTROS DE SALUD" in item.value
        )
        self.assertIn("background-color: var(--primary-color, #147d78)", heading)
        self.assertIn("font-weight: 700", heading)
        self.assertIn("text-align: center", heading)
        self.assertNotIn("Estado semanal de los centros", [item.value for item in app.subheader])
        self.assertFalse(any("Las cargas se habilitan" in item.value for item in app.caption))
        self.assertFalse(any("Pendientes por reportar:" in item.value for item in app.markdown))
        self.assertEqual(len(app.error), 1)
        self.assertIn(REPORT_PENDING.upper(), app.error[0].value)
        self.assertIn("Centro Sur", app.error[0].value)
        self.assertNotIn("Centro Norte", app.error[0].value)
        self.assertTrue(any(
            REPORT_LOADED in item.value and "Centro Norte" in item.value
            for item in app.success
        ))
        for expander in app.main.expander:
            self.assertFalse(expander.error)
            self.assertFalse(expander.success)
        app.selectbox(key="summary_center").select(north).run()
        app.button(key="inventory_category_Camas").click().run()
        self.assertFalse(app.exception)
        self.assertIn("Centro Sur", app.error[0].value)
        self.assertTrue(any("Centro Norte" in item.value for item in app.success))
        self.clock.return_value = datetime.fromisoformat("2026-11-05T00:00:00-04:00").timestamp()
        app.session_state["token"] = self.store.login("admin", PASSWORD)
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("Centro Norte", app.error[0].value)
        self.assertIn("Centro Sur", app.error[0].value)
        self.assertFalse(app.success)

    def test_admin_login_preserves_centers_without_account_management(self):
        self.store.bootstrap("admin", PASSWORD)
        token = self.store.login("admin", PASSWORD)
        self.store.create_center(token, "Centro Norte", "Norte", "norte", TEMPORARY)
        self.store.save_quantity(token, 1, "Camas", "UCI", 3, 0)
        original_centers = self.store.centers(token)
        original_users = self.store.users(token)
        original_inventory = self.store.inventory(token, 1)
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertFalse(app.tabs)
        app.text_input[0].set_value("admin")
        app.text_input[1].set_value("wrong")
        app.button[0].click().run()
        self.assertTrue(app.error)
        self.assertFalse(app.tabs)
        app.text_input[0].set_value("admin")
        app.text_input[1].set_value(PASSWORD)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertFalse(any(
            (form.key or "").startswith(("new_center", "edit_center_", "manage_user_", "password_user_"))
            for form in app.get("form")
        ))
        self.assertFalse(any(
            box.label in ("Centro a editar", "Cuenta a administrar") for box in app.selectbox
        ))
        self.assertEqual(self.store.centers(token), original_centers)
        self.assertEqual(self.store.users(token), original_users)
        self.assertEqual(self.store.inventory(token, 1), original_inventory)
        self.assertEqual(len(app.tabs), 0)
        self.assertEqual(app.selectbox(key="summary_center").options, ["Todos los centros de salud", "1. Centro Norte"])
        self.assertFalse(app.main.expander)

    def test_administrator_banner_and_heading_match_center_style(self):
        self.store.bootstrap("admin", PASSWORD)
        token = self.store.login("admin", PASSWORD)
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "SALA SITUACIONAL DIGESALUD-MPPD")
        banner = next(block for block in app.get("flex_container") if block.key == "center_banner")
        self.assertEqual(len(banner.get("image")), 1)
        blocks = list(app.main)
        self.assertLess(
            next(i for i, block in enumerate(blocks) if block.key == "center_banner"),
            next(i for i, block in enumerate(blocks) if block.key == "center_heading"),
        )
        style = next(item.value for item in app.get("html") if ".st-key-center_heading" in item.value)
        for rule in (
            "background-color: var(--primary-color, #147d78)",
            "color: #ffffff", "font-weight: 700", "text-align: center",
        ):
            self.assertIn(rule, style)

    def test_development_centers_allow_loading_every_item_outside_thursday_friday(self):
        from app import development_store
        development_store.clear()
        self.addCleanup(development_store.clear)
        self.clock.return_value = datetime(2026, 10, 27, 12, tzinfo=REPORT_TIMEZONE).timestamp()
        with patch.dict(os.environ, {"SALUD_DEVELOPMENT_MODE": "1"}), patch("store.Store", Store):
            app = AppTest.from_file(APP, default_timeout=30).run()
            app.selectbox(key="dev_perspective").set_value(1).run()
            for category in REPORT_SECTIONS:
                app.button(key=f"inventory_category_{category}").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.number_input or app.radio)
                self.assertTrue(any(
                    (button.key or "").startswith("load_") for button in app.button
                ))
                self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
                self.assertEqual(len(app.get("download_button")), 1)

    def test_admin_weekly_count_tracks_submissions_and_resets_next_period(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = admin
        app.run()
        counter = next(block for block in app.get("flex_container") if block.key == "weekly_report_count")
        self.assertIn("Semana 44 (26/10/2026 al 30/10/2026)", counter.markdown[0].value)
        self.assertIn("Centros de Salud que Han Reportado: 0/1 Faltan: 1", counter.markdown[0].value)
        blocks = list(app.main)
        self.assertLess(
            next(i for i, block in enumerate(blocks) if block.key == "center_heading"),
            next(i for i, block in enumerate(blocks) if block.key == "weekly_report_count"),
        )
        self.load_remaining_sections(token, center_id)
        self.store.submit(token, center_id, require_all_categories=True, require_loaded_sections=True)
        app.run()
        counter = next(block for block in app.get("flex_container") if block.key == "weekly_report_count")
        self.assertIn("Centros de Salud que Han Reportado: 1/1 Faltan: 0", counter.markdown[0].value)
        self.clock.return_value = datetime(2026, 11, 5, 12, tzinfo=REPORT_TIMEZONE).timestamp()
        app.session_state["token"] = self.store.login("admin", PASSWORD)
        app.run()
        self.assertFalse(app.exception)
        counter = next(block for block in app.get("flex_container") if block.key == "weekly_report_count")
        self.assertIn("Semana 45 (02/11/2026 al 06/11/2026)", counter.markdown[0].value)
        self.assertIn("Centros de Salud que Han Reportado: 0/1 Faltan: 1", counter.markdown[0].value)

    def test_center_heading_keeps_quoted_name_on_one_line(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        name = 'Ambulatorio Militar "Concepción Mariño"'
        self.store.create_center(admin, name, "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = token
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, 'AMBULATORIO MILITAR "CONCEPCIÓN\u00a0MARIÑO"')
        style = next(item.value for item in app.get("html") if ".st-key-center_heading" in item.value)
        self.assertIn("overflow-wrap: normal", style)
        self.assertIn("word-break: normal", style)
        self.assertIn("overflow-x: auto", style)
        self.assertEqual(self.store.centers(token)[0]["name"], name)

    def test_center_login_goes_straight_to_inventory_and_hides_admin(self):
        self.store.bootstrap("admin", PASSWORD)
        token = self.store.login("admin", PASSWORD)
        self.store.create_center(token, "Centro Norte", "Norte", "norte", TEMPORARY)
        self.store.create_center(token, "Centro Sur", "Sur", "sur", TEMPORARY)
        self.store.add_equipment_type(token, "Monitor")
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.text_input[0].set_value("norte")
        app.text_input[1].set_value(TEMPORARY)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.tabs)
        self.assertFalse(any(form.key == "change_password" for form in app.get("form")))
        self.assertFalse(any(box.label == "Centro de salud" for box in app.selectbox))
        self.assertEqual(app.title[0].value, "CENTRO NORTE")
        self.assertFalse(any(form.key == "new_center" for form in app.get("form")))
        self.assertFalse(any(button.key == "generate_pdf_all" for button in app.button))
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        center_id = self.store.centers(token)[0]["id"]
        app.number_input(key=f"category_operational_{center_id}_Camas_5").set_value(5)
        app.number_input(key=f"category_unavailable_{center_id}_Camas_5").set_value(2)
        self.confirm_load(app, f"load_beds_{center_id}")
        self.assertFalse(app.exception)
        self.assertFalse(app.metric)
        bed_rows = self.store.inventory(token, center_id)["quantities"]
        uci = next(row for row in bed_rows if row["kind"] == "UCI")
        self.assertEqual(uci["operational"] + uci["unavailable"], 7)
        app.button(key="inventory_category_Banco de sangre").click().run()
        blood_bank_heading = next(
            item.value for item in app.get("html")
            if ">BANCO DE SANGRE</div>" in item.value
        )
        self.assertIn("background-color: var(--primary-color, #147d78)", blood_bank_heading)
        self.assertIn("color: #ffffff", blood_bank_heading)
        self.assertEqual(app.button(key="inventory_category_Banco de sangre").proto.type, "primary")
        self.assertEqual(app.button(key="inventory_category_Camas").proto.type, "secondary")
        app.radio(key=f"blood_bank_presence_{center_id}").set_value("Sí").run()
        self.confirm_load(app, f"load_blood_bank_{center_id}")
        self.assertFalse(app.exception)
        app.button(key="inventory_category_Equipos médicos especiales").click().run()
        self.assertEqual(len(app.number_input), 2 * len(SPECIAL_EQUIPMENT_TYPES))
        app.number_input(key=f"category_operational_{center_id}_Equipos médicos especiales_0").set_value(3).run()
        self.confirm_load(app, f"load_equipment_{center_id}")
        self.assertFalse(app.exception)
        self.assertEqual(len(self.store.inventory(token, center_id)["equipment_counts"]), len(SPECIAL_EQUIPMENT_TYPES))
        center_id = self.store.centers(token)[0]["id"]
        app.button(key="inventory_category_Vehículos").click().run()
        self.assertEqual(len(app.number_input), 14)
        self.confirm_load(app, f"load_vehicles_{center_id}")
        self.assertFalse(app.exception)
        app.button(key="inventory_category_Quirófano").click().run()
        app.radio(key=f"floor_theatre_presence_{center_id}").set_value("No").run()
        app.radio(key=f"emergency_theatre_presence_{center_id}").set_value("Sí").run()
        self.confirm_load(app, f"load_theatres_{center_id}")
        self.assertFalse(app.exception)
        app.button(key="inventory_category_Vehículos").click().run()
        app.button(key=f"edit_section_{center_id}_Vehículos").click().run()
        app.number_input(key=f"category_operational_{center_id}_Vehículos_1").set_value(2)
        self.confirm_load(app, f"load_vehicles_{center_id}")
        self.assertFalse(app.exception)
        ambulance_rows = [
            row for row in self.store.inventory(token, center_id)["quantities"]
            if row["kind"] in ("Soporte básico", "Soporte avanzado", "Tácticas")
        ]
        self.assertEqual(len(ambulance_rows), 3)
        self.assertEqual(
            {row["kind"]: row["operational"] for row in ambulance_rows},
            {"Soporte básico": 0, "Soporte avanzado": 2, "Tácticas": 0},
        )
        app.button(key="inventory_category_Laboratorio").click().run()
        app.radio(key=f"laboratory_presence_{center_id}").set_value("No").run()
        app.radio(key=f"emergency_laboratory_presence_{center_id}").set_value("No").run()
        self.confirm_load(app, f"load_laboratory_{center_id}")
        self.assertFalse(self.store.submission(token, center_id)["loaded"])
        app.button(key="inventory_category_Plantas eléctricas").click().run()
        self.confirm_load(app, f"load_plants_{center_id}")
        app.button(key="inventory_category_Equipos médicos especiales").click().run()
        app.button(key="submit_inventory").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.store.summary(token)[0]["Estado"], REPORT_LOADED)
        self.assertTrue(self.store.submission(token, center_id)["loaded"])
        app.button(key="inventory_category_Laboratorio").click().run()
        self.assertFalse(any(form.key.startswith(INVENTORY_FORMS) for form in app.get("form")))
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        self.assertTrue(self.store.submission(app.session_state["token"], center_id)["loaded"])
        for category in ("Camas", "Vehículos", "Equipos médicos especiales"):
            app.button(key=f"inventory_category_{category}").click().run()
            self.assertFalse(any(form.key.startswith(INVENTORY_FORMS) for form in app.get("form")))
            self.assertFalse(any(button.key == f"load_beds_{center_id}" for button in app.button))
            self.assertFalse(any(button.key == f"load_vehicles_{center_id}" for button in app.button))
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(len(app.get("download_button")), 1)
        main = list(app.main)
        last = max(index for index, element in enumerate(main) if element.type == "download_button")
        self.assertFalse(main[last + 1:], "Nada debe aparecer después de Descargar PDF.")
        self.assertFalse(any(box.key == "summary_category" for box in app.selectbox))
        app.sidebar.button[0].click().run()
        self.assertFalse(app.tabs)

    def test_center_loads_outside_window_and_pending_next_week(self):
        self.store.bootstrap("admin", PASSWORD)
        admin = self.store.login("admin", PASSWORD)
        self.store.create_center(admin, "Centro Norte", "Norte", "norte", TEMPORARY)
        token = self.store.login("norte", TEMPORARY)
        self.store.change_password(token, TEMPORARY, PASSWORD)
        token = self.store.login("norte", PASSWORD)
        center_id = self.store.centers(token)[0]["id"]
        self.store.save_quantity(token, center_id, "Camas", "UCI", 5, 0)
        self.clock.return_value = datetime.fromisoformat("2026-10-31T00:00:00-04:00").timestamp()
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["token"] = self.store.login("norte", PASSWORD)
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(REPORT_PENDING in item.value for item in app.info))
        self.assertFalse(any("Las cargas se habilitan" in item.value for item in app.info))
        self.assertTrue(any(button.key == f"load_beds_{center_id}" for button in app.button))
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))
        app.run()
        self.assertEqual(len(app.get("download_button")), 1)
        self.clock.return_value = datetime.fromisoformat("2026-11-05T00:00:00-04:00").timestamp()
        app.session_state["token"] = self.store.login("norte", PASSWORD)
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(REPORT_PENDING in item.value for item in app.info))
        self.confirm_load(app, f"load_beds_{center_id}")
        for category in (
            "Vehículos", "Banco de sangre", "Plantas eléctricas",
            "Laboratorio", "Quirófano",
        ):
            app.button(key=f"inventory_category_{category}").click().run()
            if category == "Vehículos":
                self.confirm_load(app, f"load_vehicles_{center_id}")
                continue
            if category == "Plantas eléctricas":
                self.confirm_load(app, f"load_plants_{center_id}")
                continue
            if category == "Banco de sangre":
                app.radio(key=f"blood_bank_presence_{center_id}").set_value("No").run()
                self.confirm_load(app, f"load_blood_bank_{center_id}")
                continue
            if category == "Laboratorio":
                app.radio(key=f"laboratory_presence_{center_id}").set_value("No").run()
                app.radio(key=f"emergency_laboratory_presence_{center_id}").set_value("No").run()
                self.confirm_load(app, f"load_laboratory_{center_id}")
                continue
            if category == "Quirófano":
                app.radio(key=f"floor_theatre_presence_{center_id}").set_value("No").run()
                app.radio(key=f"emergency_theatre_presence_{center_id}").set_value("No").run()
                self.confirm_load(app, f"load_theatres_{center_id}")
                continue
            form = next(
                form for form in app.get("form")
                if form.key == f"quantity_{center_id}_{category}"
            )
            form.button[0].click().run()
        self.assertFalse(app.exception)
        app.button(key="inventory_category_Equipos médicos especiales").click().run()
        self.confirm_load(app, f"load_equipment_{center_id}")
        app.button(key="submit_inventory").click().run()
        self.assertTrue(self.store.submission(app.session_state["token"], center_id)["loaded"])
        self.clock.return_value = datetime.fromisoformat("2026-11-12T00:00:00-04:00").timestamp()
        app.session_state["token"] = self.store.login("norte", PASSWORD)
        app.session_state["inventory_category"] = "Camas"
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(REPORT_PENDING in item.value for item in app.info))
        self.assertFalse(any(button.key == "submit_inventory" for button in app.button))


if __name__ == "__main__":
    unittest.main()
