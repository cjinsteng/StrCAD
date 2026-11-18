"""
design_2d/section/solver.py  ── 2D 프레임 강성도법 (Euler-Bernoulli, 3 DOF/절점)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【좌표계】  전체 X→, Y↑ / 부재 국부 x: i→j,  국부 y: x 를 반시계 90° 회전
【자유도】  [ux, uy, θz]   θz 반시계 = +

【부호 규약 (결과)】
  N : 인장 +
  V : 왼쪽 자유물체의 오른쪽 면에서 -y 방향 = +  (단순보 좌단 +)
  M : 국부 y 기준 하부(-y) 인장 = +  (수평보 정모멘트 = 하부인장)
  반력 : 전체좌표 방향 +  (Ry > 0 = 위쪽)

【부재하중】 등가절점하중 = ∫Nᵀq dx (Hermite 형상함수, Gauss 적분)
           → 균일 단면 E-B 보에서 고정단력과 정확히 일치
【단부조건】 고정률 r (0=힌지, 1=강접, 사이=반강접 회전스프링 ks=3EI·r/(L(1-r)))
            → 내부 회전 DOF 를 정적 응축(static condensation)
【지점】     구속(Dx, Dy, Rz) + 스프링(kx, ky, kr) + 회전 고정률 r (0~1)
            kr = r/(1-r) · Σ(3EI/L)   (연결부재 기준, Monforton-Wu 고정도)

【단위】 m, kN, kN·m  (E: MPa → kN/m², 단면: mm → m)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import math
import numpy as np

from .model import material_E, section_props, elem_length, end_fix, clamp01

N_SEG = 40                       # 부재당 기본 분할수 (결과 그래프용)
_GP = np.polynomial.legendre.leggauss(6)


class FrameError(Exception):
    pass


# ═══════════════════════════════════════════════════════════════
#  요소 행렬
# ═══════════════════════════════════════════════════════════════
def _k_local(E, A, I, L):
    k = np.zeros((6, 6))
    ea = E * A / L
    c1 = 12 * E * I / L ** 3; c2 = 6 * E * I / L ** 2
    c3 = 4 * E * I / L;       c4 = 2 * E * I / L
    k[0, 0] = k[3, 3] = ea; k[0, 3] = k[3, 0] = -ea
    k[1, 1] = c1;  k[1, 2] = c2;  k[1, 4] = -c1; k[1, 5] = c2
    k[2, 1] = c2;  k[2, 2] = c3;  k[2, 4] = -c2; k[2, 5] = c4
    k[4, 1] = -c1; k[4, 2] = -c2; k[4, 4] = c1;  k[4, 5] = -c2
    k[5, 1] = c2;  k[5, 2] = c4;  k[5, 4] = -c2; k[5, 5] = c3
    return k


def _T(c, s):
    t = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1.0]])
    T = np.zeros((6, 6))
    T[:3, :3] = t; T[3:, 3:] = t
    return T


def _shape(x, L):
    """국부 형상함수 행렬 2×6 (행0: 축방향 u, 행1: 횡방향 v)"""
    xi = x / L
    N = np.zeros((2, 6))
    N[0, 0] = 1 - xi; N[0, 3] = xi
    N[1, 1] = 1 - 3 * xi ** 2 + 2 * xi ** 3
    N[1, 2] = L * (xi - 2 * xi ** 2 + xi ** 3)
    N[1, 4] = 3 * xi ** 2 - 2 * xi ** 3
    N[1, 5] = L * (-xi ** 2 + xi ** 3)
    return N


# ═══════════════════════════════════════════════════════════════
#  부재 하중 → 국부 성분
# ═══════════════════════════════════════════════════════════════
def _dir_to_local(d, val, c, s):
    """방향 코드와 크기 → (qx_local, qy_local)"""
    if d == "G":
        gx, gy = 0.0, -val
    elif d == "GX":
        gx, gy = val, 0.0
    elif d == "GY":
        gx, gy = 0.0, val
    elif d == "LX":
        return val, 0.0
    else:   # "LY"
        return 0.0, val
    return gx * c + gy * s, -gx * s + gy * c


def _member_loads(model, eid, case_id, L, c, s, A_m2, gamma, sw):
    """해당 하중케이스의 부재하중을 국부좌표 리스트로 변환
    반환: dists [(a, b, qx1, qy1, qx2, qy2)], points [(a, Px, Py)]"""
    dists, points = [], []
    for ld in model["eloads"]:
        if ld["elem"] != eid or ld["case"] != case_id:
            continue
        rel = bool(ld.get("rel"))
        if ld["kind"] == "point":
            a = float(ld.get("a", 0.5)) * (L if rel else 1.0)
            a = min(max(a, 0.0), L)
            px, py = _dir_to_local(ld.get("dir", "G"), float(ld.get("p", 0)), c, s)
            points.append((a, px, py))
        else:
            a = float(ld.get("a", 0)) * (L if rel else 1.0)
            b = float(ld.get("b", 1 if rel else L)) * (L if rel else 1.0)
            a = min(max(a, 0.0), L); b = min(max(b, 0.0), L)
            if b - a < 1e-9:
                continue
            x1, y1 = _dir_to_local(ld.get("dir", "G"), float(ld.get("w1", 0)), c, s)
            x2, y2 = _dir_to_local(ld.get("dir", "G"), float(ld.get("w2", ld.get("w1", 0))), c, s)
            dists.append((a, b, x1, y1, x2, y2))
    if sw and gamma > 0 and A_m2 > 0:
        w = sw * gamma * A_m2
        qx, qy = _dir_to_local("G", w, c, s)
        dists.append((0.0, L, qx, qy, qx, qy))
    return dists, points


def _equiv_nodal(L, dists, points):
    """∫Nᵀq dx  +  Σ N(a)ᵀP   (국부좌표 6벡터)"""
    p = np.zeros(6)
    gx, gw = _GP
    for a, b, qx1, qy1, qx2, qy2 in dists:
        h = (b - a) / 2.0; m = (a + b) / 2.0
        for xg, wg in zip(gx, gw):
            x = m + h * xg
            t = (x - a) / (b - a)
            q = np.array([qx1 + (qx2 - qx1) * t, qy1 + (qy2 - qy1) * t])
            p += _shape(x, L).T @ q * (wg * h)
    for a, px, py in points:
        p += _shape(a, L).T @ np.array([px, py])
    return p


def _condense(K, P, internal):
    """정적 응축. internal: 응축할 DOF (0~5 중 해제 DOF, 6 이상은 부재 내부 DOF).
    반환 6×6 강성, 6 등가하중 (해제 DOF 행·열은 0)"""
    if not internal:
        return K[:6, :6].copy(), P[:6].copy()
    ii = list(internal)
    cc = [i for i in range(6) if i not in ii]
    try:
        kii_inv = np.linalg.inv(K[np.ix_(ii, ii)])
    except np.linalg.LinAlgError:
        return K[:6, :6].copy(), P[:6].copy()
    kci = K[np.ix_(cc, ii)]
    kc = np.zeros((6, 6)); pc = np.zeros(6)
    kc[np.ix_(cc, cc)] = K[np.ix_(cc, cc)] - kci @ kii_inv @ K[np.ix_(ii, cc)]
    pc[cc] = P[cc] - kci @ kii_inv @ P[ii]
    return kc, pc


def _end_condition(k, p, fi, fj, EI, L):
    """단부 고정률(0=힌지, 1=강접, 사이=반강접) 적용.
    반강접 단부는 부재 내부 회전 DOF φ 를 두고 절점 회전 θ 와
    회전스프링 ks = 3EI·r / (L(1-r)) 로 연결한 뒤 φ 를 응축한다."""
    rel, springs = [], []
    for idx, r in ((2, fi), (5, fj)):
        if r <= 1e-6:
            rel.append(idx)
        elif r < 1 - 1e-6:
            springs.append((idx, 3 * EI * r / (L * (1 - r))))
    if not springs:
        return _condense(k, p, rel)
    n = 6 + len(springs)
    K = np.zeros((n, n)); P = np.zeros(n)
    cmap = list(range(6))
    for j, (idx, _) in enumerate(springs):
        cmap[idx] = 6 + j
    K[np.ix_(cmap, cmap)] += k
    P[cmap] += p
    for j, (idx, ks) in enumerate(springs):
        a, b = idx, 6 + j
        K[a, a] += ks; K[b, b] += ks; K[a, b] -= ks; K[b, a] -= ks
    return _condense(K, P, rel + [6 + j for j in range(len(springs))])


# ═══════════════════════════════════════════════════════════════
#  부재 스테이션
# ═══════════════════════════════════════════════════════════════
def element_stations(model, eid, L):
    """결과 출력 위치. 모든 하중케이스의 하중 경계점을 포함하고
    집중하중 위치는 좌/우 2개 점으로 넣어 전단 불연속을 표현.
    반환: [(x, side)]  side = -1(좌극한) / +1(우극한) / 0"""
    xs = set(round(L * i / N_SEG, 9) for i in range(N_SEG + 1))
    jumps = set()
    for ld in model["eloads"]:
        if ld["elem"] != eid:
            continue
        rel = bool(ld.get("rel"))
        f = L if rel else 1.0
        if ld["kind"] == "point":
            a = round(min(max(float(ld.get("a", 0.5)) * f, 0), L), 9)
            if 1e-9 < a < L - 1e-9:
                jumps.add(a)
        else:
            for k in ("a", "b"):
                v = round(min(max(float(ld.get(k, 0)) * f, 0), L), 9)
                xs.add(v)
    st = []
    for x in sorted(xs | jumps):
        if x in jumps:
            st.append((x, -1)); st.append((x, 1))
        else:
            st.append((x, 0))
    return st


def _internal(L, f_i, dists, points, stations):
    """i단 부재력(부재에 작용, 국부) + 하중 → 스테이션별 N, V, M"""
    Fx, Fy, Mi = f_i
    N = []; V = []; M = []
    for x, side in stations:
        sx = sy = smy = 0.0       # ∫qx, ∫qy, ∫(x-s)qy
        for a, b, qx1, qy1, qx2, qy2 in dists:
            if x <= a:
                continue
            e = min(x, b)
            if e <= a:
                continue
            ln = b - a
            dqx = (qx2 - qx1) / ln; dqy = (qy2 - qy1) / ln
            # q(s) = q1 + dq (s - a),  s ∈ [a, e]
            d = e - a
            sx += qx1 * d + dqx * d * d / 2
            sy += qy1 * d + dqy * d * d / 2
            # ∫a^e (x-s) [qy1 + dqy (s-a)] ds   (u = s - a)
            xa = x - a
            smy += qy1 * (xa * d - d * d / 2) + dqy * (xa * d * d / 2 - d ** 3 / 3)
        px = py = mpy = 0.0
        for a, Px, Py in points:
            if a < x - 1e-12 or (abs(a - x) <= 1e-12 and side > 0):
                px += Px; py += Py; mpy += (x - a) * Py
        N.append(-Fx - sx - px)
        V.append(Fy + sy + py)
        M.append(-Mi + x * Fy + smy + mpy)
    return N, V, M


def _deflection(xs, M, N, EI, EA, ui, vi, uj, vj, L):
    """v'' = M/EI 2회 적분 + 양단 처짐 경계조건 → 국부 처짐"""
    n = len(xs)
    k = [m / EI for m in M]
    sl = [0.0] * n; v = [0.0] * n; u = [0.0] * n
    for i in range(1, n):
        dx = xs[i] - xs[i - 1]
        sl[i] = sl[i - 1] + 0.5 * (k[i] + k[i - 1]) * dx
        v[i] = v[i - 1] + 0.5 * (sl[i] + sl[i - 1]) * dx
        u[i] = u[i - 1] + 0.5 * (N[i] + N[i - 1]) / EA * dx
    vL, uL = v[-1], u[-1]
    dv = [vi + (vj - vi - vL) * x / L + v[i] for i, x in enumerate(xs)]
    du = [ui + (uj - ui - uL) * x / L + u[i] for i, x in enumerate(xs)]
    return du, dv


# ═══════════════════════════════════════════════════════════════
#  해석
# ═══════════════════════════════════════════════════════════════
def _elem_data(model):
    """부재별 기하·강성 정보"""
    data = {}
    for eid, e in model["elems"].items():
        ni, nj = model["nodes"][e["ni"]], model["nodes"][e["nj"]]
        L = elem_length(model, eid)
        if L < 1e-9:
            raise FrameError(f"부재 {eid}: 길이가 0 입니다.")
        mat = model["materials"].get(e["mat"])
        sec = model["sections"].get(e["sec"])
        if mat is None:
            raise FrameError(f"부재 {eid}: 재료가 지정되지 않았습니다.")
        if sec is None:
            raise FrameError(f"부재 {eid}: 단면이 지정되지 않았습니다.")
        A_mm, I_mm = section_props(sec)
        if A_mm <= 0 or I_mm <= 0:
            raise FrameError(f"부재 {eid}: 단면 '{sec.get('name')}' 성질(A, I)이 0 입니다.")
        E = material_E(mat) * 1e3            # kN/m²
        A = A_mm * 1e-6; I = I_mm * 1e-12     # m², m⁴
        c = (nj["x"] - ni["x"]) / L; s = (nj["y"] - ni["y"]) / L
        fi, fj = end_fix(e)
        data[eid] = dict(L=L, c=c, s=s, E=E, A=A, I=I, fi=fi, fj=fj,
                         gamma=float(mat.get("gamma", 0) or 0),
                         k=_k_local(E, A, I, L), T=_T(c, s))
    return data


def solve_case(model, case_id, edata=None):
    """단일 하중케이스 해석"""
    if not model["elems"]:
        raise FrameError("부재가 없습니다.")
    if not model["supports"]:
        raise FrameError("지점이 없습니다.")
    edata = edata or _elem_data(model)
    case = model["cases"].get(case_id, {})
    sw = float(case.get("selfweight", 0) or 0)

    used = set()
    for e in model["elems"].values():
        used.update((e["ni"], e["nj"]))
    nids = sorted(used | set(model["supports"]))
    idx = {n: i for i, n in enumerate(nids)}
    ndof = 3 * len(nids)
    K = np.zeros((ndof, ndof))
    P = np.zeros(ndof)

    eload = {}
    for eid, ed in edata.items():
        e = model["elems"][eid]
        dists, points = _member_loads(model, eid, case_id, ed["L"], ed["c"],
                                      ed["s"], ed["A"], ed["gamma"], sw)
        p = _equiv_nodal(ed["L"], dists, points)
        kc, pc = _end_condition(ed["k"], p, ed["fi"], ed["fj"], ed["E"] * ed["I"], ed["L"])
        ed_case = dict(kc=kc, pc=pc, dists=dists, points=points)
        eload[eid] = ed_case
        T = ed["T"]
        kg = T.T @ kc @ T; pg = T.T @ pc
        dofs = [3 * idx[e["ni"]] + i for i in range(3)] + \
               [3 * idx[e["nj"]] + i for i in range(3)]
        K[np.ix_(dofs, dofs)] += kg
        P[dofs] += pg

    for ld in model["nloads"]:
        if ld["case"] != case_id or ld["node"] not in idx:
            continue
        b = 3 * idx[ld["node"]]
        P[b] += float(ld.get("fx", 0)); P[b + 1] += float(ld.get("fy", 0))
        P[b + 2] += float(ld.get("mz", 0))

    K_elem = K.copy()

    # ── 지점 ────────────────────────────────────────────
    fixed = set()
    for nid, stid in model["supports"].items():
        st = model["sup_types"].get(stid)
        if st is None or nid not in idx:
            continue
        b = 3 * idx[nid]
        if st.get("dx"): fixed.add(b)
        if st.get("dy"): fixed.add(b + 1)
        if st.get("rz"):
            fixed.add(b + 2)
        else:
            fix = clamp01(st.get("fix", 0) or 0)
            if fix >= 0.999:
                fixed.add(b + 2)
            elif fix > 1e-6:
                ref = 0.0
                for eid, e in model["elems"].items():
                    if nid in (e["ni"], e["nj"]):
                        ed = edata[eid]
                        ref += 3 * ed["E"] * ed["I"] / ed["L"]
                K[b + 2, b + 2] += fix / (1 - fix) * ref
        K[b, b] += float(st.get("kx", 0) or 0)
        K[b + 1, b + 1] += float(st.get("ky", 0) or 0)
        if b + 2 not in fixed:
            K[b + 2, b + 2] += float(st.get("kr", 0) or 0)

    # 강성 없는 회전 DOF (양단 힌지 부재만 모인 절점) 자동 구속
    auto_fixed = []
    for i in range(ndof):
        if i not in fixed and abs(K[i, i]) < 1e-9:
            if i % 3 == 2:
                fixed.add(i); auto_fixed.append(nids[i // 3])
    free = [i for i in range(ndof) if i not in fixed]
    U = np.zeros(ndof)
    if free:
        Kff = K[np.ix_(free, free)]
        sc = np.sqrt(np.abs(np.diag(Kff))); sc[sc < 1e-30] = 1.0
        Kn = Kff / sc[:, None] / sc[None, :]
        if np.linalg.matrix_rank(Kn, tol=1e-10) < len(free) or np.linalg.cond(Kn) > 1e13:
            raise FrameError("불안정 구조입니다.\n지점 구속 조건 또는 부재 연결/단부해제를 확인하세요.")
        U[free] = np.linalg.solve(Kff, P[free])

    R = K_elem @ U - P
    disp = {n: tuple(U[3 * i:3 * i + 3]) for n, i in idx.items()}
    react = {}
    for nid in model["supports"]:
        if nid in idx:
            b = 3 * idx[nid]
            react[nid] = tuple(R[b:b + 3])

    # ── 부재력 ──────────────────────────────────────────
    elems = {}
    for eid, ed in edata.items():
        e = model["elems"][eid]
        dofs = [3 * idx[e["ni"]] + i for i in range(3)] + \
               [3 * idx[e["nj"]] + i for i in range(3)]
        ul = ed["T"] @ U[dofs]
        el = eload[eid]
        f = el["kc"] @ ul - el["pc"]          # 부재에 작용하는 단부력 (국부)
        st = element_stations(model, eid, ed["L"])
        N, V, M = _internal(ed["L"], f[:3], el["dists"], el["points"], st)
        xs = [x for x, _ in st]
        du, dv = _deflection(xs, M, N, ed["E"] * ed["I"], ed["E"] * ed["A"],
                             ul[0], ul[1], ul[3], ul[4], ed["L"])
        elems[eid] = dict(L=ed["L"], xs=xs, N=N, V=V, M=M, du=du, dv=dv,
                          end=tuple(f), c=ed["c"], s=ed["s"])
    return dict(disp=disp, react=react, elems=elems, auto_fixed=auto_fixed)


def combine(results, factors):
    """선형 조합 {case_id: result} × {case_id: factor}"""
    out = None
    for cid, fac in factors.items():
        r = results.get(cid)
        if r is None or fac == 0:
            continue
        if out is None:
            out = dict(disp={n: tuple(fac * v for v in d) for n, d in r["disp"].items()},
                       react={n: tuple(fac * v for v in d) for n, d in r["react"].items()},
                       elems={}, auto_fixed=list(r.get("auto_fixed", [])))
            for eid, e in r["elems"].items():
                ne = dict(e)
                for k in ("N", "V", "M", "du", "dv"):
                    ne[k] = [fac * v for v in e[k]]
                ne["end"] = tuple(fac * v for v in e["end"])
                out["elems"][eid] = ne
        else:
            for n, d in r["disp"].items():
                out["disp"][n] = tuple(a + fac * b for a, b in zip(out["disp"][n], d))
            for n, d in r["react"].items():
                out["react"][n] = tuple(a + fac * b for a, b in zip(out["react"][n], d))
            for eid, e in r["elems"].items():
                oe = out["elems"][eid]
                for k in ("N", "V", "M", "du", "dv"):
                    oe[k] = [a + fac * b for a, b in zip(oe[k], e[k])]
                oe["end"] = tuple(a + fac * b for a, b in zip(oe["end"], e["end"]))
    return out


def solve_all(model):
    """모든 하중케이스 + 하중조합 해석.
    반환: {("case", id): result, ("combo", id): result}"""
    edata = _elem_data(model)
    out = {}
    for cid in model["cases"]:
        out[("case", cid)] = solve_case(model, cid, edata)
    case_res = {cid: out[("case", cid)] for cid in model["cases"]}
    for coid, co in model["combos"].items():
        r = combine(case_res, co.get("factors", {}))
        if r is not None:
            out[("combo", coid)] = r
    return out


def elem_extremes(er):
    """부재 결과 요약: (Mmax+, x), (Mmin, x), |V|max, N 범위"""
    xs, M, V, N = er["xs"], er["M"], er["V"], er["N"]
    imx = max(range(len(M)), key=lambda i: M[i])
    imn = min(range(len(M)), key=lambda i: M[i])
    iv = max(range(len(V)), key=lambda i: abs(V[i]))
    return dict(Mmax=(M[imx], xs[imx]), Mmin=(M[imn], xs[imn]),
                Vmax=(V[iv], xs[iv]), Nmax=max(N), Nmin=min(N))
