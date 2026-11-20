"""
information/boreholes.py — 시추조사 자료 DB · 반경 검색 · 시추공별 지반분류

자료 출처: 국토지반정보 포털시스템(geoinfo.or.kr) 의 시추정보 DB.
공공데이터포털(data.go.kr) 파일데이터로 같은 자료를 받을 수 있다.
  · 국토교통부_지반정보_시추공          (시추공코드·좌표·표고·심도)
  · 국토교통부_지반정보_지층정보        (시추공코드·지층시작/종료심도·토목용지층명)
  · 국토교통부_지반정보_표준관입시험정보 (시추공코드·시험심도·타격회수·관입깊이)
받은 CSV 를 가져오면 PC 안의 SQLite DB(~/.strcad/boreholes.db)에 쌓고, 인터넷 없이 반경 검색한다.
"""
import csv
import re
import io
import math
import sqlite3
import threading
from pathlib import Path

from . import geo
from . import kds_data as K
from . import seismic

DEFAULT_DB = geo.APP_DIR / "boreholes.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS holes (
    code TEXT PRIMARY KEY, project TEXT, name TEXT,
    lat REAL, lon REAL, elev REAL, depth REAL, gwl REAL, source TEXT);
CREATE INDEX IF NOT EXISTS ix_holes_ll ON holes(lat, lon);
CREATE TABLE IF NOT EXISTS layers (
    hole TEXT, top REAL, bot REAL, name TEXT, uscs TEXT, descr TEXT);
CREATE INDEX IF NOT EXISTS ix_layers_hole ON layers(hole);
CREATE TABLE IF NOT EXISTS spt (
    hole TEXT, depth REAL, blows REAL, pen REAL, n REAL);
CREATE INDEX IF NOT EXISTS ix_spt_hole ON spt(hole);
CREATE TABLE IF NOT EXISTS vs (
    hole TEXT, top REAL, bot REAL, vp REAL, vs REAL, layer TEXT);
CREATE INDEX IF NOT EXISTS ix_vs_hole ON vs(hole);
CREATE TABLE IF NOT EXISTS perm (hole TEXT, top REAL, bot REAL, k REAL);
CREATE INDEX IF NOT EXISTS ix_perm_hole ON perm(hole);
CREATE TABLE IF NOT EXISTS strength (hole TEXT, sample TEXT, typ TEXT, phi REAL, c REAL);
CREATE INDEX IF NOT EXISTS ix_str_hole ON strength(hole);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

# ─────────────────────────────────────────────────────────────
#  CSV 헤더 매핑
# ─────────────────────────────────────────────────────────────
FIELDS = {
    "hole":     ["HOLE_CODE", "시추공코드", "시추공번호", "시추공ID", "공번", "BH_CODE", "HOLECODE"],
    "project":  ["PROJECT_CODE", "프로젝트코드", "사업코드"],
    "pname":    ["PROJECT_NAME", "프로젝트명", "사업명"],
    "name":     ["HOLE_NAME", "시추공명", "시추공이름", "BH_NAME"],
    "x":        ["HOLE_X", "X좌표", "좌표X", "TM_X", "X", "경도", "LON", "LONGITUDE", "HOLE_LON", "LNG"],
    "y":        ["HOLE_Y", "Y좌표", "좌표Y", "TM_Y", "Y", "위도", "LAT", "LATITUDE", "HOLE_LAT"],
    "elev":     ["HOLE_EL", "HOLE_ELEV", "HOLE_ELEVATION", "표고", "고도", "지반고", "지반표고", "공구표고", "ELEV", "EL"],
    "depth":    ["HOLE_DEPTH", "시추심도", "굴진심도", "시추깊이", "총심도", "DEPTH"],
    "gwl":      ["HOLE_WATER_LEVEL", "WATER_LEVEL", "GWL", "지하수위", "지하수위심도"],
    "top":      ["LAYER_DEPTH_FROM", "지층시작심도", "시작심도", "상단심도", "심도FROM", "FROM"],
    "bot":      ["LAYER_DEPTH_TO", "지층종료심도", "종료심도", "하단심도", "심도TO", "TO"],
    "lname":    ["ENG_LAYER_NAME", "토목용지층명", "지층명", "LAYER_NAME", "지층"],
    "uscs":     ["USCS_CODE", "USCS_NAME", "LAYER_ENG_NAME", "학술용지층명", "학술용지층명USCS", "USCS"],
    "descr":    ["LAYER_DESC", "비고", "지층설명", "DESCRIPTION"],
    "sdepth":   ["DEPTH_SPT", "시험심도", "SPT_DEPTH", "SPT심도", "N값심도"],
    "blows":    ["SPT_BLOW", "BLOW_COUNT", "타격회수", "타격횟수", "N값", "N_VALUE", "NVALUE", "N"],
    "pen":      ["SPT_PENETRATION", "PENETRATION", "관입깊이", "관입량", "관입심도", "PEN"],
    "vs":       ["DH_VS_VELOCITY", "전단파속도(S파)", "S파속도", "VS"],
    "vp":       ["DH_VP_VELOCITY", "전단파속도(P파)", "P파속도", "VP"],
    "serial":   ["시추일련번호"],
    "pattern":  ["패턴코드"],
    "ftop":     ["구간시작(미터)"],
    "fbot":     ["구간종료(미터)"],
    "mdepth":   ["시추심도(미터)"],
    "site":     ["시추지점명"],
    "addr":     ["주소코드"],
    "geom":     ["위치정보"],
    "kperm":    ["평균투수계수"],
    "ttop":     ["시험 시작심도"],
    "tbot":     ["시험 종료심도"],
    "sample":   ["시료코드"],
    "ttype":    ["시험종류"],
    "phi":      ["내부마찰각"],
    "coh":      ["점착력"],
}


