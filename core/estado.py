"""
Estado del mundo (antes window_manager.py).

Dos niveles:
- Funciones de consulta de Windows: ventanas abiertas, ventana activa,
  monitores, contexto de un clic (las usan el grabador y el reproductor).
- Hechos para el planificador: cadenas "predicado:argumento" que se
  pueden comprobar en el sistema real, y EstadoMundo, que permite
  simular efectos sobre el estado real sin tocarlo.

Hechos que se saben consultar:
    abierta:<app>   hay alguna ventana cuyo título o proceso contiene <app>
    visible:<app>   ídem y al menos una de ellas no está minimizada
Cualquier otro hecho se considera False hasta que una skill lo produzca.

Diagnóstico: python -m core.estado

Requiere: python -m pip install pygetwindow screeninfo psutil
"""

from __future__ import annotations

import time
import unicodedata
from typing import Callable

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


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar nombres de apps y ventanas."""
    return "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").lower())
        if unicodedata.category(c) != "Mn"
    ).strip()


# ---------------------------------------------------------------------------
# Monitores
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Ventanas
# ---------------------------------------------------------------------------

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


def _info_ventana(w, monitores: list[dict]) -> dict:
    centro_x = w.left + w.width // 2
    centro_y = w.top + w.height // 2
    hwnd = getattr(w, "_hWnd", 0)
    pid = _obtener_pid_ventana(hwnd) if hwnd else 0
    return {
        "titulo": (w.title or "").strip(),
        "proceso": _obtener_proceso_por_pid(pid),
        "pid": pid or None,
        "hwnd": hwnd or None,
        "monitor": _detectar_monitor(centro_x, centro_y, monitores),
        "maximizada": w.isMaximized,
        "minimizada": w.isMinimized,
        "rect": {"left": w.left, "top": w.top, "right": w.right, "bottom": w.bottom},
        "width": w.width,
        "height": w.height,
    }


def listar_ventanas_abiertas(monitores: list[dict] | None = None) -> list[dict]:
    """Todas las ventanas con título, en primer o segundo plano, en todos los monitores."""
    if not PYGETWINDOW_DISPONIBLE:
        return []
    if monitores is None:
        monitores = obtener_monitores()

    ventanas = []
    for w in gw.getAllWindows():
        if not (w.title or "").strip() or w.width <= 0 or w.height <= 0:
            continue
        ventanas.append(_info_ventana(w, monitores))
    ventanas.sort(key=lambda v: (v["monitor"], v["titulo"].lower()))
    return ventanas


def handles_ventanas() -> set[int]:
    """Identificadores de todas las ventanas con título (para detectar ventanas nuevas)."""
    if not PYGETWINDOW_DISPONIBLE:
        return set()
    return {w._hWnd for w in gw.getAllWindows() if (w.title or "").strip()}


def buscar_ventana(termino: str, monitores: list[dict] | None = None) -> list[dict]:
    """Ventanas cuyo título o proceso contiene el término (sin distinguir mayúsculas ni tildes)."""
    termino = normalizar(termino)
    if not termino:
        return []
    return [
        v for v in listar_ventanas_abiertas(monitores)
        if termino in normalizar(v["titulo"])
        or (v["proceso"] and termino in normalizar(v["proceso"]))
    ]


def ventana_abierta(termino: str) -> bool:
    return len(buscar_ventana(termino)) > 0


def obtener_ventana_gw(hwnd: int):
    """Objeto pygetwindow para una ventana concreta (para restaurarla, activarla...)."""
    if not PYGETWINDOW_DISPONIBLE or not hwnd:
        return None
    return gw.Win32Window(hwnd)


def obtener_ventana_activa(monitores: list[dict] | None = None) -> dict:
    """Información sobre la ventana que tiene el foco ahora mismo."""
    if not PYGETWINDOW_DISPONIBLE:
        return {"error": "pygetwindow no instalado"}
    ventana = gw.getActiveWindow()
    if ventana is None:
        return {"error": "No se pudo obtener la ventana activa"}
    if monitores is None:
        monitores = obtener_monitores()
    info = _info_ventana(ventana, monitores)
    info["timestamp"] = time.time()
    return info


def obtener_contexto_click(x: int, y: int, monitores: list[dict] | None = None) -> dict:
    """Contexto completo de un clic: ventana activa + coordenadas absolutas y relativas + monitor."""
    if monitores is None:
        monitores = obtener_monitores()

    ventana = obtener_ventana_activa(monitores)
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
            "monitor": _detectar_monitor(x, y, monitores),
        },
    }


# ---------------------------------------------------------------------------
# Hechos para el planificador
# ---------------------------------------------------------------------------

def consultar_hecho(hecho: str) -> bool:
    """Comprueba un hecho "predicado:argumento" en el sistema real."""
    predicado, _, argumento = hecho.partition(":")
    if predicado == "abierta":
        return bool(buscar_ventana(argumento))
    if predicado == "visible":
        return any(not v["minimizada"] for v in buscar_ventana(argumento))
    return False


class EstadoMundo:
    """
    Vista del estado del mundo para planificar.

    Los hechos se consultan al sistema real la primera vez que se piden
    (y se guardan en caché). Los efectos simulados se apuntan aparte,
    encima del estado real, sin ejecutar nada. copia() permite probar
    planes alternativos compartiendo la caché de consultas reales.
    """

    def __init__(self, consulta: Callable[[str], bool] = consultar_hecho):
        self._consulta = consulta
        self._cache: dict[str, bool] = {}
        self._simulado: dict[str, bool] = {}

    def get(self, hecho: str) -> bool:
        hecho = normalizar(hecho)
        if hecho in self._simulado:
            return self._simulado[hecho]
        if hecho not in self._cache:
            self._cache[hecho] = self._consulta(hecho)
        return self._cache[hecho]

    def aplicar(self, efectos: dict[str, bool]) -> None:
        for hecho, valor in efectos.items():
            self._simulado[normalizar(hecho)] = valor

    def copia(self) -> "EstadoMundo":
        nuevo = EstadoMundo(self._consulta)
        nuevo._cache = self._cache          # compartida: son consultas reales
        nuevo._simulado = dict(self._simulado)
        return nuevo

    def adoptar(self, otro: "EstadoMundo") -> None:
        self._simulado = dict(otro._simulado)

    def refrescar(self) -> None:
        """Olvida lo consultado y lo simulado (tras ejecutar acciones reales)."""
        self._cache = {}
        self._simulado = {}


if __name__ == "__main__":
    monitores = obtener_monitores()

    print("=== Monitores ===")
    for m in monitores:
        principal = " (principal)" if m.get("principal") else ""
        print(f"  Monitor {m['indice']}{principal}: "
              f"{m['width']}x{m['height']} en ({m['x']}, {m['y']})")

    print("\n=== Ventana activa ===")
    for k, v in obtener_ventana_activa(monitores).items():
        if k != "timestamp":
            print(f"  {k}: {v}")

    print("\n=== Todas las ventanas abiertas ===")
    for v in listar_ventanas_abiertas(monitores):
        proceso = v["proceso"] or "desconocido"
        estado = "MAX" if v["maximizada"] else ("min" if v["minimizada"] else "normal")
        print(f"  [Monitor {v['monitor']}] {v['titulo']!r} ({proceso}) "
              f"{v['width']}x{v['height']} [{estado}]")
