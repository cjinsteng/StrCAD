# ============================================================
# strcad_gui.py 수정 안내
# 아래 3곳을 수정하세요
# ============================================================

# ── 1. 상단 import에 추가 ────────────────────────────────────
from modules.beam_editor import open_viewer, open_project_manager


# ── 2. 툴바 버튼 추가 (_build_ui → hdr 프레임 안에) ──────────
#   기존 header 부분 끝에 아래 버튼 추가:
tk.Button(hdr, text="📂  프로젝트 관리", 
          command=lambda: open_project_manager(self),
          font=("Malgun Gothic", 9), bg=BG3, fg=TEXT,
          relief="flat", padx=10, cursor="hand2").pack(side="right", padx=8, pady=12)


# ── 3. _analysis_worker에서 HTML 뷰어 생성 부분을 아래로 교체 ──
#   기존 7단계(BeamViewerExporter) 블록 전체를 아래로 변경:

# ── 7단계: 인터랙티브 뷰어 (tkinter + DB 저장) ───────────────
self._set_status("인터랙티브 뷰어 생성 중...", 90)
if beam_analyzer and beam_analyzer.beam_data:
    project_name = Path(dxf_path).stem   # DXF 파일명을 프로젝트명으로
    db_path = str(out_dir / "strcad_data.db")
    self.after(0, lambda: open_viewer(
        self,
        beam_data        = beam_analyzer.beam_data,
        column_positions = column_positions,
        project_name     = project_name,
        dxf_path         = dxf_path,
        db_path          = db_path,
    ))
    self._log("✓ 뷰어 열림 (수정 내용은 DB에 자동 저장)", "ok")
