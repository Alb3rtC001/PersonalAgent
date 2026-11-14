"""
Estado del mundo (antes window_manager.py).

Dos niveles:
- Funciones de consulta de Windows: ventanas abiertas, ventana activa,
  monitores, contexto de un clic (las usan el grabador y el reproductor),
  y traer_al_frente() para mostrar una ventana.
- Hechos para el planificador: cadenas "predicado:argumento" que se
  pueden comprobar en el sistema real, y EstadoMundo, que permite
  simular efectos sobre el estado real sin tocarlo.

Hechos que se saben consultar:
    abierta:<app>   hay alguna ventana (aunque esté oculta en la bandeja del
                    sistema) cuyo título o proceso contiene <app>
    visible:<app>   ídem y al menos una se ve: ni minimizada ni oculta
Cualquier otro hecho se considera False hasta que una skill lo produzca.

Las ventanas se enumeran directamente con la API de Windows (ctypes):
así se ven también las ventanas ocultas de apps que "se cierran" a la
bandeja del sistema (Discord, Steam, Spotify...), que pygetwindow no veía.

Diagnóstico: python -m core.estado

Requiere: python -m pip install screeninfo psutil
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
import unicodedata
from typing import Callable

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

try:
    _user32 = ctypes.windll.user32
    WINDOWS_DISPONIBLE = True
except AttributeError:  # no es Windows
    _user32 = None
    WINDOWS_DISPONIBLE = False

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOW = 5
SW_RESTORE = 9
WM_CLOSE = 0x0010
DWMWA_CLOAKED = 14

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
# Ventanas (API de Windows)
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


def _titulo(hwnd: int) -> str:
    largo = _user32.GetWindowTextLengthW(hwnd)
    if largo <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(largo + 1)
    _user32.GetWindowTextW(hwnd, buf, largo + 1)
    return buf.value.strip()


def _pid(hwnd: int) -> int:
    pid = wt.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _info_ventana(hwnd: int, monitores: list[dict]) -> dict:
    r = wt.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(r))
    ancho, alto = r.right - r.left, r.bottom - r.top
    pid = _pid(hwnd)
    return {
        "titulo": _titulo(hwnd),
        "proceso": _obtener_proceso_por_pid(pid),
        "pid": pid or None,
        "hwnd": hwnd,
        "monitor": _detectar_monitor(r.left + ancho // 2, r.top + alto // 2, monitores),
        "maximizada": bool(_user32.IsZoomed(hwnd)),
        "minimizada": bool(_user32.IsIconic(hwnd)),
        "oculta": not _user32.IsWindowVisible(hwnd),
        "rect": {"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom},
        "width": ancho,
        "height": alto,
    }


def _es_ventana_principal_oculta(hwnd: int) -> bool:
    """
    Una ventana oculta cuenta solo si parece la ventana principal de una
    app escondida en la bandeja del sistema: las apps que "se cierran a la
    bandeja" (Discord, Steam...) minimizan su ventana y luego la ocultan.
    Así se descartan las decenas de ventanas internas ocultas que tiene
    cualquier programa ("Default IME", "NvSvc", "Hidden Window"...).
    """
    if _user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
        return False
    return bool(_user32.IsIconic(hwnd))


def _camuflada(hwnd: int) -> bool:
    """
    Ventana "cloaked": existe y Windows la da por visible, pero no se ve. Pasa
    con la ventana interna de las apps de la Microsoft Store cuando se
    minimizan (la Calculadora, p. ej.: se ve solo su marco minimizado) y con
    las ventanas de otros escritorios virtuales. Se ignoran: no son algo
    sobre lo que se pueda actuar.
    """
    estado = wt.DWORD()
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wt.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(estado), ctypes.sizeof(estado))
    except (AttributeError, OSError):
        return False
    return estado.value != 0


def _handles(incluir_ocultas: bool) -> list[int]:
    if not WINDOWS_DISPONIBLE:
        return []
    handles: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def recoger(hwnd, _):
        if _titulo(hwnd) and not _camuflada(hwnd):
            if _user32.IsWindowVisible(hwnd):
                handles.append(hwnd)
            elif incluir_ocultas and _es_ventana_principal_oculta(hwnd):
                handles.append(hwnd)
        return True

    _user32.EnumWindows(recoger, 0)
    return handles


def listar_ventanas_abiertas(monitores: list[dict] | None = None,
                             incluir_ocultas: bool = False) -> list[dict]:
    """
    Ventanas con título en todos los monitores. Por defecto solo las
    visibles (incluidas las minimizadas en la barra de tareas); con
    incluir_ocultas=True también las escondidas en la bandeja del sistema.
    """
    if monitores is None:
        monitores = obtener_monitores()
    # La caché PID -> proceso solo vale para esta enumeración: Windows reutiliza
    # los PID, y un nombre viejo haría que "cierra discord" cerrase otra app.
    _cache_procesos.clear()
    ventanas = []
    for hwnd in _handles(incluir_ocultas):
        info = _info_ventana(hwnd, monitores)
        if info["width"] <= 0 or info["height"] <= 0:
            continue
        ventanas.append(info)
    ventanas.sort(key=lambda v: (v["monitor"], v["titulo"].lower()))
    return ventanas


def handles_ventanas() -> set[int]:
    """Identificadores de las ventanas visibles con título (para detectar ventanas nuevas)."""
    return set(_handles(incluir_ocultas=False))


def buscar_ventana(termino: str, monitores: list[dict] | None = None,
                   incluir_ocultas: bool = False) -> list[dict]:
    """Ventanas cuyo título o proceso contiene el término (sin distinguir mayúsculas ni tildes)."""
    termino = normalizar(termino)
    if not termino:
        return []
    return [
        v for v in listar_ventanas_abiertas(monitores, incluir_ocultas)
        if termino in normalizar(v["titulo"])
        or (v["proceso"] and termino in normalizar(v["proceso"]))
    ]


def ventana_abierta(termino: str) -> bool:
    return len(buscar_ventana(termino, incluir_ocultas=True)) > 0


def es_visible(ventana: dict) -> bool:
    return not ventana["minimizada"] and not ventana["oculta"]


def ventana_visible(hwnd: int) -> bool:
    return bool(WINDOWS_DISPONIBLE and _user32.IsWindowVisible(hwnd) and not _user32.IsIconic(hwnd))


def traer_al_frente(hwnd: int) -> bool:
    """
    Muestra la ventana (aunque esté minimizada u oculta en la bandeja) y le
    da el foco. Devuelve True si queda visible.
    """
    if not WINDOWS_DISPONIBLE:
        return False
    if _user32.IsIconic(hwnd) or not _user32.IsWindowVisible(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)
    _user32.ShowWindow(hwnd, SW_SHOW)
    _dar_foco(hwnd)
    time.sleep(0.3)
    return ventana_visible(hwnd)


def _dar_foco(hwnd: int) -> bool:
    """
    Windows solo deja a un programa quitarle el foco a otro en ciertos casos.
    Antes se usaba el truco de pulsar y soltar ALT, pero el "soltar" llega a
    la ventana nueva y, en las que tienen barra de menú, activa el menú, que
    se come la primera tecla que se escriba después. Ahora:
    1. Se engancha un momento la entrada de teclado de la ventana activa
       (AttachThreadInput), que es lo que Windows permite para esto.
    2. Si no basta, un movimiento de ratón de 0 píxeles (cuenta como
       "entrada reciente" y no pulsa ninguna tecla) y se reintenta.
    """
    actual = _user32.GetForegroundWindow()
    if actual == hwnd:
        return True
    mio = ctypes.windll.kernel32.GetCurrentThreadId()
    hilo_actual = _user32.GetWindowThreadProcessId(actual, None) if actual else 0
    enganchado = bool(hilo_actual and hilo_actual != mio
                      and _user32.AttachThreadInput(mio, hilo_actual, True))
    try:
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if enganchado:
            _user32.AttachThreadInput(mio, hilo_actual, False)
    if _user32.GetForegroundWindow() == hwnd:
        return True
    from core.teclado import mover_raton_nulo
    mover_raton_nulo()
    _user32.SetForegroundWindow(hwnd)
    return _user32.GetForegroundWindow() == hwnd


def hwnd_activo() -> int:
    """Identificador de la ventana que tiene el foco ahora mismo (0 si no se sabe)."""
    return int(_user32.GetForegroundWindow() or 0) if WINDOWS_DISPONIBLE else 0


def poner_foco(hwnd: int, intentos: int = 3) -> bool:
    """Trae la ventana al frente y comprueba que de verdad tiene el foco del teclado."""
    for _ in range(intentos):
        traer_al_frente(hwnd)
        if hwnd_activo() == hwnd:
            return True
        time.sleep(0.2)
    return False


def ventana_existe(hwnd: int) -> bool:
    """True si la ventana sigue existiendo (visible u oculta)."""
    return bool(WINDOWS_DISPONIBLE and _user32.IsWindow(hwnd))


def ventana_mostrada(hwnd: int) -> bool:
    """True si la ventana existe y no está oculta (aunque esté minimizada en la barra de tareas)."""
    return bool(WINDOWS_DISPONIBLE and _user32.IsWindow(hwnd) and _user32.IsWindowVisible(hwnd))


def pedir_cierre(hwnd: int) -> bool:
    """
    Pide a la ventana que se cierre, igual que pulsar su X (WM_CLOSE). La
    app decide qué hacer: cerrarse, preguntar si guardar cambios o
    esconderse en la bandeja del sistema.
    """
    return bool(WINDOWS_DISPONIBLE and _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def obtener_ventana_activa(monitores: list[dict] | None = None) -> dict:
    """Información sobre la ventana que tiene el foco ahora mismo."""
    if not WINDOWS_DISPONIBLE:
        return {"error": "Solo disponible en Windows"}
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return {"error": "No se pudo obtener la ventana activa"}
    if monitores is None:
        monitores = obtener_monitores()
    info = _info_ventana(hwnd, monitores)
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
        return bool(buscar_ventana(argumento, incluir_ocultas=True))
    if predicado == "visible":
        return any(es_visible(v) for v in buscar_ventana(argumento, incluir_ocultas=True))
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

    print("\n=== Todas las ventanas (incluidas las ocultas en la bandeja) ===")
    for v in listar_ventanas_abiertas(monitores, incluir_ocultas=True):
        proceso = v["proceso"] or "desconocido"
        if v["oculta"]:
            estado = "OCULTA"
        else:
            estado = "MAX" if v["maximizada"] else ("min" if v["minimizada"] else "normal")
        print(f"  [Monitor {v['monitor']}] {v['titulo']!r} ({proceso}) "
              f"{v['width']}x{v['height']} [{estado}]")
