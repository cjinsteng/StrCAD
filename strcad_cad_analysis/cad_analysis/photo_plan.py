"""종이 도면 사진 → 부재 인식.

1. 용지 네 모서리 찾기(자동, 사용자가 조정) → 반듯하게 펴기 (원근 보정)
2. 축척(용지 크기 × 도면 축척 또는 mm/px) 으로 픽셀 → mm
3. 글자 읽기 (RapidOCR, 설치돼 있으면) → G1·B1·C1·W1·400x700 같은 부재 표기
4. 형상 벡터화 (OpenCV): 칠해진 사각형 = 기둥, 칠해진 긴 덩어리 = 벽, 선 = 보/거더/벽 선
5. 위 결과를 DXF와 같은 DrawingData(레이어: 사진_기둥/사진_벽/사진_선/사진_글자)로 만들어
   기존 분석기(analyze)에 넣음 → 기둥·거더·보·벽 + 부재명 매칭 + 절점까지 DXF와 같은 흐름.

사진 품질에 따라 인식률이 달라지므로 결과는 '후보'이며, 사진을 배경으로 띄운 채 편집 탭에서 고친다.
필요 패키지: opencv-python-headless, numpy, (선택) rapidocr_onnxruntime
"""
from __future__ import annotations

import math
from collections import Counter

from .model import Segment, TextItem

PAPER_MM = {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210)}
PHOTO_ROLES = {"사진_기둥": "column", "사진_벽": "wall", "사진_선": "auto", "사진_글자": "member_text",
               "사진_그리드": "grid"}


def available() -> tuple[bool, str]:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False, "도면 사진 인식에는 opencv-python-headless, numpy 패키지가 필요합니다."
    return True, ""


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def ocr_missing_text():
    import sys
    v = sys.version_info
    if v >= (3, 15):
        return (f"부재명 글자 인식(RapidOCR)은 Python {v[0]}.{v[1]}에서 아직 설치할 수 없어(onnxruntime 미지원) "
                "형상만 인식합니다. 부재명까지 읽으려면 설치 파일(StrCAD_Setup)을 쓰거나 Python 3.12로 실행하세요.")
    return "글자 인식(RapidOCR)이 설치되지 않아 부재명은 읽지 않습니다. (pip install rapidocr_onnxruntime)"


def _cv():
    import cv2
    import numpy as np
    return cv2, np


# =============================================================================
#  1. 사진 읽기 · 모서리 · 원근 보정
# =============================================================================
def read_image(path):
    """한글 경로도 되게 PIL로 읽어 BGR numpy (EXIF 회전 반영)."""
    cv2, np = _cv()
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def _order(pts):
    """[tl, tr, br, bl]"""
    pts = sorted(pts, key=lambda p: p[1])
    top = sorted(pts[:2], key=lambda p: p[0])
    bot = sorted(pts[2:], key=lambda p: p[0])
    return [top[0], top[1], bot[1], bot[0]]


def detect_corners(img):
    """용지(밝은 큰 사각형) 네 모서리. 못 찾으면 이미지 네 모서리."""
    cv2, np = _cv()
    h, w = img.shape[:2]
    k = 1000.0 / max(h, w)
    small = cv2.resize(img, (max(1, int(w * k)), max(1, int(h * k))))
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    best = None
    for th in (cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], cv2.Canny(g, 40, 120)):
        m = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(c)
            if area < 0.25 * small.shape[0] * small.shape[1]:
                break
            peri = cv2.arcLength(c, True)
            for eps in (0.02, 0.03, 0.05):
                ap = cv2.approxPolyDP(c, eps * peri, True)
                if len(ap) == 4 and cv2.isContourConvex(ap):
                    if best is None or area > best[0]:
                        best = (area, [(float(p[0][0]) / k, float(p[0][1]) / k) for p in ap])
                    break
    if best and best[0] < 0.98 * small.shape[0] * small.shape[1]:
        return _order(best[1])
    return [(0.0, 0.0), (w - 1.0, 0.0), (w - 1.0, h - 1.0), (0.0, h - 1.0)]


