import re
import tempfile
import tomllib
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from store import (
    BED_TYPES, InventoryError, MILITARY_CAUSES, MILITARY_GRADES, MILITARY_REDI,
    Store, load_center_catalog,
)
from webapp import create_app


ADMIN_PASSWORD = "Testing-admin-password-123"
CENTER_PASSWORD = "Testing-center-password-456"


class VercelConfigurationTests(unittest.TestCase):
    def test_project_dependencies_match_runtime_requirements(self):
        root = Path(__file__).resolve().parent.parent
        project = tomllib.loads((root / "pyproject.toml").read_text())
        requirements = (root / "requirements.txt").read_text().splitlines()
        self.assertEqual(set(project["project"]["dependencies"]), set(requirements))


class HtmlApplicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name) / "inventory.sqlite3")
        self.store.bootstrap("admin", ADMIN_PASSWORD)
        self.admin_token = self.store.login("admin", ADMIN_PASSWORD)
        self.store.create_center(
            self.admin_token, "Centro Norte", "Norte", "norte", CENTER_PASSWORD,
        )
        self.center = self.store.centers(self.admin_token)[0]
        self.app = create_app(self.store, secret_key="test-secret")
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def csrf(self):
        response = self.client.get("/login")
        return re.search(
            rb'name="csrf_token" value="([^"]+)"', response.data,
        ).group(1).decode()

    def login(self, username, password):
        csrf = self.csrf()
        response = self.client.post("/login", data={
            "csrf_token": csrf, "username": username, "password": password,
        })
        self.assertEqual(response.status_code, 302)
        return response

    def authenticated_csrf(self):
        response = self.client.get("/")
        page = (
            self.client.get(response.headers["Location"])
            if response.status_code == 302 else response
        )
        return re.search(
            rb'name="csrf_token" value="([^"]+)"', page.data,
        ).group(1).decode()

    def test_inventory_requires_login_and_limits_center_access(self):
        response = self.client.get(f"/inventory/{self.center['id']}")
        self.assertEqual(response.status_code, 302)
        self.login("norte", CENTER_PASSWORD)
        response = self.client.get(f"/inventory/{self.center['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"CAMAS HOSPITALARIAS", response.data)
        pdf = self.client.get(
            f"/inventory/{self.center['id']}/report.pdf?category=Camas+hospitalarias",
        )
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")

        self.store.create_center(
            self.admin_token, "Centro Sur", "Sur", "sur", CENTER_PASSWORD,
        )
        other = self.store.centers(self.admin_token)[1]
        self.assertEqual(self.client.get(f"/inventory/{other['id']}").status_code, 403)

    def test_html_form_loads_complete_bed_section_and_locks_it(self):
        self.login("norte", CENTER_PASSWORD)
        csrf = self.authenticated_csrf()
        self.store.initialize_empty_items(
            self.store.login("norte", CENTER_PASSWORD), self.center["id"],
        )
        fields = {
            "csrf_token": csrf,
            "action": "load",
        }
        fields.update({
            f"qty_{index}_{suffix}": str(index + (1 if suffix == "operational" else 0))
            for index in range(len(BED_TYPES))
            for suffix in ("operational", "unavailable")
        })
        response = self.client.post(
            f"/inventory/{self.center['id']}/Camas", data=fields,
        )
        self.assertEqual(response.status_code, 302)
        token = self.store.login("norte", CENTER_PASSWORD)
        rows = self.store.inventory(token, self.center["id"])["quantities"]
        loaded_beds = {row["kind"]: row for row in rows if row["category"] == "Camas"}
        self.assertEqual(loaded_beds["Hospitalización"]["operational"], 1)
        self.assertEqual(loaded_beds["Observación"]["unavailable"], 1)
        self.assertTrue(self.store.section_loads(token, self.center["id"])["Camas"])
        page = self.client.get(f"/inventory/{self.center['id']}?section=Camas")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Editar secci", page.data)

    def test_all_seven_sections_can_be_loaded_and_submitted(self):
        self.login("norte", CENTER_PASSWORD)
        csrf = self.authenticated_csrf()
        token = self.store.login("norte", CENTER_PASSWORD)
        self.store.initialize_empty_items(token, self.center["id"])
        requests = {
            "Camas": {},
            "Vehículos": {},
            "Banco de sangre": {"presence_0": "No"},
            "Laboratorio": {
                "presence_0": "No", "presence_1": "No",
                "special_presence": "No",
            },
            "Quirófano": {"presence_0": "No", "presence_1": "No"},
            "Equipos médicos especiales": {},
            "Plantas eléctricas": {},
        }
        for section, fields in requests.items():
            with self.subTest(section=section):
                page = self.client.get(
                    f"/inventory/{self.center['id']}?section={section}",
                )
                self.assertEqual(page.status_code, 200)
                payload = {"csrf_token": csrf, "action": "load", **fields}
                if section == "Camas":
                    kinds = list(BED_TYPES)
                elif section == "Vehículos":
                    from store import VEHICLE_GROUPS
                    kinds = [kind for group in VEHICLE_GROUPS.values() for kind in group]
                elif section == "Equipos médicos especiales":
                    from store import SPECIAL_EQUIPMENT_TYPES
                    kinds = list(SPECIAL_EQUIPMENT_TYPES)
                elif section == "Plantas eléctricas":
                    kinds = ["Plantas eléctricas"]
                elif section == "Quirófano":
                    kinds = ["En pisos", "En emergencias"]
                elif section == "Laboratorio":
                    kinds = ["Laboratorio", "Laboratorio de emergencia"]
                else:
                    kinds = ["Banco de sangre"]
                if section in ("Camas", "Vehículos", "Equipos médicos especiales", "Plantas eléctricas"):
                    for index in range(len(kinds)):
                        payload[f"qty_{index}_operational"] = "0"
                        payload[f"qty_{index}_unavailable"] = "0"
                elif section == "Quirófano":
                    for index in range(len(kinds)):
                        payload[f"qty_{index}_operational"] = "0"
                        payload[f"qty_{index}_unavailable"] = "0"
                response = self.client.post(
                    f"/inventory/{self.center['id']}/{section}", data=payload,
                )
                self.assertEqual(response.status_code, 302)
        self.client.post(
            f"/inventory/{self.center['id']}/Camas",
            data={"csrf_token": csrf, "action": "submit"},
        )
        self.assertTrue(self.store.submission(token, self.center["id"])["loaded"])

    def test_admin_can_view_report_accounts_and_download_pdf(self):
        self.login("admin", ADMIN_PASSWORD)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn(b"Estado semanal", self.client.get("/").data)
        pdf = self.client.get("/reports.pdf?category=Camas")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertEqual(self.client.get("/admin/accounts").status_code, 200)

    def test_admin_can_create_center_account_and_update_account_state(self):
        self.login("admin", ADMIN_PASSWORD)
        csrf = self.authenticated_csrf()
        self.store.import_centers(self.admin_token, [{
            "number": 2, "center": "Centro Sur - Sur",
            "username": "centro.sur@example.com",
        }])
        center = self.store.centers(self.admin_token)[1]
        response = self.client.post("/admin/accounts", data={
            "csrf_token": csrf, "action": "create_account",
            "center_id": center["id"], "username": "norte2",
            "password": CENTER_PASSWORD, "confirmation": CENTER_PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        user = next(
            item for item in self.store.users(self.admin_token)
            if item["center_id"] == center["id"]
        )
        self.assertEqual(user["username"], "norte2")

        response = self.client.post("/admin/accounts", data={
            "csrf_token": csrf, "action": "toggle", "user_id": user["id"],
            "active": "0",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(next(
            item for item in self.store.users(self.admin_token)
            if item["center_id"] == center["id"]
        )["active"])

    def test_military_account_is_limited_to_its_report(self):
        self.login("admin", ADMIN_PASSWORD)
        csrf = self.authenticated_csrf()
        accounts_page = self.client.get("/admin/accounts")
        self.assertIn(b"Crear cuenta de instituci", accounts_page.data)
        response = self.client.post("/admin/accounts", data={
            "csrf_token": csrf, "action": "create_military_account",
            "component": "Guardia Nacional Bolivariana", "username": "guardia",
            "password": CENTER_PASSWORD, "confirmation": CENTER_PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        military_user = next(
            user for user in self.store.users(self.admin_token)
            if user["username"] == "guardia"
        )
        self.assertEqual(military_user["account_type"], "military")

        military_client = self.app.test_client()
        login_page = military_client.get("/login")
        login_csrf = re.search(
            rb'name="csrf_token" value="([^"]+)"', login_page.data,
        ).group(1).decode()
        login_response = military_client.post("/login", data={
            "csrf_token": login_csrf, "username": "guardia",
            "password": CENTER_PASSWORD,
        })
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(military_client.get("/").headers["Location"], "/military")
        page = military_client.get("/military")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Registro de Militares Fallecidos", page.data)
        self.assertNotIn(b"CAMAS HOSPITALARIAS", page.data)
        for option in (*MILITARY_GRADES, *MILITARY_CAUSES, *MILITARY_REDI):
            self.assertIn(f'value="{option}"'.encode(), page.data)
        self.assertIn(b'name="birth_date" type="date"', page.data)
        self.assertIn(b'name="death_date" type="date"', page.data)
        self.assertEqual(military_client.get("/reports.pdf?category=Camas").status_code, 403)
        self.assertEqual(
            military_client.get(f"/inventory/{military_user['center_id']}").status_code,
            403,
        )
        military_csrf = re.search(
            rb'name="csrf_token" value="([^"]+)"', page.data,
        ).group(1).decode()
        response = military_client.post("/military", data={
            "csrf_token": military_csrf, "full_name": "Persona Fallecida",
            "grade": "TTE", "cedula": "V-12345678",
            "birth_date": "1990-05-10", "unit": "Unidad Uno",
            "death_date": "2026-10-28", "cause": "Accidente de tránsito",
            "redi": "REDI Capital", "zodi": "Zodi Uno",
        })
        self.assertEqual(response.status_code, 302)
        page = military_client.get("/military")
        self.assertIn(b"PERSONA FALLECIDA", page.data)
        self.assertIn(b"ZODI UNO", page.data)
        self.assertIn(b"UNIDAD UNO", page.data)
        self.assertIn(b"Guardia Nacional Bolivariana", page.data)
        military_pdf = military_client.get("/military/report.pdf")
        self.assertEqual(military_pdf.mimetype, "application/pdf")
        import pymupdf
        with pymupdf.open(stream=military_pdf.data, filetype="pdf") as document:
            pdf_text = document[0].get_text()
        self.assertIn("Registro de Militares Fallecidos en el Componente Guardia Nacional Bolivariana", pdf_text)
        for heading in (
            "NRO.", "GDO/JQUIA", "NOMBRE Y APELLIDOS", "CEDULA",
            "FECHA NAC.", "EDAD", "FECHA DE LA MUERTE",
            "CAUSAS DE LA MUERTE", "REDI", "ZODI", "UNIDAD",
        ):
            self.assertIn(heading, pdf_text)
        self.assertIn("PERSONA FALLECIDA", pdf_text)

        self.assertEqual(self.client.get("/military").status_code, 200)
        self.assertIn(b"PERSONA FALLECIDA", self.client.get("/military").data)
        self.assertEqual(self.client.get("/military/report.pdf").mimetype, "application/pdf")
        self.assertEqual(
            self.client.get(f"/admin/accounts").status_code,
            200,
        )

    def test_forced_password_change_requires_confirmation(self):
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE users SET must_change=1 WHERE username='norte'",
            )
        self.login("norte", CENTER_PASSWORD)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/password", response.headers["Location"])
        csrf = self.authenticated_csrf()
        mismatch = self.client.post("/password", data={
            "csrf_token": csrf, "current_password": CENTER_PASSWORD,
            "new_password": "New-center-password-789",
            "confirmation": "different",
        })
        self.assertEqual(mismatch.status_code, 303)
        with self.client.session_transaction() as browser_session:
            auth_token = browser_session["token"]
        self.assertTrue(self.store.identity(auth_token)["must_change"])
        changed = self.client.post("/password", data={
            "csrf_token": csrf, "current_password": CENTER_PASSWORD,
            "new_password": "New-center-password-789",
            "confirmation": "New-center-password-789",
        })
        self.assertEqual(changed.status_code, 302)
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("token", browser_session)

    def test_post_rejects_missing_csrf_token(self):
        response = self.client.post("/login", data={
            "username": "admin", "password": ADMIN_PASSWORD,
        })
        self.assertEqual(response.status_code, 400)

    def test_vercel_bootstrap_creates_admin_and_imports_catalog_once(self):
        blank_store = Store(Path(self.directory.name) / "blank.sqlite3")
        with patch.dict(os.environ, {
            "BOOTSTRAP_ADMIN_USERNAME": "admin",
            "BOOTSTRAP_ADMIN_PASSWORD": ADMIN_PASSWORD,
        }):
            create_app(blank_store, secret_key="test-secret")
            token = blank_store.login("admin", ADMIN_PASSWORD)
            self.assertEqual(len(blank_store.centers(token)), len(load_center_catalog()))
            self.assertEqual(blank_store.users(token), [])

    def test_vercel_bootstrap_rejects_incomplete_credentials(self):
        with patch.dict(os.environ, {
            "BOOTSTRAP_ADMIN_USERNAME": "admin",
        }):
            with self.assertRaisesRegex(InventoryError, "Configura"):
                create_app(self.store, secret_key="test-secret")

    def test_vercel_requires_postgresql_database_url(self):
        with patch.dict(os.environ, {"VERCEL": "1", "DATABASE_URL": ""}):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                create_app(secret_key="test-secret")

    def test_vercel_static_and_institutional_assets_are_available(self):
        with self.client.get("/app.css") as response:
            self.assertEqual(response.status_code, 200)
        with self.client.get("/escudo.png") as response:
            self.assertEqual(response.mimetype, "image/png")
        with self.client.get("/cintillo.png") as response:
            self.assertEqual(response.mimetype, "image/png")


if __name__ == "__main__":
    unittest.main()
