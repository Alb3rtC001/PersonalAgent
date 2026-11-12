"""
Skill nativa: cerrar una aplicación.

1. Busca las ventanas de la app (también las escondidas en la bandeja del
   sistema). Para no cerrar lo que no toca, la coincidencia es estricta:
   el título es exactamente el nombre de la app, acaba en " - <app>"
   (p. ej. "README.md - Visual Studio Code") o el proceso se llama como
   la app (Discord.exe). Una pestaña de Chrome que hable de Discord no
   cuenta: su título acaba en " - Google Chrome".
2. Les pide que se cierren como si se pulsara la X (WM_CLOSE). La app
   decide: se cierra, pregunta si guardar cambios o se esconde en la bandeja.
3. Si queda alguna ventana visible (p. ej. "¿Guardar cambios?") NO fuerza
   nada: avisa y deja que decidas tú.
4. Si la app solo se ha escondido en la bandeja (Discord, Steam...) y
   CERRAR_TERMINA_BANDEJA está activo, termina su proceso para cerrarla
   del todo.

Nunca cierra el proceso desde el que se está ejecutando el agente (la
terminal, VS Code...) ni procesos de Windows compartidos (explorer.exe,
ApplicationFrameHost.exe, que aloja todas las apps de la Microsoft Store).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from config import ALIAS_APLICACIONES, CERRAR_TERMINA_BANDEJA, ESPERA_MAX_CIERRE
from core.estado import (
    listar_ventanas_abiertas,
    normalizar,
    pedir_cierre,
    ventana_existe,
    ventana_mostrada,
)
from core.skills.abrir_aplicacion import AppInstalada, buscar_app, listar_apps_instaladas
from core.skills.base import Resultado, Skill

try:
    import psutil
except ImportError:  # sin psutil no se puede terminar procesos (solo pedir el cierre)
    psutil = None

log = logging.getLogger("personalagent")

# Segundos que una app tiene que llevar con todas sus ventanas ocultas para
# considerar que se ha escondido en la bandeja (y no que se está cerrando).
GRACIA_OCULTA = 2.0

# Procesos de Windows que nunca se terminan: son compartidos o del sistema.
PROCESOS_PROTEGIDOS = {
    "explorer.exe", "applicationframehost.exe", "dwm.exe", "svchost.exe",
    "csrss.exe", "winlogon.exe", "services.exe", "lsass.exe", "sihost.exe",
    "textinputhost.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "runtimebroker.exe", "taskhostw.exe",
}
SEPARADORES_TITULO = (" - ", " — ", " | ")


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


def _pids_propios() -> set[int]:
    """PID del agente y de sus padres (terminal, VS Code...): nunca se cierran."""
    pids = {os.getpid()}
    if psutil is not None:
        try:
            pids |= {p.pid for p in psutil.Process().parents()}
        except psutil.Error:
            pass
    return pids


def _protegido(proceso: str | None) -> bool:
    return (proceso or "").lower() in PROCESOS_PROTEGIDOS


def _raiz_de_app(pid: int, propios: set[int]):
    """
    Proceso principal de la app a partir del que tiene la ventana. Ej.: la
    ventana de Steam es de steamwebhelper.exe, hijo de steam.exe; si solo
    se terminara el primero, Steam lo volvería a lanzar. Se sube por los
    padres mientras estén instalados en la misma carpeta (o una superior).
    """
    raiz = psutil.Process(pid)
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
    while True:
        try:
            padre = raiz.parent()
            if padre is None or padre.pid in propios or _protegido(padre.name()):
                break
            dir_padre = Path(padre.exe()).parent.resolve()
            if dir_padre.is_relative_to(windows) or not Path(raiz.exe()).resolve().is_relative_to(dir_padre):
                break
            raiz = padre
        except psutil.Error:
            break
    return raiz


def _terminar_procesos(pids: set[int], propios: set[int]) -> list[str]:
    """Termina las apps (proceso principal + hijos). Devuelve los nombres terminados."""
    if psutil is None:
        return []
    procesos: dict[int, "psutil.Process"] = {}
    for pid in pids:
        try:
            raiz = _raiz_de_app(pid, propios)
            for p in [raiz, *raiz.children(recursive=True)]:
                if p.pid not in propios and not _protegido(p.name()):
                    procesos[p.pid] = p
        except psutil.Error:
            continue
    nombres = sorted({p.name() for p in procesos.values() if p.is_running()})
    for p in procesos.values():
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, vivos = psutil.wait_procs(list(procesos.values()), timeout=5)
    for p in vivos:
        try:
            p.kill()
        except psutil.Error:
            pass
    return nombres


class CerrarAplicacion(Skill):
    nombre = "cerrar_aplicacion"
    descripcion = ("Cierra una aplicación abierta (como pulsar su X). Si solo se esconde en la "
                   "bandeja del sistema, termina su proceso. Nunca fuerza el cierre si la app "
                   "pregunta algo, como guardar cambios.")
    parametros = {"aplicacion": "Nombre de la aplicación, p. ej. 'Discord' o 'calculadora'"}
    coste = 2
    EFECTOS = {"abierta:{aplicacion}": False, "visible:{aplicacion}": False}

    def __init__(self, espera_max: float = ESPERA_MAX_CIERRE,
                 terminar_en_bandeja: bool = CERRAR_TERMINA_BANDEJA):
        self.espera_max = espera_max
        self.terminar_en_bandeja = terminar_en_bandeja
        self._apps: list[AppInstalada] | None = None

    def _nombres(self, aplicacion: str) -> list[str]:
        """Lo que ha dicho el usuario, su alias y el nombre de la app en el menú Inicio."""
        nombres = {aplicacion, ALIAS_APLICACIONES.get(normalizar(aplicacion), aplicacion)}
        try:
            if self._apps is None:
                self._apps = listar_apps_instaladas()
            candidatas = buscar_app(aplicacion, self._apps)
            if candidatas:
                nombres.add(candidatas[0][1].nombre)
        except Exception:  # sin índice del menú Inicio se busca solo por lo dicho
            pass
        return sorted(n for n in nombres if n.strip())

    def _ventanas(self, nombres: list[str]) -> list[dict]:
        return [v for v in listar_ventanas_abiertas(incluir_ocultas=True) if ventana_de_app(v, nombres)]

    def _esperar_cierre(self, hwnds: list[int]) -> None:
        """Espera a que las ventanas desaparezcan o lleven un rato todas ocultas (bandeja)."""
        limite = time.monotonic() + self.espera_max
        ocultas_desde: float | None = None
        while time.monotonic() < limite:
            existentes = [h for h in hwnds if ventana_existe(h)]
            if not existentes:
                return
            if any(ventana_mostrada(h) for h in existentes):
                ocultas_desde = None
            else:
                ocultas_desde = ocultas_desde or time.monotonic()
                if time.monotonic() - ocultas_desde >= GRACIA_OCULTA:
                    return
            time.sleep(0.3)

    def ejecutar(self, aplicacion: str = "") -> Resultado:
        nombres = self._nombres(aplicacion)
        propios = _pids_propios()
        ventanas = self._ventanas(nombres)
        datos = {"aplicacion": aplicacion, "nombres": nombres}

        if not ventanas:
            return Resultado(True, f"'{aplicacion}' no estaba abierta.", datos={**datos, "no_estaba": True})

        mias = [v for v in ventanas if v["pid"] in propios]
        ventanas = [v for v in ventanas if v["pid"] not in propios]
        if not ventanas:
            return Resultado(False, f"No cierro '{mias[0]['titulo']}': es desde donde me estoy ejecutando.")

        log.info("Cerrando %d ventana(s) de '%s'…", len(ventanas), aplicacion)
        hwnds = [v["hwnd"] for v in ventanas]
        for h in hwnds:
            pedir_cierre(h)
        self._esperar_cierre(hwnds)

        # Lo que queda: ventanas iniciales que siguen existiendo + ventanas de la
        # app que hayan aparecido mientras (un "¿Guardar cambios?" con su nombre).
        info = {v["hwnd"]: v for v in ventanas}
        info.update({v["hwnd"]: v for v in self._ventanas(nombres) if v["pid"] not in propios})
        restantes = {h for h in info if ventana_existe(h)}
        visibles = [h for h in restantes if ventana_mostrada(h)]
        datos["hwnds"] = hwnds

        if visibles:
            return Resultado(False, f"'{aplicacion}' sigue abierta: puede que esté preguntando algo "
                                    "(por ejemplo, si guardar cambios). No fuerzo el cierre.",
                             datos=datos)
        if not restantes:
            return Resultado(True, f"'{aplicacion}' cerrada.", datos=datos)

        # Solo quedan ventanas ocultas: la app se ha escondido en la bandeja.
        pids = {info[h]["pid"] for h in restantes
                if info[h]["pid"] and not _protegido(info[h]["proceso"])}
        if not pids:
            # Solo quedan ventanas ocultas de procesos compartidos de Windows
            # (p. ej. el marco de una app de la Store a medio cerrar): está cerrada.
            return Resultado(True, f"'{aplicacion}' cerrada.", datos=datos)
        if not self.terminar_en_bandeja or psutil is None:
            return Resultado(True, f"'{aplicacion}' se ha escondido en la bandeja del sistema "
                                   "(sigue en marcha).", datos={**datos, "en_bandeja": True})

        log.info("'%s' se ha escondido en la bandeja; termino su proceso…", aplicacion)
        terminados = _terminar_procesos(pids, propios)
        datos["procesos_terminados"] = terminados
        return Resultado(True, f"'{aplicacion}' se escondía en la bandeja; he terminado su proceso "
                               f"({', '.join(terminados) or 'ninguno'}).", datos=datos)

    def verificar(self, resultado: Resultado) -> bool:
        datos = resultado.datos
        if not resultado.ok:
            return False
        if datos.get("no_estaba") or datos.get("en_bandeja"):
            return True
        limite = time.monotonic() + 5
        while time.monotonic() < limite:
            quedan = any(ventana_mostrada(h) for h in datos["hwnds"]) or any(
                ventana_mostrada(v["hwnd"]) or not _protegido(v["proceso"])
                for v in self._ventanas(datos["nombres"])
            )
            if not quedan:
                return True
            time.sleep(0.3)
        datos["motivo_verificacion"] = f"Pedí cerrar '{datos['aplicacion']}' pero sus ventanas siguen ahí."
        return False
