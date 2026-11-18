"""
design_2d/section/tree_tab.py — 트리(Works) 탭 + 트리 → 캔버스 드래그 지정

  ▾ Structures
      Nodes ............. n
      Elements .......... n
  ▾ Properties
      Material .......... n      ← 항목을 끌어서 부재에 놓으면 재료 지정
      Section ........... n      ← 항목을 끌어서 부재에 놓으면 단면 지정
  ▾ Boundaries
      Supports .......... n      ← 지점 타입을 끌어서 노드에 놓으면 지점 지정
      End Releases ...... n      ← 해제 타입을 끌어서 부재에 놓으면 힌지 지정
  ▾ Loads
      Load Cases ........ n
      Combinations ...... n
"""

import tkinter as tk
from tkinter import ttk, messagebox

from . import model as fm
from .theme import *

DRAG_KINDS = {"MAT": "elem", "SEC": "elem", "RL": "elem", "ST": "node"}   # 드래그 가능 항목 → 놓을 대상
DEFAULT_OPEN = {"G_struct", "G_props", "G_mat", "G_sec", "G_bnd", "G_sup",
                "G_rel", "G_loads", "G_cases", "G_combos"}


class TreeTabMixin:

    def _build_tree_tab(self, nb):
        f = tk.Frame(nb, bg=BG2)
        nb.add(f, text=" 트리 ")
        self.tab_tree = f

        bar = tk.Frame(f, bg=BG2)
        bar.pack(fill="x", padx=6, pady=(6, 4))
        mb = tk.Menubutton(bar, text="＋ 추가 ▾", bg=BG3, fg=TXT, font=FONT,
                           activebackground=BG5, activeforeground=WHI, relief="flat",
                           padx=8, pady=3, cursor="hand2", highlightthickness=0)
        menu = tk.Menu(mb, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC, font=FONT)
        menu.add_command(label="재료", command=lambda: self.tree_add("MAT"))
        menu.add_command(label="단면", command=lambda: self.tree_add("SEC"))
        menu.add_command(label="지점 타입", command=lambda: self.tree_add("ST"))
        menu.add_command(label="단부조건 (고정률)", command=lambda: self.tree_add("RL"))
        menu.add_separator()
        menu.add_command(label="하중케이스", command=lambda: self.tree_add("CASE"))
        menu.add_command(label="하중조합", command=lambda: self.tree_add("CO"))
        mb.config(menu=menu)
        mb.pack(side="left", padx=1)
        btn(bar, "✎ 편집", self.tree_edit).pack(side="left", padx=1)
        btn(bar, "🗑 삭제", self.tree_delete).pack(side="left", padx=1)
        btn(bar, "⊞", lambda: self._tree_expand(True), padx=6).pack(side="right", padx=1)
        btn(bar, "⊟", lambda: self._tree_expand(False), padx=6).pack(side="right", padx=1)

        wrap = tk.Frame(f, bg=BG2)
        wrap.pack(fill="both", expand=True, padx=4)
        t = ttk.Treeview(wrap, columns=("cnt",), show="tree", style="Works.Treeview",
                         selectmode="extended")
        t.column("#0", width=250, stretch=True)
        t.column("cnt", width=48, anchor="e", stretch=False)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=vs.set)
        t.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        t.tag_configure("grp", font=FONT_B, foreground=WHI)
        t.tag_configure("sub", font=FONT_B, foreground=TXT)
        t.tag_configure("drag", foreground=CYN)
        t.tag_configure("dim", foreground=TX3)
        t.tag_configure("load", foreground=C_LOAD)
        self.tree = t
        t.bind("<<TreeviewSelect>>", self._tree_select)
        t.bind("<Double-1>", lambda e: self.tree_edit())
        t.bind("<ButtonPress-1>", self._tree_press, add="+")
        t.bind("<B1-Motion>", self._tree_drag_motion)
        t.bind("<ButtonRelease-1>", self._tree_release, add="+")
        t.bind("<Button-3>", self._tree_menu)
        t.bind("<Delete>", lambda e: (self.tree_delete(), "break")[1])

        tk.Label(f, text="💡 하늘색 항목(재료·단면·지점·단부조건)을 끌어서 캔버스의\n"
                         "    부재/노드에 놓으면 지정됩니다.\n"
                         "    먼저 선택해 두면 캔버스 아무 곳에 놓아도 선택 항목 전체에 적용",
                 font=FONT_S, bg=BG2, fg=TX3, justify="left", anchor="w").pack(
            fill="x", padx=8, pady=6)
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
            t.insert(parent, "end", iid=iid, text=text, values=(cnt,), tags=tags,
                     open=iid in opened)

        ins("", "G_struct", "▣  Structures", "", ("grp",))
        ins("G_struct", "G_nodes", "⁘  Nodes", len(m["nodes"]), ("sub",))
        for nid, n in m["nodes"].items():
            sup = ""
            if nid in m["supports"]:
                st = m["sup_types"].get(m["supports"][nid])
                sup = f"   ▲{st['name']}" if st else ""
            ins("G_nodes", f"N_{nid}", f"N{nid}   ({n['x']:.3f}, {n['y']:.3f}){sup}")
        ins("G_struct", "G_elems", "╱  Elements", len(m["elems"]), ("sub",))
        for eid, e in m["elems"].items():
            sec = m["sections"].get(e["sec"], {})
            nm = e.get("name") or ""
            rel_t = "" if fm.is_rigid(e) else f"  ◦{fm.end_desc(*fm.end_fix(e))}"
            ins("G_elems", f"E_{eid}",
                f"E{eid} {nm}  [{sec.get('name', '?')}]  N{e['ni']}→N{e['nj']}  "
                f"{fm.elem_length(m, eid):.2f}m{rel_t}")

        ins("", "G_props", "◈  Properties", "", ("grp",))
        ins("G_props", "G_mat", "▤  Material", len(m["materials"]), ("sub",))
        use_m = {}
        use_s = {}
        for e in m["elems"].values():
            use_m[e["mat"]] = use_m.get(e["mat"], 0) + 1
            use_s[e["sec"]] = use_s.get(e["sec"], 0) + 1
        for mid, mat in m["materials"].items():
            E = fm.material_E(mat)
            sub = f"fck {mat.get('fck', 0):g}" if mat.get("type") == "RC" else f"fy {mat.get('fy', 0):g}"
            ins("G_mat", f"MAT_{mid}", f"{mid}: {mat['name']}  ({mat.get('type')}, {sub}, E={E:,.0f})",
                use_m.get(mid, 0), ("drag",))
        ins("G_props", "G_sec", "▥  Section", len(m["sections"]), ("sub",))
        for sid, sec in m["sections"].items():
            ins("G_sec", f"SEC_{sid}", f"{sid}: {sec['name']}   {fm.section_desc(sec)}",
                use_s.get(sid, 0), ("drag",))

        ins("", "G_bnd", "⊥  Boundaries", "", ("grp",))
        ins("G_bnd", "G_sup", "▲  Supports", len(m["supports"]), ("sub",))
        for sid, st in m["sup_types"].items():
            nodes = [n for n, s in m["supports"].items() if s == sid]
            ins("G_sup", f"ST_{sid}", f"{st['name']}   ({fm.support_desc(st)})",
                len(nodes), ("drag",))
            for n in sorted(nodes):
                ins(f"ST_{sid}", f"SUP_{n}", f"N{n}", "", ("dim",))
        nrel = sum(1 for e in m["elems"].values() if not fm.is_rigid(e))
        ins("G_bnd", "G_rel", "◦  End Releases (고정률)", nrel, ("sub",))
        by_type = {}
        other = []
        for i, e in m["elems"].items():
            rid = fm.rel_type_of(m, e)
            if rid is None:
                other.append(i)
            else:
                by_type.setdefault(rid, []).append(i)
        for rid, rt in m["rel_types"].items():
            els = by_type.get(rid, [])
            ins("G_rel", f"RL_{rid}", f"{rt['name']}   ({fm.end_desc(rt['fi'], rt['fj'])})",
                len(els), ("drag",))
            if not (rt["fi"] >= 1 and rt["fj"] >= 1):
                for i in els:
                    ins(f"RL_{rid}", f"RE_{i}", f"E{i}", "", ("dim",))
        if other:
            ins("G_rel", "RLX", "개별 고정률", len(other), ("dim",))
            for i in other:
                ins("RLX", f"RE_{i}", f"E{i}   ({fm.end_desc(*fm.end_fix(m['elems'][i]))})", "", ("dim",))

        ins("", "G_loads", "⬇  Loads", "", ("grp",))
        ins("G_loads", "G_cases", "▧  Load Cases", len(m["cases"]), ("sub",))
        for cid, cs in m["cases"].items():
            nl = [ld for ld in m["nloads"] if ld["case"] == cid]
            el = [ld for ld in m["eloads"] if ld["case"] == cid]
            sw = f"  (자중×{float(cs.get('selfweight', 0)):g})" if float(cs.get("selfweight", 0) or 0) else ""
            mark = "  ◀" if cid == self.active_case else ""
            ins("G_cases", f"CASE_{cid}", f"{cs['name']}{sw}{mark}", len(nl) + len(el), ("load",))
            for ld in nl:
                ins(f"CASE_{cid}", f"NL_{ld['id']}", load_text(ld), "", ("dim",))
            for ld in el:
                ins(f"CASE_{cid}", f"EL_{ld['id']}", load_text(ld), "", ("dim",))
        ins("G_loads", "G_combos", "Σ  Combinations", len(m["combos"]), ("sub",))
        for coid, co in m["combos"].items():
            ins("G_combos", f"CO_{coid}", f"{co['name']}   = {combo_text(m, co)}")

        keep = [i for i in sel if t.exists(i)]
        self._tree_set_sel(keep)
        t.yview_moveto(y)

    def _tree_set_sel(self, ids):
        """프로그램에서 트리 선택 변경. <<TreeviewSelect>> 는 나중에(비동기) 오므로
        기대 선택값을 기억해 두고 이벤트 처리 시 같으면 무시한다."""
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
            for i in ("G_struct", "G_props", "G_bnd", "G_loads"):
                self.tree.item(i, open=True)

    def sync_tree_selection(self):
        t = getattr(self, "tree", None)
        if t is None:
            return
        ids = [f"N_{n}" for n in self.sel_nodes] + [f"E_{e}" for e in self.sel_elems]
        ids = [i for i in ids if t.exists(i)]
        self._tree_set_sel(ids)
        if len(ids) == 1:
            t.see(ids[0])

    # ── 선택 / 편집 ─────────────────────────────────────────
    def _tree_select(self, e=None, force=False):
        sel = self.tree.selection()
        if not sel or (not force and set(sel) == getattr(self, "_tree_expected", None)):
            return
        self._tree_expected = None
        nodes, elems = set(), set()
        target = None
        for iid in sel:
            k, _, v = iid.partition("_")
            if k == "N" or k == "SUP":
                nodes.add(int(v))
            elif k == "E" or k == "RE":
                elems.add(int(v))
            elif k in ("MAT", "SEC", "ST", "CASE", "CO", "RL"):
                target = (k, int(v))
            elif k in ("NL", "EL"):
                target = (k, int(v))
        if nodes or elems:
            self.sel_nodes, self.sel_elems = nodes, elems
            self.edit_target = None
            self.redraw()
            self.show_editor()
            self.refresh_result_detail()
        elif target:
            self.edit_target = target
            if target[0] == "CASE" and target[1] != self.active_case:
                self.set_active_case(target[1])
            if target[0] in ("NL", "EL"):
                ld = self.find_load(target)
                if ld and ld["case"] != self.active_case:
                    self.set_active_case(ld["case"])
                self.sel_load_ids = {target[1]}
                self.redraw()
            self.show_editor()

    def tree_edit(self):
        sel = self.tree.selection()
        if not sel:
            return
        self._tree_select(force=True)
        self.nb.select(self.tab_input)

    def tree_add(self, kind):
        m = self.model
        self.push_undo()
        if kind == "MAT":
            i = fm.next_id(m["materials"])
            m["materials"][i] = {"name": f"C{24 + 3 * (i - 1)}" if i < 6 else f"M{i}",
                                 "type": "RC", "fck": 24.0 + 3 * (i - 1), "fy": 400.0,
                                 "E": 0.0, "gamma": 24.0}
        elif kind == "SEC":
            i = fm.next_id(m["sections"])
            m["sections"][i] = {"name": f"S{i}", "shape": "rect", "b": 400, "h": 600}
        elif kind == "ST":
            i = fm.next_id(m["sup_types"])
            m["sup_types"][i] = {"name": f"지점{i}", "dx": 1, "dy": 1, "rz": 0, "fix": 0,
                                 "kx": 0, "ky": 0, "kr": 0}
        elif kind == "RL":
            i = fm.next_id(m["rel_types"])
            m["rel_types"][i] = {"name": f"반강접 {i}", "fi": 0.5, "fj": 0.5}
        elif kind == "CASE":
            i = fm.next_id(m["cases"])
            m["cases"][i] = {"name": f"LC{i}", "selfweight": 0.0}
        elif kind == "CO":
            i = fm.next_id(m["combos"])
            m["combos"][i] = {"name": f"COMB{i}", "factors": {c: 1.0 for c in m["cases"]}}
        self.edit_target = (kind, i)
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
        groups = {}
        for iid in sel:
            k, _, v = iid.partition("_")
            groups.setdefault(k, []).append(v)
        if "N" in groups or "E" in groups:
            self.sel_nodes = {int(v) for v in groups.get("N", [])}
            self.sel_elems = {int(v) for v in groups.get("E", [])}
            self.delete_selected()
            return
        self.push_undo()
        msgs = []
        for v in groups.get("MAT", []):
            i = int(v)
            if any(e["mat"] == i for e in m["elems"].values()):
                msgs.append(f"재료 '{m['materials'][i]['name']}' 는 부재에서 사용 중")
            elif len(m["materials"]) > 1:
                m["materials"].pop(i)
        for v in groups.get("SEC", []):
            i = int(v)
            if any(e["sec"] == i for e in m["elems"].values()):
                msgs.append(f"단면 '{m['sections'][i]['name']}' 는 부재에서 사용 중")
            elif len(m["sections"]) > 1:
                m["sections"].pop(i)
        for v in groups.get("ST", []):
            i = int(v)
            m["sup_types"].pop(i, None)
            m["supports"] = {n: s for n, s in m["supports"].items() if s != i}
        for v in groups.get("RL", []):
            m["rel_types"].pop(int(v), None)          # 부재의 고정률 값은 그대로 유지
        for v in groups.get("SUP", []):
            m["supports"].pop(int(v), None)
        for v in groups.get("RE", []):
            e = m["elems"].get(int(v))
            if e:
                fm.set_end_fix(e, 1.0, 1.0)
        for v in groups.get("CASE", []):
            i = int(v)
            if len(m["cases"]) <= 1:
                msgs.append("하중케이스는 최소 1개 필요"); continue
            m["cases"].pop(i, None)
            m["nloads"] = [ld for ld in m["nloads"] if ld["case"] != i]
            m["eloads"] = [ld for ld in m["eloads"] if ld["case"] != i]
            for co in m["combos"].values():
                co["factors"].pop(i, None)
        for v in groups.get("CO", []):
            m["combos"].pop(int(v), None)
        ids = {int(v) for v in groups.get("NL", []) + groups.get("EL", [])}
        if ids:
            m["nloads"] = [ld for ld in m["nloads"] if ld["id"] not in ids]
            m["eloads"] = [ld for ld in m["eloads"] if ld["id"] not in ids]
        d = m["defaults"]
        if d.get("mat") not in m["materials"]:
            d["mat"] = min(m["materials"])
        if d.get("sec") not in m["sections"]:
            d["sec"] = min(m["sections"])
        if d.get("sup") not in m["sup_types"] and m["sup_types"]:
            d["sup"] = min(m["sup_types"])
        self.edit_target = None
        self.changed("삭제됨")
        if msgs:
            messagebox.showinfo("삭제 안 됨", "\n".join(msgs), parent=self.win)

    def _tree_menu(self, e):
        iid = self.tree.identify_row(e.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        menu = tk.Menu(self.win, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC,
                       activeforeground=WHI, font=FONT)
        k = iid.partition("_")[0] if iid else ""
        add_map = {"G_mat": "MAT", "MAT": "MAT", "G_sec": "SEC", "SEC": "SEC",
                   "G_sup": "ST", "ST": "ST", "G_cases": "CASE", "CASE": "CASE",
                   "G_combos": "CO", "CO": "CO", "G_rel": "RL", "RL": "RL"}
        kind = add_map.get(iid) or add_map.get(k)
        if kind:
            lbl = {"MAT": "재료", "SEC": "단면", "ST": "지점 타입", "CASE": "하중케이스",
                   "CO": "하중조합", "RL": "단부조건"}[kind]
            menu.add_command(label=f"＋ {lbl} 추가", command=lambda: self.tree_add(kind))
        if k in DRAG_KINDS:
            need = DRAG_KINDS[k]
            n_sel = len(self.sel_nodes if need == "node" else self.sel_elems)
            what = "노드" if need == "node" else "부재"
            menu.add_command(label=f"⇢ 선택한 {what} {n_sel}개에 적용",
                             state="normal" if n_sel else "disabled",
                             command=lambda: self.apply_tree_item(iid))
        if k in ("MAT", "SEC", "ST", "CASE", "CO", "RL", "NL", "EL", "N", "E"):
            menu.add_command(label="✎ 편집", command=self.tree_edit)
        if k == "SEC":
            menu.add_command(label="새 부재 기본 단면으로", command=lambda: self._set_default("sec", int(iid[4:])))
        if k == "MAT":
            menu.add_command(label="새 부재 기본 재료로", command=lambda: self._set_default("mat", int(iid[4:])))
        if k == "CASE":
            menu.add_command(label="활성 하중케이스로", command=lambda: self.set_active_case(int(iid[5:])))
        if k == "SEC" or k == "MAT" or k == "ST":
            menu.add_command(label="사용 중인 부재/노드 선택", command=lambda: self._select_users(iid))
        if k and not iid.startswith("G_") and k != "RLX":
            menu.add_separator()
            menu.add_command(label="🗑 삭제", command=self.tree_delete)
        if menu.index("end") is not None:
            menu.tk_popup(e.x_root, e.y_root)

    def _set_default(self, key, i):
        self.model["defaults"][key] = i
        self.show_editor()
        self.msg("기본값 변경")

    def _select_users(self, iid):
        k, _, v = iid.partition("_")
        i = int(v)
        m = self.model
        if k == "ST":
            self.sel_nodes = {n for n, s in m["supports"].items() if s == i}
            self.sel_elems = set()
        else:
            key = "sec" if k == "SEC" else "mat"
            self.sel_elems = {eid for eid, e in m["elems"].items() if e[key] == i}
            self.sel_nodes = set()
        self._selection_changed()

    # ════════════════════════════════════════════════════════
    #  드래그 앤 드롭 (트리 → 캔버스)
    # ════════════════════════════════════════════════════════
    def _tree_press(self, e):
        iid = self.tree.identify_row(e.y)
        k = iid.partition("_")[0] if iid else ""
        self._drag = None
        if k in DRAG_KINDS:
            self._drag = {"iid": iid, "kind": k, "x": e.x_root, "y": e.y_root, "active": False}

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
            need = DRAG_KINDS[d["kind"]]
            tgt = "부재" if need == "elem" else "노드"
            n_sel = len(self.sel_elems if need == "elem" else self.sel_nodes)
            hint = (f"선택 {tgt} {n_sel}개 (캔버스 아무 곳에 놓기)" if n_sel
                    else f"{tgt}에 놓기")
            tk.Label(tw, text=f"  {text}  →  {hint}  ", font=FONT_B, bg=ACC,
                     fg=WHI, padx=4, pady=3).pack()
            self.tree.config(cursor="hand2")
        if self._drag_win:
            self._drag_win.geometry(f"+{e.x_root + 14}+{e.y_root + 10}")
        tgt = self._drop_target(e.x_root, e.y_root, d["kind"])
        if tgt != self.drop_hover:
            self.drop_hover = tgt
            self.redraw()
            if tgt and tgt[1] is not None:
                self.st_info.config(text="놓으면 지정: " + self._describe(tgt))
            elif tgt:
                n = len(self.sel_nodes if tgt[0] == "node" else self.sel_elems)
                self.st_info.config(text=f"놓으면 선택된 {'노드' if tgt[0] == 'node' else '부재'} {n}개에 지정")
        return "break"

    def _drop_target(self, xr, yr, kind):
        w = self.win.winfo_containing(xr, yr)
        if w is not self.canvas:
            return None
        cx = xr - self.canvas.winfo_rootx()
        cy = yr - self.canvas.winfo_rooty()
        if DRAG_KINDS[kind] == "node":
            n = self.hit_node(cx, cy, tol=16)
            if n is not None:
                return ("node", n)
            return ("node", None) if self.sel_nodes else None     # 빈 곳 → 선택 노드 전체
        el = self.hit_elem(cx, cy, tol=12)
        if el is not None:
            return ("elem", el)
        return ("elem", None) if self.sel_elems else None          # 빈 곳 → 선택 부재 전체

    def _tree_release(self, e):
        d = self._drag
        self._drag = None
        if self._drag_win:
            self._drag_win.destroy()
            self._drag_win = None
        self.tree.config(cursor="")
        if not d or not d["active"]:
            return
        tgt = self._drop_target(e.x_root, e.y_root, d["kind"])
        self.drop_hover = None
        if not tgt:
            self.redraw()
            self.msg("놓을 위치에 부재/노드가 없습니다.", ORG)
            return
        kind, i = tgt
        sel = self.sel_nodes if kind == "node" else self.sel_elems
        targets = sorted(sel) if (i is None or i in sel) else [i]
        self._apply_item(d["iid"], targets)

    def apply_tree_item(self, iid):
        """트리 항목(재료·단면·지점·단부조건)을 현재 선택에 적용"""
        k = iid.partition("_")[0]
        need = DRAG_KINDS.get(k)
        if not need:
            return
        targets = sorted(self.sel_nodes if need == "node" else self.sel_elems)
        if not targets:
            self.msg(f"먼저 캔버스에서 {'노드' if need == 'node' else '부재'}를 선택하세요.", ORG)
            return
        self._apply_item(iid, targets)

    def _apply_item(self, iid, targets):
        k, _, v = iid.partition("_")
        if DRAG_KINDS[k] == "node":
            targets = [t for t in targets if t in self.model["nodes"]]
            self.assign_support(targets, int(v))
        elif k == "SEC":
            self.assign_elem(targets, sec=int(v))
        elif k == "MAT":
            self.assign_elem(targets, mat=int(v))
        else:
            self.assign_release(targets, int(v))


# ── 표시 문자열 ─────────────────────────────────────────────
def load_text(ld):
    if "node" in ld:
        parts = []
        for k, lbl in (("fx", "Fx"), ("fy", "Fy"), ("mz", "Mz")):
            v = float(ld.get(k, 0) or 0)
            if abs(v) > 1e-12:
                parts.append(f"{lbl}={v:g}")
        return f"절점 N{ld['node']}: " + (", ".join(parts) or "0")
    d = fm.LOAD_DIR_LABEL.get(ld.get("dir", "G"), ld.get("dir", "")).split(" (")[0]
    unit = "" if ld.get("rel") else "m"
    if ld["kind"] == "point":
        return f"집중 E{ld['elem']}: P={float(ld.get('p', 0)):g} kN @ {float(ld.get('a', 0)):g}{unit or '·L'}  {d}"
    w1, w2 = float(ld.get("w1", 0)), float(ld.get("w2", 0))
    w = f"{w1:g}" if abs(w1 - w2) < 1e-12 else f"{w1:g}~{w2:g}"
    a, b = float(ld.get("a", 0)), float(ld.get("b", 1))
    rng = "" if (ld.get("rel") and a == 0 and b == 1) else f" [{a:g}~{b:g}{unit or '·L'}]"
    return f"분포 E{ld['elem']}: w={w} kN/m{rng}  {d}"


def combo_text(m, co):
    parts = []
    for cid, f in co.get("factors", {}).items():
        cs = m["cases"].get(cid)
        if cs and abs(f) > 1e-12:
            parts.append(f"{f:g}×{cs['name']}")
    return " + ".join(parts) or "-"
