"""
dxf_write.py — 일람표 DXF 출력 (예제 '보 일람표' 시트 양식)

시트 양식(도곽)은 템플릿 DXF 에서 가져옴:
  · 가져온 원본 DXF (같은 S_FORM 도곽이면 그대로 — 표제란·블록·문자스타일 유지)
  · 없으면 autotable/templates/schedule_form.dxf
시트 1장 기준 좌표 (도곽 폭 24262.63 기준, 다른 크기면 비례):
  표 영역 x 347~21316, y 231~16926, 줄이름 칸 347~1247
  보 : 4단 × 3부재, 부재당 3칸(2234), 단 높이 4174 = 부호300 + 구분300 + 단면2674 + 상부300 + 하부300 + 늑근300
"""
from __future__ import annotations

import math
import os
import re
import sys

from . import model as M
from . import sections as S

FORM_W = 24262.63
# 예제 도면에서 잰 정확한 값 (원본과 선·글자가 겹치도록)
X0, X1, YT, YB, LX = 346.61, 21316.45, 16926.07, 231.07, 1246.61
SUB = 2234.17
MEM_X = (LX, LX + 3 * SUB, LX + 6 * SUB)
BAND = 4173.75
SEC_BOT = BAND - 900.0           # 단면 칸 아래 끝 (단 위에서)
SEC_CY = (600.0 + SEC_BOT) / 2 + 50.0   # 보 단면(슬래브 윗면~보 밑) 가운데 = 단 위에서 1986.9 아래
SEC_DX = 100.0                   # 보 단면 가운데 = 칸 가운데 + 100
LBL_X = 796.6
H_LBL, H_VAL, H_NAME = 75.0, 90.0, 120.0
L_LINE_T, L_LINE_M, L_LINE_E, L_TEXT, L_NAME = "T", "ML", "ELE", "TEXT", "T"


def template_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "..", "templates"), os.path.join(here, "templates")]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands += [os.path.join(base, "autotable", "templates"), os.path.join(base, "templates")]
    for c in cands:
        if os.path.isdir(c):
            return os.path.normpath(c)
    return os.path.normpath(cands[0])


def default_template():
    return os.path.join(template_dir(), "schedule_form.dxf")


# ═══════════════════════════════════════════════════════════════════
#  템플릿
# ═══════════════════════════════════════════════════════════════════
def _bbox(e):
    from ezdxf import bbox as BB
    try:
        b = BB.extents([e], fast=True)
        return b if b.has_data else None
    except Exception:                         # noqa: BLE001
        return None


def open_template(path, log=print):
    """템플릿 DXF → (doc, form, decor[시트1 표제란 엔티티])  나머지 모형공간 엔티티는 지움."""
    import ezdxf
    from .dxf_read import find_form
    try:
        doc = ezdxf.readfile(path)
    except Exception:                         # noqa: BLE001
        from ezdxf import recover
        doc, _ = recover.readfile(path)
    form = find_form(doc)
    if not form:
        raise ValueError("시트 양식(도곽 블록)을 찾지 못했습니다.")
    msp = doc.modelspace()
    ox, oy = form["origin"]
    k = form["w"] / FORM_W
    decor, drop = [], []
    for e in msp:
        if e.dxftype() == "INSERT" and e.dxf.name == form["block"] and abs(e.dxf.insert.x - ox) < 1 and abs(e.dxf.insert.y - oy) < 1:
            decor.append(e)
            continue
        b = _bbox(e)
        if b is not None and ox + X1 * k - 1 <= b.extmin.x and b.extmax.x <= ox + form["w"] + 1 \
                and oy - 1 <= b.extmin.y and b.extmax.y <= oy + form["h"] + 1 and e.dxftype() in ("TEXT", "MTEXT", "LINE", "LWPOLYLINE", "INSERT", "CIRCLE"):
            decor.append(e)
        else:
            drop.append(e)
    for e in drop:
        msp.delete_entity(e)
    if form["count"] < 2:
        form["pitch"] = form["w"]
    return doc, form, decor


