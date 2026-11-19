"""
information/app.py — Information (건물정보 분석) 메인 창

건물 주소·시설물 종류·규모를 넣으면
  · 풍하중 : 기본풍속 V0(지도), 지표면조도, 지형계수 Kzt(DEM 지형단면), 설계풍속·속도압
  · 지진하중: 지진구역·S, 국토지반정보 시추공 반경검색 → 지반분류, Fa·Fv·SDS·SD1·내진설계범주
  · 설하중 : 기본지상설하중 Sg(지도) → 지붕설하중
"""
import json
import math
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import boreholes as BH
from . import geo
from . import kds_data as K
from . import maps
from . import report
from . import seismic as SE
from . import snow as SN
from . import theme as T
from . import wind as W

APP_TITLE = "StrCAD - Information"
FILE_EXT = ".stinfo"

SITE_COLORS = {"S1": "#64748b", "S2": "#22c55e", "S3": "#eab308", "S4": "#38bdf8", "S5": "#ef4444", "": "#94a3b8"}


def _num(v, default=None):
    try:
        s = str(v).strip().replace(",", "")
        return float(s) if s != "" else default
    except (ValueError, TypeError):
        return default


class InformationApp(tk.Toplevel):
    def __init__(self, parent, username=""):
        super().__init__(parent)
        self.username = username
        self.settings = geo.load_settings()
        self.db = BH.BoreholeDB(self.settings.get("db_path") or None)
        self.res = {}
        self.file_path = ""
        self.bh_results = []
        self._busy = False
        self._q = queue.Queue()                  # 작업 스레드 → 화면 갱신
        self.title(APP_TITLE + (f"  ─  {username}" if username else ""))
        self.configure(bg=T.BG)
        self.geometry("1440x900")
        self.minsize(1180, 700)
        T.setup_style(self)
        try:
            from cad_analysis import theme as _TH
            _TH.set_icon(self)
        except Exception:                            # noqa: BLE001
            pass
        self._vars()
        self._build()
        self._refresh_db_label()
        self._update_map_status()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(100, self._poll)

    def ui(self, fn):
        """화면 갱신 함수를 메인 스레드에서 실행 (작업 스레드에서 불러도 안전)."""
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            self._q.put(fn)

    def _poll(self):
        try:
            while True:
                fn = self._q.get_nowait()
                try:
                    fn()
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(80, self._poll)

    # ═════════════════════════════════════════════════════
    #  입력 변수
    # ═════════════════════════════════════════════════════
    def _vars(self):
        S = tk.StringVar
        self.v = {
            "project": S(value=""), "address": S(value=""), "lat": S(value=""), "lon": S(value=""),
            "sido": S(value=""), "sigungu": S(value=""),
            "facility": S(value=K.FACILITY_TYPES[0][0]), "importance": S(value=K.FACILITY_TYPES[0][1]),
            "floors": S(value="20"), "height": S(value="60"), "B": S(value="30"), "D": S(value="20"),
            "roughness": S(value="B"), "kd": S(value="1.0"),
            "kzt_mode": S(value="auto"), "kzt_manual": S(value="1.0"),
            "v0_mode": S(value="map"), "v0_manual": S(value=""),
            "s_mode": S(value="zone"), "s_map_manual": S(value=""),
            "radius": S(value=str(self.settings.get("radius_m", 500))),
            "amp_mode": S(value=self.settings.get("amp_mode", "max")),
            "site_override": S(value="자동(시추)"),
            "sg_mode": S(value="map"), "sg_manual": S(value=""),
            "highland": tk.BooleanVar(value=False), "ce": S(value="C"), "heat": S(value="난방"),
            "roof_slope": S(value="0"), "slippery": tk.BooleanVar(value=False), "roof_w": S(value=""),
        }

    def _inputs(self):
        g = {k: (v.get() if not isinstance(v, tk.BooleanVar) else bool(v.get())) for k, v in self.v.items()}
        for k in ("lat", "lon", "height", "B", "D", "kd", "kzt_manual", "v0_manual", "s_map_manual",
                  "radius", "sg_manual", "roof_slope", "roof_w"):
            g[k] = _num(g[k])
        g["floors"] = int(_num(g["floors"], 0) or 0)
        return g

    # ═════════════════════════════════════════════════════
    #  화면
    # ═════════════════════════════════════════════════════
    def _build(self):
        hdr = tk.Frame(self, bg=T.BG2, height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🏢  Information", font=("Malgun Gothic", 14, "bold"), bg=T.BG2, fg=T.WHI).pack(
            side="left", padx=(16, 6))
        tk.Label(hdr, text="건물정보 분석 — 풍하중 · 지진하중 · 설하중", font=T.FONT, bg=T.BG2, fg=T.TX3).pack(side="left")
        self.btn_run = T.btn(hdr, "▶  분석 실행", self._run, bg=T.ORANGE, fg=T.WHI, font=T.FONT_B, padx=16, pady=6)
        self.btn_run.pack(side="right", padx=(6, 14), pady=10)
        for txt, cmd in (("⚙ 설정", self._settings_dialog), ("📊 엑셀", self._save_xlsx),
                         ("📝 보고서", self._save_txt), ("💾 저장", self._save), ("📂 열기", self._open),
                         ("🆕 새로", self._new)):
            T.btn(hdr, txt, cmd).pack(side="right", padx=3)
        tk.Frame(self, bg=T.BDR, height=1).pack(fill="x")

        self.status = tk.StringVar(value="주소와 건물 개요를 입력하고 [분석 실행]을 누르세요.")
        sbar = tk.Frame(self, bg=T.BG2, height=26)
        sbar.pack(fill="x", side="bottom")
        tk.Label(sbar, textvariable=self.status, font=T.FONT_S, bg=T.BG2, fg=T.TX2, anchor="w").pack(
            side="left", fill="x", expand=True, padx=10)
        self.prog = ttk.Progressbar(sbar, style="Info.Horizontal.TProgressbar", length=220, mode="determinate")
        self.prog.pack(side="right", padx=10, pady=4)

        body = tk.Frame(self, bg=T.BG)
        body.pack(fill="both", expand=True)
        left = T.ScrollFrame(body, width=340)
        left.pack(side="left", fill="y")
        tk.Frame(body, bg=T.BDR, width=1).pack(side="left", fill="y")
        self._build_inputs(left.inner)

        self.nb = ttk.Notebook(body)
        self.nb.pack(side="left", fill="both", expand=True)
        self.tab_sum = tk.Frame(self.nb, bg=T.BG2)
        self.tab_wind = tk.Frame(self.nb, bg=T.BG2)
        self.tab_seis = tk.Frame(self.nb, bg=T.BG2)
        self.tab_bh = tk.Frame(self.nb, bg=T.BG2)
        self.tab_snow = tk.Frame(self.nb, bg=T.BG2)
        self.tab_log = tk.Frame(self.nb, bg=T.BG2)
        for f, t in ((self.tab_sum, "  요약  "), (self.tab_wind, "  🌬 풍하중  "), (self.tab_seis, "  🌐 지진하중  "),
                     (self.tab_bh, "  🕳 시추조사  "), (self.tab_snow, "  ❄ 설하중  "), (self.tab_log, "  로그  ")):
            self.nb.add(f, text=t)
        self._build_summary()
        self._build_wind_tab()
        self._build_seis_tab()
        self._build_bh_tab()
        self._build_snow_tab()
        self._build_log_tab()

    # ── 입력 패널 ──
    def _row(self, parent, label, widget, unit="", r=None):
        f = tk.Frame(parent, bg=T.BG2)
        f.pack(fill="x", padx=12, pady=2)
        tk.Label(f, text=label, width=11, anchor="w", font=T.FONT, bg=T.BG2, fg=T.TX2).pack(side="left")
        w = widget(f)
        w.pack(side="left", fill="x", expand=True)
        if unit:
            tk.Label(f, text=unit, font=T.FONT_S, bg=T.BG2, fg=T.TX3, width=5, anchor="w").pack(side="left", padx=(4, 0))
        return w

    def _build_inputs(self, p):
        v = self.v
        T.section(p, "건물 위치", T.C_GEO)
        self._row(p, "프로젝트명", lambda f: T.entry(f, v["project"]))
        self._row(p, "주소", lambda f: T.entry(f, v["address"]))
        bf = tk.Frame(p, bg=T.BG2)
        bf.pack(fill="x", padx=12, pady=(2, 4))
        T.btn(bf, "🔍 좌표 찾기", self._geocode, bg=T.ACC, fg=T.WHI).pack(side="left")
        T.btn(bf, "📋 좌표 붙여넣기", self._paste_coords).pack(side="left", padx=4)
        self._row(p, "위도", lambda f: T.entry(f, v["lat"]), "°N")
        self._row(p, "경도", lambda f: T.entry(f, v["lon"]), "°E")
        self._row(p, "시·도", lambda f: T.entry(f, v["sido"]))
        self._row(p, "시·군·구", lambda f: T.entry(f, v["sigungu"]))
        self.lbl_loc = T.label(p, "", fg=T.TX3, font=T.FONT_S, wraplength=300, justify="left")
        self.lbl_loc.pack(anchor="w", padx=12)

        T.section(p, "건물 개요", T.CYN)
        cb = self._row(p, "시설물 종류", lambda f: T.combo(f, v["facility"], [x[0] for x in K.FACILITY_TYPES], width=26))
        cb.bind("<<ComboboxSelected>>", lambda e: self._facility_changed())
        cb2 = self._row(p, "중요도", lambda f: T.combo(f, v["importance"], list(K.IMPORTANCE), width=6))
        cb2.bind("<<ComboboxSelected>>", lambda e: self._importance_changed())
        self.lbl_imp = T.label(p, "", fg=T.TX3, font=T.FONT_S, wraplength=300, justify="left")
        self.lbl_imp.pack(anchor="w", padx=12)
        self._row(p, "지상층수", lambda f: T.entry(f, v["floors"]), "층")
        self._row(p, "건물높이 H", lambda f: T.entry(f, v["height"]), "m")
        self._row(p, "폭 B", lambda f: T.entry(f, v["B"]), "m")
        self._row(p, "깊이 D", lambda f: T.entry(f, v["D"]), "m")

        T.section(p, "풍하중 조건", T.C_WIND)
        rb = tk.Frame(p, bg=T.BG2)
        rb.pack(fill="x", padx=12)
        tk.Label(rb, text="기본풍속", width=11, anchor="w", font=T.FONT, bg=T.BG2, fg=T.TX2).pack(side="left")
        for val, txt in (("map", "지도"), ("manual", "직접")):
            tk.Radiobutton(rb, text=txt, variable=v["v0_mode"], value=val, bg=T.BG2, fg=T.TXT, selectcolor=T.BG4,
                           activebackground=T.BG2, font=T.FONT).pack(side="left")
        T.entry(rb, v["v0_manual"], 6).pack(side="left", padx=4)
        tk.Label(rb, text="m/s", font=T.FONT_S, bg=T.BG2, fg=T.TX3).pack(side="left")
        T.btn(rb, "🗺", lambda: self.open_kds_map("wind"), padx=4).pack(side="left", padx=(4, 0))
        self.lbl_map_wind = T.label(p, "", fg=T.TX3, font=T.FONT_S)
        self.lbl_map_wind.pack(anchor="w", padx=12)
        cr = self._row(p, "지표면조도", lambda f: T.combo(f, v["roughness"], list("ABCD"), width=6))
        cr.bind("<<ComboboxSelected>>", lambda e: self._rough_changed())
        self.lbl_rough = T.label(p, "", fg=T.TX3, font=T.FONT_S, wraplength=300, justify="left")
        self.lbl_rough.pack(anchor="w", padx=12)
        self._row(p, "풍향계수 Kd", lambda f: T.entry(f, v["kd"]))
        rb = tk.Frame(p, bg=T.BG2)
        rb.pack(fill="x", padx=12, pady=2)
        tk.Label(rb, text="지형계수", width=11, anchor="w", font=T.FONT, bg=T.BG2, fg=T.TX2).pack(side="left")
        for val, txt in (("auto", "자동(DEM)"), ("flat", "평탄"), ("manual", "직접")):
            tk.Radiobutton(rb, text=txt, variable=v["kzt_mode"], value=val, bg=T.BG2, fg=T.TXT, selectcolor=T.BG4,
                           activebackground=T.BG2, font=T.FONT).pack(side="left")
        T.entry(rb, v["kzt_manual"], 5).pack(side="left", padx=2)

        T.section(p, "지진 조건", T.C_SEIS)
        rb = tk.Frame(p, bg=T.BG2)
        rb.pack(fill="x", padx=12)
        tk.Label(rb, text="S 산정", width=11, anchor="w", font=T.FONT, bg=T.BG2, fg=T.TX2).pack(side="left")
        for val, txt in (("zone", "지진구역계수"), ("map", "위험지도")):
            tk.Radiobutton(rb, text=txt, variable=v["s_mode"], value=val, bg=T.BG2, fg=T.TXT, selectcolor=T.BG4,
                           activebackground=T.BG2, font=T.FONT).pack(side="left")
        rs = tk.Frame(p, bg=T.BG2)
        rs.pack(fill="x", padx=12, pady=2)
        tk.Label(rs, text="위험지도 S", width=11, anchor="w", font=T.FONT, bg=T.BG2, fg=T.TX2).pack(side="left")
        T.entry(rs, v["s_map_manual"], 8).pack(side="left")
        tk.Label(rs, text="%g", font=T.FONT_S, bg=T.BG2, fg=T.TX3).pack(side="left", padx=4)
        T.btn(rs, "🗺", lambda: self.open_kds_map("seismic"), padx=4).pack(side="left", padx=(4, 0))
        T.label(p, "  (비우면 내장 지도에서 자동 — 등고선 사이 보간)", fg=T.TX3, font=T.FONT_S).pack(anchor="w", padx=12)
        self.lbl_map_seis = T.label(p, "", fg=T.TX3, font=T.FONT_S)
        self.lbl_map_seis.pack(anchor="w", padx=12)
        self._row(p, "시추 반경", lambda f: T.entry(f, v["radius"]), "m")
        self._row(p, "대표증폭계수", lambda f: T.combo(f, v["amp_mode"], ["max", "mean"], width=8))
        T.label(p, "  max = 설계상 가장 불리한 값, mean = 평균 (4.2.3 ①)", fg=T.TX3, font=T.FONT_S).pack(anchor="w", padx=12)
        self._row(p, "지반분류", lambda f: T.combo(f, v["site_override"], ["자동(시추)", "S1", "S2", "S3", "S4", "S5"], width=10))

        T.section(p, "설하중 조건", T.C_SNOW)
        rb = tk.Frame(p, bg=T.BG2)
        rb.pack(fill="x", padx=12)
        tk.Label(rb, text="지상설하중", width=11, anchor="w", font=T.FONT, bg=T.BG2, fg=T.TX2).pack(side="left")
        for val, txt in (("map", "지도"), ("manual", "직접")):
            tk.Radiobutton(rb, text=txt, variable=v["sg_mode"], value=val, bg=T.BG2, fg=T.TXT, selectcolor=T.BG4,
                           activebackground=T.BG2, font=T.FONT).pack(side="left")
        T.entry(rb, v["sg_manual"], 6).pack(side="left", padx=4)
        tk.Label(rb, text="kN/㎡", font=T.FONT_S, bg=T.BG2, fg=T.TX3).pack(side="left")
        T.btn(rb, "🗺", lambda: self.open_kds_map("snow"), padx=4).pack(side="left", padx=(4, 0))
        self.lbl_map_snow = T.label(p, "", fg=T.TX3, font=T.FONT_S)
        self.lbl_map_snow.pack(anchor="w", padx=12)
        T.check(p, "고지대·산간 (그림값 ×1.5, 4.2.1)", v["highland"]).pack(anchor="w", padx=12)
        self._row(p, "노출 Ce", lambda f: T.combo(f, v["ce"], list(K.SNOW_CE.keys()), width=6))
        self._row(p, "난방", lambda f: T.combo(f, v["heat"], list(K.SNOW_CT.keys()), width=8))
        self._row(p, "지붕경사", lambda f: T.entry(f, v["roof_slope"]), "°")
        T.check(p, "미끄러운 지붕면", v["slippery"]).pack(anchor="w", padx=12)
        self._row(p, "처마~용마루 W", lambda f: T.entry(f, v["roof_w"]), "m")
        tk.Frame(p, bg=T.BG2, height=20).pack()
        self._facility_changed(set_imp=False)
        self._rough_changed()

    def _facility_changed(self, set_imp=True):
        for nm, imp, cond in K.FACILITY_TYPES:
            if nm == self.v["facility"].get():
                if set_imp:
                    self.v["importance"].set(imp)
                break
        self._importance_changed()

    def _importance_changed(self):
        imp = self.v["importance"].get()
        g, ie = SE.seismic_grade(imp)
        self.lbl_imp.config(text=f"중요도({imp}): {K.IMPORTANCE_DESC.get(imp, '')}\n"
                                 f"→ Iw {K.IW.get(imp)}, Is {K.SNOW_IS.get(imp)}, 내진등급 {g}, IE {ie}")

    def _rough_changed(self):
        self.lbl_rough.config(text=K.ROUGHNESS_DESC.get(self.v["roughness"].get(), ""))

    def _update_map_status(self):
        for kind, lbl in (("wind", self.lbl_map_wind), ("snow", self.lbl_map_snow), ("seismic", self.lbl_map_seis)):
            mi = maps.map_info(kind)
            if mi and mi.get("builtin"):
                lbl.config(text="  내장 지도로 자동 조회 · 🗺 위치 확인", fg=T.C_OK)
            elif mi:
                lbl.config(text=f"  보정한 지도로 자동 조회 ({mi['created']}) · 🗺 위치 확인", fg=T.C_OK)
            else:
                lbl.config(text="  🗺 버튼 → 지도 위 건설지점 핀을 보고 값 입력", fg=T.C_WARN)

    def open_kds_map(self, kind):
        """내장 KDS 지도에 건설지점 핀 — 값을 읽어 바로 입력."""
        inp = self._inputs()
        if inp["lat"] is None or inp["lon"] is None:
            if inp["address"] and (self.settings.get("vworld_key") or self.settings.get("kakao_key")):
                self._geocode()
                inp = self._inputs()
            if inp["lat"] is None or inp["lon"] is None:
                messagebox.showinfo("KDS 지도", "먼저 위도·경도를 넣거나 [좌표 찾기]를 하세요.", parent=self)
                return
        if not maps.kds_meta(kind):
            messagebox.showerror("KDS 지도", "내장 지도 데이터(information/data)를 찾지 못했습니다.", parent=self)
            return

        def pick(k, val):
            if k == "wind":
                self.v["v0_manual"].set(f"{val:g}")
                self.v["v0_mode"].set("manual")
            elif k == "snow":
                self.v["sg_manual"].set(f"{val:g}")
                self.v["sg_mode"].set("manual")
            else:
                self.v["s_map_manual"].set(f"{val:g}")
                self.v["s_mode"].set("map")
            self.log(f"[지도] {maps.KINDS[k]['title']} → {val:g} {maps.KINDS[k]['unit']} 입력")
        from .map_tool import KdsMapViewer
        KdsMapViewer(self, kind, (inp["lat"], inp["lon"], inp.get("project") or "건설지점"), on_pick=pick)

    # ── 요약 탭 ──
    def _build_summary(self):
        p = self.tab_sum
        top = tk.Frame(p, bg=T.BG2)
        top.pack(fill="x", padx=14, pady=(14, 6))
        self.sum_title = tk.Label(top, text="분석 전", font=T.FONT_H, bg=T.BG2, fg=T.WHI, anchor="w")
        self.sum_title.pack(fill="x")
        self.sum_sub = tk.Label(top, text="", font=T.FONT_S, bg=T.BG2, fg=T.TX3, anchor="w", justify="left")
        self.sum_sub.pack(fill="x")
        cards = tk.Frame(p, bg=T.BG2)
        cards.pack(fill="x", padx=10)
        self.cards = {}
        for key, title, color in (("wind", "🌬 풍하중", T.C_WIND), ("seis", "🌐 지진하중", T.C_SEIS),
                                  ("snow", "❄ 설하중", T.C_SNOW)):
            c = tk.Frame(cards, bg=T.BG3, highlightbackground=T.BDR, highlightthickness=1)
            c.pack(side="left", fill="both", expand=True, padx=6, pady=6)
            tk.Frame(c, bg=color, height=3).pack(fill="x")
            tk.Label(c, text=title, font=T.FONT_B, bg=T.BG3, fg=color, anchor="w").pack(fill="x", padx=12, pady=(8, 2))
            big = tk.Label(c, text="—", font=T.FONT_BIG, bg=T.BG3, fg=T.WHI, anchor="w")
            big.pack(fill="x", padx=12)
            body = tk.Label(c, text="", font=T.FONT_M, bg=T.BG3, fg=T.TXT, anchor="nw", justify="left")
            body.pack(fill="both", expand=True, padx=12, pady=(4, 12))
            self.cards[key] = (big, body)
        T.section(p, "확인할 점", T.C_WARN)
        self.sum_notes = tk.Text(p, height=12, bg=T.BG3, fg=T.TXT, font=T.FONT, relief="flat", wrap="word",
                                 padx=10, pady=8)
        self.sum_notes.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    # ── 풍하중 탭 ──
    def _build_wind_tab(self):
        p = self.tab_wind
        up = tk.Frame(p, bg=T.BG2)
        up.pack(fill="x", padx=10, pady=8)
        lf = tk.Frame(up, bg=T.BG2)
        lf.pack(side="left", fill="y")
        T.section(lf, "설계풍속 · 속도압", T.C_WIND)
        fr, self.tv_wpar = T.tree(lf, ("항목", "값", "근거"), (150, 110, 230), height=9)
        fr.pack(fill="both")
        rf = tk.Frame(up, bg=T.BG2)
        rf.pack(side="left", fill="both", expand=True, padx=(12, 0))
        T.section(rf, "풍향별 지형계수 (클릭하면 단면 표시)", T.C_WIND)
        fr, self.tv_kzt = T.tree(rf, ("풍향", "지형", "H", "Lu", "x", "θ′", "Kh", "L", "Kzt", "비고"),
                                 (60, 60, 55, 55, 60, 50, 50, 50, 55, 200), height=9)
        fr.pack(fill="both", expand=True)
        self.tv_kzt.bind("<<TreeviewSelect>>", lambda e: self._draw_profile())
        dn = tk.Frame(p, bg=T.BG2)
        dn.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        cf = tk.Frame(dn, bg=T.BG2)
        cf.pack(side="left", fill="both", expand=True)
        T.section(cf, "지형 단면", T.C_GEO)
        self.cv_prof = tk.Canvas(cf, bg=T.CANV_BG, highlightthickness=0, height=260)
        self.cv_prof.pack(fill="both", expand=True)
        self.cv_prof.bind("<Configure>", lambda e: self._draw_profile())
        qf = tk.Frame(dn, bg=T.BG2, width=420)
        qf.pack(side="left", fill="both", padx=(12, 0))
        T.section(qf, "높이별 속도압", T.C_WIND)
        fr, self.tv_q = T.tree(qf, ("z (m)", "Kzr", "Kzt", "Vz (m/s)", "qz (N/㎡)"), (60, 60, 60, 80, 90), height=12)
        fr.pack(fill="both", expand=True)

    # ── 지진하중 탭 ──
    def _build_seis_tab(self):
        p = self.tab_seis
        lf = tk.Frame(p, bg=T.BG2, width=520)
        lf.pack(side="left", fill="y", padx=10, pady=8)
        T.section(lf, "지진하중 변수", T.C_SEIS)
        fr, self.tv_spar = T.tree(lf, ("항목", "값", "근거"), (150, 100, 260), height=18)
        fr.pack(fill="both", expand=True)
        rf = tk.Frame(p, bg=T.BG2)
        rf.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=8)
        T.section(rf, "설계응답스펙트럼 (KDS 41 17 00 그림 4.2-1)", T.C_SEIS)
        self.cv_spec = tk.Canvas(rf, bg=T.CANV_BG, highlightthickness=0)
        self.cv_spec.pack(fill="both", expand=True)
        self.cv_spec.bind("<Configure>", lambda e: self._draw_spectrum())

    # ── 시추조사 탭 ──
    def _build_bh_tab(self):
        p = self.tab_bh
        bar = tk.Frame(p, bg=T.BG2)
        bar.pack(fill="x", padx=10, pady=(8, 4))
        self.lbl_db = T.label(bar, "", fg=T.TX2)
        self.lbl_db.pack(side="left")
        T.btn(bar, "🔎 반경 검색", self._search_boreholes, bg=T.ACC, fg=T.WHI).pack(side="right", padx=3)
        T.btn(bar, "🗑 선택 공 삭제", self._delete_hole).pack(side="right", padx=3)
        T.btn(bar, "✏ 시추공 직접 입력", self._manual_hole).pack(side="right", padx=3)
        T.btn(bar, "📥 시추자료 CSV 가져오기", self._import_csv, bg=T.BG5, fg=T.WHI).pack(side="right", padx=3)
        mid = tk.Frame(p, bg=T.BG2)
        mid.pack(fill="both", expand=True, padx=10)
        rf = tk.Frame(mid, bg=T.BG2, width=520)
        rf.pack(side="right", fill="y", padx=(10, 0))
        rf.pack_propagate(False)
        lf = tk.Frame(mid, bg=T.BG2)
        lf.pack(side="left", fill="both", expand=True)
        fr, self.tv_bh = T.tree(lf, ("사용", "시추공", "사업명", "거리m", "심도m", "기반암m", "Vs,soil", "지반", "판정"),
                                (40, 90, 170, 60, 60, 65, 65, 45, 240), height=14)
        fr.pack(fill="both", expand=True)
        self.tv_bh.bind("<<TreeviewSelect>>", lambda e: self._draw_hole())
        self.tv_bh.bind("<Double-1>", self._toggle_hole)
        T.label(lf, "더블클릭: 판정에서 제외/포함", fg=T.TX3, font=T.FONT_S).pack(anchor="w")
        self.bh_sum = tk.Label(lf, text="", font=T.FONT, bg=T.BG3, fg=T.WHI, justify="left", anchor="w")
        self.bh_sum.pack(fill="x", pady=(4, 8), ipady=6, ipadx=8)
        T.section(rf, "위치 (건설지점 기준)", T.C_GEO)
        self.cv_bhmap = tk.Canvas(rf, bg=T.CANV_BG, highlightthickness=0, height=270)
        self.cv_bhmap.pack(fill="x")
        self.cv_bhmap.bind("<Configure>", lambda e: self._draw_bhmap())
        self.cv_bhmap.bind("<Button-1>", self._bhmap_click)
        T.section(rf, "주상도 · N값 · Vs", T.C_GEO)
        self.cv_log = tk.Canvas(rf, bg=T.CANV_BG, highlightthickness=0)
        self.cv_log.pack(fill="both", expand=True, pady=(0, 8))
        self.cv_log.bind("<Configure>", lambda e: self._draw_hole())

    # ── 설하중 탭 ──
    def _build_snow_tab(self):
        p = self.tab_snow
        T.section(p, "지붕설하중 (KDS 41 12 00:2022 4)", T.C_SNOW)
        fr, self.tv_snow = T.tree(p, ("항목", "값", "근거"), (200, 120, 420), height=16)
        fr.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_log_tab(self):
        self.txt_log = tk.Text(self.tab_log, bg=T.BG3, fg=T.TXT, font=T.FONT_M, relief="flat", padx=8, pady=6)
        self.txt_log.pack(fill="both", expand=True, padx=10, pady=10)

    def log(self, msg):
        def _do():
            self.txt_log.insert("end", msg + "\n")
            self.txt_log.see("end")
        self.ui(_do)

    def set_status(self, msg, pct=None):
        def _do():
            self.status.set(msg)
            if pct is not None:
                self.prog["value"] = pct
        self.ui(_do)

    # ═════════════════════════════════════════════════════
    #  위치
    # ═════════════════════════════════════════════════════
    def _geocode(self):
        addr = self.v["address"].get().strip()
        if not addr:
            messagebox.showinfo("좌표 찾기", "주소를 입력하세요.", parent=self)
            return
        self.config(cursor="watch")
        self.update()
        try:
            r = geo.geocode(addr, self.settings)
        except geo.GeoError as e:
            messagebox.showwarning("좌표 찾기", str(e), parent=self)
            return
        finally:
            self.config(cursor="")
        self._apply_geocode(r)

    def _apply_geocode(self, r):
        self.v["lat"].set(f"{r['lat']:.6f}")
        self.v["lon"].set(f"{r['lon']:.6f}")
        if r.get("sido"):
            self.v["sido"].set(r["sido"])
        if r.get("sigungu"):
            self.v["sigungu"].set(r["sigungu"])
        self.lbl_loc.config(text=f"{r.get('address', '')}  ({r.get('provider', '')})")
        self.log(f"[좌표] {r.get('address')} → {r['lat']:.6f}, {r['lon']:.6f} ({r.get('provider')})")

    def _paste_coords(self):
        try:
            txt = self.clipboard_get()
        except tk.TclError:
            txt = ""
        import re
        nums = [float(x) for x in re.findall(r"-?\d+\.\d+", txt)]
        if len(nums) >= 2:
            a, b = nums[0], nums[1]
            lat, lon = (a, b) if 30 < a < 45 else (b, a)
            self.v["lat"].set(f"{lat:.6f}")
            self.v["lon"].set(f"{lon:.6f}")
            self.lbl_loc.config(text="클립보드 좌표 사용 (지도 앱에서 복사한 '위도, 경도')")
        else:
            messagebox.showinfo("좌표 붙여넣기", "클립보드에서 '위도, 경도' 숫자를 찾지 못했습니다.\n"
                                "예: 37.566535, 126.977969", parent=self)

    # ═════════════════════════════════════════════════════
    #  분석 실행
    # ═════════════════════════════════════════════════════
    def _run(self):
        if self._busy:
            return
        inp = self._inputs()
        if not inp["height"] or inp["height"] <= 0:
            messagebox.showwarning("분석", "건물높이 H 를 입력하세요.", parent=self)
            return
        self._busy = True
        self.btn_run.config(state="disabled", text="  분석 중…  ")
        self.txt_log.delete("1.0", "end")
        threading.Thread(target=self._worker, args=(inp,), daemon=True).start()

    def _worker(self, inp):
        res = {"inputs": inp}
        try:
            self._do_location(inp, res)
            self._do_wind(inp, res)
            self._do_seismic(inp, res)
            self._do_snow(inp, res)
            self.set_status("분석 완료", 100)
        except Exception as e:                       # noqa: BLE001
            import traceback
            self.log(traceback.format_exc())
            self.set_status(f"오류: {e}", 0)
        self.ui(lambda: self._finish(inp, res))

    def _finish(self, inp, res):
        self._busy = False
        self.btn_run.config(state="normal", text="▶  분석 실행")
        self.res = res
        if res.get("geo"):
            self._apply_geocode(res["geo"])
            inp["lat"], inp["lon"] = res["geo"]["lat"], res["geo"]["lon"]
        for k in ("sido", "sigungu"):
            if res.get(k) and not self.v[k].get():
                self.v[k].set(res[k])
        self._show_all()

    def _do_location(self, inp, res):
        if (inp["lat"] is None or inp["lon"] is None) and inp["address"]:
            self.set_status("주소 → 좌표 변환 중…", 3)
            try:
                g = geo.geocode(inp["address"], self.settings)
                res["geo"] = g
                inp["lat"], inp["lon"] = g["lat"], g["lon"]
                inp["sido"] = inp["sido"] or g.get("sido", "")
                inp["sigungu"] = inp["sigungu"] or g.get("sigungu", "")
            except geo.GeoError as e:
                self.log(f"[좌표] {e}")
        if inp["lat"] is not None and inp["lon"] is not None and not inp["sido"]:
            rg = geo.reverse_geocode(inp["lat"], inp["lon"], self.settings) if (
                self.settings.get("vworld_key") or self.settings.get("kakao_key")) else None
            if rg:
                inp["sido"], inp["sigungu"] = rg.get("sido", ""), rg.get("sigungu", "")
                res["sido"], res["sigungu"] = inp["sido"], inp["sigungu"]
                if not inp["address"]:
                    inp["address"] = rg.get("address", "")

    # ── 풍하중 ──
    def _do_wind(self, inp, res):
        out = {"ok": False}
        res["wind"] = out
        v0, src = None, ""
        if inp["v0_mode"] == "manual" and inp["v0_manual"]:
            v0, src = inp["v0_manual"], "직접 입력"
        if v0 is None and inp["lat"] is not None:
            val, how = maps.lookup("wind", inp["lat"], inp["lon"])
            if val is not None:
                v0, src = float(val), f"그림 5.5-1 지도 ({how})"
            else:
                src = how
        if v0 is None and inp["lat"] is not None:
            val, how = maps.kds_inset_value("wind", inp["lat"], inp["lon"])
            if val is not None:
                v0, src = float(val), "그림 5.5-1 " + how
        if v0 is None and inp["v0_manual"]:
            v0, src = inp["v0_manual"], "직접 입력 (지도 조회 불가)"
        if v0 is None:
            out["msg"] = "기본풍속 V0 가 없습니다 — 기본풍속 옆 🗺 버튼으로 그림 5.5-1 위 건설지점 핀을 보고 값을 넣으세요."
            self.log("[풍하중] " + out["msg"])
            return
        cat = inp["roughness"]
        H = inp["height"]
        kzt, kzt_src, terrain = 1.0, "평탄지", None
        if inp["kzt_mode"] == "manual":
            kzt, kzt_src = inp["kzt_manual"] or 1.0, "직접 입력"
        elif inp["kzt_mode"] == "auto":
            if inp["lat"] is None:
                kzt_src = "좌표 없음 — 평탄지로 계산"
            else:
                self.set_status("지형 표고(DEM) 조회 중…", 10)
                try:
                    s = self.settings

                    def prog(d, n):
                        self.set_status(f"지형 표고 조회 {d}/{n}", 10 + 40 * d / max(n, 1))
                    terrain = W.analyze_terrain(inp["lat"], inp["lon"], H, cat, geo.elevations,
                                                ndir=int(s.get("terrain_dirs", 16)), up=float(s.get("terrain_up", 3000)),
                                                down=float(s.get("terrain_down", 2000)),
                                                step=float(s.get("terrain_step", 30)), progress=prog)
                    kzt = terrain["Kzt"]
                    g = terrain["governing"]
                    kzt_src = f"DEM 지형단면 {len(terrain['directions'])}풍향 중 최대 ({g.get('dir_ko', '')})"
                    res["site_elev"] = g.get("site_elev")
                except Exception as e:               # noqa: BLE001
                    kzt_src = f"표고 조회 실패 → 평탄지로 계산 ({e})"
                    self.log("[지형] " + kzt_src)
        d = W.design_wind(v0, cat, H, inp["importance"], kzt, inp["kd"] or 1.0, inp["floors"])

        def kzt_at(z):
            if not terrain or inp["kzt_mode"] != "auto":
                return kzt
            best = 1.0
            for r in terrain["directions"]:
                if r.get("kind") in ("hill", "escarpment") and r.get("H"):
                    best = max(best, W.kzt_from_params(r["kind"], r["H"], r["Lu"], r["x"], z, cat,
                                                       r.get("theta_d"))["Kzt"])
            return best
        prof = W.pressure_profile(v0, cat, H, inp["importance"], kzt_at, inp["kd"] or 1.0, inp["floors"])
        out.update(ok=True, design=d, v0_src=src, kzt_src=kzt_src, terrain=terrain, profile=prof)
        self.log(f"[풍하중] V0={v0} ({src}), Kzt={kzt:.3f} ({kzt_src}), VH={d['VH']:.2f} m/s, qH={d['qH']:.0f} N/㎡")

    # ── 지진 ──
    def _do_seismic(self, inp, res):
        out = {}
        res["seismic"] = out
        addr = " ".join(x for x in (inp["sido"], inp["sigungu"], inp["address"]) if x)
        zone, ztxt = SE.seismic_zone(addr, SE.parse_sido(inp["sido"]) if inp["sido"] else "", inp["sigungu"])
        out["zone"], out["zone_txt"] = zone, ztxt
        s_map = None
        if True:                                     # 위험지도 값은 방식과 관계없이 참고로 조회
            if inp["s_map_manual"]:
                s_map = inp["s_map_manual"] / 100.0
                out["s_map_src"] = "직접 입력"
            elif inp["lat"] is not None:
                val, how = maps.lookup("seismic", inp["lat"], inp["lon"])
                if val is not None:
                    s_map = float(val) / 100.0
                    out["s_map_src"] = f"그림 3.2-1 ({how})"
                else:
                    out["s_map_src"] = how
        # 시추조사
        S_for_amp = SE.effective_s(zone, s_map, inp["s_mode"] == "map").get("S") or 0.22
        bh = {"radius": inp["radius"] or 500, "holes": [], "n_total": 0}
        if inp["lat"] is not None:
            self.set_status("시추공 반경 검색 중…", 60)
            try:
                hs = self.db.search(inp["lat"], inp["lon"], bh["radius"])
                rs = []
                for k, h in enumerate(hs):
                    L, S = self.db.detail(h["code"])
                    rs.append(BH.analyze_hole(h, L, S, self.settings))
                    if k % 20 == 0:
                        self.set_status(f"시추공 분석 {k + 1}/{len(hs)}", 60 + 25 * (k + 1) / max(len(hs), 1))
                sm = BH.summarize(rs, S_for_amp, inp["amp_mode"])
                bh.update(holes=rs, n_total=len(rs), summary=sm)
                self.log(f"[시추] 반경 {bh['radius']:.0f}m: {len(rs)}공 — " + sm.get("text", "").replace("\n", " / "))
            except Exception as e:                   # noqa: BLE001
                self.log(f"[시추] 검색 실패: {e}")
        out["boreholes"] = bh
        sm = bh.get("summary") or {}
        amp = None
        if inp["site_override"] != "자동(시추)":
            site, site_src = inp["site_override"], "직접 지정"
        elif sm.get("n_ok"):
            site = sm["predicted"]
            site_src = f"시추 {sm['n_ok']}공 판정 ({'가장 불리' if inp['amp_mode'] == 'max' else '최다'})"
            amp = (sm["Fa"], sm["Fv"], "대표 증폭계수 " + sm.get("label", ""))
        else:
            site, site_src = "S4", "시추자료 없음 — 4.1.1 ③ (S5 가능성 없으면 S4) 가정"
        out["site"], out["site_src"] = site, site_src
        rep = None
        if amp is None and sm.get("n_ok"):
            rep = next((r for r in bh["holes"] if r.get("site") == site), None)
        e = SE.evaluate(zone, inp["importance"], site, s_map, inp["s_mode"] == "map",
                        rock_depth=(rep or {}).get("rock_depth"), vs_soil=(rep or {}).get("vs_soil"),
                        rock_found=(rep or {}).get("rock_found", True), amp=amp)
        out["eval"] = e
        if not e.get("ok"):
            out["msg"] = "지진구역을 정하지 못했습니다 — 시·도/시·군·구를 확인하세요" if not zone else "계산 실패"
        else:
            sp = e["spectrum"]
            self.log(f"[지진] {ztxt}, S={e['s']['S']:.3f}, {site}, SDS={sp['SDS']:.3f}, SD1={sp['SD1']:.3f}, 범주 {e['SDC']}")

    # ── 설하중 ──
    def _do_snow(self, inp, res):
        out = {"ok": False}
        res["snow"] = out
        sg_map, src = None, ""
        if inp["sg_mode"] == "manual" and inp["sg_manual"]:
            sg_map, src = inp["sg_manual"], "직접 입력"
        if sg_map is None and inp["lat"] is not None:
            val, how = maps.lookup("snow", inp["lat"], inp["lon"])
            if val is not None:
                sg_map, src = float(val), f"그림 4.2-1 지도 ({how})"
            else:
                src = how
        if sg_map is None and inp["lat"] is not None:
            val, how = maps.kds_inset_value("snow", inp["lat"], inp["lon"])
            if val is not None:
                sg_map, src = float(val), "그림 4.2-1 " + how
        if sg_map is None and inp["sg_manual"]:
            sg_map, src = inp["sg_manual"], "직접 입력 (지도 조회 불가)"
        if sg_map is None:
            out["msg"] = "기본지상설하중 Sg 가 없습니다 — 지상설하중 옆 🗺 버튼으로 그림 4.2-1 위 건설지점 핀을 보고 값을 넣으세요."
            self.log("[설하중] " + out["msg"])
            return
        sg, notes = SN.ground_snow(sg_map, inp["highland"])
        ce = K.SNOW_CE[inp["ce"]][0]
        ct = K.SNOW_CT[inp["heat"]]
        roof = SN.roof_snow(sg, ce, ct, inp["importance"], inp["roof_slope"] or 0.0, inp["slippery"], inp["roof_w"])
        out.update(ok=True, roof=roof, sg_src=src, sg_notes=notes, sg_map=sg_map)
        self.log(f"[설하중] Sg={sg:.2f} ({src}), Sf={roof['Sf']:.3f}, 설계 {roof['design']:.3f} kN/㎡")

    # ═════════════════════════════════════════════════════
    #  결과 표시
    # ═════════════════════════════════════════════════════
    def _show_all(self):
        inp = self.res.get("inputs", {})
        self.sum_title.config(text=f"{inp.get('project') or '건물정보 분석'}  —  {inp.get('address') or ''}")
        la, lo = inp.get("lat"), inp.get("lon")
        self.sum_sub.config(text=(f"위도 {la:.6f}, 경도 {lo:.6f}" if la is not None else "좌표 없음")
                            + f"   ·   {inp.get('facility')}  중요도({inp.get('importance')})"
                            + f"   ·   지상 {inp.get('floors')}층, H={inp.get('height')} m")
        self._show_wind()
        self._show_seismic()
        self._show_boreholes()
        self._show_snow()
        self._show_notes()

    def _fill(self, tv, rows):
        tv.delete(*tv.get_children())
        for r in rows:
            tv.insert("", "end", values=r)

    def _show_wind(self):
        w = self.res.get("wind") or {}
        big, body = self.cards["wind"]
        if not w.get("ok"):
            big.config(text="—")
            body.config(text=w.get("msg", ""), fg=T.C_WARN)
            self._fill(self.tv_wpar, [])
            self._fill(self.tv_kzt, [])
            self._fill(self.tv_q, [])
            self._draw_profile()
            return
        d = w["design"]
        big.config(text=f"qH = {d['qH'] / 1000:.3f} kN/㎡")
        body.config(fg=T.TXT, text=f"V0  = {d['V0']:.1f} m/s\nKzr = {d['Kzr']:.3f}  ({self.res['inputs']['roughness']})\n"
                                   f"Kzt = {d['Kzt']:.3f}\nIw  = {d['Iw']:.2f}\nVH  = {d['VH']:.2f} m/s")
        inp = self.res["inputs"]
        rows = [("기본풍속 V0", f"{d['V0']:.1f} m/s", w["v0_src"]),
                ("풍향계수 Kd", f"{d['Kd']:.2f}", "5.5.3 (관측자료 없음/외장재 1.0)"),
                ("지표면조도", inp["roughness"], K.ROUGHNESS_DESC[inp["roughness"]][:30]),
                ("풍속고도분포계수 Kzr", f"{d['Kzr']:.3f}", f"표 5.5-2, z = H = {inp['height']} m"),
                ("지형계수 Kzt", f"{d['Kzt']:.3f}", w["kzt_src"]),
                ("중요도계수 Iw", f"{d['Iw']:.2f}", "표 5.5-5" + (" 초고층" if d["supertall"] else f" 중요도({inp['importance']})")),
                ("설계풍속 VH", f"{d['VH']:.2f} m/s", "식 (5.5-2)"),
                ("설계속도압 qH", f"{d['qH']:.1f} N/㎡", "식 (5.5-1) ½ρV², ρ=1.225"),
                ("난류강도 IH", f"{d['IH']:.3f}", "식 (5.5-3.a)")]
        self._fill(self.tv_wpar, rows)
        self.tv_kzt.delete(*self.tv_kzt.get_children())
        ter = w.get("terrain") or {}
        gov = ter.get("governing")
        for i, r in enumerate(ter.get("directions", [])):
            kind = {"hill": "언덕·산", "escarpment": "경사지"}.get(r.get("kind"), "평탄")
            f = lambda k, fmt="{:.0f}": "" if r.get(k) is None else fmt.format(r[k])  # noqa: E731
            iid = self.tv_kzt.insert("", "end", iid=str(i), values=(
                r.get("dir_ko"), kind, f("H", "{:.1f}"), f("Lu"), f("x", "{:+.0f}"), f("theta_p", "{:.3f}"),
                f("Kh", "{:.2f}"), f("L", "{:.3f}"), f"{r['Kzt']:.3f}", r.get("note", "")))
            if r is gov:
                self.tv_kzt.selection_set(iid)
        self._fill(self.tv_q, [(f"{r['z']:.1f}", f"{r['Kzr']:.3f}", f"{r['Kzt']:.3f}", f"{r['Vz']:.2f}",
                                f"{r['qz']:.1f}") for r in w["profile"]])
        self._draw_profile()

    def _show_seismic(self):
        s = self.res.get("seismic") or {}
        e = s.get("eval") or {}
        big, body = self.cards["seis"]
        si = e.get("s") or {}
        rows = [("지진구역", s.get("zone") or "—", s.get("zone_txt", "")),
                ("지진구역계수 Z", "—" if si.get("Z") is None else f"{si['Z']:.2f} g", "KDS 17 10 00 표 4.2-2"),
                ("S (Z × 2.0)", "—" if si.get("S_zone") is None else f"{si['S_zone']:.3f} g", "2400년 위험도계수 2.0"),
                ("위험지도 S", "—" if si.get("S_map") is None else f"{si['S_map']:.3f} g", s.get("s_map_src", "")),
                ("위험지도 하한 (80%)", "—" if si.get("S_min") is None else f"{si['S_min']:.3f} g", "3.2(1)"),
                ("적용 S", "—" if si.get("S") is None else f"{si['S']:.3f} g", si.get("note") or
                 ("지진구역계수법" if si.get("method") == "zone" else "")),
                ("지반분류", s.get("site", "—"), s.get("site_src", ""))]
        if e.get("ok"):
            sp = e["spectrum"]
            rows += [("Fa", f"{e['Fa']:.3f}", "; ".join(e.get("amp_notes") or []) or "표 4.2-1"),
                     ("Fv", f"{e['Fv']:.3f}", "표 4.2-2"),
                     ("SDS", f"{sp['SDS']:.3f} g", "S×2.5×Fa×2/3 (4.2-4)"),
                     ("SD1", f"{sp['SD1']:.3f} g", "S×Fv×2/3 (4.2-5)"),
                     ("T0 / Ts", f"{sp['T0']:.3f} / {sp['Ts']:.3f} s", "0.2·SD1/SDS, SD1/SDS"),
                     ("TL", f"{sp['TL']:.1f} s", "장주기 천이주기"),
                     ("내진등급 / IE", f"{e['grade']} / {e['IE']:.1f}", "표 2.2-1"),
                     ("내진설계범주", e["SDC"], f"SDS→{e['SDC_SDS']}, SD1→{e['SDC_SD1']} (표 5.2-1·5.2-2)")]
            big.config(text=f"SDS {sp['SDS']:.3f} · SD1 {sp['SD1']:.3f}")
            body.config(fg=T.TXT, text=f"S   = {si['S']:.3f} g ({s.get('zone')}구역)\n지반 = {s.get('site')}\n"
                                       f"Fa  = {e['Fa']:.3f}, Fv = {e['Fv']:.3f}\n등급 {e['grade']}, IE {e['IE']:.1f}\n"
                                       f"내진설계범주 {e['SDC']}")
        else:
            big.config(text="—")
            body.config(fg=T.C_WARN, text=s.get("msg", ""))
        self._fill(self.tv_spar, rows)
        self._draw_spectrum()

    def _show_boreholes(self):
        bh = (self.res.get("seismic") or {}).get("boreholes") or {}
        self.bh_results = bh.get("holes", [])
        self._fill_bh_tree()
        sm = bh.get("summary") or {}
        self.bh_sum.config(text=(f"반경 {bh.get('radius', 0):.0f} m 검색 결과\n" + sm.get("text", "")) if bh else
                           "분석을 실행하거나 [반경 검색]을 누르세요.")
        self._draw_bhmap()
        self._draw_hole()

    def _fill_bh_tree(self):
        self.tv_bh.delete(*self.tv_bh.get_children())
        for i, r in enumerate(self.bh_results):
            h = r["hole"]
            self.tv_bh.insert("", "end", iid=str(i), values=(
                "✔" if r.get("use", True) else "✖", h["code"], (h.get("name") or h.get("project") or "")[:30],
                f"{h['dist']:.0f}", f"{r['depth']:.1f}",
                "" if r.get("rock_depth") is None else f"{r['rock_depth']:.1f}",
                "" if r.get("vs_soil") is None else f"{r['vs_soil']:.0f}", r.get("site", ""), r.get("reason", "")))

    def _show_snow(self):
        n = self.res.get("snow") or {}
        big, body = self.cards["snow"]
        if not n.get("ok"):
            big.config(text="—")
            body.config(fg=T.C_WARN, text=n.get("msg", ""))
            self._fill(self.tv_snow, [])
            return
        r = n["roof"]
        inp = self.res["inputs"]
        big.config(text=f"S = {r['design']:.3f} kN/㎡")
        body.config(fg=T.TXT, text=f"Sg = {r['Sg']:.2f} kN/㎡\nSf = {r['Sf']:.3f}\nCs = {r['Cs']:.3f}, Ss = {r['Ss']:.3f}\n"
                                   f"{r['governing']}")
        rows = [("그림값", f"{n['sg_map']:.2f} kN/㎡", n["sg_src"]),
                ("기본지상설하중 Sg", f"{r['Sg']:.2f} kN/㎡", "; ".join(n["sg_notes"]) or "4.2"),
                ("기본지붕설하중계수 Cb", f"{r['Cb']:.1f}", "4.3.1"),
                ("노출계수 Ce", f"{r['Ce']:.1f}", f"표 4.3-1 {inp['ce']}: {K.SNOW_CE[inp['ce']][1]}"),
                ("온도계수 Ct", f"{r['Ct']:.1f}", f"표 4.3-2 {inp['heat']}"),
                ("중요도계수 Is", f"{r['Is']:.1f}", f"표 4.3-3 중요도({inp['importance']})"),
                ("평지붕설하중 Sf", f"{r['Sf']:.3f} kN/㎡", "Cb·Ce·Ct·Is·Sg (4.3-1)"),
                ("지붕경사도계수 Cs", f"{r['Cs']:.3f}", f"그림 4.4-1, 경사 {inp['roof_slope'] or 0}°"),
                ("경사지붕설하중 Ss", f"{r['Ss']:.3f} kN/㎡", "Cs·Sf (4.4-1)")]
        if r["rain"]:
            rows.append(("눈 위의 비", f"{r['rain']:.2f} kN/㎡", "4.7.1"))
        if r["S_min"] is not None:
            rows.append(("완경사지붕 최소설하중", f"{r['S_min']:.3f} kN/㎡", "4.3.5 (경사 15° 이하)"))
        rows.append(("설계 지붕설하중", f"{r['design']:.3f} kN/㎡", r["governing"]))
        rows.append(("지붕활하중과 비교", "설하중 지배" if r["vs_roof_live"] else "지붕활하중 1.0 이하",
                     "4.1(1) 설하중이 지붕 최소활하중보다 클 때 적용"))
        self._fill(self.tv_snow, rows)

    def _show_notes(self):
        t = self.sum_notes
        t.delete("1.0", "end")
        lines = []
        w = self.res.get("wind") or {}
        if not w.get("ok"):
            lines.append("• 풍하중: " + w.get("msg", "").replace("\n", " "))
        elif w["design"]["V0"] and "직접" not in w.get("v0_src", ""):
            lines.append(f"• 기본풍속은 보정한 지도에서 읽은 값입니다 — {w['v0_src']}. 원 지도와 한 번 대조하세요.")
        if w.get("design") and w["design"]["Kzt"] > 1.0:
            lines.append("• 지형계수가 1보다 큽니다. DEM(90m)으로 산정한 값이므로 현장 지형·인접 지형을 확인하세요.")
        s = self.res.get("seismic") or {}
        if "가정" in s.get("site_src", ""):
            lines.append("• 반경 안에 시추자료가 없어 지반을 S4로 가정했습니다. 시추자료 CSV 를 가져오거나 반경을 넓히세요.")
        sm = ((s.get("boreholes") or {}).get("summary") or {})
        if sm.get("counts") and len(sm["counts"]) > 1:
            lines.append("• 시추공마다 지반분류가 다릅니다 — 대표지반증폭계수 적용 방법(평균/불리)을 검토하세요 (4.2.3 ①).")
        if s.get("zone") == "" or s.get("zone") is None:
            lines.append("• 지진구역을 정하지 못했습니다 — 시·도/시·군·구를 입력하세요.")
        n = self.res.get("snow") or {}
        if not n.get("ok"):
            lines.append("• 설하중: " + n.get("msg", "").replace("\n", " "))
        lines.append("")
        lines.append("원문 대조가 필요한 가정")
        for v in K.VERIFY.values():
            lines.append("  – " + v)
        t.insert("1.0", "\n".join(lines))

    # ═════════════════════════════════════════════════════
    #  그림
    # ═════════════════════════════════════════════════════
    def _draw_profile(self):
        cv = self.cv_prof
        cv.delete("all")
        w = self.res.get("wind") or {}
        dirs = (w.get("terrain") or {}).get("directions") or []
        W_, H_ = cv.winfo_width(), cv.winfo_height()
        if not dirs or W_ < 50:
            cv.create_text(W_ / 2, H_ / 2, text="지형계수 자동(DEM) 분석 결과가 여기에 표시됩니다", fill=T.TX3, font=T.FONT)
            return
        sel = self.tv_kzt.selection()
        r = dirs[int(sel[0])] if sel else (w["terrain"].get("governing") or dirs[0])
        prof = r.get("profile") or []
        if len(prof) < 2:
            return
        xs = [p[0] for p in prof]
        es = [p[1] for p in prof]
        x0, x1 = min(xs), max(xs)
        e0, e1 = min(es), max(es)
        if e1 - e0 < 10:
            e1 = e0 + 10
        pad_l, pad_r, pad_t, pad_b = 54, 16, 22, 30
        sx = lambda x: pad_l + (x - x0) / (x1 - x0) * (W_ - pad_l - pad_r)  # noqa: E731
        sy = lambda e: H_ - pad_b - (e - e0) / (e1 - e0) * (H_ - pad_t - pad_b)  # noqa: E731
        for k in range(5):
            e = e0 + (e1 - e0) * k / 4
            cv.create_line(pad_l, sy(e), W_ - pad_r, sy(e), fill="#162036")
            cv.create_text(pad_l - 6, sy(e), text=f"{e:.0f}", fill=T.TX3, anchor="e", font=T.FONT_S)
        pts = [c for p in prof for c in (sx(p[0]), sy(p[1]))]
        cv.create_polygon([sx(x0), H_ - pad_b] + pts + [sx(x1), H_ - pad_b], fill="#1e293b", outline="")
        cv.create_line(*pts, fill="#a3e635", width=2)
        cv.create_line(sx(0), pad_t, sx(0), H_ - pad_b, fill=T.ORANGE, dash=(4, 3))
        cv.create_text(sx(0), pad_t - 8, text="건설지점", fill=T.ORANGE, font=T.FONT_S)
        if r.get("crest_s") is not None and r.get("kind") != "flat":
            cx, ce = r["crest_s"], r["crest_elev"]
            cv.create_oval(sx(cx) - 4, sy(ce) - 4, sx(cx) + 4, sy(ce) + 4, fill="#f87171", outline="")
            cv.create_text(sx(cx), sy(ce) - 10, text=f"정점 H={r['H']:.0f}m", fill="#fca5a5", font=T.FONT_S)
            if r.get("Lu"):
                ylu = sy(ce - r["H"] / 2)
                cv.create_line(sx(cx - r["Lu"]), ylu, sx(cx), ylu, fill="#fbbf24", arrow="both")
                cv.create_text(sx(cx - r["Lu"] / 2), ylu - 8, text=f"Lu={r['Lu']:.0f}m", fill="#fbbf24", font=T.FONT_S)
        cv.create_text(pad_l, H_ - 10, text=f"← 풍상측 (바람이 {r.get('dir_ko', '')}쪽에서)", fill=T.TX2, anchor="w", font=T.FONT_S)
        cv.create_text(W_ - pad_r, H_ - 10, text="풍하측 →", fill=T.TX2, anchor="e", font=T.FONT_S)
        cv.create_text(W_ - pad_r, pad_t - 8, text=f"Kzt = {r['Kzt']:.3f}", fill=T.WHI, anchor="e", font=T.FONT_B)

    def _draw_spectrum(self):
        cv = self.cv_spec
        cv.delete("all")
        e = (self.res.get("seismic") or {}).get("eval") or {}
        W_, H_ = cv.winfo_width(), cv.winfo_height()
        if not e.get("ok") or W_ < 50:
            cv.create_text(W_ / 2, H_ / 2, text="분석 후 설계응답스펙트럼이 표시됩니다", fill=T.TX3, font=T.FONT)
            return
        sp = e["spectrum"]
        tmax = 6.0
        smax = max(sp["SDS"] * 1.15, 0.1)
        pl, pr, pt, pb = 56, 20, 24, 40
        sx = lambda t: pl + t / tmax * (W_ - pl - pr)  # noqa: E731
        sy = lambda s: H_ - pb - s / smax * (H_ - pt - pb)  # noqa: E731
        for k in range(7):
            cv.create_line(sx(k), pt, sx(k), H_ - pb, fill="#162036")
            cv.create_text(sx(k), H_ - pb + 12, text=str(k), fill=T.TX3, font=T.FONT_S)
        for k in range(6):
            s = smax * k / 5
            cv.create_line(pl, sy(s), W_ - pr, sy(s), fill="#162036")
            cv.create_text(pl - 6, sy(s), text=f"{s:.2f}", fill=T.TX3, anchor="e", font=T.FONT_S)
        pts = []
        n = 400
        for i in range(n + 1):
            t = tmax * i / n
            pts += [sx(t), sy(SE.sa_at(t, sp))]
        cv.create_line(*pts, fill=T.C_SEIS, width=2)
        for k, (t, lab) in enumerate(((sp["T0"], "T0"), (sp["Ts"], "Ts"), (sp["TL"], "TL"))):
            cv.create_line(sx(t), sy(0), sx(t), sy(SE.sa_at(t, sp)), fill=T.TX3, dash=(3, 3))
            cv.create_text(sx(t) + (0 if k != 0 else -2), sy(SE.sa_at(t, sp)) - 10 - (12 if k == 0 else 0),
                           text=f"{lab}={t:.2f}s", fill=T.TX2, font=T.FONT_S, anchor="e" if k == 0 else "w")
        cv.create_text(sx(sp["Ts"]) + 6, sy(sp["SDS"]) - 10, text=f"SDS = {sp['SDS']:.3f} g", fill=T.WHI, anchor="w",
                       font=T.FONT_B)
        cv.create_text(sx(1.0) + 6, sy(sp["SD1"]), text=f"SD1 = {sp['SD1']:.3f} g (T=1s)", fill=T.WHI, anchor="w",
                       font=T.FONT_S)
        cv.create_text(pl, pt - 12, text="Sa (g)", fill=T.TX2, anchor="w", font=T.FONT_S)
        cv.create_text(W_ - pr, H_ - pb + 12, text="T (s)", fill=T.TX2, anchor="e", font=T.FONT_S)

    def _draw_bhmap(self):
        cv = self.cv_bhmap
        cv.delete("all")
        W_, H_ = cv.winfo_width(), cv.winfo_height()
        inp = self.res.get("inputs") or self._inputs()
        lat0, lon0 = inp.get("lat"), inp.get("lon")
        rad = ((self.res.get("seismic") or {}).get("boreholes") or {}).get("radius") or _num(self.v["radius"].get(), 500)
        if lat0 is None or W_ < 50:
            cv.create_text(W_ / 2, H_ / 2, text="좌표를 넣고 검색하세요", fill=T.TX3, font=T.FONT)
            return
        cx, cy = W_ / 2, H_ / 2
        sc = (min(W_, H_) / 2 - 18) / max(rad, 1)
        self._bhmap_sc = (cx, cy, sc, lat0, lon0)
        cv.create_oval(cx - rad * sc, cy - rad * sc, cx + rad * sc, cy + rad * sc, outline=T.BDR2, dash=(4, 3))
        for f in (0.5,):
            cv.create_oval(cx - rad * sc * f, cy - rad * sc * f, cx + rad * sc * f, cy + rad * sc * f,
                           outline="#1e2b47", dash=(2, 4))
        cv.create_text(cx + rad * sc * 0.71 + 4, cy - rad * sc * 0.71, text=f"{rad:.0f} m", fill=T.TX3,
                       anchor="sw", font=T.FONT_S)
        cv.create_text(W_ - 12, 12, text="N ↑", fill=T.TX2, anchor="ne", font=T.FONT_B)
        sel = self.tv_bh.selection()
        for i, r in enumerate(self.bh_results):
            h = r["hole"]
            x, y = geo.local_xy(lat0, lon0, h["lat"], h["lon"])
            px, py = cx + x * sc, cy - y * sc
            col = SITE_COLORS.get(r.get("site", ""), "#94a3b8") if r.get("use", True) else "#334155"
            rr = 7 if (sel and sel[0] == str(i)) else 5
            cv.create_oval(px - rr, py - rr, px + rr, py + rr, fill=col, outline="white" if rr == 7 else "")
        cv.create_line(cx - 9, cy, cx + 9, cy, fill=T.ORANGE, width=2)
        cv.create_line(cx, cy - 9, cx, cy + 9, fill=T.ORANGE, width=2)
        y = 10
        for k in ("S1", "S2", "S3", "S4", "S5", ""):
            cv.create_oval(10, y, 20, y + 10, fill=SITE_COLORS[k], outline="")
            cv.create_text(24, y + 5, text=k or "판정불가", fill=T.TX2, anchor="w", font=T.FONT_S)
            y += 15

    def _bhmap_click(self, e):
        if not getattr(self, "_bhmap_sc", None) or not self.bh_results:
            return
        cx, cy, sc, lat0, lon0 = self._bhmap_sc
        best, bd = None, 12
        for i, r in enumerate(self.bh_results):
            x, y = geo.local_xy(lat0, lon0, r["hole"]["lat"], r["hole"]["lon"])
            d = math.hypot(cx + x * sc - e.x, cy - y * sc - e.y)
            if d < bd:
                best, bd = i, d
        if best is not None:
            self.tv_bh.selection_set(str(best))
            self.tv_bh.see(str(best))

    def _draw_hole(self):
        cv = self.cv_log
        cv.delete("all")
        W_, H_ = cv.winfo_width(), cv.winfo_height()
        sel = self.tv_bh.selection()
        self._draw_bhmap()
        if not sel or W_ < 50:
            cv.create_text(W_ / 2, H_ / 2, text="시추공을 선택하면 주상도가 표시됩니다", fill=T.TX3, font=T.FONT)
            return
        r = self.bh_results[int(sel[0])]
        L = r["layers"]
        depth = max(r["depth"], 5.0)
        pt, pb = 24, 14
        sy = lambda z: pt + z / depth * (H_ - pt - pb)  # noqa: E731
        xL, xR = 60, 170
        cv.create_text(10, 10, text=f"{r['hole']['code']}  {r['hole'].get('name') or ''}", fill=T.WHI, anchor="w",
                       font=T.FONT_B)
        step = 5 if depth <= 40 else 10
        z = 0
        while z <= depth + 1e-6:
            cv.create_line(xL - 6, sy(z), W_ - 10, sy(z), fill="#162036")
            cv.create_text(xL - 8, sy(z), text=f"{z:.0f}", fill=T.TX3, anchor="e", font=T.FONT_S)
            z += step
        for q in L:
            col = K.LAYER_COLORS.get(q["cls"], "#334155")
            cv.create_rectangle(xL, sy(q["top"]), xR, sy(q["bot"]), fill=col, outline="#0f172a")
            if sy(q["bot"]) - sy(q["top"]) > 11:
                nm = q["name"] or K.LAYER_LABEL.get(q["cls"], "")
                cv.create_text((xL + xR) / 2, (sy(q["top"]) + sy(q["bot"])) / 2, text=nm[:10], fill="white",
                               font=T.FONT_S)
                cv.create_text(xR + 6, (sy(q["top"]) + sy(q["bot"])) / 2, text=f"Vs {q['vs']:.0f}",
                               fill=T.TX2, anchor="w", font=T.FONT_S)
        if r.get("rock_depth") is not None:
            y = sy(r["rock_depth"])
            cv.create_line(xL - 10, y, W_ - 10, y, fill="#f87171", width=2, dash=(6, 3))
            cv.create_text(W_ - 12, y - 7, text=f"기반암 {r['rock_depth']:.1f} m", fill="#fca5a5", anchor="e", font=T.FONT_S)
        nx0, nx1 = xR + 70, W_ - 16
        if nx1 - nx0 > 60:
            cv.create_text(nx0, pt - 10, text="N값 0", fill=T.TX3, anchor="w", font=T.FONT_S)
            cv.create_text(nx1, pt - 10, text="50+", fill=T.TX3, anchor="e", font=T.FONT_S)
            pts = []
            for s in r["spts"]:
                if s.get("n") is None:
                    continue
                x = nx0 + min(s["n"], 50) / 50 * (nx1 - nx0)
                pts.append((x, sy(s["depth"])))
                cv.create_oval(x - 3, sy(s["depth"]) - 3, x + 3, sy(s["depth"]) + 3, fill="#38bdf8", outline="")
            if len(pts) > 1:
                cv.create_line(*[c for p in pts for c in p], fill="#38bdf8")
        txt = f"{r.get('site') or '판정불가'} — {r.get('reason', '')}"
        if r.get("vs_soil"):
            txt += f"   (Vs,soil 평균 깊이 {r.get('vs_depth', 0):.1f} m)"
        cv.create_text(10, H_ - 4, text=txt, fill=SITE_COLORS.get(r.get("site", ""), T.TX2), anchor="sw", font=T.FONT_B)

    # ═════════════════════════════════════════════════════
    #  시추자료
    # ═════════════════════════════════════════════════════
    def _refresh_db_label(self):
        try:
            st = self.db.stats()
            self.lbl_db.config(text=f"시추 DB: 시추공 {st['holes']:,} (좌표 {st['located']:,}) · 지층 {st['with_layers']:,}공 · "
                                    f"N값 {st['with_spt']:,}공   [{self.db.path.name}]")
        except Exception as e:                       # noqa: BLE001
            self.lbl_db.config(text=f"시추 DB 오류: {e}")

    def _search_boreholes(self):
        inp = self._inputs()
        if inp["lat"] is None:
            messagebox.showinfo("시추공 검색", "먼저 좌표를 넣으세요.", parent=self)
            return
        if not self.res:
            self.res = {"inputs": inp}
        self.res["inputs"] = inp
        res = self.res
        try:
            self._do_seismic(inp, res)
        except Exception as e:                       # noqa: BLE001
            messagebox.showerror("시추공 검색", str(e), parent=self)
            return
        self._show_seismic()
        self._show_boreholes()
        self.nb.select(self.tab_bh)

    def _toggle_hole(self, e):
        sel = self.tv_bh.selection()
        if not sel:
            return
        r = self.bh_results[int(sel[0])]
        r["use"] = not r.get("use", True)
        inp = self.res.get("inputs") or self._inputs()
        bh = (self.res.get("seismic") or {}).get("boreholes")
        if bh is not None:
            e_ = (self.res["seismic"].get("eval") or {}).get("s") or {}
            bh["summary"] = BH.summarize(self.bh_results, e_.get("S") or 0.22, inp.get("amp_mode", "max"))
            # 대표 지반·지진값 다시
            self._resummarize_seismic(inp)
        self._fill_bh_tree()
        self.tv_bh.selection_set(sel)

    def _resummarize_seismic(self, inp):
        s = self.res.get("seismic") or {}
        bh = s.get("boreholes") or {}
        sm = bh.get("summary") or {}
        amp = None
        if inp["site_override"] == "자동(시추)" and sm.get("n_ok"):
            s["site"] = sm["predicted"]
            s["site_src"] = f"시추 {sm['n_ok']}공 판정 ({'가장 불리' if inp['amp_mode'] == 'max' else '최다'})"
            amp = (sm["Fa"], sm["Fv"], "대표 증폭계수 " + sm.get("label", ""))
        si = (s.get("eval") or {}).get("s") or {}
        s_map = si.get("S_map")
        s["eval"] = SE.evaluate(s.get("zone"), inp["importance"], s.get("site"), s_map, inp["s_mode"] == "map", amp=amp)
        self.bh_sum.config(text=f"반경 {bh.get('radius', 0):.0f} m 검색 결과\n" + sm.get("text", ""))
        self._show_seismic()

    def _delete_hole(self):
        sel = self.tv_bh.selection()
        if not sel:
            return
        r = self.bh_results[int(sel[0])]
        if messagebox.askyesno("시추공 삭제", f"{r['hole']['code']} 를 DB 에서 지울까요?", parent=self):
            self.db.delete_hole(r["hole"]["code"])
            self._refresh_db_label()
            self._search_boreholes()

    def _import_csv(self):
        paths = filedialog.askopenfilenames(parent=self, title="시추자료 CSV 선택 (시추공·지층정보·표준관입시험)",
                                            filetypes=[("CSV", "*.csv"), ("모든 파일", "*.*")])
        if not paths:
            return
        dlg = _ImportDialog(self, list(paths), self.db)
        self.wait_window(dlg)
        self._refresh_db_label()

    def _manual_hole(self):
        inp = self._inputs()
        dlg = _HoleDialog(self, inp.get("lat"), inp.get("lon"))
        self.wait_window(dlg)
        if dlg.result:
            hole, layers, spts = dlg.result
            self.db.save_hole(hole, layers, spts)
            self._refresh_db_label()
            self.log(f"[시추] 직접 입력 저장: {hole['code']}")
            if inp.get("lat") is not None:
                self._search_boreholes()

    # ═════════════════════════════════════════════════════
    #  설정
    # ═════════════════════════════════════════════════════
    def _settings_dialog(self):
        dlg = _SettingsDialog(self, self.settings)
        self.wait_window(dlg)
        if dlg.saved:
            self.settings = geo.load_settings()
            if (self.settings.get("db_path") or "") != (str(self.db.path) if self.settings.get("db_path") else ""):
                self.db = BH.BoreholeDB(self.settings.get("db_path") or None)
            self._refresh_db_label()
        self._update_map_status()

    def open_map_tool(self, kind):
        inp = self._inputs()
        site = (inp["lat"], inp["lon"], inp.get("project") or "건설지점") if inp["lat"] is not None else None

        def pick(v):
            if kind == "wind":
                self.v["v0_manual"].set(f"{v:g}")
                self.v["v0_mode"].set("manual")
            elif kind == "snow":
                self.v["sg_manual"].set(f"{v:g}")
                self.v["sg_mode"].set("manual")
            else:
                self.v["s_map_manual"].set(f"{v:g}")
                self.v["s_mode"].set("map")
        from .map_tool import MapTool
        MapTool(self, kind, site=site, on_pick=pick, on_saved=self._update_map_status)

    # ═════════════════════════════════════════════════════
    #  파일
    # ═════════════════════════════════════════════════════
    def _new(self):
        if messagebox.askyesno("새로", "입력과 결과를 모두 지울까요?", parent=self):
            self._vars_reset()

    def _vars_reset(self):
        defaults = {"floors": "20", "height": "60", "B": "30", "D": "20", "roughness": "B", "kd": "1.0",
                    "kzt_mode": "auto", "kzt_manual": "1.0", "v0_mode": "map", "s_mode": "zone",
                    "radius": str(self.settings.get("radius_m", 500)), "amp_mode": self.settings.get("amp_mode", "max"),
                    "site_override": "자동(시추)", "sg_mode": "map", "ce": "C", "heat": "난방", "roof_slope": "0",
                    "facility": K.FACILITY_TYPES[0][0], "importance": K.FACILITY_TYPES[0][1]}
        for k, var in self.v.items():
            if isinstance(var, tk.BooleanVar):
                var.set(False)
            else:
                var.set(defaults.get(k, ""))
        self.res = {}
        self.bh_results = []
        self.file_path = ""
        self._show_all_empty()

    def _show_all_empty(self):
        self.res = {"inputs": self._inputs()}
        self._show_all()
        self.res = {}

    def _save(self):
        p = self.file_path or filedialog.asksaveasfilename(parent=self, defaultextension=FILE_EXT,
                                                           filetypes=[("Information 파일", "*" + FILE_EXT)],
                                                           initialfile=(self.v["project"].get() or "건물정보") + FILE_EXT)
        if not p:
            return
        data = {"version": 1, "inputs": {k: (bool(v.get()) if isinstance(v, tk.BooleanVar) else v.get())
                                         for k, v in self.v.items()},
                "report": report.build_text(self._inputs(), self.res) if self.res else ""}
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError as e:
            messagebox.showerror("저장", str(e), parent=self)
            return
        self.file_path = p
        self.set_status(f"저장: {p}")

    def _open(self):
        p = filedialog.askopenfilename(parent=self, filetypes=[("Information 파일", "*" + FILE_EXT), ("모든 파일", "*.*")])
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            messagebox.showerror("열기", str(e), parent=self)
            return
        for k, val in (data.get("inputs") or {}).items():
            if k in self.v:
                self.v[k].set(val)
        self.file_path = p
        self._facility_changed(set_imp=False)
        self._rough_changed()
        self.set_status(f"열기: {p} — [분석 실행]으로 다시 계산하세요")

    def _save_txt(self):
        if not self.res:
            messagebox.showinfo("보고서", "먼저 분석을 실행하세요.", parent=self)
            return
        p = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", filetypes=[("텍스트", "*.txt")],
                                         initialfile=(self.v["project"].get() or "건물정보") + "_하중검토.txt")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(report.build_text(self.res["inputs"], self.res))
            self.set_status(f"보고서 저장: {p}")

    def _save_xlsx(self):
        if not self.res:
            messagebox.showinfo("엑셀", "먼저 분석을 실행하세요.", parent=self)
            return
        p = filedialog.asksaveasfilename(parent=self, defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                         initialfile=(self.v["project"].get() or "건물정보") + "_하중검토.xlsx")
        if p:
            try:
                report.save_xlsx(p, self.res["inputs"], self.res)
            except Exception as e:                   # noqa: BLE001
                messagebox.showerror("엑셀", str(e), parent=self)
                return
            self.set_status(f"엑셀 저장: {p}")


