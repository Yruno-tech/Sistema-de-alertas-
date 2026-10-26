import hashlib
import json
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from pathlib import Path

from configurar_gateway import create_configuration
from database import Database
from gateway_api import create_api
from gateway_pairing import PairingService
from gateway_store import GatewayStore, QueueError
from gateway_web import install_gateway
from recipient_validation import validate_sheet_values

HEADERS = ['id', 'nombre', 'telefono', 'correo', 'edificio', 'activo', 'sms', 'correo_habilitado', 'oficina']
NUMBERS = ['+5493764000001', '+5493764000002', '+5493764000003']
MESSAGE = 'PRUEBA - Sistema de alertas institucional. No corresponde a una emergencia.'
DEVICE = str(uuid.uuid4())
BASE = Path(__file__).resolve().parents[1]


def sheet():
    return [HEADERS] + [[str(i+1), f'Persona {i+1}', n, '', 'Anexo', 'SI', 'SI', 'NO',
                        'Mesa de entradas' if i < 2 else 'Informática'] for i, n in enumerate(NUMBERS)]


@pytest.fixture
def setup(tmp_path):
    db = Database(tmp_path / 'alerts.db')
    db.initialize()
    db.sync_recipients(validate_sheet_values(sheet()))
    clock = [time.time()]
    store = GatewayStore(db.path, NUMBERS, clock=lambda: clock[0])
    store.initialize()
    store.heartbeat(DEVICE, True, 'SIM 1')
    store.set_enabled(True)
    return db, store, clock


def queued(store, office=None):
    batch = store.preview('edificio-anexo', office, MESSAGE)
    store.confirm(batch)
    return batch


def test_office_migration_preserves_existing_data_and_filters(setup):
    db, store, _ = setup
    with db.connect() as connection:
        connection.execute('ALTER TABLE recipients DROP COLUMN office')
    db.initialize()
    assert len(db.list_recipients()) == 3
    assert all(r['office'] == '' for r in db.list_recipients())
    db.sync_recipients(validate_sheet_values(sheet()))
    batch = queued(store, 'Informática')
    assert len(store.batch(batch)['jobs']) == 1
    assert store.batch(batch)['jobs'][0]['phone_masked'].endswith('0003')


def test_same_confirm_and_concurrent_claims_never_duplicate(setup):
    _, store, _ = setup
    batch = queued(store)
    store.confirm(batch)
    with ThreadPoolExecutor(max_workers=5) as workers:
        responses = list(workers.map(lambda _: store.next_job(DEVICE), range(5)))
    assert len({r['id'] for r in responses}) == 1
    assert len({r['ticket'] for r in responses}) == 1
    assert len(store.batch(batch)['jobs']) == 3


def test_full_three_recipient_flow_and_late_delivery(setup):
    _, store, clock = setup
    batch = queued(store)
    ids = []
    for _ in range(3):
        job = store.next_job(DEVICE)
        ids.append(job['id'])
        assert store.start(DEVICE, job['id'], job['ticket'])['allowed']
        assert store.start(DEVICE, job['id'], job['ticket'])['allowed']  # Lost start response.
        assert store.next_job(DEVICE) is None
        store.report(DEVICE, job['id'], job['ticket'], 2, 'SENT', 'WAITING', 'Enviado')
        assert store.report(DEVICE, job['id'], job['ticket'], 2, 'SENT', 'WAITING', 'Enviado') == {'ack': 2}
        assert store.next_job(DEVICE) is None  # Spacing is enforced.
        clock[0] += 31
    assert len(set(ids)) == 3
    assert store.next_job(DEVICE) is None
    assert store.batch(batch)['counts']['SENT'] == 3
    store.report(DEVICE, job['id'], job['ticket'], 3, 'SENT', 'DELIVERED', 'Entregado')
    store.report(DEVICE, job['id'], job['ticket'], 1, 'UNKNOWN', 'WAITING', 'Viejo')
    assert store.batch(batch)['counts']['DELIVERED'] == 1