def build_template(src_path, out_path, log=print):
    """원본 DXF → 양식 템플릿 저장 (모형공간엔 시트1 도곽+표제란만, 안 쓰는 블록 정리)."""
    doc, form, decor = open_template(src_path, log)
    used = set()

    def walk(name):
        if name in used:
            return
        used.add(name)
        blk = doc.blocks.get(name)
        if blk is None:
            return
        for e in blk:
            if e.dxftype() == "INSERT":
                walk(e.dxf.name)
    for e in doc.modelspace():
        if e.dxftype() == "INSERT":
            walk(e.dxf.name)
    for ds in doc.dimstyles:
        for a in ("dimblk", "dimblk1", "dimblk2", "dimldrblk"):
            n = ds.dxf.get(a, "")
            if n:
                used.add(n)
    for blk in list(doc.blocks):
        n = blk.name
        if n.upper().startswith(("*MODEL_SPACE", "*PAPER_SPACE")) or n in used:
            continue
        try:
            doc.blocks.delete_block(n, safe=False)
        except Exception:                     # noqa: BLE001
            pass
    doc.saveas(out_path)
    return out_path


# ═══════════════════════════════════════════════════════════════════
#  그리기 도우미
# ═══════════════════════════════════════════════════════════════════
class Sheet:
    def __init__(self, doc, form, i):
        self.doc = doc
        self.msp = doc.modelspace()
        self.k = form["w"] / FORM_W
        self.ox = form["origin"][0] + i * form["pitch"]
        self.oy = form["origin"][1]

    def P(self, x, y):
        return (self.ox + x * self.k, self.oy + y * self.k)

    def line(self, x0, y0, x1, y1, layer):
        self.msp.add_lwpolyline([self.P(x0, y0), self.P(x1, y1)], dxfattribs={"layer": layer})

    def text(self, s, x, y, h, layer=L_TEXT, rot=0.0):
        if s is None or str(s).strip() == "":
            return
        from ezdxf.enums import TextEntityAlignment
        t = self.msp.add_text(str(s), height=h * self.k, rotation=rot,
                              dxfattribs={"layer": layer, "style": "Standard"})
        t.set_placement(self.P(x, y), align=TextEntityAlignment.MIDDLE_CENTER)

    def section(self, prims, cx, cy, ext, avail_w, avail_h, dimstyle, anchor=None, scale=None):
        """단면 요소를 칸 가운데(cx, cy)에 맞춰 그림. 크면 축소 (치수 글자는 실제값).
        anchor=(lx, ly): 단면 좌표 (lx, ly) 를 (cx, cy) 에 맞춤 (원본 배치 규칙)."""
        xmin, ymin, xmax, ymax = ext
        s = scale if scale is not None else min(1.0, avail_w / (xmax - xmin), avail_h / (ymax - ymin))
        if anchor:
            bx = cx - anchor[0] * s
            by = cy - anchor[1] * s
        else:
            bx = cx - (xmin + xmax) / 2 * s
            by = cy - (ymin + ymax) / 2 * s
        k = self.k

        def Q(x, y):
            return self.P(bx + x * s, by + y * s)

        for pr in prims:
            t = pr["t"]
            if t == "poly":
                pts = [(*Q(p[0], p[1]), 0, 0, p[2] if len(p) > 2 else 0) for p in pr["pts"]]
                self.msp.add_lwpolyline(pts, format="xyseb", close=pr.get("closed", False),
                                        dxfattribs={"layer": pr["layer"]})
            elif t == "donut":
                (x, y), r = pr["c"], pr["r"] * s * k
                cx2, cy2 = Q(x, y)
                pl = self.msp.add_lwpolyline([(cx2 - r / 2, cy2, 0, 0, 1), (cx2 + r / 2, cy2, 0, 0, 1)], format="xyseb",
                                             close=True, dxfattribs={"layer": pr["layer"]})
                pl.dxf.const_width = r
            elif t == "circle":
                (x, y) = pr["c"]
                self.msp.add_circle(Q(x, y), pr["r"] * s * k, dxfattribs={"layer": pr["layer"]})
            elif t == "dim":
                try:
                    d = self.msp.add_linear_dim(base=Q(*pr["base"]), p1=Q(*pr["p1"]), p2=Q(*pr["p2"]),
                                                angle=pr["angle"], dimstyle=dimstyle, text=pr["text"],
                                                dxfattribs={"layer": S.L_DIM})
                    d.render()
                except Exception:             # noqa: BLE001
                    pass
        return s


def _ensure_layers(doc):
    want = {"T": 2, "ML": 4, "ELE": 1, "TEXT": 3, "bar2": 40, "dim": 7, "S_TEXT": 3}
    for n, c in want.items():
        if n not in doc.layers:
            doc.layers.add(n, color=c)


