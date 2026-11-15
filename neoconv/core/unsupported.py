"""
Known MAME Neo Geo sets that neoconv cannot pack correctly yet.

Packing these sets with the current 16-bit C interleaver and without the
deferred layout/decrypt engine produces a wrong or incomplete ``.neo``. The
stopgap is to reject them by set name (ZIP stem / directory basename) before
any member is read, instead of silently emitting a corrupt file.

Regenerate the list from MAME master ``neogeo.xml`` (307 software entries):

* ``encrypted-rom`` (47): sets with a
  ``<feature name="slot" value="cmc42_*|cmc50_*|pvc_*|sma_*|pcm2_*|k2k2_*">``
  encryption slot.
* ``protected-rom`` (7): ROM-level copy-protection MCUs / protected program
  ROMs (``fatfury2``, ``ssideki``, ``kof98*``, ``mslugx``).
* ``c-part-layout`` (9): prototype/early 4-chip C layouts (``load32_byte``)
  that the current pairwise interleaver cannot split correctly, including
  ``kotm2p``, ``viewpoinp`` and ``stakwindev``.
* ``audiocrypt`` (4): ``audiocrypt`` data area without an encryption slot
  (``kf2k2mp``, ``kf2k2mp2``, ``kof2002b``, ``ms5plus``).

Total: 67 sets. Bootlegs whose names start with ``boot_`` are intentionally
not listed; they use standard unencrypted layouts.
"""

from __future__ import annotations

UNSUPPORTED_ENCRYPTED_ROM = "encrypted-rom"
UNSUPPORTED_PROTECTED_ROM = "protected-rom"
UNSUPPORTED_C_PART_LAYOUT = "c-part-layout"
UNSUPPORTED_AUDIOCRYPT = "audiocrypt"

