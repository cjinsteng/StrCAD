"""
information/wind.py — 풍하중 설계풍속·속도압·지형계수 (KDS 41 12 00:2022 5.5)

    VH = V0 · Kd · Kzr · Kzt · Iw          (5.5-2)
    qH = ½ · ρ · VH²                        (5.5-1)
    Kzt = 1 + Kh · L · θ′ / (1 + 3.7·Iz)   (5.5-3)
"""
import math

from . import kds_data as K


# ─────────────────────────────────────────────────────────────
#  풍속고도분포계수 · 난류강도 · 중요도계수
# ─────────────────────────────────────────────────────────────
def kzr(z, cat):
    """표 5.5-2 평탄지 풍속고도분포계수."""
    r = K.ROUGHNESS[cat]
    z = max(float(z), 0.0)
    if z <= r["zb"]:
        return K.KZR_LOW[cat]
    z = min(z, r["zg"])
    return K.KZR_COEF[cat] * z ** r["alpha"]


def iz(z, cat):
    """식 (5.5-3.a) 난류강도  Iz = 0.1·(z/zg)^(−α−0.05),  z < zb 이면 zb 값."""
    r = K.ROUGHNESS[cat]
    z = min(max(float(z), r["zb"]), r["zg"])
    return 0.1 * (z / r["zg"]) ** (-r["alpha"] - 0.05)


def is_supertall(floors=0, height=0.0):
    return (floors or 0) >= K.SUPERTALL_FLOORS or (height or 0.0) >= K.SUPERTALL_HEIGHT


def iw(importance, floors=0, height=0.0):
    """표 5.5-5 중요도계수 (초고층: 50층 이상 또는 200m 이상)."""
    if is_supertall(floors, height):
        return K.IW["초고층"]
    return K.IW.get(str(importance), 1.0)


def velocity_pressure(v):
    return 0.5 * K.AIR_DENSITY * v * v          # N/m²


def design_wind(v0, cat, height, importance, kzt=1.0, kd=K.KD_DEFAULT, floors=0):
    """기준높이 H에서의 설계풍속·속도압."""
    k_zr = kzr(height, cat)
    i_w = iw(importance, floors, height)
    vh = v0 * kd * k_zr * kzt * i_w
    return {"V0": v0, "Kd": kd, "Kzr": k_zr, "Kzt": kzt, "Iw": i_w,
            "VH": vh, "qH": velocity_pressure(vh), "IH": iz(height, cat),
            "supertall": is_supertall(floors, height)}


def pressure_profile(v0, cat, height, importance, kzt_at=None, kd=K.KD_DEFAULT, floors=0, step=None):
    """높이별 Vz·qz 표.  kzt_at(z) 가 없으면 Kzt=1."""
    height = float(height)
    if step is None:
        step = 3.0 if height <= 60 else (5.0 if height <= 150 else 10.0)
    zs, z = [], 0.0
    while z < height - 1e-6:
        z += step
        zs.append(min(z, height))
    i_w = iw(importance, floors, height)
    rows = []
    for z in zs:
        kt = kzt_at(z) if kzt_at else 1.0
        vz = v0 * kd * kzr(z, cat) * kt * i_w
        rows.append({"z": z, "Kzr": kzr(z, cat), "Kzt": kt, "Vz": vz,
                     "qz": velocity_pressure(vz), "Iz": iz(z, cat)})
    return rows


# ─────────────────────────────────────────────────────────────
#  지형계수 (식 5.5-3)
# ─────────────────────────────────────────────────────────────
def kzt_from_params(kind, H, Lu, x, z, cat, theta_d=None):
    """
    kind   : "hill"(언덕·산) / "escarpment"(경사지) / "flat"
    H      : 정점높이 (m) — 풍상측 지표에서 정점까지
    Lu     : 정점에서 H/2 지점까지 풍상측 수평거리 (m)
    x      : 정점에서 건설지점까지 수평거리 (m, 풍상측 −, 풍하측 +)
    z      : 국지 지표면에서의 높이 (m)
    theta_d: 풍하측 평균경사 (언덕·산 형상계수용)
    """
    out = {"kind": kind, "H": H, "Lu": Lu, "x": x, "z": z, "Kzt": 1.0, "in_range": False, "note": ""}
    if kind == "flat" or not H or H <= 0 or not Lu or Lu <= 0:
        out["note"] = "평탄지 — Kzt = 1.0"
        return out
    rng = K.KZT_RANGE[kind]
    side = "up" if x < 0 else "down"
    a, b = rng[side]
    lim = max(a * Lu, b * H)
    out["range"] = lim
    out["side"] = side
    if abs(x) > lim:
        out["note"] = f"적용범위 밖 (|x|={abs(x):.0f}m > {lim:.0f}m) — Kzt = 1.0"
        return out
    out["in_range"] = True
    theta_u = H / (2.0 * Lu)
    theta_p = min(theta_u, K.KZT_THETA_MAX)
    if kind == "escarpment":
        kh = 1.4
    else:
        td = theta_d if theta_d is not None else theta_u
        kh = min(1.4 + 3.6 * (td - 0.05), 3.2)
        kh = max(kh, 0.0)
    if side == "up":
        lu_eff = max(Lu, H / (2.0 * K.KZT_THETA_MAX))          # θu > 0.3 이면 Lu = H/0.6
        loc = 1.0 - abs(x) / (K.KZT_K_UP * lu_eff)
        lstar = lu_eff
    else:
        c1, c2 = K.KZT_LSTAR[kind]
        lstar = max(c1 * Lu, c2 * H)
        loc = 1.0 - abs(x) / (K.KZT_K_UP * lstar)
    loc = max(loc, 0.0)
    if K.KZT_HEIGHT_DECAY_ETA:
        loc *= math.exp(-K.KZT_HEIGHT_DECAY_ETA * z / Lu)
    i_z = iz(z, cat)
    kzt = 1.0 + kh * loc * theta_p / (1.0 + 3.7 * i_z)
    out.update(theta_u=theta_u, theta_p=theta_p, theta_d=theta_d, Kh=kh, L=loc, Lstar=lstar,
               Iz=i_z, Kzt=kzt, note="")
    return out


