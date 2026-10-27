"""Several plans in one DXF: find plan blocks and crop a drawing to a window."""
from __future__ import annotations

import math
from collections import deque, Counter

from .dxf_loader import DrawingData, LayerData


def _inside(x, y, r):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def crop(dd: DrawingData, rect) -> DrawingData:
    """New DrawingData with only entities whose middle lies inside rect=(x0,y0,x1,y1)."""
    x0, y0, x1, y1 = rect
    r = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    layers = {}
    for name, ld in dd.layers.items():
        nl = LayerData(name)
        nl.segments = [s for s in ld.segments if _inside((s.x1 + s.x2) / 2, (s.y1 + s.y2) / 2, r)]
        nl.line_segments = [s for s in ld.line_segments if _inside((s.x1 + s.x2) / 2, (s.y1 + s.y2) / 2, r)]
        nl.arcs = [a for a in ld.arcs if _inside(a.cx + a.r * math.cos((a.a0 + a.a1) / 2),
                                                  a.cy + a.r * math.sin((a.a0 + a.a1) / 2), r)]
        nl.circles = [c for c in ld.circles if _inside(c[0], c[1], r)]
        nl.polygons = [p for p in ld.polygons
                       if _inside(sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p), r)]
        nl.texts = [t for t in ld.texts if _inside(t.x, t.y, r)]
        nl.hatches = [p for p in ld.hatches
                      if _inside(sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p), r)]
        n = len(nl.segments) + len(nl.arcs) + len(nl.circles) + len(nl.texts) + len(nl.hatches)
        if n == 0:
            continue
        # entity counts for the classifier (approximate, by kind of primitive)
        nl.counts["LINE"] = len(nl.segments)
        if nl.arcs:
            nl.counts["ARC"] = len(nl.arcs)
        if nl.circles:
            nl.counts["CIRCLE"] = len(nl.circles)
        if nl.polygons:
            nl.counts["LWPOLYLINE"] = len(nl.polygons)
        if nl.texts:
            nl.counts["TEXT"] = len(nl.texts)
        if nl.hatches:
            nl.counts["HATCH"] = len(nl.hatches)
        layers[name] = nl
    return DrawingData(dd.path, layers, r, dd.insunits)


def all_segments(dd: DrawingData):
    for ld in dd.layers.values():
        yield from ld.segments


def robust_extents(dd: DrawingData, q=0.01):
    xs, ys = [], []
    for s in all_segments(dd):
        xs += [s.x1, s.x2]
        ys += [s.y1, s.y2]
    if not xs:
        return dd.extents
    xs.sort(); ys.sort()
    n = len(xs)
    i0, i1 = int(n * q), max(int(n * (1 - q)) - 1, 0)
    return xs[i0], ys[i0], xs[i1], ys[i1]


def detect_plans(dd: DrawingData, max_plans=16):
    """Connected clusters of drawing ink → candidate plan windows (largest first).
    Works on an unbounded cell grid, so stray far-away entities form their own
    small clusters instead of squashing everything."""
    ex = robust_extents(dd)
    span = max(ex[2] - ex[0], ex[3] - ex[1], 1.0)
    cell = span / 160.0
    cnt = Counter()
    long_cells = set()     # cells crossed by long lines (walls, grid lines) — they hold sparse plans together
    for name, ld in dd.layers.items():
        if name.upper().startswith("DEFPOINT"):
            continue
        for s in ld.segments:
            L = s.length
            n = min(int(L / cell) + 1, 400)
            is_long = 12 * cell <= L <= span * 0.6
            for i in range(n + 1):
                t = i / n
                c = (int(math.floor((s.x1 + (s.x2 - s.x1) * t) / cell)),
                     int(math.floor((s.y1 + (s.y2 - s.y1) * t) / cell)))
                cnt[c] += 1
                if is_long:
                    long_cells.add(c)
        for t in ld.texts:
            cnt[(int(math.floor(t.x / cell)), int(math.floor(t.y / cell)))] += 2
    # sparse cells (a lone stray line passing through) do not bridge plans
    occ = {c for c, n in cnt.items() if n >= 3} | long_cells
    # dilate by 2 cells so a plan and its dimensions/notes join
    dil = set()
    for gx, gy in occ:
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                dil.add((gx + dx, gy + dy))
    seen = set()
    comps = []
    for c in dil:
        if c in seen:
            continue
        q = deque([c]); seen.add(c)
        cells = []
        while q:
            a = q.popleft()
            cells.append(a)
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                b = (a[0] + d[0], a[1] + d[1])
                if b in dil and b not in seen:
                    seen.add(b); q.append(b)
        gx = [x for x, _ in cells]; gy = [y for _, y in cells]
        comps.append((len(cells), (min(gx) * cell, min(gy) * cell, (max(gx) + 1) * cell, (max(gy) + 1) * cell)))
    # fragments of one plan (sparse drawings: big empty rooms) have overlapping boxes → merge them
    pad = 3 * cell
    merged = True
    while merged and len(comps) > 1:
        merged = False
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                (na, a), (nb, b) = comps[i], comps[j]
                if a[0] - pad <= b[2] and b[0] - pad <= a[2] and a[1] - pad <= b[3] and b[1] - pad <= a[3]:
                    comps[i] = (na + nb, (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])))
                    del comps[j]
                    merged = True
                    break
            if merged:
                break
    comps.sort(key=lambda c: -c[0])
    if not comps:
        return []
    big = comps[0][0]
    rects = [r for n, r in comps if n >= max(60, big * 0.05)][:max_plans]
    # widen each plan a little (grid bubbles, dimensions) without reaching into a neighbouring plan
    out = []
    for i, r in enumerate(rects):
        e = 0.1 * max(r[2] - r[0], r[3] - r[1])
        for j, q in enumerate(rects):
            if i != j:
                gx = max(q[0] - r[2], r[0] - q[2], 0.0)
                gy = max(q[1] - r[3], r[1] - q[3], 0.0)
                e = min(e, max(gx, gy) / 2.0)
        out.append((r[0] - e, r[1] - e, r[2] + e, r[3] + e))
    return out
