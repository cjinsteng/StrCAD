"""
basic_design/rc/slab_calc.py
RC 슬래브 Lite — 단일 슬래브(등분포하중) 설계 계산 (Tk 비의존 · 순수 계산)

적용 기준
  · 하중조합            KDS 41 12 00   U = max(1.4D, 1.2D + 1.6L)
  · 1방향 모멘트·전단   KDS 14 20 10 4.3.1 근사해법 (모멘트 계수)
  · 2방향 모멘트·전단   4변 지지 슬래브 계수법 (slab_coef.py)
  · 휨 설계             KDS 14 20 20 4.1 (등가직사각형 응력블록, φ = 0.85)
  · 최소(수축·온도)철근 KDS 14 20 50 4.6.2,  KDS 14 20 20 4.2.2(3)
  · 균열제어 철근간격   KDS 14 20 20 4.2.3(4)  (1방향 슬래브)
  · 최소 두께           KDS 14 20 30 표 4.2-1 (1방향),  4.2.2 (2방향)
  · 전단                KDS 14 20 22 4.2.1   φVc = 0.75·(1/6)·√fck·b·d

단위: 길이 m(경간)·mm(단면), 하중 kN/m², 모멘트 kN·m/m, 전단 kN/m, 강도 MPa
"""
import math

from . import slab_coef as COEF

PHI_F = 0.85
PHI_V = 0.75
ES = 200000.0

REBAR = {            # 호칭 : (공칭지름 mm, 공칭단면적 mm²)
    "D10": (9.53, 71.33), "D13": (12.7, 126.7), "D16": (15.9, 198.6),
    "D19": (19.1, 286.5), "D22": (22.2, 387.1),
}
BAR_ORDER = ["D10", "D13", "D16", "D19", "D22"]


def spacing_cols(bar):
    """배근 간격표 열: 선택 철근을 가운데 두고 한 단계 아래·위 철근과 혼용
       D10 → D10, D10+D13, D13, D13+D16, D16   (D10 아래 철근이 없으므로 D13 이 가운데)
       D13 → D10, D10+D13, D13, D13+D16, D16
       D16 → D13, D13+D16, D16, D16+D19, D19"""
    i = BAR_ORDER.index(bar) if bar in BAR_ORDER else 0
    k = max(0, min(i - 1, len(BAR_ORDER) - 3))
    a, b, c = BAR_ORDER[k:k + 3]
    return [(a,), (a, b), (b,), (b, c), (c,)]


def col_labels(cols):
    return ["+".join(c) for c in cols]

ONE_WAY_SUPPORTS = {   # key : (표시, 최소두께 l/n, 표 4.2-1 구분)
    "SS":   ("단순 ── 단순",               20.0, "단순 지지"),
    "DC":   ("불연속(단순) ── 연속",       24.0, "1단 연속"),
    "DCI":  ("불연속(보 일체) ── 연속",    24.0, "1단 연속"),
    "CC":   ("연속 ── 연속",               28.0, "양단 연속"),
    "CANT": ("캔틸레버",                   10.0, "캔틸레버"),
}
EXPOSURES = {"건조환경 (κcr=280)": 280.0, "그 외 환경 (κcr=210)": 210.0}


class SlabInputError(ValueError):
    """입력값 오류 — 메시지를 그대로 사용자에게 보여준다."""


# ── 공통 ──────────────────────────────────────────────────────
def bar_no(bar):
    return int(bar[1:])


def fy_of(bar, fy13, fy16):
    """철근 호칭에 따른 항복강도: D13 이하 → fy13, D16 이상 → fy16"""
    return fy13 if bar_no(bar) <= 13 else fy16


def stress_block(fck):
    """KDS 14 20 20 표 4.1-2 등가직사각형 응력블록 계수 (η, β1, εcu) — 사이값 직선보간"""
    pts = [(40, 1.00, 0.80, 0.0033), (50, 0.97, 0.80, 0.0032), (60, 0.95, 0.76, 0.0031),
           (70, 0.91, 0.74, 0.0030), (80, 0.87, 0.72, 0.0029), (90, 0.84, 0.70, 0.0028)]
    if fck <= 40:
        return pts[0][1:]
    if fck >= 90:
        return pts[-1][1:]
    for (f0, e0, b0, c0), (f1, e1, b1, c1) in zip(pts, pts[1:]):
        if f0 <= fck <= f1:
            r = (fck - f0) / (f1 - f0)
            return (e0 + (e1 - e0) * r, b0 + (b1 - b0) * r, c0 + (c1 - c0) * r)
    return pts[-1][1:]


def strain_limits(fy):
    """(εy, 인장지배 한계, 휨부재 최소 허용변형률)  — KDS 14 20 20 4.1.2"""
    ey = fy / ES
    return ey, (0.005 if fy <= 400 else 2.5 * ey), (0.004 if fy <= 400 else 2.0 * ey)


