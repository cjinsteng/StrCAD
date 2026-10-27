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


# 철근 규격 데이터
REBAR_AREA = {
    "D10": 71.3,  "D13": 126.7, "D16": 198.6,
    "D19": 286.5, "D22": 387.1, "D25": 506.7,
    "D29": 642.4, "D32": 794.2, "D35": 956.6,
    "D10+D13": 71.3+126.7,   "D13+D16": 126.7+198.6,
    "D16+D19": 198.6+286.5,  "D19+D22": 286.5+387.1,
    "D22+D25": 387.1+506.7,
}

def _rebar_spacing(Ast_mm2, fy, selected=None):
    """
    철근 간격 → dict
    selected : list of keys to compute (None = 기본 4종)
    """
    keys = [k for k in (selected or ["D10","D10+D13","D13","D13+D16"])
            if k and k != "—"]
    if Ast_mm2 <= 0:
        return {k: "@300" for k in keys}
    out = {}
    for k in keys:
        a = REBAR_AREA.get(k, 71.3)
        s = a / (Ast_mm2/1000) * 1000
        s = min(300, max(50, round(s/10)*10))
        out[k] = f"@{int(s)}"
    return out


# ════════════════════════════════════════════════════════════
#  처짐 검토 (KDS 14 20 30 / ACI 318 Table 24.2)
# ════════════════════════════════════════════════════════════
def _check_deflection(fck, fy, b_mm, h_mm, d_mm, cover_mm,
                      M_neg_kNm, M_pos_kNm, L_mm,
                      wD_kNm=0.0, wL_kNm=0.0, xi=2.0):
    """
    균열모멘트 → 유효단면2차모멘트 → 탄성처짐 → 장기처짐 계산
    반환: dict (모든 중간값 포함)
    
    M_neg_kNm : 지점부 최대 휨모멘트 (kN·m)
    M_pos_kNm : 경간부 최대 휨모멘트 (kN·m)
    L_mm      : 경간 (mm)
    wD/wL     : 등분포 고정/활하중 (kN/m) — 처짐 분리용 (없으면 모멘트에서 역산)
    xi        : 장기처짐 계수 (KDS 기본 2.0 / 60개월)
    """
    import math
    Ec    = 8500 * (fck + 4) ** (1/3)   # MPa  KDS 콘크리트탄성계수
    fr    = 0.63 * math.sqrt(fck)        # 파괴계수 MPa
    yt    = h_mm / 2.0                   # 중립축까지 거리 (gross)
    Ig    = b_mm * h_mm**3 / 12.0       # mm⁴  총단면2차모멘트

    # Mcr (균열모멘트)
    Mcr   = fr * Ig / yt / 1e6           # kN·m

    # 철근량 추정 (최소 철근비 사용)
    rho_min = max(0.25*math.sqrt(fck)/fy, 1.4/fy)
    # 실제 설계 Ast 는 호출자에서 제공하지 않으므로 최소로 추정
    # (보수적 Ie: 균열이 많이 진행된 경우)
    As    = rho_min * b_mm * d_mm
    n     = max(6, round(200000 / Ec))  # 탄성계수비

    # 균열단면2차모멘트 Icr
    # NA 위치: b*kd²/2 = n*As*(d - kd)
    # → b*kd² + 2n*As*kd - 2n*As*d = 0
    _a  = b_mm
    _b  = 2 * n * As
    _c  = -2 * n * As * d_mm
    kd  = (-_b + math.sqrt(_b**2 - 4*_a*_c)) / (2*_a)
    kd  = max(1.0, min(kd, d_mm))
    Icr = b_mm * kd**3 / 3.0 + n * As * (d_mm - kd)**2

    def Ie(Ma_kNm):
        """유효단면2차모멘트 (Branson)"""
        if Ma_kNm < 1e-6:
            return Ig
        ratio = Mcr / Ma_kNm
        ratio = min(ratio, 1.0)
        return ratio**3 * Ig + (1 - ratio**3) * Icr

    # 지점부 / 경간부 Ie
    Ie_neg = Ie(abs(M_neg_kNm))
    Ie_pos = Ie(abs(M_pos_kNm))
    # 유효Ie (양단 고정 근사: 평균)
    Ie_eff = (Ie_neg + Ie_pos) / 2.0
    Ie_eff = max(Icr, min(Ig, Ie_eff))

    # 등분포하중 역산 (w = 8M/L²) — 고정하중/활하중 미제공 시
    M_tot = max(abs(M_pos_kNm), abs(M_neg_kNm), 1e-6)
    if wD_kNm <= 0 and wL_kNm <= 0:
        wD_kNm = M_tot * 0.7   # 고정하중 70% 가정
        wL_kNm = M_tot * 0.3   # 활하중 30% 가정
    w_tot = wD_kNm + wL_kNm

    # 탄성처짐 δ = 5wL⁴/(384EI)
    def elastic_defl(w_kNm_per_m, Ie_mm4):
        w = w_kNm_per_m * 1e3 / 1e3   # kN/m → N/mm
        return 5 * w * L_mm**4 / (384 * Ec * Ie_mm4)  # mm

    d_D   = elastic_defl(wD_kNm,       Ie_eff)
    d_L   = elastic_defl(wL_kNm,       Ie_eff)
    d_tot = elastic_defl(w_tot,        Ie_eff)
    d_sus = elastic_defl(wD_kNm,       Ie_eff)   # 지속하중 = 고정하중

    # 장기처짐
    rho_prime = 0.0  # 압축철근 없는 경우
    lam       = xi / (1 + 50 * rho_prime)
    d_lt      = lam * d_sus   # 장기추가처짐

    # 허용처짐 검토
    allow_L360 = L_mm / 360   # mm  (활하중 단기)
    allow_L480 = L_mm / 480   # mm  (장기 + 활하중)

    short_ok = d_L    <= allow_L360
    long_ok  = (d_lt + d_L) <= allow_L480

    return {
        "Ec":  Ec,   "fr": fr,   "Ig": Ig,   "Icr": Icr,
        "Mcr": Mcr,  "n":  n,
        "Ie_neg": Ie_neg, "Ie_pos": Ie_pos, "Ie_eff": Ie_eff,
        "xi":  xi,   "lam": lam,
        "wD":  wD_kNm, "wL": wL_kNm,
        "d_D": d_D,  "d_L": d_L, "d_tot": d_tot, "d_sus": d_sus,
        "d_lt": d_lt,
        "d_short": d_L,        "allow_L360": allow_L360, "short_ok": short_ok,
        "d_long":  d_lt + d_L, "allow_L480": allow_L480, "long_ok":  long_ok,
    }


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

    def bind_scroll(self, fn):
        """테이블 위 마우스 휠 이벤트를 상위 스크롤 함수로 전파"""
        self.bind("<MouseWheel>", fn)
        for child in self.winfo_children():
            child.bind("<MouseWheel>", fn)
            for gc in child.winfo_children():
                gc.bind("<MouseWheel>", fn)


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

        # 철근 직경 선택 (슬롯 4개, OptionMenu)
        SINGLE_REBARS = ["D10","D13","D16","D19","D22","D25","D29","D32","D35"]
        self._single_rebars = SINGLE_REBARS
        self._NEXT_REBAR    = {
            "D10":"D13","D13":"D16","D16":"D19","D19":"D22",
            "D22":"D25","D25":"D29","D29":"D32","D32":"D35","D35":"D35"
        }
        # 슬롯1,2: 단일 직경  슬롯3: 슬롯1 다음 단계  슬롯4: 슬롯1+슬롯2 조합
        self._slot1 = tk.StringVar(value="D10")
        self._slot2 = tk.StringVar(value="D16")
        self._slot3_label = tk.StringVar(value="D13")   # 자동
        self._slot4_label = tk.StringVar(value="D10+D16")  # 자동
        # 슬롯1,2 변경 시 자동 갱신
        def _update_auto_slots(*_):
            s1 = self._slot1.get()
            s2 = self._slot2.get()
            # 슬롯3: 슬롯1 + 다음 규격 조합  (예: D10+D13)
            next1 = self._NEXT_REBAR.get(s1, s1)
            self._slot3_label.set(
                f"{s1}+{next1}" if s1 != next1 else s1)
            # 슬롯4: 슬롯1 + 슬롯2 조합
            self._slot4_label.set(
                f"{s1}+{s2}" if s1 != s2 else s1)
        self._slot1.trace_add("write", _update_auto_slots)
        self._slot2.trace_add("write", _update_auto_slots)
        _update_auto_slots()

        # 내부 캐시
        self._elem_data  = []   # [(x_start, x_end, res), ...]
        self._last_fck   = None
        self._last_fy    = None
        self._last_b     = None
        self._last_d     = None
        # 다이어그램 표시 타입 (M/V/D)
        self._diag_type  = tk.StringVar(value="M")

        self.win = tk.Toplevel(parent)
        self.win.title("부재 설계  —  RC Beam Design (KDS 41)")
        self.win.configure(bg=BG)
        self.win.geometry("1120x820")
        self.win.minsize(960, 700)
        # transient 제거 → 최소화/최대화 버튼 활성화
        # self.win.transient(parent)
        self.win.resizable(True, True)

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
        tk.Button(hdr, text="💾 저장",
                  command=self._save_result,
                  font=("Malgun Gothic", 9, "bold"),
                  bg=GRN, fg=WHI,
                  relief="flat", cursor="hand2",
                  padx=12, pady=4).pack(side="right", padx=4, pady=8)
        tk.Frame(win, bg=BDR, height=1).pack(fill="x")

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True)

        # 좌측 입력 패널 (스크롤 가능)
        lp_outer = tk.Frame(body, bg=BG2, width=272)
        lp_outer.pack(side="left", fill="y"); lp_outer.pack_propagate(False)
        lp_canvas = tk.Canvas(lp_outer, bg=BG2, width=270,
                              highlightthickness=0)
        lp_vsb = tk.Scrollbar(lp_outer, orient="vertical",
                              command=lp_canvas.yview)
        lp_vsb.pack(side="right", fill="y")
        lp_canvas.pack(side="left", fill="both", expand=True)
        lp = tk.Frame(lp_canvas, bg=BG2, width=270)
        lp_win = lp_canvas.create_window((0,0), window=lp, anchor="nw")
        lp.bind("<Configure>", lambda _: lp_canvas.configure(
            scrollregion=lp_canvas.bbox("all")))
        lp_canvas.config(yscrollcommand=lp_vsb.set)
        lp_canvas.bind("<MouseWheel>",
            lambda e: lp_canvas.yview_scroll(
                -1 if e.delta > 0 else 1, "units"))
        lp.bind("<MouseWheel>",
            lambda e: lp_canvas.yview_scroll(
                -1 if e.delta > 0 else 1, "units"))
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

        # 철근 직경 선택 섹션
        section("■ 표시 철근 직경 (4개 선택)")
        tk.Label(parent, text="  슬롯1,2: 단일직경 선택  슬롯3,4: 자동",
                 font=("Malgun Gothic", 7), bg=BG2, fg=TX3).pack(anchor="w", padx=12)

        def slot_om(sf_parent, label_text, var, choices, auto=False):
            sf = tk.Frame(sf_parent, bg=BG2)
            sf.pack(fill="x", padx=10, pady=2)
            tk.Label(sf, text=label_text,
                     font=("Malgun Gothic", 8), bg=BG2, fg=TX2,
                     width=6, anchor="w").pack(side="left")
            if auto:
                # 자동 계산 — 편집 불가 레이블
                tk.Label(sf, textvariable=var,
                         font=("Malgun Gothic", 9, "bold"),
                         bg=BG4, fg=CYN,
                         width=10, anchor="center",
                         relief="flat", padx=4).pack(side="left", padx=(4,0), ipady=4)
                tk.Label(sf, text="(자동)",
                         font=("Malgun Gothic", 7), bg=BG2, fg=TX3).pack(side="left", padx=2)
            else:
                om = tk.OptionMenu(sf, var, *choices)
                om.config(font=("Malgun Gothic", 9, "bold"),
                          bg=BG3, fg=YEL,
                          activebackground=BG4, activeforeground=WHI,
                          highlightthickness=0, relief="flat",
                          padx=6, pady=4, width=8,
                          indicatoron=False)
                om["menu"].config(bg=BG3, fg=TXT,
                                  font=("Malgun Gothic", 8),
                                  activebackground=ACCH, activeforeground=WHI)
                om.pack(side="left", padx=(4,0))

        slot_om(parent, "슬롯 1", self._slot1, self._single_rebars)
        slot_om(parent, "슬롯 2", self._slot2, self._single_rebars)
        slot_om(parent, "슬롯 3", self._slot3_label, [], auto=True)
        slot_om(parent, "슬롯 4", self._slot4_label, [], auto=True)

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
        # 상단 다이어그램(40%) + 하단 테이블(60%) 분할 PanedWindow
        paned = tk.PanedWindow(parent, orient="vertical",
                               bg=BG, sashwidth=5, sashrelief="flat",
                               sashpad=2, opaqueresize=True)
        paned.pack(fill="both", expand=True)

        # ── 상단: 다이어그램 캔버스 + 타입 전환 버튼 ──
        diag_frame = tk.Frame(paned, bg=CANV_BG)
        paned.add(diag_frame, minsize=140, stretch="always")

        # 다이어그램 타입 전환 버튼 (Moment / Shear / Deflection)
        diag_toolbar = tk.Frame(diag_frame, bg=BG3, height=32)
        diag_toolbar.pack(fill="x", side="top"); diag_toolbar.pack_propagate(False)
        tk.Label(diag_toolbar, text="Diagram:",
                 font=("Malgun Gothic", 8), bg=BG3, fg=TX2).pack(side="left", padx=8)

        DIAG_BTNS = [
            ("Moment",    "M", MOM_COLOR),
            ("Shear",     "V", SHEAR_COLOR),
            ("Deflection","D", DEFL_COLOR),
        ]
        self._diag_btns = {}
        for label, code, color in DIAG_BTNS:
            b = tk.Button(diag_toolbar, text=label,
                          font=("Malgun Gothic", 8, "bold"),
                          bg=BG4, fg=color,
                          relief="flat", cursor="hand2",
                          padx=10, pady=3,
                          command=lambda c=code: self._set_diag_type(c))
            b.pack(side="left", padx=2, pady=4)
            b.bind("<Enter>", lambda _, w=b: w.config(bg=BG5))
            b.bind("<Leave>", lambda _, w=b, bg_=BG4: w.config(
                bg=b._active_bg if hasattr(b,"_active_bg") else BG4))
            self._diag_btns[code] = b
        # 초기 활성 버튼
        self._diag_btns["M"].config(bg=ACC)
        self._diag_btns["M"]._active_bg = ACC

        # 줌 안내 레이블
        tk.Label(diag_toolbar,
                 text="휠:확대  드래그:이동  더블클릭:초기화",
                 font=("Malgun Gothic", 7), bg=BG3, fg=TX3
                 ).pack(side="right", padx=10)

        self.diag_canvas = tk.Canvas(diag_frame, bg=CANV_BG,
                                     highlightthickness=0)
        self.diag_canvas.pack(fill="both", expand=True)

        # ── 하단: 결과 테이블 영역 (스크롤) ──
        result_outer = tk.Frame(paned, bg=BG)
        paned.add(result_outer, minsize=120, stretch="always")

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

        # 결과 테이블 마우스 휠 스크롤 — 테이블 자식 위젯에도 전파
        def _tbl_scroll(e):
            self._result_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        self._result_canvas.bind("<MouseWheel>", _tbl_scroll)
        self._table_frame.bind("<MouseWheel>", _tbl_scroll)
        # 동적 생성 자식들에게도 휠 전파
        self._tbl_scroll_fn = _tbl_scroll

        # 초기 안내
        tk.Label(self._table_frame,
                 text="  ← 좌측에서 설계 기준 입력 후 [설계 계산 실행]을 누르세요.",
                 font=("Malgun Gothic", 9), bg=BG, fg=TX3).pack(padx=14, pady=20)

        # 다이어그램 줌(휠)/패닝(드래그) 초기화
        self._diag_scale      = tk.DoubleVar(value=1.0)
        self._diag_pan_x      = 0.0
        self._diag_pan_origin = None
        self.diag_canvas.bind("<Configure>",      lambda _: self._draw_diagram())
        self.diag_canvas.bind("<MouseWheel>",     self._diag_wheel)
        self.diag_canvas.bind("<Button-4>",       self._diag_wheel)
        self.diag_canvas.bind("<Button-5>",       self._diag_wheel)
        self.diag_canvas.bind("<ButtonPress-1>",  self._diag_pan_start)
        self.diag_canvas.bind("<B1-Motion>",      self._diag_pan_move)
        # 더블클릭으로 줌/패닝 초기화
        self.diag_canvas.bind("<Double-Button-1>",
            lambda _: [self._diag_scale.set(1.0),
                       setattr(self,"_diag_pan_x",0.0),
                       self._draw_diagram()])

    def _on_table_resize(self, _):
        self._result_canvas.configure(
            scrollregion=self._result_canvas.bbox("all"))

    def _on_canvas_resize(self, e):
        self._result_canvas.itemconfig(self._table_win_id, width=e.width)

    # ════════════════════════════════════════════════════════
    def _set_diag_type(self, code):
        """Moment / Shear / Deflection 전환"""
        COLORS = {"M": MOM_COLOR, "V": SHEAR_COLOR, "D": DEFL_COLOR}
        self._diag_type.set(code)
        for c, b in self._diag_btns.items():
            if c == code:
                b.config(bg=ACC)
                b._active_bg = ACC
            else:
                b.config(bg=BG4)
                b._active_bg = BG4
        self._draw_diagram()

    # ════════════════════════════════════════════════════════
    #  다이어그램 (해치 수직선 방식) — M / V / D 전환
    # ════════════════════════════════════════════════════════
    def _draw_diagram(self):
        c = self.diag_canvas
        c.delete("all")
        W = c.winfo_width()  or 800
        H = c.winfo_height() or 250
        c.create_rectangle(0, 0, W, H, fill=CANV_BG, outline="")

        if not self._elem_data:
            return

        x_min = min(e[0] for e in self._elem_data)
        x_max = max(e[1] for e in self._elem_data)
        total = max(x_max - x_min, 1.0)

        PAD_L, PAD_R = 52, 32
        NODE_LBL_H = 26   # 노드 라벨 + 부재선 공간 (고정)
        TITLE_H    = 20   # 범례 텍스트 공간 (고정)
        VAL_LBL_H  = 16   # 최대값 레이블 공간 (고정)

        # 줌/패닝 적용
        zoom    = getattr(self, '_diag_scale', None)
        zoom    = zoom.get() if zoom else 1.0
        pan_x   = getattr(self, '_diag_pan_x', 0.0)
        draw_w  = (W - PAD_L - PAD_R) * zoom

        # 표시 타입 선택
        dtype  = getattr(self._diag_type, "get", lambda: "M")()
        COLORS = {"M": MOM_COLOR, "V": SHEAR_COLOR, "D": DEFL_COLOR}
        UNITS  = {"M": "kN·m",    "V": "kN",        "D": "mm"}
        color  = COLORS.get(dtype, MOM_COLOR)
        unit   = UNITS.get(dtype,  "kN·m")

        # 전체 최대(양수) / 최소(음수) 분리 수집
        all_vals = []
        for e in self._elem_data:
            all_vals.extend(e[2].get(dtype, []))
        gmax_pos = max((v for v in all_vals if v >= 0), default=0.0)
        gmax_neg = min((v for v in all_vals if v <  0), default=0.0)
        gmax     = max(abs(gmax_pos), abs(gmax_neg), 1e-9)

        # beam_y: 최대·최소값이 캔버스 경계를 벗어나지 않도록 자동 배치
        avail_H = H - TITLE_H - NODE_LBL_H
        if gmax_pos > 1e-9 and abs(gmax_neg) > 1e-9:
            # 양음 혼재: 비율에 따라 beam_y 위치
            ratio_pos = gmax_pos / gmax
            pos_px    = int(avail_H * ratio_pos * 0.88)
            beam_y    = TITLE_H + VAL_LBL_H + pos_px
        elif gmax_pos > 1e-9:
            # 양수만: 부재선을 하단
            beam_y = H - NODE_LBL_H
        else:
            # 음수만 (처짐 등): 부재선을 상단
            beam_y = TITLE_H + VAL_LBL_H

        DIAG_H_pos = max(beam_y - TITLE_H - VAL_LBL_H, 1)
        DIAG_H_neg = max(H - NODE_LBL_H - beam_y, 1)
        DIAG_H     = max(DIAG_H_pos, DIAG_H_neg, 1)
        scale      = DIAG_H / gmax

        def wx(x):
            return PAD_L + pan_x + (x - x_min) / total * draw_w

        # 부재선
        c.create_line(wx(x_min), beam_y, wx(x_max), beam_y,
                      fill=LINE_COLOR, width=3)

        # 다이어그램 (수직 해칭선)
        for x_start, x_end, res in self._elem_data:
            vals = res.get(dtype, [])
            xs   = res["x"]
            L    = res["L"]
            if not vals or L < 1e-9: continue

            n_pts   = len(vals)
            pts_top = []

            for k, v in enumerate(vals):
                t  = xs[k] / L
                px = wx(x_start + t*(x_end-x_start))
                py = beam_y - v*scale
                pts_top.extend([px, py])

            # 외곽선
            c.create_line(*pts_top, fill=color, width=2, smooth=True)
            # 시작/끝 수직선
            c.create_line(wx(x_start), beam_y, pts_top[0], pts_top[1],
                          fill=color, width=1)
            c.create_line(wx(x_end), beam_y, pts_top[-2], pts_top[-1],
                          fill=color, width=1)

            # 해칭선
            step = max(1, n_pts // 40)
            for ki in range(0, n_pts, step):
                t  = xs[ki] / L
                px = wx(x_start + t*(x_end-x_start))
                py = beam_y - vals[ki]*scale
                c.create_line(px, beam_y, px, py,
                              fill=color, width=1)

            # 최대값 레이블
            mi  = max(range(len(vals)), key=lambda i: abs(vals[i]))
            t   = xs[mi] / L
            px  = wx(x_start + t*(x_end-x_start))
            py  = beam_y - vals[mi]*scale
            c.create_text(px, py - 11,
                          text=f"{vals[mi]:.2f} {unit}",
                          fill=color,
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
        TITLES = {"M": "Moment Diagram", "V": "Shear Diagram",
                  "D": "Deflection Diagram"}
        c.create_text(PAD_L, 6, text=TITLES.get(dtype, "Moment Diagram"),
                      fill=color,
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

        # ── ⑤ Flexure Reinforcement 테이블 (동적 철근 컬럼) ──
        section_label("■ Flexure Reinforcement")

        # 슬롯 4개에서 철근 직경 수집 (중복 제거)
        seen = set(); sel_rebars = []
        for sv in [self._slot1, self._slot2,
                   self._slot3_label, self._slot4_label]:
            k = sv.get()
            if k and k not in seen:
                seen.add(k); sel_rebars.append(k)
        if not sel_rebars:
            sel_rebars = ["D10", "D13"]

        rho_min = max(0.25*math.sqrt(fck)/fy, 1.4/fy)
        Ast_min = rho_min * b * d
        sp_min  = _rebar_spacing(Ast_min, fy, sel_rebars)

        # 컬럼 너비: 고정 + 철근별
        fixed_cw  = [116, 76, 76, 60, 76]
        rebar_cw  = [72] * len(sel_rebars)
        cw        = fixed_cw + rebar_cw
        hdrs      = ["위치", "X (mm)", "Mu\n(kN·m)", "ρ\n(%)",
                     "Ast\n(mm²)"] + sel_rebars
        rows  = []
        rclrs = []

        def make_row(label, x_mm_val, M_kNm):
            rho, Ast, phi_Mn, ok = _design_flexure(M_kNm, fck, fy, b, d)
            x_str = (f"{x_mm_val:.0f}"
                     if isinstance(x_mm_val, (int, float)) else str(x_mm_val))
            if not ok:
                base = [label, x_str, f"{M_kNm:.2f}", "단면부족", "—"]
                return base + ["—"] * len(sel_rebars), (RED, WHI)
            sp   = _rebar_spacing(Ast, fy, sel_rebars)
            base = [label, x_str, f"{M_kNm:.2f}",
                    f"{rho:.3f}", f"{Ast:.0f}"]
            return base + [sp.get(k, "—") for k in sel_rebars], None

        # 지점부
        for nid in sorted(node_x.keys()):
            r, cl = make_row(f"N{nid} (지점)", node_x[nid], node_M[nid])
            rows.append(r); rclrs.append(cl)

        # 경간부
        for lbl, x_sp, M_sp, _ in span_rows:
            r, cl = make_row(lbl, x_sp, M_sp)
            rows.append(r); rclrs.append(cl)

        # ④ 임의 위치 → User 행으로 Flexure 테이블에 통합
        qx_str = self.query_x.get().strip()
        user_qx = None
        if qx_str:
            try:
                user_qx = float(qx_str)
            except ValueError:
                pass
        if user_qx is not None:
            for xs_, xe_, res_ in self._elem_data:
                if xs_ <= user_qx <= xe_:
                    M_u = _interp_at(user_qx, xs_, xe_,
                                     res_["x"], res_["M"])
                    r, cl = make_row(
                        f"User ({user_qx:.0f})", user_qx, M_u)
                    rows.append(r)
                    rclrs.append((BG5, CYN))
                    break

        # 최소 철근 행
        base_min = ["최소 철근", "—", "—",
                    f"{rho_min*100:.3f}", f"{Ast_min:.0f}"]
        rows.append(base_min + [sp_min.get(k, "—") for k in sel_rebars])
        rclrs.append((BG3, TX2))

        _tbl = SimpleTable(self._table_frame,
                    headers=hdrs, rows=rows, col_w=cw,
                    row_colors=rclrs)
        _tbl.pack(fill="x", padx=8, pady=4)
        if hasattr(self, "_tbl_scroll_fn"): _tbl.bind_scroll(self._tbl_scroll_fn)

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
        _tbl2 = SimpleTable(self._table_frame,
                    headers=shear_hdrs,
                    rows=shear_rows,
                    col_w=shear_cw,
                    row_colors=shear_cl)
        _tbl2.pack(fill="x", padx=8, pady=4)
        if hasattr(self, "_tbl_scroll_fn"): _tbl2.bind_scroll(self._tbl_scroll_fn)

        # ── Check Deflection 상세 테이블 ─────────────────
        # 경간 길이, 최대 지점 / 경간 모멘트 수집
        L_total = max((xe_ - xs_) for xs_, xe_, _ in self._elem_data) if self._elem_data else 1000.0
        M_neg   = max((abs(node_M[n]) for n in node_M), default=0.0)
        M_pos   = max((abs(sp[2]) for sp in span_rows), default=0.0)

        defl = _check_deflection(
            fck=fck, fy=fy, b_mm=b, h_mm=h, d_mm=d, cover_mm=cover,
            M_neg_kNm=M_neg, M_pos_kNm=M_pos,
            L_mm=L_total,
        )

        section_label("■ Check Deflection")

        # 색상: O.K.=초록, N.G.=빨강
        def ok_cl(flag): return (None if flag else (RED, WHI))

        defl_hdrs = ["항목", "기호", "값", "판정"]
        dcw       = [260, 80, 200, 200]

        def _fv(v, fmt=".2f", unit=""):
            try: return f"{v:{fmt}}" + (f" {unit}" if unit else "")
            except: return str(v)

        defl_rows = [
            # ─ 재료/단면 ─
            ["콘크리트 탄성계수",   "Ec",  _fv(defl["Ec"],   ".0f", "MPa"),   ""],
            ["탄성계수비",          "n",   f"{defl['n']}",                     ""],
            ["총단면2차모멘트",     "Ig",  _fv(defl["Ig"],   ".0f", "mm⁴"),   ""],
            ["균열단면2차모멘트",   "Icr", _fv(defl["Icr"],  ".0f", "mm⁴"),   ""],
            ["파괴계수",            "fr",  _fv(defl["fr"],   ".2f", "MPa"),    ""],
            ["균열모멘트",          "Mcr", _fv(defl["Mcr"],  ".2f", "kN·m"),   ""],
            # ─ 지점/경간 Ie ─
            ["유효Ie (지점부)",     "Ie,neg", _fv(defl["Ie_neg"], ".0f", "mm⁴"),  ""],
            ["유효Ie (경간부)",     "Ie,pos", _fv(defl["Ie_pos"], ".0f", "mm⁴"),  ""],
            ["유효Ie (설계값)",     "Ie",     _fv(defl["Ie_eff"], ".0f", "mm⁴"),  ""],
            # ─ 하중 ─
            ["고정하중",            "wD",  _fv(defl["wD"],  ".2f", "kN·m"),   ""],
            ["활하중",              "wL",  _fv(defl["wL"],  ".2f", "kN·m"),   ""],
            # ─ 탄성처짐 ─
            ["고정하중 처짐",       "δD",  _fv(defl["d_D"], ".3f", "mm"),     ""],
            ["활하중 처짐",         "δL",  _fv(defl["d_L"], ".3f", "mm"),     ""],
            ["전체 탄성처짐",       "δtot",_fv(defl["d_tot"],".3f","mm"),     ""],
            # ─ 장기처짐 ─
            ["장기계수 (60개월)",   "ξ",   f"{defl['xi']:.1f}",               ""],
            ["장기처짐 계수",       "λ",   f"{defl['lam']:.3f}",              ""],
            ["장기추가처짐",        "δlt", _fv(defl["d_lt"], ".3f", "mm"),    ""],
            # ─ 허용처짐 판정 ─
            ["단기처짐 δL",
             "≤ L/360",
             f"{defl['d_short']:.2f} mm  <  {defl['allow_L360']:.2f} mm",
             "O.K." if defl["short_ok"] else "N.G."],
            ["장기처짐 δlt+δL",
             "≤ L/480",
             f"{defl['d_long']:.2f} mm  <  {defl['allow_L480']:.2f} mm",
             "O.K." if defl["long_ok"] else "N.G."],
        ]
        defl_clrs = [None] * (len(defl_rows) - 2)
        defl_clrs.append(ok_cl(defl["short_ok"]))
        defl_clrs.append(ok_cl(defl["long_ok"]))

        _tbl_d = SimpleTable(self._table_frame,
                             headers=defl_hdrs,
                             rows=defl_rows,
                             col_w=dcw,
                             row_colors=defl_clrs)
        _tbl_d.pack(fill="x", padx=8, pady=4)
        if hasattr(self, "_tbl_scroll_fn"): _tbl_d.bind_scroll(self._tbl_scroll_fn)

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
    #  다이어그램 줌 (마우스 휠) + 패닝 (드래그)
    # ════════════════════════════════════════════════════════
    def _diag_wheel(self, e):
        """마우스 휠로 다이어그램 X축 스케일 조정"""
        delta = getattr(e, 'delta', 0)
        if delta == 0:
            delta = -120 if e.num == 5 else 120
        factor = 1.1 if delta > 0 else 0.9
        cur = self._diag_scale.get()
        new = max(0.2, min(10.0, cur * factor))
        self._diag_scale.set(new)
        self._draw_diagram()

    def _diag_pan_start(self, e):
        self._diag_pan_origin = e.x

    def _diag_pan_move(self, e):
        if self._diag_pan_origin is None:
            return
        dx = e.x - self._diag_pan_origin
        self._diag_pan_x += dx
        self._diag_pan_origin = e.x
        self._draw_diagram()

    # ════════════════════════════════════════════════════════
    #  저장 (_save_result) — 텍스트 파일로 저장
    # ════════════════════════════════════════════════════════
    def _save_result(self):
        """설계 결과를 .2dd 파일에 design_result 키로 저장"""
        import json, os
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            parent=self.win,
            title="설계 결과 저장 (.2dd)",
            defaultextension=".2dd",
            filetypes=[("2D Design File", "*.2dd"), ("모든 파일", "*.*")],
            initialfile="design_result.2dd",
        )
        if not path:
            return

        # 테이블 내용 추출
        rows_out = []
        for w in self._table_frame.winfo_children():
            if isinstance(w, tk.Label):
                rows_out.append({"type": "label", "text": w.cget("text")})
            elif isinstance(w, SimpleTable):
                tbl = {"type": "table", "rows": []}
                for child in w.winfo_children():
                    row_txt = []
                    for lbl in child.winfo_children():
                        if isinstance(lbl, tk.Label):
                            t = lbl.cget("text").strip()
                            if t:
                                row_txt.append(t)
                    if row_txt:
                        tbl["rows"].append(row_txt)
                rows_out.append(tbl)

        # 기존 .2dd 파일이면 병합, 없으면 새로 생성
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data["design_result"] = {
            "std_code": self.std_code.get(),
            "fck":      self.fck.get(),
            "fy_main":  self.fy_main.get(),
            "fy_high":  self.fy_high.get(),
            "b":        self.b_slab.get(),
            "h":        self.h_slab.get(),
            "cover":    self.cover.get(),
            "content":  rows_out,
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo(
                "저장 완료",
                f"설계 결과를 저장했습니다.\n{os.path.basename(path)}",
                parent=self.win)
        except Exception as ex:
            messagebox.showerror("저장 오류", str(ex), parent=self.win)
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
