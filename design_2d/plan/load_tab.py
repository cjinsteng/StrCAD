"""
design_2d/plan/load_tab.py — 하중 탭: 집중(노드) · 선하중(선) · 면하중(면), 모두 중력방향(↓) +
"""

import tkinter as tk
from tkinter import ttk, messagebox

from . import model as pm
from ..section.theme import *
from .tree_tab import load_text

KINDS = {"node": ("집중하중 (노드)", "NL", "nloads", "node"),
         "line": ("선하중 (선)", "LL", "lloads", "line"),
         "area": ("면하중 (면)", "AL", "aloads", "area")}


class LoadTabMixin:

    def _build_load_tab(self, nb):
        f = tk.Frame(nb, bg=BG2)
        nb.add(f, text=" 하중 ")
        self.tab_load = f
        self.sel_load_ids = set()
        self.lv = {k: tk.StringVar(value=v) for k, v in (("p", "50"), ("w1", "10"), ("w2", "10"), ("q", "5"))}
        self.lv_replace = tk.BooleanVar(value=False)
        self.load_kind = tk.StringVar(value="area")

        top = tk.Frame(f, bg=BG2); top.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(top, text="하중케이스", font=FONT_B, bg=BG2, fg=C_LOAD).pack(side="left")
        self.v_case = tk.StringVar()
        self.cb_case = combo(top, self.v_case, [], 14)
        self.cb_case.pack(side="left", padx=6)
        self.cb_case.bind("<<ComboboxSelected>>", lambda e: self.set_active_case(self._id_of(self.v_case.get())))
        btn(top, "＋", lambda: self.tree_add("CASE"), padx=6).pack(side="left")

        kf = tk.Frame(f, bg=BG2); kf.pack(fill="x", padx=8, pady=(8, 2))
        for code in ("node", "line", "area"):
            tk.Radiobutton(kf, text=KINDS[code][0], variable=self.load_kind, value=code, indicatoron=0,
                           command=self._on_load_kind, bg=BG3, fg=TXT, selectcolor="#7c5a00",
                           activebackground=BG5, activeforeground=WHI, font=FONT_B, relief="flat",
                           bd=0, padx=6, pady=4, highlightthickness=0, cursor="hand2").pack(
                side="left", padx=1, fill="x", expand=True)
        self.load_form = tk.Frame(f, bg=BG2)
        self.load_form.pack(fill="x", padx=8, pady=4)
        check(f, "같은 케이스의 기존 하중 대체", self.lv_replace).pack(anchor="w", padx=8)
        bf = tk.Frame(f, bg=BG2); bf.pack(fill="x", padx=8, pady=6)
        btn(bf, "선택 항목에 적용", self.apply_load_selected, bg=ACC, fg=WHI, font=FONT_B,
            padx=10, pady=4).pack(side="left", padx=(0, 4))
        btn(bf, "⬇ 클릭 입력 모드", self._load_click_mode, bg="#7c5a00", fg=WHI, font=FONT_B,
            padx=10, pady=4).pack(side="left")
        tk.Frame(f, bg=BDR, height=1).pack(fill="x", padx=6, pady=(4, 2))
        lh = tk.Frame(f, bg=BG2); lh.pack(fill="x", padx=8, pady=(4, 2))
        self.lbl_loads = tk.Label(lh, text="하중 목록", font=FONT_B, bg=BG2, fg=WHI)
        self.lbl_loads.pack(side="left")
        btn(lh, "삭제", self._delete_list_loads, fg=RED, padx=6, pady=1).pack(side="right")
        wrap = tk.Frame(f, bg=BG2); wrap.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        t = ttk.Treeview(wrap, columns=("d",), show="tree", style="Works.Treeview", selectmode="extended")
        t.column("#0", width=0, stretch=False); t.column("d", width=300, stretch=True)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=vs.set)
        t.pack(side="left", fill="both", expand=True); vs.pack(side="right", fill="y")
        t.bind("<<TreeviewSelect>>", self._on_load_list_select)
        t.bind("<Double-1>", self._on_load_list_dbl)
        t.bind("<Delete>", lambda e: self._delete_list_loads())
        self.load_list = t
        self._on_load_kind()

    def _on_load_kind(self):
        for w in self.load_form.winfo_children():
            w.destroy()
        k = self.load_kind.get()
        f = Form(self.load_form, lw=11)
        if k == "node":
            f.row("P", lambda p: entry(p, self.lv["p"], 10), "kN (↓ +)")
            hint = "노드에 작용. 슬래브 안의 노드(메시 절점이 아님)는 형상함수로 분배"
        elif k == "line":
            f.row("w1 (i단)", lambda p: entry(p, self.lv["w1"], 10), "kN/m (↓ +)")
            f.row("w2 (j단)", lambda p: entry(p, self.lv["w2"], 10), "kN/m")
            hint = "보 선 → 보 부재하중 · 슬래브 변/내부 → 슬래브 · 그 외 → 양 끝 노드"
        else:
            f.row("q", lambda p: entry(p, self.lv["q"], 10), "kN/m² (↓ +)")
            hint = "슬래브 면 → 슬래브에 분포 · 비구조 면 → 둘레 선으로 전달 (2방향/1방향)"
        tk.Label(self.load_form, text=hint, font=FONT_S, bg=BG2, fg=TX3, justify="left",
                 wraplength=320).pack(anchor="w", pady=(4, 0))

    def _load_click_mode(self):
        self.mode.set("load")
        self._on_mode()
        self.msg(f"하중 모드: {KINDS[self.load_kind.get()][0].split(' (')[1].rstrip(')')}을(를) 클릭하세요", C_LOAD)

    def set_active_case(self, cid):
        if cid not in self.model["cases"]:
            return
        self.active_case = cid
        self.refresh_load_tab(); self.refresh_tree(); self.redraw()

    def refresh_load_tab(self):
        if not hasattr(self, "cb_case"):
            return
        m = self.model
        if self.active_case not in m["cases"] and m["cases"]:
            self.active_case = min(m["cases"])
        self.cb_case.config(values=self._names("cases"))
        self.v_case.set(self._pick("cases", self.active_case))
        t = self.load_list
        t.delete(*t.get_children())
        n = 0
        for code in ("node", "line", "area"):
            _, k, key, _ = KINDS[code]
            for ld in m[key]:
                if ld["case"] == self.active_case:
                    t.insert("", "end", iid=f"{k}_{ld['id']}", values=(load_text(k, ld),)); n += 1
        cs = m["cases"].get(self.active_case, {})
        self.lbl_loads.config(text=f"하중 목록 — {cs.get('name', '')} ({n})")

    def _on_load_list_select(self, e=None):
        self.sel_load_ids = {int(i.split("_")[1]) for i in self.load_list.selection()}
        self.redraw()

    def _on_load_list_dbl(self, e=None):
        s = self.load_list.selection()
        if s:
            k, _, v = s[0].partition("_")
            self.edit_target = (k, int(v)); self.show_editor(); self.nb.select(self.tab_input)

    def _delete_list_loads(self):
        s = self.load_list.selection()
        if not s:
            return
        self.push_undo()
        for iid in s:
            k, _, v = iid.partition("_")
            key = {"NL": "nloads", "LL": "lloads", "AL": "aloads"}[k]
            self.model[key] = [ld for ld in self.model[key] if ld["id"] != int(v)]
        self.sel_load_ids = set()
        self.changed(f"하중 {len(s)}개 삭제")

    def apply_load_selected(self):
        k = self.load_kind.get()
        tg = [(k, i) for i in sorted(self.sel[k])]
        if not tg:
            messagebox.showinfo("하중", f"먼저 캔버스에서 {KINDS[k][0].split('(')[1].rstrip(')')}을(를) 선택하세요.\n"
                                        "(또는 [⬇ 클릭 입력 모드])", parent=self.win)
            return
        self.apply_load_to(tg)

    def apply_load_to(self, targets):
        k = self.load_kind.get()
        targets = [t for t in targets if t[0] == k]
        if not targets:
            self.msg(f"{KINDS[k][0]} 입력: 해당 대상을 클릭하세요", ORG)
            return
        g = lambda key: parse_float(self.lv[key].get())
        if k == "node":
            vals = {"p": g("p")}
        elif k == "line":
            vals = {"w1": g("w1"), "w2": g("w2")}
        else:
            vals = {"q": g("q")}
        if None in vals.values():
            messagebox.showwarning("하중", "하중 값을 확인하세요.", parent=self.win); return
        _, _, key, ref = KINDS[k]
        m = self.model
        cid = self.active_case
        self.push_undo()
        for _, i in targets:
            if self.lv_replace.get():
                m[key] = [ld for ld in m[key] if not (ld[ref] == i and ld["case"] == cid)]
            m[key].append(dict(id=pm.next_load_id(m), case=cid, **{ref: i}, **vals))
        self.changed(f"[{m['cases'][cid]['name']}] {KINDS[k][0]} {len(targets)}개 입력")
