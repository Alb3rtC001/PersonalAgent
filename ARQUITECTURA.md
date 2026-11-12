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
                     (llama.cpp + OLMo 3 7B, Apache 2.0) para lo que no entienda,
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
| `requiere_confirmacion`     | Si es irreversible (enviar, borrar, comprar...).                  |
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
- **Fase 3 — Router híbrido.** Modelo propio pequeño para las órdenes
  conocidas + LLM abierto (llama.cpp + OLMo 3 7B) para el resto. Frase →
  JSON `{skill, parametros}` o plan de varias skills, restringido por
  esquema y validado contra el catálogo. Decisión y motivos en §10.
- **Fase 4 — Memoria y contexto.** Contexto de sesión, verificador de éxito
  general, recuperación de episodios parecidos como ejemplos.
- **Fase 5 — Acciones robustas.** UI Automation; grabador v2 que guarda el
  control pulsado (nombre, tipo) en vez de coordenadas; OCR solo si no hay otra opción.
- **Fase 6 — Aprendizaje continuo.** Episodios → dataset → reentreno del
  clasificador y LoRA del LLM; propuesta automática de skills compuestas a
  partir de secuencias repetidas.
- **Fase 7 — Voz.** faster-whisper (voz a texto), Piper (texto a voz),
  openWakeWord (palabra de activación).
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

1. **Ahora (fase 2):** JSONL, solo añadir al final, con un lock para los
   hilos de la API. Todo el acceso pasa por `core/memoria.py`, así que
   cambiar el almacenamiento no toca el resto del código.
2. **Fase 4:** migrar a **SQLite** (`data/agente.db`): tablas de episodios,
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
          LLM abierto (llama.cpp + OLMo 3 7B)
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
  (fase 6).
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

### Modelo: OLMo 3 7B Instruct (Ai2, Apache 2.0)

- **Licencia Apache 2.0:** uso, modificación y redistribución libres, sin
  registro ni límites de uso. Las directrices de "uso responsable" de Ai2
  son recomendaciones, no condiciones de la licencia.
- **El más auditable:** a diferencia de Qwen, Mistral, Llama o Gemma (que
  solo publican los pesos), Ai2 publica también los **datos de
  entrenamiento, el código y los pasos intermedios**. Es la única forma de
  saber qué sesgos puede tener un modelo en vez de suponerlo.
- **Cabe en la GPU:** cuantizado a Q4_K_M ocupa ~4,5 GB (RTX 3060 Ti, 8 GB).
- **Plan B: Qwen3-8B (Apache 2.0),** más fuerte en español y en elegir
  herramientas, pero solo publica pesos. La elección final se hace con
  datos: un conjunto de evaluación propio (frases → skill y parámetros
  esperados) y se queda el que acierte más. El modelo es un parámetro de
  `config.py`: cambiarlo es cambiar un archivo.
- **Descartados:** Llama (licencia propia con condiciones de uso y
  atribución obligatoria) y Gemma (términos de uso propios).
- Se usa el archivo GGUF original o una conversión comprobada, y se guarda
  junto a su licencia en `models/` (no se sube a git).
