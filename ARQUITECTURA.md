# PersonalAgent — Nueva arquitectura

Documento de diseño. Recoge cómo queremos reorganizar el proyecto, qué se
aprovecha del código actual y en qué orden se construye cada pieza.

---

## 1. Punto de partida: ¿entrenar por demostración abarata el entrenamiento?

**En parte sí, y conviene matizar en qué.**

Lo que **sí** abarata grabar tú las acciones:
- **Definir una acción nueva** no requiere programarla: demuestras y el
  sistema la generaliza. Es el ahorro más grande.
- **Los datos salen perfectos**: cada grabación es un ejemplo correcto,
  con el resultado comprobado. No hay que etiquetar a mano ni limpiar ruido.
- **No hace falta GPU ni nube** para "aprender" una acción grabada: es
  guardar una plantilla, no entrenar una red.

Lo que **no** resuelve por sí solo:
- Grabar no enseña al sistema a **planificar** (a decidir qué acciones
  combinar para un objetivo nuevo). Eso lo hace otra pieza (el planificador).
- Las grabaciones por coordenadas son **frágiles**: cambia la resolución,
  el tema o el diseño de una app y dejan de funcionar.

### Cómo conseguir que "se entrene solo" a partir de tus acciones

No hace falta entrenar un modelo grande desde cero. Hay tres mecanismos
complementarios, de más barato a más caro:

1. **Componer sin entrenar (en contexto).** Un LLM local pequeño recibe el
   catálogo de acciones (nombre, descripción, parámetros) y elige cuáles
   encadenar. Añadir una acción al catálogo la hace utilizable al instante,
   sin reentrenar nada. Es lo que en el mundo de los LLM se llama *tool use*.
2. **Memoria de episodios.** Cada orden ejecutada se guarda (frase,
   intención, parámetros, plan, si funcionó). Ante una frase nueva se
   recuperan los episodios exitosos más parecidos y se le pasan al
   planificador como ejemplos. El sistema mejora con el uso sin entrenar.
3. **Reentrenamiento periódico con tus datos.** Los episodios exitosos se
   convierten automáticamente en dataset (frase → plan). Con eso se
   reentrena el clasificador actual (segundos, en CPU) y, más adelante, se
   ajusta el LLM con LoRA/QLoRA (horas, en tu RTX 3060 Ti de 8 GB).

Conclusión: tu idea es correcta. **Tus demostraciones y tu uso diario son los
datos de entrenamiento**, y todo se puede hacer en local. Lo que cambia es que
las "acciones" deben ser piezas bien descritas (skills) que un planificador
pueda combinar, en vez de categorías fijas del clasificador.

---

## 2. Principios de diseño

1. **100 % local.** Ninguna pieza del núcleo usa servicios de pago ni internet.
2. **Skill = unidad de acción.** Todo lo que el agente sabe hacer es una
   skill con un contrato común (ver §4), da igual cómo esté implementada.
3. **Preferir lo robusto:** API nativa de Python > UI Automation de Windows
   > plantilla grabada por coordenadas. La grabación sigue existiendo como
   último recurso y como forma de *enseñar* acciones nuevas.
4. **Toda acción se verifica.** Una skill no ha terminado hasta comprobar
   que el efecto existe (el archivo está escrito, la ventana apareció...).
5. **Todo se registra.** Cada ejecución deja un episodio: es la memoria y el
   futuro dataset.
6. **Seguridad por defecto.** Las acciones irreversibles piden confirmación;
   si el sistema no está seguro, pregunta en vez de actuar.
7. **El núcleo no sabe quién le habla.** La CLI de hoy, la API de mañana y
   el móvil de pasado mañana son solo clientes del mismo núcleo.

---

## 3. Capas

```
 Clientes        CLI (hoy) · API HTTP local (FastAPI) · móvil · voz
                         │
 Entrada         texto ── (más adelante: voz → faster-whisper → texto)
                         │
 Comprensión     Router: frase → {intención | objetivo, parámetros, confianza}
                 v0: clasificador PyTorch actual + slots.py
                 v1: modelo propio pequeño para las órdenes conocidas + LLM abierto
                     (llama.cpp + Qwen3-8B, Apache 2.0) para lo que no entienda,
                     con salida JSON restringida y validada (ver §10)
                         │
 Planificación   objetivo → secuencia de skills
                 v0: una intención = una skill
                 v1: el LLM propone el plan; STRIPS valida precondiciones
                         │
 Ejecución       Executor: valida parámetros → confirma si es arriesgado →
                 ejecuta → verifica → registra episodio → replanifica si falla
                         │
 Skills          nativas (Python) · UI Automation (pywinauto) · plantillas grabadas
                         │
 Estado          window_manager (ventanas, procesos, monitores) + contexto de sesión
                         │
 Memoria         episodios (data/episodios.jsonl) · contexto de sesión · preferencias
                         │
 Aprendizaje     (offline) episodios → dataset → reentrenar clasificador / LoRA del LLM
```

---

## 4. Contrato de una skill

Cada skill hereda de `core.skills.base.Skill` y declara:

| Campo / método              | Para qué sirve                                                    |
| --------------------------- | ----------------------------------------------------------------- |
| `nombre`                    | Identificador único (`crear_nota`).                               |
| `descripcion`               | Texto que leerá el LLM para decidir si usarla.                    |
| `parametros`                | Parámetros obligatorios con su descripción.                       |
| `parametros_opcionales`     | Parámetros opcionales.                                            |
| `requiere_confirmacion`     | Si es irreversible (enviar, borrar, comprar...): siempre se confirma. |
| `confirmar_si_llm`          | Si tiene consecuencias (cerrar una app): se confirma cuando la orden la interpretó el LLM. |
| `ejecutar(**params)`        | Hace la acción y devuelve un `Resultado`.                         |
| `verificar(resultado)`      | Comprueba en el mundo real que el efecto existe.                  |
| *(futuro)* `precondiciones` / `efectos` | Para que STRIPS valide planes.                        |

