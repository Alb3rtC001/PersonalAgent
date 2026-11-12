"""Token compartido entre el servidor y sus clientes."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from config import RUTA_TOKEN

VARIABLE_ENTORNO = "PERSONALAGENT_TOKEN"


def obtener_token(ruta: Path = RUTA_TOKEN, crear: bool = True) -> str | None:
    """Token de la variable de entorno, o del archivo (creándolo la primera vez)."""
    if os.environ.get(VARIABLE_ENTORNO):
        return os.environ[VARIABLE_ENTORNO].strip()
    if ruta.exists():
        return ruta.read_text(encoding="utf-8").strip()
    if not crear:
        return None
    token = secrets.token_urlsafe(24)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(token, encoding="utf-8")
    return token
