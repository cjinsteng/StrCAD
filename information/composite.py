"""
information/composite.py — 반경 안 시추자료 취합 → 대표 주상도 (미터별)

    · 미터마다 반경 안 시추공의 지층 구성비, 대표 지층(최빈)
    · N값 : 표준관입시험 실측이 있으면 실측(최소·평균·최대),
            없으면 지층명·상대밀도/연경도 기술(매우느슨~매우조밀, 연약~매우견고)로 추정
    · Vs  : 하향식 탄성파 실측이 있으면 실측, 없으면 N → Imai(97·N^0.314) 또는 암반 기본값
    · 지하수위 : 시추정보의 지하수위(0 은 미측정으로 보고 제외) — 최소·중앙·최대
    · 기반암(풍화암·연암) 출현 깊이 분포, 대표 주상 기준 Vs,soil · 지반분류 추정
"""
import math
import statistics as st

from . import boreholes as BH
from . import kds_data as K
from . import seismic

CLS_KO = {
    "fill": "매립·표토", "clay": "점성토", "sand": "사질토", "gravel": "자갈·사력", "sediment": "퇴적(혼합)",
    "soil_weathered": "풍화토", "rock_weathered": "풍화암", "rock_soft": "연암", "rock_hard": "경암",
    "unknown": "미분류",
}
CLS_COLOR = {
    "fill": (176, 150, 120), "clay": (120, 160, 110), "sand": (240, 214, 120), "gravel": (215, 160, 90),
    "sediment": (200, 190, 150), "soil_weathered": (225, 140, 80), "rock_weathered": (180, 95, 70),
    "rock_soft": (140, 110, 160), "rock_hard": (100, 100, 130), "unknown": (190, 190, 190),
}
CLS_ORDER = ("fill", "clay", "sand", "gravel", "sediment", "soil_weathered", "rock_weathered", "rock_soft",
             "rock_hard", "unknown")

# 상대밀도·연경도 기술 → 대표 N (길게 겹치는 표현부터 확인)
DENS_N = (("매우느슨", 3), ("매우조밀", 50), ("보통조밀", 20), ("느슨", 7), ("조밀", 40),
          ("매우연약", 1), ("매우견고", 25), ("보통견고", 6), ("연약", 3), ("견고", 12), ("단단", 15))
CLS_N = {"fill": 7, "clay": 6, "sand": 15, "gravel": 30, "sediment": 12, "soil_weathered": 35,
         "rock_weathered": 50, "unknown": 10}


def est_n(cls, descr=""):
    """지층 분류 + 상대밀도/연경도 기술로 대표 N 추정.  암반은 None."""
    if cls in ("rock_soft", "rock_hard"):
        return None
    t = (descr or "").replace(" ", "")
    vals = []
    for kw, n in DENS_N:
        if kw in t:
            vals.append(n)
            t = t.replace(kw, "")
    n = sum(vals) / len(vals) if vals else CLS_N.get(cls, 10)
    if cls == "rock_weathered":
        n = 50
    elif cls == "soil_weathered":
        n = max(n, 20)
    return min(n, 50.0)


def _stat(v):
    v = [x for x in v if x is not None]
    if not v:
        return None
    return {"n": len(v), "min": min(v), "max": max(v), "mean": sum(v) / len(v), "med": st.median(v)}


