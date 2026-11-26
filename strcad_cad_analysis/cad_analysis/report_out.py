"""현장조사 → 손상물량표(엑셀) · 현황조사 사진첩(한글)

엑셀: 양식(손상물량표_양식.xlsx 또는 회사 양식)의 첫 시트를 도면마다 복사해
      D~K 조사 내용 · O열부터 사진 이름(사진 수만큼) · L 손상물량 = 식 · G 단위 = 식 · M·N(보수방안·발생요인)은 비워 둠.
사진첩: 한 쪽에 6칸(2열×3행) — 칸마다 사진 · 위치 · 내용. 6개가 넘으면 같은 틀로 쪽 추가.
       Word(.docx)로 만들고, 한글이 설치된 PC면 한글 자동화로 .hwp 로 저장 (없으면 .docx — 한글에서 열어 저장).
"""
from __future__ import annotations

import io
import os
import re
import zipfile

from . import survey as SV

CRACKISH = ("보 미장균열", "기둥 미장균열", "벽 미장균열", "균열")
MEMBER_FROM_TYPE = {"보 미장균열": "보", "기둥 미장균열": "기둥", "벽 미장균열": "벽체"}
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "templates", "손상물량표_양식.xlsx")


def _num(v):
    try:
        f = float(str(v).strip())
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return (str(v).strip() or None) if v not in (None, "") else None


def _mm2m(v):
    n = _num(v)
    return round(n / 1000, 3) if isinstance(n, (int, float)) else n


# --------------------------------------------------------------------------- 축 기준 위치 (스케치 축)
def axis_loc(res, x, y, tol=400.0):
    """스케치로 그린 축(X1, Y2 …)으로 위치 글자: 'X1~X2, Y1' (축 위면 그 축 이름만)."""
    vs, hs = [], []
    for sk in getattr(res, "sketches", []) or []:
        p = sk.get("pts") or []
        if sk.get("kind") != "axis" or len(p) < 4 or not sk.get("text"):
            continue
        if abs(p[2] - p[0]) < abs(p[3] - p[1]):
            vs.append(((p[0] + p[2]) / 2, sk["text"]))
        else:
            hs.append(((p[1] + p[3]) / 2, sk["text"]))

    def between(lst, v):
        if not lst:
            return ""
        lst = sorted(lst)
        near = min(lst, key=lambda a: abs(a[0] - v))
        if abs(near[0] - v) <= tol:
            return near[1]
        lo = [a for a in lst if a[0] < v]
        hi = [a for a in lst if a[0] > v]
        if lo and hi:
            return f"{lo[-1][1]}~{hi[0][1]}"
        return near[1]
    return ", ".join(x for x in (between(vs, x), between(hs, y)) if x)


def rec_point(rec, byid):
    g = SV.geometry(rec, byid)
    if g[0] == "area":
        r = g[1]
        return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
    if g[0] == "span":
        return ((g[1][0] + g[2][0]) / 2, (g[1][1] + g[2][1]) / 2)
    return g[1]


