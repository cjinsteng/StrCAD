"""
sections.py — 단면 그림 요소 (DXF 출력과 화면 미리보기 공통, 단위 mm, 단면 왼쪽 아래 = 원점)

요소:
  {"t": "poly",  "pts": [(x, y, bulge), ...], "closed": bool, "layer": str}
  {"t": "donut", "c": (x, y), "r": 반지름, "layer": str}           # 철근 (채운 원)
  {"t": "circle","c": (x, y), "r": 반지름, "layer": str}
  {"t": "dim",   "p1": (x, y), "p2": (x, y), "base": (x, y), "angle": 0|90, "text": "350"}
예제 보 일람표(-1G1) 그림을 그대로 따름: ELE=단면/슬래브선, bar2=늑근·철근, dim=치수(S_30)
"""
from __future__ import annotations

import math

from . import model as M

L_SEC, L_BAR, L_DIM = "ELE", "bar2", "dim"


def _bar_r(dia):
    return max(6.0, 0.92 * dia)                     # D19 → 17.5 (예제와 같음)


def _xs(n, x0, x1):
    if n <= 0:
        return []
    if n == 1:
        return [(x0 + x1) / 2]
    return [x0 + i * (x1 - x0) / (n - 1) for i in range(n)]


def beam_section(B, H, slab=0.0, top="", bot="", stir=""):
    B, H = float(B or 0), float(H or 0)
    if B <= 0 or H <= 0:
        return []
    slab = float(slab or 0)
    if slab >= H:
        slab = 0
    out = []
    if slab > 0:
        out.append({"t": "poly", "pts": [(-100, H, 0), (B + 100, H, 0)], "closed": False, "layer": L_SEC})
        out.append({"t": "poly", "pts": [(-100, H - slab, 0), (0, H - slab, 0), (0, 0, 0), (B, 0, 0),
                                         (B, H - slab, 0), (B + 100, H - slab, 0)], "closed": False, "layer": L_SEC})
    else:
        out.append({"t": "poly", "pts": [(0, 0, 0), (B, 0, 0), (B, H, 0), (0, H, 0)], "closed": True, "layer": L_SEC})

    # 늑근 (양쪽 135° 갈고리가 위 가운데에서 교차) + 캡타이
    x0, x1, y0 = 40.0, B - 40.0, 40.0
    yt = H - 21.0
    hk = min(79.0, max(20.0, (x1 - x0) / 2 - 40))
    out.append({"t": "poly", "closed": False, "layer": L_BAR, "pts": [
        (x1 - 34 - hk, yt - hk, 0), (x1 - 34, yt, -0.67), (x1, yt - 14, 0), (x1, y0 + 20, -0.41421),
        (x1 - 20, y0, 0), (x0 + 20, y0, -0.41421), (x0, y0 + 20, 0), (x0, yt - 14, -0.67),
        (x0 + 34, yt, 0), (x0 + 34 + hk, yt - hk, 0)]})
    if slab > 0 or True:
        out.append({"t": "poly", "closed": False, "layer": L_BAR, "pts": [
            (B - 20, H - 200, 0), (B - 20, H - 60, 0.41421), (B - 40, H - 40, 0), (40, H - 40, 0.41421),
            (20, H - 60, 0), (20, H - 200, 0)]})

    def bars(spec, at_top):
        p = M.parse_rebar(spec) if spec else None
        if not p:
            return
        d = p["dia"]
        ins = max(70.0, 60 + d / 2)                  # 예제: 철근 중심 70 안쪽
        r = _bar_r(d)
        y1 = H - ins if at_top else ins
        for x in _xs(p["n1"], ins, B - ins):
            out.append({"t": "donut", "c": (x, y1), "r": r, "layer": L_BAR})
        if p["n2"]:
            gap = max(90.0, d + 50)                  # 예제: 2단은 1단에서 90
            y2 = y1 - gap if at_top else y1 + gap
            xs = _xs(p["n1"], ins, B - ins)
            pick = xs if p["n2"] >= len(xs) else [xs[round(i * (len(xs) - 1) / max(1, p["n2"] - 1))] for i in range(p["n2"])] \
                if p["n2"] > 1 else [xs[0]]
            for x in pick:
                out.append({"t": "donut", "c": (x, y2), "r": r, "layer": L_BAR})

    bars(top, True)
    bars(bot, False)
    out.append({"t": "dim", "p1": (0, H), "p2": (B, H), "base": (0, H + 500), "angle": 0, "text": M.norm_num(str(B))})
    xl = -100 if slab > 0 else 0
    out.append({"t": "dim", "p1": (xl, 0), "p2": (xl, H), "base": (xl - 200, 0), "angle": 90, "text": M.norm_num(str(H))})
    return out


