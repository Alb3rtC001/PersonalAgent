"""
Skill hacer_clic: pulsa un botón, pestaña o enlace VISIBLE de una aplicación
por su nombre ("Biblioteca" en Steam, "Ajustes" en Discord), con UI
Automation: no depende de coordenadas grabadas ni del tamaño de la ventana.

Junto con escribir_texto (con `campo`) permite órdenes como "busca en steam
el juego X" → hacer_clic("Biblioteca") + escribir_texto("X", campo="Buscar
por nombre"). Qué botones y campos tiene cada app se apunta en
core/atajos_apps.json ("botones", "campos"), y el LLM los usa de ahí.

Seguridad:
- Nunca pulsa botones de CONTROLES_PROHIBIDOS (comprar, pagar, borrar...).
- Nunca actúa sobre VENTANAS_PROHIBIDAS.
- Solo pulsa lo que se ve de verdad: en el centro del control tiene que
  estar el propio control (Steam tiene un segundo botón JUGAR escondido en
  una cabecera) y la ventana de la app (no otra encima).
- Si hay varios distintos que encajan igual de bien, pregunta cuál.
- Comprueba que el clic ha cambiado algo en la ventana; si no, lo dice.
- Riesgo "medio": se confirma cuando la orden la ha interpretado el LLM.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager

from config import CONTROLES_PROHIBIDOS
from core import control, uia
from core.estado import hwnd_activo, normalizar
from core.seguridad import registrar_actividad
from core.skills.base import Resultado
from core.skills.teclado import DESCRIPCION_APLICACION, _EnAplicacion, _parecido
from core.skills.ventanas import elegir_opcion, preguntar

log = logging.getLogger("personalagent")

PARECIDO_MINIMO = 0.85       # más estricto que para elegir campo: un clic equivocado hace algo
ESPERA_CONTROL = 5.0         # las apps web construyen su árbol de accesibilidad al pedírselo
PAUSA_TRAS_CLIC = 0.5        # entre comprobaciones de si la ventana ha cambiado
ESPERA_CAMBIO = 4.0          # tiempo máximo para que se note el efecto del clic
# Entre dos controles igual de parecidos, mejor un botón que un texto suelto.
PRIORIDAD_TIPO = {"ButtonControl": 0, "HyperlinkControl": 0, "TabItemControl": 0, "MenuItemControl": 0,
                  "ListItemControl": 1, "TreeItemControl": 1, "SplitButtonControl": 1,
                  "CheckBoxControl": 2, "RadioButtonControl": 2, "DataItemControl": 2, "TextControl": 3}


def puntuar(elemento: str, nombre: str) -> float:
    """
    Igual (sin mayúsculas ni tildes) > el nombre contiene todo lo pedido
    ("Slay the Spire 2 [public-beta]") > lo pedido contiene el nombre ("Slay the
    Spire", que es otro juego) / misma raíz > parecido.
    """
    e, n = normalizar(elemento).strip(), normalizar(nombre).strip()
    if e == n:
        return 2.0
    if e and e in n:
        return 1.5
    return _parecido(elemento, nombre)


def elegir_control(elemento: str, candidatos: list, se_ve=lambda c: True
                   ) -> tuple[object | None, list[str], list]:
    """
    (control, nombres que había, dudas). Solo cuentan los que se ven de verdad
    (`se_ve`: en su centro está el propio control). Si el mejor no se llama
    exactamente así y hay varios distintos igual de buenos ("Slay the Spire 2
    [public-beta]" y "Slay the Spire 2 Demo"), no elige: devuelve en `dudas`
    un control de cada nombre para preguntar.
    """
    puntuados = []
    for orden, c in enumerate(candidatos):
        p = puntuar(elemento, c.Name)
        if p >= PARECIDO_MINIMO:
            # A igual parecido: tipo más "pulsable", nombre más corto, el que sale antes.
            puntuados.append((-p, PRIORIDAD_TIPO.get(c.ControlTypeName, 3), len(c.Name), orden, c))
    nombres = list(dict.fromkeys(c.Name for c in candidatos))
    visibles = [t for t in sorted(puntuados, key=lambda t: t[:4]) if se_ve(t[4])]
    if not visibles:
        return None, nombres, []
    mejor = visibles[0]
    if mejor[0] > -2.0:   # ninguno se llama exactamente así: si hay varios igual de buenos, duda
        por_nombre: dict[str, object] = {}
        # En el orden en que salen en la pantalla, que es como los verás.
        for t in sorted((t for t in visibles if t[0] == mejor[0]), key=lambda t: t[3]):
            por_nombre.setdefault(normalizar(t[4].Name), t[4])
        if len(por_nombre) > 1:
            return None, nombres, list(por_nombre.values())
    return mejor[4], nombres, []


def control_prohibido(nombre: str) -> str | None:
    n = f" {normalizar(nombre)} "
    for patron in CONTROLES_PROHIBIDOS:
        p = normalizar(patron)
        # "pay" no debe saltar con "display": las palabras cortas, enteras.
        if (len(p) <= 4 and f" {p} " in n) or (len(p) > 4 and p in n):
            return patron
    return None


def _pid(hwnd: int) -> int:
    from core.estado import _pid as pid_de
    try:
        return pid_de(hwnd)
    except Exception:
        return 0


def _mismo_programa(a: int, b: int) -> bool:
    pa = _pid(a)
    return pa != 0 and pa == _pid(b)


def _describir(hwnd: int) -> str:
    from core.estado import _obtener_proceso_por_pid, _titulo
    try:
        titulo, proceso = _titulo(hwnd), _obtener_proceso_por_pid(_pid(hwnd))
    except Exception:
        return "de otro programa"
    return f"'{titulo or '(sin título)'}' ({proceso or 'proceso desconocido'})"


def _ocultar(hwnd: int) -> None:
    import ctypes
    ctypes.windll.user32.ShowWindow(hwnd, 0)            # SW_HIDE


def _mostrar(hwnd: int) -> None:
    import ctypes
    ctypes.windll.user32.ShowWindow(hwnd, 4)            # SW_SHOWNOACTIVATE: sin quitarle el foco a la app


@contextmanager
def _sin_ventanas_propias_encima(x: int, y: int):
    """
    Si lo que tapa el punto es una ventana del propio agente (la interfaz o el
    aviso "el agente está actuando"), se esconde un momento para hacer el clic
    y se vuelve a mostrar después.
    """
    ocultas = []
    try:
        for _ in range(3):
            encima = uia.ventana_de_punto(x, y)
            if encima is None or _pid(encima) != os.getpid():
                break
            log.debug("Escondo un momento la ventana del agente que tapa el clic.")
            _ocultar(encima)
            ocultas.append(encima)
            time.sleep(0.15)
        yield
    finally:
        for hwnd in reversed(ocultas):
            _mostrar(hwnd)


def _clic(x: int, y: int) -> None:
    import pyautogui
    antes = pyautogui.position()
    pyautogui.click(x, y)
    try:
        pyautogui.moveTo(*antes)   # el ratón vuelve a donde lo tenías
    except Exception:
        pass


class HacerClic(_EnAplicacion):
    nombre = "hacer_clic"
    descripcion = ("Pulsa un botón, pestaña, enlace u opción que se ve en la ventana de una aplicación, "
                   "por su nombre (p. ej. 'Biblioteca' en Steam). No sirve para escribir (escribir_texto) "
                   "ni para atajos de teclado (pulsar_teclas). No pulsa botones de comprar, pagar o borrar.")
    parametros = {
        "elemento": "Nombre del botón, pestaña u opción tal como se ve en pantalla (p. ej. 'Biblioteca')",
        "aplicacion": DESCRIPCION_APLICACION,
    }
    riesgo = "medio"
    coste = 1

    def parametros_desde_slot(self, slot: str) -> dict:
        return {"elemento": slot} if slot else {}

    def ejecutar(self, elemento: str = "", aplicacion: str = "") -> Resultado:
        if not (elemento or "").strip():
            return Resultado(False, "¿Qué botón pulso?", falta="elemento")
        ventana, error = self._enfocar(aplicacion)
        if error:
            return Resultado(False, error)

        with uia.en_hilo():
            elegido, nombres, dudas = None, [], []
            limite = time.monotonic() + ESPERA_CONTROL
            while True:
                elegido, nombres, dudas = elegir_control(elemento, uia.controles_pulsables(ventana["hwnd"]),
                                                         se_ve=uia.se_ve_en_su_centro)
                if elegido is not None or dudas or time.monotonic() > limite:
                    break
                control.comprobar()   # botón de pánico
                time.sleep(0.5)
            if dudas:
                elegido, error = self._preguntar_cual(elemento, dudas)
                if error:
                    return Resultado(False, error)
            if elegido is None:
                vistos = ", ".join(f"'{n}'" for n in nombres[:15]) or "ninguno"
                return Resultado(False, f"No veo '{elemento}' en '{ventana['titulo']}' "
                                        f"(algunos de los que hay: {vistos}).")
            nombre, tipo = elegido.Name.strip(), elegido.ControlTypeName
            prohibido = control_prohibido(nombre)
            if prohibido:
                registrar_actividad("seguridad", f"Bloqueado {self.nombre}: botón '{nombre}' ('{prohibido}')", False)
                return Resultado(False, f"'{nombre}' es un botón delicado ('{prohibido}', CONTROLES_PROHIBIDOS "
                                        "en config.py): no lo pulso, hazlo tú.")
            x, y = uia.centro(elegido)
            with _sin_ventanas_propias_encima(x, y):
                encima = uia.ventana_de_punto(x, y)
                # Una ventana de la propia app (un diálogo de Steam) no estorba: es donde
                # está el botón. Una de otro programa sí.
                if encima is not None and encima != ventana["hwnd"] and not _mismo_programa(encima, ventana["hwnd"]):
                    return Resultado(False, f"La ventana {_describir(encima)} tapa '{nombre}' de "
                                            f"'{ventana['titulo']}': no hago clic a ciegas.")
                control.comprobar()
                antes = uia.huella(ventana["hwnd"])
                log.info("Clic en '%s' (%s) de '%s'.", nombre, tipo.replace("Control", ""), ventana["titulo"])
                _clic(x, y)
            # ¿Ha cambiado algo? (otra vista, el botón JUGAR pasa a DETENER...). Sin
            # cambios, el clic no ha llegado: mejor decirlo que dar un "Pulsado" falso.
            cambio = False
            limite = time.monotonic() + ESPERA_CAMBIO
            while not cambio and time.monotonic() < limite:
                time.sleep(PAUSA_TRAS_CLIC)
                cambio = uia.huella(ventana["hwnd"]) != antes
        return Resultado(True, f"Pulsado '{nombre}' en '{ventana['titulo']}'.", datos={
            "hwnd": ventana["hwnd"], "titulo": ventana["titulo"], "aplicacion": aplicacion,
            "elemento": nombre, "tipo": tipo, "cambio": cambio,
        })

    def _preguntar_cual(self, elemento: str, dudas: list) -> tuple[object | None, str | None]:
        nombres = [c.Name.strip() for c in dudas]
        lista = "; ".join(f"{i}) {n}" for i, n in enumerate(nombres, 1))
        respuesta = preguntar(f"Veo varios que encajan con '{elemento}': {lista}. ¿Cuál pulso? "
                              "(número o nombre)")
        if respuesta is None:
            return None, f"Veo varios que encajan con '{elemento}' ({lista}) y no sé cuál pulsar."
        i = elegir_opcion(respuesta, nombres)
        if i is None:
            return None, f"No sé cuál es '{respuesta}': no pulso nada."
        return dudas[i], None

    def verificar(self, resultado: Resultado) -> bool:
        if not resultado.ok:
            return False
        if not resultado.datos.get("cambio", True):
            resultado.datos["motivo_verificacion"] = (
                f"Hice clic en '{resultado.datos['elemento']}' pero no ha cambiado nada en la ventana: "
                "parece que el clic no ha llegado (o el botón no hace nada ahora mismo).")
            return False
        if hwnd_activo() != resultado.datos["hwnd"] and not resultado.datos.get("cambio"):
            resultado.datos["motivo_verificacion"] = "Después del clic la ventana ya no está delante."
            return False
        return True
