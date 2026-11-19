"""
dxf_read.py — CAD(DXF) 일람표 가져오기
  · TEXT/MTEXT/ATTRIB → 글자 위치 (정렬점 기준 가운데)
  · DIMENSION → 단면 B·H
  · 보 단면 선 → 슬래브 두께
  · 시트 틀(INSERT) 정보 → 내보낼 때 같은 양식으로
"""
from __future__ import annotations

import math
import re
import statistics

from . import model as M
from .parse_layout import DimItem, TItem, parse_any

_FMT = re.compile(r"\\[A-Za-z][^;\\]*;|[{}]|\\P")


def _text_center(e):
    d = e.dxf
    h = float(d.get("height", 1.0) or 1.0)
    rot = float(d.get("rotation", 0.0) or 0.0)
    txt = d.get("text", "") or ""
    ha, va = int(d.get("halign", 0) or 0), int(d.get("valign", 0) or 0)
    if (ha or va) and d.hasattr("align_point"):
        x, y = d.align_point.x, d.align_point.y
        if va == 0:                                   # 기준선 정렬 → 글자 가운데로
            y += 0.5 * h * math.cos(math.radians(rot))
        if ha in (3, 5):                              # aligned / fit → 두 점 가운데
            x = (d.insert.x + d.align_point.x) / 2
            y = (d.insert.y + d.align_point.y) / 2 + 0.5 * h
        elif ha == 2:                                 # 오른쪽 정렬
            w = 0.8 * h * _vis_len(txt)
            x -= 0.5 * w * math.cos(math.radians(rot))
            y -= 0.5 * w * math.sin(math.radians(rot))
        if va == 1:
            y += 0.5 * h
        elif va == 3:
            y -= 0.5 * h
        return x, y, h, rot
    w = 0.8 * h * _vis_len(txt) * float(d.get("width", 1.0) or 1.0)
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    return d.insert.x + 0.5 * (w * c - h * s), d.insert.y + 0.5 * (w * s + h * c), h, rot


def _vis_len(t):
    return sum(1.6 if ord(ch) > 0x2E80 else 1.0 for ch in t)


def _plain(t):
    return _FMT.sub(" ", t or "").replace("%%c", "Ø").replace("%%C", "Ø").replace("%%d", "°").strip()


def collect(doc, log=print):
    """→ items, dims, segs(가로 선분), forms(시트 틀 INSERT)"""
    msp = doc.modelspace()
    items, dims, segs, forms, bars = [], [], [], [], []

    def add_text(e, dx=0.0, dy=0.0):
        t = e.dxftype()
        if t in ("TEXT", "ATTRIB"):
            x, y, h, rot = _text_center(e)
            txt = _plain(e.dxf.get("text", ""))
        elif t == "MTEXT":
            txt = _plain(e.text)
            h = float(e.dxf.get("char_height", 1.0) or 1.0)
            x, y = e.dxf.insert.x, e.dxf.insert.y
            ap = int(e.dxf.get("attachment_point", 1) or 1)
            w = 0.8 * h * _vis_len(txt.split("\n")[0])
            x += {1: 0.5, 4: 0.5, 7: 0.5, 3: -0.5, 6: -0.5, 9: -0.5}.get(ap, 0.0) * w
            y += {1: -0.5, 2: -0.5, 3: -0.5, 7: 0.5, 8: 0.5, 9: 0.5}.get(ap, 0.0) * h
            rot = float(e.dxf.get("rotation", 0.0) or 0.0)
        else:
            return
        for line in txt.split("\n"):
            if line.strip():
                items.append(TItem(line.strip(), x + dx, y + dy, h, rot, e.dxf.layer))

    for e in msp:
        t = e.dxftype()
        if t in ("TEXT", "MTEXT"):
            add_text(e)
        elif t == "DIMENSION":
            try:
                v = e.get_measurement()
                v = float(v) if not hasattr(v, "x") else None
            except Exception:                 # noqa: BLE001
                v = None
            ov = (e.dxf.get("text", "") or "").strip()
            if ov and ov != "<>":
                m = re.search(r"\d+(?:\.\d+)?", ov.replace(",", ""))
                if m:
                    v = float(m.group())
            if not v:
                continue
            p2, p3 = e.dxf.get("defpoint2"), e.dxf.get("defpoint3")
            if p2 is None or p3 is None:
                continue
            ang = float(e.dxf.get("angle", 0.0) or 0.0)
            if (e.dxf.get("dimtype", 0) & 0x0F) == 1:          # aligned
                ang = math.degrees(math.atan2(p3.y - p2.y, p3.x - p2.x))
            dims.append(DimItem((p2.x + p3.x) / 2, (p2.y + p3.y) / 2, round(v, 1), ang))
        elif t == "INSERT":
            for a in e.attribs:
                add_text(a)
            forms.append(e)
        elif t == "CIRCLE" and e.dxf.radius > 0:
            bars.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius))
        elif t in ("LWPOLYLINE", "LINE", "POLYLINE"):
            pts = []
            if t == "LINE":
                pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            elif t == "LWPOLYLINE":
                if len(e) == 2 and e.closed:              # 도넛 = 철근
                    (x0, y0, _s, _e, b0), (x1, y1, _s2, _e2, b1) = e.get_points("xyseb")
                    if abs(abs(b0) - 1) < 0.05:
                        w = float(e.dxf.get("const_width", 0) or 0)
                        bars.append(((x0 + x1) / 2, (y0 + y1) / 2, math.hypot(x1 - x0, y1 - y0) / 2 + w / 2))
                    continue
                pts = [(p[0], p[1]) for p in e.get_points("xy")]
                if e.closed and pts:
                    pts.append(pts[0])
            else:
                try:
                    pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                except Exception:             # noqa: BLE001
                    pts = []
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                if abs(y1 - y0) < 1e-3 * max(1.0, abs(x1 - x0)) and abs(x1 - x0) > 1e-6:
                    segs.append((min(x0, x1), max(x0, x1), y0, e.dxf.layer))
    return items, dims, segs, forms, _dedupe(bars)


