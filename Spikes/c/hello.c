/* Minimal Solana SBF program used as the Phase 1 toolchain spike.
 *
 * No libc, no standard headers — these are pure C:
 *  - `entrypoint(const unsigned char *input)` is what the SBF loader calls.
 *  - Returning 0 means the transaction succeeded (Solana status codes).
 *
 * `sol_log_` is a runtime syscall; `-z notext` lets lld leave it unresolved for
 * the loader to patch, so no libc runtime is needed.
 */

extern unsigned long sol_log_ (const unsigned char *msg, unsigned long len);

unsigned long
entrypoint (const unsigned char *input)
{
    unsigned char msg[] = "pythsol: hello from SBF!";
    (void) sol_log_ (msg, sizeof (msg) - 1);
    (void) input;
    return 0;
}
