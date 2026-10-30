# Contributing

Thanks for helping build PythSol! Before opening an issue, check:

- the phase plan in `docs/spec/TRD.md` §18 (what is in scope now);
- [ADR-0001](./decisions/ADR-0001-name.md) for the name/CLI spelling;
- the currently-open [issues](https://github.com/PythSol/pythsol/issues).

## Setup

```bash
git clone https://github.com/PythSol/pythsol && cd pythsol
pip install -e .[dev]
ruff check .          # lint
ruff format .         # format
mypy --strict .       # types
pytest -q              # tests
```

Small, reviewable pull requests: one feature or one fix. Use
[Conventional Commits](https://www.conventionalcommits.org/). CI runs ruff, mypy
(strict), pytest on Python 3.11–3.13 (Linux + macOS) and a `toolchain` job that
compiles a spike program with Anza platform-tools and runs it in LiteSVM.

## Ground rules

- Anything that runs on chain must be fully tested against the Python reference
  runtime (`docs/architecture.md` explains the two paths).
- Never execute user program code inside the compiler; parse with `ast` only.
- Keep design assumptions in `docs/decisions/` with a spike or link to evidence.
- Documentation changes to `README.md` and `docs/` are reviewed like code.
