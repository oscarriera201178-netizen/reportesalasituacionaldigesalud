from collections import defaultdict
from datetime import datetime
from pathlib import Path
import unicodedata

import pymupdf

from store import (
    AMBULANCE_TYPES, BED_TYPES, InventoryError, REPORT_TIMEZONE, SPECIAL_EQUIPMENT_TYPES,
    THEATRE_TYPES, VEHICLE_GROUPS, VEHICLE_TYPES,
)


QUANTITY_TYPES = {"Camas": BED_TYPES, "Ambulancias": AMBULANCE_TYPES, "Vehículos protocolares": VEHICLE_TYPES}
LABORATORY_GROUPS = ("Central", "Emergencia", "Laboratorios especiales")
SECTIONS = (
    ("CAMAS HOSPITALARIAS", BED_TYPES),
    ("AMBULANCIAS", AMBULANCE_TYPES),
    ("VEHÍCULOS PROTOCOLARES", VEHICLE_TYPES),
    ("QUIRÓFANOS", THEATRE_TYPES),
    ("BANCOS DE SANGRE Y LABORATORIOS", ("Banco de sangre", *LABORATORY_GROUPS)),
    ("EQUIPOS MÉDICOS ESPECIALES", ()),
    ("PLANTAS ELÉCTRICAS", ("Plantas eléctricas",)),
)
SUMMARY_CATEGORIES = {
    "Camas hospitalarias": (0, None),
    "Ambulancias": (1, None),
    "Vehículos": (2, None),
    "Bancos de sangre": (4, "Banco de sangre"),
    "Laboratorios": (4, "Laboratorio"),
    "Quirófanos": (3, None),
    "Equipos médicos especiales": (5, None),
    "Plantas eléctricas": (6, None),
}


