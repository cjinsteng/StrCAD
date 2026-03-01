"""
STRCAD 부재 뷰어 - tkinter 캔버스 기반
- BEAM / GIRDER 색상 구분 (주황 / 하늘)
- 부재 클릭 → 정보 수정 → SQLite 저장
- 탭1: 부재 목록 (타입 필터)
- 탭2: 이름 목록표 (같은 이름 묶어 보기)
- 탭3: 부재 수정
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import math
from pathlib import Path
from datetime import datetime

BG=     "#0d1117"; BG2="#161b22"; BG3="#21262d"
ACCENT= "#238636"; BLUE="#1f6feb"; RED="#da3633"
TEXT=   "#c9d1d9"; TEXT2="#8b949e"; BORDER="#30363d"
WHITE=  "#f0f6fc"; TEAL="#39d353"

MEMBER_COLOR = {'GIRDER':'#FF6B35', 'BEAM':'#4FC3F7'}
MEMBER_LABEL = {'GIRDER':'거더 (GIRDER)', 'BEAM':'보 (BEAM)'}


# ════════════════ DB ════════════════════════════════════════
class BeamDB:
    def __init__(self, db_path="strcad_data.db"):
        self.db_path = db_path; self._init_db()

    def _init_db(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS projects(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, dxf_path TEXT, created TEXT, updated TEXT)""")
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

    def _conn(self): return sqlite3.connect(self.db_path)

    def create_project(self, name, dxf_path=""):
        now=datetime.now().isoformat()
        with self._conn() as c:
            return c.execute(
                "INSERT INTO projects(name,dxf_path,created,updated) VALUES(?,?,?,?)",
                (name,dxf_path,now,now)).lastrowid

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
        ok=['beam_name','span_length','beam_width','memo','member_type']
        sets=", ".join(f"{k}=?" for k in fields if k in ok)
        vals=[v for k,v in fields.items() if k in ok]
        if not sets: return
        with self._conn() as c:
            c.execute(f"UPDATE beams SET {sets},updated=?,modified=1 WHERE id=?",vals+[now,db_id])