`Resultado` lleva `ok`, `mensaje`, `datos` y, si falta información,
`falta` (el nombre del parámetro que hay que pedir al usuario).

---

## 5. Estructura de carpetas objetivo

```
core/                    # Núcleo nuevo
  skills/
    base.py              # Skill + Resultado + precondiciones/efectos (hecho)
    crear_nota.py        # Skill nativa              (hecho)
    abrir_aplicacion.py  # Skill nativa              (hecho)
    cerrar_aplicacion.py # Skill nativa              (hecho)
    restaurar_ventana.py # Skill nativa              (hecho)
    plantilla.py         # Adaptador: plantilla grabada → skill (hecho)
  agente.py              # Fachada para los clientes (hecho)
  registro.py            # Catálogo de skills        (hecho)
  router.py              # Frase → skill + parámetros (hecho, envuelve nlu/)
  planner.py             # Planificador por regresión (hecho)
  executor.py            # Confirmar + ejecutar + verificar + replanificar + registrar (hecho)
  estado.py              # Ventanas, monitores, hechos (hecho, antes window_manager.py)
  memoria.py             # Episodios                 (hecho)
  sesion.py              # Contexto de sesión (fase 4)
api/                     # FastAPI local: servidor.py, token.py, __main__.py (hecho)
cliente.py               # CLI que pasa por la API (hecho)
nlu/                     # Se mantiene: clasificador + slots
recorder/                # Se mantiene; en fase 5 graba controles UIA, no coordenadas
  catalogo.json          # Qué plantillas se publican como skill (hecho)
data/                    # Notas, episodios… (no se sube a git)
tests/
```

### Qué se aprovecha y qué se rehace

| Pieza actual                         | Decisión                                                           |
| ------------------------------------ | ------------------------------------------------------------------ |
| `nlu/` (clasificador, dataset, slots)| **Se aprovecha** como router v0 y atajo rápido del v1.             |
| `recorder/` (grabar, generalizar)    | **Se aprovecha**; se envuelve como skill y en fase 5 se mejora.    |
| `window_manager.py`                  | **Se aprovecha** como capa de estado.                              |
| `planner.py` (STRIPS)                | **Se reescribe**: operadores hardcodeados → skills con precondiciones. |
| `plan_executor.py`                   | **Se sustituye** por `core/executor.py`.                           |
| `acctions/`                          | **Se sustituye** por `core/skills/`.                               |
| `dispatcher.py`                      | Pasa a ser solo un cliente CLI del núcleo.                         |
| `fix_recordings.py`, `rebuild_recordings.py` | Se revisan en fase 5.                                      |

---

## 6. Problemas actuales y su solución