# --------------------------------------------------------------------------- 조사 → 항목
def items(res, P, purposes=("균열검토", "기타"), sheet="", with_unplaced=False, group=True):
    """검측위치 → 손상 항목 목록.
    group=True: 같은 균열번호(같은 검토자)는 한 줄로 묶고 개소 = 위치 수.
    group=False: 위치마다 한 줄 (개소 1, 사진·위치도 그 위치 것).
    항목마다 key(고르기 기억용)·uids(묶인 검측위치) 포함."""
    out, groups = [], {}
    byid = res.by_id()
    for r in sorted(res.surveys, key=lambda r: int(r.get("no") or 0)):
        if r.get("purpose") not in purposes:
            continue
        if not with_unplaced and not SV.is_placed(r):
            continue
        key = (r.get("owner") or "", r["label"]) if (group and r.get("label")) else r["uid"]
        groups.setdefault(key, []).append(r)
    for lst in groups.values():
        r = lst[0]
        fl = r.get("fields") or {}
        p = P.get(r.get("purpose"), {})
        ct = fl.get("ctype") if p.get("crack") else None
        it = {"no": r.get("label") or SV.no_text(r), "seq": 0, "member": "", "desc": "", "E": None, "F": None, "H": None, "I": None,
              "J": "m", "count": len([x for x in lst if SV.is_placed(x)]) or 1, "kind": "", "photos": [], "memo": r.get("memo", ""),
              "sheet": sheet, "inspector": r.get("inspector", ""), "purpose": r.get("purpose"),
              "uids": [x["uid"] for x in lst], "key": f"{sheet}|" + "|".join(str(v) for v in (key if isinstance(key, tuple) else (key,)))}
        m = byid.get(r.get("member"))
        placed = next((x for x in lst if SV.is_placed(x)), None)
        it["axis"] = axis_loc(res, *rec_point(placed, byid)) if placed else ""
        it["member"] = (fl.get("cmem") if ct else "") or r.get("name") or (m.name if m is not None and getattr(m, "name", "") else "") or MEMBER_FROM_TYPE.get(ct, "")
        if ct:
            shape = fl.get("shape")
            it["desc"] = ct.replace(" 미장균열", " 미장균열") + (f"({shape})" if shape else "")
            if ct in CRACKISH:
                it.update(E="cw=", F=_num(fl.get("crack_w")), H="/", I=_num(fl.get("crack_l")), kind="crack")
            elif ct == "이질재이격":
                it.update(E="cw=", F=_num(fl.get("gap_w")), H="/", I=_num(fl.get("gap_l")), kind="crack")
            elif ct == "누수":
                it.update(E="A=", F=_num(fl.get("leak_w")), H="x", I=_num(fl.get("leak_l")), kind="area")
            elif ct in ("백화", "열화"):
                it.update(E="A=", F=_num(fl.get("ar_b")), H="x", I=_num(fl.get("ar_l")), kind="area")
            elif ct in ("파손", "박리/박락"):
                it.update(E="A=", F=_mm2m(fl.get("dmg_b")), H="x", I=_mm2m(fl.get("dmg_d")), kind="area")
            elif ct == "철근노출":
                it.update(E="L=", F=_mm2m(fl.get("rebar_l")), H=None, I=None, J=None, kind="length")
            else:
                it.update(J=None, kind="etc")
            if fl.get("progress") and fl["progress"] != "없음":
                it["desc"] += f" 진행성 {fl['progress']}"
        else:
            it["desc"] = " ".join(x for x in (fl.get("item"), fl.get("desc")) if x) or SV.summary(r, P) or r.get("purpose", "")
            it.update(J=None, kind="etc")
        seen, ph_loc = [], {}
        for x in lst:
            ax = None
            for ph in x.get("photos") or []:
                if ph not in seen:
                    seen.append(ph)
                    if len(lst) > 1 and SV.is_placed(x):      # 위치마다 찍은 사진 → 그 위치의 축
                        if ax is None:
                            ax = axis_loc(res, *rec_point(x, byid))
                        ph_loc[ph] = ax
        it["photos"] = seen
        it["photo_axis"] = ph_loc
        out.append(it)
    for k, it in enumerate(out, 1):
        it["seq"] = k
    return out


def apply_pick(groups, off_uids=(), photo_off=()):
    """목록에서 고른 것만: off_uids(뺀 검측위치) · photo_off(뺀 사진) 반영한 새 groups."""
    off_uids, photo_off = set(off_uids), set(photo_off)
    out = []
    for name, its in groups:
        keep = []
        for it in its:
            uids = it.get("uids") or []
            on = [u for u in uids if u not in off_uids]
            if uids and not on:
                continue
            n = dict(it)
            if uids and len(on) < len(uids):
                n["count"] = max(1, min(it["count"], len(on)))
            n["photos"] = [p for p in it["photos"] if p not in photo_off]
            keep.append(n)
        for k, it in enumerate(keep, 1):
            it["seq"] = k
        if keep:
            out.append((name, keep))
    return out


def size_text(it):
    if it["kind"] == "crack":
        return f"cw={it['F'] if it['F'] is not None else '?'}mm, L={it['I'] if it['I'] is not None else '?'}m"
    if it["kind"] == "area":
        return f"{it['F'] if it['F'] is not None else '?'}m×{it['I'] if it['I'] is not None else '?'}m"
    if it["kind"] == "length":
        return f"L={it['F'] if it['F'] is not None else '?'}m"
    return ""


def photo_stem(p):
    return os.path.splitext(os.path.basename(str(p)))[0]


