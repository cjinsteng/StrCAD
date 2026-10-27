"""AI review of the analysed model.

Code finds suspicious spots and measures them; Ollama decides what to do
(rules decide when Ollama is off). Nothing is changed until the user accepts.

  joint    : a girder/beam/wall end that is not connected, with a node or a
             member close by → merge / keep
  col_wall : a "column" that looks like a wall (long & thin, walls continue
             from its ends, no C-mark) → to_wall / keep
"""
from __future__ import annotations

import json
import math
import re

from . import topology as T
from .geometry import dist_point_seg
from .model import KIND_KO
from .ollama_client import OllamaError

SEARCH_R = 1500.0


# ============================================================================
def _degree(res):
    deg = {}
    for m in res.members:
        for nid in (m.node, m.n1, m.n2):
            if nid is not None:
                deg[nid] = deg.get(nid, 0) + 1
        for i in m.inner:
            deg[i[0]] = deg.get(i[0], 0) + 1
    return deg


def find_candidates(res):
    deg = _degree(res)
    cands = []
    lins = [m for m in res.members if m.kind in T.LINEAR and not m.curved]
    cols = {m.node: m for m in res.members if m.kind == "column"}

    # ---- joints -------------------------------------------------------------
    for m in lins:
        ux, uy, L = T._dir(m)
        for k in (1, 2):
            nid = m.n1 if k == 1 else m.n2
            if deg.get(nid, 0) != 1:
                continue
            ex, ey = res.nodes[nid].xy
            ox, oy = (-ux, -uy) if k == 1 else (ux, uy)      # outward
            other_end = m.n2 if k == 1 else m.n1
            best = None
            for n in res.nodes.values():
                if n.id in (nid, other_end):
                    continue
                d = math.hypot(n.x - ex, n.y - ey)
                if d <= SEARCH_R and (best is None or d < best["gap"]):
                    vx, vy = n.x - ex, n.y - ey
                    best = {"target": ("node", n.id), "gap": d, "pt": n.xy,
                            "along": vx * ox + vy * oy, "lateral": abs(vx * oy - vy * ox),
                            "target_desc": ("기둥 절점" if n.id in cols else f"절점(부재 {deg.get(n.id, 0)}개)")}
            for h in lins:
                if h is m:
                    continue
                d, t = dist_point_seg(ex, ey, *h.p1, *h.p2)
                if not (0.02 < t < 0.98) or d > SEARCH_R:
                    continue
                px, py = h.p1[0] + (h.p2[0] - h.p1[0]) * t, h.p1[1] + (h.p2[1] - h.p1[1]) * t
                hx, hy, _ = T._dir(h)
                if abs(hx * uy - hy * ux) < 0.26:
                    continue                                   # parallel: not a T
                if best is None or d < best["gap"] - 1:
                    vx, vy = px - ex, py - ey
                    best = {"target": ("member", h.id, t), "gap": d, "pt": (px, py),
                            "along": vx * ox + vy * oy, "lateral": abs(vx * oy - vy * ox),
                            "target_desc": f"{KIND_KO[h.kind]} {h.display_name()} 옆면"}
            if best is None:
                continue
            cands.append({
                "id": f"J{len(cands) + 1}", "type": "joint", "member": m.id, "node": nid,
                "where": (ex, ey), "to": best["pt"], "target": best["target"],
                "features": {
                    "member": f"{KIND_KO[m.kind]} {m.display_name()} {m.size_text()} L={m.length_cc:.0f}",
                    "member_width": round(m.width), "gap_mm": round(best["gap"]),
                    "ahead_along_axis_mm": round(best["along"]), "sideways_offset_mm": round(best["lateral"]),
                    "target": best["target_desc"]},
            })

    # ---- columns that look like walls ------------------------------------------
    for c in res.members:
        if c.kind != "column" or c.shape == "round":
            continue
        aspect = c.b / max(c.h, 1)
        r = math.radians(c.angle)
        ax, ay = math.cos(r), math.sin(r)
        walls_inline = 0
        walls_at = 0
        for m in T.members_at(res, c.node):
            if m.kind == "wall":
                walls_at += 1
                wx, wy, _ = T._dir(m)
                if abs(wx * ay - wy * ax) < 0.17:
                    walls_inline += 1
        # walls whose ends touch the column outline in line with its long axis
        for m in lins:
            if m.kind != "wall" or c.node in (m.n1, m.n2):
                continue
            for p in (m.p1, m.p2):
                if math.dist(p, c.center) <= c.b / 2 + m.width:
                    wx, wy, _ = T._dir(m)
                    if abs(wx * ay - wy * ax) < 0.17:
                        walls_inline += 1
        marked = bool(re.match(r"^[A-Z]{0,2}\d{0,2}S?C\d", c.name or ""))
        if not (aspect >= 2.0 or c.h < 250 or walls_inline >= 1):
            continue
        cands.append({
            "id": f"C{len(cands) + 1}", "type": "col_wall", "member": c.id, "where": c.center, "to": c.center,
            "features": {
                "column": f"{c.display_name()} {c.b:.0f}x{c.h:.0f}", "long_side_mm": round(c.b),
                "short_side_mm": round(c.h), "aspect": round(aspect, 2),
                "walls_continuing_in_line": walls_inline, "walls_connected": walls_at,
                "has_column_mark": marked, "found_by": "shape" if c.auto else "column layer"},
        })
    return cands


