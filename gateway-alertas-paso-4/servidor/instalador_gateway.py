from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


APP_NAME = "Gateway de alertas"
PYTHON_VERSION = "3.14.10"
PYTHON_URL = (
    "https://www.python.org/ftp/python/3.14.10/"
    "python-3.14.10-amd64.exe"
)
PYTHON_SHA256 = "92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965"
PAYLOAD_NAME = "gateway_payload.zip"


class InstallerError(Exception):
    pass


def _resource_directory() -> Path:
    bundle_directory = getattr(sys, "_MEIPASS", None)
    if bundle_directory:
        return Path(bundle_directory)
    return Path(__file__).resolve().parent


def _validate_payload_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    forbidden_parts = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        "credentials",
        "data",
        "tests",
    }
    if (
        not path.parts
        or path.is_absolute()
        or any(
            part in {"", ".", ".."} or ":" in part or "\x00" in part
            for part in path.parts
        )
        or any(part.lower() in forbidden_parts for part in path.parts)
        or path.name.lower() == ".env"
        or path.name.lower() == "emparejar-gateway.json"
        or path.suffix.lower() in {".db", ".pem", ".key"}
    ):
        raise InstallerError(f"El paquete contiene una ruta no permitida: {name}")
    return path


def _extract_payload(payload: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(payload) as archive:
        for entry in archive.infolist():
            relative_path = _validate_payload_path(entry.filename)
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise InstallerError("El paquete no puede incluir enlaces simbólicos.")
            target = destination.joinpath(*relative_path.parts)
            target_resolved = target.resolve()
            if (
                target_resolved != destination_resolved
                and destination_resolved not in target_resolved.parents
            ):
                raise InstallerError(
                    "El paquete intenta escribir fuera de la carpeta de instalación."
                )
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _python_version(python_executable: Path) -> str:
    result = subprocess.run(
        [
            str(python_executable),
            "-c",
            "import sys; print('.'.join(map(str, sys.version_info[:3])))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _download_python_installer(destination: Path) -> None:
    request = urllib.request.Request(
        PYTHON_URL,
        headers={"User-Agent": "GatewayAlertasInstaller/1.0"},
    )
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response:
        total_size = response.headers.get("Content-Length")
        expected_size = int(total_size) if total_size and total_size.isdigit() else None
        downloaded = 0
        with destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if expected_size:
                    percent = min(100, downloaded * 100 // expected_size)
                    print(f"\rDescargando Python: {percent}%", end="", flush=True)
    if expected_size:
        print()
    if digest.hexdigest() != PYTHON_SHA256:
        destination.unlink(missing_ok=True)
        raise InstallerError(
            "La verificación SHA-256 del instalador de Python falló; "
            "no se ejecutó el archivo descargado."
        )


def _ensure_python(install_directory: Path) -> Path:
    python_directory = install_directory / f"python-{PYTHON_VERSION}"
    python_executable = python_directory / "python.exe"
    if python_executable.exists():
        version = _python_version(python_executable)
        if version == PYTHON_VERSION:
            return python_executable
        raise InstallerError(
            f"Hay una instalación de Python distinta en {python_directory}. "
            "No se reemplazó."
        )
    if python_directory.exists() and any(python_directory.iterdir()):
        raise InstallerError(
            f"La carpeta de Python está incompleta: {python_directory}. "
            "No se modificó."
        )

    python_directory.mkdir(parents=True, exist_ok=True)
    print(f"Descargando Python {PYTHON_VERSION} desde python.org...")
    with tempfile.TemporaryDirectory(prefix="gateway-python-") as temporary_directory:
        installer = Path(temporary_directory) / "python-installer.exe"
        _download_python_installer(installer)
        print("Instalando Python en la carpeta del usuario...")
        result = subprocess.run(
            [
                str(installer),
                "/quiet",
                "InstallAllUsers=0",
                f"TargetDir={python_directory}",
                "PrependPath=0",
                "Include_launcher=0",
                "Include_pip=1",
                "Include_test=0",
                "Include_doc=0",
            ],
            check=False,
        )
        if result.returncode not in {0, 3010}:
            raise InstallerError(
                f"El instalador oficial de Python terminó con código {result.returncode}."
            )
    if not python_executable.exists():
        raise InstallerError("Python terminó de instalarse, pero falta python.exe.")
    version = _python_version(python_executable)
    if version != PYTHON_VERSION:
        raise InstallerError(
            f"Se esperaba Python {PYTHON_VERSION}, pero se instaló {version}."
        )
    return python_executable


def _create_desktop_shortcut(
    install_directory: Path,
    venv_python: Path,
    desktop_directory: Path | None = None,
) -> Path:
    powershell = shutil.which("powershell.exe")
    if not powershell:
        raise InstallerError("No se encontró PowerShell para crear el acceso directo.")

    if desktop_directory is None:
        desktop_result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Environment]::GetFolderPath('Desktop')",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        desktop = Path(desktop_result.stdout.strip())
    else:
        desktop = desktop_directory.resolve()
    if not desktop.is_dir():
        raise InstallerError("No se pudo encontrar el Escritorio de este usuario.")

    shortcut_path = desktop / f"{APP_NAME}.lnk"
    environment = os.environ.copy()
    environment.update(
        {
            "GATEWAY_SHORTCUT": str(shortcut_path),
            "GATEWAY_CMD": str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"),
            "GATEWAY_BATCH": str(install_directory / "INICIAR.bat"),
            "GATEWAY_WORKDIR": str(install_directory),
            "GATEWAY_ICON": str(venv_python),
        }
    )
    command = (
        "$shell = New-Object -ComObject WScript.Shell; "
        "$link = $shell.CreateShortcut($env:GATEWAY_SHORTCUT); "
        "$link.TargetPath = $env:GATEWAY_CMD; "
        "$link.Arguments = '/c \"\"' + $env:GATEWAY_BATCH + '\"\"'; "
        "$link.WorkingDirectory = $env:GATEWAY_WORKDIR; "
        "$link.Description = 'Iniciar el panel local del Gateway de alertas'; "
        "$link.IconLocation = $env:GATEWAY_ICON + ',0'; "
        "$link.Save()"
    )
    subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    if not shortcut_path.is_file():
        raise InstallerError("PowerShell no creó el acceso directo esperado.")
    return shortcut_path


def install(
    install_directory: Path | None = None,
    desktop_directory: Path | None = None,
) -> Path:
    if sys.platform != "win32":
        raise InstallerError("Este instalador funciona únicamente en Windows.")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise InstallerError("Por ahora se requiere Windows de 64 bits (x64).")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise InstallerError("Windows no informó la carpeta LOCALAPPDATA del usuario.")

    install_directory = (
        install_directory
        or Path(local_app_data) / "Programs" / APP_NAME
    ).resolve()
    payload = _resource_directory() / PAYLOAD_NAME
    if not payload.is_file():
        raise InstallerError("Falta el paquete de archivos incluido en el instalador.")

    print(f"Instalando en: {install_directory}")
    install_directory.mkdir(parents=True, exist_ok=True)
    _extract_payload(payload, install_directory)

    environment_file = install_directory / ".env"
    example_file = install_directory / ".env.example"
    if not environment_file.exists():
        if not example_file.is_file():
            raise InstallerError("El paquete no incluye .env.example.")
        shutil.copyfile(example_file, environment_file)
    (install_directory / "credentials").mkdir(exist_ok=True)
    (install_directory / "data").mkdir(exist_ok=True)

    python_executable = _ensure_python(install_directory)
    venv_directory = install_directory / ".venv"
    print("Preparando el entorno privado de la aplicación...")
    subprocess.run(
        [str(python_executable), "-m", "venv", "--clear", str(venv_directory)],
        check=True,
    )
    venv_python = venv_directory / "Scripts" / "python.exe"
    print("Descargando e instalando las dependencias...")
    subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(install_directory / "requirements.txt"),
        ],
        cwd=install_directory,
        check=True,
    )
    shortcut = _create_desktop_shortcut(
        install_directory, venv_python, desktop_directory
    )
    print()
    print("Instalación finalizada.")
    print(f"Acceso directo creado: {shortcut}")
    print("La configuración, las credenciales y la base de datos quedan en esta PC.")
    print("Abrí «Gateway de alertas» desde el Escritorio para iniciar el panel.")
    return install_directory


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Instalador de {APP_NAME}")
    parser.add_argument(
        "--install-dir",
        type=Path,
        help="Carpeta destino (por defecto, dentro del perfil del usuario).",
    )
    parser.add_argument(
        "--desktop-dir",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    print(f"Instalador de {APP_NAME}")
    print("Se descargará Python y se instalarán las dependencias. Se requiere Internet.")
    try:
        install(args.install_dir, args.desktop_dir)
    except (
        InstallerError,
        OSError,
        urllib.error.URLError,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
    ) as error:
        print()
        print(f"No se completó la instalación: {error}")
        return 1
    if sys.stdin.isatty() and not args.no_pause:
        try:
            input("Presioná Enter para cerrar esta ventana...")
        except EOFError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
