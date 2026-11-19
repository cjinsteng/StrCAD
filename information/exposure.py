"""
information/exposure.py — 지표면조도구분(노풍도) 산정 (KDS 41 12 00:2022 5.5.4)

    · 범위 : 건설지점에서 기준높이 H 의 40배와 3km 가운데 작은 값 (원문 5.5.4 (1)①)
             설정에서 '큰 값'으로 바꿀 수 있다.
    · 8풍향(N, NE, …, NW) — 풍상측 45° 부채꼴 안의 지표면 상태로 A·B·C·D 판정 (표 5.5-1)
        A 대도시 중심부에서 10층 이상 고층건축구조물이 밀집
        B 높이 3.5m 정도의 주택 같은 건축구조물 밀집, 중층건물(4~9층) 산재, 수목 밀집
        C 높이 1.5~10m 장애물 산재, 수목·저층건축구조물 산재
        D 장애물이 거의 없음 (해안, 초원, 비행장)
    · 건물 자료 : 브이월드 2D 데이터(도로명주소건물, 지상층수) → 없으면 OpenStreetMap
    · 수면 비율 : 부채꼴 안 표본점 표고(Open-Meteo, 해수면 0m)로 추정
    · 배경 지도 : 브이월드 영상(위성)/기본지도 → 없으면 OpenStreetMap
"""
import io
import json
import math
import threading
import urllib.parse
import urllib.request

from . import geo

SECTORS = [("N", 0), ("NE", 45), ("E", 90), ("SE", 135), ("S", 180), ("SW", 225), ("W", 270), ("NW", 315)]
SECTOR_KO = {"N": "북", "NE": "북동", "E": "동", "SE": "남동", "S": "남", "SW": "남서", "W": "서", "NW": "북서"}
CAT_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}            # 뒤로 갈수록 바람이 세다 (불리)
CAT_DESC = {
    "A": "대도시 중심부, 10층 이상 고층건축구조물 밀집",
    "B": "주택 같은 건축구조물 밀집 · 중층건물(4~9층) 산재 · 수목 밀집",
    "C": "높이 1.5~10m 장애물 산재 · 수목·저층건축구조물 산재",
    "D": "장애물 거의 없음 — 해안·초원·비행장",
}

# 판정 기준 (부채꼴 육지면적 대비 건물 바닥면적 비율) — 화면에서 설명과 함께 보여 준다
TH = {
    "water_D": 0.60,     # 수면 60% 이상 → D
    "A_hi": 0.15,        # 10층 이상 건물 바닥면적비 15% 이상 + 전체 건폐 30% 이상 → A (도심 고층 밀집)
    "A_cov": 0.30,      # (아파트 단지 정도는 B — 안전측)
    "B_cov": 0.12,       # 건폐 12% 이상 → B (주택 밀집)
    "B_mid": 0.03,       # 4~9층 바닥면적비 3% 이상 → B (중층 산재)
    "B_hi": 0.03,        # 10층 이상 바닥면적비 3% 이상 → B
    "C_cov": 0.02,       # 건폐 2% 이상 → C
}

TILE_SRC = {
    "vworld_sat": ("브이월드 영상", "https://api.vworld.kr/req/wmts/1.0.0/{key}/Satellite/{z}/{y}/{x}.jpeg", 19),
    "vworld_base": ("브이월드 기본", "https://api.vworld.kr/req/wmts/1.0.0/{key}/Base/{z}/{y}/{x}.png", 19),
    "osm": ("OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", 19),
}
ATTRIB = {"vworld_sat": "© 국토교통부 브이월드", "vworld_base": "© 국토교통부 브이월드",
          "osm": "© OpenStreetMap contributors"}


def radius_m(H, rule="kds"):
    """조도 판정 범위.  rule='kds' : 40H 와 3km 중 작은 값 (원문) / 'max' : 큰 값."""
    a = 40.0 * float(H or 0.0)
    return min(a, 3000.0) if rule != "max" else max(a, 3000.0)