def beam_extent(B, H):
    """그림 범위 (치수 포함): xmin, ymin, xmax, ymax."""
    return (-420.0, 0.0, float(B) + 120.0, float(H) + 620.0)


def _arrangement(n, B, D, arr=""):
    """기둥 주근 → (X면 개수, Y면 개수) (모서리 포함)."""
    import re
    m = re.match(r"^\s*(\d+)\s*[X×x*]\s*(\d+)\s*$", arr or "")
    if m:
        return max(2, int(m.group(1))), max(2, int(m.group(2)))
    if n < 4:
        return 2, 2
    half = n // 2 + 2                                # nx + ny
    best = None
    for nx in range(2, half - 1):
        ny = half - nx
        if ny < 2 or 2 * nx + 2 * ny - 4 != n and 2 * nx + 2 * ny - 4 != n + (n % 2):
            continue
        err = abs((nx - 1) / max(1, ny - 1) - B / max(1.0, D))
        if best is None or err < best[0]:
            best = (err, nx, ny)
    return (best[1], best[2]) if best else (2, max(2, half - 2))


def column_section(B, D, shape="사각", main="", hoop="", tie_x="", tie_y="", arr=""):
    B = float(B or 0)
    D = float(D or 0) if shape != "원형" else B
    if B <= 0 or D <= 0:
        return []
    out = []
    p = M.parse_rebar(main) if main else None
    dia = p["dia"] if p else 22
    r = _bar_r(dia)
    ins = 60 + dia / 2
    if shape == "원형":
        R = B / 2
        out.append({"t": "circle", "c": (R, R), "r": R, "layer": L_SEC})
        out.append({"t": "circle", "c": (R, R), "r": R - 40, "layer": L_BAR})
        if p:
            n = p["total"]
            for i in range(n):
                a = math.pi / 2 + 2 * math.pi * i / n
                out.append({"t": "donut", "c": (R + (R - ins) * math.cos(a), R + (R - ins) * math.sin(a)), "r": r,
                            "layer": L_BAR})
        out.append({"t": "dim", "p1": (0, D), "p2": (B, D), "base": (0, D + 400), "angle": 0, "text": "Ø" + M.norm_num(str(B))})
        return out
    out.append({"t": "poly", "pts": [(0, 0, 0), (B, 0, 0), (B, D, 0), (0, D, 0)], "closed": True, "layer": L_SEC})
    a = 40.0
    rr = 20.0
    out.append({"t": "poly", "closed": True, "layer": L_BAR, "pts": [
        (a + rr, a, 0), (B - a - rr, a, 0.41421), (B - a, a + rr, 0), (B - a, D - a - rr, 0.41421),
        (B - a - rr, D - a, 0), (a + rr, D - a, 0.41421), (a, D - a - rr, 0), (a, a + rr, 0.41421)]})
    hk = 90.0                                        # 135° 갈고리 (왼쪽 위)
    out.append({"t": "poly", "closed": False, "layer": L_BAR, "pts": [(a + 20, D - a, 0), (a + 20 + hk * 0.7, D - a - hk * 0.7, 0)]})
    out.append({"t": "poly", "closed": False, "layer": L_BAR, "pts": [(a, D - a - 20, 0), (a + hk * 0.7, D - a - 20 - hk * 0.7, 0)]})
    if p:
        nx, ny = _arrangement(p["total"], B, D, arr)
        xs = _xs(nx, ins, B - ins)
        ys = _xs(ny, ins, D - ins)
        pts = set()
        for x in xs:
            pts.add((round(x, 2), round(ins, 2)))
            pts.add((round(x, 2), round(D - ins, 2)))
        for y in ys:
            pts.add((round(ins, 2), round(y, 2)))
            pts.add((round(B - ins, 2), round(y, 2)))
        for c in sorted(pts):
            out.append({"t": "donut", "c": c, "r": r, "layer": L_BAR})
        tx = M.parse_rebar(tie_x) if tie_x else None
        ty = M.parse_rebar(tie_y) if tie_y else None
        inner_y = ys[1:-1]
        inner_x = xs[1:-1]
        if tx and inner_y:
            for y in [inner_y[round(i * (len(inner_y) - 1) / max(1, tx["total"] - 1))] for i in range(min(tx["total"], len(inner_y)))] \
                    if tx["total"] > 1 else [inner_y[len(inner_y) // 2]]:
                out.append({"t": "poly", "closed": False, "layer": L_BAR, "pts": [(a, y, 0), (B - a, y, 0)]})
        if ty and inner_x:
            for x in [inner_x[round(i * (len(inner_x) - 1) / max(1, ty["total"] - 1))] for i in range(min(ty["total"], len(inner_x)))] \
                    if ty["total"] > 1 else [inner_x[len(inner_x) // 2]]:
                out.append({"t": "poly", "closed": False, "layer": L_BAR, "pts": [(x, a, 0), (x, D - a, 0)]})
    out.append({"t": "dim", "p1": (0, D), "p2": (B, D), "base": (0, D + 400), "angle": 0, "text": M.norm_num(str(B))})
    out.append({"t": "dim", "p1": (0, 0), "p2": (0, D), "base": (-300, 0), "angle": 90, "text": M.norm_num(str(D))})
    return out


def wall_section(t, layer="복배근", vert="", horz="", length=1000.0):
    """벽 평단면 (길이 1m 구간)."""
    t = float(t or 0)
    if t <= 0:
        return []
    L = length
    out = [{"t": "poly", "pts": [(0, 0, 0), (L, 0, 0), (L, t, 0), (0, t, 0)], "closed": True, "layer": L_SEC}]
    pv = M.parse_spacing(vert) if vert else None
    ph = M.parse_spacing(horz) if horz else None
    cover = 40.0
    faces = [t / 2] if layer == "단배근" else [cover + (ph["dia"] if ph else 10) + (pv["dia"] if pv else 13) / 2,
                                               t - cover - (ph["dia"] if ph else 10) - (pv["dia"] if pv else 13) / 2]
    for yf in faces:
        if ph:
            yh = yf - (pv["dia"] if pv else 13) / 2 - ph["dia"] / 2 if yf < t / 2 else yf + (pv["dia"] if pv else 13) / 2 + ph["dia"] / 2
            if layer == "단배근":
                yh = yf + (pv["dia"] if pv else 13) / 2 + ph["dia"] / 2
            out.append({"t": "poly", "pts": [(0, yh, 0), (L, yh, 0)], "closed": False, "layer": L_BAR})
        if pv:
            s = pv["s"]
            x = s / 2
            while x < L:
                out.append({"t": "donut", "c": (x, yf), "r": _bar_r(pv["dia"]), "layer": L_BAR})
                x += s
    out.append({"t": "dim", "p1": (0, 0), "p2": (0, t), "base": (-250, 0), "angle": 90, "text": M.norm_num(str(t))})
    return out


def bulge_points(p0, p1, b, seg=8):
    """bulge 호 → 점 목록 (p0 제외, p1 포함)."""
    if abs(b) < 1e-9:
        return [p1]
    (x0, y0), (x1, y1) = p0, p1
    th = 4 * math.atan(b)
    dx, dy = x1 - x0, y1 - y0
    c = math.hypot(dx, dy)
    if c < 1e-9:
        return [p1]
    r = c / (2 * math.sin(th / 2))
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    h = r * math.cos(th / 2)
    nx, ny = -dy / c, dx / c
    cx, cy = mx + nx * h, my + ny * h
    a0 = math.atan2(y0 - cy, x0 - cx)
    pts = []
    for i in range(1, seg + 1):
        a = a0 + th * i / seg
        pts.append((cx + abs(r) * math.cos(a) * (1 if r > 0 else 1), cy + abs(r) * math.sin(a)))
    pts[-1] = p1
    return pts


def poly_points(pr):
    pts = pr["pts"]
    if not pts:
        return []
    out = [(pts[0][0], pts[0][1])]
    seq = list(pts) + ([pts[0]] if pr.get("closed") else [])
    for a, b in zip(seq, seq[1:]):
        out += bulge_points((a[0], a[1]), (b[0], b[1]), a[2] if len(a) > 2 else 0.0)
    return out
