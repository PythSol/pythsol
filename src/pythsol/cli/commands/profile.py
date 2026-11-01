"""`pythsol profile` — read compute units and source locations from logs.

The runtime already logs ``(file.py:line)`` on failure and the loader logs
``consumed N of M compute units`` for the whole instruction. This command
prints those. It does not invent a per-line CU split.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click

_CU = re.compile(r"consumed (\d+) of (\d+)")
_LOC = re.compile(r"\(([^():]+\.py):(\d+)\)")


def profile_rows(text: str) -> list[tuple[str, str]]:
    """``(location, detail)`` rows from program logs."""
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        for match in _LOC.finditer(line):
            key = (f"{match.group(1)}:{match.group(2)}", "logged")
            if key not in seen:
                seen.add(key)
                rows.append(key)
        consumed = _CU.search(line)
        if consumed:
            rows.append(("(program)", f"{consumed.group(1)} of {consumed.group(2)} CU"))
    return rows


@click.command(name="profile")
@click.option(
    "--logs",
    "logs_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="File of program logs. Default: stdin.",
)
def profile(logs_path: Path | None) -> None:
    """Print source locations and the program compute-unit total from logs."""
    if logs_path is None:
        text = sys.stdin.read()
    else:
        text = logs_path.read_text(encoding="utf-8", errors="replace")
    rows = profile_rows(text)
    if not rows:
        click.echo("profile: no source locations or compute-unit lines")
        sys.exit(1)
    click.echo(f"{'location':<24} detail")
    for location, detail in rows:
        click.echo(f"{location:<24} {detail}")
    sys.exit(0)
