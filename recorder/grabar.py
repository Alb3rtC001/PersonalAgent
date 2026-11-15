"""
Grabar una acción nueva desde la consola (grabadora semántica):

    python -m recorder.grabar

1. Te pide el nombre y qué hace (la descripción es lo que lee el LLM para
   saber cuándo usarla: "Busca una canción en Spotify y la reproduce").
2. Haces la acción con el ratón y el teclado. F9 para terminar.
3. Eliges qué texto escrito cambia cada vez (el parámetro, p. ej. la canción).
4. Se guarda en recorder/grabadas/<nombre>.json y el agente la carga al
   arrancar (en la interfaz: comando "grabar <nombre>", sin reiniciar).
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.skills.grabada import guardar_grabacion, nombre_valido  # noqa: E402
from recorder.grabadora_semantica import GrabadoraSemantica, marcar_parametro, textos_grabados  # noqa: E402


def describir_paso(paso: dict) -> str:
    if paso["tipo"] == "clic":
        c = paso["control"]
        return f"clic en {c['tipo'].replace('Control', '').lower()} '{c['nombre'] or c['id']}' ({paso['ventana']['titulo']})"
    if paso["tipo"] == "escribir":
        return f"escribir '{paso['texto']}'"
    if paso["tipo"] == "teclas":
        return f"teclas '{paso['teclas']}'"
    return "contraseña omitida (ese paso lo harás tú)"


def main() -> None:
    logging.basicConfig(format="  %(message)s")
    logging.getLogger("personalagent").setLevel(logging.INFO)
    nombre = nombre_valido(input("Nombre de la acción (p. ej. buscar en spotify): "))
    if not nombre:
        sys.exit("Hace falta un nombre.")
    descripcion = input("¿Qué hace? (lo leerá el LLM): ").strip()
    print("\nEn 3 segundos empieza la grabación. Haz la acción y pulsa F9 para terminar.")
    for n in (3, 2, 1):
        print(f"  {n}…")
        time.sleep(1)
    grabadora = GrabadoraSemantica()
    grabadora.iniciar()
    print("● GRABANDO (F9 para terminar)")
    grabadora.esperar_fin()
    pasos = grabadora.detener()
    if not pasos:
        sys.exit("No se ha grabado nada.")

    print("\nPasos grabados:")
    for i, paso in enumerate(pasos, 1):
        print(f"  {i}. {describir_paso(paso)}")
    for aviso in grabadora.avisos:
        print(f"  ⚠ {aviso}")

    parametros = {}
    textos = textos_grabados(pasos)
    if textos:
        print("\n¿Alguno de estos textos cambia cada vez (el parámetro)? Enter = ninguno.")
        for n, (_, texto) in enumerate(textos, 1):
            print(f"  {n}. '{texto}'")
        eleccion = input("Número: ").strip()
        if eleccion.isdigit() and 1 <= int(eleccion) <= len(textos):
            parametro = nombre_valido(input("Nombre del parámetro (p. ej. cancion): ")) or "texto"
            pasos = marcar_parametro(pasos, textos[int(eleccion) - 1][0], parametro)
            parametros[parametro] = input(f"¿Qué es '{parametro}'? (p. ej. el nombre de la canción): ").strip() \
                or parametro
    archivo = guardar_grabacion(nombre, descripcion, pasos, parametros)
    print(f"\n✔ Guardada en {archivo}. El agente la tendrá disponible al arrancar.")


if __name__ == "__main__":
    main()
