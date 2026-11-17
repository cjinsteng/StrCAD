"""
basic_design/rc/slab_report.py
슬래브 Lite 계산 결과(slab_calc) → 계산서(Report) · 스케치
"""
from ..report import Report, fonts
from .. import theme as T
from . import slab_calc as S
from .slab_coef import CASE_DESC

DESIGN_CODE = "KDS 14 20 : 2022  (KDS 41 20 00)"
EDGE_NAMES = ["B1(상)", "B2(하)", "B3(좌)", "B4(우)"]


def _sp(v):
    return "-" if v is None else f"@{v}"


def _okng(ok):
    return ("O.K.", "ok") if ok else ("N.G.", "ng")


def build(res):
    return _one_way(res) if res["type"] == "1way" else _two_way(res)


# ── 공통 블록 ────────────────────────────────────────────────
def _material(rep, r):
    rep.t("Material & Dim.", 0, "sub")
    rep.t(f"Concrete     fck = {r['fck']:g} N/mm²", 2)
    rep.t(f"Re-bar        fy(D13↓) = {r['fy13']:g} N/mm²    fy(D16↑) = {r['fy16']:g} N/mm²", 2)


def _loads(rep, r):
    rep.t("Applied Loads", 0, "sub")
    rep.t(f"Dead Load   Wd = {r['wd']:.2f} kN/m²", 2)
    rep.t(f"Live Load    Wl = {r['wl']:.2f} kN/m²", 2)
    rep.t(f"Wu = {r['wu_txt']} = {r['wu']:.2f} kN/m²", 2)


def _sp_cells(sp, r):
    """간격 셀 — 선택 철근 열은 굵게"""
    return [(_sp(v), "b") if j == r["sel_col"] else _sp(v) for j, v in enumerate(sp)]


def _flex_table(rep, r, rows, tail_rows):
    labels = [(c, "sel") if j == r["sel_col"] else c for j, c in enumerate(r["cols"])]
    head = [["DIREC", "Loca", "Mu", "ρ", "Ast", "", "", "Spacing", "", ""],
            ["TION", "tion", "(kN·m/m)", "(%)", "(mm²/m)"] + labels]
    widths = [58, 112, 78, 62, 74, 72, 86, 72, 86, 72]
    aligns = ["l", "l", "r", "r", "r", "c", "c", "c", "c", "c"]
    body = []
    prev = None
    for x in rows:
        if prev is not None and x["dir"] != prev:
            body.append(None)
        st = "n" if x["ok"] else "ng"
        if x["ok"]:
            body.append([x["dir"] if x["dir"] != prev else "", x["loc"], (f"{x['mu']:.2f}", st),
                         (f"{x['rho'] * 100:.3f}", st), (f"{x['as_req']:.0f}", st)] + _sp_cells(x["sp"], r))
        else:
            body.append([x["dir"] if x["dir"] != prev else "", x["loc"], (f"{x['mu']:.2f}", st),
                         ("단면 부족", "ng"), ("", st)] + [("-", "ng")] * len(x["sp"]))
        prev = x["dir"]
    body.append(None)
    for x in tail_rows:
        body.append(["", x["loc"], "", f"{x['rho'] * 100:.3f}", f"{x['as_req']:.0f}"] + _sp_cells(x["sp"], r))
    rep.table(head, body, widths, aligns)


def _summary(rep, r, extra=None):
    rep.h(f"Design Summary  ({r['bar']})")
    head = [["Direction", "Location", "Use", "As,prov", "φMn", "Mu", "비고", "Check"],
            ["", "", "", "(mm²/m)", "(kN·m/m)", "(kN·m/m)", "", ""]]
    widths = [80, 116, 100, 96, 96, 96, 140, 68]
    aligns = ["l", "l", "c", "r", "r", "r", "c", "c"]
    body = []
    for s in r["summary"]:
        if s["s"] is None:
            body.append([s["dir"], s["loc"], ("-", "ng"), "", "", f"{s['mu']:.2f}", (s["why"], "ng"), ("N.G.", "ng")])
            continue
        body.append([s["dir"], s["loc"], (f"{r['bar']}@{s['s']}", "b"), f"{s['as_prov']:.0f}", f"{s['phi_mn']:.2f}",
                     f"{s['mu']:.2f}", s["gov"] if s["ok"] else (s["why"], "ng"), _okng(s["ok"])])
    for e in (extra or []):
        body.append(e)
    rep.table(head, body, widths, aligns)


