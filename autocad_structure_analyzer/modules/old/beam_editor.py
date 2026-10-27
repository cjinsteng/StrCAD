"""
STRCAD 부재 뷰어 v4
- 기둥 (폴리곤/다각형) 캔버스 표시 추가
- 벽 (라인/폴리곤) 캔버스 표시 추가
- 겹침 구간: 형태 추론(shape_inferred) 기둥/벽 구분 렌더링
- 기존 기능 전부 유지
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3, math, re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ── 팔레트 ──────────────────────────────────────────────────
BG=     "#0d1117"; BG2="#161b22"; BG3="#21262d"
ACCENT= "#238636"; BLUE="#1f6feb"; RED="#da3633"
TEXT=   "#c9d1d9"; TEXT2="#8b949e"; BORDER="#30363d"
WHITE=  "#f0f6fc"; TEAL="#39d353"; YELLOW="#e3b341"

MEMBER_COLOR = {'GIRDER':'#FF6B35', 'BEAM':'#4FC3F7'}
MEMBER_LABEL = {'GIRDER':'거더 (GIRDER)', 'BEAM':'보 (BEAM)'}

# 기둥/벽 색상
COL_FILL    = '#1a3a2a'    # 기둥 채우기 (어두운 초록)
COL_OUTLINE = '#4CAF50'    # 기둥 윤곽
COL_INFER   = '#2d4a1e'    # 형태추론 기둥 채우기 (약간 다른 색)
WALL_COLOR  = '#7B8FA1'    # 벽체 라인 색상
WALL_POLY   = '#4a5568'    # 벽 폴리곤 채우기

# ttk 스타일 한 번만 적용
_STYLE_INIT = False
def _init_style():
    global _STYLE_INIT
    if _STYLE_INIT: return
    s = ttk.Style(); s.theme_use('clam')
    s.configure('TNotebook',            background=BG2, borderwidth=0)
    s.configure('TNotebook.Tab',        background=BG3, foreground=TEXT,
                font=('Malgun Gothic',9), padding=[10,5])
    s.map('TNotebook.Tab',
          background=[('selected',BLUE)], foreground=[('selected',WHITE)])
    s.configure('S.Treeview',           background=BG3, foreground=WHITE,
                fieldbackground=BG3, rowheight=26, font=('Malgun Gothic',9))
    s.configure('S.Treeview.Heading',   background=BG2, foreground=WHITE,
                font=('Malgun Gothic',9,'bold'))
    s.map('S.Treeview',
          background=[('selected',BLUE)],
          foreground=[('selected',WHITE)])
    s.configure('PM.Treeview',          background=BG3, foreground=WHITE,
                fieldbackground=BG3, rowheight=28, font=('Malgun Gothic',9))
    s.configure('PM.Treeview.Heading',  background=BG2, foreground=WHITE,
                font=('Malgun Gothic',9,'bold'))
    s.map('PM.Treeview', background=[('selected',BLUE)])
    _STYLE_INIT = True


# ════════════════════════════════════════════════════════════
#  DB
# ════════════════════════════════════════════════════════════
class BeamDB:
    def __init__(self, path="strcad_data.db"):
        self.db_path = path; self._init_db()

    def _conn(self): return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS projects(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, dxf_path TEXT, created TEXT, updated TEXT,
                description TEXT DEFAULT '',
                building_name TEXT DEFAULT '',
                location TEXT DEFAULT '',
                engineer TEXT DEFAULT '',
                memo TEXT DEFAULT '')""")
            c.execute("""CREATE TABLE IF NOT EXISTS beams(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER, beam_id TEXT, beam_layer TEXT,
                beam_name TEXT, beam_raw_name TEXT, member_type TEXT,
                span_length REAL, beam_width REAL, direction TEXT,
                x1 REAL, y1 REAL, x2 REAL, y2 REAL,
                col_start TEXT, col_end TEXT,
                memo TEXT DEFAULT '', modified INTEGER DEFAULT 0, updated TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS columns(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER, x REAL, y REAL)""")
            # ── 신규: 기둥 폴리곤 테이블 ──────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS column_shapes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                coords TEXT,
                layer TEXT,
                source TEXT DEFAULT 'explicit',
                FOREIGN KEY(project_id) REFERENCES projects(id))""")
            # ── 신규: 기둥 Node 테이블 ───────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS column_nodes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                node_id TEXT,
                cx REAL, cy REAL,
                width REAL, height REAL,
                layer TEXT,
                source TEXT DEFAULT 'explicit',
                col_name TEXT DEFAULT '',
                angle REAL DEFAULT 0,
                coords TEXT DEFAULT '',
                FOREIGN KEY(project_id) REFERENCES projects(id))""")
            # 구버전 DB 호환
            try:
                c.execute("ALTER TABLE column_nodes ADD COLUMN col_name TEXT DEFAULT ''")
            except Exception: pass
            try:
                c.execute("ALTER TABLE column_nodes ADD COLUMN angle REAL DEFAULT 0")
            except Exception: pass
            try:
                c.execute("ALTER TABLE column_nodes ADD COLUMN coords TEXT DEFAULT ''")
            except Exception: pass
            # ── 신규: 벽체 형상 테이블 ────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS wall_shapes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                shape_type TEXT,
                coords TEXT,
                layer TEXT,
                source TEXT DEFAULT 'explicit',
                thickness REAL DEFAULT 0,
                FOREIGN KEY(project_id) REFERENCES projects(id))""")
            # thickness 컬럼 없는 구버전 DB 호환
            try:
                c.execute("ALTER TABLE wall_shapes ADD COLUMN thickness REAL DEFAULT 0")
            except Exception: pass
            # floors 테이블
            c.execute("""CREATE TABLE IF NOT EXISTS floors(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                floor_name TEXT,
                dxf_path TEXT,
                created TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id))""")
            # 마이그레이션
            proj_exist = {r[1] for r in c.execute("PRAGMA table_info(projects)")}
            for col, dfn in [("description","TEXT DEFAULT ''"),
                             ("building_name","TEXT DEFAULT ''"),
                             ("location","TEXT DEFAULT ''"),
                             ("engineer","TEXT DEFAULT ''"),
                             ("memo","TEXT DEFAULT ''")]:
                if col not in proj_exist:
                    c.execute(f"ALTER TABLE projects ADD COLUMN {col} {dfn}")
            exist = {r[1] for r in c.execute("PRAGMA table_info(beams)")}
            for col, dfn in [("beam_raw_name","TEXT"),
                             ("member_type",  "TEXT DEFAULT 'BEAM'"),
                             ("memo",         "TEXT DEFAULT ''"),
                             ("modified",     "INTEGER DEFAULT 0")]:
                if col not in exist:
                    c.execute(f"ALTER TABLE beams ADD COLUMN {col} {dfn}")
            c.execute("UPDATE beams SET beam_raw_name=beam_name "
                      "WHERE beam_raw_name IS NULL OR beam_raw_name=''")
            c.execute("UPDATE beams SET member_type='BEAM' "
                      "WHERE member_type IS NULL OR member_type=''")

    def create_project(self, name, dxf_path="", info=None):
        now=datetime.now().isoformat(); info=info or {}
        with self._conn() as c:
            return c.execute(
                """INSERT INTO projects(name,dxf_path,created,updated,
                   description,building_name,location,engineer,memo)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (name,dxf_path,now,now,
                 info.get('description',''),info.get('building_name',''),
                 info.get('location',''),info.get('engineer',''),
                 info.get('memo',''))).lastrowid

    def update_project_info(self, pid, info):
        now=datetime.now().isoformat()
        with self._conn() as c:
            c.execute("""UPDATE projects SET name=?,description=?,building_name=?,
                         location=?,engineer=?,memo=?,updated=? WHERE id=?""",
                      (info.get('name',''),info.get('description',''),
                       info.get('building_name',''),info.get('location',''),
                       info.get('engineer',''),info.get('memo',''),now,pid))

    def get_project_info(self, pid):
        with self._conn() as c:
            r=c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
        if not r: return {}
        cols=['id','name','dxf_path','created','updated',
              'description','building_name','location','engineer','memo']
        return dict(zip(cols, r + (None,)*(len(cols)-len(r))))

    def list_floors(self, pid):
        with self._conn() as c:
            return c.execute(
                "SELECT id,floor_name,dxf_path,created FROM floors "
                "WHERE project_id=? ORDER BY floor_name",(pid,)).fetchall()

    def add_floor(self, pid, floor_name, dxf_path):
        now=datetime.now().isoformat()
        with self._conn() as c:
            return c.execute(
                "INSERT INTO floors(project_id,floor_name,dxf_path,created) VALUES(?,?,?,?)",
                (pid,floor_name,dxf_path,now)).lastrowid

    def delete_floor(self, fid):
        with self._conn() as c:
            c.execute("DELETE FROM floors WHERE id=?",(fid,))

    def list_projects(self):
        with self._conn() as c:
            return c.execute(
                "SELECT id,name,dxf_path,created FROM projects ORDER BY id DESC").fetchall()

    def delete_project(self, pid):
        with self._conn() as c:
            for t,k in [('beams','project_id'),('columns','project_id'),
                        ('column_shapes','project_id'),('wall_shapes','project_id'),
                        ('column_nodes','project_id'),
                        ('projects','id')]:
                c.execute(f"DELETE FROM {t} WHERE {k}=?",(pid,))

    def save_beams(self, pid, beam_data, col_positions,
                   column_shapes=None, wall_shapes=None, column_nodes=None):
        """
        보 + 기둥점 + 기둥 폴리곤 + 벽체 형상 + 기둥 Node 저장
        column_nodes: dxf_reader.get_column_nodes() 반환값
        """
        import json
        now=datetime.now().isoformat()
        with self._conn() as c:
            c.execute("DELETE FROM beams          WHERE project_id=?",(pid,))
            c.execute("DELETE FROM columns        WHERE project_id=?",(pid,))
            c.execute("DELETE FROM column_shapes  WHERE project_id=?",(pid,))
            c.execute("DELETE FROM wall_shapes    WHERE project_id=?",(pid,))
            c.execute("DELETE FROM column_nodes   WHERE project_id=?",(pid,))

            for b in beam_data:
                c.execute("""INSERT INTO beams(project_id,beam_id,beam_layer,beam_name,
                    beam_raw_name,member_type,span_length,beam_width,direction,
                    x1,y1,x2,y2,col_start,col_end,memo,updated)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    pid,b.get('beam_id',''),b.get('beam_layer',''),
                    b.get('beam_name',b.get('beam_id','')),
                    b.get('beam_raw_name',b.get('beam_name','')),
                    b.get('member_type','BEAM'),
                    b.get('span_length',0),b.get('beam_width',0),
                    b.get('beam_direction',''),
                    b['start_point'][0],b['start_point'][1],
                    b['end_point'][0],  b['end_point'][1],
                    b.get('start_column','') or '',
                    b.get('end_column','')   or '',
                    b.get('memo',''),now))

            for cp in col_positions:
                c.execute("INSERT INTO columns(project_id,x,y) VALUES(?,?,?)",
                          (pid,cp[0],cp[1]))

            # 기둥 폴리곤 저장
            for sh in (column_shapes or []):
                coords_json = json.dumps(sh['coords'])
                c.execute("""INSERT INTO column_shapes
                    (project_id,coords,layer,source) VALUES(?,?,?,?)""",
                    (pid, coords_json,
                     sh.get('layer',''), sh.get('source','explicit')))

            # 벽체 형상 저장
            for sh in (wall_shapes or []):
                coords_json = json.dumps(sh['coords'])
                c.execute("""INSERT INTO wall_shapes
                    (project_id,shape_type,coords,layer,source,thickness) VALUES(?,?,?,?,?,?)""",
                    (pid, sh.get('type','line'), coords_json,
                     sh.get('layer',''), sh.get('source','explicit'),
                     sh.get('thickness', 0)))

            # 기둥 Node 저장
            for nd in (column_nodes or []):
                import json as _json
                coords_json = _json.dumps(nd.get('coords') or [])
                c.execute("""INSERT INTO column_nodes
                    (project_id,node_id,cx,cy,width,height,layer,source,col_name,angle,coords)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (pid, nd.get('id',''),
                     nd.get('cx',0), nd.get('cy',0),
                     nd.get('width',0), nd.get('height',0),
                     nd.get('layer',''), nd.get('source','explicit'),
                     nd.get('name',''), nd.get('angle',0),
                     coords_json))

        with self._conn() as c:
            c.execute("UPDATE projects SET updated=? WHERE id=?",(now,pid))

    def load_beams(self, pid):
        import json
        with self._conn() as c:
            rows  = c.execute("SELECT * FROM beams WHERE project_id=? ORDER BY id",(pid,)).fetchall()
            cols  = c.execute("SELECT x,y FROM columns WHERE project_id=?",(pid,)).fetchall()

            # 기둥 폴리곤
            csh   = c.execute(
                "SELECT coords,layer,source FROM column_shapes WHERE project_id=?",(pid,)).fetchall()
            # 벽체 형상
            wsh   = c.execute(
                "SELECT shape_type,coords,layer,source,COALESCE(thickness,0) FROM wall_shapes WHERE project_id=?",(pid,)).fetchall()
            # 기둥 Node
            nds   = c.execute(
                "SELECT node_id,cx,cy,width,height,layer,source,COALESCE(col_name,''),COALESCE(angle,0),COALESCE(coords,'') FROM column_nodes WHERE project_id=?",(pid,)).fetchall()

        beams=[]
        for r in rows:
            beams.append({'db_id':r[0],'project_id':r[1],
                'beam_id':r[2],'beam_layer':r[3],'beam_name':r[4],
                'beam_raw_name':r[5] or r[4],'member_type':r[6] or 'BEAM',
                'span_length':r[7],'beam_width':r[8],'beam_direction':r[9],
                'start_point':(r[10],r[11]),'end_point':(r[12],r[13]),
                'start_column':r[14],'end_column':r[15],
                'memo':r[16] or '','modified':r[17]})

        col_positions = [(r[0],r[1]) for r in cols]

        column_shapes = []
        for r in csh:
            try:
                coords = json.loads(r[0])
                column_shapes.append({'type':'polygon','coords':coords,'layer':r[1],'source':r[2]})
            except: pass

        wall_shapes = []
        for r in wsh:
            try:
                coords = json.loads(r[1])
                wall_shapes.append({'type':r[0],'coords':coords,
                                    'layer':r[2],'source':r[3],
                                    'thickness': r[4] if len(r)>4 else 0})
            except: pass

        column_nodes = []
        for r in nds:
            try:
                coords = json.loads(r[9]) if len(r)>9 and r[9] else []
            except Exception:
                coords = []
            column_nodes.append({
                'id':r[0],'cx':r[1],'cy':r[2],
                'width':r[3],'height':r[4],
                'layer':r[5],'source':r[6],
                'name': r[7] if len(r)>7 else '',
                'angle': r[8] if len(r)>8 else 0.0,
                'coords': coords,
            })

        return beams, col_positions, column_shapes, wall_shapes, column_nodes

    def update_beam(self, db_id, fields):
        now=datetime.now().isoformat()
        ok=['beam_name','beam_raw_name','span_length','beam_width','memo','member_type']
        sets=", ".join(f"{k}=?" for k in fields if k in ok)
        vals=[v for k,v in fields.items() if k in ok]
        if not sets: return
        with self._conn() as c:
            c.execute(f"UPDATE beams SET {sets},updated=?,modified=1 WHERE id=?",
                      vals+[now,db_id])

    def clear_modified(self, pid):
        with self._conn() as c:
            c.execute("UPDATE beams SET modified=0 WHERE project_id=?",(pid,))


