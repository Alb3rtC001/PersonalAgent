"""
Tests del LLM (core/llm.py) y del router híbrido. No arrancan el modelo:
el clasificador y el LLM son falsos.

    python -m pytest tests
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm import (  # noqa: E402
    NINGUNA,
    InterpreteLLM,
    ResultadoLLM,
    anclar,
    construir_mensajes,
    esquema_ordenes,
)
from core.router import Router  # noqa: E402
from core.skills.abrir_aplicacion import AbrirAplicacion  # noqa: E402
from core.skills.crear_nota import CrearNota  # noqa: E402

REGISTRO = {"abrir_aplicacion": AbrirAplicacion(), "crear_nota": CrearNota()}


# --- Esquema y prompt ---------------------------------------------------

def test_esquema_una_opcion_por_skill_mas_ninguna():
    opciones = esquema_ordenes(REGISTRO)["anyOf"]
    skills = [o["properties"]["skill"]["const"] for o in opciones]
    assert skills == ["abrir_aplicacion", "crear_nota", NINGUNA]
    params_nota = opciones[1]["properties"]["parametros"]
    assert set(params_nota["properties"]) == {"contenido", "titulo"}
    assert params_nota["additionalProperties"] is False


def test_mensajes_incluyen_catalogo_y_ejemplos_validos():
    ejemplos = [{"frase": "abre x", "skill": "abrir_aplicacion", "parametros": {"aplicacion": "x"}},
                {"frase": "borra todo", "skill": "skill_que_ya_no_existe", "parametros": {}}]
    mensajes = construir_mensajes("abre y", REGISTRO, ejemplos)
    assert "abrir_aplicacion" in mensajes[0]["content"]
    assert [m["content"] for m in mensajes if m["role"] == "user"] == ["abre x", "abre y"]


# --- Anclar valores al texto --------------------------------------------

def test_anclar_corrige_al_texto_del_usuario():
    assert anclar("bloque de notas", "ábreme el bloc de notas") == ("bloc de notas", True)
    assert anclar("discord", "Arranca Discord, por favor") == ("Discord", True)
    assert anclar("calculetta", "cuánto es 15 por 3")[1] is False


# --- Validación de la respuesta del LLM ---------------------------------

def _llm():
    return InterpreteLLM(REGISTRO, servidor=object(), ejemplos=[])


def test_validar_quita_opcionales_inventados_o_repetidos():
    r = _llm().validar({"skill": "crear_nota", "parametros": {
        "contenido": "medidas de la mesa", "titulo": "Medidas"}}, "guarda las medidas de la mesa")
    assert r.params == {"contenido": "medidas de la mesa"}
    r = _llm().validar({"skill": "crear_nota", "parametros": {
        "contenido": "mañana hay reunión", "titulo": "Reunión importante"}}, "apunta que mañana hay reunión")
    assert r.params == {"contenido": "mañana hay reunión"}


def test_validar_rechaza_nombres_inventados():
    r = _llm().validar({"skill": "abrir_aplicacion", "parametros": {"aplicacion": "calculetta"}},
                       "cuánto es 15 por 3")
    assert r.skill is None and r.propuesta == "abrir_aplicacion"


def test_validar_ninguna_y_skill_desconocida():
    assert _llm().validar({"skill": NINGUNA, "parametros": {}}, "hola").skill is None
    assert _llm().validar({"skill": "hackear", "parametros": {}}, "hackea").skill is None


# --- Router híbrido -----------------------------------------------------

class LLMFalso:
    def __init__(self, respuesta: ResultadoLLM):
        self.respuesta = respuesta
        self.llamadas = 0

    def interpretar(self, texto):
        self.llamadas += 1
        return self.respuesta


def _router(clasificacion, respuesta_llm):
    llm = LLMFalso(respuesta_llm)
    router = Router(REGISTRO, umbral=0.72, clasificador=lambda t: clasificacion, llm=llm)
    return router, llm


def test_clasificador_seguro_no_consulta_al_llm():
    router, llm = _router(("abrir_aplicacion", 0.99, []), ResultadoLLM(None))
    i = router.interpretar("abre discord")
    assert (i.skill, i.params, i.origen, llm.llamadas) == ("abrir_aplicacion", {"aplicacion": "discord"},
                                                           "clasificador", 0)


def test_clasificador_dudoso_pregunta_al_llm():
    router, llm = _router(("ninguna", 0.40, []),
                          ResultadoLLM("crear_nota", {"contenido": "probar la fase 1"}))
    i = router.interpretar("apunta que probar la fase 1")
    assert i.skill == "crear_nota" and i.origen == "llm" and llm.llamadas == 1


def test_verbo_desconocido_pregunta_al_llm():
    # "reinicia" es desconocido y no forma parte del nombre de la app.
    router, llm = _router(("abrir_aplicacion", 0.95, ["reinicia"]),
                          ResultadoLLM(None, motivo="No sé hacer eso todavía."))
    i = router.interpretar("reinicia steam")
    assert i.skill is None and i.motivo_rechazo and llm.llamadas == 1


def test_sin_llm_disponible_usa_el_clasificador():
    router, _ = _router(("abrir_aplicacion", 0.95, ["porfa"]),
                        ResultadoLLM(None, motivo="El LLM local no está disponible."))
    i = router.interpretar("abre discord porfa")
    assert i.skill == "abrir_aplicacion" and i.origen == "clasificador"


def test_valor_reformulado_por_el_llm_se_cambia_por_el_literal():
    router, _ = _router(("abrir_aplicacion", 0.95, ["administrador", "tareas"]),
                        ResultadoLLM(None, {"aplicacion": "tareas administrativas"},
                                     no_anclados={"aplicacion"}, propuesta="abrir_aplicacion"))
    i = router.interpretar("abre el administrador de tareas")
    assert i.skill == "abrir_aplicacion" and i.params == {"aplicacion": "administrador de tareas"}
