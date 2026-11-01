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
 *   RT_ERR_ENUM      1011  unit-enum byte is not a declared variant
 *   RT_ERR_OPTION    1012  `.value` read while the option tag is clear
 *   RT_ERR_STRING    1013  FixedString length is past its reserved bytes
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

/* One slice for sol_log_data. The VM base64-encodes it as "Program data:". */
typedef struct SolBytes {
    const uint8_t *addr;
    uint64_t len;
} SolBytes;

extern void sol_log_data(SolBytes *fields, uint64_t fields_len);
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
#define RT_ERR_ENUM 1011u
#define RT_ERR_OPTION 1012u
#define RT_ERR_STRING 1013u
#define RT_ERR_CONSTRAINT 1014u

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

/* TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA */
static const uint8_t RT_TOKEN_ID[32] = {
    6u, 221u, 246u, 225u, 215u, 101u, 161u, 147u, 217u, 203u, 225u, 70u, 206u, 235u, 121u, 172u,
    28u, 180u, 133u, 237u, 95u, 91u, 55u, 145u, 58u, 140u, 245u, 133u, 126u, 255u, 0u, 169u
};

/* TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb */
static const uint8_t RT_TOKEN_2022_ID[32] = {
    6u, 221u, 246u, 225u, 238u, 117u, 143u, 222u, 24u, 66u, 93u, 188u, 228u, 108u, 205u, 218u,
    182u, 26u, 252u, 77u, 131u, 185u, 13u, 39u, 254u, 189u, 249u, 40u, 216u, 161u, 139u, 252u
};

/* ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL */
static const uint8_t RT_ATA_ID[32] = {
    140u, 151u, 37u, 143u, 78u, 36u, 137u, 241u, 187u, 61u, 16u, 41u, 20u, 142u, 13u, 131u,
    11u, 90u, 19u, 153u, 218u, 255u, 16u, 132u, 4u, 142u, 123u, 216u, 219u, 233u, 248u, 89u
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
    /* lld encodes an rodata function pointer as an lddw immediate and
     * writes the high 32 bits at fn+12, which is past this 16-byte
     * prefix. `spill` absorbs that write so it cannot zero the next
     * discriminator or the program id that follows the table. The
     * loader rewrites `fn` from .rel.dyn before the program runs. */
    uint64_t spill;
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

/* Log an event: 8-byte discriminator then the packed payload, one slice. */
static inline void rt_log_event(const uint8_t *data, uint64_t len) {
    SolBytes field;
    field.addr = data;
    field.len = len;
    sol_log_data(&field, 1u);
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

/* 128-bit limbs ------------------------------------------------------------
 * C's char literals for __int128 need two u64 limbs; RT_U128_VAL(hi, lo)
 * composes them. Little-endian field storage is byte-wise like above.
 */
typedef unsigned __int128 RtU128;
typedef signed __int128 RtI128;
#define RT_U128_VAL(hi, lo) ((((RtU128)(hi)) << 64) | ((RtU128)(lo)))

static inline uint64_t rt_ld_u128(const uint8_t *d, uint64_t off, RtU128 *out) {
    RtU128 v = 0;
    uint64_t i;
    for (i = 0u; i < 16u; i++) {
        v |= ((RtU128)d[off + i]) << (8u * i);
    }
    *out = v;
    return RT_OK;
}

static inline void rt_st_u128(uint8_t *d, uint64_t off, RtU128 v) {
    uint64_t i;
    for (i = 0u; i < 16u; i++) {
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
/* Checked arithmetic (compiler builtins; no libc).                     */
/*                                                                     */
/* Contract (mirrors pythsol.refrt exactly — see ADR-0011):            */
/*   * every helper returns RT_OK (0) on success, otherwise the RT_ERR_* */
/*     code the caller must abort with — div-zero (1010) and overflow   */
/*     (1009) are *different values*, the emitter logs the actual code; */
/*   * division is FLOOR division for both signednesses: for signed     */
/*     types, C's `/` is truncating, so the quotient is corrected by    */
/*     one when the remainder's sign disagrees with the divisor's;      */
/*   * `min / -1` and `min % -1` abort with RT_ERR_OVERFLOW for signed; */
/*   * shifts abort with RT_ERR_DIV_ZERO when the count is negative or  */
/*     >= the width's bit count; left shifts additionally abort with    */
/*     RT_ERR_OVERFLOW when the (arithmetically-sign-extended) product  */
/*     leaves the type's range.                                         */
/* ------------------------------------------------------------------ */

#define RT_CHK3(OP, T, STYLE)                                              \
    static inline uint64_t rt_checked_##OP##_##STYLE(T a, T b, T *out) {   \
        return __builtin_##OP##_overflow(a, b, out) ? RT_ERR_OVERFLOW      \
                                                    : RT_OK;               \
    }

RT_CHK3(add, uint8_t, u8)
RT_CHK3(add, uint16_t, u16)
RT_CHK3(add, uint32_t, u32)
RT_CHK3(add, uint64_t, u64)
RT_CHK3(add, RtU128, u128)
RT_CHK3(add, int8_t, i8)
RT_CHK3(add, int16_t, i16)
RT_CHK3(add, int32_t, i32)
RT_CHK3(add, int64_t, i64)
RT_CHK3(add, RtI128, i128)

RT_CHK3(sub, uint8_t, u8)
RT_CHK3(sub, uint16_t, u16)
RT_CHK3(sub, uint32_t, u32)
RT_CHK3(sub, uint64_t, u64)
RT_CHK3(sub, RtU128, u128)
RT_CHK3(sub, int8_t, i8)
RT_CHK3(sub, int16_t, i16)
RT_CHK3(sub, int32_t, i32)
RT_CHK3(sub, int64_t, i64)
RT_CHK3(sub, RtI128, i128)

RT_CHK3(mul, uint8_t, u8)
RT_CHK3(mul, uint16_t, u16)
RT_CHK3(mul, uint32_t, u32)
RT_CHK3(mul, uint64_t, u64)
RT_CHK3(mul, RtU128, u128)
RT_CHK3(mul, int8_t, i8)
RT_CHK3(mul, int16_t, i16)
RT_CHK3(mul, int32_t, i32)
RT_CHK3(mul, int64_t, i64)
RT_CHK3(mul, RtI128, i128)

/* floor-div/mod helpers ---------------------------------------------------- */

/* i64 / i128 done natively (no wider signed type exists). */
static inline uint64_t rt_checked_div_i64(int64_t a, int64_t b, int64_t *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == (int64_t)(-9223372036854775807ll - 1) && b == -1) {
        return RT_ERR_OVERFLOW;
    }
    int64_t q = a / b;
    int64_t r = a % b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        q -= 1; /* floor, not C truncation */
    }
    *out = q;
    return RT_OK;
}

static inline uint64_t rt_checked_mod_i64(int64_t a, int64_t b, int64_t *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == (int64_t)(-9223372036854775807ll - 1) && b == -1) {
        return RT_ERR_OVERFLOW; /* min % -1 is the same overflow class */
    }
    int64_t q = a / b;
    int64_t r = a % b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        r += b; /* convert remainder to the floor system */
        q -= 1;
    }
    *out = r;
    return RT_OK;
}

static inline uint64_t rt_checked_div_i128(RtI128 a, RtI128 b, RtI128 *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == (RtI128)1 << 127 && b == -1) {
        return RT_ERR_OVERFLOW;
    }
    RtI128 q = a / b;
    RtI128 r = a % b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        q -= 1;
    }
    *out = q;
    return RT_OK;
}

static inline uint64_t rt_checked_mod_i128(RtI128 a, RtI128 b, RtI128 *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == (RtI128)1 << 127 && b == -1) {
        return RT_ERR_OVERFLOW;
    }
    RtI128 q = a / b;
    RtI128 r = a % b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        r += b;
        q -= 1;
    }
    *out = r;
    return RT_OK;
}

/* Small signed widths: compute in int64_t width to dodge promotion UB. */

static inline uint64_t rt_checked_div_i8(int8_t a, int8_t b, int8_t *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == -128 && b == -1) {
        return RT_ERR_OVERFLOW;
    }
    int64_t q = (int64_t)a / (int64_t)b;
    int64_t r = (int64_t)a % (int64_t)b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        q -= 1;
    }
    *out = (int8_t)q;
    return RT_OK;
}

static inline uint64_t rt_checked_mod_i8(int8_t a, int8_t b, int8_t *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == -128 && b == -1) {
        return RT_ERR_OVERFLOW;
    }
    int64_t q = (int64_t)a / (int64_t)b;
    int64_t r = (int64_t)a % (int64_t)b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        r += (int64_t)b;
        q -= 1;
    }
    *out = (int8_t)r;
    return RT_OK;
}

