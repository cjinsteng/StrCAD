"""
design_2d/plan/draw.py — 평면해석 캔버스 그리기
"""

import math
import numpy as np

from . import model as pm
from ..section.theme import *

# 컨투어 색상 (Midas 유사 13단계: 파랑 → 빨강)
CONTOUR = ["#1d3bff", "#1f6bff", "#1aa0ff", "#14d2ff", "#12f0d0", "#22f08a", "#3cf043",
           "#8af02a", "#cff022", "#ffe11c", "#ffaa16", "#ff6a12", "#ff2a10"]
SLAB_FILL = ["#253651", "#2b3a4f", "#30344f", "#26414a", "#3a3449", "#2f3f3a"]
RES_NAME = {"Mx": ("슬래브 Mx", "kN·m/m", "+ 하부인장"), "My": ("슬래브 My", "kN·m/m", "+ 하부인장"),
            "Qx": ("슬래브 Qx", "kN/m", ""), "Qy": ("슬래브 Qy", "kN/m", ""),
            "D": ("처짐 δ", "mm", "↓ +"), "BM": ("보 휨모멘트 M", "kN·m", "+ 하부인장"),
            "BV": ("보 전단력 V", "kN", ""), "R": ("반력", "kN, kN·m", "Rz ↑ +")}