def sector_of(brg):
    return int(((brg + 22.5) % 360) // 45)


def external_links(lat, lon, name=""):
    q = urllib.parse.quote(name or "건설지점")
    return {
        "카카오맵": f"https://map.kakao.com/link/map/{q},{lat:.6f},{lon:.6f}",
        "카카오 로드뷰": f"https://map.kakao.com/link/roadview/{lat:.6f},{lon:.6f}",
        "네이버지도": f"https://map.naver.com/p?c={lon:.6f},{lat:.6f},16,0,0,0,dh",
        "구글 위성": f"https://www.google.com/maps/@{lat:.6f},{lon:.6f},1500m/data=!3m1!1e3",
        "브이월드": "https://map.vworld.kr/map/maps.do",
    }


# ─────────────────────────────────────────────────────────────
#  HTTP
# ─────────────────────────────────────────────────────────────
def http_bytes(url, data=None, timeout=30, headers=None):
    h = {"User-Agent": "StrCAD-Information/1.0 (structural engineering desktop app)"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:                           # noqa: BLE001
        raise geo.GeoError(f"서버 연결 실패: {e}") from e


# ─────────────────────────────────────────────────────────────
#  배경 지도 (웹 메르카토르 타일)
# ─────────────────────────────────────────────────────────────
def _ll2tile(lat, lon, z):
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    la = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(la)) / math.pi) / 2.0 * n
    return x, y


class MapView:
    """합성한 배경 지도와 위경도 ↔ 그림 좌표 변환."""

    def __init__(self, image, z, x0, y0, scale, src, note=""):
        self.image, self.z, self.x0, self.y0, self.scale, self.src, self.note = image, z, x0, y0, scale, src, note

    def to_px(self, lat, lon):
        tx, ty = _ll2tile(lat, lon, self.z)
        return (tx * 256 - self.x0) * self.scale, (ty * 256 - self.y0) * self.scale


def compose_map(lat, lon, R, settings=None, size=760, provider=None, progress=None):
    """건설지점 중심, 반경 R 의 1.15배가 들어가는 배경 지도.  실패하면 회색 바탕."""
    from PIL import Image
    settings = settings or geo.load_settings()
    key = (settings.get("vworld_key") or "").strip()
    order = [provider] if provider else []
    order += (["vworld_sat", "vworld_base"] if key else []) + ["osm"]
    half = R * 1.18
    mpp_target = 2 * half / size
    errors = []
    for prov in [p for i, p in enumerate(order) if p and p not in order[:i]]:
        label, tmpl, zmax = TILE_SRC[prov]
        if prov.startswith("vworld") and not key:
            continue
        z = int(math.floor(math.log2(156543.03392 * math.cos(math.radians(lat)) / mpp_target)))
        z = max(5, min(z, zmax))
        cx, cy = _ll2tile(lat, lon, z)
        mpp = 156543.03392 * math.cos(math.radians(lat)) / 2 ** z
        half_px = half / mpp
        px0, py0 = cx * 256 - half_px, cy * 256 - half_px
        px1, py1 = cx * 256 + half_px, cy * 256 + half_px
        tx0, ty0, tx1, ty1 = int(px0 // 256), int(py0 // 256), int(px1 // 256), int(py1 // 256)
        n = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
        if n > 64:
            errors.append(f"{label}: 타일 수 과다")
            continue
        mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (60, 60, 60))
        ok = 0
        cache_dir = geo.APP_DIR / "tiles" / prov / str(z)
        for k, (tx, ty) in enumerate((a, b) for a in range(tx0, tx1 + 1) for b in range(ty0, ty1 + 1)):
            fp = cache_dir / f"{tx}_{ty}.img"
            try:
                if fp.exists():
                    raw = fp.read_bytes()
                else:
                    raw = http_bytes(tmpl.format(key=key, z=z, x=tx, y=ty), timeout=20)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    fp.write_bytes(raw)
                im = Image.open(io.BytesIO(raw)).convert("RGB")
                mosaic.paste(im, ((tx - tx0) * 256, (ty - ty0) * 256))
                ok += 1
            except Exception as e:                   # noqa: BLE001
                if not errors or not errors[-1].startswith(label):
                    errors.append(f"{label}: {e}")
            if progress:
                progress(f"배경 지도 {label} {k + 1}/{n}")
        if ok == 0:
            continue
        crop = mosaic.crop((int(px0 - tx0 * 256), int(py0 - ty0 * 256),
                            int(px0 - tx0 * 256 + 2 * half_px), int(py0 - ty0 * 256 + 2 * half_px)))
        scale = size / crop.width
        img = crop.resize((size, size), Image.LANCZOS)
        return MapView(img, z, px0, py0, scale, prov, "; ".join(errors))
    img = Image.new("RGB", (size, size), (70, 74, 80))
    z = 15
    cx, cy = _ll2tile(lat, lon, z)
    mpp = 156543.03392 * math.cos(math.radians(lat)) / 2 ** z
    half_px = half / mpp
    return MapView(img, z, cx * 256 - half_px, cy * 256 - half_px, size / (2 * half_px), "",
                   "배경 지도 없음 — " + ("; ".join(errors) or "인터넷 연결 확인"))


