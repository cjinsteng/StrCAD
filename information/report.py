"""
information/report.py — 분석 결과 글·엑셀 보고서
"""
import time

from . import kds_data as K
from . import wind as W  # noqa: F401


def _f(v, fmt="{:.3f}", none="—"):
    if v is None:
        return none
    try:
        return fmt.format(v)
    except (ValueError, TypeError):
        return str(v)


def build_text(inp, res):
    L = []
    a = L.append
    a("=" * 72)
    a(f" 건물정보 분석 — {inp.get('project') or '(이름 없음)'}")
    a(f" {time.strftime('%Y-%m-%d %H:%M')}   StrCAD Information")
    a("=" * 72)
    a(f"주소      : {inp.get('address', '')}")
    a(f"좌표      : 위도 {_f(inp.get('lat'), '{:.6f}')}, 경도 {_f(inp.get('lon'), '{:.6f}')}"
      f"   지반표고 {_f(res.get('site_elev'), '{:.1f}')} m")
    a(f"시설물    : {inp.get('facility', '')}   중요도 ({inp.get('importance')})")
    a(f"규모      : 지상 {inp.get('floors')}층, 높이 H = {_f(inp.get('height'), '{:.1f}')} m, "
      f"B = {_f(inp.get('B'), '{:.1f}')} m, D = {_f(inp.get('D'), '{:.1f}')} m")
    a("")
    w = res.get("wind") or {}
    a("■ 풍하중 (KDS 41 12 00:2022 5.5)")
    if w.get("ok"):
        d = w["design"]
        a(f"  기본풍속 V0      = {_f(d['V0'], '{:.2f}')} m/s   ({w.get('v0_src', '')})")
        kv = w.get("v0_auto") or {}
        if kv.get("interp") is not None:
            a(f"    그림 5.5-1 : 선형보간 {kv['interp']:.2f} m/s · 인근 등풍속선 중 큰 값 {kv['max']:g} m/s (주2)")
        a(f"  지표면조도       = {inp.get('roughness')}   Kzr(H) = {_f(d['Kzr'])}   ({w.get('rough_src', '')})")
        ex = w.get("expo")
        if ex:
            a(f"    판정 반경 R = {ex['R']:,.0f} m ({'40H·3km 중 작은 값' if ex.get('rule') != 'max' else '40H·3km 중 큰 값'}), "
              f"자료 {ex.get('source', '')}, 건물 {ex.get('n_buildings', 0)}동")
            bd = {r["dir"]: r for r in w.get("by_dir") or []}
            for r in ex["sectors"]:
                b = bd.get(r["dir"], {})
                a(f"    {r['dir']:>2}({r['ko']}) {r['cat']}{'★' if r.get('star') else ' '}  건폐 {r['cov'] * 100:5.1f}%  "
                  f"10층↑ {r['hi'] * 100:4.1f}%  4~9층 {r['mid'] * 100:4.1f}%  수면 {r['water'] * 100:3.0f}%  "
                  f"Kzr {b.get('Kzr', 0):.3f}  qH {b.get('qH', 0):6.0f} N/㎡  — {r['why']}")
        a(f"  풍향계수 Kd      = {_f(d['Kd'], '{:.2f}')}")
        a(f"  지형계수 Kzt     = {_f(d['Kzt'])}   ({w.get('kzt_src', '')})")
        a(f"  중요도계수 Iw    = {_f(d['Iw'], '{:.2f}')}" + ("  (초고층)" if d.get("supertall") else ""))
        a(f"  설계풍속 VH      = {_f(d['VH'], '{:.2f}')} m/s")
        a(f"  설계속도압 qH    = {_f(d['qH'], '{:.1f}')} N/㎡ = {_f(d['qH'] / 1000, '{:.3f}')} kN/㎡")
        g = (w.get("terrain") or {}).get("governing")
        if g and g.get("kind") != "flat" and g.get("H"):
            a(f"  지배 풍향 {g.get('dir_ko', '')}: {('언덕·산' if g['kind'] == 'hill' else '경사지')} "
              f"H={g['H']:.1f}m, Lu={g['Lu']:.0f}m, x={g['x']:+.0f}m, θ′={_f(g.get('theta_p'))}, "
              f"kt={_f(g.get('Kh'))}, s={_f(g.get('L'))}, Iz={_f(g.get('Iz'))}  — 식 (5.5-3)")
        a("  높이별 속도압")
        for r in w.get("profile", []):
            a(f"    z={r['z']:6.1f}m  Kzr={r['Kzr']:.3f}  Kzt={r['Kzt']:.3f}  Vz={r['Vz']:6.2f}  qz={r['qz']:7.1f} N/㎡")
    else:
        a("  " + w.get("msg", "계산 안 됨"))
    a("")
    s = res.get("seismic") or {}
    a("■ 지진하중 (KDS 41 17 00:2022)")
    if s.get("zone_txt"):
        a(f"  지진구역        : {s['zone_txt']}")
    e = s.get("eval") or {}
    si = e.get("s") or {}
    a(f"  유효지반가속도 S = {_f(si.get('S'))} g   ({'국가지진위험지도' if si.get('method') == 'map' else '지진구역계수 Z × 2.0'})"
      + (f"  {si.get('note')}" if si.get("note") else ""))
    if si.get("S_map") is not None:
        a(f"    국가지진위험지도 {si['S_map'] * 100:.1f} %g = {si['S_map']:.3f} g ({s.get('s_map_src', '')}) / "
          f"하한(Z·I×80%) {_f(si.get('S_min'))} g" + ("" if si.get("method") == "map" else "  — 참고값"))
    bh = s.get("boreholes") or {}
    if bh:
        a(f"  시추조사        : 반경 {bh.get('radius', 0):.0f} m 안 {bh.get('n_total', 0)}공")
        for line in (bh.get("summary", {}).get("text") or "").split("\n"):
            if line:
                a("    " + line)
    comp = bh.get("composite") if bh else None
    if comp and comp.get("n_radius"):
        from . import composite as CP
        a("  취합 주상도 (반경 안 시추자료):")
        for line in CP.text(comp, bh.get("radius")).split("\n"):
            a("    " + line)
    a(f"  지반분류        : {s.get('site', '—')}  {s.get('site_src', '')}")
    if e.get("ok"):
        sp = e["spectrum"]
        a(f"  Fa = {_f(e['Fa'])}, Fv = {_f(e['Fv'])}" + ("  " + "; ".join(e.get("amp_notes") or []) if e.get("amp_notes") else ""))
        a(f"  SDS = {_f(sp['SDS'])} g,  SD1 = {_f(sp['SD1'])} g,  T0 = {_f(sp['T0'])} s,  Ts = {_f(sp['Ts'])} s")
        a(f"  내진등급 {e['grade']}, 중요도계수 IE = {e['IE']:.1f}, 내진설계범주 {e['SDC']} "
          f"(SDS→{e['SDC_SDS']}, SD1→{e['SDC_SD1']})")
    else:
        a("  " + (s.get("msg") or "지진 변수를 계산하지 못했습니다"))
    a("")
    n = res.get("snow") or {}
    a("■ 설하중 (KDS 41 12 00:2022 4)")
    if n.get("ok"):
        r = n["roof"]
        a(f"  기본지상설하중 Sg = {_f(r['Sg'], '{:.2f}')} kN/㎡   ({n.get('sg_src', '')})")
        kv = n.get("sg_auto") or {}
        if kv.get("interp") is not None:
            a(f"    그림 4.2-1 : 선형보간 {kv['interp']:.2f} · 인근 큰 값 {kv['max']:g} kN/㎡")
        for t in n.get("sg_notes", []):
            a("    " + t)
        a(f"  Cb={r['Cb']:.1f}, Ce={r['Ce']:.1f}, Ct={r['Ct']:.1f}, Is={r['Is']:.1f}")
        a(f"  평지붕설하중 Sf  = {_f(r['Sf'])} kN/㎡,  Cs = {_f(r['Cs'])},  Ss = {_f(r['Ss'])} kN/㎡")
        if r.get("S_min") is not None:
            a(f"  완경사지붕 최소   = {_f(r['S_min'])} kN/㎡")
        for t in r.get("notes", []):
            a("    " + t)
        a(f"  설계 지붕설하중  = {_f(r['design'])} kN/㎡   ({r['governing']})")
    else:
        a("  " + n.get("msg", "계산 안 됨"))
    a("")
    a("■ 확인 필요 (원문 대조)")
    for k, t in K.VERIFY.items():
        a(f"  · {t}")
    a("  · 지도 값: 그림 5.5-1·4.2-1 은 그림에서 따낸 등치선(근사)으로 선형보간·큰 값을 계산, "
      "그림 3.2-1 은 등고선 격자 직선보간 — 화면 [🗺 상세]에서 핀 위치 확인")
    return "\n".join(L)


