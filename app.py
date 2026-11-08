
import logging
import os
import re
import secrets
import sqlite3
import tempfile
import time
from collections.abc import Mapping
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import streamlit as st
import pymupdf
from streamlit.errors import StreamlitSecretNotFoundError

from report import (
    SUMMARY_CATEGORIES, generate_pdf, report_data, report_types,
)
from store import (
    AccessError, InventoryError,
    INVENTORY_QUANTITIES, REPORT_LOADED, REPORT_PENDING, REPORT_TIMEZONE, STATES,
    weekly_status,
    SPECIAL_EQUIPMENT_TYPES, VEHICLE_GROUPS, Store, load_center_catalog,
)


LOGGER = logging.getLogger(__name__)


@st.cache_data
def institutional_banner():
    with pymupdf.open(Path(__file__).with_name("cintillo.pdf")) as document:
        return document[0].get_pixmap(
            matrix=pymupdf.Matrix(2, 2), clip=pymupdf.Rect(0, 0, 960, 95),
            alpha=False,
        ).tobytes("png")


@st.cache_resource
def development_store(catalog):
    directory = tempfile.TemporaryDirectory(prefix="salud-desarrollo-")
    store = Store(Path(directory.name) / "demo.sqlite3", allow_out_of_schedule=True)
    password = secrets.token_urlsafe(32)
    store.bootstrap("desarrollo", password)
    token = store.login("desarrollo", password)
    store.import_centers(token, catalog)
    centers = [(center["id"], center["name"]) for center in store.centers(token)]
    store.logout(token)
    # Development-only center accounts so the center view (with loading forms) can be previewed.
    with store.transaction() as connection:
        for center_id, _name in centers:
            store._create_user(connection, f"desarrollo-centro-{center_id}", password, "center", center_id)
        connection.execute("UPDATE users SET must_change=0")
    return store.path, password, directory, centers


def development_login(store, password, centers):
    st.warning("MODO DE DESARROLLO SIN CONTRASEÑA. Solo datos ficticios; se borran al reiniciar el servidor.")
    st.sidebar.info("MODO DESARROLLO: cargas habilitadas cualquier día. Se mantiene un envío por centro y semana.")
    admin_token = store.login("desarrollo", password)
    try:
        names = {center["id"]: center["name"] for center in store.centers(admin_token)}
        accounts = {user["center_id"]: user for user in store.users(admin_token) if user["active"]}
    finally:
        store.logout(admin_token)
    perspective = st.sidebar.selectbox(
        "Ver portal como", ["admin", *accounts],
        format_func=lambda value: "DIGESALUD-MPPD (Administrador)" if value == "admin" else f"{value}. {names[value]}",
        key="dev_perspective",
    )
    if st.session_state.get("dev_active") != perspective:
        if previous := st.session_state.get("token"):
            store.logout(previous)
        for key in list(st.session_state):
            if key != "dev_perspective":
                del st.session_state[key]
        st.session_state["dev_active"] = perspective
    if notice := st.session_state.pop("notice", None):
        success_message(notice)
    token = st.session_state.get("token", "")
    if token:
        try:
            return token, store.identity(token)
        except AccessError:
            st.info("La sesión de pruebas venció. Se ha iniciado una nueva.")
    username = "desarrollo" if perspective == "admin" else accounts[perspective]["username"]
    token = store.login(username, password)
    st.session_state["token"] = token
    return token, store.identity(token)


def password_form(store, token, *, mandatory=False):
    with st.form("change_password", clear_on_submit=True):
        st.caption("Entre 12 y 128 caracteres. El cambio cerrará tus sesiones.")
        current = st.text_input("Contraseña actual", type="password", max_chars=128)
        new = st.text_input("Nueva contraseña", type="password", max_chars=128)
        confirmation = st.text_input("Confirmar nueva contraseña", type="password", max_chars=128)
        if st.form_submit_button("Cambiar contraseña"):
            if new != confirmation:
                st.error("Las contraseñas no coinciden.")
            else:
                try:
                    store.change_password(token, current, new)
                except InventoryError as error:
                    st.error(str(error))
                else:
                    st.session_state.clear()
                    st.session_state["notice"] = "Contraseña actualizada. Inicia sesión nuevamente."
                    st.rerun()
    if mandatory:
        st.stop()


def success_message(message, *, key="notice"):
    if REPORT_LOADED in message:
        with st.container(key=f"report_confirmation_{key}"):
            st.success(message)
    else:
        st.success(message)


def login(store):
    if notice := st.session_state.pop("notice", None):
        success_message(notice)
    if not store.initialized():
        st.info("El responsable del servidor debe configurar la cuenta administradora antes de abrir el portal.")
        st.stop()
    token = st.session_state.get("token", "")
    if token:
        try:
            actor = store.identity(token)
        except AccessError as error:
            st.session_state.clear()
            st.warning(str(error))
        else:
            st.sidebar.write(f"Usuario: **{actor['username']}**")
            st.sidebar.caption("Administrador" if actor["role"] == "admin" else "Responsable de centro")
            if st.sidebar.button("Cerrar sesión"):
                store.logout(token)
                st.session_state.clear()
                st.rerun()
            if actor["must_change"]:
                st.warning("Cambia la contraseña temporal para acceder al inventario.")
                password_form(store, token, mandatory=True)
            if actor["role"] == "admin":
                with st.sidebar.expander("Cambiar contraseña"):
                    password_form(store, token)
            return token, actor
    _left, center, _right = st.columns([1, 1, 1])
    with center:
        with st.form("login", clear_on_submit=True):
            username = st.text_input("Usuario", max_chars=40)
            password = st.text_input("Contraseña", type="password", max_chars=128)
            if st.form_submit_button("Ingresar", type="primary"):
                try:
                    token = store.login(username, password)
                except AccessError as error:
                    st.error(str(error))
                else:
                    st.session_state.clear()
                    st.session_state["token"] = token
                    st.rerun()
    st.stop()


