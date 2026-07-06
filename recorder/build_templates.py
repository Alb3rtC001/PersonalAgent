"""
build_templates.py

Lee todas las grabaciones crudas (recordings.json) y, para cada acción
que ya tenga 2 o más grabaciones, las generaliza en una plantilla
reutilizable guardada en templates.json.

Ejecútalo manualmente cada vez que hayas grabado una demostración
nueva:

    python build_templates.py
"""

import json
from pathlib import Path

from storage import cargar_grabaciones
from generalizar import generalizar, ErrorGeneralizacion

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

    for nombre_accion, lista_grabaciones in grabaciones.items():
        if len(lista_grabaciones) < 2:
            print(f"'{nombre_accion}': solo {len(lista_grabaciones)} grabación(es), "
                  f"necesitas al menos 2 con valores distintos. Se omite por ahora.")
            continue
        try:
            plantilla = generalizar(lista_grabaciones)
        except ErrorGeneralizacion as e:
            print(f"'{nombre_accion}': no se pudo generalizar -> {e}")
            continue

        plantillas[nombre_accion] = plantilla
        print(f"'{nombre_accion}': plantilla generada con {len(lista_grabaciones)} grabaciones.")

    guardar_plantillas(plantillas)
    print(f"\nGuardado en {RUTA_PLANTILLAS}")


if __name__ == "__main__":
    construir_plantillas()