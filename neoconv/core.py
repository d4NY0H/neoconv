"""
neoconv.core
~~~~~~~~~~~~
Core logic for converting between .neo container files and
MAME / Darksoft ROM sets for SNK Neo Geo.

The .neo format (TerraOnion NeoSD):
  Offset 0x000  Magic       b'NEO\x01'  (4 bytes)
  Offset 0x004  P ROM size  uint32 LE
  Offset 0x008  S ROM size  uint32 LE
  Offset 0x00C  M ROM size  uint32 LE
  Offset 0x010  V1 ROM size uint32 LE
  Offset 0x014  V2 ROM size uint32 LE
  Offset 0x018  C ROM size  uint32 LE  (total, interleaved)
  Offset 0x01C  Year        uint16 LE
  Offset 0x01E  Genre       uint16 LE
  Offset 0x020  Screenshot  uint32 LE
  Offset 0x024  NGH number  uint32 LE
  Offset 0x02C  Name        33 bytes, null-terminated
  Offset 0x04D  Mfr         17 bytes, null-terminated
  Offset 0x200  (header padded to 0x1000 = 4096 bytes)
  Data: P, S, M, V1, V2, C  (in this order, sizes from header)

C ROM layout in .neo:
  Bytes are interleaved: even bytes → odd-numbered chips (c1, c3, ...),
                         odd  bytes → even-numbered chips (c2, c4, ...).

  The .neo container stores the total interleaved C data as one contiguous
  block. The original chip boundaries are NOT recorded in the header —
  de-interleaving requires knowing the individual chip size, which varies
  by game and must be looked up from the MAME/FBNeo ROM set.

  Common chip sizes found in the Neo Geo library (per chip, before interleaving):
    512 KB, 1 MB, 2 MB, 4 MB, 8 MB, 16 MB, 20 MB

  Examples:
    4 MB C total, 2 MB chips → interleaved(c1[2MB], c2[2MB])
    8 MB C total, 4 MB chips → interleaved(c1[4MB], c2[4MB])
    8 MB C total, 2 MB chips → interleaved(c1[2MB], c2[2MB])
                              + interleaved(c3[2MB], c4[2MB])

  Use the --c-chip-size option to specify the correct chip size when extracting.
  Default is 2 MB, which covers the majority of titles.
"""

from __future__ import annotations

import hashlib
import io
import re
import struct
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NEO_MAGIC = b"NEO\x01"
NEO_HEADER_SIZE = 0x1000  # 4096 bytes
C_CHIP_SIZE_DEFAULT = 2 * 1024 * 1024  # 2 MB default C chip size (most games)
V_BANK_SIZE = 2 * 1024 * 1024  # 2 MB per V ROM chunk (MAME standard)
P_SWAP_SIZE = 2 * 1024 * 1024  # 2 MB: size that triggers optional P-ROM bank swap

# Backwards-compatible alias
C_BANK_SIZE = C_CHIP_SIZE_DEFAULT

# MAME ``neogeo.xml`` cart ROM IDs whose parent sets use a 512 KiB zero-filled
# ``fixed`` / text layer when there is no dedicated s1 (encrypted boards).
_SYNTH_S_MAME_512K_SET_IDS = frozenset({253, 256, 257, 263, 266, 269, 271})


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
    sp  = int.from_bytes(sw[0:4], "big")
    rst = int.from_bytes(sw[4:8], "big")
    sp_ok  = 0x100000 <= sp  <= 0x10FFFF
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
    # Neither valid
    return False, (
        f"Neither half has a recognisable M68k vector table "
        f"(half1: SP=0x{sp1:08X}/Reset=0x{rst1:08X}, "
        f"half2: SP=0x{sp2:08X}/Reset=0x{rst2:08X}). "
        f"Swap detection inconclusive — check manually."
    )


