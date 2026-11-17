"""
basic_design/rc/slab_fem.py
슬래브 유한요소 해석 (Tk 비의존 · numpy) — 직사각형 / 다각형 / 개구부

  · 격자     x·y 격자선(간격은 달라도 됨) 위의 사각형 요소 중 '활성' 칸만 사용
              → 직각 변 다각형·사각형 개구부는 정확히, 사선 변은 계단 모양으로 근사

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
    """격자 (xs, ys) 위의 활성 칸(active[j, i])으로 이루어진 슬래브 FE 모델.
    격자 절점 (i, j) 중 활성 칸에 붙은 절점만 자유도를 가진다."""

    def __init__(self, xs, ys, active, t, e, nu=0.167):
        self.xs, self.ys = np.asarray(xs, float), np.asarray(ys, float)
        self.nx, self.ny = len(self.xs) - 1, len(self.ys) - 1
        self.active = np.asarray(active, bool)
        if self.active.shape != (self.ny, self.nx) or not self.active.any():
            raise FemError("슬래브 영역이 없습니다.")
        self.t, self.e, self.nu = t, e, nu
        self.lx, self.ly = self.xs[-1] - self.xs[0], self.ys[-1] - self.ys[0]
        used = np.zeros((self.ny + 1, self.nx + 1), bool)
        used[:-1, :-1] |= self.active
        used[:-1, 1:] |= self.active
        used[1:, :-1] |= self.active
        used[1:, 1:] |= self.active
        self.used = used
        self.nmap = -np.ones((self.ny + 1, self.nx + 1), int)
        self.nmap[used] = np.arange(int(used.sum()))
        self.nn = int(used.sum())
        self.ndof = 3 * self.nn
        self._mat = {}
        self.k = np.zeros((self.ndof, self.ndof))
        self.fixed = np.zeros(self.ndof, dtype=bool)
        self.beams = []                 # (edge_id, pos, length, dofs, ke)
        for j, i in zip(*np.nonzero(self.active)):
            d = self._dofs(self.elem_nodes(i, j))
            self.k[np.ix_(d, d)] += self.elem(i, j)[0]

    @classmethod
    def rectangle(cls, lx, ly, t, e, nu=0.167, nx=16, ny=24):
        return cls(np.linspace(0, lx, nx + 1), np.linspace(0, ly, ny + 1), np.ones((ny, nx), bool), t, e, nu)

    # ── 번호 ─────────────────────────────────────────────────
    def nid(self, i, j):
        return int(self.nmap[j, i])

    def elem_nodes(self, i, j):
        return [self.nid(i, j), self.nid(i + 1, j), self.nid(i + 1, j + 1), self.nid(i, j + 1)]

    @staticmethod
    def _dofs(nodes):
        out = []
        for n in nodes:
            out += [3 * n, 3 * n + 1, 3 * n + 2]
        return out

    def size(self, i, j):
        return self.xs[i + 1] - self.xs[i], self.ys[j + 1] - self.ys[j]

    def elem(self, i, j):
        """(Ke, Db, Ds) — 크기가 같은 요소는 한 번만 계산"""
        a, b = self.size(i, j)
        key = (round(a, 9), round(b, 9))
        if key not in self._mat:
            self._mat[key] = plate_matrices(a, b, self.e, self.nu, self.t)
        return self._mat[key]

    def is_active(self, i, j):
        return 0 <= i < self.nx and 0 <= j < self.ny and bool(self.active[j, i])

    # ── 경계 ─────────────────────────────────────────────────
    def boundary_sides(self):
        """활성 칸과 비활성(또는 바깥) 칸 사이의 변 목록.
        dict(along 'x'|'y', n1 (i, j), n2 (i, j), mid (x, y), out (i, j) 바깥쪽 칸)"""
        out = []
        xs, ys = self.xs, self.ys
        for j, i in zip(*np.nonzero(self.active)):
            for along, n1, n2, nb in (("x", (i, j), (i + 1, j), (i, j - 1)), ("x", (i, j + 1), (i + 1, j + 1), (i, j + 1)),
                                      ("y", (i, j), (i, j + 1), (i - 1, j)), ("y", (i + 1, j), (i + 1, j + 1), (i + 1, j))):
                if not self.is_active(*nb):
                    mid = ((xs[n1[0]] + xs[n2[0]]) / 2.0, (ys[n1[1]] + ys[n2[1]]) / 2.0)
                    out.append({"along": along, "n1": n1, "n2": n2, "mid": mid, "out": nb})
        return out

    def support_side(self, side, kind, bw=0.0, bh=0.0, edge_id=None, pos=0.0):
        """경계 변 하나에 지지 조건 적용.  bw, bh: 보 폭·춤 [m],  pos: 변을 따라 잰 위치(보 부재력 정렬용)"""
        if kind not in EDGE_TYPES:
            raise FemError(f"알 수 없는 변 지지: {kind}")
        _, has_beam, vert, rot = EDGE_TYPES[kind]
        along_x = side["along"] == "x"
        n1, n2 = self.nid(*side["n1"]), self.nid(*side["n2"])
        for n in (n1, n2):
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
            if along_x:
                length = self.xs[side["n2"][0]] - self.xs[side["n1"][0]]
            else:
                length = self.ys[side["n2"][1]] - self.ys[side["n1"][1]]
            ke = beam_matrix(length, ei, gj)
            ib, it = (1, 2) if along_x else (2, 1)                     # 휨 회전 / 비틀림 회전 자유도
            d = [3 * n1, 3 * n1 + ib, 3 * n1 + it, 3 * n2, 3 * n2 + ib, 3 * n2 + it]
            self.k[np.ix_(d, d)] += ke
            self.beams.append((edge_id, pos, length, d, ke))

    def fix_w(self, x, y):
        """좌표 (x, y) 의 격자 절점에 수직 지지"""
        i = int(np.argmin(np.abs(self.xs - x)))
        j = int(np.argmin(np.abs(self.ys - y)))
        if abs(self.xs[i] - x) > 1e-6 or abs(self.ys[j] - y) > 1e-6 or not self.used[j, i]:
            raise FemError(f"지지점 ({x:g}, {y:g}) 이 슬래브 절점이 아닙니다.")
        self.fixed[3 * self.nid(i, j)] = True

    # ── 하중 ─────────────────────────────────────────────────
    def locate(self, x, y):
        """(x, y) 가 속한 활성 칸 (i, j) 또는 None"""
        tol = 1e-9
        if x < self.xs[0] - tol or x > self.xs[-1] + tol or y < self.ys[0] - tol or y > self.ys[-1] + tol:
            return None
        i = min(max(int(np.searchsorted(self.xs, x, side="right")) - 1, 0), self.nx - 1)
        j = min(max(int(np.searchsorted(self.ys, y, side="right")) - 1, 0), self.ny - 1)
        ci = [i] + ([i - 1] if abs(x - self.xs[i]) < 1e-7 and i > 0 else [])
        cj = [j] + ([j - 1] if abs(y - self.ys[j]) < 1e-7 and j > 0 else [])
        for jj in cj:
            for ii in ci:
                if self.active[jj, ii]:
                    return ii, jj
        return None

    def _point(self, f, x, y, p, strict=True):
        cell = self.locate(x, y)
        if cell is None:
            if strict:
                raise FemError(f"하중 위치 ({x:g}, {y:g}) 가 슬래브 밖(또는 개구부)입니다.")
            return 0.0
        i, j = cell
        a, b = self.size(i, j)
        xi = 2 * (x - self.xs[i]) / a - 1
        eta = 2 * (y - self.ys[j]) / b - 1
        n = 0.25 * (1 + _XI * xi) * (1 + _ETA * eta)
        for node, w in zip(self.elem_nodes(i, j), n):
            f[3 * node] += p * w
        return p

    def load_vector(self, q=0.0, points=(), lines=(), areas=()):
        """q [kN/m²],  points (x, y, P),  lines (x1, y1, x2, y2, w kN/m),  areas (x1, y1, x2, y2, w kN/m²)
        라인·면 하중 중 슬래브 밖/개구부에 걸친 부분은 재하하지 않는다."""
        f = np.zeros(self.ndof)
        if q:
            for j, i in zip(*np.nonzero(self.active)):
                a, b = self.size(i, j)
                for n in self.elem_nodes(i, j):
                    f[3 * n] += q * a * b / 4.0
        for x, y, p in points:
            if p:
                self._point(f, x, y, p)
        h = min(float(np.diff(self.xs).min()), float(np.diff(self.ys).min()))
        hx, hy = float(np.diff(self.xs).mean()), float(np.diff(self.ys).mean())
        for x1, y1, x2, y2, w in lines:
            length = math.hypot(x2 - x1, y2 - y1)
            if not w or length <= 0:
                continue
            m = max(int(math.ceil(length / (max(h, min(hx, hy) / 2.0) / 4.0))), 1)
            for k in range(m):
                s = (k + 0.5) / m
                self._point(f, x1 + (x2 - x1) * s, y1 + (y2 - y1) * s, w * length / m, strict=False)
        for x1, y1, x2, y2, w in areas:
            xa, xb, ya, yb = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
            if not w or xb - xa <= 0 or yb - ya <= 0:
                continue
            mx = max(int(math.ceil((xb - xa) / (hx / 4.0))), 1)
            my = max(int(math.ceil((yb - ya) / (hy / 4.0))), 1)
            pa = w * (xb - xa) * (yb - ya) / (mx * my)
            for ii in range(mx):
                for jj in range(my):
                    self._point(f, xa + (xb - xa) * (ii + 0.5) / mx, ya + (yb - ya) * (jj + 0.5) / my, pa, strict=False)
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
        """절점 결과 dict: w[mm], mx, my, mxy [kN·m/m], qx, qy [kN/m]  — 배열 모양 (ny+1, nx+1), 슬래브 밖은 NaN
        내부 절점: 주변 요소가 그 절점에서 주는 값의 평균.
        경계 절점: 주변 요소 중심값(정확도가 가장 좋은 점)에 2차 곡면을 맞춰 변까지 외삽."""
        nx, ny = self.nx, self.ny
        shp = (ny + 1, nx + 1)
        corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        ops = {}
        acc = np.zeros((5, self.nn))
        cnt = np.zeros(self.nn)
        cen = np.full((5, ny, nx), np.nan)
        for j, i in zip(*np.nonzero(self.active)):
            a, b = self.size(i, j)
            key = (round(a, 9), round(b, 9))
            if key not in ops:
                _, db, ds = self.elem(i, j)
                ops[key] = ([np.vstack([-db @ _bb(xi, eta, a, b), ds @ _bs(xi, eta, a, b)]) for xi, eta in corners],
                            np.vstack([-db @ _bb(0, 0, a, b), ds @ _bs(0, 0, a, b)]))      # M = -Db·κ, Q = Ds·γ
            oc, o0 = ops[key]
            nodes = self.elem_nodes(i, j)
            ue = u[self._dofs(nodes)]
            cen[:, j, i] = o0 @ ue
            for c, n in enumerate(nodes):
                acc[:, n] += oc[c] @ ue
                cnt[n] += 1
        nod = np.full((5,) + shp, np.nan)
        nod[:, self.used] = acc / cnt
        w = np.full(shp, np.nan)
        w[self.used] = u[0::3] * 1000.0
        # 경계 절점 외삽
        xc = (self.xs[:-1] + self.xs[1:]) / 2.0
        yc = (self.ys[:-1] + self.ys[1:]) / 2.0
        full = np.zeros(shp, bool)                       # 네 칸이 모두 활성인 절점
        full[1:-1, 1:-1] = self.active[:-1, :-1] & self.active[:-1, 1:] & self.active[1:, :-1] & self.active[1:, 1:]
        hx, hy = float(np.diff(self.xs).mean()), float(np.diff(self.ys).mean())
        for j, i in zip(*np.nonzero(self.used & ~full)):
            i0, i1 = max(i - 3, 0), min(i + 3, nx)
            j0, j1 = max(j - 3, 0), min(j + 3, ny)
            sub = self.active[j0:j1, i0:i1]
            if sub.sum() < 3:
                continue
            jj, ii = np.nonzero(sub)
            px = (xc[i0:i1][ii] - self.xs[i]) / hx
            py = (yc[j0:j1][jj] - self.ys[j]) / hy
            vals = cen[:, j0:j1, i0:i1][:, jj, ii].T                     # (점, 5)
            wgt = 1.0 / (1.0 + px * px + py * py)                        # 가까운 점에 더 큰 가중
            for basis in (np.column_stack([np.ones_like(px), px, py, px * px, px * py, py * py]),
                          np.column_stack([np.ones_like(px), px, py])):
                if len(px) < basis.shape[1] + 2:
                    continue
                am = basis * wgt[:, None]
                if np.linalg.matrix_rank(am) < basis.shape[1]:
                    continue
                coef = np.linalg.lstsq(am, vals * wgt[:, None], rcond=None)[0]
                nod[:, j, i] = coef[0]
                break
        return {"w": w, "mx": nod[0], "my": nod[1], "mxy": nod[2], "qx": nod[3], "qy": nod[4]}

    def beam_forces(self, u):
        """변(edge_id)별 보 부재력 {edge_id: {"s": 위치[m], "m": 모멘트[kN·m], "v": 전단[kN]}}  (정모멘트 = 아래 인장)
        이 패널의 슬래브 하중에 의한 분담분 (연속단 보는 인접 패널 분담분을 따로 더해야 함)"""
        out = {}
        for edge, pos, length, d, ke in sorted(self.beams, key=lambda b: (str(b[0]), b[1])):
            fe = ke @ u[d]                        # 절점력: (V1, M1, T1, V2, M2, T2)
            o = out.setdefault(edge, {"s": [], "m": [], "v": []})
            # 요소 단부 단면력: M(시작) = -M1 … 부호를 정모멘트(+) 로 맞춤
            o["s"] += [pos - length / 2.0, pos + length / 2.0]
            o["m"] += [fe[1], -fe[4]]
            o["v"] += [fe[0], fe[0]]
        return out