def build(holes, details, step=1.0, max_depth=None, settings=None, tests=None):
    """
    holes   : BoreholeDB.search() 결과 (반경 안 전체 — 지하수위는 지층 없는 공도 사용)
    details : {code: (layers, spts, vs_list)}
    """
    settings = settings or {}
    corr = settings.get("vs_corr", "imai")
    use = [h for h in holes if details.get(h["code"]) and details[h["code"]][0]]
    out = {"n_radius": len(holes), "n_used": len(use), "rows": [], "profile": [], "step": step}
    # 지하수위
    g = []
    for h in holes:
        w = h.get("gwl")
        if w is not None and w != 0 and abs(w) < 80:
            g.append((abs(w), h))
    gs = _stat([a for a, _ in g])
    out["gwl"] = dict(gs or {}, n_zero=sum(1 for h in holes if h.get("gwl") == 0),
                      items=[{"code": h["code"], "dist": h["dist"], "gwl": a} for a, h in sorted(g, key=lambda q: q[1]["dist"])])
    # 현장투수시험 · 전단강도시험
    if tests:
        P, T = tests
        out["perm"] = dict(_stat([p["k"] for p in P]) or {}, holes=len({p["hole"] for p in P}))
        byt = {}
        for t in T:
            byt.setdefault(t["typ"] or "기타", []).append(t)
        out["strength"] = {k: {"n": len(v), "c": _stat([t["c"] for t in v]), "phi": _stat([t["phi"] for t in v])}
                           for k, v in byt.items()}
    if not use:
        return out
    # 공별 깊이 · 분류
    H = []
    for h in use:
        layers, spts, vss = details[h["code"]]
        L = []
        for ly in sorted(layers, key=lambda q: q["top"]):
            cls = BH.classify_layer(ly["name"], ly.get("uscs", ""), ly.get("descr", ""))
            L.append(dict(ly, cls=cls, n_est=est_n(cls, ly.get("descr", ""))))
        dep = max([h.get("depth") or 0.0] + [q["bot"] for q in L])
        H.append({"h": h, "L": L, "spt": spts or [], "vs": vss or [], "depth": dep})
    dmax = max(x["depth"] for x in H)
    if max_depth:
        dmax = min(dmax, max_depth)
    nz = int(math.ceil(dmax / step))
    rows = []
    for k in range(nz):
        z0, z1 = k * step, (k + 1) * step
        zm = (z0 + z1) / 2
        dist, nm, ne, vm, ve = {}, [], [], [], []
        n_reach = 0
        for x in H:
            if x["depth"] < zm:
                continue
            ly = next((q for q in x["L"] if q["top"] <= zm < q["bot"]), None)
            if ly is None:
                continue
            n_reach += 1
            dist[ly["cls"]] = dist.get(ly["cls"], 0) + 1
            meas = [s["n"] for s in x["spt"] if s.get("n") is not None and z0 <= s["depth"] < z1]
            nm += meas
            if not meas and ly["n_est"] is not None:
                ne.append(ly["n_est"])
            vv = [v["vs"] for v in x["vs"] if v["top"] <= zm < v["bot"]]
            if vv:
                vm += vv
            else:
                nn = (sum(meas) / len(meas)) if meas else ly["n_est"]
                if ly["cls"] in ("rock_soft", "rock_hard"):
                    ve.append(max(K.LAYER_DEFAULT_VS[ly["cls"]], K.BEDROCK_VS))
                elif ly["cls"] == "rock_weathered":
                    ve.append(float(settings.get("weathered_rock_vs", K.LAYER_DEFAULT_VS["rock_weathered"])))
                else:
                    ve.append(BH.vs_from_n(nn, ly["cls"], corr) if nn else K.LAYER_DEFAULT_VS.get(ly["cls"], 200.0))
        if not n_reach:
            continue
        rep = max(dist, key=lambda c: (dist[c], CLS_ORDER.index(c)))
        rows.append({"z0": z0, "z1": z1, "n": n_reach, "dist": dist, "rep": rep, "pct": dist[rep] / n_reach,
                     "N": _stat(nm) or _stat(ne), "N_src": "실측" if nm else ("추정" if ne else ""),
                     "N_meas": _stat(nm), "N_est": _stat(ne),
                     "Vs": _stat(vm) or _stat(ve), "Vs_src": "실측" if vm else ("추정" if ve else ""),
                     "Vs_meas": _stat(vm), "Vs_est": _stat(ve)})
    # 표시 깊이: 반경 안 지층자료 공의 20% 이상(최소 2공)이 닿는 깊이까지
    need = max(2, int(math.ceil(0.2 * len(H)))) if len(H) >= 2 else 1
    deep = [r for r in rows if r["n"] >= need]
    if deep:
        cut = deep[-1]["z1"]
        out["dmax_all"] = dmax
        rows = [r for r in rows if r["z1"] <= cut + 1e-6]
        dmax = cut
    out["rows"] = rows
    out["dmax"] = dmax
    # 대표 주상 — 공마다 '그 지층군 이상'이 처음 나오는 깊이의 중앙값 (위→아래 순서가 뒤집히지 않음)
    #   지층군: 매립·표토 → 토사(점성토·사질토·자갈·퇴적) → 풍화토 → 풍화암 → 연암 → 경암
    GROUPS = (("fill",), ("clay", "sand", "gravel", "sediment", "unknown"), ("soil_weathered",),
              ("rock_weathered",), ("rock_soft",), ("rock_hard",))
    gi = {c: k for k, grp in enumerate(GROUPS) for c in grp}
    tops = []
    for k in range(1, len(GROUPS)):
        v = []
        for x in H:
            z = next((q["top"] for q in x["L"] if gi.get(q["cls"], 1) >= k), None)
            v.append(z if z is not None else math.inf)
        v.sort()
        med = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
        tops.append(med)
    for k in range(len(tops) - 2, -1, -1):          # 단조 보정
        tops[k] = min(tops[k], tops[k + 1])
    bounds = [0.0] + [min(t, dmax) for t in tops] + [dmax]
    prof = []
    for k, grp in enumerate(GROUPS):
        a, b = bounds[k], bounds[k + 1]
        if b - a < 0.05:
            continue
        R = [r for r in rows if r["z0"] >= a - 1e-6 and r["z1"] <= b + 1e-6 and r["z1"] - r["z0"] > 0] or \
            [r for r in rows if r["z0"] < b and r["z1"] > a]
        cnt = {}
        tot = 0
        for r in R:
            for cc, n in r["dist"].items():
                tot += n
                if cc in grp:
                    cnt[cc] = cnt.get(cc, 0) + n
        cls = max(cnt, key=cnt.get) if cnt else grp[0]
        share = (sum(cnt.values()) / tot) if tot else 0.0
        prof.append({"top": a, "bot": b, "cls": cls, "_r": R, "pct_grp": share,
                     "mix": {CLS_KO[c]: n for c, n in sorted(cnt.items(), key=lambda q: -q[1])}})
    for p in prof:
        R = p.pop("_r")
        p["label"] = CLS_KO[p["cls"]]
        p["pct"] = p.pop("pct_grp")
        ns = [r["N"]["mean"] for r in R if r["N"]]
        vs = [r["Vs"]["mean"] for r in R if r["Vs"]]
        p["N"] = sum(ns) / len(ns) if ns else None
        p["N_min"] = min((r["N"]["min"] for r in R if r["N"]), default=None)
        p["N_max"] = max((r["N"]["max"] for r in R if r["N"]), default=None)
        p["N_src"] = "실측" if any(r["N_src"] == "실측" for r in R) else ("추정" if ns else "")
        p["Vs"] = sum(vs) / len(vs) if vs else None
        p["Vs_src"] = "실측" if any(r["Vs_src"] == "실측" for r in R) else ("추정" if vs else "")
        p["n"] = max((r["n"] for r in R), default=0)
    out["profile"] = prof
    # 기반암 깊이 분포
    rock = {}
    for key, classes in (("weathered", ("rock_weathered", "rock_soft", "rock_hard")),
                         ("soft", ("rock_soft", "rock_hard"))):
        d = [next((q["top"] for q in x["L"] if q["cls"] in classes), None) for x in H]
        rock[key] = dict(_stat([v for v in d if v is not None]) or {}, n_not=sum(1 for v in d if v is None),
                         max_hole=max(x["depth"] for x in H))
    out["rock"] = rock
    # 대표 주상 Vs,soil · 지반분류
    rule = settings.get("bedrock_rule", "soft")
    rclasses = BH.bedrock_classes(rule)
    rtop = next((p["top"] for p in prof if p["cls"] in rclasses), None)
    lim = min(rtop if rtop is not None else dmax, K.TOP_DEPTH_FOR_VS)
    tsum = z = 0.0
    for r in rows:
        if r["z0"] >= lim:
            break
        t = min(r["z1"], lim) - r["z0"]
        v = (r["Vs"] or {}).get("mean") or 200.0
        tsum += t / v
        z = r["z0"] + t
    vs_soil = z / tsum if tsum > 0 else None
    site = None
    if rtop is not None or vs_soil:
        site = seismic.classify_site(rtop if rtop is not None else dmax, vs_soil, rtop is not None, dmax)
        site = site[0] if isinstance(site, (tuple, list)) else site
    out.update(rock_top=rtop, vs_soil=vs_soil, vs_depth=z, site=site)
    out["n_spt"] = sum(1 for x in H if x["spt"])
    out["n_vs"] = sum(1 for x in H if x["vs"])
    return out