# ════════════════════════════════════════════════════════════
#  뷰어
# ════════════════════════════════════════════════════════════
class BeamViewer(tk.Toplevel):
    # 두께 팔레트 (두께 그룹별 색상)
    _WALL_THICKNESS_COLORS = [
        '#4FC3F7','#81C784','#FFB74D','#F06292',
        '#A1887F','#90A4AE','#CE93D8','#80CBC4',
    ]

    def __init__(self, parent, pid, pname, db):
        super().__init__(parent)
        self.title(f"STRCAD 뷰어  |  {pname}")
        self.geometry("1380x820"); self.minsize(1000,600); self.configure(bg=BG)
        self.pid=pid; self.pname=pname; self.db=db

        # DB에서 데이터 로드 (기둥/벽 형상 포함)
        result = db.load_beams(pid)
        if len(result) == 5:
            self.beam_data, self.col_pos, self.col_shapes, self.wall_shapes, self.col_nodes = result
        elif len(result) == 4:
            self.beam_data, self.col_pos, self.col_shapes, self.wall_shapes = result
            self.col_nodes = []
        else:
            # 이전 버전 DB 호환
            self.beam_data, self.col_pos = result[0], result[1]
            self.col_shapes, self.wall_shapes, self.col_nodes = [], [], []

        self.selected   = None
        self.scale      = 1.0
        self.pan        = [0.0, 0.0]
        self._ds        = None
        self._do        = None
        self._type_filter = tk.StringVar(value='전체')
        self._sched_type  = tk.StringVar(value='GIRDER')
        self._hl_group    = None
        self._hl_column   = None   # 기둥 탭 선택 하이라이트
        self._hl_wall_t   = None   # 벽체 두께 그룹 하이라이트
        self._hl_wall_idx = None   # 벽체 개별 하이라이트 (t, idx)
        self._bounds      = self._calc_bounds()

        # 표시 옵션 (기둥/벽 on/off)
        self._show_columns = tk.BooleanVar(value=True)
        self._show_walls   = tk.BooleanVar(value=True)
        self._show_beams   = tk.BooleanVar(value=True)

        _init_style()
        self._build_ui()
        self._draw()

    # ── 메인 UI ─────────────────────────────────────────────
    def _build_ui(self):
        # 툴바
        tb=tk.Frame(self,bg=BG2,height=46); tb.pack(fill='x'); tb.pack_propagate(False)
        tk.Label(tb,text=f"🏗  {self.pname}",font=("Consolas",12,"bold"),
                 bg=BG2,fg=WHITE).pack(side='left',padx=16,pady=10)
        for t,c in [("🔍+",lambda:self._zoom(1.2)),("🔍−",lambda:self._zoom(1/1.2)),
                    ("⟳",self._reset_view)]:
            tk.Button(tb,text=t,command=c,font=("Malgun Gothic",9),bg=BG3,fg=TEXT,
                      relief='flat',padx=8,cursor='hand2').pack(side='left',padx=2,pady=10)

        # ── 표시 토글 버튼 (기둥 / 벽 / 보) ──
        tk.Frame(tb,bg=BORDER,width=1).pack(side='left',fill='y',pady=6,padx=6)
        for var, label, color in [
            (self._show_columns, '🟩 기둥', COL_OUTLINE),
            (self._show_walls,   '🟦 벽',   WALL_COLOR),
            (self._show_beams,   '🔸 보',   MEMBER_COLOR['BEAM']),
        ]:
            cb = tk.Checkbutton(tb, text=label, variable=var, command=self._draw,
                                font=('Malgun Gothic',9), bg=BG2, fg=color,
                                selectcolor=BG3, activebackground=BG2,
                                relief='flat', cursor='hand2')
            cb.pack(side='left', padx=4, pady=10)

        tk.Button(tb,text="💾 전체 저장",command=self._save_all,
                  font=("Malgun Gothic",9,"bold"),bg=ACCENT,fg=WHITE,
                  relief='flat',padx=12,cursor='hand2').pack(side='right',padx=12,pady=10)
        tk.Frame(self,bg=BORDER,height=1).pack(fill='x')

        main=tk.Frame(self,bg=BG); main.pack(fill='both',expand=True)

        # 캔버스
        cvf=tk.Frame(main,bg=BG); cvf.pack(side='left',fill='both',expand=True)
        self.canvas=tk.Canvas(cvf,bg='#0d1117',highlightthickness=0,cursor='crosshair')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',   self._oc)
        self.canvas.bind('<B1-Motion>',        self._od)
        self.canvas.bind('<ButtonRelease-1>',  self._or)
        self.canvas.bind('<MouseWheel>',       self._ow)
        self.canvas.bind('<Configure>',        lambda e: self._draw())

        # 우측 패널
        self._build_side(main)

    def _build_side(self, parent):
        side=tk.Frame(parent,bg=BG2,width=330,
                      highlightbackground=BORDER,highlightthickness=1)
        side.pack(side='right',fill='y'); side.pack_propagate(False)

        top_nb=ttk.Notebook(side); top_nb.pack(fill='both',expand=True)
        self.top_nb = top_nb

        tab_material = tk.Frame(top_nb,bg=BG2)
        top_nb.add(tab_material, text='🧱 재료')
        self._build_material_tab(tab_material)

        tab_member = tk.Frame(top_nb,bg=BG2)
        top_nb.add(tab_member, text='🏗 부재')
        self._build_member_tab(tab_member)

        tab_load = tk.Frame(top_nb,bg=BG2)
        top_nb.add(tab_load, text='⬇ 하중')
        self._build_load_tab(tab_load)

        tab_memo = tk.Frame(top_nb,bg=BG2)
        top_nb.add(tab_memo, text='📝 메모')
        self._build_memo_tab(tab_memo)

        top_nb.select(1)

    # ── 재료 탭 ──────────────────────────────────────────────
    def _build_material_tab(self, p):
        tk.Label(p,text="재료 정보",font=('Malgun Gothic',11,'bold'),
                 bg=BG2,fg=WHITE).pack(anchor='w',padx=16,pady=(16,8))
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)
        for lbl,val in [("콘크리트 강도","fck = 24 MPa"),
                        ("철근 항복강도","fy = 400 MPa"),
                        ("탄성계수 (Ec)","Ec = 25,000 MPa"),
                        ("단위중량","γ = 24 kN/m³")]:
            row=tk.Frame(p,bg=BG2); row.pack(fill='x',padx=16,pady=5)
            tk.Label(row,text=lbl,font=('Malgun Gothic',9),bg=BG2,fg=TEXT2,
                     width=16,anchor='w').pack(side='left')
            tk.Label(row,text=val,font=('Consolas',9),bg=BG2,fg=TEAL).pack(side='left')
        tk.Label(p,text="※ 추후 편집 기능 추가 예정",font=('Malgun Gothic',8),
                 bg=BG2,fg=TEXT2).pack(anchor='w',padx=16,pady=(20,0))

    # ── 하중 탭 ──────────────────────────────────────────────
    def _build_load_tab(self, p):
        tk.Label(p,text="하중 정보",font=('Malgun Gothic',11,'bold'),
                 bg=BG2,fg=WHITE).pack(anchor='w',padx=16,pady=(16,8))
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)
        for lbl,val in [("고정하중 (DL)","4.5 kN/m²"),
                        ("활하중 (LL)",  "2.5 kN/m²"),
                        ("설계하중",     "1.2DL + 1.6LL")]:
            row=tk.Frame(p,bg=BG2); row.pack(fill='x',padx=16,pady=5)
            tk.Label(row,text=lbl,font=('Malgun Gothic',9),bg=BG2,fg=TEXT2,
                     width=16,anchor='w').pack(side='left')
            tk.Label(row,text=val,font=('Consolas',9),bg=BG2,fg=TEAL).pack(side='left')
        tk.Label(p,text="※ 추후 편집 기능 추가 예정",font=('Malgun Gothic',8),
                 bg=BG2,fg=TEXT2).pack(anchor='w',padx=16,pady=(20,0))

    # ── 메모 탭 ──────────────────────────────────────────────
    def _build_memo_tab(self, p):
        tk.Label(p,text="프로젝트 메모",font=('Malgun Gothic',11,'bold'),
                 bg=BG2,fg=WHITE).pack(anchor='w',padx=16,pady=(16,8))
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)
        self.project_memo=tk.Text(p,bg=BG3,fg=WHITE,font=('Malgun Gothic',9),
                                  relief='flat',insertbackground=WHITE,
                                  highlightbackground=BORDER,highlightthickness=1,
                                  padx=8,pady=6)
        self.project_memo.pack(fill='both',expand=True,padx=12,pady=10)
        tk.Button(p,text="💾 메모 저장",command=self._save_memo,
                  font=('Malgun Gothic',9,'bold'),bg=ACCENT,fg=WHITE,
                  relief='flat',cursor='hand2',pady=5
                  ).pack(fill='x',padx=12,pady=(0,12))

    def _save_memo(self):
        messagebox.showinfo("저장","메모가 저장되었습니다.",parent=self)

    # ── 부재 탭 ──────────────────────────────────────────────
    def _build_member_tab(self, p):
        sub_nb = ttk.Notebook(p); sub_nb.pack(fill='both', expand=True)
        self.nb = sub_nb

        t_load   = tk.Frame(sub_nb, bg=BG2); sub_nb.add(t_load,   text='⬇ 하중')
        t_list   = tk.Frame(sub_nb, bg=BG2); sub_nb.add(t_list,   text='📋 부재목록')
        t_edit   = tk.Frame(sub_nb, bg=BG2); sub_nb.add(t_edit,   text='✏ 수정')
        self.detail_frame = t_edit

        self._build_load_tab(t_load)
        self._build_unified_list_tab(t_list)
        self._show_empty_detail()

    # ── 통합 부재목록 탭 ─────────────────────────────────────
    def _build_unified_list_tab(self, p):
        """이미지 형태: 종류 선택 → 그룹 목록 → 선택된 그룹의 개별 부재"""

        # ── 상단: 부재 종류 선택 버튼 ──
        ctrl = tk.Frame(p, bg=BG2); ctrl.pack(fill='x', padx=12, pady=(10,6))
        tk.Label(ctrl, text='부재 종류:', font=('Malgun Gothic',9),
                 bg=BG2, fg=TEXT2).pack(side='left', padx=(0,8))
        self._ul_type = tk.StringVar(value='GIRDER')
        _types = [
            ('거더',  'GIRDER', MEMBER_COLOR['GIRDER']),
            ('보',    'BEAM',   MEMBER_COLOR['BEAM']),
            ('기둥',  'COL',    COL_OUTLINE),
            ('벽체',  'WALL',   WALL_COLOR),
        ]
        for lbl, val, col in _types:
            tk.Radiobutton(ctrl, text=lbl, variable=self._ul_type, value=val,
                           command=self._ul_on_type_change,
                           font=('Malgun Gothic', 9, 'bold'),
                           bg=BG2, fg=col, selectcolor=BG3, activebackground=BG2,
                           relief='flat', indicatoron=False, padx=10, pady=4
                           ).pack(side='left', padx=3)

        tk.Frame(p, bg=BORDER, height=1).pack(fill='x', padx=12)

        # ── 요약 텍스트 ──
        self._ul_summary = tk.StringVar(value='')
        tk.Label(p, textvariable=self._ul_summary,
                 font=('Malgun Gothic', 8), bg=BG2, fg=TEAL,
                 anchor='w').pack(fill='x', padx=14, pady=(4,2))

        # ── 상단 트리뷰: 그룹 목록 ──
        tf1 = tk.Frame(p, bg=BG2); tf1.pack(fill='both', expand=True, padx=8, pady=(2,0))
        sc1 = ttk.Scrollbar(tf1); sc1.pack(side='right', fill='y')
        # 컬럼은 종류별로 동적 교체 → 일단 보/거더용으로 초기화
        self._ul_group_cols_beam  = ('이름',   '개수', '평균스팬', '평균폭')
        self._ul_group_cols_col   = ('이름',   '개수', '대표치수', '기울기')
        self._ul_group_cols_wall  = ('두께',   '개수', '총연장',   '레이어수')
        gcols = self._ul_group_cols_beam
        self.ul_tree = ttk.Treeview(tf1, columns=gcols, show='headings',
                                    style='S.Treeview', yscrollcommand=sc1.set)
        sc1.config(command=self.ul_tree.yview)
        self._ul_set_group_cols(gcols, [80, 50, 80, 70])
        self.ul_tree.pack(fill='both', expand=True)
        self.ul_tree.tag_configure('normal',   foreground=WHITE,  font=('Malgun Gothic',9))
        self.ul_tree.tag_configure('modified', foreground=YELLOW, font=('Malgun Gothic',9,'bold'))
        self.ul_tree.bind('<<TreeviewSelect>>', self._ul_on_group_select)

        # ── 구분선 + 그룹레이블 + 수정버튼 ──
        tk.Frame(p, bg=BORDER, height=1).pack(fill='x', padx=12, pady=(4,2))
        lbl_row = tk.Frame(p, bg=BG2); lbl_row.pack(fill='x', padx=8, pady=(2,2))
        self._ul_group_label = tk.StringVar(value='선택된 이름의 부재')
        tk.Label(lbl_row, textvariable=self._ul_group_label,
                 font=('Malgun Gothic', 8), bg=BG2, fg=TEXT2
                 ).pack(side='left', padx=4)
        self._ul_edit_btn = tk.Button(lbl_row, text='✏ 수정',
                 font=('Malgun Gothic', 8, 'bold'),
                 bg=BLUE, fg=WHITE, relief='flat', cursor='hand2',
                 padx=8, pady=2, state='disabled',
                 command=self._ul_edit_selected)
        self._ul_edit_btn.pack(side='right', padx=4)

        # ── 하단 트리뷰: 개별 부재 목록 ──
        tf2 = tk.Frame(p, bg=BG2); tf2.pack(fill='x', padx=8, pady=(2,8))
        sc2 = ttk.Scrollbar(tf2); sc2.pack(side='right', fill='y')
        self._ul_detail_cols_beam = ('부재ID', '스팬(m)', '폭(mm)', '방향')
        self._ul_detail_cols_col  = ('Node',   '가로(mm)', '세로(mm)', '각도')
        self._ul_detail_cols_wall = ('번호',   '길이(m)', '레이어', '')
        dcols = self._ul_detail_cols_beam
        self.ul_detail_tree = ttk.Treeview(tf2, columns=dcols, show='headings',
                                           height=6, style='S.Treeview',
                                           yscrollcommand=sc2.set)
        sc2.config(command=self.ul_detail_tree.yview)
        self._ul_set_detail_cols(dcols, [80, 60, 60, 55])
        self.ul_detail_tree.pack(fill='x')
        self.ul_detail_tree.tag_configure('normal',   foreground=WHITE,  font=('Malgun Gothic',9))
        self.ul_detail_tree.tag_configure('modified', foreground=YELLOW, font=('Malgun Gothic',9,'bold'))
        self.ul_detail_tree.bind('<<TreeviewSelect>>', self._ul_on_detail_select)

        self._refresh_unified_list()

    def _ul_set_group_cols(self, cols, widths):
        self.ul_tree['columns'] = cols
        for c, w in zip(cols, widths):
            self.ul_tree.heading(c, text=c)
            self.ul_tree.column(c, width=w, anchor='center')

    def _ul_set_detail_cols(self, cols, widths):
        self.ul_detail_tree['columns'] = cols
        for c, w in zip(cols, widths):
            self.ul_detail_tree.heading(c, text=c)
            self.ul_detail_tree.column(c, width=w, anchor='center')

    def _ul_on_type_change(self):
        """종류 버튼 클릭 → 그룹 목록 갱신"""
        self._refresh_unified_list()

    def _refresh_unified_list(self):
        if not hasattr(self, 'ul_tree'): return
        self.ul_tree.delete(*self.ul_tree.get_children())
        if hasattr(self, 'ul_detail_tree'):
            self.ul_detail_tree.delete(*self.ul_detail_tree.get_children())

        from collections import defaultdict
        mt = self._ul_type.get() if hasattr(self, '_ul_type') else 'GIRDER'
        color = {
            'GIRDER': MEMBER_COLOR['GIRDER'],
            'BEAM':   MEMBER_COLOR['BEAM'],
            'COL':    COL_OUTLINE,
            'WALL':   WALL_COLOR,
        }.get(mt, WHITE)
        self.ul_tree.tag_configure('normal',   foreground=color, font=('Malgun Gothic',9))
        self.ul_tree.tag_configure('modified', foreground=YELLOW, font=('Malgun Gothic',9,'bold'))
        if hasattr(self, 'ul_detail_tree'):
            self.ul_detail_tree.tag_configure('normal',   foreground=color, font=('Malgun Gothic',9))
            self.ul_detail_tree.tag_configure('modified', foreground=YELLOW, font=('Malgun Gothic',9,'bold'))

        # ── 거더 / 보 ──────────────────────────────────────
        if mt in ('GIRDER', 'BEAM'):
            groups = defaultdict(list)
            for b in self.beam_data:
                if b['member_type'] == mt:
                    groups[b.get('beam_raw_name') or b['beam_id']].append(b)
            total = sum(len(v) for v in groups.values())
            self._ul_summary.set(f'  총 {total}개 / {len(groups)}종')
            self._ul_set_group_cols(self._ul_group_cols_beam, [80, 50, 80, 70])
            if hasattr(self, 'ul_detail_tree'):
                self._ul_set_detail_cols(self._ul_detail_cols_beam, [80, 60, 60, 55])
                if hasattr(self, '_ul_group_label'):
                    self._ul_group_label.set('선택된 이름의 부재')
            for name in sorted(groups):
                ms    = groups[name]
                spans = [m['span_length'] for m in ms]
                ws    = [m['beam_width'] for m in ms if m.get('beam_width',0)>0]
                avg_s = f"{sum(spans)/len(spans)/1000:.2f}m"
                avg_w = f"{sum(ws)/len(ws):.0f}" if ws else '-'
                has_mod = any(m.get('modified') for m in ms)
                tag = 'modified' if has_mod else 'normal'
                self.ul_tree.insert('', 'end', iid=f'GRP_{name}',
                    values=(name, len(ms), avg_s, avg_w), tags=(tag,))

        # ── 기둥 ───────────────────────────────────────────
        elif mt == 'COL':
            import re as _re
            col_nodes = getattr(self, 'col_nodes', [])
            # 이름 있는 것 vs 없는 것 분리
            named_groups  = defaultdict(list)
            unnamed_nodes = []
            for nd in col_nodes:
                raw_name = nd.get('name','').strip()
                if raw_name:
                    base = _re.sub(r'[-_]?\d+[a-zA-Z]?$','',raw_name).strip() or raw_name
                    named_groups[base].append(nd)
                else:
                    unnamed_nodes.append(nd)
            # 임의명칭 그룹: 치수(WxH)별로 묶기
            auto_groups = defaultdict(list)
            for nd in unnamed_nodes:
                dim_key = f"AUTO_{int(nd['width'])}x{int(nd['height'])}"
                auto_groups[dim_key].append(nd)
            # 합치기
            all_groups = dict(named_groups)
            all_groups.update(auto_groups)
            self._ul_summary.set(f'  총 {len(col_nodes)}개 / {len(all_groups)}종')
            self._ul_set_group_cols(('이름','개수','대표치수','기울기'), [80, 44, 90, 60])
            if hasattr(self, 'ul_detail_tree'):
                self._ul_set_detail_cols(('Node','가로(mm)','세로(mm)','각도'), [65, 65, 65, 55])
                if hasattr(self, '_ul_group_label'):
                    self._ul_group_label.set('선택된 그룹의 기둥')
            for name in sorted(all_groups):
                nds = all_groups[name]
                nd0 = nds[0]
                dim = f"{nd0['width']:.0f}×{nd0['height']:.0f}mm"
                tilted = sum(1 for n in nds if abs(n.get('angle',0)) > 1)
                ang_str = f"{tilted}개 기울어짐" if tilted else '축정렬'
                is_auto = name.startswith('AUTO_')
                disp_name = f"[임의] {nd0['width']:.0f}×{nd0['height']:.0f}" if is_auto else name
                tag_n = f'col_auto_{name}' if is_auto else 'normal'
                if is_auto:
                    self.ul_tree.tag_configure(tag_n, foreground='#aaaaaa',
                                               font=('Malgun Gothic',9,'italic'))
                self.ul_tree.insert('', 'end', iid=f'GRP_{name}',
                    values=(disp_name, len(nds), dim, ang_str), tags=(tag_n,))

        # ── 벽체 ─── 라인만, 100mm 이하 제거 ───────────────
        elif mt == 'WALL':
            wall_shapes = getattr(self, 'wall_shapes', [])
            # 100mm 이하 제거 + 라인만
            valid_walls = [w for w in wall_shapes
                           if w.get('type') == 'line'
                           and len(w.get('coords', [])) >= 2
                           and math.hypot(w['coords'][1][0]-w['coords'][0][0],
                                          w['coords'][1][1]-w['coords'][0][1]) > 100]
            groups = defaultdict(list)
            for w in valid_walls:
                t = int(round(w.get('thickness', 0) / 10) * 10)
                groups[t].append(w)
            self._ul_summary.set(f'  총 {len(valid_walls)}개 / {len(groups)}종')
            self._ul_set_group_cols(('두께','개수','총연장','평균길이'), [70, 44, 80, 75])
            if hasattr(self, 'ul_detail_tree'):
                self._ul_set_detail_cols(('번호','길이(m)','레이어',''), [55, 70, 115, 10])
                if hasattr(self, '_ul_group_label'):
                    self._ul_group_label.set('선택된 두께의 벽체')
            sorted_keys = sorted(groups.keys())
            for t in sorted_keys:
                group = groups[t]
                t_idx = sorted_keys.index(t) % len(self._WALL_THICKNESS_COLORS)
                t_col = self._WALL_THICKNESS_COLORS[t_idx]
                tag_n = f'wall_grp_{t}'
                self.ul_tree.tag_configure(tag_n, foreground=t_col, font=('Malgun Gothic',9))
                lens = [math.hypot(w['coords'][1][0]-w['coords'][0][0],
                                   w['coords'][1][1]-w['coords'][0][1]) for w in group]
                total_len = sum(lens)
                avg_len   = total_len / len(lens) if lens else 0
                t_label = f'{t}mm' if t > 0 else '미분류'
                self.ul_tree.insert('', 'end', iid=f'GRP_{t}',
                    values=(t_label, len(group), f'{total_len/1000:.1f}m',
                            f'{avg_len/1000:.2f}m'),
                    tags=(tag_n,))

    def _ul_on_group_select(self, e):
        """그룹 선택 → 하단 개별 부재 목록 갱신 + 뷰어 하이라이트"""
        sel = self.ul_tree.selection()
        if not sel: return
        iid = sel[0]
        if not iid.startswith('GRP_'): return
        key = iid[4:]

        mt = self._ul_type.get() if hasattr(self, '_ul_type') else 'GIRDER'
        self.ul_detail_tree.delete(*self.ul_detail_tree.get_children())
        if hasattr(self, '_ul_edit_btn'): self._ul_edit_btn.config(state='disabled')

        if mt in ('GIRDER', 'BEAM'):
            name = key
            self._hl_group = name; self._hl_column = None
            ms = [b for b in self.beam_data
                  if b['member_type']==mt
                  and (b.get('beam_raw_name') or b['beam_id'])==name]
            self._ul_group_label.set(f"선택된 이름의 부재  ─  {name}  ({len(ms)}개)")
            # 그룹 중심으로 pan
            if ms:
                all_x = [b['start_point'][0] for b in ms] + [b['end_point'][0] for b in ms]
                all_y = [b['start_point'][1] for b in ms] + [b['end_point'][1] for b in ms]
                self._pan_to((min(all_x)+max(all_x))/2, (min(all_y)+max(all_y))/2)
            else:
                self._draw()
            for b in ms:
                sp  = f"{b['span_length']/1000:.2f}"
                wd  = f"{b['beam_width']:.0f}" if b.get('beam_width',0)>0 else '-'
                tag = 'modified' if b.get('modified') else 'normal'
                self.ul_detail_tree.insert('', 'end',
                    iid=f'DT_{b.get("db_id","")}',
                    values=(b['beam_name'] or b['beam_id'], sp, wd,
                            b.get('beam_direction','')),
                    tags=(tag,))

        elif mt == 'COL':
            import re as _re
            col_nodes = getattr(self, 'col_nodes', [])
            if key.startswith('AUTO_'):
                try:
                    dims = key[5:].split('x')
                    tw, th = int(dims[0]), int(dims[1])
                    nds = [n for n in col_nodes
                           if not n.get('name','').strip()
                           and int(n['width'])==tw and int(n['height'])==th]
                except Exception:
                    nds = []
            else:
                nds = [n for n in col_nodes
                       if (_re.sub(r'[-_]?\d+[a-zA-Z]?$','',n.get('name') or n['id']).strip() or n['id'])==key]
            disp_key = f"[임의] {key[5:]}mm" if key.startswith('AUTO_') else key
            self._ul_group_label.set(f"선택된 그룹의 기둥  ─  {disp_key}  ({len(nds)}개)")
            if nds:
                cx = sum(n['cx'] for n in nds)/len(nds)
                cy = sum(n['cy'] for n in nds)/len(nds)
                self._hl_column = None; self._pan_to(cx, cy)
            for nd in nds:
                ang = f"{nd.get('angle',0):.1f}°" if abs(nd.get('angle',0))>1 else '0°'
                self.ul_detail_tree.insert('', 'end',
                    iid=f'DT_{nd["id"]}',
                    values=(nd['id'],
                            f"{nd['width']:.0f}",
                            f"{nd['height']:.0f}",
                            ang),
                    tags=('normal',))
        elif mt == 'WALL':
            try: t = int(key)
            except: return
            wall_shapes = getattr(self, 'wall_shapes', [])
            group = [w for w in wall_shapes
                     if int(round(w.get('thickness',0)/10)*10)==t]
            t_label = f'{t}mm' if t>0 else '미분류'
            self._ul_group_label.set(f"선택된 두께의 벽체  ─  {t_label}  ({len(group)}개)")
            # 두께 색상
            try:
                sorted_t = sorted(set(int(round(w.get('thickness',0)/10)*10) for w in wall_shapes))
                t_idx = sorted_t.index(t) % len(self._WALL_THICKNESS_COLORS)
                t_col = self._WALL_THICKNESS_COLORS[t_idx]
            except: t_col = WALL_COLOR
            self.ul_detail_tree.tag_configure('wall_item', foreground=t_col, font=('Malgun Gothic',9))
            # 그룹 중심 pan
            if group:
                pts = []
                for w in group:
                    for p in w.get('coords',[]):
                        pts.append(p)
                if pts:
                    self._pan_to(
                        sum(p[0] for p in pts)/len(pts),
                        sum(p[1] for p in pts)/len(pts))
            self._hl_wall_t = t   # 두께 하이라이트 플래그
            self._draw()
            group = [w for w in group
                     if w.get('type')=='line' and len(w.get('coords',[]))>=2
                     and math.hypot(w['coords'][1][0]-w['coords'][0][0],
                                    w['coords'][1][1]-w['coords'][0][1]) > 100]
            for i, w in enumerate(group):
                coords = w.get('coords', [])
                length = 0
                if len(coords)>=2 and w.get('type')=='line':
                    length = math.hypot(
                        coords[1][0]-coords[0][0], coords[1][1]-coords[0][1])
                self.ul_detail_tree.insert('', 'end',
                    iid=f'DT_W_{t}_{i}',
                    values=(f'W{i+1:03d}', f'{length/1000:.3f}', w.get('layer',''), ''),
                    tags=('wall_item',))

    def _ul_on_detail_select(self, e):
        """개별 부재 선택 → 뷰어 pan+하이라이트 + 수정버튼 활성화"""
        sel = self.ul_detail_tree.selection()
        if not sel: return
        iid = sel[0]
        mt = self._ul_type.get() if hasattr(self, '_ul_type') else 'GIRDER'
        if hasattr(self, '_ul_edit_btn'): self._ul_edit_btn.config(state='normal')
        self._ul_selected_iid = iid

        if mt in ('GIRDER','BEAM') and iid.startswith('DT_'):
            try: db_id = int(iid[3:])
            except: return
            b = next((x for x in self.beam_data if x.get('db_id')==db_id), None)
            if b:
                self.selected = b; self._hl_group = None; self._hl_column = None
                mx = (b['start_point'][0]+b['end_point'][0])/2
                my = (b['start_point'][1]+b['end_point'][1])/2
                self._pan_to(mx, my)

        elif mt == 'COL' and iid.startswith('DT_'):
            node_id = iid[3:]
            nd = next((n for n in getattr(self,'col_nodes',[]) if n['id']==node_id), None)
            if nd:
                self._hl_column = node_id; self.selected = None
                self._pan_to(nd['cx'], nd['cy'])

        elif mt == 'WALL' and iid.startswith('DT_W_'):
            # DT_W_{t}_{i} 형식
            parts = iid.split('_')
            if len(parts) >= 4:
                try:
                    t   = int(parts[2])
                    idx = int(parts[3])
                    wall_shapes = getattr(self, 'wall_shapes', [])
                    group = [w for w in wall_shapes
                             if int(round(w.get('thickness',0)/10)*10)==t]
                    if idx < len(group):
                        w = group[idx]
                        coords = w.get('coords',[])
                        if coords:
                            cx = sum(p[0] for p in coords)/len(coords)
                            cy = sum(p[1] for p in coords)/len(coords)
                            self._hl_wall_idx = (t, idx)
                            self._pan_to(cx, cy)
                except Exception:
                    pass

    def _on_ul_select(self, e):
        pass  # 구 통합 이벤트 (미사용)

    def _ul_edit_selected(self):
        """수정 버튼 클릭 → 선택된 부재 종류에 따라 수정 UI로 이동"""
        iid = getattr(self, '_ul_selected_iid', None)
        if not iid: return
        mt = self._ul_type.get() if hasattr(self, '_ul_type') else 'GIRDER'

        if mt in ('GIRDER','BEAM') and iid.startswith('DT_'):
            try: db_id = int(iid[3:])
            except: return
            b = next((x for x in self.beam_data if x.get('db_id')==db_id), None)
            if b:
                self.selected = b
                self._show_detail(b)
                self.nb.select(2)

        elif mt == 'COL' and iid.startswith('DT_'):
            node_id = iid[3:]
            nd = next((n for n in getattr(self,'col_nodes',[]) if n['id']==node_id), None)
            if nd:
                self._show_col_edit(nd)
                self.nb.select(2)

        elif mt == 'WALL' and iid.startswith('DT_W_'):
            parts = iid.split('_')
            if len(parts) >= 4:
                try:
                    t = int(parts[2]); idx = int(parts[3])
                    wall_shapes = getattr(self, 'wall_shapes', [])
                    group = [w for w in wall_shapes
                             if int(round(w.get('thickness',0)/10)*10)==t
                             and w.get('type')=='line' and len(w.get('coords',[]))>=2
                             and math.hypot(w['coords'][1][0]-w['coords'][0][0],
                                            w['coords'][1][1]-w['coords'][0][1]) > 100]
                    if idx < len(group):
                        self._show_wall_edit(group[idx], t, idx)
                        self.nb.select(2)
                except Exception: pass

    def _show_col_edit(self, nd):
        """기둥 수정 탭 UI"""
        for w in self.detail_frame.winfo_children(): w.destroy()
        col = COL_OUTLINE
        tk.Label(self.detail_frame,
                 text=f"  기둥  {nd.get('name') or nd['id']}  ",
                 font=('Malgun Gothic',10,'bold'), bg=col, fg=BG
                 ).pack(anchor='w', padx=12, pady=(12,8))
        fields = [
            ('Node ID',   nd['id'],                   False),
            ('가로 (mm)', f"{nd['width']:.0f}",       True),
            ('세로 (mm)', f"{nd['height']:.0f}",      True),
            ('각도 (°)',  f"{nd.get('angle',0):.1f}", False),
            ('위치 X',    f"{nd['cx']:.0f}",          False),
            ('위치 Y',    f"{nd['cy']:.0f}",          False),
        ]
        self._col_ev = {}
        for lbl2, val, ed in fields:
            row = tk.Frame(self.detail_frame, bg=BG2); row.pack(fill='x', padx=12, pady=2)
            tk.Label(row, text=lbl2, font=('Malgun Gothic',8), bg=BG2, fg=TEXT2,
                     width=10, anchor='w').pack(side='left')
            var = tk.StringVar(value=str(val)); self._col_ev[lbl2] = var
            if ed:
                tk.Entry(row, textvariable=var, font=('Consolas',9),
                         bg=BG3, fg=WHITE, insertbackground=WHITE, relief='flat',
                         highlightbackground=col, highlightthickness=1
                         ).pack(side='left', fill='x', expand=True, ipady=3)
            else:
                tk.Label(row, textvariable=var, font=('Consolas',9),
                         bg=BG2, fg=WHITE).pack(side='left')
        def _save_col():
            try:
                nd['width']  = float(self._col_ev['가로 (mm)'].get())
                nd['height'] = float(self._col_ev['세로 (mm)'].get())
                self._draw()
                messagebox.showinfo('저장', f"기둥 {nd['id']} 저장 완료!", parent=self)
            except Exception as ex:
                messagebox.showerror('오류', str(ex), parent=self)
        tk.Button(self.detail_frame, text='💾 저장', command=_save_col,
                  font=('Malgun Gothic',9,'bold'), bg=ACCENT, fg=WHITE,
                  relief='flat', cursor='hand2', pady=5
                  ).pack(fill='x', padx=12, pady=(14,4))

    def _show_wall_edit(self, w, t, idx):
        """벽체 수정 탭 UI"""
        for ww in self.detail_frame.winfo_children(): ww.destroy()
        coords = w.get('coords', [])
        length = (math.hypot(coords[1][0]-coords[0][0], coords[1][1]-coords[0][1])
                  if len(coords)>=2 else 0)
        try:
            sorted_t = sorted(set(int(round(ww.get('thickness',0)/10)*10)
                                  for ww in getattr(self,'wall_shapes',[])))
            t_col = self._WALL_THICKNESS_COLORS[sorted_t.index(t) % len(self._WALL_THICKNESS_COLORS)]
        except: t_col = WALL_COLOR
        tk.Label(self.detail_frame, text=f"  벽체  {t}mm  ",
                 font=('Malgun Gothic',10,'bold'), bg=t_col, fg=BG
                 ).pack(anchor='w', padx=12, pady=(12,8))
        for lbl2, val in [('두께 (mm)', f'{t}'), ('길이 (m)', f'{length/1000:.3f}'), ('레이어', w.get('layer',''))]:
            row = tk.Frame(self.detail_frame, bg=BG2); row.pack(fill='x', padx=12, pady=2)
            tk.Label(row, text=lbl2, font=('Malgun Gothic',8), bg=BG2, fg=TEXT2,
                     width=10, anchor='w').pack(side='left')
            tk.Label(row, text=val, font=('Consolas',9), bg=BG2, fg=WHITE).pack(side='left')



    # ── 구 탭들 (호환성 유지 - 내부적으로만 사용) ────────────
    # ── 구 탭 스텁 (호환성 유지) ──────────────────────────
    # ── 하위탭3: 수정 ────────────────────────────────────────
    def _show_empty_detail(self):
        for w in self.detail_frame.winfo_children(): w.destroy()
        tk.Label(self.detail_frame,text="부재를 클릭하거나\n목록에서 선택하세요",
                 font=('Malgun Gothic',9),bg=BG2,fg=TEXT2,justify='center').pack(pady=40)

    def _show_detail(self, b):
        for w in self.detail_frame.winfo_children(): w.destroy()
        mt=b['member_type']; col=MEMBER_COLOR.get(mt,'#aaa')
        lbl_mt=MEMBER_LABEL.get(mt,mt)
        mod_badge = "  ✏ 수정됨  " if b.get('modified') else f"  {lbl_mt}  "
        badge_col = YELLOW if b.get('modified') else col
        tk.Label(self.detail_frame,text=mod_badge,
                 font=('Malgun Gothic',10,'bold'),bg=badge_col,fg=BG
                 ).pack(anchor='w',padx=12,pady=(12,8))

        fields=[('보 ID','beam_id',False,''),('이름','beam_name',True,''),
                ('스팬 길이','span_length',True,'mm'),('보 폭','beam_width',True,'mm'),
                ('레이어','beam_layer',False,''),('방향','beam_direction',False,''),
                ('시작 기둥','start_column',False,''),('끝 기둥','end_column',False,'')]
        self.ev={}
        for lbl2,key,ed,unit in fields:
            row=tk.Frame(self.detail_frame,bg=BG2); row.pack(fill='x',padx=12,pady=2)
            tk.Label(row,text=lbl2,font=('Malgun Gothic',8),bg=BG2,fg=TEXT2,
                     width=9,anchor='w').pack(side='left')
            val=b.get(key,'') or ''
            if key in ('span_length','beam_width'):
                val=f"{float(val):.1f}" if val else '0'
            var=tk.StringVar(value=str(val)); self.ev[key]=var
            if ed:
                ew=tk.Entry(row,textvariable=var,font=('Consolas',9),bg=BG3,fg=WHITE,
                            insertbackground=WHITE,relief='flat',
                            highlightbackground=col,highlightthickness=1)
                ew.pack(side='left',fill='x',expand=True,ipady=3)
                if unit: tk.Label(row,text=unit,font=('Malgun Gothic',8),
                                  bg=BG2,fg=TEXT2).pack(side='left',padx=2)
            else:
                tk.Label(row,textvariable=var,font=('Consolas',9),bg=BG2,
                         fg=col if key=='beam_direction' else WHITE).pack(side='left')
        tk.Label(self.detail_frame,text='메모',font=('Malgun Gothic',8),
                 bg=BG2,fg=TEXT2,anchor='w').pack(fill='x',padx=12,pady=(8,2))
        memo=tk.Text(self.detail_frame,height=3,font=('Malgun Gothic',9),
                     bg=BG3,fg=WHITE,insertbackground=WHITE,relief='flat',
                     highlightbackground=BORDER,highlightthickness=1)
        memo.insert('1.0',b.get('memo','')); memo.pack(fill='x',padx=12)

        def _save():
            upd={}
            for k in ('beam_name','span_length','beam_width'):
                if k in self.ev:
                    v=self.ev[k].get().strip()
                    upd[k]=float(v) if k in ('span_length','beam_width') else v
            upd['memo']=memo.get('1.0','end-1c')
            new_name=upd.get('beam_name',b.get('beam_name',''))
            if new_name and new_name!=b.get('beam_name',''):
                raw=re.sub(r'-[0-9]+$','',new_name)
                upd['beam_raw_name']=raw; b['beam_raw_name']=raw
            b.update(upd); b['modified']=1
            if b.get('db_id'): self.db.update_beam(b['db_id'],upd)
            self._refresh_unified_list(); self._draw()
            self._show_detail(b)
            messagebox.showinfo('저장',f"'{b['beam_name']}' 저장 완료!",parent=self)

        btn_row=tk.Frame(self.detail_frame,bg=BG2)
        btn_row.pack(fill='x',padx=12,pady=(10,4))
        tk.Button(btn_row,text='✏  수정하기',command=lambda:self.nb.select(2),
                  font=('Malgun Gothic',9,'bold'),bg=BLUE,fg=WHITE,
                  relief='flat',cursor='hand2',pady=5
                  ).pack(side='left',fill='x',expand=True,padx=(0,4))
        tk.Button(btn_row,text='💾 저장',command=_save,
                  font=('Malgun Gothic',9,'bold'),bg=ACCENT,fg=WHITE,
                  relief='flat',cursor='hand2',pady=5
                  ).pack(side='left',fill='x',expand=True)

    # ── 목록 갱신 (_rl → 통합 목록 갱신 alias) ─────────────
    def _rl(self):
        """통합 부재목록 갱신 (alias for _refresh_unified_list)"""
        self._fl = []   # 하위호환용 빈 리스트 유지
        self._refresh_unified_list()

    # ════════════════════════════════════════════════════════
    #  캔버스 그리기 (기둥·벽 추가)
    # ════════════════════════════════════════════════════════
    def _calc_bounds(self):
        pts = (
            [b['start_point'] for b in self.beam_data] +
            [b['end_point']   for b in self.beam_data] +
            list(self.col_pos) +
            [p for sh in self.col_shapes  for p in sh.get('coords',[])] +
            [p for sh in self.wall_shapes for p in sh.get('coords',[])] +
            [(nd['cx'], nd['cy']) for nd in getattr(self,'col_nodes',[])]
        )
        if not pts: return {'xmin':0,'xmax':1000,'ymin':0,'ymax':1000}
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        pad=max((max(xs)-min(xs))*0.06,(max(ys)-min(ys))*0.06,500)
        return {'xmin':min(xs)-pad,'xmax':max(xs)+pad,
                'ymin':min(ys)-pad,'ymax':max(ys)+pad}

    def _ts(self,wx,wy):
        W=self.canvas.winfo_width() or 800; H=self.canvas.winfo_height() or 600
        bw=self._bounds['xmax']-self._bounds['xmin']
        bh=self._bounds['ymax']-self._bounds['ymin']
        base=min(W/bw,H/bh)*self.scale
        ox=(W-bw*base)/2+self.pan[0]; oy=(H-bh*base)/2+self.pan[1]
        return (ox+(wx-self._bounds['xmin'])*base,
                oy+(self._bounds['ymax']-wy)*base)

    def _draw(self):
        self.canvas.delete('all')
        W=self.canvas.winfo_width() or 800
        H=self.canvas.winfo_height() or 600
        bw=self._bounds['xmax']-self._bounds['xmin']
        bh=self._bounds['ymax']-self._bounds['ymin']
        base=min(W/bw,H/bh)*self.scale

        # ── 1. 벽체 그리기 (두께별 색상 + 두께 시각화) ────────
        if self._show_walls.get():
            _t_buckets = sorted(set(
                int(round(s.get('thickness', 0) / 10) * 10)
                for s in self.wall_shapes))
            hl_wall_t   = getattr(self, '_hl_wall_t',   None)
            hl_wall_idx = getattr(self, '_hl_wall_idx', None)

            def _wt_color(t):
                try: idx = _t_buckets.index(t) % len(BeamViewer._WALL_THICKNESS_COLORS)
                except ValueError: idx = 0
                return BeamViewer._WALL_THICKNESS_COLORS[idx]

            def _wt_lw(t):
                if t <= 0:   return 1
                if t < 150:  return 1
                if t < 250:  return 2
                if t < 400:  return 3
                return 4

            # 그룹별 인덱스 계산 (개별 하이라이트용)
            _w_grp_idx: dict = {}  # (t, i) → index-in-group
            _grp_counters: dict = {}
            for _w in self.wall_shapes:
                _t = int(round(_w.get('thickness',0)/10)*10)
                _grp_counters[_t] = _grp_counters.get(_t, 0)
                _grp_counters[_t] += 1

            _grp_cur: dict = {}
            for _wi, _w in enumerate(self.wall_shapes):
                _t = int(round(_w.get('thickness',0)/10)*10)
                _grp_cur[_t] = _grp_cur.get(_t, 0)
                _w['_grp_i'] = _grp_cur[_t]
                _grp_cur[_t] += 1

            for sh in self.wall_shapes:
                coords = sh.get('coords', [])
                if not coords: continue
                t      = int(round(sh.get('thickness', 0) / 10) * 10)
                grp_i  = sh.get('_grp_i', -1)
                is_hl_t = (hl_wall_t is not None and t == hl_wall_t)
                is_hl_i = (hl_wall_idx is not None and hl_wall_idx == (t, grp_i))

                color = ('#ffffff' if is_hl_i else
                         '#ffff00' if is_hl_t else
                         (_wt_color(t) if t > 0 else WALL_COLOR))
                lw    = (4 if is_hl_i else 3 if is_hl_t else _wt_lw(t))
                sc    = [self._ts(p[0], p[1]) for p in coords]

                if sh['type'] == 'line':
                    if len(sc) >= 2:
                        self.canvas.create_line(
                            sc[0][0], sc[0][1], sc[1][0], sc[1][1],
                            fill=color, width=lw, capstyle='round',
                            tags=('wall',))
                else:
                    flat = [v for pt in sc for v in pt]
                    if len(flat) >= 6:
                        self.canvas.create_polygon(
                            flat, fill=WALL_POLY, outline=color,
                            width=lw, tags=('wall',))

        # ── 2. 기둥: 실제 형태(다각형/회전사각형) + 대각선 + 이름 ─
        if self._show_columns.get():
            hl_col_id = getattr(self, '_hl_column', None)
            col_nodes  = getattr(self, 'col_nodes', [])

            for nd in col_nodes:
                cx_mm, cy_mm = nd['cx'], nd['cy']
                w_mm   = max(nd['width'],  1)
                h_mm   = max(nd['height'], 1)
                angle  = nd.get('angle', 0.0)           # 기울기 (도)
                coords = nd.get('coords') or []          # LWPOLYLINE 원본 좌표
                is_hl  = (hl_col_id == nd['id'])
                is_inf = (nd.get('source','explicit') == 'shape_inferred')

                sx, sy = self._ts(cx_mm, cy_mm)
                pw = w_mm * base   # 폭 픽셀
                ph = h_mm * base   # 높이 픽셀

                # 최소 크기 → 점
                if pw < 4 and ph < 4:
                    r = max(2, int(base * 50))
                    self.canvas.create_oval(
                        sx-r, sy-r, sx+r, sy+r,
                        fill='#4ecca3' if is_hl else COL_OUTLINE,
                        outline='', tags=('col_node', f'cn_{nd["id"]}'))
                    continue

                fill_c    = '#1e5c3a' if is_hl else (COL_INFER   if is_inf else COL_FILL)
                outline_c = '#4ecca3' if is_hl else ('#3a7a3a'   if is_inf else COL_OUTLINE)
                lw_rect   = 2         if is_hl else (1           if is_inf else 2)
                stipple   = ''        if is_hl else ('gray25'    if is_inf else '')

                # ── 다각형 좌표가 있으면 원본 형태로 그림 ────────
                if coords and len(coords) >= 3:
                    sc = [self._ts(p[0], p[1]) for p in coords]
                    flat = [v for pt in sc for v in pt]
                    if len(flat) >= 6:
                        self.canvas.create_polygon(
                            flat,
                            fill=fill_c, outline=outline_c,
                            width=lw_rect, stipple=stipple,
                            tags=('col_poly', f'cn_{nd["id"]}'))
                        # 대각선: polygon 실제 꼭짓점 기반 (기울어진 기둥 반영)
                        if pw >= 4 or ph >= 4:
                            diag_c = '#4ecca3' if is_hl else '#3d7a55'
                            dlw    = 2 if is_hl else 1
                            n_pts  = len(sc)
                            if n_pts >= 4:
                                self.canvas.create_line(sc[0][0],sc[0][1],sc[2][0],sc[2][1],fill=diag_c,width=dlw,tags=('col_node',))
                                self.canvas.create_line(sc[1][0],sc[1][1],sc[3][0],sc[3][1],fill=diag_c,width=dlw,tags=('col_node',))
                            else:
                                x0=min(p[0] for p in sc); y0=min(p[1] for p in sc)
                                x1=max(p[0] for p in sc); y1=max(p[1] for p in sc)
                                self.canvas.create_line(x0,y0,x1,y1,fill=diag_c,width=dlw,tags=('col_node',))
                                self.canvas.create_line(x1,y0,x0,y1,fill=diag_c,width=dlw,tags=('col_node',))

                # ── 좌표 없으면 angle 기반 회전 사각형 ───────────
                else:
                    hw, hh = pw / 2, ph / 2
                    rad = math.radians(angle)
                    ca, sa = math.cos(rad), math.sin(rad)
                    # 로컬 좌표 4코너 → 회전 적용
                    corners_local = [(-hw,-hh),(hw,-hh),(hw,hh),(-hw,hh)]
                    flat = []
                    for lx, ly in corners_local:
                        flat.append(sx + lx*ca - ly*sa)
                        flat.append(sy + lx*sa + ly*ca)
                    self.canvas.create_polygon(
                        flat,
                        fill=fill_c, outline=outline_c,
                        width=lw_rect, stipple=stipple,
                        tags=('col_poly', f'cn_{nd["id"]}'))
                    # 대각선
                    if pw >= 4 or ph >= 4:
                        diag_c = '#4ecca3' if is_hl else '#3d7a55'
                        dlw    = 2 if is_hl else 1
                        xs = flat[0::2]; ys = flat[1::2]
                        self.canvas.create_line(xs[0],ys[0],xs[2],ys[2], fill=diag_c, width=dlw, tags=('col_node',))
                        self.canvas.create_line(xs[1],ys[1],xs[3],ys[3], fill=diag_c, width=dlw, tags=('col_node',))

                # ── 기둥 이름 라벨 ──────────────────────────────
                label = nd.get('name') or nd['id']
                if pw >= 7 or ph >= 7 or is_hl:
                    inside = (pw >= 30 and ph >= 14)
                    tx, ty = sx, (sy if inside else (sy - ph/2 - 3))
                    anchor = 'center' if inside else 's'
                    fs = (8 if is_hl else 7) if pw < 40 else (9 if is_hl else 8)
                    fw = 'bold' if is_hl else 'normal'
                    self.canvas.create_text(
                        tx, ty, text=label,
                        fill='#4ecca3' if is_hl else '#b2dfdb',
                        font=('Malgun Gothic', fs, fw),
                        anchor=anchor, tags=('col_node',))


        # ── 3. 보 그리기 ────────────────────────────────────
        if self._show_beams.get():
            for b in self.beam_data:
                sx1,sy1=self._ts(*b['start_point'])
                sx2,sy2=self._ts(*b['end_point'])
                mt=b['member_type']; col=MEMBER_COLOR.get(mt,'#aaa')
                isSel=self.selected and self.selected.get('db_id')==b.get('db_id')
                isHL=self._hl_group and b['beam_raw_name']==self._hl_group
                isMod=b.get('modified',0)
                lw=6 if isSel else (4 if isHL else 2)
                dc=('#4ecca3' if isSel else
                    '#FFD700'  if isHL  else
                    YELLOW     if isMod else col)
                if b.get('beam_width',0)>0:
                    dx=sx2-sx1; dy=sy2-sy1; ln=math.hypot(dx,dy) or 1
                    hw=b['beam_width']*base/2; nx,ny=-dy/ln,dx/ln
                    self.canvas.create_polygon(
                        sx1+nx*hw,sy1+ny*hw,sx2+nx*hw,sy2+ny*hw,
                        sx2-nx*hw,sy2-ny*hw,sx1-nx*hw,sy1-ny*hw,
                        fill=col,stipple='gray25',outline='')
                self.canvas.create_line(sx1,sy1,sx2,sy2,fill=dc,width=lw,
                                        capstyle='round',
                                        dash=(4,3) if isMod else None)
                if math.hypot(sx2-sx1,sy2-sy1)>35:
                    mx2,my2=(sx1+sx2)/2,(sy1+sy2)/2
                    name=b.get('beam_name') or b['beam_id']
                    self.canvas.create_text(mx2,my2-6,
                        text=f"{name}  {b['span_length']/1000:.2f}m",
                        fill=dc,font=('Consolas',8 if not isSel else 9),anchor='center')

        # ── 4. 범례 ─────────────────────────────────────────
        items=[
            ('기둥 (명시)',    COL_OUTLINE),
            ('기둥 (추론)',    '#2d6a2d'),
            ('벽체',          WALL_COLOR),
            ('거더 (G)',       MEMBER_COLOR['GIRDER']),
            ('보 (B)',         MEMBER_COLOR['BEAM']),
            ('수정됨',         YELLOW),
        ]
        lx,ly=14,14
        for t,c in items:
            self.canvas.create_rectangle(lx,ly,lx+18,ly+10,fill=c,outline='')
            self.canvas.create_text(lx+24,ly+5,text=t,fill=WHITE,
                                    font=('Malgun Gothic',8),anchor='w')
            ly+=18

        # 카운트 표시
        gc  = sum(1 for b in self.beam_data if b['member_type']=='GIRDER')
        bc  = sum(1 for b in self.beam_data if b['member_type']=='BEAM')
        mod = sum(1 for b in self.beam_data if b.get('modified'))
        n_col = len(self.col_shapes)
        n_wall= len(self.wall_shapes)
        self.canvas.create_text(W-10,H-10,
            text=f"기둥 {n_col}  벽 {n_wall}  거더 {gc}  보 {bc}  수정 {mod}",
            fill=TEXT2,font=('Malgun Gothic',8),anchor='se')

    # ── 마우스 이벤트 ────────────────────────────────────────
    def _oc(self,e): self._ds=(e.x,e.y); self._do=list(self.pan)
    def _od(self,e):
        if self._ds:
            self.pan[0]=self._do[0]+e.x-self._ds[0]
            self.pan[1]=self._do[1]+e.y-self._ds[1]; self._draw()
    def _or(self,e):
        if self._ds and math.hypot(e.x-self._ds[0],e.y-self._ds[1])<5:
            self._hit(e.x,e.y)
        self._ds=None
    def _ow(self,e):
        f=1.15 if e.delta>0 else 1/1.15
        self.pan[0]=e.x+(self.pan[0]-e.x)*f
        self.pan[1]=e.y+(self.pan[1]-e.y)*f
        self.scale*=f; self._draw()
    def _zoom(self,f):
        W=self.canvas.winfo_width() or 800; H=self.canvas.winfo_height() or 600
        cx,cy=W/2,H/2
        self.pan[0]=cx+(self.pan[0]-cx)*f; self.pan[1]=cy+(self.pan[1]-cy)*f
        self.scale*=f; self._draw()
    def _reset_view(self): self.pan=[0.0,0.0]; self.scale=1.0; self._draw()

    def _pan_to(self, wx: float, wy: float):
        """세계 좌표 (wx,wy)를 캔버스 중앙으로 pan 이동"""
        W = self.canvas.winfo_width() or 800
        H = self.canvas.winfo_height() or 600
        bw = self._bounds['xmax'] - self._bounds['xmin']
        bh = self._bounds['ymax'] - self._bounds['ymin']
        base = min(W/bw, H/bh) * self.scale
        # 화면 좌표에서 중앙이 되려면:
        sx = (wx - self._bounds['xmin']) * base
        sy = (self._bounds['ymax'] - wy) * base
        # pan = 원하는 화면 중앙 - 스케일 적용된 좌표 - 자연 offset
        nat_ox = (W - bw*base)/2
        nat_oy = (H - bh*base)/2
        self.pan[0] = W/2 - nat_ox - sx
        self.pan[1] = H/2 - nat_oy - sy
        self._draw()

    def _hit(self, mx, my):
        # ── 기둥 Node 클릭 우선 ──────────────────────────────
        col_nodes = getattr(self, 'col_nodes', [])
        hit_col   = None
        best_cd   = float('inf')
        for nd in col_nodes:
            sx, sy = self._ts(nd['cx'], nd['cy'])
            # 클릭 영역: Node 사각형 + 여유 4px
            W = self.canvas.winfo_width()  or 800
            H = self.canvas.winfo_height() or 600
            bw = self._bounds['xmax'] - self._bounds['xmin']
            bh = self._bounds['ymax'] - self._bounds['ymin']
            base = min(W/bw, H/bh) * self.scale
            hw = max(8, nd['width']  * base) / 2 + 4
            hh = max(8, nd['height'] * base) / 2 + 4
            if (sx-hw <= mx <= sx+hw) and (sy-hh <= my <= sy+hh):
                d = math.hypot(mx-sx, my-sy)
                if d < best_cd:
                    best_cd  = d
                    hit_col  = nd

        if hit_col:
            # 기둥 선택
            self._hl_column = hit_col['id']
            self.selected   = None
            self._hl_group  = None
            self._draw()
            # 기둥 탭으로 이동 + 해당 Row 선택
            try:
                self.nb.select(1)   # 부재목록 탭 (index 1)
                cn_iid = f'CN_{hit_col["id"]}'
                if hasattr(self, 'ul_tree'):
                    self.ul_tree.selection_set(cn_iid)
                    self.ul_tree.see(cn_iid)
            except Exception:
                pass
            return

        # ── 보 / 거더 클릭 ──────────────────────────────────
        best, bd = None, 12
        for b in self.beam_data:
            sx1,sy1 = self._ts(*b['start_point'])
            sx2,sy2 = self._ts(*b['end_point'])
            d = self._psd(mx, my, sx1, sy1, sx2, sy2)
            if d < bd:
                bd = d; best = b

        self._hl_column = None
        self.selected   = best
        self._hl_group  = None
        self._draw()
        if best:
            self._show_detail(best)
            # 통합 목록에서 해당 보 하이라이트
            try:
                bid = str(best.get('db_id',''))
                iid = f'B_{bid}'
                if hasattr(self, 'ul_tree'):
                    self.ul_tree.selection_set(iid)
                    self.ul_tree.see(iid)
            except Exception:
                pass
        else:
            self._show_empty_detail()

    def _ols(self, e):
        pass  # 더미

    def _on_member_select(self, e):
        pass  # 통합 목록은 _on_ul_select 에서 처리

    def _save_all(self):
        gc=sum(1 for b in self.beam_data if b['member_type']=='GIRDER')
        bc=sum(1 for b in self.beam_data if b['member_type']=='BEAM')
        mod=sum(1 for b in self.beam_data if b.get('modified'))
        self.db.clear_modified(self.pid)
        for b in self.beam_data: b['modified'] = 0
        self._refresh_unified_list(); self._draw()
        if self.selected: self._show_detail(self.selected)
        messagebox.showinfo('저장 완료',
            f"거더 {gc}개 / 보 {bc}개\n수정 {mod}개 저장 완료",parent=self)

    @staticmethod
    def _psd(px,py,x1,y1,x2,y2):
        dx,dy=x2-x1,y2-y1; l2=dx*dx+dy*dy
        if l2==0: return math.hypot(px-x1,py-y1)
        t=max(0,min(1,((px-x1)*dx+(py-y1)*dy)/l2))
        return math.hypot(px-(x1+t*dx),py-(y1+t*dy))


