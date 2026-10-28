# -*- coding: utf-8 -*-
"""
hwp_reader.py — 한글(.hwp / .hwpx) 문서를 읽어 문단·표·제목 구조로 변환

 - .hwp  : HWP 5.0 바이너리(OLE) — olefile 필요 (pip install olefile)
 - .hwpx : XML(zip) — 표준 라이브러리만 사용

읽기 전용입니다. 문서 수정은 report_core.HwpApplier(한글 자동화)가 담당합니다.
"""
import re
import struct
import zlib
import zipfile
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------- 데이터 모델

class Para:
    """문단 하나. text 는 한글 '찾기'에 쓰일 수 있는 순수 텍스트.
    breaks: 표/그림/필드/탭/묶음빈칸 등 '찾아 바꾸기'가 넘어갈 수 없는 위치(오프셋)"""
    __slots__ = ("uid", "doc", "seq", "text", "orig", "breaks", "kind",
                 "table", "row", "col", "section")

    def __init__(self, doc, seq, text, breaks, kind="body", table=None, row=-1, col=-1):
        self.doc = doc
        self.seq = seq                # 문서 내 순번 (안정적인 식별자)
        self.uid = f"{doc.key}#{seq}"
        self.text = text              # 현재(편집 반영 전) 텍스트 = 파일 내용
        self.orig = text
        self.breaks = set(breaks)
        self.kind = kind              # body | cell | box
        self.table = table
        self.row, self.col = row, col
        self.section = None

    def __repr__(self):
        return f"<Para {self.uid} {self.kind} {self.text[:30]!r}>"


class Table:
    def __init__(self, tid, rows, cols):
        self.tid = tid
        self.rows, self.cols = rows, cols
        self.cells = {}               # (r, c) -> dict(paras=[...], rs, cs)

    def add_cell(self, r, c, rs, cs):
        cell = {"paras": [], "rs": rs, "cs": cs}
        self.cells[(r, c)] = cell
        return cell


class HwpDoc:
    """한 파일. blocks: [('p', Para) | ('t', Table)] — 본문 순서"""
    def __init__(self, path, key):
        self.path = path
        self.key = key
        self.blocks = []
        self.paras = []               # 모든 문단 (본문+셀+글상자)
        self.tables = []
        self.hidden = []              # 머리말/꼬리말/각주 등 (찾아 바꾸기 고유성 검사용)

    def new_para(self, text, breaks, **kw):
        p = Para(self, len(self.paras), text, breaks, **kw)
        self.paras.append(p)
        return p

    def full_text(self):
        return "\n".join([p.orig for p in self.paras] + self.hidden)


# ---------------------------------------------------------------- HWP 5.0

TAG_PARA_HEADER = 66
TAG_PARA_TEXT = 67
TAG_CTRL_HEADER = 71
TAG_LIST_HEADER = 72
TAG_TABLE = 77

SKIP_CTRLS = {"head", "foot", "fn  ", "en  ", "pghd", "secd", "cold", "nwno", "atno", "pgct", "pgnp"}
# 위 컨트롤 안의 문단(머리말/꼬리말/각주 등)은 본문에서 제외


def _records(data):
    i, n = 0, len(data)
    out = []
    while i + 4 <= n:
        h = struct.unpack_from("<I", data, i)[0]
        i += 4
        tag, lvl, size = h & 0x3FF, (h >> 10) & 0x3FF, (h >> 20) & 0xFFF
        if size == 0xFFF:
            size = struct.unpack_from("<I", data, i)[0]
            i += 4
        out.append((tag, lvl, data[i:i + size]))
        i += size
    return out


_CHAR_CTRL = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


def _decode_para_text(b):
    """PARA_TEXT → (text, breaks)"""
    out = []
    breaks = []
    i, n = 0, len(b)
    while i + 1 < n:
        c = b[i] | (b[i + 1] << 8)
        if c >= 32:
            out.append(chr(c))
            i += 2
            continue
        if c in _CHAR_CTRL:
            if c == 10:                       # 강제 줄바꿈
                breaks.append(len(out))
                out.append("\n")
            elif c in (30, 31):               # 묶음 빈칸 / 고정폭 빈칸
                breaks.append(len(out))
                out.append(" ")
            elif c == 24:                     # 하이픈
                out.append("-")
            i += 2
        else:                                 # 인라인/확장 컨트롤 (16바이트)
            if c == 9:
                breaks.append(len(out))
                out.append("\t")
            else:
                breaks.append(len(out))      # 표/그림/필드 위치
            i += 16
    return "".join(out), breaks


