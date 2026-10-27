"""DXF loading: flatten model space (incl. block references) into simple
per-layer primitives and build a layer summary for classification."""
from __future__ import annotations

import glob
import math
import os
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import ezdxf
from ezdxf import recover
from ezdxf import path as ezpath

from .model import Segment, Arc, TextItem

MAX_ENTITIES = 300_000


@dataclass
class LayerData:
    name: str
    counts: Counter = field(default_factory=Counter)
    segments: list = field(default_factory=list)      # [Segment]  (LINE + polyline straight parts)
    line_segments: list = field(default_factory=list) # [Segment]  (only LINE entities, for column loops)
    arcs: list = field(default_factory=list)          # [Arc]
    circles: list = field(default_factory=list)       # [(cx, cy, r)]
    polygons: list = field(default_factory=list)      # [[(x, y), ...]] closed polylines
    texts: list = field(default_factory=list)         # [TextItem]
    hatches: list = field(default_factory=list)       # [[(x, y), ...]] hatch boundary loops (filled areas)

    def summary(self, n_text: int = 8) -> dict:
        lens = sorted(s.length for s in self.segments)
        uniq = []
        for t in self.texts:
            if t.text not in uniq:
                uniq.append(t.text)
            if len(uniq) >= n_text:
                break
        return {
            "name": self.name,
            "entities": dict(self.counts),
            "n_texts": len(self.texts),
            "sample_texts": uniq,
            "median_line_length": round(lens[len(lens) // 2]) if lens else 0,
            "closed_polylines": len(self.polygons),
            "hatches": len(self.hatches),
        }


@dataclass
class DrawingData:
    path: str
    layers: dict            # name -> LayerData
    extents: tuple
    insunits: int = 0

    def layer_summaries(self) -> list:
        return [ld.summary() for ld in sorted(self.layers.values(), key=lambda l: l.name)]


# ----------------------------------------------------------------------------
def find_oda_converter() -> str | None:
    cands = [shutil.which("ODAFileConverter")]
    for pat in (r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
                r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe",
                "/usr/bin/ODAFileConverter", "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"):
        cands += sorted(glob.glob(pat))
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def dwg_to_dxf(path: str) -> str:
    """Convert DWG → DXF using ODA File Converter (free). Returns DXF path."""
    exe = find_oda_converter()
    if not exe:
        raise RuntimeError(
            "DWG 파일은 직접 읽을 수 없습니다.\n"
            "CAD에서 DXF로 저장하거나, 'ODA File Converter'(무료)를 설치하면 자동 변환됩니다.")
    src_dir = os.path.dirname(os.path.abspath(path))
    out_dir = tempfile.mkdtemp(prefix="strcad_dwg_")
    fname = os.path.basename(path)
    subprocess.run([exe, src_dir, out_dir, "ACAD2018", "DXF", "0", "1", fname],
                   check=True, timeout=600)
    out = os.path.join(out_dir, os.path.splitext(fname)[0] + ".dxf")
    if not os.path.exists(out):
        raise RuntimeError("ODA File Converter 변환 결과를 찾을 수 없습니다.")
    return out


def read_doc(path: str):
    if path.lower().endswith(".dwg"):
        path = dwg_to_dxf(path)
    try:
        doc = ezdxf.readfile(path)
    except Exception:
        doc, _auditor = recover.readfile(path)
    return doc


# ----------------------------------------------------------------------------
def _text_center(e, text: str, height: float, rot_deg: float):
    """Approximate visual centre of a TEXT entity."""
    ins = e.dxf.insert
    halign = e.dxf.get("halign", 0)
    valign = e.dxf.get("valign", 0)
    if (halign or valign) and e.dxf.hasattr("align_point"):
        ins = e.dxf.align_point
    w = max(len(text), 1) * height * 0.8
    r = math.radians(rot_deg)
    ux, uy = math.cos(r), math.sin(r)
    vx, vy = -uy, ux
    # along-text offset depending on horizontal alignment
    if halign in (1, 4):      # center / middle
        da = 0.0
    elif halign == 2:         # right
        da = -w / 2
    else:                     # left / aligned / fit
        da = w / 2
    dv = 0.0 if valign == 2 or halign == 4 else height / 2
    if valign == 3:
        dv = -height / 2
    return ins.x + ux * da + vx * dv, ins.y + uy * da + vy * dv


def _iter_flat(entities, depth=0, parent_layer=None):
    for e in entities:
        t = e.dxftype()
        if t == "INSERT":
            if depth > 5:
                continue
            try:
                ves = list(e.virtual_entities())
            except Exception:
                continue
            lay = e.dxf.layer
            for v in ves:
                if v.dxf.layer == "0":
                    v.dxf.layer = lay
            yield from _iter_flat(ves, depth + 1, lay)
        else:
            yield e


def load_drawing(path: str, progress=None) -> DrawingData:
    doc = read_doc(path)
    msp = doc.modelspace()
    layers: dict[str, LayerData] = {}
    xs, ys = [], []

    def L(name):
        ld = layers.get(name)
        if ld is None:
            ld = layers[name] = LayerData(name)
        return ld

    n = 0
    for e in _iter_flat(msp):
        n += 1
        if n > MAX_ENTITIES:
            break
        t = e.dxftype()
        try:
            lay = e.dxf.layer
        except Exception:
            continue
        ld = L(lay)
        ld.counts[t] += 1
        try:
            if t == "LINE":
                s, q = e.dxf.start, e.dxf.end
                seg = Segment(s.x, s.y, q.x, q.y, lay)
                if seg.length > 1.0:
                    ld.segments.append(seg)
                    ld.line_segments.append(seg)
                    xs += [s.x, q.x]; ys += [s.y, q.y]
            elif t in ("LWPOLYLINE", "POLYLINE"):
                if t == "POLYLINE" and not e.is_2d_polyline:
                    continue
                closed = e.closed if t == "LWPOLYLINE" else e.is_closed
                pts = [(p[0], p[1]) for p in (e.get_points("xy") if t == "LWPOLYLINE" else
                                              [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices])]
                if not closed and len(pts) >= 4 and math.dist(pts[0], pts[-1]) < 1.0:
                    closed, pts = True, pts[:-1]
                if closed and len(pts) >= 3:
                    ld.polygons.append(pts)
                for v in e.virtual_entities():
                    vt = v.dxftype()
                    if vt == "LINE":
                        s, q = v.dxf.start, v.dxf.end
                        seg = Segment(s.x, s.y, q.x, q.y, lay)
                        if seg.length > 1.0:
                            ld.segments.append(seg)
                            xs += [s.x, q.x]; ys += [s.y, q.y]
                    elif vt == "ARC":
                        ld.arcs.append(_arc_of(v, lay))
            elif t == "ARC":
                ld.arcs.append(_arc_of(e, lay))
            elif t == "HATCH":
                for hp in ezpath.from_hatch(e):
                    pts = [(v.x, v.y) for v in hp.flattening(20)]
                    if len(pts) >= 4 and math.dist(pts[0], pts[-1]) < 1.0:
                        pts = pts[:-1]
                    if 3 <= len(pts) <= 400:
                        ld.hatches.append(pts)
            elif t == "CIRCLE":
                c = e.dxf.center
                ld.circles.append((c.x, c.y, e.dxf.radius))
            elif t in ("TEXT", "MTEXT", "ATTRIB"):
                if t == "MTEXT":
                    txt = e.plain_text().strip()
                    h = e.dxf.get("char_height", 250)
                    rot = e.get_rotation() if hasattr(e, "get_rotation") else e.dxf.get("rotation", 0)
                    ins = e.dxf.insert
                    # MTEXT attachment point is usually top-left / middle — use insert as approx
                    cx, cy = ins.x, ins.y
                else:
                    txt = e.dxf.text.strip()
                    h = e.dxf.get("height", 250)
                    rot = e.dxf.get("rotation", 0)
                    cx, cy = _text_center(e, txt, h, rot)
                if txt:
                    ld.texts.append(TextItem(txt, cx, cy, rot % 360, h, lay))
        except Exception:
            continue
        if progress and n % 5000 == 0:
            progress(f"엔티티 읽는 중… {n:,}")

    if xs:
        ext = (min(xs), min(ys), max(xs), max(ys))
    else:
        ext = (0, 0, 1000, 1000)
    return DrawingData(path, layers, ext, doc.header.get("$INSUNITS", 0))


def _arc_of(e, lay) -> Arc:
    c = e.dxf.center
    a0 = math.radians(e.dxf.start_angle)
    a1 = math.radians(e.dxf.end_angle)
    while a1 <= a0:
        a1 += 2 * math.pi
    return Arc(c.x, c.y, e.dxf.radius, a0, a1, lay)
