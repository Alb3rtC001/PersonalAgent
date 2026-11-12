# models/

Runtime y pesos del LLM local de la fase 3 (ver `ARQUITECTURA.md` §10).
Todo lo que hay aquí **no se sube a git** (solo este README): son binarios
y archivos de varios GB. Funciona sin internet una vez descargado.

| Carpeta                | Qué es                                               | Licencia      | Origen |
| ---------------------- | ---------------------------------------------------- | ------------- | ------ |
| `llama.cpp/`           | `llama-server.exe` y librerías, build b12318, CUDA 13.5 (x64) | MIT (`llama.cpp/LICENSE`) | Releases oficiales de `ggml-org/llama.cpp` |
| `qwen3-8b/`            | `Qwen3-8B-Q4_K_M.gguf` (4,68 GB) — **el que usa el agente** | Apache 2.0 (`qwen3-8b/LICENSE`) | Repositorio oficial `Qwen/Qwen3-8B-GGUF` |
| `olmo-3-7b-instruct/`  | `Olmo-3-7B-Instruct-Q4_K_M.gguf` (4,26 GB) — alternativa | Apache 2.0 (`MODEL_CARD.md`) | Modelo de Ai2 (`allenai/Olmo-3-7B-Instruct`), cuantizado por `lmstudio-community` |

El modelo que se usa se elige en `config.py` (`RUTA_MODELO_LLM`). OLMo 3 se
puede borrar si no lo vas a usar (libera 4,3 GB); se queda como alternativa
porque es el único que publica sus datos de entrenamiento.

## Reproducir la descarga en otro PC

Desde la raíz del proyecto, en PowerShell:

```powershell
# llama.cpp (requiere driver NVIDIA compatible con CUDA 13; si no, usar los zips cuda-12.4)
$b = "https://github.com/ggml-org/llama.cpp/releases/download/b12318"
curl.exe -L -o llama.zip  "$b/llama-b12318-bin-win-cuda-13.5-x64.zip"
curl.exe -L -o cudart.zip "$b/cudart-llama-bin-win-cuda-13.5-x64.zip"
Expand-Archive llama.zip  models\llama.cpp -Force
Expand-Archive cudart.zip models\llama.cpp -Force

# Modelo (Qwen3-8B)
New-Item -ItemType Directory -Force models\qwen3-8b
curl.exe -L -o models\qwen3-8b\Qwen3-8B-Q4_K_M.gguf `
  "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/7c41481f57cb95916b40956ab2f0b139b296d974/Qwen3-8B-Q4_K_M.gguf"

# Opcional: OLMo 3 7B
curl.exe -L -o models\olmo-3-7b-instruct\Olmo-3-7B-Instruct-Q4_K_M.gguf `
  "https://huggingface.co/lmstudio-community/Olmo-3-7B-Instruct-GGUF/resolve/893e8b40befaf8a27cadd1349c0a9cbbe529cffd/Olmo-3-7B-Instruct-Q4_K_M.gguf"
```

SHA-256 esperados (comprobar con `Get-FileHash <archivo>`):

| Archivo                                   | SHA-256 |
| ----------------------------------------- | ------- |
| `llama-b12318-bin-win-cuda-13.5-x64.zip`  | `903bc987753e202b3d0ec133814bc9f4e596e8a1aa44402e76678c1880dc1e8f` |
| `cudart-llama-bin-win-cuda-13.5-x64.zip`  | `c2bf4cc202bfbaaa7a0b75f5082457c3811326947bb216059b72839d844e9cba` |
| `Qwen3-8B-Q4_K_M.gguf`                    | `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |
| `Olmo-3-7B-Instruct-Q4_K_M.gguf`          | `a87e10578f328b087f888ac7bd1018555e26028a1130980f20312b4de3a10d70` |

## Probar a mano

El agente arranca y para el servidor él solo; esto es solo para hacer pruebas:

```powershell
.\models\llama.cpp\llama-server.exe -m .\models\qwen3-8b\Qwen3-8B-Q4_K_M.gguf --host 127.0.0.1 --port 8766 -ngl 99 -c 4096 --no-webui --chat-template chatml
```

- `-ngl 99` carga todo el modelo en la GPU (unos 5,4 GB de VRAM con Qwen3,
  6,3 GB con OLMo 3, en la RTX 3060 Ti).
- `--host 127.0.0.1` hace que solo sea accesible desde este PC.
- `--chat-template chatml`: los dos modelos usan el formato ChatML
  (`<|im_start|>…<|im_end|>`). Con OLMo 3 es **obligatorio**: la plantilla
  que trae su GGUF (y la oficial, guardada en
  `olmo-3-7b-instruct/chat_template.jinja`) falla con esta build cuando no
  se le pasan herramientas, y el servidor no arranca.
