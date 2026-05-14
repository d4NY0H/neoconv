"""Parse and build TerraOnion ``.neo`` container files."""

from __future__ import annotations

import os
import struct
import warnings
from pathlib import Path
from typing import Optional

from .constants import NEO_HEADER_SIZE, NEO_MAGIC
from .models import NeoMeta, RomSet


def _meta_from_neo_header_prefix(data: bytes) -> NeoMeta:
    """Parse ``NeoMeta`` from the first ``NEO_HEADER_SIZE`` bytes of a .neo file."""
    if len(data) < NEO_HEADER_SIZE:
        raise ValueError("File too small to be a valid .neo container.")
    if data[:4] != NEO_MAGIC:
        raise ValueError(
            f"Not a valid .neo file (magic={data[:4]!r}, expected {NEO_MAGIC!r})"
        )
    year = struct.unpack_from("<H", data, 0x1C)[0]
    genre = struct.unpack_from("<H", data, 0x1E)[0]
    screenshot = struct.unpack_from("<I", data, 0x20)[0]
    ngh = struct.unpack_from("<I", data, 0x24)[0]
    name = data[0x2C:0x4D].split(b"\x00")[0].decode("latin-1")
    manufacturer = data[0x4D:0x5E].split(b"\x00")[0].decode("latin-1")
    return NeoMeta(
        name=name,
        manufacturer=manufacturer,
        year=year,
        genre=genre,
        screenshot=screenshot,
        ngh=ngh,
    )


def parse_neo_header_metadata(data: bytes) -> NeoMeta:
    """
    Read metadata from a .neo header without loading ROM regions.

    *data* must contain at least ``NEO_HEADER_SIZE`` (4096) bytes from the
    start of the file (typically read with ``path.read_bytes()[:NEO_HEADER_SIZE]``).
    """
    return _meta_from_neo_header_prefix(data)


def parse_neo(data: bytes) -> RomSet:
    """Parse a .neo file and return a RomSet."""
    meta = _meta_from_neo_header_prefix(data)

    p_size = struct.unpack_from("<I", data, 0x04)[0]
    s_size = struct.unpack_from("<I", data, 0x08)[0]
    m_size = struct.unpack_from("<I", data, 0x0C)[0]
    v1_size = struct.unpack_from("<I", data, 0x10)[0]
    v2_size = struct.unpack_from("<I", data, 0x14)[0]
    c_size = struct.unpack_from("<I", data, 0x18)[0]

    expected = NEO_HEADER_SIZE + p_size + s_size + m_size + v1_size + v2_size + c_size
    if len(data) != expected:
        raise ValueError(
            f"File size mismatch: got {len(data)}, expected {expected}. "
            "The .neo file may be corrupt or truncated."
        )

    if v2_size:
        warnings.warn(
            "This .neo header splits the V ROM across V1 and V2 size fields "
            f"(V1={v1_size} bytes, V2={v2_size} bytes). In-memory V data is merged; "
            "repacking with build_neo or replace_neo_metadata writes a normalised "
            "header (all V in the V1 field, V2 set to 0).",
            UserWarning,
            stacklevel=2,
        )

    offset = NEO_HEADER_SIZE
    p_rom = data[offset : offset + p_size]
    offset += p_size
    s_rom = data[offset : offset + s_size]
    offset += s_size
    m_rom = data[offset : offset + m_size]
    offset += m_size
    v_rom = data[offset : offset + v1_size]
    offset += v1_size
    if v2_size:
        v_rom += data[offset : offset + v2_size]
        offset += v2_size
    c_rom = data[offset : offset + c_size]

    return RomSet(p=p_rom, s=s_rom, m=m_rom, v=v_rom, c=c_rom, meta=meta)


