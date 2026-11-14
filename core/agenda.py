"""
Agenda: órdenes programadas para más tarde ("abre steam dentro de 5 min",
"cierra google a las 17:30").

- Se guardan en SQLite (data/agente.db, viene con Python): sobreviven a un
  reinicio del agente.
- Se guarda la orden YA INTERPRETADA y confirmada (skill y parámetros, o los
  pasos): a su hora se ejecuta sin volver a preguntar ni a interpretar, porque
  tú no estarás delante.
- Un hilo (Planificador) mira cada segundo si hay alguna que toque. Si el
  agente estaba apagado a su hora y ha pasado más de TOLERANCIA_RETRASO, no se
  ejecuta (se marca como perdida): abrir un juego 3 horas tarde no es lo que
  pediste.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from config import RUTA_BD, TOLERANCIA_RETRASO_TAREAS

log = logging.getLogger("personalagent")

PENDIENTE, HECHA, FALLIDA, CANCELADA, PERDIDA = "pendiente", "hecha", "fallida", "cancelada", "perdida"


@dataclass
class Tarea:
    id: int
    texto: str                 # la orden tal como la dijiste (sin la parte de tiempo)
    cuando: datetime
    orden: dict[str, Any]      # interpretación: {"skill", "params", "pasos", "origen", "confianza"}
    descripcion: str           # lo que se te enseñó al confirmarla
    estado: str = PENDIENTE
    resultado: str = ""


class Agenda:
    def __init__(self, ruta: Path = RUTA_BD):
        self.ruta = Path(ruta)
        self._lock = threading.Lock()
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._conexion() as bd:
            bd.execute("""CREATE TABLE IF NOT EXISTS tareas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                texto TEXT NOT NULL,
                cuando TEXT NOT NULL,
                orden TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                resultado TEXT NOT NULL DEFAULT '',
                creada TEXT NOT NULL,
                ejecutada TEXT)""")

    def _conexion(self) -> sqlite3.Connection:
        return sqlite3.connect(self.ruta, timeout=10)

    @staticmethod
    def _tarea(fila) -> Tarea:
        id_, texto, cuando, orden, descripcion, estado, resultado = fila
        return Tarea(id_, texto, datetime.fromisoformat(cuando), json.loads(orden), descripcion, estado, resultado)

    _COLUMNAS = "id, texto, cuando, orden, descripcion, estado, resultado"

    def programar(self, texto: str, cuando: datetime, orden: dict, descripcion: str) -> Tarea:
        with self._lock, self._conexion() as bd:
            cursor = bd.execute(
                "INSERT INTO tareas (texto, cuando, orden, descripcion, creada) VALUES (?, ?, ?, ?, ?)",
                (texto, cuando.isoformat(timespec="seconds"), json.dumps(orden, ensure_ascii=False),
                 descripcion, datetime.now().isoformat(timespec="seconds")))
            return Tarea(cursor.lastrowid, texto, cuando, orden, descripcion)

    def pendientes(self) -> list[Tarea]:
        with self._lock, self._conexion() as bd:
            filas = bd.execute(f"SELECT {self._COLUMNAS} FROM tareas WHERE estado = ? ORDER BY cuando",
                               (PENDIENTE,)).fetchall()
        return [self._tarea(f) for f in filas]

    def obtener(self, id_: int) -> Tarea | None:
        with self._lock, self._conexion() as bd:
            fila = bd.execute(f"SELECT {self._COLUMNAS} FROM tareas WHERE id = ?", (id_,)).fetchone()
        return self._tarea(fila) if fila else None

    def ultimas(self, limite: int = 20) -> list[Tarea]:
        with self._lock, self._conexion() as bd:
            filas = bd.execute(f"SELECT {self._COLUMNAS} FROM tareas ORDER BY id DESC LIMIT ?",
                               (limite,)).fetchall()
        return [self._tarea(f) for f in filas]

    def marcar(self, id_: int, estado: str, resultado: str = "") -> bool:
        """Cambia el estado solo si estaba pendiente (así no se ejecuta dos veces)."""
        with self._lock, self._conexion() as bd:
            cursor = bd.execute(
                "UPDATE tareas SET estado = ?, resultado = ?, ejecutada = ? WHERE id = ? AND estado = ?",
                (estado, resultado, datetime.now().isoformat(timespec="seconds"), id_, PENDIENTE))
            return cursor.rowcount == 1

    def cancelar(self, id_: int) -> bool:
        return self.marcar(id_, CANCELADA, "Cancelada por el usuario.")


class Planificador:
    """Hilo que ejecuta las tareas a su hora llamando a `ejecutar(tarea) -> (ok, mensaje)`."""

    def __init__(self, agenda: Agenda, ejecutar: Callable[[Tarea], tuple[bool, str]],
                 tolerancia: timedelta = timedelta(seconds=TOLERANCIA_RETRASO_TAREAS),
                 intervalo: float = 1.0):
        self.agenda = agenda
        self.ejecutar = ejecutar
        self.tolerancia = tolerancia
        self.intervalo = intervalo
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        if self._hilo and self._hilo.is_alive():
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True, name="agenda")
        self._hilo.start()
        pendientes = self.agenda.pendientes()
        if pendientes:
            log.info("Agenda: %d tarea(s) programada(s); la próxima, #%d '%s' a las %s.",
                     len(pendientes), pendientes[0].id, pendientes[0].texto, f"{pendientes[0].cuando:%H:%M}")

    def parar(self) -> None:
        self._parar.set()

    def revisar(self, ahora: datetime | None = None) -> list[Tarea]:
        """Ejecuta las tareas a las que les toca (una pasada). Devuelve las que ha tratado."""
        ahora = ahora or datetime.now()
        tratadas = []
        for tarea in self.agenda.pendientes():
            if tarea.cuando > ahora:
                break   # están ordenadas por hora
            if ahora - tarea.cuando > self.tolerancia:
                if self.agenda.marcar(tarea.id, PERDIDA, f"No se ejecutó a su hora ({tarea.cuando:%d/%m %H:%M}): "
                                                         "el agente no estaba en marcha."):
                    log.warning("Tarea #%d '%s' perdida: tocaba a las %s y el agente no estaba en marcha.",
                                tarea.id, tarea.texto, f"{tarea.cuando:%H:%M}")
                tratadas.append(tarea)
                continue
            # Se marca ANTES de ejecutarla: si algo se cuelga, no se repetirá en bucle.
            if not self.agenda.marcar(tarea.id, HECHA, "En curso…"):
                continue   # otro hilo o una cancelación se adelantó
            try:
                ok, mensaje = self.ejecutar(tarea)
            except Exception as e:  # una tarea rota no debe parar la agenda
                log.exception("La tarea #%d falló con una excepción:", tarea.id)
                ok, mensaje = False, f"Error: {e}"
            with self.agenda._lock, self.agenda._conexion() as bd:
                bd.execute("UPDATE tareas SET estado = ?, resultado = ? WHERE id = ?",
                           (HECHA if ok else FALLIDA, mensaje, tarea.id))
            log.info("⏰ Tarea #%d '%s': %s %s", tarea.id, tarea.texto, "✔" if ok else "✘", mensaje)
            tratadas.append(tarea)
        return tratadas

    def _bucle(self) -> None:
        while not self._parar.wait(self.intervalo):
            try:
                self.revisar()
            except Exception:
                log.exception("Error revisando la agenda:")
