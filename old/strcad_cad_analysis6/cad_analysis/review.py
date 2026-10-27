"""AI review of the analysed model.

Code finds suspicious spots and measures them; Ollama decides what to do
(rules decide when Ollama is off). Nothing is changed until the user accepts.

  joint    : a girder/beam/wall end that is not connected, with a node or a
             member close by → merge / keep
  col_wall : a "column" that looks like a wall (long & thin, walls continue
             from its ends, no C-mark) → to_wall / keep
  layer    : a layer whose role does not fit its contents (geometry statistics,
             which member marks lie nearest to its lines, members produced) → change / keep
  add_col  : a girder end without a column although a column is likely there
             (outline on another layer, C-mark, grid intersection, girders meeting) → add / keep
"""
from __future__ import annotations

import json
import math
import re

from . import topology as T
from collections import Counter, defaultdict

from .classifier import parse_label, IGNORE_KEYS, GRID_KEYS
from .geometry import dist_point_seg, Params, pair_edges, min_area_rect, point_in_poly, extract_columns
from .model import KIND_KO, LAYER_ROLE_KO, SRC_LABEL, SRC_INFERRED
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

VALID = {"joint": ("merge", "keep"), "col_wall": ("to_wall", "keep"),
         "layer": ("change", "keep"), "add_col": ("add", "keep")}


def decide(cands, client=None, log=print):
    for c in cands:
        if c["type"] == "layer":
            a, why, role = rule_layer(c["features"])
            c.update(action=a, reason=why, source="규칙", new_role=role, rule_role=role)
        elif c["type"] == "add_col":
            a, why = rule_add_col(c["features"])
            c.update(action=a, reason=why, source="규칙")
        else:
            a, why = rule_decide(c)
            c.update(action=a, reason=why, source="규칙")
    if client and cands:
        groups = (([c for c in cands if c["type"] in ("joint", "col_wall")], SYSTEM, SCHEMA),
                  ([c for c in cands if c["type"] == "add_col"], SYSTEM_COL, SCHEMA_COL),
                  ([c for c in cands if c["type"] == "layer"], SYSTEM_LAYER, SCHEMA_LAYER))
        for group, system, schema in groups:
            if group and not _ai_decide(group, system, schema, client, log):
                break
    for c in cands:
        c["weak"] = (c["type"] == "layer" and c["action"] == "change" and c.get("new_role") == "auto"
                     and c["source"] == "규칙")
    if any(c["type"] == "layer" for c in cands):
        # only layers with a proposed change (or a rule finding) are worth showing
        cands[:] = [c for c in cands if c["type"] != "layer" or c["action"] == "change" or c.get("rule_role")]
    return cands


def _ai_decide(batch_all, system, schema, client, log):
    by_id = {c["id"]: c for c in batch_all}
    for i in range(0, len(batch_all), 40):
        batch = batch_all[i:i + 40]
        payload = [{"id": c["id"], "type": c["type"], **c["features"]} for c in batch]
        try:
            res = client.chat_json(system, json.dumps(payload, ensure_ascii=False), schema)
        except OllamaError as e:
            log(f"[Ollama] 검토 실패 → 규칙 판단 사용: {e}")
            return False
        n = 0
        for d in res.get("decisions", []) if isinstance(res, dict) else []:
            c = by_id.get(d.get("id"))
            if not c or d.get("action") not in VALID[c["type"]]:
                continue
            why = str(d.get("reason") or "")[:80]
            if c["type"] == "layer":
                if d["action"] == "change":
                    role = d.get("role")
                    if role not in LAYER_CHOICES or role == c["features"]["current_role"]:
                        continue
                    ok, note = _layer_change_plausible(c["features"], role)
                    if not ok:                       # AI wanted a change the evidence does not support
                        c["ai_note"] = f"AI 제안 {LAYER_ROLE_KO.get(role, role)} 기각: {note}"
                        continue
                    c.update(new_role=role)
                else:
                    c.update(new_role=None)
            if c["type"] == "add_col" and d["action"] == "add":
                f = c["features"]
                g = f["grid_intersection_mm"]
                if not (f["column_outline_found"] or f["column_mark"] or (g is not None and g <= 1000)):
                    c["reason"] = f"AI 기둥 추가 제안 기각 (외곽선·표기·그리드 근거 없음) / {c['reason']}"
                    continue
            c.update(action=d["action"], reason=why or c["reason"], source="AI")
            n += 1
        log(f"[Ollama] 검토 {len(batch)}건 중 {n}건 AI 판단")
    return True


