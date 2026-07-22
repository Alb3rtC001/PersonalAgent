"""
recorded_action.py

Acción genérica que ejecuta plantillas grabadas por demostración.
Antes de reproducir, verifica que la ventana objetivo esté abierta
(si la plantilla tiene esa información grabada). Si no está, informa
al usuario en vez de ejecutar clics en el sitio equivocado.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from acctions.base import AccionBase
from recorder.player import reproducir_plantilla, _extraer_titulo_ventana_objetivo

RUTA_PLANTILLAS = Path(__file__).parent.parent / "recorder" / "templates.json"

try:
    from window_manager import ventana_abierta
    WINDOW_MANAGER_DISPONIBLE = True
except ImportError:
    WINDOW_MANAGER_DISPONIBLE = False


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

        # Verificar que la ventana objetivo esté abierta antes de ejecutar
        titulo_objetivo = _extraer_titulo_ventana_objetivo(plantilla)
        if titulo_objetivo and WINDOW_MANAGER_DISPONIBLE:
            if not ventana_abierta(titulo_objetivo):
                return (
                    f"La ventana '{titulo_objetivo}' no está abierta. "
                    f"Ábrela primero antes de ejecutar '{self.nombre_intencion}'."
                )

        return reproducir_plantilla(plantilla, slot)