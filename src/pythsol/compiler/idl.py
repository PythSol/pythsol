"""Anchor-compatible IDL generation (legacy shape, ``spec 0.1.0``).

The JSON mirrors what the Anchor TS client accepted as legacy IDL:

```json
{
  "name": "counter", "version": "0.1.0", "spec": "0.1.0",
  "metadata": {...},
  "instructions": [
    {"name": "increment", "discriminator": [...8], "accounts": [...], "args": [...]}
  ],
  "accounts": [
    {"name": "Counter", "discriminator": [...8],
     "type": {"kind": "struct", "fields": [...]}}
  ],
  "types":        [{"name": "Status", "type": {"kind": "enum", "variants": [...]}}],
  "errors":       [{"code": 6000, "name": "Unauthorized", "msg": "..."}]
}
```

``validate_idl`` is a dependency-free structural validator strong enough for the
golden tests and the build gate; full Anchor schema conformance is a Phase 5
welcome add-on. Output is deterministic (sorted keys).
"""

from __future__ import annotations

import json
from typing import Any

from pythsol.compiler.model import (
    DataParamModel,
    FieldModel,
    ProgramModel,
    fixed_string_type_name,
    option_type_name,
    snake_case,
    vec_type_name,
)

__all__ = ["build_idl", "idl_json", "validate_idl"]

_TYPE_NAMES: dict[str, str] = {
    "u8": "u8",
    "u16": "u16",
    "u32": "u32",
    "u64": "u64",
    "u128": "u128",
    "i8": "i8",
    "i16": "i16",
    "i32": "i32",
    "i64": "i64",
    "i128": "i128",
    "uint8_t": "u8",
    "uint16_t": "u16",
    "uint32_t": "u32",
    "uint64_t": "u64",
    "uint128_t": "u128",
    "int8_t": "i8",
    "int16_t": "i16",
    "int32_t": "i32",
    "int64_t": "i64",
    "int128_t": "i128",
    "bool": "bool",
    "SolPubkey": "publicKey",
    "Pubkey": "publicKey",
}

_VERSION = "0.1.0"
_IDL_SPEC = "0.1.0"


def _stored_fields(model: ProgramModel) -> list[FieldModel]:
    """Account fields and ``@struct`` fields. Options and strings live in both."""
    found: list[FieldModel] = []
    for account in model.accounts:
        found.extend(account.fields)
    for struct in model.structs:
        found.extend(struct.fields)
    return found


def _idl_scalar(c_type: str, defined: str) -> str | dict[str, Any]:
    if defined:
        return {"defined": defined}
    return _TYPE_NAMES[c_type]


def _idl_type(field: FieldModel) -> str | dict[str, Any]:
    """Anchor legacy type for one field (scalar, array, fixed option, or fixed string)."""
    if field.shape == "struct":
        return {"defined": field.defined}
    if field.shape == "option":
        return {"defined": option_type_name(field.c_type, field.defined)}
    if field.shape == "string":
        return {"defined": fixed_string_type_name(field.length)}
    if field.shape == "vec":
        return {"defined": vec_type_name(field.c_type, field.length, field.defined)}
    base = _idl_scalar(field.c_type, field.defined)
    if field.shape == "array":
        return {"array": [base, field.length]}
    return base


def _idl_account(param: Any) -> dict[str, Any]:
    """One instruction account. Constraint keys are omitted when unused."""
    entry: dict[str, Any] = {
        "name": param.name,
        "isMut": param.writable,
        "isSigner": param.kind == "signer",
        "docs": [],
    }
    constraints: list[dict[str, str]] = []
    if param.seed:
        constraints.append({"kind": "seeds", "seed": param.seed})
    if param.has_one:
        constraints.append({"kind": "has_one", "field": param.has_one})
        entry["relations"] = [param.has_one]
    if param.owner_of:
        constraints.append({"kind": "owner", "account": param.owner_of})
    if param.address_of:
        constraints.append({"kind": "address", "pubkey": param.address_of})
    if param.close_to:
        constraints.append({"kind": "close", "account": param.close_to})
    if constraints:
        entry["constraints"] = constraints
    return entry


def _idl_arg_type(param: DataParamModel) -> str | dict[str, Any]:
    if param.shape == "option":
        return {"defined": option_type_name(param.c_type, param.defined)}
    if param.shape == "string":
        return {"defined": fixed_string_type_name(param.length)}
    return _idl_scalar(param.c_type, param.defined)


def _user_structs(model: ProgramModel) -> list[dict[str, Any]]:
    """``@struct`` values, in declaration order, as Anchor struct types."""
    out: list[dict[str, Any]] = []
    for struct in model.structs:
        out.append(
            {
                "name": struct.name,
                "type": {
                    "kind": "struct",
                    "fields": [
                        {"name": field.name, "type": _idl_type(field)}
                        for field in struct.fields
                    ],
                },
            }
        )
    return out


