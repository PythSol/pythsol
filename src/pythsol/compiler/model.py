"""Stage 5 — the concrete ``ProgramModel`` the back-end emits from.

The front-end answers "is this program valid?"; this stage answers "what *is*
the program": accounts with Borsh layouts, instructions with discriminators and
account/data parameter roles, and custom error codes. It is deliberately
*ir-free* (TRD §4.2): the C emitter skips over these plain dataclasses directly,
keeping generated C readable.

Conventions verified against Anchor (TRD §6):

* account discriminator     = ``sha256("account:<PascalName>")[..8]``
* instruction discriminator = ``sha256("global:<snake_name>")[..8]``
* error codes               = ``6000 + index`` (member value is documentation)
* Borsh layout is packed, little-endian, no alignment padding
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field

from pythsol.compiler.diagnostics import PS4001, Diagnostic
from pythsol.compiler.resolve import InstructionDecl, Program

__all__ = [
    "ACCOUNT_DATA_OFFSET",
    "CUSTOM_ERROR_BASE",
    "AccountModel",
    "AccountParamModel",
    "DataParamModel",
    "ErrorModel",
    "FieldModel",
    "InstructionModel",
    "ProgramModel",
    "account_discriminator",
    "build_model",
    "error_code",
    "instruction_discriminator",
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

#: Types the phase 3 emitter can lower end-to-end (ADR-0010); everything else
#: becomes PS4001 so the build fails with a stable code instead of emitting
#: wrong-width C. u128/i128 and narrow signed fields land in phase 4.
_PHASE3_TYPES: frozenset[str] = frozenset({"u8", "u16", "u32", "u64", "i64", "bool", "Pubkey"})

_ACCOUNT_WRAPPERS: frozenset[str] = frozenset({"Mut", "Account", "Init", "InitIfNeeded", "Zeroed"})

_KIND_OF_WRAPPER: dict[str, str] = {
    "Mut": "mut",
    "Account": "ro",
    "Init": "init",
    "InitIfNeeded": "init_if_needed",
    "Zeroed": "zeroed",
}


def snake_case(name: str) -> str:
    """Anchor snake_cases every declared identifier for dispatch naming."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def account_discriminator(name: str) -> bytes:
    """Anchor account discriminator: ``sha256('account:' + name)[..8]``."""
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


def instruction_discriminator(name: str) -> bytes:
    """Anchor instruction discriminator: ``sha256('global:' + snake)[..8]``."""
    return hashlib.sha256(f"global:{snake_case(name)}".encode()).digest()[:8]


def error_code(index: int) -> int:
    """Position-based custom error code: 6000 + index."""
    return CUSTOM_ERROR_BASE + index


@dataclass(frozen=True)
class FieldModel:
    """One ``@account`` field with its packed payload offset."""

    name: str
    c_type: str
    size: int
    offset: int  # offset *within the payload* (i.e. after the discriminator)


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
class DataParamModel:
    """An instruction data argument (u*/i*/bool) with its Borsh width."""

    name: str
    c_type: str
    size: int
    line: int
    col: int


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

    @property
    def writable(self) -> bool:
        return self.kind not in ("signer", "ro")

    @property
    def is_init(self) -> bool:
        return self.kind in ("init", "init_if_needed", "zeroed")


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


@dataclass
class ProgramModel:
    """Everything the emitter needs about one program."""

    name: str
    accounts: list[AccountModel]
    instructions: list[InstructionModel]
    errors: list[ErrorModel]
    source: str

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


def build_model(
    program: Program,
    name: str,
    source: str = "program.py",
) -> tuple[ProgramModel, list[Diagnostic]]:
    """Elaborate a type-checked :class:`Program` into the emitter's model."""
    d: list[Diagnostic] = []

    accounts: list[AccountModel] = []
    for decl in program.accounts.values():
        offset = 0
        fields: list[FieldModel] = []
        for fd in decl.fields:
            c_type, size = _ctype_of(fd.annotation)
            if c_type is None or size is None:
                d.append(
                    Diagnostic(
                        code=PS4001,
                        message=(
                            f"account `{decl.name}` field `{fd.name}` has an "
                            f"unsupported type `{ast.unparse(fd.annotation)}` (phase 3)"
                        ),
                        file=source,
                        line=fd.line,
                        col=fd.col,
                    )
                )
                continue
            fields.append(FieldModel(name=fd.name, c_type=c_type, size=size, offset=offset))
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
        data_params = _data_params(instr_decl, source, d)
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
            )
        )

    model = ProgramModel(
        name=name,
        accounts=accounts,
        instructions=instructions,
        errors=errors,
        source=source,
    )
    return model, d


def _ctype_of(ann: ast.expr) -> tuple[str | None, int | None]:
    """C type + Borsh size of an account-field/data-arg annotation (phase 3)."""
    if isinstance(ann, ast.Name) and ann.id in _PHASE3_TYPES:
        return _C_TYPES[ann.id], _WIDTHS[ann.id]
    return None, None


def _account_params(
    decl: InstructionDecl,
    program: Program,
    source: str,
    d: list[Diagnostic],
) -> list[AccountParamModel]:
    out: list[AccountParamModel] = []
    index = 0
    for param in decl.params:
        kind, account = _wrapper_of(param.annotation)
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
            )
        )
        index += 1
    return out


def _data_params(decl: InstructionDecl, source: str, d: list[Diagnostic]) -> list[DataParamModel]:
    out: list[DataParamModel] = []
    for param in decl.params:
        kind, _account = _wrapper_of(param.annotation)
        if kind is not None:
            continue
        ann = param.annotation
        c_type, size = _ctype_of(ann)
        if c_type is None or size is None:
            d.append(
                Diagnostic(
                    code=PS4001,
                    message=(
                        f"instruction `{decl.name}`: data parameter `{param.name}` has "
                        f"unsupported type `{ast.unparse(ann)}` (phase 3 supports u*/i*/bool)"
                    ),
                    file=source,
                    line=param.line,
                    col=param.col,
                )
            )
            continue
        out.append(
            DataParamModel(
                name=param.name, c_type=c_type, size=size, line=param.line, col=param.col
            )
        )
    return out


def _wrapper_of(ann: ast.expr) -> tuple[str | None, str | None]:
    """``Mut[Counter]`` -> ("mut", "Counter"); ``Signer`` -> ("signer", None)."""
    if isinstance(ann, ast.Name):
        if ann.id == "Signer":
            return "signer", None
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
