/*
 * pythsol_rt.h — header-only C runtime linked into every emitted program.
 *
 * Design rules (TRD §6/§13, Phase 3):
 *   * C11 subset, `static inline` helpers, no libc, no static data (each
 *     invocation context lives on the entrypoint's stack).
 *   * Every user-visible failure is reported through `rt_fail_log`, which
 *     prefixes the program's source location: "(counter.py:51) ...".
 *   * Helpers return RT_OK (0) or a framework error code; custom program
 *     errors live in 6000+ and can never collide.
 *
 * Framework error table (stable for v0):
 *   RT_ERR_UNKNOWN   1     malformed input / unknown instruction discriminator
 *   RT_ERR_SIGNER    1001  an account of role Signer was not signed
 *   RT_ERR_WRITABLE  1002  an account of role Mut/Init was not writable
 *   RT_ERR_OWNER     1003  account owner check failed
 *   RT_ERR_SIZE      1004  account data length does not match the layout
 *   RT_ERR_DISC      1005  account discriminator mismatch
 *   RT_ERR_OOB       1006  bounds failure (missing accounts, internal bug)
 *   RT_ERR_CPI       1007  a CPI to the System program failed
 *   RT_ERR_PDA       1008  account is not the expected PDA
 *   RT_ERR_OVERFLOW  1009  checked arithmetic overflowed
 *   RT_ERR_DIV_ZERO  1010  division by zero
 *
 * The runtime never dereferences beyond what the caller checked; field
 * access helpers are unchecked because the account-size equality check is
 * mandatory before any field access (see pythsol compiler emit invariants).
 *
 * Input serialization — verified against solana-program 1.18.26
 * `entrypoint.rs` (docs.rs src view; reproduced here so the spike test in
 * tests/test_phase3_litesvm.py can be diffed against it):
 *
 *   u64 account_count
 *   [account_count] {
 *       u8 dup_tag                  (0xFF = NOT dup; <u8> = index of a dup)
 *       u8 is_signer, u8 is_writable, u8 executable
 *       u32 original_data_len       (parsed only for ordering)
 *       u8 key[32]
 *       u8 owner[32]
 *       u64 lamports
 *       u64 data_len
 *       u8 data[data_len + 10240]   (Solana's MAX_PERMITTED_DATA_INCREASE)
 *       u64 rent_epoch              (after pad-to-8 of the offset)
 *   }
 *   u64 instruction_data_len
 *   u8  instruction_data[len]
 *   u8  program_id[32]
 *
 * `entrypoint` is defined by the emitted program (dispatches to
 * `rt_entrypoint` below with its instruction table).
 */

#ifndef PYTHSOL_RT_H
#define PYTHSOL_RT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------ */
/* Syscall ABI (resolved by the SBF loader; declared `extern` so lld   */
/* leaves them unresolved inside -z notext as in the Phase 1 spike)    */
/* ------------------------------------------------------------------ */

typedef struct SolPubkey {
    unsigned char x[32];
} SolPubkey;

typedef struct SolAccountMeta {
    SolPubkey *pubkey;
    /* u8 fields per the VM's C ABI (16-byte stride); see ADR-0010. */
    uint8_t is_writable;
    uint8_t is_signer;
} SolAccountMeta;

/* Caller-side account view for the C-ABI CPI syscall. Field ORDER and the
 * by-value `data_len` must match agave's repr(C) SolAccountInfo exactly
 * (56-byte stride): the host reads `data_len` as a value and writes the
 * post-CPI length back into this struct AND into the serialized input
 * buffer's length field, then copies the new account data over `data`. */
typedef struct SolAccountInfo {
    SolPubkey *key;
    uint64_t *lamports; /* points at the current lamports value */
    uint64_t data_len;  /* by value; updated in place after CPI */
    uint8_t *data;
    SolPubkey *owner;
    uint64_t rent_epoch;
    uint8_t is_signer;
    uint8_t is_writable;
    uint8_t executable;
} SolAccountInfo;

typedef struct SolInstruction {
    SolPubkey *program_id;
    SolAccountMeta *accounts;
    uint64_t accounts_len;
    uint8_t *data;
    uint64_t data_len;
} SolInstruction;

