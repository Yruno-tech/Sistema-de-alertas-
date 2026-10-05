"""Local operator panel, separate from the phone's authenticated HTTPS API."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from gateway_config import load_gateway_config
from gateway_store import GatewayStore
from message_builder import ALERT_TYPES, BUILDINGS, TECHNICAL_CAUSES, build_message


def initialize_gateway(database):
    config = load_gateway_config()
    if config:
        GatewayStore(database.path, config["allowed_numbers"]).initialize()


def install_gateway(app, database, templates):
    router = APIRouter()

    @app.middleware("http")
    async def operator_boundary(request: Request, call_next):
        if (not request.client or request.client.host not in ("127.0.0.1", "::1") or
                request.url.hostname not in ("127.0.0.1", "localhost", "::1")):
            return PlainTextResponse("El panel se abre solamente en esta computadora.", status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if request.headers.get("origin") != origin:
                return PlainTextResponse("Origen del formulario inválido. Abrí el panel en localhost.", status_code=403)
        response = await call_next(request)
        response.headers.update({"X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "same-origin", "Cache-Control": "no-store"})
        return response

    def resources():
        config = load_gateway_config()
        if not config:
            raise HTTPException(503, "Primero ejecutá python configurar_gateway.py y reiniciá el servidor.")
        return config, GatewayStore(database.path, config["allowed_numbers"])

    def csrf(config, value):
        if not secrets.compare_digest(config["csrf"], value):
            raise HTTPException(403, "Formulario vencido: recargá la página.")

    def context(request, config, **extra):
        return {"request": request, "active_page": "gateway", "buildings": BUILDINGS,
                "alert_types": ALERT_TYPES, "technical_causes": TECHNICAL_CAUSES,
                "csrf": config["csrf"], "app_mode": "test", **extra}

    def failure(request, config, error):
        return templates.TemplateResponse(request=request, name="gateway_error.html",
                                          context=context(request, config, error=str(error)), status_code=400)

    @router.get("/gateway", response_class=HTMLResponse)
    def panel(request: Request, building: str = "edificio-anexo"):
        config, store = resources()
        if building not in BUILDINGS:
            return failure(request, config, "Edificio inválido")
        offices = sorted({r["office"] for r in database.list_recipients(building_id=building)
                          if r["office"]})
        return templates.TemplateResponse(request=request, name="gateway.html", context=context(
            request, config, selected_building=building, offices=offices,
            last_sync=database.get_last_sync(), **store.dashboard()))

    @router.get("/gateway/status")
    def status():
        _, store = resources()
        return store.dashboard()

    @router.post("/gateway/control")
    def control(csrf_token: str = Form(...), enabled: str = Form(...)):
        config, store = resources()
        csrf(config, csrf_token)
        if enabled not in ("yes", "no"):
            raise HTTPException(400, "Acción inválida")
        store.set_enabled(enabled == "yes")
        return RedirectResponse("/gateway", status_code=303)

    @router.post("/gateway/preview", response_class=HTMLResponse)
    def preview(request: Request, csrf_token: str = Form(...), building_id: str = Form(...),
                alert_type: str = Form(...), office: str = Form(""),
                technical_cause: str = Form(""), other_description: str = Form("")):
        config, store = resources()
        csrf(config, csrf_token)
        try:
            built = build_message(building_id=building_id, alert_type=alert_type,
                                  technical_cause=technical_cause, other_description=other_description)
            batch_id = store.preview(building_id, office or None, built.message)
        except ValueError as error:
            return failure(request, config, error)
        return templates.TemplateResponse(request=request, name="gateway_preview.html",
                                          context=context(request, config, batch=store.batch(batch_id)))

    @router.post("/gateway/batches/{batch_id}/confirm")
    def confirm(request: Request, batch_id: str, csrf_token: str = Form(...), confirmation: str = Form(...)):
        config, store = resources()
        csrf(config, csrf_token)
        try:
            if confirmation != "CONFIRMAR":
                raise ValueError("Escribí CONFIRMAR para autorizar los SMS de esta vista previa")
            store.confirm(batch_id)
        except ValueError as error:
            return failure(request, config, error)
        return RedirectResponse("/gateway#batches", status_code=303)

    @router.post("/gateway/batches/{batch_id}/stop")
    def stop(batch_id: str, csrf_token: str = Form(...)):
        config, store = resources()
        csrf(config, csrf_token)
        store.stop(batch_id)
        return RedirectResponse("/gateway#batches", status_code=303)

    app.include_router(router)
