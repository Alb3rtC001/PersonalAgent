"""
Vocabulario propio para la voz: nombres que Whisper no conoce o escribe "a
la española" ("Estim" por Steam, "slay de spire" por Slay the Spire).

Dos ayudas, las dos en la CPU y al momento:
1. pista(): los nombres van en el prompt inicial de Whisper, que así tiende a
   escribirlos bien.
2. corregir(): si aun así sale algo parecido a un nombre conocido (comparando
   cómo suena, no cómo se escribe), se cambia por el nombre bien escrito.

De dónde salen los nombres: las apps de core/atajos_apps.json (y sus botones
y campos), los juegos de Steam instalados y data/vocabulario_voz.txt, un
archivo tuyo (uno por línea) para lo que quieras: contactos, canales de
Discord, series... Las líneas que empiezan por # no cuentan.
"""

from __future__ import annotations

import difflib
import logging
import re
import threading
import time
from pathlib import Path

from config import RUTA_DATOS
from core.estado import normalizar

log = logging.getLogger("personalagent")

RUTA_VOCABULARIO = RUTA_DATOS / "vocabulario_voz.txt"
REFRESCO = 300                  # segundos que vale la lista antes de volver a leerla
MAX_CARACTERES_PISTA = 600      # el prompt de Whisper admite ~220 tokens: no pasarse
UMBRAL_UNA_PALABRA = 0.86       # parecido (por cómo suena) para cambiar una sola palabra
UMBRAL_VARIAS = 0.82            # y para varias ("slay de spire")
MIN_CLAVE = 4                   # nombres muy cortos no se corrigen (demasiado fácil equivocarse)
MAX_PALABRAS = 5

# Palabras corrientes que nunca empiezan ni terminan un nombre corregido.
CORRIENTES = {
    "a", "al", "de", "del", "el", "la", "las", "los", "lo", "en", "y", "o", "u", "un", "una", "con", "por",
    "para", "que", "me", "mi", "te", "se", "su", "es", "abre", "abrir", "cierra", "cerrar", "busca", "buscar",
    "pon", "escribe", "dale", "pulsa", "juega", "jugar", "quiero", "ve", "ir",
}

_lock = threading.Lock()
_cache: tuple[float, list[str]] | None = None


# --- Los nombres ---------------------------------------------------------------------

def _de_archivo(ruta: Path) -> list[str]:
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [l.strip() for l in lineas if l.strip() and not l.lstrip().startswith("#")]


def _de_atajos() -> list[str]:
    from core.atajos import cargar_atajos
    nombres = []
    for app, info in cargar_atajos().items():
        nombres.append(app)
        nombres += list(info.get("botones", {}).values()) + list(info.get("campos", {}).values())
    return nombres


def _de_steam() -> list[str]:
    try:
        from core.skills.steam import juegos_instalados
        return [j.nombre for j in juegos_instalados()]
    except Exception:
        return []


def nombres(ruta_propia: Path = RUTA_VOCABULARIO, refrescar: bool = False) -> list[str]:
    """Nombres conocidos, primero los tuyos (si no caben todos en la pista, van ellos)."""
    global _cache
    with _lock:
        if not refrescar and _cache and time.monotonic() - _cache[0] < REFRESCO and ruta_propia == RUTA_VOCABULARIO:
            return _cache[1]
        vistos, lista = set(), []
        for nombre in _de_archivo(ruta_propia) + _de_steam() + _de_atajos():
            nombre = " ".join(re.sub(r"[™®©]", "", nombre).split())
            if nombre and normalizar(nombre) not in vistos:
                vistos.add(normalizar(nombre))
                lista.append(nombre)
        if ruta_propia == RUTA_VOCABULARIO:
            _cache = (time.monotonic(), lista)
        return lista


def pista(base: str, lista: list[str]) -> str:
    """El prompt inicial de Whisper: la frase base y tantos nombres como quepan."""
    texto, puestos = base, []
    for nombre in lista:
        candidato = f"{base} Nombres: {', '.join(puestos + [nombre])}."
        if len(candidato) > MAX_CARACTERES_PISTA:
            break
        puestos.append(nombre)
        texto = candidato
    return texto


# --- Corrección por cómo suena -------------------------------------------------------