typedef struct SolSignerSeed {
    const unsigned char *addr;
    uint64_t len;
} SolSignerSeed;

/* One signer = a SolSignerSeed ARRAY; the syscall takes an array of these. */
typedef struct SolSignerSeeds {
    SolSignerSeed *seeds;
    uint64_t len;
} SolSignerSeeds;

extern uint64_t sol_log_(const unsigned char *msg, uint64_t len);
extern uint64_t sol_invoke_signed_c(
    const SolInstruction *instruction,
    const SolAccountInfo *account_infos,
    uint64_t account_infos_len,
    const SolSignerSeeds *signers_seeds,
    uint64_t signers_seeds_len);
extern uint64_t sol_sha256(const uint64_t *vals, int val_cnt, unsigned char *result);

#ifdef __cplusplus
}
#endif

/* ------------------------------------------------------------------ */
/* Error codes                                                         */
/* ------------------------------------------------------------------ */

#define RT_OK 0u
#define RT_ERR_UNKNOWN 1u
#define RT_ERR_SIGNER 1001u
#define RT_ERR_WRITABLE 1002u
#define RT_ERR_OWNER 1003u
#define RT_ERR_SIZE 1004u
#define RT_ERR_DISC 1005u
#define RT_ERR_OOB 1006u
#define RT_ERR_CPI 1007u
#define RT_ERR_PDA 1008u
#define RT_ERR_OVERFLOW 1009u
#define RT_ERR_DIV_ZERO 1010u

/* ------------------------------------------------------------------ */
/* Caps                                                                */
/* ------------------------------------------------------------------ */

#define RT_MAX_ACCOUNTS 32u
#define RT_MAX_INSTR_LEN 4096u
#define RT_DATA_INCREASE 10240u
/* 0xFF marks a NOT-duplicated account (u8::MAX); any other byte is the index
 * of the original account and means we would need duplicate handling.
 * Verified empirically against LiteSVM + solana-program 1.18: the VM marks
 * regular accounts with 0xFF and only real duplicates get their index. */
#define RT_NON_DUP_TAG 0xFFu
#define RT_LOG_BUF 192u
#define RT_PDA_SEED_MAX 32u
#define RT_PDA_DOMAIN_LEN 21u

/* System program id: 32 zero bytes. */
static const uint8_t RT_SYSTEM_ID[32] = {
    0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u,
    0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u
};

/* ------------------------------------------------------------------ */
/* Invocation context                                                  */
/* ------------------------------------------------------------------ */

typedef struct RtAccount {
    SolPubkey *key;
    uint64_t *lamports; /* VM pointer; the CPI syscalls update it in place */
    SolPubkey *owner;
    uint8_t *data;
    uint64_t data_len;
    uint8_t is_signer;
    uint8_t is_writable;
    uint8_t executable;
} RtAccount;

typedef struct RtCtx {
    RtAccount accounts[RT_MAX_ACCOUNTS];
    uint64_t n_accounts;
    const uint8_t *data;       /* instruction data, discriminator removed */
    uint64_t data_len;
    const uint8_t *program_id; /* 32 bytes, points into the input buffer */
} RtCtx;

typedef struct RtDispatchEntry {
    const unsigned char disc[8];
    uint64_t (*fn)(RtCtx *rt);
} RtDispatchEntry;

/* ------------------------------------------------------------------ */
/* Logging with a source location                                      */
/* ------------------------------------------------------------------ */

static inline void rt_itoa_u64(uint64_t value, char *out) {
    char tmp[21];
    uint64_t i = 0u, j = 0u;
    if (value == 0u) {
        out[0] = (char)'0';
        out[1] = '\0';
        return;
    }
    while (value > 0u && i < 20u) {
        tmp[i++] = (char)('0' + (int)(value % 10u));
        value /= 10u;
    }
    while (i > 0u) {
        out[j++] = tmp[--i];
    }
    out[j] = '\0';
}

static inline uint64_t rt_str_len(const char *s) {
    uint64_t n = 0u;
    while (s[n] != '\0') {
        n++;
    }
    return n;
}

