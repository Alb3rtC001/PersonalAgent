# PersonalAgent
* La idea principal es crear una IA local que no dependa de internet creando un modelo própio y se adecue a las acciones personalizadas para el usuario.
Actualmente 

# Cómo se quiere afrontar el proyecto y sus pasos a seguir (de mforma generalísta)

## (Poyecto 1):
PC application -> agente autónomo con planificación abierta

## (Proyecto 2):
agente autónomo con planificación abierta -> Gestión por voz para Móvil con posibilidad de hacer control domótico.

> **Nueva arquitectura:** ver [ARQUITECTURA.md](ARQUITECTURA.md).
> Todo lo que el agente sabe hacer son *skills* en `core/skills/`
> (`crear_nota`, `abrir_aplicacion`, `cerrar_aplicacion`, `restaurar_ventana`) más las
> plantillas grabadas publicadas en `recorder/catalogo.json`.
> Cada orden queda registrada en `data/episodios.jsonl`.

# Puesta en marcha y pruebas

Todos los comandos se ejecutan en PowerShell **desde la raíz del proyecto**
(la carpeta donde está este README). Requisitos: Windows 10/11 y Python 3.14.

## 1. Preparar el entorno (solo la primera vez)

```powershell
# 1. Crear el entorno virtual (si ya existe la carpeta .venv, sáltate esta línea)
python -m venv .venv

# 2. ACTIVARLO. Sin este paso, pip instala en tu Python global.
.\.venv\Scripts\Activate.ps1

# 3. Comprobar que está activo: debe mostrar una ruta que acabe en \.venv
python -c "import sys; print(sys.prefix)"

# 4. Instalar dependencias (torch tarda un rato: es la versión CPU, ~200 MB)
python -m pip install -r requirements.txt
```

Con el entorno activo, el prompt de PowerShell empieza por `(.venv)`. Hay que
activarlo en **cada terminal nueva** antes de ejecutar nada del proyecto
(también en la segunda terminal del paso 5).

