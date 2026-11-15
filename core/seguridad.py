"""
Seguridad y control del agente.

1. Niveles de riesgo: cada skill declara `riesgo` ("lectura", "bajo", "medio",
   "alto") y POLITICA_RIESGO (config.py) dice cuándo se pide confirmación:
   "nunca", "si_llm" (solo si la orden la interpretó el LLM) o "siempre".
   Con el MODO SEGURO todo lo que no sea de lectura se confirma siempre.
2. Ventanas prohibidas (VENTANAS_PROHIBIDAS): el teclado y las plantillas
   grabadas no actúan sobre ellas (contraseñas, banca, terminales...).
3. Registro de actividad (data/actividad.log): una línea legible por cada
   acción, quién la pidió y cómo acabó; también las pausas y los bloqueos.
4. Avisos de lo que está haciendo: el executor avisa antes de cada paso a
   quien esté escuchando (la interfaz lo muestra en un recuadro siempre
   encima).
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from config import MODO_SEGURO, POLITICA_RIESGO, RUTA_ACTIVIDAD, VENTANAS_PROHIBIDAS
from core.estado import normalizar

NIVELES = ("lectura", "bajo", "medio", "alto")
TAMANO_MAX_ACTIVIDAD = 5 * 2**20   # al pasar de 5 MB se archiva como actividad.log.1

_modo_seguro = MODO_SEGURO
_lock = threading.Lock()
_oyentes: list[Callable[[str | None], None]] = []


# --- 1. Niveles de riesgo y modo seguro --------------------------------------------

def modo_seguro() -> bool:
    return _modo_seguro


def activar_modo_seguro(activo: bool) -> None:
    global _modo_seguro
    _modo_seguro = activo
    registrar_actividad("sistema", f"Modo seguro {'activado' if activo else 'desactivado'}.")


def necesita_confirmacion(skill, origen: str | None) -> bool:
    """¿Hay que confirmar esta skill antes de ejecutarla?"""
    riesgo = getattr(skill, "riesgo", "bajo")
    if getattr(skill, "requiere_confirmacion", False):   # irreversible: siempre
        return True
    if riesgo == "lectura":
        return False
    if _modo_seguro:
        return True
    politica = POLITICA_RIESGO.get(riesgo, "siempre")
    if politica == "siempre":
        return True
    if politica == "si_llm":
        return origen == "llm"
    # "nunca": salvo que la propia skill pida confirmar lo que deduzca el LLM.
    return origen == "llm" and getattr(skill, "confirmar_si_llm", False)


# --- 2. Ventanas prohibidas -------------------------------------------------------

def ventana_prohibida(ventana: dict | None) -> str | None:
    """Motivo por el que no se puede actuar sobre esta ventana, o None."""
    if not ventana:
        return None
    titulo = normalizar(ventana.get("titulo", ""))
    proceso = normalizar(ventana.get("proceso") or "")
    for patron in VENTANAS_PROHIBIDAS:
        p = normalizar(patron)
        if p and (p in titulo or p == proceso or (p.endswith(".exe") and p == proceso)):
            return (f"'{ventana.get('titulo') or proceso}' está en la lista de ventanas prohibidas "
                    f"('{patron}', VENTANAS_PROHIBIDAS en config.py): no escribo ni hago clic en ella.")
    return None


# --- 3. Registro de actividad -------------------------------------------------------

def registrar_actividad(quien: str, texto: str, ok: bool | None = None, ruta: Path | None = None) -> None:
    """Una línea: '2026-11-15 10:23:01 | interfaz | ✔ abrir_aplicacion(...) | 'Calculadora' abierta.'"""
    ruta = Path(ruta) if ruta else RUTA_ACTIVIDAD
    marca = "" if ok is None else ("✔ " if ok else "✘ ")
    linea = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {quien:9} | {marca}{' '.join(texto.split())}\n"
    with _lock:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if ruta.exists() and ruta.stat().st_size > TAMANO_MAX_ACTIVIDAD:
            ruta.replace(ruta.with_name(ruta.name + ".1"))
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(linea)


def ultima_actividad(n: int = 15, ruta: Path | None = None) -> list[str]:
    ruta = Path(ruta) if ruta else RUTA_ACTIVIDAD
    if not ruta.exists():
        return []
    with _lock:
        return ruta.read_text(encoding="utf-8").splitlines()[-n:]


# --- 4. Avisos de lo que está haciendo ------------------------------------------------

def escuchar(oyente: Callable[[str | None], None]) -> None:
    """`oyente(texto)` recibe lo que va a hacer el agente; None cuando termina."""
    _oyentes.append(oyente)


def avisar(texto: str | None) -> None:
    for oyente in list(_oyentes):
        try:
            oyente(texto)
        except Exception:
            pass
