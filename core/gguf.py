"""
Lectura mínima de la cabecera de un archivo GGUF (el formato de los modelos
de llama.cpp), sin dependencias: solo para saber cuántas capas tiene el
modelo y así calcular cuántas caben en el límite de VRAM.

Formato: "GGUF", versión (u32), nº de tensores (u64), nº de claves (u64) y
después las claves: nombre (u64 + bytes) + tipo (u32) + valor.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO

# tipo -> formato de struct (los de tamaño fijo)
_FIJOS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?",
          10: "<Q", 11: "<q", 12: "<d"}
_STRING, _ARRAY = 8, 9


def _leer(f: BinaryIO, formato: str):
    tam = struct.calcsize(formato)
    datos = f.read(tam)
    if len(datos) != tam:
        raise ValueError("GGUF truncado")
    return struct.unpack(formato, datos)[0]


def _leer_string(f: BinaryIO) -> str:
    largo = _leer(f, "<Q")
    return f.read(largo).decode("utf-8", errors="replace")


def _leer_valor(f: BinaryIO, tipo: int, guardar: bool = True):
    if tipo in _FIJOS:
        return _leer(f, _FIJOS[tipo])
    if tipo == _STRING:
        return _leer_string(f)
    if tipo == _ARRAY:
        tipo_items, n = _leer(f, "<I"), _leer(f, "<Q")
        if tipo_items in _FIJOS:   # arrays numéricos: se saltan de golpe
            f.seek(struct.calcsize(_FIJOS[tipo_items]) * n, 1)
        else:
            for _ in range(n):
                _leer_valor(f, tipo_items, guardar=False)
        return None
    raise ValueError(f"tipo GGUF desconocido: {tipo}")


def numero_de_capas(ruta: Path) -> int | None:
    """Capas (bloques) del modelo según su cabecera, o None si no se puede leer."""
    try:
        with open(ruta, "rb") as f:
            if f.read(4) != b"GGUF":
                return None
            _leer(f, "<I")          # versión
            _leer(f, "<Q")          # nº de tensores
            n_claves = _leer(f, "<Q")
            for _ in range(n_claves):
                clave = _leer_string(f)
                valor = _leer_valor(f, _leer(f, "<I"))
                if clave.endswith(".block_count"):
                    return int(valor)
    except (OSError, ValueError, struct.error):
        return None
    return None
