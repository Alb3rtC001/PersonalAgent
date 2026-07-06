"""
Persistencia de las grabaciones crudas (recordings.json).

Separado de grabar.py a propósito: build_templates.py necesita leer
y escribir estas grabaciones, pero NO necesita pynput (no hace falta
teclado real ni escuchar nada para procesar un JSON). Así evitamos
que build_templates.py dependa de una librería que no usa.
"""

import json
from pathlib import Path

RUTA_GRABACIONES = Path(__file__).parent / "recordings.json"


def cargar_grabaciones() -> dict:
    if not RUTA_GRABACIONES.exists():
        return {}
    with open(RUTA_GRABACIONES, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_grabacion(nombre_accion: str, eventos: list[dict]) -> int:
    """Añade esta grabación a las que ya hubiera para esa acción. Devuelve el total acumulado."""
    grabaciones = cargar_grabaciones()
    grabaciones.setdefault(nombre_accion, [])
    grabaciones[nombre_accion].append(eventos)
    with open(RUTA_GRABACIONES, "w", encoding="utf-8") as f:
        json.dump(grabaciones, f, ensure_ascii=False, indent=2)
    return len(grabaciones[nombre_accion])