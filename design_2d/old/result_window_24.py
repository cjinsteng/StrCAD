"""
design_2d/result_window.py
해석 결과 창 — 다이어그램 + 반력표 + 단부/중앙 수치표
"""

import tkinter as tk
from tkinter import ttk
from .constants import *


class ResultWindow(tk.Toplevel):
    def __init__(self, parent, result, nodes, lines, supports=None):
        super().__init__(parent)
        self.title("Analysis Results")
        self.geometry("1060x700")
        self.minsize(860, 560)
        self.configure(bg=BG)

        # result: {"elems": {eid: {...}}, "reactions": {nid: {...}}}
        # (구버전 호환: dict of elems 직접 전달되면 래핑)
        if isinstance(result, dict) and "elems" in result:
            self.elems     = result["elems"]
            self.reactions = result.get("reactions", {})
        else:
            self.elems     = result or {}
            self.reactions = {}

        self.nodes    = nodes
        self.lines    = lines
        self.supports = supports or {}
        self._cur     = tk.StringVar(value="M")
        self._tab_refs = {}
        self._build()
        self.lift()

    # ═══════════════════════════════════════════════════════════
    def _build(self):
        # ── 헤더 ─────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG2, height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📊  Analysis Results",
                 font=("Malgun Gothic", 13, "bold"),
                 bg=BG2, fg=WHI).pack(side="left", padx=20)
        tk.Button(hdr, text="✕  닫기", command=self.destroy,
                  font=("Malgun Gothic", 9), bg=RED, fg=WHI,
                  relief="flat", cursor="hand2", padx=10
                  ).pack(side="right", padx=14, pady=10)
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")

        # ── 좌우 분할: 다이어그램(좌) + 수치표(우) ───────────
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # ── 좌: 다이어그램 영역 ───────────────────────────────
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)

        # 탭 버튼
        tab_fr = tk.Frame(left, bg=BG3)
        tab_fr.pack(fill="x")
        for code, label, color in [("M", "📈 Moment",  MOM_COLOR),
                                   ("V", "⚡ Shear",   SHEAR_COLOR),
                                   ("D", "↕ Deflection", DEFL_COLOR)]:
            b = tk.Button(tab_fr, text=f"  {label}  ",
                          command=lambda c=code: self._show(c),
                          font=("Malgun Gothic", 9, "bold"),
                          bg=ACC if code == "M" else BG4,
                          fg=WHI if code == "M" else color,
                          relief="flat", cursor="hand2", padx=12, pady=7)
            b.pack(side="left", padx=2, pady=5)
            self._tab_refs[code] = b
        tk.Frame(left, bg=BDR, height=1).pack(fill="x")

        # 다이어그램 캔버스
        self._canvas = tk.Canvas(left, bg=CANV_BG, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", lambda _: self._draw(self._cur.get()))

        # ── 우: 수치 테이블 영역 ──────────────────────────────
        right = tk.Frame(body, bg=BG2, width=340)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        tk.Frame(body, bg=BDR, width=1).pack(side="right", fill="y")

        # 스크롤 가능한 내부 패널
        rcanvas = tk.Canvas(right, bg=BG2, highlightthickness=0, width=338)
        rcanvas.pack(side="left", fill="both", expand=True)
        vsb = tk.Scrollbar(right, orient="vertical", command=rcanvas.yview)
        vsb.pack(side="right", fill="y")
        rcanvas.configure(yscrollcommand=vsb.set)
        rcanvas.bind("<MouseWheel>",
                     lambda e: rcanvas.yview_scroll(int(-e.delta/120), "units"))
        rcanvas.bind("<Button-4>",
                     lambda e: rcanvas.yview_scroll(-1, "units"))
        rcanvas.bind("<Button-5>",
                     lambda e: rcanvas.yview_scroll( 1, "units"))

        inner = tk.Frame(rcanvas, bg=BG2)
        rcanvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: rcanvas.configure(
                       scrollregion=rcanvas.bbox("all")))

        self._build_tables(inner)

        self.after(120, lambda: self._show("M"))

    # ═══════════════════════════════════════════════════════════
    #  수치 테이블 빌드
    # ═══════════════════════════════════════════════════════════
    def _build_tables(self, parent):
        pad = {"padx": 10, "pady": (12, 4)}

        # ── ① 지점 반력표 ─────────────────────────────────────
        self._section_hdr(parent, "⚓  지점 반력  (Reactions)", ACC)

        react_cols = ["절점", "Ry (kN)", "Rx (kN)", "Mz (kN·m)"]
        self._table_header(parent, react_cols, [50, 80, 80, 90])

        if self.reactions:
            for nid, rv in sorted(self.reactions.items()):
                sval  = self.supports.get(nid, {})
                stype = sval.get("type", "?") if isinstance(sval, dict) else sval
                Ry    = rv.get("Ry", 0.0)
                Rx    = rv.get("Rx", 0.0)
                Mz    = rv.get("Mz", 0.0)
                vals  = [f"N{nid}({stype})",
                         f"{Ry:+.3f}", f"{Rx:+.3f}", f"{Mz:+.3f}"]
                # 강조색: Ry가 주 반력
                hl = abs(Ry) > 1e-3 or abs(Mz) > 1e-3
                self._table_row(parent, vals, [50, 80, 80, 90],
                                fg=CYN if hl else TX2)
        else:
            tk.Label(parent, text="  반력 정보 없음",
                     font=("Consolas", 9), bg=BG2, fg=TX3
                     ).pack(anchor="w", padx=10)

        tk.Frame(parent, bg=BDR, height=1).pack(fill="x", padx=8, pady=6)

        # ── ② 부재별 모멘트 단부/중앙 값 ─────────────────────
        self._section_hdr(parent, "📐  부재 모멘트  M (kN·m)", MOM_COLOR)
        M_cols = ["부재", "좌단(i)", "중앙", "우단(j)", "최대|M|"]
        self._table_header(parent, M_cols, [46, 66, 66, 66, 66])
        for eid, res in sorted(self.elems.items()):
            M = res["M"]
            if not M: continue
            mid = len(M) // 2
            mmax = max(M, key=abs)
            vals = [f"L{eid}",
                    f"{M[0]:+.2f}", f"{M[mid]:+.2f}", f"{M[-1]:+.2f}",
                    f"{mmax:+.2f}"]
            self._table_row(parent, vals, [46, 66, 66, 66, 66],
                            fg=MOM_COLOR)

        tk.Frame(parent, bg=BDR, height=1).pack(fill="x", padx=8, pady=6)

        # ── ③ 부재별 전단력 단부/중앙 값 ─────────────────────
        self._section_hdr(parent, "⚡  부재 전단력  V (kN)", SHEAR_COLOR)
        V_cols = ["부재", "좌단(i)", "중앙", "우단(j)", "최대|V|"]
        self._table_header(parent, V_cols, [46, 66, 66, 66, 66])
        for eid, res in sorted(self.elems.items()):
            V = res["V"]
            if not V: continue
            mid = len(V) // 2
            vmax = max(V, key=abs)
            vals = [f"L{eid}",
                    f"{V[0]:+.2f}", f"{V[mid]:+.2f}", f"{V[-1]:+.2f}",
                    f"{vmax:+.2f}"]
            self._table_row(parent, vals, [46, 66, 66, 66, 66],
                            fg=SHEAR_COLOR)

        tk.Frame(parent, bg=BDR, height=1).pack(fill="x", padx=8, pady=6)

        # ── ④ 부재별 처짐 ─────────────────────────────────────
        self._section_hdr(parent, "↕  부재 처짐  δ (mm)", DEFL_COLOR)
        D_cols = ["부재", "좌단(i)", "중앙", "우단(j)", "최대δ"]
        self._table_header(parent, D_cols, [46, 66, 66, 66, 66])
        for eid, res in sorted(self.elems.items()):
            D = res["D"]
            if not D: continue
            mid = len(D) // 2
            dmax = max(D, key=abs)
            vals = [f"L{eid}",
                    f"{D[0]:+.3f}", f"{D[mid]:+.3f}", f"{D[-1]:+.3f}",
                    f"{dmax:+.3f}"]
            self._table_row(parent, vals, [46, 66, 66, 66, 66],
                            fg=DEFL_COLOR)

        tk.Frame(parent, bg=BG2, height=20).pack()   # 하단 여백

    # ── 헬퍼: 섹션 헤더 ─────────────────────────────────────
    def _section_hdr(self, parent, text, color):
        fr = tk.Frame(parent, bg=BG3)
        fr.pack(fill="x", padx=6, pady=(8, 2))
        tk.Label(fr, text=text,
                 font=("Malgun Gothic", 9, "bold"),
                 bg=BG3, fg=color, pady=5
                 ).pack(anchor="w", padx=8)

    # ── 헬퍼: 테이블 헤더 행 ────────────────────────────────
    def _table_header(self, parent, cols, widths):
        row = tk.Frame(parent, bg=BG4)
        row.pack(fill="x", padx=6, pady=(0, 1))
        for col, w in zip(cols, widths):
            tk.Label(row, text=col, width=w//7,
                     font=("Malgun Gothic", 8, "bold"),
                     bg=BG4, fg=TX2,
                     anchor="center"
                     ).pack(side="left", padx=1, pady=3)

    # ── 헬퍼: 데이터 행 ─────────────────────────────────────
    def _table_row(self, parent, vals, widths, fg=TXT):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", padx=6, pady=0)
        tk.Frame(row, bg=BDR, height=1).pack(fill="x", pady=0)
        data_row = tk.Frame(row, bg=BG2)
        data_row.pack(fill="x")
        for val, w in zip(vals, widths):
            tk.Label(data_row, text=val, width=w//7,
                     font=("Consolas", 9),
                     bg=BG2, fg=fg,
                     anchor="center"
                     ).pack(side="left", padx=1, pady=3)

    # ═══════════════════════════════════════════════════════════
    #  탭 전환 / 다이어그램
    # ═══════════════════════════════════════════════════════════
    def _show(self, code):
        self._cur.set(code)
        colors = {"M": MOM_COLOR, "V": SHEAR_COLOR, "D": DEFL_COLOR}
        for c2, btn in self._tab_refs.items():
            btn.config(bg=ACC if c2 == code else BG4,
                       fg=WHI if c2 == code else colors[c2])
        self._draw(code)

    def _draw(self, code):
        c = self._canvas
        c.delete("all")
        W = c.winfo_width()  or 680
        H = c.winfo_height() or 500
        pad_l, pad_r, pad_t, pad_b = 72, 30, 48, 72

        colors = {"M": MOM_COLOR, "V": SHEAR_COLOR, "D": DEFL_COLOR}
        titles = {"M": "Bending Moment  [kN·m]",
                  "V": "Shear Force  [kN]",
                  "D": "Deflection  [mm]"}
        color = colors[code]

        c.create_text(W // 2, 22, text=titles[code],
                      fill=WHI, font=("Malgun Gothic", 11, "bold"))

        if not self.elems:
            c.create_text(W//2, H//2, text="해석 결과 없음",
                          fill=TX3, font=("Malgun Gothic", 11))
            return

        # 전체 x·값 범위 수집
        all_xs, all_vals = [], []
        for eid, res in self.elems.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line: continue
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            if not n1: continue
            x0 = n1["x"]
            all_xs   += [x0 + x for x in res["x"]]
            all_vals += res[code]

        if not all_xs:
            return

        xmin, xmax = min(all_xs), max(all_xs)
        vmin, vmax = min(all_vals), max(all_vals)
        if abs(vmax - vmin) < 1e-9:
            vmin -= 1; vmax += 1

        draw_w = W - pad_l - pad_r
        draw_h = H - pad_t - pad_b

        def mx(x):
            return pad_l + (x - xmin) / (xmax - xmin + 1e-9) * draw_w
        def my(v):
            return pad_t + draw_h * (1 - (v - vmin) / (vmax - vmin + 1e-9))

        zy = my(0)

        # 격자선
        for v in [vmin, vmin/2, 0, vmax/2, vmax]:
            yg = my(v)
            c.create_line(pad_l, yg, W - pad_r, yg,
                          fill=BG3, width=1, dash=(3, 5))

        # Y=0 기준선
        c.create_line(pad_l, zy, W - pad_r, zy,
                      fill=TX3, width=1, dash=(4, 4))

        # 부재 기준선 + 절점 이름
        c.create_line(mx(xmin), zy, mx(xmax), zy,
                      fill=RC_COLOR, width=3)

        # 절점 레이블
        node_x_map = {n["id"]: n["x"] for n in self.nodes}
        drawn_xs = set()
        for eid, res in self.elems.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line: continue
            for nid in [line["n1"], line["n2"]]:
                nx_ = node_x_map.get(nid)
                if nx_ is None or nx_ in drawn_xs: continue
                drawn_xs.add(nx_)
                cx_ = mx(nx_)
                c.create_oval(cx_-4, zy-4, cx_+4, zy+4,
                              fill=NODE_COLOR, outline="")
                c.create_text(cx_, zy + 14, text=f"N{nid}",
                              fill=TX2, font=("Consolas", 8))
                c.create_text(cx_, H - pad_b + 18,
                              text=f"{nx_:.0f}",
                              fill=TX3, font=("Consolas", 7))

        # 다이어그램 폴리곤 + 해칭
        for eid, res in self.elems.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line: continue
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            if not n1: continue
            x0   = n1["x"]
            vals = res[code]
            xabs = [x0 + x for x in res["x"]]

            top  = [(mx(xabs[k]), my(vals[k])) for k in range(len(vals))]
            base = [(mx(xabs[k]), zy)          for k in range(len(vals))]

            # 해칭
            step = max(1, len(vals) // 40)
            for ki in range(0, len(vals), step):
                c.create_line(base[ki][0], base[ki][1],
                              top[ki][0],  top[ki][1],
                              fill=color, width=1)

            # 외곽선
            pts_line = [v for pt in top for v in pt]
            if len(pts_line) >= 4:
                c.create_line(*pts_line, fill=color, width=2, smooth=True)
            # 끝선
            c.create_line(base[0][0], base[0][1], top[0][0], top[0][1],
                          fill=color, width=2)
            c.create_line(base[-1][0], base[-1][1], top[-1][0], top[-1][1],
                          fill=color, width=2)

        # Y축 눈금 + 레이블
        unit = "kN·m" if code == "M" else ("kN" if code == "V" else "mm")
        tick_vals = sorted({vmin, 0.0, vmax})
        # 중간값도 추가
        if abs(vmax) > 1e-9:
            tick_vals.append(vmax / 2)
        if abs(vmin) > 1e-9:
            tick_vals.append(vmin / 2)
        for val in tick_vals:
            yp = my(val)
            if pad_t - 4 < yp < H - pad_b + 4:
                c.create_line(pad_l - 5, yp, pad_l, yp, fill=TX2, width=1)
                c.create_text(pad_l - 7, yp,
                              text=f"{val:.2f}",
                              fill=color, font=("Consolas", 8), anchor="e")

        # X축 레이블
        c.create_text(pad_l, H - pad_b + 32,
                      text=f"{xmin:.0f} mm",
                      fill=TX2, font=("Consolas", 8))
        c.create_text(W - pad_r, H - pad_b + 32,
                      text=f"{xmax:.0f} mm",
                      fill=TX2, font=("Consolas", 8), anchor="e")

        # 최대|값| 강조 마커
        if all_vals:
            mi  = max(range(len(all_vals)), key=lambda i: abs(all_vals[i]))
            mv  = all_vals[mi]
            mxv = all_xs[mi]
            cx_ = mx(mxv); cy_ = my(mv)
            c.create_oval(cx_-5, cy_-5, cx_+5, cy_+5,
                          fill=color, outline=WHI, width=1)
            lbl_y = cy_ - 18 if mv >= 0 else cy_ + 18
            anchor = "s" if mv >= 0 else "n"
            c.create_text(cx_, lbl_y,
                          text=f"max {mv:+.3f} {unit}",
                          fill=color, font=("Malgun Gothic", 9, "bold"),
                          anchor=anchor)

        # 반력 마커 (다이어그램 위에 화살표로)
        if self.reactions:
            for nid, rv in self.reactions.items():
                Ry = rv.get("Ry", 0.0)
                Mz = rv.get("Mz", 0.0)
                nx_ = node_x_map.get(nid)
                if nx_ is None: continue
                cx_ = mx(nx_)
                # 수직 반력 화살표
                if abs(Ry) > 1e-3:
                    arr_len = 28
                    tip_y   = zy - arr_len * (1 if Ry > 0 else -1)
                    c.create_line(cx_, zy, cx_, tip_y,
                                  fill=CYN, width=2, arrow=tk.LAST,
                                  arrowshape=(10, 12, 4))
                    c.create_text(cx_ + 6, (zy + tip_y) / 2,
                                  text=f"{Ry:+.2f}kN",
                                  fill=CYN, font=("Consolas", 8),
                                  anchor="w")
