"""
Reentrena el clasificador con nlu/dataset.json + tus frases aprendidas y solo
cambia el modelo si el nuevo no es peor que el actual.

Se mide con evaluacion/ordenes.json, solo el clasificador (sin LLM, en la CPU,
en un par de segundos):
- aciertos: skill y parámetros correctos;
- "seguras y mal": el clasificador está seguro (el router no consulta al LLM)
  y se equivoca. Es lo peligroso: se haría otra cosa sin preguntar.
El nuevo sustituye al actual si tiene al menos los mismos aciertos y no más
"seguras y mal". El anterior queda en nlu/modelo.pt.anterior (y su vocabulario).

    python -m aprendizaje.reentrenar              # aprende y reentrena
    python -m aprendizaje.reentrenar --simular    # solo dice qué pasaría
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from aprendizaje.datos import actualizar_aprendidas, cargar_aprendidas, frases_rechazadas  # noqa: E402
from core.memoria import cargar_episodios  # noqa: E402

RUTA_ORDENES = Path(__file__).parent.parent / "evaluacion" / "ordenes.json"
SEMILLA, EPOCHS, LR = 42, 300, 0.05
PROPORCION_VALIDACION = 0.15   # como nlu/training.py


@dataclass
class Medida:
    aciertos: int
    seguras_mal: int
    n: int

    def __str__(self) -> str:
        return f"{self.aciertos}/{self.n} aciertos, {self.seguras_mal} seguras y mal"

    def no_peor_que(self, otra: "Medida") -> bool:
        return self.aciertos >= otra.aciertos and self.seguras_mal <= otra.seguras_mal


def separar_base(base: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Las frases del dataset base con las que entrena nlu/training.py (deja fuera las mismas)."""
    indices = list(range(len(base)))
    random.Random(SEMILLA).shuffle(indices)
    fuera = set(indices[:max(1, int(len(base) * PROPORCION_VALIDACION))])
    return [f for i, f in enumerate(base) if i not in fuera]


def entrenar(base: list[tuple[str, str]], aprendidas: list[tuple[str, str]], ruta_modelo: Path,
             ruta_vocabulario: Path) -> None:
    """
    Entrena el clasificador como nlu/training.py (mismo vocabulario, mismas
    frases base fuera para validar) más TODAS las aprendidas. Así, sin frases
    aprendidas sale el mismo modelo que hay, y lo que cambie es por lo aprendido.
    """
    import numpy as np
    import torch
    import torch.nn as nn
    from nlu.model import ClasificadorIntencion, guardar_modelo
    from nlu.vocabulary import construir_vocabulario, guardar_vocabulario, tokenizar, vectorizar_bow

    random.seed(SEMILLA)
    torch.manual_seed(SEMILLA)
    vocab, intenciones = construir_vocabulario(base + aprendidas)
    guardar_vocabulario(vocab, intenciones, ruta_vocabulario)
    dataset = separar_base(base) + aprendidas
    X = torch.tensor(np.array([vectorizar_bow(tokenizar(f), vocab) for f, _ in dataset], dtype=np.float32))
    y = torch.tensor([intenciones[i] for _, i in dataset], dtype=torch.long)
    modelo = ClasificadorIntencion(dim_entrada=len(vocab), num_clases=len(intenciones))
    optimizador = torch.optim.Adam(modelo.parameters(), lr=LR)
    perdida = nn.CrossEntropyLoss()
    for _ in range(EPOCHS):
        modelo.train()
        optimizador.zero_grad()
        perdida(modelo(X), y).backward()
        optimizador.step()
    guardar_modelo(modelo, ruta_modelo)


def medir(ruta_modelo: Path | None, ruta_vocabulario: Path | None, ordenes: list[dict]) -> Medida:
    """El clasificador solo (sin LLM) frente a las frases de evaluación de una skill."""
    from core.registro import REGISTRO
    from core.router import ClasificadorBow, Router
    from evaluacion.evaluar import params_correctos, pasos_esperados

    router = Router(REGISTRO, clasificador=ClasificadorBow(ruta_modelo, ruta_vocabulario), usar_llm=False)
    aciertos = seguras_mal = 0
    for o in ordenes:
        variantes = [pasos_esperados(o)] + [pasos_esperados(v) for v in o.get("o_bien", [])]
        interp, dudosa = router.interpretar_clasificador(o["frase"])
        obtenido = [] if interp.motivo_rechazo else [(interp.skill, interp.params)]
        bien = any([s for s, _ in obtenido] == [s for s, _ in v]
                   and all(params_correctos(pe, po) for (_, pe), (_, po) in zip(v, obtenido)) for v in variantes)
        aciertos += bien
        seguras_mal += bool(obtenido) and not dudosa and not bien
    return Medida(aciertos, seguras_mal, len(ordenes))


