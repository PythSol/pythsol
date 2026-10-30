"""Random-AST fuzzing: the front-end must answer *anything* with diagnostics.

TRD §Phase 2 acceptance: feed random ``ast`` trees through ``check_tree`` and
assert it never raises and never returns ``None``. Any internal stage error is
a compiler bug: it must surface as a ``PS9000`` diagnostic — and this test
treats even that as a failure (with the seed to reproduce) so the gap gets
fixed rather than papered over.
"""

from __future__ import annotations

import ast
import random
import re

from pythsol.compiler import front
from pythsol.compiler.diagnostics import PS9000, Diagnostic

_CODE = re.compile(r"^PS\d{4}$")

_WIDTHS = ("u8", "u16", "u32", "u64", "u128", "i8", "i16", "i32", "i64", "i128")
_NAMES = ("x", "y", "n", "counter", "authority", "items", "Unknown", "Err")
_CONSTANTS = (
    0,
    1,
    255,
    2**64,
    -(2**80),
    "text",
    1.5,
    True,
    False,
    None,
    b"bytes",
    2**300,
)
_ATTRS = ("count", "authority", "key", "nope", "Member", "attr!")

_BIN_OPS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.LShift,
    ast.RShift,
    ast.BitAnd,
    ast.BitOr,
    ast.BitXor,
)
_UNARY_OPS = (ast.USub, ast.UAdd, ast.Not, ast.Invert)
_CMP_OPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.Is)
_BOOL_OPS = (ast.And, ast.Or)


def _ann(rng: random.Random) -> ast.expr:
    """A random annotation shape (Name, Subscript variants, junk)."""
    kind = rng.choice(("name", "name", "subscript", "subscript", "subscript", "attribute", "junk"))
    if kind == "name":
        return ast.Name(
            id=rng.choice((*_WIDTHS, "bool", "Pubkey", "Signer", "int", "list", "Any")),
            ctx=ast.Load(),
        )
    if kind == "subscript":
        base = ast.Name(
            id=rng.choice(("Mut", "Account", "Init", "Vec", "FixedArray", "FixedString", "Nope")),
            ctx=ast.Load(),
        )
        args = [
            rng.choice(
                (
                    ast.Name(id=rng.choice(("Counter", "Err", "u64")), ctx=ast.Load()),
                    ast.Constant(value=rng.choice((2, 4, 0, 8193))),
                )
            )
        ]
        slice_ = ast.Tuple(elts=[*args, args[0]], ctx=ast.Load()) if rng.random() < 0.5 else args[0]
        return ast.Subscript(value=base, slice=slice_, ctx=ast.Load())
    if kind == "attribute":
        return ast.Attribute(
            value=ast.Name(id="mod", ctx=ast.Load()), attr=rng.choice(_ATTRS), ctx=ast.Load()
        )
    return ast.Constant(value="not-an-annotation")


def _arg(rng: random.Random, *, annotate: bool) -> ast.arg:
    return ast.arg(
        arg=rng.choice(_NAMES),
        annotation=_ann(rng) if annotate else None,
    )


def _arguments(rng: random.Random) -> ast.arguments:
    n = rng.randint(0, 3)
    args = [_arg(rng, annotate=True) for _ in range(n)]
    if rng.random() < 0.15:
        args.append(_arg(rng, annotate=False))  # unannotated tail param
    kwonly = [_arg(rng, annotate=True) for _ in range(rng.choice((0, 1)))]
    return ast.arguments(
        posonlyargs=[],
        args=args,
        vararg=None if rng.random() > 0.1 else _arg(rng, annotate=True),
        kwonlyargs=kwonly,
        kw_defaults=[None] * (1 if kwonly else 0),
        kwarg=None if rng.random() > 0.1 else _arg(rng, annotate=True),
        defaults=[ast.Constant(value=rng.choice((0, 1)))] if rng.random() < 0.1 else [],
    )


