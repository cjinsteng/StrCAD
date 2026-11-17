"""
basic_design/pdf_out.py
계산서(Report) → A4 PDF 출력

  · 화면(Tk Canvas)과 같은 그리기 코드(report.render, 스케치 함수)를 Pillow 이미지에 그대로 그린다.
  · A4(210×297mm) 한 장에 맞춰 배율을 정하고, 길면 줄·표 행 경계에서 쪽을 나눈다.
  · 쪽마다 머릿말(제목) · 꼬릿말(부재명, 쪽 번호)을 넣는다.
  · PDF 는 쪽마다 무손실(Flate) 이미지 한 장 — 추가 패키지 없이 Pillow 만 사용.

    export_pdf(path, [(report, sketch_fn, sketch_box, name), …], header="RC SLAB DESIGN")
"""
import datetime
import os
import sys
import zlib

from . import report as RP
from . import theme as T

DPI = 240
A4_MM = (210.0, 297.0)
A4_PT = (595.28, 841.89)
MARGIN_X_MM = 15.0
HEAD_MM = 26.0          # 위 여백 + 머릿말
FOOT_MM = 17.0          # 꼬릿말 + 아래 여백


class PdfExportError(RuntimeError):
    pass


def _mm(v):
    return int(round(v / 25.4 * DPI))


# ── 글꼴 ─────────────────────────────────────────────────────
_FONT_FILES = {
    False: [r"C:\Windows\Fonts\malgun.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"],
    True: [r"C:\Windows\Fonts\malgunbd.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"],
}
_font_cache = {}


def _font_path(bold):
    win = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    cands = list(_FONT_FILES[bold])
    if win:
        cands.insert(0, os.path.join(win, "Fonts", "malgunbd.ttf" if bold else "malgun.ttf"))
    for p in cands:
        if os.path.exists(p):
            return p
    if bold:
        return _font_path(False)
    raise PdfExportError("한글 글꼴(맑은 고딕)을 찾지 못했습니다.")


def _pil_font(px, bold):
    from PIL import ImageFont
    key = (int(round(px)), bool(bold))
    if key not in _font_cache:
        path = _font_path(bold)
        idx = 1 if path.lower().endswith(".ttc") and "noto" in path.lower() else 0     # Noto CJK: KR = 1
        _font_cache[key] = ImageFont.truetype(path, key[0], index=idx)
    return _font_cache[key]


class _Font:
    """tkinter.font.Font 대용 — measure() 는 화면 단위(px)"""

    def __init__(self, size_pt, bold, scale):
        self.scale = scale
        self.pil = _pil_font(size_pt * 96.0 / 72.0 * scale, bold)

    def measure(self, text):
        return self.pil.getlength(text) / self.scale


_ANCHOR = {"center": "mm", "w": "lm", "e": "rm", "s": "ms", "n": "mt", "sw": "ls", "se": "rs", "nw": "lt", "ne": "rt"}


