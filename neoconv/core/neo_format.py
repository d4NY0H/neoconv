"""Parse and build TerraOnion ``.neo`` container files."""

from __future__ import annotations

import os
import secrets
import stat
import struct
import warnings
from pathlib import Path
from typing import Optional

from .constants import GENRES, NEO_HEADER_SIZE, NEO_MAGIC
from .exceptions import InvalidNeoError
from .models import NeoMeta, RomSet

# Fixed-width metadata fields in the 4096-byte header.
_NAME_OFFSET = 0x2C
_NAME_SIZE = 33  # 0x2C..0x4C, NUL-terminated
_MANUFACTURER_OFFSET = 0x4D
_MANUFACTURER_SIZE = 17  # 0x4D..0x5D, NUL-terminated


def _looks_like_legacy_uint16_meta(data: bytes) -> bool:
    """
    Detect pre-fix neoconv headers that packed Year/Genre as uint16 at 0x1C/0x1E.

    TerraOnion / neosdconv (and current neoconv) use four uint32 fields starting
    at 0x1C, with NGH at 0x28. Old writers left 0x28..0x2B zero and stored genre
    in the high half of the first meta word. When genre was 0 the layouts are
    ambiguous; those files are read as the modern layout.
    """
    year16 = struct.unpack_from("<H", data, 0x1C)[0]
    genre16 = struct.unpack_from("<H", data, 0x1E)[0]
    year32 = struct.unpack_from("<I", data, 0x1C)[0]
    ngh_at_28 = struct.unpack_from("<I", data, 0x28)[0]
    if ngh_at_28 != 0:
        return False
    if genre16 == 0 or genre16 not in GENRES:
        return False
    if not (1900 <= year16 <= 2100):
        return False
    return year32 == year16 + (genre16 << 16)


