"""Architectural floor plan (건축평면도) → structural members.

When no structural drawing exists, columns and concrete walls can still be read
from the architectural plan:
  - layers: Ollama (or name rules) decide which layers hold columns, concrete
    walls, partitions, grid … ; doors/windows/furniture/finishes are ignored
  - columns: closed outlines / hatched squares on column layers, hatched compact
    shapes and rectangles formed by wall lines elsewhere
  - walls: parallel line pairs (thickness 90–800); thin partitions (< min_wall)
    are dropped unless partitions are included
  - names: columns get grid names (X2-Y3) when grid bubbles are readable
  - optional: girders are estimated between neighbouring columns on a grid line
Geometry is measured in code; the AI only judges meaning (layer roles).
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter

from .classifier import GRID_KEYS
from .dxf_loader import DrawingData
from .geometry import (Params, extract_members, extract_columns, min_area_rect, point_in_poly, dist_point_seg,
                       _find_rects, pair_edges)
from .model import AnalysisResult, Member, LAYER_ROLES, SRC_INFERRED, SRC_DEFAULT
from .ollama_client import OllamaError
from .topology import build_topology

ARCH_DEFAULTS = {"include_partitions": False, "min_wall": 150, "grid_names": True, "infer_girders": False,
                 "girder_width": 400, "context_lines": True}

COL_KEYS = ("COL", "기둥", "PILLAR")
CONC_KEYS = ("CONC", "RC", "콘크리트", "옹벽", "SHEAR", "내력", "STRUCT", "구조")
PART_KEYS = ("BLK", "BLOCK", "조적", "경량", "PART", "칸막이", "ALC", "GYP", "석고", "MAS", "BRICK", "벽돌", "LGS",
             "DRY", "비내력", "PANEL", "판넬")
WALL_KEYS = ("WALL", "벽")
IGNORE_ARCH = ("DOOR", "문", "WIN", "창", "FURN", "가구", "STAIR", "계단", "DIM", "치수", "TEXT", "문자", "TXT",
               "HATCH", "해치", "PATT", "FIN", "마감", "ELEV", "입면", "SAN", "위생", "LAND", "조경", "CAR", "주차",
               "PARK", "SYMB", "CURT", "GLAZ", "TITLE", "도곽", "FLOR", "바닥", "CEIL", "천장", "EQUIP", "IDEN",
               "ROOM", "실명", "AREA", "면적", "출력금지", "DEFPOINT", "LEVEL", "SECT", "단면", "NOTE", "MARK", "RAIL",
               "난간", "TOIL", "PLUMB", "ELEC", "MECH", "설비", "전기", "기계", "소방", "FIRE", "SPRINK", "LIGHT")
CONTEXT_KEYS = ("DOOR", "문", "WIN", "창", "STAIR", "계단", "CURT", "GLAZ", "RAIL", "난간")
GENERIC_RE = re.compile(r"^(0|LAYER\d*|\d+|도면층\d*|NEW.*|임시.*|TEMP.*)$", re.I)


def rule_arch_role(summary: dict, include_partitions=False) -> str:
    u = summary["name"].upper()
    ents = summary.get("entities", {})
    n_geo = sum(v for k, v in ents.items() if k in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "HATCH"))
    if any(k in u for k in GRID_KEYS) and "IDEN" not in u:
        return "grid"
    if any(k in u for k in IGNORE_ARCH):
        return "ignore"
    if any(k in u for k in COL_KEYS):
        return "column" if n_geo else "ignore"
    if any(k in u for k in PART_KEYS):
        return "wall" if include_partitions and n_geo else "ignore"
    if any(k in u for k in CONC_KEYS + WALL_KEYS):
        return "wall" if n_geo else "ignore"
    if GENERIC_RE.match(summary["name"].strip()) and n_geo >= 8:
        return "auto"                    # layer "0" etc.: let the shapes decide
    return "ignore"


ARCH_SYSTEM = """You classify CAD layers of a Korean ARCHITECTURAL floor plan (건축평면도) so that only the
STRUCTURAL elements are kept for a structural survey. Allowed roles:
- column: structural column outlines (기둥, A-COLS) - small closed squares/rectangles/circles, often solid-hatched
- wall: reinforced-concrete / bearing walls (콘크리트벽, RC벽, 내력벽, 옹벽, 코어벽, A-WALL-CONC) and generic wall
  layers (A-WALL, 벽체) that probably contain concrete walls
