"""PyInstaller runtime hook: point pydantic-monty at the bundled worker binary.

Code mode runs sandboxed code in ``monty`` worker subprocesses. pydantic-monty
looks for that executable in the environment's scripts directory, which a
one-file bundle does not have, so the build scripts ship it at the bundle root
and this hook names it via ``MONTY_BIN`` before any Panoply code runs. An
explicit ``MONTY_BIN`` from the caller still wins.
"""

import os
import sys

_name = "monty.exe" if sys.platform == "win32" else "monty"
_bundled = os.path.join(getattr(sys, "_MEIPASS", ""), _name)
if os.path.isfile(_bundled):
    os.environ.setdefault("MONTY_BIN", _bundled)
