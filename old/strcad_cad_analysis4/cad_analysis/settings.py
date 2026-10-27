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
    "analysis_kind": "struct",   # struct 구조도면 / arch 건축도면
    "auto_review": True,         # 분석 후 2차 AI 검토 자동 실행
    "review_layers": True,
    "review_columns": True,
    "layer_memory_arch": {},
    "arch": {},                  # 건축도면 분석 옵션
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
