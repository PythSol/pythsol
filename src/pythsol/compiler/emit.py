"""Stage 6 — lower a :class:`ProgramModel` into the generated C source.

The emitter is deliberately boring C: no compound evaluation tricks, no
pointer arithmetic beyond ``data + offset``, every read/write of an account
field goes through a byte-wise helper, and every arithmetic operation is
overflow-checked with a source-tagged abort. Golden invariants (TRD §16,
"Emitter invariants"):

* Python evaluation order is preserved via statement-level temporaries;
* references alias account data in-place (the runtime's zero-copy view);
* field writes only happen after the runtime proved
  ``data_len == ACCOUNT.size`` (mut) or created fresh accounts via cpi (init);
* runtime failure logs always carry ``(source.py:LINE)``;
* the stack is the only memory an instruction touches beyond account data.

Phase 3 lowerable subset (counter-level):

* account params: ``Signer``, ``Mut[X]``, ``Account[X]``, ``Init[X]``;
* data params: ``u8/u16/u32/u64``, ``i64``, ``bool``, ``Pubkey``;
* statements: annotated locals, typed stores into a local or field, checked
  augmented assigns (``+=``, ``-=``, ``*=``, ``//``, ``%``) and
  ``require(cond, Err.Member)``;
* expressions: integer literals (bounded), names, ``param.key`` and account
  field reads, ``==``/``!=`` on pubkeys and integers, ordered integer
  comparisons, ``and``/``or``/``not``, unary ``-``.

Anything else becomes a ``PS500x`` diagnostic (never ``PS9000``), so the
build fails with a stable code instead of a compiler crash.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from pythsol.compiler.diagnostics import (
    PS5001,
    PS5002,
    PS5003,
    Diagnostic,
)
from pythsol.compiler.model import (
    ACCOUNT_DATA_OFFSET,
    AccountModel,
    FieldModel,
    InstructionModel,
    ProgramModel,
    snake_case,
)

__all__ = [
    "RT_ERR_CPI",
    "RT_ERR_DISC",
    "RT_ERR_DIV_ZERO",
    "RT_ERR_OOB",
    "RT_ERR_OVERFLOW",
    "RT_ERR_OWNER",
    "RT_ERR_PDA",
    "RT_ERR_SIGNER",
    "RT_ERR_SIZE",
    "RT_ERR_UNKNOWN",
    "RT_ERR_WRITABLE",
    "emit_program_c",
]

# Framework error codes used while lowering (keep in sync with pythsol_rt.h).
RT_ERR_UNKNOWN = 1
RT_ERR_SIGNER = 1001
RT_ERR_WRITABLE = 1002
RT_ERR_OWNER = 1003
RT_ERR_SIZE = 1004
RT_ERR_DISC = 1005
RT_ERR_OOB = 1006
RT_ERR_CPI = 1007
RT_ERR_PDA = 1008
RT_ERR_OVERFLOW = 1009
RT_ERR_DIV_ZERO = 1010

_GENERATOR = "PythSol"
_Q = '"'

#: rent-exempt reserve = (size + 128) * 3480 * 2 lamports — equal to the f64
#: math lamports_per_byte_year(3480) * exemption_threshold(2.0), exact for the
#: integer sizes. Recorded in ADR-0010.
_RENT_OVERHEAD_BYTES = 128
_RENT_LAMPORTS_PER_BYTE = 3480
_RENT_EXEMPTION_NUMER = 2

_WIDTH_C: dict[str, str] = {
    "uint8_t": "uint8_t",
    "uint16_t": "uint16_t",
    "uint32_t": "uint32_t",
    "uint64_t": "uint64_t",
    "int64_t": "int64_t",
    "bool": "uint8_t",
    "SolPubkey": "SolPubkey",
}

_WIDTH_BYTES: dict[str, int] = {
    "uint8_t": 1,
    "uint16_t": 2,
    "uint32_t": 4,
    "uint64_t": 8,
    "int64_t": 8,
    "bool": 1,
}

_ST_HELPER: dict[int, str] = {2: "rt_st_u16", 4: "rt_st_u32", 8: "rt_st_u64"}
_LD_HELPER: dict[int, str] = {2: "rt_ld_u16", 4: "rt_ld_u32", 8: "rt_ld_u64"}

_ARITH_OP_C: dict[type, str] = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.FloorDiv: "div",
    ast.Mod: "mod",
}

_COMPARE_C: dict[type, str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}

_LOCAL_TYPES_C: dict[str, str] = {
    "u8": "uint8_t",
    "u16": "uint16_t",
    "u32": "uint32_t",
    "u64": "uint64_t",
    "i64": "int64_t",
    "bool": "uint8_t",
    "Pubkey": "SolPubkey",
}


@dataclass(frozen=True)
class _Frag:
    """A lowered expression: C text plus its kind.

    ``kind`` is one of:

    * ``"pub"`` — a ``const SolPubkey *``-compatible pointer expression;
    * ``"bool"`` — a C 0/1 value usable directly in ``if``;
    * a fixed-width numeric C type such as ``uint64_t`` / ``int64_t``.
    """

    text: str
    kind: str


def _init_rent_lamports(account_size: int) -> int:
    return (account_size + _RENT_OVERHEAD_BYTES) * _RENT_LAMPORTS_PER_BYTE * _RENT_EXEMPTION_NUMER


def _c_int_lit(value: int) -> str:
    return f"{value}u" if value >= 0 else f"({value})"


class _Emitter:
    """Per-program C emitter; accumulates lines and diagnostics."""

    def __init__(self, model: ProgramModel) -> None:
        self._model = model
        self._lines: list[str] = []
        self._diags: list[Diagnostic] = []
        self._tmp_no = 0
        self._accounts: dict[str, AccountModel] = {
            account.name: account for account in model.accounts
        }
        self._error_codes: dict[tuple[str, str], int] = {
            (error.owner, error.name): error.code for error in model.errors
        }
        # Per-instruction state (reset in `_emit_instruction`).
        self._data_vars: dict[str, tuple[str, str]] = {}
        self._acct_vars: dict[str, tuple[str, str]] = {}
        self._locals: dict[str, tuple[str, str]] = {}
        self._iparams: list[Any] = []

    # -- infrastructure ----------------------------------------------------

    @property
    def file(self) -> str:
        """Source file base name used in runtime logs."""
        return self._model.source

    def _line(self, text: str, indent: int = 1) -> None:
        prefix = "    " * indent
        self._lines.append(f"{prefix}{text}" if text else "")

    def _mk_tmp(self) -> str:
        self._tmp_no += 1
        return f"rt_t{self._tmp_no}"

    def _loc(self, line: int) -> str:
        return f"{_Q}{self.file}{_Q}, {line}u"

    def _diag(self, code: str, node: ast.AST | None, message: str) -> None:
        self._diags.append(
            Diagnostic(
                code=code,
                message=message,
                file=self.file,
                line=getattr(node, "lineno", 1) or 1,
                col=(getattr(node, "col_offset", 0) or 0) + 1,
            )
        )

    def _err_macro(self, owner: str, member: str) -> str:
        return f"ERR_{owner.upper()}_{member.upper()}"

    @property
    def diagnostics(self) -> list[Diagnostic]:
        """Diagnostics collected while emitting."""
        return self._diags

    # -- program topology --------------------------------------------------

    def run(self) -> str:
        """Emit the whole program: metadata, handlers, dispatch + entry."""
        model = self._model
        self._line(f"/* Generated by {_GENERATOR} from {self.file}; do not edit.", 0)
        self._line(f" * Program: {model.name}", 0)
        self._line(
            " * Custom errors: 6000 + index; framework codes live in pythsol_rt.h. */",
            0,
        )
        self._line('#include "pythsol_rt.h"', 0)
        self._line("", 0)
        for account in model.accounts:
            self._emit_account_meta(account)
        for error in model.errors:
            self._line(
                f"#define {self._err_macro(error.owner, error.name)} {error.code}u"
                f" /* {error.owner}.{error.name} */",
                0,
            )
        if model.errors:
            self._line("", 0)
        for instruction in model.instructions:
            self._emit_instruction(instruction)
            self._line("", 0)
        self._emit_dispatch_table()
        return "\n".join(self._lines) + "\n"

    def _emit_account_meta(self, account: AccountModel) -> None:
        upper = account.name.upper()
        disc = ", ".join(f"{byte:#x}u" for byte in account.discriminator)
        self._line(
            f"/* @account {account.name}: {account.size} bytes (disc + payload). */",
            0,
        )
        self._line(f"static const unsigned char RT_DISC_{upper}[8] = {{ {disc} }};", 0)
        self._line(f"#define RT_SIZE_{upper} {account.size}u", 0)
        for field in account.fields:
            self._line(
                f"#define RT_OFF_{upper}_{field.name.upper()} "
                f"{ACCOUNT_DATA_OFFSET + field.offset}u",
                0,
            )
        self._line("", 0)

    # -- instructions ------------------------------------------------------

    def _emit_instruction(self, instruction: InstructionModel) -> None:
        self._data_vars = {}
        self._acct_vars = {}
        self._locals = {}
        self._iparams = list(instruction.account_params)
        self._line(
            f"/* instruction {instruction.name} (disc "
            f"{list(instruction.discriminator)}) declared at "
            f"{self.file}:{instruction.line} */",
            0,
        )
        self._line(f"static uint64_t pyf_{instruction.snake_name}(RtCtx *rt) {{", 0)
        self._emit_data_section(instruction)
        self._emit_account_section(instruction)
        self._line("/* body */", 1)
        for stmt in instruction.body:
            self._emit_stmt(stmt, instruction)
        self._line("return 0u; /* RT_OK */", 1)
        self._line("}", 0)

    def _emit_data_section(self, instruction: InstructionModel) -> None:
        body_size = sum(param.size for param in instruction.data_params)
        self._line("/* 1. instruction data (Borsh, disc already cropped by rt) */", 1)
        # rt_entrypoint points rt->data past the 8-byte discriminator and
        # reports rt->data_len without it, so the runtime-computed payload
        # length is exactly `body_size` here.
        self._line(f"if (rt->data_len != {body_size}u) {{", 1)
        self._line(
            f"rt_fail_log({RT_ERR_UNKNOWN}u, {self._loc(instruction.line)},"
            ' "instruction data length is wrong");',
            2,
        )
        self._line(f"return {RT_ERR_UNKNOWN}u;", 2)
        self._line("}", 1)
        offset = 0
        for param in instruction.data_params:
            var = f"dp_{param.name}"
            ctype = _WIDTH_C[param.c_type]
            if param.c_type == "SolPubkey":
                self._line(f"SolPubkey {var};", 1)
                self._line(
                    f"rt_key_copy(&{var}, (const SolPubkey *)(const void *)"
                    f"(rt->data + {offset}u));",
                    1,
                )
            elif param.c_type == "int64_t":
                self._line(f"int64_t {var} = 0;", 1)
                self._line(
                    "{ uint64_t rt_bits = 0u;"
                    f" rt_ld_u64(rt->data, {offset}u, &rt_bits);"
                    f" {var} = (int64_t)rt_bits; }}",
                    1,
                )
            elif param.c_type in ("uint8_t", "bool"):
                self._line(f"uint8_t {var} = rt->data[{offset}u];", 1)
                ctype = "uint8_t"
            elif param.c_type == "uint16_t":
                self._line(f"uint16_t {var} = 0u;", 1)
                self._line(f"rt_ld_u16(rt->data, {offset}u, &{var});", 1)
            elif param.c_type == "uint32_t":
                self._line(f"uint32_t {var} = 0u;", 1)
                self._line(f"rt_ld_u32(rt->data, {offset}u, &{var});", 1)
            else:
                self._line(f"uint64_t {var} = 0u;", 1)
                self._line(f"rt_ld_u64(rt->data, {offset}u, &{var});", 1)
            self._data_vars[param.name] = (var, ctype)
            offset += param.size
        for param in instruction.data_params:  # -Wunused silencing (deterministic)
            self._line(f"(void)dp_{param.name};", 1)

    def _emit_account_section(self, instruction: InstructionModel) -> None:
        count = len(instruction.account_params)
        self._line(f"/* 2. accounts: {count} role-checked in declared order */", 1)
        self._line(f"if (rt->n_accounts < {count}u) {{", 1)
        self._line(
            f'rt_fail_log({RT_ERR_OOB}u, {self._loc(instruction.line)}, "missing accounts");',
            2,
        )
        self._line(f"return {RT_ERR_OOB}u;", 2)
        self._line("}", 1)
        for param in instruction.account_params:
            var = f"acc_{param.name}"
            self._acct_vars[param.name] = (var, param.account)
            self._line(f"RtAccount *{var} = &rt->accounts[{param.index}u];", 1)
            self._emit_role_checks(param, var)

    # -- role checks -------------------------------------------------------

    def _emit_role_checks(self, param: Any, var: str) -> None:
        loc = self._loc(param.line)
        if param.kind == "signer":
            self._line(f"if (!{var}->is_signer) {{", 1)
            self._line(
                f'rt_fail_log({RT_ERR_SIGNER}u, {loc}, "signer required: {param.name}");',
                2,
            )
            self._line(f"return {RT_ERR_SIGNER}u;", 2)
            self._line("}", 1)
            return
        if not param.writable:
            # read-only `Account[X]`: owner + size + discriminator still apply
            self._emit_persistent_checks(param, var)
            return
        self._line(f"if (!{var}->is_writable) {{", 1)
        self._line(
            f'rt_fail_log({RT_ERR_WRITABLE}u, {loc}, "writable required: {param.name}");',
            2,
        )
        self._line(f"return {RT_ERR_WRITABLE}u;", 2)
        self._line("}", 1)
        if param.kind == "init":
            self._emit_init(param, var)
            return
        if param.kind in ("init_if_needed", "zeroed"):
            self._diag(
                PS5003,
                None,
                f"`{param.kind}[{param.account}]` on `{param.name}` is not lowered yet (phase 4)",
            )
            return
        self._emit_persistent_checks(param, var)

    def _emit_persistent_checks(self, param: Any, var: str) -> None:
        """Owner/size/discriminator for an initialized account view."""
        if self._accounts.get(param.account) is None:
            return
        loc = self._loc(param.line)
        upper = param.account.upper()
        self._line(f"if (!rt_owner_eq({var}, rt->program_id)) {{", 1)
        self._line(
            f'rt_fail_log({RT_ERR_OWNER}u, {loc}, "owner mismatch: {param.name}");',
            2,
        )
        self._line(f"return {RT_ERR_OWNER}u;", 2)
        self._line("}", 1)
        self._line(f"if ({var}->data_len != RT_SIZE_{upper}) {{", 1)
        self._line(
            f'rt_fail_log({RT_ERR_SIZE}u, {loc}, "size mismatch: {param.name}");',
            2,
        )
        self._line(f"return {RT_ERR_SIZE}u;", 2)
        self._line("}", 1)
        self._line(f"if (!rt_disc_eq({var}->data, RT_DISC_{upper})) {{", 1)
        self._line(
            f'rt_fail_log({RT_ERR_DISC}u, {loc}, "discriminator mismatch: {param.name}");',
            2,
        )
        self._line(f"return {RT_ERR_DISC}u;", 2)
        self._line("}", 1)

    def _emit_init(self, param: Any, var: str) -> None:
        """PDA verify + System create_account CPI for one Init param."""
        model = self._accounts.get(param.account)
        if model is None:
            self._diag(
                PS5003,
                None,
                f"`Init[{param.account}]` on `{param.name}` has no model (bug)",
            )
            return
        loc = self._loc(param.line)
        bump = self._find_bump()
        if bump is None:
            self._diag(
                PS5003,
                None,
                f"`Init[{param.account}]` needs a `bump: u8` data parameter",
            )
            bump = "0u"
        payer = self._find_payer()
        if payer is None:
            self._diag(
                PS5003,
                None,
                "Init needs a `Signer` parameter to pay for the account (phase 3)",
            )
            payer = "(RtAccount *)0"
        seed0 = snake_case(param.account)
        self._line("/* init: fresh system-owned PDA, then System create_account */", 1)
        # The CPI needs the System program itself in the caller's accounts.
        self._line("{", 1)
        self._line("uint64_t rt_sys_i = 0u;", 2)
        self._line("uint8_t rt_has_system = 0u;", 2)
        self._line("for (rt_sys_i = 0u; rt_sys_i < rt->n_accounts; rt_sys_i++) {", 2)
        self._line(
            "if (rt_key_eq(rt->accounts[rt_sys_i].key, "
            "(const SolPubkey *)(const void *)RT_SYSTEM_ID)) {",
            3,
        )
        self._line("rt_has_system = 1u;", 4)
        self._line("}", 3)
        self._line("}", 2)
        self._line("if (!rt_has_system) {", 2)
        self._line(
            f'rt_fail_log({RT_ERR_CPI}u, {loc}, "System program account is required: init");',
            3,
        )
        self._line(f"return {RT_ERR_CPI}u;", 3)
        self._line("}", 2)
        self._line("}", 1)
        self._line(f"if (!rt_owner_eq({var}, RT_SYSTEM_ID)) {{", 1)
        self._line(
            f'rt_fail_log({RT_ERR_OWNER}u, {loc}, "{param.name} must be system-owned to init");',
            2,
        )
        self._line(f"return {RT_ERR_OWNER}u;", 2)
        self._line("}", 1)
        self._line(f"if ({var}->data_len != 0u) {{", 1)
        self._line(
            f'rt_fail_log({RT_ERR_SIZE}u, {loc}, "{param.name} is already initialized");',
            2,
        )
        self._line(f"return {RT_ERR_SIZE}u;", 2)
        self._line("}", 1)
        self._line(
            f'if (!rt_verify_pda(rt, {var}, (const uint8_t *)"{seed0}",'
            f" {len(seed0)}u, (uint8_t)({bump}))) {{",
            1,
        )
        self._line(
            f'rt_fail_log({RT_ERR_PDA}u, {loc}, "{param.name} is not the expected PDA");',
            2,
        )
        self._line(f"return {RT_ERR_PDA}u;", 2)
        self._line("}", 1)
        rent = _init_rent_lamports(model.size)
        self._line(
            f"if (rt_system_create_account(rt, {payer}, {var},"
            f' (const uint8_t *)"{seed0}", {len(seed0)}u, (uint8_t)({bump}),'
            f" {rent}u, {model.size}u) != RT_OK) {{",
            1,
        )
        self._line(
            f'rt_fail_log({RT_ERR_CPI}u, {loc}, "System create_account failed");',
            2,
        )
        self._line(f"return {RT_ERR_CPI}u;", 2)
        self._line("}", 1)
        upper = param.account.upper()
        self._line(f"rt_st_disc({var}->data, RT_DISC_{upper});", 1)

    def _find_bump(self) -> str | None:
        for name, (_var, ctype) in self._data_vars.items():
            if name == "bump" and ctype in ("uint8_t", "bool"):
                return f"dp_{name}"
        return None

    def _find_payer(self) -> str | None:
        for param in self._iparams:
            if param.kind == "signer":
                return f"acc_{param.name}"
        return None

    # -- dispatch ----------------------------------------------------------

    def _emit_dispatch_table(self) -> None:
        self._line("static const RtDispatchEntry RT_DISPATCH[] = {", 0)
        for instruction in self._model.instructions:
            disc = ", ".join(f"{byte:#x}u" for byte in instruction.discriminator)
            self._line(
                f"    {{ {{ {disc} }}, &pyf_{instruction.snake_name} }},",
                0,
            )
        self._line("};", 0)
        self._line("", 0)
        self._line("uint64_t entrypoint(const unsigned char *input) {", 0)
        self._line(
            f"return rt_entrypoint(input, RT_DISPATCH, {len(self._model.instructions)}u);",
            1,
        )
        self._line("}", 0)

    # -- statements --------------------------------------------------------

    def _emit_stmt(self, node: ast.stmt, instruction: InstructionModel) -> None:
        if isinstance(node, ast.AnnAssign):
            self._emit_ann_assign(node)
            return
        if isinstance(node, ast.Assign):
            self._emit_assign(node)
            return
        if isinstance(node, ast.AugAssign):
            self._emit_aug_assign(node)
            return
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Call):
                self._emit_require(node.value)
            return
        if isinstance(node, ast.Pass):
            self._line("/* pass */", 1)
            return
        self._diag(
            PS5001,
            node,
            f"unsupported statement `{type(node).__name__}` in "
            f"`{instruction.name}` (phase 3 lowers AnnAssign/Assign/AugAssign/"
            "require)",
        )

    # -- annotated locals --------------------------------------------------

    def _emit_ann_assign(self, node: ast.AnnAssign) -> None:
        if not isinstance(node.target, ast.Name):
            self._diag(PS5001, node, "annotated assigns may only target simple names")
            return
        name = node.target.id
        if name in self._data_vars or name in self._acct_vars:
            self._diag(PS5002, node, f"`{name}` is already a parameter name")
            return
        if name in self._locals:
            self._diag(PS5002, node, f"`{name}` is already declared")
            return
        ann = node.annotation
        if not isinstance(ann, ast.Name):
            self._diag(PS5002, node, "unsupported local type annotation form")
            return
        c_ctype = _LOCAL_TYPES_C.get(ann.id)
        if c_ctype is None:
            self._diag(
                PS5002,
                node,
                f"local type `{ann.id}` is not lowered yet (phase 3 supports "
                "u8/u16/u32/u64/i64/bool/Pubkey)",
            )
            return
        var = f"v_{name}"
        if c_ctype == "int64_t":
            self._line(f"int64_t {var} = 0;", 1)
        elif c_ctype == "SolPubkey":
            self._line(f"SolPubkey {var};", 1)
        else:
            self._line(f"{c_ctype} {var} = 0u;", 1)
        self._locals[name] = (var, c_ctype)
        if node.value is not None:
            self._store_local(name, node.value)
        else:
            self._line(f"(void){var};", 1)

    def _store_local(self, name: str, value: ast.expr) -> None:
        info = self._locals.get(name)
        if info is None:
            self._diag(PS5001, None, f"`{name}` is not declared")
            return
        var, c_ctype = info
        frag = self._load(value)
        if c_ctype == "SolPubkey":
            if frag.kind != "pub":
                self._diag(PS5002, value, "cannot store non-Pubkey into a Pubkey local")
                return
            self._line(f"rt_key_copy(&{var}, {frag.text});", 1)
            return
        if frag.kind == "pub":
            self._diag(PS5002, value, "cannot store a Pubkey into a numeric local")
            return
        self._line(f"{var} = ({c_ctype})({frag.text});", 1)

    # -- plain assigns -------------------------------------------------------

    def _emit_assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._emit_assign_target(target, node.value)

    def _emit_assign_target(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name):
            if target.id not in self._locals:
                self._diag(
                    PS5001,
                    target,
                    f"`{target.id}` is not declared; annotate it once (`x: u64 = ...`)",
                )
                return
            self._store_local(target.id, value)
            return
        self._emit_field_store(target, value)

    def _emit_field_store(self, target: ast.expr, value: ast.expr) -> None:
        if not isinstance(target, ast.Attribute):
            self._diag(PS5001, target, "unsupported assignment target")
            return
        resolved = self._resolve_field(target)
        if resolved is None:
            return
        fmodel, acc_var = resolved
        frag = self._load(value)
        byte_offset = ACCOUNT_DATA_OFFSET + fmodel.offset
        if fmodel.c_type == "SolPubkey":
            if frag.kind != "pub":
                self._diag(PS5002, value, "cannot store non-Pubkey into a Pubkey field")
                return
            self._line(f"rt_st_key({acc_var}->data, {byte_offset}u, {frag.text});", 1)
            return
        if frag.kind == "pub":
            self._diag(PS5002, value, "cannot store a Pubkey into a numeric field")
            return
        self._store_field_value(fmodel, acc_var, frag)

    def _store_field_value(self, fmodel: FieldModel, acc_var: str, frag: _Frag) -> None:
        byte_offset = ACCOUNT_DATA_OFFSET + fmodel.offset
        if fmodel.c_type in ("uint8_t", "bool"):
            self._line(f"{acc_var}->data[{byte_offset}u] = (uint8_t)({frag.text});", 1)
            return
        size = _WIDTH_BYTES[fmodel.c_type]
        self._line(
            f"{_ST_HELPER[size]}({acc_var}->data, {byte_offset}u, {frag.text});",
            1,
        )

    # -- checked arithmetic --------------------------------------------------

    def _emit_aug_assign(self, node: ast.AugAssign) -> None:
        opname = _ARITH_OP_C.get(type(node.op))
        if opname is None:
            self._diag(
                PS5001,
                node,
                f"operator `{type(node.op).__name__}` is not a supported "
                "accumulator (phase 3: += -= *= //= %=)",
            )
            return
        if isinstance(node.target, ast.Attribute):
            resolved = self._resolve_field(node.target)
            if resolved is None:
                return
            fmodel, acc_var = resolved
            self._field_aug(opname, fmodel, acc_var, node, node.value)
            return
        if isinstance(node.target, ast.Name):
            info = self._locals.get(node.target.id)
            if info is None:
                self._diag(PS5001, node, f"`{node.target.id}` is not declared")
                return
            var, c_ctype = info
            self._local_aug(opname, var, c_ctype, node, node.value)
            return
        self._diag(PS5001, node, "unsupported AugAssign target")

    def _field_aug(
        self,
        opname: str,
        fmodel: FieldModel,
        acc_var: str,
        node: ast.AST,
        rhs: ast.expr,
    ) -> None:
        if fmodel.c_type not in ("uint64_t", "int64_t"):
            self._diag(
                PS5002,
                node,
                f"checked arithmetic on `{fmodel.c_type}` fields lands in "
                "phase 4 (use u64/i64 fields)",
            )
            return
        if fmodel.c_type == "uint64_t":
            left = self._load_field(fmodel, acc_var)
            right = self._load(rhs)
            if right.kind == "pub":
                self._diag(PS5002, rhs, "cannot mix Pubkey with numbers")
                return
            accum = self._mk_tmp()
            self._line(f"uint64_t {accum};", 1)
            self._checked_call(opname, left.text, right.text, accum, "u64", node)
            byte_offset = ACCOUNT_DATA_OFFSET + fmodel.offset
            self._line(f"rt_st_u64({acc_var}->data, {byte_offset}u, {accum});", 1)
            return
        left_i = self._load_field(fmodel, acc_var)
        right_i = self._load(rhs)
        if right_i.kind == "pub":
            self._diag(PS5002, rhs, "cannot mix Pubkey with numbers")
            return
        accum_i = self._mk_tmp()
        self._line(f"int64_t {accum_i};", 1)
        self._checked_call(opname, left_i.text, right_i.text, accum_i, "i64", node, div_zero=True)
        byte_offset = ACCOUNT_DATA_OFFSET + fmodel.offset
        self._line(f"rt_st_u64({acc_var}->data, {byte_offset}u, (uint64_t){accum_i});", 1)

    def _local_aug(
        self,
        opname: str,
        var: str,
        c_ctype: str,
        node: ast.AST,
        rhs: ast.expr,
    ) -> None:
        if c_ctype == "SolPubkey":
            self._diag(PS5001, node, "cannot update a Pubkey with arithmetic")
            return
        if c_ctype not in ("uint64_t", "int64_t"):
            self._diag(
                PS5002,
                node,
                f"checked arithmetic on `{c_ctype}` locals lands in phase 4 (use u64/i64)",
            )
            return
        right = self._load(rhs)
        if right.kind == "pub":
            self._diag(PS5002, rhs, "cannot mix Pubkey with numbers")
            return
        if c_ctype == "int64_t":
            accum = self._mk_tmp()
            self._line(f"int64_t {accum};", 1)
            self._checked_call(opname, var, right.text, accum, "i64", node, div_zero=True)
        else:
            accum = self._mk_tmp()
            self._line(f"uint64_t {accum};", 1)
            self._checked_call(opname, var, right.text, accum, "u64", node)
        self._line(f"{var} = {accum};", 1)

    def _checked_call(
        self,
        opname: str,
        left: str,
        right: str,
        accum: str,
        family: str,
        node: ast.AST,
        *,
        div_zero: bool = False,
    ) -> None:
        err = RT_ERR_DIV_ZERO if div_zero and opname in ("div", "mod") else RT_ERR_OVERFLOW
        what = f"checked {opname} ({family})"
        self._line(f"if (rt_checked_{opname}_{family}({left}, {right}, &{accum})) {{", 1)
        self._line(
            f'rt_fail_log({err}u, {self._loc(getattr(node, "lineno", 1) or 1)}, "{what}");',
            2,
        )
        self._line(f"return {err}u;", 2)
        self._line("}", 1)

    # -- field addressing ----------------------------------------------------

    def _resolve_field(self, node: ast.expr) -> tuple[FieldModel, str] | None:
        """Lookup `<account param>.<field>` -> (FieldModel, acc C var)."""
        if not isinstance(node, ast.Attribute):
            self._diag(PS5001, node, "only `account.field` accesses are lowered")
            return None
        if not isinstance(node.value, ast.Name):
            self._diag(PS5001, node, "attribute base must be a parameter name")
            return None
        entry = self._acct_vars.get(node.value.id)
        if entry is None:
            self._diag(
                PS5002,
                node,
                f"`{node.value.id}` is not an account parameter",
            )
            return None
        acc_var, cls = entry
        model = self._accounts.get(cls)
        if model is None:
            self._diag(
                PS5002,
                node,
                f"`{node.value.id}` is a Signer; only `.key` is available",
            )
            return None
        for field in model.fields:
            if field.name == node.attr:
                return field, acc_var
        self._diag(
            PS5001,
            node,
            f"account `{model.name}` has no field `{node.attr}`",
        )
        return None

    def _load_field(self, fmodel: FieldModel, acc_var: str | None) -> _Frag:
        """Emit a load of an account field into a fresh temp (prelude first)."""
        byte_offset = ACCOUNT_DATA_OFFSET + fmodel.offset
        data = f"{acc_var}->data" if acc_var is not None else "acc_unknown->data"
        var = self._mk_tmp()
        if fmodel.c_type == "SolPubkey":
            return _Frag(
                f"(const SolPubkey *)(const void *)({data} + {byte_offset}u)",
                "pub",
            )
        if fmodel.c_type in ("uint8_t", "bool"):
            self._line(f"uint8_t {var} = {data}[{byte_offset}u];", 1)
            return _Frag(var, "uint8_t")
        if fmodel.c_type == "int64_t":
            bits = self._mk_tmp()
            self._line(f"uint64_t {bits} = 0u;", 1)
            self._line(f"rt_ld_u64({data}, {byte_offset}u, &{bits});", 1)
            self._line(f"int64_t {var};", 1)
            self._line(f"{var} = (int64_t){bits};", 1)
            return _Frag(var, "int64_t")
        size = _WIDTH_BYTES[fmodel.c_type]
        self._line(f"uint{size * 8}_t {var} = 0u;", 1)
        self._line(f"{_LD_HELPER[size]}({data}, {byte_offset}u, &{var});", 1)
        return _Frag(var, f"uint{size * 8}_t")

    # -- expression lowering ---------------------------------------------------

    def _load(self, node: ast.expr) -> _Frag:
        """Emit any prelude loads, then return the reactive fragment."""
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool):
                return _Frag("1u" if value else "0u", "bool")
            if isinstance(value, int):
                if -(2**63) <= value <= 2**64 - 1:
                    return _Frag(_c_int_lit(value), "uint64_t")
                self._diag(PS5002, node, "integer literal outside u64/i64 range")
                return _Frag("0u", "uint64_t")
            self._diag(PS5002, node, f"literal {value!r} is not lowered (phase 3)")
            return _Frag("0u", "uint64_t")
        if isinstance(node, ast.Name):
            info = self._locals.get(node.id)
            if info is None:
                info = self._data_vars.get(node.id)
            if info is None:
                self._diag(PS5002, node, f"`{node.id}` is not a lowered name")
                return _Frag("0u", "uint64_t")
            var, c_ctype = info
            if c_ctype == "SolPubkey":
                return _Frag(f"&{var}", "pub")
            return _Frag(var, c_ctype)
        if isinstance(node, ast.Attribute):
            return self._load_attr(node)
        if isinstance(node, ast.Compare):
            return self._load_compare(node)
        if isinstance(node, ast.BoolOp):
            return self._load_boolop(node)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            operand = self._load(node.operand)
            return _Frag(f"!({operand.text})", "bool")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            operand = self._load(node.operand)
            if operand.kind in ("pub", "bool"):
                self._diag(PS5002, node, "unary `-` needs an integer operand")
                return _Frag("0", "int64_t")
            return _Frag(f"(-({operand.text}))", "int64_t")
        if isinstance(node, ast.BinOp):
            self._diag(
                PS5002,
                node,
                "arithmetic inside expressions lands in phase 4; use a local",
            )
            return _Frag("0u", "uint64_t")
        self._diag(PS5002, node, f"expression `{type(node).__name__}` is not lowered (phase 3)")
        return _Frag("0u", "uint64_t")

    def _load_attr(self, node: ast.Attribute) -> _Frag:
        if isinstance(node.value, ast.Name):
            base = node.value.id
            if base in self._acct_vars:
                if node.attr == "key":
                    return _Frag(f"{self._acct_vars[base][0]}->key", "pub")
                fmodel = self._resolve_field(node)
                if fmodel is None:
                    return _Frag("0u", "uint64_t")
                return self._load_field(fmodel[0], fmodel[1])
            if base in self._data_vars:
                var, c_ctype = self._data_vars[base]
                if node.attr == "key" and c_ctype == "SolPubkey":
                    return _Frag(f"&{var}", "pub")
        self._diag(PS5002, node, "attribute is not lowered in phase 3")
        return _Frag("0u", "uint64_t")

    def _load_compare(self, node: ast.Compare) -> _Frag:
        left = self._load(node.left)
        parts: list[str] = []
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            right = self._load(comparator)
            symbol = _COMPARE_C.get(type(op))
            if symbol is None:
                self._diag(PS5002, node, f"comparison `{type(op).__name__}` unsupported")
                return _Frag("0u", "uint64_t")
            parts.append(self._compare_text(left, right, symbol, node))
            left = right
        if len(parts) == 1:
            return _Frag(parts[0], "bool")
        return _Frag("(" + " && ".join(parts) + ")", "bool")

    def _compare_text(self, left: _Frag, right: _Frag, symbol: str, node: ast.AST) -> str:
        if left.kind == "pub" and right.kind == "pub":
            if symbol == "==":
                return f"rt_key_eq({left.text}, {right.text})"
            if symbol == "!=":
                return f"(!rt_key_eq({left.text}, {right.text}))"
            self._diag(PS5002, node, "pubkeys support only == and !=")
            return "0u"
        if left.kind == "pub" or right.kind == "pub":
            self._diag(PS5002, node, "cannot mix Pubkey with numbers in a comparison")
            return "0u"
        return f"({left.text} {symbol} {right.text})"

    def _load_boolop(self, node: ast.BoolOp) -> _Frag:
        joiner = " && " if isinstance(node.op, ast.And) else " || "
        parts: list[str] = []
        for operand in node.values:
            frag = self._load(operand)
            if frag.kind != "bool":
                self._diag(PS5002, operand, "boolean operators need bool operands")
                continue
            parts.append(frag.text)
        if not parts:
            return _Frag("0u", "bool")
        return _Frag("(" + joiner.join(parts) + ")", "bool")

    # -- require -----------------------------------------------------------------

    def _emit_require(self, call: ast.Call) -> None:
        func = call.func
        if not isinstance(func, ast.Name) or func.id != "require":
            self._diag(PS5001, func, "only `require(...)` calls lower (phase 3)")
            return
        if len(call.args) != 2 or call.keywords:
            self._diag(
                PS5001,
                call,
                "require(condition, ERR.Member) needs two positional args",
            )
            return
        cond = self._load(call.args[0])
        if cond.kind != "bool":
            self._diag(PS5002, call.args[0], "require() condition must be bool")
        _code, macro = self._require_error_code(call.args[1])
        text = f"require failed: {self._require_name(call.args[1])}"
        self._line("if (!(" + cond.text + ")) {", 1)
        self._line(
            f'rt_fail_log({macro}, {self._loc(call.lineno)}, "{text}");',
            2,
        )
        self._line(f"return {macro};", 2)
        self._line("}", 1)

    def _require_error_code(self, node: ast.expr) -> tuple[int, str]:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner = node.value.id
            member = node.attr
            code = self._error_codes.get((owner, member))
            if code is not None:
                return code, self._err_macro(owner, member)
        self._diag(PS5002, node, "require() error must be an @error member `Err.Member`")
        return RT_ERR_UNKNOWN, f"{RT_ERR_UNKNOWN}u"

    def _require_name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return f"{node.value.id}.{node.attr}"
        return "?"


def emit_program_c(model: ProgramModel) -> tuple[str, list[Diagnostic]]:
    """Lower ``model`` into C source text plus any emitter diagnostics."""
    emitter = _Emitter(model)
    source = emitter.run()
    return source, emitter.diagnostics
