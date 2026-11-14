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
import time
from pathlib import Path
from typing import Any, Callable

from config import CADUCIDAD_CONTEXTO, LLM_ACTIVO
from core.estado import normalizar
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
                 ruta_episodios: Path | None = None,
                 usar_llm: bool = LLM_ACTIVO, llm_cpu: bool = False):
        self.registro = REGISTRO if registro is None else registro
        self.router = router or Router(self.registro, usar_llm=usar_llm, llm_cpu=llm_cpu)
        self.ruta_episodios = ruta_episodios
        self._lock = threading.Lock()
        self._contexto: dict[str, tuple[Any, float]] = {}

    # --- LLM -------------------------------------------------------------------

    def precargar(self) -> None:
        """Carga el LLM en segundo plano para que la primera orden dudosa no espere."""
        precargar = getattr(self.router, "precargar", None)
        if precargar is not None:
            threading.Thread(target=precargar, daemon=True, name="precarga-llm").start()

    def activar_llm(self, activo: bool) -> dict[str, Any]:
        """Activa o desactiva el LLM en marcha (desactivarlo libera la VRAM)."""
        if hasattr(self.router, "activar_llm"):
            self.router.activar_llm(activo)
            if activo:
                self.precargar()
        return self.estado_llm()

    def estado_llm(self) -> dict[str, Any]:
        if hasattr(self.router, "estado_llm"):
            return self.router.estado_llm()
        return {"activo": False, "cargado": False, "modelo": None, "gpu": None}

    # --- Por pasos (API) -----------------------------------------------------

    def interpretar(self, texto: str) -> Interpretacion:
        texto = limpiar_texto(texto)
        interp = self.router.interpretar(texto)
        if interp.motivo_rechazo:
            # Las frases rechazadas también se guardan: son candidatas a ampliar el dataset.
            registrar_episodio(
                {"texto": texto, "skill": None, "intencion": interp.intencion,
                 "confianza": interp.confianza, "origen": interp.origen, "ok": False, "rechazada": True,
                 "mensaje": interp.motivo_rechazo},
                self.ruta_episodios,
            )
        return interp

    def ejecutar(self, interp: Interpretacion, params: dict[str, Any],
                 confirmar: Confirmar | None = None) -> Resultado:
        with self._lock:
            skill = self.registro.get(interp.skill)
            params, rellenados = self._rellenar_con_contexto(skill, params)
            resultado = ejecutar_orden(
                interp.skill, params, texto=interp.texto, confianza=interp.confianza,
                origen=interp.origen, confirmar=confirmar, registro=self.registro,
                ruta_episodios=self.ruta_episodios,
            )
            if rellenados and not resultado.falta:
                resultado.mensaje += " (" + ", ".join(
                    f"{k}: '{v}', la última usada" for k, v in rellenados.items()) + ")"
            self._actualizar_contexto(interp.skill, params, resultado)
            return resultado

    # --- Contexto de la sesión ---------------------------------------------------
    # De momento solo "la última aplicación con la que se ha trabajado", para
    # órdenes como "abre la calculadora" → "escribe 2+2". Caduca a los
    # CADUCIDAD_CONTEXTO segundos. (El contexto completo es la fase 4.)

    def contexto(self, clave: str) -> Any:
        valor, momento = self._contexto.get(clave, (None, 0.0))
        if valor is not None and time.monotonic() - momento > CADUCIDAD_CONTEXTO:
            self._contexto.pop(clave, None)
            return None
        return valor

    def _rellenar_con_contexto(self, skill: Skill | None,
                               params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        params, rellenados = dict(params), {}
        for parametro, clave in (getattr(skill, "del_contexto", None) or {}).items():
            valor_actual = params.get(parametro)
            if valor_actual is None or (isinstance(valor_actual, str) and not valor_actual.strip()):
                valor = self.contexto(clave)
                if valor:
                    params[parametro] = rellenados[parametro] = valor
        return params, rellenados

    def _actualizar_contexto(self, skill: str | None, params: dict[str, Any],
                             resultado: Resultado) -> None:
        if not resultado.ok:
            return
        # abrir_aplicacion devuelve el nombre real ("Calculadora" para "calcu").
        app = resultado.datos.get("aplicacion") or params.get("aplicacion")
        if not app:
            return
        if skill == "cerrar_aplicacion":
            ultima = self.contexto("ultima_aplicacion")
            if ultima and normalizar(ultima) in (normalizar(app), normalizar(params.get("aplicacion", ""))):
                self._contexto.pop("ultima_aplicacion", None)
            return
        self._contexto["ultima_aplicacion"] = (app, time.monotonic())

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