GENRES = {
    0: "Other",
    1: "Action",
    2: "BeatEmUp",
    3: "Sports",
    4: "Driving",
    5: "Platformer",
    6: "Mahjong",
    7: "Shooter",
    8: "Quiz",
    9: "Fighting",
    10: "Puzzle",
}
GENRE_BY_NAME = {v.lower(): k for k, v in GENRES.items()}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NeoMeta:
    name: str = "Unknown"
    manufacturer: str = "Unknown"
    year: int = 0
    genre: int = 0
    screenshot: int = 0
    ngh: int = 0

    def format_info(self, romset: "RomSet | None" = None) -> str:
        """Return a human-readable summary, optionally including ROM sizes."""
        lines = [
            f"  Name         : {self.name}",
            f"  Manufacturer : {self.manufacturer}",
            f"  Year         : {self.year}",
            f"  Genre        : {GENRES.get(self.genre, self.genre)}",
            f"  NGH          : {self.ngh}",
            f"  Screenshot # : {self.screenshot}",
        ]
        if romset is not None:
            v_total = len(romset.v)
            total   = NEO_HEADER_SIZE + len(romset.p) + len(romset.s) + len(romset.m) + v_total + len(romset.c)
            lines += [
                f"  P ROM        : {len(romset.p):>10,} bytes  ({len(romset.p)/1024/1024:.3f} MB)",
                f"  S ROM        : {len(romset.s):>10,} bytes  ({len(romset.s)/1024:.0f} KB)",
                f"  M ROM        : {len(romset.m):>10,} bytes  ({len(romset.m)/1024:.0f} KB)",
                f"  V ROM        : {v_total:>10,} bytes  ({v_total/1024/1024:.3f} MB)",
                f"  C ROM        : {len(romset.c):>10,} bytes  ({len(romset.c)/1024/1024:.3f} MB)",
                f"  Total        : {total:>10,} bytes  ({total/1024/1024:.2f} MB)",
            ]
        return "\n".join(lines)


@dataclass
class RomSet:
    """Holds raw ROM region data."""
    p: bytes = b""
    s: bytes = b""
    m: bytes = b""
    v: bytes = b""   # all V data concatenated (V1 + V2 + ...)
    c: bytes = b""   # all C data interleaved (as stored in .neo)
    meta: NeoMeta = field(default_factory=NeoMeta)

    # --- derived helpers ---

    def v_chunks(self) -> list[bytes]:
        """Split V data into V_BANK_SIZE (2 MB) chunks."""
        chunks = []
        for i in range(0, len(self.v), V_BANK_SIZE):
            chunks.append(self.v[i : i + V_BANK_SIZE])
        return chunks

    def c_chips(self, chip_size: int = C_CHIP_SIZE_DEFAULT) -> list[bytes]:
        """
        De-interleave C ROM into individual chip images.

        .neo stores C data byte-interleaved in banks:
          byte 0 -> chip N (c1/c3/...)
          byte 1 -> chip N+1 (c2/c4/...)

        Each interleaved bank = chip_size * 2 bytes.
        Returns list: [c1, c2, c3, c4, ...]

        Parameters
        ----------
        chip_size : size of each individual chip in bytes.
                    Default 2 MB covers most Neo Geo games.
                    Use 4 MB for games with larger C chips (e.g. Neo Turf Masters).
                    When in doubt, check the MAME ROM set for the expected chip sizes.
        """
        bank_size = chip_size * 2
        if len(self.c) % bank_size != 0:
            raise ValueError(
                f"C ROM size ({len(self.c):,} bytes) is not a multiple of "
                f"chip_size*2 ({bank_size:,} bytes). "
                f"Try a different --c-chip-size value."
            )
        chips = []
        for bank_start in range(0, len(self.c), bank_size):
            bank = self.c[bank_start : bank_start + bank_size]
            chips.append(bytes(bank[0::2]))  # odd chip  (c1, c3, ...)
            chips.append(bytes(bank[1::2]))  # even chip (c2, c4, ...)
        return chips


# ---------------------------------------------------------------------------
# .neo parsing
# ---------------------------------------------------------------------------