# ============================================================================
def rule_decide(c):
    f = c["features"]
    if c["type"] == "joint":
        w = max(f["member_width"], 200)
        if f["gap_mm"] <= 300:
            return "merge", "간격 300 이하"
        if -w <= f["ahead_along_axis_mm"] <= SEARCH_R and f["sideways_offset_mm"] <= max(w, 400):
            return "merge", "부재 축 방향 앞쪽에 연결점"
        return "keep", "축 방향과 어긋남 (자유단 가능)"
    if f["has_column_mark"] and f["aspect"] < 3:
        return "keep", "기둥 표기(C…) 있음"
    if f["aspect"] >= 3 or f["short_side_mm"] < 200:
        return "to_wall", f"가늘고 긴 단면 (비 {f['aspect']})"
    if f["aspect"] >= 2 and f["walls_continuing_in_line"] >= 1:
        return "to_wall", "같은 방향으로 벽이 이어짐"
    return "keep", "기둥 단면으로 타당"


SYSTEM = """You review an automatically extracted structural model from a Korean framing plan (구조평면도).
Members: column(기둥), girder(거더), beam(보), wall(벽체). Lengths in mm.
For each candidate decide an action.
- type "joint": a member end that is not connected to anything. "merge" if it should connect to the target
  (typical: target lies ahead along the member axis with small sideways offset, or the gap is small compared
  with member widths). "keep" if it is a genuine free end (cantilever, wall end at an opening) or the target is
  clearly unrelated (large sideways offset).
- type "col_wall": something recognised as a column. "to_wall" if it is really a wall piece (long and thin,
  aspect >= ~2.5, walls continue in line with it, no column mark like C1). "keep" if it is a real column
  (column mark present, near-square, or wall-column with mark).
Return JSON: {"decisions":[{"id":"<id>","action":"merge|keep|to_wall","reason":"<short Korean reason>"}]}"""

SCHEMA = {"type": "object", "properties": {"decisions": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"},
                                     "action": {"type": "string", "enum": ["merge", "keep", "to_wall"]},
                                     "reason": {"type": "string"}},
    "required": ["id", "action"]}}}, "required": ["decisions"]}

VALID = {"joint": ("merge", "keep"), "col_wall": ("to_wall", "keep")}


def decide(cands, client=None, log=print):
    for c in cands:
        a, why = rule_decide(c)
        c.update(action=a, reason=why, source="규칙")
    if not client or not cands:
        return cands
    by_id = {c["id"]: c for c in cands}
    for i in range(0, len(cands), 50):
        batch = cands[i:i + 50]
        payload = [{"id": c["id"], "type": c["type"], **c["features"]} for c in batch]
        try:
            res = client.chat_json(SYSTEM, json.dumps(payload, ensure_ascii=False), SCHEMA)
        except OllamaError as e:
            log(f"[Ollama] 검토 실패 → 규칙 판단 사용: {e}")
            return cands
        n = 0
        for d in res.get("decisions", []) if isinstance(res, dict) else []:
            c = by_id.get(d.get("id"))
            if c and d.get("action") in VALID[c["type"]]:
                c.update(action=d["action"], reason=str(d.get("reason") or "")[:80] or c["reason"], source="AI")
                n += 1
        log(f"[Ollama] 검토 {len(batch)}건 중 {n}건 AI 판단")
    return cands


# ============================================================================
def apply(res, c):
    """Apply one accepted suggestion. Returns a short log string or None."""
    byid = res.by_id()
    if c["type"] == "joint" and c["action"] == "merge":
        m = byid.get(c["member"])
        nid = c["node"]
        if m is None or nid not in res.nodes or nid not in (m.n1, m.n2):
            return None
        tgt = c["target"]
        if tgt[0] == "node":
            if tgt[1] not in res.nodes:
                return None
            T.merge_nodes(res, nid, tgt[1])
        else:
            h = byid.get(tgt[1])
            if h is None:
                return None
            T.attach_node_to_member(res, nid, h, tgt[2])
        return f"#{m.id} 끝 연결"
    if c["type"] == "col_wall" and c["action"] == "to_wall":
        m = byid.get(c["member"])
        if m is None or m.kind != "column":
            return None
        T.change_kind(res, m, "wall")
        return f"#{m.id} 기둥→벽"
    return None
