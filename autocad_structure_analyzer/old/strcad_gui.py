"""
STRCAD - 구조도면 자동 분석 프로그램
GUI 메인 앱 (tkinter 기반)
v1.1 - 기둥 폴리곤 / 벽체 형상 뷰어 연동 추가
"""

import sys
import os
import threading
import subprocess
import webbrowser
from pathlib import Path

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    WORK_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
    WORK_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from modules.beam_editor import open_viewer, open_project_manager

# ── 색상 팔레트 ──────────────────────────────────────────────
BG       = "#0d1117"
BG2      = "#161b22"
BG3      = "#21262d"
ACCENT   = "#238636"
ACCENT2  = "#2ea043"
BLUE     = "#1f6feb"
RED      = "#da3633"
ORANGE   = "#e3b341"
TEXT     = "#c9d1d9"
TEXT2    = "#8b949e"
BORDER   = "#30363d"
WHITE    = "#f0f6fc"
TEAL     = "#39d353"


class StrcadApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STRCAD  |  구조도면 자동 분석")
        self.geometry("820x640")
        self.minsize(700, 540)
        self.configure(bg=BG)
        self.resizable(True, True)

        self.dxf_path   = tk.StringVar(value="")
        self.is_running = False
        self.output_files = []

        self.opt_excel  = tk.BooleanVar(value=True)
        self.opt_png    = tk.BooleanVar(value=True)
        self.opt_html   = tk.BooleanVar(value=True)

        self._build_ui()
        self._center_window()

    # ──────────────────────────────────────────────────────────
    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG2, height=64)
        hdr.pack(fill="x", side="top"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🏗  STRCAD", font=("Consolas", 20, "bold"),
                 bg=BG2, fg=WHITE).pack(side="left", padx=20, pady=10)
        tk.Label(hdr, text="구조도면 자동 분석 프로그램 v1.1",
                 font=("Malgun Gothic", 10), bg=BG2, fg=TEXT2).pack(side="left", pady=20)
        tk.Button(hdr, text="📂  프로젝트 관리",
                  command=self._open_project_manager,
                  font=("Malgun Gothic", 9), bg=BG3, fg=TEXT,
                  relief="flat", padx=10, cursor="hand2"
                  ).pack(side="right", padx=12, pady=16)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=20)
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=BG2, bd=0, relief="flat",
                         highlightbackground=BORDER, highlightthickness=1)
        right.pack(side="right", fill="both", padx=(16,0), ipadx=12, ipady=12)
        right.pack_propagate(False); right.configure(width=240)
        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent):
        self._section_label(parent, "① DXF 파일 선택")
        file_row = tk.Frame(parent, bg=BG); file_row.pack(fill="x", pady=(6, 0))
        self.file_entry = tk.Entry(
            file_row, textvariable=self.dxf_path,
            font=("Consolas", 10), bg=BG3, fg=TEXT,
            insertbackground=WHITE, relief="flat",
            highlightbackground=BORDER, highlightthickness=1, state="readonly")
        self.file_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0,8))
        self._btn(file_row, "파일 선택", self._select_file,
                  bg=BG3, fg=TEXT, width=9).pack(side="left")
        tk.Label(parent, text="또는 파일을 여기에 드래그하세요",
                 font=("Malgun Gothic", 9), bg=BG, fg=TEXT2).pack(anchor="w", pady=(4,0))
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=16)

        self._section_label(parent, "② 출력 옵션")
        opts_frame = tk.Frame(parent, bg=BG); opts_frame.pack(fill="x", pady=(8, 0))
        self._check(opts_frame, "📊  Excel 리포트 생성", self.opt_excel)
        self._check(opts_frame, "🖼  보 평면도 이미지 (PNG)", self.opt_png)
        self._check(opts_frame, "🖥  인터랙티브 뷰어 (기둥·벽·보 표시)", self.opt_html)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=16)

        self._section_label(parent, "③ 분석 실행")
        self.run_btn = self._btn(parent, "▶  분석 시작", self._run_analysis,
                                  bg=ACCENT, fg=WHITE, font_size=12, pady=10)
        self.run_btn.pack(fill="x", pady=(8,0))

        style = ttk.Style(); style.theme_use('clam')
        style.configure("green.Horizontal.TProgressbar",
                        background=TEAL, troughcolor=BG3,
                        bordercolor=BG3, lightcolor=TEAL, darkcolor=TEAL)
        self.progress = ttk.Progressbar(parent, style="green.Horizontal.TProgressbar",
                                        mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(10, 4))
        self.status_var = tk.StringVar(value="대기 중...")
        tk.Label(parent, textvariable=self.status_var,
                 font=("Malgun Gothic", 9), bg=BG, fg=TEXT2, anchor="w").pack(fill="x")

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=12)
        self._section_label(parent, "실행 로그")
        log_frame = tk.Frame(parent, bg=BG3,
                             highlightbackground=BORDER, highlightthickness=1)
        log_frame.pack(fill="both", expand=True, pady=(6,0))
        self.log_text = tk.Text(log_frame, bg=BG3, fg=TEXT, font=("Consolas", 9),
                                relief="flat", state="disabled", wrap="word", padx=8, pady=6)
        scroll = tk.Scrollbar(log_frame, command=self.log_text.yview, bg=BG3, troughcolor=BG3)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("ok",     foreground=TEAL)
        self.log_text.tag_config("warn",   foreground=ORANGE)
        self.log_text.tag_config("err",    foreground=RED)
        self.log_text.tag_config("info",   foreground=BLUE)
        self.log_text.tag_config("header", foreground=WHITE, font=("Consolas", 9, "bold"))

    def _build_right(self, parent):
        tk.Label(parent, text="생성된 파일", font=("Malgun Gothic", 10, "bold"),
                 bg=BG2, fg=WHITE).pack(anchor="w", padx=12, pady=(12,6))
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)
        self.file_list_frame = tk.Frame(parent, bg=BG2)
        self.file_list_frame.pack(fill="both", expand=True, padx=12, pady=8)
        tk.Label(self.file_list_frame, text="분석 완료 후\n파일이 표시됩니다",
                 font=("Malgun Gothic", 9), bg=BG2, fg=TEXT2, justify="center").pack(pady=30)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)
        self._btn(parent, "📁  출력 폴더 열기", self._open_output_dir,
                  bg=BG3, fg=TEXT).pack(fill="x", padx=12, pady=10)

    # ── 헬퍼 ──────────────────────────────────────────────────
    def _section_label(self, parent, text):
        tk.Label(parent, text=text, font=("Malgun Gothic", 10, "bold"),
                 bg=BG, fg=TEXT).pack(anchor="w")

    def _btn(self, parent, text, cmd, bg=BG3, fg=TEXT,
             font_size=10, pady=6, width=None):
        b = tk.Button(parent, text=text, command=cmd,
                      font=("Malgun Gothic", font_size, "bold"),
                      bg=bg, fg=fg, activebackground=ACCENT2,
                      activeforeground=WHITE, relief="flat", cursor="hand2", pady=pady,
                      **({"width": width} if width else {}))
        b.bind("<Enter>", lambda e: b.configure(bg=ACCENT2 if bg==ACCENT else BG3))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def _check(self, parent, text, var):
        f = tk.Frame(parent, bg=BG); f.pack(anchor="w", pady=3)
        tk.Checkbutton(f, text=text, variable=var,
                       font=("Malgun Gothic", 10), bg=BG, fg=TEXT,
                       activebackground=BG, activeforeground=WHITE,
                       selectcolor=BG3, relief="flat").pack(side="left")

    def _center_window(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _select_file(self):
        path = filedialog.askopenfilename(
            title="DXF 파일 선택",
            filetypes=[("DXF 파일", "*.dxf"), ("모든 파일", "*.*")])
        if path:
            self.dxf_path.set(path)
            self._log(f"파일 선택: {Path(path).name}", "info")

    # ──────────────────────────────────────────────────────────
    #  분석 실행
    # ──────────────────────────────────────────────────────────
    def _run_analysis(self):
        if self.is_running: return
        path = self.dxf_path.get()
        if not path or not os.path.exists(path):
            messagebox.showwarning("파일 없음", "DXF 파일을 먼저 선택하세요."); return
        self.is_running = True
        self.run_btn.configure(text="⏳  분석 중...", state="disabled", bg=BG3)
        self.progress["value"] = 0
        self.output_files = []; self._clear_log(); self._clear_file_list()
        thread = threading.Thread(target=self._analysis_worker, args=(path,), daemon=True)
        thread.start()

    def _analysis_worker(self, dxf_path: str):
        try:
            self._log("=" * 50, "header")
            self._log("STRCAD 구조도면 분석 시작", "header")
            self._log("=" * 50, "header")

            out_dir = Path(dxf_path).parent / "STRCAD_출력"
            out_dir.mkdir(exist_ok=True)

            from modules import DXFReader, ColumnAnalyzer, BeamAnalyzer
            from modules import DiscontinuityChecker, ExcelExporter
            from modules.beam_visualizer import BeamVisualizer
            from modules.beam_viewer_exporter import BeamViewerExporter

            # ── 1. DXF 로드 ──
            self._set_status("DXF 파일 로드 중...", 5)
            reader = DXFReader(dxf_path)
            if not reader.load():
                self._log("✗ DXF 파일 로드 실패", "err"); return
            self._log("✓ DXF 파일 로드 완료", "ok")
            layer_info = reader.get_layer_info()
            self._log(f"  레이어 수: {len(layer_info)}개", "info")

            # ── 2. 기둥 분석 ──
            self._set_status("기둥 분석 중...", 15)
            columns = reader.get_columns()
            column_positions = []
            col_analyzer = None

            if not columns:
                self._log("⚠ CIRCLE/INSERT 기둥을 찾을 수 없습니다", "warn")
            else:
                col_analyzer = ColumnAnalyzer(columns)
                column_positions = col_analyzer.extract_positions()
                x_grid = col_analyzer.find_grid_spacing('x')
                y_grid = col_analyzer.find_grid_spacing('y')
                self._log(f"✓ 기둥 중심점 {len(column_positions)}개 인식", "ok")
                self._log(f"  X 그리드: {len(x_grid['gridlines'])}개 / Y 그리드: {len(y_grid['gridlines'])}개", "info")

            # ── 2-b. 기둥·벽 형상 파싱 (폴리곤/라인) ──
            self._set_status("기둥·벽 형상 파싱 중...", 25)
            column_shapes = reader.get_column_shapes()
            wall_shapes   = reader.get_wall_shapes()
            self._log(f"✓ 기둥 형상: {len(column_shapes)}개  (명시 {sum(1 for s in column_shapes if s['source']=='explicit')}  추론 {sum(1 for s in column_shapes if s['source']=='shape_inferred')})", "ok")
            self._log(f"✓ 벽체 형상: {len(wall_shapes)}개", "ok")

            # ── 3. 보 분석 ──
            self._set_status("보 스팬 분석 중...", 40)
            beams = reader.get_beams()
            beam_analyzer = None

            if not beams:
                self._log("⚠ 보를 찾을 수 없습니다", "warn")
            else:
                beam_analyzer = BeamAnalyzer(beams, column_positions, dxf_reader=reader)
                span_data = beam_analyzer.analyze_spans()
                summary = beam_analyzer.get_summary()
                self._log(f"✓ 보 스팬 {summary['total_spans']}개 분석 완료", "ok")
                self._log(f"  X방향: {summary['x_direction_spans']}개  Y방향: {summary['y_direction_spans']}개", "info")
                if summary.get('paired_beam_count', 0) > 0:
                    self._log(f"  폭 인식: {summary['paired_beam_count']}개 (평균 {summary['avg_beam_width']:.0f}mm)", "info")
                self._log(f"  평균 스팬: {summary['avg_span_length']/1000:.2f}m  최대: {summary['max_span_length']/1000:.2f}m", "info")

            # ── 4. 불연속 검사 ──
            self._set_status("불연속 구간 검사 중...", 55)
            all_members = (beams or []) + reader.get_walls()
            disc_checker = None
            if all_members:
                disc_checker = DiscontinuityChecker(all_members)
                discontinuities = disc_checker.find_discontinuities()
                self._log(f"✓ 불연속 검사 완료 ({len(discontinuities)}개 발견)", "ok")

            # ── 5. Excel ──
            if self.opt_excel.get():
                self._set_status("Excel 리포트 생성 중...", 65)
                import config as _cfg
                _orig_folder = _cfg.OUTPUT.get('folder', 'output')
                _cfg.OUTPUT['folder'] = str(out_dir)
                try:
                    exporter = ExcelExporter()
                finally:
                    _cfg.OUTPUT['folder'] = _orig_folder

                if beam_analyzer and beam_analyzer.beam_data:
                    f = exporter.export_beam_spans(beam_analyzer.beam_data)
                    self._add_output_file(f, "📊 보 스팬 리포트")
                if disc_checker and disc_checker.discontinuities:
                    f = exporter.export_discontinuities(disc_checker.discontinuities)
                    self._add_output_file(f, "📊 불연속 리포트")
                if col_analyzer:
                    f = exporter.export_column_spacing({
                        'x_spacings': x_grid['spacings'],
                        'y_spacings': y_grid['spacings']
                    })
                    self._add_output_file(f, "📊 기둥 간격 리포트")
                summary_data = {}
                if col_analyzer: summary_data['column_summary'] = col_analyzer.get_summary()
                if beam_analyzer and beam_analyzer.beam_data:
                    summary_data['beam_summary'] = summary
                if disc_checker and disc_checker.discontinuities:
                    summary_data['discontinuity_summary'] = disc_checker.get_summary()
                if summary_data:
                    f = exporter.export_summary(summary_data)
                    self._add_output_file(f, "📊 종합 요약")
                self._log("✓ Excel 리포트 생성 완료", "ok")

            # ── 6. PNG ──
            if self.opt_png.get() and beam_analyzer and beam_analyzer.beam_data:
                self._set_status("보 평면도 이미지 생성 중...", 78)
                png_path = str(out_dir / "beam_plan.png")
                viz = BeamVisualizer(beam_data=beam_analyzer.beam_data,
                                     column_positions=column_positions,
                                     title="구조 평면도 - 보 스팬 분석")
                result = viz.save_image(png_path)
                if result:
                    self._add_output_file(result, "🖼 보 평면도")
                    self._log("✓ PNG 이미지 생성 완료", "ok")

            # ── 7. 인터랙티브 뷰어 (기둥·벽·보 포함) ──
            if self.opt_html.get() and beam_analyzer and beam_analyzer.beam_data:
                self._set_status("인터랙티브 뷰어 열기...", 90)
                self._pending_viewer = {
                    'beam_data':        beam_analyzer.beam_data,
                    'column_positions': column_positions,
                    'column_shapes':    column_shapes,    # ← 신규
                    'wall_shapes':      wall_shapes,      # ← 신규
                    'project_name':     Path(dxf_path).stem,
                    'dxf_path':         dxf_path,
                    'db_path':          str(out_dir / "strcad_data.db"),
                }
                self.after(100, self._open_viewer_safe)
                self._log("✓ 인터랙티브 뷰어 준비 완료 (기둥·벽 포함)", "ok")

            # ── 완료 ──
            self._set_status("✅ 분석 완료!", 100)
            self._log("", "")
            self._log("=" * 50, "header")
            self._log(f"✅  분석 완료!  출력 폴더: {out_dir}", "ok")
            self._log("=" * 50, "header")

        except Exception as e:
            import traceback
            self._log(f"✗ 오류 발생: {e}", "err")
            self._log(traceback.format_exc(), "err")
            self._set_status("오류 발생", 0)
        finally:
            self.is_running = False
            self.after(0, lambda: self.run_btn.configure(
                text="▶  분석 시작", state="normal", bg=ACCENT))

    # ── UI 업데이트 ───────────────────────────────────────────
    def _log(self, msg, tag=""):
        def _do():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_status(self, msg, pct):
        self.after(0, lambda: self.status_var.set(msg))
        self.after(0, lambda: self.progress.configure(value=pct))

    def _add_output_file(self, path, label):
        if not path: return
        self.output_files.append((label, path))
        def _do():
            for w in self.file_list_frame.winfo_children(): w.destroy()
            for lbl, p in self.output_files:
                row = tk.Frame(self.file_list_frame, bg=BG2); row.pack(fill="x", pady=2)
                tk.Label(row, text=lbl, font=("Malgun Gothic", 9),
                         bg=BG2, fg=TEXT, anchor="w", wraplength=160
                         ).pack(side="left", fill="x", expand=True)
                tk.Button(row, text="열기", font=("Malgun Gothic", 8),
                          bg=BG3, fg=TEAL, relief="flat", cursor="hand2",
                          command=lambda fp=p: self._open_file(fp)
                          ).pack(side="right")
        self.after(0, _do)

    def _clear_file_list(self):
        for w in self.file_list_frame.winfo_children(): w.destroy()
        tk.Label(self.file_list_frame, text="분석 완료 후\n파일이 표시됩니다",
                 font=("Malgun Gothic", 9), bg=BG2, fg=TEXT2, justify="center").pack(pady=30)

    def _open_file(self, path):
        try:
            if path.endswith(".html"):
                webbrowser.open(f"file:///{path}")
            elif os.name == "nt":
                os.startfile(path)
            else:
                subprocess.Popen(["open", path])
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _open_output_dir(self):
        path = self.dxf_path.get()
        if path:
            out_dir = Path(path).parent / "STRCAD_출력"
            out_dir.mkdir(exist_ok=True)
            if os.name == "nt":
                os.startfile(str(out_dir))
            else:
                subprocess.Popen(["open", str(out_dir)])
        else:
            messagebox.showinfo("안내", "먼저 DXF 파일을 선택하세요.")

    def _open_viewer_safe(self):
        v = getattr(self, '_pending_viewer', None)
        if not v: return
        self._pending_viewer = None
        try:
            open_viewer(
                self,
                beam_data        = v['beam_data'],
                column_positions = v['column_positions'],
                column_shapes    = v.get('column_shapes', []),   # ← 신규
                wall_shapes      = v.get('wall_shapes', []),     # ← 신규
                project_name     = v['project_name'],
                dxf_path         = v['dxf_path'],
                db_path          = v['db_path'],
                project_id       = getattr(self, '_project_id', None),
                floor_name       = getattr(self, '_floor_name', None),
            )
        except Exception as e:
            import traceback
            messagebox.showerror("뷰어 오류",
                f"뷰어를 열 수 없습니다:\n{e}\n\n{traceback.format_exc()}")

    def _open_project_manager(self):
        db_path = str(WORK_DIR / "strcad_data.db")
        open_project_manager(self, db_path)

    def _run_analysis_with_file(self, dxf_path: str,
                                 floor_name: str = '',
                                 project_id: int = None):
        if self.is_running:
            messagebox.showwarning("실행 중", "현재 분석이 진행 중입니다."); return
        self.dxf_path.set(dxf_path)
        self._floor_name = floor_name
        self._project_id = project_id
        self.is_running  = True
        self.run_btn.configure(text="⏳  분석 중...", state="disabled", bg=BG3)
        self.progress["value"] = 0
        self.output_files = []; self._clear_log(); self._clear_file_list()
        self._log(f"▶  [{floor_name}] 층 분석 시작: {dxf_path}", "header")
        thread = threading.Thread(target=self._analysis_worker,
                                   args=(dxf_path,), daemon=True)
        thread.start()


if __name__ == "__main__":
    app = StrcadApp()
    app.mainloop()