def parse_neo(data: bytes) -> RomSet:
    """Parse a .neo file and return a RomSet."""
    if data[:4] != NEO_MAGIC:
        raise ValueError(
            f"Not a valid .neo file (magic={data[:4]!r}, expected {NEO_MAGIC!r})"
        )
    if len(data) < NEO_HEADER_SIZE:
        raise ValueError("File too small to be a valid .neo container.")

    p_size  = struct.unpack_from("<I", data, 0x04)[0]
    s_size  = struct.unpack_from("<I", data, 0x08)[0]
    m_size  = struct.unpack_from("<I", data, 0x0C)[0]
    v1_size = struct.unpack_from("<I", data, 0x10)[0]
    v2_size = struct.unpack_from("<I", data, 0x14)[0]
    c_size  = struct.unpack_from("<I", data, 0x18)[0]

    year        = struct.unpack_from("<H", data, 0x1C)[0]
    genre       = struct.unpack_from("<H", data, 0x1E)[0]
    screenshot  = struct.unpack_from("<I", data, 0x20)[0]
    ngh         = struct.unpack_from("<I", data, 0x24)[0]
    name        = data[0x2C:0x4D].split(b"\x00")[0].decode("latin-1")
    manufacturer= data[0x4D:0x5E].split(b"\x00")[0].decode("latin-1")

    expected = NEO_HEADER_SIZE + p_size + s_size + m_size + v1_size + v2_size + c_size
    if len(data) != expected:
        raise ValueError(
            f"File size mismatch: got {len(data)}, expected {expected}. "
            "The .neo file may be corrupt or truncated."
        )

    offset = NEO_HEADER_SIZE
    p_rom  = data[offset : offset + p_size];  offset += p_size
    s_rom  = data[offset : offset + s_size];  offset += s_size
    m_rom  = data[offset : offset + m_size];  offset += m_size
    v_rom  = data[offset : offset + v1_size]; offset += v1_size
    if v2_size:
        v_rom += data[offset : offset + v2_size]; offset += v2_size
    c_rom  = data[offset : offset + c_size]

    meta = NeoMeta(
        name=name,
        manufacturer=manufacturer,
        year=year,
        genre=genre,
        screenshot=screenshot,
        ngh=ngh,
    )
    return RomSet(p=p_rom, s=s_rom, m=m_rom, v=v_rom, c=c_rom, meta=meta)


# ---------------------------------------------------------------------------
# MAME ZIP parsing
# ---------------------------------------------------------------------------

def pack_psm_role_from_basename(filename: str) -> Optional[str]:
    """
    Map a basename to P / S / M for Pack-tab preflight (same rules as the GUI).

    ``p1`` and ``p2`` both count as program ROM (``P``); only these three roles
    are considered here (V/C are handled elsewhere).
    """
    fn = Path(filename).name.lower()
    ext = Path(fn).suffix.lstrip(".")
    stem = Path(fn).stem
    ext_map = {"p1": "P", "p2": "P", "s1": "S", "m1": "M"}
    if ext in ext_map:
        return ext_map[ext]
    for key, role in ext_map.items():
        if fn.endswith(f"-{key}.bin") or fn.endswith(f"_{key}.bin") \
                or stem.endswith(f"-{key}") or stem.endswith(f"_{key}"):
            return role
    return None


def _filenames_imply_c1_sprite_rom(filenames: tuple[str, ...]) -> bool:
    """
    True if the input looks like it includes a Neo Geo C1 sprite ROM.

    MAME uses several naming schemes (``253-c1.c1``, ``mart-c1.bin``,
    ``kf10-c1a.bin``); :func:`_name_to_role` only covers the common forms.
    """
    for p in filenames:
        n = Path(p).name
        if _name_to_role(n) == "C1":
            return True
        nl = n.lower()
        if re.search(r"[-_]c1[a-z0-9]*\.(?:c1|bin)\b", nl):
            return True
    return False


def collect_pack_psm_roles_for_validation(filenames: Iterable[str]) -> set[str]:
    """
    P/S/M roles satisfied for Pack validation, including boards with no s1 file.

    MAME lists several sets (e.g. parent ``svc``) where the text layer has no
    dedicated s1 ROM; the driver fills the fixed region with zeros. When such
    a set is detected, ``S`` is treated as present for preflight only.
    """
    names = tuple(filenames)
    roles: set[str] = set()
    for n in names:
        r = pack_psm_role_from_basename(n)
        if r:
            roles.add(r)
    if "S" not in roles and _should_inject_synthetic_s_rom(names, roles):
        roles.add("S")
    return roles


