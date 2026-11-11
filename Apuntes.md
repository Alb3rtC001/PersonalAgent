## 1. Verificar que las grabaciones que ya tienes son correctas

Ya tienes 3 grabaciones de `abrir_aplicacion` en `recordings.json`. Ábrelo
y comprueba que **al menos 2 de ellas tienen valores DISTINTOS** en el
evento "escribir" (ej. una dice "discord" y otra "steam"). Si las 3
dicen lo mismo (ej. las 3 dicen "discord"), `generalizar()` no podrá
detectar qué parte es el slot — necesitas variedad, no repetición.

Si te faltan grabaciones con valores distintos, graba una más:
```powershell
cd recorder
python recorder.py
```
Cuando te pida el nombre de la acción, escribe exactamente `abrir_aplicacion`
(tiene que coincidir con el nombre de la intención). Abre otra app distinta
a las ya grabadas (ej. "notepad" o "calculadora"), pulsa F9 al terminar.

## 2. Construir las plantillas

```powershell
cd recorder
python build_templates.py
```
Deberías ver algo como:
```
'abrir_aplicacion': plantilla generada con 3 grabaciones.
Guardado en .../templates.json
```
Abre `templates.json` y comprueba que el evento "escribir" tiene el
valor `"{slot}"` (el hueco genérico), y que la tecla "win" y "enter"
aparecen como pasos fijos.

**Si te da un error de "no se pudo generalizar"**: lee el mensaje, te
dice exactamente cuál es el problema (número de pasos distinto entre
grabaciones, o más de una parte variable). Vuelve a grabar la acción
que falló, siendo más consistente en la secuencia de teclas.

## 3. Ejecutar el dispatcher con la nueva acción genérica

```powershell
python .\dispatcher.py
> abre discord
> abre steam
> abre notion
```
La última (`notion`) es la prueba importante: **nunca la grabaste**, así
que si funciona, confirma que la generalización realmente funciona para
valores nuevos, no solo para los que grabaste.

## 4. Qué hacer si algo falla

- **`ModuleNotFoundError: No module named 'pynput'`** al ejecutar
  `build_templates.py` o `dispatcher.py`: no debería pasar con estos
  archivos nuevos (ya lo desacoplé), pero si aparece, revisa que no
  hayas dejado un import antiguo a `grabar.py`/`recorder.py` en algún
  sitio que no sea `recorder.py` en sí mismo.
- **El slot sale con basura pegada** (como el caso de "la calculadora"):
  revisa `slots.py`, puede que falte un artículo o disparador nuevo en
  las listas `DISPARADORES` / `ARTICULOS_INICIALES`.
- **La plantilla no reproduce nada / no pasa nada visible**: comprueba
  que `pyautogui` está instalado (`python -m pip install pyautogui`) y
  que ninguna otra ventana tiene el foco de forma que intercepte las
  teclas antes de que se abra el menú Inicio.

## 5. Siguientes pasos, en orden de prioridad, cuando tengas tiempo

1. **Grabar `crear_nota` de la misma forma** (si quieres que también use
   plantillas en vez de código a mano). De momento sigue con
   `create_note.py` escrito por ti, funciona igual de bien.
2. **Verificador de éxito**: ahora mismo no comprobamos si la app
   realmente se abrió. Pendiente para más adelante (ligado a la idea
   del "verificador" que diseñamos para música).
3. **Contexto de sesión** para encadenar órdenes (tu ejemplo de
   WhatsApp: abrir → buscar contacto → llamar). Esto es un componente
   nuevo, no lo toques hasta tener `abrir_aplicacion` sólido primero.
4. **Ampliar `DISPARADORES`** en `slots.py` a medida que encuentres
   frases reales tuyas que no se limpian bien.
5. Cuando el catálogo de acciones crezca (5+), reentrena el modelo de
   intención (`python nlu/training.py`) con nuevas frases de ejemplo
   para cada intención nueva que añadas.

## 6. Regla general para añadir una acción nueva a partir de ahora

1. Añade ~30 frases de ejemplo de esa intención a `dataset.json`
   (usando `agregar_frase` o editándolo).
2. Reentrena: `python nlu/training.py`.
3. Graba la acción 2+ veces con `recorder.py`, con valores distintos.
4. Ejecuta `build_templates.py`.
5. Añade una línea en `dispatcher.py`:
   ```python
   ACCIONES["nombre_nueva_intencion"] = RecordedAction("nombre_nueva_intencion")
   ```
6. Prueba con el dispatcher, incluyendo un valor que NUNCA grabaste.

Con esto ya no hace falta escribir una clase Python nueva por cada
acción basada en teclado — solo dataset + grabación.

--------------------------------------------------------------------------------------------------------

Qué hace el asistente ahora mismo
El flujo completo de una orden
Tú escribes: "abre discord"
       ↓
Clasificador (PyTorch) → intención: abrir_aplicacion (confianza: 0.98)
       ↓
slots.py → slot: "discord"
       ↓
Dispatcher → busca RecordedAction("abrir_aplicacion")
       ↓
player.py → carga plantilla → win → "discord" → enter
       ↓
