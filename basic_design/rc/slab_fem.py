"""
basic_design/rc/slab_fem.py
직사각형 슬래브 유한요소 해석 (Tk 비의존 · numpy)

  · 판 요소   4절점 MITC4 (Mindlin–Reissner, 전단 잠김 없음),  절점 자유도 (w, φx, φy)
               w: 처짐(아래 +),  φx = ∂w/∂x,  φy = ∂w/∂y  (얇은 판 한계)
  · 보 요소   변을 따라가는 2절점 보 (휨 + 비틀림) — 테두리보 / 연속단 보(대칭 → 강성 1/2)
  · 지지      변: 보지지(연속/불연속) · 벽지지(연속/불연속) · 자유,   모서리: 수직 지지(Fix) / 자유
               연속 = 변에 직각인 회전 구속 (인접 패널과 대칭)
  · 하중      등분포 + 집중 · 라인 · 면(사각형) 하중 — 고정(D) / 활(L) 따로 풀어 조합
  · 결과      절점 평균 Mx, My, Mxy [kN·m/m] (정모멘트 = 아래 인장 +),  Qx, Qy [kN/m],  w [mm]

단위: 길이 m, 힘 kN  (E 는 kN/m²)
"""
import math

import numpy as np

EDGE_KEYS = ["top", "bottom", "left", "right"]            # 상(y=Ly), 하(y=0), 좌(x=0), 우(x=Lx)
EDGE_TYPES = {                                             # key: (표시, 보, 수직지지(w=0), 회전구속)
    "beam_c": ("보지지:연속", True, False, True),
    "beam_d": ("보지지:불연속", True, False, False),
    "wall_c": ("벽지지:연속", False, True, True),
    "wall_d": ("벽지지:불연속", False, True, False),
    "free":   ("자유", False, False, False),
}
TORSION_FACTOR = 0.2          # 균열을 고려한 보 비틀림 강성 저감 (GJ × 0.2)
KS = 5.0 / 6.0


class FemError(ValueError):
    pass


# ── 요소 강성 ────────────────────────────────────────────────
_XI = np.array([-1.0, 1.0, 1.0, -1.0])
_ETA = np.array([-1.0, -1.0, 1.0, 1.0])


def _shape(xi, eta, a, b):
    """N, dN/dx, dN/dy  (a×b 직사각형)"""
    n = 0.25 * (1 + _XI * xi) * (1 + _ETA * eta)
    dx = _XI * (1 + _ETA * eta) / (2.0 * a)
    dy = _ETA * (1 + _XI * xi) / (2.0 * b)
    return n, dx, dy


def _bb(xi, eta, a, b):
    """곡률 κ = [φx,x ; φy,y ; φx,y + φy,x]"""
    _, dx, dy = _shape(xi, eta, a, b)
    m = np.zeros((3, 12))
    m[0, 1::3] = dx
    m[1, 2::3] = dy
    m[2, 1::3] = dy
    m[2, 2::3] = dx
    return m


def _gx(xi, eta, a, b):
    """γx = w,x - φx  (한 점)"""
    n, dx, _ = _shape(xi, eta, a, b)
    r = np.zeros(12)
    r[0::3] = dx
    r[1::3] = -n
    return r


def _gy(xi, eta, a, b):
    n, _, dy = _shape(xi, eta, a, b)
    r = np.zeros(12)
    r[0::3] = dy
    r[2::3] = -n
    return r


def _bs(xi, eta, a, b):
    """MITC4 가정 전단변형률장: γx 는 η 방향 선형(변 중점 A·C), γy 는 ξ 방향 선형(변 중점 B·D)"""
    m = np.zeros((2, 12))
    m[0] = 0.5 * (1 + eta) * _gx(0, 1, a, b) + 0.5 * (1 - eta) * _gx(0, -1, a, b)
    m[1] = 0.5 * (1 + xi) * _gy(1, 0, a, b) + 0.5 * (1 - xi) * _gy(-1, 0, a, b)
    return m


def plate_matrices(a, b, e, nu, t):
    """(Ke 12×12, Db 3×3, Ds 2×2)"""
    d = e * t ** 3 / (12.0 * (1 - nu * nu))
    db = d * np.array([[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2.0]])
    ds = KS * e / (2.0 * (1 + nu)) * t * np.eye(2)
    ke = np.zeros((12, 12))
    g = 1.0 / math.sqrt(3.0)
    for xi in (-g, g):
        for eta in (-g, g):
            bb = _bb(xi, eta, a, b)
            bs = _bs(xi, eta, a, b)
            ke += (bb.T @ db @ bb + bs.T @ ds @ bs) * (a * b / 4.0)
    return ke, db, ds