/* Log one failure line: "(<file>:<line>) <what>". Both parts are bounded
 * so the log cannot overflow the 192-byte scratch buffer. */
static inline void rt_fail_log(uint64_t code, const char *file, uint64_t line,
                               const char *what) {
    char buf[RT_LOG_BUF];
    char num[21];
    uint64_t k = 0u;
    uint64_t i = 0u;
    uint64_t flen = rt_str_len(file);
    buf[k++] = (char)'(';
    for (i = 0u; i < flen && k + 4u < (uint64_t)(RT_LOG_BUF - 40u); i++) {
        buf[k++] = file[i];
    }
    buf[k++] = (char)':';
    rt_itoa_u64(line, num);
    for (i = 0u; num[i] != '\0' && k + 2u < (uint64_t)(RT_LOG_BUF - 24u); i++) {
        buf[k++] = num[i];
    }
    buf[k++] = (char)')';
    buf[k++] = (char)' ';
    if (what != (const char *)0) {
        uint64_t wlen = rt_str_len(what);
        for (i = 0u; i < wlen && k + 1u < RT_LOG_BUF; i++) {
            buf[k++] = what[i];
        }
    }
    buf[k] = '\0';
    (void)code; /* the code travels in the return value, not in the log */
    (void)sol_log_((const unsigned char *)buf, k);
}

/* ------------------------------------------------------------------ */
/* Little-endian field access (byte-wise; alignment-safe on SBF)        */
/* ------------------------------------------------------------------ */

static inline uint64_t rt_ld_u16(const uint8_t *d, uint64_t off, uint16_t *out) {
    *out = (uint16_t)(d[off] | ((uint16_t)d[off + 1u] << 8));
    return RT_OK;
}

static inline uint64_t rt_ld_u32(const uint8_t *d, uint64_t off, uint32_t *out) {
    *out = (uint32_t)(d[off] | ((uint32_t)d[off + 1u] << 8) |
                      ((uint32_t)d[off + 2u] << 16) | ((uint32_t)d[off + 3u] << 24));
    return RT_OK;
}

static inline uint64_t rt_ld_u64(const uint8_t *d, uint64_t off, uint64_t *out) {
    uint64_t v = 0u;
    uint64_t i;
    for (i = 0u; i < 8u; i++) {
        v |= (uint64_t)d[off + i] << (8u * i);
    }
    *out = v;
    return RT_OK;
}

static inline void rt_st_u16(uint8_t *d, uint64_t off, uint16_t v) {
    d[off] = (uint8_t)(v & 0xFFu);
    d[off + 1u] = (uint8_t)((v >> 8) & 0xFFu);
}

static inline void rt_st_u32(uint8_t *d, uint64_t off, uint32_t v) {
    d[off] = (uint8_t)(v & 0xFFu);
    d[off + 1u] = (uint8_t)((v >> 8) & 0xFFu);
    d[off + 2u] = (uint8_t)((v >> 16) & 0xFFu);
    d[off + 3u] = (uint8_t)((v >> 24) & 0xFFu);
}

static inline void rt_st_u64(uint8_t *d, uint64_t off, uint64_t v) {
    uint64_t i;
    for (i = 0u; i < 8u; i++) {
        d[off + i] = (uint8_t)((v >> (8u * i)) & 0xFFu);
    }
}

/* 8-byte account discriminator store/compare. */
static inline void rt_st_disc(uint8_t *d, const unsigned char *disc) {
    uint64_t i;
    for (i = 0u; i < 8u; i++) {
        d[i] = disc[i];
    }
}

static inline uint64_t rt_disc_eq(const uint8_t *d, const unsigned char *disc) {
    uint64_t i;
    for (i = 0u; i < 8u; i++) {
        if (d[i] != disc[i]) {
            return 0u;
        }
    }
    return 1u;
}

/* 32-byte key helpers (alignment-safe by construction). */
static inline uint64_t rt_key_eq(const SolPubkey *a, const SolPubkey *b) {
    uint64_t i;
    for (i = 0u; i < 32u; i++) {
        if (a->x[i] != b->x[i]) {
            return 0u;
        }
    }
    return 1u;
}

