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
    x, y = datos_click["x"], datos_click["y"]
    ruta_imagen = datos_click.get("imagen")

    if ruta_imagen and Path(ruta_imagen).exists():
        try:
            posicion = pyautogui.locateCenterOnScreen(ruta_imagen, confidence=CONFIANZA_IMAGEN)
        except Exception:
            # Sin opencv instalado, o cualquier otro fallo de coincidencia:
            # seguimos con el Plan B (coordenadas fijas) sin interrumpir.
            posicion = None

        if posicion is not None:
            pyautogui.click(posicion)
            return

    # Plan B: la imagen no coincidió (o no había), usamos la coordenada grabada.
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