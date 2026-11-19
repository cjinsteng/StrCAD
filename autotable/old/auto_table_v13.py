"""
Auto Table v1.3  —  보/기둥/슬래브/벽 배근표 자동 작성 및 CAD 출력
autotable/ 폴더 내 모듈  (launcher.py 에서 open_auto_table() 호출)

수정 버그:
  - DXF: CRLF + 완전한 헤더 (BLOCKS 섹션 포함)
  - SmartEntry: _writing 플래그로 set() 재귀 방지
  - SmartEntry: stirrup 타이머 안정화
  - _do_nav: 위젯 참조를 rv에 직접 저장 (winfo_children 인덱스 문제 제거)
  - Alt/Shift+Return: 플랫폼 호환 바인딩
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import re

# ── 팔레트 ─────────────────────────────────────────────────
BG   = "#0f1520"; BG2  = "#141d2e"; BG3  = "#1a2540"
BG4  = "#1f2d4a"; BDR  = "#2c3f62"; BDR2 = "#3a5280"
ACC  = "#1a56db"; ACCH = "#2563eb"; GRN  = "#15803d"
RED  = "#dc2626"; TXT  = "#dde4f0"; TX2  = "#8fa3c0"
TX3  = "#546887"; WHI  = "#f0f5ff"

MEMBER_TYPES = ["보(Beam)", "기둥(Column)", "슬래브(Slab)", "벽(Wall)"]
PREFIXES     = ["HD", "SHD", "UHD"]

# ── 열 정의 ────────────────────────────────────────────────
# type: None=plain Entry, "rebar"=SmartEntry, "stirrup"=SmartEntry,
#       "check"=Checkbutton(특수), "btn"=Button(특수)
COL_DEFS = [
    ("부재명",          8,  "name",       None),
    ("폭\n(mm)",        5,  "width",      None),
    ("깊이\n(mm)",      5,  "depth",      None),
    ("단부(i)\n상부근", 10, "em_top",     "rebar"),
    ("단부(i)\n하부근", 10, "em_bot",     "rebar"),
    ("단부(i)\n스터럽", 10, "em_stir",    "stirrup"),
    ("중앙부\ncheck",   5,  "cen_use",    "check"),   # ★ 체크박스
    ("중앙부\n상부근",  10, "cen_top",    "rebar"),
    ("중앙부\n하부근",  10, "cen_bot",    "rebar"),
    ("중앙부\n스터럽",  10, "cen_stir",   "stirrup"),
    ("단부(j)\ncheck",  5,  "ev_use",     "check"),   # ★ 체크박스
    ("단부(j)\n상부근", 10, "ev_top",     "rebar"),
    ("단부(j)\n하부근", 10, "ev_bot",     "rebar"),
    ("단부(j)\n스터럽", 10, "ev_stir",    "stirrup"),
    ("설계",            5,  "design",     "btn"),     # ★ 설계 버튼
]
COL_KEYS = [c[2] for c in COL_DEFS]

# 체크박스 열 키 목록 (활성/비활성 그룹 매핑)
CHECK_GROUPS = {
    "cen_use":  ["cen_top", "cen_bot", "cen_stir"],
    "ev_use":   ["ev_top",  "ev_bot",  "ev_stir"],
}

DEFAULTS = {
    "name":    "B1",
    "width":   "400",
    "depth":   "600",
    "em_top":  "3-UHD22",  "em_bot":  "3-UHD22",  "em_stir":  "HD10@300",
    "cen_use": True,        # 체크박스 기본값
    "cen_top": "3-UHD22",  "cen_bot": "3-UHD22",  "cen_stir": "HD10@300",
    "ev_use":  True,        # 체크박스 기본값
    "ev_top":  "3-UHD22",  "ev_bot":  "3-UHD22",  "ev_stir":  "HD10@300",
}


# ══════════════════════════════════════════════════════════════
#  DXF Writer  (CRLF + 완전한 헤더)
# ══════════════════════════════════════════════════════════════
class DXFWriter:
    """
    원본 beamA4.dxf의 HEADER+TABLES+BLOCKS를 그대로 사용하고
    ENTITIES 섹션만 새로 생성 → CAD 완전 호환
    
    원본 파일이 없을 때는 최소 DXF 직접 생성 (폴백)
    """
    SCALE = 83.333
    OX    = 0.0   # 새 beamA4_sheet.dxf 좌표계 (오프셋 없음)
    OY    = 0.0

    # 원본 DXF 경로 (이 파일 기준 상대경로)
    _TEMPLATE = None  # 런타임에 설정

    def __init__(self, pw=210, ph=297):
        self._e   = []
        self.pw   = pw
        self.ph   = ph

    def _px(self, mm): return self.OX + mm * self.SCALE
    def _py(self, mm): return self.OY + mm * self.SCALE
    def _u(self,  mm): return mm * self.SCALE

    def line(self, x1, y1, x2, y2, layer="0", lw=-3):
        self._e.append(("L", layer,
                        self._px(x1), self._py(y1),
                        self._px(x2), self._py(y2), lw))

    def rect(self, x, y, w, h, layer="0", lw=-3):
        self.line(x,   y,   x+w, y,   layer, lw)
        self.line(x+w, y,   x+w, y+h, layer, lw)
        self.line(x+w, y+h, x,   y+h, layer, lw)
        self.line(x,   y+h, x,   y,   layer, lw)

    def text(self, x, y, s, hmm=2.5, layer="0", color=256, halign=0):
        self._e.append(("T", layer,
                        self._px(x), self._py(y),
                        str(s), self._u(hmm), halign, color))

    def circle(self, cx, cy, rmm, layer="0", color=256):
        self._e.append(("C", layer,
                        self._px(cx), self._py(cy),
                        self._u(rmm), color))

    def save(self, path):
        """원본 DXF 템플릿의 HEADER/TABLES/BLOCKS + 새 ENTITIES 합성 저장"""
        # ── ENTITIES 바이트 생성 ─────────────────────────────
        ent_lines = []
        def g(code, val):
            ent_lines.append(f"{int(code):>3}\r\n{val}")

        g(0,"SECTION"); g(2,"ENTITIES")
        h = 0x8000
        for ent in self._e:
            t = ent[0]
            if t == "L":
                _, ly, x1,y1,x2,y2,lw = ent
                g(0,"LINE"); g(5,f"{h:X}"); g(330,"2")
                g(100,"AcDbEntity"); g(8,ly); g(370,lw)
                g(100,"AcDbLine")
                g(10,f"{x1:.4f}"); g(20,f"{y1:.4f}"); g(30,"0.0")
                g(11,f"{x2:.4f}"); g(21,f"{y2:.4f}"); g(31,"0.0")
            elif t == "T":
                _, ly, x, y, s, h2, ha, col = ent
                g(0,"TEXT"); g(5,f"{h:X}"); g(330,"2")
                g(100,"AcDbEntity"); g(8,ly)
                if col != 256: g(62,col)
                g(100,"AcDbText")
                g(10,f"{x:.4f}"); g(20,f"{y:.4f}"); g(30,"0.0")
                g(40,f"{h2:.4f}"); g(1,s); g(7,"12")
                g(72, ha if ha else 0)
                if ha:
                    g(11,f"{x:.4f}"); g(21,f"{y:.4f}"); g(31,"0.0")
                g(100,"AcDbText")
            elif t == "C":
                _, ly, cx, cy, r, col = ent
                g(0,"CIRCLE"); g(5,f"{h:X}"); g(330,"2")
                g(100,"AcDbEntity"); g(8,ly)
                if col != 256: g(62,col)
                g(100,"AcDbCircle")
                g(10,f"{cx:.4f}"); g(20,f"{cy:.4f}"); g(30,"0.0")
                g(40,f"{r:.4f}")
            h += 1
        g(0,"ENDSEC")
        g(0,"EOF")

        entities_bytes = ("\r\n".join(ent_lines) + "\r\n").encode("cp949", "replace")

        # ── 원본 템플릿에서 HEADER+TABLES+BLOCKS 추출 ──────────
        tpl = self._find_template()
        if tpl:
            try:
                raw = open(tpl, "rb").read()
                # ENTITIES 섹션 시작
                ent_sec_start = raw.find(b"  0\r\nSECTION\r\n  2\r\nENTITIES\r\n")
                if ent_sec_start < 0:
                    raise ValueError("ENTITIES 섹션 없음")
                # ENTITIES 섹션의 ENDSEC 위치
                pos = ent_sec_start
                while True:
                    p = raw.find(b"  0\r\nENDSEC\r\n", pos)
                    if p < 0: raise ValueError("ENDSEC 없음")
                    if p > ent_sec_start: break
                    pos = p + 1
                ent_endsec_end = p + len(b"  0\r\nENDSEC\r\n")
                # 세 부분 합성:
                #   header_bytes  = HEADER + CLASSES + TABLES + BLOCKS
                #   entities_bytes = 우리가 생성한 ENTITIES
                #   objects_bytes  = 원본 OBJECTS + EOF
                header_bytes  = raw[:ent_sec_start]
                objects_bytes = raw[ent_endsec_end:]
                with open(path, "wb") as f:
                    f.write(header_bytes)
                    f.write(entities_bytes)
                    f.write(objects_bytes)
                return
            except Exception:
                pass

        # ── 폴백: 최소 DXF 직접 생성 ────────────────────────────
        self._save_minimal(path, entities_bytes)

    def _find_template(self):
        """beamA4.dxf 원본 파일을 프로젝트 폴더에서 탐색"""
        import os
        # 이 py 파일 위치 기준으로 탐색
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "beamA4.dxf"),
            os.path.join(here, "..", "beamA4.dxf"),
            os.path.join(here, "templates", "beamA4.dxf"),
        ]
        # 클래스 변수로 지정된 경우
        if DXFWriter._TEMPLATE and os.path.isfile(DXFWriter._TEMPLATE):
            return DXFWriter._TEMPLATE
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    def _save_minimal(self, path, entities_bytes):
        """원본 템플릿 없을 때 최소 DXF 생성 (CP949, CRLF)"""
        lines = []
        def g(code, val):
            lines.append(f"{int(code):>3}\r\n{val}")

        ex = self._px(self.pw); ey = self._py(self.ph)
        ox = self._px(0);       oy = self._py(0)

        g(0,"SECTION"); g(2,"HEADER")#HEADER섹션시작
        g(9,"$ACADVER");     g(1,"AC1015")#AUTOCAD버젼지정, #AUTOCAD2000DXF포멧
        g(9,"$DWGCODEPAGE"); g(3,"ANSI_949")#한글인코딩설정, 한글
        g(9,"$INSBASE");     g(10,"0.0"); g(20,"0.0"); g(30,"0.0")#기준점설정, 10>X, 20>Y, 30>Z
        g(9,"$EXTMIN");      g(10,f"{ox:.4f}"); g(20,f"{oy:.4f}"); g(30,"0.0")#도면최소좌표, 소수점4자리까지
        g(9,"$EXTMAX");      g(10,f"{ex:.4f}"); g(20,f"{ey:.4f}"); g(30,"0.0")
        g(9,"$LIMMIN");      g(10,"0.0"); g(20,"0.0")#작업영역 최소값
        g(9,"$LIMMAX");      g(10,"297.0"); g(20,"210.0")#도면작업크기
        g(9,"$LTSCALE");     g(40,"50.0")#점섬쇄선배율, 숫자클수록 패턴간격 커짐
        g(9,"$TEXTSIZE");    g(40,"40.0")#문자크기
        g(9,"$TEXTSTYLE");   g(7,"12")#문자스타일
        g(9,"$CLAYER");      g(8,"0")#현재레이어, 8=레이어이름
        g(9,"$CELTYPE");     g(6,"BYLAYER")#선스타일
        g(9,"$CECOLOR");     g(62,256)#현재색상
        g(9,"$DIMSCALE");    g(40,"1.0")#치수스케일
        g(9,"$DIMSTYLE");    g(2,"STANDARD")#치수스타일
        g(9,"$INSUNITS");    g(70,4)#단위설정 4=mm임
        g(9,"$MEASUREMENT"); g(70,1)#각도단위, 1=Matric, 0=Imperial
        g(9,"$CELWEIGHT");   g(370,-1)#선가중치 -1=BYLAYER
        g(9,"$LWDISPLAY");   g(290,0)#선두께 
        g(9,"$TILEMODE");    g(70,1)#1=Model Space사용, 0=Paper Space사용
        g(0,"ENDSEC")#HEACER종료

        g(0,"SECTION"); g(2,"TABLES")#Table센션시작
        g(0,"TABLE"); g(2,"LTYPE"); g(5,"5"); g(330,"0")#선타입테이블
        g(100,"AcDbSymbolTable"); g(70,1)#데이터베이스
        g(0,"LTYPE"); g(5,"14"); g(330,"5")
        g(100,"AcDbSymbolTableRecord"); g(100,"AcDbLinetypeTableRecord")
        g(2,"CONTINUOUS"); g(70,0); g(3,"Solid line"); g(72,65); g(73,0); g(40,"0.0")
        g(0,"ENDTABLE")
        g(0,"TABLE"); g(2,"STYLE"); g(5,"15"); g(330,"0")
        g(100,"AcDbSymbolTable"); g(70,2)
        g(0,"STYLE"); g(5,"52E"); g(330,"15")
        g(100,"AcDbSymbolTableRecord"); g(100,"AcDbTextStyleTableRecord")
        g(2,"12"); g(70,0); g(40,"0.0"); g(41,"1.0"); g(50,"0.0"); g(71,0); g(42,"2.5")
        g(3,"malgun.ttf")
        g(0,"STYLE"); g(5,"16"); g(330,"15")
        g(100,"AcDbSymbolTableRecord"); g(100,"AcDbTextStyleTableRecord")
        g(2,"STANDARD"); g(70,0); g(40,"0.0"); g(41,"1.0"); g(50,"0.0"); g(71,0); g(42,"2.5")
        g(3,"txt.shx")
        g(0,"ENDTABLE")
        layer_list=[("0",7,"6"),("2",2,"3A"),("DIM",7,"3D"),("TEXT",3,"46"),("edit",1,"47")]
        g(0,"TABLE"); g(2,"LAYER"); g(5,"14"); g(330,"0")
        g(100,"AcDbSymbolTable"); g(70,len(layer_list))
        for lname,cidx,hdl in layer_list:
            g(0,"LAYER"); g(5,hdl); g(330,"14")
            g(100,"AcDbSymbolTableRecord"); g(100,"AcDbLayerTableRecord")
            g(2,lname); g(70,0); g(62,cidx); g(6,"CONTINUOUS"); g(370,-3); g(390,7)
        g(0,"ENDTABLE")
        g(0,"TABLE"); g(2,"DIMSTYLE"); g(5,"A"); g(330,"0")
        g(100,"AcDbSymbolTable"); g(70,1)
        g(0,"DIMSTYLE"); g(5,"27"); g(330,"A")
        g(100,"AcDbSymbolTableRecord"); g(100,"AcDbDimStyleTableRecord")
        g(2,"STANDARD"); g(70,0); g(40,"1.0"); g(41,"50.0"); g(140,"40.0"); g(147,"20.0")
        g(0,"ENDTABLE")
        g(0,"ENDSEC")

        g(0,"SECTION"); g(2,"BLOCKS")
        g(0,"BLOCK"); g(5,"5"); g(330,"2")
        g(100,"AcDbEntity"); g(8,"0"); g(100,"AcDbBlockBegin")
        g(2,"*MODEL_SPACE"); g(70,0); g(10,"0.0"); g(20,"0.0"); g(30,"0.0")
        g(3,"*MODEL_SPACE")
        g(0,"ENDBLK"); g(5,"B"); g(330,"2")
        g(100,"AcDbEntity"); g(8,"0"); g(100,"AcDbBlockEnd")
        g(0,"ENDSEC")

        header_bytes = ("\r\n".join(lines) + "\r\n").encode("cp949", "replace")
        with open(path, "wb") as f:
            f.write(header_bytes)
            f.write(entities_bytes)


# ══════════════════════════════════════════════════════════════
#  배근표 그리기  ─── Sheet 템플릿 완전 기반
# ══════════════════════════════════════════════════════════════
import os as _os

# ── 파싱 유틸 ─────────────────────────────────────────────────
def _sr(s):
    """'3-UHD22' → (3, 'UHD', '22'),  실패 → (0,'','')"""
    m = re.match(r"(\d+)[-\s]*([A-Za-z]+)\s*(\d+)", (s or "").strip())
    if m: return int(m.group(1)), m.group(2).upper(), m.group(3)
    return 0, "", ""

def _ss(s):
    """'HD10@300' → ('HD','10','300'),  실패 → ('','','')"""
    m = re.match(r"([A-Za-z]*)\s*(\d+)[@\s]+(\d+)", (s or "").strip())
    if m: return m.group(1).upper(), m.group(2), m.group(3)
    return "", "", ""

def _rebar_xs(n, xl, xr):
    """n개 철근 x 위치 목록"""
    if n <= 0: return []
    if n == 1: return [(xl+xr)/2]
    return [xl + i*(xr-xl)/(n-1) for i in range(n)]

# ── MOD 셀 로컬 좌표 상수 (업로드된 파일 직접 측정값) ──────────────
# 셀 크기: 12.960 × 12.300 mm  (원점 = 셀 좌하단)
_CW, _CH = 12.960, 12.300

# 단면 박스 (로컬 mm)
_SX1, _SY1 = 3.372, 3.544   # 좌하
_SX2, _SY2 = 6.732, 7.744   # 우상

# 피복 박스 (layer=2, 노란색)
_CV_LX, _CV_RX = 3.612, 6.492
_CV_BY, _CV_TY = 3.784, 8.704

# 철근 원
_RXL, _RXR = 3.732, 6.372
_RYT = 8.584   # 상부 y
_RYB = 3.904   # 하부 y
_RRADII = [0.012, 0.048, 0.084, 0.120]

# 스터럽 (layer=H)
_SL, _SR = 2.172, 7.932   # 수직선 x
_SYB, _SYT = 7.294, 9.394  # 수직선 y 범위
_SYH = 8.944               # 수평 연결선 y

# 텍스트 위치 (로컬 mm), 높이 0.480mm
_TH = 0.480
_T_STR   = (7.292, 5.855)   # "Str. HD    @"
_T_BOT_L = (8.914, 3.771)   # "-           (B)"
_T_TOP_L = (8.914, 8.462)   # "-           (T)"
_T_TOP_N = (8.457, 8.403)   # 상부 철근 개수
_T_TOP_S = (9.353, 8.403)   # 상부 철근 규격
_T_BOT_N = (8.457, 3.714)   # 하부 철근 개수
_T_BOT_S = (9.353, 3.714)   # 하부 철근 규격
_T_STIR  = (9.592, 5.855)   # 스터럽 값
_T_BW    = (4.516, 2.112)   # 보 폭
_T_BH    = (0.935, 5.621)   # 보 높이 (ang=90)

# 치수선 (layer=DIM, color=7)
_DIM_H_WY1, _DIM_H_WY2 = 2.679, 1.956  # 수평 치수선 witness y
_DIM_H_Y = 1.958                         # 치수선 y
_DIM_V_WX1, _DIM_V_WX2 = 1.606, 1.064  # 수직 치수선 witness x
_DIM_V_X = 1.066                         # 치수선 x

# SHEET 격자 (절대 mm, SHEET 파일 정밀 측정)
#_COLS_X  = [762.7235, 775.6836, 788.6436]                          # END_M, CENTER, END_V 좌하단 x
#_ROWS_Y  = [1021.8033, 1007.7033, 993.6032, 965.3917]             # 행1~4 좌하단 y
#_NAME_X  = 760.800
#_NAME_YC = [1027.9534, 1013.8533, 999.7532, 971.5417]             # 행별 보이름 TEXT y 중심

_COLS_X  = [762.7235-755.0273, 775.6836-755.0273, 788.6436-755.0273]                          # END_M, CENTER, END_V 좌하단 x
_ROWS_Y  = [1021.8033-976.8631, 1007.7033-976.8631, 993.6032-976.8631, 979.5031-976.8631]             # 행1~4 좌하단 y
_NAME_X  = 760.800-755.0273
_NAME_YC = [1027.9534-976.8631, 1013.8533-976.8631, 999.7532-976.8631, 985.6532-976.8631]             # 행별 보이름 TEXT y 중심

# 시트 당 보 개수, 시트 간 X 간격
_ROWS_PER_SHEET = 4
_SHEET_DX       = 48.016356  # 4001.3470 DXF raw / 83.333 (시트 오른쪽 끝점 기준)

# SHEET 핸들 최대값(0xCA72) + 여유
_HANDLE_START = 0xDB00


def _rebar_xs(n, xl, xr):
    if n <= 0: return []
    if n == 1: return [(xl+xr)/2]
    return [xl + i*(xr-xl)/(n-1) for i in range(n)]


def _cell_entities(cell_ox, cell_oy, bw, bh, top_rb, bot_rb, stir, hcnt):
    """
    MOD 템플릿을 cell_ox, cell_oy(절대mm 좌하단)에 배치한
    DXF 엔티티 텍스트 목록을 반환.
    bw, bh: 보 폭/높이(mm) - 값만 텍스트로 표시
    hcnt: [int] 전역 핸들 카운터
    """
    S  = 83.333
    OX = DXFWriter.OX
    OY = DXFWriter.OY

    out = []

    def hdl():
        v = hcnt[0]; hcnt[0] += 1; return f"{v:X}"

    def p(c, v):
        out.append(f"{int(c):>3}\r\n{v}")

    def X(lx): return f"{OX + (cell_ox + lx) * S:.4f}"
    def Y(ly): return f"{OY + (cell_oy + ly) * S:.4f}"
    def U(mm): return f"{mm * S:.4f}"

    def line(x1, y1, x2, y2, layer="0", color=256, lw=-2):
        p(0,"LINE"); p(5,hdl()); p(330,"2")
        p(100,"AcDbEntity"); p(8,layer)
        if color != 256: p(62, color)
        if lw != -2: p(370, lw)
        p(100,"AcDbLine")
        p(10,X(x1)); p(20,Y(y1)); p(30,"0.0")
        p(11,X(x2)); p(21,Y(y2)); p(31,"0.0")

    def circle(cx, cy, r, layer="0", color=256):
        p(0,"CIRCLE"); p(5,hdl()); p(330,"2")
        p(100,"AcDbEntity"); p(8,layer)
        if color != 256: p(62, color)
        p(100,"AcDbCircle")
        p(10,X(cx)); p(20,Y(cy)); p(30,"0.0")
        p(40,U(r))

    def lwpoly(verts, layer="0", color=256, closed=1, lw=0.0):
        p(0,"LWPOLYLINE"); p(5,hdl()); p(330,"2")
        p(100,"AcDbEntity"); p(8,layer)
        if color != 256: p(62, color)
        p(100,"AcDbPolyline")
        p(90, len(verts)); p(70, closed); p(43, f"{lw:.1f}")
        for vx, vy in verts:
            p(10,X(vx)); p(20,Y(vy))

    def text(lx, ly, txt, layer="TEXT", color=256, ang=0):
        if not str(txt).strip(): return
        p(0,"TEXT"); p(5,hdl()); p(330,"2")
        p(100,"AcDbEntity"); p(8,layer)
        if color != 256: p(62, color)
        p(100,"AcDbText")
        p(10,X(lx)); p(20,Y(ly)); p(30,"0.0")
        p(40,U(_TH)); p(1,str(txt)); p(7,"12")
        if ang: p(50,f"{ang:.1f}")
        p(100,"AcDbText")   # 두번째 AcDbText 빈 블록 필수

    def insert(blk, ix, iy, sx, sy, ang, layer="DIM", color=7):
        p(0,"INSERT"); p(5,hdl()); p(330,"2")
        p(100,"AcDbEntity"); p(8,layer)
        if color != 256: p(62, color)
        p(100,"AcDbBlockReference")
        p(2,blk)
        p(10,X(ix)); p(20,Y(iy)); p(30,"0.0")
        p(41,f"{sx:.4f}"); p(42,f"{sy:.4f}"); p(43,f"{sy:.4f}")
        if ang: p(50,f"{ang:.2f}")

    # ══ MOD v2 파일 1:1 재현 ══════════════════════════════════════
    # 모든 좌표는 beamA4_mod.dxf 직접 측정값

    # ── 피복 박스 (layer=2) ───────────────────────────────────────
    # MOD 측정: (3.6122, 3.7840)~(6.4922, 8.7040)
    lwpoly([(3.6122, 8.7040),(6.4922, 8.7040),
            (6.4922, 3.7840),(3.6122, 3.7840)], layer="2", closed=1)

    # ── 단면 박스 4선 + 스터럽 연결선 ──────────────────────────────
    # 단면: (3.3722,3.5440)~(6.7322,7.7440)
    line(3.3722, 3.5440, 6.7322, 3.5440)          # 하단
    line(6.7322, 3.5440, 6.7322, 7.7440)          # 우측
    #line(6.7322, 7.7440, 3.3722, 7.7440)          # 상단
    line(3.3722, 7.7440, 3.3722, 3.5440)          # 좌측

    # 단면 우상→스터럽 우 연결
    line(6.7322, 7.7440, 7.9322, 7.7440)
    # 스터럽 좌→단면 좌상 연결
    line(2.1722, 7.7440, 3.3722, 7.7440)
    # 스터럽 상단 수평선
    line(2.1722, 8.9440, 7.9322, 8.9440)

    # ── 스터럽 수직선 (layer=H) ──────────────────────────────────
    line(7.9322, 9.3940, 7.9322, 7.2940, layer="H")   # 우측
    line(2.1722, 9.3940, 2.1722, 7.2940, layer="H")   # 좌측

    # ── 철근 원 ──────────────────────────────────────────────────
    tn, tpfx, tsz = _sr(top_rb)
    _rx_top = _rebar_xs(max(tn, 1), 3.7322, 6.3722)
    for rx in _rx_top:
        for r in _RRADII:
            circle(rx, 8.5840, r)

    bn, bpfx, bsz = _sr(bot_rb)
    _rx_bot = _rebar_xs(max(bn, 1), 3.7322, 6.3722)
    for rx in _rx_bot:
        for r in _RRADII:
            circle(rx, 3.9040, r)

    # ── 수평 치수선 (보 폭) ──────────────────────────────────────
    _dot_s = 50.0
    line(3.3722, 2.6783, 3.3722, 1.9560, "DIM", 7)    # witness 좌
    line(6.7322, 2.6783, 6.7322, 1.9560, "DIM", 7)    # witness 우
    line(3.3722, 1.9582, 6.7322, 1.9582, "DIM", 7)    # 치수선
    insert("_DOTSMALL", 3.3722, 1.9582, _dot_s, _dot_s, 180.0)
    insert("_DOTSMALL", 6.7322, 1.9582, _dot_s, _dot_s, 0.0)

    # ── 수직 치수선 (보 높이) ────────────────────────────────────
    line(1.6063, 3.5440, 1.0640, 3.5440, "DIM", 7)    # witness 하
    line(1.6063, 8.9440, 1.0640, 8.9440, "DIM", 7)    # witness 상
    line(1.0662, 3.5440, 1.0662, 8.9440, "DIM", 7)    # 치수선
    insert("_DOTSMALL", 1.0662, 3.5440, _dot_s, _dot_s, 270.0)
    insert("_DOTSMALL", 1.0662, 8.9440, _dot_s, _dot_s, 90.0)

    # ── 고정 레이블 텍스트 (TEXT 레이어) ──────────────────────────
    text(7.2922, 5.8550, "Str. HD    @",    "TEXT")
    text(8.9140, 3.7116, "-           (B)", "TEXT")
    text(8.9140, 8.4627, "-           (T)", "TEXT")

    # ── 값 텍스트 (edit 레이어) ──────────────────────────────────
    text(4.5163, 2.1125, str(int(bw)), "edit")            # 보 폭
    text(0.9354, 5.6206, str(int(bh)), "edit", ang=90)    # 보 높이

    if tn:
        text(8.4575, 8.4027, str(tn),          "edit")    # 상부 개수
        text(9.3531, 8.4027, f"{tpfx} {tsz}",  "edit")    # 상부 규격

    if bn:
        text(8.4575, 3.7143, str(bn),          "edit")    # 하부 개수
        text(9.3531, 3.7143, f"{bpfx} {bsz}",  "edit")    # 하부 규격

    _, st_dia, st_sp = _ss(stir)
    if st_dia:
        text(9.5918, 5.8550, f"{st_dia}    {st_sp}", "edit")  # 스터럽

    return out


def _sheet_get_parts(sheet_path):
    """sheet DXF → (header+tables+blocks bytes, entities bytes, objects bytes)"""
    raw = open(sheet_path, "rb").read()

    ent_sec  = raw.find(b"  0\r\nSECTION\r\n  2\r\nENTITIES\r\n")
    endsec   = raw.find(b"  0\r\nENDSEC\r\n", ent_sec + 1)
    endsec_e = endsec + len(b"  0\r\nENDSEC\r\n")

    return raw[:ent_sec], raw[ent_sec:endsec_e], raw[endsec_e:]


def _sheet_copy_lines(sheet_ent_b, dx_mm, hcnt, S):
    """
    두 번째 시트 이후: SHEET 원본의 layer=0 엔티티를
    dx_mm 만큼 X축으로 이동하여 복사 (격자 틀 재현).
    LINE, TEXT, LWPOLYLINE, HATCH 지원.
    """
    parts = []
    inner = sheet_ent_b.decode("cp949", "replace").replace("\r\n", "\n")
    lines = inner.split("\n")

    def hdl():
        v = hcnt[0]; hcnt[0] += 1; return f"{v:X}"

    i = 0
    while i < len(lines) - 1:
        if lines[i].strip() == "0" and lines[i+1].strip() in (
                "LINE", "TEXT", "LWPOLYLINE", "POLYLINE", "HATCH", "INSERT"):
            etype = lines[i+1].strip()
            # 이 엔티티의 원본 블록 전체 수집
            blk_start = i
            j = i + 2; props = {}
            raw_block = [lines[i], lines[i+1]]
            while j < len(lines) - 1:
                if lines[j].strip() == "0": break #현재 복사할 도면 다 읽음.
                raw_block.append(lines[j])#전체읽은 객체 저장
                c = lines[j].strip()
                try: ci = int(c); props[ci] = lines[j+1].strip()
                except: pass
                j += 2

            layer = props.get(8, "0")
            if layer not in ("0", "TEXT", "DEFPOINTS"):#복사허용레이어
                i += 2; continue

            out = []
            def p(c, v): out.append(f"{int(c):>3}\r\n{v}")

            # ── LINE ────────────────────────────────────────
            if etype == "LINE" and layer == "0":
                x1 = float(props.get(10, 0)) / S + dx_mm#10=시작X, 20=시작Y, 11=끝X, 21=끝Y
                y1 = float(props.get(20, 0)) / S
                x2 = float(props.get(11, 0)) / S + dx_mm
                y2 = float(props.get(21, 0)) / S
                p(0,"LINE"); p(5,hdl()); p(330,"2")
                p(100,"AcDbEntity"); p(8,"0")
                p(100,"AcDbLine")
                p(10,f"{x1*S:.4f}"); p(20,f"{y1*S:.4f}"); p(30,"0.0")
                p(11,f"{x2*S:.4f}"); p(21,f"{y2*S:.4f}"); p(31,"0.0")
                parts.append("\r\n".join(out))

            # ── TEXT ────────────────────────────────────────
            elif etype == "TEXT" and layer in ("TEXT", "0"):
                x   = float(props.get(10, 0)) / S + dx_mm
                y   = float(props.get(20, 0)) / S
                txt = props.get(1, "")
                ang = props.get(50, "")
                ht  = props.get(40, str(0.40 * S))
                p(0,"TEXT"); p(5,hdl()); p(330,"2")
                p(100,"AcDbEntity"); p(8,layer)
                p(100,"AcDbText")
                p(10,f"{x*S:.4f}"); p(20,f"{y*S:.4f}"); p(30,"0.0")
                p(40,ht); p(1,txt); p(7,"12")
                if ang: p(50, ang)
                p(100,"AcDbText")
                parts.append("\r\n".join(out))
                

            # ── LWPOLYLINE ──────────────────────────────────
            elif etype == "LWPOLYLINE" and layer == "0":
                pts = []

                k = 0

                while k < len(raw_block)-3:

                    code = raw_block[k].strip()
                    print(raw_block[:80])

                    # vertex 시작
                    if code == "10":

                        try:
                            x = float(raw_block[k+1].strip())
                        except:
                            k += 2
                            continue

                        # 바로 뒤쪽만 탐색
                        m = k + 2

                        while m < len(raw_block)-1:

                            c2 = raw_block[m].strip()

                            # 다음 vertex 시작 전에만
                            if c2 == "10":
                                break

                            if c2 == "20":

                                try:
                                    y = float(raw_block[m+1].strip())

                                    nx = x / S + dx_mm
                                    ny = y / S

                                    pts.append((nx*S, ny*S))

                                except:
                                    pass

                                break

                            m += 2

                    k += 2
                    

            # ── HATCH ───────────────────────────────────────
            elif etype == "HATCH" and layer == "0":
                # HATCH는 구조가 복잡하므로 원본 라인을 그대로 복사하되
                # 10/20 (씨드 포인트) 좌표만 X 이동
                out_lines = ["  0\r\n" + etype, f"  5\r\n{hdl()}", "330\r\n2"]
                k = blk_start + 2
                while k < j:
                    code_str = lines[k].strip()
                    val_str  = lines[k+1].strip() if k+1 < j else ""
                    try:
                        code_int = int(code_str)
                        if code_int == 10:        # X 좌표 이동
                            nx = float(val_str) / S + dx_mm
                            out_lines.append(f" {code_int:2d}\r\n{nx*S:.4f}")
                        elif code_int == 5:        # 핸들 이미 교체됨 → 건너뜀
                            pass
                        elif code_int == 330:      # owner 이미 지정 → 건너뜀
                            pass
                        else:
                            out_lines.append(f" {code_int:2d}\r\n{val_str}")
                    except ValueError:
                        out_lines.append(f"{code_str}\r\n{val_str}")
                    k += 2
                parts.append("\r\n".join(out_lines))

        i += 2
    return parts


def make_beam_table_a4(beams, path):
    """
    beamA4_sheet.dxf를 틀로 A4 배근표 DXF 저장.
    - 시트 1장 = 4행 × 3열 (END_M / CENTER / END_V)
    - 4개 초과 시 오른쪽에 시트를 반복 배치 (_SHEET_DX 간격)
    """
    try:
        _here = _os.path.dirname(_os.path.abspath(__file__))
    except NameError:
        _here = _os.getcwd()

    sheet_path = _os.path.join(_here, "beamA4_sheet.dxf")
    if not _os.path.isfile(sheet_path):
        sheet_path = _os.path.join(_here, "..", "beamA4_sheet.dxf")
    if not _os.path.isfile(sheet_path):
        raise FileNotFoundError(f"beamA4_sheet.dxf 를 {_here} 에 넣어주세요.")

    header_b, sheet_ent_b, objects_b = _sheet_get_parts(sheet_path)

    S  = 83.333
    OX = DXFWriter.OX
    OY = DXFWriter.OY

    # 전역 핸들 카운터
    hcnt = [_HANDLE_START]

    # ── SHEET 원본 엔티티 ──────────────────────────────────────
    sheet_inner = sheet_ent_b.decode("cp949", "replace")
    cut  = sheet_inner.rfind("  0\r\nENDSEC")
    base = sheet_inner[:cut].rstrip("\r\n ")
    parts = [base]

    # ── 4행 이중선 / 격자선 추가 헬퍼 ───────────────────────────
    def add_grid_line(x1_mm, y1_mm, x2_mm, y2_mm, dx_mm=0.0):
        """격자 보조선 (layer=0) 추가 — dx_mm: 시트 X 오프셋"""
        out = []
        def p(c, v): out.append(f"{int(c):>3}\r\n{v}")
        h = f"{hcnt[0]:X}"; hcnt[0] += 1
        p(0,"LINE"); p(5,h); p(330,"2")
        p(100,"AcDbEntity"); p(8,"0")
        p(100,"AcDbLine")
        p(10, f"{(x1_mm + dx_mm)*S:.4f}"); p(20, f"{y1_mm*S:.4f}"); p(30,"0.0")
        p(11, f"{(x2_mm + dx_mm)*S:.4f}"); p(21, f"{y2_mm*S:.4f}"); p(31,"0.0")
        return out

    def add_name_text(ox_mm, oy_mm, txt, dx_mm=0.0):
        """보이름 TEXT (가로, edit 레이어)"""
        out = []
        def p(c, v): out.append(f"{int(c):>3}\r\n{v}")
        h = f"{hcnt[0]:X}"; hcnt[0] += 1
        p(0,"TEXT"); p(5,h); p(330,"2")
        p(100,"AcDbEntity"); p(8,"edit")
        p(100,"AcDbText")
        p(10, f"{(ox_mm + dx_mm)*S:.4f}")
        p(20, f"{oy_mm*S:.4f}")
        p(30,"0.0")
        p(40, f"{0.40*S:.4f}"); p(1,str(txt)); p(7,"12")
        p(100,"AcDbText")
        return out

    # ── 시트 단위 처리 ────────────────────────────────────────
    import math
    n_sheets = max(1, math.ceil(len(beams) / _ROWS_PER_SHEET))

    for si in range(n_sheets):
        dx = si * _SHEET_DX   # 이 시트의 X 오프셋

        # 두번째 시트부터: 격자선 복사 (layer=0 선들만)
        if si > 0:
            parts += _sheet_copy_lines(sheet_ent_b, dx, hcnt, S)

        # ── 4행 추가 격자선 (SHEET는 3행까지만 있음) ─────────────
        # 이중선: y=977.6917 (상단), 기존 y=979.4917 (하단 = SHEET에 이미 존재)
      #  parts.append("\r\n".join(add_grid_line(758.88, 977.6917, 801.60, 977.6917, dx)))
        # 4행 하단선
      #  parts.append("\r\n".join(add_grid_line(758.88, 965.3917, 801.60, 965.3917, dx)))
        # 4행 수직선 5개 (기존 수직선 연장)
      #  for vx in [758.8835, 762.7235, 775.6836, 788.6436, 801.6037]:
      #      parts.append("\r\n".join(add_grid_line(vx, 965.3917, vx, 979.4917, dx)))

        # ── 이 시트에 해당하는 보 4개 처리 ─────────────────────
        beam_start = si * _ROWS_PER_SHEET
        beam_end   = min(beam_start + _ROWS_PER_SHEET, len(beams))

        for ri_local, bi in enumerate(range(beam_start, beam_end)):
            b    = beams[bi]
            bw   = float(b.get("width",  300) or 300)
            bh   = float(b.get("depth",  600) or 600)
            name = b.get("name","") or f"B{bi+1}"

            # 보이름 텍스트
            nm = add_name_text(_NAME_X + dx, _NAME_YC[ri_local], name)
            parts.append("\r\n".join(nm))

            # 3열: 좌=END_M, 중=CENTER, 우=END_V
            _cell_data = [
                (b.get("em_top",""),  b.get("em_bot",""),  b.get("em_stir","")),
                (b.get("cen_top",""), b.get("cen_bot",""), b.get("cen_stir","")),
                (b.get("ev_top",""),  b.get("ev_bot",""),  b.get("ev_stir","")),
            ]
            for ci, base_ox in enumerate(_COLS_X):
                cell_ox = base_ox + dx
                cell_oy = _ROWS_Y[ri_local]
                top_rb, bot_rb, stir = _cell_data[ci]
                ents = _cell_entities(cell_ox, cell_oy, bw, bh, top_rb, bot_rb, stir, hcnt)
                parts.append("\r\n".join(ents))

    parts.append("  0\r\nENDSEC")

    entities_text = "\r\n".join(parts) + "\r\n"

    with open(path, "wb") as f:
        f.write(header_b)
        f.write(entities_text.encode("cp949", "replace"))
        f.write(objects_b)


def make_beam_table_a3(beams, path):
    raise NotImplementedError("A3는 준비 중입니다.")




# ══════════════════════════════════════════════════════════════
#  SmartEntry  ─ 자동완성 (KeyRelease 기반, trace 재귀 문제 없음)
# ══════════════════════════════════════════════════════════════
class SmartEntry(tk.Frame):
    """
    rebar 모드  : '3-' 입력 → 팝업 → ←/→ 로 HD/SHD/UHD 선택 → '22' → '3-UHD22'
    stirrup 모드: '10' 입력 → 0.5s → 팝업 → ←/→ → '@300' → 'HD10@300'

    Alt+Enter   : 현재 행 전체 복사 → 아래 삽입
    Shift+Enter : 현재 셀만 아래 행 동일 칸에 복사
    ↑ / ↓       : 위·아래 행 동일 열로 이동
    """
    def __init__(self, parent, width=10, mode="rebar",
                 cb_alt=None, cb_shift=None, cb_up=None, cb_dn=None):
        super().__init__(parent, bg=BG3)
        self.mode     = mode
        self.cb_alt   = cb_alt
        self.cb_shift = cb_shift
        self.cb_up    = cb_up
        self.cb_dn    = cb_dn

        self._pop    = None
        self._plbls  = []
        self._pidx   = 0
        self._active = False   # 팝업 선택 중
        self._setting= False   # 내부에서 Entry 값 세팅 중
        self._tmr    = None

        self._ent = tk.Entry(self,
                             font=("Malgun Gothic",9), bg=BG3, fg=TXT,
                             insertbackground=WHI, relief="flat", width=width,
                             highlightbackground=BDR, highlightthickness=1)
        self._ent.pack(fill="both", expand=True, ipady=4)

        self._ent.bind("<FocusIn>",    lambda e: self._ent.config(highlightbackground=ACCH))
        self._ent.bind("<FocusOut>",   self._on_blur)
        # KeyRelease: 사용자 입력 후 값이 확정된 뒤 호출
        self._ent.bind("<KeyRelease>", self._on_key_release)
        # 방향키는 KeyPress에서 처리 (KeyRelease 전에 팝업 반응)
        self._ent.bind("<Left>",       self._kl)
        self._ent.bind("<Right>",      self._kr)
        # Enter 계열 — <Return>에서 modifier state를 확인하여 분기
        # (tkinter에서 <Return>이 Shift+Return도 가로채므로 단일 핸들러 사용)
        # Shift/Alt+Enter는 <Return>보다 specific → 먼저 매칭됨
        self._ent.bind("<Shift-Return>",   self._kshift)
        self._ent.bind("<Shift-KP_Enter>", self._kshift)
        self._ent.bind("<Alt-Return>",     self._kalt)
        self._ent.bind("<Alt-KP_Enter>",   self._kalt)
        # 순수 Enter (Shift/Alt 없는 것) → 팝업 확정
        self._ent.bind("<Return>",   self._kenter)
        self._ent.bind("<KP_Enter>", self._kenter)
        # 위아래
        self._ent.bind("<Up>",    self._kup)
        self._ent.bind("<Down>",  self._kdown)
        self._ent.bind("<Escape>",lambda e: self._close_pop())

    # ── 외부 API ──────────────────────────────────────────
    def get(self):
        return self._ent.get()

    def set(self, v):
        """외부에서 값 설정 — 자동완성 트리거 안 함"""
        self._setting = True
        self._ent.delete(0, "end")
        self._ent.insert(0, v)
        self._setting = False

    def focus(self):
        self._ent.focus_set()

    # ── KeyRelease 핸들러 ─────────────────────────────────
    def _on_key_release(self, e):
        # 방향키·Enter·특수키는 여기서 처리 안 함
        if e.keysym in ("Left","Right","Up","Down","Return",
                        "KP_Enter","Escape","Alt_L","Alt_R",
                        "Shift_L","Shift_R","Control_L","Control_R",
                        "Tab","BackSpace","Delete"):
            # BackSpace/Delete는 팝업 취소 조건 확인
            if e.keysym in ("BackSpace","Delete"):
                self._check_cancel()
            return

        if self._setting:
            return

        v = self._ent.get()

        if self.mode == "rebar":
            if self._active:
                # prefix 뒤에 숫자가 붙었으면 확정
                if re.match(r"^\d+-(HD|SHD|UHD)\d+$", v):
                    self._close_pop()
                # 패턴 벗어나면 팝업 닫기
                elif not re.match(r"^\d+-(HD|SHD|UHD)$", v):
                    self._close_pop()
            else:
                # '숫자-' 가 되면 팝업 열기
                if re.match(r"^\d+\-$", v):
                    self._open_pop()

        else:  # stirrup
            if self._active:
                # prefix+숫자 이후에 추가 글자 → 확정
                base = re.match(r"^(HD|SHD|UHD)(\d+)$", v)
                if not base:
                    # '@' 나 다른 문자가 붙었으면 확정
                    self._close_pop()
            else:
                # 타이머 리셋
                if self._tmr:
                    try: self.after_cancel(self._tmr)
                    except: pass
                    self._tmr = None
                # 순수 숫자 1자리 이상 → 타이머
                if re.match(r"^\d+$", v) and len(v) >= 1:
                    self._tmr = self.after(500, self._timer_fired)

    def _check_cancel(self):
        """BackSpace/Delete 후 패턴 벗어났으면 팝업 닫기"""
        if not self._active:
            return
        v = self._ent.get()
        if self.mode == "rebar":
            if not re.match(r"^\d+-(HD|SHD|UHD)?\d*$", v):
                self._close_pop()
        else:
            if not re.match(r"^(HD|SHD|UHD)\d*$", v):
                self._close_pop()

    def _timer_fired(self):
        self._tmr = None
        if self._active:
            return
        v = self._ent.get()
        if re.match(r"^\d+$", v):
            self._open_pop()

    def _open_pop(self):
        self._active = True
        self._pidx   = 0
        self._show_popup()
        self._inject()   # 첫 번째 prefix 삽입

    def _inject(self):
        """선택된 prefix를 Entry에 직접 씀 (_setting 플래그)"""
        v = self._ent.get()
        if self.mode == "rebar":
            m = re.match(r"^(\d+)\-", v)
            if not m:
                return
            new_v = f"{m.group(1)}-{PREFIXES[self._pidx]}"
        else:
            # 숫자 부분만 추출
            digits = re.sub(r"^(HD|SHD|UHD)", "", v)
            m = re.match(r"^(\d+)", digits)
            if not m:
                return
            new_v = f"{PREFIXES[self._pidx]}{m.group(1)}"

        self._setting = True
        self._ent.delete(0, "end")
        self._ent.insert(0, new_v)
        self._ent.icursor(len(new_v))
        self._setting = False
        self._refresh_pop()

    def _close_pop(self):
        self._active = False
        self._hide_popup()

    # ── 키 핸들러 ─────────────────────────────────────────
    def _kl(self, e):
        if self._active:
            self._pidx = (self._pidx - 1) % len(PREFIXES)
            self._inject()
            return "break"

    def _kr(self, e):
        if self._active:
            self._pidx = (self._pidx + 1) % len(PREFIXES)
            self._inject()
            return "break"

    def _kenter(self, e):
        """순수 Enter — 팝업 확정만"""
        if self._active:
            self._close_pop()
        return "break"

    def _kshift(self, e):
        """Shift+Enter — 현재 셀 아래 행에 복사"""
        self._close_pop()
        if self.cb_shift:
            self.cb_shift()
        return "break"
        if self._active: return "break"
        if self.cb_up: self.cb_up()
        return "break"

    def _kalt(self, e):
        """Alt+Enter — 현재 행 전체를 아래에 복사"""
        self._close_pop()
        if self.cb_alt:
            self.cb_alt()
        return "break"
        if self._active: return "break"
        if self.cb_up: self.cb_up()
        return "break"

    def _kup(self, e):
        if self._active: return "break"
        if self.cb_up: self.cb_up()
        return "break"

    def _kdown(self, e):
        if self._active: return "break"
        if self.cb_dn: self.cb_dn()
        return "break"

    def _on_blur(self, e):
        self._ent.config(highlightbackground=BDR)
        if self._active:
            self._close_pop()

    # ── 팝업 ──────────────────────────────────────────────
    def _show_popup(self):
        self._hide_popup()
        pop = tk.Toplevel(self, bg=BG2)
        pop.wm_overrideredirect(True)
        pop.wm_attributes("-topmost", True)
        pop.configure(highlightbackground=BDR2, highlightthickness=1)
        fr = tk.Frame(pop, bg=BG2)
        fr.pack(padx=3, pady=3)
        self._plbls = []
        for p in PREFIXES:
            lb = tk.Label(fr, text=p, font=("Consolas",10,"bold"),
                          bg=BG3, fg=TX2, padx=9, pady=3)
            lb.pack(side="left", padx=2)
            self._plbls.append(lb)
        # 위치 계산
        self._ent.update_idletasks()
        x = self._ent.winfo_rootx()
        y = self._ent.winfo_rooty() + self._ent.winfo_height() + 2
        pop.geometry(f"+{x}+{y}")
        self._pop = pop
        self._refresh_pop()

    def _refresh_pop(self):
        if not self._pop:
            return
        for i, lb in enumerate(self._plbls):
            lb.config(
                bg=ACCH if i == self._pidx else BG3,
                fg=WHI  if i == self._pidx else TX2)

    def _hide_popup(self):
        if self._pop:
            try: self._pop.destroy()
            except: pass
        self._pop  = None
        self._plbls = []


# ══════════════════════════════════════════════════════════════
#  AutoTableApp
# ══════════════════════════════════════════════════════════════
class AutoTableApp(tk.Toplevel):
    def __init__(self, parent=None, username=""):
        if parent:
            super().__init__(parent)
        else:
            self._tk = tk.Tk(); self._tk.withdraw()
            super().__init__(self._tk)

        self.title("Auto Table  —  배근표 자동 작성")
        self.geometry("1200x680"); self.minsize(900,560)
        self.configure(bg=BG)
        self.username   = username
        self.beam_rows  = []
        self._row_frame = None
        self._build()
        self._center()

    # ── 레이아웃 ──────────────────────────────────────────
    def _build(self):
        hdr = tk.Frame(self, bg=BG2, height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📊  Auto Table",
                 font=("Malgun Gothic",13,"bold"), bg=BG2, fg=WHI).pack(side="left", padx=18)
        tk.Label(hdr, text="보·기둥·슬래브·벽 배근표 자동 작성 및 CAD 출력",
                 font=("Malgun Gothic",9), bg=BG2, fg=TX2).pack(side="left")
        if self.username:
            tk.Label(hdr, text=f"({self.username})",
                     font=("Malgun Gothic",9), bg=BG2, fg=TX3).pack(side="right", padx=18)
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG); body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=BG2, width=148)
        left.pack(side="left", fill="y"); left.pack_propagate(False)
        tk.Label(left, text="부재 유형", font=("Malgun Gothic",9,"bold"),
                 bg=BG2, fg=TX2, pady=10).pack(fill="x")
        tk.Frame(left, bg=BDR, height=1).pack(fill="x")
        self._tbns = []
        for mt in MEMBER_TYPES:
            b = tk.Button(left, text=mt, font=("Malgun Gothic",10),
                          bg=BG2, fg=TXT, relief="flat", cursor="hand2",
                          pady=11, anchor="w", padx=14,
                          command=lambda t=mt: self._switch(t))
            b.pack(fill="x"); self._tbns.append((mt, b))

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        ftr = tk.Frame(right, bg=BG2, height=48)
        ftr.pack(side="bottom", fill="x"); ftr.pack_propagate(False)
        tk.Frame(right, bg=BDR, height=1).pack(side="bottom", fill="x")

        def mkb(txt, cmd, bg_=ACC):
            b = tk.Button(ftr, text=txt, command=cmd,
                          font=("Malgun Gothic",9,"bold"),
                          bg=bg_, fg=WHI, relief="flat", cursor="hand2",
                          padx=13, pady=5)
            b.bind("<Enter>", lambda _,b=b,c=bg_: b.config(bg=_lht(c)))
            b.bind("<Leave>", lambda _,b=b,c=bg_: b.config(bg=c))
            b.pack(side="right", padx=6, pady=7)

        mkb("📄 A4 DXF 출력", self._export_a4)
        mkb("📋 A3 DXF 출력", self._export_a3, bg_=GRN)
        mkb("➕ 행 추가",      self._add_row,   bg_="#374151")
        tk.Label(ftr, text="Alt+Enter: 행 복사↓   Shift+Enter: 셀 복사↓   ↑↓: 행 이동",
                 font=("Malgun Gothic",7), bg=BG2, fg=TX3).pack(side="left", padx=14)

        self._content = tk.Frame(right, bg=BG)
        self._content.pack(fill="both", expand=True)
        self._switch("보(Beam)")

    def _switch(self, t):
        for mt, b in self._tbns:
            b.config(bg=BG3 if mt==t else BG2, fg=WHI if mt==t else TXT)
        for w in self._content.winfo_children(): w.destroy()
        if t == "보(Beam)": self._build_beam()
        else:
            tk.Label(self._content, text=f"🚧  {t}\n준비 중입니다.",
                     font=("Malgun Gothic",13), bg=BG, fg=TX3).pack(expand=True)

    # ── 보 패널 ───────────────────────────────────────────
    def _build_beam(self):
        outer = tk.Frame(self._content, bg=BG)
        outer.pack(fill="both", expand=True, padx=8, pady=6)

        # ── 헤더 행 ──────────────────────────────────────
        hf = tk.Frame(outer, bg=BG3); hf.pack(fill="x")
        for lbl, w, key, mode in COL_DEFS:
            if mode == "check":
                # 체크박스 열 헤더
                tk.Label(hf, text=lbl, font=("Malgun Gothic",8,"bold"),
                         bg=BG3, fg=TX2, width=w, pady=3,
                         wraplength=w*7).pack(side="left")
            elif mode == "btn":
                tk.Label(hf, text=lbl, font=("Malgun Gothic",8,"bold"),
                         bg=BG3, fg=TX2, width=w, pady=3).pack(side="left")
            else:
                tk.Label(hf, text=lbl, font=("Malgun Gothic",8,"bold"),
                         bg=BG3, fg=TX2, width=w, pady=3).pack(side="left")
        tk.Label(hf, text="삭제", font=("Malgun Gothic",8,"bold"),
                 bg=BG3, fg=TX2, width=4, pady=3).pack(side="left")

        cf = tk.Frame(outer, bg=BG); cf.pack(fill="both", expand=True, pady=(1,0))
        cvs = tk.Canvas(cf, bg=BG, bd=0, highlightthickness=0)
        vsb = ttk.Scrollbar(cf, orient="vertical", command=cvs.yview)
        cvs.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        cvs.pack(side="left", fill="both", expand=True)
        self._row_frame = tk.Frame(cvs, bg=BG)
        wid = cvs.create_window((0,0), window=self._row_frame, anchor="nw")
        self._row_frame.bind("<Configure>",
            lambda e: cvs.configure(scrollregion=cvs.bbox("all")))
        cvs.bind("<Configure>",
            lambda e: cvs.itemconfig(wid, width=e.width))

        self.beam_rows.clear()
        for _ in range(3): self._add_row()

    # ── 행 추가 ───────────────────────────────────────────
    def _add_row(self, copy_from=None, after_rv=None):
        if self._row_frame is None: return

        fr = tk.Frame(self._row_frame, bg=BG4)
        rv = {"__frame__": fr, "__widgets__": {}}

        for lbl, w, key, mode in COL_DEFS:

            # ── 체크박스 ─────────────────────────────────
            if mode == "check":
                # copy_from 또는 기본값에서 bool 읽기
                if copy_from and key in copy_from:
                    src = copy_from[key]
                    init_bool = src.get() if hasattr(src, "get") else DEFAULTS.get(key, True)
                    if isinstance(init_bool, str):
                        init_bool = init_bool != "0" and init_bool.lower() != "false"
                else:
                    init_bool = DEFAULTS.get(key, True)

                chk_var = tk.BooleanVar(value=bool(init_bool))
                chk_fr  = tk.Frame(fr, bg=BG4, width=w*7)
                chk_fr.pack(side="left", padx=1)
                chk_fr.pack_propagate(False)

                chk = tk.Checkbutton(
                    chk_fr, variable=chk_var,
                    bg=BG4, fg=TXT, activebackground=BG4,
                    selectcolor=BG3, relief="flat", cursor="hand2"
                )
                chk.pack(expand=True)
                rv[key] = chk_var
                rv["__widgets__"][key] = chk

                # 체크 변경 시 연동 열 활성/비활성
                dep_keys = CHECK_GROUPS.get(key, [])
                def _on_check_change(var=chk_var, deps=dep_keys, _rv=rv):
                    self._toggle_group(_rv, deps, var.get())
                chk_var.trace_add("write", lambda *a, fn=_on_check_change: fn())

            # ── 설계 버튼 ────────────────────────────────
            elif mode == "btn":
                btn_fr = tk.Frame(fr, bg=BG4, width=w*7)
                btn_fr.pack(side="left", padx=1)
                btn_fr.pack_propagate(False)
                btn = tk.Button(
                    btn_fr, text="설계",
                    font=("Malgun Gothic", 8, "bold"),
                    bg="#1f4e79", fg=WHI, relief="flat", cursor="hand2",
                    pady=2,
                    command=lambda _rv=rv: self._open_design_window(_rv)
                )
                btn.bind("<Enter>", lambda e, b=btn: b.config(bg="#2563eb"))
                btn.bind("<Leave>", lambda e, b=btn: b.config(bg="#1f4e79"))
                btn.pack(fill="both", expand=True, padx=2, pady=2)
                rv[key]                  = None   # 버튼은 값 없음
                rv["__widgets__"][key]   = btn

            # ── SmartEntry (rebar / stirrup) ──────────────
            elif mode in ("rebar", "stirrup"):
                if copy_from and key in copy_from:
                    src  = copy_from[key]
                    init = src.get() if hasattr(src, "get") else ""
                else:
                    init = DEFAULTS.get(key, "")

                se = SmartEntry(fr, width=w, mode=mode,
                    cb_alt   = lambda _rv=rv: self._do_alt(_rv),
                    cb_shift = lambda _rv=rv, _k=key: self._do_shift(_rv, _k),
                    cb_up    = lambda _rv=rv, _k=key: self._do_nav(_rv, _k, -1),
                    cb_dn    = lambda _rv=rv, _k=key: self._do_nav(_rv, _k, +1),
                )
                se.set(init)
                se.pack(side="left", padx=1)
                rv[key]                 = se
                rv["__widgets__"][key]  = se

            # ── 일반 Entry ───────────────────────────────
            else:
                if copy_from and key in copy_from:
                    src  = copy_from[key]
                    init = src.get() if hasattr(src, "get") else ""
                else:
                    init = DEFAULTS.get(key, "")

                var = tk.StringVar(value=init)
                ent = tk.Entry(fr, textvariable=var,
                               font=("Malgun Gothic",9), bg=BG3, fg=TXT,
                               insertbackground=WHI, relief="flat", width=w,
                               highlightbackground=BDR, highlightthickness=1)
                ent.pack(side="left", padx=1, ipady=4)
                ent.bind("<FocusIn>",  lambda e, _e=ent: _e.config(highlightbackground=ACCH))
                ent.bind("<FocusOut>", lambda e, _e=ent: _e.config(highlightbackground=BDR))

                def _on_entry_shift(e, _rv=rv, _k=key):
                    self._do_shift(_rv, _k); return "break"
                def _on_entry_alt(e, _rv=rv):
                    self._do_alt(_rv); return "break"
                def _on_entry_enter(e): return "break"

                ent.bind("<Shift-Return>",   _on_entry_shift)
                ent.bind("<Shift-KP_Enter>", _on_entry_shift)
                ent.bind("<Alt-Return>",     _on_entry_alt)
                ent.bind("<Alt-KP_Enter>",   _on_entry_alt)
                ent.bind("<Return>",         _on_entry_enter)
                ent.bind("<KP_Enter>",       _on_entry_enter)
                ent.bind("<Up>",   lambda e, _rv=rv, _k=key: (self._do_nav(_rv,_k,-1),"break")[1])
                ent.bind("<Down>", lambda e, _rv=rv, _k=key: (self._do_nav(_rv,_k,+1),"break")[1])
                rv[key]                = var
                rv["__widgets__"][key] = ent

        # ── 삭제 버튼 ────────────────────────────────────
        def _del(_rv=rv):
            if len(self.beam_rows) <= 1:
                messagebox.showwarning("경고","최소 1개 행이 필요합니다.", parent=self)
                return
            if _rv in self.beam_rows: self.beam_rows.remove(_rv)
            _rv["__frame__"].destroy()

        tk.Button(fr, text="✕", command=_del,
                  font=("Malgun Gothic",9), bg=RED, fg=WHI,
                  relief="flat", cursor="hand2", width=3, pady=3).pack(side="left", padx=2)

        if after_rv is not None and after_rv in self.beam_rows:
            idx = self.beam_rows.index(after_rv) + 1
            self.beam_rows.insert(idx, rv)
        else:
            self.beam_rows.append(rv)

        self._repack()

        # 체크박스 초기 상태 적용 (행 추가 직후)
        for ck_key, dep_keys in CHECK_GROUPS.items():
            chk_var = rv.get(ck_key)
            if isinstance(chk_var, tk.BooleanVar):
                self._toggle_group(rv, dep_keys, chk_var.get())

    # ── 체크 연동: 의존 열 활성/비활성 ───────────────────
    def _toggle_group(self, rv, dep_keys, enabled: bool):
        """enabled=True → 입력 가능 / False → 회색 비활성"""
        for k in dep_keys:
            w = rv["__widgets__"].get(k)
            if w is None:
                continue
            if isinstance(w, SmartEntry):
                inner = w._ent
                inner.config(
                    state="normal" if enabled else "disabled",
                    bg=BG3 if enabled else TX3,
                    fg=TXT if enabled else TX3,
                )
            elif isinstance(w, tk.Entry):
                w.config(
                    state="normal" if enabled else "disabled",
                    bg=BG3 if enabled else TX3,
                    fg=TXT if enabled else TX3,
                )

    def _repack(self):
        for rv in self.beam_rows:
            f = rv["__frame__"]; f.pack_forget()
        for rv in self.beam_rows:
            rv["__frame__"].pack(fill="x", pady=1)

    # ── 단축키 동작 ───────────────────────────────────────
    def _do_alt(self, src_rv):
        """Alt+Enter: 행 전체 복사 → 아래에 삽입"""
        self._add_row(copy_from=src_rv, after_rv=src_rv)

    def _do_shift(self, src_rv, key):
        """Shift+Enter: 현재 셀 → 아래 행 동일 셀 복사"""
        if src_rv not in self.beam_rows: return
        idx = self.beam_rows.index(src_rv) + 1
        if idx >= len(self.beam_rows): return
        tgt_rv = self.beam_rows[idx]
        if key not in tgt_rv: return
        val = src_rv[key].get() if hasattr(src_rv[key],"get") else ""
        tgt = tgt_rv[key]
        if hasattr(tgt,"set"): tgt.set(val)

    def _do_nav(self, src_rv, key, direction):
        """↑/↓: 위·아래 행 동일 열로 포커스 이동"""
        if src_rv not in self.beam_rows: return
        idx = self.beam_rows.index(src_rv) + direction
        if not (0 <= idx < len(self.beam_rows)): return
        tgt_rv  = self.beam_rows[idx]
        widget  = tgt_rv["__widgets__"].get(key)
        if widget:
            if isinstance(widget, SmartEntry):
                widget.focus()
            elif isinstance(widget, tk.Entry):
                widget.focus_set()

    # ── 데이터 수집 ───────────────────────────────────────
    def _collect(self):
        """UI 행 데이터를 dict 리스트로 반환. DXF 출력용."""
        result = []
        for rv in self.beam_rows:
            d = {}
            for lbl, w, key, mode in COL_DEFS:
                if mode == "btn":
                    continue
                v = rv.get(key)
                if mode == "check":
                    d[key] = v.get() if isinstance(v, tk.BooleanVar) else True
                elif v is not None and hasattr(v, "get"):
                    d[key] = v.get()
                else:
                    d[key] = ""
            # 체크 해제 그룹 → DXF 빈칸
            for ck_key, dep_keys in CHECK_GROUPS.items():
                if not d.get(ck_key, True):
                    for dk in dep_keys:
                        d[dk] = ""
            result.append(d)
        return result

    # ── 설계 창 ───────────────────────────────────────────
    def _open_design_window(self, rv):
        name = ""
        nv = rv.get("name")
        if nv: name = nv.get() if hasattr(nv, "get") else ""
        DesignWindow(self, rv, name)



    # ── DXF 출력 ──────────────────────────────────────────
    def _export_a4(self):
        beams = self._collect()
        if not beams: messagebox.showwarning("경고","데이터 없음", parent=self); return
        path = filedialog.asksaveasfilename(
            defaultextension=".dxf", title="A4 DXF 저장",
            filetypes=[("DXF","*.dxf"),("All","*.*")],
            initialfile="beam_table_A4.dxf", parent=self)
        if not path: return
        try:
            make_beam_table_a4(beams, path)
            messagebox.showinfo("완료", f"저장 완료\n{path}", parent=self)
        except Exception as ex:
            messagebox.showerror("오류", str(ex), parent=self)

    def _export_a3(self):
        beams = self._collect()
        if not beams: messagebox.showwarning("경고","데이터 없음", parent=self); return
        path = filedialog.asksaveasfilename(
            defaultextension=".dxf", title="A3 DXF 저장",
            filetypes=[("DXF","*.dxf"),("All","*.*")],
            initialfile="beam_table_A3.dxf", parent=self)
        if not path: return
        try:
            make_beam_table_a3(beams, path)
            messagebox.showinfo("완료", f"저장 완료\n{path}", parent=self)
        except Exception as ex:
            messagebox.showerror("오류", str(ex), parent=self)

    def _center(self):
        self.update_idletasks()
        sw=self.winfo_screenwidth(); sh=self.winfo_screenheight()
        w=self.winfo_width(); h=self.winfo_height()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")


def _lht(h, a=20):
    r=min(255,int(h[1:3],16)+a); g=min(255,int(h[3:5],16)+a); b=min(255,int(h[5:7],16)+a)
    return f"#{r:02x}{g:02x}{b:02x}"


# ══════════════════════════════════════════════════════════════
#  DesignWindow  ─ 보 단면 설계 입력 창
# ══════════════════════════════════════════════════════════════
class DesignWindow(tk.Toplevel):
    """
    보 단면 설계 입력 창.
    - 설계 하중(Mu, Vu), 단면(B, D), 재료(fck, fy) 입력
    - [설계 실행] 클릭 → 최소 배근 계산 → 결과를 AutoTable 행에 자동 반영
    """
    # KDS 14.20.20 기준 계산에 사용하는 파이
    _PHI_B = 0.85   # 휨 강도감소계수
    _PHI_V = 0.75   # 전단 강도감소계수
    _BETA1 = 0.80   # fck ≤ 28 MPa 기준 (간략화)

    def __init__(self, parent, rv: dict, member_name: str = ""):
        super().__init__(parent)
        self.parent_rv  = rv           # AutoTable 행 dict (결과 반영용)
        self.member_name = member_name
        self.title(f"보 단면 설계  —  {member_name}" if member_name else "보 단면 설계")
        self.geometry("760x620"); self.minsize(700, 560)
        self.configure(bg=BG)
        self.resizable(True, True)
        self._result = {}              # 계산 결과 저장
        self._build()
        self._center()
        self.transient(parent); self.lift(); self.focus_force()

    # ── 레이아웃 ─────────────────────────────────────────
    def _build(self):
        # 제목 헤더
        hdr = tk.Frame(self, bg=BG2, height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🔧  보 단면 설계",
                 font=("Malgun Gothic",12,"bold"), bg=BG2, fg=WHI).pack(side="left", padx=16)
        tk.Label(hdr, text="KDS 14.20.20 강도설계법 (간략 계산)",
                 font=("Malgun Gothic",8), bg=BG2, fg=TX2).pack(side="left")
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG); body.pack(fill="both", expand=True, padx=16, pady=10)

        # ── 좌: 입력 패널 ─────────────────────────────────
        inp = tk.Frame(body, bg=BG2, bd=0, highlightthickness=1,
                       highlightbackground=BDR)
        inp.pack(side="left", fill="y", padx=(0,10), pady=4)

        def sec_label(parent, txt):
            tk.Label(parent, text=txt,
                     font=("Malgun Gothic",9,"bold"), bg=BG2, fg=ACC,
                     anchor="w", padx=12, pady=6).pack(fill="x")
            tk.Frame(parent, bg=BDR, height=1).pack(fill="x", padx=8)

        def field(parent, label, key, default="", unit=""):
            fr = tk.Frame(parent, bg=BG2); fr.pack(fill="x", padx=12, pady=3)
            tk.Label(fr, text=label, font=("Malgun Gothic",9),
                     bg=BG2, fg=TX2, width=18, anchor="w").pack(side="left")
            var = tk.StringVar(value=default)
            ent = tk.Entry(fr, textvariable=var, width=10,
                           font=("Malgun Gothic",9), bg=BG3, fg=TXT,
                           insertbackground=WHI, relief="flat",
                           highlightbackground=BDR, highlightthickness=1)
            ent.pack(side="left", ipady=3, padx=(0,4))
            ent.bind("<FocusIn>",  lambda e: ent.config(highlightbackground=ACCH))
            ent.bind("<FocusOut>", lambda e: ent.config(highlightbackground=BDR))
            if unit:
                tk.Label(fr, text=unit, font=("Malgun Gothic",8),
                         bg=BG2, fg=TX3).pack(side="left")
            self._vars[key] = var

        self._vars = {}

        # 단면 정보 (AutoTable 행에서 가져오기)
        bw_init = ""; bd_init = ""
        wv = self.parent_rv.get("width")
        dv = self.parent_rv.get("depth")
        if wv: bw_init = wv.get() if hasattr(wv,"get") else str(wv)
        if dv: bd_init = dv.get() if hasattr(dv,"get") else str(dv)

        sec_label(inp, "■ 단면 정보")
        field(inp, "폭  b  (mm)",         "bw",  bw_init or "300", "mm")
        field(inp, "전체 깊이  h  (mm)",   "h",   bd_init or "600", "mm")
        field(inp, "피복 두께  cc  (mm)",  "cc",  "40",             "mm")
        field(inp, "주철근 직경  (mm)",    "db",  "22",             "mm")
        field(inp, "스터럽 직경  (mm)",    "ds",  "10",             "mm")

        sec_label(inp, "■ 재료 강도")
        field(inp, "콘크리트  fck  (MPa)", "fck", "24",             "MPa")
        field(inp, "철근 항복강도  fy  (MPa)", "fy","400",          "MPa")

        sec_label(inp, "■ 설계 하중 (계수하중)")
        field(inp, "단부(i)  Mu  (kN·m)",   "Mu_i",  "200",  "kN·m")
        field(inp, "단부(i)  Vu  (kN)",     "Vu_i",  "120",  "kN")
        field(inp, "중앙부  Mu  (kN·m)",    "Mu_c",  "140",  "kN·m")
        field(inp, "중앙부  Vu  (kN)",      "Vu_c",  "80",   "kN")
        field(inp, "단부(j)  Mu  (kN·m)",   "Mu_j",  "200",  "kN·m")
        field(inp, "단부(j)  Vu  (kN)",     "Vu_j",  "120",  "kN")

        # ── 우: 결과 패널 ─────────────────────────────────
        res_outer = tk.Frame(body, bg=BG); res_outer.pack(side="left", fill="both", expand=True)

        res = tk.Frame(res_outer, bg=BG2, bd=0,
                       highlightthickness=1, highlightbackground=BDR)
        res.pack(fill="both", expand=True, pady=4)

        tk.Label(res, text="■ 설계 결과",
                 font=("Malgun Gothic",10,"bold"), bg=BG2, fg=ACC,
                 anchor="w", padx=12, pady=8).pack(fill="x")
        tk.Frame(res, bg=BDR, height=1).pack(fill="x", padx=8)

        self._result_text = tk.Text(
            res, font=("Consolas",9), bg=BG3, fg=TXT,
            relief="flat", state="disabled",
            highlightthickness=0, padx=10, pady=8
        )
        self._result_text.pack(fill="both", expand=True, padx=8, pady=6)

        # 태그 색상
        self._result_text.tag_config("head",  foreground=ACCH, font=("Consolas",9,"bold"))
        self._result_text.tag_config("ok",    foreground="#22c55e")
        self._result_text.tag_config("warn",  foreground="#f59e0b")
        self._result_text.tag_config("err",   foreground=RED)
        self._result_text.tag_config("val",   foreground=TXT)
        self._result_text.tag_config("dim",   foreground=TX3)

        # ── 하단 버튼 ─────────────────────────────────────
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")
        btn_fr = tk.Frame(self, bg=BG2, height=46)
        btn_fr.pack(fill="x"); btn_fr.pack_propagate(False)

        def mkb(txt, cmd, bg_=ACC):
            b = tk.Button(btn_fr, text=txt, command=cmd,
                          font=("Malgun Gothic",9,"bold"),
                          bg=bg_, fg=WHI, relief="flat", cursor="hand2",
                          padx=14, pady=5)
            b.bind("<Enter>", lambda _, b=b, c=bg_: b.config(bg=_lht(c)))
            b.bind("<Leave>", lambda _, b=b, c=bg_: b.config(bg=bg_))
            b.pack(side="right", padx=6, pady=7)

        mkb("✅  결과 적용",  self._apply_result, bg_=GRN)
        mkb("⚙️  설계 실행",  self._run_design,   bg_=ACC)
        mkb("✖  닫기",        self.destroy,        bg_="#374151")

    # ── 설계 계산 ─────────────────────────────────────────
    def _run_design(self):
        try:
            bw  = float(self._vars["bw"].get())
            h   = float(self._vars["h"].get())
            cc  = float(self._vars["cc"].get())
            db  = float(self._vars["db"].get())
            ds  = float(self._vars["ds"].get())
            fck = float(self._vars["fck"].get())
            fy  = float(self._vars["fy"].get())

            d = h - cc - ds - db / 2.0   # 유효깊이 (mm)

            # β1 보정
            beta1 = 0.85 - 0.007 * max(0, fck - 28)
            beta1 = max(0.65, min(0.85, beta1))

            phi_b = self._PHI_B
            phi_v = self._PHI_V

            zones = [
                ("단부(i)", float(self._vars["Mu_i"].get()), float(self._vars["Vu_i"].get())),
                ("중앙부",  float(self._vars["Mu_c"].get()), float(self._vars["Vu_c"].get())),
                ("단부(j)", float(self._vars["Mu_j"].get()), float(self._vars["Vu_j"].get())),
            ]

            lines = []
            lines.append(("head", f"{'─'*48}\n"))
            lines.append(("head", f"  보 단면 설계  (KDS 14.20.20)\n"))
            lines.append(("head", f"{'─'*48}\n"))
            lines.append(("dim",  f"  b={bw:.0f}mm  h={h:.0f}mm  d={d:.1f}mm\n"))
            lines.append(("dim",  f"  fck={fck:.0f}MPa  fy={fy:.0f}MPa  β1={beta1:.3f}\n"))
            lines.append(("val",  "\n"))

            result_store = {}

            for zone_name, Mu_kNm, Vu_kN in zones:
                Mu = Mu_kNm * 1e6   # N·mm
                Vu = Vu_kN  * 1e3   # N

                lines.append(("head", f"\n  ▶ {zone_name}   Mu={Mu_kNm:.1f} kN·m   Vu={Vu_kN:.1f} kN\n"))
                lines.append(("dim",  f"  {'─'*42}\n"))

                # ── 휨 배근 ────────────────────────────────
                # Rn = Mu / (φ·b·d²)
                Rn = Mu / (phi_b * bw * d**2)   # MPa
                m  = fy / (0.85 * fck)
                # ρ = (1/m)·(1 - √(1 - 2·m·Rn/fy))
                disc = 1 - 2 * m * Rn / fy
                if disc < 0:
                    lines.append(("err", "  ❌ 단면 부족 — 깊이/폭 증가 필요\n"))
                    result_store[zone_name] = None
                    continue
                rho   = (1.0 / m) * (1 - disc**0.5)
                rho_min = max(0.25 * fck**0.5 / fy, 1.4 / fy)
                rho_max = 0.75 * (0.85 * beta1 * fck / fy) * (600 / (600 + fy))
                rho_use = max(rho, rho_min)

                if rho_use > rho_max:
                    lines.append(("err", f"  ❌ ρ={rho_use:.5f} > ρmax={rho_max:.5f} — 단면 증가 필요\n"))
                    result_store[zone_name] = None
                    continue

                As_req = rho_use * bw * d   # mm²

                # 철근 개수 결정 (db 기준)
                Ab  = 3.14159 * (db/2)**2
                n_bar = max(2, int(As_req / Ab) + (1 if As_req % Ab > 0 else 0))
                As_prov = n_bar * Ab
                status_m = "ok" if As_prov >= As_req else "warn"

                lines.append(("val",  f"  휨:  As,req={As_req:.1f} mm²  →  {n_bar}-{int(db):d}φ  (As={As_prov:.1f} mm²)\n"))
                if rho < rho_min:
                    lines.append(("dim", f"         (최솟값 ρmin={rho_min:.5f} 적용)\n"))

                # ── 전단 배근 ──────────────────────────────
                # Vc = (1/6)·√fck·bw·d  (KDS 14.20.22 식 간략화)
                Vc = (1/6) * fck**0.5 * bw * d   # N
                Vs_req = Vu / phi_v - Vc

                if Vs_req <= 0:
                    # 최소 스터럽
                    s_req = min(d/2, 600)
                    stir_tag = "ok"
                    stir_note = "(최소 스터럽)"
                else:
                    # Av = 2·As,stir
                    Av = 2 * 3.14159 * (ds/2)**2
                    s_req = phi_v * Av * fy * d / (Vu - phi_v * Vc)
                    s_req = min(s_req, d/2, 600)
                    stir_tag = "ok" if s_req > 0 else "err"
                    stir_note = ""

                s_use = int(s_req / 50) * 50  # 50mm 단위 내림
                s_use = max(s_use, 100)

                lines.append((stir_tag, f"  전단:  Vc={Vc/1e3:.1f} kN  →  {int(ds):d}φ @ {s_use} mm  {stir_note}\n"))

                # 접두사 선택 (fy 기준)
                pfx = "UHD" if fy >= 500 else ("SHD" if fy >= 400 else "HD")
                result_store[zone_name] = {
                    "top":  f"{n_bar}-{pfx}{int(db)}",
                    "bot":  f"{n_bar}-{pfx}{int(db)}",
                    "stir": f"{pfx}{int(ds)}@{s_use}",
                    "As_req": As_req, "As_prov": As_prov,
                    "Vc": Vc, "s_use": s_use,
                }

            lines.append(("dim", f"\n  {'─'*48}\n"))
            lines.append(("ok",  "  ✔ 계산 완료. [결과 적용] 버튼으로 행에 반영하세요.\n"))

            self._result = result_store

            # 결과 텍스트 출력
            self._result_text.config(state="normal")
            self._result_text.delete("1.0", "end")
            for tag, txt in lines:
                self._result_text.insert("end", txt, tag)
            self._result_text.config(state="disabled")

        except ValueError as e:
            messagebox.showerror("입력 오류", f"숫자를 입력하세요.\n{e}", parent=self)

    # ── 결과 적용 ─────────────────────────────────────────
    def _apply_result(self):
        """설계 결과를 AutoTable 행 rv에 반영"""
        if not self._result:
            messagebox.showwarning("알림", "먼저 [설계 실행]을 클릭하세요.", parent=self)
            return

        mapping = {
            "단부(i)": ("em_top",  "em_bot",  "em_stir"),
            "중앙부":  ("cen_top", "cen_bot", "cen_stir"),
            "단부(j)": ("ev_top",  "ev_bot",  "ev_stir"),
        }

        applied = []
        for zone_name, keys in mapping.items():
            res = self._result.get(zone_name)
            if not res: continue
            top_k, bot_k, stir_k = keys
            for k, val in [(top_k, res["top"]), (bot_k, res["bot"]), (stir_k, res["stir"])]:
                widget = self.parent_rv.get(k)
                if widget and hasattr(widget, "set"):
                    widget.set(val)
                    applied.append(k)

        if applied:
            messagebox.showinfo("적용 완료",
                f"설계 결과가 행에 반영되었습니다.\n적용 항목: {', '.join(applied)}",
                parent=self)
        else:
            messagebox.showwarning("알림", "적용할 결과가 없습니다.", parent=self)

    def _center(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        w  = self.winfo_width();       h  = self.winfo_height()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")




# ── 진입점 ────────────────────────────────────────────────
def open_auto_table(parent=None, username=""):
    win = AutoTableApp(parent=parent, username=username)
    if parent:
        win.transient(parent); win.lift(); win.focus_force()
    return win

if __name__ == "__main__":
    root = tk.Tk(); root.withdraw()
    AutoTableApp(parent=root, username="test")
    root.mainloop()
