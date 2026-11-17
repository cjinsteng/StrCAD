"""
basic_design/rc/slab_pro.py
RC Slab — Pro : 유한요소 해석 기반 슬래브 설계 (Tk 비의존 계산 + 계산서 + 등고선 그림)

  · 해석     slab_fem (MITC4 판 요소 + 변 보 요소),  고정(D)·활(L) 하중을 따로 풀어 조합
  · 조합     U = max(1.4D, 1.2D + 1.6L) (점별 포락),  사용하중 D, D+L, 지속하중
  · 설계모멘트  Wood–Armer (선택): 하부 Mx + |Mxy|,  상부 -Mx + |Mxy|
  · 휨·전단·최소철근·배근 간격   Slab Lite 와 같은 함수 사용
  · 처짐     탄성(전단면) 처짐 × 균열 보정(Ig/Ie),  장기 = λΔ·Δ(지속) + Δ(활하중 순간)
"""
import math

import numpy as np

from ..report import Report, fonts
from .. import theme as T
from . import slab_calc as S
from . import slab_fem as FEM
from . import slab_report as R

NU = 0.167
DESIGN_CODE = "KDS 14 20 : 2022  (KDS 41 20 00)"
EDGE_LABEL = {"top": "상부", "bottom": "하부", "left": "좌측", "right": "우측"}
CORNERS = [("lt", "좌측상부", 0, 1), ("lb", "좌측하부", 0, 0), ("rt", "우측상부", 1, 1), ("rb", "우측하부", 1, 0)]
FIELDS = [                         # key, 표시, 단위, 설명
    ("mx", "Mxx", "kN·m/m", "X-X 방향 휨모멘트 (계수하중)"),
    ("my", "Myy", "kN·m/m", "Y-Y 방향 휨모멘트 (계수하중)"),
    ("mxy", "Mxy", "kN·m/m", "비틀림 모멘트 (계수하중)"),
    ("qx", "Vxx", "kN/m", "X-X 방향 전단력 (계수하중)"),
    ("qy", "Vyy", "kN/m", "Y-Y 방향 전단력 (계수하중)"),
    ("dz", "처짐(순간)", "mm", "D+L 순간처짐 (균열 보정)"),
    ("dzl", "처짐(장기)", "mm", "장기처짐 λΔ·Δs + ΔL"),
]


class ProInputError(ValueError):
    pass


def mesh_divisions(lx, ly, n_short):
    n_short = int(max(8, min(32, n_short)))
    n_short += n_short % 2
    ratio = max(lx, ly) / min(lx, ly)
    n_long = int(min(48, max(n_short, round(n_short * ratio / 2.0) * 2)))
    return (n_short, n_long) if lx <= ly else (n_long, n_short)


def _split_loads(loads, key):
    pts, lines, areas = [], [], []
    for ld in loads:
        v = ld.get(key, 0.0)
        if not v:
            continue
        if ld["type"] == "P":
            pts.append((ld["x"], ld["y"], v))
        elif ld["type"] == "L":
            lines.append((ld["x1"], ld["y1"], ld["x2"], ld["y2"], v))
        else:
            areas.append((ld["x1"], ld["y1"], ld["x2"], ld["y2"], v))
    return pts, lines, areas


def _argmax(arr, xs, ys):
    j, i = np.unravel_index(int(np.argmax(arr)), arr.shape)
    return float(arr[j, i]), float(xs[i]), float(ys[j])


