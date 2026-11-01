"""`pythsol serve` — local playground on 127.0.0.1."""

from __future__ import annotations

import sys

import click

from pythsol.playground.server import bind

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


@click.command(name="serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
@click.option(
    "--public",
    is_flag=True,
    help="Allow a non-loopback host. Check and emit only; compile stays off.",
)
@click.option(
    "--allow-compile",
    is_flag=True,
    help="With --public, also serve POST /v1/compile. Clang sees only "
    "compiler-generated C, never visitor source. Off by default.",
)
def serve(host: str, port: int, public: bool, allow_compile: bool) -> None:
    """Serve the playground. Check and emit parse source. They do not run it.

    Without ``--public`` the process accepts only loopback and can compile.
    ``--public`` is the hostable mode: any host, no clang until you also
    pass ``--allow-compile``.
    """
    if host not in _LOOPBACK and not public:
        click.echo(
            "error: --host must be 127.0.0.1, localhost, or ::1 (or pass --public)",
            err=True,
        )
        sys.exit(2)
    try:
        httpd = bind(host, port, public=public, allow_compile=allow_compile)
    except OSError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    mode = "check+emit+compile" if ((not public) or allow_compile) else "check+emit"
    click.echo(f"playground: http://{host}:{port}/ ({mode})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    sys.exit(0)
