# ============================================================
# config.py 에 아래 항목들을 추가/수정하세요
# ============================================================

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
