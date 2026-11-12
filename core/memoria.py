"""
Memoria de episodios: cada orden ejecutada (o rechazada) se añade como
una línea JSON en config.RUTA_EPISODIOS. Es el historial del agente y el
futuro dataset para que aprenda de su propio uso (ARQUITECTURA.md §1).

Formato JSONL (una línea por episodio): solo se añade al final, nunca se
reescribe, así que es rápido y no se corrompe si el programa se cierra a
mitad. Todo el acceso pasa por este módulo, de modo que cambiar a SQLite
o a una base vectorial más adelante no afecta al resto del código
(ARQUITECTURA.md §9).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from config import RUTA_EPISODIOS

_lock = threading.Lock()  # la API atiende peticiones en varios hilos


def registrar_episodio(episodio: dict[str, Any], ruta: Path | None = None) -> None:
    ruta = Path(ruta) if ruta else RUTA_EPISODIOS
    linea = {"momento": datetime.now().isoformat(timespec="seconds"), **episodio}
    texto = json.dumps(linea, ensure_ascii=False, default=str) + "\n"
    with _lock:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(texto)


def cargar_episodios(ruta: Path | None = None, limite: int | None = None) -> list[dict[str, Any]]:
    """Episodios en orden cronológico; con `limite`, solo los últimos N."""
    ruta = Path(ruta) if ruta else RUTA_EPISODIOS
    if not ruta.exists():
        return []
    episodios = []
    with _lock, open(ruta, encoding="utf-8") as f:
        for linea in f:
            if not linea.strip():
                continue
            try:
                episodios.append(json.loads(linea))
            except json.JSONDecodeError:
                continue  # línea a medio escribir (cierre brusco): se ignora
    return episodios[-limite:] if limite else episodios
