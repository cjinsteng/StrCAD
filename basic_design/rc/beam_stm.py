"""
basic_design/rc/beam_stm.py
RC Beam Pro — 깊은보(Deep Beam) 스트럿-타이 모델 설계  (Tk 비의존 계산 + 계산서 + 그림)

  적용 기준
  · KDS 14 20 22 4.7   깊은보: ln ≤ 4h 이거나 하중이 받침부로부터 2h 이내 → KDS 14 20 24 (STM) 로 설계
                        Vn ≤ (5/6)·λ·√fck·bw·d,   최소 수직 전단철근 Av ≥ 0.0025·bw·s  (s ≤ d/5, 300 mm)
                                                  최소 수평 전단철근 Avh ≥ 0.0015·bw·s2 (s2 ≤ d/5, 300 mm)
  · KDS 14 20 24       φFn ≥ Fu   (스트럿·절점 φ = 0.75, 타이 φ = 0.85)
                        스트럿  Fns = fce·Acs,  fce = 0.85·βs·fck   βs: 프리즘 1.0 / 병모양 0.75λ(식 4.2-3 만족) · 0.60λ
                        식 (4.2-3)  Σ Asi/(b·si)·sin γi ≥ 0.003   (fck ≤ 40 MPa)
                        타이    Fnt = Ast·fy
                        절점    Fnn = fce·Anz,  fce = 0.85·βn·fck   βn: CCC 1.0 / CCT 0.80 / CTT 0.60

  모델 (단순지지 깊은보 · 전단면 하나)
  · 상현 = 압축 스트럿(프리즘), 하현 = 인장 타이(주근), 하중점 ↔ 받침점 경사 스트럿(병모양)
  · 집중하중 위치마다 절점, 하중 사이 구간에 전단이 있으면 수직 타이(스터럽)
  · 등분포하중(+자중)은 인접 절점에 지렛대 법칙으로 분배, 집중하중이 없으면 L/4 · 3L/4 두 절점으로
  · 상현 스트럿 폭 ws, 타이 유효폭 wt(= 2u) 를 반복 계산으로 정하고 팔길이 jd = h − ws/2 − u

단위: 길이 mm, 힘 kN(입력·출력) / N(내부), 강도 MPa
"""
import math

import numpy as np

from ..report import Report, fonts
from .. import theme as T
from . import beam_calc as B

PHI_S = 0.75          # 스트럿 · 절점
PHI_T = 0.85          # 타이
PHI_V = 0.75          # 깊은보 전단 상한 검토
GAMMA_C = 24e-6       # 콘크리트 단위중량 N/mm³ (24 kN/m³)
THETA_MIN = 25.0      # 스트럿-타이 최소 각도 (°)
DESIGN_CODE = "KDS 14 20 22 4.7 · KDS 14 20 24 : 2021"
WEB_BARS = ["D10", "D13", "D16"]
MAX_LAYERS = 5

C_STRUT, C_STRUT_E = "#BFDBFE", "#2563EB"
C_TIE, C_TIE_B = "#DC2626", "#FEE2E2"
C_NODE = "#F59E0B"


class DeepBeamInputError(ValueError):
    pass


def _floor(v, step=10.0):
    return math.floor(v / step + 1e-9) * step


# ── 하중 → 절점 ─────────────────────────────────────────────
def nodal_loads(L, loads, w, lb1, lb2):
    """상현 절점 [(x, P N, lp mm, 가상절점 여부)], 받침부로 바로 가는 하중 (Pd1, Pd2) N"""
    pts = {}
    for P, x, lp in loads:
        if P <= 0:
            continue
        if not (lb1 / 2.0 < x < L - lb2 / 2.0):
            raise DeepBeamInputError(f"집중하중 위치 x = {x:g} mm 가 받침판 범위 밖(경간 안)이어야 합니다.\n"
                                     f"({lb1 / 2:g} < x < {L - lb2 / 2:g})")
        key = round(x, 3)
        if key in pts:
            pts[key][1] += P
            pts[key][2] = max(pts[key][2], lp)
        else:
            pts[key] = [x, P, lp, False]
    nodes = [pts[k] for k in sorted(pts)]
    if not nodes:
        if w <= 0:
            raise DeepBeamInputError("하중이 없습니다. 집중하중 또는 등분포하중을 입력하세요.")
        return [[L / 4.0, w * L / 2.0, L / 4.0, True], [3 * L / 4.0, w * L / 2.0, L / 4.0, True]], 0.0, 0.0
    pd1 = pd2 = 0.0
    if w > 0:                                      # 구간 등분포 → 양끝 절점 (지렛대 법칙)
        xs = [0.0] + [n[0] for n in nodes] + [L]
        share = [0.0] * len(xs)
        for i in range(len(xs) - 1):
            half = w * (xs[i + 1] - xs[i]) / 2.0
            share[i] += half
            share[i + 1] += half
        pd1, pd2 = share[0], share[-1]
        for i, n in enumerate(nodes):
            n[1] += share[i + 1]
    return nodes, pd1, pd2


