# Guía: usar el agente, enseñarle acciones y mejorar cómo entiende

Esta guía es la parte práctica. El diseño y los motivos están en
[ARQUITECTURA.md](ARQUITECTURA.md); la instalación, en el [README](README.md).

---

## 1. Qué hay ahora mismo (resumen de las fases 0–3)

```
 tu frase ──► ROUTER ──────────────────────────────► PLANNER ──► EXECUTOR ──► SKILLS
              1. clasificador propio (nlu/)          pasos      confirmar,    crear_nota
                 milisegundos, entrenado con         previos    ejecutar,     abrir_aplicacion
                 tus frases                          (abrir     verificar,    cerrar_aplicacion
              2. si duda: LLM local (Qwen3-8B)       Steam      replanificar, restaurar_ventana
                 ~0,4 s, solo puede elegir skills    antes...)  registrar     escribir_texto
                 del catálogo                                       │          pulsar_teclas
                                                                    │          + plantillas grabadas
                                                                    ▼            (ejecutar_en_steam)
                                                     data/episodios.jsonl  ◄── de aquí se aprende
```

El agente recuerda **la última aplicación** con la que has trabajado (15
min): después de "abre la calculadora", "escribe 2+2" y "pulsa enter" van
a la Calculadora sin repetirlo. Una skill lo pide con
`del_contexto = {"aplicacion": "ultima_aplicacion"}`.

| Pieza | Dónde | Qué hace |
| ----- | ----- | -------- |
| Skills | `core/skills/` + `recorder/catalogo.json` | Todo lo que el agente sabe hacer. Cada una declara descripción, parámetros, precondiciones, efectos y cómo se verifica. |
| Clasificador | `nlu/` | Frase → intención. Se entrena con `nlu/dataset.json`. Rápido, pero solo conoce las palabras que ha visto. |
| Extracción del valor | `nlu/slots.py` | Quita las palabras de la orden ("ábreme", "apunta que") para quedarse con el valor ("nombre_aplicacion"). |
| LLM | `core/llm.py`, `models/` | Qwen3-8B en tu GPU vía llama.cpp, solo en 127.0.0.1. Entra cuando el clasificador duda. |
| Ejemplos del LLM | `core/llm_ejemplos.json` | Frases resueltas que el LLM ve en cada consulta. |
| Planner / executor | `core/planner.py`, `core/executor.py` | Calcula pasos previos, pide confirmación, ejecuta, verifica, replanifica, registra. |
| Memoria | `data/episodios.jsonl` | Cada orden: frase, skill, parámetros, quién la interpretó (`origen`), si funcionó. |
| API | `api/` | La misma lógica por HTTP (para el móvil). |
| Evaluación | `evaluacion/` | Frases con su respuesta correcta para medir si un cambio mejora o empeora. |

Lo importante para enseñarle cosas: **hay tres "palancas" distintas**.

| Palanca | Qué mejora | Cómo se cambia | ¿Reentrenar? |
| ------- | ---------- | -------------- | ------------ |
| Catálogo de skills (descripción y parámetros) | Lo que el LLM sabe que existe | `catalogo.json` o la clase Python | No |
| Dataset del clasificador | Que tus frases habituales vayan rápidas y sin LLM | `add_phrases.py` | Sí: `python .\nlu\training.py` (segundos) |
| Ejemplos del LLM | Casos que el LLM confunde | `core/llm_ejemplos.json` | No |
| Atajos por aplicación | Que haga cosas dentro de una app sin skill propia (nueva pestaña, ir a un canal...) | `core/atajos_apps.json` | No |

El LLM (Qwen3) **no se reentrena** de momento: se le "enseña" con el
catálogo y los ejemplos. Ajustar sus pesos con tus episodios (LoRA) es la
fase 7, cuando haya cientos de órdenes reales registradas (sección 7).

---

## 2. Uso diario

```powershell
.\.venv\Scripts\Activate.ps1      # si usas el entorno virtual
python .\interfaz.py             # ventana con botón de pánico y temporizador
python .\dispatcher.py            # consola directa
python .\dispatcher.py --sin-llm  # solo el clasificador: no usa la GPU
# o bien: python -m api  (y en otra terminal: python .\cliente.py)
```

