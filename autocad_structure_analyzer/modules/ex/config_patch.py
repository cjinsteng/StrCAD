# ============================================================
# config.py 수정 사항
# LAYER_NAMES 전체를 아래로 교체하세요
# ============================================================

LAYER_NAMES = {
    'column': ['!!0-COLUMN', '!!0-COLUMN-N', 'S-COL', '기둥', 'COLUMN'],

    # GIRDER와 BEAM을 분리하여 정의
    'girder': ['!!0-GIRDER', 'S-GIRDER', 'GIRDER'],   # ← 추가
    'beam':   ['!!0-BEAM',   'S-BEAM',   'BEAM',  '보'],

    # 기존 통합 beam 목록도 유지 (다른 모듈 호환용)
    # 실제 get_beams()에서는 girder + beam 합쳐서 반환하도록 dxf_reader.py 수정 필요

    'wall':      ['!!0-WALL', '!!0-WALL-N', 'S-WALL', '벽체'],
    'beam_name': ['!!0-BEAM-N', '!!0-GIRDER-N', 'S-BEAM-N', 'S-GIRDER-N'],
}

# 보 이름 텍스트 매칭 최대 거리 (mm)
BEAM_NAME_MATCH_DIST = 3000

# ============================================================
# dxf_reader.py의 get_beams() 메서드를 아래로 교체
# GIRDER + BEAM 레이어 모두 반환
# ============================================================
def get_beams(self):
    """보 + 거더 엔티티 모두 가져오기"""
    girder_layers = config.LAYER_NAMES.get('girder', [])
    beam_layers   = config.LAYER_NAMES.get('beam',   [])
    all_layers    = girder_layers + beam_layers

    lines     = self.get_entities_by_layer(all_layers, 'LINE')
    polylines = self.get_entities_by_layer(all_layers, 'LWPOLYLINE')
    return lines + polylines
