"""
basic_design/rc/beam_calc.py
RC Beam Lite — 직사각형 보 단면 검토 (Tk 비의존 계산 + 계산서 + 단면 그림)

  · 보 하나에 단면 1 ~ 3개:  1 = 전단면,  2 = 단부 · 중앙부,  3 = 연속단부 · 중앙부 · 불연속단부
  · 단면마다 상·하부근(1단·2단), 측면철근, 스터럽, 단면력(Mu(-), Mu(+), Vu, Tu)
  · 휨      변형률 적합 단면 해석 (상·하부근 모두 고려, 압축철근 위치의 콘크리트 공제), φ = εt 에 따라
  · 최소 휨강도  φMn ≥ 1.2Mcr  또는  φMn ≥ 4/3·Mu      (KDS 14 20 20 4.2.2)
  · 균열     인장연단 철근 중심간격 ≤ min(375κcr/fs − 2.5cc, 300κcr/fs)   (KDS 14 20 20 4.2.3)
  · 전단     φVc = φ(0.16λ√fck + 17.6ρw·Vu·d/Mu)·bw·d ≤ φ·0.29√fck·bw·d   (KDS 14 20 22 식 4.2-3)
              최소 전단철근, 간격 d/2·600 (Vs > √fck·bw·d/3 이면 절반), Vs ≤ 2√fck·bw·d/3
  · 비틀림   Tu > φ(√fck/12)·Acp²/pcp 일 때 At/s, Al, 단면 치수 검토   (KDS 14 20 22 4.4 · 4.5)

단위: 길이 mm, 힘 kN, 모멘트 kN·m, 강도 MPa
"""
import math

from ..report import Report, fonts
from .. import theme as T
from . import slab_calc as S

BARS = {                     # 호칭 : (공칭지름 mm, 공칭단면적 mm²)
    "D10": (9.53, 71.33), "D13": (12.7, 126.7), "D16": (15.9, 198.6), "D19": (19.1, 286.5),
    "D22": (22.2, 387.1), "D25": (25.4, 506.7), "D29": (28.6, 642.4), "D32": (31.8, 794.2),
}
BAR_LIST = list(BARS)
STIRRUP_LIST = ["D10", "D13", "D16"]
ES = 200000.0
SEC_LABELS = {1: ["전단면"], 2: ["단부", "중앙부"], 3: ["연속단부", "중앙부", "불연속단부"]}
DESIGN_CODE = "KDS 14 20 : 2022  (KDS 41 20 00)"


class BeamInputError(ValueError):
    pass


# ── 단면 해석 ────────────────────────────────────────────────
def layers_of(sec, b, h, cc):
    """철근 층 목록 [(위치 'top1'|'top2'|'bot1'|'bot2', 상단에서 깊이 mm, 단면적 mm², 개수, 지름)]"""
    ds = BARS[sec["vb"]][0]
    out = []
    for side, n1, n2, b1, b2 in (("top", sec["tn1"], sec["tn2"], sec["tb"], sec.get("tb2", sec["tb"])),
                                 ("bot", sec["bn1"], sec["bn2"], sec["bb"], sec.get("bb2", sec["bb"]))):
        d1, a1 = BARS[b1]
        d2, a2 = BARS[b2]
        y1 = cc + ds + d1 / 2.0
        y2 = y1 + d1 / 2.0 + max(25.0, d1, d2) + d2 / 2.0      # 2단: 순간격 max(25, db)
        for tag, n, y, db, ab in ((side + "1", n1, y1, d1, a1), (side + "2", n2, y2, d2, a2)):
            if n > 0:
                out.append((tag, y if side == "top" else h - y, n * ab, n, db))
    return out


