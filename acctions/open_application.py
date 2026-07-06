"""
Acción: abrir_aplicacion

Implementación real (Windows): usa el propio buscador del menú Inicio,
que ya hace coincidencia difusa de nombres por nosotros. Simula pulsar
la tecla Windows, escribir el nombre de la app (el slot) y pulsar Enter.

Limitación honesta: no verificamos si la app realmente se abrió. Para
eso haría falta detectar si aparece una ventana nueva (ej. con la
librería pygetwindow) — lo dejamos como mejora futura, ligada al
"verificador" que ya diseñamos conceptualmente para música. Si el
nombre no coincide con nada instalado, Windows no abre nada y este
método, tal cual está, no se entera.
"""

import time

from .base import AccionBase

try:
    import pyautogui
    PYAUTOGUI_DISPONIBLE = True
except ImportError:
    PYAUTOGUI_DISPONIBLE = False

ESPERA_TRAS_MENU = 0.5
ESPERA_TRAS_ESCRIBIR = 0.4


class AbrirAplicacion(AccionBase):
    nombre_intencion = "abrir_aplicacion"

    def ejecutar(self, texto: str, slot: str) -> str:
        if not PYAUTOGUI_DISPONIBLE:
            return (
                "No se puede abrir la aplicación: falta la librería 'pyautogui'. "
                "Instálala con: python -m pip install pyautogui"
            )

        if not slot:
            return f"No he identificado qué aplicación abrir en: '{texto}'"

        pyautogui.press("win")
        time.sleep(ESPERA_TRAS_MENU)
        pyautogui.typewrite(slot, interval=0.03)
        time.sleep(ESPERA_TRAS_ESCRIBIR)
        pyautogui.press("enter")

        return f"Intentado abrir '{slot}' a través del buscador de Windows"