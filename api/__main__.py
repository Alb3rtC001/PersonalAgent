"""
Arranca la API local:

    python -m api

Documentación interactiva (para probar a mano): http://127.0.0.1:8765/docs
"""

import argparse
import logging
import os

import uvicorn

from api.servidor import crear_app
from api.token import VARIABLE_ENTORNO, obtener_token
from config import API_HOST, API_PUERTO, LLM_ACTIVO, RUTA_TOKEN
from core.agente import Agente


def main() -> None:
    parser = argparse.ArgumentParser(description="API local de PersonalAgent")
    parser.add_argument("--sin-llm", action="store_true",
                        help="no usar el LLM (solo el clasificador; no ocupa la GPU)")
    parser.add_argument("--llm-cpu", action="store_true", help="usar el LLM sin GPU (mucho más lento)")
    args = parser.parse_args()

    # Avisos de progreso de las skills en la consola del servidor.
    logging.basicConfig(format="  … %(message)s")
    logging.getLogger("personalagent").setLevel(logging.INFO)

    token = obtener_token()
    origen = f"variable de entorno {VARIABLE_ENTORNO}" if os.environ.get(VARIABLE_ENTORNO) else str(RUTA_TOKEN)
    host_visible = "127.0.0.1" if API_HOST in ("0.0.0.0", "") else API_HOST
    print(f"PersonalAgent API en http://{host_visible}:{API_PUERTO}  (docs: /docs)", flush=True)
    print(f"Token (cabecera X-Token) guardado en: {origen}", flush=True)
    agente = Agente(usar_llm=LLM_ACTIVO and not args.sin_llm or args.llm_cpu, llm_cpu=args.llm_cpu)
    agente.precargar()
    estado = agente.estado_llm()
    print("LLM: " + (f"activo ({estado['modelo']})" if estado["activo"] else "desactivado (solo clasificador)")
          + ". Se puede cambiar en marcha con POST /llm.", flush=True)
    uvicorn.run(crear_app(agente=agente, token=token), host=API_HOST, port=API_PUERTO, log_level="warning")


if __name__ == "__main__":
    main()
