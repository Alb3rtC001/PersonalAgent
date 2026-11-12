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
    "cerrar_aplicacion": [
        "hazme el favor de cerrar", "puedes cerrarme", "puedes cerrar",
        "quiero cerrar", "necesito cerrar", "me cierras", "cierrame",
        "cerrar", "cierra", "sal de", "salir de", "salte de", "quita",
        "termina el proceso de", "termina", "mata el proceso de", "mata", "por favor",
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
    "ejecutar_en_steam": [
    "quiero jugar a", "quiero jugar al", "quiero jugar",
    "abreme el juego", "abre el juego", "lanza el juego",
    "jugar a", "jugar al", "jugar",
    "ejecuta el juego", "pon el juego",
    "en steam", "desde steam",
    ],
}

# Artículos que pueden quedar pegados delante del slot tras quitar el
# disparador (ej. "abre" + "la calculadora" -> sobra "la"). Solo se
# quitan al PRINCIPIO del slot, nunca en medio (para no romper cosas
# como "el libro de la estanteria" si algún día fuera un slot así).
ARTICULOS_INICIALES = {"el", "la", "los", "las", "un", "una", "unos", "unas"}


def _quitar_articulo_inicial(texto: str) -> str:
    palabras = texto.split()
    while palabras and palabras[0].lower() in ARTICULOS_INICIALES:
        palabras = palabras[1:]
    return " ".join(palabras)


def _normalizar_caracter(c: str) -> str:
    """Minúscula y sin tilde, garantizando 1 carácter de salida por 1 de entrada."""
    n = _quitar_acentos(c.lower())
    return n if len(n) == 1 else c


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

    La búsqueda de disparadores se hace sobre una copia normalizada
    (minúsculas, sin tildes) con la misma longitud que el original, y lo
    que se recorta se recorta del texto ORIGINAL: así el slot conserva
    mayúsculas y tildes (importante para el contenido de una nota).
    """
    # Quitar caracteres invisibles (BOM, espacios de ancho cero) que a veces
    # llegan de la consola o de otros programas.
    original = re.sub(r"[﻿​-‍]", "", texto).strip()
    normalizado = "".join(_normalizar_caracter(c) for c in original)
    conservar = [True] * len(original)

    disparadores = sorted(DISPARADORES.get(intencion, []), key=len, reverse=True)
    for disparador in disparadores:
        patron = re.escape(_quitar_acentos(disparador))
        for m in re.finditer(rf"\b{patron}\b", normalizado):
            if all(conservar[m.start():m.end()]):
                for i in range(m.start(), m.end()):
                    conservar[i] = False

    restante = "".join(c if keep else " " for c, keep in zip(original, conservar))
    slot = re.sub(r"\s+", " ", restante).strip()
    return _quitar_articulo_inicial(slot)


if __name__ == "__main__":
    casos = [
        ("abre discord", "abrir_aplicacion"),
        ("ábreme discord", "abrir_aplicacion"),
        ("quiero abrir steam", "abrir_aplicacion"),
        ("puedes abrirme discord", "abrir_aplicacion"),
        ("Quiero jugar a Destiny 2", "abrir_aplicacion"),
        ("abreme el juego path of exile", "ejecutar_en_steam"),
        ("quiero jugar a golf it", "ejecutar_en_steam"),
        ("vamos a jugar a battlefield", "ejecutar_en_steam"),
        ("inicia el juego POE", "ejecutar_en_steam"),
        ("pon minecraft", "ejecutar_en_steam"),
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