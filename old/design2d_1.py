"""
2D Design  —  구조 부재 검토 모듈
Node / Support / Load 입력 → 모멘트·전단·처짐 Analysis
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import math

# ── 팔레트 (launcher.py 와 통일) ─────────────────────────
BG   = "#1a1a2e"; BG2  = "#16213e"; BG3  = "#0f3460"
BG4  = "#1a1a2e"; BDR  = "#2c3f62"
ACC  = "#e94560"; ACCH = "#ff6b6b"
GRN  = "#4ecdc4"; YEL  = "#ffd93d"
TXT  = "#dde4f0"; TX2  = "#8fa3c0"
WHI  = "#f0f5ff"; DIS  = "#3d5070"
RED  = "#e94560"; ORG  = "#f5a623"
BLU  = "#4a90d9"; PUR  = "#9b59b6"
CANV = "#0a0a14"   # 캔버스 배경


# ════════════════════════════════════════════════════════
#  유틸 — 간단 FEM (오일러-베르누이 보)
# ════════════════════════════════════════════════════════
def analyze_beam(nodes, members, supports, loads):
    """
    nodes   : {id: (x_mm, y_mm)}
    members : [(n1, n2, E_MPa, I_mm4, A_mm2)]
    supports: {node_id: type}  type: 'pin','fix','semi'
    loads   : [(n1, n2, w_kN_m, type)]  type: 'udl' | point (node_id 기준)
    반환: {member_id: {'M': [...], 'V': [...], 'D': [...], 'x': [...]}}
    """
    results = {}
    EI_default = 200000 * 8.333e7   # E=200GPa, I=HxB=200x200 가정

    for idx, (n1, n2, *props) in enumerate(members):
        x1, y1 = nodes[n1]
        x2, y2 = nodes[n2]
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1e-6:
            continue

        E = props[0] if len(props) > 0 else 200000  # MPa
        I = props[1] if len(props) > 1 else 8.333e7  # mm4
        EI = E * I

        # 이 부재에 걸린 하중 수집
        w = 0.0   # kN/mm 환산
        P_loads = []   # (위치 x_from_n1 mm, 크기 kN)

        for ld in loads:
            ln1, ln2, mag, ltype = ld[0], ld[1], ld[2], ld[3]
            if set([ln1, ln2]) == set([n1, n2]):
                if ltype == 'udl':
                    w += mag / 1000.0   # kN/m → kN/mm
                elif ltype == 'point':
                    P_loads.append((L / 2, mag))  # 중앙 집중
            elif ln1 == n1 and ln2 == n1:  # node 집중하중
                P_loads.append((0, mag))
            elif ln1 == n2 and ln2 == n2:
                P_loads.append((L, mag))

        # Support 반력 (단순보 가정으로 반력 계산)
        s1 = supports.get(n1, 'none')
        s2 = supports.get(n2, 'none')

        # 반력 계산 ─ 단순보(pin-pin) 기준
        RA = 0.0; RB = 0.0
        if w > 0:
            RA += w * L / 2
            RB += w * L / 2
        for xp, P in P_loads:
            RA += P * (L - xp) / L
            RB += P * xp / L

        # fix 지점이면 추가 모멘트 보정 (근사)
        MA_fix = 0.0; MB_fix = 0.0
        if s1 == 'fix' and s2 == 'fix':
            if w > 0:
                MA_fix =  w * L * L / 12
                MB_fix = -w * L * L / 12
        elif s1 == 'fix' and s2 in ('pin', 'semi', 'none'):
            if w > 0:
                MA_fix = w * L * L / 8
        elif s2 == 'fix' and s1 in ('pin', 'semi', 'none'):
            if w > 0:
                MB_fix = w * L * L / 8

        # 분포하중 + 집중하중에 대한 M, V, D 도출
        n_pts = 50
        xs = [i * L / (n_pts - 1) for i in range(n_pts)]
        Ms, Vs, Ds = [], [], []

        for x in xs:
            # 전단력
            V = RA
            if w > 0:
                V -= w * x
            for xp, P in P_loads:
                if x > xp:
                    V -= P
            Vs.append(V)

            # 휨모멘트
            M = RA * x + MA_fix
            if w > 0:
                M -= w * x * x / 2
            for xp, P in P_loads:
                if x > xp:
                    M -= P * (x - xp)
            Ms.append(M)

            # 처짐 (단순보 근사공식)
            if EI > 0:
                if w > 0:
                    D = (w * x * (L**3 - 2*L*x**2 + x**3)) / (24 * EI)
                else:
                    D = 0.0
                for xp, P in P_loads:
                    if x <= xp:
                        D += (P * x * (3*L*xp - 3*xp**2 - x**2)) / (6 * EI * L) * (L - xp)
                    else:
                        D += (P * xp * (3*L*x - 3*x**2 - xp**2)) / (6 * EI * L) * (L - x) / L * L
                Ds.append(D * 1000)  # mm → ×1000 for display
            else:
                Ds.append(0.0)

        results[idx] = {
            'n1': n1, 'n2': n2,
            'L': L,
            'M': Ms, 'V': Vs, 'D': Ds, 'x': xs,
            'RA': RA, 'RB': RB,
            'MA_fix': MA_fix
        }
    return results


# ════════════════════════════════════════════════════════
#  결과 다이얼로그
# ════════════════════════════════════════════════════════
class ResultDialog(tk.Toplevel):
    def __init__(self, parent, results, nodes):
        super().__init__(parent)
        self.title("Analysis Result")
        self.configure(bg=BG2)
        self.geometry("860x640")
        self.resizable(True, True)
        self.transient(parent); self.grab_set()
        self._results = results
        self._nodes = nodes
        self._build()

    def _build(self):
        # 헤더
        hdr = tk.Frame(self, bg=BG3, height=48); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📊  Analysis Result", font=("Malgun Gothic",13,"bold"),
                 bg=BG3, fg=WHI).pack(side="left", padx=20, pady=8)
        tk.Button(hdr, text="✕  닫기", command=self.destroy,
                  font=("Malgun Gothic",9), bg=RED, fg=WHI,
                  relief="flat", cursor="hand2", padx=10).pack(side="right", padx=12, pady=8)

        # 탭
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure("R.TNotebook", background=BG2, borderwidth=0)
        style.configure("R.TNotebook.Tab", background=BG3, foreground=TXT,
                        font=("Malgun Gothic",10,"bold"), padding=[14,6])
        style.map("R.TNotebook.Tab",
                  background=[("selected", ACC)],
                  foreground=[("selected", WHI)])
        nb = ttk.Notebook(self, style="R.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        for ridx, rdata in self._results.items():
            n1, n2 = rdata['n1'], rdata['n2']
            tab = tk.Frame(nb, bg=BG2); nb.add(tab, text=f"  부재 {ridx+1}  (N{n1}→N{n2})  ")
            self._build_tab(tab, rdata)

    def _build_tab(self, parent, r):
        L = r['L']
        # 수치 요약
        info_fr = tk.Frame(parent, bg=BG3); info_fr.pack(fill="x", padx=12, pady=(12,6))
        Mmax = max(r['M']); Mmin = min(r['M'])
        Vmax = max(r['V']); Vmin = min(r['V'])
        Dmax = max(r['D']); Dmin = min(r['D'])
        infos = [
            ("부재 길이",  f"{L:.0f} mm"),
            ("최대 모멘트", f"{Mmax:.2f} kN·m"),
            ("최소 모멘트", f"{Mmin:.2f} kN·m"),
            ("최대 전단",   f"{Vmax:.2f} kN"),
            ("최소 전단",   f"{Vmin:.2f} kN"),
            ("최대 처짐",   f"{Dmax:.3f} ×10⁻³ mm"),
            ("반력 RA",    f"{r['RA']:.2f} kN"),
            ("반력 RB",    f"{r['RB']:.2f} kN"),
        ]
        for i, (k, v) in enumerate(infos):
            c = i % 4; row = i // 4
            fr2 = tk.Frame(info_fr, bg=BG4, highlightbackground=BDR, highlightthickness=1)
            fr2.grid(row=row, column=c, padx=4, pady=4, sticky="ew", ipadx=8, ipady=6)
            info_fr.columnconfigure(c, weight=1)
            tk.Label(fr2, text=k, font=("Malgun Gothic",8), bg=BG4, fg=TX2).pack()
            tk.Label(fr2, text=v, font=("Malgun Gothic",10,"bold"), bg=BG4, fg=YEL).pack()

        # 그래프 영역 (3행)
        chart_fr = tk.Frame(parent, bg=BG2); chart_fr.pack(fill="both", expand=True, padx=12, pady=6)
        self._draw_chart(chart_fr, r['x'], r['M'], "Moment Diagram (kN·m)", ACC,   0)
        self._draw_chart(chart_fr, r['x'], r['V'], "Shear Diagram (kN)",    GRN,   1)
        self._draw_chart(chart_fr, r['x'], r['D'], "Deflection (×10⁻³ mm)", YEL,  2)

    def _draw_chart(self, parent, xs, ys, title, color, row):
        fr = tk.Frame(parent, bg=BG3, highlightbackground=BDR, highlightthickness=1)
        fr.grid(row=row, column=0, sticky="nsew", pady=4, padx=0)
        parent.rowconfigure(row, weight=1)
        parent.columnconfigure(0, weight=1)

        tk.Label(fr, text=title, font=("Malgun Gothic",9,"bold"),
                 bg=BG3, fg=color).pack(anchor="w", padx=10, pady=(6,2))

        c = tk.Canvas(fr, bg=CANV, highlightthickness=0, height=100)
        c.pack(fill="both", expand=True, padx=8, pady=(0,8))
        c.update_idletasks()

        def draw(_=None):
            c.delete("all")
            W = c.winfo_width(); H = c.winfo_height()
            pad = 30
            if W < 60 or H < 30: return
            if not ys: return
            mn = min(ys); mx = max(ys)
            rng = mx - mn if abs(mx - mn) > 1e-10 else 1.0
            zero_y = pad + (mx / rng) * (H - 2*pad)

            # 기준선
            c.create_line(pad, zero_y, W-pad, zero_y, fill="#2c3f62", dash=(4,4))
            # 폴리라인
            pts = []
            for x, y in zip(xs, ys):
                px = pad + (x / xs[-1]) * (W - 2*pad) if xs[-1] > 0 else pad
                py = pad + (1 - (y - mn) / rng) * (H - 2*pad)
                pts += [px, py]
            if len(pts) >= 4:
                c.create_line(*pts, fill=color, width=2, smooth=True)
            # 채우기
            poly_pts = [pad, zero_y] + pts + [W-pad, zero_y]
            c.create_polygon(*poly_pts, fill=color, stipple="gray25", outline="")
            # Y축 레이블
            for val, pos in [(mx, pad), (0, zero_y), (mn, H-pad)]:
                c.create_text(pad-4, pos, text=f"{val:.1f}", anchor="e",
                              font=("Consolas",7), fill=TX2)

        c.bind("<Configure>", draw)
        c.after(100, draw)


# ════════════════════════════════════════════════════════
#  메인 2D Design 패널
# ════════════════════════════════════════════════════════
class Design2DPanel:
    """
    launcher.py 의 _mkcb('2d_design') 에서 호출
    usage:
        win = tk.Toplevel(root)
        Design2DPanel(win, username="admin")
    """
    SUPPORT_COLORS = {'pin': '#4ecdc4', 'fix': '#ffd93d', 'semi': '#ff9f43'}

    def __init__(self, win, username=""):
        self.win = win
        self.user = username

        # ── 데이터 ──────────────────────────────────────
        self.projects = []          # [(name, view_type)]
        self.cur_proj = tk.IntVar(value=-1)

        # 캔버스 요소
        self.nodes   = {}           # {id: (x_canvas, y_canvas)}
        self.members = []           # [(n1, n2, E, I, A)]
        self.supports= {}           # {node_id: 'pin'|'fix'|'semi'}
        self.loads   = []           # [(n1, n2, mag_kN_m, 'udl')]

        # 상태
        self.mode       = tk.StringVar(value="none")
        self.view_type  = tk.StringVar(value="line")  # line / plan
        self.node_cnt   = 0
        self._sel_nodes  = []       # 현재 선택 중인 node ids
        self._mode_label = tk.StringVar(value="")
        self._hover_item = None

        # 팬/줌
        self._pan_start = None
        self._offset    = [0, 0]
        self._scale     = 1.0

        self._build()

    # ── UI 빌드 ─────────────────────────────────────────
    def _build(self):
        win = self.win
        # 헤더
        hdr = tk.Frame(win, bg=BG3, height=50); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="✏️  2D Design", font=("Malgun Gothic",13,"bold"),
                 bg=BG3, fg=WHI).pack(side="left", padx=18, pady=8)
        if self.user:
            tk.Label(hdr, text=f"({self.user})", font=("Malgun Gothic",9),
                     bg=BG3, fg=TX2).pack(side="left")
        tk.Label(hdr, textvariable=self._mode_label,
                 font=("Malgun Gothic",9,"italic"), bg=BG3, fg=YEL).pack(side="left", padx=16)

        # Analysis 버튼
        self._abtn = tk.Button(hdr, text="  Analysis  ",
                               font=("Malgun Gothic",11,"bold"),
                               bg=YEL, fg=BG2, relief="flat", cursor="hand2",
                               command=self._run_analysis, padx=16, pady=6)
        self._abtn.pack(side="right", padx=14, pady=8)

        tk.Frame(win, bg=BDR, height=1).pack(fill="x")

        # 바디
        body = tk.Frame(win, bg=BG); body.pack(fill="both", expand=True)

        # ── 왼쪽: 툴바 + 캔버스 ──────────────────────────
        left = tk.Frame(body, bg=BG); left.pack(side="left", fill="both", expand=True)
        self._build_toolbar(left)
        self._build_canvas(left)
        self._build_statusbar(left)

        # ── 오른쪽: 프로젝트 리스트 ──────────────────────
        self._build_sidebar(body)

    def _build_toolbar(self, parent):
        tb = tk.Frame(parent, bg="#111827"); tb.pack(fill="x")
        self._tool_btns = {}

        def sep():
            tk.Frame(tb, bg=BDR, width=1).pack(side="left", fill="y", padx=4, pady=6)

        def tbtn(text, mode, tip=""):
            b = tk.Button(tb, text=text, font=("Malgun Gothic",9,"bold"),
                          bg="#1f2937", fg=TXT, relief="flat", cursor="hand2",
                          padx=10, pady=6, command=lambda m=mode: self._set_mode(m))
            b.pack(side="left", padx=2, pady=4)
            b.bind("<Enter>", lambda e, w=b: w.config(bg="#374151"))
            b.bind("<Leave>", lambda e, w=b, m=mode: w.config(
                bg=ACC if self.mode.get()==m else "#1f2937"))
            self._tool_btns[mode] = b
            return b

        # 뷰 전환
        tk.Label(tb, text="View:", font=("Malgun Gothic",8), bg="#111827", fg=TX2).pack(side="left", padx=(10,4))
        for t, v in [("Line View","line"), ("Plan View","plan")]:
            b = tk.Button(tb, text=t, font=("Malgun Gothic",8,"bold"),
                          bg="#1f2937", fg=TXT, relief="flat", cursor="hand2",
                          padx=8, pady=4, command=lambda vt=v: self._set_view(vt))
            b.pack(side="left", padx=2, pady=4)
            if v == "line":
                b.config(bg=ACC, fg=WHI)
            self._tool_btns[f"view_{v}"] = b
        sep()

        # 도구
        tbtn("🔵 Node",    "node_menu")
        sep()
        tbtn("🔺 Support", "support_menu")
        sep()
        tbtn("⬇ Load",    "load_menu")
        sep()

        # Node 서브메뉴 프레임 (토글)
        self._sub_fr = tk.Frame(tb, bg="#111827")
        self._sub_fr.pack(side="left", padx=4)

        # 리셋
        tk.Button(tb, text="🗑 Reset", font=("Malgun Gothic",8),
                  bg="#1f2937", fg=RED, relief="flat", cursor="hand2",
                  padx=8, pady=4, command=self._reset).pack(side="right", padx=6, pady=4)

    def _set_view(self, vt):
        self.view_type.set(vt)
        self._set_mode("none")
        for v in ["line","plan"]:
            key = f"view_{v}"
            if key in self._tool_btns:
                self._tool_btns[key].config(
                    bg=ACC if v==vt else "#1f2937",
                    fg=WHI if v==vt else TXT)
        self._redraw()

    def _set_mode(self, mode):
        self.mode.set(mode)
        self._sel_nodes.clear()
        # 서브메뉴 제거
        for w in self._sub_fr.winfo_children():
            w.destroy()

        # 버튼 색상 갱신
        for m, b in self._tool_btns.items():
            if m.startswith("view_"): continue
            b.config(bg=ACC if m==mode else "#1f2937",
                     fg=WHI if m==mode else TXT)

        if mode == "node_menu":
            self._show_node_submenu()
        elif mode == "support_menu":
            self._show_support_submenu()
        elif mode == "load_menu":
            self._show_load_submenu()
        else:
            self._mode_label.set("")

    def _show_node_submenu(self):
        fr = self._sub_fr
        is_line = self.view_type.get() == "line"
        for t, m in [("Point","point"), ("Line","line_draw"), ("Plan","plan_draw")]:
            state = "normal" if (t != "Plan" or not is_line) else "disabled"
            fg_col = DIS if state=="disabled" else TXT
            b = tk.Button(fr, text=t, font=("Malgun Gothic",8),
                          bg="#0f172a", fg=fg_col, relief="flat", cursor="hand2" if state=="normal" else "arrow",
                          padx=8, pady=4, state=state,
                          command=lambda m2=m: self._activate_mode(m2))
            b.pack(side="left", padx=2)
        self._mode_label.set("▸ Node 유형 선택")

    def _show_support_submenu(self):
        fr = self._sub_fr
        for t, m in [("Fix","sup_fix"), ("Pin","sup_pin"), ("SemiFix","sup_semi")]:
            b = tk.Button(fr, text=t, font=("Malgun Gothic",8),
                          bg="#0f172a", fg=TXT, relief="flat", cursor="hand2",
                          padx=8, pady=4, command=lambda m2=m: self._activate_mode(m2))
            b.pack(side="left", padx=2)
        self._mode_label.set("▸ Support 유형 선택 후 Point 클릭")

    def _show_load_submenu(self):
        fr = self._sub_fr
        b = tk.Button(fr, text="UDL (등분포)", font=("Malgun Gothic",8),
                      bg="#0f172a", fg=TXT, relief="flat", cursor="hand2",
                      padx=8, pady=4, command=lambda: self._activate_mode("load_udl"))
        b.pack(side="left", padx=2)
        b2 = tk.Button(fr, text="집중하중", font=("Malgun Gothic",8),
                       bg="#0f172a", fg=TXT, relief="flat", cursor="hand2",
                       padx=8, pady=4, command=lambda: self._activate_mode("load_point"))
        b2.pack(side="left", padx=2)
        self._mode_label.set("▸ 하중 유형 선택")

    def _activate_mode(self, mode):
        self.mode.set(mode)
        self._sel_nodes.clear()
        labels = {
            "point":      "▸ 캔버스에 Point 클릭",
            "line_draw":  "▸ 시작 Node → 끝 Node 클릭",
            "plan_draw":  "▸ 3개 이상 Node 클릭 → 더블클릭 완료",
            "sup_fix":    "▸ Fix 적용할 Node 클릭",
            "sup_pin":    "▸ Pin 적용할 Node 클릭",
            "sup_semi":   "▸ SemiFix 적용할 Node 클릭",
            "load_udl":   "▸ 시작 Node → 끝 Node 클릭 (등분포 하중)",
            "load_point": "▸ 하중 적용 Node 클릭",
        }
        self._mode_label.set(labels.get(mode, ""))

    def _build_canvas(self, parent):
        fr = tk.Frame(parent, bg=CANV, highlightbackground=BDR, highlightthickness=1)
        fr.pack(fill="both", expand=True, padx=6, pady=(0,0))
        self._canv = tk.Canvas(fr, bg=CANV, cursor="crosshair", highlightthickness=0)
        self._canv.pack(fill="both", expand=True)

        self._canv.bind("<Button-1>",         self._on_click)
        self._canv.bind("<Double-Button-1>",  self._on_dbl)
        self._canv.bind("<Motion>",           self._on_move)
        self._canv.bind("<Button-3>",         self._on_rclick)
        # 팬
        self._canv.bind("<ButtonPress-2>",    self._pan_start_cb)
        self._canv.bind("<B2-Motion>",        self._pan_move_cb)
        # 줌
        self._canv.bind("<MouseWheel>",       self._zoom)
        self._canv.bind("<Button-4>",         self._zoom)
        self._canv.bind("<Button-5>",         self._zoom)

    def _build_statusbar(self, parent):
        sb = tk.Frame(parent, bg="#0d1117", height=26); sb.pack(fill="x"); sb.pack_propagate(False)
        self._coord_var = tk.StringVar(value="X: 0.0   Y: 0.0")
        tk.Label(sb, textvariable=self._coord_var, font=("Consolas",9),
                 bg="#0d1117", fg=TX2).pack(side="left", padx=12)
        tk.Label(sb, text="Unit : mm , kN", font=("Consolas",9),
                 bg="#0d1117", fg=TX2).pack(side="right", padx=12)

    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg="#1a1a2e", width=200,
                      highlightbackground=BDR, highlightthickness=1)
        sb.pack(side="right", fill="y"); sb.pack_propagate(False)

        # 헤더 행
        hdr = tk.Frame(sb, bg=BG3); hdr.pack(fill="x")
        tk.Label(hdr, text="List", font=("Malgun Gothic",9,"bold"),
                 bg=BG3, fg=TXT, width=10).pack(side="left", pady=6)
        tk.Button(hdr, text="ADD", font=("Malgun Gothic",9,"bold"),
                  bg=ACC, fg=WHI, relief="flat", cursor="hand2",
                  padx=8, command=self._add_project).pack(side="right", padx=4, pady=4)

        # 컬럼명
        col_fr = tk.Frame(sb, bg=BG2); col_fr.pack(fill="x")
        tk.Label(col_fr, text="Name", font=("Malgun Gothic",8), bg=BG2, fg=TX2,
                 width=11, anchor="center").pack(side="left", pady=3)
        tk.Label(col_fr, text="View", font=("Malgun Gothic",8), bg=BG2, fg=TX2,
                 width=8, anchor="center").pack(side="right", pady=3)

        tk.Frame(sb, bg=BDR, height=1).pack(fill="x")

        # 리스트 스크롤
        self._list_fr = tk.Frame(sb, bg=BG2); self._list_fr.pack(fill="both", expand=True)

        # 하단 +/-
        btn_fr = tk.Frame(sb, bg=BG3); btn_fr.pack(fill="x", pady=4)
        for t, cmd in [(" + ", self._add_project), (" − ", self._del_project)]:
            tk.Button(btn_fr, text=t, font=("Malgun Gothic",11,"bold"),
                      bg="#1f2937", fg=TXT, relief="flat", cursor="hand2",
                      padx=8, command=cmd).pack(side="left", padx=6)

    # ── 프로젝트 리스트 ──────────────────────────────────
    def _add_project(self):
        n = len(self.projects) + 1
        name = f"Sample{n}"
        vtype = "Line"
        self.projects.append([name, vtype])
        self._refresh_list()
        self._select_project(len(self.projects)-1)

    def _del_project(self):
        idx = self.cur_proj.get()
        if 0 <= idx < len(self.projects):
            self.projects.pop(idx)
            self._clear_canvas_data()
            self.cur_proj.set(-1)
            self._refresh_list()
            self._redraw()

    def _refresh_list(self):
        fr = self._list_fr
        for w in fr.winfo_children(): w.destroy()
        for i, (name, vtype) in enumerate(self.projects):
            row = tk.Frame(fr, bg=BG4 if i == self.cur_proj.get() else BG2,
                           highlightbackground=BDR if i==self.cur_proj.get() else BG2,
                           highlightthickness=1)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=name, font=("Malgun Gothic",9), bg=row.cget("bg"),
                     fg=WHI if i==self.cur_proj.get() else TXT,
                     width=11, anchor="w").pack(side="left", padx=4, pady=5)
            tk.Label(row, text=vtype, font=("Malgun Gothic",8), bg=row.cget("bg"),
                     fg=GRN if i==self.cur_proj.get() else TX2,
                     width=8, anchor="center").pack(side="right", padx=4)
            row.bind("<Button-1>", lambda e, idx=i: self._select_project(idx))
            for ch in row.winfo_children():
                ch.bind("<Button-1>", lambda e, idx=i: self._select_project(idx))

    def _select_project(self, idx):
        self.cur_proj.set(idx)
        self._clear_canvas_data()
        self._redraw()
        self._refresh_list()
        # 뷰 동기화
        vtype = self.projects[idx][1].lower()
        self._set_view(vtype)

    def _clear_canvas_data(self):
        self.nodes.clear(); self.node_cnt = 0
        self.members.clear(); self.supports.clear(); self.loads.clear()
        self._sel_nodes.clear()

    # ── 캔버스 이벤트 ────────────────────────────────────
    def _on_click(self, e):
        mode = self.mode.get()
        cx, cy = self._s2c(e.x, e.y)   # 스크린 → 캔버스 좌표

        if mode == "point":
            self._add_node(cx, cy)
        elif mode == "line_draw":
            nid = self._node_at(e.x, e.y)
            if nid is None:
                nid = self._add_node(cx, cy)
            self._sel_nodes.append(nid)
            if len(self._sel_nodes) >= 2:
                self._add_member(self._sel_nodes[-2], self._sel_nodes[-1])
                # 연속 선긋기: 마지막 노드를 시작점으로 유지
                self._sel_nodes = [self._sel_nodes[-1]]
        elif mode in ("sup_fix","sup_pin","sup_semi"):
            nid = self._node_at(e.x, e.y)
            if nid is not None:
                stype = mode.replace("sup_","")
                self.supports[nid] = stype
                self._redraw()
        elif mode in ("load_udl","load_point"):
            nid = self._node_at(e.x, e.y)
            if nid is not None:
                self._sel_nodes.append(nid)
                if len(self._sel_nodes) == 1:
                    self._mode_label.set(f"▸ 끝 Node 클릭 (시작: N{nid})")
                elif len(self._sel_nodes) >= 2:
                    n1, n2 = self._sel_nodes[0], self._sel_nodes[1]
                    ltype = "udl" if mode == "load_udl" else "point"
                    self._ask_load(n1, n2, ltype)
                    self._sel_nodes.clear()
                    self._activate_mode(mode)

    def _on_dbl(self, e):
        if self.mode.get() == "plan_draw" and len(self._sel_nodes) >= 3:
            # 평면 닫기 (미구현 — 추후 확장)
            self._sel_nodes.clear()
            self._mode_label.set("▸ Plan 완성")
            self._redraw()

    def _on_move(self, e):
        cx, cy = self._s2c(e.x, e.y)
        self._coord_var.set(f"X: {cx:.1f}   Y: {cy:.1f}")

    def _on_rclick(self, e):
        self._sel_nodes.clear()
        self._mode_label.set(self._mode_label.get().split("(")[0])

    # ── 팬 / 줌 ─────────────────────────────────────────
    def _pan_start_cb(self, e):
        self._pan_start = (e.x, e.y)

    def _pan_move_cb(self, e):
        if self._pan_start:
            dx = e.x - self._pan_start[0]
            dy = e.y - self._pan_start[1]
            self._offset[0] += dx; self._offset[1] += dy
            self._pan_start = (e.x, e.y)
            self._redraw()

    def _zoom(self, e):
        factor = 1.1 if (e.delta > 0 or e.num == 4) else 0.9
        self._scale *= factor
        self._scale = max(0.1, min(self._scale, 20))
        self._redraw()

    # ── 좌표 변환 ────────────────────────────────────────
    def _c2s(self, cx, cy):
        """캔버스 좌표 → 스크린 좌표"""
        W = self._canv.winfo_width()  // 2
        H = self._canv.winfo_height() // 2
        sx = cx * self._scale + W + self._offset[0]
        sy = -cy * self._scale + H + self._offset[1]
        return sx, sy

    def _s2c(self, sx, sy):
        """스크린 좌표 → 캔버스 좌표"""
        W = self._canv.winfo_width()  // 2
        H = self._canv.winfo_height() // 2
        cx = (sx - W - self._offset[0]) / self._scale
        cy = -(sy - H - self._offset[1]) / self._scale
        return cx, cy

    # ── 데이터 조작 ──────────────────────────────────────
    def _add_node(self, cx, cy):
        nid = self.node_cnt
        self.node_cnt += 1
        # 스냅: 50mm 격자
        cx = round(cx / 50) * 50
        cy = round(cy / 50) * 50
        self.nodes[nid] = (cx, cy)
        self._redraw()
        return nid

    def _add_member(self, n1, n2):
        if n1 == n2: return
        # 중복 방지
        for m in self.members:
            if set([m[0],m[1]]) == set([n1,n2]): return
        self.members.append((n1, n2, 200000, 8.333e7, 40000))
        self._redraw()

    def _ask_load(self, n1, n2, ltype):
        dlg = simpledialog.askfloat(
            "하중 입력",
            f"{'등분포 하중 크기 (kN/m)' if ltype=='udl' else '집중하중 크기 (kN)'}:",
            parent=self.win, minvalue=0.0)
        if dlg is not None:
            self.loads.append((n1, n2, dlg, ltype))
            self._redraw()

    def _node_at(self, sx, sy, tol=12):
        """스크린 좌표 근처의 node id 반환"""
        for nid, (cx, cy) in self.nodes.items():
            nx, ny = self._c2s(cx, cy)
            if math.hypot(sx - nx, sy - ny) < tol:
                return nid
        return None

    # ── 리셋 ─────────────────────────────────────────────
    def _reset(self):
        if messagebox.askyesno("초기화", "현재 도면을 모두 지우시겠습니까?", parent=self.win):
            self._clear_canvas_data()
            self._redraw()

    # ── 렌더링 ───────────────────────────────────────────
    def _redraw(self):
        c = self._canv; c.delete("all")
        W = c.winfo_width(); H = c.winfo_height()
        if W < 2: return

        # 격자
        self._draw_grid(c, W, H)

        # 부재 (선)
        for n1, n2, *_ in self.members:
            if n1 in self.nodes and n2 in self.nodes:
                x1,y1 = self._c2s(*self.nodes[n1])
                x2,y2 = self._c2s(*self.nodes[n2])
                c.create_line(x1,y1,x2,y2, fill=RED, width=3)
                # 치수
                mx, my = (x1+x2)/2, (y1+y2)/2
                L = math.hypot(self.nodes[n2][0]-self.nodes[n1][0],
                                self.nodes[n2][1]-self.nodes[n1][1])
                c.create_text(mx, my-12, text=f"{L:.0f}", fill=TX2,
                              font=("Consolas",8))

        # 하중 표시
        for ld in self.loads:
            self._draw_load(c, ld)

        # Support
        for nid, stype in self.supports.items():
            if nid in self.nodes:
                sx, sy = self._c2s(*self.nodes[nid])
                self._draw_support(c, sx, sy, stype)

        # Nodes
        for nid, (cx, cy) in self.nodes.items():
            sx, sy = self._c2s(cx, cy)
            col = GRN if nid == 0 else YEL
            r = 6
            c.create_oval(sx-r,sy-r,sx+r,sy+r, fill=col, outline=WHI, width=1)
            c.create_text(sx+10, sy-10, text=f"N{nid}", fill=TX2, font=("Consolas",8))

        # 선택중인 노드 하이라이트
        for nid in self._sel_nodes:
            if nid in self.nodes:
                sx, sy = self._c2s(*self.nodes[nid])
                self._canv.create_oval(sx-10,sy-10,sx+10,sy+10,
                                       outline=ACCH, width=2)

    def _draw_grid(self, c, W, H):
        step = max(10, 50 * self._scale)
        # 간격이 너무 촘촘하면 스킵
        if step < 15: return
        ox = (W//2 + self._offset[0]) % step
        oy = (H//2 + self._offset[1]) % step
        for x in range(int(ox), W, int(step)):
            c.create_line(x, 0, x, H, fill="#1e293b", width=1)
        for y in range(int(oy), H, int(step)):
            c.create_line(0, y, W, y, fill="#1e293b", width=1)
        # 원점 십자
        ox2, oy2 = self._c2s(0,0)
        c.create_line(ox2-8,oy2, ox2+8,oy2, fill="#334155", width=1)
        c.create_line(ox2,oy2-8, ox2,oy2+8, fill="#334155", width=1)

    def _draw_support(self, c, sx, sy, stype):
        col = self.SUPPORT_COLORS.get(stype, GRN)
        sz = 14
        if stype == "pin":
            # 삼각형
            pts = [sx, sy+sz, sx-sz, sy+sz*2, sx+sz, sy+sz*2]
            c.create_polygon(*pts, fill=col, outline=WHI, width=1)
            c.create_line(sx-sz, sy+sz*2, sx+sz, sy+sz*2, fill=WHI, width=2)
        elif stype == "fix":
            # 사각형 채움
            c.create_rectangle(sx-sz, sy+sz//2, sx+sz, sy+sz*2,
                                fill=col, outline=WHI, width=1)
            for i in range(-sz, sz+1, 5):
                c.create_line(sx+i, sy+sz*2, sx+i-4, sy+sz*2+6,
                               fill=WHI, width=1)
        elif stype == "semi":
            # 원형
            pts = [sx, sy+sz, sx-sz, sy+sz*2, sx+sz, sy+sz*2]
            c.create_polygon(*pts, fill=col, outline=WHI, width=1)
            c.create_oval(sx-4, sy+sz*2-4, sx+4, sy+sz*2+4,
                          fill=WHI, outline="")

    def _draw_load(self, c, ld):
        n1, n2, mag, ltype = ld
        if n1 not in self.nodes: return
        x1,y1 = self._c2s(*self.nodes[n1])
        if ltype == "udl" and n2 in self.nodes:
            x2,y2 = self._c2s(*self.nodes[n2])
            steps = 8
            for i in range(steps+1):
                ax = x1 + (x2-x1)*i/steps
                ay = y1 + (y2-y1)*i/steps
                c.create_line(ax, ay-30, ax, ay-6, fill=BLU, width=1,
                              arrow=tk.LAST, arrowshape=(6,8,3))
            c.create_line(x1, y1-30, x2, y2-30, fill=BLU, width=2)
            c.create_text((x1+x2)/2, y1-38, text=f"{mag:.1f} kN/m",
                          fill=BLU, font=("Consolas",8,"bold"))
        elif ltype == "point":
            c.create_line(x1, y1-40, x1, y1-8, fill=ORG, width=2,
                          arrow=tk.LAST, arrowshape=(8,10,4))
            c.create_text(x1+14, y1-30, text=f"{mag:.1f} kN",
                          fill=ORG, font=("Consolas",8,"bold"))

    # ── Analysis ─────────────────────────────────────────
    def _run_analysis(self):
        if self.cur_proj.get() < 0:
            messagebox.showwarning("프로젝트 없음", "프로젝트를 먼저 ADD 해주세요.", parent=self.win)
            return
        if not self.members:
            messagebox.showwarning("부재 없음", "Line을 먼저 그려주세요.", parent=self.win)
            return
        if not self.supports:
            messagebox.showwarning("Support 없음", "Support를 먼저 입력해주세요.", parent=self.win)
            return
        if not self.loads:
            messagebox.showwarning("하중 없음", "하중을 먼저 입력해주세요.", parent=self.win)
            return

        try:
            results = analyze_beam(
                nodes=self.nodes,
                members=self.members,
                supports=self.supports,
                loads=self.loads)
            ResultDialog(self.win, results, self.nodes)
        except Exception as ex:
            import traceback
            messagebox.showerror("분석 오류", f"{ex}\n\n{traceback.format_exc()}", parent=self.win)


# ════════════════════════════════════════════════════════
#  진입점 (단독 실행 & launcher 통합)
# ════════════════════════════════════════════════════════
def open_2d_design(parent, username=""):
    """launcher.py 에서 호출하는 함수"""
    win = tk.Toplevel(parent)
    win.title(f"2D Design  ─  {username}" if username else "2D Design")
    win.geometry("1280x800"); win.minsize(900,600)
    win.configure(bg=BG)
    win.lift(); win.focus_force()
    Design2DPanel(win, username=username)
    return win


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    open_2d_design(root, username="admin")
    root.mainloop()
