"""
DXF 파일 읽기 및 기본 처리 모듈
- 보 이름 텍스트 정밀 매칭: 레이어 계열 우선 + 중점 거리 가중치
- 쌍 선분의 실제 중심선 기준으로 이름 매칭
"""

import math
import ezdxf
from typing import List, Dict, Any, Tuple, Optional
import config


# 레이어 → BEAM/GIRDER 계열 판별
def _layer_family(layer: str) -> str:
    lu = layer.upper()
    if 'GIRDER' in lu: return 'GIRDER'
    if 'BEAM'   in lu: return 'BEAM'
    return ''


class DXFReader:

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.doc  = None
        self.msp  = None
        self._beam_name_texts: List[Dict] = []   # {text, x, y, layer, family}

    def load(self):
        try:
            self.doc = ezdxf.readfile(self.filepath)
            self.msp = self.doc.modelspace()
            print(f"✓ DXF 파일 로드 성공: {self.filepath}")
            self._beam_name_texts = self._parse_beam_name_texts()
            print(f"  보/거더 이름 텍스트: {len(self._beam_name_texts)}개 인식")
            return True
        except IOError:
            print(f"✗ 파일을 찾을 수 없습니다: {self.filepath}")
            return False
        except ezdxf.DXFStructureError:
            print(f"✗ 잘못된 DXF 파일 형식: {self.filepath}")
            return False

    # ── 이름 텍스트 파싱 ─────────────────────────────────────
    def _parse_beam_name_texts(self) -> List[Dict]:
        name_layers = getattr(config, 'LAYER_NAMES', {}).get(
            'beam_name', ['!!0-BEAM-N', '!!0-GIRDER-N'])
        result = []
        for ent in self.msp:
            if ent.dxf.layer not in name_layers:
                continue
            if ent.dxftype() not in ('TEXT', 'MTEXT'):
                continue
            try:
                if ent.dxftype() == 'TEXT':
                    text = ent.dxf.text.strip()
                    x, y = ent.dxf.insert.x, ent.dxf.insert.y
                else:
                    text = ent.plain_mtext().strip()
                    x, y = ent.dxf.insert.x, ent.dxf.insert.y
                if text:
                    result.append({
                        'text':   text,
                        'x':      x,
                        'y':      y,
                        'layer':  ent.dxf.layer,
                        'family': _layer_family(ent.dxf.layer),  # 'BEAM' | 'GIRDER'
                    })
            except Exception:
                continue
        return result

    # ── 정밀 이름 매칭 ───────────────────────────────────────
    def match_beam_name(self,
                        x1: float, y1: float,
                        x2: float, y2: float,
                        beam_layer: str = '',
                        max_dist: float = None) -> Optional[str]:
        """
        보 중심선 (x1,y1)~(x2,y2)에 가장 적합한 이름 텍스트 반환.

        개선 로직:
          1) 텍스트 레이어 계열(BEAM/GIRDER)이 보 레이어 계열과 같으면 우선
          2) 선분 거리 + 중점 거리 가중 점수로 최적 선택
             score = 선분거리 + 중점거리 * 0.3
             (텍스트가 선분 가운데에 가까울수록 유리)
        """
        if not self._beam_name_texts:
            return None

        max_d = max_dist or getattr(config, 'BEAM_NAME_MATCH_DIST', 3000)
        my_family = _layer_family(beam_layer)

        # 중점
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2

        best_name  = None
        best_score = float('inf')

        for t in self._beam_name_texts:
            d_seg = self._pt_to_seg_dist(t['x'], t['y'], x1, y1, x2, y2)
            if d_seg > max_d:
                continue

            # 중점까지 거리
            d_mid = math.hypot(t['x'] - mx, t['y'] - my)

            # 계열 가중치: 계열 불일치 시 패널티
            family_penalty = 0
            if my_family and t['family'] and t['family'] != my_family:
                family_penalty = max_d * 0.8   # 사실상 제외

            score = d_seg + d_mid * 0.3 + family_penalty
            if score < best_score:
                best_score = score
                best_name  = t['text']

        return best_name

    def get_beam_name_texts(self) -> List[Dict]:
        return self._beam_name_texts

    # ── 기존 메서드 ──────────────────────────────────────────
    def get_entities_by_layer(self, layer_names, entity_type=None):
        entities = []
        for layer_name in layer_names:
            q = (f'{entity_type}[layer=="{layer_name}"]' if entity_type
                 else f'*[layer=="{layer_name}"]')
            entities.extend(self.msp.query(q))
        return entities

    def get_all_layers(self):
        return [layer.dxf.name for layer in self.doc.layers]

    def get_layer_info(self):
        info = {}
        for ent in self.msp:
            info[ent.dxf.layer] = info.get(ent.dxf.layer, 0) + 1
        return info

    def print_layer_summary(self):
        print("\n=== 도면 레이어 정보 ===")
        for layer, count in sorted(self.get_layer_info().items()):
            print(f"  {layer}: {count}개 객체")

    def get_columns(self):
        layers = config.LAYER_NAMES['column']
        return (self.get_entities_by_layer(layers, 'CIRCLE') +
                self.get_entities_by_layer(layers, 'INSERT'))

    def get_beams(self):
        layers = (config.LAYER_NAMES.get('girder', []) +
                  config.LAYER_NAMES.get('beam',   []))
        return (self.get_entities_by_layer(layers, 'LINE') +
                self.get_entities_by_layer(layers, 'LWPOLYLINE'))

    def get_walls(self):
        layers = config.LAYER_NAMES['wall']
        return (self.get_entities_by_layer(layers, 'LINE') +
                self.get_entities_by_layer(layers, 'LWPOLYLINE'))

    # ── 유틸 ─────────────────────────────────────────────────
    @staticmethod
    def _pt_to_seg_dist(px, py, x1, y1, x2, y2):
        dx, dy = x2-x1, y2-y1
        l2 = dx*dx + dy*dy
        if l2 == 0:
            return math.hypot(px-x1, py-y1)
        t = max(0.0, min(1.0, ((px-x1)*dx + (py-y1)*dy) / l2))
        return math.hypot(px-(x1+t*dx), py-(y1+t*dy))
