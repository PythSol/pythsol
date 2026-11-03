"""Stage the single-tree Vercel deployment without PowerShell.

    .\\.venv\\Scripts\\python.exe tools\\stage_vercel.py

Builds ``target/vercel_stage`` from the playground assets, the Starlight
``web/docs/dist`` output, the ``pythsol`` package, and ``deploy/vercel``.
Deploy it with::

    vercel deploy target/vercel_stage --prod --yes --scope rehmandakat67-3497 --name pythsol

The repository-root ``vercel.json`` is the push-to-deploy path; this script
remains the reproducible local CLI path.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "target" / "vercel_stage"
UI_FILES = (
    "landing.html",
    "playground.html",
    "docs.html",
    "app.css",
    "app.js",
    "site.css",
    "favicon.svg",
    "favicon.ico",
    "favicon-32.png",
    "apple-touch-icon.png",
    "hero-bg.webp",
    "site-bg.svg",
    "robots.txt",
)


def main() -> int:
    docs = ROOT / "web" / "docs" / "dist"
    if not docs.is_dir():
        print("web/docs/dist is missing; run `npm run build` in web/docs", file=sys.stderr)
        return 1
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    shutil.copy2(ROOT / "deploy" / "vercel" / "vercel.json", STAGE / "vercel.json")
    (STAGE / "requirements.txt").write_text("click>=8.1\n", encoding="ascii")
    shutil.copy2(ROOT / "deploy" / "vercel" / "index.py", STAGE / "index.py")
    shutil.copy2(ROOT / "deploy" / "vercel" / "api" / "wsgi_common.py", STAGE / "wsgi_common.py")
    for name in UI_FILES:
        shutil.copy2(ROOT / "src" / "pythsol" / "playground" / name, STAGE / name)

    shutil.copytree(docs, STAGE / "docs")
    shutil.copytree(
        ROOT / "src" / "pythsol",
        STAGE / "pythsol",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    count = sum(1 for path in STAGE.rglob("*") if path.is_file())
    print(f"staged {count} files in {STAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
