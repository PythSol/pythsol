"""Stage 4 — expression-level type checking over the resolved program model.

Inputs are assumed subset-clean (stage 2 guarantees shapes: no banned
literals/statements/operators, unknown callees already rejected). On top of
the structural pass this stage computes:

* fixed-width integer types and **value range checks** for constants,
* wrapper semantics (``Mut[X]`` writable, ``Account[X]`` read-only),
* field access against ``@account`` layouts (unknown fields are errors),
* ``require(cond, Err.Member)`` call validation,
* cross-instruction checks: duplicate ``Init`` per account and mutable
  aliasing of the same account twice in one instruction.

Arithmetic widens to the larger operand width; storing a wider value into a
narrower one is rejected (``PS2007``) instead of silently truncating. Phase 4
formalizes overflow-checked casts on top of this rule.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from pythsol.compiler.diagnostics import (
    PS1008,
    PS1010,
    PS2000,
    PS2001,
    PS2006,
    PS2007,
    PS3000,
    PS3001,
    Diagnostic,
)
from pythsol.compiler.resolve import Program

__all__ = ["TInt", "Ty", "check_program"]

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
        "require",
    }
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
class TFixedArray:
    elt: Ty
    size: int


@dataclass(frozen=True)
class TFixedString:
    size: int


@dataclass(frozen=True)
class TVec:
    elt: Ty


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
    | TFixedArray
    | TFixedString
    | TVec
)


def check_program(program: Program, file: str = "<program>") -> list[Diagnostic]:
    """Type-check every instruction of ``program``; returns diagnostics."""
    return TypeChecker(program, file).run()


class TypeChecker:
    """Per-program type checker/semantic validator."""

    def __init__(self, program: Program, file: str) -> None:
        self._program = program
        self._file = file
        self._diags: list[Diagnostic] = []
        # account name -> field types, for attribute resolution
        self._fields: dict[str, dict[str, Ty]] = {
            account.name: {} for account in program.accounts.values()
        }
        for account in program.accounts.values():
            for field in account.fields:
                self._fields[account.name][field.name] = self._field_type(field.annotation)

    # -- entry point -------------------------------------------------------

    def run(self) -> list[Diagnostic]:
        for decl in self._program.instructions:
            self._check_block(
                decl.body,
                {p.name: self._annotation_type(p.annotation, for_param=True) for p in decl.params},
                loop_depth=0,
            )
        self._cross_instruction_checks()
        return self._diags

    # -- helpers -----------------------------------------------------------

    def _at(self, node: ast.AST, code: str, message: str, fix: str | None = None) -> None:
        line = getattr(node, "lineno", 1) or 1
        col = (getattr(node, "col_offset", 0) or 0) + 1
        self._diags.append(
            Diagnostic(code=code, message=message, file=self._file, line=line, col=col, fix=fix)
        )

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
            if ann.id in self._program.accounts:
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
            if ann.id in self._program.errors:
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
        if name in ("Mut", "Account", "Init", "InitIfNeeded", "Zeroed"):
            target = self._single_subscript_arg(ann)
            if not isinstance(target, ast.Name):
                self._at(
                    target if target is not None else ann,
                    PS2001,
                    f"`{name}[...]` needs an @account class",
                )
                return TyUnknown()
            if target.id not in self._program.accounts:
                if target.id in self._program.errors:
                    self._at(
                        target,
                        PS3001,
                        f"`{name}[{target.id}]`: error classes are not accounts",
                    )
                else:
                    self._at(target, PS2001, f"`{target.id}` is not an @account class")
                return TyUnknown()
            return TAccountRef(name=target.id, mutable=name != "Account")
        if name in ("Vec", "Option", "FixedArray", "FixedString"):
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
        if name in ("Vec", "Option") and len(items) == 1:
            inner = self._annotation_type(items[0], for_param=False)
            if isinstance(inner, TyUnknown):
                return TyUnknown()
            return TVec(elt=inner)
        self._at(ann, PS2007, f"`{name}` takes a different number of type arguments")
        return TyUnknown()

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
            value = stmt.value
            if value is None or (isinstance(value, ast.Constant) and value.value is None):
                return
            self._at(value, PS2006, "instructions must return nothing")
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
        # Break/Continue/Pass: nothing to check (subset validated presence).

    def _check_ann_assign(self, stmt: ast.AnnAssign, env: dict[str, Ty]) -> None:
        target = stmt.target
        if not isinstance(target, ast.Name):  # subset guard
            return
        if target.id in env:
            self._at(target, PS2001, f"`{target.id}` is already declared")
            return
        ty = self._annotation_type(stmt.annotation, for_param=False)
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
        # Tuple/List/Subscript targets were rejected by the subset pass.

    def _coerce_field_write(
        self,
        target: ast.Attribute,
        env: dict[str, Ty],
        value_ty: Ty,
        value_node: ast.expr,
    ) -> None:
        base = target.value
        if not isinstance(base, ast.Name):
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

    def _aug_target_type(self, target: ast.expr, env: dict[str, Ty]) -> Ty:
        if isinstance(target, ast.Name):
            if target.id not in env:
                self._at(target, PS2000, f"`{target.id}` is not declared")
                return TyUnknown()
            return env[target.id]
        if isinstance(target, ast.Attribute):
            base = target.value
            if not isinstance(base, ast.Name):
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
            if isinstance(value_ty, TNone):
                self._at(at_value or at, PS2006, "`None` is only valid in `return`")
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

    def _coerce_ty(self, target: Ty, value: Ty) -> Ty:
        """Element-level compatibility for collection stores."""
        if isinstance(target, TyUnknown) or isinstance(value, TyUnknown):
            return TyUnknown()
        if isinstance(target, TInt) and isinstance(value, TInt):
            if target.width is not None:
                return target
            return value
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
            return TyUnknown()  # subset rejects float/str/bytes literals
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
        # Anything else: subset should have rejected it; stay quiet.
        return TyUnknown()

    def _name_ty(self, node: ast.Name, env: dict[str, Ty]) -> Ty:
        name = node.id
        bound = env.get(name)
        if bound is not None:
            return bound
        if name in self._program.errors:
            return TErrorClassRef(name=name)
        if name in _NOT_VALUE_NAMES or name in self._program.accounts:
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
            if err.owner not in self._program.errors:
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
        self._at(node, PS1010, f"unknown function `{name}`")
        return TyUnknown()

    # -- cross-instruction checks ------------------------------------------

    def _cross_instruction_checks(self) -> None:
        # Duplicate Init across instructions, and mutable aliasing per instruction.
        init_seen: dict[str, str] = {}
        for decl in self._program.instructions:
            groups: dict[str, list[tuple[int, int, bool, str]]] = {}
            for param in decl.params:
                if not isinstance(param.annotation, ast.Subscript):
                    continue
                base = param.annotation.value
                if not isinstance(base, ast.Name):
                    continue
                if base.id not in ("Mut", "Account", "Init", "InitIfNeeded", "Zeroed"):
                    continue
                target = self._single_subscript_arg(param.annotation)
                if not isinstance(target, ast.Name) or target.id not in self._program.accounts:
                    continue
                mutable = base.id != "Account"
                if base.id in ("Init", "InitIfNeeded", "Zeroed"):
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
        if isinstance(ty, TFixedArray):
            return "FixedArray"
        if isinstance(ty, TFixedString):
            return "FixedString"
        if isinstance(ty, TVec):
            return "Vec"
        return "unknown"
