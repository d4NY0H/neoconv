"""Pack MAME inputs into ``.neo`` (P-ROM swap handling)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .mame_parse import parse_mame_dir, parse_mame_zip
from .models import NeoMeta, RomSet
from .neo_format import build_neo
from .swap_detect import detect_swap_p_needed, swap_p_banks


def apply_swap_p(romset: RomSet, swap_p: bool | str, verbose: bool = True) -> RomSet:
    """
    Apply P-ROM bank swap according to *swap_p*:

    - ``True``   : always swap (legacy ``--swap-p`` flag)
    - ``False``  : never swap
    - ``"auto"`` : call :func:`detect_swap_p_needed` and swap only when the
                   heuristic says so; prints a short diagnostic line if *verbose*.

    Returns a new :class:`RomSet` with the swapped P-ROM; the original is
    never modified.
    """
    if swap_p == "auto":
        needed, reason = detect_swap_p_needed(romset.p)
        if verbose:
            tag = "auto-swap: YES —" if needed else "auto-swap: no  —"
            print(f"  {tag} {reason}")
        if needed:
            return replace(romset, p=swap_p_banks(romset.p))
    elif swap_p:
        return replace(romset, p=swap_p_banks(romset.p))
    return romset


def mame_zip_to_neo(
    zip_path: Path,
    meta: NeoMeta,
    swap_p: bool | str = False,
    diagnostic: bool = False,
    swap_verbose: bool = True,
) -> bytes:
    """Convert a MAME ROM zip to a .neo binary.

    Parameters
    ----------
    swap_p : False  → no swap (default)
             True   → always swap
             "auto" → heuristic detection via :func:`detect_swap_p_needed`
             The CLI ``pack`` subcommand and GUI use ``"auto"`` by default; pass
             ``swap_p="auto"`` here for the same behaviour.
    swap_verbose
        If True (default), print auto-detect diagnostics for ``swap_p="auto"``.
    """
    romset = parse_mame_zip(zip_path, diagnostic=diagnostic)
    romset = apply_swap_p(romset, swap_p, verbose=swap_verbose)
    return build_neo(romset, meta)


def mame_dir_to_neo(
    dir_path: Path,
    meta: NeoMeta,
    swap_p: bool | str = False,
    diagnostic: bool = False,
    swap_verbose: bool = True,
) -> bytes:
    """Convert a directory of MAME ROM files to a .neo binary.

    Parameters
    ----------
    swap_p : False  → no swap (default)
             True   → always swap
             "auto" → heuristic detection via :func:`detect_swap_p_needed`
             The CLI ``pack`` subcommand and GUI use ``"auto"`` by default; pass
             ``swap_p="auto"`` here for the same behaviour.
    swap_verbose
        If True (default), print auto-detect diagnostics for ``swap_p="auto"``.
    """
    romset = parse_mame_dir(dir_path, diagnostic=diagnostic)
    romset = apply_swap_p(romset, swap_p, verbose=swap_verbose)
    return build_neo(romset, meta)
