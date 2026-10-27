"""간이 부재 검토 (현장조사 상세입력용).

단위: 길이 mm (부재길이 L 은 m), 힘 kN, 모멘트 kN·m, 응력 MPa.
- 부재력: 등분포하중 단순화 — 양단 지점조건(Pin / Fix / SemiFix)을 고정도 r(0 / 1 / 0.5)로 보고
  단부모멘트 M = wL²/12 · 3r₁(2−r₂)/(4−r₁r₂) (r=1,1 → wL²/12, r=1,0 → wL²/8)
- RC 보   : KDS 14 20 20 (εcu 0.0033, η·β1 표 4.1-2, φ 0.85~0.65), KDS 14 20 22 (Vc = 1/6·λ√fck·bw·d, φ 0.75)
- RC 기둥 : P-M 상관 (양면 대칭배근 가정), φPn,max = 0.80φ[0.85fck(Ag−Ast)+fyAst]
- 철골 보 : KDS 41 30 10 — φMn (소성/횡좌굴, Cb=1), φVn = 1.0×0.6FyAw (압연 H형강)
- 철골 기둥: φPn (휨좌굴), 축력+휨 상관식
검토 결과는 현장조사 판단을 돕는 참고값이며 설계 검토를 대신하지 않는다.
"""
from __future__ import annotations

import math

BAR_AREA = {6: 31.67, 10: 71.33, 13: 126.7, 16: 198.6, 19: 286.5, 22: 387.1, 25: 506.7, 29: 642.4, 32: 794.2,
            35: 956.6, 38: 1140.0, 41: 1340.0, 51: 2027.0}
FY_PREFIX = {"D": 400, "SD": 400, "HD": 400, "SHD": 500, "UHD": 600}
FIX = {"Pin": 0.0, "SemiFix": 0.5, "Fix": 1.0}
SUPPORT_KO = {"Pin": "핀", "SemiFix": "반고정", "Fix": "고정"}
ES = 200000.0
E_STEEL = 210000.0

# 압연 H형강 (H × B × tw × tf, r)  — KS D 3502 대표 규격
H_SECTIONS = {
    "H-150x150x7x10": (150, 150, 7, 10, 11), "H-194x150x6x9": (194, 150, 6, 9, 13),
    "H-200x100x5.5x8": (200, 100, 5.5, 8, 11), "H-200x200x8x12": (200, 200, 8, 12, 13),
    "H-244x175x7x11": (244, 175, 7, 11, 16), "H-250x125x6x9": (250, 125, 6, 9, 12),
    "H-250x250x9x14": (250, 250, 9, 14, 16), "H-294x200x8x12": (294, 200, 8, 12, 18),
    "H-300x150x6.5x9": (300, 150, 6.5, 9, 13), "H-300x300x10x15": (300, 300, 10, 15, 18),
    "H-340x250x9x14": (340, 250, 9, 14, 20), "H-350x175x7x11": (350, 175, 7, 11, 14),
    "H-350x350x12x19": (350, 350, 12, 19, 20), "H-390x300x10x16": (390, 300, 10, 16, 22),
    "H-400x200x8x13": (400, 200, 8, 13, 16), "H-400x400x13x21": (400, 400, 13, 21, 22),
    "H-440x300x11x18": (440, 300, 11, 18, 24), "H-450x200x9x14": (450, 200, 9, 14, 18),
    "H-488x300x11x18": (488, 300, 11, 18, 26), "H-500x200x10x16": (500, 200, 10, 16, 20),
    "H-582x300x12x17": (582, 300, 12, 17, 28), "H-588x300x12x20": (588, 300, 12, 20, 28),
    "H-600x200x11x17": (600, 200, 11, 17, 22), "H-700x300x13x24": (700, 300, 13, 24, 28),
    "H-800x300x14x26": (800, 300, 14, 26, 28), "H-900x300x16x28": (900, 300, 16, 28, 28),
}
STEEL_GRADES = {"SS275": 275.0, "SM275": 275.0, "SM355": 355.0, "SHN275": 275.0, "SHN355": 355.0,
                "SM420": 420.0, "SM460": 460.0}


# ============================================================================
def parse_bar(s):
    """'4-HD22' → (4, 'HD', 22, None);  'HD10@200' → (None, 'HD', 10, 200);  '' → None"""
    import re
    s = (s or "").replace(" ", "").upper()
    m = re.match(r"^(?:(\d+)-)?([A-Z]*)(\d+)(?:@(\d+))?$", s)
    if not m:
        return None
    n, pre, d, sp = m.groups()
    return (int(n) if n else None, pre or "D", int(d), int(sp) if sp else None)


