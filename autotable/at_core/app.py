"""
app.py — Auto Table v2 메인 창
  왼쪽: 부재 종류 (보·기둥·벽·슬래브)   가운데: 입력표   오른쪽: 단면 미리보기
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from . import dialogs as D
from . import model as M
from . import theme as T
from .grid import SheetGrid
from .preview import Preview

APP_TITLE = "Auto Table — 배근 일람표"


class AutoTableApp(tk.Toplevel):
    def __init__(self, parent=None, username=""):
        if parent is None:
            self._root = tk.Tk()
            self._root.withdraw()
            parent = self._root
        super().__init__(parent)
        self.username = username
        self.project = M.Project()
        self.mtype = "beam"
        self.dirty = False
        self.title(APP_TITLE)
        self.geometry("1500x820")
        self.minsize(1080, 600)
        self.configure(bg=T.SURFACE)
        T.set_icon(self)
        self._style()
        self._build()
        self._new_rows()
        self.switch("beam")
        self.protocol("WM_DELETE_WINDOW", self.close)
        for seq, fn in (("<Control-s>", self.save), ("<Control-S>", self.save), ("<Control-o>", self.open),
                        ("<Control-O>", self.open), ("<Control-n>", self.new), ("<Control-N>", self.new),
                        ("<F1>", lambda: D.HelpDialog(self).run())):
            self.bind(seq, lambda e, f=fn: (f(), "break")[1])
        self.after(50, self._center)

    # ═════════════════════════════════════════════════════════════
    #  화면 구성
    # ═════════════════════════════════════════════════════════════
    def _style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Treeview", font=T.F_UI, rowheight=22)
        st.configure("Treeview.Heading", font=T.F_HDR)
        st.configure("TCombobox", padding=2)

    def _build(self):
        bar = tk.Frame(self, bg=T.NAVY, height=46)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="Auto Table", font=T.F_TITLE, bg=T.NAVY, fg="white").pack(side="left", padx=(16, 6))
        tk.Label(bar, text=f" v{__version__} ", font=(T.FAM, 8, "bold"), bg=T.ORANGE, fg="white").pack(side="left")
        tk.Label(bar, text="보 · 기둥 · 벽 · 슬래브 배근 일람표 — 입력 · 가져오기 · CAD/엑셀 출력",
                 font=T.F_UI, bg=T.NAVY, fg="#B9C4DA").pack(side="left", padx=14)
        if self.username:
            tk.Label(bar, text=self.username, font=T.F_UI, bg=T.NAVY, fg="#B9C4DA").pack(side="right", padx=14)

        tb = tk.Frame(self, bg=T.PANEL, height=44)
        tb.pack(fill="x")
        tk.Frame(self, bg=T.LINE, height=1).pack(fill="x")

        def tbtn(text, cmd, primary=False, menu=None):
            b = tk.Button(tb, text=text, command=cmd, font=T.F_UI_B, relief="flat", cursor="hand2", padx=10, pady=4,
                          bg=T.ORANGE if primary else T.SURFACE, fg="white" if primary else T.INK,
                          activebackground=T.ORANGE_L, bd=0)
            b.pack(side="left", padx=3, pady=6)
            return b

        def sep():
            tk.Frame(tb, bg=T.LINE, width=1, height=24).pack(side="left", padx=6, pady=8)

        tbtn("새로", self.new)
        tbtn("열기", self.open)
        tbtn("저장", self.save)
        sep()
        self.b_imp = tbtn("가져오기 ▾", lambda: self._menu(self.b_imp, [
            ("CAD 일람표 (DXF)…", self.import_dxf), ("MIDAS Gen (MGT · txt)…", lambda: self.import_table("midas")),
            ("엑셀 (xlsx)…", lambda: self.import_table("excel")), ("TXT / CSV…", lambda: self.import_table("txt")),
            None, ("PDF…", self.import_pdf), ("사진 (jpg·png)…", self.import_photo)]), primary=True)
        self.b_exp = tbtn("내보내기 ▾", lambda: self._menu(self.b_exp, [
            ("CAD 일람표 (DXF)…", self.export_dxf), ("엑셀 (xlsx)…", self.export_excel), ("TXT (탭 구분)…", self.export_txt)]),
            primary=True)
        sep()
        tk.Label(tb, text="강종", font=T.F_UI_B, bg=T.PANEL, fg=T.MUTED).pack(side="left", padx=(4, 2))
        self.pfx = tk.StringVar(value="D")
        cb = ttk.Combobox(tb, textvariable=self.pfx, values=M.PREFIXES, width=5, state="readonly")
        cb.pack(side="left", padx=2)
        cb.bind("<<ComboboxSelected>>", lambda e: (self.project.settings.__setitem__("prefix", self.pfx.get()),
                                                    self.grid_.focus_grid()))
        sep()
        tbtn("＋ 행", lambda: (self.grid_.insert_row_below(), self.grid_.focus_grid()))
        tbtn("행 복제", lambda: (self.grid_.duplicate_row(), self.grid_.focus_grid()))
        tbtn("행 삭제", lambda: (self.grid_.delete_rows(), self.grid_.focus_grid()))
        tbtn("부호 정렬", lambda: (self.grid_.sort_by_name(), self.grid_.focus_grid()))
        sep()
        self.b_design = tbtn("보 단면 설계", self.open_design)
        tbtn("도움말 (F1)", lambda: D.HelpDialog(self).run())

        body = tk.Frame(self, bg=T.SURFACE)
        body.pack(fill="both", expand=True)

        side = tk.Frame(body, bg=T.NAVY_2, width=150)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="부재 종류", font=T.F_UI_B, bg=T.NAVY_2, fg="#B9C4DA").pack(anchor="w", padx=14, pady=(14, 6))
        self.side_btns = {}
        for t, d in M.TYPES.items():
            b = tk.Button(side, text="", anchor="w", font=(T.FAM, 11, "bold"), relief="flat", cursor="hand2",
                          bg=T.NAVY_2, fg="white", activebackground=T.NAVY_3, activeforeground="white", bd=0,
                          padx=16, pady=10, command=lambda t=t: self.switch(t))
            b.pack(fill="x")
            self.side_btns[t] = b
        self.src_lbl = tk.Label(side, text="", font=T.F_SMALL, bg=T.NAVY_2, fg="#8FA3C0", justify="left", wraplength=130)
        self.src_lbl.pack(side="bottom", anchor="w", padx=12, pady=12)

        right = tk.Frame(body, bg=T.PANEL, width=330)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        tk.Frame(body, bg=T.LINE, width=1).pack(side="right", fill="y")
        self.preview = Preview(right)
        self.preview.pack(fill="both", expand=True)

        mid = tk.Frame(body, bg=T.PANEL)
        mid.pack(side="left", fill="both", expand=True)
        self.grid_ = SheetGrid(mid, on_change=self._changed, on_select=self._selected, on_status=self.status,
                               get_prefix=lambda: self.pfx.get(), extra_menu=self._grid_menu)
        self.grid_.pack(fill="both", expand=True)

        sb = tk.Frame(self, bg=T.HDR, height=26)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self.st_msg = tk.Label(sb, text="", font=T.F_SMALL, bg=T.HDR, fg=T.INK, anchor="w")
        self.st_msg.pack(side="left", fill="x", expand=True, padx=10)
        self.st_file = tk.Label(sb, text="", font=T.F_SMALL, bg=T.HDR, fg=T.MUTED)
        self.st_file.pack(side="right", padx=10)
        tk.Label(sb, text="방향키 이동 · Enter/Tab 확정 · Alt+Enter 행 복제 · Shift+Enter 아래로 복사 · F4 강종 · F1 도움말",
                 font=T.F_SMALL, bg=T.HDR, fg=T.MUTED).pack(side="right", padx=10)

    def _menu(self, btn, items):
        m = tk.Menu(self, tearoff=0, font=T.F_UI)
        for it in items:
            if it is None:
                m.add_separator()
            else:
                m.add_command(label=it[0], command=it[1])
        m.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())

    def _grid_menu(self, m):
        if self.mtype == "beam":
            m.add_separator()
            m.add_command(label="보 단면 설계 (선택 행)…", command=self.open_design)

    def _center(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        self.grid_.focus_grid()

    # ═════════════════════════════════════════════════════════════
    #  상태
    # ═════════════════════════════════════════════════════════════
    def status(self, s):
        self.st_msg.config(text=s or "")

    def _new_rows(self):
        for t in M.TYPES:
            if not self.project.rows[t]:
                self.project.rows[t] = [M.new_row(t)]
                self.project.rows[t][0]["name"] = {"beam": "B1", "column": "C1", "wall": "W1", "slab": "S1"}[t]

    def _refresh_side(self):
        for t, b in self.side_btns.items():
            n = self.project.count(t)
            on = t == self.mtype
            b.config(text=f"{M.TYPES[t]['icon']}  {M.TYPES[t]['title']}   {n}", bg=T.ORANGE if on else T.NAVY_2,
                     activebackground=T.ORANGE_D if on else T.NAVY_3)
        src = self.project.meta.get("source")
        self.src_lbl.config(text=("원본\n" + os.path.basename(src)) if src else "")
        name = os.path.basename(self.project.path) if self.project.path else "새 파일"
        self.st_file.config(text=("● " if self.dirty else "") + name)
        self.title(f"{APP_TITLE}  —  {name}{' *' if self.dirty else ''}")
        self.b_design.config(state="normal" if self.mtype == "beam" else "disabled")

    def switch(self, t):
        self.grid_.commit()
        self.mtype = t
        self.grid_.set_data(t, self.project.rows[t])
        self._refresh_side()
        self.status("")
        self.grid_.focus_grid()

    def _changed(self):
        self.dirty = True
        self._refresh_side()

    def _selected(self, r):
        rows = self.project.rows[self.mtype]
        self.preview.show(self.mtype, rows[r] if 0 <= r < len(rows) else None)

    def _reload(self):
        self.pfx.set(self.project.settings.get("prefix", "D"))
        self.grid_.set_data(self.mtype, self.project.rows[self.mtype])
        self._refresh_side()

    # ═════════════════════════════════════════════════════════════
    #  파일
    # ═════════════════════════════════════════════════════════════
    def _ask_save(self):
        if not self.dirty:
            return True
        a = messagebox.askyesnocancel(APP_TITLE, "바뀐 내용을 저장할까요?", parent=self)
        if a is None:
            return False
        if a:
            return self.save()
        return True

    def new(self):
        if not self._ask_save():
            return
        self.project = M.Project()
        self._new_rows()
        self.dirty = False
        self.mtype = "beam"
        self._reload()

    def open(self):
        if not self._ask_save():
            return
        p = filedialog.askopenfilename(parent=self, title="일람표 열기",
                                       filetypes=[("Auto Table", "*.atbl"), ("모든 파일", "*.*")])
        if not p:
            return
        try:
            self.project = M.Project.load(p)
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"열 수 없습니다.\n{e}", parent=self)
            return
        self._new_rows()
        self.dirty = False
        first = next((t for t in M.TYPES if self.project.count(t)), "beam")
        self.mtype = first
        self._reload()
        self.status(f"열었습니다: {p}")

    def save(self, as_new=False):
        self.grid_.commit()
        p = self.project.path
        if as_new or not p:
            src = self.project.meta.get("source")
            init = os.path.splitext(os.path.basename(src))[0] + ".atbl" if src else "일람표.atbl"
            p = filedialog.asksaveasfilename(parent=self, title="일람표 저장", defaultextension=".atbl",
                                             initialfile=init, filetypes=[("Auto Table", "*.atbl")])
            if not p:
                return False
        try:
            self.project.save(p)
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"저장하지 못했습니다.\n{e}", parent=self)
            return False
        self.dirty = False
        self._refresh_side()
        self.status(f"저장했습니다: {p}")
        return True

    def close(self):
        if not self._ask_save():
            return
        self.destroy()
        if getattr(self, "_root", None):
            self._root.destroy()

    # ═════════════════════════════════════════════════════════════
    #  가져오기
    # ═════════════════════════════════════════════════════════════
    def _merge(self, res, warn, source, meta=None):
        res = {t: rows for t, rows in res.items() if rows}
        if not res:
            messagebox.showwarning(APP_TITLE, "읽은 부재가 없습니다.\n" + "\n".join(warn[:8]), parent=self)
            return False
        for rows in res.values():
            for r in rows:
                for k in [k for k in r if k.startswith("_")]:
                    r.pop(k)
        existing = {t: M.clean_rows(t, self.project.rows[t]) for t in M.TYPES}
        dlg = D.ImportResult(self, res, warn, source, existing).run()
        if not dlg:
            return False
        self.grid_.commit()
        for t in dlg["types"]:
            keys = M.col_keys(t)
            rows = [{k: str(r.get(k, "") or "") for k in keys} for r in res[t]]
            if dlg["mode"] == "replace":
                self.project.rows[t] = rows
            else:
                self.project.rows[t] = existing[t] + rows
        if meta:
            for k in ("notes", "drawing_no"):
                if meta.get(k):
                    self.project.meta[k] = meta[k]
            if meta.get("form"):
                self.project.meta["template"] = source
            self.project.meta["source"] = source
        guess = M.guess_prefix({t: res[t] for t in dlg["types"]})
        if guess:
            self.project.settings["prefix"] = guess
        self.dirty = True
        self.mtype = dlg["types"][0] if dlg["types"] else self.mtype
        self._reload()
        self.status(f"가져왔습니다: {', '.join(M.TYPES[t]['title'] + ' ' + str(len(res[t])) + '개' for t in dlg['types'])}")
        return True

    def import_dxf(self):
        p = filedialog.askopenfilename(parent=self, title="CAD 일람표 (DXF)", filetypes=[("DXF", "*.dxf"), ("모든 파일", "*.*")])
        if not p:
            return
        o = D.ImportOptions(self, "CAD").run()
        if not o:
            return
        from .dxf_read import import_dxf
        try:
            res, warn, meta = D.run_task(self, "CAD 도면 읽는 중…", lambda log: import_dxf(p, o["want"], log))
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"DXF 를 읽지 못했습니다.\n{e}\n\nDWG 는 CAD 에서 DXF 로 저장한 뒤 가져오세요.", parent=self)
            return
        self._merge(res, warn, p, meta)

    def import_table(self, kind):
        ft = {"excel": [("엑셀", "*.xlsx *.xlsm"), ("모든 파일", "*.*")],
              "midas": [("MIDAS (MGT·텍스트)", "*.mgt *.txt *.out *.csv"), ("모든 파일", "*.*")],
              "txt": [("TXT/CSV", "*.txt *.csv *.tsv"), ("모든 파일", "*.*")]}[kind]
        p = filedialog.askopenfilename(parent=self, title="표 가져오기", filetypes=ft)
        if not p:
            return
        from . import table_io as TI
        if not p.lower().endswith((".xlsx", ".xlsm", ".xltx")):
            try:
                txt = TI.read_text(p)
            except Exception:                         # noqa: BLE001
                txt = ""
            if TI.is_mgt(txt):                        # MIDAS MGT (*REBAR-BEAM)
                rows, warn = TI.parse_mgt(txt)
                self._merge({"beam": rows}, warn, p)
                return
        try:
            grids = TI.read_grids(p)
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"파일을 읽지 못했습니다.\n{e}", parent=self)
            return
        own = TI.own_format(grids)
        if own:
            self._merge(own, [], p)
            return
        grids = {k: v for k, v in grids.items() if v}
        if not grids:
            messagebox.showwarning(APP_TITLE, "내용이 없습니다.", parent=self)
            return
        r = D.MappingDialog(self, grids, self.mtype, self.pfx.get(),
                            title="MIDAS Gen 결과 가져오기" if kind == "midas" else "표 가져오기").run()
        if not r:
            return
        t, rows = r
        self._merge({t: rows}, [], p)

    def import_pdf(self):
        p = filedialog.askopenfilename(parent=self, title="PDF 일람표", filetypes=[("PDF", "*.pdf")])
        if not p:
            return
        from . import image_io as IO
        try:
            n = IO.pdf_pages(p)
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"PDF 를 열 수 없습니다.\n{e}", parent=self)
            return
        o = D.ImportOptions(self, "PDF", n).run()
        if not o:
            return
        try:
            res, warn = D.run_task(self, "PDF 읽는 중…", lambda log: IO.import_pdf(p, o["page"], o["want"], log))
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"PDF 를 읽지 못했습니다.\n{e}", parent=self)
            return
        self._merge(res, warn, p)

    def import_photo(self):
        p = filedialog.askopenfilename(parent=self, title="일람표 사진",
                                       filetypes=[("그림", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"), ("모든 파일", "*.*")])
        if not p:
            return
        from . import image_io as IO
        ok, msg = IO.available()
        if not ok:
            messagebox.showerror(APP_TITLE, msg, parent=self)
            return
        o = D.ImportOptions(self, "사진").run()
        if not o:
            return
        try:
            res, warn = D.run_task(self, "사진 글자 읽는 중…", lambda log: IO.import_photo(p, o["want"], o["flatten"], log))
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"사진을 읽지 못했습니다.\n{e}", parent=self)
            return
        self._merge(res, warn, p)

    # ═════════════════════════════════════════════════════════════
    #  내보내기
    # ═════════════════════════════════════════════════════════════
    def _base_name(self):
        src = self.project.path or self.project.meta.get("source") or ""
        return os.path.splitext(os.path.basename(src))[0] if src else "일람표"

    def export_dxf(self):
        self.grid_.commit()
        from . import dxf_write as DW
        o = D.ExportDxfDialog(self, self.project, self.mtype, DW.default_template()).run()
        if not o:
            return
        base = self._base_name()
        types = o["types"]
        init = f"{base}_{M.TYPES[types[0]]['title']}.dxf" if len(types) == 1 else f"{base}.dxf"
        p = filedialog.asksaveasfilename(parent=self, title="DXF 저장", defaultextension=".dxf", initialfile=init,
                                         filetypes=[("DXF", "*.dxf")])
        if not p:
            return
        self.project.meta.update({"notes": o["notes"], "drawing_no": o["drawing_no"], "project": o["project"]})
        root, ext = os.path.splitext(p)

        def work(log):
            out = []
            for i, t in enumerate(types):
                path = p if len(types) == 1 else f"{root}_{M.TYPES[t]['title']}{ext}"
                n = DW.export_dxf(path, t, self.project.rows[t], o["template"],
                                  {"drawing_no": o["drawing_no"], "notes": o["notes"], "project": o["project"],
                                   "layer_text": o.get("layer_text", "total"), "deep": o.get("deep", "grow")}, log)
                out.append((path, n))
            return out
        try:
            out = D.run_task(self, "DXF 만드는 중…", work)
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"DXF 를 만들지 못했습니다.\n{e}", parent=self)
            return
        self.dirty = True
        self._refresh_side()
        messagebox.showinfo(APP_TITLE, "저장했습니다.\n\n" + "\n".join(f"{os.path.basename(a)}  (시트 {n}장)" for a, n in out),
                            parent=self)

    def export_excel(self):
        self.grid_.commit()
        p = filedialog.asksaveasfilename(parent=self, title="엑셀 저장", defaultextension=".xlsx",
                                         initialfile=f"{self._base_name()}.xlsx", filetypes=[("엑셀", "*.xlsx")])
        if not p:
            return
        from . import table_io as TI
        try:
            TI.export_excel(p, self.project)
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"저장하지 못했습니다.\n{e}", parent=self)
            return
        self.status(f"엑셀 저장: {p}")
        messagebox.showinfo(APP_TITLE, f"저장했습니다.\n{p}\n\n이 엑셀은 고친 뒤 다시 가져올 수 있습니다.", parent=self)

    def export_txt(self):
        self.grid_.commit()
        p = filedialog.asksaveasfilename(parent=self, title="TXT 저장", defaultextension=".txt",
                                         initialfile=f"{self._base_name()}.txt", filetypes=[("TXT", "*.txt")])
        if not p:
            return
        from . import table_io as TI
        try:
            TI.export_txt(p, self.project)
        except Exception as e:                        # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"저장하지 못했습니다.\n{e}", parent=self)
            return
        self.status(f"TXT 저장: {p}")

    # ═════════════════════════════════════════════════════════════
    #  보 단면 설계
    # ═════════════════════════════════════════════════════════════
    def open_design(self):
        if self.mtype != "beam":
            return
        self.grid_.commit()
        r = self.grid_.cur[0]
        rows = self.project.rows["beam"]
        if r >= len(rows):
            messagebox.showinfo(APP_TITLE, "설계할 보 행을 선택하세요.", parent=self)
            return
        from .design import DesignWindow

        def applied():
            self._changed()
            self.grid_.redraw()
            self.grid_._sync_editor()
            self._selected(r)
        DesignWindow(self, rows[r], rows[r].get("name", ""), on_apply=applied)


def open_auto_table(parent=None, username=""):
    win = AutoTableApp(parent=parent, username=username)
    if parent:
        win.lift()
        win.focus_force()
    return win
