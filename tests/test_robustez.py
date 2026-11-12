"""
Tests de los arreglos de la revisión: interruptor del LLM, reintentos,
episodios corruptos y reproductor de plantillas. No tocan Windows ni la GPU.

    python -m pytest tests
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx  # noqa: E402

import recorder.player as player  # noqa: E402
from core.llm import InterpreteLLM, ResultadoLLM, ServidorLLM  # noqa: E402
from core.memoria import cargar_episodios, registrar_episodio  # noqa: E402
from core.router import Router  # noqa: E402
from core.skills.abrir_aplicacion import AbrirAplicacion  # noqa: E402

REGISTRO = {"abrir_aplicacion": AbrirAplicacion()}
DUDOSA = ("ninguna", 0.3, [])   # el clasificador no sabe: habría que preguntar al LLM


class ServidorFalso:
    def __init__(self):
        self.parado = False
        self.capas_gpu = 99
        self.modelo = Path("modelo.gguf")

    def activo(self):
        return not self.parado

    def parar(self):
        self.parado = True

    def permitir_reintento(self):
        pass


class LLMFalso:
    def __init__(self):
        self.servidor = ServidorFalso()
        self.llamadas = 0

    def interpretar(self, texto):
        self.llamadas += 1
        return ResultadoLLM("abrir_aplicacion", {"aplicacion": "discord"})

    def disponible(self):
        return True


# --- Interruptor del LLM ------------------------------------------------

def test_con_llm_desactivado_no_se_consulta():
    llm = LLMFalso()
    router = Router(REGISTRO, clasificador=lambda t: DUDOSA, llm=llm, usar_llm=False)
    i = router.interpretar("me haría falta discord")
    assert i.skill is None and llm.llamadas == 0


def test_activar_y_desactivar_en_marcha():
    llm = LLMFalso()
    router = Router(REGISTRO, clasificador=lambda t: DUDOSA, llm=llm, usar_llm=True)
    assert router.interpretar("me haría falta discord").skill == "abrir_aplicacion"

    router.activar_llm(False)
    assert llm.servidor.parado                      # libera la VRAM
    assert router.estado_llm()["activo"] is False
    assert router.interpretar("me haría falta discord").skill is None
    assert llm.llamadas == 1

    router.activar_llm(True)
    assert router.interpretar("me haría falta discord").skill == "abrir_aplicacion"


def test_desactivado_desde_el_inicio_no_crea_el_llm():
    router = Router(REGISTRO, clasificador=lambda t: DUDOSA, usar_llm=False)
    router.interpretar("lo que sea")
    assert router.llm is None and router.estado_llm()["activo"] is False


# --- LLM no disponible --------------------------------------------------

def test_sin_archivos_del_modelo_no_reintenta_en_cada_orden(tmp_path):
    servidor = ServidorLLM(ejecutable=tmp_path / "no-existe.exe", modelo=tmp_path / "no.gguf",
                           puerto=1)  # puerto 1: no hay nada escuchando
    assert servidor.asegurar() is False
    t0 = time.monotonic()
    assert servidor.asegurar() is False
    assert time.monotonic() - t0 < 1.5


def test_llm_caido_a_mitad_se_trata_como_no_disponible():
    class ServidorQueSeCae:
        def asegurar(self):
            return True

        def completar(self, *a, **k):
            raise httpx.ConnectError("se cayó")

    r = InterpreteLLM(REGISTRO, servidor=ServidorQueSeCae(), ejemplos=[]).interpretar("abre discord")
    assert r.skill is None and r.disponible is False


# --- Memoria ------------------------------------------------------------

def test_episodios_ignora_lineas_corruptas(tmp_path):
    ruta = tmp_path / "e.jsonl"
    registrar_episodio({"texto": "uno"}, ruta)
    with open(ruta, "a", encoding="utf-8") as f:
        f.write('{"texto": "a medio escrib\n')  # cierre brusco a mitad de línea
    registrar_episodio({"texto": "dos"}, ruta)
    assert [e["texto"] for e in cargar_episodios(ruta)] == ["uno", "dos"]


# --- Reproductor de plantillas -------------------------------------------

def test_reproductor_se_detiene_tras_un_error(monkeypatch):
    hechos = []

    class PyAutoGUIFalso:
        def click(self, x, y):
            raise RuntimeError("pantalla bloqueada")

        def typewrite(self, texto, interval=0):
            hechos.append(("escribir", texto))

        def press(self, tecla):
            hechos.append(("tecla", tecla))

    monkeypatch.setattr(player, "pyautogui", PyAutoGUIFalso(), raising=False)
    monkeypatch.setattr(player, "PYAUTOGUI_DISPONIBLE", True)
    monkeypatch.setattr(player, "ESPERA_ENTRE_EVENTOS", 0)
    plantilla = [
        {"tipo": "click", "valor": {"x_abs": 10, "y_abs": 10}},
        {"tipo": "escribir", "valor": "{slot}"},
        {"tipo": "click", "valor": {"x_abs": 20, "y_abs": 20}, "definitivo": True},
    ]
    log = player.reproducir_plantilla(plantilla, "hades")
    assert not log.ok and hechos == [] and len(log.pasos) == 1
