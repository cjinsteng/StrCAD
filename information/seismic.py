"""
information/seismic.py — 지진하중 변수 (KDS 41 17 00:2022, KDS 17 10 00)

    S   : 지진구역계수 Z × 위험도계수 2.0  또는 국가지진위험지도 (Z·I 의 80% 이상)
    SDS = S × 2.5 × Fa × 2/3               (4.2-4)
    SD1 = S × Fv × 2/3                     (4.2-5)
"""
from . import kds_data as K

TL = 5.0                    # 장주기 천이주기 (s)

SIDO_ALIASES = {
    "서울": ("서울",), "부산": ("부산",), "대구": ("대구",), "인천": ("인천",), "광주": ("광주",),
    "대전": ("대전",), "울산": ("울산",), "세종": ("세종",), "경기": ("경기",), "강원": ("강원",),
    "충북": ("충북", "충청북"), "충남": ("충남", "충청남"), "전북": ("전북", "전라북"),
    "전남": ("전남", "전라남"), "경북": ("경북", "경상북"), "경남": ("경남", "경상남"), "제주": ("제주",),
}
METRO = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종")


def parse_sido(text):
    """주소 문자열에서 시·도 이름(짧은 형식)."""
    t = (text or "").replace(" ", "")
    for key, keys in SIDO_ALIASES.items():
        for k in keys:
            if t.startswith(k.replace(" ", "")):
                return key
    for key, keys in SIDO_ALIASES.items():        # 앞에 없으면 아무 곳에서나
        for k in keys:
            if k.replace(" ", "") in t:
                return key
    return ""


def seismic_zone(address="", sido="", sigungu=""):
    """
    KDS 17 10 00 표 4.2-1 지진구역.
    반환 (구역 'I'/'II'/'', 근거 문자열)
    """
    sd = sido or parse_sido(address)
    if not sd:
        return "", "주소에서 시·도를 찾지 못함"
    if sd in METRO:
        return "I", f"{sd} (시) → 지진구역 I"
    if sd == "제주":
        return "II", "제주 → 지진구역 II"
    if sd == "강원":
        src = (sigungu or "") + " " + (address or "")
        for nm in K.GANGWON_NORTH:
            if nm in src:
                return "II", f"강원 북부({nm}) → 지진구역 II"
        for nm in K.GANGWON_SOUTH:
            if nm in src:
                return "I", f"강원 남부({nm}) → 지진구역 I"
        return "", "강원 — 시·군을 확인하세요 (남부 I / 북부 II)"
    return "I", f"{sd} → 지진구역 I"


def s_by_zone(zone):
    z = K.SEISMIC_ZONE_Z.get(zone)
    return None if z is None else z * K.RISK_FACTOR_2400


def effective_s(zone, s_map=None, use_map=False):
    """설계에 쓸 S 와 근거."""
    s_zone = s_by_zone(zone)
    out = {"zone": zone, "Z": K.SEISMIC_ZONE_Z.get(zone), "S_zone": s_zone, "S_map": s_map,
           "S_min": None if s_zone is None else s_zone * K.HAZARD_MAP_MIN_RATIO}
    if use_map and s_map:
        s = s_map
        note = "국가지진위험지도"
        if s_zone is not None and s < out["S_min"]:
            s = out["S_min"]
            note = f"위험지도 값 {s_map:.3f}g < 하한 {out['S_min']:.3f}g → 하한 적용"
        out.update(S=s, method="map", note=note)
    else:
        out.update(S=s_zone, method="zone",
                   note="" if s_zone is not None else "지진구역 미정")
    return out


