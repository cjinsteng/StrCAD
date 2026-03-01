"""
AutoCAD 구조도면 분석 모듈
"""

from .dxf_reader import DXFReader
from .column_analyzer import ColumnAnalyzer
from .beam_analyzer import BeamAnalyzer
from .discontinuity_checker import DiscontinuityChecker
from .excel_exporter import ExcelExporter
from .beam_visualizer import BeamVisualizer
from .beam_viewer_exporter import BeamViewerExporter
from .beam_editor import open_viewer, open_project_manager

__all__ = [
    'DXFReader',
    'ColumnAnalyzer',
    'BeamAnalyzer',
    'DiscontinuityChecker',
    'ExcelExporter'
]

#
#클릭 → 보 ID, 스팬 길이, 폭, 방향, 기둥 연결 정보 표시
#휠 스크롤 → 줌 인/아웃
#드래그 → 평면도 이동
#우측 목록 → 보 목록 클릭으로 이동
#방향 필터 버튼 → X방향/Y방향/대각선만 보기
#검색창 → 보 ID로 검색
# 