def bootstrap_from_secrets(store):
    if store.initialized():
        return
    try:
        credentials = st.secrets["bootstrap_admin"]
    except (KeyError, StreamlitSecretNotFoundError):
        return
    if not isinstance(credentials, Mapping):
        raise InventoryError("bootstrap_admin debe ser una tabla de secretos.")
    username = credentials.get("username")
    password = credentials.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise InventoryError("Configura usuario y contraseña en los secretos bootstrap_admin.")
    store.bootstrap(username, password)


def choose_record(rows, key, label):
    mapping = {row["id"]: row for row in rows}
    selected = st.selectbox(
        "Registrar o actualizar", [None, *mapping], key=key,
        format_func=lambda value: "Nuevo registro" if value is None else label(mapping[value]),
    )
    return mapping.get(selected)


def inventory_heading(label, *, centered=False):
    alignment = "text-align: center; " if centered else ""
    st.html(
        '<div style="background-color: var(--primary-color, #147d78); '
        'color: #ffffff; padding: 0.75rem 1rem; border-radius: 0.5rem; '
        f'font-weight: 700; {alignment}overflow-wrap: anywhere;">'
        f'{escape(label)}</div>'
    )


def inventory_changed():
    st.session_state.pop("_load_confirmation", None)
    st.session_state["_inventory_changed"] = True


def confirm_load_button(key):
    pending = st.session_state.get("_load_confirmation") == key
    clicked = st.button(
        "CONFIRMAR CARGA" if pending else "Cargar datos", type="primary", key=key,
    )
    if clicked:
        if pending:
            st.session_state.pop("_load_confirmation", None)
            return True
        st.session_state["_load_confirmation"] = key
        st.rerun()
    if pending:
        st.warning("¿Ha editado todos los campos? Pulsa CONFIRMAR CARGA para guardar.")
    return False


def quantity_grid(center_id, category, quantities, *, editable, kind_label, headings=None, subtotals=None):
    if not editable:
        table = [{
            kind_label: kind, "Operativas": row["operational"],
            "Inoperativas": row["unavailable"],
            "Total": row["operational"] + row["unavailable"],
        } for kind, row in quantities.items()]
        table.append({
            kind_label: "TOTAL",
            **{column: sum(row[column] for row in table)
               for column in ("Operativas", "Inoperativas", "Total")},
        })
        if headings:
            group_rows = []
            for row in table[:-1]:
                if row[kind_label] in headings:
                    if group_rows:
                        if subtotals:
                            group_rows.append({
                                kind_label: "SUBTOTAL",
                                **{column: sum(item[column] for item in group_rows)
                                   for column in ("Operativas", "Inoperativas", "Total")},
                            })
                        st.dataframe(group_rows, width="stretch", hide_index=True)
                    inventory_heading(headings[row[kind_label]])
                    group_rows = []
                group_rows.append(row)
            if group_rows:
                if subtotals:
                    group_rows.append({
                        kind_label: "SUBTOTAL",
                        **{column: sum(item[column] for item in group_rows)
                           for column in ("Operativas", "Inoperativas", "Total")},
                    })
                st.dataframe(group_rows, width="stretch", hide_index=True)
            st.dataframe(table[-1:], width="stretch", hide_index=True)
        else:
            st.dataframe(table, width="stretch", hide_index=True)
        return {}
    st.caption("Indica las cantidades de cada tipo. Si no tienes unidades, deja 00.")
    values = {}
    with st.container(border=True):
        for column, label in zip(
            st.columns([3, 2, 2, 2]),
            (kind_label, "Operativas", "Inoperativas", "Total"),
        ):
            column.markdown(f"**{label}**")
        for index, (kind, row) in enumerate(quantities.items()):
            if headings and kind in headings:
                inventory_heading(headings[kind])
            columns = st.columns([3, 2, 2, 2], vertical_alignment="center")
            columns[0].write(kind)
            operational = columns[1].number_input(
                f"Operativas: {kind}", min_value=0, max_value=1_000_000,
                value=row["operational"], format="%02d", label_visibility="collapsed",
                key=f"category_operational_{center_id}_{category}_{index}",
                on_change=inventory_changed,
            )
            unavailable = columns[2].number_input(
                f"Inoperativas: {kind}", min_value=0, max_value=1_000_000,
                value=row["unavailable"], format="%02d", label_visibility="collapsed",
                key=f"category_unavailable_{center_id}_{category}_{index}",
                on_change=inventory_changed,
            )
            columns[3].write(f"{operational + unavailable:02d}")
            values[kind] = (operational, unavailable)
            if subtotals:
                for label, group in subtotals.items():
                    if kind == group[-1]:
                        subtotal_operational = sum(values[item][0] for item in group)
                        subtotal_unavailable = sum(values[item][1] for item in group)
                        with st.container(key=f"subtotal_{center_id}_{category}_{index}"):
                            for column, text in zip(
                                st.columns([3, 2, 2, 2]),
                                (
                                    f"TOTAL {label.upper()}",
                                    f"{subtotal_operational:02d}", f"{subtotal_unavailable:02d}",
                                    f"{subtotal_operational + subtotal_unavailable:02d}",
                                ),
                            ):
                                column.markdown(f"**{text}**")
        totals = (
            sum(pair[0] for pair in values.values()),
            sum(pair[1] for pair in values.values()),
        )
        for column, label in zip(
            st.columns([3, 2, 2, 2]),
            ("TOTAL", f"{totals[0]:02d}", f"{totals[1]:02d}", f"{sum(totals):02d}"),
        ):
            column.markdown(f"**{label}**")
    return values


