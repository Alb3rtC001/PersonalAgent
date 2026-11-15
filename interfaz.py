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
from tkinter import messagebox, simpledialog

from config import LLM_ACTIVO
from core import control
from core.agente import Agente, limpiar_texto
from core.comandos import AYUDA, atajo_legible, describir_llm, ejecutar_comando, iniciar_atajo_panico, pausar_por_panico  # noqa: E501
from core.seguridad import escuchar, registrar_actividad
from core.traza import configurar_logs

MAX_MINUTOS, MAX_SEGUNDOS = 99, 60

# Estilo "libreta": tarjeta crema con borde y sombra marrón, letra de máquina de
# escribir y acentos naranjas.
FONDO = "#FFFFFF"        # alrededor de la tarjeta
PAPEL = "#F6EBDA"        # la tarjeta
PAPEL_OSCURO = "#EEDFC8" # cuadro de escritura
MARRON = "#5B3A26"       # borde, sombra y texto
NARANJA = "#F0A01E"      # acentos
LETRA = "Courier New"
FUENTE = (LETRA, 11)
COLORES = {"ok": "#3F7D3A", "error": "#B3261E", "aviso": "#9C8571", "orden": "#C77D0A", "sistema": MARRON}
RADIO, BORDE, SOMBRA, MARGEN = 26, 3, 12, 22


