"""Stage 5 — the concrete ``ProgramModel`` the back-end emits from.

The front-end answers "is this program valid?"; this stage answers "what *is*
the program": accounts with Borsh layouts, instructions with discriminators and
account/data parameter roles, and custom error codes. It is deliberately
*ir-free* (TRD §4.2): the C emitter skips over these plain dataclasses directly,
keeping generated C readable.

Conventions verified against Anchor (TRD §6):

* account discriminator     = ``sha256("account:<PascalName>")[..8]``
* instruction discriminator = ``sha256("global:<snake_name>")[..8]``
* event discriminator       = ``sha256("event:<PascalName>")[..8]``
* error codes               = ``6000 + index`` (member value is documentation)
* Borsh layout is packed, little-endian, no alignment padding
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field

from pythsol.compiler.diagnostics import PS4001, Diagnostic
from pythsol.compiler.resolve import (
    EventDecl,
    HelperDecl,
    InstructionDecl,
    ParamDecl,
    Program,
    StructDecl,
)

__all__ = [
    "ACCOUNT_DATA_OFFSET",
    "CUSTOM_ERROR_BASE",
    "AccountModel",
    "AccountParamModel",
    "DataParamModel",
    "EnumModel",
    "ErrorModel",
    "EventModel",
    "FieldModel",
    "HelperModel",
    "HelperParamModel",
    "InstructionModel",
    "ProgramModel",
    "StructModel",
    "account_discriminator",
    "build_model",
    "error_code",
    "event_discriminator",
    "fixed_string_type_name",
    "instruction_discriminator",
    "option_type_name",
    "snake_case",
]

#: On-chain data layout: 8-byte discriminator prefix, then payload fields.
ACCOUNT_DATA_OFFSET = 8

#: First custom error code (Anchor convention; keep in sync with the emitter).
CUSTOM_ERROR_BASE = 6000

_WIDTHS: dict[str, int] = {
    "u8": 1,
    "u16": 2,
    "u32": 4,
    "u64": 8,
    "u128": 16,
    "i8": 1,
    "i16": 2,
    "i32": 4,
    "i64": 8,
    "i128": 16,
    "bool": 1,
    "Pubkey": 32,
}

_C_TYPES: dict[str, str] = {
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
}

_OPTION_SUFFIX: dict[str, str] = {
    "uint8_t": "U8",
    "uint16_t": "U16",
    "uint32_t": "U32",
    "uint64_t": "U64",
    "uint128_t": "U128",
    "int8_t": "I8",
    "int16_t": "I16",
    "int32_t": "I32",
    "int64_t": "I64",
    "int128_t": "I128",
    "bool": "Bool",
    "SolPubkey": "Pubkey",
}

#: Types the emitter lowers end-to-end (phase 4: full integer gate; ADR-0011).
#: Everything else becomes PS4001 so the build fails with a stable code
#: instead of emitting wrong-width C.
_EMITTABLE_TYPES: frozenset[str] = frozenset(
    {"u8", "u16", "u32", "u64", "u128", "i8", "i16", "i32", "i64", "i128", "bool", "Pubkey"}
)

_ACCOUNT_WRAPPERS: frozenset[str] = frozenset({"Mut", "Account", "Init", "InitIfNeeded", "Zeroed"})
_CONSTRAINTS: frozenset[str] = frozenset(
    {"Seeds", "HasOne", "CloseTo", "Address", "Owner"}
)

_KIND_OF_WRAPPER: dict[str, str] = {
    "Mut": "mut",
    "Account": "ro",
    "Init": "init",
    "InitIfNeeded": "init_if_needed",
    "Zeroed": "zeroed",
}


def fixed_string_type_name(length: int) -> str:
    """IDL struct name for ``FixedString[length]`` (length prefix plus reserved bytes)."""
    return f"FixedString{length}"


def vec_type_name(c_type: str, length: int, defined: str = "") -> str:
    """IDL struct name for ``Vec[T, N]`` (u32 length plus N reserved elements)."""
    inner = defined or _OPTION_SUFFIX.get(c_type, "U64")
    return f"Vec{inner}{length}"


def option_type_name(c_type: str, defined: str) -> str:
    """IDL struct name for a fixed-width ``Option[T]`` (not Anchor's short option)."""
    if defined:
        return f"Option{defined}"
    return "Option" + _OPTION_SUFFIX[c_type]


def snake_case(name: str) -> str:
    """Anchor snake_cases every declared identifier for dispatch naming."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def account_discriminator(name: str) -> bytes:
    """Anchor account discriminator: ``sha256('account:' + name)[..8]``."""
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


def instruction_discriminator(name: str) -> bytes:
    """Anchor instruction discriminator: ``sha256('global:' + snake)[..8]``."""
    return hashlib.sha256(f"global:{snake_case(name)}".encode()).digest()[:8]


def event_discriminator(name: str) -> bytes:
    """Anchor event discriminator: ``sha256('event:' + name)[..8]``."""
    return hashlib.sha256(f"event:{name}".encode()).digest()[:8]


#: Event payload cap. The discriminator sits in front; the sum stays on the stack.
_MAX_EVENT_PAYLOAD = 1016


def error_code(index: int) -> int:
    """Position-based custom error code: 6000 + index."""
    return CUSTOM_ERROR_BASE + index


@dataclass(frozen=True)
class FieldModel:
    """One ``@account`` field with its packed payload offset.

    ``shape`` is ``"scalar"``, ``"array"``, ``"option"``, or ``"string"``.
    Arrays are Borsh fixed arrays: ``length`` elements of ``c_type`` packed
    back-to-back (``elem_size`` each). An option is a tag byte plus the inner
    value always reserved (``c_type`` / ``elem_size`` describe the inner value;
    ``size`` is ``1 + elem_size``). A fixed string is a ``u32`` byte length
    plus ``length`` reserved bytes (``size`` is ``4 + length``). ``defined``
    is the inner unit-enum name when there is one.
    """

    name: str
    c_type: str
    size: int
    offset: int  # offset *within the payload* (i.e. after the discriminator)
    shape: str = "scalar"
    length: int = 0
    elem_size: int = 0
    #: Unit-enum name when this field, or its array element, is one.
    defined: str = ""


@dataclass(frozen=True)
class AccountModel:
    """One ``@account`` class: layout + discriminator."""

    name: str
    discriminator: bytes
    fields: list[FieldModel]

    @property
    def size(self) -> int:
        """Space on chain: discriminator + all fields."""
        return ACCOUNT_DATA_OFFSET + max((f.offset + f.size for f in self.fields), default=0)

    def field(self, name: str) -> FieldModel | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None


@dataclass(frozen=True)
class EventModel:
    """An ``@event``. Offsets are within the payload, after the 8-byte discriminator."""

    name: str
    discriminator: bytes
    fields: list[FieldModel]

    @property
    def size(self) -> int:
        return max((item.offset + item.size for item in self.fields), default=0)


@dataclass(frozen=True)
class StructModel:
    """A ``@struct`` value. Offsets are within the struct, not the account."""

    name: str
    fields: list[FieldModel]

    @property
    def size(self) -> int:
        return max((item.offset + item.size for item in self.fields), default=0)

    def field(self, name: str) -> FieldModel | None:
        for item in self.fields:
            if item.name == name:
                return item
        return None


@dataclass(frozen=True)
class DataParamModel:
    """An instruction data argument (u*/i*/bool) with its Borsh width."""

    name: str
    c_type: str
    size: int
    line: int
    col: int
    #: Unit-enum name when this argument is one, or the inner enum of an option.
    defined: str = ""
    #: ``"scalar"``, ``"option"``, or ``"string"``.
    shape: str = "scalar"
    #: Inner width of an option, or 1 for a fixed string's bytes.
    elem_size: int = 0
    #: Reserved byte count of a fixed string. Other arguments leave this at 0.
    length: int = 0


@dataclass(frozen=True)
class AccountParamModel:
    """An instruction account argument and its runtime role.

    ``account`` names the backing ``@account`` class **or** is ``"Pubkey"``
    for a bare ``Signer`` (whose only payload interest is the key itself).
    """

    name: str
    index: int  # position in the incoming accounts array
    kind: str  # signer | ro | mut | init | init_if_needed | zeroed
    account: str
    line: int
    col: int
    #: PDA seed literal. Empty means ``snake_case`` of the account class.
    seed: str = ""
    #: Pubkey field that must equal the account parameter of the same name.
    has_one: str = ""
    #: Account parameter whose key must equal this account's owner.
    owner_of: str = ""
    #: ``Pubkey`` instruction argument this account's key must equal.
    address_of: str = ""
    #: Writable account that receives the lamports when the body succeeds.
    close_to: str = ""
    #: This parameter is the destination of a ``CloseTo``.
    lamport_dest: bool = False
    #: This account's lamports move in a ``system_transfer`` (a signer must be writable).
    funds: bool = False

    @property
    def writable(self) -> bool:
        # A mint is read-only in the outer transaction. Token accounts stay writable.
        if self.kind == "mint":
            return False
        return self.kind not in ("signer", "ro") or self.lamport_dest or self.funds

    @property
    def is_init(self) -> bool:
        return self.kind in ("init", "init_if_needed", "zeroed")


@dataclass(frozen=True)
class EnumModel:
    """An enum. ``variants`` is ``(name, tag)`` in declaration order.

    A unit enum is one byte. A data enum reserves ``payload_size`` bytes after
    the tag, using the largest payload, so later fields stay at fixed offsets.
    ``payload_tags`` are the variants that store that scalar.
    """

    name: str
    variants: list[tuple[str, int]]
    payload_c: str = ""
    payload_size: int = 0
    payload_tags: tuple[int, ...] = ()


@dataclass(frozen=True)
class ErrorModel:
    """A custom error member with its runtime code."""

    name: str
    owner: str
    index: int
    code: int
    declared_value: int
    line: int
    col: int


@dataclass(frozen=True)
class InstructionModel:
    """One ``@instruction`` function: params, discriminator and body AST."""

    name: str
    snake_name: str
    discriminator: bytes
    account_params: list[AccountParamModel]
    data_params: list[DataParamModel]
    line: int
    col: int
    body: list[ast.stmt] = field(default_factory=list)
    #: The body calls ``system_transfer`` or ``ata_create``.
    needs_system: bool = False
    #: SPL Token program must be on the transaction.
    needs_token: bool = False
    #: Token-2022 program must be on the transaction.
    needs_token2022: bool = False
    #: Associated Token program must be on the transaction.
    needs_ata: bool = False
    #: Basename recorded in ``rt_fail_log``. Empty uses ``ProgramModel.source``.
    source: str = ""


@dataclass(frozen=True)
class HelperParamModel:
    """One helper parameter. ``kind`` is ``account`` or ``value``.

    Account parameters alias a caller account (``Mut`` / ``Account`` /
    ``Signer``). Value parameters are scalars: an integer, bool, Pubkey, or
    a unit enum. ``Init`` and variable-width values are rejected.
    """

    name: str
    kind: str
    c_type: str
    account: str
    defined: str
    line: int
    col: int


@dataclass(frozen=True)
class HelperModel:
    """A plain function. It is inlined into each caller and is not an instruction."""

    name: str
    params: list[HelperParamModel]
    #: Model C type of the result, or ``""`` when the helper returns ``None``.
    return_c: str
    return_defined: str
    body: list[ast.stmt]
    line: int
    col: int
    #: Basename recorded in ``rt_fail_log`` while this helper is inlined.
    source: str = ""


@dataclass
class ProgramModel:
    """Everything the emitter needs about one program."""

    name: str
    accounts: list[AccountModel]
    instructions: list[InstructionModel]
    errors: list[ErrorModel]
    enums: list[EnumModel]
    source: str
    helpers: list[HelperModel] = field(default_factory=list)
    structs: list[StructModel] = field(default_factory=list)
    events: list[EventModel] = field(default_factory=list)

    def account(self, name: str) -> AccountModel | None:
        for account in self.accounts:
            if account.name == name:
                return account
        return None

    def instruction(self, name: str) -> InstructionModel | None:
        for instr in self.instructions:
            if instr.name == name:
                return instr
        return None

    @property
    def snake_name(self) -> str:
        return snake_case(self.name)


def _log_name(decl_file: str, fallback: str) -> str:
    """Basename of a declaration's file, for runtime ``(file:line)`` logs."""
    if not decl_file:
        return fallback
    name = decl_file.replace("\\", "/").rsplit("/", 1)[-1]
    return name or fallback


def _enum_meta(
    program: Program,
    source: str,
    d: list[Diagnostic],
) -> dict[str, tuple[str, int, tuple[int, ...]]]:
    """``name -> (payload c type, payload bytes, tags that store it)``."""
    out: dict[str, tuple[str, int, tuple[int, ...]]] = {}
    for decl in program.enums.values():
        kinds = {member.payload for member in decl.members if member.payload}
        if not kinds:
            out[decl.name] = ("", 0, ())
            continue
        if len(kinds) != 1:
            d.append(
                Diagnostic(
                    code=PS4001,
                    message=(
                        f"enum `{decl.name}` payloads must all be the same scalar"
                    ),
                    file=source,
                    line=decl.line,
                    col=decl.col,
                )
            )
            out[decl.name] = ("", 0, ())
            continue
        py = next(iter(kinds))
        out[decl.name] = (
            _C_TYPES[py],
            _WIDTHS[py],
            tuple(member.value for member in decl.members if member.payload),
        )
    return out


def build_model(
    program: Program,
    name: str,
    source: str = "program.py",
) -> tuple[ProgramModel, list[Diagnostic]]:
    """Elaborate a type-checked :class:`Program` into the emitter's model."""
    d: list[Diagnostic] = []
    enum_names = frozenset(program.enums)
    enum_meta = _enum_meta(program, source, d)
    enum_payload = {name: size for name, (_c, size, _tags) in enum_meta.items()}
    struct_models = _build_structs(program, source, d, enum_names, enum_payload)
    struct_sizes = {item.name: item.size for item in struct_models}

    accounts: list[AccountModel] = []
    for decl in program.accounts.values():
        offset = 0
        fields: list[FieldModel] = []
        for fd in decl.fields:
            layout = _layout_of(fd.annotation, enum_names, struct_sizes, enum_payload)
            if layout is None:
                d.append(
                    Diagnostic(
                        code=PS4001,
                        message=(
                            f"account `{decl.name}` field `{fd.name}` has an "
                            f"unsupported type `{ast.unparse(fd.annotation)}` "
                            "(supported: integer widths, bool, Pubkey, "
                            "FixedArray[scalar, N], Vec[scalar, N], FixedString[N], "
                            "unit enums, Option[scalar], @struct values)"
                        ),
                        file=source,
                        line=fd.line,
                        col=fd.col,
                    )
                )
                continue
            c_type, size, shape, length, elem_size = layout
            defined = _defined_of(fd.annotation, enum_names, frozenset(struct_sizes))
            if shape == "option":
                _reject_option_clash(
                    option_type_name(c_type, defined), source, fd.line, fd.col, program, d
                )
            if shape == "string":
                _reject_option_clash(
                    fixed_string_type_name(length), source, fd.line, fd.col, program, d
                )
            if shape == "vec":
                _reject_option_clash(
                    vec_type_name(c_type, length, defined),
                    source,
                    fd.line,
                    fd.col,
                    program,
                    d,
                )
            fields.append(
                FieldModel(
                    name=fd.name,
                    c_type=c_type,
                    size=size,
                    offset=offset,
                    shape=shape,
                    length=length,
                    elem_size=elem_size,
                    defined=defined,
                )
            )
            offset += size
        accounts.append(
            AccountModel(
                name=decl.name,
                discriminator=account_discriminator(decl.name),
                fields=fields,
            )
        )

    errors: list[ErrorModel] = []
    for cls, err in program.errors.items():
        for m_index, member in enumerate(err.members):
            errors.append(
                ErrorModel(
                    name=member.name,
                    owner=cls,
                    index=m_index,
                    code=error_code(m_index),
                    declared_value=member.value,
                    line=member.line,
                    col=member.col,
                )
            )

    instructions: list[InstructionModel] = []
    for instr_decl in program.instructions:
        account_params = _account_params(instr_decl, program, source, d)
        data_params = _data_params(instr_decl, program, source, d, enum_names, enum_payload)
        tags = _cpi_tags(instr_decl.body)
        instructions.append(
            InstructionModel(
                name=instr_decl.name,
                snake_name=snake_case(instr_decl.name),
                discriminator=instruction_discriminator(instr_decl.name),
                account_params=account_params,
                data_params=data_params,
                line=instr_decl.line,
                col=instr_decl.col,
                body=instr_decl.body,
                needs_system="system" in tags,
                needs_token="token" in tags,
                needs_token2022="token2022" in tags,
                needs_ata="ata" in tags,
                source=_log_name(instr_decl.file, source),
            )
        )

    model = ProgramModel(
        name=name,
        accounts=accounts,
        instructions=instructions,
        errors=errors,
        enums=[
            EnumModel(
                name=decl.name,
                variants=[(member.name, member.value) for member in decl.members],
                payload_c=enum_meta.get(decl.name, ("", 0, ()))[0],
                payload_size=enum_meta.get(decl.name, ("", 0, ()))[1],
                payload_tags=enum_meta.get(decl.name, ("", 0, ()))[2],
            )
            for decl in program.enums.values()
        ],
        source=source,
        helpers=_helper_models(program, source, d, enum_names),
        structs=struct_models,
        events=_build_events(program, source, d, enum_names, enum_payload),
    )
    return model, d


def _helper_models(
    program: Program,
    source: str,
    d: list[Diagnostic],
    enums: frozenset[str],
) -> list[HelperModel]:
    """Scalar and account helpers only. They never become IDL instructions."""
    out: list[HelperModel] = []
    for decl in program.helpers:
        params: list[HelperParamModel] = []
        failed = False
        for param in decl.params:
            built = _helper_param(decl, param, program, source, d, enums)
            if built is None:
                failed = True
                continue
            params.append(built)
        return_c, return_defined, return_ok = _helper_return(decl, source, d, enums)
        if failed or not return_ok:
            continue
        out.append(
            HelperModel(
                name=decl.name,
                params=params,
                return_c=return_c,
                return_defined=return_defined,
                body=decl.body,
                line=decl.line,
                col=decl.col,
                source=_log_name(decl.file, source),
            )
        )
    return out


def _helper_param(
    decl: HelperDecl,
    param: ParamDecl,
    program: Program,
    source: str,
    d: list[Diagnostic],
    enums: frozenset[str],
) -> HelperParamModel | None:
    kind, account = _wrapper_of(param.annotation)
    if kind in ("init", "init_if_needed", "zeroed"):
        d.append(
            Diagnostic(
                code=PS4001,
                message="helpers cannot create accounts; pass Mut or Account",
                file=source,
                line=param.line,
                col=param.col,
            )
        )
        return None
    if kind is not None:
        if kind != "signer" and (account is None or account not in program.accounts):
            d.append(
                Diagnostic(
                    code=PS4001,
                    message=(
                        f"helper `{decl.name}`: parameter `{param.name}` "
                        f"references `{account}`, which is not a declared @account"
                    ),
                    file=source,
                    line=param.line,
                    col=param.col,
                )
            )
            return None
        return HelperParamModel(
            name=param.name,
            kind="account",
            c_type="",
            account="Pubkey" if kind == "signer" else (account or ""),
            defined="",
            line=param.line,
            col=param.col,
        )
    layout = _layout_of(param.annotation, enums)
    if layout is None or layout[2] != "scalar":
        d.append(
            Diagnostic(
                code=PS4001,
                message=(
                    f"helper `{decl.name}`: parameter `{param.name}` must be an "
                    "integer, bool, Pubkey, unit enum, or account"
                ),
                file=source,
                line=param.line,
                col=param.col,
            )
        )
        return None
    c_type, _size, _shape, _length, _elem = layout
    return HelperParamModel(
        name=param.name,
        kind="value",
        c_type=c_type,
        account="",
        defined=_defined_of(param.annotation, enums),
        line=param.line,
        col=param.col,
    )


def _helper_return(
    decl: HelperDecl,
    source: str,
    d: list[Diagnostic],
    enums: frozenset[str],
) -> tuple[str, str, bool]:
    ann = decl.returns
    if ann is None or (isinstance(ann, ast.Constant) and ann.value is None):
        return "", "", True
    layout = _layout_of(ann, enums)
    if layout is None or layout[2] != "scalar":
        d.append(
            Diagnostic(
                code=PS4001,
                message="helpers return an integer, bool, Pubkey, unit enum, or None",
                file=source,
                line=decl.line,
                col=decl.col,
            )
        )
        return "", "", False
    return layout[0], _defined_of(ann, enums), True


def _build_structs(
    program: Program,
    source: str,
    d: list[Diagnostic],
    enums: frozenset[str],
    enum_payload: dict[str, int] | None = None,
) -> list[StructModel]:
    """Pack ``@struct`` values. A cycle is PS4001 and that struct is omitted."""
    built: dict[str, StructModel] = {}
    visiting: set[str] = set()
    failed_names: set[str] = set()

    def build(decl: StructDecl) -> StructModel | None:
        if decl.name in built:
            return built[decl.name]
        if decl.name in failed_names:
            return None
        if decl.name in visiting:
            d.append(
                Diagnostic(
                    code=PS4001,
                    message=f"struct `{decl.name}` refers to itself",
                    file=source,
                    line=decl.line,
                    col=decl.col,
                )
            )
            return None
        visiting.add(decl.name)
        fields: list[FieldModel] = []
        offset = 0
        failed = False
        for fd in decl.fields:
            nested = (
                fd.annotation.id
                if isinstance(fd.annotation, ast.Name) and fd.annotation.id in program.structs
                else ""
            )
            if nested:
                if nested == decl.name or nested in visiting:
                    d.append(
                        Diagnostic(
                            code=PS4001,
                            message=f"struct `{nested}` refers to itself",
                            file=source,
                            line=fd.line,
                            col=fd.col,
                        )
                    )
                    failed = True
                    continue
                inner = build(program.structs[nested])
                if inner is None:
                    failed = True
                    continue
                fields.append(
                    FieldModel(
                        name=fd.name,
                        c_type="",
                        size=inner.size,
                        offset=offset,
                        shape="struct",
                        defined=inner.name,
                    )
                )
                offset += inner.size
                continue
            layout = _layout_of(fd.annotation, enums, None, enum_payload)
            if layout is None:
                d.append(
                    Diagnostic(
                        code=PS4001,
                        message=(
                            f"struct `{decl.name}` field `{fd.name}` has an "
                            f"unsupported type `{ast.unparse(fd.annotation)}`"
                        ),
                        file=source,
                        line=fd.line,
                        col=fd.col,
                    )
                )
                failed = True
                continue
            c_type, size, shape, length, elem_size = layout
            defined = _defined_of(fd.annotation, enums)
            fields.append(
                FieldModel(
                    name=fd.name,
                    c_type=c_type,
                    size=size,
                    offset=offset,
                    shape=shape,
                    length=length,
                    elem_size=elem_size,
                    defined=defined,
                )
            )
            offset += size
        visiting.remove(decl.name)
        if failed:
            failed_names.add(decl.name)
            return None
        model = StructModel(name=decl.name, fields=fields)
        built[decl.name] = model
        return model

    out: list[StructModel] = []
    for decl in program.structs.values():
        model = build(decl)
        if model is not None and model not in out:
            out.append(model)
    return out


def _build_events(
    program: Program,
    source: str,
    d: list[Diagnostic],
    enums: frozenset[str],
    enum_payload: dict[str, int] | None = None,
) -> list[EventModel]:
    """Pack ``@event`` payloads. A non-scalar field drops the event."""
    out: list[EventModel] = []
    for decl in program.events.values():
        fields, failed = _event_fields(decl, source, d, enums, enum_payload)
        if failed:
            continue
        size = max((item.offset + item.size for item in fields), default=0)
        if size > _MAX_EVENT_PAYLOAD:
            d.append(
                Diagnostic(
                    code=PS4001,
                    message=(
                        f"event `{decl.name}` is {size} bytes; "
                        f"the payload cap is {_MAX_EVENT_PAYLOAD}"
                    ),
                    file=source,
                    line=decl.line,
                    col=decl.col,
                )
            )
            continue
        out.append(
            EventModel(
                name=decl.name,
                discriminator=event_discriminator(decl.name),
                fields=fields,
            )
        )
    return out


def _event_fields(
    decl: EventDecl,
    source: str,
    d: list[Diagnostic],
    enums: frozenset[str],
    enum_payload: dict[str, int] | None = None,
) -> tuple[list[FieldModel], bool]:
    fields: list[FieldModel] = []
    offset = 0
    failed = False
    for fd in decl.fields:
        layout = _layout_of(fd.annotation, enums, None, enum_payload)
        if layout is None or layout[2] != "scalar":
            d.append(
                Diagnostic(
                    code=PS4001,
                    message=(
                        f"event `{decl.name}` field `{fd.name}` must be an integer, "
                        "bool, Pubkey, or unit enum"
                    ),
                    file=source,
                    line=fd.line,
                    col=fd.col,
                )
            )
            failed = True
            continue
        c_type, size, shape, length, elem_size = layout
        fields.append(
            FieldModel(
                name=fd.name,
                c_type=c_type,
                size=size,
                offset=offset,
                shape=shape,
                length=length,
                elem_size=elem_size,
                defined=_defined_of(fd.annotation, enums),
            )
        )
        offset += size
    return fields, failed


def _defined_of(
    ann: ast.expr,
    enums: frozenset[str],
    structs: frozenset[str] = frozenset(),
) -> str:
    """Unit-enum or struct name carried by a field."""
    if isinstance(ann, ast.Name) and ann.id in structs:
        return ann.id
    if isinstance(ann, ast.Name) and ann.id in enums:
        return ann.id
    if (
        isinstance(ann, ast.Subscript)
        and isinstance(ann.value, ast.Name)
        and ann.value.id in ("FixedArray", "Option", "Vec")
    ):
        items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        if items:
            return _defined_of(items[0], enums)
    return ""


def _reject_option_clash(
    name: str,
    source: str,
    line: int,
    col: int,
    program: Program,
    d: list[Diagnostic],
) -> None:
    """A generated ``OptionU64`` or ``FixedStringN`` struct must not reuse a name."""
    if name in program.enums or name in program.accounts or name in program.structs:
        d.append(
            Diagnostic(
                code=PS4001,
                message=f"fixed-width type `{name}` reuses an account or enum name",
                file=source,
                line=line,
                col=col,
            )
        )


def _layout_of(
    ann: ast.expr,
    enums: frozenset[str] = frozenset(),
    structs: dict[str, int] | None = None,
    enum_payload: dict[str, int] | None = None,
) -> tuple[str, int, str, int, int] | None:
    """``(c_type, size, shape, length, elem_size)`` or ``None``.

    Scalars use ``shape="scalar"``. A unit enum is one ``uint8_t``.
    ``FixedArray[T, N]`` of a scalar (including a unit enum) is a packed
    array (``shape="array"``). ``Option[scalar]`` is ``shape="option"``:
    one tag byte plus the inner value always reserved. ``FixedString[N]``
    is ``shape="string"``: a ``u32`` length plus ``N`` reserved bytes.
    ``Vec[T]`` without a capacity stays unsupported. ``Vec[T, N]`` is a
    ``u32`` length plus ``N`` reserved elements (``shape="vec"``). Nested
    arrays stay unsupported so the build fails with ``PS4001``.
    """
    if structs and isinstance(ann, ast.Name) and ann.id in structs:
        return "", structs[ann.id], "struct", 0, 0
    if isinstance(ann, ast.Name) and ann.id in enums:
        extra = 0 if enum_payload is None else enum_payload.get(ann.id, 0)
        return "uint8_t", 1 + extra, "scalar", 0, extra or 1
    if isinstance(ann, ast.Name) and ann.id in _EMITTABLE_TYPES:
        size = _WIDTHS[ann.id]
        return _C_TYPES[ann.id], size, "scalar", 0, size
    if not isinstance(ann, ast.Subscript) or not isinstance(ann.value, ast.Name):
        return None
    if ann.value.id == "Option":
        items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        if len(items) != 1:
            return None
        inner = _layout_of(items[0], enums, None, enum_payload)
        if inner is None or inner[2] != "scalar":
            return None
        return inner[0], 1 + inner[1], "option", 0, inner[1]
    if ann.value.id == "FixedString":
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
        return "uint8_t", 4 + count.value, "string", count.value, 1
    if ann.value.id == "Vec":
        items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        if len(items) != 2:
            return None
        inner = _layout_of(items[0], enums, None, enum_payload)
        if inner is None or inner[2] != "scalar":
            return None
        count = items[1]
        if (
            not isinstance(count, ast.Constant)
            or isinstance(count.value, bool)
            or not isinstance(count.value, int)
            or not 1 <= count.value <= 4096
        ):
            return None
        elem = inner[1]
        return inner[0], 4 + elem * count.value, "vec", count.value, elem
    if ann.value.id != "FixedArray":
        return None
    items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
    if len(items) != 2:
        return None
    inner = _layout_of(items[0], enums)
    if inner is None or inner[2] != "scalar":
        return None
    count = items[1]
    if (
        not isinstance(count, ast.Constant)
        or isinstance(count.value, bool)
        or not isinstance(count.value, int)
        or not 1 <= count.value <= 4096
    ):
        return None
    elem = inner[1]
    return inner[0], elem * count.value, "array", count.value, elem


def _peel_constraint(ann: ast.expr) -> tuple[ast.expr, str, ast.expr | None]:
    """``HasOne[Mut[T], "field"]`` -> ``(Mut[T], "HasOne", field)``."""
    if (
        isinstance(ann, ast.Subscript)
        and isinstance(ann.value, ast.Name)
        and ann.value.id in _CONSTRAINTS
    ):
        items = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        if len(items) == 2:
            return items[0], ann.value.id, items[1]
    return ann, "", None


def _constraint_fields(kind: str, arg: ast.expr | None) -> dict[str, str]:
    """The one constraint column set on an account parameter."""
    if arg is None:
        return {}
    if kind == "Seeds" and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return {"seed": arg.value}
    if kind == "HasOne" and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return {"has_one": arg.value}
    if kind == "Owner" and isinstance(arg, ast.Name):
        return {"owner_of": arg.id}
    if kind == "Address" and isinstance(arg, ast.Name):
        return {"address_of": arg.id}
    if kind == "CloseTo" and isinstance(arg, ast.Name):
        return {"close_to": arg.id}
    return {}


def _cpi_tags(stmts: list[ast.stmt]) -> set[str]:
    """CPI programs a body needs: system, token, token2022, ata."""
    return _walk_cpi(stmts)[0]


def _moved_accounts(stmts: list[ast.stmt]) -> set[str]:
    """Account names passed to ``system_transfer`` anywhere in ``stmts``."""
    return _walk_cpi(stmts)[1]


def _walk_cpi(stmts: list[ast.stmt]) -> tuple[set[str], set[str]]:
    tags: set[str] = set()
    names: set[str] = set()

    def walk(block: list[ast.stmt]) -> None:
        for stmt in block:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Name) and not call.keywords:
                    _note_cpi(call, tags, names)
            nested: list[list[ast.stmt]] = []
            if isinstance(stmt, (ast.If, ast.While, ast.For)):
                nested = [stmt.body, stmt.orelse]
            elif isinstance(stmt, ast.Match):
                nested = [case.body for case in stmt.cases]
            for inner in nested:
                walk(inner)

    walk(stmts)
    return tags, names