def _should_inject_synthetic_s_rom(names: tuple[str, ...], psm_roles: set[str]) -> bool:
    if "P" not in psm_roles or "M" not in psm_roles:
        return False
    return _filenames_imply_c1_sprite_rom(names)


def _synthetic_zero_s_size_from_filenames(filenames: tuple[str, ...]) -> int:
    """
    MAME ``fixed`` fill size when there is no s1 (zeros).

    Sizes are taken from ``neogeo.xml`` (software list): ``0x40000`` for the
    ``kf10`` bootleg, ``0x80000`` for PVC / SMA / CHAFIO parents (including
    sets that use ``NNN-c1.c1`` without ``c1r`` in the name), and ``0x20000``
    for typical CMC / earlier encrypted boards.
    """
    blob = " ".join(Path(p).name.lower() for p in filenames)
    if "kf10-" in blob:
        return 0x40000
    if "c1r" in blob or "c2r" in blob:
        return 0x80000
    for p in filenames:
        fn = Path(p).name.lower()
        for m in re.finditer(
            r"(?<![0-9])([0-9]{3})-(?:p1\.|p2\.|m1\.|c1[a-z0-9]*\.c1)", fn
        ):
            if int(m.group(1), 10) in _SYNTH_S_MAME_512K_SET_IDS:
                return 0x80000
    return 0x20000


def _inject_synthetic_s_rom_if_needed(
    roles: dict[str, bytes],
    source: str,
    source_filenames: tuple[str, ...] | None,
) -> None:
    if "S" in roles or source_filenames is None:
        return
    names = source_filenames
    psm = {r for n in names if (r := pack_psm_role_from_basename(n))}
    if not _should_inject_synthetic_s_rom(names, psm):
        return
    size = _synthetic_zero_s_size_from_filenames(names)
    roles["S"] = b"\x00" * size
    warnings.warn(
        f"No text-layer ROM (s1) in {source}; using {size // 1024} KiB zero fill "
        "as MAME does for boards without a dedicated s1.",
        UserWarning,
        stacklevel=3,
    )


def _name_to_role(filename: str) -> Optional[str]:
    """
    Map a filename inside a MAME zip to its ROM role.
    Returns 'P', 'S', 'M', 'V1'..'V8', 'C1'..'C8', or None.
    """
    fn  = Path(filename).name.lower()
    ext = Path(fn).suffix.lstrip(".")
    stem = Path(fn).stem

    ext_map = {
        "p1": "P", "p2": "P2",
        "s1": "S",
        "m1": "M",
        "v1": "V1", "v2": "V2", "v3": "V3", "v4": "V4",
        "v5": "V5", "v6": "V6", "v7": "V7", "v8": "V8",
        "c1": "C1", "c2": "C2", "c3": "C3", "c4": "C4",
        "c5": "C5", "c6": "C6", "c7": "C7", "c8": "C8",
    }
    if ext in ext_map:
        return ext_map[ext]

    # Name-based: look for -p1, -s1, -m1, -v1..v8, -c1..c8
    for key, role in ext_map.items():
        if fn.endswith(f"-{key}.bin") or fn.endswith(f"_{key}.bin") \
                or stem.endswith(f"-{key}") or stem.endswith(f"_{key}"):
            return role
    return None


