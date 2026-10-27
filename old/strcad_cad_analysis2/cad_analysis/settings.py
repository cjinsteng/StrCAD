"""Persisted user settings (~/.strcad/cad_analysis.json)."""
import json
import os

PATH = os.path.join(os.path.expanduser("~"), ".strcad", "cad_analysis.json")
DEFAULTS = {
    "ollama_host": "http://localhost:11434",
    "ollama_model": "",
    "use_ollama": True,
    "infer_names": True,
    "layer_memory": {},      # layer name -> role confirmed by the user
    "last_dir": "",
    "wall_girder": True,
    "osnap": {},
}


def load() -> dict:
    d = dict(DEFAULTS)
    try:
        with open(PATH, encoding="utf-8") as f:
            d.update(json.load(f))
    except (OSError, ValueError):
        pass
    return d


def save(d: dict):
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