def bed_panel(store, token, center_id, quantities, *, editable):
    inventory_heading("CAMAS HOSPITALARIAS")
    values = quantity_grid(
        center_id, "Camas", quantities, editable=editable, kind_label="Tipo de cama",
    )
    if not editable:
        return
    st.caption("Cargar datos guarda las camas sin enviar el inventario semanal.")
    if confirm_load_button(f"load_beds_{center_id}"):
        save(store.load_section, token, center_id, "Camas", values)


def vehicle_panel(store, token, center_id, rows, *, editable, history=()):
    st.markdown("**VEHÍCULOS**")
    groups = VEHICLE_GROUPS
    if history:
        with st.expander("Historial sin asignar: carga pesada / autobús"):
            st.info(
                "La cantidad anterior combinaba carga pesada y transporte de personal. "
                "No se asigna automáticamente ni se suma al inventario actual. "
                "Completa ambos grupos y pulsa CARGAR DATOS para confirmar la separación."
            )
            st.dataframe([{
                "Tipo anterior": row["kind"], "Operativos": row["operational"],
                "Inoperativos": row["unavailable"],
                "Total": row["operational"] + row["unavailable"],
            } for row in history], hide_index=True, width="stretch")
    existing = {row["kind"]: row for row in rows if row["category"] == "Vehículos"}
    kinds = [kind for group in groups.values() for kind in group]
    kinds.extend(kind for kind in existing if kind not in kinds)
    quantities = {
        kind: existing.get(kind, {"operational": 0, "unavailable": 0})
        for kind in kinds
    }
    values = quantity_grid(
        center_id, "Vehículos", quantities, editable=editable, kind_label="Tipo de vehículo",
        headings={kinds[0]: label for label, kinds in groups.items()},
        subtotals=groups,
    )
    if not editable:
        return
    st.caption("Cargar datos guarda los vehículos sin enviar el inventario semanal.")
    if confirm_load_button(f"load_vehicles_{center_id}"):
        save(store.load_section, token, center_id, "Vehículos", values)


def uppercase_input(key):
    st.session_state[key] = st.session_state[key].upper()
    inventory_changed()


def facility_presence_panel(store, token, center_id, rows, category, *, editable, special_rows=()):
    if category in ("Laboratorio", "Quirófano"):
        inventory_heading("LABORATORIO" if category == "Laboratorio" else "QUIRÓFANOS")
        values = {}
        sections = (
            ("Laboratorio", "Laboratorio central", "laboratory"),
            ("Laboratorio de emergencia", "Laboratorio de emergencia", "emergency_laboratory"),
        ) if category == "Laboratorio" else (
            ("En pisos", "Quirófano en piso", "floor_theatre"),
            ("En emergencias", "Quirófano en emergencia", "emergency_theatre"),
        )
        for kind, label, prefix in sections:
            inventory_heading(label.upper())
            selected = presence_fields(
                center_id, rows, category, kind, label.lower(), prefix, editable=editable,
            )
            values[kind] = selected
        if category == "Quirófano":
            if editable:
                st.caption("Cargar datos guarda ambos quirófanos sin enviar el inventario semanal.")
                if confirm_load_button(f"load_theatres_{center_id}"):
                    if any(value is None for value in values.values()):
                        st.error("Indica si hay quirófano en piso y en emergencia, y sus estados cuando corresponda.")
                    else:
                        save(store.load_section, token, center_id, category, values)
            return
        inventory_heading("LABORATORIOS ESPECIALES")
        if not editable:
            st.write("**¿Hay laboratorios especiales?** " + ("Sí" if special_rows else "No"))
            for laboratory in special_rows:
                st.text(f"{laboratory['name'].upper()}: {laboratory['state']}")
            return
        has_special = st.radio(
            "¿Hay laboratorios especiales?", ("Sí", "No"),
            index=0 if special_rows else 1, key=f"special_laboratories_presence_{center_id}",
            on_change=inventory_changed,
        ) == "Sí"
        laboratories = []
        if has_special:
            st.caption("Completa al menos un laboratorio especial, hasta un máximo de tres.")
            existing = {row["slot"]: row for row in special_rows}
            for slot in range(1, 4):
                laboratory = existing.get(slot)
                name_key = f"special_laboratory_name_{center_id}_{slot}"
                if name_key not in st.session_state:
                    st.session_state[name_key] = laboratory["name"].upper() if laboratory else ""
                name = st.text_input(
                    f"Nombre del laboratorio especial {slot}",
                    max_chars=160, key=name_key,
                    on_change=uppercase_input,
                    args=(name_key,),
                )
                state = st.selectbox(
                    f"Estado del laboratorio especial {slot}", STATES,
                    index=STATES.index(laboratory["state"]) if laboratory else 0,
                    key=f"special_laboratory_state_{center_id}_{slot}",
                    on_change=inventory_changed,
                )
                if name.strip():
                    laboratories.append({"slot": slot, "name": name, "state": state})
        if editable:
            st.caption("Cargar datos guarda todos los laboratorios sin enviar el inventario semanal.")
            if confirm_load_button(f"load_laboratory_{center_id}"):
                if any(value is None for value in values.values()):
                    st.error("Indica si hay laboratorio central y de emergencia, y sus estados cuando corresponda.")
                else:
                    save(store.load_laboratories, token, center_id, values, has_special, laboratories)
        return
    name = category.lower()
    widget_prefix = "blood_bank"
    inventory_heading(category.upper())
    selected = presence_fields(
        center_id, rows, category, category, name, widget_prefix, editable=editable,
    )
    if not editable:
        return
    st.caption(f"Cargar datos guarda el {name} sin enviar el inventario semanal.")
    if confirm_load_button(f"load_{widget_prefix}_{center_id}"):
        if selected is None:
            st.error(f"Indica si hay {name} y selecciona su estado cuando corresponda.")
            return
        values = {row["kind"]: (0, 0) for row in rows if row["category"] == category}
        values[category] = selected
        save(store.load_section, token, center_id, category, values)


