"""
Tests de la API HTTP. Router y skills falsos: no cargan el modelo ni
tocan Windows.

    python -m pytest tests
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.servidor import crear_app  # noqa: E402
from core.agente import Agente  # noqa: E402
from core.router import Interpretacion  # noqa: E402
from core.skills.base import Resultado, Skill  # noqa: E402
from core.skills.crear_nota import CrearNota  # noqa: E402

TOKEN = "token-de-prueba"


class Peligrosa(Skill):
    nombre = "borrar_todo"
    requiere_confirmacion = True

    def __init__(self):
        self.llamadas = 0

    def ejecutar(self, **params):
        self.llamadas += 1
        return Resultado(True, "Hecho")


class RouterFalso:
    """'nota <texto>' → crear_nota, 'borra' → borrar_todo, lo demás se rechaza."""

    def interpretar(self, texto):
        if texto.startswith("nota"):
            contenido = texto[4:].strip()
            return Interpretacion(texto, "crear_nota", 0.99, "crear_nota",
                                  {"contenido": contenido} if contenido else {})
        if texto == "borra":
            return Interpretacion(texto, "borrar_todo", 0.99, "borrar_todo", {})
        return Interpretacion(texto, "ninguna", 0.99, motivo_rechazo="No he entendido esa orden.")


def test_llm_estado_y_cambio(entorno):
    cliente, _ = entorno
    assert cliente.get("/llm").json()["activo"] is False   # RouterFalso no tiene LLM
    assert cliente.post("/llm", json={"activo": False}).status_code == 200
    assert cliente.post("/llm", json={"activo": "quizá"}).status_code == 422


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    # El EstadoMundo real consultaría Windows; aquí ninguna skill tiene precondiciones.
    peligrosa = Peligrosa()
    registro = {"crear_nota": CrearNota(carpeta=tmp_path / "notas"), "borrar_todo": peligrosa}
    agente = Agente(router=RouterFalso(), registro=registro, ruta_episodios=tmp_path / "e.jsonl")
    cliente = TestClient(crear_app(agente=agente, token=TOKEN))
    cliente.headers["X-Token"] = TOKEN
    return cliente, peligrosa


def test_salud_sin_token(entorno):
    cliente, _ = entorno
    r = TestClient(cliente.app).get("/salud")
    assert r.status_code == 200 and r.json()["ok"]


def test_sin_token_no_deja_pasar(entorno):
    cliente, _ = entorno
    anonimo = TestClient(cliente.app)
    assert anonimo.post("/ordenes", json={"texto": "nota hola"}).status_code == 401
    assert anonimo.get("/skills", headers={"X-Token": "otro"}).status_code == 401


def test_skills(entorno):
    cliente, _ = entorno
    nombres = {s["nombre"] for s in cliente.get("/skills").json()}
    assert nombres == {"crear_nota", "borrar_todo"}


def test_orden_completa(entorno):
    cliente, _ = entorno
    r = cliente.post("/ordenes", json={"texto": "nota comprar pan"}).json()
    assert r["estado"] == "completada" and "Comprar pan" in r["mensaje"]
    assert cliente.get("/episodios").json()[-1]["skill"] == "crear_nota"


def test_orden_rechazada(entorno):
    cliente, _ = entorno
    r = cliente.post("/ordenes", json={"texto": "qué tiempo hace"}).json()
    assert r["estado"] == "rechazada" and r["id"] is None


def test_falta_dato_y_se_contesta(entorno):
    cliente, _ = entorno
    r = cliente.post("/ordenes", json={"texto": "nota"}).json()
    assert r["estado"] == "necesita_dato" and r["falta"] == "contenido"
    r = cliente.post(f"/ordenes/{r['id']}", json={"dato": "llamar al médico"}).json()
    assert r["estado"] == "completada"


def test_confirmacion_si_y_no(entorno):
    cliente, peligrosa = entorno
    r = cliente.post("/ordenes", json={"texto": "borra"}).json()
    assert r["estado"] == "necesita_confirmacion" and r["accion"] == "borrar_todo()"
    assert peligrosa.llamadas == 0

    r2 = cliente.post(f"/ordenes/{r['id']}", json={"confirmar": False}).json()
    assert r2["estado"] == "fallida" and peligrosa.llamadas == 0

    r = cliente.post("/ordenes", json={"texto": "borra"}).json()
    r3 = cliente.post(f"/ordenes/{r['id']}", json={"confirmar": True}).json()
    assert r3["estado"] == "completada" and peligrosa.llamadas == 1


def test_id_desconocido_o_ya_usado(entorno):
    cliente, _ = entorno
    assert cliente.post("/ordenes/noexiste", json={"dato": "x"}).status_code == 404
    r = cliente.post("/ordenes", json={"texto": "nota"}).json()
    cliente.post(f"/ordenes/{r['id']}", json={"dato": "algo"})
    assert cliente.post(f"/ordenes/{r['id']}", json={"dato": "otra vez"}).status_code == 404
