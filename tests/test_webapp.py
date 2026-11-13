import re
import tempfile
import tomllib
import unittest
import os
from html import unescape
from pathlib import Path
from unittest.mock import patch

from store import (
    BED_TYPES, AccessError, InventoryError, MILITARY_CAUSES, MILITARY_GRADES, MILITARY_REDI,
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

    def test_login_displays_shield_above_login_card(self):
        response = self.client.get("/login")
        html = response.data.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("<h1>Iniciar sesión</h1>", html)
        self.assertIn('src="/escudo.png"', html)
        self.assertLess(html.index('class="login-shield"'), html.index('class="login-card"'))

    def test_military_patient_menu_groups_registries_and_returns_to_previous_menu(self):
        response = self.client.get("/health/patients")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        self.login("norte", CENTER_PASSWORD)
        for token, home_path, menu_path, title in (
            (self.store.login("norte", CENTER_PASSWORD), f"/inventory/{self.center['id']}",
             "/health/patients", "Registros de Pacientes Militares"),
            (self.admin_token, "/", "/admin/military", "Registros de Militares"),
        ):
            with self.subTest(home=home_path):
                with self.client.session_transaction() as browser_session:
                    browser_session["token"] = token
                home = self.client.get(home_path)
                self.assertIn(f'href="{menu_path}"'.encode(), home.data)
                self.assertNotIn(b'href="/health/military"', home.data)
                self.assertNotIn(b'href="/health/traffic"', home.data)
                menu = self.client.get(menu_path)
                self.assertEqual(menu.status_code, 200)
                self.assertIn(f"<h1>{title}</h1>".encode(), menu.data)
                self.assertIn(b'href="/">Regresar</a>', menu.data)
                response = self.client.get("/", follow_redirects=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.request.path, home_path)
                for path in ("/health/military", "/health/traffic"):
                    self.assertIn(f'href="{path}"'.encode(), menu.data)
                    page = self.client.get(path)
                    self.assertEqual(page.status_code, 200)
                    self.assertIn(f'href="{menu_path}">Regresar</a>'.encode(), page.data)
                    self.assertNotIn(b'class="admin-nav"', page.data)
                    links = re.findall(rb'<a class="button[^"]*" href="([^"]+)">', page.data)
                    self.assertEqual(links, [menu_path.encode()])
                if token == self.admin_token:
                    for path in ("/military", "/military/traffic"):
                        self.assertIn(f'href="{path}"'.encode(), menu.data)
                        page = self.client.get(path)
                        self.assertEqual(page.status_code, 200)
                        links = re.findall(rb'<a class="button[^"]*" href="([^"]+)">', page.data)
                        self.assertEqual(links, [b"/admin/military"])
                        self.assertNotIn(b'class="admin-nav"', page.data)
                        self.assertIn(b'class="filter-grid"', page.data)
                    self.assertIn(b"Militares fallecidos", menu.data)
                    self.assertIn("Militares Atendidos en Centros de Salud por Accidentes de Tránsito".encode(), menu.data)
                else:
                    self.assertNotIn(b'href="/military"', menu.data)
                    self.assertNotIn(b'href="/military/traffic"', menu.data)
                    self.assertEqual(self.client.get("/admin/military").status_code, 403)
                    self.assertEqual(self.client.get("/military/records").status_code, 403)
        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        with self.client.session_transaction() as browser_session:
            browser_session["token"] = self.store.login("guardia", CENTER_PASSWORD)
        self.assertEqual(self.client.get("/health/patients").status_code, 403)
        self.assertEqual(self.client.get("/admin/military").status_code, 403)
        self.assertNotIn(b'href="/health/patients"', self.client.get("/military").data)
        menu = self.client.get("/military/records")
        self.assertEqual(menu.status_code, 200)
        self.assertIn(b'href="/military"', menu.data)
        self.assertIn(b'href="/military/traffic"', menu.data)
        self.assertNotIn(b'href="/health/military"', menu.data)
        self.assertNotIn(b'href="/health/traffic"', menu.data)
        for path in ("/military", "/military/traffic"):
            page = self.client.get(path)
            self.assertNotIn(b'class="admin-nav"', page.data)
            links = re.findall(rb'<a class="button[^"]*" href="([^"]+)">', page.data)
            self.assertEqual(links, [b"/military/records"])

    def test_components_register_traffic_with_manual_attention_center_and_separate_consolidation(self):
        import pymupdf

        self.assertEqual(self.client.get("/military/traffic").status_code, 302)
        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        self.store.create_military_account(
            self.admin_token, "Armada Bolivariana", "armada", CENTER_PASSWORD,
        )
        self.login("guardia", CENTER_PASSWORD)
        csrf = self.authenticated_csrf()
        death_page = self.client.get("/military")
        self.assertIn(b'href="/military/records">Regresar</a>', death_page.data)
        page = self.client.get("/military/traffic")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Militares Involucrados en Accidentes de Tránsito".encode(), page.data)
        self.assertIn(b'name="attention_center" maxlength="160" required', page.data)
        self.assertNotIn(b'<select name="component"', page.data)
        fields = {
            "grade": "CAP", "full_name": "Paciente componente", "cedula": "V-12345678",
            "birth_date": "2000-10-16", "attention_date": "2026-10-15",
            "accident_type": "Moto", "patient_condition": "Heridas graves",
            "traffic_role": "Conductor", "redi": "REDI Capital", "zodi": "zodi prueba",
            "unit": "unidad prueba", "attention_center": "hospital publico de prueba",
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
                        "/military/traffic", data={"csrf_token": csrf, **invalid},
                    )
                    self.assertEqual(response.status_code, 303)
                    self.assertEqual(self.store.traffic_records(
                        self.admin_token, account_type="military",
                    ), [])
        self.assertEqual(self.client.post("/military/traffic", data=fields).status_code, 400)
        response = self.client.post(
            "/military/traffic",
            data={"csrf_token": csrf, **fields, "component": "Armada Bolivariana", "center_id": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/military/traffic")
        rows = self.store.traffic_records(self.admin_token, account_type="military")
        self.assertEqual(rows[0]["component"], "Guardia Nacional Bolivariana")
        self.assertEqual(rows[0]["center_name"], "HOSPITAL PUBLICO DE PRUEBA")
        self.assertEqual(rows[0]["age"], 25)
        armada = self.store.login("armada", CENTER_PASSWORD)
        self.store.add_traffic_record(
            armada, **{**fields, "full_name": "PACIENTE ARMADA", "attention_date": "2025-11-15",
                       "attention_center": "hospital segundo"},
            account_type="military",
        )
        page = self.client.get("/military/traffic?component=Armada+Bolivariana")
        self.assertIn(b"PACIENTE COMPONENTE", page.data)
        self.assertNotIn(b"PACIENTE ARMADA", page.data)
        pdf = self.client.get("/military/traffic/report.pdf")
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.data, filetype="pdf") as document:
            text = " ".join(document[0].get_text().split())
        self.assertIn("HOSPITAL PUBLICO DE PRUEBA", text)
        self.assertNotIn("PACIENTE ARMADA", text)
        north = self.store.login("norte", CENTER_PASSWORD)
        self.store.add_traffic_record(
            north, **{**fields, "full_name": "PACIENTE CENTRO", "component": "Armada Bolivariana"},
        )
        with self.client.session_transaction() as browser_session:
            browser_session["token"] = north
        for path in ("/military/traffic", "/military/traffic/report.pdf"):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post(
            "/military/traffic", data={"csrf_token": csrf, **fields},
        ).status_code, 403)
        with self.client.session_transaction() as browser_session:
            browser_session["token"] = self.admin_token
        page = self.client.get("/military/traffic")
        self.assertIn(b"PACIENTE COMPONENTE", page.data)
        self.assertIn(b"PACIENTE ARMADA", page.data)
        self.assertNotIn(b"PACIENTE CENTRO", page.data)
        self.assertNotIn(b'name="attention_center"', page.data)
        pdf = self.client.get("/military/traffic/report.pdf")
        with pymupdf.open(stream=pdf.data, filetype="pdf") as document:
            self.assertEqual(len(document), 1)
            self.assertTrue(document[0].get_xobjects())
            text = " ".join(document[0].get_text().split())
        for value in ("Militares Involucrados en Accidentes de Tránsito", "PACIENTE COMPONENTE",
                      "PACIENTE ARMADA", "HOSPITAL PUBLICO DE PRUEBA", "HOSPITAL SEGUNDO",
                      "FUENTE: Sala Situacional/DIGESALUD"):
            self.assertIn(value, text)
        self.assertNotIn("PACIENTE CENTRO", text)
        filters = {"month": "10", "year": "2026", "cause": "Moto",
                   "component": "Guardia Nacional Bolivariana", "redi": "REDI Capital"}
        page = self.client.get("/military/traffic", query_string=filters)
        self.assertIn(b"PACIENTE COMPONENTE", page.data)
        self.assertNotIn(b"PACIENTE ARMADA", page.data)
        pdf = self.client.get("/military/traffic/report.pdf", query_string=filters)
        with pymupdf.open(stream=pdf.data, filetype="pdf") as document:
            text = " ".join(document[0].get_text().split())
        self.assertIn("PACIENTE COMPONENTE", text)
        self.assertNotIn("PACIENTE ARMADA", text)
        self.assertEqual(self.client.post(
            "/military/traffic", data={"csrf_token": csrf, **fields},
        ).status_code, 403)

    def test_admin_edits_and_confirms_deletion_in_all_four_registries(self):
        import pymupdf

        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        north = self.store.login("norte", CENTER_PASSWORD)
        guard = self.store.login("guardia", CENTER_PASSWORD)
        base = {
            "grade": "CAP", "full_name": "Paciente original", "cedula": "V-12345678",
            "birth_date": "2000-10-16", "redi": "REDI Capital", "zodi": "ZODI PRUEBA",
            "unit": "UNIDAD PRUEBA",
        }
        deaths = {**base, "death_date": "2026-10-15", "cause": "Muerte natural"}
        traffic = {
            **base, "attention_date": "2026-10-15", "accident_type": "Moto",
            "patient_condition": "Heridas leves", "traffic_role": "Conductor",
        }
        for owner, component in ((guard, None), (north, "Armada Bolivariana")):
            self.store.add_military_record(
                owner, deaths["grade"], deaths["full_name"], deaths["cedula"],
                deaths["birth_date"], deaths["death_date"], deaths["cause"],
                deaths["redi"], deaths["zodi"], deaths["unit"], component=component,
            )
        self.store.add_traffic_record(north, **traffic, component="Armada Bolivariana")
        self.store.add_traffic_record(
            guard, **traffic, account_type="military", attention_center="Hospital público",
        )
        cases = (
            ("component-deaths", "/military", "military", False, deaths),
            ("health-deaths", "/health/military", "health", False, deaths),
            ("health-traffic", "/health/traffic", "health", True, traffic),
            ("component-traffic", "/military/traffic", "military", True, traffic),
        )
        self.login("admin", ADMIN_PASSWORD)
        csrf = self.authenticated_csrf()
        for registry, path, account_type, is_traffic, fields in cases:
            with self.subTest(registry=registry):
                read = self.store.traffic_records if is_traffic else self.store.military_records
                original = read(self.admin_token, account_type=account_type)[0]
                record_id = original["id"]
                edit = f"/admin/registries/{registry}/{record_id}/edit"
                delete = f"/admin/registries/{registry}/{record_id}/delete"
                page = self.client.get(path)
                self.assertIn(f'href="{edit}"'.encode(), page.data)
                self.assertIn(f'href="{delete}"'.encode(), page.data)
                page = self.client.get(edit)
                self.assertEqual(page.status_code, 200)
                self.assertIn(b'value="PACIENTE ORIGINAL"', page.data)
                updated = {**fields, "full_name": "paciente corregido", "birth_date": "2001-10-16"}
                if account_type == "health":
                    updated["component"] = "Ejército Bolivariano"
                elif is_traffic:
                    updated["attention_center"] = "hospital nuevo"
                    updated["component"] = "Armada Bolivariana"
                invalid = {**updated, "birth_date": "2030-01-01", "csrf_token": csrf}
                response = self.client.post(edit, data=invalid, headers={"Referer": "http://localhost" + edit})
                self.assertEqual(response.status_code, 303)
                self.assertEqual(read(self.admin_token, account_type=account_type)[0], original)
                required = list(updated)
                if account_type == "military" and is_traffic:
                    required.remove("component")
                for field in required:
                    with self.subTest(registry=registry, missing=field):
                        response = self.client.post(
                            edit, data={**updated, field: "", "csrf_token": csrf},
                            headers={"Referer": "http://localhost" + edit},
                        )
                        self.assertEqual(response.status_code, 303)
                        self.assertEqual(read(self.admin_token, account_type=account_type)[0], original)
                self.assertEqual(self.client.post(edit, data=updated).status_code, 400)
                response = self.client.post(edit, data={**updated, "csrf_token": csrf})
                self.assertEqual(response.status_code, 302)
                row = read(self.admin_token, account_type=account_type)[0]
                self.assertEqual(row["full_name"], "PACIENTE CORREGIDO")
                self.assertEqual(row["age"], 24)
                self.assertEqual(row["center_id"], original["center_id"])
                self.assertEqual(row["created_at"], original["created_at"])
                reopened = Store(Path(self.directory.name) / "inventory.sqlite3")
                persisted_read = reopened.traffic_records if is_traffic else reopened.military_records
                self.assertEqual(persisted_read(self.admin_token, account_type=account_type)[0], row)
                self.assertEqual(row["component"], "Ejército Bolivariano" if account_type == "health"
                                 else "Guardia Nacional Bolivariana")
                if account_type == "military" and is_traffic:
                    self.assertEqual(row["center_name"], "HOSPITAL NUEVO")
                pdf = self.client.get(path + "/report.pdf")
                with pymupdf.open(stream=pdf.data, filetype="pdf") as document:
                    self.assertIn("PACIENTE CORREGIDO", " ".join(document[0].get_text().split()))
                confirm = self.client.get(delete)
                self.assertEqual(confirm.status_code, 200)
                self.assertIn("no se puede deshacer".encode(), confirm.data)
                self.assertEqual(self.client.post(delete, data={"csrf_token": csrf}).status_code, 400)
                self.assertEqual(len(read(self.admin_token, account_type=account_type)), 1)
                response = self.client.post(delete, data={"csrf_token": csrf, "confirm": "eliminar"})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(read(self.admin_token, account_type=account_type), [])
                self.assertEqual(persisted_read(self.admin_token, account_type=account_type), [])

    def test_registry_management_is_admin_only_and_checks_registry_scope(self):
        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        guard = self.store.login("guardia", CENTER_PASSWORD)
        self.store.add_military_record(
            guard, "TTE", "PACIENTE PRUEBA", "V-1", "2000-01-01",
            "2026-01-01", "Muerte natural", "REDI Capital", "ZODI", "UNIDAD",
        )
        record_id = self.store.military_records(self.admin_token)[0]["id"]
        self.login("norte", CENTER_PASSWORD)
        csrf = self.authenticated_csrf()
        for token in (self.store.login("norte", CENTER_PASSWORD), guard):
            with self.client.session_transaction() as browser_session:
                browser_session["token"] = token
            for operation in ("edit", "delete"):
                path = f"/admin/registries/component-deaths/{record_id}/{operation}"
                self.assertEqual(self.client.get(path).status_code, 403)
                self.assertEqual(self.client.post(
                    path, data={"csrf_token": csrf, "confirm": "eliminar"},
                ).status_code, 403)
            self.assertNotIn(b">Editar</a>", self.client.get(
                "/military" if token == guard else "/health/military",
            ).data)
            with self.assertRaises(AccessError):
                self.store.manage_patient_record(
                    token, record_id, account_type="military", traffic=False, action="delete",
                )
        with self.client.session_transaction() as browser_session:
            browser_session["token"] = self.admin_token
        with self.assertRaises(InventoryError):
            self.store.manage_patient_record(
                self.admin_token, record_id, account_type="health", traffic=False, action="delete",
            )
        for registry in ("health-deaths", "component-traffic", "no-existe"):
            self.assertEqual(self.client.get(
                f"/admin/registries/{registry}/{record_id}/edit",
            ).status_code, 404)
            self.assertEqual(self.client.post(
                f"/admin/registries/{registry}/{record_id}/delete",
                data={"csrf_token": csrf, "confirm": "eliminar"},
            ).status_code, 404)
        self.assertEqual(len(self.store.military_records(self.admin_token)), 1)

    def test_military_registry_forms_precede_records_and_filters_come_last(self):
        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        north = self.store.login("norte", CENTER_PASSWORD)
        guard = self.store.login("guardia", CENTER_PASSWORD)
        cases = (
            (north, ("/health/military", "/health/traffic"), True, False),
            (guard, ("/military", "/military/traffic"), True, True),
            (self.admin_token, ("/military", "/health/military", "/health/traffic", "/military/traffic"),
             False, True),
        )
        for token, paths, has_form, has_filters in cases:
            with self.client.session_transaction() as browser_session:
                browser_session["token"] = token
            for path in paths:
                with self.subTest(path=path, form=has_form, filters=has_filters):
                    page = self.client.get(path)
                    self.assertEqual(page.status_code, 200)
                    html = page.get_data(as_text=True)
                    records = html.index("<h2>Registros (")
                    if has_form:
                        self.assertLess(html.index('<form method="post" action="' + path), records)
                    else:
                        self.assertNotIn("<h2>Ingresar registro</h2>", html)
                    if has_filters:
                        self.assertLess(records, html.index('class="filter-grid"'))
                        self.assertIn("Generar reporte PDF", html[records:])
                    else:
                        self.assertNotIn('class="filter-grid"', html)

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

    def test_admin_edits_accounts_and_confirms_deletion_of_center40(self):
        self.store.create_center(self.admin_token, "Centro Cuarenta", "Prueba", "centro40", CENTER_PASSWORD)
        self.store.create_military_account(
            self.admin_token, "Guardia Nacional Bolivariana", "guardia", CENTER_PASSWORD,
        )
        self.login("admin", ADMIN_PASSWORD)
        csrf = self.authenticated_csrf()
        users = self.store.users(self.admin_token)
        center = next(user for user in users if user["username"] == "centro40")
        military = next(user for user in users if user["username"] == "guardia")
        page = self.client.get("/admin/accounts")
        self.assertIn(f'href="/admin/accounts/{center["id"]}/delete"'.encode(), page.data)
        self.assertIn(b'name="component"', page.data)
        response = self.client.post("/admin/accounts", data={
            "csrf_token": csrf, "action": "update", "user_id": military["id"],
            "username": "guardia2", "component": "Armada Bolivariana",
        })
        self.assertEqual(response.status_code, 302)
        identity = self.store.identity(self.store.login("guardia2", CENTER_PASSWORD))
        self.assertEqual(identity["center_name"], "Armada Bolivariana")
        token = self.store.login("centro40", CENTER_PASSWORD)
        self.store.save_quantity(token, center["center_id"], "Camas", "UCI", 1, 0)
        path = f'/admin/accounts/{center["id"]}/delete'
        page = self.client.get(path)
        self.assertIn(b"centro40", page.data)
        self.assertIn("no se puede deshacer".encode(), page.data)
        self.assertEqual(self.client.post(path, data={"confirmation": "centro40"}).status_code, 400)
        self.assertEqual(self.client.post(path, data={
            "csrf_token": csrf, "confirmation": "otro", "center_id": center["center_id"],
        }).status_code, 303)
        self.assertEqual(self.store.identity(token)["username"], "centro40")
        self.assertEqual(self.client.post(path, data={
            "csrf_token": csrf, "confirmation": "centro40", "center_id": self.center["id"],
        }).status_code, 303)
        self.assertEqual(self.store.identity(token)["username"], "centro40")
        response = self.client.post(path, data={
            "csrf_token": csrf, "confirmation": "centro40", "center_id": center["center_id"],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/accounts")
        self.assertNotIn("centro40", [user["username"] for user in self.store.users(self.admin_token)])
        self.assertNotIn(center["center_id"], [item["id"] for item in self.store.centers(self.admin_token)])
        with self.assertRaises(AccessError):
            self.store.identity(token)
        self.assertEqual(self.client.get(path).status_code, 404)
        with self.client.session_transaction() as browser_session:
            browser_session["token"] = self.store.login("norte", CENTER_PASSWORD)
        self.assertEqual(self.client.get(f'/admin/accounts/{military["id"]}/delete').status_code, 403)
        self.assertEqual(self.client.post(f'/admin/accounts/{military["id"]}/delete', data={
            "csrf_token": csrf, "confirmation": "guardia2",
        }).status_code, 403)

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
        self.assertEqual(military_client.get("/").headers["Location"], "/military/records")
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
        self.assertIn(b'href="/health/patients"', inventory_page.data)
        health_page = self.client.get("/health/military")
        self.assertEqual(health_page.status_code, 200)
        self.assertIn(b"<h1>Militares Fallecidos en Centros de Salud</h1>", health_page.data)
        self.assertNotIn(b'class="filter-grid"', health_page.data)
        self.assertNotIn(b"Generar reporte PDF", health_page.data)
        self.assertNotIn(b'class="admin-nav"', health_page.data)
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
        self.assertIn(b'class="filter-grid"', filtered.data)
        self.assertIn(b"Generar reporte PDF", filtered.data)
        self.assertIn(b"FALLECIDO NORTE", filtered.data)
        self.assertNotIn(b"FALLECIDO SUR", filtered.data)
        component_report = self.client.get("/military")
        self.assertIn(b"Registro de Militares Fallecidos", component_report.data)
        self.assertIn(b'class="filter-grid"', component_report.data)
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
        self.assertIn(b'href="/health/patients"', inventory.data)
        page = self.client.get("/health/traffic")
        self.assertEqual(page.status_code, 200)
        self.assertIn("<h1>Militares atendidos por accidentes de Tránsito</h1>".encode(), page.data)
        self.assertNotIn(b'class="filter-grid"', page.data)
        self.assertNotIn(b"Generar reporte PDF", page.data)
        self.assertNotIn(b'class="admin-nav"', page.data)
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
        self.assertIn(b'class="filter-grid"', page.data)
        self.assertIn(b"Generar reporte PDF", page.data)
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
