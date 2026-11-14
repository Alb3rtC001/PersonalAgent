"""
Botón de pánico: parar lo que esté haciendo el agente y dejarlo en pausa.

    detener()   → lo que esté en marcha se corta en el siguiente punto de
                  control (cada carácter al escribir, cada espera de ventana,
                  cada paso de un plan) y no se acepta nada nuevo, tampoco las
                  tareas programadas, hasta reanudar().
    reanudar()  → vuelve a funcionar.

Las skills y el executor llaman a comprobar() en sus bucles: si se ha pulsado
el botón, lanza Detenido y la orden termina con "Detenido por el usuario".
"""

from __future__ import annotations

import threading

_detenido = threading.Event()

MENSAJE = "Detenido por el usuario (botón de pánico)."


class Detenido(Exception):
    """La orden se ha cortado porque se pulsó el botón de pánico."""


def detener() -> None:
    _detenido.set()


def reanudar() -> None:
    _detenido.clear()


def en_pausa() -> bool:
    return _detenido.is_set()


def comprobar() -> None:
    """Punto de control: si se pulsó el botón de pánico, corta la orden."""
    if _detenido.is_set():
        raise Detenido(MENSAJE)
