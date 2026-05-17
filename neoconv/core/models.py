"""Dataclasses for Neo Geo metadata and assembled ROM regions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .constants import C_CHIP_SIZE_DEFAULT, GENRES, NEO_HEADER_SIZE, V_BANK_SIZE


@dataclass
class NeoMeta:
    name: str = "Unknown"
    manufacturer: str = "Unknown"
    year: int = 0
    genre: int = 0
    screenshot: int = 0
    ngh: int = 0

    def format_info(self, romset: "RomSet | None" = None) -> str:
        """Return a human-readable summary, optionally including ROM sizes and per-region MD5."""
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
            total = (
                NEO_HEADER_SIZE
                + len(romset.p)
                + len(romset.s)
                + len(romset.m)
                + v_total
                + len(romset.c)
            )
            md5_p = hashlib.md5(romset.p).hexdigest()
            md5_s = hashlib.md5(romset.s).hexdigest()
            md5_m = hashlib.md5(romset.m).hexdigest()
            md5_v = hashlib.md5(romset.v).hexdigest()
            md5_c = hashlib.md5(romset.c).hexdigest()
            lines += [
                f"  P ROM        : {len(romset.p):>10,} bytes  ({len(romset.p)/1024/1024:.3f} MB)",
                f"  S ROM        : {len(romset.s):>10,} bytes  ({len(romset.s)/1024:.0f} KB)",
                f"  M ROM        : {len(romset.m):>10,} bytes  ({len(romset.m)/1024:.0f} KB)",
                f"  V ROM        : {v_total:>10,} bytes  ({v_total/1024/1024:.3f} MB)",
                f"  C ROM        : {len(romset.c):>10,} bytes  ({len(romset.c)/1024/1024:.3f} MB)",
                f"  Total        : {total:>10,} bytes  ({total/1024/1024:.2f} MB)",
                f"  P ROM MD5    : {md5_p}",
                f"  S ROM MD5    : {md5_s}",
                f"  M ROM MD5    : {md5_m}",
                f"  V ROM MD5    : {md5_v}",
                f"  C ROM MD5    : {md5_c}",
            ]
        return "\n".join(lines)


@dataclass
class RomSet:
    """Holds raw ROM region data."""

    p: bytes = b""
    s: bytes = b""
    m: bytes = b""
    v: bytes = b""  # all V data concatenated (V1 + V2 + ...)
    c: bytes = b""  # all C data interleaved (as stored in .neo)
    meta: NeoMeta = field(default_factory=NeoMeta)

    def v_chunks(self, bank_size: int = V_BANK_SIZE) -> list[bytes]:
        """
        Split V data into fixed-size chunks (``v1``, ``v2``, …).

        Parameters
        ----------
        bank_size : size of each V chunk in bytes (default 2 MB, MAME standard).
                    Use 4 MB or other sizes when the MAME set uses larger V ROMs.
        """
        if bank_size <= 0:
            raise ValueError(f"V bank size must be positive (got {bank_size}).")
        chunks = []
        for i in range(0, len(self.v), bank_size):
            chunks.append(self.v[i : i + bank_size])
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
