"""
Skill nativa: crear una nota.

Escribe un archivo Markdown en la carpeta de notas (config.RUTA_NOTAS)
y verifica que el archivo existe con el contenido esperado. No depende
de ninguna app ni de coordenadas de pantalla.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from config import RUTA_NOTAS
from core.skills.base import Resultado, Skill

MAX_PALABRAS_TITULO = 8
MAX_LARGO_NOMBRE = 40


def _titulo_desde(contenido: str) -> str:
    primera_linea = contenido.strip().splitlines()[0]
    palabras = primera_linea.split()
    titulo = " ".join(palabras[:MAX_PALABRAS_TITULO])
    return titulo[:1].upper() + titulo[1:]


def _slug(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )
    slug = re.sub(r"[^a-z0-9]+", "-", sin_tildes).strip("-")
    return slug[:MAX_LARGO_NOMBRE].rstrip("-") or "nota"


class CrearNota(Skill):
    nombre = "crear_nota"
    descripcion = (
        "Crea una nota de texto con el contenido indicado y la guarda como "
        "archivo Markdown en la carpeta de notas del usuario."
    )
    parametros = {"contenido": "Texto que se quiere apuntar"}
    parametros_opcionales = {"titulo": "Título; si falta se genera a partir del contenido"}

    def __init__(self, carpeta: Path | None = None):
        self.carpeta = Path(carpeta) if carpeta else RUTA_NOTAS

    def _ruta_libre(self, momento: datetime, titulo: str) -> Path:
        base = f"{momento:%Y-%m-%d_%H%M%S}_{_slug(titulo)}"
        ruta = self.carpeta / f"{base}.md"
        n = 2
        while ruta.exists():
            ruta = self.carpeta / f"{base}_{n}.md"
            n += 1
        return ruta

    def ejecutar(self, contenido: str = "", titulo: str | None = None) -> Resultado:
        contenido = (contenido or "").strip()
        if not contenido:
            return Resultado(False, "La nota está vacía.", falta="contenido")

        titulo = (titulo or "").strip() or _titulo_desde(contenido)
        ahora = datetime.now()

        self.carpeta.mkdir(parents=True, exist_ok=True)
        ruta = self._ruta_libre(ahora, titulo)
        ruta.write_text(
            f"# {titulo}\n\n{contenido}\n\n_Creada: {ahora:%Y-%m-%d %H:%M}_\n",
            encoding="utf-8",
        )
        return Resultado(
            True,
            f"Nota '{titulo}' guardada en {ruta}",
            datos={"ruta": str(ruta), "titulo": titulo, "contenido": contenido},
        )

    def verificar(self, resultado: Resultado) -> bool:
        if not resultado.ok:
            return False
        ruta = Path(resultado.datos.get("ruta", ""))
        return ruta.is_file() and resultado.datos["contenido"] in ruta.read_text(encoding="utf-8")