static inline void rt_key_copy(SolPubkey *dst, const SolPubkey *src) {
    uint64_t i;
    for (i = 0u; i < 32u; i++) {
        dst->x[i] = src->x[i];
    }
}

/* Store a 32-byte key into account data at `off`; read one back as a
 * pointer that can be compared/copied without alignment assumptions. */
static inline void rt_st_key(uint8_t *d, uint64_t off, const SolPubkey *src) {
    uint64_t i;
    for (i = 0u; i < 32u; i++) {
        d[off + i] = src->x[i];
    }
}

static inline uint64_t rt_owner_eq(const RtAccount *acct, const uint8_t *pid) {
    uint64_t i;
    for (i = 0u; i < 32u; i++) {
        if (acct->owner->x[i] != pid[i]) {
            return 0u;
        }
    }
    return 1u;
}

/* ------------------------------------------------------------------ */
/* Checked arithmetic (compiler builtins; no libc)                      */
/* ------------------------------------------------------------------ */

static inline uint64_t rt_checked_add_u64(uint64_t a, uint64_t b, uint64_t *out) {
    return __builtin_add_overflow(a, b, out) ? 1u : 0u;
}

static inline uint64_t rt_checked_sub_u64(uint64_t a, uint64_t b, uint64_t *out) {
    return __builtin_sub_overflow(a, b, out) ? 1u : 0u;
}

static inline uint64_t rt_checked_mul_u64(uint64_t a, uint64_t b, uint64_t *out) {
    return __builtin_mul_overflow(a, b, out) ? 1u : 0u;
}

static inline uint64_t rt_checked_div_u64(uint64_t a, uint64_t b, uint64_t *out) {
    if (b == 0u) {
        return 1u;
    }
    *out = a / b;
    return 0u;
}

static inline uint64_t rt_checked_mod_u64(uint64_t a, uint64_t b, uint64_t *out) {
    if (b == 0u) {
        return 1u;
    }
    *out = a % b;
    return 0u;
}

/* Signed flavour (used when operands are i64). */
static inline uint64_t rt_checked_add_i64(int64_t a, int64_t b, int64_t *out) {
    return __builtin_add_overflow(a, b, out) ? 1u : 0u;
}

static inline uint64_t rt_checked_sub_i64(int64_t a, int64_t b, int64_t *out) {
    return __builtin_sub_overflow(a, b, out) ? 1u : 0u;
}

static inline uint64_t rt_checked_mul_i64(int64_t a, int64_t b, int64_t *out) {
    return __builtin_mul_overflow(a, b, out) ? 1u : 0u;
}

static inline uint64_t rt_checked_div_i64(int64_t a, int64_t b, int64_t *out) {
    if (b == 0) {
        return 1u;
    }
    if (a == (int64_t)(-9223372036854775807ll - 1) && b == -1) {
        return 1u; /* INT64_MIN / -1 overflows */
    }
    *out = a / b;
    return 0u;
}

static inline uint64_t rt_checked_mod_i64(int64_t a, int64_t b, int64_t *out) {
    if (b == 0) {
        return 1u;
    }
    if (a == (int64_t)(-9223372036854775807ll - 1) && b == -1) {
        *out = 0;
        return 0u;
    }
    *out = a % b;
    return 0u;
}

/* ------------------------------------------------------------------ */
/* PDA verification:                                                   */
/*   sha256(seed0 || bump || program_id || "ProgramDerivedAddress")     */
/*   == key  — exactly Pubkey::find_program_address's derivation       */
/* ------------------------------------------------------------------ */

static const unsigned char RT_PDA_DOMAIN[21] = {
    'P', 'r', 'o', 'g', 'r', 'a', 'm', 'D', 'e', 'r', 'i', 'v', 'e',
    'd', 'A', 'd', 'd', 'r', 'e', 's', 's'
};

