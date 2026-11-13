import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pymupdf

from report import SUMMARY_CATEGORIES, counts, generate_military_pdf, generate_pdf, report_data
from store import AccessError, InventoryError, REPORT_TIMEZONE, SPECIAL_EQUIPMENT_TYPES, Store, load_center_catalog


PASSWORD = "Test-report-password-123"


class MilitaryReportLayoutTests(unittest.TestCase):
    def test_components_without_records_are_omitted_and_empty_results_are_reported(self):
        record = {
            "component": "Guardia Nacional Bolivariana", "grade": "TTE",
            "full_name": "PERSONA DE PRUEBA", "cedula": "V-12345678",
            "birth_date": "1990-01-01", "age": 36, "death_date": "2026-10-15",
            "cause": "Muerte natural", "redi": "REDI Capital",
            "zodi": "ZODI CAPITAL", "unit": "UNIDAD DE PRUEBA",
        }
        with pymupdf.open(
            stream=generate_military_pdf([record]), filetype="pdf",
        ) as document:
            self.assertEqual(len(document), 1)
            self.assertIn("PERSONA DE PRUEBA", document[0].get_text())
            self.assertNotIn("Ejército Bolivariano", document[0].get_text())
        for records, component in (([], None), ([record], "Ejército Bolivariano")):
            with self.subTest(component=component), self.assertRaisesRegex(
                InventoryError, "No hay registros",
            ):
                generate_military_pdf(records, component)

    def test_long_text_is_complete_inside_cells_and_paginated_above_footer(self):
        record = {
            "component": "Guardia Nacional Bolivariana", "grade": "SOLDADO",
            "full_name": "NOMBRE Y APELLIDOS MUY EXTENSOS " * 5,
            "cedula": "V-12345678", "birth_date": "1990-01-01",
            "age": 36, "death_date": "2026-10-15",
            "cause": "Incidente por arma de fuego",
            "redi": "REDI Marítima e Insular", "zodi": "ZODI DE PRUEBA " * 8,
            "unit": "UNIDAD CON UNA DENOMINACION MUY EXTENSA " * 4,
        }
        record["center_name"] = "CENTRO DE SALUD CON UNA DENOMINACION MUY EXTENSA " * 3
        for health_registry in (False, True):
            with self.subTest(health_registry=health_registry), pymupdf.open(
                stream=generate_military_pdf([record] * 16, health_registry=health_registry),
                filetype="pdf",
            ) as document:
                self.assertGreater(len(document), 1)
                recovered = []
                for page in document:
                    self.assertTrue(page.get_xobjects())
                    self.assertIn("FUENTE: Sala Situacional/DIGESALUD", page.get_text())
                    words = page.get_text("words")
                    body = [word for word in words if 176 <= word[1] < 490]
                    self.assertTrue(body)
                    self.assertTrue(all(word[3] <= 482 for word in body))
                    self.assertTrue(all(28 <= word[0] < word[2] <= 932 for word in body))
                    recovered.append(" ".join(word[4] for word in body))
                text = " ".join(recovered)
                keys = ("full_name", "cause", "redi", "zodi", "unit")
                if health_registry:
                    keys += ("center_name", "component")
                for key in keys:
                    expected = " ".join(record[key].split())
                    self.assertEqual(text.count(expected), 16, key)


