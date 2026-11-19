"""
information/maps.py — KDS 지도(기본풍속·지상설하중·국가지진위험지도)를 좌표 격자로 바꿔 두고 조회

만드는 법 (map_tool.py 화면)
  1) KDS PDF 의 지도 쪽(또는 캡처 이미지)을 연다
  2) 지도 위 도시 표시 3곳 이상을 클릭해 위경도와 맞춘다 (affine / 6점 이상이면 2차식)
  3) 등풍속선·구역 안을 클릭해 값을 준다 — 같은 색으로 이어진 영역이 채워진다
     · 선이 끊겨 넘치면 '경계선'을 그려 막는다
     · 선 위·글자 위 픽셀은 이웃 구역 중 큰 값(안전측)으로 채운다
  4) 저장 → ~/.strcad/info_maps/<kind>.json  (위경도 격자)
"""
import base64
import json
import math
import time
import zlib
from pathlib import Path

from . import geo

MAP_DIR = geo.APP_DIR / "info_maps"
PKG_DIR = Path(__file__).parent / "data"          # 배포용 기본 지도 (있으면)

KINDS = {
    "wind":    {"title": "기본풍속 V0 (그림 5.5-1, 재현기간 500년)", "unit": "m/s",
                "caption": "그림 5.5-1", "code": "KDS 41 12 00:2022", "rule": "등풍속선 사이는 인근 등풍속선 중 큰 값"},
    "snow":    {"title": "기본지상설하중 Sg (그림 4.2-1)", "unit": "kN/㎡",
                "caption": "그림 4.2-1", "code": "KDS 41 12 00:2022", "rule": "구역 값"},
    "seismic": {"title": "국가지진위험지도 S (그림 3.2-1, 2400년)", "unit": "%g",
                "caption": "그림 3.2-1", "code": "KDS 41 17 00:2022", "rule": "등고선 사이는 큰 값(안전측)"},
}

GRID_RES = 0.01                                     # 도 (약 1km)
KOREA_BBOX = (124.0, 33.0, 131.2, 38.8)             # lon_min, lat_min, lon_max, lat_max

KNOWN_CITIES = [
    ("서울", 37.5665, 126.9780), ("인천", 37.4563, 126.7052), ("수원", 37.2636, 127.0286),
    ("춘천", 37.8813, 127.7298), ("원주", 37.3422, 127.9202), ("강릉", 37.7519, 128.8761),
    ("속초", 38.2070, 128.5918), ("대관령", 37.6771, 128.7183), ("울진", 36.9930, 129.4004),
    ("청주", 36.6424, 127.4890), ("천안", 36.8151, 127.1139), ("서산", 36.7848, 126.4503),
    ("대전", 36.3504, 127.3845), ("추풍령", 36.2205, 127.9945), ("안동", 36.5684, 128.7294),
    ("포항", 36.0190, 129.3435), ("영덕", 36.4150, 129.3653), ("대구", 35.8714, 128.6014),
    ("전주", 35.8242, 127.1480), ("군산", 35.9676, 126.7366), ("광주", 35.1595, 126.8526),
    ("목포", 34.8118, 126.3922), ("해남", 34.5734, 126.5990), ("완도", 34.3110, 126.7550),
    ("순천", 34.9507, 127.4872), ("여수", 34.7604, 127.6622), ("진주", 35.1800, 128.1076),
    ("통영", 34.8544, 128.4331), ("거제", 34.8806, 128.6211), ("창원", 35.2280, 128.6811),
    ("울산", 35.5384, 129.3114), ("부산", 35.1796, 129.0756), ("제주", 33.4996, 126.5312),
    ("서귀포", 33.2541, 126.5600), ("울릉", 37.4844, 130.9058),
]


