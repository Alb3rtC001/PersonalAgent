"""
Tests de escribir_texto, pulsar_teclas y el contexto "última aplicación".
No tocan Windows: la ventana, el foco y el teclado son falsos.

    python -m pytest tests
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.skills.teclado as mod  # noqa: E402
from core.agente import Agente  # noqa: E402
from core.llm import InterpreteLLM  # noqa: E402
from core.router import Interpretacion  # noqa: E402
from core.skills.base import Resultado, Skill  # noqa: E402
from core.skills.teclado import EscribirTexto, PulsarTeclas  # noqa: E402
from core.teclado import ErrorTeclas, interpretar_teclas, limpiar_texto_a_escribir  # noqa: E402

ENTER, TAB, CTRL, SHIFT, ESC, ABAJO = 0x0D, 0x09, 0x11, 0x10, 0x1B, 0x28


# --- Intérprete de teclas -------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("enter", [(ENTER,)]),
    ("intro", [(ENTER,)]),
    ("control s", [(CTRL, ord("S"))]),
    ("ctrl+s", [(CTRL, ord("S"))]),
    ("tab tab enter", [(TAB,), (TAB,), (ENTER,)]),
    ("tab y enter", [(TAB,), (ENTER,)]),
    ("control y", [(CTRL, ord("Y"))]),          # aquí "y" es la letra, no un conector
    ("tab 3 veces", [(TAB,)] * 3),
    ("tab dos veces", [(TAB,)] * 2),
    ("la flecha abajo", [(ABAJO,)]),
    ("control mayúsculas esc", [(CTRL, SHIFT, ESC)]),
])
def test_interpretar_teclas(texto, esperado):
    assert interpretar_teclas(texto) == esperado


@pytest.mark.parametrize("texto", ["", "abracadabra", "tab 50 veces", "3 veces"])
def test_interpretar_teclas_rechaza_lo_que_no_entiende(texto):
    with pytest.raises(ErrorTeclas):
        interpretar_teclas(texto)


def test_el_texto_nunca_lleva_saltos_de_linea():
    # Un salto de línea sería un Enter (enviar): para eso está pulsar_teclas.
    assert limpiar_texto_a_escribir("hola\nque tal\r\n") == "hola que tal "


# --- Skills ---------------------------------------------------------------

@pytest.fixture
def pantalla(monkeypatch):
    estado = {"ventana": {"hwnd": 7, "titulo": "Calculadora", "oculta": False, "minimizada": False},
              "foco_ok": True, "foco": 7, "escrito": [], "pulsado": []}
    monkeypatch.setattr(mod, "elegir_ventana", lambda nombres, app: (estado["ventana"], None))
    monkeypatch.setattr(mod, "poner_foco", lambda hwnd: estado["foco_ok"])
    monkeypatch.setattr(mod, "hwnd_activo", lambda: estado["foco"])
    monkeypatch.setattr(mod, "escribir", lambda texto: estado["escrito"].append(texto) or len(texto))
    monkeypatch.setattr(mod, "pulsar", lambda c: estado["pulsado"].append(c) or True)
    # Sin UI Automation real: la ventana entera recibe el teclado y no se puede leer.
    monkeypatch.setattr(mod, "preparar_campo", lambda hwnd, campo: (None, None, None))
    monkeypatch.setattr(mod, "comprobar_escrito", lambda c, t, exacto=False: None)
    return estado


def _skill(clase):
    s = clase()
    s._apps = []   # sin consultar el menú Inicio
    return s


def test_escribir_texto(pantalla):
    s = _skill(EscribirTexto)
    r = s.ejecutar(texto="2+2", aplicacion="calculadora")
    assert r.ok and s.verificar(r) and pantalla["escrito"] == ["2+2"]


def test_no_escribe_si_no_consigue_el_foco(pantalla):
    pantalla["foco_ok"] = False
    r = _skill(EscribirTexto).ejecutar(texto="2+2", aplicacion="calculadora")
    assert not r.ok and pantalla["escrito"] == []


def test_no_escribe_si_la_app_no_esta_abierta(pantalla):
    pantalla["ventana"] = None
    r = _skill(EscribirTexto).ejecutar(texto="hola", aplicacion="discord")
    assert not r.ok and "No encuentro" in r.mensaje and pantalla["escrito"] == []


def test_escribir_detecta_cambio_de_foco(pantalla):
    s = _skill(EscribirTexto)
    r = s.ejecutar(texto="hola", aplicacion="calculadora")
    pantalla["foco"] = 99   # el usuario hizo clic en otra ventana mientras escribía
    assert r.ok and not s.verificar(r) and "foco" in r.datos["motivo_verificacion"]


def test_pulsar_teclas(pantalla):
    s = _skill(PulsarTeclas)
    r = s.ejecutar(teclas="control s", aplicacion="bloc de notas")
    assert r.ok and s.verificar(r) and pantalla["pulsado"] == [(CTRL, ord("S"))]


def test_pulsar_teclas_desconocidas_no_toca_nada(pantalla):
    r = _skill(PulsarTeclas).ejecutar(teclas="la tecla mágica", aplicacion="x")
    assert not r.ok and pantalla["pulsado"] == []


def test_pulsar_pide_confirmacion_si_lo_interpreta_el_llm():
    assert PulsarTeclas.confirmar_si_llm and not EscribirTexto.confirmar_si_llm


# --- LLM: el texto y las teclas deben ser literales -------------------------

def test_llm_no_puede_reformular_el_texto_a_escribir():
    llm = InterpreteLLM({"escribir_texto": EscribirTexto()}, servidor=object(), ejemplos=[], memoria=False)
    r = llm.validar({"skill": "escribir_texto", "parametros": {
        "texto": "Hola, ¿cómo estás? Espero que bien"}}, "escribe hola que tal")
    assert r.skill is None
    r = llm.validar({"skill": "escribir_texto", "parametros": {"texto": "hola que tal",
                                                                "aplicacion": "discord"}},
                    "escribe hola que tal en discord")
    assert r.skill == "escribir_texto" and r.params == {"texto": "hola que tal", "aplicacion": "discord"}


# --- Contexto: la última aplicación ---------------------------------------

class Abrir(Skill):
    nombre = "abrir_aplicacion"
    parametros = {"aplicacion": "app"}

    def ejecutar(self, aplicacion=""):
        return Resultado(True, "abierta", datos={"aplicacion": "Calculadora"})  # nombre real


class Escribir(Skill):
    nombre = "escribir_texto"
    parametros = {"texto": "t", "aplicacion": "app"}
    del_contexto = {"aplicacion": "ultima_aplicacion"}

    def __init__(self):
        self.recibido = None

    def ejecutar(self, texto="", aplicacion=""):
        self.recibido = aplicacion
        return Resultado(True, "escrito", datos={"aplicacion": aplicacion})


class Cerrar(Skill):
    nombre = "cerrar_aplicacion"
    parametros = {"aplicacion": "app"}

    def ejecutar(self, aplicacion=""):
        return Resultado(True, "cerrada", datos={"aplicacion": aplicacion})


def _agente(tmp_path):
    escribir = Escribir()
    registro = {"abrir_aplicacion": Abrir(), "escribir_texto": escribir, "cerrar_aplicacion": Cerrar()}
    return Agente(router=object(), registro=registro, ruta_episodios=tmp_path / "e.jsonl"), escribir


def _orden(skill, params):
    return Interpretacion("frase", skill, 0.99, skill=skill, params=params)


def test_escribe_en_la_ultima_aplicacion_usada(tmp_path):
    agente, escribir = _agente(tmp_path)
    agente.ejecutar(_orden("abrir_aplicacion", {"aplicacion": "calcu"}), {"aplicacion": "calcu"})
    r = agente.ejecutar(_orden("escribir_texto", {"texto": "2+2"}), {"texto": "2+2"})
    assert r.ok and escribir.recibido == "Calculadora" and "la última usada" in r.mensaje


def test_sin_contexto_pregunta_la_aplicacion(tmp_path):
    agente, _ = _agente(tmp_path)
    r = agente.ejecutar(_orden("escribir_texto", {"texto": "2+2"}), {"texto": "2+2"})
    assert not r.ok and r.falta == "aplicacion"


def test_cerrar_la_app_la_olvida(tmp_path):
    agente, _ = _agente(tmp_path)
    agente.ejecutar(_orden("abrir_aplicacion", {"aplicacion": "calculadora"}), {"aplicacion": "calculadora"})
    agente.ejecutar(_orden("cerrar_aplicacion", {"aplicacion": "calculadora"}), {"aplicacion": "calculadora"})
    r = agente.ejecutar(_orden("escribir_texto", {"texto": "2+2"}), {"texto": "2+2"})
    assert r.falta == "aplicacion"


def test_la_app_dicha_gana_al_contexto(tmp_path):
    agente, escribir = _agente(tmp_path)
    agente.ejecutar(_orden("abrir_aplicacion", {"aplicacion": "calculadora"}), {"aplicacion": "calculadora"})
    agente.ejecutar(_orden("escribir_texto", {"texto": "hola", "aplicacion": "discord"}),
                    {"texto": "hola", "aplicacion": "discord"})
    assert escribir.recibido == "discord"