# ════════════════ 뷰어 ══════════════════════════════════════
class BeamViewer(tk.Toplevel):
    def __init__(self, parent, pid, pname, db):
        super().__init__(parent)
        self.title(f"STRCAD 뷰어  |  {pname}")
        self.geometry("1320x800"); self.minsize(1000,600); self.configure(bg=BG)
        self.pid=pid; self.pname=pname; self.db=db
        self.beam_data,self.col_pos=db.load_beams(pid)
        self.selected=None; self.scale=1.0; self.pan=[0.0,0.0]
        self._ds=None; self._do=None
        self._type_filter=tk.StringVar(value='전체')
        self._sched_type=tk.StringVar(value='GIRDER')
        self._hl_group=None
        self._bounds=self._calc_bounds()
        self._build_ui(); self._draw()

    # ── UI ──────────────────────────────────────────────────
    def _build_ui(self):
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
        cvf=tk.Frame(main,bg=BG); cvf.pack(side='left',fill='both',expand=True)
        self.canvas=tk.Canvas(cvf,bg='#0d1117',highlightthickness=0,cursor='crosshair')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',  self._oc)
        self.canvas.bind('<B1-Motion>',       self._od)
        self.canvas.bind('<ButtonRelease-1>', self._or)
        self.canvas.bind('<MouseWheel>',      self._ow)
        self.canvas.bind('<Configure>',       lambda e:self._draw())
        self._build_side(main)

    def _build_side(self, parent):
        side=tk.Frame(parent,bg=BG2,width=310,
                      highlightbackground=BORDER,highlightthickness=1)
        side.pack(side='right',fill='y'); side.pack_propagate(False)
        nb=ttk.Notebook(side); nb.pack(fill='both',expand=True)
        s=ttk.Style(); s.theme_use('clam')
        s.configure('TNotebook',background=BG2,borderwidth=0)
        s.configure('TNotebook.Tab',background=BG3,foreground=TEXT,
                    font=('Malgun Gothic',9),padding=[10,5])
        s.map('TNotebook.Tab',background=[('selected',BLUE)],foreground=[('selected',WHITE)])

        t1=tk.Frame(nb,bg=BG2); nb.add(t1,text='📋 부재 목록')
        t2=tk.Frame(nb,bg=BG2); nb.add(t2,text='📊 이름 목록표')
        t3=tk.Frame(nb,bg=BG2); nb.add(t3,text='✏ 수정')
        self.detail_frame=t3; self.nb=nb

        self._build_list_tab(t1)
        self._build_schedule_tab(t2)
        self._show_empty_detail()

    # ── 탭1 ─────────────────────────────────────────────────
    def _build_list_tab(self, p):
        tk.Label(p,text='검색',font=('Malgun Gothic',9),bg=BG2,fg=TEXT2).pack(anchor='w',padx=12,pady=(10,2))
        self.sv=tk.StringVar(); self.sv.trace('w',lambda*a:self._rl())
        tk.Entry(p,textvariable=self.sv,font=('Consolas',10),bg=BG3,fg=TEXT,
                 insertbackground=WHITE,relief='flat',
                 highlightbackground=BORDER,highlightthickness=1
                 ).pack(fill='x',padx=12,ipady=6,pady=(0,6))
        f=tk.Frame(p,bg=BG2); f.pack(fill='x',padx=12,pady=(0,6))
        for lbl,val,col in [('전체','전체','#888'),
                             ('거더','GIRDER',MEMBER_COLOR['GIRDER']),
                             ('보','BEAM',MEMBER_COLOR['BEAM'])]:
            tk.Radiobutton(f,text=lbl,variable=self._type_filter,value=val,
                           command=self._rl,font=('Malgun Gothic',9),
                           bg=BG2,fg=col,selectcolor=BG3,activebackground=BG2,
                           relief='flat',indicatoron=False,padx=8,pady=3
                           ).pack(side='left',padx=2)
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)
        lf=tk.Frame(p,bg=BG2); lf.pack(fill='both',expand=True,padx=12,pady=6)
        sc=tk.Scrollbar(lf,bg=BG3); sc.pack(side='right',fill='y')
        self.lb=tk.Listbox(lf,bg=BG3,fg=TEXT,font=('Consolas',9),relief='flat',
                           selectbackground=BLUE,selectforeground=WHITE,
                           yscrollcommand=sc.set,activestyle='none',borderwidth=0)
        self.lb.pack(fill='both',expand=True)
        sc.config(command=self.lb.yview)
        self.lb.bind('<<ListboxSelect>>',self._ols)
        self._rl()

    # ── 탭2: 이름 목록표 ─────────────────────────────────────
    def _build_schedule_tab(self, p):
        ctrl=tk.Frame(p,bg=BG2); ctrl.pack(fill='x',padx=12,pady=(10,6))
        tk.Label(ctrl,text='부재 종류:',font=('Malgun Gothic',9),bg=BG2,fg=TEXT2).pack(side='left',padx=(0,8))
        for lbl,val,col in [('거더','GIRDER',MEMBER_COLOR['GIRDER']),
                             ('보','BEAM',MEMBER_COLOR['BEAM'])]:
            tk.Radiobutton(ctrl,text=lbl,variable=self._sched_type,value=val,
                           command=self._rs,font=('Malgun Gothic',9,'bold'),
                           bg=BG2,fg=col,selectcolor=BG3,activebackground=BG2,
                           relief='flat',indicatoron=False,padx=10,pady=4
                           ).pack(side='left',padx=3)
        tk.Frame(p,bg=BORDER,height=1).pack(fill='x',padx=12)

        # 요약 라벨
        self.sched_summary=tk.StringVar(value='')
        tk.Label(p,textvariable=self.sched_summary,font=('Malgun Gothic',8),
                 bg=BG2,fg=TEAL,anchor='w').pack(fill='x',padx=14,pady=(4,2))

        # 이름별 트리뷰
        tf=tk.Frame(p,bg=BG2); tf.pack(fill='both',expand=True,padx=8,pady=4)
        sc=ttk.Scrollbar(tf); sc.pack(side='right',fill='y')
        s=ttk.Style()
        s.configure('S.Treeview',background=BG3,foreground=TEXT,
                    fieldbackground=BG3,rowheight=26,font=('Malgun Gothic',9))
        s.configure('S.Treeview.Heading',background=BG2,foreground=WHITE,
                    font=('Malgun Gothic',9,'bold'))
        s.map('S.Treeview',background=[('selected',BLUE)])
        cols=('이름','개수','평균스팬','평균폭')
        self.st=ttk.Treeview(tf,columns=cols,show='headings',
                             style='S.Treeview',yscrollcommand=sc.set)
        sc.config(command=self.st.yview)
        for c,w in zip(cols,[70,50,80,70]):
            self.st.heading(c,text=c); self.st.column(c,width=w,anchor='center')
        self.st.pack(fill='both',expand=True)
        self.st.bind('<<TreeviewSelect>>',self._ost)

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
        self._rs()

    def _rs(self):
        """이름 목록표 갱신"""
        self.st.delete(*self.st.get_children())
        mt=self._sched_type.get()
        from collections import defaultdict
        groups=defaultdict(list)
        for b in self.beam_data:
            if b['member_type']==mt:
                groups[b['beam_raw_name']].append(b)
        total=sum(len(v) for v in groups.values())
        self.sched_summary.set(f"  총 {total}개 / {len(groups)}종")
        col=MEMBER_COLOR.get(mt,'#aaa')
        for name in sorted(groups.keys()):
            ms=groups[name]
            sp=[m['span_length'] for m in ms]
            ws=[m['beam_width']  for m in ms if m.get('beam_width',0)>0]
            avg=f"{sum(sp)/len(sp)/1000:.2f}m"
            aw=f"{sum(ws)/len(ws):.0f}" if ws else '-'
            self.st.insert('','end',iid=name,values=(name,len(ms),avg,aw))

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
                self.dt.insert('','end',iid=str(b['db_id']),
                               values=(b['beam_name'],sp,wd,b['beam_direction']))
        self._hl_group=name; self._draw()

    def _odt(self, e):
        sel=self.dt.selection()
        if not sel: return
        db_id=int(sel[0])
        b=next((x for x in self.beam_data if x.get('db_id')==db_id),None)
        if b: self.selected=b; self._draw(); self._show_detail(b); self.nb.select(2)

    # ── 탭3: 수정 ────────────────────────────────────────────
    def _show_empty_detail(self):
        for w in self.detail_frame.winfo_children(): w.destroy()
        tk.Label(self.detail_frame,text="부재를 클릭하거나\n목록에서 선택하세요",
                 font=('Malgun Gothic',9),bg=BG2,fg=TEXT2,justify='center').pack(pady=40)

    def _show_detail(self, b):
        for w in self.detail_frame.winfo_children(): w.destroy()
        mt=b['member_type']; col=MEMBER_COLOR.get(mt,'#aaa'); lbl=MEMBER_LABEL.get(mt,mt)
        tk.Label(self.detail_frame,text=f"  {lbl}  ",font=('Malgun Gothic',10,'bold'),
                 bg=col,fg=WHITE).pack(anchor='w',padx=12,pady=(12,8))
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
                e=tk.Entry(row,textvariable=var,font=('Consolas',9),bg=BG3,fg=WHITE,
                           insertbackground=WHITE,relief='flat',
                           highlightbackground=col,highlightthickness=1)
                e.pack(side='left',fill='x',expand=True,ipady=3)
                if unit: tk.Label(row,text=unit,font=('Malgun Gothic',8),
                                  bg=BG2,fg=TEXT2).pack(side='left',padx=2)
            else:
                tk.Label(row,textvariable=var,font=('Consolas',9),bg=BG2,
                         fg=col if key=='beam_direction' else TEXT).pack(side='left')
        tk.Label(self.detail_frame,text='메모',font=('Malgun Gothic',8),
                 bg=BG2,fg=TEXT2,anchor='w').pack(fill='x',padx=12,pady=(8,2))
        memo=tk.Text(self.detail_frame,height=3,font=('Malgun Gothic',9),bg=BG3,fg=TEXT,
                     insertbackground=WHITE,relief='flat',
                     highlightbackground=BORDER,highlightthickness=1)
        memo.insert('1.0',b.get('memo','')); memo.pack(fill='x',padx=12)

        def _save():
            upd={}
            for k in ('beam_name','span_length','beam_width'):
                if k in self.ev:
                    v=self.ev[k].get().strip()
                    upd[k]=float(v) if k in ('span_length','beam_width') else v
            upd['memo']=memo.get('1.0','end-1c')
            b.update(upd); b['modified']=1
            if b.get('db_id'): self.db.update_beam(b['db_id'],upd)
            self._rl(); self._rs(); self._draw()
            messagebox.showinfo('저장',f"'{b['beam_name']}' 저장 완료!",parent=self)

        tk.Button(self.detail_frame,text='💾  이 부재 저장',command=_save,
                  font=('Malgun Gothic',9,'bold'),bg=ACCENT,fg=WHITE,
                  relief='flat',cursor='hand2',pady=5).pack(fill='x',padx=12,pady=(10,4))

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

    # ── 캔버스 ───────────────────────────────────────────────
    def _calc_bounds(self):
        pts=([b['start_point'] for b in self.beam_data]+
             [b['end_point']   for b in self.beam_data]+list(self.col_pos))
        if not pts: return {'xmin':0,'xmax':1000,'ymin':0,'ymax':1000}
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        pad=max((max(xs)-min(xs))*0.06,(max(ys)-min(ys))*0.06,500)
        return {'xmin':min(xs)-pad,'xmax':max(xs)+pad,'ymin':min(ys)-pad,'ymax':max(ys)+pad}

    def _ts(self,wx,wy):
        W=self.canvas.winfo_width() or 800; H=self.canvas.winfo_height() or 600
        bw=self._bounds['xmax']-self._bounds['xmin']
        bh=self._bounds['ymax']-self._bounds['ymin']
        base=min(W/bw,H/bh)*self.scale
        ox=(W-bw*base)/2+self.pan[0]; oy=(H-bh*base)/2+self.pan[1]
        return (ox+(wx-self._bounds['xmin'])*base, oy+(self._bounds['ymax']-wy)*base)

    def _draw(self):
        self.canvas.delete('all')
        W=self.canvas.winfo_width() or 800; H=self.canvas.winfo_height() or 600
        bw=self._bounds['xmax']-self._bounds['xmin']
        bh=self._bounds['ymax']-self._bounds['ymin']
        base=min(W/bw,H/bh)*self.scale
        csz=max(5,int(250*base))

        for cp in self.col_pos:
            sx,sy=self._ts(*cp); hs=csz//2
            self.canvas.create_rectangle(sx-hs,sy-hs,sx+hs,sy+hs,
                                         fill='#1b3a1b',outline='#4CAF50',width=1)

        for b in self.beam_data:
            sx1,sy1=self._ts(*b['start_point']); sx2,sy2=self._ts(*b['end_point'])
            mt=b['member_type']; col=MEMBER_COLOR.get(mt,'#aaa')
            isSel=self.selected and self.selected.get('db_id')==b.get('db_id')
            isHL=self._hl_group and b['beam_raw_name']==self._hl_group
            lw=6 if isSel else (4 if isHL else 2)
            dc='#4ecca3' if isSel else ('#FFD700' if isHL else col)

            if b.get('beam_width',0)>0:
                dx=sx2-sx1; dy=sy2-sy1; ln=math.hypot(dx,dy) or 1
                hw=b['beam_width']*base/2; nx,ny=-dy/ln,dx/ln
                self.canvas.create_polygon(
                    sx1+nx*hw,sy1+ny*hw,sx2+nx*hw,sy2+ny*hw,
                    sx2-nx*hw,sy2-ny*hw,sx1-nx*hw,sy1-ny*hw,
                    fill=col,stipple='gray25',outline='')

            self.canvas.create_line(sx1,sy1,sx2,sy2,fill=dc,width=lw,
                                    capstyle='round',dash=(4,3) if b.get('modified') else None)

            if math.hypot(sx2-sx1,sy2-sy1)>35:
                mx,my=(sx1+sx2)/2,(sy1+sy2)/2
                name=b.get('beam_name') or b['beam_id']
                self.canvas.create_text(mx,my-6,
                    text=f"{name}  {b['span_length']/1000:.2f}m",
                    fill=dc,font=('Consolas',8 if not isSel else 9),anchor='center')

        # 범례
        items=[('거더 (G)',MEMBER_COLOR['GIRDER']),
               ('보 (B)',  MEMBER_COLOR['BEAM']),
               ('기둥',    '#4CAF50')]
        lx,ly=14,14
        for t,c in items:
            self.canvas.create_rectangle(lx,ly,lx+18,ly+10,fill=c,outline='')
            self.canvas.create_text(lx+24,ly+5,text=t,fill=TEXT,
                                    font=('Malgun Gothic',8),anchor='w')
            ly+=18
        gc=sum(1 for b in self.beam_data if b['member_type']=='GIRDER')
        bc=sum(1 for b in self.beam_data if b['member_type']=='BEAM')
        mod=sum(1 for b in self.beam_data if b.get('modified'))
        self.canvas.create_text(W-10,H-10,
            text=f"거더 {gc}  보 {bc}  수정 {mod}",
            fill=TEXT2,font=('Malgun Gothic',8),anchor='se')

    # ── 마우스 ───────────────────────────────────────────────
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
            self._show_detail(best); self.nb.select(2)
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
        self._show_detail(b); self.nb.select(2)

    def _save_all(self):
        gc=sum(1 for b in self.beam_data if b['member_type']=='GIRDER')
        bc=sum(1 for b in self.beam_data if b['member_type']=='BEAM')
        mod=sum(1 for b in self.beam_data if b.get('modified'))
        messagebox.showinfo('저장 완료',
            f"거더 {gc}개 / 보 {bc}개\n수정 {mod}개 저장 완료",parent=self)

    @staticmethod
    def _psd(px,py,x1,y1,x2,y2):
        dx,dy=x2-x1,y2-y1; l2=dx*dx+dy*dy
        if l2==0: return math.hypot(px-x1,py-y1)
        t=max(0,min(1,((px-x1)*dx+(py-y1)*dy)/l2))
        return math.hypot(px-(x1+t*dx),py-(y1+t*dy))


