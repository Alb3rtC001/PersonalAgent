"""
config.py

Configuración global del asistente. Los valores de monitores se
detectan automáticamente la primera vez que se importa este módulo
y se reutilizan en todo el sistema sin volver a consultar el hardware.
"""

import os
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

# Segundos que ejecutar_en_steam espera a ver el juego en marcha (algunos
# tardan, sobre todo si Steam estaba cerrado).
ESPERA_MAX_JUEGO = 90

# Segundos que cerrar_aplicacion espera a que la app se cierre tras pedírselo.
ESPERA_MAX_CIERRE = 10

# Si al pedir que se cierre una app solo se esconde en la bandeja del sistema
# (Discord, Steam...), terminar su proceso para cerrarla del todo.
# Nunca se termina si queda alguna ventana visible (p. ej. "¿Guardar cambios?").
CERRAR_TERMINA_BANDEJA = True
# Apps con su propia orden de salida: se usa antes que terminar el proceso. Cierra
# la app entera de forma limpia y SIN cerrar sesión (Steam: como "Steam > Salir";
# la cuenta sigue iniciada la próxima vez). Clave: nombre de la app en minúsculas.
CIERRE_LIMPIO = {"steam": "steam://exit"}
ESPERA_CIERRE_LIMPIO = 30   # segundos para que termine sola antes de forzarla

# ---------------------------------------------------------------------------
# Seguridad (core/seguridad.py)
# ---------------------------------------------------------------------------
# Cuándo se pide confirmación según el riesgo de cada skill:
#   lectura: solo consulta (ver tareas, actualizaciones de Steam)
#   bajo:    abrir, restaurar, escribir texto (sin Enter), crear notas
#   medio:   cerrar aplicaciones, lanzar juegos
#   alto:    pulsar teclas (un Enter puede enviar algo), plantillas grabadas (clics)
# Valores: "nunca", "si_llm" (si la orden la interpretó el LLM) o "siempre".
POLITICA_RIESGO = {"lectura": "nunca", "bajo": "nunca", "medio": "si_llm", "alto": "siempre"}
# Modo seguro: todo lo que no sea de lectura se confirma siempre. También se
# activa en marcha con "seguro on" / "seguro off".
MODO_SEGURO = False
# Ventanas sobre las que el agente NUNCA escribe ni hace clic (teclado y
# plantillas grabadas). Se compara, sin mayúsculas ni tildes, con el título
# (si lo contiene) y con el nombre del proceso (si es igual).
VENTANAS_PROHIBIDAS = [
    # gestores de contraseñas
    "keepass.exe", "keepassxc.exe", "bitwarden.exe", "1password.exe", "contraseña", "password",
    # banca y pagos
    "banco", "banca online", "paypal", "bizum",
    # terminales y herramientas del sistema
    "powershell.exe", "pwsh.exe", "cmd.exe", "windowsterminal.exe", "regedit.exe", "taskmgr.exe",
    "mmc.exe", "editor del registro",
]
# Botones que hacer_clic NUNCA pulsa (compras, pagos, borrar, cerrar sesión...):
# si el nombre del botón contiene uno de estos textos (sin mayúsculas ni tildes),
# se niega y te pide que lo hagas tú.
CONTROLES_PROHIBIDOS = [
    "comprar", "compra", "pagar", "pago", "carrito", "suscrib", "donar", "regalar", "transferir",
    "eliminar", "borrar", "desinstalar", "cerrar sesion", "desconectar cuenta",
    "buy", "purchase", "checkout", "pay", "delete", "remove", "uninstall", "sign out", "log out",
]
# Combinación global (en cualquier ventana) que para el agente como el botón de
# pánico. Formato de pynput. Ctrl+Alt+P ("parar"): no la usa Windows (Ctrl+Alt+Esc
# no sirve: Windows usa Alt+Esc para mandar la ventana al fondo).
ATAJO_PANICO = "<ctrl>+<alt>+p"