def calc_pro(inp):
    """inp: name, lx, ly, t, cc, fck, fy13, fy16, wd, wl, bar, phi_f, phi_v,
            edges {top|bottom|left|right: (kind, bw mm, bh mm)}, corners {lt|lb|rt|rb: bool},
            loads [ {type 'P'|'L'|'A', 좌표…, d, l} ], mesh, wood_armer, months, lim_live, lim_long, sus_live"""
    try:
        fck, fy13, fy16, fy, t, cc, bar, db = S._common(inp)
    except S.SlabInputError as e:
        raise ProInputError(str(e)) from None
    pf, pv = inp.get("phi_f", S.PHI_F), inp.get("phi_v", S.PHI_V)
    lx, ly = inp["lx"], inp["ly"]
    if lx <= 0 or ly <= 0:
        raise ProInputError("Lx, Ly 는 0보다 커야 합니다.")
    if max(lx, ly) / min(lx, ly) > 6:
        raise ProInputError("변장비가 너무 큽니다 (6 이하로 입력).")
    loads = inp.get("loads", [])
    for n, ld in enumerate(loads, 1):
        cs = [(ld["x"], ld["y"])] if ld["type"] == "P" else [(ld["x1"], ld["y1"]), (ld["x2"], ld["y2"])]
        for x, y in cs:
            if not (0 <= x <= lx + 1e-9 and 0 <= y <= ly + 1e-9):
                raise ProInputError(f"추가 하중 {n}번: 위치 ({x:g}, {y:g}) 가 슬래브(0~{lx:g}, 0~{ly:g}) 밖입니다.")
    nx, ny = mesh_divisions(lx, ly, inp.get("mesh", 16))
    ec = S.ec_of(fck)
    model = FEM.SlabModel(lx, ly, t / 1000.0, ec * 1000.0, NU, nx, ny)
    edges = inp["edges"]
    try:
        for e in FEM.EDGE_KEYS:
            kind, bw, bh = edges[e]
            model.set_edge(e, kind, bw / 1000.0, bh / 1000.0)
        for key, _, ix, iy in CORNERS:
            model.set_corner(ix, iy, bool(inp["corners"].get(key, True)))
        f_d = model.load_vector(inp["wd"], *_split_loads(loads, "d"))
        f_l = model.load_vector(inp["wl"], *_split_loads(loads, "l"))
        u_d, u_l = model.solve([f_d, f_l])
    except FEM.FemError as e:
        raise ProInputError(str(e)) from None
    r_d, r_l = model.recover(u_d), model.recover(u_l)
    xs, ys = model.xs, model.ys
    tot_d, tot_l = float(f_d[0::3].sum()), float(f_l[0::3].sum())

    combos = [("1.4D", 1.4, 0.0), ("1.2D+1.6L", 1.2, 1.6)]

    def comb(key, a, b):
        return a * r_d[key] + b * r_l[key]
    gov = max(combos, key=lambda c: c[1] * tot_d + c[2] * tot_l)      # 화면 표시용 조합 (전체 하중이 큰 쪽)
    wa = bool(inp.get("wood_armer", True))
    env = {k: None for k in ("xb", "xt", "yb", "yt", "qx", "qy")}
    for _, a, b in combos:
        mx, my, mxy = comb("mx", a, b), comb("my", a, b), comb("mxy", a, b)
        tw = np.abs(mxy) if wa else 0.0
        cur = {"xb": np.maximum(mx + tw, 0), "xt": np.maximum(-mx + tw, 0),
               "yb": np.maximum(my + tw, 0), "yt": np.maximum(-my + tw, 0),
               "qx": np.abs(comb("qx", a, b)), "qy": np.abs(comb("qy", a, b))}
        for k in env:
            env[k] = cur[k] if env[k] is None else np.maximum(env[k], cur[k])

    # 유효깊이: 짧은 변 방향 철근을 바깥층에
    d_out = t - cc - db / 2.0
    d_in = d_out - db
    if d_in <= 10:
        raise ProInputError("두께에 비해 피복두께가 너무 큽니다 (유효깊이 부족).")
    d_x, d_y = (d_out, d_in) if lx <= ly else (d_in, d_out)
    s_flex = min(2.0 * t, 300.0)
    s_min = min(5.0 * t, 450.0)
    cols = S.spacing_cols(bar)
    rows = []

    def add(direction, loc, arr, d):
        mu, x, y = _argmax(arr, xs, ys)
        rows.append(S._row(direction, loc, mu, f"x = {x:.2f}, y = {y:.2f} m", d, fck, fy, fy13, fy16, s_flex, cols, pf))
        return mu

    def interior_top(direction, arr, d, edge_max):
        mu = float(arr.max()) if arr.size else 0.0
        if mu > max(1.05 * edge_max, 0.5):
            sub = np.zeros_like(env["xt"])
            if direction.startswith("X"):
                sub[:, 1:-1] = arr
            else:
                sub[1:-1, :] = arr
            add(direction, "내부 상부 Top", sub, d)

    e1 = add("X-X Dir.", "좌단 Left", env["xt"][:, :1] * np.ones((1, 1)), d_x)
    rows[-1]["formula"] = f"x = 0.00, y = {ys[int(np.argmax(env['xt'][:, 0]))]:.2f} m"
    add("X-X Dir.", "중앙 Cent.", env["xb"], d_x)
    e2 = float(env["xt"][:, -1].max())
    rows.append(S._row("X-X Dir.", "우단 Right", e2, f"x = {lx:.2f}, y = {ys[int(np.argmax(env['xt'][:, -1]))]:.2f} m",
                       d_x, fck, fy, fy13, fy16, s_flex, cols, pf))
    interior_top("X-X Dir.", env["xt"][:, 1:-1], d_x, max(e1, e2))
    e1 = float(env["yt"][-1, :].max())
    rows.append(S._row("Y-Y Dir.", "상단 Upper", e1, f"x = {xs[int(np.argmax(env['yt'][-1, :]))]:.2f}, y = {ly:.2f} m",
                       d_y, fck, fy, fy13, fy16, s_flex, cols, pf))
    add("Y-Y Dir.", "중앙 Cent.", env["yb"], d_y)
    e2 = float(env["yt"][0, :].max())
    rows.append(S._row("Y-Y Dir.", "하단 Lower", e2, f"x = {xs[int(np.argmax(env['yt'][0, :]))]:.2f}, y = 0.00 m",
                       d_y, fck, fy, fy13, fy16, s_flex, cols, pf))
    interior_top("Y-Y Dir.", env["yt"][1:-1, :], d_y, max(e1, e2))

    as_by_fy = {f: S.rho_min(f) * 1000.0 * t for f in {fy13, fy16}}
    min_row = {"dir": "", "loc": "Min Bar", "mu": None, "rho": S.rho_min(fy), "as_req": S.rho_min(fy) * 1000.0 * t,
               "sp": S.spacings(as_by_fy, fy13, fy16, s_min, cols), "s_max": s_min, "ok": True, "d": d_out}
    summary = S._summary(rows, min_row, bar, fck, fy, cols, pf)

    # 전단
    shear = []
    for key, lbl, sym, d in (("qx", "X-X Direction Shear", "Vux", d_x), ("qy", "Y-Y Direction Shear", "Vuy", d_y)):
        vu, x, y = _argmax(env[key], xs, ys)
        pvc = S.phi_vc(d, fck, pv=pv)
        shear.append({"label": lbl, "sym": sym, "vu": vu, "x": x, "y": y, "phi_vc": pvc, "d": d, "ok": vu <= pvc + 1e-9})

    # 처짐 (사용하중)
    ig = 1000.0 * t ** 3 / 12.0
    mcr = 0.63 * math.sqrt(fck) * ig / (t / 2.0) / 1e6
    n_mod = S.ES / ec
    sus = inp.get("sus_live", 0.5)
    mxs, mys = (lambda a, b: a * r_d["mx"] + b * r_l["mx"]), (lambda a, b: a * r_d["my"] + b * r_l["my"])
    pos = {r["dir"]: r for r in rows if "Cent" in r["loc"]}

    def crack_factor(a, b):
        """하중 수준 (a·D + b·L) 에서 Ig/Ie — 정모멘트가 가장 큰 방향의 균열단면 기준"""
        ax, ay = float(mxs(a, b).max()), float(mys(a, b).max())
        ma, row, d = (ax, pos["X-X Dir."], d_x) if ax >= ay else (ay, pos["Y-Y Dir."], d_y)
        icr = S.i_cracked(max(row["as_req"], min_row["as_req"]), d, n_mod)
        return ig / S.i_eff(mcr, ma, ig, icr), ma
    k_d, ma_d = crack_factor(1, 0)
    k_dl, ma_dl = crack_factor(1, 1)
    k_s, ma_s = crack_factor(1, sus)
    w_d, w_l = r_d["w"], r_l["w"]
    dz_d = k_d * w_d
    dz_dl = k_dl * (w_d + w_l)
    dz_live = dz_dl - dz_d
    xi = S.xi_of(inp.get("months", 60))
    dz_long = xi * k_s * (w_d + sus * w_l) + dz_live
    span = min(lx, ly) * 1000.0
    lim_live, lim_long = inp.get("lim_live", 360.0), inp.get("lim_long", 480.0)
    v_live, xl, yl = _argmax(dz_live, xs, ys)
    v_long, xg, yg = _argmax(dz_long, xs, ys)
    defl = {"xi": xi, "months": inp.get("months", 60), "sus": sus, "ec": ec, "ig": ig, "mcr": mcr,
            "k_d": k_d, "k_dl": k_dl, "k_s": k_s, "ma_dl": ma_dl,
            "elastic": float((w_d + w_l).max()), "inst": float(dz_dl.max()),
            "live": v_live, "live_xy": (xl, yl), "long": v_long, "long_xy": (xg, yg),
            "lim_live": lim_live, "lim_long": lim_long, "a_live": span / lim_live, "a_long": span / lim_long,
            "ok_live": v_live <= span / lim_live + 1e-9, "ok_long": v_long <= span / lim_long + 1e-9}

    # 보 부재력 (패널 분담분)
    beams = []
    bf_d, bf_l = model.beam_forces(u_d), model.beam_forces(u_l)
    for e in FEM.EDGE_KEYS:
        if e not in bf_d:
            continue
        md, ml = np.array(bf_d[e]["m"]), np.array(bf_l[e]["m"])
        vd, vl = np.array(bf_d[e]["v"]), np.array(bf_l[e]["v"])
        m_all = np.array([a * md + b * ml for _, a, b in combos])
        v_all = np.array([a * vd + b * vl for _, a, b in combos])
        beams.append({"edge": e, "kind": FEM.EDGE_TYPES[edges[e][0]][0], "b": edges[e][1], "h": edges[e][2],
                      "m_neg": float(min(m_all.min(), 0.0)), "m_pos": float(max(m_all.max(), 0.0)),
                      "v": float(np.abs(v_all).max()), "s": bf_d[e]["s"],
                      "m": (gov[1] * md + gov[2] * ml).tolist(), "vv": (gov[1] * vd + gov[2] * vl).tolist()})

    warn = [f"{r['dir']} {r['loc']}: {r['msg']}" for r in rows if not r["ok"]]
    warn += S._phi_notes(rows, pf)
    if any(ld["type"] == "P" for ld in loads):
        warn.append("집중하중 주변의 뚫림전단(2방향 전단)은 별도 검토가 필요합니다. 집중하중 바로 아래 모멘트·전단 "
                    "최대값은 요소 크기에 따라 달라집니다.")
    fields = {"mx": comb("mx", gov[1], gov[2]), "my": comb("my", gov[1], gov[2]), "mxy": comb("mxy", gov[1], gov[2]),
              "qx": comb("qx", gov[1], gov[2]), "qy": comb("qy", gov[1], gov[2]), "dz": dz_dl, "dzl": dz_long}
    ok = all(s_["ok"] for s_ in summary) and all(s_["ok"] for s_ in shear) and defl["ok_live"] and defl["ok_long"]
    return {
        "type": "pro", "name": inp.get("name", ""), "inp": dict(inp), "lx": lx, "ly": ly, "t": t, "cc": cc,
        "fck": fck, "fy13": fy13, "fy16": fy16, "fy": fy, "bar": bar, "db": db, "phi_f": pf, "phi_v": pv,
        "wd": inp["wd"], "wl": inp["wl"], "loads": loads, "edges": edges, "corners": inp["corners"],
        "nx": nx, "ny": ny, "xs": xs, "ys": ys, "ec": ec, "tot_d": tot_d, "tot_l": tot_l, "gov": gov[0],
        "wood_armer": wa, "d_x": d_x, "d_y": d_y, "s_flex": s_flex, "s_min": s_min,
        "rows": rows, "min_row": min_row, "summary": summary, "cols": S.col_labels(cols),
        "sel_col": S.col_labels(cols).index(bar), "shear": shear, "defl": defl, "beams": beams,
        "fields": fields, "w_elastic": w_d + w_l, "warn": warn, "ok": ok,
    }


