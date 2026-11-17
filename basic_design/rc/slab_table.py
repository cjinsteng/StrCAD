"""
basic_design/rc/slab_table.py
RC Slab — Table : 두께 · 철근 · 간격별 설계휨강도(φMn) 일람표 (Tk 비의존 계산 + 계산서)

  · 두께 1~6개, 간격 1~7개, 사용 철근을 첫 행으로 한 5가지 배근 (예: D13, D13+D16, D16, D16+D19, D19)
  · Major(주방향, 바깥층)  d = T - Cc - db/2
    Minor(부방향, 안쪽층)  d = T - Cc - db,max - db/2   (양방향 같은 배근 가정, 혼용 행 db/2 는 단면적 가중 도심)
  · φMn: Slab Lite 와 같은 단면 해석 (변화구간 φ 보간, εt < εt,min 이면 '---')
  · MinRatio: 수축·온도철근비(KDS 14 20 50 4.6.2)를 만족하는 최대 간격 (≤ 5t, 450)
  · φVc = φv·(1/6)·√fck·b·d   (사용 철근 Major d)
  · 검토 표시
      '---'(빨강)   과다 배근: εt < 휨부재 최소 허용변형률 → 사용 불가
      노란 칸       간격 > min(2t, 300)  (슬래브 위험단면 휨철근 최대 간격)
      주황 칸       철근량 < 수축·온도철근 (MinRatio 간격 초과)
      값 뒤 *       변화구간 단면 (φ < φf)
      주황 머리글   간격 > 균열제어 최대 간격 (주방향, KDS 14 20 20 4.2.3)
"""
from ..report import Report
from . import slab_calc as S

MAX_THK = 6
MAX_SP = 7
DESIGN_CODE = "KDS 14 20 : 2022  (KDS 41 20 00)"


class TableInputError(ValueError):
    pass


def table_rows(bar):
    """사용 철근을 첫 행으로: D13 → D13, D13+D16, D16, D16+D19, D19  (D19·D22 는 위가 모자라 D16 부터)"""
    order = S.BAR_ORDER
    i = order.index(bar) if bar in order else 1
    i = min(i, len(order) - 3)
    a, b, c = order[i:i + 3]
    return [(a,), (a, b), (b,), (b, c), (c,)]


def _area(combo):
    return sum(S.REBAR[b][1] for b in combo) / len(combo)


def _db(combo):
    return max(S.REBAR[b][0] for b in combo)


def _half(combo):
    """철근 도심까지 거리(피복면 기준) = Σ(Ai·dbi/2)/ΣAi — 혼용 배근의 단면적 가중 도심"""
    a = [S.REBAR[b][1] for b in combo]
    return sum(ai * S.REBAR[b][0] / 2.0 for ai, b in zip(a, combo)) / sum(a)


def _fy(combo, fy13, fy16):
    return min(S.fy_of(b, fy13, fy16) for b in combo)


def _cell(t, cc, combo, s, minor, inp, lim):
    """한 칸: dict(txt, style, tip, ...)"""
    fck, fy13, fy16, pf = inp["fck"], inp["fy13"], inp["fy16"], inp["phi_f"]
    db = _db(combo)
    fy = _fy(combo, fy13, fy16)
    d = t - cc - _half(combo) - (db if minor else 0.0)
    as_ = _area(combo) / s * 1000.0
    _, lim_t, emin = S.strain_limits(fy)
    name = "+".join(combo)
    head = (f"{'Minor' if minor else 'Major'}  {name} @{s:g}   (T = {t:g}, fy = {fy:g})\n"
            f"As = {as_:.0f} mm²/m    d = {d:.1f} mm")
    if d <= 0:
        return {"txt": "---", "style": "ng", "tip": head + "\n유효깊이가 0 이하 — 두께/피복 확인", "flag": "na"}
    sec = S.section(as_, d, fck, fy, pf=pf)
    detail = (f"\na = {sec['a']:.1f}   c = {sec['c']:.1f} mm   εt = {sec['eps_t']:.4f}"
              f"\nφ = {sec['phi']:.3f}   φMn = {sec['phi_mn']:.1f} kN·m/m")
    if sec["eps_t"] < emin:
        return {"txt": "---", "style": "ng", "flag": "na",
                "tip": head + detail + f"\n✗ 과다 배근: εt = {sec['eps_t']:.4f} < εt,min = {emin:.4f}"
                                       "\n   → 휨부재로 사용할 수 없는 배근 (간격을 넓히거나 두께 증가)"}
    notes, style, flags = [], "n", []
    if sec["phi"] < pf - 1e-6:
        notes.append(f"※ 변화구간 단면: εt < {lim_t:.4f} → φ = {sec['phi']:.3f} (< {pf:g})")
        flags.append("phi")
    if s > lim["s_crit"] + 1e-9:
        notes.append(f"⚠ 간격 {s:g} > min(2t, 300) = {lim['s_crit']:g} mm  (위험단면 휨철근 최대 간격)")
        style = "bgw"
        flags.append("sp")
    as_min = S.rho_min(fy) * 1000.0 * t
    if as_ < as_min - 1e-9:
        notes.append(f"⚠ As {as_:.0f} < 수축·온도철근 {as_min:.0f} mm²/m  (ρ = {as_ / (1000 * t):.4f} < {S.rho_min(fy):.4f})")
        style = "bgo"
        flags.append("min")
    if not minor and s > lim["s_crack"] + 1e-9:
        notes.append(f"⚠ 간격 {s:g} > 균열제어 최대 간격 {lim['s_crack']:.0f} mm  (1방향 주철근일 때)")
    txt = f"{sec['phi_mn']:.1f}" + ("*" if "phi" in flags else "")
    tip = head + detail + ("\n" + "\n".join(notes) if notes else "\n✓ 검토 항목 모두 만족")
    return {"txt": txt, "style": style, "tip": tip, "flag": flags, "phi_mn": sec["phi_mn"]}