- Al arrancar verás `… Cargando el modelo de lenguaje…` (unos 4 s, en
  segundo plano). Mientras está cargado, el LLM ocupa ~5,4 GB de la GPU.
  Se libera al salir, al escribir `llm off`, o solo tras 15 min sin usarlo
  (`LLM_DESCARGAR_TRAS`); vuelve a cargarse cuando hace falta.
- `llm` muestra su estado; `llm off` / `llm on` lo desactiva o activa en
  marcha (también en `cliente.py` y con `POST /llm` en la API). Sin LLM
  el agente sigue funcionando con el clasificador: entiende tus frases
  entrenadas y rechaza las nuevas.
- Si una orden la interpreta el LLM y la acción tiene consecuencias
  (cerrar una app), **te pedirá confirmación**. Las que reconoce el
  clasificador no preguntan. En la interfaz, la confirmación es una ventana
  de seguridad (cabecera oscura con escudo). Enseña los pasos en lenguaje
  normal ("Pulsar «JUGAR» en Steam") y el detalle técnico debajo. Se
  contesta con "Sí, continuar" / "No, cancelar", o con Enter / Esc.
- `Ctrl+C` cancela la orden en curso.

---

## 3. Cuando una frase no se entiende o se entiende mal

1. **Mira qué pasó.** La traza completa de la última orden está en
   `data/ultima_orden.log`: qué dijo el clasificador y por qué dudó, qué
   respondió el LLM, el plan, cada paso con su duración y, si algo falló,
   el error con el archivo y la línea del código. El historial de todas
   las órdenes está en el último episodio:

   ```powershell
   Get-Content data\episodios.jsonl -Tail 5
   ```

   Fíjate en `skill`, `parametros`, `origen` (`clasificador` o `llm`) y `mensaje`.

2. **Decide qué palanca toca:**

   | Síntoma | Arreglo |
   | ------- | ------- |
   | La acción no existe ("No sé hacer eso todavía") | Crear una skill (secciones 4 y 5) |
   | `origen: clasificador`, skill equivocada | Añadir frases al dataset y reentrenar (sección 6) |
   | `origen: clasificador`, skill bien pero el valor lleva palabras de más ("spotify ya") | Añadir el disparador en `nlu/slots.py` (sin reentrenar) |
   | `origen: llm`, skill equivocada | Mejorar la `descripcion` de la skill y/o añadir un ejemplo a `core/llm_ejemplos.json` |
   | `origen: llm`, bien pero lenta (~0,5 s) | Añadir la frase al dataset para que la resuelva el clasificador |

3. **Mide** que no has roto nada (sección 8).

---

## 4. Enseñar una acción nueva por demostración (sin programar)

### Con la grabadora semántica (recomendado)

En la interfaz escribe `grabar` (o `grabar buscar en spotify`):

1. Te pide el nombre y **qué hace**: esa frase es la que lee el LLM para
   saber cuándo usarla ("Busca una canción en Spotify y la reproduce").
2. Haz la acción con el ratón y el teclado. Arriba verás "● GRABANDO".
   **F9** termina.
3. Te enseña los pasos y te pregunta qué texto escrito **cambia cada vez**
   (el parámetro: la canción, el número...).
4. Ya está: pídela con tus palabras ("pon bohemian rhapsody en spotify").
   Es de riesgo alto, así que te pedirá confirmación.

Graba **qué** pulsas (el botón "Siete", el cuadro "Buscar"), no dónde:
sigue funcionando aunque muevas la ventana o cambie de tamaño. No graba
contraseñas, ventanas prohibidas ni la ventana del agente. Se guarda en
`recorder/grabadas/<nombre>.json` (lo puedes editar o borrar). Desde la
consola: `python -m recorder.grabar`.

Consejos: empieza con la app ya abierta; usa atajos de teclado cuando la
app los tenga (son más fiables que los clics); si un paso falla al
reproducir, el mensaje dice cuál y la traza (`data/ultima_orden.log`) da el
detalle.

### Con el grabador antiguo (plantillas por coordenadas)

Para acciones que haces con teclado y ratón (p. ej. "buscar X en Spotify").

