from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def config_path():
    return Path(os.environ.get("GATEWAY_CONFIG_FILE", str(BASE_DIR / "credentials/gateway-config.json")))


def load_gateway_config(required=False):
    path = config_path()
    if not path.exists():
        if required:
            raise RuntimeError("Primero ejecutá python configurar_gateway.py")
        return None
    data=json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or data.get("mode") != "test":
        raise RuntimeError("Configuración de gateway no compatible")
    if not 1 <= len(data["allowed_numbers"]) <= 3:
        raise RuntimeError("El piloto admite de 1 a 3 números autorizados")
    return data


def token_valid(config, token):
    return bool(config and time.time() < config["expires_at"] and
                secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), config["token_hash"]))
