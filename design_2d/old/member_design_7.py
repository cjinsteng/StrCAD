"""
design_2d/member_design.py
부재 설계 팝업 — RC 보 설계 (KDS 41 00 기준)

수정사항:
1. 다이어그램 해치: stipple 제거 → 수직 해칭선 직접 그리기
2. 노드 위치(mm) 다이어그램에 표시
3. 좌측 입력 모든 항목 Entry로 변경 가능
4. 임의 위치(mm) 입력 → 해당 위치 M/V/D 설계값 조회
5. 결과 영역 전체 tkinter Table(Grid) 위젯으로 구성
"""

import tkinter as tk
from tkinter import messagebox, ttk
import math

from .constants import *


# ════════════════════════════════════════════════════════════
#  RC 설계 유틸
# ════════════════════════════════════════════════════════════
def _design_flexure(Mu_kNm, fck, fy_main, b_mm, d_mm):
    """KDS 41 직사각형 단면 휨 설계 → (rho_pct, Ast, phi_Mn, OK)"""
    phi  = 0.85
    Mu_N = abs(Mu_kNm) * 1e6
    if Mu_N < 1e-3:
        rho_min = max(0.25*math.sqrt(fck)/fy_main, 1.4/fy_main)
        Ast_min = rho_min * b_mm * d_mm
        return rho_min*100, Ast_min, 0.0, True
    Rn    = Mu_N / (phi * b_mm * d_mm**2)
    under = 1 - 2*Rn / (0.85*fck)
    if under < 0:
        return None, None, None, False
    rho   = 0.85*fck/fy_main * (1 - math.sqrt(under))
    rho_min = max(0.25*math.sqrt(fck)/fy_main, 1.4/fy_main)
    rho   = max(rho, rho_min)
    Ast   = rho * b_mm * d_mm
    a     = Ast * fy_main / (0.85*fck*b_mm)
    phi_Mn = phi * Ast * fy_main * (d_mm - a/2) / 1e6
    return rho*100, Ast, phi_Mn, True


def _design_shear(Vu_kN, fck, b_mm, d_mm):
    """KDS 41 전단 검토 → (phi_Vc kN, OK)"""
    Vc     = (1/6)*math.sqrt(fck)*b_mm*d_mm
    phi_Vc = 0.75*Vc/1e3
    return phi_Vc, abs(Vu_kN) <= phi_Vc


def _rebar_spacing(Ast_mm2, fy):
    """철근 간격 → dict  (슬래브 1m 폭)"""
    if Ast_mm2 <= 0:
        return {k: "@300" for k in ["D10","D10+D13","D13","D13+D16"]}
    bars   = {"D10": 71.3, "D13": 126.7, "D16": 198.6}
    combos = {"D10+D13": 71.3+126.7, "D13+D16": 126.7+198.6}
    out = {}
    for n, a in {**bars, **combos}.items():
        s = a / (Ast_mm2/1000) * 1000
        s = min(300, max(50, round(s/10)*10))
        out[n] = f"@{int(s)}"
    return out


def _interp_at(x_abs, x_start, x_end, xs_local, vals):
    """절대 좌표 x_abs 에서의 보간값"""
    L = x_end - x_start
    if L < 1e-9:
        return vals[0] if vals else 0.0
    t_target = (x_abs - x_start) / L
    t_target = max(0.0, min(1.0, t_target))
    x_norm   = [xi/L for xi in xs_local]
    for i in range(len(x_norm)-1):
        if x_norm[i] <= t_target <= x_norm[i+1]:
            dt = x_norm[i+1] - x_norm[i]
            if dt < 1e-12:
                return vals[i]
            f = (t_target - x_norm[i]) / dt
            return vals[i] + f*(vals[i+1]-vals[i])
    return vals[-1]


