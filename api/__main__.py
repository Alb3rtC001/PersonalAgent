"""
Arranca la API local:

    python -m api

Documentación interactiva (para probar a mano): http://127.0.0.1:8765/docs
"""

import logging
import os

import uvicorn

from api.servidor import crear_app
from api.token import VARIABLE_ENTORNO, obtener_token
from config import API_HOST, API_PUERTO, RUTA_TOKEN


def main() -> None:
    # Avisos de progreso de las skills en la consola del servidor.
    logging.basicConfig(format="  … %(message)s")
    logging.getLogger("personalagent").setLevel(logging.INFO)

    token = obtener_token()
    origen = f"variable de entorno {VARIABLE_ENTORNO}" if os.environ.get(VARIABLE_ENTORNO) else str(RUTA_TOKEN)
    host_visible = "127.0.0.1" if API_HOST in ("0.0.0.0", "") else API_HOST
    print(f"PersonalAgent API en http://{host_visible}:{API_PUERTO}  (docs: /docs)", flush=True)
    print(f"Token (cabecera X-Token) guardado en: {origen}", flush=True)
    uvicorn.run(crear_app(token=token), host=API_HOST, port=API_PUERTO, log_level="warning")


if __name__ == "__main__":
    main()
