"""
design_2d/analyzer.py  ── Direct Stiffness Method (2D Euler-Bernoulli)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【좌표계 / 부호 규약】  ← KDS 구조역학 표준
  X  : 부재 축 방향 (좌→우)
  Y  : 아래 방향 = 양수 (화면/중력 방향)
  v  : 수직 처짐,  v > 0 = 아래 방향
  θ  : 기울기 dv/dx,  θ > 0 = 시계 방향 회전

  M  = -EI · d²v/dx²   (KDS 관례: M > 0 = 하단인장)
  V  =  EI · d³v/dx³   (V > 0 = 왼쪽 단면 위쪽 전단)

【등분포하중 처리】
  요소를 n_div 개 서브요소로 세분화하여 중간 절점에
  집중하중 P = w·Δx 로 등가 배분 → 경계절점 하중 오류 완전 방지

【단위】
  길이: mm / 힘: N (내부) ← 입력 kN 변환 / 탄성계수: MPa
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import numpy as np


# ── 요소 강성행렬 (6×6 Euler-Bernoulli) ────────────────────────────
def _beam_k(E, A, I, L):
    """
    자유도 순서: [ux_i, uy_i, θ_i,  ux_j, uy_j, θ_j]

    축력 항 EA/L:
      k[0,0]=EA/L, k[0,3]=k[3,0]=-EA/L, k[3,3]=EA/L

    휨 항 (c1=12EI/L³, c2=6EI/L², c3=4EI/L, c4=2EI/L):
      대칭 행렬, 횡방향·회전 결합
    """
    EA = E * A / L
    EI = E * I
    k  = np.zeros((6, 6))

    # 축력
    k[0,0]=EA;  k[0,3]=-EA
    k[3,0]=-EA; k[3,3]=EA

    # 휨
    c1=12*EI/L**3; c2=6*EI/L**2; c3=4*EI/L; c4=2*EI/L
    k[1,1]= c1; k[1,2]= c2; k[1,4]=-c1; k[1,5]= c2
    k[2,1]= c2; k[2,2]= c3; k[2,4]=-c2; k[2,5]= c4
    k[4,1]=-c1; k[4,2]=-c2; k[4,4]= c1; k[4,5]=-c2
    k[5,1]= c2; k[5,2]= c4; k[5,4]=-c2; k[5,5]= c3
    return k


class BeamAnalyzer:
    """
    Parameters
    ----------
    nodes    : [(id, x_mm), ...]
    elems    : [(id, ni, nj, E_MPa, I_mm4, A_mm2), ...]
    supports : {node_id: 'fix'|'pin'|'semi' 또는 {'type':..,'ratio':..}}
    loads    : [('point', node_id, Fy_N, Mz_Nmm), ...]
             | [('dist',  elem_id, w_kNpm), ...]
    n_div    : 등분포하중 요소 세분화 수 (기본 20)
    """

    N_DIV = 50   # 등분포하중 자동 세분화 개수 (많을수록 V 정확도 향상)

    def __init__(self, nodes, elems, supports, loads):
        self.nodes    = nodes
        self.elems    = elems
        self.supports = supports
        self.loads    = loads

    # ── 전처리: 등분포하중 요소 세분화 ─────────────────────────────
    def _preprocess(self):
        """
        등분포하중(dist)이 있는 요소를 N_DIV 개의 서브요소로 분할.
        각 내부 절점에 집중하중 w·dx 를 배분.

        반환: (all_nodes, all_elems, point_loads)
              모두 집중하중으로만 구성된 내부 모델
        """
        node_x  = {n[0]: float(n[1]) for n in self.nodes}
        dist_map = {item[1]: item[2]
                    for item in self.loads if item[0] == 'dist'}

        all_nodes = list(self.nodes)       # [(id, x), ...]
        all_elems = list(self.elems)       # [(id,ni,nj,E,I,A), ...]
        pt_loads  = [item for item in self.loads if item[0] == 'point']

        max_nid = max(n[0] for n in all_nodes)
        max_eid = max(e[0] for e in all_elems)

        for eid, w_kNm in dist_map.items():
            orig = next(e for e in self.elems if e[0] == eid)
            _, ni, nj, E, I, A = orig
            xi = node_x[ni];  xj = node_x[nj]
            L  = abs(xj - xi)
            n  = self.N_DIV
            dx = L / n                  # 서브요소 길이 [mm]
            w_N = w_kNm                 # kN/m = N/mm

            # 원래 요소 제거, 서브요소 생성
            all_elems = [e for e in all_elems if e[0] != eid]
            sub_nids  = [ni]

            for k in range(1, n):
                max_nid += 1
                all_nodes.append((max_nid, xi + k * dx))
                sub_nids.append(max_nid)
            sub_nids.append(nj)

            for k in range(n):
                max_eid += 1
                all_elems.append(
                    (max_eid, sub_nids[k], sub_nids[k+1], E, I, A))

            # 등분포하중 → 집중하중 배분
            # 내부 절점: w·dx  /  양단 절점: w·dx/2
            for k, nid_k in enumerate(sub_nids):
                Fy = w_N * dx / 2 if (k == 0 or k == n) else w_N * dx
                pt_loads.append(('point', nid_k, Fy, 0.0))

        return all_nodes, all_elems, pt_loads

    # ── DOF 인덱스 ─────────────────────────────────────────────────
    @staticmethod
    def _dof(nid, node_ids):
        idx = node_ids.index(nid)
        return idx*3, idx*3+1, idx*3+2

    # ── 주 해석 ─────────────────────────────────────────────────────
    def solve(self):
        """
        [K]{U} = {F} 풀기

        1) 등분포하중 세분화 (preprocess)
        2) 전체 강성행렬 K 조립
        3) 집중하중 F 조립
        4) 경계조건 적용 (구속 DOF 제거법)
           - uy, θ 구속 (fix), uy 구속 (pin/roller)
           - ux 안정화: 가장 왼쪽 지지 절점의 ux 1개만 구속
        5) 조건수 검사 → solve
        6) M = -EI·d²v/dx²,  V = EI·d³v/dx³  계산
        7) 원래 요소 단위로 결과 재집계

        Returns
        -------
        dict {elem_id: {'x','M','V','D','L','ni','nj'}} 또는 None
        """
        all_nodes, all_elems, pt_loads = self._preprocess()

        node_ids = [n[0] for n in all_nodes]
        node_x   = {n[0]: float(n[1]) for n in all_nodes}
        ndof     = len(all_nodes) * 3

        def dof(nid):
            return self._dof(nid, node_ids)

        # ── ① 전체 강성행렬 조립 ───────────────────────────────
        K = np.zeros((ndof, ndof))
        for eid, ni, nj, E, I, A in all_elems:
            L = abs(node_x[nj] - node_x[ni])
            if L < 1e-9: continue
            ke = _beam_k(E, A, I, L)
            ds = list(dof(ni)) + list(dof(nj))
            for a in range(6):
                for b in range(6):
                    K[ds[a], ds[b]] += ke[a, b]

        # ── ② 하중 벡터 조립 (집중하중만) ─────────────────────
        F = np.zeros(ndof)
        for item in pt_loads:
            _, nid, Fy_N, Mz_Nmm = item
            if nid not in node_x: continue
            d = dof(nid)
            F[d[1]] += float(Fy_N)
            F[d[2]] += float(Mz_Nmm)

        # ── ③ 경계조건 ─────────────────────────────────────────
        fixed = set()

        for nid, sval in self.supports.items():
            stype = sval["type"] if isinstance(sval, dict) else sval
            ratio = sval.get("ratio", 0.5) if isinstance(sval, dict) else 0.5
            d = dof(nid)

            if stype == 'fix':
                # 완전 고정: uy + θ 구속 (ux는 별도 처리)
                fixed.update([d[1], d[2]])

            elif stype == 'pin':
                # 핀/롤러: uy만 구속
                fixed.add(d[1])

            elif stype == 'semi':
                fixed.add(d[1])
                # 회전 스프링 강성
                k_ref = 0.0
                for _, ni_, nj_, E_, I_, _ in all_elems:
                    if ni_ == nid or nj_ == nid:
                        L_e = abs(node_x.get(nj_, 0) - node_x.get(ni_, 0))
                        if L_e > 1e-9:
                            k_ref += E_ * I_ / L_e
                k_sp = ratio * k_ref * 10.0
                if ratio >= 0.999:
                    fixed.add(d[2])
                elif ratio > 1e-4:
                    K[d[2], d[2]] += k_sp

        # ux 안정화: 지지 절점 중 가장 왼쪽 1개만 ux 구속
        # (수평 강체 이동 방지)
        sup_sorted = sorted(
            self.supports.keys(), key=lambda n: node_x.get(n, 0))
        if sup_sorted:
            fixed.add(dof(sup_sorted[0])[0])

        free = [i for i in range(ndof) if i not in fixed]
        if not free:
            return None

        # ── ④ 수치 안정성 검사 ─────────────────────────────────
        Kff = K[np.ix_(free, free)]
        Ff  = F[free]

        try:
            # 대각 정규화 후 조건수 계산 (스케일 독립)
            sc = np.sqrt(np.abs(np.diag(Kff)))
            sc[sc < 1e-30] = 1.0
            Kn = Kff / sc[:, None] / sc[None, :]
            if np.linalg.cond(Kn) > 1e12:
                return None   # 불안정 구조 (지지 부족)
        except Exception:
            return None

        # ── ⑤ 연립방정식 풀기 ─────────────────────────────────
        try:
            Uf = np.linalg.solve(Kff, Ff)
        except np.linalg.LinAlgError:
            return None

        U = np.zeros(ndof)
        for i, d_idx in enumerate(free):
            U[d_idx] = Uf[i]

        # ── ⑥ 요소별 M / V / δ 계산 ──────────────────────────
        # 서브요소별 결과를 원래 요소 단위로 재집계
        orig_node_x = {n[0]: float(n[1]) for n in self.nodes}
        results = {}

        for orig_eid, orig_ni, orig_nj, E, I, A in self.elems:
            x_start = orig_node_x[orig_ni]
            x_end   = orig_node_x[orig_nj]
            L_orig  = abs(x_end - x_start)
            if L_orig < 1e-9: continue

            # 이 원래 요소 범위 안의 세분화 절점을 x 순으로 정렬
            seg = sorted(
                [(node_x[n[0]], n[0]) for n in all_nodes
                 if x_start - 1e-6 <= node_x[n[0]] <= x_end + 1e-6],
                key=lambda v: v[0])

            xs_all, M_all, V_all, D_all = [], [], [], []

            for k in range(len(seg) - 1):
                x_a, nid_a = seg[k]
                x_b, nid_b = seg[k+1]
                L_sub = x_b - x_a
                if L_sub < 1e-9: continue

                da = list(dof(nid_a))
                db = list(dof(nid_b))
                u  = np.array([U[da[0]], U[da[1]], U[da[2]],
                               U[db[0]], U[db[1]], U[db[2]]])

                # 서브요소를 여러 점으로 세분화하여 분포 계산
                n_pts = max(3, 60 // max(len(seg)-1, 1))
                for m in range(n_pts + 1):
                    t   = m / n_pts
                    x_g = (x_a - x_start) + t * L_sub  # 원래 요소 기준 위치

                    # Hermite 형상함수
                    N1 = 1 - 3*t**2 + 2*t**3
                    N2 = L_sub * (t - 2*t**2 + t**3)
                    N3 = 3*t**2 - 2*t**3
                    N4 = L_sub * (-t**2 + t**3)
                    v  = N1*u[1] + N2*u[2] + N3*u[4] + N4*u[5]  # 처짐 [mm]

                    # 2차 도함수 d²v/dx²
                    d2N1 = (-6 + 12*t) / L_sub**2
                    d2N2 = (-4 +  6*t) / L_sub
                    d2N3 = ( 6 - 12*t) / L_sub**2
                    d2N4 = (-2 +  6*t) / L_sub
                    curv = (d2N1*u[1] + d2N2*u[2]
                            + d2N3*u[4] + d2N4*u[5])

                    # M = -EI·κ  (KDS 관례: 하단인장 = 양의 모멘트)
                    M_val = -E * I * curv / 1e6   # [kN·m]

                    # 3차 도함수 d³v/dx³
                    d3N1 =  12 / L_sub**3
                    d3N2 =   6 / L_sub**2
                    d3N3 = -12 / L_sub**3
                    d3N4 =   6 / L_sub**2
                    # V = -EI · d³v/dx³  (KDS 전단력 부호: 좌단 반력 위쪽 = 양수)
                    V_val = -E * I * (d3N1*u[1] + d3N2*u[2]
                                      + d3N3*u[4] + d3N4*u[5]) / 1e3  # [kN]

                    # 중복 x 제거
                    if not xs_all or abs(x_g - xs_all[-1]) > 1e-6:
                        xs_all.append(x_g)
                        M_all.append(M_val)
                        V_all.append(V_val)
                        D_all.append(v)

            if xs_all:
                results[orig_eid] = {
                    'x':  xs_all,
                    'M':  M_all,
                    'V':  V_all,
                    'D':  D_all,
                    'L':  L_orig,
                    'ni': orig_ni,
                    'nj': orig_nj,
                }

        # ── ⑦ 지점 반력 계산: R = K·U - F (구속 DOF의 내력) ──────
        R_full = K @ U - F          # 전체 반력 벡터 (자유 DOF는 ≈0)
        reactions = {}              # {node_id: {'Rx':, 'Ry':, 'Mz':}}

        for nid in self.supports:
            # 원본 node_ids (세분화 전) 기준 DOF
            if nid not in node_ids:
                continue
            d = dof(nid)
            # N → kN, N·mm → kN·m
            reactions[nid] = {
                "Rx": -R_full[d[0]] / 1e3,   # 수평 반력 [kN]
                "Ry": -R_full[d[1]] / 1e3,   # 수직 반력 [kN] (양수=위쪽)
                "Mz": -R_full[d[2]] / 1e6,   # 모멘트 반력 [kN·m]
            }

        return {"elems": results, "reactions": reactions}
