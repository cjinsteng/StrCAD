"""
design_2d/plan/model.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
평면해석 데이터 모델

  기하(먼저 그림)          →  부재 적용(나중에)
  ─────────────────────      ─────────────────────────
  노드 (node)              →  지점 (기둥/핀/고정/스프링)
  선   (line)              →  보 (단면·재료)
  면   (area, 노드 다각형) →  슬래브 (두께·재료)

  부재로 적용하지 않은 선·면에도 하중을 줄 수 있다.
    · 비구조 면의 하중 → 둘레 선으로 전달 (2방향/1방향X/1방향Y)
    · 비구조 선의 하중 → 슬래브 위면 슬래브로, 아니면 양 끝 노드로 전달

【단위】 좌표 m · 힘 kN · 단면/두께 mm · 면하중 kN/m² · 선하중 kN/m
【하중 부호】 입력은 중력방향(↓)이 +
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import copy
import json
import math

from ..section.model import (concrete_Ec, material_E, section_props, section_desc,
                             SECTION_SHAPES, SHAPE_LABEL, SHAPE_CODE, SHAPE_DIMS,
                             DIM_LABEL, parse_ids, ids_text, next_id)

FILE_EXT = ".2dp"
MODEL_VERSION = 1

AREA_DIST = [("two", "2방향"), ("x", "1방향 (X로 전달)"), ("y", "1방향 (Y로 전달)")]
AREA_DIST_LABEL = dict(AREA_DIST)
AREA_DIST_CODE = {v: k for k, v in AREA_DIST}


# ═══════════════════════════════════════════════════════════════
#  단면 비틀림 상수
# ═══════════════════════════════════════════════════════════════
def torsion_J(sec):
    """비틀림 상수 J [mm⁴]"""
    g = lambda k: float(sec.get(k, 0) or 0)
    sh = sec.get("shape", "rect")
    if sh == "rect":
        a, b = max(g("b"), g("h")), min(g("b"), g("h"))
        if a <= 0:
            return 0.0
        return a * b ** 3 * (1 / 3 - 0.21 * (b / a) * (1 - b ** 4 / (12 * a ** 4)))
    if sh == "H":
        H, B, tw, tf = g("H"), g("B"), g("tw"), g("tf")
        return (2 * B * tf ** 3 + (H - 2 * tf) * tw ** 3) / 3.0
    if sh == "box":
        H, B, t = g("H"), g("B"), g("t")
        if B + H - 2 * t <= 0:
            return 0.0
        return 2 * t * (B - t) ** 2 * (H - t) ** 2 / (B + H - 2 * t)
    if sh == "circle":
        return math.pi * g("D") ** 4 / 32.0
    if sh == "pipe":
        D, t = g("D"), g("t")
        return math.pi * (D ** 4 - (D - 2 * t) ** 4) / 32.0
    return section_props(sec)[1]        # 사용자 단면: J ≈ I


def support_desc(st):
    s = ["Dz" if st.get("dz") else "-",
         "Rx" if st.get("rx") else "-",
         "Ry" if st.get("ry") else "-"]
    extra = []
    if st.get("col"):
        extra.append(f"기둥 {float(st.get('col_b', 0)):g}×{float(st.get('col_h', 0)):g} "
                     f"H={float(st.get('col_H', 0)):g}m ×{int(st.get('col_n', 1))}")
    for k in ("kz", "krx", "kry"):
        if float(st.get(k, 0) or 0) > 0:
            extra.append(f"{k}={float(st[k]):g}")
    return " ".join(s) + (("  [" + ", ".join(extra) + "]") if extra else "")


def support_kind(st):
    if st.get("dz") and st.get("rx") and st.get("ry"):
        return "fix"
    if st.get("col"):
        return "col"
    if st.get("dz"):
        return "pin"
    return "spring"


# ═══════════════════════════════════════════════════════════════
#  기본 모델
# ═══════════════════════════════════════════════════════════════
def new_model():
    return {
        "version": MODEL_VERSION,
        "grid": 0.5,
        "mesh_size": 0.5,
        "torsion_factor": 1.0,
        "nodes": {},
        "lines": {},     # {id: {ni, nj, kind:"none"|"beam", sec, mat, name}}
        "areas": {},     # {id: {nodes:[...], kind:"none"|"slab", slab, dist, name}}
        "materials": {
            1: {"name": "C24", "type": "RC", "fck": 24.0, "fy": 400.0, "E": 0.0,
                "gamma": 24.0, "nu": 0.2},
            2: {"name": "SS275", "type": "STEEL", "fy": 275.0, "E": 210000.0,
                "gamma": 78.5, "nu": 0.3},
        },
        "sections": {
            1: {"name": "G1", "shape": "rect", "b": 400, "h": 600},
            2: {"name": "B1", "shape": "rect", "b": 300, "h": 500},
            3: {"name": "H-400", "shape": "H", "H": 400, "B": 200, "tw": 8, "tf": 13},
        },
        "slabs": {
            1: {"name": "S1", "t": 150.0, "mat": 1},
            2: {"name": "S2", "t": 200.0, "mat": 1},
        },
        "sup_types": {
            1: {"name": "핀 (기둥)", "dz": 1, "rx": 0, "ry": 0, "kz": 0, "krx": 0, "kry": 0, "col": 0},
            2: {"name": "고정", "dz": 1, "rx": 1, "ry": 1, "kz": 0, "krx": 0, "kry": 0, "col": 0},
            3: {"name": "기둥 C1 (상하부)", "dz": 1, "rx": 0, "ry": 0, "kz": 0, "krx": 0, "kry": 0,
                "col": 1, "col_b": 500, "col_h": 500, "col_H": 3.5, "col_n": 2, "col_mat": 1},
        },
        "supports": {},          # 노드 지점 {node: sup_type}
        "line_supports": {},     # 선 지점(벽체) {line: sup_type}
        "cases": {1: {"name": "DL", "selfweight": 1.0}, 2: {"name": "LL", "selfweight": 0.0}},
        "combos": {1: {"name": "1.4D", "factors": {1: 1.4}},
                   2: {"name": "1.2D+1.6L", "factors": {1: 1.2, 2: 1.6}}},
        "nloads": [],    # {id, case, node, p}            (kN, ↓+)
        "lloads": [],    # {id, case, line, w1, w2}       (kN/m, ↓+)
        "aloads": [],    # {id, case, area, q}            (kN/m², ↓+)
        "defaults": {"mat": 1, "sec": 1, "slab": 1, "sup": 1},
    }


_INT_KEY_DICTS = ("nodes", "lines", "areas", "materials", "sections", "slabs",
                  "sup_types", "cases", "combos")


def normalize(m):
    base = new_model()
    for k, v in base.items():
        if k not in m:
            m[k] = copy.deepcopy(v)
    for k in _INT_KEY_DICTS:
        m[k] = {int(i): v for i, v in m.get(k, {}).items()}
    m["supports"] = {int(n): int(s) for n, s in m.get("supports", {}).items()}
    m["line_supports"] = {int(n): int(s) for n, s in m.get("line_supports", {}).items()}
    for c in m["combos"].values():
        c["factors"] = {int(i): float(f) for i, f in c.get("factors", {}).items()}
    for ln in m["lines"].values():
        ln["ni"] = int(ln["ni"]); ln["nj"] = int(ln["nj"])
        ln.setdefault("kind", "none"); ln.setdefault("name", "")
        ln["sec"] = int(ln.get("sec", 1)); ln["mat"] = int(ln.get("mat", 1))
    for a in m["areas"].values():
        a["nodes"] = [int(n) for n in a["nodes"]]
        a.setdefault("kind", "none"); a.setdefault("dist", "two"); a.setdefault("name", "")
        a["slab"] = int(a.get("slab", 1))
    for key, ref in (("nloads", "node"), ("lloads", "line"), ("aloads", "area")):
        for ld in m[key]:
            ld["case"] = int(ld["case"]); ld[ref] = int(ld[ref]); ld["id"] = int(ld["id"])
    return m


def to_json(m):
    return json.dumps(m, ensure_ascii=False, indent=1)


def from_json(text):
    return normalize(json.loads(text))


def next_load_id(m):
    ids = [ld["id"] for k in ("nloads", "lloads", "aloads") for ld in m[k]]
    return (max(ids) + 1) if ids else 1


# ═══════════════════════════════════════════════════════════════
#  기하 유틸
# ═══════════════════════════════════════════════════════════════
def line_length(m, lid):
    ln = m["lines"][lid]
    a, b = m["nodes"][ln["ni"]], m["nodes"][ln["nj"]]
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


def poly_xy(m, nodes):
    return [(m["nodes"][n]["x"], m["nodes"][n]["y"]) for n in nodes]


def poly_area(pts):
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def poly_centroid(pts):
    A = poly_area(pts)
    if abs(A) < 1e-12:
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    cx = cy = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % len(pts)]
        f = x1 * y2 - x2 * y1
        cx += (x1 + x2) * f; cy += (y1 + y2) * f
    return cx / (6 * A), cy / (6 * A)


def point_in_poly(x, y, pts):
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]; xj, yj = pts[j]
        if (yi > y) != (yj > y):
            xc = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < xc:
                inside = not inside
        j = i
    return inside


def area_of(m, aid):
    return abs(poly_area(poly_xy(m, m["areas"][aid]["nodes"])))


def find_node_at(m, x, y, tol=1e-6):
    for nid, n in m["nodes"].items():
        if abs(n["x"] - x) <= tol and abs(n["y"] - y) <= tol:
            return nid
    return None


def find_line(m, a, b):
    for lid, ln in m["lines"].items():
        if (ln["ni"], ln["nj"]) in ((a, b), (b, a)):
            return lid
    return None


def _seg_param(m, lid, x, y):
    """선 위 점의 매개변수 t (0~1)와 거리"""
    ln = m["lines"][lid]
    a, b = m["nodes"][ln["ni"]], m["nodes"][ln["nj"]]
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return 0.0, math.hypot(x - a["x"], y - a["y"])
    t = ((x - a["x"]) * dx + (y - a["y"]) * dy) / L2
    px, py = a["x"] + t * dx, a["y"] + t * dy
    return t, math.hypot(x - px, y - py)


# ═══════════════════════════════════════════════════════════════
#  편집
# ═══════════════════════════════════════════════════════════════
def add_node(m, x, y, split=True):
    """노드 추가. 기존 선 위에 놓이면 그 선을 분할한다."""
    x, y = round(float(x), 6), round(float(y), 6)
    nid = find_node_at(m, x, y)
    if nid is not None:
        return nid
    nid = next_id(m["nodes"])
    m["nodes"][nid] = {"x": x, "y": y}
    if split:
        for lid in list(m["lines"]):
            t, d = _seg_param(m, lid, x, y)
            if d < 1e-6 and 1e-9 < t < 1 - 1e-9:
                split_line(m, lid, nid)
                break
    return nid


def split_line(m, lid, nid):
    """선 lid 를 노드 nid 위치에서 분할. 면 꼭짓점·선하중도 함께 갱신."""
    ln = m["lines"][lid]
    a, b = ln["ni"], ln["nj"]
    p = m["nodes"][nid]
    t, _ = _seg_param(m, lid, p["x"], p["y"])
    L = line_length(m, lid)
    new = dict(ln); new["ni"] = nid; new["nj"] = b
    ln["nj"] = nid
    lid2 = next_id(m["lines"])
    m["lines"][lid2] = new
    if lid in m.get("line_supports", {}):
        m["line_supports"][lid2] = m["line_supports"][lid]
    # 선하중 분할 (사다리꼴 값 보간)
    extra = []
    for ld in m["lloads"]:
        if ld["line"] != lid:
            continue
        w1, w2 = float(ld["w1"]), float(ld["w2"])
        wm = w1 + (w2 - w1) * t
        n2 = dict(ld); n2["line"] = lid2; n2["w1"] = wm; n2["w2"] = w2
        ld["w2"] = wm
        extra.append(n2)
    for n2 in extra:
        n2["id"] = next_load_id(m)
        m["lloads"].append(n2)
    # 면 꼭짓점에 삽입
    for ar in m["areas"].values():
        ns = ar["nodes"]
        for i in range(len(ns)):
            u, v = ns[i], ns[(i + 1) % len(ns)]
            if (u, v) == (a, b) or (u, v) == (b, a):
                ns.insert(i + 1, nid)
                break
    return lid2


def _seg_intersect(p1, p2, p3, p4):
    """선분 p1p2 와 p3p4 의 교점 매개변수 (t, u) — 내부 교차만"""
    d = (p2[0] - p1[0]) * (p4[1] - p3[1]) - (p2[1] - p1[1]) * (p4[0] - p3[0])
    if abs(d) < 1e-12:
        return None
    t = ((p3[0] - p1[0]) * (p4[1] - p3[1]) - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d
    u = ((p3[0] - p1[0]) * (p2[1] - p1[1]) - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d
    if 1e-9 < t < 1 - 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return t, u
    return None


def add_line(m, ni, nj, kind="none", sec=None, mat=None, name=""):
    """선 추가. 다른 선과 교차하면 교점에 노드를 만들어 양쪽을 분할한다.
    지나가는 기존 노드에서도 분할. 반환: 생성/기존 선 id 리스트"""
    if ni == nj:
        return []
    d = m["defaults"]
    pa = (m["nodes"][ni]["x"], m["nodes"][ni]["y"])
    pb = (m["nodes"][nj]["x"], m["nodes"][nj]["y"])
    cuts = []   # (t, nid)
    for lid in list(m["lines"]):
        ln = m["lines"][lid]
        if ni in (ln["ni"], ln["nj"]) and nj in (ln["ni"], ln["nj"]):
            continue
        p3 = (m["nodes"][ln["ni"]]["x"], m["nodes"][ln["ni"]]["y"])
        p4 = (m["nodes"][ln["nj"]]["x"], m["nodes"][ln["nj"]]["y"])
        r = _seg_intersect(pa, pb, p3, p4)
        if r is None:
            continue
        t, u = r
        x = pa[0] + t * (pb[0] - pa[0]); y = pa[1] + t * (pb[1] - pa[1])
        cuts.append((t, add_node(m, x, y)))
    # 선 위를 지나는 기존 노드
    L2 = (pb[0] - pa[0]) ** 2 + (pb[1] - pa[1]) ** 2
    for nid, n in m["nodes"].items():
        if nid in (ni, nj):
            continue
        t = ((n["x"] - pa[0]) * (pb[0] - pa[0]) + (n["y"] - pa[1]) * (pb[1] - pa[1])) / L2
        if 1e-9 < t < 1 - 1e-9:
            px = pa[0] + t * (pb[0] - pa[0]); py = pa[1] + t * (pb[1] - pa[1])
            if math.hypot(px - n["x"], py - n["y"]) < 1e-6:
                cuts.append((t, nid))
    pts = [ni] + [n for _, n in sorted(set(cuts))] + [nj]
    out = []
    for a, b in zip(pts[:-1], pts[1:]):
        if a == b:
            continue
        lid = find_line(m, a, b)
        if lid is None:
            lid = next_id(m["lines"])
            m["lines"][lid] = {"ni": a, "nj": b, "kind": kind, "name": name,
                               "sec": sec or d.get("sec", 1), "mat": mat or d.get("mat", 1)}
        out.append(lid)
    return out


def add_area(m, nodes, kind="none", slab=None, name=""):
    """면 추가 (반시계 방향으로 정렬). 같은 꼭짓점 집합이 있으면 기존 id."""
    nodes = [int(n) for n in nodes]
    if len(nodes) < 3 or len(set(nodes)) != len(nodes):
        return None
    if poly_area(poly_xy(m, nodes)) < 0:
        nodes = nodes[::-1]
    for aid, a in m["areas"].items():
        if set(a["nodes"]) == set(nodes):
            return aid
    aid = next_id(m["areas"])
    m["areas"][aid] = {"nodes": nodes, "kind": kind, "name": name, "dist": "two",
                       "slab": slab or m["defaults"].get("slab", 1)}
    return aid


def delete_nodes(m, nids):
    nids = set(nids)
    delete_lines(m, [lid for lid, ln in m["lines"].items() if ln["ni"] in nids or ln["nj"] in nids])
    delete_areas(m, [aid for aid, a in m["areas"].items() if nids & set(a["nodes"])])
    for n in nids:
        m["nodes"].pop(n, None)
        m["supports"].pop(n, None)
    m["nloads"] = [ld for ld in m["nloads"] if ld["node"] not in nids]


def delete_lines(m, lids):
    lids = set(lids)
    for l in lids:
        m["lines"].pop(l, None)
        m["line_supports"].pop(l, None)
    m["lloads"] = [ld for ld in m["lloads"] if ld["line"] not in lids]


def delete_areas(m, aids):
    aids = set(aids)
    for a in aids:
        m["areas"].pop(a, None)
    m["aloads"] = [ld for ld in m["aloads"] if ld["area"] not in aids]


def generate_grid(m, xs_sp, ys_sp, beams=True, slabs=True, sec=None, slab=None,
                  sup=1, x0=0.0, y0=0.0):
    """경간 리스트로 격자 생성: 노드·선(보)·면(슬래브)·지점"""
    xs = [x0]
    for s in xs_sp:
        xs.append(xs[-1] + float(s))
    ys = [y0]
    for s in ys_sp:
        ys.append(ys[-1] + float(s))
    g = {}
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            g[(i, j)] = add_node(m, x, y, split=False)
    kind = "beam" if beams else "none"
    for j in range(len(ys)):
        for i in range(len(xs) - 1):
            add_line(m, g[(i, j)], g[(i + 1, j)], kind=kind, sec=sec)
    for i in range(len(xs)):
        for j in range(len(ys) - 1):
            add_line(m, g[(i, j)], g[(i, j + 1)], kind=kind, sec=sec)
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            add_area(m, [g[(i, j)], g[(i + 1, j)], g[(i + 1, j + 1)], g[(i, j + 1)]],
                     kind="slab" if slabs else "none", slab=slab)
    if sup:
        for k in g.values():
            m["supports"][k] = sup
    return g


def copy_nodes(m, nids, dx, dy, times=1, lines=True, areas=True, extras=False):
    """노드 복사 (선·면·지점·하중 포함 옵션). 반환 (새 노드, 새 선, 새 면)"""
    nids = [n for n in nids if n in m["nodes"]]
    S = set(nids)
    src_l = [l for l, ln in m["lines"].items() if ln["ni"] in S and ln["nj"] in S] if lines else []
    src_a = [a for a, ar in m["areas"].items() if set(ar["nodes"]) <= S] if areas else []
    nn, nl, na = set(), set(), set()
    for k in range(1, int(times) + 1):
        cur = {}
        for n in nids:
            p = m["nodes"][n]
            cur[n] = add_node(m, p["x"] + dx * k, p["y"] + dy * k)
            nn.add(cur[n])
            if extras:
                if n in m["supports"]:
                    m["supports"][cur[n]] = m["supports"][n]
                for ld in [l for l in m["nloads"] if l["node"] == n]:
                    x = dict(ld); x["node"] = cur[n]; x["id"] = next_load_id(m); m["nloads"].append(x)
        for l in src_l:
            ln = m["lines"][l]
            for nl_id in add_line(m, cur[ln["ni"]], cur[ln["nj"]], kind=ln["kind"],
                                  sec=ln["sec"], mat=ln["mat"], name=ln.get("name", "")):
                nl.add(nl_id)
                if extras:
                    for ld in [x for x in m["lloads"] if x["line"] == l]:
                        y = dict(ld); y["line"] = nl_id; y["id"] = next_load_id(m); m["lloads"].append(y)
        for a in src_a:
            ar = m["areas"][a]
            aid = add_area(m, [cur[n] for n in ar["nodes"]], kind=ar["kind"], slab=ar["slab"],
                           name=ar.get("name", ""))
            if aid is not None:
                m["areas"][aid]["dist"] = ar.get("dist", "two")
                na.add(aid)
                if extras:
                    for ld in [x for x in m["aloads"] if x["area"] == a]:
                        y = dict(ld); y["area"] = aid; y["id"] = next_load_id(m); m["aloads"].append(y)
    return nn, nl, na


def move_nodes(m, nids, dx, dy):
    S = set(n for n in nids if n in m["nodes"])
    for n in S:
        p = m["nodes"][n]
        o = find_node_at(m, p["x"] + dx, p["y"] + dy)
        if o is not None and o not in S:
            return f"N{n} 이동 위치에 노드 N{o} 가 이미 있습니다."
    for n in S:
        p = m["nodes"][n]
        p["x"] = round(p["x"] + dx, 6); p["y"] = round(p["y"] + dy, 6)
    return None
