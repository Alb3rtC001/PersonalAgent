"""
Clasificador de intención — versión baseline.

Es intencionadamente lo más simple posible: una sola capa lineal.
Esto es matemáticamente una regresión logística multinomial.

Nota sobre la activación: CrossEntropyLoss en PyTorch ya aplica
log_softmax internamente, así que el forward() devuelve logits
"en crudo", sin softmax. Softmax solo se aplica explícitamente
cuando queremos leer probabilidades (en predecir_proba), no durante
el entrenamiento.
"""

from pathlib import Path

import torch
import torch.nn as nn

# Ruta absoluta basada en la ubicación de este archivo, no en el
# directorio desde el que se ejecute el script. Así da igual si
# entrenas con "python training.py" desde dentro de nlu/ o con
# "python .\nlu\training.py" desde la raíz del proyecto: el modelo
# siempre se guarda y se busca en el mismo sitio.
RUTA_MODELO_DEFECTO = Path(__file__).parent / "modelo.pt"


class ClasificadorIntencion(nn.Module):
    def __init__(self, dim_entrada: int, num_clases: int):
        super().__init__()
        self.lineal = nn.Linear(dim_entrada, num_clases)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.lineal(x)  # logits, sin activación


def predecir_proba(modelo: ClasificadorIntencion, vector) -> torch.Tensor:
    """
    Dado un vector bag-of-words (numpy array 1D), devuelve las
    probabilidades (softmax) para cada intención.
    """
    modelo.eval()
    with torch.no_grad():
        x = torch.tensor(vector, dtype=torch.float32).unsqueeze(0)
        logits = modelo(x)
        return torch.softmax(logits, dim=1).squeeze(0)


def guardar_modelo(modelo: ClasificadorIntencion, ruta=None) -> None:
    ruta = ruta or RUTA_MODELO_DEFECTO
    torch.save(
        {
            "state_dict": modelo.state_dict(),
            "dim_entrada": modelo.lineal.in_features,
            "num_clases": modelo.lineal.out_features,
        },
        ruta,
    )


def cargar_modelo(ruta=None) -> ClasificadorIntencion:
    """Reconstruye el modelo con las dimensiones correctas y carga los pesos."""
    ruta = ruta or RUTA_MODELO_DEFECTO
    checkpoint = torch.load(ruta, weights_only=False)
    modelo = ClasificadorIntencion(checkpoint["dim_entrada"], checkpoint["num_clases"])
    modelo.load_state_dict(checkpoint["state_dict"])
    modelo.eval()
    return modelo