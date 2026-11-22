"""Run by the beat_this tool venv's python (never imported by the studio): one audio file in,
`{"beats": [...], "downbeats": [...]}` (seconds) out as the last stdout line. CPU only, model
`final0` (~78 MB, fetched once into the torch hub cache). src/studio/music.py calls it."""
import json
import sys

from beat_this.inference import File2Beats

beats, downbeats = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(sys.argv[1])
print(json.dumps({"beats": [round(float(t), 3) for t in beats],
                  "downbeats": [round(float(t), 3) for t in downbeats]}))
