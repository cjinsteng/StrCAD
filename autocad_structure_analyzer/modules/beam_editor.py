"""
STRCAD 부재 뷰어 v3
- 상위 탭: 재료 / 부재 / 하중 / 메모
- 부재 탭 안에 하위 탭: 📋부재목록 / 📊이름목록표 / ✏수정
- 이름목록표 글씨 흰색, 수정된 부재 노란색
- 전체저장 시 노란색 → 흰색 초기화
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
    # selected 상태에서도 태그 색상 유지되도록 foreground 매핑 추가
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
            # floors 테이블
            c.execute("""CREATE TABLE IF NOT EXISTS floors(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                floor_name TEXT,
                dxf_path TEXT,
                created TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id))""")
            # projects 컬럼 마이그레이션
            proj_exist = {r[1] for r in c.execute("PRAGMA table_info(projects)")}
            for col, dfn in [("description","TEXT DEFAULT ''"),
                             ("building_name","TEXT DEFAULT ''"),
                             ("location","TEXT DEFAULT ''"),
                             ("engineer","TEXT DEFAULT ''"),
                             ("memo","TEXT DEFAULT ''")]:
                if col not in proj_exist:
                    c.execute(f"ALTER TABLE projects ADD COLUMN {col} {dfn}")
            # 마이그레이션
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
        now=datetime.now().isoformat()
        info=info or {}
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
            for t,k in [('beams','project_id'),('columns','project_id'),('projects','id')]:
                c.execute(f"DELETE FROM {t} WHERE {k}=?",(pid,))

    def save_beams(self, pid, beam_data, col_positions):
        now=datetime.now().isoformat()
        with self._conn() as c:
            c.execute("DELETE FROM beams   WHERE project_id=?",(pid,))
            c.execute("DELETE FROM columns WHERE project_id=?",(pid,))
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
                c.execute("INSERT INTO columns(project_id,x,y) VALUES(?,?,?)",(pid,cp[0],cp[1]))
        with self._conn() as c:
            c.execute("UPDATE projects SET updated=? WHERE id=?",(now,pid))

    def load_beams(self, pid):
        with self._conn() as c:
            rows=c.execute("SELECT * FROM beams WHERE project_id=? ORDER BY id",(pid,)).fetchall()
            cols=c.execute("SELECT x,y FROM columns WHERE project_id=?",(pid,)).fetchall()
        beams=[]
        for r in rows:
            beams.append({'db_id':r[0],'project_id':r[1],
                'beam_id':r[2],'beam_layer':r[3],'beam_name':r[4],
                'beam_raw_name':r[5] or r[4],'member_type':r[6] or 'BEAM',
                'span_length':r[7],'beam_width':r[8],'beam_direction':r[9],
                'start_point':(r[10],r[11]),'end_point':(r[12],r[13]),
                'start_column':r[14],'end_column':r[15],
                'memo':r[16] or '','modified':r[17]})
        return beams,[(r[0],r[1]) for r in cols]

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
        """전체저장 후 modified 플래그 초기화"""
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
        self.beam_data, self.col_pos = db.load_beams(pid)
        self.selected   = None
        self.scale      = 1.0
        self.pan        = [0.0, 0.0]
        self._ds        = None
        self._do        = None
        self._type_filter = tk.StringVar(value='전체')
        self._sched_type  = tk.StringVar(value='GIRDER')
        self._hl_group    = None
        self._bounds      = self._calc_bounds()
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

        # 우측 패널 (상위 탭)
        self._build_side(main)

    def _build_side(self, parent):
        side=tk.Frame(parent,bg=BG2,width=330,
                      highlightbackground=BORDER,highlightthickness=1)
        side.pack(side='right',fill='y'); side.pack_propagate(False)

        # ── 상위 탭: 재료 / 부재 / 하중 / 메모 ──
        top_nb=ttk.Notebook(side); top_nb.pack(fill='both',expand=True)
        self.top_nb = top_nb

        # 재료 탭
        tab_material = tk.Frame(top_nb,bg=BG2)
        top_nb.add(tab_material, text='🧱 재료')
        self._build_material_tab(tab_material)

        # 부재 탭 (하위 탭 포함)
        tab_member = tk.Frame(top_nb,bg=BG2)
        top_nb.add(tab_member, text='🏗 부재')
        self._build_member_tab(tab_member)

        # 하중 탭
        tab_load = tk.Frame(top_nb,bg=BG2)
        top_nb.add(tab_load, text='⬇ 하중')
        self._build_load_tab(tab_load)

        # 메모 탭
        tab_memo = tk.Frame(top_nb,bg=BG2)
        top_nb.add(tab_memo, text='📝 메모')
        self._build_memo_tab(tab_memo)

        # 기본으로 부재 탭 선택
        top_nb.select(1)

    # ── 재료 탭 (빈 틀) ─────────────────────────────────────
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

    # ── 하중 탭 (빈 틀) ─────────────────────────────────────
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

    # ── 메모 탭 ─────────────────────────────────────────────
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

    # ── 부재 탭 (하위 탭 3개) ───────────────────────────────
    def _build_member_tab(self, p):
        sub_nb=ttk.Notebook(p); sub_nb.pack(fill='both',expand=True)
        self.nb = sub_nb   # 하위 탭 nb (수정탭 이동용)

        t1=tk.Frame(sub_nb,bg=BG2); sub_nb.add(t1,text='📋 부재 목록')
        t2=tk.Frame(sub_nb,bg=BG2); sub_nb.add(t2,text='📊 이름 목록표')
        t3=tk.Frame(sub_nb,bg=BG2); sub_nb.add(t3,text='✏ 수정')
        self.detail_frame=t3

        self._build_list_tab(t1)
        self._build_schedule_tab(t2)
        self._show_empty_detail()

    # ── 하위탭1: 부재 목록 ──────────────────────────────────
    def _build_list_tab(self, p):
        tk.Label(p,text='검색',font=('Malgun Gothic',9),bg=BG2,fg=TEXT2
                 ).pack(anchor='w',padx=12,pady=(10,2))
        self.sv=tk.StringVar(); self.sv.trace('w',lambda*a:self._rl())
        tk.Entry(p,textvariable=self.sv,font=('Consolas',10),bg=BG3,fg=TEXT,
                 insertbackground=WHITE,relief='flat',
                 highlightbackground=BORDER,highlightthickness=1
                 ).pack(fill='x',padx=12,ipady=6,pady=(0,6))
        f=tk.Frame(p,bg=BG2); f.pack(fill='x',padx=12,pady=(0,6))
        for lbl,val,col in [('전체','전체','#888'),
                             ('거더','GIRDER',MEMBER_COLOR['GIRDER']),
                             ('보','BEAM',  MEMBER_COLOR['BEAM'])]:
            tk.Radiobutton(f,text=lbl,variable=self._type_filter,value=val,
                           command=self._rl,font=('Malgun Gothic',9),
                           bg=BG2,fg=col,selectcolor=BG3,activebackground=BG2,
                           relief='flat',indicatoron=False,padx=8,pady=3
                           ).pack(side='left',padx=2)
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)
        lf=tk.Frame(p,bg=BG2); lf.pack(fill='both',expand=True,padx=12,pady=6)
        sc=tk.Scrollbar(lf,bg=BG3); sc.pack(side='right',fill='y')
        self.lb=tk.Listbox(lf,bg=BG3,fg=WHITE,font=('Consolas',9),relief='flat',
                           selectbackground=BLUE,selectforeground=WHITE,
                           yscrollcommand=sc.set,activestyle='none',borderwidth=0)
        self.lb.pack(fill='both',expand=True)
        sc.config(command=self.lb.yview)
        self.lb.bind('<<ListboxSelect>>',self._ols)
        self._rl()

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

        # 이름별 트리뷰
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
        # ★ 수정 표시용 태그 (pack 이후에 설정해야 확실히 적용)
        self.st.tag_configure('modified', foreground=YELLOW, font=('Malgun Gothic',9,'bold'))
        self.st.tag_configure('normal',   foreground=WHITE,  font=('Malgun Gothic',9))

        # 하단: 개별 부재 목록
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
        # ★ pack 이후 태그 설정
        self.dt.tag_configure('modified', foreground=YELLOW, font=('Malgun Gothic',9,'bold'))
        self.dt.tag_configure('normal',   foreground=WHITE,  font=('Malgun Gothic',9))
        self._rs()

    def _rs(self):
        """이름 목록표 갱신 (수정된 그룹은 노란색)"""
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
            # 해당 이름 그룹에 수정된 부재가 하나라도 있으면 노란색
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
                # 수정된 부재는 노란색
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
            self.nb.select(2)   # 수정 탭으로

    # ── 하위탭3: 수정 ────────────────────────────────────────
    def _show_empty_detail(self):
        for w in self.detail_frame.winfo_children(): w.destroy()
        tk.Label(self.detail_frame,text="부재를 클릭하거나\n목록에서 선택하세요",
                 font=('Malgun Gothic',9),bg=BG2,fg=TEXT2,justify='center').pack(pady=40)

    def _show_detail(self, b):
        for w in self.detail_frame.winfo_children(): w.destroy()
        mt=b['member_type']; col=MEMBER_COLOR.get(mt,'#aaa')
        lbl_mt=MEMBER_LABEL.get(mt,mt)
        # 수정 여부 배지
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
            # 수정 배지 업데이트
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
        self.lb.delete(0,'end'); self._fl=[]
        q=self.sv.get().lower() if hasattr(self,'sv') else ''
        tf=self._type_filter.get()
        for b in self.beam_data:
            if tf!='전체' and b['member_type']!=tf: continue
            name=b['beam_name'] or b['beam_id']
            if q and q not in name.lower() and q not in b['beam_id'].lower(): continue
            self._fl.append(b)
            ico='🔸' if b['member_type']=='GIRDER' else '🔹'
            mod=' ✏' if b.get('modified') else ''
            self.lb.insert('end',f"{ico} {name}  {b['span_length']/1000:.2f}m{mod}")
            # 수정된 항목 노란색
            if b.get('modified'):
                self.lb.itemconfig(len(self._fl)-1,fg=YELLOW)

    # ── 캔버스 ───────────────────────────────────────────────
    def _calc_bounds(self):
        pts=([b['start_point'] for b in self.beam_data]+
             [b['end_point']   for b in self.beam_data]+list(self.col_pos))
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
        csz=max(5,int(250*base))

        for cp in self.col_pos:
            sx,sy=self._ts(*cp); hs=csz//2
            self.canvas.create_rectangle(sx-hs,sy-hs,sx+hs,sy+hs,
                                         fill='#1b3a1b',outline='#4CAF50',width=1)
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
        # 범례
        items=[('거더 (G)',MEMBER_COLOR['GIRDER']),
               ('보 (B)',  MEMBER_COLOR['BEAM']),
               ('수정됨',  YELLOW),
               ('기둥',    '#4CAF50')]
        lx,ly=14,14
        for t,c in items:
            self.canvas.create_rectangle(lx,ly,lx+18,ly+10,fill=c,outline='')
            self.canvas.create_text(lx+24,ly+5,text=t,fill=WHITE,
                                    font=('Malgun Gothic',8),anchor='w')
            ly+=18
        gc=sum(1 for b in self.beam_data if b['member_type']=='GIRDER')
        bc=sum(1 for b in self.beam_data if b['member_type']=='BEAM')
        mod=sum(1 for b in self.beam_data if b.get('modified'))
        self.canvas.create_text(W-10,H-10,
            text=f"거더 {gc}  보 {bc}  수정 {mod}",
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

    def _hit(self,mx,my):
        best,bd=None,12
        for b in self.beam_data:
            sx1,sy1=self._ts(*b['start_point']); sx2,sy2=self._ts(*b['end_point'])
            d=self._psd(mx,my,sx1,sy1,sx2,sy2)
            if d<bd: bd=d; best=b
        self.selected=best; self._hl_group=None; self._draw()
        if best:
            self._show_detail(best)
            for i,fb in enumerate(self._fl):
                if fb.get('db_id')==best.get('db_id'):
                    self.lb.selection_clear(0,'end')
                    self.lb.selection_set(i); self.lb.see(i); break
        else:
            self._show_empty_detail()

    def _ols(self,e):
        sel=self.lb.curselection()
        if not sel: return
        b=self._fl[sel[0]]; self.selected=b; self._hl_group=None; self._draw()
        self._show_detail(b)

    def _save_all(self):
        """전체 저장: DB 저장 + modified 초기화 + 노란색 → 흰색"""
        gc=sum(1 for b in self.beam_data if b['member_type']=='GIRDER')
        bc=sum(1 for b in self.beam_data if b['member_type']=='BEAM')
        mod=sum(1 for b in self.beam_data if b.get('modified'))

        # DB modified 플래그 초기화
        self.db.clear_modified(self.pid)
        # 메모리 데이터도 초기화
        for b in self.beam_data:
            b['modified'] = 0

        # UI 갱신 (노란색 → 흰색)
        self._rl()
        self._rs()
        self._draw()
        # 현재 선택된 부재 detail 갱신
        if self.selected:
            self._show_detail(self.selected)

        messagebox.showinfo('저장 완료',
            f"거더 {gc}개 / 보 {bc}개\n수정 {mod}개 저장 완료",parent=self)

    @staticmethod
    def _psd(px,py,x1,y1,x2,y2):
        dx,dy=x2-x1,y2-y1; l2=dx*dx+dy*dy
        if l2==0: return math.hypot(px-x1,py-y1)
        t=max(0,min(1,((px-x1)*dx+(py-y1)*dy)/l2))
        return math.hypot(px-(x1+t*dx),py-(y1+t*dy))



# ════════════════════════════════════════════════════════════
#  프로젝트 매니저  ―  목록 화면
# ════════════════════════════════════════════════════════════
class ProjectManager(tk.Toplevel):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.title("STRCAD  |  프로젝트 관리")
        self.geometry("580x500"); self.configure(bg=BG)
        self.db = db; _init_style()
        self._build_ui(); self._refresh()

    # ── UI ──────────────────────────────────────────────────
    def _build_ui(self):
        # 헤더
        hdr = tk.Frame(self, bg=BG2, height=52)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text="📂  프로젝트 관리",
                 font=("Malgun Gothic", 13, "bold"),
                 bg=BG2, fg=WHITE).pack(side='left', padx=20, pady=12)
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')

        # 버튼 바
        bb = tk.Frame(self, bg=BG); bb.pack(fill='x', padx=16, pady=(12, 6))
        tk.Button(bb, text="➕  프로젝트 추가", command=self._add,
                  font=('Malgun Gothic', 9, 'bold'), bg=ACCENT, fg=WHITE,
                  relief='flat', padx=12, pady=6, cursor='hand2'
                  ).pack(side='left', padx=(0, 6))
        tk.Button(bb, text="🗑  삭제", command=self._delete,
                  font=('Malgun Gothic', 9), bg=RED, fg=WHITE,
                  relief='flat', padx=10, pady=6, cursor='hand2'
                  ).pack(side='left')

        # 프로젝트 목록 트리뷰
        f = tk.Frame(self, bg=BG); f.pack(fill='both', expand=True, padx=16, pady=(0, 8))
        sc = ttk.Scrollbar(f, orient='vertical')
        sc.pack(side='right', fill='y')
        cols = ('이름', '건물명', '생성일', '층수')
        self.tree = ttk.Treeview(f, columns=cols, show='headings',
                                  style='PM.Treeview', yscrollcommand=sc.set)
        sc.config(command=self.tree.yview)
        self.tree.pack(fill='both', expand=True)
        for c, w, a in zip(cols, [200, 160, 110, 60],
                           ['w',   'w',  'center', 'center']):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor=a)
        self.tree.tag_configure('row', foreground=WHITE)
        self.tree.bind('<Double-1>', lambda e: self._open())

        # 하단 열기 버튼
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
                values=(name, bname,
                        created[:10] if created else '-',
                        len(floors)),
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
            if not name:
                return
            pid = self.db.create_project(name)
            dlg.destroy()
            self._refresh()
            ProjectDetail(self, pid, self.db, on_close=self._refresh)

        e.bind('<Return>', lambda ev: _ok())
        tk.Button(dlg, text="추가", command=_ok,
                  font=('Malgun Gothic', 9, 'bold'), bg=ACCENT, fg=WHITE,
                  relief='flat', padx=16, pady=6, cursor='hand2'
                  ).pack(pady=(10, 0))

    def _open(self):
        sel = self.tree.selection()
        if not sel:
            return
        pid = int(sel[0])
        ProjectDetail(self, pid, self.db, on_close=self._refresh)

    def _delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        pid  = int(sel[0])
        name = next((p[1] for p in self._projects if p[0] == pid), '')
        msg  = "'" + name + "' 프로젝트를 삭제할까요?\n(모든 분석 데이터가 삭제됩니다)"
        if messagebox.askyesno('삭제', msg, parent=self):
            self.db.delete_project(pid)
            self._refresh()


# ════════════════════════════════════════════════════════════
#  프로젝트 상세  ―  정보 + 층별 도면 목록
# ════════════════════════════════════════════════════════════
class ProjectDetail(tk.Toplevel):
    """
    좌측 : 프로젝트 정보 (이름·건물명·위치·담당자·설명·메모)
    우측 : 층별 DXF 파일 목록 (층 / DXF 파일 / 등록일)
              ➕ 층 추가  🗑 삭제  ▶ 분석
    캔버스 저장 시 어떤 프로젝트 몇 층인지 저장
    """
    def __init__(self, parent, pid, db, on_close=None):
        super().__init__(parent)
        self.pid      = pid
        self.db       = db
        self.on_close = on_close
        _init_style()
        info = db.get_project_info(pid) or {}
        self._info = info
        self.title("STRCAD  |  " + (info.get('name') or '프로젝트'))
        self.geometry("860x580"); self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self._refresh_floors()

    # ── UI ──────────────────────────────────────────────────
    def _build_ui(self):
        # 헤더
        hdr = tk.Frame(self, bg=BG2, height=52)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        self._title_var = tk.StringVar(
            value="🏗  " + (self._info.get('name') or ''))
        tk.Label(hdr, textvariable=self._title_var,
                 font=("Malgun Gothic", 12, "bold"),
                 bg=BG2, fg=WHITE).pack(side='left', padx=20, pady=12)
        tk.Button(hdr, text="💾 정보 저장", command=self._save_info,
                  font=('Malgun Gothic', 9, 'bold'), bg=ACCENT, fg=WHITE,
                  relief='flat', padx=10, cursor='hand2'
                  ).pack(side='right', padx=12, pady=14)
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')

        # 본문 2분할
        body = tk.Frame(self, bg=BG); body.pack(fill='both', expand=True)

        # 좌측 정보 패널
        left = tk.Frame(body, bg=BG2, width=290,
                        highlightbackground=BORDER, highlightthickness=1)
        left.pack(side='left', fill='y'); left.pack_propagate(False)
        self._build_info_panel(left)

        tk.Frame(body, bg=BORDER, width=1).pack(side='left', fill='y')

        # 우측 층 패널
        right = tk.Frame(body, bg=BG)
        right.pack(side='left', fill='both', expand=True)
        self._build_floor_panel(right)

    # ── 좌측: 프로젝트 정보 ─────────────────────────────────
    def _build_info_panel(self, p):
        tk.Label(p, text="프로젝트 정보",
                 font=('Malgun Gothic', 10, 'bold'),
                 bg=BG2, fg=WHITE).pack(anchor='w', padx=16, pady=(14, 6))
        tk.Frame(p, bg=BORDER, height=1).pack(fill='x', padx=12)

        fields = [
            ("프로젝트명",    "name"),
            ("건물명",         "building_name"),
            ("위치 / 주소",    "location"),
            ("담당 엔지니어",  "engineer"),
            ("설명",           "description"),
        ]
        self._info_vars = {}
        for lbl, key in fields:
            row = tk.Frame(p, bg=BG2); row.pack(fill='x', padx=12, pady=4)
            tk.Label(row, text=lbl,
                     font=('Malgun Gothic', 8), bg=BG2, fg=TEXT2,
                     width=13, anchor='w').pack(side='left')
            var = tk.StringVar(value=str(self._info.get(key) or ''))
            self._info_vars[key] = var
            tk.Entry(row, textvariable=var,
                     font=('Malgun Gothic', 9), bg=BG3, fg=WHITE,
                     insertbackground=WHITE, relief='flat',
                     highlightbackground=BORDER, highlightthickness=1
                     ).pack(side='left', fill='x', expand=True, ipady=4)

        # 메모
        tk.Label(p, text="메모",
                 font=('Malgun Gothic', 8), bg=BG2, fg=TEXT2, anchor='w'
                 ).pack(fill='x', padx=12, pady=(8, 2))
        self.memo_text = tk.Text(
            p, height=7, font=('Malgun Gothic', 9),
            bg=BG3, fg=WHITE, insertbackground=WHITE, relief='flat',
            highlightbackground=BORDER, highlightthickness=1,
            padx=6, pady=4)
        self.memo_text.insert('1.0', self._info.get('memo') or '')
        self.memo_text.pack(fill='x', padx=12, pady=(0, 8))

        # 통계 라벨
        tk.Frame(p, bg=BORDER, height=1).pack(fill='x', padx=12)
        self._stat_var = tk.StringVar(value='')
        tk.Label(p, textvariable=self._stat_var,
                 font=('Malgun Gothic', 8), bg=BG2, fg=TEAL, anchor='w'
                 ).pack(fill='x', padx=14, pady=6)

    # ── 우측: 층별 도면 목록 ────────────────────────────────
    def _build_floor_panel(self, p):
        # 상단 제목 + 버튼
        th = tk.Frame(p, bg=BG); th.pack(fill='x', padx=12, pady=(12, 6))
        tk.Label(th, text="층별 도면 목록",
                 font=('Malgun Gothic', 10, 'bold'),
                 bg=BG, fg=WHITE).pack(side='left')
        for txt, cmd, col in [
            ("▶ 분석",    self._run_floor,  BLUE),
            ("🗑 삭제",    self._del_floor,  RED),
            ("➕ 층 추가", self._add_floor,  ACCENT),
        ]:
            tk.Button(th, text=txt, command=cmd,
                      font=('Malgun Gothic', 9, 'bold'), bg=col, fg=WHITE,
                      relief='flat', padx=8, pady=4, cursor='hand2'
                      ).pack(side='right', padx=3)
        tk.Frame(p, bg=BORDER, height=1).pack(fill='x', padx=12)

        # 트리뷰
        tf = tk.Frame(p, bg=BG); tf.pack(fill='both', expand=True, padx=12, pady=8)
        sc = ttk.Scrollbar(tf); sc.pack(side='right', fill='y')
        cols = ('층', 'DXF 파일', '등록일')
        self.floor_tree = ttk.Treeview(
            tf, columns=cols, show='headings',
            style='PM.Treeview', yscrollcommand=sc.set)
        sc.config(command=self.floor_tree.yview)
        for c, w, a in zip(cols, [80, 340, 110],
                           ['center', 'w', 'center']):
            self.floor_tree.heading(c, text=c)
            self.floor_tree.column(c, width=w, anchor=a)
        self.floor_tree.tag_configure('ok',      foreground=TEAL)
        self.floor_tree.tag_configure('no_file', foreground=TEXT2)
        self.floor_tree.pack(fill='both', expand=True)
        self.floor_tree.bind('<Double-1>', lambda e: self._run_floor())

        # 안내 문구
        tk.Label(p,
                 text="※ 더블클릭 또는 ▶ 분석 버튼으로 해당 층 구조 분석 실행",
                 font=('Malgun Gothic', 8), bg=BG, fg=TEXT2
                 ).pack(anchor='w', padx=14, pady=(0, 8))

    # ── 층 목록 갱신 ────────────────────────────────────────
    def _refresh_floors(self):
        self.floor_tree.delete(*self.floor_tree.get_children())
        self._floors = self.db.list_floors(self.pid)
        ok_cnt = 0
        for fid, fname, fpath, fcreated in self._floors:
            exists = bool(fpath) and Path(fpath).exists()
            if exists:
                ok_cnt += 1
            tag      = 'ok' if exists else 'no_file'
            disp     = Path(fpath).name if fpath else '(파일 없음)'
            created  = fcreated[:10] if fcreated else '-'
            self.floor_tree.insert('', 'end', iid=str(fid),
                values=(fname, disp, created), tags=(tag,))
        self._stat_var.set(
            "  층 " + str(len(self._floors)) + "개"
            "  |  파일 " + str(ok_cnt) + "개")

    # ── 층 추가 다이얼로그 ───────────────────────────────────
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
        tk.Entry(prow, textvariable=path_var,
                 font=('Consolas', 8), bg=BG3, fg=TEXT,
                 insertbackground=WHITE, relief='flat', state='readonly',
                 highlightbackground=BORDER, highlightthickness=1
                 ).pack(side='left', fill='x', expand=True, ipady=4)

        def _browse():
            p = filedialog.askopenfilename(
                title="DXF 파일 선택",
                filetypes=[("DXF 파일", "*.dxf"), ("모든 파일", "*.*")])
            if p:
                path_var.set(p)

        tk.Button(prow, text="찾기", command=_browse,
                  font=('Malgun Gothic', 8), bg=BG3, fg=TEXT,
                  relief='flat', padx=6, cursor='hand2'
                  ).pack(side='left', padx=(4, 0))

        def _ok():
            n = fname_var.get().strip()
            if not n:
                messagebox.showwarning("입력 오류", "층 이름을 입력하세요", parent=dlg)
                return
            self.db.add_floor(self.pid, n, path_var.get().strip())
            dlg.destroy()
            self._refresh_floors()

        fe.bind('<Return>', lambda ev: _ok())
        tk.Button(dlg, text="추가", command=_ok,
                  font=('Malgun Gothic', 9, 'bold'), bg=ACCENT, fg=WHITE,
                  relief='flat', padx=16, pady=6, cursor='hand2'
                  ).pack(pady=(12, 0))

    # ── 층 삭제 ─────────────────────────────────────────────
    def _del_floor(self):
        sel = self.floor_tree.selection()
        if not sel:
            return
        fid   = int(sel[0])
        fname = next((f[1] for f in self._floors if f[0] == fid), '')
        msg   = "'" + fname + "' 층을 삭제할까요?"
        if messagebox.askyesno('삭제', msg, parent=self):
            self.db.delete_floor(fid)
            self._refresh_floors()

    # ── 분석 실행 ────────────────────────────────────────────
    def _run_floor(self):
        sel = self.floor_tree.selection()
        if not sel:
            messagebox.showinfo("안내", "분석할 층을 선택하세요", parent=self)
            return
        fid   = int(sel[0])
        floor = next((f for f in self._floors if f[0] == fid), None)
        if not floor:
            return
        _, fname, fpath, _ = floor
        if not fpath or not Path(fpath).exists():
            msg = "'" + fname + "' 층의 DXF 파일을 찾을 수 없습니다.\n경로: " + str(fpath)
            messagebox.showwarning("파일 없음", msg, parent=self)
            return
        # 메인 GUI 앱에 분석 요청
        app = self._find_main_app()
        if app and hasattr(app, '_run_analysis_with_file'):
            app._run_analysis_with_file(fpath, fname, self.pid)
            self.destroy()
        else:
            # 폴백: 경로를 클립보드에 복사
            self.clipboard_clear(); self.clipboard_append(fpath)
            msg = ("'" + fname + "' DXF 경로가 클립보드에 복사되었습니다.\n"
                   "메인 화면 파일 선택란에 붙여넣기 후 분석하세요.")
            messagebox.showinfo("분석 준비", msg, parent=self)

    def _find_main_app(self):
        """위젯 트리를 거슬러 올라가 StrcadApp 인스턴스 탐색"""
        w = self.master
        while w:
            if type(w).__name__ == 'StrcadApp':
                return w
            w = getattr(w, 'master', None)
        return None

    # ── 정보 저장 ────────────────────────────────────────────
    def _save_info(self):
        info = {k: v.get() for k, v in self._info_vars.items()}
        info['memo'] = self.memo_text.get('1.0', 'end-1c')
        self.db.update_project_info(self.pid, info)
        self._title_var.set("🏗  " + (info.get('name') or ''))
        self.title("STRCAD  |  " + (info.get('name') or ''))
        messagebox.showinfo("저장", "프로젝트 정보가 저장되었습니다.", parent=self)

    def _on_close(self):
        if self.on_close:
            self.on_close()
        self.destroy()


# ════════════════════════════════════════════════════════════
#  외부 호출
# ════════════════════════════════════════════════════════════
def open_viewer(parent, beam_data, column_positions,
                project_name=None, dxf_path='', db_path='strcad_data.db',
                project_id=None, floor_name=None):
    db   = BeamDB(db_path)
    name = project_name or ("프로젝트_" + datetime.now().strftime('%Y%m%d_%H%M%S'))
    # 기존 프로젝트 ID가 있으면 재사용, 없으면 새로 생성
    if project_id:
        pid = project_id
    else:
        pid = db.create_project(name, dxf_path)
    db.save_beams(pid, beam_data, column_positions)
    title = name + (" / " + floor_name if floor_name else "")
    BeamViewer(parent, pid, title, db)
    return pid


def open_project_manager(parent, db_path='strcad_data.db'):
    ProjectManager(parent, BeamDB(db_path))


if __name__ == '__main__':
    root = tk.Tk(); root.withdraw()
    open_project_manager(root); root.mainloop()
