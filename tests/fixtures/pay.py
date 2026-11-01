"""Pay: move lamports with a System-program transfer."""

from pythsol import Signer, instruction, system_transfer, u64


@instruction
def pay(payer: Signer, dest: Signer, amount: u64) -> None:
    system_transfer(payer, dest, amount)