def analyze(layers, b, h, fck, fy, positive, pf):
    """휨 단면 해석.  positive: 정모멘트(상부 압축).  layers 의 깊이는 상단 기준.
    반환 dict(c, a, cb, eps_t, phi, mn, phi_mn, d, dt, as_t, cc_force, forces[(tag, F kN)])"""
    eta, beta1, ecu = S.stress_block(fck)
    fc = 0.85 * eta * fck
    lay = [(tag, (y if positive else h - y), a) for tag, y, a, _, _ in layers]
    tens = [(y, a) for tag, y, a in lay if y > h / 2.0]
    if not tens:
        return None
    as_t = sum(a for _, a in tens)
    d = sum(y * a for y, a in tens) / as_t               # 인장철근 도심
    dt = max(y for y, _ in tens)                         # 최외단 인장철근

    def forces(c):
        a = min(beta1 * c, h)
        cf = fc * a * b
        out = []
        for tag, y, ar in lay:
            eps = ecu * (c - y) / c
            fs = max(-fy, min(fy, ES * eps))
            if fs > 0 and y < a:
                fs -= fc                                 # 철근 자리의 콘크리트 공제
            out.append((tag, y, ar * fs))
        return cf, a, out

    lo, hi = 1e-3, h * 1.5
    for _ in range(80):
        c = (lo + hi) / 2.0
        cf, a, fl = forces(c)
        if cf + sum(f for _, _, f in fl) > 0:
            hi = c
        else:
            lo = c
    c = (lo + hi) / 2.0
    cf, a, fl = forces(c)
    # 압축연단 기준 모멘트: Mn = ΣT·y − Cc·a/2 − ΣCs·y  (힘의 평형이므로 기준점과 무관)
    mn = sum(-f * y for _, y, f in fl if f < 0) - cf * a / 2.0 - sum(f * y for _, y, f in fl if f > 0)
    eps_t = ecu * (dt - c) / c
    phi = S.phi_of(eps_t, fy, pf)
    ey = fy / ES
    cb = ecu / (ecu + ey) * dt
    ts = sum(f for _, _, f in fl if f < 0)
    cs = sum(f for _, _, f in fl if f > 0)
    return {"c": c, "a": a, "cb": cb, "eps_t": eps_t, "phi": phi, "mn": mn / 1e6, "phi_mn": phi * mn / 1e6,
            "d": d, "dt": dt, "as_t": as_t, "cc": cf / 1000.0, "ts": ts / 1000.0, "cs": cs / 1000.0,
            "eps_min": S.strain_limits(fy)[2], "eps_lim": S.strain_limits(fy)[1]}


def bar_spacing(n, db, b, cc, ds):
    """1단 철근 중심간격 · 순간격"""
    if n < 2:
        return None, None
    s = (b - 2.0 * (cc + ds) - db) / (n - 1)
    return s, s - db


