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


def _patron_valor(control):
    try:
        return control.GetPattern(auto.PatternId.ValuePattern)
    except Exception:
        return None


def leer_valor(control) -> str | None:
    """Texto de un campo (para comprobar lo escrito), si el control lo permite."""
    patron = _patron_valor(control)
    try:
        return patron.Value if patron else None
    except Exception:
        return None


TIPOS_EDITABLES = {"EditControl", "DocumentControl", "ComboBoxControl"}


def es_editable(control) -> bool:
    """¿Se puede escribir en este control? (cuadro de texto, documento editable...)."""
    if control is None or control.ControlTypeName not in TIPOS_EDITABLES:
        return False
    patron = _patron_valor(control)
    if patron is not None:
        try:
            return not patron.IsReadOnly
        except Exception:
            return True
    # Sin patrón de valor: un Edit sí suele aceptar texto; un Document (una página web) no.
    return control.ControlTypeName == "EditControl"


def foco_actual():
    """El control (objeto de uiautomation) que tiene el foco, o None."""
    return auto.GetFocusedControl() if UIA_DISPONIBLE else None


def recorrer(hwnd: int, max_nodos: int = 2500, tiempo_max: float = 2.0, profundidad: int = 25):
    """Controles de una ventana, con tope de nodos y de tiempo (algunas apps tienen miles)."""
    if not UIA_DISPONIBLE or not hwnd:
        return
    import time
    ventana = auto.ControlFromHandle(hwnd)
    if ventana is None:
        return
    limite = time.monotonic() + tiempo_max
    for n, (control, _) in enumerate(auto.WalkControl(ventana, includeTop=False, maxDepth=profundidad)):
        if n >= max_nodos or time.monotonic() > limite:
            break
        yield control


def campos_editables(hwnd: int) -> list:
    """Cuadros de texto de una ventana en los que se puede escribir (visibles)."""
    campos = []
    # Las apps web (Steam, Discord) tienen árboles hondos: mismo alcance que al leer la pantalla.
    for control in recorrer(hwnd, max_nodos=6000, tiempo_max=3.0, profundidad=40):
        try:
            if control.ControlTypeName in TIPOS_EDITABLES and not control.IsOffscreen and es_editable(control):
                campos.append(control)
        except Exception:
            continue
    return campos


def nombre_de_campo(control) -> str:
    return (control.Name or control.AutomationId or control.ControlTypeName.replace("Control", "")).strip()


# Controles que se pueden pulsar por su nombre (hacer_clic). Incluye los textos:
# en las apps web (Steam, Discord...) una pestaña suele ser un texto clicable.
TIPOS_PULSABLES = {"ButtonControl", "HyperlinkControl", "TabItemControl", "MenuItemControl",
                   "ListItemControl", "TreeItemControl", "TextControl", "CheckBoxControl",
                   "RadioButtonControl", "SplitButtonControl", "DataItemControl"}


def controles_pulsables(hwnd: int, tiempo_max: float = 3.0) -> list:
    """Controles visibles de la ventana, con nombre, que se pueden pulsar."""
    encontrados = []
    for control in recorrer(hwnd, max_nodos=6000, tiempo_max=tiempo_max, profundidad=40):
        try:
            if control.IsOffscreen or control.ControlTypeName not in TIPOS_PULSABLES:
                continue
            nombre = (control.Name or "").strip()
            r = control.BoundingRectangle
            if nombre and len(nombre) <= 80 and r.right > r.left and r.bottom > r.top:
                encontrados.append(control)
        except Exception:
            continue
    return encontrados


def se_ve_en_su_centro(control, niveles: int = 4) -> bool:
    """
    ¿Lo que hay en el centro del control es el propio control (o algo suyo)?
    Descarta los que la app tiene "escondidos" sin decirlo: en Steam, la
    cabecera fija con otro botón JUGAR que solo aparece al bajar la página.
    """
    if not UIA_DISPONIBLE:
        return True
    try:
        x, y = centro(control)
        encima = auto.ControlFromPoint(x, y)
        if encima is None:
            return False
        # El punto puede caer en un hijo (el texto dentro del botón) o en el padre.
        for a, b in ((encima, control), (control, encima)):
            actual = a
            for _ in range(niveles + 1):
                if actual is None:
                    break
                if auto.ControlsAreSame(actual, b):
                    return True
                actual = actual.GetParentControl()
        # Los diálogos de algunas apps (el "¿Salir del juego?" de Steam) son otra
        # ventana y UI Automation da otro objeto para el mismo botón: vale si en
        # ese punto hay algo con el mismo nombre y exactamente el mismo sitio.
        return _mismo_control(encima, control, niveles)
    except Exception:
        return False


def _mismo_control(encima, control, niveles: int) -> bool:
    def rect(c):
        r = c.BoundingRectangle
        return r.left, r.top, r.right, r.bottom
    nombre, sitio = (control.Name or "").strip(), rect(control)
    if not nombre:
        return False
    actual = encima
    for _ in range(niveles + 1):
        if actual is None:
            return False
        if (actual.Name or "").strip() == nombre and rect(actual) == sitio:
            return True
        actual = actual.GetParentControl()
    return False


def huella(hwnd: int) -> str:
    """Resumen de lo que se ve en la ventana, para saber si un clic ha cambiado algo."""
    return texto_de_ventana(hwnd, max_caracteres=20000, tiempo_max=3.0)


def ventana_de_punto(x: int, y: int) -> int | None:
    """hwnd de la ventana de nivel superior que hay bajo un punto (para no hacer clic sobre otra)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
        hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
        return user32.GetAncestor(hwnd, 2) or None if hwnd else None    # GA_ROOT
    except Exception:
        return None


# Tipos de control cuyo nombre es texto que se ve en pantalla.
TIPOS_CON_TEXTO = {"TextControl", "HyperlinkControl", "ListItemControl", "TreeItemControl", "HeaderControl",
                   "HeaderItemControl", "DataItemControl", "ButtonControl", "TabItemControl", "MenuItemControl",
                   "TitleBarControl", "GroupControl", "StatusBarControl", "ToolTipControl"}


def texto_de_ventana(hwnd: int, max_caracteres: int = 7000, tiempo_max: float = 3.0) -> str:
    """
    El texto visible de una ventana, en orden, para que el LLM conteste
    preguntas sobre ella. Sin duplicados seguidos y con tope de tamaño.
    """
    lineas: list[str] = []
    total = 0
    for control in recorrer(hwnd, max_nodos=6000, tiempo_max=tiempo_max, profundidad=40):
        try:
            if control.IsOffscreen:
                continue
            tipo = control.ControlTypeName
            texto = ""
            if tipo in TIPOS_CON_TEXTO:
                texto = control.Name or ""
            elif tipo in TIPOS_EDITABLES:
                valor = leer_valor(control)
                texto = f"[campo {control.Name or ''}: {valor}]" if valor else ""
        except Exception:
            continue
        # Fuera los iconos (caracteres de uso privado, p. ej. "") y espacios de más.
        texto = " ".join("".join(c for c in texto if not 0xE000 <= ord(c) <= 0xF8FF).split())
        if not texto or (lineas and lineas[-1] == texto):
            continue
        lineas.append(texto)
        total += len(texto) + 1
        if total >= max_caracteres:
            lineas.append("[… texto recortado]")
            break
    return "\n".join(lineas)
