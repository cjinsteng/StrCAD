# ============================================================
# 1. modules/__init__.py 에 아래 줄 추가
# ============================================================
from .beam_viewer_exporter import BeamViewerExporter


# ============================================================
# 2. main.py 상단 import 수정
# ============================================================
from modules import (DXFReader, ColumnAnalyzer, BeamAnalyzer,
                     DiscontinuityChecker, ExcelExporter, BeamViewerExporter)


# ============================================================
# 3. main.py 에서 6단계(이미지) 이후 아래 블록 추가
#    (기존 beam_visualizer 6단계 바로 다음에 붙이세요)
# ============================================================

# ── 7단계: 인터랙티브 HTML 뷰어 생성 ─────────────────────────
print("\n7단계: 인터랙티브 HTML 뷰어 생성 중...")
if beam_analyzer and beam_analyzer.beam_data:
    col_pos = column_positions if columns else []
    viewer = BeamViewerExporter(
        beam_data=beam_analyzer.beam_data,
        column_positions=col_pos,
        title="구조 평면도 - 보 스팬 분석"
    )
    html_path = viewer.export("beam_viewer.html")
    generated_files.append(html_path)
    print(f"   → 브라우저에서 열기: {html_path}")
else:
    print("⚠ HTML 뷰어 생성할 보 데이터가 없습니다.")