# --------------------------------------------------------------------------- 엑셀
def _load_wb(path):
    """회사 양식 그대로 — 사용자 정의 문서 속성 때문에 안 열리는 파일도 열리게."""
    import openpyxl
    try:
        return openpyxl.load_workbook(path)
    except TypeError:
        zin = zipfile.ZipFile(path)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for it in zin.infolist():
                if it.filename == "docProps/custom.xml":
                    continue
                d = zin.read(it.filename)
                if it.filename == "[Content_Types].xml":
                    d = re.sub(rb'<Override PartName="/docProps/custom.xml"[^>]*/>', b"", d)
                if it.filename == "_rels/.rels":
                    d = re.sub(rb'<Relationship[^>]*custom.xml"[^>]*/>', b"", d)
                zout.writestr(it, d)
        buf.seek(0)
        return openpyxl.load_workbook(buf)


def _safe_title(t, used):
    t = re.sub(r"[\[\]:*?/\\]", "_", t or "도면")[:28] or "도면"
    base, k = t, 2
    while t in used:
        t = f"{base[:25]}_{k}"
        k += 1
    used.add(t)
    return t


def write_excel(path, groups, template=None, log=print):
    """groups: [(도면명, items)] → 시트마다 한 도면. 반환: 줄 수 합계"""
    from copy import copy
    from openpyxl.utils import get_column_letter as CL
    wb = _load_wb(template or TEMPLATE)
    base = next((w for w in wb.worksheets if w.sheet_state == "visible"), wb.worksheets[0])
    originals = list(wb.worksheets)
    style = {c.column: c for c in base[2]}                     # 2행 서식을 모든 줄에
    from openpyxl.utils import column_index_from_string as CI
    widths = {}                                                # 양식의 열 너비 (A:B 처럼 묶인 범위도 펼침)
    for key, cd in base.column_dimensions.items():
        if cd.width:
            lo = cd.min or CI(key)
            hi = cd.max or lo
            for col in range(lo, min(hi, 60) + 1):
                widths[col] = cd.width
    ocol = style.get(15)
    h2 = base.row_dimensions[2].height
    used, total = set(), 0
    for name, its in groups:
        ws = wb.copy_worksheet(base)
        ws.title = _safe_title(name, used)
        ws.sheet_state = "visible"
        for rg in list(ws.merged_cells.ranges):
            if rg.min_row > 1:
                ws.unmerge_cells(str(rg))
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row)
        for c in ws[1]:
            if c.column > 15:
                c.value = None
        maxph = max([len(it["photos"]) for it in its] + [1])
        for k in range(maxph):                                  # 사진 열 머리글
            c = ws.cell(row=1, column=15 + k)
            if k:
                c.value = f"사진{k + 1}"
                src = base.cell(row=1, column=15)
                c.font, c.alignment, c.border, c.fill = copy(src.font), copy(src.alignment), copy(src.border), copy(src.fill)
        # 열 너비 = 양식 그대로 (사진 열이 양식보다 많으면 O열 너비로)
        from openpyxl.worksheet.dimensions import ColumnDimension, DimensionHolder
        ws.column_dimensions = DimensionHolder(worksheet=ws)        # 겹치는 열 범위(G:H 등) 없이 한 열씩 새로
        for col in range(1, max(20, 15 + maxph)):
            w = widths.get(col)
            if w is None and col > 15:
                w = widths.get(15)
            if w:
                ws.column_dimensions[CL(col)] = ColumnDimension(ws, index=CL(col), width=w, customWidth=True)
        for i, it in enumerate(its):
            r = 2 + i
            for col, src in style.items():
                c = ws.cell(row=r, column=col)
                if src.has_style:
                    c._style = copy(src._style)
            for k in range(1, maxph):
                if ocol is not None:
                    ws.cell(row=r, column=15 + k)._style = copy(ocol._style)
            if h2:
                ws.row_dimensions[r].height = h2
            vals = {1: it["no"], 2: it["seq"], 3: it["member"], 4: it["desc"], 5: it["E"], 6: it["F"],
                    7: f'=IF(LEFT(E{r},1)="c","mm","m")' if it["E"] else None, 8: it["H"], 9: it["I"], 10: it["J"],
                    11: it["count"] if it["count"] > 1 else None}
            if it["kind"] == "crack":                       # 균열: 길이 × 개소 (양식과 같음)
                vals[12] = f"=I{r}*IF(K{r}>0,K{r},1)"
            elif it["kind"] == "area":                      # 면적: F × I × 개소
                vals[12] = f"=F{r}*I{r}*IF(K{r}>0,K{r},1)"
            elif it["kind"] == "length":
                vals[12] = f"=F{r}*IF(K{r}>0,K{r},1)"
            for col, v in vals.items():
                ws.cell(row=r, column=col).value = v
            for k, ph in enumerate(it["photos"]):
                ws.cell(row=r, column=15 + k).value = photo_stem(ph)
        ws.print_area = f"B1:{CL(max(15, 14 + maxph))}{max(2, len(its) + 1)}"
        total += len(its)
        log(f"  엑셀 '{ws.title}': {len(its)}줄")
    for w in originals:
        wb.remove(w)
    wb.active = 0
    for v in wb.views:                                         # 양식의 숨긴 첫 시트 흔적 → 엑셀 '손상됨' 경고 방지
        v.firstSheet = 0
        v.activeTab = 0
    for i, w in enumerate(wb.worksheets):
        for sv in w.views.sheetView:
            sv.tabSelected = i == 0
    wb.save(path)
    return total


