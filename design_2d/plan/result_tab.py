"""
design_2d/plan/result_tab.py — 결과 탭 (반력 · 보 부재력 · 슬래브 최대값 · 처짐 표 + 선택 상세)
"""

import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np

from .solver import summary
from ..section.theme import *

TABLES = ["반력", "보", "슬래브", "처짐"]


class ResultTabMixin:

    def _build_result_tab(self, nb):
        f = tk.Frame(nb, bg=BG2)
        nb.add(f, text=" 결과 ")
        self.tab_result = f
        self._res_keys = []
        top = tk.Frame(f, bg=BG2); top.pack(fill="x", padx=8, pady=(8, 4))
        self.lbl_res = tk.Label(top, text="해석 결과 없음", font=FONT_B, bg=BG2, fg=TX2)
        self.lbl_res.pack(side="left")
        btn(top, "CSV", self._export_csv, padx=6, pady=1).pack(side="right")
        tf = tk.Frame(f, bg=BG2); tf.pack(fill="x", padx=8)
        self.v_table = tk.StringVar(value=TABLES[0])
        for name in TABLES:
            tk.Radiobutton(tf, text=name, variable=self.v_table, value=name, indicatoron=0,
                           command=self.refresh_result_tables, bg=BG3, fg=TXT, selectcolor=ACC,
                           activebackground=BG5, font=FONT_S, relief="flat", bd=0, padx=6, pady=3,
                           highlightthickness=0, cursor="hand2").pack(side="left", padx=1, fill="x", expand=True)
        wrap = tk.Frame(f, bg=BG2); wrap.pack(fill="both", expand=True, padx=6, pady=4)
        self.res_tbl = ttk.Treeview(wrap, show="headings", style="Tbl.Treeview", selectmode="browse")
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.res_tbl.yview)
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=self.res_tbl.xview)
        self.res_tbl.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.res_tbl.grid(row=0, column=0, sticky="nsew"); vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1); wrap.columnconfigure(0, weight=1)
        self.res_tbl.tag_configure("sum", foreground=C_SEL)
        self.res_tbl.bind("<<TreeviewSelect>>", self._on_res_tbl_select)
        tk.Frame(f, bg=BDR, height=1).pack(fill="x", padx=6)
        self.lbl_detail = tk.Label(f, text="보(선)를 선택하면 M·V 그래프가 표시됩니다", font=FONT_B,
                                   bg=BG2, fg=TX2, anchor="w", justify="left")
        self.lbl_detail.pack(fill="x", padx=8, pady=(6, 2))
        self.detail_cv = tk.Canvas(f, bg=CANV_BG, height=200, highlightthickness=0)
        self.detail_cv.pack(fill="x", padx=6, pady=(0, 8))
        self.detail_cv.bind("<Configure>", lambda e: self.refresh_result_detail())

    def _res_name(self, key):
        kind, i = key
        if kind == "case":
            return f"[LC] {self.model['cases'].get(i, {}).get('name', i)}"
        return f"[조합] {self.model['combos'].get(i, {}).get('name', i)}"

    def refresh_result_list(self):
        if not hasattr(self, "res_combo"):
            return
        if not self.analysis:
            self._res_keys = []
            self.res_combo.config(values=[]); self.res_combo_var.set("")
            if hasattr(self, "lbl_res"):
                self.lbl_res.config(text="해석 결과 없음 — ▶ 해석 (F5)", fg=TX2)
                self.res_tbl.delete(*self.res_tbl.get_children())
                self.refresh_result_detail()
            return
        self._res_keys = list(self.analysis["results"].keys())
        self.res_combo.config(values=[self._res_name(k) for k in self._res_keys])
        if self.res_key in self.analysis["results"]:
            self.res_combo_var.set(self._res_name(self.res_key))
            self.lbl_res.config(text=f"결과: {self._res_name(self.res_key)}", fg=GRNH)

    def _on_res_combo(self, e=None):
        for k in self._res_keys:
            if self._res_name(k) == self.res_combo_var.get():
                self.res_key = k
        if self.analysis and not self.res_type.get():
            self.res_type.set("Mx")
        self.refresh_result_list(); self.refresh_result_tables(); self.redraw()

    def _table_data(self):
        res = self._res()
        if res is None:
            return [], []
        m = self.model
        mesh = self.analysis["mesh"]
        tb = self.v_table.get()
        rows = []
        if tb == "반력":
            cols = [("지점", 70), ("Rz (kN)", 80), ("Mx (kN·m)", 80), ("My (kN·m)", 80)]
            s = 0.0
            for nid in sorted(res["react"]):
                rz, mx, my = res["react"][nid]
                s += rz
                rows.append(((f"N{nid}", fnum(rz), fnum(mx), fnum(my)), ()))
            for lid, d in sorted(res.get("line_react", {}).items()):
                s += d["Rz"]
                rows.append(((f"L{lid} (선)", fnum(d["Rz"]), "", ""), ()))
            rows.append((("합계", fnum(s), "", ""), ("sum",)))
            kind, i = self.res_key
            if kind == "case":
                rows.append((("작용 하중", fnum(self.analysis["applied"].get(i, 0)), "", ""), ("sum",)))
        elif tb == "보":
            cols = [("보", 90), ("L (m)", 50), ("M+ max", 70), ("M- min", 70), ("|V| max", 70), ("|T| max", 64)]
            _, rb = summary(res, mesh, m)
            for r in rb:
                ln = m["lines"].get(r["line"], {})
                nm = (ln.get("name") or "") + " " + m["sections"].get(ln.get("sec"), {}).get("name", "")
                rows.append(((f"L{r['line']} {nm.strip()}", fnum(r["L"]), fnum(max(r["M+"], 0)),
                              fnum(min(r["M-"], 0)), fnum(r["V"]), fnum(r["T"])), ("L", r["line"])))
        elif tb == "슬래브":
            cols = [("면", 60), ("Mx+", 62), ("Mx-", 62), ("My+", 62), ("My-", 62), ("|Qx|", 58),
                    ("|Qy|", 58), ("δmax mm", 66)]
            rs, _ = summary(res, mesh, m)
            for r in rs:
                rows.append(((f"A{r['area']}", fnum(max(r["Mx+"], 0)), fnum(min(r["Mx-"], 0)),
                              fnum(max(r["My+"], 0)), fnum(min(r["My-"], 0)),
                              fnum(max(abs(r["Qx+"]), abs(r["Qx-"]))), fnum(max(abs(r["Qy+"]), abs(r["Qy-"]))),
                              fnum(r["d"], 3)), ("A", r["area"])))
        else:
            cols = [("노드", 60), ("X", 60), ("Y", 60), ("δ (mm, ↓+)", 90)]
            for nid, k in sorted(mesh.node_of.items()):
                x, y = mesh.xy[k]
                rows.append(((f"N{nid}", fnum(x, 3), fnum(y, 3), fnum(-res["w"][k] * 1000, 3)), ()))
            if len(mesh.xy):
                k = int(np.argmin(res["w"]))
                rows.append((("최대", fnum(mesh.xy[k][0], 3), fnum(mesh.xy[k][1], 3),
                              fnum(-res["w"][k] * 1000, 3)), ("sum",)))
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
            t.column(cid, width=w, anchor="w" if cid == "c0" else "e", stretch=False)
        for k, (vals, tag) in enumerate(rows):
            iid = f"{tag[0]}_{tag[1]}" if tag and tag[0] in ("L", "A") else f"r{k}"
            t.insert("", "end", iid=iid, values=vals, tags=("sum",) if tag == ("sum",) else ())
        self.refresh_result_detail()

    def _on_res_tbl_select(self, e=None):
        s = self.res_tbl.selection()
        if not s or s[0][0] not in "LA" or "_" not in s[0]:
            return
        k, _, v = s[0].partition("_")
        kind = "line" if k == "L" else "area"
        if self.sel[kind] != {int(v)}:
            self.clear_sel(); self.sel[kind].add(int(v))
            self.redraw(); self.show_editor(); self.sync_tree_selection(); self.refresh_result_detail()

    def _export_csv(self):
        cols, rows = self._table_data()
        if not rows:
            return
        p = filedialog.asksaveasfilename(parent=self.win, defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                         initialfile=f"평면해석_{self.v_table.get()}.csv")
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
            messagebox.showerror("저장 실패", str(ex), parent=self.win); return
        self.msg(f"CSV 저장: {p}", GRNH)

    def refresh_result_detail(self):
        cv = getattr(self, "detail_cv", None)
        if cv is None:
            return
        cv.delete("all")
        res = self._res()
        W, H = max(cv.winfo_width(), 200), max(cv.winfo_height(), 100)
        if res is None:
            self.lbl_detail.config(text="보(선)를 선택하면 M·V 그래프가 표시됩니다", fg=TX2)
            return
        if len(self.sel["area"]) == 1 and not self.sel["line"]:
            aid = next(iter(self.sel["area"]))
            rs, _ = summary(res, self.analysis["mesh"], self.model)
            r = next((x for x in rs if x["area"] == aid), None)
            if r:
                self.lbl_detail.config(fg=C_SEL, text=(
                    f"A{aid}  Mx {r['Mx+']:.2f} / {r['Mx-']:.2f}   My {r['My+']:.2f} / {r['My-']:.2f} kN·m/m\n"
                    f"      Qx {max(abs(r['Qx+']), abs(r['Qx-'])):.2f}   Qy {max(abs(r['Qy+']), abs(r['Qy-'])):.2f} kN/m"
                    f"   δmax {r['d']:.3f} mm"))
            return
        if len(self.sel["line"]) != 1:
            self.lbl_detail.config(text="보(선)를 선택하면 M·V 그래프가 표시됩니다", fg=TX2)
            return
        lid = next(iter(self.sel["line"]))
        d = res["beams"].get(lid)
        if d is None:
            self.lbl_detail.config(text=f"L{lid}: 보가 아닙니다", fg=TX2); return
        self.lbl_detail.config(fg=C_SEL, text=(
            f"L{lid}  L={d['s'][-1]:.3f} m   M+ {max(d['M'].max(), 0):.2f} / M- {min(d['M'].min(), 0):.2f} kN·m"
            f"   |V| {np.abs(d['V']).max():.2f} kN   |T| {np.abs(d['T']).max():.2f}"))
        ph = H / 2
        x0, x1 = 30, W - 10
        L = d["s"][-1] or 1
        for r, (key, col, fill, side) in enumerate((("M", C_M, C_M_F, -1), ("V", C_V, C_V_F, 1))):
            mid = r * ph + ph / 2
            vals = d[key]
            vmax = max(np.abs(vals).max(), 1e-9)
            k = (ph / 2 - 12) / vmax
            cv.create_line(x0, mid, x1, mid, fill=TX3)
            cv.create_text(6, mid, text=key, fill=col, font=FONT_B, anchor="w")
            pts = [x0, mid] + [q for s_, v in zip(d["s"], vals) for q in (x0 + (x1 - x0) * s_ / L, mid + side * v * k)] + [x1, mid]
            cv.create_polygon(pts, fill=fill, outline="")
            cv.create_line(pts[2:-2], fill=col, width=2)
            for i in sorted({0, len(vals) - 1, int(np.argmax(vals)), int(np.argmin(vals))}):
                if abs(vals[i]) < vmax * 1e-3:
                    continue
                px = x0 + (x1 - x0) * d["s"][i] / L
                py = mid + side * vals[i] * k
                cv.create_text(px + (4 if i < len(vals) / 2 else -4), py + (-7 if side * vals[i] < 0 else 7),
                               text=fnum(vals[i]), fill=col, font=FONT_C,
                               anchor="w" if i < len(vals) / 2 else "e")
            if r:
                cv.create_line(0, r * ph, W, r * ph, fill=BDR)
