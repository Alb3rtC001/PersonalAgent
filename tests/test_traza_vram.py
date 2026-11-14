"""
Tests de la traza de la última orden, la lectura de la GPU, la cabecera
GGUF y el cálculo de capas para el límite de VRAM. Sin GPU ni modelo real.

    python -m pytest tests
"""

import logging
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.gguf import numero_de_capas  # noqa: E402
from core.gpu import interpretar_salida  # noqa: E402
from core.llm import VRAM_BASE_MIB, ServidorLLM  # noqa: E402
from core.traza import ManejadorUltimaOrden  # noqa: E402


# --- Traza de la última orden ----------------------------------------------------

def test_la_traza_solo_guarda_la_ultima_orden(tmp_path):
    ruta = tmp_path / "ultima_orden.log"
    manejador = ManejadorUltimaOrden(ruta)
    log = logging.getLogger("personalagent.prueba_traza")
    log.setLevel(logging.DEBUG)
    log.addHandler(manejador)
    try:
        log.debug("antes de ninguna orden")            # no se guarda: no hay orden en curso
        manejador.nueva("abre discord")
        log.debug("paso de la primera orden")
        manejador.nueva("cierra discord")
        log.debug("paso de la segunda orden")
        try:
            raise RuntimeError("fallo de prueba")
        except RuntimeError:
            log.exception("La skill lanzó una excepción:")
    finally:
        log.removeHandler(manejador)
        manejador.close()

    traza = ruta.read_text(encoding="utf-8")
    assert "cierra discord" in traza and "paso de la segunda orden" in traza
    assert "abre discord" not in traza and "primera orden" not in traza and "antes de" not in traza
    assert "Traceback" in traza and "RuntimeError: fallo de prueba" in traza
    assert "test_traza_vram.test_la_traza_solo_guarda_la_ultima_orden:" in traza   # módulo.función:línea


# --- GPU ---------------------------------------------------------------------------

def test_lectura_de_la_gpu_con_decimales():
    # El driver de este PC da la temperatura con decimales: antes eso hacía que la
    # lectura fallase y las protecciones de la GPU no se aplicaran nunca.
    gpu = interpretar_salida("NVIDIA GeForce RTX 3060 Ti, 8192, 1074, 6951, 53.47")
    assert (gpu.vram_total, gpu.vram_usada, gpu.vram_libre, gpu.temperatura) == (8192, 1074, 6951, 53)


# --- GGUF y capas -----------------------------------------------------------------

def _gguf(ruta: Path, capas: int, tam_mib: int) -> Path:
    def cadena(s: str) -> bytes:
        b = s.encode()
        return struct.pack("<Q", len(b)) + b
    cabecera = b"GGUF" + struct.pack("<IQQ", 3, 0, 3)
    cabecera += cadena("general.architecture") + struct.pack("<I", 8) + cadena("qwen3")
    cabecera += cadena("tokenizer.ggml.scores") + struct.pack("<IIQ", 9, 6, 2) + struct.pack("<ff", 0.1, 0.2)
    cabecera += cadena("qwen3.block_count") + struct.pack("<II", 4, capas)
    with open(ruta, "wb") as f:
        f.write(cabecera)
        f.truncate(tam_mib * 2**20)
    return ruta


def test_numero_de_capas(tmp_path):
    assert numero_de_capas(_gguf(tmp_path / "m.gguf", 36, 1)) == 36
    (tmp_path / "no.gguf").write_text("esto no es un modelo")
    assert numero_de_capas(tmp_path / "no.gguf") is None


def _servidor(tmp_path, vram_max):
    modelo = _gguf(tmp_path / "m.gguf", 36, 37)   # 37 MiB / (36 + 1) = 1 MiB por capa
    exe = tmp_path / "s.exe"
    exe.write_text("x")
    return ServidorLLM(ejecutable=exe, modelo=modelo, puerto=1, vram_max=vram_max)


def test_plan_de_capas_segun_el_limite(tmp_path):
    assert _servidor(tmp_path, vram_max=VRAM_BASE_MIB + 1000)._plan_capas()[0] == 37   # cabe entero
    assert _servidor(tmp_path, vram_max=VRAM_BASE_MIB + 10)._plan_capas()[0] == 10
    assert _servidor(tmp_path, vram_max=0)._plan_capas()[0] == 0                       # todo al procesador


def test_en_cpu_no_va_ninguna_capa_a_la_gpu(tmp_path):
    servidor = _servidor(tmp_path, vram_max=99999)
    servidor.capas_gpu = 0
    assert servidor._plan_capas() == (0, 0)