def rectangulo_redondeado(lienzo: tk.Canvas, x1, y1, x2, y2, r, **opciones) -> int:
    puntos = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return lienzo.create_polygon(puntos, smooth=True, **opciones)


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

        raiz.title("Personal Agent")
        raiz.geometry("760x620")
        raiz.minsize(560, 460)
        raiz.configure(background=FONDO)

        # La tarjeta (con esquinas redondeadas y sombra) se dibuja en un lienzo;
        # el contenido va en un marco colocado encima.
        self.lienzo = tk.Canvas(raiz, background=FONDO, highlightthickness=0)
        self.lienzo.pack(fill="both", expand=True)
        tarjeta = tk.Frame(self.lienzo, background=PAPEL)
        self._ventana_tarjeta = self.lienzo.create_window(0, 0, anchor="nw", window=tarjeta)
        self.lienzo.bind("<Configure>", self._dibujar_tarjeta)
        tarjeta.columnconfigure(0, weight=1)
        tarjeta.rowconfigure(2, weight=1)

        # Barra superior: "‹ Agente" a la izquierda, estado a la derecha (como el ejemplo)
        barra = tk.Frame(tarjeta, background=PAPEL)
        barra.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        barra.columnconfigure(1, weight=1)
        tk.Label(barra, text="‹ Agente", font=(LETRA, 12, "bold"), fg=NARANJA, bg=PAPEL).grid(row=0, column=0)
        self.estado = tk.Label(barra, text="● listo", font=(LETRA, 10, "bold"), fg=NARANJA, bg=PAPEL)
        self.estado.grid(row=0, column=2)
        tk.Label(tarjeta, text="personal agent", font=(LETRA, 18, "bold"), fg=MARRON, bg=PAPEL,
                 anchor="w").grid(row=1, column=0, sticky="ew", pady=(10, 4))

        # 1. Respuestas
        # Sin barra de desplazamiento (en Windows no se puede colorear y rompe el
        # estilo): se desplaza con la rueda del ratón y siempre baja a lo último.
        self.salida = tk.Text(
            tarjeta, font=FUENTE, wrap="word", state="disabled", padx=2, pady=4, background=PAPEL,
            foreground=MARRON, relief="flat", borderwidth=0, highlightthickness=0, spacing1=2, spacing3=2,
            cursor="arrow")
        self.salida.grid(row=2, column=0, sticky="nsew")
        for etiqueta, color in COLORES.items():
            self.salida.tag_configure(etiqueta, foreground=color)
        self.salida.tag_configure("orden", foreground=COLORES["orden"], font=(LETRA, 11, "bold"))

        # 2. Entrada
        marco_entrada = tk.Frame(tarjeta, background=PAPEL_OSCURO, highlightthickness=2,
                                 highlightbackground=MARRON, highlightcolor=NARANJA)
        marco_entrada.grid(row=3, column=0, sticky="ew", pady=(10, 8))
        marco_entrada.columnconfigure(1, weight=1)
        tk.Label(marco_entrada, text=">", font=(LETRA, 12, "bold"), fg=NARANJA,
                 bg=PAPEL_OSCURO).grid(row=0, column=0, padx=(8, 2))
        self.entrada = tk.Entry(marco_entrada, font=(LETRA, 12), fg=MARRON, bg=PAPEL_OSCURO,
                                insertbackground=MARRON, relief="flat", borderwidth=0)
        self.entrada.grid(row=0, column=1, sticky="ew", ipady=7)
        self.entrada.bind("<Return>", lambda _: self.enviar())
        self.boton_enviar = tk.Button(marco_entrada, text="✎ enviar", font=(LETRA, 11, "bold"), fg=NARANJA,
                                      activeforeground=MARRON, bg=PAPEL_OSCURO, activebackground=PAPEL_OSCURO,
                                      relief="flat", borderwidth=0, cursor="hand2", command=self.enviar)
        self.boton_enviar.grid(row=0, column=2, padx=(4, 10))

        # 3. Control (barra inferior, como los iconos del ejemplo): programar + pánico
        marco_control = tk.Frame(tarjeta, background=PAPEL)
        marco_control.grid(row=4, column=0, sticky="ew", pady=(2, 4))
        marco_control.columnconfigure(5, weight=1)
        estilo_texto = dict(font=(LETRA, 11, "bold"), fg=NARANJA, bg=PAPEL)
        estilo_caja = dict(font=(LETRA, 11, "bold"), fg=MARRON, bg=PAPEL_OSCURO, buttonbackground=PAPEL_OSCURO,
                           relief="flat", highlightthickness=2, highlightbackground=MARRON,
                           highlightcolor=NARANJA, width=3, justify="center", validate="key")
        tk.Label(marco_control, text="⏱ programar en", **estilo_texto).grid(row=0, column=0, padx=(0, 8))
        validar = (raiz.register(self._validar_numero), "%P", "%W")
        self.minutos = tk.Spinbox(marco_control, from_=0, to=MAX_MINUTOS, validatecommand=validar,
                                  name="minutos", **estilo_caja)
        self.minutos.grid(row=0, column=1)
        tk.Label(marco_control, text="min", **estilo_texto).grid(row=0, column=2, padx=(4, 10))
        self.segundos = tk.Spinbox(marco_control, from_=0, to=MAX_SEGUNDOS, validatecommand=validar,
                                   name="segundos", **estilo_caja)
        self.segundos.grid(row=0, column=3)
        tk.Label(marco_control, text="s", **estilo_texto).grid(row=0, column=4, padx=(4, 10))
        self.boton_panico = tk.Button(marco_control, text="■ PARAR", width=13, font=(LETRA, 12, "bold"),
                                      fg=PAPEL, bg=COLORES["error"], activeforeground=PAPEL,
                                      activebackground=MARRON, relief="flat", borderwidth=0, cursor="hand2",
                                      command=self.panico)
        self.boton_panico.grid(row=0, column=6, sticky="e", ipady=5)
        self._tarjeta = tarjeta

        logging.getLogger("personalagent").addHandler(ManejadorVentana(self.cola))
        # Aviso siempre encima mientras actúa (también en las tareas programadas).
        self.aviso = Aviso(raiz)
        self.avisos: queue.Queue = queue.Queue()
        escuchar(self.avisos.put)
        raiz.after(100, self._vaciar_cola)
        self._estado()
        self.entrada.focus_set()

    def _dibujar_tarjeta(self, evento) -> None:
        """Sombra marrón desplazada + tarjeta crema con borde, redondeadas (se redibuja al cambiar el tamaño)."""
        ancho, alto = evento.width, evento.height
        x1, y1 = MARGEN, MARGEN
        x2, y2 = ancho - MARGEN - SOMBRA, alto - MARGEN - SOMBRA
        self.lienzo.delete("tarjeta")
        rectangulo_redondeado(self.lienzo, x1 + SOMBRA, y1 + SOMBRA, x2 + SOMBRA, y2 + SOMBRA, RADIO,
                              fill=MARRON, outline=MARRON, tags="tarjeta")
        rectangulo_redondeado(self.lienzo, x1, y1, x2, y2, RADIO, fill=PAPEL, outline=MARRON,
                              width=BORDE, tags="tarjeta")
        self.lienzo.tag_lower("tarjeta")
        relleno = RADIO // 2 + 12   # que el contenido no pise las esquinas redondeadas
        self.lienzo.coords(self._ventana_tarjeta, x1 + relleno, y1 + 10)
        self.lienzo.itemconfigure(self._ventana_tarjeta, width=max(1, x2 - x1 - 2 * relleno),
                                  height=max(1, y2 - y1 - 20))

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
        try:
            while True:
                aviso = self.avisos.get_nowait()
                if aviso:
                    self.aviso.mostrar(aviso)
                else:
                    self.aviso.ocultar()
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
        respuesta = ejecutar_comando(self.agente, texto, "interfaz")
        if respuesta is not None:
            self.escribir(f"> {texto}", "orden")
            for linea in respuesta.splitlines():
                self.escribir("  " + linea, "sistema")
            self._actualizar_boton()   # 'reanudar' cambia el estado del botón de pánico
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
                                    text="trabajando…" if ocupado else "✎ enviar")
        self._estado()

    def _estado(self) -> None:
        """Indicador de la barra superior: ● listo / ● trabajando… / ■ en pausa."""
        if control.en_pausa():
            self.estado.configure(text="■ en pausa", fg=COLORES["error"])
        elif self.ocupado:
            self.estado.configure(text="● trabajando…", fg=NARANJA)
        else:
            self.estado.configure(text="● listo", fg=COLORES["ok"])

    # --- Botón de pánico -----------------------------------------------------------

    def panico(self, como: str = "el botón de pánico") -> None:
        if control.en_pausa():
            control.reanudar()
            registrar_actividad("interfaz", "Agente reanudado.")
            self.escribir("▶ Agente reanudado.", "sistema")
        else:
            pausar_por_panico("interfaz", como)
            self.escribir(f"■ PARADO ({como}): lo que estuviera haciendo se corta y no hará nada más "
                          "(tampoco las tareas programadas) hasta que pulses Reanudar.", "error")
        self._actualizar_boton()

    def parar_por_atajo(self) -> None:
        """El atajo global solo para (reanudar, con el botón o el comando 'reanudar')."""
        if not control.en_pausa():
            self.panico(atajo_legible())

    def _actualizar_boton(self) -> None:
        if control.en_pausa():
            self.boton_panico.configure(text="▶ REANUDAR", bg=COLORES["ok"])
        else:
            self.boton_panico.configure(text="■ PARAR", bg=COLORES["error"])
        self._estado()