# ── 트러스 해석 ──────────────────────────────────────────────
def solve_truss(L, X, P, jd):
    """정정 트러스 (인장 +).  반환: nodes{name:(x,y)}, members[dict], RL, RR"""
    n = len(X)
    nodes = {"B0": (0.0, 0.0), f"B{n + 1}": (L, 0.0)}
    for k, x in enumerate(X, 1):
        nodes[f"T{k}"] = (x, jd)
        nodes[f"B{k}"] = (x, 0.0)
    RL = sum(p * (L - x) for p, x in zip(P, X)) / L
    mem = []
    for k in range(1, n):
        mem.append({"kind": "top", "i": f"T{k}", "j": f"T{k + 1}"})
    for k in range(0, n + 1):
        mem.append({"kind": "bot", "i": f"B{k}", "j": f"B{k + 1}"})
    for k in range(1, n + 1):
        mem.append({"kind": "vert", "i": f"T{k}", "j": f"B{k}"})
    mem.append({"kind": "diag", "i": "T1", "j": "B0"})
    V = RL
    for k in range(1, n):
        V -= P[k - 1]
        if V > 1e-6 * max(P):
            mem.append({"kind": "diag", "i": f"T{k + 1}", "j": f"B{k}"})
        elif V < -1e-6 * max(P):
            mem.append({"kind": "diag", "i": f"T{k}", "j": f"B{k + 1}"})
    mem.append({"kind": "diag", "i": f"T{n}", "j": f"B{n + 1}"})
    names = list(nodes)
    idx = {nm: i for i, nm in enumerate(names)}
    nu = len(mem) + 3
    A = np.zeros((2 * len(names), nu))
    rhs = np.zeros(2 * len(names))
    for c, m in enumerate(mem):
        (xi, yi), (xj, yj) = nodes[m["i"]], nodes[m["j"]]
        ln = math.hypot(xj - xi, yj - yi)
        cx, cy = (xj - xi) / ln, (yj - yi) / ln
        m["len"] = ln
        a, b = idx[m["i"]], idx[m["j"]]
        A[2 * a, c] += cx
        A[2 * a + 1, c] += cy
        A[2 * b, c] -= cx
        A[2 * b + 1, c] -= cy
    A[2 * idx["B0"] + 1, len(mem)] = 1.0              # RL
    A[2 * idx[f"B{n + 1}"] + 1, len(mem) + 1] = 1.0   # RR
    A[2 * idx["B0"], len(mem) + 2] = 1.0              # H
    for k, p in enumerate(P, 1):
        rhs[2 * idx[f"T{k}"] + 1] = p
    sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    if np.max(np.abs(A @ sol - rhs)) > 1e-6 * max(max(P), 1.0):
        raise DeepBeamInputError("스트럿-타이 모델이 평형을 이루지 못합니다. 하중 위치를 확인하세요.")
    tol = 1e-7 * sum(P)
    for c, m in enumerate(mem):
        f = float(sol[c])
        m["F"] = 0.0 if abs(f) < tol else f
        (xi, yi), (xj, yj) = nodes[m["i"]], nodes[m["j"]]
        m["theta"] = math.degrees(math.atan2(abs(yj - yi), abs(xj - xi))) if m["kind"] == "diag" else None
    return nodes, mem, float(sol[len(mem)]), float(sol[len(mem) + 1])


# ── 타이 배근 ────────────────────────────────────────────────
def tie_layout(n, bar, b, cc, ds, per_layer):
    """[(층, 개수, 하단에서 중심 높이)], 도심 높이 u"""
    db = B.BARS[bar][0]
    rows, left, j = [], n, 0
    while left > 0:
        k = min(per_layer, left)
        rows.append((j + 1, k, cc + ds + db / 2.0 + j * (db + max(25.0, db))))
        left -= k
        j += 1
    u = sum(k * y for _, k, y in rows) / n if n else cc + ds + db / 2.0
    return rows, u


