"""
design_2d/result_window.py
해석 결과 창 — Moment / Shear / Deflection 탭
"""

import tkinter as tk
from .constants import *


class ResultWindow(tk.Toplevel):
    def __init__(self, parent, result, nodes, lines):
        super().__init__(parent)
        self.title("Analysis Results")
        self.geometry("960x640")
        self.minsize(760, 480)
        self.configure(bg=BG)
        self.result = result    # {eid: {'x','M','V','D','L'}}
        self.nodes  = nodes     # [{'id','x','y','cx','cy'}]
        self.lines  = lines     # [{'id','n1','n2'}]
        self._cur   = tk.StringVar(value="M")
        self._tab_refs = {}
        self._build()
        self.lift()

    # ── 빌드 ─────────────────────────────────────────────────
    def _build(self):
        # 헤더
        hdr = tk.Frame(self, bg=BG2, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📊  Analysis Results",
                 font=("Malgun Gothic", 13, "bold"),
                 bg=BG2, fg=WHI).pack(side="left", padx=20)
        tk.Button(hdr, text="✕  닫기", command=self.destroy,
                  font=("Malgun Gothic", 9), bg=RED, fg=WHI,
                  relief="flat", cursor="hand2", padx=10).pack(side="right", padx=14, pady=10)
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")

        # 탭 버튼
        tab_fr = tk.Frame(self, bg=BG3)
        tab_fr.pack(fill="x")
        for code, label, color in [("M", "Moment Diagram",  MOM_COLOR),
                                   ("V", "Shear Diagram",   SHEAR_COLOR),
                                   ("D", "Deflection",      DEFL_COLOR)]:
            b = tk.Button(tab_fr, text=f"  {label}  ",
                          command=lambda c=code: self._show(c),
                          font=("Malgun Gothic", 9, "bold"),
                          bg=ACC if code == "M" else BG4,
                          fg=WHI if code == "M" else color,
                          relief="flat", cursor="hand2", padx=14, pady=8)
            b.pack(side="left", padx=2, pady=6)
            b.bind("<Enter>", lambda _, btn=b, c=code: btn.config(
                bg=ACCH if self._cur.get() == c else BG5))
            b.bind("<Leave>", lambda _, btn=b, c=code: btn.config(
                bg=ACC if self._cur.get() == c else BG4))
            self._tab_refs[code] = b

        tk.Frame(self, bg=BDR, height=1).pack(fill="x")

        # 캔버스
        self._canvas = tk.Canvas(self, bg=CANV_BG, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)

        # 수치 요약
        self._sum_var = tk.StringVar()
        tk.Label(self, textvariable=self._sum_var,
                 font=("Consolas", 9), bg=BG2, fg=TX2,
                 anchor="w").pack(fill="x", padx=16, pady=6)

        self._canvas.bind("<Configure>", lambda _: self._draw(self._cur.get()))
        self.after(120, lambda: self._show("M"))

    # ── 탭 전환 ──────────────────────────────────────────────
    def _show(self, code):
        self._cur.set(code)
        for c2, btn in self._tab_refs.items():
            colors = {"M": MOM_COLOR, "V": SHEAR_COLOR, "D": DEFL_COLOR}
            btn.config(bg=ACC if c2 == code else BG4,
                       fg=WHI if c2 == code else colors[c2])
        self._draw(code)

    # ── 다이어그램 그리기 ─────────────────────────────────────
    def _draw(self, code):
        c = self._canvas
        c.delete("all")
        W = c.winfo_width()  or 900
        H = c.winfo_height() or 520
        pad_l, pad_r, pad_t, pad_b = 80, 40, 50, 80

        colors = {"M": MOM_COLOR, "V": SHEAR_COLOR, "D": DEFL_COLOR}
        titles = {"M": "Bending Moment (kN·m)",
                  "V": "Shear Force (kN)",
                  "D": "Deflection (mm)"}
        color = colors[code]

        # 제목
        c.create_text(W // 2, 22, text=titles[code],
                      fill=WHI, font=("Malgun Gothic", 11, "bold"))

        if not self.result:
            return

        # 전체 X 범위 + 값 범위 수집
        all_xs, all_vals = [], []
        for eid, res in self.result.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line:
                continue
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            if not n1:
                continue
            x0 = n1["x"]
            all_xs   += [x0 + x for x in res["x"]]
            all_vals += res[code]

        if not all_xs:
            return

        xmin, xmax = min(all_xs), max(all_xs)
        vmin, vmax = min(all_vals), max(all_vals)
        vspan = max(abs(vmin), abs(vmax)) or 1.0

        draw_w = W - pad_l - pad_r
        draw_h = H - pad_t - pad_b
        zero_y = pad_t + draw_h * vmax / (vmax - vmin + 1e-12) if vmin < 0 else pad_t + draw_h

        def mx(x):
            return pad_l + (x - xmin) / (xmax - xmin + 1e-9) * draw_w
        def my(v):
            return pad_t + draw_h * (1 - (v - vmin) / (vmax - vmin + 1e-9))

        # Y=0 기준선
        zy = my(0)
        c.create_line(pad_l, zy, W - pad_r, zy,
                      fill=TX3, width=1, dash=(4, 4))

        # 부재 기준선
        c.create_line(mx(xmin), zy, mx(xmax), zy,
                      fill=LINE_COLOR, width=3)

        # 다이어그램 폴리곤
        for eid, res in self.result.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line:
                continue
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            if not n1:
                continue
            x0   = n1["x"]
            vals = res[code]
            xabs = [x0 + x for x in res["x"]]

            top  = [(mx(xabs[k]), my(vals[k])) for k in range(len(vals))]
            base = [(mx(xabs[k]), zy)          for k in range(len(vals))]
            poly = top + list(reversed(base))
            flat = [v for pt in poly for v in pt]
            if len(flat) >= 6:
                c.create_polygon(flat, fill=color, stipple="gray25", outline="")
            pts_line = [v for pt in top for v in pt]
            if len(pts_line) >= 4:
                c.create_line(*pts_line, fill=color, width=2, smooth=True)

        # Y축 눈금
        for val in [vmax, 0, vmin]:
            yp = my(val)
            unit = "kN·m" if code == "M" else ("kN" if code == "V" else "mm")
            c.create_text(pad_l - 6, yp, text=f"{val:.2f}",
                          fill=color, font=("Consolas", 8), anchor="e")
            c.create_line(pad_l - 3, yp, pad_l, yp, fill=TX3, width=1)

        # X축 눈금
        c.create_text(mx(xmin), H - pad_b + 14, text=f"{xmin:.0f}",
                      fill=TX2, font=("Consolas", 8))
        c.create_text(mx(xmax), H - pad_b + 14, text=f"{xmax:.0f}",
                      fill=TX2, font=("Consolas", 8))

        # 최대·최소 표시
        if all_vals:
            mi  = max(range(len(all_vals)), key=lambda i: abs(all_vals[i]))
            mv  = all_vals[mi]
            mxv = all_xs[mi]
            unit = "kN·m" if code == "M" else ("kN" if code == "V" else "mm")
            c.create_oval(mx(mxv) - 4, my(mv) - 4,
                          mx(mxv) + 4, my(mv) + 4,
                          fill=color, outline=WHI, width=1)
            c.create_text(mx(mxv), my(mv) - 16,
                          text=f"  {mv:.3f} {unit}",
                          fill=color, font=("Malgun Gothic", 9, "bold"),
                          anchor="s")

        # 요약 텍스트 (하단)
        summary = []
        for eid, res in self.result.items():
            vals = res[code]
            unit = "kN·m" if code == "M" else ("kN" if code == "V" else "mm")
            summary.append(
                f"Elem{eid}: max={max(vals):.3f}  min={min(vals):.3f}  [{unit}]")
        self._sum_var.set("   |   ".join(summary))