def phi_of(eps_t, fy, pf=PHI_F):
    """εt 에 따른 휨 강도감소계수: 인장지배 pf(기본 0.85), 압축지배 0.65, 변화구간 직선보간"""
    ey, lim, _ = strain_limits(fy)
    lo = min(0.65, pf)
    if eps_t >= lim:
        return pf
    if eps_t <= ey:
        return lo
    return lo + (pf - lo) * (eps_t - ey) / (lim - ey)


def section(as_, d, fck, fy, b=1000.0, pf=PHI_F):
    """단철근 직사각형 단면 해석 → dict(a, c, eps_t, phi, phi_mn[kN·m])"""
    eta, beta1, ecu = stress_block(fck)
    a = as_ * fy / (0.85 * eta * fck * b)
    c = a / beta1
    eps_t = ecu * (d - c) / c if c > 0 else 1.0
    phi = phi_of(eps_t, fy, pf)
    return {"a": a, "c": c, "eps_t": eps_t, "phi": phi, "phi_mn": phi * as_ * fy * (d - a / 2.0) / 1e6}


def flexure(mu, d, fck, fy, b=1000.0, pf=PHI_F):
    """단철근 직사각형 단면 소요철근량 (φMn = Mu).
    인장지배(φ=0.85)로 풀어 εt 가 한계 미만이면 변화구간 φ(εt) 를 적용해 다시 구한다.
    εt 가 휨부재 최소 허용변형률 미만이 되어야 하면 단면 부족(N.G.).
    반환 dict(ok, rho, as_req, a, c, eps_t, phi, msg)"""
    eta, beta1, ecu = stress_block(fck)
    fc = 0.85 * eta * fck
    out = {"ok": True, "rho": 0.0, "as_req": 0.0, "a": 0.0, "c": 0.0, "eps_t": None, "phi": pf, "msg": ""}
    if mu <= 0 or d <= 0:
        return out
    _, lim, emin = strain_limits(fy)
    as_req = None
    disc = 1.0 - 2.0 * (mu * 1e6 / (pf * b * d * d)) / fc
    if disc > 0:
        as0 = fc / fy * (1.0 - math.sqrt(disc)) * b * d
        if section(as0, d, fck, fy, b, pf)["eps_t"] >= lim:
            as_req = as0
    if as_req is None:                                   # 변화구간: φ(εt)·Mn(As) = Mu 를 이분법으로
        c_max = ecu * d / (ecu + emin)
        as_max = fc * b * beta1 * c_max / fy
        if section(as_max, d, fck, fy, b, pf)["phi_mn"] < mu:
            out.update(ok=False, msg=f"단면 부족 — εt < εt,min({emin:.4f}), 두께 증가 필요")
            return out
        lo, hi = 0.0, as_max
        for _ in range(60):
            mid = (lo + hi) / 2.0
            if section(mid, d, fck, fy, b, pf)["phi_mn"] < mu:
                lo = mid
            else:
                hi = mid
        as_req = hi
    sec = section(as_req, d, fck, fy, b, pf)
    out.update(rho=as_req / (b * d), as_req=as_req, a=sec["a"], c=sec["c"], eps_t=sec["eps_t"], phi=sec["phi"])
    return out


def phi_mn(as_prov, d, fck, fy, b=1000.0, pf=PHI_F):
    """설계휨강도 φMn (kN·m / 폭 b) — φ 는 εt 에 따라"""
    return section(as_prov, d, fck, fy, b, pf)["phi_mn"]


def rho_min(fy):
    """KDS 14 20 50 4.6.2 수축·온도철근비 (전체 단면적 기준)"""
    return 0.0020 if fy <= 400 else max(0.0020 * 400.0 / fy, 0.0014)


def phi_vc(d, fck, b=1000.0, pv=PHI_V):
    """φVc (kN / 폭 b) — KDS 14 20 22 식(4.2-1), λ = 1.0"""
    return pv * math.sqrt(fck) * b * d / 6.0 / 1000.0


def factored(wd, wl):
    """(wu, wdu, wlu, 식 문자열)"""
    u1, u2 = 1.4 * wd, 1.2 * wd + 1.6 * wl
    if u1 > u2:
        return u1, u1, 0.0, "1.4×Wd"
    return u2, 1.2 * wd, 1.6 * wl, "1.2×Wd+1.6×Wl"


def _floor10(x):
    return int(math.floor(x / 10.0 + 1e-9) * 10)


def _col_area(col):
    return sum(REBAR[b][1] for b in col) / len(col)


def _col_fy(col, fy13, fy16):
    return min(fy_of(b, fy13, fy16) for b in col)


def spacings(as_by_fy, fy13, fy16, s_max, cols):
    """배근 간격표 한 행: 열마다 (간격 mm | None)."""
    out = []
    for col in cols:
        as_req = as_by_fy[_col_fy(col, fy13, fy16)]
        s = s_max if as_req <= 0 else min(_col_area(col) / as_req * 1000.0, s_max)
        s = _floor10(s)
        out.append(s if s >= 50 else None)          # 50mm 미만은 배근 불가로 표시
    return out