# --------------------------------------------------------------------------- 사진첩 (Word → 한글)
def album_blocks(groups, with_nophoto=False):
    """칸 목록: 사진마다 한 칸 (같은 항목 사진이 여러 장이면 내용 뒤에 -1, -2)."""
    out = []
    for name, its in groups:
        for it in its:
            body = " ".join(x for x in (f"[{it['no']}]", it["member"], it["desc"], size_text(it),
                                        f"({it['count']}개소)" if it["count"] > 1 else "") if x)
            loc = " ".join(x for x in (name, it.get("axis"), it["member"]) if x)
            phs = [p for p in it["photos"] if os.path.isfile(str(p))]
            if not phs:
                if with_nophoto:
                    out.append({"photo": None, "loc": loc, "body": body, "name": ""})
                continue
            pax = it.get("photo_axis") or {}
            for k, p in enumerate(phs):
                if p in pax:
                    loc = " ".join(x for x in (name, pax[p] or it.get("axis"), it["member"]) if x)
                out.append({"photo": p, "loc": loc, "body": body + (f"-{k + 1}" if len(phs) > 1 else ""), "name": photo_stem(p)})
    return out


def _cell_border(cell, sz=4):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcPr = cell._tc.get_or_add_tcPr()
    b = tcPr.find(qn("w:tcBorders"))
    if b is None:
        b = OxmlElement("w:tcBorders")
        tcPr.append(b)
    for side in ("top", "left", "bottom", "right"):
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), str(sz))
        e.set(qn("w:color"), "000000")
        b.append(e)


