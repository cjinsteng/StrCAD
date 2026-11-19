"""
design.py — 보 단면 설계 창 (Auto Table v1.3 에서 그대로 옮김)
KDS 14.20.20 간략 계산: 휨 ρ (0.75ρb 상한), 전단 Vc=(1/6)√fck·bw·d.  결과를 선택한 행에 반영.
"""
import tkinter as tk
from tkinter import messagebox

BG = "#0f1520"; BG2 = "#141d2e"; BG3 = "#1a2540"; BDR = "#2c3f62"
ACC = "#1a56db"; ACCH = "#2563eb"; GRN = "#15803d"; RED = "#dc2626"
TXT = "#dde4f0"; TX2 = "#8fa3c0"; TX3 = "#546887"; WHI = "#f0f5ff"


def _lht(h, a=20):
    r = min(255, int(h[1:3], 16) + a); g = min(255, int(h[3:5], 16) + a); b = min(255, int(h[5:7], 16) + a)
    return f"#{r:02x}{g:02x}{b:02x}"


class _Cell:
    def __init__(self, row, key):
        self.row, self.key = row, key

    def get(self):
        return self.row.get(self.key, "")

    def set(self, v):
        self.row[self.key] = v


class DesignWindow(tk.Toplevel):
    """
    보 단면 설계 입력 창.
    - 설계 하중(Mu, Vu), 단면(B, D), 재료(fck, fy) 입력
    - [설계 실행] 클릭 → 최소 배근 계산 → 결과를 AutoTable 행에 자동 반영
    """
    # KDS 14.20.20 기준 계산에 사용하는 파이
    _PHI_B = 0.85   # 휨 강도감소계수
    _PHI_V = 0.75   # 전단 강도감소계수
    _BETA1 = 0.80   # fck ≤ 28 MPa 기준 (간략화)

    def __init__(self, parent, row: dict, member_name: str = "", on_apply=None):
        super().__init__(parent)
        self.on_apply = on_apply
        _map = {"width": "b", "depth": "h",
                "em_top": "e_top", "em_bot": "e_bot", "em_stir": "e_stir",
                "cen_top": "m_top", "cen_bot": "m_bot", "cen_stir": "m_stir",
                "ev_top": "j_top", "ev_bot": "j_bot", "ev_stir": "j_stir"}
        rv = {k: _Cell(row, v) for k, v in _map.items()}
        self.parent_rv  = rv           # AutoTable 행 (결과 반영용)
        self.member_name = member_name
        self.title(f"보 단면 설계  —  {member_name}" if member_name else "보 단면 설계")
        self.geometry("760x620"); self.minsize(700, 560)
        self.configure(bg=BG)
        self.resizable(True, True)
        self._result = {}              # 계산 결과 저장
        self._build()
        self._center()
        self.transient(parent); self.lift(); self.focus_force()

    # ── 레이아웃 ─────────────────────────────────────────
    def _build(self):
        # 제목 헤더
        hdr = tk.Frame(self, bg=BG2, height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🔧  보 단면 설계",
                 font=("Malgun Gothic",12,"bold"), bg=BG2, fg=WHI).pack(side="left", padx=16)
        tk.Label(hdr, text="KDS 14.20.20 강도설계법 (간략 계산)",
                 font=("Malgun Gothic",8), bg=BG2, fg=TX2).pack(side="left")
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG); body.pack(fill="both", expand=True, padx=16, pady=10)

        # ── 좌: 입력 패널 ─────────────────────────────────
        inp = tk.Frame(body, bg=BG2, bd=0, highlightthickness=1,
                       highlightbackground=BDR)
        inp.pack(side="left", fill="y", padx=(0,10), pady=4)

        def sec_label(parent, txt):
            tk.Label(parent, text=txt,
                     font=("Malgun Gothic",9,"bold"), bg=BG2, fg=ACC,
                     anchor="w", padx=12, pady=6).pack(fill="x")
            tk.Frame(parent, bg=BDR, height=1).pack(fill="x", padx=8)

        def field(parent, label, key, default="", unit=""):
            fr = tk.Frame(parent, bg=BG2); fr.pack(fill="x", padx=12, pady=3)
            tk.Label(fr, text=label, font=("Malgun Gothic",9),
                     bg=BG2, fg=TX2, width=18, anchor="w").pack(side="left")
            var = tk.StringVar(value=default)
            ent = tk.Entry(fr, textvariable=var, width=10,
                           font=("Malgun Gothic",9), bg=BG3, fg=TXT,
                           insertbackground=WHI, relief="flat",
                           highlightbackground=BDR, highlightthickness=1)
            ent.pack(side="left", ipady=3, padx=(0,4))
            ent.bind("<FocusIn>",  lambda e: ent.config(highlightbackground=ACCH))
            ent.bind("<FocusOut>", lambda e: ent.config(highlightbackground=BDR))
            if unit:
                tk.Label(fr, text=unit, font=("Malgun Gothic",8),
                         bg=BG2, fg=TX3).pack(side="left")
            self._vars[key] = var

        self._vars = {}

        # 단면 정보 (AutoTable 행에서 가져오기)
        bw_init = ""; bd_init = ""
        wv = self.parent_rv.get("width")
        dv = self.parent_rv.get("depth")
        if wv: bw_init = wv.get() if hasattr(wv,"get") else str(wv)
        if dv: bd_init = dv.get() if hasattr(dv,"get") else str(dv)

        sec_label(inp, "■ 단면 정보")
        field(inp, "폭  b  (mm)",         "bw",  bw_init or "300", "mm")
        field(inp, "전체 깊이  h  (mm)",   "h",   bd_init or "600", "mm")
        field(inp, "피복 두께  cc  (mm)",  "cc",  "40",             "mm")
        field(inp, "주철근 직경  (mm)",    "db",  "22",             "mm")
        field(inp, "스터럽 직경  (mm)",    "ds",  "10",             "mm")

        sec_label(inp, "■ 재료 강도")
        field(inp, "콘크리트  fck  (MPa)", "fck", "24",             "MPa")
        field(inp, "철근 항복강도  fy  (MPa)", "fy","400",          "MPa")

        sec_label(inp, "■ 설계 하중 (계수하중)")
        field(inp, "단부(i)  Mu  (kN·m)",   "Mu_i",  "200",  "kN·m")
        field(inp, "단부(i)  Vu  (kN)",     "Vu_i",  "120",  "kN")
        field(inp, "중앙부  Mu  (kN·m)",    "Mu_c",  "140",  "kN·m")
        field(inp, "중앙부  Vu  (kN)",      "Vu_c",  "80",   "kN")
        field(inp, "단부(j)  Mu  (kN·m)",   "Mu_j",  "200",  "kN·m")
        field(inp, "단부(j)  Vu  (kN)",     "Vu_j",  "120",  "kN")

        # ── 우: 결과 패널 ─────────────────────────────────
        res_outer = tk.Frame(body, bg=BG); res_outer.pack(side="left", fill="both", expand=True)

        res = tk.Frame(res_outer, bg=BG2, bd=0,
                       highlightthickness=1, highlightbackground=BDR)
        res.pack(fill="both", expand=True, pady=4)

        tk.Label(res, text="■ 설계 결과",
                 font=("Malgun Gothic",10,"bold"), bg=BG2, fg=ACC,
                 anchor="w", padx=12, pady=8).pack(fill="x")
        tk.Frame(res, bg=BDR, height=1).pack(fill="x", padx=8)

        self._result_text = tk.Text(
            res, font=("Consolas",9), bg=BG3, fg=TXT,
            relief="flat", state="disabled",
            highlightthickness=0, padx=10, pady=8
        )
        self._result_text.pack(fill="both", expand=True, padx=8, pady=6)

        # 태그 색상
        self._result_text.tag_config("head",  foreground=ACCH, font=("Consolas",9,"bold"))
        self._result_text.tag_config("ok",    foreground="#22c55e")
        self._result_text.tag_config("warn",  foreground="#f59e0b")
        self._result_text.tag_config("err",   foreground=RED)
        self._result_text.tag_config("val",   foreground=TXT)
        self._result_text.tag_config("dim",   foreground=TX3)

        # ── 하단 버튼 ─────────────────────────────────────
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")
        btn_fr = tk.Frame(self, bg=BG2, height=46)
        btn_fr.pack(fill="x"); btn_fr.pack_propagate(False)

        def mkb(txt, cmd, bg_=ACC):
            b = tk.Button(btn_fr, text=txt, command=cmd,
                          font=("Malgun Gothic",9,"bold"),
                          bg=bg_, fg=WHI, relief="flat", cursor="hand2",
                          padx=14, pady=5)
            b.bind("<Enter>", lambda _, b=b, c=bg_: b.config(bg=_lht(c)))
            b.bind("<Leave>", lambda _, b=b, c=bg_: b.config(bg=bg_))
            b.pack(side="right", padx=6, pady=7)

        mkb("✅  결과 적용",  self._apply_result, bg_=GRN)
        mkb("⚙️  설계 실행",  self._run_design,   bg_=ACC)
        mkb("✖  닫기",        self.destroy,        bg_="#374151")

    # ── 설계 계산 ─────────────────────────────────────────
    def _run_design(self):
        try:
            bw  = float(self._vars["bw"].get())
            h   = float(self._vars["h"].get())
            cc  = float(self._vars["cc"].get())
            db  = float(self._vars["db"].get())
            ds  = float(self._vars["ds"].get())
            fck = float(self._vars["fck"].get())
            fy  = float(self._vars["fy"].get())

            d = h - cc - ds - db / 2.0   # 유효깊이 (mm)

            # β1 보정
            beta1 = 0.85 - 0.007 * max(0, fck - 28)
            beta1 = max(0.65, min(0.85, beta1))

            phi_b = self._PHI_B
            phi_v = self._PHI_V

            zones = [
                ("단부(i)", float(self._vars["Mu_i"].get()), float(self._vars["Vu_i"].get())),
                ("중앙부",  float(self._vars["Mu_c"].get()), float(self._vars["Vu_c"].get())),
                ("단부(j)", float(self._vars["Mu_j"].get()), float(self._vars["Vu_j"].get())),
            ]

            lines = []
            lines.append(("head", f"{'─'*48}\n"))
            lines.append(("head", f"  보 단면 설계  (KDS 14.20.20)\n"))
            lines.append(("head", f"{'─'*48}\n"))
            lines.append(("dim",  f"  b={bw:.0f}mm  h={h:.0f}mm  d={d:.1f}mm\n"))
            lines.append(("dim",  f"  fck={fck:.0f}MPa  fy={fy:.0f}MPa  β1={beta1:.3f}\n"))
            lines.append(("val",  "\n"))

            result_store = {}

            for zone_name, Mu_kNm, Vu_kN in zones:
                Mu = Mu_kNm * 1e6   # N·mm
                Vu = Vu_kN  * 1e3   # N

                lines.append(("head", f"\n  ▶ {zone_name}   Mu={Mu_kNm:.1f} kN·m   Vu={Vu_kN:.1f} kN\n"))
                lines.append(("dim",  f"  {'─'*42}\n"))

                # ── 휨 배근 ────────────────────────────────
                # Rn = Mu / (φ·b·d²)
                Rn = Mu / (phi_b * bw * d**2)   # MPa
                m  = fy / (0.85 * fck)
                # ρ = (1/m)·(1 - √(1 - 2·m·Rn/fy))
                disc = 1 - 2 * m * Rn / fy
                if disc < 0:
                    lines.append(("err", "  ❌ 단면 부족 — 깊이/폭 증가 필요\n"))
                    result_store[zone_name] = None
                    continue
                rho   = (1.0 / m) * (1 - disc**0.5)
                rho_min = max(0.25 * fck**0.5 / fy, 1.4 / fy)
                rho_max = 0.75 * (0.85 * beta1 * fck / fy) * (600 / (600 + fy))
                rho_use = max(rho, rho_min)

                if rho_use > rho_max:
                    lines.append(("err", f"  ❌ ρ={rho_use:.5f} > ρmax={rho_max:.5f} — 단면 증가 필요\n"))
                    result_store[zone_name] = None
                    continue

                As_req = rho_use * bw * d   # mm²

                # 철근 개수 결정 (db 기준)
                Ab  = 3.14159 * (db/2)**2
                n_bar = max(2, int(As_req / Ab) + (1 if As_req % Ab > 0 else 0))
                As_prov = n_bar * Ab
                status_m = "ok" if As_prov >= As_req else "warn"

                lines.append(("val",  f"  휨:  As,req={As_req:.1f} mm²  →  {n_bar}-{int(db):d}φ  (As={As_prov:.1f} mm²)\n"))
                if rho < rho_min:
                    lines.append(("dim", f"         (최솟값 ρmin={rho_min:.5f} 적용)\n"))

                # ── 전단 배근 ──────────────────────────────
                # Vc = (1/6)·√fck·bw·d  (KDS 14.20.22 식 간략화)
                Vc = (1/6) * fck**0.5 * bw * d   # N
                Vs_req = Vu / phi_v - Vc

                if Vs_req <= 0:
                    # 최소 스터럽
                    s_req = min(d/2, 600)
                    stir_tag = "ok"
                    stir_note = "(최소 스터럽)"
                else:
                    # Av = 2·As,stir
                    Av = 2 * 3.14159 * (ds/2)**2
                    s_req = phi_v * Av * fy * d / (Vu - phi_v * Vc)
                    s_req = min(s_req, d/2, 600)
                    stir_tag = "ok" if s_req > 0 else "err"
                    stir_note = ""

                s_use = int(s_req / 50) * 50  # 50mm 단위 내림
                s_use = max(s_use, 100)

                lines.append((stir_tag, f"  전단:  Vc={Vc/1e3:.1f} kN  →  {int(ds):d}φ @ {s_use} mm  {stir_note}\n"))

                # 접두사 선택 (fy 기준)
                pfx = "UHD" if fy >= 600 else ("SHD" if fy >= 500 else "HD")   # SD400=HD, SD500=SHD, SD600=UHD
                result_store[zone_name] = {
                    "top":  f"{n_bar}-{pfx}{int(db)}",
                    "bot":  f"{n_bar}-{pfx}{int(db)}",
                    "stir": f"{pfx}{int(ds)}@{s_use}",
                    "As_req": As_req, "As_prov": As_prov,
                    "Vc": Vc, "s_use": s_use,
                }

            lines.append(("dim", f"\n  {'─'*48}\n"))
            lines.append(("ok",  "  ✔ 계산 완료. [결과 적용] 버튼으로 행에 반영하세요.\n"))

            self._result = result_store

            # 결과 텍스트 출력
            self._result_text.config(state="normal")
            self._result_text.delete("1.0", "end")
            for tag, txt in lines:
                self._result_text.insert("end", txt, tag)
            self._result_text.config(state="disabled")

        except ValueError as e:
            messagebox.showerror("입력 오류", f"숫자를 입력하세요.\n{e}", parent=self)

    # ── 결과 적용 ─────────────────────────────────────────
    def _apply_result(self):
        """설계 결과를 AutoTable 행 rv에 반영"""
        if not self._result:
            messagebox.showwarning("알림", "먼저 [설계 실행]을 클릭하세요.", parent=self)
            return

        mapping = {
            "단부(i)": ("em_top",  "em_bot",  "em_stir"),
            "중앙부":  ("cen_top", "cen_bot", "cen_stir"),
            "단부(j)": ("ev_top",  "ev_bot",  "ev_stir"),
        }

        applied = []
        for zone_name, keys in mapping.items():
            res = self._result.get(zone_name)
            if not res: continue
            top_k, bot_k, stir_k = keys
            for k, val in [(top_k, res["top"]), (bot_k, res["bot"]), (stir_k, res["stir"])]:
                widget = self.parent_rv.get(k)
                if widget and hasattr(widget, "set"):
                    widget.set(val)
                    applied.append(k)

        if applied and self.on_apply:
            self.on_apply()
        if applied:
            messagebox.showinfo("적용 완료",
                f"설계 결과가 행에 반영되었습니다.\n적용 항목: {', '.join(applied)}",
                parent=self)
        else:
            messagebox.showwarning("알림", "적용할 결과가 없습니다.", parent=self)

    def _center(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        w  = self.winfo_width();       h  = self.winfo_height()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")