def _norm(h):
    return "".join(ch for ch in str(h).upper() if ch not in " _-()/[].·\t﻿")


def _summary_cols(headers):
    hn = [_norm(h) for h in headers]
    cols = {}
    for key, _ in SUMMARY_LAYERS:
        for i, h in enumerate(hn):
            if h.startswith(_norm(key)) and "두께" in h:
                cols[key + "_t"] = i
            elif h.startswith(_norm(key)) and "N" in h.upper():
                cols[key + "_n"] = i
    if sum(1 for k in cols if k.endswith("_t")) >= 3:
        for i, h in enumerate(hn):
            if h.startswith(_norm("암반")):
                cols["rqd"] = i
            elif h.startswith("프로젝트명"):
                cols["pname"] = i
            elif h in ("공번", "시추번호", "시추공번호", "공명"):
                cols["hole"] = i
            elif h.startswith("가로좌표") or h in ("X좌표", "X"):
                cols["x"] = i
            elif h.startswith("세로좌표") or h in ("Y좌표", "Y"):
                cols["y"] = i
            elif h.startswith("표고"):
                cols["elev"] = i
            elif h.startswith("시추심도"):
                cols["depth"] = i
            elif h.startswith("지하수위"):
                cols["gwl"] = i
            elif h.startswith("시추일자"):
                cols["date"] = i
        return cols
    return None


def map_headers(headers):
    """헤더 → {필드: 열 index}  (공별 요약표는 {"sum_cols": {...}})"""
    sc = _summary_cols(headers)
    if sc:
        return {"sum_cols": sc}
    nh = [_norm(h) for h in headers]
    out = {}
    for f, cands in FIELDS.items():                      # 1) 정확히 같은 이름
        cn = [_norm(c) for c in cands]
        hit = next((i for i, h in enumerate(nh) if h in cn and i not in out.values()), None)
        if hit is not None:
            out[f] = hit
    generic = {"DEPTH", "EL", "N", "X", "Y", "TO", "FROM", "LON", "LAT", "LNG", "PEN", "USCS"}
    for f, cands in FIELDS.items():                      # 2) 이름 일부 (긴 후보만)
        if f in out or f in ("x", "y", "top", "bot", "blows", "pen"):
            continue
        cn = [_norm(c) for c in cands if _norm(c) not in generic and len(_norm(c)) >= 3]
        hit = next((i for i, h in enumerate(nh) for c in cn if c in h and i not in out.values()), None)
        if hit is not None:
            out[f] = hit
    return out


SUMMARY_LAYERS = (("매립층", "매립층"), ("퇴적층", "퇴적층"), ("풍화토", "풍화토층"), ("풍화암", "풍화암층"),
                  ("연암", "연암층"), ("보통암", "보통암층"), ("경암", "경암층"))


def detect_kind(m):
    if "sum_cols" in m:
        return "summary"                             # 공별 층 두께·N치 요약표 (조사보고서 요약)
    if "kperm" in m and "hole" in m:
        return "perm"                                # 현장투수시험
    if "sample" in m and ("phi" in m or "coh" in m):
        return "strength"                            # 전단강도시험 (삼축·직접전단)
    if "serial" in m and "pattern" in m:
        return "agg_layers"                          # 골재자원조사 시추 주상(패턴코드)
    if "serial" in m and "x" in m and "y" in m:
        return "agg_holes"                           # 골재자원조사 GIS (위도·경도)
    if "vs" in m and "top" in m and "hole" in m:
        return "downhole"                            # 하향식 탄성파(Vs)
    if "top" in m and "bot" in m:
        return "layers"
    if "sdepth" in m and "blows" in m:
        return "spt"
    if "x" in m and "y" in m:
        return "holes"
    return ""


KIND_LABEL = {"holes": "시추공(위치)", "layers": "지층정보", "spt": "표준관입시험", "downhole": "하향식 탄성파(Vs)",
              "agg_holes": "골재자원조사 시추위치", "agg_layers": "골재자원조사 주상", "perm": "현장투수시험",
              "strength": "전단강도시험", "summary": "공별 층두께·N치 요약표", "": "알 수 없음"}