# ── 단면 하나 검토 ───────────────────────────────────────────
def check_section(sec, label, com):
    b, h, cc, fck, fy, fys = com["b"], com["h"], com["cc"], com["fck"], com["fy"], com["fys"]
    pf, pv, kcr = com["phi_f"], com["phi_v"], com["kcr"]
    ds, av1 = BARS[sec["vb"]]
    lay = layers_of(sec, b, h, cc)
    sqf = math.sqrt(fck)
    ig = b * h ** 3 / 12.0
    fr = 0.63 * sqf
    mcr = fr * ig / (h / 2.0) / 1e6
    res = {"label": label, "sec": sec, "layers": lay, "mcr": mcr, "fr": fr, "flex": [], "warn": [], "ok": True}
    as_top = sum(a for t, _, a, _, _ in lay if t.startswith("top"))
    as_bot = sum(a for t, _, a, _, _ in lay if t.startswith("bot"))
    res.update(as_top=as_top, as_bot=as_bot, rho_st=(as_top + as_bot) / (b * h))

    # 철근 배치 (순간격)
    for side, n, bar in (("상부", sec["tn1"], sec["tb"]), ("하부", sec["bn1"], sec["bb"]),
                         ("상부 2단", sec["tn2"], sec.get("tb2", sec["tb"])), ("하부 2단", sec["bn2"], sec.get("bb2", sec["bb"]))):
        db = BARS[bar][0]
        _, clear = bar_spacing(n, db, b, cc, ds)
        if clear is not None and clear < max(25.0, db) - 1e-6:
            res["warn"].append(f"{side} {n:g}-{bar}: 순간격 {clear:.0f} mm < max(25, db) = {max(25.0, db):.0f} mm — 한 단에 들어가지 않습니다.")
            res["ok"] = False

    # 휨 (Mu(-): 상부 인장, Mu(+): 하부 인장)
    for positive, mu in ((False, sec["mn"]), (True, sec["mp"])):
        if mu <= 0:
            continue
        side = "하부" if positive else "상부"
        n1 = sec["bn1"] if positive else sec["tn1"]
        bar = sec["bb"] if positive else sec["tb"]
        an = analyze(lay, b, h, fck, fy, positive, pf)
        if an is None:
            res["flex"].append({"positive": positive, "mu": mu, "none": True, "side": side, "ok": False})
            res["warn"].append(f"{'Mu(+)' if positive else 'Mu(-)'} = {mu:g} kN·m 인데 {side} 인장철근이 없습니다.")
            res["ok"] = False
            continue
        ok_eps = an["eps_t"] >= an["eps_min"] - 1e-9
        ok_str = an["phi_mn"] + 1e-9 >= mu
        min_ok = an["phi_mn"] >= 1.2 * mcr - 1e-9 or an["phi_mn"] >= 4.0 / 3.0 * mu - 1e-9
        # 균열
        db = BARS[bar][0]
        s, _ = bar_spacing(n1, db, b, cc, ds)
        fs = 2.0 / 3.0 * fy
        cc_c = cc + ds
        smax = min(375.0 * kcr / fs - 2.5 * cc_c, 300.0 * kcr / fs)
        crack_ok = s is None or s <= smax + 1e-9
        f = dict(an, positive=positive, mu=mu, side=side, ok_eps=ok_eps, ok_str=ok_str, min_ok=min_ok, ratio=mu / an["phi_mn"],
                 s=s, smax=smax, fs=fs, cc_c=cc_c, crack_ok=crack_ok, none=False)
        f["ok"] = ok_eps and ok_str and min_ok and crack_ok
        res["flex"].append(f)
        res["ok"] &= f["ok"]
    # 표시용: 상·하부 1단 철근 중심간격 · 균열 최대간격
    fs = 2.0 / 3.0 * fy
    smax_c = min(375.0 * kcr / fs - 2.5 * (cc + ds), 300.0 * kcr / fs)
    res["spacing"] = {"top": bar_spacing(sec["tn1"], BARS[sec["tb"]][0], b, cc, ds)[0],
                      "bot": bar_spacing(sec["bn1"], BARS[sec["bb"]][0], b, cc, ds)[0], "smax": smax_c}

    # 전단 · 비틀림
    vu, tu = sec["vu"], sec["tu"]
    mu_s = max(sec["mn"], sec["mp"])
    gov = max((f for f in res["flex"] if not f["none"]), key=lambda f: f["mu"], default=None)
    if gov is None:
        an = analyze(lay, b, h, fck, fy, True, pf) or analyze(lay, b, h, fck, fy, False, pf)
        d, as_t = (an["d"], an["as_t"]) if an else (h - cc - ds - 10.0, 0.0)
    else:
        d, as_t = gov["d"], gov["as_t"]
    rho_w = as_t / (b * d)
    vdm = 1.0 if mu_s <= 0 else min(vu * d / 1000.0 / mu_s, 1.0)
    vc = (0.16 * sqf + 17.6 * rho_w * vdm) * b * d / 1000.0
    vc_max = 0.29 * sqf * b * d / 1000.0
    vc = min(vc, vc_max)
    pvc = pv * vc
    sh = {"vu": vu, "d": d, "rho_w": rho_w, "vdm": vdm, "vc": vc, "vc_max": vc_max, "phi_vc": pvc, "mu": mu_s}
    vs_req = max(vu / pv - vc, 0.0)
    vs_lim1 = sqf * b * d / 3.0 / 1000.0
    vs_lim2 = 2.0 * sqf * b * d / 3.0 / 1000.0
    s_max = min(d / 2.0, 600.0) if vs_req <= vs_lim1 else min(d / 4.0, 300.0)
    sh.update(vs_req=vs_req, vs_lim1=vs_lim1, vs_lim2=vs_lim2, s_max=s_max)

    # 비틀림
    tor = None
    acp, pcp = b * h, 2.0 * (b + h)
    tth = pv * sqf / 12.0 * acp ** 2 / pcp / 1e6
    x1, y1 = b - 2.0 * (cc + ds / 2.0), h - 2.0 * (cc + ds / 2.0)
    aoh, ph = x1 * y1, 2.0 * (x1 + y1)
    at_s = 0.0
    if tu > 0:
        tor = {"tu": tu, "tth": tth, "acp": acp, "pcp": pcp, "aoh": aoh, "ph": ph, "need": tu > tth + 1e-9}
        if tor["need"]:
            ao = 0.85 * aoh
            at_s = tu * 1e6 / (pv * 2.0 * ao * fys)                      # cotθ = 1 (θ = 45°)
            al = at_s * ph * fys / fy
            al_min = max(0.42 * sqf * acp / fy - max(at_s, 0.175 * b / fys) * ph * fys / fy, 0.0)
            lhs = math.sqrt((vu * 1000.0 / (b * d)) ** 2 + (tu * 1e6 * ph / (1.7 * aoh ** 2)) ** 2)
            rhs = pv * (vc * 1000.0 / (b * d) + 2.0 * sqf / 3.0)
            n_side = sec["sn"]
            al_side = 2 * n_side * BARS[sec["sb"]][1]
            tor.update(ao=ao, at_s=at_s, al=al, al_min=al_min, al_req=max(al, al_min), lhs=lhs, rhs=rhs,
                       sec_ok=lhs <= rhs + 1e-9, al_side=al_side, s_max=min(ph / 8.0, 300.0))
            s_max = min(s_max, tor["s_max"])
            sh["s_max"] = s_max
            if not tor["sec_ok"]:
                res["warn"].append("비틀림·전단 조합 응력이 단면 한계를 넘습니다 — 단면 증가 필요 (KDS 14 20 22 식 4.5-3).")
                res["ok"] = False
            if al_side + 1e-9 < tor["al_req"]:
                res["warn"].append(f"비틀림 종방향철근 Al = {tor['al_req']:.0f} mm² 필요 — 측면철근 {al_side:.0f} mm² "
                                   "외 부족분은 주철근 여유분 또는 추가 철근으로 둘레에 배치하세요.")
    sh["tor"] = tor

    # 스터럽
    legs = max(int(sec["vl"]), 0)
    av = legs * av1
    need_av = vu > pvc / 2.0 + 1e-9 or (tor is not None and tor["need"])
    req = vs_req * 1000.0 / (fys * d) + 2.0 * at_s                   # (Av + 2At)/s 소요 [mm²/mm]
    req_min = max(0.0625 * sqf, 0.35) * b / fys if need_av else 0.0
    req_all = max(req, req_min)
    sh.update(legs=legs, av=av, av1=av1, need_av=need_av, req=req, req_min=req_min, req_all=req_all)
    if vs_req > vs_lim2 + 1e-9:
        sh["s_req"] = None
        sh["ok"] = False
        res["warn"].append(f"Vs = {vs_req:.1f} kN > 2√fck·bw·d/3 = {vs_lim2:.1f} kN — 단면 증가 필요.")
    elif not need_av:
        sh["s_req"] = S._floor10(s_max)
        sh["ok"] = True
    elif av <= 0:
        sh["s_req"] = None
        sh["ok"] = False
        res["warn"].append("전단철근이 필요한데 스터럽 다리 수가 0 입니다.")
    else:
        s_calc = av / req_all
        s_req = S._floor10(min(s_calc, s_max))
        sh["s_calc"] = s_calc
        sh["s_req"] = s_req if s_req >= 50 else None
        sh["ok"] = sh["s_req"] is not None
        if sh["s_req"] is None:
            res["warn"].append(f"소요 스터럽 간격 {s_calc:.0f} mm < 50 mm — 다리 수·직경 증가 또는 단면 증가 필요.")
    s_in = sec["vs"]
    if s_in > 0 and sh["ok"]:
        sh["s_use"] = s_in
        sh["s_ok"] = s_in <= sh["s_req"] + 1e-9
        if not sh["s_ok"]:
            res["warn"].append(f"입력 스터럽 간격 @{s_in:g} > 소요 간격 @{sh['s_req']} — N.G.")
    else:
        sh["s_use"] = sh.get("s_req")
        sh["s_ok"] = sh["ok"]
    if sh["s_use"]:
        vs_prov = av * fys * d / sh["s_use"] / 1000.0
        sh["phi_vn"] = pv * (vc + vs_prov)
        sh["vs_prov"] = vs_prov
    else:
        sh["phi_vn"], sh["vs_prov"] = pvc, 0.0
    res["shear"] = sh
    res["ok"] &= sh["ok"] and sh["s_ok"]
    res["ratio_m"] = max((f["ratio"] for f in res["flex"] if not f["none"]), default=0.0)
    res["ratio_v"] = vu / sh["phi_vn"] if sh["phi_vn"] > 0 else 0.0
    return res