def _notes(rep, r, notes):
    if r["warn"] or notes:
        rep.h("Notes")
        for w in r["warn"]:
            rep.t("※ " + w, 1, "warn")
        for n in notes:
            rep.t("· " + n, 1, "dim")


# ── 1방향 ────────────────────────────────────────────────────
def _one_way(r):
    rep = Report(f"1Way Slab — {r['name']}")
    rep.h("Design Conditions")
    rep.t(f"Design Code  :  {DESIGN_CODE}", 1)
    rep.t(f"Slab Type      :  1 Way  ·  {r['support_txt']}", 1)
    _material(rep, r)
    rep.t(f"Slab Span     :  {r['L']:.2f} m", 2)
    rep.t(f"Slab Thk.      :  {r['t']:g} mm  (cc = {r['cc']:g} mm,  d = {r['d']:.1f} mm)", 2)
    _loads(rep, r)

    rep.h("Check Minimum Slab Thk.")
    k = "" if abs(r["h_kfy"] - 1.0) < 1e-9 else f" × (0.43+fy/700 = {r['h_kfy']:.3f})"
    rep.t(f"Treq = ln/{r['h_n']:.1f}{k} = {r['h_req']:.0f} mm      (KDS 14 20 30 표 4.2-1)", 1)
    ok = r["h_ok"]
    rep.t(f"Thk = {r['t']:g}   {'>' if ok else '<'}   Treq = {r['h_req']:.0f} mm   --->  {'O.K.' if ok else 'N.G. (처짐 검토 필요)'}",
          1, "ok" if ok else "ng")

    rep.h("Flexure Reinforcement")
    _flex_table(rep, r, r["rows"], [r["min_row"], r["temp_row"]])
    for x in r["rows"]:
        rep.t(f"{x['loc']} :  Mu = {x['formula']} = {x['mu']:.2f} kN·m/m", 1, "dim")
    rep.t(f"주철근 최대간격 = min(2t, 300, 균열제어 {r['s_crack']:.0f}) = {S._floor10(r['s_main'])} mm"
          f"      [fs = 2/3·fy = {r['fs']:.0f} MPa, κcr = {r['kcr']:g}]", 1, "dim")

    _summary(rep, r, extra=[None, ["직각방향", "배력근 Temp.", (f"{r['bar']}@{r['temp_s']}", "b"),
                                  f"{S.REBAR[r['bar']][1] / r['temp_s'] * 1000:.0f}", "", "", "수축·온도", ("O.K.", "ok")]]
             if r["temp_s"] else None)

    rep.h("Check Shear Strength")
    rep.t(f"Strength Reduction Factor   φ = {S.PHI_V:.3f}", 1)
    s = r["shear"][0]
    rep.t(f"Vu = {s['txt']} = {s['vu']:.1f}   {'<' if s['ok'] else '>'}   φVc = {s['phi_vc']:.1f} kN/m   --->  {_okng(s['ok'])[0]}",
          1, "ok" if s["ok"] else "ng")

    _notes(rep, r, [
        "유효깊이 d = T - Cc - db/2 (선택 철근 공칭지름 기준)",
        "Min Bar: 경간방향 최소철근(KDS 14 20 20 4.2.2(3)),  Temp. Bar: 직각방향 수축·온도철근(KDS 14 20 50 4.6.2)",
        "D16 이상 철근 열은 fy(D16↑), 혼용 열은 작은 fy 기준 소요철근량으로 간격을 산정 (굵은 열 = 사용 철근)",
        "강도감소계수 φ: 인장지배 0.85, 변화구간은 εt 에 따라 보간 (KDS 14 20 20 4.1.2)",
    ])
    return rep