```powershell
# 1. Graba la acción al menos 2 veces, cambiando SOLO el valor variable
#    (p. ej. una vez buscas "queen" y otra "estopa"). F9 termina cada grabación.
python .\recorder\recorder.py          # te pide el nombre: buscar_en_spotify

# 2. Genera la plantilla (detecta qué parte cambia entre grabaciones = el parámetro)
python .\recorder\build_templates.py
```

3. **Publícala** en `recorder/catalogo.json` (sin esto no es una skill):

   ```json
   "buscar_en_spotify": {
     "descripcion": "Busca una canción, artista o disco en Spotify y lo reproduce.",
     "parametro": "busqueda",
     "descripcion_parametro": "Lo que hay que buscar, p. ej. 'queen' o 'bohemian rhapsody'",
     "precondiciones": {"visible:spotify": true},
     "efectos": {},
     "coste": 2,
     "requiere_confirmacion": false
   }
   ```

   - `descripcion`: **es lo que lee el LLM** para decidir si usarla. Di
     qué hace y qué no, en una frase clara.
   - `precondiciones`: con `{"visible:spotify": true}` el planificador
     abrirá o restaurará Spotify antes, solo.
   - `requiere_confirmacion: true` si la acción es irreversible (enviar,
     comprar, borrar). `confirmar_si_llm: true` si tiene consecuencias
     pero solo quieres confirmar cuando la interpretó el LLM.
     (No marques pasos `"definitivo"` a mano en `templates.json`:
     `build_templates.py` regenera ese archivo y la marca se pierde.)

4. **Pruébala.** Ya funciona a través del LLM, sin entrenar nada:
   `python .\dispatcher.py` → `pon algo de queen en spotify`.

5. **(Opcional, recomendado) Hazla rápida:** añade ~20–30 frases al
   dataset con la intención `buscar_en_spotify`, sus disparadores en
   `nlu/slots.py` (`"busca en spotify"`, `"pon en spotify"`...) y
   reentrena (sección 6).

---

## 4b. Enseñarle atajos de una aplicación (sin programar)

Muchas acciones dentro de una app no necesitan una skill: basta con que el
LLM sepa sus atajos y los combine con `pulsar_teclas` y `escribir_texto`
en varios pasos. "busca el horario del mercadona en opera" se convierte en
`control l` → escribir → `enter`.

Añade la app (o atajos nuevos) en `core/atajos_apps.json`:

```json
"Microsoft Word": {
  "nombres": ["word"],
  "atajos": {
    "guardar": "control g",
    "negrita": "control n",
    "nuevo documento": "control u"
  }
}
```

- `nombres`: cómo la puedes llamar en las órdenes.
- La descripción de cada atajo es lo que lee el LLM: si un atajo va
  seguido de algo (escribir y Enter), dilo ("ir al buscador: después
  escribir y pulsar enter").
- Las teclas con los nombres que entiende `pulsar_teclas` (`control`,
  `shift`, `alt`, `enter`, `tab`, flechas, `f1`…`f12`, letras).
- Al LLM solo se le pasan los atajos de las apps que nombras y de la última
  que has usado, para no alargar el prompt.

**Botones y campos** (para apps sin atajos, como Steam): con `botones` y
`campos` el LLM sabe qué pulsar con `hacer_clic` y dónde escribir con
`escribir_texto`. Pon el nombre tal como se ve en pantalla:

```json
"Steam": {
  "nombres": ["steam"],
  "botones": {
    "ir a la biblioteca de juegos (para buscar uno: después escribir su nombre en el campo 'Buscar por nombre')": "Biblioteca",
    "ir a la tienda": "Tienda"
  },
  "campos": {
    "buscar un juego en la biblioteca (está tras pulsar 'Biblioteca')": "Buscar por nombre"
  }
}
```

Con eso, "busca en steam el juego slay the spire 2" se convierte en: abrir
Steam (si no está abierto) → clic en "Biblioteca" → escribir "slay the
spire 2" en "Buscar por nombre". Para saber cómo se llama un botón, pídele
que pulse algo que no existe: te responde con los nombres que ve.

**Órdenes de varios pasos:** "abre la calculadora, escribe 25*4 y pulsa
enter" se ejecuta paso a paso. Si algún paso tiene consecuencias (pulsar
teclas, cerrar...), primero te enseña el plan completo y lo confirmas una
vez. Si un paso falla, se para ahí y te dice cuál.

