"""
Grabador de acciones por demostración.

Captura la secuencia de teclas que pulsas mientras haces la acción a
mano (ej. abrir el menú Inicio, escribir "discord", pulsar Enter).

Cómo funciona:
- Cada tecla especial (win, enter, tab...) se guarda como un evento
  "tecla_especial". Las teclas de texto normal se van acumulando en
  un buffer y se cierran como un evento "escribir" en cuanto aparece
  una tecla especial o se detiene la grabación.
- Pulsa F9 para terminar la grabación.
- Al terminar, se pide un nombre de acción y la grabación se guarda
  en recordings.json, acumulando bajo ese mismo nombre para poder
  generalizarla más adelante (con 2+ grabaciones).

Requiere: python -m pip install pynput
"""

import json
from pathlib import Path

from pynput import keyboard

RUTA_GRABACIONES = Path(__file__).parent / "recordings.json"

# Nota: en Windows, pynput puede reportar la tecla Windows como
# Key.cmd_l o Key.cmd_r en vez de Key.cmd genérico. Se incluyen las
# tres variantes para no perder la pulsación en silencio como pasó
# la primera vez.
TECLAS_ESPECIALES = {
    keyboard.Key.cmd: "win",
    keyboard.Key.cmd_l: "win",
    keyboard.Key.cmd_r: "win",
    keyboard.Key.enter: "enter",
    keyboard.Key.tab: "tab",
    keyboard.Key.esc: "esc",
    keyboard.Key.space: "espacio",
}

TECLA_PARADA = keyboard.Key.f9


class Grabador:
    def __init__(self):
        self._eventos = []
        self._buffer_texto = ""

    def _cerrar_buffer_texto(self):
        if self._buffer_texto:
            self._eventos.append({"tipo": "escribir", "valor": self._buffer_texto})
            self._buffer_texto = ""

    def _on_press(self, key):
        if key == TECLA_PARADA:
            return False  # detiene el listener

        if key in TECLAS_ESPECIALES:
            self._cerrar_buffer_texto()
            self._eventos.append({"tipo": "tecla_especial", "valor": TECLAS_ESPECIALES[key]})
        else:
            try:
                self._buffer_texto += key.char
            except AttributeError:
                pass  # tecla no imprimible que no nos interesa (shift, ctrl...)

    def grabar(self) -> list[dict]:
        """Bloquea hasta que se pulsa F9. Devuelve la secuencia de eventos grabada."""
        self._eventos = []
        self._buffer_texto = ""
        with keyboard.Listener(on_press=self._on_press) as listener:
            listener.join()
        self._cerrar_buffer_texto()
        return self._eventos


def cargar_grabaciones() -> dict:
    if not RUTA_GRABACIONES.exists():
        return {}
    with open(RUTA_GRABACIONES, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_grabacion(nombre_accion: str, eventos: list[dict]) -> int:
    """Añade esta grabación a las que ya hubiera para esa acción. Devuelve el total acumulado."""
    grabaciones = cargar_grabaciones()
    grabaciones.setdefault(nombre_accion, [])
    grabaciones[nombre_accion].append(eventos)
    with open(RUTA_GRABACIONES, "w", encoding="utf-8") as f:
        json.dump(grabaciones, f, ensure_ascii=False, indent=2)
    return len(grabaciones[nombre_accion])


if __name__ == "__main__":
    nombre_accion = input("Nombre de la acción a grabar (ej. abrir_aplicacion): ").strip()

    grabador = Grabador()
    print("Grabando... haz la acción ahora y pulsa F9 para terminar.")
    eventos = grabador.grabar()

    print("\nSecuencia grabada:")
    for evento in eventos:
        print(" ", evento)

    total = guardar_grabacion(nombre_accion, eventos)
    print(f"\nGuardada en recordings.json. Ya tienes {total} grabación(es) de '{nombre_accion}'.")
    if total < 2:
        print("Necesitas al menos 2 grabaciones con valores DISTINTOS para poder generalizar (ver build_templates.py).")