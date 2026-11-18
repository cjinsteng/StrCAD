"""
design_2d/section/result_tab.py — 결과 탭 (표 + 선택 부재 상세 그래프)
"""

import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .solver import elem_extremes
from .theme import *

TABLES = ["반력", "부재력 (양단)", "부재 최대값", "절점 변위"]


class ResultTabMixin:

    def _build_result_tab(self, nb):
        f = tk.Frame(nb, bg=BG2)
        nb.add(f, text=" 결과 ")
        self.tab_result = f
        self._res_keys = []

        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x", padx=8, pady=(8, 4))
        self.lbl_res = tk.Label(top, text="해석 결과 없음", font=FONT_B, bg=BG2, fg=TX2)
        self.lbl_res.pack(side="left")
        btn(top, "CSV", self._export_csv, padx=6, pady=1).pack(side="right")

        tf = tk.Frame(f, bg=BG2)
        tf.pack(fill="x", padx=8)
        self.v_table = tk.StringVar(value=TABLES[0])
        for name in TABLES:
            tk.Radiobutton(tf, text=name.split(" ")[0] if len(name) > 6 else name,
                           variable=self.v_table, value=name, indicatoron=0,
                           command=self.refresh_result_tables, bg=BG3, fg=TXT,
                           selectcolor=ACC, activebackground=BG5, font=FONT_S,
                           relief="flat", bd=0, padx=6, pady=3, highlightthickness=0,
                           cursor="hand2").pack(side="left", padx=1, fill="x", expand=True)

        wrap = tk.Frame(f, bg=BG2)
        wrap.pack(fill="both", expand=True, padx=6, pady=4)
        self.res_tbl = ttk.Treeview(wrap, show="headings", style="Tbl.Treeview",
                                    selectmode="browse")
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.res_tbl.yview)
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=self.res_tbl.xview)
        self.res_tbl.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.res_tbl.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1); wrap.columnconfigure(0, weight=1)
        self.res_tbl.tag_configure("sum", foreground=C_SEL)
        self.res_tbl.bind("<<TreeviewSelect>>", self._on_res_tbl_select)

        tk.Frame(f, bg=BDR, height=1).pack(fill="x", padx=6)
        self.lbl_detail = tk.Label(f, text="부재를 선택하면 M·V·N 그래프가 표시됩니다",
                                   font=FONT_B, bg=BG2, fg=TX2, anchor="w")
        self.lbl_detail.pack(fill="x", padx=8, pady=(6, 2))
        self.detail_cv = tk.Canvas(f, bg=CANV_BG, height=250, highlightthickness=0)
        self.detail_cv.pack(fill="x", padx=6, pady=(0, 8))
        self.detail_cv.bind("<Configure>", lambda e: self.refresh_result_detail())

    # ════════════════════════════════════════════════════════
    def _res_name(self, key):
        kind, i = key
        if kind == "case":
            cs = self.model["cases"].get(i, {})
            return f"[LC] {cs.get('name', i)}"
        co = self.model["combos"].get(i, {})
        return f"[조합] {co.get('name', i)}"

    def refresh_result_list(self):
        if not hasattr(self, "res_combo"):
            return
        if not self.results:
            self._res_keys = []
            self.res_combo.config(values=[])
            self.res_combo_var.set("")
            if hasattr(self, "lbl_res"):
                self.lbl_res.config(text="해석 결과 없음 — ▶ 해석 실행 (F5)", fg=TX2)
                self.res_tbl.delete(*self.res_tbl.get_children())
                self.refresh_result_detail()
            return
        self._res_keys = list(self.results.keys())
        self.res_combo.config(values=[self._res_name(k) for k in self._res_keys])
        if self.res_key in self.results:
            self.res_combo_var.set(self._res_name(self.res_key))
            self.lbl_res.config(text=f"결과: {self._res_name(self.res_key)}", fg=GRNH)

    def _on_res_combo(self, e=None):
        name = self.res_combo_var.get()
        for k in self._res_keys:
            if self._res_name(k) == name:
                self.res_key = k
        if self.results and not self.res_type.get():
            self.res_type.set("M")
        self.refresh_result_list()
        self.refresh_result_tables()
        self.redraw()

    def _cur_result(self):
        if not self.results or self.res_key not in self.results:
            return None
        return self.results[self.res_key]

    # ── 표 ──────────────────────────────────────────────────
    def _table_data(self):
        res = self._cur_result()
        if not res:
            return [], []
        m = self.model
        tb = self.v_table.get()
        rows = []
        if tb == "반력":
            cols = [("노드", 50), ("Rx (kN)", 80), ("Ry (kN)", 80), ("Mz (kN·m)", 90)]
            sx = sy = 0.0
            for nid in sorted(res["react"]):
                rx, ry, mz = res["react"][nid]
                sx += rx; sy += ry
                rows.append(((f"N{nid}", fnum(rx), fnum(ry), fnum(mz)), ()))
            rows.append((("합계", fnum(sx), fnum(sy), ""), ("sum",)))
        elif tb.startswith("부재력"):
            cols = [("부재", 70), ("Ni", 64), ("Vi", 64), ("Mi", 70),
                    ("Nj", 64), ("Vj", 64), ("Mj", 70)]
            for eid in sorted(res["elems"]):
                er = res["elems"][eid]
                nm = m["elems"].get(eid, {}).get("name") or ""
                rows.append(((f"E{eid} {nm}".strip(), fnum(er["N"][0]), fnum(er["V"][0]), fnum(er["M"][0]),
                              fnum(er["N"][-1]), fnum(er["V"][-1]), fnum(er["M"][-1])), ("E", eid)))
        elif tb.startswith("부재 최대"):
            cols = [("부재", 70), ("M+max", 70), ("x(m)", 50), ("M-min", 70), ("x(m)", 50),
                    ("|V|max", 64), ("Nmax", 64), ("Nmin", 64)]
            for eid in sorted(res["elems"]):
                ex = elem_extremes(res["elems"][eid])
                nm = m["elems"].get(eid, {}).get("name") or ""
                rows.append(((f"E{eid} {nm}".strip(), fnum(max(ex["Mmax"][0], 0)), fnum(ex["Mmax"][1]),
                              fnum(min(ex["Mmin"][0], 0)), fnum(ex["Mmin"][1]),
                              fnum(abs(ex["Vmax"][0])), fnum(ex["Nmax"]), fnum(ex["Nmin"])), ("E", eid)))
        else:
            cols = [("노드", 50), ("dx (mm)", 80), ("dy (mm)", 80), ("rz (×10⁻³rad)", 100)]
            for nid in sorted(res["disp"]):
                ux, uy, rz = res["disp"][nid]
                rows.append(((f"N{nid}", fnum(ux * 1000, 3), fnum(uy * 1000, 3), fnum(rz * 1000, 4)), ()))
        return cols, rows

    def refresh_result_tables(self):
        if not hasattr(self, "res_tbl"):
            return
        t = self.res_tbl
        t.delete(*t.get_children())
        cols, rows = self._table_data()
        ids = [f"c{i}" for i in range(len(cols))]
        t.configure(columns=ids)
        for cid, (name, w) in zip(ids, cols):
            t.heading(cid, text=name)
            t.column(cid, width=w, anchor="e" if cid != "c0" else "w", stretch=False)
        for k, (vals, tag) in enumerate(rows):
            iid = f"E_{tag[1]}" if tag and tag[0] == "E" else f"r{k}"
            t.insert("", "end", iid=iid, values=vals, tags=tag[:1] if tag and tag[0] == "sum" else ())
        self.refresh_result_detail()

    def _on_res_tbl_select(self, e=None):
        sel = self.res_tbl.selection()
        if sel and sel[0].startswith("E_"):
            eid = int(sel[0][2:])
            if self.sel_elems != {eid}:
                self.sel_elems = {eid}; self.sel_nodes = set()
                self.redraw()
                self.show_editor()
                self.sync_tree_selection()
                self.refresh_result_detail()

    def _export_csv(self):
        cols, rows = self._table_data()
        if not rows:
            return
        p = filedialog.asksaveasfilename(parent=self.win, defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv")],
                                         initialfile=f"{self.v_table.get().split(' ')[0]}.csv")
        if not p:
            return
        try:
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([self._res_name(self.res_key)])
                w.writerow([c for c, _ in cols])
                for vals, _ in rows:
                    w.writerow(vals)
        except Exception as ex:
            messagebox.showerror("저장 실패", str(ex), parent=self.win)
            return
        self.msg(f"CSV 저장: {p}", GRNH)

    # ── 선택 부재 상세 그래프 ───────────────────────────────
    def refresh_result_detail(self):
        cv = getattr(self, "detail_cv", None)
        if cv is None:
            return
        cv.delete("all")
        res = self._cur_result()
        W, H = max(cv.winfo_width(), 200), max(cv.winfo_height(), 120)
        if not res or len(self.sel_elems) != 1:
            self.lbl_detail.config(text="부재를 선택하면 M·V·N 그래프가 표시됩니다", fg=TX2)
            cv.create_text(W / 2, H / 2, text="—", fill=TX3, font=FONT)
            return
        eid = next(iter(self.sel_elems))
        er = res["elems"].get(eid)
        if not er:
            return
        e = self.model["elems"].get(eid, {})
        ex = elem_extremes(er)
        self.lbl_detail.config(
            text=f"E{eid} {e.get('name', '')}   L={er['L']:.3f} m   "
                 f"M+ {fnum(max(ex['Mmax'][0], 0))} / M- {fnum(min(ex['Mmin'][0], 0))}   |V| {fnum(abs(ex['Vmax'][0]))}",
            fg=C_SEL)
        rows = [("M", er["M"], C_M, C_M_F, "kN·m", -1), ("V", er["V"], C_V, C_V_F, "kN", 1),
                ("N", er["N"], C_N, C_N_F, "kN", 1)]
        ph = H / 3
        x0, x1 = 34, W - 12
        xs = er["xs"]; L = er["L"] or 1
        for r, (name, vals, col, fill, unit, side) in enumerate(rows):
            top = r * ph
            mid = top + ph / 2
            vmax = max(max(abs(v) for v in vals), 1e-9)
            k = (ph / 2 - 12) / vmax
            cv.create_line(x0, mid, x1, mid, fill=TX3)
            cv.create_text(6, mid, text=name, fill=col, font=FONT_B, anchor="w")
            pts = [x0, mid]
            for x, v in zip(xs, vals):
                pts += [x0 + (x1 - x0) * x / L, mid + side * v * k]
            pts += [x1, mid]
            cv.create_polygon(pts, fill=fill, outline="")
            cv.create_line(pts[2:-2], fill=col, width=2)
            imx = max(range(len(vals)), key=lambda i: vals[i])
            imn = min(range(len(vals)), key=lambda i: vals[i])
            for i in sorted({imx, imn, 0, len(vals) - 1}):
                v = vals[i]
                if abs(v) < vmax * 1e-3:
                    continue
                px = x0 + (x1 - x0) * xs[i] / L
                py = mid + side * v * k
                anchor = "w" if i < len(vals) / 2 else "e"
                if i == 0:
                    anchor = "w"
                cv.create_text(px + (4 if anchor == "w" else -4), py + (-7 if side * v < 0 else 7),
                               text=fnum(v), fill=col, font=FONT_C, anchor=anchor)
            if r:
                cv.create_line(0, top, W, top, fill=BDR)