def calc_table(inp):
    """inp: name, fck, fy13, fy16, cc, bar, thks[list], spacings[list], phi_f, phi_v, kcr"""
    fck, fy13, fy16, cc = inp["fck"], inp["fy13"], inp["fy16"], inp["cc"]
    for k, lbl in (("fck", "fck"), ("fy13", "fy(D13↓)"), ("fy16", "fy(D16↑)")):
        if inp[k] <= 0:
            raise TableInputError(f"{lbl} 값은 0보다 커야 합니다.")
    if cc < 0:
        raise TableInputError("피복두께 Cc 는 0 이상이어야 합니다.")
    for k, lbl in (("phi_f", "휨 강도감소계수 φf"), ("phi_v", "전단 강도감소계수 φv")):
        if not 0 < inp[k] <= 1.0:
            raise TableInputError(f"{lbl} 는 0 초과 1.0 이하로 입력하세요.")
    thks, sps = inp["thks"], inp["spacings"]
    if not thks:
        raise TableInputError("슬래브 두께를 1개 이상 입력하세요.")
    if not sps:
        raise TableInputError("철근 간격을 1개 이상 입력하세요.")
    for t in thks:
        if not 50 <= t <= 1500:
            raise TableInputError(f"슬래브 두께 {t:g} mm — 50 ~ 1500 mm 범위로 입력하세요.")
    for s in sps:
        if not 50 <= s <= 600:
            raise TableInputError(f"철근 간격 {s:g} mm — 50 ~ 600 mm 범위로 입력하세요.")
    rows = table_rows(inp["bar"])
    kcr = inp.get("kcr", 210.0)
    out = []
    for t in thks:
        if t - cc - 2 * max(_db(c) for c in rows) <= 10:
            raise TableInputError(f"두께 {t:g} mm 에 비해 피복두께가 너무 큽니다 (부방향 유효깊이 부족).")
        fy_main = _fy(rows[0], fy13, fy16)
        fs = 2.0 / 3.0 * fy_main
        lim = {"s_crit": min(2.0 * t, 300.0),
               "s_crack": min(375.0 * kcr / fs - 2.5 * cc, 300.0 * kcr / fs)}
        blk = {"t": t, "lim": lim, "major": [], "minor": [], "minratio": []}
        for combo in rows:
            fy = _fy(combo, fy13, fy16)
            as_min = S.rho_min(fy) * 1000.0 * t
            s_mr = S._floor10(min(_area(combo) / as_min * 1000.0, min(5.0 * t, 450.0)))
            blk["minratio"].append({"s": s_mr, "as_min": as_min, "fy": fy})
            blk["major"].append([_cell(t, cc, combo, s, False, inp, lim) for s in sps])
            blk["minor"].append([_cell(t, cc, combo, s, True, inp, lim) for s in sps])
        d_v = t - cc - _half(rows[0])
        blk["phi_vc"] = S.phi_vc(d_v, fck, pv=inp["phi_v"])
        blk["d_v"] = d_v
        out.append(blk)
    return {"name": inp.get("name", ""), "inp": dict(inp), "rows": rows, "blocks": out, "spacings": sps,
            "labels": ["+".join(c) for c in rows]}


# ── 계산서 ───────────────────────────────────────────────────
def _count(blk, key, flag):
    n = 0
    for row in blk[key]:
        for c in row:
            f = c["flag"]
            n += (f == flag) if isinstance(f, str) else (flag in f)
    return n