def _option_structs(model: ProgramModel) -> list[dict[str, Any]]:
    """One defined struct per distinct fixed-width option (tag byte + reserved value)."""
    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def add(c_type: str, defined: str) -> None:
        name = option_type_name(c_type, defined)
        if name in seen:
            return
        seen.add(name)
        found.append((name, c_type, defined))

    for field in _stored_fields(model):
        if field.shape == "option":
            add(field.c_type, field.defined)
    for instr in model.instructions:
        for param in instr.data_params:
            if param.shape == "option":
                add(param.c_type, param.defined)
    structs: list[dict[str, Any]] = []
    for name, c_type, defined in found:
        structs.append(
            {
                "name": name,
                "type": {
                    "kind": "struct",
                    "fields": [
                        {"name": "tag", "type": "u8"},
                        {"name": "value", "type": _idl_scalar(c_type, defined)},
                    ],
                },
            }
        )
    return structs


def _string_structs(model: ProgramModel) -> list[dict[str, Any]]:
    """One defined struct per distinct ``FixedString[N]`` (u32 length + N bytes)."""
    found: list[int] = []
    seen: set[int] = set()

    def add(length: int) -> None:
        if length in seen:
            return
        seen.add(length)
        found.append(length)

    for field in _stored_fields(model):
        if field.shape == "string":
            add(field.length)
    for instr in model.instructions:
        for param in instr.data_params:
            if param.shape == "string":
                add(param.length)
    return [
        {
            "name": fixed_string_type_name(length),
            "type": {
                "kind": "struct",
                "fields": [
                    {"name": "len", "type": "u32"},
                    {"name": "data", "type": {"array": ["u8", length]}},
                ],
            },
        }
        for length in found
    ]


def _vec_structs(model: ProgramModel) -> list[dict[str, Any]]:
    """One defined struct per distinct ``Vec[T, N]`` (u32 length plus N elements)."""
    found: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()

    def add(c_type: str, defined: str, length: int) -> None:
        name = vec_type_name(c_type, length, defined)
        if name in seen:
            return
        seen.add(name)
        found.append((name, c_type, defined, length))

    for field in _stored_fields(model):
        if field.shape == "vec":
            add(field.c_type, field.defined, field.length)
    structs: list[dict[str, Any]] = []
    for name, c_type, defined, length in found:
        inner = _idl_scalar(c_type, defined)
        structs.append(
            {
                "name": name,
                "type": {
                    "kind": "struct",
                    "fields": [
                        {"name": "len", "type": "u32"},
                        {"name": "data", "type": {"array": [inner, length]}},
                    ],
                },
            }
        )
    return structs


def build_idl(model: ProgramModel, address: str | None = None) -> dict[str, Any]:
    """Build the legacy-IDL dictionary for ``model`` (deterministic)."""
    instructions = []
    cpi: dict[str, dict[str, bool]] = {}
    for instr in model.instructions:
        accounts = [_idl_account(param) for param in instr.account_params]
        args = [
            {"name": param.name, "type": _idl_arg_type(param)} for param in instr.data_params
        ]
        pays = any(param.is_init for param in instr.account_params)
        cpi[instr.snake_name] = {
            "ata": instr.needs_ata,
            "pays": pays,
            "system": pays or instr.needs_system,
            "token": instr.needs_token,
            "token2022": instr.needs_token2022,
        }
        instructions.append(
            {
                "name": instr.snake_name,
                "discriminator": list(instr.discriminator),
                "accounts": accounts,
                "args": args,
            }
        )

    account_types = []
    for account in model.accounts:
        fields = [{"name": f.name, "type": _idl_type(f)} for f in account.fields]
        account_types.append(
            {
                "name": account.name,
                "discriminator": list(account.discriminator),
                "type": {"kind": "struct", "fields": fields},
            }
        )

    errors = [{"code": err.code, "name": err.name, "msg": err.name} for err in model.errors]
    events = [
        {
            "name": event.name,
            "discriminator": list(event.discriminator),
            "fields": [
                {"name": field.name, "type": _idl_type(field), "index": False}
                for field in event.fields
            ],
        }
        for event in model.events
    ]
    types = [
        {
            "name": enum.name,
            "type": {
                "kind": "enum",
                "variants": [
                {"name": variant}
                if variant_tag not in enum.payload_tags
                else {
                    "name": variant,
                    "fields": [{"name": "value", "type": _TYPE_NAMES[enum.payload_c]}],
                }
                for variant, variant_tag in enum.variants
            ],
            },
        }
        for enum in model.enums
    ]
    types.extend(_user_structs(model))
    types.extend(_option_structs(model))
    types.extend(_string_structs(model))
    types.extend(_vec_structs(model))

    idl: dict[str, Any] = {
        "version": _VERSION,
        # Top-level spec mirrors Anchor's legacy IDL shape (0.1.0); the
        # metadata copy is for clients that only read `metadata`.
        "spec": _IDL_SPEC,
        "name": snake_case(model.name),
        "metadata": {
            "name": snake_case(model.name),
            "version": _VERSION,
            "spec": "0.1.0",
            "description": f"{model.name} program, generated by PythSol",
            # Which programs the client must append. Account metas stay free of
            # this: unconstrained accounts keep the same keys as before.
            "pythsol": {"cpi": cpi},
        },
        "instructions": instructions,
        "accounts": account_types,
        "types": types,
        "events": events,
        "errors": errors,
    }
    if address is not None:
        idl["address"] = address
    return idl


