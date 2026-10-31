/* Phase 3 spike: hex-dump the first 104 bytes of the entrypoint input in
 * 8-byte chunks so the PythSol zero-copy decoder can be verified against
 * what the VM actually sends. No libc, no static data; sol_log_ only. */

extern unsigned long sol_log_ (const unsigned char *msg, unsigned long len);

unsigned long
entrypoint (const unsigned char *input)
{
    char scratch[18];
    unsigned long i, k;
    for (i = 0; i < 104u; i += 8u)
    {
        for (k = 0; k < 8u; k++)
        {
            unsigned v = input[i + k];
            unsigned hi = v >> 4u;
            unsigned lo = v & 15u;
            scratch[2u * k] = (char)(hi < 10u ? (int)'0' + (int)hi
                                              : (int)'a' + (int)hi - 10);
            scratch[2u * k + 1u] = (char)(lo < 10u ? (int)'0' + (int)lo
                                                   : (int)'a' + (int)lo - 10);
        }
        scratch[16] = (char)0;
        (void) sol_log_ ((const unsigned char *)scratch, 16u);
    }
    (void) sol_log_ ((const unsigned char *)"done", 4u);
    return 0;
}