def warp(img, corners, out_w=None):
    """네 모서리를 직사각형으로 편다. 출력 크기는 원래 변 길이 기준(최대 5000px)."""
    cv2, np = _cv()
    tl, tr, br, bl = _order(corners)
    wa = math.dist(tl, tr); wb = math.dist(bl, br)
    ha = math.dist(tl, bl); hb = math.dist(tr, br)
    W, H = max(wa, wb), max(ha, hb)
    k = min(1.0, 5000.0 / max(W, H))
    if out_w:
        k = out_w / W
    W, H = int(W * k), int(H * k)
    src = np.float32([tl, tr, br, bl])
    dst = np.float32([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (W, H), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


def paper_k(corners, paper="A3", scale=200):
    """사진에서 찾은 용지 네 모서리 → 사진 1px 의 실제 길이(mm). 분석 영역을 따로 잘라도 그대로 쓸 수 있음."""
    tl, tr, br, bl = _order(corners)
    w = max(math.dist(tl, tr), math.dist(bl, br))
    h = max(math.dist(tl, bl), math.dist(tr, br))
    a, b = PAPER_MM.get(paper, PAPER_MM["A3"])
    long_px, long_mm = max(w, h), max(a, b)
    return long_mm * float(scale) / max(long_px, 1.0)


def mm_per_px(img_w_px, paper="A3", scale=200, landscape=True):
    a, b = PAPER_MM.get(paper, PAPER_MM["A3"])
    paper_w = max(a, b) if landscape else min(a, b)
    return paper_w * float(scale) / img_w_px


# =============================================================================
#  2. 글자 (OCR)
# =============================================================================
_OCR = None


def _ocr_once(img, log, tile, overlap):
    global _OCR
    cv2, np = _cv()
    from rapidocr_onnxruntime import RapidOCR
    if _OCR is None:
        _OCR = RapidOCR()
    h, w = img.shape[:2]
    out = []
    ys = list(range(0, max(1, h - overlap), tile - overlap)) or [0]
    xs = list(range(0, max(1, w - overlap), tile - overlap)) or [0]
    for y in ys:
        for x in xs:
            crop = img[y:y + tile, x:x + tile]
            if crop.size == 0 or crop.min() > 200:          # 빈 종이
                continue
            try:
                res, _ = _OCR(crop)
            except Exception as e:  # noqa: BLE001
                log(f"글자 인식 오류: {e}")
                res = None
            for box, text, score in res or []:
                out.append(([(px + x, py + y) for px, py in box], text, float(score)))
    return out


def dominant_angles(img, max_n=2):
    """도면 선의 주 방향(0·90° 말고 기울어진 방향) — 기울어진 글자 읽기용."""
    cv2, np = _cv()
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(g, None, fx=0.5, fy=0.5)
    ink = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    lines = cv2.HoughLinesP(ink, 1, np.pi / 360, 80, minLineLength=80, maxLineGap=4)
    if lines is None:
        return []
    hist = Counter()
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 90
        hist[round(a)] += math.hypot(x2 - x1, y2 - y1)
    tot = sum(hist.values()) or 1
    out = []
    for a, wgt in hist.most_common(6):
        if wgt / tot < 0.12 or a <= 2 or a >= 88:
            continue
        if all(abs(a - b) > 5 for b in out):
            out.append(float(a))
        if len(out) >= max_n:
            break
    return out


def ocr_texts(img, log=print, tile=1600, overlap=250):
    """RapidOCR로 글자 읽기 — 원본 + 도면이 기울어져 있으면 그 방향으로 돌린 사본도 읽음.
    → [(text, cx, cy, angle_deg, height_px, score)]  (angle: 도면 좌표계, 반시계 +)"""
    cv2, np = _cv()
    if not ocr_available():
        log(ocr_missing_text())
        return []
    h, w = img.shape[:2]
    up = 1.0
    if max(h, w) < 2500:                                     # 작은 사진은 키워서
        up = 2500.0 / max(h, w)
        img = cv2.resize(img, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC)
        h, w = img.shape[:2]
    rots = [0.0]
    for a in dominant_angles(img):
        rots += [a, a - 90.0]
    raw = []
    for i, rot in enumerate(rots):
        log(f"  글자 인식 {i + 1}/{len(rots)} (방향 {rot:+.0f}°)")
        if rot == 0:
            M = None
            src = img
        else:
            M = cv2.getRotationMatrix2D((w / 2, h / 2), rot, 1.0)
            cos, sin = abs(M[0, 0]), abs(M[0, 1])
            nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
            M[0, 2] += nw / 2 - w / 2
            M[1, 2] += nh / 2 - h / 2
            src = cv2.warpAffine(img, M, (nw, nh), borderValue=(255, 255, 255))
            Mi = cv2.invertAffineTransform(M)
        for box, text, score in _ocr_once(src, log, tile, overlap):
            if M is not None:
                box = [(Mi[0, 0] * x + Mi[0, 1] * y + Mi[0, 2], Mi[1, 0] * x + Mi[1, 1] * y + Mi[1, 2]) for x, y in box]
            pts = [(x / up, y / up) for x, y in box]
            cx = sum(p[0] for p in pts) / 4
            cy = sum(p[1] for p in pts) / 4
            ang = -math.degrees(math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0]))
            hh = (math.dist(pts[0], pts[3]) + math.dist(pts[1], pts[2])) / 2
            raw.append((text.strip(), cx, cy, ang, hh, score))
    # 같은 자리 중복 → 점수 높은 것 (기울어진 글자는 맞는 방향에서 점수가 높음)
    uniq = []
    for t in sorted(raw, key=lambda t: -t[5]):
        if any(math.hypot(u[1] - t[1], u[2] - t[2]) < max(6.0, 0.6 * max(t[4], u[4])) for u in uniq):
            continue
        uniq.append(t)
    return uniq


# =============================================================================
#  3. 형상 벡터화
# =============================================================================
def _merge_lines(segs, ang_tol=2.0, off_tol=2.5, gap=12.0):
    """거의 같은 직선 위의 조각들을 하나로 합침 (굵은 선의 여러 Hough 결과, 점선 조각).
    segs: [(x1,y1,x2,y2)] px → [(x1,y1,x2,y2, coverage)]"""
    items = []
    for x1, y1, x2, y2 in segs:
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1:
            continue
        items.append((L, x1, y1, x2, y2, math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180))
    items.sort(reverse=True)
    nb = max(1, int(round(180 / ang_tol)))
    buckets = {}
    for i, it in enumerate(items):
        buckets.setdefault(int(it[5] / ang_tol) % nb, []).append(i)
    used = [False] * len(items)
    out = []
    for i, (L, x1, y1, x2, y2, a) in enumerate(items):
        if used[i]:
            continue
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        nx, ny = -uy, ux
        off = x1 * nx + y1 * ny
        kb = int(a / ang_tol) % nb
        iv = []
        for kk in (kb - 1, kb, kb + 1):
            for j in buckets.get(kk % nb, ()):
                if used[j]:
                    continue
                _, tx1, ty1, tx2, ty2, ta = items[j]
                da = abs(ta - a)
                if min(da, 180 - da) > ang_tol:
                    continue
                if abs(tx1 * nx + ty1 * ny - off) > off_tol or abs(tx2 * nx + ty2 * ny - off) > off_tol:
                    continue
                p1, p2 = tx1 * ux + ty1 * uy, tx2 * ux + ty2 * uy
                iv.append((min(p1, p2), max(p1, p2)))
                used[j] = True
        if not iv:
            continue
        iv.sort()
        cur = list(iv[0])
        pieces = []
        for p, q in iv[1:]:
            if p <= cur[1] + gap:
                cur[1] = max(cur[1], q)
            else:
                pieces.append(cur)
                cur = [p, q]
        pieces.append(cur)
        for p, q in pieces:
            cover = sum(max(0.0, min(bq, q) - max(bp, p)) for bp, bq in iv) / max(q - p, 1e-6)
            out.append((p * ux + off * nx, p * uy + off * ny, q * ux + off * nx, q * uy + off * ny, min(1.0, cover)))
    return out


