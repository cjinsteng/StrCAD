"""Data model for CAD Analysis (StrCAD).

All coordinates are DXF model-space units (assumed mm), Y-up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional

KINDS = ("column", "girder", "beam", "wall")
KIND_KO = {"column": "기둥", "girder": "거더", "beam": "보", "wall": "벽체"}

# Layer roles (what a layer holds)
LAYER_ROLES = (
    "column", "girder", "beam", "wall",                  # geometry
    "column_name", "girder_name", "beam_name", "wall_name",  # name text
    "member_text",                                        # mixed labels, decide by text
    "auto",                                               # geometry, member type decided by shape
    "grid",                                               # grid / center lines (display only)
    "ignore",
)
LAYER_ROLE_KO = {
    "column": "기둥 형상", "girder": "거더 형상", "beam": "보 형상", "wall": "벽체 형상",
    "column_name": "기둥 이름", "girder_name": "거더 이름", "beam_name": "보 이름",
    "wall_name": "벽체 이름", "member_text": "부재명 혼합", "auto": "형상 자동판별",
    "grid": "그리드", "ignore": "무시",
}

# Name sources
SRC_LABEL = "label"        # matched to a text in the drawing
SRC_INFERRED = "inferred"  # copied from a collinear neighbour / same-size columns
SRC_DEFAULT = "default"    # no label found
SRC_USER = "user"          # edited by user
SRC_KO = {SRC_LABEL: "도면 표기", SRC_INFERRED: "추정(인접부재)", SRC_DEFAULT: "미표기", SRC_USER: "사용자 수정"}


@dataclass
class Node:
    """Shared joint. Columns sit on one node; linear members span n1→n2."""
    id: int
    x: float
    y: float

    @property
    def xy(self):
        return (self.x, self.y)


@dataclass
class Segment:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


@dataclass
class Arc:
    cx: float
    cy: float
    r: float
    a0: float  # start angle, radians, CCW
    a1: float  # end angle, radians (a1 > a0, may exceed 2pi)
    layer: str


@dataclass
class TextItem:
    text: str
    x: float          # approximate visual centre
    y: float
    rot: float        # degrees
    height: float
    layer: str


@dataclass
class Member:
    id: int
    kind: str                       # column / girder / beam / wall
    name: str = ""
    name_source: str = SRC_DEFAULT
    labels: list = field(default_factory=list)   # raw label strings matched
    layer: str = ""
    # --- linear members (girder/beam/wall) ---
    p1: Optional[tuple] = None      # centre-to-centre start (x, y)
    p2: Optional[tuple] = None      # centre-to-centre end
    c1: Optional[tuple] = None      # clear-span start (support face)
    c2: Optional[tuple] = None      # clear-span end
    length_cc: float = 0.0          # L  (support centre to centre)
    length_clear: float = 0.0       # ln (face to face)
    width: float = 0.0              # beam width B / wall thickness t
    depth: Optional[float] = None   # beam depth D (only if given in a label)
    angle: float = 0.0              # degrees, 0..180, DXF (Y-up) convention
    curved: bool = False
    arc: Optional[dict] = None      # {cx, cy, r, a0, a1} for curved members
    # --- columns ---
    center: Optional[tuple] = None
    b: float = 0.0                  # longer side
    h: float = 0.0                  # shorter side
    diameter: float = 0.0           # round column
    shape: str = ""                 # rect / round / polygon
    polygon: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    # --- topology ---
    node: Optional[int] = None      # column node
    n1: Optional[int] = None        # linear start node
    n2: Optional[int] = None        # linear end node
    inner: list = field(default_factory=list)   # [[node_id, t]] joints along this member (T-junctions)
    off1: float = 0.0               # node → support face distance at start (L - ln split)
    off2: float = 0.0
    auto: bool = False              # member type decided from shape (not layer)
    user: bool = False              # added / moved by user
    survey: dict = field(default_factory=dict)   # 현장조사 기록

    # ------------------------------------------------------------------
    def size_text(self) -> str:
        if self.kind == "column":
            if self.shape == "round":
                return f"Ø{self.diameter:.0f}"
            s = f"{self.b:.0f}×{self.h:.0f}"
            return s + (" (비정형)" if self.shape == "polygon" else "")
        if self.kind == "wall":
            return f"t={self.width:.0f}"
        if self.depth:
            return f"{self.width:.0f}×{self.depth:.0f}"
        return f"B={self.width:.0f}"

    def display_name(self) -> str:
        return self.name or "(미표기)"

    def polyline(self, n_arc: int = 24) -> list:
        """Points describing the centreline (for drawing / hit test)."""
        if self.kind == "column":
            return [self.center]
        if self.curved and self.arc:
            a = self.arc
            pts = []
            for i in range(n_arc + 1):
                t = a["a0"] + (a["a1"] - a["a0"]) * i / n_arc
                pts.append((a["cx"] + a["r"] * math.cos(t), a["cy"] + a["r"] * math.sin(t)))
            return pts
        return [self.p1, self.p2]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind_ko"] = KIND_KO.get(self.kind, self.kind)
        d["size"] = self.size_text()
        d["name_source_ko"] = SRC_KO.get(self.name_source, self.name_source)
        return d


@dataclass
class AnalysisResult:
    members: list = field(default_factory=list)          # [Member]
    grid: list = field(default_factory=list)             # [Segment]
    background: list = field(default_factory=list)       # [Segment] raw lines of structural layers
    texts: list = field(default_factory=list)            # [TextItem] (used labels)
    layer_roles: dict = field(default_factory=dict)
    log: list = field(default_factory=list)
    extents: tuple = (0.0, 0.0, 1.0, 1.0)                # xmin, ymin, xmax, ymax
    source_file: str = ""
    nodes: dict = field(default_factory=dict)            # id -> Node
    region: Optional[tuple] = None                       # analysed window (x0, y0, x1, y1)
    surveys: list = field(default_factory=list)          # 현장조사 검측위치/구간 (dict, see survey.py)
    kind: str = "struct"                                  # "struct" 구조도면 / "arch" 건축도면

    def by_id(self) -> dict:
        return {m.id: m for m in self.members}

    def next_member_id(self) -> int:
        return max((m.id for m in self.members), default=0) + 1

    def next_node_id(self) -> int:
        return max(self.nodes, default=0) + 1


@dataclass
class CoordSystem:
    """Local X/Y axes: origin + rotation (deg, CCW from DXF +X)."""
    x0: float = 0.0
    y0: float = 0.0
    rot: float = 0.0

    def is_identity(self) -> bool:
        return self.x0 == 0 and self.y0 == 0 and self.rot == 0

    def to_local(self, x, y):
        dx, dy = x - self.x0, y - self.y0
        r = math.radians(self.rot)
        c, s = math.cos(r), math.sin(r)
        return dx * c + dy * s, -dx * s + dy * c

    def to_dict(self):
        return {"x0": self.x0, "y0": self.y0, "rot_deg": self.rot}
