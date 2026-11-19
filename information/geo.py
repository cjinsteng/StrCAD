"""
information/geo.py — 주소→좌표, 좌표계 변환, 표고(DEM) 조회, 설정 저장

외부 서비스 (사용자 PC 에서 인터넷 필요)
  · 브이월드 지오코더  https://api.vworld.kr/req/address   (인증키, 무료)
  · 카카오 로컬        https://dapi.kakao.com/v2/local/...  (REST 키, 무료)
  · Open-Meteo 표고    https://api.open-meteo.com/v1/elevation  (키 없음, Copernicus 90m DEM)
"""
import json
import math
import os
import urllib.parse
import urllib.request
from pathlib import Path

APP_DIR = Path(os.path.expanduser("~")) / ".strcad"
SETTINGS_FILE = APP_DIR / "information.json"
ELEV_CACHE_FILE = APP_DIR / "information_elev_cache.json"

DEFAULT_SETTINGS = {
    "vworld_key": "",
    "kakao_key": "",
    "elev_provider": "open-meteo",
    "radius_m": 500,
    "vs_corr": "imai",
    "bedrock_rule": "soft",          # soft: 연암 이상 / weathered: 풍화암 이상
    "weathered_rock_vs": 500.0,      # 풍화암을 토층으로 볼 때 N값 없을 때 Vs
    "amp_mode": "max",               # 대표 지반증폭계수: max(불리) / mean(평균)
    "terrain_up": 3000.0,
    "terrain_down": 2000.0,
    "terrain_step": 30.0,
    "terrain_dirs": 16,
    "db_path": "",
}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save_settings(s):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────
#  거리·방위
# ─────────────────────────────────────────────────────────────
R_EARTH = 6371008.8


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def offset_latlon(lat, lon, brg_deg, dist_m):
    d = dist_m / R_EARTH
    b = math.radians(brg_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def local_xy(lat0, lon0, lat, lon):
    """건설지점 기준 동·북 방향 거리 (m) — 작은 범위 근사."""
    x = math.radians(lon - lon0) * R_EARTH * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * R_EARTH
    return x, y


# ─────────────────────────────────────────────────────────────
#  좌표계 (TM ↔ 경위도)
# ─────────────────────────────────────────────────────────────
GRS80 = (6378137.0, 1 / 298.257222101)
BESSEL = (6377397.155, 1 / 299.1528128)
WGS84 = (6378137.0, 1 / 298.257223563)
TOWGS84_KOREA_BESSEL = (-115.80, 474.99, 674.11, 1.16, -2.31, -1.63, 6.43)

CRS = {
    "WGS84":  {"name": "경위도 (WGS84/GRS80)"},
    "EPSG:5186": {"name": "GRS80 중부원점 (EPSG:5186, FN 600,000)", "ell": GRS80, "lat0": 38, "lon0": 127,
                  "k0": 1.0, "fe": 200000, "fn": 600000},
    "EPSG:5185": {"name": "GRS80 서부원점 (EPSG:5185)", "ell": GRS80, "lat0": 38, "lon0": 125,
                  "k0": 1.0, "fe": 200000, "fn": 600000},
    "EPSG:5187": {"name": "GRS80 동부원점 (EPSG:5187)", "ell": GRS80, "lat0": 38, "lon0": 129,
                  "k0": 1.0, "fe": 200000, "fn": 600000},
    "EPSG:5188": {"name": "GRS80 동해원점 (EPSG:5188)", "ell": GRS80, "lat0": 38, "lon0": 131,
                  "k0": 1.0, "fe": 200000, "fn": 600000},
    "EPSG:5181": {"name": "GRS80 중부원점 (EPSG:5181, FN 500,000)", "ell": GRS80, "lat0": 38, "lon0": 127,
                  "k0": 1.0, "fe": 200000, "fn": 500000},
    "EPSG:5179": {"name": "UTM-K (EPSG:5179)", "ell": GRS80, "lat0": 38, "lon0": 127.5,
                  "k0": 0.9996, "fe": 1000000, "fn": 2000000},
    "EPSG:2097": {"name": "Bessel 중부원점 (EPSG:2097)", "ell": BESSEL, "lat0": 38, "lon0": 127,
                  "k0": 1.0, "fe": 200000, "fn": 500000, "towgs84": TOWGS84_KOREA_BESSEL},
    "EPSG:5174": {"name": "Bessel 보정 중부원점 (EPSG:5174)", "ell": BESSEL, "lat0": 38,
                  "lon0": 127.0028902777778, "k0": 1.0, "fe": 200000, "fn": 500000,
                  "towgs84": TOWGS84_KOREA_BESSEL},
}


def _meridian_arc(phi, a, f):
    e2 = f * (2 - f)
    e4, e6 = e2 * e2, e2 * e2 * e2
    return a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                - (35 * e6 / 3072) * math.sin(6 * phi))