# ════════════════════════════════════════════════════════════
#  프로젝트 매니저
# ════════════════════════════════════════════════════════════
class ProjectManager(tk.Toplevel):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.title("STRCAD  |  프로젝트 관리")
        self.geometry("580x500"); self.configure(bg=BG)
        self.db = db; _init_style()
        self._build_ui(); self._refresh()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG2, height=52)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text="📂  프로젝트 관리",
                 font=("Malgun Gothic", 13, "bold"),
                 bg=BG2, fg=WHITE).pack(side='left', padx=20, pady=12)
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')
        bb = tk.Frame(self, bg=BG); bb.pack(fill='x', padx=16, pady=(12, 6))
        tk.Button(bb, text="➕  프로젝트 추가", command=self._add,
                  font=('Malgun Gothic', 9, 'bold'), bg=ACCENT, fg=WHITE,
                  relief='flat', padx=12, pady=6, cursor='hand2'
                  ).pack(side='left', padx=(0, 6))
        tk.Button(bb, text="🗑  삭제", command=self._delete,
                  font=('Malgun Gothic', 9), bg=RED, fg=WHITE,
                  relief='flat', padx=10, pady=6, cursor='hand2'
                  ).pack(side='left')
        f = tk.Frame(self, bg=BG); f.pack(fill='both', expand=True, padx=16, pady=(0, 8))
        sc = ttk.Scrollbar(f, orient='vertical'); sc.pack(side='right', fill='y')
        cols = ('이름', '건물명', '생성일', '층수')
        self.tree = ttk.Treeview(f, columns=cols, show='headings',
                                  style='PM.Treeview', yscrollcommand=sc.set)
        sc.config(command=self.tree.yview)
        self.tree.pack(fill='both', expand=True)
        for c, w, a in zip(cols, [200, 160, 110, 60], ['w','w','center','center']):
            self.tree.heading(c, text=c); self.tree.column(c, width=w, anchor=a)
        self.tree.tag_configure('row', foreground=WHITE)
        self.tree.bind('<Double-1>', lambda e: self._open())
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')
        bf = tk.Frame(self, bg=BG); bf.pack(fill='x', padx=16, pady=10)
        tk.Button(bf, text="▶  프로젝트 열기", command=self._open,
                  font=('Malgun Gothic', 10, 'bold'), bg=BLUE, fg=WHITE,
                  relief='flat', padx=16, pady=8, cursor='hand2'
                  ).pack(side='right')

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._projects = self.db.list_projects()
        for pid, name, dxf, created in self._projects:
            floors = self.db.list_floors(pid)
            info   = self.db.get_project_info(pid)
            bname  = (info.get('building_name') or '-')
            self.tree.insert('', 'end', iid=str(pid),
                values=(name, bname, created[:10] if created else '-', len(floors)),
                tags=('row',))

    def _add(self):
        dlg = tk.Toplevel(self); dlg.title("프로젝트 추가")
        dlg.geometry("320x130"); dlg.configure(bg=BG)
        dlg.resizable(False, False); dlg.grab_set()
        tk.Label(dlg, text="프로젝트 이름",
                 font=('Malgun Gothic', 9), bg=BG, fg=TEXT2
                 ).pack(anchor='w', padx=16, pady=(16, 4))
        var = tk.StringVar()
        e = tk.Entry(dlg, textvariable=var,
                     font=('Malgun Gothic', 11), bg=BG3, fg=WHITE,
                     insertbackground=WHITE, relief='flat',
                     highlightbackground=BLUE, highlightthickness=1)
        e.pack(fill='x', padx=16, ipady=6); e.focus()
        def _ok():
            name = var.get().strip()
            if not name: return
            pid = self.db.create_project(name)
            dlg.destroy(); self._refresh()
            ProjectDetail(self, pid, self.db, on_close=self._refresh)
        e.bind('<Return>', lambda ev: _ok())
        tk.Button(dlg, text="추가", command=_ok,
                  font=('Malgun Gothic', 9, 'bold'), bg=ACCENT, fg=WHITE,
                  relief='flat', padx=16, pady=6, cursor='hand2'
                  ).pack(pady=(10, 0))

    def _open(self):
        sel = self.tree.selection()
        if not sel: return
        pid = int(sel[0])
        ProjectDetail(self, pid, self.db, on_close=self._refresh)

    def _delete(self):
        sel = self.tree.selection()
        if not sel: return
        pid  = int(sel[0])
        name = next((p[1] for p in self._projects if p[0] == pid), '')
        if messagebox.askyesno('삭제', f"'{name}' 프로젝트를 삭제할까요?", parent=self):
            self.db.delete_project(pid); self._refresh()


