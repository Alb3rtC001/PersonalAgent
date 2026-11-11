"""
Tests de la skill crear_nota y de la extracción de slots.

Ejecutar desde la raíz del proyecto:
    python -m pytest tests
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.estado import EstadoMundo  # noqa: E402
from core.executor import ejecutar_orden  # noqa: E402
from core.memoria import cargar_episodios  # noqa: E402
from core.skills.crear_nota import CrearNota  # noqa: E402
from nlu.slots import extraer_slot  # noqa: E402


def _orden(tmp_path, params, episodios):
    return ejecutar_orden(
        "crear_nota", params, texto="test",
        registro={"crear_nota": CrearNota(carpeta=tmp_path / "notas")},
        estado=EstadoMundo(consulta=lambda h: False),
        ruta_episodios=episodios,
    )


def test_crea_nota_y_registra_episodio(tmp_path):
    episodios = tmp_path / "episodios.jsonl"
    r = _orden(tmp_path, {"contenido": "Comprar pan y leche"}, episodios)
    assert r.ok, r.mensaje
    contenido = Path(r.datos["ruta"]).read_text(encoding="utf-8")
    assert contenido.startswith("# Comprar pan y leche")

    eps = cargar_episodios(episodios)
    assert len(eps) == 1 and eps[0]["ok"] and eps[0]["skill"] == "crear_nota"


def test_nota_vacia_pide_contenido_y_no_registra(tmp_path):
    episodios = tmp_path / "episodios.jsonl"
    r = _orden(tmp_path, {}, episodios)
    assert not r.ok and r.falta == "contenido"
    assert cargar_episodios(episodios) == []


def test_dos_notas_iguales_no_se_pisan(tmp_path):
    eps = tmp_path / "e.jsonl"
    r1 = _orden(tmp_path, {"contenido": "repetida"}, eps)
    r2 = _orden(tmp_path, {"contenido": "repetida"}, eps)
    assert r1.ok and r2.ok
    assert r1.datos["ruta"] != r2.datos["ruta"]


def test_slot_conserva_mayusculas_y_tildes():
    assert extraer_slot("Apunta que mañana llamo a María", "crear_nota") == "mañana llamo a María"
    assert extraer_slot("hazme una nota que diga Revisar el coche", "crear_nota") == "Revisar el coche"
    assert extraer_slot("Ábreme la Calculadora", "abrir_aplicacion") == "Calculadora"
    assert extraer_slot("﻿crea una nota", "crear_nota") == ""
