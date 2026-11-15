"""Pack MAME inputs into ``.neo`` (P-ROM swap handling)."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from .constants import P_SWAP_SIZE
from .exceptions import InvalidConfigurationError
from .mame_parse import parse_mame_dir, parse_mame_zip
from .models import NeoMeta, RomSet, SwapMode
from .neo_format import build_neo
from .swap_detect import detect_swap_p_needed, swap_p_banks


def apply_swap_p(
    romset: RomSet,
    swap_p: SwapMode,
    verbose: bool = True,
    log: Callable[[str], None] | None = None,
) -> RomSet:
    """
    Apply P-ROM bank swap according to *swap_p*.

    - :attr:`SwapMode.AUTO` : call :func:`detect_swap_p_needed` and swap only
                              when the heuristic says so; prints a diagnostic
                              line if *verbose*.
    - :attr:`SwapMode.YES`  : always swap.
    - :attr:`SwapMode.NO`   : never swap.

    Returns a new :class:`RomSet` with the swapped P-ROM; the original is
    never modified.

    Raises :class:`InvalidConfigurationError` when :attr:`SwapMode.YES` is
    requested for a P-ROM that is not exactly 2 MB.
    """
    if swap_p is SwapMode.AUTO:
        needed, reason = detect_swap_p_needed(romset.p)
        inconclusive = "inconclusive" in reason.lower()
        if verbose or log is not None:
            emit = log if log is not None else print
            if inconclusive:
                emit(f"  [WARN] auto-swap inconclusive — {reason}")
                emit(
                    "         Try: neoconv detect-swap <input>  "
                    "or pack with --swap-p yes / no"
                )
            else:
                tag = "auto-swap: YES —" if needed else "auto-swap: no  —"
                emit(f"  {tag} {reason}")
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
            raise InvalidConfigurationError(
                f"--swap-p yes requires a 2 MB P-ROM, but this ROM is "
                f"{p_size:,} bytes ({p_size / 1024 / 1024:.2f} MB). "
                "P-ROM bank swap is only defined for exactly 2 MB P-ROMs. "
                "Use --swap-p auto or --swap-p no instead.",
                hint="Run neoconv detect-swap on the MAME set.",
            )
        return replace(romset, p=swap_p_banks(romset.p))
    return romset


def _apply_v2_size(romset: RomSet, v2_size: int | None) -> RomSet:
    """
    Record an explicit V1/V2 split on *romset* for ``.neo`` header writing.

    ``v2_size=None`` keeps the RomSet unchanged (legacy layout: all V in V1).
    Automatic ADPCM-B classification needs the deferred layout/softlist work,
    so the split is passed explicitly by the caller.
    """
    if v2_size is None:
        return romset
    if v2_size < 0:
        raise InvalidConfigurationError(
            f"--v2-size must not be negative (got {v2_size:,}).",
            hint="Use 0 for a single ADPCM-A bank, or the ADPCM-B byte count.",
        )
    if v2_size > len(romset.v):
        raise InvalidConfigurationError(
            f"--v2-size ({v2_size:,} bytes) exceeds the total V ROM size "
            f"({len(romset.v):,} bytes).",
            hint="The V1 and V2 sizes must add up to the total V data length.",
        )
    return replace(
        romset,
        v1_size=len(romset.v) - v2_size,
        v2_size=v2_size,
    )


def mame_zip_to_neo(
    zip_path: Path,
    meta: NeoMeta,
    swap_p: SwapMode = SwapMode.NO,
    diagnostic: bool = False,
    swap_verbose: bool = True,
    v2_size: int | None = None,
    *,
    allow_extra_files: bool = False,
    allow_synthetic_s: bool = False,
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
    v2_size
        Optional ADPCM-B (V2) byte count for the ``.neo`` header. When ``None``
        all V data is written to V1 (legacy layout). Must not exceed total V.
    allow_extra_files
        If True, unrecognized input files are ignored with a warning instead
        of raising :class:`InvalidRomLayoutError`.
    allow_synthetic_s
        If True, a missing s1 ROM may be replaced with a zero-filled
        placeholder. The result is not hardware-playable.
    """
    romset = parse_mame_zip(
        zip_path,
        diagnostic=diagnostic,
        allow_extra_files=allow_extra_files,
        allow_synthetic_s=allow_synthetic_s,
    )
    romset = apply_swap_p(romset, swap_p, verbose=swap_verbose)
    romset = _apply_v2_size(romset, v2_size)
    return build_neo(romset, meta)


def mame_dir_to_neo(
    dir_path: Path,
    meta: NeoMeta,
    swap_p: SwapMode = SwapMode.NO,
    diagnostic: bool = False,
    swap_verbose: bool = True,
    v2_size: int | None = None,
    *,
    allow_extra_files: bool = False,
    allow_synthetic_s: bool = False,
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
    v2_size
        Optional ADPCM-B (V2) byte count for the ``.neo`` header. When ``None``
        all V data is written to V1 (legacy layout). Must not exceed total V.
    allow_extra_files
        If True, unrecognized input files are ignored with a warning instead
        of raising :class:`InvalidRomLayoutError`.
    allow_synthetic_s
        If True, a missing s1 ROM may be replaced with a zero-filled
        placeholder. The result is not hardware-playable.
    """
    romset = parse_mame_dir(
        dir_path,
        diagnostic=diagnostic,
        allow_extra_files=allow_extra_files,
        allow_synthetic_s=allow_synthetic_s,
    )
    romset = apply_swap_p(romset, swap_p, verbose=swap_verbose)
    romset = _apply_v2_size(romset, v2_size)
    return build_neo(romset, meta)
