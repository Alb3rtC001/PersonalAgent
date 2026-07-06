"""
Entrenamiento del clasificador de intención.

Ejecuta este script cada vez que quieras que el modelo tenga en cuenta
frases nuevas añadidas al dataset (vía agregar_frase en dataset.py).

Vuelve a construir el vocabulario desde el dataset ACTUAL cada vez que
se entrena, para garantizar que el modelo y el vocabulario guardado en
disco están siempre sincronizados entre sí.
"""

import random

import numpy as np
import torch
import torch.nn as nn

from dataset import cargar_dataset
from vocabulary import construir_vocabulario, guardar_vocabulario, tokenizar, vectorizar_bow
from model import ClasificadorIntencion, guardar_modelo, predecir_proba

SEMILLA = 42
EPOCHS = 300
LR = 0.05
PROPORCION_VALIDACION = 0.15


def preparar_datos():
    dataset = cargar_dataset()
    vocab, intenciones = construir_vocabulario(dataset)
    guardar_vocabulario(vocab, intenciones)

    X, y = [], []
    for frase, intencion in dataset:
        tokens = tokenizar(frase)
        vector = vectorizar_bow(tokens, vocab)
        X.append(vector)
        y.append(intenciones[intencion])

    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int64)
    return X, y, vocab, intenciones


def separar_train_val(X, y, proporcion=PROPORCION_VALIDACION, semilla=SEMILLA):
    random.seed(semilla)
    indices = list(range(len(X)))
    random.shuffle(indices)
    n_val = max(1, int(len(X) * proporcion))
    val_idx, train_idx = indices[:n_val], indices[n_val:]
    return X[train_idx], y[train_idx], X[val_idx], y[val_idx]


def entrenar():
    X, y, vocab, intenciones = preparar_datos()
    X_train, y_train, X_val, y_val = separar_train_val(X, y)

    modelo = ClasificadorIntencion(dim_entrada=len(vocab), num_clases=len(intenciones))
    optimizador = torch.optim.Adam(modelo.parameters(), lr=LR)
    perdida_fn = nn.CrossEntropyLoss()

    X_train_t, y_train_t = torch.tensor(X_train), torch.tensor(y_train)
    X_val_t, y_val_t = torch.tensor(X_val), torch.tensor(y_val)

    for epoch in range(1, EPOCHS + 1):
        modelo.train()
        optimizador.zero_grad()
        logits = modelo(X_train_t)
        perdida = perdida_fn(logits, y_train_t)
        perdida.backward()
        optimizador.step()

        if epoch == 1 or epoch % 50 == 0:
            modelo.eval()
            with torch.no_grad():
                acc_train = (modelo(X_train_t).argmax(dim=1) == y_train_t).float().mean().item()
                acc_val = (modelo(X_val_t).argmax(dim=1) == y_val_t).float().mean().item()
            print(f"Epoch {epoch:4d} | loss={perdida.item():.4f} | acc_train={acc_train:.2f} | acc_val={acc_val:.2f}")

    guardar_modelo(modelo)
    print(f"\nModelo guardado en modelo.pt")
    print(f"Intenciones: {intenciones}")
    return modelo, vocab, intenciones


if __name__ == "__main__":
    modelo, vocab, intenciones = entrenar()
    idx_a_intencion = {v: k for k, v in intenciones.items()}

    print("\n--- Prueba con frases nuevas (no vistas en el dataset) ---")
    frases_prueba = [
        "abre notion",
        "abreme el bloc de notas",
        "apunta que hay que sacar la basura",
        "quiero dejar constancia de una idea",
        "que tiempo hace hoy",  # fuera de dominio, a propósito
    ]
    for frase in frases_prueba:
        vector = vectorizar_bow(tokenizar(frase), vocab)
        probas = predecir_proba(modelo, vector)
        idx_pred = probas.argmax().item()
        print(f"'{frase}' -> {idx_a_intencion[idx_pred]} (confianza={probas[idx_pred]:.2f})")
