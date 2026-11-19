"""
model.py — 부재 일람표 데이터 모델
  · 부재 종류별 열 정의 (보 / 기둥 / 벽 / 슬래브)
  · 철근 표기 정리 ("3-22" → "3-D22", "10@200" → "D10@200")
  · 프로젝트 저장/열기 (.atbl = JSON)
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field

PREFIXES = ["D", "HD", "SHD", "UHD", "SD"]
KNOWN_PFX = set(PREFIXES) | {"H", "SHD", "UHD", "HR"}
BAR_DIAS = {6, 8, 10, 13, 16, 19, 22, 25, 29, 32, 35, 38, 41, 51}
BAR_AREA = {6: 31.67, 8: 49.51, 10: 71.33, 13: 126.7, 16: 198.6, 19: 286.5, 22: 387.1,
            25: 506.7, 29: 642.4, 32: 794.2, 35: 956.6, 38: 1140.0, 41: 1340.0, 51: 2027.0}

EMPTY_MARKS = ("-", "—", "–", "－")


@dataclass
class Col:
    key: str
    title: str
    group: str = ""
    width: int = 78
    kind: str = "text"          # text | num | rebar | stir | spacing | choice
    choices: tuple = ()
    default: str = ""
    aliases: tuple = ()          # 가져오기 자동 매핑용 머리글 이름

    @property
    def full_title(self):
        return f"{self.group} {self.title}".strip() if self.group else self.title


NAME_AL = ("부호", "부재", "부재명", "부재부호", "MEMB", "MEMBER", "NAME", "MARK", "SECT", "SECTION", "SECTIONNAME", "이름")
FLOOR_AL = ("층", "FLOOR", "STORY", "STOREY", "구간", "LEVEL", "적용층")
NOTE_AL = ("비고", "NOTE", "REMARK", "REMARKS", "메모")

BEAM_KINDS = ("양단/중앙", "전단면", "외단/중앙/내단")

# ── 부재 종류별 열 ─────────────────────────────────────────────────
TYPES = {
    "beam": {
        "title": "보", "en": "Beam", "icon": "▭",
        "cols": [
            Col("name", "부호", width=92, aliases=NAME_AL),
            Col("b", "B", width=56, kind="num", default="400", aliases=("B", "BC", "BW", "폭", "WIDTH", "B(MM)")),
            Col("h", "H", width=56, kind="num", default="600", aliases=("H", "HC", "D", "깊이", "춤", "높이", "DEPTH", "H(MM)")),
            Col("slab", "슬래브", width=56, kind="num", default="150", aliases=("슬래브", "SLAB", "TS", "슬래브두께")),
            Col("kind", "구분", width=96, kind="choice", choices=BEAM_KINDS, default="양단/중앙",
                aliases=("구분", "배근구분", "TYPE", "형식")),
            Col("e_top", "상부근", "단부 (전단면)", kind="rebar", aliases=("단부상부근", "단부상부", "ENDTOP", "END-ITOP", "ITOP", "외단부상부근", "양단부상부근", "전단면상부근")),
            Col("e_bot", "하부근", "단부 (전단면)", kind="rebar", aliases=("단부하부근", "단부하부", "ENDBOT", "END-IBOT", "IBOT", "외단부하부근", "양단부하부근", "전단면하부근")),
            Col("e_stir", "늑근", "단부 (전단면)", kind="stir", aliases=("단부늑근", "단부스터럽", "ENDSTIRRUP", "END-ISTIRRUP", "ISTIRRUP", "외단부늑근", "양단부늑근", "전단면늑근")),
            Col("m_top", "상부근", "중앙부", kind="rebar", aliases=("중앙부상부근", "중앙상부", "MIDTOP", "MTOP")),
            Col("m_bot", "하부근", "중앙부", kind="rebar", aliases=("중앙부하부근", "중앙하부", "MIDBOT", "MBOT")),
            Col("m_stir", "늑근", "중앙부", kind="stir", aliases=("중앙부늑근", "중앙스터럽", "MIDSTIRRUP", "MSTIRRUP")),
            Col("j_top", "상부근", "내단부", kind="rebar", aliases=("내단부상부근", "END-JTOP", "JTOP")),
            Col("j_bot", "하부근", "내단부", kind="rebar", aliases=("내단부하부근", "END-JBOT", "JBOT")),
            Col("j_stir", "늑근", "내단부", kind="stir", aliases=("내단부늑근", "END-JSTIRRUP", "JSTIRRUP")),
            Col("note", "비고", width=130, aliases=NOTE_AL),
        ],
    },
    "column": {
        "title": "기둥", "en": "Column", "icon": "▣",
        "cols": [
            Col("name", "부호", width=92, aliases=NAME_AL),
            Col("floor", "층", width=86, aliases=FLOOR_AL),
            Col("b", "B (Cx)", width=60, kind="num", default="600", aliases=("B", "CX", "BC", "폭", "가로")),
            Col("h", "D (Cy)", width=60, kind="num", default="600", aliases=("D", "CY", "HC", "H", "세로", "깊이")),
            Col("shape", "형태", width=58, kind="choice", choices=("사각", "원형"), default="사각", aliases=("형태", "SHAPE")),
            Col("main", "주근", width=92, kind="rebar", aliases=("주근", "주철근", "MAIN", "MAINBAR", "VERTICAL", "REBAR")),
            Col("arr", "배치(X×Y)", width=72, aliases=("배치", "ARRANGE", "NXNY")),
            Col("hoop_e", "단부", "대근", kind="stir", aliases=("대근단부", "단부대근", "HOOPEND", "TIEEND", "띠철근단부")),
            Col("hoop_m", "중앙", "대근", kind="stir", aliases=("대근중앙", "중앙대근", "대근", "HOOP", "HOOPMID", "TIE", "띠철근")),
            Col("tie_x", "X방향", "보조대근", width=72, kind="rebar", aliases=("보조대근X", "X보조대근", "TIEX", "CROSSTIEX")),
            Col("tie_y", "Y방향", "보조대근", width=72, kind="rebar", aliases=("보조대근Y", "Y보조대근", "TIEY", "CROSSTIEY")),
            Col("note", "비고", width=120, aliases=NOTE_AL),
        ],
    },
    "wall": {
        "title": "벽", "en": "Wall", "icon": "▯",
        "cols": [
            Col("name", "부호", width=92, aliases=NAME_AL),
            Col("floor", "층", width=86, aliases=FLOOR_AL),
            Col("t", "두께", width=60, kind="num", default="200", aliases=("두께", "THK", "T", "TW", "THICKNESS")),
            Col("layer", "배근", width=70, kind="choice", choices=("복배근", "단배근"), default="복배근", aliases=("배근", "배근형식", "LAYER")),
            Col("vert", "수직근", width=96, kind="spacing", aliases=("수직근", "수직철근", "VERT", "VERTICAL", "V-BAR")),
            Col("horz", "수평근", width=96, kind="spacing", aliases=("수평근", "수평철근", "HORZ", "HORIZONTAL", "H-BAR")),
            Col("end", "단부보강근", width=92, kind="rebar", aliases=("단부보강근", "단부근", "END", "BOUNDARY")),
            Col("note", "비고", width=130, aliases=NOTE_AL),
        ],
    },
    "slab": {
        "title": "슬래브", "en": "Slab", "icon": "▱",
        "cols": [
            Col("name", "부호", width=92, aliases=NAME_AL),
            Col("t", "두께", width=58, kind="num", default="150", aliases=("두께", "THK", "T", "TS", "THICKNESS")),
            Col("kind", "형식", width=72, kind="choice", choices=("2방향", "1방향", "캔틸레버"), default="2방향", aliases=("형식", "TYPE", "구분")),
            Col("x_te", "상부 단부", "단변방향", kind="spacing", aliases=("단변상부단부", "단변단부상부", "XTOPEND", "SXTE")),
            Col("x_tm", "상부 중앙", "단변방향", kind="spacing", aliases=("단변상부중앙", "단변중앙상부", "XTOPMID")),
            Col("x_be", "하부 단부", "단변방향", kind="spacing", aliases=("단변하부단부", "단변단부하부", "XBOTEND")),
            Col("x_bm", "하부 중앙", "단변방향", kind="spacing", aliases=("단변하부중앙", "단변중앙하부", "XBOTMID")),
            Col("y_te", "상부 단부", "장변방향", kind="spacing", aliases=("장변상부단부", "장변단부상부", "YTOPEND")),
            Col("y_tm", "상부 중앙", "장변방향", kind="spacing", aliases=("장변상부중앙", "장변중앙상부", "YTOPMID")),
            Col("y_be", "하부 단부", "장변방향", kind="spacing", aliases=("장변하부단부", "장변단부하부", "YBOTEND")),
            Col("y_bm", "하부 중앙", "장변방향", kind="spacing", aliases=("장변하부중앙", "장변중앙하부", "YBOTMID")),
            Col("note", "비고", width=120, aliases=NOTE_AL),
        ],
    },
}
TYPE_KEYS = list(TYPES)


def cols(mtype):
    return TYPES[mtype]["cols"]


def col_keys(mtype):
    return [c.key for c in TYPES[mtype]["cols"]]


def col_by_key(mtype, key):
    for c in TYPES[mtype]["cols"]:
        if c.key == key:
            return c
    return None


def disabled(mtype, row, key):
    """해당 칸이 지금 쓰이지 않는 칸인지 (회색 표시, 출력 안 함)."""
    if mtype == "beam":
        k = row.get("kind") or BEAM_KINDS[0]
        if key.startswith("m_"):
            return k == "전단면"
        if key.startswith("j_"):
            return k != "외단/중앙/내단"
    if mtype == "column" and key == "h":
        return row.get("shape") == "원형"
    if mtype == "wall" and key == "end":
        return False
    return False


def beam_zones(row):
    """보 한 행 → 출력할 구역 목록 [(라벨, 열위치 0~2, prefix)]  (prefix: e_ / m_ / j_)"""
    k = row.get("kind") or BEAM_KINDS[0]
    if k == "전단면":
        return [("전단면", 1, "e_")]
    if k == "외단/중앙/내단":
        return [("외단부", 0, "e_"), ("중앙부", 1, "m_"), ("내단부", 2, "j_")]
    return [("양단부", 0, "e_"), ("중앙부", 1, "m_")]


def new_row(mtype, prev=None):
    """새 행. prev 가 있으면 단면·배근을 이어받고 부호 번호만 +1."""
    if prev:
        r = {k: prev.get(k, "") for k in col_keys(mtype)}
        r["name"] = next_name(prev.get("name", ""))
        return r
    return {c.key: c.default for c in cols(mtype)}


def next_name(name):
    m = re.match(r"^(.*?)(\d+)([A-Za-z]?)$", name or "")
    if not m:
        return name
    head, num, tail = m.groups()
    return f"{head}{int(num) + 1:0{len(num)}d}{tail}"


def natural_key(s):
    return [int(t) if t.isdigit() else t.upper() for t in re.split(r"(\d+)", s or "")]


# ═══════════════════════════════════════════════════════════════════
#  철근 표기 정리 / 해석
# ═══════════════════════════════════════════════════════════════════
def _clean(s):
    t = (s or "").strip().upper()
    for a, b in (("Φ", "D"), ("Ø", "D"), ("φ".upper(), "D"), ("ø".upper(), "D"), ("Ｄ", "D"), ("＠", "@"),
                 ("®", "@"), ("–", "-"), ("—", "-"), ("－", "-"), ("×", "X"), ("，", ","), (" ", "")):
        t = t.replace(a, b)
    return t


_REBAR_RE = re.compile(r"(\d+)(?:/(\d+))?(?:[-X*]([A-Z]{0,3})|([A-Z]{1,3}))(\d{1,2})")
_REBAR_REV = re.compile(r"([A-Z]{1,3})(\d{1,2})[-X*](\d+)")
_STIR_RE = re.compile(r"(?:(\d+)-)?([A-Z]{0,3})(\d{1,2})[@\-/](\d{2,4})")
_SPC_RE = re.compile(r"([A-Z]{0,3})(\d{1,2})(?:[,+/&]([A-Z]{0,3})(\d{1,2}))?[@\-](\d{2,4})")


def is_empty_mark(s):
    return (s or "").strip() in EMPTY_MARKS


def norm_rebar(s, pfx="D"):
    """'3-22'→'3-D22', '4d19'→'4-D19', '5/2-22'→'5/2-D22', 'D22-4'→'4-D22'. 못 알아보면 그대로."""
    raw = (s or "").strip()
    if not raw or is_empty_mark(raw):
        return "-" if raw else ""
    t = _clean(raw)
    out = []
    for p in t.split("+"):
        m = _REBAR_RE.fullmatch(p)
        if m:
            n, n2, pf1, pf2, d = m.groups()
            pf = pf1 or pf2 or pfx
        else:
            m2 = _REBAR_REV.fullmatch(p)
            if not m2:
                return raw
            pf, d, n = m2.groups()
            n2 = None
        if pf not in KNOWN_PFX:
            return raw
        out.append(f"{n}/{n2}-{pf}{d}" if n2 else f"{n}-{pf}{d}")
    return "+".join(out)


def norm_stir(s, pfx="D"):
    """'10@200'→'D10@200', 'HD10-150'→'HD10@150', '2-10@150'→'2-D10@150'."""
    raw = (s or "").strip()
    if not raw or is_empty_mark(raw):
        return "-" if raw else ""
    t = _clean(raw)
    m = _STIR_RE.fullmatch(t)
    if not m:
        return raw
    legs, pf, d, sp = m.groups()
    pf = pf or pfx
    if pf not in KNOWN_PFX:
        return raw
    return f"{legs + '-' if legs else ''}{pf}{d}@{sp}"


def norm_spacing(s, pfx="D"):
    """'13@200'→'D13@200', '10,13@300'→'D10,D13@300' (교대배근)."""
    raw = (s or "").strip()
    if not raw or is_empty_mark(raw):
        return "-" if raw else ""
    t = _clean(raw)
    m = _SPC_RE.fullmatch(t)
    if not m:
        return raw
    pf, d, pf2, d2, sp = m.groups()
    pf = pf or pfx
    if pf not in KNOWN_PFX:
        return raw
    if d2:
        pf2 = pf2 or pf
        return f"{pf}{d},{pf2}{d2}@{sp}"
    return f"{pf}{d}@{sp}"


def norm_num(s):
    raw = (s or "").strip()
    t = raw.replace(",", "").replace("mm", "").replace("MM", "").strip()
    try:
        v = float(t)
    except ValueError:
        return raw
    return str(int(round(v))) if abs(v - round(v)) < 1e-6 else f"{v:g}"


def normalize(kind, s, pfx="D", choices=()):
    if kind == "rebar":
        return norm_rebar(s, pfx)
    if kind == "stir":
        return norm_stir(s, pfx)
    if kind == "spacing":
        return norm_spacing(s, pfx)
    if kind == "num":
        return norm_num(s)
    if kind == "choice":
        v = (s or "").strip()
        for c in choices:
            if v == c or v.replace(" ", "") == c.replace(" ", ""):
                return c
        for c in choices:                         # "2" → 두 번째 항목, 첫 글자 일치
            if v and (v == c[:len(v)]):
                return c
        if v.isdigit() and 1 <= int(v) <= len(choices):
            return choices[int(v) - 1]
        return v
    return (s or "").strip()


def is_valid(kind, s, choices=()):
    """표기가 맞는지 (빈칸·'-' 은 OK)."""
    v = (s or "").strip()
    if not v or is_empty_mark(v):
        return True
    if kind == "rebar":
        return parse_rebar(v) is not None
    if kind == "stir":
        return parse_stir(v) is not None
    if kind == "spacing":
        return parse_spacing(v) is not None
    if kind == "num":
        try:
            float(v)
            return True
        except ValueError:
            return False
    if kind == "choice":
        return v in choices
    return True


def parse_rebar(s):
    """'5/2-D22' → dict(n1=5, n2=2, pfx='D', dia=22, total=7, area=...). '4-D22+2-D19' 도 됨."""
    t = _clean(s)
    if not t or is_empty_mark(t):
        return None
    n1 = n2 = 0
    dia = 0
    pfx = ""
    area = 0.0
    for p in t.split("+"):
        m = _REBAR_RE.fullmatch(p)
        if m:
            n, nn, pf1, pf2, d = m.groups()
            pf = pf1 or pf2 or ""
        else:
            m2 = _REBAR_REV.fullmatch(p)
            if not m2:
                return None
            pf, d, n = m2.groups()
            nn = None
        d = int(d)
        if d not in BAR_DIAS:
            return None
        a, b = int(n), int(nn or 0)
        n1 += a
        n2 += b
        dia = max(dia, d)
        pfx = pfx or pf
        area += (a + b) * BAR_AREA.get(d, 0.0)
    return {"n1": n1, "n2": n2, "pfx": pfx, "dia": dia, "total": n1 + n2, "area": area}


def parse_stir(s):
    t = _clean(s)
    m = _STIR_RE.fullmatch(t)
    if not m:
        return None
    legs, pf, d, sp = m.groups()
    if int(d) not in BAR_DIAS:
        return None
    return {"legs": int(legs) if legs else 2, "pfx": pf, "dia": int(d), "s": int(sp)}


def parse_spacing(s):
    t = _clean(s)
    m = _SPC_RE.fullmatch(t)
    if not m:
        return None
    pf, d, pf2, d2, sp = m.groups()
    if int(d) not in BAR_DIAS or (d2 and int(d2) not in BAR_DIAS):
        return None
    return {"pfx": pf, "dia": int(d), "dia2": int(d2) if d2 else 0, "s": int(sp)}


def swap_prefix(s, kind, new_pfx):
    """철근 칸의 강종 기호만 바꿈 (F4)."""
    v = (s or "").strip()
    if not v or is_empty_mark(v):
        return v
    t = _clean(v)
    if kind == "rebar":
        return "+".join(re.sub(r"^(\d+(?:/\d+)?)-[A-Z]{0,3}(\d+)$", lambda m: f"{m.group(1)}-{new_pfx}{m.group(2)}",
                               norm_rebar(p, new_pfx)) for p in t.split("+"))
    if kind == "stir":
        n = norm_stir(t, new_pfx)
        return re.sub(r"^((?:\d+-)?)[A-Z]{0,3}(\d+@)", lambda m: f"{m.group(1)}{new_pfx}{m.group(2)}", n)
    if kind == "spacing":
        n = norm_spacing(t, new_pfx)
        return re.sub(r"[A-Z]{1,3}(?=\d)", new_pfx, n)
    return v


def guess_prefix(rows_by_type):
    """가져온 자료에서 가장 많이 쓰인 강종 기호."""
    from collections import Counter
    c = Counter()
    for mtype, rows in rows_by_type.items():
        for r in rows:
            for col in cols(mtype):
                if col.kind in ("rebar", "stir", "spacing"):
                    m = re.search(r"(?:^|[-,\d])([A-Z]{1,3})\d", _clean(r.get(col.key, "")))
                    if m and m.group(1) in KNOWN_PFX:
                        c[m.group(1)] += 1
    return c.most_common(1)[0][0] if c else None


# ═══════════════════════════════════════════════════════════════════
#  프로젝트
# ═══════════════════════════════════════════════════════════════════
@dataclass
class Project:
    rows: dict = field(default_factory=lambda: {t: [] for t in TYPES})
    settings: dict = field(default_factory=lambda: {"prefix": "D"})
    meta: dict = field(default_factory=lambda: {
        "source": "",            # 가져온 원본 파일 (DXF 등)
        "template": "",          # DXF 출력 양식(시트 틀) 파일
        "notes": [],             # 도면 NOTE 문구
        "drawing_no": "",        # 시작 도면번호 (예: S-105)
        "project": ["", ""],     # 프로젝트명 2줄 (비우면 양식 그대로)
    })
    path: str = ""

    def to_dict(self):
        return {"app": "StrCAD Auto Table", "version": 2, "settings": self.settings,
                "meta": self.meta, "rows": self.rows}

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        self.path = path

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        p = cls()
        p.settings.update(d.get("settings") or {})
        p.meta.update(d.get("meta") or {})
        for t in TYPES:
            keys = col_keys(t)
            p.rows[t] = [{k: str(r.get(k, "")) for k in keys} for r in (d.get("rows") or {}).get(t, [])]
        p.path = path
        return p

    def snapshot(self):
        return copy.deepcopy(self.rows)

    def count(self, mtype):
        return sum(1 for r in self.rows[mtype] if any((r.get(k) or "").strip() for k in col_keys(mtype)))


def clean_rows(mtype, rows):
    """완전히 빈 행 제거."""
    keys = col_keys(mtype)
    return [r for r in rows if (r.get("name") or "").strip() or any(
        (r.get(k) or "").strip() and (r.get(k) or "").strip() != c.default
        for k, c in zip(keys, cols(mtype)))]
