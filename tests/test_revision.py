"""
Tests de los fallos encontrados en la revisión general (bugs y rendimiento).

    python -m pytest tests
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.skills.abrir_aplicacion as abrir  # noqa: E402
import core.skills.steam as steam  # noqa: E402
import core.skills.ventanas as ventanas  # noqa: E402
from core.atajos import plan_incompleto  # noqa: E402
from core.tiempo import separar_tiempo  # noqa: E402


def _v(titulo, proceso, hwnd, oculta=False):
    return {"titulo": titulo, "proceso": proceso, "hwnd": hwnd, "pid": hwnd, "oculta": oculta,
            "minimizada": False}


# --- Una pestaña que nombra una app no es la app ---------------------------------------

VENTANAS = [
    _v("Steam Store - Ofertas - Opera", "opera.exe", 1),
    _v("calculadora online - Google Chrome", "chrome.exe", 2),
    _v("Lista de amigos", "steamwebhelper.exe", 3),
]


@pytest.fixture
def ventanas_falsas(monkeypatch):
    lista = list(VENTANAS)
    monkeypatch.setattr(ventanas, "listar_ventanas_abiertas", lambda incluir_ocultas=True: lista)
    return lista


def test_una_pestana_que_habla_de_steam_no_es_steam(ventanas_falsas):
    # Antes: el título contenía "steam" → "Steam ya está abierta" y traía Opera al frente.
    ventanas_falsas.remove(VENTANAS[2])
    assert ventanas.ventanas_de(["steam"]) == []
    assert ventanas.ventanas_de(["calculadora"]) == []


def test_si_no_hay_coincidencia_estricta_vale_el_proceso(ventanas_falsas):
    assert [v["hwnd"] for v in ventanas.ventanas_de(["steam"])] == [3]      # steamwebhelper.exe


def test_la_estricta_va_primero(ventanas_falsas):
    ventanas_falsas.append(_v("Steam", "steamwebhelper.exe", 4))
    assert [v["hwnd"] for v in ventanas.ventanas_de(["Steam"])] == [4]


def test_restaurar_admite_parte_del_titulo(ventanas_falsas):
    assert [v["hwnd"] for v in ventanas.ventanas_de(["ofertas"], por_titulo=True)] == [1]
    assert ventanas.ventanas_de(["ofertas"]) == []


# --- Plan que se queda en Ctrl+L sin escribir nada ---------------------------------------

ATAJOS = {"Google Chrome": {"nombres": ["chrome", "google"], "atajos": {
    "ir a la barra de direcciones (para buscar en Google: después escribir la búsqueda y pulsar enter)":
        "control l"}}}


def test_plan_incompleto():
    solo_barra = [("pulsar_teclas", {"teclas": "control l", "aplicacion": "google"})]
    assert plan_incompleto(solo_barra, "busca recetas de lentejas en google", ATAJOS)
    completo = solo_barra + [("escribir_texto", {"texto": "recetas"}), ("pulsar_teclas", {"teclas": "enter"})]
    assert plan_incompleto(completo, "busca recetas de lentejas en google", ATAJOS) is None
    # "ve a la barra de direcciones" sin nada que buscar: el plan de un paso es correcto.
    assert plan_incompleto(solo_barra, "selecciona la barra de direcciones de chrome", ATAJOS) is None


# --- "A las 12 de la noche" no es mediodía ------------------------------------------------

AHORA = datetime(2026, 11, 19, 18, 0)


@pytest.mark.parametrize("frase, esperado", [
    ("cierra steam a las 12 de la noche", datetime(2026, 11, 20, 0, 0)),
    ("abre steam a las 12 de la madrugada", datetime(2026, 11, 20, 0, 0)),
    ("abre steam a las 12 y media de la noche", datetime(2026, 11, 20, 0, 30)),
    ("abre steam mañana a las 12 de la noche", datetime(2026, 11, 21, 0, 0)),
    ("abre steam a las 11 de la noche", datetime(2026, 11, 19, 23, 0)),
    ("abre steam a las 12 del mediodia", datetime(2026, 11, 20, 12, 0)),
])
def test_medianoche(frase, esperado):
    assert separar_tiempo(frase, AHORA)[1] == esperado


# --- Un juego no es otro que empieza igual ------------------------------------------------

def test_proceso_de_otro_juego_con_el_mismo_principio(tmp_path, monkeypatch):
    comun = tmp_path / "steamapps" / "common"
    (comun / "Slay the Spire").mkdir(parents=True)
    (comun / "Slay the Spire 2").mkdir()
    exe_del_2 = str(comun / "Slay the Spire 2" / "SlayTheSpire2.exe")

    class P:
        info = {"pid": 42, "exe": exe_del_2}
    monkeypatch.setattr(steam.psutil, "process_iter", lambda campos: [P()])

    def juego(carpeta):
        return steam.Juego("1", carpeta.name, carpeta, 0, "", "", 0)
    assert steam._proceso_del_juego(juego(comun / "Slay the Spire")) is None
    assert steam._proceso_del_juego(juego(comun / "Slay the Spire 2")) == 42
    assert steam._proceso_del_juego(juego(comun)) is None       # installdir vacío


# --- La lista de apps del menú Inicio se consulta una vez para todas las skills ------------

def test_apps_instaladas_compartidas(monkeypatch):
    llamadas = []
    monkeypatch.setattr(abrir, "_apps_cache", None)
    monkeypatch.setattr(abrir, "listar_apps_instaladas",
                        lambda: llamadas.append(1) or [abrir.AppInstalada("Steam", "x")])
    assert abrir.apps_instaladas()[0].nombre == "Steam"
    abrir.apps_instaladas()
    abrir.AbrirAplicacion()._indice()
    assert len(llamadas) == 1
    abrir.apps_instaladas(refrescar=True)
    assert len(llamadas) == 2


def test_apps_instaladas_si_falla_no_se_queda_vacia_para_siempre(monkeypatch):
    monkeypatch.setattr(abrir, "_apps_cache", None)

    def falla():
        raise OSError("powershell no responde")
    monkeypatch.setattr(abrir, "listar_apps_instaladas", falla)
    assert abrir.apps_instaladas() == []
    monkeypatch.setattr(abrir, "listar_apps_instaladas", lambda: [abrir.AppInstalada("Steam", "x")])
    assert len(abrir.apps_instaladas()) == 1          # se reintenta


def test_el_agente_precarga_las_skills(monkeypatch):
    from core.agente import Agente
    precargadas = []

    class Skill:
        nombre = "x"

        def precargar(self):
            precargadas.append(self.nombre)

    class Router:
        def interpretar(self, texto):
            pass
    agente = Agente(router=Router(), registro={"x": Skill()})
    agente._precargar_skills()
    assert precargadas == ["x"]


# --- Una ventana del propio agente no es la app recién abierta -------------------------

def test_abrir_no_cuenta_el_aviso_del_agente_como_la_app(monkeypatch):
    import os
    nuevas = {"propia": 900}                          # el aviso "el agente está actuando"
    monkeypatch.setattr(abrir, "_ventanas_de", lambda nombres: [])
    monkeypatch.setattr(abrir, "handles_ventanas", lambda: {1, 2, nuevas["propia"]})
    monkeypatch.setattr(abrir, "_pid", lambda h: os.getpid() if h == 900 else 1234)
    monkeypatch.setattr(abrir.time, "sleep", lambda s: None)
    skill = abrir.AbrirAplicacion(espera_max=0.05)
    r = abrir.Resultado(True, "abierta", datos={"aplicacion": "Calculadora", "nombres": ["Calculadora"],
                                                "ventanas_antes": [1, 2]})
    assert not skill.verificar(r) and "no apareció" in r.datos["motivo_verificacion"]
    # Una ventana nueva de otro programa (el Explorador con su carpeta) sí cuenta.
    monkeypatch.setattr(abrir, "handles_ventanas", lambda: {1, 2, 900, 777})
    assert skill.verificar(abrir.Resultado(True, "abierta", datos={
        "aplicacion": "Explorador", "nombres": ["Explorador"], "ventanas_antes": [1, 2]}))


def test_abrir_solo_cuenta_ventanas_de_lo_lanzado(monkeypatch):
    import psutil
    lanzada = 1000.0
    procesos = {1: ("notificaciones.exe", 500.0),    # ya estaba en marcha: una notificación
                2: ("explorer.exe", 10.0),            # el Explorador reutiliza su proceso
                3: ("nuevaapp.exe", 1001.5)}          # arrancado por la orden

    class P:
        def __init__(self, pid):
            self.pid = pid

        def name(self):
            return procesos[self.pid][0]

        def create_time(self):
            return procesos[self.pid][1]
    monkeypatch.setattr(psutil, "Process", P)
    monkeypatch.setattr(abrir, "_pid", lambda h: h)
    assert not abrir._de_lo_lanzado(1, lanzada)
    assert abrir._de_lo_lanzado(2, lanzada)
    assert abrir._de_lo_lanzado(3, lanzada)


# --- Apps nuevas: sus controles como contexto para el LLM -------------------------------

import core.controles_app as controles_app  # noqa: E402

VLC = {"titulo": "concierto.mp4 - VLC media player", "proceso": "vlc.exe", "hwnd": 10, "pid": 10,
       "oculta": False, "minimizada": False}
OBS = {"titulo": "OBS 30.2 - Perfil: Sin título", "proceso": "obs64.exe", "hwnd": 11, "pid": 11,
       "oculta": False, "minimizada": False}


def test_nombres_de_ventana():
    assert {"vlc", "vlc media player"} <= controles_app.nombres_de_ventana(VLC)
    assert "obs64" in controles_app.nombres_de_ventana(OBS)


def test_ventana_nombrada():
    assert controles_app.ventana_nombrada("en vlc dale a pausa", [OBS, VLC]) is VLC
    assert controles_app.ventana_nombrada("pon el volumen al máximo", [OBS, VLC]) is None
    oculta = dict(VLC, oculta=True)
    assert controles_app.ventana_nombrada("en vlc dale a pausa", [oculta]) is None


@pytest.fixture
def pantalla_vlc(monkeypatch):
    monkeypatch.setattr(controles_app, "listar_ventanas_abiertas", lambda: [OBS, VLC])
    monkeypatch.setattr(controles_app, "leer_controles",
                        lambda v: (["Reproducir", "Pausa", "Detener"], ["Volumen"]) if v is VLC else ([], []))


def test_contexto_de_app_nueva(pantalla_vlc):
    bloque, nombres = controles_app.contexto_app_nueva("en vlc dale a pausa", None, lambda n: False)
    assert "'Pausa'" in bloque and "'Volumen'" in bloque and "VLC media player" in bloque
    assert {"pausa", "volumen", "detener"} <= nombres


def test_app_conocida_no_se_lee(pantalla_vlc):
    # Si está en atajos_apps.json, el LLM ya tiene sus botones: no se lee la pantalla.
    assert controles_app.contexto_app_nueva("en vlc dale a pausa", None, lambda n: n == "vlc") == ("", set())


def test_la_ultima_app_usada_cuenta(pantalla_vlc):
    bloque, _ = controles_app.contexto_app_nueva("dale a pausa", "VLC media player", lambda n: False)
    assert "'Pausa'" in bloque


def test_el_llm_recibe_los_controles_y_los_acepta_como_valores():
    from core.llm import InterpreteLLM
    from core.registro import REGISTRO
    llm = InterpreteLLM(REGISTRO, servidor=object(), ejemplos=[], atajos={}, memoria=False,
                        controles_apps=lambda texto, ultima, conocida: ("Controles: 'Pausa'", {"pausa"}))
    texto, conocidos = llm._contexto("en vlc dale a pausa", None)
    assert "'Pausa'" in texto and "pausa" in conocidos
    # Sin la función (tests, evaluación) el prompt no depende de la pantalla.
    assert InterpreteLLM(REGISTRO, servidor=object(), ejemplos=[], atajos={}, memoria=False
                         )._contexto("en vlc dale a pausa", None) == ("", set())


def test_si_no_sabe_hacerlo_propone_ensenarselo():
    from core.llm import NO_SE_HACER, ResultadoLLM
    from core.router import Router

    class LLM:
        def interpretar(self, texto, contexto=None):
            return ResultadoLLM(None, motivo=NO_SE_HACER)
    router = Router(clasificador=lambda t: ("ninguna", 0.2, []), llm=LLM(), usar_llm=True)
    assert "grabar" in router.interpretar("haz algo raro").motivo_rechazo