def presence_fields(center_id, rows, category, kind, name, widget_prefix, *, editable):
    banks = [row for row in rows if row["category"] == category and row["kind"] == kind]
    operational = sum(row["operational"] for row in banks)
    unavailable = sum(row["unavailable"] for row in banks)
    if not editable:
        if not banks:
            st.info(f"Todavía no se ha indicado si hay {name}.")
        elif operational + unavailable == 0:
            st.write(f"**¿Hay {name}?** No")
        else:
            st.write(f"**¿Hay {name}?** Sí")
            states = []
            if operational:
                states.append("Operativo")
            if unavailable:
                states.append("Fuera de servicio")
            st.write("**Estado:** " + " / ".join(states))
        return
    if operational + unavailable > 1:
        st.warning(
            f"Hay cantidades anteriores de más de un {name}. "
            "Selecciona la presencia y el estado; al cargar se sustituirán por un máximo de una unidad."
        )
    presence = st.radio(
        f"¿Hay {name}?", ("Sí", "No"),
        index=None if not banks or operational + unavailable > 1 else (0 if operational + unavailable else 1),
        key=f"{widget_prefix}_presence_{center_id}",
        on_change=inventory_changed,
    )
    state = None
    if presence == "Sí":
        state = st.radio(
            f"Estado del {name}", STATES,
            index=None if operational and unavailable else (1 if unavailable else 0),
            key=f"{widget_prefix}_state_{center_id}",
            on_change=inventory_changed,
        )
    if presence is None or (presence == "Sí" and state is None):
        return None
    return (
        int(presence == "Sí" and state == "Operativo"),
        int(presence == "Sí" and state == "Fuera de servicio"),
    )


def quantity_panel(
    store, token, center_id, rows, category, *, editable=True,
    facility_rows=(), legacy_facilities=(), special_rows=(),
):
    allowed_types = INVENTORY_QUANTITIES[category]
    if category in ("Banco de sangre", "Laboratorio", "Quirófano"):
        facility_presence_panel(
            store, token, center_id, facility_rows, category,
            editable=editable, special_rows=special_rows,
        )
        return
    table_rows = (
        rows if category in ("Camas", "Ambulancias", "Vehículos protocolares")
        else facility_rows
    )
    if category == "Camas":
        table_rows = [row for row in table_rows if row["category"] == "Camas"]
    elif category in ("Ambulancias", "Vehículos protocolares"):
        is_ambulance = category == "Ambulancias"
        ambulance_types = set(INVENTORY_QUANTITIES["Ambulancias"])
        table_rows = [
            row for row in table_rows
            if row["category"] == "Vehículos"
            and ((row["kind"] in ambulance_types) == is_ambulance)
        ]
    else:
        table_rows = [row for row in table_rows if row["category"] == category]
        old_rows = [row for row in legacy_facilities if row["category"] == category]
        if old_rows:
            st.caption(
                "Registros anteriores conservados como historial; sus unidades ya están incluidas abajo."
            )
            st.dataframe([{
                "Nombre": row["name"], "Tipo anterior": row["kind"],
                "Estado anterior": row["state"],
            } for row in old_rows], width="stretch", hide_index=True)
    existing = {row["kind"]: row for row in table_rows}
    kinds = list(allowed_types)
    kinds.extend(kind for kind in existing if kind not in kinds)
    quantities = {
        kind: existing.get(kind, {"operational": 0, "unavailable": 0})
        for kind in kinds
    }
    if category == "Camas":
        bed_panel(store, token, center_id, quantities, editable=editable)
        return
    st.dataframe([{
        "Tipo": kind, "Operativas": values["operational"],
        "Fuera de servicio": values["unavailable"],
        "Total": values["operational"] + values["unavailable"],
    } for kind, values in quantities.items()], width="stretch", hide_index=True)
    if not editable:
        return
    st.caption("Indica las cantidades de cada tipo. Si no tienes unidades, deja 00.")
    with st.form(f"quantity_{center_id}_{category}", clear_on_submit=True):
        values = {}
        for index, kind in enumerate(kinds):
            row = quantities[kind]
            st.markdown(f"**{kind}**")
            columns = st.columns(2)
            with columns[0]:
                operational = st.number_input(
                    "Operativas", min_value=0, max_value=1_000_000,
                    value=row["operational"], format="%02d",
                    key=f"category_operational_{center_id}_{category}_{index}",
                )
            with columns[1]:
                unavailable = st.number_input(
                    "Fuera de servicio", min_value=0, max_value=1_000_000,
                    value=row["unavailable"], format="%02d",
                    key=f"category_unavailable_{center_id}_{category}_{index}",
                )
            values[kind] = (operational, unavailable)
        if st.form_submit_button("Guardar y enviar", type="primary"):
            try:
                missing = store.save_category_quantities_and_submit(
                    token, center_id, category, values,
                )
            except InventoryError as error:
                st.error(str(error))
            else:
                if missing:
                    st.session_state["_quantity_submission_missing"] = missing
                    st.rerun()
                else:
                    st.session_state["notice"] = REPORT_LOADED
                    st.rerun()