def _meta_from_neo_header_prefix(data: bytes) -> NeoMeta:
    """Parse ``NeoMeta`` from the first ``NEO_HEADER_SIZE`` bytes of a .neo file."""
    if len(data) < NEO_HEADER_SIZE:
        raise InvalidNeoError("File too small to be a valid .neo container.")
    if data[:4] != NEO_MAGIC:
        raise InvalidNeoError(
            f"Not a valid .neo file (magic={data[:4]!r}, expected {NEO_MAGIC!r})"
        )

    if _looks_like_legacy_uint16_meta(data):
        warnings.warn(
            "This .neo uses a legacy neoconv header (Year/Genre as uint16). "
            "Metadata is being read with the old layout; rewriting with edit "
            "or pack will emit the TerraOnion uint32 layout.",
            UserWarning,
            stacklevel=3,
        )
        year = struct.unpack_from("<H", data, 0x1C)[0]
        genre = struct.unpack_from("<H", data, 0x1E)[0]
        screenshot = struct.unpack_from("<I", data, 0x20)[0]
        ngh = struct.unpack_from("<I", data, 0x24)[0]
    else:
        # TerraOnion / neosdconv: four consecutive uint32 after the size fields.
        year = struct.unpack_from("<I", data, 0x1C)[0]
        genre = struct.unpack_from("<I", data, 0x20)[0]
        screenshot = struct.unpack_from("<I", data, 0x24)[0]
        ngh = struct.unpack_from("<I", data, 0x28)[0]

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
        raise InvalidNeoError(
            f"File size mismatch: got {len(data)}, expected {expected}. "
            "The .neo file may be corrupt or truncated."
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

    return RomSet(
        p=p_rom,
        s=s_rom,
        m=m_rom,
        v=v_rom,
        c=c_rom,
        meta=meta,
        v1_size=v1_size,
        v2_size=v2_size,
    )


def _pack_neo_header(
    p_size: int,
    s_size: int,
    m_size: int,
    v1_size: int,
    v2_size: int,
    c_size: int,
    meta: NeoMeta,
) -> bytes:
    """
    Serialise the 4096-byte TerraOnion header.

    The V1/V2 split is written exactly as supplied. Callers that do not know
    the split (for example a RomSet assembled from MAME input) must pass
    ``v1_size=len(V)`` and ``v2_size=0`` — the documented legacy layout.
    """
    header = bytearray(NEO_HEADER_SIZE)
    header[0:4] = NEO_MAGIC
    struct.pack_into("<I", header, 0x04, p_size)
    struct.pack_into("<I", header, 0x08, s_size)
    struct.pack_into("<I", header, 0x0C, m_size)
    struct.pack_into("<I", header, 0x10, v1_size)
    struct.pack_into("<I", header, 0x14, v2_size)
    struct.pack_into("<I", header, 0x18, c_size)

    struct.pack_into("<I", header, 0x1C, meta.year)
    struct.pack_into("<I", header, 0x20, meta.genre)
    struct.pack_into("<I", header, 0x24, meta.screenshot)
    struct.pack_into("<I", header, 0x28, meta.ngh)

    _write_fixed_field(header, _NAME_OFFSET, _NAME_SIZE, meta.name)
    _write_fixed_field(header, _MANUFACTURER_OFFSET, _MANUFACTURER_SIZE, meta.manufacturer)

    return bytes(header)


def _write_fixed_field(header: bytearray, offset: int, size: int, value: str) -> None:
    """Write a NUL-terminated fixed-width field, clearing any stale tail."""
    encoded = value.encode("latin-1", errors="replace")[: size - 1]
    header[offset : offset + size] = encoded.ljust(size, b"\x00")


def build_neo(romset: RomSet, meta: NeoMeta) -> bytes:
    """
    Pack a RomSet into a .neo binary.

    When ``romset.v1_size``/``v2_size`` are known (typically because the
    RomSet came from :func:`parse_neo`), the original V1/V2 split is
    reproduced exactly. Otherwise all V data is written to V1 with V2 = 0
    (legacy layout).
    """
    v1_size, v2_size = romset.v_sizes()
    hdr = _pack_neo_header(
        len(romset.p),
        len(romset.s),
        len(romset.m),
        v1_size,
        v2_size,
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

    The existing 4096-byte header is copied and only the requested fields are
    patched; every other header byte (size fields, V1/V2 split, unknown padding
    and filler such as ``RMF1`` at 0x100) is preserved byte-for-byte. Payload
    bytes after the header are reused unchanged.

    One exception is a legacy neoconv header (Year/Genre stored as uint16): the
    four metadata words at 0x1C..0x2B are migrated to the modern TerraOnion
    uint32 layout, because patching a mixed layout in place would be ambiguous.
    All other header bytes are still preserved.
    """
    if len(neo_data) < NEO_HEADER_SIZE:
        raise InvalidNeoError("File too small to be a valid .neo container.")
    if neo_data[:4] != NEO_MAGIC:
        raise InvalidNeoError(
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
        raise InvalidNeoError(
            f"File size mismatch: got {len(neo_data)}, expected {expected}. "
            "The .neo file may be corrupt or truncated."
        )

    legacy_meta = _looks_like_legacy_uint16_meta(neo_data)
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

    header = bytearray(neo_data[:NEO_HEADER_SIZE])

    if legacy_meta:
        # Migrate the whole metadata block so the result uses one consistent layout.
        struct.pack_into("<I", header, 0x1C, meta.year)
        struct.pack_into("<I", header, 0x20, meta.genre)
        struct.pack_into("<I", header, 0x24, meta.screenshot)
        struct.pack_into("<I", header, 0x28, meta.ngh)
    else:
        if year is not None:
            struct.pack_into("<I", header, 0x1C, meta.year)
        if genre is not None:
            struct.pack_into("<I", header, 0x20, meta.genre)
        if screenshot is not None:
            struct.pack_into("<I", header, 0x24, meta.screenshot)
        if ngh is not None:
            struct.pack_into("<I", header, 0x28, meta.ngh)

    if name is not None:
        _write_fixed_field(header, _NAME_OFFSET, _NAME_SIZE, meta.name)
    if manufacturer is not None:
        _write_fixed_field(header, _MANUFACTURER_OFFSET, _MANUFACTURER_SIZE, meta.manufacturer)

    return bytes(header) + neo_data[NEO_HEADER_SIZE:]


def _fsync_directory(directory: Path) -> None:
    """
    Best-effort ``fsync`` of *directory* so a rename is durable.

    Directory ``fsync`` is not available or not permitted on every platform
    (notably Windows), so failures are ignored: the data file itself was
    already synced before the rename.
    """
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def write_bytes_atomic(path: Path | str, data: bytes) -> None:
    """
    Write *data* to *path* atomically and durably.

    The content goes to a unique, exclusively created temporary file in the
    destination directory (unpredictable name, ``O_EXCL``), is flushed and
    ``fsync``-ed, then moved into place with :func:`os.replace`. The parent
    directory is ``fsync``-ed afterwards on platforms that support it.

    *path* is used as given: it is never resolved, so a symbolic link at that
    exact path is **replaced as a link** rather than followed, and the link
    target is never modified. Existing regular-file permissions are preserved
    when replacing where the filesystem supports ``chmod``; the mode copy is
    best-effort so mode-less mounts (SMB/CIFS, for example) still get the write.
    New files get the default mode allowed by the process umask (``0o666``
    masked).
    """
    target = Path(path)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)

    # Preserve the mode of an existing regular file. A symlink is not followed:
    # replacing it creates a new regular file with the umask default.
    existing_mode: Optional[int] = None
    try:
        st = os.lstat(target)
    except OSError:
        pass
    else:
        if stat.S_ISREG(st.st_mode):
            existing_mode = stat.S_IMODE(st.st_mode)

    tmp = parent / f".neoconv-{secrets.token_hex(8)}.tmp"
    fd: Optional[int] = None
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        if existing_mode is not None:
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, existing_mode)
                else:  # pragma: no cover - Windows has no fchmod
                    os.chmod(tmp, existing_mode)
            except OSError:
                # Mode-less filesystems (SMB/CIFS) may reject chmod. Keep the
                # umask-derived temp mode rather than failing the whole write.
                pass
        with os.fdopen(fd, "wb") as fh:
            fd = None  # ownership transferred to the file object
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        _fsync_directory(parent)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
