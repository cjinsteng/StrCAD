"""
design_2d/member_design.py
부재 설계 팝업 — RC 보 설계 (KDS 41 00 기준)

입력:
  analysis_result : {eid: {x, M, V, D, L, ni, nj}}
  nodes           : [{"id","x","y",...}]
  lines           : [{"id","n1","n2"}]
"""

import tkinter as tk
from tkinter import messagebox
import math

from .constants import *


# ════════════════════════════════════════════════════════════
#  RC 설계 유틸
# ════════════════════════════════════════════════════════════
def _design_flexure(Mu_kNm, fck, fy_main, b_mm, d_mm):
    """
    KDS 41 단순 직사각형 단면 휨 설계
    반환: (rho, Ast_mm2, phi_Mn_kNm, OK)
    """
    phi  = 0.85
    Mu_N = abs(Mu_kNm) * 1e6  # kN·m → N·mm
    if Mu_N < 1e-3:
        return 0.0, 0.0, 0.0, True
    # Rn = Mu / (phi·b·d²)
    Rn   = Mu_N / (phi * b_mm * d_mm**2)
    # rho = 0.85*fck/fy * (1 - sqrt(1 - 2Rn/(0.85*fck)))
    under = 1 - 2*Rn / (0.85 * fck)
    if under < 0:
        return None, None, None, False   # 단면 부족
    rho  = 0.85 * fck / fy_main * (1 - math.sqrt(under))
    # 최소 철근비
    rho_min = max(0.25*math.sqrt(fck)/fy_main, 1.4/fy_main)
    rho = max(rho, rho_min)
    Ast  = rho * b_mm * d_mm
    # 설계 모멘트 강도
    a    = Ast * fy_main / (0.85 * fck * b_mm)
    phi_Mn = phi * Ast * fy_main * (d_mm - a/2) / 1e6   # N·mm → kN·m
    return rho * 100, Ast, phi_Mn, True   # rho in %


def _design_shear(Vu_kN, fck, b_mm, d_mm):
    """
    KDS 41 전단 검토 (콘크리트만)
    반환: (phi_Vc, OK)  kN/m
    """
    phi   = 0.75
    Vc    = (1/6) * math.sqrt(fck) * b_mm * d_mm  # N
    phi_Vc = phi * Vc / 1e3                         # kN
    OK    = abs(Vu_kN) <= phi_Vc
    return phi_Vc, OK


def _rebar_spacing(Ast_mm2, fy, rho_pct):
    """
    표준 철근 간격 계산 (슬래브 1m 폭 기준)
    D10=71.3, D13=126.7, D16=198.6 mm²/ea
    반환: dict
    """
    bars = {"D10": 71.3, "D13": 126.7, "D16": 198.6}
    result = {}
    for name, area in bars.items():
        s = area / (Ast_mm2 / 1000) * 1000   # mm 간격
        s = min(300, max(50, round(s / 10) * 10))
        result[name] = f"@{int(s)}"
    # 조합
    area_combo = {"D10+D13": 71.3+126.7, "D13+D16": 126.7+198.6}
    for name, area in area_combo.items():
        s = area / (Ast_mm2 / 1000) * 1000
        s = min(300, max(50, round(s / 10) * 10))
        result[name] = f"@{int(s)}"
    return result


