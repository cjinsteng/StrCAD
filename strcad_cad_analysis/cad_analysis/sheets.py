"""도면 없이 현장조사 — 빈 도면(격자) · 사진/이미지 도면 만들기, 축척 맞추기, 배경 이미지 그리기.

좌표 단위는 mm, y 위쪽(+). 이미지 픽셀 (u, v)[v 아래쪽] → 도면 (x0 + u·k, y1 − v·k).
배경 이미지는 ~/.strcad/sheets/<uid>.jpg 로 복사해 두고 분석 결과(res.bg_image)에 경로를 기록한다.
"""
from __future__ import annotations

import os
import uuid

from .model import AnalysisResult, Segment

SHEET_DIR = os.path.join(os.path.expanduser("~"), ".strcad", "sheets")
MAX_SIDE = 4000            # 저장할 배경 이미지 최대 변 (px)


def new_uid() -> str:
    return "sh_" + uuid.uuid4().hex[:16]


def grid_lines(w, h, layer="blank"):
    """빈 도면용 연한 격자 (1 m, 넓으면 5 m) + 테두리."""
    step = 1000.0 if max(w, h) <= 60000 else 5000.0
    out = []
    x = 0.0
    while x <= w + 1:
        out.append(Segment(x, 0.0, x, h, layer))
        x += step
    y = 0.0
    while y <= h + 1:
        out.append(Segment(0.0, y, w, y, layer))
        y += step
    return out


def new_blank(width_m=30.0, height_m=20.0) -> AnalysisResult:
    w, h = float(width_m) * 1000, float(height_m) * 1000
    res = AnalysisResult(extents=(0.0, 0.0, w, h), source_file="", kind="blank")
    res.background = grid_lines(w, h)
    res.sheet_uid = new_uid()
    return res


def _pil():
    try:
        from PIL import Image, ImageOps
        return Image, ImageOps
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("사진 도면에는 Pillow 패키지가 필요합니다 (pip install pillow).") from e


def store_image(src, uid=None, img=None) -> tuple[str, int, int]:
    """이미지를 SHEET_DIR 로 JPEG 저장 (EXIF 회전 반영, 너무 크면 줄임). → (경로, 폭px, 높이px)"""
    Image, ImageOps = _pil()
    os.makedirs(SHEET_DIR, exist_ok=True)
    if img is None:
        img = Image.open(src)
        img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    k = min(1.0, MAX_SIDE / max(img.size))
    if k < 1.0:
        img = img.resize((round(img.size[0] * k), round(img.size[1] * k)), Image.LANCZOS)
    path = os.path.join(SHEET_DIR, f"{uid or new_uid()}.jpg")
    img.save(path, "JPEG", quality=88)
    return path, img.size[0], img.size[1]


def new_image(src, width_m=None, mm_per_px=None, img=None, kind="photo") -> AnalysisResult:
    """사진·스캔 도면을 배경으로 하는 조사 도면. width_m: 이미지 가로 실제 길이(m)."""
    uid = new_uid()
    if img is None:
        Image, ImageOps = _pil()
        img = ImageOps.exif_transpose(Image.open(src))
    iw, ih = img.size                       # 축척(mm/px)은 원래 크기 기준 — 저장본은 줄어들 수 있음
    path, _w, _h = store_image(src, uid, img=img)
    if mm_per_px:
        k = float(mm_per_px)
    else:
        k = float(width_m or 40.0) * 1000 / iw
    w, h = iw * k, ih * k
    res = AnalysisResult(extents=(0.0, 0.0, w, h), source_file=src or "", kind=kind)
    res.bg_image = path
    res.bg_rect = (0.0, 0.0, w, h)
    res.sheet_uid = uid
    return res