# ── 설계 ────────────────────────────────────────────────────
def calc_deep(inp):
    g = inp.get
    L, b, h, cc = g("L"), g("b"), g("h"), g("cc")
    fck, fy, fyv = g("fck"), g("fy"), g("fyv")
    lb1, lb2 = g("lb1"), g("lb2")
    lam = 1.0
    for nm, v in (("경간 L", L), ("폭 b", b), ("높이 h", h), ("fck", fck), ("fy", fy), ("fyv", fyv),
                  ("좌측 받침폭", lb1), ("우측 받침폭", lb2)):
        if v <= 0:
            raise DeepBeamInputError(f"'{nm}' 은(는) 0 보다 커야 합니다.")
    if cc < 20:
        raise DeepBeamInputError("순피복은 20 mm 이상이어야 합니다.")
    if lb1 + lb2 >= L:
        raise DeepBeamInputError("받침폭 합이 경간보다 큽니다.")
    fyv_c = min(fyv, 500.0)
    tie_bar, v_bar, h_bar = g("tie_bar"), g("v_bar"), g("h_bar")
    ds = B.BARS[v_bar][0]
    db = B.BARS[tie_bar][0]
    a_t = B.BARS[tie_bar][1]
    w_sw = 1.2 * GAMMA_C * b * h if g("selfw") else 0.0       # N/mm (계수 1.2)
    w = g("wu") + w_sw                                          # kN/m = N/mm
    loads = [(P * 1e3, x, lp) for P, x, lp in g("loads")]
    for P, x, lp in loads:
        if P > 0 and lp <= 0:
            raise DeepBeamInputError(f"x = {x:g} mm 집중하중의 재하판 폭을 입력하세요.")
    top, pd1, pd2 = nodal_loads(L, loads, w, lb1, lb2)
    X = [t[0] for t in top]
    P = [t[1] for t in top]

    # 깊은보 판정
    ln = L - (lb1 + lb2) / 2.0
    conc_x = [x for Pk, x, _ in loads if Pk > 0]
    near = bool(conc_x) and all(min(x - lb1 / 2.0, L - lb2 / 2.0 - x) <= 2 * h for x in conc_x)
    is_deep = ln <= 4 * h or near

    per_max = B.max_bars(b, cc, ds, db, "이음없음")
    beta_top = 1.0
    ws, u = 0.15 * h, cc + ds + db / 2.0
    n_user = int(g("tie_n") or 0)
    per = per_max
    for _ in range(60):
        jd = h - ws / 2.0 - u
        if jd <= 0.2 * h:
            raise DeepBeamInputError("팔길이가 너무 작습니다 (단면 높이 부족 또는 하중 과다). h 를 키우세요.")
        nodes, mem, RL, RR = solve_truss(L, X, P, jd)
        Tmax = max([m["F"] for m in mem if m["kind"] == "bot"] + [0.0])
        tens_vert = {m["i"] for m in mem if m["kind"] == "vert" and m["F"] > 0}
        beta_top = 0.8 if tens_vert else 1.0
        ws_new = Tmax / (PHI_S * 0.85 * beta_top * fck * b)
        d_est = h - u
        as_min = max(0.25 * math.sqrt(fck) / fy, 1.4 / fy) * b * d_est
        as_req = max(Tmax / (PHI_T * fy), as_min)
        n_bar = n_user if n_user > 0 else max(2, math.ceil(as_req / a_t - 1e-9))
        # 타이 유효폭 wt = 2u 가 절점 배면(βn = 0.8)에 필요한 폭보다 작으면 층을 늘린다 (자동일 때)
        wt_need = Tmax / (PHI_S * 0.85 * 0.8 * fck * b)
        if n_user <= 0:              # wt ≤ wt,max = As·fy/(0.85·βn·fck·b) 이므로 배면 강도에는 As 도 필요
            while n_bar * a_t * fy / (0.85 * 0.8 * fck * b) < wt_need - 1e-9 and n_bar < 80:
                n_bar += 1
        per = min(per_max, n_bar)
        rows, u_new = tie_layout(n_bar, tie_bar, b, cc, ds, per)
        while 2 * u_new < wt_need and per > 2 and len(rows) < MAX_LAYERS:
            per -= 1
            rows, u_new = tie_layout(n_bar, tie_bar, b, cc, ds, per)
        if abs(ws_new - ws) < 0.05 and abs(u_new - u) < 0.05:
            ws, u = ws_new, u_new
            break
        ws, u = ws_new, u_new
    jd = h - ws / 2.0 - u
    nodes, mem, RL, RR = solve_truss(L, X, P, jd)
    d = h - u
    Tmax = max([m["F"] for m in mem if m["kind"] == "bot"] + [0.0])
    as_min = max(0.25 * math.sqrt(fck) / fy, 1.4 / fy) * b * d
    as_req = max(Tmax / (PHI_T * fy), as_min)
    as_prov = n_bar * a_t
    wt_geo = 2.0 * u
    wt_max = as_prov * fy / (0.85 * 0.8 * fck * b)               # 4.3: 타이 최대 유효폭
    wt = min(wt_geo, wt_max)

    # 받침 반력
    R1, R2 = RL + pd1, RR + pd2
    beta_top_of = {}
    for k in range(1, len(X) + 1):
        vt = [m for m in mem if m["kind"] == "vert" and m["i"] == f"T{k}"]
        beta_top_of[f"T{k}"] = 0.8 if (vt and vt[0]["F"] > 0) else 1.0

    # ── 복부철근 (수직·수평) ──
    a_v, a_h = B.BARS[v_bar][1], B.BARS[h_bar][1]
    legs = max(int(g("v_legs") or 2), 2)
    Av, Ah = legs * a_v, 2 * a_h
    s_lim = min(d / 5.0, 300.0)
    diag = [m for m in mem if m["kind"] == "diag"]
    vert_t = [m for m in mem if m["kind"] == "vert" and m["F"] > 0]
    xs_all = [0.0] + X + [L]
    s_vt = None                                                   # 수직 타이가 요구하는 간격
    for m in vert_t:
        k = int(m["i"][1:])
        band = min(xs_all[k] - xs_all[k - 1], xs_all[k + 1] - xs_all[k])
        m["band"] = band
        m["as_req"] = m["F"] / (PHI_T * fyv_c)
        s_need = Av * band / m["as_req"]
        s_vt = s_need if s_vt is None else min(s_vt, s_need)
    sv_user, sh_user = float(g("v_s") or 0), float(g("h_s") or 0)
    sv = sv_user if sv_user > 0 else _floor(min(Av / (0.0025 * b), s_lim, s_vt or 1e9))
    sh = sh_user if sh_user > 0 else _floor(min(Ah / (0.0015 * b), s_lim))
    cos_min = min((math.cos(math.radians(m["theta"])) for m in diag), default=1.0)

    def conf_sum(theta, svv, shh):
        t = math.radians(theta)
        return Av / (b * svv) * math.cos(t) + Ah / (b * shh) * math.sin(t)
    conf_ok_fck = fck <= 40.0
    if conf_ok_fck:
        while (sv_user <= 0 or sh_user <= 0) and min(conf_sum(m["theta"], sv, sh) for m in diag) < 0.003:
            gv = conf_sum(45, sv - 10, sh) if sv_user <= 0 and sv > 80 else -1
            gh = conf_sum(45, sv, sh - 10) if sh_user <= 0 and sh > 80 else -1
            if gv < 0 and gh < 0:
                break
            if gv >= gh:
                sv -= 10
            else:
                sh -= 10
    rho_v, rho_h = Av / (b * sv), Ah / (b * sh)
    for m in diag:
        m["conf"] = conf_sum(m["theta"], sv, sh)
        m["beta_s"] = (0.75 * lam) if (conf_ok_fck and m["conf"] >= 0.003) else (0.60 * lam)

    # ── 스트럿 · 절점 검토 ──
    checks = []          # 부재 표
    ncheck = []          # 절점 표
    ok = True
    why = []

    def add_member(name, kind, fu, width, beta, cap, note=""):
        nonlocal ok
        r = fu / cap if cap > 0 else 9.99
        good = r <= 1.0 + 5e-4
        checks.append({"name": name, "kind": kind, "Fu": fu, "w": width, "beta": beta, "cap": cap, "ratio": r,
                       "ok": good, "note": note})
        if not good:
            ok = False
            why.append(f"{name} {kind}: Fu = {fu / 1e3:,.0f} kN > φFn = {cap / 1e3:,.0f} kN")

    def add_node(node, typ, face, fu, width, bn):
        nonlocal ok
        cap = PHI_S * 0.85 * bn * fck * width * b
        r = fu / cap if cap > 0 else 9.99
        good = r <= 1.0 + 5e-4
        ncheck.append({"node": node, "type": typ, "face": face, "Fu": fu, "w": width, "bn": bn, "cap": cap,
                       "ratio": r, "ok": good})
        if not good:
            ok = False
            why.append(f"절점 {node} {face}: Fu = {fu / 1e3:,.0f} kN > φFnn = {cap / 1e3:,.0f} kN")

    lp_of = {f"T{k}": top[k - 1][2] for k in range(1, len(X) + 1)}
    # 상현 스트럿
    sc = ss = 0
    for m in mem:
        if m["kind"] == "top" and m["F"] < 0:
            sc += 1
            m["label"] = f"C{sc}"
            add_member(m["label"], "상현 스트럿", -m["F"], ws, 1.0, PHI_S * 0.85 * 1.0 * fck * ws * b, "프리즘 (ws = 소요폭)")
    # 경사 스트럿
    for m in diag:
        ss += 1
        m["label"] = f"S{ss}"
        t = math.radians(m["theta"])
        tn, bn_ = m["i"], m["j"]
        vsum = sum(abs(o["F"]) * math.sin(math.radians(o["theta"])) for o in diag if o["i"] == tn) or 1.0
        lp_share = lp_of[tn] * abs(m["F"]) * math.sin(t) / vsum
        w_top = lp_share * math.sin(t) + ws * math.cos(t)
        k_b = int(bn_[1:])
        if k_b == 0 or k_b == len(X) + 1:
            lb = lb1 if k_b == 0 else lb2
            w_bot = lb * math.sin(t) + wt * math.cos(t)
        else:
            w_bot = lp_of[f"T{k_b}"] * math.sin(t) + wt * math.cos(t)
        m["w_top"], m["w_bot"], m["lp_share"] = w_top, w_bot, lp_share
        wmin = min(w_top, w_bot)
        add_member(m["label"], "경사 스트럿", -m["F"] if m["F"] < 0 else m["F"], wmin, m["beta_s"],
                   PHI_S * 0.85 * m["beta_s"] * fck * wmin * b, "병모양")
        if m["F"] > 0:
            ok = False
            why.append(f"{m['label']}: 경사 부재에 인장 발생 — 모델 확인")
        if m["theta"] < THETA_MIN - 1e-6:
            ok = False
            why.append(f"{m['label']}: 스트럿 각도 θ = {m['theta']:.1f}° < {THETA_MIN:g}°")
    # 하현 타이
    tc = 0
    t_cap = PHI_T * as_prov * fy
    for m in mem:
        if m["kind"] == "bot" and m["F"] > 0:
            tc += 1
            m["label"] = f"T{tc}"
            add_member(m["label"], "하현 타이", m["F"], wt, None, t_cap, f"{n_bar}-{tie_bar}")
    # 수직 타이
    vc = 0
    for m in vert_t:
        vc += 1
        m["label"] = f"V{vc}"
        n_in = m["band"] / sv
        m["as_prov"] = Av * n_in
        add_member(m["label"], "수직 타이", m["F"], m["band"], None, PHI_T * fyv_c * m["as_prov"],
                   f"{v_bar}@{sv:g} ({m['band']:,.0f} 구간)")
    for m in mem:
        if m["kind"] == "vert" and m["F"] < 0:
            vc += 1
            m["label"] = f"V{vc}"
            add_member(m["label"], "수직 스트럿", -m["F"], top[int(m["i"][1:]) - 1][2], 1.0,
                       PHI_S * 0.85 * fck * top[int(m["i"][1:]) - 1][2] * b, "")

    # 절점: 받침 (CCT)
    for k_b, R, lb, nm in ((0, R1, lb1, "A"), (len(X) + 1, R2, lb2, "B")):
        dm = [m for m in diag if m["j"] == f"B{k_b}"][0]
        tie = [m for m in mem if m["kind"] == "bot" and (m["i"] == f"B{k_b}" or m["j"] == f"B{k_b}")][0]
        add_node(f"{nm}(받침)", "CCT", "지압면", R, lb, 0.8)
        add_node(f"{nm}(받침)", "CCT", "스트럿면", abs(dm["F"]), dm["w_bot"], 0.8)
        add_node(f"{nm}(받침)", "CCT", "타이 배면", tie["F"], wt, 0.8)
    # 절점: 하중점
    for k in range(1, len(X) + 1):
        tn = f"T{k}"
        bn = beta_top_of[tn]
        typ = "CCC" if bn == 1.0 else "CCT"
        lab = f"P{k}" + ("(분포)" if top[k - 1][3] else "")
        add_node(lab, typ, "지압면", P[k - 1], lp_of[tn], bn)
        chord = [abs(m["F"]) for m in mem if m["kind"] == "top" and tn in (m["i"], m["j"])]
        dms = [m for m in diag if m["i"] == tn]
        hc = max(chord + [sum(abs(m["F"]) * math.cos(math.radians(m["theta"])) for m in dms) / (2 if len(dms) > 1 and not chord else 1)])
        add_node(lab, typ, "상현면", hc, ws, bn)
        for m in dms:
            add_node(lab, typ, f"{m['label']} 면", abs(m["F"]), m["w_top"], bn)
    # 절점: 중간 하부 (CTT)
    for m in diag:
        k_b = int(m["j"][1:])
        if 0 < k_b < len(X) + 1:
            add_node(f"N{k_b}(하부)", "CTT", f"{m['label']} 면", abs(m["F"]), m["w_bot"], 0.6)

    # ── 기타 검토 ──
    vu = max(R1, R2)
    phi_vn_max = PHI_V * 5.0 / 6.0 * lam * math.sqrt(fck) * b * d
    if vu > phi_vn_max:
        ok = False
        why.append(f"전단 상한: Vu = {vu / 1e3:,.0f} kN > φ(5/6)√fck·bw·d = {phi_vn_max / 1e3:,.0f} kN")
    if as_prov < as_req - 1e-6:
        ok = False
        why.append(f"하현 타이 철근 부족: As = {as_prov:,.0f} < 소요 {as_req:,.0f} mm²")
    if len(rows) > 1 and rows[-1][2] > h / 3:
        why.append("타이 철근 층이 너무 높음 — 철근 직경을 키우세요")
        ok = False
    web = {"Av": Av, "Ah": Ah, "sv": sv, "sh": sh, "s_lim": s_lim, "rho_v": rho_v, "rho_h": rho_h,
           "sv_min": Av / (0.0025 * b), "sh_min": Ah / (0.0015 * b), "s_vt": s_vt, "legs": legs,
           "v_ok": rho_v >= 0.0025 - 1e-9 and sv <= s_lim + 1e-6, "h_ok": rho_h >= 0.0015 - 1e-9 and sh <= s_lim + 1e-6,
           "conf_min": min((m["conf"] for m in diag), default=0.0), "conf_fck": conf_ok_fck}
    if not web["v_ok"]:
        ok = False
        why.append(f"수직 전단철근: ρv = {rho_v:.4f} < 0.0025 또는 s > {s_lim:.0f} mm")
    if not web["h_ok"]:
        ok = False
        why.append(f"수평 전단철근: ρh = {rho_h:.4f} < 0.0015 또는 s > {s_lim:.0f} mm")

    # 정착 (참고): 받침 확장절점영역 경계에서 보 끝까지 (보 끝 = 받침 바깥면 가정)
    th_end = min(dm["theta"] for dm in diag if dm["j"] in ("B0", f"B{len(X) + 1}"))
    la = min(lb1, lb2) + wt / (2.0 * math.tan(math.radians(th_end))) - cc
    ld = max(0.6 * db * fy / (lam * math.sqrt(fck)) * (0.8 if db <= 19.1 else 1.0), 300.0)
    ldh = max(0.24 * db * fy / (lam * math.sqrt(fck)), 8 * db, 150.0)
    anchor = "직선 정착 가능" if la >= ld else ("표준갈고리 정착" if la >= ldh else "기계적 정착(헤드 철근) 필요")

    return {
        "name": g("name", ""), "L": L, "b": b, "h": h, "cc": cc, "fck": fck, "fy": fy, "fyv": fyv, "fyv_c": fyv_c,
        "lb1": lb1, "lb2": lb2, "ln": ln, "is_deep": is_deep, "near": near, "loads": loads, "w": w, "wu": g("wu"),
        "w_sw": w_sw, "top": top, "pd1": pd1, "pd2": pd2, "nodes": nodes, "mem": mem, "R1": R1, "R2": R2,
        "RL": RL, "RR": RR, "jd": jd, "ws": ws, "u": u, "d": d, "wt": wt, "wt_geo": wt_geo, "wt_max": wt_max,
        "beta_top": beta_top, "Tmax": Tmax, "as_req": as_req, "as_min": as_min, "as_prov": as_prov,
        "tie_bar": tie_bar, "n_bar": n_bar, "rows": rows, "per_max": per_max, "v_bar": v_bar, "h_bar": h_bar,
        "web": web, "checks": checks, "ncheck": ncheck, "vu": vu, "phi_vn_max": phi_vn_max,
        "la": la, "ld": ld, "ldh": ldh, "anchor": anchor, "ok": ok, "why": why, "selfw": bool(g("selfw")),
        "auto_tie": n_user <= 0, "auto_sv": sv_user <= 0, "auto_sh": sh_user <= 0,
    }


