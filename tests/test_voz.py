"""
Tests de la voz (core/voz.py) sin micrófono ni modelo: cuándo termina una
grabación, el remuestreo a 16 kHz y la limpieza del texto reconocido.

    python -m pytest tests
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import voz  # noqa: E402

F = 16000
TROZO = int(F * 0.1)


def silencio(segundos, nivel=0.002):
    return [np.full(TROZO, nivel, dtype=np.float32) for _ in range(int(segundos * 10))]


def voz_alta(segundos, nivel=0.2):
    t = np.arange(TROZO) / F
    return [(nivel * np.sin(2 * np.pi * 220 * t)).astype(np.float32) for _ in range(int(segundos * 10))]


def alimentar(detector, trozos):
    for i, trozo in enumerate(trozos):
        if detector.nuevo_trozo(trozo):
            return i + 1
    return None


def test_termina_al_callarse_despues_de_hablar():
    d = voz.DetectorFin(F, silencio_fin=1.5, espera_sin_voz=8, max_segundos=30)
    trozos = silencio(0.5) + voz_alta(2) + silencio(3)
    parado_en = alimentar(d, trozos)
    assert d.motivo == "silencio" and d.ha_hablado
    assert parado_en == 5 + 20 + 15          # justo tras 1,5 s de silencio


def test_las_pausas_cortas_no_cortan_la_frase():
    d = voz.DetectorFin(F, silencio_fin=1.5, espera_sin_voz=8, max_segundos=30)
    assert alimentar(d, silencio(0.5) + voz_alta(1) + silencio(0.8) + voz_alta(1)) is None


def test_si_no_hablas_deja_de_escuchar():
    d = voz.DetectorFin(F, silencio_fin=1.5, espera_sin_voz=3, max_segundos=30)
    assert alimentar(d, silencio(5)) == 30 and d.motivo == "sin_voz" and not d.ha_hablado


def test_tope_de_duracion():
    d = voz.DetectorFin(F, silencio_fin=1.5, espera_sin_voz=8, max_segundos=2)
    assert alimentar(d, voz_alta(5)) == 20 and d.motivo == "tope"


def test_el_ruido_de_fondo_no_cuenta_como_voz():
    # Un ventilador constante (más alto que el umbral mínimo) no es hablar.
    d = voz.DetectorFin(F, silencio_fin=1.5, espera_sin_voz=3, max_segundos=30)
    assert alimentar(d, silencio(5, nivel=0.02)) is not None and d.motivo == "sin_voz"


def test_a_16k():
    audio = np.zeros(44100, dtype=np.float32)        # 1 s a 44,1 kHz
    assert len(voz.a_16k(audio, 44100)) == 16000
    assert voz.a_16k(audio[:16000], 16000) is not None and len(voz.a_16k(audio[:16000], 16000)) == 16000


@pytest.mark.parametrize("crudo, limpio", [
    ("  Abre Steam.", "Abre Steam"),
    ("¿Qué pone en la calculadora?", "Qué pone en la calculadora"),
    ("Abre Chrome, busca recetas.", "Abre Chrome, busca recetas"),
    ("Subtítulos realizados por la comunidad de Amara.org", ""),
    ("¡Gracias por ver el video!", ""),
    ("", ""),
])
def test_limpiar_transcripcion(crudo, limpio):
    assert voz.limpiar_transcripcion(crudo) == limpio


def test_grabacion_sin_hablar_no_da_audio():
    resultados = []
    g = voz.Grabacion(al_terminar=lambda audio, motivo: resultados.append((audio, motivo)))
    g._detector = voz.DetectorFin(F)
    g._trozos = silencio(1)
    g._fin()
    g._fin()                                           # solo avisa una vez
    assert resultados == [(None, "sin_voz")]


def test_grabacion_con_voz_da_audio_a_16k():
    resultados = []
    g = voz.Grabacion(al_terminar=lambda audio, motivo: resultados.append((audio, motivo)))
    g._frecuencia = 32000
    g._detector = voz.DetectorFin(32000)
    g._detector.ha_hablado = True
    g._trozos = [np.zeros(3200, dtype=np.float32)] * 10   # 1 s a 32 kHz
    g._motivo = "silencio"
    g._fin()
    audio, motivo = resultados[0]
    assert motivo == "silencio" and len(audio) == 16000 and audio.dtype == np.float32
