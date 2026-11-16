"""Parse MAME-style ZIP archives and loose ROM directories into a :class:`RomSet`."""

from __future__ import annotations

import re
import warnings
import zipfile
import zlib
from pathlib import Path
from typing import Iterable, Optional

from .constants import (
    _RE_C_LETTER_SPLIT,
    _RE_SYNTH_S_C1R_OR_C2R_CHIP,
    _RE_SYNTH_S_KF10_BOOTLEG,
    _SYNTH_S_MAME_512K_SET_IDS,
)
from .exceptions import InvalidRomLayoutError, UnsupportedRomSetError
from .interleave import interleave_c_chips
from .models import RomSet
from .unsupported import unsupported_set_reason


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
        if (
            fn.endswith(f"-{key}.bin")
            or fn.endswith(f"_{key}.bin")
            or stem.endswith(f"-{key}")
            or stem.endswith(f"_{key}")
        ):
            return role
    return None


def _c_letter_split_part(filename: str) -> Optional[tuple[str, str]]:
    """
    Map split C-chip basenames to ``(role, letter)``.

    Examples: ``kf10-c1a.bin`` → ``("C1", "a")``, ``5232-c2b.bin`` → ``("C2", "b")``.
    Native extensions such as ``.c1`` are not treated as splits (handled by
    :func:`name_to_role` first via the extension map).
    """
    fn = Path(filename).name
    stem = Path(fn).stem
    ext = Path(fn).suffix.lstrip(".").lower()
    if ext.startswith("c") and ext[1:].isdigit():
        return None
    m = _RE_C_LETTER_SPLIT.search(stem)
    if not m:
        return None
    return (f"C{int(m.group(1))}", m.group(2).lower())


def name_to_role(filename: str) -> Optional[str]:
    """
    Map a filename inside a MAME zip to its ROM role.
    Returns 'P', 'S', 'M', 'V1'..'V8', 'C1'..'C16', or None.

    C chips C9-C16 are supported for extended ROM sets (e.g. hacks/homebrews
    that exceed the standard 8-chip / 64 MB limit). The Neo Geo LSPC2 has a
    20-bit sprite address space, allowing up to 128 MB of C ROM (16 chips at
    8 MB each). No official SNK title uses more than C8, but the hardware
    address space permits it.
    """
    fn = Path(filename).name.lower()
    ext = Path(fn).suffix.lstrip(".")
    stem = Path(fn).stem

    ext_map = {
        "p1": "P",
        "p2": "P2",
        "s1": "S",
        "m1": "M",
        "v1": "V1",
        "v2": "V2",
        "v3": "V3",
        "v4": "V4",
        "v5": "V5",
        "v6": "V6",
        "v7": "V7",
        "v8": "V8",
        "c1": "C1",
        "c2": "C2",
        "c3": "C3",
        "c4": "C4",
        "c5": "C5",
        "c6": "C6",
        "c7": "C7",
        "c8": "C8",
        "c9": "C9",
        "c10": "C10",
        "c11": "C11",
        "c12": "C12",
        "c13": "C13",
        "c14": "C14",
        "c15": "C15",
        "c16": "C16",
    }
    if ext in ext_map:
        return ext_map[ext]

    # Name-based: look for -p1, -s1, -m1, -v1..v8, -c1..c8
    for key, role in ext_map.items():
        if (
            fn.endswith(f"-{key}.bin")
            or fn.endswith(f"_{key}.bin")
            or stem.endswith(f"-{key}")
            or stem.endswith(f"_{key}")
        ):
            return role

    # Split C chips: kf10-c1a.bin / 5232-c2b.bin → C1 / C2 (parts merged later).
    split = _c_letter_split_part(filename)
    if split is not None:
        return split[0]
    return None


