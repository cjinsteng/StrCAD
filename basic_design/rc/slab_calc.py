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
SPACING_COLS = [("D10",), ("D10", "D13"), ("D13",), ("D13", "D16"), ("D16",)]   # 배근 간격표 열
COL_LABELS = ["+".join(c) for c in SPACING_COLS]

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


def flexure(mu, d, fck, fy, b=1000.0):
    """단철근 직사각형 단면 소요철근량.
    mu: kN·m (폭 b 당).  반환 dict(ok, rho, as_req, a, c, eps_t, eps_lim, msg)"""
    eta, beta1, ecu = stress_block(fck)
    fc = 0.85 * eta * fck
    out = {"ok": True, "rho": 0.0, "as_req": 0.0, "a": 0.0, "c": 0.0, "eps_t": None, "eps_lim": None, "msg": ""}
    if mu <= 0 or d <= 0:
        return out
    rn = mu * 1e6 / (PHI_F * b * d * d)
    disc = 1.0 - 2.0 * rn / fc
    if disc <= 0:
        out.update(ok=False, msg="단면 부족(압축파괴) — 두께 증가 필요")
        return out
    rho = fc / fy * (1.0 - math.sqrt(disc))
    as_req = rho * b * d
    a = as_req * fy / (fc * b)
    c = a / beta1
    eps_t = ecu * (d - c) / c
    eps_lim = 0.005 if fy <= 400 else 2.5 * fy / ES          # 인장지배 한계 (φ=0.85 적용 조건)
    out.update(rho=rho, as_req=as_req, a=a, c=c, eps_t=eps_t, eps_lim=eps_lim)
    if eps_t < eps_lim:
        out.update(ok=False, msg="인장지배단면 아님(εt<한계) — 두께 증가 필요")
    return out


def phi_mn(as_prov, d, fck, fy, b=1000.0):
    """설계휨강도 φMn (kN·m / 폭 b)"""
    eta, _, _ = stress_block(fck)
    a = as_prov * fy / (0.85 * eta * fck * b)
    return PHI_F * as_prov * fy * (d - a / 2.0) / 1e6


def rho_min(fy):
    """KDS 14 20 50 4.6.2 수축·온도철근비 (전체 단면적 기준)"""
    return 0.0020 if fy <= 400 else max(0.0020 * 400.0 / fy, 0.0014)


def phi_vc(d, fck, b=1000.0):
    """φVc (kN / 폭 b) — KDS 14 20 22 식(4.2-1), λ = 1.0"""
    return PHI_V * math.sqrt(fck) * b * d / 6.0 / 1000.0


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


def spacings(as_by_fy, fy13, fy16, s_max):
    """배근 간격표 한 행: 열마다 (간격 mm | None)."""
    out = []
    for col in SPACING_COLS:
        as_req = as_by_fy[_col_fy(col, fy13, fy16)]
        s = s_max if as_req <= 0 else min(_col_area(col) / as_req * 1000.0, s_max)
        s = _floor10(s)
        out.append(s if s >= 50 else None)          # 50mm 미만은 배근 불가로 표시
    return out


def _common(inp):
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


def _row(direction, loc, mu, formula, d, fck, fy, fy13, fy16, s_max):
    """휨 배근표 한 행 계산"""
    fl = flexure(mu, d, fck, fy)
    as_by_fy = {f: flexure(mu, d, fck, f)["as_req"] for f in {fy13, fy16}}
    return {"dir": direction, "loc": loc, "mu": mu, "formula": formula, "d": d,
            "rho": fl["rho"], "as_req": fl["as_req"], "ok": fl["ok"], "msg": fl["msg"],
            "eps_t": fl["eps_t"], "sp": spacings(as_by_fy, fy13, fy16, s_max)}


