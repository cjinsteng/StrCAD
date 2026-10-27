"""SQLite storage of analyses (~/.strcad/cad_analysis.db).

analyses : one row per saved analysis, full result as zlib-compressed JSON
members  : flat copy of members for querying from other StrCAD modules
"""
from __future__ import annotations

import json
import os
import sqlite3
import zlib
from datetime import datetime

from .model import AnalysisResult, Member, Node, Segment, CoordSystem

DB_PATH = os.path.join(os.path.expanduser("~"), ".strcad", "cad_analysis.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    dxf_path TEXT,
    region TEXT,
    created TEXT,
    updated TEXT,
    n_column INTEGER, n_girder INTEGER, n_beam INTEGER, n_wall INTEGER,
    data BLOB
);
CREATE TABLE IF NOT EXISTS members (
    analysis_id INTEGER NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    member_id INTEGER, kind TEXT, name TEXT, size TEXT,
    width REAL, depth REAL, b REAL, h REAL,
    length_cc REAL, length_clear REAL,
    x1 REAL, y1 REAL, x2 REAL, y2 REAL,
    node_i INTEGER, node_j INTEGER, layer TEXT, name_source TEXT,
    PRIMARY KEY (analysis_id, member_id)
);
CREATE INDEX IF NOT EXISTS ix_members_name ON members(analysis_id, kind, name);
CREATE TABLE IF NOT EXISTS surveys (
    analysis_id INTEGER NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    survey_id INTEGER, label TEXT, type TEXT, member_id INTEGER,
    t0 REAL, t1 REAL, x REAL, y REAL, face TEXT, date TEXT, data TEXT, photos TEXT, memo TEXT,
    PRIMARY KEY (analysis_id, survey_id)
);
"""

_M_EXTRA = ("kind_ko", "size", "name_source_ko")


def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(analyses)")}
    for c, t in (("project", "TEXT DEFAULT ''"), ("seq", "INTEGER DEFAULT 0")):
        if c not in cols:
            con.execute(f"ALTER TABLE analyses ADD COLUMN {c} {t}")
    return con


# ---------------------------------------------------------------- (de)serialise
def _r(v):
    return round(v, 2)


def result_to_dict(res: AnalysisResult, cs: CoordSystem | None):
    return {
        "version": 2,
        "source_file": res.source_file,
        "region": res.region,
        "extents": res.extents,
        "layer_roles": res.layer_roles,
        "cs": cs.to_dict() if cs else None,
        "nodes": [[n.id, _r(n.x), _r(n.y)] for n in res.nodes.values()],
        "members": [{k: v for k, v in m.to_dict().items() if k not in _M_EXTRA} for m in res.members],
        "background": [[_r(s.x1), _r(s.y1), _r(s.x2), _r(s.y2)] for s in res.background],
        "grid": [[_r(s.x1), _r(s.y1), _r(s.x2), _r(s.y2)] for s in res.grid],
        "surveys": res.surveys,
        "kind": getattr(res, "kind", "struct"),
    }


def _tup(v):
    return tuple(v) if isinstance(v, list) else v


def result_from_dict(d):
    res = AnalysisResult(source_file=d.get("source_file", ""), layer_roles=d.get("layer_roles", {}),
                         extents=tuple(d.get("extents", (0, 0, 1, 1))),
                         region=_tup(d.get("region")), kind=d.get("kind", "struct"))
    res.nodes = {int(i): Node(int(i), x, y) for i, x, y in d.get("nodes", [])}
    fields = set(Member.__dataclass_fields__)
    for md in d.get("members", []):
        md = {k: v for k, v in md.items() if k in fields}
        for k in ("p1", "p2", "c1", "c2", "center"):
            md[k] = _tup(md.get(k))
        md["polygon"] = [tuple(p) for p in md.get("polygon", [])]
        res.members.append(Member(**md))
    res.background = [Segment(*s, "bg") for s in d.get("background", [])]
    res.grid = [Segment(*s, "grid") for s in d.get("grid", [])]
    res.surveys = list(d.get("surveys", []))
    c = d.get("cs")
    cs = CoordSystem(c["x0"], c["y0"], c["rot_deg"]) if c else CoordSystem()
    return res, cs


# ---------------------------------------------------------------- CRUD
def save(res: AnalysisResult, cs, name: str, analysis_id: int | None = None, path=None,
         project: str = "", seq: int | None = None) -> int:
    """name = 도면/층 이름 (예: 지하1층), project = 건물·과업명 (같은 프로젝트끼리 ‹ n/N › 이동)"""
    blob = zlib.compress(json.dumps(result_to_dict(res, cs), ensure_ascii=False).encode("utf-8"), 6)
    now = datetime.now().isoformat(timespec="seconds")
    cnt = {k: sum(1 for m in res.members if m.kind == k) for k in ("column", "girder", "beam", "wall")}
    con = connect(path)
    with con:
        if seq is None:
            if analysis_id is not None:
                r = con.execute("SELECT seq FROM analyses WHERE id=?", (analysis_id,)).fetchone()
                seq = r[0] if r else 0
            else:
                r = con.execute("SELECT MAX(seq) FROM analyses WHERE project=?", (project,)).fetchone()
                seq = (r[0] or 0) + 1
        if analysis_id is None:
            cur = con.execute(
                "INSERT INTO analyses (name, dxf_path, region, created, updated, n_column, n_girder, n_beam, n_wall, data)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (name, res.source_file, json.dumps(res.region), now, now,
                 cnt["column"], cnt["girder"], cnt["beam"], cnt["wall"], blob))
            analysis_id = cur.lastrowid
            con.execute("UPDATE analyses SET project=?, seq=? WHERE id=?", (project, seq, analysis_id))
        else:
            con.execute(
                "UPDATE analyses SET name=?, dxf_path=?, region=?, updated=?, n_column=?, n_girder=?, n_beam=?,"
                " n_wall=?, data=? WHERE id=?",
                (name, res.source_file, json.dumps(res.region), now, cnt["column"], cnt["girder"],
                 cnt["beam"], cnt["wall"], blob, analysis_id))
            con.execute("UPDATE analyses SET project=?, seq=? WHERE id=?", (project, seq, analysis_id))
            con.execute("DELETE FROM members WHERE analysis_id=?", (analysis_id,))
        rows = []
        for m in res.members:
            if m.kind == "column":
                x1, y1 = m.center
                x2 = y2 = None
            else:
                (x1, y1), (x2, y2) = m.p1, m.p2
            rows.append((analysis_id, m.id, m.kind, m.name, m.size_text(), m.width, m.depth, m.b, m.h,
                         m.length_cc, m.length_clear, x1, y1, x2, y2,
                         m.node if m.kind == "column" else m.n1, m.n2, m.layer, m.name_source))
        con.executemany("INSERT INTO members VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("DELETE FROM surveys WHERE analysis_id=?", (analysis_id,))
        con.executemany("INSERT INTO surveys VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (analysis_id, sv["id"], str(sv.get("no", sv.get("label", ""))), sv.get("purpose", sv.get("type")),
             sv.get("member"), sv.get("t0"), sv.get("t1"), sv.get("x"), sv.get("y"), sv.get("name", ""),
             sv.get("date", ""), json.dumps(sv, ensure_ascii=False),
             json.dumps(sv.get("photos", []), ensure_ascii=False), sv.get("memo", "")) for sv in res.surveys])
    con.close()
    return analysis_id


def list_analyses(path=None):
    con = connect(path)
    rows = con.execute("SELECT id, name, dxf_path, updated, n_column, n_girder, n_beam, n_wall, project, seq "
                       "FROM analyses ORDER BY project, seq, id").fetchall()
    con.close()
    return rows


def load(analysis_id: int, path=None):
    con = connect(path)
    row = con.execute("SELECT name, data FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    con.close()
    if not row:
        raise KeyError(analysis_id)
    d = json.loads(zlib.decompress(row[1]).decode("utf-8"))
    res, cs = result_from_dict(d)
    return row[0], res, cs


def delete(analysis_id: int, path=None):
    con = connect(path)
    with con:
        con.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
    con.close()


def rename(analysis_id: int, name: str, path=None):
    con = connect(path)
    with con:
        con.execute("UPDATE analyses SET name=? WHERE id=?", (name, analysis_id))
    con.close()


def meta(analysis_id: int, path=None):
    """→ (name, project, seq)"""
    con = connect(path)
    r = con.execute("SELECT name, project, seq FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    con.close()
    return r


def project_sheets(project: str, path=None):
    """Drawings (floors) of one project in order → [(id, name)]"""
    con = connect(path)
    rows = con.execute("SELECT id, name FROM analyses WHERE project=? ORDER BY seq, id", (project,)).fetchall()
    con.close()
    return rows


def projects(path=None):
    con = connect(path)
    rows = [r[0] for r in con.execute("SELECT DISTINCT project FROM analyses ORDER BY project")]
    con.close()
    return rows


def reorder(ids, path=None):
    con = connect(path)
    with con:
        for k, aid in enumerate(ids, 1):
            con.execute("UPDATE analyses SET seq=? WHERE id=?", (k, aid))
    con.close()
