"""
Extracción de slots (la parte variable de la frase) mediante
patrones disparadores por intención.

Enfoque deliberadamente simple: en vez de un modelo nuevo, listamos
las frases disparadoras típicas de cada intención (basadas en el
propio dataset) y las quitamos del texto. Lo que queda es el slot.

Limitación honesta: esto solo funciona bien para frases parecidas
a las que ya conocemos. Una forma de pedirlo muy distinta a los
disparadores listados puede dejar restos sin limpiar en el slot.
Es un punto de partida sencillo, no la versión final.
"""

import re
import unicodedata

# Frases/palabras disparadoras que NO forman parte del valor del slot.
# Se prueban de más larga a más corta, para que un disparador largo
# ("crea una nota que diga") se quite entero antes que uno corto
# que sea parte de él ("crea").
DISPARADORES = {
    "abrir_aplicacion": [
        "hazme el favor de abrir", "puedes abrirme", "puedes abrir",
        "quiero abrir", "necesito abrir", "pon en marcha", "me abres",
        "abreme", "abrir", "abre", "inicia", "iniciar", "ejecuta",
        "ejecutar", "lanza", "lanzar", "arranca", "arrancar",
        "por favor",
    ],
    "crear_nota": [
        "hazme el favor de anotar", "puedes apuntar esto por mi",
        "puedes crear una nota", "quiero crear una nota",
        "quiero apuntar algo", "necesito anotar una idea",
        "necesito una nota nueva", "quiero guardar una nota de texto",
        "quiero dejar apuntado algo",
        "crea una nota con el titulo", "crea una nota que diga",
        "crea una nota con lo que te voy a decir", "crea una nota rapida",
        "crea una nota vacia", "crea una nota",
        "hazme una nota que diga", "hazme una nota",
        "escribe una nota sobre", "escribe una nota",
        "guarda una nota con", "guarda una nota sobre", "guarda una nota",
        "guarda esto en una nota",
        "toma nota de esto", "toma nota que", "toma nota",
        "apunta la idea que tengo", "apunta una idea para el proyecto",
        "apunta que", "apunta esto", "apunta",
        "anotame esto", "anotame", "anota que", "anota esto", "anota",
        "apuntame lo que digo", "apuntame",
    ],
}

# Artículos que pueden quedar pegados delante del slot tras quitar el
# disparador (ej. "abre" + "la calculadora" -> sobra "la"). Solo se
# quitan al PRINCIPIO del slot, nunca en medio (para no romper cosas
# como "el libro de la estanteria" si algún día fuera un slot así).
ARTICULOS_INICIALES = {"el", "la", "los", "las", "un", "una", "unos", "unas"}


def _quitar_articulo_inicial(texto: str) -> str:
    palabras = texto.split()
    while palabras and palabras[0] in ARTICULOS_INICIALES:
        palabras = palabras[1:]
    return " ".join(palabras)


def _quitar_acentos(texto: str) -> str:
    """Normaliza acentos para que 'ábreme' y 'abreme' coincidan igual."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def extraer_slot(texto: str, intencion: str) -> str:
    """
    Devuelve el texto restante tras quitar los disparadores conocidos
    de la intención. Si no hay disparadores definidos para esa
    intención, devuelve el texto tal cual (sin tocar).
    """
    texto_normalizado = _quitar_acentos(texto.strip().lower())
    disparadores = DISPARADORES.get(intencion, [])
    disparadores_ordenados = sorted(disparadores, key=len, reverse=True)

    for disparador in disparadores_ordenados:
        disparador_normalizado = _quitar_acentos(disparador)
        patron = re.escape(disparador_normalizado)
        texto_normalizado = re.sub(rf"\b{patron}\b", "", texto_normalizado)

    slot = re.sub(r"\s+", " ", texto_normalizado).strip()
    slot = _quitar_articulo_inicial(slot)
    return slot


if __name__ == "__main__":
    casos = [
        ("abre discord", "abrir_aplicacion"),
        ("ábreme discord", "abrir_aplicacion"),
        ("quiero abrir steam", "abrir_aplicacion"),
        ("puedes abrirme discord", "abrir_aplicacion"),
        ("abre notion", "abrir_aplicacion"),
        ("apunta que hay que sacar la basura", "crear_nota"),
        ("hazme una nota que diga revisar el coche", "crear_nota"),
        ("crea una nota con el titulo compras", "crear_nota"),
        ("toma nota que hay que pagar la luz", "crear_nota"),
        # Caso real que falló: el artículo quedaba pegado al slot
        ("abre la calculadora", "abrir_aplicacion"),
        ("abre el navegador", "abrir_aplicacion"),
        ("abre el explorador de archivos", "abrir_aplicacion"),
        # Caso límite: frase no cubierta por ningún disparador exacto
        ("podrias por favor abrir para mi discord", "abrir_aplicacion"),
    ]
    for texto, intencion in casos:
        slot = extraer_slot(texto, intencion)
        print(f"'{texto}' [{intencion}] -> slot='{slot}'")