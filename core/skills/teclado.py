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

import difflib
import time

from core import campos, control, uia
from core.estado import hwnd_activo, normalizar, poner_foco
from core.skills.abrir_aplicacion import AppInstalada, apps_instaladas
from core.seguridad import registrar_actividad, ventana_prohibida
from core.skills.base import Resultado, Skill
from core.skills.ventanas import elegir_opcion, elegir_ventana, nombres_de_app, preguntar
from core.teclado import (
    ErrorTeclas,
    describir_combinacion,
    escribir,
    interpretar_teclas,
    limpiar_texto_a_escribir,
    pulsar,
)

PAUSA_TRAS_CAMBIAR_FOCO = 0.3   # segundos
INTENTOS_COMPROBACION = 8       # lecturas del campo tras escribir (máx. ~1,6 s)
PAUSA_COMPROBACION = 0.2

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
        apps = self._apps if self._apps is not None else apps_instaladas()
        ventana, duda = elegir_ventana(nombres_de_app(aplicacion, apps), aplicacion)
        if ventana is None:
            return None, duda or f"No encuentro ninguna ventana abierta de '{aplicacion}'."
        prohibida = ventana_prohibida(ventana)
        if prohibida:
            registrar_actividad("seguridad", f"Bloqueado {self.nombre}: {prohibida}", False)
            return None, prohibida
        ya_tenia_foco = hwnd_activo() == ventana["hwnd"]
        if not poner_foco(ventana["hwnd"]):
            return None, (f"No he podido darle el foco a '{ventana['titulo']}' (Windows no lo ha "
                          "permitido); no escribo nada para no hacerlo en otra ventana.")
        if not ya_tenia_foco:
            # Margen para que la app pase el foco a su control antes de la primera tecla.
            control.comprobar()   # botón de pánico
            time.sleep(PAUSA_TRAS_CAMBIAR_FOCO)
        return ventana, None


def _parecido(campo: str, nombre: str) -> float:
    """'buscador' ~ 'Buscar', 'mensaje' ~ 'Enviar mensaje a #general', 'direcciones' ~ 'Barra de direcciones'."""
    a, b = normalizar(campo), normalizar(nombre)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    raices = {p[:5] for p in a.split() if len(p) >= 4}
    if raices and any(p[:5] in raices for p in b.split()):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def preparar_campo(hwnd: int, campo: str | None, ventana: dict | None = None
                   ) -> tuple[object | None, str | None, str | None]:
    """(control, nombre, error): ver `elegir_campo`."""
    return elegir_campo(hwnd, campo, ventana)[:3]


def _describir_campo(control) -> tuple[str, str, str]:
    try:
        return uia.nombre_de_campo(control), control.AutomationId or "", control.ControlTypeName
    except Exception:
        return uia.nombre_de_campo(control), "", ""


def elegir_campo(hwnd: int, campo: str | None, ventana: dict | None = None
                 ) -> tuple[object | None, str | None, str | None, str | None]:
    """
    Pone el foco en el campo donde escribir. Devuelve (control, nombre, error, por qué):
    - con `campo` ("buscador"): el campo editable de la ventana con ese nombre ("dicho");
    - sin `campo`: si el foco ya está en un campo editable de la ventana, ese
      ("foco"); si no, el único que haya ("unico"); si hay varios, el que se
      usó la última vez en esa app ("recordado", data/campos.json) o se
      pregunta cuál ("preguntado"); sin nadie a quien preguntar, error. Si no
      hay ninguno, (None, None, None, None): la ventana entera recibe el
      teclado (la Calculadora).
    """
    foco = uia.foco_actual()
    origen = None
    if campo:
        candidatos = uia.campos_editables(hwnd)
        puntuados = sorted(((_parecido(campo, uia.nombre_de_campo(c)), c) for c in candidatos),
                           key=lambda p: -p[0])
        if not puntuados or puntuados[0][0] < 0.6:
            nombres = ", ".join(f"'{uia.nombre_de_campo(c)}'" for c in candidatos) or "ninguno"
            return None, None, f"No encuentro el campo '{campo}' (campos de texto de la ventana: {nombres}).", None
        elegido, origen = puntuados[0][1], "dicho"
    elif foco is not None and uia.es_editable(foco) and _de_la_ventana(foco, hwnd):
        return foco, uia.nombre_de_campo(foco), None, "foco"
    else:
        candidatos = uia.campos_editables(hwnd)
        if not candidatos:
            return None, None, None, None
        if len(candidatos) == 1:
            elegido, origen = candidatos[0], "unico"
        else:
            elegido = campos.buscar(candidatos, campos.recordado(ventana), _describir_campo) if ventana else None
            origen = "recordado"
            if elegido is None:
                elegido, error = _preguntar_campo(candidatos)
                if error:
                    return None, None, error, None
                origen = "preguntado"
    try:
        elegido.SetFocus()
        time.sleep(0.15)
    except Exception:
        pass
    return elegido, uia.nombre_de_campo(elegido), None, origen


def _preguntar_campo(candidatos: list) -> tuple[object | None, str | None]:
    nombres = [uia.nombre_de_campo(c) for c in candidatos[:8]]
    lista = "; ".join(f"{i}) {n}" for i, n in enumerate(nombres, 1))
    respuesta = preguntar(f"El cursor no está en ningún campo de texto. ¿En cuál escribo? {lista}. "
                          "(número o nombre; me acordaré para la próxima vez)")
    if respuesta is None:
        return None, (f"El cursor no está en ningún campo de texto y hay {len(candidatos)} "
                      f"({', '.join(repr(n) for n in nombres)}): dime en cuál, p. ej. \"escribe ... en el "
                      f"campo {nombres[0]}\".")
    i = elegir_opcion(respuesta, nombres)
    if i is None:
        return None, f"No sé cuál es '{respuesta}': no escribo nada."
    return candidatos[i], None


