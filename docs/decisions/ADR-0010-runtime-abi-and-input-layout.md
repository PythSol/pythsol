# ADR-0010 — SBF input layout, C-ABI CPI structs, and Phase 3 runtime conventions

- **Status:** accepted
- **Date:** 2026-10-31
- **Deciders:** PythSol contributors

## Context

Phase 3's runtime (`src/pythsol/runtime/pythsol_rt.h`) had to interoperate
**byte-for-byte** with the Solana VM: the serialized input the loader hands to
`entrypoint`, the syscall ABIs for `sol_invoke_signed_c` / `sol_sha256`, PDA
derivation, and the System-program `create_account` payload. TRD §7 sketched
these from public docs; several assumptions turned out **wrong or incomplete**
and are fixed here after empirical verification against LiteSVM
(`solders.litesvm`) plus the agave 1.18.26 sources
(`programs/bpf_loader/src/syscalls/cpi.rs`).

Every item below was verified by running real programs in LiteSVM
(`tests/test_phase3_litesvm.py` passes: initialize → increment(5) == 5,
unauthorized increment → code 6000 + `(counter.py:51)` log, overflow increment
→ checked-add abort with `(counter.py:52)` log).

## Decision

### 1. Serialized input layout (per instruction account)

```
u32 account_count
per account:
    u8  dup_tag        0xFF = NOT a duplicate; < 0xFF = index of the original
    u8  is_signer, u8 is_writable, u8 executable          (3 × u8)
    u32 original_data_len                                 (unused by us)
    u8  key[32]
    u8  owner[32]
    u64 lamports      ← kept as a *pointer* into the input buffer
    u64 data_len
    u8  data[data_len (+ MAX_PERMITTED_DATA_INCREASE zero bytes)]
    u64 rent_epoch     (after padding the data offset to 8)
```

**Inversion of the TRD assumption:** the VM marks *regular* accounts with
`dup_tag = 0xFF` (`u8::MAX`); only true duplicates carry their index.
`rt_entrypoint` therefore **rejects any byte ≠ 0xFF** ("duplicate accounts are
not supported") and keeps the account's fields as zero-copy pointers.

Proof: hex-dump spike (`Spikes/c/dump_input.c` + `dbg_dump_input.py`) shows
`…ff 01 01 …` as the leading bytes of the first account (dup 0xFF, signer 1,
writable 1).

### 2. Instruction data starts after the cropped discriminator

`rt_entrypoint` consumes the leading 8-byte instruction discriminator itself
and dispatches via the generated `RT_DISPATCH` table, exposing
`rt->data = instr_data + 8` and `rt->data_len = instr_len - 8`.

Consequence for the emitter: the Borsh decode of instruction data starts at
offset **0** in `rt->data` and the enforced length check is exactly
`sum(data_param widths)`. (The first emitter draft still assumed the disc was
included — proven wrong by the `(counter.py:41) instruction data length is
wrong` log, since fixed.)

### 3. `sol_invoke_signed_c` is the 5-argument C ABI

```c
extern uint64_t sol_invoke_signed_c(
    const SolInstruction *ix,           /* {program_id, accounts, n, data, n} */
    const SolAccountInfo *infos,        /* caller-side views, see below      */
    uint64_t n_infos,
    const SolSignerSeeds *seed_groups,  /* {SolSignerSeed*, len} per signer  */
    uint64_t n_groups);
```

- `SolAccountMeta` = `{SolPubkey *pubkey; u8 is_writable; u8 is_signer}` —
  **16-byte stride** (u8 flags, *not* `u64`). A u64-flag struct makes the VM
  read past the array: `Access violation … address 0x101` in LiteSVM.
- `SolAccountInfo` = `{SolPubkey *key; u64 *lamports; u64 data_len (*by
  value*); u8 *data; SolPubkey *owner; u64 rent_epoch; u8 signer/writable/
  executable;}` (56-byte stride). `data_len` is passed **by value** and the
  host writes the post-CPI length back into it **and** into the serialized
  input's length field (i.e. `data - 8` in our decode), then copies the
  callee's data over the caller's region — so writes via `acct->data[8..N]`
  after a CPI persist.
- `SolSignerSeed` = `{addr, len}`; one signer **is one entry** of a
  `SolSignerSeeds` array, each pointing at its own seed arrays
  (`[{seed0, bump}]` for the counter PDA).

### 4. PDA derivation includes the domain suffix

`Pubkey::find_program_address` derives
`sha256(seed0 ‖ bump ‖ program_id ‖ "ProgramDerivedAddress")` — the 21-byte
`"ProgramDerivedAddress"` suffix is **not optional**. Without it, verification
succeeds against the wrong key and real PDAs fail with RT_ERR_PDA (1008)
(`counter is not the expected PDA` log before the fix).

### 5. CPI requires the System program in the *caller's* account list

Any CPI'd program must appear in the invoking transaction's accounts. The
emitter hence guards `Init` lowering with a runtime scan for the System
program id and reports a position-accurate
`System program account is required: init` failure (RT_ERR_CPI, 1007)
otherwise. The harness (`_Counter.initialize`) passes
`[authority, pda, system]` accordingly.

### 6. `Init` stores the account discriminator after the CPI

The System program zeroes fresh accounts; the `global:` counter
discriminator is written **post-CPI** via `rt_st_disc(..., RT_DISC_COUNTER)`,
verified on-chain as `ffb004f5bcfd7c19`.

### 7. Rent for created accounts

Emitted lamports = `(space + 128) * 3480 * 2` (the exact integer rendering of
Anchor's f64 calculation); 49 bytes → **1,231,920** lamports.

### 8. No static globals, keep stack frames small

The SBF ELF loader rejects writable sections ("Found writable section (.bss)
in ELF…"), so generated code uses no static/global buffers. The SBF stack is
≈4 KB: runtime helper buffers are statically bounded
(`RT_LOG_BUF 192`, `RT_PDA_SEED_MAX 32`), and the CPI explodes into
fixed-size stack arrays (`payload[52]`, 2 metas + 2 infos + seed groups).

### 9. secp256k1-free error code table

| code  | meaning                                    |
|-------|--------------------------------------------|
| 1     | RT_ERR_UNKNOWN (bad discriminator/length)  |
| 1001  | signer required                            |
| 1002  | writable required                          |
| 1003  | owner mismatch                             |
| 1004  | account size mismatch                      |
| 1005  | account discriminator mismatch             |
| 1006  | missing account                            |
| 1007  | CPI failure (incl. missing System account) |
| 1008  | PDA verification failed (bad seeds/bump)   |
| 1009  | checked arithmetic overflow                |
| 1010  | division by zero                           |
| 6000+n | custom errors (Anchor convention)         |

`rt_fail_log` prints messages as `Program log: (file:line) text`, which is the
TRD-mandated on-chain attribution format.

## Consequences

- The Phase 3 acceptance target (`examples/counter`) runs correctly in a real
  VM simulator; the ABI pins are now regression-guarded by the LiteSVM suite.
- Phase 4 (helper functions, more types, constraints) inherits the same
  input/CPI conventions — **no further struct rewrites expected**; any change
  must re-run `tests/test_phase3_litesvm.py`.
- If a future agave changes the C ABI (e.g. `sol_invoke_signed_c` struct
  packing), the hex-dump spike in `Spikes/` is the reproduction harness.
- CI keeps `--strict-markers` clean; the LiteSVM + toolchain tests skip on
  machines without Anza platform-tools (ADR-0006) and always run on Linux CI.
