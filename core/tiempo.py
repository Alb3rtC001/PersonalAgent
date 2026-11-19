"""
Expresiones de tiempo en español para programar órdenes.

    separar_tiempo("abre steam dentro de 5 min")
        -> ("abre steam", <ahora + 5 min>, "dentro de 5 min")
    separar_tiempo("cierra google a las 17:30")
        -> ("cierra google", <hoy 17:30, o mañana si ya pasó>, "a las 17:30")

Entiende:
- relativo: "dentro de 5 minutos", "en 30 min", "en una hora", "dentro de
  media hora", "en un cuarto de hora", "en 2 horas y media", "en 20 segundos"
- absoluto: "a las 17:30", "a las 5", "a las 5 y media", "a las 9 menos
  cuarto", "a la una", "a las 8 de la tarde", "mañana a las 9",
  "pasado mañana a las 10"

La expresión tiene que estar al principio o al final de la frase (es lo
habitual: "abre steam dentro de 5 min", "a las 17:30 cierra google"); así
no se confunde con un dato del contenido ("apunta que la cita es a las 5"
lo decide quien llama, ver Agente).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

NUMEROS = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "veinte": 20, "veinticinco": 25, "treinta": 30,
    "cuarenta": 40, "cuarenta y cinco": 45, "cincuenta": 50, "noventa": 90,
}
_NUM = r"(?:\d{1,3}|" + "|".join(sorted(map(re.escape, NUMEROS), key=len, reverse=True)) + ")"
_UNIDAD = r"(?:segundos?|segs?|minutos?|mins?|horas?|h)"

RELATIVO = re.compile(
    r"\b(?:dentro de|en)\s+(?:"
    r"(?P<media>media hora)|(?P<cuarto>un cuarto de hora)|"
    rf"(?P<n>{_NUM})\s*(?P<u>{_UNIDAD})(?P<ymedia>\s+y media)?"
    r")\b")
_HORA = r"(?:\d{1,2}|" + "|".join(k for k, v in NUMEROS.items() if 1 <= v <= 12 and " " not in k) + ")"
ABSOLUTO = re.compile(
    r"\b(?:(?P<dia>pasado manana|manana|hoy)\s+)?a\s+las?\s+"
    rf"(?P<h>{_HORA})(?:\s*[:.h]\s*(?P<m>\d{{2}}))?"
    r"(?P<frac>\s+(?:y media|y cuarto|menos cuarto))?"
    r"(?:\s+(?:de la|del|por la)\s+(?P<parte>manana|tarde|noche|madrugada|mediodia))?\b")
# Palabras que sobran al quitar la expresión: "programa que ...", "abre steam, dentro de..."
PREFIJOS = re.compile(r"^\s*(?:programa(?:me)?(?:\s+que)?|recuerdame\s+que)\s+")


def _norm_1a1(texto: str) -> str:
    """Minúsculas y sin tildes con la MISMA longitud (para cortar el texto original)."""
    salida = []
    for c in texto.lower():
        n = "".join(x for x in unicodedata.normalize("NFD", c) if unicodedata.category(x) != "Mn")
        salida.append(n if len(n) == 1 else c)
    return "".join(salida)


def _numero(texto: str) -> int:
    return int(texto) if texto.isdigit() else NUMEROS[texto]


def _cuando_relativo(m: re.Match, ahora: datetime) -> datetime:
    if m.group("media"):
        return ahora + timedelta(minutes=30)
    if m.group("cuarto"):
        return ahora + timedelta(minutes=15)
    n, unidad = _numero(m.group("n")), m.group("u")
    if unidad.startswith("seg"):
        delta = timedelta(seconds=n)
    elif unidad.startswith("h"):
        delta = timedelta(hours=n)
    else:
        delta = timedelta(minutes=n)
    if m.group("ymedia"):
        delta += timedelta(minutes=30) if unidad.startswith("h") else timedelta(seconds=30)
    return ahora + delta


def _cuando_absoluto(m: re.Match, ahora: datetime) -> datetime | None:
    hora, minuto = _numero(m.group("h")), int(m.group("m") or 0)
    frac = (m.group("frac") or "").strip()
    if frac == "y media":
        minuto = 30
    elif frac == "y cuarto":
        minuto = 15
    elif frac == "menos cuarto":
        hora, minuto = hora - 1, 45
    parte = m.group("parte")
    # "las 12 de la noche" es la medianoche con la que acaba ese día (00:00 del
    # siguiente); "las 12 de la madrugada", las 00:00. No las 12 del mediodía.
    fin_del_dia = parte == "noche" and hora == 12
    if parte in ("noche", "madrugada") and hora == 12:
        hora = 0
    elif parte in ("tarde", "noche") and hora < 12:
        hora += 12
    elif parte == "mediodia" and hora < 12:
        hora += 12 if hora < 5 else 0
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None
    cuando = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    dia = m.group("dia")
    if fin_del_dia:
        cuando += timedelta(days=1)
    if dia == "manana":
        cuando += timedelta(days=1)
    elif dia == "pasado manana":
        cuando += timedelta(days=2)
    elif fin_del_dia:
        pass   # las 00:00 de mañana: siempre por venir
    elif cuando <= ahora:
        # "a las 5" cuando ya son las 18:00: si sin "de la mañana/tarde" la hora
        # de la tarde aún no ha pasado, es esa; si no, mañana.
        if not parte and hora < 12 and ahora.replace(hour=hora + 12, minute=minuto) > ahora:
            cuando = cuando.replace(hour=hora + 12)
        else:
            cuando += timedelta(days=1)
    return cuando


def separar_tiempo(texto: str, ahora: datetime | None = None
                   ) -> tuple[str, datetime, str, bool] | None:
    """
    (orden sin la expresión, cuándo, expresión, es_relativa) o None si la frase
    no empieza ni acaba con una expresión de tiempo.
    """
    ahora = ahora or datetime.now()
    normal = _norm_1a1(texto)
    candidatos = []
    for patron, relativo in ((RELATIVO, True), (ABSOLUTO, False)):
        for m in patron.finditer(normal):
            antes, despues = normal[:m.start()], normal[m.end():]
            al_principio = not re.sub(r"[\s,.:;¡!¿?]|programa(me)?( que)?|recuerdame que", "", antes)
            al_final = not re.sub(r"[\s,.:;¡!¿?]", "", despues)
            if al_principio or al_final:
                candidatos.append((m, relativo))
    if not candidatos:
        return None
    m, relativo = max(candidatos, key=lambda c: c[0].end() - c[0].start())
    cuando = _cuando_relativo(m, ahora) if relativo else _cuando_absoluto(m, ahora)
    if cuando is None:
        return None
    orden = re.sub(r"\s+", " ", texto[:m.start()] + " " + texto[m.end():]).strip(" ,.;:")
    # Quitar "programa (que)" / "recuérdame que" del principio, conservando el resto tal cual.
    prefijo = PREFIJOS.match(_norm_1a1(orden))
    if prefijo:
        orden = orden[prefijo.end():].strip()
    if not orden:
        return None
    return orden, cuando, texto[m.start():m.end()], relativo


def describir_cuando(cuando: datetime, ahora: datetime | None = None) -> str:
    ahora = ahora or datetime.now()
    if cuando.date() == ahora.date():
        dia = "hoy"
    elif cuando.date() == (ahora + timedelta(days=1)).date():
        dia = "mañana"
    else:
        dia = f"el {cuando:%d/%m}"
    return f"{dia} a las {cuando:%H:%M:%S}" if cuando.second else f"{dia} a las {cuando:%H:%M}"
