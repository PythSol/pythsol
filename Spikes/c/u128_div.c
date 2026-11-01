/* Phase 4 spike #B: does the SBF target link __int128 division/multiplication
 * (__divti3/__multi3 from compiler-rt)? Also probes the overflow builtins on
 * __int128. Prints 'D1' when u128 and i128 div/mod/mul all evaluate. */

extern unsigned long sol_log_ (const unsigned char *msg, unsigned long len);

unsigned long
entrypoint (const unsigned char *input)
{
    char tag[2];
    /* exact division: 2^96 / 2^64 = 2^32 */
    unsigned __int128 big = (unsigned __int128)1 << 96;
    unsigned __int128 quo = big / ((unsigned __int128)1 << 64);
    if (quo == (unsigned __int128)((unsigned long)1 << 32)) {
        tag[0] = 'D'; tag[1] = '1';
    } else {
        tag[0] = 'D'; tag[1] = '0';
    }
    (void) sol_log_ ((const unsigned char *)tag, 2u);

    /* i128 mul overflow builtin */
    signed __int128 m = (signed __int128)1 << 70;
    signed __int128 prod;
    if (__builtin_mul_overflow(m, m, &prod)) {
        tag[0] = 'O'; tag[1] = '1';
    } else {
        tag[0] = 'O'; tag[1] = '0';
    }
    (void) sol_log_ ((const unsigned char *)tag, 2u);

    /* i128 div with negative operands */
    signed __int128 n = -300;
    signed __int128 d = 7;
    signed __int128 q = n / d;   /* trunc: -42 */
    signed __int128 r = n % d;   /* -6 */
    if (q == -42 && r == -6) {
        tag[0] = 'T'; tag[1] = '1';
    } else {
        tag[0] = 'T'; tag[1] = '0';
    }
    (void) sol_log_ ((const unsigned char *)tag, 2u);

    /* u128 shl via builtin? (not needed if shl==mul trick) */
    unsigned __int128 s = (unsigned __int128)3 << 64;
    if ((s >> 64) == 3) {
        tag[0] = 'S'; tag[1] = '1';
    } else {
        tag[0] = 'S'; tag[1] = '0';
    }
    (void) sol_log_ ((const unsigned char *)tag, 2u);
    return 0;
}
