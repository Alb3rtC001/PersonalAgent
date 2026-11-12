"""
API HTTP local del agente (FastAPI).

El PC hace de "cerebro" y cualquier cliente (la consola, el móvil más
adelante) le manda órdenes por HTTP. Todas las rutas salvo /salud exigen
la cabecera X-Token (ver api/token.py).

Rutas
-----
GET    /salud                 ¿está vivo el servidor?
GET    /skills                catálogo de skills (lo que sabe hacer)
GET    /episodios?limite=20   últimas órdenes registradas
POST   /ordenes               {"texto": "..."}               → Respuesta
POST   /ordenes/{id}          {"dato": "..."} o {"confirmar": true|false} → Respuesta
DELETE /ordenes/{id}          descartar una orden pendiente

Conversación
------------
Una orden puede necesitar algo del usuario antes de terminar:
    estado = "necesita_dato"          → contestar con {"dato": "..."}
    estado = "necesita_confirmacion"  → contestar con {"confirmar": true}
Los estados finales son "completada", "fallida" y "rechazada".
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from api.token import obtener_token
from config import CADUCIDAD_PENDIENTES
from core.agente import Agente
from core.memoria import cargar_episodios
from core.router import Interpretacion
from core.skills.base import Resultado

class JSONUTF8(JSONResponse):
    """Declara el charset: algunos clientes (p. ej. PowerShell 5.1) si no, leen mal las tildes."""
    media_type = "application/json; charset=utf-8"


Estado = Literal["completada", "fallida", "rechazada", "necesita_dato", "necesita_confirmacion"]


class OrdenNueva(BaseModel):
    texto: str


class Contestacion(BaseModel):
    dato: str | None = None
    confirmar: bool | None = None


class Respuesta(BaseModel):
    id: str | None = None
    estado: Estado
    mensaje: str
    skill: str | None = None
    falta: str | None = None
    accion: str | None = None
    planes: list[list[str]] = []


@dataclass
class _Pendiente:
    interp: Interpretacion
    params: dict[str, Any]
    falta: str | None = None
    accion: str | None = None
    creada: float = field(default_factory=time.monotonic)


def crear_app(agente: Agente | None = None, token: str | None = None) -> FastAPI:
    agente = agente or Agente()
    token = token or obtener_token()
    pendientes: dict[str, _Pendiente] = {}
    lock_pendientes = threading.Lock()

    cabecera_token = APIKeyHeader(name="X-Token", auto_error=False)

    def autorizar(x_token: str | None = Depends(cabecera_token)) -> None:
        if not x_token or not secrets.compare_digest(x_token, token):
            raise HTTPException(status_code=401, detail="Token incorrecto o ausente (cabecera X-Token).")

    app = FastAPI(title="PersonalAgent", version="0.2", default_response_class=JSONUTF8,
                  description="API local del asistente. Pulsa 'Authorize' y pega el token.")
    protegido = [Depends(autorizar)]

    # --- Pendientes ----------------------------------------------------------

    def _purgar() -> None:
        limite = time.monotonic() - CADUCIDAD_PENDIENTES
        with lock_pendientes:
            for id_ in [i for i, p in pendientes.items() if p.creada < limite]:
                del pendientes[id_]

    def _sacar(id_: str) -> _Pendiente:
        _purgar()
        with lock_pendientes:
            pendiente = pendientes.pop(id_, None)
        if pendiente is None:
            raise HTTPException(status_code=404, detail="No hay ninguna orden pendiente con ese id (puede haber caducado).")
        return pendiente

    def _ejecutar(id_: str, pendiente: _Pendiente, accion_confirmada: str | None = None) -> Respuesta:
        resultado: Resultado = agente.ejecutar(
            pendiente.interp, pendiente.params,
            confirmar=lambda accion: accion == accion_confirmada,
        )
        base = {"id": id_, "skill": pendiente.interp.skill, "mensaje": resultado.mensaje,
                "planes": resultado.datos.get("planes") or []}

        if resultado.falta:
            pendiente.falta, pendiente.accion = resultado.falta, None
        elif resultado.datos.get("cancelado"):
            pendiente.falta, pendiente.accion = None, resultado.datos.get("accion")
        else:
            return Respuesta(estado="completada" if resultado.ok else "fallida", **base)

        pendiente.creada = time.monotonic()
        with lock_pendientes:
            pendientes[id_] = pendiente
        if pendiente.falta:
            return Respuesta(estado="necesita_dato", falta=pendiente.falta, **base)
        return Respuesta(estado="necesita_confirmacion", accion=pendiente.accion, **base)

    # --- Rutas ---------------------------------------------------------------

    @app.get("/salud")
    def salud() -> dict[str, Any]:
        return {"ok": True, "skills": len(agente.registro)}

    @app.get("/skills", dependencies=protegido)
    def skills() -> list[dict[str, Any]]:
        return [s.describir() for s in agente.registro.values()]

    @app.get("/episodios", dependencies=protegido)
    def episodios(limite: int = 20) -> list[dict[str, Any]]:
        return cargar_episodios(agente.ruta_episodios, limite=max(1, min(limite, 500)))

    @app.post("/ordenes", dependencies=protegido)
    def nueva_orden(orden: OrdenNueva) -> Respuesta:
        _purgar()
        interp = agente.interpretar(orden.texto)
        if interp.motivo_rechazo:
            return Respuesta(estado="rechazada", mensaje=interp.motivo_rechazo)
        id_ = uuid.uuid4().hex[:12]
        return _ejecutar(id_, _Pendiente(interp, dict(interp.params)))

    @app.post("/ordenes/{id_}", dependencies=protegido)
    def contestar(id_: str, contestacion: Contestacion) -> Respuesta:
        pendiente = _sacar(id_)
        if pendiente.falta:
            dato = (contestacion.dato or "").strip()
            if not dato:
                return Respuesta(id=id_, estado="fallida", skill=pendiente.interp.skill,
                                 mensaje="Orden cancelada: no se indicó el dato que faltaba.")
            pendiente.params[pendiente.falta] = dato
            return _ejecutar(id_, pendiente)

        if not contestacion.confirmar:
            return Respuesta(id=id_, estado="fallida", skill=pendiente.interp.skill,
                             mensaje=f"Cancelado por el usuario: {pendiente.accion}")
        return _ejecutar(id_, pendiente, accion_confirmada=pendiente.accion)

    @app.delete("/ordenes/{id_}", dependencies=protegido)
    def descartar(id_: str) -> dict[str, bool]:
        _sacar(id_)
        return {"ok": True}

    return app