def idl_json(model: ProgramModel, address: str | None = None) -> str:
    """Deterministic JSON text (sorted keys, 2-space indent, trailing newline)."""
    return json.dumps(build_idl(model, address), indent=2, sort_keys=True) + "\n"


def validate_idl(idl: dict[str, Any]) -> list[str]:
    """Structural validation; the list is empty when the IDL is well-formed."""
    problems: list[str] = []
    for key in ("name", "version", "instructions"):
        if key not in idl:
            problems.append(f"missing required key `{key}`")
    if not isinstance(idl.get("name"), str) or not idl.get("name"):
        problems.append("`name` must be a non-empty string")
    if not isinstance(idl.get("instructions"), list):
        problems.append("`instructions` must be a list")
        return problems
    seen: set[bytes] = set()
    for instr in idl["instructions"]:
        if "name" not in instr or "discriminator" not in instr:
            problems.append("instruction missing name/discriminator")
            continue
        disc = instr.get("discriminator")
        if not isinstance(disc, list) or len(disc) != 8:
            problems.append(f"instruction `{instr.get('name')}`: discriminator must be 8 bytes")
            continue
        key_bytes = bytes(element & 0xFF for element in disc)
        if key_bytes in seen:
            problems.append(f"instruction `{instr.get('name')}`: duplicate discriminator")
        seen.add(key_bytes)
        for account in instr.get("accounts", []):
            if "name" not in account:
                problems.append(f"instruction `{instr.get('name')}`: account without name")
        for arg in instr.get("args", []):
            if "name" not in arg or "type" not in arg:
                problems.append(f"instruction `{instr.get('name')}`: arg missing name/type")
    for account in idl.get("accounts", []):
        if "name" not in account:
            problems.append("account without name")
        t = account.get("type", {})
        if t.get("kind") != "struct" or not isinstance(t.get("fields"), list):
            problems.append(f"account `{account.get('name')}`: type must be a struct with fields")
    for err in idl.get("errors", []):
        if "code" not in err:
            problems.append("error without code")
    declared = {
        entry.get("name")
        for entry in idl.get("types", [])
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    seen_types: set[str] = set()
    for entry in idl.get("types", []):
        if not isinstance(entry, dict) or not entry.get("name"):
            problems.append("type without name")
            continue
        type_name = entry.get("name")
        if isinstance(type_name, str):
            if type_name in seen_types:
                problems.append(f"duplicate type `{type_name}`")
            seen_types.add(type_name)
        body = entry.get("type", {})
        if body.get("kind") == "enum" and not isinstance(body.get("variants"), list):
            problems.append(f"type `{entry.get('name')}`: enum needs variants")
        if body.get("kind") == "struct" and isinstance(body.get("fields"), list):
            for field in body["fields"]:
                if isinstance(field, dict):
                    _check_defined(
                        field.get("type"),
                        declared,
                        f"type `{entry.get('name')}`",
                        problems,
                    )
    for account in idl.get("accounts", []):
        fields = account.get("type", {}).get("fields", [])
        if isinstance(fields, list):
            for field in fields:
                _check_defined(
                    field.get("type"),
                    declared,
                    f"account `{account.get('name')}`",
                    problems,
                )
    for instr in idl.get("instructions", []):
        if not isinstance(instr, dict):
            continue
        for arg in instr.get("args", []):
            if isinstance(arg, dict):
                _check_defined(
                    arg.get("type"),
                    declared,
                    f"instruction `{instr.get('name')}`",
                    problems,
                )
    return problems


def _check_defined(
    ty: object,
    declared: set[object],
    where: str,
    problems: list[str],
) -> None:
    if not isinstance(ty, dict):
        return
    name = ty.get("defined")
    if isinstance(name, str) and name not in declared:
        problems.append(f"{where}: unknown defined type `{name}`")
    array = ty.get("array")
    if isinstance(array, list) and array:
        _check_defined(array[0], declared, where, problems)
