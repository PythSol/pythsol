"""Stage 3 — resolve declarations into a small in-memory program model.

After the subset pass has validated shapes, this pass collects:

* the imported surface names,
* ``@account`` classes with their fields,
* ``@error`` classes with their numeric members,
* ``@enum`` classes with unit variants (tag equals declaration index),
* ``@event`` classes (fixed-width values that ``emit`` logs),
* ``@instruction`` functions with typed params and their bodies,
* plain helper functions (no decorator, not an instruction).

The model here is intentionally dumb (positions + AST references); the
expression-level *meaning* of annotations is assigned in
:mod:`pythsol.compiler.typecheck`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from pythsol.compiler.diagnostics import PS2001, Diagnostic

#: Helpers must not hide calls the compiler already lowers itself.
_RESERVED_HELPERS: frozenset[str] = frozenset(
    {
        "require",
        "len",
        "range",
        "emit",
        "system_transfer",
        "token_transfer",
        "token2022_transfer",
        "ata_create",
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
    }
)

__all__ = [
    "AccountDecl",
    "EnumDecl",
    "ErrorDecl",
    "EventDecl",
    "FieldDecl",
    "HelperDecl",
    "InstructionDecl",
    "MemberDecl",
    "ParamDecl",
    "Program",
    "ProjectImport",
    "StructDecl",
    "collect",
]


def _pos(node: ast.AST) -> tuple[int, int]:
    """1-based (line, col) of a node."""
    return (
        getattr(node, "lineno", 1) or 1,
        (getattr(node, "col_offset", 0) or 0) + 1,
    )


@dataclass(frozen=True)
class FieldDecl:
    name: str
    annotation: ast.expr
    line: int
    col: int


@dataclass(frozen=True)
class AccountDecl:
    name: str
    fields: list[FieldDecl]
    line: int
    col: int
    file: str = ""


@dataclass(frozen=True)
class StructDecl:
    """A fixed-layout value. It has no discriminator and is not an account."""

    name: str
    fields: list[FieldDecl]
    line: int
    col: int
    file: str = ""


@dataclass(frozen=True)
class EventDecl:
    """A fixed-width value logged by ``emit``. It is not stored in an account."""

    name: str
    fields: list[FieldDecl]
    line: int
    col: int
    file: str = ""


@dataclass(frozen=True)
class MemberDecl:
    name: str
    value: int
    line: int
    col: int
    #: Python scalar name when this variant carries a payload. Empty for a unit variant.
    payload: str = ""


@dataclass(frozen=True)
class ErrorDecl:
    name: str
    members: list[MemberDecl]
    line: int
    col: int
    file: str = ""


@dataclass(frozen=True)
class EnumDecl:
    """A unit enum. Each member's value is its declaration index (the Borsh tag)."""

    name: str
    members: list[MemberDecl]
    line: int
    col: int
    file: str = ""


@dataclass(frozen=True)
class ParamDecl:
    name: str
    annotation: ast.expr
    line: int
    col: int


@dataclass(frozen=True)
class InstructionDecl:
    name: str
    params: list[ParamDecl]
    body: list[ast.stmt]
    line: int
    col: int
    file: str = ""


@dataclass(frozen=True)
class HelperDecl:
    """A plain function. It is not an instruction and has no discriminator."""

    name: str
    params: list[ParamDecl]
    returns: ast.expr | None
    body: list[ast.stmt]
    line: int
    col: int
    file: str = ""


@dataclass(frozen=True)
class ProjectImport:
    """One name brought in from a sibling module (``from mod import Name``)."""

    module: str
    name: str
    line: int
    col: int


@dataclass
class Program:
    """Everything the checker/dispatcher needs about one source file."""

    imported: set[str]
    accounts: dict[str, AccountDecl]
    errors: dict[str, ErrorDecl]
    enums: dict[str, EnumDecl]
    instructions: list[InstructionDecl]
    helpers: list[HelperDecl] = field(default_factory=list)
    structs: dict[str, StructDecl] = field(default_factory=dict)
    events: dict[str, EventDecl] = field(default_factory=dict)
    #: File this ``Program`` was collected from. Empty on a merged program.
    source_file: str = ""
    #: ``from sibling import Name`` sites in ``source_file``.
    project_imports: tuple[ProjectImport, ...] = ()
    #: File → names that file imported from project modules. Used after a merge.
    file_imports: dict[str, frozenset[str]] = field(default_factory=dict)


