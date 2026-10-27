"""
AutoCAD 구조도면 분석 프로그램 설정 파일
"""

# 레이어 이름 설정 (대소문자 구분 없음)
LAYER_NAMES = {
    'column': ['S-COL', '기둥', 'COLUMN', 'COL','!!0-COLUMN-N'],
    'girder': ['!!0-GIRDER', '!!0-GIRDER-N', 'S-GIRDER', 'GIRDER'],
    'beam':   ['!!0-BEAM', '!!0-BEAM-N',  'S-BEAM',   'BEAM',  '보'],
    'slab': ['S-SLAB', '슬라브', 'SLAB'],
    'wall': ['S-WALL', '벽체', 'WALL', 'WALL-1', 'WALL-2'],
    'beam_name': ['!!0-BEAM-N', '!!0-GIRDER-N', 'S-BEAM-N', 'S-GIRDER-N'],
    
}

BEAM_NAME_MATCH_DIST = 3000 

# 허용 오차 설정 (단위: mm)
TOLERANCE = {
    'connection': 1.0,      # 부재 연결 판단 허용 오차
    'intersection': 0.5,    # 교차점 판단 허용 오차
    'column_radius': 10.0   # 기둥 반경 기본값
}

# 출력 파일 설정
OUTPUT = {
    'folder': 'output',
    'span_prefix': '스팬정리',
    'discontinuity_prefix': '불연속구간',
    'column_spacing_prefix': '기둥간격'
}

# 분석 옵션
ANALYSIS_OPTIONS = {
    'min_span_length': 1000,        # 최소 스팬 길이 (mm)
    'max_span_length': 20000,       # 최대 스팬 길이 (mm)
    'report_decimals': 0,           # 보고서 소수점 자리수
    'sort_by_location': True        # 위치별 정렬 여부
}

# 도면 단위 (AutoCAD 단위)
DRAWING_UNITS = 'mm'  # 'mm', 'm', 'cm' 등

#추가#

# 1. LAYER_NAMES - beam 레이어를 실제 DXF 레이어명으로 수정
LAYER_NAMES = {
    'column': ['!!0-COLUMN', '!!0-COLUMN-N', 'S-COL', '기둥', 'COLUMN', 'COL'],
    'beam':   ['!!0-BEAM',   '!!0-BEAM-N',   '!!0-GIRDER', '!!0-GIRDER-N',
               'S-BEAM', '보', 'BEAM', 'GIRDER'],
    'wall':   ['!!0-WALL',   '!!0-WALL-N',   'S-WALL', '벽체', 'WALL'],
}

# 2. 평행선 보 폭 인식 설정 (beam_analyzer.py 에서 사용)
MAX_BEAM_WIDTH    = 2000   # mm - 이 이상 떨어진 평행선은 같은 보로 보지 않음
PARALLEL_ANGLE_TOL = 5.0  # degree - 평행 허용 각도 오차