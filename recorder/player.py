"""
player.py

Reproduce una plantilla grabada sustituyendo el hueco {slot} por el
valor real solicitado.

Para los clics, la lógica de resolución de coordenadas es:

1. Si el evento tiene x_abs/y_abs directamente → los usa tal cual
   (clics grabados con el formato nuevo completo).

2. Si el evento tiene x_rel/y_rel (offset desde la esquina de la
   ventana) → busca la ventana objetivo en pantalla ahora mismo y
   calcula la posición absoluta real sumando el offset a la posición
   actual de la ventana. Esto es lo que hace que la plantilla funcione
   aunque la ventana se haya movido o esté en otro monitor.

3. Si no hay ninguna coordenada → el evento se ignora con un aviso.

La ventana objetivo se extrae del primer clic que tenga información
de ventana grabada (campo "ventana" dentro del valor del evento).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pyautogui
    PYAUTOGUI_DISPONIBLE = True
except ImportError:
    PYAUTOGUI_DISPONIBLE = False

try:
    from window_manager import buscar_ventana
    WINDOW_MANAGER_DISPONIBLE = True
except ImportError:
    WINDOW_MANAGER_DISPONIBLE = False

ESPERA_ENTRE_EVENTOS = 0.4


def _extraer_titulo_ventana_objetivo(plantilla: list[dict]) -> str | None:
    """
    Extrae el título de la ventana objetivo de la plantilla buscando
    el primer evento de tipo click que tenga información de ventana
    grabada. Devuelve None si no encuentra ninguno.
    """
    for evento in plantilla:
        if evento.get("tipo") == "click":
            ventana_info = evento.get("valor", {}).get("ventana")
            if ventana_info and ventana_info.get("titulo"):
                return ventana_info["titulo"]
    return None


def _obtener_rect_ventana_actual(titulo_parcial: str) -> dict | None:
    """
    Busca la ventana por título parcial y devuelve su rect actual
    (posición real en pantalla en este momento).
    Devuelve None si no está abierta o no se puede obtener.
    """
    if not WINDOW_MANAGER_DISPONIBLE:
        return None
    resultados = buscar_ventana(titulo_parcial)
    if not resultados:
        return None
    return resultados[0].get("rect")


def _resolver_coordenadas(datos_click: dict, rect_ventana: dict | None) -> tuple[int, int] | None:
    """
    Resuelve las coordenadas finales de un clic siguiendo la prioridad:
    1. x_abs/y_abs directos
    2. x_rel/y_rel + posición actual de la ventana
    3. None si no hay coordenadas suficientes
    """
    x_abs = datos_click.get("x_abs")
    y_abs = datos_click.get("y_abs")
    if x_abs is not None and y_abs is not None:
        return int(x_abs), int(y_abs)

    x_rel = datos_click.get("x_rel")
    y_rel = datos_click.get("y_rel")
    if x_rel is not None and y_rel is not None:
        if rect_ventana:
            return (
                int(rect_ventana["left"]) + int(x_rel),
                int(rect_ventana["top"]) + int(y_rel),
            )
        else:
            print(f"  [player] Aviso: clic relativo ({x_rel}, {y_rel}) pero no se "
                  f"encontró la ventana objetivo en pantalla. Clic omitido.")
            return None

    return None


def reproducir_plantilla(plantilla: list[dict], slot: str) -> str:
    if not PYAUTOGUI_DISPONIBLE:
        return "No se puede reproducir la plantilla: falta 'pyautogui'."

    # Detectar la ventana objetivo una sola vez antes de empezar
    titulo_objetivo = _extraer_titulo_ventana_objetivo(plantilla)
    rect_ventana = None
    if titulo_objetivo:
        rect_ventana = _obtener_rect_ventana_actual(titulo_objetivo)
        if rect_ventana is None:
            print(f"  [player] Aviso: la ventana '{titulo_objetivo}' no está abierta. "
                  f"Los clics relativos no se podrán resolver.")

    for evento in plantilla:
        tipo = evento.get("tipo")
        valor = evento.get("valor")

        if tipo == "tecla_especial":
            pyautogui.press(valor)

        elif tipo == "escribir":
            texto = slot if valor == "{slot}" else valor
            pyautogui.typewrite(texto, interval=0.03)

        elif tipo == "click":
            coords = _resolver_coordenadas(valor, rect_ventana)
            if coords:
                pyautogui.click(coords[0], coords[1])
            # Si coords es None el aviso ya se imprimió dentro de _resolver_coordenadas

        time.sleep(ESPERA_ENTRE_EVENTOS)

    return f"Plantilla reproducida con slot='{slot}'"