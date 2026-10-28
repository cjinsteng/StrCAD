# -*- coding: utf-8 -*-
"""
docx_pages.py — Word 문서의 쪽(A4) 나뉨 위치 추정

Word 처럼 실제로 그리는 엔진은 없으므로, 글꼴 폭(Tk 글꼴 측정)·글자 크기·줄 간격·문단 간격·
들여쓰기·표 행 높이·그림 높이·쪽 나누기를 계산해 각 쪽이 어디서 시작하는지 '예상'한다.
(같은 글꼴이 설치된 PC에서 대개 몇 줄 이내 오차)

결과: Pages.start[id(요소)] = 쪽 번호  (그 문단/표가 새 쪽에서 시작)
      Pages.split[id(문단)] = 쪽 번호  (문단 중간에서 다음 쪽으로 넘어감)
      Pages.rows[id(표)] = {행 번호: 쪽 번호}
      Pages.total = 전체 쪽 수
"""
import re

from docx.oxml.ns import qn

W_P, W_TBL, W_R, W_T = qn("w:p"), qn("w:tbl"), qn("w:r"), qn("w:t")
W_TAB, W_BR, W_CR = qn("w:tab"), qn("w:br"), qn("w:cr")
W_DRAWING = qn("w:drawing")
Q_PPR = qn("w:pPr")
_QN = {}


def QN(t):
    v = _QN.get(t)
    if v is None:
        v = _QN[t] = qn(t)
    return v
HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣一-鿿]")


class Styles:
    """문단/글자 속성: 직접 서식 → 스타일(상속) → 문서 기본값"""

    def __init__(self, docx_document):
        st = docx_document.styles.element
        self.by_id = {s.get(qn("w:styleId")): s for s in st.findall(qn("w:style"))}
        dd = st.find(qn("w:docDefaults"))
        self.def_ppr = dd.find(qn("w:pPrDefault") + "/" + qn("w:pPr")) if dd is not None else None
        self.def_rpr = dd.find(qn("w:rPrDefault") + "/" + qn("w:rPr")) if dd is not None else None
        self._chain_cache = {}
        self._rp_cache = {}
        self._cands = {}
        self.default_para = next((s.get(qn("w:styleId")) for s in st.findall(qn("w:style"))
                                  if s.get(qn("w:type")) == "paragraph" and s.get(qn("w:default")) == "1"), None)

    def chain(self, sid):
        c = self._chain_cache.get(sid)
        if c is not None:
            return c
        out, seen = [], set()
        while sid and sid not in seen and sid in self.by_id:
            seen.add(sid)
            s = self.by_id[sid]
            out.append(s)
            b = s.find(qn("w:basedOn"))
            sid = b.get(qn("w:val")) if b is not None else None
        self._chain_cache[out[0].get(qn("w:styleId")) if out else None] = out
        return out

    def para_style(self, p_el):
        ppr = p_el.find(Q_PPR)
        ps = ppr.find(QN("w:pStyle")) if ppr is not None else None
        return ps.get(QN("w:val")) if ps is not None else self.default_para

    def _ppr_cands(self, p_el):
        key = id(p_el)
        c = self._cands.get(key)
        if c is None or c[0] is not p_el:
            ppr = p_el.find(Q_PPR)
            c = (p_el, [ppr] + [s.find(Q_PPR) for s in self.chain(self.para_style(p_el))] + [self.def_ppr])
            self._cands[key] = c
        return c[1]

    def ppr_attr(self, p_el, tag, attr):
        cands = self._ppr_cands(p_el)
        tag, attr = QN(tag), QN(attr)
        for c in cands:
            if c is None:
                continue
            e = c.find(tag)
            if e is not None:
                v = e.get(attr)
                if v is not None:
                    return v
        return None

    def ppr_flag(self, p_el, tag):
        ppr = p_el.find(qn("w:pPr"))
        cands = [ppr] + [s.find(qn("w:pPr")) for s in self.chain(self.para_style(p_el))]
        for c in cands:
            if c is None:
                continue
            e = c.find(qn(tag))
            if e is not None:
                return e.get(qn("w:val"), "1") not in ("0", "false", "off")
        return False

    def run_props(self, p_el, rpr):
        """(크기 pt, 한글 글꼴, 영문 글꼴, 진하게)"""
        sid = self.para_style(p_el)
        if rpr is not None:
            sz = rpr.find(QN("w:sz"))
            f = rpr.find(QN("w:rFonts"))
            b = rpr.find(QN("w:b"))
            if sz is not None and f is not None and f.get(QN("w:eastAsia")):
                key = (sid, sz.get(QN("w:val")), f.get(QN("w:eastAsia")), f.get(QN("w:ascii")),
                       None if b is None else b.get(QN("w:val"), "1"))
                hit = self._rp_cache.get(key)
                if hit is None:
                    hit = self._run_props(p_el, rpr)
                    self._rp_cache[key] = hit
                return hit
        return self._run_props(p_el, rpr)

    def _run_props(self, p_el, rpr):
        cands = [rpr] + [s.find(qn("w:rPr")) for s in self.chain(self.para_style(p_el))] + [self.def_rpr]
        size = ea = asc = None
        bold = None
        for c in cands:
            if c is None:
                continue
            if size is None and c.find(qn("w:sz")) is not None:
                size = int(c.find(qn("w:sz")).get(qn("w:val"))) / 2.0
            f = c.find(qn("w:rFonts"))
            if f is not None:
                ea = ea or f.get(qn("w:eastAsia"))
                asc = asc or f.get(qn("w:ascii")) or f.get(qn("w:hAnsi"))
            if bold is None and c.find(qn("w:b")) is not None:
                bold = c.find(qn("w:b")).get(qn("w:val"), "1") not in ("0", "false")
        return size or 10.0, ea or asc or "맑은 고딕", asc or ea or "맑은 고딕", bool(bold)