static inline uint64_t rt_verify_pda(const RtCtx *rt, const RtAccount *acct,
                                     const uint8_t *seed0, uint64_t seed0_len,
                                     uint8_t bump) {
    unsigned char joined[RT_PDA_SEED_MAX + 1u + 32u + 21u];
    unsigned char digest[32];
    uint64_t vals[2];
    uint64_t n = 0u;
    uint64_t i;
    if (seed0_len > RT_PDA_SEED_MAX) {
        return 0u;
    }
    for (i = 0u; i < seed0_len; i++) {
        joined[n++] = seed0[i];
    }
    joined[n++] = bump;
    for (i = 0u; i < 32u; i++) {
        joined[n++] = rt->program_id[i];
    }
    for (i = 0u; i < RT_PDA_DOMAIN_LEN; i++) {
        joined[n++] = RT_PDA_DOMAIN[i];
    }
    vals[0] = (uint64_t)(uintptr_t)(void *)&joined[0];
    vals[1] = n;
    if (sol_sha256(vals, 1, digest) != RT_OK) {
        return 0u;
    }
    return rt_key_eq(acct->key, (const SolPubkey *)(const void *)digest);
}

/* ------------------------------------------------------------------ */
/* System program CPI: create_account (C ABI, agave 1.18 5-arg form)   */
/*                                                                     */
/* payload layout (System program, instruction tag 0):                 */
/*   u32 tag = 0 | u64 lamports | u64 space | u8 owner[32]  (52 bytes) */
/* account metas: [payer {signer,writable}, new_acct {writable,signer */
/*                 via seeds}]                                         */
/* account infos: full caller views — the host syncs lamports/owner/   */
/* data+data_len back through them after the callee finishes.          */
/* signer seeds: [seed0, bump] — the bump byte is its own 1-byte seed. */
/* ------------------------------------------------------------------ */

static inline uint64_t rt_system_create_account(
    RtCtx *rt, RtAccount *payer, RtAccount *new_acct,
    const uint8_t *seed0, uint64_t seed0_len, uint8_t bump,
    uint64_t lamports, uint64_t space) {
    uint8_t payload[52];
    SolAccountMeta metas[2];
    SolAccountInfo infos[2];
    SolSignerSeed seeds[2];
    SolSignerSeeds groups[1];
    uint8_t bump_seed[1];
    SolInstruction ix;
    uint64_t i;
    rt_st_u32(payload, 0u, 0u); /* system CreateAccount tag */
    rt_st_u64(payload, 4u, lamports);
    rt_st_u64(payload, 12u, space);
    for (i = 0u; i < 32u; i++) {
        payload[20u + i] = rt->program_id[i];
    }
    metas[0].pubkey = payer->key;
    metas[0].is_writable = 1u;
    metas[0].is_signer = 1u;
    metas[1].pubkey = new_acct->key;
    metas[1].is_writable = 1u;
    metas[1].is_signer = 1u;
    infos[0].key = payer->key;
    infos[0].lamports = payer->lamports;
    infos[0].data_len = payer->data_len;
    infos[0].data = payer->data;
    infos[0].owner = payer->owner;
    infos[0].rent_epoch = 0u;
    infos[0].is_signer = 0u;
    infos[0].is_writable = 0u;
    infos[0].executable = 0u;
    infos[1].key = new_acct->key;
    infos[1].lamports = new_acct->lamports;
    infos[1].data_len = new_acct->data_len;
    infos[1].data = new_acct->data;
    infos[1].owner = new_acct->owner;
    infos[1].rent_epoch = 0u;
    infos[1].is_signer = 0u;
    infos[1].is_writable = 0u;
    infos[1].executable = 0u;
    ix.program_id = (SolPubkey *)(const void *)RT_SYSTEM_ID;
    ix.accounts = &metas[0];
    ix.accounts_len = 2u;
    ix.data = &payload[0];
    ix.data_len = 52u;
    seeds[0].addr = seed0;
    seeds[0].len = seed0_len;
    bump_seed[0] = bump;
    seeds[1].addr = &bump_seed[0];
    seeds[1].len = 1u;
    groups[0].seeds = &seeds[0];
    groups[0].len = 2u;
    return sol_invoke_signed_c(&ix, &infos[0], 2u, &groups[0], 1u);
}

/* ------------------------------------------------------------------ */
/* Entry point machinery                                               */
/* ------------------------------------------------------------------ */

/* Deserialize the SBF input, dispatch on the 8-byte discriminator, run the
 * handler. Called by the emitted program's `entrypoint`. */