# ── 결과 요약 문자열 ─────────────────────────────────────────
def rebar_text(r):
    rows = r["rows"]
    lay = " + ".join(f"{k}" for _, k, _ in rows)
    tie = f"{r['n_bar']}-{r['tie_bar']}" + (f"  ({len(rows)}단: {lay})" if len(rows) > 1 else "")
    wv = r["web"]
    return {"tie": tie, "vert": f"{r['v_bar']} @ {wv['sv']:g}  ({wv['legs']}-leg)",
            "horz": f"{r['h_bar']} @ {wv['sh']:g}  (양면)"}


def _kn(v):
    return f"{v / 1e3:,.1f}"


def _ok(good, warn=False):
    return ("O.K.", "ok") if good else (("검토", "warn") if warn else ("N.G.", "ng"))


# ── 계산서 ───────────────────────────────────────────────────
def _conditions(rep, r):
    rep.h("설계 조건")
    rep.t(f"단면  b × h = {r['b']:g} × {r['h']:g} mm,   경간(받침 중심) L = {r['L']:,.0f} mm,   "
          f"받침폭 {r['lb1']:g} / {r['lb2']:g} mm,   순피복 {r['cc']:g} mm", 1)
    rep.t(f"재료  fck = {r['fck']:g} MPa,   fy(타이) = {r['fy']:g} MPa,   fyv(복부) = {r['fyv']:g} MPa"
          + ("  (계산 500)" if r["fyv"] > 500 else ""), 1)
    ld = []
    for P, x, lp in r["loads"]:
        if P > 0:
            ld.append(f"P = {P / 1e3:,.0f} kN @ x = {x:,.0f} (판 {lp:g})")
    dist = []
    if r["wu"] > 0:
        dist.append(f"wu = {r['wu']:g} kN/m")
    if r["selfw"]:
        dist.append(f"자중 1.2D = {r['w_sw']:.2f} kN/m")
    if len(ld) + len(dist) > 3:
        rep.t("계수하중  " + ",   ".join(ld), 1)
        if dist:
            rep.t("         " + ",   ".join(dist), 1)
    else:
        rep.t("계수하중  " + ",   ".join(ld + dist), 1)
    lim = 4 * r["h"]
    rep.t(f"깊은보 판정  ln = {r['ln']:,.0f} mm {'≤' if r['ln'] <= lim else '>'} 4h = {lim:,.0f} mm"
          + ("" if r["ln"] <= lim else ("  ·  하중이 받침부에서 2h 이내" if r["near"] else "")) + "  →  "
          + ("깊은보 (KDS 14 20 22 4.7, STM 설계)" if r["is_deep"] else "깊은보 아님 — STM 은 적용 가능하나 일반 보 설계 권장"),
          1, "b" if r["is_deep"] else "warn")


