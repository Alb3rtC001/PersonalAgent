"""
Tests de cerrar_aplicacion. No tocan Windows: las ventanas son un
diccionario y cada test decide cómo reacciona la app a la X (WM_CLOSE).

    python -m pytest tests
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.skills.cerrar_aplicacion as mod  # noqa: E402
from core.estado import EstadoMundo  # noqa: E402
from core.planner import planificar  # noqa: E402
from core.skills.abrir_aplicacion import AbrirAplicacion  # noqa: E402
from core.skills.cerrar_aplicacion import CerrarAplicacion, ventana_de_app  # noqa: E402
from core.skills.restaurar_ventana import RestaurarVentana  # noqa: E402


def _v(titulo, proceso, hwnd, pid=1000):
    return {"titulo": titulo, "proceso": proceso, "hwnd": hwnd, "pid": pid}


# --- Qué ventanas son de la app -----------------------------------------

def test_ventana_de_app_coincidencia_estricta():
    assert ventana_de_app(_v("#general | Server - Discord", "Discord.exe", 1), ["discord"])
    assert ventana_de_app(_v("Calculadora", "ApplicationFrameHost.exe", 2), ["calculadora"])
    assert ventana_de_app(_v("Steam", "steamwebhelper.exe", 3), ["steam"])
    assert ventana_de_app(_v("README.md - Proyecto - Visual Studio Code", "Code.exe", 4),
                          ["visual studio code"])
    assert ventana_de_app(_v("Google - Google Chrome", "chrome.exe", 5), ["navegador", "Google Chrome"])
    # Una pestaña del navegador que habla de la app NO es la app.
    assert not ventana_de_app(_v("Discord - Google Chrome", "chrome.exe", 6), ["discord"])
    assert not ventana_de_app(_v("Calculadora online - Opera", "opera.exe", 7), ["calculadora"])


# --- Comportamiento de la skill -----------------------------------------

class MundoFalso:
    """Ventanas simuladas: hwnd -> dict con 'existe' y 'mostrada'."""

    def __init__(self, ventanas, al_cerrar):
        self.ventanas = {v["hwnd"]: {**v, "existe": True, "mostrada": not v.get("oculta")} for v in ventanas}
        self.al_cerrar = al_cerrar   # "cierra" | "pregunta" | "bandeja"
        self.terminados = None

    def listar(self, incluir_ocultas=False):
        return [{**v, "oculta": not v["mostrada"]} for v in self.ventanas.values() if v["existe"]]

    def pedir_cierre(self, hwnd):
        v = self.ventanas[hwnd]
        if self.al_cerrar == "cierra":
            v["existe"] = False
        elif self.al_cerrar == "bandeja":
            v["mostrada"] = False
        # "pregunta": la ventana sigue ahí, visible
        return True

    def terminar(self, pids, propios):
        self.terminados = pids
        for v in self.ventanas.values():
            if v["pid"] in pids:
                v["existe"] = False
        return ["App.exe"]


@pytest.fixture
def mundo(monkeypatch):
    def crear(ventanas, al_cerrar):
        m = MundoFalso(ventanas, al_cerrar)
        monkeypatch.setattr(mod, "listar_ventanas_abiertas", m.listar)
        monkeypatch.setattr(mod, "pedir_cierre", m.pedir_cierre)
        monkeypatch.setattr(mod, "ventana_existe", lambda h: m.ventanas[h]["existe"])
        monkeypatch.setattr(mod, "ventana_mostrada",
                            lambda h: m.ventanas[h]["existe"] and m.ventanas[h]["mostrada"])
        monkeypatch.setattr(mod, "_terminar_procesos", m.terminar)
        monkeypatch.setattr(mod, "_pids_propios", lambda: {1})
        monkeypatch.setattr(mod, "GRACIA_OCULTA", 0)
        return m
    return crear


def _skill():
    s = CerrarAplicacion(espera_max=0.5)
    s._apps = []  # sin consultar el menú Inicio
    return s


def _cerrar(skill, app):
    r = skill.ejecutar(aplicacion=app)
    return r, r.ok and skill.verificar(r)


def test_no_estaba_abierta(mundo):
    mundo([], "cierra")
    r, verificado = _cerrar(_skill(), "discord")
    assert verificado and r.datos["no_estaba"]


def test_cierra_la_app(mundo):
    m = mundo([_v("Calculadora", "ApplicationFrameHost.exe", 10),
               _v("Discord", "Discord.exe", 11)], "cierra")
    r, verificado = _cerrar(_skill(), "calculadora")
    assert verificado and "cerrada" in r.mensaje
    assert m.ventanas[11]["existe"]  # Discord no se toca


def test_no_fuerza_si_pregunta_guardar(mundo):
    m = mundo([_v("Sin título - Bloc de notas", "Notepad.exe", 20, pid=500)], "pregunta")
    r, _ = _cerrar(_skill(), "bloc de notas")
    assert not r.ok and "sigue abierta" in r.mensaje
    assert m.terminados is None


def test_app_en_bandeja_termina_su_proceso(mundo):
    m = mundo([_v("Discord", "Discord.exe", 30, pid=700)], "bandeja")
    r, verificado = _cerrar(_skill(), "discord")
    assert verificado and m.terminados == {700}


def test_app_en_bandeja_sin_terminar_si_esta_desactivado(mundo):
    m = mundo([_v("Discord", "Discord.exe", 30, pid=700)], "bandeja")
    skill = _skill()
    skill.terminar_en_bandeja = False
    r, verificado = _cerrar(skill, "discord")
    assert verificado and r.datos["en_bandeja"] and m.terminados is None


def test_no_se_cierra_a_si_mismo(mundo):
    m = mundo([_v("Windows PowerShell", "powershell.exe", 40, pid=1)], "cierra")
    r, _ = _cerrar(_skill(), "powershell")
    assert not r.ok and m.ventanas[40]["existe"]


# --- Planificador -------------------------------------------------------

def test_planificador_no_cierra_apps_para_restaurar_una_visible():
    registro = {s.nombre: s for s in [AbrirAplicacion(), CerrarAplicacion(), RestaurarVentana()]}
    estado = EstadoMundo(consulta=lambda h: {"abierta:steam": True, "visible:steam": True}.get(h, False))
    plan = planificar("restaurar_ventana", {"aplicacion": "steam"}, estado, registro)
    assert plan is None or all(p.skill != "cerrar_aplicacion" for p in plan)
