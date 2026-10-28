# -*- coding: utf-8 -*-
"""
hwp_to_word.py — 한글(.hwp) 원본을 읽어 '깔끔한' Word(.docx)를 새로 만든다 (한글 프로그램 불필요)

한글의 'Word로 저장'은 글상자·줄 간격·표 위치가 흐트러지기 쉬워서,
원본의 구조(문단·표·그림)와 모양 정보를 직접 읽어 Word 서식으로 다시 쓴다.

 - 쪽: 용지 크기, 여백, 머리말/꼬리말 거리, 쪽 나누기 → 한 쪽에 들어가는 내용이 한글과 비슷하게
 - 글자: 글꼴(한글/영문), 크기, 진하게/기울임/밑줄, 색, 장평, 자간
 - 문단: 정렬, 왼쪽/오른쪽 여백, 첫 줄 들여쓰기, 문단 위/아래 간격, 줄 간격(%·고정값)
 - 표: 칸 너비, 셀 합치기, 테두리(종류·굵기), 배경색, 셀 안 여백, 세로 정렬
 - 그림: 원본 크기 그대로, 묶음(그림+글상자)은 그림 + 그림 안 글자를 작은 주석으로
 - 머리말/꼬리말: 내용 그대로, 쪽 번호 자리에 쪽 번호 필드

사용:  build_docx("원본.hwp", "결과.docx")   필요: olefile, python-docx, pillow
"""
import io
import os
import re
import struct
import zlib

import olefile
from docx import Document
from docx.enum.section import WD_SECTION  # noqa: F401
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu

from hwp_reader import _records

TAG_PARA_HEADER, TAG_PARA_TEXT, TAG_PARA_CHAR_SHAPE = 66, 67, 68
TAG_CTRL_HEADER, TAG_LIST_HEADER, TAG_PAGE_DEF, TAG_TABLE = 71, 72, 73, 77
TAG_SHAPE_PICTURE = 85

HU_PER_INCH = 7200
TWIP = lambda hu: int(round(hu / 5))                 # 1 twip = 1/1440 in
EMU = lambda hu: int(round(hu * 127))                 # 1 EMU = 1/914400 in

BORDER_TYPES = {1: "single", 2: "dashed", 3: "dotted", 4: "dotDash", 5: "dotDotDash", 6: "dashed",
                7: "dotted", 8: "double", 9: "thinThickSmallGap", 10: "thickThinSmallGap",
                11: "thinThickThinSmallGap", 12: "wave", 13: "doubleWave", 14: "threeDEmboss",
                15: "threeDEngrave", 16: "single"}
