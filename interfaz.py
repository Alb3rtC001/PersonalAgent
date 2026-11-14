"""
Interfaz de escritorio del agente (tkinter, viene con Python). Hace lo mismo
que dispatcher.py, en una ventana con tres zonas:

    1. Respuestas: los avisos (… Abriendo 'Google Chrome'…) y los resultados
       (✔ / ✘), como en la terminal.
    2. Entrada: donde escribes la orden (Enter para enviar).
    3. Control: minutos y segundos para programar la orden (0 y 0 = ahora) y
       el botón de pánico, que para lo que esté haciendo el agente y lo deja
       en pausa hasta que pulses "Reanudar".

Las órdenes se ejecutan en segundo plano para que la ventana (y el botón de
pánico) respondan siempre. Las confirmaciones y los datos que falten se piden
en ventanas emergentes.

Uso:
    python interfaz.py              # clasificador + LLM si duda
    python interfaz.py --sin-llm    # solo clasificador (no usa la GPU)
    python interfaz.py --llm-cpu    # LLM sin GPU (lento)

También acepta 'llm', 'llm on', 'llm off' y 'salir'.
"""

from __future__ import annotations

import argparse
import logging
import queue
import threading
import tkinter as tk
from datetime import timedelta
from tkinter import messagebox, scrolledtext, simpledialog

from config import LLM_ACTIVO
from core import control
from core.agente import Agente, limpiar_texto
from core.traza import configurar_logs
from dispatcher import describir_llm

MAX_MINUTOS, MAX_SEGUNDOS = 99, 60
FUENTE = ("Consolas", 10)
COLORES = {"ok": "#1a7f37", "error": "#c62828", "aviso": "#6b6b6b", "orden": "#1f4e9c", "sistema": "#8a5a00"}


class ManejadorVentana(logging.Handler):
    """Pasa los avisos del agente (nivel INFO) a la ventana, desde cualquier hilo."""

    def __init__(self, cola: queue.Queue):
        super().__init__(logging.INFO)
        self.cola = cola

    def emit(self, record: logging.LogRecord) -> None:
        mensaje = record.getMessage()
        if mensaje.startswith("⏰"):   # resultado de una tarea programada
            self.cola.put(("ok" if "✔" in mensaje else "error", mensaje))
        else:
            self.cola.put(("aviso", f"  … {mensaje}"))


