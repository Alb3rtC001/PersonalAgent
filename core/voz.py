"""
Voz → texto, 100 % local (botón del micrófono de la interfaz).

- Grabacion: graba del micrófono por defecto (sounddevice) hasta que pulsas
  otra vez el botón, te callas un momento después de hablar
  (VOZ_SILENCIO_FIN) o se llega al tope (VOZ_MAX_SEGUNDOS). Si no se oye
  nada en VOZ_ESPERA_SIN_VOZ segundos, deja de escuchar.
- Transcriptor: pasa el audio a texto con faster-whisper (modelo Whisper
  "small", licencia MIT) en la CPU con int8: no usa VRAM, así que no se suma
  a la que ocupa el LLM.

Privacidad: el audio solo vive en memoria mientras se transcribe; no se
guarda en disco ni sale del PC. Solo queda el texto reconocido (como si lo
hubieras escrito).
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from config import (
    RUTA_MODELO_VOZ,
    VOZ_ESPERA_SIN_VOZ,
    VOZ_HILOS_CPU,
    VOZ_IDIOMA,
    VOZ_MAX_SEGUNDOS,
    VOZ_SILENCIO_FIN,
)
from core import control

log = logging.getLogger("personalagent")

FRECUENCIA_WHISPER = 16000
UMBRAL_VOZ_MIN = 0.01        # volumen (RMS) mínimo para considerar que hablas
FACTOR_SOBRE_RUIDO = 3.0     # o 3 veces el ruido de fondo, si este es mayor
SEGUNDOS_RUIDO = 0.4         # lo primero que se graba sirve para medir el ruido de fondo

# Pista para Whisper: vocabulario típico de las órdenes (mejora nombres de apps).
PISTA = "Órdenes a un asistente del ordenador: abre Steam, cierra Discord, escribe en el bloc de notas, busca en Chrome."

# Frases que Whisper "se inventa" con silencio o ruido (vienen de los subtítulos con
# los que se entrenó). Si el texto es solo eso, es que no has dicho nada.
ALUCINACIONES = (
    "subtitulos realizados por la comunidad de amara.org", "subtitulado por la comunidad de amara.org",
    "gracias por ver el video", "gracias por ver", "suscribete", "¡suscribete!", "musica", "[musica]",
    "subtitulos por la comunidad de amara.org", "...",
)


def disponible() -> str | None:
    """None si la voz puede funcionar; si no, el motivo (para enseñárselo al usuario)."""
    try:
        import faster_whisper  # noqa: F401
        import sounddevice  # noqa: F401
    except ImportError:
        return ("faltan las librerías de voz: python -m pip install faster-whisper==1.2.1 "
                "sounddevice==0.5.6")
    if not (Path(RUTA_MODELO_VOZ) / "model.bin").is_file():
        return f"no encuentro el modelo de voz en {RUTA_MODELO_VOZ} (ver models/README.md)"
    return None


# --- Detección de cuándo has terminado de hablar ------------------------------------

class DetectorFin:
    """
    Recibe trozos de audio y dice cuándo parar: silencio después de hablar,
    nada de voz durante demasiado rato o el tope de duración.
    """

    def __init__(self, frecuencia: int, silencio_fin: float = VOZ_SILENCIO_FIN,
                 espera_sin_voz: float = VOZ_ESPERA_SIN_VOZ, max_segundos: float = VOZ_MAX_SEGUNDOS):
        self.frecuencia = frecuencia
        self.silencio_fin, self.espera_sin_voz, self.max_segundos = silencio_fin, espera_sin_voz, max_segundos
        self.tiempo = 0.0
        self.ruido: float | None = None
        self.ha_hablado = False
        self.silencio = 0.0
        self.motivo: str | None = None

    def umbral(self) -> float:
        return max(UMBRAL_VOZ_MIN, FACTOR_SOBRE_RUIDO * (self.ruido or 0.0))

    def nuevo_trozo(self, trozo: np.ndarray) -> bool:
        """True cuando hay que dejar de grabar (y `motivo` dice por qué)."""
        duracion = len(trozo) / self.frecuencia
        self.tiempo += duracion
        rms = float(np.sqrt(np.mean(np.square(trozo, dtype=np.float64)))) if len(trozo) else 0.0
        if self.tiempo <= SEGUNDOS_RUIDO:
            # Ruido de fondo: el trozo más bajo del principio (por si empiezas a hablar ya).
            self.ruido = rms if self.ruido is None else min(self.ruido, rms)
        if rms >= self.umbral():
            self.ha_hablado, self.silencio = True, 0.0
        else:
            self.silencio += duracion
        if self.ha_hablado and self.silencio >= self.silencio_fin:
            self.motivo = "silencio"
        elif not self.ha_hablado and self.tiempo >= self.espera_sin_voz:
            self.motivo = "sin_voz"
        elif self.tiempo >= self.max_segundos:
            self.motivo = "tope"
        return self.motivo is not None


def a_16k(audio: np.ndarray, frecuencia: int) -> np.ndarray:
    """Remuestrea a 16 kHz (lo que usa Whisper). Interpolación lineal: de sobra para voz."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if frecuencia == FRECUENCIA_WHISPER or len(audio) == 0:
        return audio
    n = int(round(len(audio) * FRECUENCIA_WHISPER / frecuencia))
    x_viejo = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    x_nuevo = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(x_nuevo, x_viejo, audio).astype(np.float32)


