"""
Router híbrido: frase → skill + parámetros.

1. Clasificador propio (nlu/): rápido (milisegundos) y entrenado con tus
   frases. Si está seguro, su respuesta se usa directamente.
2. LLM local (core/llm.py, Qwen3-8B por defecto): solo cuando el clasificador no está seguro
   (confianza baja, intención "ninguna" o una intención sin skill) o cuando
   la frase tiene palabras desconocidas fuera del valor extraído (p. ej. un
   verbo nuevo: en "reinicia steam" el clasificador solo vería "steam").

Cada Interpretacion dice de dónde salió (`origen`): "clasificador" o "llm".
Si el LLM no está disponible, se comporta como el router v0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from config import LLM_ACTIVO, UMBRAL_CONFIANZA
from core.estado import normalizar
from core.registro import REGISTRO
from core.skills.base import Skill
from nlu.slots import extraer_slot
from nlu.vocabulary import tokenizar

log = logging.getLogger("personalagent")

# texto -> (intención, confianza, palabras desconocidas)
Clasificador = Callable[[str], tuple[str, float, list[str]]]


@dataclass
class Interpretacion:
    texto: str
    intencion: str
    confianza: float
    skill: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    motivo_rechazo: str | None = None
    origen: str = "clasificador"


class ClasificadorBow:
    """El clasificador bag-of-words de nlu/ (necesita nlu/modelo.pt: python nlu/training.py)."""

    def __init__(self):
        from nlu.model import cargar_modelo
        from nlu.vocabulary import cargar_vocabulario
        self.vocab, intenciones = cargar_vocabulario()
        self.idx_a_intencion = {v: k for k, v in intenciones.items()}
        self.modelo = cargar_modelo()

    def __call__(self, texto: str) -> tuple[str, float, list[str]]:
        from nlu.model import predecir_proba
        from nlu.vocabulary import vectorizar_bow
        tokens = tokenizar(texto)
        probas = predecir_proba(self.modelo, vectorizar_bow(tokens, self.vocab))
        idx = probas.argmax().item()
        return self.idx_a_intencion[idx], probas[idx].item(), [t for t in tokens if t not in self.vocab]


def _desconocidas_fuera_del_slot(desconocidas: list[str], slot: str) -> list[str]:
    en_slot = set(tokenizar(slot))
    return [p for p in desconocidas if p not in en_slot]


class Router:
    def __init__(self, registro: dict[str, Skill] | None = None,
                 umbral: float = UMBRAL_CONFIANZA,
                 clasificador: Clasificador | None = None,
                 llm=None, usar_llm: bool = LLM_ACTIVO):
        self.registro = registro or REGISTRO
        self.umbral = umbral
        self.clasificador = clasificador or ClasificadorBow()
        if llm is None and usar_llm:
            from core.llm import InterpreteLLM
            llm = InterpreteLLM(self.registro)
        self.llm = llm

    def precargar(self) -> None:
        """Arranca el LLM por adelantado (para que la primera orden dudosa no espere)."""
        if self.llm is not None:
            self.llm.disponible()

    def clasificar(self, texto: str) -> tuple[str, float]:
        intencion, confianza, _ = self.clasificador(texto)
        return intencion, confianza

    def interpretar_clasificador(self, texto: str) -> tuple[Interpretacion, bool]:
        """Interpretación del clasificador y si conviene consultar al LLM."""
        intencion, confianza, desconocidas = self.clasificador(texto)
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
            slot = extraer_slot(texto, intencion)
            interp.skill = intencion
            interp.params = self.registro[intencion].parametros_desde_slot(slot)
            # La respuesta vale si no hay LLM, pero se le pregunta si hay señales
            # de que el clasificador ha acertado "de casualidad":
            # - ninguna frase disparadora reconocida: el valor es la frase entera
            # - palabras desconocidas fuera del valor (un verbo nuevo)
            # - palabras desconocidas en un valor de varias palabras ("me apetece cs2")
            sin_disparador = normalizar(slot) == normalizar(texto)
            fuera = _desconocidas_fuera_del_slot(desconocidas, slot)
            dentro = len(slot.split()) > 1 and any(p in tokenizar(slot) for p in desconocidas)
            return interp, sin_disparador or bool(fuera) or dentro
        return interp, True

    def interpretar(self, texto: str) -> Interpretacion:
        interp, dudosa = self.interpretar_clasificador(texto)
        if not dudosa or self.llm is None:
            return interp

        r = self.llm.interpretar(texto)
        if r.skill is None and r.motivo == "El LLM local no está disponible.":
            return interp  # sin LLM: lo que dijo el clasificador
        log.debug("LLM: %s", r.crudo)
        # Si ambos coinciden en la skill y el LLM reformuló un valor que no está
        # en la frase ("tareas administrativas"), vale más el del clasificador,
        # que siempre es un trozo literal de lo que dijo el usuario.
        if interp.skill and (r.skill or r.propuesta) == interp.skill:
            params = dict(r.params)
            for clave in r.no_anclados:
                if interp.params.get(clave):
                    params[clave] = interp.params[clave]
            return Interpretacion(texto, interp.skill, interp.confianza, skill=interp.skill,
                                  params=params, origen="llm")
        params = dict(r.params) if r.skill else {}
        return Interpretacion(
            texto, r.skill or "ninguna", interp.confianza, skill=r.skill, params=params,
            motivo_rechazo=None if r.skill else r.motivo, origen="llm",
        )
