"""Compare ROM payload regions between two ``.neo`` files (header ignored)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .constants import NEO_HEADER_SIZE


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
    new_data = rebuilt_neo[NEO_HEADER_SIZE:]

    orig_md5 = hashlib.md5(orig_data).hexdigest()
    new_md5 = hashlib.md5(new_data).hexdigest()
    size_match = len(original_neo) == len(rebuilt_neo)
    data_match = orig_data == new_data

    if data_match:
        details = "ROM data regions are byte-identical. Extraction is lossless."
    else:
        for i, (a, b) in enumerate(zip(orig_data, new_data)):
            if a != b:
                details = (
                    f"First difference at ROM offset 0x{i:X} "
                    f"(file offset 0x{NEO_HEADER_SIZE + i:X}). "
                    f"Original: {orig_data[i : i + 8].hex()}  "
                    f"Rebuilt:  {new_data[i : i + 8].hex()}"
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
