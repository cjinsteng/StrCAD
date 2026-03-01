"""
보 평면도 시각화 모듈
- 인식된 보(이름, 스팬, 폭)를 선/사각형으로 표현한 이미지 생성
"""

import math
import os
from typing import List, Dict, Optional


class BeamVisualizer:
    """보 평면 시각화 클래스"""

    # 방향별 색상
    COLORS = {
        'X방향': '#2196F3',   # 파랑
        'Y방향': '#F44336',   # 빨강
        '대각선': '#FF9800',  # 주황
        'grid':  '#EEEEEE',
        'bg':    '#FAFAFA',
        'text':  '#212121',
        'col':   '#4CAF50',   # 기둥: 초록
    }

    def __init__(self, beam_data: List[Dict],
                 column_positions: Optional[List] = None,
                 title: str = "보 평면도"):
        self.beam_data = beam_data
        self.column_positions = column_positions or []
        self.title = title

    # ------------------------------------------------------------------ #

    def save_image(self, output_path: str = "beam_plan.png",
                   dpi: int = 150) -> str:
        """
        matplotlib으로 이미지 저장.
        matplotlib이 없으면 SVG로 fallback.
        """
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
            return self._save_matplotlib(plt, mpatches, output_path, dpi)
        except ImportError:
            svg_path = output_path.replace('.png', '.svg')
            return self._save_svg(svg_path)

    # ------------------------------------------------------------------ #
    #  matplotlib 렌더링
    # ------------------------------------------------------------------ #

    def _save_matplotlib(self, plt, mpatches, output_path, dpi):
        if not self.beam_data:
            print("⚠ 시각화할 보 데이터가 없습니다.")
            return None

        fig, ax = plt.subplots(figsize=(14, 12))
        ax.set_facecolor(self.COLORS['bg'])
        fig.patch.set_facecolor('#FFFFFF')

        # 좌표 범위 계산
        all_pts = (
            [s['start_point'] for s in self.beam_data] +
            [s['end_point']   for s in self.beam_data] +
            list(self.column_positions)
        )
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        if not xs:
            return None

        margin = (max(xs)-min(xs)+max(ys)-min(ys)) * 0.05 + 500
        ax.set_xlim(min(xs)-margin, max(xs)+margin)
        ax.set_ylim(min(ys)-margin, max(ys)+margin)
        ax.set_aspect('equal')

        # 기둥 표시
        for cp in self.column_positions:
            sq = mpatches.Rectangle(
                (cp[0]-150, cp[1]-150), 300, 300,
                linewidth=1.5, edgecolor='#1B5E20',
                facecolor=self.COLORS['col'], alpha=0.7, zorder=3
            )
            ax.add_patch(sq)

        # 보 표시
        label_done = set()
        for span in self.beam_data:
            sp = span['start_point']
            ep = span['end_point']
            direction = span['beam_direction']
            color = self.COLORS[direction]
            width_mm = span.get('beam_width', 0)
            span_m = span['span_length'] / 1000

            lw = 4 if width_mm > 0 else 2

            # 보 중심선
            ax.plot([sp[0], ep[0]], [sp[1], ep[1]],
                    color=color, linewidth=lw, solid_capstyle='round',
                    alpha=0.85, zorder=2,
                    label=direction if direction not in label_done else '')
            label_done.add(direction)

            # 폭이 인식된 경우 테두리 표시 (반투명 사각형)
            if width_mm > 0:
                self._draw_beam_rect(ax, sp, ep, width_mm, color)

            # 라벨: 보 ID + 스팬 + 폭
            mx = (sp[0]+ep[0])/2
            my = (sp[1]+ep[1])/2
            label = f"{span['beam_id']}\n{span_m:.2f}m"
            if width_mm > 0:
                label += f"\nW={width_mm:.0f}mm"
            ax.text(mx, my, label,
                    fontsize=6.5, ha='center', va='center',
                    color='white' if lw > 2 else self.COLORS['text'],
                    fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.2',
                              facecolor=color, alpha=0.75,
                              edgecolor='none'),
                    zorder=4)

        # 범례 & 제목
        handles = [
            mpatches.Patch(color=self.COLORS['X방향'], label=f'X방향 보 ({sum(1 for s in self.beam_data if s["beam_direction"]=="X방향")}개)'),
            mpatches.Patch(color=self.COLORS['Y방향'], label=f'Y방향 보 ({sum(1 for s in self.beam_data if s["beam_direction"]=="Y방향")}개)'),
            mpatches.Patch(color=self.COLORS['대각선'], label=f'대각선 보 ({sum(1 for s in self.beam_data if s["beam_direction"]=="대각선")}개)'),
            mpatches.Patch(color=self.COLORS['col'], label=f'기둥 ({len(self.column_positions)}개)'),
        ]
        ax.legend(handles=handles, loc='upper right', fontsize=9,
                  framealpha=0.9, edgecolor='#BDBDBD')

        ax.set_title(self.title, fontsize=14, fontweight='bold', pad=12)
        ax.set_xlabel('X (mm)', fontsize=9)
        ax.set_ylabel('Y (mm)', fontsize=9)
        ax.grid(True, color=self.COLORS['grid'], linewidth=0.5, zorder=0)
        ax.tick_params(labelsize=7)

        # 통계 텍스트 박스
        paired = sum(1 for s in self.beam_data if s.get('beam_width', 0) > 0)
        stats = (f"총 보 스팬: {len(self.beam_data)}개\n"
                 f"폭 인식: {paired}개\n"
                 f"평균 스팬: {sum(s['span_length'] for s in self.beam_data)/len(self.beam_data)/1000:.2f}m")
        ax.text(0.01, 0.99, stats, transform=ax.transAxes,
                fontsize=8, va='top', ha='left',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor='#BDBDBD'))

        plt.tight_layout()
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight')
        plt.close()
        print(f"✓ 보 평면도 이미지 저장: {output_path}")
        return output_path

    @staticmethod
    def _draw_beam_rect(ax, sp, ep, width_mm, color):
        """보 중심선 기준으로 폭을 표현하는 반투명 사각형"""
        import matplotlib.patches as mpatches
        dx = ep[0] - sp[0]
        dy = ep[1] - sp[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return
        nx = -dy / length  # 법선벡터
        ny =  dx / length
        hw = width_mm / 2   # half width

        corners = [
            (sp[0] + nx*hw, sp[1] + ny*hw),
            (ep[0] + nx*hw, ep[1] + ny*hw),
            (ep[0] - nx*hw, ep[1] - ny*hw),
            (sp[0] - nx*hw, sp[1] - ny*hw),
        ]
        from matplotlib.patches import Polygon
        poly = Polygon(corners, closed=True,
                       facecolor=color, alpha=0.15,
                       edgecolor=color, linewidth=0.8,
                       linestyle='--', zorder=1)
        ax.add_patch(poly)

    # ------------------------------------------------------------------ #
    #  SVG fallback
    # ------------------------------------------------------------------ #

    def _save_svg(self, output_path: str) -> str:
        if not self.beam_data:
            return None

        all_pts = [s['start_point'] for s in self.beam_data] + [s['end_point'] for s in self.beam_data]
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        if not xs:
            return None

        W, H = 1200, 900
        margin = 80
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        x_range = x_max - x_min or 1
        y_range = y_max - y_min or 1

        def tx(x): return margin + (x - x_min) / x_range * (W - 2*margin)
        def ty(y): return H - margin - (y - y_min) / y_range * (H - 2*margin)

        color_map = {'X방향': '#2196F3', 'Y방향': '#F44336', '대각선': '#FF9800'}

        lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" style="background:#FAFAFA">']
        lines.append(f'<text x="{W//2}" y="40" text-anchor="middle" font-size="20" font-weight="bold">{self.title}</text>')

        for span in self.beam_data:
            sp = span['start_point']
            ep = span['end_point']
            c  = color_map.get(span['beam_direction'], '#999')
            x1, y1 = tx(sp[0]), ty(sp[1])
            x2, y2 = tx(ep[0]), ty(ep[1])
            lines.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{c}" stroke-width="3" stroke-linecap="round"/>')
            mx, my = (x1+x2)/2, (y1+y2)/2
            label = f"{span['beam_id']} {span['span_length']/1000:.1f}m"
            if span.get('beam_width', 0) > 0:
                label += f" W={span['beam_width']:.0f}"
            lines.append(f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" font-size="9" fill="{c}" font-weight="bold">{label}</text>')

        lines.append('</svg>')

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"✓ 보 평면도 SVG 저장: {output_path}")
        return output_path
