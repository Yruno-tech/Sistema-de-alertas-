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


def test_bad_sheet_rows_are_disabled_and_block_real_queue(setup):
    db, store, _ = setup
    rows = sheet()
    rows[1][5] = 'QUIZAS'
    summary = db.sync_recipients(validate_sheet_values(rows))
    assert summary.status == 'success_with_errors'
    first = next(r for r in db.list_recipients() if r['phone'] == NUMBERS[0])
    assert not first['active'] and not first['sms_enabled']
    with pytest.raises(QueueError, match='Sincronizá'):
        store.preview('edificio-anexo', None, MESSAGE)


def test_failed_sync_preserves_data_but_blocks_new_test(setup):
    db, store, _ = setup
    db.record_failed_sync('Sin conexión con Google')
    assert len(db.list_recipients()) == 3
    with pytest.raises(QueueError): store.preview('edificio-anexo', None, MESSAGE)


def test_allowlist_maximum_mode_and_second_phone(setup):
    db, store, _ = setup
    restricted = GatewayStore(db.path, NUMBERS[:1])
    with pytest.raises(QueueError, match='fuera'):
        restricted.preview('edificio-anexo', None, MESSAGE)
    with pytest.raises(QueueError): store.preview('edificio-anexo', None, 'ALERTA REAL')
    with pytest.raises(QueueError): store.preview('edificio-anexo', None, 'PRUEBA - ' + 'A' * 161)
    with pytest.raises(QueueError): store.heartbeat(str(uuid.uuid4()), True, 'Otro teléfono')
    rows = sheet() + [['4', 'Cuarto', '+5493764000004', '', 'Anexo', 'SI', 'SI', 'NO', 'Informática']]
    db.sync_recipients(validate_sheet_values(rows))
    with pytest.raises(QueueError, match='entre 1 y 3'):
        store.preview('edificio-anexo', None, MESSAGE)


def test_api_requires_https_token_device_and_ticket(setup):
    _, store, _ = setup
    config = {'token_hash': hashlib.sha256(b'a' * 43).hexdigest(), 'expires_at': time.time() + 100,
              'allowed_numbers': NUMBERS}
    api = create_api(config, store)
    headers = {'Authorization': 'Bearer ' + 'a' * 43, 'X-Gateway-Device': DEVICE}
    with TestClient(api, base_url='https://192.168.1.5:8443') as client:
        assert client.post('/api/gateway/jobs/next').status_code == 401
        assert client.post('/api/gateway/heartbeat', headers=headers, json={'active': True}).status_code == 200
        assert client.get('/recipients', headers=headers).status_code == 404
        queued(store)
        job = client.post('/api/gateway/jobs/next', headers=headers).json()['job']
        bad = client.post(f"/api/gateway/jobs/{job['id']}/start", headers=headers, json={'ticket': str(uuid.uuid4())})
        assert bad.status_code == 409
        assert client.post(f"/api/gateway/jobs/{job['id']}/start", headers=headers, json={'ticket': job['ticket']}).json()['allowed']
        config['expires_at'] = 0
        assert client.post('/api/gateway/jobs/next', headers=headers).status_code == 401
    with TestClient(api, base_url='http://192.168.1.5:8443') as client:
        assert client.post('/api/gateway/jobs/next', headers=headers).status_code == 403


def test_local_panel_preview_confirm_tracking_and_csrf(setup, tmp_path, monkeypatch):
    db, store, _ = setup
    configfile = tmp_path / 'gateway-config.json'
    configfile.write_text(json.dumps({'version': 1, 'mode': 'test', 'allowed_numbers': NUMBERS, 'csrf': 'csrf-test'}))
    monkeypatch.setenv('GATEWAY_CONFIG_FILE', str(configfile))
    app = FastAPI()
    app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')
    install_gateway(app, db, Jinja2Templates(directory=BASE / 'templates'))
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 45000)) as client:
        assert 'Informática' in client.get('/gateway').text
        form = {'csrf_token': 'csrf-test', 'building_id': 'edificio-anexo', 'alert_type': 'maintenance', 'office': 'Informática'}
        assert client.post('/gateway/preview', data=form).status_code == 403
        response = client.post('/gateway/preview', data=form, headers={'Origin': 'http://127.0.0.1:8000'})
        assert response.status_code == 200
        assert '1 SMS reales de prueba' in response.text
        assert 'Persona 3' in response.text and 'Persona 1' not in response.text
        batch = store.dashboard()['batches'][0]['id']
        response = client.post(f'/gateway/batches/{batch}/confirm', data={'csrf_token': 'csrf-test', 'confirmation': 'CONFIRMAR'},
                               headers={'Origin': 'http://127.0.0.1:8000'})
        assert response.status_code == 200
        assert client.get('/gateway/status').json()['batches'][0]['counts']['QUEUED'] == 1
    with TestClient(app, base_url='http://evil.example', client=('127.0.0.1', 45000)) as client:
        assert client.get('/gateway').status_code == 403
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('192.168.1.8', 45000)) as client:
        assert client.get('/gateway').status_code == 403


def test_pairing_generates_trusted_certificate_without_google_access(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    pairing = create_configuration('192.168.1.5', NUMBERS, tmp_path)
    phone = json.loads(pairing.read_text())
    config = json.loads((tmp_path / 'credentials/gateway-config.json').read_text())
    assert config['token_hash'] == hashlib.sha256(phone['token'].encode()).hexdigest()
    assert 'token' not in config
    cert = x509.load_pem_x509_certificate(phone['certificatePem'].encode())
    assert str(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)[0]) == '192.168.1.5'
    key = serialization.load_pem_private_key((tmp_path / 'credentials/gateway-server.key').read_bytes(), password=None)
    assert key.public_key().public_numbers() == cert.public_key().public_numbers()
    with pytest.raises(ValueError): create_configuration('192.168.1.5', NUMBERS, tmp_path)
    with pytest.raises(ValueError): create_configuration('8.8.8.8', NUMBERS, tmp_path / 'public')