def _common(inp):
    for k, lbl in (("phi_f", "휨 강도감소계수 φf"), ("phi_v", "전단 강도감소계수 φv")):
        v = inp.get(k)
        if v is not None and not (0.0 < v <= 1.0):
            raise SlabInputError(f"{lbl} 는 0 초과 1.0 이하로 입력하세요.")
    fck, fy13, fy16 = inp["fck"], inp["fy13"], inp["fy16"]
    t, cc, bar = inp["t"], inp["cc"], inp["bar"]
    if bar not in REBAR:
        raise SlabInputError(f"사용 철근 '{bar}' 을(를) 알 수 없습니다.")
    for k, lbl in (("fck", "fck"), ("fy13", "fy(D13↓)"), ("fy16", "fy(D16↑)"), ("t", "두께 T")):
        if inp[k] <= 0:
            raise SlabInputError(f"{lbl} 값은 0보다 커야 합니다.")
    if cc < 0:
        raise SlabInputError("피복두께 Cc 는 0 이상이어야 합니다.")
    if inp["wd"] < 0 or inp["wl"] < 0:
        raise SlabInputError("하중은 0 이상이어야 합니다.")
    if inp["wd"] + inp["wl"] <= 0:
        raise SlabInputError("하중(Wd, Wl)을 입력하세요.")
    db = REBAR[bar][0]
    if t - cc - db / 2.0 <= 10:
        raise SlabInputError("두께에 비해 피복두께가 너무 큽니다 (유효깊이 부족).")
    fy = fy_of(bar, fy13, fy16)
    return fck, fy13, fy16, fy, t, cc, bar, db


def _row(direction, loc, mu, formula, d, fck, fy, fy13, fy16, s_max, cols, pf=PHI_F):
    """휨 배근표 한 행 계산"""
    fl = flexure(mu, d, fck, fy, pf=pf)
    as_by_fy = {f: flexure(mu, d, fck, f, pf=pf)["as_req"] for f in {fy13, fy16}}
    sp = spacings(as_by_fy, fy13, fy16, s_max, cols)
    if not fl["ok"]:
        sp = [None] * len(cols)
    return {"dir": direction, "loc": loc, "mu": mu, "formula": formula, "d": d,
            "rho": fl["rho"], "as_req": fl["as_req"], "ok": fl["ok"], "msg": fl["msg"],
            "eps_t": fl["eps_t"], "phi": fl["phi"], "sp": sp, "s_max": s_max}


def _summary(rows, min_row, bar, fck, fy, cols, pf=PHI_F):
    """선택 철근 기준 최종 배근 (소요·최소 중 좁은 간격)"""
    idx = col_labels(cols).index(bar)
    area = REBAR[bar][1]
    _, _, emin = strain_limits(fy)
    out = []
    for r in rows:
        base = {"dir": r["dir"], "loc": r["loc"], "mu": r["mu"], "s": None, "as_prov": 0, "phi_mn": 0, "phi": None,
                "ok": False, "gov": "-"}
        if not r["ok"]:
            out.append(dict(base, why="단면 부족"))
            continue
        s_req, s_min = r["sp"][idx], min_row["sp"][idx]
        if s_req is None or s_min is None:
            out.append(dict(base, why="간격 50 미만"))
            continue
        s = min(s_req, s_min)
        as_prov = area / s * 1000.0
        sec = section(as_prov, r["d"], fck, fy, pf=pf)
        ok = sec["phi_mn"] + 1e-9 >= r["mu"] and sec["eps_t"] >= emin
        if s_min < s_req:
            gov = "최소철근"
        elif r["as_req"] > 0 and area / r["as_req"] * 1000.0 >= r["s_max"] + 10:
            gov = "간격제한"
        else:
            gov = "휨"
        out.append(dict(base, s=s, as_prov=as_prov, phi_mn=sec["phi_mn"], phi=sec["phi"], ok=ok, gov=gov,
                        why="" if ok else ("과다 배근(εt<εt,min)" if sec["eps_t"] < emin else "강도 부족")))
    return out


def _phi_notes(rows, pf=PHI_F):
    return [f"{(r['dir'] + ' ') if r['dir'] not in ('', 'Main') else ''}{r['loc']}: 변화구간 단면 "
            f"(εt = {r['eps_t']:.4f}) → φ = {r['phi']:.3f} 적용" for r in rows if r["ok"] and r["phi"] < pf - 1e-6]


# ── 처짐 (KDS 14 20 30 4.2.1) ────────────────────────────────
XI_POINTS = [(0, 0.0), (3, 1.0), (6, 1.2), (12, 1.4), (60, 2.0)]     # 재하기간(개월) – 시간경과계수 ξ


