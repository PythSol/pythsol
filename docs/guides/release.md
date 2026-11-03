# Publishing PythSol to PyPI

The package name `pythsol` is free on PyPI as of 2026-11-03 (the JSON API
returns 404). Version stays `0.1.0` until the user orders a version bump.
Do not upload without an explicit publish order and an API token available
in the environment — never put the token in this repo or in chat.

## 1. Build

From the repo root, with the project virtualenv:

```powershell
.\.venv\Scripts\python.exe -m pip install "build>=1.2" "twine>=5"
.\.venv\Scripts\python.exe -m build --outdir dist
.\.venv\Scripts\python.exe -m twine check dist\*
```

Both `pythsol-0.1.0.tar.gz` and `pythsol-0.1.0-py3-none-any.whl` must PASS.

## 2. Prove the wheel, not the checkout

Use a **fresh** virtualenv and install the wheel, not `-e .`:

```powershell
python -m venv target\pypi-venv
.\target\pypi-venv\Scripts\python.exe -m pip install dist\pythsol-0.1.0-py3-none-any.whl
.\target\pypi-venv\Scripts\pythsol.exe --version
```

Acceptance checks (all must pass):

```powershell
# scaffold + front end
cd target\pypi-test
..\pypi-venv\Scripts\pythsol.exe init demo --template counter
cd demo
..\..\pypi-venv\Scripts\pythsol.exe check programs\demo.py
..\..\pypi-venv\Scripts\pythsol.exe emit-c programs\demo.py --out build\demo.c

# native build against a real platform-tools tree
$env:PYTHSOL_SBF_SDK = (Resolve-Path "..\..\..\Spikes\tools\platform-tools-1.58").Path
..\..\pypi-venv\Scripts\pythsol.exe build programs\demo.py

# the installed package can serve its own assets
..\..\pypi-venv\Scripts\pythsol.exe serve --port 8799
# GET /, /playground, /site.css, /favicon.svg must be 200
# POST /v1/check must answer JSON
```

The wheel ships every runtime asset; `tests/test_packaging.py` fails if a
playground file is added without a matching force-include entry.

## 3. Upload

Set the token in the shell (PowerShell):

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "<the PyPI API token>"
.\.venv\Scripts\python.exe -m twine upload dist\*
```

TestPyPI first is optional but recommended:

```powershell
.\.venv\Scripts\python.exe -m twine upload --repository testpypi dist\*
```

## 4. Verify the release

```powershell
.\.venv\Scripts\python.exe -m pip index versions pythsol
python -m venv target\pypi-release-check
.\target\pypi-release-check\Scripts\python.exe -m pip install "pythsol[test]"
.\target\pypi-release-check\Scripts\pythsol.exe --version
```

Then, and only then, update the install copy that still says “not on PyPI”:

- `README.md` install block
- `src/pythsol/playground/landing.html` note under the install card
- `src/pythsol/playground/docs.html` quickstart
- `web/docs` quickstart page
- `docs/STATUS.md` and `docs/HANDOFF.md`

Keep the git install line as the development path.
