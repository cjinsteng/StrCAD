"""
grid.py — 엑셀처럼 쓰는 입력표 (tkinter Canvas)

키 조작
  ←↑→↓          칸 이동 (입력 중에도 바로 다음 칸으로)      Shift+방향키  범위 선택
  Ctrl+방향키    자료 끝까지 이동                            Home/End      행 처음/끝
  Enter / Tab   입력 확정 후 아래 / 오른쪽                  Shift+Tab     왼쪽
  Shift+Enter   이 값을 아래 칸에 복사하고 내려감            Alt+Enter     행 복제(부호 +1)
  F2 / 더블클릭  칸 안에서 고치기 (←→ 로 글자 이동)          Esc           입력 취소
  Delete        선택 범위 지우기                             Ctrl+C/X/V    복사/잘라내기/붙여넣기 (엑셀과 호환)
  Ctrl+Z / Y    되돌리기 / 다시                              Ctrl+D / R    아래로 / 오른쪽으로 채우기
  F4            강종 기호 바꾸기 (D→HD→SHD→UHD→SD)          Ctrl+ + / -   행 삽입 / 삭제
  Alt+↑ / ↓     행 위/아래로 옮기기                          마지막 빈 줄에 쓰면 새 행이 생김
"""
from __future__ import annotations

import copy
import sys
import tkinter as tk

from . import model as M
from . import theme as T

_ALT = 0x20000 if sys.platform.startswith("win") else 0x0008
_NAV_KEYS = {"Up", "Down", "Left", "Right", "Tab", "ISO_Left_Tab", "Return", "KP_Enter", "Prior", "Next", "Home", "End"}