@dataclass
class Informe:
    nuevas: list[tuple[str, str]]
    total_aprendidas: int
    antes: Medida
    despues: Medida | None
    cambiado: bool
    rechazadas: list[str]

    def texto(self) -> str:
        lineas = [f"Frases aprendidas de tu uso: {len(self.nuevas)} nuevas ({self.total_aprendidas} en total)."]
        lineas += [f"  + «{f}» → {i}" for f, i in self.nuevas[:10]]
        if self.despues is None:
            lineas.append(f"Nada nuevo que aprender: el clasificador sigue igual ({self.antes}).")
        elif self.cambiado:
            lineas.append(f"Clasificador reentrenado y cambiado: {self.antes} → {self.despues}.")
        else:
            lineas.append(f"Reentrenado, pero no mejora ({self.antes} → {self.despues}): me quedo con el actual.")
        if self.rechazadas:
            lineas.append("Órdenes recientes que no entendí (enséñamelas con «grabar» o dímelas de otra forma): "
                          + "; ".join(f"«{f}»" for f in self.rechazadas[:5]))
        return "\n".join(lineas)


def reentrenar(simular: bool = False, forzar: bool = False, ruta_episodios: Path | None = None,
               ruta_aprendidas: Path | None = None, dir_nlu: Path | None = None,
               ruta_ordenes: Path = RUTA_ORDENES) -> Informe:
    from nlu.dataset import RUTA_DATASET, cargar_dataset
    from nlu.model import RUTA_MODELO_DEFECTO
    from nlu.vocabulary import RUTA_VOCABULARIO

    dir_nlu = Path(dir_nlu) if dir_nlu else None
    ruta_modelo = dir_nlu / "modelo.pt" if dir_nlu else RUTA_MODELO_DEFECTO
    ruta_vocab = dir_nlu / "vocabulary.json" if dir_nlu else Path(RUTA_VOCABULARIO)
    base = cargar_dataset(dir_nlu / "dataset.json" if dir_nlu else RUTA_DATASET)
    episodios = cargar_episodios(ruta_episodios)
    if simular:
        from aprendizaje.datos import _clave, frases_de_episodios
        aprendidas = cargar_aprendidas(ruta_aprendidas)
        nuevas = frases_de_episodios(episodios, {_clave(f) for f, _ in base + aprendidas})
        aprendidas = aprendidas + nuevas
    else:
        aprendidas, nuevas = actualizar_aprendidas(base, ruta_episodios, ruta_aprendidas)
    rechazadas = frases_rechazadas(episodios)
    ordenes = json.loads(Path(ruta_ordenes).read_text(encoding="utf-8"))
    antes = medir(ruta_modelo, ruta_vocab, ordenes)
    if not aprendidas and not forzar:
        return Informe(nuevas, 0, antes, None, False, rechazadas)

    with tempfile.TemporaryDirectory() as tmp:
        modelo_nuevo, vocab_nuevo = Path(tmp) / "modelo.pt", Path(tmp) / "vocabulary.json"
        entrenar(base, aprendidas, modelo_nuevo, vocab_nuevo)
        despues = medir(modelo_nuevo, vocab_nuevo, ordenes)
        cambiar = not simular and (forzar or despues.no_peor_que(antes))
        if cambiar:
            for ruta in (ruta_modelo, ruta_vocab):
                if ruta.exists():
                    shutil.copy2(ruta, ruta.with_name(ruta.name + ".anterior"))
            shutil.copy2(modelo_nuevo, ruta_modelo)
            shutil.copy2(vocab_nuevo, ruta_vocab)
    return Informe(nuevas, len(aprendidas), antes, despues, cambiar, rechazadas)


def main() -> None:
    ap = argparse.ArgumentParser(description="Reentrena el clasificador con lo aprendido de tu uso.")
    ap.add_argument("--simular", action="store_true", help="no cambia nada: solo dice qué pasaría")
    ap.add_argument("--forzar", action="store_true", help="cambia el modelo aunque no mejore")
    args = ap.parse_args()
    print(reentrenar(simular=args.simular, forzar=args.forzar).texto())


if __name__ == "__main__":
    main()
