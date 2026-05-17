"""Parse MAME-style ZIP archives and loose ROM directories into a :class:`RomSet`."""

from __future__ import annotations

import re
import warnings
import zipfile
from pathlib import Path
from typing import Iterable, Optional

from .constants import (
    _RE_SYNTH_S_C1R_OR_C2R_CHIP,
    _RE_SYNTH_S_KF10_BOOTLEG,
    _SYNTH_S_MAME_512K_SET_IDS,
)
from .interleave import interleave_c_chips
from .models import RomSet


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
    return None


def _filenames_imply_c1_sprite_rom(filenames: tuple[str, ...]) -> bool:
    """
    True if the input looks like it includes a Neo Geo C1 sprite ROM.

    MAME uses several naming schemes (``253-c1.c1``, ``mart-c1.bin``,
    ``kf10-c1a.bin``); :func:`name_to_role` only covers the common forms.
    """
    for p in filenames:
        n = Path(p).name
        if name_to_role(n) == "C1":
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


def roles_to_romset(
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
        if chunk:
            v_rom += chunk
        elif any(roles.get(f"V{j}") for j in range(i + 1, 9)):
            raise ValueError(
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
            raise ValueError(
                f"C{i} ROM missing but higher-numbered C chips are present "
                f"(gap in C ROM sequence). This is likely a naming error. "
                f"Expected e.g. game-c{i}.bin or game.c{i}."
            )

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

    c_rom = interleave_c_chips(c_chips_raw) if c_chips_raw else b""
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
                role = name_to_role(entry.filename)
                if role is not None:
                    _store_role_data(
                        roles, role, zf.read(entry.filename), entry.filename, diagnostic
                    )
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

    return roles_to_romset(roles, source=str(zip_path), source_filenames=tuple(all_names))


def parse_mame_dir(dir_path: Path, diagnostic: bool = False) -> RomSet:
    """Parse a directory of raw ROM files and return a RomSet.

    Parameters
    ----------
    dir_path   : directory containing ROM files
    diagnostic : if True, print a warning for every file that was not
                 recognized, so the user can diagnose naming issues.

    Notes
    -----
    Directory entries are processed in sorted path order so diagnostics and
    ``source_filenames`` metadata are reproducible across platforms.
    """
    roles: dict[str, bytes] = {}
    ignored: list[str] = []
    all_names: list[str] = []
    for f in sorted(dir_path.iterdir()):
        if f.is_file():
            all_names.append(f.name)
            role = name_to_role(f.name)
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

    return roles_to_romset(roles, source=str(dir_path), source_filenames=tuple(all_names))
