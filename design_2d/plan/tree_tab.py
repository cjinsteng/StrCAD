"""
design_2d/plan/tree_tab.py — 트리 탭 + 트리 → 캔버스 드래그 적용

 드래그 가능 항목 → 놓을 대상
   단면(SEC)  → 선 (보로 적용)        재료(MAT) → 선 (보 재료)
   슬래브(SLB) → 면 (슬래브로 적용)    지점(ST)  → 노드 또는 선(선 지점)
 노드/선/면을 먼저 선택해 두면 캔버스 아무 곳에 놓아도 선택 전체에 적용
"""

import tkinter as tk
from tkinter import ttk, messagebox

from . import model as pm
from ..section.theme import *

DRAG = {"SEC": ("line",), "MAT": ("line",), "SLB": ("area",), "ST": ("node", "line")}
DEFAULT_OPEN = {"G_geo", "G_props", "G_sec", "G_slb", "G_mat", "G_bnd", "G_sup",
                "G_loads", "G_cases", "G_combos"}
KIND_NAME = {"node": "노드", "line": "선", "area": "면"}


class TreeTabMixin:

    def _build_tree_tab(self, nb):
        f = tk.Frame(nb, bg=BG2)
        nb.add(f, text=" 트리 ")
        self.tab_tree = f
        bar = tk.Frame(f, bg=BG2)
        bar.pack(fill="x", padx=6, pady=(6, 4))
        mb = tk.Menubutton(bar, text="＋ 추가 ▾", bg=BG3, fg=TXT, font=FONT, activebackground=BG5,
                           activeforeground=WHI, relief="flat", padx=8, pady=3, cursor="hand2",
                           highlightthickness=0)
        menu = tk.Menu(mb, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC, font=FONT)
        for k, lbl in (("MAT", "재료"), ("SEC", "보 단면"), ("SLB", "슬래브 타입"), ("ST", "지점 타입"),
                       ("CASE", "하중케이스"), ("CO", "하중조합")):
            menu.add_command(label=lbl, command=lambda k=k: self.tree_add(k))
        mb.config(menu=menu)
        mb.pack(side="left", padx=1)
        btn(bar, "✎ 편집", self.tree_edit).pack(side="left", padx=1)
        btn(bar, "🗑 삭제", self.tree_delete).pack(side="left", padx=1)
        btn(bar, "⊞", lambda: self._tree_expand(True), padx=6).pack(side="right", padx=1)
        btn(bar, "⊟", lambda: self._tree_expand(False), padx=6).pack(side="right", padx=1)
        wrap = tk.Frame(f, bg=BG2)
        wrap.pack(fill="both", expand=True, padx=4)
        t = ttk.Treeview(wrap, columns=("cnt",), show="tree", style="Works.Treeview", selectmode="extended")
        t.column("#0", width=260, stretch=True)
        t.column("cnt", width=46, anchor="e", stretch=False)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=vs.set)
        t.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        t.tag_configure("grp", font=FONT_B, foreground=WHI)
        t.tag_configure("sub", font=FONT_B, foreground=TXT)
        t.tag_configure("drag", foreground=CYN)
        t.tag_configure("dim", foreground=TX3)
        t.tag_configure("load", foreground=C_LOAD)
        t.tag_configure("beam", foreground="#f0a0a0")
        t.tag_configure("slab", foreground="#9fc0ff")
        self.tree = t
        t.bind("<<TreeviewSelect>>", self._tree_select)
        t.bind("<Double-1>", lambda e: self.tree_edit())
        t.bind("<ButtonPress-1>", self._tree_press, add="+")
        t.bind("<B1-Motion>", self._tree_drag_motion)
        t.bind("<ButtonRelease-1>", self._tree_release, add="+")
        t.bind("<Button-3>", self._tree_menu)
        t.bind("<Delete>", lambda e: (self.tree_delete(), "break")[1])
        tk.Label(f, text="💡 하늘색 항목을 캔버스로 끌어다 놓으면 적용됩니다.\n"
                         "    단면→선(보) · 슬래브→면 · 지점→노드/선(벽체)\n"
                         "    먼저 선택해 두면 캔버스 아무 곳에 놓아도 선택 전체에 적용",
                 font=FONT_S, bg=BG2, fg=TX3, justify="left", anchor="w").pack(fill="x", padx=8, pady=6)
        self._drag = None
        self._drag_win = None

    # ════════════════════════════════════════════════════════
    def refresh_tree(self):
        t = getattr(self, "tree", None)
        if t is None:
            return
        opened = {i for i in self._all_iids() if t.item(i, "open")} if t.get_children() else set(DEFAULT_OPEN)
        sel = set(t.selection())
        y = t.yview()[0]
        t.delete(*t.get_children())
        m = self.model

        def ins(parent, iid, text, cnt="", tags=()):
            t.insert(parent, "end", iid=iid, text=text, values=(cnt,), tags=tags, open=iid in opened)

        ins("", "G_geo", "▣  Geometry (그리기)", "", ("grp",))
        ins("G_geo", "G_nodes", "⁘  Nodes", len(m["nodes"]), ("sub",))
        for nid, n in m["nodes"].items():
            sup = ""
            if nid in m["supports"]:
                st = m["sup_types"].get(m["supports"][nid])
                sup = f"   ▲{st['name']}" if st else ""
            ins("G_nodes", f"N_{nid}", f"N{nid}  ({n['x']:.3f}, {n['y']:.3f}){sup}")
        nb = sum(1 for l in m["lines"].values() if l["kind"] == "beam")
        ins("G_geo", "G_lines", f"╱  Lines  (보 {nb})", len(m["lines"]), ("sub",))
        for lid, ln in m["lines"].items():
            if ln["kind"] == "beam":
                s = m["sections"].get(ln["sec"], {}).get("name", "?")
                txt, tg = f"L{lid} {ln.get('name', '')} 보 [{s}]  {pm.line_length(m, lid):.2f}m", ("beam",)
            else:
                txt, tg = f"L{lid}  비구조  {pm.line_length(m, lid):.2f}m", ("dim",)
            if lid in m["line_supports"]:
                txt += "  ▬지점"
            ins("G_lines", f"L_{lid}", txt, "", tg)
        ns = sum(1 for a in m["areas"].values() if a["kind"] == "slab")
        ins("G_geo", "G_areas", f"▱  Areas  (슬래브 {ns})", len(m["areas"]), ("sub",))
        for aid, ar in m["areas"].items():
            if ar["kind"] == "slab":
                sl = m["slabs"].get(ar["slab"], {})
                txt, tg = f"A{aid} {ar.get('name', '')} 슬래브 [{sl.get('name', '?')} t{sl.get('t', 0):g}]  {pm.area_of(m, aid):.2f}m²", ("slab",)
            else:
                txt, tg = f"A{aid}  비구조 ({pm.AREA_DIST_LABEL.get(ar.get('dist'), '')})  {pm.area_of(m, aid):.2f}m²", ("dim",)
            ins("G_areas", f"A_{aid}", txt, "", tg)

        ins("", "G_props", "◈  Properties (부재 적용)", "", ("grp",))
        use_s, use_m, use_sl = {}, {}, {}
        for ln in m["lines"].values():
            if ln["kind"] == "beam":
                use_s[ln["sec"]] = use_s.get(ln["sec"], 0) + 1
                use_m[ln["mat"]] = use_m.get(ln["mat"], 0) + 1
        for ar in m["areas"].values():
            if ar["kind"] == "slab":
                use_sl[ar["slab"]] = use_sl.get(ar["slab"], 0) + 1
        ins("G_props", "G_sec", "▥  보 단면 (Beam Section)", len(m["sections"]), ("sub",))
        for sid, sec in m["sections"].items():
            ins("G_sec", f"SEC_{sid}", f"{sid}: {sec['name']}   {pm.section_desc(sec)}", use_s.get(sid, 0), ("drag",))
        ins("G_props", "G_slb", "▤  슬래브 (Slab)", len(m["slabs"]), ("sub",))
        for sid, sl in m["slabs"].items():
            mat = m["materials"].get(sl["mat"], {}).get("name", "?")
            ins("G_slb", f"SLB_{sid}", f"{sid}: {sl['name']}   t={sl['t']:g} mm  ({mat})", use_sl.get(sid, 0), ("drag",))
        ins("G_props", "G_mat", "▧  재료 (Material)", len(m["materials"]), ("sub",))
        for mid, mat in m["materials"].items():
            E = pm.material_E(mat)
            ins("G_mat", f"MAT_{mid}", f"{mid}: {mat['name']}  ({mat.get('type')}, E={E:,.0f}, ν={mat.get('nu', 0.2):g})",
                use_m.get(mid, 0), ("drag",))

        ins("", "G_bnd", "⊥  Boundaries", "", ("grp",))
        ins("G_bnd", "G_sup", "▲  Supports", len(m["supports"]) + len(m["line_supports"]), ("sub",))
        for sid, st in m["sup_types"].items():
            ns_ = [n for n, s in m["supports"].items() if s == sid]
            ls_ = [l for l, s in m["line_supports"].items() if s == sid]
            ins("G_sup", f"ST_{sid}", f"{st['name']}   ({pm.support_desc(st)})", len(ns_) + len(ls_), ("drag",))
            for n in sorted(ns_):
                ins(f"ST_{sid}", f"SUP_{n}", f"N{n}", "", ("dim",))
            for l in sorted(ls_):
                ins(f"ST_{sid}", f"LSUP_{l}", f"L{l} (선 지점)", "", ("dim",))

        ins("", "G_loads", "⬇  Loads", "", ("grp",))
        ins("G_loads", "G_cases", "▧  Load Cases", len(m["cases"]), ("sub",))
        for cid, cs in m["cases"].items():
            lds = [("NL", ld) for ld in m["nloads"] if ld["case"] == cid] + \
                  [("LL", ld) for ld in m["lloads"] if ld["case"] == cid] + \
                  [("AL", ld) for ld in m["aloads"] if ld["case"] == cid]
            sw = f"  (자중×{float(cs.get('selfweight', 0)):g})" if float(cs.get("selfweight", 0) or 0) else ""
            mark = "  ◀" if cid == self.active_case else ""
            ins("G_cases", f"CASE_{cid}", f"{cs['name']}{sw}{mark}", len(lds), ("load",))
            for k, ld in lds:
                ins(f"CASE_{cid}", f"{k}_{ld['id']}", load_text(k, ld), "", ("dim",))
        ins("G_loads", "G_combos", "Σ  Combinations", len(m["combos"]), ("sub",))
        for coid, co in m["combos"].items():
            ins("G_combos", f"CO_{coid}", f"{co['name']}   = {combo_text(m, co)}")

        self._tree_set_sel([i for i in sel if t.exists(i)])
        t.yview_moveto(y)

    def _tree_set_sel(self, ids):
        self._tree_expected = set(ids)
        self.tree.selection_set(list(ids))

    def _all_iids(self, parent=""):
        out = []
        for i in self.tree.get_children(parent):
            out.append(i)
            out += self._all_iids(i)
        return out

    def _tree_expand(self, on):
        for i in self._all_iids():
            if i.startswith("G_") or not on:
                self.tree.item(i, open=on)
        if not on:
            for i in ("G_geo", "G_props", "G_bnd", "G_loads"):
                self.tree.item(i, open=True)

    def sync_tree_selection(self):
        t = getattr(self, "tree", None)
        if t is None:
            return
        ids = [f"N_{n}" for n in self.sel["node"]] + [f"L_{l}" for l in self.sel["line"]] + \
              [f"A_{a}" for a in self.sel["area"]]
        ids = [i for i in ids if t.exists(i)]
        self._tree_set_sel(ids)
        if len(ids) == 1:
            t.see(ids[0])

    # ── 선택/편집 ───────────────────────────────────────────
    def _tree_select(self, e=None, force=False):
        sel = self.tree.selection()
        if not sel or (not force and set(sel) == self._tree_expected):
            return
        self._tree_expected = None
        picked = {"node": set(), "line": set(), "area": set()}
        target = None
        for iid in sel:
            k, _, v = iid.partition("_")
            if k in ("N", "SUP"):
                picked["node"].add(int(v))
            elif k in ("L", "LSUP"):
                picked["line"].add(int(v))
            elif k == "A":
                picked["area"].add(int(v))
            elif k in ("MAT", "SEC", "SLB", "ST", "CASE", "CO", "NL", "LL", "AL"):
                target = (k, int(v))
        if any(picked.values()):
            self.sel = picked
            self.edit_target = None
            self.redraw(); self.show_editor(); self.refresh_result_detail()
        elif target:
            self.edit_target = target
            if target[0] == "CASE":
                self.set_active_case(target[1])
            if target[0] in ("NL", "LL", "AL"):
                ld = self.find_load(target)
                if ld and ld["case"] != self.active_case:
                    self.set_active_case(ld["case"])
                self.sel_load_ids = {target[1]}
                self.redraw()
            self.show_editor()

    def tree_edit(self):
        if not self.tree.selection():
            return
        self._tree_select(force=True)
        self.nb.select(self.tab_input)

    def tree_add(self, kind):
        m = self.model
        self.push_undo()
        if kind == "MAT":
            i = pm.next_id(m["materials"])
            m["materials"][i] = {"name": f"C{24 + 3 * (i - 1)}", "type": "RC", "fck": 24.0 + 3 * (i - 1),
                                 "fy": 400.0, "E": 0.0, "gamma": 24.0, "nu": 0.167}
        elif kind == "SEC":
            i = pm.next_id(m["sections"])
            m["sections"][i] = {"name": f"G{i}", "shape": "rect", "b": 400, "h": 600}
        elif kind == "SLB":
            i = pm.next_id(m["slabs"])
            m["slabs"][i] = {"name": f"S{i}", "t": 180.0, "mat": min(m["materials"])}
        elif kind == "ST":
            i = pm.next_id(m["sup_types"])
            m["sup_types"][i] = {"name": f"지점{i}", "dz": 1, "rx": 0, "ry": 0, "kz": 0, "krx": 0,
                                 "kry": 0, "col": 0}
        elif kind == "CASE":
            i = pm.next_id(m["cases"])
            m["cases"][i] = {"name": f"LC{i}", "selfweight": 0.0}
        else:
            i = pm.next_id(m["combos"])
            m["combos"][i] = {"name": f"COMB{i}", "factors": {c: 1.0 for c in m["cases"]}}
        self.changed("추가됨 — [입력] 탭에서 편집하세요")
        self.edit_target = (kind, i)
        self.show_editor()
        self.nb.select(self.tab_input)
        iid = f"{kind}_{i}"
        if self.tree.exists(iid):
            self._tree_set_sel([iid]); self.tree.see(iid)

    def tree_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        m = self.model
        g = {}
        for iid in sel:
            k, _, v = iid.partition("_")
            g.setdefault(k, []).append(int(v) if v.lstrip("-").isdigit() else v)
        if any(k in g for k in ("N", "L", "A")):
            self.clear_sel()
            self.sel["node"] |= set(g.get("N", [])); self.sel["line"] |= set(g.get("L", []))
            self.sel["area"] |= set(g.get("A", []))
            self.delete_selected()
            return
        self.push_undo()
        msgs = []
        for i in g.get("MAT", []):
            used = any(l["mat"] == i for l in m["lines"].values() if l["kind"] == "beam") or \
                any(s["mat"] == i for s in m["slabs"].values())
            if used:
                msgs.append(f"재료 '{m['materials'][i]['name']}' 사용 중")
            elif len(m["materials"]) > 1:
                m["materials"].pop(i)
        for i in g.get("SEC", []):
            if any(l["sec"] == i and l["kind"] == "beam" for l in m["lines"].values()):
                msgs.append(f"단면 '{m['sections'][i]['name']}' 사용 중")
            elif len(m["sections"]) > 1:
                m["sections"].pop(i)
        for i in g.get("SLB", []):
            if any(a["slab"] == i and a["kind"] == "slab" for a in m["areas"].values()):
                msgs.append(f"슬래브 '{m['slabs'][i]['name']}' 사용 중")
            elif len(m["slabs"]) > 1:
                m["slabs"].pop(i)
        for i in g.get("ST", []):
            m["sup_types"].pop(i, None)
            m["supports"] = {n: s for n, s in m["supports"].items() if s != i}
            m["line_supports"] = {n: s for n, s in m["line_supports"].items() if s != i}
        for i in g.get("SUP", []):
            m["supports"].pop(i, None)
        for i in g.get("LSUP", []):
            m["line_supports"].pop(i, None)
        for i in g.get("CASE", []):
            if len(m["cases"]) <= 1:
                msgs.append("하중케이스는 최소 1개 필요"); continue
            m["cases"].pop(i, None)
            for key in ("nloads", "lloads", "aloads"):
                m[key] = [ld for ld in m[key] if ld["case"] != i]
            for co in m["combos"].values():
                co["factors"].pop(i, None)
        for i in g.get("CO", []):
            m["combos"].pop(i, None)
        for k, key in (("NL", "nloads"), ("LL", "lloads"), ("AL", "aloads")):
            ids = set(g.get(k, []))
            if ids:
                m[key] = [ld for ld in m[key] if ld["id"] not in ids]
        d = m["defaults"]
        for key, dk in (("materials", "mat"), ("sections", "sec"), ("slabs", "slab"), ("sup_types", "sup")):
            if d.get(dk) not in m[key] and m[key]:
                d[dk] = min(m[key])
        self.edit_target = None
        self.changed("삭제됨")
        if msgs:
            messagebox.showinfo("삭제 안 됨", "\n".join(msgs), parent=self.win)

    def _tree_menu(self, e):
        iid = self.tree.identify_row(e.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        menu = tk.Menu(self.win, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC, activeforeground=WHI, font=FONT)
        k = iid.partition("_")[0] if iid else ""
        amap = {"G_mat": "MAT", "MAT": "MAT", "G_sec": "SEC", "SEC": "SEC", "G_slb": "SLB", "SLB": "SLB",
                "G_sup": "ST", "ST": "ST", "G_cases": "CASE", "CASE": "CASE", "G_combos": "CO", "CO": "CO"}
        kind = amap.get(iid) or amap.get(k)
        if kind:
            lbl = {"MAT": "재료", "SEC": "보 단면", "SLB": "슬래브 타입", "ST": "지점 타입",
                   "CASE": "하중케이스", "CO": "하중조합"}[kind]
            menu.add_command(label=f"＋ {lbl} 추가", command=lambda: self.tree_add(kind))
        if k in DRAG:
            for tgt in DRAG[k]:
                n = len(self.sel[tgt])
                menu.add_command(label=f"⇢ 선택한 {KIND_NAME[tgt]} {n}개에 적용",
                                 state="normal" if n else "disabled",
                                 command=lambda t_=tgt: self._apply_item(iid, t_, sorted(self.sel[t_])))
        if k in ("MAT", "SEC", "SLB", "ST", "CASE", "CO", "NL", "LL", "AL", "N", "L", "A"):
            menu.add_command(label="✎ 편집", command=self.tree_edit)
        if k == "SEC":
            menu.add_command(label="기본 보 단면으로", command=lambda: self._set_default("sec", int(iid[4:])))
        if k == "SLB":
            menu.add_command(label="기본 슬래브로", command=lambda: self._set_default("slab", int(iid[4:])))
        if k == "CASE":
            menu.add_command(label="활성 하중케이스로", command=lambda: self.set_active_case(int(iid[5:])))
        if k and not iid.startswith("G_"):
            menu.add_separator()
            menu.add_command(label="🗑 삭제", command=self.tree_delete)
        if menu.index("end") is not None:
            menu.tk_popup(e.x_root, e.y_root)

    def _set_default(self, key, i):
        self.model["defaults"][key] = i
        self.show_editor()
        self.msg("기본값 변경")

    # ════════════════════════════════════════════════════════
    #  드래그 앤 드롭
    # ════════════════════════════════════════════════════════
    def _tree_press(self, e):
        iid = self.tree.identify_row(e.y)
        k = iid.partition("_")[0] if iid else ""
        self._drag = {"iid": iid, "kind": k, "x": e.x_root, "y": e.y_root, "active": False} if k in DRAG else None

    def _tree_drag_motion(self, e):
        d = self._drag
        if not d:
            return
        if not d["active"]:
            if abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) < 8:
                return
            d["active"] = True
            self._drag_win = tw = tk.Toplevel(self.win)
            tw.overrideredirect(True)
            try:
                tw.attributes("-alpha", 0.9)
            except tk.TclError:
                pass
            text = self.tree.item(d["iid"], "text").split("(")[0].strip()
            tg = DRAG[d["kind"]]
            nsel = [(KIND_NAME[k], len(self.sel[k])) for k in tg if self.sel[k]]
            hint = (f"선택 {nsel[0][0]} {nsel[0][1]}개 (캔버스 아무 곳에)" if nsel
                    else "/".join(KIND_NAME[k] for k in tg) + "에 놓기")
            tk.Label(tw, text=f"  {text}  →  {hint}  ", font=FONT_B, bg=ACC, fg=WHI, padx=4, pady=3).pack()
            self.tree.config(cursor="hand2")
        if self._drag_win:
            self._drag_win.geometry(f"+{e.x_root + 14}+{e.y_root + 10}")
        tgt = self._drop_target(e.x_root, e.y_root, d["kind"])
        if tgt != self.drop_hover:
            self.drop_hover = tgt
            self.redraw()
            if tgt and tgt[1] is not None:
                self.st_info.config(text="놓으면 적용: " + self._describe(tgt))
            elif tgt:
                self.st_info.config(text=f"놓으면 선택된 {KIND_NAME[tgt[0]]} {len(self.sel[tgt[0]])}개에 적용")
        return "break"

    def _drop_target(self, xr, yr, kind):
        if self.win.winfo_containing(xr, yr) is not self.canvas:
            return None
        cx = xr - self.canvas.winfo_rootx(); cy = yr - self.canvas.winfo_rooty()
        tg = DRAG[kind]
        if "node" in tg:
            n = self.hit_node(cx, cy, tol=14)
            if n is not None:
                return ("node", n)
        if "line" in tg:
            l = self.hit_line(cx, cy, tol=10)
            if l is not None:
                return ("line", l)
        if "area" in tg:
            a = self.hit_area(cx, cy)
            if a is not None:
                return ("area", a)
        for k in tg:
            if self.sel[k]:
                return (k, None)
        return None

    def _tree_release(self, e):
        d = self._drag
        self._drag = None
        if self._drag_win:
            self._drag_win.destroy(); self._drag_win = None
        self.tree.config(cursor="")
        if not d or not d["active"]:
            return
        tgt = self._drop_target(e.x_root, e.y_root, d["kind"])
        self.drop_hover = None
        if not tgt:
            self.redraw()
            self.msg("놓을 위치에 대상이 없습니다.", ORG)
            return
        kind, i = tgt
        targets = sorted(self.sel[kind]) if (i is None or i in self.sel[kind]) else [i]
        self._apply_item(d["iid"], kind, targets)

    def _apply_item(self, iid, kind, targets):
        k, _, v = iid.partition("_")
        v = int(v)
        if k == "SEC":
            self.assign_beam(targets, sec=v)
        elif k == "MAT":
            self.assign_beam(targets, mat=v)
        elif k == "SLB":
            self.assign_slab(targets, v)
        elif k == "ST":
            if kind == "node":
                self.assign_support(targets, v)
            else:
                self.assign_line_support(targets, v)


def load_text(k, ld):
    if k == "NL":
        return f"집중 N{ld['node']}: P={float(ld['p']):g} kN"
    if k == "LL":
        w1, w2 = float(ld["w1"]), float(ld["w2"])
        w = f"{w1:g}" if abs(w1 - w2) < 1e-12 else f"{w1:g}~{w2:g}"
        return f"선 L{ld['line']}: w={w} kN/m"
    return f"면 A{ld['area']}: q={float(ld['q']):g} kN/m²"


def combo_text(m, co):
    parts = [f"{f:g}×{m['cases'][c]['name']}" for c, f in co.get("factors", {}).items()
             if c in m["cases"] and abs(f) > 1e-12]
    return " + ".join(parts) or "-"
