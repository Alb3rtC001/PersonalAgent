"""
Skills de Steam usando lo que Steam ofrece, sin clics:

- Los juegos instalados están descritos en archivos de texto (formato VDF):
  steamapps/libraryfolders.vdf (bibliotecas) y steamapps/appmanifest_<id>.acf
  (nombre, id, carpeta y estado de cada juego, incluidas las actualizaciones
  pendientes).
- Un juego se lanza con el enlace steam://rungameid/<id> (si Steam está
  cerrado, lo abre él solo).

ejecutar_en_steam sustituye a la plantilla grabada (clics por coordenadas),
que se rompía si la ventana de Steam cambiaba.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from config import ESPERA_MAX_JUEGO
from core import control
from core.estado import normalizar
from core.skills.base import Resultado, Skill

try:
    import psutil
except ImportError:
    psutil = None

log = logging.getLogger("personalagent")

# StateFlags de un appmanifest (bits)
ACTUALIZACION_PENDIENTE = 2
ACTUALIZANDO = 256 | 512 | 1024 | 1048576 | 2097152 | 4194304   # en curso, en pausa, descargando...
UMBRAL_PARECIDO = 0.6


# ---------------------------------------------------------------------------
# Lectura de los archivos de Steam
# ---------------------------------------------------------------------------

def leer_vdf(texto: str) -> dict:
    """Formato VDF de Valve: "clave" "valor" y "clave" { ... } anidados."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', texto)
    pila: list[dict] = [{}]
    clave = None
    for cadena, llave in tokens:
        if llave == "{":
            nuevo: dict = {}
            pila[-1][clave] = nuevo
            pila.append(nuevo)
            clave = None
        elif llave == "}":
            if len(pila) > 1:
                pila.pop()
        elif clave is None:
            clave = cadena.replace("\\\\", "\\")
        else:
            pila[-1][clave] = cadena.replace("\\\\", "\\")
            clave = None
    return pila[0]


def ruta_steam() -> Path | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as clave:
            ruta = Path(winreg.QueryValueEx(clave, "SteamPath")[0])
            return ruta if ruta.is_dir() else None
    except (OSError, ImportError):
        por_defecto = Path(r"C:\Program Files (x86)\Steam")
        return por_defecto if por_defecto.is_dir() else None


@dataclass(frozen=True)
class Juego:
    appid: str
    nombre: str
    carpeta: Path         # steamapps/common/<installdir>
    flags: int
    build: str
    build_objetivo: str
    bytes_pendientes: int

    @property
    def actualizacion_pendiente(self) -> bool:
        return bool(self.flags & (ACTUALIZACION_PENDIENTE | ACTUALIZANDO)
                    or (self.build_objetivo not in ("", "0") and self.build_objetivo != self.build)
                    or self.bytes_pendientes > 0)


