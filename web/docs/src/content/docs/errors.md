---
title: Errors
description: Framework codes and program codes.
---

| Code | Meaning |
|---|---|
| 1 | Malformed input or an unknown instruction discriminator |
| 1001 | A `Signer` account was not signed |
| 1002 | A mutable account was not writable |
| 1003 | Owner check failed |
| 1004 | Account size does not match the layout |
| 1005 | Account discriminator mismatch |
| 1006 | Missing account or an internal bounds failure |
| 1007 | A CPI failed |
| 1008 | Account is not the expected PDA |
| 1009 | Checked arithmetic overflowed |
| 1010 | Division by zero, or an illegal shift count |
| 1011 | Unit-enum byte is not a declared variant |
| 1012 | `.value` while an option tag is clear |
| 1013 | `FixedString` length past its reserved bytes |
| 1014 | An account constraint failed |

Program errors are `6000 + index` in the `@error` class. The integer written
beside the name is documentation. `expect_error("Unauthorized")` uses the
name. Logs include `(file.py:line)`.
