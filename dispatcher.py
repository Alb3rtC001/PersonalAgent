"""
Cliente de consola del agente.

Toda la lógica vive en core/ (ver ARQUITECTURA.md). Este archivo solo
lee órdenes del teclado y muestra las respuestas.

Uso:
    python dispatcher.py
"""

from __future__ import annotations

from core.agente import Agente


def pedir(pregunta: str) -> str:
    return input(f"  {pregunta} > ")


def confirmar(accion: str) -> bool:
    respuesta = input(f"  ⚠ Acción definitiva: {accion}. ¿Continuar? (s/n) > ")
    return respuesta.strip().lower() in ("s", "si", "sí", "y", "yes")


def main() -> None:
    agente = Agente()
    print("Escribe una orden (o 'salir' para terminar)")
    while True:
        try:
            texto = input("> ")
        except EOFError:
            break
        if texto.strip().lower() == "salir":
            break
        if not texto.strip():
            continue
        resultado = agente.procesar(texto, pedir=pedir, confirmar=confirmar)
        planes = resultado.datos.get("planes") or []
        if planes and len(planes[-1]) > 1:
            print("  Plan: " + " → ".join(planes[-1]))
        print(("✔ " if resultado.ok else "✘ ") + resultado.mensaje)


if __name__ == "__main__":
    main()