def _summary_table(rep, r):
    rb = rebar_text(r)
    wv = r["web"]
    rows = [
        ["하현 타이 (주근)", f"{r['as_req']:,.0f} mm²", rb["tie"], f"{r['as_prov']:,.0f} mm²",
         _ok(r["as_prov"] >= r["as_req"] - 1e-6)],
        ["수직 전단철근", f"s ≤ {min(wv['sv_min'], wv['s_lim'], wv['s_vt'] or 1e9):,.0f}",
         rb["vert"], f"ρv = {wv['rho_v']:.4f}", _ok(wv["v_ok"])],
        ["수평 전단철근", f"s ≤ {min(wv['sh_min'], wv['s_lim']):,.0f}", rb["horz"], f"ρh = {wv['rho_h']:.4f}",
         _ok(wv["h_ok"])],
        ["스트럿 구속철근 (식 4.2-3)", "Σ ≥ 0.003", f"Σ = {wv['conf_min']:.4f}",
         "βs = 0.75" if wv["conf_fck"] and wv["conf_min"] >= 0.003 else "βs = 0.60",
         _ok(wv["conf_fck"] and wv["conf_min"] >= 0.003, warn=True)],
        ["전단 상한 φ(5/6)√fck·bw·d", f"Vu = {_kn(r['vu'])}", f"{_kn(r['phi_vn_max'])} kN",
         f"{r['vu'] / r['phi_vn_max']:.3f}", _ok(r["vu"] <= r["phi_vn_max"])],
        ["타이 정착 (참고)", f"ld = {r['ld']:,.0f} / ldh = {r['ldh']:,.0f}", f"가용 {r['la']:,.0f} mm",
         r["anchor"], ("참고", "dim")],
    ]
    rep.table([["구분", "소요", "배근 / 강도", "제공", "판정"]], rows, [196, 150, 200, 158, 144],
              ["l", "c", "c", "c", "c"])


def _member_table(rep, r):
    rows = []
    for c in r["checks"]:
        rows.append([c["name"], c["kind"], _kn(c["Fu"]), f"{c['w']:,.0f}",
                     f"{c['beta']:.2f}" if c["beta"] is not None else "-", _kn(c["cap"]),
                     (f"{c['ratio']:.3f}", "n" if c["ok"] else "ng"), _ok(c["ok"]), c["note"]])
    rep.table([["부재", "종류", "Fu (kN)", "폭 (mm)", "βs", "φFn (kN)", "Fu/φFn", "판정", "비고"]], rows,
              [52, 104, 84, 74, 58, 92, 80, 70, 234], ["c", "l", "r", "r", "c", "r", "c", "c", "l"])


def _node_table(rep, r):
    rows = []
    for c in r["ncheck"]:
        rows.append([c["node"], c["type"], c["face"], _kn(c["Fu"]), f"{c['w']:,.0f}", f"{c['bn']:.2f}",
                     _kn(c["cap"]), (f"{c['ratio']:.3f}", "n" if c["ok"] else "ng"), _ok(c["ok"])])
    rep.table([["절점", "형식", "검토면", "Fu (kN)", "면 폭 (mm)", "βn", "φFnn (kN)", "Fu/φFnn", "판정"]], rows,
              [110, 60, 110, 90, 90, 60, 100, 90, 138], ["l", "c", "l", "r", "r", "c", "r", "c", "c"])


