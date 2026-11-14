"""Entry point.

``python main.py``          opens the GUI (the default)
``python main.py --cli ...`` runs headless
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("--cli", "--headless"):
        from cli import main as cli_main

        return cli_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        from cli import build_parser

        build_parser().print_help()
        return 0
    try:
        from gui.app import main as gui_main

        return gui_main()
    except ImportError as exc:
        print("The GUI could not start:", exc)
        print("Run 'python main.py --cli --help' for the command line interface.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