# ════════════════════════════════════════════════════════════
class MemberDesignWindow:
    """부재 설계 팝업 창"""

    def __init__(self, parent, analysis_result, nodes, lines):
        self.parent          = parent
        self.analysis_result = analysis_result
        self.nodes           = nodes
        self.lines           = lines

        self.win = tk.Toplevel(parent)
        self.win.title("부재 설계  —  RC Beam Design (KDS 41)")
        self.win.configure(bg=BG)
        self.win.geometry("1060x780")
        self.win.minsize(900, 680)
        self.win.transient(parent)

        # ── 설계 변수 (기본값) ──────────────────────────
        self.fck      = tk.DoubleVar(value=24.0)    # MPa
        self.fy_main  = tk.DoubleVar(value=400.0)   # MPa  D13이하
        self.fy_high  = tk.DoubleVar(value=600.0)   # MPa  D16이상
        self.b_slab   = tk.DoubleVar(value=1000.0)  # mm  (슬래브 1m)
        self.cover    = tk.DoubleVar(value=40.0)    # mm
        self.h_slab   = tk.DoubleVar(value=200.0)   # mm  전체 두께
        self.std_code = tk.StringVar(value="KDS 41 00")

        self._build()

    # ════════════════════════════════════════════════════════
    def _build(self):
        win = self.win
        # 헤더
        hdr = tk.Frame(win, bg=BG2, height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📐  부재 설계  —  RC Beam Design",
                 font=("Malgun Gothic", 13, "bold"),
                 bg=BG2, fg=WHI).pack(side="left", padx=18, pady=10)
        tk.Button(hdr, text="✕ 닫기", command=self.win.destroy,
                  font=("Malgun Gothic", 9), bg=BG3, fg=TX2,
                  relief="flat", cursor="hand2",
                  padx=10, pady=4).pack(side="right", padx=10, pady=8)
        tk.Frame(win, bg=BDR, height=1).pack(fill="x")

        # 본문: 좌(입력) + 우(결과)
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=0)

        left_panel  = tk.Frame(body, bg=BG2, width=260)
        left_panel.pack(side="left", fill="y")
        left_panel.pack_propagate(False)

        right_panel = tk.Frame(body, bg=BG)
        right_panel.pack(side="left", fill="both", expand=True)

        self._build_input(left_panel)
        self._build_result(right_panel)

    # ── 왼쪽: 설계 기준 입력 ────────────────────────────────
    def _build_input(self, parent):
        def section(text):
            f = tk.Frame(parent, bg=BG3)
            f.pack(fill="x", pady=(10, 0))
            tk.Label(f, text=text, font=("Malgun Gothic", 9, "bold"),
                     bg=BG3, fg=ACC, padx=10, pady=6).pack(anchor="w")
            tk.Frame(parent, bg=BDR, height=1).pack(fill="x")

        def row(parent, label, var, unit=""):
            f = tk.Frame(parent, bg=BG2)
            f.pack(fill="x", padx=12, pady=3)
            tk.Label(f, text=label, font=("Malgun Gothic", 8),
                     bg=BG2, fg=TX2, width=12, anchor="w").pack(side="left")
            e = tk.Entry(f, textvariable=var,
                         font=("Malgun Gothic", 9),
                         bg=BG3, fg=TXT, insertbackground=WHI,
                         relief="flat", width=8,
                         highlightbackground=BDR, highlightthickness=1)
            e.pack(side="left", padx=(4, 2), ipady=3)
            e.bind("<FocusIn>",  lambda _, w=e: w.config(highlightbackground=ACCH))
            e.bind("<FocusOut>", lambda _, w=e: w.config(highlightbackground=BDR))
            if unit:
                tk.Label(f, text=unit, font=("Malgun Gothic", 8),
                         bg=BG2, fg=TX3).pack(side="left")

        # ── 설계 기준 ────────────────────────────────────
        section("■ 설계 기준")
        tk.Frame(parent, bg=BG2, height=4).pack()
        f_code = tk.Frame(parent, bg=BG2)
        f_code.pack(fill="x", padx=12, pady=3)
        tk.Label(f_code, text="설계기준", font=("Malgun Gothic", 8),
                 bg=BG2, fg=TX2, width=12, anchor="w").pack(side="left")
        for code in ["KDS 41 00", "ACI 318"]:
            b = tk.Radiobutton(f_code, text=code,
                               variable=self.std_code, value=code,
                               font=("Malgun Gothic", 8),
                               bg=BG2, fg=TXT,
                               selectcolor=BG3,
                               activebackground=BG2, activeforeground=WHI)
            b.pack(side="left", padx=4)

        # ── 재료 강도 ────────────────────────────────────
        section("■ 재료 강도")
        tk.Frame(parent, bg=BG2, height=4).pack()
        row(parent, "Fck",        self.fck,     "MPa")
        f_fy = tk.Frame(parent, bg=BG2)
        f_fy.pack(fill="x", padx=12, pady=2)
        tk.Label(f_fy, text="Fy",
                 font=("Malgun Gothic", 8), bg=BG2, fg=TX2,
                 width=12, anchor="w").pack(side="left")
        tk.Frame(f_fy, bg=BG2).pack(side="left", expand=True, fill="x")
        sub = tk.Frame(parent, bg=BG2)
        sub.pack(fill="x", padx=24, pady=1)
        tk.Label(sub, text="D13이하", font=("Malgun Gothic", 8),
                 bg=BG2, fg=TX2, width=8, anchor="w").pack(side="left")
        e1 = tk.Entry(sub, textvariable=self.fy_main,
                      font=("Malgun Gothic", 9), bg=BG3, fg=TXT,
                      insertbackground=WHI, relief="flat", width=7,
                      highlightbackground=BDR, highlightthickness=1)
        e1.pack(side="left", padx=(2,2), ipady=3)
        tk.Label(sub, text="MPa", font=("Malgun Gothic", 8),
                 bg=BG2, fg=TX3).pack(side="left")

        sub2 = tk.Frame(parent, bg=BG2)
        sub2.pack(fill="x", padx=24, pady=1)
        tk.Label(sub2, text="D16이상", font=("Malgun Gothic", 8),
                 bg=BG2, fg=TX2, width=8, anchor="w").pack(side="left")
        e2 = tk.Entry(sub2, textvariable=self.fy_high,
                      font=("Malgun Gothic", 9), bg=BG3, fg=TXT,
                      insertbackground=WHI, relief="flat", width=7,
                      highlightbackground=BDR, highlightthickness=1)
        e2.pack(side="left", padx=(2,2), ipady=3)
        tk.Label(sub2, text="MPa", font=("Malgun Gothic", 8),
                 bg=BG2, fg=TX3).pack(side="left")

        # ── 단면 제원 ────────────────────────────────────
        section("■ 단면 제원")
        tk.Frame(parent, bg=BG2, height=4).pack()
        row(parent, "폭 (b)",    self.b_slab, "mm")
        row(parent, "두께 (h)",  self.h_slab, "mm")
        row(parent, "피복 (c)",  self.cover,  "mm")

        # ── 계산 버튼 ────────────────────────────────────
        tk.Frame(parent, bg=BG2, height=16).pack()
        tk.Button(parent, text="🔢  설계 계산 실행",
                  command=self._run_design,
                  font=("Malgun Gothic", 10, "bold"),
                  bg=ACC, fg=WHI, relief="flat", cursor="hand2",
                  pady=10).pack(fill="x", padx=12, pady=4)
        tk.Button(parent, text="🖨  결과 출력",
                  command=self._print_result,
                  font=("Malgun Gothic", 9),
                  bg=BG3, fg=TXT, relief="flat", cursor="hand2",
                  pady=7).pack(fill="x", padx=12, pady=2)

    # ── 오른쪽: 결과 영역 ────────────────────────────────────
    def _build_result(self, parent):
        # 상단: 다이어그램 미리보기 캔버스
        self.diag_canvas = tk.Canvas(parent, bg=CANV_BG,
                                     height=200, highlightthickness=0)
        self.diag_canvas.pack(fill="x", padx=0, pady=0)

        tk.Frame(parent, bg=BDR, height=1).pack(fill="x")

        # 하단: 스크롤 가능한 결과 텍스트
        result_frame = tk.Frame(parent, bg=BG)
        result_frame.pack(fill="both", expand=True)

        self.result_text = tk.Text(
            result_frame,
            font=("Consolas", 9),
            bg=BG2, fg=TXT,
            insertbackground=WHI,
            relief="flat",
            wrap="none",
            state="disabled",
            padx=14, pady=10
        )
        vsb = tk.Scrollbar(result_frame, command=self.result_text.yview)
        vsb.pack(side="right", fill="y")
        self.result_text.pack(fill="both", expand=True)
        self.result_text.config(yscrollcommand=vsb.set)

        # 태그 스타일
        self.result_text.tag_config("header",
            font=("Malgun Gothic", 10, "bold"), foreground=ACC)
        self.result_text.tag_config("sub",
            font=("Malgun Gothic", 9, "bold"), foreground=CYN)
        self.result_text.tag_config("ok",
            font=("Consolas", 9, "bold"), foreground="#4ade80")
        self.result_text.tag_config("ng",
            font=("Consolas", 9, "bold"), foreground=RED)
        self.result_text.tag_config("val",
            font=("Consolas", 9), foreground=YEL)
        self.result_text.tag_config("dim",
            font=("Consolas", 9), foreground=TX2)
        self.result_text.tag_config("sep",
            font=("Consolas", 9), foreground=TX3)

        # 초기 안내
        self._set_text([("  ← 왼쪽에서 설계 기준 입력 후 [설계 계산 실행]을 누르세요.\n", "dim")])
        # 초기 다이어그램 그리기
        self.diag_canvas.bind("<Configure>", lambda _: self._draw_preview())

    # ════════════════════════════════════════════════════════
    #  다이어그램 미리보기
    # ════════════════════════════════════════════════════════
    def _draw_preview(self):
        """모멘트 다이어그램 미리보기 (부재 수평 배치)"""
        c = self.diag_canvas
        c.delete("all")
        W = c.winfo_width() or 700
        H = c.winfo_height() or 200
        c.create_rectangle(0, 0, W, H, fill=CANV_BG, outline="")

        if not self.analysis_result:
            return

        # 전체 X 범위
        all_x = []
        for res in self.analysis_result.values():
            all_x.extend(res["x"])
        if not all_x:
            return

        # 각 요소의 절대 x 좌표 계산
        elem_data = []
        for eid, res in self.analysis_result.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line:
                continue
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == line["n2"]), None)
            if not n1 or not n2:
                continue
            x_start = float(n1["x"])
            x_end   = float(n2["x"])
            elem_data.append((x_start, x_end, res))

        if not elem_data:
            return

        x_min = min(e[0] for e in elem_data)
        x_max = max(e[1] for e in elem_data)
        total = x_max - x_min or 1.0

        pad_l, pad_r, pad_t, pad_b = 40, 20, 20, 50
        beam_y = H // 2 + 20

        # 최대 모멘트값
        global_max = max(
            max(abs(v) for v in e[2]["M"]) if e[2]["M"] else 0
            for e in elem_data
        )
        if global_max < 1e-9:
            global_max = 1.0
        DIAG_H = (beam_y - pad_t - 10)
        scale  = DIAG_H / global_max

        def wx(x):
            return pad_l + (x - x_min) / total * (W - pad_l - pad_r)

        # 부재선
        c.create_line(wx(x_min), beam_y, wx(x_max), beam_y,
                      fill=LINE_COLOR, width=3)

        # 모멘트 다이어그램
        for x_start, x_end, res in elem_data:
            vals = res["M"]
            xs   = res["x"]
            L    = res["L"]
            if not vals or L < 1e-9:
                continue
            pts_top  = []
            pts_base = []
            for k, v in enumerate(vals):
                t  = xs[k] / L
                px = wx(x_start + t * (x_end - x_start))
                py = beam_y - v * scale
                pts_top.extend([px, py])
                pts_base.extend([px, beam_y])

            poly = pts_top + list(reversed(pts_base))
            if len(poly) >= 6:
                c.create_polygon(poly, fill=MOM_COLOR,
                                 stipple="gray50", outline="")
                c.create_line(*pts_top, fill=MOM_COLOR, width=2, smooth=True)

            # 최대값 표시
            mi  = max(range(len(vals)), key=lambda i: abs(vals[i]))
            t   = xs[mi] / L
            px  = wx(x_start + t * (x_end - x_start))
            py  = beam_y - vals[mi] * scale
            c.create_text(px, py - 10,
                          text=f"{vals[mi]:.2f} kN·m",
                          fill=MOM_COLOR, font=("Malgun Gothic", 7, "bold"))

        # 노드 표시
        node_xs = set()
        for x_start, x_end, _ in elem_data:
            node_xs.add(x_start)
            node_xs.add(x_end)
        for nx_val in node_xs:
            px = wx(nx_val)
            c.create_oval(px-4, beam_y-4, px+4, beam_y+4,
                          fill=NODE_COLOR, outline=WHI, width=1)
            c.create_text(px, beam_y + 16,
                          text=f"{nx_val:.0f}",
                          fill=TX2, font=("Consolas", 7))

        # 범례
        c.create_text(pad_l, pad_t,
                      text="Moment Diagram",
                      fill=MOM_COLOR, font=("Malgun Gothic", 8, "bold"),
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

        d = h - cover - 8   # 유효깊이 (D16 반경 ≈8mm 가정)
        if d <= 0:
            messagebox.showerror("오류", "유효깊이(d)가 0 이하입니다.", parent=self.win)
            return

        # 최대/최소 M, 최대 V 수집
        node_M  = {}   # {nid: M_kNm}  지점부 모멘트
        span_Ms = []   # [(eid, M_max_span)]  경간 최대 모멘트
        max_V   = 0.0

        # 전체 요소 루프
        for eid, res in self.analysis_result.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line:
                continue
            n1_id = line["n1"]
            n2_id = line["n2"]
            vals  = res["M"]
            vvals = res["V"]
            xs    = res["x"]
            L     = res["L"]
            if not vals:
                continue

            # 지점부 (양 끝)
            M_n1 = vals[0]
            M_n2 = vals[-1]
            node_M[n1_id] = M_n1 if abs(M_n1) > abs(node_M.get(n1_id, 0)) else node_M.get(n1_id, 0)
            node_M[n2_id] = M_n2 if abs(M_n2) > abs(node_M.get(n2_id, 0)) else node_M.get(n2_id, 0)

            # 경간 최대
            mid_s = len(vals) // 4
            mid_e = len(vals) * 3 // 4
            span_max = max(vals[mid_s:mid_e], key=abs, default=0)
            span_Ms.append((eid, span_max))

            # 전단
            v_max = max(abs(v) for v in vvals) if vvals else 0
            max_V = max(max_V, v_max)

        # ── 결과 텍스트 구성 ────────────────────────────
        lines_out = []
        A = lines_out.append

        def sep(ch="─", n=70):
            A((ch * n + "\n", "sep"))

        A(("  RC 보 설계 결과  (KDS 41 00)\n", "header"))
        sep()
        A((f"  설계기준 : {self.std_code.get()}\n", "dim"))
        A((f"  Fck = {fck:.0f} MPa  |  Fy(D13↓) = {fy:.0f} MPa  |  Fy(D16↑) = {fy_high:.0f} MPa\n", "dim"))
        A((f"  단면: b = {b:.0f} mm,  h = {h:.0f} mm,  d = {d:.0f} mm (피복 {cover:.0f}mm)\n", "dim"))
        sep()

        # ── 휨 설계 ──────────────────────────────────────
        A(("\n  ┌─ Flexure Reinforcement ─────────────────────────────────────\n", "sub"))
        header = (
            f"  {'위치':<12}  {'Mu':>10}  {'ρ(%)':>7}  {'Ast':>9}"
            f"  {'D10':>6}  {'D10+D13':>8}  {'D13':>6}  {'D13+D16':>8}\n"
        )
        A((header, "dim"))
        A(("  " + "·"*68 + "\n", "sep"))

        def design_row(label, M_kNm):
            rho, Ast, phi_Mn, ok = _design_flexure(M_kNm, fck, fy, b, d)
            if not ok:
                A((f"  {label:<12}  {M_kNm:>8.2f}  단면 부족! 두께를 늘리세요.\n", "ng"))
                return
            sp = _rebar_spacing(Ast, fy, rho)
            rho_str = f"{rho:.3f}" if rho is not None else "—"
            Ast_str = f"{Ast:.0f}" if Ast is not None else "—"
            A((f"  {label:<12}  {M_kNm:>8.2f}  {rho_str:>7}  {Ast_str:>7} mm²"
               f"  {sp.get('D10','—'):>6}  {sp.get('D10+D13','—'):>8}"
               f"  {sp.get('D13','—'):>6}  {sp.get('D13+D16','—'):>8}\n", "val"))

        # 지점부
        nodes_sorted = sorted(node_M.keys())
        for nid in nodes_sorted:
            label = f"N{nid} (지점)"
            design_row(label, node_M[nid])

        # 경간부
        for eid, M_span in span_Ms:
            label = f"Span{eid} (경간)"
            design_row(label, M_span)

        # 최소 철근
        rho_min = max(0.25*math.sqrt(fck)/fy, 1.4/fy)
        Ast_min = rho_min * b * d
        sp_min  = _rebar_spacing(Ast_min, fy, rho_min*100)
        A(("\n", "dim"))
        A((f"  {'최소 철근':<12}  {'—':>10}  {rho_min*100:>7.3f}  {Ast_min:>7.0f} mm²"
           f"  {sp_min.get('D10','—'):>6}  {sp_min.get('D10+D13','—'):>8}"
           f"  {sp_min.get('D13','—'):>6}  {sp_min.get('D13+D16','—'):>8}\n", "dim"))
        A(("  └" + "─"*68 + "\n", "sep"))

        # ── 전단 검토 ────────────────────────────────────
        A(("\n  ┌─ Check Shear Strength ──────────────────────────────────────\n", "sub"))
        phi_Vc, shear_ok = _design_shear(max_V, fck, b, d)
        phi_tag = "ok" if shear_ok else "ng"
        A((f"  Strength Reduction Factor   Φ = 0.750\n", "dim"))
        A((f"  Vu = {max_V:6.1f} kN   {'<' if shear_ok else '>'}"
           f"   ΦVc = {phi_Vc:6.1f} kN"
           f"   →  {'O.K.' if shear_ok else 'N.G. — 전단 보강 필요'}\n", phi_tag))
        A(("  └" + "─"*68 + "\n", "sep"))

        self._set_text(lines_out)
        self._draw_preview()

    # ════════════════════════════════════════════════════════
    def _set_text(self, tagged_lines):
        t = self.result_text
        t.config(state="normal")
        t.delete("1.0", "end")
        for text, tag in tagged_lines:
            t.insert("end", text, tag)
        t.config(state="disabled")

    def _print_result(self):
        """결과 텍스트를 별도 창으로 출력 (복사 가능)"""
        pw = tk.Toplevel(self.win)
        pw.title("설계 결과 출력")
        pw.configure(bg=BG2)
        pw.geometry("700x500")
        t = tk.Text(pw, font=("Consolas", 9), bg=BG2, fg=TXT,
                    relief="flat", padx=10, pady=8)
        t.pack(fill="both", expand=True)
        content = self.result_text.get("1.0", "end")
        t.insert("1.0", content)
        t.config(state="disabled")
        tk.Button(pw, text="닫기", command=pw.destroy,
                  bg=BG3, fg=TX2, relief="flat",
                  font=("Malgun Gothic", 9),
                  padx=14, pady=6).pack(pady=8)
