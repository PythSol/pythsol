# Publishing PythSol to PyPI

**0.1.0 is published** (2026-11-04):
<https://pypi.org/project/pythsol/0.1.0/>. Version stays `0.1.0` until the
user orders a version bump; PyPI releases are immutable, so a new upload
needs a new version. Do not upload without an explicit publish order and an
API token — never put the token in this repo or in chat. The first token was
exposed in chat; revoke it and use a project-scoped token.

## 1. Build

From the repo root, with the project virtualenv:

```powershell
.\.venv\Scripts\python.exe -m pip install "build>=1.2" "twine>=5"
.\.venv\Scripts\python.exe -m build --outdir target\dist
.\.venv\Scripts\python.exe -m twine check target\dist\*
```

Both `pythsol-0.1.0.tar.gz` and `pythsol-0.1.0-py3-none-any.whl` must PASS.

## 2. Prove the wheel, not the checkout

Use a **fresh** virtualenv and install the wheel, not `-e .`:

```powershell
python -m venv target\pypi-venv
.\target\pypi-venv\Scripts\python.exe -m pip install target\dist\pythsol-0.1.0-py3-none-any.whl
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

The package name `pythsol` is free as of 2026-11-03. PyPI needs an account
with a verified email and an API token; the token is shown once and must not
be committed or pasted into chat.

### One command (prompts for the token, hidden)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\publish_pypi.ps1
```

The script builds if needed, runs `twine check`, prompts with hidden input,
uploads only for that process, and clears the variables afterwards.

### Or let the agent upload from a local config

Create `%USERPROFILE%\.pypirc` yourself (never in the repo):

```ini
[pypi]
username = __token__
password = pypi-AgEIcHlwaS5vcmc...
```

Then the upload is:

```powershell
.\.venv\Scripts\python.exe -m twine upload --config-file "$env:USERPROFILE\.pypirc" target\dist\*
```

For the first upload the token scope must be **Entire account** because the
project does not exist yet. After the first release, replace it with a
project-scoped token.

TestPyPI first is optional but recommended:

```powershell
.\.venv\Scripts\python.exe -m twine upload --repository testpypi target\dist\*
```

## 4. Verify the release

```powershell
.\.venv\Scripts\python.exe -m pip index versions pythsol
python -m venv target\pypi-release-check
.\target\pypi-release-check\Scripts\python.exe -m pip install "pythsol[test]"
.\target\pypi-release-check\Scripts\pythsol.exe --version
```

After a **new version** is uploaded, update the install copy that names the
version or the release state:

- `README.md` install block
- `src/pythsol/playground/landing.html` install card and roadmap
- `src/pythsol/playground/docs.html` quickstart
- `web/docs` quickstart page
- `docs/STATUS.md` and `docs/HANDOFF.md`
- `docs/guides/release.md` (this file)

Keep the git install line as the development path.
