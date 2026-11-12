"""
Cliente de consola que habla con la API (python -m api debe estar arrancada).

Hace lo mismo que dispatcher.py pero a través de HTTP: es el mismo
camino que seguirá el móvil. Solo usa la biblioteca estándar.

Uso:
    python cliente.py
    python cliente.py --url http://192.168.1.50:8765 --token XXXXX
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from api.token import obtener_token
from config import API_HOST, API_PUERTO


class ClienteAPI:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token

    def llamar(self, metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        peticion = urllib.request.Request(
            self.url + ruta, data=datos, method=metodo,
            headers={"X-Token": self.token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(peticion, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detalle = json.loads(e.read().decode("utf-8")).get("detail", e.reason)
            raise RuntimeError(f"HTTP {e.code}: {detalle}") from None


def mostrar(respuesta: dict) -> None:
    planes = respuesta.get("planes") or []
    if planes and len(planes[-1]) > 1:
        print("  Plan: " + " → ".join(planes[-1]))
    marca = {"completada": "✔", "fallida": "✘", "rechazada": "✘"}.get(respuesta["estado"], "…")
    print(f"{marca} {respuesta['mensaje']}")


def conversar(cliente: ClienteAPI, texto: str) -> None:
    respuesta = cliente.llamar("POST", "/ordenes", {"texto": texto})
    while respuesta["estado"] in ("necesita_dato", "necesita_confirmacion"):
        mostrar(respuesta)
        if respuesta["estado"] == "necesita_dato":
            cuerpo = {"dato": input("  > ")}
        else:
            si = input("  ¿Continuar? (s/n) > ").strip().lower() in ("s", "si", "sí", "y", "yes")
            cuerpo = {"confirmar": si}
        respuesta = cliente.llamar("POST", f"/ordenes/{respuesta['id']}", cuerpo)
    mostrar(respuesta)


def main() -> None:
    host = "127.0.0.1" if API_HOST in ("0.0.0.0", "") else API_HOST
    parser = argparse.ArgumentParser(description="Cliente de consola de la API de PersonalAgent")
    parser.add_argument("--url", default=f"http://{host}:{API_PUERTO}")
    parser.add_argument("--token", default=None, help="por defecto, el de data/api_token.txt")
    args = parser.parse_args()

    token = args.token or obtener_token(crear=False)
    if not token:
        sys.exit("No hay token. Arranca antes el servidor (python -m api) o pásalo con --token.")
    cliente = ClienteAPI(args.url, token)

    try:
        salud = cliente.llamar("GET", "/salud")
    except (urllib.error.URLError, OSError):
        sys.exit(f"No hay servidor en {args.url}. Arráncalo con: python -m api")
    print(f"Conectado a {args.url} ({salud['skills']} skills). Escribe una orden o 'salir'.")

    while True:
        try:
            texto = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if texto.lower() == "salir":
            break
        if texto:
            print("  … enviando (puede tardar si hay que esperar a que se abra una app)")
            try:
                conversar(cliente, texto)
            except RuntimeError as e:
                print(f"✘ {e}")
            except KeyboardInterrupt:
                print("✘ Dejo de esperar la respuesta (el servidor puede terminar la orden igualmente).")


if __name__ == "__main__":
    main()
