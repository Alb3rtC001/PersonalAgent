"""
recorded_action.py

Acción genérica: en vez de una clase Python escrita a mano por cada
acción (como open_application.py o create_note.py), esta única clase
sirve para CUALQUIER intención que ya tenga una plantilla grabada en
templates.json. Grabar una acción nueva 2 veces (con valores
distintos) es suficiente para que funcione, sin tocar código.
"""

import json
from pathlib import Path

from acctions.base import AccionBase
from recorder.reproductor import reproducir_plantilla

RUTA_PLANTILLAS = Path(__file__).parent.parent / "grabador" / "templates.json"


def cargar_plantilla(nombre_accion: str):
    if not RUTA_PLANTILLAS.exists():
        return None
    with open(RUTA_PLANTILLAS, "r", encoding="utf-8") as f:
        plantillas = json.load(f)
    return plantillas.get(nombre_accion)


class RecordedAction(AccionBase):
    def __init__(self, nombre_intencion: str):
        self.nombre_intencion = nombre_intencion

    def ejecutar(self, texto: str, slot: str) -> str:
        plantilla = cargar_plantilla(self.nombre_intencion)
        if plantilla is None:
            return (
                f"No hay ninguna plantilla grabada todavía para "
                f"'{self.nombre_intencion}'. Grábala 2 veces con recorder.py "
                f"y ejecuta build_templates.py."
            )
        if not slot:
            return f"No he identificado el slot en: '{texto}'"
        return reproducir_plantilla(plantilla, slot)