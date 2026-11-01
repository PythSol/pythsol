---
title: Local playground
description: pythsol serve checks and emits on your machine.
---

```bash
pythsol serve
```

The server binds `127.0.0.1:8765` (also `localhost` and `::1`). Any other
host exits 2. The page loads the four examples and can `POST /v1/check`,
`POST /v1/emit`, or `POST /v1/compile`. Check and emit use the compiler.
Compile runs clang on the generated C when the SBF tools are installed and
returns the `.so` as base64. None of these paths execute the program.

There is no wallet connect and no hosted Pyodide build. A request body that
contains a keypair, seed phrase, or mnemonic is rejected.
