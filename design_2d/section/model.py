"""
design_2d/section/model.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
단면해석(2D 프레임) 데이터 모델

【단위】
  좌표·길이 : m            단면 치수 : mm
  힘        : kN           모멘트    : kN·m
  탄성계수  : MPa (입력)   단위중량  : kN/m³

【좌표계】  X → 오른쪽,  Y → 위쪽 (화면과 반대, 해석 표준)

모델은 순수 dict 로 구성 → json 저장/불러오기 및 undo 스냅샷이 쉽다.
json 으로 저장하면 int 키가 str 로 바뀌므로 from_json() 에서 int 로 복원한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import copy
import json
import math

FILE_EXT = ".2df"
MODEL_VERSION = 1

# 하중 방향 코드
LOAD_DIRS = [
    ("G",  "↓ 중력 (-GY)"),
    ("GX", "GX (전체 X)"),
    ("GY", "GY (전체 Y)"),
    ("LX", "Lx (부재축)"),
    ("LY", "Ly (부재 직각)"),
]
LOAD_DIR_LABEL = dict(LOAD_DIRS)
LOAD_DIR_CODE = {v: k for k, v in LOAD_DIRS}

# ── 부재 단부 고정률 ──────────────────────────────────────────
#  fix_i / fix_j : 0 = 힌지(완전 해제), 1 = 강접, 0~1 = 반강접
#  (Monforton-Wu 고정도: r = 1/(1+3EI/(kL))  →  k = 3EI·r / (L·(1-r)))
DEFAULT_REL_TYPES = {
    1: {"name": "강접", "fi": 1.0, "fj": 1.0},
    2: {"name": "i단 힌지", "fi": 0.0, "fj": 1.0},
    3: {"name": "j단 힌지", "fi": 1.0, "fj": 0.0},
    4: {"name": "양단 힌지", "fi": 0.0, "fj": 0.0},
    5: {"name": "양단 반강접 0.5", "fi": 0.5, "fj": 0.5},
}


def clamp01(v):
    try:
        v = float(v)
    except Exception:
        return 1.0
    return min(1.0, max(0.0, v))


def end_fix(e):
    """부재 → (i단 고정률, j단 고정률)"""
    return clamp01(e.get("fix_i", 1.0)), clamp01(e.get("fix_j", 1.0))


def set_end_fix(e, fi=None, fj=None):
    if fi is not None:
        e["fix_i"] = round(clamp01(fi), 6)
    if fj is not None:
        e["fix_j"] = round(clamp01(fj), 6)


def is_rigid(e):
    fi, fj = end_fix(e)
    return fi >= 1.0 and fj >= 1.0


def rel_type_of(m, e):
    """부재 단부 고정률과 같은 단부조건 타입 id (없으면 None)"""
    fi, fj = end_fix(e)
    for rid, rt in m.get("rel_types", {}).items():
        if abs(clamp01(rt.get("fi", 1)) - fi) < 1e-9 and abs(clamp01(rt.get("fj", 1)) - fj) < 1e-9:
            return rid
    return None


def fix_text(v):
    v = clamp01(v)
    if v <= 0:
        return "힌지"
    if v >= 1:
        return "강접"
    return f"{v:g}"


def end_desc(fi, fj):
    return f"i: {fix_text(fi)} / j: {fix_text(fj)}"


SECTION_SHAPES = [
    ("rect",   "직사각형",  ["b", "h"]),
    ("H",      "H형강",     ["H", "B", "tw", "tf"]),
    ("box",    "각형강관",  ["H", "B", "t"]),
    ("circle", "원형",      ["D"]),
    ("pipe",   "원형강관",  ["D", "t"]),
    ("user",   "사용자",    ["A", "I"]),
]
SHAPE_LABEL = {k: lbl for k, lbl, _ in SECTION_SHAPES}
SHAPE_CODE = {lbl: k for k, lbl, _ in SECTION_SHAPES}
SHAPE_DIMS = {k: dims for k, _, dims in SECTION_SHAPES}
DIM_LABEL = {
    "b": "폭 b (mm)", "h": "춤 h (mm)", "H": "춤 H (mm)", "B": "폭 B (mm)",
    "tw": "웨브 tw (mm)", "tf": "플랜지 tf (mm)", "t": "두께 t (mm)",
    "D": "지름 D (mm)", "A": "면적 A (mm²)", "I": "단면2차 I (mm⁴)",
}


# ═══════════════════════════════════════════════════════════════
#  재료 / 단면 성질
# ═══════════════════════════════════════════════════════════════
def concrete_Ec(fck):
    """KDS 14 20 10 4.3.3  Ec = 0.077·mc^1.5·∛fcm  (mc=2300 → 8500∛fcm)
    fcm = fck + Δf,  Δf = 4 (fck≤40), 6 (fck≥60), 사이 직선보간  [MPa]"""
    fck = float(fck)
    if fck <= 40:
        df = 4.0
    elif fck >= 60:
        df = 6.0
    else:
        df = 4.0 + (fck - 40.0) * 2.0 / 20.0
    return 8500.0 * (fck + df) ** (1.0 / 3.0)


def material_E(mat):
    """재료 탄성계수 [MPa]. E 를 직접 넣었으면(>0) 그 값을 사용."""
    E = float(mat.get("E", 0) or 0)
    if E > 0:
        return E
    if mat.get("type") == "RC":
        return concrete_Ec(mat.get("fck", 24))
    return 210000.0   # KDS 41 30 10 강재 탄성계수


def section_props(sec):
    """단면 → (A [mm²], I [mm⁴]).  잘못된 치수면 (0, 0)."""
    g = lambda k: float(sec.get(k, 0) or 0)
    shape = sec.get("shape", "rect")
    try:
        if shape == "rect":
            b, h = g("b"), g("h")
            return b * h, b * h ** 3 / 12.0
        if shape == "H":
            H, B, tw, tf = g("H"), g("B"), g("tw"), g("tf")
            hw = H - 2 * tf
            A = 2 * B * tf + hw * tw
            I = (B * H ** 3 - (B - tw) * hw ** 3) / 12.0
            return A, I
        if shape == "box":
            H, B, t = g("H"), g("B"), g("t")
            A = B * H - (B - 2 * t) * (H - 2 * t)
            I = (B * H ** 3 - (B - 2 * t) * (H - 2 * t) ** 3) / 12.0
            return A, I
        if shape == "circle":
            D = g("D")
            return math.pi * D ** 2 / 4.0, math.pi * D ** 4 / 64.0
        if shape == "pipe":
            D, t = g("D"), g("t")
            d = D - 2 * t
            return (math.pi * (D ** 2 - d ** 2) / 4.0,
                    math.pi * (D ** 4 - d ** 4) / 64.0)
        if shape == "user":
            return g("A"), g("I")
    except Exception:
        pass
    return 0.0, 0.0


def section_desc(sec):
    shape = sec.get("shape", "rect")
    f = lambda k: f"{float(sec.get(k, 0) or 0):g}"
    if shape == "rect":
        return f"{f('b')}×{f('h')}"
    if shape == "H":
        return f"H-{f('H')}×{f('B')}×{f('tw')}×{f('tf')}"
    if shape == "box":
        return f"□-{f('H')}×{f('B')}×{f('t')}"
    if shape == "circle":
        return f"Ø{f('D')}"
    if shape == "pipe":
        return f"P-{f('D')}×{f('t')}"
    return f"A={f('A')}, I={f('I')}"


def support_desc(st):
    s = []
    s.append("Dx" if st.get("dx") else "-")
    s.append("Dy" if st.get("dy") else "-")
    if st.get("rz"):
        s.append("Rz")
    elif 0 < clamp01(st.get("fix", 0) or 0) < 1:
        s.append(f"Rz 고정률 {clamp01(st['fix']):g}")
    else:
        s.append("-")
    sp = []
    for k, lbl in (("kx", "kx"), ("ky", "ky"), ("kr", "kr")):
        if float(st.get(k, 0) or 0) > 0:
            sp.append(f"{lbl}={float(st[k]):g}")
    return " ".join(s) + (("  [" + ", ".join(sp) + "]") if sp else "")


def support_kind(st):
    """그리기용 지점 형상 분류"""
    dx, dy, rz = bool(st.get("dx")), bool(st.get("dy")), bool(st.get("rz"))
    fix = clamp01(st.get("fix", 0) or 0)
    if dx and dy and (rz or fix >= 1):
        return "fix"
    if dx and dy and fix > 0:
        return "semi"
    if dx and dy:
        return "pin"
    if dy and not dx:
        return "rollx"     # 수평 이동 가능
    if dx and not dy:
        return "rolly"     # 수직 이동 가능
    if rz:
        return "rot"
    if any(float(st.get(k, 0) or 0) > 0 for k in ("kx", "ky", "kr")):
        return "spring"
    return "free"


# ═══════════════════════════════════════════════════════════════
#  기본 모델
# ═══════════════════════════════════════════════════════════════
def new_model():
    return {
        "version": MODEL_VERSION,
        "title": "",
        "grid": 0.5,
        "nodes": {},
        "elems": {},
        "materials": {
            1: {"name": "C24", "type": "RC", "fck": 24.0, "fy": 400.0,
                "E": 0.0, "gamma": 24.0},
            2: {"name": "SS275", "type": "STEEL", "fy": 275.0,
                "E": 210000.0, "gamma": 78.5},
        },
        "sections": {
            1: {"name": "G1", "shape": "rect", "b": 400, "h": 600},
            2: {"name": "C1", "shape": "rect", "b": 500, "h": 500},
            3: {"name": "H-400", "shape": "H", "H": 400, "B": 200,
                "tw": 8, "tf": 13},
        },
        "sup_types": {
            1: {"name": "고정", "dx": 1, "dy": 1, "rz": 1, "fix": 0,
                "kx": 0, "ky": 0, "kr": 0},
            2: {"name": "힌지", "dx": 1, "dy": 1, "rz": 0, "fix": 0,
                "kx": 0, "ky": 0, "kr": 0},
            3: {"name": "롤러", "dx": 0, "dy": 1, "rz": 0, "fix": 0,
                "kx": 0, "ky": 0, "kr": 0},
            4: {"name": "반고정 0.5", "dx": 1, "dy": 1, "rz": 0, "fix": 0.5,
                "kx": 0, "ky": 0, "kr": 0},
        },
        "supports": {},          # {node_id: sup_type_id}
        "rel_types": copy.deepcopy(DEFAULT_REL_TYPES),   # 부재 단부조건 타입
        "cases": {
            1: {"name": "DL", "selfweight": 1.0},
            2: {"name": "LL", "selfweight": 0.0},
        },
        "combos": {
            1: {"name": "1.4D", "factors": {1: 1.4}},
            2: {"name": "1.2D+1.6L", "factors": {1: 1.2, 2: 1.6}},
        },
        "nloads": [],            # {"id","case","node","fx","fy","mz"}
        "eloads": [],            # {"id","case","elem","kind","dir","w1","w2","a","b","p","rel"}
        "defaults": {"mat": 1, "sec": 1, "sup": 1},
    }


_INT_KEY_DICTS = ("nodes", "elems", "materials", "sections",
                  "sup_types", "cases", "combos", "rel_types")


def normalize(m):
    """json 로드 후 str 키 → int 키 복원 + 누락 필드 보정"""
    base = new_model()
    for k, v in base.items():
        if k not in m:
            m[k] = copy.deepcopy(v) if k not in ("nodes", "elems", "nloads",
                                                  "eloads", "supports") else type(v)()
    for k in _INT_KEY_DICTS:
        m[k] = {int(i): v for i, v in m.get(k, {}).items()}
    m["supports"] = {int(n): int(s) for n, s in m.get("supports", {}).items()}
    for st in m["sup_types"].values():
        f = float(st.get("fix", 0) or 0)
        st["fix"] = f / 100.0 if f > 1 else f          # 구버전: % → 0~1
    for c in m["combos"].values():
        c["factors"] = {int(i): float(f) for i, f in c.get("factors", {}).items()}
    for e in m["elems"].values():
        e["ni"] = int(e["ni"]); e["nj"] = int(e["nj"])
        e.setdefault("name", "")
        # 구버전 rel_i/rel_j(힌지 여부) → 고정률
        if "fix_i" not in e:
            e["fix_i"] = 0.0 if e.get("rel_i") else 1.0
        if "fix_j" not in e:
            e["fix_j"] = 0.0 if e.get("rel_j") else 1.0
        e.pop("rel_i", None); e.pop("rel_j", None)
        set_end_fix(e, e["fix_i"], e["fix_j"])
        e["mat"] = int(e.get("mat", 1)); e["sec"] = int(e.get("sec", 1))
    for ld in m["nloads"]:
        ld["case"] = int(ld["case"]); ld["node"] = int(ld["node"])
    for ld in m["eloads"]:
        ld["case"] = int(ld["case"]); ld["elem"] = int(ld["elem"])
    return m


def to_json(m):
    return json.dumps(m, ensure_ascii=False, indent=1)


def from_json(text):
    return normalize(json.loads(text))


def next_id(d):
    return (max(d.keys()) + 1) if d else 1


def next_load_id(m):
    ids = [ld["id"] for ld in m["nloads"]] + [ld["id"] for ld in m["eloads"]]
    return (max(ids) + 1) if ids else 1


def elem_length(m, eid):
    e = m["elems"][eid]
    a, b = m["nodes"][e["ni"]], m["nodes"][e["nj"]]
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


def find_node_at(m, x, y, tol=1e-6):
    for nid, n in m["nodes"].items():
        if abs(n["x"] - x) <= tol and abs(n["y"] - y) <= tol:
            return nid
    return None


def add_node(m, x, y):
    nid = find_node_at(m, x, y)
    if nid is not None:
        return nid
    nid = next_id(m["nodes"])
    m["nodes"][nid] = {"x": round(float(x), 6), "y": round(float(y), 6)}
    return nid


def add_elem(m, ni, nj, mat=None, sec=None, name=""):
    if ni == nj:
        return None
    for eid, e in m["elems"].items():
        if {e["ni"], e["nj"]} == {ni, nj}:
            return eid
    d = m.get("defaults", {})
    eid = next_id(m["elems"])
    m["elems"][eid] = {"ni": ni, "nj": nj, "name": name,
                       "mat": mat or d.get("mat", 1),
                       "sec": sec or d.get("sec", 1),
                       "fix_i": 1.0, "fix_j": 1.0}
    return eid


def delete_nodes(m, nids):
    nids = set(nids)
    eids = [eid for eid, e in m["elems"].items()
            if e["ni"] in nids or e["nj"] in nids]
    delete_elems(m, eids)
    for nid in nids:
        m["nodes"].pop(nid, None)
        m["supports"].pop(nid, None)
    m["nloads"] = [ld for ld in m["nloads"] if ld["node"] not in nids]


def delete_elems(m, eids):
    eids = set(eids)
    for eid in eids:
        m["elems"].pop(eid, None)
    m["eloads"] = [ld for ld in m["eloads"] if ld["elem"] not in eids]


def purge_orphan_nodes(m):
    used = set()
    for e in m["elems"].values():
        used.update((e["ni"], e["nj"]))
    orphan = [n for n in m["nodes"] if n not in used
              and n not in m["supports"]
              and not any(ld["node"] == n for ld in m["nloads"])]
    for n in orphan:
        m["nodes"].pop(n, None)
    return orphan


def split_elem(m, eid, ratio):
    """부재를 ratio(0~1) 위치에서 분할. 부재하중은 위치에 맞게 재배치."""
    if not (0.0 < ratio < 1.0) or eid not in m["elems"]:
        return None
    e = m["elems"][eid]
    a, b = m["nodes"][e["ni"]], m["nodes"][e["nj"]]
    L = elem_length(m, eid)
    x = a["x"] + (b["x"] - a["x"]) * ratio
    y = a["y"] + (b["y"] - a["y"]) * ratio
    nid = add_node(m, x, y)
    nj_old = e["nj"]
    e2 = dict(e)
    e2["ni"] = nid; e2["nj"] = nj_old; e2["fix_i"] = 1.0
    e["nj"] = nid; e["fix_j"] = 1.0
    eid2 = next_id(m["elems"])
    m["elems"][eid2] = e2
    L1, L2 = L * ratio, L * (1 - ratio)
    new_loads = []
    for ld in m["eloads"]:
        if ld["elem"] != eid:
            new_loads.append(ld); continue
        if ld["kind"] == "point":
            pa = ld["a"] * L if ld.get("rel") else ld["a"]
            if pa <= L1:
                n = dict(ld); n["a"] = pa / L1 if ld.get("rel") else pa
                new_loads.append(n)
            else:
                n = dict(ld); n["elem"] = eid2
                n["a"] = (pa - L1) / L2 if ld.get("rel") else pa - L1
                new_loads.append(n)
        else:
            sa = ld["a"] * L if ld.get("rel") else ld["a"]
            sb = ld["b"] * L if ld.get("rel") else ld["b"]
            w = lambda s: ld["w1"] + (ld["w2"] - ld["w1"]) * (s - sa) / (sb - sa) if sb > sa else ld["w1"]
            if sa < L1:
                n = dict(ld); n["rel"] = False
                n["a"] = sa; n["b"] = min(sb, L1)
                n["w1"] = ld["w1"]; n["w2"] = w(min(sb, L1))
                new_loads.append(n)
            if sb > L1:
                n = dict(ld); n["rel"] = False; n["elem"] = eid2
                s0 = max(sa, L1)
                n["a"] = s0 - L1; n["b"] = sb - L1
                n["w1"] = w(s0); n["w2"] = ld["w2"]
                n["id"] = ld["id"] if sa >= L1 else None
                new_loads.append(n)
    for ld in new_loads:
        if ld.get("id") is None:
            ld["id"] = 0
    m["eloads"] = new_loads
    nid_max = next_load_id(m)
    for ld in m["eloads"]:
        if ld["id"] == 0:
            ld["id"] = nid_max; nid_max += 1
    return nid


def generate_frame(m, spans, heights, sec_beam=None, sec_col=None,
                   mat=None, sup=1, x0=0.0, y0=0.0):
    """경간 리스트·층고 리스트로 라멘 프레임 생성 (예: [6,6,6], [4,3.5])"""
    xs = [x0]
    for s in spans:
        xs.append(xs[-1] + float(s))
    ys = [y0]
    for h in heights:
        ys.append(ys[-1] + float(h))
    grid = {}
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            grid[(i, j)] = add_node(m, x, y)
    for j in range(1, len(ys)):
        for i in range(len(xs)):
            add_elem(m, grid[(i, j - 1)], grid[(i, j)], mat=mat, sec=sec_col)
        for i in range(len(xs) - 1):
            add_elem(m, grid[(i, j)], grid[(i + 1, j)], mat=mat, sec=sec_beam)
    if sup:
        for i in range(len(xs)):
            m["supports"][grid[(i, 0)]] = sup
    return grid


# ═══════════════════════════════════════════════════════════════
#  노드 복사 / 이동
# ═══════════════════════════════════════════════════════════════
def parse_ids(text):
    """'1-4, 7, 9~10' → [1, 2, 3, 4, 7, 9, 10]"""
    out = []
    for tok in str(text).replace(" ", "").replace("~", "-").split(","):
        if not tok:
            continue
        if "-" in tok[1:]:
            a, b = tok.split("-", 1)
            a, b = int(a), int(b)
            out += list(range(min(a, b), max(a, b) + 1))
        else:
            out.append(int(tok))
    return sorted(set(out))


def ids_text(ids):
    """[1,2,3,4,7] → '1-4, 7'"""
    ids = sorted(set(ids))
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(f"{ids[i]}-{ids[j]}" if j - i >= 2 else
                   ", ".join(str(v) for v in ids[i:j + 1]))
        i = j + 1
    return ", ".join(out)


def copy_nodes(m, nids, dx, dy, times=1, elems=True, extras=False, link=False):
    """노드를 (dx, dy) 간격으로 times 번 복사.
    elems  : 두 노드가 모두 대상인 부재도 복사 (단면·재료·단부조건 포함)
    extras : 지점·절점하중·부재하중도 복사
    link   : 원본(이전) 노드와 복사 노드를 부재로 연결 (기본 재료·단면)
    반환: (새 노드 id 집합, 새 부재 id 집합)"""
    nids = [n for n in nids if n in m["nodes"]]
    src_e = [eid for eid, e in m["elems"].items()
             if e["ni"] in nids and e["nj"] in nids] if elems else []
    new_n, new_e = set(), set()
    prev = {n: n for n in nids}
    for k in range(1, int(times) + 1):
        cur = {}
        for n in nids:
            p = m["nodes"][n]
            cur[n] = add_node(m, p["x"] + dx * k, p["y"] + dy * k)
            new_n.add(cur[n])
            if extras:
                if n in m["supports"]:
                    m["supports"][cur[n]] = m["supports"][n]
                for ld in [l for l in m["nloads"] if l["node"] == n]:
                    nl = dict(ld); nl["node"] = cur[n]; nl["id"] = next_load_id(m)
                    m["nloads"].append(nl)
        for eid in src_e:
            e = m["elems"][eid]
            existed = set(m["elems"])
            ne = add_elem(m, cur[e["ni"]], cur[e["nj"]], mat=e["mat"], sec=e["sec"],
                          name=e.get("name", ""))
            if ne is None or ne in existed:
                continue
            set_end_fix(m["elems"][ne], *end_fix(e))
            new_e.add(ne)
            if extras:
                for ld in [l for l in m["eloads"] if l["elem"] == eid]:
                    nl = dict(ld); nl["elem"] = ne; nl["id"] = next_load_id(m)
                    m["eloads"].append(nl)
        if link:
            for n in nids:
                existed = set(m["elems"])
                mat, sec = _parallel_props(m, n, dx, dy)
                ne = add_elem(m, prev[n], cur[n], mat=mat, sec=sec)
                if ne is not None and ne not in existed:
                    new_e.add(ne)
        prev = cur
    return new_n, new_e


def _parallel_props(m, nid, dx, dy):
    """nid 에 연결된 부재 중 (dx, dy) 방향과 나란한 부재의 (재료, 단면).
    예: 기둥 위 노드를 위로 복사·연결하면 아래 기둥 단면을 그대로 사용. 없으면 (None, None)"""
    L0 = math.hypot(dx, dy)
    if L0 < 1e-12:
        return None, None
    for e in m["elems"].values():
        if nid not in (e["ni"], e["nj"]):
            continue
        a, b = m["nodes"][e["ni"]], m["nodes"][e["nj"]]
        ex, ey = b["x"] - a["x"], b["y"] - a["y"]
        L = math.hypot(ex, ey)
        if L > 1e-12 and abs(abs(ex * dx + ey * dy) / (L * L0) - 1.0) < 1e-6:
            return e["mat"], e["sec"]
    return None, None


def move_nodes(m, nids, dx, dy):
    """노드 이동. 이동 후 다른 노드와 겹치면 오류 메시지 반환."""
    nids = set(n for n in nids if n in m["nodes"])
    for n in nids:
        p = m["nodes"][n]
        other = find_node_at(m, p["x"] + dx, p["y"] + dy)
        if other is not None and other not in nids:
            return f"N{n} 이동 위치에 노드 N{other} 가 이미 있습니다."
    for n in nids:
        p = m["nodes"][n]
        p["x"] = round(p["x"] + dx, 6); p["y"] = round(p["y"] + dy, 6)
    return None