def _load_name(rng: random.Random) -> ast.expr:
    return ast.Name(id=rng.choice(_NAMES), ctx=ast.Load())


def _expr(rng: random.Random, depth: int) -> ast.expr:
    """Random well-typed (not well-typed-like) expression node."""
    if depth <= 0 or rng.random() < 0.3:
        kind = rng.random()
        if kind < 0.5:
            return ast.Constant(value=rng.choice(_CONSTANTS))
        if kind < 0.8:
            return _load_name(rng)
        return ast.Name(
            id=rng.choice(("instruction", "account", "require", "require")), ctx=ast.Load()
        )
    kind = rng.choice(
        (
            "binop",
            "binop",
            "unaryop",
            "boolop",
            "compare",
            "call",
            "attribute",
            "subscript",
            "ifexp",
            "lambda",
            "fstring",
            "literal",
            "starred",
            "walrus",
        )
    )
    inner = lambda: _expr(rng, depth - 1)  # noqa: E731
    if kind == "binop":
        return ast.BinOp(left=inner(), op=_BIN_OPS[rng.randrange(len(_BIN_OPS))](), right=inner())
    if kind == "unaryop":
        return ast.UnaryOp(op=_UNARY_OPS[rng.randrange(len(_UNARY_OPS))](), operand=inner())
    if kind == "boolop":
        return ast.BoolOp(op=_BOOL_OPS[rng.randrange(len(_BOOL_OPS))](), values=[inner(), inner()])
    if kind == "compare":
        return ast.Compare(
            left=inner(), ops=[_CMP_OPS[rng.randrange(len(_CMP_OPS))]()], comparators=[inner()]
        )
    if kind == "call":
        func = rng.choice(
            (
                ast.Name(
                    id=rng.choice(("require", "len", "range", "print", "eval", "Rand")),
                    ctx=ast.Load(),
                ),
                ast.Attribute(value=_load_name(rng), attr=rng.choice(_ATTRS), ctx=ast.Load()),
            )
        )
        args = [inner() for _ in range(rng.randrange(0, 4))]
        keywords = []
        if rng.random() < 0.2:
            keywords.append(
                ast.keyword(
                    arg=None if rng.random() < 0.5 else rng.choice(("err", "cond")), value=inner()
                )
            )
        return ast.Call(func=func, args=args, keywords=keywords)
    if kind == "attribute":
        return ast.Attribute(value=_load_name(rng), attr=rng.choice(_ATTRS), ctx=ast.Load())
    if kind == "subscript":
        return ast.Subscript(value=_load_name(rng), slice=inner(), ctx=ast.Load())
    if kind == "ifexp":
        return ast.IfExp(test=inner(), body=inner(), orelse=inner())
    if kind == "lambda":
        return ast.Lambda(args=_arguments(rng), body=inner())
    if kind == "fstring":
        return ast.JoinedStr(values=[inner(), ast.Constant(value="s")])
    if kind == "literal":
        return rng.choice(
            (
                ast.List(elts=[inner(), inner()], ctx=ast.Load()),
                ast.Dict(keys=[inner()], values=[inner()]),
                ast.Tuple(elts=[inner()], ctx=ast.Load()),
                ast.Set(elts=[inner()], ctx=ast.Load()),
            )
        )
    if kind == "starred":
        return ast.Starred(value=inner(), ctx=ast.Load())
    return ast.NamedExpr(target=_load_name(rng), value=inner())