def read_hwp(path, key=None):
    import olefile
    doc = HwpDoc(path, key or path)
    ole = olefile.OleFileIO(path)
    try:
        hdr = ole.openstream("FileHeader").read()
        props = struct.unpack_from("<I", hdr, 36)[0]
        if props & 0x2:
            raise ValueError("암호가 걸린 문서는 읽을 수 없습니다.")
        if props & 0x4:
            raise ValueError("배포용 문서는 읽을 수 없습니다.")
        compressed = bool(props & 0x1)
        secs = sorted((e for e in ole.listdir() if e[0] == "BodyText"),
                      key=lambda e: int(re.sub(r"\D", "", e[1]) or 0))
        for s in secs:
            data = ole.openstream("/".join(s)).read()
            if compressed:
                data = zlib.decompress(data, -15)
            _parse_section(doc, _records(data))
    finally:
        ole.close()
    return doc


def _parse_section(doc, recs):
    n = len(recs)

    def parse_para(i, sink, kind, table=None, row=-1, col=-1, skip=False):
        """recs[i] 는 PARA_HEADER. 문단과 그 하위 레코드를 소비하고 다음 인덱스 반환"""
        lvl = recs[i][1]
        i += 1
        text, breaks = "", []
        ctrls = []
        while i < n and recs[i][1] > lvl:
            tag, l, b = recs[i]
            if tag == TAG_PARA_TEXT and l == lvl + 1:
                text, breaks = _decode_para_text(b)
                i += 1
            elif tag == TAG_CTRL_HEADER and l == lvl + 1:
                i = parse_ctrl(i, ctrls, skip)
            else:
                i += 1
        if skip:
            if text.strip():
                doc.hidden.append(text)
        else:
            p = doc.new_para(text.rstrip("\r"), breaks, kind=kind, table=table, row=row, col=col)
            if sink is not None:
                sink.append(("p", p))
            for c in ctrls:
                if sink is not None and c is not None:
                    sink.append(c)
        return i

    def parse_ctrl(i, ctrls, skip):
        tag, lvl, b = recs[i]
        cid = b[:4][::-1].decode("latin-1", "replace") if len(b) >= 4 else ""
        i += 1
        skip = skip or cid in SKIP_CTRLS
        table = None
        cell_sink = None
        box_sink = []
        if cid == "tbl " and not skip:
            table = Table(len(doc.tables), 0, 0)
            doc.tables.append(table)
        while i < n and recs[i][1] > lvl:
            t, l, bb = recs[i]
            if t == TAG_TABLE and table is not None:
                if len(bb) >= 8:
                    table.rows, table.cols = struct.unpack_from("<HH", bb, 4)
                i += 1
            elif t == TAG_LIST_HEADER:
                if table is not None and len(bb) >= 16:
                    c, r, cs, rs = struct.unpack_from("<HHHH", bb, 8)
                    cell = table.add_cell(r, c, rs, cs)
                    cell_sink = (cell, r, c)
                else:
                    cell_sink = None
                i += 1
            elif t == TAG_PARA_HEADER:
                if table is not None and cell_sink is not None:
                    cell, r, c = cell_sink
                    tmp = []
                    i = parse_para(i, tmp, "cell", table=table, row=r, col=c, skip=skip)
                    for kind, obj in tmp:
                        if kind == "p":
                            cell["paras"].append(obj)
                        else:  # 셀 안의 중첩 표 → 셀 문단으로 평탄화
                            for pp in _table_paras(obj):
                                cell["paras"].append(pp)
                else:
                    i = parse_para(i, box_sink, "box", skip=skip)
            else:
                i += 1
        if skip:
            ctrls.append(None)
        elif table is not None:
            ctrls.append(("t", table))
        else:
            for blk in box_sink:
                ctrls.append(blk)
        return i

    i = 0
    while i < n:
        if recs[i][0] == TAG_PARA_HEADER and recs[i][1] == 0:
            i = parse_para(i, doc.blocks, "body")
        else:
            i += 1


def _table_paras(t):
    out = []
    for key in sorted(t.cells):
        for p in t.cells[key]["paras"]:
            out.append(p)
    return out


