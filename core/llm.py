"""
LLM local (fase 3): frase → {skill, parametros} cuando el clasificador no
está seguro. Ver ARQUITECTURA.md §10.

- ServidorLLM arranca llama-server (models/llama.cpp) solo en 127.0.0.1 la
  primera vez que hace falta y lo para al salir. Si ya había uno en marcha
  en ese puerto (arrancado a mano), lo usa y no lo para.
- La respuesta está RESTRINGIDA por un JSON Schema generado del catálogo de
  skills: el modelo solo puede contestar una skill que existe (o "ninguna")
  y solo con los parámetros que esa skill declara.
- Los valores se "anclan" al texto del usuario: si el modelo devuelve
  "bloque de notas" y el usuario dijo "bloc de notas", se usa lo que dijo
  el usuario.
- Los ejemplos del prompt están en core/llm_ejemplos.json (editable).

Nada sale del PC: el modelo es un archivo local y el servidor solo escucha
en 127.0.0.1.
"""

from __future__ import annotations

import atexit
import difflib
import json
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from config import (
    LLM_CAPAS_GPU,
    LLM_CONTEXTO,
    LLM_ESPERA_ARRANQUE,
    LLM_PLANTILLA_CHAT,
    LLM_PUERTO,
    RUTA_DATOS,
    RUTA_LLAMA_SERVER,
    RUTA_MODELO_LLM,
)
from core.estado import normalizar
from core.skills.base import Skill

log = logging.getLogger("personalagent")

RUTA_EJEMPLOS = Path(__file__).parent / "llm_ejemplos.json"
NINGUNA = "ninguna"
CREATE_NO_WINDOW = 0x08000000

INSTRUCCIONES = """\
Eres el intérprete de órdenes de un asistente que controla un PC con Windows.
Convierte la orden del usuario en la skill que la cumple y sus parámetros.

Reglas:
1. Elige una skill solo si hace EXACTAMENTE lo que se pide. Si la acción es
   otra (minimizar, maximizar, reiniciar, volumen, enviar mensajes, buscar en
   internet, responder preguntas, charlar...), responde "ninguna", aunque
   alguna skill se parezca.
2. Copia los valores tal como los escribe el usuario, sin corregirlos ni
   traducirlos, y sin artículos al principio ("la calculadora" -> "calculadora").
3. Si la orden no dice el valor de un parámetro, no lo incluyas: se le
   preguntará al usuario. Nunca inventes valores (por ejemplo, un título
   que el usuario no ha dicho).
4. Los juegos se lanzan con ejecutar_en_steam; los programas y apps se abren
   con abrir_aplicacion.

Skills disponibles:
"""


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------

class ServidorLLM:
    def __init__(self, ejecutable: Path = RUTA_LLAMA_SERVER, modelo: Path = RUTA_MODELO_LLM,
                 puerto: int = LLM_PUERTO, capas_gpu: int = LLM_CAPAS_GPU,
                 contexto: int = LLM_CONTEXTO, plantilla: str | None = LLM_PLANTILLA_CHAT,
                 espera_max: float = LLM_ESPERA_ARRANQUE):
        self.ejecutable = Path(ejecutable)
        self.modelo = Path(modelo)
        self.puerto = puerto
        self.capas_gpu = capas_gpu
        self.contexto = contexto
        self.plantilla = plantilla
        self.espera_max = espera_max
        self.url = f"http://127.0.0.1:{puerto}"
        self._proceso: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def archivos_presentes(self) -> bool:
        return self.ejecutable.is_file() and self.modelo.is_file()

    def activo(self) -> bool:
        try:
            return httpx.get(f"{self.url}/health", timeout=1).status_code == 200
        except httpx.HTTPError:
            return False

    def asegurar(self) -> bool:
        """Deja el servidor listo (arrancándolo si hace falta). False si no es posible."""
        with self._lock:
            if self.activo():
                return True
            if not self.archivos_presentes():
                log.warning("No encuentro el LLM en %s (ver models/README.md).", self.ejecutable.parent.parent)
                return False
            if self._proceso is None or self._proceso.poll() is not None:
                log.info("Cargando el modelo de lenguaje (%s)…", self.modelo.name)
                comando = [str(self.ejecutable), "-m", str(self.modelo), "--host", "127.0.0.1",
                           "--port", str(self.puerto), "-ngl", str(self.capas_gpu),
                           "-c", str(self.contexto), "--no-webui"]
                if self.plantilla:
                    comando += ["--chat-template", self.plantilla]
                RUTA_DATOS.mkdir(parents=True, exist_ok=True)
                salida = open(RUTA_DATOS / "llm_servidor.log", "w", encoding="utf-8")
                self._proceso = subprocess.Popen(comando, stdout=salida, stderr=subprocess.STDOUT,
                                                 creationflags=CREATE_NO_WINDOW)
                atexit.register(self.parar)

            limite = time.monotonic() + self.espera_max
            while time.monotonic() < limite:
                if self._proceso.poll() is not None:
                    log.warning("El servidor del LLM se ha cerrado al arrancar (ver data/llm_servidor.log).")
                    return False
                if self.activo():
                    return True
                time.sleep(0.5)
            log.warning("El LLM no ha terminado de cargar en %d s.", self.espera_max)
            return False

    def parar(self) -> None:
        """Para el servidor si lo arrancamos nosotros."""
        if self._proceso is not None and self._proceso.poll() is None:
            self._proceso.terminate()
            try:
                self._proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proceso.kill()
        self._proceso = None

    def completar(self, mensajes: list[dict], esquema: dict, max_tokens: int = 200) -> str:
        r = httpx.post(f"{self.url}/v1/chat/completions", timeout=60, json={
            "messages": mensajes,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "orden", "schema": esquema}},
        })
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Prompt y esquema
# ---------------------------------------------------------------------------

