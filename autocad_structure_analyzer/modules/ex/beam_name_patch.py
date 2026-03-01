# ============================================================
# 1. config.py 에 아래 항목 추가
# ============================================================

LAYER_NAMES = {
    'column':    ['!!0-COLUMN', '!!0-COLUMN-N', 'S-COL', '기둥', 'COLUMN'],
    'beam':      ['!!0-BEAM',   '!!0-GIRDER',   'S-BEAM', '보', 'BEAM'],
    'wall':      ['!!0-WALL',   '!!0-WALL-N',   'S-WALL', '벽체'],
    'beam_name': ['!!0-BEAM-N', '!!0-GIRDER-N', 'S-BEAM-N', 'S-GIRDER-N'],  # ← 추가
}

# 보 이름 텍스트 매칭 최대 거리 (mm)
BEAM_NAME_MATCH_DIST = 3000   # ← 추가


# ============================================================
# 2. main.py 수정 — BeamAnalyzer 생성 시 reader 전달
# ============================================================

# 기존:
beam_analyzer = BeamAnalyzer(beams, column_positions)

# 변경:
beam_analyzer = BeamAnalyzer(beams, column_positions, dxf_reader=reader)


# ============================================================
# 3. strcad_gui.py 수정 — _analysis_worker 안에서 동일하게
# ============================================================

# 기존:
beam_analyzer = BeamAnalyzer(beams, column_positions)

# 변경:
beam_analyzer = BeamAnalyzer(beams, column_positions, dxf_reader=reader)