def tm_forward(lat, lon, p):
    a, f = p["ell"]
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    phi, lam = math.radians(lat), math.radians(lon)
    lam0, phi0 = math.radians(p["lon0"]), math.radians(p["lat0"])
    N = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    T = math.tan(phi) ** 2
    C = ep2 * math.cos(phi) ** 2
    A = (lam - lam0) * math.cos(phi)
    M, M0 = _meridian_arc(phi, a, f), _meridian_arc(phi0, a, f)
    k0 = p["k0"]
    x = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5 / 120)
    y = k0 * (M - M0 + N * math.tan(phi) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
                                             + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6 / 720))
    return x + p["fe"], y + p["fn"]


def tm_inverse(x, y, p):
    a, f = p["ell"]
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0 = p["k0"]
    M0 = _meridian_arc(math.radians(p["lat0"]), a, f)
    M = M0 + (y - p["fn"]) / k0
    mu = M / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    N1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    T1 = math.tan(phi1) ** 2
    C1 = ep2 * math.cos(phi1) ** 2
    R1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    D = (x - p["fe"]) / (N1 * k0)
    phi = phi1 - (N1 * math.tan(phi1) / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * D ** 4 / 24
                                              + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep2 - 3 * C1 * C1) * D ** 6 / 720)
    lam = math.radians(p["lon0"]) + (D - (1 + 2 * T1 + C1) * D ** 3 / 6
                                     + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep2 + 24 * T1 * T1) * D ** 5 / 120) / math.cos(phi1)
    return math.degrees(phi), math.degrees(lam)


def _geo_to_ecef(lat, lon, h, ell):
    a, f = ell
    e2 = f * (2 - f)
    p, l = math.radians(lat), math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    return ((N + h) * math.cos(p) * math.cos(l), (N + h) * math.cos(p) * math.sin(l), (N * (1 - e2) + h) * math.sin(p))


def _ecef_to_geo(X, Y, Z, ell):
    a, f = ell
    e2 = f * (2 - f)
    lon = math.atan2(Y, X)
    p = math.hypot(X, Y)
    lat = math.atan2(Z, p * (1 - e2))
    for _ in range(6):
        N = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(Z + e2 * N * math.sin(lat), p)
    return math.degrees(lat), math.degrees(lon)


def _helmert(lat, lon, ell_from, ell_to, t):
    dx, dy, dz, rx, ry, rz, ds = t
    X, Y, Z = _geo_to_ecef(lat, lon, 0.0, ell_from)
    s = 1 + ds * 1e-6
    rx, ry, rz = (math.radians(v / 3600.0) for v in (rx, ry, rz))
    X2 = dx + s * (X - rz * Y + ry * Z)
    Y2 = dy + s * (rz * X + Y - rx * Z)
    Z2 = dz + s * (-ry * X + rx * Y + Z)
    return _ecef_to_geo(X2, Y2, Z2, ell_to)


def to_wgs84(x, y, crs):
    """(x, y) → (lat, lon).  WGS84 는 x=경도, y=위도."""
    if crs == "WGS84":
        return float(y), float(x)
    p = CRS[crs]
    lat, lon = tm_inverse(float(x), float(y), p)
    if p.get("towgs84"):
        lat, lon = _helmert(lat, lon, p["ell"], WGS84, p["towgs84"])
    return lat, lon


