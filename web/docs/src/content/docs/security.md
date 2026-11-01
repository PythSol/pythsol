---
title: Security
description: What this tree does with keys and user source. No audit is published.
---

The compiler does not execute user programs. `pythsol serve` parses posted
source and rejects JSON keys named like a keypair, seed phrase, or mnemonic.
The wallet command writes a keypair file and prints the secret only with
`--show-secret`.

Deploy and the faucet talk to the URL you choose. Mainnet deploy needs
`--yes`. The faucet refuses mainnet.

No independent audit report is published for this tree. Treat generated
programs as unaudited.
