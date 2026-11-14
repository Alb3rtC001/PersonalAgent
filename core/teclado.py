"""
Teclado virtual: escribir texto y pulsar teclas en la ventana que tiene el foco.

Se usa SendInput de Windows directamente (no pyautogui):
- El texto se envía como caracteres Unicode (KEYEVENTF_UNICODE), así que
  sale igual con cualquier distribución de teclado (español, inglés...) y
  admite tildes, eñes y símbolos sin pasar por el portapapeles.
- Las teclas (enter, tab, ctrl+s...) se envían como teclas virtuales.

Limitación de Windows: no se puede escribir en ventanas de programas
ejecutados como administrador (el Administrador de tareas, por ejemplo)
desde un programa que no lo es; la entrada se descarta sin avisar.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import re
import time

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MAX_TECLAS = 20   # tope de pulsaciones por orden (por seguridad)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _UNION)]


def _enviar(eventos: list[_INPUT]) -> int:
    if not eventos:
        return 0
    try:
        user32 = ctypes.windll.user32
    except AttributeError:  # no es Windows
        return 0
    array = (_INPUT * len(eventos))(*eventos)
    return user32.SendInput(len(eventos), array, ctypes.sizeof(_INPUT))


def _evento(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    entrada = _INPUT(type=INPUT_KEYBOARD)
    entrada.u.ki = _KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return entrada


def mover_raton_nulo() -> bool:
    """Movimiento de ratón de 0 píxeles: no mueve nada, pero cuenta como entrada reciente."""
    entrada = _INPUT(type=0)  # INPUT_MOUSE
    entrada.u.mi = _MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=0x0001, time=0, dwExtraInfo=0)
    return _enviar([entrada]) == 1


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------

def limpiar_texto_a_escribir(texto: str) -> str:
    """
    Sin saltos de línea ni tabuladores: un salto de línea sería un Enter
    (enviar un mensaje, aceptar un diálogo...). Para eso está pulsar_teclas.
    """
    return re.sub(r"[\r\n\t]+", " ", texto)


def escribir(texto: str, pausa: float = 0.005) -> int:
    """Escribe el texto en la ventana con el foco. Devuelve los caracteres enviados."""
    texto = limpiar_texto_a_escribir(texto)
    enviados = 0
    # UTF-16: los caracteres fuera del plano básico (emojis) van en dos unidades.
    datos = texto.encode("utf-16-le")
    unidades = [int.from_bytes(datos[i:i + 2], "little") for i in range(0, len(datos), 2)]
    for unidad in unidades:
        if _enviar([_evento(scan=unidad, flags=KEYEVENTF_UNICODE),
                    _evento(scan=unidad, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]) == 2:
            enviados += 1
        time.sleep(pausa)  # algunas apps pierden caracteres si llegan todos de golpe
    return enviados


# ---------------------------------------------------------------------------
# Teclas
# ---------------------------------------------------------------------------

MODIFICADORES = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "mayus": 0x10,
    "mayusculas": 0x10, "win": 0x5B, "windows": 0x5B,
}
TECLAS = {
    "enter": 0x0D, "intro": 0x0D, "tab": 0x09, "tabulador": 0x09, "esc": 0x1B,
    "escape": 0x1B, "espacio": 0x20, "space": 0x20, "retroceso": 0x08,
    "backspace": 0x08, "borrar": 0x08, "suprimir": 0x2E, "supr": 0x2E,
    "delete": 0x2E, "insertar": 0x2D, "insert": 0x2D, "arriba": 0x26,
    "abajo": 0x28, "izquierda": 0x25, "derecha": 0x27, "up": 0x26, "down": 0x28,
    "left": 0x25, "right": 0x27, "inicio": 0x24, "home": 0x24, "fin": 0x23,
    "end": 0x23, "repag": 0x21, "pageup": 0x21, "avpag": 0x22, "pagedown": 0x22,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}
# Teclas que Windows trata como "extendidas" (sin la marca, algunas apps las confunden).
EXTENDIDAS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B}
# Palabras que se ignoran: "pulsa la flecha arriba y luego enter".
RELLENO = {"flecha", "tecla", "teclas", "la", "el", "luego", "despues", "de", "nuevo", "otra", "vez"}
# "y"/"e" son conectores ("tab y enter"), salvo detrás de un modificador
# ("control y") o si son lo único que se pide ("pulsa e"): entonces son la letra.
CONECTORES = {"y", "e"}
NUMEROS = {"una": 1, "un": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
           "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}


class ErrorTeclas(ValueError):
    pass


def _vk(nombre: str) -> int | None:
    if nombre in TECLAS:
        return TECLAS[nombre]
    if len(nombre) == 1 and (nombre.isascii() and nombre.isalnum()):
        return ord(nombre.upper())
    return None


def interpretar_teclas(texto: str) -> list[tuple[int, ...]]:
    """
    "enter" -> [(VK_ENTER,)]; "control s" o "ctrl+s" -> [(VK_CTRL, VK_S)];
    "tab tab enter" -> 3 pulsaciones; "tab 3 veces" -> 3 tabs;
    "control mayúsculas esc" -> [(CTRL, SHIFT, ESC)].
    Lanza ErrorTeclas si hay una tecla que no conoce (nunca adivina).
    """
    from core.estado import normalizar

    normal = normalizar(texto).replace("re pag", "repag").replace("av pag", "avpag")
    tokens = [t for t in re.split(r"[\s+,]+", normal) if t]
    pulsaciones: list[tuple[int, ...]] = []
    pendientes: list[int] = []   # modificadores que esperan su tecla
    i = 0
    while i < len(tokens):
        t = tokens[i]
        veces = int(t) if t.isdigit() else NUMEROS.get(t)
        if veces is not None and i + 1 < len(tokens) and tokens[i + 1] in ("veces", "vez"):
            if not pulsaciones:
                raise ErrorTeclas(f"'{t} veces' sin una tecla delante.")
            if veces > MAX_TECLAS:
                raise ErrorTeclas(f"Demasiadas pulsaciones ({veces}, máximo {MAX_TECLAS}).")
            pulsaciones += [pulsaciones[-1]] * (veces - 1)
            i += 2
            continue
        if t in RELLENO or (t in CONECTORES and not pendientes and len(tokens) > 1):
            i += 1
            continue
        if t in MODIFICADORES:
            pendientes.append(MODIFICADORES[t])
        else:
            vk = _vk(t)
            if vk is None:
                raise ErrorTeclas(f"No conozco la tecla '{t}'.")
            pulsaciones.append((*pendientes, vk))
            pendientes = []
        i += 1
    if pendientes:  # "pulsa windows": el modificador solo
        pulsaciones.append(tuple(pendientes))
    if not pulsaciones:
        raise ErrorTeclas("No has dicho qué tecla pulsar.")
    if len(pulsaciones) > MAX_TECLAS:
        raise ErrorTeclas(f"Demasiadas pulsaciones ({len(pulsaciones)}, máximo {MAX_TECLAS}).")
    return pulsaciones


def pulsar(combinacion: tuple[int, ...]) -> bool:
    """Pulsa una combinación (los modificadores primero, se sueltan al revés)."""
    def flags(vk: int) -> int:
        return KEYEVENTF_EXTENDEDKEY if vk in EXTENDIDAS else 0

    eventos = [_evento(vk=vk, flags=flags(vk)) for vk in combinacion]
    eventos += [_evento(vk=vk, flags=flags(vk) | KEYEVENTF_KEYUP) for vk in reversed(combinacion)]
    return _enviar(eventos) == len(eventos)


def describir_combinacion(combinacion: tuple[int, ...]) -> str:
    nombres = {v: k for k, v in {**TECLAS, **MODIFICADORES}.items()}
    nombres.update({0x11: "ctrl", 0x10: "shift", 0x5B: "win", 0x0D: "enter", 0x1B: "esc",
                    0x08: "retroceso", 0x2E: "suprimir", 0x20: "espacio", 0x09: "tab",
                    0x26: "arriba", 0x28: "abajo", 0x25: "izquierda", 0x27: "derecha",
                    0x24: "inicio", 0x23: "fin", 0x21: "repag", 0x22: "avpag"})
    return "+".join(nombres.get(vk, chr(vk).lower()) for vk in combinacion)
