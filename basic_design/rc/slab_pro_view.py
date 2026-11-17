"""
basic_design/rc/slab_pro_view.py
Slab Pro — FEM 결과 보기 창 (모멘트 · 전단 · 처짐,  2D 등고선 / 3D 변형 형상)

  · 위쪽 버튼으로 결과 종류 선택 (Mxx, Myy, Mxy, Vxx, Vyy, 처짐)
  · 2D: 요소별 색 + 값      3D: 처짐 형상 위에 색 (마우스로 끌어 회전, 휠로 확대)
"""
import math
import tkinter as tk

import numpy as np

from .. import theme as T
from ..report import fonts
from . import slab_pro as P


class ResultViewer:
    def __init__(self, parent, res, field="mx", mode="2d", title=""):
        self.res = res
        self.field = tk.StringVar(parent, value=field)
        self.mode = tk.StringVar(parent, value=mode)
        self.show_val = tk.BooleanVar(parent, value=True)
        self.deform = tk.BooleanVar(parent, value=True)
        self.az, self.el, self.zoom = -35.0, 32.0, 1.0
        self._drag = None
        self.win = win = tk.Toplevel(parent)
        win.title(title or "FEM 결과")
        win.geometry("980x760")
        win.minsize(720, 520)
        win.configure(bg=T.SURFACE)
        T.set_icon(win)
        f_n, f_b = (T.FAM, 9), (T.FAM, 9, "bold")

        bar = tk.Frame(win, bg=T.NAVY)
        bar.pack(fill="x")
        tk.Label(bar, text="FEM 결과", font=(T.FAM, 11, "bold"), bg=T.NAVY, fg="white").pack(side="left", padx=(12, 10), pady=6)
        for key, lbl, _, _ in P.FIELDS:
            tk.Radiobutton(bar, text=lbl, value=key, variable=self.field, indicatoron=False, font=f_b, bg=T.NAVY_2,
                           fg="white", selectcolor=T.ORANGE, activebackground=T.ORANGE, activeforeground="white",
                           relief="flat", padx=10, pady=3, cursor="hand2", command=self.redraw).pack(side="left", padx=2, pady=6)

        opt = tk.Frame(win, bg=T.SURFACE)
        opt.pack(fill="x", padx=10, pady=(6, 2))
        for val, lbl in (("2d", "2D 등고선"), ("3d", "3D 형상")):
            tk.Radiobutton(opt, text=lbl, value=val, variable=self.mode, font=f_b, bg=T.SURFACE, fg=T.INK,
                           selectcolor="white", command=self.redraw).pack(side="left", padx=(0, 8))
        tk.Checkbutton(opt, text="값 표시 (2D)", variable=self.show_val, font=f_n, bg=T.SURFACE, command=self.redraw).pack(
            side="left", padx=8)
        tk.Checkbutton(opt, text="처짐 형상 (3D)", variable=self.deform, font=f_n, bg=T.SURFACE, command=self.redraw).pack(
            side="left", padx=8)
        tk.Button(opt, text="시점 초기화", font=f_n, relief="groove", bg="white", command=self.reset_view).pack(side="left", padx=8)
        self.info = tk.Label(opt, text="", font=f_n, bg=T.SURFACE, fg=T.MUTED)
        self.info.pack(side="right")

        self.cv = cv = tk.Canvas(win, bg="white", highlightthickness=1, highlightbackground=T.LINE)
        cv.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        cv.bind("<Configure>", lambda _: self.redraw())
        cv.bind("<ButtonPress-1>", self._press)
        cv.bind("<B1-Motion>", self._move)
        cv.bind("<MouseWheel>", lambda e: self._wheel(1 if e.delta > 0 else -1))
        cv.bind("<Button-4>", lambda _: self._wheel(1))
        cv.bind("<Button-5>", lambda _: self._wheel(-1))
        win.after(50, self.redraw)

    # ── 외부에서 ─────────────────────────────────────────────
    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def show(self, res=None, field=None, mode=None):
        if res is not None:
            self.res = res
        if field:
            self.field.set(field)
        if mode:
            self.mode.set(mode)
        self.win.deiconify()
        self.win.lift()
        self.redraw()

    def set_result(self, res):
        self.res = res
        if res is not None:
            self.redraw()

    def reset_view(self):
        self.az, self.el, self.zoom = -35.0, 32.0, 1.0
        self.redraw()

    # ── 마우스 ───────────────────────────────────────────────
    def _press(self, e):
        self._drag = (e.x, e.y)

    def _move(self, e):
        if self.mode.get() != "3d" or self._drag is None:
            return
        dx, dy = e.x - self._drag[0], e.y - self._drag[1]
        self._drag = (e.x, e.y)
        self.az = (self.az + dx * 0.5) % 360
        self.el = max(8.0, min(88.0, self.el + dy * 0.4))
        self.redraw()

    def _wheel(self, k):
        if self.mode.get() != "3d":
            return
        self.zoom = max(0.4, min(4.0, self.zoom * (1.1 if k > 0 else 1 / 1.1)))
        self.redraw()

    # ── 그리기 ───────────────────────────────────────────────
    def redraw(self):
        cv = self.cv
        cv.delete("all")
        r = self.res
        if r is None:
            return
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50 or h < 50:
            return
        key = self.field.get()
        _, lbl, unit, desc = next(f for f in P.FIELDS if f[0] == key)
        fld = r["fields"][key]
        self.info.config(text=f"{desc}      max {fld.max():.2f}   min {fld.min():.2f} {unit}      "
                              + ("끌기: 회전 · 휠: 확대" if self.mode.get() == "3d" else f"조합 {r['gov']}"))
        if self.mode.get() == "2d":
            P.draw_contour(cv, 16, 10, w - 32, h - 20, r["xs"], r["ys"], fld, f"{lbl}  ({unit})   — {r['name']}",
                           values=self.show_val.get())
        else:
            self._draw_3d(w, h, fld, f"{lbl}  ({unit})   — {r['name']}")

    def _draw_3d(self, w, h, fld, title):
        cv, r = self.cv, self.res
        F = fonts(cv)
        xs, ys = r["xs"], r["ys"]
        lx, ly = xs[-1], ys[-1]
        nx, ny = len(xs) - 1, len(ys) - 1
        size = max(lx, ly)
        wz = r["w_elastic"]
        wmax = float(np.abs(wz).max())
        zs = (-wz / wmax * 0.12 * size) if (self.deform.get() and wmax > 1e-12) else np.zeros_like(wz)
        az, el = math.radians(self.az), math.radians(self.el)
        ca, sa, ce, se = math.cos(az), math.sin(az), math.cos(el), math.sin(el)
        gx, gy = np.meshgrid(xs - lx / 2.0, ys - ly / 2.0)
        xr = gx * ca - gy * sa
        yr = gx * sa + gy * ca
        sx = xr
        sy = yr * se + zs * ce                      # 화면 위쪽 +
        depth = yr * ce - zs * se                   # 클수록 멀다
        # 화면 맞춤 (변형 전 외곽 기준)
        cxs = np.array([-lx / 2, lx / 2, lx / 2, -lx / 2])
        cys = np.array([-ly / 2, -ly / 2, ly / 2, ly / 2])
        bx = cxs * ca - cys * sa
        by = (cxs * sa + cys * ca) * se
        ext_x = bx.max() - bx.min()
        ext_y = by.max() - by.min() + 0.3 * size * ce
        sc = min((w - 140) / ext_x, (h - 80) / ext_y) * self.zoom
        ox, oy = (w - 70) / 2.0, h / 2.0 + 10
        px = ox + sx * sc
        py = oy - sy * sc
        vmin, vmax = float(fld.min()), float(fld.max())
        # 변형 전 외곽 (바닥 기준선)
        base = [(ox + bx[k] * sc, oy - by[k] * sc) for k in range(4)]
        cv.create_polygon(base, fill="", outline="#9CA3AF", dash=(4, 3))
        quads = []
        for j in range(ny):
            for i in range(nx):
                dep = depth[j, i] + depth[j, i + 1] + depth[j + 1, i] + depth[j + 1, i + 1]
                quads.append((dep, i, j))
        quads.sort(reverse=True)                    # 먼 것부터
        for _, i, j in quads:
            v = 0.25 * (fld[j, i] + fld[j, i + 1] + fld[j + 1, i] + fld[j + 1, i + 1])
            cv.create_polygon(px[j, i], py[j, i], px[j, i + 1], py[j, i + 1], px[j + 1, i + 1], py[j + 1, i + 1],
                              px[j + 1, i], py[j + 1, i], fill=P.band_color(v, vmin, vmax), outline="#374151")
        # 모서리 지지 표시
        for key, _, ix, iy in P.CORNERS:
            if r["corners"].get(key, True):
                jj, ii = iy * ny, ix * nx
                cv.create_rectangle(px[jj, ii] - 4, py[jj, ii] - 4, px[jj, ii] + 4, py[jj, ii] + 4, fill="#dc2626",
                                    outline="#7f1d1d")
        # 축 표시
        for lbl, vx, vy in (("X", lx / 2 + 0.06 * size, -ly / 2), ("Y", -lx / 2, ly / 2 + 0.06 * size)):
            ax = ox + (vx * ca - vy * sa) * sc
            ay = oy - (vx * sa + vy * ca) * se * sc
            cv.create_text(ax, ay, text=lbl, font=F["b"], fill=T.NAVY)
        cv.create_text(16, 16, text=f"▶ {title}", anchor="w", font=F["b"], fill=T.NAVY)
        if self.deform.get():
            cv.create_text(16, 36, text=f"처짐 형상 (탄성 D+L, 최대 {wmax:.2f} mm 를 과장 표시)", anchor="w", font=F["s"],
                           fill=T.MUTED)
        P.draw_legend(cv, w - 70, 50, min(h - 120, 260), vmin, vmax, F["s"])