def text(c, radius=None):
    L = []
    a = L.append
    a(f"반경{'' if radius is None else f' {radius:.0f} m'} 안 시추공 {c['n_radius']}공 — 지층자료 {c['n_used']}공"
      f" (표준관입 실측 {c.get('n_spt', 0)}공, 하향식 탄성파 {c.get('n_vs', 0)}공)")
    g = c.get("gwl") or {}
    if g.get("n"):
        a(f"지하수위 GL−{g['min']:.1f} ~ −{g['max']:.1f} m (중앙 −{g['med']:.1f}, 평균 −{g['mean']:.1f} m, {g['n']}공)"
          + (f", 0 기록(미측정) {g['n_zero']}공 제외" if g.get("n_zero") else ""))
    else:
        a("지하수위 자료 없음")
    for key, nm in (("weathered", "풍화암 이상"), ("soft", "연암 이상")):
        r = (c.get("rock") or {}).get(key) or {}
        if r.get("n"):
            a(f"{nm} 출현 GL−{r['min']:.1f} ~ −{r['max']:.1f} m (중앙 −{r['med']:.1f} m, {r['n']}공"
              + (f", 미확인 {r['n_not']}공" if r.get("n_not") else "") + ")")
        else:
            a(f"{nm}: 시추 깊이(최대 {r.get('max_hole', 0):.0f} m) 안에서 확인 안 됨")
    if c.get("profile"):
        a("대표 주상 (공별 지층군 출현깊이의 중앙값, % = 그 구간에서 해당 지층 비율):")
        for p in c["profile"]:
            n = "—" if p["N"] is None else (f"{p['N']:.0f}" + (f" ({p['N_min']:.0f}~{p['N_max']:.0f})"
                                                                 if p["N_min"] is not None and p["N_max"] != p["N_min"] else ""))
            vs = "—" if p["Vs"] is None else f"{p['Vs']:.0f}"
            a(f"  GL−{p['top']:5.1f} ~ −{p['bot']:5.1f} m  {p['label']:<6} ({p['pct'] * 100:3.0f}%)  "
              f"N {n} [{p['N_src']}]  Vs {vs} m/s [{p['Vs_src']}]")
    if c.get("vs_soil"):
        a(f"대표 주상 기준 Vs,soil ≈ {c['vs_soil']:.0f} m/s (0~{c['vs_depth']:.1f} m), "
          f"기반암 GL−{c['rock_top']:.1f} m" if c.get("rock_top") is not None else
          f"대표 주상 기준 Vs,soil ≈ {c['vs_soil']:.0f} m/s, 기반암 미확인")
        if c.get("site"):
            a(f"→ 예상 지반분류 {c['site']}")
    pm = c.get("perm") or {}
    if pm.get("n"):
        a(f"현장투수시험 {pm['n']}건({pm['holes']}공): 평균투수계수 {pm['min']:.2e} ~ {pm['max']:.2e} "
          f"(중앙 {pm['med']:.2e}, 원자료 단위)")
    for typ, v in (c.get("strength") or {}).items():
        cs, ps = v.get("c") or {}, v.get("phi") or {}
        a(f"전단강도시험 {typ} {v['n']}건: 점착력 {cs.get('min', 0):.1f}~{cs.get('max', 0):.1f} (중앙 {cs.get('med', 0):.1f}), "
          f"내부마찰각 {ps.get('min', 0):.1f}~{ps.get('max', 0):.1f}° (중앙 {ps.get('med', 0):.1f}°)")
    if c.get("n_used") and not c.get("n_spt"):
        a("※ N값은 표준관입시험 자료가 없어 지층명·상대밀도 기술로 추정한 값입니다 (표준관입시험 CSV를 가져오면 실측으로 바뀜).")
    return "\n".join(L)