def _roles_to_romset(
    roles: dict[str, bytes],
    source: str = "",
    *,
    source_filenames: tuple[str, ...] | None = None,
) -> RomSet:
    """
    Build a RomSet from a dict mapping role strings to raw bytes.
    Raises ValueError for missing mandatory ROMs or malformed C chip counts.

    When ``source_filenames`` is provided (ZIP member paths or directory
    basenames), boards without a physical s1 ROM may receive a zero-filled
    synthetic S region matching MAME's ``fixed`` area behaviour.
    """
    roles = dict(roles)
    _inject_synthetic_s_rom_if_needed(roles, source, source_filenames)
    missing = [r for r in ("P", "S", "M") if r not in roles]
    if missing:
        tips_by_role = {
            "P": "P program ROM missing (expected p1/p2, e.g. game-p1.bin or game.p1)",
            "S": "S ROM missing (expected s1, e.g. game-s1.bin or game.s1)",
            "M": "M ROM missing (expected m1, e.g. game-m1.bin or game.m1)",
        }
        tips = "; ".join(tips_by_role[r] for r in missing)
        raise ValueError(
            f"Missing mandatory ROM(s) in {source or 'input'}: "
            f"{', '.join(missing)}. "
            f"Quick tips: {tips}. "
            "Use --diagnostic to list unrecognized filenames."
        )

    p_rom = roles.get("P", b"") + roles.get("P2", b"")
    s_rom = roles["S"]
    m_rom = roles["M"]

    v_rom = b""
    for i in range(1, 9):
        chunk = roles.get(f"V{i}", b"")
        if not chunk:
            break
        v_rom += chunk

    c_chips_raw: list[bytes] = []
    for i in range(1, 9):
        chip = roles.get(f"C{i}", b"")
        if not chip:
            break
        c_chips_raw.append(chip)

    if c_chips_raw and len(c_chips_raw) % 2 != 0:
        raise ValueError(
            f"Odd number of C chips ({len(c_chips_raw)}) in {source or 'input'}. "
            "C chips must come in pairs (c1+c2, c3+c4, ...)."
        )

    # Validate C chip sizes
    for i in range(0, len(c_chips_raw), 2):
        a, b = c_chips_raw[i], c_chips_raw[i + 1]
        if len(a) != len(b):
            raise ValueError(
                f"C chip pair c{i+1}/c{i+2} size mismatch: {len(a)} vs {len(b)} bytes."
            )
        if len(a) % (512 * 1024) != 0:
            raise ValueError(
                f"C chip c{i+1} size ({len(a):,} bytes) is not a multiple of 512 KB. "
                "The ROM data may be corrupt or incorrectly split."
            )

    c_rom = _interleave_c_chips(c_chips_raw) if c_chips_raw else b""
    return RomSet(p=p_rom, s=s_rom, m=m_rom, v=v_rom, c=c_rom)


def _store_role_data(
    roles: dict[str, bytes],
    role: str,
    data: bytes,
    source_name: str,
    _diagnostic: bool,
) -> None:
    """Store role data, rejecting duplicate role mappings."""
    if role in roles:
        raise ValueError(
            f"Duplicate ROM role '{role}' in input: '{source_name}'. "
            "Each role (P/S/M/Vx/Cx) must map to exactly one file."
        )
    roles[role] = data


def parse_mame_zip(zip_path: Path, diagnostic: bool = False) -> RomSet:
    """Parse a MAME ROM zip and return a RomSet.

    Parameters
    ----------
    zip_path   : path to the ZIP file
    diagnostic : if True, print a warning for every file that was not
                 recognized, so the user can diagnose naming issues.
    """
    roles: dict[str, bytes] = {}
    ignored: list[str] = []
    all_names: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in zf.infolist():
                if entry.is_dir():
                    continue
                all_names.append(entry.filename)
                role = _name_to_role(entry.filename)
                if role is not None:
                    _store_role_data(roles, role, zf.read(entry.filename), entry.filename, diagnostic)
                else:
                    ignored.append(entry.filename)
    except zipfile.BadZipFile as e:
        raise ValueError(f"Cannot open ZIP file '{zip_path}': {e}") from e

    if diagnostic and ignored:
        for fn in ignored:
            warnings.warn(
                f"[diagnostic] Unrecognized file ignored: '{fn}' — "
                "check naming (expected e.g. game-p1.bin, game-c1.c1, ...)",
                stacklevel=2,
            )

    return _roles_to_romset(roles, source=str(zip_path), source_filenames=tuple(all_names))


