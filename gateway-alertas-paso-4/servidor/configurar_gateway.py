"""Automatic local configuration. No phone list and no credential files to copy."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import shutil
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from gateway_config import BASE_DIR


def is_lan_ip(value):
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and any(address in ipaddress.ip_network(n) for n in
            ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    except ValueError:
        return False


def detect_lan_ip():
    candidates = []
    # UDP connect selects a local route; it does not send a datagram.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1', 80))
            candidates.append(sock.getsockname()[0])
    except OSError:
        pass
    try:
        candidates.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return next((ip for ip in candidates if is_lan_ip(ip)), None)


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.chmod(0o600)
    os.replace(temporary, path)


def create_configuration(ip, numbers=None, base=BASE_DIR):
    if not is_lan_ip(ip):
        raise ValueError('Indicá la IPv4 privada de la PC, por ejemplo 192.168.1.50')
    cred = Path(base) / 'credentials'
    path = cred / 'gateway-config.json'
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if old and old.get('version') != 2:
        shutil.copy2(path, cred / 'gateway-config-anterior.json')
    pem_path, key_path = cred / 'gateway-server.pem', cred / 'gateway-server.key'
    now = datetime.now(timezone.utc)
    cert = None
    try:
        candidate = x509.load_pem_x509_certificate(pem_path.read_bytes())
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        ips = candidate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
        if (ipaddress.ip_address(ip) in ips and candidate.not_valid_after_utc > now+timedelta(days=7)
                and candidate.public_key().public_numbers() == private_key.public_key().public_numbers()):
            cert = candidate
    except (OSError, ValueError, x509.ExtensionNotFound):
        pass
    if cert is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Gateway local de alertas')])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
            .not_valid_after(now+timedelta(days=1095))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
        private_write(key_path, key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
        private_write(pem_path, cert.public_bytes(serialization.Encoding.PEM).decode())
    data = {'version': 2, 'mode': 'test', 'server_id': old.get('server_id', str(uuid.uuid4())),
            'ip': ip, 'csrf': old.get('csrf', secrets.token_urlsafe(32)),
            'pairing_key': old.get('pairing_key', secrets.token_urlsafe(32)),
            'certificate_file': str(pem_path.resolve()), 'key_file': str(key_path.resolve()),
            'expires_at': cert.not_valid_after_utc.timestamp()}
    private_write(path, json.dumps(data, indent=2))
    return data


def ensure_configuration(ip=None):
    ip = ip or os.getenv('GATEWAY_IP') or detect_lan_ip()
    if not ip:
        raise RuntimeError('No se pudo detectar la IP. Ejecutá iniciar_gateway.py --ip IPv4_DE_LA_PC')
    return create_configuration(ip)


def main():
    parser = argparse.ArgumentParser(description='Configurar el gateway para emparejar por QR')
    parser.add_argument('--ip')
    args = parser.parse_args()
    config = ensure_configuration(args.ip)
    print(f"Gateway configurado en {config['ip']}. No hace falta copiar archivos al celular.")
    print('Ejecutá python iniciar_gateway.py y pulsá Conectar celular en el panel.')


if __name__ == '__main__': main()
