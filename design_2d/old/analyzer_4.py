"""
design_2d/analyzer.py
구조 해석 엔진 — Direct Stiffness Method (2D Euler-Bernoulli beam)

단위 체계:
  길이: mm
  힘:   N   (내부)  ← 입력은 kN, 변환 후 사용
  모멘트: N·mm     ← 입력은 kN·m, 변환 후 사용
"""

import numpy as np


class BeamAnalyzer:
    """
    Parameters
    ----------
    nodes    : [(id, x_mm), ...]
    elems    : [(id, ni, nj, E_MPa, I_mm4, A_mm2), ...]
    supports : {node_id: 'fix' | 'pin' | 'semi'}
    loads    : [('point', node_id, Fy_N, Mz_Nmm), ...]
             | [('dist',  elem_id, w_kNpm), ...]   w: kN/m
    """

    def __init__(self, nodes, elems, supports, loads):
        # id → x_mm 딕셔너리
        self.node_x   = {n[0]: float(n[1]) for n in nodes}
        self.node_ids = [n[0] for n in nodes]
        self.elems    = elems
        self.supports = supports
        self.loads    = loads
        self.n_nodes  = len(nodes)

    # ── DOF 인덱싱 (ux, uy, rot) ────────────────────────────
    def _dof(self, nid):
        idx = self.node_ids.index(nid)
        return idx * 3, idx * 3 + 1, idx * 3 + 2

    # ── 6×6 보 요소 강성행렬 ─────────────────────────────────
    @staticmethod
    def _beam_k(E, A, I, L):
        EA = E * A / L
        EI = E * I
        k  = np.zeros((6, 6))
        k[0, 0] =  EA;   k[0, 3] = -EA
        k[3, 0] = -EA;   k[3, 3] =  EA
        c1 = 12*EI/L**3; c2 = 6*EI/L**2
        c3 =  4*EI/L;    c4 = 2*EI/L
        k[1,1]= c1; k[1,2]= c2; k[1,4]=-c1; k[1,5]= c2
        k[2,1]= c2; k[2,2]= c3; k[2,4]=-c2; k[2,5]= c4
        k[4,1]=-c1; k[4,2]=-c2; k[4,4]= c1; k[4,5]=-c2
        k[5,1]= c2; k[5,2]= c4; k[5,4]=-c2; k[5,5]= c3
        return k

    # ── 주 해석 ──────────────────────────────────────────────
    def solve(self):
        ndof = self.n_nodes * 3
        K = np.zeros((ndof, ndof))
        F = np.zeros(ndof)

        # ── 전체 강성 조립 ────────────────────────────────────
        for eid, ni, nj, E, I, A in self.elems:
            xi = self.node_x[ni]
            xj = self.node_x[nj]
            L  = abs(xj - xi)
            if L < 1e-9:
                continue
            ke   = self._beam_k(E, A, I, L)
            dofs = list(self._dof(ni)) + list(self._dof(nj))
            for a in range(6):
                for b in range(6):
                    K[dofs[a], dofs[b]] += ke[a, b]

        # ── 하중 조립 ─────────────────────────────────────────
        for item in self.loads:
            ltype = item[0]

            if ltype == 'dist':
                # item = ('dist', elem_id, w_kNpm)
                _, eid, w_kNpm = item
                elem = next((e for e in self.elems if e[0] == eid), None)
                if elem is None:
                    continue
                ni, nj = elem[1], elem[2]
                xi = self.node_x[ni]
                xj = self.node_x[nj]
                L  = abs(xj - xi)        # mm
                if L < 1e-9:
                    continue

                # w_kNpm [kN/m] → w_Npmm [N/mm]
                w_Npmm = w_kNpm * 1000.0 / 1000.0   # kN/m = N/mm

                # 등분포 고정단 반력 (등가 절점력)
                # Fy_eq = w·L/2 [N],  Mz_eq = w·L²/12 [N·mm]
                Fy_eq  = w_Npmm * L / 2.0
                Mz_eq  = w_Npmm * L * L / 12.0

                d = list(self._dof(ni)) + list(self._dof(nj))
                # [0,Fy,+Mz, 0,Fy,-Mz]
                F[d[1]] += Fy_eq
                F[d[2]] += Mz_eq
                F[d[4]] += Fy_eq
                F[d[5]] -= Mz_eq

            elif ltype == 'point':
                # item = ('point', node_id, Fy_N, Mz_Nmm)
                _, nid, Fy_N, Mz_Nmm = item
                if nid not in self.node_x:
                    continue
                d = self._dof(nid)
                F[d[1]] += float(Fy_N)
                F[d[2]] += float(Mz_Nmm)

        # ── 경계 조건 ─────────────────────────────────────────
        fixed = set()
        for nid, stype in self.supports.items():
            d = self._dof(nid)
            if stype == 'fix':
                fixed.update([d[0], d[1], d[2]])
            elif stype == 'pin':
                fixed.update([d[0], d[1]])
            elif stype == 'semi':
                fixed.update([d[0], d[1], d[2]])

        free = [i for i in range(ndof) if i not in fixed]
        if not free:
            return None

        Kff = K[np.ix_(free, free)]
        Ff  = F[free]

        # 특이행렬 검사
        cond = np.linalg.cond(Kff)
        if cond > 1e14:
            return None

        try:
            Uf = np.linalg.solve(Kff, Ff)
        except np.linalg.LinAlgError:
            return None

        U = np.zeros(ndof)
        for i, dof in enumerate(free):
            U[dof] = Uf[i]

        # ── 요소별 결과 ───────────────────────────────────────
        results = {}
        for eid, ni, nj, E, I, A in self.elems:
            xi = self.node_x[ni]
            xj = self.node_x[nj]
            L  = abs(xj - xi)
            if L < 1e-9:
                continue

            di = list(self._dof(ni))
            dj = list(self._dof(nj))
            u  = np.array([
                U[di[0]], U[di[1]], U[di[2]],
                U[dj[0]], U[dj[1]], U[dj[2]]
            ])

            n_pts = 60
            xs_list, mom, shear, defl = [], [], [], []

            for k in range(n_pts + 1):
                t = k / n_pts
                x = t * L

                # Hermite 형상함수
                N1 =  1 - 3*t**2 + 2*t**3
                N2 =  L * (t - 2*t**2 + t**3)
                N3 =  3*t**2 - 2*t**3
                N4 =  L * (-t**2 + t**3)
                v  = N1*u[1] + N2*u[2] + N3*u[4] + N4*u[5]   # mm

                # 2차 도함수 → 모멘트 [N·mm]
                d2N1 = (-6 + 12*t) / L**2
                d2N2 = (-4 + 6*t)  / L
                d2N3 = ( 6 - 12*t) / L**2
                d2N4 = (-2 + 6*t)  / L
                M_Nmm = E * I * (d2N1*u[1] + d2N2*u[2]
                                 + d2N3*u[4] + d2N4*u[5])

                # 3차 도함수 → 전단 [N]
                d3N1 =  12 / L**3
                d3N2 =   6 / L**2
                d3N3 = -12 / L**3
                d3N4 =   6 / L**2
                V_N  = E * I * (d3N1*u[1] + d3N2*u[2]
                                + d3N3*u[4] + d3N4*u[5])

                xs_list.append(x)
                mom.append(M_Nmm / 1e6)   # N·mm → kN·m
                shear.append(V_N  / 1e3)  # N    → kN
                defl.append(v)            # mm

            results[eid] = {
                'x': xs_list,
                'M': mom,
                'V': shear,
                'D': defl,
                'L': L,
                'ni': ni,
                'nj': nj
            }

        return results
