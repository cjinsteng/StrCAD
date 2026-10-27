"""
AutoCAD 구조도면 분석 프로그램 설정 파일
"""

# ── 레이어 이름 설정 ───────────────────────────────────────────────────────
# car1.dxf 기준 실측 레이어명 반영
# 기둥: !!0-COLUMN, !!0-COLUMN-N (명시적), Col (혼합 존재)
# 벽:   !!0-WALL, !!0-WALL-N, WAL, !!0-마감(W), !!0-마감
LAYER_NAMES = {
    'column': [
        '!!0-COLUMN', '!!0-COLUMN-N',          # 주 기둥 레이어
        'S-COL', '기둥', 'COLUMN', 'COL',       # 표준 레이어명
    ],
    'beam': [
        '!!0-BEAM',   '!!0-BEAM-N',
        '!!0-GIRDER', '!!0-GIRDER-N',
        'S-BEAM', '보', 'BEAM', 'GIRDER',
    ],
    'wall': [
        '!!0-WALL', '!!0-WALL-N',               # 주 벽체 레이어
        'WAL',                                   # 약어
        '!!0-마감(W)', '!!0-마감',              # 마감재 (벽)
        'S-WALL', '벽체', 'WALL',               # 표준 레이어명
    ],
    # 기둥과 벽이 겹치는 구간에서 형태 추론 대상 레이어
    # (4각형 + 비율 < 5:1 이면 기둥, 그 외 폴리곤/라인은 벽으로 분류)
    'column_finishes': [
        '!!0-마감(C)',                           # 기둥 마감재
        'Col',                                   # 혼합 레이어 (형태로 판단)
    ],
    'beam_name': ['!!0-BEAM-N', '!!0-GIRDER-N', 'S-BEAM-N', 'S-GIRDER-N'],
}

BEAM_NAME_MATCH_DIST = 3000

# ── 허용 오차 설정 (단위: mm) ──────────────────────────────────────────────
TOLERANCE = {
    'connection':    1.0,    # 부재 연결 판단 허용 오차
    'intersection':  0.5,    # 교차점 판단 허용 오차
    'column_radius': 10.0    # 기둥 반경 기본값
}

# ── 출력 파일 설정 ─────────────────────────────────────────────────────────
OUTPUT = {
    'folder':                 'output',
    'span_prefix':            '스팬정리',
    'discontinuity_prefix':   '불연속구간',
    'column_spacing_prefix':  '기둥간격',
}

# ── 분석 옵션 ──────────────────────────────────────────────────────────────
ANALYSIS_OPTIONS = {
    'min_span_length':   1000,   # 최소 스팬 길이 (mm)
    'max_span_length':   20000,  # 최대 스팬 길이 (mm)
    'report_decimals':   0,      # 보고서 소수점 자리수
    'sort_by_location':  True,   # 위치별 정렬 여부
}

# ── 도면 단위 ──────────────────────────────────────────────────────────────
DRAWING_UNITS = 'mm'

# ── 보 폭 인식 설정 ────────────────────────────────────────────────────────
MAX_BEAM_WIDTH     = 2000   # mm - 이 이상 떨어진 평행선은 같은 보로 보지 않음
PARALLEL_ANGLE_TOL = 5.0    # degree - 평행 허용 각도 오차

# ── 기둥/벽 형태 추론 설정 ────────────────────────────────────────────────
# 레이어가 불명확할 때 LWPOLYLINE 형태로 기둥/벽 구분
COLUMN_SHAPE = {
    'max_vertices':    6,     # 이하이면 기둥 후보
    'max_aspect_ratio': 4.5,  # 가로:세로 비율 이하이면 기둥 (정사각형에 가까울수록)
    'min_size':        200,   # mm - 이 이하 크기는 기둥으로 인식 안함 (노이즈 제거)
}