## 4c. Programar órdenes para más tarde

Cualquier orden con una expresión de tiempo **al principio o al final** se
programa en vez de hacerse ya:

| Orden | Cuándo |
| ----- | ------ |
| `abre steam dentro de 5 min` | dentro de 5 minutos |
| `cierra google a las 17:30` | hoy a las 17:30 (mañana, si ya pasó) |
| `cuelga la llamada de discord en media hora` | dentro de 30 minutos |
| `mañana a las 9 abre discord` | mañana a las 9:00 |
| `abre la calculadora, escribe 2+2 y pulsa enter en 10 segundos` | órdenes de varios pasos también |

- **Siempre te pide confirmación al programar**, enseñando lo que hará y a
  qué hora. A su hora lo hace sin preguntar (no estarás delante).
- `qué tengo programado` / `cancela la tarea 3` / `cancela la última tarea`
  / `cancela todas las tareas`.
- Solo se ejecutan si el agente está en marcha (`dispatcher.py` o
  `python -m api`). Si estaba apagado y han pasado más de 10 minutos
  (`TOLERANCIA_RETRASO_TAREAS`), la tarea se marca como perdida.
- En una nota, la hora es parte del contenido: `apunta que tengo dentista
  mañana a las 9` crea la nota ahora.

## 4d. Steam

`juega al cs2`, `lanza baldurs gate 3`: busca el juego entre los
instalados (por nombre o siglas) y lo lanza con el protocolo de Steam, sin
clics. `hay actualizaciones en steam` lee los archivos de Steam y te dice
qué juegos tienen una actualización pendiente.

## 4e. Preguntar por lo que hay en pantalla y elegir dónde escribir

**Preguntar** (`leer_pantalla`): `qué pone en la pantalla de la
calculadora`, `quién está conectado en discord`, `qué canción suena en
spotify`, `resume lo que pone en opera`. Lee el texto de la ventana con la
accesibilidad de Windows (sin capturas ni GPU extra) y el LLM responde. Si
la app está cerrada o minimizada, la abre o la restaura antes. Solo lee:
no pulsa ni escribe nada, y no lee ventanas de `VENTANAS_PROHIBIDAS`. Con
el LLM desactivado te enseña el principio del texto tal cual. Algunas apps
(juegos, ventanas dibujadas a mano como la de tkinter) no exponen su texto:
entonces te lo dice.

**Pulsar un botón** (`hacer_clic`): `en steam ve a la tienda`, `haz clic
en ajustes en discord`. Busca el botón, pestaña o enlace visible por su
nombre (sin coordenadas: da igual dónde esté la ventana), comprueba que no
hay otra ventana encima, hace clic y te devuelve el ratón a donde estaba.
Nunca pulsa botones de `CONTROLES_PROHIBIDOS` (comprar, pagar, borrar,
desinstalar, cerrar sesión...): te pide que lo hagas tú. Si la orden la ha
interpretado el LLM, te pide confirmación antes.

- Solo pulsa lo que se ve de verdad: Steam tiene un segundo botón JUGAR
  escondido en una cabecera; antes de pulsar comprueba que en ese punto de
  la pantalla está el propio botón.
- Si varios encajan igual de bien y ninguno se llama exactamente así
  ("Slay the Spire 2 [public-beta]" y "Slay the Spire 2 Demo"), te pregunta
  cuál. Gana el que contiene todo lo que dices: "slay the spire 2" no elige
  "Slay the Spire" (el primer juego).
- Después comprueba que la ventana ha cambiado. Si no ha cambiado nada, no
  dice "Pulsado": te dice que el clic no ha llegado. Excepción: si lo
  pulsado es una sección, pestaña, enlace u opción de una lista ("Biblioteca"
  con la Biblioteca ya abierta), que no cambie nada significa que ya estabas
  ahí, y la orden sigue. Un botón (JUGAR) que no hace nada sigue siendo un
  fallo.

Ejemplo completo en Steam: `quiero que abras steam, busques slay the spire 2
e inicies el juego` → abre Steam, Biblioteca, escribe en el buscador y pulsa
el juego en la lista (se queda en su página); `dale a jugar` pulsa el botón
verde. Si solo quieres jugar, `juega al slay the spire 2` lo lanza
directamente (`ejecutar_en_steam`), sin clics.