def xi_of(months):
    """지속하중 시간경과계수 ξ: 3개월 1.0, 6개월 1.2, 12개월 1.4, 5년 이상 2.0 (사이값 직선보간)"""
    m = max(0.0, min(float(months), 60.0))
    for (m0, x0), (m1, x1) in zip(XI_POINTS, XI_POINTS[1:]):
        if m0 <= m <= m1:
            return x0 + (x1 - x0) * (m - m0) / (m1 - m0)
    return 2.0


def ec_of(fck):
    """콘크리트 탄성계수 Ec = 8500·∛fcm  (KDS 14 20 10 4.3.3, fcm = fck + Δf)"""
    df = 4.0 if fck <= 40 else (6.0 if fck >= 60 else 4.0 + (fck - 40) / 10.0)
    return 8500.0 * (fck + df) ** (1.0 / 3.0)


def i_cracked(as_, d, n, b=1000.0):
    """균열 환산단면 2차모멘트 (단철근, mm⁴ / 폭 b)"""
    if as_ <= 0:
        return 0.0
    na = n * as_
    c = (-na + math.sqrt(na * na + 2.0 * b * na * d)) / b
    return b * c ** 3 / 3.0 + na * (d - c) ** 2


def i_eff(mcr, ma, ig, icr):
    """유효단면 2차모멘트 (KDS 14 20 30 식 4.2-1)"""
    if ma <= mcr or ma <= 0:
        return ig
    k = (mcr / ma) ** 3
    return min(k * ig + (1.0 - k) * icr, ig)


def deflection_one_way(r, months=60, lim_live=360.0, lim_long=480.0, sus_live=0.5):
    """1방향 슬래브 처짐 검토.  r: calc_one_way 결과.
    · 사용하중 모멘트 = 강도설계와 같은 계수(wl²/n)에 사용하중을 적용
    · 균열단면은 소요철근량(최소철근 이상) 기준,  Ie 는 연속단 가중평균
    · Δ = 5L²/(48·Ec·Ie)·[Mm - 0.1(M1+M2)],  캔틸레버 Δ = M·L²/(4·Ec·Ie)
    · 단기: 활하중 순간처짐 Δ(D+L) - Δ(D) ≤ L/lim_live
    · 장기: ξ·Δ(지속) + [Δ(D+L) - Δ(D)] ≤ L/lim_long   (ρ' = 0 → λΔ = ξ)"""
    t, d, fck, fy, L = r["t"], r["d"], r["fck"], r["fy"], r["L"] * 1000.0
    sup = r["support"]
    ec = ec_of(fck)
    n = ES / ec
    ig = 1000.0 * t ** 3 / 12.0
    fr = 0.63 * math.sqrt(fck)
    mcr = fr * ig / (t / 2.0) / 1e6
    xi = xi_of(months)
    as_min = r["min_row"]["as_req"]
    coef = {}                                         # 위치 → (분모 n, 소요 As)
    for row in r["rows"]:
        key = row["loc"].split()[-1]                  # Cont / Pos / DisC
        coef[key] = (r["L"] ** 2 / row["mu"] * r["wu"] if row["mu"] else None, max(row["as_req"], as_min))

    def moments(w):
        """(M1, Mm, M2) 사용하중 모멘트 크기 [kN·m/m] — M1·M2 는 단부(부모멘트)"""
        def m(key):
            return w * r["L"] ** 2 / coef[key][0] if key in coef and coef[key][0] else 0.0
        if sup == "CANT":
            return m("Cont"), 0.0, 0.0
        if sup == "SS":
            return 0.0, m("Pos"), 0.0
        if sup == "CC":
            return m("Cont"), m("Pos"), m("Cont")
        return m("DisC"), m("Pos"), m("Cont")          # 좌: 불연속단, 우: 연속단

    icr_end = i_cracked(coef["Cont"][1], d, n) if "Cont" in coef else 0.0
    icr_pos = i_cracked(coef["Pos"][1], d, n) if "Pos" in coef else 0.0
    icr_dis = i_cracked(coef["DisC"][1], d, n) if "DisC" in coef else 0.0

    def ie_of(w):
        m1, mm, m2 = moments(w)
        if sup == "CANT":
            return i_eff(mcr, m1, ig, icr_end)
        iem = i_eff(mcr, mm, ig, icr_pos)
        if sup == "SS":
            return iem
        if sup == "CC":
            return 0.70 * iem + 0.15 * (i_eff(mcr, m1, ig, icr_end) + i_eff(mcr, m2, ig, icr_end))
        return 0.85 * iem + 0.15 * i_eff(mcr, m2, ig, icr_end)     # 한쪽 연속

    def delta(w, ie):
        m1, mm, m2 = moments(w)
        if sup == "CANT":
            return m1 * 1e6 * L ** 2 / (4.0 * ec * ie)
        return 5.0 * L ** 2 / (48.0 * ec * ie) * max(mm - 0.1 * (m1 + m2), 0.0) * 1e6

    wd, wl = r["wd"], r["wl"]
    loads = {"d": wd, "l": wl, "dl": wd + wl, "s": wd + sus_live * wl}
    ie = {k: ie_of(w) for k, w in loads.items()}      # 활하중 순간처짐 검토는 Δ(D+L) - Δ(D) 로 산정
    dd = delta(wd, ie["d"])
    ddl = delta(wd + wl, ie["dl"])
    ds = delta(loads["s"], ie["s"])
    dl_inst = ddl - dd
    long_ = xi * ds + dl_inst
    a_live, a_long = L / lim_live, L / lim_long
    m_end = moments(1.0)
    return {
        "months": months, "xi": xi, "ec": ec, "n": n, "ig": ig, "fr": fr, "mcr": mcr, "sus_live": sus_live,
        "has_end": sup != "SS", "has_pos": sup != "CANT",
        "end": {k: (m_end[2] if sup not in ("CANT",) else m_end[0]) * w for k, w in loads.items() if k != "dl"},
        "pos": {k: m_end[1] * w for k, w in loads.items() if k != "dl"},
        "icr_end": icr_end if sup != "CANT" else icr_end, "icr_pos": icr_pos, "icr_dis": icr_dis,
        "as_end": coef.get("Cont", (0, 0))[1], "as_pos": coef.get("Pos", (0, 0))[1],
        "ie": ie, "dd": dd, "dl": delta(wl, ie["l"]), "ddl": ddl, "ds": ds,
        "dl_inst": dl_inst, "long": long_, "lim_live": lim_live, "lim_long": lim_long,
        "a_live": a_live, "a_long": a_long, "ok_live": dl_inst <= a_live + 1e-9, "ok_long": long_ <= a_long + 1e-9,
    }