# ─────────────────────────────────────────────────────────────
#  주상도 그림
# ─────────────────────────────────────────────────────────────
def _font(size, bold=False):
    from PIL import ImageFont
    for nm in (("malgunbd.ttf" if bold else "malgun.ttf"), "NanumGothicBold.ttf" if bold else "NanumGothic.ttf",
               "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nm, size)
        except Exception:                            # noqa: BLE001
            continue
    return ImageFont.load_default()


def render(c, title="", radius=None, px_m=16, width=1180):
    from PIL import Image, ImageDraw
    rows = c.get("rows") or []
    dmax = max(c.get("dmax") or 0, 5)
    top = 150
    H = int(top + dmax * px_m + 70)
    im = Image.new("RGB", (width, H), "white")
    d = ImageDraw.Draw(im)
    f, fs, fb, ft = _font(12), _font(11), _font(12, True), _font(16, True)
    d.text((16, 10), title or "취합 주상도", fill=(0, 0, 0), font=ft)
    head_lines = text(c, radius).split("\n")
    head_lines = head_lines[:next((i for i, t in enumerate(head_lines) if t.startswith("대표 주상")), 5)][:4]
    if c.get("site"):
        head_lines.append(f"대표 주상 기준 Vs,soil ≈ {c['vs_soil']:.0f} m/s, 기반암 "
                          + (f"GL−{c['rock_top']:.1f} m" if c.get("rock_top") is not None else "미확인")
                          + f" → 예상 지반분류 {c['site']}")
    for i, line in enumerate(head_lines[:5]):
        d.text((16, 36 + i * 17), line, fill=(40, 40, 40), font=fs)
    Y = lambda z: top + z * px_m                   # noqa: E731
    cols = {"depth": (16, 66), "rep": (76, 236), "dist": (246, 416), "N": (426, 676), "Vs": (686, 936),
            "cnt": (946, 1000)}
    heads = {"depth": "GL−(m)", "rep": "대표 지층", "dist": "지층 구성비", "N": "N 값 (0~50)", "Vs": "Vs (0~1,000 m/s)",
             "cnt": "공수"}
    for k, (x0, x1) in cols.items():
        d.rectangle((x0, top - 22, x1, top), fill=(31, 45, 74))
        d.text((x0 + 4, top - 19), heads[k], fill="white", font=fb if k != "cnt" else fs)
        d.rectangle((x0, top, x1, Y(dmax)), outline=(120, 120, 120))
    # 눈금
    for z in range(0, int(dmax) + 1):
        y = Y(z)
        major = z % 5 == 0
        d.line((cols["depth"][1] - (10 if major else 5), y, cols["depth"][1], y), fill=(0, 0, 0))
        if major:
            d.text((cols["depth"][0] + 2, y - 7), f"{z}", fill=(0, 0, 0), font=f)
            for k in ("dist", "N", "Vs"):
                d.line((cols[k][0], y, cols[k][1], y), fill=(225, 225, 225))
    for k, vmax, step in (("N", 50, 10), ("Vs", 1000, 200)):
        x0, x1 = cols[k]
        for v in range(0, vmax + 1, step):
            x = x0 + (x1 - x0) * v / vmax
            d.line((x, top, x, Y(dmax)), fill=(230, 230, 230))
            d.text((x - 6, Y(dmax) + 4), f"{v}", fill=(90, 90, 90), font=fs)
    # 대표 지층
    x0, x1 = cols["rep"]
    for p in c.get("profile") or []:
        y0, y1 = Y(p["top"]), Y(p["bot"])
        d.rectangle((x0 + 1, y0, x1 - 1, y1), fill=CLS_COLOR[p["cls"]], outline=(60, 60, 60))
        if p["cls"] in ("sand", "gravel", "soil_weathered"):
            for yy in range(int(y0) + 4, int(y1), 7):
                for xx in range(x0 + 6 + (yy % 14 == 0) * 4, x1 - 4, 9):
                    d.point((xx, yy), fill=(90, 70, 40))
        elif p["cls"] in ("clay",):
            for yy in range(int(y0) + 5, int(y1), 6):
                d.line((x0 + 4, yy, x1 - 4, yy), fill=(90, 120, 80))
        elif p["cls"] in ("rock_weathered", "rock_soft", "rock_hard"):
            gap = 14 if p["cls"] == "rock_weathered" else 9
            hgt = y1 - y0
            for c0 in range(-int(hgt), x1 - x0, gap):       # 45° 빗금, 사각형 안으로 자르기
                ax, ay = x0 + c0, y0
                bx, by = x0 + c0 + hgt, y1
                if ax < x0 + 1:
                    ay += (x0 + 1 - ax); ax = x0 + 1
                if bx > x1 - 1:
                    by -= (bx - (x1 - 1)); bx = x1 - 1
                if bx > ax:
                    d.line((ax, ay, bx, by), fill=(240, 225, 215))
        if y1 - y0 >= 13:
            lab = f"{p['label']} {p['pct'] * 100:.0f}%"
            bb = d.textbbox((0, 0), lab, font=fb)
            d.rectangle(((x0 + x1) / 2 - (bb[2] - bb[0]) / 2 - 3, (y0 + y1) / 2 - 8,
                         (x0 + x1) / 2 + (bb[2] - bb[0]) / 2 + 3, (y0 + y1) / 2 + 8), fill=(255, 255, 255))
            d.text(((x0 + x1) / 2 - (bb[2] - bb[0]) / 2, (y0 + y1) / 2 - 8), lab, fill=(0, 0, 0), font=fb)
    # 구성비 · N · Vs · 공수
    for r in rows:
        y0, y1 = Y(r["z0"]) + 1, Y(r["z1"]) - 1
        x = cols["dist"][0] + 1
        wtot = cols["dist"][1] - cols["dist"][0] - 2
        for cls in CLS_ORDER:
            n = r["dist"].get(cls, 0)
            if n:
                w = wtot * n / r["n"]
                d.rectangle((x, y0, x + w, y1), fill=CLS_COLOR[cls])
                x += w
        ym = (y0 + y1) / 2
        for k, vmax, src, colm, cole in (("N", 50.0, r["N_src"], (30, 90, 200), (230, 120, 30)),
                                         ("Vs", 1000.0, r["Vs_src"], (20, 150, 80), (200, 80, 160))):
            s = r.get(k)
            if not s:
                continue
            a0, a1 = cols[k]
            X = lambda v: a0 + (a1 - a0) * min(v, vmax) / vmax  # noqa: E731
            col = colm if src == "실측" else cole
            d.line((X(s["min"]), ym, X(s["max"]), ym), fill=col, width=2)
            cx = X(s["mean"])
            if src == "실측":
                d.ellipse((cx - 4, ym - 4, cx + 4, ym + 4), fill=col)
            else:
                d.ellipse((cx - 4, ym - 4, cx + 4, ym + 4), outline=col, width=2)
        d.text((cols["cnt"][0] + 6, ym - 7), str(r["n"]), fill=(60, 60, 60), font=fs)
    # 평균선 연결
    for k, vmax, key in (("N", 50.0, "N"), ("Vs", 1000.0, "Vs")):
        a0, a1 = cols[k]
        pts = [(a0 + (a1 - a0) * min(r[key]["mean"], vmax) / vmax, (Y(r["z0"]) + Y(r["z1"])) / 2) for r in rows if r[key]]
        if len(pts) > 1:
            d.line(pts, fill=(90, 90, 90), width=1)
    # 지하수위
    g = c.get("gwl") or {}
    if g.get("n"):
        x0, x1 = cols["rep"][0], cols["Vs"][1]
        if g["max"] > g["min"]:
            band = Image.new("RGBA", (x1 - x0, max(int(Y(g["max"]) - Y(g["min"])), 1)), (60, 140, 255, 45))
            im.paste(band, (x0, int(Y(min(g["min"], dmax)))), band)
        ym = Y(min(g["med"], dmax))
        for xx in range(x0, x1, 12):
            d.line((xx, ym, xx + 7, ym), fill=(20, 90, 230), width=2)
        d.polygon([(x1 + 4, ym), (x1 + 16, ym), (x1 + 10, ym + 9)], fill=(20, 90, 230))
        d.text((cols["cnt"][1] + 6, ym - 22), f"지하수위\nGL−{g['med']:.1f}m\n(중앙,{g['n']}공)", fill=(20, 90, 230), font=fs)
    # 범례
    y = H - 44
    x = 16
    for cls in CLS_ORDER[:-1]:
        d.rectangle((x, y, x + 14, y + 12), fill=CLS_COLOR[cls], outline=(80, 80, 80))
        d.text((x + 18, y - 1), CLS_KO[cls], fill=(0, 0, 0), font=fs)
        x += 26 + d.textbbox((0, 0), CLS_KO[cls], font=fs)[2]
    y += 20
    x = 16
    for txt, col, fill in (("N 실측", (30, 90, 200), True), ("N 추정(지층·상대밀도)", (230, 120, 30), False),
                           ("Vs 실측(하향식 탄성파)", (20, 150, 80), True), ("Vs 추정(N→Imai, 암반 기본값)", (200, 80, 160), False)):
        if fill:
            d.ellipse((x, y, x + 10, y + 10), fill=col)
        else:
            d.ellipse((x, y, x + 10, y + 10), outline=col, width=2)
        d.text((x + 14, y - 2), txt + "  (선: 최소~최대, 점: 평균)" if x == 16 else txt, fill=(0, 0, 0), font=fs)
        x += 30 + d.textbbox((0, 0), txt + ("  (선: 최소~최대, 점: 평균)" if x == 16 else ""), font=fs)[2]
    return im
