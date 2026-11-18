"""
design_2d/section/draw.py — 단면해석 캔버스 그리기 (DrawMixin)
"""

import math

from . import model as fm
from .theme import *

DIAG = {
    "M": ("M", C_M, C_M_F, "kN·m", -1),     # 마지막 값: 그리는 방향 (-1 = 인장측, 국부 -y)
    "V": ("V", C_V, C_V_F, "kN", 1),
    "N": ("N", C_N, C_N_F, "kN", 1),
}


class DrawMixin:

    # ════════════════════════════════════════════════════════
    def redraw(self):
        c = getattr(self, "canvas", None)
        if c is None:
            return
        c.delete("all")
        if self.show_grid.get():
            self._draw_grid()
        self._draw_ucs()
        rt = self.res_type.get() if self.results else ""
        res = self.results.get(self.res_key) if (self.results and self.res_key) else None
        if res and rt in DIAG:
            self._draw_diagram(res, rt)
        self._draw_elems(dim=bool(res and rt == "D"), thin=bool(res and rt))
        if res and rt == "D":
            self._draw_deformed(res)
        self._draw_supports()
        self._draw_nodes()
        if self.show_loads.get() and not (res and rt):
            self._draw_loads()
        if res and rt == "R":
            self._draw_reactions(res)
        self._draw_edit_overlay()
        self._draw_legend(res, rt)

    # ── 격자 ─────────────────────────────────────────────────
    def _draw_grid(self):
        c = self.canvas
        W, H = c.winfo_width(), c.winfo_height()
        g = float(self.model.get("grid", 0.5) or 0.5)
        step = g
        while step * self.scale < 9:
            step *= 5
        x0, y1 = self.c2w(0, 0)
        x1, y0 = self.c2w(W, H)
        i0, i1 = math.floor(x0 / step), math.ceil(x1 / step)
        j0, j1 = math.floor(y0 / step), math.ceil(y1 / step)
        if (i1 - i0) * (j1 - j0) > 40000:
            return
        major = 5
        for i in range(i0, i1 + 1):
            cx, _ = self.w2c(i * step, 0)
            col = C_AXIS if i == 0 else (C_GRID2 if i % major == 0 else C_GRID)
            c.create_line(cx, 0, cx, H, fill=col)
        for j in range(j0, j1 + 1):
            _, cy = self.w2c(0, j * step)
            col = C_AXIS if j == 0 else (C_GRID2 if j % major == 0 else C_GRID)
            c.create_line(0, cy, W, cy, fill=col)

    def _draw_ucs(self):
        c = self.canvas
        H = c.winfo_height()
        x, y = 22, H - 22
        c.create_line(x, y, x + 34, y, fill=RED, width=2, arrow="last", arrowshape=(7, 8, 3))
        c.create_line(x, y, x, y - 34, fill=GRNH, width=2, arrow="last", arrowshape=(7, 8, 3))
        c.create_text(x + 42, y, text="X", fill=RED, font=FONT_B)
        c.create_text(x, y - 42, text="Y", fill=GRNH, font=FONT_B)
        g = self.model.get("grid", 0.5)
        c.create_text(x + 56, y - 2, text=f"격자 {g:g} m", fill=TX3, font=FONT_S, anchor="w")

    # ── 부재 ─────────────────────────────────────────────────
    def _elem_depth_m(self, e):
        sec = self.model["sections"].get(e["sec"])
        if not sec:
            return 0.0
        sh = sec.get("shape")
        k = {"rect": "h", "H": "H", "box": "H", "circle": "D", "pipe": "D"}.get(sh)
        if k:
            return float(sec.get(k, 0) or 0) / 1000.0
        A, I = fm.section_props(sec)
        return math.sqrt(12 * I / A) / 1000.0 if A > 0 else 0.0

    def _draw_elems(self, dim=False, thin=False):
        c = self.canvas
        m = self.model
        hov = self.hover[1] if self.hover and self.hover[0] == "elem" else None
        drop_set = set()
        if self.drop_hover and self.drop_hover[0] == "elem":
            drop = self.drop_hover[1]
            # drop=None → 빈 곳에 놓기 = 선택 항목 전체에 적용
            drop_set = self.sel_elems if (drop is None or drop in self.sel_elems) else {drop}
        for eid, e in m["elems"].items():
            a, b = m["nodes"][e["ni"]], m["nodes"][e["nj"]]
            ax, ay = self.w2c(a["x"], a["y"])
            bx, by = self.w2c(b["x"], b["y"])
            L = math.hypot(bx - ax, by - ay)
            if L < 1e-6:
                continue
            ux, uy = (bx - ax) / L, (by - ay) / L
            nx, ny = -uy, ux
            mat = m["materials"].get(e["mat"], {})
            base = C_STEEL if mat.get("type") == "STEEL" else C_RC
            sel = eid in self.sel_elems
            if eid in drop_set:
                col, fill = C_DROP, "#0e4a57"
            elif sel:
                col, fill = C_SEL, "#5a4510"
            elif eid == hov:
                col, fill = C_HOV, "#4a5a78"
            else:
                col, fill = (TX3, "#1a2236") if dim else (base, "#3a4660")
            hw = max(2.0, self._elem_depth_m(e) * self.scale / 2)
            if thin:
                hw = 2.0
                if not (sel or eid in drop_set or eid == hov):
                    col = "#64748b"
            if hw > 3.0:
                pts = [ax + nx * hw, ay + ny * hw, bx + nx * hw, by + ny * hw,
                       bx - nx * hw, by - ny * hw, ax - nx * hw, ay - ny * hw]
                c.create_polygon(pts, fill=fill, outline=col if not dim else TX3,
                                 width=2 if (sel or eid in drop_set) else 1)
                c.create_line(ax, ay, bx, by, fill=col, width=1, dash=(6, 3))
            else:
                c.create_line(ax, ay, bx, by, fill=col, width=4 if sel else 3)
            # 단부조건 표시: 힌지 = 빈 원, 반강접 = 주황 원 + 고정률
            fi, fj = fm.end_fix(e)
            for r, (px, py), sgn in ((fi, (ax, ay), 1), (fj, (bx, by), -1)):
                if r >= 1.0:
                    continue
                off = max(hw, 6) + 8
                qx, qy = px + ux * off * sgn, py + uy * off * sgn
                if r <= 0.0:
                    c.create_oval(qx - 4, qy - 4, qx + 4, qy + 4, outline=C_SEL,
                                  fill=CANV_BG, width=2)
                else:
                    c.create_oval(qx - 4.5, qy - 4.5, qx + 4.5, qy + 4.5, outline=C_SEL,
                                  fill=ORG, width=1.5)
                    if self.show_ids.get():
                        c.create_text(qx + ux * 10 * sgn - uy * 9, qy + uy * 10 * sgn + ux * 9,
                                      text=f"{r:g}", fill=ORG, font=FONT_C)
            if self.show_ids.get() and (not thin or sel):
                mx, my = (ax + bx) / 2, (ay + by) / 2
                off = max(hw, 3) + 9
                if ny < -0.01 or (abs(ny) <= 0.01 and nx < 0):
                    nx_, ny_ = -nx, -ny
                else:
                    nx_, ny_ = nx, ny
                nm = e.get("name") or f"E{eid}"
                sec = m["sections"].get(e["sec"], {})
                c.create_text(mx + nx_ * off, my + ny_ * off,
                              text=f"{nm} [{sec.get('name', '?')}]",
                              fill=C_SEL if sel else C_TXT, font=FONT_C)

    # ── 노드 ─────────────────────────────────────────────────
    def _draw_nodes(self):
        c = self.canvas
        hov = self.hover[1] if self.hover and self.hover[0] == "node" else None
        drop_set = set()
        if self.drop_hover and self.drop_hover[0] == "node":
            drop = self.drop_hover[1]
            # drop=None → 빈 곳에 놓기 = 선택 항목 전체에 적용
            drop_set = self.sel_nodes if (drop is None or drop in self.sel_nodes) else {drop}
        for nid, n in self.model["nodes"].items():
            x, y = self.w2c(n["x"], n["y"])
            if nid in drop_set:
                col, r = C_DROP, 6
            elif nid in self.sel_nodes:
                col, r = C_SEL, 5
            elif nid == hov:
                col, r = C_HOV, 5
            else:
                col, r = C_NODE, 3.5
            c.create_rectangle(x - r, y - r, x + r, y + r, fill=col, outline="")
            if self.show_ids.get():
                c.create_text(x + 7, y - 9, text=f"{nid}", fill=C_NODE, font=FONT_C, anchor="w")

    # ── 지점 ─────────────────────────────────────────────────
    def _draw_supports(self):
        c = self.canvas
        m = self.model
        for nid, sid in m["supports"].items():
            n = m["nodes"].get(nid); st = m["sup_types"].get(sid)
            if not n or not st:
                continue
            x, y = self.w2c(n["x"], n["y"])
            kind = fm.support_kind(st)
            s = 13
            fill, out = "#1d5f8a", "#0b2236"
            if kind == "fix":
                c.create_rectangle(x - s * 1.3, y, x + s * 1.3, y + 6, fill=fill, outline=out)
                for k in range(-4, 5):
                    hx = x + k * s * 0.3
                    c.create_line(hx, y + 6, hx - 6, y + 13, fill=C_SUP)
            elif kind in ("pin", "semi", "rollx", "spring"):
                c.create_polygon(x, y, x - s, y + s * 1.4, x + s, y + s * 1.4,
                                 fill=fill, outline=out, width=1.5)
                by = y + s * 1.4
                if kind == "rollx":
                    for dx in (-s * 0.55, s * 0.55):
                        c.create_oval(x + dx - 3.5, by + 1, x + dx + 3.5, by + 8,
                                      outline=C_SUP, width=1.5)
                    by += 9
                c.create_line(x - s * 1.3, by, x + s * 1.3, by, fill=C_SUP, width=2)
                for k in range(-3, 4):
                    hx = x + k * s * 0.35
                    c.create_line(hx, by, hx - 5, by + 6, fill=C_SUP)
                if kind == "semi":
                    c.create_arc(x - 15, y - 15, x + 15, y + 15, start=200, extent=140,
                                 style="arc", outline=C_SEL, width=2)
                    c.create_text(x + 18, y - 14, text=f"r={fm.clamp01(st.get('fix', 0)):g}",
                                  fill=C_SEL, font=FONT_C, anchor="w")
            elif kind == "rolly":
                c.create_polygon(x, y, x - s * 1.4, y - s, x - s * 1.4, y + s,
                                 fill=fill, outline=out, width=1.5)
                bx = x - s * 1.4
                for dy in (-s * 0.55, s * 0.55):
                    c.create_oval(bx - 8, y + dy - 3.5, bx - 1, y + dy + 3.5,
                                  outline=C_SUP, width=1.5)
                bx -= 9
                c.create_line(bx, y - s * 1.3, bx, y + s * 1.3, fill=C_SUP, width=2)
            else:
                c.create_rectangle(x - 7, y - 7, x + 7, y + 7, outline=C_SUP, width=2)
            if any(float(st.get(k, 0) or 0) > 0 for k in ("kx", "ky", "kr")):
                zx = x + s + 8
                pts = [zx, y]
                for k in range(1, 7):
                    pts += [zx + (4 if k % 2 else -4), y + k * 4]
                pts += [zx, y + 28]
                c.create_line(pts, fill=ORG, width=1.5)

    # ── 하중 ─────────────────────────────────────────────────
    def _arrow(self, x0, y0, x1, y1, col, w=2):
        self.canvas.create_line(x0, y0, x1, y1, fill=col, width=w, arrow="last",
                                arrowshape=(8, 10, 3.5))

    def _moment_arrow(self, x, y, val, col, r=16):
        pts = []
        a0, a1 = (-70, 200) if val > 0 else (250, -20)
        n = 14
        for k in range(n + 1):
            a = math.radians(a0 + (a1 - a0) * k / n)
            pts += [x + r * math.cos(a), y - r * math.sin(a)]
        self.canvas.create_line(pts, fill=col, width=2, smooth=True, arrow="last",
                                arrowshape=(8, 10, 3.5))

    def _dir_vec(self, d, e=None):
        """하중 방향 코드 → 전체좌표 단위벡터 (값이 + 일 때 힘 방향)"""
        if d == "G":
            return 0.0, -1.0
        if d == "GX":
            return 1.0, 0.0
        if d == "GY":
            return 0.0, 1.0
        a, b = self.model["nodes"][e["ni"]], self.model["nodes"][e["nj"]]
        L = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) or 1.0
        c_, s_ = (b["x"] - a["x"]) / L, (b["y"] - a["y"]) / L
        return (c_, s_) if d == "LX" else (-s_, c_)

    def _draw_loads(self):
        c = self.canvas
        m = self.model
        case = self.active_case
        sel_loads = getattr(self, "sel_load_ids", set())
        # 절점하중
        for ld in m["nloads"]:
            if ld["case"] != case or ld["node"] not in m["nodes"]:
                continue
            n = m["nodes"][ld["node"]]
            x, y = self.w2c(n["x"], n["y"])
            col = C_SEL if ld["id"] in sel_loads else C_LOAD
            fx, fy, mz = float(ld.get("fx", 0)), float(ld.get("fy", 0)), float(ld.get("mz", 0))
            F = math.hypot(fx, fy)
            if F > 1e-12:
                ux, uy = fx / F, -fy / F            # 화면 방향
                L = 46
                self._arrow(x - ux * (L + 6), y - uy * (L + 6), x - ux * 6, y - uy * 6, col, 2)
                c.create_text(x - ux * (L + 14), y - uy * (L + 14),
                              text=fnum(F, 2) if (fx == 0 or fy == 0) else f"({fnum(fx)}, {fnum(fy)})",
                              fill=col, font=FONT_C)
            if abs(mz) > 1e-12:
                self._moment_arrow(x, y, mz, col, r=20)
                c.create_text(x + 24, y - 20, text=f"{fnum(mz)} kN·m", fill=col,
                              font=FONT_C, anchor="w")
        # 부재하중 (같은 부재에 여러 개면 바깥으로 쌓기)
        stack = {}
        wmax = max([abs(float(ld.get("w1", 0))) for ld in m["eloads"] if ld["kind"] == "dist"] +
                   [abs(float(ld.get("w2", 0))) for ld in m["eloads"] if ld["kind"] == "dist"] + [1e-9])
        for ld in m["eloads"]:
            if ld["case"] != case or ld["elem"] not in m["elems"]:
                continue
            e = m["elems"][ld["elem"]]
            a, b = m["nodes"][e["ni"]], m["nodes"][e["nj"]]
            Lm = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
            if Lm < 1e-9:
                continue
            dvx, dvy = self._dir_vec(ld.get("dir", "G"), e)
            sdx, sdy = dvx, -dvy                   # 화면 방향
            k = stack.get(ld["elem"], 0)
            stack[ld["elem"]] = k + 1
            base_off = 6 + k * 10 + max(0, self._elem_depth_m(e) * self.scale / 2)
            col = C_SEL if ld["id"] in sel_loads else (C_LOAD if ld["kind"] == "dist" else C_LOAD2)
            f = Lm if ld.get("rel") else 1.0

            def pt(s):
                t = s / Lm
                return self.w2c(a["x"] + (b["x"] - a["x"]) * t, a["y"] + (b["y"] - a["y"]) * t)

            if ld["kind"] == "point":
                p = float(ld.get("p", 0))
                s = min(max(float(ld.get("a", 0)) * f, 0), Lm)
                px, py = pt(s)
                sg = 1 if p >= 0 else -1
                L = 50
                hx, hy = px - sdx * sg * base_off, py - sdy * sg * base_off
                self._arrow(hx - sdx * sg * L, hy - sdy * sg * L, hx, hy, col, 2.5)
                c.create_text(hx - sdx * sg * (L + 10), hy - sdy * sg * (L + 10),
                              text=f"{fnum(abs(p))}", fill=col, font=FONT_C)
            else:
                w1, w2 = float(ld.get("w1", 0)), float(ld.get("w2", 0))
                sa = min(max(float(ld.get("a", 0)) * f, 0), Lm)
                sb = min(max(float(ld.get("b", 1 if ld.get("rel") else Lm)) * f, 0), Lm)
                if sb - sa < 1e-9:
                    continue
                nseg = max(2, int((sb - sa) * self.scale / 28))
                tails = []
                for i in range(nseg + 1):
                    s = sa + (sb - sa) * i / nseg
                    w = w1 + (w2 - w1) * i / nseg
                    px, py = pt(s)
                    # 하중이 + 이면 부재 '바깥쪽'(하중 반대편)에서 부재로 향한다
                    sg = 1 if w >= 0 else -1
                    ln = 10 + 30 * abs(w) / wmax
                    hx, hy = px - sdx * sg * base_off, py - sdy * sg * base_off
                    tx, ty = hx - sdx * sg * ln, hy - sdy * sg * ln
                    tails += [tx, ty]
                    if abs(w) > 1e-12:
                        self._arrow(tx, ty, hx, hy, col, 1.3)
                if len(tails) >= 4:
                    c.create_line(tails, fill=col, width=1.5)
                lbl = fnum(w1) if abs(w1 - w2) < 1e-9 else f"{fnum(w1)}~{fnum(w2)}"
                c.create_text(tails[len(tails) // 2 // 2 * 2] - sdx * 10,
                              tails[len(tails) // 2 // 2 * 2 + 1] - sdy * 10,
                              text=lbl, fill=col, font=FONT_C)

    # ── 결과: 부재력도 ───────────────────────────────────────
    def _draw_diagram(self, res, rt):
        c = self.canvas
        m = self.model
        key, col, fill, unit, side = DIAG[rt]
        vmax = 0.0
        for er in res["elems"].values():
            vmax = max(vmax, max(abs(v) for v in er[key]))
        if vmax < 1e-9:
            vmax = 1.0
        kpx = 60.0 * self.res_scale / vmax
        sel = self.sel_elems
        placed = []
        for eid, er in res["elems"].items():
            if eid not in m["elems"]:
                continue
            e = m["elems"][eid]
            a = m["nodes"][e["ni"]]
            cs, sn = er["c"], er["s"]
            # 국부 y 의 화면 방향
            lyx, lyy = -sn, -cs
            base, offp = [], []
            vals = er[key]
            for x, v in zip(er["xs"], vals):
                bx, by = self.w2c(a["x"] + cs * x, a["y"] + sn * x)
                o = side * v * kpx
                base.append((bx, by))
                offp.append((bx + lyx * o, by + lyy * o))
            pts = []
            for p in base:
                pts += p
            for p in reversed(offp):
                pts += p
            c.create_polygon(pts, fill=fill, outline="")
            step = max(1, len(base) // 24)
            for i in range(0, len(base), step):
                c.create_line(*base[i], *offp[i], fill=col, width=1, stipple="")
            line = []
            for p in offp:
                line += p
            c.create_line(line, fill=col, width=2 if eid in sel else 1.5)
            if not self.show_values.get():
                continue
            # 값 표시: 양단 + 극값
            idxs = {0, len(vals) - 1}
            imx = max(range(len(vals)), key=lambda i: vals[i])
            imn = min(range(len(vals)), key=lambda i: vals[i])
            for i in (imx, imn):
                if 0 < i < len(vals) - 1:
                    idxs.add(i)
            shown = []
            for i in sorted(idxs):
                v = vals[i]
                if abs(v) < vmax * 1e-3:
                    continue
                if any(abs(v - s) < vmax * 0.02 and abs(i - j) < len(vals) * 0.15
                       for s, j in shown):
                    continue
                shown.append((v, i))
                px, py = offp[i]
                o = 10 if side * v >= 0 else -10
                tx, ty = px + lyx * o, py + lyy * o
                if any(abs(tx - qx) < 42 and abs(ty - qy) < 15 for qx, qy in placed):
                    continue
                placed.append((tx, ty))
                c.create_text(tx, ty, text=fnum(v, 2), fill=col, font=FONT_C)

    def _draw_deformed(self, res):
        c = self.canvas
        m = self.model
        dmax = 0.0
        for er in res["elems"].values():
            for du, dv in zip(er["du"], er["dv"]):
                dmax = max(dmax, math.hypot(du, dv))
        if dmax < 1e-15:
            return
        k = 50.0 * self.res_scale / (dmax * self.scale)
        best = None
        for eid, er in res["elems"].items():
            if eid not in m["elems"]:
                continue
            e = m["elems"][eid]
            a = m["nodes"][e["ni"]]
            cs, sn = er["c"], er["s"]
            pts = []
            for x, du, dv in zip(er["xs"], er["du"], er["dv"]):
                gx = a["x"] + cs * x + k * (du * cs - dv * sn)
                gy = a["y"] + sn * x + k * (du * sn + dv * cs)
                pts += self.w2c(gx, gy)
                d = math.hypot(du, dv)
                if best is None or d > best[0]:
                    best = (d, self.w2c(gx, gy), du * cs - dv * sn, du * sn + dv * cs)
            c.create_line(pts, fill=C_D, width=2.5 if eid in self.sel_elems else 2)
        if best and self.show_values.get():
            (px, py) = best[1]
            c.create_oval(px - 4, py - 4, px + 4, py + 4, outline=C_D, width=2)
            c.create_text(px + 8, py - 12, anchor="w", fill=C_D, font=FONT_C,
                          text=f"δmax = {best[0] * 1000:.3f} mm  (dx {best[2] * 1000:.2f}, dy {best[3] * 1000:.2f})")

    def _draw_reactions(self, res):
        c = self.canvas
        m = self.model
        for nid, (rx, ry, mz) in res["react"].items():
            n = m["nodes"].get(nid)
            if not n:
                continue
            x, y = self.w2c(n["x"], n["y"])
            if abs(ry) > 1e-6:
                y0, y1 = (y + 78, y + 34) if ry > 0 else (y + 34, y + 78)
                self._arrow(x, y0, x, y1, C_R, 2.5)
                c.create_text(x + 6, y + 88, text=f"Ry {fnum(ry)}", fill=C_R, font=FONT_B, anchor="n")
            if abs(rx) > 1e-6:
                x0, x1 = (x - 70, x - 24) if rx > 0 else (x - 24, x - 70)
                self._arrow(x0, y + 26, x1, y + 26, C_R, 2.5)
                c.create_text(x - 74, y + 26, text=f"Rx {fnum(rx)}", fill=C_R, font=FONT_B, anchor="e")
            if abs(mz) > 1e-6:
                self._moment_arrow(x, y, mz, C_R, r=24)
                c.create_text(x + 28, y - 24, text=f"Mz {fnum(mz)}", fill=C_R, font=FONT_B, anchor="w")

    # ── 편집 오버레이 (스냅, 고무줄 선, 영역선택) ─────────────
    def _draw_edit_overlay(self):
        c = self.canvas
        mode = self.mode.get()
        sp = self.snap if mode in ("node", "elem") else None
        if sp:
            sx, sy = self.w2c(sp[2], sp[3])
            if self.chain is not None and mode == "elem" and self.chain in self.model["nodes"]:
                n0 = self.model["nodes"][self.chain]
                x0, y0 = self.w2c(n0["x"], n0["y"])
                c.create_line(x0, y0, sx, sy, fill=C_SEL, width=2, dash=(6, 4))
                L = math.hypot(sp[2] - n0["x"], sp[3] - n0["y"])
                c.create_text((x0 + sx) / 2, (y0 + sy) / 2 - 12, text=f"{L:.3f} m",
                              fill=C_SEL, font=FONT_B)
            if sp[0] == "node":
                c.create_rectangle(sx - 8, sy - 8, sx + 8, sy + 8, outline=C_SEL, width=2)
            elif sp[0] == "elem":
                c.create_polygon(sx, sy - 9, sx - 8, sy + 6, sx + 8, sy + 6,
                                 outline=C_DROP, fill="", width=2)
            else:
                c.create_line(sx - 7, sy, sx + 7, sy, fill=WHI)
                c.create_line(sx, sy - 7, sx, sy + 7, fill=WHI)
            c.create_text(sx + 12, sy + 14, anchor="w", fill=TX2, font=FONT_C,
                          text=f"({sp[2]:.3f}, {sp[3]:.3f})")
        if self.box:
            x0, y0, x1, y1 = self.box
            crossing = x1 < x0
            c.create_rectangle(x0, y0, x1, y1, outline=GRNH if crossing else ACCH,
                               dash=(4, 3) if crossing else None, width=1)

    def _draw_legend(self, res, rt):
        if not (res and rt):
            if self.show_loads.get() and self.model["cases"]:
                case = self.model["cases"].get(self.active_case, {})
                self.canvas.create_text(self.canvas.winfo_width() - 12, 14, anchor="ne",
                                        text=f"하중케이스: {case.get('name', '')}",
                                        fill=C_LOAD, font=FONT_B)
            return
        names = {"M": "휨모멘트 M [kN·m]", "V": "전단력 V [kN]", "N": "축력 N [kN] (인장+)",
                 "D": "변형도", "R": "반력 [kN, kN·m]"}
        kind, i = self.res_key
        src = self.model["cases" if kind == "case" else "combos"].get(i, {})
        tag = "LC" if kind == "case" else "COMB"
        self.canvas.create_text(self.canvas.winfo_width() - 12, 14, anchor="ne",
                                text=f"{names.get(rt, '')}   ·   {tag}: {src.get('name', '')}",
                                fill=WHI, font=FONT_B)
