"""
DXF 파일 읽기 및 기본 처리 모듈
- 보 이름 텍스트(!!0-BEAM-N, !!0-GIRDER-N) 자동 매칭 기능 추가
"""

import math
import ezdxf
from typing import List, Dict, Any, Tuple, Optional
import config


class DXFReader:
    """DXF 파일을 읽고 기본 처리를 수행하는 클래스"""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.doc  = None
        self.msp  = None
        # 보 이름 텍스트 캐시: [(text, x, y), ...]
        self._beam_name_texts: List[Dict] = []

    # ────────────────────────────────────────────────────────
    #  로드
    # ────────────────────────────────────────────────────────
    def load(self):
        """DXF 파일 로드"""
        try:
            self.doc = ezdxf.readfile(self.filepath)
            self.msp = self.doc.modelspace()
            print(f"✓ DXF 파일 로드 성공: {self.filepath}")
            # 로드 직후 보 이름 텍스트 파싱
            self._beam_name_texts = self._parse_beam_name_texts()
            print(f"  보/거더 이름 텍스트: {len(self._beam_name_texts)}개 인식")
            return True
        except IOError:
            print(f"✗ 파일을 찾을 수 없습니다: {self.filepath}")
            return False
        except ezdxf.DXFStructureError:
            print(f"✗ 잘못된 DXF 파일 형식입니다: {self.filepath}")
            return False

    # ────────────────────────────────────────────────────────
    #  보 이름 텍스트 파싱 (ezdxf 사용)
    # ────────────────────────────────────────────────────────
    def _parse_beam_name_texts(self) -> List[Dict]:
        """
        !!0-BEAM-N / !!0-GIRDER-N 레이어의 TEXT 엔티티에서
        이름 텍스트와 좌표를 추출
        """
        name_layers = getattr(config, 'LAYER_NAMES', {}).get(
            'beam_name', ['!!0-BEAM-N', '!!0-GIRDER-N', 'S-BEAM-N', 'S-GIRDER-N']
        )
        result = []
        for ent in self.msp:
            if ent.dxf.layer not in name_layers:
                continue
            if ent.dxftype() not in ('TEXT', 'MTEXT'):
                continue
            try:
                if ent.dxftype() == 'TEXT':
                    text = ent.dxf.text.strip()
                    x    = ent.dxf.insert.x
                    y    = ent.dxf.insert.y
                else:  # MTEXT
                    text = ent.plain_mtext().strip()
                    x    = ent.dxf.insert.x
                    y    = ent.dxf.insert.y
                if text:
                    result.append({'text': text, 'x': x, 'y': y,
                                   'layer': ent.dxf.layer})
            except Exception:
                continue
        return result

    # ────────────────────────────────────────────────────────
    #  이름 매칭 공개 메서드
    # ────────────────────────────────────────────────────────
    def match_beam_name(self,
                        x1: float, y1: float,
                        x2: float, y2: float,
                        max_dist: float = None) -> Optional[str]:
        """
        보 선분 (x1,y1)~(x2,y2)에 가장 가까운 이름 텍스트 반환.

        Args:
            x1,y1,x2,y2 : 보 선분 양 끝점
            max_dist     : 최대 허용 거리 (mm). None이면 config 값 사용.

        Returns:
            매칭된 이름 문자열 또는 None
        """
        if not self._beam_name_texts:
            return None

        if max_dist is None:
            max_dist = getattr(config, 'BEAM_NAME_MATCH_DIST', 3000)

        best_name = None
        best_dist = max_dist

        for t in self._beam_name_texts:
            d = self._pt_to_seg_dist(t['x'], t['y'], x1, y1, x2, y2)
            if d < best_dist:
                best_dist = d
                best_name = t['text']

        return best_name

    def get_beam_name_texts(self) -> List[Dict]:
        """파싱된 보 이름 텍스트 전체 반환 (디버깅용)"""
        return self._beam_name_texts

    # ────────────────────────────────────────────────────────
    #  기존 메서드
    # ────────────────────────────────────────────────────────
    def get_entities_by_layer(self, layer_names: List[str],
                               entity_type: str = None) -> List[Any]:
        entities = []
        for layer_name in layer_names:
            if entity_type:
                query = f'{entity_type}[layer=="{layer_name}"]'
            else:
                query = f'*[layer=="{layer_name}"]'
            entities.extend(self.msp.query(query))
        return entities

    def get_all_layers(self) -> List[str]:
        return [layer.dxf.name for layer in self.doc.layers]

    def get_layer_info(self) -> Dict[str, int]:
        layer_info = {}
        for entity in self.msp:
            layer = entity.dxf.layer
            layer_info[layer] = layer_info.get(layer, 0) + 1
        return layer_info

    def print_layer_summary(self):
        print("\n=== 도면 레이어 정보 ===")
        for layer, count in sorted(self.get_layer_info().items()):
            print(f"  {layer}: {count}개 객체")
        print()

    def get_columns(self) -> List[Any]:
        column_layers = config.LAYER_NAMES['column']
        circles = self.get_entities_by_layer(column_layers, 'CIRCLE')
        inserts = self.get_entities_by_layer(column_layers, 'INSERT')
        return circles + inserts
    
    def get_beams(self):
        """보 + 거더 엔티티 모두 가져오기"""
        girder_layers = config.LAYER_NAMES.get('girder', [])
        beam_layers   = config.LAYER_NAMES.get('beam',   [])
        all_layers    = girder_layers + beam_layers

        lines     = self.get_entities_by_layer(all_layers, 'LINE')
        polylines = self.get_entities_by_layer(all_layers, 'LWPOLYLINE')
        return lines + polylines    

    #def get_beams(self) -> List[Any]:
    #    beam_layers = config.LAYER_NAMES['beam']
    #    lines     = self.get_entities_by_layer(beam_layers, 'LINE')
    #    polylines = self.get_entities_by_layer(beam_layers, 'LWPOLYLINE')
    #    return lines + polylines

    def get_walls(self) -> List[Any]:
        wall_layers = config.LAYER_NAMES['wall']
        lines     = self.get_entities_by_layer(wall_layers, 'LINE')
        polylines = self.get_entities_by_layer(wall_layers, 'LWPOLYLINE')
        return lines + polylines

    # ────────────────────────────────────────────────────────
    #  내부 유틸
    # ────────────────────────────────────────────────────────
    @staticmethod
    def _pt_to_seg_dist(px: float, py: float,
                        x1: float, y1: float,
                        x2: float, y2: float) -> float:
        """점 (px,py)에서 선분 (x1,y1)~(x2,y2)까지 최단 거리"""
        dx, dy = x2 - x1, y2 - y1
        l2 = dx*dx + dy*dy
        if l2 == 0:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0, ((px-x1)*dx + (py-y1)*dy) / l2))
        return math.hypot(px - (x1 + t*dx), py - (y1 + t*dy))