# ---------------------------------------------------------------- HWPX

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def read_hwpx(path, key=None):
    doc = HwpDoc(path, key or path)
    with zipfile.ZipFile(path) as z:
        names = sorted((nm for nm in z.namelist() if re.match(r"Contents/section\d+\.xml$", nm)),
                       key=lambda s: int(re.sub(r"\D", "", s)))
        for nm in names:
            root = ET.fromstring(z.read(nm))
            for p in root.findall(HP + "p"):
                _hx_para(doc, p, doc.blocks, "body")
    return doc


def _hx_para(doc, pel, sink, kind, table=None, row=-1, col=-1):
    out, breaks, ctrls = [], [], []
    for run in pel.findall(HP + "run"):
        for ch in run:
            tg = ch.tag
            if tg == HP + "t":
                if ch.text:
                    out.append(ch.text)
                for sub in ch:
                    if sub.tag == HP + "tab":
                        breaks.append(sum(map(len, out)))
                        out.append("\t")
                    elif sub.tag in (HP + "lineBreak",):
                        breaks.append(sum(map(len, out)))
                        out.append("\n")
                    elif sub.tag in (HP + "nbSpace", HP + "fwSpace"):
                        breaks.append(sum(map(len, out)))
                        out.append(" ")
                    if sub.tail:
                        out.append(sub.tail)
            elif tg == HP + "tbl":
                breaks.append(sum(map(len, out)))
                ctrls.append(_hx_table(doc, ch))
            elif tg in (HP + "ctrl",):
                breaks.append(sum(map(len, out)))
        # 그림/글상자 내부 문단은 다음 루프에서 별도로 처리하지 않음 (단순화)
    p = doc.new_para("".join(out), breaks, kind=kind, table=table, row=row, col=col)
    sink.append(("p", p))
    sink.extend(ctrls)


def _hx_table(doc, tel):
    rows = int(tel.get("rowCnt", 0) or 0)
    cols = int(tel.get("colCnt", 0) or 0)
    t = Table(len(doc.tables), rows, cols)
    doc.tables.append(t)
    for tr in tel.findall(HP + "tr"):
        for tc in tr.findall(HP + "tc"):
            addr = tc.find(HP + "cellAddr")
            span = tc.find(HP + "cellSpan")
            c = int(addr.get("colAddr", 0)) if addr is not None else 0
            r = int(addr.get("rowAddr", 0)) if addr is not None else 0
            cs = int(span.get("colSpan", 1)) if span is not None else 1
            rs = int(span.get("rowSpan", 1)) if span is not None else 1
            cell = t.add_cell(r, c, rs, cs)
            sub = tc.find(HP + "subList")
            if sub is None:
                continue
            for p in sub.findall(HP + "p"):
                tmp = []
                _hx_para(doc, p, tmp, "cell", table=t, row=r, col=c)
                for k, obj in tmp:
                    if k == "p":
                        cell["paras"].append(obj)
                    else:
                        cell["paras"].extend(_table_paras(obj))
    return ("t", t)


def read_document(path, key=None):
    low = path.lower()
    if low.endswith(".hwpx"):
        return read_hwpx(path, key)
    if low.endswith(".hwp"):
        return read_hwp(path, key)
    raise ValueError("지원하지 않는 형식입니다 (.hwp / .hwpx 만 가능)")


# ---------------------------------------------------------------- 제목(장/절) 인식

RE_PART = re.compile(r"^\s*제\s*([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]+|\d+)\s*편\s*(.*?)\s*$")
RE_CHAPTER = re.compile(r"^\s*제\s*(\d+)\s*장\s*(.*?)\s*$")
RE_NUMHEAD = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){1,3})\.?\s+([^\d\s].{0,60}?)\s*$")
RE_TOC_TAIL = re.compile(r"[\t·….\s]*\d*\s*$")


class Section:
    def __init__(self, doc, number, title, level, block_idx, para):
        self.doc = doc
        self.number = number          # '5', '5.4', '5.4.1'
        self.title = title
        self.level = level            # 0=장, 1=절, 2=항, 3=목
        self.block_idx = block_idx    # doc.blocks 에서 제목 문단 위치
        self.end_idx = None           # (하위 포함) 끝 위치(제외)
        self.own_end = None           # 하위 절 시작 전까지
        self.para = para
        self.children = []
        self.parent = None
        self.sid = f"{doc.key}@{block_idx}"

    @property
    def label(self):
        if not self.number:
            return self.title
        if self.level == -1:
            return f"제{self.number}편 {self.title}".strip()
        if self.level == 0:
            return f"제{self.number}장 {self.title}".strip()
        return f"{self.number} {self.title}".strip()

    def iter(self):
        yield self
        for c in self.children:
            yield from c.iter()


