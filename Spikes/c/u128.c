/* Phase 4 spike #A: does SBF clang support 128-bit integers (u128)?
 * Verifies exact 2^65-2 via hi/lo limb compares + i128 shift semantics.
 * No libc; sol_log_ only. */

extern unsigned long sol_log_ (const unsigned char *msg, unsigned long len);

unsigned long
entrypoint (const unsigned char *input)
{
    char tag[2];
    unsigned __int128 a = (unsigned __int128)0xffffffffffffffffULL;
    unsigned __int128 b = a + a;           /* expect: hi=1, lo=2^64-2 */
    unsigned long long hi = (unsigned long long)(b >> 64);
    unsigned long long lo = (unsigned long long)(b & 0xffffffffffffffffULL);
    if (hi == 1ULL && lo == 0xfffffffffffffffeULL) {
        tag[0] = 'W'; tag[1] = '1';
    } else {
        tag[0] = 'W'; tag[1] = '0';
    }
    (void) sol_log_ ((const unsigned char *)tag, 2u);

    /* i128: -1 arithmetic shift keeps the sign; -2 * max int wraps sanely */
    signed __int128 n = (signed __int128)-1;
    signed __int128 m = n * 3;             /* -3 */
    if ((n >> 64) == (signed __int128)-1 && m < 0) {
        tag[0] = 'I'; tag[1] = '1';
    } else {
        tag[0] = 'I'; tag[1] = '0';
    }
    (void) sol_log_ ((const unsigned char *)tag, 2u);

    /* u128 -> u64 cast truncation */
    unsigned __int128 big = ((unsigned __int128)1 << 70) + 7UL;
    unsigned long long cut = (unsigned long long)big;
    if (cut == 7ULL) {
        tag[0] = 'C'; tag[1] = '1';
    } else {
        tag[0] = 'C'; tag[1] = '0';
    }
    (void) sol_log_ ((const unsigned char *)tag, 2u);
    return 0;
}
