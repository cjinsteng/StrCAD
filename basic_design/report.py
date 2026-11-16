"""
basic_design/report.py
계산서(Report) — 항목 목록을 만들고 Tk Canvas 에 그리거나 텍스트로 내보낸다.
  rep = Report(); rep.h("Design Conditions"); rep.t("fck = 24 N/mm²", lv=2)
  rep.table(head, rows, widths);  render(canvas, rep, sketch=fn)
"""
import tkinter.font as tkfont

from . import theme as T

STYLE_FG = {"n": T.INK, "b": T.INK, "sub": T.INK, "ok": T.OK, "ng": T.NG, "dim": T.MUTED, "warn": T.WARN, "blue": T.OK}
MARGIN = 26
INDENT = 18
LINE_H = 21
PAGE_W = 900


class Report:
    def __init__(self, title=""):
        self.title = title
        self.items = []

    def h(self, text):
        self.items.append(("h", text))

    def t(self, text, lv=1, style="n"):
        self.items.append(("t", text, lv, style))

    def gap(self, px=8):
        self.items.append(("gap", px))

    def table(self, head, rows, widths, aligns=None):
        """head: 머리글 행 목록(각 행 = 셀 문자열 목록).  rows: 셀 = str | (str, style)
        rows 의 원소가 None 이면 구분선."""
        self.items.append(("table", head, rows, widths, aligns or ["c"] * len(widths)))

    # ── 텍스트 내보내기 ──────────────────────────────────────
    def to_text(self):
        out = []
        if self.title:
            out += [self.title, "=" * 72]
        for it in self.items:
            if it[0] == "h":
                out += ["", f"■ {it[1]}", "-" * 72]
            elif it[0] == "t":
                out.append("  " * it[2] + it[1])
            elif it[0] == "gap":
                if it[1] >= 8:
                    out.append("")
            elif it[0] == "table":
                _, head, rows, widths, aligns = it
                cw = [max(6, w // 8) for w in widths]

                def fmt(cells):
                    s = ""
                    for i, c in enumerate(cells):
                        txt = c[0] if isinstance(c, tuple) else c
                        s += _pad(txt, cw[i], aligns[i] if i < len(aligns) else "c") + " "
                    return "  " + s.rstrip()
                for hr in head:
                    out.append(fmt(hr))
                out.append("  " + "-" * (sum(cw) + len(cw)))
                for r in rows:
                    out.append("  " + "-" * (sum(cw) + len(cw)) if r is None else fmt(r))
        return "\n".join(out) + "\n"


def _wlen(s):
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def _pad(s, n, align):
    k = max(n - _wlen(s), 0)
    if align == "l":
        return s + " " * k
    if align == "r":
        return " " * k + s
    return " " * (k // 2) + s + " " * (k - k // 2)


# ── Canvas 렌더링 ────────────────────────────────────────────
_fonts = {}


def fonts(root=None):
    if not _fonts:
        _fonts["h"] = tkfont.Font(root=root, family=T.FAM, size=14, weight="bold")
        _fonts["sub"] = tkfont.Font(root=root, family=T.FAM, size=11, weight="bold")
        _fonts["n"] = tkfont.Font(root=root, family=T.FAM, size=10)
        _fonts["b"] = tkfont.Font(root=root, family=T.FAM, size=10, weight="bold")
        _fonts["s"] = tkfont.Font(root=root, family=T.FAM, size=8)
    return _fonts


def render(cv, rep, sketch=None, sketch_box=(590, 18, 290, 330)):
    """rep 을 Canvas 에 그린다. sketch(cv, x, y, w, h) 는 오른쪽 위 그림 영역."""
    F = fonts(cv)
    cv.delete("all")
    y = 16
    first_h = True
    sx, sy, sw, sh = sketch_box
    for it in rep.items:
        kind = it[0]
        if kind == "h":
            y += 6 if first_h else 16
            right = (sx - 14) if (sketch and y < sy + sh) else PAGE_W - MARGIN
            tw = F["h"].measure(it[1])
            cv.create_rectangle(MARGIN - 12, y + 9, MARGIN - 6, y + 15, fill=T.NAVY, outline=T.NAVY)
            cv.create_text(MARGIN, y + 12, text=it[1], anchor="w", font=F["h"], fill=T.NAVY)
            cv.create_line(MARGIN + tw + 8, y + 12, right, y + 12, fill=T.NAVY)
            y += 30
            first_h = False
        elif kind == "t":
            _, text, lv, style = it
            f = F["sub"] if style == "sub" else (F["b"] if style in ("b", "ok", "ng") else F["n"])
            cv.create_text(MARGIN + lv * INDENT, y + LINE_H // 2, text=text, anchor="w", font=f,
                           fill=STYLE_FG.get(style, T.INK))
            y += LINE_H + (3 if style == "sub" else 0)
        elif kind == "gap":
            y += it[1]
        elif kind == "table":
            if sketch and y < sy + sh + 8:
                y = sy + sh + 14                        # 표는 그림 아래에서 시작
            y = _draw_table(cv, F, it, y)
    if sketch:
        cv.create_rectangle(sx, sy, sx + sw, sy + sh, outline=T.NAVY)
        sketch(cv, sx, sy, sw, sh)
    y += 30
    cv.configure(scrollregion=(0, 0, PAGE_W, max(y, sy + sh + 30)))
    return y


def _draw_table(cv, F, it, y):
    _, head, rows, widths, aligns = it
    x0 = MARGIN
    tw = sum(widths)
    rh = 22
    hh = rh * len(head) + 4
    cv.create_rectangle(x0, y, x0 + tw, y + hh, fill="#E5E9F0", outline="")
    cv.create_line(x0, y, x0 + tw, y, fill=T.INK, width=2)
    for i, hr in enumerate(head):
        x = x0
        for j, c in enumerate(hr):
            if c:
                cv.create_text(x + widths[j] / 2, y + 2 + rh * i + rh / 2, text=c, font=F["n"], fill=T.INK)
            x += widths[j]
    y += hh
    cv.create_line(x0, y, x0 + tw, y, fill=T.INK)
    for r in rows:
        if r is None:
            cv.create_line(x0, y, x0 + tw, y, fill="#9CA3AF")
            continue
        x = x0
        for j, c in enumerate(r):
            txt, style = (c if isinstance(c, tuple) else (c, "n"))
            if txt:
                al = aligns[j] if j < len(aligns) else "c"
                f = F["b"] if style in ("b", "ng") else F["n"]
                fg = STYLE_FG.get(style, T.INK)
                if al == "l":
                    cv.create_text(x + 8, y + rh / 2, text=txt, anchor="w", font=f, fill=fg)
                elif al == "r":
                    cv.create_text(x + widths[j] - 10, y + rh / 2, text=txt, anchor="e", font=f, fill=fg)
                else:
                    cv.create_text(x + widths[j] / 2, y + rh / 2, text=txt, font=f, fill=fg)
            x += widths[j]
        y += rh
    cv.create_line(x0, y, x0 + tw, y, fill=T.INK, width=2)
    return y + 8
