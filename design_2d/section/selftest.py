"""
design_2d/section/selftest.py — 프레임 솔버 손계산 검증
    python -m design_2d.section.selftest
"""
import math
from . import model as fm
from .solver import solve_case, solve_all, elem_extremes, FrameError

FAILS = []

def base():
    m = fm.new_model(); m["cases"][1]["selfweight"] = 0.0
    return m
def chk(name, got, exp, tol=1e-3):
    ok = abs(got-exp) <= tol*max(1,abs(exp))
    print(("OK  " if ok else "FAIL"), name, round(float(got),5), "expected", round(float(exp),5))
    if not ok:
        FAILS.append(name)
    return ok

# 1 SS beam UDL
m = base(); a=fm.add_node(m,0,0); b=fm.add_node(m,6,0); e=fm.add_elem(m,a,b)
m["supports"]={a:2,b:3}
m["eloads"].append(dict(id=1,case=1,elem=e,kind="dist",dir="G",w1=10,w2=10,a=0,b=1,rel=True))
r=solve_case(m,1); ex=elem_extremes(r["elems"][e])
chk("SS Mmax",ex["Mmax"][0],45); chk("SS Ry",r["react"][a][1],30); chk("SS V0",r["elems"][e]["V"][0],30)
E=fm.concrete_Ec(24)*1e3; I=0.4*0.6**3/12
d=min(r["elems"][e]["dv"]); chk("SS defl", d, -5*10*6**4/(384*E*I), 5e-3)
# 2 fixed-fixed
m["supports"]={a:1,b:1}; r=solve_case(m,1); ex=elem_extremes(r["elems"][e])
chk("FF Mend",ex["Mmin"][0],-30); chk("FF Mmid",ex["Mmax"][0],15); chk("FF Mz react", r["react"][a][2], 30)
# 3 cantilever tip load
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,3,0); e=fm.add_elem(m,a,b); m["supports"]={a:1}
m["nloads"].append(dict(id=1,case=1,node=b,fx=0,fy=-10,mz=0))
r=solve_case(m,1); chk("Cant M0", r["elems"][e]["M"][0], -30); chk("Cant Mz", r["react"][a][2], 30); chk("Cant Ry", r["react"][a][1], 10)
chk("Cant tip", r["disp"][b][1], -10*27/(3*E*I))
# 5 SS point load mid
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,6,0); e=fm.add_elem(m,a,b); m["supports"]={a:2,b:3}
m["eloads"].append(dict(id=1,case=1,elem=e,kind="point",dir="G",p=20,a=0.5,rel=True))
r=solve_case(m,1); er=r["elems"][e]; ex=elem_extremes(er)
chk("SSP M",ex["Mmax"][0],30); i=er["xs"].index(3.0); print("   V jump", er["V"][i], er["V"][i+1])
# point load at a=2 of 6 (abs): Ra = 20*4/6
m["eloads"][0].update(a=2.0, rel=False); r=solve_case(m,1); chk("SSP2 Ra", r["react"][a][1], 20*4/6); chk("SSP2 M", elem_extremes(r["elems"][e])["Mmax"][0], 20*2*4/6)
# triangular partial load on fixed-fixed? use SS triangular full: w 0->10, Mmax = wL^2/(9√3)
m["eloads"]=[dict(id=1,case=1,elem=e,kind="dist",dir="G",w1=0,w2=10,a=0,b=6,rel=False)]
r=solve_case(m,1); chk("Tri Mmax", elem_extremes(r["elems"][e])["Mmax"][0], 10*36/(9*math.sqrt(3)), 2e-3); chk("Tri Ra", r["react"][a][1], 10*6/6)
# 6 portal with hinged beam ends
m=base(); n=fm.generate_frame(m,[6],[4],sec_beam=1,sec_col=1,sup=1)
beam=[k for k,v in m["elems"].items() if m["nodes"][v["ni"]]["y"]==4][0]
fm.set_end_fix(m["elems"][beam], 0, 0)
m["eloads"].append(dict(id=1,case=1,elem=beam,kind="dist",dir="G",w1=10,w2=10,a=0,b=1,rel=True))
r=solve_case(m,1); chk("Hinged beam M", elem_extremes(r["elems"][beam])["Mmax"][0], 45)
cols=[k for k in m["elems"] if k!=beam]; print("   col end M", [round(abs(r["elems"][c]["end"][2]),6) for c in cols])
# 4 portal lateral, equilibrium
m=base(); n=fm.generate_frame(m,[6],[4],sec_beam=1,sec_col=1,sup=1)
m["nloads"].append(dict(id=1,case=1,node=n[(0,1)],fx=10,fy=0,mz=0))
r=solve_case(m,1); R=r["react"]
chk("Portal ΣRx", sum(v[0] for v in R.values()), -10); chk("Portal ΣRy", sum(v[1] for v in R.values()), 0)
mom = sum(v[2] + (m["nodes"][k]["x"]*v[1] - m["nodes"][k]["y"]*v[0]) for k,v in R.items()) + (-4*10)
chk("Portal ΣM", mom, 0)
print("   base reactions", {k:tuple(round(x,3) for x in v) for k,v in R.items()})
# 7 semi-rigid
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,6,0); e=fm.add_elem(m,a,b)
m["eloads"].append(dict(id=1,case=1,elem=e,kind="dist",dir="G",w1=10,w2=10,a=0,b=1,rel=True))
m["sup_types"][5]=dict(name="s",dx=1,dy=1,rz=0,fix=0.000001,kx=0,ky=0,kr=0); m["supports"]={a:5,b:5}
r=solve_case(m,1); chk("semi 0 Mmax", elem_extremes(r["elems"][e])["Mmax"][0], 45, 1e-3)
m["sup_types"][5]["fix"]=1.0; r=solve_case(m,1); chk("semi100 Mmin", elem_extremes(r["elems"][e])["Mmin"][0], -30)
m["sup_types"][5]["fix"]=0.5; r=solve_case(m,1); chk("support r=0.5 Mend", elem_extremes(r["elems"][e])["Mmin"][0], -30*1.5/2.5)
r_sup = solve_case(m,1)
# 부재 단부 반강접 (지점은 고정) — 지점 고정률과 같은 결과여야 함
m["supports"]={a:1,b:1}; fm.set_end_fix(m["elems"][e], 0.5, 0.5); r=solve_case(m,1)
chk("member r=0.5 Mend", elem_extremes(r["elems"][e])["Mmin"][0], -30*1.5/2.5)
chk("member r=0.5 Mmid", elem_extremes(r["elems"][e])["Mmax"][0], 45-18)
chk("member r=0.5 Mz react", r["react"][a][2], 18)
for rr in (0.25, 0.8):
    fm.set_end_fix(m["elems"][e], rr, rr); r=solve_case(m,1)
    chk(f"member r={rr} Mend", elem_extremes(r["elems"][e])["Mmin"][0], -30*3*rr/(2+rr))
