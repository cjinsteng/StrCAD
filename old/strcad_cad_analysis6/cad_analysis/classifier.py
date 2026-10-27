"""Semantic classification: which layer holds what, and what a label means.

Ollama is used here (meaning), never for coordinates or dimensions.
Every Ollama answer is validated; anything missing/invalid falls back to rules.
"""
from __future__ import annotations

import json
import re

from .model import LAYER_ROLES
from .ollama_client import OllamaClient, OllamaError

# ---------------------------------------------------------------------------
#  Label parsing (rules)
# ---------------------------------------------------------------------------
SIZE_RE = re.compile(r"(\d{2,4})\s*[xX×*]\s*(\d{2,4})")
NAME_RE = re.compile(r"^(?P<name>(?:[A-Za-z]{0,2}\d{0,2})?(?P<letters>[A-Za-z]{1,4})(?P<num>\d{1,3})[A-Za-z]?(?:[-_]\d{1,2})?)$")
LETTER_KIND = {"C": "column", "G": "girder", "B": "beam", "W": "wall", "S": "slab", "F": "footing",
               "L": "beam", "D": "slab"}
LABEL_TYPES = ("column", "girder", "beam", "wall", "slab", "footing", "other")


def parse_label(text: str):
    """'G1' → {'name':'G1','type':'girder','width':None,'depth':None}
       'TG2(500X800)' → name TG2, type girder, width 500, depth 800
       Returns None if the text doesn't look like a member mark."""
    t = text.strip()
    size = SIZE_RE.search(t)
    w = d = None
    if size:
        w, d = int(size.group(1)), int(size.group(2))
        t = (t[:size.start()] + t[size.end():])
    t = re.sub(r"[\(\)\[\]\s,]", "", t)
    if not t or len(t) > 12:
        return None
    m = NAME_RE.match(t)
    if not m:
        return None
    letters = m.group("letters").upper()
    kind = LETTER_KIND.get(letters[-1], "other")
    return {"name": m.group("name").upper() if letters.isupper() else m.group("name"),
            "type": kind, "width": w, "depth": d}


# ---------------------------------------------------------------------------
#  Layer roles (rules)
# ---------------------------------------------------------------------------
IGNORE_KEYS = ("출력금지", "비내력", "하부", "상부", "DIM", "치수", "HATCH", "해치", "PARK", "주차", "FURN",
               "DEFPOINT", "ASHADE", "TITLE", "FORM", "도곽", "LEVEL", "OPEN", "개구", "SLAB", "슬래브", "FOOT",
               "기초", "STAIR", "계단", "ELEV", "SYMBOL", "ARCH", "건축", "LANDSCAPE", "조경")
GRID_KEYS = ("CEN", "GRID", "AXIS", "통심", "중심선", "그리드", "X-LINE")
KIND_KEYS = (("girder", ("GIRDER", "GIRD", "거더", "큰보")),
             ("column", ("COLUMN", "COL", "기둥")),
             ("wall", ("WALL", "벽")),
             ("beam", ("BEAM", "작은보", "보")))
NAME_RE_LAYER = re.compile(r"([-_ ](N|NM|NAME|NO|TXT|TEXT|TAG|MARK|MK)$)|NAME|부재명|명칭")


def rule_layer_role(summary: dict) -> str:
    name = summary["name"]
    u = name.upper()
    ents = summary.get("entities", {})
    n_text = sum(v for k, v in ents.items() if k in ("TEXT", "MTEXT", "ATTRIB"))
    n_geo = sum(v for k, v in ents.items() if k in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"))
    if any(k in u for k in IGNORE_KEYS):
        return "ignore"
    if any(k in u for k in GRID_KEYS):
        return "grid"
    kind = next((k for k, keys in KIND_KEYS if any(x in u for x in keys)), None)
    is_name = bool(NAME_RE_LAYER.search(u)) or (n_text > 0 and n_text >= n_geo)
    if kind:
        if is_name and n_text > 0:
            return f"{kind}_name"
        if n_geo > 0:
            return kind
    # text-dominant layer whose texts look like member marks
    samples = summary.get("sample_texts", [])
    if n_text and n_text >= n_geo and samples:
        parsed = [parse_label(s) for s in samples]
        good = [p for p in parsed if p and p["type"] in ("column", "girder", "beam", "wall")]
        if len(good) >= max(1, len(samples) // 3):
            return "member_text"
    return "ignore"


# ---------------------------------------------------------------------------
#  Ollama prompts
# ---------------------------------------------------------------------------
LAYER_SYSTEM = """You classify CAD layers of a Korean structural framing plan (구조평면도) drawn in AutoCAD.
For each layer decide its role. Allowed roles:
- column: outlines of columns (기둥) - small closed rectangles/circles
- girder: edge lines of girders (큰보, 거더, G1/TG1 ...) - long parallel line pairs
- beam: edge lines of beams (작은보, 보, B1 ...) - long parallel line pairs
- wall: edge lines of structural (bearing/shear) walls (내력벽, 전단벽, 옹벽)
- column_name, girder_name, beam_name, wall_name: text layers holding member marks of that type (e.g. layer "COL-N" with texts C1, C2)
- member_text: text layer that mixes member marks of several types (C1, G1, B1 together)
- grid: grid / centre lines (통심선, X1, Y1 axes)
- ignore: anything else - dimensions, hatch, slab marks, title block, architecture, parking, furniture,
  NON-bearing walls (비내력벽, 조적, 경량), layers marked 출력금지, lower/upper floor framing (하부골조, 상부)
Use the layer name, entity counts, median line length and sample texts. Korean abbreviations: C=기둥, G=큰보, B=작은보, W=벽, S=슬래브.
Return JSON: {"layers":[{"name":"<exact layer name>","role":"<role>"}]} covering every layer given."""

LABEL_SYSTEM = """You interpret member marks written on a Korean structural framing plan.
For each text decide what it labels and extract the mark name and section size if written.
type must be one of: column, girder, beam, wall, slab, footing, other.
Conventions: C/SC/TC=column(기둥), G/TG/WG/CG/FG=girder(큰보), B/TB/CB/WB/LB=beam(작은보),
W/RW/SW/BW=wall(벽체), S/RS/FS=slab(슬래브), F/MF=footing. A floor prefix may precede the mark (2G1, B1G1 → girder).
Size like 400X700 means width 400, depth 700 (mm); null when absent. Text that is not a member mark → type "other".
Return JSON: {"labels":[{"text":"<exact text>","type":"...","name":"<mark without size>","width":null,"depth":null}]}"""

LAYER_SCHEMA = {"type": "object", "properties": {"layers": {"type": "array", "items": {
    "type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string", "enum": list(LAYER_ROLES)}},
    "required": ["name", "role"]}}}, "required": ["layers"]}