def _dimstyle(doc, k):
    if "S_30" in doc.dimstyles:
        return "S_30"
    ds = doc.dimstyles.new("AT_DIM")
    ds.dxf.dimtxt = 60 * k
    ds.dxf.dimasz = 30 * k
    ds.dxf.dimexo = 20 * k
    ds.dxf.dimexe = 30 * k
    ds.dxf.dimgap = 20 * k
    ds.dxf.dimtad = 1
    ds.dxf.dimclrt = 3
    return "AT_DIM"


# ═══════════════════════════════════════════════════════════════════
#  표제란 (제목 · 도면번호 · NOTE · 프로젝트명)
# ═══════════════════════════════════════════════════════════════════
_DNO = re.compile(r"^([A-Z]{1,3}-?)(\d{2,4})$")


def _is_note(e):
    if e.dxftype() != "TEXT":
        return False
    t = e.dxf.text or ""
    return e.dxf.layer == "000구조_기타" or bool(re.match(r"^\s*\d+\s*[.)]\s*\S", t))


def _decorate(doc, form, decor, n_sheets, opts, log=print):
    msp = doc.modelspace()
    title = opts.get("title") or "일람표"
    dno = (opts.get("drawing_no") or "").strip()
    notes = opts.get("notes")
    m = _DNO.match(dno)
    notes_proto = sorted([e for e in decor if _is_note(e)], key=lambda e: -e.dxf.insert.y)
    step = (notes_proto[0].dxf.insert.y - notes_proto[1].dxf.insert.y) if len(notes_proto) > 1 else 289 * form["w"] / FORM_W
    base = [e for e in decor if e not in notes_proto] if notes is not None else list(decor)
    proto = notes_proto[0] if notes_proto else None
    for i in range(n_sheets):
        dx = i * form["pitch"]
        ents = []
        for e in base:
            if i == 0:
                ents.append(e)
            else:
                c = e.copy()
                msp.add_entity(c)
                c.translate(dx, 0, 0)
                ents.append(c)
        for e in ents:
            if e.dxftype() != "TEXT":
                continue
            t = (e.dxf.text or "").strip()
            if "일람표" in t:
                e.dxf.text = f"{title}-{i + 1}" if n_sheets > 1 else title
            elif m and _DNO.match(t):
                e.dxf.text = f"{m.group(1)}{int(m.group(2)) + i:0{len(m.group(2))}d}"
        if notes is not None and notes:
            for j, line in enumerate(notes):
                if proto is not None:
                    c = proto.copy()
                    msp.add_entity(c)
                    c.dxf.text = line
                    c.translate(dx, -j * step, 0)
                else:
                    k = form["w"] / FORM_W
                    ox, oy = form["origin"]
                    msp.add_text(line, height=90 * k, dxfattribs={"layer": "TEXT", "insert": (ox + dx + 21605 * k, oy + (14068 - j * 289) * k)})

    if notes is not None:
        for e in notes_proto:
            msp.delete_entity(e)

    proj = [p for p in (opts.get("project") or []) if p is not None]
    if any((p or "").strip() for p in proj):
        blk = doc.blocks.get(form["block"])
        s = form["scale"]
        cand = sorted([e for e in blk if e.dxftype() == "TEXT" and e.dxf.insert.y * s > 14615 * form["w"] / FORM_W
                       and (e.dxf.text or "").strip().upper() != "PROJECT"], key=lambda e: -e.dxf.insert.y)
        for e, txt in zip(cand, list(proj) + [""] * len(cand)):
            e.dxf.text = txt or ""


# ═══════════════════════════════════════════════════════════════════
#  부재별 표
# ═══════════════════════════════════════════════════════════════════
SEC_H0 = BAND - 1500.0           # 기본 단면 그림 칸 높이 2673.75
SHEET_H = YT - YB                 # 16695


def _num(v):
    try:
        return float(v or 0)
    except ValueError:
        return 0.0


def _sec_h(rows, grow=True):
    """단(3부재)의 단면 칸 높이: 깊은 보는 300 단위로 늘림 (원본: H1950~2750 → 3574)."""
    if not grow:
        return SEC_H0
    need = max([_num(r.get("h")) for r in rows] + [0.0]) + 820.0     # 원본: H2750 → 3574
    steps = max(0, math.ceil((need - SEC_H0) / 300.0 - 1e-9))
    return min(SEC_H0 + 300.0 * steps, SHEET_H - 1500.0)


