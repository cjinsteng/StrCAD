"""검측점 · 스케치 → DXF (AutoCAD 2010, UTF-8 — 한글 그대로). 휴대폰 앱 '📐 DXF로 내보내기'와 같은 레이어.

  검측  SV-SEC · SV-CRACK-<종류(CR, PW …)> · SV-LOAD · SV-ETC · (추가 용도 SV-U1 …)   + 각 -TXT (내용 글자)
  스케치 SK-<종류>-<색>  (SK-BEAM-BLUE, SK-COLUMN-RED, SK-WALL-…, SK-AXIS-… , SK-FREE-…, SK-DIM-…, SK-TEXT-…)
        SK-AXIS-GAP(축 간격) · SK-SIGN(작성자)
  바탕  BASE-GRID · BASE-LINE · BASE-COLUMN · BASE-GIRDER · BASE-BEAM · BASE-WALL · BASE-NAME
"""
from __future__ import annotations

import math

from . import survey as SV

COLOR_NAME = {"#e11d48": "RED", "#f28c28": "ORANGE", "#eab308": "YELLOW", "#16a34a": "GREEN", "#2563eb": "BLUE",
              "#7c3aed": "PURPLE", "#111827": "BLACK", "#ec4899": "PINK"}
COLOR_ACI = {"RED": 1, "ORANGE": 30, "YELLOW": 2, "GREEN": 3, "BLUE": 5, "PURPLE": 190, "BLACK": 7, "PINK": 221}
SK_KIND = {"beam": "BEAM", "column": "COLUMN", "wall": "WALL", "axis": "AXIS", "free": "FREE", "dim": "DIM", "text": "TEXT"}
SV_CODE = {"부재검측": "SEC", "균열검토": "CRACK", "하중조사": "LOAD", "기타": "ETC"}


def _rgb(hexs):
    h = (hexs or "").lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _aci(hexs):
    from ezdxf import colors
    c = _rgb(hexs)
    if not c:
        return 7
    if max(c) < 60:
        return 7
    try:
        return min(range(1, 256), key=lambda i: sum((a - b) ** 2 for a, b in zip(colors.aci2rgb(i), c)))
    except Exception:  # noqa: BLE001
        return 7


def _cname(hexs):
    return COLOR_NAME.get((hexs or "").lower()) or ("C" + (hexs or "COLOR").lstrip("#").upper())


def _up(ang):
    return ang + 180 if ang > 90 or ang < -90 else ang


def axis_gaps(sketches, off):
    """평행한 축 사이 간격 [(p1, p2, d)] (휴대폰 화면 표시와 같은 방식)."""
    groups = []
    for a in sketches:
        if a.get("kind") != "axis" or len(a.get("pts") or []) < 4:
            continue
        p = a["pts"]
        L = math.hypot(p[2] - p[0], p[3] - p[1])
        if L < 1:
            continue
        ux, uy = (p[2] - p[0]) / L, (p[3] - p[1]) / L
        if ux < -1e-9 or (abs(ux) < 1e-9 and uy < 0):
            ux, uy = -ux, -uy
        g = next((G for G in groups if abs(G["ux"] * uy - G["uy"] * ux) < 0.02), None)
        if not g:
            g = {"ux": ux, "uy": uy, "items": []}
            groups.append(g)
        g["items"].append(p)
    out = []
    for g in groups:
        if len(g["items"]) < 2:
            continue
        nx, ny = -g["uy"], g["ux"]
        rows = sorted(((p[0] * nx + p[1] * ny, max(p[0] * g["ux"] + p[1] * g["uy"], p[2] * g["ux"] + p[3] * g["uy"]))
                       for p in g["items"]), key=lambda r: r[0])
        top = max(r[1] for r in rows) + off
        for a, b in zip(rows, rows[1:]):
            out.append(((g["ux"] * top + nx * a[0], g["uy"] * top + ny * a[0]),
                        (g["ux"] * top + nx * b[0], g["uy"] * top + ny * b[0]), b[0] - a[0]))
    return out


