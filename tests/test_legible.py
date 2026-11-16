"""
Tests de las acciones en lenguaje normal de las ventanas de seguridad
(core/legible.py) y del formato de sus preguntas.

    python -m pytest tests
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.legible import accion_legible, teclas_legibles  # noqa: E402
from interfaz import formatear_pregunta  # noqa: E402


@pytest.mark.parametrize("descripcion, pasos", [
    ("hacer_clic(elemento='JUGAR', aplicacion='Steam')", ["Pulsar «JUGAR» en Steam"]),
    ("cerrar_aplicacion(aplicacion='Steam')", ["Cerrar Steam"]),
    ("ejecutar_en_steam(juego='Hades')", ["Lanzar Hades desde Steam"]),
    ("escribir_texto(texto='hola', campo='Buscar', aplicacion='Discord')",
     ["Escribir «hola» en el campo «Buscar» de Discord"]),
    ("abrir_aplicacion(aplicacion='Steam') → pulsar_teclas(teclas='control shift t', aplicacion='Opera')",
     ["Abrir Steam", "Pulsar Ctrl + Mayús + T en Opera"]),
    ("abrir_aplicacion(aplicacion='Baldur's Gate 3')", ["Abrir Baldur's Gate 3"]),   # apóstrofo en el valor
    ("skill_nueva(dato='x')", ["Skill nueva (dato: x)"]),
    ("algo que no es un paso", ["algo que no es un paso"]),
])
def test_accion_legible(descripcion, pasos):
    assert accion_legible(descripcion) == (None, pasos)


def test_accion_programada():
    assert accion_legible("programar para mañana a las 9:00: abrir_aplicacion(aplicacion='Steam')") == \
        ("mañana a las 9:00", ["Abrir Steam"])


def test_teclas_legibles():
    assert teclas_legibles("control l") == "Ctrl + L"
    assert teclas_legibles("enter") == "Enter"
    assert teclas_legibles("tab dos veces") == "tab dos veces"


def test_formatear_pregunta_pone_las_opciones_en_lineas():
    texto = "Veo varios: 1) Slay the Spire; 2) Slay the Spire 2. ¿Cuál pulso? (número o nombre)"
    assert formatear_pregunta(texto) == "Veo varios:\n1) Slay the Spire\n2) Slay the Spire 2\n\n¿Cuál pulso? (número o nombre)"
    assert formatear_pregunta("¿Qué texto escribo?") == "¿Qué texto escribo?"