@pytest.mark.parametrize('started', [False, True])
def test_stop_cancels_pending_but_accepts_result_for_started(setup, started):
    _, store, _ = setup
    batch = queued(store)
    job = store.next_job(DEVICE)
    if started:
        store.start(DEVICE, job['id'], job['ticket'])
    store.stop(batch)
    assert not store.start(DEVICE, job['id'], job['ticket'])['allowed']
    assert store.next_job(DEVICE) is None
    if started:
        store.report(DEVICE, job['id'], job['ticket'], 1, 'SENT', 'WAITING', 'Enviado')
        assert store.batch(batch)['counts']['SENT'] == 1
        assert store.batch(batch)['counts']['CANCELLED'] == 2
    else:
        assert store.batch(batch)['counts']['CANCELLED'] == 3


def test_unknown_pauses_persistently_without_requeue_on_restart(setup):
    db, store, clock = setup
    batch = queued(store)
    job = store.next_job(DEVICE)
    store.start(DEVICE, job['id'], job['ticket'])
    clock[0] += 121
    recovered = GatewayStore(db.path, NUMBERS, clock=lambda: clock[0])
    recovered.initialize()
    assert recovered.next_job(DEVICE) is None
    assert recovered.batch(batch)['counts']['UNKNOWN'] == 1
    assert not recovered.dashboard()['control']['enabled']
    recovered.set_enabled(True)
    other = recovered.next_job(DEVICE)
    assert other['id'] != job['id']
    assert not recovered.start(DEVICE, job['id'], job['ticket'])['allowed']


def test_failed_report_pauses_and_keeps_next_pending(setup):
    _, store, clock = setup
    batch = queued(store)
    job = store.next_job(DEVICE)
    store.start(DEVICE, job['id'], job['ticket'])
    store.report(DEVICE, job['id'], job['ticket'], 1, 'FAILED', 'WAITING', 'Sin servicio')
    clock[0] += 31
    assert store.next_job(DEVICE) is None
    assert store.batch(batch)['counts']['QUEUED'] == 2


def test_expired_claim_and_batch_never_resend(setup):
    _, store, clock = setup
    batch = queued(store)
    job = store.next_job(DEVICE)
    clock[0] += 61
    assert not store.start(DEVICE, job['id'], job['ticket'])['allowed']
    assert store.batch(batch)['counts']['CANCELLED'] == 1
    clock[0] += 600
    assert store.next_job(DEVICE) is None
    assert store.batch(batch)['counts']['CANCELLED'] == 3


def test_changed_sync_or_recipient_invalidates_confirmation_and_start(setup):
    db, store, _ = setup
    batch = store.preview('edificio-anexo', None, MESSAGE)
    db.sync_recipients(validate_sheet_values(sheet()))
    with pytest.raises(QueueError, match='sincronización cambió'):
        store.confirm(batch)
    queued(store)
    job = store.next_job(DEVICE)
    with db.connect() as connection:
        connection.execute('UPDATE recipients SET office=? WHERE phone=?', ('Mudanza', job['phone']))
    assert store.start(DEVICE, job['id'], job['ticket']) == {'allowed': False, 'status': 'CANCELLED'}


def test_bad_sheet_rows_are_excluded_without_blocking_valid_people(setup):
    db, store, _ = setup
    rows = sheet()
    rows[1][5] = 'QUIZAS'
    summary = db.sync_recipients(validate_sheet_values(rows))
    assert summary.status == 'success_with_errors'
    first = next(r for r in db.list_recipients() if r['phone'] == NUMBERS[0])
    assert not first['active'] and not first['sms_enabled']
    batch=store.preview('edificio-anexo', None, MESSAGE)
    assert len(store.batch(batch)['jobs']) == 2


