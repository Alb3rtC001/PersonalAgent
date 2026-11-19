"""
De los episodios a frases de entrenamiento para el clasificador.

Cuenta una orden si:
- salió bien (ok, verificada) y no se ha corregido a mano después;
- la interpretó el LLM (el clasificador no la conocía o dudaba: es lo que
  tiene que aprender; lo que ya acertaba el clasificador no aporta);
- es de una sola skill (el clasificador solo sabe de una intención por frase);
- no es una tarea programada ni de la agenda.

Se guardan en data/frases_aprendidas.json (tus datos: no se suben al
repositorio) y el reentreno las junta con nlu/dataset.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from config import RUTA_DATOS
from core.estado import normalizar
from core.memoria import cargar_episodios

RUTA_APRENDIDAS = RUTA_DATOS / "frases_aprendidas.json"
NO_APRENDIBLES = {None, "varios_pasos", "programar"}


def _clave(frase: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9ñ ]", " ", normalizar(frase)).split())


def frases_de_episodios(episodios: list[dict], ya_conocidas: set[str] | None = None) -> list[tuple[str, str]]:
    """(frase, intención) nuevas, sin repetir y sin las que ya están en el dataset."""
    vistas = set(ya_conocidas or ())
    # Si una frase salió mal alguna vez DESPUÉS de salir bien, no se aprende (la
    # última palabra la tiene lo más reciente).
    ultimo: dict[str, dict] = {}
    for e in episodios:
        if e.get("texto"):
            ultimo[_clave(e["texto"])] = e
    frases = []
    for clave, e in ultimo.items():
        if (not e.get("ok") or e.get("rechazada") or e.get("corregido") or e.get("origen") != "llm"
                or e.get("skill") in NO_APRENDIBLES or not clave or clave in vistas):
            continue
        vistas.add(clave)
        frases.append((e["texto"].strip(), e["skill"]))
    return frases


def frases_rechazadas(episodios: list[dict], limite: int = 20) -> list[str]:
    """Las últimas órdenes que no se entendieron (para que decidas si enseñarlas)."""
    vistas, frases = set(), []
    for e in reversed(episodios):
        clave = _clave(e.get("texto") or "")
        if e.get("rechazada") and clave and clave not in vistas:
            vistas.add(clave)
            frases.append(e["texto"].strip())
        if len(frases) >= limite:
            break
    return frases


def cargar_aprendidas(ruta: Path | None = None) -> list[tuple[str, str]]:
    try:
        datos = json.loads(Path(ruta or RUTA_APRENDIDAS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [(d["frase"], d["intencion"]) for d in datos if d.get("frase") and d.get("intencion")]


def actualizar_aprendidas(base: list[tuple[str, str]], ruta_episodios: Path | None = None,
                          ruta: Path | None = None) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """
    Añade a data/frases_aprendidas.json las frases nuevas de los episodios.
    Devuelve (todas las aprendidas, las nuevas de esta vez).
    """
    ruta = Path(ruta or RUTA_APRENDIDAS)
    aprendidas = cargar_aprendidas(ruta)
    conocidas = {_clave(f) for f, _ in base} | {_clave(f) for f, _ in aprendidas}
    nuevas = frases_de_episodios(cargar_episodios(ruta_episodios), conocidas)
    if nuevas:
        aprendidas += nuevas
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps([{"frase": f, "intencion": i} for f, i in aprendidas],
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    return aprendidas, nuevas