class SheetGrid(tk.Frame):
    ROW_H = 26
    HDR1 = 22          # 그룹 머리글
    HDR2 = 26          # 열 머리글
    RH_W = 46          # 행 번호 폭
    MIN_W = 36

    def __init__(self, master, on_change=None, on_select=None, on_status=None, get_prefix=None, extra_menu=None):
        super().__init__(master, bg=T.PANEL)
        self.on_change = on_change or (lambda: None)
        self.on_select = on_select or (lambda r: None)
        self.on_status = on_status or (lambda s: None)
        self.get_prefix = get_prefix or (lambda: "D")
        self.extra_menu = extra_menu
        self.mtype = None
        self.cols: list[M.Col] = []
        self.rows: list[dict] = []
        self.widths: dict = {}
        self.frozen = 1
        self.cur = (0, 0)
        self.anchor = (0, 0)
        self.top = 0
        self.xoff = 0
        self.mode = "nav"            # nav | enter | edit
        self.undo_stack: list = []
        self.redo_stack: list = []
        self._setting = False
        self._drag = None
        self._resize = None
        self._pop = None

        self.cv = tk.Canvas(self, bg=T.PANEL, highlightthickness=0, bd=0, takefocus=1)
        self.vsb = tk.Scrollbar(self, orient="vertical", command=self._vscroll)
        self.hsb = tk.Scrollbar(self, orient="horizontal", command=self._hscroll)
        self.vsb.pack(side="right", fill="y")
        self.hsb.pack(side="bottom", fill="x")
        self.cv.pack(side="left", fill="both", expand=True)

        self.var = tk.StringVar()
        self.ed = tk.Entry(self.cv, textvariable=self.var, font=T.F_CELL, relief="flat", bd=0,
                           highlightthickness=0, exportselection=False, justify="center")
        self.ed_win = self.cv.create_window(0, 0, window=self.ed, anchor="nw", state="hidden")
        self.var.trace_add("write", self._on_var)

        for w in (self.cv, self.ed):
            w.bind("<KeyPress>", self._key)
        self.ed.bind("<FocusOut>", lambda e: self._draw_cursor())
        self.ed.bind("<Double-Button-1>", lambda e: (self._begin_edit(select_all=False), "break")[1])
        self.cv.bind("<Configure>", lambda e: self.redraw())
        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<B1-Motion>", self._motion_drag)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<Double-Button-1>", self._dbl)
        self.cv.bind("<Button-3>", self._ctx)
        self.cv.bind("<Motion>", self._hover)
        for w in (self.cv, self.ed):
            w.bind("<MouseWheel>", self._wheel)
            w.bind("<Shift-MouseWheel>", lambda e: self._hwheel(-1 if e.delta > 0 else 1))
            w.bind("<Button-4>", lambda e: self._scroll_rows(-3))
            w.bind("<Button-5>", lambda e: self._scroll_rows(3))

    # ═════════════════════════════════════════════════════════════
    #  자료 연결
    # ═════════════════════════════════════════════════════════════
    def set_data(self, mtype, rows):
        """rows: 프로젝트의 행 리스트 (그대로 수정함)."""
        self._close_pop()
        self.mtype = mtype
        self.cols = M.cols(mtype)
        self.rows = rows
        for c in self.cols:
            self.widths.setdefault((mtype, c.key), c.width)
        self.cur = self.anchor = (0, 0)
        self.top = 0
        self.xoff = 0
        self.mode = "nav"
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.redraw()
        self._sync_editor()
        self.on_select(0)

    def focus_grid(self):
        self._sync_editor()
        self.ed.focus_set()

    def W(self, c):
        return self.widths.get((self.mtype, self.cols[c].key), self.cols[c].width)

    @property
    def nrows(self):
        return len(self.rows) + 1                     # 마지막 = 새 행 자리

    def has_groups(self):
        return any(c.group for c in self.cols)

    def hdr_h(self):
        return (self.HDR1 if self.has_groups() else 0) + self.HDR2

    # ── 좌표 ─────────────────────────────────────────────────────
    def frozen_w(self):
        return sum(self.W(c) for c in range(min(self.frozen, len(self.cols))))

    def col_x(self, c):
        """화면상 왼쪽 x."""
        if c < self.frozen:
            return self.RH_W + sum(self.W(i) for i in range(c))
        return self.RH_W + self.frozen_w() + sum(self.W(i) for i in range(self.frozen, c)) - self.xoff

    def row_y(self, r):
        return self.hdr_h() + (r - self.top) * self.ROW_H

    def vis_rows(self):
        h = max(1, self.cv.winfo_height() - self.hdr_h())
        return max(1, h // self.ROW_H)

    def scroll_w(self):
        return sum(self.W(i) for i in range(self.frozen, len(self.cols)))

    def view_w(self):
        return max(10, self.cv.winfo_width() - self.RH_W - self.frozen_w())

    def cell_at(self, x, y):
        """(row, col) / 머리글이면 row=-1 / 행번호 칸이면 col=-1."""
        r = -1 if y < self.hdr_h() else self.top + int((y - self.hdr_h()) // self.ROW_H)
        if x < self.RH_W:
            return r, -1
        c = len(self.cols) - 1
        for i in range(len(self.cols)):
            x0 = self.col_x(i)
            if i >= self.frozen and x < self.RH_W + self.frozen_w():
                continue
            if x0 <= x < x0 + self.W(i):
                c = i
                break
        return r, c

    # ═════════════════════════════════════════════════════════════
    #  그리기
    # ═════════════════════════════════════════════════════════════
    def redraw(self):
        cv = self.cv
        cv.delete("g")
        if not self.cols:
            return
        W, H = cv.winfo_width(), cv.winfo_height()
        hh = self.hdr_h()
        nvis = self.vis_rows() + 1
        r0, r1 = self.top, min(self.nrows, self.top + nvis)
        (ra, ca), (rb, cb) = self.sel_range()
        fz = self.RH_W + self.frozen_w()
        issues = {}

        def cells(col_ids):
            for c in col_ids:
                col = self.cols[c]
                x0 = self.col_x(c)
                w = self.W(c)
                if x0 + w < (self.RH_W if c < self.frozen else fz) or x0 > W:
                    continue
                for r in range(r0, r1):
                    y0 = self.row_y(r)
                    phantom = r >= len(self.rows)
                    row = self.rows[r] if not phantom else {}
                    if row.get("drawn") and r not in issues:
                        issues[r] = {k for k, _ in M.drawn_issues(row, self.mtype)}
                    dis = (not phantom) and M.disabled(self.mtype, row, col.key)
                    insel = ra <= r <= rb and ca <= c <= cb and (ra, ca) != (rb, cb)
                    if dis:
                        bg = T.DIS
                    elif insel:
                        bg = T.SEL
                    elif phantom:
                        bg = "#F7F9FC"
                    else:
                        bg = T.ALT if r % 2 else T.PANEL
                    cv.create_rectangle(x0, y0, x0 + w, y0 + self.ROW_H, fill=bg, outline=T.LINE, tags="g")
                    v = row.get(col.key, "")
                    if col.kind == "drawn":
                        lab = M.drawn_label(row, self.mtype) if v else ""
                        if lab:
                            cv.create_text(x0 + 6, y0 + self.ROW_H / 2, text=lab, anchor="w", font=T.F_SMALL,
                                           fill=T.NG if lab.startswith("≠") else T.OK, tags="g")
                        continue
                    if col.key in issues.get(r, ()):      # 그림과 다른 칸: 빨간 모서리
                        cv.create_polygon(x0 + w - 9, y0 + 1, x0 + w - 1, y0 + 1, x0 + w - 1, y0 + 9, fill=T.NG,
                                          outline="", tags="g")
                    if col.kind == "choice" and not dis and not phantom:
                        cv.create_text(x0 + w - 8, y0 + self.ROW_H / 2, text="▾", fill=T.FAINT, font=T.F_SMALL, tags="g")
                    if v and c >= self.frozen and x0 + w / 2 < fz + 12:     # 고정 열 뒤로 숨은 칸 글자
                        continue
                    if v:
                        ok = M.is_valid(col.kind, v, col.choices)
                        fg = T.DIS_TX if dis else (T.NG if not ok else (T.INK if col.kind in ("text", "num", "choice") else T.BLUE))
                        font = T.F_CELL_B if col.key == "name" else T.F_CELL
                        if col.key in ("name", "note", "floor"):
                            cv.create_text(x0 + 6, y0 + self.ROW_H / 2, text=v, anchor="w", fill=fg, font=font, tags="g")
                        else:
                            cv.create_text(x0 + w / 2, y0 + self.ROW_H / 2, text=v, fill=fg, font=font, tags="g")
                    elif phantom and c == 0 and r == len(self.rows):
                        cv.create_text(x0 + 6, y0 + self.ROW_H / 2, text="＋ 새 부재", anchor="w",
                                       fill=T.FAINT, font=T.F_SMALL, tags="g")

        cells(range(self.frozen, len(self.cols)))
        cells(range(0, min(self.frozen, len(self.cols))))

        # 머리글
        cv.create_rectangle(0, 0, W, hh, fill=T.HDR, outline="", tags="g")
        g1 = self.HDR1 if self.has_groups() else 0

        def headers(col_ids, clip_left):
            i = 0
            ids = list(col_ids)
            while i < len(ids):
                c = ids[i]
                col = self.cols[c]
                x0 = self.col_x(c)
                w = self.W(c)
                if x0 + w >= clip_left and x0 <= W:
                    act = ca <= c <= cb
                    fill = T.ORANGE_L if act else T.HDR
                    if not col.group and g1:            # 그룹 없는 열: 두 줄 합쳐서
                        cv.create_rectangle(x0, 0, x0 + w, hh, fill=fill, outline=T.LINE2, tags="g")
                        cv.create_text(x0 + w / 2, hh / 2, text=col.title, fill=T.INK, font=T.F_HDR, tags="g")
                    else:
                        cv.create_rectangle(x0, g1, x0 + w, hh, fill=fill, outline=T.LINE2, tags="g")
                        cv.create_text(x0 + w / 2, g1 + self.HDR2 / 2, text=col.title, fill=T.INK, font=T.F_HDR, tags="g")
                if col.group and g1:                   # 같은 그룹 묶어서
                    j = i
                    while j + 1 < len(ids) and self.cols[ids[j + 1]].group == col.group:
                        j += 1
                    gx0 = x0
                    gx1 = self.col_x(ids[j]) + self.W(ids[j])
                    if gx1 >= clip_left and gx0 <= W:
                        cv.create_rectangle(gx0, 0, gx1, g1, fill=T.HDR2, outline=T.LINE2, tags="g")
                        cv.create_text((max(gx0, clip_left) + min(gx1, W)) / 2, g1 / 2, text=col.group,
                                       fill=T.NAVY, font=T.F_HDR, tags="g")
                    for k in range(i + 1, j + 1):
                        cc = ids[k]
                        xx = self.col_x(cc)
                        ww = self.W(cc)
                        act = ca <= cc <= cb
                        cv.create_rectangle(xx, g1, xx + ww, hh, fill=T.ORANGE_L if act else T.HDR, outline=T.LINE2, tags="g")
                        cv.create_text(xx + ww / 2, g1 + self.HDR2 / 2, text=self.cols[cc].title, fill=T.INK,
                                       font=T.F_HDR, tags="g")
                    i = j + 1
                    continue
                i += 1

        headers(range(self.frozen, len(self.cols)), fz)
        cv.create_rectangle(self.RH_W, 0, fz, hh, fill=T.HDR, outline="", tags="g")
        headers(range(0, min(self.frozen, len(self.cols))), self.RH_W)

        # 행 번호
        cv.create_rectangle(0, hh, self.RH_W, H, fill=T.HDR, outline="", tags="g")
        cv.create_rectangle(0, 0, self.RH_W, hh, fill=T.HDR2, outline=T.LINE2, tags="g")
        cv.create_text(self.RH_W / 2, hh / 2, text=M.TYPES[self.mtype]["title"] if self.mtype else "", fill=T.NAVY,
                       font=T.F_HDR, tags="g")
        for r in range(r0, r1):
            y0 = self.row_y(r)
            act = ra <= r <= rb
            phantom = r >= len(self.rows)
            cv.create_rectangle(0, y0, self.RH_W, y0 + self.ROW_H, fill=T.ORANGE_L if act else T.HDR,
                                outline=T.LINE2, tags="g")
            cv.create_text(self.RH_W / 2, y0 + self.ROW_H / 2, text="＋" if phantom else str(r + 1),
                           fill=T.FAINT if phantom else T.MUTED, font=T.F_SMALL, tags="g")
        cv.create_line(fz, 0, fz, H, fill=T.NAVY_3, width=1, tags="g")

        # 선택 범위 테두리
        if (ra, ca) != (rb, cb):
            x0, y0 = self.col_x(ca), self.row_y(ra)
            x1, y1 = self.col_x(cb) + self.W(cb), self.row_y(rb) + self.ROW_H
            cv.create_rectangle(x0, max(y0, hh), x1, max(y1, hh), outline=T.SEL_BD, width=2, tags="g")
        self._draw_cursor()
        cv.tag_raise(self.ed_win)
        self._update_scrollbars()

    def _draw_cursor(self):
        self.cv.delete("cur")
        r, c = self.cur
        if not self.cols or not self._visible(r, c):
            return
        x0, y0 = self.col_x(c), self.row_y(r)
        has_focus = self.focus_get() in (self.ed, self.cv)
        self.cv.create_rectangle(x0, y0, x0 + self.W(c), y0 + self.ROW_H, outline=T.ORANGE if has_focus else T.FAINT,
                                 width=2.5 if has_focus else 1.5, tags=("g", "cur"))
        self.cv.tag_raise("cur")

    def _update_scrollbars(self):
        n = max(1, self.nrows)
        v = self.vis_rows()
        self.vsb.set(self.top / n, min(1.0, (self.top + v) / n))
        sw = max(1, self.scroll_w())
        vw = self.view_w()
        self.hsb.set(self.xoff / sw, min(1.0, (self.xoff + vw) / sw))

    def _visible(self, r, c):
        if not (self.top <= r < self.top + self.vis_rows()):
            return False
        if c < self.frozen:
            return True
        x0 = self.col_x(c)
        return x0 >= self.RH_W + self.frozen_w() - 1 and x0 + self.W(c) <= self.cv.winfo_width() + 1

    # ═════════════════════════════════════════════════════════════
    #  편집 칸 (항상 선택 칸 위에 떠 있음 → 한글 입력기 안전)
    # ═════════════════════════════════════════════════════════════
    def _cell_value(self, r, c):
        if r >= len(self.rows) or c < 0 or c >= len(self.cols):
            return ""
        return self.rows[r].get(self.cols[c].key, "")

    def _sync_editor(self):
        """선택 칸 위로 편집 칸을 옮기고 값 표시 (nav 모드)."""
        if not self.cols:
            return
        r, c = self.cur
        col = self.cols[c]
        if not self._visible(r, c):
            self.cv.itemconfigure(self.ed_win, state="hidden")
            return
        x0, y0 = self.col_x(c), self.row_y(r)
        self.cv.coords(self.ed_win, x0 + 2, y0 + 2)
        self.cv.itemconfigure(self.ed_win, width=self.W(c) - 4, height=self.ROW_H - 4, state="normal")
        dis = r < len(self.rows) and M.disabled(self.mtype, self.rows[r], col.key)
        bg = T.DIS if dis else (T.SEL if self.mode == "nav" and self._is_multi() else
                                ("#FFFFFF" if self.mode != "nav" else (T.ALT if r % 2 else T.PANEL)))
        if r >= len(self.rows) and self.mode == "nav":
            bg = "#F7F9FC"
        val = self._cell_value(r, c)
        if col.kind == "drawn":
            val = M.drawn_label(self.rows[r], self.mtype) if r < len(self.rows) and val else ""
            dis = True
            bg = T.DIS if not self._is_multi() else T.SEL
        ok = M.is_valid(col.kind, val, col.choices)
        fg = T.DIS_TX if dis else (T.NG if not ok else (T.INK if col.kind in ("text", "num", "choice") else T.BLUE))
        if col.kind == "drawn":
            fg = T.NG if val.startswith("≠") else T.OK
        just = "left" if col.key in ("name", "note", "floor", "drawn") else "center"
        font = T.F_CELL_B if col.key == "name" else T.F_CELL
        if self.mode == "nav":
            self.ed.config(bg=bg, fg=fg, insertontime=0, selectbackground=bg, selectforeground=fg,
                           justify=just, font=font, readonlybackground=bg)
            self._set_text(val)
            self.ed.config(state="readonly" if (dis or col.kind in ("choice", "drawn")) else "normal")
            self.ed.select_range(0, "end")
            self.ed.icursor("end")
        else:
            self.ed.config(state="normal", bg="#FFFFFF", fg=T.INK, insertwidth=2, insertontime=600, selectbackground="#BFD3F7",
                           selectforeground=T.INK, justify=just, font=font)
        self.cv.tag_raise(self.ed_win)

    def _set_text(self, v):
        self._setting = True
        st = str(self.ed.cget("state"))
        if st == "readonly":
            self.ed.config(state="normal")
        self.var.set(v)
        if st == "readonly":
            self.ed.config(state="readonly")
        self._setting = False

    def _on_var(self, *a):
        if self._setting:
            return
        if self.mode == "nav":             # 글자를 치기 시작 → 입력 모드
            self.mode = "enter"
            self._sync_editor()
            self.ed.icursor("end")
            self.ed.select_clear()

    def _begin_edit(self, select_all=False):
        r, c = self.cur
        col = self.cols[c]
        if col.kind == "drawn":
            return
        if r < len(self.rows) and M.disabled(self.mtype, self.rows[r], col.key):
            self.on_status(self._dis_msg(col))
            return
        if col.kind == "choice":
            self._open_choice()
            return
        self.mode = "edit"
        self._sync_editor()
        self.ed.icursor("end")
        if select_all:
            self.ed.select_range(0, "end")
        else:
            self.ed.select_clear()
        self.ed.focus_set()

    def _dis_msg(self, col):
        if self.mtype == "beam":
            return f"'{col.group} {col.title}' 칸은 '구분'에 따라 쓰지 않는 칸입니다. 구분을 바꾸면 입력할 수 있습니다."
        return "이 칸은 지금 쓰지 않는 칸입니다."

    def commit(self):
        """입력 중인 값 확정. 바뀌었으면 True."""
        if self.mode == "nav":
            return False
        r, c = self.cur
        col = self.cols[c]
        text = self.var.get()
        self.mode = "nav"
        new = M.normalize(col.kind, text, self.get_prefix(), col.choices)
        old = self._cell_value(r, c)
        if new == old:
            self._sync_editor()
            return False
        self._push_undo()
        self._ensure_row(r)
        self.rows[r][col.key] = new
        if not M.is_valid(col.kind, new, col.choices):
            self.on_status(f"'{new}' — 표기를 확인하세요 (예: {self._example(col.kind)})")
        self._changed()
        return True

    def cancel(self):
        self.mode = "nav"
        self._sync_editor()

    def _example(self, kind):
        p = self.get_prefix()
        return {"rebar": f"4-{p}22, 5/2-{p}22", "stir": f"{p}10@200", "spacing": f"{p}13@200, {p}10,{p}13@300",
                "num": "600"}.get(kind, "")

    def _ensure_row(self, r):
        while r >= len(self.rows):
            prev = self.rows[-1] if self.rows else None
            self.rows.append(M.new_row(self.mtype, prev))

    # ═════════════════════════════════════════════════════════════
    #  이동 / 선택
    # ═════════════════════════════════════════════════════════════
    def sel_range(self):
        (r1, c1), (r2, c2) = self.anchor, self.cur
        return (min(r1, r2), min(c1, c2)), (max(r1, r2), max(c1, c2))

    def _is_multi(self):
        return self.anchor != self.cur

    def move_to(self, r, c, extend=False):
        r = max(0, min(self.nrows - 1, r))
        c = max(0, min(len(self.cols) - 1, c))
        self.cur = (r, c)
        if not extend:
            self.anchor = (r, c)
        self.ensure_visible(r, c)
        self.mode = "nav"
        self.redraw()
        self._sync_editor()
        self.ed.focus_set()
        self.on_select(r)
        col = self.cols[c]
        if r < len(self.rows) and M.disabled(self.mtype, self.rows[r], col.key):
            self.on_status(self._dis_msg(col))
        elif col.kind in ("rebar", "stir", "spacing"):
            self.on_status(f"{col.full_title}  ·  예: {self._example(col.kind)}  ·  숫자만 쳐도 강종({self.get_prefix()})이 붙습니다  ·  F4 강종 바꾸기")
        elif col.kind == "choice":
            self.on_status(f"{col.title}: " + "  ".join(f"[{i + 1}] {v}" for i, v in enumerate(col.choices)) + "   (클릭 · 숫자키 · Space)")
        else:
            self.on_status("")

    def ensure_visible(self, r, c):
        v = self.vis_rows()
        if r < self.top:
            self.top = r
        elif r >= self.top + v:
            self.top = r - v + 1
        if c >= self.frozen:
            x0 = self.RH_W + self.frozen_w() + sum(self.W(i) for i in range(self.frozen, c))
            rel = x0 - self.RH_W - self.frozen_w()
            if rel < self.xoff:
                self.xoff = rel
            elif rel + self.W(c) > self.xoff + self.view_w():
                self.xoff = rel + self.W(c) - self.view_w()
            self.xoff = max(0, min(self.xoff, max(0, self.scroll_w() - self.view_w())))

    def _jump(self, dr, dc):
        """Ctrl+방향키: 자료 끝/처음으로."""
        r, c = self.cur
        if dr:
            return (len(self.rows) - 1 if dr > 0 else 0), c
        return r, (len(self.cols) - 1 if dc > 0 else 0)

    # ═════════════════════════════════════════════════════════════
    #  키보드
    # ═════════════════════════════════════════════════════════════
    def _key(self, e):
        if not self.cols:
            return
        ks = e.keysym
        shift = bool(e.state & 0x1)
        ctrl = bool(e.state & 0x4)
        alt = bool(e.state & _ALT)
        r, c = self.cur
        col = self.cols[c]

        if self._pop:
            return "break"
        if self.cv.itemcget(self.ed_win, "state") == "hidden" and ks not in ("Shift_L", "Shift_R", "Control_L", "Control_R"):
            self.ensure_visible(r, c)
            self.redraw()
            self._sync_editor()
            self.ed.focus_set()
            if e.char and e.char.isprintable() and not ctrl and self.mode == "nav" and col.kind != "choice":
                self._set_text("")
                self.ed.insert("end", e.char)
                self.mode = "enter"
                self._sync_editor()
                return "break"

        # ── Ctrl 조합 ────────────────────────────────────────────
        if ctrl:
            k = ks.lower()
            if self.mode != "nav" and k in ("c", "x", "a") and self.ed.selection_present():
                return None                       # 입력 중 글자 복사는 기본 동작
            if k == "v" and self.mode != "nav":
                try:
                    clip = self.clipboard_get()
                except tk.TclError:
                    clip = ""
                if "\t" not in clip and "\n" not in clip.strip("\n"):
                    return None                   # 한 칸짜리는 글자 붙여넣기
                self.commit()
            if k in ("up", "down", "left", "right"):
                self.commit()
                dr = {"up": -1, "down": 1}.get(k, 0)
                dc = {"left": -1, "right": 1}.get(k, 0)
                nr, nc = self._jump(dr, dc)
                self.move_to(nr, nc, extend=shift)
                return "break"
            act = {"c": self.copy, "x": self.cut, "v": self.paste, "z": self.undo, "y": self.redo,
                   "d": self.fill_down, "r": self.fill_right, "a": self.select_all,
                   "home": lambda: self.move_to(0, 0, extend=shift),
                   "end": lambda: self.move_to(len(self.rows) - 1, len(self.cols) - 1, extend=shift),
                   "plus": self.insert_row_below, "equal": self.insert_row_below, "kp_add": self.insert_row_below,
                   "minus": self.delete_rows, "kp_subtract": self.delete_rows}.get(k)
            if act:
                if self.mode != "nav" and k not in ("z", "y"):
                    self.commit()
                elif self.mode != "nav":
                    self.cancel()
                act()
                return "break"
            return None

        # ── Alt 조합 ─────────────────────────────────────────────
        if alt:
            if ks in ("Return", "KP_Enter"):
                self.commit()
                self.duplicate_row()
                return "break"
            if ks in ("Up", "Down"):
                self.commit()
                self.move_rows(-1 if ks == "Up" else 1)
                return "break"
            if ks == "Down" and col.kind == "choice":
                self._open_choice()
                return "break"
            return None

        # ── 입력 모드 ────────────────────────────────────────────
        if self.mode == "edit" and ks in ("Left", "Right", "Home", "End"):
            return None                           # 칸 안에서 글자 이동
        if ks == "Escape":
            if self.mode != "nav":
                self.cancel()
            else:
                self.anchor = self.cur
                self.redraw()
                self._sync_editor()
            return "break"
        if ks == "F2":
            if self.mode == "enter":
                self.mode = "edit"
                self.on_status("고치기 모드 — ←→ 로 글자 사이를 움직입니다. Enter 로 확정.")
            else:
                self._begin_edit()
            return "break"
        if ks == "F4":
            self.commit()
            self.cycle_prefix()
            return "break"

        if ks in _NAV_KEYS:
            changed = self.commit()
            if ks in ("Return", "KP_Enter"):
                if shift:                          # 값 아래로 복사
                    self._copy_down_one()
                    return "break"
                self.move_to(r + 1, c)
            elif ks in ("Tab",) and not shift:
                if c + 1 < len(self.cols):
                    self.move_to(r, c + 1)
                else:
                    self.move_to(r + 1, 0)
            elif ks == "ISO_Left_Tab" or (ks == "Tab" and shift):
                self.move_to(r, c - 1) if c > 0 else self.move_to(r - 1, len(self.cols) - 1)
            elif ks == "Up":
                self.move_to(r - 1, c, extend=shift)
            elif ks == "Down":
                self.move_to(r + 1, c, extend=shift)
            elif ks == "Left":
                self.move_to(r, c - 1, extend=shift)
            elif ks == "Right":
                self.move_to(r, c + 1, extend=shift)
            elif ks == "Home":
                self.move_to(r, 0, extend=shift)
            elif ks == "End":
                self.move_to(r, len(self.cols) - 1, extend=shift)
            elif ks == "Prior":
                self.move_to(r - self.vis_rows(), c, extend=shift)
            elif ks == "Next":
                self.move_to(r + self.vis_rows(), c, extend=shift)
            _ = changed
            return "break"

        if self.mode == "nav":
            dis = r < len(self.rows) and M.disabled(self.mtype, self.rows[r], col.key)
            if ks == "Delete":
                self.clear_range()
                return "break"
            if ks == "BackSpace":
                if dis:
                    return "break"
                self.ed.config(state="normal")
                self._set_text("")
                self.mode = "enter"
                self._sync_editor()
                return "break"
            if col.kind == "choice":
                if ks == "space" or (e.char and e.char.isprintable()):
                    if dis:
                        return "break"
                    ch = e.char
                    if ch and ch.isdigit() and 1 <= int(ch) <= len(col.choices):
                        self._set_cell(r, c, col.choices[int(ch) - 1])
                    elif ch and ch.strip():
                        hit = [v for v in col.choices if v.startswith(ch)]
                        if hit:
                            self._set_cell(r, c, hit[0])
                        else:
                            self._open_choice()
                    else:
                        self._open_choice()
                    return "break"
            if col.kind == "drawn" and e.char and e.char.isprintable():
                self.on_status("그림 대조: CAD 에서 가져온 단면 그림의 철근 개수와 글자를 비교합니다 (Delete 로 지움).")
                return "break"
            if dis and e.char and e.char.isprintable():
                self.on_status(self._dis_msg(col))
                return "break"
        return None

    # ═════════════════════════════════════════════════════════════
    #  선택 목록 (구분·형태 등)
    # ═════════════════════════════════════════════════════════════
    def _open_choice(self):
        r, c = self.cur
        col = self.cols[c]
        if not col.choices:
            return
        self._close_pop()
        pop = tk.Toplevel(self)
        pop.wm_overrideredirect(True)
        try:
            pop.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        lb = tk.Listbox(pop, font=T.F_CELL, activestyle="none", selectbackground=T.ORANGE, selectforeground="white",
                        relief="solid", bd=1, height=len(col.choices), exportselection=False)
        for i, v in enumerate(col.choices):
            lb.insert("end", f" {i + 1}  {v}")
        lb.pack(fill="both", expand=True)
        cur = self._cell_value(r, c)
        idx = col.choices.index(cur) if cur in col.choices else 0
        lb.selection_set(idx)
        lb.activate(idx)
        x = self.cv.winfo_rootx() + self.col_x(c)
        y = self.cv.winfo_rooty() + self.row_y(r) + self.ROW_H
        pop.geometry(f"{max(self.W(c), 120)}x{len(col.choices) * 22 + 6}+{x}+{y}")
        self._pop = pop

        def pick(_=None):
            sel = lb.curselection()
            v = col.choices[sel[0]] if sel else None
            self._close_pop()
            if v is not None:
                self._set_cell(r, c, v)
            return "break"

        def key(e):
            if e.keysym in ("Return", "KP_Enter", "space"):
                return pick()
            if e.keysym == "Escape":
                self._close_pop()
                return "break"
            if e.char and e.char.isdigit() and 1 <= int(e.char) <= len(col.choices):
                lb.selection_clear(0, "end")
                lb.selection_set(int(e.char) - 1)
                return pick()
            if e.keysym in ("Up", "Down"):
                i = lb.curselection()[0] if lb.curselection() else 0
                i = max(0, min(len(col.choices) - 1, i + (1 if e.keysym == "Down" else -1)))
                lb.selection_clear(0, "end")
                lb.selection_set(i)
                lb.activate(i)
                return "break"
            return "break"

        lb.bind("<KeyPress>", key)
        lb.bind("<ButtonRelease-1>", pick)
        lb.bind("<FocusOut>", lambda e: self.after(80, self._close_pop))
        lb.focus_set()

    def _close_pop(self):
        if self._pop:
            try:
                self._pop.destroy()
            except tk.TclError:
                pass
            self._pop = None
            try:
                self.ed.focus_set()
            except tk.TclError:
                pass

    # ═════════════════════════════════════════════════════════════
    #  편집 동작
    # ═════════════════════════════════════════════════════════════
    def _push_undo(self):
        self.undo_stack.append(copy.deepcopy(self.rows))
        if len(self.undo_stack) > 300:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _restore(self, snap):
        self.rows[:] = snap
        self.cur = (min(self.cur[0], self.nrows - 1), self.cur[1])
        self.anchor = self.cur
        self._changed()

    def undo(self):
        if not self.undo_stack:
            self.on_status("되돌릴 내용이 없습니다.")
            return
        self.redo_stack.append(copy.deepcopy(self.rows))
        self._restore(self.undo_stack.pop())

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(copy.deepcopy(self.rows))
        self._restore(self.redo_stack.pop())

    def _changed(self):
        self.mode = "nav"
        self.redraw()
        self._sync_editor()
        self.on_change()
        self.on_select(self.cur[0])

    def _set_cell(self, r, c, v, push=True):
        col = self.cols[c]
        if push:
            self._push_undo()
        self._ensure_row(r)
        self.rows[r][col.key] = v
        if push:
            self._changed()

    def _copy_down_one(self):
        r, c = self.cur
        v = self._cell_value(r, c)
        self._set_cell(r + 1, c, v)
        self.move_to(r + 1, c)

    def clear_range(self):
        (ra, ca), (rb, cb) = self.sel_range()
        self._push_undo()
        for r in range(ra, min(rb, len(self.rows) - 1) + 1):
            for c in range(ca, cb + 1):
                self.rows[r][self.cols[c].key] = ""
        self._changed()

    def select_all(self):
        self.anchor = (0, 0)
        self.cur = (max(0, len(self.rows) - 1), len(self.cols) - 1)
        self.redraw()
        self._sync_editor()

    def _range_tsv(self):
        (ra, ca), (rb, cb) = self.sel_range()
        lines = []
        for r in range(ra, min(rb, len(self.rows) - 1) + 1):
            lines.append("\t".join(self.rows[r].get(self.cols[c].key, "") for c in range(ca, cb + 1)))
        return "\n".join(lines)

    def copy(self):
        txt = self._range_tsv()
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.on_status("복사했습니다 (엑셀에 바로 붙여넣을 수 있습니다).")

    def cut(self):
        self.copy()
        self.clear_range()

    def paste(self):
        try:
            clip = self.clipboard_get()
        except tk.TclError:
            return
        clip = clip.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
        if not clip:
            return
        block = [ln.split("\t") for ln in clip.split("\n")]
        (ra, ca), (rb, cb) = self.sel_range()
        pfx = self.get_prefix()
        self._push_undo()
        if len(block) == 1 and len(block[0]) == 1 and (ra, ca) != (rb, cb):
            for r in range(ra, rb + 1):
                for c in range(ca, cb + 1):
                    col = self.cols[c]
                    self._ensure_row(r)
                    if col.kind != "drawn":
                        self.rows[r][col.key] = M.normalize(col.kind, block[0][0], pfx, col.choices)
        else:
            for i, line in enumerate(block):
                for j, v in enumerate(line):
                    c = ca + j
                    if c >= len(self.cols):
                        break
                    col = self.cols[c]
                    self._ensure_row(ra + i)
                    if col.kind == "drawn":
                        continue
                    self.rows[ra + i][col.key] = M.normalize(col.kind, v, pfx, col.choices)
            self.anchor = (ra, ca)
            self.cur = (ra + len(block) - 1, min(len(self.cols) - 1, ca + max(len(x) for x in block) - 1))
        self._changed()
        self.on_status(f"붙여넣기: {len(block)}행")

    def fill_down(self):
        (ra, ca), (rb, cb) = self.sel_range()
        if ra == rb:
            if ra == 0:
                return
            src = ra - 1
            tgt = [ra]
        else:
            src = ra
            tgt = range(ra + 1, rb + 1)
        self._push_undo()
        for r in tgt:
            self._ensure_row(r)
            for c in range(ca, cb + 1):
                k = self.cols[c].key
                self.rows[r][k] = self.rows[src].get(k, "")
        self._changed()

    def fill_right(self):
        (ra, ca), (rb, cb) = self.sel_range()
        if ca == cb:
            if ca == 0:
                return
            src, tgt = ca - 1, [ca]
        else:
            src, tgt = ca, range(ca + 1, cb + 1)
        self._push_undo()
        for r in range(ra, min(rb, len(self.rows) - 1) + 1):
            for c in tgt:
                self.rows[r][self.cols[c].key] = self.rows[r].get(self.cols[src].key, "")
        self._changed()

    def insert_row_below(self, above=False):
        r = self.cur[0]
        at = min(len(self.rows), r if above else r + 1)
        self._push_undo()
        self.rows.insert(at, M.new_row(self.mtype))
        self.cur = self.anchor = (at, 0)
        self.ensure_visible(at, 0)
        self._changed()

    def duplicate_row(self):
        r = self.cur[0]
        if r >= len(self.rows):
            return
        self._push_undo()
        self.rows.insert(r + 1, M.new_row(self.mtype, self.rows[r]))
        self.cur = self.anchor = (r + 1, self.cur[1])
        self.ensure_visible(r + 1, self.cur[1])
        self._changed()
        self.on_status("행을 복제했습니다 (부호 번호 +1). 바뀐 칸만 고치세요.")

    def delete_rows(self):
        (ra, _), (rb, _) = self.sel_range()
        rb = min(rb, len(self.rows) - 1)
        if ra > rb:
            return
        self._push_undo()
        del self.rows[ra:rb + 1]
        self.cur = self.anchor = (min(ra, max(0, len(self.rows))), self.cur[1])
        self._changed()
        self.on_status(f"{rb - ra + 1}행 삭제 (Ctrl+Z 로 되돌리기)")

    def move_rows(self, d):
        (ra, _), (rb, _) = self.sel_range()
        rb = min(rb, len(self.rows) - 1)
        if ra > rb or (d < 0 and ra == 0) or (d > 0 and rb >= len(self.rows) - 1):
            return
        self._push_undo()
        blk = self.rows[ra:rb + 1]
        del self.rows[ra:rb + 1]
        self.rows[ra + d:ra + d] = blk
        self.anchor = (self.anchor[0] + d, self.anchor[1])
        self.cur = (self.cur[0] + d, self.cur[1])
        self.ensure_visible(*self.cur)
        self._changed()

    def cycle_prefix(self, to=None):
        """선택 범위 철근 칸의 강종 기호 바꾸기."""
        (ra, ca), (rb, cb) = self.sel_range()
        cells = [(r, c) for r in range(ra, min(rb, len(self.rows) - 1) + 1) for c in range(ca, cb + 1)
                 if self.cols[c].kind in ("rebar", "stir", "spacing") and self.rows[r].get(self.cols[c].key)]
        if not cells:
            self.on_status("F4: 철근 칸을 선택하세요.")
            return
        if to is None:
            first = self.rows[cells[0][0]][self.cols[cells[0][1]].key]
            p = M.parse_rebar(first) or M.parse_stir(first) or M.parse_spacing(first) or {}
            curp = p.get("pfx") or self.get_prefix()
            i = M.PREFIXES.index(curp) if curp in M.PREFIXES else -1
            to = M.PREFIXES[(i + 1) % len(M.PREFIXES)]
        self._push_undo()
        for r, c in cells:
            col = self.cols[c]
            self.rows[r][col.key] = M.swap_prefix(self.rows[r][col.key], col.kind, to)
        self._changed()
        self.on_status(f"강종 → {to}  ({len(cells)}칸)")

    def sort_by_name(self):
        self._push_undo()
        self.rows.sort(key=lambda r: M.natural_key(r.get("name", "")))
        self._changed()

    # ═════════════════════════════════════════════════════════════
    #  마우스 / 스크롤
    # ═════════════════════════════════════════════════════════════
    def _border_at(self, x, y):
        if y > self.hdr_h():
            return None
        for c in range(len(self.cols)):
            x1 = self.col_x(c) + self.W(c)
            if abs(x - x1) <= 4:
                return c
        return None

    def _hover(self, e):
        self.cv.config(cursor="sb_h_double_arrow" if self._border_at(e.x, e.y) is not None else "")

    def _click(self, e):
        self._close_pop()
        b = self._border_at(e.x, e.y)
        if b is not None:
            self._resize = (b, e.x, self.W(b))
            return
        self.commit()
        r, c = self.cell_at(e.x, e.y)
        shift = bool(e.state & 0x1)
        if r < 0 and c >= 0:                       # 열 머리글 → 열 선택
            self.anchor = (0, c)
            self.cur = (max(0, len(self.rows) - 1), c)
            self.redraw()
            self._sync_editor()
            self.ed.focus_set()
            return
        if r >= self.nrows:
            r = self.nrows - 1
        if c < 0:                                  # 행 번호 → 행 선택
            if shift:
                self.cur = (r, len(self.cols) - 1)
            else:
                self.anchor = (r, 0)
                self.cur = (r, len(self.cols) - 1)
            self.redraw()
            self._sync_editor()
            self.ed.focus_set()
            self.on_select(r)
            self._drag = "row"
            return
        self.move_to(r, c, extend=shift)
        self._drag = "cell"
        self._press = (r, c) if not shift else None

    def _motion_drag(self, e):
        if self._resize:
            c, x0, w0 = self._resize
            self.widths[(self.mtype, self.cols[c].key)] = max(self.MIN_W, w0 + e.x - x0)
            self.redraw()
            self._sync_editor()
            return
        if not self._drag:
            return
        if e.y > self.cv.winfo_height() - 4:
            self._scroll_rows(1)
        elif e.y < self.hdr_h() and self.top > 0:
            self._scroll_rows(-1)
        r, c = self.cell_at(max(0, e.x), max(self.hdr_h() + 1, e.y))
        r = max(0, min(self.nrows - 1, r))
        if self._drag == "row":
            c = len(self.cols) - 1
        c = max(0, c)
        if (r, c) != self.cur:
            self.cur = (r, c)
            self.redraw()
            self._sync_editor()

    def _release(self, e):
        self._resize = None
        was = self._drag
        self._drag = None
        press, self._press = getattr(self, "_press", None), None
        if was == "cell" and press and press == self.cur == self.anchor:     # 클릭 = 구분 목록 열기
            r, c = press
            col = self.cols[c]
            if col.kind == "choice" and r < len(self.rows) and not M.disabled(self.mtype, self.rows[r], col.key):
                self.after(10, self._open_choice)

    def _dbl(self, e):
        r, c = self.cell_at(e.x, e.y)
        if r >= 0 and c >= 0:
            self._begin_edit()

    def _ctx(self, e):
        r, c = self.cell_at(e.x, e.y)
        if r >= 0 and c >= 0:
            (ra, ca), (rb, cb) = self.sel_range()
            if not (ra <= r <= rb and ca <= c <= cb):
                self.move_to(r, c)
        m = tk.Menu(self, tearoff=0, font=T.F_UI)
        m.add_command(label="잘라내기          Ctrl+X", command=self.cut)
        m.add_command(label="복사                Ctrl+C", command=self.copy)
        m.add_command(label="붙여넣기          Ctrl+V", command=self.paste)
        m.add_command(label="지우기             Delete", command=self.clear_range)
        m.add_separator()
        m.add_command(label="아래에 행 삽입    Ctrl++", command=self.insert_row_below)
        m.add_command(label="위에 행 삽입", command=lambda: self.insert_row_below(above=True))
        m.add_command(label="행 복제 (부호+1)  Alt+Enter", command=self.duplicate_row)
        m.add_command(label="행 삭제             Ctrl+-", command=self.delete_rows)
        m.add_command(label="위로 이동          Alt+↑", command=lambda: self.move_rows(-1))
        m.add_command(label="아래로 이동       Alt+↓", command=lambda: self.move_rows(1))
        m.add_separator()
        m.add_command(label="아래로 채우기     Ctrl+D", command=self.fill_down)
        m.add_command(label="오른쪽으로 채우기 Ctrl+R", command=self.fill_right)
        sub = tk.Menu(m, tearoff=0, font=T.F_UI)
        for p in M.PREFIXES:
            sub.add_command(label=p, command=lambda p=p: self.cycle_prefix(p))
        m.add_cascade(label="강종 바꾸기  (F4)", menu=sub)
        m.add_command(label="부호 순서로 정렬", command=self.sort_by_name)
        if self.extra_menu:
            self.extra_menu(m)
        m.tk_popup(e.x_root, e.y_root)

    def _vscroll(self, *a):
        n = self.nrows
        if a[0] == "moveto":
            self.top = int(float(a[1]) * n)
        elif a[0] == "scroll":
            step = int(a[1]) * (self.vis_rows() if a[2] == "pages" else 1)
            self.top += step
        self.top = max(0, min(self.top, max(0, n - self.vis_rows())))
        self.redraw()
        self._sync_editor()

    def _hscroll(self, *a):
        sw = self.scroll_w()
        if a[0] == "moveto":
            self.xoff = int(float(a[1]) * sw)
        elif a[0] == "scroll":
            self.xoff += int(a[1]) * (self.view_w() if a[2] == "pages" else 40)
        self.xoff = max(0, min(self.xoff, max(0, sw - self.view_w())))
        self.redraw()
        self._sync_editor()

    def _scroll_rows(self, d):
        self.top = max(0, min(self.top + d, max(0, self.nrows - self.vis_rows())))
        self.redraw()
        self._sync_editor()
        return "break"

    def _wheel(self, e):
        return self._scroll_rows(-3 if e.delta > 0 else 3)

    def _hwheel(self, d):
        self._hscroll("scroll", d, "units")
        return "break"
