from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def config_path():
    return Path(os.environ.get('GATEWAY_CONFIG_FILE', str(BASE_DIR / 'credentials/gateway-config.json')))


def load_gateway_config(required=False):
    path = config_path()
    if not path.exists():
        if required:
            raise RuntimeError('Iniciá con python iniciar_gateway.py para configurar el QR automáticamente')
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 2 or data.get('mode') != 'test':
        raise RuntimeError('Actualización pendiente: ejecutá python iniciar_gateway.py y escaneá el nuevo QR')
    return data