static inline uint64_t rt_checked_div_i16(int16_t a, int16_t b, int16_t *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == -32768 && b == -1) {
        return RT_ERR_OVERFLOW;
    }
    int64_t q = (int64_t)a / (int64_t)b;
    int64_t r = (int64_t)a % (int64_t)b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        q -= 1;
    }
    *out = (int16_t)q;
    return RT_OK;
}

static inline uint64_t rt_checked_mod_i16(int16_t a, int16_t b, int16_t *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == -32768 && b == -1) {
        return RT_ERR_OVERFLOW;
    }
    int64_t q = (int64_t)a / (int64_t)b;
    int64_t r = (int64_t)a % (int64_t)b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        r += (int64_t)b;
        q -= 1;
    }
    *out = (int16_t)r;
    return RT_OK;
}

static inline uint64_t rt_checked_div_i32(int32_t a, int32_t b, int32_t *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == (-2147483647 - 1) && b == -1) {
        return RT_ERR_OVERFLOW;
    }
    int64_t q = (int64_t)a / (int64_t)b;
    int64_t r = (int64_t)a % (int64_t)b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        q -= 1;
    }
    *out = (int32_t)q;
    return RT_OK;
}

static inline uint64_t rt_checked_mod_i32(int32_t a, int32_t b, int32_t *out) {
    if (b == 0) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == (-2147483647 - 1) && b == -1) {
        return RT_ERR_OVERFLOW;
    }
    int64_t q = (int64_t)a / (int64_t)b;
    int64_t r = (int64_t)a % (int64_t)b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        r += (int64_t)b;
        q -= 1;
    }
    *out = (int32_t)r;
    return RT_OK;
}

/* unsigned div/mod: floor == trunc; only the zero divisor aborts. */
#define RT_CHK_DIVMOD_UNSIGNED(STYLE, T)                                   \
    static inline uint64_t rt_checked_div_##STYLE(T a, T b, T *out) {      \
        if (b == (T)0) {                                                   \
            return RT_ERR_DIV_ZERO;                                        \
        }                                                                  \
        *out = (T)(a / b);                                                 \
        return RT_OK;                                                      \
    }                                                                      \
    static inline uint64_t rt_checked_mod_##STYLE(T a, T b, T *out) {      \
        if (b == (T)0) {                                                   \
            return RT_ERR_DIV_ZERO;                                        \
        }                                                                  \
        *out = (T)(a % b);                                                 \
        return RT_OK;                                                      \
    }

RT_CHK_DIVMOD_UNSIGNED(u8, uint8_t)
RT_CHK_DIVMOD_UNSIGNED(u16, uint16_t)
RT_CHK_DIVMOD_UNSIGNED(u32, uint32_t)
RT_CHK_DIVMOD_UNSIGNED(u64, uint64_t)
RT_CHK_DIVMOD_UNSIGNED(u128, RtU128)

/* shifts -------------------------------------------------------------------
 * Mirrors refrt exactly: RT_ERR_DIV_ZERO when s < 0 or s >= bits, then
 * RT_ERR_OVERFLOW when the *mathematical* product a·2^s leaves the type's
 * bounds (a plain multiply trick would wrongly accept wrapped products,
 * e.g. i8 1 << 7 or i64 1 << 63, so result ranges are checked first).
 * Narrow types compute in 64-bit; u64/i64 in 128-bit; u128/i128 use bound
 * comparisons and raw-bit shifts (no signed-shift UB on the result path).
 */

#define RT_CHK_SHL_U(STYLE, T)                                             \
    static inline uint64_t rt_checked_shl_##STYLE(T a, T s, T *out) {      \
        if (s >= (T)(sizeof(T) * 8)) {                                     \
            return RT_ERR_DIV_ZERO;                                        \
        }                                                                  \
        uint64_t wide = ((uint64_t)a) << s;                                \
        if (wide > (uint64_t)((T)-1)) {                      \
            return RT_ERR_OVERFLOW;                                        \
        }                                                                  \
        *out = (T)wide;                                                    \
        return RT_OK;                                                      \
    }