# ============================================================================
#  layer roles: do the contents of each layer fit the role it was given?
# ============================================================================
LAYER_CHOICES = ("column", "girder", "beam", "wall", "column_name", "girder_name", "beam_name", "wall_name",
                 "member_text", "auto", "grid", "ignore")
GEO = ("column", "girder", "beam", "wall")
_SKIP_NEAREST = ("DIM", "치수", "HATCH", "해치", "TEXT", "문자", "LEADER", "SYMBOL", "TITLE", "도곽", "FORM")


def _poly_info(pts):
    r = min_area_rect(pts)
    if not r:
        return None
    cx, cy, w, h, ang = r
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    fill = abs(a) / 2 / max(w * h, 1e-9)
    return cx, cy, w, h, ang, fill


def _compact_rect(info, lo=200, hi=2000, aspect=3.0):
    return info and lo <= info[3] and info[2] <= hi and info[2] / max(info[3], 1) <= aspect and info[5] >= 0.8


def collect_labels(dd):
    """Member marks anywhere in the drawing (rules only, any layer) → [(x, y, kind, name, layer)]."""
    out = []
    for name, ld in dd.layers.items():
        for t in ld.texts:
            p = parse_label(t.text)
            if p and p["type"] in GEO:
                out.append((t.x, t.y, p["type"], p["name"], name))
    return out