def _dedupe(bars):
    """같은 자리에 겹쳐 그린 철근 하나로."""
    out = []
    for b in sorted(bars):
        if out and any(abs(b[0] - o[0]) < 0.3 * max(b[2], 1) and abs(b[1] - o[1]) < 0.3 * max(b[2], 1) for o in out[-6:]):
            continue
        out.append(b)
    return out


def drawn_layers(cell, segs, bars):
    """보 단면 칸 안 철근 그림 → {'top': (1단, 2단), 'bot': (1단, 2단)} (그림 없으면 None)."""
    zx, ybot, ytop, W = cell[:4]
    s = [g for g in segs if abs((g[0] + g[1]) / 2 - zx) < 0.55 * W and ybot < g[2] < ytop and (g[1] - g[0]) < W]
    if len(s) < 2:
        return None
    top = max(g[2] for g in s)
    bot = min(g[2] for g in s)
    wl = min(g[0] for g in s if abs(g[2] - bot) < 1e-6)
    wr = max(g[1] for g in s if abs(g[2] - bot) < 1e-6)
    bs = [b for b in bars if wl < b[0] < wr and bot < b[1] < top and b[2] < 0.25 * (wr - wl)]
    if not bs:
        return {"top": (0, 0), "bot": (0, 0)}
    rr = statistics.median(b[2] for b in bs)
    mid = (top + bot) / 2

    def layers(group, from_bottom):
        ys = sorted((b[1] for b in group), reverse=not from_bottom)
        rows = []
        for y in ys:
            if rows and abs(y - rows[-1][0]) < 0.9 * rr:
                rows[-1][1] += 1
            else:
                rows.append([y, 1])
        if not rows:
            return (0, 0)
        return (rows[0][1], sum(r[1] for r in rows[1:]))
    return {"top": layers([b for b in bs if b[1] > mid], False), "bot": layers([b for b in bs if b[1] <= mid], True)}


def slab_thickness(cell, segs, B=None, H=None):
    """보 단면 칸 안의 가로선으로 슬래브 두께 추정."""
    zx, ybot, ytop, W = cell[:4]
    s = [g for g in segs if abs((g[0] + g[1]) / 2 - zx) < 0.55 * W and ybot < g[2] < ytop and (g[1] - g[0]) < W]
    if len(s) < 2:
        return ""
    top = max(g[2] for g in s)
    bot = min(g[2] for g in s)
    bsegs = [g for g in s if abs(g[2] - bot) < 1e-6]
    wl, wr = min(g[0] for g in bsegs), max(g[1] for g in bsegs)
    tol = 0.02 * max(1.0, wr - wl)
    cands = [g[2] for g in s if top - 1e-6 > g[2] > bot + 1e-6 and (g[1] <= wl + tol or g[0] >= wr - tol)]
    if not cands:
        return ""
    t = top - min(cands)
    try:
        if H and top - bot > 0:
            t *= float(H) / (top - bot)          # 축소해서 그린 단면
    except ValueError:
        pass
    if H and not (0 < t < float(H)):
        return ""
    return M.norm_num(f"{round(t / 5) * 5}")


