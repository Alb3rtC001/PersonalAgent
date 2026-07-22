"""
generalist.py

Generaliza varias grabaciones de la misma acción en una plantilla
reutilizable, detectando automáticamente qué parte varía (el slot).

La tolerancia de píxeles para clics se puede configurar por plantilla
(pasada como parámetro a generalizar()). El valor por defecto viene
de storage.TOLERANCIA_DEFAULT.
"""

from storage import TOLERANCIA_DEFAULT


class ErrorGeneralizacion(Exception):
    pass


def _id(indice: int) -> str:
    return f"#{indice + 1:02d}"


def _clave_comparable(evento: dict, tolerancia_px: int):
    tipo = evento["tipo"]
    valor = evento["valor"]
    if tipo == "click":
        x = valor.get("x_abs", valor.get("x", 0))
        y = valor.get("y_abs", valor.get("y", 0))
        return (
            valor.get("boton", "Button.left"),
            x // tolerancia_px,
            y // tolerancia_px,
        )
    return valor


def generalizar(grabaciones: list[list[dict]],
                tolerancia_px: int = TOLERANCIA_DEFAULT) -> list[dict]:
    """
    grabaciones: lista de secuencias de eventos de la misma acción.
    tolerancia_px: margen en píxeles para considerar dos clics iguales.
                   Por defecto usa TOLERANCIA_DEFAULT de storage.py.
                   Para clics en barra de tareas o iconos grandes,
                   un valor de 50-80 es más apropiado.

    Devuelve la plantilla generalizada.
    """
    if len(grabaciones) < 2:
        raise ErrorGeneralizacion(
            "Se necesitan al menos 2 grabaciones para detectar "
            "automáticamente qué parte es el slot variable."
        )

    longitud_ref = len(grabaciones[0])
    problemas = []
    for i, g in enumerate(grabaciones[1:], start=1):
        if len(g) != longitud_ref:
            problemas.append(
                f"{_id(0)} ({longitud_ref} pasos) y "
                f"{_id(i)} ({len(g)} pasos)"
            )
    if problemas:
        raise ErrorGeneralizacion(
            f"Las grabaciones [{' | '.join(problemas)}] no tienen el mismo "
            "número de pasos. Repite la demostración de forma más consistente."
        )

    plantilla = []
    indices_variables = set()

    for i in range(longitud_ref):
        eventos_i = [g[i] for g in grabaciones]
        tipos = {e["tipo"] for e in eventos_i}
        claves = {_clave_comparable(e, tolerancia_px) for e in eventos_i}

        if len(tipos) > 1:
            ids = " ".join(_id(j) for j in range(len(grabaciones)))
            raise ErrorGeneralizacion(
                f"El paso {i + 1} no coincide en tipo entre grabaciones "
                f"[{ids}]: {tipos}."
            )

        tipo = eventos_i[0]["tipo"]

        if len(claves) == 1:
            if tipo == "click":
                valor_ref = eventos_i[0]["valor"]
                valor_guardado = {"boton": valor_ref.get("boton", "Button.left"),
                                  "ventana": valor_ref.get("ventana")}
                if valor_ref.get("x_rel") is not None:
                    valor_guardado["x_rel"] = valor_ref["x_rel"]
                    valor_guardado["y_rel"] = valor_ref["y_rel"]
                else:
                    valor_guardado["x_abs"] = valor_ref.get("x_abs", valor_ref.get("x", 0))
                    valor_guardado["y_abs"] = valor_ref.get("y_abs", valor_ref.get("y", 0))
                plantilla.append({"tipo": tipo, "valor": valor_guardado})
            else:
                plantilla.append({"tipo": tipo, "valor": eventos_i[0]["valor"]})
        else:
            if tipo != "escribir":
                ids = " ".join(_id(j) for j in range(len(grabaciones)))
                if tipo == "click":
                    raise ErrorGeneralizacion(
                        f"El paso {i + 1} es un clic en posiciones distintas "
                        f"entre grabaciones [{ids}] (más allá de {tolerancia_px}px). "
                        "Los clics variables no se pueden convertir en slot. "
                        f"Prueba a subir la tolerancia con: "
                        f"python -c \"from recorder.storage import establecer_tolerancia; "
                        f"establecer_tolerancia('nombre_accion', 80)\""
                    )
                raise ErrorGeneralizacion(
                    f"El paso {i + 1} varía pero no es 'escribir' "
                    f"(es '{tipo}') entre grabaciones [{ids}]."
                )
            plantilla.append({"tipo": "escribir", "valor": "{slot}"})
            indices_variables.add(i)

    if len(indices_variables) == 0:
        print("Aviso: plantilla totalmente fija (sin slot).")
    elif len(indices_variables) > 1:
        raise ErrorGeneralizacion(
            f"Se detectaron {len(indices_variables)} partes variables "
            f"(pasos {[i + 1 for i in sorted(indices_variables)]}). "
            "Solo se soporta un único slot por plantilla."
        )

    return plantilla