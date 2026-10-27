"""
design_2d/analyzer.py
─────────────────────────────────────────────────────────────────────────────
구조 해석 엔진 — Direct Stiffness Method (직접강성법)
보 이론: 2D Euler-Bernoulli Beam Element

【해석 원리】
  구조물을 유한개의 "보 요소(Beam Element)"로 분할한 뒤,
  각 절점(Node)의 변위 벡터 {U}를 미지수로 놓고
  전체 강성방정식  [K]{U} = {F} 를 풀어 변위를 구한다.
  이후 절점 변위로부터 Hermite 형상함수를 이용해
  경간 내 임의 위치의 모멘트 M(x), 전단력 V(x), 처짐 δ(x)를 계산한다.

【단위 체계】
  길이   : mm
  힘     : N   (내부 계산)  ← 입력은 kN, 변환 후 사용
  모멘트 : N·mm            ← 입력은 kN·m, 변환 후 사용
  탄성계수: MPa = N/mm²
─────────────────────────────────────────────────────────────────────────────
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
        # node id → x 좌표 딕셔너리 (빠른 조회용)
        self.node_x   = {n[0]: float(n[1]) for n in nodes}
        # 절점 id 순서 리스트 (DOF 인덱싱 기준)
        self.node_ids = [n[0] for n in nodes]
        self.elems    = elems
        self.supports = supports
        self.loads    = loads
        self.n_nodes  = len(nodes)

    # ── DOF 인덱싱 ──────────────────────────────────────────────
    def _dof(self, nid):
        """
        절점 nid 의 자유도(DOF) 인덱스 반환
        각 절점 당 3개 DOF: (ux, uy, θz)
          ux : 수평 변위  → idx*3
          uy : 수직 변위  → idx*3 + 1
          θz : 회전 변위  → idx*3 + 2
        """
        idx = self.node_ids.index(nid)
        return idx * 3, idx * 3 + 1, idx * 3 + 2

    # ── 6×6 보 요소 강성행렬 ────────────────────────────────────
    @staticmethod
    def _beam_k(E, A, I, L):
        """
        2D Euler-Bernoulli 보 요소의 6×6 국부 강성행렬 생성

        자유도 순서 (절점 i → j):
          [ux_i, uy_i, θ_i,  ux_j, uy_j, θ_j]

        축력 항 (EA/L):
          k[0,0] =  EA/L   k[0,3] = -EA/L
          k[3,0] = -EA/L   k[3,3] =  EA/L

        휨 항 계수:
          c1 = 12EI/L³  → 횡방향 전단 강성
          c2 =  6EI/L²  → 횡력↔모멘트 결합항
          c3 =  4EI/L   → 동단(same-end) 회전 강성
          c4 =  2EI/L   → 교차단(cross-end) 회전 강성
        """
        EA = E * A / L          # 축 강성 [N/mm]
        EI = E * I              # 휨 강성 [N·mm²]
        k  = np.zeros((6, 6))

        # 축력 항
        k[0, 0] =  EA;   k[0, 3] = -EA
        k[3, 0] = -EA;   k[3, 3] =  EA

        # 휨 항 계수
        c1 = 12*EI/L**3   # 횡방향 전단 강성
        c2 =  6*EI/L**2   # 전단-모멘트 결합
        c3 =  4*EI/L      # 동단 회전 강성
        c4 =  2*EI/L      # 교차단 회전 강성

        # 절점 i 수직(uy_i) 행/열
        k[1,1]= c1;  k[1,2]= c2;  k[1,4]=-c1;  k[1,5]= c2
        # 절점 i 회전(θ_i) 행/열
        k[2,1]= c2;  k[2,2]= c3;  k[2,4]=-c2;  k[2,5]= c4
        # 절점 j 수직(uy_j) 행/열
        k[4,1]=-c1;  k[4,2]=-c2;  k[4,4]= c1;  k[4,5]=-c2
        # 절점 j 회전(θ_j) 행/열
        k[5,1]= c2;  k[5,2]= c4;  k[5,4]=-c2;  k[5,5]= c3

        return k

    # ── 주 해석 ──────────────────────────────────────────────────
    def solve(self):
        """
        전체 강성방정식 [K]{U} = {F} 풀기

        흐름:
          1) 전체 강성행렬 K 조립
          2) 하중 벡터 F 조립
          3) 경계조건 적용 → 자유 DOF 추출
          4) [Kff]{Uf} = {Ff} 풀기
          5) Hermite 형상함수로 M / V / δ 분포 계산

        Returns
        -------
        dict : {elem_id: {'x','M','V','D','L','ni','nj'}}  또는 None
        """
        ndof = self.n_nodes * 3          # 전체 자유도 수
        K = np.zeros((ndof, ndof))       # 전체 강성행렬
        F = np.zeros(ndof)               # 전체 하중 벡터

        # ── ① 전체 강성행렬 조립 ──────────────────────────────
        for eid, ni, nj, E, I, A in self.elems:
            xi = self.node_x[ni]         # 시작 절점 x [mm]
            xj = self.node_x[nj]         # 끝 절점 x [mm]
            L  = abs(xj - xi)            # 요소 길이 [mm]
            if L < 1e-9:
                continue                 # 길이 0 요소 스킵

            ke   = self._beam_k(E, A, I, L)                    # 6×6 요소 강성행렬
            dofs = list(self._dof(ni)) + list(self._dof(nj))   # global DOF 6개

            # 요소 강성행렬 → 전체 강성행렬에 누적 (조립, Assembly)
            for a in range(6):
                for b in range(6):
                    K[dofs[a], dofs[b]] += ke[a, b]

        # ── ② 하중 벡터 조립 ──────────────────────────────────
        for item in self.loads:
            ltype = item[0]

            if ltype == 'dist':
                # 등분포하중 → 등가 절점력 변환 (Fixed-End Force Method)
                # item = ('dist', elem_id, w_kNpm)
                _, eid, w_kNpm = item
                elem = next((e for e in self.elems if e[0] == eid), None)
                if elem is None:
                    continue
                ni, nj = elem[1], elem[2]
                xi = self.node_x[ni]
                xj = self.node_x[nj]
                L  = abs(xj - xi)
                if L < 1e-9:
                    continue

                # kN/m → N/mm 단위 변환 (1 kN/m = 1 N/mm)
                w_Npmm = w_kNpm * 1000.0 / 1000.0

                # 양단 고정보 등가 절점력:
                #   수직 반력 Fy = w·L/2  [N]      (양단 동일)
                #   고정단 모멘트 Mz = w·L²/12 [N·mm] (부호 반대)
                Fy_eq  = w_Npmm * L / 2.0
                Mz_eq  = w_Npmm * L * L / 12.0

                d = list(self._dof(ni)) + list(self._dof(nj))
                F[d[1]] += Fy_eq    # 절점 i 수직력 (+)
                F[d[2]] += Mz_eq    # 절점 i 모멘트 (+, 반시계)
                F[d[4]] += Fy_eq    # 절점 j 수직력 (+)
                F[d[5]] -= Mz_eq    # 절점 j 모멘트 (-, 시계)

            elif ltype == 'point':
                # 집중하중 (절점 직접 작용)
                # item = ('point', node_id, Fy_N, Mz_Nmm)
                _, nid, Fy_N, Mz_Nmm = item
                if nid not in self.node_x:
                    continue
                d = self._dof(nid)
                F[d[1]] += float(Fy_N)    # 수직력 [N]
                F[d[2]] += float(Mz_Nmm)  # 모멘트 [N·mm]

        # ── ③ 경계조건 적용 ───────────────────────────────────
        # 지지 조건별 구속 DOF:
        #   fix  → ux, uy, θ 모두 구속 (완전 고정단)
        #   pin  → ux, uy 구속, θ 자유 (핀 지지)
        #   semi → ux, uy 구속, θ는 스프링 (반고정, ratio 비례)
        fixed = set()

        for nid, sval in self.supports.items():
            stype = sval["type"] if isinstance(sval, dict) else sval
            ratio = sval.get("ratio", 0.5) if isinstance(sval, dict) else 0.5
            d = self._dof(nid)

            if stype == 'fix':
                # 완전 고정: 3방향 모두 구속
                fixed.update([d[0], d[1], d[2]])

            elif stype == 'pin':
                # 핀: 수평·수직 구속, 회전 자유
                fixed.update([d[0], d[1]])

            elif stype == 'semi':
                # 반고정: 수평·수직 완전 구속
                fixed.update([d[0], d[1]])

                # 연결 요소의 EI/L 합산 → 기준 강성 k_ref
                k_ref = 0.0
                for eid, ni, nj, E, I, A in self.elems:
                    if ni == nid or nj == nid:
                        xi = self.node_x.get(ni, 0)
                        xj = self.node_x.get(nj, 0)
                        L_e = abs(xj - xi)
                        if L_e > 1e-9:
                            k_ref += E * I / L_e   # [N·mm/rad]

                # 회전 스프링 강성 = ratio × k_ref × 10
                k_spring = ratio * k_ref * 10.0

                if ratio >= 0.999:
                    # ratio=1 → 완전 고정 (θ 구속)
                    fixed.add(d[2])
                elif ratio > 1e-4:
                    # 0 < ratio < 1 → 스프링을 대각선에 추가
                    K[d[2], d[2]] += k_spring
                # ratio ≈ 0 → 핀과 동일, 추가 처리 없음

        # 구속되지 않은 자유 DOF 목록
        free = [i for i in range(ndof) if i not in fixed]
        if not free:
            # 모든 DOF 구속 → 물리적으로 불가능한 모델
            return None

        # ── ④ 축소 강성방정식 풀기 ────────────────────────────
        # 자유 DOF 부분만 추출: [Kff]{Uf} = {Ff}
        Kff = K[np.ix_(free, free)]   # 자유 DOF간 강성 부분행렬
        Ff  = F[free]                  # 자유 DOF 하중 벡터

        # 수치 안정성 검사 (정규화 조건수 사용)
        # 이유: 양단 고정보처럼 스케일 차이가 크면 비정규화 cond가
        #       실제보다 수백배 크게 나와 정상 모델을 오해석함.
        #       대각 원소로 정규화하면 스케일 독립적으로 판단 가능.
        try:
            diag_scale = np.sqrt(np.abs(np.diag(Kff)))
            diag_scale[diag_scale < 1e-30] = 1.0   # 0 나눔 방지
            Kff_norm = Kff / diag_scale[:, None] / diag_scale[None, :]
            cond = np.linalg.cond(Kff_norm)
            if cond > 1e12:
                # 정규화 조건수 > 1e12 → 사실상 특이행렬
                # (지지 조건 부족 또는 불안정 구조)
                return None
        except Exception:
            return None

        try:
            # 직접법으로 연립방정식 풀기
            Uf = np.linalg.solve(Kff, Ff)
        except np.linalg.LinAlgError:
            return None

        # 풀린 자유 DOF 변위를 전체 변위 벡터에 배치
        U = np.zeros(ndof)
        for i, dof in enumerate(free):
            U[dof] = Uf[i]

        # ── ⑤ 요소별 M / V / δ 분포 계산 ─────────────────────
        results = {}

        for eid, ni, nj, E, I, A in self.elems:
            xi = self.node_x[ni]
            xj = self.node_x[nj]
            L  = abs(xj - xi)
            if L < 1e-9:
                continue

            di = list(self._dof(ni))
            dj = list(self._dof(nj))

            # 요소 절점 변위 벡터 u (6성분)
            # [ux_i, uy_i, θ_i,  ux_j, uy_j, θ_j]
            u  = np.array([
                U[di[0]], U[di[1]], U[di[2]],
                U[dj[0]], U[dj[1]], U[dj[2]]
            ])

            # 경간을 n_pts 등분하여 연속 분포 계산
            n_pts = 60
            xs_list, mom, shear, defl = [], [], [], []

            for k in range(n_pts + 1):
                t = k / n_pts    # 무차원 위치 t ∈ [0, 1]
                x = t * L        # 실제 위치 x [mm]

                # ─────────────────────────────────────────────
                # 【Hermite 3차 형상함수】
                # 처짐 δ(x) = N1·δi + N2·θi + N3·δj + N4·θj
                #
                # N1(t) = 1 - 3t² + 2t³   절점 i 수직변위 기여
                # N2(t) = L(t - 2t² + t³) 절점 i 회전 기여
                # N3(t) = 3t² - 2t³       절점 j 수직변위 기여
                # N4(t) = L(-t² + t³)     절점 j 회전 기여
                # ─────────────────────────────────────────────
                N1 =  1 - 3*t**2 + 2*t**3
                N2 =  L * (t - 2*t**2 + t**3)
                N3 =  3*t**2 - 2*t**3
                N4 =  L * (-t**2 + t**3)

                # 처짐 δ(x) [mm]
                v  = N1*u[1] + N2*u[2] + N3*u[4] + N4*u[5]

                # ─────────────────────────────────────────────
                # 【휨 모멘트】 M(x) = EI · d²δ/dx²
                #
                # 형상함수 2차 도함수:
                #   d²N1/dx² = (-6 + 12t) / L²
                #   d²N2/dx² = (-4 + 6t)  / L
                #   d²N3/dx² = ( 6 - 12t) / L²
                #   d²N4/dx² = (-2 + 6t)  / L
                #
                # M > 0: 아래쪽 인장 (하향 하중에서 경간 중앙 일반적)
                # M < 0: 위쪽 인장 (지점부, 연속보 등)
                # ─────────────────────────────────────────────
                d2N1 = (-6 + 12*t) / L**2
                d2N2 = (-4 +  6*t) / L
                d2N3 = ( 6 - 12*t) / L**2
                d2N4 = (-2 +  6*t) / L

                M_Nmm = E * I * (d2N1*u[1] + d2N2*u[2]
                                 + d2N3*u[4] + d2N4*u[5])

                # ─────────────────────────────────────────────
                # 【전단력】 V(x) = EI · d³δ/dx³
                #
                # 형상함수 3차 도함수 (t에 무관한 상수):
                #   d³N1/dx³ =  12 / L³
                #   d³N2/dx³ =   6 / L²
                #   d³N3/dx³ = -12 / L³
                #   d³N4/dx³ =   6 / L²
                #
                # ※ 3차 도함수는 상수이므로 집중하중 없는 단순보/
                #   고정보에서 전단력이 경간 내 일정하게 나온다.
                #   등분포하중 시 V는 선형 변화해야 하나,
                #   이 보간식은 변위 기반이라 등분포의 V 분포가
                #   계단처럼 요소 경계에서만 반영됨
                #   (요소를 작게 나눌수록 오차 감소).
                # ─────────────────────────────────────────────
                d3N1 =  12 / L**3
                d3N2 =   6 / L**2
                d3N3 = -12 / L**3
                d3N4 =   6 / L**2

                V_N  = E * I * (d3N1*u[1] + d3N2*u[2]
                                + d3N3*u[4] + d3N4*u[5])

                xs_list.append(x)
                mom.append(M_Nmm / 1e6)    # N·mm → kN·m 변환
                shear.append(V_N  / 1e3)   # N    → kN 변환
                defl.append(v)             # mm 그대로

            # 요소 결과 딕셔너리
            results[eid] = {
                'x':  xs_list,   # 경간 내 위치 [mm] (0 ~ L)
                'M':  mom,       # 휨모멘트 분포 [kN·m]
                'V':  shear,     # 전단력 분포 [kN]
                'D':  defl,      # 처짐 분포 [mm]
                'L':  L,         # 요소 길이 [mm]
                'ni': ni,        # 시작 절점 id
                'nj': nj         # 끝 절점 id
            }

        return results
