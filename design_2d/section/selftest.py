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
m["elems"][beam]["rel_i"]=m["elems"][beam]["rel_j"]=True
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
m["sup_types"][5]=dict(name="s",dx=1,dy=1,rz=0,fix=0.0001,kx=0,ky=0,kr=0); m["supports"]={a:5,b:5}
r=solve_case(m,1); chk("semi 0 Mmax", elem_extremes(r["elems"][e])["Mmax"][0], 45, 1e-3)
m["sup_types"][5]["fix"]=100; r=solve_case(m,1); chk("semi100 Mmin", elem_extremes(r["elems"][e])["Mmin"][0], -30)
m["sup_types"][5]["fix"]=50; r=solve_case(m,1); print("   semi50 Mend", round(elem_extremes(r["elems"][e])["Mmin"][0],3))
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
for k in (e1,e2): m["elems"][k]["rel_i"]=m["elems"][k]["rel_j"]=True
m["supports"]={a:2,c:2}; m["nloads"].append(dict(id=1,case=1,node=b,fx=0,fy=-10,mz=0))
r=solve_case(m,1); chk("Truss N", r["elems"][e1]["N"][0], -10/math.sqrt(2)); print("   auto_fixed", r["auto_fixed"])
# split elem
m=base(); a=fm.add_node(m,0,0); b=fm.add_node(m,6,0); e=fm.add_elem(m,a,b); m["supports"]={a:2,b:3}
m["eloads"].append(dict(id=1,case=1,elem=e,kind="dist",dir="G",w1=10,w2=10,a=0,b=1,rel=True))
m["eloads"].append(dict(id=2,case=1,elem=e,kind="point",dir="G",p=20,a=4,rel=False))
r0=solve_case(m,1); fm.split_elem(m,e,0.5); r1=solve_case(m,1)
# json roundtrip
m2=fm.from_json(fm.to_json(m)); print("json keys int:", all(isinstance(k,int) for k in m2["nodes"]), solve_case(m2,1)["react"][a][1])

print("\n전체 통과" if not FAILS else f"\n실패: {FAILS}")
