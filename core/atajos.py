"""
Conocimiento por aplicación: atajos de teclado (core/atajos_apps.json).

El LLM los usa con pulsar_teclas para hacer cosas para las que no hay una
skill específica ("abre una pestaña nueva", "ve al canal general de
Discord"). Para no alargar el prompt, solo se le pasan los de las apps que
salen en la frase y los de la última app usada.

Es un archivo editable: añade apps o atajos a mano. Más adelante la
grabadora semántica (fase 5) los irá aprendiendo de tus demostraciones.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from core.estado import normalizar

RUTA_ATAJOS = Path(__file__).parent / "atajos_apps.json"


def cargar_atajos(ruta: Path = RUTA_ATAJOS) -> dict[str, dict]:
    if not ruta.is_file():
        return {}
    return json.loads(ruta.read_text(encoding="utf-8"))


def apps_mencionadas(texto: str, atajos: dict[str, dict]) -> list[str]:
    texto = f" {re.sub(r'[^a-z0-9ñ ]', ' ', normalizar(texto))} "
    encontradas = []
    for app, info in atajos.items():
        nombres = [app, *info.get("nombres", [])]
        if any(f" {normalizar(n)} " in texto for n in nombres):
            encontradas.append(app)
    return encontradas


def app_conocida(nombre: str | None, atajos: dict[str, dict]) -> str | None:
    """La entrada de atajos que corresponde a un nombre de app ("Google Chrome", "chrome"...)."""
    if not nombre:
        return None
    n = normalizar(nombre)
    for app, info in atajos.items():
        if n in {normalizar(x) for x in [app, *info.get("nombres", [])]}:
            return app
    return None


def describir_atajos(texto: str, ultima_aplicacion: str | None, atajos: dict[str, dict]) -> str:
    """Bloque de texto para el prompt con los atajos que vienen al caso (vacío si ninguno)."""
    apps = apps_mencionadas(texto, atajos)
    ultima = app_conocida(ultima_aplicacion, atajos)
    if ultima and ultima not in apps:
        apps.append(ultima)
    if not apps:
        return ""
    lineas = ["Atajos de teclado conocidos (úsalos con pulsar_teclas, con 'aplicacion'):"]
    for app in apps:
        lineas.append(f"- {app}:")
        lineas += [f"    {que}: '{teclas}'" for que, teclas in atajos[app]["atajos"].items()]
    return "\n".join(lineas)
