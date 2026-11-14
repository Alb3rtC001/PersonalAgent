"""
Traza de la última orden: data/ultima_orden.log (config.RUTA_TRAZA).

Guarda, con hora y lugar del código (módulo, función y línea), todo lo que
pasa desde que llega una orden: la frase, qué dijo el clasificador, qué
respondió el LLM (y si se le pidió corregir), el plan, cada paso con su
resultado y duración, y los errores con su traceback completo.

Solo se guarda la ÚLTIMA orden: cada orden nueva vacía el archivo y empieza
de cero. Así no crece y, si algo falla, la traza está ahí para mirarla.
(Las respuestas a una orden pendiente, como una confirmación desde la
API, se añaden a la traza de esa misma orden.)

Uso (lo hacen dispatcher.py y python -m api):
    configurar_logs()            # consola (avisos) + traza (todo el detalle)
    nueva_orden("abre discord")  # lo llama Agente.interpretar() en cada orden
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

from config import RUTA_TRAZA

NOMBRE_LOGGER = "personalagent"
FORMATO = ("%(asctime)s.%(msecs)03d %(levelname)-7s %(module)s.%(funcName)s:%(lineno)d"
           " [%(threadName)s]  %(message)s")


class ManejadorUltimaOrden(logging.Handler):
    """Escribe en un archivo que se vacía al empezar cada orden."""

    def __init__(self, ruta: Path = RUTA_TRAZA):
        super().__init__(logging.DEBUG)
        self.ruta = Path(ruta)
        self._archivo = None
        self._lock_archivo = threading.Lock()
        self.setFormatter(logging.Formatter(FORMATO, datefmt="%H:%M:%S"))

    def nueva(self, texto: str) -> None:
        with self._lock_archivo:
            if self._archivo is not None:
                self._archivo.close()
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self._archivo = open(self.ruta, "w", encoding="utf-8")
            self._archivo.write(f"=== Orden: {texto!r}  ({datetime.now():%Y-%m-%d %H:%M:%S}) ===\n")
            self._archivo.flush()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            linea = self.format(record)
        except Exception:
            self.handleError(record)
            return
        with self._lock_archivo:
            if self._archivo is None:   # actividad fuera de una orden (p. ej. al arrancar)
                return
            self._archivo.write(linea + "\n")
            self._archivo.flush()   # que esté escrita aunque el programa se cuelgue después

    def close(self) -> None:
        with self._lock_archivo:
            if self._archivo is not None:
                self._archivo.close()
                self._archivo = None
        super().close()


_manejador: ManejadorUltimaOrden | None = None


def configurar_logs(consola: bool = True, ruta: Path = RUTA_TRAZA) -> ManejadorUltimaOrden:
    """
    Consola: solo los avisos de progreso (nivel INFO, con "  … ").
    Traza: todo el detalle (nivel DEBUG) de la última orden.
    """
    global _manejador
    logger = logging.getLogger(NOMBRE_LOGGER)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if consola and not any(getattr(h, "_consola_agente", False) for h in logger.handlers):
        manejador_consola = logging.StreamHandler()
        manejador_consola.setLevel(logging.INFO)
        manejador_consola.setFormatter(logging.Formatter("  … %(message)s"))
        manejador_consola._consola_agente = True
        logger.addHandler(manejador_consola)
    if _manejador is None:
        _manejador = ManejadorUltimaOrden(ruta)
        logger.addHandler(_manejador)
    return _manejador


def nueva_orden(texto: str) -> None:
    """Empieza la traza de una orden nueva (borra la anterior). Sin configurar, no hace nada."""
    if _manejador is not None:
        _manejador.nueva(texto)