# Set name (lower-case) -> reason category.
UNSUPPORTED_MAME_SETS: dict[str, str] = {
    # Encryption-slot sets (CMC42 / CMC50 / PVC / SMA / PCM2 / K2K2).
    "bangbead": UNSUPPORTED_ENCRYPTED_ROM,
    "ganryu": UNSUPPORTED_ENCRYPTED_ROM,
    "garou": UNSUPPORTED_ENCRYPTED_ROM,
    "garouh": UNSUPPORTED_ENCRYPTED_ROM,
    "garouha": UNSUPPORTED_ENCRYPTED_ROM,
    "jockeygp": UNSUPPORTED_ENCRYPTED_ROM,
    "jockeygpa": UNSUPPORTED_ENCRYPTED_ROM,
    "kf2k2pla": UNSUPPORTED_ENCRYPTED_ROM,
    "kf2k2pls": UNSUPPORTED_ENCRYPTED_ROM,
    "kof2000": UNSUPPORTED_ENCRYPTED_ROM,
    "kof2000n": UNSUPPORTED_ENCRYPTED_ROM,
    "kof2001": UNSUPPORTED_ENCRYPTED_ROM,
    "kof2001h": UNSUPPORTED_ENCRYPTED_ROM,
    "kof2002": UNSUPPORTED_ENCRYPTED_ROM,
    "kof2003": UNSUPPORTED_ENCRYPTED_ROM,
    "kof2003h": UNSUPPORTED_ENCRYPTED_ROM,
    "kof99": UNSUPPORTED_ENCRYPTED_ROM,
    "kof99e": UNSUPPORTED_ENCRYPTED_ROM,
    "kof99h": UNSUPPORTED_ENCRYPTED_ROM,
    "kof99k": UNSUPPORTED_ENCRYPTED_ROM,
    "kof99ka": UNSUPPORTED_ENCRYPTED_ROM,
    "matrim": UNSUPPORTED_ENCRYPTED_ROM,
    "ms4plus": UNSUPPORTED_ENCRYPTED_ROM,
    "mslug3": UNSUPPORTED_ENCRYPTED_ROM,
    "mslug3a": UNSUPPORTED_ENCRYPTED_ROM,
    "mslug3h": UNSUPPORTED_ENCRYPTED_ROM,
    "mslug4": UNSUPPORTED_ENCRYPTED_ROM,
    "mslug4h": UNSUPPORTED_ENCRYPTED_ROM,
    "mslug5": UNSUPPORTED_ENCRYPTED_ROM,
    "mslug5h": UNSUPPORTED_ENCRYPTED_ROM,
    "nitd": UNSUPPORTED_ENCRYPTED_ROM,
    "pnyaa": UNSUPPORTED_ENCRYPTED_ROM,
    "pnyaaa": UNSUPPORTED_ENCRYPTED_ROM,
    "preisle2": UNSUPPORTED_ENCRYPTED_ROM,
    "rotd": UNSUPPORTED_ENCRYPTED_ROM,
    "rotdh": UNSUPPORTED_ENCRYPTED_ROM,
    "s1945p": UNSUPPORTED_ENCRYPTED_ROM,
    "samsh5sp": UNSUPPORTED_ENCRYPTED_ROM,
    "samsh5sph": UNSUPPORTED_ENCRYPTED_ROM,
    "samsh5spho": UNSUPPORTED_ENCRYPTED_ROM,
    "samsho5": UNSUPPORTED_ENCRYPTED_ROM,
    "samsho5a": UNSUPPORTED_ENCRYPTED_ROM,
    "samsho5h": UNSUPPORTED_ENCRYPTED_ROM,
    "sengoku3": UNSUPPORTED_ENCRYPTED_ROM,
    "sengoku3a": UNSUPPORTED_ENCRYPTED_ROM,
    "svc": UNSUPPORTED_ENCRYPTED_ROM,
    "zupapa": UNSUPPORTED_ENCRYPTED_ROM,
    # ROM-protection sets (copy-protection MCU / protected program ROMs).
    "fatfury2": UNSUPPORTED_PROTECTED_ROM,
    "ssideki": UNSUPPORTED_PROTECTED_ROM,
    "kof98": UNSUPPORTED_PROTECTED_ROM,
    "kof98a": UNSUPPORTED_PROTECTED_ROM,
    "kof98k": UNSUPPORTED_PROTECTED_ROM,
    "kof98ka": UNSUPPORTED_PROTECTED_ROM,
    "mslugx": UNSUPPORTED_PROTECTED_ROM,
    # 4-chip C layouts (load32_byte prototypes / early boards).
    "alpham2p": UNSUPPORTED_C_PART_LAYOUT,
    "burningfpa": UNSUPPORTED_C_PART_LAYOUT,
    "burningfpb": UNSUPPORTED_C_PART_LAYOUT,
    "burningfp": UNSUPPORTED_C_PART_LAYOUT,
    "gpilotsp": UNSUPPORTED_C_PART_LAYOUT,
    "lresortp": UNSUPPORTED_C_PART_LAYOUT,
    "kotm2p": UNSUPPORTED_C_PART_LAYOUT,
    "viewpoinp": UNSUPPORTED_C_PART_LAYOUT,
    "stakwindev": UNSUPPORTED_C_PART_LAYOUT,
    # Encrypted audio only (no encryption slot on the program/sprite ROMs).
    "kf2k2mp": UNSUPPORTED_AUDIOCRYPT,
    "kf2k2mp2": UNSUPPORTED_AUDIOCRYPT,
    "kof2002b": UNSUPPORTED_AUDIOCRYPT,
    "ms5plus": UNSUPPORTED_AUDIOCRYPT,
}

_REASON_TEXT: dict[str, str] = {
    UNSUPPORTED_ENCRYPTED_ROM: (
        "its program/sprite ROMs are encrypted by a CMC42/CMC50/PVC/SMA/"
        "PCM2/K2K2 protection slot"
    ),
    UNSUPPORTED_PROTECTED_ROM: (
        "its program ROMs or MCU use ROM-level copy protection"
    ),
    UNSUPPORTED_C_PART_LAYOUT: (
        "it uses a 4-chip C (sprite) layout that the current pairwise "
        "interleaver cannot split correctly"
    ),
    UNSUPPORTED_AUDIOCRYPT: "its ADPCM audio ROMs are encrypted (audiocrypt)",
}


def unsupported_set_category(set_name: str) -> str | None:
    """Return the reason category for *set_name*, or ``None`` when supported."""
    return UNSUPPORTED_MAME_SETS.get(set_name.strip().lower())


def unsupported_set_reason(set_name: str) -> str | None:
    """Return a human-readable reason for *set_name*, or ``None``."""
    category = unsupported_set_category(set_name)
    if category is None:
        return None
    return _REASON_TEXT[category]
