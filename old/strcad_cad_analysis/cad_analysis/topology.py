"""Shared-node topology and model editing.

Every member end is a Node. Members meeting at one joint share the same node:
  * a girder/beam/wall end inside (or next to) a column → the column's node
    (centre point; the member line may shift slightly — that is intended)
  * ends that meet each other (corner, crossing)          → one merged node
  * an end landing on the side of another member (T)      → node ON that member's
    axis, stored in host.inner as [node_id, t]; it slides with the host.

L (length_cc) is node-to-node; ln (length_clear) = L − off1 − off2 where the
offsets are the distances from the node to the support face (column outline
or half-width of the crossing member).
"""
from __future__ import annotations

import math
from collections import defaultdict

from .geometry import point_in_poly, dist_point_seg
from .model import Member, Node, AnalysisResult, SRC_USER

LINEAR = ("girder", "beam", "wall")


# ============================================================================
#  helpers
# ============================================================================
def members_at(res: AnalysisResult, nid: int):
    """Members using node nid as column node / end node / inner joint."""
    out = []
    for m in res.members:
        if m.node == nid or m.n1 == nid or m.n2 == nid or any(i[0] == nid for i in m.inner):
            out.append(m)
    return out


def host_of(res, nid):
    for m in res.members:
        for i in m.inner:
            if i[0] == nid:
                return m, i
    return None, None


def _new_node(res, x, y):
    nid = res.next_node_id()
    res.nodes[nid] = Node(nid, x, y)
    return nid


def _ray_exit(px, py, ux, uy, poly):
    """Distance along ray (p, u) to the last boundary crossing of poly
    when p is inside it (support face). 0 if p is outside."""
    if not poly or not point_in_poly(px, py, poly):
        return 0.0
    ts = []
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        ex, ey = x2 - x1, y2 - y1
        den = ux * ey - uy * ex
        if abs(den) < 1e-12:
            continue
        # p + t u = a + s e
        t = ((x1 - px) * ey - (y1 - py) * ex) / den
        s = ((x1 - px) * uy - (y1 - py) * ux) / den
        if t > 1e-9 and -1e-9 <= s <= 1 + 1e-9:
            ts.append(t)
    return min(ts) if ts else 0.0


def _dir(m):
    x1, y1 = m.p1
    x2, y2 = m.p2
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 1e-9:
        return 1.0, 0.0, 0.0
    return (x2 - x1) / L, (y2 - y1) / L, L


# ============================================================================
#  sync: nodes → member geometry
# ============================================================================
def sync_all(res: AnalysisResult):
    nodes = res.nodes
    by_node = defaultdict(list)
    for m in res.members:
        for nid in (m.node, m.n1, m.n2):
            if nid is not None:
                by_node[nid].append(m)
    # 1) hosts first (their inner nodes depend on them), two passes for chains
    for _ in range(2):
        for m in res.members:
            if m.kind in LINEAR and m.n1 in nodes and m.n2 in nodes:
                m.p1, m.p2 = nodes[m.n1].xy, nodes[m.n2].xy
                for nid, t in m.inner:
                    if nid in nodes:
                        nodes[nid].x = m.p1[0] + (m.p2[0] - m.p1[0]) * t
                        nodes[nid].y = m.p1[1] + (m.p2[1] - m.p1[1]) * t
    # 2) members
    for m in res.members:
        if m.kind == "column":
            if m.node in nodes:
                nx, ny = nodes[m.node].xy
                dx, dy = nx - m.center[0], ny - m.center[1]
                if dx or dy:
                    m.polygon = [(x + dx, y + dy) for x, y in m.polygon]
                    m.center = (nx, ny)
            continue
        if m.n1 in nodes and m.n2 in nodes:
            m.p1, m.p2 = nodes[m.n1].xy, nodes[m.n2].xy
        ux, uy, L = _dir(m)
        if not m.curved:
            m.length_cc = L
            m.angle = (math.degrees(math.atan2(uy, ux))) % 180.0
    # 3) offsets / clear span
    for m in res.members:
        if m.kind not in LINEAR or m.curved:
            continue
        ux, uy, L = _dir(m)
        m.off1 = _end_offset(res, m, m.n1, ux, uy, by_node)
        m.off2 = _end_offset(res, m, m.n2, -ux, -uy, by_node)
        if m.off1 + m.off2 > L:
            m.off1 = m.off2 = 0.0
        m.length_clear = max(0.0, L - m.off1 - m.off2)
        m.c1 = (m.p1[0] + ux * m.off1, m.p1[1] + uy * m.off1)
        m.c2 = (m.p2[0] - ux * m.off2, m.p2[1] - uy * m.off2)


