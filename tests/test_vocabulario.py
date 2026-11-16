"""
Tests del vocabulario de la voz (core/vocabulario.py): nombres propios que
Whisper escribe "a la española" se corrigen por cómo suenan.

    python -m pytest tests
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import vocabulario  # noqa: E402
from core.atajos import completar_enter  # noqa: E402

NOMBRES = ["Steam", "Discord", "Spotify", "Slay the Spire 2", "Hades", "Counter-Strike 2", "Opera",
           "Baldur's Gate 3", "Hollow Knight: Silksong", "Biblioteca", "JUGAR", "YouTube"]


@pytest.mark.parametrize("oido, corregido", [
    ("Abre Estim y busca slay de spire 2", "Abre Steam y busca Slay the Spire 2"),
    ("abre diskord", "abre Discord"),
    ("pon espotifai", "pon Spotify"),
    ("PonsPortify", "Pon Spotify"),
    ("Abre Valdur's GAT3", "Abre Baldur's Gate 3"),
    ("abre el contraestrike 2", "abre el Counter-Strike 2"),
    ("Quiero jugar a Halo Night Silkson", "Quiero jugar a Hollow Knight: Silksong"),
    ("abre steam, porfa", "abre Steam, porfa"),
])
def test_corrige_nombres(oido, corregido):
    assert vocabulario.corregir(oido, NOMBRES) == corregido


@pytest.mark.parametrize("frase", [
    "dale a jugar",
    "abre la calculadora y escribe 2 más 2",
    "pon la radio",
    "la puerta",
    "abre el bloc de notas",
    "busca recetas de pasta",
])
def test_no_toca_lo_corriente(frase):
    assert vocabulario.corregir(frase, NOMBRES) == frase


def test_pista_no_se_pasa_de_largo():
    muchos = [f"Juego número {i}" for i in range(200)]
    pista = vocabulario.pista("Órdenes.", muchos)
    assert pista.startswith("Órdenes. Nombres: Juego número 0")
    assert len(pista) <= vocabulario.MAX_CARACTERES_PISTA


def test_nombres_propios_del_archivo_van_primero(tmp_path):
    ruta = tmp_path / "vocabulario_voz.txt"
    ruta.write_text("# contactos\nAitana\n\nCanal General\n", encoding="utf-8")
    lista = vocabulario.nombres(ruta)
    assert lista[:2] == ["Aitana", "Canal General"]


# --- El Enter que falta tras escribir en la barra de direcciones -----------------------

ATAJOS = {
    "Opera": {"nombres": ["opera"], "atajos": {
        "nueva pestaña": "control t",
        "ir a la barra de direcciones (para buscar: después escribir la búsqueda y pulsar enter)": "control l"}},
}


def test_busqueda_sin_enter_se_completa():
    pasos = [("pulsar_teclas", {"teclas": "control l", "aplicacion": "opera"}),
             ("escribir_texto", {"texto": "musica", "aplicacion": "opera"})]
    assert completar_enter(pasos, ATAJOS) == pasos + [("pulsar_teclas", {"teclas": "enter", "aplicacion": "opera"})]


def test_busqueda_con_enter_no_se_toca():
    pasos = [("pulsar_teclas", {"teclas": "ctrl+l", "aplicacion": "opera"}),
             ("escribir_texto", {"texto": "musica"}),
             ("pulsar_teclas", {"teclas": "intro"})]
    assert completar_enter(pasos, ATAJOS) == pasos


def test_atajos_sin_enter_no_se_tocan():
    pasos = [("pulsar_teclas", {"teclas": "control t", "aplicacion": "opera"}),
             ("escribir_texto", {"texto": "youtube"})]
    assert completar_enter(pasos, ATAJOS) == pasos
