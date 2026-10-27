"""현장조사 입력 도우미 — 선택 목록, 철근 선택, 사진(드래그 앤 드롭).

Drag & drop of photo files uses the optional `tkinterdnd2` package
(pip install tkinterdnd2). Without it, photos are added with the file dialog.
"""
from __future__ import annotations

import os
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

FONT = ("Malgun Gothic", 9)
BLUE = "#4a90d9"
BLUE_D = "#2f6db5"
BG = "#eef2f7"
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".heic", ".webp", ".tif", ".tiff")

# ---------------------------------------------------------------- drag & drop
_DND = None


def enable_dnd(widget) -> bool:
    """Load tkdnd into the Tk interpreter once. Returns True if drag & drop works."""
    global _DND
    if _DND is not None:
        return _DND
    try:
        from tkinterdnd2 import TkinterDnD  # noqa: F401  (injects drop_target_register into widgets)
        TkinterDnD._require(widget._root())
        _DND = True
    except Exception:            # noqa: BLE001 — package missing or tkdnd not loadable
        _DND = False
    return _DND


def add_drop(widget, on_files) -> bool:
    """Make widget accept dropped files → on_files([paths])."""
    if not enable_dnd(widget):
        return False
    try:
        widget.drop_target_register("DND_Files")

        def _drop(ev):
            files = [f for f in widget.tk.splitlist(ev.data) if f]
            on_files(files)
            return ev.action
        widget.dnd_bind("<<Drop>>", _drop)
        widget.dnd_bind("<<DropEnter>>", lambda ev: (widget.configure(bg=BLUE_D) if isinstance(widget, tk.Button)
                                                     else None, ev.action)[1])
        widget.dnd_bind("<<DropLeave>>", lambda ev: (widget.configure(bg=BLUE) if isinstance(widget, tk.Button)
                                                     else None, ev.action)[1])
        return True
    except Exception:            # noqa: BLE001
        return False


def copy_photos(files, folder, prefix=""):
    """Copy image files into the project photo folder (keeps originals). Returns new paths."""
    out = []
    os.makedirs(folder, exist_ok=True)
    for f in files:
        if not os.path.isfile(f) or not f.lower().endswith(IMG_EXT):
            continue
        base = prefix + os.path.basename(f)
        dst = os.path.join(folder, base)
        k = 1
        while os.path.exists(dst) and not _same_file(f, dst):
            stem, ext = os.path.splitext(base)
            dst = os.path.join(folder, f"{stem}_{k}{ext}")
            k += 1
        if not os.path.exists(dst):
            shutil.copy2(f, dst)
        out.append(dst)
    return out


def _same_file(a, b):
    """Same content (size + first 64 KB) — so dropping the same photo twice does not duplicate it."""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read(65536) == fb.read(65536)
    except OSError:
        return False