def collect(tree: ast.Module, file: str = "<program>") -> tuple[Program, list[Diagnostic]]:
    """Build the model; diagnostics only for declaration-level conflicts."""
    imported: set[str] = set()
    accounts: dict[str, AccountDecl] = {}
    errors: dict[str, ErrorDecl] = {}
    enums: dict[str, EnumDecl] = {}
    instructions: list[InstructionDecl] = []
    helpers: list[HelperDecl] = []
    structs: dict[str, StructDecl] = {}
    events: dict[str, EventDecl] = {}
    project_imports: list[ProjectImport] = []
    diagnostics: list[Diagnostic] = []

    def _taken(name: str) -> bool:
        return (
            name in accounts
            or name in errors
            or name in enums
            or name in structs
            or name in events
        )

    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "pythsol":
            imported.update(alias.name for alias in stmt.names if alias.name != "*")
        elif (
            isinstance(stmt, ast.ImportFrom)
            and stmt.module
            and not stmt.level
            and stmt.module not in ("pythsol", "__future__")
        ):
            for alias in stmt.names:
                if alias.name == "*" or alias.asname is not None:
                    continue
                project_imports.append(
                    ProjectImport(
                        module=stmt.module,
                        name=alias.name,
                        line=node_line(alias),
                        col=node_col(alias),
                    )
                )
        elif isinstance(stmt, ast.ClassDef):
            dec = stmt.decorator_list[0] if stmt.decorator_list else None
            if isinstance(dec, ast.Name) and dec.id == "account":
                name = stmt.name
                if _taken(name):
                    diagnostics.append(
                        Diagnostic(
                            code=PS2001,
                            message=f"duplicate declaration `{name}`",
                            file=file,
                            line=node_line(stmt),
                            col=node_col(stmt),
                        )
                    )
                accounts[name] = AccountDecl(
                    name=name,
                    fields=_collect_fields(stmt),
                    line=node_line(stmt),
                    col=node_col(stmt),
                    file=file,
                )
            elif isinstance(dec, ast.Name) and dec.id == "error":
                name = stmt.name
                if _taken(name):
                    diagnostics.append(
                        Diagnostic(
                            code=PS2001,
                            message=f"duplicate declaration `{name}`",
                            file=file,
                            line=node_line(stmt),
                            col=node_col(stmt),
                        )
                    )
                errors[name] = ErrorDecl(
                    name=name,
                    members=_collect_members(stmt),
                    line=node_line(stmt),
                    col=node_col(stmt),
                    file=file,
                )
            elif isinstance(dec, ast.Name) and dec.id == "enum":
                name = stmt.name
                if _taken(name):
                    diagnostics.append(
                        Diagnostic(
                            code=PS2001,
                            message=f"duplicate declaration `{name}`",
                            file=file,
                            line=node_line(stmt),
                            col=node_col(stmt),
                        )
                    )
                enums[name] = EnumDecl(
                    name=name,
                    members=_collect_enum_members(stmt),
                    line=node_line(stmt),
                    col=node_col(stmt),
                    file=file,
                )
            elif isinstance(dec, ast.Name) and dec.id == "struct":
                name = stmt.name
                if _taken(name):
                    diagnostics.append(
                        Diagnostic(
                            code=PS2001,
                            message=f"duplicate declaration `{name}`",
                            file=file,
                            line=node_line(stmt),
                            col=node_col(stmt),
                        )
                    )
                structs[name] = StructDecl(
                    name=name,
                    fields=_collect_fields(stmt),
                    line=node_line(stmt),
                    col=node_col(stmt),
                    file=file,
                )
            elif isinstance(dec, ast.Name) and dec.id == "event":
                name = stmt.name
                if _taken(name):
                    diagnostics.append(
                        Diagnostic(
                            code=PS2001,
                            message=f"duplicate declaration `{name}`",
                            file=file,
                            line=node_line(stmt),
                            col=node_col(stmt),
                        )
                    )
                events[name] = EventDecl(
                    name=name,
                    fields=_collect_fields(stmt),
                    line=node_line(stmt),
                    col=node_col(stmt),
                    file=file,
                )
        elif isinstance(stmt, ast.FunctionDef):
            params = []
            for arg in stmt.args.args:
                if arg.annotation is None:  # subset guarantees none-missing
                    continue
                params.append(
                    ParamDecl(
                        name=arg.arg,
                        annotation=arg.annotation,
                        line=node_line(arg),
                        col=node_col(arg),
                    )
                )
            decl_body = _without_docstring(stmt.body)
            if stmt.decorator_list:
                instructions.append(
                    InstructionDecl(
                        name=stmt.name,
                        params=params,
                        body=decl_body,
                        line=node_line(stmt),
                        col=node_col(stmt),
                        file=file,
                    )
                )
            elif stmt.name in _RESERVED_HELPERS:
                diagnostics.append(
                    Diagnostic(
                        code=PS2001,
                        message=f"helper `{stmt.name}` hides a built-in",
                        file=file,
                        line=node_line(stmt),
                        col=node_col(stmt),
                    )
                )
            else:
                helpers.append(
                    HelperDecl(
                        name=stmt.name,
                        params=params,
                        returns=stmt.returns,
                        body=decl_body,
                        line=node_line(stmt),
                        col=node_col(stmt),
                        file=file,
                    )
                )

    # instruction-name conflicts (incl. `an instruction named like an account`)
    seen: dict[str, InstructionDecl | HelperDecl] = {}
    named: list[InstructionDecl | HelperDecl] = [*instructions, *helpers]
    for decl in named:
        if decl.name in seen or _taken(decl.name):
            diagnostics.append(
                Diagnostic(
                    code=PS2001,
                    message=f"name `{decl.name}` is already declared",
                    file=file,
                    line=decl.line,
                    col=decl.col,
                )
            )
        else:
            seen[decl.name] = decl

    brought = tuple(project_imports)
    program = Program(
        imported=imported,
        accounts=accounts,
        errors=errors,
        enums=enums,
        instructions=instructions,
        helpers=helpers,
        structs=structs,
        events=events,
        source_file=file,
        project_imports=brought,
        file_imports={file: frozenset(item.name for item in brought)},
    )
    return program, diagnostics


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """Drop a leading string literal. The emitter never lowered it."""
    if not body:
        return body
    first = body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return body[1:]
    return body