def parse_mame_dir(dir_path: Path, diagnostic: bool = False) -> RomSet:
    """Parse a directory of raw ROM files and return a RomSet.

    Parameters
    ----------
    dir_path   : directory containing ROM files
    diagnostic : if True, print a warning for every file that was not
                 recognized, so the user can diagnose naming issues.
    """
    roles: dict[str, bytes] = {}
    ignored: list[str] = []
    all_names: list[str] = []
    for f in dir_path.iterdir():
        if f.is_file():
            all_names.append(f.name)
            role = _name_to_role(f.name)
            if role is not None:
                _store_role_data(roles, role, f.read_bytes(), f.name, diagnostic)
            else:
                ignored.append(f.name)

    if diagnostic and ignored:
        for fn in ignored:
            warnings.warn(
                f"[diagnostic] Unrecognized file ignored: '{fn}' — "
                "check naming (expected e.g. game-p1.bin, game-c1.c1, ...)",
                stacklevel=2,
            )

    return _roles_to_romset(roles, source=str(dir_path), source_filenames=tuple(all_names))


# ---------------------------------------------------------------------------
# C ROM interleaving helpers
# ---------------------------------------------------------------------------

def _interleave_c_chips(chips: list[bytes]) -> bytes:
    """
    Interleave pairs of C chips into .neo format.
    chips = [c1, c2, c3, c4, ...]
    Output: interleaved(c1,c2) + interleaved(c3,c4) + ...
    """
    result = bytearray()
    for i in range(0, len(chips), 2):
        a = chips[i]
        b = chips[i + 1]
        if len(a) != len(b):
            raise ValueError(
                f"C chip pair {i+1}/{i+2} size mismatch: "
                f"{len(a)} vs {len(b)} bytes."
            )
        interleaved = bytearray(len(a) + len(b))
        interleaved[0::2] = a
        interleaved[1::2] = b
        result.extend(interleaved)
    return bytes(result)


# ---------------------------------------------------------------------------
# .neo builder
# ---------------------------------------------------------------------------

def build_neo(romset: RomSet, meta: NeoMeta) -> bytes:
    """Pack a RomSet into a .neo binary."""
    header = bytearray(NEO_HEADER_SIZE)
    header[0:4] = NEO_MAGIC

    struct.pack_into("<I", header, 0x04, len(romset.p))
    struct.pack_into("<I", header, 0x08, len(romset.s))
    struct.pack_into("<I", header, 0x0C, len(romset.m))
    struct.pack_into("<I", header, 0x10, len(romset.v))
    struct.pack_into("<I", header, 0x14, 0)  # V2 size (merged into V1)
    struct.pack_into("<I", header, 0x18, len(romset.c))

    struct.pack_into("<H", header, 0x1C, meta.year)
    struct.pack_into("<H", header, 0x1E, meta.genre)
    struct.pack_into("<I", header, 0x20, meta.screenshot)
    struct.pack_into("<I", header, 0x24, meta.ngh)

    name_b = meta.name.encode("latin-1", errors="replace")[:32]
    header[0x2C : 0x2C + len(name_b)] = name_b

    mfr_b = meta.manufacturer.encode("latin-1", errors="replace")[:16]
    header[0x4D : 0x4D + len(mfr_b)] = mfr_b

    return bytes(header) + romset.p + romset.s + romset.m + romset.v + romset.c


# ---------------------------------------------------------------------------
# Extractor: .neo -> files
# ---------------------------------------------------------------------------

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
    return extract_romset(romset, output_dir, name_prefix=name_prefix, fmt=fmt,
                          c_chip_size=c_chip_size)


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
    return extract_romset_to_zip(romset, name_prefix=name_prefix, fmt=fmt,
                                 c_chip_size=c_chip_size)


# ---------------------------------------------------------------------------
# Verifier: roundtrip check
# ---------------------------------------------------------------------------

@dataclass
class VerifyResult:
    ok: bool
    original_rom_md5: str
    rebuilt_rom_md5: str
    file_size_match: bool
    details: str


