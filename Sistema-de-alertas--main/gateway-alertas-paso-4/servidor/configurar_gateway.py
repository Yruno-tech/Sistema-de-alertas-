"""Run locally by the operator. Generates no SMS and preserves Google credentials."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from gateway_config import BASE_DIR, config_path
from recipient_validation import normalize_argentina_mobile


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        out.write(data)
    path.chmod(0o600)


def create_configuration(ip, numbers, base=BASE_DIR):
    address=ipaddress.ip_address(ip)
    networks=[ipaddress.ip_network(n) for n in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16")]
    if not any(address in n for n in networks):
        raise ValueError("Ingresá la IPv4 de la red local de la computadora")
    allowed=sorted(set(normalize_argentina_mobile(n) for n in numbers))
    if not 1 <= len(allowed) <= 3:
        raise ValueError("Se requieren entre 1 y 3 celulares autorizados")
    cred=base / "credentials"
    path=cred / "gateway-config.json"
    pairing=base / "emparejar-gateway.json"
    for existing in (path,pairing,cred/"gateway-server.pem",cred/"gateway-server.key"):
        if existing.exists():
            raise ValueError(f"Ya existe {existing.name}. Conservá la configuración o mové esos cuatro archivos para renovar y volver a emparejar.")
    now=datetime.now(timezone.utc)
    expires=now+timedelta(days=30)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"Gateway local de pruebas")])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=5)).not_valid_after(expires)
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(address)]),critical=False)
          .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
          .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
          .sign(key,hashes.SHA256()))
    pem=cert.public_bytes(serialization.Encoding.PEM).decode()
    secret=secrets.token_urlsafe(32)
    server_id=str(uuid.uuid4())
    config={"version":1,"mode":"test","server_id":server_id,"ip":ip,
            "token_hash":hashlib.sha256(secret.encode()).hexdigest(),
            "csrf":secrets.token_urlsafe(32),"allowed_numbers":allowed,
            "expires_at":expires.timestamp()}
    phone={"version":1,"mode":"test","serverId":server_id,
           "url":f"https://{ip}:8443","token":secret,"certificatePem":pem,
           "allowedNumbers":allowed,"expiresAt":expires.timestamp()}
    private_write(cred/"gateway-server.key", key.private_bytes(serialization.Encoding.PEM,
                  serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode())
    private_write(cred/"gateway-server.pem",pem)
    private_write(path,json.dumps(config,indent=2))
    private_write(pairing,json.dumps(phone,indent=2))
    return pairing


def backup_database():
    from config import settings
    if settings.database_path.exists():
        stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
        target=settings.database_path.with_name(f"alerts-before-gateway-{stamp}.db")
        with sqlite3.connect(settings.database_path) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
        print(f"Copia de respaldo: {target}")


def main():
    parser=argparse.ArgumentParser(description="Emparejamiento local sin enviar SMS")
    parser.add_argument("--ip")
    parser.add_argument("--numbers",help="1 a 3 celulares separados por coma")
    args=parser.parse_args()
    print("Consultá la IPv4 del adaptador Wi-Fi con ipconfig. No uses la IP del celular.")
    ip=args.ip or input("IPv4 de esta computadora: ").strip()
    numbers=(args.numbers or input("Celulares autorizados (+549..., separados por coma): ")).split(",")
    pairing=create_configuration(ip,numbers)
    backup_database()
    print(f"Listo. Copiá por USB al teléfono: {pairing}")
    print("Este archivo permite acceder al gateway: guardalo en privado y quitá la copia de Descargas después de importarla.")
    print("Validez: 30 días. Conservá las credenciales de Google sin modificaciones.")
    print("Revisá GOOGLE_SHEETS_RANGE en .env: si oficina es la columna I, usá DESTINATARIOS!A1:I.")
    print("Iniciá con: python iniciar_gateway.py")


if __name__ == "__main__":
    main()
