"""
storage.py

Persistencia de las grabaciones crudas (recordings.json).

Soporta dos formatos de entrada, ambos válidos:

Formato antiguo (retrocompatible):
    "abrir_aplicacion": [ [grabacion1], [grabacion2] ]

Formato nuevo (con tolerancia personalizada):
    "abrir_aplicacion_via_click": {
        "tolerancia_px": 60,
        "grabaciones": [ [grabacion1], [grabacion2] ]
    }

Internamente siempre trabaja con el formato nuevo normalizado.
Al guardar, mantiene el formato original de cada entrada para no
romper lo que ya existía.
"""

import json
from pathlib import Path

RUTA_GRABACIONES = Path(__file__).parent / "recordings.json"
TOLERANCIA_DEFAULT = 80  # px — subido de 15 para clics en barra de tareas


def _normalizar_entrada(valor) -> dict:
    """
    Convierte cualquier formato de entrada al formato interno:
    {"tolerancia_px": N, "grabaciones": [...]}
    """
    if isinstance(valor, list):
        return {"tolerancia_px": TOLERANCIA_DEFAULT, "grabaciones": valor}
    if isinstance(valor, dict) and "grabaciones" in valor:
        return {
            "tolerancia_px": valor.get("tolerancia_px", TOLERANCIA_DEFAULT),
            "grabaciones": valor["grabaciones"],
        }
    return {"tolerancia_px": TOLERANCIA_DEFAULT, "grabaciones": []}


def cargar_grabaciones() -> dict[str, dict]:
    """
    Devuelve todas las grabaciones normalizadas al formato interno:
    {
        "nombre_accion": {
            "tolerancia_px": 50,
            "grabaciones": [ [eventos...], [eventos...] ]
        }
    }
    """
    if not RUTA_GRABACIONES.exists():
        return {}
    with open(RUTA_GRABACIONES, "r", encoding="utf-8") as f:
        datos = json.load(f)
    return {nombre: _normalizar_entrada(valor) for nombre, valor in datos.items()}


def guardar_grabacion(nombre_accion: str, eventos: list[dict],
                      tolerancia_px: int | None = None) -> int:
    """
    Añade una grabación nueva a la acción indicada.
    Si la acción ya existe con formato antiguo, lo mantiene.
    Si es nueva o ya tiene formato nuevo, usa el formato nuevo.
    Devuelve el total de grabaciones acumuladas para esa acción.
    """
    if not RUTA_GRABACIONES.exists():
        datos_raw = {}
    else:
        with open(RUTA_GRABACIONES, "r", encoding="utf-8") as f:
            datos_raw = json.load(f)

    entrada_actual = datos_raw.get(nombre_accion)

    if entrada_actual is None:
        # Acción nueva
        if tolerancia_px is not None and tolerancia_px != TOLERANCIA_DEFAULT:
            datos_raw[nombre_accion] = {
                "tolerancia_px": tolerancia_px,
                "grabaciones": [eventos],
            }
        else:
            # Sin tolerancia personalizada: formato antiguo (más limpio de leer)
            datos_raw[nombre_accion] = [eventos]
        total = 1

    elif isinstance(entrada_actual, list):
        # Formato antiguo: añadir a la lista directamente
        if tolerancia_px is not None and tolerancia_px != TOLERANCIA_DEFAULT:
            # Migrar al formato nuevo si se especifica tolerancia personalizada
            datos_raw[nombre_accion] = {
                "tolerancia_px": tolerancia_px,
                "grabaciones": entrada_actual + [eventos],
            }
        else:
            datos_raw[nombre_accion] = entrada_actual + [eventos]
        total = len(datos_raw[nombre_accion]) if isinstance(
            datos_raw[nombre_accion], list) else len(
            datos_raw[nombre_accion]["grabaciones"])

    else:
        # Formato nuevo: añadir a grabaciones
        if tolerancia_px is not None:
            datos_raw[nombre_accion]["tolerancia_px"] = tolerancia_px
        datos_raw[nombre_accion]["grabaciones"].append(eventos)
        total = len(datos_raw[nombre_accion]["grabaciones"])

    with open(RUTA_GRABACIONES, "w", encoding="utf-8") as f:
        json.dump(datos_raw, f, ensure_ascii=False, indent=2)
    return total


def establecer_tolerancia(nombre_accion: str, tolerancia_px: int) -> bool:
    """
    Cambia la tolerancia de una acción ya existente sin tocar las grabaciones.
    Útil para ajustar la tolerancia después de grabar sin volver a grabar.
    Devuelve True si la acción existía, False si no.
    """
    if not RUTA_GRABACIONES.exists():
        return False
    with open(RUTA_GRABACIONES, "r", encoding="utf-8") as f:
        datos_raw = json.load(f)

    if nombre_accion not in datos_raw:
        return False

    entrada = datos_raw[nombre_accion]
    if isinstance(entrada, list):
        # Migrar al formato nuevo
        datos_raw[nombre_accion] = {
            "tolerancia_px": tolerancia_px,
            "grabaciones": entrada,
        }
    else:
        datos_raw[nombre_accion]["tolerancia_px"] = tolerancia_px

    with open(RUTA_GRABACIONES, "w", encoding="utf-8") as f:
        json.dump(datos_raw, f, ensure_ascii=False, indent=2)
    return True