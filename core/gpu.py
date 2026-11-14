"""
Estado de la GPU (NVIDIA) para proteger la tarjeta: VRAM libre y temperatura.

Se lee con nvidia-smi, que viene con el driver. Si no está (otra marca de
GPU, sin driver), las comprobaciones no se hacen y el LLM se comporta como
siempre. La lectura se guarda unos segundos para no lanzar nvidia-smi en
cada orden.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

CACHE_SEGUNDOS = 20
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class EstadoGPU:
    nombre: str
    vram_total: int    # MiB
    vram_usada: int    # MiB
    vram_libre: int    # MiB
    temperatura: int   # °C


_cache: tuple[float, EstadoGPU | None] | None = None


def interpretar_salida(linea: str) -> EstadoGPU:
    """
    "NVIDIA GeForce RTX 3060 Ti, 8192, 1074, 6951, 53.47". Algunos drivers dan
    decimales (la temperatura de este PC sale "53.47"), así que todo se lee
    como número con decimales y se redondea.
    """
    nombre, *numeros = [c.strip() for c in linea.split(",")]
    total, usada, libre, temp = (round(float(n)) for n in numeros[:4])
    return EstadoGPU(nombre, total, usada, libre, temp)


def leer_gpu(usar_cache: bool = True) -> EstadoGPU | None:
    global _cache
    if usar_cache and _cache and time.monotonic() - _cache[0] < CACHE_SEGUNDOS:
        return _cache[1]
    estado = None
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW,
        ).stdout.strip().splitlines()
        if salida:
            estado = interpretar_salida(salida[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        estado = None
    _cache = (time.monotonic(), estado)
    return estado


def olvidar_cache() -> None:
    global _cache
    _cache = None