# ─────────────────────────────────────────────────────────────
#  건물 자료
# ─────────────────────────────────────────────────────────────
FLOOR_KEYS = ("gro_flo_co", "grnd_flr", "grnd_flr_co", "flr_co", "floors", "building:levels")
HEIGHT_KEYS = ("height", "bld_hgt", "hgt", "buld_hgt", "building:height")


def _num(v):
    try:
        f = float(str(v).replace("m", "").strip())
        return f if f > 0 else None
    except Exception:                                # noqa: BLE001
        return None


def _poly_area_centroid(lat0, lon0, ring):
    """[(lon, lat)] → (면적 m², 중심 위경도)"""
    pts = [geo.local_xy(lat0, lon0, la, lo) for lo, la in ring]
    if len(pts) < 3:
        return 0.0, None
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    a *= 0.5
    if abs(a) < 1e-6:
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
    else:
        mx, my = cx / (6 * a), cy / (6 * a)
    la = lat0 + my / 111320.0
    lo = lon0 + mx / (111320.0 * math.cos(math.radians(lat0)))
    return abs(a), (la, lo)


def _building(lat0, lon0, rings, props):
    area, c = _poly_area_centroid(lat0, lon0, rings[0])
    for hole in rings[1:]:
        area -= _poly_area_centroid(lat0, lon0, hole)[0]
    if not c or area <= 1.0:
        return None
    fl = next((_num(props.get(k)) for k in FLOOR_KEYS if _num(props.get(k))), None)
    h = next((_num(props.get(k)) for k in HEIGHT_KEYS if _num(props.get(k))), None)
    if fl is None and h is not None:
        fl = max(1.0, round(h / 3.2))
    return {"lat": c[0], "lon": c[1], "area": area, "floors": fl, "height": h,
            "ring": rings[0], "name": props.get("buld_nm") or props.get("name") or ""}


def fetch_buildings_vworld(lat, lon, R, key, progress=None, cancel=None):
    """브이월드 2D 데이터 — 도로명주소건물(LT_C_SPBD).  1km 격자로 나눠 요청."""
    out = []
    dlat = R / 111320.0
    dlon = R / (111320.0 * math.cos(math.radians(lat)))
    n = max(1, int(math.ceil(2 * R / 1000.0)))
    cells = [(i, j) for i in range(n) for j in range(n)]
    seen = set()
    for k, (i, j) in enumerate(cells):
        if cancel and cancel():
            break
        x0 = lon - dlon + 2 * dlon * i / n
        y0 = lat - dlat + 2 * dlat * j / n
        x1, y1 = x0 + 2 * dlon / n, y0 + 2 * dlat / n
        page = 1
        while True:
            q = urllib.parse.urlencode({
                "service": "data", "request": "GetFeature", "data": "LT_C_SPBD", "key": key,
                "format": "json", "size": 1000, "page": page, "geometry": "true", "attribute": "true",
                "crs": "EPSG:4326", "geomFilter": f"BOX({x0:.6f},{y0:.6f},{x1:.6f},{y1:.6f})"})
            js = json.loads(http_bytes("https://api.vworld.kr/req/data?" + q, timeout=40).decode("utf-8"))
            resp = js.get("response", {})
            st = resp.get("status")
            if st == "NOT_FOUND":
                break
            if st != "OK":
                raise geo.GeoError("브이월드 데이터: " + str((resp.get("error") or {}).get("text", st)))
            feats = (resp.get("result") or {}).get("featureCollection", {}).get("features", [])
            for f in feats:
                props = f.get("properties") or {}
                fid = props.get("bd_mgt_sn") or f.get("id")
                if fid in seen:
                    continue
                seen.add(fid)
                g = f.get("geometry") or {}
                polys = g.get("coordinates") or []
                if g.get("type") == "Polygon":
                    polys = [polys]
                for poly in polys:
                    b = _building(lat, lon, poly, props)
                    if b:
                        out.append(b)
            total_pages = int((resp.get("page") or {}).get("total", 1) or 1)
            if page >= total_pages:
                break
            page += 1
        if progress:
            progress(f"건물 자료 (브이월드) {k + 1}/{len(cells)} — {len(out)}동")
    return out