def _summary(rows, min_row, bar, fck, fy, s_cap=None):
    """선택 철근 기준 최종 배근 (소요·최소 중 좁은 간격)"""
    idx = COL_LABELS.index(bar) if bar in COL_LABELS else None
    area = REBAR[bar][1]
    out = []
    for r in rows:
        if idx is not None:
            s_req, s_min = r["sp"][idx], min_row["sp"][idx]
        else:                                       # 표에 없는 철근(D19, D22)
            s_req = _floor10(min(area / r["as_req"] * 1000.0, r.get("s_max", 300))) if r["as_req"] > 0 else r.get("s_max", 300)
            s_min = _floor10(min(area / min_row["as_req"] * 1000.0, min_row.get("s_max", 450)))
        if s_req is None or s_min is None or not r["ok"]:
            out.append({"dir": r["dir"], "loc": r["loc"], "s": None, "as_prov": 0, "phi_mn": 0, "mu": r["mu"],
                        "ok": False, "gov": "-"})
            continue
        s = min(s_req, s_min)
        if s_cap:
            s = min(s, s_cap)
        as_prov = area / s * 1000.0
        pm = phi_mn(as_prov, r["d"], fck, fy)
        out.append({"dir": r["dir"], "loc": r["loc"], "s": s, "as_prov": as_prov, "phi_mn": pm, "mu": r["mu"],
                    "ok": pm + 1e-9 >= r["mu"],
                    "gov": "최소철근" if s_min < s_req else
                           ("간격제한" if r["as_req"] > 0 and area / r["as_req"] * 1000.0 >= r.get("s_max", 1e9) + 10 else "휨")})
    return out