def _interp3(vals, s):
    xs = K.FA_S_POINTS
    if s <= xs[0]:
        return vals[0]
    if s >= xs[-1]:
        return vals[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= s <= xs[i + 1]:
            t = (s - xs[i]) / (xs[i + 1] - xs[i])
            return vals[i] + t * (vals[i + 1] - vals[i])
    return vals[-1]


def classify_site(rock_depth, vs_soil, rock_found=True, hole_depth=None, building=True):
    """
    지반분류.  rock_depth: 기반암 깊이 (m), vs_soil: 토층 평균 전단파속도 (m/s)
    rock_found=False 이면 기반암이 시추심도(hole_depth)보다 깊다.
    반환 (분류 'S1'~'S5' 또는 '', 설명)
    """
    s1_lim = K.ROCK_DEPTH_S1_BUILDING if building else K.ROCK_DEPTH_S1_GENERAL
    if rock_found and rock_depth is not None and rock_depth < s1_lim:
        return "S1", f"기반암 깊이 {rock_depth:.1f}m < {s1_lim:.0f}m"
    if vs_soil is None:
        return "", "토층 전단파속도 없음"
    if rock_found:
        H = rock_depth
        deep = H > K.SHALLOW_LIMIT
    else:
        if hole_depth is None or hole_depth <= K.SHALLOW_LIMIT:
            return "", f"시추심도 {hole_depth or 0:.1f}m 안에 기반암 없음 — 판정 불가(심도 부족)"
        H = None
        deep = True
    hs = f"{H:.1f}m" if H is not None else f"> {hole_depth:.1f}m"
    if deep:
        if vs_soil >= K.VS_LIMIT_DEEP:
            return "S4", f"기반암 {hs} > 20m, Vs,soil {vs_soil:.0f} ≥ 180"
        return "S5", f"기반암 {hs} > 20m, Vs,soil {vs_soil:.0f} < 180"
    if vs_soil >= K.VS_LIMIT_SHALLOW:
        return "S2", f"기반암 {hs} ≤ 20m, Vs,soil {vs_soil:.0f} ≥ 260"
    return "S3", f"기반암 {hs} ≤ 20m, Vs,soil {vs_soil:.0f} < 260"


def amplification(site, s, rock_depth=None, vs_soil=None, rock_found=True):
    """표 4.2-1·4.2-2 + 4.2.2(2)(3) 보정."""
    if site not in K.FA_TABLE:
        return None, None, []
    fa = _interp3(K.FA_TABLE[site], s)
    fv = _interp3(K.FV_TABLE[site], s)
    notes = []
    deep = (not rock_found) or (rock_depth is not None and rock_depth > K.SHALLOW_LIMIT)
    if deep and vs_soil is not None and vs_soil >= K.FV_DEEP_STIFF_VS:
        fv *= K.FV_DEEP_STIFF_FACTOR
        notes.append("4.2.2(2) H>20m, Vs≥360 → Fv×0.8")
    if site == "S5" and not rock_found:
        fa *= K.S5_UNKNOWN_DEPTH_FACTOR
        fv *= K.S5_UNKNOWN_DEPTH_FACTOR
        notes.append("4.2.2(3) S5·기반암 깊이 불분명 → Fa·Fv×1.1")
    return fa, fv, notes


def design_spectrum(S, fa, fv):
    sds = S * 2.5 * fa * 2.0 / 3.0
    sd1 = S * fv * 2.0 / 3.0
    ts = sd1 / sds if sds > 0 else 0.0
    t0 = 0.2 * ts
    return {"SDS": sds, "SD1": sd1, "T0": t0, "Ts": ts, "TL": TL}


def sa_at(T, sp):
    sds, sd1, t0, ts = sp["SDS"], sp["SD1"], sp["T0"], sp["Ts"]
    if T <= t0:
        return 0.6 * (sds / t0) * T + 0.4 * sds if t0 > 0 else sds
    if T <= ts:
        return sds
    if T <= TL:
        return sd1 / T
    return sd1 * TL / (T * T)


def seismic_grade(importance):
    return K.SEISMIC_GRADE.get(str(importance), ("II", 1.0))


def design_category(sds, sd1, grade):
    col = 1 if grade == "특" else 2
    c1 = next(row[col] for row in K.SDC_SDS if sds >= row[0])
    c2 = next(row[col] for row in K.SDC_SD1 if sd1 >= row[0])
    return max(c1, c2), c1, c2


def evaluate(zone, importance, site, s_map=None, use_map=False,
             rock_depth=None, vs_soil=None, rock_found=True, amp=None):
    """
    지진 변수 일괄 계산.
    amp: 시추공 여러 개에서 구한 대표 증폭계수 (fa, fv, 설명) — 주면 site 표 값 대신 사용
    """
    s_info = effective_s(zone, s_map, use_map)
    grade, ie = seismic_grade(importance)
    out = {"s": s_info, "grade": grade, "IE": ie, "site": site}
    S = s_info.get("S")
    if S is None or (site not in K.FA_TABLE and not amp):
        out["ok"] = False
        return out
    if amp:
        fa, fv = amp[0], amp[1]
        notes = [amp[2]] if len(amp) > 2 and amp[2] else []
    else:
        fa, fv, notes = amplification(site, S, rock_depth, vs_soil, rock_found)
    sp = design_spectrum(S, fa, fv)
    sdc, c1, c2 = design_category(sp["SDS"], sp["SD1"], grade)
    out.update(ok=True, Fa=fa, Fv=fv, amp_notes=notes, spectrum=sp, SDC=sdc, SDC_SDS=c1, SDC_SD1=c2)
    return out
