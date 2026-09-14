"""Dataclasses and enums for Neo Geo metadata and assembled ROM regions."""

from __future__ import annotations

import enum
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Optional

from .constants import C_CHIP_SIZE_DEFAULT, GENRES, NEO_HEADER_SIZE, V_BANK_SIZE
from .exceptions import InvalidConfigurationError


class SwapMode(enum.Enum):
    """P-ROM half-swap behaviour for :func:`~neoconv.core.apply_swap_p`.

    ``AUTO``  — inspect the M68000 vector table and swap only when the second
                half carries valid SP / Reset vectors (default for ``pack``).
    ``YES``   — always swap (use when auto-detect is ambiguous).
    ``NO``    — never swap.
    """

    AUTO = "auto"
    YES = "yes"
    NO = "no"


@dataclass
class NeoMeta:
    name: str = "Unknown"
    manufacturer: str = "Unknown"
    year: int = 0
    genre: int = 0
    screenshot: int = 0
    ngh: int = 0

    def format_info(self, romset: "RomSet | None" = None) -> str:
        """Return a human-readable summary, optionally including ROM sizes and per-region MD5.

        MD5 is recomputed on every call. For typical CLI / GUI use (single call per
        run) this is negligible; caching is intentionally omitted to keep the dataclass simple.
        """
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

    def v_chunks(
        self,
        bank_size: int = V_BANK_SIZE,
        *,
        bank_sizes: Optional[Sequence[int]] = None,
    ) -> list[bytes]:
        """
        Split V data into chunks (``v1``, ``v2``, …).

        Parameters
        ----------
        bank_size : uniform size of each V chunk in bytes (default 2 MB).
                    Ignored when *bank_sizes* is provided.
        bank_sizes : explicit per-file sizes in order. Sum must equal ``len(V)``.
        """
        if bank_sizes is not None:
            sizes = list(bank_sizes)
            if not sizes:
                raise InvalidConfigurationError("V bank size list must not be empty.")
            if any(s <= 0 for s in sizes):
                raise InvalidConfigurationError(
                    f"V bank sizes must be positive (got {sizes})."
                )
            expected = sum(sizes)
            if expected != len(self.v):
                raise InvalidConfigurationError(
                    f"V ROM size ({len(self.v):,} bytes) does not match the sum of "
                    f"--v-bank-sizes ({expected:,} bytes).",
                    hint="List every v1, v2, … size from MAME neogeo.xml in order.",
                )
            chunks: list[bytes] = []
            offset = 0
            for size in sizes:
                chunks.append(self.v[offset : offset + size])
                offset += size
            return chunks

        if bank_size <= 0:
            raise InvalidConfigurationError(f"V bank size must be positive (got {bank_size}).")
        chunks = []
        for i in range(0, len(self.v), bank_size):
            chunks.append(self.v[i : i + bank_size])
        return chunks

    def c_chips(
        self,
        chip_size: int = C_CHIP_SIZE_DEFAULT,
        *,
        chip_sizes: Optional[Sequence[int]] = None,
    ) -> list[bytes]:
        """
        De-interleave C ROM into individual chip images.

        .neo stores C data byte-interleaved in banks:
          byte 0 -> chip N (c1/c3/...)
          byte 1 -> chip N+1 (c2/c4/...)

        Each interleaved bank = chip_size * 2 bytes.
        Returns list: [c1, c2, c3, c4, ...]

        Parameters
        ----------
        chip_size : uniform size of each individual chip in bytes.
                    Default 2 MB covers most Neo Geo games.
                    Ignored when *chip_sizes* is provided.
        chip_sizes : explicit per-chip sizes in order (c1, c2, c3, c4, …).
                     Adjacent pair sizes must match; sum of chip sizes
                     must equal ``len(C)``.
        """
        if chip_sizes is not None:
            sizes = list(chip_sizes)
            if not sizes:
                raise InvalidConfigurationError("C chip size list must not be empty.")
            if any(s <= 0 for s in sizes):
                raise InvalidConfigurationError(
                    f"C chip sizes must be positive (got {sizes})."
                )
            if len(sizes) % 2 != 0:
                raise InvalidConfigurationError(
                    f"Odd number of C chip sizes ({len(sizes)}). "
                    "Sizes must come in pairs (c1+c2, c3+c4, ...).",
                    hint="Use --c-chip-sizes with an even count matching the MAME set.",
                )
            for i in range(0, len(sizes), 2):
                if sizes[i] != sizes[i + 1]:
                    raise InvalidConfigurationError(
                        f"C chip pair c{i + 1}/c{i + 2} size mismatch in list: "
                        f"{sizes[i]} vs {sizes[i + 1]} bytes.",
                        hint="Paired chips must share the same size.",
                    )
            # Two chips of size S → interleaved bank of 2*S; sum(chip sizes) == len(C).
            expected = sum(sizes)
            if expected != len(self.c):
                raise InvalidConfigurationError(
                    f"C ROM size ({len(self.c):,} bytes) does not match the sum of "
                    f"--c-chip-sizes ({expected:,} bytes).",
                    hint="List every c1, c2, … size from MAME neogeo.xml in order.",
                )
            chips: list[bytes] = []
            offset = 0
            for i in range(0, len(sizes), 2):
                pair_size = sizes[i]
                bank_size = pair_size * 2
                bank = self.c[offset : offset + bank_size]
                chips.append(bytes(bank[0::2]))
                chips.append(bytes(bank[1::2]))
                offset += bank_size
            return chips

        bank_size = chip_size * 2
        if len(self.c) % bank_size != 0:
            raise InvalidConfigurationError(
                f"C ROM size ({len(self.c):,} bytes) is not a multiple of "
                f"chip_size*2 ({bank_size:,} bytes). "
                f"Try a different --c-chip-size value, or --c-chip-sizes for mixed sets.",
                hint="Check per-chip sizes in MAME neogeo.xml (see --c-chip-size).",
            )
        chips = []
        for bank_start in range(0, len(self.c), bank_size):
            bank = self.c[bank_start : bank_start + bank_size]
            chips.append(bytes(bank[0::2]))  # odd chip  (c1, c3, ...)
            chips.append(bytes(bank[1::2]))  # even chip (c2, c4, ...)
        return chips