def _note_cpi(call: ast.Call, tags: set[str], names: set[str]) -> None:
    func = call.func
    if not isinstance(func, ast.Name):
        return
    if func.id == "system_transfer" and len(call.args) == 3:
        tags.add("system")
        for arg in call.args[:2]:
            if isinstance(arg, ast.Name):
                names.add(arg.id)
        return
    if func.id == "token_transfer" and len(call.args) == 4:
        tags.add("token")
        return
    if func.id == "token2022_transfer" and len(call.args) == 4:
        tags.add("token2022")
        return
    if func.id == "ata_create" and len(call.args) == 4:
        tags.update(("ata", "system", "token"))


def _account_params(
    decl: InstructionDecl,
    program: Program,
    source: str,
    d: list[Diagnostic],
) -> list[AccountParamModel]:
    close_dests: set[str] = set()
    moved = _moved_accounts(decl.body)
    for param in decl.params:
        _inner, constraint, carg = _peel_constraint(param.annotation)
        if constraint == "CloseTo" and isinstance(carg, ast.Name):
            close_dests.add(carg.id)
    out: list[AccountParamModel] = []
    index = 0
    for param in decl.params:
        inner, ck, arg = _peel_constraint(param.annotation)
        extra = _constraint_fields(ck, arg)
        kind, account = _wrapper_of(inner)
        if kind is None:
            continue
        if kind == "signer":
            # A bare `Signer` has no backing @account; its payload is just the key.
            out.append(
                AccountParamModel(
                    name=param.name,
                    index=index,
                    kind="signer",
                    account="Pubkey",
                    line=param.line,
                    col=param.col,
                    lamport_dest=param.name in close_dests,
                    funds=param.name in moved,
                )
            )
            index += 1
            continue
        if kind in ("token", "mint"):
            out.append(
                AccountParamModel(
                    name=param.name,
                    index=index,
                    kind=kind,
                    account=account or kind,
                    line=param.line,
                    col=param.col,
                )
            )
            index += 1
            continue
        assert account is not None
        if account not in program.accounts:
            d.append(
                Diagnostic(
                    code=PS4001,
                    message=(
                        f"instruction `{decl.name}`: parameter `{param.name}` "
                        f"references `{account}`, which is not a declared @account"
                    ),
                    file=source,
                    line=param.line,
                    col=param.col,
                )
            )
            continue
        out.append(
            AccountParamModel(
                name=param.name,
                index=index,
                kind=kind,
                account=account,
                line=param.line,
                col=param.col,
                lamport_dest=param.name in close_dests,
                funds=param.name in moved,
                **extra,
            )
        )
        index += 1
    return out


