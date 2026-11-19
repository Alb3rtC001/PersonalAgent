"""
Catálogo de skills disponibles.

- Skills nativas: se importan y se añaden a SKILLS_NATIVAS.
- Plantillas grabadas: se publican añadiéndolas a recorder/catalogo.json
  (no hace falta tocar código).

Si una plantilla tiene el mismo nombre que una skill nativa, gana la nativa.
"""

from core.skills.abrir_aplicacion import AbrirAplicacion
from core.skills.base import Skill
from core.skills.grabada import cargar_skills_grabadas
from core.skills.cerrar_aplicacion import CerrarAplicacion
from core.skills.clic import HacerClic
from core.skills.compuesta import cargar_compuestas
from core.skills.crear_nota import CrearNota
from core.skills.plantilla import cargar_skills_plantilla
from core.skills.restaurar_ventana import RestaurarVentana
from core.skills.agenda import CancelarTarea, VerTareas
from core.skills.pantalla import LeerPantalla
from core.skills.steam import ActualizacionesSteam, EjecutarEnSteam
from core.skills.teclado import EscribirTexto, PulsarTeclas

SKILLS_NATIVAS: list[Skill] = [
    CrearNota(),
    AbrirAplicacion(),
    CerrarAplicacion(),
    RestaurarVentana(),
    EscribirTexto(),
    PulsarTeclas(),
    HacerClic(),
    EjecutarEnSteam(),        # sustituye a la plantilla grabada del mismo nombre
    ActualizacionesSteam(),
    VerTareas(),
    CancelarTarea(),
    LeerPantalla(),
]


def construir_registro() -> dict[str, Skill]:
    registro: dict[str, Skill] = {s.nombre: s for s in cargar_skills_plantilla()}
    # Grabaciones semánticas (recorder/grabadas/*.json); si se llaman igual que
    # una plantilla antigua, gana la grabación.
    registro.update({s.nombre: s for s in cargar_skills_grabadas()})
    registro.update({s.nombre: s for s in SKILLS_NATIVAS})
    # Órdenes compuestas aprendidas de tu uso (data/compuestas/*.json, fase 7): al
    # final, con el catálogo ya hecho (heredan el riesgo de su paso más delicado).
    # Nunca sustituyen a una skill que ya existe.
    for compuesta in cargar_compuestas():
        compuesta._registro = registro
        compuesta.riesgo = compuesta._riesgo_maximo()
        registro.setdefault(compuesta.nombre, compuesta)
    return registro


REGISTRO: dict[str, Skill] = construir_registro()
