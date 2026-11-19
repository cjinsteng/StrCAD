"""
information/map_tool.py — KDS 지도 보정 도구 (지도 이미지 → 위경도 격자)

  ① PDF 열기(그림 쪽 자동 찾기) 또는 캡처 이미지 열기
  ② [기준점] 지도 위 도시 표시를 클릭 → 도시 선택 (3곳 이상, 6곳 이상이면 2차식)
  ③ [구역값] 등풍속선·구역 안을 클릭 → 값 입력 (같은 색으로 이어진 영역이 채워짐)
  ④ [경계선] 선이 끊겨 넘치는 곳을 드래그로 막기
  ⑤ [미리보기]로 확인 → [저장]
  [값읽기] 클릭한 곳의 값을 바로 읽어 현재 프로젝트에 쓸 수도 있다.
"""
import math
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import maps
from . import theme as T

MODES = [("pan", "✋ 이동"), ("point", "📍 기준점"), ("seed", "🎨 구역값"),
         ("barrier", "✏ 경계선"), ("read", "🔎 값읽기")]

HELP = {
    "pan": "왼쪽 드래그로 지도 이동, 휠로 확대·축소합니다.\n(다른 모드에서도 오른쪽 드래그로 이동)",
    "point": "지도 위 도시 표시(●/◯)를 정확히 클릭하고 도시를 고르세요.\n서로 멀리 떨어진 3곳 이상 — "
             "예: 서울·부산·목포·강릉·제주. 6곳 이상이면 더 정확합니다.",
    "seed": "등풍속선(구역) 사이 빈 곳을 클릭하고 값을 넣으세요.\n같은 색으로 이어진 영역이 그 값으로 "
            "채워집니다. '등풍속선 사이는 큰 값' 규정대로 양쪽 선 중 큰 값을 넣으세요.",
    "barrier": "선이 끊겨 색이 넘치는 곳을 드래그해서 막으세요.",
    "read": "지도 위를 클릭하면 그 지점의 값(미리보기 기준)과 위경도를 보여줍니다.",
}

PALETTE = [(56, 189, 248), (34, 197, 94), (250, 204, 21), (249, 115, 22), (239, 68, 68),
           (168, 85, 247), (236, 72, 153), (20, 184, 166), (132, 204, 22), (99, 102, 241),
           (245, 158, 11), (14, 165, 233)]


