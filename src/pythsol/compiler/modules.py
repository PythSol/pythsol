"""Load sibling project modules without executing them.

A program may ``from sibling import Name`` when ``sibling.py`` sits next to
the entry file. The compiler reads that text and parses it. It never imports
the module, so user code cannot run during a build. Third-party and stdlib
imports stay rejected.

Instructions from a sibling join the program only when a loaded file imports
them by name. Accounts, errors, enums, structs, events, and helpers from a
loaded sibling are part of the program. A file may mention a foreign name
only after importing that name.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeVar

from pythsol.compiler import resolve, subset
from pythsol.compiler.diagnostics import PS1001, PS2001, PS9000, Diagnostic
from pythsol.compiler.parse import parse_source
from pythsol.compiler.resolve import Program, ProjectImport

_DeclT = TypeVar("_DeclT")
_Walker = Callable[[str, list[str]], Program | None]

__all__ = ["load_program", "read_sibling_modules"]


def read_sibling_modules(entry: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Read ``*.py`` siblings of ``entry``. Returns ``(sources, files)``.

    The entry file itself is omitted. Stems that are not identifiers, and
    stems that start with ``_``, are omitted. The text is parsed later; it
    is never executed.
    """
    sources: dict[str, str] = {}
    files: dict[str, str] = {}
    folder = entry.parent
    if not folder.is_dir():
        return sources, files
    entry_resolved = entry.resolve()
    for path in sorted(folder.glob("*.py")):
        if path.resolve() == entry_resolved:
            continue
        stem = path.stem
        if not stem.isidentifier() or stem.startswith("_"):
            continue
        sources[stem] = path.read_text(encoding="utf-8", errors="replace")
        files[stem] = str(path)
    return sources, files


def load_program(
    source: str,
    file: str = "<program>",
    modules: Mapping[str, str] | None = None,
    module_files: Mapping[str, str] | None = None,
) -> tuple[Program | None, list[Diagnostic]]:
    """Parse, subset, and resolve ``source``, pulling in project imports.

    ``modules`` maps a sibling module name to its source text. ``None`` is the
    single-file path: a foreign import is rejected by the subset pass and no
    other file is read. The returned program is not type-checked yet.
    """
    allowed = None if modules is None else frozenset(modules)
    entry, diags = _compile_one(source, file, allowed)
    if entry is None:
        return None, diags
    if not entry.project_imports or modules is None:
        return entry, diags

    loaded: dict[str, Program] = {}
    failed: set[str] = set()
    order: list[str] = []
    extra: list[Diagnostic] = []

    def walk(name: str, stack: list[str]) -> Program | None:
        found = loaded.get(name)
        if found is not None:
            return found
        if name in failed or name in stack:
            return None
        path = (module_files or {}).get(name, f"{name}.py")
        text = modules.get(name)
        if text is None:
            return None
        program, one_diags = _compile_one(text, path, allowed)
        extra.extend(one_diags)
        if program is None:
            failed.add(name)
            return None
        loaded[name] = program
        order.append(name)
        stack.append(name)
        _bind_imports(program, program.source_file, stack, walk, modules, extra)
        stack.pop()
        return program

    _bind_imports(entry, file, [], walk, modules, extra)
    if extra:
        return None, diags + extra
    merged, merge_diags = _merge(entry, [(name, loaded[name]) for name in order])
    if merge_diags:
        return None, diags + merge_diags
    return merged, diags


def _bind_imports(
    program: Program,
    file: str,
    stack: list[str],
    walk: _Walker,
    modules: Mapping[str, str],
    diags: list[Diagnostic],
) -> None:
    """Resolve ``program``'s project imports. ``walk`` loads a sibling by name."""
    for imp in program.project_imports:
        if imp.module not in modules:
            diags.append(_missing_module(file, imp))
            continue
        if imp.module in stack:
            diags.append(
                Diagnostic(
                    code=PS1001,
                    message=f"import cycle involving `{imp.module}`",
                    file=file,
                    line=imp.line,
                    col=imp.col,
                )
            )
            continue
        target = walk(imp.module, stack)
        if target is None:
            continue
        if imp.name not in _decl_names(target):
            diags.append(
                Diagnostic(
                    code=PS1001,
                    message=f"`{imp.module}` does not define `{imp.name}`",
                    file=file,
                    line=imp.line,
                    col=imp.col,
                )
            )


def _missing_module(file: str, imp: ProjectImport) -> Diagnostic:
    return Diagnostic(
        code=PS1001,
        message=f"unknown project module `{imp.module}`",
        file=file,
        line=imp.line,
        col=imp.col,
    )


