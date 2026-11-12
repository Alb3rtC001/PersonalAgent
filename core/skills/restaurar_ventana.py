"""
Skill nativa: traer al frente una ventana que ya está abierta
(restaurándola si estaba minimizada u oculta en la bandeja del sistema).
"""

from __future__ import annotations

from core.estado import buscar_ventana, es_visible, traer_al_frente, ventana_visible
from core.skills.base import Resultado, Skill


class RestaurarVentana(Skill):
    nombre = "restaurar_ventana"
    descripcion = ("Trae al frente una aplicación que ya está abierta, restaurándola si está "
                   "minimizada u oculta en la bandeja del sistema.")
    parametros = {"aplicacion": "Nombre (o parte del título) de la ventana"}
    coste = 1
    PRECONDICIONES = {"abierta:{aplicacion}": True, "visible:{aplicacion}": False}
    EFECTOS = {"visible:{aplicacion}": True}

    def ejecutar(self, aplicacion: str = "") -> Resultado:
        ventanas = buscar_ventana(aplicacion, incluir_ocultas=True)
        if not ventanas:
            return Resultado(False, f"No hay ninguna ventana abierta de '{aplicacion}'.")

        # Preferir la que no se ve (es la que hay que restaurar).
        ventanas.sort(key=es_visible)
        info = ventanas[0]
        traer_al_frente(info["hwnd"])
        return Resultado(True, f"Ventana '{info['titulo']}' al frente.",
                         datos={"hwnd": info["hwnd"], "titulo": info["titulo"]})

    def verificar(self, resultado: Resultado) -> bool:
        return resultado.ok and ventana_visible(resultado.datos["hwnd"])
