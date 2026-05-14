"""
neoconv.core
~~~~~~~~~~~~
Core logic for converting between .neo container files and
MAME / Darksoft Neo Geo ROM sets.

Implementation is split across submodules under ``neoconv.core``; this
package re-exports the public API so ``from neoconv.core import …`` continues
to work unchanged.

The .neo format (TerraOnion NeoSD):
  Offset 0x000  Magic       b'NEO\\x01'  (4 bytes)
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
  Bytes are interleaved: even bytes → odd-numbered chips (c1, c3, …),
                         odd  bytes → even-numbered chips (c2, c4, …).

  The .neo container stores the total interleaved C data as one contiguous
  block. The original chip boundaries are NOT recorded in the header —
  de-interleaving requires knowing the individual chip size, which varies
  by game and must be looked up from the MAME/FBNeo ROM set.

  Common chip sizes found in the Neo Geo library (per chip, before interleaving):
    512 KB, 1 MB, 2 MB, 4 MB, 8 MB, 16 MB, 20 MB

  Use the --c-chip-size option to specify the correct chip size when extracting.
  Default is 2 MB, which covers the majority of titles.
"""

from __future__ import annotations

from .constants import (
    C_BANK_SIZE,
    C_CHIP_SIZE_DEFAULT,
    GENRE_BY_NAME,
    GENRES,
    NEO_HEADER_SIZE,
    NEO_MAGIC,
    P_SWAP_SIZE,
    V_BANK_SIZE,
)
from .extract import (
    extract_neo,
    extract_neo_to_zip,
    extract_romset,
    extract_romset_to_zip,
    neo_to_darksoft_zip,
    neo_to_mame_zip,
)
from .interleave import _interleave_c_chips
from .mame_parse import (
    collect_pack_psm_roles_for_validation,
    pack_psm_role_from_basename,
    parse_mame_dir,
    parse_mame_zip,
    _name_to_role,
    _roles_to_romset,
)
from .models import NeoMeta, RomSet
from .neo_format import (
    build_neo,
    parse_neo,
    parse_neo_header_metadata,
    replace_neo_metadata,
    write_bytes_atomic,
)
from .pack import _apply_swap_p, mame_dir_to_neo, mame_zip_to_neo
from .swap_detect import _check_m68k_vectors, detect_swap_p_needed, swap_p_banks
from .verify import VerifyResult, verify_roundtrip

__all__ = [
    "C_BANK_SIZE",
    "C_CHIP_SIZE_DEFAULT",
    "GENRE_BY_NAME",
    "GENRES",
    "NEO_HEADER_SIZE",
    "NEO_MAGIC",
    "P_SWAP_SIZE",
    "V_BANK_SIZE",
    "NeoMeta",
    "RomSet",
    "VerifyResult",
    "_apply_swap_p",
    "_check_m68k_vectors",
    "_interleave_c_chips",
    "_name_to_role",
    "_roles_to_romset",
    "build_neo",
    "collect_pack_psm_roles_for_validation",
    "detect_swap_p_needed",
    "extract_neo",
    "extract_neo_to_zip",
    "extract_romset",
    "extract_romset_to_zip",
    "mame_dir_to_neo",
    "mame_zip_to_neo",
    "neo_to_darksoft_zip",
    "neo_to_mame_zip",
    "pack_psm_role_from_basename",
    "parse_mame_dir",
    "parse_mame_zip",
    "parse_neo",
    "parse_neo_header_metadata",
    "replace_neo_metadata",
    "swap_p_banks",
    "verify_roundtrip",
    "write_bytes_atomic",
]
