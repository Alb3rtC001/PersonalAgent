"""
Skill nativa: traer al frente una ventana que ya está abierta
(restaurándola si estaba minimizada).
"""

from __future__ import annotations

import time

from core.estado import buscar_ventana, obtener_ventana_gw
from core.skills.base import Resultado, Skill


class RestaurarVentana(Skill):
    nombre = "restaurar_ventana"
    descripcion = "Trae al frente una aplicación que ya está abierta, restaurándola si está minimizada."
    parametros = {"aplicacion": "Nombre (o parte del título) de la ventana"}
    coste = 1
    PRECONDICIONES = {"abierta:{aplicacion}": True, "visible:{aplicacion}": False}
    EFECTOS = {"visible:{aplicacion}": True}

    def ejecutar(self, aplicacion: str = "") -> Resultado:
        ventanas = buscar_ventana(aplicacion)
        if not ventanas:
            return Resultado(False, f"No hay ninguna ventana abierta de '{aplicacion}'.")

        # Preferir la ventana minimizada (es la que hay que restaurar).
        ventanas.sort(key=lambda v: not v["minimizada"])
        info = ventanas[0]
        ventana = obtener_ventana_gw(info["hwnd"])
        if ventana is None:
            return Resultado(False, "No se puede manejar ventanas (falta pygetwindow).")

        if ventana.isMinimized:
            ventana.restore()
        try:
            ventana.activate()
        except Exception:
            # Windows a veces bloquea SetForegroundWindow; minimizar y restaurar lo esquiva.
            ventana.minimize()
            ventana.restore()
        time.sleep(0.3)
        return Resultado(True, f"Ventana '{info['titulo']}' al frente.",
                         datos={"hwnd": info["hwnd"], "titulo": info["titulo"]})

    def verificar(self, resultado: Resultado) -> bool:
        if not resultado.ok:
            return False
        ventana = obtener_ventana_gw(resultado.datos["hwnd"])
        return ventana is not None and not ventana.isMinimized
