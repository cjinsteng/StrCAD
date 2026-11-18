"""
design_2d/section/input_tab.py — 입력(속성 편집) 탭

선택 상태에 따라 편집 화면이 바뀐다.
  · 아무것도 선택 안 함 → 모델 설정 + 좌표로 노드/부재 입력
  · 노드 1개            → 좌표, 지점
  · 부재 1개            → 부재명, 재료, 단면(크기 입력 시 단면 목록에 자동 추가), 단부해제
  · 여러 개             → 일괄 지정
  · 트리에서 재료/단면/지점타입/하중케이스/조합/하중 선택 → 해당 편집
"""

import math
import tkinter as tk
from tkinter import ttk, messagebox

from . import model as fm
from .theme import *
from .tree_tab import load_text


class InputTabMixin:

    def _build_input_tab(self, nb):
        f = tk.Frame(nb, bg=BG2)
        nb.add(f, text=" 입력 ")
        self.tab_input = f
        self.inp_head = tk.Label(f, text="", font=FONT_H, bg=BG3, fg=WHI, anchor="w",
                                 padx=10, pady=6)
        self.inp_head.pack(fill="x")
        self.inp_scroll = ScrollFrame(f)
        self.inp_scroll.pack(fill="both", expand=True, padx=(8, 0), pady=4)

    def _head(self, text, color=WHI):
        self.inp_head.config(text=text, fg=color)

    # ════════════════════════════════════════════════════════
    def show_editor(self):
        sc = getattr(self, "inp_scroll", None)
        if sc is None:
            return
        sc.clear()
        body = sc.inner
        t = self.edit_target
        m = self.model
        try:
            if t:
                k, i = t
                fn = {"MAT": self._ed_material, "SEC": self._ed_section, "ST": self._ed_suptype,
                      "CASE": self._ed_case, "CO": self._ed_combo,
                      "NL": self._ed_load, "EL": self._ed_load}.get(k)
                if fn:
                    fn(body, *((t,) if k in ("NL", "EL") else (i,)))
                    return
            nn, ne = len(self.sel_nodes), len(self.sel_elems)
            if nn == 1 and ne == 0:
                self._ed_node(body, next(iter(self.sel_nodes)))
            elif ne == 1 and nn == 0:
                self._ed_elem(body, next(iter(self.sel_elems)))
            elif nn or ne:
                self._ed_multi(body)
            else:
                self._ed_model(body)
        except KeyError:
            self.edit_target = None
            sc.clear()
            self._ed_model(sc.inner)

    # ── 공통 ─────────────────────────────────────────────────
    def _btn_row(self, parent, items):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", pady=(12, 4))
        for text, cmd, bg in items:
            btn(row, text, cmd, bg=bg, fg=WHI if bg != BG3 else TXT,
                font=FONT_B, padx=12, pady=4).pack(side="left", padx=(0, 4))
        return row

    def _names(self, key):
        return [f"{i}: {v['name']}" for i, v in self.model[key].items()]

    @staticmethod
    def _id_of(s):
        try:
            return int(str(s).split(":")[0])
        except Exception:
            return None

    def _pick(self, key, i):
        v = self.model[key].get(i)
        return f"{i}: {v['name']}" if v else ""

    # ════════════════════════════════════════════════════════
    #  모델 (선택 없음)
    # ════════════════════════════════════════════════════════
    def _ed_model(self, body):
        m = self.model
        self._head("모델 입력", CYN)
        section_title(body, "모델 설정")
        fm_ = Form(body)
        self._v_grid = tk.StringVar(value=f"{m.get('grid', 0.5):g}")
        fm_.row("격자 간격", lambda p: entry(p, self._v_grid, 8), "m")
        d = m["defaults"]
        self._v_dmat = tk.StringVar(value=self._pick("materials", d.get("mat")))
        self._v_dsec = tk.StringVar(value=self._pick("sections", d.get("sec")))
        fm_.row("새 부재 재료", lambda p: combo(p, self._v_dmat, self._names("materials")))
        fm_.row("새 부재 단면", lambda p: combo(p, self._v_dsec, self._names("sections")))

        def apply_settings():
            g = parse_float(self._v_grid.get())
            if not g or g <= 0:
                messagebox.showwarning("입력", "격자 간격을 확인하세요.", parent=self.win); return
            m["grid"] = g
            d["mat"] = self._id_of(self._v_dmat.get()) or d.get("mat")
            d["sec"] = self._id_of(self._v_dsec.get()) or d.get("sec")
            self.dirty = True; self._update_title()
            self.redraw(); self.msg("설정 적용")
        self._btn_row(body, [("적용", apply_settings, ACC)])

        section_title(body, "노드 입력 (좌표)", GRNH)
        f2 = Form(body)
        self._v_nx = tk.StringVar(value="0"); self._v_ny = tk.StringVar(value="0")
        e1 = f2.row("X", lambda p: entry(p, self._v_nx, 10), "m")
        f2.row("Y", lambda p: entry(p, self._v_ny, 10), "m")

        def add_node(_=None):
            x, y = parse_float(self._v_nx.get()), parse_float(self._v_ny.get())
            if x is None or y is None:
                return
            self.push_undo()
            nid = fm.add_node(m, x, y)
            self.changed(f"노드 N{nid} ({x:g}, {y:g})")
            e1.focus_set()
        e1.bind("<Return>", add_node)
        self._btn_row(body, [("＋ 노드 추가", add_node, GRN)])

        section_title(body, "부재 입력 (노드 번호)", GRNH)
        f3 = Form(body)
        self._v_ni = tk.StringVar(); self._v_nj = tk.StringVar()
        f3.row("i 노드", lambda p: entry(p, self._v_ni, 10))
        f3.row("j 노드", lambda p: entry(p, self._v_nj, 10))

        def add_elem():
            try:
                ni, nj = int(self._v_ni.get()), int(self._v_nj.get())
            except ValueError:
                return
            if ni not in m["nodes"] or nj not in m["nodes"] or ni == nj:
                messagebox.showwarning("입력", "노드 번호를 확인하세요.", parent=self.win); return
            self.push_undo()
            eid = fm.add_elem(m, ni, nj)
            self.changed(f"부재 E{eid} (N{ni}→N{nj})")
        self._btn_row(body, [("＋ 부재 추가", add_elem, GRN)])

        section_title(body, "사용 방법", TX3)
        tips = ("① [노드]·[부재] 모드로 캔버스에 직접 그리거나 [프레임 생성] 사용\n"
                "② 부재/노드를 클릭 → 이 탭에서 부재명·단면 크기·지점 입력\n"
                "③ [트리] 탭의 단면·재료·지점을 캔버스로 끌어다 놓아도 지정됨\n"
                "④ [하중] 탭에서 하중 입력 → ▶ 해석 실행 (F5)\n"
                "⑤ 툴바 M·V·N·변형·반력 버튼으로 결과 확인, [결과] 탭에서 표")
        tk.Label(body, text=tips, font=FONT_S, bg=BG2, fg=TX2, justify="left",
                 anchor="w").pack(fill="x", padx=4)

    # ════════════════════════════════════════════════════════
    #  노드
    # ════════════════════════════════════════════════════════
    def _ed_node(self, body, nid):
        m = self.model
        n = m["nodes"][nid]
        self._head(f"노드  N{nid}", C_NODE)
        section_title(body, "좌표")
        f = Form(body)
        vx = tk.StringVar(value=f"{n['x']:g}"); vy = tk.StringVar(value=f"{n['y']:g}")
        ex = f.row("X", lambda p: entry(p, vx, 10), "m")
        ey = f.row("Y", lambda p: entry(p, vy, 10), "m")

        section_title(body, "지점", C_SUP)
        f2 = Form(body)
        sup_names = ["없음"] + self._names("sup_types")
        vs = tk.StringVar(value=self._pick("sup_types", m["supports"].get(nid)) or "없음")
        f2.row("지점 타입", lambda p: combo(p, vs, sup_names))
        st = m["sup_types"].get(m["supports"].get(nid))
        f2.text("구속", fm.support_desc(st) if st else "-", TX2)

        def apply(_=None):
            x, y = parse_float(vx.get()), parse_float(vy.get())
            if x is None or y is None:
                return
            other = fm.find_node_at(m, x, y)
            if other is not None and other != nid:
                messagebox.showwarning("입력", f"같은 위치에 노드 N{other} 가 있습니다.", parent=self.win)
                return
            self.push_undo()
            n["x"], n["y"] = round(x, 6), round(y, 6)
            sid = self._id_of(vs.get())
            if sid is None:
                m["supports"].pop(nid, None)
            else:
                m["supports"][nid] = sid
            self.changed(f"노드 N{nid} 수정")
        ex.bind("<Return>", apply); ey.bind("<Return>", apply)
        self._btn_row(body, [("적용", apply, ACC), ("삭제", self.delete_selected, RED)])

        conn = [eid for eid, e in m["elems"].items() if nid in (e["ni"], e["nj"])]
        section_title(body, f"연결 부재 ({len(conn)})", TX3)
        tk.Label(body, text=", ".join(f"E{i}" for i in conn) or "-", font=FONT, bg=BG2,
                 fg=TX2, anchor="w", justify="left", wraplength=280).pack(fill="x", padx=4)
        self._load_list(body, [ld for ld in m["nloads"] if ld["node"] == nid])

    # ════════════════════════════════════════════════════════
    #  부재
    # ════════════════════════════════════════════════════════
    def _ed_elem(self, body, eid):
        m = self.model
        e = m["elems"][eid]
        a, b = m["nodes"][e["ni"]], m["nodes"][e["nj"]]
        L = fm.elem_length(m, eid)
        ang = math.degrees(math.atan2(b["y"] - a["y"], b["x"] - a["x"]))
        self._head(f"부재  E{eid}   {e.get('name', '')}", C_SEL)

        section_title(body, "일반")
        f = Form(body)
        v_name = tk.StringVar(value=e.get("name", ""))
        en = f.row("부재명", lambda p: entry(p, v_name, 14))
        f.text("노드", f"N{e['ni']} → N{e['nj']}")
        f.text("길이 / 각도", f"{L:.3f} m   /   {ang:.1f}°")
        v_mat = tk.StringVar(value=self._pick("materials", e["mat"]))
        f.row("재료", lambda p: combo(p, v_mat, self._names("materials")))

        # ── 단면 ──
        section_title(body, "단면 (크기 입력 → 단면 목록에 추가)", CYN)
        sec = m["sections"].get(e["sec"], {"name": "", "shape": "rect", "b": 400, "h": 600})
        sf = SectionFields(body, sec, sections=m["sections"], show_pick=True)
        # 부재명과 단면명이 같으면 부재명 입력 시 단면명도 따라감
        linked = [not sec.get("name") or sec.get("name") == e.get("name", "") or not e.get("name")]

        def on_name(*_):
            if linked[0]:
                sf.v_name.set(v_name.get())
        v_name.trace_add("write", on_name)
        sf.v_name.trace_add("write", lambda *_: linked.__setitem__(0, sf.v_name.get() == v_name.get()))

        section_title(body, "단부 해제 (힌지)", C_SEL)
        rf = tk.Frame(body, bg=BG2); rf.pack(fill="x", padx=4)
        v_ri = tk.BooleanVar(value=bool(e.get("rel_i"))); v_rj = tk.BooleanVar(value=bool(e.get("rel_j")))
        check(rf, f"i단 (N{e['ni']}) 힌지", v_ri).pack(side="left")
        check(rf, f"j단 (N{e['nj']}) 힌지", v_rj).pack(side="left", padx=12)

        def apply(_=None):
            spec = sf.get()
            if spec is None:
                return
            self.push_undo()
            sid = self._resolve_section(spec, e["sec"])
            if sid is None:
                self.undo_stack.pop(); self._refresh_undo_btns()
                return
            e["name"] = v_name.get().strip()
            e["mat"] = self._id_of(v_mat.get()) or e["mat"]
            e["sec"] = sid
            e["rel_i"], e["rel_j"] = bool(v_ri.get()), bool(v_rj.get())
            self.changed(f"부재 E{eid} 수정 — 단면 '{m['sections'][sid]['name']}'")
        en.bind("<Return>", apply)
        self._btn_row(body, [("적용", apply, ACC), ("2등분", lambda: self.split_selected(2), BG3),
                             ("삭제", self.delete_selected, RED)])
        self._load_list(body, [ld for ld in m["eloads"] if ld["elem"] == eid])

    def _resolve_section(self, spec, cur_sid):
        """입력한 단면(이름+형상+치수) → 단면 id.
        · 같은 이름이 있고 치수도 같으면 그 단면
        · 같은 이름인데 치수가 다르면 → 단면 수정 / 새 단면 추가 선택
        · 없으면 새 단면 추가 (같은 치수의 단면이 있어도 이름이 다르면 새로 만든다)"""
        m = self.model
        name = spec["name"].strip()
        if not name:
            # 이름이 비면 같은 치수 단면 재사용, 없으면 자동 이름
            for sid, s in m["sections"].items():
                if same_section(s, spec):
                    return sid
            name = f"S{fm.next_id(m['sections'])}"
            spec["name"] = name
        same = [sid for sid, s in m["sections"].items() if s["name"] == name]
        if same:
            sid = same[0]
            if same_section(m["sections"][sid], spec):
                return sid
            users = sum(1 for el in m["elems"].values() if el["sec"] == sid)
            ans = messagebox.askyesnocancel(
                "단면 변경",
                f"단면 '{name}' 의 크기가 바뀌었습니다.\n\n"
                f"[예]      단면 '{name}' 수정 (사용 부재 {users}개 모두 변경)\n"
                f"[아니오]  새 단면으로 추가", parent=self.win)
            if ans is None:
                return None
            if ans:
                m["sections"][sid].update(spec)
                return sid
            k = 2
            while any(s["name"] == f"{name}-{k}" for s in m["sections"].values()):
                k += 1
            spec["name"] = f"{name}-{k}"
        sid = fm.next_id(m["sections"])
        m["sections"][sid] = dict(spec)
        self.msg(f"단면 '{spec['name']}' 이(가) 단면 목록에 추가되었습니다.", GRNH)
        return sid

    # ════════════════════════════════════════════════════════
    #  다중 선택
    # ════════════════════════════════════════════════════════
    def _ed_multi(self, body):
        m = self.model
        nn, ne = len(self.sel_nodes), len(self.sel_elems)
        self._head(f"다중 선택   노드 {nn} · 부재 {ne}", C_SEL)
        if nn:
            section_title(body, f"노드 {nn}개 — 지점", C_SUP)
            f = Form(body)
            vs = tk.StringVar(value="")
            f.row("지점 타입", lambda p: combo(p, vs, ["없음"] + self._names("sup_types")))

            def apply_sup():
                if not vs.get():
                    return
                self.assign_support(sorted(self.sel_nodes), self._id_of(vs.get()))
            self._btn_row(body, [("지점 적용", apply_sup, ACC)])
        if ne:
            section_title(body, f"부재 {ne}개 — 일괄 지정 (빈칸 = 유지)", CYN)
            f = Form(body)
            v_name = tk.StringVar(); v_mat = tk.StringVar(); v_sec = tk.StringVar(); v_rel = tk.StringVar()
            f.row("부재명", lambda p: entry(p, v_name, 14))
            f.row("재료", lambda p: combo(p, v_mat, [""] + self._names("materials")))
            f.row("단면", lambda p: combo(p, v_sec, [""] + self._names("sections")))
            f.row("단부해제", lambda p: combo(p, v_rel, [""] + [l for _, l in fm.RELEASE_PRESETS]))

            def apply_el():
                eids = sorted(self.sel_elems)
                self.push_undo()
                for i in eids:
                    el = m["elems"][i]
                    if v_name.get().strip():
                        el["name"] = v_name.get().strip()
                    if self._id_of(v_mat.get()):
                        el["mat"] = self._id_of(v_mat.get())
                    if self._id_of(v_sec.get()):
                        el["sec"] = self._id_of(v_sec.get())
                    if v_rel.get():
                        code = {l: c for c, l in fm.RELEASE_PRESETS}[v_rel.get()]
                        el["rel_i"] = code in ("i", "ij"); el["rel_j"] = code in ("j", "ij")
                self.changed(f"부재 {len(eids)}개 일괄 수정")
            self._btn_row(body, [("부재 적용", apply_el, ACC)])
        self._btn_row(body, [("선택 항목 삭제", self.delete_selected, RED)])

    # ════════════════════════════════════════════════════════
    #  재료 / 단면 / 지점타입 / 하중케이스 / 조합
    # ════════════════════════════════════════════════════════
    def _ed_material(self, body, mid):
        m = self.model
        mat = m["materials"][mid]
        self._head(f"재료  {mat['name']}", CYN)
        section_title(body, "재료 속성")
        f = Form(body)
        v = {k: tk.StringVar(value=f"{mat.get(k, 0):g}" if isinstance(mat.get(k, 0), (int, float)) else str(mat.get(k, "")))
             for k in ("fck", "fy", "E", "gamma")}
        v_name = tk.StringVar(value=mat["name"])
        v_type = tk.StringVar(value=mat.get("type", "RC"))
        f.row("이름", lambda p: entry(p, v_name, 14))
        f.row("종류", lambda p: combo(p, v_type, ["RC", "STEEL"], 10))
        f.row("fck", lambda p: entry(p, v["fck"], 10), "MPa (RC)")
        f.row("fy", lambda p: entry(p, v["fy"], 10), "MPa")
        f.row("E (0=자동)", lambda p: entry(p, v["E"], 10), "MPa")
        f.row("단위중량 γ", lambda p: entry(p, v["gamma"], 10), "kN/m³")
        auto = f.text("적용 E", f"{fm.material_E(mat):,.0f} MPa", CYN)
        tk.Label(body, text="RC: Ec = 8500·∛(fck+Δf)  (KDS 14 20 10)\nSTEEL: E = 210,000 MPa (KDS 41 30 10)",
                 font=FONT_S, bg=BG2, fg=TX3, justify="left").pack(anchor="w", padx=4, pady=4)

        def apply():
            vals = {k: parse_float(v[k].get(), 0.0) for k in v}
            self.push_undo()
            mat.update(name=v_name.get().strip() or mat["name"], type=v_type.get(), **vals)
            self.edit_target = ("MAT", mid)
            self.changed(f"재료 '{mat['name']}' 수정")

        def on_type(*_):
            if v_type.get() == "STEEL" and parse_float(v["gamma"].get(), 0) == 24:
                v["gamma"].set("78.5")
                if parse_float(v["E"].get(), 0) == 0:
                    v["E"].set("210000")
                if parse_float(v["fy"].get(), 0) in (0, 400):
                    v["fy"].set("275")
            elif v_type.get() == "RC" and parse_float(v["gamma"].get(), 0) == 78.5:
                v["gamma"].set("24"); v["E"].set("0")
        v_type.trace_add("write", on_type)
        self._btn_row(body, [("적용", apply, ACC),
                             ("기본 재료로", lambda: self._set_default("mat", mid), BG3)])

    def _ed_section(self, body, sid):
        m = self.model
        sec = m["sections"][sid]
        users = sum(1 for e in m["elems"].values() if e["sec"] == sid)
        self._head(f"단면  {sec['name']}", CYN)
        section_title(body, f"단면 속성 (사용 부재 {users}개)")
        sf = SectionFields(body, sec)

        def apply():
            spec = sf.get()
            if spec is None:
                return
            self.push_undo()
            sec.clear(); sec.update(spec)
            self.edit_target = ("SEC", sid)
            self.changed(f"단면 '{sec['name']}' 수정")
        self._btn_row(body, [("적용", apply, ACC),
                             ("기본 단면으로", lambda: self._set_default("sec", sid), BG3),
                             ("사용 부재 선택", lambda: self._select_users(f"SEC_{sid}"), BG3)])

    def _ed_suptype(self, body, sid):
        m = self.model
        st = m["sup_types"][sid]
        users = sum(1 for s in m["supports"].values() if s == sid)
        self._head(f"지점 타입  {st['name']}", C_SUP)
        section_title(body, f"구속 조건 (사용 노드 {users}개)", C_SUP)
        f = Form(body)
        v_name = tk.StringVar(value=st["name"])
        f.row("이름", lambda p: entry(p, v_name, 14))
        cf = tk.Frame(body, bg=BG2); cf.pack(fill="x", padx=4, pady=4)
        vd = {k: tk.BooleanVar(value=bool(st.get(k))) for k in ("dx", "dy", "rz")}
        check(cf, "Dx 구속", vd["dx"]).pack(side="left")
        check(cf, "Dy 구속", vd["dy"]).pack(side="left", padx=10)
        check(cf, "Rz 구속", vd["rz"]).pack(side="left")
        section_title(body, "회전 구속률 / 스프링", C_SEL)
        f2 = Form(body)
        vf = tk.StringVar(value=f"{float(st.get('fix', 0) or 0):g}")
        ef = f2.row("회전 구속률", lambda p: entry(p, vf, 10), "% (0=핀, 100=고정)")
        vk = {k: tk.StringVar(value=f"{float(st.get(k, 0) or 0):g}") for k in ("kx", "ky", "kr")}
        f2.row("kx 스프링", lambda p: entry(p, vk["kx"], 10), "kN/m")
        f2.row("ky 스프링", lambda p: entry(p, vk["ky"], 10), "kN/m")
        f2.row("kr 회전스프링", lambda p: entry(p, vk["kr"], 10), "kN·m/rad")
        tk.Label(body, text="구속률 γ: kr = γ/(1-γ)·Σ(3EI/L) (연결 부재 기준)\n"
                            "Rz 구속을 체크하면 구속률은 무시됩니다.",
                 font=FONT_S, bg=BG2, fg=TX3, justify="left").pack(anchor="w", padx=4, pady=4)

        def on_rz(*_):
            ef.config(state="disabled" if vd["rz"].get() else "normal")
        vd["rz"].trace_add("write", on_rz); on_rz()

        def apply():
            fix = parse_float(vf.get(), 0.0)
            if not (0 <= fix <= 100):
                messagebox.showwarning("입력", "구속률은 0~100% 입니다.", parent=self.win); return
            self.push_undo()
            st.update(name=v_name.get().strip() or st["name"],
                      dx=int(vd["dx"].get()), dy=int(vd["dy"].get()), rz=int(vd["rz"].get()),
                      fix=fix, **{k: max(0.0, parse_float(vk[k].get(), 0.0)) for k in vk})
            self.edit_target = ("ST", sid)
            self.changed(f"지점 타입 '{st['name']}' 수정")

        def assign_sel():
            if self.sel_nodes:
                self.assign_support(sorted(self.sel_nodes), sid)
        self._btn_row(body, [("적용", apply, ACC), ("선택 노드에 지정", assign_sel, BG3)])

    def _ed_case(self, body, cid):
        m = self.model
        cs = m["cases"][cid]
        n = sum(1 for ld in m["nloads"] + m["eloads"] if ld["case"] == cid)
        self._head(f"하중케이스  {cs['name']}", C_LOAD)
        section_title(body, f"하중케이스 (하중 {n}개)", C_LOAD)
        f = Form(body)
        v_name = tk.StringVar(value=cs["name"])
        v_sw = tk.StringVar(value=f"{float(cs.get('selfweight', 0) or 0):g}")
        f.row("이름", lambda p: entry(p, v_name, 14))
        f.row("자중 계수", lambda p: entry(p, v_sw, 8), "(0=자중 없음, 1=자중 포함)")
        tk.Label(body, text="자중 = 재료 단위중량 × 단면적 (부재 길이 방향 등분포, 중력방향)",
                 font=FONT_S, bg=BG2, fg=TX3).pack(anchor="w", padx=4, pady=4)

        def apply():
            self.push_undo()
            cs["name"] = v_name.get().strip() or cs["name"]
            cs["selfweight"] = parse_float(v_sw.get(), 0.0)
            self.edit_target = ("CASE", cid)
            self.changed(f"하중케이스 '{cs['name']}' 수정")
        self._btn_row(body, [("적용", apply, ACC),
                             ("활성 케이스로", lambda: self.set_active_case(cid), BG3)])

    def _ed_combo(self, body, coid):
        m = self.model
        co = m["combos"][coid]
        self._head(f"하중조합  {co['name']}", C_LOAD)
        section_title(body, "조합 계수", C_LOAD)
        f = Form(body)
        v_name = tk.StringVar(value=co["name"])
        f.row("이름", lambda p: entry(p, v_name, 16))
        vs = {}
        for cid, cs in m["cases"].items():
            vs[cid] = tk.StringVar(value=f"{co['factors'].get(cid, 0):g}")
            f.row(f"× {cs['name']}", lambda p, v=vs[cid]: entry(p, v, 8))

        def apply():
            self.push_undo()
            co["name"] = v_name.get().strip() or co["name"]
            co["factors"] = {cid: parse_float(v.get(), 0.0) for cid, v in vs.items()
                             if parse_float(v.get(), 0.0) != 0}
            self.edit_target = ("CO", coid)
            self.changed(f"하중조합 '{co['name']}' 수정")
        self._btn_row(body, [("적용", apply, ACC)])
        tk.Label(body, text="KDS 41 10 15 예: 1.4D / 1.2D+1.6L / 1.2D+1.0L+1.0E",
                 font=FONT_S, bg=BG2, fg=TX3).pack(anchor="w", padx=4)

    # ── 하중 개별 편집 ──────────────────────────────────────
    def _ed_load(self, body, target):
        ld = self.find_load(target)
        if ld is None:
            self.edit_target = None; self._ed_model(body); return
        m = self.model
        self._head(f"하중  #{ld['id']}", C_LOAD)
        section_title(body, load_text(ld), C_LOAD)
        f = Form(body)
        v_case = tk.StringVar(value=self._pick("cases", ld["case"]))
        f.row("하중케이스", lambda p: combo(p, v_case, self._names("cases")))
        vs = {}
        if target[0] == "NL":
            f.text("노드", f"N{ld['node']}")
            for k, lbl, u in (("fx", "Fx", "kN (→+)"), ("fy", "Fy", "kN (↑+)"), ("mz", "Mz", "kN·m (반시계+)")):
                vs[k] = tk.StringVar(value=f"{float(ld.get(k, 0)):g}")
                f.row(lbl, lambda p, v=vs[k]: entry(p, v, 10), u)
        else:
            f.text("부재", f"E{ld['elem']}  (L={fm.elem_length(m, ld['elem']):.3f} m)")
            v_dir = tk.StringVar(value=fm.LOAD_DIR_LABEL.get(ld.get("dir", "G")))
            f.row("방향", lambda p: combo(p, v_dir, [l for _, l in fm.LOAD_DIRS]))
            v_rel = tk.BooleanVar(value=bool(ld.get("rel")))
            keys = (("p", "P", "kN"), ("a", "위치 a", "")) if ld["kind"] == "point" else \
                (("w1", "w1 (시작)", "kN/m"), ("w2", "w2 (끝)", "kN/m"), ("a", "시작 a", ""), ("b", "끝 b", ""))
            for k, lbl, u in keys:
                vs[k] = tk.StringVar(value=f"{float(ld.get(k, 0)):g}")
                f.row(lbl, lambda p, v=vs[k]: entry(p, v, 10), u)
            check(body, "위치를 비율(0~1)로 입력", v_rel).pack(anchor="w", padx=4)

        def apply():
            self.push_undo()
            ld["case"] = self._id_of(v_case.get()) or ld["case"]
            for k, v in vs.items():
                ld[k] = parse_float(v.get(), 0.0)
            if target[0] == "EL":
                ld["dir"] = fm.LOAD_DIR_CODE.get(v_dir.get(), "G")
                ld["rel"] = bool(v_rel.get())
            self.edit_target = target
            self.changed("하중 수정")

        def delete():
            self.push_undo()
            m["nloads"] = [x for x in m["nloads"] if x is not ld]
            m["eloads"] = [x for x in m["eloads"] if x is not ld]
            self.edit_target = None
            self.changed("하중 삭제")
        self._btn_row(body, [("적용", apply, ACC), ("삭제", delete, RED)])

    def find_load(self, target):
        k, i = target
        lst = self.model["nloads"] if k == "NL" else self.model["eloads"]
        return next((ld for ld in lst if ld["id"] == i), None)

    def _load_list(self, body, loads):
        section_title(body, f"하중 ({len(loads)})", C_LOAD)
        if not loads:
            tk.Label(body, text="없음 — [하중] 탭에서 입력", font=FONT_S, bg=BG2,
                     fg=TX3).pack(anchor="w", padx=4)
            return
        for ld in loads:
            row = tk.Frame(body, bg=BG2); row.pack(fill="x", padx=2, pady=1)
            cs = self.model["cases"].get(ld["case"], {}).get("name", "?")
            tk.Label(row, text=f"[{cs}] {load_text(ld)}", font=FONT_S, bg=BG2, fg=TXT,
                     anchor="w", justify="left", wraplength=250).pack(side="left", fill="x", expand=True)
            kind = "NL" if "node" in ld else "EL"

            def rm(l=ld):
                self.push_undo()
                self.model["nloads"] = [x for x in self.model["nloads"] if x is not l]
                self.model["eloads"] = [x for x in self.model["eloads"] if x is not l]
                self.changed("하중 삭제")
            btn(row, "✕", rm, fg=RED, padx=4, pady=0).pack(side="right")
            btn(row, "✎", lambda t=(kind, ld["id"]): self._edit_load_target(t),
                padx=4, pady=0).pack(side="right")

    def _edit_load_target(self, t):
        self.edit_target = t
        self.show_editor()


