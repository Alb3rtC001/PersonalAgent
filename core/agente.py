"""
Agente: la fachada del núcleo. Recibe una frase y devuelve un Resultado.

Es lo único que necesitan los clientes (CLI hoy, API y móvil después).
La interacción con el usuario se inyecta como funciones, así el núcleo
no depende de la consola:
    pedir(pregunta) -> str       para pedir un dato que falta
    confirmar(accion) -> bool    para acciones irreversibles
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.executor import Confirmar, ejecutar_orden
from core.memoria import registrar_episodio
from core.registro import REGISTRO
from core.router import Router
from core.skills.base import Resultado, Skill

Pedir = Callable[[str], str]


class Agente:
    def __init__(self, router: Router | None = None,
                 registro: dict[str, Skill] | None = None,
                 ruta_episodios: Path | None = None):
        self.registro = registro or REGISTRO
        self.router = router or Router(self.registro)
        self.ruta_episodios = ruta_episodios

    def procesar(self, texto: str, pedir: Pedir | None = None,
                 confirmar: Confirmar | None = None) -> Resultado:
        texto = texto.replace("﻿", "").strip()  # BOM que a veces mete la consola
        interp = self.router.interpretar(texto)

        if interp.motivo_rechazo:
            # Las frases rechazadas también se guardan: son candidatas a ampliar el dataset.
            registrar_episodio(
                {"texto": texto, "skill": None, "intencion": interp.intencion,
                 "confianza": interp.confianza, "ok": False, "rechazada": True,
                 "mensaje": interp.motivo_rechazo},
                self.ruta_episodios,
            )
            return Resultado(False, interp.motivo_rechazo)

        params = dict(interp.params)
        while True:
            resultado = ejecutar_orden(
                interp.skill, params, texto=texto, confianza=interp.confianza,
                confirmar=confirmar, registro=self.registro,
                ruta_episodios=self.ruta_episodios,
            )
            if not resultado.falta or pedir is None:
                return resultado
            valor = pedir(resultado.mensaje).strip()
            if not valor:
                return Resultado(False, "Orden cancelada: no se indicó el dato que faltaba.")
            params[resultado.falta] = valor