# 비대칭: i단 0.5 / j단 강접  ==  좌측 지점 고정률 0.5 / 우측 고정
fm.set_end_fix(m["elems"][e], 0.5, 1.0); r1=solve_case(m,1)
fm.set_end_fix(m["elems"][e], 1.0, 1.0); m["supports"]={a:5,b:1}; r2=solve_case(m,1)
chk("asym member vs support Mi", r1["elems"][e]["M"][0], r2["elems"][e]["M"][0])
chk("asym member vs support Mj", r1["elems"][e]["M"][-1], r2["elems"][e]["M"][-1])
fm.set_end_fix(m["elems"][e], 0.0, 0.0); m["supports"]={a:1,b:1}; r=solve_case(m,1)
chk("member r=0 = hinge", elem_extremes(r["elems"][e])["Mmax"][0], 45)
# 8 inclined SS gravity
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,4,3); e=fm.add_elem(m,a,b); m["supports"]={a:2,b:3}
m["eloads"].append(dict(id=1,case=1,elem=e,kind="dist",dir="G",w1=10,w2=10,a=0,b=1,rel=True))
r=solve_case(m,1); chk("Incl Mmax", elem_extremes(r["elems"][e])["Mmax"][0], 10*0.8*25/8); chk("Incl ΣRy", sum(v[1] for v in r["react"].values()), 50)
# selfweight + combos
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,6,0); e=fm.add_elem(m,a,b); m["supports"]={a:2,b:3}
m["cases"][1]["selfweight"]=1.0
m["eloads"].append(dict(id=1,case=2,elem=e,kind="dist",dir="G",w1=10,w2=10,a=0,b=1,rel=True))
allr=solve_all(m); sw=24*0.4*0.6
chk("SW M", elem_extremes(allr[("case",1)]["elems"][e])["Mmax"][0], sw*36/8)
chk("Combo M", elem_extremes(allr[("combo",2)]["elems"][e])["Mmax"][0], (1.2*sw+1.6*10)*36/8)
# unstable
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,6,0); e=fm.add_elem(m,a,b); m["supports"]={a:3,b:3}
try: solve_case(m,1); print("FAIL unstable not detected")
except FrameError as ex: print("OK   unstable detected")
# truss-like both released 
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,3,3); c=fm.add_node(m,6,0)
e1=fm.add_elem(m,a,b); e2=fm.add_elem(m,b,c)
for k in (e1,e2): fm.set_end_fix(m["elems"][k], 0, 0)
m["supports"]={a:2,c:2}; m["nloads"].append(dict(id=1,case=1,node=b,fx=0,fy=-10,mz=0))
r=solve_case(m,1); chk("Truss N", r["elems"][e1]["N"][0], -10/math.sqrt(2)); print("   auto_fixed", r["auto_fixed"])
# split elem
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,6,0); e=fm.add_elem(m,a,b); m["supports"]={a:2,b:3}
m["eloads"].append(dict(id=1,case=1,elem=e,kind="dist",dir="G",w1=10,w2=10,a=0,b=1,rel=True))
m["eloads"].append(dict(id=2,case=1,elem=e,kind="point",dir="G",p=20,a=4,rel=False))
r0=solve_case(m,1); fm.split_elem(m,e,0.5); r1=solve_case(m,1)
# json roundtrip
m2=fm.from_json(fm.to_json(m)); print("json keys int:", all(isinstance(k,int) for k in m2["nodes"]), solve_case(m2,1)["react"][a][1])

