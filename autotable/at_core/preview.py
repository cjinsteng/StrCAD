"""preview.py — 선택한 부재 단면 미리보기 (오른쪽 패널)"""
from __future__ import annotations

import tkinter as tk

from . import model as M
from . import sections as S
from . import theme as T

LAYER_COLOR = {"ELE": "#C0392B", "bar2": "#D9741A", "dim": "#6B7280"}


class Preview(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=T.PANEL)
        self.title = tk.Label(self, text="미리보기", font=T.F_UI_B, bg=T.PANEL, fg=T.NAVY, anchor="w")
        self.title.pack(fill="x", padx=10, pady=(8, 2))
        self.cv = tk.Canvas(self, bg="#FBFCFE", highlightthickness=1, highlightbackground=T.LINE)
        self.cv.pack(fill="both", expand=True, padx=8, pady=4)
        self.info = tk.Label(self, text="", font=T.F_SMALL, bg=T.PANEL, fg=T.MUTED, justify="left", anchor="nw")
        self.info.pack(fill="x", padx=10, pady=(0, 8))
        self.cv.bind("<Configure>", lambda e: self.redraw())
        self.mtype = None
        self.row = None

    def show(self, mtype, row):
        self.mtype, self.row = mtype, row
        self.redraw()

    # ── 그리기 ─────────────────────────────────────────────────────
    def redraw(self):
        cv = self.cv
        cv.delete("all")
        W, H = max(cv.winfo_width(), 50), max(cv.winfo_height(), 50)
        r, t = self.row, self.mtype
        if not r or not t or not (r.get("name") or "").strip():
            self.title.config(text="미리보기")
            self.info.config(text="행을 선택하면 단면이 보입니다.")
            cv.create_text(W / 2, H / 2, text="—", fill=T.FAINT, font=T.F_TITLE)
            return
        self.title.config(text=f"{r.get('name')}   ·   {M.TYPES[t]['title']}")
        try:
            if t == "beam":
                self._beam(r, W, H)
            elif t == "column":
                self._column(r, W, H)
            elif t == "wall":
                self._wall(r, W, H)
            else:
                self._slab(r, W, H)
        except Exception as e:                       # noqa: BLE001
            cv.create_text(W / 2, H / 2, text=f"그릴 수 없음\n{e}", fill=T.NG, font=T.F_SMALL)

    def _prims(self, prims, ext, box):
        """prims 를 box(x0,y0,x1,y1) 안에 맞춰 그림 (y 위로)."""
        cv = self.cv
        xmin, ymin, xmax, ymax = ext
        bx0, by0, bx1, by1 = box
        s = min((bx1 - bx0) / (xmax - xmin), (by1 - by0) / (ymax - ymin))
        ox = (bx0 + bx1) / 2 - (xmin + xmax) / 2 * s
        oy = (by0 + by1) / 2 + (ymin + ymax) / 2 * s

        def P(x, y):
            return ox + x * s, oy - y * s

        for pr in prims:
            col = LAYER_COLOR.get(pr.get("layer"), T.INK)
            if pr["t"] == "poly":
                pts = S.poly_points(pr)
                flat = [c for p in pts for c in P(*p)]
                if len(flat) >= 4:
                    cv.create_line(*flat, fill=col, width=1.6 if pr["layer"] == "bar2" else 1.2)
            elif pr["t"] in ("donut", "circle"):
                (x, y), rr = pr["c"], pr["r"]
                if pr["t"] == "donut":
                    rr = max(rr, 2.6 / s)
                cx, cy = P(x, y)
                cv.create_oval(cx - rr * s, cy - rr * s, cx + rr * s, cy + rr * s,
                               fill=col if pr["t"] == "donut" else "", outline=col)
            elif pr["t"] == "dim":
                (x1, y1), (x2, y2), (bx, by) = pr["p1"], pr["p2"], pr["base"]
                if pr["angle"] == 0:
                    a, b = P(x1, by), P(x2, by)
                    cv.create_line(*P(x1, y1), *a, fill=col, dash=(2, 2))
                    cv.create_line(*P(x2, y2), *b, fill=col, dash=(2, 2))
                    cv.create_line(*a, *b, fill=col, arrow="both", arrowshape=(6, 7, 2))
                    cv.create_text((a[0] + b[0]) / 2, a[1] - 8, text=pr["text"], fill=T.INK, font=T.F_SMALL)
                else:
                    a, b = P(bx, y1), P(bx, y2)
                    cv.create_line(*P(x1, y1), *a, fill=col, dash=(2, 2))
                    cv.create_line(*P(x2, y2), *b, fill=col, dash=(2, 2))
                    cv.create_line(*a, *b, fill=col, arrow="both", arrowshape=(6, 7, 2))
                    cv.create_text(a[0] - 9, (a[1] + b[1]) / 2, text=pr["text"], fill=T.INK, font=T.F_SMALL, angle=90)
        return s

    def _num(self, v):
        try:
            return float(v or 0)
        except ValueError:
            return 0.0

    def _beam(self, r, W, H):
        B, Hh = self._num(r.get("b")), self._num(r.get("h"))
        zones = M.beam_zones(r)
        n = len(zones)
        cw = W / n
        lines = []
        for i, (label, _pos, p) in enumerate(zones):
            x0 = i * cw
            self.cv.create_text(x0 + cw / 2, 14, text=label, font=T.F_UI_B, fill=T.NAVY)
            if B > 0 and Hh > 0:
                prims = S.beam_section(B, Hh, r.get("slab"), r.get(p + "top"), r.get(p + "bot"), r.get(p + "stir"))
                self._prims(prims, S.beam_extent(B, Hh), (x0 + 8, 30, x0 + cw - 8, H - 70))
            for j, (k, lb) in enumerate((("top", "상부"), ("bot", "하부"), ("stir", "늑근"))):
                v = r.get(p + k) or ""
                ok = M.is_valid("stir" if k == "stir" else "rebar", v)
                self.cv.create_text(x0 + cw / 2, H - 52 + j * 17, text=f"{lb}  {v or '·'}", font=T.F_SMALL,
                                    fill=T.INK if ok else T.NG)
            pt, pb = M.parse_rebar(r.get(p + "top", "")), M.parse_rebar(r.get(p + "bot", ""))
            lines.append(f"{label}: As상 {pt['area']:.0f} / As하 {pb['area']:.0f} mm²" if pt and pb else
                         f"{label}: As하 {pb['area']:.0f} mm²" if pb else f"{label}: —")
        if not (B > 0 and Hh > 0):
            self.cv.create_text(W / 2, H / 2, text="B, H 를 입력하세요", fill=T.FAINT, font=T.F_UI)
        self.info.config(text=f"B×H = {r.get('b') or '?'}×{r.get('h') or '?'}   슬래브 {r.get('slab') or '-'}   구분 {r.get('kind')}\n" + "\n".join(lines))

    def _column(self, r, W, H):
        B = self._num(r.get("b"))
        D = self._num(r.get("h")) if r.get("shape") != "원형" else B
        if B <= 0 or D <= 0:
            self.cv.create_text(W / 2, H / 2, text="B, D 를 입력하세요", fill=T.FAINT, font=T.F_UI)
        else:
            prims = S.column_section(B, D, r.get("shape", "사각"), r.get("main"), r.get("hoop_m"), r.get("tie_x"),
                                     r.get("tie_y"), r.get("arr"))
            self._prims(prims, (-420, -100, B + 120, D + 520), (10, 10, W - 10, H - 10))
        p = M.parse_rebar(r.get("main", ""))
        rho = ""
        if p and B > 0 and D > 0:
            Ag = B * D if r.get("shape") != "원형" else 3.14159 * B * B / 4
            rho = f"   ρ = {p['area'] / Ag * 100:.2f}%"
        self.info.config(text=f"{r.get('floor') or ''}  {r.get('b')}×{r.get('h')}  주근 {r.get('main') or '-'}{rho}\n"
                              f"대근 단부 {r.get('hoop_e') or '-'} / 중앙 {r.get('hoop_m') or '-'}")

    def _wall(self, r, W, H):
        t = self._num(r.get("t"))
        if t > 0:
            prims = S.wall_section(t, r.get("layer"), r.get("vert"), r.get("horz"))
            self._prims(prims, (-350, -150, 1050, t + 150), (10, 10, W - 10, H - 10))
        self.info.config(text=f"두께 {r.get('t')}  {r.get('layer')}\n수직 {r.get('vert') or '-'}   수평 {r.get('horz') or '-'}   (1 m 구간 평단면)")

    def _slab(self, r, W, H):
        cv = self.cv
        x0, y0, x1, y1 = 30, 40, W - 30, H - 40
        cv.create_rectangle(x0, y0, x1, y1, outline=T.NAVY, width=1.5)
        cv.create_text((x0 + x1) / 2, y0 - 14, text=f"{r.get('name')}  t={r.get('t')}  {r.get('kind')}", font=T.F_UI_B, fill=T.NAVY)
        cy = (y0 + y1) / 2
        cx = (x0 + x1) / 2
        cv.create_line(x0 + 10, cy, x1 - 10, cy, arrow="both", fill=T.ORANGE_D, width=2)
        cv.create_line(cx, y0 + 10, cx, y1 - 10, arrow="both", fill=T.BLUE, width=2)
        cv.create_text(cx, cy - 12, text="단변", fill=T.ORANGE_D, font=T.F_SMALL)
        cv.create_text(cx + 18, y0 + 20, text="장변", fill=T.BLUE, font=T.F_SMALL, anchor="w")
        self.info.config(text=(f"단변  상부 {r.get('x_te') or '-'} / {r.get('x_tm') or '-'}   하부 {r.get('x_be') or '-'} / {r.get('x_bm') or '-'}\n"
                               f"장변  상부 {r.get('y_te') or '-'} / {r.get('y_tm') or '-'}   하부 {r.get('y_be') or '-'} / {r.get('y_bm') or '-'}"))
