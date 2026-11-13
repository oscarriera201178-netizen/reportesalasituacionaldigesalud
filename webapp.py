import hmac
import io
import logging
import os
import secrets
from datetime import datetime, timedelta
from functools import lru_cache, wraps
from pathlib import Path
from urllib.parse import urlsplit

import pymupdf
from flask import (
    Flask, Response, abort, flash, redirect, render_template, request, send_file,
    send_from_directory, session, url_for,
)

from report import (
    SUMMARY_CATEGORIES, generate_military_pdf, generate_pdf, report_data, report_types,
)
from database import DATABASE_ERRORS
from store import (
    AccessError, BED_TYPES, InventoryError, INVENTORY_QUANTITIES, MILITARY_CAUSES,
    MILITARY_COMPONENTS, MILITARY_GRADES, MILITARY_REDI,
    REPORT_LOADED, REPORT_SECTIONS, REPORT_TIMEZONE, load_center_catalog,
    SPECIAL_EQUIPMENT_TYPES, STATES, Store, VEHICLE_GROUPS,
    weekly_status,
)


LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
REPORT_CATEGORIES = {
    "Camas": "Camas hospitalarias",
    "Vehículos": "Todos los vehículos",
    "Banco de sangre": "Bancos de sangre",
    "Laboratorio": "Laboratorios",
    "Quirófano": "Quirófanos",
    "Equipos médicos especiales": "Equipos médicos especiales",
    "Plantas eléctricas": "Plantas eléctricas",
}
SECTION_LABELS = {
    "Camas": "Camas hospitalarias",
    "Vehículos": "Vehículos",
    "Banco de sangre": "Banco de sangre",
    "Laboratorio": "Laboratorios",
    "Quirófano": "Quirófanos",
    "Equipos médicos especiales": "Equipos médicos especiales",
    "Plantas eléctricas": "Plantas eléctricas",
}