BORDER_MM = [0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
ALIGN = {0: "both", 1: "left", 2: "right", 3: "center", 4: "distribute", 5: "both"}


# ====================================================================== 원본 읽기 (모양 정보 포함)

class DocInfo:
    def __init__(self, data):
        recs = _records(data)
        self.faces, self.char, self.para, self.bfill, self.bins = [], [], [], [], {}
        idmap = None
        for t, l, b in recs:
            if t == 17:
                idmap = struct.unpack_from("<%di" % (len(b) // 4), b)
            elif t == 19:
                n = struct.unpack_from("<H", b, 1)[0]
                self.faces.append(b[3:3 + 2 * n].decode("utf-16le", "replace"))
            elif t == 21:
                self.char.append(self._char(b))
            elif t == 25:
                self.para.append(self._para(b))
            elif t == 20:
                self.bfill.append(self._bfill(b))
            elif t == 18:
                props = struct.unpack_from("<H", b, 0)[0]
                if props & 0xF in (1, 2) and len(b) >= 6:
                    bid, n = struct.unpack_from("<HH", b, 2)
                    ext = b[6:6 + 2 * n].decode("utf-16le", "replace")
                    self.bins[bid] = ext
        n = list(idmap[1:8]) if idmap else [len(self.faces)] + [0] * 6
        self.face_lang = []
        k = 0
        for cnt in n:                                   # 언어별 글꼴 목록 (한글, 영문, 한자, …)
            self.face_lang.append(self.faces[k:k + cnt])
            k += cnt

    @staticmethod
    def _char(b):
        fid = struct.unpack_from("<7H", b, 0)
        ratio = struct.unpack_from("<7B", b, 14)
        spc = struct.unpack_from("<7b", b, 21)
        rel = struct.unpack_from("<7B", b, 28)
        size, props = struct.unpack_from("<iI", b, 42)
        color = struct.unpack_from("<I", b, 52)[0] if len(b) >= 56 else 0
        return {"fid": fid, "ratio": ratio, "spc": spc, "rel": rel, "size": size,
                "italic": bool(props & 1), "bold": bool(props & 2),
                "underline": (props >> 2) & 3, "strike": bool((props >> 18) & 7),
                "sup": bool(props & (1 << 15)), "sub": bool(props & (1 << 16)), "color": color}

    @staticmethod
    def _para(b):
        p1, lm, rm, ind, pre, nxt, ls_old = struct.unpack_from("<Iiiiiii", b, 0)
        ls_type, ls = p1 & 3, ls_old
        if len(b) >= 54:
            p3, ls_new = struct.unpack_from("<II", b, 46)
            ls_type, ls = p3 & 0x1F, ls_new
        return {"align": (p1 >> 2) & 7, "lm": lm, "rm": rm, "ind": ind, "pre": pre, "next": nxt,
                "ls_type": ls_type, "ls": ls}

    @staticmethod
    def _bfill(b):
        borders = []
        for i in range(4):                              # 왼, 오른, 위, 아래
            ty, w = b[2 + 6 * i], b[3 + 6 * i]
            col = struct.unpack_from("<I", b, 4 + 6 * i)[0]
            borders.append((ty, w, col))
        bg = None
        if len(b) >= 40:
            ft = struct.unpack_from("<I", b, 32)[0]
            if ft & 1:
                c = struct.unpack_from("<I", b, 36)[0]
                if c != 0xFFFFFFFF and c != 0x00FFFFFF:
                    bg = c
        return {"borders": borders, "bg": bg}

    def face(self, cs, lang=0):
        lst = self.face_lang[lang] if lang < len(self.face_lang) else []
        i = cs["fid"][lang]
        return lst[i] if i < len(lst) else (self.face_lang[0][0] if self.face_lang and self.face_lang[0] else None)


class RPara:
    def __init__(self, shape, brk):
        self.shape, self.brk = shape, brk
        self.chars = []          # [(글자, 글자모양 id)] ; '\t', '\n' 포함, '\x12' = 쪽 번호 자리
        self.pitch = None        # 한글이 실제로 쓴 줄 간격 (HWPUNIT, LINE_SEG: 줄 높이 + 줄 간격)
        self.items = []          # 문단 뒤에 놓일 표/그림/글상자


class RTable:
    def __init__(self):
        self.rows = self.cols = 0
        self.cells = []          # dict(r,c,rs,cs,w,h,bf,mar,valign,blocks)
        self.width = 0
        self.inline = True


class RPic:
    def __init__(self, bin_id, w, h, notes=None):
        self.bin_id, self.w, self.h, self.notes = bin_id, w, h, notes or []


class HwpSource:
    def __init__(self, path):
        self.path = path
        self.ole = olefile.OleFileIO(path)
        hdr = self.ole.openstream("FileHeader").read()
        props = struct.unpack_from("<I", hdr, 36)[0]
        if props & 0x6:
            raise ValueError("암호/배포용 문서는 변환할 수 없습니다.")
        self.compressed = bool(props & 1)
        self.info = DocInfo(self._stream("DocInfo"))
        self.blocks = []                       # [('p', RPara) | ('t', RTable) | ('g', RPic)]
        self.header, self.footer = [], []
        self.page = None
        secs = sorted((e for e in self.ole.listdir() if e[0] == "BodyText"),
                      key=lambda e: int(re.sub(r"\D", "", e[1]) or 0))
        for s in secs:
            self.recs = _records(self._stream("/".join(s)))
            self._parse_list(0, len(self.recs), 0, self.blocks)

    def _stream(self, name):
        d = self.ole.openstream(name).read()
        return zlib.decompress(d, -15) if self.compressed else d

    def bin_bytes(self, bid):
        ext = self.info.bins.get(bid, "")
        cands = [f"BinData/BIN{bid:04X}.{ext}"] if ext else []
        cands += [e for e in ("/".join(x) for x in self.ole.listdir()) if e.upper().startswith(f"BINDATA/BIN{bid:04X}")]
        for name in cands:
            if self.ole.exists(name):
                raw = self.ole.openstream(name).read()
                try:
                    return zlib.decompress(raw, -15), ext
                except zlib.error:
                    return raw, ext
        return None, ext

    # ------------------------------------------------------------ 레코드 해석
    def _parse_list(self, i, end, lvl, sink):
        """i..end 에서 lvl 단계 문단들을 sink 블록으로"""
        while i < end:
            t, l, b = self.recs[i]
            if t == TAG_PARA_HEADER and l == lvl:
                i = self._parse_para(i, sink)
            else:
                i += 1
        return i

    def _subtree_end(self, i):
        lvl = self.recs[i][1]
        j = i + 1
        while j < len(self.recs) and self.recs[j][1] > lvl:
            j += 1
        return j

    def _parse_para(self, i, sink):
        t, lvl, b = self.recs[i]
        shape = struct.unpack_from("<H", b, 8)[0] if len(b) >= 10 else 0
        brk = b[11] if len(b) >= 12 else 0
        p = RPara(shape, brk)
        end = self._subtree_end(i)
        raw = None
        cshapes = [(0, 0)]
        ctrls = []
        j = i + 1
        while j < end:
            tt, l, bb = self.recs[j]
            if l == lvl + 1 and tt == TAG_PARA_TEXT:
                raw = bb
            elif l == lvl + 1 and tt == 69 and len(bb) >= 36:          # PARA_LINE_SEG
                segs = [struct.unpack_from("<IiiiiiiiI", bb, k) for k in range(0, len(bb) - 35, 36)]
                pitches = [s_[2] + s_[5] for s_ in segs if s_[2] > 0]
                if pitches:
                    p.pitch = max(set(pitches), key=pitches.count)
            elif l == lvl + 1 and tt == TAG_PARA_CHAR_SHAPE:
                cshapes = [struct.unpack_from("<II", bb, k) for k in range(0, len(bb) - 7, 8)]
            elif l == lvl + 1 and tt == TAG_CTRL_HEADER:
                ctrls.append(j)
            j += 1
        if raw:
            p.chars = self._decode(raw, cshapes)
        sink.append(("p", p))
        for c in ctrls:
            self._parse_ctrl(c, p, sink)
        return end

    @staticmethod
    def _decode(b, cshapes):
        out = []
        k, n = 0, len(b)
        ci = 0

        def cs_at(pos):
            nonlocal ci
            while ci + 1 < len(cshapes) and cshapes[ci + 1][0] <= pos:
                ci += 1
            return cshapes[ci][1]
        while k + 1 < n:
            c = b[k] | (b[k + 1] << 8)
            pos = k // 2
            if c >= 32:
                out.append((chr(c), cs_at(pos)))
                k += 2
            elif c in (0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31):
                if c == 10:
                    out.append(("\n", cs_at(pos)))
                elif c in (30, 31):
                    out.append((" ", cs_at(pos)))
                elif c == 24:
                    out.append(("-", cs_at(pos)))
                k += 2
            else:
                if c == 9:
                    out.append(("\t", cs_at(pos)))
                elif c == 18:                         # 자동 번호(쪽 번호) 자리
                    out.append(("\x12", cs_at(pos)))
                k += 16
        return out

    def _parse_ctrl(self, i, para, sink):
        t, lvl, b = self.recs[i]
        cid = b[:4][::-1].decode("latin-1", "replace")
        end = self._subtree_end(i)
        if cid == "tbl ":
            sink.append(("t", self._parse_table(i, end, b)))
        elif cid == "gso ":
            for blk in self._parse_gso(i, end, b):
                sink.append(blk)
        elif cid == "secd":
            for j in range(i + 1, end):
                if self.recs[j][0] == TAG_PAGE_DEF and self.page is None:
                    self.page = struct.unpack_from("<9I", self.recs[j][2], 0)
        elif cid in ("head", "foot"):
            target = self.header if cid == "head" else self.footer
            if not target:
                for j in range(i + 1, end):
                    if self.recs[j][0] == TAG_LIST_HEADER:
                        self._parse_list(j + 1, end, self.recs[j][1], target)
                        break

    def _parse_table(self, i, end, ctrl_b):
        tb = RTable()
        if len(ctrl_b) >= 24:
            props = struct.unpack_from("<I", ctrl_b, 4)[0]
            tb.inline = bool(props & 1)
            tb.width = struct.unpack_from("<I", ctrl_b, 16)[0]
        cell = None
        lvl = self.recs[i][1]
        j = i + 1
        while j < end:
            tt, l, bb = self.recs[j]
            if tt == TAG_TABLE and l == lvl + 1:
                tb.rows, tb.cols = struct.unpack_from("<HH", bb, 4)
                j += 1
            elif tt == TAG_LIST_HEADER and l == lvl + 1 and len(bb) >= 34:
                props = struct.unpack_from("<I", bb, 2)[0]
                c, r, cs, rs, w, h = struct.unpack_from("<HHHHII", bb, 8)
                mar = struct.unpack_from("<4H", bb, 24)
                bf = struct.unpack_from("<H", bb, 32)[0]
                cell = {"r": r, "c": c, "rs": max(rs, 1), "cs": max(cs, 1), "w": w, "h": h,
                        "mar": mar, "bf": bf, "valign": (props >> 21) & 3, "blocks": []}
                tb.cells.append(cell)
                j += 1
            elif tt == TAG_PARA_HEADER and cell is not None and l == lvl + 1:
                j = self._parse_para(j, cell["blocks"])
            else:
                j += 1
        return tb

    def _parse_gso(self, i, end, ctrl_b):
        w, h = struct.unpack_from("<II", ctrl_b, 16) if len(ctrl_b) >= 24 else (0, 0)
        pics, texts = [], []
        j = i + 1
        while j < end:
            tt, l, bb = self.recs[j]
            if tt == TAG_SHAPE_PICTURE and len(bb) >= 73:
                pics.append(struct.unpack_from("<H", bb, 71)[0])
                j += 1
            elif tt == TAG_PARA_HEADER:
                tmp = []
                j = self._parse_para(j, tmp)
                for k, obj in tmp:
                    if k == "p":
                        s = "".join(ch for ch, _ in obj.chars).strip()
                        if s:
                            texts.append((s, obj))
            else:
                j += 1
        if pics:
            return [("g", RPic(pics[0], w, h, [s for s, _ in texts]))]
        return [("p", obj) for s, obj in texts]          # 글상자 → 보통 문단


# ====================================================================== Word 만들기

def _el(tag, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k), str(v))
    return e


def _sub(parent, tag, **attrs):
    e = _el(tag, **attrs)
    parent.append(e)
    return e


def _rgb(colorref):
    r, g, b = colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF
    return f"{r:02X}{g:02X}{b:02X}"


class Builder:
    def __init__(self, src):
        self.src = src
        self.info = src.info
        self.doc = Document()
        body = self.doc.element.body
        for c in list(body):
            if c.tag != qn("w:sectPr"):
                body.remove(c)
        self.pic_count = 0
        self.pitch_scale = 1.0          # 쪽을 꽉 채우는 표는 줄 간격을 살짝 줄여 다음 쪽으로 넘치지 않게

    # ------------------------------------------------------------ 글자/문단
    def _rpr(self, csid, parent, scale=1.0):
        cs = self.info.char[csid] if csid < len(self.info.char) else self.info.char[0]
        rpr = _sub(parent, "w:rPr")
        ko = self.info.face(cs, 0)
        en = self.info.face(cs, 1) or ko
        if ko or en:
            _sub(rpr, "w:rFonts", **{"w:ascii": en or ko, "w:hAnsi": en or ko, "w:eastAsia": ko or en,
                                     "w:cs": en or ko})
        if cs["bold"]:
            _sub(rpr, "w:b")
            _sub(rpr, "w:bCs")
        if cs["italic"]:
            _sub(rpr, "w:i")
        if cs["strike"]:
            _sub(rpr, "w:strike")
        if cs["color"] & 0xFFFFFF:
            _sub(rpr, "w:color", **{"w:val": _rgb(cs["color"])})
        size = cs["size"] * (cs["rel"][0] or 100) / 100.0 / 100.0 * scale  # pt
        spc = cs["spc"][0]
        if spc:
            _sub(rpr, "w:spacing", **{"w:val": int(round(size * spc / 100.0 * 20))})
        if cs["ratio"][0] and cs["ratio"][0] != 100:
            _sub(rpr, "w:w", **{"w:val": max(1, min(600, cs["ratio"][0]))})
        _sub(rpr, "w:sz", **{"w:val": int(round(size * 2))})
        _sub(rpr, "w:szCs", **{"w:val": int(round(size * 2))})
        if cs["underline"]:
            _sub(rpr, "w:u", **{"w:val": "single"})
        if cs["sup"]:
            _sub(rpr, "w:vertAlign", **{"w:val": "superscript"})
        elif cs["sub"]:
            _sub(rpr, "w:vertAlign", **{"w:val": "subscript"})
        return rpr

    def _size(self, csid):
        cs = self.info.char[csid] if csid < len(self.info.char) else self.info.char[0]
        return cs["size"] * (cs["rel"][0] or 100) / 10000.0

    def make_p(self, rp, part=None, has_pic=False, first_csid=None):
        p = _el("w:p")
        ps = self.info.para[rp.shape] if rp.shape < len(self.info.para) else self.info.para[0]
        ppr = _sub(p, "w:pPr")
        if rp.brk & 0x04:
            _sub(ppr, "w:pageBreakBefore")
        _sub(ppr, "w:widowControl", **{"w:val": "0"})
        # 줄 간격
        sizes = [self._size(c) for _, c in rp.chars] or [self._size(first_csid if first_csid is not None else 0)]
        mx = max(sizes) if sizes else 10
        # 한글은 쪽 맨 위에서 '문단 위 간격'을 띄우지 않으므로 쪽 나누기 문단은 0
        sp = {"w:before": 0 if (rp.brk & 0x04) else TWIP(ps["pre"] / 2), "w:after": TWIP(ps["next"] / 2)}
        if not has_pic:
            if ps["ls_type"] == 0:                      # 글자에 따라 (%)
                # 줄 간격은 한글과 똑같이 (쪽 구성 유지). 100% 미만은 Word 에서 글자가 겹치므로 글자만 줄인다
                if rp.pitch:                             # 한글이 실제 배치한 줄 간격 그대로
                    sp["w:line"] = max(40, int(round(rp.pitch / 5 * self.pitch_scale)))
                else:
                    sp["w:line"] = int(round(mx * ps["ls"] / 100.0 * 20))
                sp["w:lineRule"] = "exact"
            elif ps["ls_type"] == 1:                    # 고정 값
                sp["w:line"] = TWIP(ps["ls"] / 2)
                sp["w:lineRule"] = "exact"
            else:                                       # 여백만 / 최소
                sp["w:line"] = int(round(mx * 20 + TWIP(ps["ls"] / 2)))
                sp["w:lineRule"] = "atLeast"
        _sub(ppr, "w:spacing", **sp)
        ind = {}
        if ps["lm"]:
            ind["w:left"] = TWIP(ps["lm"] / 2)
        if ps["rm"]:
            ind["w:right"] = TWIP(ps["rm"] / 2)
        if ps["ind"] > 0:
            ind["w:firstLine"] = TWIP(ps["ind"] / 2)
        elif ps["ind"] < 0:
            ind["w:hanging"] = TWIP(-ps["ind"] / 2)
            ind["w:left"] = TWIP(ps["lm"] / 2 - ps["ind"] / 2)
        if ind:
            _sub(ppr, "w:ind", **ind)
        _sub(ppr, "w:autoSpaceDE", **{"w:val": "0"})
        _sub(ppr, "w:autoSpaceDN", **{"w:val": "0"})
        _sub(ppr, "w:jc", **{"w:val": ALIGN.get(ps["align"], "both")})
        # 문단 기호 글자 모양 (빈 문단 높이)
        scale = 1.0
        if not has_pic and ps["ls_type"] == 0 and 0 < ps["ls"] < 100:
            scale = max(0.5, ps["ls"] / 90.0)
        csid0 = rp.chars[0][1] if rp.chars else (first_csid or 0)
        self._rpr(csid0, ppr, scale)
        # run 들
        run_cs, buf = None, []

        def flush():
            if not buf:
                return
            r = _sub(p, "w:r")
            self._rpr(run_cs, r, scale)
            txt = ""
            for ch in buf:
                if ch in "\t\n\x12":
                    if txt:
                        t = _sub(r, "w:t")
                        t.text = txt
                        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                        txt = ""
                    if ch == "\t":
                        _sub(r, "w:tab")
                    elif ch == "\n":
                        _sub(r, "w:br")
                    else:                                  # 쪽 번호
                        _sub(r, "w:fldChar", **{"w:fldCharType": "begin"})
                        it = _sub(r, "w:instrText")
                        it.text = " PAGE "
                        it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                        _sub(r, "w:fldChar", **{"w:fldCharType": "separate"})
                        t = _sub(r, "w:t")
                        t.text = "1"
                        _sub(r, "w:fldChar", **{"w:fldCharType": "end"})
                else:
                    txt += ch
            if txt:
                t = _sub(r, "w:t")
                t.text = txt
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            buf.clear()
        for ch, cs in rp.chars:
            if cs != run_cs:
                flush()
                run_cs = cs
            buf.append(ch)
        flush()
        return p

    # ------------------------------------------------------------ 그림
    def pic_run(self, pic, part):
        data, ext = self.src.bin_bytes(pic.bin_id)
        if not data:
            return None
        stream = io.BytesIO(data)
        if ext.lower() in ("bmp", "dib", "wmf", "emf", "tif", "tiff", "gif", "pcx") or not ext:
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(data))
                if im.mode not in ("RGB", "RGBA", "L"):
                    im = im.convert("RGB")
                out = io.BytesIO()
                im.save(out, "PNG")
                out.seek(0)
                stream = out
            except Exception:
                stream = io.BytesIO(data)
        w = EMU(pic.w) if pic.w else None
        h = EMU(pic.h) if pic.h else None
        try:
            inline = part.new_pic_inline(stream, w, h)
        except Exception:
            return None
        self.pic_count += 1
        r = _el("w:r")
        d = _sub(r, "w:drawing")
        d.append(inline)
        return r

    def pic_para(self, pic, part, align="center", shape=None):
        rp = RPara(shape if shape is not None else 0, 0)
        p = self.make_p(rp, part, has_pic=True)
        if align:
            jc = p.find(qn("w:pPr")).find(qn("w:jc"))
            jc.set(qn("w:val"), align)
        r = self.pic_run(pic, part)
        if r is not None:
            p.append(r)
        return p

    def note_para(self, texts):
        p = _el("w:p")
        ppr = _sub(p, "w:pPr")
        _sub(ppr, "w:jc", **{"w:val": "center"})
        r = _sub(p, "w:r")
        rpr = _sub(r, "w:rPr")
        _sub(rpr, "w:color", **{"w:val": "666666"})
        _sub(rpr, "w:sz", **{"w:val": "16"})
        t = _sub(r, "w:t")
        t.text = "(그림 안 글자: " + " · ".join(texts) + ")"
        return p

    # ------------------------------------------------------------ 표
    def _col_widths(self, tb):
        n = max(tb.cols, max((c["c"] + c["cs"] for c in tb.cells), default=0))
        widths = [None] * n
        votes = [{} for _ in range(n)]
        for c in tb.cells:
            if c["cs"] == 1 and c["c"] < n:
                votes[c["c"]][c["w"]] = votes[c["c"]].get(c["w"], 0) + 1
        for k in range(n):
            if votes[k]:
                widths[k] = max(votes[k].items(), key=lambda x: x[1])[0]
        for _ in range(3):
            for c in tb.cells:
                rng = range(c["c"], min(n, c["c"] + c["cs"]))
                unknown = [k for k in rng if widths[k] is None]
                if unknown:
                    known = sum(widths[k] for k in rng if widths[k] is not None)
                    each = max(300, (c["w"] - known) // len(unknown))
                    for k in unknown:
                        widths[k] = each
        return [w or 2000 for w in widths]

    def _borders(self, tcpr, bf_id):
        if not bf_id or bf_id > len(self.info.bfill):
            return
        bf = self.info.bfill[bf_id - 1]
        tb = _sub(tcpr, "w:tcBorders")
        for name, (ty, wi, col) in zip(("left", "right", "top", "bottom"), bf["borders"]):
            if ty == 0:
                _sub(tb, f"w:{name}", **{"w:val": "nil"})
            else:
                mm = BORDER_MM[wi] if wi < len(BORDER_MM) else 0.12
                sz = max(2, min(96, int(round(mm / 25.4 * 72 * 8))))
                _sub(tb, f"w:{name}", **{"w:val": BORDER_TYPES.get(ty, "single"), "w:sz": sz,
                                         "w:space": 0, "w:color": _rgb(col) if col & 0xFFFFFF else "000000"})
        if bf["bg"] is not None:
            _sub(tcpr, "w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": _rgb(bf["bg"])})

    def make_tbl(self, tb, part, align="center"):
        old_scale = self.pitch_scale
        if self.src.page:
            body_h = self.src.page[1] - sum(self.src.page[4:8])
            total = 0
            for r in range(max(tb.rows, 1)):
                total += max([c["h"] for c in tb.cells if c["r"] == r and c["rs"] == 1] or [0])
            if total > body_h * 0.95:
                self.pitch_scale = old_scale * max(0.85, body_h * 0.95 / total)
        try:
            return self._make_tbl(tb, part, align)
        finally:
            self.pitch_scale = old_scale

    def _make_tbl(self, tb, part, align="center"):
        widths = self._col_widths(tb)
        n = len(widths)
        tbl = _el("w:tbl")
        pr = _sub(tbl, "w:tblPr")
        _sub(pr, "w:tblW", **{"w:w": sum(TWIP(w) for w in widths), "w:type": "dxa"})
        _sub(pr, "w:jc", **{"w:val": align})
        _sub(pr, "w:tblLayout", **{"w:type": "fixed"})
        mar = _sub(pr, "w:tblCellMar")
        for side in ("left", "right"):
            _sub(mar, f"w:{side}", **{"w:w": 0, "w:type": "dxa"})
        _sub(pr, "w:tblLook", **{"w:val": "0000", "w:firstRow": 0, "w:lastRow": 0, "w:firstColumn": 0,
                                  "w:lastColumn": 0, "w:noHBand": 1, "w:noVBand": 1})
        grid = _sub(tbl, "w:tblGrid")
        for w in widths:
            _sub(grid, "w:gridCol", **{"w:w": TWIP(w)})
        start = {(c["r"], c["c"]): c for c in tb.cells}
        cover = {}
        for c in tb.cells:
            for dr in range(1, c["rs"]):
                cover[(c["r"] + dr, c["c"])] = c
        nrows = max(tb.rows, max((c["r"] + c["rs"] for c in tb.cells), default=0))
        for r in range(nrows):
            tr = _sub(tbl, "w:tr")
            trpr = _sub(tr, "w:trPr")
            hs = [c["h"] for c in tb.cells if c["r"] == r and c["rs"] == 1]
            if hs:
                _sub(trpr, "w:trHeight", **{"w:val": TWIP(min(hs)), "w:hRule": "atLeast"})
            # 쪽 높이에 가까운 행은 나뉘어도 되게 (안 그러면 다음 쪽으로 밀려 빈 쪽이 생김)
            body_h = (self.src.page[1] - sum(self.src.page[4:8])) if self.src.page else 60000
            row_h = max([c["h"] for c in tb.cells if c["r"] == r] or [0])
            if row_h < body_h * 0.6:
                _sub(trpr, "w:cantSplit")
            col = 0
            while col < n:
                c = start.get((r, col))
                vm = None
                if c is None and (r, col) in cover:
                    c, vm = cover[(r, col)], "continue"
                elif c is not None and c["rs"] > 1:
                    vm = "restart"
                tc = _sub(tr, "w:tc")
                tcpr = _sub(tc, "w:tcPr")
                span = c["cs"] if c else 1
                w = sum(widths[col:col + span])
                _sub(tcpr, "w:tcW", **{"w:w": TWIP(w), "w:type": "dxa"})
                if span > 1:
                    _sub(tcpr, "w:gridSpan", **{"w:val": span})
                if vm:
                    _sub(tcpr, "w:vMerge", **({"w:val": "restart"} if vm == "restart" else {}))
                if c:
                    self._borders(tcpr, c["bf"])
                    m = _sub(tcpr, "w:tcMar")
                    for side, v in zip(("left", "right", "top", "bottom"), c["mar"]):
                        _sub(m, f"w:{side}", **{"w:w": TWIP(v), "w:type": "dxa"})
                    _sub(tcpr, "w:vAlign", **{"w:val": {0: "top", 1: "center", 2: "bottom"}.get(c["valign"], "center")})
                if c and vm != "continue":
                    for e in self.make_blocks(c["blocks"], part, in_cell=True):
                        tc.append(e)
                if not [e for e in tc if e.tag == qn("w:p")] or tc[-1].tag != qn("w:p"):
                    tc.append(_el("w:p"))
                col += span
        return tbl

    # ------------------------------------------------------------ 블록 묶음
    def make_blocks(self, blocks, part, in_cell=False):
        out = []
        last_align = "center"
        carry_break = False                       # 빈 앵커 문단의 '쪽 나누기'를 다음 표/그림에 옮김

        def page_break_on(el):
            p = el if el.tag == qn("w:p") else el.find(".//" + qn("w:p"))
            if p is None:
                return
            ppr = p.find(qn("w:pPr"))
            if ppr is None:
                ppr = _el("w:pPr")
                p.insert(0, ppr)
            if ppr.find(qn("w:pageBreakBefore")) is None:
                ppr.insert(0, _el("w:pageBreakBefore"))
            sp = ppr.find(qn("w:spacing"))
            if sp is not None:
                sp.set(qn("w:before"), "0")
        for idx, (k, obj) in enumerate(blocks):
            if k == "p":
                has_text = any(ch.strip() for ch, _ in obj.chars)
                nxt = [b for b in blocks[idx + 1:idx + 2]]
                ps = self.info.para[obj.shape] if obj.shape < len(self.info.para) else self.info.para[0]
                last_align = ALIGN.get(ps["align"], "both")
                # 표/그림만 담은 빈 문단(앵커)은 건너뛴다 — 표/그림이 그 자리를 차지.
                # 쪽 나누기가 있던 앵커면 표/그림의 첫 문단에 쪽 나누기를 옮겨 빈 쪽이 생기지 않게 한다
                if not has_text and nxt and nxt[0][0] in ("t", "g"):
                    carry_break = carry_break or bool(obj.brk & 0x04)
                    continue
                # 쪽 나누기만 하는 빈 문단 → 다음 글 문단으로 쪽 나누기를 옮기고 지움 (새 쪽 맨 위 빈 줄 방지)
                # 다음 문단도 쪽 나누기면(일부러 비운 쪽) 그대로 둔다
                if (not has_text and (obj.brk & 0x04) and nxt and nxt[0][0] == "p"
                        and not (nxt[0][1].brk & 0x04) and not in_cell):
                    carry_break = True
                    continue
                out.append(self.make_p(obj, part))
                if carry_break:
                    page_break_on(out[-1])
                    carry_break = False
            elif k == "t":
                align = last_align if last_align in ("left", "center", "right") else "center"
                if (out and out[-1].tag == qn("w:tbl")) or carry_break:
                    # 표 두 개가 붙으면 Word 가 합쳐 버리므로 1pt 짜리 빈 문단을 사이에 둔다.
                    # 쪽 나누기도 표 안이 아니라 이 문단에 둔다 (표 안 쪽 나누기는 프로그램마다 다르게 처리)
                    gap = _el("w:p")
                    gppr = _sub(gap, "w:pPr")
                    _sub(gppr, "w:spacing", **{"w:before": 0, "w:after": 0, "w:line": 20, "w:lineRule": "exact"})
                    grpr = _sub(gppr, "w:rPr")
                    _sub(grpr, "w:sz", **{"w:val": 2})
                    out.append(gap)
                    if carry_break:
                        page_break_on(gap)
                        carry_break = False
                out.append(self.make_tbl(obj, part, align))
                if carry_break:
                    page_break_on(out[-1])
                    carry_break = False
            elif k == "g":
                out.append(self.pic_para(obj, part, "center" if last_align == "both" else last_align))
                if carry_break:
                    page_break_on(out[-1])
                    carry_break = False
                if obj.notes:
                    out.append(self.note_para(obj.notes))
        return out

    # ------------------------------------------------------------ 문서
    def build(self, out_path):
        sec = self.doc.sections[0]
        if self.src.page:
            w, h, l, r, t, b, hd, ft, gut = self.src.page
            sec.page_width, sec.page_height = Emu(EMU(w)), Emu(EMU(h))
            sec.left_margin, sec.right_margin = Emu(EMU(l + gut)), Emu(EMU(r))
            sec.top_margin, sec.bottom_margin = Emu(EMU(t + hd)), Emu(EMU(b + ft))
            sec.header_distance, sec.footer_distance = Emu(EMU(t)), Emu(EMU(b))
        body = self.doc.element.body
        sectpr = body.find(qn("w:sectPr"))
        for e in self.make_blocks(self.src.blocks, self.doc.part):
            sectpr.addprevious(e)
        if sectpr.getprevious() is None or sectpr.getprevious().tag == qn("w:tbl"):
            endp = _el("w:p")
            ppr = _sub(endp, "w:pPr")
            _sub(ppr, "w:spacing", **{"w:before": 0, "w:after": 0, "w:line": 20, "w:lineRule": "exact"})
            sectpr.addprevious(endp)
        # 머리말 / 꼬리말
        for blocks, hf in ((self.src.header, sec.header), (self.src.footer, sec.footer)):
            if not blocks:
                continue
            hf.is_linked_to_previous = False
            el = hf._element
            for c in list(el):
                el.remove(c)
            for e in self.make_blocks(blocks, hf.part):
                el.append(e)
            # Word 는 머리말/꼬리말 끝에 문단이 꼭 있어야 함 → 표 뒤 빈 문단을 1pt 로 (본문이 밀리지 않게)
            if not len(el) or el[-1].tag != qn("w:p"):
                el.append(_el("w:p"))
            last = el[-1]
            if not "".join(t.text or "" for t in last.iter(qn("w:t"))).strip() and last.find(".//" + qn("w:drawing")) is None:
                for c in list(last):
                    last.remove(c)
                ppr = _sub(last, "w:pPr")
                _sub(ppr, "w:spacing", **{"w:before": 0, "w:after": 0, "w:line": 20, "w:lineRule": "exact"})
                rpr = _sub(ppr, "w:rPr")
                _sub(rpr, "w:sz", **{"w:val": 2})
        self._settings()
        self.doc.save(out_path)
        return out_path

    def _settings(self):
        st = self.doc.settings.element
        compat = st.find(qn("w:compat"))
        if compat is None:
            compat = _el("w:compat")
            st.append(compat)
        if compat.find(qn("w:suppressSpBfAfterPgBrk")) is None:      # 쪽 나누기 뒤 '문단 위 간격' 없앰
            compat.insert(0, _el("w:suppressSpBfAfterPgBrk"))
        dts = st.find(qn("w:defaultTabStop"))
        if dts is None:
            dts = _el("w:defaultTabStop")
            st.insert(0, dts)
        dts.set(qn("w:val"), "800")                       # 한글 기본 탭 간격 40pt
        # 기본 글꼴 = 본문에서 가장 많이 쓴 글자 모양
        counts = {}
        for k, obj in self.src.blocks:
            if k == "p":
                for _, cs in obj.chars:
                    counts[cs] = counts.get(cs, 0) + 1
        if counts:
            cs = self.info.char[max(counts, key=counts.get)]
            ko = self.info.face(cs, 0)
            en = self.info.face(cs, 1) or ko
            normal = self.doc.styles["Normal"]
            normal.font.name = en
            rpr = normal.element.get_or_add_rPr()
            fonts = rpr.find(qn("w:rFonts"))
            if fonts is None:
                fonts = _sub(rpr, "w:rFonts")
            fonts.set(qn("w:eastAsia"), ko or en)
            from docx.shared import Pt
            normal.font.size = Pt(cs["size"] / 100.0)


def build_docx(hwp_path, out_path=None, progress=None):
    """한글 → 깔끔한 Word. 반환: 만든 파일 경로"""
    out_path = out_path or os.path.splitext(hwp_path)[0] + "_정리.docx"
    if progress:
        progress("한글 원본 읽는 중…")
    src = HwpSource(hwp_path)
    if progress:
        progress("Word 문서 만드는 중…")
    Builder(src).build(out_path)
    return out_path


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        print(build_docx(f))