def analyze_profile(prof, z, cat, search=2000.0, base_win=1500.0, h_min=2.0, site_not_peak=False):
    """
    한 풍향의 지형단면에서 지형계수 산정.
    prof : [(s, elev)]  s = 건설지점 기준 바람방향 거리 (m) — 풍상측 −, 풍하측 +, s=0 이 건설지점
    site_not_peak : 건설지점 주변(다른 풍향)에 더 높은 곳이 있으면 True — 건설지점 자체를 정점으로 보지 않음
                    (사면 중턱을 지나는 단면에서 건설지점이 가짜 정점으로 잡히는 것 방지)
    반환 : 가장 큰 Kzt 를 주는 정점에 대한 kzt_from_params 결과 + 단면 정보
    """
    prof = sorted((float(s), float(e)) for s, e in prof if e is not None)
    if len(prof) < 5:
        return {"Kzt": 1.0, "kind": "flat", "note": "지형자료 부족 — Kzt = 1.0"}
    ss = [p[0] for p in prof]
    es = [p[1] for p in prof]
    n = len(prof)
    i0 = min(range(n), key=lambda i: abs(ss[i]))
    step = max((ss[-1] - ss[0]) / max(n - 1, 1), 1.0)
    # 정점 후보 ① 국부 최대점 (DEM 해상도 90m 를 고려해 ±90m 창)
    w = max(2, int(round(90.0 / step)))
    cand = set()
    near = 1.5 * w * step
    for i in range(n):
        if abs(ss[i]) > search or (site_not_peak and abs(ss[i]) <= near):
            continue
        lo, hi = max(0, i - w), min(n, i + w + 1)
        if es[i] >= max(es[lo:hi]) and es[i] > min(es[lo:hi]):
            cand.add(i)
    # 정점 후보 ② 경사지 어깨 — 풍상측은 가파르고 풍하측은 완만해지는 점
    wb = max(2, int(round(150.0 / step)))
    for i in range(wb, n - wb):
        if abs(ss[i]) > search or (site_not_peak and abs(ss[i]) <= near):
            continue
        up = (es[i] - es[i - wb]) / (ss[i] - ss[i - wb])
        dn = (es[i + wb] - es[i]) / (ss[i + wb] - ss[i])
        if up >= 0.05 and abs(dn) <= 0.25 * up and es[i] - es[i - wb] >= h_min:
            if not any(abs(i - j) <= wb for j in cand):
                cand.add(i)
    best = None                     # 가장 큰 Kzt
    biggest = None                  # Kzt=1 이라도 가장 큰 지형 (표시용)
    for ic in cand:
        sc, ec = ss[ic], es[ic]
        up = [i for i in range(ic + 1) if ss[i] >= sc - base_win]
        if not up:
            continue
        eb = min(es[i] for i in up)
        H = ec - eb
        if H < h_min:
            continue
        half = ec - H / 2.0
        Lu = None
        for i in range(ic, -1, -1):                  # 정점에서 풍상측으로
            if es[i] <= half:
                if i < ic and es[i + 1] != es[i]:     # 직선보간
                    t = (half - es[i]) / (es[i + 1] - es[i])
                    Lu = sc - (ss[i] + t * (ss[i + 1] - ss[i]))
                else:
                    Lu = sc - ss[i]
                break
        if not Lu or Lu <= 0:
            continue
        # 풍하측: H/2 아래로 내려가는 지점이 있으면 언덕·산, 없으면 경사지
        # 풍하측 평균경사 θd — 표 5.5-4 그림: 정점에서 지표면까지 직선거리 5H 인 점까지의 경사
        #   θd ≤ 0.05 → 경사지, 그 밖 → 언덕·산
        theta_d = None
        Ld = None
        for i in range(ic + 1, n):
            dxs = ss[i] - sc
            if math.hypot(dxs, ec - es[i]) >= 5.0 * H:
                theta_d = max((ec - es[i]) / max(dxs, 1.0), 0.0)
                Ld = dxs
                break
        if theta_d is None:
            # 단면이 5H 까지 닿지 않음 → 있는 데까지로 판단 (끝까지 거의 평평하면 경사지)
            if ss[-1] - sc > 2.0 * H:
                theta_d = max((ec - es[-1]) / (ss[-1] - sc), 0.0)
                Ld = ss[-1] - sc
            else:
                theta_d = H / (2.0 * Lu)               # 판단 불가 → 풍상측 경사와 같게 (언덕)
        kind = "escarpment" if theta_d <= 0.05 else "hill"
        x = 0.0 - sc
        r = kzt_from_params(kind, H, Lu, x, z, cat, theta_d)
        r.update(crest_s=sc, crest_elev=ec, base_elev=eb, site_elev=es[i0], Ld=Ld)
        if best is None or r["Kzt"] > best["Kzt"]:
            best = r
        if biggest is None or H > biggest["H"]:
            biggest = r
    if best is None:
        return {"Kzt": 1.0, "kind": "flat", "note": "뚜렷한 언덕·경사지 없음 — Kzt = 1.0",
                "z": z, "site_elev": es[i0]}
    if best["Kzt"] <= 1.0 + 1e-9 and biggest is not None:
        return biggest
    return best


