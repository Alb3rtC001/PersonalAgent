"""
Órdenes compuestas: varias skills seguidas con un nombre (data/compuestas/*.json).

Las crea la fase 7 a partir de lo que repites (aprendizaje/propuestas.py), o a
mano. Cada paso es una skill del catálogo con sus parámetros; "{p1}" en un
valor se sustituye por el parámetro de la orden. Se ejecutan con el executor
(validar, ejecutar y verificar cada paso); si uno falla, se para ahí.

    {"nombre": "buscar_en_opera", "descripcion": "...",
     "parametros": {"p1": "texto a buscar"},
     "pasos": [["pulsar_teclas", {"teclas": "control l", "aplicacion": "opera"}],
               ["escribir_texto", {"texto": "{p1}", "aplicacion": "opera"}],
               ["pulsar_teclas", {"teclas": "enter", "aplicacion": "opera"}]],
     "frases": ["busca recetas en opera"]}
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from config import RUTA_DATOS
from core import control
from core.skills.base import Resultado, Skill

log = logging.getLogger("personalagent")

RUTA_COMPUESTAS = RUTA_DATOS / "compuestas"
NIVELES = ("lectura", "bajo", "medio", "alto")
PAUSA_ENTRE_PASOS = 0.4


def _sustituir(valor: Any, params: dict[str, Any]) -> Any:
    if not isinstance(valor, str):
        return valor
    return re.sub(r"\{(\w+)\}", lambda m: str(params.get(m.group(1), m.group(0))), valor)


class SkillCompuesta(Skill):
    def __init__(self, datos: dict[str, Any], registro: dict[str, Skill] | None = None):
        self.nombre = datos["nombre"]
        self.parametros = dict(datos.get("parametros") or {})
        self.pasos = [(s, dict(p)) for s, p in datos["pasos"]]
        self.frases = list(datos.get("frases") or [])
        resumen = " → ".join(s for s, _ in self.pasos)
        self.descripcion = datos.get("descripcion") or f"Orden compuesta: {resumen}."
        self._registro = registro
        self.interpretar_con_llm = bool(self.parametros)
        self.parametros_literales = frozenset(self.parametros)   # p. ej. el texto a buscar, tal cual
        self.coste = len(self.pasos)
        self.riesgo = self._riesgo_maximo()

    @property
    def registro(self) -> dict[str, Skill]:
        if self._registro is None:
            from core.registro import REGISTRO
            self._registro = REGISTRO
        return self._registro

    def _riesgo_maximo(self) -> str:
        """El del paso más delicado (si no se conoce aún el catálogo, "alto": se confirma)."""
        try:
            niveles = [getattr(self.registro.get(s), "riesgo", "alto") for s, _ in self.pasos]
        except Exception:
            return "alto"
        return max(niveles, key=lambda n: NIVELES.index(n) if n in NIVELES else len(NIVELES))

    def ejecutar(self, **params: Any) -> Resultado:
        from core.executor import ejecutar_orden
        mensajes = []
        for i, (skill, plantilla) in enumerate(self.pasos, 1):
            if i > 1:
                control.comprobar()   # botón de pánico
                time.sleep(PAUSA_ENTRE_PASOS)
            concretos = {k: _sustituir(v, params) for k, v in plantilla.items()}
            r = ejecutar_orden(skill, concretos, texto=f"[{self.nombre}]", origen="compuesta",
                               confirmar=lambda _: True,   # la orden compuesta ya se confirmó entera
                               registro=self.registro, registrar=False)
            mensajes.append(r.mensaje)
            if not r.ok:
                return Resultado(False, f"'{self.nombre}', paso {i} de {len(self.pasos)} ({skill}): {r.mensaje}",
                                 datos={"paso": i})
        return Resultado(True, f"'{self.nombre}' hecha ({len(self.pasos)} pasos). Último: {mensajes[-1]}",
                         datos={"pasos": len(self.pasos)})


def nombre_valido(nombre: str) -> str:
    from core.estado import normalizar
    return re.sub(r"[^a-z0-9]+", "_", normalizar(nombre)).strip("_")


def crear_compuesta(nombre: str, propuesta, ruta: Path | None = None) -> Path:
    """Guarda una propuesta (aprendizaje/propuestas.py) como orden compuesta."""
    ruta = Path(ruta or RUTA_COMPUESTAS)
    nombre = nombre_valido(nombre)
    if not nombre:
        raise ValueError("El nombre no puede estar vacío.")
    ruta.mkdir(parents=True, exist_ok=True)
    datos = {"nombre": nombre,
             "descripcion": f"Orden compuesta aprendida de tu uso: {' → '.join(s for s, _ in propuesta.pasos)}.",
             "parametros": propuesta.parametros, "pasos": [[s, p] for s, p in propuesta.pasos],
             "frases": propuesta.frases[-5:]}
    archivo = ruta / f"{nombre}.json"
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return archivo


def cargar_compuestas(ruta: Path | None = None) -> list[SkillCompuesta]:
    ruta = Path(ruta or RUTA_COMPUESTAS)
    skills = []
    for archivo in sorted(ruta.glob("*.json")) if ruta.is_dir() else []:
        try:
            skills.append(SkillCompuesta(json.loads(archivo.read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError) as e:
            log.warning("No pude cargar la orden compuesta %s: %s", archivo.name, e)
    return skills


def pasos_hechos(ruta: Path | None = None) -> set[str]:
    """Las ya creadas (para no volver a proponerlas)."""
    return {json.dumps([(s, p) for s, p in c.pasos], sort_keys=True) for c in cargar_compuestas(ruta)}
