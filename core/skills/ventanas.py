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

from pathlib import Path

from config import ALIAS_APLICACIONES
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
