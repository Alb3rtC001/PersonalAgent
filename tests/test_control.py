"""
Tests del botón de pánico (core/control.py) y de programar con tiempo
explícito (los recuadros de la interfaz). Sin Windows ni GPU.

    python -m pytest tests
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import control  # noqa: E402
from core.agenda import Agenda, Planificador  # noqa: E402
from core.agente import Agente  # noqa: E402
from core.router import Interpretacion  # noqa: E402
from core.skills.base import Resultado, Skill  # noqa: E402


@pytest.fixture(autouse=True)
def sin_pausa():
    control.reanudar()
    yield
    control.reanudar()


class Larga(Skill):
    """Una skill con un bucle largo que se para con el botón de pánico a mitad."""
    nombre = "larga"

    def __init__(self):
        self.vueltas = 0

    def ejecutar(self):
        for _ in range(100):
            if self.vueltas == 3:
                control.detener()       # alguien pulsa el botón a mitad
            control.comprobar()
            self.vueltas += 1
        return Resultado(True, "terminada")


class Router:
    def interpretar(self, texto):
        return Interpretacion(texto, "larga", 0.99, skill="larga")


def _agente(tmp_path, skill):
    return Agente(router=Router(), registro={"larga": skill}, ruta_episodios=tmp_path / "e.jsonl",
                  ruta_bd=tmp_path / "a.db")


def test_el_boton_corta_la_orden_a_mitad(tmp_path):
    skill = Larga()
    r = _agente(tmp_path, skill).procesar("haz algo largo")
    assert not r.ok and r.mensaje == control.MENSAJE and skill.vueltas == 3


def test_en_pausa_no_se_acepta_nada_nuevo(tmp_path):
    skill = Larga()
    control.detener()
    r = _agente(tmp_path, skill).procesar("haz algo largo")
    assert not r.ok and "pausa" in r.mensaje and skill.vueltas == 0
    control.reanudar()
    skill.vueltas = 4   # ya no vuelve a pulsar el botón
    assert _agente(tmp_path, skill).procesar("haz algo largo").ok


def test_en_pausa_las_tareas_programadas_esperan(tmp_path):
    agenda = Agenda(tmp_path / "a.db")
    hechas = []
    planificador = Planificador(agenda, lambda t: (hechas.append(t.id) or True, "ok"))
    agenda.programar("algo", datetime.now() - timedelta(seconds=1), {}, "x")
    control.detener()
    planificador.revisar()
    assert hechas == [] and len(agenda.pendientes()) == 1
    control.reanudar()
    planificador.revisar()
    assert len(hechas) == 1


def test_programar_con_tiempo_explicito(tmp_path):
    agente = _agente(tmp_path, Larga())
    interp = agente.interpretar("haz algo largo", programar_en=timedelta(minutes=2, seconds=30))
    assert interp.programada and "2 min 30 s" in interp.programada["expresion"]
    assert interp.programada["cuando"] > datetime.now() + timedelta(minutes=2)
