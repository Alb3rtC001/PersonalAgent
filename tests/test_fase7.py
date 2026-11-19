"""
Tests de la fase 7 (aprendizaje continuo): frases aprendidas de los episodios,
reentreno que solo cambia el modelo si no empeora, propuestas de órdenes
compuestas y la skill que las ejecuta. Todo con archivos temporales.

    python -m pytest tests
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from aprendizaje import datos, propuestas, reentrenar  # noqa: E402
from core.skills.base import Resultado, Skill  # noqa: E402
from core.skills.compuesta import SkillCompuesta, cargar_compuestas, crear_compuesta, pasos_hechos  # noqa: E402


def ep(texto, skill, ok=True, origen="llm", momento="2026-11-20T10:00:00", **extra):
    return {"texto": texto, "skill": skill, "ok": ok, "origen": origen, "momento": momento, **extra}


# --- Frases aprendidas -------------------------------------------------------------------

def test_solo_se_aprende_lo_que_salio_bien_y_no_sabia_el_clasificador():
    episodios = [
        ep("pon el elden ring desde steam", "ejecutar_en_steam"),                 # sí
        ep("abre steam", "abrir_aplicacion", origen="clasificador"),              # ya lo sabía
        ep("dale a jugar", "hacer_clic", ok=False),                               # salió mal
        ep("busca X en opera", "varios_pasos"),                                   # varios pasos
        ep("hazme algo", None, ok=False, rechazada=True),                         # no entendida
        ep("pulsa jugar en steam", "hacer_clic", ok=False, corregido="éxito falso"),
        ep("Pon el Elden Ring desde Steam.", "ejecutar_en_steam"),                # repetida
    ]
    assert datos.frases_de_episodios(episodios) == [("Pon el Elden Ring desde Steam.", "ejecutar_en_steam")]


def test_si_luego_salio_mal_no_se_aprende():
    episodios = [ep("lanza hades", "ejecutar_en_steam"), ep("lanza hades", "ejecutar_en_steam", ok=False)]
    assert datos.frases_de_episodios(episodios) == []


def test_no_repite_las_que_ya_estan_en_el_dataset():
    assert datos.frases_de_episodios([ep("abre steam", "abrir_aplicacion")], {"abre steam"}) == []


def test_frases_rechazadas():
    episodios = [ep("haz magia", None, ok=False, rechazada=True), ep("haz magia", None, ok=False, rechazada=True),
                 ep("vuela", None, ok=False, rechazada=True)]
    assert datos.frases_rechazadas(episodios) == ["vuela", "haz magia"]


def test_actualizar_aprendidas(tmp_path):
    episodios = tmp_path / "episodios.jsonl"
    episodios.write_text(json.dumps(ep("pon el elden ring desde steam", "ejecutar_en_steam")) + "\n",
                         encoding="utf-8")
    ruta = tmp_path / "aprendidas.json"
    todas, nuevas = datos.actualizar_aprendidas([("abre steam", "abrir_aplicacion")], episodios, ruta)
    assert nuevas == todas == [("pon el elden ring desde steam", "ejecutar_en_steam")]
    assert datos.actualizar_aprendidas([], episodios, ruta)[1] == []       # la segunda vez, nada nuevo
    assert datos.cargar_aprendidas(ruta) == todas


# --- Reentreno: solo si no empeora ---------------------------------------------------------

def test_medida_no_peor_que():
    M = reentrenar.Medida
    assert M(40, 0, 79).no_peor_que(M(39, 0, 79))
    assert not M(41, 1, 79).no_peor_que(M(39, 0, 79))        # más aciertos, pero uno seguro y mal
    assert not M(38, 0, 79).no_peor_que(M(39, 0, 79))


def test_sin_aprendidas_se_entrena_el_mismo_modelo(tmp_path):
    """Con el mismo procedimiento que nlu/training.py: si no hay nada aprendido, nada cambia."""
    from nlu.dataset import cargar_dataset
    base = cargar_dataset()
    ordenes = json.loads(reentrenar.RUTA_ORDENES.read_text(encoding="utf-8"))
    reentrenar.entrenar(base, [], tmp_path / "m.pt", tmp_path / "v.json")
    nuevo = reentrenar.medir(tmp_path / "m.pt", tmp_path / "v.json", ordenes)
    actual = reentrenar.medir(None, None, ordenes)
    assert (nuevo.aciertos, nuevo.seguras_mal) == (actual.aciertos, actual.seguras_mal)


@pytest.fixture
def nlu_temporal(tmp_path):
    """Una copia de nlu/ (dataset, modelo y vocabulario) para reentrenar sin tocar el de verdad."""
    raiz = Path(__file__).parent.parent / "nlu"
    destino = tmp_path / "nlu"
    destino.mkdir()
    for nombre in ("dataset.json", "modelo.pt", "vocabulary.json"):
        shutil.copy2(raiz / nombre, destino / nombre)
    return destino


def test_reentrenar_no_cambia_el_modelo_si_empeora(tmp_path, nlu_temporal, monkeypatch):
    episodios = tmp_path / "episodios.jsonl"
    episodios.write_text(json.dumps(ep("abre discord ahora mismo porfa", "ejecutar_en_steam")) + "\n",
                         encoding="utf-8")
    medidas = iter([reentrenar.Medida(39, 0, 79), reentrenar.Medida(38, 0, 79)])
    monkeypatch.setattr(reentrenar, "medir", lambda m, v, o: next(medidas))
    antes = (nlu_temporal / "modelo.pt").read_bytes()
    informe = reentrenar.reentrenar(ruta_episodios=episodios, ruta_aprendidas=tmp_path / "a.json",
                                    dir_nlu=nlu_temporal)
    assert not informe.cambiado and "no mejora" in informe.texto()
    assert (nlu_temporal / "modelo.pt").read_bytes() == antes


def test_reentrenar_sin_nada_que_aprender(tmp_path, nlu_temporal):
    episodios = tmp_path / "episodios.jsonl"
    episodios.write_text("", encoding="utf-8")
    informe = reentrenar.reentrenar(ruta_episodios=episodios, ruta_aprendidas=tmp_path / "a.json",
                                    dir_nlu=nlu_temporal)
    assert informe.despues is None and not informe.cambiado and "Nada nuevo" in informe.texto()


def test_reentrenar_cambia_el_modelo_si_mejora(tmp_path, nlu_temporal, monkeypatch):
    episodios = tmp_path / "episodios.jsonl"
    episodios.write_text(json.dumps(ep("pon el elden ring desde steam", "ejecutar_en_steam")) + "\n",
                         encoding="utf-8")
    medidas = iter([reentrenar.Medida(39, 0, 79), reentrenar.Medida(40, 0, 79)])
    monkeypatch.setattr(reentrenar, "medir", lambda m, v, o: next(medidas))
    informe = reentrenar.reentrenar(ruta_episodios=episodios, ruta_aprendidas=tmp_path / "a.json",
                                    dir_nlu=nlu_temporal)
    assert informe.cambiado and (nlu_temporal / "modelo.pt.anterior").exists()


# --- Propuestas de órdenes compuestas ---------------------------------------------------------

def plan(texto, buscar, momento):
    return ep(texto, "varios_pasos", momento=momento, pasos_orden=[
        ["pulsar_teclas", {"teclas": "control l", "aplicacion": "opera"}],
        ["escribir_texto", {"texto": buscar, "aplicacion": "opera"}],
        ["pulsar_teclas", {"teclas": "enter", "aplicacion": "opera"}]])


def test_plan_repetido_con_un_valor_que_cambia_es_un_parametro():
    episodios = [plan(f"busca {x} en opera", x, f"2026-11-2{i}T10:00:00")
                 for i, x in enumerate(["recetas", "el tiempo", "noticias"])]
    [p] = propuestas.proponer(episodios)
    assert p.veces == 3 and p.tipo == "plan" and p.parametros.keys() == {"p1"}
    assert p.pasos[1] == ("escribir_texto", {"texto": "{p1}", "aplicacion": "opera"})
    assert p.pasos[0][1]["teclas"] == "control l"


def test_lo_que_se_repite_menos_de_tres_veces_no_se_propone():
    assert propuestas.proponer([plan("busca a en opera", "a", "2026-11-20T10:00:00"),
                                plan("busca b en opera", "b", "2026-11-21T10:00:00")]) == []


def seguidas(dia):
    return [ep("abre steam", "abrir_aplicacion", momento=f"2026-11-{dia}T10:00:00",
               parametros={"aplicacion": "steam"}),
            ep("ve a la biblioteca", "hacer_clic", momento=f"2026-11-{dia}T10:00:30",
               parametros={"elemento": "Biblioteca", "aplicacion": "steam"})]


def test_ordenes_seguidas_repetidas():
    [p] = propuestas.proponer(seguidas(20) + seguidas(21) + seguidas(22))
    assert p.tipo == "seguidas" and [s for s, _ in p.pasos] == ["abrir_aplicacion", "hacer_clic"]


def test_abrir_y_cerrar_la_misma_app_no_es_una_costumbre():
    episodios = []
    for dia in (20, 21, 22):
        episodios += [ep("abre la calculadora", "abrir_aplicacion", momento=f"2026-11-{dia}T10:00:00",
                         parametros={"aplicacion": "calculadora"}),
                      ep("cierra la calculadora", "cerrar_aplicacion", momento=f"2026-11-{dia}T10:00:10",
                         parametros={"aplicacion": "calculadora"})]
    assert propuestas.proponer(episodios) == []


def test_ya_creada_no_se_vuelve_a_proponer(tmp_path):
    episodios = seguidas(20) + seguidas(21) + seguidas(22)
    [p] = propuestas.proponer(episodios)
    crear_compuesta("ir a la biblioteca", p, tmp_path)
    assert propuestas.proponer(episodios, pasos_hechos(tmp_path)) == []


# --- La orden compuesta como skill ------------------------------------------------------------

class Apuntar(Skill):
    def __init__(self, nombre, riesgo="bajo", falla=False, hechas=None):
        self.nombre, self.riesgo, self.falla, self.hechas = nombre, riesgo, falla, hechas
        self.descripcion = nombre
        self.parametros = {"texto": "texto"}

    def ejecutar(self, **params):
        self.hechas.append((self.nombre, params))
        return Resultado(not self.falla, "falló" if self.falla else "hecho")


def test_compuesta_ejecuta_sus_pasos_con_el_parametro(tmp_path):
    hechas = []
    registro = {"escribir": Apuntar("escribir", hechas=hechas), "pulsar": Apuntar("pulsar", "alto", hechas=hechas)}
    datos_ = {"nombre": "buscar", "parametros": {"p1": "qué buscar"},
              "pasos": [["escribir", {"texto": "{p1}"}], ["pulsar", {"texto": "enter"}]]}
    skill = SkillCompuesta(datos_, registro)
    assert skill.riesgo == "alto" and skill.interpretar_con_llm
    import core.skills.compuesta as compuesta
    compuesta.PAUSA_ENTRE_PASOS = 0
    r = skill.ejecutar(p1="recetas")
    assert r.ok and hechas == [("escribir", {"texto": "recetas"}), ("pulsar", {"texto": "enter"})]


def test_compuesta_para_en_el_paso_que_falla():
    hechas = []
    registro = {"a": Apuntar("a", falla=True, hechas=hechas), "b": Apuntar("b", hechas=hechas)}
    skill = SkillCompuesta({"nombre": "x", "pasos": [["a", {"texto": "1"}], ["b", {"texto": "2"}]]}, registro)
    r = skill.ejecutar()
    assert not r.ok and "paso 1 de 2" in r.mensaje and [n for n, _ in hechas] == ["a"]


def test_crear_y_cargar_compuesta(tmp_path):
    p = propuestas.Propuesta([("abrir_aplicacion", {"aplicacion": "steam"})], {}, 3, ["abre steam"])
    archivo = crear_compuesta("Abrir Steam ya", p, tmp_path)
    assert archivo.name == "abrir_steam_ya.json"
    [skill] = cargar_compuestas(tmp_path)
    assert skill.nombre == "abrir_steam_ya" and skill.frases == ["abre steam"]
