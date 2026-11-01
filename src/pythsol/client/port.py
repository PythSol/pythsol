"""Turn an Anchor-legacy IDL into a PythSol program skeleton.

The bodies are ``pass``. Account wrappers are inferred: a ``seeds`` constraint
becomes ``Seeds[Init[T], "seed"]``, a mutable account on ``initialize`` /
``init`` / ``make`` / ``create`` / ``open`` becomes ``Init[T]``, and other
mutable accounts become ``Mut[T]``. The compiler still has to accept the
result; fill the bodies in before the program can run.
"""

from __future__ import annotations

from typing import Any

__all__ = ["render_port"]

_INIT_NAMES = {"initialize", "init", "make", "create", "open"}
_SCALARS = {"u8", "u16", "u32", "u64", "u128", "i8", "i16", "i32", "i64", "i128"}
_WRAPPERS = ("Seeds[", "HasOne[", "CloseTo[", "Address[", "Owner[")


class PortError(Exception):
    """The IDL is too incomplete to sketch a program."""


def render_port(idl: dict[str, Any]) -> str:
    """Return Python source for a skeleton program."""
    program = str(idl.get("name") or "program")
    types = _type_map(idl)
    accounts = [item for item in idl.get("accounts") or [] if isinstance(item, dict)]
    if not accounts:
        raise PortError("IDL has no accounts to port")
    imports: set[str] = {"account", "instruction"}
    blocks: list[str] = []
    for info in types.values():
        body = info.get("type")
        if isinstance(body, dict) and body.get("kind") == "enum":
            imports.add("enum")
            blocks.append(_enum_block(info))
    for info in types.values():
        if _is_user_struct(info):
            imports.add("struct")
            blocks.append(_struct_block(info, types, imports))
    for account in accounts:
        blocks.append(_account_block(account, types, imports))
    errors = [item for item in idl.get("errors") or [] if isinstance(item, dict)]
    if errors:
        imports.update({"error", "ProgramError"})
        blocks.append(_error_block(program, errors))
    instructions = [item for item in idl.get("instructions") or [] if isinstance(item, dict)]
    if not instructions:
        raise PortError("IDL has no instructions to port")
    for instr in instructions:
        blocks.append(_instruction_block(instr, accounts, types, imports))
    header = [
        f'"""Ported from the `{program}` IDL.',
        "",
        "Each instruction body is a placeholder. Replace ``pass`` with the program.",
        '"""',
        "",
        "from pythsol import (",
    ]
    for name in _import_lines(imports):
        header.append(f"    {name},")
    header.append(")")
    header.append("")
    return "\n".join([*header, "", *blocks]).rstrip() + "\n"


def _import_lines(names: set[str]) -> list[str]:
    order = [
        "Account",
        "Address",
        "CloseTo",
        "FixedArray",
        "FixedString",
        "HasOne",
        "Init",
        "Mut",
        "Option",
        "Owner",
        "ProgramError",
        "Pubkey",
        "Seeds",
        "Signer",
        "account",
        "enum",
        "error",
        "instruction",
        "struct",
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
    ]
    return [name for name in order if name in names]


