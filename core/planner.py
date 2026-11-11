"""
Planificador (sustituye a planner.py + plan_executor.py).

Dada la skill que se quiere ejecutar y sus parámetros, calcula qué otras
skills hay que ejecutar antes para cumplir sus precondiciones. Trabaja
hacia atrás (regresión, estilo STRIPS):

    ejecutar_en_steam(juego=X)  necesita  visible:steam
        visible:steam  lo consiguen  restaurar_ventana(steam)  [coste 1, necesita abierta:steam y no visible]
                                     abrir_aplicacion(steam)   [coste 3, no necesita nada]

Elige la opción más barata cuyas precondiciones se puedan cumplir con el
estado real (EstadoMundo consulta Windows). No hay operadores escritos a
mano: todo sale de los PRECONDICIONES/EFECTOS que declara cada skill, así
que una skill nueva entra en los planes sin tocar este archivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.estado import EstadoMundo
from core.skills.base import Skill

PROFUNDIDAD_MAX = 4


@dataclass
class Paso:
    skill: str
    params: dict[str, Any] = field(default_factory=dict)


def planificar(
    nombre: str,
    params: dict[str, Any],
    estado: EstadoMundo,
    registro: dict[str, Skill],
) -> list[Paso] | None:
    """Plan completo (pasos previos + la skill pedida), o None si no hay forma."""
    skill = registro[nombre]
    simulado = estado.copia()
    previos = _conseguir(skill.precondiciones(params), simulado, registro, PROFUNDIDAD_MAX)
    if previos is None:
        return None
    return previos + [Paso(nombre, dict(params))]


def _coste(pasos: list[Paso], registro: dict[str, Skill]) -> int:
    return sum(registro[p.skill].coste for p in pasos)


def _conseguir(
    objetivos: dict[str, bool],
    estado: EstadoMundo,
    registro: dict[str, Skill],
    profundidad: int,
) -> list[Paso] | None:
    """
    Pasos para que se cumplan todos los objetivos partiendo de `estado`.
    Modifica `estado` con los efectos simulados del plan elegido.
    """
    pasos: list[Paso] = []
    for hecho, valor in objetivos.items():
        if estado.get(hecho) == valor:
            continue
        if profundidad == 0:
            return None

        mejor: tuple[int, list[Paso], EstadoMundo] | None = None
        for skill in registro.values():
            params = skill.consigue(hecho, valor)
            if params is None:
                continue
            simulado = estado.copia()
            previos = _conseguir(skill.precondiciones(params), simulado, registro, profundidad - 1)
            if previos is None:
                continue
            simulado.aplicar(skill.efectos(params))
            candidato = previos + [Paso(skill.nombre, params)]
            coste = _coste(candidato, registro)
            if mejor is None or coste < mejor[0]:
                mejor = (coste, candidato, simulado)

        if mejor is None:
            return None
        pasos += mejor[1]
        estado.adoptar(mejor[2])

    # Un paso posterior podría haber deshecho un objetivo ya conseguido.
    if not all(estado.get(h) == v for h, v in objetivos.items()):
        return None
    return pasos