# ── 1방향 슬래브 ──────────────────────────────────────────────
def calc_one_way(inp):
    """inp: name, span(m, 순경간), t, cc, fck, fy13, fy16, wd, wl, bar,
            support('SS'|'DC'|'DCI'|'CC'|'CANT'), spans(2|3), kcr(280|210)"""
    fck, fy13, fy16, fy, t, cc, bar, db = _common(inp)
    pf, pv = inp.get("phi_f", PHI_F), inp.get("phi_v", PHI_V)
    L = inp["span"]
    if L <= 0:
        raise SlabInputError("경간(Span)은 0보다 커야 합니다.")
    sup = inp.get("support", "CC")
    if sup not in ONE_WAY_SUPPORTS:
        raise SlabInputError("지지형식을 선택하세요.")
    two_span = int(inp.get("spans", 3)) == 2
    kcr = float(inp.get("kcr", 210.0))
    wu, wdu, wlu, wu_txt = factored(inp["wd"], inp["wl"])
    w2 = wu * L * L
    d = t - cc - db / 2.0

    # 모멘트·전단 (KDS 14 20 10 4.3.1(4))
    short = L <= 3.0                                 # 경간 3 m 이하 슬래브: 받침부 부모멘트 wl²/12
    mom = []                                         # (위치, 계수분모, 비고)
    if sup == "SS":
        mom = [("Pos", "중앙부", 8.0, "")]
        vu, v_txt = wu * L / 2.0, "Wu·L/2"
    elif sup == "CANT":
        mom = [("Cont", "고정단", 2.0, "")]
        vu, v_txt = wu * L, "Wu·L"
    elif sup == "CC":
        mom = [("Cont", "연속단", 12.0 if short else 11.0, "경간 3m 이하" if short else ""),
               ("Pos", "중앙부", 16.0, "")]
        vu, v_txt = wu * L / 2.0, "Wu·L/2"
    else:
        n_int = 12.0 if short else (9.0 if two_span else 10.0)
        note = "경간 3m 이하" if short else ("2경간" if two_span else "3경간 이상")
        mom = [("Cont", "연속단", n_int, note)]
        if sup == "DCI":
            mom += [("DisC", "불연속단", 24.0, "테두리보"), ("Pos", "중앙부", 14.0, "")]
        else:
            mom += [("Pos", "중앙부", 11.0, "")]
        vu, v_txt = 1.15 * wu * L / 2.0, "1.15·Wu·L/2"

    # 모멘트도·전단도용 설계값 (좌단, 중앙, 우단) — 부모멘트는 양수 크기로 저장
    mv = {key: w2 / n for key, _, n, _ in mom}
    if sup == "CANT":
        diagram = {"ml": mv["Cont"], "mp": 0.0, "mr": 0.0, "vl": vu, "vr": 0.0}
    elif sup == "CC":
        diagram = {"ml": mv["Cont"], "mp": mv["Pos"], "mr": mv["Cont"], "vl": vu, "vr": -vu}
    elif sup == "SS":
        diagram = {"ml": 0.0, "mp": mv["Pos"], "mr": 0.0, "vl": vu, "vr": -vu}
    else:                                            # 좌: 불연속단, 우: 첫 번째 내부 받침부
        diagram = {"ml": mv.get("DisC", 0.0), "mp": mv["Pos"], "mr": mv["Cont"], "vl": wu * L / 2.0, "vr": -vu}

    # 간격 제한
    fs = 2.0 / 3.0 * fy
    s_crack = min(375.0 * kcr / fs - 2.5 * cc, 300.0 * kcr / fs)
    s_code = min(2.0 * t, 300.0)                     # 위험단면 주철근: 2t, 300mm 이하
    s_main = max(min(s_code, s_crack), 0.0)
    s_temp = min(5.0 * t, 450.0)                     # 수축·온도철근: 5t, 450mm 이하

    cols = spacing_cols(bar)
    rows = []
    for key, loc, n, note in mom:
        rows.append(_row("Main", f"{loc} {key}", w2 / n, f"Wu·L²/{n:g}" + (f" ({note})" if note else ""),
                         d, fck, fy, fy13, fy16, s_main, cols, pf))

    def min_bar(s_max, label):
        as_by_fy = {f: rho_min(f) * 1000.0 * t for f in {fy13, fy16}}
        return {"dir": "", "loc": label, "mu": None, "rho": rho_min(fy), "as_req": rho_min(fy) * 1000.0 * t,
                "sp": spacings(as_by_fy, fy13, fy16, s_max, cols), "s_max": s_max, "ok": True, "d": d}
    min_row = min_bar(s_main, "Min Bar")             # 경간방향 최소철근 (주철근 간격 제한 적용)
    temp_row = min_bar(s_temp, "Temp. Bar")          # 직각방향 수축·온도철근(배력근)

    # 최소 두께 (KDS 14 20 30 표 4.2-1)
    n_h = ONE_WAY_SUPPORTS[sup][1]
    k_fy = 1.0 if abs(fy - 400.0) < 1e-6 else 0.43 + fy / 700.0
    h_req = L * 1000.0 / n_h * k_fy

    pvc = phi_vc(d, fck, pv=pv)
    warn = []
    if sup not in ("SS", "CANT"):
        if inp["wl"] > 3.0 * inp["wd"]:
            warn.append("활하중이 고정하중의 3배를 초과 — 근사해법(모멘트 계수) 적용 조건을 벗어납니다.")
        warn.append("근사해법 조건: 2경간 이상, 인접 경간 차이 20% 이하, 등분포하중, 일정 단면 (KDS 14 20 10 4.3.1)")
    for r in rows:
        if not r["ok"]:
            warn.append(f"{r['loc']}: {r['msg']}")
    warn += _phi_notes(rows, pf)
    summary = _summary(rows, min_row, bar, fck, fy, cols, pf)
    temp_s = temp_row["sp"][col_labels(cols).index(bar)]

    res = {
        "type": "1way", "name": inp.get("name", ""), "inp": dict(inp), "phi_f": pf, "phi_v": pv,
        "L": L, "t": t, "cc": cc, "fck": fck, "fy13": fy13, "fy16": fy16, "fy": fy, "bar": bar, "db": db, "d": d,
        "support": sup, "support_txt": ONE_WAY_SUPPORTS[sup][0], "two_span": two_span,
        "wd": inp["wd"], "wl": inp["wl"], "wu": wu, "wu_txt": wu_txt,
        "h_req": h_req, "h_n": n_h, "h_kfy": k_fy, "h_ok": t + 1e-9 >= h_req,
        "rows": rows, "min_row": min_row, "temp_row": temp_row, "temp_s": temp_s,
        "cols": col_labels(cols), "sel_col": col_labels(cols).index(bar),
        "kcr": kcr, "fs": fs, "s_crack": s_crack, "s_code": s_code, "s_main": s_main, "s_temp": s_temp,
        "shear": [{"label": "", "vu": vu, "txt": v_txt, "phi_vc": pvc, "d": d, "ok": vu <= pvc + 1e-9}],
        "summary": summary, "warn": warn, "diagram": diagram,
    }
    res["defl"] = None
    if t + 1e-9 < h_req and all(rw["ok"] for rw in rows):         # 최소두께 미달 → 처짐 계산으로 검토
        res["defl"] = deflection_one_way(res, months=inp.get("months", 60), lim_live=inp.get("lim_live", 360.0),
                                         lim_long=inp.get("lim_long", 480.0), sus_live=inp.get("sus_live", 0.5))
    dfl = res["defl"]
    thk_ok = (t + 1e-9 >= h_req) or (dfl is not None and dfl["ok_live"] and dfl["ok_long"])
    res["ok"] = thk_ok and all(s["ok"] for s in summary) and vu <= pvc + 1e-9
    return res