def find_form(doc, forms=None):
    """시트 틀(도곽) INSERT 찾기 → dict(block, scale, origins[], pitch) 또는 None."""
    from ezdxf import bbox as BB
    if forms is None:
        forms = list(doc.modelspace().query("INSERT"))
    best = {}
    for ins in forms:
        try:
            blk = doc.blocks.get(ins.dxf.name)
            if blk is None:
                continue
            ext = BB.extents(blk, fast=True)
            if not ext.has_data:
                continue
            w = (ext.extmax.x - ext.extmin.x) * abs(ins.dxf.get("xscale", 1.0))
            h = (ext.extmax.y - ext.extmin.y) * abs(ins.dxf.get("yscale", 1.0))
        except Exception:                     # noqa: BLE001
            continue
        if w < 1000 or h < 500 or not (1.2 < w / h < 1.6):
            continue
        best.setdefault(ins.dxf.name, []).append((ins, w, h))
    if not best:
        return None
    name, lst = max(best.items(), key=lambda kv: kv[1][0][1] * kv[1][0][2] * len(kv[1]))
    lst.sort(key=lambda t: (t[0].dxf.insert.x, -t[0].dxf.insert.y))
    ins0, w, h = lst[0]
    xs = [t[0].dxf.insert.x for t in lst]
    pitch = min((b - a for a, b in zip(xs, xs[1:]) if b - a > 0.5 * w), default=w)
    return {"block": name, "scale": float(ins0.dxf.get("xscale", 1.0)), "w": w, "h": h, "pitch": pitch,
            "origin": (ins0.dxf.insert.x, ins0.dxf.insert.y), "count": len(lst)}


def read_meta(doc, form, items):
    """NOTE 문구, 도면번호 등 (시트 1 오른쪽 표제란)."""
    meta = {"notes": [], "drawing_no": ""}
    if not form:
        return meta
    ox, oy = form["origin"]
    k = form["w"] / 24262.63
    x_tb = ox + 21316 * k
    in1 = [i for i in items if x_tb < i.x < ox + form["w"] and oy < i.y < oy + form["h"]]
    for i in in1:
        if re.fullmatch(r"[A-Z]{1,3}-?\d{2,4}", i.text.strip()) and not meta["drawing_no"]:
            meta["drawing_no"] = i.text.strip()
    notes = sorted([i for i in in1 if re.match(r"^\s*\d+\s*[.)]", i.text) or (i.layer and i.layer == "000구조_기타")],
                   key=lambda i: -i.y)
    meta["notes"] = [i.text.rstrip() if re.match(r"^\s*\d+\s*[.)]", i.text) else "   " + i.text.strip() for i in notes]
    return meta


def import_dxf(path, want="auto", log=print):
    """→ (rows_by_type, warnings, meta)"""
    import ezdxf
    try:
        doc = ezdxf.readfile(path)
    except Exception:                         # noqa: BLE001
        from ezdxf import recover
        doc, _aud = recover.readfile(path)
    items, dims, segs, forms, bars = collect(doc, log)
    log(f"글자 {len(items)}개, 치수 {len(dims)}개 읽음")
    res, warn = parse_any(items, dims, want, log)
    for r in res.get("beam", []):
        cells = r.pop("_cells", [])
        r.pop("_pos", None)
        drawn = {}
        for cell in cells:
            pre = cell[4] if len(cell) > 4 else None
            if not pre:
                continue
            d = drawn_layers(cell, segs, bars)
            if d:
                drawn[pre + "top"] = d["top"]
                drawn[pre + "bot"] = d["bot"]
        if drawn:
            r["drawn"] = M.drawn_format(drawn)
            warn += M.apply_drawn(r)
        if not r.get("slab"):
            for cell in cells:
                t = slab_thickness(cell, segs, r.get("b"), r.get("h"))
                if t:
                    r["slab"] = t
                    break
    form = find_form(doc, forms)
    meta = read_meta(doc, form, items)
    meta["form"] = form
    meta["dxfversion"] = doc.dxfversion
    return res, warn, meta
