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

Lowered subset:

* account params: ``Signer``, ``Mut[X]``, ``Account[X]``, ``Init[X]``;
* data params and locals: every integer width through 128, ``bool``, ``Pubkey``,
  and unit enums (one ``uint8_t``, variant ``Status.Open`` is the tag literal);
* ``FixedArray[scalar, N]`` fields and locals, indexed read and write
  (the scalar may be a unit enum);
* ``Option[scalar]`` fields, locals, and instruction arguments: a tag byte
  plus the inner value always reserved. ``None`` clears the tag. ``.is_some``
  and ``.value`` read it; ``.value`` on a clear tag aborts with 1012;
* ``FixedString[N]`` fields, locals, and instruction arguments: a ``u32``
  byte length plus ``N`` reserved bytes. A literal that fits stores the
  UTF-8 bytes. ``len`` reads the stored count. A length past ``N`` aborts
  with 1013;
* statements: assign, checked aug-assign, ``require``, ``if``/``elif``/``else``,
  ``while`` (and ``while``/``else``), ``for x in range(...)``, ``break``,
  ``continue``, bare ``return``, ``match`` on a unit enum;
* plain helpers, inlined at the call (``do { ... } while (0)``) so a
  ``require`` or checked-math abort still returns from the instruction;
* ``emit(Event(...))`` logs ``sha256("event:Name")[..8]`` plus the packed
  fields through ``sol_log_data`` (``rt_log_event``);
* expressions: checked arithmetic (including shifts), bitwise ``&|^``,
  comparisons, ``and``/``or``/``not``, unary ``-``, ``len``, width casts
  such as ``u64(x)`` (narrowing is checked).

Anything else becomes a ``PS500x`` diagnostic (never ``PS9000``), so the
build fails with a stable code instead of a compiler crash.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
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
    DataParamModel,
    EnumModel,
    EventModel,
    FieldModel,
    HelperModel,
    InstructionModel,
    ProgramModel,
    StructModel,
    snake_case,
)

__all__ = [
    "RT_ERR_CONSTRAINT",
    "RT_ERR_CPI",
    "RT_ERR_DISC",
    "RT_ERR_DIV_ZERO",
    "RT_ERR_ENUM",
    "RT_ERR_OOB",
    "RT_ERR_OPTION",
    "RT_ERR_OVERFLOW",
    "RT_ERR_OWNER",
    "RT_ERR_PDA",
    "RT_ERR_SIGNER",
    "RT_ERR_SIZE",
    "RT_ERR_STRING",
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
RT_ERR_ENUM = 1011
RT_ERR_OPTION = 1012
RT_ERR_STRING = 1013
RT_ERR_CONSTRAINT = 1014

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
    "uint128_t": "RtU128",
    "int8_t": "int8_t",
    "int16_t": "int16_t",
    "int32_t": "int32_t",
    "int64_t": "int64_t",
    "int128_t": "RtI128",
    "bool": "uint8_t",
    "SolPubkey": "SolPubkey",
}

_WIDTH_BYTES: dict[str, int] = {
    "uint8_t": 1,
    "uint16_t": 2,
    "uint32_t": 4,
    "uint64_t": 8,
    "uint128_t": 16,
    "int8_t": 1,
    "int16_t": 2,
    "int32_t": 4,
    "int64_t": 8,
    "int128_t": 16,
    "bool": 1,
}

#: rt_checked_<op>_<family> helper suffix per model C type (ADR-0011).
_FAMILY_OF: dict[str, str] = {
    "uint8_t": "u8",
    "uint16_t": "u16",
    "uint32_t": "u32",
    "uint64_t": "u64",
    "uint128_t": "u128",
    "RtU128": "u128",
    "int8_t": "i8",
    "int16_t": "i16",
    "int32_t": "i32",
    "int64_t": "i64",
    "int128_t": "i128",
    "RtI128": "i128",
}

#: The bytewise store helpers take *unsigned* word widths; signed values
#: reinterpret through these before the helper call.
_UNSIGNED_OF: dict[str, str] = {
    "int8_t": "uint8_t",
    "int16_t": "uint16_t",
    "int32_t": "uint32_t",
    "int64_t": "uint64_t",
    "int128_t": "RtU128",
}

_ST_HELPER: dict[int, str] = {2: "rt_st_u16", 4: "rt_st_u32", 8: "rt_st_u64", 16: "rt_st_u128"}
_LD_HELPER: dict[int, str] = {2: "rt_ld_u16", 4: "rt_ld_u32", 8: "rt_ld_u64", 16: "rt_ld_u128"}

_ARITH_OP_C: dict[type, str] = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.FloorDiv: "div",
    ast.Mod: "mod",
    ast.LShift: "shl",
    ast.RShift: "shr",
}

