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


# ── 형상 ─────────────────────────────────────────────────────
def build_verts(inp):
    """입력 → 꼭짓점 목록 [{x, y, fix, kind, bw, bh, label}]  (변 = 이 꼭짓점 → 다음 꼭짓점)"""
    if inp.get("shape", "rect") == "rect":
        lx, ly = inp["lx"], inp["ly"]
        if lx <= 0 or ly <= 0:
            raise ProInputError("Lx, Ly 는 0보다 커야 합니다.")
        e, c = inp["edges"], inp["corners"]
        pts = [(0.0, 0.0, "lb", "bottom"), (lx, 0.0, "rb", "right"), (lx, ly, "rt", "top"), (0.0, ly, "lt", "left")]
        return [{"x": x, "y": y, "fix": bool(c.get(ck, True)), "kind": e[ek][0], "bw": e[ek][1], "bh": e[ek][2],
                 "label": EDGE_LABEL[ek]} for x, y, ck, ek in pts]
    verts = [dict(v) for v in inp.get("verts", [])]
    if len(verts) < 3:
        raise ProInputError("다각형 꼭짓점을 3개 이상 입력하세요.")
    n = len(verts)
    for i, v in enumerate(verts):
        v["label"] = f"변 {i + 1}"
        w = verts[(i + 1) % n]
        if math.hypot(w["x"] - v["x"], w["y"] - v["y"]) < 1e-6:
            raise ProInputError(f"꼭짓점 {i + 1} 과 {(i + 1) % n + 1} 의 좌표가 같습니다.")
    if abs(poly_area(verts)) < 1e-6:
        raise ProInputError("다각형의 면적이 0 입니다 — 꼭짓점 좌표를 확인하세요.")
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _seg_cross(verts[i], verts[(i + 1) % n], verts[j], verts[(j + 1) % n]):
                raise ProInputError(f"변 {i + 1} 과 변 {j + 1} 이 서로 교차합니다 — 꼭짓점 순서를 확인하세요.")
    return verts


def poly_area(verts):
    n = len(verts)
    return 0.5 * sum(verts[i]["x"] * verts[(i + 1) % n]["y"] - verts[(i + 1) % n]["x"] * verts[i]["y"] for i in range(n))


def _seg_cross(p1, p2, p3, p4):
    def orient(a, b, c):
        v = (b["x"] - a["x"]) * (c["y"] - a["y"]) - (b["y"] - a["y"]) * (c["x"] - a["x"])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)
    return orient(p1, p2, p3) * orient(p1, p2, p4) < 0 and orient(p3, p4, p1) * orient(p3, p4, p2) < 0


