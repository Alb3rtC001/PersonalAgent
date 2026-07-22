"""
rebuild_recordings.py

Genera un recordings.json limpio a partir de los datos actuales,
aplicando todas las correcciones de una vez:

1. abrir_aplicacion: eliminar el paso 3 (clic variable en el buscador)
   dejando solo win + escribir + enter
2. nueva_nota_via_enter: reconstruir desde las grabaciones de
   nueva_nota que tenían 5 pasos (win + escribir + enter + 2 clics)
3. nueva_nota_via_click: reconstruir desde las grabaciones de
   nueva_nota que tenían 4 pasos (win + escribir + 2 clics, sin enter)
4. ejecutar_en_steam: ya está bien, conservar tal cual
5. abrir_aplicacion_via_click: borrar (clics demasiado distintos,
   hay que regravar)

Ejecutar UNA SOLA VEZ desde la raíz del proyecto:
    python rebuild_recordings.py
"""

import json
import shutil
from pathlib import Path

RUTA = Path("recorder/recordings.json")
RUTA_BACKUP = Path("recorder/recordings.backup2.json")

# Grabaciones originales de nueva_nota recuperadas del backup
NUEVA_NOTA_GRABACIONES = [
    # Grabación #01 original: win + escribir + enter + click + click (5 pasos)
    [
        {"tipo": "tecla_especial", "valor": "win", "timestamp": 1784662437.4069417},
        {"tipo": "escribir", "valor": "notas rapidas", "timestamp": 1784662441.1210163},
        {"tipo": "tecla_especial", "valor": "enter", "timestamp": 1784662441.121023},
        {"tipo": "click", "valor": {"x_abs": 3260, "y_abs": 148, "x_rel": 29, "y_rel": 19, "boton": "Button.left", "monitor": 1, "ventana": {"titulo": "Notas rápidas", "proceso": "ApplicationFrameHost.exe", "pid": 9496, "monitor": 1, "maximizada": False, "minimizada": False, "rect": {"left": 3231, "top": 129, "right": 3470, "bottom": 818}, "width": 239, "height": 689, "timestamp": 1784662443.368255}}, "timestamp": 1784662443.3682666},
        {"tipo": "click", "valor": {"x_abs": 3523, "y_abs": 198, "x_rel": 59, "y_rel": 69, "boton": "Button.left", "monitor": 1, "ventana": {"titulo": "Notas rápidas", "proceso": "ApplicationFrameHost.exe", "pid": 9496, "monitor": 1, "maximizada": False, "minimizada": False, "rect": {"left": 3464, "top": 129, "right": 3703, "bottom": 818}, "width": 239, "height": 689, "timestamp": 1784662444.834122}}, "timestamp": 1784662444.8341362},
    ],
    # Grabación #03 original: win + escribir + enter + click + click (5 pasos)
    [
        {"tipo": "tecla_especial", "valor": "win", "timestamp": 1784662567.030222},
        {"tipo": "escribir", "valor": "notas rapid", "timestamp": 1784662569.833107},
        {"tipo": "tecla_especial", "valor": "enter", "timestamp": 1784662569.833114},
        {"tipo": "click", "valor": {"x_abs": 3264, "y_abs": 149, "x_rel": 33, "y_rel": 20, "boton": "Button.left", "monitor": 1, "ventana": {"titulo": "Notas rápidas", "proceso": "ApplicationFrameHost.exe", "pid": 9496, "monitor": 1, "maximizada": False, "minimizada": False, "rect": {"left": 3231, "top": 129, "right": 3470, "bottom": 818}, "width": 239, "height": 689, "timestamp": 1784662572.9932742}}, "timestamp": 1784662572.9932847},
        {"tipo": "click", "valor": {"x_abs": 3524, "y_abs": 217, "x_rel": 60, "y_rel": 88, "boton": "Button.left", "monitor": 1, "ventana": {"titulo": "Notas rápidas", "proceso": "ApplicationFrameHost.exe", "pid": 9496, "monitor": 1, "maximizada": False, "minimizada": False, "rect": {"left": 3464, "top": 129, "right": 3703, "bottom": 818}, "width": 239, "height": 689, "timestamp": 1784662574.2713645}}, "timestamp": 1784662574.2713773},
    ],
]