Windows abre Discord
Las tres capas del sistema
Capa 1 — Núcleo NLU (nlu/)
El cerebro del sistema, 100% local y sin internet. Un clasificador de intención entrenado desde cero en PyTorch con un vocabulario bag-of-words. Recibe texto, devuelve una intención y una confianza. Actualmente conoce 3 intenciones:

abrir_aplicacion — cualquier orden de abrir una app
crear_nota — cualquier orden de anotar algo
ninguna — frases fuera de dominio, para rechazarlas activamente

El clasificador tiene dos redes de seguridad antes de ejecutar nada: la clase ninguna (el modelo activamente reconoce cuando no entiende algo) y un umbral de confianza (si la predicción es muy insegura, no ejecuta nada aunque la intención no sea ninguna).
Capa 2 — Extracción de slots (nlu/slots.py)
Una vez clasificada la intención, limpia la frase para extraer solo el dato útil. Funciona con reglas de texto explícitas (no IA): quita los verbos disparadores y los artículos, dejando solo el valor real. Por ejemplo: "quiero abrir la calculadora" → slot: "calculadora".
Capa 3 — Sistema de grabación y reproducción (recorder/)
En vez de programar cada acción a mano en Python, tú la demuestras dos veces con teclado y ratón. El sistema compara ambas grabaciones, detecta automáticamente qué parte varía (el slot), y genera una plantilla reutilizable. La próxima vez que pidas esa acción con un valor nuevo (ej. "abre Steam" en vez de "abre Discord"), reproduce la misma secuencia sustituyendo solo el hueco.

Qué tienes funcionando a día de hoy

Clasificación de intención con 3 clases, con rechazo activo de frases fuera de dominio.
Extracción de slots para abrir_aplicacion y crear_nota.
Grabación de acciones con teclado (teclas especiales + texto) y ratón (clics con coordenadas).
Generalización automática de 2+ grabaciones en una plantilla con hueco {slot}.
Reproducción de plantillas sustituyendo el slot en tiempo real.
abrir_aplicacion completamente funcional de punta a punta via plantilla grabada.
crear_nota clasificada correctamente pero con acción placeholder todavía (no crea nada real).
Detección de duplicados al añadir frases al dataset.
Inserción ordenada de frases nuevas (justo después de las de la misma intención).
Herramienta add_phrases.py con 3 modos: una frase interactiva, JSON externo, o lista hardcodeada.
README.md con guía de operación completa.


Qué está pendiente (por orden de prioridad)
Inmediato

Arreglar la captura de imagen en Windows (el recorte de pantalla al hacer clic llega vacío, "imagen": ""). Necesario para que player.py pueda buscar visualmente los elementos en pantalla en vez de depender solo de coordenadas fijas.
Conectar crear_nota con una acción real (crear un archivo .txt con el contenido del slot).

Siguiente bloque

Contexto de sesión: encadenar órdenes consecutivas que se necesitan entre sí (ej. "abre Steam" → "busca Destiny 2" → "lanza"). Requiere un diccionario de estado compartido con caducidad por tiempo y por cambio de dominio.
Verificador de éxito: detectar si la acción realmente funcionó (ej. comprobar si apareció una ventana nueva tras abrir una app).

Más adelante

Ampliar el catálogo de intenciones (reproducir música, poner alarma, buscar contacto, llamar...).
OCR para clics variables según el contenido de la pantalla (ej. seleccionar un contacto en una lista de WhatsApp). Candidatos: pytesseract o easyocr, ambos 100% locales.
Transformer en vez del clasificador lineal actual, cuando el dataset sea suficientemente grande.


Lo que el sistema NO hace todavía

No verifica si la acción tuvo éxito.
No encadena órdenes que dependen de una anterior.
No crea notas reales (solo placeholder).
No captura bien las imágenes de los clics en Windows.
No generaliza clics en posiciones variables según el contenido de la pantalla.
No tiene interfaz gráfica ni entrada por voz (solo texto escrito).

------------------------------------------------------------------------------------------ // -------------------------------------------------------------------------------------

Lo que habría que añadir concretamente

Capa 1 — Entender el objetivo en lenguaje libre
En vez de clasificar en categorías fijas (abrir_aplicacion, ejecutar_en_steam...), un modelo que extraiga el objetivo en forma estructurada desde cualquier frase. Por ejemplo "pon música de rock mientras termino el trabajo" → {objetivo: "reproducir_musica", parametros: {genero: "rock"}, contexto: "fondo"}. Esto requiere un modelo generativo pequeño (no clasificador), o un LLM local ligero como Phi-3 Mini o Mistral 7B cuantizado — ambos corren en local en una máquina moderna.

Capa 2 — Razonador que compone plantillas
STRIPS ya hace esto para secuencias predefinidas. La versión abierta sería un razonador que, dado el objetivo extraído, busca en el catálogo de plantillas grabadas cuáles combinadas podrían conseguirlo, aunque nunca hayas visto esa combinación antes. Esto es lo que en investigación se llama "task and motion planning" o en versiones más modernas "LLM + tool use".

Capa 3 — Aprendizaje de nuevas plantillas sin programar
El grabador que ya tienes es exactamente esto — demuestras una vez y el sistema aprende la acción. La pieza que falta es que el razonador descubra solo qué plantillas necesita para un objetivo nuevo, en vez de que tú se lo digas.