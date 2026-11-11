"""
Router v0: frase → skill + parámetros.

Envuelve el clasificador de intención (nlu/) y la extracción de slots.
Cada intención del clasificador se corresponde con la skill del mismo
nombre. En la fase 3 este módulo tendrá un segundo camino con un LLM
local; el clasificador seguirá respondiendo primero cuando esté muy seguro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import UMBRAL_CONFIANZA
from core.registro import REGISTRO
from core.skills.base import Skill
from nlu.model import cargar_modelo, predecir_proba
from nlu.slots import extraer_slot
from nlu.vocabulary import cargar_vocabulario, tokenizar, vectorizar_bow


@dataclass
class Interpretacion:
    texto: str
    intencion: str
    confianza: float
    skill: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    motivo_rechazo: str | None = None


class Router:
    def __init__(self, registro: dict[str, Skill] | None = None,
                 umbral: float = UMBRAL_CONFIANZA):
        self.registro = registro or REGISTRO
        self.umbral = umbral
        self.vocab, intenciones = cargar_vocabulario()
        self.idx_a_intencion = {v: k for k, v in intenciones.items()}
        self.modelo = cargar_modelo()

    def clasificar(self, texto: str) -> tuple[str, float]:
        vector = vectorizar_bow(tokenizar(texto), self.vocab)
        probas = predecir_proba(self.modelo, vector)
        idx = probas.argmax().item()
        return self.idx_a_intencion[idx], probas[idx].item()

    def interpretar(self, texto: str) -> Interpretacion:
        intencion, confianza = self.clasificar(texto)
        interp = Interpretacion(texto, intencion, confianza)

        if intencion == "ninguna":
            interp.motivo_rechazo = f"No he entendido esa orden (confianza={confianza:.2f})."
        elif confianza < self.umbral:
            interp.motivo_rechazo = (
                f"No estoy seguro de lo que pides (¿{intencion}?, "
                f"confianza={confianza:.2f} < umbral {self.umbral})."
            )
        elif intencion not in self.registro:
            interp.motivo_rechazo = f"Entiendo '{intencion}', pero todavía no sé hacerlo."
        else:
            skill = self.registro[intencion]
            interp.skill = intencion
            interp.params = skill.parametros_desde_slot(extraer_slot(texto, intencion))
        return interp
