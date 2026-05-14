"""Extract :class:`RomSet` / ``.neo`` bytes into MAME or Darksoft file layouts."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .constants import C_CHIP_SIZE_DEFAULT
from .models import RomSet
from .neo_format import parse_neo


def extract_romset(
    romset: RomSet,
    output_dir: Path,
    name_prefix: str = "game",
    fmt: str = "mame",
    c_chip_size: int = C_CHIP_SIZE_DEFAULT,
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

    Returns dict mapping role -> output Path.
    """
    ext = ".bin" if fmt == "mame" else ".rom"
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def write(role: str, data: bytes, suffix: str = "") -> Path:
        fname = f"{name_prefix}-{role}{suffix}{ext}"
        p = output_dir / fname
        p.write_bytes(data)
        written[role + suffix] = p
        return p

    write("p1", romset.p)
    write("s1", romset.s)
    write("m1", romset.m)

    for i, chunk in enumerate(romset.v_chunks(), start=1):
        write("v", chunk, suffix=str(i))

    for i, chip in enumerate(romset.c_chips(chip_size=c_chip_size), start=1):
        write("c", chip, suffix=str(i))

    return written


def extract_neo(
    neo_data: bytes,
    output_dir: Path,
    name_prefix: str = "game",
    fmt: str = "mame",
    c_chip_size: int = C_CHIP_SIZE_DEFAULT,
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

    Returns dict mapping role -> output Path.
    """
    romset = parse_neo(neo_data)
    return extract_romset(
        romset, output_dir, name_prefix=name_prefix, fmt=fmt, c_chip_size=c_chip_size
    )


def extract_romset_to_zip(
    romset: RomSet,
    name_prefix: str = "game",
    fmt: str = "mame",
    c_chip_size: int = C_CHIP_SIZE_DEFAULT,
) -> bytes:
    """
    Like extract_romset but returns a ZIP archive as bytes.

    Parameters
    ----------
    c_chip_size : size of each C chip in bytes (default 2 MB).
                  Use 4 MB for games with larger C chips (e.g. Neo Turf Masters).
    """
    ext = ".bin" if fmt == "mame" else ".rom"
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name_prefix}-p1{ext}", romset.p)
        zf.writestr(f"{name_prefix}-s1{ext}", romset.s)
        zf.writestr(f"{name_prefix}-m1{ext}", romset.m)
        for i, chunk in enumerate(romset.v_chunks(), start=1):
            zf.writestr(f"{name_prefix}-v{i}{ext}", chunk)
        for i, chip in enumerate(romset.c_chips(chip_size=c_chip_size), start=1):
            zf.writestr(f"{name_prefix}-c{i}{ext}", chip)

    return buf.getvalue()


def extract_neo_to_zip(
    neo_data: bytes,
    name_prefix: str = "game",
    fmt: str = "mame",
    c_chip_size: int = C_CHIP_SIZE_DEFAULT,
) -> bytes:
    """Like extract_neo but returns a ZIP archive as bytes.

    Parameters
    ----------
    c_chip_size : size of each C chip in bytes (default 2 MB).
                  Use 4 MB for games with larger C chips (e.g. Neo Turf Masters).
    """
    romset = parse_neo(neo_data)
    return extract_romset_to_zip(
        romset, name_prefix=name_prefix, fmt=fmt, c_chip_size=c_chip_size
    )


def neo_to_mame_zip(neo_path: Path, prefix: str) -> bytes:
    """Extract a .neo file and return a MAME-format ZIP as bytes."""
    return extract_neo_to_zip(neo_path.read_bytes(), name_prefix=prefix, fmt="mame")


def neo_to_darksoft_zip(neo_path: Path, prefix: str) -> bytes:
    """Extract a .neo file and return a Darksoft-format ZIP as bytes."""
    return extract_neo_to_zip(neo_path.read_bytes(), name_prefix=prefix, fmt="darksoft")