# ── 계산서 ───────────────────────────────────────────────────
def _load_text(ld):
    if ld["type"] == "P":
        return "집중", f"({ld['x']:g}, {ld['y']:g})", "kN"
    if ld["type"] == "L":
        return "라인", f"({ld['x1']:g}, {ld['y1']:g}) ~ ({ld['x2']:g}, {ld['y2']:g})", "kN/m"
    return "면", f"({ld['x1']:g}, {ld['y1']:g}) ~ ({ld['x2']:g}, {ld['y2']:g})", "kN/m²"


def build_report(r, figures=False):
    rep = Report(f"Slab Pro — {r['name']}")
    rep.h("Design Conditions")
    rep.t(f"Design Code  :  {DESIGN_CODE}", 1)
    rep.t("Material & Dim.", 0, "sub")
    rep.t(f"Concrete     fck = {r['fck']:g} N/mm²      Ec = {r['ec']:,.0f} N/mm²,  ν = {NU}", 2)
    rep.t(f"Re-bar        fy(D13↓) = {r['fy13']:g} N/mm²    fy(D16↑) = {r['fy16']:g} N/mm²", 2)
    rep.t(f"Slab Dim.  :  {r['lx'] * 1000:.0f} × {r['ly'] * 1000:.0f} × {r['t']:g} mm  (cc = {r['cc']:g} mm)", 2)
    rep.t("Edge Support", 0, "sub")
    for e in FEM.EDGE_KEYS:
        kind, bw, bh = r["edges"][e]
        beam = f"   보 {bw:g}×{bh:g} mm" if FEM.EDGE_TYPES[kind][1] else ""
        rep.t(f"{EDGE_LABEL[e]} = {FEM.EDGE_TYPES[kind][0]}{beam}", 2)
    rep.t("Corner Support  :  " + ",  ".join(f"{lbl} {'Fix' if r['corners'].get(k, True) else 'Free'}"
                                             for k, lbl, _, _ in CORNERS), 1)
    rep.t("Uniform Loads", 0, "sub")
    rep.t(f"Dead Load   Wd = {r['wd']:.2f} kN/m²        Live Load   Wl = {r['wl']:.2f} kN/m²", 2)

    if r["loads"]:
        rep.h("Point / Line / Area Loads")
        head = [["No", "종류", "위치 (m)", "고정 D", "활 L", "단위"]]
        body = []
        for n, ld in enumerate(r["loads"], 1):
            kind, pos, unit = _load_text(ld)
            body.append([str(n), kind, pos, f"{ld.get('d', 0):.2f}", f"{ld.get('l', 0):.2f}", unit])
        rep.table(head, body, [50, 70, 300, 100, 100, 90], ["c", "c", "c", "r", "r", "c"])

    rep.h("FEM Analysis")
    rep.t(f"Mesh {r['nx']} × {r['ny']}  ({r['lx'] / r['nx'] * 1000:.0f} × {r['ly'] / r['ny'] * 1000:.0f} mm),  "
          "4절점 판 요소(MITC4) + 변 보 요소", 1)
    rep.t(f"ΣD = {r['tot_d']:.1f} kN     ΣL = {r['tot_l']:.1f} kN     "
          f"U = max(1.4D, 1.2D+1.6L)  →  표시 조합 {r['gov']}", 1)
    rep.t("설계모멘트 : " + ("Wood–Armer 적용 (하부 M + |Mxy|,  상부 -M + |Mxy|)" if r["wood_armer"]
                        else "Mxx, Myy 그대로 (비틀림 모멘트 Mxy 미반영)"), 1)

    rep.h("Flexure Reinforcement")
    R._flex_table(rep, r, r["rows"], [r["min_row"]])
    rep.t(f"d(X-X) = {r['d_x']:.1f} mm,  d(Y-Y) = {r['d_y']:.1f} mm      휨철근 최대간격 min(2t, 300) = "
          f"{S._floor10(r['s_flex'])} mm", 1, "dim")
    for x in r["rows"]:
        if x["mu"] > 0.005:
            rep.t(f"{x['dir']} {x['loc']} :  Mu = {x['mu']:.2f} kN·m/m   at  {x['formula']}", 1, "dim")

    R._summary(rep, r)

    rep.h("Check Shear Strength")
    rep.t(f"Strength Reduction Factor   φ = {r['phi_v']:.3f}", 1)
    for s in r["shear"]:
        rep.t(s["label"], 0, "sub")
        rep.t(f"{s['sym']} = {s['vu']:.1f}   {'<' if s['ok'] else '>'}   φVc = {s['phi_vc']:.1f} kN/m   --->  "
              f"{'O.K.' if s['ok'] else 'N.G.'}      (at x = {s['x']:.2f}, y = {s['y']:.2f} m)", 2, "ok" if s["ok"] else "ng")

    D = r["defl"]
    rep.h("Check Deflection")
    rep.t(f"Multiplier for Long-term Deflection   ξ = {D['xi']:.2f}  ({D['months']:g} months)      "
          f"Sus. Load = D + {D['sus'] * 100:.0f}% L", 1)
    rep.t(f"Ig = {D['ig'] / 1000:,.0f} mm⁴/mm     Mcr = {D['mcr']:.2f} kN·m/m     Ma(D+L) = {D['ma_dl']:.2f} kN·m/m", 1)
    rep.t(f"균열 보정 Ig/Ie :  D {D['k_d']:.2f},   D+L {D['k_dl']:.2f},   Sus. {D['k_s']:.2f}", 1)
    rep.t(f"탄성 처짐(전단면) D+L = {D['elastic']:.2f} mm     순간처짐 Δ(D+L) = {D['inst']:.2f} mm", 1)
    rep.t(f"Short-time Deflection   Δ(D+L) - Δ(D)  = {D['live']:.2f} mm   {'<' if D['ok_live'] else '>'}   "
          f"L/{D['lim_live']:g} = {D['a_live']:.2f} mm   --->  {'O.K.' if D['ok_live'] else 'N.G.'}",
          1, "ok" if D["ok_live"] else "ng")
    rep.t(f"Long-term Deflection    ξ·Δs + ΔL = {D['long']:.2f} mm   {'<' if D['ok_long'] else '>'}   "
          f"L/{D['lim_long']:g} = {D['a_long']:.2f} mm   --->  {'O.K.' if D['ok_long'] else 'N.G.'}",
          1, "ok" if D["ok_long"] else "ng")

    if r["beams"]:
        rep.h("Edge Beam Forces")
        head = [["위치", "지지", "b × h (mm)", "M(-) (kN·m)", "M(+) (kN·m)", "V max (kN)"]]
        body = [[EDGE_LABEL[b["edge"]], b["kind"], f"{b['b']:g} × {b['h']:g}", f"{b['m_neg']:.1f}", f"{b['m_pos']:.1f}",
                 f"{b['v']:.1f}"] for b in r["beams"]]
        rep.table(head, body, [80, 130, 130, 130, 130, 130], ["c", "c", "c", "r", "r", "r"])
        rep.t("이 패널의 슬래브 하중에 의한 분담분입니다 (보 자중 제외). 연속단 보는 인접 패널 분담분을 더해야 합니다.",
              1, "dim")

    if figures:
        rep.h("FEM Results")
        for (k1, k2) in (("mx", "my"), ("qx", "qy"), ("dz", "dzl")):
            rep.fig(330, _pair_drawer(r, k1, k2), f"{k1}, {k2} 등고선")

    rep.h("Notes")
    for w in r["warn"]:
        rep.t("※ " + w, 1, "warn")
    for n in (
        "모멘트 부호: 정(+) = 하부 인장.  설계모멘트는 1.4D, 1.2D+1.6L 을 점마다 비교한 큰 값(포락)",
        "보지지: 변을 따라 보 요소(T형 유효 단면, 비틀림 강성 20%)를 두고 모서리에서 수직 지지.  "
        "연속 = 변에 직각인 회전 구속(인접 패널과 대칭), 보 강성 1/2",
        "유효깊이: 짧은 변 방향 철근을 바깥층으로 가정.  Min Bar: 수축·온도철근(KDS 14 20 50 4.6.2)",
        "처짐: 전단면 탄성 처짐에 균열 보정(Ig/Ie, 정모멘트 최대 위치의 균열단면)을 곱한 근사값.  "
        "제한은 짧은 변 길이 기준",
        f"강도감소계수: 휨 φ = {r['phi_f']:.2f} (인장지배, 변화구간은 보간),  전단 φ = {r['phi_v']:.2f}",
    ):
        rep.t("· " + n, 1, "dim")
    return rep


