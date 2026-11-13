import re
import tempfile
import tomllib
import unittest
import os
from html import unescape
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
                form = re.search(
                    rb'<form[^>]*action="([^"]+)"[^>]*id="inventory-form"[^>]*>(.*?)</form>',
                    page.data, re.S,
                )
                self.assertIsNotNone(form)
                load_url = unescape(form.group(1).decode())
                self.assertEqual(load_url, f"/inventory/{self.center['id']}/save")
                section_field = re.search(rb'name="section" value="([^"]+)"', form.group(2))
                self.assertIsNotNone(section_field)
                self.assertEqual(unescape(section_field.group(1).decode()), section)
                payload = {"csrf_token": csrf, "action": "load", "section": section, **fields}
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
                for attempt in range(2):
                    response = self.client.post(load_url, data=payload, follow_redirects=True)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(self.store.section_loads(token, self.center["id"])[section])
                    edit_form = next(
                        (action, body) for action, body in re.findall(
                            rb'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>',
                            response.data, re.S,
                        ) if b'name="action" value="edit"' in body
                    )
                    edit_url = unescape(edit_form[0].decode())
                    self.assertEqual(edit_url, load_url)
                    edit_section = re.search(
                        rb'name="section" value="([^"]+)"', edit_form[1],
                    )
                    self.assertIsNotNone(edit_section)
                    self.assertEqual(unescape(edit_section.group(1).decode()), section)
                    if attempt == 0:
                        edited = self.client.post(edit_url, data={
                            "csrf_token": csrf, "action": "edit", "section": section,
                        }, follow_redirects=True)
                        self.assertEqual(edited.status_code, 200)
                        self.assertFalse(self.store.section_loads(token, self.center["id"])[section])
                        self.assertIn(b'id="inventory-form"', edited.data)
        submit_form = next(
            (action, body) for action, body in re.findall(
                rb'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>',
                response.data, re.S,
            ) if b'name="action" value="submit"' in body
        )
        submit_section = re.search(rb'name="section" value="([^"]+)"', submit_form[1])
        self.assertIsNotNone(submit_section)
        submitted = self.client.post(
            unescape(submit_form[0].decode()),
            data={
                "csrf_token": csrf, "action": "submit",
                "section": unescape(submit_section.group(1).decode()),
            },
            follow_redirects=True,
        )
        self.assertEqual(submitted.status_code, 200)
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
            has_banner = bool(document[0].get_xobjects())
        self.assertIn("Registro de Militares Fallecidos en el Componente Guardia Nacional Bolivariana", pdf_text)
        for heading in (
            "NRO.", "GDO/JQUIA", "NOMBRE Y APELLIDOS", "CEDULA",
            "FECHA NAC.", "EDAD", "FECHA DE LA MUERTE",
            "CAUSAS DE LA MUERTE", "REDI", "ZODI", "UNIDAD",
        ):
            self.assertIn(heading, pdf_text)
        self.assertIn("PERSONA FALLECIDA", pdf_text)
        self.assertIn("FUENTE: Sala Situacional/DIGESALUD", pdf_text)
        self.assertTrue(has_banner)

        self.assertEqual(self.client.get("/military").status_code, 200)
        admin_page = self.client.get("/military")
        self.assertIn(b"PERSONA FALLECIDA", admin_page.data)
        self.assertIn(b"Todos los componentes", admin_page.data)
        self.assertIn(b"Aviaci\xc3\xb3n Militar Bolivariana", admin_page.data)

        self.store.create_military_account(
            self.admin_token, "Ejército Bolivariano", "ejercito", CENTER_PASSWORD,
        )
        army = self.store.login("ejercito", CENTER_PASSWORD)
        self.store.add_military_record(
            army, "GJ", "OTRO MILITAR", "V-87654321", "1980-01-01",
            "2020-01-01", "Homicidio", "REDI Central", "ZODI DOS", "UNIDAD DOS",
        )
        selected_pdf = self.client.get(
            "/military/report.pdf?component=Ej%C3%A9rcito+Bolivariano",
        )
        self.assertEqual(selected_pdf.mimetype, "application/pdf")
        with pymupdf.open(stream=selected_pdf.data, filetype="pdf") as document:
            self.assertEqual(len(document), 1)
            selected_text = document[0].get_text()
        self.assertIn("Ejército Bolivariano", selected_text)
        self.assertIn("OTRO MILITAR", selected_text)
        self.assertNotIn("PERSONA FALLECIDA", selected_text)

        all_pdf = self.client.get("/military/report.pdf")
        with pymupdf.open(stream=all_pdf.data, filetype="pdf") as document:
            self.assertEqual(len(document), 2)
            all_text = "\n".join(page.get_text() for page in document)
        self.assertIn("PERSONA FALLECIDA", all_text)
        self.assertIn("OTRO MILITAR", all_text)
        self.assertIn("FUENTE: Sala Situacional/DIGESALUD", all_text)
        invalid_pdf = self.client.get("/military/report.pdf?component=Desconocido")
        self.assertEqual(invalid_pdf.status_code, 400)
        self.assertEqual(
            self.client.get(f"/admin/accounts").status_code,
            200,
        )

    def test_military_search_filters_screen_and_pdf_by_death_month_and_year(self):
        import pymupdf

        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        military_token = self.store.login("guardia", CENTER_PASSWORD)
        for name, death_date in (
            ("COINCIDE", "2026-10-15"),
            ("OTRO MES", "2026-11-15"),
            ("OTRO AÑO", "2025-10-15"),
        ):
            self.store.add_military_record(
                military_token, "TTE", name, "V-12345678", "1990-01-01",
                death_date, "Muerte natural", "REDI Capital", "ZODI", "UNIDAD",
            )
        self.login("admin", ADMIN_PASSWORD)
        query = "?month=10&year=2026"
        page = self.client.get("/military" + query)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"COINCIDE", page.data)
        self.assertNotIn(b"OTRO MES", page.data)
        self.assertNotIn("OTRO AÑO".encode(), page.data)
        self.assertIn(b'value="10" selected', page.data)
        year_select = re.search(rb'<select name="year">(.*?)</select>', page.data, re.S).group(1)
        self.assertIn(b'value="2026" selected', year_select)
        self.assertIn(b'value="2025"', year_select)
        self.assertEqual(year_select.count(b'value="2026"'), 1)
        for path in ("/military", "/military/report.pdf"):
            for invalid in ("?month=13", "?month=abc", "?year=0", "?year=10000"):
                with self.subTest(path=path, invalid=invalid):
                    self.assertEqual(self.client.get(path + invalid).status_code, 400)
        pdf = self.client.get("/military/report.pdf" + query)
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.data, filetype="pdf") as document:
            text = "\n".join(page.get_text() for page in document)
        self.assertIn("COINCIDE", text)
        self.assertNotIn("OTRO MES", text)
        self.assertNotIn("OTRO AÑO", text)
        month_only = self.client.get("/military?month=10")
        self.assertIn("OTRO AÑO".encode(), month_only.data)
        self.assertNotIn(b"OTRO MES", month_only.data)
        year_only = self.client.get("/military?year=2026")
        self.assertIn(b"OTRO MES", year_only.data)
        self.assertNotIn("OTRO AÑO".encode(), year_only.data)

    def test_military_search_combines_redi_and_cause_with_existing_filters(self):
        import pymupdf

        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        military_token = self.store.login("guardia", CENTER_PASSWORD)
        for name, redi, cause, death_date in (
            ("COINCIDE", "REDI Capital", "Homicidio", "2026-10-15"),
            ("OTRA REDI", "REDI Central", "Homicidio", "2026-10-15"),
            ("OTRA CAUSA", "REDI Capital", "Muerte natural", "2026-10-15"),
            ("OTRO PERIODO", "REDI Capital", "Homicidio", "2025-11-15"),
        ):
            self.store.add_military_record(
                military_token, "TTE", name, "V-12345678", "1990-01-01",
                death_date, cause, redi, "ZODI", "UNIDAD",
            )
        self.login("admin", ADMIN_PASSWORD)
        filters = {
            "component": "Guardia Nacional Bolivariana",
            "month": "10", "year": "2026", "redi": "REDI Capital", "cause": "Homicidio",
        }
        page = self.client.get("/military", query_string=filters)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"COINCIDE", page.data)
        for excluded in (b"OTRA REDI", b"OTRA CAUSA", b"OTRO PERIODO"):
            self.assertNotIn(excluded, page.data)
        self.assertIn(b'value="REDI Capital" selected', page.data)
        self.assertIn(b'value="Homicidio" selected', page.data)
        pdf = self.client.get("/military/report.pdf", query_string=filters)
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.data, filetype="pdf") as document:
            text = "\n".join(page.get_text() for page in document)
        self.assertIn("COINCIDE", text)
        for excluded in ("OTRA REDI", "OTRA CAUSA", "OTRO PERIODO"):
            self.assertNotIn(excluded, text)
        redi_only = self.client.get("/military", query_string={"redi": "REDI Capital"})
        self.assertIn(b"OTRA CAUSA", redi_only.data)
        self.assertNotIn(b"OTRA REDI", redi_only.data)
        cause_only = self.client.get("/military", query_string={"cause": "Homicidio"})
        self.assertIn(b"OTRA REDI", cause_only.data)
        self.assertNotIn(b"OTRA CAUSA", cause_only.data)
        for path in ("/military", "/military/report.pdf"):
            for invalid in ({"redi": "REDI inexistente"}, {"cause": "Causa inexistente"}):
                with self.subTest(path=path, invalid=invalid):
                    self.assertEqual(self.client.get(path, query_string=invalid).status_code, 400)

    def test_military_registration_rejects_each_missing_or_blank_required_field(self):
        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        self.login("guardia", CENTER_PASSWORD)
        csrf = self.authenticated_csrf()
        fields = {
            "grade": "TTE", "full_name": "PERSONA DE PRUEBA", "cedula": "V-12345678",
            "birth_date": "1990-01-01", "death_date": "2026-10-15",
            "cause": "Muerte natural", "redi": "REDI Capital",
            "zodi": "ZODI CAPITAL", "unit": "UNIDAD DE PRUEBA",
        }
        for field in fields:
            for value in (None, "", "   "):
                with self.subTest(field=field, value=value):
                    payload = {"csrf_token": csrf, **fields}
                    if value is None:
                        del payload[field]
                    else:
                        payload[field] = value
                    response = self.client.post(
                        "/military", data=payload,
                        headers={"Referer": "http://localhost/military"},
                    )
                    self.assertEqual(response.status_code, 303)
                    page = self.client.get(response.headers["Location"])
                    self.assertIn(b"notice-error", page.data)
                    self.assertNotIn(b"Registro ingresado.", page.data)
                    self.assertEqual(self.store.military_records(self.admin_token), [])
        response = self.client.post("/military", data={"csrf_token": csrf, **fields})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.store.military_records(self.admin_token)), 1)

    def test_health_centers_register_deaths_privately_with_a_separate_single_table_consolidated_pdf(self):
        import pymupdf

        self.store.create_center(
            self.admin_token, "Centro Sur", "Sur", "sur", CENTER_PASSWORD,
        )
        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        guard = self.store.login("guardia", CENTER_PASSWORD)
        south = self.store.login("sur", CENTER_PASSWORD)
        self.store.add_military_record(
            guard, "TTE", "REGISTRO COMPONENTE", "V-1", "1990-01-01",
            "2026-10-15", "Muerte natural", "REDI Capital", "ZODI", "UNIDAD",
        )
        self.store.add_military_record(
            south, "TTE", "FALLECIDO SUR", "V-2", "1990-01-01",
            "2026-10-15", "Muerte natural", "REDI Capital", "ZODI", "UNIDAD",
            component="Ejército Bolivariano",
        )
        self.login("norte", CENTER_PASSWORD)
        csrf = self.authenticated_csrf()
        inventory_page = self.client.get(f"/inventory/{self.center['id']}")
        self.assertIn(b'href="/health/military"', inventory_page.data)
        health_page = self.client.get("/health/military")
        self.assertEqual(health_page.status_code, 200)
        self.assertIn(b"Selecciona el componente", health_page.data)
        self.assertNotIn(b"FALLECIDO SUR", health_page.data)
        self.assertNotIn(b"REGISTRO COMPONENTE", health_page.data)
        fields = {
            "csrf_token": csrf, "grade": "CAP", "full_name": "FALLECIDO NORTE",
            "cedula": "V-3", "birth_date": "1990-01-01", "death_date": "2026-11-15",
            "cause": "Homicidio", "redi": "REDI Central", "zodi": "ZODI NORTE",
            "unit": "UNIDAD", "component": "Armada Bolivariana",
        }
        for field in ("component", "grade", "full_name", "cedula", "birth_date",
                      "death_date", "cause", "redi", "zodi", "unit"):
            invalid = {**fields, field: ""}
            response = self.client.post("/health/military", data=invalid)
            self.assertEqual(response.status_code, 303, field)
        before = self.store.submission(self.store.login("norte", CENTER_PASSWORD), self.center["id"])
        response = self.client.post("/health/military", data=fields)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/health/military")
        after = self.store.submission(self.store.login("norte", CENTER_PASSWORD), self.center["id"])
        self.assertEqual(before, after)
        private_page = self.client.get("/health/military?center_id=2")
        self.assertIn(b"FALLECIDO NORTE", private_page.data)
        self.assertNotIn(b"FALLECIDO SUR", private_page.data)
        self.assertEqual(self.client.get("/military").status_code, 403)
        north_pdf = self.client.get("/health/military/report.pdf")
        self.assertEqual(north_pdf.status_code, 200)
        with pymupdf.open(stream=north_pdf.data, filetype="pdf") as document:
            text = document[0].get_text()
        self.assertIn("Centro Norte", text)
        self.assertNotIn("FALLECIDO SUR", text)
        with self.client.session_transaction() as browser_session:
            browser_session["token"] = self.admin_token
        consolidated = self.client.get("/health/military/report.pdf")
        self.assertEqual(consolidated.status_code, 200)
        with pymupdf.open(stream=consolidated.data, filetype="pdf") as document:
            self.assertEqual(len(document), 1)
            text = document[0].get_text()
            self.assertTrue(document[0].get_xobjects())
        for expected in ("FALLECIDO NORTE", "FALLECIDO SUR", "Centro Norte", "Centro Sur",
                         "CENTRO DE SALUD", "COMPONENTE", "Armada Bolivariana",
                         "Ejército Bolivariano", "FUENTE: Sala Situacional/DIGESALUD"):
            self.assertIn(expected, " ".join(text.split()))
        self.assertNotIn("REGISTRO COMPONENTE", text)
        self.assertEqual(text.count("NRO."), 1)
        filtered = self.client.get("/health/military?month=11&cause=Homicidio")
        self.assertIn(b"FALLECIDO NORTE", filtered.data)
        self.assertNotIn(b"FALLECIDO SUR", filtered.data)
        component_report = self.client.get("/military")
        self.assertIn(b"REGISTRO COMPONENTE", component_report.data)
        self.assertNotIn(b"FALLECIDO NORTE", component_report.data)
        with self.client.session_transaction() as browser_session:
            browser_session["token"] = guard
        for path in ("/health/military", "/health/military/report.pdf"):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post("/health/military", data=fields).status_code, 403)

    def test_traffic_registry_is_private_complete_and_independent_with_filtered_consolidation(self):
        import pymupdf

        self.store.create_center(self.admin_token, "Centro Sur", "Sur", "sur", CENTER_PASSWORD)
        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        self.login("norte", CENTER_PASSWORD)
        csrf = self.authenticated_csrf()
        inventory = self.client.get(f"/inventory/{self.center['id']}")
        self.assertIn(b'href="/health/traffic"', inventory.data)
        page = self.client.get("/health/traffic")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Pacientes Militares atendidos por Accidentes de Tránsito".encode(), page.data)
        for field in ("attention_date", "accident_type", "patient_condition", "traffic_role"):
            self.assertIn(f'name="{field}"'.encode(), page.data)
        self.assertNotIn(b'name="death_date"', page.data)
        fields = {
            "grade": "CAP", "full_name": "Paciente Norte", "cedula": "V-12345678",
            "birth_date": "2000-10-16", "attention_date": "2026-10-15",
            "accident_type": "Moto", "patient_condition": "Heridas leves",
            "traffic_role": "Conductor", "redi": "REDI Capital", "zodi": "zodi norte",
            "unit": "unidad norte", "component": "Armada Bolivariana",
        }
        for field in fields:
            for value in (None, "", "   "):
                invalid = {**fields}
                if value is None:
                    del invalid[field]
                else:
                    invalid[field] = value
                with self.subTest(field=field, value=value):
                    response = self.client.post(
                        "/health/traffic", data={"csrf_token": csrf, **invalid},
                    )
                    self.assertEqual(response.status_code, 303)
                    self.assertEqual(self.store.traffic_records(self.admin_token), [])
        before = self.store.submission(self.store.login("norte", CENTER_PASSWORD), self.center["id"])
        response = self.client.post("/health/traffic", data={"csrf_token": csrf, **fields})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/health/traffic")
        north = self.store.login("norte", CENTER_PASSWORD)
        self.assertEqual(self.store.submission(north, self.center["id"]), before)
        rows = self.store.traffic_records(north)
        self.assertEqual(rows[0]["age"], 25)
        self.assertEqual(rows[0]["full_name"], "PACIENTE NORTE")
        self.assertEqual(rows[0]["zodi"], "ZODI NORTE")
        self.assertEqual(rows[0]["unit"], "UNIDAD NORTE")
        south = self.store.login("sur", CENTER_PASSWORD)
        self.assertEqual(self.store.traffic_records(south), [])
        self.store.add_traffic_record(
            south, **{**fields, "full_name": "PACIENTE SUR", "attention_date": "2025-11-15",
                      "component": "Ejército Bolivariano", "accident_type": "Carro"},
        )
        page = self.client.get("/health/traffic?center_id=2")
        self.assertIn(b"PACIENTE NORTE", page.data)
        self.assertNotIn(b"PACIENTE SUR", page.data)
        self.assertEqual(self.store.military_records(self.admin_token, account_type="health"), [])
        private_pdf = self.client.get("/health/traffic/report.pdf")
        self.assertEqual(private_pdf.status_code, 200)
        with pymupdf.open(stream=private_pdf.data, filetype="pdf") as document:
            text = " ".join(document[0].get_text().split())
        self.assertIn("PACIENTE NORTE", text)
        self.assertNotIn("PACIENTE SUR", text)
        with self.client.session_transaction() as browser_session:
            browser_session["token"] = self.admin_token
        consolidated = self.client.get("/health/traffic/report.pdf")
        self.assertEqual(consolidated.status_code, 200)
        with pymupdf.open(stream=consolidated.data, filetype="pdf") as document:
            self.assertEqual(len(document), 1)
            self.assertTrue(document[0].get_xobjects())
            text = " ".join(document[0].get_text().split())
        for value in ("PACIENTE NORTE", "PACIENTE SUR", "Centro Norte", "Centro Sur",
                      "FECHA DE ATENCIÓN", "TIPO DE ACCIDENTE", "CONDICIÓN", "PARTICIPACIÓN",
                      "Conductor", "Heridas leves", "FUENTE: Sala Situacional/DIGESALUD"):
            self.assertIn(value, text)
        self.assertNotIn("FECHA DE LA MUERTE", text)
        filters = {"month": "10", "year": "2026", "cause": "Moto",
                   "component": "Armada Bolivariana", "redi": "REDI Capital"}
        page = self.client.get("/health/traffic", query_string=filters)
        self.assertIn(b"PACIENTE NORTE", page.data)
        self.assertNotIn(b"PACIENTE SUR", page.data)
        pdf = self.client.get("/health/traffic/report.pdf", query_string=filters)
        with pymupdf.open(stream=pdf.data, filetype="pdf") as document:
            text = document[0].get_text()
        self.assertIn("PACIENTE NORTE", text)
        self.assertNotIn("PACIENTE SUR", text)
        self.assertEqual(
            self.client.post("/health/traffic", data={"csrf_token": csrf, **fields}).status_code, 403,
        )
        guard = self.store.login("guardia", CENTER_PASSWORD)
        with self.client.session_transaction() as browser_session:
            browser_session["token"] = guard
        for path in ("/health/traffic", "/health/traffic/report.pdf"):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(
            self.client.post("/health/traffic", data={"csrf_token": csrf, **fields}).status_code, 403,
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