class DrawMixin:

    # ── 결과 접근 ───────────────────────────────────────────
    def _res(self):
        if not self.analysis or self.res_key not in self.analysis["results"]:
            return None
        return self.analysis["results"][self.res_key]

    def _nodal(self, res, rt):
        if rt == "D":
            return -res["w"] * 1000.0
        return res[rt]

    def probe_text(self, x, y):
        res = self._res()
        rt = self.res_type.get()
        if res is None or rt not in ("Mx", "My", "Qx", "Qy", "D"):
            return ""
        mesh = self.analysis["mesh"]
        if not len(mesh.plates):
            return ""
        d = np.hypot(mesh.xy[:, 0] - x, mesh.xy[:, 1] - y)
        v = self._nodal(res, rt)
        d = np.where(np.isnan(v), np.inf, d)
        k = int(np.argmin(d))
        if d[k] * self.scale > 30:
            return ""
        return f"   │ {RES_NAME[rt][0].split()[-1]} = {v[k]:.3f} {RES_NAME[rt][1]}"

    # ════════════════════════════════════════════════════════
    def redraw(self):
        c = getattr(self, "canvas", None)
        if c is None:
            return
        c.delete("all")
        if self.show_grid.get():
            self._draw_grid()
        self._draw_ucs()
        res = self._res()
        rt = self.res_type.get() if res else ""
        contour = rt in ("Mx", "My", "Qx", "Qy", "D")
        self._draw_areas(dim=bool(rt))
        if contour:
            self._draw_contour(res, rt)
        if self.show_mesh.get():
            self._draw_mesh()
        self._draw_lines(thin=bool(rt))
        if rt in ("BM", "BV"):
            self._draw_beam_diagram(res, rt)
        self._draw_supports()
        self._draw_nodes()
        if self.show_loads.get() and not rt:
            self._draw_loads()
        if rt == "R":
            self._draw_reactions(res)
        self._draw_overlay()
        self._draw_legend(res, rt)

    def _draw_grid(self):
        c = self.canvas
        W, H = c.winfo_width(), c.winfo_height()
        g = float(self.model.get("grid", 0.5) or 0.5)
        step = g
        while step * self.scale < 9:
            step *= 5
        x0, y1 = self.c2w(0, 0); x1, y0 = self.c2w(W, H)
        i0, i1 = math.floor(x0 / step), math.ceil(x1 / step)
        j0, j1 = math.floor(y0 / step), math.ceil(y1 / step)
        if (i1 - i0) + (j1 - j0) > 3000:
            return
        for i in range(i0, i1 + 1):
            cx, _ = self.w2c(i * step, 0)
            c.create_line(cx, 0, cx, H, fill=C_AXIS if i == 0 else (C_GRID2 if i % 5 == 0 else C_GRID))
        for j in range(j0, j1 + 1):
            _, cy = self.w2c(0, j * step)
            c.create_line(0, cy, W, cy, fill=C_AXIS if j == 0 else (C_GRID2 if j % 5 == 0 else C_GRID))

    def _draw_ucs(self):
        c = self.canvas
        H = c.winfo_height()
        x, y = 22, H - 22
        c.create_line(x, y, x + 34, y, fill=RED, width=2, arrow="last", arrowshape=(7, 8, 3))
        c.create_line(x, y, x, y - 34, fill=GRNH, width=2, arrow="last", arrowshape=(7, 8, 3))
        c.create_text(x + 42, y, text="X", fill=RED, font=FONT_B)
        c.create_text(x, y - 42, text="Y", fill=GRNH, font=FONT_B)
        c.create_text(x + 56, y - 2, anchor="w", fill=TX3, font=FONT_S,
                      text=f"격자 {self.model.get('grid', 0.5):g} m · 메시 {self.model.get('mesh_size', 0.5):g} m")

    # ── 면 ───────────────────────────────────────────────────
    def _drop_set(self, kind):
        dh = self.drop_hover
        if not dh or dh[0] != kind:
            return set()
        return self.sel[kind] if (dh[1] is None or dh[1] in self.sel[kind]) else {dh[1]}

    def _draw_areas(self, dim=False):
        c = self.canvas
        m = self.model
        hov = self.hover[1] if self.hover and self.hover[0] == "area" else None
        drop = self._drop_set("area")
        for aid, ar in m["areas"].items():
            pts = []
            for n in ar["nodes"]:
                pts += self.w2c(m["nodes"][n]["x"], m["nodes"][n]["y"])
            if len(pts) < 6:
                continue
            sel = aid in self.sel["area"]
            slab = ar["kind"] == "slab"
            if aid in drop:
                fill, out = "#0e4a57", C_DROP
            elif sel:
                fill, out = "#4a3a12", C_SEL
            elif aid == hov:
                fill, out = ("#34466a" if slab else "#1d2840"), C_HOV
            elif slab:
                fill = SLAB_FILL[(ar["slab"] - 1) % len(SLAB_FILL)] if not dim else "#18213a"
                out = "#5b7bb0"
            else:
                fill, out = "", "#556074"
            c.create_polygon(pts, fill=fill, outline=out, width=2 if (sel or aid in drop) else 1,
                             dash=() if slab else (5, 4))
            if not slab and not dim:
                # 비구조 면: 대각 빗금
                self._hatch(pts, "#2c3850")
            if self.show_ids.get() and not dim:
                cx, cy = pm.poly_centroid(pm.poly_xy(m, ar["nodes"]))
                px, py = self.w2c(cx, cy)
                if slab:
                    sl = m["slabs"].get(ar["slab"], {})
                    t1 = f"A{aid}  {sl.get('name', '?')}"
                    t2 = f"t={sl.get('t', 0):g}"
                else:
                    t1 = f"A{aid}  비구조"
                    t2 = pm.AREA_DIST_LABEL.get(ar.get("dist", "two"), "").split(" ")[0] + " 전달"
                c.create_text(px, py - 7, text=t1, fill=C_SEL if sel else "#9fb4d6", font=FONT_C)
                c.create_text(px, py + 7, text=t2, fill=TX3, font=FONT_C)

    def _hatch(self, pts, col):
        xs = pts[0::2]; ys = pts[1::2]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        poly = list(zip(xs, ys))
        step = 14
        k = x0 - (y1 - y0)
        while k < x1:
            # 선 x - y = k 와 다각형 교차 구간
            hits = []
            n = len(poly)
            for i in range(n):
                (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
                da, db = ax - ay - k, bx - by - k
                if (da > 0) != (db > 0):
                    t = da / (da - db)
                    hits.append((ax + t * (bx - ax), ay + t * (by - ay)))
            hits.sort()
            for i in range(0, len(hits) - 1, 2):
                self.canvas.create_line(*hits[i], *hits[i + 1], fill=col)
            k += step

    # ── 선 ───────────────────────────────────────────────────
    def _draw_lines(self, thin=False):
        c = self.canvas
        m = self.model
        hov = self.hover[1] if self.hover and self.hover[0] == "line" else None
        drop = self._drop_set("line")
        for lid, ln in m["lines"].items():
            a, b = m["nodes"][ln["ni"]], m["nodes"][ln["nj"]]
            ax, ay = self.w2c(a["x"], a["y"]); bx, by = self.w2c(b["x"], b["y"])
            L = math.hypot(bx - ax, by - ay)
            if L < 1e-6:
                continue
            ux, uy = (bx - ax) / L, (by - ay) / L
            nx, ny = -uy, ux
            sel = lid in self.sel["line"]
            beam = ln["kind"] == "beam"
            # 선 지점 (벽체)
            if lid in m["line_supports"]:
                c.create_line(ax, ay, bx, by, fill="#1d5f8a", width=9)
                k = 0.0
                while k < L:
                    px, py = ax + ux * k, ay + uy * k
                    c.create_line(px, py, px + nx * 7 - ux * 5, py + ny * 7 - uy * 5, fill=C_SUP)
                    k += 9
            if lid in drop:
                col = C_DROP
            elif sel:
                col = C_SEL
            elif lid == hov:
                col = C_HOV
            elif beam:
                mat = m["materials"].get(ln["mat"], {})
                col = C_STEEL if mat.get("type") == "STEEL" else C_RC
            else:
                col = "#8794ab"
            if beam:
                sec = m["sections"].get(ln["sec"], {})
                bw = float(sec.get("b", sec.get("B", sec.get("D", 300))) or 300) / 1000.0
                hw = max(2.0, bw * self.scale / 2)
                if thin:
                    c.create_line(ax, ay, bx, by, fill=col if (sel or lid in drop) else "#9aa6bb", width=2)
                elif hw > 3:
                    c.create_polygon(ax + nx * hw, ay + ny * hw, bx + nx * hw, by + ny * hw,
                                     bx - nx * hw, by - ny * hw, ax - nx * hw, ay - ny * hw,
                                     fill="#3a2a30" if col == C_RC else "#22324a", outline=col,
                                     width=2 if sel else 1)
                    c.create_line(ax, ay, bx, by, fill=col, dash=(6, 3))
                else:
                    c.create_line(ax, ay, bx, by, fill=col, width=4 if sel else 3)
            else:
                c.create_line(ax, ay, bx, by, fill=col, width=2 if sel or lid in drop else 1,
                              dash=(6, 4))
            if self.show_ids.get() and not thin:
                mx, my = (ax + bx) / 2, (ay + by) / 2
                if ny < -0.01 or (abs(ny) <= 0.01 and nx < 0):
                    nx, ny = -nx, -ny
                off = 11 if not beam else max(11, hw + 8)
                txt = f"L{lid}"
                if beam:
                    txt = f"{ln.get('name') or 'L' + str(lid)} [{m['sections'].get(ln['sec'], {}).get('name', '?')}]"
                c.create_text(mx + nx * off, my + ny * off, text=txt,
                              fill=C_SEL if sel else (C_TXT if beam else TX3), font=FONT_C)

    def _draw_mesh(self):
        mesh = self._mesh_for_view()
        if mesh is None:
            return
        c = self.canvas
        for nodes in mesh.plates:
            pts = []
            for n in nodes:
                pts += self.w2c(*mesh.xy[n])
            c.create_polygon(pts, fill="", outline="#3d5a80")

    def _mesh_for_view(self):
        if self.analysis:
            return self.analysis["mesh"]
        ver = (id(self.model), len(self.undo_stack), len(self.redo_stack), self.dirty,
               getattr(self, "_ver", 0))
        cache = getattr(self, "_mesh_cache", None)
        if cache and cache[0] == ver:
            return cache[1]
        from .mesh import build_mesh, MeshError
        try:
            mesh = build_mesh(self.model)
        except MeshError as ex:
            self.msg(f"메시 미리보기 불가: {ex}", ORG)
            mesh = None
        self._mesh_cache = (ver, mesh)
        return mesh

    # ── 노드·지점 ────────────────────────────────────────────
    def _draw_nodes(self):
        c = self.canvas
        hov = self.hover[1] if self.hover and self.hover[0] == "node" else None
        drop = self._drop_set("node")
        for nid, n in self.model["nodes"].items():
            x, y = self.w2c(n["x"], n["y"])
            if nid in drop:
                col, r = C_DROP, 6
            elif nid in self.sel["node"]:
                col, r = C_SEL, 5
            elif nid == hov:
                col, r = C_HOV, 5
            else:
                col, r = C_NODE, 3
            c.create_rectangle(x - r, y - r, x + r, y + r, fill=col, outline="")
            if self.show_ids.get():
                c.create_text(x + 6, y - 8, text=f"{nid}", fill=C_NODE, font=FONT_C, anchor="w")

    def _draw_supports(self):
        c = self.canvas
        m = self.model
        for nid, sid in m["supports"].items():
            n = m["nodes"].get(nid); st = m["sup_types"].get(sid)
            if not n or not st:
                continue
            x, y = self.w2c(n["x"], n["y"])
            kind = pm.support_kind(st)
            if kind == "col":
                hb = max(5.0, float(st.get("col_b", 500)) / 2000 * self.scale)
                hh = max(5.0, float(st.get("col_h", 500)) / 2000 * self.scale)
                c.create_rectangle(x - hb, y - hh, x + hb, y + hh, fill="#1d5f8a", outline=C_SUP, width=1.5)
                c.create_line(x - hb, y - hh, x + hb, y + hh, fill=C_SUP)
                c.create_line(x - hb, y + hh, x + hb, y - hh, fill=C_SUP)
            elif kind == "fix":
                c.create_rectangle(x - 8, y - 8, x + 8, y + 8, fill="#1d5f8a", outline=C_SUP, width=2)
            elif kind == "pin":
                c.create_polygon(x, y - 10, x - 9, y + 7, x + 9, y + 7, fill="#1d5f8a", outline=C_SUP, width=1.5)
            else:
                c.create_oval(x - 8, y - 8, x + 8, y + 8, outline=ORG, width=2)

    # ── 하중 ─────────────────────────────────────────────────
    def _draw_loads(self):
        c = self.canvas
        m = self.model
        case = self.active_case
        selids = getattr(self, "sel_load_ids", set())
        stack = {}
        for ld in m["aloads"]:
            if ld["case"] != case or ld["area"] not in m["areas"]:
                continue
            ar = m["areas"][ld["area"]]
            pts = pm.poly_xy(m, ar["nodes"])
            cx, cy = pm.poly_centroid(pts)
            k = stack.get(("a", ld["area"]), 0); stack[("a", ld["area"])] = k + 1
            col = C_SEL if ld["id"] in selids else C_LOAD
            sp = []
            for x, y in pts:
                sp += self.w2c(cx + (x - cx) * 0.86, cy + (y - cy) * 0.86)
            c.create_polygon(sp, fill="", outline=col, dash=(3, 3))
            px, py = self.w2c(cx, cy)
            c.create_text(px, py + 22 + 13 * k, text=f"⬇ {float(ld['q']):g} kN/m²", fill=col, font=FONT_B)
        for ld in m["lloads"]:
            if ld["case"] != case or ld["line"] not in m["lines"]:
                continue
            ln = m["lines"][ld["line"]]
            a, b = m["nodes"][ln["ni"]], m["nodes"][ln["nj"]]
            ax, ay = self.w2c(a["x"], a["y"]); bx, by = self.w2c(b["x"], b["y"])
            L = math.hypot(bx - ax, by - ay)
            if L < 1e-6:
                continue
            ux, uy = (bx - ax) / L, (by - ay) / L
            nx, ny = uy, -ux
            if ny > 0.01 or (abs(ny) <= 0.01 and nx > 0):
                nx, ny = -nx, -ny
            k = stack.get(("l", ld["line"]), 0); stack[("l", ld["line"])] = k + 1
            w1, w2 = float(ld["w1"]), float(ld["w2"])
            wmax = max(abs(w1), abs(w2), 1e-9)
            col = C_SEL if ld["id"] in selids else C_LOAD2
            base = 9 + 16 * k
            n = max(2, int(L / 22))
            tails = []
            for i in range(n + 1):
                t = i / n
                w = w1 + (w2 - w1) * t
                h = base + 4 + 10 * abs(w) / wmax
                px, py = ax + (bx - ax) * t, ay + (by - ay) * t
                hx, hy = px + nx * base, py + ny * base
                tx, ty = px + nx * h, py + ny * h
                tails += [tx, ty]
                c.create_line(tx, ty, hx, hy, fill=col, arrow="last", arrowshape=(5, 6, 2.5))
            c.create_line(tails, fill=col)
            lbl = f"{w1:g}" if abs(w1 - w2) < 1e-12 else f"{w1:g}~{w2:g}"
            c.create_text((ax + bx) / 2 + nx * (base + 22), (ay + by) / 2 + ny * (base + 22),
                          text=f"{lbl} kN/m", fill=col, font=FONT_C)
        for ld in m["nloads"]:
            if ld["case"] != case or ld["node"] not in m["nodes"]:
                continue
            n = m["nodes"][ld["node"]]
            x, y = self.w2c(n["x"], n["y"])
            k = stack.get(("n", ld["node"]), 0); stack[("n", ld["node"])] = k + 1
            col = C_SEL if ld["id"] in selids else C_LOAD
            c.create_oval(x - 9, y - 9, x + 9, y + 9, outline=col, width=2)
            c.create_line(x - 6, y - 6, x + 6, y + 6, fill=col, width=2)
            c.create_line(x - 6, y + 6, x + 6, y - 6, fill=col, width=2)
            c.create_text(x + 12, y + 12 + 12 * k, text=f"P={float(ld['p']):g} kN", fill=col,
                          font=FONT_B, anchor="w")

    # ── 결과 ─────────────────────────────────────────────────
    def _range(self, v):
        v = v[np.isfinite(v)]
        if not len(v):
            return 0.0, 1.0
        lo, hi = float(v.min()), float(v.max())
        if hi - lo < 1e-12:
            hi = lo + 1e-9
        return lo, hi

    def _draw_contour(self, res, rt):
        c = self.canvas
        mesh = self.analysis["mesh"]
        v = self._nodal(res, rt)
        lo, hi = self._range(v[np.unique(mesh.plates.ravel())] if len(mesh.plates) else v)
        nb = len(CONTOUR)

        def col(val):
            k = int((val - lo) / (hi - lo) * nb)
            return CONTOUR[max(0, min(nb - 1, k))]
        sub = 2
        for nodes in mesh.plates:
            X = mesh.xy[nodes]
            vv = v[nodes]
            if np.any(~np.isfinite(vv)):
                continue
            for i in range(sub):
                for j in range(sub):
                    corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                    pts = []
                    vals = []
                    for a, b in corners:
                        s, t = a / sub, b / sub
                        N = np.array([(1 - s) * (1 - t), s * (1 - t), s * t, (1 - s) * t])
                        p = N @ X
                        pts += self.w2c(*p)
                        vals.append(N @ vv)
                    f = col(sum(vals) / 4)
                    c.create_polygon(pts, fill=f, outline=f)
        if self.show_values.get() and len(mesh.plates):
            nodes = np.unique(mesh.plates.ravel())
            for k, tag in ((nodes[np.nanargmax(v[nodes])], "MAX"), (nodes[np.nanargmin(v[nodes])], "MIN")):
                x, y = self.w2c(*mesh.xy[k])
                c.create_oval(x - 5, y - 5, x + 5, y + 5, outline=WHI, width=2)
                c.create_text(x + 8, y - 10, anchor="w", text=f"{tag} {v[k]:.2f}", fill=WHI,
                              font=FONT_B)

    def _draw_beam_diagram(self, res, rt):
        c = self.canvas
        m = self.model
        key = "M" if rt == "BM" else "V"
        colr, fill = (C_M, C_M_F) if key == "M" else (C_V, C_V_F)
        vmax = max([np.abs(d[key]).max() for d in res["beams"].values()] + [1e-9])
        k = 45.0 * self.res_scale / vmax
        placed = []
        for lid, d in res["beams"].items():
            if lid not in m["lines"]:
                continue
            ln = m["lines"][lid]
            a, b = m["nodes"][ln["ni"]], m["nodes"][ln["nj"]]
            ax, ay = self.w2c(a["x"], a["y"]); bx, by = self.w2c(b["x"], b["y"])
            L = math.hypot(bx - ax, by - ay)
            Lm = d["s"][-1] if len(d["s"]) else 1.0
            if L < 1e-6 or Lm <= 0:
                continue
            ux, uy = (bx - ax) / L, (by - ay) / L
            nx, ny = -uy, ux
            base, off = [], []
            for s_, v in zip(d["s"], d[key]):
                t = s_ / Lm
                px, py = ax + (bx - ax) * t, ay + (by - ay) * t
                base.append((px, py)); off.append((px + nx * v * k, py + ny * v * k))
            pts = [q for p in base for q in p] + [q for p in reversed(off) for q in p]
            c.create_polygon(pts, fill=fill, outline="")
            c.create_line([q for p in off for q in p], fill=colr, width=2 if lid in self.sel["line"] else 1.5)
            if not self.show_values.get():
                continue
            vals = d[key]
            idx = {0, len(vals) - 1, int(np.argmax(vals)), int(np.argmin(vals))}
            for i in sorted(idx):
                if abs(vals[i]) < vmax * 2e-3:
                    continue
                px, py = off[i]
                o = 9 if vals[i] >= 0 else -9
                tx, ty = px + nx * o, py + ny * o
                if any(abs(tx - qx) < 40 and abs(ty - qy) < 13 for qx, qy in placed):
                    continue
                placed.append((tx, ty))
                c.create_text(tx, ty, text=fnum(vals[i]), fill=colr, font=FONT_C)

    def _draw_reactions(self, res):
        c = self.canvas
        m = self.model
        for nid, (rz, mx, my) in res["react"].items():
            n = m["nodes"].get(nid)
            if not n:
                continue
            x, y = self.w2c(n["x"], n["y"])
            c.create_text(x + 10, y + 12, anchor="nw", text=f"Rz {fnum(rz)}", fill=C_R, font=FONT_B)
            if abs(mx) > 1e-6 or abs(my) > 1e-6:
                c.create_text(x + 10, y + 26, anchor="nw", fill=ORG, font=FONT_C,
                              text=f"Mx {fnum(mx)}  My {fnum(my)}")
        for lid, d in res.get("line_react", {}).items():
            if lid not in m["lines"]:
                continue
            ln = m["lines"][lid]
            a, b = m["nodes"][ln["ni"]], m["nodes"][ln["nj"]]
            x, y = self.w2c((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2)
            L = pm.line_length(m, lid)
            c.create_text(x, y - 12, text=f"ΣRz {fnum(d['Rz'])} ({fnum(d['Rz'] / L if L else 0)}/m)",
                          fill=C_R, font=FONT_B)

    # ── 편집 오버레이 ───────────────────────────────────────
    def _draw_overlay(self):
        c = self.canvas
        mode = self.mode.get()
        sp = self.snap if mode in ("node", "line") else None
        if sp:
            sx, sy = self.w2c(sp[2], sp[3])
            if self.chain is not None and mode == "line" and self.chain in self.model["nodes"]:
                n0 = self.model["nodes"][self.chain]
                x0, y0 = self.w2c(n0["x"], n0["y"])
                c.create_line(x0, y0, sx, sy, fill=C_SEL, width=2, dash=(6, 4))
                c.create_text((x0 + sx) / 2, (y0 + sy) / 2 - 12, fill=C_SEL, font=FONT_B,
                              text=f"{math.hypot(sp[2] - n0['x'], sp[3] - n0['y']):.3f} m")
            if sp[0] == "node":
                c.create_rectangle(sx - 8, sy - 8, sx + 8, sy + 8, outline=C_SEL, width=2)
            elif sp[0] == "line":
                c.create_polygon(sx, sy - 9, sx - 8, sy + 6, sx + 8, sy + 6, outline=C_DROP, fill="", width=2)
            else:
                c.create_line(sx - 7, sy, sx + 7, sy, fill=WHI); c.create_line(sx, sy - 7, sx, sy + 7, fill=WHI)
            c.create_text(sx + 12, sy + 14, anchor="w", fill=TX2, font=FONT_C, text=f"({sp[2]:.3f}, {sp[3]:.3f})")
        if self.poly:
            pts = []
            for n in self.poly:
                pts += self.w2c(self.model["nodes"][n]["x"], self.model["nodes"][n]["y"])
            if self.snap and self.snap[0] == "node":
                if self.snap[1] is not None:
                    nn = self.model["nodes"][self.snap[1]]
                    pts += self.w2c(nn["x"], nn["y"])
                else:
                    pts += self.w2c(self.snap[2], self.snap[3])
            if len(pts) >= 4:
                c.create_line(pts, fill=C_SEL, width=2, dash=(6, 3))
            for i in range(0, 2 * len(self.poly), 2):
                c.create_oval(pts[i] - 5, pts[i + 1] - 5, pts[i] + 5, pts[i + 1] + 5, outline=C_SEL, width=2)
        if self.box:
            x0, y0, x1, y1 = self.box
            cr = x1 < x0
            c.create_rectangle(x0, y0, x1, y1, outline=GRNH if cr else ACCH, dash=(4, 3) if cr else None)

    def _draw_legend(self, res, rt):
        c = self.canvas
        W = c.winfo_width()
        if not (res and rt):
            if self.show_loads.get() and self.model["cases"]:
                cs = self.model["cases"].get(self.active_case, {})
                c.create_text(W - 12, 14, anchor="ne", text=f"하중케이스: {cs.get('name', '')}",
                              fill=C_LOAD, font=FONT_B)
            return
        name, unit, note = RES_NAME[rt]
        kind, i = self.res_key
        src = self.model["cases" if kind == "case" else "combos"].get(i, {})
        tag = "LC" if kind == "case" else "COMB"
        c.create_text(W - 12, 14, anchor="ne", fill=WHI, font=FONT_B,
                      text=f"{name} [{unit}] {note}   ·   {tag}: {src.get('name', '')}")
        if rt in ("Mx", "My", "Qx", "Qy", "D"):
            mesh = self.analysis["mesh"]
            v = self._nodal(res, rt)
            lo, hi = self._range(v[np.unique(mesh.plates.ravel())] if len(mesh.plates) else v)
            nb = len(CONTOUR)
            x0, y0, hgt = W - 78, 40, 18
            for k in range(nb):
                y = y0 + (nb - 1 - k) * hgt
                c.create_rectangle(x0, y, x0 + 16, y + hgt, fill=CONTOUR[k], outline="#0a0e18")
            for k in range(nb + 1):
                y = y0 + (nb - k) * hgt
                c.create_text(x0 + 20, y, anchor="w", fill=TXT, font=FONT_C,
                              text=f"{lo + (hi - lo) * k / nb:.2f}")
