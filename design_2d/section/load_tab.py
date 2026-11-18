"""
design_2d/section/load_tab.py — 하중 탭

 하중케이스 선택 → 하중 종류(절점/부재집중/부재분포) → 값 입력
 → [선택 항목에 적용] 또는 [⬇ 하중] 모드에서 캔버스 클릭으로 입력
"""

import tkinter as tk
from tkinter import ttk, messagebox

from . import model as fm
from .theme import *
from .tree_tab import load_text


class LoadTabMixin:

    def _build_load_tab(self, nb):
        f = tk.Frame(nb, bg=BG2)
        nb.add(f, text=" 하중 ")
        self.tab_load = f
        self.sel_load_ids = set()

        lv = self.lv = {k: tk.StringVar(value=v) for k, v in (
            ("fx", "0"), ("fy", "-10"), ("mz", "0"), ("p", "10"), ("pa", "0.5"),
            ("w1", "10"), ("w2", "10"), ("a", "0"), ("b", "1"))}
        self.lv_dir = tk.StringVar(value=fm.LOAD_DIR_LABEL["G"])
        self.lv_rel = tk.BooleanVar(value=True)
        self.lv_replace = tk.BooleanVar(value=False)
        self.load_kind = tk.StringVar(value="dist")

        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(top, text="하중케이스", font=FONT_B, bg=BG2, fg=C_LOAD).pack(side="left")
        self.v_case = tk.StringVar()
        self.cb_case = combo(top, self.v_case, [], 14)
        self.cb_case.pack(side="left", padx=6)
        self.cb_case.bind("<<ComboboxSelected>>",
                          lambda e: self.set_active_case(self._case_id_from_combo()))
        btn(top, "＋", lambda: self.tree_add("CASE"), padx=6).pack(side="left")

        kf = tk.Frame(f, bg=BG2)
        kf.pack(fill="x", padx=8, pady=(8, 2))
        for code, text in (("node", "절점하중"), ("point", "부재 집중"), ("dist", "부재 분포")):
            tk.Radiobutton(kf, text=text, variable=self.load_kind, value=code,
                           indicatoron=0, command=self._on_load_kind, bg=BG3, fg=TXT,
                           selectcolor="#7c5a00", activebackground=BG5,
                           activeforeground=WHI, font=FONT_B, relief="flat", bd=0,
                           padx=10, pady=4, highlightthickness=0,
                           cursor="hand2").pack(side="left", padx=1, fill="x", expand=True)

        self.load_form = tk.Frame(f, bg=BG2)
        self.load_form.pack(fill="x", padx=8, pady=4)

        opt = tk.Frame(f, bg=BG2)
        opt.pack(fill="x", padx=8)
        check(opt, "같은 케이스의 기존 하중(같은 종류) 대체", self.lv_replace).pack(anchor="w")

        bf = tk.Frame(f, bg=BG2)
        bf.pack(fill="x", padx=8, pady=6)
        btn(bf, "선택 항목에 적용", self.apply_load_selected, bg=ACC, fg=WHI,
            font=FONT_B, padx=10, pady=4).pack(side="left", padx=(0, 4))
        btn(bf, "⬇ 클릭 입력 모드", self._load_click_mode, bg="#7c5a00", fg=WHI,
            font=FONT_B, padx=10, pady=4).pack(side="left")

        tk.Frame(f, bg=BDR, height=1).pack(fill="x", padx=6, pady=(4, 2))
        lh = tk.Frame(f, bg=BG2)
        lh.pack(fill="x", padx=8, pady=(4, 2))
        self.lbl_loads = tk.Label(lh, text="하중 목록", font=FONT_B, bg=BG2, fg=WHI)
        self.lbl_loads.pack(side="left")
        btn(lh, "케이스 하중 모두 삭제", self._clear_case_loads, fg=RED, padx=6, pady=1).pack(side="right")
        btn(lh, "삭제", self._delete_list_loads, fg=RED, padx=6, pady=1).pack(side="right", padx=2)

        wrap = tk.Frame(f, bg=BG2)
        wrap.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        t = ttk.Treeview(wrap, columns=("desc",), show="tree", style="Works.Treeview",
                         selectmode="extended")
        t.column("#0", width=0, stretch=False)
        t.column("desc", width=300, stretch=True)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=vs.set)
        t.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        t.bind("<<TreeviewSelect>>", self._on_load_list_select)
        t.bind("<Double-1>", self._on_load_list_dbl)
        t.bind("<Delete>", lambda e: self._delete_list_loads())
        self.load_list = t
        self._on_load_kind()

    # ── 입력 폼 ─────────────────────────────────────────────
    def _on_load_kind(self):
        for w in self.load_form.winfo_children():
            w.destroy()
        k = self.load_kind.get()
        lv = self.lv
        f = Form(self.load_form, lw=11)
        if k == "node":
            f.row("Fx", lambda p: entry(p, lv["fx"], 10), "kN  (→ +)")
            f.row("Fy", lambda p: entry(p, lv["fy"], 10), "kN  (↑ +)")
            f.row("Mz", lambda p: entry(p, lv["mz"], 10), "kN·m (반시계 +)")
            hint = "전체좌표 기준. 중력방향 하중은 Fy 에 음수(-)로 입력"
        else:
            f.row("방향", lambda p: combo(p, self.lv_dir, [l for _, l in fm.LOAD_DIRS], 16))
            rf = tk.Frame(self.load_form, bg=BG2)
            if k == "point":
                f.row("P", lambda p: entry(p, lv["p"], 10), "kN")
                f.row("위치 a", lambda p: entry(p, lv["pa"], 10), "")
            else:
                f.row("w1 (시작)", lambda p: entry(p, lv["w1"], 10), "kN/m")
                f.row("w2 (끝)", lambda p: entry(p, lv["w2"], 10), "kN/m")
                f.row("시작 a", lambda p: entry(p, lv["a"], 10), "")
                f.row("끝 b", lambda p: entry(p, lv["b"], 10), "")
            rf.pack(fill="x", pady=(2, 0))
            radio(rf, "위치: 비율(0~1)", self.lv_rel, True, command=self._on_rel_toggle).pack(side="left")
            radio(rf, "거리(m, i단 기준)", self.lv_rel, False, command=self._on_rel_toggle).pack(side="left", padx=8)
            hint = ("↓중력: + 값이 아래 방향  ·  Ly: 부재 i→j 기준 왼쪽(+)\n"
                    "w1≠w2 이면 사다리꼴/삼각형 분포")
        tk.Label(self.load_form, text=hint, font=FONT_S, bg=BG2, fg=TX3,
                 justify="left").pack(anchor="w", pady=(4, 0))
        if self.mode.get() == "load":
            self.msg(self._load_mode_msg())

    def _on_rel_toggle(self):
        # 비율 ↔ 거리 전환 시 기본값 보정
        lv = self.lv
        if self.lv_rel.get():
            if parse_float(lv["b"].get(), 1) > 1:
                lv["b"].set("1")
            if parse_float(lv["pa"].get(), 0.5) > 1:
                lv["pa"].set("0.5")

    def _load_mode_msg(self):
        k = self.load_kind.get()
        return {"node": "하중 모드: 노드를 클릭하면 절점하중이 입력됩니다",
                "point": "하중 모드: 부재를 클릭하면 집중하중이 입력됩니다",
                "dist": "하중 모드: 부재를 클릭하면 분포하중이 입력됩니다"}[k]

    def _load_click_mode(self):
        self.mode.set("load")
        self.chain = None
        self.msg(self._load_mode_msg(), C_LOAD)
        self.redraw()

    # ── 케이스 ───────────────────────────────────────────────
    def _case_id_from_combo(self):
        s = self.v_case.get()
        for cid, cs in self.model["cases"].items():
            if s == f"{cid}: {cs['name']}":
                return cid
        return self.active_case

    def set_active_case(self, cid):
        if cid not in self.model["cases"]:
            return
        self.active_case = cid
        self.refresh_load_tab()
        self.refresh_tree()
        self.redraw()

    def refresh_load_tab(self):
        if not hasattr(self, "cb_case"):
            return
        m = self.model
        if self.active_case not in m["cases"] and m["cases"]:
            self.active_case = min(m["cases"])
        vals = [f"{cid}: {cs['name']}" for cid, cs in m["cases"].items()]
        self.cb_case.config(values=vals)
        cs = m["cases"].get(self.active_case)
        self.v_case.set(f"{self.active_case}: {cs['name']}" if cs else "")
        t = self.load_list
        t.delete(*t.get_children())
        n = 0
        for ld in m["nloads"]:
            if ld["case"] == self.active_case:
                t.insert("", "end", iid=f"NL_{ld['id']}", values=(load_text(ld),)); n += 1
        for ld in m["eloads"]:
            if ld["case"] == self.active_case:
                t.insert("", "end", iid=f"EL_{ld['id']}", values=(load_text(ld),)); n += 1
        self.lbl_loads.config(text=f"하중 목록 — {cs['name'] if cs else ''} ({n})")
        self.sel_load_ids = {i for i in self.sel_load_ids
                             if t.exists(f"NL_{i}") or t.exists(f"EL_{i}")}

    def _on_load_list_select(self, e=None):
        self.sel_load_ids = {int(i.split("_")[1]) for i in self.load_list.selection()}
        self.redraw()

    def _on_load_list_dbl(self, e=None):
        sel = self.load_list.selection()
        if not sel:
            return
        k, _, v = sel[0].partition("_")
        self.edit_target = (k, int(v))
        self.show_editor()
        self.nb.select(self.tab_input)

    def _delete_list_loads(self):
        ids = {int(i.split("_")[1]) for i in self.load_list.selection()}
        if not ids:
            return
        self.push_undo()
        m = self.model
        m["nloads"] = [ld for ld in m["nloads"] if ld["id"] not in ids]
        m["eloads"] = [ld for ld in m["eloads"] if ld["id"] not in ids]
        self.sel_load_ids = set()
        self.changed(f"하중 {len(ids)}개 삭제")

    def _clear_case_loads(self):
        m = self.model
        cid = self.active_case
        n = sum(1 for ld in m["nloads"] + m["eloads"] if ld["case"] == cid)
        if not n:
            return
        if not messagebox.askyesno("삭제", f"'{m['cases'][cid]['name']}' 의 하중 {n}개를 모두 삭제할까요?",
                                   parent=self.win):
            return
        self.push_undo()
        m["nloads"] = [ld for ld in m["nloads"] if ld["case"] != cid]
        m["eloads"] = [ld for ld in m["eloads"] if ld["case"] != cid]
        self.changed("케이스 하중 삭제")

    # ── 하중 적용 ───────────────────────────────────────────
    def apply_load_selected(self):
        k = self.load_kind.get()
        if k == "node":
            tg = [("node", n) for n in sorted(self.sel_nodes)]
        else:
            tg = [("elem", e) for e in sorted(self.sel_elems)]
        if not tg:
            messagebox.showinfo("하중", "먼저 캔버스에서 " + ("노드를" if k == "node" else "부재를")
                                + " 선택하세요.\n(또는 [⬇ 클릭 입력 모드] 사용)", parent=self.win)
            return
        self.apply_load_to(tg)

    def _read_load(self):
        lv = self.lv
        k = self.load_kind.get()
        g = lambda key: parse_float(lv[key].get())
        if k == "node":
            vals = dict(fx=g("fx"), fy=g("fy"), mz=g("mz"))
            if None in vals.values():
                return None
            if all(abs(v) < 1e-12 for v in vals.values()):
                return None
            return vals
        rel = bool(self.lv_rel.get())
        d = fm.LOAD_DIR_CODE.get(self.lv_dir.get(), "G")
        if k == "point":
            p, a = g("p"), g("pa")
            if p is None or a is None or (rel and not 0 <= a <= 1):
                return None
            return dict(kind="point", dir=d, p=p, a=a, rel=rel)
        w1, w2, a, b = g("w1"), g("w2"), g("a"), g("b")
        if None in (w1, w2, a, b) or b <= a or (rel and not (0 <= a < b <= 1)):
            return None
        return dict(kind="dist", dir=d, w1=w1, w2=w2, a=a, b=b, rel=rel)

    def apply_load_to(self, targets):
        k = self.load_kind.get()
        want = "node" if k == "node" else "elem"
        targets = [t for t in targets if t[0] == want]
        if not targets:
            self.msg(f"{'노드' if want == 'node' else '부재'}를 클릭하세요 ({self._load_mode_msg()})", ORG)
            return
        vals = self._read_load()
        if vals is None:
            messagebox.showwarning("하중", "하중 값/위치를 확인하세요.", parent=self.win)
            return
        m = self.model
        cid = self.active_case
        self.push_undo()
        for _, i in targets:
            if want == "elem" and not vals.get("rel"):
                L = fm.elem_length(m, i)
                pos = vals.get("a", 0) if k == "point" else vals.get("b", 0)
                if pos > L + 1e-9:
                    self.msg(f"E{i}: 위치가 부재 길이({L:.3f} m)를 넘습니다 — 끝까지로 처리", ORG)
            if self.lv_replace.get():
                if want == "node":
                    m["nloads"] = [ld for ld in m["nloads"] if not (ld["node"] == i and ld["case"] == cid)]
                else:
                    m["eloads"] = [ld for ld in m["eloads"]
                                   if not (ld["elem"] == i and ld["case"] == cid and ld["kind"] == k)]
            lid = fm.next_load_id(m)
            if want == "node":
                m["nloads"].append(dict(id=lid, case=cid, node=i, **vals))
            else:
                m["eloads"].append(dict(id=lid, case=cid, elem=i, **vals))
        name = m["cases"][cid]["name"]
        self.changed(f"[{name}] 하중 {len(targets)}개 입력")