def _pair_drawer(r, k1, k2):
    def draw(cv, x, y, w, h):
        half = w / 2.0
        for n, key in enumerate((k1, k2)):
            _, lbl, unit, desc = next(f for f in FIELDS if f[0] == key)
            draw_contour(cv, x + n * half, y, half - 10, h, r["xs"], r["ys"], r["fields"][key], f"{lbl}  ({unit})",
                         values=True)
    return draw


# ── 등고선 ───────────────────────────────────────────────────
PALETTE = ["#1d3fd8", "#1e7be6", "#22b8e6", "#25d6c2", "#2fd27a", "#7bdc3a", "#c9e22e", "#f4d62a", "#f9a825",
           "#f57c1f", "#ee4a22", "#d81f1f"]


def band_color(v, vmin, vmax):
    if vmax - vmin < 1e-12:
        return PALETTE[len(PALETTE) // 2]
    k = int((v - vmin) / (vmax - vmin) * len(PALETTE))
    return PALETTE[max(0, min(len(PALETTE) - 1, k))]


def fmt_value(v, span):
    txt = f"{v:.0f}" if span >= 20 else (f"{v:.1f}" if span >= 2 else f"{v:.2f}")
    return txt[1:] if txt.startswith("-") and float(txt) == 0 else txt       # "-0" → "0"


def draw_legend(cv, x, y, h, vmin, vmax, font, width=14):
    n = len(PALETTE)
    bh = h / n
    for k in range(n):
        yy = y + h - (k + 1) * bh
        cv.create_rectangle(x, yy, x + width, yy + bh, fill=PALETTE[k], outline="")
    span = vmax - vmin
    for k in range(0, n + 1, 2):
        v = vmin + span * k / n
        cv.create_text(x + width + 4, y + h - k * bh, text=fmt_value(v, span), anchor="w", font=font, fill=T.INK)
    cv.create_rectangle(x, y, x + width, y + h, outline=T.INK)


def draw_contour(cv, x, y, w, h, xs, ys, field, title, values=True):
    """2D 등고선(요소별 색) + 값 — 화면 Canvas / PDF 공용"""
    F = fonts(cv)
    lx, ly = xs[-1], ys[-1]
    top, leg = 22, 58
    sc = min((w - leg - 8) / lx, (h - top - 6) / ly)
    pw, ph = lx * sc, ly * sc
    x0 = x + 4
    y0 = y + top
    vmin, vmax = float(field.min()), float(field.max())
    cv.create_text(x0, y + 10, text=f"▶ {title}", anchor="w", font=F["b"], fill=T.NAVY)
    nx, ny = len(xs) - 1, len(ys) - 1
    cw, ch = pw / nx, ph / ny
    span = vmax - vmin
    show = values and cw >= 15 and ch >= 11
    for j in range(ny):
        for i in range(nx):
            v = 0.25 * (field[j, i] + field[j, i + 1] + field[j + 1, i] + field[j + 1, i + 1])
            xa, xb = x0 + i * cw, x0 + (i + 1) * cw
            ya, yb = y0 + ph - (j + 1) * ch, y0 + ph - j * ch
            cv.create_rectangle(xa, ya, xb, yb, fill=band_color(v, vmin, vmax), outline="#FFFFFF" if show else "")
            if show:
                cv.create_text((xa + xb) / 2, (ya + yb) / 2, text=fmt_value(v, max(span, 20)), font=F["s"], fill="#111827")
    cv.create_rectangle(x0, y0, x0 + pw, y0 + ph, outline=T.INK)
    draw_legend(cv, x0 + pw + 10, y0, min(ph, 200), vmin, vmax, F["s"])
    cv.create_text(x0 + pw + 10, y0 + min(ph, 200) + 14, text=f"max {fmt_value(vmax, span)}", anchor="w", font=F["s"],
                   fill=T.MUTED)
    cv.create_text(x0 + pw + 10, y0 + min(ph, 200) + 28, text=f"min {fmt_value(vmin, span)}", anchor="w", font=F["s"],
                   fill=T.MUTED)


# ── 평면 스케치 (지지 · 하중) ────────────────────────────────
def draw_plan(cv, x, y, w, h, r, font=None, small=None):
    lx, ly = r["lx"], r["ly"]
    sc = min((w - 90) / lx, (h - 70) / ly)
    pw, ph = lx * sc, ly * sc
    x0 = x + (w - pw) / 2 + 10
    y0 = y + (h - ph) / 2 - 8
    cv.create_rectangle(x0, y0, x0 + pw, y0 + ph, fill="#FFFBEA", outline=T.INK)

    def px(xx):
        return x0 + xx * sc

    def py(yy):
        return y0 + ph - yy * sc
    geo = {"top": (x0, y0, x0 + pw, y0, 0, -1), "bottom": (x0, y0 + ph, x0 + pw, y0 + ph, 0, 1),
           "left": (x0, y0, x0, y0 + ph, -1, 0), "right": (x0 + pw, y0, x0 + pw, y0 + ph, 1, 0)}
    for e, (x1, y1, x2, y2, nx_, ny_) in geo.items():
        kind = r["edges"][e][0]
        _, beam, vert, rot = FEM.EDGE_TYPES[kind]
        if kind == "free":
            cv.create_line(x1, y1, x2, y2, fill="#9CA3AF")
            continue
        if rot:
            R._hatch_edge(cv, x1, y1, x2, y2, nx_, ny_)
        cv.create_line(x1, y1, x2, y2, fill="#2563eb" if beam else "#111827", width=3)
    for key, _, ix, iy in CORNERS:
        if r["corners"].get(key, True):
            cx, cy = x0 + ix * pw, y0 + (1 - iy) * ph
            cv.create_rectangle(cx - 4, cy - 4, cx + 4, cy + 4, fill="#dc2626", outline="#7f1d1d")
    for n, ld in enumerate(r["loads"], 1):
        if ld["type"] == "P":
            cx, cy = px(ld["x"]), py(ld["y"])
            cv.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill="#7c3aed", outline="#7c3aed")
            if small is not None:
                cv.create_text(cx + 5, cy, text=f"P{n}", anchor="w", font=small, fill="#7c3aed")
        elif ld["type"] == "L":
            cv.create_line(px(ld["x1"]), py(ld["y1"]), px(ld["x2"]), py(ld["y2"]), fill="#ea580c", width=3)
            if small is not None:
                cv.create_text((px(ld["x1"]) + px(ld["x2"])) / 2 + 4, (py(ld["y1"]) + py(ld["y2"])) / 2 - 7, text=f"L{n}",
                               anchor="w", font=small, fill="#ea580c")
        else:
            xa, xb = sorted((px(ld["x1"]), px(ld["x2"])))
            ya, yb = sorted((py(ld["y1"]), py(ld["y2"])))
            cv.create_rectangle(xa, ya, xb, yb, fill="#BBF7D0", outline="#16a34a")
            if small is not None:
                cv.create_text((xa + xb) / 2, (ya + yb) / 2, text=f"A{n}", font=small, fill="#166534")
    if font is not None:
        R._dim(cv, x0 - 26, y0, x0 - 26, y0 + ph, f"{ly * 1000:.0f}", {"n": font}, vertical=True)
        R._dim(cv, x0, y0 + ph + 30, x0 + pw, y0 + ph + 30, f"{lx * 1000:.0f}", {"n": font})
    return x0, y0, pw, ph


def sketch(r):
    def draw(cv, x, y, w, h):
        F = fonts(cv)
        draw_plan(cv, x, y, w, h - 26, r, F["n"], F["s"])
        cv.create_text(x + 8, y + h - 14, anchor="w", font=F["s"], fill=T.MUTED,
                       text="파랑 = 보,  검정 = 벽,  빗금 = 연속,  ■ = 모서리 지지")
    return draw


SKETCH_BOX = (590, 18, 290, 340)
