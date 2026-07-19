"""
config.py

Configuración global del asistente. Los valores de monitores se
detectan automáticamente la primera vez que se importa este módulo
y se reutilizan en todo el sistema sin volver a consultar el hardware.
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Parámetros ajustables manualmente
# ---------------------------------------------------------------------------

# Confianza mínima para ejecutar una acción. Por debajo de este valor,
# el dispatcher no ejecuta nada aunque la intención predicha no sea
# "ninguna". Ajustado con datos reales del entrenamiento: las
# predicciones correctas rondan 0.85-1.00, así que 0.70 da margen
# de seguridad sin ser demasiado estricto.
UMBRAL_CONFIANZA = 0.70

# Cuando el grabador detecte automáticamente la parte variable (slot)
# de una plantilla grabada, pregunta al usuario para confirmarlo.
# Ponlo a False cuando confíes en que la detección funciona bien sola.
CONFIRMAR_SLOT_DETECTADO = True

# ---------------------------------------------------------------------------
# Detección automática de monitores (se ejecuta solo una vez al importar)
# ---------------------------------------------------------------------------

def _detectar_monitores() -> list[dict]:
    """
    Detecta los monitores disponibles al arrancar. Si screeninfo no está
    instalado, devuelve un monitor por defecto (1920x1080) para no romper
    el resto del sistema.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from window_manager import obtener_monitores
        monitores = obtener_monitores()
        if monitores and "error" not in monitores[0]:
            return monitores
    except Exception:
        pass

    # Fallback: un solo monitor 1920x1080 (edítalo manualmente si tu
    # resolución es distinta y no tienes screeninfo instalado)
    print(
        "[config] Aviso: no se pudo detectar la resolución automáticamente. "
        "Usando 1920x1080 por defecto. Instala 'screeninfo' para detección real: "
        "python -m pip install screeninfo"
    )
    return [{"indice": 0, "nombre": "DISPLAY1", "x": 0, "y": 0,
             "width": 1920, "height": 1080, "principal": True}]


# Se ejecuta una sola vez al importar config.py. Todos los módulos que
# necesiten información de monitores importan MONITORES desde aquí en
# vez de llamar a obtener_monitores() cada vez.
MONITORES = _detectar_monitores()

# Monitor principal (índice 0 en la lista de monitores detectados
# marcados como principal, o el primero si ninguno está marcado)
MONITOR_PRINCIPAL = next(
    (m for m in MONITORES if m.get("principal")),
    MONITORES[0]
)