# ════════════════════════════════════════════════════════════
#  Table 위젯 헬퍼
# ════════════════════════════════════════════════════════════
class SimpleTable(tk.Frame):
    """
    tkinter 순수 그리드 테이블
    headers : [str, ...]
    rows    : [[str, ...], ...]
    col_w   : [int, ...]  (픽셀)
    row_colors: [(bg, fg), ...] None=기본
    """
    H_HDR = 28
    H_ROW = 24

    def __init__(self, parent, headers, rows,
                 col_w=None, row_colors=None,
                 hdr_bg=BG3, hdr_fg=ACC,
                 row_bg=BG2, row_fg=TXT,
                 alt_bg=BG4,
                 font_hdr=("Malgun Gothic", 8, "bold"),
                 font_row=("Consolas", 8)):
        super().__init__(parent, bg=BDR)
        self._build(headers, rows, col_w, row_colors,
                    hdr_bg, hdr_fg, row_bg, row_fg, alt_bg,
                    font_hdr, font_row)

    def _build(self, headers, rows, col_w, row_colors,
               hdr_bg, hdr_fg, row_bg, row_fg, alt_bg,
               font_hdr, font_row):
        n = len(headers)
        if col_w is None:
            col_w = [100]*n

        # 헤더
        hdr_frame = tk.Frame(self, bg=hdr_bg)
        hdr_frame.pack(fill="x")
        for j, (h, w) in enumerate(zip(headers, col_w)):
            lbl = tk.Label(hdr_frame, text=h,
                           font=font_hdr, bg=hdr_bg, fg=hdr_fg,
                           width=0, anchor="center",
                           padx=4, pady=4,
                           relief="flat")
            lbl.place(x=sum(col_w[:j])+j, y=0,
                      width=w, height=self.H_HDR)
        hdr_frame.config(height=self.H_HDR,
                         width=sum(col_w)+n)
        hdr_frame.pack_propagate(False)

        # 구분선
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")

        # 행
        for i, row in enumerate(rows):
            if row_colors and i < len(row_colors) and row_colors[i]:
                rbg, rfg = row_colors[i]
            else:
                rbg = alt_bg if i % 2 else row_bg
                rfg = row_fg
            rf = tk.Frame(self, bg=rbg,
                          height=self.H_ROW,
                          width=sum(col_w)+n)
            rf.pack(fill="x")
            rf.pack_propagate(False)
            for j, (cell, w) in enumerate(zip(row, col_w)):
                tk.Label(rf, text=str(cell),
                         font=font_row, bg=rbg, fg=rfg,
                         anchor="center", padx=3,
                         relief="flat").place(
                             x=sum(col_w[:j])+j, y=0,
                             width=w, height=self.H_ROW)
            # 행 구분선
            tk.Frame(self, bg=BDR, height=1).pack(fill="x")