**Ojo con la memoria:** las órdenes que salen bien se guardan en
`data/episodios.jsonl` y el LLM las copia como ejemplos. Si una orden se dio
por buena sin serlo, la volverá a hacer igual: márcala como fallida
(`"ok": false`) en ese archivo.

**Elegir el campo** (`escribir_texto` con `campo`): `escribe pizza en el
buscador de chrome`, `en telegram escribe hola en el campo del mensaje`.
Si no dices el campo, escribe donde está el cursor (si está en un cuadro
de texto de esa ventana) o en el único que haya; si hay varios, te
pregunta cuál. En los campos de búsqueda (buscar, filtrar, direcciones)
primero borra lo que hubiera (y comprueba que ha quedado vacío; si no, no
escribe encima); en los demás (un mensaje a medias) se escribe a
continuación, para no borrarte nada. Después lee el campo para comprobar que
el texto está; si no está, la orden cuenta como fallida.

**Varias ventanas de la misma app** (dos ventanas de Chrome, Steam y su
"Lista de amigos"): el agente no elige a ciegas.
1. Si solo hay una a la vista, esa.
2. Si ya elegiste una en los últimos 15 min (`CADUCIDAD_CONTEXTO`), esa.
   La que se acaba de abrir con "abre ..." también cuenta como elegida.
3. La que se llama exactamente como la app ("Steam", no "Lista de amigos").
4. Si sigue la duda, pregunta: "Hay 2 ventanas de 'google': 1) Correo -
   Google Chrome; 2) YouTube - Google Chrome. ¿Cuál uso?". Responde con el
   número ("2", "la segunda") o parte del título ("la de youtube").

En las tareas programadas y en la API no hay a quién preguntar: si hay
duda, no hace nada y lo dice.

**Cerrar Steam** (`cierra steam`): usa su propia salida (`steam://exit`,
como "Steam > Salir"), así que se cierra entero y **la sesión sigue
iniciada**. Otras apps con salida propia se añaden en `CIERRE_LIMPIO`
(`config.py`).

## 4f. Hablarle (botón del micrófono)

En la interfaz, el micrófono junto a "enviar":

1. Púlsalo (se pone rojo: "● escuchando…") y di la orden.
2. Termina cuando llevas **3 s callado** después de hablar
   (`VOZ_SILENCIO_FIN`): las pausas más cortas para pensar no cortan. Para
   terminar antes, púlsalo otra vez. Si no oye
   nada en 8 s, lo deja (¿micrófono silenciado?).
3. Lo que ha entendido aparece en el cuadro de texto y el micrófono **sigue
   escuchando 6 s** (`VOZ_ESPERA_CONFIRMACION`, estado "● ¿enviar?"), sin
   pulsar nada:
   - "enviar", "enter", "intro", "envíalo", "vale, envíalo"… → la manda.
   - "cancelar", "bórralo" → la borra.
   - Otra frase → sustituye a la orden y vuelve a esperar la confirmación.
   - Un "sí" u "ok" suelto no manda nada (podría ser otra conversación).
   - Si te callas, deja de escuchar y la orden se queda en el cuadro (Enter
     también vale).

   Para no tener esa espera, `VOZ_ESCUCHAR_CONFIRMACION = False`; para que se
   envíe sin confirmar, `VOZ_ENVIAR_AL_TERMINAR = True` (en `config.py`).

**Nombres propios y en inglés.** Whisper recibe como pista los nombres que el
agente conoce (apps de `core/atajos_apps.json` con sus botones y campos, y
tus juegos de Steam instalados). Si aun así escribe algo "a la española", se
corrige por cómo suena: "Estim" → Steam, "slay de spire" → Slay the Spire,
"Valdur's GAT3" → Baldur's Gate 3. Para añadir los tuyos (contactos, canales
de Discord, series...), escríbelos uno por línea en `data/vocabulario_voz.txt`.
Los tuyos van primero en la pista. Las líneas que empiezan por `#` no cuentan.

