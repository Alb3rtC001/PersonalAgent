"""
Interfaz común para todas las acciones.

Cada acción nueva (abrir_aplicacion, crear_nota, reproducir_musica...)
debe heredar de AccionBase e implementar ejecutar(). Así el dispatcher
puede tratar a todas las acciones de la misma forma, sin importar lo
que hagan por dentro.
"""

from abc import ABC, abstractmethod


class AccionBase(ABC):
    nombre_intencion: str = ""

    @abstractmethod
    def ejecutar(self, texto: str, slot: str) -> str:
        """
        Ejecuta la acción.
        - texto: la frase original completa del usuario (por si se necesita).
        - slot: la parte variable ya extraída (ej. el nombre de la app,
          o el contenido de la nota), lista para usar.
        Devuelve un mensaje de resultado (para mostrar o loggear).
        """
        raise NotImplementedError