def build_report(res):
    inp = res["inp"]
    rep = Report(f"Slab Table — {res['name']}")
    rep.h("Design Conditions")
    rep.t(f"Design Code  :  {DESIGN_CODE}", 1)
    rep.t(f"Concrete       fck = {inp['fck']:g} N/mm²", 1)
    rep.t(f"Re-bar          fy(D13↓) = {inp['fy13']:g} N/mm²    fy(D16↑) = {inp['fy16']:g} N/mm²", 1)
    rep.t(f"Re-bar Clear Cover   cc = {inp['cc']:g} mm        "
          f"φf = {inp['phi_f']:.2f} (휨, 인장지배)    φv = {inp['phi_v']:.2f} (전단)", 1)
    sps = res["spacings"]
    nsp = len(sps)
    w_lbl, w_mr = 104, 96
    w_sp = min(86, (848 - w_lbl - w_mr) // nsp)
    widths = [w_lbl] + [w_sp] * nsp + [w_mr]
    aligns = ["l"] + ["r"] * nsp + ["c"]
    for blk in res["blocks"]:
        t, lim = blk["t"], blk["lim"]
        rep.h(f"Slab Thk :  {t:g} mm")
        for key, title in (("major", "Major Direction Moment"), ("minor", "Minor Direction Moment")):
            rep.t(f"{title}   (Unit : kN·m/m)", 0, "sub")
            head = [[""] + [((f"@ {s:g}", "hw") if key == "major" and s > lim["s_crack"] + 1e-9 else f"@ {s:g}")
                            for s in sps] + ["MinRatio"]]
            body = []
            for lbl, cells, mr in zip(res["labels"], blk[key], blk["minratio"]):
                body.append([(lbl, "b")] + [(c["txt"], c["style"], c["tip"]) for c in cells]
                            + [(f"@ {mr['s']}", "n", f"{lbl}: 수축·온도철근 As,min = {mr['as_min']:.0f} mm²/m"
                                f"  (ρ = {S.rho_min(mr['fy']):.4f} × 1000 × {t:g})\n최대 간격 = min(As1/As,min, 5t, 450)"
                                f" = {mr['s']} mm")])
            rep.table(head, body, widths, aligns)
        rep.t(f"φVc = {inp['phi_v']:.2f}·(1/6)·√fck·b·d = {blk['phi_vc']:.1f} kN/m      (d = {blk['d_v']:.1f} mm, "
              f"{res['labels'][0]} 주방향)", 1)
        # 이 두께에서 검토가 필요한 항목
        msgs = []
        n_na = _count(blk, "major", "na") + _count(blk, "minor", "na")
        if n_na:
            msgs.append(("ng", f"'---' {n_na}칸 : 과다 배근 (εt < εt,min) — 사용할 수 없는 배근입니다."))
        n_sp = _count(blk, "major", "sp") + _count(blk, "minor", "sp")
        if n_sp:
            msgs.append(("warn", f"노란 칸 {n_sp}칸 : 간격 > min(2t, 300) = {lim['s_crit']:g} mm "
                                 "— 2방향 슬래브 위험단면 휨철근 최대 간격 초과"))
        n_min = _count(blk, "major", "min") + _count(blk, "minor", "min")
        if n_min:
            msgs.append(("warn", f"주황 칸 {n_min}칸 : 철근량 < 수축·온도철근 — MinRatio 간격보다 넓음"))
        crack = [s for s in sps if s > lim["s_crack"] + 1e-9]
        if crack:
            msgs.append(("warn", f"주황 머리글 (@{', @'.join(f'{s:g}' for s in crack)}) : 균열제어 최대 간격 "
                                 f"{lim['s_crack']:.0f} mm 초과 — 1방향 슬래브 주철근으로는 사용 불가"))
        n_phi = _count(blk, "major", "phi") + _count(blk, "minor", "phi")
        if n_phi:
            msgs.append(("dim", f"값 뒤 * {n_phi}칸 : 변화구간 단면 — φ 를 εt 에 따라 낮춰 적용"))
        for st, m in msgs:
            rep.t(("※ " if st != "dim" else "· ") + m, 1, st)
    rep.h("Notes")
    for n in (
        "칸 위에 마우스를 올리면 d, As, εt, φ 와 판정 사유가 표시됩니다.",
        "Major: 바깥층 d = T - Cc - db/2,  Minor: 안쪽층 d = T - Cc - db,max - db/2  (양방향 같은 배근 가정)",
        "혼용 행(예: D13+D16)은 두 철근을 번갈아 배치 — 평균 단면적, 작은 fy, 단면적 가중 도심 기준",
        "강도감소계수: 인장지배 φf, 변화구간 0.65 와 보간,  εt < εt,min(fy≤400: 0.004, 그 외 2εy) 이면 '---'",
        "MinRatio: KDS 14 20 50 4.6.2 수축·온도철근비, 최대 간격 min(5t, 450)",
        "균열제어 간격: KDS 14 20 20 4.2.3, fs = 2/3·fy, κcr = " + f"{inp.get('kcr', 210):g}",
    ):
        rep.t("· " + n, 1, "dim")
    return rep


def overall_ok(res):
    """목록 표시용: 사용 철근 행(첫 행) 주방향에 과다 배근(---) 이 있으면 NG"""
    return not any(c["flag"] == "na" for blk in res["blocks"] for c in blk["major"][0])