| Problema                                                                 | Solución                                                         | Fase |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------- | :--: |
| `plan_executor.py` importaba un módulo inexistente; el dispatcher no arrancaba | Import corregido                                            | 0 ✅ |
| `crear_nota` era un placeholder                                          | Skill nativa que escribe un `.md` y verifica                     | 0 ✅ |
| `extraer_slot` devolvía el texto en minúsculas y sin tildes              | Ahora conserva el texto original del usuario                     | 0 ✅ |
| No se guardaba ningún historial                                          | Episodios en `data/episodios.jsonl`                              | 0 ✅ |
| La replanificación de `plan_executor` no tiene efecto y detecta errores buscando el texto "ERROR" | Executor nuevo con `Resultado.ok` real        | 1 ✅ |
| El operador `restaurar_steam` no tiene plantilla                         | Skill nativa `restaurar_ventana` con pygetwindow                 | 1 ✅ |
| Abrir apps tecleando en el menú Inicio es frágil                         | Skill nativa: índice del menú Inicio (`Get-StartApps`) + `shell:AppsFolder` | 1 ✅ |
| El reproductor preguntaba con `input()` (imposible desde una API)        | La confirmación la pide el executor mediante una función inyectada | 1 ✅ |
| El reproductor no podía escribir tildes ni eñes                          | Texto no ASCII se pega desde el portapapeles                     | 1 ✅ |
| "cerrar calculadora" abría la Calculadora: el clasificador ignora las palabras que no conoce | Skill `cerrar_aplicacion` + 40 frases de cierre; los verbos desconocidos ("minimiza", "reinicia") quedan por debajo del umbral y se rechazan | 2 ✅ |
| Clics por coordenadas se rompen al cambiar la pantalla                   | UI Automation (pywinauto) y grabador que guarda controles        | 5 |
| Clasificador de categorías fijas: no entiende objetivos nuevos ni varios parámetros | LLM local con salida estructurada                     | 3 |
| Sin contexto entre órdenes ("abre WhatsApp" → "llama a mamá")            | `core/sesion.py` con caducidad                                   | 4 |
| `requirements.txt` con paquetes que no se usan                           | Limpiarlo y separar dependencias opcionales                      | 1 ✅ |
| `.gitignore` con rutas con `\` que git no entiende                       | Reescribirlo                                                     | 1 ✅ |
| *Revisión de la fase 3:* la caché PID → proceso no caducaba; con la API días encendida, un PID reutilizado podía hacer que "cierra discord" cerrase otra app | La caché vive solo durante una enumeración de ventanas | 3 ✅ |
| El reproductor seguía tras un paso fallido (podía hacer el clic "definitivo" en el sitio equivocado) | Se detiene en el primer error | 3 ✅ |
| Pegar texto con tildes machacaba el portapapeles del usuario | Se restaura tras pegar | 3 ✅ |
| `llama-server` quedaba vivo (ocupando VRAM) si el agente moría de golpe | Job Object de Windows: muere con el agente | 3 ✅ |
| Si el LLM no arrancaba (sin VRAM), cada orden esperaba otro intento | Reintento cada 5 min; sin archivos, no se reintenta | 3 ✅ |
| Una línea a medio escribir en `episodios.jsonl` rompía `/episodios` | Se ignora | 3 ✅ |
| `cliente.py` se cerraba con un traceback si el servidor caía o respondía un error no JSON | Errores capturados y mostrados | 3 ✅ |
| La lectura de la GPU fallaba siempre en este PC (el driver da la temperatura con decimales) y las protecciones de VRAM y temperatura no se aplicaban | Se leen los números con decimales | 4 ✅ |
| Sin forma de desactivar el LLM sin editar código | `--sin-llm`, `llm off/on`, `POST /llm`, `PERSONALAGENT_LLM`, descarga por inactividad | 3 ✅ |
| Al dar el foco a una ventana se perdía la primera tecla escrita después (el truco de pulsar ALT activaba el menú de la app) | `AttachThreadInput` + movimiento de ratón nulo; sin teclas falsas | 3 ✅ |
| Las apps de la Store minimizadas dejan una ventana interna "camuflada" (cloaked) que el agente tomaba por visible: no se restauraban ni recibían el foco | Las ventanas camufladas se ignoran | 3 ✅ |
| `escribir_texto` escribe en la ventana, pero no puede saber si el cursor está en el campo correcto | UI Automation: elige el campo (el del cursor, el único que haya o el que digas) y después lee lo escrito (§11) | 5 ✅ |
| `abrir_aplicacion` da por buena cualquier ventana nueva (una notificación que aparezca a la vez cuenta como éxito) | En parte: ya no cuentan las del propio agente (su aviso "está actuando" daba la Calculadora por abierta antes de aparecer, y el "cierra la calculadora" siguiente fallaba). Pendiente: exigir un proceso lanzado tras la orden (ojo con el Explorador) | 5 |
| *Revisión general:* una pestaña "Steam Store - Opera" contaba como Steam: "abre steam" traía Opera al frente y el planificador creía Steam abierto | `ventanas_de`: coincidencia estricta (título exacto, " - App" o proceso); después, el proceso; el título suelto solo en `restaurar_ventana` | 6 ✅ |
| "A las 12 de la noche" se programaba a las 12 del mediodía del día siguiente | 12 de la noche = 00:00 del día siguiente; 12 de la madrugada = 00:00 | 6 ✅ |
| Con Slay the Spire 2 en marcha, "juega al Slay the Spire" decía "ya está en marcha" (una carpeta era el principio de la otra) | Se compara la carpeta con su separador | 6 ✅ |
| El LLM devolvía a veces solo Ctrl+L para "busca X en google" (búsqueda que no se hace) | `plan_incompleto`: se le pide que lo corrija | 6 ✅ |
| Cada skill consultaba por su cuenta las apps del menú Inicio (1,5 s la primera vez de cada una) | Una consulta compartida, precargada al arrancar | 6 ✅ |
| Leer una ventana con UI Automation iba control a control (Steam: 1,2 s por lectura; un clic, 4-5 s) | `uia.controles`: todo de una vez con caché (FindAllBuildCache, vista cruda): ~0,5 s; un clic, ~2 s | 6 ✅ |

---

## 7. Hoja de ruta

Cada fase termina con algo que funciona de punta a punta.

- **Fase 0 — Base mínima (hecha).** `core/` con contrato de skill,
  executor, memoria de episodios y `crear_nota` real. Dispatcher arranca.
- **Fase 1 — Núcleo único (hecha).** `core/agente.py` (fachada),
  `router.py`, `planner.py` (regresión sobre precondiciones/efectos
  declarados por cada skill), `executor.py` (confirmar → ejecutar →
  verificar → replanificar una vez → registrar), `estado.py`;
  `abrir_aplicacion` y `restaurar_ventana` nativas; plantillas publicadas
  vía `recorder/catalogo.json`; retirados `acctions/`, `planner.py`,
  `plan_executor.py` y `window_manager.py`; 16 tests.
- **Fase 2 — API local (hecha).** `python -m api` (FastAPI + uvicorn) con
  token en la cabecera `X-Token`: `POST /ordenes`, `POST /ordenes/{id}`
  (contestar un dato o una confirmación), `DELETE /ordenes/{id}`,
  `GET /skills`, `GET /episodios`, `GET /salud`. `cliente.py` es una CLI
  que pasa por la API (el mismo camino que usará el móvil); `dispatcher.py`
  sigue disponible sin servidor. Una sola orden se ejecuta a la vez.
- **Fase 3 — Router híbrido (en curso).** Modelo propio pequeño para las
  órdenes conocidas + LLM abierto (llama.cpp + Qwen3-8B) para el resto.
  Frase → JSON `{skill, parametros}` o plan de varias skills, restringido
  por esquema y validado contra el catálogo. Decisión y motivos en §10.
  - ✅ `core/llm.py` + router híbrido (clasificador actual + LLM), conjunto
    de evaluación y `python -m evaluacion.evaluar`; `origen` en los episodios.
  - ✅ Comparado con Qwen3-8B: Qwen gana en acierto, velocidad y memoria y pasa a ser el modelo por defecto.
  - ⏳ Sustituir el clasificador bag-of-words por un transformer pequeño
    propio que también extraiga los parámetros.
  - ✅ Órdenes de varios pasos: pasan a la fase 4 (ver abajo).
- **Fase 4 — Memoria, contexto y órdenes compuestas (hecha).**
  - ✅ Órdenes de varios pasos: el LLM devuelve `{"pasos": [...]}` (máx. 12);
    si algún paso tiene consecuencias se confirma el plan entero una vez; se
    ejecutan en orden y paran en el primer fallo; un episodio por orden.
  - ✅ Atajos de teclado por aplicación (`core/atajos_apps.json`): el LLM los
    usa con `pulsar_teclas` ("busca X en opera" = control l + escribir + enter).
  - ✅ Contexto "última aplicación" (también dentro de un plan).
  - ✅ Autocorrección: si la respuesta del LLM no es válida, se le enseña el
    error y la corrige una vez.
  - ✅ Protección de la GPU (§12).
  - ✅ Tareas programadas: cualquier orden con una expresión de tiempo al
    principio o al final ("dentro de 5 min", "a las 17:30", "mañana a las 9")
    se interpreta ya, se confirma SIEMPRE al programarla y se guarda en SQLite
    (`data/agente.db`); un hilo la ejecuta a su hora sin volver a preguntar.
    Si el agente estaba apagado y han pasado más de 10 min, se marca como
    perdida. `ver_tareas`, `cancelar_tarea`, `GET/DELETE /tareas`. En una
    nota la hora es contenido: no se programa.
  - ✅ Memoria: hasta 3 órdenes tuyas parecidas que salieron bien se le
    enseñan al LLM como ejemplos (parecido de texto por trigramas, CPU, ms).
    Se guarda lo interpretado antes de rellenar con el contexto.
  - ✅ Steam por sus archivos y su protocolo: `ejecutar_en_steam` lanza con
    `steam://rungameid/<id>` y comprueba que el juego arranca (sustituye a la
    plantilla de clics); `actualizaciones_steam` lee los `appmanifest_*.acf`.
