from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from gateway_web import install_gateway, initialize_gateway
from database import Database, SyncSafetyError
from message_builder import (
    ALERT_TYPES,
    BUILDINGS,
    TECHNICAL_CAUSES,
    AlertValidationError,
    MessagePreview,
    build_message,
)
from recipient_validation import HeaderValidationError, validate_sheet_values
from sheets_service import (
    SheetsConfigurationError,
    SheetsReadError,
    read_service_account_email,
    read_sheet_values,
)

BASE_DIR = Path(__file__).resolve().parent
database = Database(settings.database_path)


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    initialize_gateway(database)
    yield


app = FastAPI(
    title="Programa de Alertas",
    description="Prototipo institucional con Google Sheets y simulación local",
    version="0.4.0",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
install_gateway(app, database, templates)


def common_context(request: Request, *, active_page: str) -> dict[str, object]:
    return {
        "request": request,
        "active_page": active_page,
        "app_mode": settings.app_mode,
        "sms_enabled": settings.sms_enabled,
        "buildings": BUILDINGS,
        "alert_types": ALERT_TYPES,
        "technical_causes": TECHNICAL_CAUSES,
    }


def form_context(
    request: Request,
    *,
    error: str | None = None,
    selected: dict[str, str] | None = None,
) -> dict[str, object]:
    context = common_context(request, active_page="alert")
    context.update(
        {
            "error": error,
            "selected": selected or {},
            "recipient_counts": database.count_active_sms_by_building(),
            "last_sync": database.get_last_sync(),
        }
    )
    return context


def preview_context(
    request: Request,
    *,
    preview: MessagePreview,
    building_id: str,
    alert_type: str,
    technical_cause: str,
    other_description: str,
    error: str | None = None,
) -> dict[str, object]:
    recipients = database.get_active_sms_recipients(building_id)
    context = common_context(request, active_page="alert")
    context.update(
        {
            "preview": preview,
            "building_id": building_id,
            "alert_type": alert_type,
            "technical_cause": technical_cause,
            "other_description": other_description,
            "recipients": recipients,
            "recipient_limit": settings.test_recipient_limit,
            "last_sync": database.get_last_sync(),
            "error": error,
            "can_simulate": (
                0 < len(recipients) <= settings.test_recipient_limit
                and not settings.sms_enabled
            ),
        }
    )
    return context


@app.get("/health")
def health_check() -> dict[str, object]:
    last_sync = database.get_last_sync()
    from gateway_config import load_gateway_config
    from gateway_store import GatewayStore
    gateway_config = load_gateway_config()
    gateway_enabled = bool(gateway_config and GatewayStore(database.path, gateway_config["allowed_numbers"])
                           .dashboard()["control"]["enabled"])
    return {
        "status": "ok",
        "mode": settings.app_mode,
        "sms_enabled": settings.sms_enabled,
        "gateway_test_sms_enabled": gateway_enabled,
        "version": "0.4.0",
        "database_ready": settings.database_path.exists(),
        "last_sync_status": last_sync["status"] if last_sync else None,
    }


@app.get("/", response_class=HTMLResponse)
def alert_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=form_context(request),
    )


@app.post("/preview", response_class=HTMLResponse)
def preview_alert(
    request: Request,
    building_id: Annotated[str, Form()],
    alert_type: Annotated[str, Form()],
    technical_cause: Annotated[str, Form()] = "",
    other_description: Annotated[str, Form()] = "",
) -> HTMLResponse:
    selected = {
        "building_id": building_id,
        "alert_type": alert_type,
        "technical_cause": technical_cause,
        "other_description": other_description,
    }

    try:
        preview = build_message(
            building_id=building_id,
            alert_type=alert_type,
            technical_cause=technical_cause,
            other_description=other_description,
        )
    except AlertValidationError as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=form_context(request, error=str(exc), selected=selected),
            status_code=400,
        )

    return templates.TemplateResponse(
        request=request,
        name="preview.html",
        context=preview_context(
            request,
            preview=preview,
            building_id=building_id,
            alert_type=alert_type,
            technical_cause=technical_cause,
            other_description=other_description,
        ),
    )


