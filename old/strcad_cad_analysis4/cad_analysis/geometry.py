"""Deterministic geometry extraction.

* Columns  : closed outlines (LINE loops / closed polylines / circles) → centre point + b×h
* Beams, girders, walls : pairs of parallel edge lines → centreline + width,
  split into spans at supports (columns, girders, walls).
* Concentric arc pairs → curved centreline.

Nothing here guesses numbers: every coordinate and dimension comes from the
drawing geometry.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .model import Member, Segment, Arc

DEG = math.pi / 180.0


@dataclass
class Params:
    width_range: dict = field(default_factory=lambda: {
        "girder": (150.0, 2500.0),
        "beam": (100.0, 2000.0),
        "wall": (80.0, 1500.0),
    })
    ang_tol: float = 1.0 * DEG       # parallel tolerance for edge pairing
    min_overlap: float = 50.0        # mm, minimum overlap of paired edges
    group_ang_tol: float = 0.5 * DEG
    group_off_tol: float = 25.0      # mm, collinear centreline tolerance
    group_w_tol: float = 25.0        # mm, same width tolerance
    small_gap: float = 60.0          # gaps smaller than this are always merged
    support_tol: float = 60.0        # end-to-support-face tolerance
    min_span: float = 150.0          # drop members shorter than this (clear length)
    col_snap: float = 3.0            # endpoint snap for column loops
    col_min: float = 150.0
    col_max: float = 4000.0


# ============================================================================
#  Small helpers
# ============================================================================
def _norm_angle(dx, dy):
    a = math.atan2(dy, dx)
    if a < 0:
        a += math.pi
    if a >= math.pi:
        a -= math.pi
    return a


def _ang_diff(a, b):
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def _merge_intervals(iv, gap=0.0):
    iv = sorted((a, b) for a, b in iv if b > a)
    out = []
    for a, b in iv:
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(x) for x in out]


def _subtract(iv, covered):
    """interval iv minus union(covered) → list of intervals"""
    res = [iv]
    for ca, cb in covered:
        nxt = []
        for a, b in res:
            if cb <= a or ca >= b:
                nxt.append((a, b))
            else:
                if ca > a:
                    nxt.append((a, ca))
                if cb < b:
                    nxt.append((cb, b))
        res = nxt
    return res


def _cover_len(ivs, a, b):
    s = 0.0
    for x, y in ivs:
        lo, hi = max(a, x), min(b, y)
        if hi > lo:
            s += hi - lo
    return s


def _poly_area_centroid(pts):
    a = cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cr = x1 * y2 - x2 * y1
        a += cr
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    a *= 0.5
    if abs(a) < 1e-9:
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return 0.0, (sum(xs) / n, sum(ys) / n)
    return abs(a), (cx / (6 * a), cy / (6 * a))


def _convex_hull(pts):
    pts = sorted(set((round(x, 3), round(y, 3)) for x, y in pts))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def min_area_rect(pts):
    """→ (cx, cy, long_side, short_side, angle_of_long_side_rad[0,pi))"""
    hull = _convex_hull(pts)
    if len(hull) < 3:
        return None
    best = None
    for i in range(len(hull)):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % len(hull)]
        th = math.atan2(y2 - y1, x2 - x1)
        c, s = math.cos(th), math.sin(th)
        us = [x * c + y * s for x, y in hull]
        vs = [-x * s + y * c for x, y in hull]
        w, h = max(us) - min(us), max(vs) - min(vs)
        area = w * h
        if best is None or area < best[0] - 1e-6:
            um, vm = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
            cx, cy = um * c - vm * s, um * s + vm * c
            best = (area, cx, cy, w, h, th)
    _, cx, cy, w, h, th = best
    if h > w:
        w, h = h, w
        th += math.pi / 2
    return cx, cy, w, h, _norm_angle(math.cos(th), math.sin(th))


def point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xin = (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi
            if x < xin:
                inside = not inside
        j = i
    return inside


# ============================================================================
#  Columns
# ============================================================================
def extract_columns(polygons, line_segments, circles, p: Params, layer_of=None):
    """Return list of dicts {center, b, h, angle, shape, polygon, diameter, layer}"""
    outs = []

    def add_poly(pts, layer, from_loop=True):
        r = min_area_rect(pts)
        if not r:
            return
        cx, cy, w, h, ang = r
        if w < p.col_min * 0.5 or w > p.col_max:
            return
        area, cen = _poly_area_centroid(pts)
        rect_area = w * h
        shape = "rect" if rect_area > 0 and area / rect_area > 0.93 else "polygon"
        if shape == "polygon":
            cx, cy = cen
        outs.append(dict(center=(cx, cy), b=w, h=h, angle=ang / DEG, shape=shape,
                         polygon=[tuple(q) for q in pts], diameter=0.0, layer=layer))

    for pts, layer in polygons:
        add_poly(pts, layer)

    # LINE loops → union find on snapped endpoints
    snap = p.col_snap
    grid = {}
    verts = []

    def vid(x, y):
        k = (round(x / snap), round(y / snap))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                v = grid.get((k[0] + dx, k[1] + dy))
                if v is not None and abs(verts[v][0] - x) <= snap and abs(verts[v][1] - y) <= snap:
                    return v
        verts.append((x, y))
        grid[k] = len(verts) - 1
        return len(verts) - 1

    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    edges = []
    for s in line_segments:
        a, b = vid(s.x1, s.y1), vid(s.x2, s.y2)
        if a == b:
            continue
        edges.append((a, b, s.layer))
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comps = defaultdict(list)
    for a, b, lay in edges:
        comps[find(a)].append((a, b, lay))
    for _root, es in comps.items():
        if len(es) < 3:
            continue
        deg = defaultdict(list)
        for a, b, _ in es:
            deg[a].append(b); deg[b].append(a)
        layer = es[0][2]
        if all(len(v) == 2 for v in deg.values()) and len(deg) == len(es):
            # ordered loop
            start = es[0][0]
            loop = [start]
            prev, cur = None, start
            while True:
                nb = deg[cur]
                nxt = nb[0] if nb[0] != prev else nb[1]
                if nxt == start:
                    break
                loop.append(nxt)
                prev, cur = cur, nxt
                if len(loop) > len(deg):
                    break
            add_poly([verts[i] for i in loop], layer)
        else:
            # open / branched outline: use hull of its points (flag as polygon)
            pts = [verts[i] for i in deg]
            r = min_area_rect(pts)
            if r and p.col_min * 0.5 <= r[2] <= p.col_max:
                cx, cy, w, h, ang = r
                outs.append(dict(center=(cx, cy), b=w, h=h, angle=ang / DEG, shape="rect",
                                 polygon=_convex_hull(pts), diameter=0.0, layer=layer,
                                 note="외곽선이 닫혀있지 않음(외접사각형 사용)"))

    for (cx, cy, r, layer) in circles:
        if p.col_min * 0.5 <= 2 * r <= p.col_max:
            poly = [(cx + r * math.cos(t * DEG), cy + r * math.sin(t * DEG)) for t in range(0, 360, 15)]
            outs.append(dict(center=(cx, cy), b=2 * r, h=2 * r, angle=0.0, shape="round",
                             polygon=poly, diameter=2 * r, layer=layer))

    # de-duplicate (same outline drawn twice)
    uniq = []
    for c in outs:
        if any(math.dist(c["center"], u["center"]) < 5 and abs(c["b"] - u["b"]) < 5 for u in uniq):
            continue
        uniq.append(c)
    return uniq


# ============================================================================
#  Linear members: edge pairing
# ============================================================================
@dataclass
class _Ln:
    s: Segment
    ang: float
    ux: float
    uy: float
    nx: float
    ny: float
    off: float     # n·p
    t0: float      # u·p1
    t1: float      # u·p2 (t1 > t0)
    layer: str


def _prep(segs):
    out = []
    for s in segs:
        L = s.length
        if L < 1.0:
            continue
        ang = _norm_angle(s.x2 - s.x1, s.y2 - s.y1)
        ux, uy = math.cos(ang), math.sin(ang)
        nx, ny = -uy, ux
        ta = ux * s.x1 + uy * s.y1
        tb = ux * s.x2 + uy * s.y2
        out.append(_Ln(s, ang, ux, uy, nx, ny, nx * s.x1 + ny * s.y1, min(ta, tb), max(ta, tb), s.layer))
    return out


@dataclass
class Piece:
    """A centreline piece produced by one edge pair."""
    ang: float
    ux: float
    uy: float
    nx: float
    ny: float
    off: float       # centreline offset (n·p)
    t0: float
    t1: float
    width: float
    layer: str


def pair_edges(segs, wmin, wmax, p: Params):
    lns = _prep(segs)
    n = len(lns)
    if n < 2:
        return []
    # spatial hash on bbox
    cell = max(wmax * 2, 2000.0)
    index = defaultdict(list)
    for i, l in enumerate(lns):
        s = l.s
        x0, x1 = sorted((s.x1, s.x2)); y0, y1 = sorted((s.y1, s.y2))
        for gx in range(int(math.floor(x0 / cell)), int(math.floor(x1 / cell)) + 1):
            for gy in range(int(math.floor(y0 / cell)), int(math.floor(y1 / cell)) + 1):
                index[(gx, gy)].append(i)

    def neighbours(i):
        s = lns[i].s
        x0, x1 = sorted((s.x1, s.x2)); y0, y1 = sorted((s.y1, s.y2))
        res = set()
        for gx in range(int(math.floor((x0 - wmax) / cell)), int(math.floor((x1 + wmax) / cell)) + 1):
            for gy in range(int(math.floor((y0 - wmax) / cell)), int(math.floor((y1 + wmax) / cell)) + 1):
                res.update(index.get((gx, gy), ()))
        res.discard(i)
        return res

    # 1) all candidate pairs (i<j), parallel, within width range, overlapping
    cands = []
    for i in range(n):
        li = lns[i]
        for j in neighbours(i):
            if j <= i:
                continue
            lj = lns[j]
            if _ang_diff(li.ang, lj.ang) > p.ang_tol:
                continue
            mx, my = (lj.s.x1 + lj.s.x2) / 2, (lj.s.y1 + lj.s.y2) / 2
            d = li.nx * mx + li.ny * my - li.off
            if not (wmin <= abs(d) <= wmax):
                continue
            ta = li.ux * lj.s.x1 + li.uy * lj.s.y1
            tb = li.ux * lj.s.x2 + li.uy * lj.s.y2
            a, b = max(li.t0, min(ta, tb)), min(li.t1, max(ta, tb))
            if b - a < p.min_overlap:
                continue
            cands.append((abs(d), i, j, d, (a, b)))
    # 2) greedy, narrowest first: each portion of an edge line is used once.
    #    (stops a line pairing with its own member AND the neighbour across a gap)
    cands.sort(key=lambda c: c[0])
    used = [[] for _ in range(n)]          # intervals in each line's own t
    pieces = []
    for w, i, j, d, iv in cands:
        li, lj = lns[i], lns[j]
        # same-direction check: map i-axis t to j-axis t (sign of u_i·u_j)
        sgn = 1.0 if (li.ux * lj.ux + li.uy * lj.uy) > 0 else -1.0
        # j own t for a point on i-line at param t:  t_j = sgn*t + k
        k = (lj.ux * li.nx + lj.uy * li.ny) * li.off
        def to_j(t):
            return sgn * t + k
        def to_i(tj):
            return (tj - k) * sgn
        rem = _subtract(iv, used[i])
        out = []
        for a, b in rem:
            ja, jb = sorted((to_j(a), to_j(b)))
            for c, e in _subtract((ja, jb), used[j]):
                ia, ib = sorted((to_i(c), to_i(e)))
                if ib - ia >= p.min_overlap:
                    out.append((ia, ib))
        if not out:
            continue
        dj1 = li.nx * lj.s.x1 + li.ny * lj.s.y1 - li.off
        dj2 = li.nx * lj.s.x2 + li.ny * lj.s.y2 - li.off
        dm = (dj1 + dj2) / 2
        off = li.off + dm / 2
        for a, b in out:
            pieces.append(Piece(li.ang, li.ux, li.uy, li.nx, li.ny, off, a, b, abs(dm), li.layer))
            used[i] = _merge_intervals(used[i] + [(a, b)])
            ja, jb = sorted((to_j(a), to_j(b)))
            used[j] = _merge_intervals(used[j] + [(ja, jb)])
    return pieces


def pair_arcs(arcs, wmin, wmax, p: Params):
    """Concentric arc pairs → list of dict(cx, cy, r, a0, a1, width, layer)"""
    out = []
    used = set()
    for i, a in enumerate(arcs):
        best = None
        for j, b in enumerate(arcs):
            if i == j or (min(i, j), max(i, j)) in used:
                continue
            if math.hypot(a.cx - b.cx, a.cy - b.cy) > 5.0:
                continue
            dr = abs(a.r - b.r)
            if not (wmin <= dr <= wmax):
                continue
            # angular overlap (normalise b into a's frame)
            b0, b1 = b.a0, b.a1
            while b0 < a.a0 - math.pi:
                b0 += 2 * math.pi; b1 += 2 * math.pi
            while b0 > a.a0 + math.pi:
                b0 -= 2 * math.pi; b1 -= 2 * math.pi
            lo, hi = max(a.a0, b0), min(a.a1, b1)
            if hi - lo <= 0:
                continue
            if best is None or dr < best[0]:
                best = (dr, j, lo, hi, b)
        if best:
            dr, j, lo, hi, b = best
            used.add((min(i, j), max(i, j)))
            r = (a.r + b.r) / 2
            if r * (hi - lo) >= p.min_span:
                out.append(dict(cx=a.cx, cy=a.cy, r=r, a0=lo, a1=hi, width=dr, layer=a.layer))
    return out


# ============================================================================
#  Grouping & span splitting
# ============================================================================
@dataclass
class Group:
    ang: float
    ux: float
    uy: float
    nx: float
    ny: float
    off: float
    width: float
    layer: str
    kind: str
    ivs: list = field(default_factory=list)
    auto: bool = False
    reason: str = ""

    def pt(self, t):
        return (self.ux * t + self.nx * self.off, self.uy * t + self.ny * self.off)


def group_pieces(pieces, kind, p: Params):
    groups: list[Group] = []
    buckets = defaultdict(list)   # angle bucket (deg int) -> group idx
    for pc in pieces:
        bk = int(round(pc.ang / DEG)) % 180
        found = None
        for b in (bk - 1, bk, bk + 1):
            for gi in buckets[b % 180]:
                g = groups[gi]
                if _ang_diff(g.ang, pc.ang) > p.group_ang_tol:
                    continue
                # piece centre offset measured with group normal
                tm = (pc.t0 + pc.t1) / 2
                mx = pc.ux * tm + pc.nx * pc.off
                my = pc.uy * tm + pc.ny * pc.off
                if abs(g.nx * mx + g.ny * my - g.off) > p.group_off_tol:
                    continue
                if abs(g.width - pc.width) > p.group_w_tol:
                    continue
                found = g
                break
            if found:
                break
        # re-project the piece onto the group (or its own) axis
        if found is None:
            found = Group(pc.ang, pc.ux, pc.uy, pc.nx, pc.ny, pc.off, pc.width, pc.layer, kind)
            groups.append(found)
            buckets[bk].append(len(groups) - 1)
        g = found
        ts = []
        for t in (pc.t0, pc.t1):
            x = pc.ux * t + pc.nx * pc.off
            y = pc.uy * t + pc.ny * pc.off
            ts.append(g.ux * x + g.uy * y)
        g.ivs.append((min(ts), max(ts)))
    for g in groups:
        g.ivs = _merge_intervals(g.ivs, gap=0.5)
    return groups


@dataclass
class _Support:
    a: float
    b: float
    c: float
    prio: int     # 0 column, 1 girder/wall, 2 beam


def _supports_for(g: Group, columns, strips, ext):
    """Support intervals along group axis."""
    lo = g.ivs[0][0] - ext
    hi = g.ivs[-1][1] + ext
    out = []
    hw = g.width / 2
    for col in columns:
        poly = col["polygon"]
        ns = [g.nx * x + g.ny * y for x, y in poly]
        if not (min(ns) - hw * 0.5 <= g.off <= max(ns) + hw * 0.5):
            continue
        ts = [g.ux * x + g.uy * y for x, y in poly]
        a, b = min(ts), max(ts)
        if b < lo or a > hi:
            continue
        cx, cy = col["center"]
        c = g.ux * cx + g.uy * cy
        # column narrower in this direction? clip to polygon strip at axis
        out.append(_Support(a, b, c, 0))
    for st, prio in strips:
        if st is g:
            continue
        sa = _ang_diff(st.ang, g.ang)
        if sa < 10 * DEG:
            continue
        # intersection of axes: g.pt(t) on st axis: st.n·p = st.off
        den = st.nx * g.ux + st.ny * g.uy
        if abs(den) < 1e-9:
            continue
        t = (st.off - (st.nx * g.nx + st.ny * g.ny) * g.off) / den
        if t < lo or t > hi:
            continue
        x, y = g.pt(t)
        s = st.ux * x + st.uy * y
        tol = hw / max(math.sin(sa), 0.2) + 50
        if not any(a - tol <= s <= b + tol for a, b in st.ivs):
            continue
        half = (st.width / 2) / max(math.sin(sa), 0.2)
        out.append(_Support(t - half, t + half, t, prio))
    # merge overlapping supports, keep highest priority centre
    out.sort(key=lambda s: s.a)
    merged = []
    for s in out:
        if merged and s.a <= merged[-1].b:
            m = merged[-1]
            if s.prio < m.prio:
                m.c, m.prio = s.c, s.prio
            m.b = max(m.b, s.b)
            m.a = min(m.a, s.a)
        else:
            merged.append(_Support(s.a, s.b, s.c, s.prio))
    return merged


def split_group(g: Group, supports, split_at_supports: bool, p: Params):
    """→ list of span tuples (t_cc0, t_cc1, t_cl0, t_cl1)."""
    ivs = _merge_intervals(g.ivs, gap=p.small_gap)
    # 1) runs: break at gaps not explained by a support
    runs = [[ivs[0]]]
    for iv in ivs[1:]:
        prev_end = runs[-1][-1][1]
        gap_mid = (prev_end + iv[0]) / 2
        explained = any(s.a - p.support_tol <= gap_mid <= s.b + p.support_tol for s in supports)
        if explained:
            runs[-1].append(iv)
        else:
            runs.append([iv])

    spans = []
    for run in runs:
        s0, s1 = run[0][0], run[-1][1]
        tol = p.support_tol
        start = next((s for s in supports if s.a - tol <= s0 <= s.b + tol), None)
        end = next((s for s in supports if s.a - tol <= s1 <= s.b + tol), None)
        if start is end and start is not None:      # whole run inside one support
            continue
        c_start = start.c if start else s0
        c_end = end.c if end else s1
        if not split_at_supports:
            spans.append((c_start, c_end, s0, s1))
            continue
        nodes = [(c_start, c_start, start.b if start else s0)]   # (centre, face_a, face_b)
        for s in supports:
            if s is not start and s is not end and s0 + tol < s.c < s1 - tol:
                nodes.append((s.c, s.a, s.b))
        nodes.append((c_end, end.a if end else s1, c_end))
        nodes.sort(key=lambda x: x[0])
        for k in range(len(nodes) - 1):
            c0, _a0, b0 = nodes[k]
            c1, a1, _b1 = nodes[k + 1]
            cl0, cl1 = max(b0, s0), min(a1, s1)
            if cl1 - cl0 < p.min_span:
                continue
            cov = _cover_len(run, cl0, cl1) / (cl1 - cl0)
            if cov < 0.5:
                continue
            spans.append((c0, c1, cl0, cl1))
    return spans


# ============================================================================
#  Main entry
# ============================================================================
def extract_members(geo: dict, p: Params | None = None, log=None):
    """geo = {
        'column': {'polygons': [(pts, layer)], 'lines': [Segment], 'circles': [(cx,cy,r,layer)]},
        'girder'|'beam'|'wall': {'segments': [Segment], 'arcs': [Arc]}
    }"""
    p = p or Params()
    log = log or (lambda *_: None)
    members = []
    nid = 1

    cols = geo["column"].get("precomputed")
    if cols is None:
        cols = extract_columns(geo["column"]["polygons"], geo["column"]["lines"], geo["column"]["circles"], p)
    auto = geo.get("auto")
    if auto:
        acols = auto_columns(auto, cols, p)
        log(f"형상판별: 닫힌 사각형/원 → 기둥 {len(acols)}개")
        cols = cols + acols
    log(f"기둥 {len(cols)}개 검출")
    for c in cols:
        m = Member(nid, "column", layer=c["layer"], center=c["center"], b=c["b"], h=c["h"],
                   angle=c["angle"], shape=c["shape"], polygon=c["polygon"], diameter=c["diameter"],
                   auto=bool(c.get("auto")))
        if c.get("note"):
            m.notes.append(c["note"])
        members.append(m); nid += 1

    groups = {}
    arcs = {}
    for kind in ("girder", "beam", "wall"):
        wmin, wmax = p.width_range[kind]
        pcs = _drop_inside_columns(pair_edges(geo[kind]["segments"], wmin, wmax, p), cols)
        groups[kind] = group_pieces(pcs, kind, p)
        arcs[kind] = pair_arcs(geo[kind]["arcs"], wmin, wmax, p)
        log(f"{kind}: 평행선 쌍 {len(pcs)}개 → 축선 그룹 {len(groups[kind])}개, 곡선 {len(arcs[kind])}개")
    if auto:
        pcs = _drop_inside_columns(pair_edges(auto["segments"], 80.0, 2500.0, p), cols)
        ag = group_pieces(pcs, "auto", p)
        classify_auto_groups(ag, cols, groups, p)
        cnt = {}
        for g in ag:
            groups[g.kind].append(g)
            cnt[g.kind] = cnt.get(g.kind, 0) + 1
        for a in pair_arcs(auto["arcs"], 80.0, 2500.0, p):
            k = "wall" if a["width"] <= 350 else "girder"
            a["auto"] = True
            arcs[k].append(a)
        log("형상판별: 평행선 쌍 → " + ", ".join(f"{k} {v}" for k, v in cnt.items()))

    support_strips = {
        "girder": [(g, 1) for g in groups["girder"]] + [(g, 1) for g in groups["wall"]],
        "beam": [(g, 1) for g in groups["girder"]] + [(g, 1) for g in groups["wall"]]
                + [(g, 2) for g in groups["beam"]],
        "wall": [(g, 1) for g in groups["wall"]] + [(g, 1) for g in groups["girder"]],
    }
    for kind in ("girder", "beam", "wall"):
        for g in groups[kind]:
            sup = _supports_for(g, cols, support_strips[kind], ext=max(1500.0, g.width * 3))
            spans = split_group(g, sup, split_at_supports=(kind != "wall"), p=p)
            for (c0, c1, l0, l1) in spans:
                if l1 - l0 < max(p.min_span, g.width * (0.9 if kind == "wall" else 0.0)):
                    continue
                m = Member(nid, kind, layer=g.layer, width=round(g.width, 1),
                           p1=g.pt(c0), p2=g.pt(c1), c1=g.pt(l0), c2=g.pt(l1),
                           length_cc=abs(c1 - c0), length_clear=abs(l1 - l0),
                           angle=g.ang / DEG)
                if getattr(g, "auto", False):
                    m.auto = True
                    m.notes.append("형상으로 종류 판별: " + g.reason)
                m._axis = (g.ux, g.uy, g.nx, g.ny, g.off, c0, c1)   # for neighbour inference
                m._gid = id(g)
                members.append(m); nid += 1
        for a in arcs[kind]:
            m = Member(nid, kind, layer=a["layer"], width=round(a["width"], 1), curved=True,
                       arc={k: a[k] for k in ("cx", "cy", "r", "a0", "a1")})
            r = a["r"]
            m.p1 = m.c1 = (a["cx"] + r * math.cos(a["a0"]), a["cy"] + r * math.sin(a["a0"]))
            m.p2 = m.c2 = (a["cx"] + r * math.cos(a["a1"]), a["cy"] + r * math.sin(a["a1"]))
            m.length_cc = m.length_clear = r * (a["a1"] - a["a0"])
            m.notes.append(f"곡선부재 R={r:.0f}")
            if a.get("auto"):
                m.auto = True
            members.append(m); nid += 1
    return members


# ============================================================================
#  Shape-based recognition (layer role "auto")
# ============================================================================
def _drop_inside_columns(pieces, cols):
    """Edge pairs formed by a column's own outline are not members."""
    if not cols:
        return pieces
    out = []
    for pc in pieces:
        tm = (pc.t0 + pc.t1) / 2
        x = pc.ux * tm + pc.nx * pc.off
        y = pc.uy * tm + pc.ny * pc.off
        L = pc.t1 - pc.t0
        if any(L <= c["b"] + 60 and abs(x - c["center"][0]) <= c["b"] and abs(y - c["center"][1]) <= c["b"]
               and point_in_poly(x, y, c["polygon"]) for c in cols):
            continue
        out.append(pc)
    return out


