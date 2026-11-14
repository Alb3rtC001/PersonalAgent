"""
Memoria de episodios: cada orden ejecutada (o rechazada) se añade como
una línea JSON en config.RUTA_EPISODIOS. Es el historial del agente y el
futuro dataset para que aprenda de su propio uso (ARQUITECTURA.md §1).

Formato JSONL (una línea por episodio): solo se añade al final, nunca se
reescribe, así que es rápido y no se corrompe si el programa se cierra a
mitad. Todo el acceso pasa por este módulo, de modo que cambiar a SQLite
o a una base vectorial más adelante no afecta al resto del código
(ARQUITECTURA.md §9).
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from config import RUTA_EPISODIOS

_lock = threading.Lock()  # la API atiende peticiones en varios hilos


def registrar_episodio(episodio: dict[str, Any], ruta: Path | None = None) -> None:
    ruta = Path(ruta) if ruta else RUTA_EPISODIOS
    linea = {"momento": datetime.now().isoformat(timespec="seconds"), **episodio}
    texto = json.dumps(linea, ensure_ascii=False, default=str) + "\n"
    with _lock:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(texto)


def cargar_episodios(ruta: Path | None = None, limite: int | None = None) -> list[dict[str, Any]]:
    """Episodios en orden cronológico; con `limite`, solo los últimos N."""
    ruta = Path(ruta) if ruta else RUTA_EPISODIOS
    if not ruta.exists():
        return []
    episodios = []
    with _lock, open(ruta, encoding="utf-8") as f:
        for linea in f:
            if not linea.strip():
                continue
            try:
                episodios.append(json.loads(linea))
            except json.JSONDecodeError:
                continue  # línea a medio escribir (cierre brusco): se ignora
    return episodios[-limite:] if limite else episodios


# ---------------------------------------------------------------------------
# Órdenes parecidas como ejemplos para el LLM (aprender del uso sin reentrenar)
# ---------------------------------------------------------------------------

def _normal(texto: str) -> str:
    from core.estado import normalizar
    return re.sub(r"[^a-z0-9ñ ]", " ", normalizar(texto)).strip()


def _trigramas(texto: str) -> frozenset[str]:
    t = f"  {' '.join(_normal(texto).split())}  "
    return frozenset(t[i:i + 3] for i in range(len(t) - 2))


def ejemplo_de(episodio: dict[str, Any]) -> dict[str, Any] | None:
    """
    Convierte un episodio que salió bien en un ejemplo {"frase", "pasos"} con
    los parámetros TAL COMO SE INTERPRETARON (no los que se rellenaron luego
    con el contexto: si "escribe 3*3" se mandó a la Calculadora por ser la
    última app, el ejemplo no debe enseñar a poner "Calculadora").
    """
    if not episodio.get("ok") or episodio.get("rechazada") or not episodio.get("texto"):
        return None
    if episodio.get("skill") in (None, "programar") or episodio.get("origen") == "agenda":
        return None
    if episodio.get("pasos_interpretados"):
        pasos = [{"skill": s, "parametros": p} for s, p in episodio["pasos_interpretados"]]
    elif "parametros_interpretados" in episodio:
        pasos = [{"skill": episodio["skill"], "parametros": episodio["parametros_interpretados"]}]
    else:
        return None   # episodios antiguos: no se sabe qué se interpretó exactamente
    return {"frase": episodio["texto"], "pasos": pasos}


class MemoriaEjemplos:
    """
    Busca, entre tus órdenes pasadas que salieron bien, las más parecidas a
    una frase (parecido de texto por trigramas: CPU, milisegundos). Se recarga
    sola cuando cambia el archivo de episodios.
    """

    def __init__(self, ruta: Path | None = None, umbral: float = 0.35):
        self.ruta = Path(ruta) if ruta else RUTA_EPISODIOS
        self.umbral = umbral
        self._firma: tuple[float, int] | None = None
        self._ejemplos: list[tuple[frozenset[str], dict[str, Any]]] = []

    def _recargar(self) -> None:
        try:
            st = self.ruta.stat()
        except OSError:
            self._ejemplos, self._firma = [], None
            return
        firma = (st.st_mtime, st.st_size)
        if firma == self._firma:
            return
        unicos: dict[str, dict[str, Any]] = {}
        for episodio in cargar_episodios(self.ruta):
            ejemplo = ejemplo_de(episodio)
            if ejemplo:
                unicos[_normal(ejemplo["frase"])] = ejemplo   # el más reciente gana
        self._ejemplos = [(_trigramas(e["frase"]), e) for e in unicos.values()]
        self._firma = firma

    def parecidos(self, texto: str, n: int = 3) -> list[dict[str, Any]]:
        if n <= 0:
            return []
        self._recargar()
        objetivo = _trigramas(texto)
        puntuados = []
        for trigramas, ejemplo in self._ejemplos:
            union = len(objetivo | trigramas)
            parecido = len(objetivo & trigramas) / union if union else 0.0
            if parecido >= self.umbral:
                puntuados.append((parecido, ejemplo))
        puntuados.sort(key=lambda p: -p[0])
        # Del menos al más parecido: el más parecido queda justo antes de la orden.
        return [e for _, e in reversed(puntuados[:n])]
