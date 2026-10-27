"""
Auto Table  —  보/기둥/슬래브/벽 배근표 자동 작성 및 CAD 출력
autotable 폴더 내 독립 실행 모듈
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import math, os

# ── 팔레트 (launcher 동일 테마) ──────────────────────────────
BG  = "#0f1520"; BG2 = "#141d2e"; BG3 = "#1a2540"
BG4 = "#1f2d4a"; BG5 = "#263556"
BDR = "#2c3f62"; BDR2= "#3a5280"
ACC = "#1a56db"; ACCH= "#2563eb"
GRN = "#15803d"; GRNH= "#16a34a"
RED = "#dc2626"; ORG = "#d97706"; BLU = "#3b82f6"
TXT = "#dde4f0"; TX2 = "#8fa3c0"; TX3 = "#546887"
WHI = "#f0f5ff"; DIS = "#3d5070"


# ══════════════════════════════════════════════════════════════
#  DXF 순수 Python 생성기
# ══════════════════════════════════════════════════════════════
class DXFWriter:
    """ezdxf 없이 DXF R2010 파일 직접 생성"""

    def __init__(self):
        self.entities = []
        self.layers   = {}          # name -> color_index

    def add_layer(self, name, color=7):
        self.layers[name] = color

    # ── 기본 도형 ───────────────────────────────────────────
    def line(self, x1,y1, x2,y2, layer="0", lw=0):
        self.entities.append(("LINE", layer, x1,y1, x2,y2, lw))

    def rect(self, x,y, w,h, layer="0", lw=0):
        self.line(x,y,   x+w,y,   layer, lw)
        self.line(x+w,y, x+w,y+h, layer, lw)
        self.line(x+w,y+h, x,y+h, layer, lw)
        self.line(x,y+h, x,y,     layer, lw)

    def text(self, x,y, txt, height=2.5, layer="0", halign=0, color=7):
        self.entities.append(("TEXT", layer, x, y, txt, height, halign, color))

    def mtext(self, x,y, txt, height=2.5, width=50, layer="0", color=7):
        self.entities.append(("MTEXT", layer, x, y, txt, height, width, color))

    def circle(self, cx,cy, r, layer="0"):
        self.entities.append(("CIRCLE", layer, cx, cy, r))

    def arc(self, cx,cy,r, sa,ea, layer="0"):
        self.entities.append(("ARC", layer, cx,cy,r, sa,ea))

    # ── DXF 직렬화 ─────────────────────────────────────────
    def save(self, filepath):
        lines = []
        def w(*args):
            for pair in args: lines.append(f"{pair[0]}\n{pair[1]}")

        # HEADER
        lines.append("  0\nSECTION\n  2\nHEADER")
        lines.append("  9\n$ACADVER\n  1\nAC1015")
        lines.append("  9\n$INSUNITS\n 70\n4")
        lines.append("  0\nENDSEC")

        # TABLES
        lines.append("  0\nSECTION\n  2\nTABLES")
        lines.append("  0\nTABLE\n  2\nLAYER\n 70\n100")
        default_layers = {"0":7,"FRAME":7,"REBAR":1,"DIM":3,"TEXT":7,"RED_TEXT":1,"TITLE":7}
        default_layers.update(self.layers)
        for lname, cidx in default_layers.items():
            lines.append(f"  0\nLAYER\n  2\n{lname}\n 70\n0\n 62\n{cidx}\n  6\nCONTINUOUS")
        lines.append("  0\nENDTABLE")
        lines.append("  0\nENDSEC")

        # ENTITIES
        lines.append("  0\nSECTION\n  2\nENTITIES")
        for ent in self.entities:
            kind = ent[0]
            if kind == "LINE":
                _, layer, x1,y1,x2,y2, lw = ent
                lines.append(f"  0\nLINE\n  8\n{layer}\n"
                              f" 10\n{x1:.4f}\n 20\n{y1:.4f}\n 30\n0.0\n"
                              f" 11\n{x2:.4f}\n 21\n{y2:.4f}\n 31\n0.0")
                if lw: lines[-1] += f"\n 370\n{lw}"

            elif kind == "TEXT":
                _, layer, x, y, txt, h, halign, color = ent
                lines.append(f"  0\nTEXT\n  8\n{layer}\n 62\n{color}\n"
                              f" 10\n{x:.4f}\n 20\n{y:.4f}\n 30\n0.0\n"
                              f" 40\n{h:.4f}\n  1\n{txt}\n 72\n{halign}")

            elif kind == "MTEXT":
                _, layer, x, y, txt, h, width, color = ent
                txt_esc = txt.replace("\n","\\P")
                lines.append(f"  0\nMTEXT\n  8\n{layer}\n 62\n{color}\n"
                              f" 10\n{x:.4f}\n 20\n{y:.4f}\n 30\n0.0\n"
                              f" 40\n{h:.4f}\n 41\n{width:.4f}\n  1\n{txt_esc}")

            elif kind == "CIRCLE":
                _, layer, cx,cy,r = ent
                lines.append(f"  0\nCIRCLE\n  8\n{layer}\n"
                              f" 10\n{cx:.4f}\n 20\n{cy:.4f}\n 30\n0.0\n 40\n{r:.4f}")

            elif kind == "ARC":
                _, layer, cx,cy,r,sa,ea = ent
                lines.append(f"  0\nARC\n  8\n{layer}\n"
                              f" 10\n{cx:.4f}\n 20\n{cy:.4f}\n 30\n0.0\n 40\n{r:.4f}\n"
                              f" 50\n{sa:.4f}\n 51\n{ea:.4f}")

        lines.append("  0\nENDSEC\n  0\nEOF")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


# ══════════════════════════════════════════════════════════════
#  보 단면 스케치 (DXF 기하)
# ══════════════════════════════════════════════════════════════
def draw_beam_section(dxf, ox, oy, bw, bh, scale=0.1,
                      top_bars="", bot_bars="", stir="",
                      label="", show_dim=True):
    """
    ox,oy : 섹션 좌하단 기준점 (DXF mm 단위)
    bw,bh : 보폭, 보깊이 (mm)
    scale : 1mm = scale DXF units  (A4≈0.12, A3≈0.16)
    """
    W = bw * scale
    H = bh * scale
    cvr = 40 * scale   # 피복 40mm
    bar_r = 6 * scale

    # 외곽 단면
    dxf.rect(ox, oy, W, H, layer="FRAME", lw=30)

    # 내부 (피복선)
    dxf.rect(ox+cvr, oy+cvr, W-2*cvr, H-2*cvr, layer="DIM")

    # 상단 철근
    if top_bars.strip():
        n = _parse_bar_count(top_bars)
        _draw_bar_row(dxf, ox, oy+H-cvr, W, n, bar_r, layer="REBAR")

    # 하단 철근
    if bot_bars.strip():
        n = _parse_bar_count(bot_bars)
        _draw_bar_row(dxf, ox, oy+cvr, W, n, bar_r, layer="REBAR")

    # 치수 (폭 × 깊이)
    if show_dim:
        dxf.text(ox + W/2, oy - 4, f"{bw}×{bh}",
                 height=2.0, layer="DIM", halign=1)

    # 라벨
    if label:
        dxf.text(ox - 2, oy + H/2, label,
                 height=2.5, layer="TEXT", halign=2)


def _parse_bar_count(spec):
    """'3-UHD22T' → 3, '16-UHD32' → 16  (숫자만 추출)"""
    import re
    m = re.match(r"(\d+)", spec.strip())
    return int(m.group(1)) if m else 2


def _draw_bar_row(dxf, ox, cy, W, n, r, layer="REBAR"):
    cvr = r * 2
    span = W - 2*cvr
    if n <= 1:
        dxf.circle(ox + W/2, cy, r, layer=layer)
    else:
        for i in range(n):
            x = ox + cvr + span * i / (n-1)
            dxf.circle(x, cy, r, layer=layer)


# ══════════════════════════════════════════════════════════════
#  A4 보 배근표 DXF 생성
# ══════════════════════════════════════════════════════════════
def make_beam_table_a4(beams, filepath):
    """
    beams : list of dict
      {name, width, depth,
       end_M, end_V,
       end_top, end_bot, end_stir,
       cen_M,
       cen_top, cen_bot, cen_stir}
    """
    dxf = DXFWriter()
    # A4 = 210×297mm → DXF 단위 1:1 mm
    PW, PH = 297, 210   # 가로(landscape)

    # 용지 테두리
    MARGIN = 10
    dxf.rect(MARGIN, MARGIN, PW-2*MARGIN, PH-2*MARGIN, layer="FRAME", lw=50)

    # 표 헤더
    col_x = [MARGIN, MARGIN+15, MARGIN+15+95, MARGIN+15+95+90, MARGIN+15+95+90+85]
    row_h   = 8
    hdr_y   = PH - MARGIN - row_h

    headers = ["부재", "END", "CENTER", "END"]
    sub_hdr = ["위치", "M=  kN.m  V=  kN", "M=  kN.m", "M=  kN.m  V=  kN"]

    for i, (hdr, sub) in enumerate(zip(headers, sub_hdr)):
        cx = col_x[i] + (col_x[i+1]-col_x[i])/2 if i < 3 else col_x[i]
        dxf.text(col_x[i]+2, hdr_y+2, hdr, height=3.0, layer="TEXT")
        dxf.text(col_x[i]+2, hdr_y-3, sub, height=2.0, layer="DIM")

    # 헤더 구분선
    y_top = PH - MARGIN
    dxf.line(MARGIN, y_top - row_h*2, PW-MARGIN, y_top - row_h*2, layer="FRAME")
    for cx in col_x:
        dxf.line(cx, MARGIN, cx, y_top, layer="FRAME")
    dxf.line(PW-MARGIN, MARGIN, PW-MARGIN, y_top, layer="FRAME")

    # 각 보 행 그리기
    row_height = 40    # 한 행 높이 mm
    sec_scale  = 0.08

    for idx, b in enumerate(beams[:4]):   # A4에 최대 4행
        y0 = hdr_y - row_h*2 - idx*row_height - row_height
        dxf.line(MARGIN, y0, PW-MARGIN, y0, layer="FRAME")

        bw = int(b.get("width",  300))
        bh = int(b.get("depth",  600))

        # 부재명
        dxf.text(MARGIN+1, y0 + row_height/2,
                 b.get("name","B1"), height=3.0, layer="TEXT")
        dxf.text(MARGIN+1, y0 + row_height/2 - 5,
                 f"{bh}", height=2.5, layer="DIM")

        # END 단면 (좌)
        ex1 = col_x[1] + 5
        draw_beam_section(dxf, ex1, y0+5, bw, bh,
                          scale=sec_scale,
                          top_bars=b.get("end_top",""),
                          bot_bars=b.get("end_bot",""),
                          stir=b.get("end_stir",""),
                          label="", show_dim=True)
        # END 텍스트
        _write_beam_text(dxf, ex1 + bw*sec_scale + 3, y0+5,
                         b.get("end_top",""), b.get("end_stir",""), b.get("end_bot",""),
                         b.get("end_M",""), b.get("end_V",""), row_height, is_end=True)

        # CENTER 단면
        cx1 = col_x[2] + 8
        draw_beam_section(dxf, cx1, y0+5, bw, bh,
                          scale=sec_scale,
                          top_bars=b.get("cen_top",""),
                          bot_bars=b.get("cen_bot",""),
                          show_dim=False)
        _write_beam_text(dxf, cx1 + bw*sec_scale + 3, y0+5,
                         b.get("cen_top",""), b.get("cen_stir",""), b.get("cen_bot",""),
                         b.get("cen_M",""), "", row_height, is_end=False)

        # END 단면 (우) - 동일 데이터
        ex2 = col_x[3] + 5
        draw_beam_section(dxf, ex2, y0+5, bw, bh,
                          scale=sec_scale,
                          top_bars=b.get("end_top",""),
                          bot_bars=b.get("end_bot",""),
                          show_dim=False)
        _write_beam_text(dxf, ex2 + bw*sec_scale + 3, y0+5,
                         b.get("end_top",""), b.get("end_stir",""), b.get("end_bot",""),
                         b.get("end_M",""), b.get("end_V",""), row_height, is_end=True)

        # 보 폭 치수
        dxf.text(MARGIN+1, y0+3, f"{bw}", height=2.0, layer="DIM")

    # 하단 테두리선
    bot_y = hdr_y - row_h*2 - len(beams[:4])*row_height
    dxf.line(MARGIN, bot_y, PW-MARGIN, bot_y, layer="FRAME")

    # 페이지 번호
    dxf.text(PW/2, MARGIN+2, "PAGE NO.", height=2.5, layer="DIM", halign=1)

    dxf.save(filepath)


def _write_beam_text(dxf, x, y, top, stir, bot, M, V, row_h, is_end=True):
    h = 2.2; dy = row_h / 4
    # 상단 철근
    if top:
        dxf.text(x, y + dy*3, f"- {top} (T)", height=h, layer="RED_TEXT", color=1)
    # 스터럽
    if stir:
        dxf.text(x, y + dy*2, f"Str. {stir}", height=h, layer="RED_TEXT", color=1)
    # 하단 철근
    if bot:
        dxf.text(x, y + dy*1, f"- {bot} (B)", height=h, layer="RED_TEXT", color=1)
    # M, V
    if M:
        dxf.text(x, y + row_h - 4, f"M= {M} kN.m", height=h, layer="TEXT")
    if V:
        dxf.text(x + 30, y + row_h - 4, f"V= {V} kN", height=h, layer="TEXT")


# ══════════════════════════════════════════════════════════════
#  A3 보 배근표 DXF 생성
# ══════════════════════════════════════════════════════════════
def make_beam_table_a3(beams, filepath):
    """A3 = 420×297mm landscape  —  A4 대비 2배 폭, 더 많은 부재 수용"""
    dxf = DXFWriter()
    PW, PH = 420, 297
    MARGIN = 10

    dxf.rect(MARGIN, MARGIN, PW-2*MARGIN, PH-2*MARGIN, layer="FRAME", lw=50)

    # 열 구성: 부재명 | -1열 | 1열 | 2-3열 | 4열 | PIT열 ...
    # A3에서는 한 행에 1개 보, 가로로 여러 스팬 표현
    col_names = [b.get("name","─") for b in beams]
    n_cols = max(len(beams), 3)

    # 부재명 행 헤더
    hdr_y = PH - MARGIN - 8
    col_w = (PW - 2*MARGIN - 20) / n_cols
    sec_scale = 0.10

    dxf.text(MARGIN+1, hdr_y+2, "번 호", height=3.0, layer="TEXT")
    dxf.text(MARGIN+1, hdr_y-4, "전 단면", height=2.5, layer="DIM")

    for i, b in enumerate(beams):
        cx = MARGIN + 20 + i*col_w
        dxf.text(cx + col_w/2, hdr_y+2, b.get("name",""), height=3.0, layer="TEXT", halign=1)
        dxf.text(cx + col_w/2, hdr_y-4, "전 단 면", height=2.0, layer="DIM", halign=1)

    # 구분선
    dxf.line(MARGIN, hdr_y, PW-MARGIN, hdr_y, layer="FRAME")
    dxf.line(MARGIN, hdr_y-8, PW-MARGIN, hdr_y-8, layer="FRAME")
    dxf.line(MARGIN+20, MARGIN, MARGIN+20, PH-MARGIN, layer="FRAME")

    row_h = (PH - 2*MARGIN - 16) * 0.55   # 단면 영역 높이

    for i, b in enumerate(beams):
        bw = int(b.get("width", 300))
        bh = int(b.get("depth", 600))
        cx = MARGIN + 20 + i*col_w + col_w*0.1

        # 단면 그리기
        draw_beam_section(dxf, cx, MARGIN + (PH-2*MARGIN)*0.3,
                          bw, bh, scale=sec_scale,
                          top_bars=b.get("end_top",""),
                          bot_bars=b.get("end_bot",""),
                          show_dim=True)

        # 철근 텍스트 (단면 우측)
        tx = cx + bw*sec_scale + 4
        ty = MARGIN + (PH-2*MARGIN)*0.3
        h  = 2.0
        top = b.get("end_top","")
        stir= b.get("end_stir","")
        bot = b.get("end_bot","")
        if top:  dxf.text(tx, ty + bh*sec_scale*0.75, f"- {top} (T)", height=h, layer="RED_TEXT", color=1)
        if stir: dxf.text(tx, ty + bh*sec_scale*0.45, f"Str. {stir}",   height=h, layer="RED_TEXT", color=1)
        if bot:  dxf.text(tx, ty + bh*sec_scale*0.15, f"- {bot} (B)", height=h, layer="RED_TEXT", color=1)

    # 하단 상부근/하부근/스터럽 행
    rows = [("상 부 근", "end_top"), ("하 부 근", "end_bot"), ("전   단", "end_stir")]
    row_labels_y = MARGIN + 18
    for ri, (rlbl, rkey) in enumerate(rows):
        ry = row_labels_y + ri*6
        dxf.text(MARGIN+1, ry, rlbl, height=2.0, layer="TEXT")
        dxf.line(MARGIN, ry-1, PW-MARGIN, ry-1, layer="FRAME")
        for i, b in enumerate(beams):
            cx = MARGIN + 20 + i*col_w + 3
            val = b.get(rkey, "")
            if val:
                dxf.text(cx, ry, val, height=2.0, layer="RED_TEXT", color=1)

    # 하단 경계
    dxf.line(MARGIN, row_labels_y-1, PW-MARGIN, row_labels_y-1, layer="FRAME")
    # 세로선들
    for i in range(len(beams)+1):
        lx = MARGIN + 20 + i*col_w
        dxf.line(lx, MARGIN, lx, PH-MARGIN, layer="FRAME")

    dxf.save(filepath)


# ══════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════
MEMBER_TYPES = ["보(Beam)", "기둥(Column)", "슬래브(Slab)", "벽(Wall)"]

class AutoTableApp(tk.Toplevel):
    def __init__(self, parent=None, username=""):
        if parent:
            super().__init__(parent)
        else:
            # 독립 실행시
            self._root = tk.Tk()
            self._root.withdraw()
            super().__init__(self._root)
        self.title(f"Auto Table  —  배근표 자동 작성")
        self.geometry("1100x720"); self.minsize(900,600)
        self.configure(bg=BG)
        self.username = username
        self.beam_rows = []   # 보 데이터 행 목록
        self._build()
        self._center()

    # ── 레이아웃 ───────────────────────────────────────────
    def _build(self):
        self._build_hdr()
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")
        self._build_body()
        tk.Frame(self, bg=BDR, height=1).pack(fill="x", side="bottom")
        self._build_ftr()

    def _build_hdr(self):
        hdr = tk.Frame(self, bg=BG2, height=56); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📊  Auto Table",
                 font=("Malgun Gothic",14,"bold"), bg=BG2, fg=WHI).pack(side="left", padx=20)
        tk.Label(hdr, text="보·기둥·슬래브·벽 배근표 자동 작성 및 CAD 출력",
                 font=("Malgun Gothic",9), bg=BG2, fg=TX2).pack(side="left", padx=8)
        if self.username:
            tk.Label(hdr, text=f"({self.username})", font=("Malgun Gothic",9),
                     bg=BG2, fg=TX3).pack(side="right", padx=20)

    def _build_body(self):
        body = tk.Frame(self, bg=BG); body.pack(fill="both", expand=True, padx=0, pady=0)

        # 좌: 부재 유형 탭
        left = tk.Frame(body, bg=BG2, width=160); left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="부재 유형", font=("Malgun Gothic",10,"bold"),
                 bg=BG2, fg=TX2, pady=12).pack(fill="x")
        tk.Frame(left, bg=BDR, height=1).pack(fill="x")

        self._type_var = tk.StringVar(value="보(Beam)")
        self._type_btns = []
        for mt in MEMBER_TYPES:
            b = tk.Button(left, text=mt, font=("Malgun Gothic",10),
                          bg=BG2, fg=TXT, relief="flat", cursor="hand2",
                          pady=12, anchor="w", padx=16,
                          command=lambda t=mt: self._switch_type(t))
            b.pack(fill="x")
            self._type_btns.append((mt, b))

        tk.Frame(left, bg=BDR, height=1).pack(fill="x", pady=8)

        # 우: 콘텐츠 영역
        right = tk.Frame(body, bg=BG); right.pack(side="left", fill="both", expand=True)
        self._content = right
        self._switch_type("보(Beam)")

    def _build_ftr(self):
        ftr = tk.Frame(self, bg=BG2, height=42); ftr.pack(fill="x", side="bottom")
        ftr.pack_propagate(False)
        def mkb(txt, cmd, bg=ACC):
            b = tk.Button(ftr, text=txt, command=cmd,
                          font=("Malgun Gothic",10,"bold"),
                          bg=bg, fg=WHI, relief="flat", cursor="hand2",
                          padx=18, pady=6)
            b.bind("<Enter>", lambda _,b=b,c=bg: b.config(bg=_lighten(c)))
            b.bind("<Leave>", lambda _,b=b,c=bg: b.config(bg=c))
            b.pack(side="right", padx=8, pady=6)
        mkb("📄  A4 DXF 출력", self._export_a4)
        mkb("📋  A3 DXF 출력", self._export_a3, bg=GRN)
        mkb("➕  행 추가",      self._add_row,   bg="#374151")
        tk.Label(ftr, text="STR Design & Check  |  Auto Table  v1.0",
                 font=("Malgun Gothic",8), bg=BG2, fg=TX3).pack(side="left", padx=20)

    # ── 타입 전환 ──────────────────────────────────────────
    def _switch_type(self, t):
        self._type_var.set(t)
        for mt, b in self._type_btns:
            b.config(bg=BG3 if mt==t else BG2,
                     fg=WHI if mt==t else TXT)
        for w in self._content.winfo_children(): w.destroy()
        if t == "보(Beam)":
            self._build_beam_panel()
        else:
            self._build_placeholder(t)

    def _build_placeholder(self, t):
        fr = tk.Frame(self._content, bg=BG); fr.pack(fill="both", expand=True)
        tk.Label(fr, text=f"🚧  {t}\n\n준비 중입니다.",
                 font=("Malgun Gothic",14), bg=BG, fg=TX3).pack(expand=True)

    # ── 보 패널 ────────────────────────────────────────────
    def _build_beam_panel(self):
        outer = tk.Frame(self._content, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        # 컬럼 헤더
        hdr_cols = [
            ("부재명",10), ("폭\n(mm)",6), ("깊이\n(mm)",6),
            ("END\nM(kN.m)",8), ("END\nV(kN)",8),
            ("END 상부근",12), ("END 스터럽",12), ("END 하부근",12),
            ("CENTER\nM(kN.m)",8),
            ("CEN 상부근",12), ("CEN 스터럽",12), ("CEN 하부근",12),
            ("삭제",5)
        ]
        self._col_keys = [
            "name","width","depth",
            "end_M","end_V","end_top","end_stir","end_bot",
            "cen_M","cen_top","cen_stir","cen_bot"
        ]
        self._col_widths = [c[1] for c in hdr_cols]

        # 헤더 프레임
        hf = tk.Frame(outer, bg=BG3); hf.pack(fill="x")
        for (label, w) in hdr_cols:
            tk.Label(hf, text=label, font=("Malgun Gothic",8,"bold"),
                     bg=BG3, fg=TX2, width=w, pady=4,
                     relief="flat", bd=0).pack(side="left")

        # 스크롤 가능 데이터 영역
        canvas_frame = tk.Frame(outer, bg=BG); canvas_frame.pack(fill="both", expand=True, pady=(2,0))
        canvas = tk.Canvas(canvas_frame, bg=BG, bd=0, highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._row_frame = tk.Frame(canvas, bg=BG)
        self._row_win = canvas.create_window((0,0), window=self._row_frame, anchor="nw")
        self._row_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._row_win, width=e.width))
        self._canvas = canvas

        # 기존 행 재구성
        self.beam_rows.clear()
        for _ in range(3):
            self._add_row()

        # 미리보기 캔버스
        pv_frame = tk.LabelFrame(outer, text=" 단면 미리보기 ", font=("Malgun Gothic",8),
                                  bg=BG, fg=TX2, bd=1, relief="flat",
                                  highlightbackground=BDR, highlightthickness=1)
        pv_frame.pack(fill="x", pady=(8,0))
        self._pv_canvas = tk.Canvas(pv_frame, bg="#ffffff", height=120, bd=0, highlightthickness=0)
        self._pv_canvas.pack(fill="x", padx=4, pady=4)
        self._pv_canvas.bind("<Configure>", lambda e: self._refresh_preview())

    def _add_row(self):
        fr = tk.Frame(self._row_frame, bg=BG4); fr.pack(fill="x", pady=1)
        row_vars = {}
        defaults = {
            "name":"B1","width":"300","depth":"600",
            "end_M":"","end_V":"",
            "end_top":"3-UHD22","end_stir":"HD10@300","end_bot":"3-UHD22",
            "cen_M":"",
            "cen_top":"3-UHD22","cen_stir":"HD10@300","cen_bot":"3-UHD22"
        }
        for key, w in zip(self._col_keys, self._col_widths[:-1]):
            v = tk.StringVar(value=defaults.get(key,""))
            v.trace_add("write", lambda *a: self._refresh_preview())
            e = tk.Entry(fr, textvariable=v,
                         font=("Malgun Gothic",9), bg=BG3, fg=TXT,
                         insertbackground=WHI, relief="flat", width=w,
                         highlightbackground=BDR, highlightthickness=1)
            e.pack(side="left", padx=1, ipady=4)
            row_vars[key] = v

        # 삭제 버튼
        def _del(f=fr, rv=row_vars):
            if len(self.beam_rows) <= 1:
                messagebox.showwarning("경고", "최소 1개 행은 필요합니다.", parent=self)
                return
            self.beam_rows.remove(rv)
            f.destroy()
            self._refresh_preview()

        tk.Button(fr, text="✕", command=_del,
                  font=("Malgun Gothic",9), bg=RED, fg=WHI,
                  relief="flat", cursor="hand2", width=3, pady=3).pack(side="left", padx=2)

        self.beam_rows.append(row_vars)
        self._refresh_preview()

    # ── 미리보기 ───────────────────────────────────────────
    def _refresh_preview(self):
        if not hasattr(self, "_pv_canvas"): return
        c = self._pv_canvas
        c.delete("all")
        cw = c.winfo_width() or 600
        ch = c.winfo_height() or 120
        if not self.beam_rows: return

        n = len(self.beam_rows)
        slot_w = cw / n
        for i, rv in enumerate(self.beam_rows):
            try:
                bw = int(rv["width"].get() or 300)
                bh = int(rv["depth"].get() or 600)
                name = rv["name"].get() or f"B{i+1}"
            except: continue

            scale = min((slot_w*0.5)/bw, (ch*0.6)/bh)
            ox = i*slot_w + slot_w*0.2
            oy = ch*0.15
            W = bw*scale; H = bh*scale

            # 단면 그리기
            c.create_rectangle(ox, oy, ox+W, oy+H, outline="#444", width=2, fill="#e8e8e8")
            # 피복선
            cvr = min(8, W*0.1, H*0.1)
            c.create_rectangle(ox+cvr, oy+cvr, ox+W-cvr, oy+H-cvr, outline="#aaa", width=1)
            # 상부근
            top = rv["end_top"].get()
            bot = rv["end_bot"].get()
            r_px = max(3, W*0.05)
            nt = _parse_bar_count(top) if top else 2
            nb = _parse_bar_count(bot) if bot else 2
            for j in range(nt):
                x = ox + cvr + (W-2*cvr)*j/(max(nt-1,1))
                c.create_oval(x-r_px, oy+cvr-r_px, x+r_px, oy+cvr+r_px, fill="#e74c3c", outline="")
            for j in range(nb):
                x = ox + cvr + (W-2*cvr)*j/(max(nb-1,1))
                c.create_oval(x-r_px, oy+H-cvr-r_px, x+r_px, oy+H-cvr+r_px, fill="#e74c3c", outline="")

            # 라벨
            c.create_text(ox+W/2, oy+H+8, text=f"{name}\n{bw}×{bh}",
                          font=("Malgun Gothic",7), fill="#333", justify="center")

    # ── 데이터 수집 ────────────────────────────────────────
    def _collect_beams(self):
        beams = []
        for rv in self.beam_rows:
            d = {k: rv[k].get() for k in self._col_keys}
            beams.append(d)
        return beams

    # ── 출력 ───────────────────────────────────────────────
    def _export_a4(self):
        beams = self._collect_beams()
        if not beams:
            messagebox.showwarning("경고","데이터가 없습니다.", parent=self); return
        path = filedialog.asksaveasfilename(
            defaultextension=".dxf",
            filetypes=[("DXF 파일","*.dxf"),("모든 파일","*.*")],
            title="A4 DXF 저장",
            initialfile="beam_table_A4.dxf",
            parent=self)
        if not path: return
        try:
            make_beam_table_a4(beams, path)
            messagebox.showinfo("완료", f"A4 DXF 파일이 저장되었습니다.\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("오류", str(e), parent=self)

    def _export_a3(self):
        beams = self._collect_beams()
        if not beams:
            messagebox.showwarning("경고","데이터가 없습니다.", parent=self); return
        path = filedialog.asksaveasfilename(
            defaultextension=".dxf",
            filetypes=[("DXF 파일","*.dxf"),("모든 파일","*.*")],
            title="A3 DXF 저장",
            initialfile="beam_table_A3.dxf",
            parent=self)
        if not path: return
        try:
            make_beam_table_a3(beams, path)
            messagebox.showinfo("완료", f"A3 DXF 파일이 저장되었습니다.\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("오류", str(e), parent=self)

    # ── 유틸 ───────────────────────────────────────────────
    def _center(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        w  = self.winfo_width();       h  = self.winfo_height()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")


def _lighten(hex_color, amt=20):
    r = min(255, int(hex_color[1:3],16)+amt)
    g = min(255, int(hex_color[3:5],16)+amt)
    b = min(255, int(hex_color[5:7],16)+amt)
    return f"#{r:02x}{g:02x}{b:02x}"


# ── 진입점 (launcher에서 호출) ────────────────────────────
def open_auto_table(parent=None, username=""):
    win = AutoTableApp(parent=parent, username=username)
    if parent:
        win.transient(parent)
        win.lift()
        win.focus_force()
    return win


# ── 독립 실행 ─────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk(); root.withdraw()
    app = AutoTableApp(parent=root, username="test")
    root.mainloop()