def build_simple(r, figures=True):
    rep = Report()
    _conditions(rep, r)
    if figures:
        rep.fig(300, draw_stm(r), "스트럿-타이 모델")
    rep.h("배근 결과")
    _summary_table(rep, r)
    if not r["ok"]:
        for i, w in enumerate(r["why"]):
            rep.t(f"{'①②③④⑤⑥⑦⑧⑨⑩'[i] if i < 10 else '·'} {w}", 1, "ng")
    rep.h("스트럿 · 타이 검토")
    _member_table(rep, r)
    rep.h("절점영역 검토")
    _node_table(rep, r)
    if figures:
        rep.gap(10)
        rep.fig(300, draw_rebar(r), "배근도")
    return rep


def build_report(r, figures=True):
    """Detail: 풀이 과정"""
    rep = Report()
    _conditions(rep, r)
    if figures:
        rep.fig(300, draw_stm(r), "스트럿-타이 모델")
    fck, b = r["fck"], r["b"]
    rep.h("1. 하중과 절점")
    for k, t in enumerate(r["top"], 1):
        rep.t(f"P{k}  x = {t[0]:,.0f} mm,  Pu = {t[1] / 1e3:,.1f} kN,  재하판 lp = {t[2]:,.0f} mm"
              + ("   (등분포하중 가상절점 — 반경간 하중의 합력, lp = L/4 가정)" if t[3] else ""), 1)
    if r["pd1"] or r["pd2"]:
        rep.t(f"받침부로 바로 전달되는 분포하중  A: {_kn(r['pd1'])} kN,  B: {_kn(r['pd2'])} kN", 1, "dim")
    rep.t(f"반력  RA = {_kn(r['R1'])} kN,   RB = {_kn(r['R2'])} kN", 1, "b")
    rep.h("2. 모델 형상 (반복 계산)")
    rep.t(f"타이 도심  u = {r['u']:.1f} mm  (하단에서),   d = h − u = {r['d']:.1f} mm", 1)
    rep.t(f"상현 스트럿 폭  ws = Tu,max / (φ·0.85·βn·fck·b) = {_kn(r['Tmax'])}×10³ / (0.75×0.85×{r['beta_top']:.2f}"
          f"×{fck:g}×{b:g}) = {r['ws']:.1f} mm", 1)
    rep.t(f"팔길이  jd = h − ws/2 − u = {r['h']:g} − {r['ws'] / 2:.1f} − {r['u']:.1f} = {r['jd']:.1f} mm", 1, "b")
    rep.t(f"타이 유효폭  wt = min(2u, wt,max) = min({r['wt_geo']:.1f}, {r['wt_max']:.1f}) = {r['wt']:.1f} mm"
          f"     wt,max = As·fy / (0.85·βn·fck·b),  βn = 0.80", 1)
    rep.h("3. 부재력 (인장 +)")
    rows = []
    for m in r["mem"]:
        if abs(m["F"]) <= 0 and m["kind"] == "vert":
            continue
        kind = {"top": "상현", "bot": "하현", "vert": "수직", "diag": "경사"}[m["kind"]]
        rows.append([m.get("label", "-"), kind, f"{m['i']}–{m['j']}", f"{m['len']:,.0f}",
                     f"{m['theta']:.1f}°" if m["theta"] is not None else "-", _kn(m["F"]),
                     "압축" if m["F"] < 0 else ("인장" if m["F"] > 0 else "-")])
    rep.table([["부재", "위치", "절점", "길이 (mm)", "θ", "F (kN)", "구분"]], rows,
              [70, 80, 110, 110, 90, 140, 110], ["c", "c", "c", "r", "c", "r", "c"])
    rep.h("4. 스트럿 강도  (KDS 14 20 24 4.2)")
    rep.t("φFns = φ·0.85·βs·fck·ws·b,   φ = 0.75", 1, "dim")
    for m in r["mem"]:
        if m["kind"] != "diag":
            continue
        t = math.radians(m["theta"])
        rep.t(f"{m['label']}  θ = {m['theta']:.1f}°", 1, "sub")
        rep.t(f"상단 폭 = lp′·sinθ + ws·cosθ = {m['lp_share']:.0f}×{math.sin(t):.3f} + {r['ws']:.1f}×{math.cos(t):.3f}"
              f" = {m['w_top']:.1f} mm", 2)
        rep.t(f"하단 폭 = lb·sinθ + wt·cosθ = {m['w_bot']:.1f} mm   →  ws = {min(m['w_top'], m['w_bot']):.1f} mm", 2)
        rep.t(f"구속철근  Σ Asi/(b·si)·sinγi = Av/(b·sv)·cosθ + Ah/(b·sh)·sinθ = {m['conf']:.4f}"
              f" {'≥' if m['conf'] >= 0.003 else '<'} 0.003  →  βs = {m['beta_s']:.2f}"
              + ("" if r["web"]["conf_fck"] else "  (fck > 40 MPa: βs = 0.60 적용)"), 2)
        cap = PHI_S * 0.85 * m["beta_s"] * fck * min(m["w_top"], m["w_bot"]) * b
        rep.t(f"φFns = 0.75×0.85×{m['beta_s']:.2f}×{fck:g}×{min(m['w_top'], m['w_bot']):.1f}×{b:g} = {_kn(cap)} kN"
              f"  {'≥' if cap >= abs(m['F']) else '<'}  Fu = {_kn(abs(m['F']))} kN", 2,
              "ok" if cap >= abs(m["F"]) else "ng")
    rep.h("5. 타이 강도  (KDS 14 20 24 4.3)")
    rep.t(f"소요 As = Tu / (φ·fy) = {_kn(r['Tmax'])}×10³ / (0.85×{r['fy']:g}) = {r['Tmax'] / (PHI_T * r['fy']):,.0f} mm²", 1)
    rep.t(f"최소 휨철근 As,min = max(0.25√fck/fy, 1.4/fy)·b·d = {r['as_min']:,.0f} mm²", 1)
    rep.t(f"배근 {rebar_text(r)['tie']}  As = {r['as_prov']:,.0f} mm²   (한 단 최대 {r['per_max']}개)", 1,
          "ok" if r["as_prov"] >= r["as_req"] - 1e-6 else "ng")
    for m in r["mem"]:
        if m["kind"] == "vert" and m["F"] > 0:
            rep.t(f"{m['label']} 수직 타이  Tu = {_kn(m['F'])} kN,  소요 As = {m['as_req']:,.0f} mm² "
                  f"(구간 {m['band']:,.0f} mm) → 제공 {m['as_prov']:,.0f} mm²", 1)
    rep.h("6. 절점영역  (KDS 14 20 24 4.4)")
    rep.t("φFnn = φ·0.85·βn·fck·Anz,   βn: CCC 1.0 · CCT 0.80 · CTT 0.60", 1, "dim")
    _node_table(rep, r)
    rep.h("7. 깊은보 전단 · 최소 복부철근  (KDS 14 20 22 4.7)")
    wv = r["web"]
    rep.t(f"Vu = {_kn(r['vu'])} kN  ≤  φ(5/6)λ√fck·bw·d = 0.75×5/6×√{fck:g}×{b:g}×{r['d']:.0f} = {_kn(r['phi_vn_max'])} kN",
          1, "ok" if r["vu"] <= r["phi_vn_max"] else "ng")
    rep.t(f"수직  Av = {wv['Av']:.1f} mm² ({wv['legs']}-{r['v_bar']}),  s ≤ min(Av/(0.0025b), d/5, 300) = "
          f"min({wv['sv_min']:.0f}, {r['d'] / 5:.0f}, 300)" + (f", 수직타이 {wv['s_vt']:.0f}" if wv["s_vt"] else "")
          + f"  →  s = {wv['sv']:g} mm,  ρv = {wv['rho_v']:.4f}", 1, "ok" if wv["v_ok"] else "ng")
    rep.t(f"수평  Ah = {wv['Ah']:.1f} mm² (양면 {r['h_bar']}),  s2 ≤ min(Ah/(0.0015b), d/5, 300) = "
          f"min({wv['sh_min']:.0f}, {r['d'] / 5:.0f}, 300)  →  s2 = {wv['sh']:g} mm,  ρh = {wv['rho_h']:.4f}",
          1, "ok" if wv["h_ok"] else "ng")
    rep.h("8. 타이 정착 (참고)")
    rep.t(f"가용 길이 (확장절점영역 경계 → 보 끝, 보 끝 = 받침 바깥면 가정)  la = lb + wt/(2·tanθ) − cc = {r['la']:,.0f} mm", 1)
    rep.t(f"직선 ld = 0.6·db·fy/(λ√fck) = {r['ld']:,.0f} mm,   표준갈고리 ldh = 0.24·db·fy/(λ√fck) = {r['ldh']:,.0f} mm"
          f"   →  {r['anchor']}", 1, "b")
    if not r["ok"]:
        rep.h("N.G. 사유")
        for i, w in enumerate(r["why"]):
            rep.t(f"{i + 1}. {w}", 1, "ng")
    if figures:
        rep.gap(10)
        rep.fig(300, draw_rebar(r), "배근도")
    return rep