> - Si PowerShell no deja activarlo ("la ejecución de scripts está
>   deshabilitada"), ejecuta una vez
>   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y vuelve a probar.
> - Si al instalar ves `Requirement already satisfied ... in C:\Users\...\Python314\...`,
>   el entorno **no** está activo: vuelve al paso 2.
> - También puedes no usar entorno virtual e instalar en tu Python global
>   (pasos 1–3 fuera); funciona igual.

## 2. Entrenar el clasificador (primera vez y cada vez que cambie el dataset)

`nlu/modelo.pt` no se sube a git, así que en un clon nuevo hay que generarlo:

```powershell
python .\nlu\training.py
```

Al final muestra cómo clasifica unas frases de prueba.

### 2b. LLM local (opcional, recomendado)

Cuando el clasificador no está seguro (frases nuevas como "me haría falta la
calculadora"), el agente pregunta a un LLM que corre en tu PC sin internet:
llama.cpp + Qwen3-8B (Apache 2.0). Hay que descargarlo una vez (~5,3 GB);
los pasos y los hashes están en [models/README.md](models/README.md).

El agente arranca el LLM solo al empezar (tarda unos 4 s, en segundo plano)
y lo para al salir. Ocupa unos 5,4 GB de memoria de la GPU mientras el
agente está abierto. Sin los archivos de `models/` (o con `LLM_ACTIVO =
False` en `config.py`) el agente funciona solo con el clasificador.

Para medir qué tal entiende las órdenes (frases que no están en el
dataset, en `evaluacion/ordenes.json` y `evaluacion/ordenes_control.json`):

```powershell
python -m evaluacion.evaluar
python -m evaluacion.evaluar --ordenes evaluacion\ordenes_control.json
# Comparar con otro modelo GGUF:
python -m evaluacion.evaluar --via llm --modelo models\olmo-3-7b-instruct\Olmo-3-7B-Instruct-Q4_K_M.gguf
```

## 3. Comprobar que todo está bien

```powershell
python -m pytest tests
```

Deben pasar todos los tests (no abren ventanas ni tocan nada del sistema).

## 4. Usar el agente desde la consola (sin servidor)

```powershell
python .\dispatcher.py
```

Órdenes de ejemplo para probar:

| Orden                                   | Qué debería pasar                                                  |
| --------------------------------------- | ------------------------------------------------------------------ |
| `apunta que mañana llamo a María`        | Crea `data/notas/<fecha>_manana-llamo-a-maria.md`                  |
| `crea una nota`                          | Te pregunta qué apuntar y luego la crea                            |
| `abre la calculadora`                    | Abre la Calculadora y comprueba que aparece su ventana             |
| `abre discrod`                           | Abre Discord aunque esté mal escrito. Si ya estaba abierto (aunque esté escondido en la bandeja del sistema) lo trae al frente en vez de relanzarlo |
| `cierra la calculadora`                  | La cierra como si pulsaras su X. Si ya estaba cerrada, lo dice     |
| `cierra discord`                         | Pulsa su X; como Discord solo se esconde en la bandeja del sistema, termina su proceso para cerrarlo del todo (se desactiva con `CERRAR_TERMINA_BANDEJA` en `config.py`). Si una app pregunta "¿Guardar cambios?", no fuerza nada |
| `quiero jugar a <juego>`                 | Si Steam está cerrado lo abre, si está minimizado lo restaura, y luego reproduce la plantilla grabada (pide confirmación antes del último clic) |
| `me haría falta la calculadora`          | Con el LLM: el clasificador no la conoce, el LLM la entiende como `abrir_aplicacion` (~0,5 s) |
| `ya no necesito la calculadora, quítamela` | Con el LLM: `cerrar_aplicacion`, pero **pide confirmación** antes (cerrar algo por un malentendido molesta) |
| `minimiza discord`                       | La rechaza: no hay skill para minimizar (no la confunde con otra)   |
| `qué tiempo hace hoy`                    | Lo rechaza: no sabe hacerlo                                        |

Mientras una orden espera (por ejemplo, a que se abra una app) verás avisos
que empiezan por `…`. `Ctrl+C` cancela la orden en curso sin cerrar el
programa. Escribe `salir` para terminar.

## 5. Usar el agente a través de la API (así funcionará el móvil)

En una terminal, arranca el servidor y déjalo abierto:

```powershell
python -m api
```

La primera vez genera un token en `data/api_token.txt`. En **otra** terminal:

```powershell
python .\cliente.py
```

Funciona igual que el dispatcher, pero pasando por HTTP. También puedes
probar la API en el navegador: abre <http://127.0.0.1:8765/docs>, pulsa
**Authorize**, pega el contenido de `data/api_token.txt` y prueba
`POST /ordenes` con `{"texto": "apunta que probar la API"}`.

Para pararlo, `Ctrl+C` en la terminal del servidor.

## 6. Dónde mirar los resultados

| Archivo                     | Qué contiene                                                     |
| --------------------------- | ---------------------------------------------------------------- |
| `data/notas/`               | Notas creadas                                                    |
| `data/episodios.jsonl`      | Una línea por orden: texto, skill, quién la interpretó (`origen`: clasificador o llm), plan, pasos, si funcionó |
| `data/llm_servidor.log`     | Salida del servidor del LLM (para diagnosticar si no arranca)    |
| `data/api_token.txt`        | Token de la API (bórralo para generar uno nuevo)                 |

`data/` no se sube a git. Puedes borrarla entera para empezar de cero.

## 7. Configuración útil (`config.py`)

- `UMBRAL_CONFIANZA`: por debajo, el agente no actúa y dice que no está seguro.
- `ALIAS_APLICACIONES`: nombres alternativos (`"navegador": "Google Chrome"`).
- `ESPERA_MAX_APERTURA`: segundos que espera a que aparezca la ventana de una app (30 por defecto).
- `LLM_ACTIVO`: `False` para no usar el LLM. `RUTA_MODELO_LLM` para usar otro modelo GGUF;
  `LLM_CAPAS_GPU = 0` para usarlo sin GPU (mucho más lento).
- `API_HOST` / `API_PUERTO`: `127.0.0.1` solo deja conectarse desde este PC;
  `0.0.0.0` permite conectarse desde otros dispositivos de tu red (el móvil).

# Asistente Local — Documentación

## Estructura del proyecto

```
asistente/
├── config.py               # Configuración global (umbral, rutas, alias de apps)
├── dispatcher.py           # Cliente de consola: lee órdenes y llama a core.agente
├── cliente.py              # Cliente de consola que pasa por la API HTTP
├── api/                    # API HTTP local (python -m api): servidor.py, token.py
├── add_phrases.py          # Utilidad para añadir frases al dataset (ver sección más abajo)
├── requirements.txt        # Dependencias
├── README.md               # Esta documentación
├── ARQUITECTURA.md         # Diseño y hoja de ruta
├── core/                   # Núcleo del agente
│   ├── agente.py           # Fachada: frase → Resultado (lo que usan los clientes)
│   ├── router.py           # Frase → skill + parámetros (clasificador; si duda, LLM)
│   ├── llm.py              # LLM local: llama-server, prompt, salida restringida y validada
│   ├── llm_ejemplos.json   # Ejemplos que ve el LLM en cada consulta (editable)
│   ├── planner.py          # Pasos previos necesarios según precondiciones/efectos
│   ├── executor.py         # Confirmar → ejecutar → verificar → replanificar → registrar
│   ├── estado.py           # Ventanas, monitores y hechos del mundo (antes window_manager.py)
│   ├── memoria.py          # Episodios (data/episodios.jsonl)
│   ├── registro.py         # Catálogo de skills
│   └── skills/             # base.py, crear_nota, abrir/cerrar_aplicacion, restaurar_ventana, plantilla
├── tests/                  # python -m pytest tests
├── evaluacion/             # Frases de evaluación + python -m evaluacion.evaluar
├── models/                 # llama.cpp + modelo GGUF (no se suben a git; ver models/README.md)
├── nlu/                    # Núcleo de comprensión del lenguaje (100% local, sin internet)
│   ├── dataset.py          # Funciones para gestionar el dataset (agregar_frase, cargar_dataset...)
│   ├── dataset.json        # Frases de entrenamiento por intención
│   ├── vocabulary.py       # Tokenizador, vocabulario y vectorización bag-of-words
│   ├── vocabulary.json     # Vocabulario generado al entrenar (no editar a mano)
│   ├── model.py            # Arquitectura del clasificador (capa lineal + softmax)
│   ├── modelo.pt           # Pesos del modelo entrenado (generado por training.py)
│   ├── training.py         # Bucle de entrenamiento
│   └── slots.py            # Extracción de slots (qué app, qué contenido de nota...)
└── recorder/               # Sistema de grabación por demostración
    ├── recorder.py         # Captura teclado + ratón mientras haces la acción tú mismo
    ├── storage.py          # Persistencia de grabaciones (recordings.json)
    ├── build_templates.py  # Generaliza grabaciones en plantillas reutilizables
    ├── generalizer.py      # Lógica de comparación y detección del slot variable
    ├── player.py           # Reproduce una plantilla sustituyendo el slot
    ├── recordings.json     # Grabaciones crudas acumuladas
    ├── templates.json      # Plantillas generalizadas (generado por build_templates.py)
    └── catalogo.json       # Qué plantillas se publican como skill (descripción, parámetro, precondiciones, efectos)
```

---

## Cómo funciona el sistema (resumen)

1. Escribes una orden (`"quiero jugar a Destiny 2"`) en la consola o la envías a la API. __Más adelante será con voz__
2. El **router** usa el clasificador de intención (PyTorch) para decidir la skill (`ejecutar_en_steam`) y extrae el parámetro (`juego = "Destiny 2"`). Si el clasificador duda (confianza baja, intención `"ninguna"`, palabras que no conoce...), pregunta al **LLM local** (Qwen3-8B), que solo puede responder una skill del catálogo con sus parámetros. Si tampoco hay skill, no hace nada.
3. El **planificador** mira el estado real de Windows y calcula qué hace falta antes (abrir Steam o restaurarlo).
4. El **executor** ejecuta cada paso, pide confirmación en los irreversibles, verifica que ha funcionado, replanifica una vez si algo falla y registra el episodio.

Los modelos (clasificador y LLM) solo interpretan el texto. El resto es código determinista (ver ARQUITECTURA.md para la evolución).

> **Para enseñar acciones nuevas y mejorar cómo entiende las órdenes, ver [GUIA.md](GUIA.md).**

---

## Roadmap — Sistema de grabación y generalización de acciones

## Añadir frases al dataset (`add_phrases.py`)

`add_phrases.py` tiene tres modos de uso. Las frases nuevas siempre se
insertan **justo después de las que ya existen para esa misma intención**
(no al final del archivo), y se detectan duplicados automáticamente.

### Modo 1 — Una sola frase (interactivo)

```powershell
python .\add_phrases.py
```

Te muestra las intenciones existentes numeradas, eliges una (o escribes
una nueva), y luego escribes la frase. Útil para añadir algo puntual
sin tener que editar ningún archivo.

### Modo 2 — Varias frases desde un JSON externo

```powershell
python .\add_phrases.py .\mis_frases.json
```

El archivo JSON debe tener el mismo formato que `dataset.json`:

```json
[
  {"frase": "abre notion", "intencion": "abrir_aplicacion"},
  {"frase": "nueva nota rapida", "intencion": "crear_nota"}
]
```

Útil cuando quieres preparar un lote de frases fuera y luego importarlas
de golpe. Las entradas incompletas (sin frase o sin intención) se
ignoran con un aviso, sin interrumpir el resto de la importación.

### Modo 3 — Lista hardcodeada (histórico)

Edita la lista `FRASES_NUEVAS` dentro de `add_phrases.py` y ejecuta:

```powershell
python .\add_phrases.py
```

Se activa automáticamente cuando `FRASES_NUEVAS` no está vacía.
Útil si quieres dejar constancia en el propio archivo de qué frases
añadiste y cuándo.

### Output de ejemplo

```
Añadiendo 2 frase(s)...

  [OK] 'abre notion' -> abrir_aplicacion
  [YA EXISTÍA] 'abre discord' -> abrir_aplicacion

1 frase(s) nueva(s) añadidas de 2 procesadas.

Totales por intención:
  abrir_aplicacion: 38 frases
  crear_nota: 40 frases
  ninguna: 35 frases

Recuerda reentrenar el modelo:
  python .\nlu\training.py
```

## Guía de operación: qué hacer después de cada cambio

### 1. Añadiste frases nuevas al dataset (`dataset.json`)

Siempre que uses `agregar_frase()` o edites `dataset.json` a mano:

```powershell
python .\nlu\training.py
```

Esto reconstruye el vocabulario (`vocabulary.json`) y entrena el modelo
desde cero con los datos actualizados, guardando el resultado en
`nlu/modelo.pt`. El dispatcher carga el modelo nuevo automáticamente
la próxima vez que lo inicies.

**Cuándo entrenar:** no hace falta hacerlo por cada frase suelta.
Hazlo cuando hayas acumulado un lote (ej. una intención nueva completa,
o 10-15 frases adicionales).

---

### 2. Modificaste `slots.py` (añadiste un disparador o un artículo)

No hace falta reentrenar el modelo. `slots.py` no usa IA, son reglas
de texto puras. Simplemente reinicia el dispatcher:

```powershell
python .\dispatcher.py
```

---

### 3. Grabaste una acción nueva (o repetiste una ya existente)

```powershell
# Paso 1: grabar (2+ veces con valores distintos)
python .\recorder\recorder.py

# Paso 2: construir la plantilla
python .\recorder\build_templates.py

# Paso 3: publicarla como skill (solo si es completamente nueva)
# Añade una entrada en recorder/catalogo.json con el mismo nombre:
#   "nombre_accion": {"descripcion": "...", "parametro": "...",
#                     "precondiciones": {...}, "efectos": {...}}

# Paso 4: probar
python .\dispatcher.py
```

Si la acción ya existía (solo añadiste más grabaciones para mejorarla),
los pasos 2 y 4 son suficientes — no hace falta tocar el catálogo.

---

### 4. Añadiste una intención nueva de principio a fin

Este es el flujo completo, de punta a punta:

```powershell
# 1. Añade ~30 frases de ejemplo al dataset
#    (edita dataset.json o usa agregar_frase() desde Python)

# 2. Reentrena el modelo
python .\nlu\training.py

# 3. Añade los disparadores de la nueva intención en nlu/slots.py
#    (los verbos y frases que hay que quitar para extraer el slot)

# 4. Graba la acción 2+ veces con valores distintos
python .\recorder\recorder.py

# 5. Construye la plantilla
python .\recorder\build_templates.py

# 6. Publícala en recorder/catalogo.json con el MISMO nombre que la intención
#    (o, si es una skill en Python, añádela a SKILLS_NATIVAS en core/registro.py)

# 7. Prueba
python .\dispatcher.py
```

---

### 5. Algo falla y no sabes dónde

Sigue este orden de diagnóstico:

**¿El modelo clasifica bien la intención?**
```powershell
python .\nlu\training.py
# Mira las predicciones de las frases de prueba al final del output
```

**¿El slot se extrae bien?**
```python
# Abre un terminal Python y prueba manualmente:
from nlu.slots import extraer_slot
print(extraer_slot("tu frase aquí", "nombre_intencion"))
```

**¿La plantilla existe y tiene la forma correcta?**
Abre `recorder/templates.json` y comprueba que:
- La intención está presente como clave.
- El evento `"escribir"` que debería variar dice `"{slot}"` (con llaves).
- Los demás eventos son los pasos fijos que grabaste.

**¿El slot llega sucio a la plantilla?**
Casi siempre significa que falta un disparador en `slots.py`.
Añade la forma verbal o frase que no se está limpiando y reinicia
el dispatcher (sin reentrenar).

**¿Las grabaciones no generalizan?**
Los errores más comunes de `build_templates.py`:
- _"Distinto número de pasos"_: fuiste más o menos consistente en
  la secuencia de teclas entre grabaciones. Borra las grabaciones
  problemáticas de `recordings.json` y graba de nuevo.
- _"Se detectaron 2 partes variables"_: cambiaste más de una cosa
  entre grabaciones (ej. en `nueva_nota` grabaste `"nota rapida"` y
  `"notas rapidas"` — ambas palabras cambiaron). Asegúrate de cambiar
  solo el slot entre grabaciones, no la secuencia entera.

---

### Referencia rápida

| Cambios realizados                  | Reentrenar modelo   | Rebuild plantillas  |      Reiniciar dispatcher       |
| ----------------------------------- | :----------------:  | :----------------:  | :---------------------------:   |
| Frases nuevas en dataset            |        ✅ Sí       |        ❌ No        |              ✅ Sí             |
| Disparador nuevo en `slots.py`      |        ❌ No       |        ❌ No        |              ✅ Sí             |
| Grabación nueva de acción existente |        ❌ No       |        ✅ Sí        |              ✅ Sí             |
| Intención nueva desde cero          |        ✅ Sí       |        ✅ Sí        | ✅ Sí + editar `catalogo.json` |
| Solo cambio en `config.py` (umbral) |        ❌ No       |        ❌ No        |              ✅ Sí             |


---

## Siguientes pasos pendientes (por orden de prioridad)

1. ~~**Verificador de éxito**~~: hecho. Cada skill implementa
   `verificar()` y el executor lo aplica siempre.
2. **Contexto de sesión**: encadenar órdenes consecutivas que dependen
   unas de otras (ej. `"abre whatsapp"` → `"busca Mama"` → `"llama"`).
   Requiere un diccionario de estado compartido con caducidad por tiempo
   y por cambio de dominio.
3. **Ampliar `DISPARADORES`** en `slots.py` a medida que encuentres
   frases reales que no se limpian bien.
4. Cuando el catálogo de acciones crezca a 5+, reentrena el modelo con
   nuevas frases de ejemplo para cada intención nueva.
5. **OCR para clics variables**: para acciones donde el punto de clic
   depende del contenido de la pantalla (ej. seleccionar un contacto
   en una lista), se necesita reconocimiento de texto en pantalla.
   Candidato: `pytesseract` o `easyocr`, ambos 100% locales.

---

## Notas de diseño importantes

- **Los modelos solo interpretan, no ejecutan**: el clasificador y el LLM
  deciden qué skill y con qué parámetros. Todo lo que ocurre después
  (planificar, reproducir teclas, verificar) es código determinista.
- **Añadir una acción nueva no requiere escribir código**: grabación +
  `build_templates.py` + una entrada en `recorder/catalogo.json`. El
  registro la convierte en skill, el planificador ya puede usarla y el
  LLM la ve en su catálogo. Las frases en el dataset hacen que el
  clasificador la reconozca sin pasar por el LLM (más rápido).
- **Slots vs. sub-intenciones**: si el código que se ejecuta es el mismo
  y solo cambia un valor (qué app, qué canción), es un slot. Si el
  código es distinto (abrir vs. cerrar), son intenciones separadas.
- **Sin servicios externos**: todo el sistema es 100% local (también el
  LLM, que es un archivo en `models/` servido en 127.0.0.1). El único
  componente que puede usar internet es la acción concreta que lo
  necesite (ej. buscar en YouTube), nunca el núcleo NLU.