def rescale(res, f: float, ox=0.0, oy=0.0):
    """축척 맞추기: (ox, oy) 기준으로 모든 좌표 × f (배경·격자·검측위치·스케치·부재)."""
    def P(x, y):
        return ox + (x - ox) * f, oy + (y - oy) * f
    x0, y0, x1, y1 = res.extents
    res.extents = (*P(x0, y0), *P(x1, y1))
    if res.bg_rect:
        a, b, c, d = res.bg_rect
        res.bg_rect = (*P(a, b), *P(c, d))
    for lst in (res.background, res.grid):
        for s in lst:
            s.x1, s.y1 = P(s.x1, s.y1)
            s.x2, s.y2 = P(s.x2, s.y2)
    for r in res.surveys:
        if r.get("x") is not None and r.get("y") is not None:
            r["x"], r["y"] = P(r["x"], r["y"])
        for k in ("bx", "by", "dx", "dy"):
            if isinstance(r.get(k), (int, float)):
                r[k] = r[k] * f
        if r.get("area") and len(r["area"]) == 4:
            a = r["area"]
            r["area"] = [*P(a[0], a[1]), *P(a[2], a[3])]
    for sk in getattr(res, "sketches", []):
        p = sk.get("pts") or []
        q = []
        for i in range(0, len(p) - 1, 2):
            q += list(P(p[i], p[i + 1]))
        sk["pts"] = [round(v) for v in q]
    for n in res.nodes.values():
        n.x, n.y = P(n.x, n.y)
    for m in res.members:
        for k in ("p1", "p2", "c1", "c2", "center"):
            v = getattr(m, k, None)
            if v:
                setattr(m, k, P(*v))
        if m.polygon:
            m.polygon = [P(*q) for q in m.polygon]
        for k in ("b", "h", "width", "length_cc", "length_clear"):
            v = getattr(m, k, None)
            if isinstance(v, (int, float)) and v:
                setattr(m, k, v * f)


class BgImage:
    """캔버스에 배경 이미지 그리기 (보이는 부분만 잘라서 확대/축소, 결과 캐시)."""

    def __init__(self):
        self.path = None
        self.img = None
        self.key = None
        self.photo = None

    def draw(self, cv, res, w2s, view_box, W, H):
        path = getattr(res, "bg_image", "") if res else ""
        if not path or not res.bg_rect:
            return
        try:
            Image, _ = _pil()
            from PIL import ImageTk
        except (RuntimeError, ImportError):
            return
        if path != self.path:
            self.path, self.key, self.photo = path, None, None
            try:
                self.img = Image.open(path).convert("RGB")
            except OSError:
                self.img = None
        if self.img is None:
            return
        x0, y0, x1, y1 = res.bg_rect
        vx0, vy0, vx1, vy1 = view_box
        ix0, iy0, ix1, iy1 = max(x0, vx0), max(y0, vy0), min(x1, vx1), min(y1, vy1)
        if ix1 <= ix0 or iy1 <= iy0:
            return
        iw, ih = self.img.size
        kx, ky = iw / (x1 - x0), ih / (y1 - y0)
        box = (int((ix0 - x0) * kx), int((y1 - iy1) * ky), int(min(iw, (ix1 - x0) * kx + 1)),
               int(min(ih, (y1 - iy0) * ky + 1)))
        a = w2s(box[0] / kx + x0, y1 - box[1] / ky)
        b = w2s(box[2] / kx + x0, y1 - box[3] / ky)
        sw, sh = max(1, round(b[0] - a[0])), max(1, round(b[1] - a[1]))
        if sw > 4 * W + 2000 or sh > 4 * H + 2000:
            return
        key = (path, box, sw, sh)
        if key != self.key:
            crop = self.img.crop(box)
            crop = crop.resize((sw, sh), Image.BILINEAR if (sw < crop.size[0]) else Image.NEAREST
                               if sw > 3 * crop.size[0] else Image.BILINEAR)
            self.photo = ImageTk.PhotoImage(crop)
            self.key = key
        cv.create_image(a[0], a[1], image=self.photo, anchor="nw", tags=("bgimg",))
        cv.tag_lower("bgimg")