def guess_crs(xs, ys):
    """좌표 값 범위로 좌표계 추정."""
    xs = [v for v in xs if v is not None]
    ys = [v for v in ys if v is not None]
    if not xs or not ys:
        return "WGS84"
    mx, my = sorted(xs)[len(xs) // 2], sorted(ys)[len(ys) // 2]
    if 124 < mx < 132 and 33 < my < 39.5:
        return "WGS84"
    if 700000 < mx < 1400000 and 1300000 < my < 2200000:
        return "EPSG:5179"
    if 0 < mx < 500000 and 300000 < my < 800000:
        return "EPSG:5186" if my > 450000 else "EPSG:2097"
    return "EPSG:5186"


# ─────────────────────────────────────────────────────────────
#  HTTP
# ─────────────────────────────────────────────────────────────
class GeoError(Exception):
    pass


def http_json(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=dict({"User-Agent": "StrCAD-Information/1.0"}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except Exception as e:                       # noqa: BLE001
        raise GeoError(f"서버 연결 실패: {e}") from e
    for enc in ("utf-8", "cp949"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:                        # noqa: BLE001
            continue
    raise GeoError("응답을 읽지 못했습니다")


# ─────────────────────────────────────────────────────────────
#  지오코딩
# ─────────────────────────────────────────────────────────────
def geocode_vworld(address, key):
    for typ in ("road", "parcel"):
        q = urllib.parse.urlencode({
            "service": "address", "request": "getcoord", "version": "2.0", "crs": "epsg:4326",
            "address": address, "refine": "true", "simple": "false", "format": "json",
            "type": typ, "key": key})
        js = http_json("https://api.vworld.kr/req/address?" + q)
        resp = js.get("response", {})
        st = resp.get("status")
        if st == "OK":
            pt = resp["result"]["point"]
            ref = resp.get("refined", {})
            stc = ref.get("structure", {}) or {}
            return {"lat": float(pt["y"]), "lon": float(pt["x"]), "address": ref.get("text", address),
                    "sido": stc.get("level1", ""), "sigungu": stc.get("level2", ""), "provider": "브이월드"}
        if st == "ERROR":
            raise GeoError("브이월드: " + str(resp.get("error", {}).get("text", "오류")))
    return None


def geocode_kakao(address, key):
    h = {"Authorization": "KakaoAK " + key}
    for path in ("address", "keyword"):
        js = http_json(f"https://dapi.kakao.com/v2/local/search/{path}.json?" +
                       urllib.parse.urlencode({"query": address}), headers=h)
        docs = js.get("documents") or []
        if docs:
            d = docs[0]
            ad = d.get("address") or {}
            name = d.get("address_name") or ad.get("address_name") or d.get("place_name") or address
            sido = ad.get("region_1depth_name", "") if isinstance(ad, dict) else ""
            sgg = ad.get("region_2depth_name", "") if isinstance(ad, dict) else ""
            if not sido and d.get("address_name"):
                parts = d["address_name"].split()
                sido = parts[0] if parts else ""
                sgg = parts[1] if len(parts) > 1 else ""
            return {"lat": float(d["y"]), "lon": float(d["x"]), "address": name,
                    "sido": sido, "sigungu": sgg, "provider": "카카오"}
    return None


def geocode(address, settings=None):
    s = settings or load_settings()
    errs = []
    if s.get("vworld_key"):
        try:
            r = geocode_vworld(address, s["vworld_key"])
            if r:
                return r
        except GeoError as e:
            errs.append(str(e))
    if s.get("kakao_key"):
        try:
            r = geocode_kakao(address, s["kakao_key"])
            if r:
                return r
        except GeoError as e:
            errs.append(str(e))
    if not s.get("vworld_key") and not s.get("kakao_key"):
        raise GeoError("주소 검색 키가 없습니다. 설정에서 브이월드 또는 카카오 키를 입력하거나 위도·경도를 직접 입력하세요.")
    raise GeoError("주소를 찾지 못했습니다." + (("\n" + "\n".join(errs)) if errs else ""))


def reverse_geocode(lat, lon, settings=None):
    s = settings or load_settings()
    if s.get("vworld_key"):
        try:
            q = urllib.parse.urlencode({"service": "address", "request": "getAddress", "version": "2.0",
                                        "crs": "epsg:4326", "point": f"{lon},{lat}", "format": "json",
                                        "type": "both", "key": s["vworld_key"]})
            js = http_json("https://api.vworld.kr/req/address?" + q)
            res = (js.get("response") or {}).get("result") or []
            if res:
                stc = res[0].get("structure", {}) or {}
                return {"address": res[0].get("text", ""), "sido": stc.get("level1", ""),
                        "sigungu": stc.get("level2", "")}
        except GeoError:
            pass
    if s.get("kakao_key"):
        try:
            js = http_json("https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?" +
                           urllib.parse.urlencode({"x": lon, "y": lat}),
                           headers={"Authorization": "KakaoAK " + s["kakao_key"]})
            docs = js.get("documents") or []
            if docs:
                d = docs[0]
                return {"address": d.get("address_name", ""), "sido": d.get("region_1depth_name", ""),
                        "sigungu": d.get("region_2depth_name", "")}
        except GeoError:
            pass
    return None


# ─────────────────────────────────────────────────────────────
#  표고 (DEM)
# ─────────────────────────────────────────────────────────────
_elev_cache = None


def _cache():
    global _elev_cache
    if _elev_cache is None:
        try:
            _elev_cache = json.loads(ELEV_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:                        # noqa: BLE001
            _elev_cache = {}
    return _elev_cache


def _save_cache():
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        c = _cache()
        if len(c) > 200000:                      # 너무 커지면 비움
            c.clear()
        ELEV_CACHE_FILE.write_text(json.dumps(c), encoding="utf-8")
    except Exception:                            # noqa: BLE001
        pass


def elevations(points, progress=None, batch=100):
    """[(lat, lon)] → [elev(m) | None]  — Open-Meteo (Copernicus DEM 90m)."""
    cache = _cache()
    keys = [f"{la:.5f},{lo:.5f}" for la, lo in points]
    need = [i for i, k in enumerate(keys) if k not in cache]
    done = 0
    for i in range(0, len(need), batch):
        idx = need[i:i + batch]
        lats = ",".join(f"{points[j][0]:.5f}" for j in idx)
        lons = ",".join(f"{points[j][1]:.5f}" for j in idx)
        js = http_json("https://api.open-meteo.com/v1/elevation?" +
                       urllib.parse.urlencode({"latitude": lats, "longitude": lons}), timeout=30)
        el = js.get("elevation")
        if not isinstance(el, list) or len(el) != len(idx):
            raise GeoError("표고 응답 형식이 올바르지 않습니다: " + str(js)[:200])
        for j, e in zip(idx, el):
            cache[keys[j]] = e
        done += len(idx)
        if progress:
            progress(done, len(need))
    if need:
        _save_cache()
    return [cache.get(k) for k in keys]
