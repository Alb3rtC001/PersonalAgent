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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from config import CADUCIDAD_CONTEXTO, LLM_ACTIVO
from core import control
from core.agenda import Agenda, Planificador, Tarea
from core.estado import normalizar
from core.skills.agenda import SKILLS_DE_AGENDA, usar_agenda
from core.tiempo import describir_cuando, separar_tiempo
from core.executor import Confirmar, ejecutar_orden
from core.seguridad import avisar, necesita_confirmacion, registrar_actividad
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
                 usar_llm: bool = LLM_ACTIVO, llm_cpu: bool = False,
                 ruta_bd: Path | None = None, canal: str = "consola"):
        self.registro = REGISTRO if registro is None else registro
        self.canal = canal   # quién da las órdenes: consola, interfaz, api (para el registro de actividad)
        self.router = router or Router(self.registro, usar_llm=usar_llm, llm_cpu=llm_cpu)
        self.ruta_episodios = ruta_episodios
        self.ruta_bd = ruta_bd
        self._lock = threading.RLock()   # reentrante: una tarea programada se ejecuta con ejecutar()
        self._contexto: dict[str, tuple[Any, float]] = {}
        self._agenda: Agenda | None = None
        self._planificador: Planificador | None = None

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

    def interpretar(self, texto: str, programar_en: timedelta | None = None) -> Interpretacion:
        texto = limpiar_texto(texto)
        nueva_orden(texto)   # la traza de la orden anterior se borra aquí
        contexto = {"ultima_aplicacion": self.contexto("ultima_aplicacion")}
        log.debug("Contexto de la sesión: %s", contexto)

        interp = None
        tiempo = None if programar_en else separar_tiempo(texto)
        if programar_en:
            # Tiempo puesto aparte (los recuadros de minutos/segundos de la interfaz):
            # se programa lo que sea, también una nota, porque lo has pedido así.
            interp = self._interpretar_texto(texto, contexto)
            if not interp.motivo_rechazo:
                segundos = int(programar_en.total_seconds())
                interp.programada = {"cuando": datetime.now() + programar_en, "orden": texto,
                                     "expresion": f"dentro de {segundos // 60} min {segundos % 60} s"}
        if tiempo:
            # "abre steam dentro de 5 min": se interpreta "abre steam" y se programa.
            orden, cuando, expresion, relativa = tiempo
            log.debug("Expresión de tiempo: %r → %s; orden: %r", expresion, cuando, orden)
            candidata = self._interpretar_texto(orden, contexto)
            if not candidata.motivo_rechazo and self._se_puede_programar(candidata, relativa):
                candidata.texto = texto
                candidata.programada = {"cuando": cuando, "expresion": expresion, "orden": orden}
                interp = candidata
            else:
                log.debug("No se programa (%s): se interpreta la frase entera.",
                          candidata.motivo_rechazo or "el tiempo es parte del contenido")
        if interp is None:
            interp = self._interpretar_texto(texto, contexto)
        if interp.motivo_rechazo:
            registrar_actividad(self.canal, f"«{texto}» no entendida: {interp.motivo_rechazo}", False)
            # Las frases rechazadas también se guardan: son candidatas a ampliar el dataset.
            registrar_episodio(
                {"texto": texto, "skill": None, "intencion": interp.intencion,
                 "confianza": interp.confianza, "origen": interp.origen, "ok": False, "rechazada": True,
                 "mensaje": interp.motivo_rechazo},
                self.ruta_episodios,
            )
        return interp

    def _interpretar_texto(self, texto: str, contexto: dict[str, Any]) -> Interpretacion:
        t0 = time.monotonic()
        if "contexto" in inspect.signature(self.router.interpretar).parameters:
            interp = self.router.interpretar(texto, contexto=contexto)
        else:  # routers sin contexto (p. ej. los de los tests)
            interp = self.router.interpretar(texto)
        log.debug("Interpretación (%s, %.0f ms): skill=%s params=%s pasos=%s confianza=%.2f rechazo=%s",
                  interp.origen, (time.monotonic() - t0) * 1000, interp.skill, interp.params,
                  interp.pasos or "-", interp.confianza, interp.motivo_rechazo)
        return interp

    @staticmethod
    def _se_puede_programar(interp: Interpretacion, relativa: bool) -> bool:
        """
        En una nota, la hora es parte del contenido ("apunta que tengo dentista
        mañana a las 9"): nunca se programa. Un texto a escribir solo con tiempos
        relativos ("escribe hola dentro de 5 min"), no con horas ("...a las 5").
        """
        skills = [s for s, _ in interp.pasos] if interp.pasos else [interp.skill]
        if "crear_nota" in skills or any(s in SKILLS_DE_AGENDA for s in skills):
            return False
        return relativa or "escribir_texto" not in skills

    def ejecutar(self, interp: Interpretacion, params: dict[str, Any],
                 confirmar: Confirmar | None = None) -> Resultado:
        quien = "agenda" if interp.origen == "agenda" else self.canal
        if control.en_pausa():
            resultado = Resultado(False, "El agente está en pausa (botón de pánico): reanúdalo para seguir.")
        else:
            try:
                resultado = self._ejecutar(interp, params, confirmar)
            except control.Detenido:
                log.info("Orden detenida con el botón de pánico.")
                resultado = Resultado(False, control.MENSAJE, datos={"detenido": True})
            finally:
                avisar(None)   # fin: la interfaz quita el recuadro de "trabajando"
        if not resultado.falta:   # si falta un dato la orden sigue abierta: se registra al acabar
            registrar_actividad(quien, f"«{interp.texto}» [{interp.skill}] {resultado.mensaje}", resultado.ok)
        return resultado

    def _ejecutar(self, interp: Interpretacion, params: dict[str, Any],
                  confirmar: Confirmar | None = None) -> Resultado:
        with self._lock:
            if interp.programada:
                resultado = self._programar(interp, params, confirmar)
                log.debug("Resultado final: ok=%s falta=%s | %s", resultado.ok, resultado.falta, resultado.mensaje)
                return resultado
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
                # Lo interpretado ANTES de rellenar con el contexto: es lo que la
                # memoria enseñará al LLM como ejemplo (core/memoria.py).
                extra={"parametros_interpretados": dict(interp.params)},
            )
            if rellenados and not resultado.falta:
                resultado.mensaje += " (" + ", ".join(
                    f"{k}: '{v}', la última usada" for k, v in rellenados.items()) + ")"
            self._actualizar_contexto(interp.skill, params, resultado)
            log.debug("Resultado final: ok=%s falta=%s | %s", resultado.ok, resultado.falta, resultado.mensaje)
            return resultado

    # --- Tareas programadas ---------------------------------------------------------

    @property
    def agenda(self) -> Agenda:
        if self._agenda is None:
            self._agenda = Agenda(self.ruta_bd) if self.ruta_bd else Agenda()
            usar_agenda(self._agenda)   # la que usan ver_tareas y cancelar_tarea
        return self._agenda

    def iniciar_agenda(self) -> None:
        """Arranca el hilo que ejecuta las tareas programadas a su hora."""
        if self._planificador is None:
            self._planificador = Planificador(self.agenda, self._ejecutar_tarea)
        self._planificador.iniciar()

    def _programar(self, interp: Interpretacion, params: dict[str, Any],
                   confirmar: Confirmar | None) -> Resultado:
        """
        Se completa y valida la orden AHORA (a su hora no estarás para contestar),
        se te enseña con su hora y, si la confirmas, se guarda en la agenda.
        """
        cuando: datetime = interp.programada["cuando"]
        if interp.pasos:
            pasos, error = self._preparar_pasos(interp.pasos)
            if error:
                return Resultado(False, f"No puedo programar esa orden: {error}")
            descripcion = " → ".join(self.registro[n].describir_paso(p) for n, p in pasos)
            orden = {"skill": VARIOS_PASOS, "params": {}, "pasos": [list(p) for p in pasos]}
        else:
            skill = self.registro.get(interp.skill)
            if skill is None:
                return Resultado(False, f"No existe ninguna skill llamada '{interp.skill}'.")
            params, _ = self._rellenar_con_contexto(skill, params)
            falta = skill.validar(params)
            if falta:   # se pregunta ahora, como en cualquier orden
                return Resultado(False, f"Falta un dato para '{skill.nombre}': "
                                        f"{skill.parametros.get(falta, falta)}.", falta=falta)
            error = skill.comprobar_valores(params)
            if error:
                return Resultado(False, f"No puedo programar esa orden: {error}")
            descripcion = skill.describir_paso(params)
            orden = {"skill": interp.skill, "params": params, "pasos": []}
        orden.update(origen=interp.origen, confianza=interp.confianza)

        accion = f"programar para {describir_cuando(cuando)}: {descripcion}"
        confirmado = confirmar is not None and confirmar(accion)
        log.debug("Confirmación de '%s': %s", accion, "sí" if confirmado else "no")
        if not confirmado:   # las tareas programadas SIEMPRE se confirman al programarlas
            return Resultado(False, f"Necesita confirmación: {accion}",
                             datos={"cancelado": True, "accion": accion, "planes": [[descripcion]]})
        tarea = self.agenda.programar(interp.programada["orden"], cuando, orden, descripcion)
        registrar_episodio(
            {"texto": interp.texto, "skill": "programar", "tarea": tarea.id, "cuando": cuando.isoformat(),
             "orden": orden, "origen": interp.origen, "ok": True, "mensaje": accion},
            self.ruta_episodios,
        )
        return Resultado(True, f"Programada la tarea #{tarea.id} para {describir_cuando(cuando)}: {descripcion}",
                         datos={"tarea": tarea.id, "planes": [[descripcion]]})

    def _ejecutar_tarea(self, tarea: Tarea) -> tuple[bool, str]:
        """Lo llama el planificador a su hora: sin preguntar (ya se confirmó al programarla)."""
        nueva_orden(f"[tarea #{tarea.id} programada] {tarea.texto}")
        orden = tarea.orden
        interp = Interpretacion(tarea.texto, orden["skill"], orden.get("confianza") or 0.0,
                                skill=orden["skill"], params=dict(orden.get("params") or {}),
                                pasos=[tuple(p) for p in orden.get("pasos") or []],
                                # "agenda": la memoria no aprende de estas (sus parámetros
                                # ya venían rellenados con el contexto al programarlas).
                                origen="agenda")
        resultado = self.ejecutar(interp, dict(interp.params), confirmar=lambda _: True)
        return resultado.ok, resultado.mensaje

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
        delicado = any(necesita_confirmacion(self.registro[n], interp.origen) for n, _ in pasos)
        if delicado and (confirmar is None or not confirmar(descripcion)):
            log.debug("Plan sin confirmar: no se ejecuta.")
            return Resultado(False, f"Necesita confirmación: {descripcion}",
                             datos={"cancelado": True, "accion": descripcion, "planes": [[descripcion]]})
        if delicado:
            log.debug("Plan confirmado por el usuario.")

        historial, mensajes, resultado = [], [], Resultado(False, "Plan vacío.")
        for i, (nombre, params) in enumerate(pasos, 1):
            if i > 1:
                control.comprobar()   # botón de pánico
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
             "pasos_interpretados": [list(p) for p in interp.pasos],
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
                 confirmar: Confirmar | None = None,
                 programar_en: timedelta | None = None) -> Resultado:
        if control.en_pausa():
            return Resultado(False, "El agente está en pausa (botón de pánico): reanúdalo para seguir.")
        interp = self.interpretar(texto, programar_en=programar_en)
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