def plan_beam_sheets(rows, grow=True):
    """→ [[(부재들, 단면칸높이), …] 시트별]  (단 높이 = 1500 + 단면칸)
    원본 도면처럼: 깊은 보 단은 늘리고, 시트에 안 들어가면 같은 시트의 보통 단을 300 줄여서(2374) 맞춤."""
    small = SEC_H0 - 300.0

    def fits(cur, extra):
        return sum(1500.0 + h for _, h in cur) + extra <= SHEET_H + 0.5

    def squeeze(cur):
        """모든 단을 (단면이 들어가는 한) 300 씩 줄인 목록 (원본 시트 4 처럼)."""
        out = []
        for bm, h in cur:
            hh = h - 300.0
            ok = hh >= small - 0.5 and all(_num(r.get("h")) + 870.0 <= hh + 0.5 for r in bm)
            out.append((bm, hh if ok else h))
        return out

    bands = [rows[i:i + 3] for i in range(0, len(rows), 3)]
    sheets, cur = [], []
    for bm in bands:
        h = _sec_h(bm, grow)
        if cur and not fits(cur, 1500.0 + h):
            sq = squeeze(cur + [(bm, h)]) if (grow and h <= SEC_H0) else None     # 보통 단을 넣을 때만 줄임
            if sq is not None and fits(sq, 0.0):
                cur = sq
                continue
            sheets.append(cur)
            cur = []
        cur.append((bm, h))
    while fits(cur, 1500.0 + SEC_H0):                  # 남는 자리는 빈 단으로 (원본처럼 틀만)
        cur.append(([], SEC_H0))
    sheets.append(cur)
    return sheets


def _beam_cy(H, sec_h=SEC_H0):
    """단 위에서 보 단면(슬래브 윗면~보 밑) 가운데까지 거리."""
    if sec_h <= SEC_H0:
        return 1986.875                                  # 원본 고정값
    sb = 600.0 + sec_h
    cy = max((600.0 + sb) / 2 + 50.0, 600.0 + H / 2 + 650.0)   # 깊은 보: 위 치수가 구분 줄에 안 닿게
    return min(cy, sb - H / 2 - 60.0)


def _beam_scale(B, H, sec_h=SEC_H0):
    """원본 배치로 칸을 넘지 않게 하는 축척 (보통은 1)."""
    cy = _beam_cy(H, sec_h)
    up = cy - 600.0 - 20.0
    dn = 600.0 + sec_h - cy - 40.0
    lf = SUB / 2 + SEC_DX - 30.0
    rt = SUB / 2 - SEC_DX - 30.0
    return min(1.0, up / (H / 2 + 600.0), dn / (H / 2 + 20.0), lf / (B / 2 + 420.0), rt / (B / 2 + 120.0))


def _bar_text(v, total):
    """2단 배근 글자: total=True 면 '4/2-D19' → '6-D19'."""
    if not total or not v:
        return v
    p = M.parse_rebar(v)
    if not p or not p["n2"] or "+" in v:
        return v
    import re as _re
    m = _re.fullmatch(r"(\d+)/(\d+)-([A-Z]{0,3})(\d+)", M._clean(v))
    return f"{p['n1'] + p['n2']}-{m.group(3)}{m.group(4)}" if m else v