# ════════════════ 프로젝트 매니저 ════════════════════════════
class ProjectManager(tk.Toplevel):
    def __init__(self,parent,db):
        super().__init__(parent); self.title("STRCAD  |  프로젝트 관리")
        self.geometry("580x440"); self.configure(bg=BG); self.db=db
        self._build_ui(); self._refresh()

    def _build_ui(self):
        tk.Label(self,text="📂  프로젝트 목록",font=("Malgun Gothic",13,"bold"),
                 bg=BG,fg=WHITE).pack(anchor='w',padx=20,pady=(16,8))
        tk.Frame(self,bg=BORDER,height=1).pack(fill='x')
        f=tk.Frame(self,bg=BG); f.pack(fill='both',expand=True,padx=16,pady=12)
        s=ttk.Style(); s.theme_use('clam')
        s.configure('PM.Treeview',background=BG3,foreground=TEXT,
                    fieldbackground=BG3,rowheight=28,font=('Malgun Gothic',9))
        s.configure('PM.Treeview.Heading',background=BG2,foreground=WHITE,
                    font=('Malgun Gothic',9,'bold'))
        s.map('PM.Treeview',background=[('selected',BLUE)])
        cols=('이름','DXF','생성일')
        self.tree=ttk.Treeview(f,columns=cols,show='headings',style='PM.Treeview')
        sc=ttk.Scrollbar(f,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=sc.set)
        sc.pack(side='right',fill='y'); self.tree.pack(fill='both',expand=True)
        for c,w in zip(cols,[160,250,120]):
            self.tree.heading(c,text=c); self.tree.column(c,width=w)
        self.tree.bind('<Double-1>',lambda e:self._open())
        br=tk.Frame(self,bg=BG); br.pack(fill='x',padx=16,pady=(0,16))
        for txt,cmd,col in [('▶  열기',self._open,BLUE),('🗑  삭제',self._delete,RED)]:
            tk.Button(br,text=txt,command=cmd,font=('Malgun Gothic',9,'bold'),
                      bg=col,fg=WHITE,relief='flat',padx=12,pady=6,cursor='hand2'
                      ).pack(side='left',padx=4)

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._projects=self.db.list_projects()
        for pid,name,dxf,created in self._projects:
            self.tree.insert('','end',iid=str(pid),
                             values=(name,Path(dxf).name if dxf else '-',
                                     created[:10] if created else '-'))

    def _open(self):
        sel=self.tree.selection()
        if not sel: return
        pid=int(sel[0]); name=next(p[1] for p in self._projects if p[0]==pid)
        BeamViewer(self,pid,name,self.db)

    def _delete(self):
        sel=self.tree.selection()
        if not sel: return
        pid=int(sel[0]); name=next(p[1] for p in self._projects if p[0]==pid)
        if messagebox.askyesno('삭제',f"'{name}' 삭제할까요?",parent=self):
            self.db.delete_project(pid); self._refresh()


# ════════════════ 외부 호출 ══════════════════════════════════
def open_viewer(parent, beam_data, column_positions,
                project_name=None, dxf_path='', db_path='strcad_data.db'):
    db=BeamDB(db_path)
    name=project_name or f"프로젝트_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    pid=db.create_project(name,dxf_path)
    db.save_beams(pid,beam_data,column_positions)
    BeamViewer(parent,pid,name,db)
    return pid

def open_project_manager(parent, db_path='strcad_data.db'):
    ProjectManager(parent,BeamDB(db_path))

if __name__=='__main__':
    root=tk.Tk(); root.withdraw()
    open_project_manager(root); root.mainloop()
