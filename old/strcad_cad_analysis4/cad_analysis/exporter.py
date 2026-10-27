"""Export analysis results: CSV (Excel), JSON, centreline DXF (R2004 / CP949 for ZWCAD)."""
from __future__ import annotations

import csv
import json
import math

import ezdxf

from .model import KIND_KO, SRC_KO


def _r(v, n=1):
    return None if v is None else round(v, n)


def to_rows(members, cs=None):
    rows = []
    for m in members:
        if m.kind == "column":
            x1, y1 = m.center
            x2 = y2 = None
            b, h = (m.diameter, m.diameter) if m.shape == "round" else (m.b, m.h)
        else:
            (x1, y1), (x2, y2) = m.p1, m.p2
            b, h = m.width, m.depth
        row = {
            "ID": m.id, "종류": KIND_KO[m.kind], "부재명": m.name, "이름근거": SRC_KO.get(m.name_source, ""),
            "크기": m.size_text(), "폭(b/B/t)": _r(b), "춤(h/D)": _r(h),
            "L_중심간(mm)": _r(m.length_cc) if m.kind != "column" else None,
            "ln_순경간(mm)": _r(m.length_clear) if m.kind != "column" else None,
            "X1": _r(x1), "Y1": _r(y1), "X2": _r(x2), "Y2": _r(y2),
            "i절점": m.node if m.kind == "column" else m.n1, "j절점": m.n2,
            "각도(°)": _r(m.angle, 2), "레이어": m.layer, "도면표기": " / ".join(m.labels), "비고": " / ".join(m.notes),
        }
        if cs:
            lx1, ly1 = cs.to_local(x1, y1)
            row.update({"x1_국부": _r(lx1), "y1_국부": _r(ly1)})
            if x2 is not None:
                lx2, ly2 = cs.to_local(x2, y2)
                row.update({"x2_국부": _r(lx2), "y2_국부": _r(ly2)})
        rows.append(row)
    return rows


def export_csv(path, members, cs=None):
    rows = to_rows(members, cs)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def export_json(path, result, cs=None):
    data = {
        "source": result.source_file,
        "coordinate_system": cs.to_dict() if cs else None,
        "members": [m.to_dict() for m in result.members],
        "layer_roles": result.layer_roles,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


LAYERS = {"column": ("CL-COLUMN", 1), "girder": ("CL-GIRDER", 5), "beam": ("CL-BEAM", 3), "wall": ("CL-WALL", 8)}


def export_dxf(path, members, text_height=250.0):
    doc = ezdxf.new("R2004")
    doc.header["$DWGCODEPAGE"] = "ANSI_949"
    doc.encoding = "cp949"
    doc.header["$INSUNITS"] = 4
    for name, color in LAYERS.values():
        doc.layers.add(name, color=color)
    doc.layers.add("CL-NAME", color=2)
    doc.layers.add("CL-OUTLINE", color=9)
    msp = doc.modelspace()
    for m in members:
        lay = LAYERS[m.kind][0]
        label = f"{m.name or '?'} {m.size_text()}"
        if m.kind == "column":
            cx, cy = m.center
            msp.add_point((cx, cy), dxfattribs={"layer": lay})
            msp.add_circle((cx, cy), 100, dxfattribs={"layer": lay})
            if m.polygon:
                msp.add_lwpolyline(m.polygon, close=True, dxfattribs={"layer": "CL-OUTLINE"})
            msp.add_text(label, height=text_height, dxfattribs={"layer": "CL-NAME"}).set_placement(
                (cx + 150, cy + 150))
            continue
        if m.curved and m.arc:
            a = m.arc
            msp.add_arc((a["cx"], a["cy"]), a["r"], math.degrees(a["a0"]), math.degrees(a["a1"]),
                        dxfattribs={"layer": lay})
            mid = (a["a0"] + a["a1"]) / 2
            pos = (a["cx"] + a["r"] * math.cos(mid), a["cy"] + a["r"] * math.sin(mid))
            rot = math.degrees(mid) - 90
        else:
            msp.add_line(m.p1, m.p2, dxfattribs={"layer": lay})
            pos = ((m.p1[0] + m.p2[0]) / 2, (m.p1[1] + m.p2[1]) / 2)
            rot = m.angle if m.angle <= 90 else m.angle - 180
        r = math.radians(rot)
        pos = (pos[0] - math.sin(r) * text_height * 0.8, pos[1] + math.cos(r) * text_height * 0.8)
        t = msp.add_text(f"{label} L={m.length_cc:.0f}", height=text_height,
                         dxfattribs={"layer": "CL-NAME", "rotation": rot})
        t.set_placement(pos, align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
    doc.saveas(path)
