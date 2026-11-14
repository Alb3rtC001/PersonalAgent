"""
Cliente de consola del agente.

Toda la lógica vive en core/ (ver ARQUITECTURA.md). Este archivo solo
lee órdenes del teclado y muestra las respuestas.

Uso:
    python dispatcher.py              # clasificador + LLM si duda
    python dispatcher.py --sin-llm    # solo clasificador (no usa la GPU)
    python dispatcher.py --llm-cpu    # LLM sin GPU (lento)

En marcha: 'llm off' / 'llm on' / 'llm'.
"""

from __future__ import annotations

import argparse

from config import LLM_ACTIVO
from core.agente import Agente, limpiar_texto
from core.traza import configurar_logs


def pedir(pregunta: str) -> str:
    return input(f"  {pregunta} > ")


def confirmar(accion: str) -> bool:
    respuesta = input(f"  ⚠ Acción definitiva: {accion}. ¿Continuar? (s/n) > ")
    return respuesta.strip().lower() in ("s", "si", "sí", "y", "yes")


def describir_llm(estado: dict) -> str:
    gpu = ""
    if estado.get("vram_libre_mib") is not None:
        gpu = f" GPU: {estado['vram_libre_mib']} MiB libres, {estado['temperatura_gpu']} °C."
    if not estado["activo"]:
        return "LLM desactivado: solo clasificador, sin usar la GPU." + gpu
    carga = "cargado" if estado["cargado"] else "se cargará cuando haga falta"
    donde = "GPU" if estado["gpu"] else "CPU"
    if estado["cargado"] and estado.get("capas_en_gpu") is not None and estado.get("capas_totales"):
        donde = f"{estado['capas_en_gpu']} de {estado['capas_totales']} capas en la GPU"
        if estado.get("vram_llm_mib"):
            donde += f", {estado['vram_llm_mib']} MiB"
    limite = f", límite {estado['vram_max_mib']} MiB" if estado.get("vram_max_mib") else ""
    return f"LLM activo ({estado['modelo']}, {donde}{limite}, {carga})." + gpu


def comando_llm(agente: Agente, texto: str) -> bool:
    """Comandos 'llm', 'llm on', 'llm off'. Devuelve True si el texto era uno de ellos."""
    partes = texto.strip().lower().split()
    if not partes or partes[0] != "llm" or len(partes) > 2:
        return False
    if len(partes) == 2 and partes[1] not in ("on", "off"):
        return False
    if len(partes) == 2:
        agente.activar_llm(partes[1] == "on")
    print("  " + describir_llm(agente.estado_llm()))
    return True


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
    agente = Agente(usar_llm=usar_llm, llm_cpu=args.llm_cpu)
    agente.precargar()
    print(describir_llm(agente.estado_llm()))
    print("Escribe una orden (o 'salir' para terminar). Ctrl+C cancela la orden en curso.")
    print("'llm off' / 'llm on' desactiva o activa el LLM; 'llm' muestra su estado.")
    while True:
        try:
            texto = limpiar_texto(input("> "))
        except (EOFError, KeyboardInterrupt):
            break
        if texto.strip().lower() == "salir":
            break
        if not texto.strip() or comando_llm(agente, texto):
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