def beam_matrix(length, ei, gj):
    """보 요소 6×6: 자유도 (w1, θb1, θt1, w2, θb2, θt2) — θb = dw/ds (휨), θt = 비틀림"""
    k = np.zeros((6, 6))
    c = ei / length ** 3
    kb = c * np.array([[12, 6 * length, -12, 6 * length],
                       [6 * length, 4 * length ** 2, -6 * length, 2 * length ** 2],
                       [-12, -6 * length, 12, -6 * length],
                       [6 * length, 2 * length ** 2, -6 * length, 4 * length ** 2]])
    ib = [0, 1, 3, 4]
    for i in range(4):
        for j in range(4):
            k[ib[i], ib[j]] = kb[i, j]
    kt = gj / length
    k[2, 2] += kt
    k[5, 5] += kt
    k[2, 5] -= kt
    k[5, 2] -= kt
    return k


def beam_section(bw, h, t, both_sides):
    """(I, J) [m⁴] — 슬래브 아래로 내민 높이(≤ 4t)만큼 플랜지를 포함한 단면의 I 에서
    플랜지 자체의 I(판 요소에 이미 포함)를 뺀 값.  입력 m"""
    if bw <= 0 or h <= 0:
        return 0.0, 0.0
    if h <= t:
        return 0.0, 0.0
    hw = h - t
    proj = min(hw, 4.0 * t)
    bf = bw + proj * (2 if both_sides else 1)
    a1, y1 = bf * t, t / 2.0
    a2, y2 = bw * hw, t + hw / 2.0
    yb = (a1 * y1 + a2 * y2) / (a1 + a2)
    i_t = bf * t ** 3 / 12.0 + a1 * (yb - y1) ** 2 + bw * hw ** 3 / 12.0 + a2 * (y2 - yb) ** 2
    i_net = i_t - bf * t ** 3 / 12.0
    s, l = min(bw, h), max(bw, h)
    j = (1.0 / 3.0 - 0.21 * s / l * (1 - s ** 4 / (12.0 * l ** 4))) * s ** 3 * l
    return i_net, j


