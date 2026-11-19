"""
table_io.py — 엑셀 / TXT / MIDAS Gen 표 가져오기·내보내기

가져오기
  · 엑셀(.xlsx/.xlsm), CSV, TXT(탭·쉼표·공백 정렬) → 2차원 표
  · 머리글 줄 자동 찾기 + 열 자동 매핑 (부족하면 매핑 창에서 고름)
  · MIDAS 처럼 '위치(I/M/J)' 열로 한 부재가 여러 줄인 표 → 단부/중앙부로 합침
  · 이 프로그램이 내보낸 엑셀·TXT 는 바로 읽음
내보내기
  · 엑셀: 부재 종류별 시트, 2단 머리글, 틀 고정
  · TXT : 탭 구분 ([beam] 구역마다 머리글 + 자료) — 다시 가져오기 가능
"""
from __future__ import annotations

import csv
import io
import os
import re

from . import model as M

LOC_AL = ("위치", "LOCATION", "LOC", "POS", "POSITION", "구간위치", "I/M/J", "IMJ", "PART", "부위")
GEN_AL = {
    "top": ("상부근", "상부", "상부철근", "TOP", "TOPBAR", "TOPREBAR", "REBARTOP", "ASTOP", "상단근", "NEGATIVE"),
    "bot": ("하부근", "하부", "하부철근", "BOT", "BOTTOM", "BOTBAR", "BOTREBAR", "REBARBOT", "ASBOT", "하단근", "POSITIVE"),
    "stir": ("늑근", "스터럽", "STIRRUP", "STIRRUPS", "STIR", "ST", "SHEAR", "SHEARREBAR", "늑근간격"),
}
TYPE_TITLES = {M.TYPES[t]["title"]: t for t in M.TYPES}


def hkey(s):
    return re.sub(r"[\s.:·()\[\]_/\-~,]", "", str(s or "")).upper()


def _alias_index(mtype, long_fmt=False):
    idx = {}
    for c in M.cols(mtype):
        for a in (c.full_title, c.title) + tuple(c.aliases):
            idx.setdefault(hkey(a), c.key)
    if long_fmt:
        for k, al in GEN_AL.items():
            for a in al:
                idx[hkey(a)] = "@" + k
        for a in LOC_AL:
            idx[hkey(a)] = "@loc"
    return idx