def in_poly(x, y, verts):
    inside = False
    n = len(verts)
    for i in range(n):
        x1, y1, x2, y2 = verts[i]["x"], verts[i]["y"], verts[(i + 1) % n]["x"], verts[(i + 1) % n]["y"]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _seg_dist(x, y, a, b):
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    t = max(0.0, min(1.0, ((x - a["x"]) * dx + (y - a["y"]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - a["x"] - t * dx, y - a["y"] - t * dy)


def _grid_lines(coords, lo, hi, h):
    pts = sorted({round(c, 6) for c in coords if lo - 1e-9 <= c <= hi + 1e-9} | {round(lo, 6), round(hi, 6)})
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(round((b - a) / h)))
        out += [a + (b - a) * k / n for k in range(1, n + 1)]
    return np.array(out)


def make_mesh(verts, openings, n_short):
    """(xs, ys, active) — 격자선은 꼭짓점·개구부 좌표를 지나고, 칸 중심이 다각형 안(개구부 밖)이면 활성"""
    vx, vy = [v["x"] for v in verts], [v["y"] for v in verts]
    x0, x1, y0, y1 = min(vx), max(vx), min(vy), max(vy)
    n_short = int(max(8, min(32, n_short)))
    h = min(x1 - x0, y1 - y0) / n_short
    ox = [c for o in openings for c in (o[0], o[2])]
    oy = [c for o in openings for c in (o[1], o[3])]
    while True:
        xs, ys = _grid_lines(vx + ox, x0, x1, h), _grid_lines(vy + oy, y0, y1, h)
        if len(xs) * len(ys) <= 1500:
            break
        h *= 1.15
    xc, yc = (xs[:-1] + xs[1:]) / 2.0, (ys[:-1] + ys[1:]) / 2.0
    active = np.zeros((len(yc), len(xc)), bool)
    for j, y in enumerate(yc):
        for i, x in enumerate(xc):
            if in_poly(x, y, verts) and not any(o[0] < x < o[2] and o[1] < y < o[3] for o in openings):
                active[j, i] = True
    return xs, ys, active


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
        elif ld["type"] == "A":
            areas.append((ld["x1"], ld["y1"], ld["x2"], ld["y2"], v))
    return pts, lines, areas


def _amax(arr, xs, ys):
    """NaN 을 뺀 최댓값과 위치 (값, x, y)"""
    if arr.size == 0 or np.all(np.isnan(arr)):
        return 0.0, float(xs[0]), float(ys[0])
    j, i = np.unravel_index(int(np.nanargmax(arr)), arr.shape)
    return float(arr[j, i]), float(xs[i]), float(ys[j])


def _only(arr, sl):
    out = np.full_like(arr, np.nan)
    out[sl] = arr[sl]
    return out


# ── 뚫림전단 (KDS 14 20 22 4.11) ─────────────────────────────
def punching(ld, no, d, fck, rho, pv, t, openings, model):
    """집중하중 한 개의 2방향 전단 검토.  재하면 c1 × c2 [mm] (x × y 방향), 위험단면 = 재하면에서 d/2"""
    c1, c2 = ld.get("c1", 0.0), ld.get("c2", 0.0)
    pu = max(1.4 * ld.get("d", 0.0), 1.2 * ld.get("d", 0.0) + 1.6 * ld.get("l", 0.0))
    hx, hy = (c1 + d) / 2000.0, (c2 + d) / 2000.0            # 위험단면 반폭 [m]
    cx, cy = ld["x"], ld["y"]
    sides = [((cx - hx, cy - hy), (cx + hx, cy - hy)), ((cx + hx, cy - hy), (cx + hx, cy + hy)),
             ((cx + hx, cy + hy), (cx - hx, cy + hy)), ((cx - hx, cy + hy), (cx - hx, cy - hy))]
    # 개구부: 재하면에서 10t 이내이면, 하중 중심에서 개구부를 바라보는 각도 범위의 둘레는 무효
    blocked = []
    for o in openings:
        gap = math.hypot(max(o[0] - (cx + c1 / 2000.0), (cx - c1 / 2000.0) - o[2], 0.0),
                         max(o[1] - (cy + c2 / 2000.0), (cy - c2 / 2000.0) - o[3], 0.0))
        if gap <= 10.0 * t / 1000.0:
            angs = [math.atan2(yy - cy, xx - cx) for xx in (o[0], o[2]) for yy in (o[1], o[3])]
            ref = angs[0]
            rel = [((a - ref + math.pi) % (2 * math.pi)) - math.pi for a in angs]
            blocked.append((ref + min(rel), ref + max(rel)))

    def is_blocked(x, y):
        ang = math.atan2(y - cy, x - cx)
        for lo, hi in blocked:
            for k in (-2 * math.pi, 0.0, 2 * math.pi):
                if lo - 1e-9 <= ang + k <= hi + 1e-9:
                    return True
        return False
    b0, lost_sides, n_op = 0.0, 0, 0
    nseg = 60
    for (xa, ya), (xb, yb) in sides:
        seg = math.hypot(xb - xa, yb - ya) / nseg
        outside = 0
        for k in range(nseg):
            x, y = xa + (xb - xa) * (k + 0.5) / nseg, ya + (yb - ya) * (k + 0.5) / nseg
            if model.locate(x, y) is None:
                outside += 1
            elif is_blocked(x, y):
                n_op += 1
            else:
                b0 += seg
        if outside > nseg // 2:
            lost_sides += 1
    b0 *= 1000.0                                             # mm
    alpha_s = 1.0 if lost_sides == 0 else (1.33 if lost_sides == 1 else 2.0)
    pos = {1.0: "내부", 1.33: "외부(변)", 2.0: "모서리"}[alpha_s]
    out = {"no": no, "x": cx, "y": cy, "c1": c1, "c2": c2, "pu": pu, "d": d, "b0": b0, "alpha_s": alpha_s, "pos": pos,
           "rho": rho, "opening": n_op > 0}
    if b0 <= 1e-6:
        out.update(vc=0.0, phi_vc=0.0, ok=False, ks=0, kbo=0, cu=0, cot=0, fte=0)
        return out
    ks = min(max((300.0 / d) ** 0.25, 0.75), 1.1)
    kbo = min(4.0 / math.sqrt(alpha_s * b0 / d), 1.25)
    fte = 0.2 * math.sqrt(fck)
    fcc = 2.0 / 3.0 * fck
    cot = math.sqrt(fte * (fte + fcc)) / fte
    cu = d * (25.0 * math.sqrt(rho / fck) - 300.0 * rho / fck)
    vc = ks * kbo * fte * cot * cu / d                       # λ = 1.0
    vn = min(vc * b0 * d, 0.58 * fck * b0 * cu) / 1000.0     # kN
    out.update(ks=ks, kbo=kbo, fte=fte, cot=cot, cu=cu, vc=vc, phi_vc=pv * vn, ok=pu <= pv * vn + 1e-9)
    return out


def calc_pro(inp):
    """inp: name, shape 'rect'|'poly', t, cc, fck, fy13, fy16, wd, wl, bar, phi_f, phi_v,
            rect: lx, ly, edges {top|bottom|left|right: (kind, bw mm, bh mm)}, corners {lt|lb|rt|rb: bool}
            poly: verts [{x, y, fix, kind, bw, bh}]  (변 = 이 점 → 다음 점)
            loads [ {type 'P'|'L'|'A'|'O'(개구부), 좌표…, d, l, (P) c1, c2 mm} ],
            mesh, wood_armer, months, lim_live, lim_long, sus_live"""
    try:
        fck, fy13, fy16, fy, t, cc, bar, db = S._common(inp)
    except S.SlabInputError as e:
        raise ProInputError(str(e)) from None
    pf, pv = inp.get("phi_f", S.PHI_F), inp.get("phi_v", S.PHI_V)
    shape = inp.get("shape", "rect")
    verts = build_verts(inp)
    vx, vy = [v["x"] for v in verts], [v["y"] for v in verts]
    lx, ly = max(vx) - min(vx), max(vy) - min(vy)
    if lx <= 0 or ly <= 0:
        raise ProInputError("슬래브 크기를 확인하세요.")
    if max(lx, ly) / min(lx, ly) > 6:
        raise ProInputError("변장비가 너무 큽니다 (6 이하로 입력).")
    all_loads = inp.get("loads", [])
    openings = []
    for ld in all_loads:
        if ld["type"] == "O":
            o = (min(ld["x1"], ld["x2"]), min(ld["y1"], ld["y2"]), max(ld["x1"], ld["x2"]), max(ld["y1"], ld["y2"]))
            if o[2] - o[0] < 0.05 or o[3] - o[1] < 0.05:
                raise ProInputError("개구부 크기가 너무 작습니다 (한 변 50 mm 이상).")
            openings.append(o)
    loads = [ld for ld in all_loads if ld["type"] != "O"]
    xs, ys, active = make_mesh(verts, openings, inp.get("mesh", 16))
    ec = S.ec_of(fck)
    try:
        model = FEM.SlabModel(xs, ys, active, t / 1000.0, ec * 1000.0, NU)
    except FEM.FemError as e:
        raise ProInputError(str(e)) from None
    for n, ld in enumerate(loads, 1):
        if ld["type"] == "P" and model.locate(ld["x"], ld["y"]) is None:
            raise ProInputError(f"추가 하중 {n}번: 위치 ({ld['x']:g}, {ld['y']:g}) 가 슬래브 밖(또는 개구부)입니다.")
    nv = len(verts)
    xc, yc = (xs[:-1] + xs[1:]) / 2.0, (ys[:-1] + ys[1:]) / 2.0
    try:
        for sd in model.boundary_sides():
            oi, oj = sd["out"]
            if 0 <= oi < len(xc) and 0 <= oj < len(yc) and in_poly(xc[oi], yc[oj], verts):
                continue                                           # 개구부 둘레 = 자유단
            mx_, my_ = sd["mid"]
            k = min(range(nv), key=lambda q: _seg_dist(mx_, my_, verts[q], verts[(q + 1) % nv]))
            v, w = verts[k], verts[(k + 1) % nv]
            length = math.hypot(w["x"] - v["x"], w["y"] - v["y"])
            pos = ((mx_ - v["x"]) * (w["x"] - v["x"]) + (my_ - v["y"]) * (w["y"] - v["y"])) / length
            model.support_side(sd, v["kind"], v["bw"] / 1000.0, v["bh"] / 1000.0, edge_id=k, pos=pos)
        for v in verts:
            if v["fix"]:
                model.fix_w(v["x"], v["y"])
        f_d = model.load_vector(inp["wd"], *_split_loads(loads, "d"))
        f_l = model.load_vector(inp["wl"], *_split_loads(loads, "l"))
        u_d, u_l = model.solve([f_d, f_l])
    except FEM.FemError as e:
        raise ProInputError(str(e)) from None
    r_d, r_l = model.recover(u_d), model.recover(u_l)
    tot_d, tot_l = float(f_d[0::3].sum()), float(f_l[0::3].sum())
    slanted = any(abs(verts[i]["x"] - verts[(i + 1) % nv]["x"]) > 1e-6 and
                  abs(verts[i]["y"] - verts[(i + 1) % nv]["y"]) > 1e-6 for i in range(nv))

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
    rows, pos_rows = [], {}

    def add(direction, loc, arr, d, is_pos=False):
        mu, x, y = _amax(arr, xs, ys)
        rows.append(S._row(direction, loc, mu, f"x = {x:.2f}, y = {y:.2f} m", d, fck, fy, fy13, fy16, s_flex, cols, pf))
        if is_pos:
            pos_rows[direction] = rows[-1]
        return mu

    if shape == "rect":
        e1 = add("X-X Dir.", "좌단 Left", _only(env["xt"], np.s_[:, 0]), d_x)
        add("X-X Dir.", "중앙 Cent.", env["xb"], d_x, True)
        e2 = add("X-X Dir.", "우단 Right", _only(env["xt"], np.s_[:, -1]), d_x)
        mu = _amax(_only(env["xt"], np.s_[:, 1:-1]), xs, ys)[0]
        if mu > max(1.05 * max(e1, e2), 0.5):
            add("X-X Dir.", "내부 상부 Top", _only(env["xt"], np.s_[:, 1:-1]), d_x)
        e1 = add("Y-Y Dir.", "상단 Upper", _only(env["yt"], np.s_[-1, :]), d_y)
        add("Y-Y Dir.", "중앙 Cent.", env["yb"], d_y, True)
        e2 = add("Y-Y Dir.", "하단 Lower", _only(env["yt"], np.s_[0, :]), d_y)
        mu = _amax(_only(env["yt"], np.s_[1:-1, :]), xs, ys)[0]
        if mu > max(1.05 * max(e1, e2), 0.5):
            add("Y-Y Dir.", "내부 상부 Top", _only(env["yt"], np.s_[1:-1, :]), d_y)
    else:
        add("X-X Dir.", "상부 Top", env["xt"], d_x)
        add("X-X Dir.", "하부 Bottom", env["xb"], d_x, True)
        add("Y-Y Dir.", "상부 Top", env["yt"], d_y)
        add("Y-Y Dir.", "하부 Bottom", env["yb"], d_y, True)

    as_by_fy = {f: S.rho_min(f) * 1000.0 * t for f in {fy13, fy16}}
    min_row = {"dir": "", "loc": "Min Bar", "mu": None, "rho": S.rho_min(fy), "as_req": S.rho_min(fy) * 1000.0 * t,
               "sp": S.spacings(as_by_fy, fy13, fy16, s_min, cols), "s_max": s_min, "ok": True, "d": d_out}
    summary = S._summary(rows, min_row, bar, fck, fy, cols, pf)

    # 전단
    shear = []
    for key, lbl, sym, d in (("qx", "X-X Direction Shear", "Vux", d_x), ("qy", "Y-Y Direction Shear", "Vuy", d_y)):
        vu, x, y = _amax(env[key], xs, ys)
        pvc = S.phi_vc(d, fck, pv=pv)
        shear.append({"label": lbl, "sym": sym, "vu": vu, "x": x, "y": y, "phi_vc": pvc, "d": d, "ok": vu <= pvc + 1e-9})

    # 뚫림전단 — 재하면적(c1, c2)을 입력한 집중하중만
    d_avg = (d_x + d_y) / 2.0
    as_bot = [s_["as_prov"] for s_ in summary if s_["as_prov"] and ("Cent" in s_["loc"] or "Bottom" in s_["loc"])]
    rho_p = min(max(sum(as_bot) / len(as_bot) / (1000.0 * d_avg) if as_bot else 0.0, 0.005), 0.03)
    punch = [punching(ld, n, d_avg, fck, rho_p, pv, t, openings, model)
             for n, ld in enumerate(loads, 1) if ld["type"] == "P" and ld.get("c1", 0) > 0 and ld.get("c2", 0) > 0]

    # 처짐 (사용하중)
    ig = 1000.0 * t ** 3 / 12.0
    mcr = 0.63 * math.sqrt(fck) * ig / (t / 2.0) / 1e6
    n_mod = S.ES / ec
    sus = inp.get("sus_live", 0.5)

    def crack_factor(a, b):
        """하중 수준 (a·D + b·L) 에서 Ig/Ie — 정모멘트가 가장 큰 방향의 균열단면 기준"""
        ax = float(np.nanmax(a * r_d["mx"] + b * r_l["mx"]))
        ay = float(np.nanmax(a * r_d["my"] + b * r_l["my"]))
        ma, row, d = (ax, pos_rows["X-X Dir."], d_x) if ax >= ay else (ay, pos_rows["Y-Y Dir."], d_y)
        icr = S.i_cracked(max(row["as_req"], min_row["as_req"]), d, n_mod)
        return ig / S.i_eff(mcr, ma, ig, icr), ma
    k_d, _ = crack_factor(1, 0)
    k_dl, ma_dl = crack_factor(1, 1)
    k_s, _ = crack_factor(1, sus)
    w_d, w_l = r_d["w"], r_l["w"]
    dz_d = k_d * w_d
    dz_dl = k_dl * (w_d + w_l)
    dz_live = dz_dl - dz_d
    xi = S.xi_of(inp.get("months", 60))
    dz_long = xi * k_s * (w_d + sus * w_l) + dz_live
    span = min(lx, ly) * 1000.0
    lim_live, lim_long = inp.get("lim_live", 360.0), inp.get("lim_long", 480.0)
    v_live, xl, yl = _amax(dz_live, xs, ys)
    v_long, xg, yg = _amax(dz_long, xs, ys)
    defl = {"xi": xi, "months": inp.get("months", 60), "sus": sus, "ec": ec, "ig": ig, "mcr": mcr,
            "k_d": k_d, "k_dl": k_dl, "k_s": k_s, "ma_dl": ma_dl,
            "elastic": float(np.nanmax(w_d + w_l)), "inst": float(np.nanmax(dz_dl)),
            "live": v_live, "live_xy": (xl, yl), "long": v_long, "long_xy": (xg, yg),
            "lim_live": lim_live, "lim_long": lim_long, "a_live": span / lim_live, "a_long": span / lim_long,
            "ok_live": v_live <= span / lim_live + 1e-9, "ok_long": v_long <= span / lim_long + 1e-9}

    # 보 부재력 (패널 분담분)
    beams = []
    bf_d, bf_l = model.beam_forces(u_d), model.beam_forces(u_l)
    for k in sorted(bf_d):
        md, ml = np.array(bf_d[k]["m"]), np.array(bf_l[k]["m"])
        vd, vl = np.array(bf_d[k]["v"]), np.array(bf_l[k]["v"])
        m_all = np.array([a * md + b * ml for _, a, b in combos])
        v_all = np.array([a * vd + b * vl for _, a, b in combos])
        v = verts[k]
        beams.append({"edge": v["label"], "kind": FEM.EDGE_TYPES[v["kind"]][0], "b": v["bw"], "h": v["bh"],
                      "m_neg": float(min(m_all.min(), 0.0)), "m_pos": float(max(m_all.max(), 0.0)),
                      "v": float(np.abs(v_all).max())})

    warn = [f"{r['dir']} {r['loc']}: {r['msg']}" for r in rows if not r["ok"]]
    warn += S._phi_notes(rows, pf)
    n_p = sum(1 for ld in loads if ld["type"] == "P")
    if n_p > len(punch):
        warn.append(f"집중하중 {n_p - len(punch)}개는 재하면적(c1, c2)이 0 이라 뚫림전단을 검토하지 않았습니다.")
    if n_p:
        warn.append("집중하중 바로 아래의 모멘트·전단 최대값은 요소 크기에 따라 달라집니다.")
    if slanted:
        warn.append("사선 변은 계단 모양 격자로 근사했습니다 — 사선 변 근처 값과 사선 보지지는 정확도가 떨어집니다.")
    if shape == "poly" or openings:
        warn.append("오목한 모서리(다각형 안쪽 꺾임, 개구부 모서리)에는 모멘트가 집중되며 최대값이 요소 크기에 따라 달라집니다.")
    fields = {"mx": comb("mx", gov[1], gov[2]), "my": comb("my", gov[1], gov[2]), "mxy": comb("mxy", gov[1], gov[2]),
              "qx": comb("qx", gov[1], gov[2]), "qy": comb("qy", gov[1], gov[2]), "dz": dz_dl, "dzl": dz_long}
    ok = (all(s_["ok"] for s_ in summary) and all(s_["ok"] for s_ in shear) and defl["ok_live"] and defl["ok_long"]
          and all(p_["ok"] for p_ in punch))
    return {
        "type": "pro", "shape": shape, "name": inp.get("name", ""), "inp": dict(inp), "lx": lx, "ly": ly, "t": t,
        "cc": cc, "fck": fck, "fy13": fy13, "fy16": fy16, "fy": fy, "bar": bar, "db": db, "phi_f": pf, "phi_v": pv,
        "wd": inp["wd"], "wl": inp["wl"], "loads": loads, "openings": openings, "verts": verts,
        "area": float(sum((xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j]) for j, i in zip(*np.nonzero(active)))),
        "nx": len(xs) - 1, "ny": len(ys) - 1, "n_elem": int(active.sum()), "xs": xs, "ys": ys, "active": active,
        "ec": ec, "tot_d": tot_d, "tot_l": tot_l, "gov": gov[0],
        "wood_armer": wa, "d_x": d_x, "d_y": d_y, "s_flex": s_flex, "s_min": s_min,
        "rows": rows, "min_row": min_row, "summary": summary, "cols": S.col_labels(cols),
        "sel_col": S.col_labels(cols).index(bar), "shear": shear, "punch": punch, "defl": defl, "beams": beams,
        "fields": fields, "w_elastic": w_d + w_l, "warn": warn, "ok": ok,
    }


# ── 계산서 ───────────────────────────────────────────────────
def _load_text(ld):
    if ld["type"] == "O":
        return "개구부", f"({ld['x1']:g}, {ld['y1']:g}) ~ ({ld['x2']:g}, {ld['y2']:g})", ""
    if ld["type"] == "P":
        c = f"   재하면 {ld['c1']:g}×{ld['c2']:g}" if ld.get("c1", 0) > 0 and ld.get("c2", 0) > 0 else ""
        return "집중", f"({ld['x']:g}, {ld['y']:g}){c}", "kN"
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
    verts = r["verts"]
    if r["shape"] == "rect":
        rep.t(f"Slab Dim.  :  {r['lx'] * 1000:.0f} × {r['ly'] * 1000:.0f} × {r['t']:g} mm  (cc = {r['cc']:g} mm)", 2)
        rep.t("Edge Support", 0, "sub")
        for v in (verts[2], verts[0], verts[3], verts[1]):            # 상 · 하 · 좌 · 우
            beam = f"   보 {v['bw']:g}×{v['bh']:g} mm" if FEM.EDGE_TYPES[v["kind"]][1] else ""
            rep.t(f"{v['label']} = {FEM.EDGE_TYPES[v['kind']][0]}{beam}", 2)
        rep.t("Corner Support  :  " + ",  ".join(f"{lbl} {'Fix' if v['fix'] else 'Free'}" for lbl, v in
                                                 (("좌측상부", verts[3]), ("좌측하부", verts[0]),
                                                  ("우측상부", verts[2]), ("우측하부", verts[1]))), 1)
    else:
        rep.t(f"Slab  :  다각형 {len(verts)}점,  면적 {r['area']:.2f} m²,  외곽 {r['lx'] * 1000:.0f} × {r['ly'] * 1000:.0f} mm,"
              f"  T = {r['t']:g} mm  (cc = {r['cc']:g} mm)", 2)
    rep.t("Uniform Loads", 0, "sub")
    rep.t(f"Dead Load   Wd = {r['wd']:.2f} kN/m²        Live Load   Wl = {r['wl']:.2f} kN/m²", 2)
    if r["shape"] == "poly":
        rep.h("Polygon · Edge Support")
        head = [["No", "x (m)", "y (m)", "꼭짓점 지지", "변 (→ 다음 점) 지지", "보 b × h (mm)"]]
        body = [[str(i + 1), f"{v['x']:g}", f"{v['y']:g}", "Fix" if v["fix"] else "Free", FEM.EDGE_TYPES[v["kind"]][0],
                 f"{v['bw']:g} × {v['bh']:g}" if FEM.EDGE_TYPES[v["kind"]][1] else "-"] for i, v in enumerate(verts)]
        rep.table(head, body, [50, 100, 100, 120, 190, 150], ["c", "r", "r", "c", "c", "c"])
    if r["openings"]:
        rep.t("Openings  :  " + ",   ".join(f"({o[0]:g}, {o[1]:g}) ~ ({o[2]:g}, {o[3]:g})" for o in r["openings"])
              + "   (둘레 자유단)", 1)

    if r["loads"]:
        rep.h("Point / Line / Area Loads")
        head = [["No", "종류", "위치 (m)", "고정 D", "활 L", "단위"]]
        body = []
        for n, ld in enumerate(r["loads"], 1):
            kind, pos, unit = _load_text(ld)
            body.append([str(n), kind, pos, f"{ld.get('d', 0):.2f}", f"{ld.get('l', 0):.2f}", unit])
        rep.table(head, body, [50, 70, 300, 100, 100, 90], ["c", "c", "c", "r", "r", "c"])

    rep.h("FEM Analysis")
    rep.t(f"Mesh {r['nx']} × {r['ny']} 격자,  요소 {r['n_elem']}개  (약 {r['lx'] / r['nx'] * 1000:.0f} × "
          f"{r['ly'] / r['ny'] * 1000:.0f} mm),  4절점 판 요소(MITC4) + 변 보 요소", 1)
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

    if r["punch"]:
        rep.h("Check Punching Shear")
        head = [["No", "위치 (m)", "c1 × c2", "b0", "위치", "vc", "Vu", "φVc", "Check"],
                ["", "", "(mm)", "(mm)", "(αs)", "(MPa)", "(kN)", "(kN)", ""]]
        body = []
        for p in r["punch"]:
            body.append([f"P{p['no']}", f"({p['x']:g}, {p['y']:g})", f"{p['c1']:g} × {p['c2']:g}",
                         f"{p['b0']:.0f}" + ("*" if p["opening"] else ""), f"{p['pos']} ({p['alpha_s']:g})",
                         f"{p['vc']:.2f}", f"{p['pu']:.1f}", f"{p['phi_vc']:.1f}", R._okng(p["ok"])])
        rep.table(head, body, [50, 110, 110, 80, 130, 80, 80, 90, 70], ["c", "c", "c", "r", "c", "r", "r", "r", "c"])
        p = r["punch"][0]
        rep.t(f"d = {p['d']:.1f} mm (양방향 평균),  ρ = {p['rho']:.4f},  위험단면 = 재하면에서 d/2,  Vu = 계수 집중하중", 1, "dim")
        rep.t(f"vc = ks·kbo·fte·cotψ·(cu/d)     [P{p['no']}: ks = {p['ks']:.2f}, kbo = {p['kbo']:.2f}, fte = {p['fte']:.2f}, "
              f"cotψ = {p['cot']:.2f}, cu = {p['cu']:.1f} mm]", 1, "dim")
        if any(q["opening"] for q in r["punch"]):
            rep.t("* 개구부(10t 이내)를 바라보는 방향의 둘레를 뺀 값", 1, "dim")

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
        body = [[b["edge"], b["kind"], f"{b['b']:g} × {b['h']:g}", f"{b['m_neg']:.1f}", f"{b['m_pos']:.1f}",
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
        "뚫림전단: KDS 14 20 22 4.11 (재하면적을 입력한 집중하중만).  자유단·개구부 쪽 둘레는 제외, "
        "위험단면 안쪽 등분포 하중은 빼지 않음(안전측)",
        "다각형·개구부: 격자선을 꼭짓점·개구부 좌표에 맞춰 나눔.  개구부 둘레는 자유단",
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
                         values=True, active=r["active"])
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


def draw_contour(cv, x, y, w, h, xs, ys, field, title, values=True, active=None):
    """2D 등고선(요소별 색) + 값 — 화면 Canvas / PDF 공용.  active: 활성 칸 (없으면 전부)"""
    F = fonts(cv)
    lx, ly = xs[-1] - xs[0], ys[-1] - ys[0]
    top, leg = 22, 58
    sc = min((w - leg - 8) / lx, (h - top - 6) / ly)
    pw, ph = lx * sc, ly * sc
    x0 = x + 4
    y0 = y + top
    vmin, vmax = float(np.nanmin(field)), float(np.nanmax(field))
    cv.create_text(x0, y + 10, text=f"▶ {title}", anchor="w", font=F["b"], fill=T.NAVY)
    nx, ny = len(xs) - 1, len(ys) - 1
    span = vmax - vmin
    show = values and (pw / nx) >= 15 and (ph / ny) >= 11
    px = x0 + (np.asarray(xs) - xs[0]) * sc
    py = y0 + ph - (np.asarray(ys) - ys[0]) * sc
    for j in range(ny):
        for i in range(nx):
            if active is not None and not active[j, i]:
                continue
            v = 0.25 * (field[j, i] + field[j, i + 1] + field[j + 1, i] + field[j + 1, i + 1])
            cv.create_rectangle(px[i], py[j + 1], px[i + 1], py[j], fill=band_color(v, vmin, vmax),
                                outline="#FFFFFF" if show else "")
            if show:
                cv.create_text((px[i] + px[i + 1]) / 2, (py[j] + py[j + 1]) / 2, text=fmt_value(v, max(span, 20)),
                               font=F["s"], fill="#111827")
    if active is None or active.all():
        cv.create_rectangle(x0, y0, x0 + pw, y0 + ph, outline=T.INK)
    else:                                               # 활성 영역의 외곽선
        for j in range(ny):
            for i in range(nx):
                if not active[j, i]:
                    continue
                if j == 0 or not active[j - 1, i]:
                    cv.create_line(px[i], py[j], px[i + 1], py[j], fill=T.INK)
                if j == ny - 1 or not active[j + 1, i]:
                    cv.create_line(px[i], py[j + 1], px[i + 1], py[j + 1], fill=T.INK)
                if i == 0 or not active[j, i - 1]:
                    cv.create_line(px[i], py[j], px[i], py[j + 1], fill=T.INK)
                if i == nx - 1 or not active[j, i + 1]:
                    cv.create_line(px[i + 1], py[j], px[i + 1], py[j + 1], fill=T.INK)
    draw_legend(cv, x0 + pw + 10, y0, min(ph, 200), vmin, vmax, F["s"])
    cv.create_text(x0 + pw + 10, y0 + min(ph, 200) + 14, text=f"max {fmt_value(vmax, span)}", anchor="w", font=F["s"],
                   fill=T.MUTED)
    cv.create_text(x0 + pw + 10, y0 + min(ph, 200) + 28, text=f"min {fmt_value(vmin, span)}", anchor="w", font=F["s"],
                   fill=T.MUTED)


# ── 평면 스케치 (형상 · 지지 · 하중 · 개구부) ────────────────
def draw_plan(cv, x, y, w, h, r, font=None, small=None):
    """r: verts, openings, loads 를 가진 dict (calc_pro 결과 또는 미리보기용)"""
    verts = r["verts"]
    vx, vy = [v["x"] for v in verts], [v["y"] for v in verts]
    x_min, y_min = min(vx), min(vy)
    lx, ly = max(vx) - x_min, max(vy) - y_min
    sc = min((w - 90) / lx, (h - 70) / ly)
    pw, ph = lx * sc, ly * sc
    x0 = x + (w - pw) / 2 + 10
    y0 = y + (h - ph) / 2 - 8

    def px(xx):
        return x0 + (xx - x_min) * sc

    def py(yy):
        return y0 + ph - (yy - y_min) * sc
    n = len(verts)
    cv.create_polygon([(px(v["x"]), py(v["y"])) for v in verts], fill="#FFFBEA", outline="")
    for o in r.get("openings", []):
        cv.create_rectangle(px(o[0]), py(o[3]), px(o[2]), py(o[1]), fill="white", outline="#6B7280")
        cv.create_line(px(o[0]), py(o[3]), px(o[2]), py(o[1]), fill="#9CA3AF")
        cv.create_line(px(o[0]), py(o[1]), px(o[2]), py(o[3]), fill="#9CA3AF")
    sign = 1.0 if poly_area(verts) > 0 else -1.0
    for i, v in enumerate(verts):
        w_ = verts[(i + 1) % n]
        x1, y1, x2, y2 = px(v["x"]), py(v["y"]), px(w_["x"]), py(w_["y"])
        _, beam, vert, rot = FEM.EDGE_TYPES[v["kind"]]
        length = math.hypot(x2 - x1, y2 - y1) or 1.0
        nx_, ny_ = sign * (y2 - y1) / length, -sign * (x2 - x1) / length       # 화면 좌표계의 바깥쪽 법선
        if v["kind"] == "free":
            cv.create_line(x1, y1, x2, y2, fill="#9CA3AF")
        else:
            if rot:
                m = max(int(length // 6), 1)
                for k in range(m + 1):
                    qx, qy = x1 + (x2 - x1) * k / m, y1 + (y2 - y1) * k / m
                    cv.create_line(qx, qy, qx + nx_ * 7 + (x2 - x1) / length * 4, qy + ny_ * 7 + (y2 - y1) / length * 4,
                                   fill="#d946ef")
            cv.create_line(x1, y1, x2, y2, fill="#2563eb" if beam else "#111827", width=3)
        if r.get("shape") == "poly" and small is not None:
            cv.create_text((x1 + x2) / 2 - nx_ * 9, (y1 + y2) / 2 - ny_ * 9, text=f"{i + 1}", font=small, fill=T.MUTED)
    for i, v in enumerate(verts):
        cx, cy = px(v["x"]), py(v["y"])
        if v["fix"]:
            cv.create_rectangle(cx - 4, cy - 4, cx + 4, cy + 4, fill="#dc2626", outline="#7f1d1d")
        else:
            cv.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill="#6B7280", outline="#6B7280")
    for k, ld in enumerate(r.get("loads", []), 1):
        if ld["type"] == "P":
            cx, cy = px(ld["x"]), py(ld["y"])
            if ld.get("c1", 0) > 0 and ld.get("c2", 0) > 0:
                cv.create_rectangle(cx - ld["c1"] / 2000.0 * sc, cy - ld["c2"] / 2000.0 * sc,
                                    cx + ld["c1"] / 2000.0 * sc, cy + ld["c2"] / 2000.0 * sc, outline="#7c3aed")
            cv.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill="#7c3aed", outline="#7c3aed")
            if small is not None:
                cv.create_text(cx + 6, cy, text=f"P{k}", anchor="w", font=small, fill="#7c3aed")
        elif ld["type"] == "L":
            cv.create_line(px(ld["x1"]), py(ld["y1"]), px(ld["x2"]), py(ld["y2"]), fill="#ea580c", width=3)
            if small is not None:
                cv.create_text((px(ld["x1"]) + px(ld["x2"])) / 2 + 4, (py(ld["y1"]) + py(ld["y2"])) / 2 - 7, text=f"L{k}",
                               anchor="w", font=small, fill="#ea580c")
        elif ld["type"] == "A":
            xa, xb = sorted((px(ld["x1"]), px(ld["x2"])))
            ya, yb = sorted((py(ld["y1"]), py(ld["y2"])))
            cv.create_rectangle(xa, ya, xb, yb, fill="#BBF7D0", outline="#16a34a")
            if small is not None:
                cv.create_text((xa + xb) / 2, (ya + yb) / 2, text=f"A{k}", font=small, fill="#166534")
    if font is not None:
        R._dim(cv, x0 - 26, y0, x0 - 26, y0 + ph, f"{ly * 1000:.0f}", {"n": font}, vertical=True)
        R._dim(cv, x0, y0 + ph + 30, x0 + pw, y0 + ph + 30, f"{lx * 1000:.0f}", {"n": font})
    return x0, y0, pw, ph


def sketch(r):
    def draw(cv, x, y, w, h):
        F = fonts(cv)
        draw_plan(cv, x, y, w, h - 26, r, F["n"], F["s"])
        cv.create_text(x + 8, y + h - 14, anchor="w", font=F["s"], fill=T.MUTED,
                       text="파랑 = 보,  검정 = 벽,  빗금 = 연속,  ■ = 수직 지지")
    return draw


SKETCH_BOX = (590, 18, 290, 340)