@app.post("/simulate", response_class=HTMLResponse)
def simulate_alert(
    request: Request,
    building_id: Annotated[str, Form()],
    alert_type: Annotated[str, Form()],
    technical_cause: Annotated[str, Form()] = "",
    other_description: Annotated[str, Form()] = "",
    confirm_simulation: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    try:
        preview = build_message(
            building_id=building_id,
            alert_type=alert_type,
            technical_cause=technical_cause,
            other_description=other_description,
        )
    except AlertValidationError as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=form_context(request, error=str(exc)),
            status_code=400,
        )

    error: str | None = None
    recipients = database.get_active_sms_recipients(building_id)

    if settings.sms_enabled:
        error = (
            "Bloqueo de seguridad: SMS_ENABLED debe permanecer en false "
            "durante esta etapa."
        )
    elif confirm_simulation != "yes":
        error = "Debe marcar la casilla de confirmación para registrar la simulación."
    elif not recipients:
        error = "No hay destinatarios activos con SMS habilitado para este edificio."
    elif len(recipients) > settings.test_recipient_limit:
        error = (
            f"Hay {len(recipients)} destinatarios, pero el límite de prueba es "
            f"{settings.test_recipient_limit}. La simulación fue bloqueada."
        )

    if error:
        return templates.TemplateResponse(
            request=request,
            name="preview.html",
            context=preview_context(
                request,
                preview=preview,
                building_id=building_id,
                alert_type=alert_type,
                technical_cause=technical_cause,
                other_description=other_description,
                error=error,
            ),
            status_code=400,
        )

    alert_id = database.create_simulation(
        building_id=building_id,
        alert_type=alert_type,
        technical_cause=technical_cause,
        other_description=other_description,
        preview=preview,
        recipients=recipients,
    )

    alert = database.get_alert(alert_id)
    deliveries = database.get_deliveries(alert_id)

    context = common_context(request, active_page="history")
    context.update(
        {
            "alert": alert,
            "deliveries": deliveries,
            "preview": preview,
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="simulation_result.html",
        context=context,
    )


@app.get("/recipients", response_class=HTMLResponse)
def recipients_page(request: Request) -> HTMLResponse:
    recipients = database.list_recipients()
    service_account_email = ""
    credentials_error = ""

    try:
        service_account_email = read_service_account_email(
            settings.service_account_file
        )
    except SheetsConfigurationError as exc:
        credentials_error = str(exc)

    context = common_context(request, active_page="recipients")
    context.update(
        {
            "recipients": recipients,
            "last_sync": database.get_last_sync(),
            "sheet_configured": bool(settings.spreadsheet_id),
            "sheet_range": settings.sheets_range,
            "credentials_ready": not credentials_error,
            "credentials_error": credentials_error,
            "service_account_email": service_account_email,
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="recipients.html",
        context=context,
    )


@app.post("/recipients/sync", response_class=HTMLResponse)
def sync_recipients(request: Request) -> HTMLResponse:
    fatal_error: str | None = None
    result = None
    summary = None

    try:
        values = read_sheet_values(settings)
        result = validate_sheet_values(values)
        summary = database.sync_recipients(result)
    except (
        SheetsConfigurationError,
        SheetsReadError,
        HeaderValidationError,
        SyncSafetyError,
    ) as exc:
        fatal_error = str(exc)
        database.record_failed_sync(fatal_error)

    context = common_context(request, active_page="recipients")
    context.update(
        {
            "fatal_error": fatal_error,
            "validation": result,
            "summary": summary,
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="sync_result.html",
        context=context,
        status_code=400 if fatal_error else 200,
    )


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request) -> HTMLResponse:
    context = common_context(request, active_page="history")
    context.update({"alerts": database.list_alerts()})
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context=context,
    )
