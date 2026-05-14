"""Shared constants and small compiled patterns for Neo Geo / .neo handling."""

from __future__ import annotations

import re

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

# Synthetic S-ROM size heuristics (see mame_parse._synthetic_zero_s_size_from_filenames).
_RE_SYNTH_S_KF10_BOOTLEG = re.compile(r"^kf10[-_]", re.IGNORECASE)
# Require ``c1r.`` / ``c2r.`` so stems like ``game-c1r2`` do not match ``c1r``.
_RE_SYNTH_S_C1R_OR_C2R_CHIP = re.compile(
    r"[-_]c1r\.(?:c1|bin)\b|[-_]c2r\.(?:c2|bin)\b",
    re.IGNORECASE,
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
