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
UMBRAL_CONFIANZA = 0.72

# Segundos que abrir_aplicacion espera a que aparezca la ventana de la app.
ESPERA_MAX_APERTURA = 30

# Segundos que cerrar_aplicacion espera a que la app se cierre tras pedírselo.
ESPERA_MAX_CIERRE = 10

# Si al pedir que se cierre una app solo se esconde en la bandeja del sistema
# (Discord, Steam...), terminar su proceso para cerrarla del todo.
# Nunca se termina si queda alguna ventana visible (p. ej. "¿Guardar cambios?").
CERRAR_TERMINA_BANDEJA = True

# Nombres alternativos para abrir_aplicacion y cerrar_aplicacion: lo que dices -> nombre en el menú Inicio.
# Las claves van en minúsculas y sin tildes.
ALIAS_APLICACIONES = {
    "navegador": "Google Chrome",
    "chrome": "Google Chrome",
    "explorador": "Explorador de archivos",
    "notas": "Notas rápidas",
}

# ---------------------------------------------------------------------------
# LLM local (fase 3, ver ARQUITECTURA.md §10 y models/README.md)
# ---------------------------------------------------------------------------
# Si el clasificador no está seguro, se pregunta al LLM. Con False (o si no
# están los archivos de models/) el agente funciona solo con el clasificador.
LLM_ACTIVO = True
RUTA_MODELOS = Path(__file__).parent / "models"
RUTA_LLAMA_SERVER = RUTA_MODELOS / "llama.cpp" / "llama-server.exe"
# Elegido por evaluación (ARQUITECTURA.md §10): Qwen3-8B acierta más y responde el doble de rápido.
# Alternativa más auditable (datos de entrenamiento abiertos):
#   RUTA_MODELOS / "olmo-3-7b-instruct" / "Olmo-3-7B-Instruct-Q4_K_M.gguf"
RUTA_MODELO_LLM = RUTA_MODELOS / "qwen3-8b" / "Qwen3-8B-Q4_K_M.gguf"
# Formato de chat de los dos modelos. (La plantilla que trae el GGUF de OLMo 3
# no funciona con llama-server; ChatML es el mismo formato.)
LLM_PLANTILLA_CHAT = "chatml"
LLM_PUERTO = 8766            # solo en 127.0.0.1
LLM_CAPAS_GPU = 99           # 99 = todo el modelo en la GPU; 0 = solo CPU (mucho más lento)
LLM_CONTEXTO = 4096
LLM_ESPERA_ARRANQUE = 120    # segundos máximos para cargar el modelo

# Datos generados por el agente (no se suben a git).
RUTA_DATOS = Path(__file__).parent / "data"
RUTA_NOTAS = RUTA_DATOS / "notas"                  # notas creadas por crear_nota
RUTA_EPISODIOS = RUTA_DATOS / "episodios.jsonl"    # historial de órdenes ejecutadas

# API HTTP local (python -m api)
# 127.0.0.1 = solo este PC. Para conectar el móvil por la red de casa: "0.0.0.0".
API_HOST = "127.0.0.1"
API_PUERTO = 8765
# Token que deben enviar los clientes en la cabecera X-Token. Se genera
# solo la primera vez; también se puede fijar con la variable de entorno
# PERSONALAGENT_TOKEN.
RUTA_TOKEN = RUTA_DATOS / "api_token.txt"
# Segundos que una orden puede esperar una respuesta del usuario
# (un dato que falta o una confirmación) antes de descartarse.
CADUCIDAD_PENDIENTES = 300

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
        from core.estado import obtener_monitores
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