RT_CHK_SHL_U(u8, uint8_t)
RT_CHK_SHL_U(u16, uint16_t)
RT_CHK_SHL_U(u32, uint32_t)

static inline uint64_t rt_checked_shl_u64(uint64_t a, uint64_t s, uint64_t *out) {
    if (s >= 64u) {
        return RT_ERR_DIV_ZERO;
    }
    RtU128 wide = ((RtU128)a) << s;
    if (wide > (RtU128)UINT64_MAX) {
        return RT_ERR_OVERFLOW;
    }
    *out = (uint64_t)wide;
    return RT_OK;
}

static inline uint64_t rt_checked_shl_u128(RtU128 a, RtU128 s, RtU128 *out) {
    if (s >= 128) {
        return RT_ERR_DIV_ZERO;
    }
    if (a > ((RtU128)0 - (RtU128)1) >> s) {
        return RT_ERR_OVERFLOW;
    }
    *out = a << s; /* unsigned: well-defined modulo 2^128 */
    return RT_OK;
}

#define RT_CHK_SHL_I(STYLE, T, MINVCONST, MAXVCONST)                       \
    static inline uint64_t rt_checked_shl_##STYLE(T a, T s, T *out) {      \
        if (s >= (T)(sizeof(T) * 8)) {                                     \
            return RT_ERR_DIV_ZERO;                                        \
        }                                                                  \
        int64_t wide = (int64_t)a;                                         \
        int64_t lo = (int64_t)((MINVCONST) >> s);                           \
        int64_t hi = (int64_t)((MAXVCONST) >> s);                           \
        if (wide < lo || wide > hi) {                                      \
            return RT_ERR_OVERFLOW;                                        \
        }                                                                  \
        wide = wide << s; /* value proven in-range */                      \
        *out = (T)wide;                                                    \
        return RT_OK;                                                      \
    }

RT_CHK_SHL_I(i8, int8_t, (-128), 127)
RT_CHK_SHL_I(i16, int16_t, (-32768), 32767)
RT_CHK_SHL_I(i32, int32_t, (-2147483647 - 1), 2147483647)

static inline uint64_t rt_checked_shl_i64(int64_t a, int64_t s, int64_t *out) {
    if (s >= 64) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == 0) {
        *out = 0;
        return RT_OK;
    }
    /* Bound comparisons in the wide i128 domain; lo via an arithmetic
     * shift of INT64_MIN inside i128 (exact, no implementation-defined
     * narrow-type traps), then the product in i128 as well. */
    RtI128 lo = ((RtI128)(-9223372036854775807LL - 1)) >> s;
    RtI128 hi = (RtI128)(9223372036854775807LL) >> s;
    if ((RtI128)a < lo || (RtI128)a > hi) {
        return RT_ERR_OVERFLOW;
    }
    RtI128 two_s = (RtI128)1 << s; /* s < 64 fits i128 as a positive value */
    *out = (int64_t)((RtI128)a * two_s);
    return RT_OK;
}

static inline uint64_t rt_checked_shl_i128(RtI128 a, RtI128 s, RtI128 *out) {
    if (s >= 128) {
        return RT_ERR_DIV_ZERO;
    }
    if (a == 0) {
        *out = 0;
        return RT_OK;
    }
    if (s == 127) {
        /* 2^127 has no positive i128 value: only a == -1 fits (result MIN). */
        if (a == -1) {
            *out = (RtI128)((RtU128)1 << 127);
            return RT_OK;
        }
        return RT_ERR_OVERFLOW;
    }
    if (a > 0) {
        RtI128 max_v = (RtI128)(((RtU128)0 - (RtU128)1) >> 1);
        if (a > (max_v >> s)) {
            return RT_ERR_OVERFLOW;
        }
    } else {
        RtI128 min_v = (RtI128)((RtU128)1 << 127);
        if (a < (min_v >> s)) {
            return RT_ERR_OVERFLOW;
        }
    }
    RtI128 two_s = (RtI128)((RtU128)1 << s);
    *out = (RtI128)(a * two_s); /* product proven in-range */
    return RT_OK;
}

#define RT_CHK_SHR(STYLE, T)                                               \
    static inline uint64_t rt_checked_shr_##STYLE(T a, T s, T *out) {      \
        if (s < 0 || s >= (T)(sizeof(T) * 8)) {                            \
            return RT_ERR_DIV_ZERO;                                        \
        }                                                                  \
        *out = (T)(a >> s); /* arithmetic for signed, logical for unsigned */ \
        return RT_OK;                                                      \
    }