# ═══════════════════════════════════════════════════════════════
#  단면 입력 위젯 (형상 선택 → 치수 입력 → A, I 자동 계산)
# ═══════════════════════════════════════════════════════════════
def same_section(a, b):
    if a.get("shape") != b.get("shape"):
        return False
    for k in fm.SHAPE_DIMS.get(a.get("shape"), []):
        if abs(float(a.get(k, 0) or 0) - float(b.get(k, 0) or 0)) > 1e-9:
            return False
    return True


class SectionFields:
    def __init__(self, parent, sec, sections=None, show_pick=False):
        self.sections = sections or {}
        self.frame = tk.Frame(parent, bg=BG2)
        self.frame.pack(fill="x")
        f = Form(self.frame)
        self.v_name = tk.StringVar(value=sec.get("name", ""))
        if show_pick:
            cur = next((f"{i}: {s['name']}  {fm.section_desc(s)}" for i, s in self.sections.items()
                        if s is sec), "")
            self.v_pick = tk.StringVar(value=cur)
            cb = f.row("목록에서 선택", lambda p: combo(
                p, self.v_pick, [f"{i}: {s['name']}  {fm.section_desc(s)}" for i, s in self.sections.items()], 20))
            cb.bind("<<ComboboxSelected>>", self._on_pick)
        f.row("단면명", lambda p: entry(p, self.v_name, 14))
        self.v_shape = tk.StringVar(value=fm.SHAPE_LABEL.get(sec.get("shape", "rect")))
        cs = f.row("형상", lambda p: combo(p, self.v_shape, [l for _, l, _ in fm.SECTION_SHAPES], 12))
        cs.bind("<<ComboboxSelected>>", lambda e: self._build_dims())
        self.vals = {k: tk.StringVar(value=f"{float(sec.get(k, 0) or 0):g}")
                     for k in fm.DIM_LABEL}
        for k in self.vals:
            if not float(sec.get(k, 0) or 0):
                self.vals[k].set({"b": "400", "h": "600", "H": "400", "B": "200", "tw": "8",
                                  "tf": "13", "t": "9", "D": "500", "A": "0", "I": "0"}[k])
            self.vals[k].trace_add("write", lambda *_: self._calc())
        self.dims = tk.Frame(self.frame, bg=BG2)
        self.dims.pack(fill="x")
        self.props = tk.Label(self.frame, text="", font=FONT_M, bg=BG2, fg=CYN, anchor="w",
                              justify="left")
        self.props.pack(fill="x", padx=4, pady=(2, 0))
        self._build_dims()

    def _shape(self):
        return fm.SHAPE_CODE.get(self.v_shape.get(), "rect")

    def _build_dims(self):
        for w in self.dims.winfo_children():
            w.destroy()
        f = Form(self.dims)
        for k in fm.SHAPE_DIMS[self._shape()]:
            f.row(fm.DIM_LABEL[k], lambda p, v=self.vals[k]: entry(p, v, 10))
        self._calc()

    def _on_pick(self, e=None):
        sid = InputTabMixin._id_of(self.v_pick.get())
        s = self.sections.get(sid)
        if not s:
            return
        self.v_name.set(s["name"])
        self.v_shape.set(fm.SHAPE_LABEL[s["shape"]])
        for k in fm.SHAPE_DIMS[s["shape"]]:
            self.vals[k].set(f"{float(s.get(k, 0)):g}")
        self._build_dims()

    def spec(self):
        sh = self._shape()
        d = {"name": self.v_name.get().strip(), "shape": sh}
        for k in fm.SHAPE_DIMS[sh]:
            v = parse_float(self.vals[k].get())
            if v is None:
                return None
            d[k] = v
        return d

    def _calc(self):
        s = self.spec()
        if not s:
            self.props.config(text="치수를 확인하세요", fg=RED); return
        A, I = fm.section_props(s)
        self.props.config(text=f"A = {A:,.0f} mm²   I = {I:,.4g} mm⁴", fg=CYN if A > 0 else RED)

    def get(self):
        s = self.spec()
        if not s:
            messagebox.showwarning("단면", "단면 치수를 확인하세요.")
            return None
        A, I = fm.section_props(s)
        if A <= 0 or I <= 0:
            messagebox.showwarning("단면", "단면 성질(A, I)이 0 이하입니다. 치수를 확인하세요.")
            return None
        return s
