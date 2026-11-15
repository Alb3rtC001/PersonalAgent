"""
Skills grabadas con la grabadora semántica (recorder/grabadora_semantica.py).

Cada grabación es un archivo recorder/grabadas/<nombre>.json con su
descripción (lo que lee el LLM), su parámetro (el texto que cambia cada vez,
p. ej. {busqueda}) y sus pasos. Al reproducirla:

- cada paso busca su ventana por programa y título, y dentro el CONTROL por
  su identificador o su nombre (no por coordenadas): da igual dónde esté la
  ventana o qué tamaño tenga;
- antes de escribir, pone el foco en el campo donde se escribió al grabar;
- respeta las ventanas prohibidas y el botón de pánico;
- su riesgo es "alto" por defecto: con POLITICA_RIESGO se confirma siempre.

Si un control no tiene nombre ni identificador (juegos, lienzos), se usa su
posición relativa dentro de la ventana como último recurso.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from core import control, uia
from core.estado import listar_ventanas_abiertas, normalizar, poner_foco
from core.seguridad import registrar_actividad, ventana_prohibida
from core.skills.base import Resultado, Skill
from core.teclado import ErrorTeclas, escribir, interpretar_teclas, pulsar

log = logging.getLogger("personalagent")

RUTA_GRABADAS = Path(__file__).resolve().parents[2] / "recorder" / "grabadas"
PAUSA_ENTRE_PASOS = 0.35
PROCESOS_COMPARTIDOS = {"applicationframehost.exe"}   # todas las apps de la Store: se distingue por el título


def localizar_ventana(descripcion: dict | None) -> dict | None:
    """La ventana abierta que corresponde a la grabada (mismo programa; título si hace falta)."""
    if not descripcion:
        return None
    proceso = normalizar(descripcion.get("proceso") or "")
    titulo = normalizar(descripcion.get("titulo") or "")
    candidatas = [v for v in listar_ventanas_abiertas(incluir_ocultas=True)
                  if normalizar(v.get("proceso") or "") == proceso]
    if proceso in PROCESOS_COMPARTIDOS or len(candidatas) > 1:
        iguales = [v for v in candidatas if normalizar(v["titulo"]) == titulo]
        if iguales or proceso in PROCESOS_COMPARTIDOS:
            candidatas = iguales
    candidatas.sort(key=lambda v: (v["minimizada"] or v["oculta"]))
    return candidatas[0] if candidatas else None


def _sustituir(texto: str, params: dict[str, Any]) -> str:
    for clave, valor in params.items():
        texto = texto.replace("{" + clave + "}", str(valor))
    return texto


class SkillGrabada(Skill):
    def __init__(self, datos: dict[str, Any]):
        self.nombre = datos["nombre"]
        self.descripcion = datos.get("descripcion") or f"Acción grabada '{self.nombre}'."
        self.parametros = dict(datos.get("parametros") or {})
        self.pasos = datos["pasos"]
        self.riesgo = datos.get("riesgo", "alto")
        self.requiere_confirmacion = bool(datos.get("requiere_confirmacion", False))
        self.parametros_literales = frozenset(self.parametros)   # el texto, tal como lo dices
        self.interpretar_con_llm = bool(self.parametros)
        self.coste = 2

    def ejecutar(self, **params: Any) -> Resultado:
        with uia.en_hilo():
            for i, paso in enumerate(self.pasos, 1):
                control.comprobar()   # botón de pánico
                error = self._paso(paso, params)
                if error:
                    return Resultado(False, f"'{self.nombre}', paso {i} de {len(self.pasos)} "
                                            f"({paso['tipo']}): {error}", datos={"paso": i})
                time.sleep(PAUSA_ENTRE_PASOS)
        return Resultado(True, f"'{self.nombre}' hecha ({len(self.pasos)} pasos).",
                         datos={"pasos": len(self.pasos)})

    def _paso(self, paso: dict, params: dict[str, Any]) -> str | None:
        tipo = paso["tipo"]
        if tipo == "contrasena_omitida":
            return "la grabación tenía un campo de contraseña, que no se graba: ese paso tienes que hacerlo tú."
        ventana = localizar_ventana(paso.get("ventana"))
        if paso.get("ventana") and ventana is None:
            v = paso["ventana"]
            return f"no encuentro abierta la ventana '{v.get('titulo')}' ({v.get('proceso')})."
        if ventana is not None:
            prohibida = ventana_prohibida(ventana)
            if prohibida:
                registrar_actividad("seguridad", f"Grabación '{self.nombre}' detenida: {prohibida}", False)
                return prohibida
            if not poner_foco(ventana["hwnd"]):
                return f"no he podido darle el foco a '{ventana['titulo']}'."

        if tipo == "clic":
            return self._clic(paso, ventana)
        if tipo == "escribir":
            texto = _sustituir(paso["texto"], params)
            if paso.get("control", {}).get("id") or paso.get("control", {}).get("nombre"):
                campo = uia.buscar_control(ventana["hwnd"], paso["control"], espera=2.0)
                if campo is not None:
                    try:
                        campo.SetFocus()
                    except Exception:
                        pass
            log.info("Escribiendo '%s'…", texto)
            escribir(texto)
            return None
        if tipo == "teclas":
            try:
                for combinacion in interpretar_teclas(paso["teclas"]):
                    pulsar(combinacion)
            except ErrorTeclas as e:
                return str(e)
            return None
        return f"tipo de paso desconocido: {tipo}"

    def _clic(self, paso: dict, ventana: dict) -> str | None:
        import pyautogui
        descripcion = paso.get("control") or {}
        objetivo = uia.buscar_control(ventana["hwnd"], descripcion) if ventana else None
        if objetivo is not None:
            x, y = uia.centro(objetivo)
            log.info("Clic en '%s'", descripcion.get("nombre") or descripcion.get("id"))
        elif not (descripcion.get("id") or descripcion.get("nombre")) and ventana and paso.get("relativo"):
            # Control sin identidad (juego, lienzo): posición relativa dentro de la ventana.
            r = ventana["rect"]
            x = int(r["left"] + paso["relativo"][0] * (r["right"] - r["left"]))
            y = int(r["top"] + paso["relativo"][1] * (r["bottom"] - r["top"]))
            log.info("Clic por posición relativa (el control no tiene nombre)")
        else:
            return (f"no encuentro el control '{descripcion.get('nombre') or descripcion.get('id')}' "
                    f"({descripcion.get('tipo', '').replace('Control', '').lower()}).")
        pyautogui.click(x, y, button=paso.get("boton", "left"))
        return None


# ---------------------------------------------------------------------------
# Guardar y cargar
# ---------------------------------------------------------------------------

def nombre_valido(nombre: str) -> str:
    """'Buscar en Spotify' -> 'buscar_en_spotify'"""
    return re.sub(r"[^a-z0-9]+", "_", normalizar(nombre)).strip("_")


def guardar_grabacion(nombre: str, descripcion: str, pasos: list[dict],
                      parametros: dict[str, str] | None = None, ruta: Path = RUTA_GRABADAS) -> Path:
    ruta.mkdir(parents=True, exist_ok=True)
    datos = {"nombre": nombre_valido(nombre), "descripcion": descripcion, "parametros": parametros or {},
             "riesgo": "alto", "pasos": pasos}
    archivo = ruta / f"{datos['nombre']}.json"
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return archivo


def cargar_skills_grabadas(ruta: Path = RUTA_GRABADAS) -> list[SkillGrabada]:
    skills = []
    for archivo in sorted(ruta.glob("*.json")) if ruta.is_dir() else []:
        try:
            skills.append(SkillGrabada(json.loads(archivo.read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError) as e:
            log.warning("No pude cargar la grabación %s: %s", archivo.name, e)
    return skills
