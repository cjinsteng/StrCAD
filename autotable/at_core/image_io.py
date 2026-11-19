"""
image_io.py — 사진 · PDF 일람표 가져오기
  · PDF: 글자가 들어 있는 PDF(CAD 출력) 는 글자 위치를 그대로, 스캔 PDF 는 글자 인식(OCR)
  · 사진: 용지 모서리 찾기 → 원근 보정 → 글자 인식(RapidOCR) → 위치로 일람표 읽기
CAD Analysis 모듈(cad_analysis.photo_plan / pdf_plan)의 함수를 재사용하고, 없으면 간이 방식으로 처리.
"""
from __future__ import annotations

import os
import sys

from .parse_layout import TItem, parse_any


def _cad_analysis():
    try:
        from cad_analysis import pdf_plan, photo_plan       # noqa: F401
        return photo_plan, pdf_plan
    except Exception:                                    # noqa: BLE001
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(here, "..", "..", "strcad_cad_analysis"), os.path.join(here, "..", "strcad_cad_analysis")):
        if os.path.isdir(c) and c not in sys.path:
            sys.path.insert(0, os.path.normpath(c))
    try:
        from cad_analysis import pdf_plan, photo_plan
        return photo_plan, pdf_plan
    except Exception:                                    # noqa: BLE001
        return None, None


def available():
    msg = []
    try:
        import numpy  # noqa: F401
        import cv2  # noqa: F401
    except Exception:                                    # noqa: BLE001
        msg.append("opencv-python-headless, numpy")
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:                                    # noqa: BLE001
        msg.append("rapidocr_onnxruntime (글자 인식)")
    return (not msg), ("필요한 패키지: " + ", ".join(msg)) if msg else ""


def _to_items(texts, img_h):
    """[(text, cx, cy, ang, h, score)] (그림 px, y 아래로) → TItem (y 위로)."""
    out = []
    for t in texts:
        text, cx, cy, ang, hh = t[0], t[1], t[2], t[3], t[4]
        score = t[5] if len(t) > 5 else 1.0
        if not text or score < 0.45:
            continue
        out.append(TItem(text.strip(), float(cx), float(img_h - cy), float(max(hh, 1.0)), float(ang)))
    return out


_OCR = None


def _ocr_simple(img_bgr, log=print):
    global _OCR
    from rapidocr_onnxruntime import RapidOCR
    if _OCR is None:
        _OCR = RapidOCR()
    res, _ = _OCR(img_bgr)
    out = []
    import math
    for box, text, score in res or []:
        cx = sum(p[0] for p in box) / 4
        cy = sum(p[1] for p in box) / 4
        hh = (math.dist(box[0], box[3]) + math.dist(box[1], box[2])) / 2
        out.append((text, cx, cy, 0.0, hh, float(score)))
    return out


def _read_bgr(path):
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def ocr_image(img_bgr, log=print, vertical_numbers=True):
    PP, _ = _cad_analysis()
    texts = PP.ocr_texts(img_bgr, log=log) if PP is not None else _ocr_simple(img_bgr, log)
    if vertical_numbers:                     # 세로 치수 글자(보 춤 등): 90° 돌려 숫자만 한 번 더
        import re
        import cv2
        h, w = img_bgr.shape[:2]
        rot = cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)          # (x,y) → (h-1-y, x)
        log("  세로 글자(치수) 인식…")
        extra = PP.ocr_texts(rot, log=lambda *a: None) if PP is not None else _ocr_simple(rot)
        for t in extra:
            if re.fullmatch(r"\d{2,4}", t[0].strip()):
                rx, ry = t[1], t[2]
                texts.append((t[0], ry, h - 1 - rx, 90.0, t[4], t[5] if len(t) > 5 else 1.0))
    return texts


def import_photo(path, want="auto", flatten=True, log=print):
    """→ (rows_by_type, warnings)"""
    ok, msg = available()
    if not ok:
        raise RuntimeError(msg)
    PP, _ = _cad_analysis()
    img = PP.read_image(path) if PP else _read_bgr(path)
    if flatten and PP is not None:
        try:
            corners = PP.detect_corners(img)
            h, w = img.shape[:2]
            if corners != [(0.0, 0.0), (w - 1.0, 0.0), (w - 1.0, h - 1.0), (0.0, h - 1.0)]:
                img = PP.warp(img, corners)
                log("용지 모서리를 찾아 원근을 보정했습니다.")
        except Exception as e:                           # noqa: BLE001
            log(f"원근 보정 건너뜀: {e}")
    log("글자 인식 중… (사진 크기에 따라 수십 초 걸릴 수 있습니다)")
    texts = ocr_image(img, log)
    log(f"글자 {len(texts)}개 인식")
    items = _to_items(texts, img.shape[0])
    return parse_any(items, [], want, log)


def pdf_pages(path):
    _, PDF = _cad_analysis()
    if PDF is not None:
        return PDF.page_count(path)
    import pypdfium2 as pdfium
    d = pdfium.PdfDocument(path)
    try:
        return len(d)
    finally:
        d.close()


def import_pdf(path, page=0, want="auto", log=print):
    """→ (rows_by_type, warnings)"""
    _, PDF = _cad_analysis()
    import numpy as np
    if PDF is not None:
        img, mm_px = PDF.render(path, page, long_px=6000)
        H = img.size[1]
        texts = PDF.pdf_texts(path, page, H, mm_px)
    else:
        import pypdfium2 as pdfium
        d = pdfium.PdfDocument(path)
        pg = d[page]
        w, h = pg.get_size()
        k = 6000 / max(w, h)
        img = pg.render(scale=k, fill_color=(255, 255, 255, 255)).to_pil().convert("RGB")
        d.close()
        H = img.size[1]
        texts = []
    if len(texts) >= 10:
        log(f"PDF 안의 글자 {len(texts)}개 사용")
    else:
        ok, msg = available()
        if not ok:
            raise RuntimeError("글자가 없는 (스캔) PDF 입니다. " + msg)
        import cv2
        log("글자가 없는 PDF → 글자 인식(OCR) 중…")
        bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        texts = ocr_image(bgr, log)
        log(f"글자 {len(texts)}개 인식")
    items = _to_items(texts, H)
    return parse_any(items, [], want, log)
