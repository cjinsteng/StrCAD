"""부재리스트 (부재일람 ↔ 현장검측).

res.schedule = [entry]   entry = {
    "id", "kind": slab|girder|beam|column|wall|other, "name": "G1",
    "b": "500", "h": "600",            # 부재일람(설계) — 도면 추정 또는 사용자 입력 (슬래브·벽: b = 두께)
    "src": "도면" | "사용자" | "검측",
    "meas_b", "meas_h": 직접 입력한 현장검측 값 (없으면 검측기록에서 자동),
    "status": "" (자동) | "조사됨" | "조사안됨",
    "note": "" }
검측기록의 부재명 '기둥 C1' ↔ (column, C1).
"""
from __future__ import annotations

from collections import Counter

from .model import KIND_KO

KINDS = ("slab", "girder", "beam", "column", "wall", "other")
KIND_TAB = {"slab": "슬래브", "girder": "거더", "beam": "보", "column": "기둥", "wall": "벽체", "other": "기타"}
KO2KIND = {"슬래브": "slab", "거더": "girder", "보": "beam", "기둥": "column", "벽체": "wall", "벽": "wall",
           "기타": "other", "계단": "other", "기초": "other"}
LETTER = {"C": "column", "G": "girder", "B": "beam", "W": "wall", "S": "slab"}


def _fmt(v):
    if v in (None, "", 0):
        return ""
    v = float(v)
    return f"{v:.0f}" if abs(v - round(v)) < 1e-6 else f"{v:.1f}"


def full_name(e):
    return f"{KIND_TAB[e['kind']] if e['kind'] != 'wall' else '벽체'} {e['name']}".strip()


def split_name(text):
    """'기둥 C1' → ('column', 'C1');  'G1' → (guess, 'G1');  '보' → ('beam', '')"""
    t = (text or "").strip()
    if not t:
        return None, ""
    parts = t.split(None, 1)
    if parts[0] in KO2KIND:
        return KO2KIND[parts[0]], (parts[1].strip() if len(parts) > 1 else "")
    import re
    m = re.match(r"^[A-Z]{0,2}\d{0,2}([A-Z])\d", t.upper())
    return (LETTER.get(m.group(1)) if m else None), t


def next_id(sch):
    return max((e["id"] for e in sch), default=0) + 1


def find(sch, kind, name):
    for e in sch:
        if e["name"] == name and (kind is None or e["kind"] == kind):
            return e
    return None


def estimate(res):
    """도면(분석 결과)에서 부재일람 추정: 이름 있는 부재별 대표 단면."""
    groups = {}
    for m in res.members:
        if not m.name:
            continue
        groups.setdefault((m.kind, m.name), []).append(m)
    out = []
    for (kind, name), ms in sorted(groups.items(), key=lambda kv: (KINDS.index(kv[0][0]), kv[0][1])):
        if kind == "column":
            b, h = Counter((round(m.b), round(m.h)) for m in ms).most_common(1)[0][0]
        elif kind == "wall":
            b, h = Counter(round(m.width) for m in ms).most_common(1)[0][0], ""
        else:
            b = Counter(round(m.width) for m in ms).most_common(1)[0][0]
            ds = [round(m.depth) for m in ms if m.depth]
            h = Counter(ds).most_common(1)[0][0] if ds else ""
        out.append({"kind": kind, "name": name, "b": _fmt(b), "h": _fmt(h), "src": "도면", "n": len(ms)})
    return out


def merge_estimate(sch, res):
    """추정값을 리스트에 반영: 새 이름은 추가, '도면' 출처는 값 갱신, 사용자가 고친 항목은 유지."""
    added = updated = 0
    for est in estimate(res):
        e = find(sch, est["kind"], est["name"])
        if e is None:
            sch.append({"id": next_id(sch), "kind": est["kind"], "name": est["name"], "b": est["b"], "h": est["h"],
                        "src": "도면", "meas_b": "", "meas_h": "", "status": "", "note": ""})
            added += 1
        elif e.get("src") == "도면" and (e["b"], e["h"]) != (est["b"], est["h"]):
            e["b"], e["h"] = est["b"], est["h"]
            updated += 1
    return added, updated


def linked(e, surveys):
    """이 부재에 연결된 검측기록 (부재명이 같은 것)"""
    out = []
    for r in surveys:
        k, n = split_name(r.get("name", ""))
        if n == e["name"] and (k is None or k == e["kind"]):
            out.append(r)
    return out


def measured(e, surveys):
    """→ (b, h, records)  현장검측값: 직접입력 > 최근 검측기록"""
    recs = linked(e, surveys)
    b, h = e.get("meas_b", ""), e.get("meas_h", "")
    if not (b or h):
        for r in sorted(recs, key=lambda r: r.get("updated", ""), reverse=True):
            if r.get("size_b") or r.get("size_h"):
                b, h = r.get("size_b", ""), r.get("size_h", "")
                break
    return b, h, recs


def status(e, surveys):
    if e.get("status"):
        return e["status"]
    return "조사됨" if linked(e, surveys) else ""


def design_text(e):
    if e["kind"] in ("slab", "wall"):
        return f"t={e['b']}" if e.get("b") else "~"
    return f"{e.get('b') or '~'}  X  {e.get('h') or '~'}"


def meas_text(e, surveys):
    b, h, recs = measured(e, surveys)
    if not (b or h):
        return "조사안됨" if not recs else "치수 미입력"
    if e["kind"] in ("slab", "wall"):
        return f"t={b}"
    return f"{b or '-'}  X  {h or '-'}"


def compare(e, surveys):
    """'일치' / '상이' / ''  (설계값과 검측값이 20mm 넘게 다르면 상이)"""
    b, h, _ = measured(e, surveys)
    pairs = [(e.get("b"), b), (e.get("h"), h)]
    diff = False
    seen = False
    for d, m in pairs:
        try:
            dv, mv = float(d), float(m)
        except (TypeError, ValueError):
            continue
        seen = True
        if abs(dv - mv) > 20:
            diff = True
    return ("상이" if diff else "일치") if seen else ""


def ensure_from_record(sch, rec):
    """검측기록을 저장할 때 부재명이 리스트에 없으면 추가 → 새 항목 또는 None"""
    k, n = split_name(rec.get("name", ""))
    if not n or k is None:
        return None
    if find(sch, k, n):
        return None
    e = {"id": next_id(sch), "kind": k, "name": n, "b": "", "h": "", "src": "검측", "meas_b": "", "meas_h": "",
         "status": "", "note": ""}
    sch.append(e)
    return e


def rename(sch, surveys, e, new):
    old = full_name(e)
    old_short = e["name"]
    e["name"] = new
    n = 0
    for r in surveys:
        k, nm = split_name(r.get("name", ""))
        if nm == old_short and (k is None or k == e["kind"]):
            r["name"] = full_name(e)
            n += 1
    return old, n


def names_for_pick(sch, kind=None):
    """검측 입력의 부재명 선택 목록용"""
    es = [e for e in sch if kind is None or e["kind"] == kind] + [e for e in sch if kind and e["kind"] != kind]
    return [full_name(e) for e in es]
