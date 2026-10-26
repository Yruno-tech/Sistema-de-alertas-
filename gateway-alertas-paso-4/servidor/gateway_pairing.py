"""Five-minute single-device QR; replay by the same device recovers a lost response."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from gateway_store import QueueError


class PairingService:
    def __init__(self, path, config, clock=time.time):
        self.path, self.config, self.clock = Path(path), config, clock

    def initialize(self):
        with sqlite3.connect(self.path) as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS gateway_pairings(
                id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, expires_at REAL NOT NULL,
                device_id TEXT, used_at REAL);
              CREATE TABLE IF NOT EXISTS gateway_credentials(
                id INTEGER PRIMARY KEY CHECK(id=1),device_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,expires_at REAL NOT NULL,pairing_id TEXT NOT NULL);
            ''')

    def certificate(self):
        return Path(self.config['certificate_file']).read_text(encoding='utf-8')

    def issue(self):
        pairing_id, secret = str(uuid.uuid4()), secrets.token_urlsafe(32)
        expires = self.clock() + 300
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM gateway_pairings')
            db.execute('INSERT INTO gateway_pairings(id,secret_hash,expires_at) VALUES(?,?,?)',
                (pairing_id,hashlib.sha256(secret.encode()).hexdigest(),expires))
        certificate = x509.load_pem_x509_certificate(self.certificate().encode())
        return {'version':2,'purpose':'gateway-pair','url':f"https://{self.config['ip']}:8443",
                'id':pairing_id,'secret':secret,'expiresAt':expires,
                'certificateSha256':certificate.fingerprint(hashes.SHA256()).hex()}

    def redeem(self, pairing_id, secret, device_id):
        if str(uuid.UUID(device_id)) != device_id:
            raise QueueError('Dispositivo inválido')
        with sqlite3.connect(self.path, timeout=10) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM gateway_pairings WHERE id=?', (pairing_id,)).fetchone()
            if (not row or row['expires_at'] < self.clock() or not secrets.compare_digest(
                    row['secret_hash'],hashlib.sha256(secret.encode()).hexdigest())):
                raise QueueError('El QR no es válido o venció. Generá otro desde la PC.')
            if row['device_id'] and row['device_id'] != device_id:
                raise QueueError('Este QR ya se usó en otro celular')
            token = base64.urlsafe_b64encode(hmac.new(self.config['pairing_key'].encode(),
                f'{pairing_id}:{device_id}'.encode(),hashlib.sha256).digest()).decode().rstrip('=')
            existing = db.execute('SELECT * FROM gateway_credentials WHERE id=1').fetchone()
            if row['used_at']:
                if not existing or existing['pairing_id'] != pairing_id:
                    raise QueueError('Este vínculo fue reemplazado. Generá un QR nuevo.')
                expiry = existing['expires_at']
            else:
                if db.execute("SELECT 1 FROM gateway_jobs WHERE status IN ('CLAIMED','STARTED') LIMIT 1").fetchone():
                    raise QueueError('Esperá a que termine el SMS en curso antes de cambiar el vínculo')
                expiry = min(self.clock()+365*86400, self.config['expires_at'])
                db.execute('INSERT OR REPLACE INTO gateway_credentials VALUES(1,?,?,?,?)',
                    (device_id,hashlib.sha256(token.encode()).hexdigest(),expiry,pairing_id))
                db.execute('UPDATE gateway_pairings SET device_id=?,used_at=? WHERE id=?',
                    (device_id,self.clock(),pairing_id))
                db.execute('UPDATE gateway_control SET device_id=?,enabled=0,active=0,last_seen=0 WHERE id=1', (device_id,))
            return {'version':2,'mode':'test','serverId':self.config['server_id'],
                    'url':f"https://{self.config['ip']}:8443",'token':token,'certificatePem':self.certificate(),
                    'recipientPolicy':'database','expiresAt':expiry}

    def token_valid(self, token, device_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT device_id,token_hash,expires_at FROM gateway_credentials WHERE id=1').fetchone()
        return bool(row and row[0] == device_id and row[2] > self.clock() and
                    secrets.compare_digest(row[1],hashlib.sha256(token.encode()).hexdigest()))
