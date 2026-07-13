"""
add_phrases.py

Tres modos de uso desde la raíz del proyecto:

  1. UNA sola frase:
     python .\\add_phrases.py

     Te pregunta la intención (mostrando las que ya existen) y la frase.

  2. VARIAS frases desde un JSON externo:
     python .\\add_phrases.py .\\mis_frases.json

     El archivo debe tener el mismo formato que dataset.json:
     [{"frase": "...", "intencion": "..."}, ...]

  3. Lista hardcodeada (edita FRASES_NUEVAS abajo):
     Deja el archivo sin argumentos pero rellena FRASES_NUEVAS.
     Útil si quieres tener un histórico de lo que añadiste.

En todos los casos las frases nuevas se insertan justo después de
las que ya existen para esa misma intención, y se detectan duplicados.
Acuérdate de reentrenar después:
    python .\\nlu\\training.py
"""

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "nlu"))

from nlu.dataset import agregar_frase, contar_por_intencion, listar_intenciones  # noqa: E402

# ---------------------------------------------------------------
# MODO 3: edita aquí si quieres añadir varias frases hardcodeadas
# ---------------------------------------------------------------
FRASES_NUEVAS = [
    # ("frase de ejemplo", "nombre_intencion"),
]
# ---------------------------------------------------------------


def _mostrar_resultado(frase: str, intencion: str, añadida: bool) -> None:
    estado = "OK" if añadida else "YA EXISTÍA"
    print(f"  [{estado}] '{frase}' -> {intencion}")


def _resumen(añadidas: int, total: int) -> None:
    print(f"\n{añadidas} frase(s) nueva(s) añadidas de {total} procesadas.")
    print("\nTotales por intención:")
    for intencion, n in contar_por_intencion().items():
        print(f"  {intencion}: {n} frases")
    if añadidas > 0:
        print("\nRecuerda reentrenar el modelo:")
        print("  python .\\nlu\\training.py")


def modo_una_frase() -> None:
    """Modo interactivo: pide intención y frase por consola."""
    intenciones = sorted(listar_intenciones())
    print("Intenciones disponibles:")
    for i, nombre in enumerate(intenciones, 1):
        print(f"  {i}. {nombre}")
    print(f"  {len(intenciones) + 1}. [nueva intención]")

    eleccion = input("\nElige el número de la intención (o escríbela directamente): ").strip()

    if eleccion.isdigit():
        idx = int(eleccion) - 1
        if 0 <= idx < len(intenciones):
            intencion = intenciones[idx]
        else:
            intencion = input("Nombre de la nueva intención: ").strip().lower()
    else:
        intencion = eleccion.lower()

    if not intencion:
        print("Intención vacía, cancelando.")
        return

    frase = input(f"Frase a añadir para '{intencion}': ").strip()
    if not frase:
        print("Frase vacía, cancelando.")
        return

    print()
    añadida = agregar_frase(frase, intencion)
    _mostrar_resultado(frase, intencion, añadida)
    _resumen(1 if añadida else 0, 1)


def modo_json(ruta_json: Path) -> None:
    """Modo importación: lee un JSON externo con el mismo formato que dataset.json."""
    if not ruta_json.exists():
        print(f"Error: no se encontró el archivo '{ruta_json}'")
        sys.exit(1)

    with open(ruta_json, "r", encoding="utf-8") as f:
        datos = json.load(f)

    if not isinstance(datos, list):
        print("Error: el JSON debe ser una lista de objetos {frase, intencion}.")
        sys.exit(1)

    print(f"Importando {len(datos)} frase(s) desde '{ruta_json}'...\n")
    añadidas = 0
    for item in datos:
        frase = item.get("frase", "").strip()
        intencion = item.get("intencion", "").strip()
        if not frase or not intencion:
            print(f"  [IGNORADO] Entrada incompleta: {item}")
            continue
        resultado = agregar_frase(frase, intencion)
        _mostrar_resultado(frase, intencion, resultado)
        if resultado:
            añadidas += 1

    _resumen(añadidas, len(datos))


def modo_lista() -> None:
    """Modo lista hardcodeada: usa FRASES_NUEVAS definida arriba."""
    if not FRASES_NUEVAS:
        print("FRASES_NUEVAS está vacía. Edita add_phrases.py o pasa un JSON como argumento.")
        print("Uso: python .\\add_phrases.py [ruta_a_archivo.json]")
        return

    print(f"Añadiendo {len(FRASES_NUEVAS)} frase(s)...\n")
    añadidas = 0
    for frase, intencion in FRASES_NUEVAS:
        resultado = agregar_frase(frase, intencion)
        _mostrar_resultado(frase, intencion, resultado)
        if resultado:
            añadidas += 1

    _resumen(añadidas, len(FRASES_NUEVAS))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Modo 2: JSON externo pasado como argumento
        modo_json(Path(sys.argv[1]))
    elif FRASES_NUEVAS:
        # Modo 3: lista hardcodeada
        modo_lista()
    else:
        # Modo 1: interactivo (una frase)
        modo_una_frase()