# ── 2방향 ────────────────────────────────────────────────────
def _two_way(r):
    rep = Report(f"2Way Slab — {r['name']}")
    rep.h("Design Conditions")
    rep.t(f"Design Code  :  {DESIGN_CODE}", 1)
    rep.t(f"Slab Type      :  2 Way  ·  Case {r['case']} ({CASE_DESC[r['case']]})", 1)
    _material(rep, r)
    rep.t(f"Slab Dim.  :  {r['lx'] * 1000:.0f} × {r['ly'] * 1000:.0f} × {r['t']:g} mm  (cc = {r['cc']:g} mm)", 2)
    rep.t("Edge Beam", 2)
    b = r["beams"]
    rep.t(f"UP = {b[0][0]:g}×{b[0][1]:g},    DN = {b[1][0]:g}×{b[1][1]:g} mm", 3)
    rep.t(f"LT = {b[2][0]:g}×{b[2][1]:g},    RT = {b[3][0]:g}×{b[3][1]:g} mm", 3)
    _loads(rep, r)

    rep.h("Check Minimum Slab Thk.")
    rep.t(f"β = Lny/Lnx = {r['lny']:.0f}/{r['lnx']:.0f} = {r['beta']:.4f}        "
          f"αfm = {r['afm']:.2f}  (" + ", ".join(f"{a:.2f}" for a in r["alphas"]) + ")", 1)
    rep.t(f"hreq = {r['h_txt']}" + ("  × 1.1" if r["h_inc"] else "") + f" = {r['h_req']:.0f} mm", 1)
    ok = r["h_ok"]
    rep.t(f"Thk = {r['t']:g}   {'>' if ok else '<'}   Treq = {r['h_req']:.0f} mm   --->  {'O.K.' if ok else 'N.G. (처짐 검토 필요)'}",
          1, "ok" if ok else "ng")

    rep.h("Flexure Reinforcement")
    _flex_table(rep, r, r["rows"], [r["min_row"]])
    c = r["coef"]
    rep.t(f"m = Lx/Ly = {r['m']:.3f}     Wdu = {r['wdu']:.2f},  Wlu = {r['wlu']:.2f} kN/m²     "
          f"d(Short) = {r['d_s']:.1f},  d(Long) = {r['d_l']:.1f} mm", 1, "dim")
    rep.t(f"Ca,neg = {c['ca_neg']:.4f}   Ca,dl = {c['ca_dl']:.4f}   Ca,ll = {c['ca_ll']:.4f}      "
          f"Cb,neg = {c['cb_neg']:.4f}   Cb,dl = {c['cb_dl']:.4f}   Cb,ll = {c['cb_ll']:.4f}", 1, "dim")

    _summary(rep, r)

    rep.h("Check Shear Strength")
    rep.t(f"Strength Reduction Factor   φ = {S.PHI_V:.3f}", 1)
    for s in r["shear"]:
        rep.t(s["label"], 0, "sub")
        rep.t(f"{s['sym']} = {s['txt']} = {s['vu']:.1f}   {'<' if s['ok'] else '>'}   φVc = {s['phi_vc']:.1f} kN/m   --->  {_okng(s['ok'])[0]}",
              2, "ok" if s["ok"] else "ng")

    _notes(rep, r, [
        "모멘트·전단: 4변 지지 2방향 슬래브 계수법 (m 은 직선보간),  불연속단 부모멘트 = 정모멘트의 1/3",
        "유효깊이: 단변방향 d = T - Cc - db/2,  장변방향 d = 단변방향 d - db (선택 철근 공칭지름 기준)",
        "휨철근 최대간격 min(2t, 300),  Min Bar: 수축·온도철근(KDS 14 20 50 4.6.2) 최대간격 min(5t, 450)",
        "D16 이상 철근 열은 fy(D16↑), 혼용 열은 작은 fy 기준 소요철근량으로 간격을 산정 (굵은 열 = 사용 철근)",
        "강도감소계수 φ: 인장지배 0.85, 변화구간은 εt 에 따라 보간 (KDS 14 20 20 4.1.2)",
    ])
    return rep