def _draw_beam_sheet(sh, bands, dimstyle, total=False):
    """bands: [(부재들 ≤3, 단면칸높이)]"""
    L = sh.line
    tops = []
    y = YT
    for _bm, h in bands:
        tops.append((y, h))
        y -= 1500.0 + h
    ybot = y
    for x in MEM_X:
        L(x, YT, x, ybot, L_LINE_T)
    for (Y, h) in tops[1:]:
        L(X0, Y, X1, Y, L_LINE_T)
    if ybot > YB + 1:
        L(X0, ybot, X1, ybot, L_LINE_T)
    for (Y, h) in tops:
        sb = 600.0 + h                                # 단면 칸 아래 끝
        bh = sb + 900.0
        L(X0, Y - 300, X1, Y - 300, L_LINE_M)
        L(X0, Y - sb, X1, Y - sb, L_LINE_M)
        L(LX, Y - 600, X1, Y - 600, L_LINE_E)
        L(X0, Y - sb - 300, X1, Y - sb - 300, L_LINE_E)
        L(X0, Y - sb - 600, X1, Y - sb - 600, L_LINE_E)
        for mx in MEM_X:
            for j in (1, 2):
                L(mx + j * SUB, Y - 300, mx + j * SUB, Y - bh, L_LINE_M)
        sh.text("부   호", LBL_X, Y - 150, H_LBL)
        sh.text("단   면", LBL_X, (Y - 300 + Y - sb) / 2, H_LBL)
        sh.text("상 부 근", LBL_X, Y - sb - 150, H_LBL)
        sh.text("하 부 근", LBL_X, Y - sb - 450, H_LBL)
        sh.text("늑   근", LBL_X, Y - sb - 750, H_LBL)
    for (bm, h), (Y, _h) in zip(bands, tops):
        sb = 600.0 + h
        for m, r in enumerate(bm):
            mx = MEM_X[m]
            sh.text(r.get("name", ""), mx + 1.5 * SUB, Y - 150, H_NAME, layer=L_NAME)
            for label, pos, p in M.beam_zones(r):
                cx = mx + (pos + 0.5) * SUB
                sh.text(label, cx, Y - 450, H_VAL)
                sh.text(_bar_text(r.get(p + "top", ""), total), cx, Y - sb - 150, H_VAL)
                sh.text(_bar_text(r.get(p + "bot", ""), total), cx, Y - sb - 450, H_VAL)
                sh.text(r.get(p + "stir", ""), cx, Y - sb - 750, H_VAL)
                B, H = _num(r.get("b")), _num(r.get("h"))
                if B > 0 and H > 0:
                    prims = S.beam_section(B, H, r.get("slab") or 0, r.get(p + "top", ""), r.get(p + "bot", ""), r.get(p + "stir", ""))
                    sh.section(prims, cx + SEC_DX, Y - _beam_cy(H, h), S.beam_extent(B, H), 0, 0, dimstyle,
                               anchor=(B / 2, H / 2), scale=_beam_scale(B, H, h))


C_ROWS = [("부   호", 300, "name"), ("층", 300, "floor"), ("단   면", 2674, "sec"), ("크   기", 300, "size"),
          ("주   근", 300, "main"), ("대근(단부)", 300, "hoop_e"), ("대근(중앙)", 300, "hoop_m"), ("보조대근", 300, "tie")]
C_PER = 9


