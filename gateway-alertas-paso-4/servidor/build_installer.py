from __future__ import annotations

import argparse
import importlib.util
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


SERVER_DIRECTORY = Path(__file__).resolve().parent
INSTALLER_SCRIPT = SERVER_DIRECTORY / "instalador_gateway.py"
OUTPUT_DIRECTORY = SERVER_DIRECTORY / "dist"
WORK_DIRECTORY = SERVER_DIRECTORY / "build" / "pyinstaller"
SPEC_DIRECTORY = SERVER_DIRECTORY / "build"
OUTPUT_NAME = "Instalar Gateway de alertas.exe"
ROOT_FILES = {".env.example", "INICIAR.bat", "README.md", "requirements.txt"}
EXCLUDED_SCRIPTS = {"build_installer.py", "instalador_gateway.py"}
ASSET_DIRECTORIES = {"static", "templates"}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "credentials",
    "data",
    "tests",
}


def _is_safe_source_path(path: Path) -> bool:
    relative = path.relative_to(SERVER_DIRECTORY)
    parts = {part.lower() for part in relative.parts}
    name = relative.name.lower()
    return not (
        parts.intersection(EXCLUDED_PARTS)
        or name == ".env"
        or name == "emparejar-gateway.json"
        or relative.suffix.lower() in {".db", ".pem", ".key"}
        or path.is_symlink()
    )


def create_payload(source_directory: Path, output_zip: Path) -> tuple[str, ...]:
    candidates: list[Path] = []
    for path in source_directory.iterdir():
        if path.is_file() and (
            path.suffix.lower() == ".py" or path.name in ROOT_FILES
        ) and path.name not in EXCLUDED_SCRIPTS:
            candidates.append(path)
        elif path.is_dir() and path.name in ASSET_DIRECTORIES:
            candidates.extend(item for item in path.rglob("*") if item.is_file())

    entries: list[tuple[Path, str]] = []
    for path in candidates:
        if not _is_safe_source_path(path):
            continue
        relative = path.relative_to(source_directory).as_posix()
        parts = PurePosixPath(relative).parts
        if (
            any(part.lower() in EXCLUDED_PARTS for part in parts)
            or PurePosixPath(relative).suffix.lower() in {".db", ".pem", ".key"}
            or PurePosixPath(relative).name.lower() in {
                ".env",
                "emparejar-gateway.json",
            }
        ):
            continue
        entries.append((path, relative))

    entry_names = {relative for _, relative in entries}
    required = {
        ".env.example",
        "INICIAR.bat",
        "config.py",
        "iniciar_gateway.py",
        "requirements.txt",
        "main.py",
        "gateway_api.py",
    }
    missing = required - entry_names
    if missing:
        raise RuntimeError(
            "Faltan archivos requeridos para el instalador: "
            + ", ".join(sorted(missing))
        )

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_zip,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path, relative in sorted(entries, key=lambda item: item[1].lower()):
            archive.write(path, relative)
    return tuple(sorted(entry_names))


def build_installer() -> Path:
    if sys.platform != "win32":
        raise RuntimeError("El instalador debe construirse desde Windows.")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("El instalador requiere una PC de compilación x64.")
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError(
            "Falta PyInstaller. Instalalo con: "
            f'"{sys.executable}" -m pip install -r requirements-dev.txt'
        )
    if not INSTALLER_SCRIPT.is_file():
        raise RuntimeError(f"No se encontró el instalador: {INSTALLER_SCRIPT}")

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gateway-payload-") as temporary:
        payload = Path(temporary) / "gateway_payload.zip"
        create_payload(SERVER_DIRECTORY, payload)
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--onefile",
            "--console",
            "--name",
            "Instalar Gateway de alertas",
            "--distpath",
            str(OUTPUT_DIRECTORY),
            "--workpath",
            str(WORK_DIRECTORY),
            "--specpath",
            str(SPEC_DIRECTORY),
            "--add-data",
            f"{payload};.",
            str(INSTALLER_SCRIPT),
        ]
        subprocess.run(command, cwd=SERVER_DIRECTORY, check=True)

    output = OUTPUT_DIRECTORY / OUTPUT_NAME
    if not output.is_file():
        raise RuntimeError(f"PyInstaller terminó sin generar {output}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Construye el instalador Windows del Gateway de alertas."
    )
    parser.parse_args()
    try:
        output = build_installer()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"No se pudo construir el instalador: {error}", file=sys.stderr)
        return 1
    print(f"Instalador creado: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