def equipment_panel(store, token, center_id, rows, *, editable=True, history=()):
    inventory_heading("EQUIPOS MÉDICOS ESPECIALES")
    if history:
        with st.expander("Historial de equipos anteriores"):
            st.caption("Solo historial. Estos registros no se suman al inventario actual.")
            st.dataframe([{
            "Código": row["code"], "Tipo": row["kind"], "Marca": row["brand"],
            "Modelo": row["model"], "Serie": row["serial"], "Estado": row["state"],
            } for row in history], width="stretch", hide_index=True)
    if not rows:
        st.info("Pendiente de cargar las cantidades de equipos médicos especiales.")
    existing = {row["kind"]: row for row in rows}
    quantities = {
        kind: existing.get(kind, {"operational": 0, "unavailable": 0})
        for kind in SPECIAL_EQUIPMENT_TYPES
    }
    values = quantity_grid(
        center_id, "Equipos médicos especiales", quantities,
        editable=editable, kind_label="Tipo de equipo",
        headings={kind: kind for kind in SPECIAL_EQUIPMENT_TYPES},
    )
    if not editable:
        return
    st.caption("Cargar datos guarda las cantidades sin enviar el inventario semanal.")
    if confirm_load_button(f"load_equipment_{center_id}"):
        save(store.load_section, token, center_id, "Equipos médicos especiales", values)


def complete(*values):
    if all(value.strip() for value in values):
        return True
    st.error("Completa todos los campos antes de guardar. No se cargan datos incompletos.")
    return False


def save(method, *args):
    try:
        method(*args)
    except InventoryError as error:
        st.error(str(error))
    else:
        st.session_state["notice"] = "Inventario guardado."
        st.rerun()


def submission_panel(store, token, center_id):
    status = store.submission(token, center_id)
    if status["loaded"]:
        success_message(REPORT_LOADED, key="status")
        return
    with st.container(key="report_pending"):
        st.info(status["status"])
    if not status["open"]:
        return
    missing = store.missing_data(token, center_id)
    if missing:
        st.info("Para enviar, completa todos los datos:\n\n" + "\n".join(f"- {item}" for item in missing))
        return
    missing_categories = store.missing_inventory_categories(token, center_id)
    missing_categories.extend(
        f"{section}: pendiente de cargar en este período."
        for section, loaded in store.section_loads(token, center_id).items() if not loaded
    )
    if missing_categories:
        st.info(
            "Para enviar, carga cada categoría de cantidades. Los tipos pendientes son:\n\n"
            + "\n".join(f"- {item}" for item in missing_categories)
        )
        return
    if st.button("ENVIAR A DIGESALUD-MPPD", type="primary", key="submit_inventory", width="stretch"):
        try:
            store.submit(token, center_id, require_all_categories=True, require_loaded_sections=True)
        except InventoryError as error:
            st.error(str(error))
        else:
            st.session_state["notice"] = REPORT_LOADED
            st.rerun()


def category_summary(store, token, center_id, category, *, kind=None, vehicle_group=None):
    data = report_data(store, token, center_id)
    options = report_types(data, category, vehicle_group=vehicle_group)
    if kind is not None and kind not in options:
        raise InventoryError("Tipo de informe no válido para la categoría seleccionada.")
    if category == "Laboratorios" and kind is None:
        options = tuple(option for option in options if not option.startswith("Laboratorio especial: "))
    totals = {option: [0, 0] for option in options if kind in (None, option)}
    for _center, sections in data:
        values_by_type = (
            {**sections[1], **sections[2]} if category == "Todos los vehículos"
            else sections[SUMMARY_CATEGORIES[category][0]]
        )
        for option, pair in totals.items():
            values = values_by_type.get(option, [0, 0])
            pair[0] += values[0]
            pair[1] += values[1]
    rows = [{
        "Tipo": kind, "Operativas": operational, "Fuera de servicio": unavailable,
        "Total": operational + unavailable,
    } for kind, (operational, unavailable) in totals.items()]
    rows.append({
        "Tipo": "TOTAL",
        "Operativas": sum(row["Operativas"] for row in rows),
        "Fuera de servicio": sum(row["Fuera de servicio"] for row in rows),
        "Total": sum(row["Total"] for row in rows),
    })
    return rows


def pdf_download(
    store, token, center_id=None, *, widget_scope=None, category=None,
    kind=None, vehicle_group=None, label="DESCARGAR PDF",
):
    key = "all" if center_id is None else str(center_id)
    widget_key = f"{widget_scope}_{key}" if widget_scope else key
    export_key = f"_pdf_export_{widget_key}"
    file_name = f"Cuadros_{key}_{category}.pdf" if category is not None else f"Cuadros_{key}.pdf"
    if kind is not None or vehicle_group is not None:
        file_name = file_name[:-4] + "_" + "_".join(
            value.replace("/", "-") for value in (vehicle_group, kind) if value is not None
        ) + ".pdf"
    snapshot = store.report_snapshot(token, center_id)
    previous = st.session_state.get(export_key)
    if previous and (
        previous["snapshot"] != snapshot or previous.get("category") != category
        or previous.get("kind") != kind or previous.get("vehicle_group") != vehicle_group
    ):
        del st.session_state[export_key]
    export = st.session_state.get(export_key)
    if export is None:
        try:
            with st.spinner("Preparando el PDF…"):
                data = generate_pdf(
                    store, token, center_id, category=category, kind=kind, vehicle_group=vehicle_group,
                )
        except InventoryError as error:
            st.error(str(error))
            return
        st.session_state[export_key] = {
            "snapshot": snapshot, "category": category, "kind": kind,
            "vehicle_group": vehicle_group, "data": data,
        }
        export = st.session_state[export_key]
    st.download_button(
        label, data=export["data"], file_name=file_name,
        mime="application/pdf", key=f"download_pdf_{widget_key}", on_click="ignore",
    )


REPORT_CATEGORIES = {
    "Camas": "Camas hospitalarias",
    "Vehículos": "Todos los vehículos",
    "Banco de sangre": "Bancos de sangre",
    "Laboratorio": "Laboratorios",
    "Quirófano": "Quirófanos",
    "Equipos médicos especiales": "Equipos médicos especiales",
    "Plantas eléctricas": "Plantas eléctricas",
}


