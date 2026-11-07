#!/usr/bin/env python3
"""Context Bridge command-line entry point.

Run as ``python3 -I cb.py <command>``. Isolated mode ignores PYTHON* environment
variables and keeps the current directory off ``sys.path``, so modules planted in an
untrusted project cannot shadow the standard library or this package.
"""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - must run on old Pythons to explain
    sys.stderr.write("context-bridge requires Python 3.11 or newer\n")
    sys.exit(2)

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_bridge.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