def export(path, res, P, include_base=True):
    """res: AnalysisResult (surveys · sketches · members), P: 용도 정의. → 저장한 레이어 수"""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment as TA
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    for name, pat in (("CENTER", [2.0, 1.25, -0.25, 0.25, -0.25]), ("DASHED", [0.6, 0.4, -0.2])):
        if name not in doc.linetypes:
            doc.linetypes.add(name, [x * 1000 for x in pat], description=name)
    msp = doc.modelspace()
    x0, y0, x1, y1 = res.extents
    H = min(500.0, max(120.0, max(x1 - x0, y1 - y0, 1000) / 200))

    def lay(name, color, lt="CONTINUOUS"):
        if name not in doc.layers:
            doc.layers.add(name, color=color, linetype=lt)
        return {"layer": name}

    def text(L, p, h, t, rot=0.0, align=TA.MIDDLE_CENTER):
        t = (t or "").replace("📍", "").replace("✍", "").strip()
        if t:
            msp.add_text(t, height=h, dxfattribs={**L, "rotation": rot}).set_placement(p, align=align)

    # ---- 바탕
    if include_base:
        Lg, Lb = lay("BASE-GRID", 8, "CENTER"), lay("BASE-LINE", 9)
        for s in res.grid:
            msp.add_line((s.x1, s.y1), (s.x2, s.y2), dxfattribs=Lg)
        for s in res.background:
            msp.add_line((s.x1, s.y1), (s.x2, s.y2), dxfattribs=Lb)
        KL = {"column": ("BASE-COLUMN", 1), "girder": ("BASE-GIRDER", 4), "beam": ("BASE-BEAM", 3), "wall": ("BASE-WALL", 8)}
        for m in res.members:
            nm, col = KL.get(m.kind, ("BASE-ETC", 8))
            L = lay(nm, col)
            if m.kind == "column":
                if m.polygon:
                    msp.add_lwpolyline(m.polygon, close=True, dxfattribs=L)
                c = m.center
            else:
                msp.add_line(m.p1, m.p2, dxfattribs=L)
                c = ((m.p1[0] + m.p2[0]) / 2, (m.p1[1] + m.p2[1]) / 2)
            if m.name and c:
                text(lay("BASE-NAME", 8), (c[0], c[1] + H * 0.7), H * 0.6, m.name)
    # ---- 검측점
    byid = res.by_id()
    custom = {}
    for rec in res.surveys:
        if not SV.is_placed(rec):
            continue
        p = P.get(rec.get("purpose"), {})
        code = SV_CODE.get(rec.get("purpose")) or custom.setdefault(rec.get("purpose"), f"U{len(custom) + 1}")
        ct = (rec.get("fields") or {}).get("ctype")
        if p.get("crack") and ct in SV.CRACK_CODE:
            code += "-" + SV.CRACK_CODE[ct]
        col = _aci(p.get("color"))
        L, Lt = lay("SV-" + code, col), lay("SV-" + code + "-TXT", col)
        g = SV.geometry(rec, byid)
        Rb = H * 1.1
        if g[0] == "area":
            pl = SV.poly_pts(rec)
            r = g[1]
            msp.add_lwpolyline(pl or [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])], close=True, dxfattribs=L)
            fl = rec.get("fields") or {}
            lines = [x for x in (rec.get("name"), fl.get("use"), " ".join(x for x in (fl.get("fin"), f"{fl['fin_t']}mm" if fl.get("fin_t") else "") if x),
                                 fl.get("ceil"), f"{SV.area_m2(rec):.1f} m²", SV.load_text(fl)) if x]
            cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
            for i, t in enumerate(lines):
                text(Lt, (cx, cy + (len(lines) / 2 - i - 0.5) * H * 1.4), H * 0.8, t)
        elif g[0] == "span":
            msp.add_line(g[1], g[2], dxfattribs=L)
            for q in (g[1], g[2]):
                msp.add_circle(q, H * 0.25, dxfattribs=L)
        else:
            q = g[1]
            msp.add_circle(q, H * 0.3, dxfattribs=L)
            msp.add_line((q[0] - H * 0.5, q[1]), (q[0] + H * 0.5, q[1]), dxfattribs=L)
            msp.add_line((q[0], q[1] - H * 0.5), (q[0], q[1] + H * 0.5), dxfattribs=L)
        an, bb = SV.anchor(rec, byid), SV.bubble(rec, byid)
        d = math.hypot(bb[0] - an[0], bb[1] - an[1])
        if d > Rb:
            msp.add_line(an, (bb[0] - (bb[0] - an[0]) / d * Rb, bb[1] - (bb[1] - an[1]) / d * Rb), dxfattribs=L)
        msp.add_circle(bb, Rb, dxfattribs=L)
        lab = str(rec.get("label") or rec.get("no", ""))
        text(L, bb, H * (0.65 if len(lab) > 2 else 0.85), lab)
        sm = SV.summary(rec, P).replace("미배치", "")
        if sm:
            text(Lt, (bb[0] + Rb * 1.3, bb[1]), H * 0.6, sm, align=TA.MIDDLE_LEFT)
        if rec.get("name") and g[0] != "area":
            text(Lt, (bb[0] + Rb * 1.3, bb[1] + H * 0.9), H * 0.6, rec["name"], align=TA.MIDDLE_LEFT)
    # ---- 스케치
    sks = getattr(res, "sketches", []) or []
    Ls = lay("SK-SIGN", 8)
    for sk in sks:
        p = sk.get("pts") or []
        if len(p) < 2:
            continue
        kind = sk.get("kind")
        cn = _cname(sk.get("color"))
        col = COLOR_ACI.get(cn) or _aci(sk.get("color"))
        L = lay(f"SK-{SK_KIND.get(kind, 'ETC')}-{cn}", col, "CENTER" if kind == "axis" else "CONTINUOUS")
        P0 = (p[0], p[1])
        P1 = (p[2], p[3]) if len(p) >= 4 else P0
        ang = math.degrees(math.atan2(P1[1] - P0[1], P1[0] - P0[0]))
        Lx = math.hypot(P1[0] - P0[0], P1[1] - P0[1]) or 1
        nx, ny = -(P1[1] - P0[1]) / Lx, (P1[0] - P0[0]) / Lx
        mid = ((P0[0] + P1[0]) / 2, (P0[1] + P1[1]) / 2)
        if kind in ("beam", "wall"):
            t = float(sk.get("t") or 200) if kind == "wall" else float(sk.get("w") or 400)
            q = [(P0[0] + nx * t / 2, P0[1] + ny * t / 2), (P1[0] + nx * t / 2, P1[1] + ny * t / 2),
                 (P1[0] - nx * t / 2, P1[1] - ny * t / 2), (P0[0] - nx * t / 2, P0[1] - ny * t / 2)]
            if kind == "wall":
                msp.add_lwpolyline(q, close=True, dxfattribs=L)
            elif sk.get("dbl"):
                msp.add_line(q[0], q[1], dxfattribs=L)
                msp.add_line(q[3], q[2], dxfattribs=L)
                msp.add_line(P0, P1, dxfattribs=lay(f"SK-BEAM-{cn}-CL", col, "DASHED"))
            else:
                msp.add_line(P0, P1, dxfattribs=L)
            if sk.get("name"):
                text(L, (mid[0] + nx * (t / 2 + H * 0.7), mid[1] + ny * (t / 2 + H * 0.7)), H * 0.8, sk["name"], _up(ang))
        elif kind == "column":
            msp.add_lwpolyline([(P0[0], P0[1]), (P1[0], P0[1]), (P1[0], P1[1]), (P0[0], P1[1])], close=True, dxfattribs=L)
            b, h = sk.get("b") or abs(P1[0] - P0[0]), sk.get("h") or abs(P1[1] - P0[1])
            text(L, ((P0[0] + P1[0]) / 2, max(P0[1], P1[1]) + H * 0.7), H * 0.7, (f"{sk['name']} " if sk.get("name") else "") + f"{b:.0f}x{h:.0f}")
        elif kind == "axis":
            ux, uy, R = (P1[0] - P0[0]) / Lx, (P1[1] - P0[1]) / Lx, H * 1.2
            msp.add_line(P0, P1, dxfattribs=L)
            Lb2 = lay(f"SK-AXIS-{cn}-BUBBLE", col)
            for v, sg in ((P0, -1), (P1, 1)):
                c = (v[0] + ux * R * sg, v[1] + uy * R * sg)
                msp.add_circle(c, R, dxfattribs=Lb2)
                text(Lb2, c, H, sk.get("text", ""))
        elif kind == "free":
            msp.add_lwpolyline([(p[i], p[i + 1]) for i in range(0, len(p) - 1, 2)], dxfattribs=L)
        elif kind == "dim":
            msp.add_line(P0, P1, dxfattribs=L)
            ux, uy, k = (P1[0] - P0[0]) / Lx, (P1[1] - P0[1]) / Lx, H * 0.4
            for v in (P0, P1):
                msp.add_line((v[0] - (ux + nx) * k, v[1] - (uy + ny) * k), (v[0] + (ux + nx) * k, v[1] + (uy + ny) * k), dxfattribs=L)
                msp.add_line((v[0] + nx * k * 1.5, v[1] + ny * k * 1.5), (v[0] - nx * k * 1.5, v[1] - ny * k * 1.5), dxfattribs=L)
            sg = 1 if _up(ang) == ang else -1
            text(L, (mid[0] + nx * H * 0.7 * sg, mid[1] + ny * H * 0.7 * sg), H * 0.8, f"{float(sk.get('val') or Lx):,.0f}", _up(ang))
        elif kind == "text":
            text(L, P0, H, sk.get("text", ""))
        if sk.get("inspector") and kind not in ("axis", "dim"):
            if kind == "column":
                at = ((P0[0] + P1[0]) / 2, min(P0[1], P1[1]) - H * 0.6)
            elif kind == "text":
                at = (P0[0], P0[1] - H)
            else:
                at = (p[-2], p[-1] - H * 0.6)
            text(Ls, at, H * 0.45, f"({sk['inspector']})")
    Lgap = lay("SK-AXIS-GAP", 8)
    for a, b, d in axis_gaps(sks, H * 3.2):
        msp.add_line(a, b, dxfattribs=Lgap)
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        L2 = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        nx2, ny2 = -(b[1] - a[1]) / L2, (b[0] - a[0]) / L2
        sg = 1 if _up(ang) == ang else -1
        text(Lgap, ((a[0] + b[0]) / 2 + nx2 * H * 0.6 * sg, (a[1] + b[1]) / 2 + ny2 * H * 0.6 * sg), H * 0.7, f"{d:,.0f}", _up(ang))
    doc.saveas(path)
    return len(doc.layers)
