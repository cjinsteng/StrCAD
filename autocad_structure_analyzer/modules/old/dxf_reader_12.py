"""
DXF 파일 읽기 및 기본 처리 모듈
- 보 이름 텍스트 정밀 매칭: 레이어 계열 우선 + 중점 거리 가중치
- 기둥: LWPOLYLINE 폴리곤 + 형태 추론(4각형·비율) 지원
- 벽:   LINE + LWPOLYLINE 모두 지원, 마감 레이어 포함
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
        self._beam_name_texts: List[Dict] = []
        # 기둥·벽 원시 데이터 캐시 (dict 형태)
        self._column_shapes: List[Dict] = []
        self._wall_shapes:   List[Dict] = []

    def load(self):
        try:
            self.doc = ezdxf.readfile(self.filepath)
            self.msp = self.doc.modelspace()
            print(f"✓ DXF 파일 로드 성공: {self.filepath}")
            self._beam_name_texts = self._parse_beam_name_texts()
            print(f"  보/거더 이름 텍스트: {len(self._beam_name_texts)}개 인식")
            # 기둥·벽 형상 미리 파싱
            self._column_shapes, self._wall_shapes = self._parse_column_wall_shapes()
            print(f"  기둥 폴리곤: {len(self._column_shapes)}개 / 벽 요소: {len(self._wall_shapes)}개 인식")
            return True
        except IOError:
            print(f"✗ 파일을 찾을 수 없습니다: {self.filepath}")
            return False
        except ezdxf.DXFStructureError:
            print(f"✗ 잘못된 DXF 파일 형식: {self.filepath}")
            return False

    # ════════════════════════════════════════════════════════
    #  기둥 · 벽 형상 파싱  (ezdxf 기반)
    # ════════════════════════════════════════════════════════
    def _parse_column_wall_shapes(self):
        """
        기둥: LWPOLYLINE (명시 레이어 + 형태 추론)
        벽:   LINE + LWPOLYLINE (명시 레이어)

        반환값: (column_shapes, wall_shapes)
          각 요소는 dict:
            { 'type': 'polygon'|'line',
              'coords': [(x,y), ...],
              'layer': str,
              'source': 'explicit'|'shape_inferred' }
        """
        col_layers     = set(config.LAYER_NAMES.get('column', []))
        wall_layers    = set(config.LAYER_NAMES.get('wall', []))
        finish_layers  = set(config.LAYER_NAMES.get('column_finishes', []))

        col_shapes  = []
        wall_shapes = []

        shape_cfg = getattr(config, 'COLUMN_SHAPE', {})
        max_vert   = shape_cfg.get('max_vertices',    6)
        max_ratio  = shape_cfg.get('max_aspect_ratio', 4.5)
        min_size   = shape_cfg.get('min_size',         200)

        for ent in self.msp:
            layer = ent.dxf.layer

            # ── LWPOLYLINE ──────────────────────────────────
            if ent.dxftype() == 'LWPOLYLINE':
                try:
                    pts = [(p[0], p[1]) for p in ent.get_points()]
                except Exception:
                    continue
                if len(pts) < 2:
                    continue

                closed = bool(ent.dxf.flags & 1) if ent.dxf.hasattr('flags') else False
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                w  = max(xs) - min(xs);   h  = max(ys) - min(ys)
                ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 999

                if layer in col_layers:
                    col_shapes.append({
                        'type': 'polygon', 'coords': pts,
                        'closed': closed, 'layer': layer,
                        'source': 'explicit',
                    })
                elif layer in wall_layers:
                    wall_shapes.append({
                        'type': 'polygon', 'coords': pts,
                        'closed': closed, 'layer': layer,
                        'source': 'explicit',
                    })
                elif layer in finish_layers and closed:
                    # 마감 레이어: 형태로 기둥/벽 구분
                    if (len(pts) <= max_vert and ratio <= max_ratio
                            and max(w, h) >= min_size):
                        col_shapes.append({
                            'type': 'polygon', 'coords': pts,
                            'closed': closed, 'layer': layer,
                            'source': 'shape_inferred',
                        })
                    else:
                        wall_shapes.append({
                            'type': 'polygon', 'coords': pts,
                            'closed': closed, 'layer': layer,
                            'source': 'shape_inferred',
                        })

            # ── LINE ────────────────────────────────────────
            elif ent.dxftype() == 'LINE':
                try:
                    x1, y1 = ent.dxf.start.x, ent.dxf.start.y
                    x2, y2 = ent.dxf.end.x,   ent.dxf.end.y
                except Exception:
                    continue

                if layer in wall_layers:
                    wall_shapes.append({
                        'type': 'line',
                        'coords': [(x1, y1), (x2, y2)],
                        'layer': layer,
                        'source': 'explicit',
                    })
                elif layer in col_layers:
                    # 기둥 레이어의 LINE은 기둥 윤곽선 (짧은 노이즈 제외)
                    if math.hypot(x2 - x1, y2 - y1) >= min_size:
                        col_shapes.append({
                            'type': 'line',
                            'coords': [(x1, y1), (x2, y2)],
                            'layer': layer,
                            'source': 'explicit',
                        })

        return col_shapes, wall_shapes

    # ── 외부 접근용 ──────────────────────────────────────────
    def get_column_shapes(self) -> List[Dict]:
        """기둥 형상 리스트 반환 (dict: type/coords/layer/source)"""
        return self._column_shapes

    def get_wall_shapes(self) -> List[Dict]:
        """벽체 형상 리스트 반환 (dict: type/coords/layer/source)"""
        return self._wall_shapes

    # ════════════════════════════════════════════════════════
    #  이름 텍스트 파싱
    # ════════════════════════════════════════════════════════
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
                        'family': _layer_family(ent.dxf.layer),
                    })
            except Exception:
                continue
        return result

    # ════════════════════════════════════════════════════════
    #  정밀 이름 매칭
    # ════════════════════════════════════════════════════════
    def match_beam_name(self,
                        x1: float, y1: float,
                        x2: float, y2: float,
                        beam_layer: str = '',
                        max_dist: float = None) -> Optional[str]:
        if not self._beam_name_texts:
            return None

        max_d = max_dist or getattr(config, 'BEAM_NAME_MATCH_DIST', 3000)
        my_family = _layer_family(beam_layer)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2

        best_name  = None
        best_score = float('inf')

        for t in self._beam_name_texts:
            d_seg = self._pt_to_seg_dist(t['x'], t['y'], x1, y1, x2, y2)
            if d_seg > max_d:
                continue
            d_mid = math.hypot(t['x'] - mx, t['y'] - my)
            family_penalty = 0
            if my_family and t['family'] and t['family'] != my_family:
                family_penalty = max_d * 0.8
            score = d_seg + d_mid * 0.3 + family_penalty
            if score < best_score:
                best_score = score
                best_name  = t['text']

        return best_name

    def get_beam_name_texts(self) -> List[Dict]:
        return self._beam_name_texts

    # ════════════════════════════════════════════════════════
    #  기존 메서드 (빔/기둥 엔티티 리스트 — 분석 모듈용)
    # ════════════════════════════════════════════════════════
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
