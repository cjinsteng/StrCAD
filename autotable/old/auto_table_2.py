"""
Auto Table  —  보/기둥/슬래브/벽 배근표 자동 작성 및 CAD 출력
autotable/ 폴더 내 모듈  (launcher.py 에서 호출)

DXF 좌표계: 1mm = 83.33 DXF units (원본 beamA4.dxf 기준)
원점 offset: OX=62917, OY=70080  (EXTMIN)
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import re, os

# ── 팔레트 ──────────────────────────────────────────────────
BG  = "#0f1520"; BG2 = "#141d2e"; BG3 = "#1a2540"
BG4 = "#1f2d4a"; BG5 = "#263556"
BDR = "#2c3f62"; BDR2= "#3a5280"
ACC = "#1a56db"; ACCH= "#2563eb"
GRN = "#15803d"; GRNH= "#16a34a"
RED = "#dc2626"; ORG = "#d97706"; BLU = "#3b82f6"
TXT = "#dde4f0"; TX2 = "#8fa3c0"; TX3 = "#546887"
WHI = "#f0f5ff"; DIS = "#3d5070"

MEMBER_TYPES = ["보(Beam)", "기둥(Column)", "슬래브(Slab)", "벽(Wall)"]


# ══════════════════════════════════════════════════════════════
#  DXF 생성기  (원본 beamA4.dxf 좌표계 기반)
# ══════════════════════════════════════════════════════════════
class DXFWriter:
    """AutoCAD 호환 DXF R2010 직접 생성"""
    SCALE = 83.333      # 1 mm = 83.333 DXF units (beamA4.dxf 실측)
    OX    = 62917.0     # 도면 원점 X (EXTMIN)
    OY    = 70080.0     # 도면 원점 Y

    def __init__(self, paper_w=210, paper_h=297):
        self._ents   = []
        self._layers = {}
        self.pw = paper_w
        self.ph = paper_h

    def u(self, mm):  return mm * self.SCALE
    def px(self, mm): return self.OX + mm * self.SCALE
    def py(self, mm): return self.OY + mm * self.SCALE

    def add_layer(self, name, color=7, ltype="CONTINUOUS"):
        self._layers[name] = (color, ltype)

    # ── 도형 ──────────────────────────────────────────────
    def line(self, x1, y1, x2, y2, layer="0", lw=-3):
        self._ents.append(("LINE", layer,
                           self.px(x1), self.py(y1),
                           self.px(x2), self.py(y2), lw))

    def rect(self, x, y, w, h, layer="0", lw=-3):
        self.line(x,   y,   x+w, y,   layer, lw)
        self.line(x+w, y,   x+w, y+h, layer, lw)
        self.line(x+w, y+h, x,   y+h, layer, lw)
        self.line(x,   y+h, x,   y,   layer, lw)

    def text(self, x, y, txt, height_mm=2.5, layer="0",
             color=256, halign=0, style="12"):
        h = self.u(height_mm)
        self._ents.append(("TEXT", layer,
                           self.px(x), self.py(y),
                           str(txt), h, halign, color, style))

    def circle(self, cx, cy, r_mm, layer="0", color=256):
        self._ents.append(("CIRCLE", layer,
                           self.px(cx), self.py(cy),
                           self.u(r_mm), color))

    # ── DXF 직렬화 ────────────────────────────────────────
    def save(self, filepath):
        out = []
        A = out.append

        # HEADER
        A("  0\nSECTION\n  2\nHEADER")
        A("  9\n$ACADVER\n  1\nAC1015")
        A("  9\n$INSUNITS\n 70\n4")
        A("  9\n$LTSCALE\n 40\n50.0")
        A("  9\n$TEXTSIZE\n 40\n40.0")
        A("  9\n$TEXTSTYLE\n  7\n12")
        A(f"  9\n$EXTMIN\n 10\n{self.px(0):.4f}\n 20\n{self.py(0):.4f}\n 30\n0.0")
        A(f"  9\n$EXTMAX\n 10\n{self.px(self.pw):.4f}\n 20\n{self.py(self.ph):.4f}\n 30\n0.0")
        A("  0\nENDSEC")

        # TABLES
        A("  0\nSECTION\n  2\nTABLES")

        A("  0\nTABLE\n  2\nLTYPE\n 70\n1")
        A("  0\nLTYPE\n  2\nCONTINUOUS\n 70\n0\n  3\nSolid line\n"
          " 72\n65\n 73\n0\n 40\n0.0")
        A("  0\nENDTABLE")

        A("  0\nTABLE\n  2\nSTYLE\n 70\n2")
        A("  0\nSTYLE\n  2\n12\n 70\n0\n 40\n0.0\n 41\n1.0\n 50\n0.0\n"
          " 71\n0\n  3\ngulim.ttc\n  4\n")
        A("  0\nSTYLE\n  2\nStandard\n 70\n0\n 40\n0.0\n 41\n1.0\n 50\n0.0\n"
          " 71\n0\n  3\ntxt.shx\n  4\n")
        A("  0\nENDTABLE")

        default_layers = {
            "0":        (7,  "CONTINUOUS"),
            "2":        (2,  "CONTINUOUS"),
            "DIM":      (7,  "CONTINUOUS"),
            "DEFPOINTS":(156,"CONTINUOUS"),
            "H":        (9,  "CONTINUOUS"),
            "TEXT":     (3,  "CONTINUOUS"),
            "edit":     (1,  "CONTINUOUS"),
        }
        default_layers.update(self._layers)
        A(f"  0\nTABLE\n  2\nLAYER\n 70\n{len(default_layers)}")
        for lname, (cidx, ltype) in default_layers.items():
            A(f"  0\nLAYER\n  2\n{lname}\n 70\n0\n 62\n{cidx}"
              f"\n  6\n{ltype}\n370\n-3\n390\n7")
        A("  0\nENDTABLE")
        A("  0\nENDSEC")

        # ENTITIES
        A("  0\nSECTION\n  2\nENTITIES")
        for ent in self._ents:
            kind = ent[0]
            if kind == "LINE":
                _, layer, x1,y1,x2,y2,lw = ent
                A(f"  0\nLINE\n  8\n{layer}\n370\n{lw}\n"
                  f" 10\n{x1:.4f}\n 20\n{y1:.4f}\n 30\n0.0\n"
                  f" 11\n{x2:.4f}\n 21\n{y2:.4f}\n 31\n0.0")
            elif kind == "TEXT":
                _, layer, x, y, txt, h, halign, color, style = ent
                flag_c = f" 62\n{color}\n" if color != 256 else ""
                if halign == 0:
                    A(f"  0\nTEXT\n  8\n{layer}\n{flag_c}"
                      f" 10\n{x:.4f}\n 20\n{y:.4f}\n 30\n0.0\n"
                      f" 40\n{h:.4f}\n  1\n{txt}\n  7\n{style}\n 72\n0")
                else:
                    A(f"  0\nTEXT\n  8\n{layer}\n{flag_c}"
                      f" 10\n{x:.4f}\n 20\n{y:.4f}\n 30\n0.0\n"
                      f" 40\n{h:.4f}\n  1\n{txt}\n  7\n{style}\n 72\n{halign}\n"
                      f" 11\n{x:.4f}\n 21\n{y:.4f}\n 31\n0.0")
            elif kind == "CIRCLE":
                _, layer, cx,cy,r,color = ent
                flag_c = f" 62\n{color}\n" if color != 256 else ""
                A(f"  0\nCIRCLE\n  8\n{layer}\n{flag_c}"
                  f" 10\n{cx:.4f}\n 20\n{cy:.4f}\n 30\n0.0\n 40\n{r:.4f}")
        A("  0\nENDSEC\n  0\nEOF")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(out))


# ══════════════════════════════════════════════════════════════
#  A4 보 배근표  —  레이아웃 상수 (mm)
# ══════════════════════════════════════════════════════════════
# 원본 beamA4.dxf 좌표 분석 결과를 mm 환산한 값
#  열 경계 X (mm):
#    부재열:  0  ~ 10.5
#    END(좌): 10.5 ~ 79
#    CENTER:  79  ~ 147.5
#    END(우): 147.5~ 210
#  헤더: y=195(상단) ~ 188(하단)
#  행 높이: 47mm  (최대 4행)

A4_COL_X  = [0.0, 10.5, 79.0, 147.5, 210.0]
A4_HDR_T  = 195.0   # 헤더 상단
A4_HDR_B  = 188.0   # 헤더 하단
A4_ROW_H  = 47.0    # 행 높이
A4_MARG   = 5.0     # 여백
A4_MAX    = 4       # 최대 행 수


def _a4_row_top(ri):  return A4_HDR_B - ri * A4_ROW_H
def _a4_row_bot(ri):  return A4_HDR_B - (ri+1) * A4_ROW_H
def _col_cx(i):       return (A4_COL_X[i] + A4_COL_X[i+1]) / 2


def _parse_n(spec):
    m = re.match(r"(\d+)", (spec or "").strip())
    return max(1, int(m.group(1))) if m else 2


def _split_rebar(spec):
    """'3-UHD22' → ('3','UHD 22')"""
    m = re.match(r"(\d+)[-\s]*([A-Za-z]+)(\d+)", (spec or "").strip())
    if m:
        return m.group(1), f"{m.group(2)} {m.group(3)}"
    return "", spec or ""


def _split_stirrup(spec):
    """'HD10@300' → ('10','300')"""
    s = re.sub(r"[A-Za-z]+","", spec or "")
    m = re.match(r"(\d+)[@\s]+(\d+)", s.strip())
    if m: return m.group(1), m.group(2)
    return s.strip(), ""


def _draw_section(dxf, ox, oy, sw, sh, top_n, bot_n):
    """단면 그리기 (ox,oy: 좌하단 mm, sw/sh: 스케일된 폭/높이 mm)"""
    cvr  = min(sw, sh) * 0.10
    bar_r = max(0.4, min(sw, sh) * 0.045)

    dxf.rect(ox, oy, sw, sh, layer="0", lw=30)
    dxf.rect(ox+cvr, oy+cvr, sw-2*cvr, sh-2*cvr, layer="DIM", lw=-3)

    def bars(n, y_c):
        if n == 1:
            dxf.circle(ox+sw/2, y_c, bar_r, layer="2", color=1)
        else:
            for i in range(n):
                xb = ox+cvr + (sw-2*cvr)*i/(n-1)
                dxf.circle(xb, y_c, bar_r, layer="2", color=1)

    bars(top_n, oy + sh - cvr)
    bars(bot_n, oy + cvr)


def _write_cell_text(dxf, col_idx, ri, b, is_center):
    """END/CENTER 셀 내 M=, 철근 텍스트"""
    x0   = A4_COL_X[col_idx]
    x1   = A4_COL_X[col_idx+1]
    cw   = x1 - x0
    ytop = _a4_row_top(ri)
    ybot = _a4_row_bot(ri)
    h    = 2.0   # 텍스트 높이 mm

    if is_center:
        M    = b.get("cen_M","") or ""
        top  = b.get("cen_top","") or ""
        stir = b.get("cen_stir","") or ""
        bot  = b.get("cen_bot","") or ""
    else:
        M    = b.get("end_M","") or ""
        V    = b.get("end_V","") or ""
        top  = b.get("end_top","") or ""
        stir = b.get("end_stir","") or ""
        bot  = b.get("end_bot","") or ""

    # M= / V= 행 (행 상단 기준 아래로 4mm)
    y_mv = ytop - 4.5
    dxf.text(x0+1.0, y_mv, "M=", height_mm=h, layer="TEXT")
    if M:
        dxf.text(x0+4.5, y_mv, M, height_mm=h, layer="edit", color=1)
    if is_center:
        dxf.text(x0+16, y_mv, "kN.m", height_mm=h, layer="TEXT")
    else:
        dxf.text(x0+16, y_mv, "kN.m, V=", height_mm=h, layer="TEXT")
        if b.get("end_V",""):
            dxf.text(x0+30, y_mv, b["end_V"], height_mm=h, layer="edit", color=1)
        dxf.text(x0+40, y_mv, "kN", height_mm=h, layer="TEXT")

    # 단면 우측 텍스트 시작 X
    # 단면폭 계산 (재계산)
    bw = float(b.get("width",300) or 300)
    bh = float(b.get("depth",600) or 600)
    sw, sh, ox, oy = _sec_dims(x0, ybot, bw, bh)
    tx  = ox + sw + 2.5
    h2  = 1.9

    # 상부근
    y_t = oy + sh * 0.70
    dxf.text(tx,       y_t, "-",   height_mm=h2, layer="TEXT")
    if top:
        cnt, spec = _split_rebar(top)
        dxf.text(tx+2,   y_t, cnt,  height_mm=h2, layer="edit", color=1)
        dxf.text(tx+4.5, y_t, spec, height_mm=h2, layer="edit", color=1)
    dxf.text(tx+14.5, y_t, "(T)", height_mm=h2, layer="TEXT")

    # 스터럽
    y_s = oy + sh * 0.44
    dxf.text(tx, y_s, "Str. HD", height_mm=h2, layer="TEXT")
    if stir:
        sn, sp = _split_stirrup(stir)
        dxf.text(tx+7.5,  y_s, sn, height_mm=h2, layer="edit", color=1)
        dxf.text(tx+11.0, y_s, "@", height_mm=h2, layer="TEXT")
        dxf.text(tx+13.5, y_s, sp, height_mm=h2, layer="edit", color=1)

    # 하부근
    y_b = oy + sh * 0.18
    dxf.text(tx,       y_b, "-",   height_mm=h2, layer="TEXT")
    if bot:
        cnt, spec = _split_rebar(bot)
        dxf.text(tx+2,   y_b, cnt,  height_mm=h2, layer="edit", color=1)
        dxf.text(tx+4.5, y_b, spec, height_mm=h2, layer="edit", color=1)
    dxf.text(tx+14.5, y_b, "(B)", height_mm=h2, layer="TEXT")


def _sec_dims(col_x0, ybot, bw, bh):
    """단면 스케일 계산 → (sw, sh, ox, oy)"""
    MAX_W = 24.0; MAX_H = 36.0
    PAD_X = 3.0;  PAD_Y = 3.5
    sx = min(MAX_W/bw, MAX_H/bh)
    sw = bw*sx; sh = bh*sx
    ox = col_x0 + PAD_X
    oy = ybot   + PAD_Y
    return sw, sh, ox, oy


def make_beam_table_a4(beams, filepath):
    dxf = DXFWriter(paper_w=210, paper_h=297)

    M = A4_MARG
    # 용지 테두리
    dxf.rect(M, M, 210-2*M, 297-2*M, layer="0", lw=50)

    # 헤더 수평선
    dxf.line(M, A4_HDR_T, 210-M, A4_HDR_T, layer="0", lw=30)
    dxf.line(M, A4_HDR_B, 210-M, A4_HDR_B, layer="0", lw=30)

    # 열 수직선 (표 전체 높이)
    table_bot = A4_HDR_B - min(len(beams), A4_MAX)*A4_ROW_H
    for cx in A4_COL_X[1:-1]:
        dxf.line(cx, table_bot, cx, A4_HDR_T, layer="0", lw=20)

    # 헤더 레이블
    dxf.text(M+1, (A4_HDR_T+A4_HDR_B)/2 - 1, "부재", height_mm=2.8, layer="TEXT")
    for i, lbl in enumerate(["END","CENTER","END"]):
        dxf.text(_col_cx(i+1), (A4_HDR_T+A4_HDR_B)/2 - 1,
                 lbl, height_mm=3.2, layer="TEXT", halign=1)

    nrows = min(len(beams), A4_MAX)
    for ri in range(nrows):
        b    = beams[ri]
        ytop = _a4_row_top(ri)
        ybot = _a4_row_bot(ri)

        # 행 구분선
        dxf.line(M, ybot, 210-M, ybot, layer="0", lw=20)

        bw = float(b.get("width", 300) or 300)
        bh = float(b.get("depth", 600) or 600)

        # 부재명 / 보 깊이
        nm = b.get("name","") or f"B{ri+1}"
        dxf.text(M+0.5, ytop - A4_ROW_H*0.35, nm,
                 height_mm=2.8, layer="TEXT")
        dxf.text(M+0.5, ytop - A4_ROW_H*0.6,  str(int(bh)),
                 height_mm=2.2, layer="edit", color=1)

        # 3개 열 단면 + 텍스트
        for col_idx, is_cen in [(1,False),(2,True),(3,False)]:
            top_n = _parse_n(b.get("cen_top" if is_cen else "end_top",""))
            bot_n = _parse_n(b.get("cen_bot" if is_cen else "end_bot",""))
            sw, sh, ox, oy = _sec_dims(A4_COL_X[col_idx], ybot, bw, bh)
            _draw_section(dxf, ox, oy, sw, sh, top_n, bot_n)
            _write_cell_text(dxf, col_idx, ri, b, is_center=is_cen)

        # 보 폭 (행 하단 좌측)
        dxf.text(A4_COL_X[1]+0.5, ybot+1.2, str(int(bw)),
                 height_mm=2.0, layer="edit", color=1)

    # PAGE NO.
    dxf.text(105, M+2, "PAGE NO.", height_mm=2.5, layer="TEXT", halign=1)
    dxf.save(filepath)


# ══════════════════════════════════════════════════════════════
#  A3 보 배근표  (beamA3.dxf 형식 — 가로 나열)
# ══════════════════════════════════════════════════════════════
def make_beam_table_a3(beams, filepath):
    dxf = DXFWriter(paper_w=420, paper_h=297)
    dxf.OX, dxf.OY = 62917.0, 70080.0

    PW, PH = 420.0, 297.0
    M = 5.0
    NB  = 20.0    # 번호 열 폭

    dxf.rect(M, M, PW-2*M, PH-2*M, layer="0", lw=50)

    n     = max(len(beams), 1)
    cw    = (PW - 2*M - NB) / n
    HDR_H = 12.0
    ROW_H = 6.0
    N_ROW = 3

    hdr_t = PH - M
    hdr_b = hdr_t - HDR_H
    row_b = [hdr_b - i*ROW_H for i in range(N_ROW+1)]
    sec_t = row_b[N_ROW]
    sec_h = sec_t - M

    # 수평선
    for y in [hdr_t, hdr_b] + row_b:
        dxf.line(M, y, PW-M, y, layer="0", lw=20)

    # 번호열 수직선
    x_nb = M + NB
    dxf.line(x_nb, M, x_nb, hdr_t, layer="0", lw=20)

    # 헤더 텍스트
    dxf.text(M+1, hdr_b+4, "번  호",    height_mm=3.0, layer="TEXT")
    dxf.text(M+1, hdr_b-1, "전 단 면",  height_mm=2.2, layer="DIM")

    row_labels = ["상 부 근", "하 부 근", "전    단"]
    row_keys   = ["end_top",  "end_bot",  "end_stir"]
    for ri, rlbl in enumerate(row_labels):
        dxf.text(M+1, row_b[ri+1]+1.5, rlbl, height_mm=2.5, layer="TEXT")

    for i, b in enumerate(beams):
        x0 = x_nb + i*cw
        x1 = x0 + cw
        xc = (x0+x1)/2

        dxf.line(x0, M, x0, hdr_t, layer="0", lw=20)

        # 헤더: 보 이름
        nm = b.get("name","") or f"B{i+1}"
        dxf.text(xc, hdr_b+4, nm,        height_mm=3.5, layer="edit", color=1, halign=1)
        dxf.text(xc, hdr_b-1, "전 단 면",height_mm=2.2, layer="DIM", halign=1)

        # 단면
        bw = float(b.get("width",300) or 300)
        bh = float(b.get("depth",600) or 600)
        MAX_W = cw*0.45; MAX_H = sec_h*0.65
        sx = min(MAX_W/bw, MAX_H/bh)
        sw = bw*sx; sh = bh*sx
        ox = xc - sw/2
        oy = M + (sec_h-sh)/2
        top_n = _parse_n(b.get("end_top",""))
        bot_n = _parse_n(b.get("end_bot",""))
        _draw_section(dxf, ox, oy, sw, sh, top_n, bot_n)

        # 치수
        dxf.text(ox-0.5, oy+sh/2, str(int(bh)),
                 height_mm=1.8, layer="edit", color=1, halign=2)
        dxf.text(xc,     oy-2.5,  str(int(bw)),
                 height_mm=1.8, layer="edit", color=1, halign=1)

        # 하단 철근 행
        for ri, rkey in enumerate(row_keys):
            val = b.get(rkey,"") or ""
            if val:
                dxf.text(x0+1, row_b[ri+1]+1.5, val,
                         height_mm=2.3, layer="edit", color=1)

    # 마지막 수직선
    dxf.line(PW-M, M, PW-M, hdr_t, layer="0", lw=20)
    dxf.save(filepath)


# ══════════════════════════════════════════════════════════════
#  철근 자동완성 위젯
# ══════════════════════════════════════════════════════════════
class RebarEntry(tk.Frame):
    """
    숫자+'-' 입력 후 ←→ 방향키로 HD/SHD/UHD 선택,
    이후 숫자 입력으로  '3-UHD22' 완성.
    Alt+Enter: 바로 아래 행에 같은 값 복사.
    """
    PREFIXES = ["HD", "SHD", "UHD"]

    def __init__(self, parent, width=10, on_alt_enter=None, **kw):
        super().__init__(parent, bg=BG3)
        self._cb  = on_alt_enter
        self._pop = None
        self._pidx    = 0
        self._choosing= False

        self._var = tk.StringVar()
        self._ent = tk.Entry(self, textvariable=self._var,
                             font=("Malgun Gothic",9), bg=BG3, fg=TXT,
                             insertbackground=WHI, relief="flat", width=width,
                             highlightbackground=BDR, highlightthickness=1)
        self._ent.pack(fill="both", expand=True, ipady=4)

        self._ent.bind("<FocusIn>",   lambda _: self._ent.config(highlightbackground=ACCH))
        self._ent.bind("<FocusOut>",  self._blur)
        self._ent.bind("<Left>",      self._left)
        self._ent.bind("<Right>",     self._right)
        self._ent.bind("<Return>",    self._enter)
        self._ent.bind("<Alt-Return>",self._alt_enter)
        self._ent.bind("<Escape>",    lambda _: (self._stop_choosing(), "break")[1])
        self._var.trace_add("write",  lambda *a: self._on_write())

    def get(self): return self._var.get()
    def set(self, v): self._var.set(v)

    def _on_write(self):
        v = self._var.get()
        if re.match(r"^\d+-$", v):
            self._start()
        elif self._choosing:
            if re.match(r"^\d+-[A-Za-z]*$", v):
                self._update_pop()
            else:
                self._stop_choosing()
        else:
            self._hide_pop()

    def _start(self):
        self._choosing = True; self._pidx = 0
        self._show_pop(); self._fill()

    def _left(self, e):
        if not self._choosing: return
        self._pidx = (self._pidx-1) % len(self.PREFIXES)
        self._fill(); return "break"

    def _right(self, e):
        if not self._choosing: return
        self._pidx = (self._pidx+1) % len(self.PREFIXES)
        self._fill(); return "break"

    def _fill(self):
        base = re.match(r"^(\d+)-", self._var.get())
        if base:
            nv = base.group(1) + "-" + self.PREFIXES[self._pidx]
            self._var.set(nv)
            self._ent.icursor(len(nv))
        self._update_pop()

    def _enter(self, e):
        if self._choosing: self._stop_choosing()
        return "break"

    def _alt_enter(self, e):
        if self._cb: self._cb(self)
        return "break"

    def _blur(self, e):
        self._ent.config(highlightbackground=BDR)
        if self._choosing: self._stop_choosing()

    def _stop_choosing(self):
        self._choosing = False; self._hide_pop()

    # ── 팝업 ──────────────────────────────────────────────
    def _show_pop(self):
        self._hide_pop()
        pop = tk.Toplevel(self, bg=BG2)
        pop.wm_overrideredirect(True)
        pop.wm_attributes("-topmost", True)
        pop.configure(highlightbackground=BDR2, highlightthickness=1)
        self._pop_lbl = []
        fr = tk.Frame(pop, bg=BG2); fr.pack(padx=2, pady=2)
        for p in self.PREFIXES:
            lb = tk.Label(fr, text=p, font=("Consolas",10,"bold"),
                          bg=BG3, fg=TX2, padx=7, pady=2)
            lb.pack(side="left", padx=1)
            self._pop_lbl.append(lb)
        self.update_idletasks()
        x = self._ent.winfo_rootx()
        y = self._ent.winfo_rooty() + self._ent.winfo_height()
        pop.geometry(f"+{x}+{y}")
        self._pop = pop
        self._update_pop()

    def _update_pop(self):
        if not self._pop: return
        for pi, lb in enumerate(self._pop_lbl):
            lb.config(bg=ACCH if pi==self._pidx else BG3,
                      fg=WHI  if pi==self._pidx else TX2)

    def _hide_pop(self):
        if self._pop:
            try: self._pop.destroy()
            except: pass
            self._pop = None


# ══════════════════════════════════════════════════════════════
#  GUI — AutoTableApp
# ══════════════════════════════════════════════════════════════
class AutoTableApp(tk.Toplevel):
    def __init__(self, parent=None, username=""):
        if parent:
            super().__init__(parent)
        else:
            self._root = tk.Tk(); self._root.withdraw()
            super().__init__(self._root)

        self.title("Auto Table  —  배근표 자동 작성")
        self.geometry("1200x680"); self.minsize(900,560)
        self.configure(bg=BG)
        self.username  = username
        self.beam_rows = []
        self._col_keys  = []
        self._col_widths= []
        self._rebar_keys= set()
        self._build()
        self._center()

    # ── 레이아웃 ───────────────────────────────────────────
    def _build(self):
        self._build_hdr()
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")
        self._build_body()

    def _build_hdr(self):
        hdr = tk.Frame(self, bg=BG2, height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📊  Auto Table",
                 font=("Malgun Gothic",13,"bold"), bg=BG2, fg=WHI).pack(side="left", padx=18)
        tk.Label(hdr, text="보·기둥·슬래브·벽 배근표 자동 작성 및 CAD 출력",
                 font=("Malgun Gothic",9), bg=BG2, fg=TX2).pack(side="left")
        if self.username:
            tk.Label(hdr, text=f"({self.username})",
                     font=("Malgun Gothic",9), bg=BG2, fg=TX3).pack(side="right", padx=18)

    def _build_body(self):
        body = tk.Frame(self, bg=BG); body.pack(fill="both", expand=True)

        # 좌 탭
        left = tk.Frame(body, bg=BG2, width=148)
        left.pack(side="left", fill="y"); left.pack_propagate(False)
        tk.Label(left, text="부재 유형", font=("Malgun Gothic",9,"bold"),
                 bg=BG2, fg=TX2, pady=10).pack(fill="x")
        tk.Frame(left, bg=BDR, height=1).pack(fill="x")
        self._type_btns = []
        for mt in MEMBER_TYPES:
            b = tk.Button(left, text=mt, font=("Malgun Gothic",10),
                          bg=BG2, fg=TXT, relief="flat", cursor="hand2",
                          pady=11, anchor="w", padx=14,
                          command=lambda t=mt: self._switch(t))
            b.pack(fill="x")
            self._type_btns.append((mt, b))

        # 우 콘텐츠
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        # 하단 버튼 바
        ftr = tk.Frame(right, bg=BG2, height=44)
        ftr.pack(side="bottom", fill="x"); ftr.pack_propagate(False)

        def mkb(txt, cmd, bg_=ACC):
            b = tk.Button(ftr, text=txt, command=cmd,
                          font=("Malgun Gothic",9,"bold"),
                          bg=bg_, fg=WHI, relief="flat", cursor="hand2",
                          padx=13, pady=4)
            b.bind("<Enter>", lambda _,b=b,c=bg_: b.config(bg=_lht(c)))
            b.bind("<Leave>", lambda _,b=b,c=bg_: b.config(bg=c))
            b.pack(side="right", padx=5, pady=6)

        mkb("📄 A4 DXF 출력", self._export_a4)
        mkb("📋 A3 DXF 출력", self._export_a3, bg_=GRN)
        mkb("➕ 행 추가",      self._add_row,   bg_="#374151")
        tk.Label(ftr, text="STR Design & Check  |  Auto Table  v1.0",
                 font=("Malgun Gothic",8), bg=BG2, fg=TX3).pack(side="left", padx=14)

        tk.Frame(right, bg=BDR, height=1).pack(side="bottom", fill="x")

        self._content = tk.Frame(right, bg=BG)
        self._content.pack(fill="both", expand=True)
        self._switch("보(Beam)")

    # ── 탭 전환 ───────────────────────────────────────────
    def _switch(self, t):
        for mt, b in self._type_btns:
            b.config(bg=BG3 if mt==t else BG2,
                     fg=WHI if mt==t else TXT)
        for w in self._content.winfo_children(): w.destroy()
        if t == "보(Beam)":
            self._build_beam()
        else:
            fr = tk.Frame(self._content, bg=BG); fr.pack(fill="both", expand=True)
            tk.Label(fr, text=f"🚧  {t}\n준비 중입니다.",
                     font=("Malgun Gothic",13), bg=BG, fg=TX3).pack(expand=True)

    # ── 보 패널 ────────────────────────────────────────────
    def _build_beam(self):
        outer = tk.Frame(self._content, bg=BG)
        outer.pack(fill="both", expand=True, padx=8, pady=6)

        cols = [
            ("부재명",   8,  "name"),
            ("폭\n(mm)", 5,  "width"),
            ("깊이\n(mm)",5, "depth"),
            ("END\nM",   6,  "end_M"),
            ("END\nV",   5,  "end_V"),
            ("END 상부근",10,"end_top"),
            ("END 스터럽",10,"end_stir"),
            ("END 하부근",10,"end_bot"),
            ("CEN\nM",   6,  "cen_M"),
            ("CEN 상부근",10,"cen_top"),
            ("CEN 스터럽",10,"cen_stir"),
            ("CEN 하부근",10,"cen_bot"),
            ("삭제",      4,  None),
        ]
        self._col_keys   = [c[2] for c in cols[:-1]]
        self._col_widths = [c[1] for c in cols]
        self._rebar_keys = {"end_top","end_stir","end_bot",
                            "cen_top","cen_stir","cen_bot"}

        # 헤더
        hf = tk.Frame(outer, bg=BG3); hf.pack(fill="x")
        for lbl, w, _ in cols:
            tk.Label(hf, text=lbl, font=("Malgun Gothic",8,"bold"),
                     bg=BG3, fg=TX2, width=w, pady=3).pack(side="left")

        # 스크롤 캔버스
        cf = tk.Frame(outer, bg=BG); cf.pack(fill="both", expand=True, pady=(1,0))
        cvs = tk.Canvas(cf, bg=BG, bd=0, highlightthickness=0)
        vsb = ttk.Scrollbar(cf, orient="vertical", command=cvs.yview)
        cvs.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        cvs.pack(side="left", fill="both", expand=True)
        self._row_frame = tk.Frame(cvs, bg=BG)
        win_id = cvs.create_window((0,0), window=self._row_frame, anchor="nw")
        self._row_frame.bind("<Configure>",
            lambda e: cvs.configure(scrollregion=cvs.bbox("all")))
        cvs.bind("<Configure>",
            lambda e: cvs.itemconfig(win_id, width=e.width))
        self._cvs = cvs

        self.beam_rows.clear()
        for _ in range(3):
            self._add_row()

    def _add_row(self, copy_from=None):
        if not hasattr(self, "_row_frame"): return
        fr = tk.Frame(self._row_frame, bg=BG4); fr.pack(fill="x", pady=1)
        rv = {}
        defs = {
            "name":"B1","width":"300","depth":"600",
            "end_M":"","end_V":"",
            "end_top":"3-UHD22","end_stir":"HD10@300","end_bot":"3-UHD22",
            "cen_M":"",
            "cen_top":"3-UHD22","cen_stir":"HD10@300","cen_bot":"3-UHD22"
        }

        for key, w in zip(self._col_keys, self._col_widths[:-1]):
            init = copy_from[key].get() if (copy_from and key in copy_from
                                            and hasattr(copy_from[key],'get')) else defs.get(key,"")
            if key in self._rebar_keys:
                we = RebarEntry(fr, width=w,
                                on_alt_enter=lambda _w, _rv=rv: self._copy_below(_rv))
                we.set(init)
                we.pack(side="left", padx=1)
                rv[key] = we
            else:
                v = tk.StringVar(value=init)
                e = tk.Entry(fr, textvariable=v,
                             font=("Malgun Gothic",9), bg=BG3, fg=TXT,
                             insertbackground=WHI, relief="flat", width=w,
                             highlightbackground=BDR, highlightthickness=1)
                e.pack(side="left", padx=1, ipady=4)
                e.bind("<FocusIn>",   lambda _,e=e: e.config(highlightbackground=ACCH))
                e.bind("<FocusOut>",  lambda _,e=e: e.config(highlightbackground=BDR))
                e.bind("<Alt-Return>",lambda _,_rv=rv: self._copy_below(_rv))
                rv[key] = v

        def _del(f=fr, _rv=rv):
            if len(self.beam_rows) <= 1:
                messagebox.showwarning("경고","최소 1개 행이 필요합니다.", parent=self)
                return
            if _rv in self.beam_rows: self.beam_rows.remove(_rv)
            f.destroy()

        tk.Button(fr, text="✕", command=_del,
                  font=("Malgun Gothic",9), bg=RED, fg=WHI,
                  relief="flat", cursor="hand2", width=3, pady=3).pack(side="left", padx=2)

        rv["__frame__"] = fr
        self.beam_rows.append(rv)

    def _copy_below(self, source_rv):
        """source_rv 바로 아래에 동일 값 행 삽입"""
        if source_rv not in self.beam_rows: return
        idx = self.beam_rows.index(source_rv)

        # 새 행 생성 (리스트 맨 뒤)
        self._add_row(copy_from=source_rv)
        new_rv = self.beam_rows[-1]

        # 리스트 재정렬
        self.beam_rows.pop()                    # 맨 뒤 제거
        self.beam_rows.insert(idx+1, new_rv)    # idx+1 위치 삽입

        # pack 순서 재정렬
        frames = [rv["__frame__"] for rv in self.beam_rows if "__frame__" in rv]
        for f in frames:
            f.pack_forget()
        for f in frames:
            f.pack(fill="x", pady=1)

    # ── 데이터 수집 ────────────────────────────────────────
    def _collect(self):
        res = []
        for rv in self.beam_rows:
            d = {}
            for k, v in rv.items():
                if k == "__frame__": continue
                d[k] = v.get() if hasattr(v, "get") else ""
            res.append(d)
        return res

    # ── DXF 출력 ──────────────────────────────────────────
    def _export_a4(self):
        beams = self._collect()
        if not beams:
            messagebox.showwarning("경고","데이터가 없습니다.", parent=self); return
        path = filedialog.asksaveasfilename(
            defaultextension=".dxf",
            filetypes=[("DXF 파일","*.dxf"),("모든 파일","*.*")],
            title="A4 DXF 저장", initialfile="beam_table_A4.dxf", parent=self)
        if not path: return
        try:
            make_beam_table_a4(beams, path)
            messagebox.showinfo("완료", f"A4 DXF 저장 완료\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("오류", str(e), parent=self)

    def _export_a3(self):
        beams = self._collect()
        if not beams:
            messagebox.showwarning("경고","데이터가 없습니다.", parent=self); return
        path = filedialog.asksaveasfilename(
            defaultextension=".dxf",
            filetypes=[("DXF 파일","*.dxf"),("모든 파일","*.*")],
            title="A3 DXF 저장", initialfile="beam_table_A3.dxf", parent=self)
        if not path: return
        try:
            make_beam_table_a3(beams, path)
            messagebox.showinfo("완료", f"A3 DXF 저장 완료\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("오류", str(e), parent=self)

    # ── 유틸 ───────────────────────────────────────────────
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