def _compile_one(
    source: str,
    file: str,
    modules: frozenset[str] | None,
) -> tuple[Program | None, list[Diagnostic]]:
    try:
        tree, parse_diags = parse_source(source, file)
    except Exception as err:  # pragma: no cover — the parser never raises today
        return None, _internal(file, "parse", err)
    if tree is None or parse_diags:
        return None, parse_diags
    try:
        subset_diags = subset.scan_tree(tree, file, modules)
    except Exception as err:
        return None, _internal(file, "subset", err)
    if subset_diags:
        return None, subset_diags
    try:
        program, resolve_diags = resolve.collect(tree, file)
    except Exception as err:
        return None, _internal(file, "resolve", err)
    if resolve_diags:
        return None, resolve_diags
    return program, []


def _decl_names(program: Program) -> set[str]:
    names: set[str] = set()
    names.update(program.accounts)
    names.update(program.errors)
    names.update(program.enums)
    names.update(program.structs)
    names.update(program.events)
    names.update(instr.name for instr in program.instructions)
    names.update(helper.name for helper in program.helpers)
    return names


def _merge(
    entry: Program,
    deps: list[tuple[str, Program]],
) -> tuple[Program, list[Diagnostic]]:
    """Fold dependency declarations into ``entry``. Entry wins the name order."""
    diags: list[Diagnostic] = []
    accounts = dict(entry.accounts)
    errors = dict(entry.errors)
    enums = dict(entry.enums)
    structs = dict(entry.structs)
    events = dict(entry.events)
    instructions = list(entry.instructions)
    helpers = list(entry.helpers)
    taken = _decl_names(entry)
    wanted = _wanted_instructions(entry, deps)

    for mod_name, dep in deps:
        _take_mapping(accounts, dep.accounts, taken, diags)
        _take_mapping(errors, dep.errors, taken, diags)
        _take_mapping(enums, dep.enums, taken, diags)
        _take_mapping(structs, dep.structs, taken, diags)
        _take_mapping(events, dep.events, taken, diags)
        for instr in dep.instructions:
            if (mod_name, instr.name) not in wanted:
                continue
            if instr.name in taken:
                diags.append(_duplicate(instr.name, instr.file, instr.line, instr.col))
                continue
            taken.add(instr.name)
            instructions.append(instr)
        for helper in dep.helpers:
            if helper.name in taken:
                diags.append(_duplicate(helper.name, helper.file, helper.line, helper.col))
                continue
            taken.add(helper.name)
            helpers.append(helper)

    imported = set(entry.imported)
    file_imports: dict[str, frozenset[str]] = {
        entry.source_file: frozenset(item.name for item in entry.project_imports)
    }
    for _name, dep in deps:
        imported.update(dep.imported)
        file_imports[dep.source_file] = frozenset(item.name for item in dep.project_imports)

    if diags:
        return entry, diags
    merged = Program(
        imported=imported,
        accounts=accounts,
        errors=errors,
        enums=enums,
        instructions=instructions,
        helpers=helpers,
        structs=structs,
        events=events,
        source_file=entry.source_file,
        project_imports=entry.project_imports,
        file_imports=file_imports,
    )
    return merged, []


def _wanted_instructions(
    entry: Program,
    deps: list[tuple[str, Program]],
) -> set[tuple[str, str]]:
    """``(module, instruction)`` pairs some loaded file imported by name."""
    by_name = {name: program for name, program in deps}
    wanted: set[tuple[str, str]] = set()
    sources = [entry, *(program for _name, program in deps)]
    for program in sources:
        for imp in program.project_imports:
            target = by_name.get(imp.module)
            if target is None:
                continue
            if any(instr.name == imp.name for instr in target.instructions):
                wanted.add((imp.module, imp.name))
    return wanted


def _take_mapping(
    dest: dict[str, _DeclT],
    src: Mapping[str, _DeclT],
    taken: set[str],
    diags: list[Diagnostic],
) -> None:
    for name, decl in src.items():
        if name in taken:
            file, line, col = _decl_pos(decl)
            diags.append(_duplicate(name, file, line, col))
            continue
        dest[name] = decl
        taken.add(name)


def _decl_pos(decl: object) -> tuple[str, int, int]:
    file = str(getattr(decl, "file", "") or "")
    line = int(getattr(decl, "line", 1) or 1)
    col = int(getattr(decl, "col", 1) or 1)
    return file, line, col


def _duplicate(name: str, file: str, line: int, col: int) -> Diagnostic:
    return Diagnostic(
        code=PS2001,
        message=f"duplicate declaration `{name}`",
        file=file or "<program>",
        line=line,
        col=col,
    )


def _internal(file: str, stage: str, err: BaseException) -> list[Diagnostic]:
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
