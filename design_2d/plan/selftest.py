"""
design_2d/plan/selftest.py — 평면 FEM 검증 (판 이론해·보 손계산·평형)
    python -m design_2d.plan.selftest
"""
import math
import numpy as np
from . import model as pm
from .solver import analyze, summary, PlanError
from .mesh import find_face

FAILS = []


def chk(name, got, exp, tol=0.03):
    ok = abs(got - exp) <= tol * max(abs(exp), 1e-9)
    print(("OK  " if ok else "FAIL"), name, f"{got:.6g}", "기대", f"{exp:.6g}", f"({(got/exp-1)*100 if exp else 0:+.2f}%)")
    if not ok:
        FAILS.append(name)


def plate_model(a=6.0, t=150, q=10.0, edge="pin", size=0.25):
    m = pm.new_model()
    m["mesh_size"] = size
    m["cases"][1]["selfweight"] = 0.0
    m["materials"][1]["nu"] = 0.3
    m["materials"][1]["E"] = 30000.0
    m["slabs"][1]["t"] = t
    g = pm.generate_grid(m, [a], [a], beams=False, slabs=True, sup=None)
    st = 1 if edge == "pin" else 2
    for lid in m["lines"]:
        m["line_supports"][lid] = st
    aid = next(iter(m["areas"]))
    m["aloads"].append(dict(id=1, case=1, area=aid, q=q))
    return m, aid


def D_of(t, E=30000e3, nu=0.3):
    t = t / 1000
    return E * t ** 3 / (12 * (1 - nu ** 2))


# 1) 단순지지 정사각형 판, 등분포: w = 0.00406 qa⁴/D, Mc = 0.0479 qa²
m, aid = plate_model(edge="pin", t=60)
r = analyze(m); res = r["results"][("case", 1)]; mesh = r["mesh"]
D = D_of(60); a = 6.0; q = 10.0
c = np.argmin(np.hypot(mesh.xy[:, 0] - 3, mesh.xy[:, 1] - 3))
chk("SS 판 중앙 처짐", -res["w"][c], 0.00406 * q * a ** 4 / D)
chk("SS 판 중앙 Mx", res["Mx"][c], 0.0479 * q * a * a, 0.04)
chk("SS 판 중앙 My", res["My"][c], 0.0479 * q * a * a, 0.04)
tot = sum(v["Rz"] for v in res["line_react"].values())
chk("SS 판 반력 합", tot, q * a * a, 1e-6)
# 2) 고정 정사각형 판: w = 0.00126 qa⁴/D, Mc = 0.0231 qa², 변 중앙 = -0.0513 qa²
m, aid = plate_model(edge="fix", t=60)
r = analyze(m); res = r["results"][("case", 1)]; mesh = r["mesh"]
c = np.argmin(np.hypot(mesh.xy[:, 0] - 3, mesh.xy[:, 1] - 3))
e = np.argmin(np.hypot(mesh.xy[:, 0] - 0, mesh.xy[:, 1] - 3))
chk("고정 판 중앙 처짐", -res["w"][c], 0.00126 * q * a ** 4 / D, 0.04)
chk("고정 판 중앙 Mx", res["Mx"][c], 0.0231 * q * a * a, 0.06)
chk("고정 판 변중앙 Mx", res["Mx"][e], -0.0513 * q * a * a, 0.10)   # 메시 0.25m (6m 판 24분할)
# 3) 보 하나: 양단 핀 지점, 등분포 선하중 → M = wL²/8, δ = 5wL⁴/384EI
m = pm.new_model(); m["cases"][1]["selfweight"] = 0; m["mesh_size"] = 0.5
n1 = pm.add_node(m, 0, 0); n2 = pm.add_node(m, 8, 0)
l = pm.add_line(m, n1, n2, kind="beam", sec=1)[0]
m["supports"] = {n1: 1, n2: 1}
m["lloads"].append(dict(id=1, case=1, line=l, w1=20, w2=20))
r = analyze(m); res = r["results"][("case", 1)]
bd = res["beams"][l]
chk("보 Mmax", bd["M"].max(), 20 * 64 / 8, 0.01)
chk("보 V단부", abs(bd["V"][0]), 80, 0.01)
chk("보 M 중앙(포물선)", bd["M"][np.argmin(np.abs(bd["s"] - 4))], 160, 0.001)
E = pm.concrete_Ec(24) * 1e3; I = 0.4 * 0.6 ** 3 / 12
chk("보 처짐", -res["w"].min(), 5 * 20 * 8 ** 4 / (384 * E * I), 0.01)
chk("보 반력", res["react"][n1][0], 80, 1e-6)
# 4) 보 위 슬래브 (2×2 격자, 기둥 핀): 평형
m = pm.new_model(); m["mesh_size"] = 0.5
pm.generate_grid(m, [6, 6], [5, 5], beams=True, slabs=True, sec=1, slab=1, sup=1)
for aid in m["areas"]:
    m["aloads"].append(dict(id=pm.next_load_id(m), case=2, area=aid, q=5.0))
