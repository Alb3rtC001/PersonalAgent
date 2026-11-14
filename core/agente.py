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

import inspect
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from config import CADUCIDAD_CONTEXTO, LLM_ACTIVO
from core.estado import normalizar
from core.executor import Confirmar, ejecutar_orden
from core.traza import nueva_orden
from core.memoria import registrar_episodio
from core.registro import REGISTRO
from core.router import VARIOS_PASOS, Interpretacion, Router
from core.skills.base import Resultado, Skill

Pedir = Callable[[str], str]
log = logging.getLogger("personalagent")

PAUSA_ENTRE_PASOS = 0.4   # segundos entre los pasos de una orden de varios pasos


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
        nueva_orden(texto)   # la traza de la orden anterior se borra aquí
        contexto = {"ultima_aplicacion": self.contexto("ultima_aplicacion")}
        log.debug("Contexto de la sesión: %s", contexto)
        t0 = time.monotonic()
        if "contexto" in inspect.signature(self.router.interpretar).parameters:
            interp = self.router.interpretar(texto, contexto=contexto)
        else:  # routers sin contexto (p. ej. los de los tests)
            interp = self.router.interpretar(texto)
        log.debug("Interpretación (%s, %.0f ms): skill=%s params=%s pasos=%s confianza=%.2f rechazo=%s",
                  interp.origen, (time.monotonic() - t0) * 1000, interp.skill, interp.params,
                  interp.pasos or "-", interp.confianza, interp.motivo_rechazo)
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
            if interp.pasos:
                resultado = self._ejecutar_varios_pasos(interp, confirmar)
                log.debug("Resultado final: ok=%s | %s", resultado.ok, resultado.mensaje)
                return resultado
            skill = self.registro.get(interp.skill)
            params, rellenados = self._rellenar_con_contexto(skill, params)
            if rellenados:
                log.debug("Parámetros tomados del contexto: %s", rellenados)
            resultado = ejecutar_orden(
                interp.skill, params, texto=interp.texto, confianza=interp.confianza,
                origen=interp.origen, confirmar=confirmar, registro=self.registro,
                ruta_episodios=self.ruta_episodios,
            )
            if rellenados and not resultado.falta:
                resultado.mensaje += " (" + ", ".join(
                    f"{k}: '{v}', la última usada" for k, v in rellenados.items()) + ")"
            self._actualizar_contexto(interp.skill, params, resultado)
            log.debug("Resultado final: ok=%s falta=%s | %s", resultado.ok, resultado.falta, resultado.mensaje)
            return resultado

    # --- Órdenes de varios pasos ---------------------------------------------------

    def _preparar_pasos(self, pasos: list[tuple[str, dict[str, Any]]]
                        ) -> tuple[list[tuple[str, dict[str, Any]]], str | None]:
        """
        Completa cada paso con el contexto (la "última aplicación" va cambiando
        a lo largo del plan: "abre chrome" → "pulsa control t" va a Chrome) y
        comprueba que no falte nada ANTES de empezar: un plan no se puede
        quedar a medias esperando un dato.
        """
        ultima = self.contexto("ultima_aplicacion")
        preparados = []
        for i, (nombre, params) in enumerate(pasos, 1):
            skill = self.registro.get(nombre)
            if skill is None:
                return [], f"Paso {i}: no existe la skill '{nombre}'."
            params = dict(params)
            for parametro, clave in (skill.del_contexto or {}).items():
                if clave == "ultima_aplicacion" and not str(params.get(parametro) or "").strip() and ultima:
                    params[parametro] = ultima
            falta = skill.validar(params)
            if falta:
                return [], f"Paso {i} ({nombre}): falta '{skill.parametros.get(falta, falta)}'."
            if params.get("aplicacion"):
                ultima = None if nombre == "cerrar_aplicacion" else params["aplicacion"]
            preparados.append((nombre, params))
        return preparados, None

    def _ejecutar_varios_pasos(self, interp: Interpretacion, confirmar: Confirmar | None) -> Resultado:
        pasos, error = self._preparar_pasos(interp.pasos)
        if error:
            log.debug("Plan rechazado antes de empezar: %s", error)
            return Resultado(False, f"No puedo hacer esa orden: {error}")

        descripcion = " → ".join(self.registro[n].describir_paso(p) for n, p in pasos)
        log.debug("Plan de %d pasos: %s", len(pasos), descripcion)
        # El plan lo ha construido el LLM: si algún paso tiene consecuencias, se
        # confirma el plan entero UNA vez, enseñándolo, en vez de paso a paso.
        delicado = any(self.registro[n].requiere_confirmacion or self.registro[n].confirmar_si_llm
                       for n, _ in pasos)
        if delicado and (confirmar is None or not confirmar(descripcion)):
            log.debug("Plan sin confirmar: no se ejecuta.")
            return Resultado(False, f"Necesita confirmación: {descripcion}",
                             datos={"cancelado": True, "accion": descripcion, "planes": [[descripcion]]})
        if delicado:
            log.debug("Plan confirmado por el usuario.")

        historial, mensajes, resultado = [], [], Resultado(False, "Plan vacío.")
        for i, (nombre, params) in enumerate(pasos, 1):
            if i > 1:
                time.sleep(PAUSA_ENTRE_PASOS)  # que la app reaccione (nueva pestaña, cambio de canal...)
            log.debug("--- Paso %d/%d: %s", i, len(pasos), self.registro[nombre].describir_paso(params))
            resultado = ejecutar_orden(
                nombre, params, texto=interp.texto, origen=interp.origen,
                confirmar=lambda _: True,   # ya confirmado al enseñar el plan
                registro=self.registro, ruta_episodios=self.ruta_episodios, registrar=False,
            )
            self._actualizar_contexto(nombre, params, resultado)
            historial += resultado.datos.get("historial", [])
            mensajes.append(resultado.mensaje)
            if not resultado.ok:
                hechos = f" (hechos antes: {i - 1} de {len(pasos)})" if i > 1 else ""
                resultado = Resultado(False, f"Paso {i} ({nombre}) falló: {resultado.mensaje}{hechos}",
                                      datos=resultado.datos)
                break
        else:
            resultado = Resultado(True, f"Hecho en {len(pasos)} pasos. Último: {mensajes[-1]}",
                                  datos=resultado.datos)

        registrar_episodio(
            {"texto": interp.texto, "skill": VARIOS_PASOS, "pasos_orden": [list(p) for p in pasos],
             "confianza": interp.confianza, "origen": interp.origen, "pasos": historial,
             "ok": resultado.ok, "mensaje": resultado.mensaje},
            self.ruta_episodios,
        )
        resultado.datos["planes"] = [[self.registro[n].describir_paso(p) for n, p in pasos]]
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