class Measure:
    """Tk 글꼴로 글자 폭 측정 (글자별 캐시)"""

    def __init__(self, root=None):
        import tkinter.font as tkfont
        self.tkfont = tkfont
        self.root = root
        self.fonts = {}
        self.cw = {}
        fams = set(tkfont.families(root))
        self.fallback = next((f for f in ("맑은 고딕", "Malgun Gothic", "Noto Sans CJK KR", "NanumGothic")
                              if f in fams), None)
        self.fams = fams

    def _font(self, fam, bold):
        key = (fam, bold)
        if key not in self.fonts:
            use = fam if fam in self.fams else self.fallback
            self.fonts[key] = self.tkfont.Font(root=self.root, family=use, size=-200,
                                               weight="bold" if bold else "normal")
        return self.fonts[key]

    def width(self, text, fam, size, bold):
        """pt 단위 폭"""
        f = self._font(fam, bold)
        tot = 0.0
        for ch in text:
            k = (fam, bold, ch)
            w = self.cw.get(k)
            if w is None:
                w = f.measure(ch) / 200.0
                self.cw[k] = w
            tot += w
        return tot * size


def _twip(v, default=0):
    try:
        return int(v) / 20.0
    except (TypeError, ValueError):
        return default


class Estimator:
    def __init__(self, docx_document, measure):
        self.dx = docx_document
        self.m = measure
        self.st = Styles(docx_document)
        s = docx_document.sections[0]
        self.body_h = (s.page_height - s.top_margin - s.bottom_margin) / 12700.0
        self.body_w = (s.page_width - s.left_margin - s.right_margin) / 12700.0
        dts = docx_document.settings.element.find(qn("w:defaultTabStop"))
        self.tab = _twip(dts.get(qn("w:val")), 36) if dts is not None else 36.0

    # ------------------------------------------------------------ 문단
    def para_lines(self, p_el, avail):
        """→ (줄 높이 목록 pt, 앞 간격, 뒤 간격, 쪽 나누기 앞?)"""
        st = self.st
        ind_l = _twip(st.ppr_attr(p_el, "w:ind", "w:left") or st.ppr_attr(p_el, "w:ind", "w:start"))
        ind_r = _twip(st.ppr_attr(p_el, "w:ind", "w:right") or st.ppr_attr(p_el, "w:ind", "w:end"))
        first = _twip(st.ppr_attr(p_el, "w:ind", "w:firstLine"))
        hang = _twip(st.ppr_attr(p_el, "w:ind", "w:hanging"))
        before = _twip(st.ppr_attr(p_el, "w:spacing", "w:before"))
        after = _twip(st.ppr_attr(p_el, "w:spacing", "w:after"))
        line = st.ppr_attr(p_el, "w:spacing", "w:line")
        rule = st.ppr_attr(p_el, "w:spacing", "w:lineRule") or "auto"
        width = max(30.0, avail - ind_l - ind_r)
        # 글자 흐름
        lines_w, x, maxsize, pics = [], first - hang, 0.0, []
        cur_line_sizes = []
        ppr = p_el.find(qn("w:pPr"))
        mark = ppr.find(qn("w:rPr")) if ppr is not None else None
        msize = st.run_props(p_el, mark)[0]
        line_sizes = []

        def newline():
            nonlocal x, cur_line_sizes
            line_sizes.append(max(cur_line_sizes) if cur_line_sizes else msize)
            cur_line_sizes = []
            x = 0.0
        for r in p_el.iter(W_R):
            rpr = r.find(qn("w:rPr"))
            size, ea, asc, bold = st.run_props(p_el, rpr)
            for ch in r:
                if ch.tag == W_T and ch.text:
                    for tok in re.findall(r"\S+\s*|\s+", ch.text):
                        fam = ea if HANGUL.search(tok) else asc
                        w = self.m.width(tok, fam, size, bold)
                        wt = self.m.width(tok.rstrip(), fam, size, bold)
                        if x + wt > width and x > 0.01:
                            newline()
                        while wt > width:                       # 한 줄보다 긴 낱말
                            newline()
                            wt -= width
                            w -= width
                        x += w
                        cur_line_sizes.append(size)
                elif ch.tag == W_TAB:
                    x = (int(x / self.tab) + 1) * self.tab
                    if x > width:
                        newline()
                    cur_line_sizes.append(size)
                elif ch.tag in (W_BR, W_CR):
                    if ch.get(qn("w:type")) == "page":
                        continue
                    cur_line_sizes.append(size)
                    newline()
                elif ch.tag == W_DRAWING:
                    ext = ch.find(".//" + qn("wp:extent"))
                    if ext is not None:
                        pics.append(int(ext.get("cy", "0")) / 12700.0)
        newline()
        heights = []
        for i, sz in enumerate(line_sizes):
            nat = sz * 1.3
            if pics and i == len(line_sizes) - 1:
                nat = max(nat, max(pics))
            if line is None:
                h = nat
            elif rule == "exact":
                h = _twip(line)
                if pics:
                    h = max(h, max(pics))
            elif rule == "atLeast":
                h = max(_twip(line), nat)
            else:
                h = nat * int(line) / 240.0 if not pics else nat
            heights.append(h)
        brk = st.ppr_flag(p_el, "w:pageBreakBefore") or any(
            b.get(qn("w:type")) == "page" for b in p_el.iter(W_BR))
        return heights, before, after, brk

    def para_height(self, p_el, avail):
        hs, b, a, _ = self.para_lines(p_el, avail)
        return b + sum(hs) + a

    # ------------------------------------------------------------ 표
    def table_rows(self, tbl_el):
        """각 행 높이 (pt), 머리글 반복 행 수"""
        trs = [tr for tr in tbl_el if tr.tag == qn("w:tr")]
        tblpr = tbl_el.find(qn("w:tblPr"))
        dmar = {"top": 0.0, "bottom": 0.0, "left": 5.4, "right": 5.4}
        cm = tblpr.find(qn("w:tblCellMar")) if tblpr is not None else None
        if cm is not None:
            for side in dmar:
                e = cm.find(qn("w:" + side))
                if e is not None:
                    dmar[side] = _twip(e.get(qn("w:w")))
        hs = []
        header = 0
        pending = {}                                 # 세로 병합 칸의 내용 높이
        for r, tr in enumerate(trs):
            trpr = tr.find(qn("w:trPr"))
            if trpr is not None and trpr.find(qn("w:tblHeader")) is not None and r == header:
                header += 1
            content = 0.0
            col = 0
            for tc in tr.findall(qn("w:tc")):
                pr = tc.find(qn("w:tcPr"))
                w = 0.0
                span = 1
                vm = None
                mar = dict(dmar)
                if pr is not None:
                    we = pr.find(qn("w:tcW"))
                    if we is not None and we.get(qn("w:type"), "dxa") == "dxa":
                        w = _twip(we.get(qn("w:w")))
                    g = pr.find(qn("w:gridSpan"))
                    span = int(g.get(qn("w:val"))) if g is not None else 1
                    v = pr.find(qn("w:vMerge"))
                    vm = (v.get(qn("w:val"), "continue")) if v is not None else None
                    m = pr.find(qn("w:tcMar"))
                    if m is not None:
                        for side in mar:
                            e = m.find(qn("w:" + side))
                            if e is not None:
                                mar[side] = _twip(e.get(qn("w:w")))
                if w <= 0:
                    w = self.body_w / max(1, len(tr.findall(qn("w:tc"))))
                avail = max(20.0, w - mar["left"] - mar["right"])
                h = mar["top"] + mar["bottom"]
                for c in tc:
                    if c.tag == W_P:
                        h += self.para_height(c, avail)
                    elif c.tag == W_TBL:
                        h += sum(self.table_rows(c)[0])
                if vm == "restart":
                    pending[col] = [h, r]
                elif vm == "continue" and col in pending:
                    pass
                else:
                    content = max(content, h)
                col += span
            hgt = content
            if trpr is not None and trpr.find(qn("w:trHeight")) is not None:
                th = trpr.find(qn("w:trHeight"))
                v = _twip(th.get(qn("w:val")))
                hgt = v if th.get(qn("w:hRule")) == "exact" else max(v, content)
            hs.append(hgt)
            # 세로 병합이 끝났으면 모자라는 높이를 마지막 행에 더함
            for c0, (h, r0) in list(pending.items()):
                nxt = trs[r + 1] if r + 1 < len(trs) else None
                cont = False
                if nxt is not None:
                    cc = 0
                    for tc in nxt.findall(qn("w:tc")):
                        pr = tc.find(qn("w:tcPr"))
                        g = pr.find(qn("w:gridSpan")) if pr is not None else None
                        v = pr.find(qn("w:vMerge")) if pr is not None else None
                        if cc == c0:
                            cont = v is not None and v.get(qn("w:val"), "continue") == "continue"
                            break
                        cc += int(g.get(qn("w:val"))) if g is not None else 1
                if not cont:
                    have = sum(hs[r0:r + 1])
                    if h > have:
                        hs[r] += h - have
                    del pending[c0]
        return hs, header