static inline uint64_t rt_entrypoint(const uint8_t *input,
                                     const RtDispatchEntry *table,
                                     uint64_t n_entries) {
    RtCtx rtx;
    uint64_t off = 0u;
    uint64_t count = 0u;
    uint64_t instr_len = 0u;
    const uint8_t *instr_data;
    uint64_t i;

    rtx.n_accounts = 0u;
    rtx.data = (const uint8_t *)0;
    rtx.data_len = 0u;
    rtx.program_id = (const uint8_t *)0;

    if (rt_ld_u64(input, off, &count) != RT_OK) {
        rt_fail_log(RT_ERR_UNKNOWN, "<rt>", 0u, "malformed input: no account count");
        return RT_ERR_UNKNOWN;
    }
    off += 8u;
    if (count > RT_MAX_ACCOUNTS) {
        rt_fail_log(RT_ERR_UNKNOWN, "<rt>", 0u, "too many accounts");
        return RT_ERR_UNKNOWN;
    }
    for (i = 0u; i < count; i++) {
        uint8_t dup_tag;
        uint8_t is_signer;
        uint8_t is_writable;
        uint8_t executable;
        uint64_t dlen = 0u;
        dup_tag = input[off];
        off += 1u;
        if (dup_tag != RT_NON_DUP_TAG) {
            rt_fail_log(RT_ERR_UNKNOWN, "<rt>", 0u,
                        "duplicate accounts are not supported");
            return RT_ERR_UNKNOWN;
        }
        is_signer = input[off];
        is_writable = input[off + 1u];
        executable = input[off + 2u];
        off += 3u;                 /* is_signer, is_writable, executable */
        off += 4u;                 /* u32 original_data_len (ordering only)  */
        rtx.accounts[i].key = (SolPubkey *)(void *)(input + off);
        off += 32u;
        rtx.accounts[i].owner = (SolPubkey *)(void *)(input + off);
        off += 32u;
        rtx.accounts[i].lamports = (uint64_t *)(void *)(input + off);
        off += 8u;
        if (rt_ld_u64(input, off, &dlen) != RT_OK) {
            rt_fail_log(RT_ERR_UNKNOWN, "<rt>", 0u, "malformed input: account data");
            return RT_ERR_UNKNOWN;
        }
        off += 8u;
        rtx.accounts[i].data = (uint8_t *)(void *)(input + off);
        rtx.accounts[i].data_len = dlen;
        off += dlen + RT_DATA_INCREASE;
        off = (off + 7u) & ~((uint64_t)7u); /* pad to 8 */
        off += 8u;                 /* u64 rent_epoch                         */
        rtx.accounts[i].is_signer = is_signer;
        rtx.accounts[i].is_writable = is_writable;
        rtx.accounts[i].executable = executable;
    }
    rtx.n_accounts = count;

    if (rt_ld_u64(input, off, &instr_len) != RT_OK) {
        rt_fail_log(RT_ERR_UNKNOWN, "<rt>", 0u, "malformed input: instruction length");
        return RT_ERR_UNKNOWN;
    }
    off += 8u;
    if (instr_len > RT_MAX_INSTR_LEN) {
        rt_fail_log(RT_ERR_UNKNOWN, "<rt>", 0u, "instruction data too large");
        return RT_ERR_UNKNOWN;
    }
    if (instr_len < 8u) {
        rt_fail_log(RT_ERR_UNKNOWN, "<rt>", 0u,
                    "instruction data missing discriminator");
        return RT_ERR_UNKNOWN;
    }
    instr_data = input + off;
    off += instr_len;
    rtx.program_id = input + off;

    for (i = 0u; i < n_entries; i++) {
        if (rt_disc_eq(instr_data, table[i].disc)) {
            rtx.data = instr_data + 8u;
            rtx.data_len = instr_len - 8u;
            return (*table[i].fn)(&rtx);
        }
    }
    rt_fail_log(RT_ERR_UNKNOWN, "<rt>", 0u, "unknown instruction discriminator");
    return RT_ERR_UNKNOWN;
}

#endif /* PYTHSOL_RT_H */