# ── 2방향 슬래브 ──────────────────────────────────────────────
def beam_alpha(bw, h, t, slab_w, both_sides):
    """보-슬래브 휨강성비 αf = Ib / Is  (Ecb = Ecs).
    보 단면은 슬래브 아래로 내민 높이만큼(≤ 4t) 연장한 플랜지를 포함한다."""
    if bw <= 0 or h <= 0 or slab_w <= 0:
        return 0.0
    if h <= t:
        return bw / slab_w
    hw = h - t
    proj = min(hw, 4.0 * t)
    bf = bw + proj * (2 if both_sides else 1)
    a1, y1 = bf * t, t / 2.0
    a2, y2 = bw * hw, t + hw / 2.0
    yb = (a1 * y1 + a2 * y2) / (a1 + a2)
    ib = bf * t ** 3 / 12.0 + a1 * (yb - y1) ** 2 + bw * hw ** 3 / 12.0 + a2 * (y2 - yb) ** 2
    return ib / (slab_w * t ** 3 / 12.0)


def _flat_min_n(fy, ext_no_edge_beam):
    """KDS 14 20 30 표 4.2-3 (지판 없음): ln / n 의 n"""
    fys = [300, 350, 400, 500, 600]
    col = [32, 31, 30, 28, 26] if ext_no_edge_beam else [35, 34, 33, 31, 29]
    if fy <= fys[0]:
        return col[0]
    if fy >= fys[-1]:
        return col[-1]
    for i in range(4):
        if fys[i] <= fy <= fys[i + 1]:
            return col[i] + (col[i + 1] - col[i]) * (fy - fys[i]) / (fys[i + 1] - fys[i])
    return col[-1]