LABEL_SCHEMA = {"type": "object", "properties": {"labels": {"type": "array", "items": {
    "type": "object", "properties": {
        "text": {"type": "string"}, "type": {"type": "string", "enum": list(LABEL_TYPES)},
        "name": {"type": "string"},
        "width": {"type": ["integer", "null"]}, "depth": {"type": ["integer", "null"]}},
    "required": ["text", "type", "name"]}}}, "required": ["labels"]}


def classify_layers(summaries: list, client: OllamaClient | None, log=print):
    """→ {layer: (role, source)}  source = 'AI' | '규칙'"""
    out = {s["name"]: (rule_layer_role(s), "규칙") for s in summaries}
    if not client:
        return out
    compact = [{k: s[k] for k in ("name", "entities", "n_texts", "sample_texts", "median_line_length")}
               for s in summaries]
    for i in range(0, len(compact), 40):
        batch = compact[i:i + 40]
        try:
            res = client.chat_json(LAYER_SYSTEM, json.dumps(batch, ensure_ascii=False), LAYER_SCHEMA)
        except OllamaError as e:
            log(f"[Ollama] 레이어 분류 실패 → 규칙 사용: {e}")
            return out
        names = {b["name"] for b in batch}
        n_ok = 0
        for item in res.get("layers", []) if isinstance(res, dict) else []:
            nm, role = item.get("name"), item.get("role")
            if nm in names and role in LAYER_ROLES:
                out[nm] = (role, "AI"); n_ok += 1
        log(f"[Ollama] 레이어 {len(batch)}개 중 {n_ok}개 AI 분류")
    return out


def classify_labels(texts: list, client: OllamaClient | None, log=print):
    """texts: unique strings → {text: {'type','name','width','depth','source'}}"""
    out = {}
    for t in texts:
        p = parse_label(t)
        if p:
            p["source"] = "규칙"
            out[t] = p
    if not client or not texts:
        return out
    uniq = list(dict.fromkeys(texts))[:600]
    for i in range(0, len(uniq), 120):
        batch = uniq[i:i + 120]
        try:
            res = client.chat_json(LABEL_SYSTEM, json.dumps(batch, ensure_ascii=False), LABEL_SCHEMA)
        except OllamaError as e:
            log(f"[Ollama] 부재명 해석 실패 → 규칙 사용: {e}")
            return out
        n_ok = 0
        for item in res.get("labels", []) if isinstance(res, dict) else []:
            t = item.get("text")
            if t not in batch or item.get("type") not in LABEL_TYPES:
                continue
            name = str(item.get("name") or "").strip()
            if not name or len(name) > 16:
                continue
            w, d = item.get("width"), item.get("depth")
            w = int(w) if isinstance(w, (int, float)) and 50 <= w <= 5000 else None
            d = int(d) if isinstance(d, (int, float)) and 50 <= d <= 5000 else None
            # sanity: the AI's name must actually appear in the text
            if name.replace(" ", "").upper() not in t.replace(" ", "").upper():
                continue
            out[t] = {"type": item["type"], "name": name, "width": w, "depth": d, "source": "AI"}
            n_ok += 1
        log(f"[Ollama] 부재명 {len(batch)}종 중 {n_ok}종 AI 해석")
    return out


def fallback_auto(summaries: list, roles: dict) -> dict:
    """If no layer was recognised as member geometry, geometry-heavy layers
    (not obviously non-structural) are switched to shape recognition."""
    geo_roles = ("column", "girder", "beam", "wall", "auto")
    if any(r in geo_roles for r, _src in roles.values()):
        return roles
    out = dict(roles)
    for s in summaries:
        ents = s.get("entities", {})
        n_geo = sum(v for k, v in ents.items() if k in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"))
        u = s["name"].upper()
        if n_geo >= 20 and out[s["name"]][0] == "ignore" and not any(k in u for k in IGNORE_KEYS + GRID_KEYS):
            out[s["name"]] = ("auto", "자동")
    return out