class Pages:
    def __init__(self):
        self.start, self.split, self.rows = {}, {}, {}
        self.total = 1
        self.exact = False


def estimate(doc_model, root=None, measure=None):
    """doc_model: hwp_reader.HwpDoc (fmt == 'docx')"""
    m = measure or Measure(root)
    est = Estimator(doc_model.docx, m)
    H = est.body_h
    pg = Pages()
    page, y = 1, 0.0
    for k, obj in doc_model.blocks:
        el = obj.ref
        if el is None:
            continue
        if k == "p":
            hs, before, after, brk = est.para_lines(el, est.body_w)
            if brk and y > 0:
                page, y = page + 1, 0.0
                pg.start[id(el)] = page
            first = (before if y > 0 else before) + (hs[0] if hs else 0)
            if y > 0 and y + first > H:
                page, y = page + 1, 0.0
                pg.start[id(el)] = page
            y += before
            for i, h in enumerate(hs):
                if y + h > H and y > 0:
                    page, y = page + 1, 0.0
                    if i == 0:
                        pg.start[id(el)] = page
                    else:
                        pg.split.setdefault(id(el), page)
                y += h
            y += after
            if y > H:
                y = H
        else:
            p0 = el.find(".//" + qn("w:p"))           # 표 첫 칸 문단의 '쪽 나누기'
            if p0 is not None and est.st.ppr_flag(p0, "w:pageBreakBefore") and y > 0:
                page, y = page + 1, 0.0
                pg.start[id(el)] = page
            hs, header = est.table_rows(el)
            hdr_h = sum(hs[:header])
            rows = {}
            for r, h in enumerate(hs):
                if y > 0 and y + h > H:
                    page, y = page + 1, 0.0
                    if r == 0:
                        pg.start[id(el)] = page
                    else:
                        rows[r] = page
                        if header and r >= header:
                            y += hdr_h
                # 한 쪽보다 큰 행은 Word 도 쪽을 넘겨 나눔
                while y + h > H and h > 0:
                    h -= (H - y)
                    page, y = page + 1, 0.0
                    rows.setdefault(r + 0.5, page)
                    if header and r >= header:
                        y += hdr_h
                y += h
            if rows:
                pg.rows[id(el)] = rows
    pg.total = page
    return pg


