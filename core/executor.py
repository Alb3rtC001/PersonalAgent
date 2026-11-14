"""
Executor: único punto por el que se ejecutan las órdenes.

ejecutar_orden(skill, params):
    validar parámetros → planificar (pasos previos necesarios) →
    para cada paso: confirmar si es arriesgado → ejecutar → verificar →
    si un paso falla: replanificar UNA vez desde el estado real →
    registrar el episodio completo.

Si falta un parámetro devuelve Resultado.falta para que el cliente
(CLI, API, móvil) se lo pida al usuario; no registra nada hasta que la
orden está completa.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

from core.estado import EstadoMundo
from core.memoria import registrar_episodio
from core.planner import Paso, planificar
from core.registro import REGISTRO
from core.skills.base import Resultado, Skill

Confirmar = Callable[[str], bool]
log = logging.getLogger("personalagent")


def _ejecutar_paso(skill: Skill, params: dict[str, Any]) -> Resultado:
    log.debug("Ejecutando %s", skill.describir_paso(params))
    t0 = time.monotonic()
    try:
        resultado = skill.ejecutar(**params)
    except Exception as e:  # una skill rota no debe tumbar al agente
        log.exception("La skill '%s' lanzó una excepción:", skill.nombre)   # traceback en la traza
        return Resultado(False, f"Error ejecutando '{skill.nombre}': {e}")
    log.debug("  ejecutado en %.0f ms: ok=%s | %s", (time.monotonic() - t0) * 1000,
              resultado.ok, resultado.mensaje)

    if resultado.ok:
        t0 = time.monotonic()
        try:
            verificado = skill.verificar(resultado)
        except Exception as e:
            log.exception("La verificación de '%s' lanzó una excepción:", skill.nombre)
            return Resultado(False, f"Error verificando '{skill.nombre}': {e}", resultado.datos)
        log.debug("  verificación (%.0f ms): %s", (time.monotonic() - t0) * 1000,
                  "correcta" if verificado else resultado.datos.get("motivo_verificacion", "fallida"))
        if not verificado:
            motivo = resultado.datos.get("motivo_verificacion")
            return Resultado(
                False,
                motivo or f"'{skill.nombre}' se ejecutó pero no se pudo verificar el resultado.",
                resultado.datos,
            )
    return resultado


def _ejecutar_plan(
    plan: list[Paso],
    registro: dict[str, Skill],
    confirmar: Confirmar | None,
    historial: list[dict[str, Any]],
    origen: str | None = None,
) -> tuple[Resultado, Paso | None]:
    """Ejecuta los pasos en orden. Devuelve el último resultado y el paso que falló (si alguno)."""
    resultado = Resultado(False, "Plan vacío.")
    for paso in plan:
        skill = registro[paso.skill]
        if skill.requiere_confirmacion or (origen == "llm" and skill.confirmar_si_llm):
            descripcion = skill.describir_paso(paso.params)
            confirmado = confirmar is not None and confirmar(descripcion)
            log.debug("Confirmación de %s: %s", descripcion, "sí" if confirmado else "no")
            if not confirmado:
                resultado = Resultado(False, f"Necesita confirmación: {descripcion}",
                                      datos={"cancelado": True, "accion": descripcion})
                historial.append({"skill": paso.skill, "params": paso.params,
                                  "ok": False, "mensaje": resultado.mensaje})
                return resultado, None

        resultado = _ejecutar_paso(skill, paso.params)
        historial.append({"skill": paso.skill, "params": paso.params,
                          "ok": resultado.ok, "mensaje": resultado.mensaje})
        if not resultado.ok:
            return resultado, paso
    return resultado, None


def ejecutar_orden(
    nombre: str,
    params: dict[str, Any],
    *,
    texto: str = "",
    confianza: float | None = None,
    origen: str | None = None,
    confirmar: Confirmar | None = None,
    registro: dict[str, Skill] | None = None,
    estado: EstadoMundo | None = None,
    ruta_episodios: Path | None = None,
    registrar: bool = True,
    extra: dict[str, Any] | None = None,
) -> Resultado:
    """
    `registrar=False`: no guarda el episodio (lo hace quien llama, p. ej. una
    orden de varios pasos que se guarda entera); los pasos quedan en
    resultado.datos["historial"].
    """
    registro = REGISTRO if registro is None else registro
    skill = registro.get(nombre)
    if skill is None:
        return Resultado(False, f"No existe ninguna skill llamada '{nombre}'.")

    falta = skill.validar(params)
    if falta:
        descripcion = skill.parametros.get(falta, falta)
        log.debug("Falta el parámetro '%s' de %s: se le pide al usuario.", falta, nombre)
        return Resultado(False, f"Falta un dato para '{nombre}': {descripcion}.", falta=falta)

    estado = estado or EstadoMundo()
    historial: list[dict[str, Any]] = []
    planes: list[list[str]] = []
    replanificado = False

    plan = planificar(nombre, params, estado, registro)
    log.debug("Plan para %s: %s", skill.describir_paso(params),
              " → ".join(registro[p.skill].describir_paso(p.params) for p in plan) if plan else "ninguno posible")
    if plan is None:
        resultado = Resultado(
            False, f"No sé cómo preparar lo necesario para {skill.describir_paso(params)}."
        )
    else:
        planes.append([registro[p.skill].describir_paso(p.params) for p in plan])
        resultado, fallido = _ejecutar_plan(plan, registro, confirmar, historial, origen)

        if fallido is not None:
            # El mundo ha cambiado (o no era como creíamos): se vuelve a mirar y se replanifica.
            estado.refrescar()
            nuevo = planificar(nombre, params, estado, registro)
            # Si el nuevo plan empieza repitiendo el mismo paso que falló, no tiene sentido reintentar.
            if nuevo and nuevo[0] != fallido:
                replanificado = True
                log.debug("Un paso falló; replanifico desde el estado real: %s",
                          " → ".join(registro[p.skill].describir_paso(p.params) for p in nuevo))
                planes.append([registro[p.skill].describir_paso(p.params) for p in nuevo])
                resultado, _ = _ejecutar_plan(nuevo, registro, confirmar, historial, origen)

    if registrar:
        registrar_episodio(
            {
                "texto": texto,
                "skill": nombre,
                "parametros": params,
                "confianza": confianza,
                "origen": origen,   # quién interpretó la frase: "clasificador" o "llm"
                "planes": planes,
                "pasos": historial,
                "replanificado": replanificado,
                "ok": resultado.ok,
                "mensaje": resultado.mensaje,
                **(extra or {}),
            },
            ruta_episodios,
        )
    resultado.datos.setdefault("planes", planes)
    resultado.datos["historial"] = historial
    return resultado
