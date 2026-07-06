"""
Generaliza varias grabaciones de la misma acción en una plantilla
reutilizable, detectando automáticamente qué parte varía (el slot).

Enfoque: si grabas la misma acción 2+ veces con valores distintos
(ej. "discord" y "steam"), comparamos las secuencias de eventos paso
a paso. Todo lo que sea idéntico en todas las grabaciones es la parte
fija de la plantilla; el único paso que cambie de una grabación a
otra es, sin ambigüedad, el slot. No hace falta preguntar nada si hay
2+ grabaciones consistentes entre sí.

Los clics de ratón se comparan con una TOLERANCIA en píxeles (nunca
haces clic en el pixel exacto dos veces), en vez de exigir coordenadas
idénticas. Si la posición de un clic varía MÁS que esa tolerancia
entre grabaciones, no se puede convertir en slot (a diferencia del
texto escrito): un clic no tiene una forma genérica de sustituirse
por un valor nuevo cualquiera, así que se informa como no soportado.
"""

TOLERANCIA_PIXELES_CLICK = 15


class ErrorGeneralizacion(Exception):
    pass


def _clave_comparable(evento: dict):
    """
    Devuelve una clave hashable para comparar si dos eventos son
    'el mismo paso'. Para clics, se agrupa por bloques de píxeles
    (tolerancia), no por coordenada exacta.
    """
    tipo = evento["tipo"]
    valor = evento["valor"]
    if tipo == "click":
        return (
            valor["boton"],
            valor["x"] // TOLERANCIA_PIXELES_CLICK,
            valor["y"] // TOLERANCIA_PIXELES_CLICK,
        )
    return valor


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
        claves = {_clave_comparable(e) for e in eventos_en_posicion_i}

        if len(tipos) > 1:
            raise ErrorGeneralizacion(
                f"El paso {i} no coincide en tipo entre grabaciones: {tipos}. "
                "No se puede generalizar con seguridad."
            )

        tipo = eventos_en_posicion_i[0]["tipo"]

        if len(claves) == 1:
            # Idéntico (o dentro de tolerancia, si es un clic) en todas
            # las grabaciones: parte fija. Usamos el valor exacto de la
            # primera grabación como referencia.
            plantilla.append({"tipo": tipo, "valor": eventos_en_posicion_i[0]["valor"]})
        else:
            # Varía entre grabaciones: candidato a slot.
            if tipo != "escribir":
                if tipo == "click":
                    raise ErrorGeneralizacion(
                        f"El paso {i} es un clic en posiciones distintas entre "
                        "grabaciones (más allá de la tolerancia de "
                        f"{TOLERANCIA_PIXELES_CLICK}px). No se puede convertir "
                        "un clic en un slot de texto: si el punto de clic "
                        "depende del contenido (ej. un contacto en una lista), "
                        "esto necesita reconocimiento de texto en pantalla (OCR), "
                        "no la generalización simple que hacemos aquí."
                    )
                raise ErrorGeneralizacion(
                    f"El paso {i} varía pero no es de tipo 'escribir' (es '{tipo}'). "
                    "No se puede convertir en slot."
                )
            plantilla.append({"tipo": "escribir", "valor": "{slot}"})
            indices_variables.add(i)

    if len(indices_variables) == 0:
        print(
            "Aviso: no se detectó ninguna parte variable entre las grabaciones. "
            "Se generará una plantilla totalmente fija (sin slot) — correcto "
            "para acciones como 'cerrar ventana' o 'abrir calendario', donde "
            "no hace falta ningún dato variable. Si esta acción SÍ debería "
            "tener un slot, revisa que hayas usado valores distintos al grabar."
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
    print("Grabaciones idénticas (ya no es un error, genera plantilla fija):")
    plantilla_identica = generalizar([grabacion_discord, grabacion_discord])
    for evento in plantilla_identica:
        print(" ", evento)

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

    print("\n--- Casos con clic de ratón ---")
    # Clic en la misma posición (con pequeña variación natural de la mano)
    grabacion_a = [
        {"tipo": "click", "valor": {"x": 1850, "y": 1040, "boton": "Button.left", "imagen": ""}},
        {"tipo": "tecla_especial", "valor": "enter"},
    ]
    grabacion_b = [
        {"tipo": "click", "valor": {"x": 1855, "y": 1038, "boton": "Button.left", "imagen": ""}},
        {"tipo": "tecla_especial", "valor": "enter"},
    ]
    plantilla_click_fijo = generalizar([grabacion_a, grabacion_b])
    print("Clic casi en el mismo sitio (dentro de tolerancia) -> se trata como FIJO:")
    for evento in plantilla_click_fijo:
        print(" ", evento)

    # Clic en posiciones claramente distintas (ej. dos contactos distintos)
    grabacion_c = [
        {"tipo": "click", "valor": {"x": 1850, "y": 1040, "boton": "Button.left", "imagen": ""}},
    ]
    grabacion_d = [
        {"tipo": "click", "valor": {"x": 1850, "y": 1200, "boton": "Button.left", "imagen": ""}},
    ]
    try:
        generalizar([grabacion_c, grabacion_d])
    except ErrorGeneralizacion as e:
        print(f"\nClic en posiciones muy distintas -> {e}")