def _de_la_ventana(control, hwnd: int) -> bool:
    try:
        return (control.GetTopLevelControl() or control).NativeWindowHandle == hwnd
    except Exception:
        return False


# Campos cuyo contenido anterior sobra: una búsqueda nueva sustituye a la vieja
# (en los demás, p. ej. un mensaje a medias, se escribe a continuación).
PALABRAS_CAMPO_BUSQUEDA = ("busca", "search", "filtr", "direccion", "address", "url")


def es_campo_de_busqueda(nombre: str | None) -> bool:
    n = normalizar(nombre or "")
    return any(p in n for p in PALABRAS_CAMPO_BUSQUEDA)


def vaciar_si_es_busqueda(campo, nombre: str | None) -> tuple[bool, str | None]:
    """
    Si es un campo de búsqueda con texto, lo vacía (Ctrl+A y Supr) y comprueba
    que ha quedado vacío ANTES de escribir. Devuelve (vaciado, error).
    """
    if campo is None or not es_campo_de_busqueda(nombre) or not uia.leer_valor(campo):
        return False, None
    for combinacion in interpretar_teclas("control a supr"):
        pulsar(combinacion)
    for intento in range(INTENTOS_COMPROBACION):
        if not uia.leer_valor(campo):
            return True, None
        time.sleep(PAUSA_COMPROBACION)
    return False, (f"No he podido vaciar el campo '{nombre}' (sigue con texto): no escribo encima "
                   "para no mezclar las dos búsquedas.")


def comprobar_escrito(campo, texto: str, exacto: bool = False) -> bool | None:
    """
    ¿El campo contiene el texto? (`exacto`: ¿es exactamente el texto? tras
    vaciarlo no debe quedar nada más). None si no se puede leer (la Calculadora).
    """
    if campo is None:
        return None
    # Las apps web (Steam, Discord) actualizan el valor un momento después de
    # recibir las teclas: se vuelve a leer unas cuantas veces antes de dar el fallo.
    for intento in range(INTENTOS_COMPROBACION):
        valor = uia.leer_valor(campo)
        if valor is None:
            return None
        if (normalizar(valor).strip() == normalizar(texto).strip()) if exacto else (normalizar(texto) in normalizar(valor)):
            return True
        if intento < INTENTOS_COMPROBACION - 1:
            time.sleep(PAUSA_COMPROBACION)
    return False


class EscribirTexto(_EnAplicacion):
    nombre = "escribir_texto"
    descripcion = ("Escribe un texto, como si lo tecleara el usuario, en la ventana de una "
                   "aplicación abierta (la pone antes en primer plano y elige el cuadro de texto). "
                   "No pulsa Enter ni envía nada: para eso está pulsar_teclas. No sirve para "
                   "guardar notas: eso es crear_nota.")
    parametros = {
        "texto": "Texto exacto a escribir, copiado tal cual de la orden",
        "aplicacion": DESCRIPCION_APLICACION,
    }
    parametros_opcionales = {
        "campo": ("Cuadro de texto donde escribir, solo si el usuario lo dice (p. ej. 'buscador', "
                  "'mensaje', 'barra de direcciones'). Si no lo dice, no lo incluyas"),
    }
    parametros_literales = frozenset({"texto"})
    coste = 1

    def ejecutar(self, texto: str = "", aplicacion: str = "", campo: str | None = None) -> Resultado:
        texto = limpiar_texto_a_escribir(texto or "")
        if not texto.strip():
            return Resultado(False, "No hay nada que escribir.", falta="texto")
        ventana, error = self._enfocar(aplicacion)
        if error:
            return Resultado(False, error)

        with uia.en_hilo():
            control_campo, nombre_campo, error, origen = elegir_campo(ventana["hwnd"], campo, ventana)
            if error:
                return Resultado(False, error)
            reemplazado, error = vaciar_si_es_busqueda(control_campo, nombre_campo)
            if error:
                return Resultado(False, error)
            esperados = len(texto.encode("utf-16-le")) // 2
            enviados = escribir(texto)
            comprobado = comprobar_escrito(control_campo, texto, exacto=reemplazado)
            if origen in ("dicho", "preguntado") and comprobado is not False:
                # "En esta app, aquí": la próxima vez, sin preguntar.
                campos.recordar(ventana, *_describir_campo(control_campo))
        donde = f"'{ventana['titulo']}'" + (f", campo '{nombre_campo}'" if nombre_campo else "")
        if origen == "recordado":
            donde += " (el que usaste la última vez en esta app)"
        return Resultado(True, f"Escrito en {donde}: {texto!r}" + (" (antes he vaciado el campo)" if reemplazado else ""),
                         datos={
            "hwnd": ventana["hwnd"], "titulo": ventana["titulo"], "aplicacion": aplicacion,
            "enviados": enviados, "esperados": esperados, "campo": nombre_campo, "comprobado": comprobado,
            "reemplazado": reemplazado,
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
        if datos.get("comprobado") is False:
            datos["motivo_verificacion"] = (f"Lo escribí, pero el campo '{datos.get('campo')}' no lo contiene "
                                            "(la app puede haberlo rechazado o cambiado).")
            return False
        # comprobado None: el campo no se puede leer (p. ej. la Calculadora).
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
    riesgo = "alto"
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