# ═════════════════════════════════════════════════════════
#  대화상자
# ═════════════════════════════════════════════════════════
class _SettingsDialog(tk.Toplevel):
    def __init__(self, app, settings):
        super().__init__(app)
        self.app = app
        self.saved = False
        self.title("Information 설정")
        self.configure(bg=T.BG2)
        self.transient(app)
        self.resizable(False, False)
        self.s = dict(settings)
        self.vars = {}
        f = tk.Frame(self, bg=T.BG2)
        f.pack(fill="both", padx=18, pady=12)

        def row(r, label, key, width=40, note=""):
            T.label(f, label).grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=str(self.s.get(key, "")))
            self.vars[key] = v
            T.entry(f, v, width).grid(row=r, column=1, sticky="w", padx=6)
            if note:
                T.label(f, note, fg=T.TX3, font=T.FONT_S).grid(row=r, column=2, sticky="w")

        T.label(f, "주소 검색 (둘 중 하나만 있어도 됨)", fg=T.WHI, font=T.FONT_B).grid(row=0, column=0, columnspan=3, sticky="w")
        row(1, "브이월드 인증키", "vworld_key", note="vworld.kr › 오픈API › 인증키 발급 (무료)")
        row(2, "카카오 REST 키", "kakao_key", note="developers.kakao.com › 내 애플리케이션")
        T.label(f, "지형계수 (DEM: Open-Meteo, Copernicus 90m — 키 없음)", fg=T.WHI, font=T.FONT_B).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
        row(4, "풍상측 단면 길이", "terrain_up", 10, "m")
        row(5, "풍하측 단면 길이", "terrain_down", 10, "m")
        row(6, "단면 간격", "terrain_step", 10, "m")
        row(7, "풍향 수", "terrain_dirs", 10, "8 또는 16")
        T.label(f, "지반분류", fg=T.WHI, font=T.FONT_B).grid(row=8, column=0, columnspan=3, sticky="w", pady=(10, 0))
        T.label(f, "N→Vs 상관식").grid(row=9, column=0, sticky="w")
        self.v_corr = tk.StringVar(value=self.s.get("vs_corr", "imai"))
        T.combo(f, self.v_corr, list(K.VS_CORRELATIONS.keys()), width=8).grid(row=9, column=1, sticky="w", padx=6)
        T.label(f, " / ".join(K.VS_CORRELATIONS.values()), fg=T.TX3, font=T.FONT_S, wraplength=360,
                justify="left").grid(row=9, column=2, sticky="w")
        T.label(f, "기반암 기준").grid(row=10, column=0, sticky="w")
        self.v_rock = tk.StringVar(value=self.s.get("bedrock_rule", "soft"))
        T.combo(f, self.v_rock, ["soft", "weathered"], width=10).grid(row=10, column=1, sticky="w", padx=6)
        T.label(f, "soft = 연암 이상(Vs ≥ 760), weathered = 풍화암 이상", fg=T.TX3, font=T.FONT_S).grid(row=10, column=2, sticky="w")
        row(11, "풍화암 기본 Vs", "weathered_rock_vs", 10, "m/s (N값 없을 때)")
        row(12, "기본 검색 반경", "radius_m", 10, "m")
        row(13, "시추 DB 파일", "db_path", 40, "비우면 ~/.strcad/boreholes.db")

        T.label(f, "KDS 지도 보정", fg=T.WHI, font=T.FONT_B).grid(row=14, column=0, columnspan=3, sticky="w", pady=(12, 2))
        mf = tk.Frame(f, bg=T.BG2)
        mf.grid(row=15, column=0, columnspan=3, sticky="w")
        for kind in ("wind", "snow", "seismic"):
            mi = maps.map_info(kind)
            st = f"보정됨 {mi['created']}" if mi else "없음"
            T.btn(mf, f"🗺 {maps.KINDS[kind]['title'].split(' (')[0]}  [{st}]",
                  lambda k=kind: app.open_map_tool(k)).pack(anchor="w", pady=2)
        b = tk.Frame(self, bg=T.BG2)
        b.pack(fill="x", padx=18, pady=(4, 14))
        T.btn(b, "저장", self._ok, bg=T.ACC, fg=T.WHI).pack(side="right")
        T.btn(b, "닫기", self.destroy).pack(side="right", padx=6)
        self.geometry(f"+{app.winfo_rootx() + 160}+{app.winfo_rooty() + 80}")

    def _ok(self):
        for k, v in self.vars.items():
            val = v.get().strip()
            if k in ("terrain_up", "terrain_down", "terrain_step", "weathered_rock_vs", "radius_m"):
                val = _num(val, geo.DEFAULT_SETTINGS[k])
            elif k == "terrain_dirs":
                val = 16 if str(val).strip() != "8" else 8
            self.s[k] = val
        self.s["vs_corr"] = self.v_corr.get()
        self.s["bedrock_rule"] = self.v_rock.get()
        geo.save_settings(self.s)
        self.saved = True
        self.destroy()