def save_xlsx(path, inp, res):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    hdr = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1F2D4A")

    def head(ws, row, cols):
        for i, c in enumerate(cols, 1):
            cell = ws.cell(row=row, column=i, value=c)
            cell.font, cell.fill = hdr, fill
            cell.alignment = Alignment(horizontal="center")

    ws = wb.active
    ws.title = "요약"
    for i, line in enumerate(build_text(inp, res).split("\n"), 1):
        ws.cell(row=i, column=1, value=line).font = Font(name="Consolas")
    ws.column_dimensions["A"].width = 120

    w = res.get("wind") or {}
    ws = wb.create_sheet("풍하중")
    head(ws, 1, ["z (m)", "Kzr", "Kzt", "Iz", "Vz (m/s)", "qz (N/㎡)"])
    for i, r in enumerate(w.get("profile", []), 2):
        for j, k in enumerate(("z", "Kzr", "Kzt", "Iz", "Vz", "qz"), 1):
            ws.cell(row=i, column=j, value=round(r[k], 4))
    dirs = (w.get("terrain") or {}).get("directions") or []
    if dirs:
        r0 = len(w.get("profile", [])) + 4
        head(ws, r0, ["풍향", "지형", "H (m)", "Lu (m)", "x (m)", "φ′", "kt", "s", "Iz", "Kzt", "비고"])
        for i, d in enumerate(dirs, r0 + 1):
            vals = [d.get("dir_ko"), {"hill": "언덕·산", "escarpment": "경사지"}.get(d.get("kind"), "평탄"),
                    d.get("H"), d.get("Lu"), d.get("x"), d.get("theta_p"), d.get("Kh"), d.get("L"),
                    d.get("Iz"), d.get("Kzt"), d.get("note", "")]
            for j, v in enumerate(vals, 1):
                ws.cell(row=i, column=j, value=round(v, 4) if isinstance(v, float) else v)

    ex = w.get("expo")
    if ex:
        ws = wb.create_sheet("노풍도")
        head(ws, 1, ["방위", "조도", "자동판정", "건물(동)", "건폐(%)", "10층↑(%)", "4~9층(%)", "수면(%)", "Kzr", "VH (m/s)",
                     "qH (N/㎡)", "근거"])
        bd = {r["dir"]: r for r in w.get("by_dir") or []}
        for i, r in enumerate(ex["sectors"], 2):
            b = bd.get(r["dir"], {})
            vals = [f"{r['dir']} {r['ko']}", r["cat"] + ("★" if r.get("star") else ""), r.get("auto"), r["n"],
                    round(r["cov"] * 100, 2), round(r["hi"] * 100, 2), round(r["mid"] * 100, 2), round(r["water"] * 100, 1),
                    round(b.get("Kzr", 0), 4), round(b.get("VH", 0), 2), round(b.get("qH", 0), 1), r["why"]]
            for j, v in enumerate(vals, 1):
                ws.cell(row=i, column=j, value=v)
        ws.cell(row=11, column=1, value=f"판정 반경 R = {ex['R']:.0f} m, 자료: {ex.get('source', '')}")
        ws.column_dimensions["L"].width = 70

    s = res.get("seismic") or {}
    ws = wb.create_sheet("시추조사")
    head(ws, 1, ["시추공", "사업명", "거리 (m)", "심도 (m)", "기반암 (m)", "Vs,soil (m/s)", "지반", "Fa", "Fv", "판정"])
    for i, r in enumerate((s.get("boreholes") or {}).get("holes", []), 2):
        h = r["hole"]
        vals = [h["code"], h.get("name") or h.get("project"), round(h.get("dist", 0), 1), round(r.get("depth") or 0, 1),
                None if r.get("rock_depth") is None else round(r["rock_depth"], 1),
                None if r.get("vs_soil") is None else round(r["vs_soil"], 0), r.get("site"),
                None if r.get("Fa") is None else round(r["Fa"], 3), None if r.get("Fv") is None else round(r["Fv"], 3),
                r.get("reason")]
        for j, v in enumerate(vals, 1):
            ws.cell(row=i, column=j, value=v)
    for col, wd in zip("ABCDEFGHIJ", (14, 30, 10, 10, 10, 12, 8, 8, 8, 40)):
        ws.column_dimensions[col].width = wd
    wb.save(path)


