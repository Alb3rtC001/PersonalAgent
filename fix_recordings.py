"""
fix_recordings.py

Limpia recordings.json eliminando grabaciones problemáticas y
reorganizando las que tienen estrategias distintas en plantillas
separadas.

Ejecutar UNA SOLA VEZ desde la raíz del proyecto:
    python fix_recordings.py

Hace una copia de seguridad en recordings.backup.json antes de tocar nada.
"""

import json
import shutil
import sys
from pathlib import Path

RUTA = Path("recorder/recordings.json")
RUTA_BACKUP = Path("recorder/recordings.backup.json")


def main():
    if not RUTA.exists():
        print("No se encontró recordings.json")
        sys.exit(1)

    # Copia de seguridad
    shutil.copy(RUTA, RUTA_BACKUP)
    print(f"Copia de seguridad guardada en {RUTA_BACKUP}")

    with open(RUTA, "r", encoding="utf-8") as f:
        datos = json.load(f)

    nuevo = {}

    # ------------------------------------------------------------------
    # abrir_aplicacion: conservar solo #01, #03, #04 (3 pasos cada una)
    # Borrar #02 y #05 (1 paso, clics accidentales)
    # ------------------------------------------------------------------
    grabaciones_app = datos.get("abrir_aplicacion", [])
    if isinstance(grabaciones_app, list):
        validas = [g for g in grabaciones_app if len(g) == 3]
        print(f"abrir_aplicacion: {len(grabaciones_app)} grabaciones "
              f"→ conservando {len(validas)} con 3 pasos")
        nuevo["abrir_aplicacion"] = validas

    # ------------------------------------------------------------------
    # nueva_nota: separar en dos estrategias según número de pasos
    # 5 pasos → nueva_nota_via_enter (#01, #03)
    # 4 pasos → nueva_nota_via_click (#02, #04)
    # ------------------------------------------------------------------
    grabaciones_nota = datos.get("nueva_nota", [])
    if isinstance(grabaciones_nota, list):
        via_enter = [g for g in grabaciones_nota if len(g) == 5]
        via_click = [g for g in grabaciones_nota if len(g) == 4]
        print(f"nueva_nota: separando en:")
        print(f"  nueva_nota_via_enter: {len(via_enter)} grabaciones (5 pasos)")
        print(f"  nueva_nota_via_click: {len(via_click)} grabaciones (4 pasos)")
        nuevo["nueva_nota_via_enter"] = via_enter
        nuevo["nueva_nota_via_click"] = via_click

    # ------------------------------------------------------------------
    # ejecutar_en_steam: borrar el primer paso (clic accidental en VS Code)
    # de ambas grabaciones. El primer paso válido es el clic en
    # explorer.exe (barra de tareas para ir a Steam).
    # ------------------------------------------------------------------
    grabaciones_steam = datos.get("ejecutar_en_steam", [])
    if isinstance(grabaciones_steam, list):
        limpias = []
        for i, g in enumerate(grabaciones_steam):
            # El primer evento tiene ventana "VS Code" — lo eliminamos
            primer_titulo = g[0].get("valor", {}).get("ventana", {}).get("titulo", "")
            if "Visual Studio Code" in primer_titulo or "recordings.json" in primer_titulo:
                g_limpia = g[1:]  # quitar el primer clic accidental
                print(f"ejecutar_en_steam #{i+1:02d}: eliminado clic accidental "
                      f"en VS Code → {len(g_limpia)} pasos")
                limpias.append(g_limpia)
            else:
                limpias.append(g)
        nuevo["ejecutar_en_steam"] = limpias

    # ------------------------------------------------------------------
    # abrir_aplicacion_via_click: subir tolerancia a 120px
    # La diferencia entre clics es 48px, con 80px el bloque no coincide.
    # Con 120px: 1194//120=9 y 1242//120=10 — sigue sin coincidir.
    # Con 200px: 1194//200=5 y 1242//200=6 — sigue sin coincidir.
    # El problema es que la diferencia (48px) es demasiado grande para
    # un clic en la barra de tareas. Necesitas regravar con más precisión
    # o aumentar mucho la tolerancia. Lo dejamos con tolerancia=200 y
    # un aviso.
    # ------------------------------------------------------------------
    via_click = datos.get("abrir_aplicacion_via_click", {})
    if isinstance(via_click, dict):
        nuevo["abrir_aplicacion_via_click"] = {
            "tolerancia_px": 200,
            "grabaciones": via_click.get("grabaciones", []),
        }
        print("abrir_aplicacion_via_click: tolerancia subida a 200px")
        print("  AVISO: diferencia entre clics es 48px. Si sigue fallando,")
        print("  graba de nuevo intentando clicar en el mismo punto exacto.")

    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump(nuevo, f, ensure_ascii=False, indent=2)

    print(f"\nrecordings.json actualizado. Claves: {list(nuevo.keys())}")
    print("\nAhora ejecuta:")
    print("  python .\\recorder\\build_templates.py")


if __name__ == "__main__":
    main()