# ---------------------------------------------------------------- pick list
class PickDialog(tk.Toplevel):
    """Touch-friendly list: groups of option buttons + direct input + manage custom options.

    groups : [(title, [values], removable)]  — removable groups are the user's own options
    """

    def __init__(self, master, title, groups, current, on_pick, on_add=None, on_remove=None, unit="",
                 numeric=False):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.on_pick, self.on_add, self.on_remove = on_pick, on_add, on_remove
        self.groups = groups
        self.unit = unit
        self.manage = tk.BooleanVar(value=False)
        self.f = tk.Frame(self, bg=BG, padx=12, pady=10)
        self.f.pack(fill="both")
        top = tk.Frame(self.f, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text=title + (f"  ({unit})" if unit else ""), bg=BG, font=("Malgun Gothic", 12, "bold")).pack(
            side="left")
        if on_remove:
            ttk.Checkbutton(top, text="목록 정리", variable=self.manage, command=self._draw).pack(side="right")
        self.body = tk.Frame(self.f, bg=BG)
        self.body.pack(fill="both", pady=(6, 0))
        inp = tk.Frame(self.f, bg=BG)
        inp.pack(fill="x", pady=(10, 0))
        tk.Label(inp, text="직접 입력", bg=BG, font=FONT).pack(side="left")
        self.v = tk.StringVar(value=current or "")
        e = tk.Entry(inp, textvariable=self.v, font=("Malgun Gothic", 12), width=16, justify="center")
        e.pack(side="left", padx=6, ipady=3)
        e.bind("<Return>", lambda ev: self._pick(self.v.get().strip()))
        ttk.Button(inp, text="확인", command=lambda: self._pick(self.v.get().strip())).pack(side="left")
        if on_add:
            ttk.Button(inp, text="목록에 추가", command=self._add).pack(side="left", padx=4)
        ttk.Button(inp, text="지우기", command=lambda: self._pick("")).pack(side="left")
        self._draw()
        self.bind("<Escape>", lambda ev: self.destroy())
        e.focus_set()
        e.select_range(0, "end")
        self.update_idletasks()
        try:
            x = master.winfo_pointerx() - self.winfo_reqwidth() // 2
            y = master.winfo_pointery() - 40
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass
        self.grab_set()

    def _draw(self):
        for w in self.body.winfo_children():
            w.destroy()
        cur = self.v.get()
        r = 0
        for title, values, removable in self.groups:
            if not values:
                continue
            tk.Label(self.body, text=title, bg=BG, fg="#555", font=FONT).grid(row=r, column=0, columnspan=6,
                                                                             sticky="w", pady=(4, 1))
            r += 1
            for i, val in enumerate(values):
                on = str(val) == cur
                if self.manage.get() and removable:
                    b = tk.Button(self.body, text=f"✕ {val}", bg="#f87171", fg="white", relief="flat",
                                  font=("Malgun Gothic", 11), width=9,
                                  command=lambda v=val, t=title: self._remove(t, v))
                else:
                    b = tk.Button(self.body, text=str(val), bg=BLUE_D if on else BLUE, fg="white", relief="flat",
                                  activebackground=BLUE_D, font=("Malgun Gothic", 11, "bold" if on else "normal"),
                                  width=9, command=lambda v=val: self._pick(str(v)))
                b.grid(row=r + i // 5, column=i % 5, padx=2, pady=2, ipady=4, sticky="ew")
            r += (len(values) + 4) // 5

    def _pick(self, val):
        self.destroy()
        self.on_pick(val)

    def _add(self):
        val = self.v.get().strip()
        if not val:
            return
        self.on_add(val)
        for i, g in enumerate(self.groups):
            if g[2] and val not in g[1]:
                g[1].append(val)
                break
        self._draw()

    def _remove(self, title, val):
        self.on_remove(val)
        for g in self.groups:
            if g[0] == title and val in g[1]:
                g[1].remove(val)
        self._draw()


# ---------------------------------------------------------------- rebar picker
BAR_PREFIX = ("D", "HD", "SHD", "UHD")
BAR_DIA = (10, 13, 16, 19, 22, 25, 29, 32, 35)
BAR_COUNT = (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 20)
BAR_SPACING = (100, 125, 150, 175, 200, 250, 300, 400)


def parse_bar(s):
    """'4-HD22' → (4, 'HD', 22, None) ; 'HD10@200' → (None, 'HD', 10, 200)"""
    import re
    s = (s or "").replace(" ", "").upper()
    m = re.match(r"^(?:(\d+)-)?([A-Z]*)(\d+)(?:@(\d+))?$", s)
    if not m:
        return None, "HD", None, None
    n, pre, d, sp = m.groups()
    return (int(n) if n else None, pre or "D", int(d), int(sp) if sp else None)


def fmt_bar(n, pre, d, sp):
    if d is None:
        return ""
    s = f"{pre}{d}"
    if n:
        s = f"{n}-{s}"
    if sp:
        s += f"@{sp}"
    return s


class RebarPickDialog(tk.Toplevel):
    """철근 칸 클릭 — 개수 / 규격(D·HD·SHD·UHD) / 직경 / 간격 선택."""

    def __init__(self, master, title, current, mode, on_pick):
        """mode: 'count' (주근: 개수+직경) | 'spacing' (스터럽·띠철근·벽: 직경+간격) | 'both'"""
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.on_pick = on_pick
        n, pre, d, sp = parse_bar(current)
        if mode == "count" and n is None:
            n = 4
        self.n = tk.IntVar(value=n or 0)
        self.pre = tk.StringVar(value=pre if pre in BAR_PREFIX else "HD")
        self.d = tk.IntVar(value=d or (22 if mode == "count" else 10))
        self.sp = tk.IntVar(value=sp or (200 if mode != "count" else 0))
        self.mode = mode
        f = tk.Frame(self, bg=BG, padx=12, pady=10)
        f.pack()
        self.preview = tk.Label(f, text="", bg=BLUE_D, fg="white", font=("Malgun Gothic", 14, "bold"), pady=6)
        self.preview.pack(fill="x")
        if mode in ("count", "both"):
            self._row(f, "개수", BAR_COUNT, self.n, lambda v: f"{v}개")
        self._row(f, "규격", BAR_PREFIX, self.pre, str)
        self._row(f, "직경", BAR_DIA, self.d, lambda v: f"D{v}")
        if mode in ("spacing", "both"):
            self._row(f, "간격", BAR_SPACING, self.sp, lambda v: f"@{v}")
        b = tk.Frame(f, bg=BG)
        b.pack(fill="x", pady=(10, 0))
        ttk.Button(b, text="지우기", command=lambda: self._done("")).pack(side="left")
        ttk.Button(b, text="확인", command=lambda: self._done(self._value())).pack(side="right")
        ttk.Button(b, text="취소", command=self.destroy).pack(side="right", padx=4)
        self._update()
        self.bind("<Return>", lambda e: self._done(self._value()))
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()

    def _row(self, parent, label, values, var, fmt):
        fr = tk.Frame(parent, bg=BG)
        fr.pack(fill="x", pady=(8, 0))
        tk.Label(fr, text=label, bg=BG, font=("Malgun Gothic", 10, "bold"), width=5, anchor="w").grid(
            row=0, column=0, rowspan=2, sticky="nw")
        btns = []
        for i, v in enumerate(values):
            b = tk.Button(fr, text=fmt(v), relief="flat", fg="white", font=("Malgun Gothic", 10), width=6,
                          command=lambda v=v: (var.set(v), self._update()))
            b.grid(row=i // 7, column=1 + i % 7, padx=2, pady=2, ipady=3)
            btns.append((v, b))
        setattr(self, f"_btns_{label}", (var, btns))

    def _update(self):
        for label in ("개수", "규격", "직경", "간격"):
            t = getattr(self, f"_btns_{label}", None)
            if not t:
                continue
            var, btns = t
            for v, b in btns:
                b.configure(bg=BLUE_D if var.get() == v else BLUE)
        self.preview.config(text=self._value() or "-")

    def _value(self):
        n = self.n.get() if self.mode in ("count", "both") else None
        sp = self.sp.get() if self.mode in ("spacing", "both") else None
        return fmt_bar(n or None, self.pre.get(), self.d.get(), sp or None)

    def _done(self, val):
        self.destroy()
        self.on_pick(val)


def rebar_mode(row):
    return "spacing" if row in ("스터럽", "띠철근", "배근") else "count"


# ---------------------------------------------------------------- rebar grid
class RebarDialog(tk.Toplevel):
    """철근 클릭 시 — I단/중앙/J단 × 상부근/하부근/스터럽. 각 칸을 누르면 개수·직경·간격 선택."""

    def __init__(self, master, rec_label, rows, cols, current, on_save):
        super().__init__(master)
        self.title(f"철근 — {rec_label}")
        self.transient(master)
        self.resizable(False, False)
        self.configure(bg="#e5e7eb")
        self.val = dict(current or {})
        f = tk.Frame(self, bg="#e5e7eb", padx=14, pady=12)
        f.pack()
        for j, c in enumerate(cols):
            tk.Label(f, text=c, bg=BLUE, fg="white", font=("Malgun Gothic", 11, "bold"), width=11, pady=6).grid(
                row=0, column=j + 1, padx=4, pady=4)
        self.btn = {}
        for i, r in enumerate(rows):
            tk.Label(f, text=r, bg=BLUE_D, fg="white", font=("Malgun Gothic", 10, "bold"), width=6, pady=8).grid(
                row=i + 1, column=0, padx=4, pady=4)
            for j, c in enumerate(cols):
                k = f"{r}|{c}"
                b = tk.Button(f, text=self.val.get(k, "") or "선택", width=11, font=("Malgun Gothic", 11),
                              bg=BLUE, fg="white", relief="flat", activebackground=BLUE_D,
                              command=lambda k=k, r=r, c=c: self._pick(k, r, c))
                b.grid(row=i + 1, column=j + 1, padx=4, pady=4, ipady=6)
                self.btn[k] = b
        ctl = tk.Frame(f, bg="#e5e7eb")
        ctl.grid(row=len(rows) + 1, column=0, columnspan=len(cols) + 1, sticky="ew", pady=(8, 0))
        ttk.Button(ctl, text="중앙 → 양단 복사", command=lambda: self._copy(rows, cols)).pack(side="left")
        ttk.Button(ctl, text="확인", command=lambda: (on_save({k: v for k, v in self.val.items() if v}),
                                                    self.destroy())).pack(side="right")
        ttk.Button(ctl, text="취소", command=self.destroy).pack(side="right", padx=4)
        self.grab_set()

    def _pick(self, k, r, c):
        def done(v):
            self.val[k] = v
            self.btn[k].config(text=v or "선택")
        RebarPickDialog(self, f"{r} · {c}", self.val.get(k, ""), rebar_mode(r), done)

    def _copy(self, rows, cols):
        mid = "중앙" if "중앙" in cols else cols[0]
        for r in rows:
            v = self.val.get(f"{r}|{mid}", "")
            if not v:
                continue
            for c in cols:
                if c != mid and not self.val.get(f"{r}|{c}"):
                    self.val[f"{r}|{c}"] = v
                    self.btn[f"{r}|{c}"].config(text=v)


# ---------------------------------------------------------------- photos
class PhotoDialog(tk.Toplevel):
    """사진 — 썸네일, 추가(파일/드래그), 열기, 제거."""

    def __init__(self, master, title, photos, on_save, add_files):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.configure(bg=BG)
        self.photos = list(photos)
        self.add_files = add_files            # callable(list[str]) -> list[str] (copies into project folder)
        self._imgs = []
        f = tk.Frame(self, bg=BG, padx=10, pady=10)
        f.pack(fill="both", expand=True)
        self.drop = tk.Label(f, text="", bg="#dbeafe", fg="#1e3a8a", font=("Malgun Gothic", 11), height=2,
                             relief="ridge")
        self.drop.pack(fill="x")
        self.grid = tk.Frame(f, bg=BG)
        self.grid.pack(fill="both", expand=True, pady=6)
        b = tk.Frame(f, bg=BG)
        b.pack(fill="x")
        ttk.Button(b, text="사진 추가…", command=self._browse).pack(side="left")
        ttk.Button(b, text="확인", command=lambda: (on_save(self.photos), self.destroy())).pack(side="right")
        ok = add_drop(self.drop, self._dropped) and add_drop(self.grid, self._dropped)
        self.drop.config(text="여기로 사진 파일을 끌어다 놓으세요" if ok else
                         "사진 추가… 버튼으로 넣으세요  (끌어다 놓기: pip install tkinterdnd2)")
        self._fill()
        self.grab_set()

    def _dropped(self, files):
        new = self.add_files(files)
        for p in new:
            if p not in self.photos:
                self.photos.append(p)
        self._fill()

    def _browse(self):
        fs = filedialog.askopenfilenames(parent=self, title="사진 선택",
                                         filetypes=[("이미지", " ".join("*" + e for e in IMG_EXT)), ("모든 파일", "*.*")])
        if fs:
            self._dropped(list(fs))

    def _fill(self):
        for w in self.grid.winfo_children():
            w.destroy()
        self._imgs = []
        try:
            from PIL import Image, ImageTk
        except ImportError:
            Image = None
        if not self.photos:
            tk.Label(self.grid, text="(사진 없음)", bg=BG, fg="#777").grid(row=0, column=0, pady=20)
        for i, p in enumerate(self.photos):
            cell = tk.Frame(self.grid, bg="white", bd=1, relief="solid")
            cell.grid(row=i // 4, column=i % 4, padx=4, pady=4)
            img = None
            if Image is not None and os.path.exists(p):
                try:
                    im = Image.open(p)
                    im.thumbnail((150, 110))
                    img = ImageTk.PhotoImage(im)
                    self._imgs.append(img)
                except Exception:         # noqa: BLE001
                    img = None
            if img:
                tk.Label(cell, image=img, bg="white").pack()
            else:
                tk.Label(cell, text="🖼" if os.path.exists(p) else "⚠ 파일 없음", width=18, height=6,
                         bg="white").pack()
            row = tk.Frame(cell, bg="white")
            row.pack(fill="x")
            tk.Label(row, text=os.path.basename(p)[:20], bg="white", font=("Malgun Gothic", 8)).pack(side="left")
            tk.Button(row, text="✕", relief="flat", bg="white", fg="#dc2626",
                      command=lambda p=p: self._remove(p)).pack(side="right")
            tk.Button(row, text="열기", relief="flat", bg="white", font=("Malgun Gothic", 8),
                      command=lambda p=p: _open(p)).pack(side="right")

    def _remove(self, p):
        self.photos.remove(p)
        self._fill()


def _open(p):
    from .survey import open_file
    if os.path.exists(p):
        open_file(p)
    else:
        messagebox.showwarning("사진", f"파일이 없습니다:\n{p}")