def create_app(store=None, *, secret_key=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=secret_key or os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get(
            "COOKIE_SECURE", "1" if os.environ.get("APP_ENV") == "production" else "0",
        ) == "1",
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if not app.config["SECRET_KEY"]:
        if os.environ.get("APP_ENV") == "production":
            raise RuntimeError("Configura FLASK_SECRET_KEY antes de iniciar el servidor.")
        app.config["SECRET_KEY"] = secrets.token_hex(32)
    if store is None:
        database_url = os.environ.get("DATABASE_URL")
        if os.environ.get("VERCEL") and not database_url:
            raise RuntimeError("Configura DATABASE_URL con una base PostgreSQL de Vercel Marketplace.")
        store = Store(database_url=database_url) if database_url else Store()
    bootstrap_from_environment(store)
    app.extensions["inventory_store"] = store

    @app.get("/app.css")
    def app_css():
        return send_from_directory(ROOT / "public", "app.css")

    def get_store():
        return app.extensions["inventory_store"]

    def token():
        return session.get("token", "")

    def actor():
        if not token():
            return None
        try:
            return get_store().identity(token())
        except AccessError:
            session.clear()
            return None

    def require_role(role=None):
        current = actor()
        if current is None:
            flash("Inicia sesión para continuar.", "error")
            return None
        if current["must_change"] and request.endpoint != "change_password":
            return redirect(url_for("change_password"))
        if role and current["role"] != role:
            abort(403)
        return current

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            current = require_role("admin")
            if not isinstance(current, dict):
                return current or redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    @app.before_request
    def protect_forms():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        if request.method == "POST":
            supplied = request.form.get("csrf_token", "")
            if not hmac.compare_digest(supplied, session["csrf"]):
                abort(400, "La solicitud expiró. Recarga la página e inténtalo otra vez.")

    @app.context_processor
    def template_context():
        return {"csrf_token": session.get("csrf", ""), "current_actor": actor()}

    @app.errorhandler(InventoryError)
    def inventory_error(error):
        flash(str(error), "error")
        referrer = urlsplit(request.referrer or "")
        destination = (
            referrer.path + (f"?{referrer.query}" if referrer.query else "")
            if referrer.netloc in ("", request.host) else ""
        )
        if not destination.startswith("/") or destination.startswith("//"):
            destination = url_for("home")
        return redirect(destination, code=303)

    @app.errorhandler(AccessError)
    def access_error(error):
        session.clear()
        flash(str(error), "error")
        return redirect(url_for("login"), code=303)

    def storage_error(error):
        LOGGER.exception("Error de almacenamiento del inventario", exc_info=error)
        return "No se pudo acceder al almacenamiento. Revisa el servidor antes de continuar.", 503
    for exception in (*DATABASE_ERRORS, OSError):
        app.register_error_handler(exception, storage_error)

    @lru_cache(maxsize=1)
    def institutional_banner():
        with pymupdf.open(ROOT / "cintillo.pdf") as document:
            return document[0].get_pixmap(
                matrix=pymupdf.Matrix(2, 2), clip=pymupdf.Rect(0, 0, 960, 95),
                alpha=False,
            ).tobytes("png")

    @app.get("/cintillo.png")
    def banner():
        return Response(institutional_banner(), mimetype="image/png")

    @app.get("/escudo.png")
    def shield():
        return send_from_directory(ROOT, "escudo.png")

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if actor():
            return redirect(url_for("home"))
        if request.method == "POST":
            try:
                authenticated = get_store().login(
                    request.form.get("username", ""),
                    request.form.get("password", ""),
                )
            except AccessError as error:
                flash(str(error), "error")
            else:
                session.clear()
                session["token"] = authenticated
                session["csrf"] = secrets.token_urlsafe(32)
                return redirect(url_for("home"))
        try:
            initialized = get_store().initialized()
        except (*DATABASE_ERRORS, OSError):
            LOGGER.exception("No se pudo comprobar el almacenamiento")
            abort(503, "No se pudo acceder al almacenamiento.")
        return render_template("login.html", initialized=initialized)

    @app.post("/logout")
    def logout():
        if token():
            get_store().logout(token())
        session.clear()
        flash("Sesión cerrada.", "success")
        return redirect(url_for("login"))

    @app.route("/password", methods=("GET", "POST"))
    def change_password():
        current_actor = require_role()
        if not isinstance(current_actor, dict):
            if current_actor:
                return current_actor
            return redirect(url_for("login"))
        if request.method == "POST":
            new_password = request.form.get("new_password", "")
            if new_password != request.form.get("confirmation", ""):
                raise InventoryError("Las contraseñas no coinciden.")
            get_store().change_password(
                token(), request.form.get("current_password", ""), new_password,
            )
            session.clear()
            flash("Contraseña actualizada. Inicia sesión nuevamente.", "success")
            return redirect(url_for("login"))
        return render_template("password.html", mandatory=current_actor["must_change"])

    @app.get("/")
    def home():
        current_actor = require_role()
        if not isinstance(current_actor, dict):
            if current_actor:
                return current_actor
            return redirect(url_for("login"))
        if current_actor["role"] == "admin":
            return render_admin(get_store(), token())
        if current_actor["account_type"] == "military":
            return redirect(url_for("military_report"))
        centers = get_store().centers(token())
        if not centers:
            abort(403, "La cuenta no tiene un centro asignado.")
        return redirect(url_for("inventory", center_id=centers[0]["id"]))

    def render_admin(store_obj, auth_token):
        centers = store_obj.centers(auth_token)
        summary = store_obj.summary(auth_token)
        period = datetime.fromtimestamp(
            weekly_status(0, datetime.now(REPORT_TIMEZONE).timestamp())["period_start"],
            REPORT_TIMEZONE,
        )
        category = request.args.get("category", "Camas")
        if category not in REPORT_CATEGORIES:
            category = "Camas"
        report_category = REPORT_CATEGORIES[category]
        selected_center = request.args.get("center", "all")
        center_id = None
        if selected_center != "all":
            try:
                center_id = int(selected_center)
            except ValueError:
                abort(400, "Centro seleccionado no válido.")
            if center_id not in {center["id"] for center in centers}:
                abort(400, "Centro seleccionado no válido.")
        vehicle_group = request.args.get("group") or None
        if vehicle_group not in VEHICLE_GROUPS:
            vehicle_group = None
        data = report_data(store_obj, auth_token, center_id)
        options = report_types(data, report_category, vehicle_group=vehicle_group)
        kind = request.args.get("kind") or None
        if kind not in options:
            kind = None
        rows = summary_rows(data, report_category, kind=kind, vehicle_group=vehicle_group)
        reported = sum(row["Estado"] == REPORT_LOADED for row in summary)
        return render_template(
            "admin.html", centers=centers, summary=summary, rows=rows,
            categories=REPORT_CATEGORIES, category=category,
            report_category=report_category, center_id=selected_center,
            vehicle_group=vehicle_group, vehicle_groups=VEHICLE_GROUPS,
            options=options, kind=kind, reported=reported,
            period_week=period.isocalendar().week,
            period_start=period.strftime("%d/%m/%Y"),
            period_end=(period + timedelta(days=4)).strftime("%d/%m/%Y"),
        )

    def summary_rows(data, category, *, kind=None, vehicle_group=None):
        options = report_types(data, category, vehicle_group=vehicle_group)
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
        rows = [
            {"Tipo": label, "Operativas": values[0], "Fuera de servicio": values[1],
             "Total": sum(values)}
            for label, values in totals.items()
        ]
        rows.append({
            "Tipo": "TOTAL",
            "Operativas": sum(row["Operativas"] for row in rows),
            "Fuera de servicio": sum(row["Fuera de servicio"] for row in rows),
            "Total": sum(row["Total"] for row in rows),
        })
        return rows

    @app.get("/admin/accounts")
    @admin_required
    def accounts():
        store_obj = get_store()
        users = store_obj.users(token())
        accounted = {user["center_id"] for user in users}
        available_centers = [
            center for center in store_obj.centers(token())
            if center["id"] not in accounted
        ]
        accounted_components = {
            user["center"] for user in users if user["account_type"] == "military"
        }
        return render_template(
            "accounts.html", users=users, available_centers=available_centers,
            available_components=[
                component for component in MILITARY_COMPONENTS
                if component not in accounted_components
            ],
        )

    @app.post("/admin/accounts")
    @admin_required
    def account_action():
        store_obj = get_store()
        action = request.form.get("action", "")
        if action == "create_center":
            password = request.form.get("password", "")
            if password != request.form.get("confirmation", ""):
                raise InventoryError("Las contraseñas no coinciden.")
            store_obj.create_center(
                token(), request.form.get("name", ""), request.form.get("location", ""),
                request.form.get("username", ""), password,
            )
            flash("Centro y cuenta creados. Entrega las credenciales por un canal privado.", "success")
        elif action == "create_military_account":
            password = request.form.get("password", "")
            if password != request.form.get("confirmation", ""):
                raise InventoryError("Las contraseñas no coinciden.")
            store_obj.create_military_account(
                token(), request.form.get("component", ""),
                request.form.get("username", ""), password,
            )
            flash("Cuenta militar creada. Entrega las credenciales por un canal privado.", "success")
        elif action == "create_account":
            password = request.form.get("password", "")
            if password != request.form.get("confirmation", ""):
                raise InventoryError("Las contraseñas no coinciden.")
            try:
                center_id = int(request.form.get("center_id", "0"))
            except ValueError as error:
                raise InventoryError("Centro seleccionado no válido.") from error
            store_obj.create_account(
                token(), center_id, request.form.get("username", ""), password,
            )
            flash("Cuenta creada. Entrega las credenciales por un canal privado.", "success")
        elif action in {"update", "password", "toggle"}:
            try:
                user_id = int(request.form.get("user_id", "0"))
            except ValueError as error:
                raise InventoryError("Selecciona una cuenta de centro válida.") from error
            users = {user["id"]: user for user in store_obj.users(token())}
            user = users.get(user_id)
            if not user:
                abort(404)
            if action == "update":
                if user["account_type"] == "military":
                    abort(403)
                store_obj.update_center(
                    token(), user["center_id"], request.form.get("name", ""),
                    request.form.get("location", ""), request.form.get("username", ""),
                )
                flash("Datos de la cuenta actualizados.", "success")
            elif action == "password":
                password = request.form.get("password", "")
                if password != request.form.get("confirmation", ""):
                    raise InventoryError("Las contraseñas no coinciden.")
                store_obj.manage_user(token(), user_id, user["active"], password)
                flash("Contraseña actualizada.", "success")
            else:
                active = request.form.get("active") == "1"
                store_obj.manage_user(token(), user_id, active)
                flash("Cuenta activada." if active else "Cuenta desactivada. El inventario se conserva.", "success")
        else:
            abort(400, "Acción no válida.")
        return redirect(url_for("accounts"))

    def filtered_military_records(current_actor):
        selected_component = request.args.get("component") or None
        if current_actor["role"] != "admin":
            selected_component = current_actor["center_name"]
        elif selected_component is not None and selected_component not in MILITARY_COMPONENTS:
            abort(400, "Componente militar no válido.")
        filters = {}
        for field, label, maximum in (("month", "Mes", 12), ("year", "Año", 9999)):
            raw = request.args.get(field, "")
            try:
                value = int(raw) if raw else None
            except ValueError:
                abort(400, f"{label} no válido.")
            if value is not None and not 1 <= value <= maximum:
                abort(400, f"{label} no válido.")
            filters[field] = value
        selected_redi = request.args.get("redi") or None
        selected_cause = request.args.get("cause") or None
        if selected_redi is not None and selected_redi not in MILITARY_REDI:
            abort(400, "REDI no válida.")
        if selected_cause is not None and selected_cause not in MILITARY_CAUSES:
            abort(400, "Causa de fallecimiento no válida.")
        filters["redi"] = selected_redi
        filters["cause"] = selected_cause
        records = [
            record for record in get_store().military_records(token())
            if (selected_component is None or record["component"] == selected_component)
            and (filters["month"] is None or int(record["death_date"][5:7]) == filters["month"])
            and (filters["year"] is None or int(record["death_date"][:4]) == filters["year"])
            and (selected_redi is None or record["redi"] == selected_redi)
            and (selected_cause is None or record["cause"] == selected_cause)
        ]
        return records, selected_component, filters

    @app.get("/military")
    def military_report():
        current_actor = require_role()
        if not isinstance(current_actor, dict):
            return current_actor or redirect(url_for("login"))
        if current_actor["role"] != "admin" and current_actor["account_type"] != "military":
            abort(403)
        records, selected_component, filters = filtered_military_records(current_actor)
        return render_template(
            "military_records.html", records=records,
            military_grades=MILITARY_GRADES, military_causes=MILITARY_CAUSES,
            military_redi=MILITARY_REDI, military_components=MILITARY_COMPONENTS,
            selected_component=selected_component, month=filters["month"],
            year=filters["year"], selected_redi=filters["redi"],
            selected_cause=filters["cause"],
            months=(
                "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
            ),
        )

    @app.post("/military")
    def add_military_record():
        current_actor = require_role("center")
        if not isinstance(current_actor, dict):
            return current_actor or redirect(url_for("login"))
        if current_actor["account_type"] != "military":
            abort(403)
        get_store().add_military_record(
            token(), request.form.get("grade", ""), request.form.get("full_name", ""),
            request.form.get("cedula", ""), request.form.get("birth_date", ""),
            request.form.get("death_date", ""), request.form.get("cause", ""),
            request.form.get("redi", ""), request.form.get("zodi", ""),
            request.form.get("unit", ""),
        )
        flash("Registro ingresado.", "success")
        return redirect(url_for("military_report"))

    @app.get("/military/report.pdf")
    def download_military_report():
        current_actor = require_role()
        if not isinstance(current_actor, dict):
            return current_actor or redirect(url_for("login"))
        if current_actor["role"] != "admin" and current_actor["account_type"] != "military":
            abort(403)
        records, selected_component, _filters = filtered_military_records(current_actor)
        pdf = generate_military_pdf(
            records, component=selected_component,
        )
        return send_file(
            io.BytesIO(pdf), as_attachment=True,
            download_name="Registro_de_Militares_Fallecidos.pdf",
            mimetype="application/pdf",
        )

    @app.get("/backup")
    @admin_required
    def backup():
        data = get_store().sqlite_backup(token())
        name = f"inventario-{datetime.now(REPORT_TIMEZONE):%Y%m%d-%H%M%S}.sqlite3"
        return send_file(
            io.BytesIO(data), as_attachment=True, download_name=name,
            mimetype="application/octet-stream",
        )

    @app.get("/inventory/<int:center_id>")
    def inventory(center_id):
        current_actor = require_role("center")
        if not isinstance(current_actor, dict):
            return current_actor or redirect(url_for("login"))
        store_obj = get_store()
        centers = store_obj.centers(token())
        if not centers or centers[0]["id"] != center_id:
            abort(403)
        store_obj.initialize_empty_items(token(), center_id)
        inventory_data = store_obj.inventory(token(), center_id)
        category = request.args.get("section", "Camas")
        if category not in REPORT_CATEGORIES:
            category = "Camas"
        loaded = store_obj.section_loads(token(), center_id)
        submission = store_obj.submission(token(), center_id)
        editable = submission["editable"] and not loaded[category]
        rows, presence_items, special_labs = inventory_form_data(
            category, inventory_data,
        )
        status = submission
        missing = []
        if status["open"] and not status["loaded"]:
            missing = store_obj.missing_data(token(), center_id)
            if not missing:
                missing = store_obj.missing_inventory_categories(token(), center_id)
                missing.extend(
                    f"{SECTION_LABELS[section]}: pendiente de cargar en este período."
                    for section, is_loaded in loaded.items() if not is_loaded
                )
        return render_template(
            "inventory.html", center=centers[0], categories=REPORT_CATEGORIES,
            category=category, rows=rows, presence_items=presence_items,
            special_labs=special_labs, loaded=loaded[category],
            editable=editable, status=status, missing=missing,
            vehicle_groups=VEHICLE_GROUPS, states=STATES,
            vehicle_kinds=[kind for group in VEHICLE_GROUPS.values() for kind in group],
            pdf_category=REPORT_CATEGORIES[category],
            vehicle_history=inventory_data["vehicle_history"] if category == "Vehículos" else [],
            equipment_history=inventory_data["equipment"] if category == "Equipos médicos especiales" else [],
            legacy_facilities=[
                row for row in inventory_data["facilities"]
                if row["category"] == category
            ] if category in ("Banco de sangre", "Laboratorio", "Quirófano") else [],
        )

    @app.get("/inventory/<int:center_id>/report.pdf")
    def download_center_report(center_id):
        current = require_role("center")
        if not isinstance(current, dict):
            return current or redirect(url_for("login"))
        selected = request.args.get("category", "")
        if selected not in REPORT_CATEGORIES.values():
            abort(400, "Categoría de informe no válida.")
        data = generate_pdf(get_store(), token(), center_id, category=selected)
        return send_file(
            io.BytesIO(data), as_attachment=True,
            download_name=f"Cuadros_{center_id}_{selected}.pdf",
            mimetype="application/pdf",
        )

    def inventory_form_data(category, data):
        rows = []
        presence = []
        special_labs = data["special_laboratories"]
        if category == "Camas":
            source = [r for r in data["quantities"] if r["category"] == "Camas"]
            rows = quantity_rows(BED_TYPES, source)
        elif category == "Vehículos":
            source = [r for r in data["quantities"] if r["category"] == "Vehículos"]
            kinds = [kind for group in VEHICLE_GROUPS.values() for kind in group]
            kinds.extend(row["kind"] for row in source if row["kind"] not in kinds)
            rows = quantity_rows(kinds, source)
        elif category == "Equipos médicos especiales":
            rows = quantity_rows(SPECIAL_EQUIPMENT_TYPES, data["equipment_counts"])
        elif category == "Plantas eléctricas":
            rows = quantity_rows(INVENTORY_QUANTITIES[category], data["plant_counts"])
        elif category in ("Banco de sangre", "Laboratorio", "Quirófano"):
            types = INVENTORY_QUANTITIES[category]
            source = [r for r in data["facility_counts"] if r["category"] == category]
            known_kinds = list(types)
            known_kinds.extend(row["kind"] for row in source if row["kind"] not in known_kinds)
            for kind in known_kinds:
                matches = [row for row in source if row["kind"] == kind]
                operational = sum(row["operational"] for row in matches)
                unavailable = sum(row["unavailable"] for row in matches)
                if category == "Quirófano":
                    label = {
                        "En pisos": "Quirófano en piso",
                        "En emergencias": "Quirófano en emergencia",
                    }.get(kind, kind)
                    presence.append({
                        "kind": kind, "label": label, "has": operational + unavailable > 0,
                        "operational": operational, "unavailable": unavailable,
                        "with_quantity": True,
                    })
                else:
                    label = {
                        "Banco de sangre": "Banco de sangre",
                        "Laboratorio": "Laboratorio central",
                        "Laboratorio de emergencia": "Laboratorio de emergencia",
                    }.get(kind, kind)
                    legacy = [
                        row for row in data["facilities"]
                        if row["category"] == category and row["kind"] == kind
                    ]
                    operational += sum(row["state"] == "Operativo" for row in legacy)
                    unavailable += sum(row["state"] == "Fuera de servicio" for row in legacy)
                    units = operational + unavailable
                    state = "Fuera de servicio" if unavailable and not operational else "Operativo"
                    presence.append({
                        "kind": kind, "label": label, "has": bool(units),
                        "state": state, "operational": operational, "unavailable": unavailable,
                        "with_quantity": False,
                    })
        return rows, presence, special_labs

    def quantity_rows(kinds, source):
        values = {row["kind"]: row for row in source}
        return [{
            "kind": kind,
            "operational": values.get(kind, {}).get("operational", 0),
            "unavailable": values.get(kind, {}).get("unavailable", 0),
        } for kind in kinds]

    @app.post("/inventory/<int:center_id>/<section>")
    def save_inventory(center_id, section):
        current = require_role("center")
        if not isinstance(current, dict):
            return current or redirect(url_for("login"))
        if section not in REPORT_SECTIONS:
            abort(404)
        store_obj = get_store()
        action = request.form.get("action", "load")
        if action == "edit":
            store_obj.edit_section(token(), center_id, section)
            flash("La sección está habilitada para editar.", "success")
        elif action == "submit":
            store_obj.submit(
                token(), center_id, require_all_categories=True,
                require_loaded_sections=True,
            )
            flash(REPORT_LOADED, "success")
        elif action == "load":
            quantities = parse_quantities(request.form, section, store_obj, token(), center_id)
            if section == "Laboratorio":
                has_special = request.form.get("special_presence") == "Sí"
                laboratories = []
                if has_special:
                    for slot in range(1, 4):
                        name = request.form.get(f"special_name_{slot}", "").strip()
                        state = request.form.get(f"special_state_{slot}", STATES[0])
                        if name:
                            laboratories.append({"slot": slot, "name": name, "state": state})
                store_obj.load_laboratories(
                    token(), center_id, quantities, has_special, laboratories,
                )
            else:
                store_obj.load_section(token(), center_id, section, quantities)
            flash("Inventario guardado. La sección quedó bloqueada hasta el envío final.", "success")
        else:
            abort(400, "Acción no válida.")
        return redirect(url_for("inventory", center_id=center_id, section=section))

    def parse_quantities(form, category, store_obj, auth_token, center_id):
        existing = store_obj.inventory(auth_token, center_id)
        if category == "Camas":
            kinds = list(BED_TYPES)
            source = existing["quantities"]
            kinds.extend(row["kind"] for row in source if row["category"] == category and row["kind"] not in kinds)
        elif category == "Vehículos":
            kinds = [kind for group in VEHICLE_GROUPS.values() for kind in group]
            source = existing["quantities"]
            kinds.extend(row["kind"] for row in source if row["category"] == category and row["kind"] not in kinds)
        elif category == "Equipos médicos especiales":
            kinds, source = list(SPECIAL_EQUIPMENT_TYPES), existing["equipment_counts"]
        elif category == "Plantas eléctricas":
            kinds, source = list(INVENTORY_QUANTITIES[category]), existing["plant_counts"]
        elif category in ("Banco de sangre", "Quirófano"):
            kinds = list(INVENTORY_QUANTITIES[category])
            source = [r for r in existing["facility_counts"] if r["category"] == category]
            kinds.extend(row["kind"] for row in source if row["kind"] not in kinds)
        elif category == "Laboratorio":
            kinds = list(INVENTORY_QUANTITIES[category])
            source = [r for r in existing["facility_counts"] if r["category"] == category]
            kinds.extend(row["kind"] for row in source if row["kind"] not in kinds)
        else:
            raise InventoryError("Categoría de inventario no válida.")
        values = {}
        for kind in kinds:
            prefix = f"qty_{kinds.index(kind)}"
            if category in ("Banco de sangre", "Laboratorio", "Quirófano"):
                presence_key = f"presence_{kinds.index(kind)}"
                selected = form.get(presence_key, "")
                if category == "Quirófano":
                    if selected not in ("Sí", "No"):
                        raise InventoryError(f"Indica si hay {kind.lower()}.")
                    operational = parse_count(form, prefix + "_operational", 1 if selected == "Sí" else 0)
                    unavailable = parse_count(form, prefix + "_unavailable", 0)
                    if selected == "No":
                        operational = unavailable = 0
                    elif operational + unavailable == 0:
                        raise InventoryError(f"Indica al menos una unidad para {kind.lower()}.")
                else:
                    if selected not in ("Sí", "No"):
                        raise InventoryError(f"Indica si hay {kind.lower()}.")
                    state = form.get(f"state_{kinds.index(kind)}", "")
                    if selected == "Sí" and state not in STATES:
                        raise InventoryError(f"Selecciona el estado de {kind.lower()}.")
                    operational = int(selected == "Sí" and state == "Operativo")
                    unavailable = int(selected == "Sí" and state == "Fuera de servicio")
                values[kind] = (operational, unavailable)
            else:
                values[kind] = (
                    parse_count(form, prefix + "_operational"),
                    parse_count(form, prefix + "_unavailable"),
                )
        return values

    def parse_count(form, field, default=None):
        value = form.get(field)
        if value in (None, "") and default is not None:
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise InventoryError("Completa todas las cantidades con números enteros.") from error
        if not 0 <= parsed <= 1_000_000:
            raise InventoryError("Las cantidades deben estar entre 0 y 1.000.000.")
        return parsed

    @app.get("/reports.pdf")
    @admin_required
    def download_report():
        selected_center = request.args.get("center", "all")
        try:
            center_id = None if selected_center == "all" else int(selected_center)
        except ValueError:
            abort(400, "Centro seleccionado no válido.")
        category_key = request.args.get("category", "Camas")
        if category_key not in REPORT_CATEGORIES:
            abort(400, "Categoría de informe no válida.")
        category = REPORT_CATEGORIES[category_key]
        group = request.args.get("group") or None
        kind = request.args.get("kind") or None
        data = generate_pdf(
            get_store(), token(), center_id, category=category, kind=kind,
            vehicle_group=group,
        )
        return send_file(
            io.BytesIO(data), as_attachment=True,
            download_name=f"Cuadros_{selected_center}_{category}.pdf",
            mimetype="application/pdf",
        )

    return app


def bootstrap_from_environment(store):
    username = os.environ.get("BOOTSTRAP_ADMIN_USERNAME")
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
    if username is None and password is None:
        return
    if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
        raise InventoryError(
            "Configura BOOTSTRAP_ADMIN_USERNAME y BOOTSTRAP_ADMIN_PASSWORD juntos.",
        )
    if store.initialized():
        return
    try:
        store.bootstrap(username, password)
    except InventoryError:
        if not store.initialized():
            raise
    else:
        store.bootstrap_catalog(load_center_catalog())


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8503")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