def _pack_neo_header(
    p_size: int,
    s_size: int,
    m_size: int,
    v_total: int,
    c_size: int,
    meta: NeoMeta,
) -> bytes:
    """
    Serialise the 4096-byte TerraOnion header.

    All V data is recorded in the V1 size field; V2 is always zero (same layout
    as :func:`build_neo` output).
    """
    header = bytearray(NEO_HEADER_SIZE)
    header[0:4] = NEO_MAGIC
    struct.pack_into("<I", header, 0x04, p_size)
    struct.pack_into("<I", header, 0x08, s_size)
    struct.pack_into("<I", header, 0x0C, m_size)
    struct.pack_into("<I", header, 0x10, v_total)
    struct.pack_into("<I", header, 0x14, 0)  # V2 size (merged into V1)
    struct.pack_into("<I", header, 0x18, c_size)

    struct.pack_into("<H", header, 0x1C, meta.year)
    struct.pack_into("<H", header, 0x1E, meta.genre)
    struct.pack_into("<I", header, 0x20, meta.screenshot)
    struct.pack_into("<I", header, 0x24, meta.ngh)

    name_b = meta.name.encode("latin-1", errors="replace")[:32]
    header[0x2C : 0x2C + len(name_b)] = name_b

    mfr_b = meta.manufacturer.encode("latin-1", errors="replace")[:16]
    header[0x4D : 0x4D + len(mfr_b)] = mfr_b

    return bytes(header)


def build_neo(romset: RomSet, meta: NeoMeta) -> bytes:
    """Pack a RomSet into a .neo binary."""
    hdr = _pack_neo_header(
        len(romset.p),
        len(romset.s),
        len(romset.m),
        len(romset.v),
        len(romset.c),
        meta,
    )
    return hdr + romset.p + romset.s + romset.m + romset.v + romset.c


def replace_neo_metadata(
    neo_data: bytes,
    *,
    name: Optional[str] = None,
    manufacturer: Optional[str] = None,
    year: Optional[int] = None,
    genre: Optional[int] = None,
    ngh: Optional[int] = None,
    screenshot: Optional[int] = None,
) -> bytes:
    """
    Return a new .neo file with updated header metadata. ROM regions are unchanged.

    Parameters set to ``None`` are left unchanged from *neo_data*.

    Only the 4096-byte header is rebuilt; ROM payload bytes are reused without
    splitting the file into a :class:`RomSet` (avoids large temporary copies).
    """
    if len(neo_data) < NEO_HEADER_SIZE:
        raise ValueError("File too small to be a valid .neo container.")
    if neo_data[:4] != NEO_MAGIC:
        raise ValueError(
            f"Not a valid .neo file (magic={neo_data[:4]!r}, expected {NEO_MAGIC!r})"
        )

    p_size = struct.unpack_from("<I", neo_data, 0x04)[0]
    s_size = struct.unpack_from("<I", neo_data, 0x08)[0]
    m_size = struct.unpack_from("<I", neo_data, 0x0C)[0]
    v1_size = struct.unpack_from("<I", neo_data, 0x10)[0]
    v2_size = struct.unpack_from("<I", neo_data, 0x14)[0]
    c_size = struct.unpack_from("<I", neo_data, 0x18)[0]

    expected = NEO_HEADER_SIZE + p_size + s_size + m_size + v1_size + v2_size + c_size
    if len(neo_data) != expected:
        raise ValueError(
            f"File size mismatch: got {len(neo_data)}, expected {expected}. "
            "The .neo file may be corrupt or truncated."
        )

    if v2_size:
        warnings.warn(
            "Input .neo has a non-zero V2 ROM size in the header; the rewritten "
            "header records all V data in the V1 field (V2 set to 0). "
            "ROM payload bytes after the 4096-byte header are unchanged.",
            UserWarning,
            stacklevel=2,
        )

    meta = _meta_from_neo_header_prefix(neo_data)
    if name is not None:
        meta.name = name
    if manufacturer is not None:
        meta.manufacturer = manufacturer
    if year is not None:
        meta.year = year
    if genre is not None:
        meta.genre = genre
    if ngh is not None:
        meta.ngh = ngh
    if screenshot is not None:
        meta.screenshot = screenshot

    v_total = v1_size + v2_size
    hdr = _pack_neo_header(p_size, s_size, m_size, v_total, c_size, meta)
    return hdr + neo_data[NEO_HEADER_SIZE:]


def write_bytes_atomic(path: Path | str, data: bytes) -> None:
    """
    Write *data* to *path* via a temporary file in the same directory and
    ``os.replace`` (atomic on POSIX when replacing an existing file).
    """
    p = Path(path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.parent / f".neoconv_{p.name}.{os.getpid()}.tmp"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, p)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
