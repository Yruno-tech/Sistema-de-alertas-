"""Two separate listeners: local operator UI and TLS-only phone API."""
import subprocess
import sys
import time

from gateway_config import BASE_DIR, load_gateway_config


def main():
    conf=load_gateway_config(required=True)
    if time.time() >= conf["expires_at"]:
        raise SystemExit("El emparejamiento venció. Renová la configuración antes de iniciar.")
    processes=[]
    try:
        commands=[
            ["main:app","--host","127.0.0.1","--port","8000"],
            ["gateway_api:app_factory","--factory","--host",conf["ip"],"--port","8443",
             "--ssl-keyfile","credentials/gateway-server.key","--ssl-certfile","credentials/gateway-server.pem"],
        ]
        for command in commands:
            processes.append(subprocess.Popen([sys.executable,"-m","uvicorn",*command,"--no-proxy-headers"],cwd=BASE_DIR))
        print("Panel en esta computadora: http://127.0.0.1:8000/gateway",flush=True)
        print("API del teléfono: HTTPS en la IP local configurada, puerto 8443",flush=True)
        print("Ctrl+C detiene ambos procesos. No se reinician automáticamente.",flush=True)
        while all(p.poll() is None for p in processes):
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
