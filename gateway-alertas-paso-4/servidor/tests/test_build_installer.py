from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from instalador_gateway import InstallerError, _validate_payload_path
from build_installer import SERVER_DIRECTORY, create_payload


def test_payload_includes_app_and_excludes_local_secrets(tmp_path: Path) -> None:
    payload = tmp_path / "gateway_payload.zip"

    names = set(create_payload(SERVER_DIRECTORY, payload))

    assert ".env.example" in names
    assert "main.py" in names
    assert "templates/gateway.html" in names
    assert "templates/settings.html" in names
    assert "static/gateway.js" in names
    assert "build_installer.py" not in names
    assert "instalador_gateway.py" not in names
    assert ".env" not in names
    assert "emparejar-gateway.json" not in names
    assert not any(
        part.lower() in {"credentials", "data", ".venv", "venv", "tests"}
        for name in names
        for part in Path(name).parts
    )
    assert not any(
        Path(name).suffix.lower() in {".db", ".pem", ".key"} for name in names
    )

    with zipfile.ZipFile(payload) as archive:
        assert archive.testzip() is None


@pytest.mark.parametrize(
    "name",
    [
        "../outside.txt",
        "C:/outside.txt",
        ".env",
        "credentials/service-account.json",
        "data/alerts.db",
        "templates/server.key",
    ],
)
def test_payload_rejects_paths_outside_the_app_code(name: str) -> None:
    with pytest.raises(InstallerError):
        _validate_payload_path(name)