# ─────────────────────────────────────────────────────────────
#  좌표 맞춤 (경위도 ↔ 픽셀)
# ─────────────────────────────────────────────────────────────
def _lstsq(rows, rhs):
    """정규방정식 최소제곱 (작은 행렬용, numpy 없이도 동작)."""
    n = len(rows[0])
    A = [[sum(r[i] * r[j] for r in rows) for j in range(n)] for i in range(n)]
    b = [sum(r[i] * v for r, v in zip(rows, rhs)) for i in range(n)]
    for c in range(n):                               # 가우스 소거
        p = max(range(c, n), key=lambda i: abs(A[i][c]))
        if abs(A[p][c]) < 1e-15:
            raise ValueError("기준점 배치가 한 줄에 몰려 있습니다")
        A[c], A[p] = A[p], A[c]
        b[c], b[p] = b[p], b[c]
        for i in range(c + 1, n):
            f = A[i][c] / A[c][c]
            for j in range(c, n):
                A[i][j] -= f * A[c][j]
            b[i] -= f * b[c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (b[i] - sum(A[i][j] * x[j] for j in range(i + 1, n))) / A[i][i]
    return x


def _terms(lon, lat, order):
    u, v = lon - 127.5, lat - 36.0
    if order == 2:
        return [1.0, u, v, u * u, u * v, v * v]
    return [1.0, u, v]


class Georef:
    """경위도 → 이미지 픽셀 변환 (기준점 최소제곱)."""

    def __init__(self, points):
        """points: [(px, py, lat, lon), ...]"""
        if len(points) < 3:
            raise ValueError("기준점이 3개 이상 필요합니다")
        self.points = list(points)
        self.order = 2 if len(points) >= 6 else 1
        rows = [_terms(p[3], p[2], self.order) for p in points]
        self.cx = _lstsq(rows, [p[0] for p in points])
        self.cy = _lstsq(rows, [p[1] for p in points])
        # 역변환(픽셀→경위도)은 1차식으로
        rows2 = [[1.0, p[0], p[1]] for p in points]
        self.ilon = _lstsq(rows2, [p[3] for p in points])
        self.ilat = _lstsq(rows2, [p[2] for p in points])

    def to_px(self, lat, lon):
        t = _terms(lon, lat, self.order)
        return (sum(a * b for a, b in zip(self.cx, t)), sum(a * b for a, b in zip(self.cy, t)))

    def to_ll(self, px, py):
        lat = self.ilat[0] + self.ilat[1] * px + self.ilat[2] * py
        lon = self.ilon[0] + self.ilon[1] * px + self.ilon[2] * py
        for _ in range(8):                           # 정변환으로 보정
            x, y = self.to_px(lat, lon)
            dx, dy = px - x, py - y
            if abs(dx) + abs(dy) < 0.05:
                break
            lat += self.ilat[1] * dx + self.ilat[2] * dy
            lon += self.ilon[1] * dx + self.ilon[2] * dy
        return lat, lon

    def residuals(self):
        out = []
        for px, py, la, lo in self.points:
            x, y = self.to_px(la, lo)
            out.append(math.hypot(x - px, y - py))
        return out

    def km_per_px(self):
        la, lo = 36.0, 127.5
        x0, y0 = self.to_px(la, lo)
        x1, y1 = self.to_px(la + 0.5, lo)
        return 55.6 / max(math.hypot(x1 - x0, y1 - y0), 1e-9)

    def to_json(self):
        return {"points": self.points}


# ─────────────────────────────────────────────────────────────
#  이미지 → 구역 라벨
# ─────────────────────────────────────────────────────────────
def build_labels(img, seeds, barriers=(), tol=40, fill_gap=12):
    """
    img      : PIL.Image (RGB)
    seeds    : [(px, py, value)]
    barriers : [[(x, y), ...], ...] 사용자가 그린 경계선 (픽셀)
    반환     : (labels ndarray[h,w] int16 — 0 없음, k = values[k-1]),  values 목록,  막힌 seed 목록
    """
    import numpy as np
    from PIL import Image, ImageDraw

    work = img.convert("RGB").copy()
    dr = ImageDraw.Draw(work)
    for line in barriers:
        if len(line) >= 2:
            dr.line([tuple(p) for p in line], fill=(0, 0, 0), width=3)
    base = np.asarray(work).copy()
    h, w = base.shape[:2]
    labels = np.zeros((h, w), dtype=np.int16)
    values = []
    sentinel = (1, 254, 3)
    leaks = []
    for px, py, val in seeds:
        x, y = int(round(px)), int(round(py))
        if not (0 <= x < w and 0 <= y < h):
            continue
        if labels[y, x]:
            # 이미 다른 seed 영역 — 값이 다르면 큰 값으로
            k = labels[y, x]
            if val > values[k - 1]:
                values[k - 1] = val
            continue
        im = Image.fromarray(base)
        ImageDraw.floodfill(im, (x, y), sentinel, thresh=tol)
        arr = np.asarray(im)
        mask = (arr[:, :, 0] == sentinel[0]) & (arr[:, :, 1] == sentinel[1]) & (arr[:, :, 2] == sentinel[2])
        mask &= labels == 0
        if mask.sum() > 0.6 * h * w:
            leaks.append((px, py, val))
        values.append(float(val))
        labels[mask] = len(values)
    # 선·글자 픽셀: 이웃 중 큰 값으로 확장 (fill_gap 회)
    if values and fill_gap:
        vals = np.array([0.0] + values)
        for _ in range(int(fill_gap)):
            empty = labels == 0
            if not empty.any():
                break
            best = labels.copy()
            bestv = vals[labels]
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                sh = np.roll(np.roll(labels, dy, axis=0), dx, axis=1)
                shv = vals[sh]
                take = empty & (sh > 0) & (shv > bestv)
                best[take] = sh[take]
                bestv = np.where(take, shv, bestv)
            labels = best
    return labels, values, leaks


def labels_to_grid(labels, values, georef, bbox=KOREA_BBOX, res=GRID_RES):
    """라벨 이미지 → 위경도 격자 (uint8 인덱스)."""
    import numpy as np
    lon0, lat0, lon1, lat1 = bbox
    nx = int(round((lon1 - lon0) / res)) + 1
    ny = int(round((lat1 - lat0) / res)) + 1
    lons = lon0 + np.arange(nx) * res
    lats = lat0 + np.arange(ny) * res
    LON, LAT = np.meshgrid(lons, lats)
    t = [np.ones_like(LON)]
    u, v = LON - 127.5, LAT - 36.0
    t += [u, v] if georef.order == 1 else [u, v, u * u, u * v, v * v]
    PX = sum(c * a for c, a in zip(georef.cx, t))
    PY = sum(c * a for c, a in zip(georef.cy, t))
    h, w = labels.shape
    xi = np.clip(np.round(PX).astype(int), 0, w - 1)
    yi = np.clip(np.round(PY).astype(int), 0, h - 1)
    inside = (PX >= 0) & (PX < w) & (PY >= 0) & (PY < h)
    g = np.where(inside, labels[yi, xi], 0).astype(np.uint8)
    uniq = sorted(set(values))
    remap = np.zeros(len(values) + 1, dtype=np.uint8)
    for k, val in enumerate(values, start=1):
        remap[k] = uniq.index(val) + 1
    return remap[g], uniq, (nx, ny)


# ─────────────────────────────────────────────────────────────
#  저장·조회
# ─────────────────────────────────────────────────────────────
def save_grid(kind, grid, values, size, calib, bbox=KOREA_BBOX, res=GRID_RES):
    MAP_DIR.mkdir(parents=True, exist_ok=True)
    nx, ny = size
    data = base64.b64encode(zlib.compress(bytes(grid.astype("uint8").ravel()), 9)).decode("ascii")
    js = {"kind": kind, "unit": KINDS[kind]["unit"], "bbox": list(bbox), "res": res, "nx": nx, "ny": ny,
          "values": values, "data": data, "calib": calib, "created": time.strftime("%Y-%m-%d %H:%M"),
          "code": KINDS[kind]["code"]}
    p = MAP_DIR / f"{kind}.json"
    p.write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")
    _CACHE.pop(kind, None)
    return p


_CACHE = {}


def load_grid(kind):
    if kind in _CACHE:
        return _CACHE[kind]
    for p in (MAP_DIR / f"{kind}.json", PKG_DIR / f"{kind}.json"):
        if p.exists():
            try:
                js = json.loads(p.read_text(encoding="utf-8"))
                js["_grid"] = zlib.decompress(base64.b64decode(js["data"]))
                js["_path"] = str(p)
                _CACHE[kind] = js
                return js
            except Exception:                        # noqa: BLE001
                continue
    _CACHE[kind] = None
    return None


def has_map(kind):
    return load_grid(kind) is not None


def lookup(kind, lat, lon, search=3):
    """
    위경도 → 지도 값.  반환 (값 | None, 설명)
    격자 칸이 비어 있으면 주변 search 칸 안의 값 중 큰 값.
    """
    js = load_grid(kind)
    if js is None:
        return None, "지도 데이터 없음 — '지도 보정'에서 만드세요"
    lon0, lat0 = js["bbox"][0], js["bbox"][1]
    res, nx, ny = js["res"], js["nx"], js["ny"]
    ix = int(round((lon - lon0) / res))
    iy = int(round((lat - lat0) / res))
    g = js["_grid"]
    vals = js["values"]

    def at(i, j):
        if 0 <= i < nx and 0 <= j < ny:
            k = g[j * nx + i]
            return vals[k - 1] if k else None
        return None

    v = at(ix, iy)
    if v is not None:
        near = [w for w in (at(i, j) for i in (ix - 1, ix, ix + 1) for j in (iy - 1, iy, iy + 1)) if w is not None]
        if max(near) > v:
            return max(near), f"구역 경계부(±{res * 111:.0f}km) — 큰 값 {max(near):g} 적용 (해당 칸 {v:g})"
        return v, "지도 격자"
    best = None
    for r in range(1, search + 1):
        for i in range(ix - r, ix + r + 1):
            for j in range(iy - r, iy + r + 1):
                w = at(i, j)
                if w is not None and (best is None or w > best):
                    best = w
        if best is not None:
            return best, f"주변 {r}칸 중 큰 값"
    return None, "지도 범위 밖 (바다 또는 미지정 구역)"


def map_info(kind):
    js = load_grid(kind)
    if not js:
        return None
    return {"created": js.get("created", ""), "values": js.get("values", []), "path": js.get("_path", ""),
            "points": len((js.get("calib") or {}).get("points", [])),
            "seeds": len((js.get("calib") or {}).get("seeds", []))}
