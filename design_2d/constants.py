"""
design_2d/constants.py
공통 팔레트 · 상수
"""

# ── 팔레트 (launcher.py 통일) ──────────────────────────────
BG   = "#0f1520"; BG2  = "#141d2e"; BG3  = "#1a2540"
BG4  = "#1f2d4a"; BG5  = "#263556"
BDR  = "#2c3f62"; BDR2 = "#3a5280"
ACC  = "#1a56db"; ACCH = "#2563eb"; ACCD = "#1e40af"
GRN  = "#15803d"; GRNH = "#16a34a"
RED  = "#dc2626"; ORG  = "#d97706"; YEL  = "#f59e0b"
BLU  = "#3b82f6"; CYN  = "#06b6d4"; PRP  = "#8b5cf6"
TXT  = "#dde4f0"; TX2  = "#8fa3c0"; TX3  = "#546887"
WHI  = "#f0f5ff"; DIS  = "#3d5070"
CANV_BG = "#0a0e18"

# ── 도면 컬러 ───────────────────────────────────────────────
GRID_COLOR  = "#1a2035"
NODE_COLOR  = "#22c55e"
SEL_COLOR   = "#fbbf24"
LINE_COLOR  = "#ef4444"
PIN_COLOR   = "#38bdf8"
FIX_COLOR   = "#a78bfa"
SEMI_COLOR  = "#fb923c"
LOAD_COLOR  = "#facc15"
MOM_COLOR   = "#f472b6"
SHEAR_COLOR = "#34d399"
DEFL_COLOR  = "#60a5fa"

# ── 부재 재료 색상 ─────────────────────────────────────────
RC_COLOR    = "#ef4444"   # 철근콘크리트 — 빨간색
STEEL_COLOR = "#60a5fa"   # 철골          — 파란색

# ── 기타 상수 ───────────────────────────────────────────────
SNAP_DIST = 15    # px — 노드 스냅 반경

# ── 기본 단면 상수 ─────────────────────────────────────────
# RC : fck=24 MPa, 400×600 mm 직사각형 보
RC_FCK_DEFAULT  = 24.0          # MPa
RC_B_DEFAULT    = 400.0         # mm
RC_H_DEFAULT    = 600.0         # mm
RC_E_DEFAULT    = 8500 * (24 + 4) ** (1/3)   # ≈ 27,806 MPa
RC_I_DEFAULT    = 400.0 * 600.0**3 / 12.0    # mm⁴
RC_A_DEFAULT    = 400.0 * 600.0              # mm²

# 철골 기본 (H250×125, A36 — 변경 전 기존값)
STEEL_E_DEFAULT = 205000.0
STEEL_I_DEFAULT = 4050e4
STEEL_A_DEFAULT = 6340.0