def _vcenter(cell):
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _fit_image(path, wmm, hmm):
    """칸에 맞춘 JPEG (가로세로 비율 유지, 회전 정보 반영) → (BytesIO, w_mm, h_mm)"""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    iw, ih = im.size
    k = min(wmm / iw, hmm / ih)
    w, h = iw * k, ih * k
    px = 1400 / max(iw, ih)
    if px < 1:
        im = im.resize((max(1, int(iw * px)), max(1, int(ih * px))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    buf.seek(0)
    return buf, w, h


def write_album_docx(path, blocks, title="", header="", section="", log=print):
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ROW_HEIGHT_RULE
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(20)
    sec.top_margin, sec.bottom_margin = Mm(18), Mm(15)
    sec.header_distance = Mm(10)
    st = doc.styles["Normal"]
    st.font.name = "맑은 고딕"
    st.font.size = Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    st.paragraph_format.space_after = Pt(0)
    st.paragraph_format.space_before = Pt(0)
    if header:
        hp = sec.header.paragraphs[0]
        hp.text = header
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for r in hp.runs:
            r.font.size = Pt(9)
    W_LAB, W_VAL = 14.0, 71.0            # 칸 하나 = 85 mm (위치·내용 머리 14 + 값 71)
    PH_H = 62.0
    pages = [blocks[i:i + 6] for i in range(0, len(blocks), 6)] or [[]]
    body = doc.element.body
    for pi, page in enumerate(pages):
        p = doc.add_paragraph() if pi else doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
        if pi:
            p.paragraph_format.page_break_before = True
        tab = p.paragraph_format.tab_stops
        tab.add_tab_stop(Mm(170), alignment=2)          # 오른쪽 탭
        r1 = p.add_run(f"●{title}" if title else "●현황조사 사진첩")
        r1.bold = True
        r1.font.size = Pt(11)
        if section:
            r2 = p.add_run(f"\t<{section}>")
            r2.font.size = Pt(10)
        p.paragraph_format.space_after = Pt(3)
        t = doc.add_table(rows=9, cols=4)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        tblPr = t._tbl.tblPr
        lay = OxmlElement("w:tblLayout")
        lay.set(qn("w:type"), "fixed")
        tblPr.append(lay)
        widths = [W_LAB, W_VAL, W_LAB, W_VAL]
        for row in t.rows:
            for ci, c in enumerate(row.cells):
                c.width = Mm(widths[ci])
        grid = t._tbl.tblGrid
        for ci, gc in enumerate(grid.findall(qn("w:gridCol"))):
            gc.set(qn("w:w"), str(int(widths[ci] * 56.7)))
        for b in range(3):
            pr, lr, cr = t.rows[b * 3], t.rows[b * 3 + 1], t.rows[b * 3 + 2]
            pr.height, pr.height_rule = Mm(PH_H), WD_ROW_HEIGHT_RULE.EXACTLY
            for rr in (lr, cr):
                rr.height, rr.height_rule = Mm(7.5), WD_ROW_HEIGHT_RULE.EXACTLY
            for side in range(2):
                k = b * 2 + side
                blk = page[k] if k < len(page) else None
                pc = pr.cells[side * 2].merge(pr.cells[side * 2 + 1])
                _vcenter(pc)
                pp = pc.paragraphs[0]
                pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                if blk and blk.get("photo"):
                    try:
                        buf, w, h = _fit_image(blk["photo"], W_LAB + W_VAL - 2, PH_H - 2)
                        pp.add_run().add_picture(buf, width=Mm(w), height=Mm(h))
                    except Exception as e:  # noqa: BLE001
                        pp.add_run(f"(사진을 열 수 없음: {os.path.basename(str(blk['photo']))})")
                        log(f"  사진 오류: {blk['photo']} — {e}")
                for rr, lab, key in ((lr, "위 치", "loc"), (cr, "내 용", "body")):
                    lc, vc = rr.cells[side * 2], rr.cells[side * 2 + 1]
                    for c in (lc, vc):
                        _vcenter(c)
                        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                    lc.paragraphs[0].add_run(lab).font.size = Pt(9.5)
                    v = (blk or {}).get(key) or ("-" if blk is None else "")
                    run = vc.paragraphs[0].add_run(v)
                    run.font.size = Pt(9 if len(v) < 34 else 8)
        for row in t.rows:
            for c in row.cells:
                _cell_border(c, 6)
    doc.save(path)
    return len(pages)


def docx_to_hwp(docx_path, hwp_path, log=print):
    """한글 자동화(한글 설치 PC)로 .docx → .hwp. 성공하면 True"""
    try:
        import win32com.client as win32
    except Exception:  # noqa: BLE001
        return False
    h = None
    try:
        try:
            h = win32.gencache.EnsureDispatch("HWPFrame.HwpObject")
        except Exception:  # noqa: BLE001
            h = win32.Dispatch("HWPFrame.HwpObject")
        try:
            h.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:  # noqa: BLE001
            pass
        try:
            h.XHwpWindows.Item(0).Visible = False
        except Exception:  # noqa: BLE001
            pass
        opened = False
        for fmt in ("OOXML", "DOCX", "MSWORD", ""):
            try:
                if h.Open(os.path.abspath(docx_path), fmt, "forceopen:true"):
                    opened = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not opened:
            log("  한글에서 Word 파일을 열지 못했습니다.")
            return False
        ok = h.SaveAs(os.path.abspath(hwp_path), "HWP", "")
        return bool(ok) and os.path.exists(hwp_path)
    except Exception as e:  # noqa: BLE001
        log(f"  한글 변환 실패: {e}")
        return False
    finally:
        if h is not None:
            try:
                h.Clear(1)
                h.Quit()
            except Exception:  # noqa: BLE001
                pass