def calc_beam(inp):
    """inp: name, b, h, cc, fck, fy, fys, phi_f, phi_v, kcr, sections [ {tn1, tn2, tb, bn1, bn2, bb, sn, sb, vl, vb, vs,
            mn, mp, vu, tu} × 1~3 ]"""
    b, h, cc = inp["b"], inp["h"], inp["cc"]
    for k, lbl in (("b", "B"), ("h", "H"), ("fck", "fck"), ("fy", "fy"), ("fys", "fys")):
        if inp[k] <= 0:
            raise BeamInputError(f"{lbl} 값은 0보다 커야 합니다.")
    if cc < 0:
        raise BeamInputError("피복두께 Cc 는 0 이상이어야 합니다.")
    for k, lbl in (("phi_f", "휨 강도감소계수 φf"), ("phi_v", "전단 강도감소계수 φv")):
        if not 0 < inp[k] <= 1.0:
            raise BeamInputError(f"{lbl} 는 0 초과 1.0 이하로 입력하세요.")
    secs = inp["sections"]
    if not 1 <= len(secs) <= 3:
        raise BeamInputError("단면은 1 ~ 3개입니다.")
    labels = inp.get("labels") or SEC_LABELS[len(secs)]
    out = []
    for lbl, sec in zip(labels, secs):
        for k in ("tn1", "tn2", "bn1", "bn2", "sn", "vl"):
            if sec[k] < 0 or int(sec[k]) != sec[k]:
                raise BeamInputError(f"[{lbl}] 철근 개수는 0 이상의 정수로 입력하세요.")
        if sec["tn1"] + sec["bn1"] == 0:
            raise BeamInputError(f"[{lbl}] 주철근(1단)을 입력하세요.")
        if (sec["tn2"] and not sec["tn1"]) or (sec["bn2"] and not sec["bn1"]):
            raise BeamInputError(f"[{lbl}] 2단 철근은 1단 철근이 있을 때만 입력할 수 있습니다.")
        for k in ("mn", "mp", "vu", "tu", "vs"):
            if sec[k] < 0:
                raise BeamInputError(f"[{lbl}] 단면력·간격은 0 이상으로 입력하세요 (Mu(-), Mu(+) 는 크기).")
        for k in ("tb", "bb", "tb2", "bb2", "sb", "vb"):
            if sec.get(k, "D10") not in BARS:
                raise BeamInputError(f"[{lbl}] 철근 '{sec.get(k)}' 을(를) 알 수 없습니다.")
        need = cc + BARS[sec["vb"]][0] + BARS[sec["tb"]][0] + BARS[sec["bb"]][0] + cc
        if h <= need + 20 or b <= 2 * (cc + BARS[sec["vb"]][0]) + 20:
            raise BeamInputError(f"[{lbl}] 단면에 비해 피복·철근이 너무 큽니다.")
        out.append(check_section(sec, lbl, inp))
    eta, beta1, ecu = S.stress_block(inp["fck"])
    return {"name": inp.get("name", ""), "inp": dict(inp), "b": b, "h": h, "cc": cc, "fck": inp["fck"], "fy": inp["fy"],
            "fys": inp["fys"], "beta1": beta1, "phi_f": inp["phi_f"], "phi_v": inp["phi_v"], "kcr": inp["kcr"],
            "sections": out, "ok": all(s["ok"] for s in out)}


