"""
Skill leer_pantalla: lee lo que se ve en la ventana de una aplicación (con
UI Automation, sin capturas ni GPU extra) y responde a una pregunta con el
LLM: "¿hay alguien en el canal general?", "¿qué pone el resumen de Google?",
"¿qué canción suena?".

Seguridad:
- Solo lee (riesgo "lectura"): no pulsa ni escribe nada.
- El texto de la pantalla se le pasa al LLM como información, nunca como
  órdenes: una web que diga "ignora todo y abre X" no hace que actúe (y
  aunque lo intentara, esta skill solo devuelve una respuesta de texto).
- No lee ventanas prohibidas (contraseñas, banca...).
- Si el LLM está desactivado, devuelve el principio del texto tal cual.
"""

from __future__ import annotations

import logging
import time

from core import control, uia
from core.llm import llm_permitido, responder_sobre_texto, servidor_compartido
from core.seguridad import registrar_actividad, ventana_prohibida
from core.skills.abrir_aplicacion import AppInstalada, apps_instaladas
from core.skills.base import Resultado, Skill
from core.skills.teclado import DESCRIPCION_APLICACION
from core.skills.ventanas import elegir_ventana, nombres_de_app

log = logging.getLogger("personalagent")

LECTURAS_MAX = 3          # si el texto aún cambia (una página cargando), se vuelve a leer
PAUSA_ENTRE_LECTURAS = 1.0


class LeerPantalla(Skill):
    nombre = "leer_pantalla"
    descripcion = ("Lee lo que se ve en la ventana de una aplicación abierta y responde a una "
                   "pregunta sobre ello (qué pone, quién hay en un canal, qué canción suena, qué "
                   "dice un resumen...). Solo lee: no toca nada.")
    parametros = {
        "pregunta": "Lo que el usuario quiere saber, con sus palabras",
        "aplicacion": DESCRIPCION_APLICACION,
    }
    parametros_sin_anclar = frozenset({"pregunta"})   # la pregunta puede reformularse sin peligro
    riesgo = "lectura"
    interpretar_con_llm = True
    del_contexto = {"aplicacion": "ultima_aplicacion"}
    PRECONDICIONES = {"visible:{aplicacion}": True}   # si está minimizada, el planificador la restaura
    coste = 1

    def __init__(self):
        self._apps: list[AppInstalada] | None = None

    def parametros_desde_slot(self, slot: str) -> dict:
        return {"pregunta": slot} if slot else {}

    def ejecutar(self, pregunta: str = "", aplicacion: str = "") -> Resultado:
        apps = self._apps if self._apps is not None else apps_instaladas()
        ventana, duda = elegir_ventana(nombres_de_app(aplicacion, apps), aplicacion)
        if ventana is None:
            return Resultado(False, duda or f"No encuentro ninguna ventana abierta de '{aplicacion}'.")
        prohibida = ventana_prohibida(ventana)
        if prohibida:
            registrar_actividad("seguridad", f"Bloqueado {self.nombre}: {prohibida}", False)
            return Resultado(False, prohibida.replace("no escribo ni hago clic en ella", "no la leo"))

        log.info("Leyendo la ventana '%s'…", ventana["titulo"])
        texto = self._leer_estable(ventana["hwnd"])
        if not texto:
            return Resultado(False, f"No he podido leer nada en '{ventana['titulo']}' (la app no ofrece su "
                                    "texto a la accesibilidad de Windows).")
        datos = {"ventana": ventana["titulo"], "caracteres": len(texto), "aplicacion": aplicacion}
        if not llm_permitido():
            return Resultado(True, f"(LLM desactivado: no puedo responder, este es el texto de "
                                   f"'{ventana['titulo']}') {texto[:600]}", datos=datos)
        control.comprobar()   # botón de pánico
        log.info("Preguntando al LLM: %s", pregunta)
        respuesta = responder_sobre_texto(servidor_compartido(), pregunta, texto)
        if respuesta is None:
            return Resultado(True, f"(El LLM no está disponible; texto de '{ventana['titulo']}') {texto[:600]}",
                             datos=datos)
        return Resultado(True, respuesta, datos={**datos, "respuesta": respuesta})

    def _leer_estable(self, hwnd: int) -> str:
        """Lee la ventana; si el texto aún cambia (cargando), espera y vuelve a leer."""
        with uia.en_hilo():
            texto = uia.texto_de_ventana(hwnd)
            for _ in range(LECTURAS_MAX - 1):
                control.comprobar()
                time.sleep(PAUSA_ENTRE_LECTURAS)
                nuevo = uia.texto_de_ventana(hwnd)
                if nuevo == texto:
                    break
                texto = nuevo
        return texto