r = analyze(m)
for key, exp in ((("case", 1), None), (("case", 2), 5.0 * 120)):
    res = r["results"][key]
    tot = sum(v[0] for v in res["react"].values())
    chk(f"격자 반력합 {key}", tot, r["applied"][key[1]], 1e-6)
chk("격자 LL 하중합", r["applied"][2], 600, 1e-9)
sw = 24 * 0.15 * 120 + 24 * 0.4 * 0.6 * (3 * 12 + 3 * 10)
chk("격자 DL 자중합", r["applied"][1], sw, 1e-6)
rs, rb = summary(r["results"][("combo", 2)], r["mesh"], m)
print("   슬래브 요약:", {k: round(v, 2) for k, v in rs[0].items()})
print("   보 요약:", {k: round(v, 2) for k, v in rb[0].items()})
# 5) 비구조 면 하중 전달 (사각 면, 4변 보)
for dist, exp_x in (("two", None), ("x", 0.0)):
    m = pm.new_model(); m["cases"][1]["selfweight"] = 0; m["mesh_size"] = 0.5
    g = pm.generate_grid(m, [8], [4], beams=True, slabs=False, sec=1, sup=1)
    aid = next(iter(m["areas"])); m["areas"][aid]["dist"] = dist
    m["aloads"].append(dict(id=1, case=1, area=aid, q=10.0))
    r = analyze(m); res = r["results"][("case", 1)]
    chk(f"비구조면({dist}) 하중합", r["applied"][1], 320, 1e-3)
    chk(f"비구조면({dist}) 반력합", sum(v[0] for v in res["react"].values()), 320, 1e-3)
    # 변별 전달량 직접 집계
    from .mesh import build_mesh, LoadBuilder
    lb = LoadBuilder(m, build_mesh(m)); lb.F = np.zeros(len(lb.mesh.xy)); lb.BE = np.zeros((len(lb.mesh.beams), 2))
    got = {}
    orig = lb.point_on_edge
    def rec(a, b, t, P, _o=orig):
        k = "short" if m["nodes"][a]["x"] == m["nodes"][b]["x"] else "long"
        got[k] = got.get(k, 0) + P
    lb.point_on_edge = rec
    lb.area_transfer(aid, 10.0)
    if dist == "x":
        chk("1방향X: 짧은변(좌우)으로 전부", got.get("short", 0), 320, 1e-6)
    else:
        # 2방향 (8×4): 짧은 변 = 삼각형 2개 = 2·(4·2/2)·10 = 80
        chk("2방향: 짧은변 하중합", got.get("short", 0), 80, 0.02)
# 6) 면 자동 인식 + 교차선 분할
m = pm.new_model()
a1 = pm.add_node(m, 0, 0); a2 = pm.add_node(m, 6, 0); a3 = pm.add_node(m, 6, 4); a4 = pm.add_node(m, 0, 4)
for u, v in ((a1, a2), (a2, a3), (a3, a4), (a4, a1)):
    pm.add_line(m, u, v)
b1 = pm.add_node(m, 3, -1); b2 = pm.add_node(m, 3, 5); pm.add_line(m, b1, b2)
chk("교차 분할 선 개수", len(m["lines"]), 4 + 2 + 3)   # 사각 4변 중 2변 분할 → 6, 세로선 3
f = find_face(m, 1, 1)
chk("면 인식 꼭짓점", len(f), 4)
chk("면 인식 넓이", pm.area_of(m, pm.add_area(m, f)), 12, 1e-9)
# 7) 변 중간 노드가 있는 슬래브 + 이웃 면 분할수 맞춤
m = pm.new_model(); m["mesh_size"] = 0.7; m["cases"][1]["selfweight"] = 1
pm.generate_grid(m, [6, 6], [6], beams=True, slabs=True, sup=1)
big = pm.add_area(m, [])  # 잘못된 입력 무시
n_mid = pm.add_node(m, 9, 0)            # 오른쪽 아래 변 분할 → 면 꼭짓점 5개 (4 코너)
r = analyze(m)
chk("중간노드 슬래브 반력합", sum(v[0] for v in r["results"][("case", 1)]["react"].values()), r["applied"][1], 1e-6)
# 8) 밴드 솔버 = scipy/조밀 해 비교
from . import solver as S
rng = np.random.default_rng(1)
A = rng.random((30, 30)); A = A @ A.T + 30 * np.eye(30)
for i in range(30):
    for j in range(30):
        if abs(i - j) > 4: A[i, j] = 0
A = (A + A.T) / 2 + 30 * np.eye(30)
rr, cc = np.nonzero(A)
x = S._band_solve(rr, cc, A[rr, cc], 30, np.ones((30, 2)))
chk("밴드 솔버", float(np.abs(A @ x - 1).max()) + 1, 1, 1e-9)
print("\n전체 통과" if not FAILS else f"\n실패: {FAILS}")