DIRECTIONS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                 "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
DIR_KO = {"N": "북", "NNE": "북북동", "NE": "북동", "ENE": "동북동", "E": "동", "ESE": "동남동",
          "SE": "남동", "SSE": "남남동", "S": "남", "SSW": "남남서", "SW": "남서", "WSW": "서남서",
          "W": "서", "WNW": "서북서", "NW": "북서", "NNW": "북북서"}


def profile_points(lat, lon, bearing_from, up=3000.0, down=2000.0, step=30.0):
    """
    풍향(바람이 불어오는 방위, 0=북) 단면의 위경도 점 목록.
    반환 [(s, lat, lon)]  s<0 풍상측(바람이 오는 쪽)
    """
    from .geo import offset_latlon
    pts = []
    s = -up
    while s <= down + 1e-6:
        # 풍상측(s<0)은 bearing_from 방향으로 |s| 만큼, 풍하측은 반대
        if s < 0:
            la, lo = offset_latlon(lat, lon, bearing_from, -s)
        else:
            la, lo = offset_latlon(lat, lon, (bearing_from + 180.0) % 360.0, s)
        pts.append((s, la, lo))
        s += step
    return pts


def analyze_terrain(lat, lon, z, cat, elev_func, ndir=16, up=3000.0, down=2000.0, step=30.0,
                    progress=None):
    """
    여러 풍향의 지형단면을 만들어 Kzt 를 계산.
    elev_func([(lat, lon), ...]) → [elev | None, ...]
    """
    names = DIRECTIONS_16 if ndir == 16 else ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    step_deg = 360.0 / len(names)
    allpts, index = [], []
    for k, nm in enumerate(names):
        pts = profile_points(lat, lon, k * step_deg, up, down, step)
        for s, la, lo in pts:
            index.append((k, s))
            allpts.append((la, lo))
    elevs = elev_func(allpts, progress=progress) if progress else elev_func(allpts)
    profs = {k: [] for k in range(len(names))}
    for (k, s), e in zip(index, elevs):
        if e is not None:
            profs[k].append((s, e))
    # 건설지점이 2차원적으로 봉우리인지: 90~150m 떨어진 주변점 중 3m 이상 높은 곳이 있으면 봉우리 아님
    site_e = None
    ring = []
    for k in profs:
        for s_, e_ in profs[k]:
            if abs(s_) < 1e-6:
                site_e = e_
            elif 85.0 <= abs(s_) <= 155.0:
                ring.append(e_)
    site_not_peak = site_e is not None and ring and max(ring) > site_e + 3.0
    res = []
    for k, nm in enumerate(names):
        r = analyze_profile(profs[k], z, cat, site_not_peak=site_not_peak)
        r.update(dir=nm, dir_ko=DIR_KO.get(nm, nm), bearing=k * step_deg, profile=profs[k])
        res.append(r)
    gov = max(res, key=lambda r: r["Kzt"]) if res else None
    return {"directions": res, "governing": gov, "Kzt": gov["Kzt"] if gov else 1.0,
            "site_elev": site_e, "site_is_peak": not site_not_peak}