# ── 모델 ─────────────────────────────────────────────────────
class SlabModel:
    """직사각형 슬래브 FE 모델.  nid(i, j) = j·(nx+1) + i   (i: x 방향, j: y 방향)"""

    def __init__(self, lx, ly, t, e, nu=0.167, nx=16, ny=24):
        self.lx, self.ly, self.t, self.e, self.nu = lx, ly, t, e, nu
        self.nx, self.ny = nx, ny
        self.a, self.b = lx / nx, ly / ny
        self.nn = (nx + 1) * (ny + 1)
        self.ndof = 3 * self.nn
        self.xs = np.linspace(0, lx, nx + 1)
        self.ys = np.linspace(0, ly, ny + 1)
        self.ke, self.db, self.ds = plate_matrices(self.a, self.b, e, nu, t)
        self.k = np.zeros((self.ndof, self.ndof))
        self.fixed = np.zeros(self.ndof, dtype=bool)
        self.beams = []                                   # (edge, n1, n2, dofs, ke, factor)
        self._assemble_plate()

    def nid(self, i, j):
        return j * (self.nx + 1) + i

    def elem_nodes(self, i, j):
        return [self.nid(i, j), self.nid(i + 1, j), self.nid(i + 1, j + 1), self.nid(i, j + 1)]

    @staticmethod
    def _dofs(nodes):
        out = []
        for n in nodes:
            out += [3 * n, 3 * n + 1, 3 * n + 2]
        return out

    def _assemble_plate(self):
        for j in range(self.ny):
            for i in range(self.nx):
                d = self._dofs(self.elem_nodes(i, j))
                self.k[np.ix_(d, d)] += self.ke

    def edge_nodes(self, edge):
        nx, ny = self.nx, self.ny
        if edge == "top":
            return [self.nid(i, ny) for i in range(nx + 1)]
        if edge == "bottom":
            return [self.nid(i, 0) for i in range(nx + 1)]
        if edge == "left":
            return [self.nid(0, j) for j in range(ny + 1)]
        return [self.nid(nx, j) for j in range(ny + 1)]

    def set_edge(self, edge, kind, bw=0.0, bh=0.0):
        """변 지지 조건.  bw, bh: 보 폭·춤 [m]"""
        if kind not in EDGE_TYPES:
            raise FemError(f"알 수 없는 변 지지: {kind}")
        _, has_beam, vert, rot = EDGE_TYPES[kind]
        nodes = self.edge_nodes(edge)
        along_x = edge in ("top", "bottom")
        for n in nodes:
            if vert:
                self.fixed[3 * n] = True
                self.fixed[3 * n + (1 if along_x else 2)] = True      # 변 방향 기울기도 0 (w ≡ 0)
            if rot:
                self.fixed[3 * n + (2 if along_x else 1)] = True      # 변에 직각인 회전
        if has_beam and bw > 0 and bh > self.t:
            cont = kind == "beam_c"
            i_net, j = beam_section(bw, bh, self.t, both_sides=cont)
            f = 0.5 if cont else 1.0                                   # 연속단 보: 대칭 → 강성 1/2
            ei = self.e * i_net * f
            gj = self.e / (2 * (1 + self.nu)) * j * TORSION_FACTOR * f
            length = self.a if along_x else self.b
            ke = beam_matrix(length, ei, gj)
            ib, it = (1, 2) if along_x else (2, 1)                     # 휨 회전 / 비틀림 회전 자유도
            for n1, n2 in zip(nodes[:-1], nodes[1:]):
                d = [3 * n1, 3 * n1 + ib, 3 * n1 + it, 3 * n2, 3 * n2 + ib, 3 * n2 + it]
                self.k[np.ix_(d, d)] += ke
                self.beams.append((edge, n1, n2, d, ke, f))

    def set_corner(self, ix, iy, fixed=True):
        if fixed:
            self.fixed[3 * self.nid(ix * self.nx, iy * self.ny)] = True

    # ── 하중 ─────────────────────────────────────────────────
    def _point(self, f, x, y, p):
        if not (-1e-9 <= x <= self.lx + 1e-9 and -1e-9 <= y <= self.ly + 1e-9):
            raise FemError(f"하중 위치 ({x:g}, {y:g}) 가 슬래브 밖입니다.")
        i = min(int(x / self.a), self.nx - 1)
        j = min(int(y / self.b), self.ny - 1)
        xi = 2 * (x - self.xs[i]) / self.a - 1
        eta = 2 * (y - self.ys[j]) / self.b - 1
        n = 0.25 * (1 + _XI * xi) * (1 + _ETA * eta)
        for node, w in zip(self.elem_nodes(i, j), n):
            f[3 * node] += p * w

    def load_vector(self, q=0.0, points=(), lines=(), areas=()):
        """q [kN/m²],  points (x, y, P),  lines (x1, y1, x2, y2, w kN/m),  areas (x1, y1, x2, y2, w kN/m²)"""
        f = np.zeros(self.ndof)
        if q:
            pe = q * self.a * self.b / 4.0
            for j in range(self.ny):
                for i in range(self.nx):
                    for n in self.elem_nodes(i, j):
                        f[3 * n] += pe
        for x, y, p in points:
            if p:
                self._point(f, x, y, p)
        h = min(self.a, self.b)
        for x1, y1, x2, y2, w in lines:
            length = math.hypot(x2 - x1, y2 - y1)
            if not w or length <= 0:
                continue
            m = max(int(math.ceil(length / (h / 4.0))), 1)
            for k in range(m):
                s = (k + 0.5) / m
                self._point(f, x1 + (x2 - x1) * s, y1 + (y2 - y1) * s, w * length / m)
        for x1, y1, x2, y2, w in areas:
            xa, xb, ya, yb = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
            if not w or xb - xa <= 0 or yb - ya <= 0:
                continue
            mx = max(int(math.ceil((xb - xa) / (self.a / 4.0))), 1)
            my = max(int(math.ceil((yb - ya) / (self.b / 4.0))), 1)
            pa = w * (xb - xa) * (yb - ya) / (mx * my)
            for ii in range(mx):
                for jj in range(my):
                    self._point(f, xa + (xb - xa) * (ii + 0.5) / mx, ya + (yb - ya) * (jj + 0.5) / my, pa)
        return f

    # ── 해석 ─────────────────────────────────────────────────
    def solve(self, fs):
        """fs: 하중벡터 목록 → 변위벡터 목록"""
        free = ~self.fixed
        if not self.fixed[0::3].any():
            raise FemError("수직 지지가 없습니다 — 변 또는 모서리 지지를 지정하세요.")
        kff = self.k[np.ix_(free, free)]
        rhs = np.column_stack([f[free] for f in fs])
        try:
            sol = np.linalg.solve(kff, rhs)
        except np.linalg.LinAlgError:
            raise FemError("지지 조건이 부족해 해석할 수 없습니다 (불안정 구조).") from None
        if not np.all(np.isfinite(sol)) or np.abs(sol).max() > 1e3:
            raise FemError("지지 조건이 부족해 해석할 수 없습니다 (불안정 구조).")
        out = []
        for c in range(len(fs)):
            u = np.zeros(self.ndof)
            u[free] = sol[:, c]
            out.append(u)
        return out

    def recover(self, u):
        """절점 결과 dict: w[mm], mx, my, mxy [kN·m/m], qx, qy [kN/m]  — 배열 모양 (ny+1, nx+1)
        내부 절점: 주변 요소가 그 절점에서 주는 값의 평균.
        경계 절점: 요소 중심값(정확도가 가장 좋은 점) 세 개를 지나는 2차 곡선으로 변까지 외삽."""
        nx, ny = self.nx, self.ny
        shp = (ny + 1, nx + 1)
        corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        bms = [-self.db @ _bb(xi, eta, self.a, self.b) for xi, eta in corners]      # M = -Db·κ
        bqs = [self.ds @ _bs(xi, eta, self.a, self.b) for xi, eta in corners]
        bm0 = -self.db @ _bb(0, 0, self.a, self.b)
        bq0 = self.ds @ _bs(0, 0, self.a, self.b)
        acc = np.zeros((5, self.nn))
        cnt = np.zeros(self.nn)
        cen = np.zeros((5, ny, nx))
        for j in range(ny):
            for i in range(nx):
                nodes = self.elem_nodes(i, j)
                ue = u[self._dofs(nodes)]
                cen[0:3, j, i] = bm0 @ ue
                cen[3:5, j, i] = bq0 @ ue
                for c, n in enumerate(nodes):
                    acc[0:3, n] += bms[c] @ ue
                    acc[3:5, n] += bqs[c] @ ue
                    cnt[n] += 1
        nod = (acc / cnt).reshape((5,) + shp)

        def ghost(c0, c1, c2):                 # (ghost + c0)/2 = 2차 외삽한 변 위의 값
            return (11.0 * c0 - 10.0 * c1 + 3.0 * c2) / 4.0
        if nx >= 3 and ny >= 3:
            ext = np.zeros((5, ny + 2, nx + 2))
            ext[:, 1:-1, 1:-1] = cen
            ext[:, 1:-1, 0] = ghost(cen[:, :, 0], cen[:, :, 1], cen[:, :, 2])
            ext[:, 1:-1, -1] = ghost(cen[:, :, -1], cen[:, :, -2], cen[:, :, -3])
            ext[:, 0, :] = ghost(ext[:, 1, :], ext[:, 2, :], ext[:, 3, :])
            ext[:, -1, :] = ghost(ext[:, -2, :], ext[:, -3, :], ext[:, -4, :])
            avg = 0.25 * (ext[:, :-1, :-1] + ext[:, 1:, :-1] + ext[:, :-1, 1:] + ext[:, 1:, 1:])
            for sl in ((slice(None), 0), (slice(None), -1), (0, slice(None)), (-1, slice(None))):
                nod[(slice(None),) + sl] = avg[(slice(None),) + sl]
        return {"w": (u[0::3] * 1000.0).reshape(shp), "mx": nod[0], "my": nod[1], "mxy": nod[2],
                "qx": nod[3], "qy": nod[4]}

    def beam_forces(self, u):
        """변별 보 부재력 {edge: {"s": 위치[m], "m": 모멘트[kN·m], "v": 전단[kN]}}  (정모멘트 = 아래 인장)
        이 패널의 슬래브 하중에 의한 분담분 (연속단 보는 인접 패널 분담분을 따로 더해야 함)"""
        out = {}
        for edge, n1, n2, d, ke, f in self.beams:
            fe = ke @ u[d]                        # 절점력: (V1, M1, T1, V2, M2, T2)
            o = out.setdefault(edge, {"s": [], "m": [], "v": []})
            length = self.a if edge in ("top", "bottom") else self.b
            s0 = len(o["s"]) // 2 * length
            # 요소 단부 단면력: M(시작) = -M1, M(끝) = M2  ;  V = V1 (요소 내 일정)
            o["s"] += [s0, s0 + length]
            o["m"] += [fe[1], -fe[4]]
            o["v"] += [fe[0], fe[0]]
        return out