def admin_reports(store, token, centers):
    inventory_buttons()
    category = REPORT_CATEGORIES[st.session_state["inventory_category"]]
    inventory_heading(st.session_state["inventory_category"].upper())
    by_id = {center["id"]: center for center in centers}
    selection = st.selectbox(
        "Centro de salud", ["all", *by_id],
        format_func=lambda value: (
            "Todos los centros de salud" if value == "all" else f"{value}. {by_id[value]['name']}"
        ),
        key="summary_center",
    )
    center_id = None if selection == "all" else selection
    group = None
    if category == "Todos los vehículos":
        group_selection = st.selectbox(
            "Grupo de vehículos", ["all", *VEHICLE_GROUPS],
            format_func=lambda value: "Todos los grupos de vehículos" if value == "all" else value,
            key="summary_vehicle_group",
        )
        group = None if group_selection == "all" else group_selection
    data = report_data(store, token, center_id)
    options = ["all", *report_types(data, category, vehicle_group=group)]
    kind_key = f"summary_kind_{category}"
    if st.session_state.get(kind_key, "all") not in options:
        st.session_state[kind_key] = "all"
    selected_kind = st.selectbox(
        "Tipo", options, key=kind_key,
        format_func=lambda value: "Todos los tipos" if value == "all" else value,
    )
    kind = None if selected_kind == "all" else selected_kind
    if not centers:
        st.info("No hay centros registrados.")
        return
    st.dataframe(
        category_summary(store, token, center_id, category, kind=kind, vehicle_group=group),
        width="stretch", hide_index=True,
    )
    pdf_download(
        store, token, center_id, widget_scope="summary",
        category=category, kind=kind, vehicle_group=group, label="GENERAR REPORTE",
    )


def center_view(store, token, center_id):
    if st.session_state.pop("_inventory_changed", False):
        try:
            store.edit_section(token, center_id, st.session_state["inventory_category"])
        except InventoryError as error:
            st.error(str(error))
            st.stop()
    store.initialize_empty_items(token, center_id)
    inventory = store.inventory(token, center_id)
    editable = store.submission(token, center_id)["editable"]
    inventory_buttons()
    selected_category = st.session_state["inventory_category"]
    if selected_category not in REPORT_CATEGORIES:
        raise InventoryError("Categoría de inventario no válida. Selecciona uno de los ítems disponibles.")
    loaded = store.section_loads(token, center_id)[selected_category]
    if loaded and editable:
        st.success("SECCIÓN CARGADA. Bloqueada hasta el envío final; puedes usar EDITAR para corregirla.")
        if st.button("EDITAR", key=f"edit_section_{center_id}_{selected_category}"):
            save(store.edit_section, token, center_id, selected_category)
    editable = editable and not loaded
    if editable:
        st.caption("Si no tienes unidades, deja 00 y pulsa CARGAR DATOS en cada ítem antes de enviar.")
    if missing := st.session_state.pop("_quantity_submission_missing", None):
        st.error(
            "No se pudo enviar. Completa estos datos y vuelve a intentarlo:\n\n"
            + "\n".join(f"- {item}" for item in missing)
        )
    if selected_category == "Vehículos":
        vehicle_panel(
            store, token, center_id, inventory["quantities"], editable=editable,
            history=inventory["vehicle_history"],
        )
    elif selected_category in INVENTORY_QUANTITIES and selected_category != "Plantas eléctricas":
        quantity_panel(
            store, token, center_id, inventory["quantities"], selected_category,
            editable=editable, facility_rows=inventory["facility_counts"],
            legacy_facilities=inventory["facilities"],
            special_rows=inventory["special_laboratories"],
        )
    elif selected_category == "Equipos médicos especiales":
        equipment_panel(
            store, token, center_id, inventory["equipment_counts"], editable=editable,
            history=inventory["equipment"],
        )
    elif selected_category == "Plantas eléctricas":
        inventory_heading("PLANTAS ELÉCTRICAS")
        existing = {row["kind"]: row for row in inventory["plant_counts"]}
        values = quantity_grid(
            center_id, selected_category,
            {"Plantas eléctricas": existing.get("Plantas eléctricas", {"operational": 0, "unavailable": 0})},
            editable=editable, kind_label="Tipo",
        )
        if editable:
            st.caption("Cargar datos guarda las plantas eléctricas sin enviar el inventario semanal.")
            if confirm_load_button(f"load_plants_{center_id}"):
                save(store.load_section, token, center_id, selected_category, values)
    st.divider()
    submission_panel(store, token, center_id)
    pdf_download(
        store, token, center_id,
        category=REPORT_CATEGORIES[selected_category],
    )


def select_category(category):
    st.session_state.pop("_load_confirmation", None)
    st.session_state["inventory_category"] = category


def inventory_buttons():
    categories = [
        ("**CAMAS HOSPITALARIAS**", "Camas"),
        ("VEHÍCULOS", "Vehículos"),
        ("Bancos de sangre", "Banco de sangre"),
        ("Laboratorios", "Laboratorio"),
        ("Quirófanos", "Quirófano"),
        ("Equipos médicos especiales", "Equipos médicos especiales"),
        ("PLANTAS ELÉCTRICAS", "Plantas eléctricas"),
    ]
    st.session_state.setdefault("inventory_category", "Camas")
    if st.session_state["inventory_category"] in ("Ambulancias", "Vehículos protocolares"):
        st.session_state["inventory_category"] = "Vehículos"
    for start in range(0, len(categories), 4):
        row_categories = categories[start:start + 4]
        columns = st.columns(len(row_categories))
        for column, (label, category) in zip(columns, row_categories):
            with column:
                st.button(
                    label,
                    key=f"inventory_category_{category}",
                    type=(
                        "primary"
                        if st.session_state["inventory_category"] == category
                        else "secondary"
                    ),
                    width="stretch",
                    on_click=select_category,
                    args=(category,),
                )