class Aviso:
    """
    Recuadro siempre encima, arriba en el centro de la pantalla, con lo que está
    haciendo el agente. NO se activa al mostrarse (WS_EX_NOACTIVATE): si robara
    el foco, el texto iría a parar a él en vez de a la app donde se escribe.
    """

    WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000
    SW_HIDE, SW_SHOWNOACTIVATE = 0, 4

    def __init__(self, raiz: tk.Tk):
        self.raiz = raiz
        self.ventana = tk.Toplevel(raiz, background=MARRON)
        self.ventana.overrideredirect(True)
        self.ventana.attributes("-topmost", True)
        self.ventana.attributes("-alpha", 0.94)
        self.etiqueta = tk.Label(self.ventana, font=(LETRA, 11, "bold"), fg=NARANJA, bg=PAPEL,
                                 padx=14, pady=7, justify="left")
        self.etiqueta.pack(padx=3, pady=3)   # borde marrón de 3 px, como la tarjeta
        self.ventana.update_idletasks()
        self.hwnd = int(self.ventana.wm_frame(), 16)
        try:
            import ctypes
            self.user32 = ctypes.windll.user32
            estilo = self.user32.GetWindowLongW(self.hwnd, -20)
            self.user32.SetWindowLongW(self.hwnd, -20, estilo | self.WS_EX_TOPMOST
                                       | self.WS_EX_TOOLWINDOW | self.WS_EX_NOACTIVATE)
        except (AttributeError, OSError):
            self.user32 = None
        self.ventana.withdraw()
        self._ocultar_id = None

    def mostrar(self, texto: str) -> None:
        if self._ocultar_id:
            self.raiz.after_cancel(self._ocultar_id)
            self._ocultar_id = None
        texto = texto if len(texto) <= 70 else texto[:67] + "…"
        self.etiqueta.configure(text=f"🤖 El agente está actuando: {texto}\n    {atajo_legible()} para parar")
        self.ventana.update_idletasks()
        ancho = self.ventana.winfo_reqwidth()
        x = (self.raiz.winfo_screenwidth() - ancho) // 2
        self.ventana.geometry(f"+{x}+14")
        if self.user32:
            self.user32.ShowWindow(self.hwnd, self.SW_SHOWNOACTIVATE)
        else:
            self.ventana.deiconify()

    def ocultar(self, tras_ms: int = 900) -> None:
        def ocultar_ya():
            self._ocultar_id = None
            if self.user32:
                self.user32.ShowWindow(self.hwnd, self.SW_HIDE)
            else:
                self.ventana.withdraw()
        if self._ocultar_id:
            self.raiz.after_cancel(self._ocultar_id)
        self._ocultar_id = self.raiz.after(tras_ms, ocultar_ya)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interfaz del agente")
    parser.add_argument("--sin-llm", action="store_true", help="no usar el LLM (no ocupa la GPU)")
    parser.add_argument("--llm-cpu", action="store_true", help="usar el LLM sin GPU (lento)")
    args = parser.parse_args()

    configurar_logs(consola=False)   # los avisos van a la ventana; la traza, a data/ultima_orden.log
    raiz = tk.Tk()
    agente = Agente(usar_llm=LLM_ACTIVO and not args.sin_llm or args.llm_cpu, llm_cpu=args.llm_cpu,
                    canal="interfaz")
    interfaz = Interfaz(raiz, agente)
    iniciar_atajo_panico(lambda: raiz.after(0, interfaz.parar_por_atajo))
    interfaz.escribir(describir_llm(agente.estado_llm()), "sistema")
    interfaz.escribir(f"Escribe una orden y pulsa Enter. {atajo_legible()} para el agente desde cualquier ventana.",
                      "sistema")
    interfaz.escribir(AYUDA, "sistema")
    agente.precargar()
    agente.iniciar_agenda()
    raiz.mainloop()


if __name__ == "__main__":
    main()
