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
                FOREIGN KEY(project_id) REFERENCES projects(id))""")
            # col_name 컬럼 없는 구버전 DB 호환
            try:
                c.execute("ALTER TABLE column_nodes ADD COLUMN col_name TEXT DEFAULT ''")
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
                c.execute("""INSERT INTO column_nodes
                    (project_id,node_id,cx,cy,width,height,layer,source,col_name)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (pid, nd.get('id',''),
                     nd.get('cx',0), nd.get('cy',0),
                     nd.get('width',0), nd.get('height',0),
                     nd.get('layer',''), nd.get('source','explicit'),
                     nd.get('name','')))

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
                "SELECT node_id,cx,cy,width,height,layer,source,COALESCE(col_name,'') FROM column_nodes WHERE project_id=?",(pid,)).fetchall()

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
            column_nodes.append({
                'id':r[0],'cx':r[1],'cy':r[2],
                'width':r[3],'height':r[4],
                'layer':r[5],'source':r[6],
                'name': r[7] if len(r)>7 else '',
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
        sub_nb=ttk.Notebook(p); sub_nb.pack(fill='both',expand=True)
        self.nb = sub_nb

        # 기존 탭
        t1=tk.Frame(sub_nb,bg=BG2); sub_nb.add(t1,text='📋 부재 목록')
        t2=tk.Frame(sub_nb,bg=BG2); sub_nb.add(t2,text='📊 이름 목록표')
        t3=tk.Frame(sub_nb,bg=BG2); sub_nb.add(t3,text='✏ 수정')
        self.detail_frame=t3

        # 신규 탭
        t4=tk.Frame(sub_nb,bg=BG2); sub_nb.add(t4,text='🟩 기둥')
        t5=tk.Frame(sub_nb,bg=BG2); sub_nb.add(t5,text='🟦 슬래브')
        t6=tk.Frame(sub_nb,bg=BG2); sub_nb.add(t6,text='🧱 벽체')

        self._build_list_tab(t1)
        self._build_schedule_tab(t2)
        self._show_empty_detail()
        self._build_column_tab(t4)
        self._build_slab_tab(t5)
        self._build_wall_tab(t6)

    # ── 하위탭1: 부재 목록 ──────────────────────────────────
    def _build_list_tab(self, p):
        # 검색 + 필터
        ctrl = tk.Frame(p, bg=BG2); ctrl.pack(fill='x', padx=10, pady=(8,3))
        tk.Label(ctrl, text='검색', font=('Malgun Gothic',8),
                 bg=BG2, fg=TEXT2).pack(side='left', padx=(0,4))
        self.sv = tk.StringVar(); self.sv.trace('w', lambda *a: self._rl())
        tk.Entry(ctrl, textvariable=self.sv, font=('Consolas',9),
                 bg=BG3, fg=TEXT, insertbackground=WHITE, relief='flat',
                 highlightbackground=BORDER, highlightthickness=1, width=14
                 ).pack(side='left', ipady=3)

        filt_row = tk.Frame(p, bg=BG2); filt_row.pack(fill='x', padx=10, pady=(3,4))
        for lbl, val, col in [
            ('전체',  '전체',   '#888888'),
            ('거더',  'GIRDER', MEMBER_COLOR['GIRDER']),
            ('보',    'BEAM',   MEMBER_COLOR['BEAM']),
            ('기둥',  'COL',    COL_OUTLINE),
            ('벽체',  'WALL',   WALL_COLOR),
        ]:
            tk.Radiobutton(filt_row, text=lbl, variable=self._type_filter, value=val,
                           command=self._rl, font=('Malgun Gothic',8),
                           bg=BG2, fg=col, selectcolor=BG3, activebackground=BG2,
                           relief='flat', indicatoron=False, padx=6, pady=3
                           ).pack(side='left', padx=1)

        tk.Frame(p, bg=BORDER, height=1).pack(fill='x', padx=10)
        self._list_count_var = tk.StringVar(value='')
        tk.Label(p, textvariable=self._list_count_var,
                 font=('Malgun Gothic',7), bg=BG2, fg=TEXT2, anchor='w'
                 ).pack(fill='x', padx=12, pady=(2,0))

        tf2 = tk.Frame(p, bg=BG2); tf2.pack(fill='both', expand=True, padx=8, pady=4)
        sc2 = ttk.Scrollbar(tf2); sc2.pack(side='right', fill='y')
        cols2 = ('유형', 'ID', '이름', '치수/스팬', '레이어')
        self.member_tree = ttk.Treeview(tf2, columns=cols2, show='headings',
                                        style='S.Treeview', yscrollcommand=sc2.set)
        sc2.config(command=self.member_tree.yview)
        for c, w in zip(cols2, [40, 55, 72, 72, 78]):
            self.member_tree.heading(c, text=c)
            self.member_tree.column(c, width=w, anchor='center')
        self.member_tree.pack(fill='both', expand=True)
        self.member_tree.tag_configure('GIRDER',  foreground=MEMBER_COLOR['GIRDER'],
                                       font=('Malgun Gothic',9,'bold'))
        self.member_tree.tag_configure('BEAM',    foreground=MEMBER_COLOR['BEAM'],
                                       font=('Malgun Gothic',9))
        self.member_tree.tag_configure('COL',     foreground=COL_OUTLINE,
                                       font=('Malgun Gothic',9,'bold'))
        self.member_tree.tag_configure('COL_INF', foreground='#4a9a4a',
                                       font=('Malgun Gothic',9))
        self.member_tree.tag_configure('WALL',    foreground=WALL_COLOR,
                                       font=('Malgun Gothic',9))
        self.member_tree.tag_configure('MOD',     foreground=YELLOW,
                                       font=('Malgun Gothic',9,'bold'))
        self.member_tree.bind('<<TreeviewSelect>>', self._on_member_select)

        self.lb = tk.Listbox(p, height=0, bg=BG2)  # 더미 (하위호환)
        self._fl = []
        self._rl()

    # ── 🟩 기둥 탭 ──────────────────────────────────────────
    def _build_column_tab(self, p):
        # 헤더
        hdr = tk.Frame(p,bg=BG2); hdr.pack(fill='x',padx=12,pady=(10,4))
        tk.Label(hdr,text='기둥 Node 목록',font=('Malgun Gothic',10,'bold'),
                 bg=BG2,fg=COL_OUTLINE).pack(side='left')
        self._col_count_var = tk.StringVar(value='')
        tk.Label(hdr,textvariable=self._col_count_var,
                 font=('Malgun Gothic',8),bg=BG2,fg=TEXT2).pack(side='right')

        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)

        # Treeview
        tf=tk.Frame(p,bg=BG2); tf.pack(fill='both',expand=True,padx=8,pady=6)
        sc=ttk.Scrollbar(tf); sc.pack(side='right',fill='y')
        cols=('이름','Node','중심X(mm)','중심Y(mm)','가로(mm)','세로(mm)','레이어')
        self.col_tree=ttk.Treeview(tf,columns=cols,show='headings',
                                   style='S.Treeview',yscrollcommand=sc.set)
        sc.config(command=self.col_tree.yview)
        widths=[60,55,75,75,65,65,85]
        for c,w in zip(cols,widths):
            self.col_tree.heading(c,text=c)
            self.col_tree.column(c,width=w,anchor='center')
        self.col_tree.pack(fill='both',expand=True)
        self.col_tree.tag_configure('explicit',foreground=COL_OUTLINE,
                                    font=('Malgun Gothic',9,'bold'))
        self.col_tree.tag_configure('inferred',foreground='#4a7c4a',
                                    font=('Malgun Gothic',9))
        self.col_tree.bind('<<TreeviewSelect>>',self._on_col_select)

        # 하단 상세
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12,pady=(2,2))
        self._col_detail_var = tk.StringVar(value='기둥을 선택하면 상세 정보가 표시됩니다.')
        tk.Label(p,textvariable=self._col_detail_var,
                 font=('Malgun Gothic',8),bg=BG2,fg=TEXT2,
                 wraplength=290,justify='left').pack(anchor='w',padx=14,pady=(4,8))

        self._refresh_column_tab()

    def _refresh_column_tab(self):
        if not hasattr(self,'col_tree'): return
        self.col_tree.delete(*self.col_tree.get_children())
        nodes = getattr(self,'col_nodes',[])
        exp = sum(1 for n in nodes if n.get('source')=='explicit')
        inf = sum(1 for n in nodes if n.get('source')=='shape_inferred')
        self._col_count_var.set(f'총 {len(nodes)}개  (명시 {exp}  추론 {inf})')
        for nd in nodes:
            tag = 'explicit' if nd.get('source')=='explicit' else 'inferred'
            src_label = '명시' if nd.get('source')=='explicit' else '추론'
            self.col_tree.insert('','end',
                values=(nd.get('name') or nd['id'],
                        nd['id'],
                        f"{nd['cx']:.0f}",
                        f"{nd['cy']:.0f}",
                        f"{nd['width']:.0f}",
                        f"{nd['height']:.0f}",
                        nd.get('layer','')),
                tags=(tag,))

    def _on_col_select(self, e):
        sel = self.col_tree.selection()
        if not sel: return
        vals = self.col_tree.item(sel[0],'values')
        if not vals: return
        node_id = vals[1]  # 0=이름, 1=Node ID
        node = next((n for n in self.col_nodes if n['id']==node_id), None)
        if not node: return
        w  = node.get('width',0);  h = node.get('height',0)
        cx = node.get('cx',0);     cy = node.get('cy',0)
        # 연결된 보/거더 찾기
        connected = []
        for b in self.beam_data:
            sc_id = b.get('start_column','')
            ec_id = b.get('end_column','')
            if sc_id == node_id or ec_id == node_id:
                connected.append(b.get('beam_name') or b.get('beam_id',''))
        conn_str = ', '.join(connected[:5]) or '없음'
        if len(connected) > 5: conn_str += f' 외 {len(connected)-5}개'
        detail = (f"▪ 이름 : {node.get('name') or '—'}\n"
                  f"▪ Node : {node_id}\n"
                  f"▪ 위치 : ({cx:.0f}, {cy:.0f})\n"
                  f"▪ 치수 : {w:.0f} × {h:.0f} mm\n"
                  f"▪ 레이어 : {node.get('layer','')}\n"
                  f"▪ 연결 부재 : {conn_str}")
        self._col_detail_var.set(detail)
        # 뷰어에서 해당 기둥 하이라이트
        self._hl_column = node_id
        self._draw()

    # ── 🟦 슬래브 탭 ─────────────────────────────────────────
    def _build_slab_tab(self, p):
        tk.Label(p,text='슬래브 정보',font=('Malgun Gothic',10,'bold'),
                 bg=BG2,fg='#4FC3F7').pack(anchor='w',padx=16,pady=(16,8))
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)

        # 슬래브 요약 (보 스팬으로 계산된 패널)
        info_frame = tk.Frame(p,bg=BG2); info_frame.pack(fill='x',padx=12,pady=8)

        # 보 데이터에서 슬래브 패널 자동 추론
        slab_summary = self._compute_slab_summary()

        for row_data in slab_summary:
            row = tk.Frame(info_frame,bg=BG2); row.pack(fill='x',pady=3)
            tk.Label(row,text=row_data[0],font=('Malgun Gothic',9),
                     bg=BG2,fg=TEXT2,width=14,anchor='w').pack(side='left')
            tk.Label(row,text=row_data[1],font=('Consolas',9),
                     bg=BG2,fg='#4FC3F7').pack(side='left')

        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12,pady=(8,4))
        tk.Label(p,text='※ 슬래브는 보/거더로 둘러싸인 패널 자동 계산\n'
                        '   상세 슬래브 편집 기능은 추후 추가 예정',
                 font=('Malgun Gothic',8),bg=BG2,fg=TEXT2,justify='left'
                 ).pack(anchor='w',padx=16,pady=4)

    def _compute_slab_summary(self):
        """보 스팬 데이터에서 슬래브 패널 요약 계산"""
        if not self.beam_data:
            return [('슬래브 없음','데이터 없음')]
        spans = [b['span_length'] for b in self.beam_data if b.get('span_length',0)>0]
        if not spans:
            return [('데이터','없음')]
        avg_span = sum(spans)/len(spans)/1000
        # X/Y 방향 구분
        x_beams = [b for b in self.beam_data if b.get('beam_direction','')=='X']
        y_beams = [b for b in self.beam_data if b.get('beam_direction','')=='Y']
        # 대략적 슬래브 패널 수 = X방향 보수 × Y방향 보수 / 2
        est_panels = max(1, (len(x_beams) * len(y_beams)) // max(len(x_beams)+len(y_beams),1))
        return [
            ('총 패널 추정', f'{est_panels}개 (추정)'),
            ('X방향 보',   f'{len(x_beams)}개'),
            ('Y방향 보',   f'{len(y_beams)}개'),
            ('평균 스팬',  f'{avg_span:.2f} m'),
            ('최소 스팬',  f'{min(spans)/1000:.2f} m'),
            ('최대 스팬',  f'{max(spans)/1000:.2f} m'),
        ]

    # ── 🧱 벽체 탭 (두께 그룹) ──────────────────────────────
    # 두께 팔레트 (두께mm → 색상)
    _WALL_THICKNESS_COLORS = [
        '#4FC3F7','#81C784','#FFB74D','#F06292',
        '#A1887F','#90A4AE','#CE93D8','#80CBC4',
    ]

    def _wall_thickness_color(self, t: int) -> str:
        """두께값으로 고정 색상 반환"""
        buckets = sorted(self._wall_thickness_buckets) if hasattr(self,'_wall_thickness_buckets') else [0]
        try:
            idx = buckets.index(t) % len(self._WALL_THICKNESS_COLORS)
        except ValueError:
            idx = 0
        return self._WALL_THICKNESS_COLORS[idx]

    def _build_wall_tab(self, p):
        hdr = tk.Frame(p,bg=BG2); hdr.pack(fill='x',padx=12,pady=(10,4))
        tk.Label(hdr,text='벽체 두께 그룹',font=('Malgun Gothic',10,'bold'),
                 bg=BG2,fg=WALL_COLOR).pack(side='left')
        self._wall_count_var = tk.StringVar(value='')
        tk.Label(hdr,textvariable=self._wall_count_var,
                 font=('Malgun Gothic',8),bg=BG2,fg=TEXT2).pack(side='right')
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)

        # 두께 필터 버튼 행
        self._wall_thickness_filter = tk.StringVar(value='전체')
        self._wall_filter_frame = tk.Frame(p,bg=BG2)
        self._wall_filter_frame.pack(fill='x',padx=10,pady=(4,2))

        tf=tk.Frame(p,bg=BG2); tf.pack(fill='both',expand=True,padx=8,pady=(2,4))
        sc=ttk.Scrollbar(tf); sc.pack(side='right',fill='y')
        wcols=('두께(mm)','번호','길이(mm)','레이어')
        self.wall_tree=ttk.Treeview(tf,columns=wcols,show='headings',
                                    style='S.Treeview',yscrollcommand=sc.set)
        sc.config(command=self.wall_tree.yview)
        for c,w in zip(wcols,[65,55,75,100]):
            self.wall_tree.heading(c,text=c)
            self.wall_tree.column(c,width=w,anchor='center')
        self.wall_tree.pack(fill='both',expand=True)
        # 미리 색상 태그 등록 (나중에 동적으로 추가됨)
        self.wall_tree.tag_configure('wall_0',foreground=WALL_COLOR,font=('Malgun Gothic',9))

        # 하단: 선택 두께 합계 정보
        self._wall_detail_var = tk.StringVar(value='두께 그룹을 선택하면 상세 정보 표시')
        tk.Label(p,textvariable=self._wall_detail_var,
                 font=('Malgun Gothic',8),bg=BG2,fg=TEXT2,
                 anchor='w',wraplength=290).pack(fill='x',padx=14,pady=(2,6))

        self._refresh_wall_tab()

    def _refresh_wall_tab(self):
        if not hasattr(self,'wall_tree'): return
        self.wall_tree.delete(*self.wall_tree.get_children())
        walls = getattr(self,'wall_shapes',[])

        # 두께 버킷 계산
        from collections import defaultdict
        thickness_groups = defaultdict(list)
        for w in walls:
            t = int(round(w.get('thickness', 0) / 10) * 10)  # 10mm 단위
            thickness_groups[t].append(w)

        self._wall_thickness_buckets = sorted(thickness_groups.keys())

        # 필터 버튼 재구성
        for child in self._wall_filter_frame.winfo_children():
            child.destroy()
        tk.Radiobutton(self._wall_filter_frame, text='전체',
                       variable=self._wall_thickness_filter, value='전체',
                       command=self._refresh_wall_tab,
                       font=('Malgun Gothic',8), bg=BG2, fg='#888',
                       selectcolor=BG3, activebackground=BG2,
                       relief='flat', indicatoron=False, padx=6, pady=2
                       ).pack(side='left', padx=1)
        for t in self._wall_thickness_buckets:
            col = self._wall_thickness_color(t)
            lbl = f'{t}mm' if t > 0 else '미분류'
            tk.Radiobutton(self._wall_filter_frame, text=lbl,
                           variable=self._wall_thickness_filter, value=str(t),
                           command=self._refresh_wall_tab,
                           font=('Malgun Gothic',8), bg=BG2, fg=col,
                           selectcolor=BG3, activebackground=BG2,
                           relief='flat', indicatoron=False, padx=5, pady=2
                           ).pack(side='left', padx=1)

        # 필터 적용
        sel_t = self._wall_thickness_filter.get()
        if sel_t == '전체':
            show_groups = self._wall_thickness_buckets
        else:
            try: show_groups = [int(sel_t)]
            except: show_groups = self._wall_thickness_buckets

        # 트리뷰 채우기 (두께 그룹 헤더 → 개별 벽체)
        total_shown = 0
        for t in show_groups:
            group = thickness_groups[t]
            col   = self._wall_thickness_color(t)
            tag   = f'wall_t{t}'
            self.wall_tree.tag_configure(tag, foreground=col,
                                          font=('Malgun Gothic',9,'bold'))
            tag_item = f'wall_item_{t}'
            self.wall_tree.tag_configure(tag_item, foreground=col,
                                          font=('Malgun Gothic',8))

            # 그룹 합계 길이
            total_len = 0
            for w in group:
                coords = w.get('coords',[])
                if w.get('type')=='line' and len(coords)>=2:
                    total_len += math.hypot(
                        coords[1][0]-coords[0][0], coords[1][1]-coords[0][1])

            t_label = f'{t}mm' if t > 0 else '미분류'
            # 그룹 헤더 행
            grp_iid = f'grp_{t}'
            self.wall_tree.insert('', 'end', iid=grp_iid,
                values=(f'▶ {t_label}', f'{len(group)}개',
                        f'{total_len/1000:.1f}m', ''),
                tags=(tag,), open=False)

            # 개별 벽체
            for i, w in enumerate(group, 1):
                coords = w.get('coords',[])
                length = 0
                if len(coords)>=2:
                    if w.get('type')=='line':
                        length = math.hypot(
                            coords[1][0]-coords[0][0], coords[1][1]-coords[0][1])
                    else:
                        for j in range(len(coords)):
                            p1=coords[j]; p2=coords[(j+1)%len(coords)]
                            length += math.hypot(p2[0]-p1[0],p2[1]-p1[1])
                self.wall_tree.insert(grp_iid, 'end',
                    values=(t_label, f'W{total_shown+i:03d}',
                            f'{length:.0f}', w.get('layer','')),
                    tags=(tag_item,))
            total_shown += len(group)

        # 카운트 업데이트
        t_count = len([t for t in self._wall_thickness_buckets if t > 0])
        self._wall_count_var.set(
            f'총 {len(walls)}개  두께 {t_count}종  (10mm 단위)')

        # 선택 이벤트
        self.wall_tree.bind('<<TreeviewSelect>>', self._on_wall_select)

    def _on_wall_select(self, e):
        sel = self.wall_tree.selection()
        if not sel: return
        iid = sel[0]
        if iid.startswith('grp_'):
            t_str = iid[4:]
            try:
                t = int(t_str)
                walls = getattr(self,'wall_shapes',[])
                group = [w for w in walls
                         if int(round(w.get('thickness',0)/10)*10)==t]
                total_len = sum(
                    math.hypot(w['coords'][1][0]-w['coords'][0][0],
                               w['coords'][1][1]-w['coords'][0][1])
                    for w in group if w.get('type')=='line' and len(w.get('coords',[]))>=2)
                t_label = f'{t}mm' if t>0 else '미분류'
                self._wall_detail_var.set(
                    f'두께 {t_label}  |  {len(group)}개  |  총 연장 {total_len/1000:.1f}m')
            except: pass

    # ── 하위탭2: 이름 목록표 ────────────────────────────────
    def _build_schedule_tab(self, p):
        ctrl=tk.Frame(p,bg=BG2); ctrl.pack(fill='x',padx=12,pady=(10,6))
        tk.Label(ctrl,text='부재 종류:',font=('Malgun Gothic',9),bg=BG2,fg=TEXT2
                 ).pack(side='left',padx=(0,8))
        for lbl,val,col in [('거더','GIRDER',MEMBER_COLOR['GIRDER']),
                             ('보','BEAM',  MEMBER_COLOR['BEAM'])]:
            tk.Radiobutton(ctrl,text=lbl,variable=self._sched_type,value=val,
                           command=self._rs,font=('Malgun Gothic',9,'bold'),
                           bg=BG2,fg=col,selectcolor=BG3,activebackground=BG2,
                           relief='flat',indicatoron=False,padx=10,pady=4
                           ).pack(side='left',padx=3)
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)
        self.sched_summary=tk.StringVar(value='')
        tk.Label(p,textvariable=self.sched_summary,font=('Malgun Gothic',8),
                 bg=BG2,fg=TEAL,anchor='w').pack(fill='x',padx=14,pady=(4,2))

        tf=tk.Frame(p,bg=BG2); tf.pack(fill='both',expand=True,padx=8,pady=4)
        sc=ttk.Scrollbar(tf); sc.pack(side='right',fill='y')
        cols=('이름','개수','평균스팬','평균폭')
        self.st=ttk.Treeview(tf,columns=cols,show='headings',
                             style='S.Treeview',yscrollcommand=sc.set)
        sc.config(command=self.st.yview)
        for c,w in zip(cols,[70,50,80,70]):
            self.st.heading(c,text=c); self.st.column(c,width=w,anchor='center')
        self.st.pack(fill='both',expand=True)
        self.st.bind('<<TreeviewSelect>>',self._ost)
        self.st.tag_configure('modified', foreground=YELLOW, font=('Malgun Gothic',9,'bold'))
        self.st.tag_configure('normal',   foreground=WHITE,  font=('Malgun Gothic',9))

        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12,pady=(2,2))
        tk.Label(p,text='선택된 이름의 부재',font=('Malgun Gothic',8),
                 bg=BG2,fg=TEXT2).pack(anchor='w',padx=12)
        df=tk.Frame(p,bg=BG2); df.pack(fill='x',padx=8,pady=(2,8))
        sc2=ttk.Scrollbar(df); sc2.pack(side='right',fill='y')
        dc=('부재ID','스팬(m)','폭(mm)','방향')
        self.dt=ttk.Treeview(df,columns=dc,show='headings',height=5,
                             style='S.Treeview',yscrollcommand=sc2.set)
        sc2.config(command=self.dt.yview)
        for c,w in zip(dc,[80,60,60,55]):
            self.dt.heading(c,text=c); self.dt.column(c,width=w,anchor='center')
        self.dt.pack(fill='x')
        self.dt.bind('<<TreeviewSelect>>',self._odt)
        self.dt.tag_configure('modified', foreground=YELLOW, font=('Malgun Gothic',9,'bold'))
        self.dt.tag_configure('normal',   foreground=WHITE,  font=('Malgun Gothic',9))
        self._rs()

    def _rs(self):
        self.st.delete(*self.st.get_children())
        mt=self._sched_type.get()
        groups=defaultdict(list)
        for b in self.beam_data:
            if b['member_type']==mt:
                groups[b['beam_raw_name']].append(b)
        total=sum(len(v) for v in groups.values())
        self.sched_summary.set(f"  총 {total}개 / {len(groups)}종")
        for name in sorted(groups.keys()):
            ms=groups[name]
            sp=[m['span_length'] for m in ms]
            ws=[m['beam_width']  for m in ms if m.get('beam_width',0)>0]
            avg=f"{sum(sp)/len(sp)/1000:.2f}m"
            aw=f"{sum(ws)/len(ws):.0f}" if ws else '-'
            has_mod=any(m.get('modified') for m in ms)
            tag='modified' if has_mod else 'normal'
            self.st.insert('','end',iid=name,
                           values=(name,len(ms),avg,aw),tags=(tag,))

    def _ost(self, e):
        sel=self.st.selection()
        if not sel: return
        name=sel[0]; mt=self._sched_type.get()
        self.dt.delete(*self.dt.get_children())
        self._sm=[]
        for b in self.beam_data:
            if b['member_type']==mt and b['beam_raw_name']==name:
                self._sm.append(b)
                sp=f"{b['span_length']/1000:.2f}"
                wd=f"{b['beam_width']:.0f}" if b.get('beam_width',0)>0 else '-'
                tag='modified' if b.get('modified') else 'normal'
                self.dt.insert('','end',iid=str(b['db_id']),
                               values=(b['beam_name'],sp,wd,b['beam_direction']),
                               tags=(tag,))
        self._hl_group=name; self._draw()

    def _odt(self, e):
        sel=self.dt.selection()
        if not sel: return
        db_id=int(sel[0])
        b=next((x for x in self.beam_data if x.get('db_id')==db_id),None)
        if b:
            self.selected=b; self._draw()
            self._show_detail(b)
            self.nb.select(2)

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
            self._rl(); self._rs(); self._draw()
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

    # ── 목록 갱신 ────────────────────────────────────────────
    def _rl(self):
        """부재 목록 갱신 (거더+보+기둥+벽체 통합)"""
        if not hasattr(self, 'member_tree'):
            return
        self.member_tree.delete(*self.member_tree.get_children())
        self._fl = []

        q  = self.sv.get().lower() if hasattr(self, 'sv') else ''
        tf = self._type_filter.get()

        # 거더 / 보
        for b in self.beam_data:
            mt = b['member_type']
            if tf not in ('전체', mt): continue
            name = b.get('beam_name') or b['beam_id']
            if q and q not in name.lower() and q not in b['beam_id'].lower(): continue
            span_m = f"{b['span_length']/1000:.2f}m"
            tag = 'MOD' if b.get('modified') else mt
            ico = '🔸' if mt=='GIRDER' else '🔹'
            try:
                self.member_tree.insert('', 'end',
                    values=(f"{ico}{mt[:1]}", b['beam_id'], name,
                            span_m, b.get('beam_layer','')),
                    tags=(tag,), iid=f"B_{b['beam_id']}")
            except Exception:
                pass
            self._fl.append(('beam', b))

        # 기둥 Node
        if tf in ('전체', 'COL'):
            for nd in getattr(self, 'col_nodes', []):
                dim = f"{nd['width']:.0f}×{nd['height']:.0f}"
                col_label = nd.get('name') or nd['id']
                if q and q not in col_label.lower() and q not in dim.lower(): continue
                tag = 'COL' if nd.get('source')=='explicit' else 'COL_INF'
                try:
                    self.member_tree.insert('', 'end',
                        values=('🟩C', nd['id'], col_label, dim, nd.get('layer','')),
                        tags=(tag,), iid=f"C_{nd['id']}")
                except Exception:
                    pass
                self._fl.append(('col', nd))

        # 벽체
        if tf in ('전체', 'WALL'):
            for i, w in enumerate(getattr(self, 'wall_shapes', [])):
                wid  = f"W{i+1:03d}"
                coords = w.get('coords', [])
                length = 0
                if len(coords) >= 2:
                    if w.get('type') == 'line':
                        length = math.hypot(
                            coords[1][0]-coords[0][0],
                            coords[1][1]-coords[0][1])
                    else:
                        for j in range(len(coords)):
                            p1=coords[j]; p2=coords[(j+1)%len(coords)]
                            length += math.hypot(p2[0]-p1[0],p2[1]-p1[1])
                t = int(round(w.get('thickness', 0) / 10) * 10)
                t_str = f't={t}mm' if t > 0 else '-'
                if q and q not in wid.lower() and q not in t_str.lower(): continue
                try:
                    self.member_tree.insert('', 'end',
                        values=('🧱W', wid, t_str,
                                f"{length:.0f}mm", w.get('layer','')),
                        tags=('WALL',), iid=f"W_{i}")
                except Exception:
                    pass
                self._fl.append(('wall', w))

        # 카운트
        gc  = sum(1 for b in self.beam_data if b['member_type']=='GIRDER')
        bc  = sum(1 for b in self.beam_data if b['member_type']=='BEAM')
        cc  = len(getattr(self, 'col_nodes', []))
        wc  = len(getattr(self, 'wall_shapes', []))
        shown = len(self.member_tree.get_children())
        if hasattr(self, '_list_count_var'):
            self._list_count_var.set(
                f"거더 {gc}  보 {bc}  기둥 {cc}  벽체 {wc}  |  표시 {shown}개")

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
            # 두께 버킷 목록 (색상 매핑용)
            _t_buckets = sorted(set(
                int(round(s.get('thickness', 0) / 10) * 10)
                for s in self.wall_shapes))

            def _wt_color(t):
                try: idx = _t_buckets.index(t) % len(BeamViewer._WALL_THICKNESS_COLORS)
                except ValueError: idx = 0
                return BeamViewer._WALL_THICKNESS_COLORS[idx]

            # 두께 → 선 굵기 (px): 두꺼운 벽은 더 굵게
            def _wt_lw(t):
                if t <= 0:   return 1
                if t < 150:  return 1
                if t < 250:  return 2
                if t < 400:  return 3
                return 4

            for sh in self.wall_shapes:
                coords = sh.get('coords', [])
                if not coords:
                    continue
                t     = int(round(sh.get('thickness', 0) / 10) * 10)
                color = _wt_color(t) if t > 0 else WALL_COLOR
                lw    = _wt_lw(t)
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

        # ── 2. 기둥: 실제 형태(사각형) + 대각선 + 이름 라벨 ───
        if self._show_columns.get():
            hl_col_id = getattr(self, '_hl_column', None)
            col_nodes  = getattr(self, 'col_nodes', [])

            for nd in col_nodes:
                cx_mm, cy_mm = nd['cx'], nd['cy']
                w_mm  = max(nd['width'],  1)
                h_mm  = max(nd['height'], 1)
                is_hl = (hl_col_id == nd['id'])
                is_inf = (nd.get('source','explicit') == 'shape_inferred')

                # 화면 좌표
                sx, sy = self._ts(cx_mm, cy_mm)

                # 기둥 크기(mm → px)
                pw = w_mm * base   # 폭 픽셀
                ph = h_mm * base   # 높이 픽셀
                hw, hh = pw / 2, ph / 2

                # 최소 표시 크기: 4px 이하면 점으로 대신
                if pw < 4 and ph < 4:
                    r = max(2, int(base * 50))
                    self.canvas.create_oval(
                        sx-r, sy-r, sx+r, sy+r,
                        fill='#4ecca3' if is_hl else COL_OUTLINE,
                        outline='', tags=('col_node', f'cn_{nd["id"]}'))
                    continue

                # ── 기둥 사각형 본체 ────────────────────────────
                x0, y0 = sx - hw, sy - hh
                x1, y1 = sx + hw, sy + hh

                fill_c    = '#1e5c3a' if is_hl else (COL_INFER   if is_inf else COL_FILL)
                outline_c = '#4ecca3' if is_hl else ('#3a7a3a'   if is_inf else COL_OUTLINE)
                lw_rect   = 2         if is_hl else (1           if is_inf else 2)
                stipple   = ''        if is_hl else ('gray25'    if is_inf else '')

                self.canvas.create_rectangle(
                    x0, y0, x1, y1,
                    fill=fill_c, outline=outline_c,
                    width=lw_rect, stipple=stipple,
                    tags=('col_poly', f'cn_{nd["id"]}'))

                # ── 대각선 (기둥 방향 표현, X자) ────────────────
                # 큰 기둥만 (4px 이상)
                if pw >= 4 and ph >= 4:
                    diag_c = '#4ecca3' if is_hl else '#3d7a55'
                    dlw    = 2 if is_hl else 1
                    self.canvas.create_line(
                        x0, y0, x1, y1,
                        fill=diag_c, width=dlw, tags=('col_node',))
                    self.canvas.create_line(
                        x1, y0, x0, y1,
                        fill=diag_c, width=dlw, tags=('col_node',))

                # ── 기둥 이름 라벨 ──────────────────────────────
                label = nd.get('name') or nd['id']
                # 이름 표시 조건: 사각형이 7px 이상이거나 하이라이트
                if pw >= 7 or ph >= 7 or is_hl:
                    # 이름이 사각형 안에 들어가면 내부, 아니면 위에
                    inside = (pw >= 30 and ph >= 14)
                    tx = sx
                    ty = sy if inside else (y0 - 3)
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
                self.nb.select(3)          # 🟩 기둥 탭 (index 3)
                for iid in self.col_tree.get_children():
                    if self.col_tree.item(iid, 'values')[0] == hit_col['id']:
                        self.col_tree.selection_set(iid)
                        self.col_tree.see(iid)
                        self._on_col_select(None)
                        break
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
            for i, fb in enumerate(self._fl):
                if fb.get('db_id') == best.get('db_id'):
                    self.lb.selection_clear(0, 'end')
                    self.lb.selection_set(i)
                    self.lb.see(i)
                    break
        else:
            self._show_empty_detail()

    def _ols(self, e):
        pass  # 더미 (member_tree로 대체)

    def _on_member_select(self, e):
        """통합 부재 목록 선택 이벤트"""
        sel = self.member_tree.selection()
        if not sel: return
        iid = sel[0]

        if iid.startswith('B_'):
            bid = iid[2:]
            b = next((x for x in self.beam_data if x['beam_id']==bid), None)
            if b:
                self.selected   = b
                self._hl_column = None
                self._hl_group  = None
                self._draw()
                self._show_detail(b)
                try: self.nb.select(2)
                except: pass

        elif iid.startswith('C_'):
            nid = iid[2:]
            nd  = next((n for n in getattr(self,'col_nodes',[]) if n['id']==nid), None)
            if nd:
                self._hl_column = nid
                self.selected   = None
                self._draw()
                try:
                    self.nb.select(3)
                    for col_iid in self.col_tree.get_children():
                        if self.col_tree.item(col_iid,'values')[0] == nid:
                            self.col_tree.selection_set(col_iid)
                            self.col_tree.see(col_iid)
                            self._on_col_select(None)
                            break
                except Exception:
                    pass

    def _save_all(self):
        gc=sum(1 for b in self.beam_data if b['member_type']=='GIRDER')
        bc=sum(1 for b in self.beam_data if b['member_type']=='BEAM')
        mod=sum(1 for b in self.beam_data if b.get('modified'))
        self.db.clear_modified(self.pid)
        for b in self.beam_data: b['modified'] = 0
        self._rl(); self._rs(); self._draw()
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
