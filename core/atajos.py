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
    lineas = []
    con_atajos = [a for a in apps if atajos[a].get("atajos")]
    if con_atajos:
        lineas.append("Atajos de teclado conocidos (úsalos con pulsar_teclas, con 'aplicacion'):")
        for app in con_atajos:
            lineas.append(f"- {app}:")
            lineas += [f"    {que}: '{teclas}'" for que, teclas in atajos[app]["atajos"].items()]
    # Botones y campos que se ven en la app (hacer_clic y escribir_texto con 'campo').
    con_controles = [a for a in apps if atajos[a].get("botones") or atajos[a].get("campos")]
    if con_controles:
        lineas.append("Botones y campos conocidos (botones con hacer_clic 'elemento'; campos con "
                      "escribir_texto 'campo'; siempre con 'aplicacion'):")
        for app in con_controles:
            lineas.append(f"- {app}:")
            lineas += [f"    botón para {que}: '{nombre}'" for que, nombre in atajos[app].get("botones", {}).items()]
            lineas += [f"    campo para {que}: '{nombre}'" for que, nombre in atajos[app].get("campos", {}).items()]
    return "\n".join(lineas)


TECLAS_ENTER = {"enter", "intro", "return"}


def _teclas(teclas: str) -> str:
    t = normalizar(teclas).replace("+", " ").replace("ctrl", "control")
    return " ".join(t.split())


def atajo_pide_enter(app: str | None, teclas: str, atajos: dict[str, dict]) -> bool:
    """¿El atajo es de los que van "después escribir ... y pulsar enter" (barra de direcciones, selector)?"""
    entrada = app_conocida(app, atajos)
    if not entrada:
        return False
    return any(_teclas(t) == _teclas(teclas) and "pulsar enter" in normalizar(que)
               for que, t in atajos[entrada].get("atajos", {}).items())


def completar_enter(pasos: list[tuple[str, dict]], atajos: dict[str, dict]) -> list[tuple[str, dict]]:
    """
    Añade el Enter que falta tras escribir en la barra de direcciones o en un
    selector: "busca en google música" = Ctrl+L, escribir y ENTER. El LLM a
    veces se lo deja y la búsqueda se queda escrita sin hacer.
    """
    resultado = list(pasos)
    i, app = 0, None
    while i < len(resultado) - 1:
        skill, params = resultado[i]
        app = params.get("aplicacion") or app
        siguiente, params_sig = resultado[i + 1]
        if (skill == "pulsar_teclas" and siguiente == "escribir_texto"
                and atajo_pide_enter(app, params.get("teclas", ""), atajos)):
            despues = resultado[i + 2] if i + 2 < len(resultado) else None
            ya_hay_enter = (despues is not None and despues[0] == "pulsar_teclas"
                            and _teclas(despues[1].get("teclas", "")) in TECLAS_ENTER)
            if not ya_hay_enter:
                enter = {"teclas": "enter"}
                if params_sig.get("aplicacion") or app:
                    enter["aplicacion"] = params_sig.get("aplicacion") or app
                resultado.insert(i + 2, ("pulsar_teclas", enter))
            i += 2
        i += 1
    return resultado


PIDE_ESCRIBIR = re.compile(r"\b(busc|escrib|entr[ae]\b|ve al|ve a la|pon\b)\w*")


def plan_incompleto(pasos: list[tuple[str, dict]], texto: str, atajos: dict[str, dict]) -> str | None:
    """
    El plan se queda en "ir a la barra de direcciones" sin escribir nada, y la
    orden pedía buscar o escribir algo ("busca recetas en google" → solo
    Ctrl+L). Devuelve el motivo (para que el LLM lo corrija) o None.
    """
    if not PIDE_ESCRIBIR.search(normalizar(texto)):
        return None
    app = None
    for i, (skill, params) in enumerate(pasos):
        app = params.get("aplicacion") or app
        if skill == "pulsar_teclas" and atajo_pide_enter(app, params.get("teclas", ""), atajos):
            siguiente = pasos[i + 1][0] if i + 1 < len(pasos) else None
            if siguiente != "escribir_texto":
                return (f"después de '{params.get('teclas')}' hay que escribir lo que pide la orden "
                        "(escribir_texto) y pulsar enter: faltan esos pasos.")
    return None


def valores_conocidos(app: str, atajos: dict[str, dict]) -> set[str]:
    """Teclas, botones y campos de una app: el LLM puede usarlos aunque no estén en la frase."""
    info = atajos.get(app, {})
    return {normalizar(v) for clave in ("atajos", "botones", "campos") for v in info.get(clave, {}).values()}