# ── 계산서 ───────────────────────────────────────────────────
def _okng(ok):
    return "O.K." if ok else "N.G."


def _rebar_text(sec, upper):
    if upper:
        n1, n2, b1, b2 = sec["tn1"], sec["tn2"], sec["tb"], sec.get("tb2", sec["tb"])
    else:
        n1, n2, b1, b2 = sec["bn1"], sec["bn2"], sec["bb"], sec.get("bb2", sec["bb"])
    if n1 == 0:
        return "-"
    if not n2:
        return f"{n1:g} - {b1}"
    return f"{n1:g}/{n2:g} - {b1}" if b1 == b2 else f"{n1:g}-{b1} + {n2:g}-{b2}"


def build_report(r):
    rep = Report(f"RC Beam — {r['name']}")
    rep.h("Design Conditions")
    rep.t(f"Design Code  :  {DESIGN_CODE}", 1)
    rep.t("Material Data", 0, "sub")
    rep.t(f"fck = {r['fck']:g} N/mm²  (β1 = {r['beta1']:.3f})", 2)
    rep.t(f"fy = {r['fy']:g},   fys = {r['fys']:g} N/mm²", 2)
    rep.t("Section Data", 0, "sub")
    rep.t(f"B = {r['b']:g} mm    H = {r['h']:g} mm    Cc = {r['cc']:g} mm", 2)
    rep.t(f"단면 {len(r['sections'])}개 :  " + " · ".join(s["label"] for s in r["sections"]), 2)
    rep.t(f"φf = {r['phi_f']:.2f} (휨, 인장지배)    φv = {r['phi_v']:.2f}", 2)

    # 요약
    rep.h("Design Summary")
    head = [["단면", "상부근", "하부근", "스터럽", "Mu/φMn", "Vu/φVn", "Check"]]
    body = []
    for s in r["sections"]:
        sec, sh = s["sec"], s["shear"]
        st = f"{sh['legs']}-{sec['vb']} @{sh['s_use']:g}" if sh.get("s_use") else "-"
        body.append([(s["label"], "b"), _rebar_text(sec, True), _rebar_text(sec, False), st,
                     (f"{s['ratio_m']:.3f}", "n" if s["ratio_m"] <= 1 else "ng"),
                     (f"{s['ratio_v']:.3f}", "n" if s["ratio_v"] <= 1 else "ng"), ("O.K.", "ok") if s["ok"] else ("N.G.", "ng")])
    rep.table(head, body, [110, 120, 120, 160, 100, 100, 80], ["c", "c", "c", "c", "r", "r", "c"])

    for n, s in enumerate(r["sections"], 1):
        _section_report(rep, r, s, n)

    rep.h("Notes")
    for n in (
        "단면 해석: 변형률 적합(εcu, 등가직사각형 응력블록), 상·하부근 모두 고려.  측면철근은 휨 계산에서 제외(비틀림 Al 에만 반영)",
        "2단 철근은 1단과 순간격 max(25 mm, db) 로 배치.  스터럽 바깥면까지 순피복 Cc",
        "전단: KDS 14 20 22 식 (4.2-3),  ρw = 인장철근비(큰 휨모멘트 쪽),  Vu·d/Mu ≤ 1.0,  Mu = 0 이면 1.0",
        "스터럽: 간격 입력 0 = 소요 간격 자동(10 mm 단위 내림),  입력값이 있으면 그 간격으로 검토",
        "비틀림: θ = 45°,  Ao = 0.85·Aoh,  횡방향 소요량은 (Av + 2At)/s 로 전단과 합산",
    ):
        rep.t("· " + n, 1, "dim")
    return rep