def heading_of(p):
    """본문 문단이 제목이면 (number, title, level) 반환"""
    if p.kind != "body":
        return None
    t = p.text.strip()
    if not t or len(t) > 70 or "\n" in t:
        return None
    m = RE_PART.match(t)
    if m:
        return m.group(1), RE_TOC_TAIL.sub("", m.group(2).split("\t")[0]).strip(), -1
    m = RE_CHAPTER.match(t)
    if m:
        return m.group(1), RE_TOC_TAIL.sub("", m.group(2).split("\t")[0]).strip(), 0
    m = RE_NUMHEAD.match(t)
    if m:
        num = m.group(1)
        title = m.group(2).split("\t")[0].strip()
        if not title or title[0] in "+-*/=×xX(":
            return None
        return num, title, num.count(".")
    return None


def build_sections(doc):
    """doc.blocks → 장/절 트리. 반환: 최상위 Section 리스트"""
    heads = []
    for bi, (k, obj) in enumerate(doc.blocks):
        if k == "p":
            h = heading_of(obj)
            if h:
                heads.append((bi, h))

    # 목차(TOC) 제거: 같은 편·장 안의 같은 제목이 뒤에 다시 나오고, 다음 제목까지 내용이 없으면 목차로 본다
    # (편이 여러 개면 'Ⅰ편 4.1 개 요' 와 'Ⅱ편 4.1 개 요' 는 서로 다른 제목)
    ctx_keys = []
    part = chap = ""
    for bi, h in heads:
        if h[2] == -1:
            part, chap = h[0], ""
        elif h[2] == 0:
            chap = h[0]
        ctx_keys.append((part, chap if h[2] > 0 else "", h[0], re.sub(r"\s+", "", h[1])))

    def has_content(b0, b1):
        for k, obj in doc.blocks[b0 + 1:b1]:
            if k == "t":
                return True
            if obj.text.strip():
                return True
        return False

    keep = []
    for idx, (bi, h) in enumerate(heads):
        nxt = heads[idx + 1][0] if idx + 1 < len(heads) else len(doc.blocks)
        later = ctx_keys[idx] in ctx_keys[idx + 1:]
        if later and not has_content(bi, nxt):
            continue
        keep.append((bi, h))

    roots, stack = [], []
    chapter_num = None
    for bi, (num, title, level) in keep:
        p = doc.blocks[bi][1]
        if level == 0:
            chapter_num = num
        s = Section(doc, num, title, level, bi, p)
        while stack and stack[-1].level >= level:
            stack.pop()
        if stack:
            s.parent = stack[-1]
            stack[-1].children.append(s)
        else:
            roots.append(s)
        stack.append(s)
    if not roots:
        s = Section(doc, "", "(제목 없음)", 0, 0, None)
        roots.append(s)

    # 첫 장 제목 이전 내용(표지 등)도 볼 수 있도록 '머리' 노드
    first = roots[0].block_idx
    if first > 0 and has_content(-1, first):
        front = Section(doc, "", "(표지·목차)", 0, 0, None)
        front.sid = f"{doc.key}@front"
        roots.insert(0, front)

    flat = [s for r in roots for s in r.iter()]
    starts = [s.block_idx for s in flat]
    for i, s in enumerate(flat):
        s.own_end = starts[i + 1] if i + 1 < len(flat) else len(doc.blocks)
    for s in flat:
        last = list(s.iter())[-1]
        s.end_idx = last.own_end
    if roots and roots[0].title == "(표지·목차)":
        roots[0].own_end = roots[0].end_idx = first

    # 문단 → 소속 절
    for s in flat:
        rng = range(s.block_idx, s.own_end) if s.title != "(표지·목차)" else range(0, first)
        for bi in rng:
            k, obj = doc.blocks[bi]
            if k == "p":
                obj.section = s
            else:
                for cell in obj.cells.values():
                    for p in cell["paras"]:
                        p.section = s
    return roots