# ── 그림 ────────────────────────────────────────────────────
def _frame(r, x, y, w, h, pad_x=46, pad_top=58, pad_bot=56):
    """보 입면 좌표 변환: 받침 바깥면 = 보 끝"""
    x0m, x1m = -r["lb1"] / 2.0, r["L"] + r["lb2"] / 2.0
    sx = (w - 2 * pad_x) / (x1m - x0m)
    sy = (h - pad_top - pad_bot) / r["h"]
    s = min(sx, sy)
    bw = (x1m - x0m) * s
    ox = x + (w - bw) / 2.0 - x0m * s
    oy = y + pad_top + (h - pad_top - pad_bot - r["h"] * s) / 2.0 + r["h"] * s   # 보 하단

    def P(xm, ym):
        return ox + xm * s, oy - ym * s
    return P, s, x0m, x1m


def _band(cv, P, a, b_, width, fill, outline):
    (xa, ya), (xb, yb) = a, b_
    ln = math.hypot(xb - xa, yb - ya) or 1.0
    nx, ny = -(yb - ya) / ln * width / 2.0, (xb - xa) / ln * width / 2.0
    pts = [P(xa + nx, ya + ny), P(xb + nx, yb + ny), P(xb - nx, yb - ny), P(xa - nx, ya - ny)]
    cv.create_polygon(*[c for p in pts for c in p], fill=fill, outline=outline)


def draw_stm(r):
    def draw(cv, x, y, w, h):
        F = fonts(cv)
        P, s, x0m, x1m = _frame(r, x, y, w, h)
        H = r["h"]
        # 보
        cv.create_rectangle(*P(x0m, H), *P(x1m, 0), fill="#F8FAFC", outline=T.INK, width=1.5)
        # 받침
        for xc, lb in ((0.0, r["lb1"]), (r["L"], r["lb2"])):
            cv.create_rectangle(*P(xc - lb / 2, 0), *P(xc + lb / 2, -0.06 * H), fill="#9CA3AF", outline=T.INK)
        nodes = r["nodes"]
        # 스트럿 띠 (실제 폭)
        for m in r["mem"]:
            a, b_ = nodes[m["i"]], nodes[m["j"]]
            if m["F"] < 0:
                wdt = r["ws"] if m["kind"] == "top" else (min(m.get("w_top", 0), m.get("w_bot", 0)) or 0.1 * H)
                if m["kind"] == "vert":
                    wdt = r["top"][int(m["i"][1:]) - 1][2]
                _band(cv, P, a, b_, wdt, C_STRUT, C_STRUT_E)
            elif m["F"] > 0 and m["kind"] == "bot":
                _band(cv, P, a, b_, r["wt"], C_TIE_B, "")
        for m in r["mem"]:
            a, b_ = nodes[m["i"]], nodes[m["j"]]
            pa, pb = P(*a), P(*b_)
            if m["F"] > 0:
                cv.create_line(*pa, *pb, fill=C_TIE, width=3)
            elif m["F"] < 0:
                cv.create_line(*pa, *pb, fill=C_STRUT_E, width=1)
            else:
                continue
            mx, my = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
            lab = f"{m.get('label', '')} {abs(m['F']) / 1e3:,.0f}"
            dy = -9 if m["kind"] == "top" else (11 if m["kind"] == "bot" else 0)
            dx = 0 if m["kind"] in ("top", "bot") else 6
            cv.create_text(mx + dx, my + dy, text=lab, font=F["s"], anchor="w" if dx else "center",
                           fill=C_TIE if m["F"] > 0 else C_STRUT_E)
        for nm, (xn, yn) in nodes.items():
            used = any(nm in (m["i"], m["j"]) and m["F"] != 0 for m in r["mem"])
            if not used:
                continue
            px, py = P(xn, yn)
            cv.create_oval(px - 3.5, py - 3.5, px + 3.5, py + 3.5, fill=C_NODE, outline=T.INK)
        # 하중
        for k, t in enumerate(r["top"], 1):
            px, py = P(t[0], H)
            cv.create_rectangle(*P(t[0] - t[2] / 2, H + 0.035 * H), *P(t[0] + t[2] / 2, H),
                                fill="#4B5563" if not t[3] else "#D1D5DB", outline=T.INK)
            cv.create_line(px, py - 40, px, py - 0.035 * H * s - 1, fill=T.NG, width=2, arrow="last")
            cv.create_text(px, py - 47, text=f"P{k} = {t[1] / 1e3:,.0f} kN" + (" (분포)" if t[3] else ""),
                           font=F["s"], fill=T.NG)
        # 반력 · 치수
        for xc, R, nm in ((0.0, r["R1"], "RA"), (r["L"], r["R2"], "RB")):
            px, py = P(xc, -0.06 * H)
            cv.create_text(px, py + 12, text=f"{nm} = {R / 1e3:,.0f} kN", font=F["s"], fill=T.INK)
        pa, pb = P(0, -0.06 * H), P(r["L"], -0.06 * H)
        yy = pa[1] + 30
        cv.create_line(pa[0], yy, pb[0], yy, fill=T.MUTED, arrow="both", arrowshape=(6, 7, 2))
        cv.create_text((pa[0] + pb[0]) / 2, yy + 9, text=f"L = {r['L']:,.0f}", font=F["s"], fill=T.MUTED)
        xr = P(x1m, 0)[0] + 12
        cv.create_line(xr, P(0, H)[1], xr, P(0, 0)[1], fill=T.MUTED, arrow="both", arrowshape=(6, 7, 2))
        cv.create_text(xr + 4, (P(0, H)[1] + P(0, 0)[1]) / 2, text=f"h={r['h']:g}", font=F["s"], fill=T.MUTED,
                       anchor="w")
        xl = P(x0m, 0)[0] - 6
        cv.create_text(xl, P(0, r["u"])[1], text=f"u={r['u']:.0f}", font=F["s"], fill=C_TIE, anchor="e")
        cv.create_text(xl, P(0, r["jd"] + r["u"])[1], text=f"ws={r['ws']:.0f}", font=F["s"], fill=C_STRUT_E,
                       anchor="e")
        cv.create_text(x + 10, y + 12, text="스트럿-타이 모델  (파랑 띠: 스트럿 폭, 빨강: 타이, 단위 kN)",
                       font=F["s"], fill=T.MUTED, anchor="w")
    return draw


