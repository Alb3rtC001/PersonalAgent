"""
Adaptador: convierte una plantilla grabada (recorder/templates.json) en
una skill más del catálogo.

Qué plantillas se publican como skill, y con qué descripción,
precondiciones y efectos, se decide en recorder/catalogo.json:

    {
      "ejecutar_en_steam": {
        "descripcion": "Busca un juego en Steam y lo lanza.",
        "parametro": "juego",
        "descripcion_parametro": "Nombre del juego",
        "precondiciones": {"visible:steam": true},
        "efectos": {"lanzado:{juego}": true},
        "coste": 2,
        "requiere_confirmacion": true,   // opcional: confirmar siempre
        "confirmar_si_llm": false        // opcional: confirmar si lo interpretó el LLM
      }
    }

Así una plantilla de pruebas o a medio grabar no aparece sola en el
catálogo (y en el futuro, en lo que ve el LLM).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.skills.base import Resultado, Skill
from recorder.player import (
    _extraer_titulo_ventana_objetivo,
    reproducir_plantilla,
    tiene_pasos_definitivos,
)

RUTA_RECORDER = Path(__file__).resolve().parent.parent.parent / "recorder"
RUTA_PLANTILLAS = RUTA_RECORDER / "templates.json"
RUTA_CATALOGO = RUTA_RECORDER / "catalogo.json"


def _leer_json(ruta: Path) -> dict:
    if not ruta.exists():
        return {}
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


class SkillPlantilla(Skill):
    def __init__(self, nombre: str, plantilla: list[dict], meta: dict[str, Any]):
        self.nombre = nombre
        self.plantilla = plantilla
        self.descripcion = meta.get("descripcion", f"Plantilla grabada '{nombre}'.")
        parametro = meta.get("parametro")
        self.parametros = (
            {parametro: meta.get("descripcion_parametro", parametro)} if parametro else {}
        )
        self._parametro = parametro
        self.PRECONDICIONES = dict(meta.get("precondiciones", {}))
        self.EFECTOS = dict(meta.get("efectos", {}))
        self.coste = int(meta.get("coste", 2))
        # La confirmación se puede pedir desde el catálogo (sobrevive a reconstruir
        # templates.json) o marcando un paso con "definitivo": true en la plantilla.
        self.requiere_confirmacion = (tiene_pasos_definitivos(plantilla)
                                      or bool(meta.get("requiere_confirmacion", False)))
        self.confirmar_si_llm = bool(meta.get("confirmar_si_llm", False))

    def ejecutar(self, **params: Any) -> Resultado:
        slot = str(params.get(self._parametro, "")) if self._parametro else ""
        log = reproducir_plantilla(self.plantilla, slot)
        return Resultado(log.ok, f"Plantilla '{self.nombre}': {log.resumen()}",
                         datos={"pasos": log.pasos})

    def describir(self) -> dict[str, Any]:
        datos = super().describir()
        datos["tipo"] = "plantilla"
        datos["ventana_objetivo"] = _extraer_titulo_ventana_objetivo(self.plantilla)
        return datos


def cargar_skills_plantilla(
    ruta_plantillas: Path = RUTA_PLANTILLAS,
    ruta_catalogo: Path = RUTA_CATALOGO,
) -> list[SkillPlantilla]:
    plantillas = _leer_json(ruta_plantillas)
    catalogo = _leer_json(ruta_catalogo)
    return [
        SkillPlantilla(nombre, plantillas[nombre], meta)
        for nombre, meta in catalogo.items()
        if nombre in plantillas
    ]