def juegos_instalados(raiz: Path | None = None) -> list[Juego]:
    raiz = raiz or ruta_steam()
    if raiz is None:
        return []
    bibliotecas = [raiz]
    try:
        datos = leer_vdf((raiz / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace"))
        for info in datos.get("libraryfolders", {}).values():
            if isinstance(info, dict) and info.get("path"):
                bibliotecas.append(Path(info["path"]))
    except OSError:
        pass

    juegos: dict[str, Juego] = {}
    for biblioteca in dict.fromkeys(p.resolve() for p in bibliotecas):
        for manifiesto in (biblioteca / "steamapps").glob("appmanifest_*.acf"):
            try:
                app = leer_vdf(manifiesto.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
                a_bajar = int(app.get("BytesToDownload", 0) or 0) - int(app.get("BytesDownloaded", 0) or 0)
                juegos[app["appid"]] = Juego(
                    appid=app["appid"], nombre=app.get("name", app["appid"]),
                    carpeta=biblioteca / "steamapps" / "common" / app.get("installdir", ""),
                    flags=int(app.get("StateFlags", 0) or 0), build=app.get("buildid", ""),
                    build_objetivo=app.get("TargetBuildID", ""), bytes_pendientes=max(0, a_bajar),
                )
            except (OSError, KeyError, ValueError):
                continue
    # Steamworks Common Redistributables y similares no son juegos.
    return sorted((j for j in juegos.values() if "redistributable" not in j.nombre.lower()),
                  key=lambda j: j.nombre.lower())


# ---------------------------------------------------------------------------
# Buscar un juego por cómo lo nombra el usuario
# ---------------------------------------------------------------------------

def _siglas(nombre: str) -> str:
    """'Counter-Strike 2' -> 'cs2'; 'Baldur's Gate 3' -> 'bg3'."""
    palabras = re.findall(r"[a-z]+|\d+", normalizar(nombre))
    return "".join(p if p.isdigit() else p[0] for p in palabras)


def buscar_juego(consulta: str, juegos: list[Juego]) -> Juego | None:
    c = re.sub(r"[^a-z0-9 ]", " ", normalizar(consulta)).split()
    consulta_n = " ".join(c)
    if not consulta_n:
        return None
    mejor, puntos_mejor = None, 0.0
    for juego in juegos:
        nombre = " ".join(re.sub(r"[^a-z0-9 ]", " ", normalizar(juego.nombre)).split())
        if consulta_n == nombre:
            puntos = 1.0
        elif consulta_n.replace(" ", "") == _siglas(juego.nombre):
            puntos = 0.95
        elif nombre.startswith(consulta_n) or f" {consulta_n} " in f" {nombre} ":
            puntos = 0.9
        else:
            puntos = difflib.SequenceMatcher(None, consulta_n, nombre).ratio()
        if puntos > puntos_mejor:
            mejor, puntos_mejor = juego, puntos
    return mejor if puntos_mejor >= UMBRAL_PARECIDO else None


def _proceso_del_juego(juego: Juego) -> int | None:
    """PID de un proceso que se ejecuta desde la carpeta del juego, o None."""
    # Sin carpeta propia (installdir vacío) sería "common": valdría cualquier juego.
    if psutil is None or juego.carpeta.name.lower() == "common" or not juego.carpeta.is_dir():
        return None
    # Con el separador al final: "...\Slay the Spire\" no es el principio de
    # "...\Slay the Spire 2\juego.exe" (otro juego).
    carpeta = os.path.join(str(juego.carpeta.resolve()), "").lower()
    for p in psutil.process_iter(["pid", "exe"]):
        exe = (p.info.get("exe") or "").lower()
        if exe.startswith(carpeta):
            return p.info["pid"]
    return None


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

class EjecutarEnSteam(Skill):
    nombre = "ejecutar_en_steam"
    descripcion = ("Lanza un juego instalado en Steam (si Steam está cerrado, lo abre). "
                   "Admite el nombre del juego o sus siglas (cs2).")
    parametros = {"juego": "Nombre del juego tal como lo dice el usuario"}
    confirmar_si_llm = True   # lanzar un juego ocupa el PC: si lo dedujo el LLM, se pregunta
    riesgo = "medio"
    coste = 2

    def __init__(self, espera_max: float = ESPERA_MAX_JUEGO):
        self.espera_max = espera_max

    def ejecutar(self, juego: str = "") -> Resultado:
        instalados = juegos_instalados()
        if not instalados:
            return Resultado(False, "No encuentro Steam ni ningún juego instalado.")
        encontrado = buscar_juego(juego, instalados)
        if encontrado is None:
            return Resultado(False, f"No tengo ningún juego instalado que se llame '{juego}'.")
        datos = {"appid": encontrado.appid, "nombre": encontrado.nombre, "carpeta": str(encontrado.carpeta)}
        if _proceso_del_juego(encontrado):
            return Resultado(True, f"'{encontrado.nombre}' ya está en marcha.", datos={**datos, "ya_abierto": True})
        if encontrado.actualizacion_pendiente:
            log.info("'%s' tiene una actualización pendiente: Steam la hará antes de abrirlo.", encontrado.nombre)
        log.info("Lanzando '%s' desde Steam…", encontrado.nombre)
        os.startfile(f"steam://rungameid/{encontrado.appid}")
        return Resultado(True, f"Lanzando '{encontrado.nombre}'.", datos=datos)

    def verificar(self, resultado: Resultado) -> bool:
        datos = resultado.datos
        if not resultado.ok or datos.get("ya_abierto"):
            return resultado.ok
        juego = next((j for j in juegos_instalados() if j.appid == datos["appid"]), None)
        if juego is None:
            return False
        log.info("Esperando a que arranque '%s' (máximo %d s)…", juego.nombre, self.espera_max)
        limite = time.monotonic() + self.espera_max
        while time.monotonic() < limite:
            if _proceso_del_juego(juego):
                return True
            control.comprobar()   # botón de pánico
            time.sleep(1.0)
        datos["motivo_verificacion"] = (
            f"Steam recibió la orden, pero '{juego.nombre}' no ha arrancado en {self.espera_max} s "
            "(puede estar actualizándose o pidiendo algo en la ventana de Steam).")
        return False


class ActualizacionesSteam(Skill):
    nombre = "actualizaciones_steam"
    descripcion = ("Dice qué juegos de Steam tienen actualizaciones pendientes (lo lee de los "
                   "archivos de Steam, no hace falta abrirlo).")
    parametros = {}
    riesgo = "lectura"
    coste = 1

    def ejecutar(self) -> Resultado:
        instalados = juegos_instalados()
        if not instalados:
            return Resultado(False, "No encuentro Steam ni ningún juego instalado.")
        pendientes = [j for j in instalados if j.actualizacion_pendiente]
        datos = {"instalados": len(instalados), "pendientes": [j.nombre for j in pendientes]}
        if not pendientes:
            return Resultado(True, f"Ningún juego tiene actualizaciones pendientes ({len(instalados)} instalados).",
                             datos=datos)
        return Resultado(True, f"{len(pendientes)} de {len(instalados)} juegos con actualización pendiente: "
                               + ", ".join(j.nombre for j in pendientes) + ".", datos=datos)
