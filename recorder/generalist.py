"""
Generaliza varias grabaciones de la misma acción en una plantilla
reutilizable, detectando automáticamente qué parte varía (el slot).

Enfoque: si grabas la misma acción 2+ veces con valores distintos
(ej. "discord" y "steam"), comparamos las secuencias de eventos paso
a paso. Todo lo que sea idéntico en todas las grabaciones es la parte
fija de la plantilla; el único paso que cambie de una grabación a
otra es, sin ambigüedad, el slot. No hace falta preguntar nada si hay
2+ grabaciones consistentes entre sí.
"""


class ErrorGeneralizacion(Exception):
    pass


def generalizar(grabaciones: list[list[dict]]) -> list[dict]:
    """
    grabaciones: lista de secuencias de eventos (cada una viene de una
    grabación distinta de la MISMA acción, con valores distintos).

    Devuelve la plantilla generalizada: la misma secuencia de eventos,
    con el evento "escribir" que varía sustituido por
    {"tipo": "escribir", "valor": "{slot}"}.
    """
    if len(grabaciones) < 2:
        raise ErrorGeneralizacion(
            "Se necesitan al menos 2 grabaciones para detectar automáticamente "
            "qué parte es el slot variable."
        )

    longitud = len(grabaciones[0])
    for grabacion in grabaciones[1:]:
        if len(grabacion) != longitud:
            raise ErrorGeneralizacion(
                "Las grabaciones no tienen el mismo número de pasos. "
                "Repite la demostración de forma más consistente."
            )

    plantilla = []
    indices_variables = set()

    for i in range(longitud):
        eventos_en_posicion_i = [g[i] for g in grabaciones]
        tipos = {e["tipo"] for e in eventos_en_posicion_i}
        valores = {e["valor"] for e in eventos_en_posicion_i}

        if len(tipos) > 1:
            raise ErrorGeneralizacion(
                f"El paso {i} no coincide en tipo entre grabaciones: {tipos}. "
                "No se puede generalizar con seguridad."
            )

        tipo = eventos_en_posicion_i[0]["tipo"]

        if len(valores) == 1:
            # Idéntico en todas las grabaciones: parte fija.
            plantilla.append({"tipo": tipo, "valor": eventos_en_posicion_i[0]["valor"]})
        else:
            # Varía entre grabaciones: candidato a slot.
            if tipo != "escribir":
                raise ErrorGeneralizacion(
                    f"El paso {i} varía pero no es de tipo 'escribir' (es '{tipo}'). "
                    "No se puede convertir en slot."
                )
            plantilla.append({"tipo": "escribir", "valor": "{slot}"})
            indices_variables.add(i)

    if len(indices_variables) == 0:
        raise ErrorGeneralizacion(
            "Las grabaciones son idénticas, no se detectó ninguna parte variable. "
            "¿Usaste valores distintos en cada demostración?"
        )
    if len(indices_variables) > 1:
        raise ErrorGeneralizacion(
            f"Se detectaron {len(indices_variables)} partes variables. "
            "De momento solo se soportan plantillas con un único slot."
        )

    return plantilla


if __name__ == "__main__":
    grabacion_discord = [
        {"tipo": "tecla_especial", "valor": "win"},
        {"tipo": "escribir", "valor": "discord"},
        {"tipo": "tecla_especial", "valor": "enter"},
    ]
    grabacion_steam = [
        {"tipo": "tecla_especial", "valor": "win"},
        {"tipo": "escribir", "valor": "steam"},
        {"tipo": "tecla_especial", "valor": "enter"},
    ]

    plantilla = generalizar([grabacion_discord, grabacion_steam])
    print("Plantilla generalizada a partir de 2 grabaciones:")
    for evento in plantilla:
        print(" ", evento)

    print("\n--- Casos de error esperados ---")
    try:
        generalizar([grabacion_discord, grabacion_discord])
    except ErrorGeneralizacion as e:
        print(f"Grabaciones idénticas -> {e}")

    grabacion_incompleta = [
        {"tipo": "tecla_especial", "valor": "win"},
        {"tipo": "escribir", "valor": "steam"},
    ]
    try:
        generalizar([grabacion_discord, grabacion_incompleta])
    except ErrorGeneralizacion as e:
        print(f"Distinto número de pasos -> {e}")

    grabacion_dos_variables = [
        {"tipo": "tecla_especial", "valor": "ctrl"},
        {"tipo": "escribir", "valor": "otra_cosa"},
        {"tipo": "tecla_especial", "valor": "enter"},
    ]
    try:
        generalizar([grabacion_discord, grabacion_dos_variables])
    except ErrorGeneralizacion as e:
        print(f"Tipo distinto en un paso -> {e}")