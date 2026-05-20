"""Pack MAME inputs into ``.neo`` (P-ROM swap handling)."""

from __future__ import annotations

import warnings
from dataclasses import replace
from pathlib import Path

from .constants import P_SWAP_SIZE
from .mame_parse import parse_mame_dir, parse_mame_zip
from .models import NeoMeta, RomSet, SwapMode
from .neo_format import build_neo
from .swap_detect import detect_swap_p_needed, swap_p_banks


def apply_swap_p(romset: RomSet, swap_p: SwapMode, verbose: bool = True) -> RomSet:
    """
    Apply P-ROM bank swap according to *swap_p*.

    - :attr:`SwapMode.AUTO` : call :func:`detect_swap_p_needed` and swap only
                              when the heuristic says so; prints a diagnostic
                              line if *verbose*.
    - :attr:`SwapMode.YES`  : always swap.
    - :attr:`SwapMode.NO`   : never swap.

    Returns a new :class:`RomSet` with the swapped P-ROM; the original is
    never modified.

    Raises :class:`ValueError` with a clear message when :attr:`SwapMode.YES`
    is requested for a P-ROM that is not exactly 2 MB.
    """
    if swap_p is SwapMode.AUTO:
        needed, reason = detect_swap_p_needed(romset.p)
        inconclusive = "inconclusive" in reason.lower()
        if verbose:
            if inconclusive:
                print(f"  [WARN] auto-swap inconclusive — {reason}")
                print(
                    "         Try: neoconv detect-swap <input>  "
                    "or pack with --swap-p yes / no"
                )
            else:
                tag = "auto-swap: YES —" if needed else "auto-swap: no  —"
                print(f"  {tag} {reason}")
        if inconclusive:
            warnings.warn(
                f"P-ROM swap detection inconclusive: {reason}. "
                "Use neoconv detect-swap or set --swap-p yes/no.",
                UserWarning,
                stacklevel=2,
            )
        if needed:
            return replace(romset, p=swap_p_banks(romset.p))
    elif swap_p is SwapMode.YES:
        p_size = len(romset.p)
        if p_size != P_SWAP_SIZE:
            raise ValueError(
                f"--swap-p yes requires a 2 MB P-ROM, but this ROM is "
                f"{p_size:,} bytes ({p_size / 1024 / 1024:.2f} MB). "
                "P-ROM bank swap is only defined for exactly 2 MB P-ROMs. "
                "Use --swap-p auto or --swap-p no instead."
            )
        return replace(romset, p=swap_p_banks(romset.p))
    return romset


def mame_zip_to_neo(
    zip_path: Path,
    meta: NeoMeta,
    swap_p: SwapMode = SwapMode.NO,
    diagnostic: bool = False,
    swap_verbose: bool = True,
) -> bytes:
    """Convert a MAME ROM zip to a .neo binary.

    Parameters
    ----------
    swap_p
        :attr:`SwapMode.NO` (default), :attr:`SwapMode.YES`, or
        :attr:`SwapMode.AUTO` (heuristic via :func:`detect_swap_p_needed`).
        The CLI ``pack`` subcommand and GUI pass ``SwapMode.AUTO`` by default.
    swap_verbose
        If True (default), print auto-detect diagnostics for ``SwapMode.AUTO``.
    """
    romset = parse_mame_zip(zip_path, diagnostic=diagnostic)
    romset = apply_swap_p(romset, swap_p, verbose=swap_verbose)
    return build_neo(romset, meta)


def mame_dir_to_neo(
    dir_path: Path,
    meta: NeoMeta,
    swap_p: SwapMode = SwapMode.NO,
    diagnostic: bool = False,
    swap_verbose: bool = True,
) -> bytes:
    """Convert a directory of MAME ROM files to a .neo binary.

    Parameters
    ----------
    swap_p
        :attr:`SwapMode.NO` (default), :attr:`SwapMode.YES`, or
        :attr:`SwapMode.AUTO` (heuristic via :func:`detect_swap_p_needed`).
        The CLI ``pack`` subcommand and GUI pass ``SwapMode.AUTO`` by default.
    swap_verbose
        If True (default), print auto-detect diagnostics for ``SwapMode.AUTO``.
    """
    romset = parse_mame_dir(dir_path, diagnostic=diagnostic)
    romset = apply_swap_p(romset, swap_p, verbose=swap_verbose)
    return build_neo(romset, meta)