def _end_offset(res, m, nid, ux, uy, by_node):
    """Distance from the node to the support face, looking into the member."""
    if nid is None or nid not in res.nodes:
        return 0.0
    px, py = res.nodes[nid].xy
    off = 0.0
    supports = list(by_node.get(nid, []))
    h, _ = host_of(res, nid)
    if h is not None:
        supports.append(h)
    for o in supports:
        if o is m:
            continue
        if o.kind == "column":
            off = max(off, _ray_exit(px, py, ux, uy, o.polygon))
        elif not o.curved:
            ox, oy, _ = _dir(o)
            s = abs(ux * oy - uy * ox)            # sin of angle between members
            if s < math.sin(math.radians(15)):
                continue                           # collinear continuation: no face
            # only a support if it is a "heavier" member or a wall/girder
            if m.kind == "girder" and o.kind == "beam":
                continue
            off = max(off, (o.width / 2) / s)
    return off


# ============================================================================
#  build topology after analysis
# ============================================================================
def build_topology(res: AnalysisResult, log=None):
    log = log or (lambda *_: None)
    res.nodes = {}
    for m in res.members:
        m.node = m.n1 = m.n2 = None
        m.inner = []
    cols = [m for m in res.members if m.kind == "column"]
    lins = [m for m in res.members if m.kind in LINEAR]
    for c in cols:
        c.node = _new_node(res, *c.center)

    # spatial hash for columns
    cell = 3000.0
    cgrid = defaultdict(list)
    for c in cols:
        cgrid[(int(c.center[0] // cell), int(c.center[1] // cell))].append(c)

    def near_cols(x, y):
        gx, gy = int(x // cell), int(y // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                yield from cgrid.get((gx + dx, gy + dy), ())

    ends = []          # [member, which(1/2), point]
    for m in lins:
        ends.append([m, 1, m.p1])
        ends.append([m, 2, m.p2])

    # A) ends at columns
    free = []
    n_col = 0
    for e in ends:
        m, k, (x, y) = e
        best = None
        for c in near_cols(x, y):
            d = math.hypot(x - c.center[0], y - c.center[1])
            inside = point_in_poly(x, y, c.polygon) if c.polygon else False
            lim = max(c.b, c.h) / 2 + m.width / 2 + 50
            if (inside or d <= lim) and (best is None or d < best[0]):
                best = (d, c)
        if best:
            setattr(m, "n1" if k == 1 else "n2", best[1].node)
            n_col += 1
        else:
            free.append(e)

    # B) cluster remaining ends (union-find, tolerance from member widths)
    parent = list(range(len(free)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    g = defaultdict(list)
    c2 = 1000.0
    for i, (m, k, (x, y)) in enumerate(free):
        g[(int(x // c2), int(y // c2))].append(i)
    for i, (mi, ki, (xi, yi)) in enumerate(free):
        gx, gy = int(xi // c2), int(yi // c2)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in g.get((gx + dx, gy + dy), ()):
                    if j <= i:
                        continue
                    mj, kj, (xj, yj) = free[j]
                    if mi is mj:
                        continue
                    tol = max(100.0, max(mi.width, mj.width) / 2 + 50)
                    if math.hypot(xi - xj, yi - yj) <= tol:
                        ra, rb = find(i), find(j)
                        if ra != rb:
                            parent[ra] = rb
    clusters = defaultdict(list)
    for i in range(len(free)):
        clusters[find(i)].append(free[i])

    # C) each cluster → one node; T-junction onto host member if it lands on one
    n_t = n_merge = n_ext = 0
    for cl in clusters.values():
        xs = [e[2][0] for e in cl]
        ys = [e[2][1] for e in cl]
        x, y = sum(xs) / len(xs), sum(ys) / len(ys)
        mem = {id(e[0]) for e in cl}
        wmax = max(e[0].width for e in cl)
        best = None
        for h in lins:
            if id(h) in mem or h.curved:
                continue
            hx, hy, hL = _dir(h)
            # host must not be collinear with every member of the cluster
            if all(abs(hx * _dir(e[0])[1] - hy * _dir(e[0])[0]) < 0.26 for e in cl):
                continue
            d, t = dist_point_seg(x, y, *h.p1, *h.p2)
            if not (0.01 < t < 0.99):
                continue
            if d <= h.width / 2 + wmax / 2 + 60 and (best is None or d < best[0]):
                best = (d, h, t)
        if not best and len(cl) == 1 and cl[0][0].kind in ("girder", "beam") and not cl[0][0].curved:
            best = _extend_to_host(cl[0], lins)
            if best:
                n_ext += 1
        if best:
            _, h, t = best
            x = h.p1[0] + (h.p2[0] - h.p1[0]) * t
            y = h.p1[1] + (h.p2[1] - h.p1[1]) * t
            nid = _new_node(res, x, y)
            h.inner.append([nid, t])
            n_t += 1
        else:
            nid = _new_node(res, x, y)
            if len(cl) > 1:
                n_merge += 1
        for m, k, _p in cl:
            setattr(m, "n1" if k == 1 else "n2", nid)
    for m in lins:
        m.inner.sort(key=lambda i: i[1])
    sync_all(res)
    n_ext += _join_dangling(res, lins)
    # drop members that collapsed (both ends on the same node)
    bad = [m for m in lins if m.n1 == m.n2]
    for m in bad:
        res.members.remove(m)
    _gc_nodes(res)
    log(f"절점 공유: 절점 {len(res.nodes)}개 (기둥접합 {n_col}, 부재끼리 {n_merge}, T접합 {n_t}, 연장접합 {n_ext}"
        + (f", 길이0 부재 {len(bad)}개 제거" if bad else "") + ")")


EXTEND_MAX = 1200.0


def _join_dangling(res, lins):
    """Free girder/beam end with a node just ahead of it (e.g. the end of
    another member at a corner) → share that node."""
    deg = defaultdict(int)
    for m in res.members:
        for nid in (m.node, m.n1, m.n2):
            if nid is not None:
                deg[nid] += 1
        for i in m.inner:
            deg[i[0]] += 1
    n = 0
    for m in lins:
        if m.kind not in ("girder", "beam") or m.curved:
            continue
        for k in (1, 2):
            nid = m.n1 if k == 1 else m.n2
            if deg[nid] != 1:
                continue
            ux, uy, L = _dir(m)
            if k == 1:
                ux, uy = -ux, -uy
            ex, ey = res.nodes[nid].xy
            other = m.n2 if k == 1 else m.n1
            own = {nid, other}
            mine = {i[0] for i in m.inner}       # own T-joint right at the free end = really a corner
            best = None
            for o in res.nodes.values():
                if o.id in own:
                    continue
                vx, vy = o.x - ex, o.y - ey
                along = vx * ux + vy * uy
                lat = abs(vx * uy - vy * ux)
                if -m.width <= along <= EXTEND_MAX and lat <= max(m.width / 2 + 150, 300):
                    sc = abs(along) + 2 * lat
                    if best is None or sc < best[0]:
                        best = (sc, o.id)
            if best:
                if best[1] in mine:
                    m.inner = [i for i in m.inner if i[0] != best[1]]
                setattr(m, "n1" if k == 1 else "n2", best[1])
                deg[best[1]] += 1
                deg[nid] -= 1
                n += 1
    if n:
        sync_all(res)
    return n


def _extend_to_host(end, lins):
    """Free girder/beam end: extend along its axis to the first member hit."""
    m, k, (x, y) = end
    ux, uy, L = _dir(m)
    if k == 1:
        ux, uy = -ux, -uy                 # outward direction
    best = None
    for h in lins:
        if h is m or h.curved:
            continue
        hx, hy, hL = _dir(h)
        den = ux * hy - uy * hx
        if abs(den) < 0.26:               # nearly parallel
            continue
        # (x,y) + s*u = h.p1 + r*(hx,hy)
        dx, dy = h.p1[0] - x, h.p1[1] - y
        s_ = (dx * hy - dy * hx) / den
        r = (dx * uy - dy * ux) / den
        lim = max(EXTEND_MAX, m.width * 2)
        if not (-m.width / 2 <= s_ <= lim):
            continue
        t = r / max(hL, 1e-9)
        if not (0.01 < t < 0.99):
            continue
        if best is None or s_ < best[0]:
            best = (s_, h, t)
    return best


def _gc_nodes(res):
    used = set()
    for m in res.members:
        for nid in (m.node, m.n1, m.n2):
            if nid is not None:
                used.add(nid)
        for i in m.inner:
            used.add(i[0])
    for nid in list(res.nodes):
        if nid not in used:
            del res.nodes[nid]
    # inner entries pointing to deleted nodes
    for m in res.members:
        m.inner = [i for i in m.inner if i[0] in res.nodes]


# ============================================================================
#  editing operations (all followed by sync_all)
# ============================================================================
def find_node(res, x, y, tol, exclude=()):
    best = None
    for n in res.nodes.values():
        if n.id in exclude:
            continue
        d = math.hypot(n.x - x, n.y - y)
        if d <= tol and (best is None or d < best[0]):
            best = (d, n.id)
    return best[1] if best else None


def find_member_body(res, x, y, tol, kinds=LINEAR, exclude=()):
    """Nearest straight linear member whose axis passes within tol → (m, t)."""
    best = None
    for m in res.members:
        if m.kind not in kinds or m.curved or m.id in exclude:
            continue
        d, t = dist_point_seg(x, y, *m.p1, *m.p2)
        if 0.0 < t < 1.0 and d <= tol and (best is None or d < best[0]):
            best = (d, m, t)
    return (best[1], best[2]) if best else (None, None)


def locked_node(res, nid):
    """Nodes on curved members are not movable (arc geometry is fixed)."""
    return any(m.curved for m in members_at(res, nid) if m.kind in LINEAR)


def move_node(res, nid, x, y):
    h, entry = host_of(res, nid)
    if h is not None:
        # slide along host
        ux, uy, L = _dir(h)
        t = ((x - h.p1[0]) * ux + (y - h.p1[1]) * uy) / max(L, 1e-9)
        entry[1] = min(0.99, max(0.01, t))
    else:
        res.nodes[nid].x, res.nodes[nid].y = x, y
    sync_all(res)


def translate_member(res, m, dx, dy):
    nids = [m.node] if m.kind == "column" else [m.n1, m.n2]
    for nid in nids:
        h, entry = host_of(res, nid)
        n = res.nodes[nid]
        if h is not None:
            ux, uy, L = _dir(h)
            entry[1] = min(0.99, max(0.01, entry[1] + (dx * ux + dy * uy) / max(L, 1e-9)))
        else:
            n.x += dx
            n.y += dy
    if m.curved and m.arc:
        m.arc["cx"] += dx
        m.arc["cy"] += dy
    sync_all(res)


def merge_nodes(res, src, dst):
    """All references to src now point to dst (joins members at one point)."""
    if src == dst:
        return
    for m in res.members:
        if m.node == src:
            m.node = dst
        if m.n1 == src:
            m.n1 = dst
        if m.n2 == src:
            m.n2 = dst
        m.inner = [i for i in m.inner if i[0] != src]
    # a column on dst wins its position
    res.nodes.pop(src, None)
    bad = [m for m in res.members if m.kind in LINEAR and m.n1 == m.n2]
    for m in bad:
        res.members.remove(m)
    sync_all(res)
    _gc_nodes(res)


def attach_node_to_member(res, nid, host, t):
    """Make nid a T-joint on host (it will slide with host)."""
    for m in res.members:
        m.inner = [i for i in m.inner if i[0] != nid]
    host.inner.append([nid, t])
    host.inner.sort(key=lambda i: i[1])
    sync_all(res)


def detach_node(res, nid):
    for m in res.members:
        m.inner = [i for i in m.inner if i[0] != nid]


def resolve_point(res, x, y, tol):
    """Snap a picked point: existing node > member body (new T-node) > new node."""
    nid = find_node(res, x, y, tol)
    if nid is not None:
        return nid
    h, t = find_member_body(res, x, y, tol)
    if h is not None:
        nid = _new_node(res, x, y)
        attach_node_to_member(res, nid, h, t)
        return nid
    return _new_node(res, x, y)


def add_column(res, x, y, b, h, rot_deg, tol, name=""):
    nid = find_node(res, x, y, tol)
    if nid is not None and any(m.kind == "column" and m.node == nid for m in res.members):
        return None
    if nid is None:
        nid = resolve_point(res, x, y, tol)
    n = res.nodes[nid]
    poly = _rect(n.x, n.y, b, h, rot_deg)
    m = Member(res.next_member_id(), "column", name=name, name_source=SRC_USER if name else "default",
               layer="(사용자)", center=(n.x, n.y), b=max(b, h), h=min(b, h), angle=rot_deg % 180,
               shape="rect", polygon=poly, node=nid, user=True)
    m.notes.append("사용자 추가")
    res.members.append(m)
    sync_all(res)
    return m


def _rect(cx, cy, b, h, rot_deg):
    r = math.radians(rot_deg)
    ux, uy = math.cos(r), math.sin(r)
    vx, vy = -uy, ux
    pts = []
    for sb, sh in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        pts.append((cx + ux * b / 2 * sb + vx * h / 2 * sh, cy + uy * b / 2 * sb + vy * h / 2 * sh))
    return pts


def add_linear(res, kind, n1, n2, width, name=""):
    if n1 == n2:
        return None
    m = Member(res.next_member_id(), kind, name=name, name_source=SRC_USER if name else "default",
               layer="(사용자)", width=float(width), n1=n1, n2=n2, user=True,
               p1=res.nodes[n1].xy, p2=res.nodes[n2].xy)
    m.notes.append("사용자 추가")
    res.members.append(m)
    sync_all(res)
    return m


def delete_member(res, m):
    res.members.remove(m)
    # inner joints of a deleted host become free nodes (stay where they are)
    sync_all(res)
    _gc_nodes(res)


def change_kind(res, m, new_kind):
    """Change member type. column ↔ linear converts geometry:
       column → wall/beam/girder : centreline along the long side, width = short side
       linear → column           : rectangle L × width at the midpoint"""
    if new_kind == m.kind:
        return m
    note = f"종류 변경: {m.kind}→{new_kind} (사용자)"
    if m.kind in LINEAR and new_kind in LINEAR:
        m.kind = new_kind
        m.notes.append(note)
        m.user = True
        sync_all(res)
        return m
    if m.kind == "column":
        cx, cy = m.center
        r = math.radians(m.angle)
        ux, uy = math.cos(r), math.sin(r)
        L = m.b
        a = _new_node(res, cx - ux * L / 2, cy - uy * L / 2)
        b = _new_node(res, cx + ux * L / 2, cy + uy * L / 2)
        old = m.node
        nm = Member(m.id, new_kind, name=m.name, name_source=m.name_source, labels=m.labels, layer=m.layer,
                    width=m.h, n1=a, n2=b, p1=res.nodes[a].xy, p2=res.nodes[b].xy, user=True,
                    notes=m.notes + [note])
        res.members[res.members.index(m)] = nm
        # members that were on the column node → nearest new end
        for o in res.members:
            for attr in ("n1", "n2"):
                if getattr(o, attr) == old:
                    p = res.nodes[old].xy
                    da = math.dist(p, res.nodes[a].xy)
                    db = math.dist(p, res.nodes[b].xy)
                    setattr(o, attr, a if da <= db else b)
        res.nodes.pop(old, None)
        sync_all(res)
        _gc_nodes(res)
        return nm
    # linear → column
    cx, cy = (m.p1[0] + m.p2[0]) / 2, (m.p1[1] + m.p2[1]) / 2
    L = m.length_cc
    nid = _new_node(res, cx, cy)
    nm = Member(m.id, "column", name=m.name, name_source=m.name_source, labels=m.labels, layer=m.layer,
                center=(cx, cy), b=max(L, m.width), h=min(L, m.width), angle=m.angle, shape="rect",
                polygon=_rect(cx, cy, L, m.width, m.angle), node=nid, user=True, notes=m.notes + [note])
    old_nodes = (m.n1, m.n2)
    res.members[res.members.index(m)] = nm
    # members that ended on the old ends → column node
    for o in res.members:
        for attr in ("n1", "n2"):
            if getattr(o, attr) in old_nodes:
                setattr(o, attr, nid)
    bad = [o for o in res.members if o.kind in LINEAR and o.n1 == o.n2]
    for o in bad:
        res.members.remove(o)
    sync_all(res)
    _gc_nodes(res)
    return nm
