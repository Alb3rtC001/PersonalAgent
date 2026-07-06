"""
Gestión del dataset de entrenamiento para el clasificador de intención.

El dataset ya NO vive hardcodeado en una lista de Python: vive en
dataset.json. Este módulo expone funciones para leerlo y para añadir
frases nuevas sin tocar el archivo a mano.

Uso típico mientras vas ampliando el proyecto:

    from dataset import agregar_frase

    agregar_frase("abre notion", "abrir_aplicacion")
    agregar_frase("apunta que hay que sacar la basura", "crear_nota")

Importante: añadir una frase aquí NO reentrena el modelo automáticamente.
Es un dataset de entrenamiento por lotes (batch): cuando quieras que el
modelo tenga en cuenta las frases nuevas, hay que volver a ejecutar
entrenar.py. Esto es distinto de las "plantillas" grabadas por
demostración, que sí se consultan en caliente sin reentrenar nada.
"""

import json
from pathlib import Path

RUTA_DATASET = Path(__file__).parent / "dataset.json"


def cargar_dataset(ruta: Path = RUTA_DATASET) -> list[tuple[str, str]]:
    """Devuelve el dataset como lista de tuplas (frase, intención)."""
    if not ruta.exists():
        return []
    with open(ruta, "r", encoding="utf-8") as f:
        datos = json.load(f)
    return [(item["frase"], item["intencion"]) for item in datos]


def guardar_dataset(dataset: list[tuple[str, str]], ruta: Path = RUTA_DATASET) -> None:
    datos = [{"frase": frase, "intencion": intencion} for frase, intencion in dataset]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def agregar_frase(frase: str, intencion: str, ruta: Path = RUTA_DATASET) -> bool:
    """
    Añade una frase nueva al dataset y la guarda en disco.
    Evita duplicados exactos (misma frase + misma intención).
    Devuelve True si se añadió, False si ya existía.
    """
    dataset = cargar_dataset(ruta)
    frase = frase.strip().lower()

    if (frase, intencion) in dataset:
        return False

    dataset.append((frase, intencion))
    guardar_dataset(dataset, ruta)
    return True


def listar_intenciones(ruta: Path = RUTA_DATASET) -> set:
    dataset = cargar_dataset(ruta)
    return {intencion for _, intencion in dataset}


def contar_por_intencion(ruta: Path = RUTA_DATASET) -> dict:
    from collections import Counter
    dataset = cargar_dataset(ruta)
    return dict(Counter(intencion for _, intencion in dataset))


# Compatibilidad con el código anterior (vocabulario.py hacía
# "from dataset import DATASET"): se sigue exponiendo esa variable,
# pero ahora se carga desde el JSON en vez de estar hardcodeada aquí.
DATASET = cargar_dataset()


if __name__ == "__main__":
    print(f"Total de frases: {len(DATASET)}")
    print(f"Por intención: {contar_por_intencion()}")