def _filenames_imply_c1_sprite_rom(filenames: tuple[str, ...]) -> bool:
    """
    True if the input looks like it includes a Neo Geo C1 sprite ROM.

    MAME uses several naming schemes (``253-c1.c1``, ``mart-c1.bin``,
    ``kf10-c1a.bin``).
    """
    for p in filenames:
        n = Path(p).name
        if name_to_role(n) == "C1":
            return True
        nl = n.lower()
        if re.search(r"[-_]c1[a-z0-9]*\.(?:c1|bin)\b", nl):
            return True
    return False


def iter_mame_dir_rom_files(dir_path: Path) -> list[Path]:
    """
    ROM files in *dir_path* and its immediate subdirectories (one level).

    Covers the common layout after unzipping a MAME set into a folder.
    """
    files: list[Path] = []
    for entry in sorted(dir_path.iterdir()):
        if entry.is_file():
            files.append(entry)
        elif entry.is_dir():
            for sub in sorted(entry.iterdir()):
                if sub.is_file():
                    files.append(sub)
    return files


def collect_pack_sequence_issues(filenames: Iterable[str]) -> list[str]:
    """
    Detect gaps in V1..V8 or C1..C16 numbering from input filenames.

    Used for Pack preflight (GUI) before :func:`roles_to_romset` would raise.
    """
    found: set[str] = set()
    for raw in filenames:
        role = name_to_role(raw)
        if role:
            found.add(role)
    issues: list[str] = []
    for prefix, max_n in (("V", 8), ("C", 16)):
        present = [i for i in range(1, max_n + 1) if f"{prefix}{i}" in found]
        if not present:
            continue
        last = present[-1]
        for i in range(1, last):
            if f"{prefix}{i}" not in found:
                issues.append(
                    f"{prefix}{i} ROM missing but {prefix}{last} is present "
                    "(gap in ROM sequence)"
                )
    return issues


