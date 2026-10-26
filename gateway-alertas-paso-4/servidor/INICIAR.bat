@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Falta el entorno Python. Segui la instalacion indicada en LEEME.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" iniciar_gateway.py
pause
