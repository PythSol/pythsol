"""Label program: fixed-width FixedString[8] (u32 length plus 8 reserved bytes)."""

from pythsol import FixedString, Init, Mut, Signer, account, instruction, u8, u64


@account
class Label:
    text: FixedString[8]
    nchars: u64
    bump: u8


@instruction
def initialize(authority: Signer, label: Init[Label], bump: u8) -> None:
    label.text = "hi"
    label.nchars = len(label.text)
    label.bump = bump


@instruction
def set_text(authority: Signer, label: Mut[Label], text: FixedString[8]) -> None:
    label.text = text
    label.nchars = len(label.text)


@instruction
def clear(authority: Signer, label: Mut[Label]) -> None:
    label.text = ""
    label.nchars = len(label.text)


@instruction
def stamp(authority: Signer, label: Mut[Label]) -> None:
    note: FixedString[8] = "ok"
    label.text = note
    label.nchars = len(note)


@instruction
def poke(authority: Signer, label: Mut[Label], index: u8, byte: u8) -> None:
    label.text[index] = byte


@instruction
def echo(authority: Signer, label: Mut[Label], index: u8) -> None:
    label.nchars = label.text[index]


@instruction
def choose(
    authority: Signer,
    label: Mut[Label],
    text: FixedString[8],
    use_arg: u8,
) -> None:
    picked: FixedString[8] = text if use_arg == 1 else label.text
    label.text = picked
    label.nchars = len(picked)
