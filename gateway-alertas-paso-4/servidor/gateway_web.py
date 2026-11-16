from __future__ import annotations

import asyncio
import base64
import io
import json
import secrets
from pathlib import Path

import qrcode
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from config import save_sheets_configuration, settings
from gateway_config import load_gateway_config
from gateway_pairing import PairingService
from gateway_store import GatewayStore, QueueError
from operator_accounts import AccountError, OperatorAccounts
from service_account_upload import CredentialUploadError, save_service_account_json
from sheets_service import SheetsConfigurationError, read_service_account_email
from sync_service import synchronize
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


def install_gateway(app, database, templates, service_account_file=None):
    router = APIRouter()
    accounts = OperatorAccounts(database.path)
    credentials_path = Path(service_account_file or settings.service_account_file)
    accounts.initialize()

    @app.middleware('http')
    async def operator_boundary(request: Request, call_next):
        if (not request.client or request.client.host not in ('127.0.0.1','::1') or
                request.url.hostname not in ('127.0.0.1','localhost','::1')):
            return PlainTextResponse('El panel se abre en esta computadora.',status_code=403)
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.headers.get('origin') != f"{request.url.scheme}://{request.headers.get('host','')}":
                return PlainTextResponse('Origen del formulario inválido.',status_code=403)
        path = request.url.path
        is_public_page = path in ('/setup', '/login', '/health') or path.startswith('/static/')
        if not is_public_page:
            if not accounts.has_users():
                if path.startswith('/gateway/'):
                    return JSONResponse({'detail':'Creá la cuenta administradora para continuar.'},
                                        status_code=401)
                return RedirectResponse('/setup', status_code=303)
            operator = accounts.get_session(request.cookies.get('operator_session'))
            if not operator:
                if path.startswith('/gateway/'):
                    return JSONResponse({'detail':'La sesión venció. Iniciá sesión nuevamente.'},
                                        status_code=401)
                return RedirectResponse('/login', status_code=303)
            request.state.operator = operator
        response = await call_next(request)
        response.headers.update({'X-Frame-Options':'DENY','X-Content-Type-Options':'nosniff',
                                 'Referrer-Policy':'same-origin','Cache-Control':'no-store'})
        return response

    def resources():
        config = load_gateway_config()
        if not config:
            raise HTTPException(503,'Iniciá el programa con python iniciar_gateway.py')
        return config, GatewayStore(database.path)

    def csrf(request, value):
        operator = getattr(request.state, 'operator', None)
        if not operator or not secrets.compare_digest(operator['csrf_token'], value):
            raise HTTPException(403,'Recargá la página para actualizar el formulario')

    def readiness(store, request=None):
        dashboard = store.dashboard()
        last_sync = database.get_last_sync()
        checks = []

        try:
            read_service_account_email(credentials_path)
            checks.append({
                'id': 'credentials', 'label': 'Credencial de Google',
                'ok': True, 'detail': 'Archivo de cuenta de servicio encontrado y válido.',
            })
        except SheetsConfigurationError as error:
            credential_check = {
                'id': 'credentials', 'label': 'Credencial de Google',
                'ok': False, 'detail': str(error),
            }
            if request and request.state.operator['role'] == 'admin':
                credential_check['action'] = {
                    'label': 'Configurar credencial', 'href': '/settings',
                }
            else:
                credential_check['detail'] += ' Pedí a la administradora que la configure.'
            checks.append(credential_check)

        current_settings = settings.snapshot()
        sheet_ok = bool(
            current_settings.spreadsheet_id and current_settings.sheets_range
        )
        checks.append({
            'id': 'spreadsheet', 'label': 'Planilla configurada',
            'ok': sheet_ok,
            'detail': (
                f'ID y rango configurados ({current_settings.sheets_range}).'
                if sheet_ok else
                'Falta configurar el ID o el rango de Google Sheets.'
            ),
            **({} if sheet_ok else {
                'action': {'label': 'Abrir configuración', 'href': '/settings'},
            }),
        })

        sync_ok = bool(last_sync and last_sync['status'] in ('success', 'success_with_errors'))
        if sync_ok:
            sync_detail = (
                f"Sincronización válida: {last_sync['accepted']} registros."
                + (f" {last_sync['rejected']} filas excluidas." if last_sync['rejected'] else '')
            )
        elif last_sync and last_sync.get('error_message'):
            sync_detail = f"Último error: {last_sync['error_message']}"
        else:
            sync_detail = 'Todavía no hay una sincronización correcta con Google Sheets.'
        checks.append({
            'id': 'sync', 'label': 'Acceso y sincronización de Google Sheets',
            'ok': sync_ok, 'detail': sync_detail,
            **({} if sync_ok else {
                'action': {'label': 'Configurar o sincronizar planilla', 'href': '/settings'},
            }),
        })

        phone_ok = bool(dashboard['control']['connected'])
        checks.append({
            'id': 'phone', 'label': 'Celular gateway conectado',
            'ok': phone_ok,
            'detail': (
                'El celular está activo y responde al servidor.'
                if phone_ok else
                'Abrí la app Android, conectala por QR si hace falta y pulsá Activar gateway.'
            ),
            **({} if phone_ok else {
                'action': {'label': 'Conectar celular (QR)', 'href': '#pair-button'},
            }),
        })
        return {'ready': all(check['ok'] for check in checks), 'checks': checks}

    def account_context(request, *, error=None):
        return {
            'request': request,
            'active_page': 'accounts',
            'error': error,
            'users': accounts.list_users(),
            'operator': getattr(request.state, 'operator', None),
        }

    def configuration_context(
        request,
        *,
        error=None,
        saved=False,
        sync_error=None,
        sync_summary=None,
        credential_error=None,
        credential_success=None,
        spreadsheet_id=None,
        sheets_range=None,
    ):
        current_settings = settings.snapshot()
        service_account_email = ''
        credential_status = ''
        try:
            service_account_email = read_service_account_email(credentials_path)
        except SheetsConfigurationError as credential_exception:
            credential_status = str(credential_exception)
        return {
            'request': request,
            'active_page': 'settings',
            'operator': getattr(request.state, 'operator', None),
            'csrf': request.state.operator['csrf_token'],
            'spreadsheet_id': (
                current_settings.spreadsheet_id
                if spreadsheet_id is None else spreadsheet_id
            ),
            'sheets_range': (
                current_settings.sheets_range
                if sheets_range is None else sheets_range
            ),
            'service_account_email': service_account_email,
            'credential_status': credential_status,
            'credential_file_exists': credentials_path.is_file(),
            'error': error,
            'saved': saved,
            'sync_error': sync_error,
            'sync_summary': sync_summary,
            'credential_error': credential_error,
            'credential_success': credential_success,
            'last_sync': database.get_last_sync(),
        }

    @router.get('/setup', response_class=HTMLResponse)
    def setup_page(request: Request):
        if accounts.get_session(request.cookies.get('operator_session')):
            return RedirectResponse('/gateway', status_code=303)
        if accounts.has_users():
            return RedirectResponse('/login', status_code=303)
        return templates.TemplateResponse(
            request=request, name='account_setup.html',
            context={'request': request, 'error': None},
        )

    @router.post('/setup')
    def setup_account(request: Request, username: str=Form(...), display_name: str=Form(...),
                      password: str=Form(...), password_confirm: str=Form(...)):
        if accounts.has_users():
            return RedirectResponse('/login', status_code=303)
        if password != password_confirm:
            return templates.TemplateResponse(
                request=request, name='account_setup.html',
                context={'request': request, 'error': 'Las contraseñas no coinciden.'},
                status_code=400,
            )
        try:
            user_id = accounts.create_initial_admin(username, display_name, password)
        except AccountError as error:
            return templates.TemplateResponse(
                request=request, name='account_setup.html',
                context={'request': request, 'error': str(error)}, status_code=400,
            )
        return _create_login_response(accounts, user_id)

    @router.get('/login', response_class=HTMLResponse)
    def login_page(request: Request):
        if accounts.get_session(request.cookies.get('operator_session')):
            return RedirectResponse('/gateway', status_code=303)
        if not accounts.has_users():
            return RedirectResponse('/setup', status_code=303)
        return templates.TemplateResponse(
            request=request, name='account_login.html',
            context={'request': request, 'error': None},
        )

    @router.post('/login')
    def login(request: Request, username: str=Form(...), password: str=Form(...)):
        if not accounts.has_users():
            return RedirectResponse('/setup', status_code=303)
        user = accounts.authenticate(username, password)
        if not user:
            return templates.TemplateResponse(
                request=request, name='account_login.html',
                context={'request': request, 'error': 'Usuario o contraseña incorrectos.'},
                status_code=401,
            )
        return _create_login_response(accounts, user['id'])

    @router.post('/logout')
    def logout(request: Request, csrf_token: str=Form(...)):
        csrf(request, csrf_token)
        token = request.cookies.get('operator_session')
        accounts.revoke_session(token)
        response = RedirectResponse('/login', status_code=303)
        response.delete_cookie('operator_session', path='/', httponly=True, samesite='strict')
        return response

    @router.get('/accounts', response_class=HTMLResponse)
    def account_list(request: Request):
        if request.state.operator['role'] != 'admin':
            raise HTTPException(403, 'Solo la cuenta administradora puede crear usuarios.')
        return templates.TemplateResponse(
            request=request, name='accounts.html', context=account_context(request),
        )

    @router.get('/settings', response_class=HTMLResponse)
    def settings_page(request: Request):
        if request.state.operator['role'] != 'admin':
            raise HTTPException(403, 'Solo la cuenta administradora puede configurar Google Sheets.')
        return templates.TemplateResponse(
            request=request,
            name='settings.html',
            context=configuration_context(request),
        )

    @router.post('/settings', response_class=HTMLResponse)
    def save_settings(
        request: Request,
        csrf_token: str=Form(...),
        spreadsheet_id: str=Form(..., max_length=512),
        sheets_range: str=Form(..., max_length=256),
    ):
        if request.state.operator['role'] != 'admin':
            raise HTTPException(403, 'Solo la cuenta administradora puede configurar Google Sheets.')
        csrf(request, csrf_token)
        try:
            current_settings = save_sheets_configuration(
                spreadsheet_id, sheets_range
            )
        except (OSError, ValueError) as error:
            return templates.TemplateResponse(
                request=request,
                name='settings.html',
                context=configuration_context(
                    request,
                    error=str(error),
                    spreadsheet_id=spreadsheet_id,
                    sheets_range=sheets_range,
                ),
                status_code=400,
            )

        _, summary, sync_error = synchronize(database, current_settings)
        return templates.TemplateResponse(
            request=request,
            name='settings.html',
            context=configuration_context(
                request,
                saved=True,
                sync_error=sync_error,
                sync_summary=summary,
            ),
        )

    @router.post('/accounts')
    def create_account(request: Request, csrf_token: str=Form(...),
                       username: str=Form(...), display_name: str=Form(...),
                       password: str=Form(...), password_confirm: str=Form(...)):
        if request.state.operator['role'] != 'admin':
            raise HTTPException(403, 'Solo la cuenta administradora puede crear usuarios.')
        csrf(request, csrf_token)
        if password != password_confirm:
            return templates.TemplateResponse(
                request=request, name='accounts.html',
                context=account_context(request, error='Las contraseñas no coinciden.'),
                status_code=400,
            )
        try:
            accounts.create_operator(username, display_name, password)
        except AccountError as error:
            return templates.TemplateResponse(
                request=request, name='accounts.html',
                context=account_context(request, error=str(error)), status_code=400,
            )
        return RedirectResponse('/accounts?created=1', status_code=303)

    @router.post('/settings/service-account', response_class=HTMLResponse)
    async def upload_service_account(
        request: Request,
        csrf_token: str=Form(...),
        credential_file: UploadFile=File(...),
    ):
        if request.state.operator['role'] != 'admin':
            raise HTTPException(403, 'Solo la cuenta administradora puede configurar credenciales.')
        csrf(request, csrf_token)
        contents = await credential_file.read(1024 * 1024 + 1)
        await credential_file.close()
        try:
            email = save_service_account_json(contents, credentials_path)
        except CredentialUploadError as error:
            return templates.TemplateResponse(
                request=request,
                name='settings.html',
                context=configuration_context(request, credential_error=str(error)),
                status_code=400,
            )
        _, summary, sync_error = await asyncio.to_thread(
            synchronize, database, settings.snapshot()
        )
        return templates.TemplateResponse(
            request=request,
            name='settings.html',
            context=configuration_context(
                request,
                sync_error=sync_error,
                sync_summary=summary,
                credential_success=(
                    f'Credencial de {email} importada. Se intentó sincronizar Google Sheets.'
                ),
            ),
        )

    @router.get('/gateway', response_class=HTMLResponse)
    def panel(request: Request):
        config, store = resources()
        return templates.TemplateResponse(request=request,name='gateway.html',context={
            'request':request,'active_page':'gateway','buildings':BUILDINGS,'alert_types':ALERT_TYPES,
            'technical_causes':TECHNICAL_CAUSES,'csrf':request.state.operator['csrf_token'],
            'operator':request.state.operator,**store.dashboard()})

    @router.get('/gateway/status')
    def status(request: Request):
        _, store = resources()
        data = store.dashboard()
        data['last_sync'] = database.get_last_sync()
        data['readiness'] = readiness(store, request)
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
    def send(request: Request, csrf_token: str=Form(...),request_id: str=Form(...),
             snapshot: str=Form(...),building_id: str=Form(...),alert_type: str=Form(...),office: str=Form(''),
             technical_cause: str=Form(''),other_description: str=Form(''),
             controlled_reason: str=Form('')):
        config, store = resources()
        csrf(request,csrf_token)
        current_readiness = readiness(store, request)
        if not current_readiness['ready']:
            first_problem = next(check for check in current_readiness['checks'] if not check['ok'])
            return JSONResponse(
                {'detail': f"No se puede enviar todavía. {first_problem['label']}: {first_problem['detail']}"},
                status_code=409,
            )
        try:
            message = build_message(
                building_id, alert_type, technical_cause, other_description, controlled_reason
            ).message
            operator = request.state.operator
            batch = store.enqueue(
                building_id,office or None,message,request_id,snapshot,
                actor_user_id=operator['id'], actor_username=operator['username'],
                actor_name=operator['display_name'],
            )
            return {'batch_id':batch}
        except ValueError as error:
            return JSONResponse({'detail':str(error)},status_code=409)

    @router.post('/gateway/pairing')
    def pairing(request: Request, csrf_token: str=Form(...)):
        config, _ = resources()
        csrf(request,csrf_token)
        service = PairingService(database.path,config)
        payload = service.issue()
        image = qrcode.make(json.dumps(payload,separators=(',',':')),box_size=7,border=4)
        buffer = io.BytesIO()
        image.save(buffer,format='PNG')
        return {'qr_png':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),
                'expires_at':payload['expiresAt'],'url':payload['url']}

    @router.post('/gateway/control')
    def control(request: Request, csrf_token: str=Form(...),enabled: str=Form(...)):
        config, store = resources(); csrf(request,csrf_token)
        if enabled not in ('yes','no'): raise HTTPException(400,'Acción inválida')
        operator=request.state.operator
        store.set_enabled(enabled=='yes',actor_user_id=operator['id'],actor_username=operator['username'])
        return RedirectResponse('/gateway#batches',status_code=303)

    @router.post('/gateway/interval')
    def interval(request: Request, csrf_token: str=Form(...),seconds: int=Form(...)):
        config, store = resources(); csrf(request,csrf_token)
        operator=request.state.operator
        try:
            store.set_interval(seconds,actor_user_id=operator['id'],actor_username=operator['username'])
        except QueueError as error: raise HTTPException(400,str(error))
        return RedirectResponse('/gateway',status_code=303)

    @router.post('/gateway/batches/{batch_id}/stop')
    def stop(request: Request, batch_id: str,csrf_token: str=Form(...)):
        config, store = resources(); csrf(request,csrf_token)
        operator=request.state.operator
        store.stop(batch_id,actor_user_id=operator['id'],actor_username=operator['username'])
        return RedirectResponse('/gateway#batches',status_code=303)

    app.include_router(router)


def _create_login_response(accounts, user_id):
    token, _ = accounts.create_session(user_id)
    response = RedirectResponse('/gateway', status_code=303)
    response.set_cookie(
        'operator_session', token, max_age=12 * 60 * 60, httponly=True,
        samesite='strict', secure=False, path='/',
    )
    return response