def test_failed_sync_preserves_data_but_blocks_new_test(setup):
    db, store, _ = setup
    db.record_failed_sync('Sin conexión con Google')
    assert len(db.list_recipients()) == 3
    with pytest.raises(QueueError): store.preview('edificio-anexo', None, MESSAGE)


def test_new_fourth_person_is_included_without_changing_phone_configuration(setup):
    db, store, _ = setup
    with pytest.raises(QueueError): store.preview('edificio-anexo', None, 'ALERTA REAL')
    with pytest.raises(QueueError): store.preview('edificio-anexo', None, 'PRUEBA - ' + 'A' * 161)
    with pytest.raises(QueueError): store.heartbeat(str(uuid.uuid4()), True, 'Otro teléfono')
    rows = sheet() + [['4', 'Cuarto', '+5493764000004', '', 'Anexo', 'SI', 'SI', 'NO', 'Informática']]
    db.sync_recipients(validate_sheet_values(rows))
    batch = store.preview('edificio-anexo', None, MESSAGE)
    assert len(store.batch(batch)['jobs']) == 4


def test_api_requires_https_qr_credential_device_and_ticket(setup, tmp_path):
    _, store, _ = setup
    config=create_configuration('192.168.1.5',base=tmp_path)
    api = create_api(config, store)
    headers = {'X-Gateway-Device': DEVICE}
    with TestClient(api, base_url='https://192.168.1.5:8443') as client:
        assert client.post('/api/gateway/jobs/next',headers=headers).status_code == 401
        service=PairingService(store.path,config)
        qr=service.issue()
        response=client.post('/api/gateway/pair',headers=headers,json={'id':qr['id'],'secret':qr['secret']})
        assert response.status_code == 200
        headers['Authorization']='Bearer '+response.json()['token']
        assert client.post('/api/gateway/heartbeat', headers=headers, json={'active': True,'protocol_version':2}).status_code == 200
        store.set_enabled(True)
        assert client.get('/recipients', headers=headers).status_code == 404
        queued(store)
        job = client.post('/api/gateway/jobs/next', headers=headers).json()['job']
        bad = client.post(f"/api/gateway/jobs/{job['id']}/start", headers=headers, json={'ticket': str(uuid.uuid4())})
        assert bad.status_code == 409
        assert client.post(f"/api/gateway/jobs/{job['id']}/start", headers=headers, json={'ticket': job['ticket']}).json()['allowed']
        with sqlite3.connect(store.path) as connection:
            connection.execute('UPDATE gateway_credentials SET expires_at=0')
        assert client.post('/api/gateway/jobs/next', headers=headers).status_code == 401
    with TestClient(api, base_url='http://192.168.1.5:8443') as client:
        assert client.post('/api/gateway/jobs/next', headers=headers).status_code == 403


def test_local_panel_preview_confirm_tracking_and_csrf(setup, tmp_path, monkeypatch):
    db, store, _ = setup
    configfile = tmp_path / 'gateway-config.json'
    configfile.write_text(json.dumps({'version': 2, 'mode': 'test', 'csrf': 'csrf-test'}))
    monkeypatch.setenv('GATEWAY_CONFIG_FILE', str(configfile))
    app = FastAPI()
    app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')
    install_gateway(app, db, Jinja2Templates(directory=BASE / 'templates'))
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 45000)) as client:
        html=client.get('/gateway').text
        assert 'Enviar ahora' in html and 'CONFIRMAR' not in html
        form = {'csrf_token': 'csrf-test', 'building_id': 'edificio-anexo', 'alert_type': 'maintenance', 'office': 'Informática'}
        assert client.post('/gateway/send', data=form).status_code == 403
        response = client.get('/gateway/quote', params={k:v for k,v in form.items() if k!='csrf_token'})
        assert response.status_code == 200
        assert response.json()['count'] == 1
        assert 'Persona 3' in response.text and 'Persona 1' not in response.text
        batch=str(uuid.uuid4())
        form.update(request_id=batch,snapshot=response.json()['snapshot'])
        response = client.post('/gateway/send',data=form,
                               headers={'Origin': 'http://127.0.0.1:8000'})
        assert response.status_code == 200
        assert client.post('/gateway/send',data=form,headers={'Origin':'http://127.0.0.1:8000'}).json()['batch_id'] == batch
        assert client.get('/gateway/status').json()['batches'][0]['counts']['QUEUED'] == 1
    with TestClient(app, base_url='http://evil.example', client=('127.0.0.1', 45000)) as client:
        assert client.get('/gateway').status_code == 403
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('192.168.1.8', 45000)) as client:
        assert client.get('/gateway').status_code == 403