def portal_heading(banner, title, name, *, single_line=False):
    with banner.container(key="center_banner"):
        st.image(institutional_banner(), width="stretch")
    with title.container(key="center_heading"):
        st.html("""
            <style>
            .st-key-center_heading {
                background-color: var(--primary-color, #147d78);
                border-radius: 0.5rem;
                padding: 1.25rem;
                overflow-x: auto;
            }
            .st-key-center_heading h1 {
                color: #ffffff;
                font-weight: 700;
                overflow-wrap: normal;
                word-break: normal;
                text-align: center;
            }
            </style>
        """)
        if single_line:
            st.html("""
                <style>
                .st-key-center_heading h1 {
                    white-space: nowrap;
                    font-size: clamp(0.55rem, 3.4vw, 1.65rem);
                }
                </style>
            """)
        name = re.sub(
            r'"[^"]+"|“[^”]+”|«[^»]+»',
            lambda match: re.sub(r"\s", "\u00a0", match.group()),
            name.upper(),
        )
        st.title(name)


def center_accounts(store, token):
    users = store.users(token)
    st.subheader("Cuentas de centros")
    st.info(
        "Todos ingresan por el mismo enlace con su propio usuario y contraseña. "
        "Cada centro solo accede a su inventario. "
        "Tú asignas el usuario y la clave de cada cuenta y eres quien puede cambiarlos."
    )
    accounted = {user["center_id"] for user in users}
    available = [center for center in store.centers(token) if center["id"] not in accounted]
    if available:
        with st.expander("Crear cuenta para un centro registrado"):
            with st.form("new_account", clear_on_submit=True):
                by_id = {center["id"]: center for center in available}
                center_id = st.selectbox(
                    "Centro", list(by_id),
                    format_func=lambda value: f"{value}. {by_id[value]['name']}"
                    + (f" — {by_id[value]['location']}" if by_id[value]["location"] else ""),
                    key="account_center_id",
                )
                if by_id[center_id]["assigned_username"]:
                    st.caption(f"Usuario asignado en el catálogo: {by_id[center_id]['assigned_username']}")
                username = st.text_input("Usuario del centro", max_chars=40, key="account_new_username")
                password = st.text_input(
                    "Contraseña", type="password", max_chars=128, key="account_new_password",
                )
                confirmation = st.text_input(
                    "Confirmar contraseña", type="password", max_chars=128,
                    key="account_new_confirmation",
                )
                st.caption(
                    "El nombre y la ubicación ya están registrados; solo asignas el acceso. "
                    "Usuario: 3 a 40 letras sin acentos, números, punto, guion o guion bajo. "
                    "Contraseña: 12 a 128 caracteres. Tú la defines y solo tú puedes cambiarla."
                )
                if st.form_submit_button("Crear cuenta"):
                    if password != confirmation:
                        st.error("Las contraseñas no coinciden.")
                    else:
                        try:
                            store.create_account(token, center_id, username, password)
                        except InventoryError as error:
                            st.error(str(error))
                        else:
                            st.session_state["notice"] = "Cuenta creada. Entrega las credenciales por un canal privado."
                            st.rerun()
    with st.expander("Crear centro nuevo y cuenta"):
        with st.form("new_center", clear_on_submit=True):
            name = st.text_input("Nombre del centro", key="account_center_name")
            location = st.text_input("Ubicación", key="account_center_location")
            username = st.text_input("Usuario del centro", max_chars=40, key="account_username")
            password = st.text_input(
                "Contraseña", type="password", max_chars=128, key="account_password",
            )
            confirmation = st.text_input(
                "Confirmar contraseña", type="password", max_chars=128,
                key="account_confirmation",
            )
            st.caption(
                "Usuario: 3 a 40 letras sin acentos, números, punto, guion o guion bajo. "
                "Contraseña: 12 a 128 caracteres. Tú la defines y solo tú puedes cambiarla."
            )
            if st.form_submit_button("Crear centro y cuenta"):
                if password != confirmation:
                    st.error("Las contraseñas no coinciden.")
                else:
                    try:
                        store.create_center(token, name, location, username, password)
                    except InventoryError as error:
                        st.error(str(error))
                    else:
                        st.session_state["notice"] = "Centro y cuenta creados. Entrega las credenciales por un canal privado."
                        st.rerun()
    if not users:
        st.info("No hay cuentas de centros registradas.")
        return
    st.divider()
    st.caption(
        f"{len(users)} cuentas registradas. Desde cada panel puedes cambiar la clave, "
        "activar o desactivar la cuenta y editar sus datos."
    )
    for user in users:
        user_id = user["id"]
        status = "🟢 Activa" if user["active"] else "🔴 Desactivada"
        with st.container(border=True):
            st.markdown(f"**{user['center']}** — `{user['username']}` · {status}")
            with st.form(f"password_user_{user_id}", clear_on_submit=True):
                password = st.text_input(
                    "Nueva contraseña", type="password", max_chars=128,
                    key=f"account_password_{user_id}",
                )
                confirmation = st.text_input(
                    "Confirmar nueva contraseña", type="password", max_chars=128,
                    key=f"account_confirmation_{user_id}",
                )
                st.caption(
                    "Entre 12 y 128 caracteres. Al cambiarla se cierran las sesiones del centro."
                )
                if st.form_submit_button("Cambiar contraseña"):
                    if password != confirmation:
                        st.error("Las contraseñas no coinciden.")
                    elif not 12 <= len(password) <= 128:
                        st.error("La contraseña debe tener entre 12 y 128 caracteres.")
                    else:
                        try:
                            store.manage_user(token, user_id, user["active"], password)
                        except InventoryError as error:
                            st.error(str(error))
                        else:
                            st.session_state["notice"] = "Contraseña actualizada."
                            st.rerun()
            if user["active"]:
                if st.button("Desactivar cuenta", key=f"deactivate_user_{user_id}"):
                    store.manage_user(token, user_id, False)
                    st.session_state["notice"] = "Cuenta desactivada. El inventario se conserva."
                    st.rerun()
            else:
                if st.button("Activar cuenta", key=f"activate_user_{user_id}", type="primary"):
                    store.manage_user(token, user_id, True)
                    st.session_state["notice"] = "Cuenta activada."
                    st.rerun()
            with st.expander("Editar nombre, ubicación y usuario"):
                with st.form(f"manage_user_{user_id}"):
                    name = st.text_input(
                        "Nombre del centro", value=user["center"], key=f"account_name_{user_id}",
                    )
                    location = st.text_input(
                        "Ubicación", value=user["location"] or "", key=f"account_location_{user_id}",
                    )
                    username = st.text_input(
                        "Usuario del centro", value=user["username"], max_chars=40,
                        key=f"account_user_{user_id}",
                    )
                    st.caption("Cambiar el usuario cierra las sesiones del centro.")
                    if st.form_submit_button("Guardar datos"):
                        try:
                            store.update_center(token, user["center_id"], name, location, username)
                        except InventoryError as error:
                            st.error(str(error))
                        else:
                            st.session_state["notice"] = "Datos de la cuenta actualizados."
                            st.rerun()


