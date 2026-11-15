"""
Tests de seguridad: niveles de riesgo, modo seguro, ventanas prohibidas,
registro de actividad, comandos y las rutas /pausa y /actividad de la API.

    python -m pytest tests
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.skills.teclado as teclado  # noqa: E402
from core import control, seguridad  # noqa: E402
from core.agente import Agente  # noqa: E402
from core.comandos import ejecutar_comando  # noqa: E402
from core.router import Interpretacion  # noqa: E402
from core.seguridad import necesita_confirmacion, ultima_actividad, ventana_prohibida  # noqa: E402
from core.skills.base import Resultado, Skill  # noqa: E402


@pytest.fixture(autouse=True)
def estado_limpio():
    control.reanudar()
    seguridad.activar_modo_seguro(False)
    yield
    control.reanudar()
    seguridad.activar_modo_seguro(False)


def _skill(riesgo, **extra):
    return type("S", (Skill,), {"nombre": "s", "riesgo": riesgo, "ejecutar": lambda self: None, **extra})()


# --- Niveles de riesgo y modo seguro -----------------------------------------------------

@pytest.mark.parametrize("riesgo, origen, esperado", [
    ("lectura", "llm", False), ("bajo", "llm", False), ("bajo", "clasificador", False),
    ("medio", "llm", True), ("medio", "clasificador", False),
    ("alto", "clasificador", True), ("alto", "llm", True),
])
def test_politica_por_riesgo(riesgo, origen, esperado):
    assert necesita_confirmacion(_skill(riesgo), origen) is esperado


def test_irreversible_siempre_y_modo_seguro():
    assert necesita_confirmacion(_skill("bajo", requiere_confirmacion=True), "clasificador")
    seguridad.activar_modo_seguro(True)
    assert necesita_confirmacion(_skill("bajo"), "clasificador")
    assert not necesita_confirmacion(_skill("lectura"), "llm")   # la lectura nunca


# --- Ventanas prohibidas --------------------------------------------------------------------

@pytest.mark.parametrize("ventana, prohibida", [
    ({"titulo": "Contraseñas - KeePass", "proceso": "KeePass.exe"}, True),
    ({"titulo": "Windows PowerShell", "proceso": "powershell.exe"}, True),
    ({"titulo": "Banco Santander - Google Chrome", "proceso": "chrome.exe"}, True),
    ({"titulo": "Calculadora", "proceso": "ApplicationFrameHost.exe"}, False),
    ({"titulo": "#general - Discord", "proceso": "Discord.exe"}, False),
])
def test_ventanas_prohibidas(ventana, prohibida):
    assert bool(ventana_prohibida(ventana)) is prohibida


def test_el_teclado_no_escribe_en_una_ventana_prohibida(monkeypatch):
    escrito = []
    monkeypatch.setattr(teclado, "elegir_ventana",
                        lambda nombres, app: ({"hwnd": 1, "titulo": "Windows PowerShell", "proceso": "powershell.exe",
                                               "oculta": False, "minimizada": False}, None))
    monkeypatch.setattr(teclado, "poner_foco", lambda hwnd: True)
    monkeypatch.setattr(teclado, "escribir", lambda t: escrito.append(t) or len(t))
    skill = teclado.EscribirTexto()
    skill._apps = []
    r = skill.ejecutar(texto="del *.*", aplicacion="powershell")
    assert not r.ok and "prohibidas" in r.mensaje and escrito == []
    assert "Bloqueado" in ultima_actividad(1)[0]


# --- Registro de actividad -------------------------------------------------------------------

class Abrir(Skill):
    nombre = "abrir_aplicacion"
    parametros = {"aplicacion": "app"}

    def ejecutar(self, aplicacion=""):
        return Resultado(True, f"'{aplicacion}' abierta")


class Router:
    def interpretar(self, texto):
        if texto.startswith("abre "):
            return Interpretacion(texto, "abrir_aplicacion", 0.99, skill="abrir_aplicacion",
                                  params={"aplicacion": texto[5:]})
        return Interpretacion(texto, "ninguna", 0.5, motivo_rechazo="No he entendido esa orden.")


def test_cada_orden_queda_en_el_registro_con_quien_la_pidio(tmp_path):
    agente = Agente(router=Router(), registro={"abrir_aplicacion": Abrir()}, canal="interfaz",
                    ruta_episodios=tmp_path / "e.jsonl", ruta_bd=tmp_path / "a.db")
    agente.procesar("abre la calculadora")
    agente.procesar("qué tiempo hace")
    lineas = ultima_actividad(2)
    assert "| interfaz  | ✔ «abre la calculadora» [abrir_aplicacion]" in lineas[0]
    assert "✘ «qué tiempo hace» no entendida" in lineas[1]


# --- Comandos -------------------------------------------------------------------------------

class AgenteFalso:
    def estado_llm(self):
        return {"activo": False, "cargado": False, "modelo": None, "gpu": None}


def test_comandos():
    agente = AgenteFalso()
    assert "ACTIVADO" in ejecutar_comando(agente, "seguro on") and seguridad.modo_seguro()
    assert "desactivado" in ejecutar_comando(agente, "seguro off") and not seguridad.modo_seguro()
    assert "LLM desactivado" in ejecutar_comando(agente, "llm")
    control.detener()
    assert "reanudado" in ejecutar_comando(agente, "reanudar") and not control.en_pausa()
    assert "Modo seguro" in ejecutar_comando(agente, "actividad")   # lo acaba de registrar
    assert ejecutar_comando(agente, "abre discord") is None          # una orden, no un comando


# --- API --------------------------------------------------------------------------------------

def test_api_pausa_y_actividad(tmp_path):
    from fastapi.testclient import TestClient

    from api.servidor import crear_app
    agente = Agente(router=Router(), registro={"abrir_aplicacion": Abrir()}, canal="api",
                    ruta_episodios=tmp_path / "e.jsonl", ruta_bd=tmp_path / "a.db")
    cliente = TestClient(crear_app(agente=agente, token="t"))
    cliente.headers["X-Token"] = "t"
    assert cliente.post("/pausa", json={"pausa": True}).json() == {"pausa": True}
    r = cliente.post("/ordenes", json={"texto": "abre discord"}).json()
    assert r["estado"] == "fallida" and "pausa" in r["mensaje"]
    assert cliente.post("/pausa", json={"pausa": False}).json() == {"pausa": False}
    assert cliente.post("/ordenes", json={"texto": "abre discord"}).json()["estado"] == "completada"
    assert any("| api" in linea and "abre discord" in linea for linea in cliente.get("/actividad").json())


# --- Atajo global de pánico --------------------------------------------------------------------

def test_atajo_de_panico():
    from pynput.keyboard import Key, KeyCode

    from core.comandos import _nombre_tecla, atajo_legible, teclas_del_atajo
    assert teclas_del_atajo("<ctrl>+<alt>+p") == {"ctrl", "alt", "p"}
    assert atajo_legible("<ctrl>+<alt>+p") == "Ctrl+Alt+P"
    # Con Ctrl pulsado, la P llega como código 80 sin carácter: se reconoce por su código.
    assert [_nombre_tecla(k) for k in (Key.ctrl_l, Key.alt_gr, KeyCode(vk=80), Key.f12)] == \
        ["ctrl", "alt", "p", "f12"]
