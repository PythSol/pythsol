"""Stage 4 — expression-level type checking over the resolved program model.

Inputs are assumed subset-clean (stage 2 guarantees shapes: no banned
literals/statements/operators, unknown callees already rejected). On top of
the structural pass this stage computes:

* fixed-width integer types and **value range checks** for constants,
* wrapper semantics (``Mut[X]`` writable, ``Account[X]`` read-only),
* field access against ``@account`` layouts (unknown fields are errors),
* ``require(cond, Err.Member)`` call validation,
* cross-instruction checks: duplicate ``Init`` per account and mutable
  aliasing of the same account twice in one instruction (a constraint
  wrapper is peeled, so ``HasOne[Mut[T], ...]`` still counts);
* ``emit(Event(...))`` for ``@event`` values (integers, bool, Pubkey,
  unit enums).

Arithmetic widens to the larger operand width; storing a wider value into a
narrower one is rejected (``PS2007``) instead of silently truncating. Phase 4
formalizes overflow-checked casts on top of this rule.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from pythsol.compiler.diagnostics import (
    PS1003,
    PS1008,
    PS1010,
    PS2000,
    PS2001,
    PS2004,
    PS2006,
    PS2007,
    PS3000,
    PS3001,
    Diagnostic,
)
from pythsol.compiler.resolve import (
    HelperDecl,
    InstructionDecl,
    ParamDecl,
    Program,
    StructDecl,
)

__all__ = ["TInt", "Ty", "check_program"]

#: How many helper frames may sit on one call chain (TR-LANG-08).
_MAX_HELPER_DEPTH = 8

_WIDTHS: dict[str, tuple[int, bool]] = {
    name: (int(name[1:]), False) for name in ("u8", "u16", "u32", "u64", "u128")
}
_WIDTHS.update({name: (int(name[1:]), True) for name in ("i8", "i16", "i32", "i64", "i128")})

#: Names that may appear in annotations but are not data types.
_NOT_VALUE_NAMES: frozenset[str] = frozenset(
    {
        *_WIDTHS,
        "bool",
        "Pubkey",
        "Signer",
        "SystemProgram",
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
        "TokenAccount",
        "TokenMint",
        "Seeds",
        "HasOne",
        "CloseTo",
        "Address",
        "Owner",
    }
)

_CONSTRAINTS: frozenset[str] = frozenset(
    {"Seeds", "HasOne", "CloseTo", "Address", "Owner"}
)

_MAX_EXPONENT = 4096  # guards constant folding `2 ** 999999`


@dataclass(frozen=True)
class TyUnknown:
    """Suppresses follow-up errors after a root-cause diagnostic."""


@dataclass(frozen=True)
class TInt:
    """A fixed-width integer. ``width=None`` is an (unbounded) literal."""

    width: int | None = None
    value: int | None = None
    signed: bool = False


@dataclass(frozen=True)
class TBool:
    pass


@dataclass(frozen=True)
class TNone:
    pass


@dataclass(frozen=True)
class TPubkey:
    is_signer: bool = False


@dataclass(frozen=True)
class TSysProg:
    """`system_program` presence marker."""


@dataclass(frozen=True)
class TAccountRef:
    name: str
    mutable: bool


@dataclass(frozen=True)
class TErrorClassRef:
    """Bare name of an ``@error`` class (usable only before ``.Member``)."""

    name: str


@dataclass(frozen=True)
class TErrorMember:
    owner: str


@dataclass(frozen=True)
class TEnum:
    """A unit-enum type: a field, local, or instruction argument."""

    name: str


@dataclass(frozen=True)
class TEnumRef:
    """Bare ``@enum`` class name, usable only before ``.Variant``."""

    name: str


@dataclass(frozen=True)
class TEnumVal:
    """One variant. ``tag`` is the Borsh discriminant (the declaration index)."""

    enum: str
    variant: str
    tag: int


@dataclass(frozen=True)
class TFixedArray:
    elt: Ty
    size: int


@dataclass(frozen=True)
class TStr:
    """A string literal. ``nbytes`` is the UTF-8 length, not the code-point count."""

    nbytes: int


@dataclass(frozen=True)
class TFixedString:
    size: int


@dataclass(frozen=True)
class TOption:
    """Fixed-width optional. The wire form is a tag byte plus ``elt`` reserved."""

    elt: Ty


@dataclass(frozen=True)
class TStruct:
    """A ``@struct`` value nested in an account. The layout is fixed-width."""

    name: str


@dataclass(frozen=True)
class TVec:
    """``Vec[T]`` is unbounded and rejected later. ``Vec[T, N]`` reserves ``N`` slots."""

    elt: Ty
    cap: int = 0


Ty = (
    TyUnknown
    | TInt
    | TBool
    | TNone
    | TPubkey
    | TSysProg
    | TAccountRef
    | TErrorClassRef
    | TErrorMember
    | TEnum
    | TEnumRef
    | TEnumVal
    | TFixedArray
    | TStr
    | TFixedString
    | TOption
    | TStruct
    | TVec
)


def _event_value(ty: Ty) -> bool:
    """Event payloads are fixed-width scalars. Options and strings stay in accounts."""
    if isinstance(ty, TInt):
        return ty.width is not None
    if isinstance(ty, (TBool, TEnum)):
        return True
    return isinstance(ty, TPubkey) and not ty.is_signer


def _block_returns(stmts: list[ast.stmt]) -> bool:
    """True when the instruction body has a Python ``return`` (success path)."""
    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            return True
        nested: list[list[ast.stmt]] = []
        if isinstance(stmt, (ast.If, ast.While, ast.For)):
            nested = [stmt.body, stmt.orelse]
        elif isinstance(stmt, ast.Match):
            nested = [case.body for case in stmt.cases]
        for block in nested:
            if _block_returns(block):
                return True
    return False


def check_program(program: Program, file: str = "<program>") -> list[Diagnostic]:
    """Type-check every instruction of ``program``; returns diagnostics."""
    return TypeChecker(program, file).run()


class TypeChecker:
    """Per-program type checker/semantic validator."""

    def __init__(self, program: Program, file: str) -> None:
        self._program = program
        self._file = file
        self._diags: list[Diagnostic] = []
        self._origins: dict[str, str] = {}
        for account in program.accounts.values():
            self._origins[account.name] = account.file or file
        for error in program.errors.values():
            self._origins[error.name] = error.file or file
        for enum in program.enums.values():
            self._origins[enum.name] = enum.file or file
        for struct in program.structs.values():
            self._origins[struct.name] = struct.file or file
        for event in program.events.values():
            self._origins[event.name] = event.file or file
        for helper in program.helpers:
            self._origins[helper.name] = helper.file or file
        for instr in program.instructions:
            self._origins[instr.name] = instr.file or file
        # account name -> field types, for attribute resolution
        self._fields: dict[str, dict[str, Ty]] = {
            account.name: {} for account in program.accounts.values()
        }
        for account in program.accounts.values():
            with self._in_file(account.file):
                for field in account.fields:
                    self._fields[account.name][field.name] = self._field_type(field.annotation)
        self._struct_fields: dict[str, dict[str, Ty]] = {
            struct.name: {} for struct in program.structs.values()
        }
        for struct in program.structs.values():
            with self._in_file(struct.file):
                for field in struct.fields:
                    self._struct_fields[struct.name][field.name] = self._field_type(
                        field.annotation
                    )
        self._event_fields: dict[str, dict[str, Ty]] = {}
        for event in program.events.values():
            typed: dict[str, Ty] = {}
            with self._in_file(event.file):
                for event_field in event.fields:
                    event_ty = self._field_type(event_field.annotation)
                    if not isinstance(event_ty, TyUnknown) and not _event_value(event_ty):
                        self._at(
                            event_field.annotation,
                            PS3001,
                            "event fields are integers, bool, Pubkey, or unit enums",
                        )
                        event_ty = TyUnknown()
                    typed[event_field.name] = event_ty
            self._event_fields[event.name] = typed
        self._helpers: dict[str, HelperDecl] = {decl.name: decl for decl in program.helpers}
        self._helper_state: dict[str, str] = {}
        self._helper_sigs: dict[str, tuple[list[Ty], Ty]] = {}
        self._helper_depth = 0
        # ``None`` means the body is an instruction (bare ``return`` only).
        self._fn_return: Ty | None = None

    # -- entry point -------------------------------------------------------

    def run(self) -> list[Diagnostic]:
        self._check_struct_cycles()
        for decl in self._program.helpers:
            self._check_helper(decl)
        self._fn_return = None
        for instr in self._program.instructions:
            with self._in_file(instr.file):
                env = {
                    param.name: self._annotation_type(param.annotation, for_param=True)
                    for param in instr.params
                }
                self._check_constraints(instr, env)
                self._check_block(instr.body, env, loop_depth=0)
        self._cross_instruction_checks()
        return self._diags

    # -- helpers -----------------------------------------------------------

    def _at(self, node: ast.AST, code: str, message: str, fix: str | None = None) -> None:
        line = getattr(node, "lineno", 1) or 1
        col = (getattr(node, "col_offset", 0) or 0) + 1
        self._diags.append(
            Diagnostic(code=code, message=message, file=self._file, line=line, col=col, fix=fix)
        )

    def _in_file(self, file: str) -> _FileScope:
        """Attribute diagnostics to ``file`` while a declaration from it is checked."""
        return _FileScope(self, file)

    def _hidden(self, name: str) -> bool:
        """True when ``name`` is declared in another file and this file did not import it."""
        origin = self._origins.get(name, "")
        if origin == "" or origin == self._file:
            return False
        allowed = self._program.file_imports.get(self._file, frozenset())
        return name not in allowed

    def _present(self, bucket: str, name: str) -> bool:
        table: dict[str, object] = getattr(self._program, bucket)
        if name not in table:
            return False
        return not self._hidden(name)

    # -- annotation -> type ------------------------------------------------

    def _field_type(self, ann: ast.expr) -> Ty:
        ty = self._annotation_type(ann, for_param=False)
        if isinstance(ty, (TAccountRef, TSysProg)):
            self._at(
                ann,
                PS3001,
                "account/SystemProgram types cannot be account fields (phase 2)",
            )
            return TyUnknown()
        if isinstance(ty, TErrorClassRef):
            self._at(ann, PS3001, "error classes are not data types")
            return TyUnknown()
        return ty

    def _annotation_type(self, ann: ast.expr, *, for_param: bool) -> Ty:
        if isinstance(ann, ast.Name):
            name = ann.id
            if name in _WIDTHS:
                bits, signed = _WIDTHS[name]
                return TInt(width=bits, signed=signed)
            if name == "bool":
                return TBool()
            if name == "Pubkey":
                return TPubkey(is_signer=False)
            if name == "Signer":
                return TPubkey(is_signer=True)
            if name == "SystemProgram":
                return TSysProg()
            if name == "TokenAccount":
                return TAccountRef(name="TokenAccount", mutable=True)
            if name == "TokenMint":
                return TAccountRef(name="TokenMint", mutable=False)
            if self._present("enums", ann.id):
                return TEnum(name=ann.id)
            if self._present("structs", ann.id):
                if for_param:
                    self._at(
                        ann,
                        PS3001,
                        f"struct `{ann.id}` is data, not an instruction argument",
                    )
                    return TyUnknown()
                return TStruct(name=ann.id)
            if self._present("events", ann.id):
                self._at(ann, PS3001, f"event `{ann.id}` is logged, not stored")
                return TyUnknown()
            if self._present("accounts", ann.id):
                if for_param:
                    name2 = ann.id
                    self._at(
                        ann,
                        PS3001,
                        f"account parameter `{name2}` needs a wrapper "
                        "(Mut[...], Account[...], Init[...])",
                    )
                else:
                    self._at(
                        ann,
                        PS3001,
                        f"nested account `{ann.id}` fields land in phase 3",
                    )
                return TyUnknown()
            if self._present("errors", ann.id):
                self._at(ann, PS3001, f"error class `{ann.id}` is not a data type")
                return TyUnknown()
            if name in _NOT_VALUE_NAMES:
                self._at(ann, PS3001, f"`{name}` cannot be a data type")
                return TyUnknown()
            self._at(ann, PS2001, f"unknown name `{name}` in annotation")
            return TyUnknown()
        if isinstance(ann, ast.Subscript):
            return self._subscript_annotation_type(ann, for_param=for_param)
        self._at(ann, PS2001, "unsupported annotation form")  # subset-guarded
        return TyUnknown()

    def _subscript_annotation_type(self, ann: ast.Subscript, *, for_param: bool) -> Ty:
        base = ann.value
        if not isinstance(base, ast.Name):
            self._at(ann, PS2001, "unsupported generic annotation")
            return TyUnknown()
        name = base.id
        if name in _CONSTRAINTS:
            return self._constraint_param_type(ann, for_param=for_param)
        if name in ("Mut", "Account", "Init", "InitIfNeeded", "Zeroed"):
            target = self._single_subscript_arg(ann)
            if not isinstance(target, ast.Name):
                self._at(
                    target if target is not None else ann,
                    PS2001,
                    f"`{name}[...]` needs an @account class",
                )
                return TyUnknown()
            if not self._present("accounts", target.id):
                if self._present("errors", target.id):
                    self._at(
                        target,
                        PS3001,
                        f"`{name}[{target.id}]`: error classes are not accounts",
                    )
                elif self._present("enums", target.id):
                    self._at(
                        target,
                        PS3001,
                        f"`{name}[{target.id}]`: enums are data, not accounts",
                    )
                elif self._present("structs", target.id):
                    self._at(
                        target,
                        PS3001,
                        f"`{name}[{target.id}]`: structs are data, not accounts",
                    )
                else:
                    self._at(target, PS2001, f"`{target.id}` is not an @account class")
                return TyUnknown()
            return TAccountRef(name=target.id, mutable=name != "Account")
        if name in ("Option", "FixedString"):
            # Fixed-width, so each is a real instruction argument (exact data_len).
            return self._collection_type(ann)
        if name in ("Vec", "FixedArray"):
            if for_param:
                self._at(ann, PS3001, "collections are not instruction arguments (phase 2)")
                return TyUnknown()
            return self._collection_type(ann)
        self._at(ann, PS2001, f"unknown wrapper `{name}`")
        return TyUnknown()

    def _single_subscript_arg(self, ann: ast.Subscript) -> ast.expr | None:
        if isinstance(ann.slice, ast.Tuple):
            return ann.slice.elts[0] if ann.slice.elts else None
        return ann.slice

    def _collection_type(self, ann: ast.Subscript) -> Ty:
        base = ann.value
        if not isinstance(base, ast.Name):
            return TyUnknown()
        items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        name = base.id
        if name == "FixedString" and len(items) == 1:
            size = self._size_value(items[0])
            return TyUnknown() if size is None else TFixedString(size=size)
        if name == "FixedArray" and len(items) == 2:
            size = self._size_value(items[1])
            inner = self._annotation_type(items[0], for_param=False)
            if size is None or isinstance(inner, TyUnknown):
                return TyUnknown()
            return TFixedArray(elt=inner, size=size)
        if name == "Option" and len(items) == 1:
            inner = self._annotation_type(items[0], for_param=False)
            if isinstance(inner, TyUnknown):
                return TyUnknown()
            if not self._option_inner_ok(inner):
                self._at(
                    ann,
                    PS2006,
                    "Option[T] needs an integer, bool, Pubkey, or unit enum",
                )
                return TyUnknown()
            return TOption(elt=inner)
        if name == "Vec" and len(items) in (1, 2):
            inner = self._annotation_type(items[0], for_param=False)
            if isinstance(inner, TyUnknown):
                return TyUnknown()
            cap = 0
            if len(items) == 2:
                size = self._size_value(items[1])
                if size is None:
                    return TyUnknown()
                cap = size
                if not self._option_inner_ok(inner):
                    self._at(
                        ann,
                        PS2006,
                        "Vec[T, N] needs an integer, bool, Pubkey, or unit enum",
                    )
                    return TyUnknown()
            return TVec(elt=inner, cap=cap)
        self._at(ann, PS2007, f"`{name}` takes a different number of type arguments")
        return TyUnknown()

    def _enum_payload_ty(self, name: str) -> Ty | None:
        decl = self._program.enums.get(name)
        if decl is None:
            return None
        kinds = {member.payload for member in decl.members if member.payload}
        if len(kinds) != 1:
            return None
        py = next(iter(kinds))
        if py == "bool":
            return TBool()
        width = {"u8": 8, "u16": 16, "u32": 32, "u64": 64, "i8": 8, "i16": 16, "i32": 32, "i64": 64}
        bits = width.get(py)
        if bits is None:
            return None
        return TInt(width=bits, signed=py.startswith("i"))

    def _option_inner_ok(self, inner: Ty) -> bool:
        """Scalars only. A nested option or array would still be fixed, but not this slice."""
        if isinstance(inner, TInt):
            return inner.width is not None
        if isinstance(inner, (TBool, TEnum)):
            return True
        return isinstance(inner, TPubkey) and not inner.is_signer

    def _size_value(self, node: ast.expr) -> int | None:
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
        ):
            if 1 <= node.value <= 4096:
                return node.value
            self._at(node, PS2007, f"size {node.value} outside 1..4096")
            return None
        self._at(node, PS2007, "sizes must be integer literals")
        return None

    # -- instruction bodies ------------------------------------------------

    def _check_block(
        self,
        stmts: list[ast.stmt],
        env: dict[str, Ty],
        loop_depth: int,
    ) -> None:
        for stmt in stmts:
            self._check_stmt(stmt, env, loop_depth)

    def _check_stmt(self, stmt: ast.stmt, env: dict[str, Ty], loop_depth: int) -> None:
        if isinstance(stmt, ast.AnnAssign):
            self._check_ann_assign(stmt, env)
            return
        if isinstance(stmt, ast.Assign):
            value_ty = self._type_of(stmt.value, env)
            for target in stmt.targets:
                self._check_assign_target(target, env, value_ty, stmt.value)
            return
        if isinstance(stmt, ast.AugAssign):
            target_ty = self._aug_target_type(stmt.target, env)
            value_ty = self._type_of(stmt.value, env)
            self._coerce_aug_assign(stmt, target_ty, value_ty)
            return
        if isinstance(stmt, ast.Return):
            self._check_return(stmt, env)
            return
        if isinstance(stmt, ast.Expr):
            value = stmt.value
            if isinstance(value, ast.Call):
                self._type_of(value, env)
            return
        if isinstance(stmt, ast.If):
            self._require_bool(stmt.test, env, "if condition")
            self._check_block(stmt.body, dict(env), loop_depth)
            self._check_block(stmt.orelse, dict(env), loop_depth)
            return
        if isinstance(stmt, ast.While):
            self._require_bool(stmt.test, env, "while condition")
            self._check_block(stmt.body, dict(env), loop_depth)
            self._check_block(stmt.orelse, dict(env), loop_depth)
            return
        if isinstance(stmt, ast.For):
            self._check_for(stmt, env, loop_depth)
            return
        if isinstance(stmt, ast.Match):
            self._check_match(stmt, env, loop_depth)
            return
        # Break/Continue/Pass: nothing to check (subset validated presence).

    def _check_ann_assign(self, stmt: ast.AnnAssign, env: dict[str, Ty]) -> None:
        target = stmt.target
        if not isinstance(target, ast.Name):  # subset guard
            return
        if target.id in env:
            self._at(target, PS2001, f"`{target.id}` is already declared")
            return
        ty = self._annotation_type(stmt.annotation, for_param=False)
        if isinstance(ty, TStruct):
            self._at(
                stmt.annotation,
                PS2006,
                "a struct is stored in an account field, not a local",
            )
            env[target.id] = TyUnknown()
            return
        env[target.id] = ty
        if stmt.value is not None:
            self._coerce(target, ty, self._type_of(stmt.value, env), at_value=stmt.value)

    def _check_for(self, stmt: ast.For, env: dict[str, Ty], loop_depth: int) -> None:
        target = stmt.target
        if not isinstance(target, ast.Name):  # subset guard
            return
        it = stmt.iter
        var_ty: Ty = TyUnknown()
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range":
            if not 1 <= len(it.args) <= 3:
                self._at(it, PS2006, "range() takes 1-3 arguments")
            for arg in it.args:
                arg_ty = self._type_of(arg, env)
                if not isinstance(arg_ty, (TInt, TyUnknown)):
                    self._at(arg, PS2006, "range() bounds must be integers")
            var_ty = TInt(width=64, signed=False)
        else:
            iter_ty = self._type_of(it, env)
            if isinstance(iter_ty, (TFixedArray, TVec)):
                var_ty = iter_ty.elt
            elif isinstance(iter_ty, TFixedString):
                var_ty = TInt(width=8, signed=False)
            elif not isinstance(iter_ty, TyUnknown):
                self._at(it, PS2006, "only arrays/vectors are iterable (phase 2)")
        if target.id in env:
            self._at(target, PS2001, f"`{target.id}` is already declared")
        env[target.id] = var_ty
        self._check_block(stmt.body, env, loop_depth + 1)
        self._check_block(stmt.orelse, env, loop_depth)

    def _check_assign_target(
        self,
        target: ast.expr,
        env: dict[str, Ty],
        value_ty: Ty,
        value_node: ast.expr,
    ) -> None:
        if isinstance(target, ast.Name):
            if target.id not in env:
                self._at(
                    target,
                    PS2000,
                    f"`{target.id}` is not declared; annotate it (`{target.id}: u8 = ...`)",
                )
                return
            self._coerce(target, env[target.id], value_ty, at_value=value_node)
            return
        if isinstance(target, ast.Attribute):
            self._coerce_field_write(target, env, value_ty, value_node)
            return
        if isinstance(target, ast.Subscript):
            self._check_subscript_store(target, env, value_ty, value_node)
            return

    def _coerce_field_write(
        self,
        target: ast.Attribute,
        env: dict[str, Ty],
        value_ty: Ty,
        value_node: ast.expr,
    ) -> None:
        base = target.value
        if (
            target.attr == "value"
            and isinstance(base, ast.Attribute)
            and isinstance(base.value, ast.Name)
        ):
            field_ty = self._type_of(base, env)
            if isinstance(field_ty, TEnum):
                payload = self._enum_payload_ty(field_ty.name)
                if payload is None:
                    self._at(target, PS2001, f"`{field_ty.name}` has no payload")
                    return
                root = env.get(base.value.id)
                if isinstance(root, TAccountRef) and not root.mutable:
                    self._at(target, PS3001, f"cannot write to read-only `Account[{root.name}]`")
                    return
                self._coerce(target, payload, value_ty, at_value=value_node)
                return
        if not isinstance(base, ast.Name):
            if isinstance(base, ast.Attribute) and self._write_struct_field(
                target, env, value_ty, value_node
            ):
                return
            self._at(target, PS1008, "nested attribute writes are not supported (phase 2)")
            return
        base_ty = env.get(base.id)
        if not isinstance(base_ty, TAccountRef):
            if base_ty is None:
                self._at(base, PS2001, f"unknown name `{base.id}`")
                return
            self._at(target, PS1008, f"cannot write fields of `{self._ty_name(base_ty)}`")
            return
        if not base_ty.mutable:
            self._at(
                target,
                PS3001,
                f"cannot write to read-only `Account[{base_ty.name}]`",
            )
            return
        fields = self._fields.get(base_ty.name, {})
        if target.attr not in fields:
            self._at(
                target,
                PS2001,
                f"account `{base_ty.name}` has no field `{target.attr}`",
            )
            return
        self._coerce(target, fields[target.attr], value_ty, at_value=value_node)

    def _write_struct_field(
        self,
        target: ast.Attribute,
        env: dict[str, Ty],
        value_ty: Ty,
        value_node: ast.expr,
    ) -> bool:
        """Write ``account.struct.leaf``. False when the base is not a struct."""
        leaf = self._struct_leaf_type(target, env)
        if leaf is None:
            return False
        self._coerce(target, leaf, value_ty, at_value=value_node)
        return True

    def _struct_leaf_type(self, target: ast.Attribute, env: dict[str, Ty]) -> Ty | None:
        """Leaf type of a struct field write, or None when the base is not a struct."""
        base = target.value
        if not isinstance(base, ast.Attribute):
            return None
        base_ty = self._type_of(base, env)
        if not isinstance(base_ty, TStruct):
            return None
        root = self._account_root(base, env)
        if root is None:
            self._at(target, PS2006, "a struct field needs an account")
            return TyUnknown()
        if not root.mutable:
            self._at(target, PS3001, f"cannot write to read-only `Account[{root.name}]`")
            return TyUnknown()
        fields = self._struct_fields.get(base_ty.name, {})
        if target.attr not in fields:
            self._at(target, PS2001, f"struct `{base_ty.name}` has no field `{target.attr}`")
            return TyUnknown()
        return fields[target.attr]

    def _account_root(self, node: ast.expr, env: dict[str, Ty]) -> TAccountRef | None:
        current = node
        while isinstance(current, ast.Attribute):
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        ty = env.get(current.id)
        if isinstance(ty, TAccountRef):
            return ty
        return None

    def _check_struct_cycles(self) -> None:
        for name in self._program.structs:
            self._walk_struct(name, [])

    def _walk_struct(self, name: str, stack: list[str]) -> None:
        if name in stack:
            return
        stack.append(name)
        decl = self._program.structs[name]
        with self._in_file(decl.file):
            self._walk_struct_fields(name, decl, stack)

    def _walk_struct_fields(self, name: str, decl: StructDecl, stack: list[str]) -> None:
        for field in decl.fields:
            ty = self._struct_fields.get(name, {}).get(field.name)
            if not isinstance(ty, TStruct):
                continue
            if ty.name in stack:
                self._diags.append(
                    Diagnostic(
                        code=PS2006,
                        message=f"struct `{ty.name}` refers to itself",
                        file=self._file,
                        line=field.line,
                        col=field.col,
                    )
                )
                continue
            self._walk_struct(ty.name, stack)
        stack.pop()

    def _aug_target_type(self, target: ast.expr, env: dict[str, Ty]) -> Ty:
        if isinstance(target, ast.Name):
            if target.id not in env:
                self._at(target, PS2000, f"`{target.id}` is not declared")
                return TyUnknown()
            return env[target.id]
        if isinstance(target, ast.Attribute):
            base = target.value
            if not isinstance(base, ast.Name):
                nested = self._struct_leaf_type(target, env)
                if nested is not None:
                    return nested
                self._at(target, PS1008, "nested attribute writes are not supported (phase 2)")
                return TyUnknown()
            base_ty = env.get(base.id)
            if not isinstance(base_ty, TAccountRef):
                self._at(target, PS1008, f"cannot update fields of `{base.id}`")
                return TyUnknown()
            if not base_ty.mutable:
                self._at(target, PS3001, f"cannot write to read-only `Account[{base_ty.name}]`")
                return TyUnknown()
            fields = self._fields.get(base_ty.name, {})
            if target.attr not in fields:
                self._at(
                    target,
                    PS2001,
                    f"account `{base_ty.name}` has no field `{target.attr}`",
                )
                return TyUnknown()
            return fields[target.attr]
        return TyUnknown()

    # -- coercions ---------------------------------------------------------

    def _coerce_aug_assign(self, stmt: ast.AugAssign, target_ty: Ty, value_ty: Ty) -> None:
        at = stmt.target
        if isinstance(target_ty, TyUnknown) or isinstance(value_ty, TyUnknown):
            return
        if isinstance(target_ty, TInt):
            if isinstance(value_ty, TBool):
                self._at(at, PS2006, "cannot mix `bool` into integer arithmetic")
                return
            if not isinstance(value_ty, TInt):
                self._at(
                    at,
                    PS2006,
                    f"cannot apply `{self._op_name(stmt.op)}` to `{self._ty_name(value_ty)}`",
                )
                return
            out_width, _out_signed = self._widen_ty(
                (target_ty.width, target_ty.signed),
                (value_ty.width, value_ty.signed),
            )
            if (
                value_ty.value is not None
                and target_ty.width is not None
                and not self._fits(target_ty, value_ty.value)
            ):
                lo, hi = self._range(target_ty)
                self._at(
                    stmt.value,
                    PS2007,
                    f"{self._lit(value_ty.value)} does not fit into "
                    f"{self._width_name(target_ty.width, target_ty.signed)} "
                    f"(range {lo}..{hi})",
                )
                return
            op_name = stmt.op.__class__.__name__
            if (
                target_ty.width is not None
                and out_width is not None
                and out_width > target_ty.width
                and op_name not in ("RShift", "BitAnd")
            ):
                self._at(
                    at,
                    PS2007,
                    f"`{self._op_symbol(stmt.op)}` would widen beyond "
                    f"{self._width_name(target_ty.width, target_ty.signed)}; "
                    "use a wider local/field",
                )
            return
        if isinstance(target_ty, TBool):
            self._at(at, PS2006, "`bool` cannot be accumulated")
            return
        self._at(
            at,
            PS2006,
            f"cannot use `{self._ty_name(target_ty)}` as an accumulator",
        )

    def _coerce(
        self,
        at: ast.AST,
        target_ty: Ty,
        value_ty: Ty,
        at_value: ast.AST | None,
    ) -> None:
        if isinstance(target_ty, TyUnknown) or isinstance(value_ty, TyUnknown):
            return
        if isinstance(target_ty, TOption):
            self._coerce_option(at, target_ty, value_ty, at_value)
            return
        if isinstance(value_ty, TNone):
            self._at(at_value or at, PS2006, "`None` is only valid in `return` or `Option[T]`")
            return
        if isinstance(value_ty, TStr) and not isinstance(target_ty, TFixedString):
            self._at(
                at_value or at,
                PS2004,
                "string literals can only be stored in `FixedString[N]`",
            )
            return
        if isinstance(target_ty, TInt):
            if isinstance(value_ty, TInt):
                if value_ty.value is not None and not self._fits(target_ty, value_ty.value):
                    lo, hi = self._range(target_ty)
                    self._at(
                        at_value or at,
                        PS2007,
                        f"{self._lit(value_ty.value)} does not fit into "
                        f"{self._width_name(target_ty.width, target_ty.signed)} "
                        f"(range {lo}..{hi})",
                    )
                    return
                if (
                    value_ty.value is None
                    and value_ty.width is not None
                    and target_ty.width is not None
                    and value_ty.width > target_ty.width
                ):
                    self._at(
                        at_value or at,
                        PS2007,
                        f"assigning {self._width_name(value_ty.width, value_ty.signed)} to "
                        f"{self._width_name(target_ty.width, target_ty.signed)} may truncate",
                    )
                return
            if isinstance(value_ty, TBool):
                self._at(at_value or at, PS2006, "cannot assign `bool` to an integer")
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to an integer",
            )
            return
        if isinstance(target_ty, TBool):
            if isinstance(value_ty, TBool):
                return
            if isinstance(value_ty, TInt):
                self._at(
                    at_value or at,
                    PS2006,
                    "cannot assign an integer to `bool`; write a comparison",
                )
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to `bool`",
            )
            return
        if isinstance(target_ty, TPubkey):
            if isinstance(value_ty, TPubkey):
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to a Pubkey",
            )
            return
        if isinstance(target_ty, TAccountRef):
            if isinstance(value_ty, TAccountRef) and value_ty.name == target_ty.name:
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to account `{target_ty.name}`",
            )
            return
        if isinstance(target_ty, TErrorMember | TErrorClassRef):
            self._at(
                at_value or at,
                PS2006,
                "@error names cannot be stored",
            )
            return
        if isinstance(target_ty, TFixedArray):
            if (
                isinstance(value_ty, TFixedArray)
                and value_ty.size == target_ty.size
                and not isinstance(self._coerce_ty(target_ty.elt, value_ty.elt), TyUnknown)
            ):
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to a fixed array",
            )
            return
        if isinstance(target_ty, TFixedString):
            if isinstance(value_ty, TStr):
                if value_ty.nbytes <= target_ty.size:
                    return
                self._at(
                    at_value or at,
                    PS2007,
                    f"string is {value_ty.nbytes} bytes; `FixedString[{target_ty.size}]` "
                    f"holds {target_ty.size}",
                )
                return
            if isinstance(value_ty, TFixedString) and value_ty.size == target_ty.size:
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to a fixed string",
            )
            return
        if isinstance(target_ty, TVec):
            if isinstance(value_ty, TVec) and not isinstance(
                self._coerce_ty(target_ty.elt, value_ty.elt), TyUnknown
            ):
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to a vector",
            )
            return
        if isinstance(target_ty, TEnum):
            if self._enum_type_name(value_ty) == target_ty.name and not isinstance(
                value_ty, TEnumRef
            ):
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to enum `{target_ty.name}`",
            )
            return
        if isinstance(target_ty, TStruct):
            if isinstance(value_ty, TStruct) and value_ty.name == target_ty.name:
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to struct `{target_ty.name}`",
            )
            return

    def _coerce_option(
        self,
        at: ast.AST,
        target_ty: TOption,
        value_ty: Ty,
        at_value: ast.AST | None,
    ) -> None:
        """``None`` clears the tag. A ``T`` stores Some. Another option copies both."""
        if isinstance(value_ty, TNone):
            return
        if isinstance(value_ty, TOption):
            if self._option_inner_eq(target_ty.elt, value_ty.elt):
                return
            self._at(
                at_value or at,
                PS2006,
                f"cannot assign `{self._ty_name(value_ty)}` to `{self._ty_name(target_ty)}`",
            )
            return
        self._coerce(at, target_ty.elt, value_ty, at_value)

    def _option_inner_eq(self, target: Ty, value: Ty) -> bool:
        if isinstance(target, TInt) and isinstance(value, TInt):
            return (
                target.width is not None
                and target.width == value.width
                and target.signed == value.signed
            )
        if isinstance(target, TBool) and isinstance(value, TBool):
            return True
        if isinstance(target, TPubkey) and isinstance(value, TPubkey):
            return not target.is_signer and not value.is_signer
        if isinstance(target, TEnum) and isinstance(value, TEnum):
            return target.name == value.name
        return False

    def _coerce_ty(self, target: Ty, value: Ty) -> Ty:
        """Element-level compatibility for collection stores."""
        if isinstance(target, TyUnknown) or isinstance(value, TyUnknown):
            return TyUnknown()
        if isinstance(target, TInt) and isinstance(value, TInt):
            if target.width is not None:
                return target
            return value
        if isinstance(target, TEnum) and self._enum_type_name(value) == target.name:
            if isinstance(value, TEnumRef):
                return TyUnknown()
            return target
        if type(target) is type(value):
            return target
        return TyUnknown()

    # -- expressions -------------------------------------------------------

    def _require_bool(self, test: ast.expr, env: dict[str, Ty], what: str) -> None:
        ty = self._type_of(test, env)
        if not isinstance(ty, (TBool, TyUnknown)):
            self._at(test, PS2006, f"{what} must be `bool`, got `{self._ty_name(ty)}`")

    def _type_of(self, node: ast.expr, env: dict[str, Ty]) -> Ty:
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool):
                return TBool()
            if value is None:
                return TNone()
            if isinstance(value, int):
                return TInt(value=value)
            if isinstance(value, str):
                return TStr(nbytes=len(value.encode("utf-8")))
            return TyUnknown()  # subset rejects float/bytes literals
        if isinstance(node, ast.Name):
            return self._name_ty(node, env)
        if isinstance(node, ast.Attribute):
            return self._attribute_ty(node, env)
        if isinstance(node, ast.BinOp):
            return self._binop_ty(node, env)
        if isinstance(node, ast.UnaryOp):
            return self._unaryop_ty(node, env)
        if isinstance(node, ast.BoolOp):
            for operand in node.values:
                self._require_bool(operand, env, "boolean operand")
            return TBool()
        if isinstance(node, ast.Compare):
            self._compare_ty(node, env)
            return TBool()
        if isinstance(node, ast.IfExp):
            self._require_bool(node.test, env, "conditional test")
            body_ty = self._type_of(node.body, env)
            else_ty = self._type_of(node.orelse, env)
            return self._merge_branches(node, body_ty, else_ty)
        if isinstance(node, ast.Subscript):
            return self._subscript_expr_ty(node, env)
        if isinstance(node, ast.Call):
            return self._call_ty(node, env)
        if isinstance(node, ast.ListComp):
            return self._listcomp_ty(node, env)
        # Anything else: subset should have rejected it; stay quiet.
        return TyUnknown()

    def _listcomp_ty(self, node: ast.ListComp, env: dict[str, Ty]) -> Ty:
        """``[expr for i in range(4)]`` is a ``FixedArray[T, 4]``."""
        gen = node.generators[0] if len(node.generators) == 1 else None
        if gen is None or gen.is_async or gen.ifs or not isinstance(gen.target, ast.Name):
            self._at(node, PS2006, "a list comprehension is `[expr for i in range(<int>)]`")
            return TyUnknown()
        it = gen.iter
        count: int | None = None
        elem: Ty = TyUnknown()
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range":
            bound = it.args[0] if len(it.args) == 1 else None
            if (
                isinstance(bound, ast.Constant)
                and isinstance(bound.value, int)
                and not isinstance(bound.value, bool)
            ):
                count = bound.value
                elem = TInt(width=64, signed=False)
        else:
            iter_ty = self._type_of(it, env)
            if isinstance(iter_ty, (TFixedArray, TVec)):
                count = iter_ty.size if isinstance(iter_ty, TFixedArray) else iter_ty.cap
                elem = iter_ty.elt
            elif isinstance(iter_ty, TFixedString):
                count = iter_ty.size
                elem = TInt(width=8, signed=False)
        if count is None or not 1 <= count <= 4096:
            self._at(it, PS2006, "a list comprehension needs a constant length 1..4096")
            return TyUnknown()
        if gen.target.id in env:
            self._at(gen.target, PS2001, f"`{gen.target.id}` is already declared")
            return TyUnknown()
        inner = dict(env)
        inner[gen.target.id] = elem
        elt_ty = self._type_of(node.elt, inner)
        return TFixedArray(elt=elt_ty, size=count)

    def _name_ty(self, node: ast.Name, env: dict[str, Ty]) -> Ty:
        name = node.id
        bound = env.get(name)
        if bound is not None:
            return bound
        if self._present("enums", name):
            return TEnumRef(name=name)
        if self._present("errors", name):
            return TErrorClassRef(name=name)
        if name in _NOT_VALUE_NAMES or self._present("accounts", name):
            self._at(node, PS2001, f"declaration name `{name}` is not a value")
            return TyUnknown()
        self._at(node, PS2001, f"unknown name `{name}`")
        return TyUnknown()

    def _attribute_ty(self, node: ast.Attribute, env: dict[str, Ty]) -> Ty:
        base_ty = self._type_of(node.value, env)
        if isinstance(base_ty, TyUnknown):
            return TyUnknown()
        if isinstance(base_ty, TErrorClassRef):
            err = self._program.errors.get(base_ty.name)
            if err is not None and any(m.name == node.attr for m in err.members):
                return TErrorMember(owner=base_ty.name)
            self._at(node, PS2001, f"`{base_ty.name}` has no member `{node.attr}`")
            return TyUnknown()
        if isinstance(base_ty, TEnum):
            if node.attr == "value":
                payload = self._enum_payload_ty(base_ty.name)
                if payload is None:
                    self._at(node, PS2001, f"`{base_ty.name}` has no payload")
                    return TyUnknown()
                return payload
            self._at(node, PS2001, f"`{base_ty.name}` has no attribute `{node.attr}`")
            return TyUnknown()
        if isinstance(base_ty, TEnumRef):
            enum = self._program.enums.get(base_ty.name)
            if enum is not None:
                for member in enum.members:
                    if member.name == node.attr:
                        return TEnumVal(enum=base_ty.name, variant=member.name, tag=member.value)
            self._at(node, PS2001, f"`{base_ty.name}` has no variant `{node.attr}`")
            return TyUnknown()
        if isinstance(base_ty, TAccountRef):
            fields = self._fields.get(base_ty.name, {})
            if node.attr in fields:
                return fields[node.attr]
            self._at(
                node,
                PS2001,
                f"account `{base_ty.name}` has no field `{node.attr}`",
            )
            return TyUnknown()
        if isinstance(base_ty, TPubkey):
            if node.attr == "key":
                return TPubkey(is_signer=False)
            self._at(node, PS2001, f"`Pubkey` has no attribute `{node.attr}`")
            return TyUnknown()
        if isinstance(base_ty, TOption):
            if node.attr == "is_some":
                return TBool()
            if node.attr == "value":
                return base_ty.elt
            self._at(
                node,
                PS2001,
                f"`Option` has no attribute `{node.attr}`; use `is_some` or `value`",
            )
            return TyUnknown()
        if isinstance(base_ty, TStruct):
            fields = self._struct_fields.get(base_ty.name, {})
            if node.attr in fields:
                return fields[node.attr]
            self._at(node, PS2001, f"struct `{base_ty.name}` has no field `{node.attr}`")
            return TyUnknown()
        self._at(node, PS1008, f"attribute access on `{self._ty_name(base_ty)}`")
        return TyUnknown()

    def _binop_ty(self, node: ast.BinOp, env: dict[str, Ty]) -> Ty:
        left = self._type_of(node.left, env)
        right = self._type_of(node.right, env)
        if isinstance(left, TyUnknown) or isinstance(right, TyUnknown):
            return TyUnknown()
        op_name = node.op.__class__.__name__
        if op_name == "Div":
            self._at(
                node,
                PS2006,
                "`/` true division is unsupported; use `//` for integer division",
            )
            return TyUnknown()
        if (
            op_name == "Pow"
            and isinstance(right, TInt)
            and right.value is not None
            and not 0 <= right.value <= _MAX_EXPONENT
        ):
            self._at(node, PS2007, "constant exponent outside 0..4096")
            return TyUnknown()
        if isinstance(left, TInt) and isinstance(right, TInt):
            width, signed = self._widen_ty((left.width, left.signed), (right.width, right.signed))
            if width is not None:
                limit = TInt(width=width, signed=signed)
                for side in (left, right):
                    if side.value is not None and not self._fits(limit, side.value):
                        self._at(
                            node,
                            PS2007,
                            f"{self._lit(side.value)} does not fit in "
                            f"{self._width_name(width, signed)}",
                        )
                        return TyUnknown()
            folded: int | None = None
            if left.value is not None and right.value is not None:
                folded = self._fold(op_name, left.value, right.value)
                if folded is None:
                    return TyUnknown()
                if width is not None and not self._fits(TInt(width=width, signed=signed), folded):
                    self._at(
                        node,
                        PS2007,
                        f"folded constant {self._lit(folded)} "
                        f"overflows {self._width_name(width, signed)}",
                    )
            return TInt(width=width, value=folded, signed=signed)
        if (isinstance(left, TBool) or isinstance(right, TBool)) and (
            op_name in ("BitAnd", "BitOr", "BitXor", "Add", "Sub", "Mult")
        ):
            self._at(node, PS2006, f"cannot mix `bool` and integers for `{op_name}`")
            return TyUnknown()
        self._at(
            node,
            PS2006,
            f"unsupported operands for `{op_name}`: {self._ty_name(left)}, {self._ty_name(right)}",
        )
        return TyUnknown()

    def _unaryop_ty(self, node: ast.UnaryOp, env: dict[str, Ty]) -> Ty:
        operand = self._type_of(node.operand, env)
        op_name = node.op.__class__.__name__
        if op_name == "Not":
            if isinstance(operand, TBool):
                return TBool()
            if isinstance(operand, TyUnknown):
                return TyUnknown()
            self._at(node, PS2006, f"`not` needs a bool, got `{self._ty_name(operand)}`")
            return TyUnknown()
        if isinstance(operand, TInt):
            folded = operand.value
            if folded is not None and op_name == "USub":
                folded = -folded
                if operand.width is not None and not self._fits(operand, folded):
                    self._at(node, PS2007, f"`-{folded}` overflows u{operand.width}")
            return TInt(width=operand.width, value=folded, signed=operand.signed)
        if isinstance(operand, TyUnknown):
            return TyUnknown()
        self._at(node, PS2006, f"unary `{op_name}` needs an integer")
        return TyUnknown()

    def _compare_ty(self, node: ast.Compare, env: dict[str, Ty]) -> None:
        left = self._type_of(node.left, env)
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            right = self._type_of(comparator, env)
            op_name = op.__class__.__name__
            if isinstance(left, TyUnknown) or isinstance(right, TyUnknown):
                left = TyUnknown()
                continue
            ordering = op_name in ("Lt", "LtE", "Gt", "GtE")
            equality = op_name in ("Eq", "NotEq")
            if ordering and isinstance(left, TInt) and isinstance(right, TInt):
                left = right
                continue
            if equality and isinstance(left, TPubkey) and isinstance(right, TPubkey):
                left = right
                continue
            if equality and isinstance(left, TInt) and isinstance(right, TInt):
                left = right
                continue
            if equality and isinstance(left, TBool) and isinstance(right, TBool):
                left = right
                continue
            left_enum = self._enum_type_name(left)
            right_enum = self._enum_type_name(right)
            if left_enum is not None and left_enum == right_enum:
                if equality:
                    left = right
                    continue
                self._at(node, PS2006, f"enum `{left_enum}` supports only `==` and `!=`")
                left = right
                continue
            self._at(
                node,
                PS2006,
                f"cannot compare `{self._ty_name(left)}` `{op_name}` `{self._ty_name(right)}`",
            )
            left = right

    def _merge_branches(self, node: ast.IfExp, left: Ty, right: Ty) -> Ty:
        if isinstance(left, TyUnknown):
            return right
        if isinstance(right, TyUnknown):
            return left
        if left == right:
            return left
        left_enum = self._enum_type_name(left)
        right_enum = self._enum_type_name(right)
        if left_enum is not None and left_enum == right_enum:
            return TEnum(name=left_enum)
        if isinstance(left, TInt) and isinstance(right, TInt):
            width, signed = self._widen_ty((left.width, left.signed), (right.width, right.signed))
            return TInt(width=width, signed=signed)
        self._at(node, PS2006, "conditional branches have different types")
        return TyUnknown()

    def _subscript_expr_ty(self, node: ast.Subscript, env: dict[str, Ty]) -> Ty:
        base_ty = self._type_of(node.value, env)
        index = node.slice
        if isinstance(base_ty, TyUnknown):
            return TyUnknown()
        if isinstance(base_ty, TFixedArray):
            if (
                isinstance(index, ast.Constant)
                and isinstance(index.value, int)
                and not isinstance(index.value, bool)
            ):
                if not 0 <= index.value < base_ty.size:
                    self._at(
                        index,
                        PS2007,
                        f"index {index.value} outside 0..{base_ty.size - 1}",
                    )
                    return TyUnknown()
                return base_ty.elt
            idx_ty = self._type_of(index if not isinstance(index, ast.Slice) else node, env)
            if isinstance(idx_ty, (TInt, TyUnknown)):
                return base_ty.elt
            self._at(node, PS2006, "array index must be an integer")
            return TyUnknown()
        if isinstance(base_ty, TVec):
            if (
                base_ty.cap
                and isinstance(index, ast.Constant)
                and isinstance(index.value, int)
                and not isinstance(index.value, bool)
                and not 0 <= index.value < base_ty.cap
            ):
                self._at(
                    index,
                    PS2007,
                    f"index {index.value} outside 0..{base_ty.cap - 1}",
                )
                return TyUnknown()
            idx_ty = self._type_of(index, env)
            if isinstance(idx_ty, (TInt, TyUnknown)):
                return base_ty.elt
            self._at(node, PS2006, "array index must be an integer")
            return TyUnknown()
        if isinstance(base_ty, TFixedString):
            idx_ty = self._type_of(index, env)
            if isinstance(idx_ty, (TInt, TyUnknown)):
                return TInt(width=8, signed=False)  # a char is u8
            self._at(node, PS2006, "string index must be an integer")
            return TyUnknown()
        self._at(node, PS2006, f"`{self._ty_name(base_ty)}` is not subscriptable")
        return TyUnknown()

    def _call_ty(self, node: ast.Call, env: dict[str, Ty]) -> Ty:
        func = node.func
        if not isinstance(func, ast.Name):  # subset guard
            self._at(node, PS1010, "unsupported call target")
            return TyUnknown()
        name = func.id
        if name in _WIDTHS:
            return self._cast_ty(node, name, env)
        if name == "emit":
            return self._emit_ty(node, env)
        if name == "system_transfer":
            return self._system_transfer_ty(node, env)
        if name in ("token_transfer", "token2022_transfer"):
            return self._token_transfer_ty(node, env)
        if name == "ata_create":
            return self._ata_create_ty(node, env)
        if name == "require":
            if len(node.args) != 2:
                self._at(
                    node,
                    PS3001,
                    "require(condition, ERR.Member) takes exactly two arguments",
                )
                return TyUnknown()
            cond = self._type_of(node.args[0], env)
            if not isinstance(cond, (TBool, TyUnknown)):
                self._at(node.args[0], PS2006, "require() condition must be `bool`")
            err = self._type_of(node.args[1], env)
            if not isinstance(err, TErrorMember):
                if not isinstance(err, TyUnknown):
                    self._at(
                        node.args[1],
                        PS3001,
                        "second require() argument must be a member of an @error class",
                    )
                return TyUnknown()
            if not self._present("errors", err.owner):
                self._at(node.args[1], PS2001, f"unknown @error class `{err.owner}`")
                return TyUnknown()
            return TNone()
        if name == "len":
            if len(node.args) != 1:
                self._at(node, PS3001, "len() takes exactly one argument")
                return TyUnknown()
            arg_ty = self._type_of(node.args[0], env)
            if isinstance(arg_ty, (TFixedArray, TVec, TFixedString)):
                return TInt(width=64, signed=False)
            if isinstance(arg_ty, TyUnknown):
                return TyUnknown()
            self._at(node.args[0], PS2006, f"`{self._ty_name(arg_ty)}` has no length")
            return TyUnknown()
        # range() in value position:
        if name == "range":
            self._at(node, PS1010, "range() is only valid as a for-loop iterable")
            return TyUnknown()
        helper = self._helpers.get(name)
        if helper is not None and not self._hidden(name):
            return self._helper_call(helper, node, env)
        self._at(node, PS1010, f"unknown function `{name}`")
        return TyUnknown()

    # -- plain helpers -----------------------------------------------------

    def _check_helper(self, decl: HelperDecl, at: ast.AST | None = None) -> None:
        """Type-check one helper. A cycle or a chain longer than 8 is PS2006."""
        state = self._helper_state.get(decl.name)
        if state == "done":
            return
        if state == "checking":
            self._at_helper(at, decl, PS2006, f"helper `{decl.name}` recurses")
            return
        if self._helper_depth >= _MAX_HELPER_DEPTH:
            self._at_helper(at, decl, PS2006, "helper call depth exceeds 8")
            return
        with self._in_file(decl.file):
            param_tys = [self._helper_param_type(param) for param in decl.params]
            returned = self._helper_return_type(decl)
            self._helper_sigs[decl.name] = (param_tys, returned)
            self._helper_state[decl.name] = "checking"
            self._helper_depth += 1
            previous = self._fn_return
            self._fn_return = returned
            try:
                env = {
                    param.name: ty for param, ty in zip(decl.params, param_tys, strict=False)
                }
                self._check_block(decl.body, env, 0)
            finally:
                self._fn_return = previous
                self._helper_depth -= 1
                self._helper_state[decl.name] = "done"

    def _at_helper(self, at: ast.AST | None, decl: HelperDecl, code: str, message: str) -> None:
        if at is not None:
            self._at(at, code, message)
            return
        self._diags.append(
            Diagnostic(
                code=code,
                message=message,
                file=decl.file or self._file,
                line=decl.line,
                col=decl.col,
            )
        )

    def _helper_call(self, decl: HelperDecl, node: ast.Call, env: dict[str, Ty]) -> Ty:
        if node.keywords or len(node.args) != len(decl.params):
            self._at(
                node,
                PS3001,
                f"`{decl.name}()` takes {len(decl.params)} argument(s)",
            )
            self._check_helper(decl, at=node)
            return TyUnknown()
        self._check_helper(decl, at=node)
        signature = self._helper_sigs.get(decl.name)
        if signature is None:
            return TyUnknown()
        param_tys, returned = signature
        for arg, expected in zip(node.args, param_tys, strict=False):
            self._check_helper_arg(arg, expected, env)
        return returned

    def _check_return(self, stmt: ast.Return, env: dict[str, Ty]) -> None:
        value = stmt.value
        bare = value is None or (isinstance(value, ast.Constant) and value.value is None)
        expected = self._fn_return
        if expected is None:
            if not bare and value is not None:
                self._at(value, PS2006, "instructions must return nothing")
            return
        if isinstance(expected, TyUnknown):
            if not bare and value is not None:
                self._type_of(value, env)
            return
        if isinstance(expected, TNone):
            if not bare and value is not None:
                self._at(value, PS2006, "this helper returns nothing")
            return
        if bare or value is None:
            self._at(stmt, PS2006, "helper must return a value")
            return
        self._coerce(stmt, expected, self._type_of(value, env), at_value=value)

    def _token_transfer_ty(self, node: ast.Call, env: dict[str, Ty]) -> Ty:
        """``token_transfer(src, dest, authority, amount)`` and the Token-2022 twin."""
        if self._fn_return is not None:
            self._at(node, PS3001, "token transfers belong in an instruction")
            return TNone()
        if node.keywords or len(node.args) != 4:
            self._at(
                node,
                PS3001,
                "token_transfer(src, dest, authority, amount) takes four arguments",
            )
            for arg in node.args:
                self._type_of(arg, env)
            return TNone()
        src, dest, authority, amount = node.args
        self._expect_account(src, env, "TokenAccount", "token source")
        self._expect_account(dest, env, "TokenAccount", "token destination")
        self._expect_signer(authority, env, "token authority")
        if isinstance(src, ast.Name) and isinstance(dest, ast.Name) and src.id == dest.id:
            self._at(dest, PS3001, "token source and destination must differ")
        self._coerce(amount, TInt(width=64, signed=False), self._type_of(amount, env), amount)
        return TNone()

    def _ata_create_ty(self, node: ast.Call, env: dict[str, Ty]) -> Ty:
        """``ata_create(payer, ata, owner, mint)`` — idempotent associated-token create."""
        if self._fn_return is not None:
            self._at(node, PS3001, "ata_create belongs in an instruction")
            return TNone()
        if node.keywords or len(node.args) != 4:
            self._at(
                node,
                PS3001,
                "ata_create(payer, ata, owner, mint) takes four arguments",
            )
            for arg in node.args:
                self._type_of(arg, env)
            return TNone()
        payer, ata, owner, mint = node.args
        self._expect_signer(payer, env, "payer")
        self._expect_account(ata, env, "TokenAccount", "associated token account")
        self._expect_signer(owner, env, "owner")
        self._expect_account(mint, env, "TokenMint", "mint")
        return TNone()

    def _expect_signer(self, arg: ast.expr, env: dict[str, Ty], what: str) -> None:
        if not isinstance(arg, ast.Name):
            self._at(arg, PS3001, f"{what} must be a Signer")
            self._type_of(arg, env)
            return
        ty = env.get(arg.id)
        if isinstance(ty, TPubkey) and ty.is_signer:
            return
        if ty is None:
            self._at(arg, PS2001, f"unknown name `{arg.id}`")
            return
        self._at(arg, PS3001, f"{what} must be a Signer")

    def _expect_account(self, arg: ast.expr, env: dict[str, Ty], name: str, what: str) -> None:
        if not isinstance(arg, ast.Name):
            self._at(arg, PS3001, f"{what} must be a `{name}` parameter")
            self._type_of(arg, env)
            return
        ty = env.get(arg.id)
        if isinstance(ty, TAccountRef) and ty.name == name:
            return
        if ty is None:
            self._at(arg, PS2001, f"unknown name `{arg.id}`")
            return
        self._at(arg, PS3001, f"{what} must be a `{name}`")

    def _system_transfer_ty(self, node: ast.Call, env: dict[str, Ty]) -> Ty:
        """``system_transfer(src, dest, lamports)`` — a System program CPI."""
        if self._fn_return is not None:
            self._at(node, PS3001, "system_transfer belongs in an instruction")
            return TNone()
        if node.keywords or len(node.args) != 3:
            self._at(
                node,
                PS3001,
                "system_transfer(src, dest, lamports) takes three arguments",
            )
            for arg in node.args:
                self._type_of(arg, env)
            return TNone()
        src, dest, amount = node.args
        self._transfer_account(src, env, "source")
        self._transfer_account(dest, env, "destination")
        if isinstance(src, ast.Name) and isinstance(dest, ast.Name) and src.id == dest.id:
            self._at(dest, PS3001, "system_transfer source and destination must differ")
        self._coerce(amount, TInt(width=64, signed=False), self._type_of(amount, env), amount)
        return TNone()

    def _transfer_account(self, arg: ast.expr, env: dict[str, Ty], what: str) -> None:
        if not isinstance(arg, ast.Name):
            self._at(arg, PS3001, f"system_transfer {what} must be an account parameter")
            self._type_of(arg, env)
            return
        ty = env.get(arg.id)
        if ty is None:
            self._at(arg, PS2001, f"unknown name `{arg.id}`")
            return
        if isinstance(ty, TPubkey) and ty.is_signer:
            return
        if isinstance(ty, TAccountRef) and ty.mutable:
            return
        self._at(arg, PS3001, f"system_transfer {what} must be a Signer or Mut account")

    def _emit_ty(self, node: ast.Call, env: dict[str, Ty]) -> Ty:
        """``emit(Event(field, ...))`` — positional fields, then a log."""
        if node.keywords or len(node.args) != 1:
            self._at(node, PS3001, "emit() takes one event: emit(Name(...))")
            for arg in node.args:
                self._type_of(arg, env)
            return TNone()
        arg = node.args[0]
        if not isinstance(arg, ast.Call) or not isinstance(arg.func, ast.Name):
            self._at(node, PS3001, "emit() takes one event: emit(Name(...))")
            self._type_of(arg, env)
            return TNone()
        decl = self._program.events.get(arg.func.id)
        if decl is None:
            self._at(arg.func, PS2001, f"unknown event `{arg.func.id}`")
            for value in arg.args:
                self._type_of(value, env)
            return TNone()
        if arg.keywords or len(arg.args) != len(decl.fields):
            self._at(arg, PS3001, f"`{decl.name}` takes {len(decl.fields)} field(s)")
            for value in arg.args:
                self._type_of(value, env)
            return TNone()
        expected = self._event_fields.get(decl.name, {})
        for field, value in zip(decl.fields, arg.args, strict=False):
            self._coerce(
                value,
                expected.get(field.name, TyUnknown()),
                self._type_of(value, env),
                value,
            )
        return TNone()

    def _constraint_items(self, ann: ast.Subscript) -> list[ast.expr]:
        if isinstance(ann.slice, ast.Tuple):
            return list(ann.slice.elts)
        return [ann.slice]

    def _constraint_param_type(self, ann: ast.Subscript, *, for_param: bool) -> Ty:
        """The account type under one constraint. The argument is checked later."""
        if not for_param:
            self._at(ann, PS3001, "constraints are only valid on instruction accounts")
            return TyUnknown()
        items = self._constraint_items(ann)
        if len(items) != 2:
            return TyUnknown()
        if self._wrapper_name(items[0]) in _CONSTRAINTS:
            self._at(items[0], PS3001, "an account takes one constraint")
            return TyUnknown()
        return self._annotation_type(items[0], for_param=True)

    def _check_constraints(self, instr: InstructionDecl, env: dict[str, Ty]) -> None:
        """Seeds, HasOne, CloseTo, Address, and Owner name real parameters."""
        returned = _block_returns(instr.body)
        for param in instr.params:
            ann = param.annotation
            if not isinstance(ann, ast.Subscript) or not isinstance(ann.value, ast.Name):
                continue
            name = ann.value.id
            if name not in _CONSTRAINTS:
                continue
            items = self._constraint_items(ann)
            if len(items) != 2:
                continue
            wrapper = self._wrapper_name(items[0])
            arg = items[1]
            inner = env.get(param.name)
            if name == "Seeds":
                if wrapper != "Init":
                    self._at(ann, PS3001, "`Seeds` applies to `Init` accounts")
                continue
            if name == "HasOne":
                self._check_has_one(ann, inner, arg, env)
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self._require_earlier(instr, arg.value, param.name, arg, "HasOne")
                continue
            if name == "CloseTo":
                if wrapper != "Mut":
                    self._at(ann, PS3001, "`CloseTo` applies to `Mut` accounts")
                self._check_named_account(arg, env, writable=True, what="CloseTo")
                if isinstance(arg, ast.Name) and arg.id == param.name:
                    self._at(arg, PS3001, "an account cannot close into itself")
                if returned:
                    self._at(
                        ann,
                        PS3001,
                        "`CloseTo` runs after the body; this instruction has a `return`",
                    )
                continue
            if name == "Address":
                if wrapper not in ("Mut", "Account", "Init"):
                    self._at(ann, PS3001, "`Address` applies to an account wrapper")
                self._check_address_arg(arg, env)
                continue
            if wrapper not in ("Mut", "Account"):
                self._at(ann, PS3001, "`Owner` applies to `Mut` or `Account`")
            self._check_named_account(arg, env, writable=False, what="Owner")
            if isinstance(arg, ast.Name):
                self._require_earlier(instr, arg.id, param.name, arg, "Owner")

    def _check_has_one(
        self,
        ann: ast.Subscript,
        inner: Ty | None,
        arg: ast.expr,
        env: dict[str, Ty],
    ) -> None:
        wrapper = self._wrapper_name(self._constraint_items(ann)[0])
        if wrapper not in ("Mut", "Account"):
            self._at(ann, PS3001, "`HasOne` applies to `Mut` or `Account`")
            return
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
            return
        field = arg.value
        if not isinstance(inner, TAccountRef):
            self._at(ann, PS3001, "`HasOne` needs an account")
            return
        fields = self._fields.get(inner.name, {})
        field_ty = fields.get(field)
        if field_ty is None:
            self._at(arg, PS2001, f"account `{inner.name}` has no field `{field}`")
            return
        if not isinstance(field_ty, TPubkey):
            self._at(arg, PS3001, f"`HasOne` field `{field}` must be a Pubkey")
            return
        other = env.get(field)
        if not isinstance(other, (TAccountRef, TPubkey)):
            self._at(
                arg,
                PS3001,
                f"`HasOne` needs an account parameter named `{field}`",
            )

    def _check_address_arg(self, arg: ast.expr, env: dict[str, Ty]) -> None:
        if not isinstance(arg, ast.Name):
            return
        other = env.get(arg.id)
        if isinstance(other, TPubkey) and not other.is_signer:
            return
        if other is None:
            self._at(arg, PS2001, f"unknown name `{arg.id}`")
            return
        self._at(arg, PS3001, "`Address` compares the account key to a `Pubkey` argument")

    def _require_earlier(
        self,
        instr: InstructionDecl,
        other: str,
        current: str,
        node: ast.AST,
        what: str,
    ) -> None:
        """The referenced account is declared first, so its C pointer exists."""
        names = [param.name for param in instr.params]
        if other not in names or current not in names:
            return
        if names.index(other) >= names.index(current):
            self._at(
                node,
                PS3001,
                f"`{what}` account `{other}` must be declared before `{current}`",
            )

    def _check_named_account(
        self,
        arg: ast.expr,
        env: dict[str, Ty],
        *,
        writable: bool,
        what: str,
    ) -> None:
        if not isinstance(arg, ast.Name):
            return
        other = env.get(arg.id)
        if other is None:
            self._at(arg, PS2001, f"unknown name `{arg.id}`")
            return
        if isinstance(other, TPubkey) and other.is_signer:
            return
        if isinstance(other, TAccountRef) and (other.mutable or not writable):
            return
        if writable:
            self._at(arg, PS3001, f"`{what}` destination must be a writable account")
            return
        self._at(arg, PS3001, f"`{what}` needs an account parameter")

    def _helper_param_type(self, param: ParamDecl) -> Ty:
        ann = param.annotation
        wrapper = self._wrapper_name(ann)
        if wrapper in _CONSTRAINTS:
            self._at(ann, PS3001, "constraints belong on instruction accounts")
            return TyUnknown()
        if wrapper in ("Init", "InitIfNeeded", "Zeroed"):
            self._at(ann, PS3001, "helpers cannot create accounts; pass Mut or Account")
            return TyUnknown()
        if wrapper in ("Option", "FixedString", "Vec", "FixedArray"):
            self._at(
                ann,
                PS2006,
                "helpers take integers, bool, Pubkey, unit enums, or accounts",
            )
            return TyUnknown()
        ty = self._annotation_type(ann, for_param=True)
        if isinstance(ty, TyUnknown):
            return ty
        if isinstance(ty, TAccountRef):
            return ty
        if isinstance(ty, TPubkey) and ty.is_signer:
            return ty
        if self._helper_value(ty):
            return ty
        self._at(
            ann,
            PS2006,
            "helpers take integers, bool, Pubkey, unit enums, or accounts",
        )
        return TyUnknown()

    def _helper_return_type(self, decl: HelperDecl) -> Ty:
        ann = decl.returns
        if ann is None or (isinstance(ann, ast.Constant) and ann.value is None):
            return TNone()
        wrapper = self._wrapper_name(ann)
        if wrapper in ("Option", "FixedString", "Vec", "FixedArray"):
            self._at(
                ann,
                PS2006,
                "helpers return an integer, bool, Pubkey, unit enum, or None",
            )
            return TyUnknown()
        if isinstance(ann, ast.Name) and self._present("accounts", ann.id):
            self._at(ann, PS2006, "helpers cannot return accounts")
            return TyUnknown()
        ty = self._annotation_type(ann, for_param=False)
        if isinstance(ty, (TyUnknown, TNone)):
            return ty
        if self._helper_value(ty):
            return ty
        self._at(
            ann,
            PS2006,
            "helpers return an integer, bool, Pubkey, unit enum, or None",
        )
        return TyUnknown()

    def _helper_value(self, ty: Ty) -> bool:
        if isinstance(ty, TInt):
            return ty.width is not None
        if isinstance(ty, (TBool, TEnum)):
            return True
        return isinstance(ty, TPubkey) and not ty.is_signer

    def _check_helper_arg(self, arg: ast.expr, expected: Ty, env: dict[str, Ty]) -> None:
        actual = self._type_of(arg, env)
        if isinstance(expected, TyUnknown) or isinstance(actual, TyUnknown):
            return
        if isinstance(expected, TAccountRef):
            if not isinstance(actual, TAccountRef) or actual.name != expected.name:
                wrapper = "Mut" if expected.mutable else "Account"
                self._at(arg, PS2006, f"expected `{wrapper}[{expected.name}]`")
                return
            if expected.mutable and not actual.mutable:
                self._at(
                    arg,
                    PS3001,
                    "cannot pass a read-only account where Mut is required",
                )
            return
        if isinstance(expected, TPubkey) and expected.is_signer:
            if isinstance(actual, TPubkey) and actual.is_signer:
                return
            self._at(arg, PS2006, "expected a Signer")
            return
        if isinstance(expected, TPubkey) and isinstance(actual, TAccountRef):
            return
        self._coerce(arg, expected, actual, at_value=arg)

    def _wrapper_name(self, ann: ast.expr) -> str | None:
        if isinstance(ann, ast.Name):
            return ann.id
        if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name):
            return ann.value.id
        return None

    def _cast_ty(self, node: ast.Call, name: str, env: dict[str, Ty]) -> Ty:
        """``u64(x)`` / ``i32(x)`` — an explicit width cast (TR-LANG-02)."""
        bits, signed = _WIDTHS[name]
        target = TInt(width=bits, signed=signed)
        if len(node.args) != 1 or node.keywords:
            self._at(node, PS2006, f"`{name}(...)` takes one integer argument")
            return TyUnknown()
        arg_ty = self._type_of(node.args[0], env)
        if isinstance(arg_ty, TyUnknown):
            return target
        if not isinstance(arg_ty, TInt):
            self._at(node.args[0], PS2006, f"cannot cast `{self._ty_name(arg_ty)}` to `{name}`")
            return TyUnknown()
        if arg_ty.value is not None and not self._fits(target, arg_ty.value):
            lo, hi = self._range(target)
            self._at(
                node.args[0],
                PS2007,
                f"{self._lit(arg_ty.value)} does not fit into `{name}` (range {lo}..{hi})",
            )
            return TyUnknown()
        return target

    def _check_subscript_store(
        self,
        target: ast.Subscript,
        env: dict[str, Ty],
        value_ty: Ty,
        value_node: ast.expr,
    ) -> None:
        elt, size = self._subscript_element(target, env, writable=True)
        if isinstance(elt, TyUnknown) or size is None:
            return
        self._check_index(target, size, env)
        self._coerce(target, elt, value_ty, at_value=value_node)

    def _subscript_element(
        self,
        target: ast.Subscript,
        env: dict[str, Ty],
        *,
        writable: bool,
    ) -> tuple[Ty, int | None]:
        """Element type and length of ``base[index]``, or ``(TyUnknown(), None)``."""
        base = target.value
        if isinstance(base, ast.Name):
            ty = env.get(base.id)
            if isinstance(ty, TFixedArray):
                return ty.elt, ty.size
            if isinstance(ty, TVec) and ty.cap:
                return ty.elt, ty.cap
            if isinstance(ty, TFixedString):
                return TInt(width=8, signed=False), ty.size
            if ty is None:
                self._at(base, PS2001, f"unknown name `{base.id}`")
            elif not isinstance(ty, TyUnknown):
                self._at(target, PS2006, f"`{self._ty_name(ty)}` is not an array")
            return TyUnknown(), None
        if isinstance(base, ast.Attribute) and not isinstance(base.value, ast.Name):
            field_ty = self._type_of(base, env)
            root = self._account_root(base, env)
            if writable and (root is None or not root.mutable):
                if root is None:
                    self._at(base, PS2006, "a struct field needs an account")
                else:
                    self._at(
                        target,
                        PS3001,
                        f"cannot write to read-only `Account[{root.name}]`",
                    )
                return TyUnknown(), None
            if isinstance(field_ty, TFixedArray):
                return field_ty.elt, field_ty.size
            if isinstance(field_ty, TVec) and field_ty.cap:
                return field_ty.elt, field_ty.cap
            if isinstance(field_ty, TFixedString):
                return TInt(width=8, signed=False), field_ty.size
            if not isinstance(field_ty, TyUnknown):
                self._at(target, PS2006, "only a fixed array or fixed string can be indexed")
            return TyUnknown(), None
        if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
            base_ty = env.get(base.value.id)
            if not isinstance(base_ty, TAccountRef):
                if base_ty is None:
                    self._at(base.value, PS2001, f"unknown name `{base.value.id}`")
                else:
                    self._at(target, PS2006, f"`{base.value.id}` is not an account")
                return TyUnknown(), None
            if writable and not base_ty.mutable:
                self._at(
                    target,
                    PS3001,
                    f"cannot write to read-only `Account[{base_ty.name}]`",
                )
                return TyUnknown(), None
            account_field = self._fields.get(base_ty.name, {}).get(base.attr)
            if isinstance(account_field, TFixedArray):
                return account_field.elt, account_field.size
            if isinstance(account_field, TVec) and account_field.cap:
                return account_field.elt, account_field.cap
            if isinstance(account_field, TFixedString):
                return TInt(width=8, signed=False), account_field.size
            if account_field is None:
                self._at(target, PS2001, f"account `{base_ty.name}` has no field `{base.attr}`")
            else:
                self._at(target, PS2006, f"`{base.attr}` is not an array")
            return TyUnknown(), None
        self._at(target, PS2006, "only `name[i]` and `account.field[i]` can be indexed")
        return TyUnknown(), None

    def _check_index(self, target: ast.Subscript, size: int, env: dict[str, Ty]) -> None:
        index = target.slice
        if isinstance(index, ast.Slice):
            return
        if (
            isinstance(index, ast.Constant)
            and isinstance(index.value, int)
            and not isinstance(index.value, bool)
        ):
            if not 0 <= index.value < size:
                self._at(index, PS2007, f"index {index.value} outside 0..{size - 1}")
            return
        idx_ty = self._type_of(index, env)
        if not isinstance(idx_ty, (TInt, TyUnknown)):
            self._at(index, PS2006, "array index must be an integer")

    # -- cross-instruction checks ------------------------------------------

    def _account_view(self, ann: ast.expr) -> tuple[str, ast.expr] | None:
        """``(Mut|Account|Init, target)``, peeling one ``Seeds``/``HasOne``/… layer."""
        if not isinstance(ann, ast.Subscript) or not isinstance(ann.value, ast.Name):
            return None
        if ann.value.id in _CONSTRAINTS:
            items = self._constraint_items(ann)
            if len(items) != 2:
                return None
            return self._account_view(items[0])
        if ann.value.id not in ("Mut", "Account", "Init", "InitIfNeeded", "Zeroed"):
            return None
        target = self._single_subscript_arg(ann)
        if target is None:
            return None
        return ann.value.id, target

    def _cross_instruction_checks(self) -> None:
        # Duplicate Init across instructions, and mutable aliasing per instruction.
        init_seen: dict[str, str] = {}
        for decl in self._program.instructions:
            groups: dict[str, list[tuple[int, int, bool, str]]] = {}
            saved_file = self._file
            if decl.file:
                self._file = decl.file
            for param in decl.params:
                view = self._account_view(param.annotation)
                if view is None:
                    continue
                base_id, target = view
                if not isinstance(target, ast.Name) or target.id not in self._program.accounts:
                    continue
                mutable = base_id != "Account"
                if base_id in ("Init", "InitIfNeeded", "Zeroed"):
                    prior = init_seen.get(target.id)
                    if prior is not None:
                        self._at(
                            param.annotation,
                            PS3001,
                            f"account `{target.id}` is initialized by `{prior}` "
                            "already; only one Init is allowed",
                        )
                    else:
                        init_seen[target.id] = decl.name
                groups.setdefault(target.id, []).append(
                    (param.line, param.col, mutable, param.name)
                )
            for name, entries in groups.items():
                mutables = [e for e in entries if e[2]]
                readonlys = [e for e in entries if not e[2]]
                if len(mutables) >= 2 or (mutables and readonlys):
                    duplicate = mutables[1] if len(mutables) >= 2 else readonlys[0]
                    self._diags.append(
                        Diagnostic(
                            code=PS3000,
                            message=(
                                f"aliased access to `{name}` in `{decl.name}`: "
                                f"`{duplicate[3]}` conflicts with an earlier mutable view"
                            ),
                            file=self._file,
                            line=duplicate[0],
                            col=duplicate[1],
                        )
                    )
            self._file = saved_file

    # -- numeric/name helpers ----------------------------------------------

    def _widen_ty(
        self,
        left: tuple[int | None, bool],
        right: tuple[int | None, bool],
    ) -> tuple[int | None, bool]:
        (l_w, l_s) = left
        (r_w, r_s) = right
        if l_w is None:
            return (r_w, l_s or r_s)
        if r_w is None:
            return (l_w, bool(l_s or r_s))
        return (max(l_w, r_w), bool(l_s or r_s))

    def _fits(self, ty: TInt, value: int) -> bool:
        if ty.width is None:
            return True
        lo, hi = self._range(ty)
        return lo <= value <= hi

    def _range(self, ty: TInt) -> tuple[int, int]:
        if ty.width is None:
            return (0, 0)
        if ty.signed:
            return (-(2 ** (ty.width - 1)), 2 ** (ty.width - 1) - 1)
        return (0, 2**ty.width - 1)

    def _width_name(self, width: int | None, signed: bool) -> str:
        if width is None:
            return "int"
        return ("i" if signed else "u") + str(width)

    def _fold(self, op_name: str, left: int, right: int) -> int | None:
        try:
            if op_name == "Add":
                return left + right
            if op_name == "Sub":
                return left - right
            if op_name == "Mult":
                return left * right
            if op_name == "FloorDiv":
                return left // right if right != 0 else 0
            if op_name == "Mod":
                return left % right if right != 0 else 0
            if op_name == "LShift":
                return left << min(right, 2048)
            if op_name == "RShift":
                return left >> max(min(right, 2048), -2048)
            if op_name == "BitAnd":
                return left & right
            if op_name == "BitOr":
                return left | right
            if op_name == "BitXor":
                return left ^ right
            if op_name == "Pow" and 0 <= right <= _MAX_EXPONENT:
                return int(left**right)
        except (OverflowError, ValueError):  # pragma: no cover
            return None
        return None

    def _lit(self, value: int) -> str:
        """Render an integer constant safely (CPython caps int->str digits)."""
        try:
            text = str(value)
        except ValueError:  # pragma: no cover — CPython int digit cap
            return "<huge int>"
        return text if len(text) <= 24 else f"<{value.bit_length()}-bit int>"

    def _op_name(self, op: object) -> str:
        return op.__class__.__name__

    def _op_symbol(self, op: object) -> str:
        mapping = {
            "Add": "+",
            "Sub": "-",
            "Mult": "*",
            "FloorDiv": "//",
            "Mod": "%",
            "Pow": "**",
            "LShift": "<<",
            "RShift": ">>",
            "BitAnd": "&",
            "BitOr": "|",
            "BitXor": "^",
        }
        return mapping.get(op.__class__.__name__, op.__class__.__name__)

    def _ty_name(self, ty: Ty) -> str:
        if isinstance(ty, TInt):
            return self._width_name(ty.width, ty.signed)
        if isinstance(ty, TBool):
            return "bool"
        if isinstance(ty, TNone):
            return "None"
        if isinstance(ty, TPubkey):
            return "Signer" if ty.is_signer else "Pubkey"
        if isinstance(ty, TSysProg):
            return "SystemProgram"
        if isinstance(ty, TAccountRef):
            return ty.name
        if isinstance(ty, TErrorClassRef):
            return ty.name
        if isinstance(ty, TErrorMember):
            return "@error member"
        if isinstance(ty, TEnum):
            return ty.name
        if isinstance(ty, TEnumRef):
            return ty.name
        if isinstance(ty, TEnumVal):
            return f"{ty.enum}.{ty.variant}"
        if isinstance(ty, TFixedArray):
            return "FixedArray"
        if isinstance(ty, TStr):
            return "str"
        if isinstance(ty, TFixedString):
            return "FixedString"
        if isinstance(ty, TOption):
            return f"Option[{self._ty_name(ty.elt)}]"
        if isinstance(ty, TStruct):
            return ty.name
        if isinstance(ty, TVec):
            inner = self._ty_name(ty.elt)
            if ty.cap:
                return f"Vec[{inner}, {ty.cap}]"
            return "Vec"
        return "unknown"

    def _enum_type_name(self, ty: Ty) -> str | None:
        """Enum a value belongs to. A bare class name (``TEnumRef``) is not a value."""
        if isinstance(ty, TEnum):
            return ty.name
        if isinstance(ty, TEnumVal):
            return ty.enum
        return None

    def _check_match(self, stmt: ast.Match, env: dict[str, Ty], loop_depth: int) -> None:
        subject = self._type_of(stmt.subject, env)
        enum_name = self._enum_type_name(subject)
        if enum_name is None and not isinstance(subject, TyUnknown):
            self._at(
                stmt.subject,
                PS2006,
                f"match subject must be a unit enum, got `{self._ty_name(subject)}`",
            )
        seen: set[str] = set()
        saw_wild = False
        for case in stmt.cases:
            if case.guard is not None:
                self._at(case.guard, PS1003, "match guards are not supported")
            kind, variant = self._match_variant(case.pattern, env)
            if kind == "wild":
                if saw_wild:
                    self._at(case.pattern, PS2006, "wildcard must be the last match case")
                saw_wild = True
            elif kind == "variant":
                if saw_wild:
                    self._at(case.pattern, PS2006, "wildcard must be the last match case")
                owner, _, name = variant.partition(".")
                if enum_name is not None and owner != enum_name:
                    self._at(
                        case.pattern,
                        PS2006,
                        f"`{variant}` is not a variant of `{enum_name}`",
                    )
                elif name in seen:
                    self._at(case.pattern, PS2006, f"variant `{name}` is already matched")
                else:
                    seen.add(name)
            self._check_block(case.body, dict(env), loop_depth)
        if enum_name is None or saw_wild:
            return
        decl = self._program.enums.get(enum_name)
        if decl is None:
            return
        missing = [member.name for member in decl.members if member.name not in seen]
        if missing:
            self._at(
                stmt,
                PS2006,
                f"match on `{enum_name}` is not exhaustive; missing {', '.join(missing)}",
            )

    def _match_variant(self, pattern: ast.pattern, env: dict[str, Ty]) -> tuple[str, str]:
        """``("wild", "")``, ``("variant", "Enum.Name")``, or ``("bad", "")``."""
        if isinstance(pattern, ast.MatchAs) and pattern.pattern is None and pattern.name is None:
            return "wild", ""
        if isinstance(pattern, ast.MatchValue) and isinstance(pattern.value, ast.Attribute):
            ty = self._type_of(pattern.value, env)
            if isinstance(ty, TEnumVal):
                return "variant", f"{ty.enum}.{ty.variant}"
            if isinstance(ty, TyUnknown):
                return "bad", ""
            self._at(pattern, PS2006, f"match case `{self._ty_name(ty)}` is not an enum variant")
            return "bad", ""
        self._at(pattern, PS1003, "match cases must be `Enum.Variant` or `_`")
        return "bad", ""


class _FileScope:
    """Set ``TypeChecker._file`` for the duration of one declaration."""

    def __init__(self, checker: TypeChecker, file: str) -> None:
        self._checker = checker
        self._file = file
        self._saved = checker._file

    def __enter__(self) -> None:
        if self._file:
            self._checker._file = self._file

    def __exit__(self, *_exc: object) -> None:
        self._checker._file = self._saved
