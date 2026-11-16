"""
Acciones en lenguaje normal para las ventanas de seguridad.

El agente describe lo que va a hacer como "hacer_clic(elemento='JUGAR',
aplicacion='Steam') → pulsar_teclas(teclas='enter')" (así sale en los logs y
en el plan). Para confirmar, mejor leer "Pulsar «JUGAR» en Steam" y "Pulsar
Enter". Lo que no se sabe traducir se enseña tal cual.
"""

from __future__ import annotations

import re

_PASO = re.compile(r"(\w+)\((.*?)\)(?=\s*→|\s*$)")
_ARGUMENTO = re.compile(r"(\w+)='(.*?)'(?=, \w+=|$)")
_PROGRAMADA = re.compile(r"^programar para (.+?): (.+)$", re.S)

_NOMBRE_TECLA = {"control": "Ctrl", "ctrl": "Ctrl", "alt": "Alt", "shift": "Mayús", "mayus": "Mayús",
                 "enter": "Enter", "intro": "Enter", "return": "Enter", "tab": "Tab", "esc": "Esc",
                 "escape": "Esc", "supr": "Supr", "delete": "Supr", "win": "Windows", "espacio": "Espacio",
                 "space": "Espacio", "izquierda": "←", "derecha": "→", "arriba": "↑", "abajo": "↓"}


def teclas_legibles(teclas: str) -> str:
    """"control shift t" → "Ctrl + Mayús + T"; "tab dos veces" se deja con sus palabras."""
    partes = teclas.replace("+", " ").split()
    if any(p.lower() in {"veces", "vez"} for p in partes):
        return teclas
    return " + ".join(_NOMBRE_TECLA.get(p.lower(), p.upper() if len(p) == 1 else p.capitalize()) for p in partes)


def _en(app: str | None) -> str:
    return f" en {app}" if app else ""


def paso_legible(skill: str, p: dict[str, str]) -> str:
    app = p.get("aplicacion")
    frases = {
        "abrir_aplicacion": lambda: f"Abrir {app}",
        "cerrar_aplicacion": lambda: f"Cerrar {app}",
        "restaurar_ventana": lambda: f"Traer al frente la ventana de {app}",
        "hacer_clic": lambda: f"Pulsar «{p.get('elemento', '')}»{_en(app)}",
        "escribir_texto": lambda: (f"Escribir «{p.get('texto', '')}»"
                                   + (f" en el campo «{p['campo']}»" if p.get("campo") else "")
                                   + (f" de {app}" if app and p.get("campo") else _en(app))),
        "pulsar_teclas": lambda: f"Pulsar {teclas_legibles(p.get('teclas', ''))}{_en(app)}",
        "ejecutar_en_steam": lambda: f"Lanzar {p.get('juego', '')} desde Steam",
        "crear_nota": lambda: f"Crear una nota: «{p.get('contenido', '')}»",
        "actualizaciones_steam": lambda: "Comprobar si hay actualizaciones en Steam",
        "ver_tareas": lambda: "Ver las tareas programadas",
        "cancelar_tarea": lambda: f"Cancelar la tarea programada «{p.get('tarea', '')}»",
        "leer_pantalla": lambda: f"Leer la pantalla{_en(app)}",
    }
    if skill in frases and (app or skill not in {"abrir_aplicacion", "cerrar_aplicacion", "restaurar_ventana"}):
        return frases[skill]()
    detalle = ", ".join(f"{k}: {v}" for k, v in p.items())
    return skill.replace("_", " ").capitalize() + (f" ({detalle})" if detalle else "")


def accion_legible(descripcion: str) -> tuple[str | None, list[str]]:
    """
    (cuándo, pasos): "programar para mañana a las 9: abrir_aplicacion(...)" →
    ("mañana a las 9", ["Abrir Steam"]). Si no se entiende, ([descripcion]).
    """
    cuando = None
    programada = _PROGRAMADA.match(descripcion.strip())
    if programada:
        cuando, descripcion = programada.group(1), programada.group(2)
    pasos = [paso_legible(m.group(1), dict(_ARGUMENTO.findall(m.group(2))))
             for m in _PASO.finditer(descripcion)]
    return cuando, pasos or [descripcion]
