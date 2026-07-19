"""
window_manager.py

Módulo de consulta del estado del sistema en tiempo real.
Centraliza toda la información que se puede obtener de Windows sobre
ventanas activas, todas las ventanas abiertas, y monitores.

Requiere: python -m pip install pygetwindow screeninfo psutil
"""

from __future__ import annotations

import time

try:
    import pygetwindow as gw
    PYGETWINDOW_DISPONIBLE = True
except ImportError:
    PYGETWINDOW_DISPONIBLE = False

try:
    from screeninfo import get_monitors
    SCREENINFO_DISPONIBLE = True
except ImportError:
    SCREENINFO_DISPONIBLE = False

try:
    import psutil
    PSUTIL_DISPONIBLE = True
except ImportError:
    PSUTIL_DISPONIBLE = False

_cache_procesos: dict[int, str] = {}


def obtener_monitores() -> list[dict]:
    if not SCREENINFO_DISPONIBLE:
        return [{"error": "screeninfo no instalado. Ejecuta: pip install screeninfo"}]
    monitores = []
    for i, m in enumerate(get_monitors()):
        monitores.append({
            "indice": i,
            "nombre": m.name or f"DISPLAY{i + 1}",
            "x": m.x,
            "y": m.y,
            "width": m.width,
            "height": m.height,
            "principal": m.is_primary,
        })
    return monitores


def _detectar_monitor(x: int, y: int, monitores: list[dict]) -> int:
    for m in monitores:
        if (m.get("x", 0) <= x < m.get("x", 0) + m.get("width", 1920) and
                m.get("y", 0) <= y < m.get("y", 0) + m.get("height", 1080)):
            return m["indice"]
    return 0


def _obtener_proceso_por_pid(pid: int) -> str | None:
    if not PSUTIL_DISPONIBLE or pid <= 0:
        return None
    if pid in _cache_procesos:
        return _cache_procesos[pid]
    try:
        nombre = psutil.Process(pid).name()
        _cache_procesos[pid] = nombre
        return nombre
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _obtener_pid_ventana(hwnd: int) -> int:
    try:
        import ctypes
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    except Exception:
        return 0


def listar_ventanas_abiertas(monitores: list[dict] | None = None) -> list[dict]:
    """
    Devuelve todas las ventanas visibles abiertas en el sistema,
    tanto en primer como en segundo plano, en todos los monitores.
    """
    if not PYGETWINDOW_DISPONIBLE:
        return [{"error": "pygetwindow no instalado. Ejecuta: pip install pygetwindow"}]

    if monitores is None:
        monitores = obtener_monitores()

    ventanas = []
    for w in gw.getAllWindows():
        titulo = (w.title or "").strip()
        if not titulo:
            continue
        if w.width <= 0 or w.height <= 0:
            continue

        centro_x = w.left + w.width // 2
        centro_y = w.top + w.height // 2
        monitor_idx = _detectar_monitor(centro_x, centro_y, monitores)

        pid = _obtener_pid_ventana(w._hWnd) if hasattr(w, "_hWnd") else 0
        proceso = _obtener_proceso_por_pid(pid)

        ventanas.append({
            "titulo": titulo,
            "proceso": proceso,
            "pid": pid if pid else None,
            "monitor": monitor_idx,
            "maximizada": w.isMaximized,
            "minimizada": w.isMinimized,
            "rect": {"left": w.left, "top": w.top, "right": w.right, "bottom": w.bottom},
            "width": w.width,
            "height": w.height,
        })

    ventanas.sort(key=lambda v: (v["monitor"], v["titulo"].lower()))
    return ventanas


def buscar_ventana(termino: str, monitores: list[dict] | None = None) -> list[dict]:
    """
    Busca entre todas las ventanas abiertas las que coincidan con el
    término (insensible a mayúsculas, busca en título y proceso).
    Útil para precondiciones STRIPS: saber si Steam está abierto
    antes de intentar abrirlo.
    """
    termino = termino.lower()
    ventanas = listar_ventanas_abiertas(monitores)
    return [
        v for v in ventanas
        if termino in v["titulo"].lower()
        or (v["proceso"] and termino in v["proceso"].lower())
    ]


def ventana_abierta(titulo_parcial: str) -> bool:
    """
    Versión booleana de buscar_ventana(). Para usar en precondiciones STRIPS.
    Ejemplo: ventana_abierta("steam") → True / False
    """
    return len(buscar_ventana(titulo_parcial)) > 0


def obtener_ventana_activa(monitores: list[dict] | None = None) -> dict:
    """Devuelve información sobre la ventana que tiene el foco ahora mismo."""
    if not PYGETWINDOW_DISPONIBLE:
        return {"error": "pygetwindow no instalado"}

    ventana = gw.getActiveWindow()
    if ventana is None:
        return {"error": "No se pudo obtener la ventana activa"}

    if monitores is None:
        monitores = obtener_monitores()

    centro_x = ventana.left + ventana.width // 2
    centro_y = ventana.top + ventana.height // 2
    monitor_idx = _detectar_monitor(centro_x, centro_y, monitores)

    pid = _obtener_pid_ventana(ventana._hWnd) if hasattr(ventana, "_hWnd") else 0
    proceso = _obtener_proceso_por_pid(pid)

    return {
        "titulo": ventana.title,
        "proceso": proceso,
        "pid": pid if pid else None,
        "monitor": monitor_idx,
        "maximizada": ventana.isMaximized,
        "minimizada": ventana.isMinimized,
        "rect": {
            "left": ventana.left, "top": ventana.top,
            "right": ventana.right, "bottom": ventana.bottom
        },
        "width": ventana.width,
        "height": ventana.height,
        "timestamp": time.time(),
    }


def obtener_contexto_click(x: int, y: int, monitores: list[dict] | None = None) -> dict:
    """
    Captura el contexto completo en el momento de un clic:
    ventana activa + coordenadas absolutas y relativas + monitor.
    """
    if monitores is None:
        monitores = obtener_monitores()

    ventana = obtener_ventana_activa(monitores)
    monitor_click = _detectar_monitor(x, y, monitores)

    x_rel = y_rel = None
    if "rect" in ventana:
        x_rel = x - ventana["rect"]["left"]
        y_rel = y - ventana["rect"]["top"]

    return {
        "ventana": ventana,
        "click": {
            "x_abs": x,
            "y_abs": y,
            "x_rel": x_rel,
            "y_rel": y_rel,
            "monitor": monitor_click,
        },
    }


if __name__ == "__main__":
    monitores = obtener_monitores()

    print("=== Monitores ===")
    for m in monitores:
        principal = " (principal)" if m.get("principal") else ""
        print(f"  Monitor {m['indice']}{principal}: "
              f"{m['width']}x{m['height']} en ({m['x']}, {m['y']})")

    print("\n=== Ventana activa ===")
    ventana = obtener_ventana_activa(monitores)
    for k, v in ventana.items():
        if k != "timestamp":
            print(f"  {k}: {v}")

    print("\n=== Todas las ventanas abiertas ===")
    ventanas = listar_ventanas_abiertas(monitores)
    for v in ventanas:
        proceso = v["proceso"] or "desconocido"
        estado = "MAX" if v["maximizada"] else ("min" if v["minimizada"] else "normal")
        print(f"  [Monitor {v['monitor']}] {v['titulo']!r} ({proceso}) "
              f"{v['width']}x{v['height']} [{estado}]")