def _section_report(rep, r, s, n):
    sec, sh = s["sec"], s["shear"]
    tag = f"[{n}. {s['label']}]"
    rep.h(f"{tag}  Rebar & Force")
    rep.t(f"Upper : {_rebar_text(sec, True)}      Lower : {_rebar_text(sec, False)}      "
          f"Side : {sec['sn']:g} - {sec['sb']} (한쪽)" if sec["sn"] else
          f"Upper : {_rebar_text(sec, True)}      Lower : {_rebar_text(sec, False)}", 1)
    rep.t(f"Total Rebar Area = {s['as_top'] + s['as_bot']:.0f} mm²  (ρst = {s['rho_st']:.4f})      "
          f"Stirrup : {sec['vl']:g} - {sec['vb']}" + (f" @{sec['vs']:g}" if sec["vs"] else " (간격 자동)"), 1)
    rep.t(f"Mu(-) = {sec['mn']:.1f} kN·m    Mu(+) = {sec['mp']:.1f} kN·m    Vu = {sec['vu']:.1f} kN    Tu = {sec['tu']:.1f} kN·m", 1)
    for w in s["warn"]:
        rep.t("※ " + w, 1, "warn")

    for f in s["flex"]:
        sym = "Mu(+) (하부 인장)" if f["positive"] else "Mu(-) (상부 인장)"
        if f["none"]:
            rep.h(f"{tag}  Check Bending — {sym}")
            rep.t(f"{f['side']} 인장철근이 없습니다  --->  N.G.", 1, "ng")
            continue
        rep.h(f"{tag}  Check Crack Width — {sym}")
        if f["s"] is None:
            rep.t("인장측 1단 철근이 1개 — 간격 검토 생략", 1, "dim")
        else:
            rep.t(f"smax = min[375(κcr/fs) − 2.5cc, 300(κcr/fs)] = {f['smax']:.0f}   {'>' if f['crack_ok'] else '<'}   "
                  f"s = {f['s']:.0f} mm   --->  {_okng(f['crack_ok'])}", 1, "ok" if f["crack_ok"] else "ng")
            rep.t(f"fs = 2/3·fy = {f['fs']:.0f} MPa,  κcr = {r['kcr']:g},  cc = {f['cc_c']:.1f} mm (인장철근 표면까지)", 2, "dim")
        rep.h(f"{tag}  Check Bending Moment Capacity — {sym}")
        rep.t(f"Strength Reduction Factor   φ = {f['phi']:.3f}" + ("  (변화구간)" if f["phi"] < r["phi_f"] - 1e-6 else ""), 1)
        rep.t(f"Effective Depth    d = {f['d']:.1f} mm      dt = {f['dt']:.1f} mm", 1)
        rep.t(f"Balanced Axis Depth     cb = {f['cb']:.0f} mm", 1)
        rep.t(f"Neutral Axis Depth       c = {f['c']:.0f} mm", 1)
        rep.t(f"Max. Tensile Strain    εt = {f['eps_t']:.4f}   {'>' if f['ok_eps'] else '<'}   εt,min = {f['eps_min']:.4f}"
              f"   --->  {_okng(f['ok_eps'])}", 1, "ok" if f["ok_eps"] else "ng")
        rep.t(f"Tension : Rebar                 Ts = {f['ts']:.1f} kN", 2)
        rep.t(f"Compression : Rebar         Cs = {f['cs']:.1f} kN", 2)
        rep.t(f"Compression : Concrete    Cc = {f['cc']:.1f} kN", 2)
        lim, lim_t = (1.2 * s["mcr"], f"1.2Mcr = {1.2 * s['mcr']:.1f}") if f["phi_mn"] >= 1.2 * s["mcr"] or not f["min_ok"] \
            else (4.0 / 3.0 * f["mu"], f"4/3·Mu = {4.0 / 3.0 * f['mu']:.1f}")
        rep.t(f"Design Moment Capacity   φMn = {f['phi_mn']:.1f} kN·m   {'>' if f['min_ok'] else '<'}   {lim_t}   --->  "
              f"{_okng(f['min_ok'])}", 1, "ok" if f["min_ok"] else "ng")
        rep.t(f"Mu/φMn = {f['ratio']:.3f}   {'<' if f['ok_str'] else '>'}   1.000   --->  {_okng(f['ok_str'])}",
              1, "ok" if f["ok_str"] else "ng")

    rep.h(f"{tag}  Calculate Shear Reinf.")
    rep.t(f"Strength Reduction Factor   φ = {r['phi_v']:.3f}", 1)
    rep.t(f"φVc = φ(0.16√fck + 17.6ρw·Vu·d/Mu)·bw·d = {sh['phi_vc']:.1f} kN"
          + ("   (≤ φ·0.29√fck·bw·d)" if abs(sh["vc"] - sh["vc_max"]) < 1e-6 else ""), 1)
    rep.t(f"d = {sh['d']:.1f} mm,  ρw = {sh['rho_w']:.4f},  Vu·d/Mu = {sh['vdm']:.3f}", 2, "dim")
    if not sh["need_av"]:
        rep.t(f"Vu = {sh['vu']:.1f}   ≤   φVc/2 = {sh['phi_vc'] / 2:.1f} kN   --->  전단보강 불필요 (최대간격 배치 권장)", 1, "ok")
    else:
        rep.t(f"Vs,req = Vu/φ − Vc = {sh['vs_req']:.1f} kN"
              + (f"   (> √fck·bw·d/3 = {sh['vs_lim1']:.1f} → 간격 절반)" if sh["vs_req"] > sh["vs_lim1"] else ""), 1)
        tor = sh["tor"]
        if tor and tor["need"]:
            rep.t(f"(Av + 2At)/s = Vs/(fys·d) + 2·At/s = {sh['req']:.3f} mm²/mm      최소 {sh['req_min']:.3f} mm²/mm", 1)
        else:
            rep.t(f"Av/s = max(Vs/(fys·d), Av,min/s) = max({sh['req']:.3f}, {sh['req_min']:.3f}) mm²/mm", 1)
        rep.t(f"smax = {S._floor10(sh['s_max'])} mm" + ("  (d/4, 300)" if sh["vs_req"] > sh["vs_lim1"] else "  (d/2, 600)")
              + ("  · 비틀림 ph/8, 300" if tor and tor["need"] else ""), 2, "dim")
    if sh.get("s_req"):
        rep.t(f"Required Stirrup Reinf. :  {sh['legs']} - {sec['vb']} @ {sh['s_req']} mm", 1, "ok" if sh["ok"] else "ng")
        if sec["vs"] > 0:
            rep.t(f"Used Stirrup :  {sh['legs']} - {sec['vb']} @ {sec['vs']:g} mm   --->  {_okng(sh['s_ok'])}", 1,
                  "ok" if sh["s_ok"] else "ng")
        rep.t(f"φVn = φ(Vc + Vs) = {r['phi_v']:.2f}·({sh['vc']:.1f} + {sh['vs_prov']:.1f}) = {sh['phi_vn']:.1f} kN   "
              f"{'>' if sh['phi_vn'] >= sh['vu'] else '<'}   Vu = {sh['vu']:.1f} kN", 1, "ok" if sh["phi_vn"] >= sh["vu"] else "ng")
    else:
        rep.t("Required Stirrup Reinf. :  배치 불가  --->  N.G.", 1, "ng")

    tor = sh["tor"]
    if tor:
        rep.h(f"{tag}  Check Torsion")
        rep.t(f"Tth = φ(√fck/12)·Acp²/pcp = {tor['tth']:.2f} kN·m      (Acp = {tor['acp']:,.0f} mm², pcp = {tor['pcp']:,.0f} mm)", 1)
        if not tor["need"]:
            rep.t(f"Tu = {tor['tu']:.2f}   ≤   Tth = {tor['tth']:.2f} kN·m   --->  비틀림 무시", 1, "ok")
        else:
            rep.t(f"Tu = {tor['tu']:.2f}   >   Tth   --->  비틀림 설계      (Aoh = {tor['aoh']:,.0f} mm², ph = {tor['ph']:,.0f} mm)", 1, "warn")
            rep.t(f"단면 검토 √[(Vu/bw·d)² + (Tu·ph/1.7Aoh²)²] = {tor['lhs']:.2f}   {'≤' if tor['sec_ok'] else '>'}   "
                  f"φ(Vc/bw·d + 2√fck/3) = {tor['rhs']:.2f} MPa   --->  {_okng(tor['sec_ok'])}", 1, "ok" if tor["sec_ok"] else "ng")
            rep.t(f"At/s = Tu/(φ·2·Ao·fys·cotθ) = {tor['at_s']:.3f} mm²/mm  (한 가닥)", 1)
            rep.t(f"Al = At/s·ph·(fys/fy) = {tor['al']:.0f} mm²,   Al,min = {tor['al_min']:.0f} mm²   →   Al = {tor['al_req']:.0f} mm²"
                  f"      (측면철근 {tor['al_side']:.0f} mm²)", 1, "ok" if tor["al_side"] >= tor["al_req"] else "warn")


