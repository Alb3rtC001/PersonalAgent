"""
build_templates.py

Lee todas las grabaciones crudas (recordings.json) y, para cada acción
que ya tenga 2 o más grabaciones, las generaliza en una plantilla
reutilizable guardada en templates.json.

Usa la tolerancia de píxeles de cada acción (configurable por plantilla).
"""

import json
from pathlib import Path

from storage import cargar_grabaciones
from generalist import generalizar, ErrorGeneralizacion

RUTA_PLANTILLAS = Path(__file__).parent / "templates.json"


def cargar_plantillas() -> dict:
    if not RUTA_PLANTILLAS.exists():
        return {}
    with open(RUTA_PLANTILLAS, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_plantillas(plantillas: dict) -> None:
    with open(RUTA_PLANTILLAS, "w", encoding="utf-8") as f:
        json.dump(plantillas, f, ensure_ascii=False, indent=2)


def construir_plantillas() -> None:
    grabaciones = cargar_grabaciones()
    plantillas = cargar_plantillas()

    if not grabaciones:
        print("No hay ninguna grabación todavía en recordings.json.")
        return

    print("=== Grabaciones disponibles ===")
    for nombre, entrada in grabaciones.items():
        lista = entrada["grabaciones"]
        tolerancia = entrada["tolerancia_px"]
        ids = "  ".join(f"#{i+1:02d}({len(g)}p)" for i, g in enumerate(lista))
        ya_tiene = "✓ plantilla existente" if nombre in plantillas else ""
        print(f"  {nombre}: {len(lista)} grabación(es) "
              f"[{ids}] tolerancia={tolerancia}px {ya_tiene}")
    print()

    generadas = 0
    for nombre_accion, entrada in grabaciones.items():
        lista_grabaciones = entrada["grabaciones"]
        tolerancia_px = entrada["tolerancia_px"]

        if len(lista_grabaciones) < 2:
            g = lista_grabaciones[0]
            print(f"[SKIP] '{nombre_accion}': solo 1 grabación "
                  f"(#01 con {len(g)} pasos). Necesitas al menos 2.")
            continue
        try:
            plantilla = generalizar(lista_grabaciones, tolerancia_px=tolerancia_px)
            plantillas[nombre_accion] = plantilla
            print(f"[ OK ] '{nombre_accion}': plantilla generada "
                  f"({len(lista_grabaciones)} grabaciones → {len(plantilla)} pasos, "
                  f"tolerancia={tolerancia_px}px).")
            generadas += 1
        except ErrorGeneralizacion as e:
            print(f"[FAIL] '{nombre_accion}': no se pudo generalizar -> {e}")

    if generadas > 0:
        guardar_plantillas(plantillas)
        print(f"\n{generadas} plantilla(s) guardadas en {RUTA_PLANTILLAS}")
    else:
        print("\nNinguna plantilla nueva generada.")


if __name__ == "__main__":
    construir_plantillas()