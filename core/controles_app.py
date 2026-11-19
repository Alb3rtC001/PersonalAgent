"""
Apps nuevas: lo que se ve en su ventana como contexto para el LLM.

De las apps de core/atajos_apps.json el LLM ya conoce los botones y campos.
De las demás no sabe nada: si la orden nombra una app abierta que no está ahí
("en VLC dale a pausa") o va a la última usada, se leen (UI Automation, en
la CPU, ~0,5 s) los botones y campos que se ven en su ventana y se le pasan,
para que pueda planear hacer_clic y escribir_texto con nombres que existen.
Si sale bien, la memoria de episodios guarda el plan: la próxima vez ya lo sabe.

Solo nombres de controles (y nada de ventanas prohibidas): no se le pasa el
texto de la ventana.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from core.estado import listar_ventanas_abiertas, normalizar

log = logging.getLogger("personalagent")

MAX_BOTONES = 80
MAX_CAMPOS = 8
MAX_LARGO_NOMBRE = 40
SEPARADORES = (" - ", " — ", " | ")
# Nombres de ventana que no identifican una app (están en cualquier frase).
# Los botones del marco de la ventana: no son de la app y ocupan sitio en el prompt.
MARCO = ("minimizar", "maximizar", "restaurar", "cerrar", "minimize", "maximize", "restore", "close")
GENERICOS = {"ventana", "configuracion", "ajustes", "inicio", "programa", "aplicacion", "nueva", "sin titulo"}


def nombres_de_ventana(ventana: dict) -> set[str]:
    """Cómo se puede nombrar la app de una ventana: su programa y la parte final del título."""
    nombres = set()
    proceso = normalizar(Path(ventana.get("proceso") or "").stem)
    if len(proceso) >= 3:
        nombres.add(proceso)
    titulo = ventana.get("titulo") or ""
    for sep in SEPARADORES:
        if sep in titulo:
            titulo = titulo.rsplit(sep, 1)[1]
    titulo = normalizar(titulo)
    if titulo:
        nombres.add(titulo)
        primera = titulo.split()[0]
        if len(primera) >= 3:
            nombres.add(primera)      # "vlc" de "VLC media player"
    return {n for n in nombres if n not in GENERICOS}


def _palabras(texto: str) -> str:
    return f" {' '.join(re.sub(r'[^a-z0-9ñ ]', ' ', normalizar(texto)).split())} "


def ventana_nombrada(texto: str, ventanas: list[dict]) -> dict | None:
    """La ventana (visible) de la app que nombra la orden, o None."""
    frase = _palabras(texto)
    for v in ventanas:
        if v.get("oculta") or v.get("minimizada") or v.get("pid") == os.getpid():
            continue
        if any(f" {n} " in frase for n in nombres_de_ventana(v)):
            return v
    return None


def leer_controles(ventana: dict) -> tuple[list[str], list[str]]:
    """(botones, campos) que se ven en la ventana, por su nombre, sin repetir."""
    from core import uia
    from core.seguridad import ventana_prohibida
    if ventana_prohibida(ventana):
        return [], []
    with uia.en_hilo():
        botones = list(dict.fromkeys(
            c.Name.strip() for c in uia.controles_pulsables(ventana["hwnd"])
            if len(c.Name.strip()) <= MAX_LARGO_NOMBRE and c.ControlTypeName != "TextControl"
            and not normalizar(c.Name).startswith(MARCO)))
        campos = list(dict.fromkeys(uia.nombre_de_campo(c) for c in uia.campos_editables(ventana["hwnd"])))
    return botones[:MAX_BOTONES], campos[:MAX_CAMPOS]


def contexto_app_nueva(texto: str, ultima: str | None, conocida) -> tuple[str, set[str]]:
    """
    Bloque para el prompt con los controles de la app nueva que nombra la
    orden (o de la última usada), y sus nombres como valores válidos.
    `conocida(nombre)`: True si la app ya está en atajos_apps.json (entonces nada).
    """
    ventanas = listar_ventanas_abiertas()
    ventana = ventana_nombrada(texto, ventanas)
    if ventana is None and ultima and not conocida(ultima):
        ventana = ventana_nombrada(ultima, ventanas)
    if ventana is None or any(conocida(n) for n in nombres_de_ventana(ventana)):
        return "", set()
    try:
        botones, campos = leer_controles(ventana)
    except Exception:
        log.debug("No pude leer los controles de '%s'.", ventana.get("titulo"), exc_info=True)
        return "", set()
    if not botones and not campos:
        return "", set()
    app = (ventana.get("titulo") or "").rsplit(" - ", 1)[-1] or ventana.get("proceso")
    lineas = [f"Controles que se ven ahora en la ventana de {app} (app sin atajos conocidos; "
              "botones con hacer_clic 'elemento', campos con escribir_texto 'campo', siempre con "
              "'aplicacion'):"]
    if botones:
        lineas.append("  botones: " + ", ".join(f"'{b}'" for b in botones))
    if campos:
        lineas.append("  campos: " + ", ".join(f"'{c}'" for c in campos))
    log.debug("App nueva '%s': %d botones y %d campos para el LLM.", app, len(botones), len(campos))
    return "\n".join(lineas), {normalizar(n) for n in botones + campos}
