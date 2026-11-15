"""
Grabadora semántica (fase 5): graba QUÉ haces, no DÓNDE.

- Un clic se guarda como el CONTROL pulsado (identificador, nombre y tipo,
  leídos con UI Automation) y su ventana, no como coordenadas. Así la
  grabación sigue funcionando aunque la ventana se mueva o cambie de tamaño.
- Lo que escribes se guarda como texto, junto con el campo que tenía el foco
  (al reproducir se pone el foco en ese campo antes de escribir).
- Las combinaciones y teclas especiales (control s, enter, tab...) se guardan
  con los nombres que entiende pulsar_teclas.
- Nunca se graba lo escrito en un campo de contraseña (se anota que se omitió),
  ni nada en las ventanas prohibidas (VENTANAS_PROHIBIDAS) o en la propia
  consola o interfaz del agente.
- F9 termina la grabación.

Los eventos llegan del ratón y el teclado (pynput) y se procesan en un hilo
aparte, porque consultar UI Automation dentro del gancho del teclado lo
ralentizaría.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from core import uia
from core.seguridad import registrar_actividad, ventana_prohibida

log = logging.getLogger("personalagent")

TECLA_FIN = "f9"
MODIFICADORES = {"ctrl": "control", "alt": "alt", "shift": "shift", "cmd": "win"}
ESPECIALES = {
    "enter": "enter", "tab": "tab", "esc": "escape", "delete": "suprimir", "up": "arriba",
    "down": "abajo", "left": "izquierda", "right": "derecha", "home": "inicio", "end": "fin",
    "page_up": "repag", "page_down": "avpag", "insert": "insertar",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}


def _base_modificador(nombre: str) -> str | None:
    for base, nuestro in MODIFICADORES.items():
        if nombre.startswith(base) or (base == "alt" and nombre == "alt_gr"):
            return nuestro
    return None


class GrabadoraSemantica:
    def __init__(self, pids_ignorados: set[int] | None = None):
        from core.skills.cerrar_aplicacion import _pids_propios
        self.ignorar = set(pids_ignorados or set()) | _pids_propios()
        self.pasos: list[dict[str, Any]] = []
        self.avisos: list[str] = []
        self._cola: queue.Queue = queue.Queue()
        self._modificadores: set[str] = set()
        self._texto: list[str] = []
        self._fin = threading.Event()
        self._escuchas = []
        self._hilo: threading.Thread | None = None

    # --- Arranque y fin -------------------------------------------------------------

    def iniciar(self) -> None:
        from pynput import keyboard, mouse
        self._hilo = threading.Thread(target=self._procesar, daemon=True, name="grabadora")
        self._hilo.start()
        self._escuchas = [mouse.Listener(on_click=self._al_clic),
                          keyboard.Listener(on_press=self._al_bajar, on_release=self._al_soltar)]
        for escucha in self._escuchas:
            escucha.daemon = True
            escucha.start()
        registrar_actividad("grabadora", "● Grabación iniciada (F9 para terminar).")

    def esperar_fin(self, tiempo_max: float | None = None) -> bool:
        return self._fin.wait(tiempo_max)

    def detener(self) -> list[dict[str, Any]]:
        for escucha in self._escuchas:
            escucha.stop()
        self._cola.put(("fin_texto",))
        self._cola.put(None)
        if self._hilo:
            self._hilo.join(timeout=5)
        self._fin.set()
        registrar_actividad("grabadora", f"■ Grabación terminada: {len(self.pasos)} paso(s).")
        return self.pasos

    # --- Eventos (hilos de pynput: solo encolar, rápido) -------------------------------

    def _al_clic(self, x, y, boton, pulsado, *_):
        if pulsado:
            self._cola.put(("clic", int(x), int(y), str(boton).split(".")[-1], time.time()))

    def _al_bajar(self, tecla, *_):
        nombre = getattr(tecla, "name", None)
        if nombre == TECLA_FIN:
            self._fin.set()
            return
        base = _base_modificador(nombre) if nombre else None
        if base:
            self._modificadores.add(base)
            return
        char = getattr(tecla, "char", None)
        con_atajo = self._modificadores & {"control", "win"} and not (
            {"control", "alt"} <= self._modificadores)            # Ctrl+Alt = AltGr: escribe @, #, €...
        if nombre == "space" and not con_atajo:
            self._cola.put(("texto", " "))
        elif char and char.isprintable() and not con_atajo:
            self._cola.put(("texto", char))
        elif nombre == "backspace" and not self._modificadores:
            self._cola.put(("borrar",))
        else:
            letra = ESPECIALES.get(nombre or "") or (nombre if nombre else None)
            vk = getattr(tecla, "vk", None)
            if not letra and vk is not None and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
                letra = chr(vk).lower()
            if letra:
                mods = [m for m in ("control", "alt", "shift", "win") if m in self._modificadores]
                self._cola.put(("teclas", " ".join(mods + [letra])))

    def _al_soltar(self, tecla, *_):
        nombre = getattr(tecla, "name", None)
        base = _base_modificador(nombre) if nombre else None
        if base:
            self._modificadores.discard(base)

    # --- Procesado (hilo propio, con UI Automation) --------------------------------------

    def _procesar(self) -> None:
        with uia.en_hilo():
            while True:
                evento = self._cola.get()
                if evento is None:
                    break
                try:
                    self._tratar(evento)
                except Exception:
                    log.exception("Grabadora: error procesando %s", evento[0])

    def _tratar(self, evento) -> None:
        tipo = evento[0]
        if tipo == "texto":
            if not self._escribiendo:   # primera letra de un texto: ¿en qué campo?
                self._escribiendo = True
                self._empezar_texto()
            if self._texto_destino is not None:
                self._texto.append(evento[1])
            return
        if tipo == "borrar":
            if self._texto:
                self._texto.pop()
            elif not self._escribiendo:
                self._anadir_teclas("retroceso")
            return
        self._cerrar_texto()
        if tipo == "clic":
            _, x, y, boton, _ = evento
            resultado = uia.control_en(x, y)
            if resultado is None:
                return
            control, ventana = resultado
            if self._ignorada(ventana):
                return
            r = ventana.get("rect") or [0, 0, 1, 1]
            ancho, alto = max(1, r[2] - r[0]), max(1, r[3] - r[1])
            self.pasos.append({"tipo": "clic", "boton": boton, "control": control,
                               "ventana": self._ventana_resumen(ventana),
                               "relativo": [round((x - r[0]) / ancho, 4), round((y - r[1]) / alto, 4)]})
            log.info("● Grabado: clic en %s '%s'", control["tipo"].replace("Control", "").lower(),
                     control["nombre"] or control["id"] or "?")
        elif tipo == "teclas":
            self._anadir_teclas(evento[1])

    def _empezar_texto(self) -> None:
        """Al empezar a escribir: qué campo tiene el foco (y si es de contraseña)."""
        self._texto_destino = None
        resultado = uia.control_con_foco()
        if resultado is None:
            return
        control, ventana = resultado
        if self._ignorada(ventana):
            return
        if control.get("contrasena"):
            self.pasos.append({"tipo": "contrasena_omitida", "ventana": self._ventana_resumen(ventana)})
            self.avisos.append("Había un campo de contraseña: no se ha grabado lo que escribiste en él.")
            log.info("● Campo de contraseña: no se graba lo que escribas.")
            return
        self._texto_destino = (control, ventana)

    _texto_destino: tuple[dict, dict] | None = None
    _escribiendo: bool = False

    def _cerrar_texto(self) -> None:
        if self._texto and self._texto_destino is not None:
            control, ventana = self._texto_destino
            texto = "".join(self._texto)
            self.pasos.append({"tipo": "escribir", "texto": texto, "control": control,
                               "ventana": self._ventana_resumen(ventana)})
            log.info("● Grabado: escribir '%s'", texto)
        self._texto = []
        self._texto_destino = None
        self._escribiendo = False

    def _anadir_teclas(self, teclas: str) -> None:
        resultado = uia.control_con_foco()
        ventana = resultado[1] if resultado else None
        if ventana is not None and self._ignorada(ventana):
            return
        self.pasos.append({"tipo": "teclas", "teclas": teclas,
                           "ventana": self._ventana_resumen(ventana) if ventana else None})
        log.info("● Grabado: teclas '%s'", teclas)

    def _ignorada(self, ventana: dict) -> bool:
        if ventana.get("pid") in self.ignorar:
            return True   # la consola o la interfaz del propio agente
        motivo = ventana_prohibida(ventana)
        if motivo:
            aviso = f"No se graba en '{ventana.get('titulo')}': ventana prohibida."
            if aviso not in self.avisos:
                self.avisos.append(aviso)
                registrar_actividad("grabadora", aviso, False)
            return True
        return False

    @staticmethod
    def _ventana_resumen(ventana: dict) -> dict:
        return {"titulo": ventana.get("titulo", ""), "proceso": ventana.get("proceso")}


def textos_grabados(pasos: list[dict]) -> list[tuple[int, str]]:
    """(índice, texto) de los pasos de escribir: candidatos a ser el parámetro."""
    return [(i, p["texto"]) for i, p in enumerate(pasos) if p["tipo"] == "escribir"]


def marcar_parametro(pasos: list[dict], indice: int, nombre: str) -> list[dict]:
    """Convierte el texto del paso `indice` en el parámetro {nombre} (lo que cambia cada vez)."""
    pasos = [dict(p) for p in pasos]
    pasos[indice]["ejemplo"] = pasos[indice]["texto"]
    pasos[indice]["texto"] = "{" + nombre + "}"
    return pasos