RT_CHK_SHR(u8, uint8_t)
RT_CHK_SHR(u16, uint16_t)
RT_CHK_SHR(u32, uint32_t)
RT_CHK_SHR(u64, uint64_t)
RT_CHK_SHR(u128, RtU128)
RT_CHK_SHR(i8, int8_t)
RT_CHK_SHR(i16, int16_t)
RT_CHK_SHR(i32, int32_t)
RT_CHK_SHR(i64, int64_t)
RT_CHK_SHR(i128, RtI128)

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

/* System Transfer (tag 2): u32 tag | u64 lamports. ``from`` signs the outer
 * transaction; ``to`` is writable and does not sign this CPI. The System
 * program must already be in the caller's account list. */
static inline uint64_t rt_system_transfer(RtCtx *rt, RtAccount *from, RtAccount *to,
                                          uint64_t lamports) {
    uint8_t payload[12];
    SolAccountMeta metas[2];
    SolAccountInfo infos[2];
    SolInstruction ix;
    uint64_t i;
    uint8_t saw = 0u;
    for (i = 0u; i < rt->n_accounts; i++) {
        if (rt_key_eq(rt->accounts[i].key, (const SolPubkey *)(const void *)RT_SYSTEM_ID)) {
            saw = 1u;
        }
    }
    if (!saw) {
        return RT_ERR_CPI;
    }
    rt_st_u32(payload, 0u, 2u);
    rt_st_u64(payload, 4u, lamports);
    metas[0].pubkey = from->key;
    metas[0].is_writable = 1u;
    metas[0].is_signer = 1u;
    metas[1].pubkey = to->key;
    metas[1].is_writable = 1u;
    metas[1].is_signer = 0u;
    infos[0].key = from->key;
    infos[0].lamports = from->lamports;
    infos[0].data_len = from->data_len;
    infos[0].data = from->data;
    infos[0].owner = from->owner;
    infos[0].rent_epoch = 0u;
    infos[0].is_signer = from->is_signer;
    infos[0].is_writable = from->is_writable;
    infos[0].executable = from->executable;
    infos[1].key = to->key;
    infos[1].lamports = to->lamports;
    infos[1].data_len = to->data_len;
    infos[1].data = to->data;
    infos[1].owner = to->owner;
    infos[1].rent_epoch = 0u;
    infos[1].is_signer = to->is_signer;
    infos[1].is_writable = to->is_writable;
    infos[1].executable = to->executable;
    ix.program_id = (SolPubkey *)(const void *)RT_SYSTEM_ID;
    ix.accounts = &metas[0];
    ix.accounts_len = 2u;
    ix.data = &payload[0];
    ix.data_len = 12u;
    return sol_invoke_signed_c(&ix, &infos[0], 2u, (const SolSignerSeeds *)0, 0u);
}

/* Move lamports off an account this program owns. The System program rejects
 * Transfer when `from` carries data, which every PythSol account does. */
static inline uint64_t rt_move_lamports(RtCtx *rt, RtAccount *from, RtAccount *to,
                                        uint64_t lamports) {
    if (!from->is_writable || !to->is_writable) {
        return RT_ERR_WRITABLE;
    }
    if (!rt_key_eq(from->owner, (const SolPubkey *)(const void *)rt->program_id)) {
        return RT_ERR_OWNER;
    }
    if (*from->lamports < lamports || *to->lamports > ~0ull - lamports) {
        return RT_ERR_OVERFLOW;
    }
    *from->lamports -= lamports;
    *to->lamports += lamports;
    return 0u;
}

static inline uint8_t rt_has_program(const RtCtx *rt, const uint8_t *program) {
    uint64_t i;
    for (i = 0u; i < rt->n_accounts; i++) {
        if (rt_key_eq(rt->accounts[i].key, (const SolPubkey *)(const void *)program)) {
            return 1u;
        }
    }
    return 0u;
}

static inline void rt_fill_info(SolAccountInfo *info, RtAccount *acct) {
    info->key = acct->key;
    info->lamports = acct->lamports;
    info->data_len = acct->data_len;
    info->data = acct->data;
    info->owner = acct->owner;
    info->rent_epoch = 0u;
    info->is_signer = acct->is_signer;
    info->is_writable = acct->is_writable;
    info->executable = acct->executable;
}