def normalized(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def counts(inventory):
    result = [{} for _ in SECTIONS]
    for row in inventory["quantities"]:
        if row["category"] == "Camas":
            section, options = 0, BED_TYPES
        elif row["category"] == "Vehículos" and normalized(row["kind"]) in {normalized(kind) for kind in AMBULANCE_TYPES}:
            section, options = 1, AMBULANCE_TYPES
        else:
            section, options = 2, VEHICLE_TYPES
        matches = [option for option in options if normalized(option) == normalized(row["kind"])]
        if not matches:
            raise InventoryError(
                f"El tipo «{row['kind']}» no corresponde al cuadro modelo. "
                "Actualiza ese registro antes de generar el PDF."
            )
        kind = matches[0]
        pair = result[section].setdefault(kind, [0, 0])
        pair[0] += row["operational"]
        pair[1] += row["unavailable"]
    for row in inventory.get("facility_counts", []):
        category = row["category"]
        if category == "Banco de sangre":
            section, kind = 4, "Banco de sangre"
        elif category == "Laboratorio":
            section, kind = 4, "Laboratorio"
            group = "Emergencia" if row["kind"] == "Laboratorio de emergencia" else "Central"
            detail = result[4].setdefault(group, [0, 0])
            detail[0] += row["operational"]
            detail[1] += row["unavailable"]
        else:
            section, kind = 3, row["kind"]
            if kind not in THEATRE_TYPES:
                raise InventoryError(
                    f"Selecciona En pisos o En emergencias para el quirófano «{kind}»."
                )
        pair = result[section].setdefault(kind, [0, 0])
        pair[0] += row["operational"]
        pair[1] += row["unavailable"]
    for row in inventory["facilities"]:
        if row["category"] == "Quirófano":
            if row["kind"] not in THEATRE_TYPES:
                raise InventoryError(f"Selecciona En pisos o En emergencias para el quirófano «{row['name']}».")
            section, key = 3, row["kind"]
        else:
            section, key = 4, row["category"]
        pair = result[section].setdefault(key, [0, 0])
        pair[0 if row["state"] == "Operativo" else 1] += 1
        if row["category"] == "Laboratorio":
            group = "Emergencia" if row["kind"] == "Laboratorio de emergencia" else "Central"
            result[4].setdefault(group, [0, 0])[0 if row["state"] == "Operativo" else 1] += 1
    for row in inventory.get("equipment_counts", []):
        pair = result[5].setdefault(row["kind"], [0, 0])
        pair[0] += row["operational"]
        pair[1] += row["unavailable"]
    for row in inventory.get("plant_counts", []):
        pair = result[6].setdefault("Plantas eléctricas", [0, 0])
        pair[0] += row["operational"]
        pair[1] += row["unavailable"]
    for row in inventory.get("special_laboratories", []):
        state = 0 if row["state"] == "Operativo" else 1
        result[4].setdefault("Laboratorio", [0, 0])[state] += 1
        result[4].setdefault("Laboratorios especiales", [0, 0])[state] += 1
        result[4].setdefault(f"Laboratorio especial: {row['name'].upper()}", [0, 0])[state] += 1
    return result


def report_data(store, token, center_id=None):
    snapshot = store.report_snapshot(token, center_id)
    return [(center, counts(inventory)) for center, inventory in snapshot]


def report_types(data, category, *, vehicle_group=None):
    if category == "Todos los vehículos":
        if vehicle_group is not None and vehicle_group not in VEHICLE_GROUPS:
            raise InventoryError("Grupo de vehículos no válido.")
        return tuple(
            kind for group, kinds in VEHICLE_GROUPS.items()
            if vehicle_group in (None, group) for kind in kinds
        )
    if vehicle_group is not None:
        raise InventoryError("El filtro de grupo solo corresponde a vehículos.")
    if category not in SUMMARY_CATEGORIES:
        raise InventoryError("Categoría de informe no válida.")
    section, only = SUMMARY_CATEGORIES[category]
    if only == "Laboratorio":
        special = tuple(dict.fromkeys(
            kind for _, values in data for kind in values[4]
            if kind.startswith("Laboratorio especial: ")
        ))
        return ("Central", "Emergencia", "Laboratorios especiales", *special)
    if section == 5:
        return SPECIAL_EQUIPMENT_TYPES
    return (only,) if only else SECTIONS[section][1]


def _text(page, rectangle, text, size=9, bold=False, align=1):
    for font_size in (size, size - 1, size - 2, 6):
        shape = page.new_shape()
        spare = shape.insert_textbox(
            rectangle, str(text), fontsize=font_size,
            fontname="hebo" if bold else "helv", align=align,
        )
        if spare >= 0:
            shape.commit()
            return
    raise InventoryError(f"No se pudo ajustar el texto del PDF: {str(text)[:60]}")


def _cell(page, x, y, width, height, text, *, bold=False, size=9):
    rect = pymupdf.Rect(x, y, x + width, y + height)
    page.draw_rect(rect, color=(0.2, 0.25, 0.28), width=0.5)
    _text(page, pymupdf.Rect(x + 3, y + 5, x + width - 3, y + height - 2), text, size, bold)


def _table(doc, title, groups, rows, signature, subtitle, timestamp):
    if len(groups) > 6:
        for start in range(0, len(groups), 6):
            part_rows = [
                (number, label, values[start * 2:(start + 6) * 2], total)
                for number, label, values, total in rows
            ]
            _table(
                doc, title, groups[start:start + 6], part_rows, signature,
                f"{subtitle} | Total correspondiente a los tipos de este cuadro" if subtitle else "", timestamp,
            )
        return
    numeric = len(groups) * 2 + 1
    first_width, number_width = 265, 30
    unit = (888 - first_width - number_width) / numeric
    # Repeat complete headings and totals across pages without splitting a row.
    chunks = [rows[start:start + 5] for start in range(0, len(rows), 5)] or [[]]
    for part, chunk in enumerate(chunks, 1):
        page = doc.new_page(width=960, height=540)
        with pymupdf.open(Path(__file__).with_name("cintillo.pdf")) as banner:
            page.show_pdf_page(
                pymupdf.Rect(36, 8, 924, 96), banner, 0,
                clip=pymupdf.Rect(0, 0, 960, 95),
            )
        _text(page, pymupdf.Rect(36, 110, 924, 138), title, 18, True)
        if subtitle:
            _text(page, pymupdf.Rect(36, 144, 924, 180), subtitle, 11)
        y = 205
        _cell(page, 36, y, number_width, 60, "N.º", bold=True)
        _cell(page, 66, y, first_width, 60, "CENTRO / DESCRIPCIÓN", bold=True)
        x = 66 + first_width
        for group in groups:
            _cell(page, x, y, unit * 2, 30, group.removeprefix("Laboratorio especial: ").upper(), bold=True, size=8)
            _cell(page, x, y + 30, unit, 30, "OPE", bold=True, size=8)
            _cell(page, x + unit, y + 30, unit, 30, "INOP", bold=True, size=8)
            x += unit * 2
        _cell(page, x, y, unit, 60, "TOTAL", bold=True, size=8)
        y += 60
        for number, label, values, total_row in chunk:
            _cell(page, 36, y, number_width, 32, number, bold=total_row, size=8)
            _cell(page, 66, y, first_width, 32, label, bold=total_row, size=8)
            x = 66 + first_width
            for value in (*values, sum(values)):
                _cell(page, x, y, unit, 32, value, bold=total_row, size=8)
                x += unit
            y += 32
        _text(page, pymupdf.Rect(36, 446, 924, 486), signature, 10, True)
        _text(page, pymupdf.Rect(36, 490, 924, 505), "FUENTE: Sala Situacional/DIGESALUD", 9, align=0)
        _text(page, pymupdf.Rect(36, 506, 924, 521), f"{timestamp} | Parte {part}/{len(chunks)}", 8, align=0)
        _text(page, pymupdf.Rect(36, 522, 924, 538), "OPE: operativo | INOP: inoperativo | 0: sin unidades registradas", 8)


def generate_pdf(store, token, center_id=None, *, category=None, kind=None, vehicle_group=None):
    if category is not None and category not in SUMMARY_CATEGORIES and category != "Todos los vehículos":
        raise InventoryError("Categoría de informe no válida.")
    data = report_data(store, token, center_id)
    if category is None and (kind is not None or vehicle_group is not None):
        raise InventoryError("Selecciona una categoría para filtrar el informe.")
    if category is not None:
        options = report_types(data, category, vehicle_group=vehicle_group)
        if kind is not None and kind not in options:
            raise InventoryError("Tipo de informe no válido para la categoría seleccionada.")
    consolidated = center_id is None
    if not data:
        raise InventoryError("No hay centros registrados para generar el informe.")
    signature = "CONSOLIDADO GENERAL - ADMINISTRACIÓN" if consolidated else f"DIRECTOR DEL {data[0][0]['name']}"
    subtitle = "SUMATORIA DE TODOS LOS CENTROS" if consolidated else ""
    title_suffix = (
        "DE TODOS LOS CENTROS DE SALUD" if consolidated
        else f"DEL {data[0][0]['name'].split(' - ', 1)[0].upper()}"
    )
    timestamp = datetime.now(REPORT_TIMEZONE).strftime("Generado: %d/%m/%Y %H:%M (hora de Venezuela)")
    with pymupdf.open() as doc:
        if category == "Todos los vehículos":
            for label, groups in VEHICLE_GROUPS.items():
                if vehicle_group not in (None, label) or (kind is not None and kind not in groups):
                    continue
                if kind is not None:
                    groups = (kind,)
                title = label.upper()
                section = 1 if label == "Ambulancias" else 2
                rows = []
                totals = [0] * (len(groups) * 2)
                for index, (center, values) in enumerate(data, 1):
                    cells = [number for group in groups for number in values[section].get(group, [0, 0])]
                    rows.append((index, center["name"], cells, False))
                    totals = [left + right for left, right in zip(totals, cells)]
                if consolidated:
                    rows.append(("", "TOTAL GENERAL", totals, True))
                _table(doc, f"{title} {title_suffix}", groups, rows, signature, subtitle, timestamp)
            return doc.tobytes(garbage=4, deflate=True)
        for section, (title, groups) in enumerate(SECTIONS):
            only = None
            if category is not None:
                selected_section, only = SUMMARY_CATEGORIES[category]
                if section != selected_section:
                    continue
                if only is not None:
                    title = category.upper()
                    groups = LABORATORY_GROUPS if only == "Laboratorio" else (only,)
            if section == 4 and only != "Banco de sangre":
                special_groups = tuple(dict.fromkeys(
                    kind for _, values in data for kind in values[4]
                    if kind.startswith("Laboratorio especial: ")
                ))
                groups = (
                    (() if only == "Laboratorio" else ("Banco de sangre",))
                    + ("Central", "Emergencia")
                    + (special_groups or ("Laboratorios especiales",))
                )
            if kind is not None:
                groups = (kind,)
            rows = []
            if section != 5:
                totals = [0] * (len(groups) * 2)
                for index, (center, values) in enumerate(data, 1):
                    cells = [number for group in groups for number in values[section].get(group, [0, 0])]
                    rows.append((index, center["name"], cells, False))
                    totals = [left + right for left, right in zip(totals, cells)]
                if consolidated:
                    rows.append(("", "TOTAL GENERAL", totals, True))
            else:
                groups = ("Situación",)
                totals = [0, 0]
                for center, values in data:
                    equipment = values[5] if kind is None else {kind: values[5].get(kind, [0, 0])}
                    for description, pair in sorted(equipment.items()):
                        if kind not in (None, description):
                            continue
                        label = f"{center['name']} / {description}" if consolidated else description
                        rows.append((len(rows) + 1, label, pair, False))
                        totals = [left + right for left, right in zip(totals, pair)]
                if consolidated:
                    descriptions = defaultdict(lambda: [0, 0])
                    for _, values in data:
                        for description, pair in values[5].items():
                            if kind not in (None, description):
                                continue
                            descriptions[description] = [left + right for left, right in zip(descriptions[description], pair)]
                    for description, pair in sorted(descriptions.items()):
                        rows.append(("", f"SUMA POR DESCRIPCIÓN: {description}", pair, True))
                rows.append(("", "TOTAL GENERAL" if consolidated else "TOTAL", totals, True))
            _table(doc, f"{title} {title_suffix}", groups, rows, signature, subtitle, timestamp)
            if section == 4 and only != "Banco de sangre" and (
                kind in (None, "Laboratorios especiales") or kind.startswith("Laboratorio especial: ")
            ):
                special_rows = []
                for center, values in data:
                    for detail_kind, pair in values[4].items():
                        if detail_kind.startswith("Laboratorio especial: ") and (
                            kind in (None, "Laboratorios especiales", detail_kind)
                        ):
                            label = f"{center['name']} / {detail_kind}" if consolidated else detail_kind
                            special_rows.append((len(special_rows) + 1, label, pair, False))
                if special_rows:
                    _table(
                        doc, f"LABORATORIOS ESPECIALES {title_suffix}", ("Situación",), special_rows,
                        signature, subtitle, timestamp,
                    )
        return doc.tobytes(garbage=4, deflate=True)
