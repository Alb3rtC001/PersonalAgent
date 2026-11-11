"""
Memoria de episodios: cada orden ejecutada se añade como una línea JSON
en config.RUTA_EPISODIOS. Es el historial del agente y el futuro dataset
para que aprenda de su propio uso (ARQUITECTURA.md §1).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import RUTA_EPISODIOS


def registrar_episodio(episodio: dict[str, Any], ruta: Path | None = None) -> None:
    ruta = Path(ruta) if ruta else RUTA_EPISODIOS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    linea = {"momento": datetime.now().isoformat(timespec="seconds"), **episodio}
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def cargar_episodios(ruta: Path | None = None) -> list[dict[str, Any]]:
    ruta = Path(ruta) if ruta else RUTA_EPISODIOS
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]