# ── 단면 그림 ────────────────────────────────────────────────
def _draw_section(cv, F, s, r, cx, top, w_max, h_max, dims):
    b, h, cc = r["b"], r["h"], r["cc"]
    sec = s["sec"]
    sc = min(w_max / b, h_max / h)
    pw, ph = b * sc, h * sc
    x0, y0 = cx - pw / 2, top
    cv.create_rectangle(x0, y0, x0 + pw, y0 + ph, fill="#FFFBEA", outline=T.INK)
    ds = BARS[sec["vb"]][0]
    o = (cc + ds / 2) * sc
    cv.create_rectangle(x0 + o, y0 + o, x0 + pw - o, y0 + ph - o, outline="#dc2626", width=2)
    for tag, y, _, n, db in s["layers"]:
        rr = max(db * sc / 2, 2.2)
        xa = x0 + (cc + ds + db / 2) * sc
        xb = x0 + pw - (cc + ds + db / 2) * sc
        for k in range(int(n)):
            xx = xa if n == 1 else xa + (xb - xa) * k / (n - 1)
            yy = y0 + y * sc
            cv.create_oval(xx - rr, yy - rr, xx + rr, yy + rr, fill=T.INK, outline=T.INK)
    if sec["sn"] > 0:
        db = BARS[sec["sb"]][0]
        rr = max(db * sc / 2, 2.0)
        ytop = y0 + (cc + ds + BARS[sec["tb"]][0] / 2) * sc
        ybot = y0 + ph - (cc + ds + BARS[sec["bb"]][0] / 2) * sc
        n = int(sec["sn"])
        for k in range(n):
            yy = ytop + (ybot - ytop) * (k + 1) / (n + 1)
            for xx in (x0 + (cc + ds + db / 2) * sc, x0 + pw - (cc + ds + db / 2) * sc):
                cv.create_oval(xx - rr, yy - rr, xx + rr, yy + rr, fill="#2563eb", outline="#2563eb")
    cv.create_text(cx, top - 12, text=s["label"], font=F["b"], fill=T.NAVY)
    sh = s["shear"]
    lines = [f"상 {_rebar_text(sec, True)}", f"하 {_rebar_text(sec, False)}",
             f"St {sh['legs']}-{sec['vb']}" + (f"@{sh['s_use']:g}" if sh.get("s_use") else "")]
    for k, ln in enumerate(lines):
        cv.create_text(cx, y0 + ph + 12 + k * 13, text=ln, font=F["s"], fill=T.INK if s["ok"] else T.NG)
    if dims:
        cv.create_line(x0 - 12, y0, x0 - 12, y0 + ph, fill=T.INK)
        cv.create_text(x0 - 15, y0 + ph / 2, text=f"{h:g}", angle=90, anchor="s", font=F["s"], fill=T.INK)
    return pw


def sketch(r):
    def draw(cv, x, y, w, h):
        F = fonts(cv)
        secs = r["sections"]
        n = len(secs)
        cell = w / n
        w_max = min(cell - 28, 120)
        h_max = h - 92
        for k, s in enumerate(secs):
            _draw_section(cv, F, s, r, x + cell * (k + 0.5), y + 28, w_max, h_max, k == 0)
        cv.create_text(x + w / 2, y + h - 10, text=f"B × H = {r['b']:g} × {r['h']:g} mm", font=F["s"], fill=T.MUTED)
    return draw


def sketch_box(r):
    return (470, 18, 410, 260)
