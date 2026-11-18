"""
design_2d/plan/mesh.py — 면 자동 인식 · 슬래브 메시 생성 · 하중 전달
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【메시】 슬래브 면(꼭짓점 4개, 변 위의 중간 노드 허용) → 매핑 사각형 메시
        · 변(노드쌍)마다 분할수 n = ceil(L / 메시크기), 이웃 면과 공유
        · 마주보는 변의 분할수 합이 같아지도록 반복 보정 → 이웃 면과 절점 일치
        · 내부 절점은 Coons(TFI) 보간
        · 보 선은 슬래브 변의 절점을 공유하고, 슬래브와 닿지 않는 보는 자체 분할
【하중】 FE 절점하중으로 변환 (입력 ↓+ → w 방향 -)
        · 슬래브 면하중/자중: 일관 절점하중 (2×2 Gauss)
        · 비구조 면하중: 내부를 촘촘히 샘플링하여 각 점을
            2방향  → 가장 가까운 둘레 변
            1방향X → ±X 방향 첫 번째 둘레 변 두 곳에 지렛대 분배
            1방향Y → ±Y 방향 …
          으로 보낸 뒤, 그 변(보/슬래브 변이면 FE 절점, 아니면 양 끝 노드)으로 전달
        · 선하중: 메시가 있는 선이면 FE 절점, 아니면 샘플 점을
            슬래브 요소 안 → 형상함수 분배 / 밖 → 양 끝 노드 지렛대 분배
        · 절점하중: FE 절점이면 그대로, 슬래브 안이면 형상함수 분배
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import math
import numpy as np

from . import model as pm


class MeshError(Exception):
    pass


# ═══════════════════════════════════════════════════════════════
#  면 자동 인식 (닫힌 영역 클릭)
# ═══════════════════════════════════════════════════════════════
def find_face(m, x, y):
    """선으로 둘러싸인 가장 작은 영역의 노드 리스트 (반시계). 없으면 None"""
    nodes = m["nodes"]
    adj = {}
    for ln in m["lines"].values():
        a, b = ln["ni"], ln["nj"]
        if a == b:
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    ang = lambda u, v: math.atan2(nodes[v]["y"] - nodes[u]["y"], nodes[v]["x"] - nodes[u]["x"])
    order = {u: sorted(vs, key=lambda v: ang(u, v)) for u, vs in adj.items()}
    used = set()
    best = None
    for u in adj:
        for v in adj[u]:
            if (u, v) in used:
                continue
            face = [u]
            a, b = u, v
            ok = True
            for _ in range(10000):
                used.add((a, b))
                face.append(b)
                nb = order[b]
                i = nb.index(a)
                c = nb[i - 1]            # (b→a) 에서 시계방향으로 다음 이웃
                a, b = b, c
                if (a, b) == (u, v):
                    break
            else:
                ok = False
            if not ok:
                continue
            face = face[:-1]
            face = _remove_spikes(face)
            if len(face) < 3:
                continue
            pts = pm.poly_xy(m, face)
            A = pm.poly_area(pts)
            if A <= 1e-9:
                continue
            if pm.point_in_poly(x, y, pts) and (best is None or A < best[0]):
                best = (A, face)
    return best[1] if best else None


def _remove_spikes(f):
    changed = True
    while changed and len(f) >= 3:
        changed = False
        n = len(f)
        for i in range(n):
            if f[(i - 1) % n] == f[(i + 1) % n]:
                del f[i]
                j = i % len(f)
                del f[j]
                changed = True
                break
    # 중복 제거
    out = []
    for v in f:
        if not out or out[-1] != v:
            out.append(v)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


# ═══════════════════════════════════════════════════════════════
#  메시
# ═══════════════════════════════════════════════════════════════
def _corners(m, nodes, tol_deg=8.0):
    pts = pm.poly_xy(m, nodes)
    n = len(pts)
    idx = []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        a1 = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        a2 = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        d = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
        if math.degrees(d) > tol_deg:
            idx.append(i)
    return idx


class Mesh:
    """FE 메시. 절점 좌표 xy (nn,2), 판요소 plates (ne,4), 보요소 beams (nb,2)"""

    def __init__(self):
        self.xy = []
        self.node_of = {}          # 모델 노드 → FE 절점
        self.edge_nodes = {}       # (a,b) 정방향 키 → FE 절점 리스트 (a→b)
        self.plates = []           # [n1,n2,n3,n4]
        self.plate_area = []       # 소속 면 id
        self.beams = []            # [n1,n2]
        self.beam_line = []        # 소속 선 id
        self.line_chain = {}       # 보 선 id → FE 절점 리스트 (ni→nj)
        self.line_beams = {}       # 보 선 id → 보요소 번호 리스트 (ni→nj 순)
        self.line_chain_all = {}   # 메시가 있는 모든 선 id → FE 절점 리스트
        self.warnings = []

    def _new(self, x, y):
        self.xy.append((x, y))
        return len(self.xy) - 1

    def model_node(self, m, nid):
        if nid not in self.node_of:
            n = m["nodes"][nid]
            self.node_of[nid] = self._new(n["x"], n["y"])
        return self.node_of[nid]

    def chain(self, a, b):
        """모델 노드 a→b 변의 FE 절점 리스트 (없으면 None)"""
        if (a, b) in self.edge_nodes:
            return self.edge_nodes[(a, b)]
        if (b, a) in self.edge_nodes:
            return self.edge_nodes[(b, a)][::-1]
        return None


def build_mesh(m):
    size = max(0.05, float(m.get("mesh_size", 0.5) or 0.5))
    mesh = Mesh()
    nodes = m["nodes"]
    elen = lambda a, b: math.hypot(nodes[b]["x"] - nodes[a]["x"], nodes[b]["y"] - nodes[a]["y"])
    key = lambda a, b: (a, b) if a < b else (b, a)

    # ── 슬래브 면 → 4변(각 변은 노드쌍 체인) ──
    slabs = []
    for aid, ar in m["areas"].items():
        if ar.get("kind") != "slab":
            continue
        ns = pm.expand_poly(m, ar["nodes"])      # 변 위의 노드(보 분할점)도 꼭짓점으로
        if ar.get("slab") not in m["slabs"]:
            raise MeshError(f"면 A{aid}: 슬래브 타입이 지정되지 않았습니다.")
        cs = _corners(m, ns)
        if len(cs) != 4:
            raise MeshError(f"면 A{aid}: 슬래브는 꼭짓점이 4개인 사각형만 가능합니다 "
                            f"(현재 {len(cs)}개). 면을 사각형으로 나눠 주세요.")
        sides = []
        for k in range(4):
            i0, i1 = cs[k], cs[(k + 1) % 4]
            seq = []
            i = i0
            while True:
                seq.append(ns[i])
                if i == i1:
                    break
                i = (i + 1) % len(ns)
            sides.append(seq)
        slabs.append((aid, sides))

    # ── 변 분할수 ──
    cnt = {}
    for _, sides in slabs:
        for seq in sides:
            for a, b in zip(seq[:-1], seq[1:]):
                cnt[key(a, b)] = max(1, math.ceil(elen(a, b) / size - 1e-9))
    for _ in range(200):
        changed = False
        for _, sides in slabs:
            for s1, s2 in ((sides[0], sides[2]), (sides[1], sides[3])):
                t1 = sum(cnt[key(a, b)] for a, b in zip(s1[:-1], s1[1:]))
                t2 = sum(cnt[key(a, b)] for a, b in zip(s2[:-1], s2[1:]))
                if t1 != t2:
                    lo = s1 if t1 < t2 else s2
                    segs = list(zip(lo[:-1], lo[1:]))
                    # 분할 길이가 가장 긴 구간에 1 추가
                    a, b = max(segs, key=lambda e: elen(*e) / cnt[key(*e)])
                    cnt[key(a, b)] += 1
                    changed = True
        if not changed:
            break
    else:
        raise MeshError("슬래브 메시 분할수를 맞추지 못했습니다. 면 배치를 확인하세요.")

    def edge_chain(a, b, n=None):
        c = mesh.chain(a, b)
        if c is not None:
            return c
        k = key(a, b)
        n = n or cnt.get(k) or max(1, math.ceil(elen(a, b) / size - 1e-9))
        p, q = k
        na, nb_ = mesh.model_node(m, p), mesh.model_node(m, q)
        xa, ya = nodes[p]["x"], nodes[p]["y"]
        xb, yb = nodes[q]["x"], nodes[q]["y"]
        lst = [na] + [mesh._new(xa + (xb - xa) * i / n, ya + (yb - ya) * i / n)
                      for i in range(1, n)] + [nb_]
        mesh.edge_nodes[k] = lst
        return mesh.chain(a, b)

    def side_chain(seq):
        out = []
        for a, b in zip(seq[:-1], seq[1:]):
            c = edge_chain(a, b)
            out += c if not out else c[1:]
        return out

    # ── 슬래브 매핑 메시 ──
    for aid, sides in slabs:
        S = [side_chain(s) for s in sides]
        N, M = len(S[0]) - 1, len(S[1]) - 1
        B = S[0]; R = S[1]; T = S[2][::-1]; L = S[3][::-1]
        xy = mesh.xy
        c0, c1, c2, c3 = (np.array(xy[B[0]]), np.array(xy[B[-1]]),
                          np.array(xy[T[-1]]), np.array(xy[T[0]]))
        G = [[None] * (M + 1) for _ in range(N + 1)]
        for i in range(N + 1):
            G[i][0] = B[i]; G[i][M] = T[i]
        for j in range(M + 1):
            G[0][j] = L[j]; G[N][j] = R[j]
        for i in range(1, N):
            u = i / N
            for j in range(1, M):
                v = j / M
                p = ((1 - v) * np.array(xy[B[i]]) + v * np.array(xy[T[i]]) +
                     (1 - u) * np.array(xy[L[j]]) + u * np.array(xy[R[j]]) -
                     ((1 - u) * (1 - v) * c0 + u * (1 - v) * c1 + u * v * c2 + (1 - u) * v * c3))
                G[i][j] = mesh._new(float(p[0]), float(p[1]))
        for i in range(N):
            for j in range(M):
                mesh.plates.append([G[i][j], G[i + 1][j], G[i + 1][j + 1], G[i][j + 1]])
                mesh.plate_area.append(aid)

    # ── 보 ──
    for lid, ln in m["lines"].items():
        if ln.get("kind") != "beam":
            continue
        if ln.get("sec") not in m["sections"]:
            raise MeshError(f"선 L{lid}: 보 단면이 지정되지 않았습니다.")
        ch = edge_chain(ln["ni"], ln["nj"])
        mesh.line_chain[lid] = ch
        mesh.line_beams[lid] = []
        for a, b in zip(ch[:-1], ch[1:]):
            mesh.line_beams[lid].append(len(mesh.beams))
            mesh.beams.append([a, b])
            mesh.beam_line.append(lid)

    # ── 선 지점 (벽체) ──
    for lid, sid in m.get("line_supports", {}).items():
        if lid in m["lines"]:
            ln = m["lines"][lid]
            edge_chain(ln["ni"], ln["nj"])
    for lid, ln in m["lines"].items():
        ch = mesh.chain(ln["ni"], ln["nj"])
        if ch is not None:
            mesh.line_chain_all[lid] = ch

    # ── 지점 노드 ──
    for nid in m["supports"]:
        if nid not in mesh.node_of:
            mesh.warnings.append(f"지점 N{nid} 는 보·슬래브에 연결되지 않아 무시됩니다.")

    mesh.xy = np.array(mesh.xy, dtype=float) if mesh.xy else np.zeros((0, 2))
    mesh.plates = np.array(mesh.plates, dtype=int).reshape(-1, 4)
    mesh.beams = np.array(mesh.beams, dtype=int).reshape(-1, 2)
    _merge_coincident(mesh)
    # 슬래브 영역 안을 지나는데 판 절점과 연결되지 않은 보 경고
    if len(mesh.plates) and len(mesh.beams):
        pn = set(mesh.plates.ravel().tolist())
        loc = PointLocator(mesh)
        for lid, ch in mesh.line_chain.items():
            inner = ch[1:-1]
            if not inner:
                continue
            k = inner[len(inner) // 2]
            if k not in pn and loc.locate(*mesh.xy[k]) is not None:
                mesh.warnings.append(f"보 L{lid} 이(가) 슬래브 내부를 지나지만 메시 절점과 맞지 않아 "
                                     f"슬래브와 연결되지 않았습니다. 보를 따라 면을 나눠 주세요.")
    return mesh


def _merge_coincident(mesh, tol=1e-6):
    """같은 위치의 FE 절점을 하나로 합침 (안전장치)"""
    n = len(mesh.xy)
    if n == 0:
        return
    key = np.round(mesh.xy / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    if len(first) == n:
        return
    keep = np.sort(first)
    new_id = -np.ones(n, dtype=int)
    rep = first[inv]                      # 각 절점 → 대표(최초) 절점
    new_id[keep] = np.arange(len(keep))
    remap = new_id[rep]
    mesh.xy = mesh.xy[keep]
    mesh.plates = remap[mesh.plates] if len(mesh.plates) else mesh.plates
    mesh.beams = remap[mesh.beams] if len(mesh.beams) else mesh.beams
    mesh.node_of = {k: int(remap[v]) for k, v in mesh.node_of.items()}
    mesh.edge_nodes = {k: [int(remap[v]) for v in lst] for k, lst in mesh.edge_nodes.items()}
    mesh.line_chain = {k: [int(remap[v]) for v in lst] for k, lst in mesh.line_chain.items()}
    mesh.line_chain_all = {k: [int(remap[v]) for v in lst] for k, lst in mesh.line_chain_all.items()}


# ═══════════════════════════════════════════════════════════════
#  점 위치 → 판요소 (역사상)
# ═══════════════════════════════════════════════════════════════
def _shape4(xi, eta):
    return 0.25 * np.array([(1 - xi) * (1 - eta), (1 + xi) * (1 - eta),
                            (1 + xi) * (1 + eta), (1 - xi) * (1 + eta)])


def _inverse_map(X, x, y):
    """사각형 요소 좌표 X(4,2) 에서 점 (x,y)의 자연좌표. 실패시 None"""
    xi = eta = 0.0
    for _ in range(25):
        N = _shape4(xi, eta)
        px, py = N @ X[:, 0], N @ X[:, 1]
        dN = 0.25 * np.array([[-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)],
                              [-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)]])
        J = dN @ X
        r = np.array([x - px, y - py])
        try:
            d = np.linalg.solve(J.T, r)
        except np.linalg.LinAlgError:
            return None
        xi += d[0]; eta += d[1]
        if abs(d[0]) + abs(d[1]) < 1e-10:
            break
    if abs(xi) <= 1 + 1e-7 and abs(eta) <= 1 + 1e-7:
        return xi, eta
    return None


class PointLocator:
    def __init__(self, mesh):
        self.mesh = mesh
        P = mesh.plates
        if len(P):
            X = mesh.xy[P]               # (ne,4,2)
            self.lo = X.min(axis=1) - 1e-9
            self.hi = X.max(axis=1) + 1e-9
        else:
            self.lo = self.hi = np.zeros((0, 2))
        self._node_xy = {tuple(np.round(p, 6)): i for i, p in enumerate(mesh.xy)}

    def node_at(self, x, y):
        return self._node_xy.get((round(x, 6), round(y, 6)))

    def locate(self, x, y):
        """(요소 번호, 형상함수 값 4) 또는 None"""
        if not len(self.lo):
            return None
        cand = np.where((self.lo[:, 0] <= x) & (self.hi[:, 0] >= x) &
                        (self.lo[:, 1] <= y) & (self.hi[:, 1] >= y))[0]
        for e in cand:
            X = self.mesh.xy[self.mesh.plates[e]]
            r = _inverse_map(X, x, y)
            if r is not None:
                return e, _shape4(*r)
        return None


# ═══════════════════════════════════════════════════════════════
#  하중 → FE 절점하중
# ═══════════════════════════════════════════════════════════════
_G2 = (-1 / math.sqrt(3), 1 / math.sqrt(3))


class LoadBuilder:
    """케이스별 FE 하중벡터 (w 방향만, 크기 nn) 작성"""

    def __init__(self, m, mesh):
        self.m = m
        self.mesh = mesh
        self.loc = PointLocator(mesh)
        self.F = None
        self.lost = 0.0

    # ── 기본 전달 ──
    def _fe(self, nid):
        return self.mesh.node_of.get(nid)

    def point_xy(self, x, y, P, fallback=None):
        """좌표 (x,y)에 P(↓+) 작용"""
        k = self.loc.node_at(x, y)
        if k is not None:
            self.F[k] += P; return
        r = self.loc.locate(x, y)
        if r is not None:
            e, N = r
            for nn, v in zip(self.mesh.plates[e], N):
                self.F[nn] += P * v
            return
        if fallback:
            fallback(P)
        else:
            self.lost += P

    def point_node(self, nid, P):
        k = self._fe(nid)
        if k is not None:
            self.F[k] += P; return
        n = self.m["nodes"][nid]
        self.point_xy(n["x"], n["y"], P)

    def point_on_edge(self, a, b, t, P):
        """모델 노드 a→b 변 위 t(0~1) 위치의 P"""
        ch = self.mesh.chain(a, b)
        if ch is not None:
            n = len(ch) - 1
            s = min(max(t, 0.0), 1.0) * n
            i = min(int(s), n - 1); f = s - i
            # 체인 절점이 등간격이 아닐 수 있으므로 실제 위치로 보간
            pa, pb = self.mesh.xy[ch[0]], self.mesh.xy[ch[-1]]
            L = np.linalg.norm(pb - pa)
            if L > 0:
                ts = [np.linalg.norm(self.mesh.xy[c] - pa) / L for c in ch]
                i = max(0, min(n - 1, int(np.searchsorted(ts, t) - 1)))
                f = (t - ts[i]) / (ts[i + 1] - ts[i]) if ts[i + 1] > ts[i] else 0.0
            self.F[ch[i]] += P * (1 - f); self.F[ch[i + 1]] += P * f
            return
        na, nb = self.m["nodes"][a], self.m["nodes"][b]
        x = na["x"] + (nb["x"] - na["x"]) * t; y = na["y"] + (nb["y"] - na["y"]) * t

        def lever(P_):
            self.point_node(a, P_ * (1 - t)); self.point_node(b, P_ * t)
        self.point_xy(x, y, P, fallback=lever)

    def line_load(self, a, b, w1, w2):
        """a→b 변 사다리꼴 선하중 (kN/m)"""
        nodes = self.m["nodes"]
        L = math.hypot(nodes[b]["x"] - nodes[a]["x"], nodes[b]["y"] - nodes[a]["y"])
        if L < 1e-12:
            return
        ch = self.mesh.chain(a, b)
        if ch is not None:
            pa = self.mesh.xy[ch[0]]
            ts = [np.linalg.norm(self.mesh.xy[c] - pa) / L for c in ch]
            for i in range(len(ch) - 1):
                t0, t1 = ts[i], ts[i + 1]
                q0 = w1 + (w2 - w1) * t0; q1 = w1 + (w2 - w1) * t1
                ln = (t1 - t0) * L
                self.F[ch[i]] += ln * (2 * q0 + q1) / 6
                self.F[ch[i + 1]] += ln * (q0 + 2 * q1) / 6
            return
        n = max(8, int(L / max(0.05, float(self.m.get("mesh_size", 0.5)) / 2)))
        for i in range(n):
            t = (i + 0.5) / n
            self.point_on_edge(a, b, t, (w1 + (w2 - w1) * t) * L / n)

    def beam_line_load(self, lid, w1, w2):
        """보 선의 사다리꼴 하중 → 보요소 부재하중 (고정단력은 솔버에서)"""
        els = self.mesh.line_beams.get(lid)
        if not els:
            ln = self.m["lines"][lid]
            return self.line_load(ln["ni"], ln["nj"], w1, w2)
        ch = self.mesh.line_chain[lid]
        pa = self.mesh.xy[ch[0]]
        L = np.linalg.norm(self.mesh.xy[ch[-1]] - pa)
        for k, e in enumerate(els):
            t0 = np.linalg.norm(self.mesh.xy[ch[k]] - pa) / L
            t1 = np.linalg.norm(self.mesh.xy[ch[k + 1]] - pa) / L
            self.BE[e, 0] += w1 + (w2 - w1) * t0
            self.BE[e, 1] += w1 + (w2 - w1) * t1

    def plate_pressure(self, elems, q):
        """판요소 리스트에 등분포 q (↓+)"""
        for e in elems:
            X = self.mesh.xy[self.mesh.plates[e]]
            fe = np.zeros(4)
            for xi in _G2:
                for eta in _G2:
                    N = _shape4(xi, eta)
                    dN = 0.25 * np.array([[-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)],
                                          [-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)]])
                    fe += N * q * abs(np.linalg.det(dN @ X))
            self.F[self.mesh.plates[e]] += fe

    def area_transfer(self, aid, q):
        """비구조 면의 면하중을 둘레 변으로 전달"""
        ar = self.m["areas"][aid]
        ns = ar["nodes"]
        pts = pm.poly_xy(self.m, ns)
        edges = [(ns[i], ns[(i + 1) % len(ns)], pts[i], pts[(i + 1) % len(ns)]) for i in range(len(ns))]
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        h = max((x1 - x0), (y1 - y0)) / 120.0
        h = max(h, 1e-3)
        mode = ar.get("dist", "two")
        nx_, ny_ = max(1, int(round((x1 - x0) / h))), max(1, int(round((y1 - y0) / h)))
        dx, dy = (x1 - x0) / nx_, (y1 - y0) / ny_
        total = q * abs(pm.poly_area(pts))
        acc = []
        for i in range(nx_):
            x = x0 + (i + 0.5) * dx
            for j in range(ny_):
                y = y0 + (j + 0.5) * dy
                if pm.point_in_poly(x, y, pts):
                    acc.append((x, y))
        if not acc:
            self.lost += total; return
        P = total / len(acc)          # 다각형 넓이를 정확히 맞추도록 정규화
        NB = 100
        bins = {}                     # (변 번호, 구간) → 하중  (변 위 위치를 구간으로 묶어 속도 개선)

        def put(ei, t, p):
            k = (ei, min(NB - 1, int(t * NB)))
            bins[k] = bins.get(k, 0.0) + p
        for x, y in acc:
            if mode == "two":
                ds = [_seg_dist(pa, pb, x, y) for _, _, pa, pb in edges]
                dmin = min(d for _, d in ds)
                ties = [i for i, (_, d) in enumerate(ds) if d <= dmin + 1e-9]
                for i in ties:                       # 등거리(이등분선 위)는 나눠 줌
                    put(i, ds[i][0], P / len(ties))
            else:
                ax = 0 if mode == "x" else 1
                hits = []
                for i, (a, b, pa, pb) in enumerate(edges):
                    r = _ray_hit(pa, pb, x, y, ax)
                    if r is not None:
                        hits.append((r[0], i, r[1]))
                neg = [h_ for h_ in hits if h_[0] < 0]
                pos = [h_ for h_ in hits if h_[0] > 0]
                if not neg or not pos:
                    ds = [_seg_dist(pa, pb, x, y) for _, _, pa, pb in edges]
                    i = min(range(len(ds)), key=lambda k: ds[k][1])
                    put(i, ds[i][0], P)
                    continue
                n1 = max(neg, key=lambda h_: h_[0]); p1 = min(pos, key=lambda h_: h_[0])
                d1, d2 = -n1[0], p1[0]
                put(n1[1], n1[2], P * d2 / (d1 + d2))
                put(p1[1], p1[2], P * d1 / (d1 + d2))
        for (i, k), p in bins.items():
            a, b = edges[i][0], edges[i][1]
            self.point_on_edge(a, b, (k + 0.5) / NB, p)

    # ── 케이스 ──
    def build(self, case_id):
        m, mesh = self.m, self.mesh
        nn = len(mesh.xy)
        self.F = np.zeros(nn)
        self.BE = np.zeros((len(mesh.beams), 2))     # 보요소 하중 [시작, 끝] kN/m (↓+)
        self.lost = 0.0
        sw = float(m["cases"].get(case_id, {}).get("selfweight", 0) or 0)
        by_area = {}
        for e, aid in enumerate(mesh.plate_area):
            by_area.setdefault(aid, []).append(e)
        if sw:
            for aid, els in by_area.items():
                sl = m["slabs"][m["areas"][aid]["slab"]]
                mat = m["materials"].get(sl["mat"], {})
                self.plate_pressure(els, sw * float(mat.get("gamma", 0)) * float(sl["t"]) / 1000.0)
            for lid, ch in mesh.line_chain.items():
                ln = m["lines"][lid]
                A = pm.section_props(m["sections"][ln["sec"]])[0] * 1e-6
                g = float(m["materials"].get(ln["mat"], {}).get("gamma", 0))
                w = sw * g * A
                self.beam_line_load(lid, w, w)
        for ld in m["aloads"]:
            if ld["case"] != case_id or ld["area"] not in m["areas"]:
                continue
            q = float(ld.get("q", 0))
            if ld["area"] in by_area:
                self.plate_pressure(by_area[ld["area"]], q)
            else:
                self.area_transfer(ld["area"], q)
        for ld in m["lloads"]:
            if ld["case"] != case_id or ld["line"] not in m["lines"]:
                continue
            ln = m["lines"][ld["line"]]
            w1, w2 = float(ld.get("w1", 0)), float(ld.get("w2", ld.get("w1", 0)))
            if ld["line"] in mesh.line_beams:
                self.beam_line_load(ld["line"], w1, w2)
            else:
                self.line_load(ln["ni"], ln["nj"], w1, w2)
        for ld in m["nloads"]:
            if ld["case"] != case_id or ld["node"] not in m["nodes"]:
                continue
            self.point_node(ld["node"], float(ld.get("p", 0)))
        return self.F.copy(), self.lost, self.BE.copy()


def _seg_dist(pa, pb, x, y):
    dx, dy = pb[0] - pa[0], pb[1] - pa[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((x - pa[0]) * dx + (y - pa[1]) * dy) / L2))
    return t, math.hypot(x - (pa[0] + t * dx), y - (pa[1] + t * dy))


def _ray_hit(pa, pb, x, y, ax):
    """점에서 축(ax=0:X, 1:Y) 방향 직선과 선분 교차 → (부호 있는 거리, t)"""
    if ax == 0:
        y0, y1 = pa[1], pb[1]
        if abs(y1 - y0) < 1e-12 or not (min(y0, y1) - 1e-12 <= y <= max(y0, y1) + 1e-12):
            return None
        t = (y - y0) / (y1 - y0)
        xh = pa[0] + t * (pb[0] - pa[0])
        return xh - x, t
    x0, x1 = pa[0], pb[0]
    if abs(x1 - x0) < 1e-12 or not (min(x0, x1) - 1e-12 <= x <= max(x0, x1) + 1e-12):
        return None
    t = (x - x0) / (x1 - x0)
    yh = pa[1] + t * (pb[1] - pa[1])
    return yh - y, t
