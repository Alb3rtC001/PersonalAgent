"""
player.py

Reproduce una plantilla grabada con verificación de ventana activa y
log de ejecución en tiempo real.

La confirmación de pasos "definitivos" ya no se pide aquí con input():
la skill que envuelve la plantilla se marca como requiere_confirmacion
y es el executor quien pregunta al usuario (por CLI, API o móvil)
antes de empezar.
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
    import pyperclip
    PYPERCLIP_DISPONIBLE = True
except ImportError:
    PYPERCLIP_DISPONIBLE = False

try:
    from core.estado import buscar_ventana, obtener_ventana_activa
    WINDOW_MANAGER_DISPONIBLE = True
except ImportError:
    WINDOW_MANAGER_DISPONIBLE = False

ESPERA_ENTRE_EVENTOS = 0.5
ESPERA_TRAS_CLIC = 0.3


class LogEjecucion:
    def __init__(self):
        self.pasos = []

    def ok(self, descripcion: str):
        self.pasos.append({"estado": "OK", "descripcion": descripcion})
        print(f"  [ OK ] {descripcion}")

    def skip(self, descripcion: str, razon: str):
        self.pasos.append({"estado": "SKIP", "descripcion": descripcion, "razon": razon})
        print(f"  [SKIP] {descripcion} — {razon}")

    def error(self, descripcion: str, razon: str):
        self.pasos.append({"estado": "ERROR", "descripcion": descripcion, "razon": razon})
        print(f"  [ERR ] {descripcion} — {razon}")

    @property
    def ok(self) -> bool:
        """True si se ejecutaron todos los pasos sin errores ni cancelaciones."""
        return bool(self.pasos) and all(p["estado"] == "OK" for p in self.pasos)

    def resumen(self) -> str:
        total = len(self.pasos)
        oks = sum(1 for p in self.pasos if p["estado"] == "OK")
        skips = sum(1 for p in self.pasos if p["estado"] == "SKIP")
        errors = sum(1 for p in self.pasos if p["estado"] == "ERROR")
        return f"{total} pasos: {oks} OK, {skips} omitidos, {errors} errores"


def _ventana_correcta_activa(titulo_esperado: str) -> bool:
    if not WINDOW_MANAGER_DISPONIBLE or not titulo_esperado:
        return True
    ventana = obtener_ventana_activa()
    return titulo_esperado.lower() in ventana.get("titulo", "").lower()


def _esperar_ventana(titulo_esperado: str, intentos: int = 5,
                     espera: float = 1.0) -> bool:
    if not titulo_esperado:
        return True
    for _ in range(intentos):
        if _ventana_correcta_activa(titulo_esperado):
            return True
        time.sleep(espera)
    return False


def _escribir(texto: str) -> None:
    """typewrite solo sabe teclear ASCII; para tildes y eñes se pega desde el portapapeles."""
    if texto.isascii() or not PYPERCLIP_DISPONIBLE:
        pyautogui.typewrite(texto, interval=0.05)
    else:
        try:
            anterior = pyperclip.paste()
        except pyperclip.PyperclipException:
            anterior = None
        pyperclip.copy(texto)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)  # que la app lea el portapapeles antes de restaurarlo
        if anterior is not None:
            pyperclip.copy(anterior)  # no pisar lo que el usuario tenía copiado


def tiene_pasos_definitivos(plantilla: list[dict]) -> bool:
    return any(evento.get("definitivo") for evento in plantilla)


def _extraer_titulo_ventana_objetivo(plantilla: list[dict]) -> str | None:
    for evento in plantilla:
        if evento.get("tipo") == "click":
            ventana_info = evento.get("valor", {}).get("ventana")
            if ventana_info and ventana_info.get("titulo"):
                return ventana_info["titulo"]
    return None


def _obtener_rect_ventana_actual(titulo_parcial: str) -> dict | None:
    if not WINDOW_MANAGER_DISPONIBLE or not titulo_parcial:
        return None
    resultados = buscar_ventana(titulo_parcial)
    if not resultados:
        return None
    return resultados[0].get("rect")


def _resolver_coordenadas(datos_click: dict,
                           rect_ventana: dict | None) -> tuple[int, int] | None:
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
    return None


def _describir_paso(numero: int, tipo: str, valor, slot: str) -> str:
    if tipo == "tecla_especial":
        return f"Paso {numero}: tecla '{valor}'"
    elif tipo == "escribir":
        texto = slot if valor == "{slot}" else valor
        return f"Paso {numero}: escribir '{texto}'"
    elif tipo == "click" and isinstance(valor, dict):
        titulo = valor.get("ventana", {}).get("titulo", "") or "escritorio"
        x = valor.get("x_rel", valor.get("x_abs", "?"))
        y = valor.get("y_rel", valor.get("y_abs", "?"))
        return f"Paso {numero}: clic en '{titulo}' ({x}, {y})"
    return f"Paso {numero}: {tipo}"


def reproducir_plantilla(plantilla: list[dict], slot: str) -> LogEjecucion:
    log = LogEjecucion()
    if not PYAUTOGUI_DISPONIBLE:
        log.error("Reproducir plantilla", "falta 'pyautogui'")
        return log

    titulo_objetivo = _extraer_titulo_ventana_objetivo(plantilla)
    rect_ventana = None

    print(f"\n  Reproduciendo plantilla (slot='{slot}'):")
    if titulo_objetivo:
        print(f"  Ventana objetivo: '{titulo_objetivo}'")
        rect_ventana = _obtener_rect_ventana_actual(titulo_objetivo)
    print()

    for i, evento in enumerate(plantilla):
        tipo = evento.get("tipo")
        valor = evento.get("valor")

        titulo_ventana_evento = ""
        if tipo == "click" and isinstance(valor, dict):
            titulo_ventana_evento = valor.get("ventana", {}).get("titulo", "")

        descripcion = _describir_paso(i + 1, tipo, valor, slot)

        # Verificar que la ventana correcta está activa
        if tipo in ("click", "escribir") and titulo_ventana_evento:
            if not _esperar_ventana(titulo_ventana_evento):
                log.error(descripcion,
                          f"ventana '{titulo_ventana_evento}' no está activa "
                          f"tras 5 intentos")
                print(f"\n  Ejecución interrumpida en paso {i + 1}.")
                break

        # Ejecutar
        try:
            if tipo == "tecla_especial":
                pyautogui.press(valor)
                log.ok(descripcion)

            elif tipo == "escribir":
                texto = slot if valor == "{slot}" else valor
                _escribir(texto)
                log.ok(descripcion)

            elif tipo == "click":
                if titulo_ventana_evento:
                    rect_actual = _obtener_rect_ventana_actual(titulo_ventana_evento)
                    if rect_actual:
                        rect_ventana = rect_actual

                coords = _resolver_coordenadas(valor, rect_ventana)
                if coords:
                    pyautogui.click(coords[0], coords[1])
                    log.ok(f"{descripcion} → ({coords[0]}, {coords[1]})")
                    time.sleep(ESPERA_TRAS_CLIC)
                else:
                    log.error(descripcion, "coordenadas no resolubles")

        except Exception as e:
            log.error(descripcion, str(e))

        # Un paso fallido deja la pantalla en un estado desconocido: seguir
        # haría clics (quizá el último, el "definitivo") en el sitio equivocado.
        if log.pasos and log.pasos[-1]["estado"] == "ERROR":
            print(f"\n  Ejecución interrumpida en paso {i + 1}.")
            break

        time.sleep(ESPERA_ENTRE_EVENTOS)

    print(f"\n  {log.resumen()}")
    return log