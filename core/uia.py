"""
UI Automation (accesibilidad de Windows) para la grabadora semántica: saber
QUÉ control hay en un punto o tiene el foco, guardarlo por su identidad
(identificador, nombre, tipo) y volver a encontrarlo después aunque la
ventana se haya movido o cambiado de tamaño.

Funciona solo con el procesador (sin GPU). Librería: uiautomation (Apache
2.0). Cada hilo que la use debe estar dentro de `en_hilo()` (COM).
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

try:
    import uiautomation as auto
    auto.SetGlobalSearchTimeout(2)
    UIA_DISPONIBLE = True
except ImportError:   # sin la librería, la grabadora semántica no está disponible
    auto = None
    UIA_DISPONIBLE = False

log = logging.getLogger("personalagent")

PROFUNDIDAD_BUSQUEDA = 30


@contextlib.contextmanager
def en_hilo():
    """Inicializa COM en el hilo actual (obligatorio para usar UI Automation fuera del principal)."""
    if not UIA_DISPONIBLE:
        yield
        return
    with auto.UIAutomationInitializerInThread():
        yield


def describir_control(control) -> dict[str, Any]:
    """Identidad de un control: lo que se guarda en la grabación."""
    r = control.BoundingRectangle
    try:
        es_contrasena = bool(control.IsPassword)
    except Exception:
        es_contrasena = False
    return {
        "nombre": control.Name or "",
        "tipo": control.ControlTypeName or "",
        "id": control.AutomationId or "",
        "clase": control.ClassName or "",
        "contrasena": es_contrasena,
        "rect": [r.left, r.top, r.right, r.bottom],
    }


def describir_ventana(control) -> dict[str, Any]:
    """La ventana principal (de nivel superior) a la que pertenece un control."""
    from core.estado import _info_ventana, obtener_monitores  # noqa: PLC0415 (evitar import circular)
    superior = control.GetTopLevelControl() or control
    hwnd = superior.NativeWindowHandle
    if not hwnd:
        return {"titulo": superior.Name or "", "proceso": None, "hwnd": 0, "pid": superior.ProcessId}
    info = _info_ventana(hwnd, obtener_monitores())
    return {"titulo": info["titulo"], "proceso": info["proceso"], "hwnd": hwnd, "pid": info["pid"],
            "rect": [info["rect"]["left"], info["rect"]["top"], info["rect"]["right"], info["rect"]["bottom"]]}


def control_en(x: int, y: int) -> tuple[dict, dict] | None:
    """(control, ventana) en un punto de la pantalla, o None."""
    if not UIA_DISPONIBLE:
        return None
    control = auto.ControlFromPoint(x, y)
    if control is None:
        return None
    return describir_control(control), describir_ventana(control)


def control_con_foco() -> tuple[dict, dict] | None:
    """(control, ventana) que tiene ahora el foco del teclado, o None."""
    if not UIA_DISPONIBLE:
        return None
    control = auto.GetFocusedControl()
    if control is None:
        return None
    return describir_control(control), describir_ventana(control)


def buscar_control(hwnd: int, descripcion: dict, espera: float = 3.0):
    """
    Busca dentro de la ventana el control descrito: primero por su
    identificador (AutomationId), si no por nombre; siempre del mismo tipo.
    Devuelve el control de uiautomation o None.
    """
    if not UIA_DISPONIBLE or not hwnd:
        return None
    ventana = auto.ControlFromHandle(hwnd)
    if ventana is None:
        return None
    tipo = getattr(auto.ControlType, descripcion.get("tipo") or "", None)
    criterios = []
    if descripcion.get("id"):
        criterios.append({"AutomationId": descripcion["id"]})
    if descripcion.get("nombre"):
        criterios.append({"Name": descripcion["nombre"]})
    for criterio in criterios:
        if tipo is not None:
            criterio["ControlType"] = tipo
        control = ventana.Control(searchDepth=PROFUNDIDAD_BUSQUEDA, **criterio)
        if control.Exists(maxSearchSeconds=espera, searchIntervalSeconds=0.2):
            return control
        espera = min(espera, 1.0)   # el segundo criterio, con menos paciencia
    return None


def centro(control) -> tuple[int, int]:
    r = control.BoundingRectangle
    return (r.left + r.right) // 2, (r.top + r.bottom) // 2


def leer_valor(control) -> str | None:
    """Texto de un campo (para comprobar lo escrito), si el control lo permite."""
    try:
        patron = control.GetValuePattern()
        return patron.Value if patron else None
    except Exception:
        return None
