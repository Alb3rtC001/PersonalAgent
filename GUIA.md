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
                 ~0,4 s, solo puede elegir skills    antes...)  registrar     + plantillas grabadas
                 del catálogo                                       │          (ejecutar_en_steam)
                                                                    ▼
                                                     data/episodios.jsonl  ◄── de aquí se aprende
```

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

El LLM (Qwen3) **no se reentrena** de momento: se le "enseña" con el
catálogo y los ejemplos. Ajustar sus pesos con tus episodios (LoRA) es la
fase 6, cuando haya cientos de órdenes reales registradas (sección 7).

---

## 2. Uso diario

```powershell
.\.venv\Scripts\Activate.ps1      # si usas el entorno virtual
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
  clasificador no preguntan.
- `Ctrl+C` cancela la orden en curso.

---

## 3. Cuando una frase no se entiende o se entiende mal

1. **Mira qué pasó** en el último episodio:

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

- Unas **20–30 frases por intención**, variadas (verbos distintos, con y
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

Más adelante (fase 6), **ajuste fino con LoRA**: con unos cientos de
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

- **Varias acciones en una orden** ("abre Steam y lanza Hades"): cada
  orden es una skill (el planificador sí añade los pasos previos).
- **Contexto entre órdenes** ("abre WhatsApp" → "escríbele a mamá"): fase 4.
- **Plantillas frágiles:** las grabaciones repiten clics por coordenadas;
  si la ventana cambia de sitio o de tamaño pueden fallar (fase 5: UI Automation).
- **Aprendizaje automático:** el paso de episodios al dataset es manual
  (sección 6); automatizarlo y el LoRA son la fase 6.
- **Clasificador pequeño:** el bag-of-words se sustituirá por un
  transformer pequeño propio que también extraiga los parámetros.