def _todos_parametros(skill: Skill) -> dict[str, str]:
    return {**skill.parametros, **skill.parametros_opcionales}


def esquema_ordenes(registro: dict[str, Skill]) -> dict:
    """JSON Schema: una opción por skill (con sus parámetros exactos) + "ninguna"."""
    opciones = []
    for nombre, skill in registro.items():
        props = {p: {"type": "string"} for p in _todos_parametros(skill)}
        opciones.append({
            "type": "object",
            "properties": {
                "skill": {"const": nombre},
                "parametros": {"type": "object", "properties": props, "additionalProperties": False},
            },
            "required": ["skill", "parametros"],
            "additionalProperties": False,
        })
    opciones.append({
        "type": "object",
        "properties": {"skill": {"const": NINGUNA},
                       "parametros": {"type": "object", "properties": {}, "additionalProperties": False}},
        "required": ["skill", "parametros"],
        "additionalProperties": False,
    })
    return {"anyOf": opciones}


def describir_catalogo(registro: dict[str, Skill]) -> str:
    lineas = []
    for nombre, skill in registro.items():
        params = ", ".join(f"{p} ({d})" for p, d in _todos_parametros(skill).items()) or "ninguno"
        lineas.append(f"- {nombre}: {skill.descripcion} Parámetros: {params}.")
    return "\n".join(lineas)


def cargar_ejemplos(ruta: Path = RUTA_EJEMPLOS) -> list[dict]:
    if not ruta.is_file():
        return []
    return json.loads(ruta.read_text(encoding="utf-8"))


def construir_mensajes(texto: str, registro: dict[str, Skill], ejemplos: list[dict]) -> list[dict]:
    mensajes = [{"role": "system", "content": INSTRUCCIONES + describir_catalogo(registro)}]
    for ej in ejemplos:
        if ej["skill"] != NINGUNA and ej["skill"] not in registro:
            continue  # ejemplo de una skill que ya no existe
        mensajes.append({"role": "user", "content": ej["frase"]})
        mensajes.append({"role": "assistant", "content": json.dumps(
            {"skill": ej["skill"], "parametros": ej["parametros"]}, ensure_ascii=False)})
    mensajes.append({"role": "user", "content": texto})
    return mensajes


# ---------------------------------------------------------------------------
# Anclar valores al texto del usuario
# ---------------------------------------------------------------------------

def _norm_palabra(p: str) -> str:
    return re.sub(r"[^\w]", "", normalizar(p))


def anclar_al_texto(valor: str, texto: str, umbral: float = 0.8) -> str:
    return anclar(valor, texto, umbral)[0]


