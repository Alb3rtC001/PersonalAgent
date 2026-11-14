"""
Evaluación del router con frases que NO están en el dataset de entrenamiento
(evaluacion/ordenes.json). Mide, para cada vía:

    clasificador  solo el clasificador de nlu/ (router v0)
    llm           solo el LLM local
    hibrido       el router actual (clasificador y, si duda, LLM)

Aciertos de skill y de skill + parámetros, y tiempo por frase.

    python -m evaluacion.evaluar                 # las tres vías
    python -m evaluacion.evaluar --via llm       # solo una
    python -m evaluacion.evaluar --modelo models\\otro\\modelo.gguf   # comparar modelos

Con --modelo se arranca un llama-server propio con ese GGUF (en otro puerto).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.estado import normalizar  # noqa: E402
from core.llm import InterpreteLLM, ServidorLLM  # noqa: E402
from core.registro import REGISTRO  # noqa: E402
from core.router import Interpretacion, Router  # noqa: E402
from core.teclado import ErrorTeclas, interpretar_teclas  # noqa: E402

RUTA_ORDENES = Path(__file__).parent / "ordenes.json"


def _norm(valor: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", normalizar(valor))).strip()


def _mismas_teclas(a: str, b: str) -> bool:
    """'flecha abajo dos veces' y 'flecha abajo 2 veces' pulsan lo mismo."""
    try:
        return interpretar_teclas(a) == interpretar_teclas(b)
    except ErrorTeclas:
        return False


def params_correctos(esperados: dict, obtenidos: dict) -> bool:
    """Un valor esperado puede ser una lista de alternativas; None en ella = "puede faltar"."""
    for clave, valor in esperados.items():
        validos = [v for v in (valor if isinstance(valor, list) else [valor])]
        if clave not in obtenidos:
            if None not in validos:
                return False
        elif clave == "teclas":
            if not any(v is not None and _mismas_teclas(obtenidos[clave], v) for v in validos):
                return False
        elif _norm(obtenidos[clave]) not in {_norm(v) for v in validos if v is not None}:
            return False
    return set(obtenidos) <= set(esperados)


def pasos_esperados(o: dict) -> list[tuple[str, dict]]:
    """[] si la orden se debe rechazar; si no, la lista de (skill, parametros)."""
    if "pasos" in o:
        return [(p["skill"], p["parametros"]) for p in o["pasos"]]
    return [] if o["skill"] == "ninguna" else [(o["skill"], o["parametros"])]


def _describir(pasos) -> str:
    if not pasos:
        return "ninguna"
    return " → ".join(f"{s}{p or ''}" for s, p in pasos)


def evaluar(nombre: str, interpretar, ordenes: list[dict]) -> dict:
    aciertos_skill = aciertos_total = 0
    fallos = []
    tiempos = []
    for o in ordenes:
        t0 = time.monotonic()
        obtenidos, origen = interpretar(o["frase"])
        tiempos.append(time.monotonic() - t0)
        # "o_bien": otras respuestas igual de válidas (p. ej. abrir la app antes de escribir).
        variantes = [pasos_esperados(o)] + [pasos_esperados(v) for v in o.get("o_bien", [])]
        esperados = variantes[0]
        ok_skill = ok_total = False
        for variante in variantes:
            mismas_skills = [s for s, _ in obtenidos] == [s for s, _ in variante]
            ok_skill = ok_skill or mismas_skills
            if mismas_skills and all(params_correctos(pe, po) for (_, pe), (_, po) in zip(variante, obtenidos)):
                ok_total = True
                break
        aciertos_skill += ok_skill
        aciertos_total += ok_total
        if not ok_total:
            fallos.append(f"  ✘ {o['frase']!r}: esperaba {_describir(esperados)}, "
                          f"obtuvo {_describir(obtenidos)} [{origen}]")
    n = len(ordenes)
    tiempos.sort()
    print(f"\n=== {nombre} ===")
    print(f"skill correcta:              {aciertos_skill}/{n} ({aciertos_skill / n:.0%})")
    print(f"skill y parámetros correctos: {aciertos_total}/{n} ({aciertos_total / n:.0%})")
    print(f"tiempo por frase: mediana {tiempos[n // 2] * 1000:.0f} ms, máximo {tiempos[-1] * 1000:.0f} ms")
    for f in fallos:
        print(f)
    return {"skill": aciertos_skill, "total": aciertos_total, "n": n}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--via", choices=["clasificador", "llm", "hibrido", "todas"], default="todas")
    ap.add_argument("--modelo", type=Path, help="GGUF alternativo para comparar")
    ap.add_argument("--puerto", type=int, default=8767, help="puerto para el servidor de --modelo")
    ap.add_argument("--ordenes", type=Path, default=RUTA_ORDENES,
                    help="archivo de frases (p. ej. evaluacion/ordenes_control.json)")
    ap.add_argument("--plantilla", default=None,
                    help="plantilla de chat de llama-server ('nativa' = la que trae el GGUF)")
    args = ap.parse_args()

    ordenes = json.loads(args.ordenes.read_text(encoding="utf-8"))
    print(f"Frases: {args.ordenes.name} ({len(ordenes)})")
    opciones = {}
    if args.modelo:
        opciones.update(modelo=args.modelo, puerto=args.puerto)
    if args.plantilla:
        opciones["plantilla"] = None if args.plantilla == "nativa" else args.plantilla
    servidor = ServidorLLM(**opciones)
    llm = InterpreteLLM(REGISTRO, servidor=servidor)
    router = Router(REGISTRO, llm=llm, usar_llm=True)
    vias = ["clasificador", "llm", "hibrido"] if args.via == "todas" else [args.via]

    if "llm" in vias or "hibrido" in vias:
        print(f"Modelo: {servidor.modelo.name} (plantilla: {servidor.plantilla or 'nativa'})")
        if servidor.activo():
            print("Aviso: ya había un servidor en ese puerto; se usa ese.")
        t0 = time.monotonic()
        if not servidor.asegurar():
            sys.exit("No se pudo arrancar el LLM.")
        print(f"Carga del modelo: {time.monotonic() - t0:.1f} s")
        try:
            import subprocess
            vram = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader"],
                                  capture_output=True, text=True).stdout.strip()
            print(f"Memoria de GPU en uso con el modelo cargado: {vram}")
        except OSError:
            pass

    def solo_clasificador(frase: str):
        i, _ = router.interpretar_clasificador(frase)
        return ([] if i.motivo_rechazo else [(i.skill, i.params)]), "clasificador"

    def solo_llm(frase: str):
        r = llm.interpretar(frase)
        return (r.pasos or ([(r.skill, r.params)] if r.skill else [])), "llm"

    def hibrido(frase: str):
        i: Interpretacion = router.interpretar(frase)
        return (i.pasos or ([(i.skill, i.params)] if i.skill else [])), i.origen

    funciones = {"clasificador": solo_clasificador, "llm": solo_llm, "hibrido": hibrido}
    try:
        for via in vias:
            evaluar(via, funciones[via], ordenes)
    finally:
        servidor.parar()


if __name__ == "__main__":
    main()
