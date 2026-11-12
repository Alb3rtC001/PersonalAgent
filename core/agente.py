"""
Agente: la fachada del núcleo. Es lo único que usan los clientes
(CLI, API HTTP y, más adelante, el móvil).

Dos formas de usarlo:

1. Interactiva (CLI): procesar(texto, pedir, confirmar)
   La interacción con el usuario se inyecta como funciones:
       pedir(pregunta) -> str       para pedir un dato que falta
       confirmar(accion) -> bool    para acciones irreversibles

2. Por pasos (API): interpretar(texto) y luego ejecutar(interp, params, confirmar)
   Si falta un dato o hace falta confirmar, ejecutar() devuelve un
   Resultado con `falta` o con datos["cancelado"] y datos["accion"]; el
   cliente contesta y se vuelve a llamar a ejecutar(). Como el executor
   replanifica desde el estado real, los pasos ya hechos no se repiten.

Solo se ejecuta una orden a la vez (las acciones manejan teclado,
ratón y ventanas: dos a la vez se pisarían).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from core.executor import Confirmar, ejecutar_orden
from core.memoria import registrar_episodio
from core.registro import REGISTRO
from core.router import Interpretacion, Router
from core.skills.base import Resultado, Skill

Pedir = Callable[[str], str]


def limpiar_texto(texto: str) -> str:
    return texto.replace("﻿", "").strip()  # BOM que a veces mete la consola


class Agente:
    def __init__(self, router: Router | None = None,
                 registro: dict[str, Skill] | None = None,
                 ruta_episodios: Path | None = None):
        self.registro = registro or REGISTRO
        self.router = router or Router(self.registro)
        self.ruta_episodios = ruta_episodios
        self._lock = threading.Lock()

    # --- Por pasos (API) -----------------------------------------------------

    def interpretar(self, texto: str) -> Interpretacion:
        texto = limpiar_texto(texto)
        interp = self.router.interpretar(texto)
        if interp.motivo_rechazo:
            # Las frases rechazadas también se guardan: son candidatas a ampliar el dataset.
            registrar_episodio(
                {"texto": texto, "skill": None, "intencion": interp.intencion,
                 "confianza": interp.confianza, "ok": False, "rechazada": True,
                 "mensaje": interp.motivo_rechazo},
                self.ruta_episodios,
            )
        return interp

    def ejecutar(self, interp: Interpretacion, params: dict[str, Any],
                 confirmar: Confirmar | None = None) -> Resultado:
        with self._lock:
            return ejecutar_orden(
                interp.skill, params, texto=interp.texto, confianza=interp.confianza,
                confirmar=confirmar, registro=self.registro,
                ruta_episodios=self.ruta_episodios,
            )

    # --- Interactiva (CLI) ---------------------------------------------------

    def procesar(self, texto: str, pedir: Pedir | None = None,
                 confirmar: Confirmar | None = None) -> Resultado:
        interp = self.interpretar(texto)
        if interp.motivo_rechazo:
            return Resultado(False, interp.motivo_rechazo)

        params = dict(interp.params)
        while True:
            resultado = self.ejecutar(interp, params, confirmar)
            if not resultado.falta or pedir is None:
                return resultado
            valor = pedir(resultado.mensaje).strip()
            if not valor:
                return Resultado(False, "Orden cancelada: no se indicó el dato que faltaba.")
            params[resultado.falta] = valor
