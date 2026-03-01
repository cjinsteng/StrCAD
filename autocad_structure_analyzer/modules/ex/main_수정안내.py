# ============================================================
# main.py 에서 아래처럼 수정하세요
# ============================================================

# 상단 import 에 추가:
from modules import DXFReader, ColumnAnalyzer, BeamAnalyzer, DiscontinuityChecker, ExcelExporter
from modules.beam_visualizer import BeamVisualizer   # ← 추가


# 5단계(Excel 리포트) 이후, "완료 메시지" 직전에 아래 블록 추가:

# ── 6단계: 보 평면도 시각화 ──────────────────────────────────
print("\n6단계: 보 평면도 이미지 생성 중...")
if beam_analyzer and beam_analyzer.beam_data:
    col_pos = column_positions if columns else []
    visualizer = BeamVisualizer(
        beam_data=beam_analyzer.beam_data,
        column_positions=col_pos,
        title="구조 평면도 - 보 스팬 분석"
    )
    img_path = visualizer.save_image("beam_plan.png")
    if img_path:
        generated_files.append(img_path)
else:
    print("⚠ 시각화할 보 데이터가 없습니다.")
