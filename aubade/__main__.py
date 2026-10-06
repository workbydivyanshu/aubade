"""Aubade entry point. Must run under system python (/usr/bin/python3)."""
import sys

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst


def main() -> int:
    Gst.init(None)
    from .ui import AubadeApp
    return AubadeApp().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
