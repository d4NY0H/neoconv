"""P-ROM half-swap detection and application (M68000 vector heuristics)."""

from __future__ import annotations

from .constants import P_SWAP_SIZE


def swap_p_banks(p_rom: bytes) -> bytes:
    """
    Swap the two 1 MB halves of a 2 MB P-ROM.

    Some Neo Geo titles (mostly early SNK releases with P-ROM banking) store
    their program data in a layout where the NeoSD/MiSTer expects the two
    megabytes in reversed order. For 2 MB P-ROMs, ``neoconv pack`` defaults to
    ``--swap-p auto`` (vector-table heuristic); use ``--swap-p yes`` / ``no`` to
    override. Applying a swap when it is not needed (or skipping it when needed)
    will break the game.

    Only valid for exactly 2 MB P-ROMs. Raises ValueError otherwise.
    """
    if len(p_rom) != P_SWAP_SIZE:
        raise ValueError(
            f"P-ROM bank swap requires exactly 2 MB (got {len(p_rom):,} bytes)."
        )
    half = P_SWAP_SIZE // 2
    return p_rom[half:] + p_rom[:half]


def _word_swap(data: bytes) -> bytes:
    """Swap every pair of adjacent bytes (MAME P-ROM byte-order correction)."""
    b = bytearray(data)
    for i in range(0, len(b) - 1, 2):
        b[i], b[i + 1] = b[i + 1], b[i]
    return bytes(b)


def _check_m68k_vectors(half: bytes) -> tuple[bool, int, int]:
    """
    Read the M68000 initial SP and Reset PC from the first 8 bytes of a
    P-ROM half (after word-swap from MAME storage format).

    Returns (valid, sp, reset_pc).  ``valid`` is True when both values
    fall within Neo Geo address ranges that make physical sense:

    - SP must be in Work RAM  : 0x100000 – 0x10FFFF
    - Reset PC must be in ROM : 0x000100 – 0x1FFFFF
      *or* in System ROM/BIOS : 0xC00000 – 0xC7FFFF
      (some games/hacks vector directly into the BIOS entry point)
    """
    if len(half) < 8:
        return False, 0, 0
    sw = _word_swap(half[:8])
    sp = int.from_bytes(sw[0:4], "big")
    rst = int.from_bytes(sw[4:8], "big")
    sp_ok = 0x100000 <= sp <= 0x10FFFF
    rst_ok = (0x000100 <= rst <= 0x1FFFFF) or (0xC00000 <= rst <= 0xC7FFFF)
    return (sp_ok and rst_ok), sp, rst


def detect_swap_p_needed(p_rom: bytes) -> tuple[bool, str]:
    """
    Heuristically detect whether a 2 MB P-ROM needs its two 1 MB halves
    swapped before packing into a .neo file.

    The detection works by inspecting the M68000 exception-vector table
    (initial Stack Pointer at offset 0, Reset PC at offset 4) in both
    the first and second 1 MB half.  Exactly one half should contain a
    plausible vector table; that determines whether a swap is required.

    Returns
    -------
    (swap_needed, reason_string)
        ``swap_needed`` is True when the second half carries the valid
        vector table (meaning the halves are currently in the wrong order).
        ``reason_string`` is a human-readable explanation for logging.

    Notes
    -----
    - Only meaningful for exactly 2 MB P-ROMs; returns (False, …) otherwise.
    - When *both* halves look valid the first half is preferred (no swap).
    - When *neither* half looks valid the function returns (False, …) and
      the caller should warn the user to check manually.
    - This heuristic covers all known Neo Geo titles that require ``--swap-p``
      (early SNK releases such as KOF94, NTM, and their hacks) but is not
      guaranteed to be correct for every future ROM set.
    """
    if len(p_rom) != P_SWAP_SIZE:
        return False, (
            f"P-ROM is {len(p_rom):,} bytes, not 2 MB — swap detection skipped."
        )

    half = P_SWAP_SIZE // 2
    v1_ok, sp1, rst1 = _check_m68k_vectors(p_rom[:half])
    v2_ok, sp2, rst2 = _check_m68k_vectors(p_rom[half:])

    if v1_ok and not v2_ok:
        return False, (
            f"First half has valid vectors (SP=0x{sp1:08X}, Reset=0x{rst1:08X}) — no swap needed."
        )
    if v2_ok and not v1_ok:
        return True, (
            f"Second half has valid vectors (SP=0x{sp2:08X}, Reset=0x{rst2:08X}) — swap required."
        )
    if v1_ok and v2_ok:
        return False, (
            f"Both halves appear valid; preferring first half (SP=0x{sp1:08X}, "
            f"Reset=0x{rst1:08X}) — no swap applied. Use --swap-p to override."
        )
    return False, (
        f"Neither half has a recognisable M68k vector table "
        f"(half1: SP=0x{sp1:08X}/Reset=0x{rst1:08X}, "
        f"half2: SP=0x{sp2:08X}/Reset=0x{rst2:08X}). "
        f"Swap detection inconclusive — check manually."
    )
