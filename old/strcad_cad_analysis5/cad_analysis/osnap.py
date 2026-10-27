"""CAD-style object snap on the original plan lines.

Modes (AutoCAD names): END 끝점, MID 중간점, INT 교차점, PER 수직, NEA 근접.
Model snaps (node / grid / member) are handled by the app; this module only
deals with the drawing lines.
"""
from __future__ import annotations

import math
from collections import defaultdict

MODES = ("end", "mid", "int", "per", "nea")
MODE_KO = {"node": "절점", "end": "끝점", "mid": "중간점", "int": "교차점", "per": "수직", "nea": "근접",
           "grid": "그리드 교점", "member": "부재 위", "free": ""}
# lower = preferred when several snaps fall inside the aperture
RANK = {"node": 0, "end": 1, "int": 1, "mid": 2, "grid": 2, "per": 3, "member": 4, "nea": 5}


class OSnap:
    def __init__(self, segments, cell=1500.0):
        self.segs = [(s.x1, s.y1, s.x2, s.y2) for s in segments if abs(s.x2 - s.x1) + abs(s.y2 - s.y1) > 1e-6]
        self.cell = cell
        self.idx = defaultdict(list)
        for i, (x1, y1, x2, y2) in enumerate(self.segs):
            L = math.hypot(x2 - x1, y2 - y1)
            n = max(1, int(L / cell) + 1)
            seen = set()
            for k in range(n + 1):
                t = k / n
                c = (int(math.floor((x1 + (x2 - x1) * t) / cell)), int(math.floor((y1 + (y2 - y1) * t) / cell)))
                if c not in seen:
                    seen.add(c)
                    self.idx[c].append(i)

    def _near(self, x, y, r):
        c = self.cell
        out = set()
        for gx in range(int(math.floor((x - r) / c)), int(math.floor((x + r) / c)) + 1):
            for gy in range(int(math.floor((y - r) / c)), int(math.floor((y + r) / c)) + 1):
                out.update(self.idx.get((gx, gy), ()))
        return out

    @staticmethod
    def _foot(px, py, s):
        x1, y1, x2, y2 = s
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = ((px - x1) * dx + (py - y1) * dy) / L2
        return t, (x1 + dx * t, y1 + dy * t)

    def query(self, x, y, tol, modes, ref=None):
        """Candidates within tol → list of (rank, dist, kind, (x, y)), best first."""
        if not self.segs or not modes:
            return []
        near = [self.segs[i] for i in self._near(x, y, tol)]
        hits = []
        close = []
        for s in near:
            t, f = self._foot(x, y, s)
            tc = min(1.0, max(0.0, t))
            px, py = s[0] + (s[2] - s[0]) * tc, s[1] + (s[3] - s[1]) * tc
            if math.hypot(px - x, py - y) <= tol:
                close.append(s)
            if "end" in modes:
                for p in ((s[0], s[1]), (s[2], s[3])):
                    d = math.hypot(p[0] - x, p[1] - y)
                    if d <= tol:
                        hits.append((RANK["end"], d, "end", p))
            if "mid" in modes:
                p = ((s[0] + s[2]) / 2, (s[1] + s[3]) / 2)
                d = math.hypot(p[0] - x, p[1] - y)
                if d <= tol:
                    hits.append((RANK["mid"], d, "mid", p))
            if "nea" in modes and 0 <= t <= 1:
                d = math.hypot(f[0] - x, f[1] - y)
                if d <= tol:
                    hits.append((RANK["nea"], d, "nea", f))
            if "per" in modes and ref is not None:
                t2, f2 = self._foot(ref[0], ref[1], s)
                if 0 <= t2 <= 1:
                    d = math.hypot(f2[0] - x, f2[1] - y)
                    if d <= tol:
                        hits.append((RANK["per"], d, "per", f2))
        if "int" in modes and len(close) >= 2:
            for i in range(len(close)):
                a = close[i]
                for j in range(i + 1, len(close)):
                    b = close[j]
                    d1x, d1y = a[2] - a[0], a[3] - a[1]
                    d2x, d2y = b[2] - b[0], b[3] - b[1]
                    den = d1x * d2y - d1y * d2x
                    if abs(den) < 1e-9 * (abs(d1x) + abs(d1y)) * (abs(d2x) + abs(d2y)) + 1e-12:
                        continue
                    t = ((b[0] - a[0]) * d2y - (b[1] - a[1]) * d2x) / den
                    u = ((b[0] - a[0]) * d1y - (b[1] - a[1]) * d1x) / den
                    if -1e-6 <= t <= 1 + 1e-6 and -1e-6 <= u <= 1 + 1e-6:
                        p = (a[0] + d1x * t, a[1] + d1y * t)
                        d = math.hypot(p[0] - x, p[1] - y)
                        if d <= tol:
                            hits.append((RANK["int"], d, "int", p))
        hits.sort(key=lambda h: (h[0], h[1]))
        return hits
