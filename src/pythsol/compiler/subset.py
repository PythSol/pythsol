"""Stage 2 — enforce the typed Python subset structurally.

This pass only looks at *shapes*: statements, literals, calls, imports,
annotations and decorators. Name/type resolution happens later
(:mod:`pythsol.compiler.resolve`, :mod:`pythsol.compiler.typecheck`) so that
this stage stays parse-shaped and deterministic.

Every rejection references a stable ``PS1xxx`` code; an unknown construct is
always rejected (never silently accepted), which is also what makes the fuzzer
in ``tests/test_phase2_fuzz.py`` crash-free.
"""

from __future__ import annotations

import ast
from pathlib import Path

from pythsol.compiler.diagnostics import (
    PS1001,
    PS1002,
    PS1003,
    PS1004,
    PS1005,
    PS1006,
    PS1007,
    PS1008,
    PS1009,
    PS1010,
    PS1011,
    PS1012,
    PS2001,
    PS2003,
    PS2004,
    PS2005,
    PS2007,
    PS2008,
    Diagnostic,
)
from pythsol.compiler.parse import parse_source

__all__ = ["PYTHSOL_EXPORTS", "scan_module"]

#: Names a program may import from ``pythsol`` (kept in sync with the DSL
#: surface in ``src/pythsol/__init__.py``; a unit test pins the equality).
PYTHSOL_EXPORTS: frozenset[str] = frozenset(
    {
        *("u8", "u16", "u32", "u64", "u128", "i8", "i16", "i32", "i64", "i128"),
        "Pubkey",
        "Signer",
        "SystemProgram",
        "TokenAccount",
        "TokenMint",
        "ProgramError",
        "Mut",
        "Account",
        "Init",
        "InitIfNeeded",
        "Zeroed",
        "Option",
        "Vec",
        "FixedArray",
        "FixedString",
        "instruction",
        "account",
        "error",
        "enum",
        "struct",
        "event",
        "require",
        "emit",
        "system_transfer",
        "token_transfer",
        "token2022_transfer",
        "ata_create",
        "Seeds",
        "HasOne",
        "CloseTo",
        "Address",
        "Owner",
    }
)

#: Wrappers that may be subscripted in annotations, and their expected arity
#: (number of type arguments; ``None`` means "any").
_CONSTRAINTS: frozenset[str] = frozenset(
    {"Seeds", "HasOne", "CloseTo", "Address", "Owner"}
)

_WRAPPER_ARITY: dict[str, int] = {
    "Mut": 1,
    "Account": 1,
    "Init": 1,
    "InitIfNeeded": 1,
    "Zeroed": 1,
    "Vec": 1,
    "Option": 1,
    "FixedString": 1,
    "FixedArray": 2,
}

#: Types whose *value* form is rejected anywhere in the subset.
_UNVALUEABLE_CONTAINERS: tuple[type[ast.expr], ...] = (
    ast.List,
    ast.Set,
    ast.Dict,
    ast.Tuple,
)

#: Builtin names usable only outside program code.
_BUILTIN_BANNER_TYPES: frozenset[str] = frozenset(
    {"float", "str", "bytes", "list", "dict", "set", "tuple", "frozenset", "object", "type"}
)

_DYNAMIC_EXEC_NAMES: frozenset[str] = frozenset({"__import__", "eval", "exec", "compile"})

_WIDTH_CASTS: frozenset[str] = frozenset(
    {"u8", "u16", "u32", "u64", "u128", "i8", "i16", "i32", "i64", "i128"}
)

#: Names an ``@enum`` class must not take (they are already types).
_ENUM_SHADOW: frozenset[str] = _WIDTH_CASTS | {
    "bool",
    "Pubkey",
    "Signer",
    "Option",
    "Vec",
    "FixedArray",
    "FixedString",
}

_KNOWN_CALLABLES: frozenset[str] = frozenset(
    {
        "require",
        "len",
        "range",
        "emit",
        "system_transfer",
        "token_transfer",
        "token2022_transfer",
        "ata_create",
        *_WIDTH_CASTS,
    }
)

_MAX_COLLECTION_SIZE = 4096


def _seed_text(value: str) -> bool:
    """A PDA seed that can be pasted into a C string without escaping."""
    if not 1 <= len(value.encode("utf-8")) <= 32:
        return False
    return value.isascii() and all(ch.isalnum() or ch == "_" for ch in value)


