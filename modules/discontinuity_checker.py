"""
부재 불연속 구간 검출 모듈
"""

import math
from typing import List, Tuple, Dict
import autocad_structure_analyzer.config as config


class DiscontinuityChecker:
    """부재의 불연속 구간을 검출하는 클래스"""
    
    def __init__(self, entities: List):
        """
        Args:
            entities: 검사할 엔티티 리스트 (보, 벽체 등)
        """
        self.entities = entities
        self.endpoints = []
        self.discontinuities = []
        
    def extract_endpoints(self) -> List[Dict]:
        """모든 부재의 끝점 추출"""
        endpoints = []
        
        for i, entity in enumerate(self.entities):
            entity_id = f"E{i+1}"
            layer = entity.dxf.layer
            
            if entity.dxftype() == 'LINE':
                endpoints.append({
                    'entity_id': entity_id,
                    'entity_type': 'LINE',
                    'layer': layer,
                    'point': (entity.dxf.start.x, entity.dxf.start.y),
                    'end_type': 'start',
                    'connected_to': None
                })
                endpoints.append({
                    'entity_id': entity_id,
                    'entity_type': 'LINE',
                    'layer': layer,
                    'point': (entity.dxf.end.x, entity.dxf.end.y),
                    'end_type': 'end',
                    'connected_to': None
                })
            
            elif entity.dxftype() == 'LWPOLYLINE':
                points = list(entity.get_points())
                if points:
                    # 시작점
                    endpoints.append({
                        'entity_id': entity_id,
                        'entity_type': 'POLYLINE',
                        'layer': layer,
                        'point': (points[0][0], points[0][1]),
                        'end_type': 'start',
                        'connected_to': None
                    })
                    # 끝점
                    endpoints.append({
                        'entity_id': entity_id,
                        'entity_type': 'POLYLINE',
                        'layer': layer,
                        'point': (points[-1][0], points[-1][1]),
                        'end_type': 'end',
                        'connected_to': None
                    })
        
        self.endpoints = endpoints
        print(f"✓ 끝점 {len(endpoints)}개 추출")
        return endpoints
    
    def find_discontinuities(self) -> List[Dict]:
        """불연속 구간 찾기"""
        if not self.endpoints:
            self.extract_endpoints()
        
        tolerance = config.TOLERANCE['connection']
        discontinuities = []
        
        # 각 끝점에 대해 연결된 다른 끝점 찾기
        for i, ep1 in enumerate(self.endpoints):
            connected = False
            
            for j, ep2 in enumerate(self.endpoints):
                if i != j:  # 자기 자신은 제외
                    # 같은 엔티티의 다른 끝점은 제외
                    if ep1['entity_id'] == ep2['entity_id']:
                        continue
                    
                    dist = self._distance(ep1['point'], ep2['point'])
                    
                    if dist <= tolerance:
                        connected = True
                        self.endpoints[i]['connected_to'] = ep2['entity_id']
                        break
            
            # 연결되지 않은 끝점
            if not connected:
                discontinuities.append({
                    'entity_id': ep1['entity_id'],
                    'entity_type': ep1['entity_type'],
                    'layer': ep1['layer'],
                    'position': ep1['point'],
                    'end_type': ep1['end_type'],
                    'x': ep1['point'][0],
                    'y': ep1['point'][1]
                })
        
        self.discontinuities = discontinuities
        print(f"✓ 불연속 구간 {len(discontinuities)}개 발견")
        return discontinuities
    
    def group_by_layer(self) -> Dict[str, List[Dict]]:
        """레이어별로 불연속 구간 그룹화"""
        if not self.discontinuities:
            self.find_discontinuities()
        
        grouped = {}
        for disc in self.discontinuities:
            layer = disc['layer']
            if layer not in grouped:
                grouped[layer] = []
            grouped[layer].append(disc)
        
        return grouped
    
    def find_nearby_discontinuities(self, max_distance: float = 1000) -> List[Dict]:
        """
        가까이 있는 불연속 구간 쌍 찾기 (연결 가능성 있는 구간)
        
        Args:
            max_distance: 최대 거리 (mm)
        
        Returns:
            가까운 불연속 구간 쌍 리스트
        """
        if not self.discontinuities:
            self.find_discontinuities()
        
        nearby_pairs = []
        n = len(self.discontinuities)
        
        for i in range(n):
            for j in range(i + 1, n):
                disc1 = self.discontinuities[i]
                disc2 = self.discontinuities[j]
                
                # 같은 레이어만 검사
                if disc1['layer'] == disc2['layer']:
                    dist = self._distance(disc1['position'], disc2['position'])
                    
                    if dist <= max_distance:
                        nearby_pairs.append({
                            'discontinuity1': disc1,
                            'discontinuity2': disc2,
                            'distance': dist,
                            'layer': disc1['layer']
                        })
        
        # 거리순 정렬
        nearby_pairs.sort(key=lambda x: x['distance'])
        return nearby_pairs
    
    def check_alignment(self, disc1: Dict, disc2: Dict, angle_tolerance: float = 5.0) -> bool:
        """
        두 불연속 구간이 직선상에 있는지 확인
        
        Args:
            disc1, disc2: 불연속 구간 정보
            angle_tolerance: 각도 허용 오차 (도)
        
        Returns:
            직선상에 있으면 True
        """
        # 간단한 구현: X축 또는 Y축과 평행한지만 확인
        dx = abs(disc2['x'] - disc1['x'])
        dy = abs(disc2['y'] - disc1['y'])
        
        # X축 평행
        if dy < dx * math.tan(math.radians(angle_tolerance)):
            return True
        # Y축 평행
        if dx < dy * math.tan(math.radians(angle_tolerance)):
            return True
        
        return False
    
    @staticmethod
    def _distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """두 점 사이의 거리"""
        return math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
    
    def get_summary(self) -> Dict:
        """불연속 구간 분석 요약"""
        if not self.discontinuities:
            self.find_discontinuities()
        
        by_layer = self.group_by_layer()
        nearby = self.find_nearby_discontinuities()
        
        return {
            'total_discontinuities': len(self.discontinuities),
            'discontinuities_by_layer': {layer: len(discs) for layer, discs in by_layer.items()},
            'nearby_pairs_count': len(nearby),
            'total_endpoints': len(self.endpoints)
        }