class _ImportDialog(tk.Toplevel):
    """시추자료 CSV 가져오기 — 종류·좌표계 확인 후 DB 에 넣는다."""

    def __init__(self, app, paths, db):
        super().__init__(app)
        self.app, self.db = app, db
        self.title("시추자료 CSV 가져오기")
        self.configure(bg=T.BG2)
        self.transient(app)
        self.geometry("880x430")
        self.items = []
        T.label(self, "국토지반정보 포털 / 공공데이터포털(국토교통부_지반정보_시추공·지층정보·표준관입시험정보) CSV",
                fg=T.WHI, font=T.FONT_B).pack(anchor="w", padx=14, pady=(12, 4))
        T.label(self, "열 이름으로 종류를 자동 판단합니다. 시추공(위치) 파일은 좌표계를 확인하세요.",
                fg=T.TX3, font=T.FONT_S).pack(anchor="w", padx=14)
        tbl = tk.Frame(self, bg=T.BG2)
        tbl.pack(fill="both", expand=True, padx=14, pady=8)
        hdrs = ("파일", "종류", "좌표계", "찾은 열")
        for j, h in enumerate(hdrs):
            T.label(tbl, h, fg=T.TX2, font=T.FONT_B).grid(row=0, column=j, sticky="w", padx=4)
        crs_names = list(geo.CRS.keys())
        for i, p in enumerate(paths, 1):
            try:
                headers, rows, enc = BH.read_csv_head(p, 300)
                m = BH.map_headers(headers)
                kind = BH.detect_kind(m)
                crs = ""
                if kind == "holes":
                    xs = [BH._f(r[m["x"]]) for r in rows if len(r) > m["x"]]
                    ys = [BH._f(r[m["y"]]) for r in rows if len(r) > m["y"]]
                    crs = geo.guess_crs(xs, ys)
                found = ", ".join(f"{k}={headers[v]}" for k, v in m.items())
            except Exception as e:                   # noqa: BLE001
                kind, crs, found, m = "", "", f"읽기 실패: {e}", {}
            vk = tk.StringVar(value=kind)
            vc = tk.StringVar(value=crs)
            T.label(tbl, p.replace("\\", "/").split("/")[-1][:34], fg=T.TXT).grid(row=i, column=0, sticky="w", padx=4)
            T.combo(tbl, vk, ["holes", "layers", "spt", ""], width=8).grid(row=i, column=1, padx=4)
            cc = T.combo(tbl, vc, crs_names, width=11)
            cc.grid(row=i, column=2, padx=4)
            T.label(tbl, found[:80], fg=T.TX3, font=T.FONT_S).grid(row=i, column=3, sticky="w", padx=4)
            self.items.append((p, vk, vc, m))
        self.prog = ttk.Progressbar(self, style="Info.Horizontal.TProgressbar", mode="determinate")
        self.prog.pack(fill="x", padx=14)
        self.msg = T.label(self, "순서: 시추공(위치) → 지층정보 → 표준관입시험 (자동 정렬)", fg=T.TX3, font=T.FONT_S)
        self.msg.pack(anchor="w", padx=14, pady=4)
        b = tk.Frame(self, bg=T.BG2)
        b.pack(fill="x", padx=14, pady=(0, 12))
        self.btn = T.btn(b, "가져오기", self._go, bg=T.ACC, fg=T.WHI)
        self.btn.pack(side="right")
        T.btn(b, "닫기", self.destroy).pack(side="right", padx=6)
        self._cancel = False
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self):
        self._cancel = True
        self.destroy()

    def _go(self):
        self.btn.config(state="disabled")
        order = {"holes": 0, "layers": 1, "spt": 2, "": 3}
        jobs = sorted(((p, vk.get(), vc.get() or None, m) for p, vk, vc, m in self.items), key=lambda j: order[j[1]])

        def work():
            msgs = []
            for k, (p, kind, crs, m) in enumerate(jobs):
                if not kind or self._cancel:
                    continue

                def prog(fr, n, k=k, p=p):
                    self.app.ui(lambda: (self.prog.configure(value=(k + fr) / len(jobs) * 100),
                                         self.msg.config(text=f"{p.replace(chr(92), '/').split('/')[-1]} … {n:,}행")))
                try:
                    _, msg = self.db.import_csv(p, kind, m, crs if kind == "holes" else None, prog,
                                                cancel=lambda: self._cancel)
                except Exception as e:               # noqa: BLE001
                    msg = f"{p}: 실패 — {e}"
                msgs.append(msg)
                self.app.log("[시추 가져오기] " + msg)
            self.app.ui(lambda: self._done(msgs))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, msgs):
        if self._cancel:
            return
        self.prog.configure(value=100)
        self.msg.config(text="완료")
        messagebox.showinfo("시추자료 가져오기", "\n".join(msgs) or "가져온 파일 없음", parent=self)
        self.destroy()