def bar_area(d):
    return BAR_AREA.get(int(d), math.pi * d * d / 4)


def as_of(s):
    """주근 표기 → (As mm², 개수, 직경, fy)"""
    p = parse_bar(s)
    if not p or not p[0]:
        return 0.0, 0, 0, 400.0
    n, pre, d, _sp = p
    return n * bar_area(d), n, d, float(FY_PREFIX.get(pre, 400))


def stirrup_of(s, legs=2):
    """스터럽 표기 'HD10@150' → (Av mm², s mm, dia, fyt)"""
    p = parse_bar(s)
    if not p or not p[3]:
        return 0.0, 0.0, 0, 400.0
    n, pre, d, sp = p
    return legs * bar_area(d), float(sp), d, float(FY_PREFIX.get(pre, 400))


def stress_block(fck):
    tab = ((40, 0.0033, 1.00, 0.80), (50, 0.0032, 0.97, 0.80), (60, 0.0031, 0.95, 0.76),
           (70, 0.0030, 0.91, 0.74), (80, 0.0029, 0.87, 0.72), (90, 0.0028, 0.84, 0.70))
    if fck <= 40:
        return tab[0][1:]
    for (f0, e0, n0, b0), (f1, e1, n1, b1) in zip(tab, tab[1:]):
        if fck <= f1:
            t = (fck - f0) / (f1 - f0)
            return e0 + (e1 - e0) * t, n0 + (n1 - n0) * t, b0 + (b1 - b0) * t
    return tab[-1][1:]


def phi_flex(eps_t, fy):
    ey = fy / ES
    etl = 0.005 if fy <= 400 else 2.5 * ey
    if eps_t >= etl:
        return 0.85
    if eps_t <= ey:
        return 0.65
    return 0.65 + 0.20 * (eps_t - ey) / (etl - ey)


# ============================================================================
def beam_forces(w, L, sup_i="Fix", sup_j="Fix"):
    """등분포 w(kN/m), 경간 L(m) → dict(Mi, Mj (부모멘트, 크기), Mpos, Vi, Vj, x0)"""
    r1, r2 = FIX.get(sup_i, 1.0), FIX.get(sup_j, 1.0)
    fem = w * L * L / 12.0
    den = 4.0 - r1 * r2
    Mi = fem * 3 * r1 * (2 - r2) / den
    Mj = fem * 3 * r2 * (2 - r1) / den
    Vi = w * L / 2 + (Mi - Mj) / L
    Vj = w * L - Vi
    x0 = Vi / w if w > 0 else L / 2
    Mpos = Vi * x0 - w * x0 * x0 / 2 - Mi
    return {"Mi": Mi, "Mj": Mj, "Mpos": Mpos, "Vi": Vi, "Vj": Vj, "x0": x0}


def factored_w(D, Lv):
    return max(1.4 * D, 1.2 * D + 1.6 * Lv)


