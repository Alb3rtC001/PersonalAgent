"""
Localizar las ventanas de una aplicación a partir de cómo la nombra el
usuario ("calculadora", "navegador", "discord"). Lo usan las skills que
actúan sobre una app ya abierta: cerrar_aplicacion, escribir_texto,
pulsar_teclas.

La coincidencia es estricta para no tocar lo que no toca: el título es
exactamente el nombre de la app, acaba en " - <app>" (p. ej.
"README.md - Visual Studio Code") o el proceso se llama como la app
(Discord.exe). Una pestaña de Chrome que hable de Discord no cuenta: su
título acaba en " - Google Chrome".
"""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from config import ALIAS_APLICACIONES, CADUCIDAD_CONTEXTO
from core.estado import es_visible, listar_ventanas_abiertas, normalizar
from core.skills.abrir_aplicacion import AppInstalada, buscar_app

SEPARADORES_TITULO = (" - ", " — ", " | ")


def nombres_de_app(aplicacion: str, apps: list[AppInstalada]) -> list[str]:
    """Lo que ha dicho el usuario, su alias y el nombre de la app en el menú Inicio."""
    nombres = {aplicacion, ALIAS_APLICACIONES.get(normalizar(aplicacion), aplicacion)}
    candidatas = buscar_app(aplicacion, apps) if apps else []
    if candidatas:
        nombres.add(candidatas[0][1].nombre)
    return sorted(n for n in nombres if n.strip())


def ventana_de_app(ventana: dict, nombres: list[str]) -> bool:
    """¿Esta ventana es de la app? (coincidencia estricta, ver docstring del módulo)."""
    titulo = normalizar(ventana.get("titulo", ""))
    proceso = normalizar(Path(ventana.get("proceso") or "").stem)
    for nombre in nombres:
        n = normalizar(nombre)
        if not n:
            continue
        if titulo == n or (proceso and proceso == n.replace(" ", "")):
            return True
        if any(titulo.endswith(sep + n) for sep in SEPARADORES_TITULO):
            return True
    return False


def ventanas_de_app(nombres: list[str], incluir_ocultas: bool = True) -> list[dict]:
    return [v for v in listar_ventanas_abiertas(incluir_ocultas=incluir_ocultas)
            if ventana_de_app(v, nombres)]


def ventana_principal(nombres: list[str]) -> dict | None:
    """La ventana de la app donde actuar: la visible antes que la minimizada u oculta."""
    ventanas = ventanas_de_app(nombres)
    if not ventanas:
        return None
    return sorted(ventanas, key=lambda v: (not es_visible(v), v["oculta"]))[0]


# --- Varias ventanas de la misma app: cuál usar --------------------------------
#
# Steam tiene la principal y la "Lista de amigos"; Chrome puede tener dos
# ventanas (no pestañas). Para no actuar en la que no es:
#   1. si solo hay una a la vista (no escondida en la bandeja), esa;
#   2. la que elegiste antes (durante CADUCIDAD_CONTEXTO), si sigue abierta;
#   3. la que se llama exactamente como la app ("Steam" frente a "Lista de amigos");
#   4. si sigue habiendo duda, se pregunta: "¿cuál uso?" (número o parte del título).
# Sin nadie a quien preguntar (tareas programadas, API) no se elige a ciegas:
# se devuelve un error con las ventanas que hay.

Preguntar = Callable[[str], str]
_preguntar: Preguntar | None = None
_elegidas: dict[str, tuple[int, float]] = {}      # proceso → (hwnd, cuándo se eligió)
_lock = threading.Lock()


@contextmanager
def preguntando_con(pedir: Preguntar | None):
    """Mientras dura, si hay que elegir ventana se le pregunta al usuario con `pedir`."""
    global _preguntar
    anterior, _preguntar = _preguntar, pedir
    try:
        yield
    finally:
        _preguntar = anterior


def _clave(ventana: dict) -> str:
    return normalizar(ventana.get("proceso") or "") or str(ventana.get("hwnd"))


def recordar_ventana(ventana: dict) -> None:
    """La próxima vez que haya varias ventanas de esta app, se usa esta."""
    with _lock:
        _elegidas[_clave(ventana)] = (ventana["hwnd"], time.monotonic())


def olvidar_ventanas() -> None:
    with _lock:
        _elegidas.clear()


def _recordada(ventanas: list[dict]) -> dict | None:
    with _lock:
        for v in ventanas:
            elegida = _elegidas.get(_clave(v))
            if elegida and elegida[0] == v["hwnd"] and time.monotonic() - elegida[1] < CADUCIDAD_CONTEXTO:
                return v
    return None


def interpretar_eleccion(respuesta: str, opciones: list[dict]) -> dict | None:
    """'2', 'la 2', 'la segunda' o parte del título → la ventana; None si no está claro."""
    r = normalizar(respuesta or "").strip()
    if not r:
        return None
    ordinales = {"primera": 1, "segunda": 2, "tercera": 3, "cuarta": 4, "quinta": 5}
    numeros = [int(x) for x in re.findall(r"\d+", r)] + [n for p, n in ordinales.items() if p in r.split()]
    if len(numeros) == 1 and 1 <= numeros[0] <= len(opciones):
        return opciones[numeros[0] - 1]
    # "la de youtube", "la del correo": las palabras con significado, todas en el título.
    palabras = [p for p in re.findall(r"\w+", r) if len(p) > 2 and p not in PALABRAS_VACIAS]
    if not palabras:
        return None
    coinciden = [v for v in opciones
                 if all(p in re.findall(r"\w+", normalizar(v.get("titulo", ""))) for p in palabras)]
    return coinciden[0] if len(coinciden) == 1 else None


PALABRAS_VACIAS = {"las", "los", "del", "una", "uno", "que", "ventana", "esa", "esta", "usa", "uso", "pon"}


def elegir_entre(ventanas: list[dict], aplicacion: str, nombres: list[str] | None = None
                 ) -> tuple[dict | None, str | None]:
    """(ventana, None), o (None, motivo) si hay varias y no se ha podido decidir."""
    if not ventanas:
        return None, None
    if len(ventanas) == 1:
        return ventanas[0], None
    a_la_vista = [v for v in ventanas if not v.get("oculta")] or ventanas
    if len(a_la_vista) == 1:
        return a_la_vista[0], None
    recordada = _recordada(a_la_vista)
    if recordada:
        return recordada, None
    exactos = {normalizar(n) for n in (nombres or [aplicacion]) if n}
    exactas = [v for v in a_la_vista if normalizar(v.get("titulo", "")) in exactos]
    if len(exactas) == 1:
        return exactas[0], None

    opciones = exactas or a_la_vista
    lista = "; ".join(f"{i}) {v.get('titulo') or v.get('proceso')}" for i, v in enumerate(opciones, 1))
    pregunta = f"Hay {len(opciones)} ventanas de '{aplicacion}': {lista}. ¿Cuál uso? (número o parte del título)"
    if _preguntar is None:
        return None, f"Hay {len(opciones)} ventanas de '{aplicacion}' ({lista}) y no sé cuál usar."
    respuesta = _preguntar(pregunta)
    elegida = interpretar_eleccion(respuesta, opciones)
    if elegida is None:
        return None, f"No sé qué ventana es '{respuesta}': no hago nada."
    recordar_ventana(elegida)
    return elegida, None


def elegir_ventana(nombres: list[str], aplicacion: str) -> tuple[dict | None, str | None]:
    """Como elegir_entre, con las ventanas de la app (coincidencia estricta)."""
    return elegir_entre(ventanas_de_app(nombres), aplicacion, nombres)
