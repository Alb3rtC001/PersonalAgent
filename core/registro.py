"""
Catálogo de skills disponibles.

- Skills nativas: se importan y se añaden a SKILLS_NATIVAS.
- Plantillas grabadas: se publican añadiéndolas a recorder/catalogo.json
  (no hace falta tocar código).

Si una plantilla tiene el mismo nombre que una skill nativa, gana la nativa.
"""

from core.skills.abrir_aplicacion import AbrirAplicacion
from core.skills.base import Skill
from core.skills.cerrar_aplicacion import CerrarAplicacion
from core.skills.crear_nota import CrearNota
from core.skills.plantilla import cargar_skills_plantilla
from core.skills.restaurar_ventana import RestaurarVentana

SKILLS_NATIVAS: list[Skill] = [
    CrearNota(),
    AbrirAplicacion(),
    CerrarAplicacion(),
    RestaurarVentana(),
]


def construir_registro() -> dict[str, Skill]:
    registro: dict[str, Skill] = {s.nombre: s for s in cargar_skills_plantilla()}
    registro.update({s.nombre: s for s in SKILLS_NATIVAS})
    return registro


REGISTRO: dict[str, Skill] = construir_registro()