class Interfaz:
    def __init__(self, raiz: tk.Tk, agente: Agente):
        self.raiz = raiz
        self.agente = agente
        self.cola: queue.Queue = queue.Queue()
        self.ocupado = False

        raiz.title("PersonalAgent")
        raiz.geometry("820x560")
        raiz.minsize(560, 380)
        raiz.columnconfigure(0, weight=1)
        raiz.rowconfigure(0, weight=1)

        # 1. Respuestas
        self.salida = scrolledtext.ScrolledText(raiz, font=FUENTE, wrap="word", state="disabled",
                                                padx=8, pady=6, background="#fbfbfb")
        self.salida.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        for etiqueta, color in COLORES.items():
            self.salida.tag_configure(etiqueta, foreground=color)
        self.salida.tag_configure("orden", foreground=COLORES["orden"], font=(*FUENTE, "bold"))

        # 2. Entrada
        marco_entrada = tk.Frame(raiz)
        marco_entrada.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        marco_entrada.columnconfigure(1, weight=1)
        tk.Label(marco_entrada, text=">", font=(*FUENTE, "bold")).grid(row=0, column=0, padx=(0, 4))
        self.entrada = tk.Entry(marco_entrada, font=("Consolas", 11))
        self.entrada.grid(row=0, column=1, sticky="ew", ipady=4)
        self.entrada.bind("<Return>", lambda _: self.enviar())
        self.boton_enviar = tk.Button(marco_entrada, text="Enviar", width=10, command=self.enviar)
        self.boton_enviar.grid(row=0, column=2, padx=(6, 0))

        # 3. Control: programar + botón de pánico
        marco_control = tk.Frame(raiz)
        marco_control.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 8))
        marco_control.columnconfigure(5, weight=1)
        tk.Label(marco_control, text="Programar dentro de").grid(row=0, column=0, padx=(0, 6))
        validar = (raiz.register(self._validar_numero), "%P", "%W")
        self.minutos = tk.Spinbox(marco_control, from_=0, to=MAX_MINUTOS, width=4, justify="center",
                                  validate="key", validatecommand=validar, name="minutos")
        self.minutos.grid(row=0, column=1)
        tk.Label(marco_control, text="min").grid(row=0, column=2, padx=(2, 8))
        self.segundos = tk.Spinbox(marco_control, from_=0, to=MAX_SEGUNDOS, width=4, justify="center",
                                   validate="key", validatecommand=validar, name="segundos")
        self.segundos.grid(row=0, column=3)
        tk.Label(marco_control, text="s   (0 y 0 = ahora)").grid(row=0, column=4, padx=(2, 8))
        self.boton_panico = tk.Button(marco_control, text="■  PARAR", width=16, font=("Segoe UI", 10, "bold"),
                                      fg="white", bg="#c62828", activebackground="#8e0000",
                                      activeforeground="white", command=self.panico)
        self.boton_panico.grid(row=0, column=6, sticky="e")

        logging.getLogger("personalagent").addHandler(ManejadorVentana(self.cola))
        raiz.after(100, self._vaciar_cola)
        self.entrada.focus_set()

    # --- Salida -------------------------------------------------------------------

    def escribir(self, texto: str, estilo: str = "") -> None:
        self.cola.put((estilo, texto))

    def _vaciar_cola(self) -> None:
        try:
            while True:
                estilo, texto = self.cola.get_nowait()
                self.salida.configure(state="normal")
                self.salida.insert("end", texto + "\n", estilo or ())
                self.salida.configure(state="disabled")
                self.salida.see("end")
        except queue.Empty:
            pass
        self.raiz.after(100, self._vaciar_cola)

    # --- Programar -----------------------------------------------------------------

    def _validar_numero(self, valor: str, widget: str) -> bool:
        if valor == "":
            return True
        maximo = MAX_MINUTOS if widget.endswith("minutos") else MAX_SEGUNDOS
        return valor.isdigit() and int(valor) <= maximo

    def _tiempo(self) -> timedelta | None:
        minutos = int(self.minutos.get() or 0)
        segundos = int(self.segundos.get() or 0)
        total = timedelta(minutes=min(minutos, MAX_MINUTOS), seconds=min(segundos, MAX_SEGUNDOS))
        return total if total.total_seconds() > 0 else None

    def _reiniciar_tiempo(self) -> None:
        for caja in (self.minutos, self.segundos):
            caja.delete(0, "end")
            caja.insert(0, "0")

    # --- Diálogos desde el hilo de la orden -------------------------------------------

    def _en_ventana(self, funcion):
        """Ejecuta `funcion` en el hilo de la ventana y espera su resultado."""
        listo, caja = threading.Event(), {}

        def llamar():
            try:
                caja["valor"] = funcion()
            finally:
                listo.set()
        self.raiz.after(0, llamar)
        listo.wait()
        return caja.get("valor")

    def confirmar(self, accion: str) -> bool:
        respuesta = self._en_ventana(lambda: messagebox.askyesno(
            "Confirmar acción", f"El agente va a hacer:\n\n{accion}\n\n¿Continuar?", parent=self.raiz))
        self.escribir(f"  {'✔ confirmado' if respuesta else '✘ no confirmado'}: {accion}", "sistema")
        return bool(respuesta)

    def pedir(self, pregunta: str) -> str:
        return self._en_ventana(lambda: simpledialog.askstring("Falta un dato", pregunta, parent=self.raiz)) or ""

    # --- Órdenes --------------------------------------------------------------------

    def enviar(self) -> None:
        texto = limpiar_texto(self.entrada.get())
        if not texto or self.ocupado:
            return
        self.entrada.delete(0, "end")
        if texto.lower() == "salir":
            self.raiz.destroy()
            return
        if texto.lower() in ("llm", "llm on", "llm off"):
            if texto.lower() != "llm":
                self.agente.activar_llm(texto.lower() == "llm on")
            self.escribir("  " + describir_llm(self.agente.estado_llm()), "sistema")
            return

        programar_en = self._tiempo()
        self._reiniciar_tiempo()
        sufijo = f"   (programada: dentro de {int(programar_en.total_seconds()) // 60} min " \
                 f"{int(programar_en.total_seconds()) % 60} s)" if programar_en else ""
        self.escribir(f"> {texto}{sufijo}", "orden")
        self._ocupar(True)
        threading.Thread(target=self._procesar, args=(texto, programar_en), daemon=True, name="orden").start()

    def _procesar(self, texto: str, programar_en: timedelta | None) -> None:
        try:
            resultado = self.agente.procesar(texto, pedir=self.pedir, confirmar=self.confirmar,
                                             programar_en=programar_en)
            planes = resultado.datos.get("planes") or []
            if planes and len(planes[-1]) > 1:
                self.escribir("  Plan: " + " → ".join(planes[-1]), "aviso")
            self.escribir(("✔ " if resultado.ok else "✘ ") + resultado.mensaje,
                          "ok" if resultado.ok else "error")
        except Exception as e:   # que un fallo no deje la ventana bloqueada
            logging.getLogger("personalagent").exception("Error procesando la orden:")
            self.escribir(f"✘ Error inesperado: {e} (detalle en data/ultima_orden.log)", "error")
        finally:
            self.raiz.after(0, self._ocupar, False)

    def _ocupar(self, ocupado: bool) -> None:
        self.ocupado = ocupado
        self.boton_enviar.configure(state="disabled" if ocupado else "normal",
                                    text="Trabajando…" if ocupado else "Enviar")

    # --- Botón de pánico -----------------------------------------------------------

    def panico(self) -> None:
        if control.en_pausa():
            control.reanudar()
            self.boton_panico.configure(text="■  PARAR", bg="#c62828", activebackground="#8e0000")
            self.escribir("▶ Agente reanudado.", "sistema")
        else:
            control.detener()
            self.boton_panico.configure(text="▶  REANUDAR", bg="#1a7f37", activebackground="#0f5223")
            self.escribir("■ PARADO: lo que estuviera haciendo se corta y no hará nada más (tampoco las "
                          "tareas programadas) hasta que pulses Reanudar.", "error")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interfaz del agente")
    parser.add_argument("--sin-llm", action="store_true", help="no usar el LLM (no ocupa la GPU)")
    parser.add_argument("--llm-cpu", action="store_true", help="usar el LLM sin GPU (lento)")
    args = parser.parse_args()

    configurar_logs(consola=False)   # los avisos van a la ventana; la traza, a data/ultima_orden.log
    raiz = tk.Tk()
    agente = Agente(usar_llm=LLM_ACTIVO and not args.sin_llm or args.llm_cpu, llm_cpu=args.llm_cpu)
    interfaz = Interfaz(raiz, agente)
    interfaz.escribir(describir_llm(agente.estado_llm()), "sistema")
    interfaz.escribir("Escribe una orden y pulsa Enter. 'llm off' / 'llm on' para el LLM; 'salir' para cerrar.",
                      "sistema")
    agente.precargar()
    agente.iniciar_agenda()
    raiz.mainloop()


if __name__ == "__main__":
    main()
