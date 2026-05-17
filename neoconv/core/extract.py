"""Extract :class:`RomSet` / ``.neo`` bytes into MAME or Darksoft file layouts."""

from __future__ import annotations

import io
import warnings
import zipfile
from pathlib import Path

from .constants import C_CHIP_SIZE_DEFAULT, V_BANK_SIZE
from .models import RomSet
from .neo_format import parse_neo


def _warn_v_bank_size_remainder(romset: RomSet, v_bank_size: int) -> None:
    v_len = len(romset.v)
    if v_len > 0 and v_len % v_bank_size != 0:
        warnings.warn(
            f"V ROM size ({v_len:,} bytes) is not a multiple of "
            f"v_bank_size ({v_bank_size:,} bytes); the last vN file will be "
            f"smaller. Try a different --v-bank-size if chip boundaries look wrong.",
            UserWarning,
            stacklevel=3,
        )


def extract_romset(
    romset: RomSet,
    output_dir: Path,
    name_prefix: str = "game",
    fmt: str = "mame",
    c_chip_size: int = C_CHIP_SIZE_DEFAULT,
    v_bank_size: int = V_BANK_SIZE,
) -> dict[str, Path]:
    """
    Extract a parsed RomSet into individual ROM files.

    Parameters
    ----------
    romset       : parsed ROM regions
    output_dir   : destination directory
    name_prefix  : filename prefix (e.g. 'turfmast' -> turfmast-p1.bin)
    fmt          : 'mame' -> .bin extension, 'darksoft' -> .rom extension
    c_chip_size  : size of each C chip in bytes (default 2 MB).
                   Use 4 MB for games with larger C chips (e.g. Neo Turf Masters).
    v_bank_size  : size of each V chunk in bytes (default 2 MB).

    Returns dict mapping role -> output Path.
    """
    _warn_v_bank_size_remainder(romset, v_bank_size)
    ext = ".bin" if fmt == "mame" else ".rom"
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _write_rom(role: str, data: bytes, suffix: str = "") -> Path:
        fname = f"{name_prefix}-{role}{suffix}{ext}"
        p = output_dir / fname
        p.write_bytes(data)
        written[role + suffix] = p
        return p

    _write_rom("p1", romset.p)
    _write_rom("s1", romset.s)
    _write_rom("m1", romset.m)

    for i, chunk in enumerate(romset.v_chunks(bank_size=v_bank_size), start=1):
        _write_rom("v", chunk, suffix=str(i))

    for i, chip in enumerate(romset.c_chips(chip_size=c_chip_size), start=1):
        _write_rom("c", chip, suffix=str(i))

    return written


def extract_neo(
    neo_data: bytes,
    output_dir: Path,
    name_prefix: str = "game",
    fmt: str = "mame",
    c_chip_size: int = C_CHIP_SIZE_DEFAULT,
    v_bank_size: int = V_BANK_SIZE,
) -> dict[str, Path]:
    """
    Extract a .neo file into individual ROM files.

    Parameters
    ----------
    neo_data     : raw bytes of the .neo file
    output_dir   : destination directory
    name_prefix  : filename prefix (e.g. 'turfmast' -> turfmast-p1.bin)
    fmt          : 'mame' -> .bin extension, 'darksoft' -> .rom extension
    c_chip_size  : size of each C chip in bytes (default 2 MB).
                   Use 4 MB for games with larger C chips (e.g. Neo Turf Masters).
    v_bank_size  : size of each V chunk in bytes (default 2 MB).

    Returns dict mapping role -> output Path.
    """
    romset = parse_neo(neo_data)
    return extract_romset(
        romset,
        output_dir,
        name_prefix=name_prefix,
        fmt=fmt,
        c_chip_size=c_chip_size,
        v_bank_size=v_bank_size,
    )


def extract_romset_to_zip(
    romset: RomSet,
    name_prefix: str = "game",
    fmt: str = "mame",
    c_chip_size: int = C_CHIP_SIZE_DEFAULT,
    v_bank_size: int = V_BANK_SIZE,
) -> bytes:
    """
    Like extract_romset but returns a ZIP archive as bytes.

    Parameters
    ----------
    c_chip_size : size of each C chip in bytes (default 2 MB).
                  Use 4 MB for games with larger C chips (e.g. Neo Turf Masters).
    v_bank_size : size of each V chunk in bytes (default 2 MB).
    """
    _warn_v_bank_size_remainder(romset, v_bank_size)
    ext = ".bin" if fmt == "mame" else ".rom"
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name_prefix}-p1{ext}", romset.p)
        zf.writestr(f"{name_prefix}-s1{ext}", romset.s)
        zf.writestr(f"{name_prefix}-m1{ext}", romset.m)
        for i, chunk in enumerate(romset.v_chunks(bank_size=v_bank_size), start=1):
            zf.writestr(f"{name_prefix}-v{i}{ext}", chunk)
        for i, chip in enumerate(romset.c_chips(chip_size=c_chip_size), start=1):
            zf.writestr(f"{name_prefix}-c{i}{ext}", chip)

    return buf.getvalue()


def extract_neo_to_zip(
    neo_data: bytes,
    name_prefix: str = "game",
    fmt: str = "mame",
    c_chip_size: int = C_CHIP_SIZE_DEFAULT,
    v_bank_size: int = V_BANK_SIZE,
) -> bytes:
    """Like extract_neo but returns a ZIP archive as bytes.

    Parameters
    ----------
    c_chip_size : size of each C chip in bytes (default 2 MB).
                  Use 4 MB for games with larger C chips (e.g. Neo Turf Masters).
    v_bank_size : size of each V chunk in bytes (default 2 MB).
    """
    romset = parse_neo(neo_data)
    return extract_romset_to_zip(
        romset,
        name_prefix=name_prefix,
        fmt=fmt,
        c_chip_size=c_chip_size,
        v_bank_size=v_bank_size,
    )


def neo_to_mame_zip(neo_path: Path, prefix: str) -> bytes:
    """Extract a .neo file and return a MAME-format ZIP as bytes."""
    return extract_neo_to_zip(neo_path.read_bytes(), name_prefix=prefix, fmt="mame")


def neo_to_darksoft_zip(neo_path: Path, prefix: str) -> bytes:
    """Extract a .neo file and return a Darksoft-format ZIP as bytes."""
    return extract_neo_to_zip(neo_path.read_bytes(), name_prefix=prefix, fmt="darksoft")
