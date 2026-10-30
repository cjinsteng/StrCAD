"""StrCAD CAD Analysis — standalone launcher.

    python run_cad_analysis.py [plan.dxf]
    StrCAD.exe --selftest result.txt     (설치판 점검용: 모듈·리소스 확인 후 종료)

Launcher integration (launcher.py):
    from cad_analysis.app import open_window
    open_window(root)          # opens as Toplevel
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _selftest(out):
    lines = []
    try:
        from cad_analysis import __version__, app, check, sync, theme, licensing, licensing_ui  # noqa: F401
        import ezdxf
        lines.append(f"version {__version__}")
        lines.append(f"ezdxf {ezdxf.__version__}")
        lines.append("license " + licensing.status().get("state", "?") + " · code " + licensing.machine_code())
        for rel in (("cad_analysis", "assets", "icon.ico"), ("mobile", "index.html"), ("mobile", "app.js"),
                    ("mobile", "vendor", "sql-wasm.wasm"), ("mobile", "sketch.js"), ("mobile", "vendor", "pdfjs", "pdf.min.js"),
                    ("samples",)):
            p = theme.resource(*rel)
            lines.append(f"{'OK' if os.path.exists(p) else 'MISSING'} {'/'.join(rel)}")
        try:
            import tkinterdnd2  # noqa: F401
            lines.append("OK tkinterdnd2")
        except Exception as e:  # noqa: BLE001
            lines.append(f"MISSING tkinterdnd2 {e}")
        try:
            import pypdfium2 as pdfium
            import pdfminer  # noqa: F401
            d = pdfium.PdfDocument.new()
            d.new_page(200, 100)
            im = d[0].render(scale=1).to_pil()
            lines.append(f"OK pdf {im.size}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"MISSING pdf {e}")
        r = check.rc_column_check(500, 500, 2000, 280, 60, "8-HD22", "HD10@300")
        lines.append("check " + str(check.summarize(r[0])))
    except Exception as e:  # noqa: BLE001
        import traceback
        lines.append("FAIL " + repr(e))
        lines.append(traceback.format_exc())
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        _selftest(sys.argv[2])
        sys.exit(0)
    from cad_analysis.app import open_window  # noqa: E402
    open_window(path=sys.argv[1] if len(sys.argv) > 1 else None)
