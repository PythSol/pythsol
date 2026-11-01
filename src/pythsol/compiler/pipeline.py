"""Full compile pipeline: source → diagnostics-checked model → C text.

``check_source`` answers "does this program type-check?"; :mod:`pipeline`
answers "turn it into C". Both report problems as diagnostics only (never
exceptions for user input), so the CLI and tests share one contract:

* the returned ``GeneratedProgram.diagnostics`` list is empty only when
  ``c_text`` and ``generated`` are usable;
* ``PS9000`` still means a compiler bug (report it), just like the front-end;
* the phase 3 emitter adds ``PS4xxx`` (model) and ``PS5xxx`` (emit) codes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pythsol.compiler import resolve, typecheck
from pythsol.compiler.diagnostics import PS9000, Diagnostic
from pythsol.compiler.emit import emit_program_c
from pythsol.compiler.idl import build_idl, validate_idl
from pythsol.compiler.model import ProgramModel, build_model
from pythsol.compiler.modules import load_program

__all__ = [
    "GeneratedProgram",
    "emit_program",
    "idl_ok",
    "prepare_program",
]


@dataclass
class GeneratedProgram:
    """The pipeline output for one source file."""

    #: snake_case program name (used for file names).
    name: str
    #: source file as given (absolute paths are caller concerns).
    source_file: str
    #: generated C text (empty when diagnostics exist).
    c_text: str = ""
    #: elaborated model (usable when ``not diagnostics``).
    generated: ProgramModel | None = None
    #: all diagnostics from front-end, model and emitter; sorted for output.
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """``True`` when the program generated cleanly."""
        return not self.diagnostics and bool(self.c_text) and self.generated is not None


def prepare_program(
    source_text: str,
    file: str = "<program>",
    *,
    modules: Mapping[str, str] | None = None,
    module_files: Mapping[str, str] | None = None,
) -> tuple[resolve.Program | None, list[Diagnostic]]:
    """parse → subset → resolve → typecheck; returns the ``Program`` or diags.

    ``modules`` is the same sibling map ``check_source`` accepts. Project
    modules are parsed, not executed.
    """
    try:
        program, diagnostics = load_program(source_text, file, modules, module_files)
    except Exception as err:  # pragma: no cover — load_program catches stage errors
        return None, _internal(file, "parse", err)
    if program is None or diagnostics:
        return None, diagnostics
    try:
        diagnostics.extend(typecheck.check_program(program, file))
    except Exception as err:
        return program, diagnostics + _internal(file, "typecheck", err)
    return program, diagnostics


def emit_program(
    source_text: str,
    path: Path,
    name: str | None = None,
    *,
    modules: Mapping[str, str] | None = None,
    module_files: Mapping[str, str] | None = None,
) -> GeneratedProgram:
    """Run the full pipeline for one source file.

    ``name`` overrides the program/file stem naming; diagnostics are
    position-sorted and never raise.
    """
    file_path = Path(path)
    program_name = name or file_path.stem
    source = file_path.name
    program, diagnostics = prepare_program(
        source_text,
        file=str(file_path),
        modules=modules,
        module_files=module_files,
    )
    if program is None or diagnostics:
        return GeneratedProgram(
            name=program_name,
            source_file=source,
            diagnostics=_sorted(diagnostics),
        )

    model, model_diags = build_model(program, program_name, source=source)
    if model_diags:
        return GeneratedProgram(
            name=program_name,
            source_file=source,
            diagnostics=_sorted(diagnostics + model_diags),
        )
    text, emit_diags = emit_program_c(model)
    if emit_diags or text == "":
        return GeneratedProgram(
            name=program_name,
            source_file=source,
            diagnostics=_sorted(diagnostics + emit_diags),
        )
    return GeneratedProgram(
        name=program_name,
        source_file=source,
        c_text=text,
        generated=model,
        diagnostics=[],
    )


def idl_ok(model: ProgramModel) -> list[str]:
    """Validate the model's own IDL; non-empty = structural problems."""
    return validate_idl(build_idl(model))


def _sorted(diags: list[Diagnostic]) -> list[Diagnostic]:
    return sorted(diags, key=lambda d: (d.file, d.line, d.col, d.code))


def _internal(file: str, stage: str, err: BaseException) -> list[Diagnostic]:
    """An escaped exception is a compiler bug: report it as PS9000."""
    return [
        Diagnostic(
            code=PS9000,
            message=f"internal compiler error in {stage}: {err!r}",
            file=file,
            line=1,
            col=1,
            fix="please report this at github.com/PythSol/pythsol/issues",
        )
    ]