def read_csv_head(path, n=200):
    """(headers, rows, encoding)"""
    with open(path, "rb") as fp:
        raw = fp.read(4_000_000)
    # 깨진 글자가 가장 적은 인코딩 (자료 안에 잘못된 바이트가 섞여 있어도 판별)
    best = None
    for enc in ("utf-8-sig", "cp949"):
        t = raw.decode(enc, errors="replace")
        bad = t.count("\ufffd")
        if best is None or bad < best[0]:
            best = (bad, t, enc)
    _, text, enc = best
    rd = csv.reader(io.StringIO(text, newline=""))
    headers = next(rd, [])
    rows = []
    for r in rd:
        rows.append(r)
        if len(rows) >= n:
            break
    return headers, rows, enc


def _f(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "NULL", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        # "50/10" 같은 타격회수/관입 표기
        if "/" in s:
            return None
        return None


def parse_blows(text):
    """'50/10' → (50, 10), '23' → (23, None)"""
    s = str(text or "").strip()
    if "/" in s:
        a, b = s.split("/", 1)
        return _f(a), _f(b)
    return _f(s), None


def n_value(blows, pen):
    """타격회수·관입깊이(cm) → 환산 N (30cm 기준, 상한 N_CAP)."""
    if blows is None:
        return None
    if pen and pen > 0:
        p = pen / 10.0 if pen > 60 else pen        # mm 로 적힌 경우
        if p < 30:
            return min(blows * 30.0 / p, K.N_CAP)
    return min(blows, K.N_CAP)


# ─────────────────────────────────────────────────────────────
#  DB
# ─────────────────────────────────────────────────────────────
class BoreholeDB:
    def __init__(self, path=None):
        self.path = Path(path or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        return sqlite3.connect(str(self.path))

    def stats(self):
        with self._conn() as c:
            h = c.execute("SELECT COUNT(*) FROM holes").fetchone()[0]
            hl = c.execute("SELECT COUNT(*) FROM holes WHERE lat IS NOT NULL").fetchone()[0]
            l = c.execute("SELECT COUNT(DISTINCT hole) FROM layers").fetchone()[0]
            s = c.execute("SELECT COUNT(DISTINCT hole) FROM spt").fetchone()[0]
            v = c.execute("SELECT COUNT(DISTINCT hole) FROM vs").fetchone()[0]
            w = c.execute("SELECT COUNT(*) FROM holes WHERE gwl IS NOT NULL AND gwl != 0").fetchone()[0]
        return {"holes": h, "located": hl, "with_layers": l, "with_spt": s, "with_vs": v, "with_gwl": w}

    def clear(self):
        with self._lock, self._conn() as c:
            for t in ("holes", "layers", "spt", "vs", "perm", "strength"):
                c.execute(f"DELETE FROM {t}")

    # ── 가져오기 ──
    def import_summary(self, path, cols, enc, progress=None, cancel=None):
        """
        공별 요약표 (프로젝트명·공번·좌표·표고·시추심도·지하수위·층별 두께·층별 N치 범위).
        층 두께를 위에서부터 쌓아 지층을 만들고, 'a/b~c/d' N치 범위는 층 상·하단 근처의
        표준관입 2점(최소→최대)으로 넣는다.  좌표는 중부원점(EPSG:5186), 가로·세로가 뒤바뀐 행은 바로잡음.
        """
        import hashlib
        src = Path(path).name
        n_ok = n_bad = 0

        def g(r, k):
            i = cols.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""

        def parse_n(txt):
            out = []
            for a, b in re.findall(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", txt or ""):
                out.append((float(a), float(b)))
            return out

        with self._lock, self._conn() as c, open(path, "r", encoding=enc, errors="replace", newline="") as fp:
            rd = csv.reader(fp)
            next(rd, None)
            for r in rd:
                if cancel and cancel():
                    break
                hole, pname = g(r, "hole"), g(r, "pname")
                if not hole:
                    continue
                tag = hashlib.md5(pname.encode("utf-8")).hexdigest()[:6].upper()
                code = f"R{tag}-{hole}"
                x, y = _f(g(r, "x")), _f(g(r, "y"))
                la = lo = None
                if x is not None and y is not None:
                    if x > 380000 and y < 300000:            # 가로·세로 뒤바뀜 (동해·남해 바다로 떨어짐)
                        x, y = y, x
                    try:
                        la, lo = geo.to_wgs84(x, y, "EPSG:5186")
                    except Exception:                    # noqa: BLE001
                        la = lo = None
                    if la is None or not (32.5 < la < 39.5 and 123.5 < lo < 132.5):
                        la = lo = None
                if la is None:
                    n_bad += 1
                gw = _f(g(r, "gwl"))
                c.execute("INSERT OR REPLACE INTO holes VALUES (?,?,?,?,?,?,?,?,?)",
                          (code, pname, f"{pname} {hole} ({g(r, 'date')})", la, lo, _f(g(r, "elev")),
                           _f(g(r, "depth")), (-abs(gw) if gw else None), src))
                c.execute("DELETE FROM layers WHERE hole=?", (code,))
                c.execute("DELETE FROM spt WHERE hole=?", (code,))
                z = 0.0
                for key, nm in SUMMARY_LAYERS:
                    t = _f(g(r, key + "_t"))
                    if not t or t <= 0:
                        continue
                    ntxt = g(r, key + "_n")
                    note = f"N치 {ntxt}" if ntxt else ""
                    if key in ("연암", "보통암", "경암") and g(r, "rqd"):
                        note = f"암질지수 {g(r, 'rqd')}"
                    c.execute("INSERT INTO layers VALUES (?,?,?,?,?,?)", (code, z, z + t, nm, "", note))
                    ns = parse_n(ntxt)
                    if ns:
                        pts = [ns[0], ns[-1]] if len(ns) > 1 else [ns[0]]
                        deps = [z + min(0.5, t / 3), z + t - min(0.5, t / 3)] if len(pts) > 1 else [z + t / 2]
                        for (bl, pe), dd in zip(pts, deps):
                            c.execute("INSERT INTO spt VALUES (?,?,?,?,?)", (code, dd, bl, pe, n_value(bl, pe)))
                    z += t
                n_ok += 1
            if progress:
                progress(1.0, n_ok)
        return n_ok, f"공별 요약표 {n_ok:,}공 가져옴 (지층·N치 범위 → 표준관입 2점/층)" + (
            f", 좌표 없음 {n_bad}공" if n_bad else "")

    def fix_agg_units(self):
        """골재자원조사 주상 일부는 cm 단위 — 시추심도보다 훨씬 깊으면 1/100."""
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT hole, MAX(bot) FROM layers WHERE hole LIKE 'AGG-%' AND bot > 60 "
                             "GROUP BY hole").fetchall()
            for code, mb in rows:
                m_max = c.execute("SELECT MAX(bot) FROM layers WHERE hole=? AND bot <= 60", (code,)).fetchone()[0]
                if m_max and m_max >= 0.5 * mb / 100.0:          # m 단위 행이 따로 있으면 cm 행은 중복
                    c.execute("DELETE FROM layers WHERE hole=? AND bot > 60", (code,))
                else:
                    c.execute("UPDATE layers SET top=top/100.0, bot=bot/100.0 WHERE hole=?", (code,))

    def import_csv(self, path, kind=None, mapping=None, crs=None, progress=None, cancel=None, replace=True):
        """data.go.kr 형식 CSV 가져오기.  반환 (가져온 행 수, 메시지)"""
        headers, sample, enc = read_csv_head(path, 300)
        m = mapping or map_headers(headers)
        kind = kind or detect_kind(m)
        if not kind:
            raise ValueError("CSV 종류(시추공/지층/표준관입)를 알 수 없습니다. 열 이름을 확인하세요.")
        if kind == "summary":
            return self.import_summary(path, m["sum_cols"], enc, progress, cancel)
        if kind in ("holes", "agg_holes") and crs is None:
            xs = [_f(r[m["x"]]) for r in sample if len(r) > m["x"]]
            ys = [_f(r[m["y"]]) for r in sample if len(r) > m["y"]]
            crs = geo.guess_crs(xs, ys)
        total = max(Path(path).stat().st_size, 1)
        n_ok = n_bad = 0
        batch = []
        src = Path(path).name

        def g(r, f):
            i = m.get(f)
            return r[i].strip() if i is not None and i < len(r) else ""

        with self._lock, self._conn() as c, open(path, "r", encoding=enc, errors="replace", newline="") as fp:
            rd = csv.reader(fp)
            next(rd, None)
            seen = set()
            pnames = {}
            nbytes = 0
            for k, r in enumerate(rd):
                nbytes += sum(len(x) for x in r) + len(r) + 1
                if cancel and cancel():
                    break
                code = g(r, "hole")
                if kind == "strength":
                    smp = g(r, "sample")
                    code = smp[:-4] if len(smp) > 6 else ""   # 시료코드 = 시추공코드 + DS07 등 4자리
                if kind in ("agg_holes", "agg_layers"):
                    code = "AGG-" + g(r, "serial") if g(r, "serial") else ""
                if kind not in ("holes", "agg_holes") and not code:
                    n_bad += 1
                    continue
                if kind == "agg_holes":
                    la, lo = _f(g(r, "y")), _f(g(r, "x"))
                    if la is None or lo is None or not (32.5 < la < 39.5 and 123.5 < lo < 132.5):
                        la = lo = None
                        gm = g(r, "geom")                  # 'POINT (x y)' — 중부원점 GRS80(FN 500,000)
                        if gm.upper().startswith("POINT"):
                            try:
                                px, py = (float(t) for t in gm[gm.index("(") + 1:gm.index(")")].split()[:2])
                                la, lo = geo.to_wgs84(px, py, "EPSG:5181")
                            except Exception:          # noqa: BLE001
                                la = lo = None
                    if la is None or not (32.5 < la < 39.5 and 123.5 < lo < 132.5):
                        n_bad += 1
                        continue
                    batch.append(("H", (code, "골재자원조사", (g(r, "site") + " " + g(r, "addr")).strip(), la, lo,
                                        None, _f(g(r, "mdepth")), None, src)))
                elif kind == "agg_layers":
                    if replace and code not in seen:
                        seen.add(code)
                        batch.append(("DL", (code,)))
                    nm = g(r, "pattern")
                    batch.append(("L", (code, _f(g(r, "ftop")), _f(g(r, "fbot")),
                                        "" if nm.startswith("#") else nm, "", "골재자원조사 패턴")))
                elif kind == "perm":
                    if replace and code not in seen:
                        seen.add(code)
                        batch.append(("DP", (code,)))
                    batch.append(("P", (code, _f(g(r, "ttop")), _f(g(r, "tbot")), _f(g(r, "kperm")))))
                elif kind == "strength":
                    if replace and code not in seen:
                        seen.add(code)
                        batch.append(("DT", (code,)))
                    batch.append(("T", (code, g(r, "sample"), g(r, "ttype"), _f(g(r, "phi")), _f(g(r, "coh")))))
                elif kind == "downhole":
                    if replace and code not in seen:
                        seen.add(code)
                        batch.append(("DV", (code,)))
                    batch.append(("V", (code, _f(g(r, "top")), _f(g(r, "bot")), _f(g(r, "vp")), _f(g(r, "vs")),
                                        g(r, "lname"))))
                elif kind == "holes":
                    x, y = _f(g(r, "x")), _f(g(r, "y"))
                    lat = lon = None
                    if x is not None and y is not None:
                        try:
                            if crs == "WGS84" and not (124 < x < 132) and (124 < y < 132):
                                x, y = y, x                 # 경도·위도 열이 바뀐 경우
                            lat, lon = geo.to_wgs84(x, y, crs)
                            if not (32.5 < lat < 39.5 and 123.5 < lon < 132.5):
                                lat = lon = None
                        except Exception:              # noqa: BLE001
                            lat = lon = None
                    if not code:
                        code = f"{src}:{k}"
                    proj = g(r, "project")
                    nm = g(r, "name") or g(r, "pname")
                    batch.append(("H", (code, proj, nm, lat, lon, _f(g(r, "elev")), _f(g(r, "depth")),
                                        _f(g(r, "gwl")), src)))
                    if lat is None:
                        n_bad += 1
                elif kind == "layers":
                    if replace and code not in seen:
                        seen.add(code)
                        batch.append(("DL", (code,)))
                    batch.append(("L", (code, _f(g(r, "top")), _f(g(r, "bot")), g(r, "lname"),
                                        g(r, "uscs"), g(r, "descr"))))
                else:
                    if replace and code not in seen:
                        seen.add(code)
                        batch.append(("DS", (code,)))
                    raw_b = g(r, "blows")
                    b, p_in = parse_blows(raw_b)
                    p = _f(g(r, "pen")) or p_in
                    batch.append(("S", (code, _f(g(r, "sdepth")), b, p, n_value(b, p))))
                    pn = g(r, "pname")
                    if pn and code not in pnames:
                        pnames[code] = pn
                n_ok += 1
                if len(batch) >= 5000:
                    self._flush(c, batch)
                    batch.clear()
                    if progress:
                        progress(min(nbytes / total, 1.0), n_ok)
            self._flush(c, batch)
            if pnames:                                   # 사업명이 비어 있는 시추공에 프로젝트명 채우기
                c.executemany("UPDATE holes SET project=? WHERE code=? AND (project IS NULL OR project='')",
                              [(v, k) for k, v in pnames.items()])
            c.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"import:{src}", f"{kind}:{n_ok}"))
        msg = f"{KIND_LABEL[kind]} {n_ok:,}행 가져옴" + (f" (좌표계 {crs})" if kind == "holes" else "")
        if kind == "agg_layers":
            self.fix_agg_units()
        if n_bad:
            msg += f", 좌표/코드 없는 행 {n_bad:,}"
        return n_ok, msg

    @staticmethod
    def _flush(c, batch):
        for typ, row in batch:
            if typ == "H":
                c.execute("INSERT OR REPLACE INTO holes VALUES (?,?,?,?,?,?,?,?,?)", row)
            elif typ == "L":
                c.execute("INSERT INTO layers VALUES (?,?,?,?,?,?)", row)
            elif typ == "S":
                c.execute("INSERT INTO spt VALUES (?,?,?,?,?)", row)
            elif typ == "DL":
                c.execute("DELETE FROM layers WHERE hole=?", row)
            elif typ == "DS":
                c.execute("DELETE FROM spt WHERE hole=?", row)
            elif typ == "P":
                c.execute("INSERT INTO perm VALUES (?,?,?,?)", row)
            elif typ == "DP":
                c.execute("DELETE FROM perm WHERE hole=?", row)
            elif typ == "T":
                c.execute("INSERT INTO strength VALUES (?,?,?,?,?)", row)
            elif typ == "DT":
                c.execute("DELETE FROM strength WHERE hole=?", row)
            elif typ == "V":
                c.execute("INSERT INTO vs VALUES (?,?,?,?,?,?)", row)
            elif typ == "DV":
                c.execute("DELETE FROM vs WHERE hole=?", row)

    # ── 직접 입력 ──
    def save_hole(self, hole, layers, spts):
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO holes VALUES (?,?,?,?,?,?,?,?,?)",
                      (hole["code"], hole.get("project", ""), hole.get("name", ""), hole.get("lat"),
                       hole.get("lon"), hole.get("elev"), hole.get("depth"), hole.get("gwl"),
                       hole.get("source", "직접입력")))
            c.execute("DELETE FROM layers WHERE hole=?", (hole["code"],))
            c.execute("DELETE FROM spt WHERE hole=?", (hole["code"],))
            for L in layers:
                c.execute("INSERT INTO layers VALUES (?,?,?,?,?,?)",
                          (hole["code"], L["top"], L["bot"], L.get("name", ""), L.get("uscs", ""), L.get("descr", "")))
            for s in spts:
                c.execute("INSERT INTO spt VALUES (?,?,?,?,?)",
                          (hole["code"], s["depth"], s.get("blows"), s.get("pen"),
                           s.get("n") if s.get("n") is not None else n_value(s.get("blows"), s.get("pen"))))

    def delete_hole(self, code):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM holes WHERE code=?", (code,))
            c.execute("DELETE FROM layers WHERE hole=?", (code,))
            c.execute("DELETE FROM spt WHERE hole=?", (code,))

    # ── 검색 ──
    def search(self, lat, lon, radius_m, limit=500):
        dlat = radius_m / 111320.0
        dlon = radius_m / (111320.0 * max(math.cos(math.radians(lat)), 0.2))
        with self._conn() as c:
            rows = c.execute(
                "SELECT code, project, name, lat, lon, elev, depth, gwl, source FROM holes "
                "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                (lat - dlat, lat + dlat, lon - dlon, lon + dlon)).fetchall()
        out = []
        for r in rows:
            d = geo.haversine(lat, lon, r[3], r[4])
            if d <= radius_m:
                out.append({"code": r[0], "project": r[1] or "", "name": r[2] or "", "lat": r[3],
                            "lon": r[4], "elev": r[5], "depth": r[6], "gwl": r[7], "source": r[8] or "",
                            "dist": d, "brg": geo.bearing(lat, lon, r[3], r[4])})
        out.sort(key=lambda h: h["dist"])
        return out[:limit]

    def tests(self, codes):
        """반경 안 공들의 현장투수시험·전단강도시험."""
        codes = list(codes)
        P, T = [], []
        with self._conn() as c:
            for i in range(0, len(codes), 500):
                q = ",".join("?" * len(codes[i:i + 500]))
                P += c.execute(f"SELECT hole, top, bot, k FROM perm WHERE hole IN ({q})", codes[i:i + 500]).fetchall()
                T += c.execute(f"SELECT hole, sample, typ, phi, c FROM strength WHERE hole IN ({q})",
                               codes[i:i + 500]).fetchall()
        return ([{"hole": h, "top": a, "bot": b, "k": k} for h, a, b, k in P if k],
                [{"hole": h, "sample": s_, "typ": t or "", "phi": f, "c": cc} for h, s_, t, f, cc in T])

    def vs_detail(self, code):
        with self._conn() as c:
            R = c.execute("SELECT top, bot, vp, vs, layer FROM vs WHERE hole=? ORDER BY top", (code,)).fetchall()
        return [{"top": a, "bot": b, "vp": p, "vs": v, "layer": n or ""} for a, b, p, v, n in R
                if a is not None and b is not None and v]

    def detail(self, code):
        with self._conn() as c:
            L = c.execute("SELECT top, bot, name, uscs, descr FROM layers WHERE hole=? ORDER BY top",
                          (code,)).fetchall()
            S = c.execute("SELECT depth, blows, pen, n FROM spt WHERE hole=? ORDER BY depth",
                          (code,)).fetchall()
        layers = [{"top": a, "bot": b, "name": n or "", "uscs": u or "", "descr": d or ""}
                  for a, b, n, u, d in L if a is not None and b is not None and b > a]
        spts = [{"depth": d, "blows": b, "pen": p, "n": n} for d, b, p, n in S if d is not None]
        return layers, spts


# ─────────────────────────────────────────────────────────────
#  지층 분류 · 전단파속도 · 지반분류
# ─────────────────────────────────────────────────────────────
_ORDER = ("rock_hard", "rock_soft", "rock_weathered", "soil_weathered", "fill", "gravel", "clay", "sand", "sediment")


def _kw_class(text):
    t = (text or "").lower()
    for cls in _ORDER:
        if any(kw.lower() in t for kw in K.LAYER_KEYWORDS[cls]):
            return cls
    return None


def _uscs_class(uscs):
    u = (uscs or "").strip().upper()
    if not u or len(u) > 3:
        return None
    if u in ("PT",) or u[:1] in ("C", "M", "O"):
        return "clay"
    if u[:1] == "S":
        return "sand"
    if u[:1] == "G":
        return "gravel"
    return None


def classify_layer(name, uscs="", descr=""):
    """층 이름 → (암반·풍화·매립이면 그대로) → USCS → 이름의 토질 → 설명 순으로 판정."""
    c = _kw_class(name)
    if c in ("rock_hard", "rock_soft", "rock_weathered", "soil_weathered", "fill"):
        return c
    u = _uscs_class(uscs)
    if u and (c is None or c == "sediment"):
        return u
    if c:
        return c
    if u:
        return u
    return _kw_class(uscs) or _kw_class((descr or "")[:40]) or "unknown"


def vs_from_n(n, cls, corr="imai"):
    if n is None or n <= 0:
        return None
    if corr == "jra":
        return (100.0 if cls == "clay" else 80.0) * n ** (1.0 / 3.0)
    return 97.0 * n ** 0.314


def bedrock_classes(rule="soft"):
    return ("rock_soft", "rock_hard") if rule == "soft" else ("rock_weathered", "rock_soft", "rock_hard")


def analyze_hole(hole, layers, spts, settings=None, vs_meas=None):
    """한 시추공: 층 분류, Vs, 기반암 깊이, Vs,soil, 지반분류."""
    s = settings or geo.load_settings()
    corr = s.get("vs_corr", "imai")
    rocks = bedrock_classes(s.get("bedrock_rule", "soft"))
    defaults = dict(K.LAYER_DEFAULT_VS)
    defaults["rock_weathered"] = float(s.get("weathered_rock_vs", defaults["rock_weathered"]))

    L = []
    for ly in sorted(layers, key=lambda q: q["top"]):
        cls = classify_layer(ly["name"], ly.get("uscs", ""), ly.get("descr", ""))
        ns = [sp["n"] for sp in spts if sp.get("n") is not None and ly["top"] <= sp["depth"] <= ly["bot"]]
        vss = [vs_from_n(n, cls, corr) for n in ns]
        vss = [v for v in vss if v]
        meas = []
        for v in vs_meas or []:
            ov = min(v["bot"], ly["bot"]) - max(v["top"], ly["top"])
            if ov > 0 and v.get("vs"):
                meas.append((ov, v["vs"]))
        if meas:
            tw = sum(t for t, _ in meas)
            vs = tw / sum(t / v for t, v in meas)          # 두께 가중 조화평균
            src = f"하향식 탄성파 실측 {len(meas)}구간"
        elif cls in ("rock_soft", "rock_hard"):
            vs = max(defaults[cls], K.BEDROCK_VS)
            src = "암반 기본값"
        elif vss:
            vs = sum(vss) / len(vss)
            src = f"N {len(ns)}개 평균"
        else:
            vs = defaults.get(cls, defaults["unknown"])
            src = "층 기본값"
        L.append(dict(ly, cls=cls, n_list=ns, vs=vs, vs_src=src))

    depth = max([hole.get("depth") or 0.0] + [q["bot"] for q in L] + [sp["depth"] for sp in spts] + [0.0])
    rock_top = next((q["top"] for q in L if q["cls"] in rocks), None)
    rock_found = rock_top is not None
    res = {"hole": hole, "layers": L, "spts": spts, "depth": depth,
           "rock_depth": rock_top, "rock_found": rock_found, "vs_soil": None, "site": "", "reason": ""}
    if not L:
        res["reason"] = "지층정보 없음"
        return res
    if rock_found and rock_top < K.ROCK_DEPTH_S1_BUILDING:
        res["site"], res["reason"] = seismic.classify_site(rock_top, None, True, depth)
        return res
    lim = min(rock_top if rock_found else depth, K.TOP_DEPTH_FOR_VS)
    if lim <= 0:
        res["reason"] = "토층 두께 0"
        return res
    # 0 ~ lim 구간 조화평균 (층 사이 빈 구간은 가까운 층 Vs)
    sum_t = 0.0
    z = 0.0
    for q in L:
        if q["top"] >= lim:
            break
        if q["cls"] in rocks:
            break
        if q["top"] > z:                                 # 빈 구간
            sum_t += (min(q["top"], lim) - z) / q["vs"]
            z = min(q["top"], lim)
        b = min(q["bot"], lim)
        if b > z:
            sum_t += (b - z) / q["vs"]
            z = b
    if z < lim and L:                                    # 마지막 층 아래 남은 구간
        last = [q for q in L if q["cls"] not in rocks]
        v = last[-1]["vs"] if last else defaults["unknown"]
        sum_t += (lim - z) / v
        z = lim
    vs_soil = lim / sum_t if sum_t > 0 else None
    res["vs_soil"] = vs_soil
    res["vs_depth"] = lim
    res["site"], res["reason"] = seismic.classify_site(rock_top, vs_soil, rock_found, depth)
    return res


def summarize(results, S, mode="max"):
    """
    여러 시추공 결과 → 예상 지반분류와 대표 증폭계수.
    mode: 'max' 설계상 가장 불리한 값 / 'mean' 평균 (KDS 41 17 00 4.2.3 ①)
    """
    ok = [r for r in results if r.get("site") in K.FA_TABLE and r.get("use", True)]
    counts = {}
    for r in ok:
        counts[r["site"]] = counts.get(r["site"], 0) + 1
    out = {"n_total": len(results), "n_ok": len(ok), "counts": counts}
    if not ok:
        out["text"] = "판정 가능한 시추공이 없습니다."
        return out
    amps = []
    for r in ok:
        fa, fv, _ = seismic.amplification(r["site"], S, r.get("rock_depth"), r.get("vs_soil"), r.get("rock_found"))
        r["Fa"], r["Fv"] = fa, fv
        amps.append((fa, fv, r))
    major = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    if mode == "mean":
        fa = sum(a[0] for a in amps) / len(amps)
        fv = sum(a[1] for a in amps) / len(amps)
        label = f"평균 ({len(amps)}공)"
    else:
        fa_r = max(amps, key=lambda a: a[0])
        fv_r = max(amps, key=lambda a: a[1])
        fa, fv = fa_r[0], fv_r[1]
        label = f"불리측 — Fa {fa_r[2]['site']}({fa_r[2]['hole']['code']}), Fv {fv_r[2]['site']}({fv_r[2]['hole']['code']})"
    worst = max(amps, key=lambda a: S * a[1])[2]["site"]
    vs = [r["vs_soil"] for r in ok if r.get("vs_soil")]
    rd = [r["rock_depth"] for r in ok if r.get("rock_found")]
    out.update(major=major, worst=worst, Fa=fa, Fv=fv, label=label,
               vs_range=(min(vs), max(vs)) if vs else None,
               rock_range=(min(rd), max(rd)) if rd else None)
    cs = ", ".join(f"{k} {v}공" for k, v in sorted(counts.items()))
    txt = [f"판정 가능 {len(ok)}공 / 검색 {len(results)}공 — {cs}",
           f"가장 많은 분류: {major}" + ("" if worst == major else f"  ·  가장 불리한 분류: {worst}")]
    if out["rock_range"]:
        txt.append(f"기반암 깊이 {out['rock_range'][0]:.1f} ~ {out['rock_range'][1]:.1f} m")
    if out["vs_range"]:
        txt.append(f"Vs,soil {out['vs_range'][0]:.0f} ~ {out['vs_range'][1]:.0f} m/s")
    txt.append(f"대표 증폭계수 Fa {fa:.3f}, Fv {fv:.3f} — {label}")
    # 현재 위치 추정 — 거리 역제곱 가중 (가까운 시추공일수록 크게)
    idw = site_estimate(ok)
    if idw:
        out["idw"] = idw
        txt.append(f"현재 위치 추정 (거리가중 {idw['n']}공): 기반암 {idw['rock_txt']}, "
                   f"Vs,soil ≈ {idw['vs']:.0f} m/s → {idw['site']}")
    out["text"] = "\n".join(txt)
    out["predicted"] = worst if mode == "max" else major
    return out


def site_estimate(results, power=2.0, min_d=20.0):
    """
    반경 안 시추공을 거리 역제곱으로 가중해 건설지점의 기반암 깊이·Vs,soil 을 추정하고 지반분류.
    기반암을 못 만난 공은 시추 깊이를 하한으로 보고 '이상'으로 표시.
    """
    rows = [r for r in results if r.get("vs_soil") and r.get("hole", {}).get("dist") is not None]
    if not rows:
        return None
    ws = [1.0 / max(r["hole"]["dist"], min_d) ** power for r in rows]
    W = sum(ws)
    vs = sum(w * r["vs_soil"] for w, r in zip(ws, rows)) / W
    found = [(w, r) for w, r in zip(ws, rows) if r.get("rock_found") and r.get("rock_depth") is not None]
    frac_found = sum(w for w, _ in found) / W
    if found and frac_found >= 0.5:
        rd = sum(w * r["rock_depth"] for w, r in found) / sum(w for w, _ in found)
        site = seismic.classify_site(rd, vs, True)
        rock_txt = f"≈ {rd:.1f} m"
    else:
        deep = [r.get("depth") or r.get("rock_depth") or 0 for r in rows]
        rd = max(deep) if deep else None
        site = seismic.classify_site(rd or 30.0, vs, False, hole_depth=rd)
        rock_txt = f"> {rd:.0f} m (미확인)" if rd else "미확인"
    if isinstance(site, (tuple, list)):
        site = site[0]
    return {"n": len(rows), "vs": vs, "rock_depth": rd, "rock_found": frac_found >= 0.5,
            "site": site, "rock_txt": rock_txt}
