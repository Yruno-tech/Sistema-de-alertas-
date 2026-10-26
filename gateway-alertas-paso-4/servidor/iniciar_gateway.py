"""Two separate listeners: local operator UI and TLS-only phone API."""
import subprocess
import argparse
import sys
import time
import webbrowser
from urllib.request import build_opener, ProxyHandler

from gateway_config import BASE_DIR
from configurar_gateway import ensure_configuration
from config import settings
from database import Database
from gateway_store import GatewayStore
from gateway_pairing import PairingService


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--ip', help='IPv4 de la PC si la detección automática elige otro adaptador')
    parser.add_argument('--no-browser', action='store_true', help='No abrir el panel automáticamente')
    args=parser.parse_args()
    conf=ensure_configuration(args.ip)
    # Apply migrations once before the two listeners start concurrently.
    Database(settings.database_path).initialize()
    GatewayStore(settings.database_path).initialize()
    PairingService(settings.database_path,conf).initialize()
    processes=[]
    try:
        commands=[
            ["main:app","--host","127.0.0.1","--port","8000"],
            ["gateway_api:app_factory","--factory","--host",conf["ip"],"--port","8443",
             "--ssl-keyfile",conf['key_file'],"--ssl-certfile",conf['certificate_file']],
        ]
        for command in commands:
            processes.append(subprocess.Popen([sys.executable,"-m","uvicorn",*command,"--no-proxy-headers"],cwd=BASE_DIR))
        print("Panel en esta computadora: http://127.0.0.1:8000/gateway",flush=True)
        print("API del teléfono: HTTPS en la IP local configurada, puerto 8443",flush=True)
        print("Ctrl+C detiene ambos procesos. No se reinician automáticamente.",flush=True)
        browser_pending=not args.no_browser
        browser_deadline=time.monotonic()+20
        opener=build_opener(ProxyHandler({}))
        while all(p.poll() is None for p in processes):
            if browser_pending and time.monotonic()<browser_deadline:
                try:
                    with opener.open('http://127.0.0.1:8000/health',timeout=0.5) as response:
                        if response.status==200:
                            browser_pending=False
                            webbrowser.open('http://127.0.0.1:8000/gateway')
                except OSError:
                    pass
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