def main():
    st.set_page_config(page_title="DIGESALUD-MPPD", page_icon="🏥", layout="wide")
    st.html("""
        <style>
        [class*="st-key-report_confirmation_"] [data-testid="stAlert"] [data-testid="stMarkdownContainer"] {
            text-align: center;
            width: 100%;
        }
        .stButton button, .stFormSubmitButton button, .stDownloadButton button,
        .stDownloadButton a {
            text-transform: uppercase;
            font-weight: 700;
        }
        .stButton button p, .stFormSubmitButton button p,
        .stDownloadButton button p, .stDownloadButton a p {
            font-weight: 700;
        }
        .st-key-inventory_category_Camas button {
            height: auto;
            min-height: 2.5rem;
        }
        .st-key-inventory_category_Camas button p {
            white-space: normal;
            overflow: visible;
            text-overflow: clip;
            overflow-wrap: anywhere;
        }
        </style>
    """)
    banner = st.empty()
    shield = st.empty()
    with shield.container(key="login_shield"):
        _left, middle, _right = st.columns([1, 1, 1])
        with middle:
            _pad_left, emblem, _pad_right = st.columns([1, 2, 1])
            emblem.image(str(Path(__file__).with_name("escudo.png")), width="stretch")
    title = st.empty()
    with title.container(key="login_heading"):
        st.html("""
            <style>
            .st-key-login_heading h1 {
                text-align: center;
                font-size: clamp(0.9rem, 3vw, 1.65rem);
            }
            </style>
        """)
        st.title("SALA SITUACIONAL DIGESALUD-MPPD")
    subtitle = st.empty()
    development = os.environ.get("SALUD_DEVELOPMENT_MODE") == "1"
    if development:
        path, password, _directory, development_centers = development_store(load_center_catalog())
        store = Store(path, allow_out_of_schedule=True)
        token, actor = development_login(store, password, development_centers)
    else:
        store = Store()
        bootstrap_from_secrets(store)
        token, actor = login(store)
    shield.empty()
    centers = store.centers(token)
    if actor["role"] == "admin":
        portal_heading(banner, title, "SALA SITUACIONAL DIGESALUD-MPPD", single_line=True)
        subtitle.empty()
        if not development:
            page = st.sidebar.radio(
                "Administración", ["Informes", "Cuentas de centros"], key="admin_page",
            )
            if page == "Cuentas de centros":
                center_accounts(store, token)
                return
        centers = store.centers(token)
        summary = store.summary(token)
        period = datetime.fromtimestamp(weekly_status(0, time.time())["period_start"], REPORT_TIMEZONE)
        period_end = period + timedelta(days=4)
        reported_count = sum(row["Estado"] == REPORT_LOADED for row in summary)
        with subtitle.container(key="weekly_report_count"):
            st.markdown(
                f"**Esta semana — Semana {period.isocalendar().week} "
                f"({period:%d/%m/%Y} al {period_end:%d/%m/%Y})**\n\n"
                f"**Centros de Salud que Han Reportado: {reported_count}/{len(summary)} "
                f"Faltan: {len(summary) - reported_count}**"
            )
        inventory_heading("RESUMEN DE LOS CENTROS DE SALUD", centered=True)
        admin_reports(store, token, centers)
        if summary:
            pending = [row for row in summary if row["Estado"] == REPORT_PENDING]
            reported = [row for row in summary if row["Estado"] == REPORT_LOADED]
            if pending:
                st.error(
                    f"**{REPORT_PENDING.upper()}**\n\n"
                    + "\n".join(f"- **{row['N°']}. {row['Centro']}**" for row in pending)
                )
            if reported:
                success_message(
                    f"**{REPORT_LOADED}**\n\n"
                    + "\n".join(f"- **{row['N°']}. {row['Centro']}**" for row in reported),
                    key="summary",
                )
        else:
            st.info("No hay centros registrados.")
        return
    if centers:
        portal_heading(banner, title, centers[0]["name"])
        subtitle.empty()
    else:
        st.info("No hay un centro de salud asignado a esta cuenta.")
        st.stop()
    center_view(store, token, centers[0]["id"])


if __name__ == "__main__":
    try:
        main()
    except AccessError as error:
        st.error(str(error))
        st.stop()
    except InventoryError as error:
        st.error(str(error))
    except (sqlite3.Error, OSError):
        LOGGER.exception("Error de almacenamiento del inventario")
        st.error("No se pudo acceder al almacenamiento. Revisa el servidor antes de continuar.")
        st.stop()