# ============================================================================
def rc_flexure(b, h, bars, fck, cover=40.0, stirrup_d=10):
    """직사각형 단면 휨강도 (인장철근 1단 또는 1·2단, 압축철근 무시).
    bars: '4-HD22' 또는 ['4-HD22', '2-HD22'] (1단 = 바깥쪽, 2단 = 안쪽).
    2단 위치: 1단 중심에서 db1/2 + 순간격 max(25, db1) + db2/2 안쪽 (KDS 14 20 50 철근 순간격).
    변형률 적합으로 중립축 c를 구함 → dict(As, d(도심), dt(최외단), a, c, eps_t, phi, Mn, phiMn, fy, layers)"""
    if isinstance(bars, str):
        bars = [bars]
    layers = []
    d1 = db1 = None
    for i, s in enumerate(bars[:2]):
        As_i, n_i, db_i, fy_i = as_of(s)
        if As_i <= 0:
            if i == 0:
                break               # 2단만 있는 입력은 무시
            continue
        if i == 0:
            d_i = h - cover - stirrup_d - db_i / 2
            d1, db1 = d_i, db_i
        else:
            d_i = d1 - (db1 / 2 + max(25.0, db1) + db_i / 2)
        layers.append({"As": As_i, "n": n_i, "db": db_i, "fy": fy_i, "d": d_i})
    if not layers:
        return {"As": 0.0, "phiMn": 0.0, "d": h - cover - stirrup_d - 11, "eps_t": 0, "phi": 0, "fy": 400.0,
                "n": 0, "layers": []}
    ecu, eta, b1 = stress_block(fck)
    k = eta * 0.85 * fck * b * b1

    def net(c):
        return k * c - sum(L["As"] * max(-L["fy"], min(L["fy"], ES * ecu * (L["d"] - c) / c)) for L in layers)
    lo, hi = 1e-3, h
    for _ in range(80):
        mid = (lo + hi) / 2
        if net(mid) > 0:
            hi = mid
        else:
            lo = mid
    c = (lo + hi) / 2
    a = b1 * c
    Mn = 0.0
    for L in layers:
        L["fs"] = max(-L["fy"], min(L["fy"], ES * ecu * (L["d"] - c) / c))
        Mn += L["As"] * L["fs"] * (L["d"] - a / 2)
    Mn /= 1e6
    dt = layers[0]["d"]
    eps_t = ecu * (dt - c) / c
    fy = layers[0]["fy"]
    phi = phi_flex(eps_t, fy)
    As = sum(L["As"] for L in layers)
    dc = sum(L["As"] * L["d"] for L in layers) / As
    return {"As": As, "d": dc, "dt": dt, "a": a, "c": c, "eps_t": eps_t, "phi": phi, "Mn": Mn, "phiMn": phi * Mn,
            "fy": fy, "n": sum(L["n"] for L in layers), "db": layers[0]["db"], "layers": layers}


def rc_shear(b, d, stirrup, fck, lam=1.0, Nu=0.0, Ag=None):
    """→ dict(Vc, Vs, phiVn, s, smax, Vs_max, note) (kN). Nu: 압축(+) kN (기둥)"""
    sq = min(math.sqrt(fck), 8.4)
    Vc = sq * lam * b * d / 6.0
    if Nu and Ag:
        Vc *= (1 + Nu * 1000 / (14 * Ag))
    Av, s, _dia, fyt = stirrup_of(stirrup)
    fyt = min(fyt, 500.0)
    Vs = Av * fyt * d / s if s > 0 else 0.0
    Vs_max = 2.0 / 3.0 * sq * b * d
    note = []
    if Vs > Vs_max:
        note.append("Vs 상한(2/3√fck·bw·d) 적용")
        Vs = Vs_max
    smax = min(d / 2, 600.0)
    if Vs > sq * b * d / 3.0:
        smax /= 2
    if s and s > smax + 1e-6:
        note.append(f"스터럽 간격 {s:.0f} > 최대 {smax:.0f}")
    return {"Vc": Vc / 1000, "Vs": Vs / 1000, "phiVn": 0.75 * (Vc + Vs) / 1000, "s": s, "smax": smax,
            "Av": Av, "note": note}


