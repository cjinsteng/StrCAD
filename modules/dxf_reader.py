"""
DXF 파일 읽기 및 기본 처리 모듈
"""

import ezdxf
from typing import List, Dict, Any
import autocad_structure_analyzer.config as config


class DXFReader:
    """DXF 파일을 읽고 기본 처리를 수행하는 클래스"""
    
    def __init__(self, filepath: str):
        """
        Args:
            filepath: DXF 파일 경로
        """
        self.filepath = filepath
        self.doc = None
        self.msp = None
        
    def load(self):
        """DXF 파일 로드"""
        try:
            self.doc = ezdxf.readfile(self.filepath)
            self.msp = self.doc.modelspace()
            print(f"✓ DXF 파일 로드 성공: {self.filepath}")
            return True
        except IOError:
            print(f"✗ 파일을 찾을 수 없습니다: {self.filepath}")
            return False
        except ezdxf.DXFStructureError:
            print(f"✗ 잘못된 DXF 파일 형식입니다: {self.filepath}")
            return False
    
    def get_entities_by_layer(self, layer_names: List[str], entity_type: str = None) -> List[Any]:
        """
        레이어 이름으로 엔티티 검색
        
        Args:
            layer_names: 검색할 레이어 이름 리스트
            entity_type: 엔티티 타입 ('LINE', 'CIRCLE', 'LWPOLYLINE' 등)
        
        Returns:
            해당 레이어의 엔티티 리스트
        """
        entities = []
        
        for layer_name in layer_names:
            if entity_type:
                query = f'{entity_type}[layer=="{layer_name}"]'
            else:
                query = f'*[layer=="{layer_name}"]'
            
            entities.extend(self.msp.query(query))
        
        return entities
    
    def get_all_layers(self) -> List[str]:
        """도면의 모든 레이어 이름 가져오기"""
        layers = []
        for layer in self.doc.layers:
            layers.append(layer.dxf.name)
        return layers
    
    def get_layer_info(self) -> Dict[str, int]:
        """레이어별 엔티티 개수 정보"""
        layer_info = {}
        
        for entity in self.msp:
            layer = entity.dxf.layer
            if layer in layer_info:
                layer_info[layer] += 1
            else:
                layer_info[layer] = 1
        
        return layer_info
    
    def print_layer_summary(self):
        """레이어 요약 정보 출력"""
        print("\n=== 도면 레이어 정보 ===")
        layer_info = self.get_layer_info()
        
        for layer, count in sorted(layer_info.items()):
            print(f"  {layer}: {count}개 객체")
        print()
    
    def get_columns(self) -> List[Any]:
        """기둥 엔티티 가져오기 (CIRCLE 또는 INSERT)"""
        column_layers = config.LAYER_NAMES['column']
        
        circles = self.get_entities_by_layer(column_layers, 'CIRCLE')
        inserts = self.get_entities_by_layer(column_layers, 'INSERT')
        
        return circles + inserts
    
    def get_beams(self) -> List[Any]:
        """보 엔티티 가져오기 (LINE 또는 LWPOLYLINE)"""
        beam_layers = config.LAYER_NAMES['beam']
        
        lines = self.get_entities_by_layer(beam_layers, 'LINE')
        polylines = self.get_entities_by_layer(beam_layers, 'LWPOLYLINE')
        
        return lines + polylines
    
    def get_walls(self) -> List[Any]:
        """벽체 엔티티 가져오기"""
        wall_layers = config.LAYER_NAMES['wall']
        
        lines = self.get_entities_by_layer(wall_layers, 'LINE')
        polylines = self.get_entities_by_layer(wall_layers, 'LWPOLYLINE')
        
        return lines + polylines
