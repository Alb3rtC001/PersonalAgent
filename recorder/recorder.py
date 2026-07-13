"""
Grabador de acciones por demostración.

Captura la secuencia de teclas Y de clics de ratón mientras haces la
acción a mano.

Cómo funciona:
- Cada tecla especial (win, enter, tab...) se guarda como un evento
  "tecla_especial". Las teclas de texto normal se acumulan en un
  buffer y se cierran como "escribir" en cuanto aparece otro tipo
  de evento.
- Cada clic de ratón se guarda como un evento "click", con su
  posición (x, y) Y un pequeño recorte de pantalla alrededor del
  punto, para poder reconocerlo visualmente más adelante aunque la
  posición cambie de sitio.
- Pulsa F9 para terminar la grabación.
- Al terminar, se pide un nombre de acción y la grabación se guarda
  en recordings.json.

Requiere: python -m pip install pynput pyautogui
Recomendado además: python -m pip install opencv-python
(sin opencv, la coincidencia de imagen en el reproductor es exacta
pixel a pixel; con opencv permite tolerancia, mucho más robusto)
"""

import threading
import time
from pathlib import Path

from pynput import keyboard, mouse

from storage import cargar_grabaciones, guardar_grabacion

try:
    import pyautogui
    PYAUTOGUI_DISPONIBLE = True
except ImportError:
    PYAUTOGUI_DISPONIBLE = False

# Nota: en Windows, pynput puede reportar la tecla Windows como
# Key.cmd_l o Key.cmd_r en vez de Key.cmd genérico. Se incluyen las
# tres variantes para no perder la pulsación en silencio.
TECLAS_ESPECIALES = {
    keyboard.Key.cmd: "win",
    keyboard.Key.cmd_l: "win",
    keyboard.Key.cmd_r: "win",
    keyboard.Key.enter: "enter",
    keyboard.Key.tab: "tab",
    keyboard.Key.esc: "esc",
    #keyboard.Key.space: "espacio",
}

TECLA_PARADA = keyboard.Key.f9

CARPETA_CAPTURAS = Path(__file__).parent / "capturas"
TAMANO_RECORTE = 40  # píxeles de lado del recorte alrededor del clic


class Grabador:
    def __init__(self):
        self._eventos = []
        self._buffer_texto = ""
        self._lock = threading.Lock()
        self._mouse_listener = None

    def _agregar_evento(self, evento: dict):
        evento["timestamp"] = time.time()
        with self._lock:
            self._eventos.append(evento)

    def _cerrar_buffer_texto(self):
        if self._buffer_texto:
            self._agregar_evento({"tipo": "escribir", "valor": self._buffer_texto})
            self._buffer_texto = ""

    def _on_press(self, key):
        if key == TECLA_PARADA:
            if self._mouse_listener:
                self._mouse_listener.stop()
            return False  # detiene el listener de teclado
        
        # La barra espaciadora debe formar parte del texto, no ser un evento independiente.
        if key == keyboard.Key.space:
            self._buffer_texto += " "
            return

        if key in TECLAS_ESPECIALES:
            self._cerrar_buffer_texto()
            self._agregar_evento({"tipo": "tecla_especial", "valor": TECLAS_ESPECIALES[key]})
        else:
            try:
                self._buffer_texto += key.char
            except AttributeError:
                pass  # tecla no imprimible que no nos interesa (shift, ctrl...)

    def _capturar_recorte(self, x: int, y: int) -> str:
        """Guarda un recorte de pantalla alrededor del clic. Devuelve la ruta relativa, o "" si falla."""
        if not PYAUTOGUI_DISPONIBLE:
            return ""
        try:
            CARPETA_CAPTURAS.mkdir(exist_ok=True)
            mitad = TAMANO_RECORTE // 2
            region = (max(0, x - mitad), max(0, y - mitad), TAMANO_RECORTE, TAMANO_RECORTE)
            nombre = f"click_{int(time.time() * 1000)}.png"
            ruta = CARPETA_CAPTURAS / nombre
            pyautogui.screenshot(region=region).save(ruta)
            return str(ruta.relative_to(Path(__file__).parent))
        except Exception as e:
            print(f"Error capturado en _capturar_recorte: {e}")
            return ""  # si falla la captura, seguimos solo con coordenadas

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return  # solo nos interesa el momento de pulsar, no de soltar
        self._cerrar_buffer_texto()
        ruta_imagen = self._capturar_recorte(x, y)
        self._agregar_evento({
            "tipo": "click",
            "valor": {"x": x, "y": y, "boton": str(button), "imagen": ruta_imagen},
        })

    def grabar(self) -> list[dict]:
        """Bloquea hasta que se pulsa F9. Devuelve la secuencia de eventos grabada, ordenada en el tiempo."""
        self._eventos = []
        self._buffer_texto = ""

        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()

        with keyboard.Listener(on_press=self._on_press) as kb_listener:
            kb_listener.join()

        self._cerrar_buffer_texto()
        self._eventos.sort(key=lambda e: e["timestamp"])
        return self._eventos


if __name__ == "__main__":
    nombre_accion = input("Nombre de la acción a grabar (ej. abrir_aplicacion): ").strip()

    grabador = Grabador()
    print("Grabando... haz la acción ahora (teclado y/o ratón) y pulsa F9 para terminar.")
    eventos = grabador.grabar()

    print("\nSecuencia grabada:")
    for evento in eventos:
        print(" ", {k: v for k, v in evento.items() if k != "timestamp"})

    total = guardar_grabacion(nombre_accion, eventos)
    print(f"\nGuardada en recordings.json. Ya tienes {total} grabación(es) de '{nombre_accion}'.")
    if total < 2:
        print("Necesitas al menos 2 grabaciones con valores DISTINTOS para poder generalizar (ver build_templates.py).")