# ════════════════════════════════════════════════════════════
class MemberDesignWindow:

    def __init__(self, parent, analysis_result, nodes, lines):
        self.parent          = parent
        self.analysis_result = analysis_result
        self.nodes           = nodes
        self.lines           = lines

        # 설계 변수
        self.fck      = tk.DoubleVar(value=24.0)
        self.fy_main  = tk.DoubleVar(value=400.0)
        self.fy_high  = tk.DoubleVar(value=600.0)
        self.b_slab   = tk.DoubleVar(value=1000.0)
        self.h_slab   = tk.DoubleVar(value=200.0)
        self.cover    = tk.DoubleVar(value=40.0)
        self.std_code = tk.StringVar(value="KDS 41 00")

        # ④ 임의 위치 입력
        self.query_x  = tk.StringVar(value="")

        # 내부 캐시
        self._elem_data  = []   # [(x_start, x_end, res), ...]
        self._last_fck   = None
        self._last_fy    = None
        self._last_b     = None
        self._last_d     = None

        self.win = tk.Toplevel(parent)
        self.win.title("부재 설계  —  RC Beam Design (KDS 41)")
        self.win.configure(bg=BG)
        self.win.geometry("1120x820")
        self.win.minsize(960, 700)
        self.win.transient(parent)

        self._build()
        self._prepare_elem_data()

    # ════════════════════════════════════════════════════════
    #  elem_data 준비 (x_start, x_end, res)
    # ════════════════════════════════════════════════════════
    def _prepare_elem_data(self):
        self._elem_data = []
        for eid, res in self.analysis_result.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line: continue
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == line["n2"]), None)
            if not n1 or not n2: continue
            self._elem_data.append((float(n1["x"]), float(n2["x"]), res))
        self._elem_data.sort(key=lambda e: e[0])

    # ════════════════════════════════════════════════════════
    #  UI
    # ════════════════════════════════════════════════════════
    def _build(self):
        win = self.win
        # 헤더
        hdr = tk.Frame(win, bg=BG2, height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📐  부재 설계  —  RC Beam Design",
                 font=("Malgun Gothic", 13, "bold"),
                 bg=BG2, fg=WHI).pack(side="left", padx=18)
        tk.Button(hdr, text="✕ 닫기", command=self.win.destroy,
                  font=("Malgun Gothic", 9), bg=BG3, fg=TX2,
                  relief="flat", cursor="hand2",
                  padx=10, pady=4).pack(side="right", padx=10, pady=8)
        tk.Frame(win, bg=BDR, height=1).pack(fill="x")

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True)

        # 좌측 입력 패널
        lp = tk.Frame(body, bg=BG2, width=270)
        lp.pack(side="left", fill="y"); lp.pack_propagate(False)
        tk.Frame(body, bg=BDR, width=1).pack(side="left", fill="y")

        # 우측 결과 패널
        rp = tk.Frame(body, bg=BG)
        rp.pack(side="left", fill="both", expand=True)

        self._build_input(lp)
        self._build_right(rp)

    # ────────────────────────────────────────────────────────
    #  ③ 왼쪽 입력 (모두 Entry)
    # ────────────────────────────────────────────────────────
    def _build_input(self, parent):
        def section(title):
            tk.Frame(parent, bg=BG3, height=1).pack(fill="x", pady=(10,0))
            tk.Label(parent, text=title,
                     font=("Malgun Gothic", 9, "bold"),
                     bg=BG3, fg=ACC,
                     padx=10, pady=6).pack(fill="x")
            tk.Frame(parent, bg=BDR, height=1).pack(fill="x")

        def inp(label, var, unit=""):
            f = tk.Frame(parent, bg=BG2)
            f.pack(fill="x", padx=10, pady=3)
            tk.Label(f, text=label,
                     font=("Malgun Gothic", 8), bg=BG2, fg=TX2,
                     width=10, anchor="w").pack(side="left")
            e = tk.Entry(f, textvariable=var,
                         font=("Malgun Gothic", 9),
                         bg=BG3, fg=YEL,         # ← 노란색: 편집 가능 강조
                         insertbackground=WHI,
                         relief="flat", width=8,
                         highlightbackground=BDR,
                         highlightthickness=1)
            e.pack(side="left", padx=(4,2), ipady=4)
            e.bind("<FocusIn>",  lambda _, w=e: w.config(highlightbackground=ACCH))
            e.bind("<FocusOut>", lambda _, w=e: w.config(highlightbackground=BDR))
            e.bind("<Return>",   lambda _: self._run_design())
            if unit:
                tk.Label(f, text=unit,
                         font=("Malgun Gothic", 8),
                         bg=BG2, fg=TX3).pack(side="left")

        # 설계 기준
        section("■ 설계 기준")
        f_code = tk.Frame(parent, bg=BG2)
        f_code.pack(fill="x", padx=10, pady=4)
        for code in ["KDS 41 00", "ACI 318"]:
            tk.Radiobutton(f_code, text=code,
                           variable=self.std_code, value=code,
                           font=("Malgun Gothic", 8),
                           bg=BG2, fg=TXT,
                           selectcolor=BG4,
                           activebackground=BG2,
                           activeforeground=WHI).pack(side="left", padx=6)

        # 재료 강도
        section("■ 재료 강도")
        inp("Fck",      self.fck,     "MPa")
        inp("Fy D13이하", self.fy_main, "MPa")
        inp("Fy D16이상", self.fy_high, "MPa")

        # 단면 제원
        section("■ 단면 제원")
        inp("폭 b",    self.b_slab, "mm")
        inp("두께 h",  self.h_slab, "mm")
        inp("피복 c",  self.cover,  "mm")

        # ④ 임의 위치 조회
        section("■ 위치별 설계 조회")
        fq = tk.Frame(parent, bg=BG2)
        fq.pack(fill="x", padx=10, pady=4)
        tk.Label(fq, text="위치 X",
                 font=("Malgun Gothic", 8), bg=BG2, fg=TX2,
                 width=8, anchor="w").pack(side="left")
        eq = tk.Entry(fq, textvariable=self.query_x,
                      font=("Malgun Gothic", 9),
                      bg=BG3, fg=CYN,
                      insertbackground=WHI,
                      relief="flat", width=8,
                      highlightbackground=BDR,
                      highlightthickness=1)
        eq.pack(side="left", padx=(4,2), ipady=4)
        eq.bind("<FocusIn>",  lambda _, w=eq: w.config(highlightbackground=ACCH))
        eq.bind("<FocusOut>", lambda _, w=eq: w.config(highlightbackground=BDR))
        eq.bind("<Return>",   lambda _: self._run_design())
        tk.Label(fq, text="mm",
                 font=("Malgun Gothic", 8), bg=BG2, fg=TX3).pack(side="left")

        # 버튼
        tk.Frame(parent, bg=BG2, height=12).pack()
        tk.Button(parent, text="🔢  설계 계산 실행",
                  command=self._run_design,
                  font=("Malgun Gothic", 10, "bold"),
                  bg=ACC, fg=WHI, relief="flat", cursor="hand2",
                  pady=10).pack(fill="x", padx=10, pady=3)
        tk.Button(parent, text="🖨  결과 출력 (텍스트)",
                  command=self._print_result,
                  font=("Malgun Gothic", 8),
                  bg=BG3, fg=TX2, relief="flat", cursor="hand2",
                  pady=6).pack(fill="x", padx=10, pady=2)

    # ────────────────────────────────────────────────────────
    #  오른쪽: 다이어그램 + 테이블
    # ────────────────────────────────────────────────────────
    def _build_right(self, parent):
        # ① 다이어그램 캔버스
        self.diag_canvas = tk.Canvas(parent, bg=CANV_BG,
                                     height=210, highlightthickness=0)
        self.diag_canvas.pack(fill="x")
        tk.Frame(parent, bg=BDR, height=1).pack(fill="x")

        # ⑤ 결과 테이블 영역 (스크롤)
        result_outer = tk.Frame(parent, bg=BG)
        result_outer.pack(fill="both", expand=True)

        self._result_canvas = tk.Canvas(result_outer, bg=BG,
                                         highlightthickness=0)
        vsb = tk.Scrollbar(result_outer, orient="vertical",
                           command=self._result_canvas.yview)
        vsb.pack(side="right", fill="y")
        self._result_canvas.pack(side="left", fill="both", expand=True)
        self._result_canvas.config(yscrollcommand=vsb.set)

        self._table_frame = tk.Frame(self._result_canvas, bg=BG)
        self._table_win_id = self._result_canvas.create_window(
            (0, 0), window=self._table_frame, anchor="nw")
        self._table_frame.bind("<Configure>", self._on_table_resize)
        self._result_canvas.bind("<Configure>", self._on_canvas_resize)
        self._result_canvas.bind("<MouseWheel>",
            lambda e: self._result_canvas.yview_scroll(
                -1 if e.delta > 0 else 1, "units"))

        # 초기 안내
        tk.Label(self._table_frame,
                 text="  ← 좌측에서 설계 기준 입력 후 [설계 계산 실행]을 누르세요.",
                 font=("Malgun Gothic", 9), bg=BG, fg=TX3).pack(padx=14, pady=20)

        self.diag_canvas.bind("<Configure>", lambda _: self._draw_diagram())

    def _on_table_resize(self, _):
        self._result_canvas.configure(
            scrollregion=self._result_canvas.bbox("all"))

    def _on_canvas_resize(self, e):
        self._result_canvas.itemconfig(self._table_win_id, width=e.width)

    # ════════════════════════════════════════════════════════
    #  ① 다이어그램 (해치 수직선 방식)
    # ════════════════════════════════════════════════════════
    def _draw_diagram(self):
        c = self.diag_canvas
        c.delete("all")
        W = c.winfo_width()  or 800
        H = c.winfo_height() or 210
        c.create_rectangle(0, 0, W, H, fill=CANV_BG, outline="")

        if not self._elem_data:
            return

        x_min = min(e[0] for e in self._elem_data)
        x_max = max(e[1] for e in self._elem_data)
        total = max(x_max - x_min, 1.0)

        PAD_L, PAD_R, PAD_T, PAD_B = 50, 30, 16, 52
        beam_y = H - PAD_B

        # 전체 최대 모멘트
        gmax = max(
            (max(abs(v) for v in e[2]["M"]) if e[2]["M"] else 0)
            for e in self._elem_data
        )
        if gmax < 1e-9: gmax = 1.0
        DIAG_H  = beam_y - PAD_T - 8
        scale   = DIAG_H / gmax

        def wx(x):
            return PAD_L + (x - x_min) / total * (W - PAD_L - PAD_R)

        # 부재선
        c.create_line(wx(x_min), beam_y, wx(x_max), beam_y,
                      fill=LINE_COLOR, width=3)

        # 모멘트 다이어그램 (수직 해칭선)
        for x_start, x_end, res in self._elem_data:
            vals = res["M"]
            xs   = res["x"]
            L    = res["L"]
            if not vals or L < 1e-9: continue

            n_pts = len(vals)
            pts_top = []

            for k, v in enumerate(vals):
                t  = xs[k] / L
                px = wx(x_start + t*(x_end-x_start))
                py = beam_y - v*scale
                pts_top.extend([px, py])

            # 외곽선
            c.create_line(*pts_top, fill=MOM_COLOR, width=2, smooth=True)
            # 시작/끝 수직선
            c.create_line(wx(x_start), beam_y, pts_top[0], pts_top[1],
                          fill=MOM_COLOR, width=1)
            c.create_line(wx(x_end), beam_y, pts_top[-2], pts_top[-1],
                          fill=MOM_COLOR, width=1)

            # 해칭선 (부재 방향 수직 = 화면 수직)
            step = max(1, n_pts // 40)
            for ki in range(0, n_pts, step):
                t  = xs[ki] / L
                px = wx(x_start + t*(x_end-x_start))
                py = beam_y - vals[ki]*scale
                c.create_line(px, beam_y, px, py,
                              fill=MOM_COLOR, width=1)

            # 최대값 레이블
            mi  = max(range(len(vals)), key=lambda i: abs(vals[i]))
            t   = xs[mi] / L
            px  = wx(x_start + t*(x_end-x_start))
            py  = beam_y - vals[mi]*scale
            c.create_text(px, py - 11,
                          text=f"{vals[mi]:.2f} kN·m",
                          fill=MOM_COLOR,
                          font=("Malgun Gothic", 7, "bold"))

        # ② 노드 위치 표시
        node_xs = {}
        for x_start, x_end, _ in self._elem_data:
            node_xs[x_start] = True
            node_xs[x_end]   = True
        for x_val in sorted(node_xs):
            px = wx(x_val)
            c.create_oval(px-5, beam_y-5, px+5, beam_y+5,
                          fill=NODE_COLOR, outline=WHI, width=1)
            # 수직 점선
            c.create_line(px, beam_y-5, px, PAD_T,
                          fill=TX3, width=1, dash=(3,4))
            # ② 위치 치수 (mm)
            c.create_text(px, beam_y + 14,
                          text=f"{x_val:.0f} mm",
                          fill=YEL,
                          font=("Consolas", 7, "bold"))

        # ④ 조회 위치 표시
        qx_str = self.query_x.get().strip()
        if qx_str:
            try:
                qx = float(qx_str)
                if x_min <= qx <= x_max:
                    pxq = wx(qx)
                    c.create_line(pxq, PAD_T, pxq, beam_y,
                                  fill=CYN, width=2, dash=(5,3))
                    c.create_text(pxq, PAD_T - 4,
                                  text=f"X={qx:.0f}",
                                  fill=CYN,
                                  font=("Consolas", 7, "bold"))
            except ValueError:
                pass

        # 범례
        c.create_text(PAD_L, 6, text="Moment Diagram",
                      fill=MOM_COLOR,
                      font=("Malgun Gothic", 8, "bold"),
                      anchor="nw")

    # ════════════════════════════════════════════════════════
    #  설계 계산
    # ════════════════════════════════════════════════════════
    def _run_design(self):
        try:
            fck     = float(self.fck.get())
            fy      = float(self.fy_main.get())
            fy_high = float(self.fy_high.get())
            b       = float(self.b_slab.get())
            h       = float(self.h_slab.get())
            cover   = float(self.cover.get())
        except Exception:
            messagebox.showerror("입력 오류", "숫자를 확인하세요.", parent=self.win)
            return

        d = h - cover - 8
        if d <= 0:
            messagebox.showerror("오류", "유효깊이(d) ≤ 0 입니다.", parent=self.win)
            return

        self._last_fck = fck
        self._last_fy  = fy
        self._last_b   = b
        self._last_d   = d

        # ── 데이터 수집 ─────────────────────────────────
        node_M  = {}   # {nid: M_kNm}
        node_V  = {}   # {nid: V_kN}
        node_x  = {}   # {nid: x_mm}
        span_rows = [] # [(label, x_mm, M, V)]
        max_V   = 0.0

        for eid, res in self.analysis_result.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line: continue
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == line["n2"]), None)
            if not n1 or not n2: continue

            vals  = res["M"]
            vvals = res["V"]
            xs    = res["x"]
            L     = res["L"]
            if not vals: continue

            nid1, nid2 = line["n1"], line["n2"]
            x1, x2 = float(n1["x"]), float(n2["x"])

            def _upd_node(nid, xval, M, V):
                if nid not in node_M or abs(M) > abs(node_M[nid]):
                    node_M[nid] = M
                    node_V[nid] = V
                    node_x[nid] = xval

            _upd_node(nid1, x1, vals[0],  vvals[0]  if vvals else 0)
            _upd_node(nid2, x2, vals[-1], vvals[-1] if vvals else 0)

            # 경간 최대
            mi   = max(range(len(vals)), key=lambda i: abs(vals[i]))
            t    = xs[mi] / L
            x_sp = x1 + t*(x2-x1)
            V_sp = vvals[mi] if vvals else 0
            span_rows.append((f"Span {eid} (경간)", x_sp, vals[mi], V_sp))

            v_max = max(abs(v) for v in vvals) if vvals else 0
            max_V = max(max_V, v_max)

        # ── 테이블 구성 ─────────────────────────────────
        for w in self._table_frame.winfo_children():
            w.destroy()

        def section_label(text):
            tk.Frame(self._table_frame, bg=BG3, height=2).pack(fill="x", pady=(14,0))
            lf = tk.Frame(self._table_frame, bg=BG3)
            lf.pack(fill="x")
            tk.Label(lf, text=text,
                     font=("Malgun Gothic", 9, "bold"),
                     bg=BG3, fg=ACC,
                     padx=12, pady=5).pack(anchor="w")
            tk.Frame(self._table_frame, bg=BDR, height=1).pack(fill="x")

        # 기본 정보
        info = (f"  설계기준 : {self.std_code.get()}   |   "
                f"Fck = {fck:.0f} MPa   |   Fy(D13↓) = {fy:.0f} MPa   "
                f"|   Fy(D16↑) = {fy_high:.0f} MPa   |   "
                f"b = {b:.0f} mm,  h = {h:.0f} mm,  d = {d:.0f} mm  (피복 {cover:.0f}mm)")
        tk.Label(self._table_frame, text=info,
                 font=("Malgun Gothic", 8), bg=BG, fg=TX2,
                 padx=10, pady=6, anchor="w").pack(fill="x")
        tk.Frame(self._table_frame, bg=BDR, height=1).pack(fill="x")

        # ── ⑤ Flexure Reinforcement 테이블 ──────────────
        section_label("■ Flexure Reinforcement")

        hdrs  = ["위치", "X (mm)", "Mu\n(kN·m)", "ρ\n(%)", "Ast\n(mm²)",
                 "D10", "D10+D13", "D13", "D13+D16"]
        cw    = [110, 80, 76, 60, 76, 64, 80, 64, 80]
        rows  = []
        rclrs = []

        rho_min = max(0.25*math.sqrt(fck)/fy, 1.4/fy)
        Ast_min = rho_min * b * d
        sp_min  = _rebar_spacing(Ast_min, fy)

        def make_row(label, x_mm, M_kNm):
            rho, Ast, phi_Mn, ok = _design_flexure(M_kNm, fck, fy, b, d)
            if not ok:
                return [label, f"{x_mm:.0f}", f"{M_kNm:.2f}",
                        "단면부족", "—", "—", "—", "—", "—"], (RED, WHI)
            sp  = _rebar_spacing(Ast, fy)
            return (
                [label, f"{x_mm:.0f}", f"{M_kNm:.2f}",
                 f"{rho:.3f}", f"{Ast:.0f}",
                 sp["D10"], sp["D10+D13"], sp["D13"], sp["D13+D16"]],
                None
            )

        # 지점부
        for nid in sorted(node_x.keys()):
            r, cl = make_row(f"N{nid} (지점)", node_x[nid], node_M[nid])
            rows.append(r); rclrs.append(cl)

        # 경간부
        for label, x_sp, M_sp, _ in span_rows:
            r, cl = make_row(label, x_sp, M_sp)
            rows.append(r); rclrs.append(cl)

        # 최소 철근
        rows.append(["최소 철근", "—", "—",
                     f"{rho_min*100:.3f}", f"{Ast_min:.0f}",
                     sp_min["D10"], sp_min["D10+D13"],
                     sp_min["D13"], sp_min["D13+D16"]])
        rclrs.append((BG3, TX2))

        SimpleTable(self._table_frame,
                    headers=hdrs, rows=rows, col_w=cw,
                    row_colors=rclrs).pack(fill="x", padx=8, pady=4)

        # ── ⑤ Shear Strength 테이블 ─────────────────────
        section_label("■ Check Shear Strength")
        phi_Vc, shear_ok = _design_shear(max_V, fck, b, d)
        judge = "O.K." if shear_ok else "N.G. — 전단 보강 필요"
        cl_j  = (None if shear_ok else (RED, WHI))

        shear_hdrs = ["항목", "값", "판정"]
        shear_cw   = [200, 260, 200]
        shear_rows = [
            ["강도감소계수 Φ", "0.750", ""],
            ["콘크리트 전단강도 ΦVc",
             f"{phi_Vc:.1f} kN", ""],
            ["최대 전단력 Vu",
             f"{max_V:.1f} kN",
             judge],
        ]
        shear_cl = [None, None, cl_j]
        SimpleTable(self._table_frame,
                    headers=shear_hdrs,
                    rows=shear_rows,
                    col_w=shear_cw,
                    row_colors=shear_cl).pack(fill="x", padx=8, pady=4)

        # ── ④ 임의 위치 조회 테이블 ─────────────────────
        qx_str = self.query_x.get().strip()
        if qx_str:
            try:
                qx = float(qx_str)
                self._build_query_table(qx, fck, fy, b, d)
            except ValueError:
                pass

        tk.Frame(self._table_frame, bg=BG, height=20).pack()
        self._draw_diagram()

    # ── ④ 임의 위치 설계값 테이블 ──────────────────────────
    def _build_query_table(self, qx, fck, fy, b, d):
        # 어느 요소에 속하는지 찾기
        target_res = None
        for x_start, x_end, res in self._elem_data:
            if x_start <= qx <= x_end:
                target_res = (x_start, x_end, res)
                break
        if target_res is None:
            return

        x_start, x_end, res = target_res
        M_q = _interp_at(qx, x_start, x_end, res["x"], res["M"])
        V_q = _interp_at(qx, x_start, x_end, res["x"], res["V"])
        D_q = _interp_at(qx, x_start, x_end, res["x"], res["D"])

        rho, Ast, phi_Mn, ok = _design_flexure(M_q, fck, fy, b, d)
        sp = _rebar_spacing(Ast if ok and Ast else 0, fy)

        section_lf = tk.Frame(self._table_frame, bg=BG3)
        section_lf.pack(fill="x", pady=(14, 0))
        tk.Label(section_lf,
                 text=f"■ 위치 X = {qx:.0f} mm 설계값",
                 font=("Malgun Gothic", 9, "bold"),
                 bg=BG3, fg=CYN,
                 padx=12, pady=5).pack(anchor="w")
        tk.Frame(self._table_frame, bg=BDR, height=1).pack(fill="x")

        q_hdrs = ["항목", "값"]
        q_cw   = [200, 460]
        q_rows = [
            ["모멘트  Mu",   f"{M_q:.3f} kN·m"],
            ["전단력  Vu",   f"{V_q:.3f} kN"],
            ["처짐    δ",    f"{D_q:.4f} mm"],
            ["필요 철근비 ρ", f"{rho:.3f} %" if ok else "단면 부족"],
            ["필요 철근량 Ast", f"{Ast:.0f} mm²" if ok else "단면 부족"],
        ]
        if ok and Ast:
            q_rows += [
                ["철근 간격 D10",      sp["D10"]],
                ["철근 간격 D10+D13",  sp["D10+D13"]],
                ["철근 간격 D13",      sp["D13"]],
                ["철근 간격 D13+D16",  sp["D13+D16"]],
            ]
        q_cl = [None]*len(q_rows)
        if not ok:
            q_cl[3] = (RED, WHI)
            q_cl[4] = (RED, WHI)

        SimpleTable(self._table_frame,
                    headers=q_hdrs, rows=q_rows,
                    col_w=q_cw,
                    row_colors=q_cl).pack(fill="x", padx=8, pady=4)

    # ════════════════════════════════════════════════════════
    def _print_result(self):
        pw = tk.Toplevel(self.win)
        pw.title("설계 결과 출력")
        pw.configure(bg=BG2)
        pw.geometry("720x520")
        t = tk.Text(pw, font=("Consolas", 9),
                    bg=BG2, fg=TXT,
                    relief="flat", padx=10, pady=8)
        t.pack(fill="both", expand=True)
        # 테이블에서 텍스트 추출
        lines = []
        for w in self._table_frame.winfo_children():
            if isinstance(w, tk.Label):
                lines.append(w.cget("text"))
            elif isinstance(w, SimpleTable):
                for child in w.winfo_children():
                    row_txt = []
                    for lbl in child.winfo_children():
                        if isinstance(lbl, tk.Label):
                            row_txt.append(lbl.cget("text").strip())
                    if row_txt:
                        lines.append("  ".join(row_txt))
        t.insert("1.0", "\n".join(lines))
        t.config(state="disabled")
        tk.Button(pw, text="닫기", command=pw.destroy,
                  bg=BG3, fg=TX2, relief="flat",
                  font=("Malgun Gothic", 9),
                  padx=14, pady=6).pack(pady=8)
