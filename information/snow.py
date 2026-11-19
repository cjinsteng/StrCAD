"""
information/snow.py — 지붕설하중 (KDS 41 12 00:2022 4)

    Sf = Cb · Ce · Ct · Is · Sg      (4.3-1)
    Ss = Cs · Sf                     (4.4-1)
"""
from . import kds_data as K


def ground_snow(sg_map, highland=False):
    """기본지상설하중 Sg (그림 4.2-1 값, 고지대·산간 ×1.5, 최소 0.5)."""
    if sg_map is None:
        return None, []
    sg = float(sg_map)
    notes = []
    if highland and sg <= K.SNOW_HIGHLAND_LIMIT:
        sg *= K.SNOW_HIGHLAND_FACTOR
        notes.append(f"고지대·산간 → 그림값 {sg_map:.2f} × 1.5")
    if sg < K.SNOW_SG_MIN:
        notes.append(f"최소 지상설하중 {K.SNOW_SG_MIN} 적용")
        sg = K.SNOW_SG_MIN
    return sg, notes


def slope_factor(slope_deg, ct, slippery=False):
    """
    그림 4.4-1 지붕경사도계수 Cs (꺾은선 가정 — kds_data.VERIFY['snow_cs'])
      난방 (Ct=1.0): 미끄러운 면 5°, 그 외 30° 까지 1.0 → 70° 에서 0
      비난방 (Ct>1.0): 미끄러운 면 15°, 그 외 45° 까지 1.0 → 70° 에서 0
    """
    a = float(slope_deg or 0.0)
    if ct <= 1.0:
        flat = 5.0 if slippery else 30.0
    else:
        flat = 15.0 if slippery else 45.0
    if a <= flat:
        return 1.0
    if a >= 70.0:
        return 0.0
    return (70.0 - a) / (70.0 - flat)


def roof_snow(sg, ce, ct, importance, slope_deg=0.0, slippery=False, eave_ridge_w=None):
    """설하중 일괄 계산.  eave_ridge_w: 처마~용마루 수평거리 W (m) — 비 추가하중 판정용."""
    i_s = K.SNOW_IS.get(str(importance), 1.0)
    sf = K.SNOW_CB * ce * ct * i_s * sg
    cs = slope_factor(slope_deg, ct, slippery)
    ss = cs * sf
    notes = []
    smin = None
    if slope_deg <= 15.0:                            # 4.3.5 완경사지붕 최소설하중
        if sg <= 1.0:
            smin = max(sg * i_s, 1.0)
        else:
            smin = 1.0 * i_s
    rain = 0.0
    if sg <= 1.0:                                    # 4.7.1 눈 위의 비
        lim = (eave_ridge_w / 15.0) if eave_ridge_w else None
        if lim is None or slope_deg <= lim:
            rain = K.SNOW_RAIN_ON_SNOW
            notes.append("4.7.1 Sg ≤ 1.0 → 눈 위의 비 0.25 kN/㎡ 추가"
                         + ("" if lim is not None else " (W 미입력 — 적용으로 가정)"))
    design = ss + rain
    gov = "경사지붕설하중 Ss" + (" + 비" if rain else "")
    if smin is not None and smin > design:
        design = smin
        gov = "완경사지붕 최소설하중"
    return {"Sg": sg, "Cb": K.SNOW_CB, "Ce": ce, "Ct": ct, "Is": i_s, "Sf": sf, "Cs": cs,
            "Ss": ss, "rain": rain, "S_min": smin, "design": design, "governing": gov,
            "notes": notes, "vs_roof_live": design > 1.0}
