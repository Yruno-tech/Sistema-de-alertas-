from __future__ import annotations

import base64
import io
import json
import secrets

import qrcode
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from gateway_config import load_gateway_config
from gateway_pairing import PairingService
from gateway_store import GatewayStore, QueueError
from message_builder import (
    ALERT_TYPES,
    BUILDINGS,
    TECHNICAL_CAUSES,
    build_message,
    controlled_reason_limit,
)


def initialize_gateway(database):
    config = load_gateway_config()
    if config:
        GatewayStore(database.path).initialize()
        PairingService(database.path,config).initialize()


def install_gateway(app, database, templates):
    router = APIRouter()

    @app.middleware('http')
    async def operator_boundary(request: Request, call_next):
        if (not request.client or request.client.host not in ('127.0.0.1','::1') or
                request.url.hostname not in ('127.0.0.1','localhost','::1')):
            return PlainTextResponse('El panel se abre en esta computadora.',status_code=403)
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.headers.get('origin') != f"{request.url.scheme}://{request.headers.get('host','')}":
                return PlainTextResponse('Origen del formulario inválido.',status_code=403)
        response = await call_next(request)
        response.headers.update({'X-Frame-Options':'DENY','X-Content-Type-Options':'nosniff',
                                 'Referrer-Policy':'same-origin','Cache-Control':'no-store'})
        return response

    def resources():
        config = load_gateway_config()
        if not config:
            raise HTTPException(503,'Iniciá el programa con python iniciar_gateway.py')
        return config, GatewayStore(database.path)

    def csrf(config, value):
        if not secrets.compare_digest(config['csrf'],value):
            raise HTTPException(403,'Recargá la página para actualizar el formulario')

    @router.get('/gateway', response_class=HTMLResponse)
    def panel(request: Request):
        config, store = resources()
        return templates.TemplateResponse(request=request,name='gateway.html',context={
            'request':request,'active_page':'gateway','buildings':BUILDINGS,'alert_types':ALERT_TYPES,
            'technical_causes':TECHNICAL_CAUSES,'csrf':config['csrf'],**store.dashboard()})

    @router.get('/gateway/status')
    def status():
        _, store = resources()
        data = store.dashboard()
        data['last_sync'] = database.get_last_sync()
        return data

    @router.get('/gateway/reason-limit')
    def reason_limit(building_id: str):
        try:
            return {'max_chars': controlled_reason_limit(building_id)}
        except ValueError as error:
            return JSONResponse({'detail':str(error)},status_code=400)

    @router.get('/gateway/quote')
    def quote(building_id: str, alert_type: str, office: str='',technical_cause: str='',
              other_description: str='',controlled_reason: str=''):
        _, store = resources()
        try:
            message = build_message(
                building_id, alert_type, technical_cause, other_description, controlled_reason
            ).message
            data = store.quote(building_id,office or None,message)
            data['offices'] = sorted({r['office'] for r in database.list_recipients(building_id=building_id) if r['office']})
            return data
        except ValueError as error:
            return JSONResponse({'detail':str(error)},status_code=400)

    @router.post('/gateway/send')
    def send(csrf_token: str=Form(...),request_id: str=Form(...),snapshot: str=Form(...),
             building_id: str=Form(...),alert_type: str=Form(...),office: str=Form(''),
             technical_cause: str=Form(''),other_description: str=Form(''),
             controlled_reason: str=Form('')):
        config, store = resources()
        csrf(config,csrf_token)
        try:
            message = build_message(
                building_id, alert_type, technical_cause, other_description, controlled_reason
            ).message
            batch = store.enqueue(building_id,office or None,message,request_id,snapshot)
            return {'batch_id':batch}
        except ValueError as error:
            return JSONResponse({'detail':str(error)},status_code=409)

    @router.post('/gateway/pairing')
    def pairing(csrf_token: str=Form(...)):
        config, _ = resources()
        csrf(config,csrf_token)
        service = PairingService(database.path,config)
        payload = service.issue()
        image = qrcode.make(json.dumps(payload,separators=(',',':')),box_size=7,border=4)
        buffer = io.BytesIO()
        image.save(buffer,format='PNG')
        return {'qr_png':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),
                'expires_at':payload['expiresAt'],'url':payload['url']}

    @router.post('/gateway/control')
    def control(csrf_token: str=Form(...),enabled: str=Form(...)):
        config, store = resources(); csrf(config,csrf_token)
        if enabled not in ('yes','no'): raise HTTPException(400,'Acción inválida')
        store.set_enabled(enabled=='yes')
        return RedirectResponse('/gateway#batches',status_code=303)

    @router.post('/gateway/interval')
    def interval(csrf_token: str=Form(...),seconds: int=Form(...)):
        config, store = resources(); csrf(config,csrf_token)
        try: store.set_interval(seconds)
        except QueueError as error: raise HTTPException(400,str(error))
        return RedirectResponse('/gateway',status_code=303)

    @router.post('/gateway/batches/{batch_id}/stop')
    def stop(batch_id: str,csrf_token: str=Form(...)):
        config, store = resources(); csrf(config,csrf_token)
        store.stop(batch_id)
        return RedirectResponse('/gateway#batches',status_code=303)

    app.include_router(router)