NUEVA_NOTA_VIA_CLICK_GRABACIONES = [
    # Grabación #02 original: win + escribir + click + click (4 pasos, sin enter)
    [
        {"tipo": "tecla_especial", "valor": "win", "timestamp": 1784662501.5741365},
        {"tipo": "escribir", "valor": "nota rapida", "timestamp": 1784662505.1812289},
        {"tipo": "click", "valor": {"x_abs": 687, "y_abs": 335, "x_rel": 156, "y_rel": 193, "boton": "Button.left", "monitor": 0, "ventana": {"titulo": "Buscar", "proceso": "SearchHost.exe", "pid": 15044, "monitor": 0, "maximizada": False, "minimizada": False, "rect": {"left": 531, "top": 142, "right": 1389, "bottom": 1032}, "width": 858, "height": 890, "timestamp": 1784662505.1818964}}, "timestamp": 1784662505.1819274},
        {"tipo": "click", "valor": {"x_abs": 3533, "y_abs": 174, "x_rel": 69, "y_rel": 45, "boton": "Button.left", "monitor": 1, "ventana": {"titulo": "Notas rápidas", "proceso": "ApplicationFrameHost.exe", "pid": 9496, "monitor": 1, "maximizada": False, "minimizada": False, "rect": {"left": 3464, "top": 129, "right": 3703, "bottom": 818}, "width": 239, "height": 689, "timestamp": 1784662508.3008773}}, "timestamp": 1784662508.3008974},
    ],
    # Grabación #04 original: win + escribir + click + click (4 pasos, sin enter)
    [
        {"tipo": "tecla_especial", "valor": "win", "timestamp": 1784662593.5761347},
        {"tipo": "escribir", "valor": "notas rapi", "timestamp": 1784662597.3721495},
        {"tipo": "click", "valor": {"x_abs": 698, "y_abs": 335, "x_rel": 167, "y_rel": 193, "boton": "Button.left", "monitor": 0, "ventana": {"titulo": "Buscar", "proceso": "SearchHost.exe", "pid": 15044, "monitor": 0, "maximizada": False, "minimizada": False, "rect": {"left": 531, "top": 142, "right": 1389, "bottom": 1032}, "width": 858, "height": 890, "timestamp": 1784662597.37265}}, "timestamp": 1784662597.3726687},
        {"tipo": "click", "valor": {"x_abs": 3261, "y_abs": 145, "x_rel": 30, "y_rel": 16, "boton": "Button.left", "monitor": 1, "ventana": {"titulo": "Notas rápidas", "proceso": "ApplicationFrameHost.exe", "pid": 9496, "monitor": 1, "maximizada": False, "minimizada": False, "rect": {"left": 3231, "top": 129, "right": 3470, "bottom": 818}, "width": 239, "height": 689, "timestamp": 1784662600.9413118}}, "timestamp": 1784662600.9413207},
    ],
]


def main():
    shutil.copy(RUTA, RUTA_BACKUP)
    print(f"Backup guardado en {RUTA_BACKUP}")

    with open(RUTA, "r", encoding="utf-8") as f:
        datos = json.load(f)

    nuevo = {}

    # 1. abrir_aplicacion: quitar paso 3 (clic variable en buscador)
    grabaciones_app = datos.get("abrir_aplicacion", [])
    if isinstance(grabaciones_app, list):
        limpias = [g[:2] for g in grabaciones_app]  # solo los 2 primeros pasos
        # Añadir enter como paso 3 fijo si no lo tienen ya
        for g in limpias:
            if not any(e.get("valor") == "enter" for e in g
                       if e.get("tipo") == "tecla_especial"):
                g.append({"tipo": "tecla_especial", "valor": "enter"})
        nuevo["abrir_aplicacion"] = limpias
        print(f"abrir_aplicacion: {len(limpias)} grabaciones → "
              f"{[len(g) for g in limpias]} pasos cada una")

    # 2. nueva_nota_via_enter: reconstruida desde el backup
    nuevo["nueva_nota_via_enter"] = NUEVA_NOTA_GRABACIONES
    print(f"nueva_nota_via_enter: {len(NUEVA_NOTA_GRABACIONES)} grabaciones "
          f"reconstruidas desde backup")

    # 3. nueva_nota_via_click: reconstruida desde el backup
    nuevo["nueva_nota_via_click"] = NUEVA_NOTA_VIA_CLICK_GRABACIONES
    print(f"nueva_nota_via_click: {len(NUEVA_NOTA_VIA_CLICK_GRABACIONES)} grabaciones "
          f"reconstruidas desde backup")

    # 4. ejecutar_en_steam: conservar tal cual
    nuevo["ejecutar_en_steam"] = datos.get("ejecutar_en_steam", [])
    print(f"ejecutar_en_steam: conservado tal cual "
          f"({len(nuevo['ejecutar_en_steam'])} grabaciones)")

    # 5. abrir_aplicacion_via_click: borrar (clics demasiado distintos)
    print("abrir_aplicacion_via_click: ELIMINADO "
          "(diferencia entre clics > 48px, necesita regrabarse)")

    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump(nuevo, f, ensure_ascii=False, indent=2)

    print(f"\nrecordings.json reconstruido. Claves: {list(nuevo.keys())}")
    print("\nAhora ejecuta:")
    print("  python .\\recorder\\build_templates.py")


if __name__ == "__main__":
    main()