class ReportTests(unittest.TestCase):
    def setUp(self):
        clock = patch("store.time.time", return_value=datetime(
            2026, 10, 29, 12, tzinfo=REPORT_TIMEZONE,
        ).timestamp())
        clock.start()
        self.addCleanup(clock.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "report.sqlite3")
        self.store.bootstrap("admin", PASSWORD)
        self.token = self.store.login("admin", PASSWORD)
        self.store.add_equipment_type(self.token, "Monitor")
        self.store.create_center(self.token, "Centro Norte", "Norte", "norte", PASSWORD)
        self.store.create_center(self.token, "Centro Sur", "Sur", "sur", PASSWORD)
        self.north, self.south = [center["id"] for center in self.store.centers(self.token)]

    def test_pdf_generation_time_uses_venezuela_timezone(self):
        from datetime import timezone

        instant = datetime(2026, 10, 28, 2, 5, tzinfo=timezone.utc)
        with patch("report.datetime") as clock:
            clock.now.side_effect = lambda zone: instant.astimezone(zone)
            for center_id in (self.north, None):
                with self.subTest(center=center_id), pymupdf.open(
                    stream=generate_pdf(self.store, self.token, center_id, category="Plantas eléctricas"),
                    filetype="pdf",
                ) as doc:
                    self.assertIn(
                        "Generado: 27/10/2026 22:05 (hora de Venezuela)",
                        doc[0].get_text(),
                    )
            self.assertTrue(all(call.args == (REPORT_TIMEZONE,) for call in clock.now.call_args_list))

    def test_pdf_type_and_vehicle_group_filters_exclude_other_columns_and_totals(self):
        self.populate(self.north)
        self.populate(self.south)
        for center_id in (None, self.north):
            for category, kind, expected, excluded in (
                ("Camas hospitalarias", "UCI", "UCI", "Hospitalización"),
                ("Todos los vehículos", "Soporte básico", "Soporte básico", "Motos"),
                ("Bancos de sangre", "Banco de sangre", "Banco de sangre", "Central"),
                ("Laboratorios", "Central", "Central", "Emergencia"),
                ("Quirófanos", "En pisos", "En pisos", "En emergencias"),
                ("Equipos médicos especiales", "Tomógrafo", "Tomógrafo", "Resonador"),
                ("Plantas eléctricas", "Plantas eléctricas", "Plantas eléctricas", "UCI"),
            ):
                with self.subTest(center=center_id, category=category), pymupdf.open(
                    stream=generate_pdf(
                        self.store, self.token, center_id, category=category, kind=kind,
                    ), filetype="pdf",
                ) as doc:
                    self.assertEqual(len(doc), 1)
                    text = doc[0].get_text()
                    self.assertIn(expected.upper(), text.upper())
                    self.assertNotIn(excluded.upper(), text.upper())
                    self.assertEqual("Centro Sur" in text, center_id is None)
                    if category in ("Camas hospitalarias", "Todos los vehículos", "Equipos médicos especiales"):
                        pair = {
                            "Camas hospitalarias": (5, 2),
                            "Todos los vehículos": (3, 1),
                            "Equipos médicos especiales": (3, 2),
                        }[category]
                        multiplier = 2 if center_id is None else 1
                        expected_total = [value * multiplier for value in (*pair, sum(pair))]
                        words = doc[0].get_text("words")
                        marker = (
                            "GENERAL" if center_id is None
                            else "TOTAL" if category == "Equipos médicos especiales" else "Norte"
                        )
                        total = next(
                            word for word in words
                            if word[4] == marker and word[0] < 331 and word[1] > 260
                        )
                        actual = [
                            int(word[4]) for word in words
                            if word[0] > 331 and abs(word[1] - total[1]) < 1 and word[4].isdigit()
                        ]
                        self.assertEqual(actual, expected_total)
            with pymupdf.open(stream=generate_pdf(
                self.store, self.token, center_id, category="Todos los vehículos",
                vehicle_group="Ambulancias",
            ), filetype="pdf") as doc:
                self.assertEqual(len(doc), 1)
                self.assertIn("SOPORTE BÁSICO", doc[0].get_text())
                self.assertNotIn("MOTOS", doc[0].get_text())

    def test_named_laboratory_filter_excludes_other_special_labs_and_central(self):
        with self.store.transaction() as connection:
            for center, slot, name, state in (
                (self.north, 1, "MICROBIOLOGIA", "Operativo"),
                (self.north, 2, "TOXICOLOGIA", "Fuera de servicio"),
                (self.south, 1, "TOXICOLOGIA", "Operativo"),
            ):
                connection.execute(
                    "INSERT INTO special_laboratories(center_id, slot, name, state) VALUES(?, ?, ?, ?)",
                    (center, slot, name, state),
                )
        for center_id in (None, self.north):
            with self.subTest(center=center_id), pymupdf.open(
                stream=generate_pdf(
                    self.store, self.token, center_id, category="Laboratorios",
                    kind="Laboratorio especial: MICROBIOLOGIA",
                ), filetype="pdf",
            ) as doc:
                self.assertEqual(len(doc), 2)
                text = "\n".join(page.get_text() for page in doc).upper()
                self.assertIn("MICROBIOLOGIA", text)
                self.assertNotIn("TOXICOLOGIA", text)
                self.assertNotIn("CENTRAL", text)

    def test_invalid_report_filter_combinations_are_rejected(self):
        for filters in (
            {"kind": "UCI"},
            {"category": "Camas hospitalarias", "kind": "Motos"},
            {"category": "Camas hospitalarias", "vehicle_group": "Ambulancias"},
            {"category": "Todos los vehículos", "vehicle_group": "Desconocido"},
            {"category": "Todos los vehículos", "vehicle_group": "Ambulancias", "kind": "Motos"},
        ):
            with self.subTest(filters=filters), self.assertRaises(InventoryError):
                generate_pdf(self.store, self.token, **filters)

    def populate(self, center):
        self.store.save_quantity(self.token, center, "Camas", "UCI", 5, 2)
        self.store.save_quantity(self.token, center, "Vehículos", "Soporte básico", 3, 1)
        self.store.save_quantity(self.token, center, "Vehículos", "Motos", 4, 2)
        self.store.save_facility(self.token, center, "Quirófano", "Q1", "En pisos", "Operativo")
        self.store.save_facility(self.token, center, "Quirófano", "Q2", "En emergencias", "Fuera de servicio")
        self.store.save_facility(self.token, center, "Banco de sangre", "Banco", "General", "Operativo")
        self.store.save_facility(self.token, center, "Laboratorio", "Lab", "General", "Fuera de servicio")
        self.store.save_equipment(self.token, center, "M1", "Monitor", "Marca", "Modelo", "Serie", "Operativo")
        self.store.save_equipment(self.token, center, "M2", "  MONITOR  ", "Marca", "Modelo", "Serie", "Fuera de servicio")
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO equipment_counts(center_id, category, kind, operational, unavailable) VALUES(?, ?, ?, ?, ?)",
                (center, "Equipos médicos especiales", "Tomógrafo", 3, 2),
            )

    def test_all_six_sections_have_exact_counts_and_normalized_equipment(self):
        self.populate(self.north)
        values = report_data(self.store, self.token, self.north)[0][1]
        self.assertEqual(values[0], {"UCI": [5, 2]})
        self.assertEqual(values[1], {"Soporte básico": [3, 1]})
        self.assertEqual(values[2], {"Motos": [4, 2]})
        self.assertEqual(values[3], {"En pisos": [1, 0], "En emergencias": [0, 1]})
        self.assertEqual(values[4], {
            "Banco de sangre": [1, 0], "Laboratorio": [0, 1], "Central": [0, 1],
        })
        self.assertEqual(values[5], {"Tomógrafo": [3, 2]})

    def test_vehicle_pdf_separates_five_groups_and_keeps_each_total(self):
        types = (
            ("Soporte básico", 1, 2), ("Soporte avanzado", 3, 4), ("Tácticas", 5, 6),
            ("Carros / camionetas", 7, 8), ("Carga pesada (camiones y gandolas)", 9, 10),
            ("Transporte de personal (autobús, van y minivan)", 11, 12), ("Motos", 13, 14),
        )
        for kind, operational, unavailable in types:
            self.store.save_quantity(self.token, self.north, "Vehículos", kind, operational, unavailable)
        with pymupdf.open(
            stream=generate_pdf(self.store, self.token, self.north, category="Todos los vehículos"),
            filetype="pdf",
        ) as document:
            self.assertEqual(len(document), 5)
            for page, title, expected in zip(
                document,
                ("AMBULANCIAS", "VEHÍCULOS PROTOCOLARES",
                 "CARGA PESADA (CAMIONES Y GANDOLAS)",
                 "TRANSPORTE DE PERSONAL (AUTOBÚS, VAN Y MINIVAN)", "MOTOS"),
                ((1, 2, 3, 4, 5, 6, 21), (7, 8, 15), (9, 10, 19), (11, 12, 23), (13, 14, 27)),
            ):
                self.assertIn(title, page.get_text())
                words = page.get_text("words")
                center_word = next(word for word in words if word[4] == "Centro" and word[0] < 331)
                numbers = [
                    int(word[4]) for word in words
                    if word[0] > 331 and abs(word[1] - center_word[1]) < 1 and word[4].isdigit()
                ]
                self.assertEqual(tuple(numbers), expected)
                self.assertNotIn("CAMAS HOSPITALARIAS", page.get_text())

    def test_institutional_banner_appears_above_content_in_every_export(self):
        self.populate(self.north)
        for center_id in (self.north, None):
            for category in (None, *SUMMARY_CATEGORIES, "Todos los vehículos"):
                with self.subTest(center=center_id, category=category), pymupdf.open(
                    stream=generate_pdf(self.store, self.token, center_id, category=category),
                    filetype="pdf",
                ) as doc:
                    for page in doc:
                        banner = [word for word in page.get_text("words") if word[4] == "VICESALUDBSS"]
                        self.assertEqual(len(banner), 1)
                        self.assertLess(banner[0][3], 96)
                        for image in page.get_image_info():
                            self.assertLessEqual(image["bbox"][3], 96)
                        content = [
                            word for word in page.get_text("words") if word[4] != "VICESALUDBSS"
                        ]
                        self.assertTrue(all(word[1] >= 109.99 for word in content))

    def test_titles_identify_each_of_34_centers_in_every_pdf(self):
        self.store.import_centers(self.token, load_center_catalog())
        centers = self.store.centers(self.token)
        centers = [center for center in centers if center["id"] not in (self.north, self.south)]
        self.assertEqual(len(centers), 34)
        for center in centers:
            suffix = f"DEL {center['name'].split(' - ', 1)[0].upper()}"
            for category in (None, *SUMMARY_CATEGORIES, "Todos los vehículos"):
                with self.subTest(center=center["name"], category=category), pymupdf.open(
                    stream=generate_pdf(self.store, self.token, center["id"], category=category),
                    filetype="pdf",
                ) as doc:
                    for page in doc:
                        title = " ".join(
                            word[4] for word in page.get_text("words")
                            if 109.99 <= word[1] and word[3] <= 138.01
                        )
                        self.assertTrue(title.endswith(suffix), title)
                        self.assertIn("VICESALUDBSS", page.get_text())
                        words = page.get_text("words")
                        self.assertFalse(any(138.01 < word[1] < 204.99 for word in words))
                        source = next(word for word in words if word[4] == "FUENTE:")
                        generated = next(word for word in words if word[4] == "Generado:")
                        self.assertGreater(generated[1], source[3])
                        self.assertLess(generated[3], 522)
        with pymupdf.open(
            stream=generate_pdf(self.store, self.token, category="Camas hospitalarias"),
            filetype="pdf",
        ) as doc:
            self.assertIn(
                "CAMAS HOSPITALARIAS DE TODOS LOS CENTROS DE SALUD",
                " ".join(doc[0].get_text().split()),
            )

    def test_center_pdf_matches_six_sections_and_director_name(self):
        self.populate(self.north)
        data = generate_pdf(self.store, self.token, self.north)
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            self.assertEqual(len(doc), 7)
            for page in doc:
                self.assertEqual((page.rect.width, page.rect.height), (960, 540))
                text = page.get_text()
                self.assertIn("VICESALUDBSS", text)
                self.assertTrue(page.get_images())
                self.assertIn("DIRECTOR DEL Centro Norte", text)
                self.assertNotIn("Centro Sur", text)
                self.assertIn("FUENTE: Sala Situacional/DIGESALUD", text)
            self.assertIn("UCI", doc[0].get_text())
            self.assertIn("Tomógrafo", doc[5].get_text())
            self.assertNotIn("monitor", doc[5].get_text())

    def test_consolidated_totals_include_every_center_once(self):
        self.populate(self.north)
        self.populate(self.south)
        data = report_data(self.store, self.token)
        self.assertEqual(sum(values[0].get("UCI", [0, 0])[0] for _, values in data), 10)
        with pymupdf.open(stream=generate_pdf(self.store, self.token), filetype="pdf") as doc:
            self.assertEqual(len(doc), 7)
            for page in doc:
                self.assertIn("VICESALUDBSS", page.get_text())
                self.assertIn("Centro Norte", page.get_text())
                self.assertIn("Centro Sur", page.get_text())
                self.assertIn("TOTAL GENERAL", page.get_text())
            self.assertIn("SUMA POR DESCRIPCIÓN: Tomógrafo", doc[5].get_text())
            # UCI OPE, UCI INOP, total for the TOTAL GENERAL row.
            words = doc[0].get_text("words")
            total_word = next(word for word in words if word[4] == "GENERAL")
            numbers = [word[4] for word in words if abs(word[1] - total_word[1]) < 1 and word[0] > 331]
            self.assertEqual(numbers[-3:], ["10", "4", "14"])

    def test_missing_or_unmapped_types_raise_instead_of_omitting_counts(self):
        self.store.save_quantity(self.token, self.north, "Camas", "Tipo antiguo", 3, 0)
        with self.assertRaises(InventoryError):
            generate_pdf(self.store, self.token, self.north)
        with self.assertRaises(InventoryError):
            counts({"quantities": [], "facilities": [{
                "category": "Quirófano", "name": "Q1", "kind": "General", "state": "Operativo",
            }], "equipment": []})

    def test_filtered_blood_bank_and_laboratory_pdfs_keep_separate_counts(self):
        self.populate(self.north)
        self.populate(self.south)
        for category, expected in (
            ("Bancos de sangre", [1, 0, 1]),
            ("Laboratorios", [0, 1, 0, 0, 0, 0, 1]),
        ):
            for center_id in (self.north, None):
                with self.subTest(category=category, center=center_id):
                    data = generate_pdf(self.store, self.token, center_id, category=category)
                    with pymupdf.open(stream=data, filetype="pdf") as doc:
                        self.assertEqual(len(doc), 1)
                        words = doc[0].get_text("words")
                        north_word = next(word for word in words if word[4] == "Norte" and word[1] > 175)
                        numbers = [
                            word[4] for word in words
                            if abs(word[1] - north_word[1]) < 1 and word[0] > 331
                        ]
                        self.assertEqual(numbers, [str(value) for value in expected])
                        if center_id is None:
                            total_word = next(word for word in words if word[4] == "GENERAL")
                            totals = [
                                word[4] for word in words
                                if abs(word[1] - total_word[1]) < 1 and word[0] > 331
                            ]
                            self.assertEqual(totals, [str(value * 2) for value in expected])

    def test_laboratory_pdf_separates_central_emergency_and_special_totals(self):
        for center, username in ((self.north, "norte"), (self.south, "sur")):
            token = self.store.login(username, PASSWORD)
            password = "Laboratory-report-password-456"
            self.store.change_password(token, PASSWORD, password)
            token = self.store.login(username, password)
            self.store.save_laboratories(
                token, center,
                {"Laboratorio": (1, 0), "Laboratorio de emergencia": (0, 1)},
                True, [
                    {"slot": 1, "name": "Microbiologia", "state": "Operativo"},
                    {"slot": 2, "name": "Toxicologia", "state": "Fuera de servicio"},
                    {"slot": 3, "name": "Inmunologia", "state": "Operativo"},
                ],
            )
        for center_id in (self.north, None):
            with self.subTest(center=center_id), pymupdf.open(
                stream=generate_pdf(self.store, self.token, center_id, category="Laboratorios"),
                filetype="pdf",
            ) as doc:
                self.assertEqual(len(doc), 2 if center_id is not None else 3)
                text = doc[0].get_text()
                for heading in ("CENTRAL", "EMERGENCIA", "MICROBIOLOGIA", "TOXICOLOGIA", "INMUNOLOGIA"):
                    self.assertIn(heading, text)
                self.assertNotIn("LABORATORIOS ESPECIALES", text)
                words = doc[0].get_text("words")
                north = next(word for word in words if word[4] == "Norte" and word[1] > 175)
                numbers = [int(word[4]) for word in words if word[0] > 331 and abs(word[1] - north[1]) < 1]
                self.assertEqual(numbers, [1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 5])
                if center_id is None:
                    total = next(word for word in words if word[4] == "GENERAL")
                    numbers = [int(word[4]) for word in words if word[0] > 331 and abs(word[1] - total[1]) < 1]
                    self.assertEqual(numbers, [2, 0, 0, 2, 2, 0, 0, 2, 2, 0, 10])
                for name in ("MICROBIOLOGIA", "TOXICOLOGIA", "INMUNOLOGIA"):
                    self.assertIn(name, doc[1].get_text())

    def test_many_named_laboratories_paginate_columns_without_losing_counts(self):
        with self.store.transaction() as connection:
            for center, names in (
                (self.north, ("MICROBIOLOGIA", "TOXICOLOGIA", "INMUNOLOGIA")),
                (self.south, ("PATOLOGIA", "HEMATOLOGIA", "GENETICA")),
            ):
                for slot, name in enumerate(names, 1):
                    connection.execute(
                        "INSERT INTO special_laboratories(center_id, slot, name, state) VALUES(?, ?, ?, ?)",
                        (center, slot, name.lower(), "Operativo"),
                    )
        with pymupdf.open(
            stream=generate_pdf(self.store, self.token, category="Laboratorios"),
            filetype="pdf",
        ) as doc:
            self.assertEqual(len(doc), 4)
            text = doc[0].get_text() + doc[1].get_text()
            for name in ("MICROBIOLOGIA", "TOXICOLOGIA", "INMUNOLOGIA", "PATOLOGIA", "HEMATOLOGIA", "GENETICA"):
                self.assertEqual(text.count(name), 1)
            totals = []
            for page in (doc[0], doc[1]):
                words = page.get_text("words")
                total = next(word for word in words if word[4] == "GENERAL")
                numbers = [int(word[4]) for word in words if word[0] > 331 and abs(word[1] - total[1]) < 1]
                totals.append(numbers[-1])
            self.assertEqual(sum(totals), 6)

    def test_invalid_pdf_category_is_rejected(self):
        with self.assertRaisesRegex(InventoryError, "Categoría de informe no válida"):
            generate_pdf(self.store, self.token, self.north, category="Desconocida")

    def test_center_cannot_export_other_centers_or_consolidated(self):
        token = self.store.login("norte", PASSWORD)
        self.store.change_password(token, PASSWORD, PASSWORD + "changed")
        token = self.store.login("norte", PASSWORD + "changed")
        self.assertTrue(generate_pdf(self.store, token, self.north).startswith(b"%PDF"))
        for center_id in (None, self.south):
            with self.assertRaises(AccessError):
                generate_pdf(self.store, token, center_id)
            with self.assertRaises(AccessError):
                generate_pdf(self.store, token, center_id, category="Camas hospitalarias")
        with self.assertRaises(AccessError):
            generate_pdf(self.store, "fake-token", self.north)

    def test_35_centers_and_long_equipment_names_paginate_without_clipping(self):
        store = Store(self.store.path.with_name("full.sqlite3"))
        store.bootstrap("admin", PASSWORD)
        token = store.login("admin", PASSWORD)
        store.import_centers(token, load_center_catalog())
        center = store.centers(token)[0]
        with store.transaction() as connection:
            for index in range(20):
                kind = "Descripción extensa " * 7 + str(index)
                connection.execute(
                    "INSERT INTO equipment_counts(center_id, category, kind, operational, unavailable) VALUES(?, ?, ?, ?, ?)",
                    (center["id"], "Equipos médicos especiales", kind, 1, 0),
                )
        with pymupdf.open(stream=generate_pdf(store, token), filetype="pdf") as doc:
            self.assertGreater(len(doc), 25)
            text = "\n".join(page.get_text() for page in doc)
            self.assertEqual(text.count("TOTAL GENERAL"), 7)
            self.assertEqual(text.count("SUMA POR DESCRIPCIÓN:"), 20)
            for page in doc:
                for word in page.get_text("words"):
                    self.assertGreaterEqual(word[0], 0)
                    self.assertLessEqual(word[2], 960)
                    self.assertLessEqual(word[3], 540)


if __name__ == "__main__":
    unittest.main()
