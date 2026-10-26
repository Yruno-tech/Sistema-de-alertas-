import base64
import hashlib
import json
import sqlite3
import uuid

import pytest

from configurar_gateway import create_configuration
from gateway_pairing import PairingService
from gateway_store import QueueError
from recipient_validation import validate_sheet_values
from test_gateway import setup, sheet, MESSAGE, DEVICE, NUMBERS


@pytest.mark.parametrize('value',['NO','No','FALSE',False,'0'])
@pytest.mark.parametrize('phone',['','no tiene celular','+5493764000001'])
def test_disabled_sms_is_not_an_incomplete_row(setup,value,phone):
    db,store,_=setup
    rows=sheet();rows[1][6]=value;rows[1][2]=phone
    validation=validate_sheet_values(rows)
    assert not validation.errors
    assert len(validation.recipients)==3
    summary=db.sync_recipients(validation)
    assert summary.status=='success'
    assert store.quote('edificio-anexo',None,MESSAGE)['count']==2


def test_all_sms_disabled_is_valid_and_gives_zero_recipients(setup):
    db,store,_=setup
    rows=sheet()
    for row in rows[1:]:row[6]='NO';row[2]=''
    result=validate_sheet_values(rows)
    assert not result.errors
    db.sync_recipients(result)
    quote=store.quote('edificio-anexo',None,MESSAGE)
    assert quote['count']==0
    with pytest.raises(QueueError,match='No hay personas'):
        store.enqueue('edificio-anexo',None,MESSAGE,str(uuid.uuid4()),quote['snapshot'])


def test_single_click_hundred_recipients_repeat_click_and_adaptive_expiry(setup):
    db,store,clock=setup
    rows=[sheet()[0]]+[[str(i),f'Persona {i}',f'+5493764{i:06d}','','Anexo','SI','SI','NO','Oficina'] for i in range(1,101)]
    db.sync_recipients(validate_sheet_values(rows))
    store.set_enabled(False)  # No separate enable confirmation is required for a new send.
    quote=store.quote('edificio-anexo',None,MESSAGE)
    assert quote['count']==100
    key=str(uuid.uuid4())
    assert store.enqueue('edificio-anexo',None,MESSAGE,key,quote['snapshot'])==key
    assert store.enqueue('edificio-anexo',None,MESSAGE,key,quote['snapshot'])==key
    batch=store.batch(key)
    assert len(batch['jobs'])==100 and batch['expires_at']-clock[0]>600
    ids=set()
    for _ in range(100):
        job=store.next_job(DEVICE)
        assert job['id'] not in ids
        ids.add(job['id'])
        assert job['interval_seconds']==2
        assert store.start(DEVICE,job['id'],job['ticket'])['allowed']
        store.report(DEVICE,job['id'],job['ticket'],1,'SENT','WAITING','Simulado')
        clock[0]+=2
    assert store.batch(key)['counts']['SENT']==100
    assert store.next_job(DEVICE) is None


def test_sync_without_changes_does_not_force_another_confirmation(setup):
    db,store,_=setup
    quote=store.quote('edificio-anexo',None,MESSAGE)
    db.sync_recipients(validate_sheet_values(sheet()))
    store.enqueue('edificio-anexo',None,MESSAGE,str(uuid.uuid4()),quote['snapshot'])


def test_changed_list_refreshes_preview_and_opt_out_cancels_before_sms(setup):
    db,store,_=setup
    quote=store.quote('edificio-anexo',None,MESSAGE)
    rows=sheet()+[['4','Nueva persona','+5493764000004','','Anexo','SI','SI','NO','Oficina']]
    db.sync_recipients(validate_sheet_values(rows))
    with pytest.raises(QueueError,match='lista cambió'):
        store.enqueue('edificio-anexo',None,MESSAGE,str(uuid.uuid4()),quote['snapshot'])
    quote=store.quote('edificio-anexo',None,MESSAGE)
    key=store.enqueue('edificio-anexo',None,MESSAGE,str(uuid.uuid4()),quote['snapshot'])
    assert len(store.batch(key)['jobs'])==4
    job=store.next_job(DEVICE)
    for row in rows[1:]:
        if row[2]==job['phone']:row[6]='NO'
    db.sync_recipients(validate_sheet_values(rows))
    assert store.start(DEVICE,job['id'],job['ticket'])=={'allowed':False,'status':'CANCELLED'}


def test_disabled_shared_phone_does_not_make_an_active_person_invalid(setup):
    rows=sheet();rows[1][6]='NO';rows[1][2]=rows[2][2]
    result=validate_sheet_values(rows)
    assert not result.errors
    assert len(result.recipients)==3


def test_qr_single_device_expiry_retry_rotation_and_no_static_number_list(setup,tmp_path):
    _,store,clock=setup
    config=create_configuration('192.168.1.5',base=tmp_path)
    pairing=PairingService(store.path,config,clock=lambda:clock[0]);pairing.initialize()
    qr=pairing.issue()
    assert 'token' not in qr and 'certificatePem' not in qr
    assert len(json.dumps(qr))<500
    phone=pairing.redeem(qr['id'],qr['secret'],DEVICE)
    assert 'allowedNumbers' not in phone and phone['recipientPolicy']=='database'
    assert pairing.token_valid(phone['token'],DEVICE)
    assert pairing.redeem(qr['id'],qr['secret'],DEVICE)['token']==phone['token']
    with pytest.raises(QueueError):pairing.redeem(qr['id'],qr['secret'],str(uuid.uuid4()))
    with pytest.raises(QueueError):pairing.redeem(qr['id'],'invalid-secret',DEVICE)
    clock[0]+=301
    with pytest.raises(QueueError):pairing.redeem(qr['id'],qr['secret'],DEVICE)
    next_qr=pairing.issue()
    next_phone=pairing.redeem(next_qr['id'],next_qr['secret'],DEVICE)
    assert not pairing.token_valid(phone['token'],DEVICE)
    assert pairing.token_valid(next_phone['token'],DEVICE)
    assert not pairing.token_valid(next_phone['token'],str(uuid.uuid4()))


def test_old_config_upgrades_without_carrying_three_person_allowlist(tmp_path):
    credentials=tmp_path/'credentials';credentials.mkdir()
    old={'version':1,'mode':'test','server_id':str(uuid.uuid4()),'allowed_numbers':NUMBERS,'csrf':'preserved'}
    (credentials/'gateway-config.json').write_text(json.dumps(old))
    config=create_configuration('192.168.1.5',base=tmp_path)
    assert config['version']==2 and 'allowed_numbers' not in config
    assert config['server_id']==old['server_id'] and config['csrf']=='preserved'
    assert (credentials/'gateway-config-anterior.json').exists()