- auto: a layer mixing several things (e.g. layer "0") whose structural shapes should be found by geometry
- grid: grid / centre lines (A-GRID, 통심, CEN)
- ignore: everything else - partitions (조적, 블록, 경량벽, 칸막이, ALC, 석고보드){partition_note}, doors, windows,
  curtain walls, stairs, furniture, fixtures, finishes, floor patterns, dimensions, texts, room names, grid bubbles,
  landscape, title block, MEP, layers marked 출력금지
Use the layer name, entity counts (HATCH = filled areas, often concrete), closed polylines and median line length.
Return JSON: {"layers":[{"name":"<exact layer name>","role":"<role>"}]} covering every layer given."""

ARCH_ROLES = ("column", "wall", "auto", "grid", "ignore")
ARCH_SCHEMA = {"type": "object", "properties": {"layers": {"type": "array", "items": {
    "type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string", "enum": list(ARCH_ROLES)}},
    "required": ["name", "role"]}}}, "required": ["layers"]}


def classify_arch_layers(summaries: list, client=None, include_partitions=False, log=print):
    """→ {layer: (role, source)}"""
    out = {s["name"]: (rule_arch_role(s, include_partitions), "규칙") for s in summaries}
    if client:
        system = ARCH_SYSTEM.replace("{partition_note}", " (BUT map partitions to wall: the user wants them)"
                                     if include_partitions else "")
        compact = [{k: s.get(k) for k in ("name", "entities", "n_texts", "sample_texts", "median_line_length",
                                          "closed_polylines", "hatches")} for s in summaries]
        for i in range(0, len(compact), 40):
            batch = compact[i:i + 40]
            try:
                res = client.chat_json(system, json.dumps(batch, ensure_ascii=False), ARCH_SCHEMA)
            except OllamaError as e:
                log(f"[Ollama] 건축 레이어 분류 실패 → 규칙 사용: {e}")
                break
            names = {b["name"] for b in batch}
            n_ok = 0
            for item in res.get("layers", []) if isinstance(res, dict) else []:
                nm, role = item.get("name"), item.get("role")
                if nm in names and role in ARCH_ROLES:
                    out[nm] = (role, "AI"); n_ok += 1
            log(f"[Ollama] 건축 레이어 {len(batch)}개 중 {n_ok}개 AI 분류")
    if not any(r in ("column", "wall", "auto") for r, _ in out.values()):
        # nothing recognised: geometry-heavy layers go to shape recognition
        for s in summaries:
            ents = s.get("entities", {})
            n_geo = sum(v for k, v in ents.items() if k in ("LINE", "LWPOLYLINE", "POLYLINE", "HATCH"))
            u = s["name"].upper()
            if n_geo >= 20 and out[s["name"]][0] == "ignore" and not any(k in u for k in IGNORE_ARCH + GRID_KEYS):
                out[s["name"]] = ("auto", "자동")
    return out


# ============================================================================
def _poly_rect(pts):
    r = min_area_rect(pts)
    if not r:
        return None
    cx, cy, w, h, ang = r
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return cx, cy, w, h, ang, abs(a) / 2 / max(w * h, 1e-9)


def _col_dict(pts, layer, note):
    r = _poly_rect(pts)
    cx, cy, w, h, ang, fill = r
    return dict(center=(cx, cy), b=w, h=h, angle=math.degrees(ang), shape="rect" if fill > 0.93 else "polygon",
                polygon=[tuple(q) for q in pts], diameter=0.0, layer=layer, note=note, auto=True)


def _grid_points(grid):
    pts = []
    for i in range(len(grid)):
        a = grid[i]
        for j in range(i + 1, len(grid)):
            b = grid[j]
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


def analyze_arch(dd: DrawingData, roles: dict, client=None, params: Params | None = None, opts: dict | None = None,
                 log=print) -> AnalysisResult:
    o = dict(ARCH_DEFAULTS, **(opts or {}))
    p = params or Params()
    p.width_range = dict(p.width_range, wall=(80.0, 800.0))
    res = AnalysisResult(layer_roles=dict(roles), source_file=dd.path)
    res.kind = "arch"
    L = log

    col_polys, col_lines, col_circles = [], [], []
    wall_segs, wall_arcs = [], []
    other_polys = []           # (pts, layer, hatched) on wall/auto layers: possible columns
    auto_lines = []
    xs, ys = [], []
    for name, ld in dd.layers.items():
        role = roles.get(name, "ignore")
        u = name.upper()
        if role == "column":
            col_polys += [(q, name) for q in ld.polygons + ld.hatches]
            col_lines += ld.line_segments
            col_circles += [(cx, cy, r, name) for cx, cy, r in ld.circles]
        elif role in ("wall", "auto"):
            wall_segs += ld.segments
            wall_arcs += ld.arcs
            other_polys += [(q, name, True) for q in ld.hatches] + [(q, name, False) for q in ld.polygons]
            if role == "auto":
                auto_lines += ld.line_segments
                col_circles += [(cx, cy, r, name) for cx, cy, r in ld.circles if 250 <= 2 * r <= 1500]
        elif role == "grid":
            res.grid += ld.segments
        if role in ("column", "wall", "auto") or (o["context_lines"] and any(k in u for k in CONTEXT_KEYS)):
            res.background += ld.segments
        if role in ("column", "wall", "auto"):
            for s in ld.segments:
                xs += [s.x1, s.x2]; ys += [s.y1, s.y2]
    res.extents = (min(xs), min(ys), max(xs), max(ys)) if xs else dd.extents
    L(f"건축도면 형상: 기둥 레이어 도형 {len(col_polys)}, 벽 선 {len(wall_segs)}, 그리드 {len(res.grid)}")

    # ---- columns -------------------------------------------------------------
    cols = extract_columns(col_polys, col_lines, col_circles, p)
    cols = [c for c in cols if not c.get("note") or c["shape"] == "round" or c["h"] >= 200]
    gpts = _grid_points(res.grid)
    wall_hatched = []
    found = 0
    for pts, layer, hatched in other_polys:
        r = _poly_rect(pts)
        if not r:
            continue
        cx, cy, w, h, ang, fill = r
        if fill < 0.85:
            if hatched and 90 <= h <= 800 and w >= 3 * h:
                wall_hatched.append(pts)
            continue
        if hatched and 90 <= h <= 800 and w >= 2.5 * h:
            wall_hatched.append(pts)
            continue
        if not (250 <= h and w <= 1500 and w / max(h, 1) <= 2.0):
            continue
        near_grid = any(math.hypot(cx - gx, cy - gy) <= 300 for gx, gy in gpts)
        if not (hatched or near_grid):
            continue
        if any(math.dist((cx, cy), c["center"]) < 100 for c in cols):
            continue
        cols.append(_col_dict(pts, layer, "건축도면: " + ("해치된 " if hatched else "그리드 교점의 ") + "사각형 → 기둥"))
        found += 1
    # rectangles formed by wall lines (column drawn into the wall network)
    for pts in _find_rects(auto_lines or wall_segs, p):
        r = _poly_rect(pts)
        if not r:
            continue
        cx, cy, w, h, ang, fill = r
        if not (300 <= h and w <= 1200 and w / max(h, 1) <= 1.5):
            continue
        hatched = any(point_in_poly(cx, cy, q) for q, _l, hh in other_polys if hh)
        near_grid = any(math.hypot(cx - gx, cy - gy) <= 300 for gx, gy in gpts)
        if not (hatched or near_grid) or any(math.dist((cx, cy), c["center"]) < 100 for c in cols):
            continue
        cols.append(_col_dict(pts, "(벽선)", "건축도면: 벽선이 만든 사각형 → 기둥"))
        found += 1
    if found:
        L(f"벽/자동 레이어에서 기둥 {found}개 추가 판별 (해치·그리드 교점 근거)")

    # ---- walls -----------------------------------------------------------------
    min_wall = 0 if o["include_partitions"] else float(o["min_wall"])
    if min_wall > 80:
        # window frames / partitions: lines that pair up thinner than a concrete wall are removed first,
        # otherwise they bridge openings between wall pieces
        thin = pair_edges(wall_segs, 40.0, min_wall - 1.0, p)
        if thin:
            n0 = len(wall_segs)
            wall_segs = [sg for sg in wall_segs if not _in_band(sg, thin)]
            if n0 - len(wall_segs):
                L(f"창호·칸막이 선 {n0 - len(wall_segs)}개 제외 (선 간격 < {min_wall:.0f})")
    geo = {"column": {"polygons": [], "lines": [], "circles": [], "precomputed": cols},
           "girder": {"segments": [], "arcs": []}, "beam": {"segments": [], "arcs": []},
           "wall": {"segments": wall_segs, "arcs": wall_arcs}}
    members = extract_members(geo, p, log=L)
    thin = [m for m in members if m.kind == "wall" and m.width < min_wall]
    for m in thin:
        members.remove(m)
    if thin:
        L(f"두께 {min_wall:.0f} 미만 벽 {len(thin)}개 제외 (비내력 칸막이로 판단)")
    for m in members:
        if m.kind == "wall":
            hatched = any(point_in_poly((m.c1[0] + m.c2[0]) / 2, (m.c1[1] + m.c2[1]) / 2, q) for q in wall_hatched)
            m.notes.append("건축도면: " + ("해치된 콘크리트 벽" if hatched else f"벽선 쌍 (두께 {m.width:.0f})"))
        if m.kind == "column" and not m.notes:
            m.notes.append("건축도면: 기둥 레이어 외곽선")
    res.members = members

    # ---- names from the grid --------------------------------------------------------------------------------------------
    if o["grid_names"] and res.grid:
        n = _grid_names(dd, res, members)
        if n:
            L(f"그리드 이름으로 기둥 명명: {n}개")

    # ---- optional girders between neighbouring columns ----------------------------------------------------------------------
    if o["infer_girders"]:
        n = _infer_girders(res, float(o["girder_width"]))
        L(f"기둥열 사이 거더 추정: {n}개 (점선 이름 = 추정)")

    for m in res.members:
        for a in ("_axis", "_gid"):
            if hasattr(m, a):
                delattr(m, a)
        if not m.name:
            m.name_source = SRC_DEFAULT
    order = {"column": 0, "girder": 1, "beam": 2, "wall": 3}
    res.members.sort(key=lambda m: (order[m.kind], -round(_ref(m)[1] / 500), round(_ref(m)[0] / 500)))
    for i, m in enumerate(res.members, 1):
        m.id = i
    build_topology(res, log=L)
    cnt = Counter(m.kind for m in res.members)
    L("건축도면 분석 완료: 기둥 {} · 벽체 {}{}".format(cnt.get("column", 0), cnt.get("wall", 0),
                                                 f" · 추정 거더 {cnt['girder']}" if cnt.get("girder") else ""))
    return res


def _in_band(sg, pieces):
    L = sg.length or 1.0
    dx, dy = (sg.x2 - sg.x1) / L, (sg.y2 - sg.y1) / L
    for pc in pieces:
        if abs(dx * pc.uy - dy * pc.ux) > 0.02:
            continue
        ok = True
        for x, y in ((sg.x1, sg.y1), (sg.x2, sg.y2)):
            t = pc.ux * x + pc.uy * y
            o = pc.nx * x + pc.ny * y
            if not (pc.t0 - 2 <= t <= pc.t1 + 2 and abs(o - pc.off) <= pc.width / 2 + 2):
                ok = False
                break
        if ok:
            return True
    return False


def _ref(m):
    return m.center if m.kind == "column" else ((m.p1[0] + m.p2[0]) / 2, (m.p1[1] + m.p2[1]) / 2)


AXIS_RE = re.compile(r"^(?:[A-Z]{1,2}-?\d{1,2}[A-Z']?|[A-Z]{1,2}'?|\d{1,2}'?)$")


def _grid_names(dd, res, members):
    """Grid line → bubble text near one of its ends; column → '<X>-<Y>' of the two grid lines through it."""
    texts = [t for ld in dd.layers.values() for t in ld.texts if AXIS_RE.match(t.text.strip().upper())]
    label = {}
    for i, g in enumerate(res.grid):
        best = None
        L = g.length or 1.0
        ux, uy = (g.x2 - g.x1) / L, (g.y2 - g.y1) / L
        for t in texts:
            for (ex, ey), sgn in (((g.x1, g.y1), -1), ((g.x2, g.y2), 1)):
                vx, vy = t.x - ex, t.y - ey
                along = (vx * ux + vy * uy) * sgn            # beyond the end
                side = abs(vx * uy - vy * ux)
                if -300 <= along <= 2500 and side <= 700:
                    d = math.hypot(vx, vy)
                    if best is None or d < best[0]:
                        best = (d, t.text.strip().upper())
        if best:
            label[i] = (best[1], abs(ux) < abs(uy))          # (name, is_vertical)
    if not label:
        return 0
    n = 0
    for m in members:
        if m.kind != "column":
            continue
        hits = []
        for i, (nm, vert) in label.items():
            g = res.grid[i]
            d, t = dist_point_seg(*m.center, g.x1, g.y1, g.x2, g.y2)
            if d <= max(400.0, m.b / 2):
                hits.append((d, nm, vert))
        v = sorted(h for h in hits if h[2])
        hz = sorted(h for h in hits if not h[2])
        if v and hz:
            a, b = v[0][1], hz[0][1]
            if b.startswith("X") and not a.startswith("X"):
                a, b = b, a
            m.name = f"{a}-{b}"
            m.name_source = SRC_INFERRED
            m.notes.append(f"그리드 교점 이름 ({a}, {b})")
            n += 1
    return n


def _infer_girders(res, width):
    cols = [m for m in res.members if m.kind == "column"]
    walls = [m for m in res.members if m.kind == "wall"]
    nid = max((m.id for m in res.members), default=0) + 1
    added = 0
    seen = set()
    for a in cols:
        for ux, uy in ((1, 0), (0, 1)):
            best = None
            for b in cols:
                if b is a:
                    continue
                vx, vy = b.center[0] - a.center[0], b.center[1] - a.center[1]
                along = vx * ux + vy * uy
                side = abs(vx * uy - vy * ux)
                if 2000 <= along <= 12000 and side <= 150 and (best is None or along < best[0]):
                    best = (along, b)
            if not best:
                continue
            b = best[1]
            key = tuple(sorted((a.id, b.id)))
            if key in seen:
                continue
            seen.add(key)
            (x1, y1), (x2, y2) = a.center, b.center
            Lc = math.hypot(x2 - x1, y2 - y1)
            # a wall along this line already carries the floor → no girder needed
            cover = 0.0
            for w in walls:
                if w.curved:
                    continue
                d1, t1 = dist_point_seg(*w.p1, x1, y1, x2, y2)
                d2, t2 = dist_point_seg(*w.p2, x1, y1, x2, y2)
                if d1 <= 300 and d2 <= 300:
                    cover += abs(min(max(t2, 0), 1) - min(max(t1, 0), 1)) * Lc
            if cover >= 0.6 * Lc:
                continue
            ha, hb = a.b / 2 if ux else a.h / 2, b.b / 2 if ux else b.h / 2
            m = Member(nid, "girder", layer="(건축도면 추정)", width=width,
                       p1=(x1, y1), p2=(x2, y2),
                       c1=(x1 + ux * ha, y1 + uy * ha), c2=(x2 - ux * hb, y2 - uy * hb),
                       length_cc=Lc, length_clear=max(Lc - ha - hb, 0.0),
                       angle=math.degrees(math.atan2(uy, ux)), auto=True)
            m.notes.append("건축도면: 기둥열 사이 거더 추정 (도면에 없음, 확인 필요)")
            res.members.append(m)
            nid += 1
            added += 1
    return added