# 구버전 파일 변환 (rel_i, 지점 %)
old = fm.new_model(); a=fm.add_node(old,0,0); b=fm.add_node(old,6,0); e=fm.add_elem(old,a,b)
old["elems"][e].pop("fix_i"); old["elems"][e].pop("fix_j"); old["elems"][e]["rel_i"]=True; old["elems"][e]["rel_j"]=False
old["sup_types"][4]["fix"]=50; old.pop("rel_types")
nm = fm.from_json(fm.to_json(old))
chk("migrate fix_i", nm["elems"][e]["fix_i"], 0); chk("migrate fix_j", nm["elems"][e]["fix_j"], 1)
chk("migrate sup %", nm["sup_types"][4]["fix"], 0.5); chk("migrate rel_types", len(nm["rel_types"]), 5)
# 노드 복사
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,0,4); e=fm.add_elem(m,a,b,sec=2); m["supports"]={a:1}
nn, ne = fm.copy_nodes(m,[a,b],6,0,times=3,elems=True,extras=True)
chk("copy nodes", len(m["nodes"]), 8); chk("copy elems", len(m["elems"]), 4); chk("copy supports", len(m["supports"]), 4)
nn, ne = fm.copy_nodes(m,[b],0,3.5,times=1,elems=False,link=True)
chk("copy link elems", len(ne), 1)
chk("copy link uses column section", m["elems"][next(iter(ne))]["sec"], m["elems"][e]["sec"])
chk("parse_ids", len(fm.parse_ids("1-4, 7, 9~10")), 7); print("   ids_text", fm.ids_text([1,2,3,4,7,9,10]))
chk("move clash", 1 if fm.move_nodes(m,[a],6,0) else 0, 1)

print("\n전체 통과" if not FAILS else f"\n실패: {FAILS}")