# ═══════════════════════════════════════════════════════════════════
#  읽기
# ═══════════════════════════════════════════════════════════════════
def read_grids(path):
    """→ {시트이름: [[str]]}"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xltx"):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
        out = {}
        for ws in wb.worksheets:
            merged = {}
            for rg in ws.merged_cells.ranges:
                v = ws.cell(rg.min_row, rg.min_col).value
                for r in range(rg.min_row, rg.max_row + 1):
                    for c in range(rg.min_col, rg.max_col + 1):
                        merged[(r, c)] = v
            grid = []
            for r in range(1, (ws.max_row or 0) + 1):
                row = []
                for c in range(1, (ws.max_column or 0) + 1):
                    v = merged.get((r, c), ws.cell(r, c).value)
                    row.append(_s(v))
                grid.append(row)
            while grid and not any(grid[-1]):
                grid.pop()
            out[ws.title] = grid
        return out
    if ext == ".xls":
        raise ValueError("옛 엑셀(.xls)은 엑셀에서 .xlsx 로 저장한 뒤 가져오세요.")
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp949", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return {os.path.basename(path): split_text(text)}


def _s(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def split_text(text):
    lines = [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    sample = "\n".join(lines[:200])
    if "\t" in sample:
        return [[c.strip() for c in ln.split("\t")] for ln in lines]
    if sample.count(",") > sample.count("\n"):
        return [[c.strip() for c in r] for r in csv.reader(io.StringIO("\n".join(lines)))]
    return split_fixed(lines)


def split_fixed(lines):
    """공백 정렬 표 (MIDAS 텍스트 출력 등): 모든 줄이 비어 있는 세로 띠를 열 경계로."""
    L = [ln.rstrip().expandtabs(8) for ln in lines]
    rows = [ln for ln in L if ln.strip()]
    if not rows:
        return [[] for _ in L]
    width = max(len(ln) for ln in rows)
    occ = [0] * width
    for ln in rows:
        for i, ch in enumerate(ln):
            if ch != " ":
                occ[i] += 1
    spans = []
    i = 0
    while i < width:
        if occ[i]:
            j = i
            while j < width and occ[j]:
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    out = []
    for ln in L:
        if not ln.strip():
            out.append([])
            continue
        cells = [""] * len(spans)
        for m in re.finditer(r"\S+", ln):
            c = (m.start() + m.end()) / 2
            k = min(range(len(spans)), key=lambda q: 0 if spans[q][0] <= c < spans[q][1] else
                    min(abs(c - spans[q][0]), abs(c - spans[q][1])))
            cells[k] = (cells[k] + " " + m.group()).strip()
        out.append(cells)
    return out


def own_format(grids):
    """이 프로그램이 내보낸 파일인지 → {mtype: rows} 또는 None."""
    res = {}
    for name, g in grids.items():
        g = [r for r in g if not (r and r[0].startswith("#"))]
        if g and g[0] and g[0][0].startswith("[") and g[0][0].strip("[]") in M.TYPES:
            cur = None
            hdr = None
            for row in g:
                if row and row[0].startswith("[") and row[0].strip("[]") in M.TYPES:
                    cur = row[0].strip("[]")
                    hdr = None
                    res.setdefault(cur, [])
                    continue
                if cur is None or not any(row):
                    continue
                if hdr is None:
                    hdr = row
                    continue
                res[cur].append(_map_row(cur, hdr, row))
            continue
        t = TYPE_TITLES.get(name.strip())
        if t and len(g) >= 3:
            hdr = _combine(g, 1)
            res[t] = [_map_row(t, hdr, row) for row in g[2:] if any(row)]
    return res or None


def _map_row(mtype, hdr, row):
    idx = _alias_index(mtype)
    r = M.new_row(mtype)
    for i, h in enumerate(hdr):
        k = idx.get(hkey(h))
        if k and i < len(row):
            r[k] = row[i]
    return r


def _combine(grid, h):
    """머리글 줄 h + 바로 위 줄(병합된 그룹 이름) 합치기."""
    row = grid[h]
    up = grid[h - 1] if h > 0 else []
    out = []
    for i, v in enumerate(row):
        g = up[i] if i < len(up) else ""
        out.append(f"{g} {v}" if g and v and g != v else (v or g))
    return out


def detect_header(grid, mtype, long_fmt=None):
    """→ (머리글 줄 번호, 합친 머리글, 자동 매핑 {키: 열}, long_fmt)"""
    best = (-1, 0, [], {}, False)
    for h in range(min(len(grid), 30)):
        for lf in ((False, True) if long_fmt is None else (long_fmt,)):
            idx = _alias_index(mtype, lf)
            for hdr in (grid[h], _combine(grid, h)):
                mp = {}
                for i, v in enumerate(hdr):
                    k = idx.get(hkey(v))
                    if k and k not in mp:
                        mp[k] = i
                score = len(mp) + (2 if "name" in mp else 0) + (1 if lf and "@loc" in mp else 0) - (3 if lf and "@loc" not in mp else 0)
                if score > best[1]:
                    best = (h, score, hdr, mp, lf)
    h, hdr, mp, lf = best[0], best[2], best[3], best[4]
    if h >= 0 and "name" in mp:                       # 부재번호보다 부재 이름(2G1 등) 열을 우선
        from .parse_layout import is_name
        idx = _alias_index(mtype, lf)
        cands = [i for i, v in enumerate(hdr) if idx.get(hkey(v)) == "name"]
        if len(cands) > 1:
            body = grid[h + 1:h + 60]
            score = lambda i: sum(1 for r in body if i < len(r) and r[i] and is_name(r[i]))
            mp["name"] = max(cands, key=score)
    return h, hdr, mp, lf


def apply_mapping(grid, hdr_row, mapping, mtype, long_fmt=False, pfx="D"):
    """mapping: {키: 열번호}  (long_fmt: '@loc','@top','@bot','@stir')"""
    out = []
    body = grid[hdr_row + 1:]
    colinfo = {c.key: c for c in M.cols(mtype)}

    def val(row, i):
        return row[i].strip() if i is not None and 0 <= i < len(row) else ""

    if not long_fmt:
        for row in body:
            if not any(row):
                continue
            r = M.new_row(mtype)
            if mtype == "beam":
                r["slab"] = ""
            for k, i in mapping.items():
                if k.startswith("@") or i is None:
                    continue
                c = colinfo[k]
                r[k] = M.normalize(c.kind, val(row, i), pfx, c.choices)
            if (r.get("name") or "").strip():
                if mtype == "beam":
                    _fix_kind(r)
                out.append(r)
        return out

    # MIDAS 형: 위치 열로 묶기
    groups = {}
    order = []
    for row in body:
        if not any(row):
            continue
        name = val(row, mapping.get("name"))
        if not name:
            continue
        if name not in groups:
            groups[name] = {"base": row, "loc": {}}
            order.append(name)
        loc = _loc(val(row, mapping.get("@loc")), len(groups[name]["loc"]))
        groups[name]["loc"].setdefault(loc, row)
    for name in order:
        g = groups[name]
        r = M.new_row(mtype)
        r["slab"] = "" if mtype == "beam" else r.get("slab", "")
        for k, i in mapping.items():
            if not k.startswith("@") and i is not None:
                c = colinfo[k]
                r[k] = M.normalize(c.kind, val(g["base"], i), pfx, c.choices)
        locs = g["loc"]

        def zone(row):
            return (M.norm_rebar(val(row, mapping.get("@top")), pfx), M.norm_rebar(val(row, mapping.get("@bot")), pfx),
                    M.norm_stir(val(row, mapping.get("@stir")), pfx))
        zi, zm, zj = (zone(locs[k]) if k in locs else None for k in ("I", "M", "J"))
        if zm and not zi and not zj:
            r["kind"] = "전단면"
            zi = zm
            zm = None
        elif zi and zj and zi != zj:
            r["kind"] = "외단/중앙/내단"
        elif zi and not zm:
            r["kind"] = "전단면"
        else:
            r["kind"] = "양단/중앙"
        zi = zi or zj
        for p, z in (("e_", zi), ("m_", zm), ("j_", zj if r["kind"] == "외단/중앙/내단" else None)):
            if z:
                r[p + "top"], r[p + "bot"], r[p + "stir"] = z
        out.append(r)
    return out


def _loc(v, n):
    k = hkey(v)
    if k in ("I", "ENDI", "I단", "단부", "양단부", "외단부", "좌단부", "END", "1", "START", "LEFT"):
        return "I"
    if k in ("M", "MID", "MIDDLE", "중앙", "중앙부", "CENTER", "2", "C"):
        return "M"
    if k in ("J", "ENDJ", "J단", "내단부", "우단부", "3", "LAST", "RIGHT"):
        return "J"
    return ("I", "M", "J")[min(n, 2)]


def _fix_kind(r):
    """구분 칸이 비었으면 채워진 칸으로 판단."""
    if r.get("kind") in M.BEAM_KINDS:
        return
    has_m = any(r.get("m_" + s) for s in ("top", "bot", "stir"))
    has_j = any(r.get("j_" + s) for s in ("top", "bot", "stir"))
    r["kind"] = "외단/중앙/내단" if has_j else ("양단/중앙" if has_m else "전단면")


# ═══════════════════════════════════════════════════════════════════
#  내보내기
# ═══════════════════════════════════════════════════════════════════
def export_txt(path, project, types=None):
    lines = ["# StrCAD Auto Table  (탭 구분, 이 파일을 다시 가져올 수 있습니다)"]
    for t in types or M.TYPE_KEYS:
        rows = M.clean_rows(t, project.rows[t])
        if not rows:
            continue
        lines.append(f"[{t}]")
        lines.append("\t".join(c.full_title for c in M.cols(t)))
        for r in rows:
            lines.append("\t".join((r.get(c.key) or "").replace("\t", " ") for c in M.cols(t)))
        lines.append("")
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines))


def export_excel(path, project, types=None):
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="9AA3B2")
    bd = Border(left=thin, right=thin, top=thin, bottom=thin)
    hfill = PatternFill("solid", fgColor="1E2A44")
    gfill = PatternFill("solid", fgColor="2B3B5C")
    hfont = Font(name="맑은 고딕", bold=True, color="FFFFFF", size=10)
    font = Font(name="맑은 고딕", size=10)
    bold = Font(name="맑은 고딕", size=10, bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center")
    n = 0
    for t in types or M.TYPE_KEYS:
        rows = M.clean_rows(t, project.rows[t])
        if not rows and types is None:
            continue
        n += 1
        ws = wb.create_sheet(M.TYPES[t]["title"])
        cs = M.cols(t)
        i = 0
        while i < len(cs):
            c = cs[i]
            if c.group:
                j = i
                while j + 1 < len(cs) and cs[j + 1].group == c.group:
                    j += 1
                ws.cell(1, i + 1, c.group)
                if j > i:
                    ws.merge_cells(start_row=1, start_column=i + 1, end_row=1, end_column=j + 1)
                for k in range(i, j + 1):
                    ws.cell(2, k + 1, cs[k].title)
                i = j + 1
            else:
                ws.cell(1, i + 1, c.title)
                ws.merge_cells(start_row=1, start_column=i + 1, end_row=2, end_column=i + 1)
                i += 1
        for ci, c in enumerate(cs, start=1):
            for rr in (1, 2):
                cell = ws.cell(rr, ci)
                cell.fill = gfill if (rr == 1 and c.group) else hfill
                cell.font = hfont
                cell.alignment = center
                cell.border = bd
            ws.column_dimensions[get_column_letter(ci)].width = max(7, c.width / 7.2)
        for ri, r in enumerate(rows, start=3):
            for ci, c in enumerate(cs, start=1):
                v = r.get(c.key, "")
                if c.kind == "num" and v:
                    try:
                        v = int(v) if float(v).is_integer() else float(v)
                    except ValueError:
                        pass
                elif t == "beam" and M.disabled(t, r, c.key):
                    v = ""
                elif c.kind == "drawn":
                    v = M.drawn_label(r, t)
                cell = ws.cell(ri, ci, v)
                cell.font = bold if c.key == "name" else font
                cell.alignment = left if c.key in ("name", "note", "floor") else center
                cell.border = bd
        ws.freeze_panes = "B3"
        ws.row_dimensions[1].height = 20
        ws.row_dimensions[2].height = 20
    if n == 0:
        wb.create_sheet("보")
    wb.save(path)


# ═══════════════════════════════════════════════════════════════════
#  MIDAS Gen MGT  (*REBAR-BEAM ; Modify Beam Rebar Data)
#  한 단면 = 4줄:  1) iSEC, iSUBSEC, 늑근이름, dT, dB, …, bSAMETOPBOT, bSAMEIMJ, bSAMELAYER
#                 2~4) I / 중앙(M) / J :
#                    상부 [배치, 1단개수, 2단개수, 1단이름, 2단이름], 하부 [같음], 늑근간격, 늑근다리수, 측면근수
#  *SECTION 이 같이 있으면 단면 이름(2G1 등)·B·H 도 읽음,  *UNIT 으로 길이 단위
# ═══════════════════════════════════════════════════════════════════
def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp949", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def is_mgt(text):
    return "*REBAR-BEAM" in text.upper()


def _mgt_blocks(text):
    blocks = {}
    cur = None
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("*"):
            cur = s.split(";")[0].strip().upper()
            blocks.setdefault(cur, [])
            continue
        if s.startswith(";") or cur is None:
            continue
        blocks[cur].append(s.split(";")[0])
    return blocks


def _toks(line):
    return [t.strip() for t in line.split(",")]


def parse_mgt(text):
    """→ (rows, warnings)"""
    blocks = _mgt_blocks(text)
    warn = []
    unit = 1000.0                                   # 기본 m → mm
    for ln in blocks.get("*UNIT", [])[:1]:
        t = _toks(ln)
        if len(t) > 1:
            unit = {"M": 1000.0, "CM": 10.0, "MM": 1.0, "IN": 25.4, "FT": 304.8}.get(t[1].upper(), 1000.0)
    unit_known = bool(blocks.get("*UNIT"))

    secs = {}                                       # iSEC → (이름, B, H)
    for ln in blocks.get("*SECTION", []):
        t = _toks(ln)
        if len(t) < 3 or not t[0].isdigit():
            continue
        name = t[2]
        B = H = ""
        up = [x.upper() for x in t]
        for shp in ("SB", "SR"):
            if shp in up[3:]:
                i = up.index(shp, 3)
                if i + 3 < len(t) and t[i + 1] == "2":
                    try:
                        d1, d2 = float(t[i + 2]), float(t[i + 3])
                        if shp == "SB":                 # 직사각형: H, B
                            H, B = M.norm_num(str(d1 * unit)), M.norm_num(str(d2 * unit))
                        else:
                            B = M.norm_num(str(d1 * unit))
                    except ValueError:
                        pass
                break
        secs[t[0]] = (name, B, H)

    recs = []
    for ln in blocks.get("*REBAR-BEAM", []):
        t = _toks(ln)
        if t and t[-1].upper() in ("YES", "NO") and t[0].isdigit():
            recs.append({"head": t, "lines": []})
        elif recs:
            recs[-1]["lines"].append(t)

    def bars(n1, n2, a, b):
        try:
            n1, n2 = int(float(n1 or 0)), int(float(n2 or 0))
        except ValueError:
            return ""
        a, b = (a or "").upper(), (b or a or "").upper()
        if n1 == 0 and n2 == 0:
            return ""
        if n2 == 0:
            return f"{n1}-{a}"
        if a == b:
            return f"{n1}/{n2}-{a}"
        return f"{n1}-{a}/{n2}-{b}"

    rows = []
    for rec in recs:
        h = rec["head"]
        isec = h[0]
        stir_name = (h[2] or "D10").upper()
        zones = []
        for t in rec["lines"][:3]:
            t = t + [""] * (13 - len(t))
            top = bars(t[1], t[2], t[3], t[4])
            bot = bars(t[6], t[7], t[8], t[9])
            try:
                sp = float(t[10] or 0)
                if not unit_known and sp < 5:
                    sp *= 1000.0
                elif unit_known:
                    sp *= unit
                legs = int(float(t[11] or 2))
            except ValueError:
                sp, legs = 0, 2
            stir = (f"{legs}-" if legs not in (0, 2) else "") + f"{stir_name}@{M.norm_num(str(round(sp)))}" if sp else ""
            zones.append((top, bot, stir))
        if not zones:
            warn.append(f"단면 {isec}: 배근 줄이 없음")
            continue
        while len(zones) < 3:
            zones.append(zones[0])
        zi, zm, zj = zones
        name, B, H = secs.get(isec, (isec, "", ""))
        r = M.new_row("beam")
        r.update({"name": name, "b": B, "h": H, "slab": ""})
        if zi == zm == zj:
            r["kind"] = "전단면"
            r["e_top"], r["e_bot"], r["e_stir"] = zi
        else:
            r["kind"] = "양단/중앙" if zi == zj else "외단/중앙/내단"
            r["e_top"], r["e_bot"], r["e_stir"] = zi
            r["m_top"], r["m_bot"], r["m_stir"] = zm
            if zi != zj:
                r["j_top"], r["j_bot"], r["j_stir"] = zj
        r["note"] = f"MIDAS 단면 {isec}" if name != isec else ""
        rows.append(r)
    if rows and not secs:
        warn.append("*SECTION 자료가 없어 부호는 MIDAS 단면 번호, B·H 는 빈칸입니다. "
                    "MGT 전체(*SECTION 포함)를 가져오면 단면 이름·크기도 채워집니다.")
    return rows, warn
