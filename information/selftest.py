"""
information/selftest.py — 계산부 자체 점검  (python -m information.selftest)
"""
import math
import os
import sys
import tempfile


def _close(a, b, tol=1e-3):
    return abs(a - b) <= tol * max(1.0, abs(b))


def run():
    from . import boreholes as BH
    from . import geo, maps, seismic as SE, snow as SN, wind as W
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  OK  " if cond else "  FAIL") + "  " + name)
        ok &= bool(cond)

    print("[풍하중]")
    check("Kzr C, z≤10 = 1.00", _close(W.kzr(8, "C"), 1.0))
    check("Kzr B, z=50 = 0.45·50^0.22", _close(W.kzr(50, "B"), 0.45 * 50 ** 0.22))
    check("Iz C, z≤zb = 0.1·(10/350)^-0.2", _close(W.iz(5, "C"), 0.1 * (10 / 350) ** -0.2))
    d = W.design_wind(30, "C", 10, "2")
    check("qH = ½·1.225·VH²", _close(d["qH"], 0.5 * 1.225 * d["VH"] ** 2))
    check("초고층 Iw 1.05", W.iw("2", floors=50) == 1.05)
    r = W.kzt_from_params("escarpment", 60, 150, 100, 10, "C")
    exp = 1 + 1.4 * (1 - 100 / (1.5 * 300)) * (1 - 10 / 150) * 0.2 / (1 + 3.7 * W.iz(10, "C"))
    check("Kzt 경사지 풍하측 (식 5.5-3, s=(1-|x|/1.5L*)(1-z/Lu))", _close(r["Kzt"], exp))
    r = W.kzt_from_params("hill", 100, 100, -50, 20, "C", theta_d=0.25)    # φ = 0.5 > 0.3
    kt = min(1.4 + 3.6 * (0.25 - 0.05), 3.2)
    exp = 1 + kt * (1 - 50 / (1.5 * 170)) * (1 - 0.6 * 20 / 100) * 0.3 / (1 + 3.7 * W.iz(20, "C"))
    check("Kzt 언덕 풍상측 φ>0.3 (L*=1.7H, 1-0.6z/H, φ′=0.3)", _close(r["Kzt"], exp))
    check("Kzt 적용범위 밖 = 1", W.kzt_from_params("hill", 50, 200, -2000, 10, "C")["Kzt"] == 1.0)
    prof = [(i * 30.0, 30 + 120 * math.exp(-((i * 30.0 - 396) / 450) ** 2)) for i in range(-100, 70)]
    r = W.analyze_profile(prof, 10, "C")
    check("지형단면 — 풍상측 사면 언덕 인식", r["kind"] == "hill" and r["x"] < 0 and 1.0 < r["Kzt"] < 1.1)

    print("[지진하중]")
    check("서울 → I", SE.seismic_zone("서울특별시 강남구")[0] == "I")
    check("강원 춘천 → II", SE.seismic_zone("강원특별자치도 춘천시")[0] == "II")
    check("강원 강릉 → I", SE.seismic_zone("강원도 강릉시")[0] == "I")
    check("제주 → II", SE.seismic_zone("제주특별자치도 서귀포시")[0] == "II")
    check("경기 광주 → I (광주광역시와 구분)", SE.seismic_zone("경기도 광주시")[1].startswith("경기"))
    e = SE.evaluate("I", "2", "S4")
    check("S4, S=0.22 → SDS 0.499, SD1 0.287", _close(e["spectrum"]["SDS"], 0.4987, 2e-3)
          and _close(e["spectrum"]["SD1"], 0.2875, 2e-3))
    check("S4 내진등급 II → 범주 D", e["SDC"] == "D")
    check("지반 S1 (기반암 2m)", SE.classify_site(2, None)[0] == "S1")
    check("지반 S3 (12m, 220)", SE.classify_site(12, 220)[0] == "S3")
    check("지반 S5 (25m, 170)", SE.classify_site(25, 170)[0] == "S5")
    check("위험지도 하한 80%", _close(SE.effective_s("I", 0.15, True)["S"], 0.176))

    print("[설하중]")
    sg, _ = SN.ground_snow(0.3)
    check("최소 지상설하중 0.5", sg == 0.5)
    r = SN.roof_snow(2.0, 1.0, 1.0, "1", slope_deg=0)
    check("Sf = 0.7·Is·Sg", _close(r["Sf"], 0.7 * 1.1 * 2.0))
    check("Cs 비난방 미끄럽지 않음 45°까지 1.0", SN.slope_factor(40, 1.2) == 1.0)

    print("[좌표·시추]")
    x, y = geo.tm_forward(37.5665, 126.978, geo.CRS["EPSG:5186"])
    la, lo = geo.to_wgs84(x, y, "EPSG:5186")
    check("TM 5186 왕복", _close(la, 37.5665, 1e-7) and _close(lo, 126.978, 1e-7))
    check("N 50/10 → 150 (상한 100)", BH.n_value(50, 10) == 100.0)
    check("지층 분류", BH.classify_layer("연암") == "rock_soft" and BH.classify_layer("퇴적층(모래)") == "sand")
    with tempfile.TemporaryDirectory() as td:
        db = BH.BoreholeDB(os.path.join(td, "t.db"))
        db.save_hole({"code": "T1", "lat": 37.5, "lon": 127.0, "depth": 30},
                     [{"top": 0, "bot": 8, "name": "퇴적층(모래)"}, {"top": 8, "bot": 25, "name": "풍화토"},
                      {"top": 25, "bot": 30, "name": "연암"}],
                     [{"depth": d, "blows": min(4 + d * 2, 50), "pen": 30} for d in range(1, 25, 2)])
        hs = db.search(37.5005, 127.0, 200)
        L, S = db.detail("T1")
        res = BH.analyze_hole(hs[0], L, S, {"vs_corr": "imai", "bedrock_rule": "soft"})
        check("시추공 반경검색·지반분류 S4", len(hs) == 1 and res["site"] == "S4" and _close(res["rock_depth"], 25))

    print("[지도 격자]")
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (400, 500), "white")
        ImageDraw.Draw(img).line([(200, 0), (200, 500)], fill="black", width=2)
        f = lambda la, lo: ((lo - 124) * 55, (38.9 - la) * 85)  # noqa: E731
        pts = [(*f(la, lo), la, lo) for _, la, lo in maps.KNOWN_CITIES[:5]]
        g = maps.Georef(pts)
        lab, vals, leaks = maps.build_labels(img, [(100, 250, 30), (300, 250, 36)])
        grid, uniq, size = maps.labels_to_grid(lab, vals, g)
        old = maps.MAP_DIR
        with tempfile.TemporaryDirectory() as td:
            maps.MAP_DIR = __import__("pathlib").Path(td)
            maps._CACHE.clear()
            maps.save_grid("wind", grid, uniq, size, {"points": pts})
            v1, _ = maps.lookup("wind", 37.5665, 126.978)        # 서울 (선 왼쪽)
            v2, _ = maps.lookup("wind", 35.1796, 129.0756)       # 부산 (선 오른쪽)
            maps.MAP_DIR = old
            maps._CACHE.clear()
        check("지도 조회 (서울 30, 부산 36)", v1 == 30 and v2 == 36 and not leaks)
    except ImportError:
        print("  (PIL/numpy 없음 — 지도 점검 생략)")
    print("[내장 KDS 지도]")
    old = maps.MAP_DIR
    maps.MAP_DIR = __import__("pathlib").Path(tempfile.gettempdir()) / "no_user_maps"
    maps._CACHE.clear()
    v, how = maps.lookup("seismic", 37.5665, 126.978)
    check("국가지진위험지도 서울 ≈ 16 %g (내장 격자)", v is not None and 15.5 < v < 17.0)
    v, _ = maps.lookup("seismic", 35.8714, 128.6014)
    check("국가지진위험지도 대구 ≈ 19 %g", v is not None and 18.5 < v <= 19.0)
    maps.MAP_DIR = old
    maps._CACHE.clear()
    for k in ("wind", "snow", "seismic"):
        x, y, _ = maps.kds_to_px(k, 36.35, 127.38)
        la, lo = maps.kds_to_ll(k, x, y)
        check(f"지도 핀 왕복 ({k})", abs(la - 36.35) < 1e-6 and abs(lo - 127.38) < 1e-6)
    check("울릉도 인셋 값 (풍속 46)", maps.kds_inset_value("wind", 37.48, 130.9)[0] == 46)
    w = maps.kds_value("wind", 37.5665, 126.978)
    check("기본풍속 서울 = 28 (내륙)", w["max"] == 28 and abs(w["interp"] - 28) < 0.3)
    w = maps.kds_value("wind", 35.1796, 129.0756)
    check("기본풍속 부산 40~42 사이 → 큰 값 42", w["max"] == 42 and 40 < w["interp"] <= 42)
    w = maps.kds_value("wind", 33.4996, 126.5312)
    check("기본풍속 제주 48~50", w["max"] == 50 and 48 <= w["interp"] <= 50)
    n = maps.kds_value("snow", 36.35, 127.38)
    check("지상설하중 대전 0.5 (최소)", n["max"] == 0.5)
    e = maps.kds_value("seismic", 37.5665, 126.978)
    check("지진 올림 = 위 등고선", e["max"] == math.ceil(e["interp"]))

    print("[취합 주상도]")
    from . import composite as CP
    from . import boreholes as BH2
    check("지층 분류 (사층·사력층·니층·풍화대)", BH2.classify_layer("사층") == "sand" and BH2.classify_layer("사력층") == "gravel"
          and BH2.classify_layer("니층") == "clay" and BH2.classify_layer("풍화대") == "soil_weathered"
          and BH2.classify_layer("퇴적층", "CL") == "clay")
    check("N 추정 (보통조밀-조밀 → 30)", CP.est_n("sand", "실트질 모래 보통조밀-조밀함") == 30)
    hs = [{"code": f"H{i}", "dist": 50.0 * i, "gwl": -2.0 - i, "depth": 20.0} for i in range(1, 4)]
    det = {f"H{i}": ([{"top": 0, "bot": 2, "name": "매립층"}, {"top": 2, "bot": 8 + i, "name": "점토층"},
                      {"top": 8 + i, "bot": 15, "name": "풍화암층"}, {"top": 15, "bot": 20, "name": "연암층"}], [], [])
           for i in range(1, 4)}
    c = CP.build(hs, det)
    tops = [p["top"] for p in c["profile"]]
    check("대표 주상 지층군 중앙값 (풍화암 GL-10, 연암 GL-15)", any(abs(t - 10) < 1e-6 for t in tops) and any(abs(t - 15) < 1e-6 for t in tops))
    check("지하수위 중앙 GL-4.0", abs(c["gwl"]["med"] - 4.0) < 1e-6)
    check("취합 주상도 그림", CP.render(c).height > 300)

    print("[노풍도]")
    from . import exposure as X
    check("판정 반경 40H·3km 중 작은 값", X.radius_m(50) == 2000 and X.radius_m(100) == 3000 and X.radius_m(50, "max") == 3000)
    check("방위 구간 N/NE/S", X.sector_of(10) == 0 and X.sector_of(30) == 1 and X.sector_of(200) == 4)
    check("조도 판정 A/B/C/D", X.classify(0.35, 0.2, 0.05, 0)[0] == "A" and X.classify(0.15, 0, 0, 0)[0] == "B"
          and X.classify(0.05, 0, 0, 0)[0] == "C" and X.classify(0.0, 0, 0, 0.8)[0] == "D")
    print("결과:", "모두 통과" if ok else "실패 있음")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
