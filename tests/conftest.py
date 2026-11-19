"""Configuración común de los tests: nada se escribe en data/ (los datos reales del usuario)."""

import pytest


@pytest.fixture(autouse=True)
def actividad_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr("core.seguridad.RUTA_ACTIVIDAD", tmp_path / "actividad.log")
    # Los campos recordados por app (escribir_texto) tampoco van a data/campos.json.
    monkeypatch.setattr("core.campos.RUTA_CAMPOS", tmp_path / "campos.json")
    # Fase 7: frases aprendidas y órdenes compuestas, tampoco en data/.
    monkeypatch.setattr("aprendizaje.datos.RUTA_APRENDIDAS", tmp_path / "frases_aprendidas.json")
    monkeypatch.setattr("core.skills.compuesta.RUTA_COMPUESTAS", tmp_path / "compuestas")