- **Seguridad y control (antes de la fase 5).**
  - ✅ Botón de pánico (`core/control.py`): corta lo que esté en marcha en el
    siguiente punto de control (cada carácter, cada espera, cada paso) y deja
    el agente en pausa, también la agenda, hasta reanudar.
  - ✅ Interfaz (`interfaz.py`): respuestas, entrada, temporizador (min/s) y
    botón de pánico.
  - ✅ Aviso siempre encima mientras actúa (sin robar el foco) y atajo global
    de pánico Ctrl+Alt+P (`ATAJO_PANICO`).
  - ✅ Niveles de riesgo por skill (lectura, bajo, medio, alto) con
    `POLITICA_RIESGO` y modo seguro (`seguro on/off`) — `core/seguridad.py`.
  - ✅ Ventanas prohibidas (`VENTANAS_PROHIBIDAS`): ni el teclado ni las
    plantillas actúan sobre contraseñas, banca, terminales, registro...
  - ✅ Registro de actividad legible (`data/actividad.log`, comando
    `actividad`, `GET /actividad`) y `POST /pausa` en la API.
- **Fase 5 — Grabadora semántica + LLM (hecha).**
  - ✅ Grabadora semántica (`recorder/grabadora_semantica.py`, `core/uia.py`):
    cada clic se guarda como el control pulsado (identificador, nombre,
    tipo) y su ventana; lo escrito, con el campo que tenía el foco; los
    atajos, como teclas. Nunca graba contraseñas, ventanas prohibidas ni la
    propia ventana del agente. F9 termina.
  - ✅ Skills grabadas (`core/skills/grabada.py`, `recorder/grabadas/*.json`):
    al reproducir busca cada control por su identidad (probado: la ventana
    movida de sitio y el resultado correcto). Riesgo alto por defecto.
  - ✅ En la interfaz, `grabar <nombre>`: graba, eliges el parámetro y la
    skill está disponible al momento; el LLM la usa por su descripción
    ("suma 4 a siete" → `sumar_a_siete(numero=4)`). También
    `python -m recorder.grabar`.
  - ✅ Leer la pantalla para responder (`leer_pantalla`,
    `core/skills/pantalla.py`): lee el texto de la ventana con UI Automation
    (CPU, sin capturas) y el LLM responde a la pregunta ("qué pone en la
    calculadora" → "La pantalla muestra 144", ~2 s). El texto de la
    pantalla se le pasa como información, nunca como órdenes; no lee
    ventanas prohibidas; con el LLM desactivado devuelve el texto tal cual.
  - ✅ `escribir_texto` escribe en el campo correcto (§11): el que tiene el
    cursor, el único de la ventana, o el que digas ("escribe pizza en el
    buscador de chrome", parámetro opcional `campo`). Si hay varios y no
    dices cuál, pregunta en vez de escribir a ciegas.
  - ✅ Comprueba lo escrito: después de escribir lee el campo; si no
    contiene el texto, la verificación falla (y el ejecutor replanifica).
    Las apps web (Steam) actualizan el valor con retraso: se relee hasta
    ~1,6 s. Los campos de búsqueda se vacían antes (Ctrl+A, Supr y se
    comprueba que quedan vacíos) y después deben contener exactamente lo
    escrito.
  - ✅ Varias ventanas de una app (`core/skills/ventanas.py`,
    `elegir_entre`): la única a la vista, la elegida antes (15 min), la que
    se llama como la app, o se pregunta cuál (número o parte del título).
    Lo usan escribir_texto, pulsar_teclas, hacer_clic, leer_pantalla,
    restaurar_ventana y abrir_aplicacion (si ya estaba abierta).
  - ✅ Cierre limpio (`CIERRE_LIMPIO`): Steam se cierra con `steam://exit`,
    sin cerrar sesión, en vez de terminar su proceso. Probado: cerrado,
    sin procesos, y al reabrir la cuenta seguía iniciada.
  - ✅ `hacer_clic` (`core/skills/clic.py`): pulsa un botón, pestaña o
    enlace visible por su nombre. Nunca pulsa `CONTROLES_PROHIBIDOS`
    (comprar, pagar, borrar...), no hace clic si hay otra ventana encima y
    tiene riesgo "medio". En `core/atajos_apps.json` cada app puede tener
    `botones` y `campos` además de `atajos`. Probado de verdad: "busca en
    steam el juego slay the spire 2" → abrir Steam → clic en "Biblioteca"
    → escribir en "Buscar por nombre"; el campo y la lista lo confirman.
    Solo pulsa controles que se ven de verdad (en su centro está el propio
    control: Steam tiene un JUGAR escondido en una cabecera), pregunta si
    hay varios igual de buenos y comprueba que la ventana cambia; si no, no
    da el clic por bueno. Probado: "dale a jugar" lanza el juego.
  - ✅ El prompt del LLM siempre cabe: `LLM_CONTEXTO` = 6144 y, si aun así
    no cabe (muchos ejemplos), se pasan solo los que vienen al caso
    (`seleccionar_ejemplos`: los de "ninguna", el primero de cada skill y
    los más parecidos). Antes, con 4096, una orden con contexto de Steam y
    memoria daba error 400 y caía al clasificador.
  - Lección: un éxito falso envenena la memoria (el LLM copia la orden
    "que salió bien"). La verificación honesta de cada skill es lo que
    protege el aprendizaje de la fase 7.
  - ✅ Campo recordado por app (`core/campos.py`, `data/campos.json`): el
    que dices o eliges al preguntarte se usa la próxima vez sin preguntar
    (por AutomationId o nombre). Si no hay ninguno recordado, pregunta cuál.
  - ✅ Apps nuevas (`core/controles_app.py`): si la orden nombra una app abierta
    que no está en `atajos_apps.json`, sus botones y campos visibles van al
    LLM como contexto y como valores válidos. Probado: "en la calculadora
    pulsa el botón pi" → hacer_clic 'Pi'. Si aun así no sabe, propone `grabar`.
  - ✅ `abrir_aplicacion` ya no da por buena una ventana nueva de otro
    programa que ya estaba en marcha (una notificación): tiene que ser de un
    proceso arrancado por la orden (o del Explorador).
  Diseño original: UI Automation (CPU,
  sin GPU): la grabadora guarda el control pulsado (tipo, nombre,
  AutomationId) y los atajos usados, no coordenadas; con una sola
  demostración el LLM la convierte en una skill con parámetros; al
  reproducir se busca cada control por su nombre y se verifica leyéndolo.
  Lectura de pantalla para preguntas ("¿hay alguien en el canal?", "¿qué
  pone?"). Campo destino de `escribir_texto` (§11). Apps nuevas: el LLM
  propone un plan a partir de la lista de controles de la ventana, se
  confirma y se guarda si funciona; si no, "hazlo tú y lo grabo".
- **Fase 6 — Voz (hecha).** faster-whisper (voz a texto) en la CPU.
  - ✅ Botón del micrófono en la interfaz (`core/voz.py`): graba hasta que
    te callas (o pulsas otra vez) y Whisper "small" lo pasa a texto en la
    CPU con int8 (no usa VRAM; ~2 s para una orden de 3 s). El audio no se
    guarda.
  - ✅ Confirmación de palabra, sin teclado: la orden queda en el cuadro y el
    micrófono sigue escuchando unos segundos; "enviar"/"enter" la manda,
    "cancelar" la borra y otra frase la sustituye. Un "sí" suelto no manda
    nada (`VOZ_ESCUCHAR_CONFIRMACION`, `VOZ_ENVIAR_AL_TERMINAR`).
  - ✅ Dictado con calma: corta tras 3 s de silencio (`VOZ_SILENCIO_FIN`); "enviar"
    y las respuestas a ventanas, tras 1 s (`VOZ_SILENCIO_FIN_RESPUESTA`).
  - ✅ Nombres propios y en inglés (`core/vocabulario.py`): pista a Whisper
    con las apps, botones, juegos de Steam y `data/vocabulario_voz.txt`, y
    corrección por cómo suena ("Estim" → Steam).
  - ✅ Ventanas de seguridad de una orden por voz contestadas de palabra,
    solo tras el código (`VOZ_CODIGO_SEGURIDAD` o `data/codigo_voz.txt`).
  - ⏳ Opcional, más adelante: texto a voz (Piper) y palabra de activación
    (openWakeWord).
- **Fase 7 — Aprendizaje continuo (en curso).** Episodios → dataset → reentreno del
  clasificador y LoRA del LLM; propuesta automática de skills compuestas a
  partir de secuencias repetidas.
  - ✅ `aprendizaje/datos.py`: las órdenes que resolvió el LLM y salieron
    bien (verificadas, no corregidas, de una skill) → `data/frases_aprendidas.json`.
  - ✅ `aprendizaje/reentrenar.py` (comando `aprende`): reentrena como
    `nlu/training.py` más lo aprendido y solo cambia el modelo si no empeora
    en aciertos ni en "seguras y mal" (evaluacion/ordenes.json). Con tus
    episodios actuales (4 frases) no mejora y se queda el de antes.
  - ✅ `aprendizaje/propuestas.py`: planes del LLM repetidos (lo que cambia,
    parámetro) y órdenes que das seguidas → `aprende crea <n> <nombre>` →
    `data/compuestas/*.json` (`core/skills/compuesta.py`, riesgo del paso
    más delicado). Probado: "abre steam" + "ve a la biblioteca" → una orden.
  - ⏳ LoRA del LLM con los episodios (cuando haya cientos), entorno aparte
    con PyTorch CUDA y respetando el límite de GPU.
  - ⏳ Clasificador más capaz (transformer pequeño que extraiga parámetros),
    entrenado con el mismo bucle.
- **Fase 8 — Móvil y domótica.** App cliente contra la API del PC;
  domótica vía Home Assistant (local).

---

## 8. Riesgos a vigilar

- **Calidad del LLM local:** un 7–8B se equivoca más que uno en la nube. Se
  compensa con salida validada, confirmación en acciones arriesgadas y
  verificación tras actuar.
- **Python 3.14:** algunas librerías (p. ej. CUDA para PyTorch) pueden tardar
  en tener versión compatible. Si hace falta GPU para entrenar, valorar un
  entorno separado con Python 3.12.
- **VRAM:** el LLM ocupa ~4,8 GB de 8 (§12). Si otra cosa (un juego)
  necesita la GPU: `llm off`, `--sin-llm` o esperar a que se descargue solo
  por inactividad. Sin LLM el agente sigue funcionando con el clasificador.
- **Seguridad de la API:** escucha solo en `127.0.0.1` y exige token. Para
  el móvil habrá que abrirla a la red local (`0.0.0.0`) y, como el token
  viaja en claro por HTTP, valorar HTTPS con certificado autofirmado.

---

## 9. Almacenamiento de la memoria (episodios, skills, conocimiento)

**Decisión: seguir con JSONL de momento; pasar a SQLite + embeddings en la
fase 4. No hacen falta MongoDB ni un servidor de base vectorial.**

Qué guarda el agente hoy:

| Dato                    | Dónde                        | Volumen esperado                       |
| ----------------------- | ---------------------------- | -------------------------------------- |
| Episodios (órdenes)     | `data/episodios.jsonl`       | ~50/día → ~20 000/año → unos 10–20 MB  |
| Catálogo de skills      | código + `recorder/catalogo.json` | decenas o cientos                 |
| Plantillas grabadas     | `recorder/templates.json`    | decenas o cientos                      |
| Dataset del clasificador| `nlu/dataset.json`           | cientos o miles de frases              |

Por qué no MongoDB: es un servidor aparte (instalar, arrancar, mantener)
para un único usuario con datos pequeños. No aporta nada que SQLite (que
viene con Python, es un solo archivo y aguanta millones de filas) no dé.

Por qué no todavía una base vectorial: sirve para buscar "episodios
parecidos" por significado, y eso solo hace falta cuando exista algo que
use esos resultados (el planificador con LLM, fase 3–4). Con unos miles de
episodios, comparar vectores con numpy a fuerza bruta tarda milisegundos.

Plan de evolución (todo local y gratuito):

1. **Fases 2–4 (hecho):** episodios en JSONL, solo añadir al final, con un
   lock para los hilos de la API. La memoria de órdenes parecidas (fase 4)
   los lee de ahí con parecido de texto en CPU; con miles de episodios tarda
   milisegundos, así que de momento no hace falta más. Las tareas
   programadas sí van en **SQLite** (`data/agente.db`).
2. **Cuando haga falta:** pasar también los episodios a SQLite: tablas de episodios,
   pasos y contexto de sesión, con consultas reales (por skill, por fecha,
   solo fallidos...). Los embeddings de cada frase se calculan en local
   (p. ej. `sentence-transformers` multilingüe, ~100 MB, CPU) y se guardan
   en la misma base. Búsqueda por similitud con numpy, o con la extensión
   **sqlite-vec** si crece.
3. **Solo si pasa de cientos de miles de vectores:** una base vectorial
   embebida (LanceDB o Chroma en modo local), que también es un archivo y
   no un servidor.

---

## 10. Fase 3: modelo propio + LLM abierto (decisión)

**Criterios** (por orden): 100 % local y sin internet al usarlo; licencia
sin ataduras (uso, modificación y redistribución libres, sin registro ni
condiciones de uso); ningún dato sale del PC; el menor sesgo posible y,
sobre todo, que se pueda auditar.

### Arquitectura híbrida

```
frase ──► modelo propio pequeño (nlu/, entrenado aquí con tus frases)
            │  confianza ≥ umbral y sin verbos desconocidos ──► {skill, params}
            │  si no
            ▼
          LLM abierto (llama.cpp + Qwen3-8B)
            prompt = catálogo de skills (Skill.describir()) + frase
            salida RESTRINGIDA por un JSON Schema generado del catálogo:
            solo puede responder una skill que existe, con sus parámetros
            ──► validación (Skill.validar) ──► planner/executor como hoy
```

- El modelo propio responde en milisegundos a lo que ya conoce y es 100 %
  tuyo. Hoy es el clasificador bag-of-words; en esta fase se sustituye por
  un transformer pequeño (pocos millones de parámetros) entrenado desde
  cero con `nlu/dataset.json` + frases generadas, que además extrae los
  parámetros (adiós a los disparadores de `slots.py`).
- El LLM solo entra cuando el modelo propio no está seguro. Sus respuestas
  correctas (confirmadas por el resultado del episodio) se añaden al
  dataset: con el tiempo el modelo propio cubre más y el LLM se usa menos
  (fase 7).
- El sesgo del LLM influye poco: no opina ni redacta, solo elige una skill
  del catálogo con salida restringida, y el executor confirma lo arriesgado
  y verifica el resultado.

### Runtime: llama.cpp (no Ollama)

Los dos son MIT y funcionan sin internet. Se elige **llama.cpp** porque:

- Es el motor: Ollama está construido encima de él. Menos capas.
- Se usa el binario oficial `llama-server` (versiones precompiladas para
  Windows con CUDA, sin compilar nada), arrancado por el propio agente en
  `127.0.0.1`: no queda ningún servicio residente ni actualizaciones
  automáticas.
- Carga un archivo `.gguf` de tu disco; no hay catálogo online ni cuenta.
- Admite salida restringida por JSON Schema / gramática GBNF, que es lo que
  garantiza que solo conteste skills válidas.

Ollama es una alternativa válida (también MIT), pero añade un servicio en
segundo plano, su propio registro de modelos online y auto-actualización.

### Modelo elegido: Qwen3-8B (Apache 2.0), tras compararlo con OLMo 3

La primera elección fue OLMo 3 7B por ser el más auditable (motivos
abajo). Tras medir los dos con las mismas frases, el agente usa
**Qwen3-8B** (`Qwen/Qwen3-8B-GGUF`, Q4_K_M), porque gana en acierto, en
velocidad y en memoria:

| Solo el LLM, Q4_K_M, RTX 3060 Ti    | OLMo 3 7B | Qwen3-8B |
| ----------------------------------- | :-------: | :------: |
| Conjunto de ajuste (52 frases)      | 96 %      | **100 %** |
| Conjunto de control (30 frases que no se usaron para ajustar nada) | 97 % | **100 %** |
| Tiempo por orden (mediana)          | ~0,87 s   | **~0,43 s** |
| Memoria de GPU del modelo           | ~6,3 GB   | **~5,4 GB** |
| Carga del modelo                    | 3,6 s     | 4,1 s    |

(Porcentajes de skill + parámetros correctos. El prompt se ajustó mirando
los fallos de OLMo, así que la comparación no favorece a Qwen.)

Lo que se cede: Qwen solo publica los pesos, no los datos de
entrenamiento, así que su sesgo no se puede auditar como el de OLMo. Las
condiciones que pediste siguen intactas: licencia Apache 2.0 (sin
registro, sin condiciones de uso, redistribuible), archivo local y ningún
dato sale del PC. Y en este uso el sesgo apenas influye: solo elige una
skill del catálogo con salida restringida y validada. OLMo 3 sigue en
`models/` como alternativa: cambiarlo es cambiar `RUTA_MODELO_LLM` en
`config.py`.

### Primera opción: OLMo 3 7B Instruct (Ai2, Apache 2.0)

- **Licencia Apache 2.0:** uso, modificación y redistribución libres, sin
  registro ni límites de uso. Las directrices de "uso responsable" de Ai2
  son recomendaciones, no condiciones de la licencia.
- **El más auditable:** a diferencia de Qwen, Mistral, Llama o Gemma (que
  solo publican los pesos), Ai2 publica también los **datos de
  entrenamiento, el código y los pasos intermedios**. Es la única forma de
  saber qué sesgos puede tener un modelo en vez de suponerlo.
- **Cabe en la GPU:** cuantizado a Q4_K_M ocupa ~4,5 GB (RTX 3060 Ti, 8 GB).
- **Plan B: Qwen3-8B (Apache 2.0),** más fuerte en español y en elegir
  herramientas, pero solo publica pesos. La elección final se hizo con
  datos (tabla de arriba).
- **Descartados:** Llama (licencia propia con condiciones de uso y
  atribución obligatoria) y Gemma (términos de uso propios).
- Se usa el archivo GGUF original o una conversión comprobada, y se guarda
  junto a su licencia en `models/` (no se sube a git).

### Cómo decide el router cuándo preguntar al LLM

El clasificador responde solo si está seguro **y** no hay señales de que
haya acertado "de casualidad". Se pregunta al LLM si:

- la intención es "ninguna", la confianza está por debajo del umbral o la
  intención no tiene skill;
- no se reconoció ninguna frase disparadora (el "valor" sería la frase entera);
- hay palabras desconocidas fuera del valor (un verbo nuevo: "reinicia steam");
- el valor tiene varias palabras y alguna es desconocida ("me apetece cs2").

Salvaguardas sobre la respuesta del LLM:

- Salida restringida por JSON Schema: solo skills del catálogo y sus parámetros.
- Cada valor se "ancla" al texto del usuario (si el modelo escribe "bloque
  de notas" y el usuario dijo "bloc de notas", se usa lo del usuario).
- Los parámetros opcionales que el usuario no dijo (un título inventado) se quitan.
- Un nombre corto que no aparece en la frase es una invención ("cuánto es
  15 por 3" → abrir "calculetta"): se rechaza la orden.
- Si el clasificador y el LLM coinciden en la skill pero el LLM reformuló
  el valor, se usa el trozo literal que extrajo el clasificador.
- Si el LLM no está disponible, se usa lo que diga el clasificador.
- Las skills con consecuencias declaran `confirmar_si_llm = True`
  (`cerrar_aplicacion`): si la orden la interpretó el LLM, se pide
  confirmación antes de ejecutarla. Motivo: en una prueba real, "minimiza
  discord" se interpretó una vez como cerrar Discord. Las que interpreta el
  clasificador (entrenado con tus frases) no preguntan.

### Resultados (`python -m evaluacion.evaluar`)

Con Qwen3-8B. `ordenes.json` (79 frases tras la fase 5, usado para
ajustar; incluye órdenes de varios pasos, `leer_pantalla` y `campo`) y
`ordenes_control.json` (30 frases que no se usaron para ajustar nada):

| Vía               | Ajuste: skill + parámetros | Control: skill + parámetros | Tiempo por frase |
| ----------------- | :------------------------: | :-------------------------: | ---------------- |
| Solo clasificador | 46 % (con 76 frases)       | —                           | < 2 ms           |
| Solo LLM          | 95 % (con 76 frases)       | —                           | ~0,55 s          |
| Híbrido           | 99 % (78/79)               | 100 % (30/30)               | 0 ms (conocidas) – ~0,6 s mediana (nuevas) |

Fallo del híbrido: "busca recetas de lentejas en google" (se queda en el
primer paso). En
`evaluacion/*.json` un valor `"*"` acepta cualquier texto (la pregunta de
`leer_pantalla`, que el LLM puede reformular).

Ojo con los ejemplos de `core/llm_ejemplos.json`: cambian el
comportamiento de todo el modelo. Un ejemplo "dime qué tiempo hace" →
`ninguna` hizo que rechazara "reinicia steam"; tras cada cambio en los
ejemplos, vuelve a pasar la evaluación. Son pocas frases: para medir de verdad hay que ir
añadiendo órdenes reales (de `data/episodios.jsonl`) al conjunto de control.

---

## 11. Escribir en el campo correcto (fase 5: puntos 1, 2 y 3 hechos)

`escribir_texto` y `pulsar_teclas` ponen la **ventana** en primer plano y
comprueban que tiene el foco del teclado. Pero dentro de la ventana el
texto va al **control** que tenga el cursor, y eso no siempre es el campo
que quieres:

| App | ¿Funciona hoy? | Por qué |
| --- | -------------- | ------- |
| Calculadora | Sí | Toda la ventana acepta teclado |
| Bloc de notas | Sí | El único control es el área de texto |
| Discord, Telegram, WhatsApp | Normalmente | Al activarse ponen el cursor en el cuadro de mensaje (pero no si estabas en el buscador) |
| Chrome / Google | No siempre | El cursor puede estar en la página, en la barra de direcciones o en ningún sitio |

### Qué está hecho (fase 5)

`escribir_texto` (`core/skills/teclado.py`, `preparar_campo` y
`comprobar_escrito`) usa UI Automation (`core/uia.py`) antes y después de
escribir:

1. Con `campo` ("escribe hola en el buscador de discord"): busca entre los
   campos editables de la ventana el de nombre más parecido ("buscador" ~
   "Buscar", "mensaje" ~ "Enviar mensaje a #general") y lo enfoca. Si
   ninguno se parece, dice cuáles hay.
2. Sin `campo`: si el cursor ya está en un campo editable de esa ventana,
   escribe ahí; si no, y solo hay uno, lo enfoca; si hay varios, pregunta
   cuál; si no hay ninguno (la Calculadora), escribe en la ventana.
3. Después lee el valor del campo: si no contiene el texto, `verificar`
   falla. Si el campo no se puede leer, no se da por fallido.

Probado con un formulario de dos campos (Nombre y Buscar) y con la
Calculadora. El punto 2 también está hecho (`core/campos.py`), sin grabador:
se aprende del campo que dices o eliges. Falta el 4.

### Solución propuesta, por capas (de más barata a más cara)

1. **Mirar dónde está el cursor (UI Automation).** Windows expone el árbol
   de controles de casi todas las apps (Win32, WPF, Store, Chrome/Edge,
   Electron como Discord) a través de UI Automation, la API de
   accesibilidad. Con ella se puede preguntar qué control tiene el foco y
   si es editable (tipo *Edit* o *Document*, no de solo lectura). Si lo
   es, se escribe; si no, se busca uno. Además permite **leer el valor**
   después de escribir, que es la verificación que hoy falta. Librerías
   locales y libres: `uiautomation` (Apache 2.0) o `pywinauto` (BSD).

2. **Aprenderlo por demostración, una vez por app.** Un "grabador de campo":
   le dices "aprende dónde se escribe en Chrome", haces clic en el buscador
   y el agente guarda el control bajo el ratón (tipo, nombre, AutomationId),
   no las coordenadas. Se guarda en `data/campos.json` (app → selector) y a
   partir de ahí `escribir_texto` enfoca ese control antes de escribir.
   Es la misma idea que el grabador v2 de la fase 5. Encaja con tu idea de
   que aprenda de lo que le enseñas, y no necesita entrenar ninguna red:
   es una memoria de "en esta app, aquí".

3. **Que el LLM elija entre los candidatos.** Cuando no hay nada aprendido
   o dices el campo ("escribe hola en el buscador"), se le pasa al LLM la
   lista de controles editables de la ventana (nombre y tipo, p. ej.
   "Barra de direcciones y de búsqueda", "Buscar", "Mensaje en #general")
   con salida restringida a esa lista, igual que hoy con las skills. Lo que
   elijas se guarda como en el punto 2. `escribir_texto` ganaría un
   parámetro opcional `campo`.

4. **Atajos de teclado por app** (complemento barato): muchas apps tienen
   uno para ir al campo (Ctrl+L en los navegadores, "/" en muchas webs).
   Se pueden guardar por app en el mismo `data/campos.json`.

5. **Visión, solo como último recurso:** un modelo que localice el campo
   en una captura de pantalla (detección de elementos de interfaz). Sirve
   para apps sin accesibilidad (juegos, lienzos), pero pide más GPU y es
   menos fiable. No hace falta para las apps habituales.

**¿Un modelo propio para esto?** No hace falta al principio: los puntos 1
y 2 lo resuelven sin entrenar nada, y el 3 reutiliza el LLM que ya
tenemos. Con muchas apps y muchos campos aprendidos sí tendría sentido un
modelo pequeño que ordene los controles candidatos (por tipo, nombre,
tamaño y posición) a partir de tus elecciones guardadas, para acertar en
apps nuevas parecidas (p. ej., el cuadro de mensaje de cualquier app de
chat). Sería un clasificador pequeño como el de `nlu/`, entrenado con
`data/campos.json`.

---

## 12. Uso de la GPU (límite: no pasar del uso actual)

La RTX 3060 Ti (8 GB) es de uso diario: el agente no debe saturarla.

| Medida | Efecto |
| ------ | ------ |
| Modelo cuantizado a 4 bits (Q4_K_M) | ~4,7 GB de pesos en vez de ~16 GB |
| Una conversación a la vez (`-np 1`), flash attention, caché KV en 8 bits (`LLM_ARGUMENTOS_EXTRA`) | ~4,8 GB en total (antes ~5,3), misma velocidad y respuestas (medido) |
| `LLM_VRAM_MAX_MIB` (5.200) | Límite de VRAM del LLM: si no cabe entero, solo van a la GPU las capas que quepan (leídas del GGUF, ~116 MiB cada una) y el resto al procesador. Tras cargar se mide y, si se pasa, se recarga con menos capas |
| `LLM_MARGEN_VRAM_MIB` (500) | Si no queda libre lo que ocupará el LLM + este margen (p. ej. jugando), no se carga: sigue el clasificador y lo reintenta en 5 min |
| `LLM_TEMPERATURA_MAX` (83 °C) | Si la GPU pasa de ahí, no se carga o se descarga |
| `LLM_DESCARGAR_TRAS` (15 min) | Sin uso, se descarga y la VRAM queda libre |
| `llm off`, `--sin-llm`, `POST /llm` | Descargarlo a mano en cualquier momento |
| Job Object | Si el agente muere de golpe, el LLM muere con él |

Sobre "quemar la GPU": el LLM trabaja a ráfagas de menos de un segundo
por orden (no como un juego, que la tiene al 100 % sin parar), y la propia
tarjeta baja su velocidad si se calienta. Si aun así quieres un margen
extra, se puede limitar su consumo con `nvidia-smi -pl <vatios>` (lo tienes
que hacer tú, como administrador; el agente no cambia ajustes del sistema).

Las piezas nuevas siguen esta regla: la grabadora semántica y la lectura de
pantalla (UI Automation) y la memoria con episodios parecidos (similitud de
texto) van en el procesador, sin GPU. Ningún modelo nuevo se cargará en la
GPU a la vez que el LLM.
