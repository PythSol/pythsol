# PythSol for VS Code

This extension runs `pythsol check --json` on a saved Python file whose text
contains `pythsol`. Diagnostics use the CLI payload:

```json
{"ok": false, "diagnostics": [{"code": "PS1003", "message": "...", "file": "...", "line": 1, "col": 1, "fix": null}]}
```

`line` and `col` are 1-based. The extension maps them onto a VS Code range.

Install from this folder with **Developer: Install Extension from Location...**
after `pip install -e .` so the `pythsol` command is on `PATH`. The setting
`pythsol.executable` overrides the command name. The extension is not published.
The CLI takes one program path. It does not accept a `--files` flag.
