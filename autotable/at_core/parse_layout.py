"""
parse_layout.py — 글자 위치로 일람표 읽기 (CAD · PDF · 사진 공통)

입력: 글자 목록 TItem(text, x, y, h, rot)  — y 는 위쪽이 + (CAD 좌표계)
      치수 목록 DimItem(x, y, value, angle)  — CAD 치수 (사진·PDF 는 숫자 글자로 대신)
출력: 부재 종류별 행 dict 리스트 (model.TYPES 열 키)

보 일람표   : 부호 줄 → 그 아래 '양단부/중앙부/전단면' 줄 → 같은 칸 아래 상부근/하부근/늑근
기둥 일람표 : 왼쪽에 '부호/층/단면/주근/대근/보조대근' 줄 이름, 오른쪽으로 부재가 한 칸씩
벽·슬래브   : 머리글 줄(부호/두께/수직근…) 아래로 한 줄에 한 부재
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from . import model as M


@dataclass
class TItem:
    text: str
    x: float
    y: float
    h: float = 1.0
    rot: float = 0.0
    layer: str = ""

    @property
    def key(self):
        return re.sub(r"[\s.:·()\[\]]", "", self.text).upper()


@dataclass
class DimItem:
    x: float
    y: float
    value: float
    angle: float          # 0 = 가로 치수, 90 = 세로 치수


ZONE = {"양단부": "E", "단부": "E", "외단부": "E", "좌단부": "E", "I단": "E", "I단부": "E", "END": "E", "END-I": "E",
        "ENDI": "E", "중앙부": "M", "중앙": "M", "MID": "M", "CENTER": "M", "내단부": "J", "우단부": "J", "J단": "J",
        "J단부": "J", "END-J": "J", "ENDJ": "J", "전단면": "A", "전구간": "A", "ALL": "A", "TYPICAL": "A"}
BEAM_ROWS = {"부호": "name", "부재": "name", "MARK": "name", "단면": "sec", "SECTION": "sec",
             "상부근": "top", "상부": "top", "상단근": "top", "상부철근": "top", "TOP": "top", "TOPBAR": "top",
             "하부근": "bot", "하부": "bot", "하단근": "bot", "하부철근": "bot", "BOT": "bot", "BOTTOM": "bot", "BOTBAR": "bot",
             "늑근": "stir", "스터럽": "stir", "STIRRUP": "stir", "STIRRUPS": "stir", "STIR": "stir", "ST": "stir",
             "크기": "size", "SIZE": "size", "BXH": "size", "B×H": "size"}
COL_ROWS = {"부호": "name", "부재": "name", "MARK": "name", "층": "floor", "구간": "floor", "적용층": "floor", "FLOOR": "floor",
            "단면": "sec", "크기": "size", "SIZE": "size", "BXD": "size", "B×D": "size", "주근": "main", "주철근": "main",
            "MAIN": "main", "대근": "hoop_m", "띠철근": "hoop_m", "HOOP": "hoop_m", "TIE": "hoop_m", "대근단부": "hoop_e",
            "단부대근": "hoop_e", "대근중앙": "hoop_m", "중앙대근": "hoop_m", "보조대근": "tie_x", "보조대근X": "tie_x",
            "X보조대근": "tie_x", "보조대근Y": "tie_y", "Y보조대근": "tie_y", "비고": "note"}

_NAME_RE = re.compile(r"^[-(]?\d{0,3}[A-Z]{1,4}\d{1,3}[A-Z]?(?:[-~]\d{1,2}[A-Z]?)?\)?$")
_NUM_RE = re.compile(r"^\d{2,4}$")
_SIZE_RE = re.compile(r"^[(\[]?(\d{2,4})\s*[X×*]\s*(\d{2,4})[)\]]?$")
_ROUND_RE = re.compile(r"^[ØΦφD]?(\d{3,4})(?:Ø|Φ)?$")


def fix_ocr(t: str) -> str:
    """사진 글자 인식에서 흔한 혼동 바로잡기."""
    s = t.strip().replace("＠", "@").replace("®", "@").replace("©", "@").replace("—", "-").replace("–", "-")
    s = re.sub(r"(?<=\d)[Oo](?=[\d@]|$)", "0", s)
    s = re.sub(r"(?<=[@\d])[Oo]", "0", s)
    s = re.sub(r"(?<=\d)[Il|](?=\d)", "1", s)
    s = re.sub(r"(?<=[A-Z])[Oo](?=\d)", "0", s)
    s = re.sub(r"^0(?=\d+@)", "D", s)               # 'O10@200' → 'D10@200'
    return s


def is_dash(t):
    return M.is_empty_mark(t.strip())


def as_rebar(t):
    s = fix_ocr(t)
    if is_dash(s):
        return "-"
    n = M.norm_rebar(s, "D")
    return n if M.parse_rebar(n) else None


def as_stir(t):
    s = fix_ocr(t)
    n = M.norm_stir(s, "D")
    return n if M.parse_stir(n) else None


def as_spacing(t):
    s = fix_ocr(t)
    if is_dash(s):
        return "-"
    n = M.norm_spacing(s, "D")
    return n if M.parse_spacing(n) else None


def is_name(t):
    k = re.sub(r"\s", "", t).upper()
    if k in ZONE or k in BEAM_ROWS or k in COL_ROWS:
        return False
    if as_stir(k):
        return False
    return bool(_NAME_RE.match(k))


def _med(vals, default):
    vals = [v for v in vals if v > 0]
    return statistics.median(vals) if vals else default


def _rows_of(items, tol):
    """y 로 묶기 → [[items]] (위에서 아래로)."""
    out = []
    for it in sorted(items, key=lambda i: -i.y):
        if out and abs(out[-1][0].y - it.y) < tol:
            out[-1].append(it)
        else:
            out.append([it])
    return out


def _clusters(vals, tol):
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] < tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


# ═══════════════════════════════════════════════════════════════════
#  보 일람표
# ═══════════════════════════════════════════════════════════════════
def parse_beams(items: list[TItem], dims: list[DimItem] = (), log=print):
    """→ (rows, info)  rows: 보 행 dict, info: {'members':[(name, x, y, zones)], 'warn':[...]}"""
    items = [i for i in items if i.text and i.text.strip()]
    zones = [i for i in items if i.key in ZONE]
    warn = []
    if not zones:
        rows = parse_cards(items, BEAM_ROWS, "beam", dims)
        if rows:
            return rows, {"warn": ["양단부/중앙부/전단면 표시가 없어 '부호 줄 + 같은 칸 아래 값' 방식으로 읽었습니다."],
                          "members": len(rows)}
        rows, warn2 = parse_beams_nolabel(items, dims)
        return rows, {"warn": warn2, "members": len(rows)}
    u = _med([z.h for z in zones], 1.0)
    labels = [i for i in items if i.key in BEAM_ROWS]
    names = [i for i in items if is_name(i.text)]

    # 칸 폭: 같은 줄 구역 표시 사이 간격
    gaps = []
    for row in _rows_of(zones, 0.7 * u):
        xs = sorted(z.x for z in row)
        gaps += [b - a for a, b in zip(xs, xs[1:]) if 4 * u < b - a < 45 * u]
    W = _med(gaps, 25 * u)
    W = min(W, _med([g for g in gaps], W))

    # 구역 → 부재 이름
    members = {}           # id(name item) → dict
    for zrow in _rows_of(zones, 0.7 * u):
        zy = statistics.mean(z.y for z in zrow)
        cand = [n for n in names if 1.2 * u < n.y - zy < 9 * u]
        if not cand:
            for z in zrow:
                warn.append(f"'{z.text}'({z.x:.0f},{z.y:.0f}) 위에서 부호를 못 찾음")
            continue
        dmin = min(n.y - zy for n in cand)
        nrow = [n for n in cand if n.y - zy < dmin + 0.8 * u]
        for z in zrow:
            n = min(nrow, key=lambda n: abs(n.x - z.x))
            if abs(n.x - z.x) > 2.2 * W:
                warn.append(f"'{z.text}' 칸의 부호가 너무 멀어 건너뜀")
                continue
            m = members.setdefault(id(n), {"name": n, "zones": {}, "zy": zy})
            m["zones"].setdefault(ZONE[z.key], z)

    if not members:
        return [], {"warn": warn or ["부재를 찾지 못했습니다."], "members": []}

    zone_items = [z for m in members.values() for z in m["zones"].values()]
    name_items = [m["name"] for m in members.values()]
    sheets = _clusters([l.x for l in labels if BEAM_ROWS[l.key] in ("name", "sec", "top", "bot", "stir")], 40 * u)

    def sheet_of(x):
        return sum(1 for s in sheets if s < x + 2 * u)

    def label_for(v):
        best = None
        for lb in labels:
            if BEAM_ROWS[lb.key] not in ("top", "bot", "stir"):
                continue
            if lb.x >= v.x or v.x - lb.x > 300 * u or sheet_of(lb.x) != sheet_of(v.x):
                continue
            dy = abs(lb.y - v.y)
            if dy < 0.9 * max(u, lb.h) and (best is None or dy < best[0]):
                best = (dy, BEAM_ROWS[lb.key])
        return best[1] if best else None

    rows = []
    for m in members.values():
        n = m["name"]
        row = M.new_row("beam")
        row["name"] = n.text.strip()
        row["slab"] = ""
        got = {}
        sizes = []
        cells = []
        for zt, z in m["zones"].items():
            # 이 칸의 아래쪽 끝 = 같은 칸 아래 다음 구역표시/부호
            below = [o for o in zone_items if o.y < z.y - 2 * u and abs(o.x - z.x) < 0.5 * W] + \
                    [o for o in name_items if o.y < z.y - 2 * u and abs(o.x - z.x) < 1.7 * W]
            limit = max((o.y for o in below), default=z.y - 70 * u) + 0.5 * u
            col = [v for v in items if abs(v.x - z.x) < 0.48 * W and limit < v.y < z.y - 0.6 * u and v is not z]
            vals = []
            for v in col:
                st = as_stir(v.text)
                rb = None if st else as_rebar(v.text)
                if st or rb:
                    vals.append((v, st, rb))
            vals.sort(key=lambda t: -t[0].y)
            zone = {}
            order = []
            for v, st, rb in vals:
                lab = label_for(v)
                if lab == "stir" or (lab is None and st):
                    zone.setdefault("stir", st or rb)
                elif lab in ("top", "bot"):
                    zone.setdefault(lab, rb or st)
                else:
                    order.append(rb)
            for val in order:                       # 줄 이름이 없으면 위에서부터 상부·하부
                for k in ("top", "bot"):
                    if k not in zone:
                        zone[k] = val
                        break
            got[zt] = zone
            # 단면 크기 (치수)
            ybot = min((t[0].y for t in vals), default=limit)
            sec_top = z.y
            B = H = None
            for d in dims:
                if abs(d.x - z.x) < 0.65 * W and ybot < d.y < sec_top:
                    if abs(d.angle % 180) < 10 or abs(d.angle % 180) > 170:
                        B = B or d.value
                    else:
                        H = H or d.value
            if B is None or H is None:              # 사진·PDF: 숫자 글자
                nums = [v for v in items if _NUM_RE.match(v.text.strip()) and abs(v.x - z.x) < 0.6 * W
                        and ybot + 0.5 * u < v.y < sec_top - 0.5 * u and 100 <= int(v.text.strip()) <= 6000]
                vert = [v for v in nums if 60 < abs(v.rot % 180) < 120]
                hor = [v for v in nums if v not in vert]
                if H is None and vert:
                    H = float(vert[0].text)
                if B is None and hor:
                    hor.sort(key=lambda v: -v.y)
                    B = float(hor[0].text)
                    if H is None and len(hor) > 1:
                        H = float(min(hor[1:], key=lambda v: v.x).text)
            if B or H:
                sizes.append((B, H))
            cells.append((z.x, ybot, sec_top, W))
        kinds = set(got)
        if kinds == {"A"}:
            row["kind"] = "전단면"
            mp = {"A": "e_"}
        elif kinds == {"M"}:
            row["kind"] = "전단면"
            mp = {"M": "e_"}
        elif "J" in kinds:
            row["kind"] = "외단/중앙/내단"
            mp = {"E": "e_", "M": "m_", "J": "j_", "A": "e_"}
        else:
            row["kind"] = "양단/중앙"
            mp = {"E": "e_", "M": "m_", "A": "e_"}
        for zt, zone in got.items():
            p = mp.get(zt)
            if not p:
                continue
            row[p + "top"] = zone.get("top", "")
            row[p + "bot"] = zone.get("bot", "")
            row[p + "stir"] = zone.get("stir", "")
        bs = [s[0] for s in sizes if s[0]]
        hs = [s[1] for s in sizes if s[1]]
        row["b"] = M.norm_num(str(bs[0])) if bs else ""
        row["h"] = M.norm_num(str(hs[0])) if hs else ""
        if not bs or not hs:
            warn.append(f"{row['name']}: 단면 크기(치수)를 못 읽음")
        row["_sort"] = (sheet_of(n.x), -round(m["zy"] / (3 * u)), n.x)
        row["_pos"] = (n.x, n.y)
        row["_cells"] = cells
        rows.append(row)
    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        r.pop("_sort", None)
    return rows, {"warn": warn, "members": len(rows), "unit": u, "col_w": W}


def parse_beams_nolabel(items, dims=()):
    """한글 표시를 못 읽은 경우(사진 글자 인식): 부호 + 늑근/철근 값의 위치만으로 읽기.
    · 부재 칸 = 같은 줄 부호들 사이 중간점으로 나눔
    · 칸 안 값의 x 묶음 = 구역 (1개: 전단면, 2개: 양단/중앙, 3개: 외단/중앙/내단)
    · 늑근 줄 기준 한 줄 위 = 하부근, 두 줄 위 = 상부근"""
    warn = []
    vals = []
    for i in items:
        st = as_stir(i.text)
        rb = None if st else as_rebar(i.text)
        if st or (rb and rb != "-"):
            vals.append((i, st, rb))
    names = [i for i in items if is_name(i.text) and not as_rebar(i.text)]
    stirs = [v for v in vals if v[1]]
    if not names or not stirs:
        return [], ["부호나 늑근 값을 찾지 못했습니다."]
    u = _med([v[0].h for v in vals], 1.0)
    # 줄 간격: 늑근 ↔ 바로 위 철근
    pitch = []
    for v, st, _ in stirs:
        up = [w for w, s2, r2 in vals if r2 and abs(w.x - v.x) < 3 * u and 0.5 * u < w.y - v.y < 8 * u]
        if up:
            pitch.append(min(w.y - v.y for w in up))
    p = _med(pitch, 2.4 * u)
    rows = []
    nrows = _rows_of(names, 0.8 * u)
    for nrow in nrows:
        nrow.sort(key=lambda n: n.x)
        xs = [n.x for n in nrow]
        sp = _med([b - a for a, b in zip(xs, xs[1:])], 60 * u)
        for k, n in enumerate(nrow):
            x0 = (xs[k - 1] + n.x) / 2 if k else n.x - sp / 2
            x1 = (xs[k + 1] + n.x) / 2 if k + 1 < len(xs) else n.x + sp / 2
            lower = [m.y for m in names if m.y < n.y - 3 * u and x0 - u < m.x < x1 + u]
            ylim = max(lower) + 0.5 * u if lower else n.y - 80 * u
            mine = [v for v in vals if x0 <= v[0].x < x1 and ylim < v[0].y < n.y - u]
            ms = [v for v in mine if v[1]]
            if not ms:
                continue
            cols = _clusters([v[0].x for v in ms], 5 * u)
            row = M.new_row("beam")
            row["name"] = n.text.strip()
            row["slab"] = ""
            kind = {1: "전단면", 2: "양단/중앙"}.get(len(cols), "외단/중앙/내단")
            row["kind"] = kind
            prefixes = {1: ["e_"], 2: ["e_", "m_"]}.get(len(cols), ["e_", "m_", "j_"])
            sizes = []
            for cx, pre in zip(cols[:3], prefixes):
                col = [v for v in mine if abs(v[0].x - cx) < 5 * u]
                st = [v for v in col if v[1]]
                ys = st[0][0].y
                row[pre + "stir"] = st[0][1]
                row[pre + "top"] = "-"
                for v, _, rb in col:
                    if rb:
                        kk = round((v.y - ys) / p)
                        if kk == 1:
                            row[pre + "bot"] = rb
                        elif kk == 2:
                            row[pre + "top"] = rb
                top_y = ys + 2.5 * p
                nums = [i for i in items if _NUM_RE.match(i.text.strip()) and abs(i.x - cx) < 0.6 * (x1 - x0) / max(1, len(cols))
                        and top_y < i.y < n.y - u and 100 <= int(i.text.strip()) <= 6000]
                vert = [i for i in nums if 60 < abs(i.rot % 180) < 120]
                hor = sorted([i for i in nums if i not in vert], key=lambda i: -i.y)
                if hor or vert:
                    B = hor[0].text.strip() if hor else ""
                    if vert:
                        H = max(vert, key=lambda i: int(i.text.strip())).text.strip()
                    else:
                        rest = [i for i in hor[1:] if i.x < hor[0].x]
                        H = min(rest, key=lambda i: i.x).text.strip() if rest else ""
                    sizes.append((B, H))
            if sizes:
                row["b"], row["h"] = sizes[0]
            else:
                row["b"] = row["h"] = ""
                warn.append(f"{row['name']}: 단면 크기를 못 읽음")
            rows.append(row)
    warn.insert(0, "한글 글자를 읽지 못해 위치로 판단했습니다 — 구분(양단/중앙/전단면)과 값을 꼭 확인하세요.")
    return rows, warn


# ═══════════════════════════════════════════════════════════════════
#  카드형 (왼쪽 줄 이름 + 오른쪽 부재 칸) — 기둥, 구역 표시 없는 보
# ═══════════════════════════════════════════════════════════════════
def _size(t):
    k = t.strip().upper().replace(" ", "")
    m = _SIZE_RE.match(k)
    if m:
        return m.group(1), m.group(2), "사각"
    m = _ROUND_RE.match(k)
    if m and ("Ø" in k or "Φ" in k or "φ" in t or k.startswith("D")):
        return m.group(1), "", "원형"
    return None


def parse_cards(items, rowmap, mtype, dims=(), log=print):
    labels = [i for i in items if i.key in rowmap]
    name_labels = [l for l in labels if rowmap[l.key] == "name"]
    if not name_labels:
        return []
    u = _med([l.h for l in labels], 1.0)
    out = []
    for nl in name_labels:
        same_sheet = [l for l in labels if abs(l.x - nl.x) < 8 * u]
        # 이 부호 줄 아래 ~ 다음 부호 줄까지
        nxt = [l.y for l in name_labels if l.y < nl.y - u and abs(l.x - nl.x) < 8 * u]
        ylim = max(nxt) + 0.5 * u if nxt else -1e18
        rlabels = [l for l in same_sheet if ylim < l.y <= nl.y + 0.5 * u and rowmap[l.key] != "name"]
        names = [i for i in items if abs(i.y - nl.y) < 0.9 * u and i.x > nl.x + 2 * u and is_name(i.text)]
        names.sort(key=lambda i: i.x)
        if not names:
            continue
        xs = [n.x for n in names]
        sp = _med([b - a for a, b in zip(xs, xs[1:])], 30 * u)
        for n in names:
            row = M.new_row(mtype)
            row["name"] = n.text.strip()
            if mtype == "beam":
                row["kind"] = "전단면"
                row["slab"] = ""
            for rl in rlabels:
                f = rowmap[rl.key]
                cand = [i for i in items if abs(i.y - rl.y) < 0.9 * max(u, rl.h) and abs(i.x - n.x) < 0.45 * sp
                        and i is not rl]
                if f == "sec":
                    continue
                if not cand:
                    continue
                v = min(cand, key=lambda i: abs(i.x - n.x)).text.strip()
                if f == "size":
                    s = _size(v)
                    if s:
                        row["b"], row["h"] = s[0], s[1]
                        if mtype == "column":
                            row["shape"] = s[2]
                    continue
                if mtype == "beam":
                    key = {"top": "e_top", "bot": "e_bot", "stir": "e_stir"}.get(f)
                    if key:
                        row[key] = (as_stir(v) if f == "stir" else as_rebar(v)) or v
                    continue
                col = M.col_by_key(mtype, f)
                if not col:
                    continue
                if col.kind == "rebar":
                    v = as_rebar(v) or v
                elif col.kind == "stir":
                    v = as_stir(v) or v
                row[f] = v
            if not row.get("b"):                      # 치수 / 숫자 글자
                ds = [d for d in dims if abs(d.x - n.x) < 0.6 * sp and d.y < n.y]
                for d in sorted(ds, key=lambda d: -d.y):
                    if abs(d.angle % 180) < 10 and not row.get("b"):
                        row["b"] = M.norm_num(str(d.value))
                    elif abs(d.angle % 180) >= 10 and not row.get("h"):
                        row["h"] = M.norm_num(str(d.value))
            out.append(row)
    return out


# ═══════════════════════════════════════════════════════════════════
#  표 형식 (머리글 한 줄 + 한 줄에 한 부재) — 벽, 슬래브
# ═══════════════════════════════════════════════════════════════════
def _alias_index(mtype):
    idx = {}
    for c in M.cols(mtype):
        for a in (c.title, c.full_title) + tuple(c.aliases):
            idx.setdefault(re.sub(r"[\s.:·()\[\]_/]", "", a).upper(), c.key)
    return idx


def parse_table(items, mtype, log=print):
    idx = _alias_index(mtype)
    heads = [i for i in items if i.key in idx]
    names_h = [h for h in heads if idx[h.key] == "name"]
    out = []
    for nh in names_h:
        u = nh.h or 1.0
        hrow = [h for h in heads if abs(h.y - nh.y) < 1.2 * u]
        if len(hrow) < 2:
            continue
        hrow.sort(key=lambda h: h.x)
        centers = [(h.x, idx[h.key]) for h in hrow]
        body = [i for i in items if i.y < nh.y - 0.8 * u and i not in heads and i.x > nh.x - 6 * u]
        for line in _rows_of(body, 0.6 * u):
            if nh.y - line[0].y > 80 * u:
                break
            row = M.new_row(mtype)
            filled = 0
            for it in line:
                k = min(centers, key=lambda c: abs(c[0] - it.x))[1]
                col = M.col_by_key(mtype, k)
                v = it.text.strip()
                if col.kind == "spacing":
                    v = as_spacing(v) or v
                elif col.kind == "rebar":
                    v = as_rebar(v) or v
                elif col.kind == "num":
                    v = M.norm_num(v)
                row[k] = v
                filled += 1
            if row.get("name") and is_name(row["name"]) and filled >= 2:
                out.append(row)
            elif out and not row.get("name"):
                break
    return out


# ═══════════════════════════════════════════════════════════════════
#  자동 판별
# ═══════════════════════════════════════════════════════════════════
def parse_any(items, dims=(), want="auto", log=print):
    """→ {mtype: rows}, warnings"""
    res = {}
    warn = []
    if want in ("auto", "beam"):
        rows, info = parse_beams(items, dims, log)
        if rows:
            res["beam"] = rows
            warn += info.get("warn", [])
    if want in ("auto", "column") and not (want == "auto" and res):
        rows = parse_cards(items, COL_ROWS, "column", dims, log)
        rows = [r for r in rows if r.get("main") or r.get("b")]
        if rows:
            res["column"] = rows
    for t in ("wall", "slab"):
        if want in ("auto", t) and not (want == "auto" and res):
            rows = parse_table(items, t, log)
            if rows:
                res[t] = rows
    return res, warn