def fetch_buildings_osm(lat, lon, R, progress=None, cancel=None):
    """OpenStreetMap Overpass — building 다각형."""
    if progress:
        progress("건물 자료 (OpenStreetMap) 요청 중…")
    q = (f'[out:json][timeout:120];(way["building"](around:{int(R)},{lat:.6f},{lon:.6f}););'
         'out tags geom;')
    raw = None
    errs = []
    for ep in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
        try:
            raw = http_bytes(ep, data=urllib.parse.urlencode({"data": q}).encode(), timeout=150)
            break
        except Exception as e:                       # noqa: BLE001
            errs.append(str(e))
    if raw is None:
        raise geo.GeoError("OpenStreetMap 건물 요청 실패: " + "; ".join(errs))
    js = json.loads(raw.decode("utf-8"))
    out = []
    for el in js.get("elements", []):
        g = el.get("geometry") or []
        ring = [(p["lon"], p["lat"]) for p in g]
        b = _building(lat, lon, [ring], el.get("tags") or {})
        if b:
            out.append(b)
    if progress:
        progress(f"건물 자료 (OpenStreetMap) {len(out)}동")
    return out


def fetch_buildings(lat, lon, R, settings=None, progress=None, cancel=None):
    settings = settings or geo.load_settings()
    key = (settings.get("vworld_key") or "").strip()
    errors = []
    if key and settings.get("exposure_source", "auto") in ("auto", "vworld"):
        try:
            b = fetch_buildings_vworld(lat, lon, R, key, progress, cancel)
            if b:
                return b, "브이월드 2D 데이터 (도로명주소건물·지상층수)", errors
        except Exception as e:                       # noqa: BLE001
            errors.append(str(e))
    try:
        return fetch_buildings_osm(lat, lon, R, progress, cancel), "OpenStreetMap 건물 (층수 태그 일부)", errors
    except Exception as e:                           # noqa: BLE001
        errors.append(str(e))
    return [], "", errors


def water_fraction(lat, lon, R, progress=None):
    """부채꼴마다 표본점 15개 표고 → 해수면(≤0.5m) 비율."""
    pts, owner = [], []
    for s, (nm, brg) in enumerate(SECTORS):
        for f in (0.25, 0.45, 0.65, 0.82, 0.97):
            for da in (-15, 0, 15):
                pts.append(geo.offset_latlon(lat, lon, brg + da, f * R))
                owner.append(s)
    try:
        el = geo.elevations(pts)
    except Exception:                                # noqa: BLE001
        return None
    cnt = [0] * 8
    wat = [0] * 8
    for s, e in zip(owner, el):
        if e is None:
            continue
        cnt[s] += 1
        if e <= 0.5:
            wat[s] += 1
    return [w / c if c else 0.0 for w, c in zip(wat, cnt)]


# ─────────────────────────────────────────────────────────────
#  판정
# ─────────────────────────────────────────────────────────────
def classify(cov, hi, mid, water):
    if water >= TH["water_D"]:
        return "D", f"수면 {water * 100:.0f}% ≥ {TH['water_D'] * 100:.0f}% (해안·수면)"
    if hi >= TH["A_hi"] and cov >= TH["A_cov"]:
        return "A", f"10층 이상 바닥면적비 {hi * 100:.1f}% ≥ {TH['A_hi'] * 100:.0f}%, 건폐 {cov * 100:.1f}% ≥ {TH['A_cov'] * 100:.0f}%"
    if cov >= TH["B_cov"]:
        return "B", f"건폐 {cov * 100:.1f}% ≥ {TH['B_cov'] * 100:.0f}% (건축구조물 밀집)"
    if mid >= TH["B_mid"] or hi >= TH["B_hi"]:
        return "B", f"중·고층 바닥면적비 {(mid + hi) * 100:.1f}% (중층건물 산재)"
    if cov >= TH["C_cov"]:
        return "C", f"건폐 {cov * 100:.1f}% (저층 건물 산재)"
    if water >= 0.3:
        return "D", f"건물 거의 없음 + 수면 {water * 100:.0f}%"
    return "C", "건물 거의 없음 — 수목·농경지로 보고 C (평탄 개활지·초원이면 D로 바꾸세요)"


