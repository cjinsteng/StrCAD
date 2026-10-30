"""PDF 도면 → 조사 도면 배경 / 부재 인식.

· 페이지를 그림으로 그려(pypdfium2) 배경으로 깐다. PDF 에는 용지 크기(pt)가 들어 있으므로
  축척(1/N)만 정하면 1px 의 실제 길이(mm)가 정확히 정해진다 (사진처럼 모서리 맞추기가 필요 없음).
· 부재 인식은 그린 그림에 사진 인식(photo_plan)을 그대로 쓰되, PDF 안에 글자가 들어 있으면(CAD에서 내보낸 PDF)
  OCR 대신 그 글자를 바로 쓴다 (pdfminer.six). 스캔 PDF 는 OCR.
두 패키지 모두 상업적 사용이 자유로운 라이선스(Apache/BSD, MIT).
"""
from __future__ import annotations

import math

PT_MM = 25.4 / 72.0


def available() -> tuple[bool, str]:
    try:
        import pypdfium2  # noqa: F401
    except ImportError:
        return False, "PDF 도면에는 pypdfium2 패키지가 필요합니다 (pip install pypdfium2)."
    return True, ""


def _doc(path):
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(path)


def page_count(path) -> int:
    d = _doc(path)
    try:
        return len(d)
    finally:
        d.close()


def page_sizes(path) -> list[tuple[float, float]]:
    """각 페이지 (가로 mm, 세로 mm) — 회전 반영, 화면에 보이는 방향."""
    d = _doc(path)
    try:
        out = []
        for i in range(len(d)):
            w, h = d[i].get_size()
            out.append((w * PT_MM, h * PT_MM))
        return out
    finally:
        d.close()


def paper_name(w_mm, h_mm) -> str:
    a, b = sorted((w_mm, h_mm))
    for n, (x, y) in (("A0", (841, 1189)), ("A1", (594, 841)), ("A2", (420, 594)), ("A3", (297, 420)), ("A4", (210, 297))):
        if abs(a - x) < 8 and abs(b - y) < 8:
            return n
    return f"{w_mm:.0f}×{h_mm:.0f}mm"


def render(path, page=0, long_px=5000):
    """→ (PIL 이미지 RGB, 용지 mm/px). long_px: 긴 변 픽셀 수."""
    d = _doc(path)
    try:
        pg = d[page]
        w, h = pg.get_size()                       # pt (회전 반영)
        k = long_px / max(w, h)                    # px per pt
        img = pg.render(scale=k, fill_color=(255, 255, 255, 255)).to_pil().convert("RGB")
        return img, PT_MM / k
    finally:
        d.close()


def pdf_texts(path, page, img_h_px, mm_px):
    """PDF 안의 글자 → photo_plan.ocr_texts 와 같은 형식 [(text, cx, cy, ang, h_px, 1.0)] (그림 px 좌표).
    회전된 페이지나 글자가 없는 PDF 는 []."""
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTChar, LAParams
    except ImportError:
        return []
    k = PT_MM / mm_px                              # px per pt
    out = []
    try:
        for lp in (extract_pages(path, page_numbers=[page], laparams=LAParams(detect_vertical=True))):
            if getattr(lp, "rotate", 0) % 360:
                return []
            x0b, y0b = lp.bbox[0], lp.bbox[1]

            def walk(o):
                for c in getattr(o, "_objs", []):
                    if type(c).__name__ in ("LTTextLineHorizontal", "LTTextLineVertical"):
                        add(c)
                    elif hasattr(c, "_objs") and not isinstance(c, LTChar):
                        walk(c)

            def add(line):
                t = line.get_text().strip()
                if not t:
                    return
                chars = [c for c in line if isinstance(c, LTChar)]
                ang = 0.0
                if chars:
                    m = chars[0].matrix
                    ang = math.degrees(math.atan2(m[1], m[0]))
                x0, y0, x1, y1 = line.bbox
                cx, cy = ((x0 + x1) / 2 - x0b) * k, img_h_px - ((y0 + y1) / 2 - y0b) * k
                hh = (min(x1 - x0, y1 - y0) if abs(ang) > 45 else (y1 - y0)) * k
                out.append((t, cx, cy, ang, hh, 1.0))
            walk(lp)
    except Exception:          # noqa: BLE001 — 깨진 PDF 등은 OCR 로
        return []
    return out


def recognize_pdf(path, page=0, scale=100.0, use_ocr=True, log=print):
    """PDF 한 페이지 → (그림 BGR, AnalysisResult, mm/px(실제), texts)."""
    from . import photo_plan as PP
    import cv2
    import numpy as np
    pil, mm_px = render(path, page, 5000)
    k_mm = mm_px * float(scale)
    flat = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    h, w = flat.shape[:2]
    log(f"PDF {page + 1}쪽 {w}×{h}px · 1px = {k_mm:.1f}mm (축척 1/{scale:g})")
    texts = pdf_texts(path, page, h, mm_px)
    if len(texts) >= 3:
        log(f"  PDF 글자 {len(texts)}개 사용 (OCR 생략)")
    elif use_ocr and PP.ocr_available():
        texts = PP.ocr_texts(flat, log=log)
    else:
        texts = []
        if use_ocr:
            log(PP.ocr_missing_text())
    res = PP.recognize_image(flat, k_mm, texts, log=log)
    drop_frame(res, w * k_mm, h * k_mm, log)
    return flat, res, k_mm, texts


def drop_frame(res, W, H, log=print, edge=0.06):
    """용지 테두리(도곽선)를 보·벽으로 잡은 것 지우기 — 용지 가장자리를 따라 길게 놓인 선."""
    mx, my = W * edge, H * edge
    keep, n = [], 0
    for m in res.members:
        if m.kind != "column":
            (x1, y1), (x2, y2) = m.p1, m.p2
            horiz = abs(y1 - y2) < my * 0.2 and (y1 < my or y1 > H - my) and abs(x2 - x1) > W * 0.4
            vert = abs(x1 - x2) < mx * 0.2 and (x1 < mx or x1 > W - mx) and abs(y2 - y1) > H * 0.4
            if horiz or vert:
                n += 1
                continue
        keep.append(m)
    if n:
        res.members = keep
        log(f"  도곽선 {n}개 제외")
