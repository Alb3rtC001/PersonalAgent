# PersonalAgent
* La idea principal es crear una IA local que no dependa de internet creando un modelo própio y se adecue a las acciones personalizadas para el usuario.
Actualmente 

# Step 1:
PC application

# Step 2:
Mobile application 

## Roadmap — Sistema de grabación y generalización de acciones

# Asistente Local — Documentación

## Estructura del proyecto

```
asistente/
├── config.py               # Configuración global (umbral de confianza, flag de confirmación)
├── dispatcher.py           # Punto de entrada principal: texto → intención → acción
├── add_phrases.py          # Utilidad para añadir frases al dataset (ver sección más abajo)
├── README.md               # Esta documentación
├── nlu/                    # Núcleo de comprensión del lenguaje (100% local, sin internet)
│   ├── dataset.py          # Funciones para gestionar el dataset (agregar_frase, cargar_dataset...)
│   ├── dataset.json        # Frases de entrenamiento por intención
│   ├── vocabulary.py       # Tokenizador, vocabulario y vectorización bag-of-words
│   ├── vocabulary.json     # Vocabulario generado al entrenar (no editar a mano)
│   ├── model.py            # Arquitectura del clasificador (capa lineal + softmax)
│   ├── modelo.pt           # Pesos del modelo entrenado (generado por training.py)
│   ├── training.py         # Bucle de entrenamiento
│   └── slots.py            # Extracción de slots (qué app, qué contenido de nota...)
├── acctions/               # Capa de acciones (una clase por tipo de acción)
│   ├── __init__.py
│   ├── base.py             # Interfaz común AccionBase
│   ├── recorded_actions.py # Acción genérica que ejecuta plantillas grabadas
│   ├── open_application.py # Acción de abrir apps (ahora sustituida por recorded_actions)
│   └── create_note.py      # Acción de crear notas
└── recorder/               # Sistema de grabación por demostración
    ├── recorder.py         # Captura teclado + ratón mientras haces la acción tú mismo
    ├── storage.py          # Persistencia de grabaciones (recordings.json)
    ├── build_templates.py  # Generaliza grabaciones en plantillas reutilizables
    ├── generalizer.py      # Lógica de comparación y detección del slot variable
    ├── player.py           # Reproduce una plantilla sustituyendo el slot
    ├── recordings.json     # Grabaciones crudas acumuladas
    └── templates.json      # Plantillas generalizadas (generado por build_templates.py)
```

---

## Cómo funciona el sistema (resumen)

1. Escribes una orden en texto (`"abre aplicacionX"`).
2. El **clasificador de intención** (modelo PyTorch) decide qué categoría es (`abrir_aplicacion`) y con qué confianza.
3. Si la confianza es suficiente (confianza > 0,750) y la intención no es `"ninguna"`, el **dispatcher** extrae el slot (`"aplicacionX"`) y llama a la acción correspondiente.
4. La **acción** carga la plantilla grabada por demostración y la reproduce sustituyendo el hueco `{slot}` por el valor real.

El modelo solo clasifica texto. Todo lo demás es código determinista.

---

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

# Paso 3: añadir al dispatcher (solo si la intención es completamente nueva)
# En dispatcher.py, añade dentro de ACCIONES:
# "nombre_nueva_intencion": RecordedAction("nombre_nueva_intencion"),

# Paso 4: probar
python .\dispatcher.py
```

Si la acción ya existía (solo añadiste más grabaciones para mejorarla),
los pasos 2 y 4 son suficientes — no hace falta tocar el dispatcher.

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

# 6. Registra la acción en dispatcher.py
#    ACCIONES["nombre_nueva_intencion"] = RecordedAction("nombre_nueva_intencion")

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
| Intención nueva desde cero          |        ✅ Sí       |        ✅ Sí        | ✅ Sí + editar `dispatcher.py` |
| Solo cambio en `config.py` (umbral) |        ❌ No       |        ❌ No        |              ✅ Sí             |


---

## Siguientes pasos pendientes (por orden de prioridad)

1. **Verificador de éxito**: comprobar si la app realmente se abrió
   tras ejecutar la plantilla (usando `pygetwindow` para detectar si
   apareció una ventana nueva). Ligado al "verificador" diseñado
   también para música.
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

- **El modelo solo clasifica, no ejecuta**: el modelo de PyTorch solo
  decide a qué categoría pertenece la frase. Todo lo que ocurre después
  (extraer slot, cargar plantilla, reproducir teclas) es código
  determinista, sin IA.
- **Añadir una acción nueva no requiere escribir código**: solo dataset
  + grabación + `build_templates.py`. El dispatcher la recoge
  automáticamente via `RecordedAction`.
- **Slots vs. sub-intenciones**: si el código que se ejecuta es el mismo
  y solo cambia un valor (qué app, qué canción), es un slot. Si el
  código es distinto (abrir vs. cerrar), son intenciones separadas.
- **Sin modelos externos**: todo el sistema es 100% local. El único
  componente que puede usar internet es la acción concreta que lo
  necesite (ej. buscar en YouTube), nunca el núcleo NLU.