def _find_rects(lines, p: Params):
    """Small rectangles inside a line network (column outlines touched by
    other lines, so they are not isolated loops)."""
    snap = p.col_snap
    grid, verts, adj = {}, [], defaultdict(set)

    def vid(x, y):
        k = (round(x / snap), round(y / snap))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                v = grid.get((k[0] + dx, k[1] + dy))
                if v is not None:
                    return v
        verts.append((x, y))
        grid[k] = len(verts) - 1
        return len(verts) - 1
    for s in lines:
        if not (p.col_min * 0.8 <= s.length <= 1600):
            continue
        a, b = vid(s.x1, s.y1), vid(s.x2, s.y2)
        if a != b:
            adj[a].add(b); adj[b].add(a)
    found = {}
    for a, nb in adj.items():
        nb = list(nb)
        ax, ay = verts[a]
        for i in range(len(nb)):
            for j in range(i + 1, len(nb)):
                b, c = nb[i], nb[j]
                bx, by = verts[b][0] - ax, verts[b][1] - ay
                cx, cy = verts[c][0] - ax, verts[c][1] - ay
                lb, lc = math.hypot(bx, by), math.hypot(cx, cy)
                if abs(bx * cx + by * cy) > 0.02 * lb * lc:      # not perpendicular
                    continue
                dx, dy = ax + bx + cx, ay + by + cy
                k = (round(dx / snap), round(dy / snap))
                d = None
                for ex in (-1, 0, 1):
                    for ey in (-1, 0, 1):
                        d = grid.get((k[0] + ex, k[1] + ey), d)
                if d is None or d not in adj[b] or d not in adj[c]:
                    continue
                key = tuple(sorted((a, b, c, d)))
                found[key] = [verts[a], verts[b], verts[d], verts[c]]
    return list(found.values())