def collect_pack_psm_roles_for_validation(
    filenames: Iterable[str],
    *,
    allow_synthetic_s: bool = False,
) -> set[str]:
    """
    P/S/M roles satisfied for Pack validation, matching the pack defaults.

    A set with no physical ``s1`` is *not* reported as having ``S`` by default,
    because pack now refuses to inject a zero-filled S unless the user enables
    ``allow_synthetic_s`` (CLI: ``--allow-synthetic-s``). When that escape
    hatch is on, a MAME ``fixed``-style zero fill is still treated as present
    for preflight so the Pack tab can reach the real pack step.
    """
    names = tuple(filenames)
    roles: set[str] = set()
    for n in names:
        r = pack_psm_role_from_basename(n)
        if r:
            roles.add(r)
    if (
        allow_synthetic_s
        and "S" not in roles
        and _should_inject_synthetic_s_rom(names, roles)
    ):
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

    Matching uses filename regexes (not arbitrary substrings) so unrelated
    names such as ``game-c1r2.bin`` do not trigger the ``c1r`` PVC branch.
    """
    for p in filenames:
        if _RE_SYNTH_S_KF10_BOOTLEG.match(Path(p).name):
            return 0x40000
    for p in filenames:
        if _RE_SYNTH_S_C1R_OR_C2R_CHIP.search(Path(p).name):
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
    allow_synthetic_s: bool,
) -> bool:
    """Inject zero-filled S when explicitly allowed. Returns True if injected."""
    if not allow_synthetic_s or roles.get("S") or source_filenames is None:
        return False
    names = source_filenames
    psm = {r for n in names if (r := pack_psm_role_from_basename(n))}
    if not _should_inject_synthetic_s_rom(names, psm):
        return False
    size = _synthetic_zero_s_size_from_filenames(names)
    roles["S"] = b"\x00" * size
    warnings.warn(
        f"No text-layer ROM (s1) in {source}; using {size // 1024} KiB zero fill "
        "as a MAME softlist-shaped placeholder because --allow-synthetic-s is "
        "enabled. The resulting .neo is NOT playable on TerraOnion / MiSTer "
        "hardware (missing or corrupt text/fix layer). Prefer a set that ships "
        "a real s1 (e.g. the svcboot bootleg), or repair S from a known-good "
        ".neo.",
        UserWarning,
        stacklevel=3,
    )
    return True


# Cap long ignored-file lists so layout errors stay readable.
_MAX_EXTRA_FILES_IN_MESSAGE = 12

# Recognized-but-unmapped ROM naming patterns. ``--allow-extra-files`` must
# never drop these because doing so can truncate P/V/C data.
_RE_ROM_ROLE_SUFFIX = re.compile(
    r"\.(?:p[0-9]+[a-z]*|sp[0-9]+[a-z]*|ep[0-9a-z]*|s[1-9]|m[1-9]|v[0-9]+[a-z]*|c[0-9]+[a-z]*|neo-sma)$",
    re.IGNORECASE,
)
_RE_ROM_ROLE_IN_STEM = re.compile(
    r"(?:^|[-_])(?:p[0-9]+[a-z]*|sp[0-9]+[a-z]*|ep[0-9]+|epr|s[1-9]|m[1-9]|v[0-9]+[a-z]*|c[0-9]+[a-z]*)$",
    re.IGNORECASE,
)
_ROM_DATA_SUFFIXES = frozenset({".bin", ".rom"})

# BIOS files that may sit beside a MAME/FBNeo set. They are ignored before
# role classification so e.g. ``sm1.sm1`` cannot be mistaken for the game M ROM.
_KNOWN_BIOS_FILES = frozenset({
    "000-lo.lo",
    "sfix.sfix",
    "sm1.sm1",
    "sp-s2.sp1",
    "sp-s.sp1",
    "sp-45.sp1",
    "sp-s3.sp1",
    "sp-u2.sp1",
    "sp-e.sp1",
    "sp1-u2",
    "sp1-u4.bin",
    "sp1-u3.bin",
    "vs-bios.rom",
    "sp-j2.sp1",
    "sp1.jipan.1024",
    "japan-j3.bin",
    "sp1-j3.bin",
    "sp-j3.sp1",
    "sp-1v1_3db8c.bin",
    "asia-s3.rom",
    "neo-epo.bin",
})
_RE_UNI_BIOS_ROM = re.compile(r"^uni-bios_.*\.rom$", re.IGNORECASE)


def is_known_bios_file(filename: str) -> bool:
    """True when *filename* is a known Neo Geo BIOS file (case-insensitive)."""
    name = Path(filename).name.lower()
    return name in _KNOWN_BIOS_FILES or bool(_RE_UNI_BIOS_ROM.match(name))


# MAME ADPCM-A/B V-chip naming (``001-v11.v11`` / ``001-v21.v21``). These are
# flattened 16-bit V-ROM layouts, not the standard byte-wide v1..v8 chips, and
# mapping them as ordinary V data would produce a wrong audio region.
_RE_ADPCM_V_CHIP_STEM = re.compile(r"(?:^|[-_])v(?:11|21)$", re.IGNORECASE)
_RE_ADPCM_V_CHIP_EXT = re.compile(r"^v(?:11|21)$", re.IGNORECASE)


def _is_adpcm_ab_v_chip(filename: str) -> bool:
    """True for ADPCM-A/B ``v11`` / ``v21`` chip names that need a region map."""
    path = Path(filename)
    suffix = path.suffix.lstrip(".")
    if _RE_ADPCM_V_CHIP_EXT.match(suffix):
        return True
    return bool(_RE_ADPCM_V_CHIP_STEM.search(path.stem))


def _looks_like_neo_geo_rom(filename: str) -> bool:
    """
    True when an *unrecognized* filename still looks like Neo Geo ROM data.

    Used to stop ``--allow-extra-files`` from dropping renamed or truncated
    ROMs. Only clearly non-ROM extras (README, ``.txt``, ``.dat``, …) may be
    ignored with that flag.
    """
    name = Path(filename).name
    if _RE_ROM_ROLE_SUFFIX.search(name):
        return True
    suffix = Path(name).suffix.lower()
    if suffix in _ROM_DATA_SUFFIXES:
        return bool(_RE_ROM_ROLE_IN_STEM.search(Path(name).stem))
    if not suffix:
        # Bare MAME prototype names such as ``p1`` / ``v1`` / ``c1``.
        return bool(_RE_ROM_ROLE_IN_STEM.search(name))
    return False


def _format_file_list(names: list[str]) -> str:
    shown = ", ".join(f"'{n}'" for n in names[:_MAX_EXTRA_FILES_IN_MESSAGE])
    remaining = len(names) - _MAX_EXTRA_FILES_IN_MESSAGE
    if remaining > 0:
        shown += f", … (+{remaining} more)"
    noun = "file" if len(names) == 1 else "files"
    return f"{shown} ({len(names)} {noun})"


def roles_to_romset(
    roles: dict[str, bytes],
    source: str = "",
    *,
    source_filenames: tuple[str, ...] | None = None,
    allow_extra_files: bool = False,
    allow_synthetic_s: bool = False,
    ignored: Iterable[str] | None = None,
) -> RomSet:
    """
    Build a RomSet from a dict mapping role strings to raw bytes.

    Raises :class:`~neoconv.core.InvalidRomLayoutError` for missing or empty
    mandatory ROMs, unrecognized input files, or malformed C chip counts.

    When ``source_filenames`` is provided (ZIP member paths or directory
    basenames), files that do not map to a Neo Geo role are rejected by
    default so they cannot be silently dropped. ``allow_extra_files=True``
    permits clearly non-ROM extras (README, ``.txt``, ``.dat``, …) with a
    warning; names that still look like ROM data stay hard errors.

    Boards without a physical s1 ROM can receive a zero-filled synthetic S
    region matching MAME's ``fixed`` area *size* only when
    ``allow_synthetic_s=True``. That placeholder is **not** hardware-correct on
    TerraOnion / MiSTer (see the ``UserWarning`` emitted on injection).
    """
    roles = dict(roles)
    if ignored is None and source_filenames is not None:
        ignored = [
            name
            for name in source_filenames
            if _c_letter_split_part(name) is None and name_to_role(name) is None
        ]
    ignored = list(ignored or ())
    adpcm_v = [name for name in ignored if _is_adpcm_ab_v_chip(name)]
    if adpcm_v:
        raise InvalidRomLayoutError(
            f"ADPCM-A/B V-chip naming in {source or 'input'}: "
            f"{_format_file_list(adpcm_v)}. MAME sets that use v11/v21-style "
            "V chips need the region/layout engine, which is not implemented "
            "yet, so packing is refused even with --allow-extra-files.",
            hint=(
                "Only standard v1..v8 ADPCM ROM sets are supported. Use a set "
                "with v1..v8 naming, or start from an existing .neo."
            ),
        )
    if ignored and not allow_extra_files:
        raise InvalidRomLayoutError(
            f"Unrecognized file(s) in {source or 'input'}: "
            f"{_format_file_list(ignored)}. Packing would drop them from the "
            ".neo, which can truncate the program or sprite data, so it is "
            "refused by default.",
            hint=(
                "Rename the files to Neo Geo role names (p1/s1/m1/v1/c1…) or "
                "pass --allow-extra-files (GUI: \"Allow extra files\") to pack "
                "without clearly non-ROM extras."
            ),
        )
    rom_like = [name for name in ignored if _looks_like_neo_geo_rom(name)]
    if rom_like:
        raise InvalidRomLayoutError(
            f"Unrecognized file(s) in {source or 'input'} that look like Neo "
            f"Geo ROM data: {_format_file_list(rom_like)}. "
            "--allow-extra-files only ignores clearly non-ROM extras; dropping "
            "these could truncate the program or sprite data, so packing is "
            "refused.",
            hint=(
                "Check the names against the expected p1/p2, s1, m1, v1…, "
                "c1… roles. Rename/repack them, or remove the extra ROM data "
                "explicitly; the allow flag cannot override this."
            ),
        )
    if ignored:
        warnings.warn(
            f"Ignoring {_format_file_list(ignored)} in {source or 'input'} "
            "because extra files are allowed; the .neo will not contain them.",
            UserWarning,
            stacklevel=3,
        )

    injected_s = _inject_synthetic_s_rom_if_needed(
        roles, source, source_filenames, allow_synthetic_s
    )
    missing = [r for r in ("P", "S", "M") if not roles.get(r)]
    if missing:
        tips_by_role = {
            "P": "P program ROM missing (expected p1/p2, e.g. game-p1.bin or game.p1)",
            "S": "S ROM missing (expected s1, e.g. game-s1.bin or game.s1)",
            "M": "M ROM missing (expected m1, e.g. game-m1.bin or game.m1)",
        }
        tips = "; ".join(tips_by_role[r] for r in missing)
        hint = None
        if "S" in missing and source_filenames is not None:
            names = tuple(source_filenames)
            psm = {r for n in names if (r := pack_psm_role_from_basename(n))}
            if _should_inject_synthetic_s_rom(names, psm):
                if allow_synthetic_s:
                    hint = (
                        "Synthetic S was requested but could not be generated "
                        "for this input. Check the p1/m1 and c1 file layout "
                        "instead of enabling the flag again."
                    )
                else:
                    hint = (
                        "This set has no physical s1 ROM. Pass "
                        "--allow-synthetic-s (GUI: \"Allow synthetic S\") only "
                        "if you accept a non-playable zero-filled text layer."
                    )
        raise InvalidRomLayoutError(
            f"Missing mandatory ROM(s) in {source or 'input'}: "
            f"{', '.join(missing)}. "
            f"Quick tips: {tips}. "
            "Use --diagnostic to list unrecognized filenames.",
            hint=hint,
        )

    p_rom = roles.get("P", b"") + roles.get("P2", b"")
    s_rom = roles["S"]
    m_rom = roles["M"]

    v_rom = b""
    for i in range(1, 9):
        chunk = roles.get(f"V{i}", b"")
        if chunk:
            v_rom += chunk
        elif any(roles.get(f"V{j}") for j in range(i + 1, 9)):
            raise InvalidRomLayoutError(
                f"V{i} ROM missing but higher-numbered V chips are present "
                f"(gap in V ROM sequence). This is likely a naming error. "
                f"Expected e.g. game-v{i}.bin or game.v{i}."
            )

    c_chips_raw: list[bytes] = []
    for i in range(1, 17):
        chip = roles.get(f"C{i}", b"")
        if chip:
            c_chips_raw.append(chip)
        elif any(roles.get(f"C{j}") for j in range(i + 1, 17)):
            raise InvalidRomLayoutError(
                f"C{i} ROM missing but higher-numbered C chips are present "
                f"(gap in C ROM sequence). This is likely a naming error. "
                f"Expected e.g. game-c{i}.bin or game.c{i}."
            )

    if injected_s and not c_chips_raw:
        raise InvalidRomLayoutError(
            f"No C sprite ROM data collected from {source or 'input'}, but a "
            "synthetic S-ROM was injected because filenames looked like a C1 "
            "set. Sprite chips were likely ignored due to unsupported naming. "
            "Use --diagnostic to list unrecognized filenames."
        )

    if c_chips_raw and len(c_chips_raw) % 2 != 0:
        raise InvalidRomLayoutError(
            f"Odd number of C chips ({len(c_chips_raw)}) in {source or 'input'}. "
            "C chips must come in pairs (c1+c2, c3+c4, ...)."
        )

    # Validate C chip sizes
    for i in range(0, len(c_chips_raw), 2):
        a, b = c_chips_raw[i], c_chips_raw[i + 1]
        if len(a) != len(b):
            raise InvalidRomLayoutError(
                f"C chip pair c{i+1}/c{i+2} size mismatch: {len(a)} vs {len(b)} bytes."
            )
        if len(a) % (512 * 1024) != 0:
            raise InvalidRomLayoutError(
                f"C chip c{i+1} size ({len(a):,} bytes) is not a multiple of 512 KB. "
                "The ROM data may be corrupt or incorrectly split."
            )

    if not v_rom:
        raise InvalidRomLayoutError(
            f"No V (audio) ROM data in {source or 'input'}. Expected at least "
            "one v1..v8 file (e.g. game-v1.bin or game.v1). Refusing to build "
            "a .neo with an empty V region.",
            hint="Use --diagnostic to list unrecognized filenames.",
        )

    if not c_chips_raw:
        raise InvalidRomLayoutError(
            f"No C (sprite) ROM data in {source or 'input'}. Expected c1/c2 … "
            "sprite chips (e.g. game-c1.bin or game.c1). Refusing to build a "
            ".neo with an empty C region.",
            hint="Use --diagnostic to list unrecognized filenames.",
        )

    c_rom = interleave_c_chips(c_chips_raw)
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
        raise InvalidRomLayoutError(
            f"Duplicate ROM role '{role}' in input: '{source_name}'. "
            "Each role (P/S/M/Vx/Cx) must map to exactly one file."
        )
    roles[role] = data


def _store_c_letter_part(
    c_parts: dict[str, dict[str, bytes]],
    roles: dict[str, bytes],
    role: str,
    letter: str,
    data: bytes,
    source_name: str,
) -> None:
    """Accumulate a letter-split C chip part (``c1a``, ``c1b``, …)."""
    if role in roles:
        raise InvalidRomLayoutError(
            f"Duplicate ROM role '{role}' in input: '{source_name}'. "
            "Cannot mix a complete C chip file with split parts (cNa/cNb)."
        )
    parts = c_parts.setdefault(role, {})
    if letter in parts:
        raise InvalidRomLayoutError(
            f"Duplicate split C part '{role}{letter}' in input: '{source_name}'."
        )
    parts[letter] = data


def _flush_c_letter_parts(
    c_parts: dict[str, dict[str, bytes]],
    roles: dict[str, bytes],
) -> None:
    """
    Concatenate letter-split C parts in alphabetical order into *roles*.

    Letters must be contiguous from ``a``: silently sorting and joining
    ``c1a`` + ``c1c`` would drop the bytes a missing ``c1b`` should have
    supplied, so such gaps are rejected instead.
    """
    for role, parts in sorted(c_parts.items(), key=lambda item: item[0]):
        letters = sorted(parts)
        last = letters[-1]
        expected = [chr(ord("a") + i) for i in range(ord(last) - ord("a") + 1)]
        missing = [letter for letter in expected if letter not in parts]
        if missing:
            chip = f"c{role[1:].lower()}"
            found = ", ".join(f"{chip}{letter}" for letter in letters)
            absent = ", ".join(f"{chip}{letter}" for letter in missing)
            raise InvalidRomLayoutError(
                f"Split C chip {role} is missing part(s): {absent} "
                f"(found {found}).",
                hint=(
                    "Letter-split C parts must be contiguous from 'a' "
                    "(c1a, c1b, c1c, …) so the merged chip keeps the correct "
                    "byte order. Add the missing part(s) or use a complete "
                    f"{chip} file."
                ),
            )
        merged = b"".join(parts[letter] for letter in letters)
        label = "+".join(f"c{role[1:].lower()}{letter}" for letter in letters)
        _store_role_data(roles, role, merged, f"merged ({label})", False)


def _ingest_named_rom(
    filename: str,
    data: bytes,
    roles: dict[str, bytes],
    c_parts: dict[str, dict[str, bytes]],
    ignored: list[str],
    diagnostic: bool,
) -> None:
    """Classify one ROM file into *roles*, letter-split *c_parts*, or *ignored*."""
    split = _c_letter_split_part(filename)
    if split is not None:
        role, letter = split
        _store_c_letter_part(c_parts, roles, role, letter, data, filename)
        return
    role = name_to_role(filename)
    if role is not None:
        _store_role_data(roles, role, data, filename, diagnostic)
    else:
        ignored.append(filename)


def _romset_from_collected_roles(
    roles: dict[str, bytes],
    c_parts: dict[str, dict[str, bytes]],
    ignored: list[str],
    all_names: list[str],
    source: str,
    diagnostic: bool,
    allow_extra_files: bool = False,
    allow_synthetic_s: bool = False,
) -> RomSet:
    """Flush split C parts, emit diagnostic warnings, build a RomSet."""
    _flush_c_letter_parts(c_parts, roles)
    if diagnostic and ignored:
        for fn in ignored:
            warnings.warn(
                f"[diagnostic] Unrecognized file ignored: '{fn}' — "
                "check naming (expected e.g. game-p1.bin, game-c1.c1, ...)",
                stacklevel=3,
            )
    return roles_to_romset(
        roles,
        source=source,
        source_filenames=tuple(all_names),
        allow_extra_files=allow_extra_files,
        allow_synthetic_s=allow_synthetic_s,
        ignored=ignored,
    )


def _reject_unsupported_set(set_name: str) -> None:
    """Fail early for known encrypted/protected/4-chip-C MAME sets."""
    reason = unsupported_set_reason(set_name)
    if reason is None:
        return
    raise UnsupportedRomSetError(
        f"MAME set '{set_name}' is not supported yet: {reason}. Packing it "
        "now would produce a wrong or incomplete .neo, so it is refused.",
        hint=(
            "Support requires the deferred layout/decrypt work. Use a "
            "known-good .neo or an unencrypted bootleg set in the meantime."
        ),
    )


def parse_mame_zip(
    zip_path: Path,
    diagnostic: bool = False,
    *,
    allow_extra_files: bool = False,
    allow_synthetic_s: bool = False,
) -> RomSet:
    """Parse a MAME ROM zip and return a RomSet.

    Parameters
    ----------
    zip_path   : path to the ZIP file
    diagnostic : if True, print a warning for every file that was not
                 recognized, so the user can diagnose naming issues.
    allow_extra_files
                 if True, ignore clearly non-ROM extras (README, .txt, .dat, …)
                 with a warning instead of failing. ROM-like extras still
                 raise. Defaults to False to prevent silent data loss.
    allow_synthetic_s
                 if True, inject a zero-filled S region for MAME boards that
                 have no s1 ROM. Defaults to False (missing S is an error).

    Raises
    ------
    UnsupportedRomSetError
        When the ZIP stem names a known encrypted/protected/4-chip-C set.
    InvalidRomLayoutError
        For unrecognized files (unless allowed), missing/empty P/S/M/V/C,
        malformed C chips, duplicate role members, or a ZIP that cannot be
        opened or whose members cannot be decompressed (corrupt, encrypted, or
        unsupported compression).
    """
    _reject_unsupported_set(zip_path.stem)
    roles: dict[str, bytes] = {}
    c_parts: dict[str, dict[str, bytes]] = {}
    ignored: list[str] = []
    all_names: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in zf.infolist():
                if entry.is_dir() or is_known_bios_file(entry.filename):
                    continue
                all_names.append(entry.filename)
                # Read the entry itself, not by name: duplicate member names
                # would otherwise resolve to a different (usually last) entry.
                with zf.open(entry) as member:
                    data = member.read()
                _ingest_named_rom(
                    entry.filename,
                    data,
                    roles,
                    c_parts,
                    ignored,
                    diagnostic,
                )
    except (zipfile.BadZipFile, zlib.error, RuntimeError) as e:
        raise InvalidRomLayoutError(f"Cannot open ZIP file '{zip_path}': {e}") from e

    return _romset_from_collected_roles(
        roles,
        c_parts,
        ignored,
        all_names,
        str(zip_path),
        diagnostic,
        allow_extra_files=allow_extra_files,
        allow_synthetic_s=allow_synthetic_s,
    )


def read_p_rom_from_zip(zip_path: Path) -> bytes:
    """
    Read only the P-ROM data from a MAME-style ZIP.

    Intended for inspection commands such as ``detect-swap`` that need nothing
    but the program ROM. Members are classified with :func:`name_to_role`;
    only ``P`` (``p1``) and ``P2`` (``p2``) members are read and concatenated
    (P followed by P2). Other members are ignored entirely, and neither the
    mandatory P/S/M/V/C gate nor the known-unsupported-set denylist applies,
    so a P-only ZIP is enough.

    Raises
    ------
    InvalidRomLayoutError
        When the ZIP cannot be opened or a member cannot be decompressed
        (corrupt, encrypted, or unsupported compression), when a role appears
        more than once, or when no P/P2 member exists.
    """
    p_parts: list[bytes] = []
    p2_parts: list[bytes] = []
    p_seen: Optional[str] = None
    p2_seen: Optional[str] = None
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in zf.infolist():
                if entry.is_dir():
                    continue
                role = name_to_role(entry.filename)
                if role not in ("P", "P2"):
                    continue
                previous = p_seen if role == "P" else p2_seen
                if previous is not None:
                    raise InvalidRomLayoutError(
                        f"Duplicate {role} ROM in ZIP '{zip_path}': members "
                        f"'{previous}' and '{entry.filename}' map to the same role."
                    )
                # Read this exact entry so duplicate member names cannot be
                # silently routed through a different one.
                with zf.open(entry) as member:
                    data = member.read()
                if role == "P":
                    p_seen = entry.filename
                    p_parts.append(data)
                else:
                    p2_seen = entry.filename
                    p2_parts.append(data)
    except (zipfile.BadZipFile, zlib.error, RuntimeError) as e:
        raise InvalidRomLayoutError(f"Cannot open ZIP file '{zip_path}': {e}") from e

    if not p_parts:
        raise InvalidRomLayoutError(
            f"No P (program) ROM in ZIP '{zip_path}'. Expected a p1 member "
            "(e.g. game-p1.bin or game.p1).",
            hint="detect-swap only needs the P-ROM; check the ZIP contains one.",
        )
    return b"".join(p_parts) + b"".join(p2_parts)


def parse_mame_dir(
    dir_path: Path,
    diagnostic: bool = False,
    *,
    allow_extra_files: bool = False,
    allow_synthetic_s: bool = False,
) -> RomSet:
    """Parse a directory of raw ROM files and return a RomSet.

    Parameters
    ----------
    dir_path   : directory containing ROM files
    diagnostic : if True, print a warning for every file that was not
                 recognized, so the user can diagnose naming issues.
    allow_extra_files
                 if True, ignore clearly non-ROM extras (README, .txt, .dat, …)
                 with a warning instead of failing. ROM-like extras still
                 raise. Defaults to False to prevent silent data loss.
    allow_synthetic_s
                 if True, inject a zero-filled S region for MAME boards that
                 have no s1 ROM. Defaults to False (missing S is an error).

    Notes
    -----
    Files in the top-level directory and one level of subdirectories are
    included (typical unzip layout). Entries are processed in sorted order so
    diagnostics and ``source_filenames`` metadata are reproducible.

    Raises
    ------
    UnsupportedRomSetError
        When the directory basename names a known encrypted/protected/4-chip-C
        set.
    InvalidRomLayoutError
        For unrecognized files (unless allowed), missing/empty P/S/M/V/C, or
        malformed C chips.
    """
    _reject_unsupported_set(dir_path.resolve().name)
    roles: dict[str, bytes] = {}
    c_parts: dict[str, dict[str, bytes]] = {}
    ignored: list[str] = []
    all_names: list[str] = []
    for f in iter_mame_dir_rom_files(dir_path):
        if is_known_bios_file(f.name):
            continue
        all_names.append(f.name)
        _ingest_named_rom(f.name, f.read_bytes(), roles, c_parts, ignored, diagnostic)

    return _romset_from_collected_roles(
        roles,
        c_parts,
        ignored,
        all_names,
        str(dir_path),
        diagnostic,
        allow_extra_files=allow_extra_files,
        allow_synthetic_s=allow_synthetic_s,
    )