def _is_str_lit(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _assign_str_ok(stmt: ast.Assign) -> bool:
    """``account.field = "hi"`` may be a FixedString store. ``s = "hi"`` stays PS2004."""
    if not _is_str_lit(stmt.value):
        return False
    return bool(stmt.targets) and all(isinstance(target, ast.Attribute) for target in stmt.targets)


def _is_const_int(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    )


def _ann_str_ok(stmt: ast.AnnAssign) -> bool:
    """``name: FixedString[N] = "hi"`` is the annotated form of the same store."""
    if stmt.value is None or not _is_str_lit(stmt.value):
        return False
    ann = stmt.annotation
    return (
        isinstance(ann, ast.Subscript)
        and isinstance(ann.value, ast.Name)
        and ann.value.id == "FixedString"
    )


def scan_module(
    source: str,
    file: str = "<program>",
    modules: frozenset[str] | None = None,
) -> tuple[ast.Module | None, list[Diagnostic]]:
    """Parse ``source`` and apply the structural subset rules.

    Returns the parsed tree (or ``None`` on a syntax error) and all ``PS1xxx``
    diagnostics in source order. ``modules`` names sibling project modules
    the file may import. ``None`` keeps the single-file rule.
    """

    tree, parse_diags = parse_source(source, file)
    if tree is None:
        return None, parse_diags
    return tree, scan_tree(tree, file, modules)


def scan_tree(
    tree: ast.Module,
    file: str = "<program>",
    modules: frozenset[str] | None = None,
) -> list[Diagnostic]:
    """Apply the structural subset rules to an already-parsed module."""
    checker = _SubsetVisitor(file, modules)
    return checker.run(tree)


class _SubsetVisitor:
    """One source file's structural checks."""

    def __init__(self, file: str, modules: frozenset[str] | None = None) -> None:
        self._file = file
        self._modules = modules
        self._diags: list[Diagnostic] = []
        self._imports: set[str] = set()
        self._helpers: set[str] = set()
        self._events: set[str] = set()
        self._imported: set[str] = set()

    # -- helpers -----------------------------------------------------------

    def _at(
        self,
        node: ast.AST,
        code: str,
        message: str,
        fix: str | None = None,
    ) -> None:
        line = getattr(node, "lineno", 1) or 1
        col = (getattr(node, "col_offset", 0) or 0) + 1
        self._diags.append(
            Diagnostic(code=code, message=message, file=self._file, line=line, col=col, fix=fix)
        )

    def run(self, tree: ast.Module) -> list[Diagnostic]:
        self._helpers = {
            stmt.name
            for stmt in tree.body
            if isinstance(stmt, ast.FunctionDef) and not stmt.decorator_list
        }
        self._events = {
            stmt.name
            for stmt in tree.body
            if isinstance(stmt, ast.ClassDef)
            and len(stmt.decorator_list) == 1
            and isinstance(stmt.decorator_list[0], ast.Name)
            and stmt.decorator_list[0].id == "event"
        }
        for index, stmt in enumerate(tree.body):
            if isinstance(stmt, ast.ImportFrom):
                self._visit_import(stmt)
            elif isinstance(stmt, ast.Import):
                self._at(
                    stmt,
                    PS1001,
                    "plain `import` is not supported; use `from pythsol import ...`",
                )
            elif isinstance(stmt, ast.AsyncFunctionDef):
                self._at(stmt, PS1003, "async functions are not supported")
            elif isinstance(stmt, ast.FunctionDef):
                self._visit_function(stmt, top_level=True)
            elif isinstance(stmt, ast.ClassDef):
                self._visit_class(stmt)
            elif (
                index == 0
                and isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                continue  # module docstring
            else:
                self._at(
                    stmt,
                    PS1003,
                    "modules may only declare instructions, accounts, errors, and enums",
                )
        return self._diags

    # -- imports -----------------------------------------------------------

    def _visit_import(self, stmt: ast.ImportFrom) -> None:
        module = stmt.module
        if module == "__future__":
            for alias in stmt.names:
                if alias.name == "annotations" and alias.asname is None:
                    self._imports.add("annotations")
                else:
                    self._at(alias, PS1001, "unsupported `__future__` import")
            return
        if module != "pythsol" or stmt.level:
            if self._allow_project_import(stmt, module):
                self._visit_project_import(stmt)
                return
            self._at(
                stmt,
                PS1001,
                "only `from pythsol import ...` imports are supported"
                + (f" (got `{module or '.'}`)" if module else " (relative import)"),
            )
            return
        for alias in stmt.names:
            if alias.name == "*" or alias.asname is not None:
                self._at(alias, PS1001, "import aliases and star imports are not supported")
                continue
            if alias.name not in PYTHSOL_EXPORTS:
                self._at(
                    alias,
                    PS1001,
                    f"pythsol does not export `{alias.name}`",
                    fix="see the language reference for the full import list",
                )
                continue
            self._imports.add(alias.name)

    def _allow_project_import(self, stmt: ast.ImportFrom, module: str | None) -> bool:
        """True when ``stmt`` names a sibling module this file may import.

        Single-file checks pass no module set, so every foreign import keeps
        the historical PS1001 at the import statement.
        """
        if self._modules is None or stmt.level or not module or not module.isidentifier():
            return False
        if module == Path(self._file).stem:
            self._at(stmt, PS1001, "a module cannot import itself")
            return True
        return module in self._modules

    def _visit_project_import(self, stmt: ast.ImportFrom) -> None:
        """Record a sibling import. The name is checked once that file is loaded."""
        if stmt.module == Path(self._file).stem:
            return  # diagnostic already reported
        for alias in stmt.names:
            if alias.name == "*" or alias.asname is not None:
                self._at(alias, PS1001, "import aliases and star imports are not supported")
                continue
            self._imported.add(alias.name)

    # -- functions ---------------------------------------------------------

    def _visit_function(self, node: ast.FunctionDef, *, top_level: bool) -> None:
        if not top_level:
            self._at(node, PS1003, "nested functions are not supported")
            return
        self._check_decorator(node)
        self._check_signature(node)
        self._visit_block(node.body, docstring_ok=True)

    def _check_decorator(self, node: ast.FunctionDef) -> None:
        decorators = node.decorator_list
        if not decorators:
            return
        if len(decorators) != 1:
            self._at(decorators[1], PS2008, "only a single `@instruction` decorator is allowed")
            return
        dec = decorators[0]
        if not isinstance(dec, ast.Name):
            self._at(dec, PS2008, "`@instruction` must be applied directly (no dotted/complex)")
            return
        if dec.id != "instruction":
            self._at(dec, PS2008, f"`@{dec.id}` cannot decorate a function; use `@instruction`")
            return
        if "instruction" not in self._imports:
            self._at(dec, PS2008, "`@instruction` used but not imported")

    def _check_signature(self, node: ast.FunctionDef) -> None:
        args = node.args
        if args.posonlyargs:
            self._at(args.posonlyargs[0], PS1005, "positional-only params are not supported")
        if args.vararg is not None:
            self._at(args.vararg, PS1005, "`*args` is not supported")
        if args.kwonlyargs:
            self._at(args.kwonlyargs[0], PS1005, "keyword-only params are not supported")
        if args.kwarg is not None:
            self._at(args.kwarg, PS1005, "`**kwargs` is not supported")
        if args.defaults:
            self._at(args.defaults[0], PS1005, "instruction arguments must not have defaults")
        for default in args.kw_defaults:
            if default is not None:
                self._at(default, PS1005, "instruction arguments must not have defaults")
        if len(args.args) > 16:
            self._at(args.args[16], PS1005, "instructions accept at most 16 accounts/data args")
        for arg in args.args:
            if arg.annotation is None:
                self._at(
                    arg,
                    PS1006,
                    f"argument `{arg.arg}` needs a type annotation",
                    fix=f"`{arg.arg}: u64`",
                )
            else:
                self._check_annotation(arg.annotation)
        if node.returns is None:
            self._at(node, PS1006, "instructions must declare a return type: `-> None`")

    # -- classes -----------------------------------------------------------

    def _visit_class(self, node: ast.ClassDef) -> None:
        decorators = node.decorator_list
        if not decorators:
            self._at(
                node,
                PS1012,
                "classes must be decorated with "
                "`@account`, `@struct`, `@event`, `@error`, or `@enum`",
            )
            return
        if len(decorators) != 1:
            self._at(decorators[1], PS2008, "only a single decorator is allowed on classes")
            return
        dec = decorators[0]
        allowed = ("account", "struct", "event", "error", "enum", "instruction")
        if not isinstance(dec, ast.Name) or dec.id not in allowed:
            self._at(
                dec,
                PS2008,
                "unknown class decorator; use `@account`, `@struct`, "
                "`@event`, `@error`, or `@enum`",
            )
            return
        if dec.id == "instruction":
            self._at(
                dec,
                PS2008,
                "`@instruction` decorates functions; "
                "use `@account`, `@struct`, `@event`, `@error`, or `@enum`",
            )
            return
        if dec.id not in self._imports:
            self._at(dec, PS2008, f"`@{dec.id}` used but not imported")
            return
        if dec.id == "account":
            self._visit_account_class(node)
        elif dec.id == "struct":
            self._visit_struct_class(node)
        elif dec.id == "event":
            self._visit_event_class(node)
        elif dec.id == "error":
            self._visit_error_class(node)
        else:
            self._visit_enum_class(node)

    def _visit_account_class(self, node: ast.ClassDef) -> None:
        if node.bases or node.keywords:
            self._at(node, PS1012, "`@account` classes must not inherit from anything")
        self._visit_class_body(
            node,
            allow_annassign=True,
            allow_assign=False,
            message="account fields are annotated declarations: `field: u64`",
        )

    def _visit_struct_class(self, node: ast.ClassDef) -> None:
        if node.bases or node.keywords:
            self._at(node, PS1012, "`@struct` classes must not inherit from anything")
        self._visit_class_body(
            node,
            allow_annassign=True,
            allow_assign=False,
            message="struct fields are annotated declarations: `field: u64`",
        )
        if not any(isinstance(stmt, ast.AnnAssign) for stmt in node.body):
            self._at(node, PS1012, "structs need at least one field")

    def _visit_event_class(self, node: ast.ClassDef) -> None:
        if node.bases or node.keywords:
            self._at(node, PS1012, "`@event` classes must not inherit from anything")
        self._visit_class_body(
            node,
            allow_annassign=True,
            allow_assign=False,
            message="event fields are annotated declarations: `field: u64`",
        )

    def _visit_error_class(self, node: ast.ClassDef) -> None:
        if len(node.bases) != 1:
            self._at(node, PS1012, "`@error` classes must extend `ProgramError` exactly once")
        elif not isinstance(node.bases[0], ast.Name) or node.bases[0].id != "ProgramError":
            self._at(node.bases[0], PS1012, "`@error` classes must extend `ProgramError`")
        self._visit_class_body(
            node,
            allow_annassign=False,
            allow_assign=True,
            message="error members are plain assignments: `Member = <int constant>`",
        )

    def _visit_enum_class(self, node: ast.ClassDef) -> None:
        if node.bases or node.keywords:
            self._at(node, PS1012, "`@enum` classes must not inherit")
        if node.name in _ENUM_SHADOW:
            self._at(node, PS2001, f"enum name `{node.name}` shadows a built-in type")
        count = self._visit_enum_body(node)
        if count == 0:
            self._at(node, PS1012, "enums need at least one variant")

    def _visit_class_body(
        self,
        node: ast.ClassDef,
        *,
        allow_annassign: bool,
        allow_assign: bool,
        message: str,
        assign_kind: str = "error",
    ) -> int:
        seen: set[str] = set()
        assigns = 0
        for index, stmt in enumerate(node.body):
            if (
                index == 0
                and isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                continue  # class docstring
            if isinstance(stmt, ast.FunctionDef):
                self._at(stmt, PS1012, "methods are not supported inside DSL classes")
                continue
            if isinstance(stmt, ast.AnnAssign):
                if not allow_annassign:
                    self._at(stmt, PS1012, message)
                    continue
                self._check_class_field(stmt, seen)
                continue
            if isinstance(stmt, ast.Assign):
                if not allow_assign:
                    self._at(stmt, PS1012, message)
                    continue
                if assign_kind == "enum":
                    self._check_enum_member(stmt, seen, assigns)
                else:
                    self._check_error_member(stmt, seen)
                assigns += 1
                continue
            if isinstance(stmt, ast.Pass):
                continue
            self._at(stmt, PS1012, "unsupported statement inside a DSL class body")
        return assigns

    def _check_class_field(self, stmt: ast.AnnAssign, seen: set[str]) -> None:
        if not isinstance(stmt.target, ast.Name):
            self._at(stmt, PS2005, "account fields must be plain names")
            return
        name = stmt.target.id
        if name in seen:
            self._at(stmt, PS2001, f"duplicate field `{name}`")
        seen.add(name)
        if stmt.value is not None:
            self._at(stmt, PS1012, "account fields cannot have initializers")
        self._check_annotation(stmt.annotation)

    def _check_error_member(self, stmt: ast.Assign, seen: set[str]) -> None:
        target = stmt.targets[0] if stmt.targets else None
        if stmt.targets and len(stmt.targets) != 1:
            self._at(stmt, PS1012, "assign one error member at a time")
            return
        if not isinstance(target, ast.Name):
            self._at(stmt, PS2005, "error members must be plain names")
            return
        if target.id in seen:
            self._at(stmt, PS2001, f"duplicate member `{target.id}`")
        seen.add(target.id)
        value = stmt.value
        if (
            not isinstance(value, ast.Constant)
            or isinstance(value.value, bool)
            or not isinstance(value.value, int)
        ):
            self._visit_expr(value)
            self._at(
                target,
                PS1012,
                "error members must be integer constants",
                fix="`Unauthorized = 100`",
            )
            return
        if not 0 <= value.value < 2**32:
            self._at(value, PS2007, f"error code {value.value} must fit in u32")

    def _visit_enum_body(self, node: ast.ClassDef) -> int:
        """``Name = index`` is a unit variant. ``Name: u64`` carries that scalar."""
        seen: set[str] = set()
        count = 0
        for index, stmt in enumerate(node.body):
            if (
                index == 0
                and isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                continue
            if isinstance(stmt, ast.FunctionDef):
                self._at(stmt, PS1012, "methods are not supported inside DSL classes")
                continue
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.AnnAssign):
                self._check_enum_payload(stmt, seen)
                count += 1
                continue
            if isinstance(stmt, ast.Assign):
                self._check_enum_member(stmt, seen, count)
                count += 1
                continue
            self._at(stmt, PS1012, "unsupported statement inside a DSL class body")
        return count

    def _check_enum_payload(self, stmt: ast.AnnAssign, seen: set[str]) -> None:
        if not isinstance(stmt.target, ast.Name):
            self._at(stmt, PS2005, "enum variants must be plain names")
            return
        if stmt.target.id in seen:
            self._at(stmt, PS2001, f"duplicate variant `{stmt.target.id}`")
        seen.add(stmt.target.id)
        if stmt.value is not None:
            self._at(stmt, PS1012, "a payload variant has no initializer; the tag is its index")
        ann = stmt.annotation
        if not isinstance(ann, ast.Name) or ann.id not in {
            "u8",
            "u16",
            "u32",
            "u64",
            "i8",
            "i16",
            "i32",
            "i64",
            "bool",
        }:
            self._at(
                ann,
                PS2007,
                "a data-enum payload must be one scalar (u8..u64, i8..i64, or bool)",
            )

    def _check_enum_member(self, stmt: ast.Assign, seen: set[str], index: int) -> None:
        target = stmt.targets[0] if stmt.targets else None
        if stmt.targets and len(stmt.targets) != 1:
            self._at(stmt, PS1012, "assign one enum variant at a time")
            return
        if not isinstance(target, ast.Name):
            self._at(stmt, PS2005, "enum variants must be plain names")
            return
        if target.id in seen:
            self._at(stmt, PS2001, f"duplicate variant `{target.id}`")
        seen.add(target.id)
        value = stmt.value
        if (
            not isinstance(value, ast.Constant)
            or isinstance(value.value, bool)
            or not isinstance(value.value, int)
        ):
            self._visit_expr(value)
            self._at(
                target,
                PS1012,
                "unit variants are `Name = <index>`; a payload variant is `Name: u64`",
            )
            return
        if index > 255:
            self._at(
                value,
                PS2007,
                f"unit enums have at most 256 variants; `{target.id}` is past u8",
            )
            return
        if value.value != index:
            self._at(
                value,
                PS2007,
                f"enum variant `{target.id}` must be tag {index} (declaration index)",
            )

    # -- annotations -------------------------------------------------------

    def _check_annotation(self, node: ast.expr) -> None:
        if isinstance(node, ast.Name):
            name = node.id
            if name == "int":
                self._at(
                    node,
                    PS2003,
                    "`int` is not allowed; use a fixed width (`u64`, `i32`, ...)",
                )
            elif name in _BUILTIN_BANNER_TYPES or name == "Any":
                self._at(
                    node,
                    PS1007,
                    f"`{name}` is not a valid PythSol type annotation",
                )
            elif name == "NoneType" or name == "None":
                self._at(node, PS2001, "`None` is not a valid annotation")
            # anything else is resolved later (account classes, wrapper names)
            return
        if isinstance(node, ast.Attribute):
            self._at(node, PS2001, "dotted annotations are not supported")
            return
        if isinstance(node, ast.Subscript):
            self._check_subscript_annotation(node)
            return
        self._at(node, PS2001, "unsupported annotation form")

    def _check_subscript_annotation(self, node: ast.Subscript) -> None:
        base = node.value
        if not isinstance(base, ast.Name):
            self._at(node, PS2001, "unsupported generic annotation")
            return
        base_name = base.id
        if base_name == "Vec":
            items = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
            if len(items) not in (1, 2):
                self._at(
                    node,
                    PS2007,
                    f"`Vec` takes 1 or 2 type arguments, got {len(items)}",
                )
                return
            self._check_annotation(items[0])
            if len(items) == 2:
                self._check_size(items[1])
            return
        if base_name in ("list", "dict", "set", "tuple", "frozenset"):
            self._at(
                node,
                PS1007,
                f"unbounded container `{base_name}`; use FixedArray/Vec with explicit sizes",
            )
            return
        if base_name in _CONSTRAINTS:
            self._check_constraint_annotation(node, base_name)
            return
        if base_name not in _WRAPPER_ARITY:
            self._at(node, PS2001, f"unknown wrapper `{base_name}`")
            return
        expected = _WRAPPER_ARITY[base_name]
        items = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if expected != len(items):
            self._at(
                node,
                PS2007,
                f"`{base_name}` takes {expected} type argument(s), got {len(items)}",
            )
            return
        data_slots = items if base_name != "FixedArray" else items[:1]
        size_slots = items[1:] if base_name in ("FixedArray", "FixedString") else []
        if base_name == "FixedString":
            size_slots, data_slots = items, []
        for slot in data_slots:
            self._check_annotation(slot)
        for slot in size_slots:
            self._check_size(slot)

    def _check_constraint_annotation(self, node: ast.Subscript, name: str) -> None:
        """``HasOne[Mut[T], "field"]`` and the other account constraints."""
        items = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if len(items) != 2:
            self._at(node, PS2007, f"`{name}` takes an account wrapper and one argument")
            return
        self._check_annotation(items[0])
        arg = items[1]
        if name in ("Seeds", "HasOne"):
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value:
                if name == "Seeds" and _seed_text(arg.value):
                    return
                if name == "HasOne" and arg.value.isidentifier():
                    return
            if name == "Seeds":
                self._at(
                    arg,
                    PS2007,
                    "`Seeds` needs a 1..32 byte string of letters, digits, or `_`",
                )
            else:
                self._at(arg, PS2007, '`HasOne` needs the field name as a string, `"authority"`')
            return
        if not isinstance(arg, ast.Name):
            self._at(arg, PS2007, f"`{name}` needs the name of another parameter")

    def _check_size(self, slot: ast.expr) -> None:
        if not isinstance(slot, ast.Constant):
            self._at(slot, PS2007, "array/string sizes must be integer literals")
            return
        value = slot.value
        if isinstance(value, bool) or not isinstance(value, int):
            self._at(slot, PS2007, "array/string sizes must be integer literals")
            return
        if not 1 <= value <= _MAX_COLLECTION_SIZE:
            self._at(slot, PS2007, f"size {value} outside 1..{_MAX_COLLECTION_SIZE}")

    # -- statements --------------------------------------------------------

    def _visit_block(self, stmts: list[ast.stmt], *, docstring_ok: bool) -> None:
        for index, stmt in enumerate(stmts):
            if isinstance(stmt, ast.Expr):
                value = stmt.value
                if (
                    index == 0
                    and docstring_ok
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    continue  # function docstring
                if isinstance(value, ast.Call):
                    self._visit_expr(value)
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    self._at(value, PS2004, "bare strings are not valid expressions")
                    continue
                self._at(stmt, PS1003, "expression statements must be calls")
                continue
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    self._visit_store_target(target)
                self._visit_expr(stmt.value, str_ok=_assign_str_ok(stmt))
                continue
            if isinstance(stmt, ast.AnnAssign):
                self._visit_store_target(stmt.target)
                self._check_annotation(stmt.annotation)
                if stmt.value is not None:
                    self._visit_expr(stmt.value, str_ok=_ann_str_ok(stmt))
                continue
            if isinstance(stmt, ast.AugAssign):
                self._visit_store_target(stmt.target)
                self._visit_expr(stmt.value)
                continue
            if isinstance(stmt, ast.Return):
                if stmt.value is not None:
                    self._visit_expr(stmt.value)
                continue
            if isinstance(stmt, (ast.Break, ast.Continue, ast.Pass)):
                continue
            if isinstance(stmt, ast.If):
                self._visit_expr(stmt.test)
                self._visit_block(stmt.body, docstring_ok=False)
                self._visit_block(stmt.orelse, docstring_ok=False)
                continue
            if isinstance(stmt, ast.While):
                self._visit_expr(stmt.test)
                self._visit_block(stmt.body, docstring_ok=False)
                self._visit_block(stmt.orelse, docstring_ok=False)
                continue
            if isinstance(stmt, ast.For):
                if not isinstance(stmt.target, ast.Name):
                    self._at(stmt, PS2005, "loop variables must be plain names")
                self._visit_expr(stmt.iter)
                self._visit_block(stmt.body, docstring_ok=False)
                self._visit_block(stmt.orelse, docstring_ok=False)
                continue
            if isinstance(stmt, ast.Match):
                self._visit_match(stmt)
                continue
            if isinstance(stmt, ast.FunctionDef):
                self._visit_function(stmt, top_level=False)
                continue
            name = type(stmt).__name__
            self._at(stmt, PS1003, f"unsupported statement: {name}")

    def _visit_match(self, stmt: ast.Match) -> None:
        self._visit_expr(stmt.subject)
        for case in stmt.cases:
            if case.guard is not None:
                self._at(case.guard, PS1003, "match guards are not supported")
                self._visit_expr(case.guard)
            self._visit_match_pattern(case.pattern)
            self._visit_block(case.body, docstring_ok=False)

    def _visit_match_pattern(self, pattern: ast.pattern) -> None:
        if isinstance(pattern, ast.MatchAs) and pattern.pattern is None and pattern.name is None:
            return
        if isinstance(pattern, ast.MatchValue) and isinstance(pattern.value, ast.Attribute):
            self._visit_expr(pattern.value)
            return
        self._at(pattern, PS1003, "match cases must be `Enum.Variant` or `_`")

    def _visit_store_target(self, target: ast.expr) -> None:
        if isinstance(target, (ast.Name, ast.Attribute)):
            self._visit_expr(target)
            return
        if isinstance(target, ast.Subscript):
            self._visit_expr(target)
            return
        if isinstance(target, ast.Starred):
            self._at(target, PS1005, "star targets are not supported")
            return
        self._at(target, PS2005, f"cannot assign to `{type(target).__name__}` here")

    # -- expressions -------------------------------------------------------

    def _visit_expr(self, node: ast.expr, *, str_ok: bool = False) -> None:
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or value is None or isinstance(value, int):
                return
            if isinstance(value, (float, complex)):
                self._at(node, PS1002, f"`{value!r}` is not allowed; use fixed-width integers")
                return
            if isinstance(value, str):
                if str_ok:
                    return
                self._at(node, PS2004, "string literals are not part of the program surface")
                return
            self._at(node, PS2004, f"`{type(value).__name__}` literals are unsupported")
            return
        if isinstance(node, ast.Name):
            return  # resolution is typecheck's job
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Call):
                self._at(node, PS1008, "cannot read attributes off call results")
            else:
                self._visit_expr(node.value)
            return
        if isinstance(node, ast.Call):
            self._visit_call(node)
            return
        if isinstance(node, ast.BoolOp):
            for operand in node.values:
                self._visit_expr(operand)
            return
        if isinstance(node, ast.UnaryOp):
            self._visit_expr(node.operand)
            return
        if isinstance(node, ast.BinOp):
            self._visit_expr(node.left)
            self._visit_expr(node.right)
            return
        if isinstance(node, ast.Compare):
            self._visit_expr(node.left)
            comparators = list(node.comparators)
            for op, right in zip(node.ops, comparators, strict=True):
                self._visit_expr(right)
                if isinstance(op, (ast.Is, ast.IsNot)):
                    self._at(right, PS1009, "`is`/`is not` is unsupported; use `==`/`!=`")
                elif isinstance(op, (ast.In, ast.NotIn)):
                    self._at(right, PS1009, "`in`/`not in` is unsupported in the subset")
            return
        if isinstance(node, ast.IfExp):
            self._visit_expr(node.test)
            self._visit_expr(node.body)
            self._visit_expr(node.orelse)
            return
        if isinstance(node, ast.Subscript):
            self._visit_expr(node.value)
            slice_ = node.slice
            if isinstance(slice_, ast.Slice):
                self._at(slice_, PS1003, "slices are not supported in phase 2")
                return
            if isinstance(slice_, ast.Tuple):
                self._at(node, PS1003, "multi-index subscripts are not supported")
                return
            self._visit_expr(slice_)
            return
        if isinstance(node, _UNVALUEABLE_CONTAINERS):
            self._at(node, PS2004, f"`{type(node).__name__.lower()}` literals are unsupported")
            return
        if isinstance(node, (ast.Lambda, ast.NamedExpr, ast.Yield, ast.YieldFrom, ast.Await)):
            self._at(node, PS1003, f"unsupported expression: {type(node).__name__}")
            return
        if isinstance(node, ast.Starred):
            self._at(node, PS1005, "*unpacking is not supported")
            return
        if isinstance(node, (ast.JoinedStr, ast.FormattedValue)):
            self._at(node, PS1003, "f-strings are not supported in phase 2")
            return
        if isinstance(node, ast.ListComp):
            self._visit_listcomp(node)
            return
        if isinstance(node, (ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            self._at(node, PS1011, "only list comprehensions are supported")
            return
        if isinstance(node, ast.Slice):
            self._at(node, PS1003, "slice expressions are not supported")
            return
        self._at(node, PS1003, f"unsupported expression: {type(node).__name__}")

    def _visit_listcomp(self, node: ast.ListComp) -> None:
        """A list comprehension is a fixed-size array initializer.

        Allowed shape: ``[expr for name in range(<int literal>)]``. The length
        must be a compile-time constant so the result can be a FixedArray.
        """
        if len(node.generators) != 1:
            self._at(node, PS1011, "a list comprehension takes exactly one `for` clause")
            return
        gen = node.generators[0]
        if gen.is_async:
            self._at(node, PS1011, "async comprehensions are not supported")
            return
        if gen.ifs:
            self._at(gen.ifs[0], PS1011, "comprehension `if` filters are not supported")
            return
        if not isinstance(gen.target, ast.Name):
            self._at(gen.target, PS1011, "the comprehension variable must be a plain name")
            return
        it = gen.iter
        if not (
            isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"
        ):
            self._at(it, PS1011, "a list comprehension iterates `range(<int literal>)`")
            return
        if len(it.args) != 1 or not _is_const_int(it.args[0]):
            self._at(it, PS1011, "comprehension range takes one integer literal")
            return
        self._visit_expr(node.elt)

    def _visit_call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id == "emit":
            self._visit_emit(node)
            return
        if isinstance(func, ast.Name):
            if func.id in self._events:
                self._at(func, PS1010, f"`{func.id}` is an event; write emit({func.id}(...))")
            elif func.id in _DYNAMIC_EXEC_NAMES:
                self._at(func, PS1004, f"`{func.id}()` is forbidden in program code")
            elif (
                func.id not in _KNOWN_CALLABLES
                and func.id not in self._helpers
                and func.id not in self._imported
            ):
                self._at(
                    func,
                    PS1010,
                    f"unknown function `{func.id}`; supported: require, len, range, "
                    "width casts such as u64(x), emit(Event(...)), system_transfer, "
                    "and plain helper functions",
                )
        elif isinstance(func, ast.Attribute):
            self._at(func, PS1010, "method calls are not supported in the subset")
            self._visit_expr(func.value)
        else:
            self._at(func, PS1010, "unsupported call target")
            self._visit_expr(func)
        for arg in node.args:
            self._visit_expr(arg)
        for keyword in node.keywords:
            self._at(keyword.value, PS1003, "keyword arguments are not supported")

    def _visit_emit(self, node: ast.Call) -> None:
        """``emit(Event(...))`` is the only place an event constructor is legal."""
        if node.keywords:
            for keyword in node.keywords:
                self._at(keyword.value, PS1003, "keyword arguments are not supported")
        if len(node.args) != 1 or node.keywords:
            self._at(node, PS1010, "emit() takes one event: emit(Name(...))")
            for arg in node.args:
                self._visit_expr(arg)
            return
        arg = node.args[0]
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
            # Any `Name(...)` has the event shape. Typecheck names the event.
            if arg.keywords:
                for keyword in arg.keywords:
                    self._at(keyword.value, PS1003, "keyword arguments are not supported")
            for inner in arg.args:
                self._visit_expr(inner)
            return
        self._at(node, PS1010, "emit() takes one event: emit(Name(...))")
        self._visit_expr(arg)
