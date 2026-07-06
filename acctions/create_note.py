"""
Acción: crear_nota

De momento es un placeholder. Aquí conectaremos más adelante la
extracción del contenido real de la nota (el slot) y el guardado
real en disco.
"""

from .base import AccionBase


class CrearNota(AccionBase):
    nombre_intencion = "crear_nota"

    def ejecutar(self, texto: str, slot: str) -> str:
        return f"[PLACEHOLDER] Crearía una nota con el contenido: '{slot}'"