**Ventanas de seguridad de palabra.** Si la orden la diste por voz, las
ventanas "Confirmar acción" y "Falta un dato" (por ejemplo, "¿qué ventana
de Steam?") también se pueden contestar de palabra, pero **solo después de
decir el código**, para que nada que se oiga de fondo las acepte:
- "Código Romeo, sí" (o "no"), o "código Romeo" y luego "sí".
- Para elegir entre opciones: "código Romeo, la dos" (o "2", "la segunda").

Sin el código no hace caso a la voz y se contesta con el teclado o el ratón,
como siempre. Escucha como mucho 60 s (`VOZ_ESCUCHA_DIALOGO`). El código está
en `VOZ_CODIGO_SEGURIDAD` (`config.py`). Como ese archivo está en GitHub, pon
el tuyo en `data/codigo_voz.txt` (una línea), que tiene prioridad y no se sube.
Con `""` se desactiva.

Todo es local: Whisper "small" (`models/faster-whisper-small`) en la CPU,
sin VRAM y sin internet; el audio no se guarda en ningún sitio. Usa el
micrófono por defecto de Windows. El botón de pánico (o Ctrl+Alt+P) también
corta la escucha.

## 5. Crear una skill en Python

Para acciones que se pueden hacer con código (más robustas que una
grabación). Ejemplo: minimizar una ventana, que hoy el agente rechaza.

1. Crea `core/skills/minimizar_ventana.py`:

   ```python
   from __future__ import annotations

   import ctypes

   from core.estado import buscar_ventana, es_visible
   from core.skills.base import Resultado, Skill

   SW_MINIMIZE = 6


   class MinimizarVentana(Skill):
       nombre = "minimizar_ventana"
       descripcion = "Minimiza la ventana de una aplicación abierta (no la cierra)."
       parametros = {"aplicacion": "Nombre de la aplicación, p. ej. 'Discord'"}
       coste = 1
       # Sin EFECTOS a propósito: si declarara {"visible:{aplicacion}": False},
       # el planificador podría usarla como paso previo de otras skills.

       def ejecutar(self, aplicacion: str = "") -> Resultado:
           ventanas = [v for v in buscar_ventana(aplicacion) if es_visible(v)]
           if not ventanas:
               return Resultado(False, f"No veo ninguna ventana visible de '{aplicacion}'.")
           for v in ventanas:
               ctypes.windll.user32.ShowWindow(v["hwnd"], SW_MINIMIZE)
           return Resultado(True, f"'{aplicacion}' minimizada.",
                            datos={"hwnds": [v["hwnd"] for v in ventanas]})

       def verificar(self, resultado: Resultado) -> bool:
           return all(ctypes.windll.user32.IsIconic(h) for h in resultado.datos["hwnds"])
   ```

   El contrato completo (qué es cada campo) está en
   [ARQUITECTURA.md §4](ARQUITECTURA.md) y en `core/skills/base.py`.

2. Regístrala en `core/registro.py` (import + añadirla a `SKILLS_NATIVAS`).

3. **Ojo con los ejemplos del LLM:** `core/llm_ejemplos.json` tiene
   `"minimiza spotify" → ninguna` porque antes no existía. Cámbialo a
   `{"skill": "minimizar_ventana", "parametros": {"aplicacion": "spotify"}}`,
   o el LLM seguirá rechazándolo. Lo mismo en `evaluacion/ordenes.json`
   ("minimiza discord" / "minimiza todas las ventanas" esperan `ninguna`).

4. Escribe un test en `tests/` (mira `tests/test_cerrar_aplicacion.py`:
   simula las ventanas con un diccionario, sin tocar Windows).

5. Opcional: frases en el dataset + disparadores en `slots.py` + reentrenar.

---

## 6. Enseñar frases al clasificador (el "modelo propio")

```powershell
python .\add_phrases.py                    # una frase, interactivo
python .\add_phrases.py .\mis_frases.json  # un lote: [{"frase": "...", "intencion": "..."}]
python .\nlu\training.py                   # reentrenar (segundos, CPU)
```

- Unas **20-30 frases por intención**, variadas (verbos distintos, con y
  sin artículos, con apps distintas). Incluye también frases de
  **otras** intenciones que se parezcan, para que aprenda la diferencia
  ("abre discord" / "cierra discord").
- La intención `ninguna` son cosas que **no** debe hacer (charla,
  preguntas). Añade ahí las que se confunda.
- Después de reentrenar, mira las frases de prueba que imprime al final.

### El bucle de aprendizaje (hoy, a mano)

Cada orden queda en `data/episodios.jsonl`. Las que resolvió el LLM y
funcionaron son las mejores candidatas para el dataset: así la próxima vez
las resuelve tu clasificador, sin LLM y al instante. Para listarlas:

```powershell
python -c "import json; [print(e['skill'], '|', e['texto']) for e in map(json.loads, open('data/episodios.jsonl', encoding='utf-8')) if e.get('origen') == 'llm' and e.get('ok')]"
```

Añádelas con `add_phrases.py` (la intención es la skill que aparece) y
reentrena. Con el tiempo el LLM se usará cada vez menos.

---

## 7. Mejorar el LLM

Hoy, sin reentrenarlo:

1. **Descripción de las skills** (`descripcion` en la clase o en
   `catalogo.json`): es su "manual". Si confunde dos skills, di en cada
   una qué hace y qué no ("No sirve para minimizar").
2. **Ejemplos** (`core/llm_ejemplos.json`): añade la frase que falló con
   su respuesta correcta. Mejor pocos y variados (15–30) que muchos
   parecidos: todos van en cada consulta y alargan el prompt.
3. **Reglas** (`INSTRUCCIONES` en `core/llm.py`): solo para cosas
   generales, no para casos concretos.
4. **Otro modelo**: cualquier GGUF con licencia abierta. Descárgalo en
   `models/`, compáralo con `python -m evaluacion.evaluar --via llm
   --modelo <ruta>` y, si gana, cambia `RUTA_MODELO_LLM` en `config.py`.

Más adelante (fase 7), **ajuste fino con LoRA**: con unos cientos de
episodios reales correctos se entrena un "parche" pequeño sobre Qwen3 en
tu GPU (con QLoRA, un 8B cabe justo en 8 GB) y se carga junto al modelo en
llama.cpp. Requiere un entorno aparte con PyTorch CUDA (Python 3.12).
Hasta tener esos datos, las palancas de arriba rinden más.

---

## 8. Comprobar que un cambio no rompe nada

```powershell
python -m pytest tests                                               # lógica (sin tocar Windows)
python -m evaluacion.evaluar                                         # comprensión: 52 frases
python -m evaluacion.evaluar --ordenes evaluacion\ordenes_control.json   # 30 frases de control
```

- `evaluacion/ordenes.json`: añade aquí frases nuevas con su respuesta
  correcta cuando crees skills.
- `evaluacion/ordenes_control.json`: **no lo uses para ajustar** el
  prompt ni los ejemplos; es para comprobar que las mejoras generalizan.
  Si lo miras para corregir fallos, deja de medir de verdad.
- No pongas en los ejemplos del LLM ni en el dataset frases que estén en
  la evaluación (el número saldría inflado).

### Qué hay que hacer después de cada cambio

| Cambio | Reentrenar (`nlu\training.py`) | `build_templates.py` | Reiniciar el agente |
| ------ | :---: | :---: | :---: |
| Frases en el dataset | ✅ | | ✅ |
| Disparadores en `slots.py` | | | ✅ |
| Grabación nueva | | ✅ | ✅ |
| Entrada en `catalogo.json` / skill Python nueva | | | ✅ |
| `llm_ejemplos.json`, descripciones, `config.py` | | | ✅ |

---

## 9. Lo que todavía no hace

- **Contexto entre órdenes** ("abre WhatsApp" → "escríbele a mamá"): fase 4.
- **Recordar el campo por app:** si eliges "el buscador" en una app, la
  próxima vez no lo recuerda solo (hay que volver a decirlo).
- **Apps sin accesibilidad** (juegos, lienzos): no puede leerlas ni elegir
  campos en ellas; haría falta visión, que pide más GPU.
- **Plantillas antiguas frágiles:** las del grabador antiguo repiten clics
  por coordenadas; las de `grabar` (sección 4) no tienen ese problema.
- **Aprendizaje automático:** el paso de episodios al dataset es manual
  (sección 6); automatizarlo y el LoRA son la fase 7.
- **Clasificador pequeño:** el bag-of-words se sustituirá por un
  transformer pequeño propio que también extraiga los parámetros.