def draw_rebar(r):
    def draw(cv, x, y, w, h):
        F = fonts(cv)
        ew = w * 0.70
        P, s, x0m, x1m = _frame(r, x, y, ew, h, pad_x=24, pad_top=40, pad_bot=40)
        H, cc = r["h"], r["cc"]
        ds = B.BARS[r["v_bar"]][0]
        cv.create_rectangle(*P(x0m, H), *P(x1m, 0), fill="white", outline=T.INK, width=1.5)
        wv = r["web"]
        # 수직 스터럽
        xx = x0m + cc + ds / 2 + 50
        while xx < x1m - cc - 40:
            cv.create_line(*P(xx, cc), *P(xx, H - cc), fill="#059669", width=1)
            xx += wv["sv"]
        # 수평 철근
        yy = r["rows"][-1][2] + wv["sh"]
        while yy < H - cc - 0.6 * wv["sh"]:
            cv.create_line(*P(x0m + cc, yy), *P(x1m - cc, yy), fill="#7C3AED", width=1)
            yy += wv["sh"]
        # 상부 조립근
        cv.create_line(*P(x0m + cc, H - cc - ds - 8), *P(x1m - cc, H - cc - ds - 8), fill=T.INK, width=2)
        # 하부 타이 (갈고리 표시)
        for _, _, yb in r["rows"]:
            a, b_ = P(x0m + cc, yb), P(x1m - cc, yb)
            cv.create_line(*a, *b_, fill=C_TIE, width=2.5)
            if r["anchor"] != "직선 정착 가능":
                up = min(0.25 * H, 12 * B.BARS[r["tie_bar"]][0]) * s
                cv.create_line(a[0], a[1], a[0], a[1] - up, fill=C_TIE, width=2.5)
                cv.create_line(b_[0], b_[1], b_[0], b_[1] - up, fill=C_TIE, width=2.5)
        for xc, lb in ((0.0, r["lb1"]), (r["L"], r["lb2"])):
            cv.create_rectangle(*P(xc - lb / 2, 0), *P(xc + lb / 2, -0.05 * H), fill="#9CA3AF", outline=T.INK)
        rb = rebar_text(r)
        cv.create_text(x + 10, y + 12, text=f"배근도  ·  수직 {rb['vert']}   수평 {rb['horz']}", font=F["s"],
                       fill=T.MUTED, anchor="w")
        cv.create_text(x + 10, y + h - 12, text=f"하부 타이 {rb['tie']}  ·  정착: {r['anchor']}", font=F["s"],
                       fill=C_TIE, anchor="w")
        # 단면
        sx0 = x + ew + 10
        sw = w - ew - 20
        sc = min((sw - 30) / r["b"], (h - 80) / H)
        bx = sx0 + (sw - r["b"] * sc) / 2
        by = y + 36

        def Q(xm, ym):
            return bx + xm * sc, by + (H - ym) * sc
        cv.create_rectangle(*Q(0, H), *Q(r["b"], 0), fill="#F8FAFC", outline=T.INK, width=1.5)
        cv.create_rectangle(*Q(cc + ds / 2, H - cc - ds / 2), *Q(r["b"] - cc - ds / 2, cc + ds / 2), outline="#059669")
        db = B.BARS[r["tie_bar"]][0]
        for _, k, yb in r["rows"]:
            xs = [cc + ds + db / 2] if k == 1 else [cc + ds + db / 2 + i * (r["b"] - 2 * (cc + ds) - db) / (k - 1)
                                                    for i in range(k)]
            for xb in xs:
                px, py = Q(xb, yb)
                rr = max(db / 2 * sc, 2.5)
                cv.create_oval(px - rr, py - rr, px + rr, py + rr, fill=C_TIE, outline=C_TIE)
        dh = B.BARS[r["h_bar"]][0]
        yy = r["rows"][-1][2] + wv["sh"]
        while yy < H - cc - 0.6 * wv["sh"]:
            for xb in (cc + ds + dh / 2, r["b"] - cc - ds - dh / 2):
                px, py = Q(xb, yy)
                rr = max(dh / 2 * sc, 1.8)
                cv.create_oval(px - rr, py - rr, px + rr, py + rr, fill="#7C3AED", outline="#7C3AED")
            yy += wv["sh"]
        for xb in (cc + ds + 8, r["b"] - cc - ds - 8):
            px, py = Q(xb, H - cc - ds - 8)
            cv.create_oval(px - 3, py - 3, px + 3, py + 3, fill=T.INK)
        cv.create_text(sx0 + sw / 2, y + 16, text=f"단면 {r['b']:g} × {r['h']:g}", font=F["s"], fill=T.MUTED)
    return draw