def save_composite_xlsx(path, c, radius=None, image=None):
    """취합 주상도 — 미터별 표 + 대표 주상 + 지하수위 (+ 그림)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from . import composite as CP
    wb = Workbook()
    hdr, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F2D4A")

    def head(ws, row, cols):
        for i, t in enumerate(cols, 1):
            cell = ws.cell(row=row, column=i, value=t)
            cell.font, cell.fill = hdr, fill

    ws = wb.active
    ws.title = "요약"
    for i, line in enumerate(CP.text(c, radius).split("\n"), 1):
        ws.cell(row=i, column=1, value=line)
    ws.column_dimensions["A"].width = 120
    ws = wb.create_sheet("대표주상")
    head(ws, 1, ["상단 GL−m", "하단 GL−m", "지층", "비율(%)", "N 평균", "N 최소", "N 최대", "N 근거", "Vs (m/s)", "Vs 근거", "공수"])
    for i, p in enumerate(c.get("profile") or [], 2):
        for j, v in enumerate([p["top"], p["bot"], p["label"], round(p["pct"] * 100, 1), p["N"], p["N_min"], p["N_max"],
                               p["N_src"], p["Vs"], p["Vs_src"], p["n"]], 1):
            ws.cell(row=i, column=j, value=round(v, 2) if isinstance(v, float) else v)
    ws = wb.create_sheet("미터별")
    cls_cols = list(CP.CLS_ORDER)
    head(ws, 1, ["상단", "하단", "공수", "대표", "N 최소", "N 평균", "N 최대", "N 근거", "Vs 최소", "Vs 평균", "Vs 최대", "Vs 근거"]
         + [CP.CLS_KO[k] + "(공)" for k in cls_cols])
    for i, r in enumerate(c.get("rows") or [], 2):
        N, V = r.get("N") or {}, r.get("Vs") or {}
        vals = [r["z0"], r["z1"], r["n"], CP.CLS_KO[r["rep"]], N.get("min"), N.get("mean"), N.get("max"), r["N_src"],
                V.get("min"), V.get("mean"), V.get("max"), r["Vs_src"]] + [r["dist"].get(k, 0) for k in cls_cols]
        for j, v in enumerate(vals, 1):
            ws.cell(row=i, column=j, value=round(v, 1) if isinstance(v, float) else v)
    ws = wb.create_sheet("지하수위")
    head(ws, 1, ["시추공", "거리 (m)", "지하수위 GL−m"])
    for i, it in enumerate((c.get("gwl") or {}).get("items") or [], 2):
        ws.cell(row=i, column=1, value=it["code"])
        ws.cell(row=i, column=2, value=round(it["dist"], 1))
        ws.cell(row=i, column=3, value=round(it["gwl"], 2))
    if image is not None:
        try:
            import io
            from openpyxl.drawing.image import Image as XLImage
            bio = io.BytesIO()
            image.save(bio, format="PNG")
            bio.seek(0)
            ws = wb.create_sheet("주상도")
            ws.add_image(XLImage(bio), "A1")
        except Exception:                            # noqa: BLE001
            pass
    wb.save(path)