# ════════════════════════════════════════════════════════════
#  프로젝트 상세
# ════════════════════════════════════════════════════════════
class ProjectDetail(tk.Toplevel):
    def __init__(self, parent, pid, db, on_close=None):
        super().__init__(parent)
        self.pid=pid; self.db=db; self.on_close=on_close
        _init_style()
        info = db.get_project_info(pid) or {}
        self._info = info
        self.title("STRCAD  |  " + (info.get('name') or '프로젝트'))
        self.geometry("860x580"); self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui(); self._refresh_floors()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG2, height=52)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        self._title_var = tk.StringVar(value="🏗  " + (self._info.get('name') or ''))
        tk.Label(hdr, textvariable=self._title_var,
                 font=("Malgun Gothic", 12, "bold"),
                 bg=BG2, fg=WHITE).pack(side='left', padx=20, pady=12)
        tk.Button(hdr, text="💾 정보 저장", command=self._save_info,
                  font=('Malgun Gothic', 9, 'bold'), bg=ACCENT, fg=WHITE,
                  relief='flat', padx=10, cursor='hand2'
                  ).pack(side='right', padx=12, pady=14)
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')
        body = tk.Frame(self, bg=BG); body.pack(fill='both', expand=True)
        left = tk.Frame(body, bg=BG2, width=290,
                        highlightbackground=BORDER, highlightthickness=1)
        left.pack(side='left', fill='y'); left.pack_propagate(False)
        self._build_info_panel(left)
        tk.Frame(body, bg=BORDER, width=1).pack(side='left', fill='y')
        right = tk.Frame(body, bg=BG)
        right.pack(side='left', fill='both', expand=True)
        self._build_floor_panel(right)

    def _build_info_panel(self, p):
        tk.Label(p, text="프로젝트 정보",
                 font=('Malgun Gothic', 10, 'bold'),
                 bg=BG2, fg=WHITE).pack(anchor='w', padx=16, pady=(14, 6))
        tk.Frame(p, bg=BORDER, height=1).pack(fill='x', padx=12)
        fields = [("프로젝트명","name"),("건물명","building_name"),
                  ("위치 / 주소","location"),("담당 엔지니어","engineer"),("설명","description")]
        self._info_vars = {}
        for lbl, key in fields:
            row = tk.Frame(p, bg=BG2); row.pack(fill='x', padx=12, pady=4)
            tk.Label(row, text=lbl, font=('Malgun Gothic', 8), bg=BG2, fg=TEXT2,
                     width=13, anchor='w').pack(side='left')
            var = tk.StringVar(value=str(self._info.get(key) or ''))
            self._info_vars[key] = var
            tk.Entry(row, textvariable=var, font=('Malgun Gothic', 9), bg=BG3, fg=WHITE,
                     insertbackground=WHITE, relief='flat',
                     highlightbackground=BORDER, highlightthickness=1
                     ).pack(side='left', fill='x', expand=True, ipady=4)
        tk.Label(p, text="메모", font=('Malgun Gothic', 8), bg=BG2, fg=TEXT2, anchor='w'
                 ).pack(fill='x', padx=12, pady=(8, 2))
        self.memo_text = tk.Text(p, height=7, font=('Malgun Gothic', 9),
                                  bg=BG3, fg=WHITE, insertbackground=WHITE, relief='flat',
                                  highlightbackground=BORDER, highlightthickness=1, padx=6, pady=4)
        self.memo_text.insert('1.0', self._info.get('memo') or '')
        self.memo_text.pack(fill='x', padx=12, pady=(0, 8))
        tk.Frame(p, bg=BORDER, height=1).pack(fill='x', padx=12)
        self._stat_var = tk.StringVar(value='')
        tk.Label(p, textvariable=self._stat_var,
                 font=('Malgun Gothic', 8), bg=BG2, fg=TEAL, anchor='w'
                 ).pack(fill='x', padx=14, pady=6)

    def _build_floor_panel(self, p):
        th = tk.Frame(p, bg=BG); th.pack(fill='x', padx=12, pady=(12, 6))
        tk.Label(th, text="층별 도면 목록",
                 font=('Malgun Gothic', 10, 'bold'),
                 bg=BG, fg=WHITE).pack(side='left')
        for txt, cmd, col in [("▶ 분석", self._run_floor, BLUE),
                               ("🗑 삭제", self._del_floor, RED),
                               ("➕ 층 추가", self._add_floor, ACCENT)]:
            tk.Button(th, text=txt, command=cmd,
                      font=('Malgun Gothic', 9, 'bold'), bg=col, fg=WHITE,
                      relief='flat', padx=8, pady=4, cursor='hand2'
                      ).pack(side='right', padx=3)
        tk.Frame(p, bg=BORDER, height=1).pack(fill='x', padx=12)
        tf = tk.Frame(p, bg=BG); tf.pack(fill='both', expand=True, padx=12, pady=8)
        sc = ttk.Scrollbar(tf); sc.pack(side='right', fill='y')
        cols = ('층', 'DXF 파일', '등록일')
        self.floor_tree = ttk.Treeview(tf, columns=cols, show='headings',
                                        style='PM.Treeview', yscrollcommand=sc.set)
        sc.config(command=self.floor_tree.yview)
        for c, w, a in zip(cols, [80, 340, 110], ['center', 'w', 'center']):
            self.floor_tree.heading(c, text=c); self.floor_tree.column(c, width=w, anchor=a)
        self.floor_tree.tag_configure('ok',      foreground=TEAL)
        self.floor_tree.tag_configure('no_file', foreground=TEXT2)
        self.floor_tree.pack(fill='both', expand=True)
        self.floor_tree.bind('<Double-1>', lambda e: self._run_floor())
        tk.Label(p, text="※ 더블클릭 또는 ▶ 분석 버튼으로 해당 층 구조 분석 실행",
                 font=('Malgun Gothic', 8), bg=BG, fg=TEXT2).pack(anchor='w', padx=14, pady=(0, 8))

    def _refresh_floors(self):
        self.floor_tree.delete(*self.floor_tree.get_children())
        self._floors = self.db.list_floors(self.pid)
        ok_cnt = 0
        for fid, fname, fpath, fcreated in self._floors:
            exists = bool(fpath) and Path(fpath).exists()
            if exists: ok_cnt += 1
            tag = 'ok' if exists else 'no_file'
            disp = Path(fpath).name if fpath else '(파일 없음)'
            self.floor_tree.insert('', 'end', iid=str(fid),
                values=(fname, disp, fcreated[:10] if fcreated else '-'), tags=(tag,))
        self._stat_var.set(f"  층 {len(self._floors)}개  |  파일 {ok_cnt}개")

    def _add_floor(self):
        from tkinter import filedialog
        dlg = tk.Toplevel(self); dlg.title("층 추가")
        dlg.geometry("380x200"); dlg.configure(bg=BG)
        dlg.resizable(False, False); dlg.grab_set()
        tk.Label(dlg, text="층 이름  (예: B3F, B2F, B1F, 1F, RF)",
                 font=('Malgun Gothic', 9), bg=BG, fg=TEXT2
                 ).pack(anchor='w', padx=16, pady=(14, 2))
        fname_var = tk.StringVar()
        fe = tk.Entry(dlg, textvariable=fname_var,
                      font=('Malgun Gothic', 11), bg=BG3, fg=WHITE,
                      insertbackground=WHITE, relief='flat',
                      highlightbackground=BLUE, highlightthickness=1)
        fe.pack(fill='x', padx=16, ipady=5); fe.focus()
        tk.Label(dlg, text="DXF 파일 (선택)",
                 font=('Malgun Gothic', 9), bg=BG, fg=TEXT2
                 ).pack(anchor='w', padx=16, pady=(10, 2))
        path_var = tk.StringVar()
        prow = tk.Frame(dlg, bg=BG); prow.pack(fill='x', padx=16)
        tk.Entry(prow, textvariable=path_var, font=('Consolas', 8), bg=BG3, fg=TEXT,
                 insertbackground=WHITE, relief='flat', state='readonly',
                 highlightbackground=BORDER, highlightthickness=1
                 ).pack(side='left', fill='x', expand=True, ipady=4)
        def _browse():
            p = filedialog.askopenfilename(title="DXF 파일 선택",
                filetypes=[("DXF 파일", "*.dxf"), ("모든 파일", "*.*")])
            if p: path_var.set(p)
        tk.Button(prow, text="찾기", command=_browse,
                  font=('Malgun Gothic', 8), bg=BG3, fg=TEXT,
                  relief='flat', padx=6, cursor='hand2').pack(side='left', padx=(4, 0))
        def _ok():
            n = fname_var.get().strip()
            if not n:
                messagebox.showwarning("입력 오류", "층 이름을 입력하세요", parent=dlg); return
            self.db.add_floor(self.pid, n, path_var.get().strip())
            dlg.destroy(); self._refresh_floors()
        fe.bind('<Return>', lambda ev: _ok())
        tk.Button(dlg, text="추가", command=_ok,
                  font=('Malgun Gothic', 9, 'bold'), bg=ACCENT, fg=WHITE,
                  relief='flat', padx=16, pady=6, cursor='hand2').pack(pady=(12, 0))

    def _del_floor(self):
        sel = self.floor_tree.selection()
        if not sel: return
        fid = int(sel[0])
        fname = next((f[1] for f in self._floors if f[0] == fid), '')
        if messagebox.askyesno('삭제', f"'{fname}' 층을 삭제할까요?", parent=self):
            self.db.delete_floor(fid); self._refresh_floors()

    def _run_floor(self):
        sel = self.floor_tree.selection()
        if not sel:
            messagebox.showinfo("안내", "분석할 층을 선택하세요", parent=self); return
        fid = int(sel[0])
        floor = next((f for f in self._floors if f[0] == fid), None)
        if not floor: return
        _, fname, fpath, _ = floor
        if not fpath or not Path(fpath).exists():
            messagebox.showwarning("파일 없음",
                f"'{fname}' 층의 DXF 파일을 찾을 수 없습니다.\n경로: {fpath}", parent=self); return
        app = self._find_main_app()
        if app and hasattr(app, '_run_analysis_with_file'):
            app._run_analysis_with_file(fpath, fname, self.pid)
            self.destroy()
        else:
            self.clipboard_clear(); self.clipboard_append(fpath)
            messagebox.showinfo("분석 준비",
                f"'{fname}' DXF 경로가 클립보드에 복사되었습니다.", parent=self)

    def _find_main_app(self):
        w = self.master
        while w:
            if type(w).__name__ == 'StrcadApp': return w
            w = getattr(w, 'master', None)
        return None

    def _save_info(self):
        info = {k: v.get() for k, v in self._info_vars.items()}
        info['memo'] = self.memo_text.get('1.0', 'end-1c')
        self.db.update_project_info(self.pid, info)
        self._title_var.set("🏗  " + (info.get('name') or ''))
        self.title("STRCAD  |  " + (info.get('name') or ''))
        messagebox.showinfo("저장", "프로젝트 정보가 저장되었습니다.", parent=self)

    def _on_close(self):
        if self.on_close: self.on_close()
        self.destroy()


# ════════════════════════════════════════════════════════════
#  외부 호출
# ════════════════════════════════════════════════════════════
def open_viewer(parent, beam_data, column_positions,
                project_name=None, dxf_path='', db_path='strcad_data.db',
                project_id=None, floor_name=None,
                column_shapes=None, wall_shapes=None, column_nodes=None):
    db   = BeamDB(db_path)
    name = project_name or ("프로젝트_" + datetime.now().strftime('%Y%m%d_%H%M%S'))
    if project_id:
        pid = project_id
    else:
        pid = db.create_project(name, dxf_path)
    db.save_beams(pid, beam_data, column_positions,
                  column_shapes=column_shapes,
                  wall_shapes=wall_shapes,
                  column_nodes=column_nodes)
    title = name + (" / " + floor_name if floor_name else "")
    BeamViewer(parent, pid, title, db)
    return pid


def open_project_manager(parent, db_path='strcad_data.db'):
    ProjectManager(parent, BeamDB(db_path))


if __name__ == '__main__':
    root = tk.Tk(); root.withdraw()
    open_project_manager(root); root.mainloop()