def rc_beam_check(b, h, L, w, sup_i, sup_j, rebar, fck=24.0, cover=40.0):
    """rebar: {'상부근|I단':'4-HD22', '하부근|중앙':..., '스터럽|J단':'HD10@150', ...}
    → (lines [(항목, 요구, 강도, 비, ok)], forces, summary)"""
    F = beam_forces(w, L, sup_i, sup_j)
    lines = []
    sd = 10
    for key in ("스터럽|I단", "스터럽|중앙", "스터럽|J단"):
        p = parse_bar(rebar.get(key, ""))
        if p:
            sd = p[2]
            break
    fr = 0.63 * math.sqrt(fck)
    Mcr = fr * b * h * h / 6 / 1e6

    def flex(label, Mu, bars):
        r = rc_flexure(b, h, bars, fck, cover, sd)
        ok = r["phiMn"] >= Mu - 1e-9
        extra = ""
        if len(r.get("layers", [])) > 1:
            label = label.replace("근)", " 1+2단)")
        if r["As"] > 0:
            extra = f"As={r['As']:.0f}mm², φ={r['phi']:.2f}, εt={r['eps_t']:.4f}"
            if len(r["layers"]) > 1:
                extra += f", d={r['d']:.0f}(2단 d={r['layers'][1]['d']:.0f})"
            emin = 0.004 if r["fy"] <= 400 else 2 * r["fy"] / ES
            if r["eps_t"] < emin:
                extra += f" (최소허용변형률 {emin:.4f} 미만)"
                ok = False
            if r["phiMn"] < 1.2 * Mcr and r["phiMn"] < 4 / 3 * Mu:
                extra += " · 최소철근 φMn<1.2Mcr"
        elif Mu > 0.5:
            extra = "철근 미입력"
        lines.append((label, Mu, r["phiMn"], Mu / r["phiMn"] if r["phiMn"] > 0 else float("inf"), ok, extra))
        return r

    two = lambda row, col: [rebar.get(f"{row}|{col}", ""), rebar.get(f"{row}2|{col}", "")]
    ri = flex("휨 I단 −M (상부근)", F["Mi"], two("상부근", "I단"))
    flex("휨 중앙 +M (하부근)", F["Mpos"], two("하부근", "중앙"))
    rj = flex("휨 J단 −M (상부근)", F["Mj"], two("상부근", "J단"))
    d_i = ri.get("d") or (h - cover - sd - 11)
    d_j = rj.get("d") or d_i
    for label, Vu, key, d in (("전단 I단", F["Vi"], "스터럽|I단", d_i), ("전단 J단", F["Vj"], "스터럽|J단", d_j)):
        st = rebar.get(key) or rebar.get("스터럽|중앙", "")
        r = rc_shear(b, d, st, fck)
        ok = r["phiVn"] >= Vu - 1e-9
        extra = f"φVc={0.75 * r['Vc']:.1f}, Vs={r['Vs']:.1f}"
        if not st:
            extra += " · 스터럽 미입력"
        if Vu > 0.5 * 0.75 * r["Vc"] and not st:
            extra += " · 최소전단철근 필요"
        if r["note"]:
            extra += " · " + ", ".join(r["note"])
            if any("간격" in n for n in r["note"]):
                ok = False
        lines.append((label, Vu, r["phiVn"], Vu / r["phiVn"] if r["phiVn"] > 0 else float("inf"), ok, extra))
    return lines, F


