"""Copies reviewed source files, backing up overwritten code. Uses Python's standard library only."""
from __future__ import annotations

import argparse
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent


def install(source: Path, destination: Path, kind: str):
    destination = destination.resolve()
    if not destination.is_dir():
        raise ValueError(f"No existe el proyecto: {destination}")
    if kind == 'servidor':
        if not all((destination / name).exists() for name in ('main.py', 'database.py', 'recipient_validation.py')):
            raise ValueError('La carpeta no parece ser ProgramaAlertas del Paso 3')
        excluded = {'credentials', 'data', '.venv', '__pycache__', '.pytest_cache'}
    else:
        gradle = destination / 'android/app/build.gradle.kts'
        if not gradle.exists(): gradle = destination / 'android/app/build.gradle'
        if not (destination / 'pubspec.yaml').exists() or not gradle.exists():
            raise ValueError('Primero crea el proyecto Android con flutter create; consulta LEEME.md')
        text = gradle.read_text(encoding='utf-8')
        if not re.search(r'applicationId\s*(?:=\s*)?[\"\x27]ar\.gob\.misiones\.gateway_alertas[\"\x27]', text):
            raise ValueError('El applicationId debe ser ar.gob.misiones.gateway_alertas; no se cambiara automaticamente')
        excluded = {'.dart_tool', 'build', '__pycache__', '.pytest_cache'}
    files = [p for p in source.rglob('*') if p.is_file() and not excluded.intersection(p.relative_to(source).parts)
             and p.name not in {'.env', 'pubspec.lock'} and p.suffix != '.pyc']
    replacements = [p.relative_to(source) for p in files if (destination / p.relative_to(source)).exists()]
    backup = destination.parent / f'{destination.name}-codigo-antes-gateway-{datetime.now():%Y%m%d-%H%M%S-%f}.zip'
    with zipfile.ZipFile(backup, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in replacements: archive.write(destination / relative, relative)
    for path in files:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    print(f'Actualizado: {destination}')
    print(f'Respaldo del codigo reemplazado: {backup}')
    if kind == 'servidor':
        print('Se conservaron .env, las credenciales y la base. Instala requirements.txt y lee LEEME.md.')
    else:
        print('Ejecuta flutter pub get, flutter analyze, flutter test y flutter run. Requiere recompilacion completa.')


def main():
    parser = argparse.ArgumentParser(description='Actualizacion con respaldo del codigo existente')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--servidor', type=Path)
    group.add_argument('--flutter', type=Path)
    args = parser.parse_args()
    try:
        if args.servidor: install(BASE / 'servidor', args.servidor, 'servidor')
        else: install(BASE / 'flutter-overlay', args.flutter, 'flutter')
    except (ValueError, OSError) as error:
        parser.exit(1, f'No se pudo completar la actualizacion: {error}\n')


if __name__ == '__main__': main()