# Segundos que el agente recuerda "la última aplicación usada" (para "escribe
# 2+2" o "pulsa enter" sin decir dónde, después de "abre la calculadora").
CADUCIDAD_CONTEXTO = 15 * 60

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
# están los archivos de models/) el agente funciona solo con el clasificador
# y no usa la GPU. Otras formas de desactivarlo sin tocar este archivo:
#   - al arrancar:     python dispatcher.py --sin-llm      (o python -m api --sin-llm)
#   - variable:        $env:PERSONALAGENT_LLM = "off"      ("cpu" = sin GPU)
#   - en marcha:       escribe "llm off" / "llm on" en la consola (o POST /llm en la API)
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
LLM_CAPAS_GPU = 79           # 99 = todo el modelo en la GPU; 0 = solo CPU (mucho más lento)
LLM_CONTEXTO = 6144
LLM_ESPERA_ARRANQUE = 120    # segundos máximos para cargar el modelo
# Opciones de memoria de llama-server (medido con Qwen3-8B en la RTX 3060 Ti):
# una conversación a la vez (-np 1), flash attention y caché KV en 8 bits.
# Ocupa ~4,8 GB en vez de ~5,3 GB, con la misma velocidad y respuestas.
LLM_ARGUMENTOS_EXTRA = ["-np", "1", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"]
# LÍMITE DE VRAM del LLM, en MiB. Si el modelo entero no cabe, se ponen en la
# GPU solo las capas que quepan y el resto va al procesador: ocupa menos pero
# tarda más. Medido con Qwen3-8B en la RTX 3060 Ti (~116 MiB por capa):
#   5200 -> modelo entero (~5,0 GB)  ~0,5 s por orden
#   4200 -> 30 de 36 capas           ~1,7 s
#   3500 -> 24 capas                 ~2,6 s
#   2100 -> 12 capas                 ~5 s
#   0    -> solo procesador          ~7 s  (igual que LLM_CAPAS_GPU = 0)
LLM_VRAM_MAX_MIB = 5200
# Además de lo que vaya a ocupar el LLM, deja al menos estos MiB libres en la
# GPU: si no hay sitio (p. ej. mientras juegas), no se carga.
LLM_MARGEN_VRAM_MIB = 500
# No usar el LLM (y descargarlo) si la GPU pasa de esta temperatura en °C.
LLM_TEMPERATURA_MAX = 83
# Si no se usa en este tiempo, el modelo se descarga y libera la VRAM; se
# vuelve a cargar solo (unos 4 s) la próxima vez que haga falta. 0 = nunca.
LLM_DESCARGAR_TRAS = 15 * 60

# Variable de entorno PERSONALAGENT_LLM: "off" desactiva el LLM, "cpu" lo usa
# sin GPU (mucho más lento), "on"/"gpu" lo activa.
_modo_llm = os.environ.get("PERSONALAGENT_LLM", "").strip().lower()
if _modo_llm in ("0", "off", "no", "false", "desactivado"):
    LLM_ACTIVO = False
elif _modo_llm == "cpu":
    LLM_ACTIVO, LLM_CAPAS_GPU = True, 0
elif _modo_llm in ("1", "on", "si", "sí", "true", "gpu"):
    LLM_ACTIVO = True

# Datos generados por el agente (no se suben a git).
RUTA_DATOS = Path(__file__).parent / "data"
RUTA_NOTAS = RUTA_DATOS / "notas"                  # notas creadas por crear_nota
RUTA_EPISODIOS = RUTA_DATOS / "episodios.jsonl"    # historial de órdenes ejecutadas
# Traza detallada (paso a paso, con errores y líneas de código) de la ÚLTIMA
# orden; cada orden nueva la sobrescribe. Para saber qué pasó si algo falla.
RUTA_TRAZA = RUTA_DATOS / "ultima_orden.log"
# Registro de actividad legible y permanente: una línea por acción, quién la
# pidió (consola, interfaz, api, agenda) y cómo acabó. Comando "actividad".
RUTA_ACTIVIDAD = RUTA_DATOS / "actividad.log"
# Memoria: cuántas de tus órdenes pasadas parecidas (que salieron bien) se le
# enseñan al LLM como ejemplos en cada consulta. Así aprende de tu uso sin
# reentrenar. 0 = desactivado.
MEMORIA_EJEMPLOS = 3
# Tokens que se dejan libres en LLM_CONTEXTO para la respuesta. Si la consulta (con
# todos los ejemplos de core/llm_ejemplos.json) no cabe, se pasan solo los que vienen
# al caso: los de "ninguna", el primero de cada skill y los más parecidos a la orden.
# Así el prompt nunca se sale del contexto aunque añadas muchos ejemplos.
LLM_RESERVA_RESPUESTA = 900

# Base de datos local (SQLite, viene con Python): de momento, las tareas programadas.
RUTA_BD = RUTA_DATOS / "agente.db"
# Si el agente estaba apagado cuando tocaba una tarea programada y ha pasado
# más de esto (segundos), ya no se ejecuta: se marca como perdida.
TOLERANCIA_RETRASO_TAREAS = 10 * 60

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