def _shapes(img, k_mm, texts=(), log=print):
    return vectorize(img, k_mm, texts, log, _shapes_only=True)


def vectorize(img, k_mm, texts=(), log=print, _shapes_only=False):
    """img(BGR, 펴진 도면) → layers dict (mm 좌표, y 위쪽)."""
    cv2, np = _cv()
    H, W = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 조명 얼룩 제거: 큰 블러로 배경 추정 후 나눔
    bg = cv2.medianBlur(cv2.resize(g, (max(1, W // 8), max(1, H // 8))), 21)
    bg = cv2.resize(bg, (W, H))
    norm = cv2.divide(g, bg, scale=255)
    ink = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    # 선 굵기 추정
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    vals = dist[dist > 0]
    t = float(np.median(vals)) * 2 if vals.size else 2.0
    t = max(1.5, min(t, 8.0))
    log(f"  선 굵기 약 {t:.1f}px · 1px = {k_mm:.1f}mm")
    # 글자 영역은 형상에서 뺌
    clean = ink.copy()
    for text, cx, cy, ang, hh, _s in texts:
        r = int(max(hh, 6) * 0.6 + 2)
        wlen = int(max(len(text), 1) * hh * 0.45 + r)
        box = cv2.boxPoints(((cx, cy), (2 * wlen, 2 * r), -ang)).astype(np.int32)
        cv2.fillPoly(clean, [box], 0)

    def P(x, y):
        return x * k_mm, (H - y) * k_mm

    layers = {n: {"segments": [], "polygons": [], "line_segments": [], "texts": []} for n in PHOTO_ROLES}
    # ---- 기둥 = 작은 사각형 (속이 칠해졌든 외곽선만 있든), 벽 = 칠해진 긴 덩어리
    kc = max(3, int(round(t * 2.2)) | 1)
    closed = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, np.ones((kc, kc), np.uint8))
    ko = max(3, int(round(t * 3.5)) | 1)
    blobs = cv2.morphologyEx(closed, cv2.MORPH_OPEN, np.ones((ko, ko), np.uint8))
    lo, hi = 250.0 / k_mm, 2000.0 / k_mm
    cols = []                                   # (cx, cy, poly_px, filled)
    cnts, _ = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        (cx, cy), (bw, bh), ang = cv2.minAreaRect(c)
        a_, b_ = max(bw, bh), min(bw, bh)
        if b_ < lo or a_ > hi or a_ / max(b_, 1e-6) > 2.5:
            continue
        area = cv2.contourArea(c)
        if area < 0.75 * bw * bh:               # 사각형에 가깝지 않음
            continue
        cols.append((cx, cy, cv2.boxPoints(((cx, cy), (bw, bh), ang)), a_))
    # 외곽선 기둥은 바깥·안쪽 두 사각형이 잡힘 → 큰 것 하나만
    cols.sort(key=lambda q: -q[3])
    keep = []
    for q in cols:
        if any(math.hypot(q[0] - r[0], q[1] - r[1]) < r[3] * 0.5 for r in keep):
            continue
        keep.append(q)
    for cx, cy, box, _a in keep:
        layers["사진_기둥"]["polygons"].append([P(float(x), float(y)) for x, y in box])
    _col_boxes = [box for _cx, _cy, box, _a in keep]
    nwall = 0
    cnts, _ = cv2.findContours(blobs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        (cx, cy), (bw, bh), ang = cv2.minAreaRect(c)
        a_, b_ = max(bw, bh), min(bw, bh)
        if b_ <= 0 or a_ / b_ <= 2.5 or b_ * k_mm > 1200 or a_ * k_mm < 600:
            continue
        if cv2.contourArea(c) < 0.6 * bw * bh:
            continue
        layers["사진_벽"]["polygons"].append([P(float(x), float(y)) for x, y in cv2.boxPoints(((cx, cy), (bw, bh), ang))])
        nwall += 1
    log(f"  기둥 후보(사각형) {len(keep)}개, 칠해진 벽 {nwall}개")
    # ---- 선 (덩어리는 빼고)
    thin = cv2.subtract(clean, cv2.dilate(blobs, np.ones((3, 3), np.uint8)))
    minlen = max(15.0, 300.0 / k_mm)
    lines = cv2.HoughLinesP(thin, 1, np.pi / 720, threshold=max(15, int(minlen * 0.6)),
                            minLineLength=minlen * 0.5, maxLineGap=max(3, int(t * 2)))
    raw = [tuple(map(float, l)) for l in lines.reshape(-1, 4)] if lines is not None else []
    merged = _merge_lines(raw, ang_tol=1.5, off_tol=max(1.5, t * 0.8), gap=max(6.0, t * 4, 450.0 / k_mm))
    diag = math.hypot(W, H)
    if _shapes_only:
        return merged, _col_boxes
    nline = ngrid = 0
    for x1, y1, x2, y2, cover in merged:
        L = math.hypot(x2 - x1, y2 - y1)
        if L < minlen:
            continue
        a = P(x1, y1); b = P(x2, y2)
        s = Segment(a[0], a[1], b[0], b[1], "")
        if L > 0.45 * diag and cover < 0.75:          # 길고 끊긴(일점쇄선) 단독선 = 그리드
            s.layer = "사진_그리드"
            layers["사진_그리드"]["segments"].append(s)
            ngrid += 1
        else:
            s.layer = "사진_선"
            layers["사진_선"]["segments"].append(s)
            layers["사진_선"]["line_segments"].append(s)
            nline += 1
    log(f"  선 {len(raw)}조각 → 합쳐서 {nline}개 (그리드 {ngrid}개)")
    # ---- 글자
    for text, cx, cy, ang, hh, score in texts:
        if score < 0.5 or not text:
            continue
        x, y = P(cx, cy)
        layers["사진_글자"]["texts"].append(TextItem(text, x, y, ang, hh * k_mm, "사진_글자"))
    return layers, (0.0, 0.0, W * k_mm, H * k_mm)


def to_drawing(layers, extents, path):
    """layers → DrawingData (dxf_loader 와 같은 구조)."""
    from .dxf_loader import DrawingData, LayerData
    out = {}
    for name, d in layers.items():
        ld = LayerData(name)
        for s in d["segments"]:
            s.layer = name
        ld.segments = list(d["segments"])
        ld.line_segments = list(d["line_segments"])
        ld.polygons = [list(p) for p in d["polygons"]]
        ld.texts = list(d["texts"])
        for p in ld.polygons:                       # 다각형 외곽도 선으로 (벽 두께 판정용)
            for i in range(len(p)):
                a, b = p[i], p[(i + 1) % len(p)]
                sg = Segment(a[0], a[1], b[0], b[1], name)
                ld.line_segments.append(sg)
                if PHOTO_ROLES[name] == "wall":
                    ld.segments.append(sg)
        ld.counts = Counter({"LINE": len(ld.segments), "LWPOLYLINE": len(ld.polygons), "TEXT": len(ld.texts)})
        out[name] = ld
    return DrawingData(path=path, layers=out, extents=extents)


def recognize(path, corners=None, k_mm=None, paper="A3", scale=200, use_ocr=True, log=print):
    """사진 경로 → (펴진 이미지 BGR, DrawingData, k_mm)."""
    cv2, np = _cv()
    img = read_image(path)
    log(f"사진 {img.shape[1]}×{img.shape[0]}px")
    corners = corners or detect_corners(img)
    flat = warp(img, corners)
    h, w = flat.shape[:2]
    landscape = w >= h
    if not k_mm:
        k_mm = mm_per_px(w, paper, scale, landscape)
    log(f"원근 보정 → {w}×{h}px, 용지 {paper} {'가로' if landscape else '세로'} · 축척 1/{scale} → 1px={k_mm:.1f}mm")
    texts = ocr_texts(flat, log=log) if use_ocr else []
    if texts:
        log(f"글자 {len(texts)}개 읽음: " + ", ".join(sorted({t[0] for t in texts})[:20]))
    layers, ext = vectorize(flat, k_mm, texts, log=log)
    dd = to_drawing(layers, ext, path)
    return flat, dd, k_mm


# =============================================================================
#  3b. 방향 모폴로지로 선 찾기 (해상도 낮고 글자 많은 실제 도면 사진용)
# =============================================================================
def _line_kernel(K, ang):
    cv2, np = _cv()
    k = np.zeros((K, K), np.uint8)
    c = K // 2
    dx, dy = math.cos(math.radians(ang)) * c, math.sin(math.radians(ang)) * c
    cv2.line(k, (int(round(c - dx)), int(round(c - dy))), (int(round(c + dx)), int(round(c + dy))), 1, 1)
    return k


def _ink(img, texts=()):
    cv2, np = _cv()
    H, W = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bg = cv2.medianBlur(cv2.resize(g, (max(1, W // 8), max(1, H // 8))), 21)
    norm = cv2.divide(g, cv2.resize(bg, (W, H)), scale=255)
    block = max(15, (min(W, H) // 80) | 1)
    ink = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 10)
    for text, cx, cy, ang, hh, _s in texts:
        r = int(max(hh, 6) * 0.55 + 1)
        wlen = int(max(len(text), 1) * hh * 0.42 + r)
        box = cv2.boxPoints(((cx, cy), (2 * wlen, 2 * r), -ang)).astype(np.int32)
        cv2.fillPoly(ink, [box], 0)
    return ink


def morph_lines(img, texts=(), log=print):
    """글자보다 긴 직선만 남기는 방향 열림(opening) → 중심선 조각.
    → (pieces [(x1,y1,x2,y2,1.0)], 선 마스크, 방향 목록)"""
    cv2, np = _cv()
    H, W = img.shape[:2]
    ink = _ink(img, texts)
    K = max(21, int(min(W, H) / 60) | 1)               # 글자(높이 ~1/100)보다 긴 선
    bases = [0.0, 90.0]
    for a in dominant_angles(img):
        for b in (a, a + 90.0):
            if all(min(abs(b - c) % 180, 180 - abs(b - c) % 180) > 6 for c in bases):
                bases.append(b)
    pieces = []
    union = np.zeros_like(ink)
    for base in bases:
        m = np.zeros_like(ink)
        for d in (-6.0, -4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5, 6.0):     # 책 접힘·원근으로 살짝 휜 선까지
            m |= cv2.morphologyEx(ink, cv2.MORPH_OPEN, _line_kernel(K, base + d))
        # 두 줄로 그린 보(가까운 평행선)와 작은 끊김을 하나로
        r = math.radians(base)
        ux, uy = math.cos(r), math.sin(r)
        cl = _line_kernel(9, base)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cl)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, _line_kernel(5, base + 90))
        union |= m
        n, lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            x, y, w, h, area = st[i]
            ys, xs = np.nonzero(lab[y:y + h, x:x + w] == i)
            if xs.size < K:
                continue
            xs = xs + x
            ys = ys + y
            t = xs * ux + ys * uy                       # 방향 좌표
            o = -xs * uy + ys * ux                      # 수직 좌표
            if t.max() - t.min() < K:
                continue
            step = 4.0
            bins = ((t - t.min()) // step).astype(int)
            order = np.argsort(bins)
            bins, t_s, o_s = bins[order], t[order], o[order]
            cuts = np.flatnonzero(np.diff(bins)) + 1
            pts = []
            for tb, ob in zip(np.split(t_s, cuts), np.split(o_s, cuts)):
                tm, om = float(tb.mean()), float(np.median(ob))
                pts.append((tm * ux - om * uy, tm * uy + om * ux))
            if len(pts) < 2:
                continue
            ap = cv2.approxPolyDP(np.array(pts, np.float32).reshape(-1, 1, 2), 1.5, False).reshape(-1, 2)
            for a_, b_ in zip(ap[:-1], ap[1:]):
                if math.hypot(b_[0] - a_[0], b_[1] - a_[1]) >= 6:
                    pieces.append((float(a_[0]), float(a_[1]), float(b_[0]), float(b_[1]), 1.0))
    log(f"  선 찾기(방향 {', '.join(f'{b:.0f}°' for b in bases)}): 중심선 조각 {len(pieces)}개")
    return pieces, union, ink


def structure_box(pieces, W, H, cells=24):
    """선이 촘촘히 교차하는 곳 = 골조 영역 (도면 테두리·치수선·책상 등 바깥 선 제외용).
    교차점 밀도 격자에서 많이 모인 칸들의 범위."""
    nodes = _crossings(pieces)
    if len(nodes) < 30:
        return 0.0, 0.0, float(W), float(H)
    cw, ch = W / cells, H / cells
    cnt = {}
    for x, y in nodes:
        key = (min(cells - 1, int(x / cw)), min(cells - 1, int(y / ch)))
        cnt[key] = cnt.get(key, 0) + 1
    vals = sorted(cnt.values())
    thr = max(3, vals[int(len(vals) * 0.5)])           # 중간 이상으로 촘촘한 칸
    dense = [k for k, v in cnt.items() if v >= thr]
    if not dense:
        return 0.0, 0.0, float(W), float(H)
    xs = sorted(k[0] for k in dense)
    ys = sorted(k[1] for k in dense)
    q = lambda v, f: v[min(len(v) - 1, max(0, int(round((len(v) - 1) * f))))]
    x0, x1 = q(xs, 0.02) * cw, (q(xs, 0.98) + 1) * cw
    y0, y1 = q(ys, 0.02) * ch, (q(ys, 0.98) + 1) * ch
    return max(0.0, x0 - cw * 0.3), max(0.0, y0 - ch * 0.3), min(float(W), x1 + cw * 0.3), min(float(H), y1 + ch * 0.3)


def clip_to_box(pieces, box, min_len=12.0):
    """상자 안 부분만 남김 (선분 자르기)."""
    x0, y0, x1, y1 = box
    out = []
    for p in pieces:
        ax, ay, bx, by = p[:4]
        dx, dy = bx - ax, by - ay
        t0, t1 = 0.0, 1.0
        ok = True
        for pp, qq in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
            if abs(pp) < 1e-12:
                if qq < 0:
                    ok = False
                    break
                continue
            r = qq / pp
            if pp < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
        if not ok or t0 >= t1:
            continue
        q = (ax + dx * t0, ay + dy * t0, ax + dx * t1, ay + dy * t1) + tuple(p[4:])
        if math.hypot(q[2] - q[0], q[3] - q[1]) >= min_len:
            out.append(q)
    return out


def _crossings(pieces, min_ang=30.0):
    """조각들 사이 교차점 (px)."""
    out = []
    segs = [p for p in pieces if math.hypot(p[2] - p[0], p[3] - p[1]) >= 8]
    for i, a in enumerate(segs):
        d1x, d1y = a[2] - a[0], a[3] - a[1]
        L1 = math.hypot(d1x, d1y)
        for b in segs[i + 1:]:
            d2x, d2y = b[2] - b[0], b[3] - b[1]
            den = d1x * d2y - d1y * d2x
            if abs(den) < math.sin(math.radians(min_ang)) * L1 * math.hypot(d2x, d2y):
                continue
            t = ((b[0] - a[0]) * d2y - (b[1] - a[1]) * d2x) / den
            u = ((b[0] - a[0]) * d1y - (b[1] - a[1]) * d1x) / den
            if -0.05 <= t <= 1.05 and -0.05 <= u <= 1.05:
                out.append((a[0] + d1x * t, a[1] + d1y * t))
    return out


def columns_at_nodes(ink, pieces, extra_boxes=(), log=print, k_mm=None):
    """교차점에 있는 작은 네모(속 채움·외곽선) = 기둥. 글자 덩어리는 교차점에서 떨어져 있어 걸러짐."""
    cv2, np = _cv()
    nodes = _crossings(pieces)
    if not nodes:
        return []
    pts = np.array(nodes, np.float32)
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # 선 두께보다 큰 네모만 남김
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    vals = dist[dist > 0]
    t = max(1.5, float(np.median(vals)) * 2 if vals.size else 2.0)
    kk = max(5, int(round(t * 2.6)) | 1)
    sq = cv2.morphologyEx(closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kk, kk)))
    n, lab, st, cen = cv2.connectedComponentsWithStats(sq, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if not (kk <= w <= kk * 5 and kk <= h <= kk * 5 and 0.4 <= w / h <= 2.5):
            continue
        cx, cy = cen[i]
        d = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).min()
        if d > max(4.0, 0.6 * max(w, h)):
            continue
        boxes.append(np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.float32))
    for b in extra_boxes:                      # 외곽선 사각형 검출 결과도 교차점 근처만
        cx, cy = float(np.mean(b[:, 0])), float(np.mean(b[:, 1]))
        if np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).min() <= max(4.0, 0.5 * float(np.ptp(b[:, 0]))):
            if all(math.hypot(cx - float(np.mean(q[:, 0])), cy - float(np.mean(q[:, 1]))) > 4 for q in boxes):
                boxes.append(np.asarray(b, np.float32))
    if k_mm:                                   # 실제 크기 250~2000mm 만
        lo, hi = 250.0 / k_mm, 2000.0 / k_mm
        boxes = [b for b in boxes if lo <= max(float(np.ptp(b[:, 0])), float(np.ptp(b[:, 1]))) <= hi]
    # 한 교차부에 여러 개 → 큰 것 하나
    boxes.sort(key=lambda b: -float(np.ptp(b[:, 0]) * np.ptp(b[:, 1])))
    keep = []
    for b in boxes:
        cx, cy = float(b[:, 0].mean()), float(b[:, 1].mean())
        r = max(float(np.ptp(b[:, 0])), float(np.ptp(b[:, 1])), (600.0 / k_mm) if k_mm else 6.0)
        if any(math.hypot(cx - q[0], cy - q[1]) < r for q in keep):
            continue
        keep.append((cx, cy, b))
    boxes = [q[2] for q in keep]
    log(f"  기둥(교차점의 네모) {len(boxes)}개 · 교차점 {len(nodes)}개")
    return boxes


# =============================================================================
#  4. 사진 전용 부재 만들기 (평행선 쌍 = 보·벽 띠, 사각형 = 기둥, 글자 = 부재명)
# =============================================================================
import re as _re

_LABEL_RE = _re.compile(r"^(?P<pre>[A-Z]{1,3})(?P<num>\d{1,3})[A-Z]?(?:-\d{1,2})?$")
_SIZE_RE = _re.compile(r"(\d{3,4})\s*[xX×*]\s*(\d{3,4})")
_PRE_KIND = {"G": "girder", "TG": "girder", "WG": "girder", "FG": "girder", "B": "beam", "SB": "beam", "TB": "beam",
             "CB": "beam", "LB": "beam", "C": "column", "TC": "column", "W": "wall", "CW": "wall", "RW": "wall"}


def _fix_ocr(t):
    t = t.strip().upper().replace(" ", "")
    t = t.replace("O", "0") if _re.match(r"^[A-Z]{1,3}[O0-9]+$", t) and t[0] != "O" else t
    # 흔한 오인식: S1 ↔ 51, G1 ↔ 61, B1 ↔ 81
    if _re.match(r"^[568]\d{1,2}$", t):
        return None
    return t


def parse_labels(texts):
    """OCR 글자 → [(kind, name, cx, cy, ang, hh, w, d)] (슬래브 S·계단 등은 버림)."""
    out = []
    for text, cx, cy, ang, hh, score in texts:
        if score < 0.5:
            continue
        t = _fix_ocr(text)
        if not t:
            continue
        sz = _SIZE_RE.search(t)
        w = d = None
        if sz:
            w, d = int(sz.group(1)), int(sz.group(2))
            t = _SIZE_RE.sub("", t).strip("()[]:-_ ")
        m = _LABEL_RE.match(t)
        if not m:
            continue
        kind = _PRE_KIND.get(m.group("pre")) or _PRE_KIND.get(m.group("pre")[-1:])
        if not kind:
            continue
        out.append((kind, t, cx, cy, ang, hh, w, d))
    return out


def _bands(lines, k_mm, wmin=120.0, wmax=1300.0, ang_tol=2.0, keep_single=False, single_w_mm=400.0):
    """평행선 쌍 → 띠 [(x1,y1,x2,y2, width_px, uses_middle)] — 가운데 선(그리드·중심선)이 있으면 바깥 두 선을 씀."""
    L = []
    for x1, y1, x2, y2, cov in lines:
        ln = math.hypot(x2 - x1, y2 - y1)
        if ln * k_mm < 400:
            continue
        a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        L.append([x1, y1, x2, y2, a, ln, False])
    L.sort(key=lambda s: -s[5])
    out = []
    lo, hi = wmin / k_mm, wmax / k_mm
    for i, s in enumerate(L):
        if s[6]:
            continue
        ux, uy = (s[2] - s[0]) / s[5], (s[3] - s[1]) / s[5]
        nx, ny = -uy, ux
        o0 = s[0] * nx + s[1] * ny
        p0a, p0b = sorted((s[0] * ux + s[1] * uy, s[2] * ux + s[3] * uy))
        cands = []
        for j, t in enumerate(L):
            if j == i or t[6]:
                continue
            da = abs(t[4] - s[4])
            if min(da, 180 - da) > ang_tol:
                continue
            o = ((t[0] + t[2]) / 2) * nx + ((t[1] + t[3]) / 2) * ny - o0
            if not (lo <= abs(o) <= hi):
                continue
            pa, pb = sorted((t[0] * ux + t[1] * uy, t[2] * ux + t[3] * uy))
            ov = min(p0b, pb) - max(p0a, pa)
            if ov < 0.5 * min(p0b - p0a, pb - pa) or ov * k_mm < 400:
                continue
            cands.append((abs(o), o, j, max(p0a, pa), min(p0b, pb)))
        if not cands:
            if keep_single and s[5] * k_mm >= 400:          # 짝 없는 선 = 한 줄로 그린 보(해상도가 낮아 두 줄이 붙음)
                s[6] = True
                out.append((s[0], s[1], s[2], s[3], single_w_mm / k_mm))
            continue
        cands.sort()
        best = cands[0]
        # 가운데 선이면(2배 거리에 같은 쪽 선이 또 있음) 바깥 선과 짝
        for c in cands[1:]:
            if (c[1] > 0) == (best[1] > 0) and abs(c[0] - 2 * best[0]) <= 0.2 * best[0] + 2:
                L[best[2]][6] = True            # 가운데 선 소비
                best = c
                break
        s[6] = True
        L[best[2]][6] = True
        o_mid = o0 + best[1] / 2
        a, b = best[3], best[4]
        out.append((a * ux + o_mid * nx, a * uy + o_mid * ny, b * ux + o_mid * nx, b * uy + o_mid * ny, best[0]))
    return out


def build_result(flat, k_mm, lines, col_boxes, texts, log=print):
    """사진에서 찾은 것들 → AnalysisResult (mm, y 위쪽)."""
    from .model import AnalysisResult, Member, SRC_LABEL, SRC_DEFAULT
    from .topology import build_topology
    H, W = flat.shape[:2]

    def P(x, y):
        return (x * k_mm, (H - y) * k_mm)

    res = AnalysisResult(extents=(0.0, 0.0, W * k_mm, H * k_mm), kind="photo")
    labels = parse_labels(texts)
    mid = 0
    members = []
    # ---- 띠 → 축선(같은 직선 위 띠 합침) → 교차점에서 경간 나눔 → 보/벽
    bands = _spans(_dedupe_axes(_axes(_bands(lines, k_mm, keep_single=True), k_mm), k_mm), k_mm)
    for x1, y1, x2, y2, wpx in bands:
        a, b = P(x1, y1), P(x2, y2)
        Lmm = math.hypot(b[0] - a[0], b[1] - a[1])
        width = wpx * k_mm
        mid += 1
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
        m = Member(mid, "wall" if width < 260 else "beam", p1=a, p2=b, c1=a, c2=b, length_cc=Lmm,
                   length_clear=Lmm, width=round(width / 10) * 10, angle=ang, layer="사진", auto=True)
        members.append(m)
    # ---- 기둥
    for box in col_boxes:
        pts = [P(float(x), float(y)) for x, y in box]
        cx = sum(p[0] for p in pts) / 4
        cy = sum(p[1] for p in pts) / 4
        e1 = math.dist(pts[0], pts[1]); e2 = math.dist(pts[1], pts[2])
        bb, hh = max(e1, e2), min(e1, e2)
        mid += 1
        members.append(Member(mid, "column", center=(cx, cy), b=round(bb / 10) * 10, h=round(hh / 10) * 10,
                              shape="rect", polygon=pts, layer="사진", auto=True))
    # ---- 부재명: 가까운(그리고 방향이 맞는) 부재에 붙임
    named = 0
    for kind, name, tx, ty, tang, thh, w, d in labels:
        x, y = P(tx, ty)
        best = None
        for m in members:
            if kind == "column":
                if m.kind != "column":
                    continue
                dist = math.hypot(x - m.center[0], y - m.center[1]) - max(m.b, 300) * 0.5
                lim = 1500.0 + thh * k_mm * 3
            else:
                if m.kind == "column":
                    continue
                da = abs((tang % 180) - m.angle)
                if min(da, 180 - da) > 25:
                    continue
                vx, vy = m.p2[0] - m.p1[0], m.p2[1] - m.p1[1]
                L2 = vx * vx + vy * vy or 1
                t = max(0, min(1, ((x - m.p1[0]) * vx + (y - m.p1[1]) * vy) / L2))
                dist = math.hypot(x - (m.p1[0] + t * vx), y - (m.p1[1] + t * vy)) - m.width / 2
                lim = 1200.0 + thh * k_mm * 2
            if dist <= lim and (best is None or dist < best[0]):
                best = (dist, m)
        if best is None:
            # 기둥 표기인데 사각형이 없으면 가장 가까운 띠 교차점에 기둥 만들기
            if kind == "column":
                pt = _nearest_crossing(members, x, y, 2500.0)
                if pt:
                    mid += 1
                    s = 500.0
                    c = Member(mid, "column", center=pt, b=s, h=s, shape="rect",
                               polygon=[(pt[0] - s / 2, pt[1] - s / 2), (pt[0] + s / 2, pt[1] - s / 2),
                                        (pt[0] + s / 2, pt[1] + s / 2), (pt[0] - s / 2, pt[1] + s / 2)],
                               layer="사진", auto=True, name=name, name_source=SRC_LABEL,
                               notes=["사진의 기둥 표기 위치(보 교차점)에 만든 기둥 — 크기 확인 필요"])
                    members.append(c)
                    named += 1
            continue
        m = best[1]
        if m.name and m.name != name:
            m.notes.append(f"표기 충돌: {m.name} / {name}")
            continue
        m.name, m.name_source = name, SRC_LABEL
        m.labels = [name]
        if kind in ("girder", "beam", "wall") and m.kind != "column":
            m.kind = kind
        if d:
            m.depth = float(d)
        named += 1
    for m in members:
        if not m.name:
            m.name_source = SRC_DEFAULT
        m.notes.append("사진 인식 — 위치·크기 확인 필요")
    res.members = members
    res.background = [Segment(*P(x1, y1), *P(x2, y2), "사진") for x1, y1, x2, y2, _c in lines]
    from collections import Counter as _C
    cnt = _C(m.kind for m in members)
    log(f"사진 인식 결과: 기둥 {cnt['column']} · 거더 {cnt['girder']} · 보 {cnt['beam']} · 벽 {cnt['wall']} "
        f"(부재명 {named}개 읽음, 표기 {len(labels)}개)")
    return res


def _axes(bands, k_mm, ang_tol=2.5, gap_mm=2500.0):
    """같은 직선 위의 띠들을 하나의 축선으로 (교차부에서 끊긴 보 이어 붙이기)."""
    items = sorted(bands, key=lambda b: -math.hypot(b[2] - b[0], b[3] - b[1]))
    used = [False] * len(items)
    out = []
    for i, (x1, y1, x2, y2, w) in enumerate(items):
        if used[i]:
            continue
        L = math.hypot(x2 - x1, y2 - y1)
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        nx, ny = -uy, ux
        o = x1 * nx + y1 * ny
        a = math.degrees(math.atan2(uy, ux)) % 180
        iv, ws = [], []
        for j in range(i, len(items)):
            if used[j]:
                continue
            bx1, by1, bx2, by2, bw = items[j]
            ba = math.degrees(math.atan2(by2 - by1, bx2 - bx1)) % 180
            da = abs(ba - a)
            if min(da, 180 - da) > ang_tol:
                continue
            tol = max(0.6 * max(w, bw), 150.0 / k_mm)
            if abs(bx1 * nx + by1 * ny - o) > tol or abs(bx2 * nx + by2 * ny - o) > tol:
                continue
            if abs(bw - w) > 0.45 * max(bw, w):
                continue
            p, q = sorted((bx1 * ux + by1 * uy, bx2 * ux + by2 * uy))
            iv.append((p, q))
            ws.append(bw)
            used[j] = True
        iv.sort()
        cur = list(iv[0])
        for p, q in iv[1:]:
            if p <= cur[1] + gap_mm / k_mm:
                cur[1] = max(cur[1], q)
            else:
                out.append((cur[0] * ux + o * nx, cur[0] * uy + o * ny, cur[1] * ux + o * nx, cur[1] * uy + o * ny,
                            sorted(ws)[len(ws) // 2]))
                cur = [p, q]
        out.append((cur[0] * ux + o * nx, cur[0] * uy + o * ny, cur[1] * ux + o * nx, cur[1] * uy + o * ny,
                    sorted(ws)[len(ws) // 2]))
    return out


def _dedupe_axes(axes, k_mm):
    """나란히 겹친 축선(같은 보를 두 번 잡음) → 긴 것 하나."""
    axes = sorted(axes, key=lambda a: -math.hypot(a[2] - a[0], a[3] - a[1]))
    keep = []
    for a in axes:
        x1, y1, x2, y2, w = a
        L = math.hypot(x2 - x1, y2 - y1)
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        dup = False
        for b in keep:
            bx1, by1, bx2, by2, bw = b
            BL = math.hypot(bx2 - bx1, by2 - by1)
            vx, vy = (bx2 - bx1) / BL, (by2 - by1) / BL
            if abs(ux * vy - uy * vx) > 0.05:
                continue
            nx, ny = -vy, vx
            off = abs(((x1 + x2) / 2 - bx1) * nx + ((y1 + y2) / 2 - by1) * ny)
            if off > 0.75 * max(w, bw) + 2:
                continue
            p1, p2 = sorted(((x1 - bx1) * vx + (y1 - by1) * vy, (x2 - bx1) * vx + (y2 - by1) * vy))
            ov = min(p2, BL) - max(p1, 0)
            if ov > 0.5 * L:
                dup = True
                break
        if not dup:
            keep.append(a)
    return keep


def _spans(axes, k_mm, min_mm=600.0):
    """축선을 다른 축선과의 교차점에서 나눔 (경간 단위 보)."""
    out = []
    for i, (x1, y1, x2, y2, w) in enumerate(axes):
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        ts = [0.0, 1.0]
        for j, (a1, b1, a2, b2, w2) in enumerate(axes):
            if i == j:
                continue
            ex, ey = a2 - a1, b2 - b1
            den = dx * ey - dy * ex
            if abs(den) < 0.5 * L * math.hypot(ex, ey):     # 30° 이하로 비스듬하면 무시
                continue
            t = ((a1 - x1) * ey - (b1 - y1) * ex) / den
            u = ((a1 - x1) * dy - (b1 - y1) * dx) / den
            ext = (w2 / 2 + 3) / max(math.hypot(ex, ey), 1e-6)
            if 0.0 < t < 1.0 and -ext <= u <= 1 + ext:
                ts.append(t)
        ts.sort()
        for a, b in zip(ts, ts[1:]):
            if (b - a) * L * k_mm >= min_mm:
                out.append((x1 + dx * a, y1 + dy * a, x1 + dx * b, y1 + dy * b, w))
    return out


def _nearest_crossing(members, x, y, lim):
    lins = [m for m in members if m.kind != "column" and m.p1 and m.p2]
    best = None
    for i, a in enumerate(lins):
        if math.hypot(x - (a.p1[0] + a.p2[0]) / 2, y - (a.p1[1] + a.p2[1]) / 2) > a.length_cc / 2 + lim:
            continue
        for b in lins[i + 1:]:
            d1x, d1y = a.p2[0] - a.p1[0], a.p2[1] - a.p1[1]
            d2x, d2y = b.p2[0] - b.p1[0], b.p2[1] - b.p1[1]
            den = d1x * d2y - d1y * d2x
            if abs(den) < 1e-9 * (a.length_cc * b.length_cc + 1):
                continue
            t = ((b.p1[0] - a.p1[0]) * d2y - (b.p1[1] - a.p1[1]) * d2x) / den
            u = ((b.p1[0] - a.p1[0]) * d1y - (b.p1[1] - a.p1[1]) * d1x) / den
            if -0.1 <= t <= 1.1 and -0.1 <= u <= 1.1:
                px, py = a.p1[0] + d1x * t, a.p1[1] + d1y * t
                dd = math.hypot(px - x, py - y)
                if dd <= lim and (best is None or dd < best[0]):
                    best = (dd, (px, py))
    return best[1] if best else None


def recognize_photo(path, corners=None, k_mm=None, paper="A3", scale=200, use_ocr=True, log=print, auto_region=False):
    """사진 → (펴진 이미지, AnalysisResult). vectorize 의 선·사각형 + 글자로 부재를 바로 만든다."""
    img = read_image(path)
    log(f"사진 {img.shape[1]}×{img.shape[0]}px")
    corners = corners or detect_corners(img)
    flat = warp(img, corners)
    h, w = flat.shape[:2]
    if not k_mm:
        k_mm = mm_per_px(w, paper, scale, w >= h)
    log(f"원근 보정 → {w}×{h}px · 1px = {k_mm:.1f}mm")
    texts = ocr_texts(flat, log=log) if use_ocr and ocr_available() else []
    if use_ocr and not ocr_available():
        log(ocr_missing_text())
    _lines_h, rect_boxes = _shapes(flat, k_mm, texts, log)         # 외곽선 사각형(기둥) 후보
    pieces, _mask, ink = morph_lines(flat, (), log)                # 방향 열림이 글자를 걸러내므로 글자 지우기 안 함
    merged = _merge_lines([p[:4] for p in pieces], ang_tol=2.0, off_tol=2.5, gap=10.0)
    if auto_region:
        box = structure_box(merged, w, h)
        n0 = len(merged)
        merged = clip_to_box(merged, box)
        rect_boxes = [b for b in rect_boxes if box[0] <= float(b[:, 0].mean()) <= box[2] and
                      box[1] <= float(b[:, 1].mean()) <= box[3]]
        texts = [t for t in texts if box[0] <= t[1] <= box[2] and box[1] <= t[2] <= box[3]]
        log(f"  골조 영역만 사용 ({box[0]:.0f},{box[1]:.0f})-({box[2]:.0f},{box[3]:.0f}): 선 {n0} → {len(merged)}개")
    col_boxes = columns_at_nodes(ink, merged, rect_boxes, log, k_mm=k_mm)
    res = build_result(flat, k_mm, merged, col_boxes, texts, log)
    return flat, res, k_mm, texts