def _draw_column_sheet(sh, members, dimstyle):
    L = sh.line
    cw = (X1 - LX) / C_PER
    bh = sum(r[1] for r in C_ROWS)
    nb = int((YT - YB) // bh)
    L(LX, YT, LX, YB, L_LINE_T)
    for b in range(nb):
        Y = YT - b * bh
        y = Y
        for lbl, hgt, key in C_ROWS:
            sh.text(lbl, LBL_X, y - hgt / 2, H_LBL)
            y -= hgt
            L(X0, y, X1, y, L_LINE_T if key == C_ROWS[-1][2] else (L_LINE_M if key in ("name", "sec") else L_LINE_E))
        for j in range(1, C_PER):
            L(LX + j * cw, Y, LX + j * cw, Y - bh, L_LINE_M)
    for idx, r in enumerate(members):
        b, j = divmod(idx, C_PER)
        if b >= nb:
            break
        Y = YT - b * bh
        cx = LX + (j + 0.5) * cw
        y = Y
        for lbl, hgt, key in C_ROWS:
            cy = y - hgt / 2
            if key == "name":
                sh.text(r.get("name", ""), cx, cy, H_NAME, layer=L_NAME)
            elif key == "size":
                if r.get("shape") == "원형":
                    sh.text(f"Ø{r.get('b', '')}", cx, cy, H_VAL)
                elif r.get("b") or r.get("h"):
                    sh.text(f"{r.get('b', '')}×{r.get('h', '')}", cx, cy, H_VAL)
            elif key == "tie":
                tx, ty = r.get("tie_x", ""), r.get("tie_y", "")
                sh.text(" / ".join(v for v in (f"X:{tx}" if tx else "", f"Y:{ty}" if ty else "") if v), cx, cy, H_VAL * 0.85)
            elif key == "sec":
                try:
                    B = float(r.get("b") or 0)
                    D = float(r.get("h") or 0) if r.get("shape") != "원형" else B
                except ValueError:
                    B = D = 0
                if B > 0 and D > 0:
                    prims = S.column_section(B, D, r.get("shape", "사각"), r.get("main", ""), r.get("hoop_m", ""),
                                             r.get("tie_x", ""), r.get("tie_y", ""), r.get("arr", ""))
                    sh.section(prims, cx, cy, (-420, -100, B + 120, D + 520), cw - 200, hgt - 150, dimstyle)
            else:
                sh.text(r.get(key, ""), cx, cy, H_VAL)
            y -= hgt


def _table_layout(mtype):
    cs = M.cols(mtype)
    tot = sum(c.width for c in cs)
    xs = [X0]
    for c in cs:
        xs.append(xs[-1] + (X1 - X0) * c.width / tot)
    return cs, xs


def _draw_table_sheet(sh, mtype, members):
    L = sh.line
    cs, xs = _table_layout(mtype)
    hdr = 600.0
    rh = 300.0
    n = len(members)
    yb = YT - hdr - max(n, 1) * rh
    # 머리글
    L(X0, YT - hdr, X1, YT - hdr, L_LINE_T)
    i = 0
    while i < len(cs):
        c = cs[i]
        if c.group:
            j = i
            while j + 1 < len(cs) and cs[j + 1].group == c.group:
                j += 1
            sh.text(c.group, (xs[i] + xs[j + 1]) / 2, YT - 150, H_LBL)
            L(xs[i], YT - 300, xs[j + 1], YT - 300, L_LINE_E)
            for k in range(i, j + 1):
                sh.text(cs[k].title, (xs[k] + xs[k + 1]) / 2, YT - 450, H_LBL)
            i = j + 1
        else:
            sh.text(c.title, (xs[i] + xs[i + 1]) / 2, YT - 300, H_LBL)
            i += 1
    for i, x in enumerate(xs[1:-1], start=1):
        top = YT - 300 if cs[i].group and cs[i - 1].group == cs[i].group else YT
        L(x, top, x, yb, L_LINE_M)
    for r_i, r in enumerate(members):
        y = YT - hdr - (r_i + 0.5) * rh
        for c_i, c in enumerate(cs):
            sh.text(r.get(c.key, ""), (xs[c_i] + xs[c_i + 1]) / 2, y, H_VAL, layer=L_NAME if c.key == "name" else L_TEXT)
        L(X0, y - rh / 2, X1, y - rh / 2, L_LINE_E)


PER_SHEET = {"beam": 12, "column": None, "wall": int((YT - YB - 600) // 300), "slab": int((YT - YB - 600) // 300)}


def _per_sheet(mtype):
    if mtype == "column":
        bh = sum(r[1] for r in C_ROWS)
        return int((YT - YB) // bh) * C_PER
    return PER_SHEET[mtype]


def export_dxf(path, mtype, rows, template=None, opts=None, log=print):
    """일람표 DXF 저장 → 시트 수."""
    opts = dict(opts or {})
    rows = [r for r in M.clean_rows(mtype, rows)]
    if not rows:
        raise ValueError("출력할 부재가 없습니다.")
    tpl = template if template and os.path.isfile(template) else default_template()
    if not os.path.isfile(tpl):
        raise FileNotFoundError(f"시트 양식 파일이 없습니다: {tpl}")
    doc, form, decor = open_template(tpl, log)
    _ensure_layers(doc)
    k = form["w"] / FORM_W
    dimstyle = _dimstyle(doc, k)
    if mtype == "beam":
        plan = plan_beam_sheets(rows, grow=opts.get("deep", "grow") == "grow")
        n_sheets = len(plan)
    else:
        per = _per_sheet(mtype)
        n_sheets = max(1, math.ceil(len(rows) / per))
    opts.setdefault("title", f"{M.TYPES[mtype]['title']} 일람표")
    _decorate(doc, form, decor, n_sheets, opts, log)
    for i in range(n_sheets):
        sh = Sheet(doc, form, i)
        if mtype == "beam":
            _draw_beam_sheet(sh, plan[i], dimstyle, total=opts.get("layer_text", "total") == "total")
            continue
        part = rows[i * per:(i + 1) * per]
        if mtype == "column":
            _draw_column_sheet(sh, part, dimstyle)
        else:
            _draw_table_sheet(sh, mtype, part)
    try:
        doc.header["$EXTMIN"] = (form["origin"][0], form["origin"][1], 0)
        doc.header["$EXTMAX"] = (form["origin"][0] + n_sheets * form["pitch"], form["origin"][1] + form["h"], 0)
    except Exception:                         # noqa: BLE001
        pass
    doc.saveas(path)
    log(f"DXF 저장: {path}  (시트 {n_sheets}장, {len(rows)}개)")
    return n_sheets