def test_gateway_controlled_alert_requires_reason_and_limits_sms(setup, tmp_path, monkeypatch):
    db, _store, _ = setup
    configfile = tmp_path / 'gateway-config.json'
    configfile.write_text(json.dumps({'version': 2, 'mode': 'test', 'csrf': 'csrf-test'}))
    monkeypatch.setenv('GATEWAY_CONFIG_FILE', str(configfile))
    app = FastAPI()
    app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')
    install_gateway(app, db, Jinja2Templates(directory=BASE / 'templates'))

    with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 45000)) as client:
        html = client.get('/gateway').text
        assert 'Alarma de Situación Controlada' in html
        assert 'Motivo por el que se da por finalizada la alerta' in html

        limit = client.get('/gateway/reason-limit', params={'building_id': 'edificio-anexo'})
        assert limit.status_code == 200
        max_chars = limit.json()['max_chars']
        assert client.get(
            '/gateway/reason-limit', params={'building_id': 'invalid'}
        ).status_code == 400

        values = {
            'building_id': 'edificio-anexo',
            'alert_type': 'controlled',
            'office': '',
        }
        assert client.get('/gateway/quote', params=values).status_code == 400

        values['controlled_reason'] = 'Falsa alarma por sensor de humo activado en cocina.'
        quote = client.get('/gateway/quote', params=values)
        assert quote.status_code == 200
        assert quote.json()['message'] == (
            'PRUEBA - AVISO: Situacion controlada en Edificio Anexo. Motivo: '
            'Falsa alarma por sensor de humo activado en cocina. '
            'Puede retornar a sus actividades.'
        )
        assert len(quote.json()['message']) <= 160

        form = {
            **values,
            'csrf_token': 'csrf-test',
            'request_id': str(uuid.uuid4()),
            'snapshot': quote.json()['snapshot'],
        }
        response = client.post(
            '/gateway/send',
            data={key: value for key, value in form.items() if key != 'controlled_reason'},
            headers={'Origin': 'http://127.0.0.1:8000'},
        )
        assert response.status_code == 409

        form['request_id'] = str(uuid.uuid4())
        response = client.post(
            '/gateway/send', data=form, headers={'Origin': 'http://127.0.0.1:8000'}
        )
        assert response.status_code == 200
        batch = _store.batch(response.json()['batch_id'])
        assert batch['message'] == quote.json()['message']

        values['controlled_reason'] = 'x' * (max_chars + 1)
        assert client.get('/gateway/quote', params=values).status_code == 400


def test_pairing_generates_trusted_certificate_without_google_access(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    config = create_configuration('192.168.1.5',base=tmp_path)
    assert 'token' not in config
    cert = x509.load_pem_x509_certificate(Path(config['certificate_file']).read_bytes())
    assert str(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)[0]) == '192.168.1.5'
    key = serialization.load_pem_private_key((tmp_path / 'credentials/gateway-server.key').read_bytes(), password=None)
    assert key.public_key().public_numbers() == cert.public_key().public_numbers()
    assert create_configuration('192.168.1.5',base=tmp_path)['server_id']==config['server_id']
    assert not (tmp_path/'emparejar-gateway.json').exists()
    with pytest.raises(ValueError): create_configuration('8.8.8.8', NUMBERS, tmp_path / 'public')
