"""
Órdenes compuestas a partir de lo que repites (data/episodios.jsonl).

Dos señales:
1. Planes de varios pasos que el LLM te ha hecho varias veces con la misma
   forma ("busca X en opera": Ctrl+L → escribir X → Enter). Si un valor cambia
   de una vez a otra (X), pasa a ser un parámetro de la orden nueva.
2. Órdenes sueltas que das una detrás de otra, siempre igual ("abre steam" y
   enseguida "ve a la biblioteca"), en menos de VENTANA_SEGUIDAS segundos.

Una propuesta aceptada se guarda en data/compuestas/<nombre>.json y es una
skill más (core/skills/compuesta.py): el LLM la ve en su catálogo y ya no
tiene que planear esos pasos cada vez.

    python -m aprendizaje.propuestas                  # ver propuestas
    python -m aprendizaje.propuestas --crear 1 nombre # aceptar la 1 con ese nombre
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.estado import normalizar  # noqa: E402
from core.memoria import cargar_episodios  # noqa: E402

MIN_REPETICIONES = 3
VENTANA_SEGUIDAS = 90       # segundos entre dos órdenes para contarlas como seguidas
MAX_SEGUIDAS = 3


@dataclass
class Propuesta:
    pasos: list[tuple[str, dict]]           # con "{p1}"... donde va un parámetro
    parametros: dict[str, str]              # p1 -> descripción
    veces: int
    frases: list[str] = field(default_factory=list)
    tipo: str = "plan"                      # "plan" (del LLM) o "seguidas"

    def describir(self) -> str:
        pasos = " → ".join(f"{s}({', '.join(f'{k}={v!r}' for k, v in p.items())})" for s, p in self.pasos)
        origen = "planes que te hizo el LLM" if self.tipo == "plan" else "órdenes que das seguidas"
        ejemplo = f" Ej.: «{self.frases[-1]}»." if self.frases else ""
        return f"{self.veces} veces ({origen}): {pasos}.{ejemplo}"


def _norm(valor) -> str:
    return normalizar(str(valor)).strip()


def _con_parametros(grupo: list[list[tuple[str, dict]]]) -> tuple[list[tuple[str, dict]], dict[str, str]]:
    """Los pasos comunes; donde un valor cambia entre repeticiones, un parámetro {p1}, {p2}..."""
    plantilla, parametros = [], {}
    for i, (skill, params) in enumerate(grupo[0]):
        nuevos = {}
        for clave in params:
            valores = [g[i][1].get(clave, "") for g in grupo]
            if len({_norm(v) for v in valores}) == 1:
                nuevos[clave] = params[clave]
            else:
                nombre = f"p{len(parametros) + 1}"
                parametros[nombre] = f"{clave} de {skill} (p. ej. '{valores[-1]}')"
                nuevos[clave] = "{" + nombre + "}"
        plantilla.append((skill, nuevos))
    return plantilla, parametros


INVERSAS = {("abrir_aplicacion", "cerrar_aplicacion"), ("cerrar_aplicacion", "abrir_aplicacion")}


def tiene_sentido(pasos: list[tuple[str, dict]]) -> bool:
    """Fuera lo que no es una costumbre útil: repetir la misma orden o abrir y cerrar la misma app."""
    if len({json.dumps(p, sort_keys=True) for p in pasos}) == 1:
        return False
    for (s1, p1), (s2, p2) in zip(pasos, pasos[1:]):
        if (s1, s2) in INVERSAS and _norm(p1.get("aplicacion", "")) == _norm(p2.get("aplicacion", "")):
            return False
    return True


def _contenida(corta: list, larga: list) -> bool:
    n = len(corta)
    return any(larga[i:i + n] == corta for i in range(len(larga) - n + 1))


def _forma(pasos: list[tuple[str, dict]]) -> tuple:
    return tuple((s, tuple(sorted(p))) for s, p in pasos)


def _agrupar(secuencias: list[tuple[list[tuple[str, dict]], str]], tipo: str) -> list[Propuesta]:
    grupos: dict[tuple, list] = defaultdict(list)
    for pasos, frase in secuencias:
        if tiene_sentido(pasos):
            grupos[_forma(pasos)].append((pasos, frase))
    propuestas = []
    for miembros in grupos.values():
        if len(miembros) < MIN_REPETICIONES:
            continue
        plantilla, parametros = _con_parametros([p for p, _ in miembros])
        # Demasiado variable (todo es parámetro): no es una costumbre, es casualidad.
        fijos = sum(1 for _, p in plantilla for v in p.values() if "{" not in str(v))
        if len(parametros) > max(1, fijos):
            continue
        propuestas.append(Propuesta(plantilla, parametros, len(miembros),
                                    list(dict.fromkeys(f for _, f in miembros if f)), tipo))
    return propuestas


def _momento(e: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(e["momento"])
    except (KeyError, ValueError):
        return None


def proponer(episodios: list[dict], ya_hechas: set[str] | None = None) -> list[Propuesta]:
    buenos = [e for e in episodios if e.get("ok") and not e.get("rechazada") and not e.get("corregido")
              and e.get("origen") != "agenda" and e.get("skill") not in (None, "programar")]

    # 1. Planes de varios pasos del LLM que se repiten.
    planes = [([(s, dict(p)) for s, p in e["pasos_orden"]], e.get("texto", ""))
              for e in buenos if e.get("skill") == "varios_pasos" and e.get("pasos_orden")]
    propuestas = _agrupar(planes, "plan")

    # 2. Órdenes sueltas seguidas (pares y tríos) que se repiten.
    sueltas = [e for e in buenos if e.get("skill") != "varios_pasos" and "parametros" in e and _momento(e)]
    seguidas = []
    for n in range(2, MAX_SEGUIDAS + 1):
        for i in range(len(sueltas) - n + 1):
            tramo = sueltas[i:i + n]
            if all((_momento(b) - _momento(a)).total_seconds() <= VENTANA_SEGUIDAS for a, b in zip(tramo, tramo[1:])):
                seguidas.append(([(e["skill"], dict(e["parametros"])) for e in tramo],
                                 " y luego ".join(e.get("texto", "") for e in tramo)))
    propuestas += _agrupar(seguidas, "seguidas")

    # Un par que solo aparece dentro de un trío igual de frecuente: basta con el trío.
    propuestas = [p for p in propuestas
                  if not any(len(o.pasos) > len(p.pasos) and o.veces >= p.veces and _contenida(p.pasos, o.pasos)
                             for o in propuestas)]
    hechas = ya_hechas or set()
    propuestas = [p for p in propuestas if json.dumps(p.pasos, sort_keys=True) not in hechas]
    return sorted(propuestas, key=lambda p: (-p.veces, -len(p.pasos)))


def main() -> None:
    from core.skills.compuesta import crear_compuesta, pasos_hechos
    ap = argparse.ArgumentParser(description="Órdenes compuestas a partir de lo que repites.")
    ap.add_argument("--crear", nargs=2, metavar=("N", "NOMBRE"), help="acepta la propuesta N con ese nombre")
    args = ap.parse_args()
    propuestas = proponer(cargar_episodios(), pasos_hechos())
    if args.crear:
        n, nombre = int(args.crear[0]), args.crear[1]
        if not 1 <= n <= len(propuestas):
            sys.exit(f"No hay propuesta {n} (hay {len(propuestas)}).")
        archivo = crear_compuesta(nombre, propuestas[n - 1])
        print(f"Creada la orden compuesta '{archivo.stem}' ({archivo}). Reinicia el agente para usarla.")
        return
    if not propuestas:
        print(f"Aún no hay nada que se repita al menos {MIN_REPETICIONES} veces.")
    for i, p in enumerate(propuestas, 1):
        print(f"{i}. {p.describir()}")


if __name__ == "__main__":
    main()