def _stmt(rng: random.Random, depth: int) -> ast.stmt:
    kind = rng.choice(
        (
            "assign",
            "assign",
            "annassign",
            "augassign",
            "expr",
            "if",
            "while",
            "for",
            "return",
            "try",
            "assert",
            "with",
            "global",
            "delete",
            "pass",
            "raise",
        )
    )
    if kind == "assign":
        targets = [
            rng.choice(
                (
                    ast.Name(id=rng.choice(_NAMES), ctx=ast.Store()),
                    ast.Attribute(value=_load_name(rng), attr=rng.choice(_ATTRS), ctx=ast.Store()),
                    ast.Subscript(
                        value=_load_name(rng), slice=ast.Constant(value=0), ctx=ast.Store()
                    ),
                )
            )
            for _ in range(rng.randrange(1, 3))
        ]
        return ast.Assign(targets=targets, value=_expr(rng, depth))
    if kind == "annassign":
        return ast.AnnAssign(
            target=ast.Name(id=rng.choice(_NAMES), ctx=ast.Store()),
            annotation=_ann(rng),
            value=None if rng.random() < 0.5 else _expr(rng, depth),
            simple=1,
        )
    if kind == "augassign":
        return ast.AugAssign(
            target=ast.Name(id=rng.choice(_NAMES), ctx=ast.Store()),
            op=_BIN_OPS[rng.randrange(len(_BIN_OPS))](),
            value=_expr(rng, depth),
        )
    if kind == "expr":
        return ast.Expr(value=_expr(rng, depth))
    if kind == "if":
        return ast.If(
            test=_expr(rng, depth), body=[_stmt(rng, depth - 1)], orelse=[_stmt(rng, depth - 1)]
        )
    if kind == "while":
        return ast.While(test=_expr(rng, depth), body=[_stmt(rng, depth - 1)], orelse=[])
    if kind == "for":
        return ast.For(
            target=ast.Name(id=rng.choice(_NAMES), ctx=ast.Store()),
            iter=_expr(rng, depth),
            body=[_stmt(rng, depth - 1)],
            orelse=[],
        )
    if kind == "return":
        return ast.Return(value=None if rng.random() < 0.5 else _expr(rng, depth))
    if kind == "try":
        return ast.Try(
            body=[_stmt(rng, depth - 1)],
            handlers=[
                ast.ExceptHandler(
                    type=None if rng.random() < 0.5 else ast.Name(id="Exception", ctx=ast.Load()),
                    name=None,
                    body=[ast.Pass()],
                )
            ],
            orelse=[],
            finalbody=[],
        )
    if kind == "assert":
        return ast.Assert(test=_expr(rng, depth), msg=None)
    if kind == "with":
        return ast.If(test=ast.Constant(value=True), body=[ast.Pass()], orelse=[])
    if kind == "global":
        return ast.Global(names=[rng.choice(_NAMES)])
    if kind == "delete":
        return ast.Delete(targets=[ast.Name(id=rng.choice(_NAMES), ctx=ast.Del())])
    if kind == "pass":
        return ast.Pass()
    return ast.Return(value=None)