def calc_two_way(inp):
    """inp: name, lx, ly (m, 중심간), t, cc, fck, fy13, fy16, wd, wl, bar, case(1~9),
            beams = [(b,h) ×4]  (B1 상, B2 하, B3 좌, B4 우 ; mm)
       Lx = 단변(가로), Ly = 장변(세로)"""
    fck, fy13, fy16, fy, t, cc, bar, db = _common(inp)
    pf, pv = inp.get("phi_f", PHI_F), inp.get("phi_v", PHI_V)
    lx, ly = inp["lx"], inp["ly"]
    if lx <= 0 or ly <= 0:
        raise SlabInputError("Lx, Ly 는 0보다 커야 합니다.")
    if lx > ly + 1e-9:
        raise SlabInputError("Lx 는 단변, Ly 는 장변입니다.\nLx ≤ Ly 가 되도록 입력하세요.")
    case = int(inp.get("case", 2))
    if case not in COEF.CASE_EDGES:
        raise SlabInputError("지지 형식(Case 1~9)을 선택하세요.")
    m = lx / ly
    if m < 0.5 - 1e-9:
        raise SlabInputError(f"변장비 Ly/Lx = {ly / lx:.2f} > 2.0 입니다.\n1방향 슬래브로 설계하세요.")
    beams = [tuple(float(v) for v in b) for b in inp.get("beams", [(0, 0)] * 4)]
    while len(beams) < 4:
        beams.append((0.0, 0.0))
    edges = COEF.CASE_EDGES[case]                    # (상, 하, 좌, 우) 연속 여부
    wu, wdu, wlu, wu_txt = factored(inp["wd"], inp["wl"])
    c = COEF.coefficients(m, case)

    d_s = t - cc - db / 2.0                          # 단변방향 철근 (바깥쪽)
    d_l = d_s - db                                   # 장변방향 철근 (안쪽)
    if d_l <= 10:
        raise SlabInputError("두께에 비해 피복두께가 너무 큽니다 (유효깊이 부족).")
    s_flex = min(2.0 * t, 300.0)                     # 위험단면: 2t, 300mm 이하
    s_min = min(5.0 * t, 450.0)                      # 수축·온도철근: 5t, 450mm 이하

    cols = spacing_cols(bar)
    rows = []

    def add(direction, d, n_cont, c_neg, c_dl, c_ll, span, sym):
        pos = (c_dl * wdu + c_ll * wlu) * span * span
        if n_cont > 0:
            rows.append(_row(direction, "연속단 Cont", c_neg * wu * span * span,
                             f"{c_neg:.4f}·Wu·{sym}²", d, fck, fy, fy13, fy16, s_flex, cols, pf))
        if n_cont < 2:
            rows.append(_row(direction, "불연속단 DisC", pos / 3.0, "M(Pos)/3", d, fck, fy, fy13, fy16, s_flex, cols, pf))
        rows.append(_row(direction, "중앙부 Pos", pos,
                         f"({c_dl:.4f}·Wdu+{c_ll:.4f}·Wlu)·{sym}²", d, fck, fy, fy13, fy16, s_flex, cols, pf))

    n_long_cont = int(edges[2]) + int(edges[3])      # 단변방향 경간의 양 끝 = 장변(좌·우)
    n_short_cont = int(edges[0]) + int(edges[1])     # 장변방향 경간의 양 끝 = 단변(상·하)
    add("Short", d_s, n_long_cont, c["ca_neg"], c["ca_dl"], c["ca_ll"], lx, "Lx")
    add("Long", d_l, n_short_cont, c["cb_neg"], c["cb_dl"], c["cb_ll"], ly, "Ly")

    as_by_fy = {f: rho_min(f) * 1000.0 * t for f in {fy13, fy16}}
    min_row = {"dir": "", "loc": "Min Bar", "mu": None, "rho": rho_min(fy), "as_req": rho_min(fy) * 1000.0 * t,
               "sp": spacings(as_by_fy, fy13, fy16, s_min, cols), "s_max": s_min, "ok": True, "d": d_s}

    # 최소 두께 (KDS 14 20 30 4.2.2)
    lnx = lx * 1000.0 - (beams[2][0] + beams[3][0]) / 2.0
    lny = ly * 1000.0 - (beams[0][0] + beams[1][0]) / 2.0
    if lnx <= 0 or lny <= 0:
        raise SlabInputError("지지보 폭이 경간보다 큽니다.")
    ln_long, ln_short = max(lnx, lny), min(lnx, lny)
    beta = ln_long / ln_short
    alphas = []
    for i, (bw, bh) in enumerate(beams[:4]):
        panel = ly * 1000.0 if i < 2 else lx * 1000.0       # 보 직각방향 패널 폭
        cont = edges[i]
        slab_w = panel if cont else panel / 2.0 + bw / 2.0
        alphas.append(beam_alpha(bw, bh, t, slab_w, cont))
    afm = sum(alphas) / 4.0
    weak_edge = any((not edges[i]) and alphas[i] < 0.8 for i in range(4))   # 불연속단 테두리보 α<0.8
    f_h = 800.0 + fy / 1.4
    if afm <= 0.2:
        n = _flat_min_n(fy, weak_edge)
        h_req = max(ln_long / n, 120.0)
        h_txt = f"ln/{n:g} ≥ 120  (αfm ≤ 0.2, 표 4.2-3)"
        inc = False
    elif afm < 2.0:
        h_req = ln_long * f_h / (36000.0 + 5000.0 * beta * (afm - 0.2))
        h_txt = "ln(800+fy/1.4)/(36000+5000β(αfm-0.2)) ≥ 120"
        inc = weak_edge
        h_req = max(h_req * (1.1 if inc else 1.0), 120.0)
    else:
        h_req = ln_long * f_h / (36000.0 + 9000.0 * beta)
        h_txt = "ln(800+fy/1.4)/(36000+9000β) ≥ 90"
        inc = weak_edge
        h_req = max(h_req * (1.1 if inc else 1.0), 90.0)

    # 전단 (하중 분담비)
    vux = c["wa"] * wu * lx / 2.0
    vuy = c["wb"] * wu * ly / 2.0
    shear = [
        {"label": "Short Direction Shear", "sym": "Vux", "vu": vux, "txt": f"{c['wa']:.3f}·Wu·Lx/2",
         "phi_vc": phi_vc(d_s, fck, pv=pv), "d": d_s},
        {"label": "Long Direction Shear", "sym": "Vuy", "vu": vuy, "txt": f"{c['wb']:.3f}·Wu·Ly/2",
         "phi_vc": phi_vc(d_l, fck, pv=pv), "d": d_l},
    ]
    for s in shear:
        s["ok"] = s["vu"] <= s["phi_vc"] + 1e-9

    warn = [f"{r['dir']} {r['loc']}: {r['msg']}" for r in rows if not r["ok"]]
    if inc:
        warn.append("불연속단 테두리보 강성비 αf < 0.8 — 최소 두께 10% 증대 적용 (KDS 14 20 30 4.2.2(3)③)")
    warn += _phi_notes(rows, pf)
    summary = _summary(rows, min_row, bar, fck, fy, cols, pf)
    h_ok = t + 1e-9 >= h_req

    return {
        "type": "2way", "name": inp.get("name", ""), "inp": dict(inp), "phi_f": pf, "phi_v": pv,
        "lx": lx, "ly": ly, "m": m, "case": case, "edges": edges, "beams": beams, "coef": c,
        "t": t, "cc": cc, "fck": fck, "fy13": fy13, "fy16": fy16, "fy": fy, "bar": bar, "db": db,
        "d_s": d_s, "d_l": d_l,
        "wd": inp["wd"], "wl": inp["wl"], "wu": wu, "wdu": wdu, "wlu": wlu, "wu_txt": wu_txt,
        "lnx": lnx, "lny": lny, "beta": beta, "alphas": alphas, "afm": afm,
        "h_req": h_req, "h_txt": h_txt, "h_inc": inc, "h_ok": h_ok,
        "rows": rows, "min_row": min_row, "s_flex": s_flex, "s_min": s_min,
        "cols": col_labels(cols), "sel_col": col_labels(cols).index(bar),
        "shear": shear, "summary": summary, "warn": warn,
        "ok": h_ok and all(s["ok"] for s in summary) and all(s["ok"] for s in shear),
    }


def calculate(inp):
    """inp['type'] : '1way' | '2way'"""
    return calc_one_way(inp) if inp.get("type") == "1way" else calc_two_way(inp)
