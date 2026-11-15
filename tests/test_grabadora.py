"""
Tests de la grabadora semántica y de las skills grabadas. Sin Windows: UI
Automation, las ventanas, el ratón y el teclado son falsos.

    python -m pytest tests
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.skills.grabada as grabada  # noqa: E402
import recorder.grabadora_semantica as gs  # noqa: E402
from core.skills.grabada import SkillGrabada, cargar_skills_grabadas, guardar_grabacion, nombre_valido  # noqa: E402
from recorder.grabadora_semantica import GrabadoraSemantica, marcar_parametro, textos_grabados  # noqa: E402

pynput = pytest.importorskip("pynput")
from pynput.keyboard import Key, KeyCode  # noqa: E402

CALC = {"titulo": "Calculadora", "proceso": "ApplicationFrameHost.exe", "pid": 500, "rect": [0, 0, 100, 100]}
BOTON = {"nombre": "Siete", "tipo": "ButtonControl", "id": "num7Button", "clase": "Button",
         "contrasena": False, "rect": [10, 10, 20, 20]}
CAMPO = {"nombre": "Buscar", "tipo": "EditControl", "id": "q", "clase": "Edit", "contrasena": False, "rect": [0, 0, 1, 1]}


def _eventos(grabadora):
    salida = []
    while not grabadora._cola.empty():
        salida.append(grabadora._cola.get())
    return salida


# --- Teclado: qué se graba ------------------------------------------------------------------

def test_teclas_a_eventos():
    g = GrabadoraSemantica(pids_ignorados=set())
    for tecla in (KeyCode.from_char("h"), KeyCode.from_char("i"), Key.space, Key.backspace):
        g._al_bajar(tecla)
    g._al_bajar(Key.ctrl_l); g._al_bajar(KeyCode(vk=83)); g._al_soltar(Key.ctrl_l)              # control s
    g._al_bajar(Key.ctrl_l); g._al_bajar(Key.alt_gr); g._al_bajar(KeyCode.from_char("@"))      # AltGr+2 = @
    g._al_soltar(Key.alt_gr); g._al_soltar(Key.ctrl_l)
    g._al_bajar(Key.enter)
    assert _eventos(g) == [("texto", "h"), ("texto", "i"), ("texto", " "), ("borrar",),
                           ("teclas", "control s"), ("texto", "@"), ("teclas", "enter")]
    g._al_bajar(Key.f9)
    assert g.esperar_fin(0)


# --- Procesado con UI Automation (falsa) ------------------------------------------------------

@pytest.fixture
def uia_falsa(monkeypatch):
    estado = {"en_punto": (BOTON, CALC), "foco": (CAMPO, CALC)}
    monkeypatch.setattr(gs.uia, "control_en", lambda x, y: estado["en_punto"])
    monkeypatch.setattr(gs.uia, "control_con_foco", lambda: estado["foco"])
    return estado


def test_graba_controles_y_texto(uia_falsa):
    g = GrabadoraSemantica(pids_ignorados=set())
    for evento in [("clic", 15, 15, "left", 0), ("texto", "q"), ("texto", "u"), ("texto", "e"),
                   ("texto", "e"), ("texto", "n"), ("teclas", "enter"), ("fin_texto",)]:
        g._tratar(evento)
    tipos = [p["tipo"] for p in g.pasos]
    assert tipos == ["clic", "escribir", "teclas"]
    assert g.pasos[0]["control"]["id"] == "num7Button" and g.pasos[0]["relativo"] == [0.15, 0.15]
    assert g.pasos[1]["texto"] == "queen" and g.pasos[1]["control"]["nombre"] == "Buscar"


def test_no_graba_contrasenas(uia_falsa):
    uia_falsa["foco"] = ({**CAMPO, "contrasena": True}, CALC)
    g = GrabadoraSemantica(pids_ignorados=set())
    for letra in "secreto123":
        g._tratar(("texto", letra))
    g._tratar(("fin_texto",))
    assert [p["tipo"] for p in g.pasos] == ["contrasena_omitida"]
    assert "secreto" not in json.dumps(g.pasos) and g.avisos


def test_no_graba_ventanas_prohibidas_ni_la_propia(uia_falsa):
    uia_falsa["en_punto"] = (BOTON, {**CALC, "titulo": "Windows PowerShell", "proceso": "powershell.exe"})
    g = GrabadoraSemantica(pids_ignorados=set())
    g._tratar(("clic", 1, 1, "left", 0))
    uia_falsa["en_punto"] = (BOTON, {**CALC, "pid": 999})
    g2 = GrabadoraSemantica(pids_ignorados={999})   # la consola o la interfaz del agente
    g2._tratar(("clic", 1, 1, "left", 0))
    assert g.pasos == [] and g.avisos and g2.pasos == []


# --- Parámetro, guardar y cargar ---------------------------------------------------------------

PASOS = [{"tipo": "clic", "boton": "left", "control": CAMPO, "ventana": {"titulo": "Spotify", "proceso": "Spotify.exe"},
          "relativo": [0.5, 0.1]},
         {"tipo": "escribir", "texto": "queen", "control": CAMPO, "ventana": {"titulo": "Spotify", "proceso": "Spotify.exe"}},
         {"tipo": "teclas", "teclas": "enter", "ventana": {"titulo": "Spotify", "proceso": "Spotify.exe"}}]


def test_parametro_guardar_y_cargar(tmp_path):
    assert textos_grabados(PASOS) == [(1, "queen")]
    pasos = marcar_parametro(PASOS, 1, "cancion")
    assert pasos[1]["texto"] == "{cancion}" and pasos[1]["ejemplo"] == "queen" and PASOS[1]["texto"] == "queen"
    guardar_grabacion("Buscar en Spotify", "Busca una canción", pasos, {"cancion": "La canción"}, ruta=tmp_path)
    skill = cargar_skills_grabadas(tmp_path)[0]
    assert skill.nombre == "buscar_en_spotify" and skill.parametros == {"cancion": "La canción"}
    assert skill.riesgo == "alto" and "cancion" in skill.parametros_literales
    assert nombre_valido("Abrir Página Ñ") == "abrir_pagina_n"


# --- Reproducir ------------------------------------------------------------------------------

@pytest.fixture
def pantalla(monkeypatch):
    hecho = []
    ventana = {"titulo": "Spotify", "proceso": "Spotify.exe", "hwnd": 7,
               "rect": {"left": 0, "top": 0, "right": 100, "bottom": 100}}
    monkeypatch.setattr(grabada, "localizar_ventana", lambda d: ventana)
    monkeypatch.setattr(grabada, "poner_foco", lambda hwnd: True)
    monkeypatch.setattr(grabada.uia, "buscar_control", lambda hwnd, d, espera=3.0: type("C", (), {"SetFocus": lambda s: None})())
    monkeypatch.setattr(grabada.uia, "centro", lambda c: (40, 9))
    monkeypatch.setattr(grabada, "escribir", lambda t: hecho.append(("escribir", t)))
    monkeypatch.setattr(grabada, "pulsar", lambda c: hecho.append(("pulsar", c)))
    monkeypatch.setattr(grabada, "PAUSA_ENTRE_PASOS", 0)
    import pyautogui
    monkeypatch.setattr(pyautogui, "click", lambda x, y, button="left": hecho.append(("clic", x, y)))
    return hecho, ventana


def _skill(pasos):
    return SkillGrabada({"nombre": "buscar_en_spotify", "parametros": {"cancion": "c"}, "pasos": pasos})


def test_reproduce_con_el_parametro(pantalla):
    hecho, _ = pantalla
    r = _skill(marcar_parametro(PASOS, 1, "cancion")).ejecutar(cancion="Bohemian Rhapsody")
    assert r.ok and hecho == [("clic", 40, 9), ("escribir", "Bohemian Rhapsody"), ("pulsar", (0x0D,))]


def test_no_reproduce_en_una_ventana_prohibida(pantalla):
    hecho, ventana = pantalla
    ventana.update(titulo="Banco - Google Chrome", proceso="chrome.exe")
    r = _skill(PASOS).ejecutar(cancion="x")
    assert not r.ok and "prohibidas" in r.mensaje and hecho == []


def test_paso_de_contrasena_hay_que_hacerlo_a_mano(pantalla):
    r = _skill([{"tipo": "contrasena_omitida", "ventana": None}]).ejecutar()
    assert not r.ok and "contraseña" in r.mensaje
