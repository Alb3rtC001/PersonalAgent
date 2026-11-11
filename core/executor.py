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

from pathlib import Path
from typing import Any, Callable

from core.estado import EstadoMundo
from core.memoria import registrar_episodio
from core.planner import Paso, planificar
from core.registro import REGISTRO
from core.skills.base import Resultado, Skill

Confirmar = Callable[[str], bool]


def _ejecutar_paso(skill: Skill, params: dict[str, Any]) -> Resultado:
    try:
        resultado = skill.ejecutar(**params)
    except Exception as e:  # una skill rota no debe tumbar al agente
        return Resultado(False, f"Error ejecutando '{skill.nombre}': {e}")

    if resultado.ok and not skill.verificar(resultado):
        return Resultado(
            False,
            f"'{skill.nombre}' se ejecutó pero no se pudo verificar el resultado.",
            resultado.datos,
        )
    return resultado


def _ejecutar_plan(
    plan: list[Paso],
    registro: dict[str, Skill],
    confirmar: Confirmar | None,
    historial: list[dict[str, Any]],
) -> tuple[Resultado, Paso | None]:
    """Ejecuta los pasos en orden. Devuelve el último resultado y el paso que falló (si alguno)."""
    resultado = Resultado(False, "Plan vacío.")
    for paso in plan:
        skill = registro[paso.skill]
        if skill.requiere_confirmacion:
            descripcion = skill.describir_paso(paso.params)
            if confirmar is None or not confirmar(descripcion):
                resultado = Resultado(False, f"Cancelado: {descripcion}", datos={"cancelado": True})
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
    confirmar: Confirmar | None = None,
    registro: dict[str, Skill] | None = None,
    estado: EstadoMundo | None = None,
    ruta_episodios: Path | None = None,
) -> Resultado:
    registro = registro or REGISTRO
    skill = registro.get(nombre)
    if skill is None:
        return Resultado(False, f"No existe ninguna skill llamada '{nombre}'.")

    falta = skill.validar(params)
    if falta:
        descripcion = skill.parametros.get(falta, falta)
        return Resultado(False, f"Falta un dato para '{nombre}': {descripcion}.", falta=falta)

    estado = estado or EstadoMundo()
    historial: list[dict[str, Any]] = []
    planes: list[list[str]] = []
    replanificado = False

    plan = planificar(nombre, params, estado, registro)
    if plan is None:
        resultado = Resultado(
            False, f"No sé cómo preparar lo necesario para {skill.describir_paso(params)}."
        )
    else:
        planes.append([registro[p.skill].describir_paso(p.params) for p in plan])
        resultado, fallido = _ejecutar_plan(plan, registro, confirmar, historial)

        if fallido is not None:
            # El mundo ha cambiado (o no era como creíamos): se vuelve a mirar y se replanifica.
            estado.refrescar()
            nuevo = planificar(nombre, params, estado, registro)
            # Si el nuevo plan empieza repitiendo el mismo paso que falló, no tiene sentido reintentar.
            if nuevo and nuevo[0] != fallido:
                replanificado = True
                planes.append([registro[p.skill].describir_paso(p.params) for p in nuevo])
                resultado, _ = _ejecutar_plan(nuevo, registro, confirmar, historial)

    registrar_episodio(
        {
            "texto": texto,
            "skill": nombre,
            "parametros": params,
            "confianza": confianza,
            "planes": planes,
            "pasos": historial,
            "replanificado": replanificado,
            "ok": resultado.ok,
            "mensaje": resultado.mensaje,
        },
        ruta_episodios,
    )
    resultado.datos.setdefault("planes", planes)
    return resultado
