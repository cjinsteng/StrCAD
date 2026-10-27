"""현장조사 상세 부재입력 (INPUT) — 재료/방향, 지점·하중, 단면, 배근 → 간이 휨·전단 검토."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import check as C
from .survey_ui import RebarPickDialog, rebar_mode

BG = "#ffffff"
YEL = "#fde68a"
YEL_D = "#f59e0b"
BLUE = "#4a90d9"
BLUE_D = "#2f6db5"
OK = "#16a34a"
NG = "#dc2626"
F9 = ("Malgun Gothic", 9)
F10 = ("Malgun Gothic", 10)
FB = ("Malgun Gothic", 11, "bold")
MATS = (("RC", "철근콘크리트"), ("S", "철골"), ("SRC", "합성부재"))
DIRS = (("V", "수직 (기둥)"), ("H", "수평 (보)"))
SUPS = ("Pin", "SemiFix", "Fix")


def _f(v, d=0.0):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return d


class DetailDialog(tk.Toplevel):
    def __init__(self, master, rec, member=None, entry=None, on_save=None):
        super().__init__(master)
        self.title(f"상세 부재입력 — {rec.get('name') or '부재'} (#{rec.get('no')})")
        self.configure(bg=BG)
        self.transient(master)
        self.geometry("1060x820")
        self.minsize(900, 700)
        self.on_save = on_save
        self.rec = rec
        c = dict(rec.get("calc") or {})
        inp = c.get("inputs", {})
        kind = member.kind if member is not None else None
        if kind is None and entry:
            kind = entry.get("kind")
        self.kind = kind
        dflt_dir = "V" if kind in ("column", "wall") else "H"
        self.mat = tk.StringVar(value=c.get("mat", "RC"))
        self.dir = tk.StringVar(value=c.get("dir", dflt_dir))
        # sizes: 기록 > 부재일람 > 도면
        b = rec.get("size_b") or (entry or {}).get("b") or ""
        h = rec.get("size_h") or (entry or {}).get("h") or ""
        if member is not None and not b:
            b = round(member.b if member.kind == "column" else member.width) or ""
        if member is not None and not h:
            h = round(member.h) if member.kind == "column" else (round(member.depth) if member.depth else "")
        L = rec.get("length") or (round(member.length_cc / 1000, 2) if member is not None and member.kind != "column"
                                  else inp.get("L", ""))
        V = lambda k, d="": tk.StringVar(value=str(inp.get(k, d)))
        self.v = {"b": tk.StringVar(value=str(b)), "h": tk.StringVar(value=str(h)), "L": tk.StringVar(value=str(L)),
                  "D": V("D", "20"), "Lv": V("Lv", "10"), "fck": V("fck", "24"), "cover": V("cover", "40"),
                  "Pu": V("Pu", ""), "Mu": V("Mu", ""), "Vu": V("Vu", ""), "K": V("K", "1.0"),
                  "sec": V("sec", "H-400x200x8x13"), "grade": V("grade", "SS275"), "Lb": V("Lb", "")}
        self.sup = [inp.get("sup_i", "Fix"), inp.get("sup_j", "Fix")]
        self.rebar = dict(rec.get("rebar") or {})
        self.result = c.get("result")
        for var in self.v.values():
            var.trace_add("write", lambda *_: self._redraw())
        self._build()
        self._layout()
        if self.result:
            self._show_result(self.result)

    # ------------------------------------------------------------------ UI
    def _build(self):
        top = tk.Frame(self, bg=BG, padx=12, pady=10)
        top.pack(fill="x")
        self.mat_btn = {}
        for i, (k, t) in enumerate(MATS):
            b = tk.Button(top, text=t, font=FB, relief="solid", bd=2, width=11, command=lambda k=k: self._set_mat(k))
            b.grid(row=0, column=i, padx=4, pady=2)
            self.mat_btn[k] = b
        self.dir_btn = {}
        for i, (k, t) in enumerate(DIRS):
            b = tk.Button(top, text=t, font=FB, relief="solid", bd=2, width=11, command=lambda k=k: self._set_dir(k))
            b.grid(row=1, column=i, padx=4, pady=2)
            self.dir_btn[k] = b
        mf = tk.Frame(top, bg=BG)
        mf.grid(row=0, column=4, rowspan=2, sticky="e", padx=(30, 0))
        self.mat_rc = tk.Frame(mf, bg=BG)
        tk.Label(self.mat_rc, text="fck", bg=BG, font=F10).grid(row=0, column=0)
        ttk.Combobox(self.mat_rc, textvariable=self.v["fck"], values=("21", "24", "27", "30", "35", "40", "50"),
                     width=5).grid(row=0, column=1)
        tk.Label(self.mat_rc, text="MPa   피복", bg=BG, font=F10).grid(row=0, column=2)
        ttk.Entry(self.mat_rc, textvariable=self.v["cover"], width=5).grid(row=0, column=3)
        tk.Label(self.mat_rc, text="mm   (철근 fy: D·HD 400, SHD 500, UHD 600)", bg=BG, font=F9,
                 fg="#666").grid(row=0, column=4)
        self.mat_s = tk.Frame(mf, bg=BG)
        tk.Label(self.mat_s, text="단면", bg=BG, font=F10).grid(row=0, column=0)
        ttk.Combobox(self.mat_s, textvariable=self.v["sec"], values=list(C.H_SECTIONS), width=20,
                     state="readonly").grid(row=0, column=1)
        tk.Label(self.mat_s, text="강종", bg=BG, font=F10).grid(row=0, column=2, padx=(8, 0))
        ttk.Combobox(self.mat_s, textvariable=self.v["grade"], values=list(C.STEEL_GRADES), width=8,
                     state="readonly").grid(row=0, column=3)
        self.mat_note = tk.Label(mf, text="", bg=BG, fg="#b45309", font=F9)

        mid = tk.Frame(self, bg=BG, padx=12)
        mid.pack(fill="x")
        self.cv = tk.Canvas(mid, width=600, height=230, bg=BG, highlightthickness=0)
        self.cv.grid(row=0, column=0, rowspan=2, sticky="nw")
        self.cv.bind("<Button-1>", self._cv_click)
        side = tk.Frame(mid, bg=BG)
        side.grid(row=0, column=1, sticky="nw", padx=(16, 0), pady=(10, 0))
        self.side = side

        self.sec_fr = tk.Frame(self, bg=BG, padx=12)
        self.sec_fr.pack(fill="x", pady=(4, 0))

        bot = tk.Frame(self, bg=BG, padx=12, pady=6)
        bot.pack(fill="both", expand=True)
        self.res_tv = ttk.Treeview(bot, columns=("item", "req", "cap", "ratio", "ok", "note"), show="headings",
                                   height=6)
        for c, t, w in (("item", "검토 항목", 200), ("req", "소요 (Mu·Vu·Pu)", 110), ("cap", "설계강도 (φ)", 110),
                        ("ratio", "비율", 60), ("ok", "판정", 60), ("note", "비고", 400)):
            self.res_tv.heading(c, text=t)
            self.res_tv.column(c, width=w, anchor="w" if c in ("item", "note") else "center")
        self.res_tv.tag_configure("ng", foreground=NG)
        self.res_tv.tag_configure("ok", foreground=OK)
        self.res_tv.pack(side="left", fill="both", expand=True)
        btns = tk.Frame(bot, bg=BG)
        btns.pack(side="right", fill="y", padx=(10, 0))
        tk.Button(btns, text="입력", font=("Malgun Gothic", 13, "bold"), width=8, relief="solid", bd=2,
                  command=self._save).pack(pady=(0, 10))
        tk.Button(btns, text="계산", font=("Malgun Gothic", 13, "bold"), width=8, relief="solid", bd=2,
                  command=self._calc).pack()
        self.sum_lbl = tk.Label(self, text="", bg=BG, font=("Malgun Gothic", 12, "bold"), anchor="w", padx=14)
        self.sum_lbl.pack(fill="x", pady=(0, 8))
        tk.Label(self, bg=BG, fg="#888", font=("Malgun Gothic", 8), anchor="w", padx=14, justify="left", text=(
            "간이 검토: 등분포하중 단경간 (지점 고정도 핀 0 · 반고정 0.5 · 고정 1), 계수하중 max(1.4D, 1.2D+1.6L). "
            "RC: KDS 14 20 20/22 (단철근, 받침부 전단은 지점값 사용).  철골: KDS 41 30 10 (Cb=1). "
            "현장조사 판단 참고용이며 설계 검토를 대신하지 않습니다.")).pack(fill="x", pady=(0, 6))

    def _set_mat(self, k):
        self.mat.set(k)
        self._clear_result()
        self._layout()

    def _set_dir(self, k):
        self.dir.set(k)
        self._clear_result()
        self._layout()

    def _clear_result(self):
        self.result = None
        self.res_tv.delete(*self.res_tv.get_children())
        self.sum_lbl.config(text="계산을 누르면 검토 결과가 나옵니다.", fg="#555")

    def _entry(self, parent, label, key, unit, row, width=8):
        tk.Label(parent, text=label, bg=BG, font=FB).grid(row=row, column=0, sticky="e", pady=3)
        e = tk.Entry(parent, textvariable=self.v[key], width=width, font=("Malgun Gothic", 12), bg=YEL,
                     relief="solid", bd=1, justify="center")
        e.grid(row=row, column=1, padx=6, pady=3)
        tk.Label(parent, text=unit, bg=BG, font=F10).grid(row=row, column=2, sticky="w")
        return e

    def _layout(self):
        mat, dr = self.mat.get(), self.dir.get()
        for k, b in self.mat_btn.items():
            b.config(bg="#bfdbfe" if k == mat else BG)
        for k, b in self.dir_btn.items():
            b.config(bg="#bfdbfe" if k == dr else BG)
        self.mat_rc.grid_forget()
        self.mat_s.grid_forget()
        self.mat_note.grid_forget()
        if mat == "RC":
            self.mat_rc.grid(row=0, column=0, sticky="w")
        else:
            self.mat_s.grid(row=0, column=0, sticky="w")
            if mat == "SRC":
                self.mat_note.config(text="합성부재: 철골 단면으로 보수적 검토 (슬래브 합성효과·피복콘크리트 미반영)")
                self.mat_note.grid(row=1, column=0, sticky="w")
        for w in self.side.winfo_children():
            w.destroy()
        r = 0
        if mat == "RC":
            self._entry(self.side, "B :", "b", "mm (폭)", r); r += 1
            self._entry(self.side, "H :", "h", "mm (춤)", r); r += 1
        self._entry(self.side, "L :", "L", "m (길이)", r); r += 1
        if dr == "H":
            self._entry(self.side, "고정 D :", "D", "kN/m", r); r += 1
            self._entry(self.side, "활 L :", "Lv", "kN/m", r); r += 1
            if mat != "RC":
                self._entry(self.side, "Lb :", "Lb", "m (횡지지, 빈칸=L)", r); r += 1
        else:
            self._entry(self.side, "Pu :", "Pu", "kN (계수축력)", r); r += 1
            self._entry(self.side, "Mu :", "Mu", "kN·m", r); r += 1
            if mat == "RC":
                self._entry(self.side, "Vu :", "Vu", "kN", r); r += 1
            else:
                self._entry(self.side, "K :", "K", "(유효길이계수)", r); r += 1
        self._build_sections()
        self._redraw()

    # ------------------------------------------------------------------ section grid (I단 / 중앙 / J단)
    def _rows_cols(self):
        if self.dir.get() == "V":
            return ["주근", "띠철근"], ["단부", "중앙"]
        return ["상부근", "하부근", "스터럽"], ["I단", "중앙", "J단"]

    def _build_sections(self):
        for w in self.sec_fr.winfo_children():
            w.destroy()
        self.sec_cv = {}
        self.cell = {}
        if self.mat.get() != "RC":
            tk.Label(self.sec_fr, bg=BG, fg="#555", font=F10, text="철골 단면은 위에서 규격을 선택합니다 (배근 입력 없음).").pack(
                anchor="w", pady=10)
            return
        rows, cols = self._rows_cols()
        g = tk.Frame(self.sec_fr, bg=BG)
        g.pack(anchor="w")
        for j, c in enumerate(cols):
            tk.Label(g, text=c, bg=BG, font=FB).grid(row=0, column=j + 1, pady=(2, 0))
            cv = tk.Canvas(g, width=150, height=140, bg=BG, highlightthickness=0)
            cv.grid(row=1, column=j + 1, padx=14)
            self.sec_cv[c] = cv
        for i, r in enumerate(rows):
            tk.Label(g, text={"상부근": "상", "하부근": "하", "스터럽": "스트럽"}.get(r, r), bg=BG,
                     font=FB).grid(row=2 + i, column=0, sticky="e", padx=(0, 6))
            for j, c in enumerate(cols):
                key = f"{r}|{c}"
                b = tk.Button(g, text=self.rebar.get(key) or "선택", font=F10, width=14, bg=YEL, relief="solid", bd=1,
                              activebackground=YEL_D, command=lambda r=r, c=c: self._pick(r, c))
                b.grid(row=2 + i, column=j + 1, padx=14, pady=3)
                self.cell[key] = b
        tk.Label(g, text="⟵ 배근", bg=BG, fg=NG, font=FB).grid(row=2, column=len(cols) + 1, rowspan=len(rows),
                                                             padx=10)
        ttk.Button(g, text="중앙 → 양단 복사", command=self._copy_mid).grid(row=2 + len(rows), column=1, sticky="w",
                                                                    pady=(4, 0))

    def _copy_mid(self):
        rows, cols = self._rows_cols()
        mid = "중앙"
        for r in rows:
            v = self.rebar.get(f"{r}|{mid}")
            if not v:
                continue
            for c in cols:
                if c != mid and not self.rebar.get(f"{r}|{c}"):
                    self.rebar[f"{r}|{c}"] = v
        self._build_sections()
        self._redraw()

    def _pick(self, r, c):
        key = f"{r}|{c}"

        def done(v):
            if v:
                self.rebar[key] = v
            else:
                self.rebar.pop(key, None)
            self.cell[key].config(text=v or "선택")
            self._redraw()
        RebarPickDialog(self, f"{r} — {c}", self.rebar.get(key, ""), rebar_mode(r), done)

    # ------------------------------------------------------------------ drawing
    def _redraw(self):
        if not hasattr(self, "cv"):
            return
        cv = self.cv
        cv.delete("all")
        if self.dir.get() == "H":
            self._draw_beam(cv)
        else:
            self._draw_col(cv)
        for c, scv in getattr(self, "sec_cv", {}).items():
            self._draw_section(scv, c)

    def _sup_box(self, cv, x, y, idx):
        s = self.sup[idx]
        cv.create_rectangle(x - 26, y - 34, x + 26, y + 34, fill=YEL, outline=YEL_D, width=2, tags=(f"sup{idx}",))
        if s == "Pin":
            cv.create_polygon(x, y - 6, x - 14, y + 16, x + 14, y + 16, fill="white", outline="#333",
                              tags=(f"sup{idx}",))
        elif s == "Fix":
            for k in range(-24, 25, 8):
                cv.create_line(x - 6, y + k, x + 6, y + k - 8, fill="#333", tags=(f"sup{idx}",))
            cv.create_line(x, y - 30, x, y + 30, width=3, fill="#333", tags=(f"sup{idx}",))
        else:
            cv.create_oval(x - 10, y - 10, x + 10, y + 10, outline="#333", width=2, tags=(f"sup{idx}",))
            cv.create_line(x, y - 30, x, y + 30, width=1, dash=(3, 2), fill="#333", tags=(f"sup{idx}",))
        cv.create_text(x, y + 46, text=f"{s}\n({C.SUPPORT_KO[s]})", font=F9, tags=(f"sup{idx}",))

    def _draw_beam(self, cv):
        x0, x1, y = 70, 500, 120
        cv.create_rectangle(x0 + 30, y - 9, x1 - 30, y + 9, outline="#111", width=2)
        self._sup_box(cv, x0, y, 0)
        self._sup_box(cv, x1, y, 1)
        cx = (x0 + x1) / 2
        cv.create_rectangle(cx - 90, 22, cx + 90, 52, fill=YEL, outline=YEL_D, width=2, tags=("load",))
        cv.create_text(cx, 37, text=f"하중  D={self.v['D'].get()}  L={self.v['Lv'].get()} kN/m", font=F10,
                       tags=("load",))
        for k in range(9):
            xx = x0 + 40 + k * (x1 - x0 - 80) / 8
            cv.create_line(xx, 66, xx, y - 12, arrow="last", fill="#dc2626")
        cv.create_line(x0 + 30, 66, x1 - 30, 66, fill="#dc2626")
        cv.create_text(cx, y + 30, text=f"L = {self.v['L'].get() or '?'} m", font=F10)
        cv.create_text(x1 + 50, 22, text="지점 상자를 누르면\nPin → SemiFix → Fix", font=F9, fill="#555")
        if self.mat.get() == "RC":
            cv.create_text(cx, 210, text=f"B {self.v['b'].get() or '?'} × H {self.v['h'].get() or '?'} mm",
                           font=FB)
        else:
            cv.create_text(cx, 210, text=f"{self.v['sec'].get()}  {self.v['grade'].get()}", font=FB)

    def _draw_col(self, cv):
        x, y0, y1 = 200, 50, 190
        cv.create_rectangle(x - 14, y0, x + 14, y1, outline="#111", width=2)
        cv.create_rectangle(x - 90, 8, x + 90, 34, fill=YEL, outline=YEL_D, width=2)
        cv.create_text(x, 21, text=f"Pu={self.v['Pu'].get() or '?'} kN  Mu={self.v['Mu'].get() or '?'} kN·m",
                       font=F10)
        cv.create_line(x, 34, x, y0, arrow="last", width=2, fill="#dc2626")
        for k in range(-40, 41, 10):
            cv.create_line(x + k, y1 + 4, x + k - 8, y1 + 14, fill="#333")
        cv.create_line(x - 44, y1 + 2, x + 44, y1 + 2, width=3)
        cv.create_text(x + 40, (y0 + y1) / 2, text=f"L = {self.v['L'].get() or '?'} m", font=F10, anchor="w")
        if self.mat.get() == "RC":
            cv.create_text(x + 150, 80, anchor="w", font=F10,
                           text=f"b {self.v['b'].get() or '?'} × h {self.v['h'].get() or '?'} mm\n"
                                f"(b = 휨방향 폭, h = 휨방향 춤)")
        else:
            cv.create_text(x + 150, 80, anchor="w", font=F10,
                           text=f"{self.v['sec'].get()}  {self.v['grade'].get()}  K={self.v['K'].get()}")
        if self.kind == "wall":
            cv.create_text(x + 150, 170, anchor="w", text="벽체는 상세 검토를 지원하지 않습니다 (치수·배근 기록만)",
                           fill=NG, font=F9)

    def _draw_section(self, cv, col):
        cv.delete("all")
        b, h = _f(self.v["b"].get(), 400), _f(self.v["h"].get(), 600)
        if b <= 0 or h <= 0:
            return
        k = min(120 / b, 120 / h)
        w, hh = b * k, h * k
        x0, y0 = 75 - w / 2, 70 - hh / 2
        cv.create_rectangle(x0, y0, x0 + w, y0 + hh, outline="#111", width=2, fill="#f3f4f6")
        cvr = 40 * k + 4
        cv.create_rectangle(x0 + cvr - 2, y0 + cvr - 2, x0 + w - cvr + 2, y0 + hh - cvr + 2, outline="#9ca3af")

        def dots(n, yy):
            if not n:
                return
            for i in range(n):
                xx = x0 + cvr + 3 + (w - 2 * cvr - 6) * (i / (n - 1) if n > 1 else 0.5)
                cv.create_oval(xx - 4, yy - 4, xx + 4, yy + 4, fill="#111")
        if self.dir.get() == "H":
            for key, yy in ((f"상부근|{col}", y0 + cvr + 3), (f"하부근|{col}", y0 + hh - cvr - 3)):
                p = C.parse_bar(self.rebar.get(key, ""))
                dots(min(p[0], 12) if p and p[0] else 0, yy)
        else:
            p = C.parse_bar(self.rebar.get(f"주근|{col}", "") or self.rebar.get("주근|단부", ""))
            n = p[0] if p and p[0] else 0
            dots(n // 2 + n % 2, y0 + cvr + 3)
            dots(n // 2, y0 + hh - cvr - 3)

    def _cv_click(self, e):
        tags = set()
        for it in self.cv.find_overlapping(e.x - 2, e.y - 2, e.x + 2, e.y + 2):
            tags.update(self.cv.gettags(it))
        for t in sorted(tags):
            if t.startswith("sup"):
                i = int(t[3:])
                self.sup[i] = SUPS[(SUPS.index(self.sup[i]) + 1) % 3]
                self._redraw()
                return

    # ------------------------------------------------------------------ calc / save
    def _inputs(self):
        d = {k: v.get() for k, v in self.v.items()}
        d.update(sup_i=self.sup[0], sup_j=self.sup[1])
        return d

    def _run(self):
        mat, dr = self.mat.get(), self.dir.get()
        i = self._inputs()
        L = _f(i["L"])
        if L <= 0:
            raise ValueError("길이 L(m)을 입력하세요.")
        if dr == "H":
            w = C.factored_w(_f(i["D"]), _f(i["Lv"]))
            if mat == "RC":
                b, h = _f(i["b"]), _f(i["h"])
                if b <= 0 or h <= 0:
                    raise ValueError("B, H를 입력하세요.")
                lines, F = C.rc_beam_check(b, h, L, w, self.sup[0], self.sup[1], self.rebar, _f(i["fck"], 24),
                                           _f(i["cover"], 40))
            else:
                lines, F = C.steel_beam_check(i["sec"], C.STEEL_GRADES[i["grade"]], L, w, self.sup[0], self.sup[1],
                                              _f(i["Lb"]) or None)
            head = (f"wu = {w:.1f} kN/m · M(I) {F['Mi']:.1f} · M(+) {F['Mpos']:.1f} · M(J) {F['Mj']:.1f} kN·m · "
                    f"V(I) {F['Vi']:.1f} · V(J) {F['Vj']:.1f} kN")
        else:
            if self.kind == "wall":
                raise ValueError("벽체는 상세 검토를 지원하지 않습니다.")
            Pu, Mu = _f(i["Pu"]), _f(i["Mu"])
            if mat == "RC":
                b, h = _f(i["b"]), _f(i["h"])
                main = self.rebar.get("주근|단부") or self.rebar.get("주근|중앙", "")
                tie = self.rebar.get("띠철근|단부") or self.rebar.get("띠철근|중앙", "")
                if not main:
                    raise ValueError("주근(예: 8-HD22)을 입력하세요.")
                lines, _ = C.rc_column_check(b, h, Pu, Mu, _f(i["Vu"]), main, tie, _f(i["fck"], 24),
                                             _f(i["cover"], 40))
            else:
                lines = C.steel_column_check(i["sec"], C.STEEL_GRADES[i["grade"]], L, _f(i["K"], 1.0), Pu, Mu)
            head = f"Pu = {Pu:.1f} kN · Mu = {Mu:.1f} kN·m"
        ok, summ = C.summarize(lines)
        rows = [[l[0], round(l[1], 1), round(l[2], 1), round(l[3], 2) if l[3] != float("inf") else "∞",
                 "O.K" if l[4] else "N.G", l[5]] for l in lines]
        return {"ok": ok, "summary": summ, "head": head, "rows": rows}

    def _show_result(self, r):
        self.res_tv.delete(*self.res_tv.get_children())
        for row in r.get("rows", []):
            self.res_tv.insert("", "end", values=row, tags=("ok" if row[4] == "O.K" else "ng",))
        self.sum_lbl.config(text=f"{'✔' if r.get('ok') else '✘'} {r.get('summary', '')}     {r.get('head', '')}",
                            fg=OK if r.get("ok") else NG)

    def _calc(self):
        try:
            self.result = self._run()
        except (ValueError, KeyError) as e:
            self.sum_lbl.config(text=f"입력 확인: {e}", fg=NG)
            return None
        self._show_result(self.result)
        return self.result

    def _save(self):
        r = self._calc()
        i = self._inputs()
        upd = {"rebar": dict(self.rebar), "length": i["L"],
               "calc": {"mat": self.mat.get(), "dir": self.dir.get(), "inputs": i, "result": r}}
        if self.mat.get() == "RC":
            upd["size_b"], upd["size_h"] = i["b"], i["h"]
        else:
            H, B, *_ = C.H_SECTIONS[i["sec"]]
            upd["size_b"], upd["size_h"] = str(B), str(H)
        if self.on_save:
            self.on_save(upd)
        self.destroy()
