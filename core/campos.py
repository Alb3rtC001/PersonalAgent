"""
Memoria de "en esta app, aquí se escribe" (data/campos.json).

Cuando dices el campo ("escribe hola en el buscador de Steam") o contestas en
cuál cuando hay varios, se guarda el control elegido para esa app (su nombre,
AutomationId y tipo, no la posición). La próxima vez, si el cursor no está en
ningún campo y hay varios, `escribir_texto` usa ese sin preguntar.

Una entrada por app: la clave es el programa (steamwebhelper, discord...) o,
en las apps de la Microsoft Store, que comparten programa, el título.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from config import RUTA_DATOS
from core.estado import normalizar

RUTA_CAMPOS = RUTA_DATOS / "campos.json"
PROCESOS_COMPARTIDOS = {"applicationframehost"}
_lock = threading.Lock()


def clave_app(ventana: dict) -> str:
    proceso = normalizar(Path(ventana.get("proceso") or "").stem)
    if not proceso or proceso in PROCESOS_COMPARTIDOS:
        return normalizar(ventana.get("titulo") or "")
    return proceso


def _leer(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def recordado(ventana: dict, ruta: Path | None = None) -> dict | None:
    """{"nombre", "id", "tipo"} del campo recordado para la app de esta ventana, o None."""
    with _lock:
        return _leer(Path(ruta or RUTA_CAMPOS)).get(clave_app(ventana))


def recordar(ventana: dict, nombre: str, id_: str = "", tipo: str = "", ruta: Path | None = None) -> None:
    clave = clave_app(ventana)
    if not clave or not (nombre or id_):
        return
    ruta = Path(ruta or RUTA_CAMPOS)
    with _lock:
        datos = _leer(ruta)
        nuevo = {"nombre": nombre, "id": id_, "tipo": tipo}
        if datos.get(clave) == nuevo:
            return
        datos[clave] = nuevo
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def olvidar(ventana: dict, ruta: Path | None = None) -> None:
    ruta = Path(ruta or RUTA_CAMPOS)
    with _lock:
        datos = _leer(ruta)
        if datos.pop(clave_app(ventana), None) is not None:
            ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def buscar(candidatos: list, guardado: dict | None, describir) -> object | None:
    """
    Entre los campos de la ventana, el recordado: primero por AutomationId (no
    cambia aunque cambie el texto), si no por nombre; siempre del mismo tipo.
    `describir(control)` -> (nombre, id, tipo).
    """
    if not guardado:
        return None
    datos = [(c, *describir(c)) for c in candidatos]
    if guardado.get("id"):
        por_id = [c for c, _, id_, tipo in datos if id_ == guardado["id"] and tipo == guardado.get("tipo", tipo)]
        if len(por_id) == 1:
            return por_id[0]
    por_nombre = [c for c, nombre, _, tipo in datos
                  if normalizar(nombre) == normalizar(guardado.get("nombre", "")) and tipo == guardado.get("tipo", tipo)]
    return por_nombre[0] if len(por_nombre) == 1 else None
