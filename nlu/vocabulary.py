"""
Vocabulario y vectorización para el clasificador de intención.

Flujo:
    frase (texto) -> tokenizar() -> lista de tokens
    lista de tokens + vocabulario -> vectorizar_bow() -> vector numpy

El vocabulario y el mapa de intenciones se guardan en JSON para poder
reutilizarlos exactamente igual en el momento de inferencia (main.py),
sin tener que reconstruirlos desde el dataset cada vez.
"""

import json
import re
from pathlib import Path

import numpy as np

# Ruta absoluta basada en la ubicación de este archivo, no en el
# directorio desde el que se ejecute el script (mismo criterio que
# en model.py, para evitar el mismo bug: guardar en un sitio y
# cargar desde otro según desde dónde se ejecute cada script).
RUTA_VOCABULARIO = Path(__file__).parent / "vocabulary.json"


def tokenizar(frase: str) -> list[str]:
    """
    Tokenizador simple:
    - todo a minúsculas
    - quita signos de puntuación (deja letras, números y espacios)
    - separa por espacios
    """
    frase = frase.lower()
    frase = re.sub(r"[^a-z0-9áéíóúñü\s]", "", frase)
    tokens = frase.split()
    return tokens


def construir_vocabulario(dataset: list[tuple[str, str]]) -> tuple[dict, dict]:
    """
    A partir del dataset (frase, intención) construye:
    - vocab: dict palabra -> índice
    - intenciones: dict intención -> índice

    El orden de los índices se basa en orden alfabético para que sea
    determinista (no depende del orden en que aparecen en el dataset).
    """
    palabras = set()
    intenciones_set = set()

    for frase, intencion in dataset:
        tokens = tokenizar(frase)
        palabras.update(tokens)
        intenciones_set.add(intencion)

    vocab = {palabra: idx for idx, palabra in enumerate(sorted(palabras))}
    intenciones = {intencion: idx for idx, intencion in enumerate(sorted(intenciones_set))}

    return vocab, intenciones


def vectorizar_bow(tokens: list[str], vocab: dict) -> np.ndarray:
    """
    Convierte una lista de tokens en un vector bag-of-words (conteo de
    apariciones). Palabras no vistas en el vocabulario se ignoran
    (importante: esto pasará a menudo con nombres de apps nuevos, no
    es un error, es esperado en esta fase).
    """
    vector = np.zeros(len(vocab), dtype=np.float32)
    for token in tokens:
        if token in vocab:
            vector[vocab[token]] += 1.0
    return vector


def guardar_vocabulario(vocab: dict, intenciones: dict, ruta: str = RUTA_VOCABULARIO) -> None:
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"vocab": vocab, "intenciones": intenciones}, f, ensure_ascii=False, indent=2)


def cargar_vocabulario(ruta: str = RUTA_VOCABULARIO) -> tuple[dict, dict]:
    with open(ruta, "r", encoding="utf-8") as f:
        datos = json.load(f)
    return datos["vocab"], datos["intenciones"]


if __name__ == "__main__":
    from dataset import DATASET

    vocab, intenciones = construir_vocabulario(DATASET)
    guardar_vocabulario(vocab, intenciones)

    print(f"Tamaño del vocabulario: {len(vocab)} palabras únicas")
    print(f"Intenciones: {intenciones}")

    # Prueba rápida con una frase nueva, con una app que NO está en el dataset
    frase_prueba = "abre Blender por favor"
    tokens = tokenizar(frase_prueba)
    vector = vectorizar_bow(tokens, vocab)

    print(f"\nFrase de prueba: '{frase_prueba}'")
    print(f"Tokens: {tokens}")
    print(f"Palabras del vocabulario detectadas: {vector.sum():.0f} de {len(tokens)} tokens")
    print(f"Dimensión del vector: {vector.shape}")