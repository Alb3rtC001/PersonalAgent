"""
Dispatcher: conecta el clasificador de intención con las acciones reales.

Aplica dos redes de seguridad antes de ejecutar nada:
1. Si la intención predicha es "ninguna", no se ejecuta ninguna acción.
2. Si la confianza está por debajo de UMBRAL_CONFIANZA (config.py),
   tampoco se ejecuta, aunque la intención predicha no sea "ninguna"
   (el modelo puede estar dudando entre una acción real y "ninguna").
"""

import sys
from pathlib import Path

RUTA_BASE = Path(__file__).parent
sys.path.append(str(RUTA_BASE / "nlu"))

from vocabulary import tokenizar, vectorizar_bow, cargar_vocabulario  # noqa: E402
from model import cargar_modelo, predecir_proba  # noqa: E402
from slots import extraer_slot  # noqa: E402

from acctions.open_application import AbrirAplicacion  # noqa: E402
from acctions.create_note import CrearNota  # noqa: E402
from config import UMBRAL_CONFIANZA  # noqa: E402

RUTA_VOCAB = RUTA_BASE / "nlu" / "vocabulary.json"

# Registro de acciones disponibles. Añadir una acción nueva es
# tan simple como crear su clase en acciones/ y añadirla aquí.
ACCIONES = {
    "abrir_aplicacion": AbrirAplicacion(),
    "crear_nota": CrearNota(),
}


class Dispatcher:
    def __init__(self):
        self.vocab, self.intenciones = cargar_vocabulario(RUTA_VOCAB)
        self.idx_a_intencion = {v: k for k, v in self.intenciones.items()}
        self.modelo = cargar_modelo()

    def procesar(self, texto: str) -> str:
        vector = vectorizar_bow(tokenizar(texto), self.vocab)
        probas = predecir_proba(self.modelo, vector)
        idx = probas.argmax().item()
        confianza = probas[idx].item()
        intencion = self.idx_a_intencion[idx]

        if intencion == "ninguna":
            return f"No he entendido esa orden (confianza={confianza:.2f})"

        if confianza < UMBRAL_CONFIANZA:
            return (
                f"No estoy seguro de lo que pides "
                f"(predicción: {intencion}, confianza={confianza:.2f} "
                f"< umbral {UMBRAL_CONFIANZA})"
            )

        accion = ACCIONES.get(intencion)
        if accion is None:
            return f"Intención '{intencion}' reconocida pero sin acción implementada todavía"

        slot = extraer_slot(texto, intencion)
        return accion.ejecutar(texto, slot)


if __name__ == "__main__":
    dispatcher = Dispatcher()
    print("Escribe una orden (o 'salir' para terminar)")
    while True:
        texto = input("> ")
        if texto.strip().lower() == "salir":
            break
        print(dispatcher.procesar(texto))