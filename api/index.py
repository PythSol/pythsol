"""Vercel entrypoint for a repository-root build.

The staged deploy copies ``deploy/vercel/index.py`` to the deployment root.
This wrapper runs the same WSGI app from the repository so a Vercel Git build
does not need a local stage: ``vercel.json`` builds the Starlight site and
this function serves the landing page, playground, docs, and ``/v1/*``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "deploy" / "vercel"))
sys.path.insert(0, str(ROOT / "deploy" / "vercel" / "api"))

os.environ.setdefault("PYTHSOL_UI_DIR", str(ROOT / "src" / "pythsol" / "playground"))
os.environ.setdefault("PYTHSOL_DOCS_DIR", str(ROOT / "web" / "docs" / "dist"))

_spec = importlib.util.spec_from_file_location(
    "pythsol_vercel_app", ROOT / "deploy" / "vercel" / "index.py"
)
if _spec is None or _spec.loader is None:  # pragma: no cover - packaging error
    raise RuntimeError("deploy/vercel/index.py is missing")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

app = _module.app
