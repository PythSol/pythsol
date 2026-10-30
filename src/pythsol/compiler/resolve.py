"""Stage 3 — resolve declarations into a small in-memory program model.

After the subset pass has validated shapes, this pass collects:

* the imported surface names,
* ``@account`` classes with their fields,
* ``@error`` classes with their numeric members,
* ``@instruction`` functions with typed params and their bodies.

The model here is intentionally dumb (positions + AST references); the
expression-level *meaning* of annotations is assigned in
:mod:`pythsol.compiler.typecheck`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from pythsol.compiler.diagnostics import PS2001, Diagnostic

__all__ = [
    "AccountDecl",
    "ErrorDecl",
    "FieldDecl",
    "InstructionDecl",
    "MemberDecl",
    "ParamDecl",
    "Program",
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


@dataclass(frozen=True)
class MemberDecl:
    name: str
    value: int
    line: int
    col: int


@dataclass(frozen=True)
class ErrorDecl:
    name: str
    members: list[MemberDecl]
    line: int
    col: int


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


@dataclass
class Program:
    """Everything the checker/dispatcher needs about one source file."""

    imported: set[str]
    accounts: dict[str, AccountDecl]
    errors: dict[str, ErrorDecl]
    instructions: list[InstructionDecl]


def collect(tree: ast.Module, file: str = "<program>") -> tuple[Program, list[Diagnostic]]:
    """Build the model; diagnostics only for declaration-level conflicts."""
    imported: set[str] = set()
    accounts: dict[str, AccountDecl] = {}
    errors: dict[str, ErrorDecl] = {}
    instructions: list[InstructionDecl] = []
    diagnostics: list[Diagnostic] = []

    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "pythsol":
            imported.update(alias.name for alias in stmt.names if alias.name != "*")
        elif isinstance(stmt, ast.ClassDef):
            dec = stmt.decorator_list[0] if stmt.decorator_list else None
            if isinstance(dec, ast.Name) and dec.id == "account":
                name = stmt.name
                if name in accounts or name in errors:
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
                )
            elif isinstance(dec, ast.Name) and dec.id == "error":
                name = stmt.name
                if name in accounts or name in errors:
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
            instructions.append(
                InstructionDecl(
                    name=stmt.name,
                    params=params,
                    body=stmt.body,
                    line=node_line(stmt),
                    col=node_col(stmt),
                )
            )

    # instruction-name conflicts (incl. `an instruction named like an account`)
    seen: dict[str, InstructionDecl] = {}
    for decl in instructions:
        if decl.name in seen or decl.name in accounts or decl.name in errors:
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

    program = Program(
        imported=imported,
        accounts=accounts,
        errors=errors,
        instructions=instructions,
    )
    return program, diagnostics


def _collect_fields(cls: ast.ClassDef) -> list[FieldDecl]:
    fields = []
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            line, col = _pos(stmt)
            fields.append(
                FieldDecl(name=stmt.target.id, annotation=stmt.annotation, line=line, col=col)
            )
    return fields


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
