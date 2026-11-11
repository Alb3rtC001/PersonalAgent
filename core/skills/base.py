"""
Contrato común de todas las skills (lo que el agente sabe hacer).

Una skill puede estar implementada en Python puro, con UI Automation o
reproduciendo una plantilla grabada: al executor y al planificador les
da igual, solo usan este contrato. Ver ARQUITECTURA.md §4.

Precondiciones y efectos (para el planificador)
-----------------------------------------------
Se declaran como plantillas de hechos "predicado:{parametro}":

    PRECONDICIONES = {"visible:steam": True}
    EFECTOS = {"abierta:{aplicacion}": True, "visible:{aplicacion}": True}

A partir de ahí la clase base sabe:
- precondiciones(params) / efectos(params): rellenar las plantillas.
- consigue(hecho, valor): si esta skill puede producir un hecho, y con
  qué parámetros (ej. "visible:steam" -> {"aplicacion": "steam"}).
"""

from __future__ import annotations

import re
import string
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.estado import normalizar


@dataclass
class Resultado:
    ok: bool
    mensaje: str
    datos: dict[str, Any] = field(default_factory=dict)
    # Nombre del parámetro que falta, para que el cliente se lo pida al usuario.
    falta: str | None = None


def _rellenar(plantilla: str, params: dict[str, Any]) -> str:
    valores = {k: normalizar(str(v)) for k, v in params.items()}
    return plantilla.format_map(valores)


def _plantilla_a_regex(plantilla: str) -> re.Pattern:
    partes = []
    for literal, campo, _, _ in string.Formatter().parse(plantilla):
        partes.append(re.escape(literal))
        if campo:
            partes.append(f"(?P<{campo}>.+)")
    return re.compile("^" + "".join(partes) + "$")


class Skill(ABC):
    nombre: str = ""
    descripcion: str = ""
    parametros: dict[str, str] = {}             # obligatorios: nombre -> descripción
    parametros_opcionales: dict[str, str] = {}  # opcionales:   nombre -> descripción
    requiere_confirmacion: bool = False         # acciones irreversibles
    coste: int = 1                              # el planificador prefiere planes baratos
    PRECONDICIONES: dict[str, bool] = {}
    EFECTOS: dict[str, bool] = {}

    # --- Planificación -----------------------------------------------------

    def precondiciones(self, params: dict[str, Any]) -> dict[str, bool]:
        return {_rellenar(h, params): v for h, v in self.PRECONDICIONES.items()}

    def efectos(self, params: dict[str, Any]) -> dict[str, bool]:
        return {_rellenar(h, params): v for h, v in self.EFECTOS.items()}

    def consigue(self, hecho: str, valor: bool = True) -> dict[str, Any] | None:
        """Parámetros con los que esta skill produce `hecho = valor`, o None."""
        hecho = normalizar(hecho)
        for plantilla, v in self.EFECTOS.items():
            if v != valor:
                continue
            m = _plantilla_a_regex(plantilla).match(hecho)
            if m:
                return m.groupdict()
        return None

    # --- Ejecución ---------------------------------------------------------

    def parametros_desde_slot(self, slot: str) -> dict[str, Any]:
        """
        Puente con el router v0 (clasificador + slots.py), que solo
        extrae un valor: se asigna al primer parámetro obligatorio.
        """
        primero = next(iter(self.parametros), None)
        return {primero: slot} if primero and slot else {}

    def validar(self, params: dict[str, Any]) -> str | None:
        """Devuelve el primer parámetro obligatorio que falta, o None."""
        for nombre in self.parametros:
            valor = params.get(nombre)
            if valor is None or (isinstance(valor, str) and not valor.strip()):
                return nombre
        return None

    def describir_paso(self, params: dict[str, Any]) -> str:
        """Frase corta para logs y confirmaciones."""
        args = ", ".join(f"{k}='{v}'" for k, v in params.items())
        return f"{self.nombre}({args})"

    @abstractmethod
    def ejecutar(self, **params: Any) -> Resultado:
        raise NotImplementedError

    def verificar(self, resultado: Resultado) -> bool:
        """Comprueba en el mundo real que la acción tuvo efecto."""
        return resultado.ok

    def describir(self) -> dict[str, Any]:
        """Descripción serializable (para la API y, más adelante, el LLM)."""
        return {
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "parametros": self.parametros,
            "parametros_opcionales": self.parametros_opcionales,
            "requiere_confirmacion": self.requiere_confirmacion,
            "precondiciones": self.PRECONDICIONES,
            "efectos": self.EFECTOS,
        }
