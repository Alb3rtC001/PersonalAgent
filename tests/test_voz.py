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


@pytest.mark.parametrize("dicho, que", [
    ("Enviar.", "enviar"),
    ("Enter", "enviar"),
    ("Enviad", "enviar"),
    ("Intro.", "enviar"),
    ("Envíalo", "enviar"),
    ("Vale, envíalo.", "enviar"),
    ("Sí, envíalo, por favor.", "enviar"),
    ("Vale.", "enviar"),
    ("Cancelar.", "cancelar"),
    ("Sí, bórralo.", "cancelar"),
    ("Sí.", "dudoso"),
    ("OK", "dudoso"),
    ("Envía un correo a Juan", None),          # otra orden, no una confirmación
    ("Abre Steam", None),
    ("Cancela la descarga de Steam", None),
    ("", None),
])
def test_confirmacion(dicho, que):
    assert voz.confirmacion(dicho) == que


def test_grabacion_descartada_no_da_audio():
    resultados = []
    g = voz.Grabacion(al_terminar=lambda audio, motivo: resultados.append((audio, motivo)), espera_sin_voz=6)
    g._detector = voz.DetectorFin(F)
    g._detector.ha_hablado = True
    g._trozos = voz_alta(1)
    g._motivo = "descartar"
    g._fin()
    assert resultados == [(None, "descartar")]


def test_al_dictar_las_pausas_no_cortan_antes_del_minimo():
    d = voz.DetectorFin(F, silencio_fin=1.5, espera_sin_voz=8, max_segundos=30, min_segundos=10)
    # Hablas 2 s y te callas: no termina hasta los 10 s (y entonces sí).
    parado_en = alimentar(d, silencio(0.5) + voz_alta(2) + silencio(12))
    assert d.motivo == "silencio" and parado_en == 100


def test_sin_minimo_termina_al_callarse():
    d = voz.DetectorFin(F, silencio_fin=1.5, espera_sin_voz=8, max_segundos=30, min_segundos=0)
    assert alimentar(d, silencio(0.5) + voz_alta(1) + silencio(3)) == 30


# --- Ventanas de seguridad de palabra (con código) -----------------------------------

CODIGO = "código romeo"


@pytest.mark.parametrize("dicho, resto", [
    ("Código Romeo, sí.", "sí"),
    ("código, romeo", ""),
    ("Codigo Romero. La dos.", "La dos"),
    ("Vale, código Romeo, no", "no"),
    ("Sí.", None),
    ("Romeo", None),
    ("", None),
])
def test_quitar_codigo(dicho, resto):
    assert voz.quitar_codigo(dicho, CODIGO) == resto


@pytest.mark.parametrize("dicho, valor", [
    ("Sí", True), ("Vale, adelante.", True), ("Sí, por favor", True), ("Confirmo", True),
    ("No", False), ("No lo hagas", False), ("Cancela", False),
    ("Quizás", None), ("", None),
])
def test_respuesta_si_no(dicho, valor):
    assert voz.respuesta_si_no(dicho) == valor


def test_en_cifras():
    assert voz.en_cifras("La dos.") == "La 2"
    assert voz.en_cifras("Uno") == "1"
    assert voz.en_cifras("la de YouTube") == "la de YouTube"


def test_responder_de_palabra_exige_el_codigo():
    assert voz.responder_de_palabra("Sí", CODIGO, False, "si_no") == ("sin_codigo", None, False)
    assert voz.responder_de_palabra("Código Romeo, sí", CODIGO, False, "si_no") == ("respuesta", True, True)
    assert voz.responder_de_palabra("Código Romeo, no", CODIGO, False, "si_no") == ("respuesta", False, True)
    assert voz.responder_de_palabra("Código Romeo, la tres", CODIGO, False, "texto") == ("respuesta", "la 3", True)


def test_responder_de_palabra_en_dos_veces():
    estado, _, autorizado = voz.responder_de_palabra("Código Romeo.", CODIGO, False, "si_no")
    assert (estado, autorizado) == ("codigo", True)
    assert voz.responder_de_palabra("Quizás", CODIGO, autorizado, "si_no") == ("no_entiendo", None, True)
    assert voz.responder_de_palabra("Sí", CODIGO, autorizado, "si_no") == ("respuesta", True, True)


def test_sin_codigo_configurado_no_se_acepta_nada():
    assert voz.responder_de_palabra("Sí", "", False, "si_no")[0] == "sin_codigo"


def test_codigo_seguridad_del_archivo(tmp_path):
    ruta = tmp_path / "codigo_voz.txt"
    assert voz.codigo_seguridad(ruta, "código romeo") == "código romeo"
    ruta.write_text("# mi código\nclave tango\n", encoding="utf-8")
    assert voz.codigo_seguridad(ruta, "código romeo") == "clave tango"


def test_dictado_con_los_valores_de_config_corta_a_los_3_s_de_silencio():
    from config import VOZ_MIN_SEGUNDOS, VOZ_SILENCIO_FIN
    assert (VOZ_MIN_SEGUNDOS, VOZ_SILENCIO_FIN) == (0, 3)
    d = voz.DetectorFin(F)                         # los valores de config.py
    # Pausa de 2 s para pensar: sigue escuchando; luego 3 s callado: corta.
    parado_en = alimentar(d, silencio(0.5) + voz_alta(1) + silencio(2) + voz_alta(1) + silencio(5))
    assert d.motivo == "silencio" and parado_en == 5 + 10 + 20 + 10 + 30


def test_la_confirmacion_corta_antes():
    resultados = []
    g = voz.Grabacion(al_terminar=lambda a, m: resultados.append(m), min_segundos=0,
                      silencio_fin=voz.VOZ_SILENCIO_FIN_RESPUESTA)
    assert g._silencio_fin == 1 < voz.VOZ_SILENCIO_FIN
