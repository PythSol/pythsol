# Security policy

Security is a core commitment of PythSol.

- **Scope:** the compiler, the runtime header, the CLI, anything that runs on chain.
- **Never** include a real funding key, signature, or transaction payload in a
  report; redact before sending.
- We respond within 2 business days and keep reports private until they are
  resolved and disclosed. Preferred contact: GitHub security advisories at
  <https://github.com/PythSol/pythsol/security>.

## Reported issues (tracked)

| Where | Notes |
|---|---|
| <https://github.com/PythSol/pythsol/issues> | For public questions that don't reveal a vulnerability. |
| GitHub Security Advisories | Report every vulnerability. |

We follow the [Open Source Security Foundation](https://openssf.org/) practices
for release-provenance and dependency hygiene: dependencies are pinned and
audited, the compiler depends on `click` only, wheels are pure-Python and
`py.typed`-marked, and anything shipped must pass the phase gates in
`docs/spec/TRD.md` §18.