_REGLAS_SONIDO = [
    (r"ph", "f"), (r"th", "t"), (r"sh", "s"), (r"ch", "c"), (r"ck", "k"), (r"qu", "k"), (r"q", "k"),
    (r"c(?=[eiy])", "s"), (r"c", "k"), (r"z", "s"), (r"x", "ks"), (r"v", "b"), (r"w", "u"), (r"h", ""),
    (r"ll", "l"), (r"ee", "i"), (r"ea", "i"), (r"oo", "u"), (r"ai", "ei"), (r"ay", "ei"), (r"y", "i"),
    (r"([a-z])\1", r"\1"),
]


def clave(texto: str) -> str:
    """Cómo suena, aproximado: 'Steam' y 'Estim' dan lo mismo; 'Discord' y 'Diskord', también."""
    t = re.sub(r"[^a-z0-9ñ ]", "", normalizar(texto)).replace("ñ", "n")
    # El español pone una "e" delante de "s"+consonante: "Espotify", "Estim".
    t = " ".join(re.sub(r"^es(?=[bcdfgkmnpqtv])", "s", p) for p in t.split())
    # Grafías inglesas que no suenan: "Knight" → "nait", "Hollow" → "holo".
    t = " ".join(re.sub(r"ow$", "o", re.sub(r"^kn", "n", p)).replace("gh", "") for p in t.split())
    t = t.replace(" ", "")
    for patron, cambio in _REGLAS_SONIDO:
        t = re.sub(patron, cambio, t)
    return t


def _parecido(a: str, b: str) -> float:
    if not a or not b or abs(len(a) - len(b)) > max(2, len(b) // 3):
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _despegar(palabras: list[str], lista: list[str]) -> list[str]:
    """Whisper a veces pega el verbo al nombre ("PonsPortify"): se separan si el resto suena a un nombre."""
    claves = [clave(n) for n in lista if len(clave(n)) >= MIN_CLAVE]
    resultado = []
    for palabra in palabras:
        limpia = re.sub(r"[^\w]", "", normalizar(palabra))
        partida = None
        for verbo in CORRIENTES:
            if len(verbo) >= 2 and limpia.startswith(verbo) and len(limpia) - len(verbo) >= MIN_CLAVE:
                c = clave(palabra[len(verbo):])
                if any(_parecido(c, cn) >= UMBRAL_UNA_PALABRA for cn in claves):
                    partida = [palabra[:len(verbo)], palabra[len(verbo):]]
                    break
        resultado += partida or [palabra]
    return resultado


def corregir(texto: str, lista: list[str]) -> str:
    """Cambia los trozos de `texto` que suenan como un nombre conocido por ese nombre."""
    palabras = _despegar(texto.split(), lista)
    if not palabras or not lista:
        return texto
    claves = [(nombre, clave(nombre)) for nombre in lista]
    claves = [(n, c) for n, c in claves if len(c) >= MIN_CLAVE]
    candidatos = []   # (parecido, nº de palabras, inicio, nombre)
    for n in range(1, min(MAX_PALABRAS, len(palabras)) + 1):
        for i in range(len(palabras) - n + 1):
            trozo = palabras[i:i + n]
            limpio = [re.sub(r"[^\w]", "", normalizar(p)) for p in trozo]
            if limpio[0] in CORRIENTES or limpio[-1] in CORRIENTES:
                continue
            c = clave(" ".join(trozo))
            if len(c) < MIN_CLAVE:
                continue
            umbral = UMBRAL_UNA_PALABRA if n == 1 else UMBRAL_VARIAS
            for nombre, c_nombre in claves:
                p = 1.0 if c == c_nombre else _parecido(c, c_nombre)
                if p >= umbral:
                    candidatos.append((p, n, i, nombre))
    # Los mejores primero; a igualdad, el trozo más largo. Sin solaparse.
    candidatos.sort(key=lambda x: (-x[0], -x[1]))
    usadas, cambios = set(), []
    for p, n, i, nombre in candidatos:
        sitio = set(range(i, i + n))
        if sitio & usadas:
            continue
        usadas |= sitio
        cambios.append((i, n, nombre))
    for i, n, nombre in sorted(cambios, reverse=True):
        # Conserva la puntuación de detrás ("Estim," → "Steam,").
        final = re.search(r"[^\w]*$", palabras[i + n - 1]).group(0)
        if " ".join(palabras[i:i + n]).rstrip(final) != nombre:
            log.debug("Voz: '%s' → '%s'", " ".join(palabras[i:i + n]), nombre)
        palabras[i:i + n] = [nombre + final]
    return " ".join(palabras)