def analyze(lat, lon, H, buildings, water=None, rule="kds", source=""):
    R = radius_m(H, rule)
    sec_area = math.pi * R * R / 8.0
    rows = []
    acc = [{"n": 0, "area": 0.0, "hi": 0.0, "mid": 0.0, "low": 0.0, "unk": 0, "fl_area": 0.0, "fl_w": 0.0,
            "max_fl": 0} for _ in range(8)]
    for b in buildings:
        x, y = geo.local_xy(lat, lon, b["lat"], b["lon"])
        d = math.hypot(x, y)
        if d > R or d < 15.0:
            continue
        s = sector_of(math.degrees(math.atan2(x, y)) % 360)
        a = acc[s]
        a["n"] += 1
        a["area"] += b["area"]
        fl = b.get("floors")
        if fl is None:
            a["unk"] += 1
            a["low"] += b["area"]
        elif fl >= 10:
            a["hi"] += b["area"]
        elif fl >= 4:
            a["mid"] += b["area"]
        else:
            a["low"] += b["area"]
        if fl:
            a["fl_area"] += fl * b["area"]
            a["fl_w"] += b["area"]
            a["max_fl"] = max(a["max_fl"], int(fl))
    for s, (nm, brg) in enumerate(SECTORS):
        a = acc[s]
        w = (water[s] if water else 0.0) or 0.0
        land = max(sec_area * (1.0 - w), sec_area * 0.05)
        cov, hi, mid = a["area"] / land, a["hi"] / land, a["mid"] / land
        cat, why = classify(cov, hi, mid, w)
        mean_fl = a["fl_area"] / a["fl_w"] if a["fl_w"] else None
        rows.append({"dir": nm, "ko": SECTOR_KO[nm], "brg": brg, "cat": cat, "auto": cat, "why": why,
                     "n": a["n"], "cov": cov, "hi": hi, "mid": mid, "water": w, "mean_fl": mean_fl,
                     "max_fl": a["max_fl"], "unk": a["unk"]})
    res = {"lat": lat, "lon": lon, "H": H, "R": R, "rule": rule, "source": source, "sectors": rows,
           "n_buildings": sum(r["n"] for r in rows)}
    update_governing(res)
    return res


def update_governing(res):
    rows = res["sectors"]
    g = max(rows, key=lambda r: (CAT_ORDER[r["cat"]], -r["cov"]))
    for r in rows:
        r["star"] = r is g
    res["governing"] = g["cat"]
    res["governing_dir"] = g["dir"]
    return res


def explain(r):
    fl = f", 평균 {r['mean_fl']:.1f}층(최고 {r['max_fl']}층)" if r.get("mean_fl") else ""
    unk = f", 층수 미상 {r['unk']}동" if r.get("unk") else ""
    return (f"{r['dir']}({r['ko']}) {r['cat']}{' ★' if r.get('star') else ''} — 건물 {r['n']}동, "
            f"건폐 {r['cov'] * 100:.1f}%, 10층↑ {r['hi'] * 100:.1f}%, 4~9층 {r['mid'] * 100:.1f}%, "
            f"수면 {r['water'] * 100:.0f}%{fl}{unk} → {r['why']}")


def run(lat, lon, H, settings=None, progress=None, cancel=None):
    settings = settings or geo.load_settings()
    rule = settings.get("exposure_rule", "kds")
    R = radius_m(H, rule)
    res = {"errors": []}
    out = {}

    def bg():
        out["view"] = compose_map(lat, lon, R, settings, progress=progress)

    t = threading.Thread(target=bg, daemon=True)
    t.start()
    b, src, errs = fetch_buildings(lat, lon, R, settings, progress, cancel)
    if progress:
        progress("수면 비율(표고) 확인 중…")
    w = water_fraction(lat, lon, R)
    t.join(timeout=120)
    res = analyze(lat, lon, H, b, w, rule, src)
    res["errors"] = errs + ([] if w is not None else ["표고 조회 실패 — 수면 비율 0으로 가정"])
    res["view"] = out.get("view")
    res["buildings"] = b
    return res


