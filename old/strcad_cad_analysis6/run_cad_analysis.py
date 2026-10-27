"""StrCAD CAD Analysis — standalone launcher.

    python run_cad_analysis.py [plan.dxf]

Launcher integration (launcher.py):
    from cad_analysis.app import open_window
    open_window(root)          # opens as Toplevel
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cad_analysis.app import open_window  # noqa: E402

if __name__ == "__main__":
    open_window(path=sys.argv[1] if len(sys.argv) > 1 else None)
