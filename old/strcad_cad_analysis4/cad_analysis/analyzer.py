"""Analysis pipeline: drawing + layer roles → members with names."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from .classifier import classify_labels
from .dxf_loader import DrawingData
from .geometry import Params, extract_members, extract_columns, dist_point_seg, point_in_poly
from .topology import build_topology
from .postprocess import remove_wall_girders
from .model import (KIND_KO, AnalysisResult, Member, TextItem, SRC_LABEL, SRC_INFERRED, SRC_DEFAULT)

MEMBER_KINDS = ("column", "girder", "beam", "wall")


def _ang_diff_deg(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


def analyze(dd: DrawingData, roles: dict, client=None, params: Params | None = None,
            infer_names: bool = True, build_nodes: bool = True,
            wall_girder: bool = True, log=print) -> AnalysisResult:
    """roles: {layer: role}"""
    params = params or Params()
    res = AnalysisResult(layer_roles=dict(roles), source_file=dd.path)
    L = log

    # ---- 1. collect geometry per role ------------------------------------
    geo = {"column": {"polygons": [], "lines": [], "circles": []},
           "girder": {"segments": [], "arcs": []},
           "beam": {"segments": [], "arcs": []},
           "wall": {"segments": [], "arcs": []}}
    auto = {"segments": [], "arcs": [], "polygons": [], "lines": [], "circles": []}
    xs, ys = [], []
    col_cands = []          # closed outlines on wall/girder/beam layers (possible columns)
    for name, ld in dd.layers.items():
        role = roles.get(name, "ignore")
        if role in ("wall", "girder", "beam"):
            col_cands += [(pts, name) for pts in ld.polygons]
        if role == "column":
            geo["column"]["polygons"] += [(pts, name) for pts in ld.polygons]
            geo["column"]["lines"] += ld.line_segments
            geo["column"]["circles"] += [(cx, cy, r, name) for cx, cy, r in ld.circles]
        elif role in ("girder", "beam", "wall"):
            geo[role]["segments"] += ld.segments
            geo[role]["arcs"] += ld.arcs
        elif role == "grid":
            res.grid += ld.segments
        elif role == "auto":
            auto["segments"] += ld.segments
            auto["arcs"] += ld.arcs
            auto["polygons"] += [(pts, name) for pts in ld.polygons]
            auto["lines"] += ld.line_segments
            auto["circles"] += [(cx, cy, r, name) for cx, cy, r in ld.circles]
        if role in MEMBER_KINDS or role == "auto":
            res.background += ld.segments
            for s in ld.segments:
                xs += [s.x1, s.x2]; ys += [s.y1, s.y2]
    if xs:
        res.extents = (min(xs), min(ys), max(xs), max(ys))
    else:
        res.extents = dd.extents
    L(f"형상 수집: 기둥선 {len(geo['column']['lines'])}, 거더선 {len(geo['girder']['segments'])}, "
      f"보선 {len(geo['beam']['segments'])}, 벽선 {len(geo['wall']['segments'])}")

    # ---- 1b. labels (read first: column marks help find columns) ----------------------------------------------------------
    texts: list[TextItem] = []
    text_role = {}
    for name, ld in dd.layers.items():
        role = roles.get(name, "ignore")
        if role.endswith("_name") or role == "member_text":
            texts += ld.texts
            text_role[name] = role
    uniq = list(dict.fromkeys(t.text for t in texts))
    L(f"부재명 텍스트 {len(texts)}개 ({len(uniq)}종) 해석 중…")
    lab = classify_labels(uniq, client, log=L)

    items = []   # (TextItem, kind, name, w, d)
    for t in texts:
        role = text_role[t.layer]
        info = lab.get(t.text)
        if role == "member_text":
            if not info or info["type"] not in MEMBER_KINDS:
                continue
            kind = info["type"]
        else:
            kind = role[:-5]
            if info and info["type"] in MEMBER_KINDS and info["type"] != kind:
                # layer says one thing, text says another: trust the layer, keep a note
                pass
        if info:
            name, w, d = info["name"], info.get("width"), info.get("depth")
        else:
            s = t.text.strip()
            if len(s) > 12:
                continue
            name, w, d = s, None, None
        items.append((t, kind, name, w, d))
    res.texts = [it[0] for it in items]

    # ---- 2. columns on column layers; promote marked outlines on other layers
    cols = extract_columns(geo["column"]["polygons"], geo["column"]["lines"], geo["column"]["circles"], params)
    promoted = []
    if col_cands:
        cand_cols = extract_columns(col_cands, [], [], params)
        cand_cols = [c for c in cand_cols if c["b"] <= 2000 and c["h"] >= 250 and c["b"] / c["h"] <= 3.0]
        for t, kind, name, w, d in items:
            if kind != "column":
                continue
            if any(math.hypot(t.x - c["center"][0], t.y - c["center"][1]) <= max(1500.0, c["b"] * 1.5 + 4 * t.height)
                   for c in cols):
                continue
            best = None
            for c in cand_cols:
                dist = math.hypot(t.x - c["center"][0], t.y - c["center"][1])
                if dist <= max(1500.0, c["b"] * 1.5 + 4 * t.height) and (best is None or dist < best[0]):
                    best = (dist, c)
            if best:
                c = best[1]
                cand_cols.remove(c)
                c["note"] = f"'{c['layer']}' 레이어에 그려진 기둥 (인접 기둥표기로 판정)"
                promoted.append(c)
        if promoted:
            L(f"타 레이어에 그려진 기둥 {len(promoted)}개 발견 (기둥 표기 근거)")
    geo["column"]["precomputed"] = cols + promoted
    if auto["segments"] or auto["polygons"] or auto["circles"]:
        geo["auto"] = auto

    # ---- 3. geometry → members -------------------------------------------
    members = extract_members(geo, params, log=L)
    if promoted:
        def inside(m):
            if m.kind == "column" or m.curved:
                return False
            mx, my = (m.c1[0] + m.c2[0]) / 2, (m.c1[1] + m.c2[1]) / 2
            return any(point_in_poly(mx, my, c["polygon"]) for c in promoted)
        drop = [m for m in members if inside(m)]
        for m in drop:
            members.remove(m)
        if drop:
            L(f"기둥 내부의 허위 선부재 {len(drop)}개 제거")
    res.members = members

    # ---- 4. match labels to members ------------------------------------------
    by_kind = defaultdict(list)
    for m in members:
        by_kind[m.kind].append(m)
    assigned = defaultdict(list)    # member id -> [(name, w, d, dist)]
    unmatched = 0
    for t, kind, name, w, d in items:
        best = _match(t, kind, by_kind)
        cross = False
        if best is None and kind in ("girder", "beam"):
            other = "beam" if kind == "girder" else "girder"
            best = _match(t, other, by_kind)
            cross = best is not None
        if best is None:
            unmatched += 1
            continue
        m, dist = best
        if cross:
            m.notes.append(f"'{t.text}' 표기가 {'보' if kind == 'beam' else '거더'} 이름 레이어에 있으나 "
                           f"형상은 {'거더' if kind == 'beam' else '보'} 레이어")
        assigned[m.id].append((name, w, d, dist, t.text, kind))
    for m in members:
        got = assigned.get(m.id)
        if not got:
            continue
        names = Counter(g[0] for g in got)
        m.name = names.most_common(1)[0][0]
        m.name_source = SRC_LABEL
        m.labels = [g[4] for g in got]
        lk = Counter(g[5] for g in got if g[0] == m.name).most_common(1)[0][0]
        if m.auto and lk != m.kind and m.kind != "column" and lk != "column":
            m.notes.append(f"표기 '{m.name}'에 따라 {KIND_KO[m.kind]}→{KIND_KO[lk]}로 변경")
            m.kind = lk
        if len(names) > 1:
            m.notes.append("부재명 충돌: " + ", ".join(names))
        for g in got:
            if g[0] == m.name and (g[1] or g[2]):
                if g[2]:
                    m.depth = float(g[2])
                if g[1] and m.kind != "column" and abs(g[1] - m.width) > 20:
                    m.notes.append(f"표기폭 {g[1]} ≠ 도면폭 {m.width:.0f}")
                break
    L(f"부재명 매칭: {sum(1 for m in members if m.name)}개 부재 표기 확인, 미매칭 텍스트 {unmatched}개")

    # ---- 5. inference ---------------------------------------------------------
    if infer_names:
        n_inf = _infer_linear(members) + _infer_columns(members)
        L(f"인접/동일규격 부재로부터 이름 추정: {n_inf}개")

    # cleanup helper attrs
    for m in members:
        for a in ("_axis", "_gid"):
            if hasattr(m, a):
                delattr(m, a)
        if not m.name:
            m.name_source = SRC_DEFAULT
    # stable numbering: sort by kind then position
    order = {k: i for i, k in enumerate(MEMBER_KINDS)}
    members.sort(key=lambda m: (order[m.kind], -round(_ref_pt(m)[1] / 500), round(_ref_pt(m)[0] / 500)))
    for i, m in enumerate(members, 1):
        m.id = i
    if build_nodes:
        build_topology(res, log=L)
        if wall_girder:
            remove_wall_girders(res, log=L)
    cnt = Counter(m.kind for m in res.members)
    L("완료: " + ", ".join(f"{k} {cnt.get(k, 0)}" for k in MEMBER_KINDS))
    return res


def _ref_pt(m: Member):
    if m.kind == "column":
        return m.center
    return ((m.p1[0] + m.p2[0]) / 2, (m.p1[1] + m.p2[1]) / 2)


def _match(t: TextItem, kind: str, by_kind):
    best = None
    if kind == "column":
        for m in by_kind.get("column", []):
            cx, cy = m.center
            d = math.hypot(t.x - cx, t.y - cy)
            if m.polygon and point_in_poly(t.x, t.y, m.polygon):
                d = 0.0
            lim = max(1500.0, m.b * 1.5 + 4 * t.height)
            if d <= lim and (best is None or d < best[1]):
                best = (m, d)
        return best
    cands = list(by_kind.get(kind, []))
    for k in ("girder", "beam", "wall"):      # shape-recognised members: label may fix the type
        if k != kind:
            cands += [x for x in by_kind.get(k, []) if x.auto]
    for m in cands:
        if m.curved:
            a = m.arc
            rr = math.hypot(t.x - a["cx"], t.y - a["cy"])
            ang = math.atan2(t.y - a["cy"], t.x - a["cx"])
            while ang < a["a0"]:
                ang += 2 * math.pi
            if ang > a["a1"] + 0.05:
                continue
            d = abs(rr - a["r"])
        else:
            d, tt = dist_point_seg(t.x, t.y, *m.c1, *m.c2)
            if tt < -0.05 or tt > 1.05:
                continue
            if _ang_diff_deg(t.rot, m.angle) > 10:
                d += 800.0     # labels are normally written along the member
        lim = max(1500.0, m.width + 4 * t.height)
        if d <= lim and (best is None or d < best[1]):
            best = (m, d)
    return best


def _infer_linear(members):
    """Unlabeled span takes the name of the nearest labeled span on the same
    continuous line (same axis & width, sharing supports)."""
    groups = defaultdict(list)
    for m in members:
        if m.kind in ("girder", "beam") and hasattr(m, "_gid"):
            groups[m._gid].append(m)
    n = 0
    for g in groups.values():
        g.sort(key=lambda m: m._axis[5])
        # split into continuous chains (spans sharing a support centre)
        chains, cur = [], [g[0]]
        for a, b in zip(g, g[1:]):
            if abs(b._axis[5] - a._axis[6]) < 5.0:
                cur.append(b)
            else:
                chains.append(cur); cur = [b]
        chains.append(cur)
        for ch in chains:
            labeled = [i for i, m in enumerate(ch) if m.name_source == SRC_LABEL]
            if not labeled:
                continue
            for i, m in enumerate(ch):
                if m.name:
                    continue
                j = min(labeled, key=lambda k: abs(k - i))
                m.name = ch[j].name
                m.depth = m.depth or ch[j].depth
                m.name_source = SRC_INFERRED
                m.notes.append(f"인접 스팬({ch[j].name})에서 이름 추정")
                n += 1
    return n


def _infer_columns(members):
    cols = [m for m in members if m.kind == "column"]
    by_size = defaultdict(set)
    for c in cols:
        if c.name_source == SRC_LABEL:
            by_size[(round(c.b / 10), round(c.h / 10), c.shape)].add(c.name)
    n = 0
    for c in cols:
        if c.name:
            continue
        names = by_size.get((round(c.b / 10), round(c.h / 10), c.shape))
        if names and len(names) == 1:
            c.name = next(iter(names))
            c.name_source = SRC_INFERRED
            c.notes.append("동일 단면 기둥의 표기에서 추정")
            n += 1
    return n