# --- Grabación -----------------------------------------------------------------------

Terminado = Callable[[np.ndarray | None, str], None]   # (audio a 16 kHz o None, motivo)


class Grabacion:
    """
    Una grabación del micrófono por defecto. `al_terminar(audio, motivo)` se
    llama UNA vez, desde otro hilo, con el audio a 16 kHz (None si no se
    pudo grabar o no hablaste). motivo: "boton", "silencio", "sin_voz",
    "tope", "panico" o "error: ...".
    """

    def __init__(self, al_terminar: Terminado):
        self._al_terminar = al_terminar
        self._trozos: list[np.ndarray] = []
        self._stream = None
        self._frecuencia = FRECUENCIA_WHISPER
        self._detector: DetectorFin | None = None
        self._motivo = "boton"
        self._lock = threading.Lock()
        self._terminada = False

    def iniciar(self) -> None:
        import sounddevice as sd
        dispositivo = sd.query_devices(kind="input")
        self._frecuencia = int(dispositivo["default_samplerate"])
        self._detector = DetectorFin(self._frecuencia)
        self._stream = sd.InputStream(samplerate=self._frecuencia, channels=1, dtype="float32",
                                      blocksize=int(self._frecuencia * 0.1), callback=self._trozo,
                                      finished_callback=self._fin)
        self._stream.start()
        log.debug("Escuchando el micrófono '%s' (%d Hz).", dispositivo["name"], self._frecuencia)

    def parar(self, motivo: str = "boton") -> None:
        """Termina la grabación (el botón otra vez). `al_terminar` llega igualmente."""
        self._motivo = motivo
        if self._stream is not None:
            threading.Thread(target=self._stream.stop, daemon=True).start()

    def _cerrar(self) -> None:
        try:
            if self._stream is not None:
                self._stream.close()
        except Exception:
            pass

    def _trozo(self, datos, frames, tiempo, estado) -> None:
        import sounddevice as sd
        trozo = datos[:, 0].copy()
        self._trozos.append(trozo)
        if control.en_pausa():
            self._motivo = "panico"
            raise sd.CallbackStop
        if self._detector.nuevo_trozo(trozo):
            self._motivo = self._detector.motivo
            raise sd.CallbackStop

    def _fin(self) -> None:
        with self._lock:
            if self._terminada:
                return
            self._terminada = True
        # Cerrar el stream desde su propio callback puede bloquear PortAudio: aparte.
        threading.Thread(target=self._cerrar, daemon=True).start()
        motivo = self._motivo
        hablo = self._detector is not None and self._detector.ha_hablado
        if motivo in ("panico", "sin_voz") or not self._trozos or (motivo == "boton" and not hablo):
            self._al_terminar(None, motivo if motivo != "boton" else "sin_voz")
            return
        audio = a_16k(np.concatenate(self._trozos), self._frecuencia)
        self._trozos.clear()
        self._al_terminar(audio, motivo)


# --- Transcripción --------------------------------------------------------------------

def limpiar_transcripcion(texto: str) -> str:
    """Quita la puntuación de los extremos y las frases que Whisper se inventa con el silencio."""
    texto = " ".join((texto or "").split())
    texto = re.sub(r"^[¿¡\s]+|[.!?…\s]+$", "", texto)
    from core.estado import normalizar
    if normalizar(texto).strip(" .!¡") in {normalizar(a).strip(" .!¡") for a in ALUCINACIONES}:
        return ""
    return texto


class Transcriptor:
    """Whisper en la CPU (int8). Se carga la primera vez que hace falta (~1-2 s)."""

    def __init__(self, ruta: Path = RUTA_MODELO_VOZ, idioma: str = VOZ_IDIOMA, hilos: int = VOZ_HILOS_CPU):
        self.ruta, self.idioma, self.hilos = Path(ruta), idioma, hilos
        self._modelo = None
        self._lock = threading.Lock()

    def cargar(self):
        with self._lock:
            if self._modelo is None:
                from faster_whisper import WhisperModel
                log.debug("Cargando el modelo de voz %s (CPU, int8)…", self.ruta.name)
                self._modelo = WhisperModel(str(self.ruta), device="cpu", compute_type="int8",
                                            cpu_threads=self.hilos, local_files_only=True)
            return self._modelo

    def precargar(self) -> None:
        """Carga el modelo en segundo plano (mientras hablas)."""
        threading.Thread(target=self.cargar, daemon=True).start()

    def transcribir(self, audio: np.ndarray) -> str:
        modelo = self.cargar()
        segmentos, _ = modelo.transcribe(audio, language=self.idioma, beam_size=5, vad_filter=True,
                                         condition_on_previous_text=False, initial_prompt=PISTA)
        return limpiar_transcripcion(" ".join(s.text.strip() for s in segmentos))