class PilCanvas:
    """report.render / 스케치 함수가 쓰는 Tk Canvas 메서드를 Pillow 로 구현"""

    def __init__(self, width, height, scale):
        from PIL import Image, ImageDraw
        self.scale = scale
        self.img = Image.new("RGB", (int(width * scale) + 2, int(height * scale) + 2), "white")
        self.d = ImageDraw.Draw(self.img)
        self.report_fonts = {
            "h": _Font(14, True, scale), "sub": _Font(11, True, scale), "n": _Font(10, False, scale),
            "b": _Font(10, True, scale), "s": _Font(8, False, scale),
        }

    # Tk 호환 (동작 없음)
    def delete(self, *_):
        pass

    def configure(self, **_):
        pass

    def _p(self, coords):
        s = self.scale
        return [(coords[i] * s, coords[i + 1] * s) for i in range(0, len(coords) - 1, 2)]

    @staticmethod
    def _flat(args):
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            args = args[0]
        out = []
        for a in args:
            if isinstance(a, (list, tuple)):
                out.extend(a)
            else:
                out.append(a)
        return out

    def _w(self, width):
        return max(int(round(float(width) * self.scale * 0.8)), 1)

    def _font(self, font):
        if isinstance(font, _Font):
            return font.pil
        if isinstance(font, (tuple, list)) and len(font) >= 2:
            return _pil_font(float(font[1]) * 96.0 / 72.0 * self.scale, "bold" in font[2:])
        return self.report_fonts["n"].pil

    def create_line(self, *args, fill="black", width=1, arrow=None, arrowshape=(8, 10, 3), **_):
        pts = self._p(self._flat(args))
        if not fill or len(pts) < 2:
            return
        self.d.line(pts, fill=fill, width=self._w(width), joint="curve")
        if arrow in ("last", "both"):
            self._arrow(pts[-2], pts[-1], arrowshape, fill)
        if arrow in ("first", "both"):
            self._arrow(pts[1], pts[0], arrowshape, fill)

    def _arrow(self, p0, p1, shape, fill):
        import math
        s = self.scale
        ln, wd = shape[1] * s, shape[2] * s
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        bx, by = p1[0] - ln * math.cos(ang), p1[1] - ln * math.sin(ang)
        nx, ny = -math.sin(ang) * wd, math.cos(ang) * wd
        self.d.polygon([p1, (bx + nx, by + ny), (bx - nx, by - ny)], fill=fill)

    def create_rectangle(self, x1, y1, x2, y2, fill="", outline="black", width=1, **_):
        (a, b), (c, e) = self._p([x1, y1, x2, y2])
        self.d.rectangle([min(a, c), min(b, e), max(a, c), max(b, e)], fill=fill or None,
                         outline=outline or None, width=self._w(width))

    def create_oval(self, x1, y1, x2, y2, fill="", outline="black", **_):
        (a, b), (c, e) = self._p([x1, y1, x2, y2])
        self.d.ellipse([a, b, c, e], fill=fill or None, outline=outline or None)

    def create_polygon(self, *args, fill="", outline="", width=1, **_):
        pts = self._p(self._flat(args))
        if fill:
            self.d.polygon(pts, fill=fill)
        if outline:
            self.d.line(pts + [pts[0]], fill=outline, width=self._w(width))

    def create_text(self, x, y, text="", anchor="center", font=None, fill="black", angle=0, **_):
        f = self._font(font)
        X, Y = x * self.scale, y * self.scale
        if not angle:
            self.d.text((X, Y), text, font=f, fill=fill or "black", anchor=_ANCHOR.get(anchor, "mm"))
            return
        from PIL import Image, ImageDraw
        w = int(f.getlength(text)) + 8
        h = int(f.size * 1.5) + 4
        tmp = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        ImageDraw.Draw(tmp).text((w / 2, h / 2), text, font=f, fill=fill or "black", anchor="mm")
        rot = tmp.rotate(angle, expand=True)
        # 세로 글자(90°): anchor 's' = 글자 아랫변이 (x, y) 쪽 → 왼쪽에 놓인다
        if anchor == "s":
            pos = (int(X - rot.width), int(Y - rot.height / 2))
        else:
            pos = (int(X - rot.width / 2), int(Y - rot.height / 2))
        self.img.paste(rot, pos, rot)


# ── 쪽 나누기 · 쪽 그리기 ────────────────────────────────────
def _split(total, breaks, page_h):
    """[(시작, 끝), …]  — breaks(나눠도 되는 y) 중에서 쪽 높이를 넘지 않는 가장 아래 위치에서 자른다."""
    cuts, a = [], 0.0
    cands = sorted(set(b for b in breaks if 0 < b < total))
    while total - a > page_h:
        ok = [b for b in cands if a + page_h * 0.35 < b <= a + page_h]
        b = ok[-1] if ok else a + page_h
        cuts.append((a, b))
        a = b
    cuts.append((a, total))
    return cuts


def _pages_for(rep, sketch, sketch_box, scale, page_h):
    """한 부재의 계산서를 쪽 이미지 조각 목록으로"""
    probe = PilCanvas(RP.PAGE_W, 10, scale)                     # 1차: 높이·쪽 경계만 계산
    breaks = []
    total = RP.render(probe, rep, sketch=sketch, sketch_box=sketch_box, breaks=breaks) - 14
    cv = PilCanvas(RP.PAGE_W, total + 4, scale)
    RP.render(cv, rep, sketch=sketch, sketch_box=sketch_box)
    out = []
    for a, b in _split(total, breaks, page_h):
        out.append(cv.img.crop((0, int(a * scale), cv.img.width, int(b * scale))))
    return out