def layer_features(dd, roles, res, labels=None, params=None, log=print):
    p = params or Params()
    labels = collect_labels(dd) if labels is None else labels
    made = Counter(m.layer for m in res.members) if res else Counter()
    # sample points of every geometry layer → nearest layer for each label
    CELL = 1000.0
    hashp = defaultdict(list)
    for name, ld in dd.layers.items():
        u = name.upper()
        if roles.get(name) == "grid" or any(k in u for k in GRID_KEYS + _SKIP_NEAREST):
            continue
        for sg in ld.segments:
            n = max(1, int(sg.length // 700))
            for i in range(n + 1):
                x = sg.x1 + (sg.x2 - sg.x1) * i / n
                y = sg.y1 + (sg.y2 - sg.y1) * i / n
                hashp[(int(x // CELL), int(y // CELL))].append((x, y, name))
        for poly in ld.polygons + ld.hatches:
            x = sum(q[0] for q in poly) / len(poly)
            y = sum(q[1] for q in poly) / len(poly)
            hashp[(int(x // CELL), int(y // CELL))].append((x, y, name))
    near = defaultdict(Counter)          # all marks
    near_free = defaultdict(Counter)     # marks no extracted member explains (evidence of a missed layer)
    mem = res.members if res else []
    for x, y, kind, _nm, _ly in labels:
        explained = _explained(x, y, kind, mem)
        cx, cy = int(x // CELL), int(y // CELL)
        best = None
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for px, py, ly in hashp.get((cx + i, cy + j), ()):
                    d = (px - x) ** 2 + (py - y) ** 2
                    if d <= 1500.0 ** 2 and (best is None or d < best[0]):
                        best = (d, ly)
        if best:
            near[best[1]][kind] += 1
            if not explained:
                near_free[best[1]][kind] += 1
    feats = {}
    for name, ld in dd.layers.items():
        nseg = len(ld.segments)
        nt = len(ld.texts)
        polys = ld.polygons + ld.hatches
        if nseg + len(polys) + len(ld.circles) + nt < 3:
            continue
        infos = [_poly_info(q) for q in polys]
        rects = sum(1 for i in infos if _compact_rect(i))
        f = {"layer": name, "current_role": roles.get(name, "ignore"), "lines": nseg, "closed_shapes": len(polys),
             "hatches": len(ld.hatches), "circles": len(ld.circles), "texts": nt,
             "column_like_rects": rects, "members_made_from_layer": made.get(name, 0),
             "nearest_layer_for_marks": dict(near.get(name, {})),
             "unexplained_marks_nearest": dict(near_free.get(name, {}))}
        if 4 <= nseg <= 40000:
            pcs = pair_edges(ld.segments, 80.0, 2500.0, p)
            tot = sum(sg.length for sg in ld.segments) or 1.0
            ws = sorted(pc.width for pc in pcs)
            f["parallel_pairs"] = len(pcs)
            f["paired_length_ratio"] = round(min(1.0, sum(2 * (pc.t1 - pc.t0) for pc in pcs) / tot), 2)
            f["median_pair_width_mm"] = round(ws[len(ws) // 2]) if ws else 0
        else:
            f["parallel_pairs"], f["paired_length_ratio"], f["median_pair_width_mm"] = 0, 0.0, 0
        if nt:
            mk = Counter()
            for t in ld.texts:
                q = parse_label(t.text)
                if q and q["type"] in GEO:
                    mk[q["type"]] += 1
            f["member_marks_in_texts"] = dict(mk)
            f["sample_texts"] = list(dict.fromkeys(t.text for t in ld.texts))[:6]
        feats[name] = f
    return feats


def _explained(x, y, kind, members, lim=1500.0):
    for m in members:
        if kind == "column":
            if m.kind == "column" and math.hypot(x - m.center[0], y - m.center[1]) <= max(lim, m.b * 1.5):
                return True
        elif m.kind in ("girder", "beam", "wall") and not m.curved:
            d, t = dist_point_seg(x, y, *m.p1, *m.p2)
            if d <= lim and -0.05 <= t <= 1.05:
                return True
    return False


def _shape_guess(f):
    if f["column_like_rects"] >= 3 and f["column_like_rects"] * 4 >= 0.4 * max(f["lines"], 1):
        return "column", f"기둥형 사각형 {f['column_like_rects']}개"
    if f["parallel_pairs"] >= 3 and f["paired_length_ratio"] >= 0.45:
        w = f["median_pair_width_mm"]
        if w <= 300:
            return "wall", f"평행선 쌍 두께 {w}"
        return "girder", f"평행선 쌍 폭 {w}"
    return None, ""


def _top_mark(f, min_n=3, share=0.6, key="nearest_layer_for_marks", kinds=GEO):
    near = {k: v for k, v in f[key].items() if k in kinds}
    tot = sum(near.values())
    if not tot:
        return None, 0
    k, n = max(near.items(), key=lambda kv: kv[1])
    return (k, n) if n >= min_n and n >= share * tot else (None, n)


def rule_layer(f):
    """→ (action, reason, new_role|None)"""
    role = f["current_role"]
    # ---- text layers
    mk = f.get("member_marks_in_texts", {})
    if f["texts"] >= 3 and f["texts"] >= f["lines"]:
        good = sum(mk.values())
        if good >= max(3, 0.5 * f["texts"]):
            k, n = max(mk.items(), key=lambda kv: kv[1])
            want = f"{k}_name" if n >= 0.8 * good else "member_text"
            if role != want and role != "member_text" and not (role.endswith("_name") and n < 0.8 * good):
                return "change", f"텍스트 {f['texts']}개 중 부재표기 {good}개 ({KIND_KO[k]} {n})", want
        elif role.endswith("_name") or role == "member_text":
            if f["texts"] >= 5 and good <= 0.1 * f["texts"]:
                return "change", f"텍스트 {f['texts']}개 중 부재표기 {good}개뿐", "ignore"
        return "keep", "", None
    if f["lines"] + f["closed_shapes"] < 4:
        return "keep", "", None
    guess, why = _shape_guess(f)
    if role == "column" and f["parallel_pairs"] >= 10 and f["paired_length_ratio"] >= 0.4 \
            and f["median_pair_width_mm"] <= 400 and f["parallel_pairs"] > 3 * f["column_like_rects"]:
        return "change", (f"기둥 레이어지만 내용 대부분이 벽 형상 (평행선 쌍 {f['parallel_pairs']}개, "
                          f"두께 {f['median_pair_width_mm']}, 기둥형 사각형 {f['column_like_rects']}개)"), "wall"
    if role in GEO:
        # columns stand next to every girder/wall line, so only line-member marks are compared here
        k, n = _top_mark(f, 5, 0.7, kinds=("girder", "beam", "wall")) if role != "column" else \
            _top_mark(f, 5, 0.7)
        if k and k != role and f["nearest_layer_for_marks"].get(role, 0) <= 0.2 * n:
            return "change", f"이 레이어 선에 가장 가까운 표기가 {KIND_KO[k]} {n}개 ({KIND_KO[role]} 표기는 "\
                             f"{f['nearest_layer_for_marks'].get(role, 0)}개)", k
        if f["members_made_from_layer"] == 0:
            g = guess if guess and guess != role else "ignore"
            return "change", f"{LAYER_ROLE_KO[role]}로 지정됐지만 부재가 하나도 안 나옴" + (f" ({why})" if why else ""), g
        return "keep", "", None
    if role in ("ignore", "auto"):
        named_ignore = any(x in f["layer"].upper() for x in IGNORE_KEYS)
        k, n = _top_mark(f, 6 if named_ignore else 3, 0.6, key="unexplained_marks_nearest")
        if k == "column" and f["column_like_rects"] < max(2, n):
            k = None
        linear = guess in ("wall", "girder") and f["parallel_pairs"] >= max(8, 5 * f["column_like_rects"])
        if k and linear:
            # mostly line pairs: the layer draws walls/girders (columns standing in them carry the C marks)
            role2 = k if k in ("girder", "beam", "wall") else guess
            return "change", (f"{'무시' if role == 'ignore' else '자동판별'} 레이어지만 {why}, 부재를 못 찾은 "
                              f"{KIND_KO[k]} 표기 {n}개가 이 레이어 선에 가장 가까움"), role2
        if k and ((k != "column" and f["parallel_pairs"] >= 3) or (k == "column" and f["column_like_rects"] >= 2)):
            return "change", (f"{'무시' if role == 'ignore' else '자동판별'} 레이어지만, 부재를 못 찾은 "
                              f"{KIND_KO[k]} 표기 {n}개가 이 레이어 선에 가장 가까움"), k
        u = f["layer"].upper()
        if role == "ignore" and guess and not any(x in u for x in IGNORE_KEYS + GRID_KEYS) and not f["members_made_from_layer"]:
            # structural-looking geometry nobody uses, without a 'non-structural' name
            if f["parallel_pairs"] >= 8 or f["column_like_rects"] >= 4:
                return "change", f"무시 레이어지만 구조부재 형상 ({why}) — 확인 필요", "auto"
    return "keep", "", None


def _layer_change_plausible(f, role):
    """An AI layer change is accepted only when the measured evidence supports it."""
    near, free = f["nearest_layer_for_marks"], f["unexplained_marks_nearest"]
    if role == "ignore":
        return (f["members_made_from_layer"] == 0, f"이 레이어에서 부재 {f['members_made_from_layer']}개가 나옴")
    if role in ("grid", "auto"):
        return True, ""
    if role in GEO and any(x in f["layer"].upper() for x in IGNORE_KEYS) and \
            sum(free.values()) < 6 and f["members_made_from_layer"] == 0:
        return False, "이름이 비구조 레이어(하부·주차·해치 등)이고 근거 표기가 적음"
    if role.endswith("_name") or role == "member_text":
        good = sum(f.get("member_marks_in_texts", {}).values())
        return (f["texts"] >= 3 and good >= 0.5 * f["texts"], "부재표기 텍스트가 거의 없음")
    if role == "column":
        rects = f["column_like_rects"]
        ok = rects >= 2 and (free.get("column", 0) >= 2 or rects * 4 >= 0.4 * max(f["lines"], 1))
        return ok, f"기둥형 사각형 {rects}개 — 근거 부족"
    if f["parallel_pairs"] < 3:
        return False, "평행선 쌍 없음"
    lin = {k: v for k, v in near.items() if k in ("girder", "beam", "wall")}
    guess, _ = _shape_guess(f)
    if free.get(role, 0) >= 2 or (lin.get(role, 0) >= 5 and lin.get(role, 0) >= 0.5 * sum(lin.values())) \
            or guess == role or (guess == "girder" and role == "beam"):
        return True, ""
    return False, "근처 부재표기·형상 근거 없음"


SYSTEM_LAYER = """You check layer roles of a Korean structural framing plan (구조평면도) after a first automatic analysis.
Each item is one layer with its current role and measured evidence:
- nearest_layer_for_marks: how many member marks (C1=column, G1=girder, B1=beam, W1=wall) have THIS layer's
  lines as the nearest geometry. Columns stand next to girders/walls, so column marks near a girder/wall layer are normal.
- unexplained_marks_nearest: same, counting only marks for which the first pass found NO member - strong evidence
  that this layer holds members that were missed (e.g. an "ignore" layer that really draws girders)
- parallel_pairs / paired_length_ratio / median_pair_width_mm: line pairs typical of girders/beams/walls
- column_like_rects: small closed rectangles (columns); members_made_from_layer: members found in the first pass
- member_marks_in_texts / sample_texts for text layers
Roles: column, girder, beam, wall (geometry); column_name, girder_name, beam_name, wall_name, member_text (texts);
auto (geometry whose member type is decided by shape); grid; ignore.
Layer names are often wrong or misleading; trust the evidence. Keep the role unless evidence clearly contradicts it.
Return JSON: {"decisions":[{"id":"<id>","action":"change|keep","role":"<new role when change>","reason":"<short Korean reason>"}]}"""

SCHEMA_LAYER = {"type": "object", "properties": {"decisions": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "action": {"type": "string", "enum": ["change", "keep"]},
                                     "role": {"type": "string", "enum": list(LAYER_CHOICES)},
                                     "reason": {"type": "string"}},
    "required": ["id", "action"]}}}, "required": ["decisions"]}


def find_layer_candidates(dd, roles, res, labels=None, log=print):
    feats = layer_features(dd, roles, res, labels=labels, log=log)
    out = []
    for name, f in sorted(feats.items()):
        pts = []
        ld = dd.layers[name]
        for sg in ld.segments[:4000]:
            pts += [(sg.x1, sg.y1), (sg.x2, sg.y2)]
        pts += [(t.x, t.y) for t in ld.texts[:2000]]
        if not pts:
            continue
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        out.append({"id": f"L{len(out) + 1}", "type": "layer", "layer": name, "member": None,
                    "where": (min(xs), min(ys)), "to": (max(xs), max(ys)), "features": f})
    return out


# ============================================================================
#  girder ends without a column
# ============================================================================
def _outline_index(dd, p):
    """Closed shapes in every layer (any role) that could be a column outline."""
    out = []
    for name, ld in dd.layers.items():
        for poly in ld.polygons + ld.hatches:
            info = _poly_info(poly)
            if _compact_rect(info, 200, 2000, 3.0):
                out.append({"center": (info[0], info[1]), "b": info[2], "h": info[3], "angle": math.degrees(info[4]),
                            "polygon": [tuple(q) for q in poly], "layer": name, "shape": "rect"})
        for cx, cy, r in ld.circles:
            if 200 <= 2 * r <= 2000:
                out.append({"center": (cx, cy), "b": 2 * r, "h": 2 * r, "angle": 0.0, "layer": name, "shape": "round",
                            "polygon": [(cx + r * math.cos(t * math.pi / 12), cy + r * math.sin(t * math.pi / 12))
                                        for t in range(24)]})
    return out


def _grid_points(res):
    pts = []
    g = res.grid
    for i in range(len(g)):
        a = g[i]
        for j in range(i + 1, len(g)):
            b = g[j]
            d1x, d1y = a.x2 - a.x1, a.y2 - a.y1
            d2x, d2y = b.x2 - b.x1, b.y2 - b.y1
            den = d1x * d2y - d1y * d2x
            if abs(den) < 1e-9 * (a.length * b.length + 1):
                continue
            t = ((b.x1 - a.x1) * d2y - (b.y1 - a.y1) * d2x) / den
            u = ((b.x1 - a.x1) * d1y - (b.y1 - a.y1) * d1x) / den
            if -0.02 <= t <= 1.02 and -0.02 <= u <= 1.02:
                pts.append((a.x1 + d1x * t, a.y1 + d1y * t))
    return pts


def find_missing_columns(res, dd=None, labels=None):
    cols = [m for m in res.members if m.kind == "column"]
    col_nodes = {c.node for c in cols}
    sizes = Counter((round(c.b / 50) * 50, round(c.h / 50) * 50) for c in cols if c.shape != "round")
    typical = sizes.most_common(1)[0][0] if sizes else (600, 600)
    size_by_name = {}
    for c in cols:
        if c.name and c.name_source == SRC_LABEL:
            size_by_name.setdefault(c.name, (c.b, c.h))
    outlines = _outline_index(dd, Params()) if dd is not None else []
    if labels is None:
        labels = collect_labels(dd) if dd is not None else []
    col_marks = [(x, y, nm) for x, y, k, nm, _ly in labels if k == "column"]
    # marks already used by an existing column are not evidence for a new one
    col_marks = [q for q in col_marks if not any(
        math.hypot(q[0] - c.center[0], q[1] - c.center[1]) <= max(1500.0, c.b * 1.5) for c in cols)]
    gpts = _grid_points(res)
    deg = _degree(res)
    seen = set()
    out = []
    for g in res.members:
        if g.kind != "girder" or g.curved:
            continue
        for nid in (g.n1, g.n2):
            if nid is None or nid in col_nodes or nid in seen or nid not in res.nodes:
                continue
            seen.add(nid)
            x, y = res.nodes[nid].xy
            at = [m for m in T.members_at(res, nid) if m is not g]
            host, _e = T.host_of(res, nid)
            if host is not None and host.kind == "wall" or any(m.kind == "wall" for m in at):
                continue                                         # sits on a wall
            body = None                  # end lies inside another member's body (T-junction, not a column)
            for h in res.members:
                if h is g or h.kind not in ("girder", "beam", "wall") or h.curved or nid in (h.n1, h.n2):
                    continue
                d, t = dist_point_seg(x, y, *h.p1, *h.p2)
                if d <= h.width / 2 + g.width / 2 + 100:          # d is measured to the clamped segment
                    if body is None or h.kind == "wall":
                        body = h
            if body is not None and body.kind == "wall":
                continue                                         # girder rests on a wall
            lim = max(600.0, g.width)
            ol = None
            for o in outlines:
                d = math.hypot(o["center"][0] - x, o["center"][1] - y)
                if (d <= lim or point_in_poly(x, y, o["polygon"])) and (ol is None or d < ol[0]):
                    ol = (d, o)
            mk = None
            for q in col_marks:
                d = math.hypot(q[0] - x, q[1] - y)
                if d <= 1500 and (mk is None or d < mk[0]):
                    mk = (d, q[2])
            gd = min((math.hypot(px - x, py - y) for px, py in gpts), default=None)
            meet = sum(1 for m in at if m.kind in ("girder", "beam") and abs(
                T._dir(m)[0] * T._dir(g)[1] - T._dir(m)[1] * T._dir(g)[0]) > 0.5)
            ev = bool(ol) or bool(mk) or (gd is not None and gd <= 400) or meet >= 1
            if not ev:
                continue
            if ol:
                o = ol[1]
                b, h, ang, poly = o["b"], o["h"], o["angle"], o["polygon"]
                src = f"'{o['layer']}' 레이어 외곽선"
            else:
                b, h = size_by_name.get(mk[1], typical) if mk else typical
                ang, poly, src = g.angle, None, ("표기 " + mk[1]) if mk else "대표 단면"
            out.append({
                "id": f"A{len(out) + 1}", "type": "add_col", "member": g.id, "node": nid, "where": (x, y),
                "to": ol[1]["center"] if ol else (x, y),
                "place": {"x": ol[1]["center"][0] if ol else x, "y": ol[1]["center"][1] if ol else y,
                          "b": max(b, h), "h": min(b, h), "angle": ang, "polygon": poly,
                          "name": mk[1] if mk else "", "src": src},
                "features": {
                    "girder": f"{g.display_name()} {g.size_text()} L={g.length_cc:.0f}",
                    "end_connected_members": deg.get(nid, 0) - 1,
                    "girders_meeting_at_angle": meet,
                    "framed_into_girder_side": bool((host is not None and host.kind in ("girder", "beam"))
                                                    or body is not None),
                    "column_outline_found": (f"{ol[1]['b']:.0f}x{ol[1]['h']:.0f} on layer {ol[1]['layer']}"
                                             if ol else None),
                    "column_mark_near_mm": round(mk[0]) if mk else None,
                    "column_mark": mk[1] if mk else None,
                    "grid_intersection_mm": round(gd) if gd is not None else None,
                    "typical_column": f"{typical[0]}x{typical[1]}"},
            })
    return out


def rule_add_col(f):
    if f["column_outline_found"]:
        return "add", f"외곽선 발견 ({f['column_outline_found'].split(' on ')[0]})"
    if f["column_mark"]:
        return "add", f"기둥표기 {f['column_mark']} ({f['column_mark_near_mm']}mm)"
    if f["framed_into_girder_side"]:
        return "keep", "다른 거더 옆면에 걸침 (거더-거더 접합)"
    g = f["grid_intersection_mm"]
    if g is not None and g <= 400 and (f["girders_meeting_at_angle"] >= 1 or f["end_connected_members"] == 0):
        return "add", f"그리드 교점({g}mm) + 거더 끝"
    if f["girders_meeting_at_angle"] >= 2 and g is not None and g <= 600:
        return "add", f"거더 {f['girders_meeting_at_angle'] + 1}개가 모이는 그리드 교점({g}mm)"
    return "keep", "근거 부족"


SYSTEM_COL = """You review girder ends in an automatically extracted Korean structural framing plan (구조평면도).
Girders (큰보, G1...) normally span between columns, so a girder end with no column is suspicious.
For each candidate decide "add" (a column very likely stands here) or "keep" (no column: the girder frames into
another girder's side, rests on a wall, or is a cantilever).
Evidence: column_outline_found (closed outline on some layer at that point - strong), column_mark (C1.. mark nearby - strong),
grid_intersection_mm (distance to a grid intersection - small is supportive), girders_meeting_at_angle (other girders
meeting at an angle there), framed_into_girder_side (end sits on another girder's side - usually no column).
Return JSON: {"decisions":[{"id":"<id>","action":"add|keep","reason":"<short Korean reason>"}]}"""

SCHEMA_COL = {"type": "object", "properties": {"decisions": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "action": {"type": "string", "enum": ["add", "keep"]},
                                     "reason": {"type": "string"}},
    "required": ["id", "action"]}}}, "required": ["decisions"]}


# ============================================================================
TYPE_KO = {"joint": "미연결 절점", "col_wall": "기둥→벽 의심", "layer": "레이어 역할", "add_col": "거더 끝 기둥 추정"}


def describe(c):
    """(대상, 제안, 수치) strings for the review list."""
    f = c["features"]
    t = c["type"]
    if t == "joint":
        act = "연결(절점 합침)" if c["action"] == "merge" else "유지"
        return f["member"], act, (f"간격 {f['gap_mm']} · 축방향 {f['ahead_along_axis_mm']} · 옆 "
                                  f"{f['sideways_offset_mm']} → {f['target']}")
    if t == "col_wall":
        act = "벽으로 변경" if c["action"] == "to_wall" else "유지"
        return f["column"], act, (f"비 {f['aspect']} · 일직선 벽 {f['walls_continuing_in_line']} · C표기 "
                                  f"{'O' if f['has_column_mark'] else 'X'}")
    if t == "layer":
        cur = LAYER_ROLE_KO.get(f["current_role"], f["current_role"])
        if c["action"] == "change" and c.get("new_role"):
            act = f"{cur} → {LAYER_ROLE_KO.get(c['new_role'], c['new_role'])}"
        else:
            act = f"유지 ({cur})"
        near = ", ".join(f"{KIND_KO[k]}{v}" for k, v in f["nearest_layer_for_marks"].items()) or "-"
        info = (f"선 {f['lines']} · 평행쌍 {f['parallel_pairs']}(폭 {f['median_pair_width_mm']}) · "
                f"기둥형 {f['column_like_rects']} · 부재 {f['members_made_from_layer']} · 가까운표기 {near}")
        if f.get("member_marks_in_texts") is not None and f["texts"]:
            info = f"텍스트 {f['texts']} · 부재표기 {sum(f['member_marks_in_texts'].values())} · " + info
        if c.get("ai_note"):
            info = c["ai_note"] + " · " + info
        return f"레이어 {f['layer']}", act, info
    act = "기둥 추가" if c["action"] == "add" else "유지"
    pl = c.get("place", {})
    if c["action"] == "add" and pl:
        act += f" {pl['b']:.0f}×{pl['h']:.0f}" + (f" {pl['name']}" if pl.get("name") else "")
    bits = []
    if f["column_outline_found"]:
        bits.append("외곽선 " + f["column_outline_found"].split(" on ")[0])
    if f["column_mark"]:
        bits.append(f"표기 {f['column_mark']}")
    if f["grid_intersection_mm"] is not None:
        bits.append(f"그리드 {f['grid_intersection_mm']}mm")
    bits.append(f"교차거더 {f['girders_meeting_at_angle']}")
    if f["framed_into_girder_side"]:
        bits.append("거더옆면")
    return f["girder"] + " 끝", act, " · ".join(bits)


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
    if c["type"] == "add_col" and c["action"] == "add":
        nid = c["node"]
        if nid not in res.nodes or any(m.kind == "column" and m.node == nid for m in res.members):
            return None
        pl = c["place"]
        n = res.nodes[nid]
        if math.hypot(pl["x"] - n.x, pl["y"] - n.y) > 1.0:
            T.move_node(res, nid, pl["x"], pl["y"])
        m = T.add_column(res, n.x, n.y, pl["b"], pl["h"], pl["angle"], 1.0, name=pl.get("name", ""))
        if m is None:
            return None
        if pl.get("polygon"):
            m.polygon = [tuple(q) for q in pl["polygon"]]
        m.user, m.auto = False, True
        m.layer = "(2차 검토)"
        m.name_source = SRC_LABEL if pl.get("name") else "default"
        m.notes = [f"2차 검토: 거더 끝 기둥 추정 ({pl['src']}; {c.get('reason', '')})"]
        return f"#{m.id} 기둥 추가"
    return None
