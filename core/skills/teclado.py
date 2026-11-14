"""
Skills de teclado: escribir_texto y pulsar_teclas.

Las dos actúan sobre la ventana de una aplicación: primero la ponen en
primer plano y comprueban que tiene el foco del teclado; si no lo
consiguen, no escriben nada (para no teclear en otra ventana, p. ej. en
la propia consola del agente).

Si no se dice la aplicación, el agente usa la última con la que se ha
trabajado en la sesión ("abre la calculadora" → "escribe 2+2").

Limitación importante: tener el foco en la VENTANA no garantiza que el
texto vaya al CAMPO correcto. En la Calculadora sí (toda la ventana
acepta teclado); en un navegador o en Discord puede que haya que
seleccionar antes el cuadro de texto. Ver ARQUITECTURA.md §11.
"""

from __future__ import annotations

import time

from core import control
from core.estado import hwnd_activo, poner_foco
from core.skills.abrir_aplicacion import AppInstalada, listar_apps_instaladas
from core.skills.base import Resultado, Skill
from core.skills.ventanas import nombres_de_app, ventana_principal
from core.teclado import (
    ErrorTeclas,
    describir_combinacion,
    escribir,
    interpretar_teclas,
    limpiar_texto_a_escribir,
    pulsar,
)

PAUSA_TRAS_CAMBIAR_FOCO = 0.3   # segundos

DESCRIPCION_APLICACION = ("Aplicación donde actuar, tal como la nombra el usuario. Si no la dice, "
                          "no la incluyas: se usa la última con la que se ha trabajado")


class _EnAplicacion(Skill):
    """Base: localizar la ventana de la app y darle el foco del teclado."""

    PRECONDICIONES = {"visible:{aplicacion}": True}   # el planificador la abre/restaura si hace falta
    interpretar_con_llm = True
    del_contexto = {"aplicacion": "ultima_aplicacion"}

    def __init__(self):
        self._apps: list[AppInstalada] | None = None

    def _enfocar(self, aplicacion: str) -> tuple[dict | None, str | None]:
        try:
            if self._apps is None:
                self._apps = listar_apps_instaladas()
        except Exception:
            self._apps = []
        ventana = ventana_principal(nombres_de_app(aplicacion, self._apps))
        if ventana is None:
            return None, f"No encuentro ninguna ventana abierta de '{aplicacion}'."
        ya_tenia_foco = hwnd_activo() == ventana["hwnd"]
        if not poner_foco(ventana["hwnd"]):
            return None, (f"No he podido darle el foco a '{ventana['titulo']}' (Windows no lo ha "
                          "permitido); no escribo nada para no hacerlo en otra ventana.")
        if not ya_tenia_foco:
            # Margen para que la app pase el foco a su control antes de la primera tecla.
            control.comprobar()   # botón de pánico
            time.sleep(PAUSA_TRAS_CAMBIAR_FOCO)
        return ventana, None


class EscribirTexto(_EnAplicacion):
    nombre = "escribir_texto"
    descripcion = ("Escribe un texto, como si lo tecleara el usuario, en la ventana de una "
                   "aplicación abierta (la pone antes en primer plano). No pulsa Enter ni envía "
                   "nada: para eso está pulsar_teclas. No sirve para guardar notas: eso es crear_nota.")
    parametros = {
        "texto": "Texto exacto a escribir, copiado tal cual de la orden",
        "aplicacion": DESCRIPCION_APLICACION,
    }
    parametros_literales = frozenset({"texto"})
    coste = 1

    def ejecutar(self, texto: str = "", aplicacion: str = "") -> Resultado:
        texto = limpiar_texto_a_escribir(texto or "")
        if not texto.strip():
            return Resultado(False, "No hay nada que escribir.", falta="texto")
        ventana, error = self._enfocar(aplicacion)
        if error:
            return Resultado(False, error)

        esperados = len(texto.encode("utf-16-le")) // 2
        enviados = escribir(texto)
        return Resultado(True, f"Escrito en '{ventana['titulo']}': {texto!r}", datos={
            "hwnd": ventana["hwnd"], "titulo": ventana["titulo"], "aplicacion": aplicacion,
            "enviados": enviados, "esperados": esperados,
        })

    def verificar(self, resultado: Resultado) -> bool:
        if not resultado.ok:
            return False
        datos = resultado.datos
        if datos["enviados"] != datos["esperados"]:
            datos["motivo_verificacion"] = (f"Windows solo aceptó {datos['enviados']} de "
                                            f"{datos['esperados']} caracteres.")
            return False
        if hwnd_activo() != datos["hwnd"]:
            datos["motivo_verificacion"] = ("El foco cambió de ventana mientras escribía: puede que "
                                            "parte del texto haya ido a otra ventana.")
            return False
        # Lo que no se puede comprobar aquí es que el campo correcto lo haya
        # recibido (ver el docstring del módulo).
        return True


class PulsarTeclas(_EnAplicacion):
    nombre = "pulsar_teclas"
    descripcion = ("Pulsa teclas o combinaciones de teclas (enter, tab, escape, flechas, "
                   "control+s...) en la ventana de una aplicación abierta (la pone antes en "
                   "primer plano). No escribe textos: para eso está escribir_texto.")
    parametros = {
        "teclas": ("Teclas copiadas tal cual de la orden, p. ej. 'enter', 'control s', "
                   "'tab tab', 'flecha abajo 3 veces'"),
        "aplicacion": DESCRIPCION_APLICACION,
    }
    # Las teclas no se anclan a la frase: se valida que existan (comprobar_valores)
    # y, si las propone el LLM, se confirman antes de pulsarlas.
    parametros_sin_anclar = frozenset({"teclas"})
    confirmar_si_llm = True   # un Enter puede enviar un mensaje; alt+f4 cierra la ventana
    coste = 1

    def comprobar_valores(self, params: dict) -> str | None:
        try:
            interpretar_teclas(params.get("teclas") or "")
        except ErrorTeclas as e:
            return str(e)
        return None

    def ejecutar(self, teclas: str = "", aplicacion: str = "") -> Resultado:
        try:
            combinaciones = interpretar_teclas(teclas or "")
        except ErrorTeclas as e:
            return Resultado(False, f"{e} Ejemplos: 'enter', 'control s', 'tab 3 veces'.")
        ventana, error = self._enfocar(aplicacion)
        if error:
            return Resultado(False, error)

        pulsadas = []
        for combinacion in combinaciones:
            if not pulsar(combinacion):
                break
            pulsadas.append(describir_combinacion(combinacion))
            control.comprobar()   # botón de pánico
            time.sleep(0.05)
        return Resultado(True, f"Pulsado en '{ventana['titulo']}': {', '.join(pulsadas)}", datos={
            "hwnd": ventana["hwnd"], "titulo": ventana["titulo"], "aplicacion": aplicacion,
            "pulsadas": pulsadas, "pedidas": len(combinaciones),
        })

    def verificar(self, resultado: Resultado) -> bool:
        if not resultado.ok:
            return False
        datos = resultado.datos
        if len(datos["pulsadas"]) != datos["pedidas"]:
            datos["motivo_verificacion"] = (f"Windows solo aceptó {len(datos['pulsadas'])} de "
                                            f"{datos['pedidas']} pulsaciones.")
            return False
        # No se comprueba el foco después: un Enter o un alt+f4 lo cambian a propósito.
        return True