def _top_stmt(rng: random.Random, depth: int) -> ast.stmt:
    kind = rng.random()
    if kind < 0.35:
        return ast.FunctionDef(
            name=rng.choice(("increment", "initialize", "f", "duplicate")),
            args=_arguments(rng),
            body=[_stmt(rng, depth) for _ in range(rng.randrange(0, 3))] or [ast.Pass()],
            decorator_list=[
                rng.choice(
                    (
                        [
                            ast.Name(
                                id=rng.choice(("instruction", "account", "Nope")), ctx=ast.Load()
                            )
                        ],
                        [
                            ast.Call(
                                func=ast.Name(id="instruction", ctx=ast.Load()),
                                args=[],
                                keywords=[],
                            )
                        ],
                        [],
                    )
                )
            ],
            returns=None if rng.random() < 0.4 else ast.Name(id="None", ctx=ast.Load()),
            type_params=[],
        )
    if kind < 0.65:
        base: list[ast.expr] = (
            [ast.Name(id="ProgramError", ctx=ast.Load())] if rng.random() < 0.2 else []
        )
        body: list[ast.stmt] = []
        if rng.random() < 0.6:
            body.append(
                ast.Assign(
                    targets=[ast.Name(id=rng.choice(("Member", "Bad", "dup")), ctx=ast.Store())],
                    value=ast.Constant(value=rng.choice((100, -1, 2**33, "x", True))),
                )
            )
        if rng.random() < 0.6:
            body.append(
                ast.AnnAssign(
                    target=ast.Name(id=rng.choice(("count", "authority")), ctx=ast.Store()),
                    annotation=_ann(rng),
                    value=None,
                    simple=1,
                )
            )
        if rng.random() < 0.2:
            body.append(
                ast.FunctionDef(
                    name="m",
                    args=_arguments(rng),
                    body=[ast.Pass()],
                    decorator_list=[],
                    returns=None,
                    type_params=[],
                )
            )
        return ast.ClassDef(
            name=rng.choice(("Counter", "Err", "Counter")),
            bases=base,
            keywords=[],
            body=body or [ast.Pass()],
            decorator_list=[
                rng.choice(
                    (
                        [
                            ast.Name(
                                id=rng.choice(("account", "error", "instruction")), ctx=ast.Load()
                            )
                        ],
                        [],
                    )
                )
            ],
            type_params=[],
        )
    if kind < 0.8:
        return ast.ImportFrom(
            module=rng.choice(("pythsol", "typing", "os")),
            names=[
                ast.alias(
                    name=rng.choice(("Mut", "u64", "Nope", "require", "*")),
                    asname=None if rng.random() < 0.8 else "a",
                )
            ],
            level=0,
        )
    if kind < 0.9:
        return ast.Import(names=[ast.alias(name=rng.choice(("os", "json.tool")), asname=None)])
    return _stmt(rng, depth)


def _module_for(rng: random.Random) -> ast.Module:
    body = [
        ast.ImportFrom(
            module="__future__", names=[ast.alias(name="annotations", asname=None)], level=0
        )
    ]
    for _ in range(rng.randrange(1, 5)):
        body.append(_top_stmt(rng, rng.choice((1, 2, 3))))
    mod = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(mod)
    return mod


def test_fuzz_random_trees_never_crash() -> None:
    """300 seeds: check_tree must return PSxxxx diagnostics, never raise."""
    for seed in range(300):
        rng = random.Random(seed)
        tree = _module_for(rng)
        try:
            diagnostics = front.check_tree(tree, file=f"fuzz-{seed}.py")
        except BaseException as err:
            raise AssertionError(
                f"seed {seed}: check_tree raised {type(err).__name__}: {err}"
            ) from err
        _assert_llp(diagnostics, seed)


def test_fuzz_unparsed_text_never_crashes() -> None:
    """Where ast.unparse works, the text pipeline must behave the same."""
    unparseable = 0
    diagnostics_total = 0
    for seed in range(120):
        rng = random.Random(10_000 + seed)
        tree = _module_for(rng)
        try:
            source = ast.unparse(tree)
        except Exception:
            unparseable += 1
            continue
        try:
            diagnostics = front.check_source(source, file=f"fuzz-{seed}.py")
        except BaseException as err:
            raise AssertionError(
                f"seed {seed}: check_source raised {type(err).__name__}: {err}"
            ) from err
        _assert_llp(diagnostics, seed)
        diagnostics_total += len(diagnostics)
    # The palette is mostly-rejected shapes: the aggregate must not be empty,
    # otherwise the fuzzer is not exercising the negative paths at all.
    assert diagnostics_total > 0
    assert unparseable < 120  # ast.unparse should handle our constructed trees


def _assert_llp(diagnostics: list[Diagnostic], seed: int) -> None:
    """Low-level invariants for every fuzz result."""
    codes = [d.code for d in diagnostics]
    for code in codes:
        assert _CODE.match(code), (seed, code)
    if any(code == PS9000 for code in codes):
        raise AssertionError(
            f"seed {seed}: PS9000 internal error (compiler bug):\n"
            + "\n".join(d.render() for d in diagnostics if d.code == PS9000)
        )
