"""
design_2d/plan/solver.py — 평면 유한요소해석 (슬래브 판요소 + 격자보)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【자유도】 절점당 [w, βx, βy]   (w: 연직 위 +,  β: 회전 → u = z·βx, v = z·βy)
          박판 극한에서 βx = -∂w/∂x, βy = -∂w/∂y
          (전체 회전 θx = -βy, θy = βx)
【판요소】 MITC4 (Bathe-Dvorkin) — 두께에 무관하게 전단잠김 없음
          휨: 2×2 Gauss, 전단: 가정 공변 전단변형률(변 중앙 tying)
【보요소】 격자보: 휨(E-B) + 비틀림(GJ). 편심(T형보 효과) 미고려
【지점】   Dz/Rx/Ry 구속 + 스프링 + 기둥 회전스프링 k = n·4EI/H
【결과】   슬래브: Mx, My, Mxy (+ = 하부 인장), Qx, Qy (kN/m), 처짐 δ (mm, ↓+)
          보: M (+ = 하부 인장), V, T   / 반력: Rz(↑+), Mx, My
【풀이】   scipy 가 있으면 희소행렬, 없으면 RCM 재배열 + 밴드 Cholesky
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import math
import numpy as np

from . import model as pm
from .mesh import build_mesh, LoadBuilder, MeshError

KAPPA = 5.0 / 6.0
_G2 = (-1 / math.sqrt(3), 1 / math.sqrt(3))
_NAT = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], dtype=float)


class PlanError(Exception):
    pass


# ═══════════════════════════════════════════════════════════════
#  MITC4 판요소
# ═══════════════════════════════════════════════════════════════
def _dN(xi, eta):
    return 0.25 * np.array([[-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)],
                            [-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)]])


def _N(xi, eta):
    return 0.25 * np.array([(1 - xi) * (1 - eta), (1 + xi) * (1 - eta),
                            (1 + xi) * (1 + eta), (1 - xi) * (1 + eta)])


def _Bb(X, xi, eta):
    """휨 곡률 B (3×12): κ = [βx,x ; βy,y ; βx,y + βy,x]"""
    dn = _dN(xi, eta)
    J = dn @ X
    dxy = np.linalg.solve(J, dn)          # (2,4)  [∂N/∂x; ∂N/∂y]
    B = np.zeros((3, 12))
    for a in range(4):
        B[0, 3 * a + 1] = dxy[0, a]
        B[1, 3 * a + 2] = dxy[1, a]
        B[2, 3 * a + 1] = dxy[1, a]
        B[2, 3 * a + 2] = dxy[0, a]
    return B, J


def _Bs(X, xi, eta):
    """MITC4 가정 전단변형률 B (2×12): [γx; γy]"""
    # 변 중앙 tying 점의 공변 전단변형률 (12 계수)
    def g_xi(i, j):            # 변 i→j (ξ 방향), γξ = (w_j - w_i)/2 + β_avg · (X_j - X_i)/2
        r = np.zeros(12)
        r[3 * i] -= 0.5; r[3 * j] += 0.5
        dx, dy = (X[j] - X[i]) / 2.0
        for k in (i, j):
            r[3 * k + 1] += 0.5 * dx
            r[3 * k + 2] += 0.5 * dy
        return r
    gA = g_xi(0, 1)            # A (0,-1)  변 1-2
    gC = g_xi(3, 2)            # C (0, 1)  변 4-3
    gD = g_xi(0, 3)            # D (-1,0)  변 1-4 (η 방향)
    gB = g_xi(1, 2)            # B (1, 0)  변 2-3
    gxi = 0.5 * (1 - eta) * gA + 0.5 * (1 + eta) * gC
    geta = 0.5 * (1 - xi) * gD + 0.5 * (1 + xi) * gB
    J = _dN(xi, eta) @ X
    Jinv = np.linalg.inv(J)
    return Jinv @ np.vstack([gxi, geta]), J


def plate_k(X, E, nu, t):
    """반환: K(12×12), 응력행렬 S(4 GP, 5, 12) [Mx,My,Mxy (+하부인장), Qx,Qy], GP 좌표(4,2)"""
    Db = E * t ** 3 / (12 * (1 - nu ** 2)) * np.array([[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2]])
    Ds = KAPPA * E / (2 * (1 + nu)) * t * np.eye(2)
    K = np.zeros((12, 12))
    S = np.zeros((4, 5, 12)); P = np.zeros((4, 2))
    g = 0
    for xi in _G2:
        for eta in _G2:
            Bb, J = _Bb(X, xi, eta)
            Bs, _ = _Bs(X, xi, eta)
            dJ = np.linalg.det(J)
            if dJ <= 0:
                raise PlanError("찌그러진 슬래브 요소가 있습니다 (면 형상 확인).")
            K += (Bb.T @ Db @ Bb + Bs.T @ Ds @ Bs) * dJ
            S[g, :3] = -(Db @ Bb); S[g, 3:] = Ds @ Bs
            P[g] = _N(xi, eta) @ X
            g += 1
    return K, S, P


# ═══════════════════════════════════════════════════════════════
#  격자보 요소
# ═══════════════════════════════════════════════════════════════
def beam_k(xa, xb, EI, GJ):
    """DOF [w1, βx1, βy1, w2, βx2, βy2] → 6×6 + 변환정보"""
    dx, dy = xb - xa
    L = math.hypot(dx, dy)
    c, s = dx / L, dy / L
    # 국부: [w1, φ1, w2, φ2] (φ = dw/dx' = -(c βx + s βy)),  비틀림 [ψ1, ψ2] (ψ = s βx - c βy)
    kb = EI / L ** 3 * np.array([[12, 6 * L, -12, 6 * L],
                                 [6 * L, 4 * L * L, -6 * L, 2 * L * L],
                                 [-12, -6 * L, 12, -6 * L],
                                 [6 * L, 2 * L * L, -6 * L, 4 * L * L]])
    Tb = np.zeros((4, 6))
    Tb[0, 0] = 1; Tb[1, 1] = -c; Tb[1, 2] = -s
    Tb[2, 3] = 1; Tb[3, 4] = -c; Tb[3, 5] = -s
    kt = GJ / L * np.array([[1, -1], [-1, 1]])
    Tt = np.zeros((2, 6))
    Tt[0, 1] = s; Tt[0, 2] = -c; Tt[1, 4] = s; Tt[1, 5] = -c
    K = Tb.T @ kb @ Tb + Tt.T @ kt @ Tt
    return K, (kb, Tb, kt, Tt, L)


# ═══════════════════════════════════════════════════════════════
#  선형 풀이 (scipy 또는 밴드 Cholesky)
# ═══════════════════════════════════════════════════════════════
def _rcm(nn, edges):
    adj = [[] for _ in range(nn)]
    for a, b in edges:
        adj[a].append(b); adj[b].append(a)
    deg = [len(set(x)) for x in adj]
    adj = [sorted(set(x), key=lambda v: deg[v]) for x in adj]
    seen = [False] * nn
    order = []
    for start in sorted(range(nn), key=lambda v: deg[v]):
        if seen[start]:
            continue
        seen[start] = True
        q = [start]; k = 0
        while k < len(q):
            v = q[k]; k += 1
            for w in adj[v]:
                if not seen[w]:
                    seen[w] = True; q.append(w)
        order += q
    return order[::-1]


def _band_solve(rows, cols, vals, n, rhs, nb=64):
    """대칭 양정치 밴드 행렬 블록 Cholesky (BLAS 행렬곱 사용).
    rows/cols/vals: 삼중항(중복 합산), rhs: (n, k)"""
    bw = int(np.abs(rows - cols).max()) if len(rows) else 0
    s = nb + bw
    npad = n + s
    FB = np.zeros((npad, 2 * bw + 1))
    np.add.at(FB, (rows, cols - rows + bw), vals)
    FB[n:, bw] = 1.0                                   # 패딩: 단위행렬
    ii, kk = np.meshgrid(np.arange(s), np.arange(s), indexing="ij")
    msk = np.abs(kk - ii) <= bw
    I_, K_ = ii[msk], kk[msk]
    blocks = []
    for j in range(0, n, nb):
        S = np.zeros((s, s))
        S[I_, K_] = FB[j + I_, K_ - I_ + bw]
        try:
            L11 = np.linalg.cholesky(S[:nb, :nb])
        except np.linalg.LinAlgError:
            raise PlanError("불안정 구조입니다 (강성행렬이 양정치가 아님).\n"
                            "지점 조건과 부재 연결을 확인하세요.")
        if np.diag(L11).min() <= 1e-7 * np.sqrt(np.abs(np.diag(S[:nb, :nb])).max()):
            raise PlanError("불안정 구조입니다. 지점 조건과 부재 연결을 확인하세요.")
        L21 = np.linalg.solve(L11, S[nb:, :nb].T).T
        S[nb:, nb:] -= L21 @ L21.T
        sub = (I_ >= nb) & (K_ >= nb)
        FB[j + I_[sub], K_[sub] - I_[sub] + bw] = S[I_[sub], K_[sub]]
        blocks.append((L11, L21))
    k = rhs.shape[1] if rhs.ndim == 2 else 1
    y = np.zeros((npad, k)); y[:n] = rhs.reshape(n, k)
    for b, j in enumerate(range(0, n, nb)):
        L11, L21 = blocks[b]
        y[j:j + nb] = np.linalg.solve(L11, y[j:j + nb])
        y[j + nb:j + s] -= L21 @ y[j:j + nb]
    x = y
    for b in range(len(blocks) - 1, -1, -1):
        j = b * nb
        L11, L21 = blocks[b]
        x[j:j + nb] = np.linalg.solve(L11.T, x[j:j + nb] - L21.T @ x[j + nb:j + s])
    return x[:n].reshape(rhs.shape)


def _solve(rows, cols, vals, n, rhs, order):
    """rows/cols: 원래 자유도 번호(0..n-1). order: 재배열 (새 → 옛)"""
    try:
        import scipy.sparse as sp
        import scipy.sparse.linalg as spl
        K = sp.csc_matrix((vals, (rows, cols)), shape=(n, n))
        lu = spl.splu(K)
        x = lu.solve(rhs)
        if not np.all(np.isfinite(x)):
            raise PlanError("불안정 구조입니다. 지점 조건과 부재 연결을 확인하세요.")
        d = np.abs(lu.U.diagonal())
        if d.min() < 1e-10 * d.max():
            raise PlanError("불안정 구조입니다. 지점 조건과 부재 연결을 확인하세요.")
        return x
    except ImportError:
        pass
    inv = np.empty(n, dtype=int); inv[order] = np.arange(n)
    xs = _band_solve(inv[rows], inv[cols], vals, n, rhs[order])
    out = np.empty_like(xs); out[order] = xs
    return out


# ═══════════════════════════════════════════════════════════════
#  해석
# ═══════════════════════════════════════════════════════════════
def _plate_props(m, aid):
    sl = m["slabs"][m["areas"][aid]["slab"]]
    mat = m["materials"].get(sl["mat"])
    if mat is None:
        raise PlanError(f"슬래브 '{sl['name']}': 재료가 없습니다.")
    E = pm.material_E(mat) * 1e3
    nu = float(mat.get("nu", 0.2) or 0.2)
    t = float(sl["t"]) / 1000.0
    if t <= 0:
        raise PlanError(f"슬래브 '{sl['name']}': 두께가 0 입니다.")
    return E, nu, t


def analyze(m):
    """모든 하중케이스 + 조합 해석. 반환 dict(mesh, results{key: res}, warnings)"""
    if not m["lines"] and not m["areas"]:
        raise PlanError("부재가 없습니다.")
    try:
        mesh = build_mesh(m)
    except MeshError as ex:
        raise PlanError(str(ex))
    nn = len(mesh.xy)
    if nn == 0 or (not len(mesh.plates) and not len(mesh.beams)):
        raise PlanError("보 또는 슬래브로 적용된 부재가 없습니다.\n선/면을 선택해 부재로 적용하세요.")
    ndof = 3 * nn
    R, C, V = [], [], []
    edges = []
    ne = len(mesh.plates)
    pS = np.zeros((ne, 4, 5, 12)); pP = np.zeros((ne, 4, 2))
    pD = np.zeros((ne, 12), dtype=int)
    props = {}
    for e, (nodes, aid) in enumerate(zip(mesh.plates, mesh.plate_area)):
        X = mesh.xy[nodes]
        if aid not in props:
            props[aid] = _plate_props(m, aid)
        E, nu, t = props[aid]
        K, pS[e], pP[e] = plate_k(X, E, nu, t)
        dofs = np.array([3 * n + k for n in nodes for k in range(3)])
        pD[e] = dofs
        R.append(np.repeat(dofs, 12)); C.append(np.tile(dofs, 12)); V.append(K.ravel())
        for i in range(4):
            edges.append((nodes[i], nodes[(i + 1) % 4])); edges.append((nodes[i], nodes[(i + 2) % 4]))
    bdata = []
    tf = float(m.get("torsion_factor", 1.0) or 0.0)
    for (a, b), lid in zip(mesh.beams, mesh.beam_line):
        ln = m["lines"][lid]
        sec = m["sections"][ln["sec"]]
        mat = m["materials"].get(ln["mat"])
        if mat is None:
            raise PlanError(f"보 L{lid}: 재료가 없습니다.")
        E = pm.material_E(mat) * 1e3
        nu = float(mat.get("nu", 0.2) or 0.2)
        G = E / (2 * (1 + nu))
        A, I = pm.section_props(sec)
        if I <= 0:
            raise PlanError(f"보 L{lid}: 단면 '{sec['name']}' 성질이 0 입니다.")
        J = pm.torsion_J(sec)
        K, info = beam_k(mesh.xy[a], mesh.xy[b], E * I * 1e-12, G * J * 1e-12 * tf)
        dofs = np.array([3 * a + k for k in range(3)] + [3 * b + k for k in range(3)])
        R.append(np.repeat(dofs, 6)); C.append(np.tile(dofs, 6)); V.append(K.ravel())
        bdata.append((dofs, K, info))
        edges.append((a, b))
    rows = np.concatenate(R); cols = np.concatenate(C); vals = np.concatenate(V)

    # ── 지점 ──
    fixed = np.zeros(ndof, dtype=bool)
    spring = np.zeros(ndof)
    sup_nodes = {}
    # 선 지점(벽체 등): 선 위 모든 FE 절점에 같은 구속 (기둥 스프링 제외)
    line_sup = {}
    for lid, sid in m.get("line_supports", {}).items():
        ch = mesh.line_chain_all.get(lid)
        st = m["sup_types"].get(sid)
        if not ch or st is None:
            continue
        for k in ch:
            b = 3 * k
            if st.get("dz"): fixed[b] = True
            if st.get("rx"): fixed[b + 2] = True
            if st.get("ry"): fixed[b + 1] = True
        line_sup[lid] = ch
    for nid, sid in m["supports"].items():
        st = m["sup_types"].get(sid)
        k = mesh.node_of.get(nid)
        if st is None or k is None:
            continue
        sup_nodes[nid] = k
        b = 3 * k
        if st.get("dz"): fixed[b] = True
        if st.get("rx"): fixed[b + 2] = True        # θx = -βy
        if st.get("ry"): fixed[b + 1] = True        # θy =  βx
        spring[b] += float(st.get("kz", 0) or 0)
        krx = float(st.get("krx", 0) or 0); kry = float(st.get("kry", 0) or 0)
        if st.get("col"):
            cm = m["materials"].get(int(st.get("col_mat", 1)), m["materials"][min(m["materials"])])
            Ec = pm.material_E(cm) * 1e3
            bb, hh = float(st.get("col_b", 500)) / 1000, float(st.get("col_h", 500)) / 1000
            H = max(float(st.get("col_H", 3.5)), 1e-3)
            n = int(st.get("col_n", 1) or 1)
            krx += n * 4 * Ec * (bb * hh ** 3 / 12) / H     # X축 회전 → Y방향 휨
            kry += n * 4 * Ec * (hh * bb ** 3 / 12) / H
        spring[b + 2] += krx
        spring[b + 1] += kry
    if not fixed.any() and not spring.any():
        raise PlanError("지점이 없습니다.")

    # 강성 없는 자유도 (예: 판에 속하지 않은 보 끝 회전 등) 확인
    diag = np.zeros(ndof); np.add.at(diag, rows[rows == cols], vals[rows == cols])
    diag += spring
    weak = (~fixed) & (np.abs(diag) < 1e-9 * max(np.abs(diag).max(), 1))
    fixed |= weak

    # 회전 자유도 안정화: 직선 보만 있는 곳의 비틀림 기구(축 회전) 등 방지.
    # 실제 강성 대비 1e-9 수준이라 결과에 영향 없음
    rot = np.zeros(ndof, dtype=bool); rot[1::3] = True; rot[2::3] = True
    if (rot & ~fixed).any():
        kref = np.abs(diag[rot]).max()
        spring[rot & ~fixed] += 1e-9 * kref

    free = np.where(~fixed)[0]
    fmap = -np.ones(ndof, dtype=int); fmap[free] = np.arange(len(free))
    sel = (~fixed[rows]) & (~fixed[cols])
    fr, fc, fv = fmap[rows[sel]], fmap[cols[sel]], vals[sel]
    sp_idx = free[spring[free] > 0]
    fr = np.concatenate([fr, fmap[sp_idx]]); fc = np.concatenate([fc, fmap[sp_idx]])
    fv = np.concatenate([fv, spring[sp_idx]])
    # 절점 RCM → 자유도 순서
    norder = _rcm(nn, edges)
    dorder = [fmap[3 * v + k] for v in norder for k in range(3) if fmap[3 * v + k] >= 0]

    # ── 하중 ──
    lb = LoadBuilder(m, mesh)
    case_ids = list(m["cases"])
    F = np.zeros((ndof, len(case_ids)))
    lost = {}
    BEs = []
    for j, cid in enumerate(case_ids):
        fw, ls, be = lb.build(cid)
        F[0::3, j] = -fw                 # ↓+ 입력 → w 방향 -
        for e, (dofs, K, (kb, Tb, kt, Tt, L)) in enumerate(bdata):
            if be[e].any():
                F[dofs, j] += Tb.T @ _beam_feq(L, -be[e, 0], -be[e, 1])
        BEs.append(be)
        if ls > 1e-9:
            lost[cid] = ls
    if len(free) == 0:
        raise PlanError("자유도가 없습니다.")
    Uf = _solve(fr, fc, fv, len(free), F[free], np.array(dorder))
    if Uf.ndim == 1:
        Uf = Uf[:, None]
    U = np.zeros((ndof, len(case_ids)))
    U[free] = Uf

    # 반력: K_elem·U - F (+ 스프링 힘)
    KU = np.zeros_like(U)
    np.add.at(KU, rows, vals[:, None] * U[cols])
    Rf = KU - F            # 스프링 자유도는 -k·u (= 스프링 반력)
    applied = {cid: float(-F[0::3, j].sum()) for j, cid in enumerate(case_ids)}

    results = {}
    for j, cid in enumerate(case_ids):
        results[("case", cid)] = _post(m, mesh, U[:, j], Rf[:, j], (pS, pP, pD), bdata, sup_nodes, line_sup, BEs[j])
    for coid, co in m["combos"].items():
        fac = co.get("factors", {})
        u = sum(U[:, case_ids.index(c)] * f for c, f in fac.items() if c in case_ids) if fac else None
        if u is None or np.isscalar(u):
            continue
        rf = sum(Rf[:, case_ids.index(c)] * f for c, f in fac.items() if c in case_ids)
        be = sum(BEs[case_ids.index(c)] * f for c, f in fac.items() if c in case_ids)
        results[("combo", coid)] = _post(m, mesh, u, rf, (pS, pP, pD), bdata, sup_nodes, line_sup, be)
    warnings = list(mesh.warnings)
    for cid, ls in lost.items():
        warnings.append(f"[{m['cases'][cid]['name']}] 전달되지 않은 하중 {ls:.2f} kN "
                        f"(부재와 연결되지 않은 노드·선·면의 하중)")
    if weak.any():
        warnings.append(f"강성이 없는 자유도 {int(weak.sum())}개를 자동 구속했습니다.")
    return {"mesh": mesh, "results": results, "warnings": warnings,
            "ndof": ndof, "nfree": len(free), "applied": applied}


def _spr(mesh, gp_xy, gp_v):
    """초수렴 패치 복원(SPR, Zienkiewicz-Zhu): 절점 주변 요소 Gauss 점 값에
    1차식을 최소제곱으로 맞춰 절점값 계산. 경계 절점은 이웃 내부 절점 패치식으로 외삽."""
    nn = len(mesh.xy)
    nq = gp_v.shape[2]
    out = np.full((nn, nq), np.nan)
    if not len(mesh.plates):
        return out
    patch = {}
    for e, nodes in enumerate(mesh.plates):
        for n in nodes:
            patch.setdefault(int(n), []).append(e)
    # 면(슬래브 영역)이 바뀌는 곳(두께 다름)은 같은 면 요소만 사용
    area = np.array(mesh.plate_area)
    coef = {}
    for n, els in patch.items():
        if len(els) < 4:
            continue
        if len(set(area[els])) > 1:
            continue
        P = gp_xy[els].reshape(-1, 2) - mesh.xy[n]
        A = np.column_stack([np.ones(len(P)), P])
        if np.linalg.matrix_rank(A) < 3:
            continue
        c, *_ = np.linalg.lstsq(A, gp_v[els].reshape(-1, nq), rcond=None)
        coef[n] = c
        out[n] = c[0]
    nb = {}
    for e, nodes in enumerate(mesh.plates):
        for n in nodes:
            nb.setdefault(int(n), set()).update(int(x) for x in nodes)
    for n, els in patch.items():
        if n in coef:
            continue
        vals = []
        for k in nb[n]:
            if k in coef:
                d = mesh.xy[n] - mesh.xy[k]
                vals.append(coef[k][0] + coef[k][1] * d[0] + coef[k][2] * d[1])
        if vals:
            out[n] = np.mean(vals, axis=0)
        else:                                   # 패치가 없으면 Gauss 점 평균
            out[n] = gp_v[els].reshape(-1, nq).mean(axis=0)
    return out


def _beam_feq(L, p0, p1):
    """선형 분포하중 p (w 방향 +)의 일관 절점하중 [Fz1, M1, Fz2, M2]"""
    return np.array([L * (7 * p0 + 3 * p1) / 20, L * L * (3 * p0 + 2 * p1) / 60,
                     L * (3 * p0 + 7 * p1) / 20, -L * L * (2 * p0 + 3 * p1) / 60])


def _post(m, mesh, u, rf, pdata, bdata, sup_nodes, line_sup=None, BE=None):
    nn = len(mesh.xy)
    w = u[0::3]
    out = {"w": w.copy(), "u": u.copy()}
    # ── 슬래브 절점값 (요소별 절점 평가 후 평균) ──
    keys = ("Mx", "My", "Mxy", "Qx", "Qy")
    pS, pP, pD = pdata
    gp_v = np.einsum("egij,ej->egi", pS, u[pD]) if len(pD) else np.zeros((0, 4, 5))
    nodal = _spr(mesh, pP, gp_v)
    for i, k in enumerate(keys):
        out[k] = nodal[:, i]
    # ── 보 ──
    beams = {}
    for e, ((dofs, K, (kb, Tb, kt, Tt, L)), lid) in enumerate(zip(bdata, mesh.beam_line)):
        ue = u[dofs]
        p0, p1 = (-BE[e, 0], -BE[e, 1]) if BE is not None else (0.0, 0.0)
        f = kb @ (Tb @ ue) - _beam_feq(L, p0, p1)     # [Fz1, M1, Fz2, M2] (부재에 작용)
        tq = kt @ (Tt @ ue)
        d = beams.setdefault(lid, {"s": [], "M": [], "V": [], "T": []})
        s0 = d["s"][-1] if d["s"] else 0.0
        for x in (0.0, L / 2, L):
            ip = p0 * x + (p1 - p0) / L * x * x / 2                 # ∫p
            imp = p0 * x * x / 2 + (p1 - p0) / L * x ** 3 / 6      # ∫(x-s)p
            d["s"].append(s0 + x)
            d["M"].append(-f[1] + x * f[0] + imp)
            d["V"].append(f[0] + ip)
            d["T"].append(-tq[0])
    for d in beams.values():
        for k in d:
            d[k] = np.array(d[k])
    out["beams"] = beams
    # ── 반력 ──
    out["react"] = {nid: (float(rf[3 * k]), float(-rf[3 * k + 2]), float(rf[3 * k + 1]))
                    for nid, k in sup_nodes.items()}      # (Rz, Mx=θx방향, My=θy방향)
    # 선 지점 반력: 선 전체 합 + 분포 (kN/m 근사는 표시용)
    lr = {}
    share = {}
    for lid, ch in (line_sup or {}).items():
        for k in ch:
            share[k] = share.get(k, 0) + 1
    for lid, ch in (line_sup or {}).items():
        rz = np.array([rf[3 * k] / share[k] for k in ch])   # 여러 선이 공유하는 절점은 나눠서 합산
        lr[lid] = {"Rz": float(rz.sum()), "nodes": list(ch), "rz": rz}
    out["line_react"] = lr
    return out


def summary(res, mesh, m):
    """면별·보별 최대값 요약"""
    rows_slab = []
    if len(mesh.plates):
        for aid in sorted(set(mesh.plate_area)):
            els = [e for e, a in enumerate(mesh.plate_area) if a == aid]
            nodes = np.unique(mesh.plates[els].ravel())
            r = {"area": aid}
            for k in ("Mx", "My", "Qx", "Qy"):
                v = res[k][nodes]
                r[k + "+"] = float(np.nanmax(v)); r[k + "-"] = float(np.nanmin(v))
            r["d"] = float(np.max(-res["w"][nodes])) * 1000
            rows_slab.append(r)
    rows_beam = []
    for lid, d in sorted(res["beams"].items()):
        rows_beam.append({"line": lid, "M+": float(d["M"].max()), "M-": float(d["M"].min()),
                          "V": float(np.abs(d["V"]).max()), "T": float(np.abs(d["T"]).max()),
                          "L": float(d["s"][-1])})
    return rows_slab, rows_beam