def _data_params(
    decl: InstructionDecl,
    program: Program,
    source: str,
    d: list[Diagnostic],
    enums: frozenset[str],
    enum_payload: dict[str, int] | None = None,
) -> list[DataParamModel]:
    out: list[DataParamModel] = []
    for param in decl.params:
        kind, _account = _wrapper_of(param.annotation)
        if kind is not None:
            continue
        ann = param.annotation
        if (
            isinstance(ann, ast.Name)
            and enum_payload is not None
            and enum_payload.get(ann.id, 0) > 0
        ):
            d.append(
                Diagnostic(
                    code=PS4001,
                    message=(
                        f"instruction `{decl.name}`: data parameter `{param.name}` "
                        "is a data enum; keep it on an account and pass the scalar"
                    ),
                    file=source,
                    line=param.line,
                    col=param.col,
                )
            )
            continue
        layout = _layout_of(ann, enums, None, enum_payload)
        if layout is None or layout[2] in ("array", "vec"):
            d.append(
                Diagnostic(
                    code=PS4001,
                    message=(
                        f"instruction `{decl.name}`: data parameter `{param.name}` has "
                        f"unsupported type `{ast.unparse(ann)}` "
                        "(supported: u8..u128, i8..i128, bool, Pubkey, unit enums, "
                        "Option[scalar], FixedString[N])"
                    ),
                    file=source,
                    line=param.line,
                    col=param.col,
                )
            )
            continue
        c_type, size, shape, length, elem_size = layout
        defined = _defined_of(ann, enums)
        if shape == "option":
            _reject_option_clash(
                option_type_name(c_type, defined), source, param.line, param.col, program, d
            )
        if shape == "string":
            _reject_option_clash(
                fixed_string_type_name(length), source, param.line, param.col, program, d
            )
        out.append(
            DataParamModel(
                name=param.name,
                c_type=c_type,
                size=size,
                line=param.line,
                col=param.col,
                defined=defined,
                shape=shape,
                elem_size=elem_size,
                length=length if shape == "string" else 0,
            )
        )
    return out


def _wrapper_of(ann: ast.expr) -> tuple[str | None, str | None]:
    """``Mut[Counter]`` -> ("mut", "Counter"); ``Signer`` -> ("signer", None)."""
    ann, _kind, _arg = _peel_constraint(ann)
    if isinstance(ann, ast.Name):
        if ann.id == "Signer":
            return "signer", None
        if ann.id == "TokenAccount":
            return "token", "TokenAccount"
        if ann.id == "TokenMint":
            return "mint", "TokenMint"
        if ann.id in _ACCOUNT_WRAPPERS:  # bare wrapper without [...] — upstream rejects
            return None, None
        return None, None
    if isinstance(ann, ast.Subscript):
        if isinstance(ann.value, ast.Name) and ann.value.id == "Signer":
            if isinstance(ann.slice, ast.Name):
                return "signer", ann.slice.id
            return None, None
        if isinstance(ann.value, ast.Name) and ann.value.id in _KIND_OF_WRAPPER:
            target = (
                ann.slice.elts[0]
                if isinstance(ann.slice, ast.Tuple) and ann.slice.elts
                else ann.slice
            )
            if isinstance(target, ast.Name):
                return _KIND_OF_WRAPPER[ann.value.id], target.id
    return None, None