def anclar(valor: str, texto: str, umbral: float = 0.8) -> tuple[str, bool]:
    """
    Devuelve el trozo del texto original que corresponde al valor (con las
    mayúsculas y tildes del usuario) y True. Si el modelo cambió alguna
    palabra ("bloque de notas" por "bloc de notas") usa el trozo más
    parecido; si nada se parece lo bastante, devuelve el valor del modelo y
    False (el modelo se lo ha inventado o lo ha reformulado).
    """
    palabras = texto.split()
    objetivo = [w for w in (_norm_palabra(p) for p in valor.split()) if w]
    if not objetivo or not palabras:
        return valor.strip(), False
    norm = [_norm_palabra(p) for p in palabras]
    n = len(objetivo)
    mejor, mejor_ratio = None, 0.0
    for largo in {max(1, n - 1), n, n + 1}:
        for i in range(0, len(palabras) - largo + 1):
            trozo = [w for w in norm[i:i + largo] if w]
            ratio = difflib.SequenceMatcher(None, " ".join(objetivo), " ".join(trozo)).ratio()
            # A igualdad, el trozo de largo exacto.
            if ratio > mejor_ratio or (ratio == mejor_ratio and largo == n):
                mejor, mejor_ratio = (i, largo), ratio
    if mejor is None or mejor_ratio < umbral:
        return valor.strip(), False
    i, largo = mejor
    return " ".join(palabras[i:i + largo]).strip(" ,.;:¡!¿?\"'"), True


# ---------------------------------------------------------------------------
# Intérprete
# ---------------------------------------------------------------------------

@dataclass
class ResultadoLLM:
    skill: str | None
    params: dict[str, Any] = field(default_factory=dict)
    motivo: str | None = None   # por qué no hay skill (None si la hay)
    crudo: str = ""
    # Parámetros cuyo valor no aparece en la frase (el modelo lo reformuló o inventó).
    no_anclados: set[str] = field(default_factory=set)
    # Skill que propuso el modelo aunque se haya rechazado (por un valor inventado).
    propuesta: str | None = None


class InterpreteLLM:
    def __init__(self, registro: dict[str, Skill], servidor: ServidorLLM | None = None,
                 ejemplos: list[dict] | None = None):
        self.registro = registro
        self.servidor = servidor or ServidorLLM()
        self.ejemplos = cargar_ejemplos() if ejemplos is None else ejemplos
        self.esquema = esquema_ordenes(registro)

    def disponible(self) -> bool:
        return self.servidor.asegurar()

    def interpretar(self, texto: str) -> ResultadoLLM:
        if not self.servidor.asegurar():
            return ResultadoLLM(None, motivo="El LLM local no está disponible.")
        try:
            crudo = self.servidor.completar(construir_mensajes(texto, self.registro, self.ejemplos),
                                            self.esquema)
            datos = json.loads(crudo)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
            return ResultadoLLM(None, motivo=f"El LLM no ha devuelto una respuesta válida ({e}).")
        return self.validar(datos, texto, crudo)

    def validar(self, datos: dict, texto: str, crudo: str = "") -> ResultadoLLM:
        skill = datos.get("skill")
        if skill == NINGUNA:
            return ResultadoLLM(None, motivo="No sé hacer eso todavía.", crudo=crudo)
        if skill not in self.registro:
            return ResultadoLLM(None, motivo=f"El LLM propuso una skill desconocida: {skill!r}.", crudo=crudo)
        definicion = self.registro[skill]
        permitidos = _todos_parametros(definicion)
        params, no_anclados = {}, set()
        for clave, valor in (datos.get("parametros") or {}).items():
            if clave in permitidos and isinstance(valor, str) and valor.strip():
                params[clave], anclado = anclar(valor, texto)
                if not anclado:
                    no_anclados.add(clave)

        # Opcionales que el usuario no ha dicho (inventados o copia de otro valor): fuera.
        for clave in [c for c in params if c in definicion.parametros_opcionales]:
            otros = [normalizar(v) for c, v in params.items() if c != clave]
            if clave in no_anclados or any(normalizar(params[clave]) in o for o in otros):
                del params[clave]
                no_anclados.discard(clave)

        # Un nombre corto (app, juego...) que no aparece en la frase es una
        # invención ("cuánto es 15 por 3" -> abrir 'calculetta'): no se acepta.
        inventados = [c for c in no_anclados
                      if c in definicion.parametros and len(params[c].split()) <= 3]
        if inventados:
            return ResultadoLLM(None, params, motivo=(f"No he entendido bien la orden (¿{skill}? "
                                f"'{params[inventados[0]]}' no aparece en lo que has dicho)."),
                                crudo=crudo, no_anclados=no_anclados, propuesta=skill)
        return ResultadoLLM(skill, params, crudo=crudo, no_anclados=no_anclados)
