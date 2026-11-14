"""
Skills para consultar y cancelar órdenes programadas.

(Programar no es una skill: cualquier orden con una expresión de tiempo al
principio o al final, "abre steam dentro de 5 min", se programa. Ver
core/tiempo.py y Agente.)
"""

from __future__ import annotations

import re
from datetime import datetime

from core.agenda import Agenda
from core.estado import normalizar
from core.skills.base import Resultado, Skill
from core.tiempo import describir_cuando

_ACTUAL: Agenda | None = None


def usar_agenda(agenda: Agenda) -> None:
    """El agente indica qué agenda usan estas skills (la suya)."""
    global _ACTUAL
    _ACTUAL = agenda


def agenda_actual() -> Agenda:
    global _ACTUAL
    if _ACTUAL is None:
        _ACTUAL = Agenda()
    return _ACTUAL


def _linea(tarea, ahora: datetime) -> str:
    return f"#{tarea.id} {describir_cuando(tarea.cuando, ahora)}: {tarea.texto}"


class VerTareas(Skill):
    nombre = "ver_tareas"
    descripcion = "Dice qué órdenes hay programadas para más tarde (la agenda)."
    parametros = {}

    def ejecutar(self) -> Resultado:
        pendientes = agenda_actual().pendientes()
        if not pendientes:
            return Resultado(True, "No hay ninguna tarea programada.", datos={"tareas": []})
        ahora = datetime.now()
        return Resultado(True, f"{len(pendientes)} tarea(s) programada(s): "
                               + "; ".join(_linea(t, ahora) for t in pendientes) + ".",
                         datos={"tareas": [t.id for t in pendientes]})


class CancelarTarea(Skill):
    nombre = "cancelar_tarea"
    descripcion = "Cancela una orden programada (por su número, 'la última' o 'todas')."
    parametros = {"tarea": "Número de la tarea (p. ej. '3'), 'la última' o 'todas'"}

    def ejecutar(self, tarea: str = "") -> Resultado:
        agenda = agenda_actual()
        pendientes = agenda.pendientes()
        if not pendientes:
            return Resultado(False, "No hay ninguna tarea programada que cancelar.")
        texto = normalizar(tarea)
        if "todas" in texto:
            elegidas = pendientes
        elif "ultima" in texto:
            elegidas = [max(pendientes, key=lambda t: t.id)]
        elif "proxima" in texto or "siguiente" in texto:
            elegidas = [pendientes[0]]
        else:
            numero = re.search(r"\d+", texto)
            elegidas = [t for t in pendientes if numero and t.id == int(numero.group())]
            if not elegidas:
                return Resultado(False, f"No hay ninguna tarea pendiente con el número '{tarea}'. Pendientes: "
                                        + ", ".join(f"#{t.id}" for t in pendientes) + ".")
        canceladas = [t for t in elegidas if agenda.cancelar(t.id)]
        return Resultado(bool(canceladas), "Cancelada(s): " + ", ".join(f"#{t.id} {t.texto}" for t in canceladas)
                         + "." if canceladas else "No se pudo cancelar (ya se había ejecutado).",
                         datos={"canceladas": [t.id for t in canceladas]})


SKILLS_DE_AGENDA = {VerTareas.nombre, CancelarTarea.nombre}
