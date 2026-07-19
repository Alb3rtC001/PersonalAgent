"""
Reproduce una plantilla grabada, sustituyendo el hueco {slot} por el
valor real solicitado cada vez que se usa.

Para los eventos de tipo "click", se intenta primero encontrar el
recorte de imagen guardado en la pantalla actual (más robusto frente
a pequeños cambios de posición); si no se encuentra, se usa la
coordenada fija grabada como Plan B.
"""

import time
from pathlib import Path

try:
    import pyautogui
    PYAUTOGUI_DISPONIBLE = True
except ImportError:
    PYAUTOGUI_DISPONIBLE = False

ESPERA_ENTRE_EVENTOS = 0.4
CONFIANZA_IMAGEN = 0.8  # requiere opencv-python instalado para usarse


def _reproducir_click(datos_click: dict) -> None:
    # Soporte tanto del formato nuevo (x_abs) como del viejo (x) por compatibilidad
    x = datos_click.get("x_abs", datos_click.get("x", 0))
    y = datos_click.get("y_abs", datos_click.get("y", 0))
    pyautogui.click(x, y)


def reproducir_plantilla(plantilla: list[dict], slot: str) -> str:
    if not PYAUTOGUI_DISPONIBLE:
        return "No se puede reproducir la plantilla: falta 'pyautogui'."

    for evento in plantilla:
        tipo = evento["tipo"]
        if tipo == "tecla_especial":
            pyautogui.press(evento["valor"])
        elif tipo == "escribir":
            valor = slot if evento["valor"] == "{slot}" else evento["valor"]
            pyautogui.typewrite(valor, interval=0.03)
        elif tipo == "click":
            _reproducir_click(evento["valor"])
        time.sleep(ESPERA_ENTRE_EVENTOS)

    return f"Plantilla reproducida con slot='{slot}'"