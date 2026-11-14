"""
Tests de las órdenes de varios pasos, los atajos por app, la autocorrección
del LLM y las protecciones de la GPU. Sin Windows, sin GPU y sin LLM real.

    python -m pytest tests
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.llm as llm_mod  # noqa: E402
from core.agente import Agente  # noqa: E402
from core.atajos import apps_mencionadas, describir_atajos  # noqa: E402
from core.gpu import EstadoGPU  # noqa: E402
from core.llm import InterpreteLLM, ServidorLLM, construir_mensajes, esquema_ordenes  # noqa: E402
from core.router import VARIOS_PASOS, Interpretacion, Router  # noqa: E402
from core.skills.abrir_aplicacion import AbrirAplicacion  # noqa: E402
from core.skills.base import Resultado, Skill  # noqa: E402
from core.skills.teclado import EscribirTexto, PulsarTeclas  # noqa: E402

ATAJOS = {"Google Chrome": {"nombres": ["chrome", "navegador"],
                            "atajos": {"nueva pestaña": "control t", "barra de direcciones": "control l"}}}
REGISTRO = {"abrir_aplicacion": AbrirAplicacion(), "escribir_texto": EscribirTexto(),
            "pulsar_teclas": PulsarTeclas()}


# --- Atajos -----------------------------------------------------------------

def test_atajos_solo_de_las_apps_que_vienen_al_caso():
    assert apps_mencionadas("abre una pestaña en chrome", ATAJOS) == ["Google Chrome"]
    assert apps_mencionadas("abre la calculadora", ATAJOS) == []
    assert describir_atajos("abre la calculadora", None, ATAJOS) == ""
    # La última app usada también cuenta, aunque la frase no la nombre.
    assert "control t" in describir_atajos("abre una pestaña nueva", "Google Chrome", ATAJOS)


# --- Esquema y mensajes -----------------------------------------------------

def test_esquema_es_una_lista_de_pasos():
    esquema = esquema_ordenes(REGISTRO)
    assert esquema["required"] == ["pasos"]
    assert esquema["properties"]["pasos"]["maxItems"] == llm_mod.MAX_PASOS


def test_el_contexto_va_al_final_para_no_romper_la_cache():
    mensajes = construir_mensajes("abre una pestaña", REGISTRO, [], contexto="Última aplicación usada: X.")
    assert mensajes[-2] == {"role": "system", "content": "Última aplicación usada: X."}
    assert mensajes[-1]["content"] == "abre una pestaña"


# --- Validación de varios pasos ----------------------------------------------

def _llm(servidor=object()):
    return InterpreteLLM(REGISTRO, servidor=servidor, ejemplos=[], atajos=ATAJOS, memoria=False)


def _paso(skill, **params):
    return {"skill": skill, "parametros": params}


def test_plan_valido_con_atajos_y_teclas_que_no_estan_en_la_frase():
    texto = "abre una pestaña nueva en chrome y busca el tiempo"
    _, conocidos = _llm()._contexto(texto, None)
    r = _llm().validar({"pasos": [_paso("pulsar_teclas", teclas="control t", aplicacion="chrome"),
                                  _paso("escribir_texto", texto="el tiempo"),
                                  _paso("pulsar_teclas", teclas="enter")]}, texto, conocidos=conocidos)
    assert [s for s, _ in r.pasos] == ["pulsar_teclas", "escribir_texto", "pulsar_teclas"]
    assert r.pasos[2][1] == {"teclas": "enter"}   # 'enter' no está en la frase, pero es una tecla


def test_las_teclas_no_se_cambian_por_una_palabra_parecida():
    # Antes, "enter" se "anclaba" a la palabra "entra" de la frase (y no es una tecla).
    r = _llm().validar({"pasos": [_paso("pulsar_teclas", teclas="enter", aplicacion="discord")]},
                       "en discord entra al canal")
    assert r.params["teclas"] == "enter"


def test_un_paso_imposible_anula_todo_el_plan():
    r = _llm().validar({"pasos": [_paso("abrir_aplicacion", aplicacion="steam"),
                                  _paso("ninguna")]}, "abre steam y dime si hay actualizaciones")
    assert r.skill is None and not r.pasos and "no sé hacer" in r.motivo


def test_teclas_que_no_existen_se_rechazan():
    r = _llm().validar({"pasos": [_paso("pulsar_teclas", teclas="entra")]}, "entra")
    assert r.skill is None and "entra" in r.motivo


def test_el_llm_corrige_su_respuesta_una_vez():
    class ServidorConError:
        def __init__(self):
            self.respuestas = [
                json.dumps({"pasos": [_paso("pulsar_teclas", teclas="entra", aplicacion="discord")]}),
                json.dumps({"pasos": [_paso("pulsar_teclas", teclas="enter", aplicacion="discord")]}),
            ]
            self.mensajes = []

        def asegurar(self):
            return True

        def completar(self, mensajes, esquema):
            self.mensajes.append(list(mensajes))
            return self.respuestas.pop(0)

    servidor = ServidorConError()
    r = _llm(servidor).interpretar("en discord dale a entra")
    assert r.params == {"teclas": "enter", "aplicacion": "discord"}
    assert "no es válida" in servidor.mensajes[1][-1]["content"]   # se le enseñó el error


# --- Router ------------------------------------------------------------------

def test_las_conjunciones_hacen_dudar_al_clasificador():
    router = Router(REGISTRO, clasificador=lambda t: ("abrir_aplicacion", 0.99, []), usar_llm=False)
    _, dudosa = router.interpretar_clasificador("abre discord y escribe hola")
    assert dudosa
    _, dudosa = router.interpretar_clasificador("abre discord")
    assert not dudosa


def test_el_router_devuelve_los_pasos():
    class LLM:
        def interpretar(self, texto, contexto=None):
            self.contexto = contexto
            return llm_mod.ResultadoLLM("abrir_aplicacion", {"aplicacion": "x"},
                                        pasos=[("abrir_aplicacion", {"aplicacion": "x"}),
                                               ("escribir_texto", {"texto": "hola"})])
    llm = LLM()
    router = Router(REGISTRO, clasificador=lambda t: ("ninguna", 0.3, []), llm=llm)
    i = router.interpretar("abre x y escribe hola", contexto={"ultima_aplicacion": "y"})
    assert i.skill == VARIOS_PASOS and len(i.pasos) == 2 and llm.contexto == {"ultima_aplicacion": "y"}


# --- Agente: ejecución de varios pasos -----------------------------------------

class Abrir(Skill):
    nombre = "abrir_aplicacion"
    parametros = {"aplicacion": "app"}

    def __init__(self, log):
        self.log = log

    def ejecutar(self, aplicacion=""):
        self.log.append(("abrir", aplicacion))
        return Resultado(True, "abierta", datos={"aplicacion": aplicacion.title()})


class Escribir(Skill):
    nombre = "escribir_texto"
    parametros = {"texto": "t", "aplicacion": "app"}
    del_contexto = {"aplicacion": "ultima_aplicacion"}

    def __init__(self, log, falla=False):
        self.log, self.falla = log, falla

    def ejecutar(self, texto="", aplicacion=""):
        self.log.append(("escribir", texto, aplicacion))
        return Resultado(not self.falla, "escrito" if not self.falla else "sin foco",
                         datos={"aplicacion": aplicacion})


class Pulsar(Escribir):
    nombre = "pulsar_teclas"
    parametros = {"teclas": "t", "aplicacion": "app"}
    confirmar_si_llm = True

    def ejecutar(self, teclas="", aplicacion=""):
        self.log.append(("pulsar", teclas, aplicacion))
        return Resultado(True, "pulsado", datos={"aplicacion": aplicacion})


def _agente(tmp_path, falla_escribir=False):
    log = []
    registro = {"abrir_aplicacion": Abrir(log), "escribir_texto": Escribir(log, falla_escribir),
                "pulsar_teclas": Pulsar(log)}
    agente = Agente(router=object(), registro=registro, ruta_episodios=tmp_path / "e.jsonl")
    return agente, log


@pytest.fixture(autouse=True)
def sin_pausas(monkeypatch):
    monkeypatch.setattr("core.agente.PAUSA_ENTRE_PASOS", 0)


def _plan(*pasos):
    return Interpretacion("orden", VARIOS_PASOS, 0.5, skill=VARIOS_PASOS, pasos=list(pasos), origen="llm")


def test_varios_pasos_con_la_app_del_paso_anterior(tmp_path):
    agente, log = _agente(tmp_path)
    confirmaciones = []
    r = agente.ejecutar(_plan(("abrir_aplicacion", {"aplicacion": "calculadora"}),
                              ("escribir_texto", {"texto": "2+2"}),
                              ("pulsar_teclas", {"teclas": "enter"})),
                        {}, confirmar=lambda d: confirmaciones.append(d) or True)
    assert r.ok
    assert log == [("abrir", "calculadora"), ("escribir", "2+2", "calculadora"),
                   ("pulsar", "enter", "calculadora")]
    assert len(confirmaciones) == 1 and "escribir_texto" in confirmaciones[0]   # el plan entero, una vez
    episodio = json.loads((tmp_path / "e.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert episodio["skill"] == VARIOS_PASOS and len(episodio["pasos_orden"]) == 3


def test_sin_confirmar_no_se_ejecuta_ningun_paso(tmp_path):
    agente, log = _agente(tmp_path)
    r = agente.ejecutar(_plan(("abrir_aplicacion", {"aplicacion": "x"}), ("pulsar_teclas", {"teclas": "enter"})),
                        {}, confirmar=lambda d: False)
    assert not r.ok and r.datos["cancelado"] and log == []


def test_un_fallo_detiene_el_plan(tmp_path):
    agente, log = _agente(tmp_path, falla_escribir=True)
    r = agente.ejecutar(_plan(("abrir_aplicacion", {"aplicacion": "x"}),
                              ("escribir_texto", {"texto": "hola"}),
                              ("pulsar_teclas", {"teclas": "enter"})), {}, confirmar=lambda d: True)
    assert not r.ok and "Paso 2" in r.mensaje and [e[0] for e in log] == ["abrir", "escribir"]


def test_si_falta_un_dato_no_empieza(tmp_path):
    agente, log = _agente(tmp_path)
    r = agente.ejecutar(_plan(("escribir_texto", {"texto": "hola"})), {}, confirmar=lambda d: True)
    assert not r.ok and "falta" in r.mensaje and log == []   # no hay app ni contexto


# --- Protecciones de la GPU ------------------------------------------------------

def _servidor(tmp_path):
    exe, modelo = tmp_path / "s.exe", tmp_path / "m.gguf"
    exe.write_text("x")
    modelo.write_text("x")
    return ServidorLLM(ejecutable=exe, modelo=modelo, puerto=1)


def test_no_carga_el_llm_sin_vram_libre(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_mod, "leer_gpu", lambda usar_cache=True: EstadoGPU("GPU", 8192, 6000, 2192, 50))
    arrancados = []
    servidor = _servidor(tmp_path)
    monkeypatch.setattr(servidor, "_arrancar", lambda: arrancados.append(1))
    assert servidor.asegurar() is False and arrancados == []


def test_no_carga_el_llm_con_la_gpu_caliente(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_mod, "leer_gpu", lambda usar_cache=True: EstadoGPU("GPU", 8192, 1000, 7192, 90))
    servidor = _servidor(tmp_path)
    monkeypatch.setattr(servidor, "_arrancar", lambda: (_ for _ in ()).throw(AssertionError("no debía")))
    assert servidor.asegurar() is False


def test_en_cpu_no_se_mira_la_gpu(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_mod, "leer_gpu", lambda usar_cache=True: EstadoGPU("GPU", 8192, 8000, 192, 95))
    servidor = _servidor(tmp_path)
    servidor.capas_gpu = 0
    assert servidor._motivo_para_no_cargar() is None