# ── 스케치 ───────────────────────────────────────────────────
def _hatch_edge(cv, x1, y1, x2, y2, nx, ny, color="#d946ef"):
    """연속단 표시: 변 바깥쪽으로 빗금"""
    import math
    length = math.hypot(x2 - x1, y2 - y1)
    n = max(int(length // 6), 1)
    for i in range(n + 1):
        px = x1 + (x2 - x1) * i / n
        py = y1 + (y2 - y1) * i / n
        cv.create_line(px, py, px + nx * 7 + (ny * 5), py + ny * 7 + (nx * 5), fill=color)
    cv.create_line(x1, y1, x2, y2, fill=color, width=2)


def _dim(cv, x1, y1, x2, y2, text, F, vertical=False):
    cv.create_line(x1, y1, x2, y2, fill=T.INK)
    if vertical:
        for yy in (y1, y2):
            cv.create_line(x1 - 4, yy, x1 + 4, yy, fill=T.INK)
        cv.create_text(x1 - 6, (y1 + y2) / 2, text=text, angle=90, anchor="s", font=F["n"], fill=T.INK)
    else:
        for xx in (x1, x2):
            cv.create_line(xx, y1 - 4, xx, y1 + 4, fill=T.INK)
        cv.create_text((x1 + x2) / 2, y1 - 3, text=text, anchor="s", font=F["n"], fill=T.INK)


def _section(cv, cx, y, w, r, F):
    """슬래브 단면(상·하부 철근)"""
    h = 30
    x1, x2 = cx - w / 2, cx + w / 2
    cv.create_rectangle(x1, y, x2, y + h, outline="#dc2626", fill="#FFFBEA")
    for yy in (y + 8, y + h - 8):
        cv.create_line(x1, yy, x2, yy, fill="#dc2626")
        for i in range(3):
            xx = x1 + w * (i + 1) / 4
            cv.create_oval(xx - 2.5, yy - 2.5, xx + 2.5, yy + 2.5, fill="#dc2626", outline="#dc2626")
    _dim(cv, x1 - 14, y, x1 - 14, y + h, f"{r['t']:g}", F, vertical=True)


def draw_plan_icon(cv, edges, x, y, w, h, labels=True, font=None):
    """Case 아이콘/평면: edges = (상, 하, 좌, 우) 연속 여부"""
    cv.create_rectangle(x, y, x + w, y + h, fill="#FFFBEA", outline=T.INK)
    if edges[0]:
        _hatch_edge(cv, x, y, x + w, y, 0, -1)
    if edges[1]:
        _hatch_edge(cv, x, y + h, x + w, y + h, 0, 1)
    if edges[2]:
        _hatch_edge(cv, x, y, x, y + h, -1, 0)
    if edges[3]:
        _hatch_edge(cv, x + w, y, x + w, y + h, 1, 0)
    if labels and font is not None:
        cv.create_text(x + w / 2, y + 9, text="B1", font=font, fill=T.NAVY)
        cv.create_text(x + w / 2, y + h - 9, text="B2", font=font, fill=T.NAVY)
        cv.create_text(x + 11, y + h / 2, text="B3", font=font, fill=T.NAVY)
        cv.create_text(x + w - 11, y + h / 2, text="B4", font=font, fill=T.NAVY)


def sketch_box(res):
    """오른쪽 위 그림 영역 (x, y, w, h) — 1방향은 모멘트도·전단도가 들어가 더 높다."""
    return (590, 18, 290, 392) if res["type"] == "1way" else (590, 18, 290, 330)


def moment_curve(ml, mp, mr, cantilever=False, n=48):
    """모멘트도 좌표 [(ξ, M)] — M 은 정모멘트(+), 부모멘트(-).
    양단 설계 부모멘트(ml, mr)를 잇는 직선에 포물선을 더해 최대 정모멘트가 mp 가 되도록 한 곡선."""
    xs = [i / n for i in range(n + 1)]
    if cantilever:
        return [(t, -ml * (1 - t) ** 2) for t in xs]

    def peak(sag):
        return max(-ml * (1 - t) - mr * t + 4 * sag * t * (1 - t) for t in xs)
    lo, hi = 0.0, max(mp + ml + mr, 1e-9) * 2
    for _ in range(50):
        mid = (lo + hi) / 2
        if peak(mid) < mp:
            lo = mid
        else:
            hi = mid
    sag = (lo + hi) / 2
    return [(t, -ml * (1 - t) - mr * t + 4 * sag * t * (1 - t)) for t in xs]


def _moment_diagram(cv, F, r, x1, x2, yb, bx):
    """1방향 모멘트도 — 부모멘트는 기준선 위, 정모멘트는 아래(인장측)"""
    dg = r["diagram"]
    col, fill = "#2563eb", "#DBEAFE"
    pts = moment_curve(dg["ml"], dg["mp"], dg["mr"], cantilever=(r["support"] == "CANT"))
    mmax = max(abs(m) for _, m in pts) or 1.0
    k = 30.0 / mmax
    xy = [(x1 + (x2 - x1) * t, yb + m * k) for t, m in pts]
    cv.create_text(bx + 12, yb - 48, text="Moment (kN·m/m)", anchor="w", font=F["s"], fill=col)
    cv.create_polygon([(x1, yb)] + xy + [(x2, yb)], fill=fill, outline="")
    cv.create_line(xy, fill=col, width=2)
    cv.create_line(x1, yb, x1, xy[0][1], fill=col)
    cv.create_line(x2, yb, x2, xy[-1][1], fill=col)
    cv.create_line(x1 - 10, yb, x2 + 10, yb, fill=T.INK)
    if dg["ml"] > 0:
        cv.create_text(x1 - 4, yb - dg["ml"] * k - 2, text=f"-{dg['ml']:.2f}", anchor="e", font=F["s"], fill=T.INK)
    if dg["mr"] > 0:
        cv.create_text(x2 + 4, yb - dg["mr"] * k - 2, text=f"-{dg['mr']:.2f}", anchor="w", font=F["s"], fill=T.INK)
    if dg["mp"] > 0:
        t_pk, m_pk = max(pts, key=lambda p: p[1])
        cv.create_text(x1 + (x2 - x1) * t_pk, yb + m_pk * k + 10, text=f"+{dg['mp']:.2f}", font=F["s"], fill=T.INK)


def _shear_diagram(cv, F, r, x1, x2, yb, bx):
    """1방향 전단도 — 좌단(+)에서 우단(-)으로 직선"""
    dg = r["diagram"]
    col, fill = "#059669", "#D1FAE5"
    vmax = max(abs(dg["vl"]), abs(dg["vr"])) or 1.0
    k = 26.0 / vmax
    ya, yc = yb - dg["vl"] * k, yb - dg["vr"] * k
    cv.create_text(bx + 12, yb - 44, text="Shear (kN/m)", anchor="w", font=F["s"], fill=col)
    if dg["vl"] * dg["vr"] < 0:
        xz = x1 + (x2 - x1) * dg["vl"] / (dg["vl"] - dg["vr"])
        cv.create_polygon(x1, yb, x1, ya, xz, yb, fill=fill, outline="")
        cv.create_polygon(xz, yb, x2, yc, x2, yb, fill=fill, outline="")
    else:
        cv.create_polygon(x1, yb, x1, ya, x2, yc, x2, yb, fill=fill, outline="")
    cv.create_line(x1, yb, x1, ya, x2, yc, x2, yb, fill=col, width=2)
    cv.create_line(x1 - 10, yb, x2 + 10, yb, fill=T.INK)
    cv.create_text(x1 - 4, ya + 2, text=f"{dg['vl']:.1f}", anchor="e", font=F["s"], fill=T.INK)
    if abs(dg["vr"]) > 0:
        cv.create_text(x2 + 4, yc - 2, text=f"{dg['vr']:.1f}", anchor="w", font=F["s"], fill=T.INK)


def sketch(res):
    """render() 에 넘길 그림 함수"""
    def one_way(cv, x, y, w, h):
        F = fonts(cv)
        r = res
        cy = y + 74
        x1, x2 = x + 52, x + w - 52
        sup = r["support"]
        cv.create_line(x1 - (0 if sup == "CANT" else 24), cy, x2 + (0 if sup in ("CANT", "SS") else 24), cy,
                       fill=T.INK, width=2)
        # 하중
        for i in range(9):
            xx = x1 + (x2 - x1) * i / 8
            cv.create_line(xx, cy - 28, xx, cy - 5, arrow="last", arrowshape=(6, 7, 3), fill=T.INK)
        cv.create_line(x1, cy - 28, x2, cy - 28, fill=T.INK)
        cv.create_text((x1 + x2) / 2, cy - 40, text=f"Wu = {r['wu']:.2f} kN/m²", font=F["n"], fill=T.INK)

        def tri(xx):
            cv.create_polygon(xx, cy, xx - 8, cy + 13, xx + 8, cy + 13, fill="#dc2626", outline="#dc2626")

        def fixed(xx):
            cv.create_line(xx, cy - 22, xx, cy + 22, fill=T.INK, width=2)
            for i in range(8):
                yy = cy - 22 + i * 6
                cv.create_line(xx, yy, xx - 7, yy + 6, fill=T.INK)
        if sup == "CANT":
            fixed(x1)
        else:
            tri(x1); tri(x2)
        if sup in ("DC", "DCI", "CC"):
            cv.create_text(x2 + 26, cy + 24, text="연속", font=F["s"], fill=T.MUTED)
        if sup == "CC":
            cv.create_text(x1 - 26, cy + 24, text="연속", font=F["s"], fill=T.MUTED)
        elif sup in ("DC", "DCI"):
            cv.create_text(x1 - 26, cy + 24, text="불연속", font=F["s"], fill=T.MUTED)
        _dim(cv, x1, cy + 46, x2, cy + 46, f"{r['L'] * 1000:.0f}", F)
        _moment_diagram(cv, F, r, x1, x2, y + 194, x)
        _shear_diagram(cv, F, r, x1, x2, y + 318, x)

    def two_way(cv, x, y, w, h):
        F = fonts(cv)
        r = res
        aw, ah = w - 120, h - 150                         # 평면 영역
        sc = min(aw / r["lx"], ah / r["ly"])
        pw, ph = r["lx"] * sc, r["ly"] * sc
        px = x + (w - pw) / 2 + 14
        py = y + 22 + (ah - ph) / 2
        draw_plan_icon(cv, r["edges"], px, py, pw, ph, labels=False)
        cv.create_text(px + pw / 2, py + ph / 2, text=f"Case {r['case']}", font=F["b"], fill=T.NAVY)
        _dim(cv, px - 24, py, px - 24, py + ph, f"{r['ly'] * 1000:.0f}", F, vertical=True)
        _dim(cv, px, py + ph + 30, px + pw, py + ph + 30, f"{r['lx'] * 1000:.0f}", F)
        _section(cv, x + w / 2 + 14, y + h - 60, 110, r, F)

    return one_way if res["type"] == "1way" else two_way