/* SPL Token / Token-2022 Transfer: one tag byte (3) then a u64 amount.
 * Accounts: source writable, destination writable, authority signer. */
static inline uint64_t rt_token_transfer(RtCtx *rt, const uint8_t *program,
                                         RtAccount *src, RtAccount *dst,
                                         RtAccount *authority, uint64_t amount) {
    uint8_t payload[9];
    SolAccountMeta metas[3];
    SolAccountInfo infos[3];
    SolInstruction ix;
    if (!rt_has_program(rt, program)) {
        return RT_ERR_CPI;
    }
    payload[0] = 3u;
    rt_st_u64(payload, 1u, amount);
    metas[0].pubkey = src->key;
    metas[0].is_writable = 1u;
    metas[0].is_signer = 0u;
    metas[1].pubkey = dst->key;
    metas[1].is_writable = 1u;
    metas[1].is_signer = 0u;
    metas[2].pubkey = authority->key;
    metas[2].is_writable = 0u;
    metas[2].is_signer = 1u;
    rt_fill_info(&infos[0], src);
    rt_fill_info(&infos[1], dst);
    rt_fill_info(&infos[2], authority);
    ix.program_id = (SolPubkey *)(const void *)program;
    ix.accounts = &metas[0];
    ix.accounts_len = 3u;
    ix.data = &payload[0];
    ix.data_len = 9u;
    return sol_invoke_signed_c(&ix, &infos[0], 3u, (const SolSignerSeeds *)0, 0u);
}

/* Associated Token Account CreateIdempotent (data byte 1).
 * Accounts: payer, ata, owner, mint, system program, token program. */
static inline uint64_t rt_ata_create(RtCtx *rt, RtAccount *payer, RtAccount *ata,
                                     RtAccount *owner, RtAccount *mint,
                                     const uint8_t *token_program) {
    uint8_t payload[1];
    SolAccountMeta metas[6];
    SolAccountInfo infos[6];
    SolInstruction ix;
    RtAccount *system;
    RtAccount *token;
    if (!rt_has_program(rt, RT_ATA_ID) || !rt_has_program(rt, RT_SYSTEM_ID) ||
        !rt_has_program(rt, token_program)) {
        return RT_ERR_CPI;
    }
    system = 0;
    token = 0;
    {
        uint64_t i;
        for (i = 0u; i < rt->n_accounts; i++) {
            if (rt_key_eq(rt->accounts[i].key, (const SolPubkey *)(const void *)RT_SYSTEM_ID)) {
                system = &rt->accounts[i];
            }
            if (rt_key_eq(rt->accounts[i].key, (const SolPubkey *)(const void *)token_program)) {
                token = &rt->accounts[i];
            }
        }
    }
    if (system == 0 || token == 0) {
        return RT_ERR_CPI;
    }
    payload[0] = 1u;
    metas[0].pubkey = payer->key;
    metas[0].is_writable = 1u;
    metas[0].is_signer = 1u;
    metas[1].pubkey = ata->key;
    metas[1].is_writable = 1u;
    metas[1].is_signer = 0u;
    metas[2].pubkey = owner->key;
    metas[2].is_writable = 0u;
    metas[2].is_signer = 0u;
    metas[3].pubkey = mint->key;
    metas[3].is_writable = 0u;
    metas[3].is_signer = 0u;
    metas[4].pubkey = system->key;
    metas[4].is_writable = 0u;
    metas[4].is_signer = 0u;
    metas[5].pubkey = token->key;
    metas[5].is_writable = 0u;
    metas[5].is_signer = 0u;
    rt_fill_info(&infos[0], payer);
    rt_fill_info(&infos[1], ata);
    rt_fill_info(&infos[2], owner);
    rt_fill_info(&infos[3], mint);
    rt_fill_info(&infos[4], system);
    rt_fill_info(&infos[5], token);
    ix.program_id = (SolPubkey *)(const void *)RT_ATA_ID;
    ix.accounts = &metas[0];
    ix.accounts_len = 6u;
    ix.data = &payload[0];
    ix.data_len = 1u;
    return sol_invoke_signed_c(&ix, &infos[0], 6u, (const SolSignerSeeds *)0, 0u);
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
