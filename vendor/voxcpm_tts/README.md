# VoxCPM2 voice service

The studio's voice-over (step 038, docs/DECISIONS.md 2026-11-19): [VoxCPM2](https://huggingface.co/openbmb/VoxCPM2)
(OpenBMB, Apache-2.0) running on the local NVIDIA GPU, with the owner's approved settings and
voices. The studio calls it through its generic `http` TTS provider (`src/studio/tts.py`).

- `POST /tts` `{"text": "<one script line per line>", "voice": "<id>"}` →
  `{"audio": <base64 wav, 48 kHz>, "words": [{"text", "start_s", "end_s"}], "take": {...}}`.
  `words` holds one span per script line, its text as written, so captions match the voice.
  Empty voice = the default voice; an unknown voice = HTTP 400 listing the ids.
- `GET /health` → model, `loaded` (true/false), voices, default voice, settings. Answers at
  once, loaded or not.

## What it does per request

1. French speech normalisation of what is said (`speech.py speak()`; captions keep the
   script): `308 kcal` → « trois cent huit calories » (kcal is said "calories", as people
   say it), `21 h` → « vingt et une heures », `21h30`, `1 800`, `1,5 kg`, `20 %`, `1er`,
   `macrobody.fr` → « Macro Body point f r », `MacroBody` → « Macro Body ».
2. The whole script in **one take** (a line break is a sentence break), cloned from the voice
   card as continuation (card wav + its text) and as reference, `cfg 1.6`, `30 steps`. Never
   split below whole lines: short takes garble short words ("Trop" → "Prop").
3. Whisper large-v3-turbo (faster-whisper, int8 on the CPU) transcribes the take; its words are compared to the
   text (difflib ratio on normalised words). Under `VOXCPM_MIN_SCORE` the take is redone, up
   to `VOXCPM_MAX_TAKES`; the best take wins. Takes and scores go to the log.
4. Peak limited to 0.99 (never clips); loudness is the studio's loudnorm.

One request at a time; others wait.

## Sharing the GPU (step 145)

The models load on the first request (~35 s) and are dropped after `VOXCPM_IDLE_UNLOAD_S`
without a request. While they are loaded the service
holds the machine's GPU lock (`src/studio/gpu_lock.py`, file `GPU_LOCK_PATH`, default
`~/.ig-campaign/gpu.lock`), the one Blender and Remotion renders take: a render waits until
the voice is unloaded, and a voice-over waits for a running render. Waiters log who holds it.

## Giving the RAM back (step 146)

The models run in a worker process (`engine_worker.py`, started with `spawn` on the first
request); the HTTP service itself imports no torch and stays around 60 MB. Unloading
**terminates** the worker, so the OS takes back every byte. In one process, dropping the
models gave the VRAM back but torch's CPU allocator kept ~17 GB of committed RAM.

- A worker that dies, or whose load or take fails: HTTP 503, the GPU lock released, and the
  next request starts a new worker. If the service dies (even killed), the worker exits
  at once, mid-take or mid-load: the OS has already released the service's GPU lock.
- The worker sets `MIMALLOC_PURGE_DELAY=0` (torch's CPU allocator on Windows gives freed
  pages back at once) and checks takes with faster-whisper int8 instead of the transformers
  fp32 pipeline (same words and score on the same take, half the time; its word timestamps
  took ~7 GB more at peak).
- On Windows the GPU memory a process allocates also counts in its committed memory (WDDM
  can page it out): ~6 GB of the worker's committed memory is the model on the GPU.

Committed memory (private bytes), one 7.7 s take, RTX 3070 Laptop:

| | service | worker loaded | worker peak (take) | after unload |
|---|---|---|---|---|
| before (one process) | 19.6 GB | (same process) | ~23 GB | 19.6 GB |
| step 146 | 41 MB | WORKER_LOADED | WORKER_PEAK | 41 MB, no worker |

## Voices

`brand/voices/<id>.wav` (the card: the clip that defines the voice) + `brand/voices/voices.json`
(id, label, description, `card_text`, `styles`, `address`, one `default: true`). Approved by the
owner on 2026-11-19: `conteur_grave` (default), `coach_energique`, `douce_nuit`.

## Setup (Windows, NVIDIA GPU with 8 GB)

```powershell
uv venv D:\voice\vox --python 3.12
uv pip install --python D:\voice\vox\Scripts\python.exe torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python D:\voice\vox\Scripts\python.exe -r vendor\voxcpm_tts\requirements.txt
```

The models (~6 GB: VoxCPM2 + Whisper for faster-whisper) download on the first load into `HF_HOME`: put it on a
disk with room (`TTS_SERVER_HF_HOME`). Then in the studio's `.env`:

```
TTS_PROVIDER=http
TTS_HTTP_URL=http://127.0.0.1:8766/tts
TTS_HTTP_RESPONSE=json
TTS_VOICE=conteur_grave
TTS_SERVER_PYTHON=D:\voice\vox\Scripts\python.exe
TTS_SERVER_HF_HOME=D:\voice\hf
```

`ig-campaign up` then starts the service on that port (loopback), waits until it answers
before the worker starts, and stops it on exit; it also exits by itself when the studio dies (it watches the studio's pid).
Its output goes to `data/logs/tts.log`. To run it by hand instead:
`python vendor/voxcpm_tts/server.py --port 8766` (with `HF_HOME` set).

## Settings (environment of the service)

| Variable | Default | |
|---|---|---|
| `VOXCPM_STEPS` | 30 | diffusion steps (approved; never lower by default) |
| `VOXCPM_CFG` | 1.6 | guidance (approved) |
| `VOXCPM_MAX_TAKES` | 3 | takes per request at most |
| `VOXCPM_MIN_SCORE` | 0.9 | a take at or above this is kept at once |
| `VOXCPM_IDLE_UNLOAD_S` | 120 | idle seconds before the worker is stopped and the GPU freed |
| `VOXCPM_WHISPER` | `mobiuslabsgmbh/faster-whisper-large-v3-turbo` | the take checker: a hub id or a local CTranslate2 folder (`ct2-transformers-converter --model openai/whisper-large-v3-turbo --output_dir <dir> --quantization int8 --copy_files tokenizer.json preprocessor_config.json` converts the transformers model you already have) |
| `GPU_LOCK_PATH` | `~/.ig-campaign/gpu.lock` | the machine's GPU lock (`ig-campaign up` passes its own) |

## Cost (RTX 3070 Laptop 8 GB, i7-11800H)

About 3.7 s of GPU per second of audio per take, plus ~1.3 s of CPU Whisper per second;
VRAM peak about 6.5 GB (Whisper is on the CPU so the total stays under 8 GB).