def _type_map(idl: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for item in idl.get("types") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            found[item["name"]] = item
    return found


def _snake(name: str) -> str:
    out: list[str] = []
    for char in name:
        if char.isupper() and out and out[-1] != "_":
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def _pascal(name: str) -> str:
    parts = name.replace("-", "_").split("_")
    return "".join(part[:1].upper() + part[1:] for part in parts if part) or "Program"


def _is_user_struct(info: dict[str, Any]) -> bool:
    body = info.get("type")
    if not isinstance(body, dict) or body.get("kind") != "struct":
        return False
    fields = body.get("fields")
    if not isinstance(fields, list):
        return False
    if (
        len(fields) == 2
        and isinstance(fields[0], dict)
        and isinstance(fields[1], dict)
        and fields[0].get("name") == "tag"
        and fields[1].get("name") == "value"
    ):
        return False
    return not (
        len(fields) == 2
        and isinstance(fields[0], dict)
        and isinstance(fields[1], dict)
        and fields[0].get("name") == "len"
        and fields[1].get("name") == "data"
    )


def _annotation(ty: Any, types: dict[str, dict[str, Any]], imports: set[str]) -> str:
    if ty == "publicKey":
        imports.add("Pubkey")
        return "Pubkey"
    if ty == "bool":
        return "bool"
    if isinstance(ty, str) and ty in _SCALARS:
        imports.add(ty)
        return ty
    if isinstance(ty, dict) and isinstance(ty.get("array"), list) and len(ty["array"]) == 2:
        inner, count = ty["array"]
        imports.add("FixedArray")
        return f"FixedArray[{_annotation(inner, types, imports)}, {count}]"
    if isinstance(ty, dict) and isinstance(ty.get("option"), (str, dict)):
        imports.add("Option")
        return f"Option[{_annotation(ty['option'], types, imports)}]"
    if isinstance(ty, dict) and isinstance(ty.get("defined"), str):
        return _defined(ty["defined"], types, imports)
    imports.add("u64")
    return "u64"


def _defined(name: str, types: dict[str, dict[str, Any]], imports: set[str]) -> str:
    info = types.get(name)
    body = info.get("type") if isinstance(info, dict) else None
    if not isinstance(body, dict):
        return name
    if body.get("kind") == "enum":
        return name
    fields = body.get("fields")
    if isinstance(fields, list) and len(fields) == 2:
        first, second = fields[0], fields[1]
        if (
            isinstance(first, dict)
            and isinstance(second, dict)
            and first.get("name") == "tag"
            and second.get("name") == "value"
        ):
            imports.add("Option")
            return f"Option[{_annotation(second.get('type'), types, imports)}]"
        if (
            isinstance(first, dict)
            and isinstance(second, dict)
            and first.get("name") == "len"
            and second.get("name") == "data"
            and isinstance(second.get("type"), dict)
            and isinstance(second["type"].get("array"), list)
        ):
            imports.add("FixedString")
            return f"FixedString[{second['type']['array'][1]}]"
    return name


def _enum_block(info: dict[str, Any]) -> str:
    name = str(info.get("name") or "Enum")
    body = info.get("type") if isinstance(info.get("type"), dict) else {}
    variants = body.get("variants") if isinstance(body, dict) else []
    lines = ["@enum", f"class {name}:"]
    if not isinstance(variants, list) or not variants:
        lines.append("    pass")
        return "\n".join(lines)
    for index, variant in enumerate(variants):
        label = "Variant"
        if isinstance(variant, dict) and isinstance(variant.get("name"), str):
            label = variant["name"]
        lines.append(f"    {label} = {index}")
    return "\n".join(lines)


def _struct_block(info: dict[str, Any], types: dict[str, dict[str, Any]], imports: set[str]) -> str:
    name = str(info.get("name") or "Struct")
    body = info.get("type") if isinstance(info.get("type"), dict) else {}
    fields = body.get("fields") if isinstance(body, dict) else []
    lines = ["@struct", f"class {name}:"]
    if not isinstance(fields, list) or not fields:
        lines.append("    pass")
        return "\n".join(lines)
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_name = str(field.get("name") or "field")
        lines.append(f"    {field_name}: {_annotation(field.get('type'), types, imports)}")
    return "\n".join(lines)


def _account_block(
    account: dict[str, Any],
    types: dict[str, dict[str, Any]],
    imports: set[str],
) -> str:
    name = str(account.get("name") or "Account")
    body = account.get("type") if isinstance(account.get("type"), dict) else {}
    fields = body.get("fields") if isinstance(body, dict) else []
    lines = ["@account", f"class {name}:"]
    if not isinstance(fields, list) or not fields:
        lines.append("    pass")
        return "\n".join(lines)
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_name = str(field.get("name") or "field")
        lines.append(f"    {field_name}: {_annotation(field.get('type'), types, imports)}")
    return "\n".join(lines)


def _error_block(program: str, errors: list[dict[str, Any]]) -> str:
    lines = [
        "@error",
        f"class {_pascal(program)}Error(ProgramError):",
        '    """Ported error names. Codes on chain are 6000 + declaration index."""',
    ]
    for index, error in enumerate(errors):
        label = str(error.get("name") or f"Error{index}")
        lines.append(f"    {label} = {index}")
    return "\n".join(lines)


def _match_account(param: str, accounts: list[dict[str, Any]]) -> str | None:
    for account in accounts:
        name = str(account.get("name") or "")
        if name == param or _snake(name) == param:
            return name
    return None


def _constraint(account: dict[str, Any], kind: str, key: str) -> str | None:
    raw = account.get("constraints")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if isinstance(item, dict) and item.get("kind") == kind and isinstance(item.get(key), str):
            return str(item[key])
    return None


def _account_annotation(
    instr_name: str,
    account: dict[str, Any],
    accounts: list[dict[str, Any]],
    imports: set[str],
) -> str:
    if account.get("isSigner"):
        imports.add("Signer")
        return "Signer"
    matched = _match_account(str(account.get("name") or ""), accounts)
    if matched is None:
        imports.add("Pubkey")
        return "Pubkey"
    seed = _constraint(account, "seeds", "seed")
    has_one = _constraint(account, "has_one", "field")
    close = _constraint(account, "close", "account")
    owner = _constraint(account, "owner", "account")
    address = _constraint(account, "address", "pubkey")
    if seed is not None:
        imports.update({"Seeds", "Init"})
        return f'Seeds[Init[{matched}], "{seed}"]'
    if has_one is not None:
        imports.update({"HasOne", "Mut"})
        return f'HasOne[Mut[{matched}], "{has_one}"]'
    if close is not None:
        imports.update({"CloseTo", "Mut"})
        return f"CloseTo[Mut[{matched}], {close}]"
    if owner is not None:
        imports.update({"Owner", "Mut"})
        return f"Owner[Mut[{matched}], {owner}]"
    if address is not None:
        imports.update({"Address", "Mut"})
        return f"Address[Mut[{matched}], {address}]"
    if instr_name in _INIT_NAMES and account.get("isMut"):
        imports.add("Init")
        return f"Init[{matched}]"
    if account.get("isMut"):
        imports.add("Mut")
        return f"Mut[{matched}]"
    imports.add("Account")
    return f"Account[{matched}]"


def _instruction_block(
    instr: dict[str, Any],
    accounts: list[dict[str, Any]],
    types: dict[str, dict[str, Any]],
    imports: set[str],
) -> str:
    name = str(instr.get("name") or "instruction")
    params: list[str] = []
    for account in instr.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        param = str(account.get("name") or "account")
        ann = _account_annotation(name, account, accounts, imports)
        suffix = ""
        if ann.startswith(_WRAPPERS):
            suffix = "  # type: ignore[name-defined]  # noqa: F821"
        params.append(f"    {param}: {ann},{suffix}")
    for arg in instr.get("args") or []:
        if not isinstance(arg, dict):
            continue
        param = str(arg.get("name") or "arg")
        params.append(f"    {param}: {_annotation(arg.get('type'), types, imports)},")
    lines = ["@instruction", f"def {name}("]
    lines.extend(params)
    lines.append(") -> None:")
    lines.append(f'    """TODO: port {name}."""')
    lines.append("    pass")
    return "\n".join(lines)
