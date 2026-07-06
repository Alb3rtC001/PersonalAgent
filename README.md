# PersonalAgent
* La idea principal es crear una IA local que no dependa de internet creando un modelo própio y se adecue a las acciones personalizadas para el usuario.
Actualmente 

# Step 1:
PC application

# Step 2:
Mobile application 

## Roadmap — Sistema de grabación y generalización de acciones

**Importante**: `recorded_action.py` importa `from acctions.base import AccionBase`
y `from grabador.reproductor import reproducir_plantilla`. Si tu carpeta de
grabador se llama `recorder` en vez de `grabador`, cambia esa línea de
import a `from recorder.reproductor import reproducir_plantilla`
(y renombra `reproductor.py` a `player.py` si quieres mantener todo en
inglés — solo tendrías que ajustar esa misma línea de import).

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