# ============================================================================
def col_layouts(n):
    """주근 n개를 둘레에 배치하는 (가로 nx, 세로 ny) 조합 — 2·nx + 2·ny − 4 = n, 모서리 공유."""
    out = []
    if n < 4 or n % 2:
        return out
    for nx in range(2, n // 2 + 1):
        ny = (n + 4) // 2 - nx
        if ny >= 2:
            out.append((nx, ny))
    return out


def parse_layout(s):
    import re
    m = re.match(r"^\s*(\d+)\s*[xX×*]\s*(\d+)\s*$", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def default_layout(n, b=1.0, h=1.0):
    opts = col_layouts(n)
    if not opts:
        return None
    return min(opts, key=lambda o: abs((o[0] - 1) / max(o[1] - 1, 1) - b / max(h, 1)))


def col_bar_positions(b, h, n, layout, edge):
    """둘레 배근 좌표 [(x, y)] — 원점 단면 좌상단, x: b 방향, y: h 방향(휨 깊이). edge: 표면~철근중심."""
    nx, ny = layout
    xs = [edge + (b - 2 * edge) * i / (nx - 1) for i in range(nx)]
    ys = [edge + (h - 2 * edge) * j / (ny - 1) for j in range(ny)]
    pts = [(x, ys[0]) for x in xs] + [(x, ys[-1]) for x in xs]
    for y in ys[1:-1]:
        pts += [(xs[0], y), (xs[-1], y)]
    return pts


def rc_column_check(b, h, Pu, Mu, Vu, main_bars, tie, fck=24.0, cover=40.0, layout=None):
    """직사각형 기둥 — 주근을 둘레에 배치 (가로 nx = b면, 세로 ny = h면 개수, 모서리 공유).
    b: 휨방향 폭, h: 휨방향 춤 (h 방향으로 휨). 변형률 적합으로 P-M 상관도 계산."""
    Ast, n, db, fy = as_of(main_bars)
    tp = parse_bar(tie)
    td = tp[2] if tp else 10
    ecu, eta, b1 = stress_block(fck)
    Ag = b * h
    lay = layout if (layout and 2 * layout[0] + 2 * layout[1] - 4 == n) else default_layout(n, b, h)
    edge = cover + td + db / 2
    ab = bar_area(db) if db else 0.0
    if lay:
        pos = col_bar_positions(b, h, n, lay, edge)
        rows = {}
        for _x, y in pos:
            rows[round(y, 3)] = rows.get(round(y, 3), 0) + 1
        layers = sorted((y, k * ab) for y, k in rows.items())
    else:                                   # 홀수 등 둘레 배치가 안 되면 양면 반씩
        layers = [(edge, Ast / 2), (h - edge, Ast / 2)]
    d = max(y for y, _ in layers)
    P0 = (0.85 * eta * fck * (Ag - Ast) + fy * Ast) / 1000
    phiPmax = 0.80 * 0.65 * P0

    def point(c):
        a = min(b1 * c, h)
        Cc = 0.85 * eta * fck * a * b
        Pn, Mn = Cc, Cc * (h / 2 - a / 2)
        for y, As_i in layers:
            fs = max(-fy, min(fy, ES * ecu * (c - y) / c))      # 압축 +
            if y < a and fs > 0:
                fs -= 0.85 * eta * fck                            # 철근이 차지한 콘크리트
            Pn += As_i * fs
            Mn += As_i * fs * (h / 2 - y)
        et = ecu * (d - c) / c
        return Pn / 1000, Mn / 1e6, phi_flex(et, fy)
    pts = []
    for i in range(1, 400):
        c = h * 3.0 * i / 400
        Pn, Mn, phi = point(c)
        pts.append((min(phi * Pn, phiPmax), phi * Mn))
    pts.append((phiPmax, 0.0))
    pts.sort()
    phiMn_at = 0.0
    for (p0, m0), (p1, m1) in zip(pts, pts[1:]):
        if p0 <= Pu <= p1 and p1 > p0:
            phiMn_at = max(phiMn_at, m0 + (m1 - m0) * (Pu - p0) / (p1 - p0))
    lines = [("축력 φPn,max", Pu, phiPmax, Pu / phiPmax if phiPmax else float("inf"), Pu <= phiPmax,
              f"Ast={Ast:.0f}mm² (ρ={Ast / Ag * 100:.2f}%)")]
    rho = Ast / Ag
    note = (f"배치 가로{lay[0]}×세로{lay[1]}" if lay else "둘레 배치 불가 → 양면 반씩 가정")
    if rho < 0.01 or rho > 0.08:
        note += f" · 철근비 {rho * 100:.2f}% (1~8% 범위 밖)"
    if lay:
        sx = (b - 2 * edge) / (lay[0] - 1) - db
        sy = (h - 2 * edge) / (lay[1] - 1) - db
        smin = max(40.0, 1.5 * db)
        if min(sx, sy) < smin:
            note += f" · 주근 순간격 {min(sx, sy):.0f} < {smin:.0f}mm"
    lines.append(("P-M 상관 (Pu에서 φMn)", Mu, phiMn_at, Mu / phiMn_at if phiMn_at > 0 else float("inf"),
                  Pu <= phiPmax and Mu <= phiMn_at, note))
    if Vu:
        r = rc_shear(b, d, tie, fck, Nu=Pu, Ag=Ag)
        lines.append(("전단 (띠철근)", Vu, r["phiVn"], Vu / r["phiVn"] if r["phiVn"] else float("inf"),
                      r["phiVn"] >= Vu, f"φVc={0.75 * r['Vc']:.1f}"))
    return lines, {"curve": pts, "phiPmax": phiPmax, "layout": lay}


# ============================================================================
def h_props(name):
    H, B, tw, tf, r = H_SECTIONS[name]
    hw = H - 2 * tf
    A = 2 * B * tf + hw * tw + (4 - math.pi) * r * r
    Ix = (B * H ** 3 - (B - tw) * hw ** 3) / 12
    Iy = (2 * tf * B ** 3 + hw * tw ** 3) / 12
    Zx = B * tf * (H - tf) + tw * hw * hw / 4
    Sx = Ix / (H / 2)
    J = (2 * B * tf ** 3 + (H - tf) * tw ** 3) / 3
    h0 = H - tf
    Cw = Iy * h0 * h0 / 4
    return {"H": H, "B": B, "tw": tw, "tf": tf, "A": A, "Ix": Ix, "Iy": Iy, "Zx": Zx, "Sx": Sx, "J": J, "Cw": Cw,
            "rx": math.sqrt(Ix / A), "ry": math.sqrt(Iy / A), "h0": h0}


def steel_beam_check(section, Fy, L, w, sup_i, sup_j, Lb=None):
    p = h_props(section)
    F = beam_forces(w, L, sup_i, sup_j)
    Mu = max(F["Mi"], F["Mj"], F["Mpos"])
    Vu = max(F["Vi"], F["Vj"])
    E = E_STEEL
    Mp = Fy * p["Zx"] / 1e6
    lam_f = p["B"] / (2 * p["tf"])
    lam_pf = 0.38 * math.sqrt(E / Fy)
    note = []
    if lam_f > lam_pf:
        note.append(f"플랜지 비조밀 (b/t={lam_f:.1f} > {lam_pf:.1f}) — 국부좌굴 미반영")
    Lb_mm = (Lb if Lb else L) * 1000
    ry = p["ry"]
    Lp = 1.76 * ry * math.sqrt(E / Fy)
    rts = math.sqrt(math.sqrt(p["Iy"] * p["Cw"]) / p["Sx"])
    Jc = p["J"] / (p["Sx"] * p["h0"])
    Lr = 1.95 * rts * E / (0.7 * Fy) * math.sqrt(Jc + math.sqrt(Jc ** 2 + 6.76 * (0.7 * Fy / E) ** 2))
    if Lb_mm <= Lp:
        Mn = Mp
        lt = "소성 (Lb≤Lp)"
    elif Lb_mm <= Lr:
        Mn = min(Mp, Mp - (Mp - 0.7 * Fy * p["Sx"] / 1e6) * (Lb_mm - Lp) / (Lr - Lp))
        lt = "비탄성 횡좌굴"
    else:
        Fcr = math.pi ** 2 * E / (Lb_mm / rts) ** 2 * math.sqrt(1 + 0.078 * Jc * (Lb_mm / rts) ** 2)
        Mn = min(Mp, Fcr * p["Sx"] / 1e6)
        lt = "탄성 횡좌굴"
    phiMn = 0.9 * Mn
    phiVn = 1.0 * 0.6 * Fy * p["H"] * p["tw"] / 1000
    lines = [("휨 (최대 |M|)", Mu, phiMn, Mu / phiMn, Mu <= phiMn,
              f"{lt}, Lb={Lb_mm / 1000:.2f}m, Lp={Lp / 1000:.2f}m, Lr={Lr / 1000:.2f}m, Cb=1" +
              (" · " + "; ".join(note) if note else "")),
             ("전단", Vu, phiVn, Vu / phiVn, Vu <= phiVn, "φv=1.0, 0.6Fy·d·tw")]
    return lines, F


def steel_column_check(section, Fy, L, K, Pu, Mu):
    p = h_props(section)
    E = E_STEEL
    KL = K * L * 1000
    r = p["ry"]
    sl = KL / r
    Fe = math.pi ** 2 * E / sl ** 2
    if sl <= 4.71 * math.sqrt(E / Fy):
        Fcr = 0.658 ** (Fy / Fe) * Fy
    else:
        Fcr = 0.877 * Fe
    phiPn = 0.9 * Fcr * p["A"] / 1000
    phiMn = 0.9 * Fy * p["Zx"] / 1e6
    pr = Pu / phiPn if phiPn else float("inf")
    mr = Mu / phiMn if phiMn else float("inf")
    inter = pr + 8 / 9 * mr if pr >= 0.2 else pr / 2 + mr
    lines = [("축압축 φPn (약축)", Pu, phiPn, pr, pr <= 1, f"KL/r={sl:.0f}, Fcr={Fcr:.0f}MPa"),
             ("휨 φMn (소성 가정)", Mu, phiMn, mr, mr <= 1, "횡좌굴 미반영"),
             ("축력+휨 상관", inter, 1.0, inter, inter <= 1.0, "Pr/Pc≥0.2: Pr/Pc+8/9·Mr/Mc")]
    return lines


# ============================================================================
def summarize(lines):
    """→ (전체 OK?, '휨 O.K · 전단 N.G' 형태 요약)"""
    groups = {}
    for name, *_r, ok, _e in [(l[0], l[1], l[2], l[3], l[4], l[5]) for l in lines]:
        g = "휨" if name.startswith("휨") else "전단" if name.startswith("전단") else \
            "P-M" if "P-M" in name else "축력+휨" if "상관" in name else "축력" if "축" in name else name
        groups[g] = groups.get(g, True) and ok
    txt = " · ".join(f"{g} {'O.K' if v else 'N.G'}" for g, v in groups.items())
    return all(groups.values()), txt