# ── 1방향 슬래브 ──────────────────────────────────────────────
def calc_one_way(inp):
    """inp: name, span(m, 순경간), t, cc, fck, fy13, fy16, wd, wl, bar,
            support('SS'|'DC'|'DCI'|'CC'|'CANT'), spans(2|3), kcr(280|210)"""
    fck, fy13, fy16, fy, t, cc, bar, db = _common(inp)
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

    rows = []
    for key, loc, n, note in mom:
        r = _row("Main", f"{loc} {key}", w2 / n, f"Wu·L²/{n:g}" + (f" ({note})" if note else ""),
                 d, fck, fy, fy13, fy16, s_main)
        r["s_max"] = s_main
        rows.append(r)

    def min_bar(s_max, label):
        as_by_fy = {f: rho_min(f) * 1000.0 * t for f in {fy13, fy16}}
        return {"dir": "", "loc": label, "mu": None, "rho": rho_min(fy), "as_req": rho_min(fy) * 1000.0 * t,
                "sp": spacings(as_by_fy, fy13, fy16, s_max), "s_max": s_max, "ok": True, "d": d}
    min_row = min_bar(s_main, "Min Bar")             # 경간방향 최소철근 (주철근 간격 제한 적용)
    temp_row = min_bar(s_temp, "Temp. Bar")          # 직각방향 수축·온도철근(배력근)

    # 최소 두께 (KDS 14 20 30 표 4.2-1)
    n_h = ONE_WAY_SUPPORTS[sup][1]
    k_fy = 1.0 if abs(fy - 400.0) < 1e-6 else 0.43 + fy / 700.0
    h_req = L * 1000.0 / n_h * k_fy

    pvc = phi_vc(d, fck)
    warn = []
    if sup not in ("SS", "CANT"):
        if inp["wl"] > 3.0 * inp["wd"]:
            warn.append("활하중이 고정하중의 3배를 초과 — 근사해법(모멘트 계수) 적용 조건을 벗어납니다.")
        warn.append("근사해법 조건: 2경간 이상, 인접 경간 차이 20% 이하, 등분포하중, 일정 단면 (KDS 14 20 10 4.3.1)")
    for r in rows:
        if not r["ok"]:
            warn.append(f"{r['loc']}: {r['msg']}")
    summary = _summary(rows, min_row, bar, fck, fy)
    ti = COL_LABELS.index(bar) if bar in COL_LABELS else None
    temp_s = temp_row["sp"][ti] if ti is not None else _floor10(min(REBAR[bar][1] / temp_row["as_req"] * 1000.0, s_temp))

    return {
        "type": "1way", "name": inp.get("name", ""), "inp": dict(inp),
        "L": L, "t": t, "cc": cc, "fck": fck, "fy13": fy13, "fy16": fy16, "fy": fy, "bar": bar, "db": db, "d": d,
        "support": sup, "support_txt": ONE_WAY_SUPPORTS[sup][0], "two_span": two_span,
        "wd": inp["wd"], "wl": inp["wl"], "wu": wu, "wu_txt": wu_txt,
        "h_req": h_req, "h_n": n_h, "h_kfy": k_fy, "h_ok": t + 1e-9 >= h_req,
        "rows": rows, "min_row": min_row, "temp_row": temp_row, "temp_s": temp_s,
        "kcr": kcr, "fs": fs, "s_crack": s_crack, "s_code": s_code, "s_main": s_main, "s_temp": s_temp,
        "shear": [{"label": "", "vu": vu, "txt": v_txt, "phi_vc": pvc, "d": d, "ok": vu <= pvc + 1e-9}],
        "summary": summary, "warn": warn, "diagram": diagram,
        "ok": (t + 1e-9 >= h_req) and all(s["ok"] for s in summary) and vu <= pvc + 1e-9,
    }


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

    rows = []

    def add(direction, d, n_cont, c_neg, c_dl, c_ll, span, sym):
        pos = (c_dl * wdu + c_ll * wlu) * span * span
        if n_cont > 0:
            rows.append(_row(direction, "연속단 Cont", c_neg * wu * span * span,
                             f"{c_neg:.4f}·Wu·{sym}²", d, fck, fy, fy13, fy16, s_flex))
        if n_cont < 2:
            rows.append(_row(direction, "불연속단 DisC", pos / 3.0, "M(Pos)/3", d, fck, fy, fy13, fy16, s_flex))
        rows.append(_row(direction, "중앙부 Pos", pos,
                         f"({c_dl:.4f}·Wdu+{c_ll:.4f}·Wlu)·{sym}²", d, fck, fy, fy13, fy16, s_flex))

    n_long_cont = int(edges[2]) + int(edges[3])      # 단변방향 경간의 양 끝 = 장변(좌·우)
    n_short_cont = int(edges[0]) + int(edges[1])     # 장변방향 경간의 양 끝 = 단변(상·하)
    add("Short", d_s, n_long_cont, c["ca_neg"], c["ca_dl"], c["ca_ll"], lx, "Lx")
    add("Long", d_l, n_short_cont, c["cb_neg"], c["cb_dl"], c["cb_ll"], ly, "Ly")
    for r in rows:
        r["s_max"] = s_flex

    as_by_fy = {f: rho_min(f) * 1000.0 * t for f in {fy13, fy16}}
    min_row = {"dir": "", "loc": "Min Bar", "mu": None, "rho": rho_min(fy), "as_req": rho_min(fy) * 1000.0 * t,
               "sp": spacings(as_by_fy, fy13, fy16, s_min), "s_max": s_min, "ok": True, "d": d_s}

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
         "phi_vc": phi_vc(d_s, fck), "d": d_s},
        {"label": "Long Direction Shear", "sym": "Vuy", "vu": vuy, "txt": f"{c['wb']:.3f}·Wu·Ly/2",
         "phi_vc": phi_vc(d_l, fck), "d": d_l},
    ]
    for s in shear:
        s["ok"] = s["vu"] <= s["phi_vc"] + 1e-9

    warn = [f"{r['dir']} {r['loc']}: {r['msg']}" for r in rows if not r["ok"]]
    if inc:
        warn.append("불연속단 테두리보 강성비 αf < 0.8 — 최소 두께 10% 증대 적용 (KDS 14 20 30 4.2.2(3)③)")
    summary = _summary(rows, min_row, bar, fck, fy)
    h_ok = t + 1e-9 >= h_req

    return {
        "type": "2way", "name": inp.get("name", ""), "inp": dict(inp),
        "lx": lx, "ly": ly, "m": m, "case": case, "edges": edges, "beams": beams, "coef": c,
        "t": t, "cc": cc, "fck": fck, "fy13": fy13, "fy16": fy16, "fy": fy, "bar": bar, "db": db,
        "d_s": d_s, "d_l": d_l,
        "wd": inp["wd"], "wl": inp["wl"], "wu": wu, "wdu": wdu, "wlu": wlu, "wu_txt": wu_txt,
        "lnx": lnx, "lny": lny, "beta": beta, "alphas": alphas, "afm": afm,
        "h_req": h_req, "h_txt": h_txt, "h_inc": inc, "h_ok": h_ok,
        "rows": rows, "min_row": min_row, "s_flex": s_flex, "s_min": s_min,
        "shear": shear, "summary": summary, "warn": warn,
        "ok": h_ok and all(s["ok"] for s in summary) and all(s["ok"] for s in shear),
    }


def calculate(inp):
    """inp['type'] : '1way' | '2way'"""
    return calc_one_way(inp) if inp.get("type") == "1way" else calc_two_way(inp)