def _compose(body, header, name, page_no, page_cnt, stamp, footer):
    from PIL import Image, ImageDraw
    W, H = _mm(A4_MM[0]), _mm(A4_MM[1])
    mx = _mm(MARGIN_X_MM)
    page = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(page)
    k = DPI / 72.0
    f_title = _pil_font(17 * k, True)
    f_small = _pil_font(8.5 * k, False)
    f_name = _pil_font(10 * k, True)
    y_rule = _mm(HEAD_MM) - _mm(4)
    d.text((mx, y_rule - _mm(2.2)), header, font=f_title, fill=T.NAVY, anchor="ls")
    if name:
        d.text((W - mx, y_rule - _mm(2.4)), name, font=f_name, fill=T.INK, anchor="rs")
    d.line([(mx, y_rule), (W - mx, y_rule)], fill=T.NAVY, width=max(int(k * 1.6), 2))
    d.line([(mx, y_rule + int(k * 2.6)), (W - mx, y_rule + int(k * 2.6))], fill=T.ORANGE, width=max(int(k * 0.8), 1))
    page.paste(body, (mx, _mm(HEAD_MM)))
    y_f = H - _mm(FOOT_MM) + _mm(4)
    d.line([(mx, y_f), (W - mx, y_f)], fill="#9CA3AF", width=max(int(k * 0.6), 1))
    d.text((mx, y_f + _mm(1.5)), footer, font=f_small, fill=T.MUTED, anchor="lt")
    d.text((W / 2, y_f + _mm(1.5)), stamp, font=f_small, fill=T.MUTED, anchor="mt")
    d.text((W - mx, y_f + _mm(1.5)), f"{page_no} / {page_cnt}", font=f_small, fill=T.MUTED, anchor="rt")
    return page


def render_pages(items, header="RC SLAB DESIGN", footer="StrCAD  ·  Basic Design  │  RC Slab Lite"):
    """items: [(report, sketch_fn, sketch_box, name), …] → A4 쪽 이미지 목록 (부재마다 새 쪽)"""
    try:
        import PIL  # noqa: F401
    except ImportError as e:
        raise PdfExportError("출력에는 Pillow 패키지가 필요합니다.  pip install pillow") from e
    W, H = _mm(A4_MM[0]), _mm(A4_MM[1])
    scale = (W - 2 * _mm(MARGIN_X_MM)) / float(RP.PAGE_W)
    page_h = (H - _mm(HEAD_MM) - _mm(FOOT_MM)) / scale
    parts = []
    for rep, sketch, box, name in items:
        for body in _pages_for(rep, sketch, box, scale, page_h):
            parts.append((body, name))
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return [_compose(body, header, name, i + 1, len(parts), stamp, footer) for i, (body, name) in enumerate(parts)]


def write_pdf(path, pages):
    """쪽 이미지 목록 → A4 PDF (쪽마다 색인색 Flate 이미지 한 장)"""
    objs = []                                    # 1-based PDF 객체 본문(bytes)

    def add(body):
        objs.append(body)
        return len(objs)

    cat = add(b"")
    pgs = add(b"")
    kids = []
    for im in pages:
        q = im.quantize(colors=96, dither=0)     # 무손실에 가깝게 색 수만 줄임
        pal = bytes(q.getpalette()[:96 * 3])
        data = zlib.compress(q.tobytes(), 9)
        w, h = q.size
        img = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /BitsPerComponent 8 "
                  b"/ColorSpace [/Indexed /DeviceRGB %d <%s>] /Filter /FlateDecode /Length %d >>\nstream\n"
                  % (w, h, len(pal) // 3 - 1, pal.hex().encode(), len(data)) + data + b"\nendstream")
        cont = b"q %.2f 0 0 %.2f 0 0 cm /Im0 Do Q" % A4_PT
        con = add(b"<< /Length %d >>\nstream\n" % len(cont) + cont + b"\nendstream")
        pg = add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /XObject << /Im0 %d 0 R >> >> "
                 b"/Contents %d 0 R >>" % (pgs, A4_PT[0], A4_PT[1], img, con))
        kids.append(pg)
    objs[cat - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pgs
    objs[pgs - 1] = b"<< /Type /Pages /Count %d /Kids [%s] >>" % (len(kids), b" ".join(b"%d 0 R" % k for k in kids))
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = []
    for i, body in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref)
    with open(path, "wb") as f:
        f.write(out)


def export_pdf(path, items, header="RC SLAB DESIGN", footer="StrCAD  ·  Basic Design  │  RC Slab Lite"):
    pages = render_pages(items, header, footer)
    write_pdf(path, pages)
    return len(pages)


def open_file(path):
    """기본 프로그램(PDF 뷰어)으로 연다 — 뷰어에서 인쇄(Ctrl+P)"""
    import subprocess
    if sys.platform.startswith("win"):
        os.startfile(path)                       # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
