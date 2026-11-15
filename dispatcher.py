"""
Cliente de consola del agente.

Toda la lógica vive en core/ (ver ARQUITECTURA.md). Este archivo solo
lee órdenes del teclado y muestra las respuestas.

Uso:
    python dispatcher.py              # clasificador + LLM si duda
    python dispatcher.py --sin-llm    # solo clasificador (no usa la GPU)
    python dispatcher.py --llm-cpu    # LLM sin GPU (lento)

Comandos: llm, seguro, actividad, reanudar, ayuda, salir (core/comandos.py).
Ctrl+Alt+P (ATAJO_PANICO en config.py) para el agente desde cualquier ventana.
"""

from __future__ import annotations

import argparse

from config import LLM_ACTIVO
from core.agente import Agente, limpiar_texto
from core.comandos import AYUDA, atajo_legible, describir_llm, ejecutar_comando, iniciar_atajo_panico, pausar_por_panico  # noqa: E501
from core.traza import configurar_logs

__all__ = ["describir_llm", "main"]   # describir_llm: compatibilidad con quien lo importaba de aquí


def pedir(pregunta: str) -> str:
    return input(f"  {pregunta} > ")


def confirmar(accion: str) -> bool:
    respuesta = input(f"  ⚠ Confirma: {accion}. ¿Continuar? (s/n) > ")
    return respuesta.strip().lower() in ("s", "si", "sí", "y", "yes")


def main() -> None:
    parser = argparse.ArgumentParser(description="Consola del agente")
    parser.add_argument("--sin-llm", action="store_true",
                        help="no usar el LLM (solo el clasificador; no ocupa la GPU)")
    parser.add_argument("--llm-cpu", action="store_true",
                        help="usar el LLM sin GPU (mucho más lento)")
    args = parser.parse_args()

    # Consola: avisos de progreso ("Esperando a que aparezca la ventana…").
    # data/ultima_orden.log: traza completa de la última orden.
    configurar_logs()

    usar_llm = LLM_ACTIVO and not args.sin_llm or args.llm_cpu
    agente = Agente(usar_llm=usar_llm, llm_cpu=args.llm_cpu, canal="consola")
    agente.precargar()
    agente.iniciar_agenda()   # ejecuta las órdenes programadas a su hora

    def panico():
        pausar_por_panico("consola", atajo_legible())
        print(f"\n■ PARADO ({atajo_legible()}): escribe 'reanudar' para seguir.")
    iniciar_atajo_panico(panico)

    print(describir_llm(agente.estado_llm()))
    print(f"Escribe una orden (o 'salir' para terminar). Ctrl+C cancela la orden en curso; "
          f"{atajo_legible()} para el agente desde cualquier ventana.")
    print(AYUDA)
    while True:
        try:
            texto = limpiar_texto(input("> "))
        except (EOFError, KeyboardInterrupt):
            break
        if texto.strip().lower() == "salir":
            break
        if not texto.strip():
            continue
        respuesta = ejecutar_comando(agente, texto, "consola")
        if respuesta is not None:
            print("\n".join("  " + linea for linea in respuesta.splitlines()))
            continue
        try:
            resultado = agente.procesar(texto, pedir=pedir, confirmar=confirmar)
        except KeyboardInterrupt:
            print("✘ Orden cancelada (Ctrl+C).")
            continue
        planes = resultado.datos.get("planes") or []
        if planes and len(planes[-1]) > 1:
            print("  Plan: " + " → ".join(planes[-1]))
        print(("✔ " if resultado.ok else "✘ ") + resultado.mensaje)


if __name__ == "__main__":
    main()