def auto_columns(auto, cols, p: Params):
    """Columns among unlabeled-layer geometry: compact closed shapes."""
    cand = extract_columns(auto["polygons"], auto["lines"], auto["circles"], p)
    cand += extract_columns([(r, auto["lines"][0].layer if auto["lines"] else "") for r in
                             _find_rects(auto["lines"], p)], [], [], p)
    out = []
    for c in cand:
        if c.get("note"):                      # open outline (hull) — not reliable here
            continue
        if c["shape"] != "round":
            if not (200 <= c["h"] and c["b"] <= 1600 and c["b"] / max(c["h"], 1) <= 3.0):
                continue
        if any(math.dist(c["center"], o["center"]) < 50 for o in cols + out):
            continue
        c["auto"] = True
        c["note"] = "형상으로 기둥 판별 (닫힌 " + ("원" if c["shape"] == "round" else "사각형") + ")"
        out.append(c)
    return out


def classify_auto_groups(ag, cols, groups, p: Params):
    """Decide girder / beam / wall for edge-pair groups from shape + connectivity.
    pass 1: thickness and columns at both ends; pass 2: ends on girders → beam."""
    def col_hits(g):
        sup = _supports_for(g, cols, [], ext=max(1500.0, g.width * 3))
        s0, s1 = g.ivs[0][0], g.ivs[-1][1]
        return sum(1 for s in sup if s.b >= s0 - p.support_tol and s.a <= s1 + p.support_tol)
    pending = []
    for g in ag:
        g.auto = True
        n = col_hits(g)
        w = g.width
        if w < 150:
            g.kind, g.reason = "wall", f"두께 {w:.0f} < 150"
        elif n >= 2 and w >= 300:
            g.kind, g.reason = "girder", f"기둥 {n}개 연결, 폭 {w:.0f}"
        elif n >= 2:
            g.kind, g.reason = "wall", f"기둥 사이 얇은 부재 (t {w:.0f})"
        else:
            g.kind = None
            pending.append((g, n))
    girders = [(x, 1) for x in groups["girder"]] + [(x, 1) for x in ag if x.kind == "girder"]
    for g, n in pending:
        w = g.width
        sup = _supports_for(g, [], girders, ext=max(1500.0, w * 3))
        s0, s1 = g.ivs[0][0], g.ivs[-1][1]
        on_g = sum(1 for s in sup if s.a - p.support_tol <= s0 <= s.b + p.support_tol
                   or s.a - p.support_tol <= s1 <= s.b + p.support_tol)
        if on_g and 150 <= w <= 600:
            g.kind, g.reason = "beam", f"거더에 걸림, 폭 {w:.0f}"
        elif w <= 350:
            g.kind, g.reason = "wall", f"두께 {w:.0f} (연결 기둥/거더 없음)"
        elif n >= 1:
            g.kind, g.reason = "girder", f"기둥 연결, 폭 {w:.0f}"
        else:
            g.kind, g.reason = "beam", f"폭 {w:.0f} (판정 근거 약함)"


def dist_point_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(px - x1, py - y1), 0.0
    t = ((px - x1) * dx + (py - y1) * dy) / L2
    tc = max(0.0, min(1.0, t))
    return math.hypot(px - (x1 + tc * dx), py - (y1 + tc * dy)), t
