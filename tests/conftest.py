"""Configuración común de los tests: nada se escribe en data/ (los datos reales del usuario)."""

import pytest


@pytest.fixture(autouse=True)
def actividad_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr("core.seguridad.RUTA_ACTIVIDAD", tmp_path / "actividad.log")
