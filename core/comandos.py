"""
Comandos del propio agente (no son órdenes): los usan la consola y la interfaz.

    llm / llm on / llm off      estado del LLM, activarlo o descargarlo
    seguro / seguro on / off    modo seguro: confirmar todo lo que no sea de lectura
    actividad                   las últimas acciones del registro de actividad
    reanudar                    quitar la pausa del botón de pánico
    ayuda                       esta lista
"""

from __future__ import annotations

from core import control
from core.seguridad import activar_modo_seguro, modo_seguro, registrar_actividad, ultima_actividad

AYUDA = ("Comandos: 'llm' / 'llm on' / 'llm off', 'seguro' / 'seguro on' / 'seguro off', "
         "'actividad', 'reanudar', 'ayuda', 'salir'.")


def describir_llm(estado: dict) -> str:
    gpu = ""
    if estado.get("vram_libre_mib") is not None:
        gpu = f" GPU: {estado['vram_libre_mib']} MiB libres, {estado['temperatura_gpu']} °C."
    if not estado["activo"]:
        return "LLM desactivado: solo clasificador, sin usar la GPU." + gpu
    carga = "cargado" if estado["cargado"] else "se cargará cuando haga falta"
    donde = "GPU" if estado["gpu"] else "CPU"
    if estado["cargado"] and estado.get("capas_en_gpu") is not None and estado.get("capas_totales"):
        donde = f"{estado['capas_en_gpu']} de {estado['capas_totales']} capas en la GPU"
        if estado.get("vram_llm_mib"):
            donde += f", {estado['vram_llm_mib']} MiB"
    limite = f", límite {estado['vram_max_mib']} MiB" if estado.get("vram_max_mib") else ""
    return f"LLM activo ({estado['modelo']}, {donde}{limite}, {carga})." + gpu


def ejecutar_comando(agente, texto: str, quien: str = "consola") -> str | None:
    """Respuesta del comando, o None si `texto` no es un comando (es una orden)."""
    partes = texto.strip().lower().split()
    if not partes:
        return None
    if partes == ["ayuda"]:
        return AYUDA
    if partes[0] == "llm" and len(partes) <= 2 and (len(partes) == 1 or partes[1] in ("on", "off")):
        if len(partes) == 2:
            agente.activar_llm(partes[1] == "on")
            registrar_actividad(quien, f"LLM {'activado' if partes[1] == 'on' else 'desactivado'}.")
        return describir_llm(agente.estado_llm())
    if partes[0] == "seguro" and len(partes) <= 2 and (len(partes) == 1 or partes[1] in ("on", "off")):
        if len(partes) == 2:
            activar_modo_seguro(partes[1] == "on")
        return ("Modo seguro ACTIVADO: se confirma todo lo que no sea de lectura." if modo_seguro()
                else "Modo seguro desactivado: se confirma según POLITICA_RIESGO (config.py).")
    if partes == ["actividad"]:
        lineas = ultima_actividad(15)
        return "\n".join(lineas) if lineas else "El registro de actividad está vacío."
    if partes == ["reanudar"]:
        if not control.en_pausa():
            return "El agente no está en pausa."
        control.reanudar()
        registrar_actividad(quien, "Agente reanudado.")
        return "▶ Agente reanudado."
    return None


def _nombre_tecla(tecla) -> str | None:
    """Nombre normalizado de una tecla de pynput: 'ctrl', 'alt', 'shift', 'win', 'p', 'f12'..."""
    nombre = getattr(tecla, "name", None)            # teclas especiales (Key.ctrl_l, Key.f12...)
    if nombre:
        for base in ("ctrl", "alt", "shift"):
            if nombre.startswith(base):
                return base
        return "win" if nombre.startswith("cmd") else nombre
    vk = getattr(tecla, "vk", None)                  # letras y números: por su código, no por el
    if vk is not None and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):   # carácter (con Ctrl
        return chr(vk).lower()                       # pulsado, el carácter cambia)
    char = getattr(tecla, "char", None)
    return char.lower() if char else None


def atajo_legible(atajo: str | None = None) -> str:
    """'<ctrl>+<alt>+p' -> 'Ctrl+Alt+P'"""
    from config import ATAJO_PANICO
    return "+".join(p.strip("<> ").capitalize() for p in (atajo or ATAJO_PANICO).split("+"))


def teclas_del_atajo(atajo: str) -> frozenset[str]:
    """'<ctrl>+<alt>+p' -> {'ctrl', 'alt', 'p'}"""
    return frozenset(parte.strip("<> ").lower() for parte in atajo.split("+") if parte.strip())


def iniciar_atajo_panico(al_pulsar, atajo: str | None = None) -> object | None:
    """
    Escucha la combinación ATAJO_PANICO (config.py) en CUALQUIER ventana y llama
    a `al_pulsar()`. Devuelve el escuchador (o None si pynput no está).

    No se usa GlobalHotKeys de pynput: ignora las pulsaciones generadas por
    programa y así no se puede probar; aquí se sigue qué teclas están
    pulsadas por su código.
    """
    try:
        from pynput import keyboard
    except ImportError:
        return None
    from config import ATAJO_PANICO
    necesarias = teclas_del_atajo(atajo or ATAJO_PANICO)
    pulsadas: set[str] = set()
    disparado = [False]

    def al_bajar(tecla, *_):
        nombre = _nombre_tecla(tecla)
        if nombre:
            pulsadas.add(nombre)
        if necesarias <= pulsadas and not disparado[0]:
            disparado[0] = True   # una vez por pulsación
            al_pulsar()

    def al_soltar(tecla, *_):
        pulsadas.discard(_nombre_tecla(tecla))
        if not necesarias <= pulsadas:
            disparado[0] = False

    escuchador = keyboard.Listener(on_press=al_bajar, on_release=al_soltar)
    escuchador.daemon = True
    escuchador.start()
    return escuchador


def pausar_por_panico(quien: str, como: str) -> None:
    """Lo que hace el botón (o el atajo) de pánico."""
    control.detener()
    registrar_actividad(quien, f"■ PARADO con {como}: se corta lo que estuviera haciendo y queda en pausa.")
