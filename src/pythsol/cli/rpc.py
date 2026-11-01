"""JSON-RPC helper for faucet and wallet balance.

The compiler never calls this. Commands that talk to a cluster the user named
do. The body is a JSON-RPC request and the response is parsed as JSON.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

__all__ = ["RpcError", "post_json"]


class RpcError(Exception):
    """The endpoint refused the call or returned an error object."""


def post_json(
    url: str,
    method: str,
    params: list[object],
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """POST one JSON-RPC request and return the decoded object."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(
        "utf-8"
    )
    request = Request(
        url,
        data=payload,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RpcError(detail or f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise RpcError(str(exc.reason)) from exc
    try:
        body = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RpcError("RPC response was not JSON") from exc
    if not isinstance(body, dict):
        raise RpcError("RPC response was not an object")
    if "error" in body and body["error"] is not None:
        error = body["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RpcError(str(message))
    return body
