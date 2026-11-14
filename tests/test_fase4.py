"""
Tests de la fase 4: expresiones de tiempo, agenda (tareas programadas),
memoria de órdenes parecidas y Steam (archivos VDF). Sin Windows ni Steam real.

    python -m pytest tests
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agenda import CANCELADA, FALLIDA, HECHA, PERDIDA, Agenda, Planificador  # noqa: E402
from core.agente import Agente  # noqa: E402
from core.memoria import MemoriaEjemplos, ejemplo_de, registrar_episodio  # noqa: E402
from core.router import Interpretacion  # noqa: E402
from core.skills.agenda import CancelarTarea, VerTareas, usar_agenda  # noqa: E402
from core.skills.base import Resultado, Skill  # noqa: E402
from core.skills.steam import buscar_juego, juegos_instalados, leer_vdf  # noqa: E402
from core.tiempo import separar_tiempo  # noqa: E402

AHORA = datetime(2026, 11, 14, 16, 0, 0)


# --- Expresiones de tiempo ------------------------------------------------------------

@pytest.mark.parametrize("frase, orden, cuando", [
    ("abre steam dentro de 5 min", "abre steam", AHORA + timedelta(minutes=5)),
    ("cierra google a las 17:30", "cierra google", AHORA.replace(hour=17, minute=30)),
    ("a las 17:30 cierra google", "cierra google", AHORA.replace(hour=17, minute=30)),
    ("cuelga la llamada en media hora", "cuelga la llamada", AHORA + timedelta(minutes=30)),
    ("abre discord en una hora y media", "abre discord", AHORA + timedelta(minutes=90)),
    ("mañana a las 9 abre discord", "abre discord", AHORA.replace(hour=9) + timedelta(days=1)),
    ("abre discord a las 5", "abre discord", AHORA.replace(hour=17)),       # las 5 de la mañana ya pasaron
    ("abre discord a las 8 de la tarde", "abre discord", AHORA.replace(hour=20)),
    ("programa abrir steam a las 9 y media", "abrir steam", AHORA.replace(hour=21, minute=30)),
])
def test_separar_tiempo(frase, orden, cuando):
    r = separar_tiempo(frase, AHORA)
    assert r is not None and r[0] == orden and r[1] == cuando


@pytest.mark.parametrize("frase", ["escribe hola en discord", "abre discord",
                                   "apunta que la cita es a las 5 y llevo papeles", "abre discord a las 25"])
def test_sin_expresion_de_tiempo(frase):
    assert separar_tiempo(frase, AHORA) is None


# --- Agenda y planificador ---------------------------------------------------------------

def test_agenda_ejecuta_a_su_hora_y_marca_perdidas(tmp_path):
    agenda = Agenda(tmp_path / "a.db")
    hechas = []
    planificador = Planificador(agenda, lambda t: (hechas.append(t.id) or True, "hecho"),
                                tolerancia=timedelta(minutes=10))
    vieja = agenda.programar("muy tarde", AHORA - timedelta(hours=3), {}, "x")
    ya = agenda.programar("ahora", AHORA - timedelta(seconds=5), {}, "x")
    luego = agenda.programar("luego", AHORA + timedelta(minutes=5), {}, "x")

    planificador.revisar(AHORA)
    assert hechas == [ya.id]
    assert agenda.obtener(vieja.id).estado == PERDIDA
    assert agenda.obtener(ya.id).estado == HECHA and agenda.obtener(ya.id).resultado == "hecho"
    assert [t.id for t in agenda.pendientes()] == [luego.id]

    planificador.revisar(AHORA)            # no se repite
    assert hechas == [ya.id]


def test_tarea_que_falla_o_lanza_excepcion(tmp_path):
    agenda = Agenda(tmp_path / "a.db")
    t1 = agenda.programar("falla", AHORA, {}, "x")
    Planificador(agenda, lambda t: (False, "no se pudo")).revisar(AHORA)
    t2 = agenda.programar("explota", AHORA, {}, "x")
    Planificador(agenda, lambda t: 1 / 0).revisar(AHORA)
    assert agenda.obtener(t1.id).estado == FALLIDA
    assert agenda.obtener(t2.id).estado == FALLIDA and "division" in agenda.obtener(t2.id).resultado


def test_skills_ver_y_cancelar(tmp_path):
    agenda = Agenda(tmp_path / "a.db")
    usar_agenda(agenda)
    a = agenda.programar("abre steam", datetime.now() + timedelta(minutes=5), {}, "x")
    b = agenda.programar("cierra discord", datetime.now() + timedelta(minutes=9), {}, "x")
    assert "abre steam" in VerTareas().ejecutar().mensaje
    assert CancelarTarea().ejecutar(tarea=str(a.id)).ok
    assert agenda.obtener(a.id).estado == CANCELADA
    assert CancelarTarea().ejecutar(tarea="la última").ok and agenda.obtener(b.id).estado == CANCELADA
    assert not CancelarTarea().ejecutar(tarea="7").ok


# --- Agente: programar órdenes -------------------------------------------------------------

class Abrir(Skill):
    nombre = "abrir_aplicacion"
    parametros = {"aplicacion": "app"}

    def __init__(self):
        self.abiertas = []

    def ejecutar(self, aplicacion=""):
        self.abiertas.append(aplicacion)
        return Resultado(True, f"{aplicacion} abierta", datos={"aplicacion": aplicacion})


class Nota(Skill):
    nombre = "crear_nota"
    parametros = {"contenido": "texto"}

    def ejecutar(self, contenido=""):
        return Resultado(True, "nota")


class RouterFalso:
    def interpretar(self, texto):
        if texto.startswith("abre "):
            return Interpretacion(texto, "abrir_aplicacion", 0.99, skill="abrir_aplicacion",
                                  params={"aplicacion": texto[5:]})
        if texto.startswith("apunta "):
            return Interpretacion(texto, "crear_nota", 0.99, skill="crear_nota", params={"contenido": texto[7:]})
        return Interpretacion(texto, "ninguna", 0.5, motivo_rechazo="no")


def _agente(tmp_path):
    abrir = Abrir()
    agente = Agente(router=RouterFalso(), registro={"abrir_aplicacion": abrir, "crear_nota": Nota()},
                    ruta_episodios=tmp_path / "e.jsonl", ruta_bd=tmp_path / "a.db")
    return agente, abrir


def test_programar_pide_confirmacion_y_no_ejecuta_ya(tmp_path):
    agente, abrir = _agente(tmp_path)
    preguntas = []
    r = agente.procesar("abre steam dentro de 5 min", confirmar=lambda d: preguntas.append(d) or True)
    assert r.ok and "#1" in r.mensaje and abrir.abiertas == []
    assert "programar para" in preguntas[0] and "abrir_aplicacion" in preguntas[0]
    tarea = agente.agenda.pendientes()[0]
    assert tarea.texto == "abre steam" and tarea.orden["params"] == {"aplicacion": "steam"}

    ok, mensaje = agente._ejecutar_tarea(tarea)   # lo que hará el planificador a su hora
    assert ok and abrir.abiertas == ["steam"]


def test_sin_confirmar_no_se_programa(tmp_path):
    agente, _ = _agente(tmp_path)
    r = agente.procesar("abre steam a las 17:30", confirmar=lambda d: False)
    assert not r.ok and agente.agenda.pendientes() == []


def test_la_hora_de_una_nota_es_contenido(tmp_path):
    agente, _ = _agente(tmp_path)
    interp = agente.interpretar("apunta que tengo dentista mañana a las 9")
    assert interp.programada is None and interp.skill == "crear_nota"
    assert "mañana a las 9" in interp.params["contenido"]


# --- Memoria de órdenes parecidas -----------------------------------------------------------

def test_memoria_devuelve_ordenes_parecidas_que_salieron_bien(tmp_path):
    ruta = tmp_path / "e.jsonl"
    registrar_episodio({"texto": "abre el bloc de notas", "skill": "abrir_aplicacion", "ok": True,
                        "parametros_interpretados": {"aplicacion": "bloc de notas"}}, ruta)
    registrar_episodio({"texto": "abre el paint", "skill": "abrir_aplicacion", "ok": False,
                        "parametros_interpretados": {"aplicacion": "paint"}}, ruta)          # falló
    registrar_episodio({"texto": "qué tiempo hace", "skill": None, "ok": False, "rechazada": True}, ruta)
    registrar_episodio({"texto": "abre el bloc de notas ya", "skill": "abrir_aplicacion", "ok": True,
                        "origen": "agenda", "parametros_interpretados": {"aplicacion": "x"}}, ruta)
    memoria = MemoriaEjemplos(ruta)
    parecidos = memoria.parecidos("ábreme el bloc de notas", 3)
    assert [e["frase"] for e in parecidos] == ["abre el bloc de notas"]
    assert parecidos[0]["pasos"] == [{"skill": "abrir_aplicacion", "parametros": {"aplicacion": "bloc de notas"}}]
    assert memoria.parecidos("cuéntame un chiste", 3) == []


def test_ejemplo_usa_lo_interpretado_no_lo_rellenado():
    episodio = {"texto": "escribe 3*3", "skill": "escribir_texto", "ok": True,
                "parametros": {"texto": "3*3", "aplicacion": "Calculadora"},   # rellenado con el contexto
                "parametros_interpretados": {"texto": "3*3"}}
    assert ejemplo_de(episodio)["pasos"][0]["parametros"] == {"texto": "3*3"}


# --- Steam ---------------------------------------------------------------------------------

def _steam(tmp_path) -> Path:
    raiz = tmp_path / "Steam"
    (raiz / "steamapps").mkdir(parents=True)
    (raiz / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % str(raiz).replace("\\", "\\\\"),
        encoding="utf-8")

    def manifiesto(appid, nombre, flags, build="1", objetivo="1"):
        (raiz / "steamapps" / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{nombre}"\n\t"StateFlags"\t\t"{flags}"\n'
            f'\t"installdir"\t\t"{nombre}"\n\t"buildid"\t\t"{build}"\n\t"TargetBuildID"\t\t"{objetivo}"\n}}\n',
            encoding="utf-8")
    manifiesto(730, "Counter-Strike 2", 4)
    manifiesto(105600, "Terraria", 6)
    manifiesto(1086940, "Baldur's Gate 3", 4, build="10", objetivo="11")
    manifiesto(228980, "Steamworks Common Redistributables", 4)
    return raiz


def test_vdf_anidado():
    datos = leer_vdf('"a"\n{\n\t"b"\t\t"1"\n\t"c"\n\t{\n\t\t"d"\t\t"C:\\\\x"\n\t}\n}')
    assert datos == {"a": {"b": "1", "c": {"d": "C:\\x"}}}


def test_juegos_y_actualizaciones(tmp_path):
    juegos = juegos_instalados(_steam(tmp_path))
    assert [j.nombre for j in juegos] == ["Baldur's Gate 3", "Counter-Strike 2", "Terraria"]
    assert [j.nombre for j in juegos if j.actualizacion_pendiente] == ["Baldur's Gate 3", "Terraria"]


@pytest.mark.parametrize("consulta, esperado", [
    ("cs2", "Counter-Strike 2"), ("counter strike", "Counter-Strike 2"),
    ("baldurs gate 3", "Baldur's Gate 3"), ("terraria", "Terraria"), ("hades", None),
])
def test_buscar_juego(tmp_path, consulta, esperado):
    encontrado = buscar_juego(consulta, juegos_instalados(_steam(tmp_path)))
    assert (encontrado.nombre if encontrado else None) == esperado