class _HoleDialog(tk.Toplevel):
    """지반조사보고서의 시추주상도를 직접 입력."""

    def __init__(self, app, lat, lon):
        super().__init__(app)
        self.result = None
        self.title("시추공 직접 입력")
        self.configure(bg=T.BG2)
        self.transient(app)
        self.geometry("620x620")
        f = tk.Frame(self, bg=T.BG2)
        f.pack(fill="x", padx=14, pady=10)
        self.v = {k: tk.StringVar() for k in ("code", "name", "lat", "lon", "elev", "depth")}
        if lat is not None:
            self.v["lat"].set(f"{lat:.6f}")
            self.v["lon"].set(f"{lon:.6f}")
        for i, (k, lab) in enumerate((("code", "시추공 번호*"), ("name", "사업명/비고"), ("lat", "위도*"),
                                       ("lon", "경도*"), ("elev", "지반표고 (m)"), ("depth", "시추심도 (m)"))):
            T.label(f, lab).grid(row=i // 2, column=(i % 2) * 2, sticky="w", pady=2)
            T.entry(f, self.v[k], 18).grid(row=i // 2, column=(i % 2) * 2 + 1, padx=6, pady=2)
        T.label(self, "지층  —  한 줄에 '시작심도, 종료심도, 지층명'   예) 0, 2.5, 매립층", fg=T.WHI,
                font=T.FONT_B).pack(anchor="w", padx=14)
        self.t_layers = tk.Text(self, height=10, bg=T.BG3, fg=T.TXT, insertbackground=T.WHI, font=T.FONT_M, relief="flat")
        self.t_layers.pack(fill="both", expand=True, padx=14, pady=4)
        self.t_layers.insert("1.0", "0, 2.0, 매립층\n2.0, 9.5, 퇴적층(모래)\n9.5, 15.0, 풍화토\n15.0, 18.0, 풍화암\n18.0, 25.0, 연암\n")
        T.label(self, "표준관입시험  —  한 줄에 '심도, N값'  (50/10 처럼 써도 됨)", fg=T.WHI, font=T.FONT_B).pack(anchor="w", padx=14)
        self.t_spt = tk.Text(self, height=8, bg=T.BG3, fg=T.TXT, insertbackground=T.WHI, font=T.FONT_M, relief="flat")
        self.t_spt.pack(fill="both", expand=True, padx=14, pady=4)
        self.t_spt.insert("1.0", "1.5, 6\n3.0, 9\n4.5, 12\n6.0, 15\n9.0, 22\n12.0, 38\n15.0, 50/10\n")
        b = tk.Frame(self, bg=T.BG2)
        b.pack(fill="x", padx=14, pady=(4, 12))
        T.btn(b, "저장", self._ok, bg=T.ACC, fg=T.WHI).pack(side="right")
        T.btn(b, "취소", self.destroy).pack(side="right", padx=6)

    def _ok(self):
        code = self.v["code"].get().strip()
        lat, lon = _num(self.v["lat"].get()), _num(self.v["lon"].get())
        if not code or lat is None or lon is None:
            messagebox.showwarning("시추공", "시추공 번호와 위도·경도는 꼭 넣으세요.", parent=self)
            return
        layers, spts = [], []
        for ln in self.t_layers.get("1.0", "end").splitlines():
            parts = [x.strip() for x in ln.replace("\t", ",").split(",")]
            if len(parts) >= 3 and _num(parts[0]) is not None and _num(parts[1]) is not None:
                layers.append({"top": _num(parts[0]), "bot": _num(parts[1]), "name": ",".join(parts[2:])})
        for ln in self.t_spt.get("1.0", "end").splitlines():
            parts = [x.strip() for x in ln.replace("\t", ",").split(",")]
            if len(parts) >= 2 and _num(parts[0]) is not None:
                b, p = BH.parse_blows(parts[1])
                spts.append({"depth": _num(parts[0]), "blows": b, "pen": p})
        hole = {"code": code, "name": self.v["name"].get().strip(), "lat": lat, "lon": lon,
                "elev": _num(self.v["elev"].get()), "depth": _num(self.v["depth"].get()), "source": "직접입력"}
        self.result = (hole, layers, spts)
        self.destroy()


def open_information(parent, username=""):
    return InformationApp(parent, username=username)
