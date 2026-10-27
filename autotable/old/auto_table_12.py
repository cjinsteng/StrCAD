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
COL_DEFS = [
    ("부재명",    8,  "name",     None),
    ("폭\n(mm)",  5,  "width",    None),
    ("깊이\n(mm)",5,  "depth",    None),
    ("END\nM",    6,  "end_M",    None),
    ("END\nV",    5,  "end_V",    None),
    ("END 상부근",10, "end_top",  "rebar"),
    ("END 스터럽",10, "end_stir", "stirrup"),
    ("END 하부근",10, "end_bot",  "rebar"),
    ("CEN\nM",    6,  "cen_M",    None),
    ("CEN 상부근",10, "cen_top",  "rebar"),
    ("CEN 스터럽",10, "cen_stir", "stirrup"),
    ("CEN 하부근",10, "cen_bot",  "rebar"),
]
COL_KEYS = [c[2] for c in COL_DEFS]

DEFAULTS = {
    "name":"B1",  "width":"300",  "depth":"600",
    "end_M":"",   "end_V":"",
    "end_top":"3-UHD22",  "end_stir":"HD10@300",  "end_bot":"3-UHD22",
    "cen_M":"",
    "cen_top":"3-UHD22",  "cen_stir":"HD10@300",  "cen_bot":"3-UHD22",
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
    OX    = 62917.0
    OY    = 70080.0

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

        g(0,"SECTION"); g(2,"HEADER")
        g(9,"$ACADVER");     g(1,"AC1015")
        g(9,"$DWGCODEPAGE"); g(3,"ANSI_949")
        g(9,"$INSBASE");     g(10,"0.0"); g(20,"0.0"); g(30,"0.0")
        g(9,"$EXTMIN");      g(10,f"{ox:.4f}"); g(20,f"{oy:.4f}"); g(30,"0.0")
        g(9,"$EXTMAX");      g(10,f"{ex:.4f}"); g(20,f"{ey:.4f}"); g(30,"0.0")
        g(9,"$LIMMIN");      g(10,"0.0"); g(20,"0.0")
        g(9,"$LIMMAX");      g(10,"297.0"); g(20,"210.0")
        g(9,"$LTSCALE");     g(40,"50.0")
        g(9,"$TEXTSIZE");    g(40,"40.0")
        g(9,"$TEXTSTYLE");   g(7,"12")
        g(9,"$CLAYER");      g(8,"0")
        g(9,"$CELTYPE");     g(6,"BYLAYER")
        g(9,"$CECOLOR");     g(62,256)
        g(9,"$DIMSCALE");    g(40,"1.0")
        g(9,"$DIMSTYLE");    g(2,"STANDARD")
        g(9,"$INSUNITS");    g(70,4)
        g(9,"$MEASUREMENT"); g(70,1)
        g(9,"$CELWEIGHT");   g(370,-1)
        g(9,"$LWDISPLAY");   g(290,0)
        g(9,"$TILEMODE");    g(70,1)
        g(0,"ENDSEC")

        g(0,"SECTION"); g(2,"TABLES")
        g(0,"TABLE"); g(2,"LTYPE"); g(5,"5"); g(330,"0")
        g(100,"AcDbSymbolTable"); g(70,1)
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
#  배근표 그리기
# ══════════════════════════════════════════════════════════════
A4_CX = [0.0, 10.5, 79.0, 147.5, 210.0]
A4_HT = 195.0; A4_HB = 188.0; A4_RH = 47.0; A4_MG = 5.0

def _rt(ri): return A4_HB - ri * A4_RH
def _rb(ri): return A4_HB - (ri+1) * A4_RH
def _cx(i):  return (A4_CX[i]+A4_CX[i+1])/2

def _pn(s):
    m = re.match(r"(\d+)", (s or "").strip())
    return max(1, int(m.group(1))) if m else 2

def _sr(s):   # split rebar '3-UHD22' → ('3','UHD 22')
    m = re.match(r"(\d+)[-\s]*([A-Za-z]+)\s*(\d+)", (s or "").strip())
    return (m.group(1), f"{m.group(2)} {m.group(3)}") if m else ("", s or "")

def _ss(s):   # split stirrup 'HD10@300' → ('10','300')
    t = re.sub(r"[A-Za-z]+","", s or "")
    m = re.match(r"(\d+)[@\s]+(\d+)", t.strip())
    return (m.group(1), m.group(2)) if m else (t.strip(), "")

def _sdim(x0, yb, bw, bh):
    sx = min(24/max(bw,1), 36/max(bh,1))
    return bw*sx, bh*sx, x0+3.0, yb+3.5

def _dsec(d, ox, oy, sw, sh, tn, bn):
    cv = min(sw,sh)*0.10; br = max(0.4, min(sw,sh)*0.045)
    d.rect(ox, oy, sw, sh, layer="0", lw=30)
    d.rect(ox+cv, oy+cv, sw-2*cv, sh-2*cv, layer="DIM", lw=-3)
    def bars(n, yc):
        for i in range(n):
            x = ox+sw/2 if n==1 else ox+cv+(sw-2*cv)*i/(n-1)
            d.circle(x, yc, br, layer="2", color=1)
    bars(tn, oy+sh-cv); bars(bn, oy+cv)

def _ctxt(d, ci, ri, b, cen):
    x0=A4_CX[ci]; yt=_rt(ri); yb=_rb(ri); H=2.0; h=1.9
    M  = b.get("cen_M","")    if cen else b.get("end_M","")
    V  = ""                   if cen else b.get("end_V","")
    tp = b.get("cen_top","")  if cen else b.get("end_top","")
    st = b.get("cen_stir","") if cen else b.get("end_stir","")
    bt = b.get("cen_bot","")  if cen else b.get("end_bot","")
    ym = yt - 4.5
    d.text(x0+1, ym, "M=", hmm=H, layer="TEXT")
    if M: d.text(x0+4.5, ym, M, hmm=H, layer="edit", color=1)
    if cen:
        d.text(x0+16, ym, "kN.m", hmm=H, layer="TEXT")
    else:
        d.text(x0+16, ym, "kN.m, V=", hmm=H, layer="TEXT")
        if V: d.text(x0+30, ym, V, hmm=H, layer="edit", color=1)
        d.text(x0+42, ym, "kN", hmm=H, layer="TEXT")
    bw=float(b.get("width",300) or 300); bh=float(b.get("depth",600) or 600)
    sw,sh,ox,oy = _sdim(x0, yb, bw, bh); tx=ox+sw+2.5
    y1=oy+sh*0.70; y2=oy+sh*0.44; y3=oy+sh*0.18
    d.text(tx, y1, "-", hmm=h, layer="TEXT")
    if tp:
        c,s=_sr(tp); d.text(tx+2,y1,c,hmm=h,layer="edit",color=1)
        d.text(tx+4.5,y1,s,hmm=h,layer="edit",color=1)
    d.text(tx+15, y1, "(T)", hmm=h, layer="TEXT")
    d.text(tx, y2, "Str. HD", hmm=h, layer="TEXT")
    if st:
        sn,sp=_ss(st); d.text(tx+8,y2,sn,hmm=h,layer="edit",color=1)
        d.text(tx+11,y2,"@",hmm=h,layer="TEXT")
        d.text(tx+14,y2,sp,hmm=h,layer="edit",color=1)
    d.text(tx, y3, "-", hmm=h, layer="TEXT")
    if bt:
        c,s=_sr(bt); d.text(tx+2,y3,c,hmm=h,layer="edit",color=1)
        d.text(tx+4.5,y3,s,hmm=h,layer="edit",color=1)
    d.text(tx+15, y3, "(B)", hmm=h, layer="TEXT")

def make_beam_table_a4(beams, path):
    d=DXFWriter(pw=210,ph=297); M=A4_MG
    d.rect(M,M,210-2*M,297-2*M,layer="0",lw=50)
    d.line(M,A4_HT,210-M,A4_HT,layer="0",lw=30)
    d.line(M,A4_HB,210-M,A4_HB,layer="0",lw=30)
    nr=min(len(beams),4); tb=A4_HB-nr*A4_RH
    for cx in A4_CX[1:-1]: d.line(cx,tb,cx,A4_HT,layer="0",lw=20)
    d.text(M+1,(A4_HT+A4_HB)/2-1,"부재",hmm=2.8,layer="TEXT")
    for i,lb in enumerate(["END","CENTER","END"]):
        d.text(_cx(i+1),(A4_HT+A4_HB)/2-1,lb,hmm=3.2,layer="TEXT",halign=1)
    for ri in range(nr):
        b=beams[ri]; yt=_rt(ri); yb=_rb(ri)
        d.line(M,yb,210-M,yb,layer="0",lw=20)
        bw=float(b.get("width",300) or 300); bh=float(b.get("depth",600) or 600)
        d.text(M+0.5,yt-A4_RH*0.35,b.get("name","") or f"B{ri+1}",hmm=2.8,layer="TEXT")
        d.text(M+0.5,yt-A4_RH*0.60,str(int(bh)),hmm=2.2,layer="edit",color=1)
        for ci,cen in [(1,False),(2,True),(3,False)]:
            k="cen" if cen else "end"
            sw,sh,ox,oy=_sdim(A4_CX[ci],yb,bw,bh)
            _dsec(d,ox,oy,sw,sh,_pn(b.get(f"{k}_top","")),_pn(b.get(f"{k}_bot","")))
            _ctxt(d,ci,ri,b,cen)
        d.text(A4_CX[1]+0.5,yb+1.2,str(int(bw)),hmm=2.0,layer="edit",color=1)
    d.text(105,M+2,"PAGE NO.",hmm=2.5,layer="TEXT",halign=1)
    d.save(path)

def make_beam_table_a3(beams, path):
    d=DXFWriter(pw=420,ph=297)
    PW,PH,M,NB=420.0,297.0,5.0,20.0
    d.rect(M,M,PW-2*M,PH-2*M,layer="0",lw=50)
    n=max(len(beams),1); cw=(PW-2*M-NB)/n
    ht=PH-M; hb=ht-12.0; rb=[hb-i*6.0 for i in range(4)]
    sh=rb[3]-M
    for y in [ht,hb]+rb: d.line(M,y,PW-M,y,layer="0",lw=20)
    xnb=M+NB; d.line(xnb,M,xnb,ht,layer="0",lw=20)
    d.text(M+1,hb+4,"번  호",hmm=3.0,layer="TEXT")
    d.text(M+1,hb-1,"전 단 면",hmm=2.2,layer="DIM")
    for ri,rl in enumerate(["상 부 근","하 부 근","전    단"]):
        d.text(M+1,rb[ri+1]+1.5,rl,hmm=2.5,layer="TEXT")
    for i,b in enumerate(beams):
        x0=xnb+i*cw; xc=x0+cw/2
        d.line(x0,M,x0,ht,layer="0",lw=20)
        d.text(xc,hb+4,b.get("name","") or f"B{i+1}",hmm=3.5,layer="edit",color=1,halign=1)
        d.text(xc,hb-1,"전 단 면",hmm=2.2,layer="DIM",halign=1)
        bw=float(b.get("width",300) or 300); bh=float(b.get("depth",600) or 600)
        sx=min((cw*0.45)/bw,(sh*0.65)/bh)
        sw=bw*sx; sh2=bh*sx; ox=xc-sw/2; oy=M+(sh-sh2)/2
        _dsec(d,ox,oy,sw,sh2,_pn(b.get("end_top","")),_pn(b.get("end_bot","")))
        d.text(ox-0.5,oy+sh2/2,str(int(bh)),hmm=1.8,layer="edit",color=1,halign=2)
        d.text(xc,oy-2.5,str(int(bw)),hmm=1.8,layer="edit",color=1,halign=1)
        for ri,rk in enumerate(["end_top","end_bot","end_stir"]):
            v=b.get(rk,"") or ""
            if v: d.text(x0+1,rb[ri+1]+1.5,v,hmm=2.3,layer="edit",color=1)
    d.line(PW-M,M,PW-M,ht,layer="0",lw=20)
    d.save(path)


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

    def _kalt(self, e):
        """Alt+Enter — 현재 행 전체를 아래에 복사"""
        self._close_pop()
        if self.cb_alt:
            self.cb_alt()
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

        hf = tk.Frame(outer, bg=BG3); hf.pack(fill="x")
        for lbl, w, key, _ in COL_DEFS:
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
        # rv에 위젯 참조를 직접 저장 (포커스 이동에 사용)
        rv = {"__frame__": fr, "__widgets__": {}}

        for lbl, w, key, mode in COL_DEFS:
            init = ""
            if copy_from and key in copy_from:
                src = copy_from[key]
                init = src.get() if hasattr(src,"get") else ""
            else:
                init = DEFAULTS.get(key,"")

            if mode:
                se = SmartEntry(fr, width=w, mode=mode,
                    cb_alt  = lambda _rv=rv: self._do_alt(_rv),
                    cb_shift= lambda _rv=rv, _k=key: self._do_shift(_rv, _k),
                    cb_up   = lambda _rv=rv, _k=key: self._do_nav(_rv, _k, -1),
                    cb_dn   = lambda _rv=rv, _k=key: self._do_nav(_rv, _k, +1),
                )
                se.set(init); se.pack(side="left", padx=1)
                rv[key] = se
                rv["__widgets__"][key] = se
            else:
                var = tk.StringVar(value=init)
                ent = tk.Entry(fr, textvariable=var,
                               font=("Malgun Gothic",9), bg=BG3, fg=TXT,
                               insertbackground=WHI, relief="flat", width=w,
                               highlightbackground=BDR, highlightthickness=1)
                ent.pack(side="left", padx=1, ipady=4)
                ent.bind("<FocusIn>",     lambda e, _e=ent: _e.config(highlightbackground=ACCH))
                ent.bind("<FocusOut>",    lambda e, _e=ent: _e.config(highlightbackground=BDR))
                def _on_entry_shift(e, _rv=rv, _k=key):
                    self._do_shift(_rv, _k)
                    return "break"
                def _on_entry_alt(e, _rv=rv):
                    self._do_alt(_rv)
                    return "break"
                def _on_entry_enter(e):
                    return "break"
                # Shift/Alt 먼저 바인딩 (more specific → 우선 매칭)
                ent.bind("<Shift-Return>",   _on_entry_shift)
                ent.bind("<Shift-KP_Enter>", _on_entry_shift)
                ent.bind("<Alt-Return>",     _on_entry_alt)
                ent.bind("<Alt-KP_Enter>",   _on_entry_alt)
                ent.bind("<Return>",         _on_entry_enter)
                ent.bind("<KP_Enter>",       _on_entry_enter)
                ent.bind("<Up>",  lambda e, _rv=rv, _k=key: (self._do_nav(_rv,_k,-1),"break")[1])
                ent.bind("<Down>",lambda e, _rv=rv, _k=key: (self._do_nav(_rv,_k,+1),"break")[1])
                rv[key] = var
                rv["__widgets__"][key] = ent

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
        result = []
        for rv in self.beam_rows:
            d = {}
            for k in COL_KEYS:
                v = rv.get(k)
                d[k] = v.get() if (v and hasattr(v,"get")) else ""
            result.append(d)
        return result

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
