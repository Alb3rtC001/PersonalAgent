"""
Tests del planificador, el executor, la búsqueda de apps y las plantillas
como skills. No tocan Windows: el estado del mundo es un diccionario.

    python -m pytest tests
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.estado import EstadoMundo  # noqa: E402
from core.executor import ejecutar_orden  # noqa: E402
from core.memoria import cargar_episodios  # noqa: E402
from core.planner import Paso, planificar  # noqa: E402
from core.skills.abrir_aplicacion import AbrirAplicacion, AppInstalada, buscar_app  # noqa: E402
from core.skills.base import Resultado, Skill  # noqa: E402
from core.skills.plantilla import SkillPlantilla  # noqa: E402
from core.skills.restaurar_ventana import RestaurarVentana  # noqa: E402

META_STEAM = {
    "parametro": "juego",
    "precondiciones": {"visible:steam": True},
    "efectos": {"lanzado:{juego}": True},
    "coste": 2,
}


def _estado(hechos: dict) -> EstadoMundo:
    return EstadoMundo(consulta=lambda h: hechos.get(h, False))


def _registro_steam() -> dict[str, Skill]:
    plantilla = [{"tipo": "escribir", "valor": "{slot}"}, {"tipo": "click", "definitivo": True, "valor": {}}]
    skills = [AbrirAplicacion(), RestaurarVentana(), SkillPlantilla("ejecutar_en_steam", plantilla, META_STEAM)]
    return {s.nombre: s for s in skills}


# --- Planificador -------------------------------------------------------

def test_plan_steam_cerrado_abre_steam_primero():
    plan = planificar("ejecutar_en_steam", {"juego": "Destiny 2"}, _estado({}), _registro_steam())
    assert plan == [Paso("abrir_aplicacion", {"aplicacion": "steam"}),
                    Paso("ejecutar_en_steam", {"juego": "Destiny 2"})]


def test_plan_steam_minimizado_lo_restaura():
    estado = _estado({"abierta:steam": True, "visible:steam": False})
    plan = planificar("ejecutar_en_steam", {"juego": "X"}, estado, _registro_steam())
    assert [p.skill for p in plan] == ["restaurar_ventana", "ejecutar_en_steam"]


def test_plan_steam_visible_va_directo():
    estado = _estado({"abierta:steam": True, "visible:steam": True})
    plan = planificar("ejecutar_en_steam", {"juego": "X"}, estado, _registro_steam())
    assert [p.skill for p in plan] == ["ejecutar_en_steam"]


def test_plan_imposible_devuelve_none():
    registro = {"s": SkillPlantilla("s", [], {"precondiciones": {"magia:si": True}})}
    assert planificar("s", {}, _estado({}), registro) is None


def test_consigue_extrae_parametros_de_un_hecho():
    assert AbrirAplicacion().consigue("visible:Discord") == {"aplicacion": "discord"}
    assert RestaurarVentana().consigue("abierta:discord") is None


# --- Executor -----------------------------------------------------------

class Falsa(Skill):
    def __init__(self, nombre, resultados, pre=None, efe=None, coste=1, confirmar=False):
        self.nombre = nombre
        self.resultados = list(resultados)
        self.PRECONDICIONES = pre or {}
        self.EFECTOS = efe or {}
        self.coste = coste
        self.requiere_confirmacion = confirmar
        self.llamadas = 0

    def ejecutar(self, **params):
        self.llamadas += 1
        ok = self.resultados.pop(0) if self.resultados else True
        return Resultado(ok, f"{self.nombre} {'ok' if ok else 'falló'}")


def test_executor_ejecuta_plan_y_registra(tmp_path):
    preparar = Falsa("preparar", [True], efe={"listo:si": True})
    objetivo = Falsa("objetivo", [True], pre={"listo:si": True})
    eps = tmp_path / "e.jsonl"
    r = ejecutar_orden("objetivo", {}, registro={"preparar": preparar, "objetivo": objetivo},
                       estado=_estado({}), ruta_episodios=eps)
    assert r.ok and preparar.llamadas == 1 and objetivo.llamadas == 1
    ep = cargar_episodios(eps)[0]
    assert [p["skill"] for p in ep["pasos"]] == ["preparar", "objetivo"]


def test_executor_replanifica_si_falla_un_paso(tmp_path):
    hechos = {}
    # La primera vía falla, pero entre medias el mundo cambia y ya no hace falta.
    preparar = Falsa("preparar", [False], efe={"listo:si": True})
    objetivo = Falsa("objetivo", [True], pre={"listo:si": True})
    orig = preparar.ejecutar

    def ejecutar_y_cambiar_mundo(**p):
        hechos["listo:si"] = True
        return orig(**p)
    preparar.ejecutar = ejecutar_y_cambiar_mundo

    r = ejecutar_orden("objetivo", {}, registro={"preparar": preparar, "objetivo": objetivo},
                       estado=_estado(hechos), ruta_episodios=tmp_path / "e.jsonl")
    assert r.ok and objetivo.llamadas == 1
    assert cargar_episodios(tmp_path / "e.jsonl")[0]["replanificado"] is True


def test_executor_no_repite_el_mismo_paso_fallido(tmp_path):
    objetivo = Falsa("objetivo", [False, True])
    r = ejecutar_orden("objetivo", {}, registro={"objetivo": objetivo},
                       estado=_estado({}), ruta_episodios=tmp_path / "e.jsonl")
    assert not r.ok and objetivo.llamadas == 1


def test_executor_pide_confirmacion(tmp_path):
    peligrosa = Falsa("peligrosa", [True], confirmar=True)
    reg = {"peligrosa": peligrosa}
    r = ejecutar_orden("peligrosa", {}, registro=reg, estado=_estado({}),
                       confirmar=lambda d: False, ruta_episodios=tmp_path / "e.jsonl")
    assert not r.ok and r.datos.get("cancelado") and peligrosa.llamadas == 0

    r = ejecutar_orden("peligrosa", {}, registro=reg, estado=_estado({}),
                       confirmar=lambda d: True, ruta_episodios=tmp_path / "e.jsonl")
    assert r.ok and peligrosa.llamadas == 1


def test_executor_skill_que_lanza_excepcion(tmp_path):
    class Rota(Falsa):
        def ejecutar(self, **p):
            raise RuntimeError("boom")
    r = ejecutar_orden("rota", {}, registro={"rota": Rota("rota", [])},
                       estado=_estado({}), ruta_episodios=tmp_path / "e.jsonl")
    assert not r.ok and "boom" in r.mensaje


# --- Búsqueda de apps ---------------------------------------------------

APPS = [
    AppInstalada("Steam", "steam-id"),
    AppInstalada("Steam Support Center", "http://support.steampowered.com/"),
    AppInstalada("Calculadora", "calc-id"),
    AppInstalada("Bloc de notas", "notepad-id"),
    AppInstalada("Notas rápidas", "sticky-id"),
    AppInstalada("Google Chrome", "chrome-id"),
    AppInstalada("Discord", "discord-id"),
]


def _mejor(consulta):
    candidatas = buscar_app(consulta, APPS)
    return candidatas[0][1].nombre if candidatas else None


def test_buscar_app():
    assert _mejor("steam") == "Steam"
    assert _mejor("Calculadora") == "Calculadora"
    assert _mejor("bloc de notas") == "Bloc de notas"
    assert _mejor("notas rapidas") == "Notas rápidas"
    assert _mejor("navegador") == "Google Chrome"   # alias de config.py
    assert _mejor("discrod") == "Discord"          # errata
    assert _mejor("photoshop") is None


# --- Plantillas como skills ---------------------------------------------

def test_plantilla_con_paso_definitivo_requiere_confirmacion():
    skill = _registro_steam()["ejecutar_en_steam"]
    assert skill.requiere_confirmacion
    assert skill.parametros == {"juego": "juego"}


def test_executor_confirma_si_lo_interpreto_el_llm(tmp_path):
    cerrar = Falsa("cerrar", [True, True])
    cerrar.confirmar_si_llm = True
    reg = {"cerrar": cerrar}
    # Interpretada por el clasificador: no pregunta.
    r = ejecutar_orden("cerrar", {}, registro=reg, estado=_estado({}), origen="clasificador",
                       confirmar=lambda d: False, ruta_episodios=tmp_path / "e.jsonl")
    assert r.ok and cerrar.llamadas == 1
    # Interpretada por el LLM: pregunta, y si no se confirma no se ejecuta.
    r = ejecutar_orden("cerrar", {}, registro=reg, estado=_estado({}), origen="llm",
                       confirmar=lambda d: False, ruta_episodios=tmp_path / "e.jsonl")
    assert not r.ok and r.datos.get("cancelado") and cerrar.llamadas == 1


def test_plantilla_confirmacion_desde_el_catalogo():
    sin_definitivo = [{"tipo": "escribir", "valor": "{slot}"}]
    meta = {**META_STEAM, "requiere_confirmacion": True, "confirmar_si_llm": True}
    skill = SkillPlantilla("x", sin_definitivo, meta)
    assert skill.requiere_confirmacion and skill.confirmar_si_llm
    assert not SkillPlantilla("y", sin_definitivo, META_STEAM).requiere_confirmacion