# ─────────────────────────────────────────────────────────────
#  그림 (8방위 부채꼴 · 노풍도 표기 · 건물 층수 색)
# ─────────────────────────────────────────────────────────────
def render(res, size=760, show_buildings=True):
    from PIL import Image, ImageDraw, ImageFont
    view = res.get("view")
    if view is None:
        view = compose_map(res["lat"], res["lon"], res["R"], size=size)
    base = view.image.convert("RGBA")
    W, H = base.size
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    lat, lon, R = res["lat"], res["lon"], res["R"]
    cx, cy = view.to_px(lat, lon)
    ex, ey = view.to_px(*geo.offset_latlon(lat, lon, 90, R))
    rp = math.hypot(ex - cx, ey - cy)
    # 반경 밖은 어둡게
    mask = Image.new("L", base.size, 120)
    ImageDraw.Draw(mask).ellipse((cx - rp, cy - rp, cx + rp, cy + rp), fill=0)
    ov.paste((255, 255, 255, 255), (0, 0), Image.eval(mask, lambda v: v))
    if show_buildings:
        for b in res.get("buildings") or []:
            fl = b.get("floors")
            col = ((150, 150, 150, 120) if fl is None else (230, 60, 60, 170) if fl >= 10
                   else (245, 160, 40, 160) if fl >= 4 else (250, 230, 90, 130))
            pts = [view.to_px(la, lo) for lo, la in b["ring"]]
            if len(pts) >= 3 and max(abs(x - cx) for x, _ in pts) < rp * 1.05:
                d.polygon(pts, fill=col)
    d.ellipse((cx - rp, cy - rp, cx + rp, cy + rp), outline=(230, 30, 30, 255), width=3)
    for s in range(8):
        a = math.radians(22.5 + 45 * s)
        d.line((cx, cy, cx + rp * math.sin(a), cy - rp * math.cos(a)), fill=(230, 30, 30, 220), width=2)
    try:
        font = ImageFont.truetype("malgunbd.ttf", 18)
        small = ImageFont.truetype("malgun.ttf", 12)
    except Exception:                                # noqa: BLE001
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 17)
            small = ImageFont.truetype("DejaVuSans.ttf", 11)
        except Exception:                            # noqa: BLE001
            font = small = ImageFont.load_default()
    for r in res["sectors"]:
        a = math.radians(r["brg"])
        tx, ty = cx + 0.72 * rp * math.sin(a), cy - 0.72 * rp * math.cos(a)
        txt = f"{r['dir']} {r['cat']}{'★' if r.get('star') else ''}"
        bb = d.textbbox((0, 0), txt, font=font)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        d.rectangle((tx - w / 2 - 6, ty - h / 2 - 5, tx + w / 2 + 6, ty + h / 2 + 7), fill=(255, 255, 255, 235),
                    outline=(60, 60, 60, 255))
        d.text((tx - w / 2, ty - h / 2 - 2), txt, fill=(20, 20, 20, 255), font=font)
    d.rectangle((cx - 5, cy - 5, cx + 5, cy + 5), fill=(255, 30, 30, 255), outline=(255, 255, 255, 255))
    lab = f"R = {R:,.0f} m  ({'40H·3km 중 작은 값' if res['rule'] != 'max' else '40H·3km 중 큰 값'})"
    d.rectangle((6, 6, 16 + d.textbbox((0, 0), lab, font=small)[2], 26), fill=(255, 255, 255, 220))
    d.text((11, 9), lab, fill=(0, 0, 0, 255), font=small)
    att = ATTRIB.get(view.src, "")
    if att:
        bb = d.textbbox((0, 0), att, font=small)
        d.rectangle((W - bb[2] - 14, H - 22, W - 4, H - 4), fill=(255, 255, 255, 200))
        d.text((W - bb[2] - 9, H - 20), att, fill=(0, 0, 0, 255), font=small)
    if show_buildings:
        y = H - 24
        for txt, col in (("10층↑", (230, 60, 60)), ("4~9층", (245, 160, 40)), ("1~3층", (250, 230, 90)),
                         ("층수 미상", (150, 150, 150))):
            d.rectangle((8, y, 22, y + 14), fill=col + (255,))
            d.text((26, y), txt, fill=(255, 255, 255, 255), font=small, stroke_width=2, stroke_fill=(0, 0, 0, 255))
            y -= 18
    return Image.alpha_composite(base, ov).convert("RGB")
