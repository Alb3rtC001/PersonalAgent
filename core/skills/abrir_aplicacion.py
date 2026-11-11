"""
Skill nativa: abrir una aplicación.

En vez de pulsar Win, escribir y Enter, usa el mismo índice que el menú
Inicio de Windows (Get-StartApps): incluye programas clásicos, apps de
la Microsoft Store (Calculadora, Notas rápidas...) y accesos directos
de juegos. Cada entrada tiene un AppID que se lanza con
    explorer.exe shell:AppsFolder\\<AppID>

Verificación: espera a que aparezca una ventana cuyo título o proceso
contenga el nombre de la app, o una ventana nueva que no existía antes.
"""

from __future__ import annotations

import difflib
import json
import subprocess
import time
from dataclasses import dataclass

from config import ALIAS_APLICACIONES, ESPERA_MAX_APERTURA
from core.estado import buscar_ventana, handles_ventanas, normalizar
from core.skills.base import Resultado, Skill

# Puntuación mínima para aceptar una app. Los parecidos "difusos" puntúan
# ratio * 0.75, así que 0.45 equivale a exigir un ratio de difflib >= 0.6.
UMBRAL_PUNTOS = 0.45


@dataclass(frozen=True)
class AppInstalada:
    nombre: str
    app_id: str


def listar_apps_instaladas() -> list[AppInstalada]:
    """Apps del menú Inicio (nombre visible + AppID)."""
    salida = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
         "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    datos = json.loads(salida.stdout or "[]")
    if isinstance(datos, dict):
        datos = [datos]
    return [AppInstalada(d["Name"], d["AppID"]) for d in datos if d.get("Name") and d.get("AppID")]


def _puntuar(consulta: str, nombre: str) -> float:
    if nombre == consulta:
        return 1.0
    if nombre.startswith(consulta):
        return 0.9
    if consulta in nombre.split():
        return 0.85
    if all(p in nombre.split() for p in consulta.split()):
        return 0.8
    return difflib.SequenceMatcher(None, consulta, nombre).ratio() * 0.75


def buscar_app(consulta: str, apps: list[AppInstalada]) -> list[tuple[float, AppInstalada]]:
    """Apps ordenadas de más a menos parecida a la consulta (solo las que superan el umbral)."""
    consulta = normalizar(consulta)
    consulta = normalizar(ALIAS_APLICACIONES.get(consulta, consulta))
    candidatas = []
    for app in apps:
        nombre = normalizar(app.nombre)
        puntos = _puntuar(consulta, nombre)
        if app.app_id.startswith("http") and puntos < 1.0:
            puntos -= 0.2  # enlaces web del menú Inicio ("Steam Support Center"...)
        if puntos >= UMBRAL_PUNTOS:
            candidatas.append((puntos, app))
    # Más puntos primero; a igualdad, el nombre más corto ("Steam" antes que "Steam VR").
    candidatas.sort(key=lambda c: (-c[0], len(c[1].nombre)))
    return candidatas


class AbrirAplicacion(Skill):
    nombre = "abrir_aplicacion"
    descripcion = "Abre una aplicación instalada (o la trae al frente si ya está abierta)."
    parametros = {"aplicacion": "Nombre de la aplicación, p. ej. 'Discord' o 'calculadora'"}
    coste = 3
    EFECTOS = {"abierta:{aplicacion}": True, "visible:{aplicacion}": True}

    def __init__(self, espera_max: float = ESPERA_MAX_APERTURA):
        self.espera_max = espera_max
        self._apps: list[AppInstalada] | None = None

    def _indice(self, refrescar: bool = False) -> list[AppInstalada]:
        if self._apps is None or refrescar:
            self._apps = listar_apps_instaladas()
        return self._apps

    def ejecutar(self, aplicacion: str = "") -> Resultado:
        candidatas = buscar_app(aplicacion, self._indice())
        if not candidatas:
            # Puede ser una app recién instalada: se reintenta con el índice actualizado.
            candidatas = buscar_app(aplicacion, self._indice(refrescar=True))
        if not candidatas:
            return Resultado(False, f"No encuentro ninguna aplicación llamada '{aplicacion}'.")

        app = candidatas[0][1]
        antes = handles_ventanas()
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app.app_id}"])
        return Resultado(
            True,
            f"Abriendo '{app.nombre}'.",
            datos={"aplicacion": app.nombre, "app_id": app.app_id,
                   "pedida": aplicacion, "ventanas_antes": sorted(antes)},
        )

    def verificar(self, resultado: Resultado) -> bool:
        if not resultado.ok:
            return False
        nombres = {resultado.datos["aplicacion"], resultado.datos["pedida"]}
        antes = set(resultado.datos["ventanas_antes"])
        limite = time.monotonic() + self.espera_max
        while time.monotonic() < limite:
            if any(buscar_ventana(n) for n in nombres):
                return True
            if handles_ventanas() - antes:
                return True
            time.sleep(0.5)
        return False