def _collect_fields(cls: ast.ClassDef) -> list[FieldDecl]:
    fields = []
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            line, col = _pos(stmt)
            fields.append(
                FieldDecl(name=stmt.target.id, annotation=stmt.annotation, line=line, col=col)
            )
    return fields


_ENUM_PAYLOADS: frozenset[str] = frozenset(
    {"u8", "u16", "u32", "u64", "i8", "i16", "i32", "i64", "bool"}
)


def _collect_enum_members(cls: ast.ClassDef) -> list[MemberDecl]:
    """Unit variants are ``Name = index``. A payload variant is ``Name: u64``."""
    members: list[MemberDecl] = []
    index = 0
    for stmt in cls.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, int)
            and not isinstance(stmt.value.value, bool)
        ):
            line, col = _pos(stmt)
            members.append(
                MemberDecl(name=stmt.targets[0].id, value=stmt.value.value, line=line, col=col)
            )
            index += 1
            continue
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and isinstance(stmt.annotation, ast.Name)
            and stmt.annotation.id in _ENUM_PAYLOADS
            and stmt.value is None
        ):
            line, col = _pos(stmt)
            members.append(
                MemberDecl(
                    name=stmt.target.id,
                    value=index,
                    line=line,
                    col=col,
                    payload=stmt.annotation.id,
                )
            )
            index += 1
    return members


def _collect_members(cls: ast.ClassDef) -> list[MemberDecl]:
    members = []
    for stmt in cls.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, int)
            and not isinstance(stmt.value.value, bool)
        ):
            line, col = _pos(stmt)
            members.append(
                MemberDecl(name=stmt.targets[0].id, value=stmt.value.value, line=line, col=col)
            )
    return members


def node_line(node: ast.AST) -> int:
    return getattr(node, "lineno", 1) or 1


def node_col(node: ast.AST) -> int:
    return (getattr(node, "col_offset", 0) or 0) + 1
