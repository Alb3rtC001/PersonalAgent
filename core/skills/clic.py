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
- Antes de pulsar comprueba que en ese punto de la pantalla está la ventana
  de la app (no otra encima).
- Riesgo "medio": se confirma cuando la orden la ha interpretado el LLM.
"""

from __future__ import annotations

import logging
import time

from config import CONTROLES_PROHIBIDOS
from core import control, uia
from core.estado import hwnd_activo, normalizar
from core.seguridad import registrar_actividad
from core.skills.base import Resultado
from core.skills.teclado import DESCRIPCION_APLICACION, _EnAplicacion, _parecido

log = logging.getLogger("personalagent")

PARECIDO_MINIMO = 0.85       # más estricto que para elegir campo: un clic equivocado hace algo
ESPERA_CONTROL = 5.0         # las apps web construyen su árbol de accesibilidad al pedírselo
PAUSA_TRAS_CLIC = 1.0        # que la app cambie de vista antes del paso siguiente
# Entre dos controles igual de parecidos, mejor un botón que un texto suelto.
PRIORIDAD_TIPO = {"ButtonControl": 0, "HyperlinkControl": 0, "TabItemControl": 0, "MenuItemControl": 0,
                  "ListItemControl": 1, "TreeItemControl": 1, "SplitButtonControl": 1,
                  "CheckBoxControl": 2, "RadioButtonControl": 2, "DataItemControl": 2, "TextControl": 3}


def puntuar(elemento: str, nombre: str) -> float:
    """Igual (sin mayúsculas ni tildes) > contenido / misma raíz > parecido."""
    if normalizar(elemento) == normalizar(nombre):
        return 2.0
    return _parecido(elemento, nombre)


def elegir_control(elemento: str, candidatos: list) -> tuple[object | None, list[str]]:
    """El control que mejor encaja con `elemento` (o None) y los nombres que había."""
    puntuados = []
    for orden, c in enumerate(candidatos):
        p = puntuar(elemento, c.Name)
        if p >= PARECIDO_MINIMO:
            # A igual parecido: tipo más "pulsable", nombre más corto, el que sale antes.
            puntuados.append((-p, PRIORIDAD_TIPO.get(c.ControlTypeName, 3), len(c.Name), orden, c))
    nombres = list(dict.fromkeys(c.Name for c in candidatos))
    if not puntuados:
        return None, nombres
    return min(puntuados, key=lambda t: t[:4])[4], nombres


def control_prohibido(nombre: str) -> str | None:
    n = f" {normalizar(nombre)} "
    for patron in CONTROLES_PROHIBIDOS:
        p = normalizar(patron)
        # "pay" no debe saltar con "display": las palabras cortas, enteras.
        if (len(p) <= 4 and f" {p} " in n) or (len(p) > 4 and p in n):
            return patron
    return None


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
            elegido, nombres = None, []
            limite = time.monotonic() + ESPERA_CONTROL
            while True:
                elegido, nombres = elegir_control(elemento, uia.controles_pulsables(ventana["hwnd"]))
                if elegido is not None or time.monotonic() > limite:
                    break
                control.comprobar()   # botón de pánico
                time.sleep(0.5)
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
            encima = uia.ventana_de_punto(x, y)
            if encima is not None and encima != ventana["hwnd"]:
                return Resultado(False, f"Hay otra ventana encima de '{nombre}': no hago clic a ciegas.")
            control.comprobar()
            log.info("Clic en '%s' (%s) de '%s'.", nombre, tipo.replace("Control", ""), ventana["titulo"])
            _clic(x, y)
        time.sleep(PAUSA_TRAS_CLIC)
        return Resultado(True, f"Pulsado '{nombre}' en '{ventana['titulo']}'.", datos={
            "hwnd": ventana["hwnd"], "titulo": ventana["titulo"], "aplicacion": aplicacion,
            "elemento": nombre, "tipo": tipo,
        })

    def verificar(self, resultado: Resultado) -> bool:
        if not resultado.ok:
            return False
        if hwnd_activo() != resultado.datos["hwnd"]:
            resultado.datos["motivo_verificacion"] = "Después del clic la ventana ya no está delante."
            return False
        return True
