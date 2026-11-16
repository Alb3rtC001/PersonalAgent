"""
Voz → texto, 100 % local (botón del micrófono de la interfaz).

- Grabacion: graba del micrófono por defecto (sounddevice) hasta que pulsas
  otra vez el botón, te callas un momento después de hablar
  (VOZ_SILENCIO_FIN, pero no antes de VOZ_MIN_SEGUNDOS) o se llega al tope (VOZ_MAX_SEGUNDOS). Si no se oye
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
from typing import Any, Callable

import numpy as np

from config import (
    RUTA_DATOS,
    RUTA_MODELO_VOZ,
    VOZ_CODIGO_SEGURIDAD,
    VOZ_ESPERA_SIN_VOZ,
    VOZ_HILOS_CPU,
    VOZ_IDIOMA,
    VOZ_MAX_SEGUNDOS,
    VOZ_MIN_SEGUNDOS,
    VOZ_SILENCIO_FIN,
    VOZ_SILENCIO_FIN_RESPUESTA,
)
from core import control, vocabulario

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
    except ImportError as e:
        # Se dice qué Python es: si el agente se arranca con otro (el del sistema en
        # vez del .venv), la instalación tiene que ir a ese.
        import sys
        return (f"faltan las librerías de voz en el Python que está usando el agente ({sys.executable}; "
                f"{e}). Instálalas en ese: \"{sys.executable}\" -m pip install faster-whisper==1.2.1 "
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
                 espera_sin_voz: float = VOZ_ESPERA_SIN_VOZ, max_segundos: float = VOZ_MAX_SEGUNDOS,
                 min_segundos: float = 0.0):
        self.frecuencia = frecuencia
        self.min_segundos = min_segundos      # antes de esto, callarse no termina
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
        if self.ha_hablado and self.silencio >= self.silencio_fin and self.tiempo >= self.min_segundos - 1e-6:
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

    def __init__(self, al_terminar: Terminado, espera_sin_voz: float = VOZ_ESPERA_SIN_VOZ,
                 min_segundos: float = VOZ_MIN_SEGUNDOS, silencio_fin: float = VOZ_SILENCIO_FIN):
        self._al_terminar = al_terminar
        self._espera_sin_voz = espera_sin_voz
        self._min_segundos = min_segundos
        self._silencio_fin = silencio_fin
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
        self._detector = DetectorFin(self._frecuencia, espera_sin_voz=self._espera_sin_voz,
                                     min_segundos=self._min_segundos, silencio_fin=self._silencio_fin)
        self._stream = sd.InputStream(samplerate=self._frecuencia, channels=1, dtype="float32",
                                      blocksize=int(self._frecuencia * 0.1), callback=self._trozo,
                                      finished_callback=self._fin)
        self._stream.start()
        log.debug("Escuchando el micrófono '%s' (%d Hz).", dispositivo["name"], self._frecuencia)

    def parar(self, motivo: str = "boton") -> None:
        """
        Termina la grabación (el botón otra vez). `al_terminar` llega igualmente;
        con motivo "descartar" llega sin audio (lo grabado no se quiere).
        """
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
        if motivo in ("panico", "sin_voz", "descartar") or not self._trozos or (motivo == "boton" and not hablo):
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


# Lo que puedes decir (solo eso, sin más palabras) cuando ya hay una orden dictada
# en el cuadro. "envía un correo a Juan" no cuenta: es otra orden, no una confirmación.
DECIR_ENVIAR = {
    "enviar", "enviado", "envia", "envialo", "envialo ya", "enviala", "enviarlo", "enviarla",
    "enviad", "envie", "envio", "enviat",          # cómo oye Whisper a veces un "enviar" suelto
    "enter", "intro", "manda", "mandar", "mandalo",
    "ejecutar", "ejecuta", "ejecutalo", "adelante", "hazlo", "dale", "vale",
}   # "sí" u "ok" sueltos no: un "sí" de fondo (otra conversación, la tele) no debe mandar nada
DECIR_CANCELAR = {"no", "cancelamos", "cancelar", "cancela", "cancelalo", "borrar", "borra", "borralo", "olvidalo", "dejalo"}
RELLENO_CONFIRMACION = {"vale", "si", "ok", "okay", "pues", "venga", "ya", "por favor", "porfa"}


def confirmacion(texto: str) -> str | None:
    """
    "enviar" o "cancelar" si lo dicho es solo una confirmación ("Enviar.",
    "Vale, envíalo", "Enter"); "dudoso" si solo es un "sí" u "ok" suelto; None
    si es otra cosa (una orden nueva).
    """
    from core.estado import normalizar
    palabras = re.sub(r"[^\w\s]", " ", normalizar(texto)).split()
    if not palabras:
        return None
    frase = " ".join(palabras)
    for decir, que in ((DECIR_CANCELAR, "cancelar"), (DECIR_ENVIAR, "enviar")):
        if frase in decir:
            return que
    # Muletillas delante o detrás: "vale, envíalo", "envíalo por favor", "sí, cancela".
    resto = frase
    for relleno in sorted(RELLENO_CONFIRMACION, key=len, reverse=True):
        resto = re.sub(rf"(^| ){relleno}(?= |$)", " ", resto)
    resto = " ".join(resto.split())
    if not resto:
        return "dudoso"          # solo "sí", "ok"…: ni orden nueva ni confirmación clara
    if resto in DECIR_CANCELAR:
        return "cancelar"
    if resto in DECIR_ENVIAR:
        return "enviar"
    return None


# --- Contestar ventanas de seguridad de palabra (con código) -----------------------

RUTA_CODIGO = RUTA_DATOS / "codigo_voz.txt"
UMBRAL_CODIGO = 0.8
DECIR_SI = {"si", "vale", "confirmo", "confirmar", "acepto", "aceptar", "adelante", "correcto", "hazlo",
            "de acuerdo", "claro", "afirmativo", "continua", "continuar", "ok", "okay"}
DECIR_NO = {"no", "cancela", "cancelar", "para", "niego", "negativo", "rechazo", "rechazar", "no lo hagas",
            "mejor no", "deten", "detener"}
CIFRAS = {"uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6",
          "siete": "7", "ocho": "8", "nueve": "9", "diez": "10"}


def codigo_seguridad(ruta: Path = RUTA_CODIGO, por_defecto: str = VOZ_CODIGO_SEGURIDAD) -> str:
    """El código para contestar de palabra: el de data/codigo_voz.txt o el de config.py ("" = desactivado)."""
    try:
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip() and not linea.lstrip().startswith("#"):
                return linea.strip()
    except OSError:
        pass
    return (por_defecto or "").strip()


def _palabras(texto: str) -> list[str]:
    from core.estado import normalizar
    return re.sub(r"[^\w\s]", " ", normalizar(texto)).split()


def quitar_codigo(texto: str, codigo: str) -> str | None:
    """
    Lo que va detrás del código ("código Romeo, sí" → "sí"; solo el código → "").
    None si no se ha dicho el código. Se compara por cómo suena: "Código Romeo",
    "código, romeo" o "codigo romero" valen.
    """
    from core.vocabulario import _parecido, clave
    palabras, objetivo = texto.split(), clave(codigo)
    n = len(codigo.split())
    if not objetivo or not palabras:
        return None
    for tam in (n, n + 1, n - 1):
        for i in range(0, len(palabras) - tam + 1) if tam > 0 else ():
            c = clave(" ".join(palabras[i:i + tam]))
            if c == objetivo or _parecido(c, objetivo) >= UMBRAL_CODIGO:
                resto = " ".join(palabras[i + tam:])
                return re.sub(r"^[\s,.;:!¡?¿-]+|[\s.!?…]+$", "", resto)
    return None


def respuesta_si_no(texto: str) -> bool | None:
    """True ("sí", "vale, adelante"), False ("no", "cancela") o None si no está claro."""
    frase = " ".join(_palabras(texto))
    if not frase:
        return None
    if frase in DECIR_NO or frase.split()[0] == "no":
        return False
    if frase in DECIR_SI or all(p in DECIR_SI or p in {"por", "favor", "porfa", "lo"} for p in frase.split()):
        return True
    return None


def en_cifras(texto: str) -> str:
    """"La dos." → "La 2", "Uno" → "1" (así lo entiende la elección de opciones); el resto, tal cual."""
    from core.estado import normalizar
    palabras = [CIFRAS.get(re.sub(r"[^\w]", "", normalizar(p)), p) for p in texto.split()]
    return re.sub(r"[\s.!?…]+$", "", " ".join(palabras))


def responder_de_palabra(texto: str, codigo: str, autorizado: bool, tipo: str) -> tuple[str, Any, bool]:
    """
    Lo que se ha dicho delante de una ventana de seguridad → (estado, valor, autorizado).
    estado: "sin_codigo" (no vale: falta el código), "codigo" (dicho el código; falta
    la respuesta), "no_entiendo" o "respuesta" (valor: True/False si tipo es
    "si_no", o el texto con los números en cifras si es "texto"). Dicho el código
    una vez, lo siguiente vale sin repetirlo.
    """
    resto = quitar_codigo(texto, codigo) if codigo else None
    if resto is None and not autorizado:
        return "sin_codigo", None, False
    respuesta = texto if resto is None else resto
    if not respuesta.strip():
        return "codigo", None, True
    if tipo == "si_no":
        valor = respuesta_si_no(respuesta)
        return ("no_entiendo", None, True) if valor is None else ("respuesta", valor, True)
    return "respuesta", en_cifras(respuesta), True


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
        conocidos = vocabulario.nombres()
        segmentos, _ = modelo.transcribe(audio, language=self.idioma, beam_size=5, vad_filter=True,
                                         condition_on_previous_text=False,
                                         initial_prompt=vocabulario.pista(PISTA, conocidos))
        texto = limpiar_transcripcion(" ".join(s.text.strip() for s in segmentos))
        # Nombres propios que aun así salen "a la española" (Estim → Steam).
        return vocabulario.corregir(texto, conocidos)