class MapTool(tk.Toplevel):
    def __init__(self, parent, kind, site=None, on_pick=None, on_saved=None):
        super().__init__(parent)
        self.kind = kind
        self.info = maps.KINDS[kind]
        self.site = site                     # (lat, lon, 이름)
        self.on_pick = on_pick
        self.on_saved = on_saved
        self.title(f"지도 보정 — {self.info['title']}")
        self.configure(bg=T.BG)
        self.geometry("1280x820")
        self.minsize(980, 620)
        T.setup_style(self)

        self.img = None                      # PIL 원본
        self.pdf = None
        self.page_no = 0
        self.points = []                     # (px, py, lat, lon, 이름)
        self.seeds = []                      # (px, py, val)
        self.barriers = []
        self.labels = None
        self.values = []
        self.zoom = 0.5
        self._photo = None
        self._cur_bar = None
        self._picked = None
        self.mode = tk.StringVar(value="pan")
        self.tol = tk.IntVar(value=40)
        self.src_path = ""

        self._build()
        self._load_existing()
        self.bind("<Escape>", lambda e: self.destroy())

    # ── 화면 ──────────────────────────────────────────────
    def _build(self):
        bar = tk.Frame(self, bg=T.BG2, height=44)
        bar.pack(fill="x")
        T.btn(bar, "📄 PDF 열기", self._open_pdf, bg=T.ACC, fg=T.WHI).pack(side="left", padx=(10, 4), pady=7)
        T.btn(bar, "🖼 이미지 열기", self._open_image).pack(side="left", padx=4)
        self.pg_prev = T.btn(bar, "◀", lambda: self._goto_page(self.page_no - 1))
        self.pg_lbl = T.label(bar, "", bg=T.BG2, fg=T.TX2)
        self.pg_next = T.btn(bar, "▶", lambda: self._goto_page(self.page_no + 1))
        for w in (self.pg_prev, self.pg_lbl, self.pg_next):
            w.pack(side="left", padx=2)
        tk.Frame(bar, bg=T.BDR, width=1).pack(side="left", fill="y", padx=8, pady=8)
        for key, txt in MODES:
            tk.Radiobutton(bar, text=txt, variable=self.mode, value=key, indicatoron=False,
                           bg=T.BG3, fg=T.TXT, selectcolor=T.ACC, activebackground=T.BG5,
                           activeforeground=T.WHI, font=T.FONT_B, bd=0, padx=10, pady=4,
                           command=self._mode_changed).pack(side="left", padx=2)
        tk.Frame(bar, bg=T.BDR, width=1).pack(side="left", fill="y", padx=8, pady=8)
        T.label(bar, "색 허용오차", bg=T.BG2).pack(side="left")
        tk.Scale(bar, from_=5, to=120, orient="horizontal", variable=self.tol, length=110, bg=T.BG2,
                 fg=T.TXT, troughcolor=T.BG3, highlightthickness=0, bd=0, showvalue=True,
                 font=T.FONT_S).pack(side="left", padx=4)
        T.btn(bar, "💾 저장", self._save, bg=T.GRN, fg=T.WHI).pack(side="right", padx=10)
        T.btn(bar, "👁 미리보기", self._preview).pack(side="right", padx=4)
        T.btn(bar, "−", lambda: self._zoom_at(1 / 1.25)).pack(side="right", padx=2)
        T.btn(bar, "맞춤", self._fit).pack(side="right", padx=2)
        T.btn(bar, "+", lambda: self._zoom_at(1.25)).pack(side="right", padx=2)

        body = tk.Frame(self, bg=T.BG)
        body.pack(fill="both", expand=True)
        right = tk.Frame(body, bg=T.BG2, width=300)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        cf = tk.Frame(body, bg=T.CANV_BG)
        cf.pack(side="left", fill="both", expand=True)
        self.cv = tk.Canvas(cf, bg=T.CANV_BG, highlightthickness=0, cursor="crosshair")
        sx = ttk.Scrollbar(cf, orient="horizontal", command=self.cv.xview)
        sy = ttk.Scrollbar(cf, orient="vertical", command=self.cv.yview)
        self.cv.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        sy.pack(side="right", fill="y")
        sx.pack(side="bottom", fill="x")
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._drag)
        self.cv.bind("<ButtonRelease-1>", self._release)
        for b in ("<ButtonPress-3>", "<ButtonPress-2>"):
            self.cv.bind(b, lambda e: self.cv.scan_mark(e.x, e.y))
        for b in ("<B3-Motion>", "<B2-Motion>"):
            self.cv.bind(b, lambda e: self.cv.scan_dragto(e.x, e.y, gain=1))
        self.cv.bind("<MouseWheel>", lambda e: self._zoom_at(1.15 if e.delta > 0 else 1 / 1.15, e))
        self.cv.bind("<Button-4>", lambda e: self._zoom_at(1.15, e))
        self.cv.bind("<Button-5>", lambda e: self._zoom_at(1 / 1.15, e))
        self.cv.bind("<Motion>", self._motion)

        # 오른쪽 패널
        T.label(right, self.info["title"], fg=T.WHI, font=T.FONT_H, wraplength=280,
                justify="left").pack(anchor="w", padx=10, pady=(10, 0))
        T.label(right, f"{self.info['code']}  ·  단위 {self.info['unit']}  ·  {self.info['rule']}",
                fg=T.TX3, font=T.FONT_S, wraplength=280, justify="left").pack(anchor="w", padx=10)
        self.help = T.label(right, "", fg=T.TXT, wraplength=280, justify="left", bg=T.BG3)
        self.help.pack(fill="x", padx=10, pady=8, ipady=6, ipadx=4)

        T.section(right, "기준점 (도시)", T.CYN)
        fr, self.tv_pts = T.tree(right, ("도시", "위도", "경도", "오차px"), (60, 70, 70, 50), height=6)
        fr.pack(fill="x", padx=10)
        T.btn(right, "선택 기준점 삭제", self._del_point).pack(anchor="e", padx=10, pady=2)
        self.lbl_geo = T.label(right, "", fg=T.TX3, font=T.FONT_S, wraplength=280, justify="left")
        self.lbl_geo.pack(anchor="w", padx=10)

        T.section(right, "구역값", T.YEL)
        fr, self.tv_seed = T.tree(right, ("값", "x", "y"), (80, 70, 70), height=7)
        fr.pack(fill="x", padx=10)
        rb = tk.Frame(right, bg=T.BG2)
        rb.pack(fill="x", padx=10, pady=2)
        T.btn(rb, "선택 삭제", self._del_seed).pack(side="right")
        T.btn(rb, "경계선 모두 지우기", self._clear_barriers).pack(side="right", padx=4)

        T.section(right, "값 읽기 / 건설지점", T.ORANGE)
        self.lbl_read = T.label(right, "—", fg=T.WHI, font=T.FONT_B, wraplength=280, justify="left")
        self.lbl_read.pack(anchor="w", padx=10)
        self.btn_use = T.btn(right, "이 값을 프로젝트에 사용", self._use_value, bg=T.ORANGE, fg=T.WHI)
        if self.on_pick:
            self.btn_use.pack(anchor="w", padx=10, pady=4)
        self.status = T.label(right, "", fg=T.TX3, font=T.FONT_S, wraplength=280, justify="left")
        self.status.pack(side="bottom", anchor="w", padx=10, pady=8)
        self._mode_changed()

    def _mode_changed(self):
        self.help.config(text=HELP[self.mode.get()])
        self.cv.config(cursor="fleur" if self.mode.get() == "pan" else "crosshair")

    # ── 불러오기 ──────────────────────────────────────────
    def _load_existing(self):
        js = maps.load_grid(self.kind)
        if not js:
            self.status.config(text="아직 저장된 지도가 없습니다. PDF 또는 이미지를 여세요.")
            return
        cal = js.get("calib") or {}
        src = maps.MAP_DIR / f"{self.kind}_src.png"
        if src.exists():
            try:
                from PIL import Image
                self.img = Image.open(src).convert("RGB")
                self.points = [tuple(p) for p in cal.get("points", [])]
                self.seeds = [tuple(s) for s in cal.get("seeds", [])]
                self.barriers = [list(map(tuple, b)) for b in cal.get("barriers", [])]
                self.tol.set(int(cal.get("tol", 40)))
                self._fit()
                self._refresh_lists()
                self._preview(quiet=True)
                self.status.config(text=f"저장된 지도 ({js.get('created', '')}) 를 불러왔습니다.")
            except Exception as e:                   # noqa: BLE001
                self.status.config(text=f"원본 이미지를 열지 못했습니다: {e}")

    def _open_pdf(self):
        try:
            try:
                import pymupdf as fitz               # PyMuPDF
            except ImportError:
                import fitz
        except ImportError:
            messagebox.showinfo("PDF 열기",
                                "PDF 를 열려면 PyMuPDF 가 필요합니다.\n  pip install pymupdf\n\n"
                                "또는 PDF 의 지도 쪽을 캡처(PNG/JPG)해서 '이미지 열기'로 여세요.", parent=self)
            return
        p = filedialog.askopenfilename(parent=self, title=f"{self.info['code']} PDF 선택",
                                       filetypes=[("PDF", "*.pdf"), ("모든 파일", "*.*")])
        if not p:
            return
        try:
            self.pdf = fitz.open(p)
        except Exception as e:                       # noqa: BLE001
            messagebox.showerror("PDF", str(e), parent=self)
            return
        self.src_path = p
        hit = self._find_caption()
        self._goto_page(hit if hit is not None else 0)
        if hit is None:
            self.status.config(text=f"'{self.info['caption']}' 쪽을 찾지 못했습니다. ◀ ▶ 로 넘기세요.")

    def _find_caption(self):
        cap = self.info["caption"]
        hits = []
        for i, pg in enumerate(self.pdf):
            try:
                if pg.search_for(cap):
                    hits.append(i)
            except Exception:                        # noqa: BLE001
                continue
        for i in hits:                                # 그림이 있는 쪽 우선
            try:
                pg = self.pdf[i]
                if pg.get_images() or len(pg.get_drawings()) > 200:
                    return i
            except Exception:                        # noqa: BLE001
                pass
        return hits[-1] if hits else None

    def _goto_page(self, n):
        if not self.pdf:
            return
        n = max(0, min(n, len(self.pdf) - 1))
        self.page_no = n
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        from PIL import Image
        pg = self.pdf[n]
        pix = pg.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
        self.img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self.pg_lbl.config(text=f"{n + 1} / {len(self.pdf)} 쪽")
        self.labels = None
        self._fit()

    def _open_image(self):
        p = filedialog.askopenfilename(parent=self, title="지도 이미지 선택",
                                       filetypes=[("이미지", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                                                  ("모든 파일", "*.*")])
        if not p:
            return
        from PIL import Image
        try:
            self.img = Image.open(p).convert("RGB")
        except Exception as e:                       # noqa: BLE001
            messagebox.showerror("이미지", str(e), parent=self)
            return
        self.src_path = p
        self.pdf = None
        self.pg_lbl.config(text="")
        self.labels = None
        self._fit()

    # ── 그리기 ────────────────────────────────────────────
    def _fit(self):
        if not self.img:
            return
        self.update_idletasks()
        cw, ch = max(self.cv.winfo_width(), 400), max(self.cv.winfo_height(), 300)
        self.zoom = min(cw / self.img.width, ch / self.img.height) * 0.98
        self._render()

    def _zoom_at(self, f, e=None):
        if not self.img:
            return
        old = self.zoom
        self.zoom = max(0.1, min(self.zoom * f, 6.0))
        if e is not None:
            cx, cy = self.cv.canvasx(e.x), self.cv.canvasy(e.y)
        self._render()
        if e is not None:
            k = self.zoom / old
            W, H = self.img.width * self.zoom, self.img.height * self.zoom
            self.cv.xview_moveto(max(0, (cx * k - e.x) / W))
            self.cv.yview_moveto(max(0, (cy * k - e.y) / H))

    def _composite(self):
        from PIL import Image
        if self.labels is None or not self.values:
            return self.img
        import numpy as np
        lab = self.labels
        uniq = sorted(set(self.values))
        col = np.zeros((len(self.values) + 1, 3), dtype=np.uint8)
        for k, v in enumerate(self.values, start=1):
            col[k] = PALETTE[uniq.index(v) % len(PALETTE)]
        over = col[lab]
        base = np.asarray(self.img).astype(np.float32)
        m = (lab > 0)[..., None]
        out = np.where(m, base * 0.55 + over.astype(np.float32) * 0.45, base).astype(np.uint8)
        return Image.fromarray(out)

    def _render(self):
        if not self.img:
            return
        from PIL import Image, ImageTk
        im = self._composite()
        w, h = max(1, int(im.width * self.zoom)), max(1, int(im.height * self.zoom))
        im = im.resize((w, h), Image.BILINEAR if self.zoom < 1 else Image.NEAREST)
        self._photo = ImageTk.PhotoImage(im)
        self.cv.delete("all")
        self.cv.create_image(0, 0, image=self._photo, anchor="nw", tags="img")
        self.cv.configure(scrollregion=(0, 0, w, h))
        self._draw_overlay()

    def _draw_overlay(self):
        self.cv.delete("ov")
        z = self.zoom
        for b in self.barriers:
            if len(b) >= 2:
                self.cv.create_line(*[c * z for p in b for c in p], fill="#ff2fd6", width=2, tags="ov")
        for px, py, la, lo, *nm in self.points:
            x, y = px * z, py * z
            self.cv.create_oval(x - 6, y - 6, x + 6, y + 6, outline="#00e5ff", width=2, tags="ov")
            self.cv.create_line(x - 9, y, x + 9, y, fill="#00e5ff", tags="ov")
            self.cv.create_line(x, y - 9, x, y + 9, fill="#00e5ff", tags="ov")
            self.cv.create_text(x + 9, y - 9, text=(nm[0] if nm else ""), fill="#00e5ff",
                                anchor="sw", font=T.FONT_B, tags="ov")
        for px, py, v in self.seeds:
            x, y = px * z, py * z
            self.cv.create_rectangle(x - 4, y - 4, x + 4, y + 4, fill="#facc15", outline="#000", tags="ov")
            self.cv.create_text(x + 7, y, text=f"{v:g}", fill="#facc15", anchor="w", font=T.FONT_B, tags="ov")
        g = self._georef()
        if g and self.site:
            sx, sy = g.to_px(self.site[0], self.site[1])
            x, y = sx * z, sy * z
            self.cv.create_oval(x - 8, y - 8, x + 8, y + 8, fill="#ef4444", outline="white", width=2, tags="ov")
            self.cv.create_text(x + 11, y, text=self.site[2] if len(self.site) > 2 else "건설지점",
                                fill="#fecaca", anchor="w", font=T.FONT_B, tags="ov")
        if self._picked:
            x, y = self._picked[0] * z, self._picked[1] * z
            self.cv.create_oval(x - 5, y - 5, x + 5, y + 5, outline=T.ORANGE, width=3, tags="ov")

    # ── 마우스 ────────────────────────────────────────────
    def _img_xy(self, e):
        return self.cv.canvasx(e.x) / self.zoom, self.cv.canvasy(e.y) / self.zoom

    def _motion(self, e):
        if not self.img:
            return
        x, y = self._img_xy(e)
        g = self._georef()
        if g:
            la, lo = g.to_ll(x, y)
            self.status.config(text=f"픽셀 ({x:.0f}, {y:.0f})   위도 {la:.4f}  경도 {lo:.4f}")
        else:
            self.status.config(text=f"픽셀 ({x:.0f}, {y:.0f})")

    def _press(self, e):
        if not self.img:
            return
        m = self.mode.get()
        if m == "pan":
            self.cv.scan_mark(e.x, e.y)
        elif m == "barrier":
            self._cur_bar = [self._img_xy(e)]
        elif m == "point":
            self._add_point(*self._img_xy(e))
        elif m == "seed":
            self._add_seed(*self._img_xy(e))
        elif m == "read":
            self._read(*self._img_xy(e))

    def _drag(self, e):
        m = self.mode.get()
        if m == "pan":
            self.cv.scan_dragto(e.x, e.y, gain=1)
        elif m == "barrier" and self._cur_bar is not None:
            p = self._img_xy(e)
            last = self._cur_bar[-1]
            if math.hypot(p[0] - last[0], p[1] - last[1]) * self.zoom > 3:
                z = self.zoom
                self.cv.create_line(last[0] * z, last[1] * z, p[0] * z, p[1] * z, fill="#ff2fd6", width=2, tags="ov")
                self._cur_bar.append(p)

    def _release(self, e):
        if self.mode.get() == "barrier" and self._cur_bar:
            if len(self._cur_bar) >= 2:
                self.barriers.append(self._cur_bar)
                self.labels = None
            self._cur_bar = None
            self._draw_overlay()

    # ── 편집 ──────────────────────────────────────────────
    def _add_point(self, x, y):
        dlg = _CityDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        name, la, lo = dlg.result
        self.points.append((x, y, la, lo, name))
        self._refresh_lists()
        self._draw_overlay()

    def _add_seed(self, x, y):
        v = simpledialog.askfloat("구역값", f"이 구역의 값 ({self.info['unit']})", parent=self)
        if v is None:
            return
        self.seeds.append((x, y, v))
        self._refresh_lists()
        self._preview(quiet=True)

    def _del_point(self):
        sel = self.tv_pts.selection()
        if sel:
            idx = sorted((self.tv_pts.index(s) for s in sel), reverse=True)
            for i in idx:
                del self.points[i]
            self._refresh_lists()
            self._draw_overlay()

    def _del_seed(self):
        sel = self.tv_seed.selection()
        if sel:
            for i in sorted((self.tv_seed.index(s) for s in sel), reverse=True):
                del self.seeds[i]
            self._refresh_lists()
            self._preview(quiet=True)

    def _clear_barriers(self):
        self.barriers.clear()
        self._preview(quiet=True)

    def _georef(self):
        if len(self.points) < 3:
            return None
        try:
            return maps.Georef([p[:4] for p in self.points])
        except Exception:                            # noqa: BLE001
            return None

    def _refresh_lists(self):
        self.tv_pts.delete(*self.tv_pts.get_children())
        g = self._georef()
        res = g.residuals() if g else [None] * len(self.points)
        for p, r in zip(self.points, res):
            nm = p[4] if len(p) > 4 else ""
            self.tv_pts.insert("", "end", values=(nm, f"{p[2]:.4f}", f"{p[3]:.4f}",
                                                   "" if r is None else f"{r:.1f}"))
        if g:
            kmp = g.km_per_px()
            rms = math.sqrt(sum(r * r for r in res) / len(res))
            self.lbl_geo.config(text=f"{'2차식' if g.order == 2 else 'affine'} 맞춤 · RMS {rms:.1f}px "
                                     f"(≈{rms * kmp:.1f} km) · 1px ≈ {kmp * 1000:.0f} m",
                                fg=T.C_OK if rms * kmp < 3 else T.C_WARN)
        else:
            self.lbl_geo.config(text=f"기준점 {len(self.points)}/3", fg=T.TX3)
        self.tv_seed.delete(*self.tv_seed.get_children())
        for x, y, v in self.seeds:
            self.tv_seed.insert("", "end", values=(f"{v:g}", f"{x:.0f}", f"{y:.0f}"))

    def _preview(self, quiet=False):
        if not self.img or not self.seeds:
            self.labels = None
            self._render()
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.labels, self.values, leaks = maps.build_labels(self.img, self.seeds, self.barriers,
                                                                tol=self.tol.get())
        finally:
            self.config(cursor="")
        self._render()
        if leaks and not quiet:
            messagebox.showwarning("미리보기", f"{len(leaks)}개 구역이 지도 대부분으로 넘쳤습니다.\n"
                                   "경계선을 그려 막거나 허용오차를 줄이세요.", parent=self)
        elif leaks:
            self.status.config(text=f"⚠ {len(leaks)}개 구역이 넘쳤습니다 — 경계선으로 막으세요")

    def _read(self, x, y):
        self._picked = (x, y)
        g = self._georef()
        txt = []
        val = None
        if self.labels is not None:
            xi, yi = int(x), int(y)
            if 0 <= yi < self.labels.shape[0] and 0 <= xi < self.labels.shape[1]:
                k = int(self.labels[yi, xi])
                if k:
                    val = self.values[k - 1]
        if val is not None:
            txt.append(f"값  {val:g} {self.info['unit']}")
        else:
            txt.append("값  — (미리보기 구역 밖)")
        if g:
            la, lo = g.to_ll(x, y)
            txt.append(f"위도 {la:.4f}  경도 {lo:.4f}")
        self._read_val = val
        self.lbl_read.config(text="\n".join(txt))
        self._draw_overlay()

    def _use_value(self):
        v = getattr(self, "_read_val", None)
        if v is None:
            v = simpledialog.askfloat("값 사용", f"사용할 값 ({self.info['unit']})", parent=self)
        if v is None:
            return
        if self.on_pick:
            self.on_pick(v)
        self.destroy()

    def _save(self):
        g = self._georef()
        if not g:
            messagebox.showwarning("저장", "기준점이 3개 이상 필요합니다.", parent=self)
            return
        if not self.seeds:
            messagebox.showwarning("저장", "구역값을 하나 이상 넣으세요.", parent=self)
            return
        self._preview(quiet=True)
        try:
            grid, uniq, size = maps.labels_to_grid(self.labels, self.values, g)
            maps.MAP_DIR.mkdir(parents=True, exist_ok=True)
            self.img.save(maps.MAP_DIR / f"{self.kind}_src.png")
            calib = {"points": [list(p) for p in self.points], "seeds": [list(s) for s in self.seeds],
                     "barriers": [list(map(list, b)) for b in self.barriers], "tol": self.tol.get(),
                     "source": self.src_path, "page": self.page_no + 1 if self.pdf else None}
            p = maps.save_grid(self.kind, grid, uniq, size, calib)
        except Exception as e:                       # noqa: BLE001
            messagebox.showerror("저장", str(e), parent=self)
            return
        msg = f"저장했습니다.\n{p}\n\n값: {', '.join(f'{v:g}' for v in uniq)} {self.info['unit']}"
        if self.site:
            v, how = maps.lookup(self.kind, self.site[0], self.site[1])
            msg += f"\n\n건설지점 값: {v if v is not None else '—'} ({how})"
        messagebox.showinfo("저장", msg, parent=self)
        if self.on_saved:
            self.on_saved()


class _CityDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("기준점 — 도시 선택")
        self.configure(bg=T.BG2)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        names = [c[0] for c in maps.KNOWN_CITIES] + ["직접 입력"]
        self.v_city = tk.StringVar(value=names[0])
        self.v_lat = tk.StringVar()
        self.v_lon = tk.StringVar()
        f = tk.Frame(self, bg=T.BG2)
        f.pack(padx=16, pady=14)
        T.label(f, "클릭한 지도 표시의 도시").grid(row=0, column=0, sticky="w")
        cb = T.combo(f, self.v_city, names, width=14)
        cb.grid(row=0, column=1, padx=6, pady=3)
        cb.bind("<<ComboboxSelected>>", lambda e: self._fill())
        T.label(f, "위도").grid(row=1, column=0, sticky="w")
        T.entry(f, self.v_lat, 14).grid(row=1, column=1, padx=6, pady=3)
        T.label(f, "경도").grid(row=2, column=0, sticky="w")
        T.entry(f, self.v_lon, 14).grid(row=2, column=1, padx=6, pady=3)
        T.label(f, "시청·군청(◯) 또는 기상관서(●) 위치 기준", fg=T.TX3, font=T.FONT_S).grid(
            row=3, column=0, columnspan=2, sticky="w")
        b = tk.Frame(self, bg=T.BG2)
        b.pack(fill="x", padx=16, pady=(0, 12))
        T.btn(b, "확인", self._ok, bg=T.ACC, fg=T.WHI).pack(side="right")
        T.btn(b, "취소", self.destroy).pack(side="right", padx=6)
        self._fill()
        self.bind("<Return>", lambda e: self._ok())
        self.geometry(f"+{parent.winfo_rootx() + 200}+{parent.winfo_rooty() + 150}")

    def _fill(self):
        for n, la, lo in maps.KNOWN_CITIES:
            if n == self.v_city.get():
                self.v_lat.set(f"{la:.4f}")
                self.v_lon.set(f"{lo:.4f}")

    def _ok(self):
        try:
            la, lo = float(self.v_lat.get()), float(self.v_lon.get())
        except ValueError:
            messagebox.showwarning("기준점", "위도·경도를 숫자로 넣으세요.", parent=self)
            return
        nm = self.v_city.get()
        self.result = ("" if nm == "직접 입력" else nm, la, lo)
        self.destroy()


# ═════════════════════════════════════════════════════════
#  내장 KDS 지도에서 건설지점 위치 확인 (위경도 → 그림 위 핀)
# ═════════════════════════════════════════════════════════
VIEW_KINDS = [("wind", "🌬 기본풍속 (그림 5.5-1)"), ("snow", "❄ 지상설하중 (그림 4.2-1)"),
              ("seismic", "🌐 국가지진위험지도 (그림 3.2-1)")]
VIEW_NOTE = {
    "wind": "등풍속선 사이에 있으면 인근 등풍속선 중 큰 값 (그림 5.5-1 주2). 가장 안쪽 28 m/s 선 안쪽 내륙은 28. "
            "색선은 프로그램이 그림에서 따낸 등풍속선 — 원 그림 선과 맞는지 확인하세요.",
    "snow": "등치선 사이는 큰 값(안전측). 0.5 선 바깥은 최소 지상설하중 0.5 kN/㎡ (4.2.1(3)). "
            "색선은 프로그램이 따낸 등치선(강원 영동 동심원은 근사).",
    "seismic": "값은 %g (S = 값/100 g). 등고선 사이는 직선보간 — 자동 계산값을 같이 표시합니다. "
               "지진구역계수법 S(=Z×2.0)의 80% 이상이어야 합니다 (3.2).",
}


class KdsMapViewer(tk.Toplevel):
    def __init__(self, parent, kind, site, on_pick=None):
        super().__init__(parent)
        self.site = site                     # (lat, lon, 이름)
        self.on_pick = on_pick
        self.kind = tk.StringVar(value=kind)
        self.zoom = 2.0
        self._photo = None
        self._click = None
        self.title("KDS 지도 — 건설지점 위치")
        self.configure(bg=T.BG)
        self.geometry("1220x860")
        self.minsize(900, 600)
        T.setup_style(self)
        self._build()
        self._load()
        self.bind("<Escape>", lambda e: self.destroy())

    def _build(self):
        bar = tk.Frame(self, bg=T.BG2, height=44)
        bar.pack(fill="x")
        for key, txt in VIEW_KINDS:
            tk.Radiobutton(bar, text=txt, variable=self.kind, value=key, indicatoron=False, bg=T.BG3, fg=T.TXT,
                           selectcolor=T.ACC, activebackground=T.BG5, activeforeground=T.WHI, font=T.FONT_B,
                           bd=0, padx=10, pady=4, command=self._load).pack(side="left", padx=(8, 2), pady=7)
        T.btn(bar, "📍 건설지점으로", self._center_pin, bg=T.ORANGE, fg=T.WHI).pack(side="right", padx=10)
        self.v_lines = tk.BooleanVar(value=True)
        T.check(bar, "따낸 등치선 겹쳐 보기", self.v_lines, command=self._render).pack(side="right", padx=8)
        T.btn(bar, "−", lambda: self._zoom(1 / 1.3)).pack(side="right", padx=2)
        T.btn(bar, "맞춤", self._fit).pack(side="right", padx=2)
        T.btn(bar, "+", lambda: self._zoom(1.3)).pack(side="right", padx=2)
        body = tk.Frame(self, bg=T.BG)
        body.pack(fill="both", expand=True)
        right = tk.Frame(body, bg=T.BG2, width=320)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        cf = tk.Frame(body, bg="white")
        cf.pack(side="left", fill="both", expand=True)
        self.cv = tk.Canvas(cf, bg="white", highlightthickness=0, cursor="crosshair")
        sx = ttk.Scrollbar(cf, orient="horizontal", command=self.cv.xview)
        sy = ttk.Scrollbar(cf, orient="vertical", command=self.cv.yview)
        self.cv.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        sy.pack(side="right", fill="y")
        sx.pack(side="bottom", fill="x")
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Button-1>", self._on_click)
        for b in ("<ButtonPress-3>", "<ButtonPress-2>"):
            self.cv.bind(b, lambda e: self.cv.scan_mark(e.x, e.y))
        for b in ("<B3-Motion>", "<B2-Motion>"):
            self.cv.bind(b, lambda e: self.cv.scan_dragto(e.x, e.y, gain=1))
        self.cv.bind("<MouseWheel>", lambda e: self._zoom(1.15 if e.delta > 0 else 1 / 1.15))
        self.cv.bind("<Button-4>", lambda e: self._zoom(1.15))
        self.cv.bind("<Button-5>", lambda e: self._zoom(1 / 1.15))

        self.lbl_title = T.label(right, "", fg=T.WHI, font=T.FONT_H, wraplength=300, justify="left")
        self.lbl_title.pack(anchor="w", padx=12, pady=(12, 2))
        self.lbl_site = T.label(right, "", fg=T.TX2, wraplength=300, justify="left")
        self.lbl_site.pack(anchor="w", padx=12)
        self.lbl_note = T.label(right, "", fg=T.TXT, wraplength=296, justify="left", bg=T.BG3)
        self.lbl_note.pack(fill="x", padx=12, pady=10, ipady=6, ipadx=4)
        T.section(right, "자동 값", T.C_OK)
        self.lbl_auto = T.label(right, "", fg=T.WHI, font=T.FONT_B, wraplength=300, justify="left")
        self.lbl_auto.pack(anchor="w", padx=12)
        T.section(right, "클릭한 곳", T.CYN)
        self.lbl_click = T.label(right, "지도를 클릭하면 위경도와 건설지점까지 거리를 보여줍니다.",
                                 fg=T.TX2, wraplength=300, justify="left")
        self.lbl_click.pack(anchor="w", padx=12)
        T.section(right, "적용할 값", T.ORANGE)
        f = tk.Frame(right, bg=T.BG2)
        f.pack(fill="x", padx=12)
        self.v_val = tk.StringVar()
        T.entry(f, self.v_val, 10).pack(side="left")
        self.lbl_unit = T.label(f, "", fg=T.TX3)
        self.lbl_unit.pack(side="left", padx=6)
        if self.on_pick:
            T.btn(right, "이 값을 프로젝트에 사용", self._use, bg=T.ORANGE, fg=T.WHI).pack(anchor="w", padx=12, pady=8)
        T.label(right, "휠: 확대·축소   오른쪽 드래그: 이동", fg=T.TX3, font=T.FONT_S).pack(side="bottom", anchor="w",
                                                                                     padx=12, pady=8)

    def _load(self):
        from PIL import Image
        k = self.kind.get()
        p = maps.kds_image_path(k)
        if not p or not p.exists():
            messagebox.showerror("KDS 지도", "내장 지도 그림을 찾지 못했습니다 (information/data).", parent=self)
            return
        self.img = Image.open(p).convert("RGB")
        info = maps.KINDS[k]
        self.lbl_title.config(text=info["title"])
        self.lbl_note.config(text=VIEW_NOTE[k])
        self.lbl_unit.config(text=info["unit"])
        la, lo = self.site[0], self.site[1]
        x, y, note = maps.kds_to_px(k, la, lo)
        self.pin = (x, y)
        self.lbl_site.config(text=f"{self.site[2] if len(self.site) > 2 else '건설지점'}\n위도 {la:.5f}, 경도 {lo:.5f}"
                                  + (f"\n{note}" if note else ""))
        r = maps.kds_value(k, la, lo)
        u = info["unit"]
        if r["interp"] is not None:
            if k == "seismic":
                txt = f"직선보간  {r['interp']:.2f} {u}\n올림(위 등고선)  {r['max']:g} {u}"
            else:
                txt = f"선형보간  {r['interp']:.2f} {u}\n인근 큰 값  {r['max']:g} {u}  ← 설계 적용"
            self.lbl_auto.config(text=txt + f"\n{r['src']}", fg=T.WHI)
            v = r["design"]
        else:
            v = None
            self.lbl_auto.config(text=(r["note"] or "자동 값 없음") + "\n핀 위치의 등치선을 읽어 아래에 입력하세요",
                                 fg=T.C_WARN)
        self.v_val.set("" if v is None else (f"{v:.2f}" if k == "seismic" else f"{v:g}"))
        self._click = None
        self.zoom = 3.0
        self._render()
        self.after(50, self._center_pin)

    def _render(self):
        from PIL import Image, ImageTk
        w, h = int(self.img.width * self.zoom), int(self.img.height * self.zoom)
        im = self.img.resize((w, h), Image.LANCZOS if self.zoom < 1 else Image.BICUBIC)
        self._photo = ImageTk.PhotoImage(im)
        self.cv.delete("all")
        self.cv.create_image(0, 0, image=self._photo, anchor="nw")
        self.cv.configure(scrollregion=(0, 0, w, h))
        z = self.zoom
        x, y = self.pin[0] * z, self.pin[1] * z
        self.cv.create_line(x, 0, x, h, fill="#ef4444", dash=(4, 4))
        self.cv.create_line(0, y, w, y, fill="#ef4444", dash=(4, 4))
        r = max(5, 3 * z)
        self.cv.create_oval(x - r, y - r, x + r, y + r, outline="#dc2626", width=3)
        self.cv.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill="#dc2626", outline="")
        self.cv.create_text(x + r + 4, y - r - 2, text=self.site[2] if len(self.site) > 2 else "건설지점",
                            fill="#b91c1c", anchor="sw", font=T.FONT_B)
        if self.v_lines.get() and self.kind.get() in ("wind", "snow"):
            pal = ["#e11d48", "#16a34a", "#2563eb", "#c026d3", "#0891b2", "#ea580c", "#854d0e", "#7c3aed",
                   "#db2777", "#0d9488"]
            for val, pts in maps.kds_contours(self.kind.get()):
                if len(pts) < 2:
                    continue
                c = pal[int(round(val * (1 if self.kind.get() == "wind" else 4))) % len(pal)]
                flat = [q * z for pt in pts for q in pt]
                self.cv.create_line(*flat, fill=c, width=2 if z >= 2 else 1, smooth=False)
                mx, my = pts[len(pts) // 2]
                self.cv.create_text(mx * z + 4, my * z, text=f"{val:g}", fill=c, anchor="w", font=T.FONT_S)
        if self._click:
            cx, cy = self._click[0] * z, self._click[1] * z
            self.cv.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, outline="#2563eb", width=2)

    def _fit(self):
        self.update_idletasks()
        cw, ch = max(self.cv.winfo_width(), 300), max(self.cv.winfo_height(), 300)
        self.zoom = min(cw / self.img.width, ch / self.img.height) * 0.98
        self._render()

    def _zoom(self, f):
        self.zoom = max(0.5, min(self.zoom * f, 10.0))
        self._render()
        self._center_pin()

    def _center_pin(self):
        self.update_idletasks()
        w, h = self.img.width * self.zoom, self.img.height * self.zoom
        cw, ch = self.cv.winfo_width(), self.cv.winfo_height()
        x, y = self.pin[0] * self.zoom, self.pin[1] * self.zoom
        self.cv.xview_moveto(max(0.0, (x - cw / 2) / w))
        self.cv.yview_moveto(max(0.0, (y - ch / 2) / h))

    def _on_click(self, e):
        x, y = self.cv.canvasx(e.x) / self.zoom, self.cv.canvasy(e.y) / self.zoom
        self._click = (x, y)
        la, lo = maps.kds_to_ll(self.kind.get(), x, y)
        from . import geo
        d = geo.haversine(self.site[0], self.site[1], la, lo)
        txt = f"위도 {la:.4f}, 경도 {lo:.4f}\n건설지점에서 {d / 1000:.1f} km"
        r = maps.kds_value(self.kind.get(), la, lo)
        if r["interp"] is not None:
            u = maps.KINDS[self.kind.get()]["unit"]
            txt += f"\n선형보간 {r['interp']:.2f} {u} · 큰 값 {r['max']:g} {u}"
        self.lbl_click.config(text=txt, fg=T.TXT)
        self._render()

    def _use(self):
        try:
            v = float(self.v_val.get())
        except ValueError:
            messagebox.showwarning("값", "적용할 값을 숫자로 넣으세요.", parent=self)
            return
        self.on_pick(self.kind.get(), v)
        self.destroy()