def verify_roundtrip(
    original_neo: bytes,
    rebuilt_neo: bytes,
) -> VerifyResult:
    """
    Compare ROM data regions of two .neo files (headers are ignored).
    Returns a VerifyResult.
    """
    orig_data = original_neo[NEO_HEADER_SIZE:]
    new_data  = rebuilt_neo[NEO_HEADER_SIZE:]

    orig_md5 = hashlib.md5(orig_data).hexdigest()
    new_md5  = hashlib.md5(new_data).hexdigest()
    size_match = len(original_neo) == len(rebuilt_neo)
    data_match = orig_data == new_data

    if data_match:
        details = "ROM data regions are byte-identical. Extraction is lossless."
    else:
        # Find first difference
        for i, (a, b) in enumerate(zip(orig_data, new_data)):
            if a != b:
                details = (
                    f"First difference at ROM offset 0x{i:X} "
                    f"(file offset 0x{NEO_HEADER_SIZE + i:X}). "
                    f"Original: {orig_data[i:i+8].hex()}  "
                    f"Rebuilt:  {new_data[i:i+8].hex()}"
                )
                break
        else:
            details = "Data regions differ in length."

    return VerifyResult(
        ok=data_match,
        original_rom_md5=orig_md5,
        rebuilt_rom_md5=new_md5,
        file_size_match=size_match,
        details=details,
    )


# ---------------------------------------------------------------------------
# High-level convenience functions
# ---------------------------------------------------------------------------

def neo_to_mame_zip(neo_path: Path, prefix: str) -> bytes:
    """Extract a .neo file and return a MAME-format ZIP as bytes."""
    return extract_neo_to_zip(neo_path.read_bytes(), name_prefix=prefix, fmt="mame")


def neo_to_darksoft_zip(neo_path: Path, prefix: str) -> bytes:
    """Extract a .neo file and return a Darksoft-format ZIP as bytes."""
    return extract_neo_to_zip(neo_path.read_bytes(), name_prefix=prefix, fmt="darksoft")


def _apply_swap_p(romset: "RomSet", swap_p: "bool | str", verbose: bool = True) -> "RomSet":
    """
    Apply P-ROM bank swap according to *swap_p*:

    - ``True``   : always swap (legacy ``--swap-p`` flag)
    - ``False``  : never swap
    - ``"auto"`` : call :func:`detect_swap_p_needed` and swap only when the
                   heuristic says so; prints a short diagnostic line if *verbose*.

    Returns the (possibly modified) romset.
    """
    if swap_p == "auto":
        needed, reason = detect_swap_p_needed(romset.p)
        if verbose:
            tag = "auto-swap: YES —" if needed else "auto-swap: no  —"
            print(f"  {tag} {reason}")
        if needed:
            romset.p = swap_p_banks(romset.p)
    elif swap_p:
        romset.p = swap_p_banks(romset.p)
    return romset


def mame_zip_to_neo(
    zip_path: Path,
    meta: NeoMeta,
    swap_p: "bool | str" = False,
    diagnostic: bool = False,
    swap_verbose: bool = True,
) -> bytes:
    """Convert a MAME ROM zip to a .neo binary.

    Parameters
    ----------
    swap_p : False  → no swap (default)
             True   → always swap
             "auto" → heuristic detection via :func:`detect_swap_p_needed`
    swap_verbose
        If True (default), print auto-detect diagnostics for ``swap_p="auto"``.
    """
    romset = parse_mame_zip(zip_path, diagnostic=diagnostic)
    romset = _apply_swap_p(romset, swap_p, verbose=swap_verbose)
    return build_neo(romset, meta)


def mame_dir_to_neo(
    dir_path: Path,
    meta: NeoMeta,
    swap_p: "bool | str" = False,
    diagnostic: bool = False,
    swap_verbose: bool = True,
) -> bytes:
    """Convert a directory of MAME ROM files to a .neo binary.

    Parameters
    ----------
    swap_p : False  → no swap (default)
             True   → always swap
             "auto" → heuristic detection via :func:`detect_swap_p_needed`
    swap_verbose
        If True (default), print auto-detect diagnostics for ``swap_p="auto"``.
    """
    romset = parse_mame_dir(dir_path, diagnostic=diagnostic)
    romset = _apply_swap_p(romset, swap_p, verbose=swap_verbose)
    return build_neo(romset, meta)
