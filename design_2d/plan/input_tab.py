"""
design_2d/plan/input_tab.py — 입력 탭 (선택에 따라 편집 화면 전환)
  · 선택 없음 → 모델 설정(격자·메시크기·비틀림계수), 좌표로 노드/선/면 입력, 노드 복사
  · 노드 → 좌표, 지점        · 선 → 보 적용(단면 크기 입력 시 목록 자동 추가), 선 지점
  · 면 → 슬래브 적용(두께 입력 시 슬래브 타입 자동 추가), 비구조 면 하중 전달 방식
  · 여러 개 → 일괄 적용       · 트리 항목 → 재료/단면/슬래브/지점/케이스/조합/하중 편집
"""

import tkinter as tk
from tkinter import ttk, messagebox

from . import model as pm
from ..section.theme import *
from ..section.input_tab import SectionFields, same_section
from .tree_tab import load_text


class InputTabMixin:

    def _build_input_tab(self, nb):
        f = tk.Frame(nb, bg=BG2)
        nb.add(f, text=" 입력 ")
        self.tab_input = f
        self.inp_head = tk.Label(f, text="", font=FONT_H, bg=BG3, fg=WHI, anchor="w", padx=10, pady=6)
        self.inp_head.pack(fill="x")
        self.inp_scroll = ScrollFrame(f)
        self.inp_scroll.pack(fill="both", expand=True, padx=(8, 0), pady=4)

    def _head(self, text, color=WHI):
        self.inp_head.config(text=text, fg=color)

    def _names(self, key):
        return [f"{i}: {v['name']}" for i, v in self.model[key].items()]

    def _pick(self, key, i):
        v = self.model[key].get(i)
        return f"{i}: {v['name']}" if v else ""

    @staticmethod
    def _id_of(s):
        try:
            return int(str(s).split(":")[0])
        except Exception:
            return None

    def _btn_row(self, parent, items):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", pady=(10, 4))
        for text, cmd, bg in items:
            btn(row, text, cmd, bg=bg, fg=WHI if bg != BG3 else TXT, font=FONT_B,
                padx=10, pady=4).pack(side="left", padx=(0, 4))

    def show_editor(self):
        sc = getattr(self, "inp_scroll", None)
        if sc is None:
            return
        sc.clear()
        body = sc.inner
        t = self.edit_target
        try:
            if t:
                k, i = t
                fn = {"MAT": self._ed_material, "SEC": self._ed_section, "SLB": self._ed_slab,
                      "ST": self._ed_suptype, "CASE": self._ed_case, "CO": self._ed_combo}.get(k)
                if fn:
                    fn(body, i); return
                if k in ("NL", "LL", "AL"):
                    self._ed_load(body, t); return
            c = {k: len(v) for k, v in self.sel.items()}
            tot = sum(c.values())
            if tot == 1:
                k = next(k for k, v in c.items() if v)
                i = next(iter(self.sel[k]))
                {"node": self._ed_node, "line": self._ed_line, "area": self._ed_area}[k](body, i)
            elif tot:
                self._ed_multi(body)
            else:
                self._ed_model(body)
        except KeyError:
            self.edit_target = None
            sc.clear()
            self._ed_model(sc.inner)

    # ════════════════════════════════════════════════════════
    def _ed_model(self, body):
        m = self.model
        self._head("모델 입력", CYN)
        section_title(body, "모델 설정")
        f = Form(body, lw=13)
        v = {k: tk.StringVar(value=f"{float(m.get(k, d)):g}") for k, d in
             (("grid", 0.5), ("mesh_size", 0.5), ("torsion_factor", 1.0))}
        f.row("격자 간격", lambda p: entry(p, v["grid"], 8), "m")
        f.row("메시 크기", lambda p: entry(p, v["mesh_size"], 8), "m (정밀: 0.25)")
        f.row("보 비틀림 계수", lambda p: entry(p, v["torsion_factor"], 8), "× GJ (0~1)")
        NM = {"avg": "요소 외삽 평균 (Midas 방식)", "spr": "SPR 패치 복원"}
        v_nm = tk.StringVar(value=NM.get(m.get("nodal_method", "avg")))
        f.row("슬래브 절점값", lambda p: combo(p, v_nm, list(NM.values()), 22))
        d = m["defaults"]
        vd = {k: tk.StringVar(value=self._pick(key, d.get(k))) for k, key in
              (("sec", "sections"), ("slab", "slabs"), ("mat", "materials"))}
        f.row("기본 보 단면", lambda p: combo(p, vd["sec"], self._names("sections")))
        f.row("기본 슬래브", lambda p: combo(p, vd["slab"], self._names("slabs")))
        f.row("기본 보 재료", lambda p: combo(p, vd["mat"], self._names("materials")))

        def apply():
            vals = {k: parse_float(x.get()) for k, x in v.items()}
            if not vals["grid"] or vals["grid"] <= 0 or not vals["mesh_size"] or vals["mesh_size"] < 0.05:
                messagebox.showwarning("입력", "격자 간격/메시 크기를 확인하세요 (메시 ≥ 0.05 m).", parent=self.win)
                return
            self.push_undo()
            m["grid"], m["mesh_size"] = vals["grid"], vals["mesh_size"]
            m["torsion_factor"] = min(1.0, max(0.0, vals["torsion_factor"] or 0.0))
            m["nodal_method"] = {v_: k for k, v_ in NM.items()}.get(v_nm.get(), "avg")
            for k in vd:
                d[k] = self._id_of(vd[k].get()) or d.get(k)
            self.changed("설정 적용")
        self._btn_row(body, [("적용", apply, ACC)])

        section_title(body, "좌표로 노드 추가", GRNH)
        f2 = Form(body, lw=13)
        vx = tk.StringVar(value="0"); vy = tk.StringVar(value="0")
        e1 = f2.row("X", lambda p: entry(p, vx, 10), "m")
        f2.row("Y", lambda p: entry(p, vy, 10), "m")

        def add_node(_=None):
            x, y = parse_float(vx.get()), parse_float(vy.get())
            if x is None or y is None:
                return
            self.push_undo()
            nid = pm.add_node(m, x, y)
            self.changed(f"노드 N{nid} ({x:g}, {y:g})")
            e1.focus_set()
        e1.bind("<Return>", add_node)
        self._btn_row(body, [("＋ 노드", add_node, GRN)])

        section_title(body, "노드 번호로 선 / 면 추가", GRNH)
        f3 = Form(body, lw=13)
        vl = tk.StringVar(); va = tk.StringVar()
        f3.row("선 (i, j)", lambda p: entry(p, vl, 14), "예: 1, 2")
        f3.row("면 (노드 순서)", lambda p: entry(p, va, 14), "예: 1,2,5,4")

        def add_line():
            try:
                a, b = [int(s) for s in vl.get().replace(" ", "").split(",")[:2]]
            except ValueError:
                return
            if a not in m["nodes"] or b not in m["nodes"]:
                messagebox.showwarning("입력", "노드 번호를 확인하세요.", parent=self.win); return
            self.push_undo()
            lids = pm.add_line(m, a, b)
            self.changed(f"선 {len(lids)}개 추가")

        def add_area():
            try:
                ns = [int(s) for s in va.get().replace(" ", "").split(",") if s]
            except ValueError:
                return
            if len(ns) < 3 or any(n not in m["nodes"] for n in ns):
                messagebox.showwarning("입력", "노드 3개 이상을 순서대로 입력하세요.", parent=self.win); return
            self.push_undo()
            aid = pm.add_area(m, ns)
            if aid is None:
                self.undo_stack.pop(); return
            self.changed(f"면 A{aid} 추가")
        self._btn_row(body, [("＋ 선", add_line, GRN), ("＋ 면", add_area, GRN)])
        self._copy_section(body, [])

        section_title(body, "사용 방법", TX3)
        tk.Label(body, font=FONT_S, bg=BG2, fg=TX2, justify="left", anchor="w", text=(
            "① [노드]·[선] 모드로 그리기 (또는 ▦ 격자 생성)\n"
            "② [면] 모드: 선으로 닫힌 영역 클릭 → 면 생성\n"
            "③ 선 → 보, 면 → 슬래브, 노드 → 지점 적용\n"
            "    (입력 탭 / 우클릭 / 트리 항목 드래그)\n"
            "④ [하중] 탭: 노드·선·면 하중 (비구조 선·면도 가능)\n"
            "⑤ ▶ 해석 → 슬래브 Mx·My·Qx·Qy·처짐, 보 M·V, 반력")).pack(fill="x", padx=4)

    # ── 노드 ─────────────────────────────────────────────────
    def _ed_node(self, body, nid):
        m = self.model
        n = m["nodes"][nid]
        self._head(f"노드  N{nid}", C_NODE)
        section_title(body, "좌표")
        f = Form(body)
        vx = tk.StringVar(value=f"{n['x']:g}"); vy = tk.StringVar(value=f"{n['y']:g}")
        f.row("X", lambda p: entry(p, vx, 10), "m")
        f.row("Y", lambda p: entry(p, vy, 10), "m")
        section_title(body, "지점 (기둥)", C_SUP)
        f2 = Form(body)
        vs = tk.StringVar(value=self._pick("sup_types", m["supports"].get(nid)) or "없음")
        f2.row("지점 타입", lambda p: combo(p, vs, ["없음"] + self._names("sup_types"), 18))
        st = m["sup_types"].get(m["supports"].get(nid))
        f2.text("구속", pm.support_desc(st) if st else "-", TX2)

        def apply():
            x, y = parse_float(vx.get()), parse_float(vy.get())
            if x is None or y is None:
                return
            o = pm.find_node_at(m, x, y)
            if o is not None and o != nid:
                messagebox.showwarning("입력", f"같은 위치에 노드 N{o} 가 있습니다.", parent=self.win); return
            self.push_undo()
            n["x"], n["y"] = round(x, 6), round(y, 6)
            sid = self._id_of(vs.get())
            if sid is None:
                m["supports"].pop(nid, None)
            else:
                m["supports"][nid] = sid
            self.changed(f"노드 N{nid} 수정")
        self._btn_row(body, [("적용", apply, ACC), ("삭제", self.delete_selected, RED)])
        self._copy_section(body, [nid])
        self._load_list(body, [("NL", ld) for ld in m["nloads"] if ld["node"] == nid])

    # ── 선 ───────────────────────────────────────────────────
    def _ed_line(self, body, lid):
        m = self.model
        ln = m["lines"][lid]
        self._head(f"선  L{lid}   {ln.get('name', '')}", C_SEL)
        section_title(body, "일반")
        f = Form(body)
        v_name = tk.StringVar(value=ln.get("name", ""))
        f.row("부재명", lambda p: entry(p, v_name, 14))
        f.text("노드 / 길이", f"N{ln['ni']} → N{ln['nj']}   {pm.line_length(m, lid):.3f} m")
        v_kind = tk.StringVar(value=ln["kind"])
        rf = tk.Frame(body, bg=BG2); rf.pack(fill="x", padx=4, pady=4)
        radio(rf, "비구조 선 (하중만)", v_kind, "none").pack(side="left")
        radio(rf, "보로 적용", v_kind, "beam").pack(side="left", padx=12)

        bf = tk.Frame(body, bg=BG2); bf.pack(fill="x")
        section_title(bf, "보 단면 (크기 입력 → 단면 목록에 추가)", CYN)
        sec = m["sections"].get(ln["sec"], {"name": "", "shape": "rect", "b": 400, "h": 600})
        sf = SectionFields(bf, sec, sections=m["sections"], show_pick=True)
        f2 = Form(bf)
        v_mat = tk.StringVar(value=self._pick("materials", ln["mat"]))
        f2.row("재료", lambda p: combo(p, v_mat, self._names("materials")))
        linked = [not sec.get("name") or sec.get("name") == ln.get("name") or not ln.get("name")]
        v_name.trace_add("write", lambda *_: linked[0] and sf.v_name.set(v_name.get()))
        sf.v_name.trace_add("write", lambda *_: linked.__setitem__(0, sf.v_name.get() == v_name.get()))

        section_title(body, "선 지점 (벽체)", C_SUP)
        f3 = Form(body)
        v_ls = tk.StringVar(value=self._pick("sup_types", m["line_supports"].get(lid)) or "없음")
        f3.row("지점 타입", lambda p: combo(p, v_ls, ["없음"] + self._names("sup_types"), 18))

        def apply():
            self.push_undo()
            if v_kind.get() == "beam":
                spec = sf.get()
                if spec is None:
                    self.undo_stack.pop(); self._refresh_undo_btns(); return
                sid = self._resolve_section(spec)
                if sid is None:
                    self.undo_stack.pop(); self._refresh_undo_btns(); return
                ln["sec"] = sid
                ln["mat"] = self._id_of(v_mat.get()) or ln["mat"]
            ln["kind"] = v_kind.get()
            ln["name"] = v_name.get().strip()
            s = self._id_of(v_ls.get())
            if s is None:
                m["line_supports"].pop(lid, None)
            else:
                m["line_supports"][lid] = s
            self.changed(f"선 L{lid} 수정" + (f" — 보 '{m['sections'][ln['sec']]['name']}'" if ln["kind"] == "beam" else ""))
        self._btn_row(body, [("적용", apply, ACC), ("삭제", self.delete_selected, RED)])
        self._load_list(body, [("LL", ld) for ld in m["lloads"] if ld["line"] == lid])

    def _resolve_section(self, spec):
        m = self.model
        name = spec["name"].strip()
        if not name:
            for sid, s in m["sections"].items():
                if same_section(s, spec):
                    return sid
            name = spec["name"] = f"G{pm.next_id(m['sections'])}"
        same = [sid for sid, s in m["sections"].items() if s["name"] == name]
        if same:
            sid = same[0]
            if same_section(m["sections"][sid], spec):
                return sid
            users = sum(1 for l in m["lines"].values() if l["sec"] == sid and l["kind"] == "beam")
            ans = messagebox.askyesnocancel(
                "단면 변경", f"단면 '{name}' 의 크기가 바뀌었습니다.\n\n[예]  단면 수정 (사용 보 {users}개 모두)\n"
                             f"[아니오]  새 단면으로 추가", parent=self.win)
            if ans is None:
                return None
            if ans:
                m["sections"][sid].update(spec); return sid
            k = 2
            while any(s["name"] == f"{name}-{k}" for s in m["sections"].values()):
                k += 1
            spec["name"] = f"{name}-{k}"
        sid = pm.next_id(m["sections"])
        m["sections"][sid] = dict(spec)
        self.msg(f"단면 '{spec['name']}' 이(가) 목록에 추가되었습니다.", GRNH)
        return sid

    # ── 면 ───────────────────────────────────────────────────
    def _ed_area(self, body, aid):
        m = self.model
        ar = m["areas"][aid]
        self._head(f"면  A{aid}   {ar.get('name', '')}", C_SEL)
        section_title(body, "일반")
        f = Form(body)
        v_name = tk.StringVar(value=ar.get("name", ""))
        f.row("이름", lambda p: entry(p, v_name, 14))
        f.text("꼭짓점", ", ".join(f"N{n}" for n in ar["nodes"]))
        f.text("넓이", f"{pm.area_of(m, aid):.3f} m²")
        v_kind = tk.StringVar(value=ar["kind"])
        rf = tk.Frame(body, bg=BG2); rf.pack(fill="x", padx=4, pady=4)
        radio(rf, "비구조 면 (하중 전달)", v_kind, "none").pack(side="left")
        radio(rf, "슬래브로 적용", v_kind, "slab").pack(side="left", padx=12)

        section_title(body, "슬래브 (두께 입력 → 슬래브 목록에 추가)", CYN)
        f2 = Form(body)
        sl = m["slabs"].get(ar["slab"], {"name": "S1", "t": 150, "mat": 1})
        v_sl = tk.StringVar(value=self._pick("slabs", ar["slab"]))
        v_t = tk.StringVar(value=f"{float(sl['t']):g}")
        cb = f2.row("슬래브 타입", lambda p: combo(p, v_sl, self._names("slabs")))
        f2.row("두께 t", lambda p: entry(p, v_t, 8), "mm")
        cb.bind("<<ComboboxSelected>>", lambda e: v_t.set(
            f"{m['slabs'][self._id_of(v_sl.get())]['t']:g}"))

        section_title(body, "비구조 면 하중 전달", C_LOAD)
        f3 = Form(body)
        v_dist = tk.StringVar(value=pm.AREA_DIST_LABEL.get(ar.get("dist", "two")))
        f3.row("전달 방식", lambda p: combo(p, v_dist, [l for _, l in pm.AREA_DIST], 18))
        tk.Label(body, text="2방향: 가까운 둘레 선으로 (사다리꼴/삼각형)\n1방향: 지정 방향 양쪽 둘레 선으로",
                 font=FONT_S, bg=BG2, fg=TX3, justify="left").pack(anchor="w", padx=4)

        def apply():
            t = parse_float(v_t.get())
            if v_kind.get() == "slab" and (t is None or t <= 0):
                messagebox.showwarning("입력", "두께를 확인하세요.", parent=self.win); return
            self.push_undo()
            if v_kind.get() == "slab":
                sid = self._id_of(v_sl.get()) or ar["slab"]
                if abs(float(m["slabs"][sid]["t"]) - t) > 1e-9:
                    sid = self._resolve_slab(t, m["slabs"][sid]["mat"])
                ar["slab"] = sid
            ar["kind"] = v_kind.get()
            ar["name"] = v_name.get().strip()
            ar["dist"] = pm.AREA_DIST_CODE.get(v_dist.get(), "two")
            self.changed(f"면 A{aid} 수정")
            if ar["kind"] == "slab":
                from .mesh import _corners
                if len(_corners(m, ar["nodes"])) != 4:
                    messagebox.showwarning("슬래브", "꼭짓점이 4개가 아닌 면은 슬래브로 해석할 수 없습니다.\n"
                                           "사각형으로 나눠 주세요.", parent=self.win)
        self._btn_row(body, [("적용", apply, ACC), ("삭제", self.delete_selected, RED)])
        self._load_list(body, [("AL", ld) for ld in m["aloads"] if ld["area"] == aid])

    def _resolve_slab(self, t, mat):
        m = self.model
        for sid, s in m["slabs"].items():
            if abs(float(s["t"]) - t) < 1e-9 and s["mat"] == mat:
                return sid
        sid = pm.next_id(m["slabs"])
        name = f"S{t:g}"
        k = 2
        while any(s["name"] == name for s in m["slabs"].values()):
            name = f"S{t:g}-{k}"; k += 1
        m["slabs"][sid] = {"name": name, "t": t, "mat": mat}
        self.msg(f"슬래브 '{name}' (t={t:g}) 이(가) 목록에 추가되었습니다.", GRNH)
        return sid

    # ── 다중 ─────────────────────────────────────────────────
    def _ed_multi(self, body):
        m = self.model
        c = {k: len(v) for k, v in self.sel.items()}
        self._head(f"다중 선택  노드 {c['node']} · 선 {c['line']} · 면 {c['area']}", C_SEL)
        if c["node"]:
            section_title(body, f"노드 {c['node']}개 — 지점", C_SUP)
            f = Form(body)
            vs = tk.StringVar()
            f.row("지점 타입", lambda p: combo(p, vs, ["없음"] + self._names("sup_types"), 18))
            self._btn_row(body, [("지점 적용", lambda: vs.get() and self.assign_support(
                sorted(self.sel["node"]), self._id_of(vs.get())), ACC)])
        if c["line"]:
            section_title(body, f"선 {c['line']}개 — 보 적용", CYN)
            f = Form(body)
            v_sec = tk.StringVar(); v_mat = tk.StringVar(); v_ls = tk.StringVar()
            f.row("보 단면", lambda p: combo(p, v_sec, self._names("sections")))
            f.row("재료", lambda p: combo(p, v_mat, [""] + self._names("materials")))
            f.row("선 지점", lambda p: combo(p, v_ls, ["", "없음"] + self._names("sup_types")))

            def ap_line():
                ids = sorted(self.sel["line"])
                if v_ls.get():
                    self.assign_line_support(ids, self._id_of(v_ls.get()))
                if v_sec.get() or v_mat.get():
                    self.assign_beam(ids, sec=self._id_of(v_sec.get()), mat=self._id_of(v_mat.get()))
            self._btn_row(body, [("보로 적용", ap_line, ACC),
                                 ("비구조로", lambda: self.unassign("line", sorted(self.sel["line"])), BG3)])
        if c["area"]:
            section_title(body, f"면 {c['area']}개 — 슬래브 적용", CYN)
            f = Form(body)
            v_sl = tk.StringVar(); v_d = tk.StringVar()
            f.row("슬래브", lambda p: combo(p, v_sl, self._names("slabs")))
            f.row("비구조 전달", lambda p: combo(p, v_d, [""] + [l for _, l in pm.AREA_DIST], 18))

            def ap_area():
                ids = sorted(self.sel["area"])
                if v_d.get():
                    self.set_dist(ids, pm.AREA_DIST_CODE[v_d.get()])
                if v_sl.get():
                    self.assign_slab(ids, self._id_of(v_sl.get()))
            self._btn_row(body, [("슬래브로 적용", ap_area, ACC),
                                 ("비구조로", lambda: self.unassign("area", sorted(self.sel["area"])), BG3)])
        nodes = set(self.sel["node"])
        for l in self.sel["line"]:
            nodes |= {m["lines"][l]["ni"], m["lines"][l]["nj"]}
        for a in self.sel["area"]:
            nodes |= set(m["areas"][a]["nodes"])
        self._copy_section(body, sorted(nodes))
        self._btn_row(body, [("선택 항목 삭제", self.delete_selected, RED)])

    # ── 노드 복사 ───────────────────────────────────────────
    def _copy_section(self, body, nids):
        section_title(body, "노드 복사 / 이동", GRNH)
        st = self.__dict__.setdefault("_copy_state", {"dx": "6", "dy": "0", "n": "1", "l": True,
                                                       "a": True, "x": False})
        f = Form(body)
        v_ids = tk.StringVar(value=pm.ids_text(nids))
        v_dx = tk.StringVar(value=st["dx"]); v_dy = tk.StringVar(value=st["dy"]); v_n = tk.StringVar(value=st["n"])
        f.row("대상 노드", lambda p: entry(p, v_ids, 16), "예: 1-4, 7")
        f.row("간격 dx", lambda p: entry(p, v_dx, 8), "m")
        f.row("간격 dy", lambda p: entry(p, v_dy, 8), "m")
        f.row("복사 횟수", lambda p: entry(p, v_n, 8), "회")
        vl, va, vx = tk.BooleanVar(value=st["l"]), tk.BooleanVar(value=st["a"]), tk.BooleanVar(value=st["x"])
        cf = tk.Frame(body, bg=BG2); cf.pack(fill="x", padx=4)
        check(cf, "대상 노드 사이의 선(보)도 복사", vl).pack(anchor="w")
        check(cf, "대상 노드로 이루어진 면(슬래브)도 복사", va).pack(anchor="w")
        check(cf, "지점·하중도 복사", vx).pack(anchor="w")

        def run(move):
            try:
                ids = pm.parse_ids(v_ids.get())
            except ValueError:
                messagebox.showwarning("노드 복사", "대상 노드 번호를 확인하세요.", parent=self.win); return
            dx, dy = parse_float(v_dx.get()), parse_float(v_dy.get())
            try:
                n = int(float(v_n.get()))
            except ValueError:
                n = 0
            if dx is None or dy is None or (not move and not 1 <= n <= 100):
                messagebox.showwarning("노드 복사", "간격·횟수를 확인하세요.", parent=self.win); return
            st.update(dx=v_dx.get(), dy=v_dy.get(), n=v_n.get(), l=vl.get(), a=va.get(), x=vx.get())
            self.copy_nodes_cmd(ids, dx, dy, n, vl.get(), va.get(), vx.get(), move=move)
        self._btn_row(body, [("⧉ 복사", lambda: run(False), GRN), ("➜ 이동", lambda: run(True), BG3)])

    # ════════════════════════════════════════════════════════
    #  속성 편집
    # ════════════════════════════════════════════════════════
    def _ed_material(self, body, mid):
        m = self.model
        mat = m["materials"][mid]
        self._head(f"재료  {mat['name']}", CYN)
        section_title(body, "재료 속성")
        f = Form(body)
        v = {k: tk.StringVar(value=f"{float(mat.get(k, 0) or 0):g}") for k in ("fck", "fy", "E", "gamma", "nu")}
        v_name = tk.StringVar(value=mat["name"]); v_type = tk.StringVar(value=mat.get("type", "RC"))
        f.row("이름", lambda p: entry(p, v_name, 14))
        f.row("종류", lambda p: combo(p, v_type, ["RC", "STEEL"], 10))
        f.row("fck", lambda p: entry(p, v["fck"], 10), "MPa")
        f.row("fy", lambda p: entry(p, v["fy"], 10), "MPa")
        f.row("E (0=자동)", lambda p: entry(p, v["E"], 10), "MPa")
        f.row("단위중량 γ", lambda p: entry(p, v["gamma"], 10), "kN/m³")
        f.row("포아송비 ν", lambda p: entry(p, v["nu"], 10), "")
        f.text("적용 E", f"{pm.material_E(mat):,.0f} MPa", CYN)

        def apply():
            vals = {k: parse_float(x.get(), 0.0) for k, x in v.items()}
            if not 0 <= vals["nu"] < 0.5:
                messagebox.showwarning("입력", "포아송비는 0 ~ 0.5 입니다.", parent=self.win); return
            self.push_undo()
            mat.update(name=v_name.get().strip() or mat["name"], type=v_type.get(), **vals)
            self.edit_target = ("MAT", mid)
            self.changed(f"재료 '{mat['name']}' 수정")
        self._btn_row(body, [("적용", apply, ACC)])

    def _ed_section(self, body, sid):
        m = self.model
        sec = m["sections"][sid]
        self._head(f"보 단면  {sec['name']}", CYN)
        section_title(body, "단면 속성")
        sf = SectionFields(body, sec)
        tk.Label(body, text=f"비틀림상수 J = {pm.torsion_J(sec):,.4g} mm⁴", font=FONT_M, bg=BG2,
                 fg=CYN).pack(anchor="w", padx=4)

        def apply():
            spec = sf.get()
            if spec is None:
                return
            self.push_undo()
            sec.clear(); sec.update(spec)
            self.edit_target = ("SEC", sid)
            self.changed(f"단면 '{sec['name']}' 수정")
        self._btn_row(body, [("적용", apply, ACC),
                             ("선택 선에 보로 적용", lambda: self.assign_beam(sorted(self.sel["line"]), sec=sid), BG3)])

    def _ed_slab(self, body, sid):
        m = self.model
        sl = m["slabs"][sid]
        self._head(f"슬래브  {sl['name']}", CYN)
        section_title(body, "슬래브 타입")
        f = Form(body)
        v_name = tk.StringVar(value=sl["name"]); v_t = tk.StringVar(value=f"{float(sl['t']):g}")
        v_mat = tk.StringVar(value=self._pick("materials", sl["mat"]))
        f.row("이름", lambda p: entry(p, v_name, 14))
        f.row("두께 t", lambda p: entry(p, v_t, 8), "mm")
        f.row("재료", lambda p: combo(p, v_mat, self._names("materials")))

        def apply():
            t = parse_float(v_t.get())
            if not t or t <= 0:
                return
            self.push_undo()
            sl.update(name=v_name.get().strip() or sl["name"], t=t, mat=self._id_of(v_mat.get()) or sl["mat"])
            self.edit_target = ("SLB", sid)
            self.changed(f"슬래브 '{sl['name']}' 수정")
        self._btn_row(body, [("적용", apply, ACC),
                             ("선택 면에 적용", lambda: self.assign_slab(sorted(self.sel["area"]), sid), BG3)])

    def _ed_suptype(self, body, sid):
        m = self.model
        st = m["sup_types"][sid]
        self._head(f"지점 타입  {st['name']}", C_SUP)
        section_title(body, "구속", C_SUP)
        f = Form(body)
        v_name = tk.StringVar(value=st["name"])
        f.row("이름", lambda p: entry(p, v_name, 16))
        cf = tk.Frame(body, bg=BG2); cf.pack(fill="x", padx=4)
        vb = {k: tk.BooleanVar(value=bool(st.get(k))) for k in ("dz", "rx", "ry", "col")}
        check(cf, "Dz 구속", vb["dz"]).pack(side="left")
        check(cf, "Rx 구속", vb["rx"]).pack(side="left", padx=8)
        check(cf, "Ry 구속", vb["ry"]).pack(side="left")
        section_title(body, "스프링", C_SEL)
        f2 = Form(body)
        vk = {k: tk.StringVar(value=f"{float(st.get(k, 0) or 0):g}") for k in ("kz", "krx", "kry")}
        f2.row("kz", lambda p: entry(p, vk["kz"], 10), "kN/m")
        f2.row("krx", lambda p: entry(p, vk["krx"], 10), "kN·m/rad")
        f2.row("kry", lambda p: entry(p, vk["kry"], 10), "kN·m/rad")
        section_title(body, "기둥 회전강성 (k = n·4EI/H)", C_SUP)
        check(body, "기둥 강성 사용 (노드 지점에만 적용)", vb["col"]).pack(anchor="w", padx=4)
        f3 = Form(body)
        vc = {k: tk.StringVar(value=f"{float(st.get(k, d) or d):g}") for k, d in
              (("col_b", 500), ("col_h", 500), ("col_H", 3.5), ("col_n", 2))}
        v_cm = tk.StringVar(value=self._pick("materials", int(st.get("col_mat", 1))))
        f3.row("기둥 b (X)", lambda p: entry(p, vc["col_b"], 8), "mm")
        f3.row("기둥 h (Y)", lambda p: entry(p, vc["col_h"], 8), "mm")
        f3.row("층고 H", lambda p: entry(p, vc["col_H"], 8), "m")
        f3.row("기둥 수 n", lambda p: entry(p, vc["col_n"], 8), "(하부만 1, 상하부 2)")
        f3.row("재료", lambda p: combo(p, v_cm, self._names("materials")))

        def apply():
            self.push_undo()
            st.update(name=v_name.get().strip() or st["name"],
                      **{k: int(x.get()) for k, x in vb.items()},
                      **{k: max(0.0, parse_float(x.get(), 0.0)) for k, x in vk.items()},
                      col_b=parse_float(vc["col_b"].get(), 500), col_h=parse_float(vc["col_h"].get(), 500),
                      col_H=max(0.1, parse_float(vc["col_H"].get(), 3.5)),
                      col_n=max(1, int(parse_float(vc["col_n"].get(), 1))),
                      col_mat=self._id_of(v_cm.get()) or 1)
            self.edit_target = ("ST", sid)
            self.changed(f"지점 타입 '{st['name']}' 수정")
        self._btn_row(body, [("적용", apply, ACC),
                             ("선택 노드에", lambda: self.assign_support(sorted(self.sel["node"]), sid), BG3),
                             ("선택 선에", lambda: self.assign_line_support(sorted(self.sel["line"]), sid), BG3)])

    def _ed_case(self, body, cid):
        cs = self.model["cases"][cid]
        self._head(f"하중케이스  {cs['name']}", C_LOAD)
        section_title(body, "하중케이스", C_LOAD)
        f = Form(body)
        v_name = tk.StringVar(value=cs["name"]); v_sw = tk.StringVar(value=f"{float(cs.get('selfweight', 0)):g}")
        f.row("이름", lambda p: entry(p, v_name, 14))
        f.row("자중 계수", lambda p: entry(p, v_sw, 8), "(0=없음, 1=포함)")
        tk.Label(body, text="자중 = 슬래브 γ·t + 보 γ·A (보와 슬래브 겹침 미공제)", font=FONT_S,
                 bg=BG2, fg=TX3).pack(anchor="w", padx=4)

        def apply():
            self.push_undo()
            cs["name"] = v_name.get().strip() or cs["name"]
            cs["selfweight"] = parse_float(v_sw.get(), 0.0)
            self.edit_target = ("CASE", cid)
            self.changed("하중케이스 수정")
        self._btn_row(body, [("적용", apply, ACC), ("활성 케이스로", lambda: self.set_active_case(cid), BG3)])

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
            co["factors"] = {c: parse_float(v.get(), 0.0) for c, v in vs.items() if parse_float(v.get(), 0.0)}
            self.edit_target = ("CO", coid)
            self.changed("하중조합 수정")
        self._btn_row(body, [("적용", apply, ACC)])

    def find_load(self, target):
        k, i = target
        key = {"NL": "nloads", "LL": "lloads", "AL": "aloads"}[k]
        return next((ld for ld in self.model[key] if ld["id"] == i), None)

    def _ed_load(self, body, target):
        ld = self.find_load(target)
        if ld is None:
            self.edit_target = None; self._ed_model(body); return
        k = target[0]
        key = {"NL": "nloads", "LL": "lloads", "AL": "aloads"}[k]
        self._head(f"하중  #{ld['id']}", C_LOAD)
        section_title(body, load_text(k, ld), C_LOAD)
        f = Form(body)
        v_case = tk.StringVar(value=self._pick("cases", ld["case"]))
        f.row("하중케이스", lambda p: combo(p, v_case, self._names("cases")))
        fields = {"NL": (("p", "P", "kN ↓"),), "LL": (("w1", "w1 (i단)", "kN/m ↓"), ("w2", "w2 (j단)", "kN/m ↓")),
                  "AL": (("q", "q", "kN/m² ↓"),)}[k]
        vs = {}
        for fk, lbl, u in fields:
            vs[fk] = tk.StringVar(value=f"{float(ld.get(fk, 0)):g}")
            f.row(lbl, lambda p, v=vs[fk]: entry(p, v, 10), u)

        def apply():
            self.push_undo()
            ld["case"] = self._id_of(v_case.get()) or ld["case"]
            for fk, v in vs.items():
                ld[fk] = parse_float(v.get(), 0.0)
            self.edit_target = target
            self.changed("하중 수정")

        def delete():
            self.push_undo()
            self.model[key] = [x for x in self.model[key] if x is not ld]
            self.edit_target = None
            self.changed("하중 삭제")
        self._btn_row(body, [("적용", apply, ACC), ("삭제", delete, RED)])

    def _load_list(self, body, items):
        section_title(body, f"하중 ({len(items)})", C_LOAD)
        if not items:
            tk.Label(body, text="없음 — [하중] 탭에서 입력", font=FONT_S, bg=BG2, fg=TX3).pack(anchor="w", padx=4)
            return
        for k, ld in items:
            row = tk.Frame(body, bg=BG2); row.pack(fill="x", padx=2, pady=1)
            cs = self.model["cases"].get(ld["case"], {}).get("name", "?")
            tk.Label(row, text=f"[{cs}] {load_text(k, ld)}", font=FONT_S, bg=BG2, fg=TXT, anchor="w").pack(
                side="left", fill="x", expand=True)
            key = {"NL": "nloads", "LL": "lloads", "AL": "aloads"}[k]

            def rm(l=ld, key=key):
                self.push_undo()
                self.model[key] = [x for x in self.model[key] if x is not l]
                self.changed("하중 삭제")
            btn(row, "✕", rm, fg=RED, padx=4, pady=0).pack(side="right")
            btn(row, "✎", lambda t=(k, ld["id"]): (setattr(self, "edit_target", t), self.show_editor()),
                padx=4, pady=0).pack(side="right")
