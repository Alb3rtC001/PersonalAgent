"""
Reproduce una plantilla grabada, sustituyendo el hueco {slot} por el
valor real solicitado cada vez que se usa.
"""

import time

try:
    import pyautogui
    PYAUTOGUI_DISPONIBLE = True
except ImportError:
    PYAUTOGUI_DISPONIBLE = False

ESPERA_ENTRE_EVENTOS = 0.4


def reproducir_plantilla(plantilla: list[dict], slot: str) -> str:
    if not PYAUTOGUI_DISPONIBLE:
        return "No se puede reproducir la plantilla: falta 'pyautogui'."

    for evento in plantilla:
        if evento["tipo"] == "tecla_especial":
            pyautogui.press(evento["valor"])
        elif evento["tipo"] == "escribir":
            valor = slot if evento["valor"] == "{slot}" else evento["valor"]
            pyautogui.typewrite(valor, interval=0.03)
        time.sleep(ESPERA_ENTRE_EVENTOS)

    return f"Plantilla reproducida con slot='{slot}'"