_BIT_OP_C: dict[type, str] = {ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^"}

#: For diagnostics: the checked-opname back to Python's spelling.
_PY_OP: dict[str, str] = {
    "add": "+",
    "sub": "-",
    "mul": "*",
    "div": "//",
    "mod": "%",
    "shl": "<<",
    "shr": ">>",
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
    "u128": "RtU128",
    "i8": "int8_t",
    "i16": "int16_t",
    "i32": "int32_t",
    "i64": "int64_t",
    "i128": "RtI128",
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

    ``literal`` is set when the fragment is a pure integer constant, so a
    later store or operator can re-type it (``u8 + 1`` stays ``u8``).
    """

    text: str
    kind: str
    literal: int | None = None


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _utf8_literal(node: ast.expr) -> bytes | None:
    """UTF-8 bytes of a string constant, or ``None`` when ``node`` is not one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.encode("utf-8")
    return None


@dataclass
class _StrVar:
    """A local or data-parameter fixed string: length plus reserved bytes."""

    length_var: str
    data_var: str
    capacity: int


@dataclass
class _OptVar:
    """A local or data-parameter option: tag byte plus reserved inner value."""

    tag: str
    value: str
    ctype: str
    defined: str


@dataclass
class _Loop:
    """Labels for the innermost ``while`` / ``for`` (break, continue, else)."""

    head: str
    cont: str
    done: str
    flag: str | None


@dataclass
class _Inline:
    """One helper frame. ``result`` is ``None`` when the helper returns nothing.

    ``break`` leaves this frame. User loops lower to ``goto``, so a helper
    ``return`` cannot cancel the caller's loop, and a C ``for`` that copies
    bytes is closed before the ``break``.
    """

    name: str
    result: str | None
    c_type: str
    defined: str


_KIND_META: dict[str, tuple[int, bool]] = {
    "uint8_t": (8, False),
    "uint16_t": (16, False),
    "uint32_t": (32, False),
    "uint64_t": (64, False),
    "RtU128": (128, False),
    "int8_t": (8, True),
    "int16_t": (16, True),
    "int32_t": (32, True),
    "int64_t": (64, True),
    "RtI128": (128, True),
}

_CAST_NAMES: frozenset[str] = frozenset(
    {"u8", "u16", "u32", "u64", "u128", "i8", "i16", "i32", "i64", "i128"}
)


def _canon(kind: str) -> str:
    """Map model C names onto the expression types the runtime helpers use."""
    return {"uint128_t": "RtU128", "int128_t": "RtI128", "bool": "uint8_t"}.get(kind, kind)


def _fits_c(value: int, kind: str) -> bool:
    bits, signed = _KIND_META[_canon(kind)]
    if signed:
        return -(1 << (bits - 1)) <= value <= (1 << (bits - 1)) - 1
    return 0 <= value < (1 << bits)


def _typed_lit(value: int, kind: str) -> str:
    """A C literal of ``kind`` holding ``value`` (caller checked the range)."""
    kind = _canon(kind)
    if kind in ("RtU128", "RtI128"):
        raw = value & ((1 << 128) - 1)
        hi = (raw >> 64) & ((1 << 64) - 1)
        lo = raw & ((1 << 64) - 1)
        composed = f"RT_U128_VAL(0x{hi:x}ULL, 0x{lo:x}ULL)"
        if kind == "RtI128":
            return f"((RtI128){composed})"
        return composed
    if _KIND_META[kind][1] and value < 0:
        return f"(({kind}){value})"
    return f"(({kind}){value}u)"


def _wider_kind(left: str, right: str) -> str:
    """Result width of a binary op: max bits, signed if either side is."""
    lk = _canon(left)
    rk = _canon(right)
    lb, ls = _KIND_META[lk]
    rb, rs = _KIND_META[rk]
    bits = max(lb, rb)
    prefix = "i" if (ls or rs) else "u"
    return _LOCAL_TYPES_C[f"{prefix}{bits}"]


def _widen_safe(src: str, dest: str) -> bool:
    """True when every ``src`` value fits in ``dest`` with a C cast."""
    sb, ss = _KIND_META[src]
    db, ds = _KIND_META[dest]
    if ss == ds:
        return sb <= db
    # Unsigned into a wider signed type (u32 fits in i64; u64 does not fit in i64).
    if (not ss) and ds:
        return db > sb
    return False


def _hi_lit(hi: int) -> str:
    """C literal for an inclusive upper bound used in a cast check."""
    if hi > 2**64 - 1:
        return _typed_lit(hi, "RtU128")
    if hi > 2**63 - 1:
        return f"{hi}ULL"
    return str(hi)


def _bound_lit(value: int) -> str:
    """C literal for a cast-check bound, including negatives wider than i64."""
    if value >= 0:
        return _hi_lit(value)
    # ``-9223372036854775808`` is not a valid signed long-long literal.
    if value == -(2**63):
        return "(-9223372036854775807LL - 1)"
    if value > -(2**63):
        return f"({value}LL)"
    return _typed_lit(value, "RtI128")


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
        self._structs: dict[str, StructModel] = {item.name: item for item in model.structs}
        self._events: dict[str, EventModel] = {item.name: item for item in model.events}
        self._error_codes: dict[tuple[str, str], int] = {
            (error.owner, error.name): error.code for error in model.errors
        }
        self._enums = {enum.name: enum for enum in model.enums}
        # Per-instruction state (reset in `_emit_instruction`).
        self._data_vars: dict[str, tuple[str, str]] = {}
        self._acct_vars: dict[str, tuple[str, str]] = {}
        self._locals: dict[str, tuple[str, str]] = {}
        self._arrays: dict[str, tuple[str, str, int]] = {}
        self._options: dict[str, _OptVar] = {}
        self._strings: dict[str, _StrVar] = {}
        self._value_enum: dict[str, str] = {}
        self._array_enum: dict[str, str] = {}
        self._loops: list[_Loop] = []
        self._loop_no = 0
        self._indent = 1
        self._iparams: list[Any] = []
        self._helpers: dict[str, HelperModel] = {
            helper.name: helper for helper in model.helpers
        }
        self._inline: list[_Inline] = []
        self._instr: InstructionModel | None = None
        self._log_file = ""

    def _s(self, text: str, extra: int = 0) -> None:
        """Emit one body line at the current block indent."""
        self._line(text, self._indent + extra)

    # -- infrastructure ----------------------------------------------------

    @property
    def file(self) -> str:
        """Source file base name used in runtime logs."""
        return self._log_file or self._model.source

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
        self._arrays = {}
        self._options = {}
        self._strings = {}
        self._value_enum = {}
        self._array_enum = {}
        self._loops = []
        self._loop_no = 0
        self._indent = 1
        self._inline = []
        self._instr = instruction
        self._log_file = instruction.source
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
        for param in instruction.account_params:
            if param.close_to:
                self._emit_close(param)
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
            if param.shape == "string":
                self._emit_string_data(param, offset)
                offset += param.size
                continue
            if param.shape == "option":
                self._emit_option_data(param, offset)
                offset += param.size
                continue
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
            elif param.c_type == "int8_t":
                self._line(f"int8_t {var} = 0;", 1)
                self._line(
                    f"{{ uint8_t rt_bits = rt->data[{offset}u]; {var} = (int8_t)rt_bits; }}",
                    1,
                )
                ctype = "int8_t"
            elif param.c_type == "int16_t":
                self._line(f"int16_t {var} = 0;", 1)
                self._line(
                    "{ uint16_t rt_bits = 0u;"
                    f" rt_ld_u16(rt->data, {offset}u, &rt_bits);"
                    f" {var} = (int16_t)rt_bits; }}",
                    1,
                )
                ctype = "int16_t"
            elif param.c_type == "int32_t":
                self._line(f"int32_t {var} = 0;", 1)
                self._line(
                    "{ uint32_t rt_bits = 0u;"
                    f" rt_ld_u32(rt->data, {offset}u, &rt_bits);"
                    f" {var} = (int32_t)rt_bits; }}",
                    1,
                )
                ctype = "int32_t"
            elif param.c_type == "uint128_t":
                self._line(f"RtU128 {var} = 0;", 1)
                self._line(f"rt_ld_u128(rt->data, {offset}u, &{var});", 1)
                ctype = "RtU128"
            elif param.c_type == "int128_t":
                self._line(f"RtI128 {var} = 0;", 1)
                self._line(
                    "{ RtU128 rt_bits = 0;"
                    f" rt_ld_u128(rt->data, {offset}u, &rt_bits);"
                    f" {var} = (RtI128)rt_bits; }}",
                    1,
                )
                ctype = "RtI128"
            else:
                self._line(f"uint64_t {var} = 0u;", 1)
                self._line(f"rt_ld_u64(rt->data, {offset}u, &{var});", 1)
            self._data_vars[param.name] = (var, ctype)
            if param.defined:
                self._value_enum[param.name] = param.defined
            offset += param.size
        for param in instruction.data_params:  # -Wunused silencing (deterministic)
            if param.shape == "string":
                self._line(f"(void)dp_{param.name}_len;", 1)
                self._line(f"(void)dp_{param.name};", 1)
                continue
            if param.shape == "option":
                self._line(f"(void)dp_{param.name}_tag;", 1)
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
        if param.kind == "mint":
            return
        if param.kind == "token":
            self._line(f"if (!{var}->is_writable) {{", 1)
            self._line(
                f'rt_fail_log({RT_ERR_WRITABLE}u, {loc}, "writable required: {param.name}");',
                2,
            )
            self._line(f"return {RT_ERR_WRITABLE}u;", 2)
            self._line("}", 1)
            return
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
        if param.owner_of:
            other = self._acct_vars.get(param.owner_of)
            owner_expr = (
                f"(const uint8_t *)(const void *){other[0]}->key"
                if other is not None
                else "rt->program_id"
            )
            if other is None:
                self._diag(PS5002, None, f"`Owner` on `{param.name}` is not lowered")
            self._line(f"if (!rt_owner_eq({var}, {owner_expr})) {{", 1)
            self._line(
                f'rt_fail_log({RT_ERR_CONSTRAINT}u, {loc}, "owner: {param.name}");',
                2,
            )
            self._line(f"return {RT_ERR_CONSTRAINT}u;", 2)
            self._line("}", 1)
        else:
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
        self._emit_relation_checks(param, var)

    def _emit_relation_checks(self, param: Any, var: str) -> None:
        """HasOne and Address run after the account is known to be ours."""
        loc = self._loc(param.line)
        if param.has_one:
            model = self._accounts.get(param.account)
            field = model.field(param.has_one) if model is not None else None
            other = self._acct_vars.get(param.has_one)
            if field is None or field.c_type != "SolPubkey" or other is None:
                self._diag(PS5002, None, f"`HasOne` on `{param.name}` is not lowered")
            else:
                off = ACCOUNT_DATA_OFFSET + field.offset
                self._line(
                    f"if (!rt_key_eq((const SolPubkey *)(const void *)({var}->data + {off}u),"
                    f" {other[0]}->key)) {{",
                    1,
                )
                self._line(
                    f'rt_fail_log({RT_ERR_CONSTRAINT}u, {loc},'
                    f' "has one: {param.name}.{param.has_one}");',
                    2,
                )
                self._line(f"return {RT_ERR_CONSTRAINT}u;", 2)
                self._line("}", 1)
        if param.address_of:
            data = self._data_vars.get(param.address_of)
            if data is None:
                self._diag(PS5002, None, f"`Address` on `{param.name}` needs a Pubkey argument")
            else:
                self._line(
                    f"if (!rt_key_eq({var}->key, &{data[0]})) {{",
                    1,
                )
                self._line(
                    f'rt_fail_log({RT_ERR_CONSTRAINT}u, {loc},'
                    f' "address: {param.name}");',
                    2,
                )
                self._line(f"return {RT_ERR_CONSTRAINT}u;", 2)
                self._line("}", 1)

    def _emit_close(self, param: Any) -> None:
        """Move lamports to ``close_to``, zero the account, assign the system program."""
        src_entry = self._acct_vars.get(param.name)
        dest_entry = self._acct_vars.get(param.close_to)
        if src_entry is None or dest_entry is None:
            self._diag(PS5002, None, f"`CloseTo` on `{param.name}` is not lowered")
            return
        src = src_entry[0]
        dest = dest_entry[0]
        loc = self._loc(param.line)
        moved = self._mk_tmp()
        rc = self._mk_tmp()
        self._s(f"if (!{dest}->is_writable) {{")
        self._s(
            f'rt_fail_log({RT_ERR_WRITABLE}u, {loc}, "close destination must be writable");',
            1,
        )
        self._s(f"return {RT_ERR_WRITABLE}u;", 1)
        self._s("}")
        self._s(f"uint64_t {moved} = 0u;")
        self._s(
            f"uint64_t {rc} = rt_checked_add_u64(*{dest}->lamports, *{src}->lamports, &{moved});"
        )
        self._s(f"if ({rc} != RT_OK) {{")
        self._s(
            f'rt_fail_log({rc}, {loc}, "checked add (u64)");',
            1,
        )
        self._s(f"return {rc};", 1)
        self._s("}")
        self._s(f"*{dest}->lamports = {moved};")
        self._s(f"*{src}->lamports = 0u;")
        idx = self._mk_tmp()
        self._s(f"uint64_t {idx};")
        self._s(f"for ({idx} = 0u; {idx} < {src}->data_len; {idx}++) {{")
        self._s(f"{src}->data[{idx}] = 0u;", 1)
        self._s("}")
        self._s(f"rt_st_u64({src}->data - 8, 0u, 0u);")
        self._s(
            f"rt_key_copy({src}->owner, (const SolPubkey *)(const void *)RT_SYSTEM_ID);"
        )

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
        seed0 = param.seed or snake_case(param.account)
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
        if isinstance(node, ast.If):
            self._emit_if(node, instruction)
            return
        if isinstance(node, ast.While):
            self._emit_while(node, instruction)
            return
        if isinstance(node, ast.For):
            self._emit_for(node, instruction)
            return
        if isinstance(node, ast.Break):
            self._emit_break(node)
            return
        if isinstance(node, ast.Continue):
            self._emit_continue(node)
            return
        if isinstance(node, ast.Return):
            self._emit_return(node)
            return
        if isinstance(node, ast.Match):
            self._emit_match(node, instruction)
            return
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Call):
                self._emit_call_stmt(node.value)
            return
        if isinstance(node, ast.Pass):
            self._s("/* pass */")
            return
        self._diag(
            PS5001,
            node,
            f"unsupported statement `{type(node).__name__}` in `{instruction.name}`",
        )

    # -- control flow --------------------------------------------------------

    def _emit_if(self, node: ast.If, instruction: InstructionModel) -> None:
        cond = self._load(node.test)
        if cond.kind != "bool":
            self._diag(PS5002, node.test, "if condition must be bool")
        self._s(f"if ({cond.text}) {{")
        self._emit_block(node.body, instruction)
        if node.orelse:
            self._s("} else {")
            self._emit_block(node.orelse, instruction)
        self._s("}")

    def _emit_block(self, stmts: list[ast.stmt], instruction: InstructionModel) -> None:
        self._indent += 1
        for stmt in stmts:
            self._emit_stmt(stmt, instruction)
        self._indent -= 1

    def _emit_while(self, node: ast.While, instruction: InstructionModel) -> None:
        frame = self._push_loop(bool(node.orelse), continue_at_head=True)
        self._s(f"{frame.head}:")
        # Condition temps live in this block so `goto head` does not cross a
        # C declaration (clang rejects that).
        self._s("{")
        self._indent += 1
        cond = self._load(node.test)
        if cond.kind != "bool":
            self._diag(PS5002, node.test, "while condition must be bool")
        self._s(f"if (!({cond.text})) goto {frame.done};")
        for stmt in node.body:
            self._emit_stmt(stmt, instruction)
        self._indent -= 1
        self._s("}")
        self._s(f"goto {frame.head};")
        self._finish_loop(frame, node.orelse, instruction)

    def _emit_for(self, node: ast.For, instruction: InstructionModel) -> None:
        it = node.iter
        if not (
            isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"
        ):
            self._diag(PS5001, node, "only `for x in range(...)` is lowered")
            return
        if not isinstance(node.target, ast.Name):
            self._diag(PS5001, node, "loop variables must be plain names")
            return
        name = node.target.id
        if name in self._locals or name in self._data_vars or name in self._acct_vars:
            self._diag(PS5002, node, f"`{name}` is already declared")
            return
        args = list(it.args)
        if not 1 <= len(args) <= 3:
            self._diag(PS5001, it, "range() takes 1, 2, or 3 arguments")
            return
        start_n, stop_n, step_n = self._range_args(args, node)
        if isinstance(step_n, ast.Constant) and isinstance(step_n.value, int):
            if step_n.value == 0:
                self._diag(PS5002, step_n, "range() step must not be zero")
                return
            if step_n.value < 0:
                self._diag(PS5002, step_n, "range() step must be positive")
                return
        start = self._as_u64(start_n)
        stop = self._as_u64(stop_n)
        step = self._as_u64(step_n)
        var = f"v_{name}"
        self._locals[name] = (var, "uint64_t")
        self._s(f"uint64_t {var} = {start};")
        self._s(f"if ({step} == 0u) {{")
        self._s(
            f'rt_fail_log({RT_ERR_DIV_ZERO}u, {self._loc(node.lineno)}, "range step is zero");',
            1,
        )
        self._s(f"return {RT_ERR_DIV_ZERO}u;", 1)
        self._s("}")
        frame = self._push_loop(bool(node.orelse), continue_at_head=False)
        self._s(f"{frame.head}:")
        self._s(f"if (!({var} < {stop})) goto {frame.done};")
        self._s("{")
        self._emit_block(node.body, instruction)
        self._s("}")
        self._s(f"{frame.cont}:")
        self._s("{")
        self._indent += 1
        nxt = self._mk_tmp()
        self._s(f"uint64_t {nxt};")
        self._checked_call("add", var, step, nxt, "u64", node)
        self._s(f"{var} = {nxt};")
        self._indent -= 1
        self._s("}")
        self._s(f"goto {frame.head};")
        self._finish_loop(frame, node.orelse, instruction)

    def _range_args(
        self, args: list[ast.expr], node: ast.AST
    ) -> tuple[ast.expr, ast.expr, ast.expr]:
        zero = ast.Constant(value=0)
        one = ast.Constant(value=1)
        zero.lineno = getattr(node, "lineno", 1) or 1
        zero.col_offset = getattr(node, "col_offset", 0) or 0
        one.lineno = zero.lineno
        one.col_offset = zero.col_offset
        if len(args) == 1:
            return zero, args[0], one
        if len(args) == 2:
            return args[0], args[1], one
        return args[0], args[1], args[2]

    def _push_loop(self, has_else: bool, *, continue_at_head: bool) -> _Loop:
        self._loop_no += 1
        n = self._loop_no
        flag: str | None = None
        if has_else:
            flag = f"rt_broke_{n}"
            self._s(f"uint8_t {flag} = 0u;")
        head = f"rt_h{n}"
        cont = head if continue_at_head else f"rt_c{n}"
        frame = _Loop(head=head, cont=cont, done=f"rt_d{n}", flag=flag)
        self._loops.append(frame)
        return frame

    def _finish_loop(
        self,
        frame: _Loop,
        orelse: list[ast.stmt],
        instruction: InstructionModel,
    ) -> None:
        self._s(f"{frame.done}: ;")
        if frame.flag is not None:
            self._s(f"if (!{frame.flag}) {{")
            self._emit_block(orelse, instruction)
            self._s("}")
        self._loops.pop()

    def _emit_break(self, node: ast.Break) -> None:
        if not self._loops:
            self._diag(PS5001, node, "`break` is outside a loop")
            return
        frame = self._loops[-1]
        if frame.flag is not None:
            self._s(f"{frame.flag} = 1u;")
        self._s(f"goto {frame.done};")

    def _emit_continue(self, node: ast.Continue) -> None:
        if not self._loops:
            self._diag(PS5001, node, "`continue` is outside a loop")
            return
        self._s(f"goto {self._loops[-1].cont};")

    def _emit_match(self, node: ast.Match, instruction: InstructionModel) -> None:
        """Lower ``match`` on a unit enum to ``if`` / ``else if`` plus a tag check."""
        enum_name = self._enum_of_expr(node.subject)
        if enum_name is None or enum_name not in self._enums:
            self._diag(PS5002, node.subject, "match subject must be a unit enum")
            return
        enum = self._enums[enum_name]
        arms: list[tuple[int, list[ast.stmt]]] = []
        wild: list[ast.stmt] | None = None
        seen: set[int] = set()
        for case in node.cases:
            parsed = self._match_arm(case, enum_name)
            if parsed is None:
                return
            tag, body = parsed
            if tag is None:
                if wild is not None:
                    self._diag(PS5002, case.pattern, "wildcard must be the last match case")
                    return
                wild = body
                continue
            if wild is not None:
                self._diag(PS5002, case.pattern, "wildcard must be the last match case")
                return
            if tag in seen:
                self._diag(PS5002, case.pattern, "variant is already matched")
                return
            seen.add(tag)
            arms.append((tag, body))
        if wild is None:
            missing = [name for name, tag in enum.variants if tag not in seen]
            if missing:
                self._diag(
                    PS5002,
                    node,
                    f"match on `{enum_name}` is not exhaustive; missing {', '.join(missing)}",
                )
                return
        if not arms:
            if wild is not None:
                for stmt in wild:
                    self._emit_stmt(stmt, instruction)
            return
        scrut = self._load(node.subject)
        if _canon(scrut.kind) != "uint8_t":
            self._diag(PS5002, node.subject, "match subject must be a unit enum")
            return
        for index, (tag, body) in enumerate(arms):
            keyword = "if" if index == 0 else "} else if"
            self._s(f"{keyword} ({scrut.text} == {tag}u) {{")
            self._emit_block(body, instruction)
        self._s("} else {")
        if wild is not None:
            self._emit_block(wild, instruction)
        else:
            line = getattr(node, "lineno", 1) or 1
            self._s(
                f'rt_fail_log({RT_ERR_ENUM}u, {self._loc(line)}, "invalid enum tag");',
                1,
            )
            self._s(f"return {RT_ERR_ENUM}u;", 1)
        self._s("}")

    def _match_arm(
        self, case: ast.match_case, enum_name: str
    ) -> tuple[int | None, list[ast.stmt]] | None:
        if case.guard is not None:
            self._diag(PS5001, case.guard, "match guards are not supported")
            return None
        pattern = case.pattern
        if isinstance(pattern, ast.MatchAs) and pattern.pattern is None and pattern.name is None:
            return None, case.body
        if isinstance(pattern, ast.MatchValue) and isinstance(pattern.value, ast.Attribute):
            value = pattern.value
            if isinstance(value.value, ast.Name) and value.value.id == enum_name:
                for variant, tag in self._enums[enum_name].variants:
                    if variant == value.attr:
                        return tag, case.body
                self._diag(PS5002, pattern, f"`{enum_name}` has no variant `{value.attr}`")
                return None
        self._diag(PS5001, pattern, "match cases must be `Enum.Variant` or `_`")
        return None

    def _enum_of_expr(self, node: ast.expr) -> str | None:
        """Unit-enum name of a value, or ``None`` when it is not one."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            helper = self._helpers.get(node.func.id)
            if helper is not None and helper.return_defined:
                return helper.return_defined
        if isinstance(node, ast.Name):
            return self._value_enum.get(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            found = self._lookup_field(node)
            if found is not None:
                leaf, _acc = found
                if leaf.defined and leaf.shape not in ("option", "struct", "string"):
                    return leaf.defined
        if isinstance(node, ast.Attribute) and node.attr == "value":
            meta = self._option_meta(node.value)
            if meta is not None and meta[1]:
                return meta[1]
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base = node.value.id
            if base in self._enums:
                return base
            entry = self._acct_vars.get(base)
            if entry is None:
                return None
            account = self._accounts.get(entry[1])
            if account is None:
                return None
            field = account.field(node.attr)
            if field is not None and field.defined and field.shape != "option":
                return field.defined
            return None
        if isinstance(node, ast.Subscript):
            target = node.value
            if isinstance(target, ast.Name):
                return self._array_enum.get(target.id)
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                entry = self._acct_vars.get(target.value.id)
                if entry is None:
                    return None
                account = self._accounts.get(entry[1])
                if account is None:
                    return None
                field = account.field(target.attr)
                if field is not None and field.shape == "array" and field.defined:
                    return field.defined
        return None

    def _emit_return(self, node: ast.Return) -> None:
        if self._inline:
            self._emit_helper_return(node)
            return
        if node.value is not None and not (
            isinstance(node.value, ast.Constant) and node.value.value is None
        ):
            self._diag(PS5001, node, "only a bare `return` is lowered")
            return
        self._s("return 0u;")

    def _emit_helper_return(self, node: ast.Return) -> None:
        frame = self._inline[-1]
        bare = node.value is None or (
            isinstance(node.value, ast.Constant) and node.value.value is None
        )
        if frame.result is None:
            if not bare:
                self._diag(PS5002, node, "this helper returns nothing")
            self._s("break;")
            return
        if bare or node.value is None:
            self._diag(PS5002, node, "helper must return a value")
            self._s("break;")
            return
        frag = self._load(node.value)
        self._store_frag(frame.result, frame.c_type, frag, node.value)
        self._s("break;")

    def _emit_call_stmt(self, call: ast.Call) -> None:
        func = call.func
        if isinstance(func, ast.Name) and func.id == "require":
            self._emit_require(call)
            return
        if isinstance(func, ast.Name) and func.id == "emit":
            self._emit_event(call)
            return
        if isinstance(func, ast.Name) and func.id == "system_transfer":
            self._emit_system_transfer(call)
            return
        if isinstance(func, ast.Name) and func.id in ("token_transfer", "token2022_transfer"):
            self._emit_token_transfer(call, func.id == "token2022_transfer")
            return
        if isinstance(func, ast.Name) and func.id == "ata_create":
            self._emit_ata_create(call)
            return
        if isinstance(func, ast.Name) and func.id in _CAST_NAMES:
            self._diag(PS5001, call, "a cast is not a statement; store the result")
            return
        if isinstance(func, ast.Name) and func.id in self._helpers:
            self._inline_helper(call, self._helpers[func.id], as_value=False)
            return
        self._diag(
            PS5001,
            func,
            "only `require`, `emit`, and `system_transfer` calls are statements",
        )

    def _inline_helper(self, call: ast.Call, helper: HelperModel, *, as_value: bool) -> _Frag:
        """Inline ``helper`` in the caller. Arguments are evaluated first.

        The helper's maps replace the caller's for the body, so it cannot see
        accounts it was not passed. ``break`` stores the result and leaves the
        ``do``/``while``; checked math still ``return``s from the instruction.
        """
        if self._instr is None:
            self._diag(PS5001, call, "a helper call is outside an instruction")
            return _Frag("0u", "uint64_t")
        if len(self._inline) >= 8 or any(frame.name == helper.name for frame in self._inline):
            self._diag(PS5002, call, f"helper `{helper.name}` recurses or is too deep")
            return _Frag("0u", "uint64_t")
        if call.keywords or len(call.args) != len(helper.params):
            self._diag(
                PS5001,
                call,
                f"`{helper.name}()` takes {len(helper.params)} argument(s)",
            )
            return _Frag("0u", "uint64_t")
        if as_value and not helper.return_c:
            self._diag(PS5002, call, f"`{helper.name}` returns nothing")
            return _Frag("0u", "uint64_t")

        bound_locals: dict[str, tuple[str, str]] = {}
        bound_accounts: dict[str, tuple[str, str]] = {}
        bound_enums: dict[str, str] = {}
        for arg, param in zip(call.args, helper.params, strict=False):
            if param.kind == "account":
                if not isinstance(arg, ast.Name) or arg.id not in self._acct_vars:
                    self._diag(PS5002, arg, "pass an account parameter by name")
                    continue
                acc_var, cls = self._acct_vars[arg.id]
                if param.account != "Pubkey" and cls != param.account:
                    self._diag(PS5002, arg, f"expected account `{param.account}`")
                    continue
                bound_accounts[param.name] = (acc_var, cls)
                continue
            if (
                param.c_type == "SolPubkey"
                and isinstance(arg, ast.Name)
                and arg.id in self._acct_vars
            ):
                acc_var = self._acct_vars[arg.id][0]
                tmp = self._mk_tmp()
                self._s(f"SolPubkey {tmp};")
                self._s(f"rt_key_copy(&{tmp}, {acc_var}->key);")
                bound_locals[param.name] = (tmp, "SolPubkey")
                continue
            frag = self._load(arg)
            tmp = self._mk_tmp()
            ctype = self._declare_zero(tmp, param.c_type)
            self._store_frag(tmp, ctype, frag, arg)
            bound_locals[param.name] = (tmp, ctype)
            if param.defined:
                bound_enums[param.name] = param.defined

        result_var: str | None = None
        result_c = ""
        if helper.return_c:
            result_var = self._mk_tmp()
            result_c = self._declare_zero(result_var, helper.return_c)

        saved = (
            self._locals,
            self._acct_vars,
            self._arrays,
            self._options,
            self._strings,
            self._value_enum,
            self._array_enum,
            self._loops,
        )
        self._locals = bound_locals
        self._acct_vars = bound_accounts
        self._arrays = {}
        self._options = {}
        self._strings = {}
        self._value_enum = bound_enums
        self._array_enum = {}
        self._loops = []
        self._inline.append(
            _Inline(helper.name, result_var, result_c, helper.return_defined)
        )
        saved_log = self._log_file
        if helper.source:
            self._log_file = helper.source
        try:
            self._s("do {")
            self._indent += 1
            for _name, (var, _ctype) in bound_locals.items():
                self._s(f"(void){var};")
            for _name, (var, _cls) in bound_accounts.items():
                self._s(f"(void){var};")
            for stmt in helper.body:
                self._emit_stmt(stmt, self._instr)
            self._indent -= 1
            self._s("} while (0);")
        finally:
            self._log_file = saved_log
            self._inline.pop()
            (
                self._locals,
                self._acct_vars,
                self._arrays,
                self._options,
                self._strings,
                self._value_enum,
                self._array_enum,
                self._loops,
            ) = saved
        if result_var is None:
            return _Frag("0u", "uint64_t")
        if not as_value:
            self._s(f"(void){result_var};")
            return _Frag("0u", "uint64_t")
        if result_c == "SolPubkey":
            return _Frag(f"&{result_var}", "pub")
        if helper.return_c == "bool":
            return _Frag(result_var, "bool")
        return _Frag(result_var, result_c)

    def _declare_zero(self, var: str, model_c: str) -> str:
        """Declare ``var`` zeroed. Returns the expression C type."""
        ctype = _WIDTH_C.get(model_c, model_c)
        if ctype == "SolPubkey":
            self._s(f"SolPubkey {var} = {{{{0}}}};")
        elif ctype in ("RtU128", "RtI128") or ctype.startswith("int"):
            self._s(f"{ctype} {var} = 0;")
        else:
            self._s(f"{ctype} {var} = 0u;")
        return ctype

    def _store_frag(self, var: str, ctype: str, frag: _Frag, node: ast.AST) -> None:
        if ctype == "SolPubkey":
            if frag.kind != "pub":
                self._diag(PS5002, node, "cannot store a non-Pubkey into a Pubkey")
                return
            self._s(f"rt_key_copy(&{var}, {frag.text});")
            return
        if frag.kind == "pub":
            self._diag(PS5002, node, "cannot store a Pubkey into a number")
            return
        text = frag.text
        if _canon(frag.kind) != _canon(ctype):
            text = self._coerce_numeric(frag, ctype, node)
        self._s(f"{var} = ({ctype})({text});")

    # -- fixed-width options -----------------------------------------------

    def _emit_option_data(self, param: DataParamModel, offset: int) -> None:
        """Load a tag byte and the reserved inner value from instruction data."""
        tag = f"dp_{param.name}_tag"
        var = f"dp_{param.name}"
        self._s(f"uint8_t {tag} = rt->data[{offset}u];")
        ctype = self._emit_loaded_var(var, param.c_type, offset + 1, "rt->data")
        self._options[param.name] = _OptVar(tag, var, ctype, param.defined)

    def _emit_loaded_var(self, var: str, c_type: str, offset: int, data: str) -> str:
        """Declare ``var`` and load one scalar. Returns the expression C type."""
        if c_type == "SolPubkey":
            self._s(f"SolPubkey {var};")
            self._s(
                "rt_key_copy(&"
                f"{var}, (const SolPubkey *)(const void *)({data} + {offset}u));"
            )
            return "SolPubkey"
        if c_type in ("bool", "uint8_t"):
            self._s(f"uint8_t {var} = {data}[{offset}u];")
            return "uint8_t"
        if c_type == "int8_t":
            self._s(f"int8_t {var} = 0;")
            self._s(f"{{ uint8_t rt_bits = {data}[{offset}u]; {var} = (int8_t)rt_bits; }}")
            return "int8_t"
        if c_type == "uint16_t":
            self._s(f"uint16_t {var} = 0u;")
            self._s(f"rt_ld_u16({data}, {offset}u, &{var});")
            return "uint16_t"
        if c_type == "uint32_t":
            self._s(f"uint32_t {var} = 0u;")
            self._s(f"rt_ld_u32({data}, {offset}u, &{var});")
            return "uint32_t"
        if c_type == "int16_t":
            self._s(f"int16_t {var} = 0;")
            self._s(
                "{ uint16_t rt_bits = 0u;"
                f" rt_ld_u16({data}, {offset}u, &rt_bits); {var} = (int16_t)rt_bits; }}"
            )
            return "int16_t"
        if c_type == "int32_t":
            self._s(f"int32_t {var} = 0;")
            self._s(
                "{ uint32_t rt_bits = 0u;"
                f" rt_ld_u32({data}, {offset}u, &rt_bits); {var} = (int32_t)rt_bits; }}"
            )
            return "int32_t"
        if c_type == "int64_t":
            self._s(f"int64_t {var} = 0;")
            self._s(
                "{ uint64_t rt_bits = 0u;"
                f" rt_ld_u64({data}, {offset}u, &rt_bits); {var} = (int64_t)rt_bits; }}"
            )
            return "int64_t"
        if c_type == "uint128_t":
            self._s(f"RtU128 {var} = 0;")
            self._s(f"rt_ld_u128({data}, {offset}u, &{var});")
            return "RtU128"
        if c_type == "int128_t":
            self._s(f"RtI128 {var} = 0;")
            self._s(
                "{ RtU128 rt_bits = 0;"
                f" rt_ld_u128({data}, {offset}u, &rt_bits); {var} = (RtI128)rt_bits; }}"
            )
            return "RtI128"
        self._s(f"uint64_t {var} = 0u;")
        self._s(f"rt_ld_u64({data}, {offset}u, &{var});")
        return "uint64_t"

    def _option_ann(self, ann: ast.Subscript) -> tuple[str, str] | None:
        """``(model c type, inner enum name)`` for ``Option[scalar]``."""
        if not isinstance(ann.value, ast.Name) or ann.value.id != "Option":
            return None
        items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        if len(items) != 1 or not isinstance(items[0], ast.Name):
            return None
        inner = items[0].id
        if inner in self._enums:
            return "uint8_t", inner
        mapped = {
            "u8": "uint8_t",
            "u16": "uint16_t",
            "u32": "uint32_t",
            "u64": "uint64_t",
            "u128": "uint128_t",
            "i8": "int8_t",
            "i16": "int16_t",
            "i32": "int32_t",
            "i64": "int64_t",
            "i128": "int128_t",
            "bool": "bool",
            "Pubkey": "SolPubkey",
        }.get(inner)
        if mapped is None:
            return None
        return mapped, ""

    def _emit_option_local(self, node: ast.AnnAssign, name: str, ann: ast.Subscript) -> None:
        parsed = self._option_ann(ann)
        if parsed is None:
            self._diag(PS5002, node, "only `Option[scalar]` locals are lowered")
            return
        model_c, defined = parsed
        ctype = "SolPubkey" if model_c == "SolPubkey" else _canon(model_c)
        tag = f"v_{name}_tag"
        var = f"v_{name}"
        self._s(f"uint8_t {tag} = 0u;")
        if ctype == "SolPubkey":
            self._s(f"SolPubkey {var} = {{{{0}}}};")
        elif ctype in ("RtU128", "RtI128") or ctype.startswith("int"):
            self._s(f"{ctype} {var} = 0;")
        else:
            self._s(f"{ctype} {var} = 0u;")
        binding = _OptVar(tag, var, ctype, defined)
        self._options[name] = binding
        if node.value is not None:
            self._store_option_var(binding, node.value)
            return
        self._s(f"(void){tag};")
        self._s(f"(void){var};")

    def _peek_field(self, node: ast.expr) -> tuple[FieldModel, str] | None:
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            return None
        entry = self._acct_vars.get(node.value.id)
        if entry is None:
            return None
        acc_var, cls = entry
        account = self._accounts.get(cls)
        if account is None:
            return None
        field = account.field(node.attr)
        if field is None:
            return None
        return field, acc_var

    def _peek_option_field(self, node: ast.expr) -> tuple[FieldModel, str] | None:
        peeked = self._peek_field(node)
        if peeked is None or peeked[0].shape != "option":
            return None
        return peeked

    def _option_meta(self, node: ast.expr) -> tuple[str, str] | None:
        """``(inner ctype, enum name)`` when ``node`` is a whole option."""
        if isinstance(node, ast.Name):
            bound = self._options.get(node.id)
            if bound is None:
                return None
            return bound.ctype, bound.defined
        peeked = self._peek_option_field(node)
        if peeked is None:
            return None
        field, _acc = peeked
        ctype = "SolPubkey" if field.c_type == "SolPubkey" else _canon(field.c_type)
        return ctype, field.defined

    def _option_tag_expr(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            bound = self._options.get(node.id)
            if bound is None:
                return None
            return bound.tag
        peeked = self._peek_option_field(node)
        if peeked is None:
            return None
        field, acc = peeked
        return f"{acc}->data[{ACCOUNT_DATA_OFFSET + field.offset}u]"

    def _load_option_attr(self, node: ast.Attribute) -> _Frag | None:
        if node.attr not in ("is_some", "value"):
            return None
        tag = self._option_tag_expr(node.value)
        if tag is None:
            return None
        if node.attr == "is_some":
            return _Frag(f"({tag} == 1u)", "bool")
        line = getattr(node, "lineno", 1) or 1
        self._s(f"if ({tag} != 1u) {{")
        self._s(
            f'rt_fail_log({RT_ERR_OPTION}u, {self._loc(line)}, "option is none");',
            1,
        )
        self._s(f"return {RT_ERR_OPTION}u;", 1)
        self._s("}")
        return self._load_option_inner(node.value)

    def _load_option_inner(self, node: ast.expr) -> _Frag:
        if isinstance(node, ast.Name):
            bound = self._options.get(node.id)
            if bound is None:
                self._diag(PS5002, node, "read `.is_some` or `.value`")
                return _Frag("0u", "uint64_t")
            if bound.ctype == "SolPubkey":
                return _Frag(f"&{bound.value}", "pub")
            return _Frag(bound.value, bound.ctype)
        peeked = self._peek_option_field(node)
        if peeked is None:
            self._diag(PS5002, node, "read `.is_some` or `.value`")
            return _Frag("0u", "uint64_t")
        field, acc = peeked
        off = f"{ACCOUNT_DATA_OFFSET + field.offset + 1}u"
        return self._load_field(field, acc, offset_expr=off)

    def _store_option_var(self, binding: _OptVar, value: ast.expr) -> None:
        if isinstance(value, ast.IfExp):
            cond = self._load(value.test)
            if cond.kind != "bool":
                self._diag(PS5002, value.test, "conditional test must be bool")
            self._s(f"if ({cond.text}) {{")
            self._indent += 1
            self._store_option_var(binding, value.body)
            self._indent -= 1
            self._s("} else {")
            self._indent += 1
            self._store_option_var(binding, value.orelse)
            self._indent -= 1
            self._s("}")
            return
        if _is_none(value):
            self._clear_opt_var(binding)
            return
        if isinstance(value, ast.Name) and value.id in self._options:
            self._copy_opt_var(binding, self._options[value.id])
            return
        peeked = self._peek_option_field(value)
        if peeked is not None:
            tag = self._option_tag_expr(value)
            if tag is None:
                return
            inner = self._load_option_inner(value)
            self._s(f"{binding.tag} = {tag};")
            self._write_opt_var_value(binding, inner, value)
            return
        frag = self._load(value)
        self._s(f"{binding.tag} = 1u;")
        self._write_opt_var_value(binding, frag, value)

    def _clear_opt_var(self, binding: _OptVar) -> None:
        self._s(f"{binding.tag} = 0u;")
        if binding.ctype == "SolPubkey":
            self._s(f"{{ SolPubkey rt_z = {{{{0}}}}; rt_key_copy(&{binding.value}, &rt_z); }}")
            return
        if binding.ctype in ("RtU128", "RtI128") or binding.ctype.startswith("int"):
            self._s(f"{binding.value} = 0;")
            return
        self._s(f"{binding.value} = 0u;")

    def _copy_opt_var(self, dst: _OptVar, src: _OptVar) -> None:
        self._s(f"{dst.tag} = {src.tag};")
        if dst.ctype == "SolPubkey":
            self._s(f"rt_key_copy(&{dst.value}, &{src.value});")
            return
        self._s(f"{dst.value} = {src.value};")

    def _write_opt_var_value(self, binding: _OptVar, frag: _Frag, at: ast.AST) -> None:
        if binding.ctype == "SolPubkey":
            if frag.kind != "pub":
                self._diag(PS5002, at, "cannot store non-Pubkey into an Option[Pubkey]")
                return
            self._s(f"rt_key_copy(&{binding.value}, {frag.text});")
            return
        if frag.kind == "pub":
            self._diag(PS5002, at, "cannot store a Pubkey into this option")
            return
        text = frag.text
        if _canon(frag.kind) != _canon(binding.ctype):
            text = self._coerce_numeric(frag, binding.ctype, at)
        self._s(f"{binding.value} = ({binding.ctype})({text});")

    def _store_option_field(self, field: FieldModel, acc: str, value: ast.expr) -> None:
        off = ACCOUNT_DATA_OFFSET + field.offset
        if isinstance(value, ast.IfExp):
            cond = self._load(value.test)
            if cond.kind != "bool":
                self._diag(PS5002, value.test, "conditional test must be bool")
            self._s(f"if ({cond.text}) {{")
            self._indent += 1
            self._store_option_field(field, acc, value.body)
            self._indent -= 1
            self._s("} else {")
            self._indent += 1
            self._store_option_field(field, acc, value.orelse)
            self._indent -= 1
            self._s("}")
            return
        if _is_none(value):
            self._s(f"{acc}->data[{off}u] = 0u;")
            self._zero_option_field(field, acc, off + 1)
            return
        if isinstance(value, ast.Name) and value.id in self._options:
            src = self._options[value.id]
            self._s(f"{acc}->data[{off}u] = {src.tag};")
            self._store_inner_at(field, acc, off + 1, self._frag_opt_var(src), value)
            return
        peeked = self._peek_option_field(value)
        if peeked is not None:
            tmp = self._mk_tmp()
            tag = self._option_tag_expr(value)
            if tag is None:
                return
            inner = self._load_option_inner(value)
            self._s(f"uint8_t {tmp} = {tag};")
            self._s(f"{acc}->data[{off}u] = {tmp};")
            self._store_inner_at(field, acc, off + 1, inner, value)
            return
        frag = self._load(value)
        self._s(f"{acc}->data[{off}u] = 1u;")
        self._store_inner_at(field, acc, off + 1, frag, value)

    def _frag_opt_var(self, binding: _OptVar) -> _Frag:
        if binding.ctype == "SolPubkey":
            return _Frag(f"&{binding.value}", "pub")
        return _Frag(binding.value, binding.ctype)

    def _zero_option_field(self, field: FieldModel, acc: str, data_off: int) -> None:
        if field.c_type == "SolPubkey":
            tmp = self._mk_tmp()
            self._s(f"SolPubkey {tmp} = {{{{0}}}};")
            self._s(f"rt_st_key({acc}->data, {data_off}u, &{tmp});")
            return
        kind = "SolPubkey" if field.c_type == "SolPubkey" else _canon(field.c_type)
        zero = "0" if kind.startswith("int") or kind in ("RtU128", "RtI128") else "0u"
        self._store_inner_at(field, acc, data_off, _Frag(zero, kind), None)

    def _store_inner_at(
        self,
        field: FieldModel,
        acc: str,
        data_off: int,
        frag: _Frag,
        at: ast.AST | None,
    ) -> None:
        off = f"{data_off}u"
        if field.c_type == "SolPubkey":
            if frag.kind != "pub":
                self._diag(PS5002, at, "cannot store non-Pubkey into an Option[Pubkey]")
                return
            self._s(f"rt_st_key({acc}->data, {off}, {frag.text});")
            return
        if frag.kind == "pub":
            self._diag(PS5002, at, "cannot store a Pubkey into this option")
            return
        self._store_field_value(field, acc, frag, offset_expr=off, at=at)

    # -- fixed-width strings (u32 length + N reserved bytes) ---------------

    def _emit_string_data(self, param: DataParamModel, offset: int) -> None:
        """Load a ``u32`` length and ``N`` payload bytes. Length past ``N`` is 1013."""
        capacity = param.length
        length_var = f"dp_{param.name}_len"
        data_var = f"dp_{param.name}"
        self._s(f"uint32_t {length_var} = 0u;")
        self._s(f"rt_ld_u32(rt->data, {offset}u, &{length_var});")
        self._fail_long_string(length_var, capacity, param.line)
        self._s(f"uint8_t {data_var}[{capacity}];")
        idx = self._mk_tmp()
        self._s(f"uint32_t {idx};")
        self._s(f"for ({idx} = 0u; {idx} < {capacity}u; {idx}++) {{")
        self._s(f"{data_var}[{idx}] = rt->data[{offset + 4}u + {idx}];", 1)
        self._s("}")
        self._strings[param.name] = _StrVar(length_var, data_var, capacity)

    def _fixed_string_ann(self, ann: ast.Subscript) -> int | None:
        if not isinstance(ann.value, ast.Name) or ann.value.id != "FixedString":
            return None
        items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        if len(items) != 1:
            return None
        count = items[0]
        if (
            not isinstance(count, ast.Constant)
            or isinstance(count.value, bool)
            or not isinstance(count.value, int)
            or not 1 <= count.value <= 4096
        ):
            return None
        return count.value

    def _emit_string_local(self, node: ast.AnnAssign, name: str, ann: ast.Subscript) -> None:
        capacity = self._fixed_string_ann(ann)
        if capacity is None:
            self._diag(PS5002, node, "only `FixedString[N]` locals are lowered")
            return
        length_var = f"v_{name}_len"
        data_var = f"v_{name}"
        self._s(f"uint32_t {length_var} = 0u;")
        self._s(f"uint8_t {data_var}[{capacity}] = {{0}};")
        binding = _StrVar(length_var, data_var, capacity)
        self._strings[name] = binding
        if node.value is not None:
            self._store_string_var(binding, node.value)
            return
        self._s(f"(void){length_var};")
        self._s(f"(void){data_var};")

    def _store_string_var(self, binding: _StrVar, value: ast.expr) -> None:
        if isinstance(value, ast.IfExp):
            cond = self._load(value.test)
            if cond.kind != "bool":
                self._diag(PS5002, value.test, "conditional test must be bool")
            self._s(f"if ({cond.text}) {{")
            self._indent += 1
            self._store_string_var(binding, value.body)
            self._indent -= 1
            self._s("} else {")
            self._indent += 1
            self._store_string_var(binding, value.orelse)
            self._indent -= 1
            self._s("}")
            return
        raw = _utf8_literal(value)
        if raw is not None:
            if len(raw) > binding.capacity:
                self._diag(PS5002, value, "string literal does not fit this FixedString")
                return
            self._s(f"{binding.length_var} = {len(raw)}u;")
            self._paint_bytes(binding.data_var, binding.capacity, raw)
            return
        if isinstance(value, ast.Name) and value.id in self._strings:
            self._copy_string_var(binding, self._strings[value.id], value)
            return
        field_src = self._string_field(value)
        if field_src is not None:
            self._copy_field_to_var(binding, field_src[0], field_src[1], value)
            return
        self._diag(
            PS5002,
            value,
            "a fixed string stores a literal or another FixedString of the same size",
        )

    def _store_string_field(self, field: FieldModel, acc: str, value: ast.expr) -> None:
        if isinstance(value, ast.IfExp):
            cond = self._load(value.test)
            if cond.kind != "bool":
                self._diag(PS5002, value.test, "conditional test must be bool")
            self._s(f"if ({cond.text}) {{")
            self._indent += 1
            self._store_string_field(field, acc, value.body)
            self._indent -= 1
            self._s("} else {")
            self._indent += 1
            self._store_string_field(field, acc, value.orelse)
            self._indent -= 1
            self._s("}")
            return
        off = ACCOUNT_DATA_OFFSET + field.offset
        raw = _utf8_literal(value)
        if raw is not None:
            if len(raw) > field.length:
                self._diag(PS5002, value, "string literal does not fit this FixedString")
                return
            self._s(f"rt_st_u32({acc}->data, {off}u, {len(raw)}u);")
            self._paint_bytes(self._payload_ptr(acc, off + 4), field.length, raw)
            return
        if isinstance(value, ast.Name) and value.id in self._strings:
            src = self._strings[value.id]
            if src.capacity != field.length:
                self._diag(PS5002, value, "fixed strings have different sizes")
                return
            line = getattr(value, "lineno", 1) or 1
            self._fail_long_string(src.length_var, field.length, line)
            self._s(f"rt_st_u32({acc}->data, {off}u, {src.length_var});")
            self._copy_bytes(self._payload_ptr(acc, off + 4), src.data_var, field.length)
            return
        field_src = self._string_field(value)
        if field_src is not None:
            src_field, src_acc = field_src
            if src_field.length != field.length:
                self._diag(PS5002, value, "fixed strings have different sizes")
                return
            length = self._read_u32(src_acc, ACCOUNT_DATA_OFFSET + src_field.offset)
            line = getattr(value, "lineno", 1) or 1
            self._fail_long_string(length, field.length, line)
            self._s(f"rt_st_u32({acc}->data, {off}u, {length});")
            src_ptr = self._payload_ptr(src_acc, ACCOUNT_DATA_OFFSET + src_field.offset + 4)
            self._copy_bytes(self._payload_ptr(acc, off + 4), src_ptr, field.length)
            return
        self._diag(
            PS5002,
            value,
            "a fixed string stores a literal or another FixedString of the same size",
        )

    def _copy_string_var(self, dst: _StrVar, src: _StrVar, at: ast.expr) -> None:
        if dst.capacity != src.capacity:
            self._diag(PS5002, at, "fixed strings have different sizes")
            return
        line = getattr(at, "lineno", 1) or 1
        self._fail_long_string(src.length_var, dst.capacity, line)
        self._s(f"{dst.length_var} = {src.length_var};")
        self._copy_bytes(dst.data_var, src.data_var, dst.capacity)

    def _copy_field_to_var(
        self,
        dst: _StrVar,
        field: FieldModel,
        acc: str,
        at: ast.expr,
    ) -> None:
        if field.length != dst.capacity:
            self._diag(PS5002, at, "fixed strings have different sizes")
            return
        length = self._read_u32(acc, ACCOUNT_DATA_OFFSET + field.offset)
        line = getattr(at, "lineno", 1) or 1
        self._fail_long_string(length, dst.capacity, line)
        self._s(f"{dst.length_var} = {length};")
        src = self._payload_ptr(acc, ACCOUNT_DATA_OFFSET + field.offset + 4)
        self._copy_bytes(dst.data_var, src, dst.capacity)

    def _string_field(self, node: ast.expr) -> tuple[FieldModel, str] | None:
        peeked = self._peek_field(node)
        if peeked is None or peeked[0].shape != "string":
            return None
        return peeked

    def _fail_long_string(self, length_expr: str, capacity: int, line: int) -> None:
        self._s(f"if ((uint32_t)({length_expr}) > {capacity}u) {{")
        self._s(
            f"rt_fail_log({RT_ERR_STRING}u, {self._loc(line)}, "
            '"FixedString length is past its reserved bytes");',
            1,
        )
        self._s(f"return {RT_ERR_STRING}u;", 1)
        self._s("}")

    def _read_u32(self, acc: str, byte_off: int) -> str:
        tmp = self._mk_tmp()
        self._s(f"uint32_t {tmp} = 0u;")
        self._s(f"rt_ld_u32({acc}->data, {byte_off}u, &{tmp});")
        return tmp

    def _payload_ptr(self, acc: str, byte_off: int) -> str:
        ptr = self._mk_tmp()
        self._s(f"uint8_t *{ptr} = {acc}->data + {byte_off}u;")
        return ptr

    def _paint_bytes(self, dest: str, capacity: int, raw: bytes) -> None:
        """Write ``raw`` then zero the rest of the reserved payload. No globals."""
        if capacity <= 0:
            return
        if not raw:
            self._zero_bytes(dest, capacity)
            return
        src = self._mk_tmp()
        parts = ", ".join(f"{byte}u" for byte in raw)
        self._s(f"uint8_t {src}[{len(raw)}] = {{{parts}}};")
        idx = self._mk_tmp()
        self._s(f"uint32_t {idx};")
        self._s(f"for ({idx} = 0u; {idx} < {capacity}u; {idx}++) {{")
        self._s(f"{dest}[{idx}] = ({idx} < {len(raw)}u ? {src}[{idx}] : 0u);", 1)
        self._s("}")

    def _copy_bytes(self, dest: str, src: str, count: int) -> None:
        if count <= 0:
            return
        idx = self._mk_tmp()
        self._s(f"uint32_t {idx};")
        self._s(f"for ({idx} = 0u; {idx} < {count}u; {idx}++) {{")
        self._s(f"{dest}[{idx}] = {src}[{idx}];", 1)
        self._s("}")

    def _zero_bytes(self, dest: str, count: int) -> None:
        if count <= 0:
            return
        idx = self._mk_tmp()
        self._s(f"uint32_t {idx};")
        self._s(f"for ({idx} = 0u; {idx} < {count}u; {idx}++) {{")
        self._s(f"{dest}[{idx}] = 0u;", 1)
        self._s("}")

    # -- annotated locals --------------------------------------------------

    def _emit_ann_assign(self, node: ast.AnnAssign) -> None:
        if not isinstance(node.target, ast.Name):
            self._diag(PS5001, node, "annotated assigns may only target simple names")
            return
        name = node.target.id
        if name in self._data_vars or name in self._acct_vars:
            self._diag(PS5002, node, f"`{name}` is already a parameter name")
            return
        bound = self._options.get(name)
        if bound is not None and bound.tag.startswith("dp_"):
            self._diag(PS5002, node, f"`{name}` is already a parameter name")
            return
        if name in self._strings and self._strings[name].length_var.startswith("dp_"):
            self._diag(PS5002, node, f"`{name}` is already a parameter name")
            return
        if (
            name in self._locals
            or name in self._arrays
            or name in self._options
            or name in self._strings
        ):
            self._diag(PS5002, node, f"`{name}` is already declared")
            return
        ann = node.annotation
        if isinstance(ann, ast.Subscript):
            if isinstance(ann.value, ast.Name) and ann.value.id == "FixedString":
                self._emit_string_local(node, name, ann)
                return
            if isinstance(ann.value, ast.Name) and ann.value.id == "Option":
                self._emit_option_local(node, name, ann)
                return
            self._emit_array_local(node, name, ann)
            return
        if not isinstance(ann, ast.Name):
            self._diag(PS5002, node, "unsupported local type annotation form")
            return
        c_ctype = _LOCAL_TYPES_C.get(ann.id)
        enum_name = ann.id if ann.id in self._enums else ""
        if c_ctype is None and enum_name:
            c_ctype = "uint8_t"
        if c_ctype is None:
            self._diag(
                PS5002,
                node,
                f"local type `{ann.id}` is not lowered "
                "(supported: integer widths, bool, Pubkey, FixedArray[scalar, N], "
                "unit enums, Option[scalar])",
            )
            return
        var = f"v_{name}"
        if c_ctype == "SolPubkey":
            self._s(f"SolPubkey {var};")
        elif c_ctype in ("RtU128", "RtI128") or c_ctype.startswith("int"):
            self._s(f"{c_ctype} {var} = 0;")
        else:
            self._s(f"{c_ctype} {var} = 0u;")
        self._locals[name] = (var, c_ctype)
        if enum_name:
            self._value_enum[name] = enum_name
        if node.value is not None:
            self._store_local(name, node.value)
        else:
            self._s(f"(void){var};")

    def _emit_array_local(self, node: ast.AnnAssign, name: str, ann: ast.Subscript) -> None:
        parsed = self._fixed_array_ann(ann)
        if parsed is None:
            self._diag(PS5002, node, "only `FixedArray[scalar, N]` locals are lowered")
            return
        ctype, length = parsed
        var = f"v_{name}"
        self._s(f"{ctype} {var}[{length}] = {{0}};")
        self._arrays[name] = (var, ctype, length)
        items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        if items and isinstance(items[0], ast.Name) and items[0].id in self._enums:
            self._array_enum[name] = items[0].id
        if node.value is not None:
            self._emit_array_init(var, ctype, length, node.value)

    def _emit_array_init(
        self, var: str, ctype: str, length: int, value: ast.expr
    ) -> None:
        """Fill a FixedArray local from a list comprehension."""
        if not isinstance(value, ast.ListComp):
            self._diag(PS5002, value, "assign array elements with `name[i] = ...`")
            return
        gen = value.generators[0] if len(value.generators) == 1 else None
        if gen is None or not isinstance(gen.target, ast.Name):
            self._diag(PS5002, value, "unsupported list comprehension")
            return
        name = gen.target.id
        ivar = f"v_{name}"
        self._locals[name] = (ivar, "uint64_t")
        self._loop_no += 1
        tag = self._loop_no
        self._s("{")
        self._indent += 1
        self._s(f"uint64_t {ivar} = 0u;")
        self._s(f"rt_h{tag}:")
        self._s(f"if (!({ivar} < {length}u)) goto rt_d{tag};")
        self._store_array_element(var, ctype, ivar, value.elt)
        self._s(f"{ivar} = {ivar} + 1u;")
        self._s(f"goto rt_h{tag};")
        self._s(f"rt_d{tag}: ;")
        self._indent -= 1
        self._s("}")
        self._locals.pop(name, None)

    def _store_array_element(
        self, var: str, ctype: str, index: str, value: ast.expr
    ) -> None:
        frag = self._load(value)
        if ctype == "SolPubkey":
            if frag.kind != "pub":
                self._diag(PS5002, value, "cannot store a non-Pubkey into a Pubkey array")
                return
            self._s(f"rt_key_copy(&{var}[{index}], {frag.text});")
            return
        text = frag.text
        if _canon(frag.kind) != _canon(ctype):
            text = self._coerce_numeric(frag, ctype, value)
        self._s(f"{var}[{index}] = ({ctype})({text});")

    def _fixed_array_ann(self, ann: ast.Subscript) -> tuple[str, int] | None:
        if not isinstance(ann.value, ast.Name) or ann.value.id != "FixedArray":
            return None
        items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        if len(items) != 2 or not isinstance(items[0], ast.Name):
            return None
        if items[0].id in self._enums:
            ctype: str | None = "uint8_t"
        else:
            ctype = _LOCAL_TYPES_C.get(items[0].id)
        count = items[1]
        if (
            ctype is None
            or not isinstance(count, ast.Constant)
            or isinstance(count.value, bool)
            or not isinstance(count.value, int)
            or not 1 <= count.value <= 4096
        ):
            return None
        return ctype, count.value

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
            self._s(f"rt_key_copy(&{var}, {frag.text});")
            return
        if frag.kind == "pub":
            self._diag(PS5002, value, "cannot store a Pubkey into a numeric local")
            return
        text = frag.text
        if _canon(frag.kind) != _canon(c_ctype):
            text = self._coerce_numeric(frag, c_ctype, value)
        self._s(f"{var} = ({c_ctype})({text});")

    # -- plain assigns -------------------------------------------------------

    def _emit_assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._emit_assign_target(target, node.value)

    def _emit_assign_target(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name):
            if target.id in self._options:
                self._store_option_var(self._options[target.id], value)
                return
            if target.id in self._strings:
                self._store_string_var(self._strings[target.id], value)
                return
            if target.id not in self._locals:
                self._diag(
                    PS5001,
                    target,
                    f"`{target.id}` is not declared; annotate it once (`x: u64 = ...`)",
                )
                return
            self._store_local(target.id, value)
            return
        if isinstance(target, ast.Subscript):
            self._emit_subscript_store(target, value)
            return
        self._emit_field_store(target, value)

    def _emit_field_store(self, target: ast.expr, value: ast.expr) -> None:
        if not isinstance(target, ast.Attribute):
            self._diag(PS5001, target, "unsupported assignment target")
            return
        if target.attr == "value" and self._store_enum_value(target, value):
            return
        resolved = self._resolve_field(target)
        if resolved is None:
            return
        fmodel, acc_var = resolved
        if fmodel.shape == "array":
            self._diag(PS5001, target, f"index `{fmodel.name}[i]` to write one element")
            return
        if fmodel.shape == "option":
            self._store_option_field(fmodel, acc_var, value)
            return
        if fmodel.shape == "string":
            self._store_string_field(fmodel, acc_var, value)
            return
        if fmodel.shape == "struct":
            self._copy_struct(fmodel, acc_var, value)
            return
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

    def _store_field_value(
        self,
        fmodel: FieldModel,
        acc_var: str,
        frag: _Frag,
        offset_expr: str | None = None,
        at: ast.AST | None = None,
    ) -> None:
        """Store one numeric field value (casting signeds to their raw word)."""
        if frag.kind != "pub" and _canon(frag.kind) != _canon(fmodel.c_type):
            text = self._coerce_numeric(frag, fmodel.c_type, at)
            frag = _Frag(text, _canon(fmodel.c_type))
        off = offset_expr if offset_expr is not None else f"{ACCOUNT_DATA_OFFSET + fmodel.offset}u"
        size = _WIDTH_BYTES[fmodel.c_type]
        if size == 1:
            # One byte: store the raw bits directly (works for i8/u8/bool).
            self._s(f"{acc_var}->data[{off}] = (uint8_t)({frag.text});")
            self._zero_enum_payload(fmodel, acc_var, off)
            return
        value = frag.text
        if fmodel.c_type in _UNSIGNED_OF:
            value = f"({_UNSIGNED_OF[fmodel.c_type]})({value})"
        self._s(f"{_ST_HELPER[size]}({acc_var}->data, {off}, {value});")

    # -- checked arithmetic --------------------------------------------------

    def _emit_aug_assign(self, node: ast.AugAssign) -> None:
        opname = _ARITH_OP_C.get(type(node.op))
        if opname is None:
            self._diag(
                PS5001,
                node,
                f"operator `{type(node.op).__name__}` is not a supported "
                "accumulator (+= -= *= //= %= <<= >>=)",
            )
            return
        if isinstance(node.target, ast.Subscript):
            self._diag(
                PS5001,
                node,
                "index updates use `a[i] = a[i] + x` (checked, same width)",
            )
            return
        if isinstance(node.target, ast.Attribute):
            resolved = self._resolve_field(node.target)
            if resolved is None:
                return
            fmodel, acc_var = resolved
            if fmodel.shape == "array":
                self._diag(PS5001, node.target, f"index `{fmodel.name}[i]` before updating it")
                return
            if fmodel.shape == "option":
                self._diag(PS5002, node, "an option is not a number; assign `None` or a value")
                return
            if fmodel.shape == "string":
                self._diag(PS5002, node, "a fixed string is not a number")
                return
            self._field_aug(opname, fmodel, acc_var, node, node.value)
            return
        if isinstance(node.target, ast.Name):
            if node.target.id in self._options:
                self._diag(PS5002, node, "an option is not a number; assign `None` or a value")
                return
            if node.target.id in self._strings:
                self._diag(PS5002, node, "a fixed string is not a number")
                return
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
        family = _FAMILY_OF.get(fmodel.c_type)
        if family is None:
            self._diag(
                PS5002,
                node,
                f"cannot `{_PY_OP[opname]}`-assign a `{fmodel.c_type}` field",
            )
            return
        left = self._load_field(fmodel, acc_var)
        right = self._load(rhs)
        if right.kind == "pub":
            self._diag(PS5002, rhs, "cannot mix Pubkey with numbers")
            return
        dest = _WIDTH_C[fmodel.c_type]
        right_text = right.text
        if _canon(right.kind) != _canon(dest):
            right_text = self._coerce_numeric(right, dest, rhs)
        accum = self._mk_tmp()
        self._s(f"{dest} {accum};")
        self._checked_call(opname, left.text, right_text, accum, family, node)
        self._store_field_value(fmodel, acc_var, _Frag(accum, dest))

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
        family = _FAMILY_OF.get(c_ctype)
        if family is None:
            self._diag(
                PS5002,
                node,
                f"cannot `{_PY_OP[opname]}`-assign a `{c_ctype}` local",
            )
            return
        right = self._load(rhs)
        if right.kind == "pub":
            self._diag(PS5002, rhs, "cannot mix Pubkey with numbers")
            return
        right_text = right.text
        if _canon(right.kind) != _canon(c_ctype):
            right_text = self._coerce_numeric(right, c_ctype, rhs)
        accum = self._mk_tmp()
        self._s(f"{c_ctype} {accum};")
        self._checked_call(opname, var, right_text, accum, family, node)
        self._s(f"{var} = ({c_ctype})({accum});")

    def _checked_call(
        self,
        opname: str,
        left: str,
        right: str,
        accum: str,
        family: str,
        node: ast.AST,
    ) -> None:
        """Emit one rt_checked_<op>_<family> call with the real error code.

        The runtime helpers return ``RT_OK`` or the actual RT_ERR_* code, so
        div-zero aborts log 1010 and arithmetic overflow logs 1009 — the
        distinction carried by ``refrt`` holds in the generated C.
        """
        rc = self._mk_tmp()
        what = f"checked {opname} ({family})"
        self._s(f"uint64_t {rc} = rt_checked_{opname}_{family}({left}, {right}, &{accum});")
        self._s(f"if ({rc} != RT_OK) {{")
        self._s(
            f'rt_fail_log({rc}, {self._loc(getattr(node, "lineno", 1) or 1)}, "{what}");',
            1,
        )
        self._s(f"return {rc};", 1)
        self._s("}")

    # -- field addressing ----------------------------------------------------

    def _copy_struct(self, dest: FieldModel, dest_acc: str, value: ast.expr) -> None:
        """Copy one fixed struct onto another. Both sides are account fields."""
        if not isinstance(value, ast.Attribute):
            self._diag(PS5002, value, "copy a struct from another account field")
            return
        found = self._resolve_field(value)
        if found is None:
            return
        src, src_acc = found
        if src.shape != "struct" or src.defined != dest.defined or src.size != dest.size:
            self._diag(PS5002, value, f"cannot copy this value onto `{dest.defined}`")
            return
        self._copy_span(
            dest_acc,
            ACCOUNT_DATA_OFFSET + dest.offset,
            src_acc,
            ACCOUNT_DATA_OFFSET + src.offset,
            dest.size,
        )

    def _copy_span(
        self,
        dest_acc: str,
        dest_off: int,
        src_acc: str,
        src_off: int,
        count: int,
    ) -> None:
        if count <= 0:
            return
        idx = self._mk_tmp()
        self._s(f"uint32_t {idx};")
        self._s(f"for ({idx} = 0u; {idx} < {count}u; {idx}++) {{")
        self._s(
            f"{dest_acc}->data[{dest_off}u + {idx}] = {src_acc}->data[{src_off}u + {idx}];",
            1,
        )
        self._s("}")

    def _lookup_field(self, node: ast.expr) -> tuple[FieldModel, str] | None:
        """Quiet lookup of ``account.a.b``. The leaf offset is within the account payload."""
        names: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            names.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name) or not names:
            return None
        names.reverse()
        entry = self._acct_vars.get(current.id)
        if entry is None:
            return None
        acc_var, cls = entry
        account = self._accounts.get(cls)
        if account is None:
            return None
        field = account.field(names[0])
        if field is None:
            return None
        base = field.offset
        leaf = field
        for attr in names[1:]:
            if leaf.shape != "struct":
                return None
            struct = self._structs.get(leaf.defined)
            if struct is None:
                return None
            inner = struct.field(attr)
            if inner is None:
                return None
            base += inner.offset
            leaf = inner
        if base != leaf.offset:
            leaf = replace(leaf, offset=base)
        return leaf, acc_var

    def _resolve_field(self, node: ast.expr) -> tuple[FieldModel, str] | None:
        """Lookup `account.field` or `account.struct.leaf` -> (FieldModel, acc C var)."""
        if not isinstance(node, ast.Attribute):
            self._diag(PS5001, node, "only `account.field` accesses are lowered")
            return None
        if not isinstance(node.value, ast.Name):
            found = self._lookup_field(node)
            if found is None:
                self._diag(PS5002, node, "no such nested field")
                return None
            return found
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

    def _load_field(
        self,
        fmodel: FieldModel,
        acc_var: str | None,
        offset_expr: str | None = None,
    ) -> _Frag:
        """Emit a load of an account field (or one array element) into a temp."""
        off = offset_expr if offset_expr is not None else f"{ACCOUNT_DATA_OFFSET + fmodel.offset}u"
        data = f"{acc_var}->data" if acc_var is not None else "acc_unknown->data"
        var = self._mk_tmp()
        if fmodel.c_type == "SolPubkey":
            return _Frag(f"(const SolPubkey *)(const void *)({data} + {off})", "pub")
        if fmodel.c_type in ("uint8_t", "bool"):
            self._s(f"uint8_t {var} = {data}[{off}];")
            return _Frag(var, "uint8_t")
        if fmodel.c_type == "int128_t":
            bits = self._mk_tmp()
            self._s(f"RtU128 {bits} = 0;")
            self._s(f"rt_ld_u128({data}, {off}, &{bits});")
            self._s(f"RtI128 {var} = (RtI128){bits};")
            return _Frag(var, "RtI128")
        if fmodel.c_type in ("int8_t", "int16_t", "int32_t", "int64_t"):
            size = _WIDTH_BYTES[fmodel.c_type]
            bits = self._mk_tmp()
            if size == 8:
                self._s(f"uint64_t {bits} = 0u;")
                self._s(f"rt_ld_u64({data}, {off}, &{bits});")
            elif size == 1:
                self._s(f"uint8_t {bits} = {data}[{off}];")
            else:
                self._s(f"uint{size * 8}_t {bits} = 0u;")
                self._s(f"{_LD_HELPER[size]}({data}, {off}, &{bits});")
            ctype = _WIDTH_C[fmodel.c_type]
            self._s(f"{ctype} {var} = ({ctype})(({fmodel.c_type}){bits});")
            return _Frag(var, ctype)
        size = _WIDTH_BYTES[fmodel.c_type]
        if size == 8:
            self._s(f"uint64_t {var} = 0u;")
            self._s(f"rt_ld_u64({data}, {off}, &{var});")
        else:
            ctype = _WIDTH_C[fmodel.c_type]
            self._s(f"{ctype} {var} = 0;")
            self._s(f"{_LD_HELPER[size]}({data}, {off}, &{var});")
        return _Frag(var, _WIDTH_C[fmodel.c_type])

    # -- expression lowering ---------------------------------------------------

    def _load(self, node: ast.expr) -> _Frag:
        """Emit any prelude loads, then return the reactive fragment."""
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool):
                return _Frag("1u" if value else "0u", "bool")
            if isinstance(value, int):
                return self._int_literal(value, node)
            self._diag(PS5002, node, f"literal {value!r} is not lowered")
            return _Frag("0u", "uint64_t")
        if isinstance(node, ast.Name):
            if node.id in self._arrays:
                self._diag(PS5002, node, f"index `{node.id}[i]` before using it")
                return _Frag("0u", "uint64_t")
            if node.id in self._options:
                self._diag(
                    PS5002,
                    node,
                    "read `.is_some` or `.value`, or assign the whole option",
                )
                return _Frag("0u", "uint64_t")
            if node.id in self._strings:
                self._diag(PS5002, node, "index the string or call `len`")
                return _Frag("0u", "uint64_t")
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
        if isinstance(node, ast.Subscript):
            return self._load_subscript(node)
        if isinstance(node, ast.Compare):
            return self._load_compare(node)
        if isinstance(node, ast.BoolOp):
            return self._load_boolop(node)
        if isinstance(node, ast.IfExp):
            return self._load_ifexp(node)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            operand = self._load(node.operand)
            return _Frag(f"!({operand.text})", "bool")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return self._load_negate(node)
        if isinstance(node, ast.BinOp):
            return self._load_binop(node)
        if isinstance(node, ast.Call):
            return self._load_call(node)
        self._diag(PS5002, node, f"expression `{type(node).__name__}` is not lowered")
        return _Frag("0u", "uint64_t")

    def _int_literal(self, value: int, node: ast.AST) -> _Frag:
        if not -(2**127) <= value <= 2**128 - 1:
            self._diag(PS5002, node, "integer literal outside i128/u128 range")
            return _Frag("0u", "uint64_t")
        if value < 0:
            if value >= -(2**63):
                return _Frag(_c_int_lit(value), "int64_t", literal=value)
            return _Frag(_typed_lit(value, "RtI128"), "RtI128", literal=value)
        if value <= 2**64 - 1:
            return _Frag(_c_int_lit(value), "uint64_t", literal=value)
        return _Frag(_typed_lit(value, "RtU128"), "RtU128", literal=value)

    def _load_attr(self, node: ast.Attribute) -> _Frag:
        if node.attr == "value":
            loaded = self._load_enum_value(node)
            if loaded is not None:
                return loaded
        projected = self._load_option_attr(node)
        if projected is not None:
            return projected
        if isinstance(node.value, ast.Name):
            base = node.value.id
            enum = self._enums.get(base)
            if enum is not None:
                for variant, tag in enum.variants:
                    if variant == node.attr:
                        return _Frag(f"{tag}u", "uint8_t", literal=tag)
                self._diag(PS5002, node, f"`{base}` has no variant `{node.attr}`")
                return _Frag("0u", "uint8_t")
            if base in self._acct_vars:
                if node.attr == "key":
                    return _Frag(f"{self._acct_vars[base][0]}->key", "pub")
                fmodel = self._resolve_field(node)
                if fmodel is None:
                    return _Frag("0u", "uint64_t")
                return self._load_resolved(node, fmodel)
            if base in self._data_vars:
                var, c_ctype = self._data_vars[base]
                if node.attr == "key" and c_ctype == "SolPubkey":
                    return _Frag(f"&{var}", "pub")
        if isinstance(node.value, ast.Attribute):
            resolved = self._resolve_field(node)
            if resolved is None:
                return _Frag("0u", "uint64_t")
            return self._load_resolved(node, resolved)
        self._diag(PS5002, node, "attribute is not lowered in phase 3")
        return _Frag("0u", "uint64_t")

    def _load_resolved(
        self,
        node: ast.Attribute,
        resolved: tuple[FieldModel, str],
    ) -> _Frag:
        field, acc_var = resolved
        if field.shape == "struct":
            self._diag(PS5002, node, "read a field of the struct, or copy the whole struct")
            return _Frag("0u", "uint64_t")
        if field.shape in ("array", "vec"):
            self._diag(PS5002, node, f"index `{field.name}[i]` before using it")
            return _Frag("0u", "uint64_t")
        if field.shape == "option":
            self._diag(
                PS5002,
                node,
                "read `.is_some` or `.value`, or assign the whole option",
            )
            return _Frag("0u", "uint64_t")
        if field.shape == "string":
            self._diag(PS5002, node, "index the string or call `len`")
            return _Frag("0u", "uint64_t")
        return self._load_field(field, acc_var)

    def _load_compare(self, node: ast.Compare) -> _Frag:
        left = self._load(node.left)
        parts: list[str] = []
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            right = self._load(comparator)
            symbol = _COMPARE_C.get(type(op))
            if symbol is None:
                self._diag(PS5002, node, f"comparison `{type(op).__name__}` unsupported")
                return _Frag("0u", "uint64_t")
            left, right = self._align_pair(left, right, comparator)
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

    def _coerce_numeric(self, frag: _Frag, dest: str, node: ast.AST | None) -> str:
        """Expression of C type ``dest`` (checked when the value might not fit)."""
        dest_c = _canon(dest)
        src = _canon(frag.kind)
        if src not in _KIND_META or dest_c not in _KIND_META:
            self._diag(PS5002, node, "expected an integer")
            return "0"
        if frag.literal is not None:
            if not _fits_c(frag.literal, dest_c):
                self._diag(PS5002, node, f"literal {frag.literal} does not fit in `{dest_c}`")
                return "0"
            if src == dest_c:
                return frag.text
            return _typed_lit(frag.literal, dest_c)
        if src == dest_c:
            return frag.text
        if _widen_safe(src, dest_c):
            return f"(({dest_c})({frag.text}))"
        tmp = self._mk_tmp()
        self._emit_fit_check(frag.text, src, dest_c, node)
        self._s(f"{dest_c} {tmp} = ({dest_c})({frag.text});")
        return tmp

    def _emit_fit_check(self, text: str, src: str, dest: str, node: ast.AST | None) -> None:
        """Abort with 1009 when ``text`` (type ``src``) does not fit in ``dest``."""
        sb, ss = _KIND_META[src]
        db, ds = _KIND_META[dest]
        line = getattr(node, "lineno", 1) or 1
        loc = self._loc(line)
        if ds and not ss:
            hi = (1 << (db - 1)) - 1
            cond = f"({text}) > {_bound_lit(hi)}"
        elif ss and not ds:
            if db >= sb:
                cond = f"({text}) < 0"
            else:
                hi = (1 << db) - 1
                cond = f"({text}) < 0 || ({text}) > {_bound_lit(hi)}"
        elif ds and ss:
            lo = -(1 << (db - 1))
            hi = (1 << (db - 1)) - 1
            cond = f"({text}) < {_bound_lit(lo)} || ({text}) > {_bound_lit(hi)}"
        else:
            hi = (1 << db) - 1
            cond = f"({text}) > {_bound_lit(hi)}"
        self._s(f"if ({cond}) {{")
        self._s(f'rt_fail_log({RT_ERR_OVERFLOW}u, {loc}, "cast out of range");', 1)
        self._s(f"return {RT_ERR_OVERFLOW}u;", 1)
        self._s("}")

    def _align_pair(self, left: _Frag, right: _Frag, node: ast.AST) -> tuple[_Frag, _Frag]:
        if left.kind in ("pub", "bool") or right.kind in ("pub", "bool"):
            return left, right
        if _canon(left.kind) not in _KIND_META or _canon(right.kind) not in _KIND_META:
            return left, right
        if right.literal is not None and _fits_c(right.literal, left.kind):
            kind = _canon(left.kind)
            text = right.text if _canon(right.kind) == kind else _typed_lit(right.literal, kind)
            return left, _Frag(text, kind, literal=right.literal)
        if left.literal is not None and _fits_c(left.literal, right.kind):
            kind = _canon(right.kind)
            text = left.text if _canon(left.kind) == kind else _typed_lit(left.literal, kind)
            return _Frag(text, kind, literal=left.literal), right
        if _canon(left.kind) == _canon(right.kind):
            return left, right
        dest = _wider_kind(left.kind, right.kind)
        return (
            _Frag(self._coerce_numeric(left, dest, node), dest),
            _Frag(self._coerce_numeric(right, dest, node), dest),
        )

    def _binop_dest(self, left: _Frag, right: _Frag) -> str:
        if (
            left.literal is not None
            and right.literal is None
            and _canon(right.kind) in _KIND_META
            and _fits_c(left.literal, right.kind)
        ):
            return _canon(right.kind)
        if (
            right.literal is not None
            and left.literal is None
            and _canon(left.kind) in _KIND_META
            and _fits_c(right.literal, left.kind)
        ):
            return _canon(left.kind)
        if _canon(left.kind) in _KIND_META and _canon(right.kind) in _KIND_META:
            return _wider_kind(left.kind, right.kind)
        return "uint64_t"

    def _load_binop(self, node: ast.BinOp) -> _Frag:
        if type(node.op) in _BIT_OP_C:
            return self._load_bitop(node)
        opname = _ARITH_OP_C.get(type(node.op))
        if opname is None:
            self._diag(PS5002, node, f"operator `{type(node.op).__name__}` is not lowered")
            return _Frag("0u", "uint64_t")
        left = self._load(node.left)
        right = self._load(node.right)
        if left.kind in ("pub", "bool") or right.kind in ("pub", "bool"):
            self._diag(PS5002, node, "arithmetic needs integer operands")
            return _Frag("0u", "uint64_t")
        dest = self._binop_dest(left, right)
        left_text = self._coerce_numeric(left, dest, node.left)
        right_text = self._coerce_numeric(right, dest, node.right)
        accum = self._mk_tmp()
        self._s(f"{dest} {accum};")
        self._checked_call(opname, left_text, right_text, accum, _FAMILY_OF[dest], node)
        return _Frag(accum, dest)

    def _load_bitop(self, node: ast.BinOp) -> _Frag:
        left = self._load(node.left)
        right = self._load(node.right)
        if left.kind in ("pub", "bool") or right.kind in ("pub", "bool"):
            self._diag(PS5002, node, "bitwise operators need integer operands")
            return _Frag("0u", "uint64_t")
        if _canon(left.kind) not in _KIND_META or _canon(right.kind) not in _KIND_META:
            self._diag(PS5002, node, "bitwise operators need integer operands")
            return _Frag("0u", "uint64_t")
        dest = self._binop_dest(left, right)
        left_text = self._coerce_numeric(left, dest, node.left)
        right_text = self._coerce_numeric(right, dest, node.right)
        symbol = _BIT_OP_C[type(node.op)]
        return _Frag(f"(({dest})(({left_text}) {symbol} ({right_text})))", dest)

    def _load_negate(self, node: ast.UnaryOp) -> _Frag:
        operand_node = node.operand
        if (
            isinstance(operand_node, ast.Constant)
            and isinstance(operand_node.value, int)
            and not isinstance(operand_node.value, bool)
        ):
            return self._int_literal(-operand_node.value, node)
        operand = self._load(operand_node)
        dest = _canon(operand.kind)
        if dest not in _KIND_META:
            self._diag(PS5002, node, "unary `-` needs an integer operand")
            return _Frag("0", "int64_t")
        accum = self._mk_tmp()
        self._s(f"{dest} {accum};")
        self._checked_call("sub", _typed_lit(0, dest), operand.text, accum, _FAMILY_OF[dest], node)
        return _Frag(accum, dest)

    def _load_call(self, node: ast.Call) -> _Frag:
        func = node.func
        if not isinstance(func, ast.Name):
            self._diag(PS5002, node, "unsupported call")
            return _Frag("0u", "uint64_t")
        if func.id == "len":
            return self._load_len(node)
        if func.id in _CAST_NAMES:
            if len(node.args) != 1 or node.keywords:
                self._diag(PS5002, node, f"`{func.id}(...)` takes one integer")
                return _Frag("0u", "uint64_t")
            dest = _LOCAL_TYPES_C[func.id]
            frag = self._load(node.args[0])
            return _Frag(self._coerce_numeric(frag, dest, node.args[0]), dest)
        helper = self._helpers.get(func.id)
        if helper is not None:
            return self._inline_helper(node, helper, as_value=True)
        self._diag(PS5002, node, f"call `{func.id}` is not an expression")
        return _Frag("0u", "uint64_t")

    def _load_len(self, node: ast.Call) -> _Frag:
        if len(node.args) != 1:
            self._diag(PS5002, node, "len() takes one argument")
            return _Frag("0u", "uint64_t")
        arg = node.args[0]
        if isinstance(arg, ast.Name) and arg.id in self._arrays:
            length = self._arrays[arg.id][2]
            return _Frag(f"{length}u", "uint64_t", literal=length)
        if isinstance(arg, ast.Name) and arg.id in self._strings:
            return _Frag(f"(uint64_t){self._strings[arg.id].length_var}", "uint64_t")
        if isinstance(arg, ast.Attribute):
            resolved = self._resolve_field(arg)
            if resolved is not None and resolved[0].shape == "array":
                length = resolved[0].length
                return _Frag(f"{length}u", "uint64_t", literal=length)
            if resolved is not None and resolved[0].shape == "vec":
                field, acc = resolved
                tmp = self._mk_tmp()
                off = ACCOUNT_DATA_OFFSET + field.offset
                self._s(f"uint32_t {tmp} = 0u;")
                self._s(f"rt_ld_u32({acc}->data, {off}u, &{tmp});")
                return _Frag(f"(uint64_t){tmp}", "uint64_t")
            if resolved is not None and resolved[0].shape == "string":
                field, acc = resolved
                tmp = self._mk_tmp()
                off = ACCOUNT_DATA_OFFSET + field.offset
                self._s(f"uint32_t {tmp} = 0u;")
                self._s(f"rt_ld_u32({acc}->data, {off}u, &{tmp});")
                return _Frag(f"(uint64_t){tmp}", "uint64_t")
        self._diag(PS5002, arg, "len() needs a FixedArray or FixedString")
        return _Frag("0u", "uint64_t")

    def _load_subscript(self, node: ast.Subscript) -> _Frag:
        base = node.value
        if isinstance(base, ast.Name) and base.id in self._strings:
            binding = self._strings[base.id]
            idx = self._index_text(node.slice, binding.capacity)
            tmp = self._mk_tmp()
            self._s(f"uint8_t {tmp} = {binding.data_var}[{idx}];")
            return _Frag(tmp, "uint8_t")
        if isinstance(base, ast.Name) and base.id in self._arrays:
            var, ctype, length = self._arrays[base.id]
            idx = self._index_text(node.slice, length)
            if ctype == "SolPubkey":
                return _Frag(f"&{var}[{idx}]", "pub")
            tmp = self._mk_tmp()
            self._s(f"{ctype} {tmp} = {var}[{idx}];")
            return _Frag(tmp, ctype)
        if isinstance(base, ast.Attribute):
            resolved = self._resolve_field(base)
            if resolved is None:
                return _Frag("0u", "uint64_t")
            field, acc = resolved
            if field.shape == "string":
                idx = self._index_text(node.slice, field.length)
                return self._load_field(field, acc, offset_expr=self._string_at(field, idx))
            if field.shape not in ("array", "vec"):
                self._diag(PS5002, node, f"`{field.name}` is not an array")
                return _Frag("0u", "uint64_t")
            idx = self._index_text(node.slice, field.length)
            return self._load_field(field, acc, offset_expr=self._elem_offset(field, idx))
        self._diag(PS5002, node, "only `name[i]` and `account.field[i]` can be indexed")
        return _Frag("0u", "uint64_t")

    def _emit_subscript_store(self, target: ast.Subscript, value: ast.expr) -> None:
        base = target.value
        if isinstance(base, ast.Name) and base.id in self._strings:
            binding = self._strings[base.id]
            idx = self._index_text(target.slice, binding.capacity)
            text = self._u8_text(value)
            if text is None:
                return
            self._s(f"{binding.data_var}[{idx}] = (uint8_t)({text});")
            return
        if isinstance(base, ast.Name) and base.id in self._arrays:
            var, ctype, length = self._arrays[base.id]
            idx = self._index_text(target.slice, length)
            frag = self._load(value)
            if ctype == "SolPubkey":
                if frag.kind != "pub":
                    self._diag(PS5002, value, "cannot store a non-Pubkey into a Pubkey array")
                    return
                self._s(f"rt_key_copy(&{var}[{idx}], {frag.text});")
                return
            text = frag.text
            if _canon(frag.kind) != _canon(ctype):
                text = self._coerce_numeric(frag, ctype, value)
            self._s(f"{var}[{idx}] = ({ctype})({text});")
            return
        if isinstance(base, ast.Attribute):
            resolved = self._resolve_field(base)
            if resolved is None:
                return
            field, acc = resolved
            if field.shape == "string":
                idx = self._index_text(target.slice, field.length)
                text = self._u8_text(value)
                if text is None:
                    return
                off = self._string_at(field, idx)
                self._s(f"{acc}->data[{off}] = (uint8_t)({text});")
                return
            if field.shape not in ("array", "vec"):
                self._diag(PS5001, target, f"`{field.name}` is not an array")
                return
            idx = self._index_text(target.slice, field.length)
            frag = self._load(value)
            self._store_field_value(
                field,
                acc,
                frag,
                offset_expr=self._elem_offset(field, idx),
                at=value,
            )
            if field.shape == "vec":
                self._note_vec_len(field, acc, idx)
            return
        self._diag(PS5001, target, "only `name[i]` and `account.field[i]` can be assigned")

    def _u8_text(self, value: ast.expr) -> str | None:
        frag = self._load(value)
        if frag.kind == "pub" or _canon(frag.kind) not in _KIND_META:
            self._diag(PS5002, value, "a string byte is a u8")
            return None
        if _canon(frag.kind) == "uint8_t":
            return frag.text
        return self._coerce_numeric(frag, "uint8_t", value)

    def _string_at(self, field: FieldModel, index_text: str) -> str:
        """Byte offset of one reserved payload byte (after the ``u32`` length)."""
        base = ACCOUNT_DATA_OFFSET + field.offset + 4
        tmp = self._mk_tmp()
        self._s(f"uint64_t {tmp} = {base}u + ({index_text});")
        return tmp

    def _index_text(self, index: ast.expr, length: int) -> str:
        frag = self._load(index)
        text = self._coerce_numeric(frag, "uint64_t", index)
        tmp = self._mk_tmp()
        self._s(f"uint64_t {tmp} = {text};")
        line = getattr(index, "lineno", 1) or 1
        self._s(f"if ({tmp} >= {length}u) {{")
        self._s(
            f'rt_fail_log({RT_ERR_OOB}u, {self._loc(line)}, "index out of bounds");',
            1,
        )
        self._s(f"return {RT_ERR_OOB}u;", 1)
        self._s("}")
        return tmp

    def _elem_offset(self, field: FieldModel, index_text: str) -> str:
        base = ACCOUNT_DATA_OFFSET + field.offset
        if field.shape == "vec":
            base += 4
        tmp = self._mk_tmp()
        elem = field.elem_size or _WIDTH_BYTES[field.c_type]
        self._s(f"uint64_t {tmp} = {base}u + ({index_text}) * {elem}u;")
        return tmp

    def _note_vec_len(self, field: FieldModel, acc: str, index_text: str) -> None:
        """A store at ``index`` grows the stored length when it writes past the end."""
        off = ACCOUNT_DATA_OFFSET + field.offset
        tmp = self._mk_tmp()
        self._s(f"uint32_t {tmp} = 0u;")
        self._s(f"rt_ld_u32({acc}->data, {off}u, &{tmp});")
        self._s(f"if ((uint64_t){tmp} <= {index_text}) {{")
        self._s(f"rt_st_u32({acc}->data, {off}u, (uint32_t)({index_text} + 1u));", 1)
        self._s("}")

    def _as_u64(self, node: ast.expr) -> str:
        return self._coerce_numeric(self._load(node), "uint64_t", node)

    def _load_ifexp(self, node: ast.IfExp) -> _Frag:
        cond = self._load(node.test)
        if cond.kind != "bool":
            self._diag(PS5002, node.test, "conditional test must be bool")
        dest = self._guess_ctype(node.body) or self._guess_ctype(node.orelse) or "uint64_t"
        other = self._guess_ctype(node.orelse)
        if other is not None and other != dest and dest in _KIND_META and other in _KIND_META:
            dest = _wider_kind(dest, other)
        tmp = self._mk_tmp()
        if dest == "SolPubkey":
            self._s(f"SolPubkey {tmp};")
        elif dest in ("RtU128", "RtI128") or dest.startswith("int"):
            self._s(f"{dest} {tmp} = 0;")
        else:
            self._s(f"{dest} {tmp} = 0u;")
        self._s(f"if ({cond.text}) {{")
        self._indent += 1
        self._store_into(tmp, dest, self._load(node.body), node.body)
        self._indent -= 1
        self._s("} else {")
        self._indent += 1
        self._store_into(tmp, dest, self._load(node.orelse), node.orelse)
        self._indent -= 1
        self._s("}")
        if dest == "SolPubkey":
            return _Frag(f"&{tmp}", "pub")
        return _Frag(tmp, dest)

    def _store_into(self, tmp: str, dest: str, frag: _Frag, node: ast.AST) -> None:
        if dest == "SolPubkey":
            self._s(f"rt_key_copy(&{tmp}, {frag.text});")
            return
        text = frag.text
        if _canon(frag.kind) != _canon(dest):
            text = self._coerce_numeric(frag, dest, node)
        self._s(f"{tmp} = ({dest})({text});")

    def _guess_ctype(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return "uint8_t"
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            if node.value < 0:
                return "int64_t" if node.value >= -(2**63) else "RtI128"
            return "uint64_t" if node.value <= 2**64 - 1 else "RtU128"
        if isinstance(node, ast.Name):
            info = self._locals.get(node.id) or self._data_vars.get(node.id)
            if info is not None and info[1] != "SolPubkey":
                return info[1]
            if info is not None:
                return "SolPubkey"
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _CAST_NAMES
        ):
            return _LOCAL_TYPES_C[node.func.id]
        if isinstance(node, ast.Attribute) and node.attr == "value":
            meta = self._option_meta(node.value)
            if meta is not None:
                return meta[0]
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in self._enums:
                return "uint8_t"
            if node.attr == "key":
                return "SolPubkey"
            entry = self._acct_vars.get(node.value.id)
            if entry is None:
                return None
            model = self._accounts.get(entry[1])
            if model is None:
                return None
            for field in model.fields:
                if field.name == node.attr and field.shape == "scalar":
                    return _WIDTH_C[field.c_type]
        return None

    # -- require -----------------------------------------------------------------

    def _emit_token_transfer(self, call: ast.Call, token2022: bool) -> None:
        """SPL Token or Token-2022 Transfer (instruction byte 3)."""
        if call.keywords or len(call.args) != 4:
            self._diag(PS5001, call, "token_transfer takes src, dest, authority, amount")
            return
        src = self._transfer_var(call.args[0])
        dest = self._transfer_var(call.args[1])
        authority = self._transfer_var(call.args[2])
        if src is None or dest is None or authority is None:
            return
        frag = self._load(call.args[3])
        if frag.kind == "pub":
            self._diag(PS5002, call.args[3], "amount must be an integer")
            return
        text = frag.text
        if _canon(frag.kind) != "uint64_t":
            text = self._coerce_numeric(frag, "uint64_t", call.args[3])
        program = "RT_TOKEN_2022_ID" if token2022 else "RT_TOKEN_ID"
        rc = self._mk_tmp()
        self._s("{")
        self._indent += 1
        self._s(
            f"uint64_t {rc} = rt_token_transfer(rt, {program}, {src}, {dest}, "
            f"{authority}, (uint64_t)({text}));"
        )
        self._s(f"if ({rc} != RT_OK) {{")
        self._s(f'rt_fail_log({rc}, {self._loc(call.lineno)}, "token transfer");', 1)
        self._s(f"return {rc};", 1)
        self._s("}")
        self._indent -= 1
        self._s("}")

    def _emit_ata_create(self, call: ast.Call) -> None:
        """Associated-token CreateIdempotent (data byte 1) for the SPL Token program."""
        if call.keywords or len(call.args) != 4:
            self._diag(PS5001, call, "ata_create takes payer, ata, owner, mint")
            return
        payer = self._transfer_var(call.args[0])
        ata = self._transfer_var(call.args[1])
        owner = self._transfer_var(call.args[2])
        mint = self._transfer_var(call.args[3])
        if payer is None or ata is None or owner is None or mint is None:
            return
        rc = self._mk_tmp()
        self._s("{")
        self._indent += 1
        self._s(
            f"uint64_t {rc} = rt_ata_create(rt, {payer}, {ata}, {owner}, {mint}, RT_TOKEN_ID);"
        )
        self._s(f"if ({rc} != RT_OK) {{")
        self._s(f'rt_fail_log({rc}, {self._loc(call.lineno)}, "create ata");', 1)
        self._s(f"return {rc};", 1)
        self._s("}")
        self._indent -= 1
        self._s("}")

    def _emit_system_transfer(self, call: ast.Call) -> None:
        """System-program Transfer (tag 2): lamports move from ``src`` to ``dest``."""
        if call.keywords or len(call.args) != 3:
            self._diag(PS5001, call, "system_transfer(src, dest, lamports) takes three arguments")
            return
        src = self._transfer_var(call.args[0])
        dest = self._transfer_var(call.args[1])
        if src is None or dest is None:
            return
        frag = self._load(call.args[2])
        if frag.kind == "pub":
            self._diag(PS5002, call.args[2], "lamports must be an integer")
            return
        text = frag.text
        if _canon(frag.kind) != "uint64_t":
            text = self._coerce_numeric(frag, "uint64_t", call.args[2])
        rc = self._mk_tmp()
        self._s("{")
        self._indent += 1
        signed = self._pda_transfer(call.args[0])
        if signed is not None and not signed[1]:
            self._indent -= 1
            self._s("}")
            return
        if signed is None:
            self._s(
                f"uint64_t {rc} = rt_system_transfer(rt, {src}, {dest}, (uint64_t)({text}));"
            )
        else:
            self._s(
                f"uint64_t {rc} = rt_move_lamports(rt, {src}, {dest}, (uint64_t)({text}));"
            )
        self._s(f"if ({rc} != RT_OK) {{")
        self._s(f'rt_fail_log({rc}, {self._loc(call.lineno)}, "system transfer");', 1)
        self._s(f"return {rc};", 1)
        self._s("}")
        self._indent -= 1
        self._s("}")

    def _enum_field(
        self, node: ast.Attribute
    ) -> tuple[FieldModel, str, EnumModel] | None:
        """The account field under ``field.value``, when that field is a data enum."""
        field_node = node.value
        if not isinstance(field_node, ast.Attribute):
            return None
        resolved = self._resolve_field(field_node)
        if resolved is None:
            return None
        field, acc = resolved
        enum = self._enums.get(field.defined) if field.defined else None
        if enum is None or not enum.payload_size:
            return None
        return field, acc, enum

    def _require_payload_tag(self, acc: str, off: int, enum: EnumModel, line: int) -> str:
        tag = self._mk_tmp()
        self._s(f"uint8_t {tag} = {acc}->data[{off}u];")
        allowed = " || ".join(f"{tag} == {item}u" for item in enum.payload_tags)
        self._s(f"if (!({allowed})) {{")
        self._s(
            f'rt_fail_log({RT_ERR_ENUM}u, {self._loc(line)}, "enum payload");',
            1,
        )
        self._s(f"return {RT_ERR_ENUM}u;", 1)
        self._s("}")
        return tag

    def _load_enum_value(self, node: ast.Attribute) -> _Frag | None:
        found = self._enum_field(node)
        if found is None:
            return None
        field, acc, enum = found
        off = ACCOUNT_DATA_OFFSET + field.offset
        self._require_payload_tag(acc, off, enum, node.lineno)
        payload = off + 1
        size = enum.payload_size
        tmp = self._mk_tmp()
        if size == 1:
            self._s(f"uint8_t {tmp} = {acc}->data[{payload}u];")
            return _Frag(tmp, "uint8_t")
        self._s(f"uint64_t {tmp} = 0u;")
        self._s(f"{_LD_HELPER[size]}({acc}->data, {payload}u, &{tmp});")
        return _Frag(tmp, "uint64_t")

    def _store_enum_value(self, target: ast.Attribute, value: ast.expr) -> bool:
        found = self._enum_field(target)
        if found is None:
            return False
        field, acc, enum = found
        off = ACCOUNT_DATA_OFFSET + field.offset
        self._require_payload_tag(acc, off, enum, target.lineno)
        frag = self._load(value)
        if frag.kind == "pub":
            self._diag(PS5002, value, "an enum payload is a scalar")
            return True
        text = frag.text
        payload = off + 1
        size = enum.payload_size
        if size == 1:
            self._s(f"{acc}->data[{payload}u] = (uint8_t)({text});")
            return True
        if _canon(frag.kind) != "uint64_t":
            text = self._coerce_numeric(frag, "uint64_t", value)
        self._s(f"{_ST_HELPER[size]}({acc}->data, {payload}u, {text});")
        return True

    def _zero_enum_payload(self, field: FieldModel, acc: str, off: str) -> None:
        enum = self._enums.get(field.defined) if field.defined else None
        if enum is None or not enum.payload_size:
            return
        index = self._mk_tmp()
        self._s(f"for (uint64_t {index} = 0u; {index} < {enum.payload_size}u; {index}++) {{")
        self._s(f"{acc}->data[({off}) + 1u + {index}] = 0u;", 1)
        self._s("}")

    def _account_seed(self, account: str) -> str:
        """Seed literal for ``account``, from ``Seeds`` or the snake_case init name."""
        found = ""
        for instr in self._model.instructions:
            for param in instr.account_params:
                if param.account != account:
                    continue
                if param.seed:
                    return param.seed
                if param.is_init and not found:
                    found = snake_case(account)
        return found

    def _pda_transfer(self, node: ast.expr) -> tuple[str, str, int] | None:
        """``(account var, seed, bump offset)`` when ``node`` is a program PDA.

        A missing ``bump`` field is a diagnostic and this returns ``None`` after
        recording it. Callers must not also emit the unsigned transfer. The
        sentinel is an empty seed.
        """
        if not isinstance(node, ast.Name):
            return None
        param = next((item for item in self._iparams if item.name == node.id), None)
        if param is None or param.kind == "signer":
            return None
        seed = self._account_seed(param.account)
        if not seed:
            return None
        account = self._accounts.get(param.account)
        bump = None if account is None else account.field("bump")
        if bump is None or bump.shape != "scalar" or bump.c_type != "uint8_t":
            self._diag(PS5001, node, "a PDA system_transfer needs a u8 field named bump")
            return ("", "", -1)
        acc = self._acct_vars[node.id][0]
        return acc, seed, ACCOUNT_DATA_OFFSET + bump.offset

    def _transfer_var(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            entry = self._acct_vars.get(node.id)
            if entry is not None:
                return entry[0]
        self._diag(PS5002, node, "system_transfer account is not an instruction parameter")
        return None

    def _emit_event(self, call: ast.Call) -> None:
        """Log one event: 8-byte discriminator, then packed scalar fields."""
        if call.keywords or len(call.args) != 1:
            self._diag(PS5001, call, "emit() takes one event: emit(Name(...))")
            return
        arg = call.args[0]
        if not isinstance(arg, ast.Call) or not isinstance(arg.func, ast.Name):
            self._diag(PS5001, call, "emit() takes one event: emit(Name(...))")
            return
        event = self._events.get(arg.func.id)
        if event is None:
            self._diag(PS5002, arg.func, f"unknown event `{arg.func.id}`")
            return
        if arg.keywords or len(arg.args) != len(event.fields):
            self._diag(PS5001, arg, f"`{event.name}` takes {len(event.fields)} field(s)")
            return
        total = 8 + event.size
        buf = self._mk_tmp()
        self._s("{")
        self._indent += 1
        self._s(f"uint8_t {buf}[{total}u];")
        for index, byte in enumerate(event.discriminator):
            self._s(f"{buf}[{index}u] = {byte:#x}u;")
        for field, value in zip(event.fields, arg.args, strict=False):
            self._store_event_field(buf, field, value)
        self._s(f"rt_log_event({buf}, {total}u);")
        self._indent -= 1
        self._s("}")

    def _store_event_field(self, buf: str, field: FieldModel, value: ast.expr) -> None:
        frag = self._load(value)
        off = 8 + field.offset
        if field.c_type == "SolPubkey":
            if frag.kind != "pub":
                self._diag(PS5002, value, "cannot store non-Pubkey into a Pubkey field")
                return
            self._s(f"rt_st_key({buf}, {off}u, {frag.text});")
            return
        if frag.kind == "pub":
            self._diag(PS5002, value, "cannot store a Pubkey into a numeric field")
            return
        if field.c_type not in _WIDTH_BYTES:
            self._diag(PS5002, value, f"event field `{field.name}` is not lowered")
            return
        text = frag.text
        if _canon(frag.kind) != _canon(field.c_type):
            text = self._coerce_numeric(frag, field.c_type, value)
        size = _WIDTH_BYTES[field.c_type]
        if size == 1:
            self._s(f"{buf}[{off}u] = (uint8_t)({text});")
            return
        if field.c_type in _UNSIGNED_OF:
            text = f"({_UNSIGNED_OF[field.c_type]})({text})"
        self._s(f"{_ST_HELPER[size]}({buf}, {off}u, {text});")

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
        self._s("if (!(" + cond.text + ")) {")
        self._s(
            f'rt_fail_log({macro}, {self._loc(call.lineno)}, "{text}");',
            1,
        )
        self._s(f"return {macro};", 1)
        self._s("}")

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