def from_word_markers(doc_model):
    """Word 가 저장할 때 남긴 쪽 위치 표시(lastRenderedPageBreak)로 정확한 쪽 나뉨. 없으면 None"""
    LR = qn("w:lastRenderedPageBreak")
    body = doc_model.docx.element.body
    if body.find(".//" + LR) is None:
        return None
    pg = Pages()
    page = 1
    for k, obj in doc_model.blocks:
        el = obj.ref
        if el is None:
            continue
        if k == "p":
            first = True
            for r in el.iter(W_R):
                has_text_before = False
                for ch in r:
                    if ch.tag == LR:
                        page += 1
                        if first and not has_text_before:
                            pg.start[id(el)] = page
                        else:
                            pg.split.setdefault(id(el), page)
                    elif ch.tag == W_T and ch.text:
                        has_text_before = True
                        first = False
            if any(b.get(qn("w:type")) == "page" for b in el.iter(W_BR)) and id(el) not in pg.start:
                pass
            ppr = el.find(Q_PPR)
            if ppr is not None and ppr.find(QN("w:pageBreakBefore")) is not None and id(el) not in pg.start:
                page += 1
                pg.start[id(el)] = page
        else:
            rows = {}
            for r, tr in enumerate(t for t in el if t.tag == qn("w:tr")):
                p0 = tr.find(".//" + qn("w:p"))
                if p0 is not None and p0.find(".//" + LR) is not None:
                    page += 1
                    if r == 0:
                        pg.start[id(el)] = page
                    else:
                        rows[r] = page
            if rows:
                pg.rows[id(el)] = rows
    pg.total = page
    pg.exact = True
    return pg


def word_repaginate(path):
    """Word(설치된 PC)로 파일을 열어 쪽을 다시 계산하고 저장 → 정확한 쪽 위치가 파일에 기록됨"""
    import win32com.client as win32
    app = win32.DispatchEx("Word.Application")
    app.Visible = False
    app.DisplayAlerts = 0
    try:
        d = app.Documents.Open(path, False, False, False)
        d.Repaginate()
        n = d.ComputeStatistics(2)              # wdStatisticPages
        d.Save()
        d.Close(False)
        return n
    finally:
        app.Quit()
