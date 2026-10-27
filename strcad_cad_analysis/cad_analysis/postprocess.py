"""Post-processing on an analysed model.

WallGirder: a girder/beam drawn on top of a wall (same axis, overlapping) is
almost always the wall-top beam of that wall. It is removed and the wall is
kept; the girder's name/size is recorded on the wall, and any members that
were T-jointed onto the girder are moved onto the wall.
"""
from __future__ import annotations

import math

from . import topology as T
from .geometry import dist_point_seg

ANG_TOL = 3.0          # deg
MIN_COVER = 0.7        # fraction of girder length lying on the wall(s)


def _axis(m):
    ux, uy, L = T._dir(m)
    return ux, uy, L


def find_wall_girders(res):
    """→ [(girder, [walls], cover_fraction)]"""
    walls = [w for w in res.members if w.kind == "wall" and not w.curved]
    out = []
    for g in res.members:
        if g.kind not in ("girder", "beam") or g.curved:
            continue
        gx, gy, gL = _axis(g)
        if gL < 1:
            continue
        ivs, hit = [], []
        for w in walls:
            wx, wy, wL = _axis(w)
            if abs(gx * wy - gy * wx) > math.sin(math.radians(ANG_TOL)):
                continue
            tol = max(w.width, g.width) / 2 + 20
            d1, _ = dist_point_seg(*g.p1, *w.p1, *w.p2)
            d2, _ = dist_point_seg(*g.p2, *w.p1, *w.p2)
            # perpendicular offset of girder axis from wall axis
            off = abs((g.p1[0] - w.p1[0]) * wy - (g.p1[1] - w.p1[1]) * wx)
            if off > tol:
                continue
            # overlap of projections on girder axis
            a = (w.p1[0] - g.p1[0]) * gx + (w.p1[1] - g.p1[1]) * gy
            b = (w.p2[0] - g.p1[0]) * gx + (w.p2[1] - g.p1[1]) * gy
            lo, hi = max(0.0, min(a, b)), min(gL, max(a, b))
            if hi - lo > 1:
                ivs.append((lo, hi))
                hit.append(w)
        if not ivs:
            continue
        ivs.sort()
        cov, cur = 0.0, None
        for lo, hi in ivs:
            if cur is None or lo > cur[1]:
                if cur:
                    cov += cur[1] - cur[0]
                cur = [lo, hi]
            else:
                cur[1] = max(cur[1], hi)
        cov += cur[1] - cur[0]
        frac = cov / gL
        if frac >= MIN_COVER:
            out.append((g, hit, frac))
    return out


def remove_wall_girders(res, log=None):
    log = log or (lambda *_: None)
    found = find_wall_girders(res)
    for g, walls, frac in found:
        if g not in res.members:
            continue
        tag = f"WallGirder: {g.display_name()} {g.size_text()} (L={g.length_cc:,.0f}) — 벽 상부 보 가능성"
        for w in walls:
            if tag not in w.notes:
                w.notes.append(tag)
            if g.name and g.name not in w.labels:
                w.labels.append(g.name)
        # T-joints that sat on the girder → move to the wall that carries them
        for nid, _t in list(g.inner):
            n = res.nodes.get(nid)
            if n is None:
                continue
            best = None
            for w in walls:
                d, t = dist_point_seg(n.x, n.y, *w.p1, *w.p2)
                if 0.0 < t < 1.0 and (best is None or d < best[0]):
                    best = (d, w, t)
            g.inner = [i for i in g.inner if i[0] != nid]
            if best:
                T.attach_node_to_member(res, nid, best[1], best[2])
        res.members.remove(g)
    if found:
        T.sync_all(res)
        T._gc_nodes(res)
    log(f"WallGirder {len(found)}개: 벽과 겹친 보/거더 삭제, 벽으로 표현"
        + (" (" + ", ".join(sorted({g.display_name() for g, _, _ in found})[:8]) + ")" if found else ""))
    return len(found)
