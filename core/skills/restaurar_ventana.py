"""
Skill nativa: traer al frente una ventana que ya está abierta
(restaurándola si estaba minimizada u oculta en la bandeja del sistema).
"""

from __future__ import annotations

from core.estado import es_visible, traer_al_frente, ventana_visible
from core.skills.base import Resultado, Skill
from core.skills.ventanas import elegir_entre, ventanas_de


class RestaurarVentana(Skill):
    nombre = "restaurar_ventana"
    descripcion = ("Muestra y trae al frente una aplicación que ya está abierta, restaurándola si "
                   "está minimizada u oculta en la bandeja del sistema. No sirve para minimizar.")
    parametros = {"aplicacion": "Nombre (o parte del título) de la ventana"}
    coste = 1
    PRECONDICIONES = {"abierta:{aplicacion}": True, "visible:{aplicacion}": False}
    EFECTOS = {"visible:{aplicacion}": True}

    def ejecutar(self, aplicacion: str = "") -> Resultado:
        ventanas = ventanas_de([aplicacion], incluir_ocultas=True, por_titulo=True)
        if not ventanas:
            return Resultado(False, f"No hay ninguna ventana abierta de '{aplicacion}'.")

        # Si solo una no se ve, es la que hay que restaurar; si no, la que
        # elegiste antes, la que se llama como la app o se pregunta cuál.
        escondidas = [v for v in ventanas if not es_visible(v)]
        if len(escondidas) == 1:
            info = escondidas[0]
        else:
            info, duda = elegir_entre(escondidas or ventanas, aplicacion)
            if info is None:
                return Resultado(False, duda)
        traer_al_frente(info["hwnd"])
        return Resultado(True, f"Ventana '{info['titulo']}' al frente.",
                         datos={"hwnd": info["hwnd"], "titulo": info["titulo"]})

    def verificar(self, resultado: Resultado) -> bool:
        return resultado.ok and ventana_visible(resultado.datos["hwnd"])
