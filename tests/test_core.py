"""
Unit tests for neoconv.core
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Run with:  python -m pytest tests/ -v
"""

import hashlib
import io
import os
import stat
import struct
import warnings
import zipfile
from pathlib import Path

import pytest

from neoconv.core import (
    C_BANK_SIZE,
    InvalidConfigurationError,
    InvalidNeoError,
    InvalidRomLayoutError,
    NEO_HEADER_SIZE,
    NEO_MAGIC,
    GENRES,
    NeoMeta,
    RomSet,
    SwapMode,
    P_SWAP_SIZE,
    UNSUPPORTED_MAME_SETS,
    UnsupportedRomSetError,
    UserCancelledError,
    apply_swap_p,
    check_m68k_vectors,
    interleave_c_chips,
    name_to_role,
    roles_to_romset,
    build_neo,
    extract_neo,
    extract_neo_to_zip,
    extract_romset,
    extract_romset_to_zip,
    neo_to_darksoft_zip,
    neo_to_mame_zip,
    parse_mame_dir,
    parse_mame_zip,
    parse_neo,
    parse_neo_header_metadata,
    parse_uint32,
    read_p_rom_from_zip,
    replace_neo_metadata,
    swap_p_banks,
    validate_name_prefix,
    verify_roundtrip,
    write_bytes_atomic,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_rom(size: int, fill: int = 0xAB) -> bytes:
    """Create a fake ROM filled with a repeating byte."""
    return bytes([fill & 0xFF]) * size


def make_romset(
    p_size: int = 1024 * 1024,
    s_size: int = 128 * 1024,
    m_size: int = 128 * 1024,
    v_size: int = 4 * 1024 * 1024,
    c_pairs: int = 1,
) -> RomSet:
    """Build a synthetic RomSet with distinguishable fill bytes per region."""
    c_chip = make_rom(C_BANK_SIZE, 0xCC)
    c_chips = [c_chip, make_rom(C_BANK_SIZE, 0xDD)] * c_pairs
    c_interleaved = interleave_c_chips(c_chips[:2])  # one bank for simplicity

    return RomSet(
        p=make_rom(p_size, 0xAA),
        s=make_rom(s_size, 0xBB),
        m=make_rom(m_size, 0xCC),
        v=make_rom(v_size, 0xDD),
        c=c_interleaved,
    )


def make_neo(romset: RomSet, meta: NeoMeta | None = None) -> bytes:
    if meta is None:
        meta = NeoMeta(name="Test", manufacturer="SNK", year=1994, ngh=42)
    return build_neo(romset, meta)


def write_complete_mame_zip(
    path: Path,
    *,
    prefix: str = "game",
    extra: tuple[tuple[str, bytes], ...] = (),
) -> None:
    """Write a small but complete (P/S/M/V/C) MAME-style ZIP fixture."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(f"{prefix}-p1.bin", make_rom(64 * 1024))
        zf.writestr(f"{prefix}-s1.bin", make_rom(128 * 1024))
        zf.writestr(f"{prefix}-m1.bin", make_rom(128 * 1024))
        zf.writestr(f"{prefix}-v1.bin", make_rom(128 * 1024))
        zf.writestr(f"{prefix}-c1.bin", make_rom(C_BANK_SIZE))
        zf.writestr(f"{prefix}-c2.bin", make_rom(C_BANK_SIZE))
        for name, data in extra:
            zf.writestr(name, data)


def write_role_zip(path: Path, roles: list[tuple[str, bytes]]) -> None:
    """Write a ZIP from explicit ``(member_name, data)`` pairs."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for name, data in roles:
            zf.writestr(name, data)


def corrupt_zip_member_data(path: Path, member: str = "game-p1.bin") -> None:
    """Flip bytes in a deflated member's compressed data so reads fail."""
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo(member)
    raw = bytearray(path.read_bytes())
    name_len, extra_len = struct.unpack_from("<HH", raw, info.header_offset + 26)
    start = info.header_offset + 30 + name_len + extra_len
    raw[start] ^= 0xFF
    raw[start + 1] ^= 0xFF
    path.write_bytes(bytes(raw))


def make_neo_with_v2_split(
    *,
    v1: bytes = b"AAA",
    v2: bytes = b"bb",
    name: str = "SplitGame",
    manufacturer: str = "SNK",
) -> bytes:
    """
    Build a small .neo whose header splits V across V1/V2 and carries unknown
    filler bytes (``RMF1`` at 0x100, arbitrary padding at 0x200).

    Real TerraOnion headers are not fully zero-filled; this fixture guards
    against code that rebuilds the header from scratch.
    """
    h = bytearray(NEO_HEADER_SIZE)
    h[0:4] = NEO_MAGIC
    struct.pack_into("<I", h, 0x04, 0)
    struct.pack_into("<I", h, 0x08, 0)
    struct.pack_into("<I", h, 0x0C, 0)
    struct.pack_into("<I", h, 0x10, len(v1))
    struct.pack_into("<I", h, 0x14, len(v2))
    struct.pack_into("<I", h, 0x18, 0)
    struct.pack_into("<I", h, 0x1C, 1999)
    struct.pack_into("<I", h, 0x20, 9)
    struct.pack_into("<I", h, 0x24, 7)
    struct.pack_into("<I", h, 0x28, 42)
    name_b = name.encode("latin-1")
    h[0x2C : 0x2C + len(name_b)] = name_b
    mfr_b = manufacturer.encode("latin-1")
    h[0x4D : 0x4D + len(mfr_b)] = mfr_b
    h[0x100:0x104] = b"RMF1"
    h[0x200:0x210] = bytes(range(0x10))
    return bytes(h) + v1 + v2


# ---------------------------------------------------------------------------
# name_to_role
# ---------------------------------------------------------------------------

class TestNameToRole:
    def test_extension_based(self):
        assert name_to_role("054-p1.p1") == "P"
        assert name_to_role("054-s1.s1") == "S"
        assert name_to_role("054-m1.m1") == "M"
        assert name_to_role("054-v1.v1") == "V1"
        assert name_to_role("054-v4.v4") == "V4"
        assert name_to_role("054-c1.c1") == "C1"
        assert name_to_role("054-c2.c2") == "C2"

    def test_bin_suffix(self):
        assert name_to_role("zin-p1.bin") == "P"
        assert name_to_role("zin-s1.bin") == "S"
        assert name_to_role("zin-m1.bin") == "M"
        assert name_to_role("zin-v2.bin") == "V2"
        assert name_to_role("zin-c1.bin") == "C1"
        assert name_to_role("zin-c2.bin") == "C2"

    def test_rom_suffix(self):
        assert name_to_role("zin-p1.rom") == "P"
        assert name_to_role("zin-c4.rom") == "C4"

    def test_unknown(self):
        assert name_to_role("neogeo.zip") is None
        assert name_to_role("000-lo.lo") is None
        assert name_to_role("sfix.sfix") is None

    def test_case_insensitive(self):
        assert name_to_role("ZIN-P1.BIN") == "P"
        assert name_to_role("ZIN-C1.C1") == "C1"

    def test_encrypted_sprite_naming_c1r(self):
        assert name_to_role("269-c1r.c1") == "C1"
        assert name_to_role("269-c2r.c2") == "C2"

    def test_letter_split_c_chips(self):
        assert name_to_role("kf10-c1a.bin") == "C1"
        assert name_to_role("kf10-c2a.bin") == "C2"
        assert name_to_role("kf10-c1b.bin") == "C1"
        assert name_to_role("5232-c1a.bin") == "C1"
        assert name_to_role("5232-c2b.bin") == "C2"
        # Native .c1 extension still wins over stem letter suffix.
        assert name_to_role("271-c1c.c1") == "C1"


# ---------------------------------------------------------------------------
# C ROM interleaving / de-interleaving
# ---------------------------------------------------------------------------

class TestCRomInterleaving:
    def test_roundtrip_single_bank(self):
        """De-interleave then re-interleave must produce identical bytes."""
        c1 = make_rom(C_BANK_SIZE, 0x11)
        c2 = make_rom(C_BANK_SIZE, 0x22)
        interleaved = interleave_c_chips([c1, c2])

        assert len(interleaved) == C_BANK_SIZE * 2
        # Even bytes = c1, odd bytes = c2
        assert bytes(interleaved[0::2]) == c1
        assert bytes(interleaved[1::2]) == c2

        # RomSet.c_chips() de-interleaves back
        rs = RomSet(c=interleaved)
        chips = rs.c_chips(chip_size=C_BANK_SIZE)
        assert chips[0] == c1
        assert chips[1] == c2

    def test_roundtrip_two_banks(self):
        c1 = make_rom(C_BANK_SIZE, 0x11)
        c2 = make_rom(C_BANK_SIZE, 0x22)
        c3 = make_rom(C_BANK_SIZE, 0x33)
        c4 = make_rom(C_BANK_SIZE, 0x44)
        interleaved = interleave_c_chips([c1, c2, c3, c4])

        rs = RomSet(c=interleaved)
        chips = rs.c_chips(chip_size=C_BANK_SIZE)
        assert chips == [c1, c2, c3, c4]

    def test_large_chip_size(self):
        """4 MB chips (e.g. Neo Turf Masters) roundtrip correctly."""
        large = 4 * 1024 * 1024
        c1 = make_rom(large, 0xAA)
        c2 = make_rom(large, 0xBB)
        interleaved = interleave_c_chips([c1, c2])
        rs = RomSet(c=interleaved)
        chips = rs.c_chips(chip_size=large)
        assert chips == [c1, c2]

    def test_wrong_chip_size_raises(self):
        """chip_size that doesn't divide C evenly should raise."""
        rs = RomSet(c=make_rom(C_BANK_SIZE * 2, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="not a multiple"):
            rs.c_chips(chip_size=C_BANK_SIZE + 1)

    def test_size_mismatch_raises(self):
        with pytest.raises(InvalidRomLayoutError, match="size mismatch"):
            interleave_c_chips([make_rom(C_BANK_SIZE), make_rom(C_BANK_SIZE // 2)])

    def test_odd_chip_count_raises(self):
        with pytest.raises(InvalidRomLayoutError, match="[Oo]dd"):
            roles_to_romset({
                "P": make_rom(512 * 1024),
                "S": make_rom(128 * 1024),
                "M": make_rom(128 * 1024),
                "C1": make_rom(C_BANK_SIZE),
                # C2 intentionally missing
            })

    def test_mixed_c_chip_sizes_roundtrip(self):
        """trally-style: 1 MiB pair + 512 KiB pair."""
        one_m = 1024 * 1024
        half_m = 512 * 1024
        c1 = make_rom(one_m, 0x11)
        c2 = make_rom(one_m, 0x22)
        c3 = make_rom(half_m, 0x33)
        c4 = make_rom(half_m, 0x44)
        interleaved = interleave_c_chips([c1, c2, c3, c4])
        assert len(interleaved) == 3 * 1024 * 1024
        rs = RomSet(c=interleaved)
        chips = rs.c_chips(chip_sizes=[one_m, one_m, half_m, half_m])
        assert chips == [c1, c2, c3, c4]

    def test_mixed_c_chip_sizes_uniform_small_silently_wrong_vs_list(self):
        """Single 512 KiB size divides 3 MiB but yields six wrong chips."""
        one_m = 1024 * 1024
        half_m = 512 * 1024
        c1 = make_rom(one_m, 0x11)
        c2 = make_rom(one_m, 0x22)
        c3 = make_rom(half_m, 0x33)
        c4 = make_rom(half_m, 0x44)
        interleaved = interleave_c_chips([c1, c2, c3, c4])
        rs = RomSet(c=interleaved)
        wrong = rs.c_chips(chip_size=half_m)
        assert len(wrong) == 6
        assert wrong != [c1, c2, c3, c4]
        assert rs.c_chips(chip_sizes=[one_m, one_m, half_m, half_m]) == [c1, c2, c3, c4]

    def test_c_chip_sizes_sum_mismatch_raises(self):
        rs = RomSet(c=make_rom(1024 * 1024, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="does not match the sum"):
            rs.c_chips(chip_sizes=[512 * 1024, 512 * 1024, 512 * 1024, 512 * 1024])

    def test_c_chip_sizes_odd_count_raises(self):
        rs = RomSet(c=make_rom(1024 * 1024, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="Odd number"):
            rs.c_chips(chip_sizes=[512 * 1024, 512 * 1024, 512 * 1024])

    def test_c_chip_sizes_unequal_pair_raises(self):
        rs = RomSet(c=make_rom(1024 * 1024 + 512 * 1024, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="size mismatch in list"):
            rs.c_chips(chip_sizes=[1024 * 1024, 512 * 1024])

    def test_c_chip_sizes_not_multiple_of_512k_raises(self):
        rs = RomSet(c=make_rom(1024 * 1024, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="not a multiple of 512 KB"):
            rs.c_chips(chip_sizes=[400_000, 400_000])

    def test_uniform_c_chip_size_not_multiple_of_512k_raises(self):
        rs = RomSet(c=make_rom(800_000, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="not a multiple of 512 KB"):
            rs.c_chips(chip_size=400_000)

    def test_mixed_v_bank_sizes_roundtrip(self):
        one_m = 1024 * 1024
        half_m = 512 * 1024
        v1 = make_rom(one_m, 0xA1)
        v2 = make_rom(half_m, 0xA2)
        rs = RomSet(v=v1 + v2)
        assert rs.v_chunks(bank_sizes=[one_m, half_m]) == [v1, v2]

    def test_v_bank_sizes_sum_mismatch_raises(self):
        rs = RomSet(v=make_rom(1024 * 1024, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="does not match the sum"):
            rs.v_chunks(bank_sizes=[512 * 1024, 512 * 1024, 512 * 1024])

    def test_p_chips_default_is_entire_region(self):
        p = make_rom(1024 * 1024, 0xB1)
        rs = RomSet(p=p)
        assert rs.p_chips() == [p]
        assert rs.p_chips(chip_size=0) == [p]
        assert rs.p_chips(chip_size=None) == [p]

    def test_p_chips_uniform_split(self):
        half_m = 512 * 1024
        p1 = make_rom(half_m, 0xB1)
        p2 = make_rom(half_m, 0xB2)
        rs = RomSet(p=p1 + p2)
        assert rs.p_chips(chip_size=half_m) == [p1, p2]

    def test_p_chips_mixed_sizes(self):
        one_m = 1024 * 1024
        half_m = 512 * 1024
        p1 = make_rom(one_m, 0xB1)
        p2 = make_rom(half_m, 0xB2)
        rs = RomSet(p=p1 + p2)
        assert rs.p_chips(chip_sizes=[one_m, half_m]) == [p1, p2]

    def test_p_chips_sum_mismatch_raises(self):
        rs = RomSet(p=make_rom(1024 * 1024, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="does not match the sum"):
            rs.p_chips(chip_sizes=[512 * 1024, 512 * 1024, 512 * 1024])

    def test_p_chips_uniform_not_multiple_raises(self):
        rs = RomSet(p=make_rom(1024 * 1024, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="not a multiple"):
            rs.p_chips(chip_size=400_000)

    def test_p_chips_negative_size_raises(self):
        rs = RomSet(p=make_rom(1024, 0xFF))
        with pytest.raises(InvalidConfigurationError, match="must be positive"):
            rs.p_chips(chip_size=-1)

    def test_p_chips_empty_p_with_uniform_size_keeps_single_empty(self):
        rs = RomSet(p=b"")
        assert rs.p_chips(chip_size=524288) == [b""]

    def test_extract_romset_default_writes_single_p1(self, tmp_path):
        p = make_rom(4096, 0xB1)
        rs = RomSet(
            p=p,
            s=make_rom(128, 2),
            m=make_rom(128, 3),
            v=make_rom(256, 4),
            c=interleave_c_chips([make_rom(C_BANK_SIZE, 5), make_rom(C_BANK_SIZE, 6)]),
        )
        written = extract_romset(
            rs, tmp_path / "out", name_prefix="g", fmt="mame", v_bank_size=256
        )
        assert set(k for k in written if k.startswith("p")) == {"p1"}
        assert written["p1"].read_bytes() == p

    def test_extract_romset_empty_p_with_uniform_size_still_writes_p1(self, tmp_path):
        rs = RomSet(
            p=b"",
            s=make_rom(128, 2),
            m=make_rom(128, 3),
            v=b"",
            c=interleave_c_chips([make_rom(C_BANK_SIZE, 5), make_rom(C_BANK_SIZE, 6)]),
        )
        written = extract_romset(
            rs, tmp_path / "out", name_prefix="g", fmt="mame", p_chip_size=524288
        )
        assert written["p1"].read_bytes() == b""
        assert "p2" not in written

    def test_extract_romset_to_zip_honours_p_chip_sizes(self):
        half_m = 512 * 1024
        p1 = make_rom(half_m, 0xB1)
        p2 = make_rom(half_m, 0xB2)
        rs = RomSet(
            p=p1 + p2,
            s=make_rom(128, 2),
            m=make_rom(128, 3),
            v=make_rom(256, 4),
            c=interleave_c_chips([make_rom(C_BANK_SIZE, 5), make_rom(C_BANK_SIZE, 6)]),
        )
        zip_data = extract_romset_to_zip(
            rs,
            name_prefix="038",
            fmt="mame",
            p_chip_sizes=[half_m, half_m],
            v_bank_size=256,
        )
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            assert zf.read("038-p1.bin") == p1
            assert zf.read("038-p2.bin") == p2
            names = zf.namelist()
            assert "038-p3.bin" not in names

    def test_extract_romset_honours_mixed_size_lists(self, tmp_path):
        one_m = 1024 * 1024
        half_m = 512 * 1024
        c1 = make_rom(one_m, 0x11)
        c2 = make_rom(one_m, 0x22)
        c3 = make_rom(half_m, 0x33)
        c4 = make_rom(half_m, 0x44)
        v1 = make_rom(one_m, 0xA1)
        v2 = make_rom(half_m, 0xA2)
        p1 = make_rom(half_m, 0xB1)
        p2 = make_rom(half_m, 0xB2)
        rs = RomSet(
            p=p1 + p2,
            s=make_rom(128 * 1024, 2),
            m=make_rom(128 * 1024, 3),
            v=v1 + v2,
            c=interleave_c_chips([c1, c2, c3, c4]),
        )
        out = tmp_path / "out"
        written = extract_romset(
            rs,
            out,
            name_prefix="038",
            fmt="mame",
            c_chip_sizes=[one_m, one_m, half_m, half_m],
            v_bank_sizes=[one_m, half_m],
            p_chip_sizes=[half_m, half_m],
        )
        assert written["p1"].read_bytes() == p1
        assert written["p2"].read_bytes() == p2
        assert written["c1"].read_bytes() == c1
        assert written["c2"].read_bytes() == c2
        assert written["c3"].read_bytes() == c3
        assert written["c4"].read_bytes() == c4
        assert written["v1"].read_bytes() == v1
        assert written["v2"].read_bytes() == v2

    def test_v_rom_gap_raises(self):
        base = {
            "P": make_rom(512 * 1024),
            "S": make_rom(128 * 1024),
            "M": make_rom(128 * 1024),
        }
        with pytest.raises(InvalidRomLayoutError, match="gap in V ROM"):
            roles_to_romset({**base, "V1": make_rom(128 * 1024), "V3": make_rom(128 * 1024)})

    def test_c_rom_gap_raises(self):
        base = {
            "P": make_rom(512 * 1024),
            "S": make_rom(128 * 1024),
            "M": make_rom(128 * 1024),
        }
        with pytest.raises(InvalidRomLayoutError, match="gap in C ROM"):
            roles_to_romset({
                **base,
                "C1": make_rom(C_BANK_SIZE),
                "C3": make_rom(C_BANK_SIZE),
            })


# ---------------------------------------------------------------------------
# build_neo / parse_neo
# ---------------------------------------------------------------------------

class TestBuildParseNeo:
    def test_magic(self):
        rs = make_romset()
        neo = make_neo(rs)
        assert neo[:4] == NEO_MAGIC

    def test_header_size(self):
        rs = make_romset()
        neo = make_neo(rs)
        assert len(neo) == NEO_HEADER_SIZE + len(rs.p) + len(rs.s) + len(rs.m) + len(rs.v) + len(rs.c)

    def test_rom_sizes_in_header(self):
        rs = make_romset()
        neo = make_neo(rs)
        assert struct.unpack_from("<I", neo, 0x04)[0] == len(rs.p)
        assert struct.unpack_from("<I", neo, 0x08)[0] == len(rs.s)
        assert struct.unpack_from("<I", neo, 0x0C)[0] == len(rs.m)
        assert struct.unpack_from("<I", neo, 0x10)[0] == len(rs.v)
        assert struct.unpack_from("<I", neo, 0x18)[0] == len(rs.c)

    def test_metadata_roundtrip(self):
        rs = make_romset()
        meta = NeoMeta(name="Windjammers", manufacturer="Data East", year=1994, ngh=65, genre=3)
        neo = build_neo(rs, meta)
        parsed = parse_neo(neo)
        assert parsed.meta.name == "Windjammers"
        assert parsed.meta.manufacturer == "Data East"
        assert parsed.meta.year == 1994
        assert parsed.meta.ngh == 65
        assert parsed.meta.genre == 3

    def test_metadata_terraonion_uint32_offsets(self):
        """Year/Genre/Screenshot/NGH are four consecutive uint32 (neosdconv layout)."""
        rs = make_romset()
        meta = NeoMeta(
            name="OffsetCheck",
            manufacturer="SNK",
            year=1994,
            genre=9,
            screenshot=7,
            ngh=101,
        )
        neo = build_neo(rs, meta)
        assert struct.unpack_from("<I", neo, 0x1C)[0] == 1994
        assert struct.unpack_from("<I", neo, 0x20)[0] == 9
        assert struct.unpack_from("<I", neo, 0x24)[0] == 7
        assert struct.unpack_from("<I", neo, 0x28)[0] == 101
        # Name still starts at 0x2C (must not be overwritten by NGH).
        assert neo[0x2C:0x2C + 11] == b"OffsetCheck"

    def test_parse_legacy_uint16_meta_and_rewrite_to_uint32(self):
        """Old neoconv Year/Genre uint16 headers are detected, read, then rewritten."""
        rs = make_romset()
        neo = bytearray(build_neo(rs, NeoMeta(name="Legacy", year=0, genre=0, ngh=0)))
        # Simulate pre-fix layout: uint16 year/genre, then screenshot/ngh uint32.
        struct.pack_into("<H", neo, 0x1C, 1994)
        struct.pack_into("<H", neo, 0x1E, 9)
        struct.pack_into("<I", neo, 0x20, 7)
        struct.pack_into("<I", neo, 0x24, 101)
        struct.pack_into("<I", neo, 0x28, 0)
        with pytest.warns(UserWarning, match="legacy neoconv header"):
            meta = parse_neo(bytes(neo)).meta
        assert meta.year == 1994
        assert meta.genre == 9
        assert meta.screenshot == 7
        assert meta.ngh == 101
        with pytest.warns(UserWarning, match="legacy neoconv header"):
            rewritten = replace_neo_metadata(bytes(neo), name="Migrated")
        # No legacy warning on the rewritten modern header.
        parsed = parse_neo(rewritten)
        assert parsed.meta.name == "Migrated"
        assert parsed.meta.year == 1994
        assert parsed.meta.genre == 9
        assert parsed.meta.screenshot == 7
        assert parsed.meta.ngh == 101
        assert struct.unpack_from("<I", rewritten, 0x28)[0] == 101
        assert struct.unpack_from("<I", rewritten, 0x1C)[0] == 1994
        assert struct.unpack_from("<I", rewritten, 0x20)[0] == 9

    def test_rom_data_preserved(self):
        rs = make_romset()
        neo = make_neo(rs)
        parsed = parse_neo(neo)
        assert parsed.p == rs.p
        assert parsed.s == rs.s
        assert parsed.m == rs.m
        assert parsed.v == rs.v
        assert parsed.c == rs.c

    def test_invalid_magic_raises(self):
        with pytest.raises(InvalidNeoError, match="Not a valid .neo"):
            parse_neo(b"BAD!" + bytes(NEO_HEADER_SIZE))

    def test_truncated_file_raises(self):
        rs = make_romset()
        neo = make_neo(rs)
        with pytest.raises(InvalidNeoError):
            parse_neo(neo[:-100])  # truncate last 100 bytes

    def test_file_shorter_than_header_raises(self):
        data = NEO_MAGIC + b"\x00" * 64
        assert len(data) < NEO_HEADER_SIZE
        with pytest.raises(InvalidNeoError, match="too small"):
            parse_neo(data)

    def test_parse_neo_preserves_v1_v2_sizes(self):
        """Header V1/V2 split is merged for callers but retained on the RomSet."""
        neo = make_neo_with_v2_split()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            rs = parse_neo(neo)
        assert rs.v == b"AAAbb"
        assert rs.v1_size == 3
        assert rs.v2_size == 2
        assert rs.v_sizes() == (3, 2)

    def test_parse_build_roundtrip_preserves_v_split(self):
        neo = make_neo_with_v2_split()
        rs = parse_neo(neo)
        rebuilt = build_neo(rs, rs.meta)
        assert struct.unpack_from("<I", rebuilt, 0x10)[0] == 3
        assert struct.unpack_from("<I", rebuilt, 0x14)[0] == 2
        assert rebuilt[NEO_HEADER_SIZE:] == neo[NEO_HEADER_SIZE:]

    def test_build_neo_unknown_v_split_uses_legacy_layout(self):
        """RomSets built from MAME input have no original split; V2 stays 0."""
        rs = RomSet(v=b"x" * 10)
        neo = build_neo(rs, NeoMeta())
        assert struct.unpack_from("<I", neo, 0x10)[0] == 10
        assert struct.unpack_from("<I", neo, 0x14)[0] == 0

    def test_build_neo_explicit_zero_v2(self):
        rs = RomSet(v=b"x" * 10, v1_size=10, v2_size=0)
        neo = build_neo(rs, NeoMeta())
        assert struct.unpack_from("<I", neo, 0x10)[0] == 10
        assert struct.unpack_from("<I", neo, 0x14)[0] == 0

    def test_romset_rejects_v_sizes_that_do_not_sum_to_v(self):
        with pytest.raises(InvalidConfigurationError, match="does not match the V ROM size"):
            RomSet(v=b"abc", v1_size=2, v2_size=2)

    def test_romset_rejects_negative_v_sizes(self):
        with pytest.raises(InvalidConfigurationError, match="must not be negative"):
            RomSet(v=b"abc", v1_size=-1, v2_size=4)

    def test_romset_rejects_v2_without_v1(self):
        with pytest.raises(InvalidConfigurationError, match="V1 size is unknown"):
            RomSet(v=b"abc", v2_size=3)


# ---------------------------------------------------------------------------
# Metadata-only .neo edits
# ---------------------------------------------------------------------------

class TestNeoMetadataEdit:
    def test_parse_neo_header_metadata_matches_full_parse(self):
        rs = make_romset()
        meta = NeoMeta(
            name="HdrX",
            manufacturer="HdrY",
            year=2002,
            genre=9,
            ngh=99,
            screenshot=7,
        )
        neo = build_neo(rs, meta)
        quick = parse_neo_header_metadata(neo[:NEO_HEADER_SIZE])
        assert quick == parse_neo(neo).meta

    def test_parse_neo_header_metadata_too_short(self):
        with pytest.raises(InvalidNeoError, match="too small"):
            parse_neo_header_metadata(NEO_MAGIC + b"\x00" * 64)

    def test_replace_neo_metadata_rom_regions_unchanged(self):
        rs = make_romset()
        meta = NeoMeta(
            name="Old",
            manufacturer="SNK",
            year=1990,
            genre=1,
            ngh=2,
            screenshot=3,
        )
        neo = build_neo(rs, meta)
        new = replace_neo_metadata(neo, name="NewName")
        before = parse_neo(neo)
        after = parse_neo(new)
        assert after.meta.name == "NewName"
        assert after.meta.manufacturer == before.meta.manufacturer
        assert after.meta.year == before.meta.year
        assert after.p == before.p and after.c == before.c

    def test_replace_neo_metadata_partial_cli_semantics(self):
        neo = make_neo(make_romset())
        old = parse_neo(neo)
        new = replace_neo_metadata(neo, year=2099, ngh=123)
        m = parse_neo(new).meta
        assert m.year == 2099
        assert m.ngh == 123
        assert m.name == old.meta.name

    def test_replace_neo_metadata_bitwise_matches_build_neo_parse_path(self):
        neo = make_neo(make_romset())
        rs = parse_neo(neo)
        ref_meta = NeoMeta(
            name=rs.meta.name + "X",
            manufacturer="OtherMfr",
            year=rs.meta.year + 3,
            genre=min(10, rs.meta.genre + 1),
            screenshot=rs.meta.screenshot + 2,
            ngh=rs.meta.ngh + 9,
        )
        ref = build_neo(rs, ref_meta)
        new = replace_neo_metadata(
            neo,
            name=ref_meta.name,
            manufacturer=ref_meta.manufacturer,
            year=ref_meta.year,
            genre=ref_meta.genre,
            screenshot=ref_meta.screenshot,
            ngh=ref_meta.ngh,
        )
        assert new == ref

    def test_edit_preserves_untouched_header_bytes_and_payload(self):
        neo = make_neo_with_v2_split()
        new = replace_neo_metadata(neo, name="NewName", year=2001)

        # Payload after the header must be byte-identical.
        assert new[NEO_HEADER_SIZE:] == neo[NEO_HEADER_SIZE:]
        assert hashlib.md5(new[NEO_HEADER_SIZE:]).hexdigest() == hashlib.md5(
            neo[NEO_HEADER_SIZE:]
        ).hexdigest()

        # Unknown header filler and padding survive.
        assert new[0x100:0x104] == b"RMF1"
        assert new[0x200:0x210] == bytes(range(0x10))

        # V1/V2 split survives.
        assert struct.unpack_from("<I", new, 0x10)[0] == 3
        assert struct.unpack_from("<I", new, 0x14)[0] == 2

        # Only the requested fields change.
        changed = {i for i in range(NEO_HEADER_SIZE) if neo[i] != new[i]}
        assert changed <= set(range(0x1C, 0x20)) | set(range(0x2C, 0x4D))

        parsed = parse_neo(new)
        assert parsed.meta.name == "NewName"
        assert parsed.meta.year == 2001
        assert parsed.meta.genre == 9
        assert parsed.meta.screenshot == 7
        assert parsed.meta.ngh == 42
        assert (parsed.v1_size, parsed.v2_size) == (3, 2)

    def test_edit_does_not_warn_about_v2(self):
        neo = make_neo_with_v2_split()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            replace_neo_metadata(neo, name="Quiet")

    def test_edit_clears_stale_name_and_manufacturer_tail(self):
        neo = make_neo_with_v2_split(
            name="AVeryLongOriginalName",
            manufacturer="LongManufacturer",
        )
        new = replace_neo_metadata(neo, name="X", manufacturer="Y")
        assert new[0x2C:0x4D] == b"X" + b"\x00" * 32
        assert new[0x4D:0x5E] == b"Y" + b"\x00" * 16
        assert new[NEO_HEADER_SIZE:] == neo[NEO_HEADER_SIZE:]

    def test_edit_without_metadata_overrides_returns_input(self):
        neo = make_neo_with_v2_split()
        assert replace_neo_metadata(neo) == neo

    def test_replace_neo_metadata_preserves_split_v_header(self):
        """A V1/V2 split in the header must survive an edit unchanged."""
        neo = make_neo_with_v2_split()
        new = replace_neo_metadata(neo, year=3333)
        assert struct.unpack_from("<I", new, 0x10)[0] == 3
        assert struct.unpack_from("<I", new, 0x14)[0] == 2
        assert replace_neo_metadata(neo, year=3333)[NEO_HEADER_SIZE:] == neo[
            NEO_HEADER_SIZE:
        ]
        # parse -> build reproduces the split and payload, even though build_neo
        # legitimately zero-fills unknown header padding.
        parsed = parse_neo(new)
        rebuilt = build_neo(parsed, parsed.meta)
        assert struct.unpack_from("<I", rebuilt, 0x10)[0] == 3
        assert struct.unpack_from("<I", rebuilt, 0x14)[0] == 2
        assert rebuilt[NEO_HEADER_SIZE:] == new[NEO_HEADER_SIZE:]

    def test_write_bytes_atomic(self, tmp_path):
        p = tmp_path / "out.neo"
        write_bytes_atomic(p, b"alpha")
        assert p.read_bytes() == b"alpha"
        write_bytes_atomic(p, b"beta")
        assert p.read_bytes() == b"beta"


# ---------------------------------------------------------------------------
# Vector check, ZIP/dir parse helpers, neo_to_* convenience
# ---------------------------------------------------------------------------

class TestCoreEdgeCases:
    def testcheck_m68k_vectors_too_short(self):
        ok, sp, rst = check_m68k_vectors(b"\x00\x01\x02")
        assert ok is False
        assert sp == 0 and rst == 0

    def test_word_swap_odd_length_raises(self):
        from neoconv.core.swap_detect import _word_swap

        with pytest.raises(InvalidConfigurationError, match="even byte length"):
            _word_swap(b"\x00\x01\x02")
        assert _word_swap(b"\x12\x34") == b"\x34\x12"
        assert _word_swap(b"") == b""

    def test_parse_mame_zip_rejects_corrupt_archive(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"\xffNOT_A_ZIP\xff")
        with pytest.raises(InvalidRomLayoutError, match="Cannot open ZIP"):
            parse_mame_zip(bad)

    def test_parse_mame_zip_diagnostic_warns_on_unknown_files(self, tmp_path):
        z = tmp_path / "set.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("game-p1.bin", b"p" * 4096)
            zf.writestr("game-s1.bin", make_rom(128 * 1024, 0x11))
            zf.writestr("game-m1.bin", make_rom(128 * 1024, 0x22))
            zf.writestr("game-v1.bin", make_rom(128 * 1024, 0x33))
            zf.writestr("game-c1.bin", make_rom(C_BANK_SIZE, 0x44))
            zf.writestr("game-c2.bin", make_rom(C_BANK_SIZE, 0x55))
            zf.writestr("readme.txt", b"x")
        with pytest.warns(UserWarning, match=r"\[diagnostic\]"):
            parse_mame_zip(z, diagnostic=True, allow_extra_files=True)

    def test_parse_mame_zip_svc_parent_style_inserts_512k_zero_s(self, tmp_path):
        """MAME parent ``svc`` has no s1; fixed layer is 512 KiB of zeros (PVC / c1r)."""
        z = tmp_path / "svcish.zip"
        chip = make_rom(C_BANK_SIZE, 0x11)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("269-p1.p1", make_rom(1024, 1))
            zf.writestr("269-p2.p2", make_rom(1024, 2))
            zf.writestr("269-m1.m1", make_rom(1024, 3))
            zf.writestr("269-v1.v1", make_rom(1024, 4))
            zf.writestr("269-c1r.c1", chip)
            zf.writestr("269-c2r.c2", make_rom(C_BANK_SIZE, 0x22))
        with pytest.warns(UserWarning, match="No text-layer ROM") as caught:
            rs = parse_mame_zip(z, allow_synthetic_s=True)
        assert len(rs.s) == 0x80000
        assert rs.s == b"\x00" * 0x80000
        assert any("NOT playable" in str(w.message) for w in caught)

    def test_parse_mame_zip_garou_style_512k_zero_s_without_c1r(self, tmp_path):
        """Garou parent uses 512 KiB fixed fill; C ROMs are ``253-c1.c1`` (no ``r``)."""
        z = tmp_path / "garouish.zip"
        chip = make_rom(C_BANK_SIZE, 0x11)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("253-p1.p1", make_rom(1024, 1))
            zf.writestr("253-p2.sp2", make_rom(1024, 2))
            zf.writestr("253-m1.m1", make_rom(1024, 3))
            zf.writestr("253-v1.v1", make_rom(1024, 4))
            zf.writestr("253-c1.c1", chip)
            zf.writestr("253-c2.c2", make_rom(C_BANK_SIZE, 0x22))
        with pytest.warns(UserWarning, match="No text-layer ROM"):
            rs = parse_mame_zip(z, allow_synthetic_s=True)
        assert len(rs.s) == 0x80000

    def test_parse_mame_zip_kof2003_style_c1c_suffix_512k_s(self, tmp_path):
        z = tmp_path / "k03.zip"
        chip = make_rom(C_BANK_SIZE, 0x11)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("271-p1.p1", make_rom(1024, 1))
            zf.writestr("271-p2.p2", make_rom(1024, 2))
            zf.writestr("271-m1.m1", make_rom(1024, 3))
            zf.writestr("271-v1.v1", make_rom(1024, 4))
            zf.writestr("271-c1c.c1", chip)
            zf.writestr("271-c2c.c2", make_rom(C_BANK_SIZE, 0x22))
        with pytest.warns(UserWarning, match="No text-layer ROM"):
            rs = parse_mame_zip(z, allow_synthetic_s=True)
        assert len(rs.s) == 0x80000

    def test_parse_mame_zip_kof10th_style_256k_zero_s(self, tmp_path):
        z = tmp_path / "kf10.zip"
        chip = make_rom(C_BANK_SIZE // 2, 0x11)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("kf10-p1.bin", make_rom(1024, 1))
            zf.writestr("kf10-m1.bin", make_rom(1024, 3))
            zf.writestr("kf10-v1.bin", make_rom(1024, 4))
            zf.writestr("kf10-c1a.bin", chip)
            zf.writestr("kf10-c2a.bin", make_rom(C_BANK_SIZE // 2, 0x22))
        with pytest.warns(UserWarning, match="No text-layer ROM"):
            rs = parse_mame_zip(z, allow_synthetic_s=True)
        assert len(rs.s) == 0x40000
        assert len(rs.c) == C_BANK_SIZE  # interleaved pair of half-size chips

    def test_c_letter_parts_three_contiguous_parts_merge(self, tmp_path):
        """A contiguous c1a+c1b+c1c set is merged in letter order."""
        z = tmp_path / "three_part.zip"
        part = C_BANK_SIZE // 4
        parts = [make_rom(part, 0x10 + i) for i in range(3)]
        roles = [
            ("game-p1.bin", make_rom(1024, 1)),
            ("game-s1.bin", make_rom(1024, 2)),
            ("game-m1.bin", make_rom(1024, 3)),
            ("game-v1.bin", make_rom(1024, 4)),
        ]
        roles += [
            (f"game-c1{letter}.bin", data)
            for letter, data in zip("abc", parts)
        ]
        roles += [
            (f"game-c2{letter}.bin", make_rom(part, 0x20 + i))
            for i, letter in enumerate("abc")
        ]
        write_role_zip(z, roles)
        rs = parse_mame_zip(z)
        c2_merged = b"".join(make_rom(part, 0x20 + i) for i in range(3))
        assert rs.c == interleave_c_chips([b"".join(parts), c2_merged])

    def test_c_letter_part_gap_rejected(self, tmp_path):
        """c1a + c1c without c1b must fail instead of dropping the gap."""
        z = tmp_path / "c_gap.zip"
        half = C_BANK_SIZE // 2
        write_role_zip(z, [
            ("game-p1.bin", make_rom(1024, 1)),
            ("game-s1.bin", make_rom(1024, 2)),
            ("game-m1.bin", make_rom(1024, 3)),
            ("game-v1.bin", make_rom(1024, 4)),
            ("game-c1a.bin", make_rom(half, 0x11)),
            ("game-c1c.bin", make_rom(half, 0x13)),
        ])
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z)
        assert "c1b" in str(exc.value)
        assert "contiguous" in (exc.value.hint or "")

    def test_parse_mame_zip_kof10th_merges_c1a_c1b_parts(self, tmp_path):
        """Split C parts (c1a+c1b) are concatenated before interleaving."""
        z = tmp_path / "kf10_full.zip"
        half = C_BANK_SIZE // 2
        c1a = make_rom(half, 0x11)
        c1b = make_rom(half, 0x12)
        c2a = make_rom(half, 0x21)
        c2b = make_rom(half, 0x22)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("kf10-p1.bin", make_rom(1024, 1))
            zf.writestr("kf10-m1.bin", make_rom(1024, 3))
            zf.writestr("kf10-v1.bin", make_rom(1024, 4))
            zf.writestr("kf10-c1a.bin", c1a)
            zf.writestr("kf10-c1b.bin", c1b)
            zf.writestr("kf10-c2a.bin", c2a)
            zf.writestr("kf10-c2b.bin", c2b)
        with pytest.warns(UserWarning, match="No text-layer ROM"):
            rs = parse_mame_zip(z, allow_synthetic_s=True)
        assert len(rs.s) == 0x40000
        assert rs.c == interleave_c_chips([c1a + c1b, c2a + c2b])

    def test_roles_to_romset_rejects_synthetic_s_without_c(self):
        with pytest.warns(UserWarning, match="No text-layer ROM"):
            with pytest.raises(InvalidRomLayoutError, match="No C sprite ROM"):
                roles_to_romset(
                    {
                        "P": b"x" * 4096,
                        "M": b"y" * 1024,
                    },
                    source="empty-c.zip",
                    source_filenames=(
                        "kf10-p1.bin",
                        "kf10-m1.bin",
                        "kf10-c1a.bin",  # implies C1 / synthetic S, but no C bytes stored
                    ),
                    allow_synthetic_s=True,
                )

    def test_parse_mame_zip_encrypted_without_c1r_inserts_128k_zero_s(self, tmp_path):
        z = tmp_path / "sam5ish.zip"
        chip = make_rom(C_BANK_SIZE, 0x11)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("270-p1.p1", make_rom(1024, 1))
            zf.writestr("270-p2.sp2", make_rom(1024, 2))
            zf.writestr("270-m1.m1", make_rom(1024, 3))
            zf.writestr("270-v1.v1", make_rom(1024, 4))
            zf.writestr("270-c1.c1", chip)
            zf.writestr("270-c2.c2", make_rom(C_BANK_SIZE, 0x22))
        with pytest.warns(UserWarning, match="No text-layer ROM"):
            rs = parse_mame_zip(z, allow_synthetic_s=True)
        assert len(rs.s) == 0x20000
        assert rs.s == b"\x00" * 0x20000

    def test_parse_mame_zip_synthetic_s_ignores_c1r_substring_false_positive(self, tmp_path):
        """``game-c1r2.bin`` must not trigger the PVC ``c1r`` 512 KiB branch."""
        z = tmp_path / "sam5ish_plus_junk.zip"
        chip = make_rom(C_BANK_SIZE, 0x11)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("270-p1.p1", make_rom(1024, 1))
            zf.writestr("270-p2.sp2", make_rom(1024, 2))
            zf.writestr("270-m1.m1", make_rom(1024, 3))
            zf.writestr("270-v1.v1", make_rom(1024, 4))
            zf.writestr("270-c1.c1", chip)
            zf.writestr("270-c2.c2", make_rom(C_BANK_SIZE, 0x22))
            zf.writestr("game-c1r2.bin", b"readme")
        with pytest.warns(UserWarning, match="No text-layer ROM"):
            rs = parse_mame_zip(
                z, allow_extra_files=True, allow_synthetic_s=True
            )
        assert len(rs.s) == 0x20000

    def testroles_to_romset_without_filenames_still_requires_physical_s(self):
        with pytest.raises(InvalidRomLayoutError, match="S"):
            roles_to_romset(
                {
                    "P": b"x" * 4096,
                    "M": b"y" * 1024,
                    "C1": make_rom(C_BANK_SIZE),
                    "C2": make_rom(C_BANK_SIZE),
                },
                source="dict",
            )

    def test_parse_mame_dir_inserts_synthetic_s_like_zip(self, tmp_path):
        chip = make_rom(C_BANK_SIZE, 0x11)
        (tmp_path / "269-p1.p1").write_bytes(make_rom(1024, 1))
        (tmp_path / "269-p2.p2").write_bytes(make_rom(1024, 2))
        (tmp_path / "269-m1.m1").write_bytes(make_rom(1024, 3))
        (tmp_path / "269-v1.v1").write_bytes(make_rom(1024, 4))
        (tmp_path / "269-c1r.c1").write_bytes(chip)
        (tmp_path / "269-c2r.c2").write_bytes(make_rom(C_BANK_SIZE, 0x22))
        with pytest.warns(UserWarning, match="No text-layer ROM"):
            rs = parse_mame_dir(tmp_path, allow_synthetic_s=True)
        assert len(rs.s) == 0x80000

    def test_parse_mame_dir_diagnostic_warns_on_unknown_files(self, tmp_path):
        (tmp_path / "game-p1.bin").write_bytes(b"p" * 4096)
        (tmp_path / "game-s1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-m1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-v1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-c1.bin").write_bytes(make_rom(C_BANK_SIZE))
        (tmp_path / "game-c2.bin").write_bytes(make_rom(C_BANK_SIZE))
        (tmp_path / "readme.txt").write_text("x", encoding="utf-8")
        with pytest.warns(UserWarning, match=r"\[diagnostic\]"):
            parse_mame_dir(tmp_path, diagnostic=True, allow_extra_files=True)

    def test_parse_mame_dir_reads_one_subdirectory_level(self, tmp_path):
        sub = tmp_path / "set"
        sub.mkdir()
        (sub / "game-p1.bin").write_bytes(make_rom(512 * 1024))
        (sub / "game-s1.bin").write_bytes(make_rom(128 * 1024))
        (sub / "game-m1.bin").write_bytes(make_rom(128 * 1024))
        (sub / "game-v1.bin").write_bytes(make_rom(128 * 1024))
        (sub / "game-c1.bin").write_bytes(make_rom(C_BANK_SIZE))
        (sub / "game-c2.bin").write_bytes(make_rom(C_BANK_SIZE))
        rs = parse_mame_dir(tmp_path)
        assert len(rs.p) == 512 * 1024

    def test_neo_to_mame_zip_and_darksoft_zip(self, tmp_path):
        rs = make_romset(p_size=65536)
        neo_path = tmp_path / "tiny.neo"
        neo_path.write_bytes(make_neo(rs))
        mzip = neo_to_mame_zip(neo_path, "game")
        dzip = neo_to_darksoft_zip(neo_path, "game")
        assert mzip[:2] == b"PK"
        assert dzip[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(mzip)) as zf:
            assert any(n.endswith("-p1.bin") for n in zf.namelist())


# ---------------------------------------------------------------------------
# V ROM chunking
# ---------------------------------------------------------------------------

class TestVRomChunking:
    def test_v_chunks_default_2mb(self):
        two_mb = 2 * 1024 * 1024
        rs = RomSet(v=make_rom(8 * 1024 * 1024, 0xDD))
        chunks = rs.v_chunks()
        assert len(chunks) == 4
        assert all(len(c) == two_mb for c in chunks)

    def test_v_chunks_custom_bank_size(self):
        four_mb = 4 * 1024 * 1024
        rs = RomSet(v=make_rom(8 * 1024 * 1024, 0xDD))
        chunks = rs.v_chunks(bank_size=four_mb)
        assert len(chunks) == 2
        assert all(len(c) == four_mb for c in chunks)

    def test_v_chunks_invalid_bank_size_raises(self):
        with pytest.raises(InvalidConfigurationError, match="positive"):
            RomSet(v=b"x").v_chunks(bank_size=0)

    def test_extract_zip_uses_v_bank_size(self):
        four_mb = 4 * 1024 * 1024
        rs = make_romset(v_size=8 * 1024 * 1024)
        zip_bytes = extract_romset_to_zip(
            rs, name_prefix="x", fmt="mame", v_bank_size=four_mb
        )
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert "x-v1.bin" in names
        assert "x-v2.bin" in names
        assert "x-v3.bin" not in names
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert len(zf.read("x-v1.bin")) == four_mb
            assert len(zf.read("x-v2.bin")) == four_mb

    def test_warn_when_v_not_multiple_of_bank_size(self):
        two_mb = 2 * 1024 * 1024
        rs = RomSet(v=b"\x00" * (two_mb + 512))
        with pytest.warns(UserWarning, match="not a multiple"):
            extract_romset_to_zip(rs, name_prefix="x", fmt="mame", v_bank_size=two_mb)


# ---------------------------------------------------------------------------
# extract_neo_to_zip
# ---------------------------------------------------------------------------

class TestExtractNeoToZip:
    def test_mame_format_filenames(self):
        rs = make_romset()
        neo = make_neo(rs)
        zip_bytes = extract_neo_to_zip(neo, name_prefix="test", fmt="mame")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert "test-p1.bin" in names
        assert "test-s1.bin" in names
        assert "test-m1.bin" in names
        assert "test-v1.bin" in names
        assert "test-c1.bin" in names
        assert "test-c2.bin" in names

    def test_darksoft_format_filenames(self):
        rs = make_romset()
        neo = make_neo(rs)
        zip_bytes = extract_neo_to_zip(neo, name_prefix="test", fmt="darksoft")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert "test-p1.rom" in names
        assert "test-c1.rom" in names

    def test_v_rom_split(self):
        """8 MB V ROM should produce 4x 2 MB chunks (v1..v4)."""
        rs = make_romset(v_size=8 * 1024 * 1024)
        neo = make_neo(rs)
        zip_bytes = extract_neo_to_zip(neo, name_prefix="x", fmt="mame")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert "x-v1.bin" in names
        assert "x-v2.bin" in names
        assert "x-v3.bin" in names
        assert "x-v4.bin" in names
        assert "x-v5.bin" not in names

    def test_extract_romset_to_zip_matches_extract_neo_to_zip(self):
        """RomSet-based ZIP extraction should match neo_data-based extraction."""
        rs = make_romset()
        neo = make_neo(rs)
        zip_from_neo = extract_neo_to_zip(neo, name_prefix="cmp", fmt="mame")
        parsed = parse_neo(neo)
        zip_from_romset = extract_romset_to_zip(parsed, name_prefix="cmp", fmt="mame")

        with zipfile.ZipFile(io.BytesIO(zip_from_neo)) as z1, zipfile.ZipFile(io.BytesIO(zip_from_romset)) as z2:
            names1 = sorted(z1.namelist())
            names2 = sorted(z2.namelist())
            assert names1 == names2
            for name in names1:
                assert z1.read(name) == z2.read(name)

    def test_extract_romset_writes_same_files_as_extract_neo(self, tmp_path):
        """RomSet-based directory extraction should match neo_data-based extraction."""
        from neoconv.core import extract_neo

        rs = make_romset()
        neo = make_neo(rs)
        out_neo = tmp_path / "from_neo"
        out_rs = tmp_path / "from_rs"

        files_from_neo = extract_neo(neo, out_neo, name_prefix="cmp", fmt="mame")
        files_from_rs = extract_romset(parse_neo(neo), out_rs, name_prefix="cmp", fmt="mame")

        assert sorted(files_from_neo.keys()) == sorted(files_from_rs.keys())
        for key in files_from_neo:
            assert files_from_neo[key].read_bytes() == files_from_rs[key].read_bytes()

    def test_extract_romset_warns_when_overwriting(self, tmp_path):
        rs = make_romset()
        out_dir = tmp_path / "out"
        extract_romset(rs, out_dir, name_prefix="g", fmt="mame")
        with pytest.warns(UserWarning, match="Overwriting"):
            extract_romset(rs, out_dir, name_prefix="g", fmt="mame")

    def test_extract_romset_cancel_check_aborts_between_writes(self, tmp_path):
        rs = make_romset()
        out_dir = tmp_path / "partial"
        calls = {"n": 0}

        def cancel_after_first() -> None:
            calls["n"] += 1
            if calls["n"] > 1:
                raise UserCancelledError("stop")

        with pytest.raises(UserCancelledError, match="stop"):
            extract_romset(rs, out_dir, name_prefix="g", fmt="mame", cancel_check=cancel_after_first)
        # First ROM (p1) written; later ones aborted.
        assert (out_dir / "g-p1.bin").exists()
        assert not (out_dir / "g-s1.bin").exists()

    def test_extract_romset_to_zip_cancel_check_aborts(self):
        rs = make_romset()
        calls = {"n": 0}

        def cancel_after_p() -> None:
            calls["n"] += 1
            if calls["n"] > 1:
                raise UserCancelledError("stop")

        with pytest.raises(UserCancelledError, match="stop"):
            extract_romset_to_zip(rs, name_prefix="g", fmt="mame", cancel_check=cancel_after_p)


# ---------------------------------------------------------------------------
# verify_roundtrip
# ---------------------------------------------------------------------------

class TestVerifyRoundtrip:
    def test_identical_passes(self):
        rs  = make_romset()
        neo = make_neo(rs)
        result = verify_roundtrip(neo, neo)
        assert result.ok
        assert result.original_rom_md5 == result.rebuilt_rom_md5

    def test_different_header_same_data_passes(self):
        """Different metadata headers but identical ROM data -> OK."""
        rs    = make_romset()
        meta1 = NeoMeta(name="Game A", year=1993)
        meta2 = NeoMeta(name="Game B", year=1999)
        neo1  = build_neo(rs, meta1)
        neo2  = build_neo(rs, meta2)
        result = verify_roundtrip(neo1, neo2)
        assert result.ok

    def test_different_rom_data_fails(self):
        rs1 = make_romset()
        rs2 = make_romset(p_size=512 * 1024)  # different P size
        neo1 = make_neo(rs1)
        neo2 = make_neo(rs2)
        result = verify_roundtrip(neo1, neo2)
        assert not result.ok
        assert result.original_rom_md5 != result.rebuilt_rom_md5


# ---------------------------------------------------------------------------
# NeoMeta.format_info
# ---------------------------------------------------------------------------

class TestNeoMetaFormatInfo:
    def test_without_romset(self):
        meta = NeoMeta(name="Test Game", manufacturer="SNK", year=1994, ngh=42, genre=9, screenshot=123)
        info = meta.format_info()
        assert "Test Game" in info
        assert "SNK" in info
        assert "1994" in info
        assert "NGH          : 42" in info
        assert "Fighting" in info  # genre 9
        assert "Screenshot #" in info
        assert "123" in info
        assert "MD5" not in info

    def test_with_romset_includes_sizes(self):
        import hashlib

        rs   = make_romset()
        meta = NeoMeta(name="Test")
        info = meta.format_info(rs)
        assert "P ROM" in info
        assert "C ROM" in info
        assert "Total" in info
        assert "P ROM MD5" in info
        assert hashlib.md5(rs.p).hexdigest() in info
        assert hashlib.md5(rs.s).hexdigest() in info
        assert hashlib.md5(rs.m).hexdigest() in info
        assert hashlib.md5(rs.v).hexdigest() in info
        assert hashlib.md5(rs.c).hexdigest() in info

    def test_with_split_v_romset_shows_split(self):
        rs = parse_neo(make_neo_with_v2_split())
        info = NeoMeta().format_info(rs)
        assert "V ROM split" in info
        assert "V1 3 bytes (ADPCM-A) + V2 2 bytes (ADPCM-B)" in info

    def test_without_v2_omits_split_line(self):
        rs = make_romset()
        assert "V ROM split" not in NeoMeta().format_info(rs)

    def test_all_genres_present(self):
        for genre_id, genre_name in GENRES.items():
            meta = NeoMeta(genre=genre_id)
            assert genre_name in meta.format_info()


# ---------------------------------------------------------------------------
# swap_p_banks
# ---------------------------------------------------------------------------

class TestSwapPBanks:
    def test_swap_reverses_halves(self):
        first  = make_rom(P_SWAP_SIZE // 2, 0xAA)
        second = make_rom(P_SWAP_SIZE // 2, 0xBB)
        p_rom  = first + second
        swapped = swap_p_banks(p_rom)
        assert swapped == second + first

    def test_swap_is_its_own_inverse(self):
        """Applying swap twice must return the original."""
        p_rom = make_rom(P_SWAP_SIZE, 0xCC)
        # Vary second half so the two halves are distinguishable
        p_rom = make_rom(P_SWAP_SIZE // 2, 0xAA) + make_rom(P_SWAP_SIZE // 2, 0xBB)
        assert swap_p_banks(swap_p_banks(p_rom)) == p_rom

    def test_wrong_size_raises(self):
        with pytest.raises(InvalidConfigurationError, match="2 MB"):
            swap_p_banks(make_rom(1024 * 1024))  # 1 MB — too small

    def test_wrong_size_4mb_raises(self):
        with pytest.raises(InvalidConfigurationError, match="2 MB"):
            swap_p_banks(make_rom(4 * 1024 * 1024))  # 4 MB — too large

    def test_apply_swap_p_auto_logs_via_callback(self):
        lines: list[str] = []
        p = _make_2mb_p_rom(valid_in_first=False)
        rs = RomSet(p=p, s=b"", m=b"", v=b"", c=b"")
        apply_swap_p(rs, SwapMode.AUTO, verbose=True, log=lines.append)
        assert any("auto-swap: YES" in line for line in lines)


# ---------------------------------------------------------------------------
# diagnostic mode
# ---------------------------------------------------------------------------

class TestDiagnosticMode:
    def test_missing_mandatory_rom_error_has_quick_tips(self, tmp_path):
        from neoconv.core import parse_mame_dir

        # Empty input: verify the actionable missing-role error text.
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_dir(tmp_path, diagnostic=False)

        msg = str(exc.value)
        assert "Missing mandatory ROM(s)" in msg
        assert "Quick tips:" in msg
        assert "game-p1.bin" in msg
        assert "game-s1.bin" in msg
        assert "game-m1.bin" in msg
        assert "--diagnostic" in msg

    def test_unrecognized_files_warn(self, tmp_path):
        import warnings
        from neoconv.core import parse_mame_dir

        # Write a valid set plus one unrecognized file
        (tmp_path / "game-p1.bin").write_bytes(make_rom(512 * 1024))
        (tmp_path / "game-s1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-m1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-v1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-c1.bin").write_bytes(make_rom(C_BANK_SIZE))
        (tmp_path / "game-c2.bin").write_bytes(make_rom(C_BANK_SIZE))
        (tmp_path / "readme.txt").write_bytes(b"hello")       # unrecognized
        (tmp_path / "000-lo.lo").write_bytes(make_rom(128 * 1024))  # known BIOS

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            parse_mame_dir(tmp_path, diagnostic=True, allow_extra_files=True)

        warned_names = [str(w.message) for w in caught]
        # Only the truly unrecognized file warns; known BIOS files are skipped.
        assert any("readme.txt" in m for m in warned_names)
        assert not any("000-lo.lo" in m for m in warned_names)

    def test_no_warnings_without_diagnostic(self, tmp_path):
        import warnings
        from neoconv.core import parse_mame_dir

        (tmp_path / "game-p1.bin").write_bytes(make_rom(512 * 1024))
        (tmp_path / "game-s1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-m1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-v1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-c1.bin").write_bytes(make_rom(C_BANK_SIZE))
        (tmp_path / "game-c2.bin").write_bytes(make_rom(C_BANK_SIZE))
        (tmp_path / "readme.txt").write_bytes(b"hello")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(InvalidRomLayoutError, match="Unrecognized file"):
                parse_mame_dir(tmp_path, diagnostic=False)

        assert len(caught) == 0

    def test_duplicate_role_in_directory_raises(self, tmp_path):
        from neoconv.core import parse_mame_dir

        # Both map to role "P" and should be rejected to avoid ambiguity.
        (tmp_path / "game-p1.bin").write_bytes(make_rom(512 * 1024))
        (tmp_path / "alt_p1.bin").write_bytes(make_rom(512 * 1024, 0xAB))
        (tmp_path / "game-s1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-m1.bin").write_bytes(make_rom(128 * 1024))

        with pytest.raises(InvalidRomLayoutError, match="Duplicate ROM role"):
            parse_mame_dir(tmp_path, diagnostic=False)

    def test_duplicate_role_in_zip_raises(self, tmp_path):
        from neoconv.core import parse_mame_zip

        zip_path = tmp_path / "dupe.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("game-p1.bin", make_rom(512 * 1024))
            zf.writestr("alt_p1.bin", make_rom(512 * 1024, 0xAB))
            zf.writestr("game-s1.bin", make_rom(128 * 1024))
            zf.writestr("game-m1.bin", make_rom(128 * 1024))

        with pytest.raises(InvalidRomLayoutError, match="Duplicate ROM role"):
            parse_mame_zip(zip_path, diagnostic=False)


# ---------------------------------------------------------------------------
# Fail-closed pack gates (1.5.2)
# ---------------------------------------------------------------------------

class TestUnsupportedSets:
    def test_list_matches_mame_xml_union(self):
        assert len(UNSUPPORTED_MAME_SETS) == 67
        assert UNSUPPORTED_MAME_SETS["mslug5"] == "encrypted-rom"
        assert UNSUPPORTED_MAME_SETS["kof98"] == "protected-rom"
        assert UNSUPPORTED_MAME_SETS["kotm2p"] == "c-part-layout"
        assert UNSUPPORTED_MAME_SETS["kf2k2mp"] == "audiocrypt"
        assert not any(name.startswith("boot_") for name in UNSUPPORTED_MAME_SETS)

    @pytest.mark.parametrize(
        "name", ["mslug5", "kof2003", "kotm2p", "viewpoinp", "stakwindev"]
    )
    def test_blocked_zip_fails_before_reading_members(self, tmp_path, name):
        z = tmp_path / f"{name}.zip"
        z.write_bytes(b"not a zip")  # gate must run before ZIP parsing
        with pytest.raises(UnsupportedRomSetError) as exc:
            parse_mame_zip(z)
        assert exc.value.code == "unsupported_rom_set"
        assert name in str(exc.value)
        assert "layout/decrypt" in (exc.value.hint or "")

    def test_blocked_zip_name_is_case_insensitive(self, tmp_path):
        z = tmp_path / "MSLUG5.zip"
        z.write_bytes(b"not a zip")
        with pytest.raises(UnsupportedRomSetError, match="MSLUG5"):
            parse_mame_zip(z)

    def test_blocked_directory_basename(self, tmp_path):
        d = tmp_path / "kotm2p"
        d.mkdir()
        with pytest.raises(UnsupportedRomSetError, match="kotm2p"):
            parse_mame_dir(d)

    def test_blocked_directory_dot_path_resolves_real_name(
        self, tmp_path, monkeypatch
    ):
        d = tmp_path / "mslug5"
        d.mkdir()
        monkeypatch.chdir(d)
        with pytest.raises(UnsupportedRomSetError, match="mslug5"):
            parse_mame_dir(Path("."))

    def test_boot_legacy_names_are_not_blocked(self, tmp_path):
        d = tmp_path / "boot_mslug5"
        d.mkdir()
        with pytest.raises(InvalidRomLayoutError, match="Missing mandatory"):
            parse_mame_dir(d)


class TestFailClosedPack:
    @pytest.mark.parametrize("allow_extra", [False, True])
    def test_samsho_extra_pg2_fails_instead_of_truncating_p(
        self, tmp_path, allow_extra
    ):
        z = tmp_path / "samsho_fixture.zip"
        write_role_zip(z, [
            ("045-p1.p1", make_rom(1024, 1)),
            ("045-pg2.sp2", make_rom(1024, 2)),
            ("045-s1.s1", make_rom(1024, 3)),
            ("045-m1.m1", make_rom(1024, 4)),
            ("045-v1.v1", make_rom(1024, 5)),
            ("045-c1.c1", make_rom(C_BANK_SIZE, 0x11)),
            ("045-c2.c2", make_rom(C_BANK_SIZE, 0x22)),
        ])
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z, allow_extra_files=allow_extra)
        assert "045-pg2.sp2" in str(exc.value)
        if allow_extra:
            assert "look like Neo Geo ROM data" in str(exc.value)
        else:
            assert "--allow-extra-files" in (exc.value.hint or "")

    @pytest.mark.parametrize("allow_extra", [False, True])
    def test_aof2a_extra_epr_fails(self, tmp_path, allow_extra):
        z = tmp_path / "aof2a_fixture.zip"
        write_role_zip(z, [
            ("056-p1.p1", make_rom(1024, 1)),
            ("056-epr.ep1", make_rom(1024, 2)),
            ("056-s1.s1", make_rom(1024, 3)),
            ("056-m1.m1", make_rom(1024, 4)),
            ("056-v1.v1", make_rom(1024, 5)),
            ("056-c1.c1", make_rom(C_BANK_SIZE, 0x11)),
            ("056-c2.c2", make_rom(C_BANK_SIZE, 0x22)),
        ])
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z, allow_extra_files=allow_extra)
        assert "056-epr.ep1" in str(exc.value)
        if allow_extra:
            assert "look like Neo Geo ROM data" in str(exc.value)

    @pytest.mark.parametrize("allow_extra", [False, True])
    def test_kof99_extra_neo_sma_fails(self, tmp_path, allow_extra):
        z = tmp_path / "kof99_fixture.zip"
        write_role_zip(z, [
            ("251-p1.p1", make_rom(1024, 1)),
            ("251-p2.p2", make_rom(1024, 2)),
            ("251-s1.s1", make_rom(1024, 3)),
            ("251-m1.m1", make_rom(1024, 4)),
            ("251-v1.v1", make_rom(1024, 5)),
            ("251-c1.c1", make_rom(C_BANK_SIZE, 0x11)),
            ("251-c2.c2", make_rom(C_BANK_SIZE, 0x22)),
            ("ka.neo-sma", make_rom(1024, 6)),
        ])
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z, allow_extra_files=allow_extra)
        assert "ka.neo-sma" in str(exc.value)
        if allow_extra:
            assert "look like Neo Geo ROM data" in str(exc.value)

    @pytest.mark.parametrize("allow_extra", [False, True])
    def test_nblktiger_v9_extra_fails(self, tmp_path, allow_extra):
        z = tmp_path / "nblktiger_fixture.zip"
        roles = [
            ("202-p1.bin", make_rom(1024, 1)),
            ("202-s1.bin", make_rom(1024, 2)),
            ("202-m1.bin", make_rom(1024, 3)),
        ]
        roles += [(f"202-v{i}.bin", make_rom(1024, i)) for i in range(1, 10)]
        roles += [
            (f"202-c{i}.bin", make_rom(C_BANK_SIZE, 0x10 + i))
            for i in range(1, 9)
        ]
        write_role_zip(z, roles)
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z, allow_extra_files=allow_extra)
        assert "202-v9.bin" in str(exc.value)
        if allow_extra:
            assert "look like Neo Geo ROM data" in str(exc.value)

    @pytest.mark.parametrize("allow_extra", [False, True])
    def test_viewpoinp_bare_names_fail(self, tmp_path, allow_extra):
        z = tmp_path / "viewpoint_proto_fixture.zip"
        roles = [("p1", b"p"), ("p2", b"p"), ("s1", b"s"), ("m1", b"m")]
        roles += [(f"v{i}", b"v") for i in range(1, 5)]
        roles += [
            (f"c{i}", make_rom(C_BANK_SIZE, i)) for i in range(1, 9)
        ]
        write_role_zip(z, roles)
        with pytest.raises(InvalidRomLayoutError, match="Unrecognized file"):
            parse_mame_zip(z, allow_extra_files=allow_extra)

    def test_stakwindev_bare_sp_names_fail(self, tmp_path):
        z = tmp_path / "stakwindev_fixture.zip"
        roles = [("sp1.sp1", b"p"), ("sp2.sp2", b"p")]
        roles += [("s1.s1", b"s"), ("m1.m1", b"m")]
        roles += [(f"v{i}.v{i}", b"v") for i in range(1, 4)]
        roles += [
            (f"c{i}.c{i}", make_rom(C_BANK_SIZE, i)) for i in range(1, 13)
        ]
        write_role_zip(z, roles)
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z)
        assert "sp1.sp1" in str(exc.value)

    @pytest.mark.parametrize("name", ["001-v11.v11", "001-v21.v21"])
    @pytest.mark.parametrize("allow_extra", [False, True])
    def test_adpcm_ab_v11_v21_naming_rejected(self, tmp_path, name, allow_extra):
        """ADPCM-A/B v11/v21 layouts need a region engine and must not be dropped."""
        z = tmp_path / "adpcm_ab_fixture.zip"
        write_complete_mame_zip(z, extra=((name, make_rom(1024, 0x77)),))
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z, allow_extra_files=allow_extra)
        msg = str(exc.value)
        assert name in msg
        assert "ADPCM-A/B" in msg
        assert "v1..v8" in (exc.value.hint or "")

    @pytest.mark.parametrize(
        "name", ["orochi-p21.bin", "lnsq-p21.bin", "5006-p2a.bin"]
    )
    def test_allow_extra_files_rejects_multidigit_p_names(self, tmp_path, name):
        """Multi-digit/letter P names are real P data, not disposable extras."""
        z = tmp_path / "multi_p_fixture.zip"
        write_complete_mame_zip(z, extra=((name, make_rom(1024, 0x66)),))
        with pytest.raises(
            InvalidRomLayoutError, match="look like Neo Geo ROM data"
        ) as exc:
            parse_mame_zip(z, allow_extra_files=True)
        assert name in str(exc.value)

    @pytest.mark.parametrize(
        "bios_name",
        [
            "000-lo.lo",
            "sfix.sfix",
            "sm1.sm1",
            "sp-s2.sp1",
            "sp1-u4.bin",
            "uni-bios_4_0.rom",
            "neo-epo.bin",
        ],
    )
    def test_known_bios_extras_pack_without_allow_flag_zip(
        self, tmp_path, bios_name
    ):
        z = tmp_path / "bios_fixture.zip"
        write_complete_mame_zip(z, extra=((bios_name, b"bios"),))
        rs = parse_mame_zip(z)
        assert rs.m == make_rom(128 * 1024)

    def test_known_bios_extras_pack_without_allow_flag_dir(self, tmp_path):
        (tmp_path / "game-p1.bin").write_bytes(make_rom(64 * 1024))
        (tmp_path / "game-s1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-m1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-v1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-c1.bin").write_bytes(make_rom(C_BANK_SIZE))
        (tmp_path / "game-c2.bin").write_bytes(make_rom(C_BANK_SIZE))
        for bios_name in ("000-lo.lo", "sfix.sfix", "sm1.sm1", "sp-s2.sp1"):
            (tmp_path / bios_name).write_bytes(b"bios")
        rs = parse_mame_dir(tmp_path)
        assert rs.m == make_rom(128 * 1024)

    def test_bios_sm1_does_not_override_real_m1(self, tmp_path):
        z = tmp_path / "sm1_first.zip"
        real_m = make_rom(128 * 1024, 0x5A)
        write_role_zip(z, [
            ("sm1.sm1", make_rom(1024, 0x99)),
            ("game-p1.bin", make_rom(64 * 1024)),
            ("game-s1.bin", make_rom(128 * 1024)),
            ("game-m1.bin", real_m),
            ("game-v1.bin", make_rom(128 * 1024)),
            ("game-c1.bin", make_rom(C_BANK_SIZE)),
            ("game-c2.bin", make_rom(C_BANK_SIZE)),
        ])
        assert parse_mame_zip(z).m == real_m

    def test_unknown_readme_still_fails_despite_bios_allowlist(self, tmp_path):
        z = tmp_path / "bios_and_readme.zip"
        write_complete_mame_zip(
            z,
            extra=(("000-lo.lo", b"bios"), ("readme.txt", b"x")),
        )
        with pytest.raises(InvalidRomLayoutError, match="readme.txt"):
            parse_mame_zip(z)

    def test_extra_file_fails_by_default(self, tmp_path):
        z = tmp_path / "set.zip"
        write_complete_mame_zip(z, extra=(("readme.txt", b"x"),))
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z)
        assert "readme.txt" in str(exc.value)
        assert "--allow-extra-files" in (exc.value.hint or "")

    def test_roles_to_romset_rejects_extra_source_filename(self):
        with pytest.raises(InvalidRomLayoutError, match="readme.txt"):
            roles_to_romset(
                {
                    "P": make_rom(64 * 1024),
                    "S": make_rom(1024),
                    "M": make_rom(1024),
                    "V1": make_rom(1024),
                    "C1": make_rom(C_BANK_SIZE, 0x11),
                    "C2": make_rom(C_BANK_SIZE, 0x22),
                },
                source_filenames=("game-p1.bin", "readme.txt"),
            )

    def test_diagnostic_does_not_override_extra_file_failure(self, tmp_path):
        z = tmp_path / "set.zip"
        write_complete_mame_zip(z, extra=(("readme.txt", b"x"),))
        with pytest.warns(UserWarning, match=r"\[diagnostic\]"):
            with pytest.raises(InvalidRomLayoutError, match="Unrecognized file"):
                parse_mame_zip(z, diagnostic=True)

    def test_allow_extra_files_succeeds_with_warning(self, tmp_path):
        z = tmp_path / "set.zip"
        write_complete_mame_zip(z, extra=(("readme.txt", b"x"),))
        with pytest.warns(UserWarning, match="Ignoring"):
            rs = parse_mame_zip(z, allow_extra_files=True)
        assert len(rs.p) == 64 * 1024
        assert len(rs.v) == 128 * 1024
        assert len(rs.c) == 2 * C_BANK_SIZE

    def test_mame_bios_neo_epo_is_silently_ignored(self, tmp_path):
        """``neo-epo.bin`` is a BIOS file, not an EP program-ROM role."""
        z = tmp_path / "set.zip"
        write_complete_mame_zip(z, extra=(("neo-epo.bin", b"bios"),))
        rs = parse_mame_zip(z)  # no --allow-extra-files needed
        assert len(rs.p) == 64 * 1024

    @pytest.mark.parametrize("name", ["game.ep1", "game.epr"])
    def test_ep_role_extras_remain_rom_like(self, tmp_path, name):
        z = tmp_path / "set.zip"
        write_complete_mame_zip(z, extra=((name, make_rom(1024)),))
        with pytest.raises(
            InvalidRomLayoutError, match="look like Neo Geo ROM data"
        ):
            parse_mame_zip(z, allow_extra_files=True)

    def test_extra_file_error_caps_long_list(self, tmp_path):
        extras = tuple((f"junk{i}.bin", b"x") for i in range(20))
        z = tmp_path / "set.zip"
        write_complete_mame_zip(z, extra=extras)
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z)
        msg = str(exc.value)
        assert "(20 files)" in msg
        assert "+8 more" in msg

    def test_empty_v_region_rejected(self):
        with pytest.raises(InvalidRomLayoutError, match=r"No V \(audio\) ROM"):
            roles_to_romset({
                "P": make_rom(64 * 1024),
                "S": make_rom(1024),
                "M": make_rom(1024),
                "C1": make_rom(C_BANK_SIZE, 0x11),
                "C2": make_rom(C_BANK_SIZE, 0x22),
            })

    def test_empty_c_region_rejected(self):
        with pytest.raises(InvalidRomLayoutError, match=r"No C \(sprite\) ROM"):
            roles_to_romset({
                "P": make_rom(64 * 1024),
                "S": make_rom(1024),
                "M": make_rom(1024),
                "V1": make_rom(1024),
            })

    @pytest.mark.parametrize("role", ["P", "S", "M"])
    def test_empty_required_role_rejected(self, role):
        roles = {
            "P": make_rom(64 * 1024),
            "S": make_rom(1024),
            "M": make_rom(1024),
            "V1": make_rom(1024),
            "C1": make_rom(C_BANK_SIZE, 0x11),
            "C2": make_rom(C_BANK_SIZE, 0x22),
        }
        roles[role] = b""
        with pytest.raises(InvalidRomLayoutError, match="Missing mandatory"):
            roles_to_romset(roles)

    def _write_unsynthesized_zip(self, tmp_path: Path) -> Path:
        z = tmp_path / "svc_fixture.zip"
        write_role_zip(z, [
            ("269-p1.p1", make_rom(1024, 1)),
            ("269-p2.p2", make_rom(1024, 2)),
            ("269-m1.m1", make_rom(1024, 3)),
            ("269-v1.v1", make_rom(1024, 4)),
            ("269-c1r.c1", make_rom(C_BANK_SIZE, 0x11)),
            ("269-c2r.c2", make_rom(C_BANK_SIZE, 0x22)),
        ])
        return z

    def test_synthetic_s_is_off_by_default(self, tmp_path):
        z = self._write_unsynthesized_zip(tmp_path)
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z)
        assert "Missing mandatory ROM(s)" in str(exc.value)
        assert "S" in str(exc.value)
        assert "--allow-synthetic-s" in (exc.value.hint or "")

    def test_allow_synthetic_s_still_warns_not_playable(self, tmp_path):
        z = self._write_unsynthesized_zip(tmp_path)
        with pytest.warns(UserWarning, match="No text-layer ROM") as caught:
            rs = parse_mame_zip(z, allow_synthetic_s=True)
        assert rs.s == b"\x00" * 0x80000
        assert any("NOT playable" in str(w.message) for w in caught)

    def test_zero_byte_s_is_treated_as_missing_and_can_be_synthesized(
        self, tmp_path
    ):
        z = tmp_path / "zero_byte_s.zip"
        write_role_zip(z, [
            ("game-p1.bin", make_rom(1024, 1)),
            ("game-s1.bin", b""),
            ("game-m1.bin", make_rom(1024, 3)),
            ("game-v1.bin", make_rom(1024, 4)),
            ("game-c1.bin", make_rom(C_BANK_SIZE, 0x11)),
            ("game-c2.bin", make_rom(C_BANK_SIZE, 0x22)),
        ])
        with pytest.raises(InvalidRomLayoutError) as exc:
            parse_mame_zip(z)
        assert "Missing mandatory ROM(s)" in str(exc.value)
        assert "--allow-synthetic-s" in (exc.value.hint or "")

        with pytest.warns(UserWarning, match="No text-layer ROM"):
            rs = parse_mame_zip(z, allow_synthetic_s=True)
        assert rs.s == b"\x00" * 0x20000


# ---------------------------------------------------------------------------
# detect_swap_p_needed
# ---------------------------------------------------------------------------

def _make_valid_vectors(sp: int = 0x0010F300, rst: int = 0x00C00402) -> bytes:
    """
    Build a plausible 8-byte M68000 vector table (SP + Reset PC) in
    MAME word-swapped storage format (odd byte first per 16-bit word).
    """
    sp_be  = sp.to_bytes(4, "big")
    rst_be = rst.to_bytes(4, "big")
    native = sp_be + rst_be  # big-endian as the 68k sees it
    # Word-swap to MAME storage format
    swapped = bytearray(8)
    for i in range(0, 8, 2):
        swapped[i]     = native[i + 1]
        swapped[i + 1] = native[i]
    return bytes(swapped)


def _make_2mb_p_rom(valid_in_first: bool) -> bytes:
    """
    Return a synthetic 2 MB P-ROM where exactly one half contains a
    valid M68k vector table in MAME word-swapped format.
    """
    HALF = P_SWAP_SIZE // 2
    valid_half   = _make_valid_vectors() + make_rom(HALF - 8, 0x00)
    invalid_half = make_rom(HALF, 0xFF)  # 0xFFFF… is not a valid SP/Reset
    if valid_in_first:
        return valid_half + invalid_half
    else:
        return invalid_half + valid_half


class TestDetectSwapP:
    def test_valid_first_half_no_swap(self):
        from neoconv.core import detect_swap_p_needed
        p = _make_2mb_p_rom(valid_in_first=True)
        needed, reason = detect_swap_p_needed(p)
        assert not needed
        assert "no swap" in reason.lower() or "first half" in reason.lower()

    def test_valid_second_half_swap_needed(self):
        from neoconv.core import detect_swap_p_needed
        p = _make_2mb_p_rom(valid_in_first=False)
        needed, reason = detect_swap_p_needed(p)
        assert needed
        assert "swap" in reason.lower()

    def test_non_2mb_returns_false(self):
        from neoconv.core import detect_swap_p_needed
        for size in [512 * 1024, 1024 * 1024, 4 * 1024 * 1024]:
            needed, reason = detect_swap_p_needed(make_rom(size))
            assert not needed
            assert "not 2 mb" in reason.lower() or "2 mb" in reason.lower()

    def test_neither_valid_returns_false(self):
        from neoconv.core import detect_swap_p_needed
        # All 0xFF — no valid vectors anywhere
        p = make_rom(P_SWAP_SIZE, 0xFF)
        needed, reason = detect_swap_p_needed(p)
        assert not needed
        assert "inconclusive" in reason.lower() or "neither" in reason.lower()

    def test_both_valid_prefers_first_no_swap(self):
        from neoconv.core import detect_swap_p_needed
        HALF = P_SWAP_SIZE // 2
        half1 = _make_valid_vectors(sp=0x0010F300, rst=0x00000200) + make_rom(HALF - 8, 0x00)
        half2 = _make_valid_vectors(sp=0x0010E000, rst=0x00100200) + make_rom(HALF - 8, 0x00)
        p = half1 + half2
        needed, reason = detect_swap_p_needed(p)
        assert not needed  # first half preferred

    def test_bios_reset_vector_accepted(self):
        """Reset vector pointing into BIOS (0xC00000-0xC7FFFF) must be valid."""
        from neoconv.core import detect_swap_p_needed
        # KOF94/NTM pattern: SP in RAM, Reset in BIOS
        p = _make_2mb_p_rom(valid_in_first=False)  # valid in second half
        needed, _ = detect_swap_p_needed(p)
        assert needed

    def test_auto_swap_applies_when_needed(self):
        """mame_zip_to_neo with swap_p='auto' swaps only when needed."""
        from neoconv.core import RomSet, NeoMeta, build_neo, apply_swap_p
        p_with_valid_second = _make_2mb_p_rom(valid_in_first=False)
        rs = RomSet(
            p=p_with_valid_second,
            s=make_rom(128 * 1024),
            m=make_rom(128 * 1024),
            v=make_rom(2 * 1024 * 1024),
            c=interleave_c_chips([make_rom(C_BANK_SIZE), make_rom(C_BANK_SIZE)]),
        )
        rs_after = apply_swap_p(rs, SwapMode.AUTO, verbose=False)
        HALF = P_SWAP_SIZE // 2
        # After auto-swap the first half must be the originally-second half
        assert rs_after.p[:HALF] == p_with_valid_second[HALF:]

    def test_auto_swap_no_op_when_not_needed(self):
        from neoconv.core import RomSet, apply_swap_p
        p_with_valid_first = _make_2mb_p_rom(valid_in_first=True)
        rs = RomSet(
            p=p_with_valid_first,
            s=make_rom(128 * 1024),
            m=make_rom(128 * 1024),
            v=make_rom(2 * 1024 * 1024),
            c=interleave_c_chips([make_rom(C_BANK_SIZE), make_rom(C_BANK_SIZE)]),
        )
        rs_after = apply_swap_p(rs, SwapMode.AUTO, verbose=False)
        assert rs_after.p == p_with_valid_first  # unchanged

    def test_auto_swap_inconclusive_emits_warning(self):
        from neoconv.core import RomSet, apply_swap_p

        rs = RomSet(p=make_rom(P_SWAP_SIZE, 0xFF))
        with pytest.warns(UserWarning, match="inconclusive"):
            apply_swap_p(rs, SwapMode.AUTO, verbose=False)


class TestPackPreflight:
    def test_collect_pack_sequence_issues_v_gap(self):
        from neoconv.core import collect_pack_sequence_issues

        issues = collect_pack_sequence_issues(
            ["game-v1.bin", "game-v3.bin", "game-p1.bin"]
        )
        assert any("V2" in m for m in issues)

    def test_collect_pack_sequence_issues_clean(self):
        from neoconv.core import collect_pack_sequence_issues

        assert collect_pack_sequence_issues(["game-v1.bin", "game-v2.bin"]) == []


# ---------------------------------------------------------------------------
# End-to-end roundtrip tests
# ---------------------------------------------------------------------------

class TestEndToEndRoundtrip:
    """
    Full pipeline tests: build_neo -> extract_neo_to_zip -> parse_mame_zip
    -> build_neo -> verify_roundtrip.

    These catch regressions that unit tests on individual steps cannot:
    interleave/de-interleave symmetry across the full stack, header
    serialisation, and ZIP packing/parsing consistency.
    """

    def _make_meta(self) -> NeoMeta:
        return NeoMeta(name="RoundtripGame", manufacturer="SNK", year=1995, ngh=99, genre=9)

    def test_roundtrip_mame_zip(self, tmp_path):
        """build_neo -> extract to MAME ZIP -> parse_mame_zip -> build_neo -> identical ROM data."""
        meta = self._make_meta()
        romset = make_romset()
        original_neo = build_neo(romset, meta)

        # Extract to a MAME ZIP in memory, write it so parse_mame_zip can read it
        zip_bytes = extract_neo_to_zip(original_neo, name_prefix="rtrip", fmt="mame")
        zip_path = tmp_path / "rtrip.zip"
        zip_path.write_bytes(zip_bytes)

        # Re-parse and rebuild
        reparsed = parse_mame_zip(zip_path)
        rebuilt_neo = build_neo(reparsed, meta)

        result = verify_roundtrip(original_neo, rebuilt_neo)
        assert result.ok, f"Roundtrip failed: {result.details}"

    def test_roundtrip_mame_dir(self, tmp_path):
        """build_neo -> extract to directory -> parse_mame_dir -> build_neo -> identical ROM data."""
        meta = self._make_meta()
        romset = make_romset()
        original_neo = build_neo(romset, meta)

        out_dir = tmp_path / "roms"
        extract_neo(original_neo, out_dir, name_prefix="rtrip", fmt="mame")

        reparsed = parse_mame_dir(out_dir)
        rebuilt_neo = build_neo(reparsed, meta)

        result = verify_roundtrip(original_neo, rebuilt_neo)
        assert result.ok, f"Roundtrip failed: {result.details}"

    def test_roundtrip_darksoft_zip(self, tmp_path):
        """Same pipeline with Darksoft (.rom) naming."""
        meta = self._make_meta()
        romset = make_romset()
        original_neo = build_neo(romset, meta)

        zip_bytes = extract_neo_to_zip(original_neo, name_prefix="rtrip", fmt="darksoft")
        zip_path = tmp_path / "rtrip_ds.zip"
        zip_path.write_bytes(zip_bytes)

        reparsed = parse_mame_zip(zip_path)
        rebuilt_neo = build_neo(reparsed, meta)

        result = verify_roundtrip(original_neo, rebuilt_neo)
        assert result.ok, f"Darksoft roundtrip failed: {result.details}"

    def test_roundtrip_multi_v_and_c(self, tmp_path):
        """Roundtrip with multiple V banks and C chip pairs (4 chips total)."""
        meta = self._make_meta()
        c1, c2, c3, c4 = (make_rom(C_BANK_SIZE, b) for b in (0x11, 0x22, 0x33, 0x44))
        romset = RomSet(
            p=make_rom(1024 * 1024, 0xAA),
            s=make_rom(128 * 1024, 0xBB),
            m=make_rom(128 * 1024, 0xCC),
            v=make_rom(4 * 1024 * 1024, 0xDD),   # two 2 MB V banks
            c=interleave_c_chips([c1, c2, c3, c4]),
        )
        original_neo = build_neo(romset, meta)

        zip_bytes = extract_neo_to_zip(original_neo, name_prefix="rtrip", fmt="mame")
        zip_path = tmp_path / "rtrip_multi.zip"
        zip_path.write_bytes(zip_bytes)

        reparsed = parse_mame_zip(zip_path)
        rebuilt_neo = build_neo(reparsed, meta)

        result = verify_roundtrip(original_neo, rebuilt_neo)
        assert result.ok, f"Multi V/C roundtrip failed: {result.details}"

    def test_parse_rejects_no_v_no_c(self, tmp_path):
        """A .neo with empty V/C can still exist, but re-packing must fail."""
        meta = self._make_meta()
        romset = RomSet(
            p=make_rom(512 * 1024, 0xAA),
            s=make_rom(128 * 1024, 0xBB),
            m=make_rom(128 * 1024, 0xCC),
            v=b"",
            c=b"",
        )
        original_neo = build_neo(romset, meta)

        zip_bytes = extract_neo_to_zip(original_neo, name_prefix="rtrip", fmt="mame")
        zip_path = tmp_path / "rtrip_novc.zip"
        zip_path.write_bytes(zip_bytes)

        with pytest.raises(InvalidRomLayoutError, match="No V \\(audio\\) ROM"):
            parse_mame_zip(zip_path)

    def test_swap_p_roundtrip(self, tmp_path):
        """Swapping P-ROM and then re-swapping must reproduce the original."""
        meta = self._make_meta()
        p_orig = make_rom(P_SWAP_SIZE // 2, 0xAA) + make_rom(P_SWAP_SIZE // 2, 0xBB)
        romset = RomSet(
            p=p_orig,
            s=make_rom(128 * 1024, 0xBB),
            m=make_rom(128 * 1024, 0xCC),
            v=make_rom(2 * 1024 * 1024, 0xDD),
            c=interleave_c_chips([make_rom(C_BANK_SIZE), make_rom(C_BANK_SIZE)]),
        )
        # swap once -> swap again -> must be identical to original
        from neoconv.core import swap_p_banks
        swapped = swap_p_banks(p_orig)
        assert swapped != p_orig
        assert swap_p_banks(swapped) == p_orig

        # Full neo roundtrip with swap applied
        from neoconv.core import apply_swap_p
        import dataclasses
        rs_swapped = apply_swap_p(romset, SwapMode.YES, verbose=False)
        original_neo = build_neo(rs_swapped, meta)

        zip_bytes = extract_neo_to_zip(original_neo, name_prefix="rtrip", fmt="mame")
        zip_path = tmp_path / "rtrip_swap.zip"
        zip_path.write_bytes(zip_bytes)

        reparsed = parse_mame_zip(zip_path)
        rebuilt_neo = build_neo(reparsed, meta)

        result = verify_roundtrip(original_neo, rebuilt_neo)
        assert result.ok, f"Swap roundtrip failed: {result.details}"


# ---------------------------------------------------------------------------
# Wave 3: extraction safety, atomic writes, P-only ZIP reading
# ---------------------------------------------------------------------------

class TestExtractionSafety:
    @pytest.mark.parametrize(
        "prefix",
        ["game", "038", "a.b-c_d", "turfmast", "ünïcode"],
    )
    def test_validate_name_prefix_accepts_plain_component(self, prefix):
        assert validate_name_prefix(prefix) == prefix

    @pytest.mark.skipif(os.name == "nt", reason="':' is invalid in Windows filenames")
    def test_validate_name_prefix_allows_posix_colon(self, tmp_path):
        assert validate_name_prefix("foo:bar") == "foo:bar"

        rs = make_romset()
        written = extract_romset(
            rs,
            tmp_path / "out",
            name_prefix="foo:bar",
            v_bank_size=1024 * 1024,
        )
        assert written["p1"].name == "foo:bar-p1.bin"
        assert written["p1"].exists()

    @pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges")
    def test_directory_extract_replaces_symlink_without_following(self, tmp_path):
        """A planted symlink in --out-dir must not redirect a write outside it."""
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"original")
        out = tmp_path / "out"
        out.mkdir()
        link = out / "game-p1.bin"
        link.symlink_to(outside)

        rs = make_romset()
        with pytest.warns(UserWarning, match="Overwriting existing file"):
            extract_romset(rs, out, name_prefix="game", v_bank_size=1024 * 1024)

        assert outside.read_bytes() == b"original"
        assert not link.is_symlink()
        assert link.is_file()
        assert link.read_bytes() == rs.p

    @pytest.mark.parametrize(
        "prefix",
        [
            "",
            ".",
            "..",
            "../evil",
            "..\\evil",
            "/tmp/evil",
            "C:evil",
            "z:evil",
            "C:\\temp\\evil",
            "sub/evil",
            "sub\\evil",
            "bad\x00name",
            "bad\nname",
            "bad\x1fname",
            "bad\x7fname",
        ],
    )
    def test_validate_name_prefix_rejects_unsafe(self, prefix):
        with pytest.raises(InvalidConfigurationError, match="prefix"):
            validate_name_prefix(prefix)

    def test_validate_name_prefix_rejects_non_string(self):
        with pytest.raises(InvalidConfigurationError, match="must be a string"):
            validate_name_prefix(None)  # type: ignore[arg-type]

    def test_extract_romset_rejects_unsafe_prefix_without_writing(self, tmp_path):
        rs = make_romset()
        cases = [
            "../evil",
            "..\\evil",
            str(tmp_path / "evil"),
            "C:evil",
            "sub/evil",
            "sub\\evil",
            ".",
            "..",
            "",
            "bad\x00name",
        ]
        for i, prefix in enumerate(cases):
            out = tmp_path / f"out{i}"
            with pytest.raises(InvalidConfigurationError, match="prefix"):
                extract_romset(rs, out, name_prefix=prefix, v_bank_size=1024 * 1024)
            assert not out.exists()
        # Nothing (not even "evil-p1.bin") escaped next to the output directory.
        assert sorted(p.name for p in tmp_path.iterdir()) == []

    def test_extract_romset_to_zip_rejects_unsafe_prefix(self, tmp_path):
        rs = make_romset()
        for prefix in ["../evil", "..\\evil", str(tmp_path / "evil"), "C:evil"]:
            with pytest.raises(InvalidConfigurationError, match="prefix"):
                extract_romset_to_zip(
                    rs, name_prefix=prefix, v_bank_size=1024 * 1024
                )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"c_chip_size": 100},
            {"p_chip_sizes": [1024]},
            {"v_bank_sizes": [1024]},
        ],
    )
    def test_invalid_split_leaves_no_output_files(self, tmp_path, kwargs):
        rs = make_romset()
        out = tmp_path / "out"

        with pytest.raises(InvalidConfigurationError):
            extract_romset(rs, out, name_prefix="g", **kwargs)

        assert not out.exists()

        with pytest.raises(InvalidConfigurationError):
            extract_romset_to_zip(rs, name_prefix="g", **kwargs)

    def test_invalid_c_does_not_leave_p_s_m_v(self, tmp_path):
        rs = RomSet(
            p=make_rom(4096, 0xAA),
            s=make_rom(128, 0xBB),
            m=make_rom(128, 0xCC),
            v=make_rom(256, 0xDD),
            c=b"\x00" * 100,  # not a multiple of chip_size * 2
        )
        out = tmp_path / "out"
        with pytest.raises(InvalidConfigurationError, match="not a multiple"):
            extract_romset(rs, out, name_prefix="g", v_bank_size=256)

        assert not out.exists()
        assert list(tmp_path.iterdir()) == []

    def test_existing_output_survives_validation_failure(self, tmp_path):
        rs = RomSet(
            p=make_rom(4096, 0xAA),
            s=make_rom(128, 0xBB),
            m=make_rom(128, 0xCC),
            v=make_rom(256, 0xDD),
            c=b"\x00" * 100,
        )
        out = tmp_path / "out"
        out.mkdir()
        existing = out / "g-p1.bin"
        existing.write_bytes(b"KEEP")

        with pytest.raises(InvalidConfigurationError):
            extract_romset(rs, out, name_prefix="g", v_bank_size=256)

        assert existing.read_bytes() == b"KEEP"
        assert sorted(p.name for p in out.iterdir()) == ["g-p1.bin"]


class TestWriteBytesAtomicHardening:
    def test_replaces_content(self, tmp_path):
        p = tmp_path / "out.neo"
        write_bytes_atomic(p, b"alpha")
        write_bytes_atomic(p, b"beta")
        assert p.read_bytes() == b"beta"

    def test_writes_exact_bytes_without_newline_translation(self, tmp_path):
        p = tmp_path / "binary.neo"
        payload = b"\n\r\n\x00"
        write_bytes_atomic(p, payload)
        assert p.read_bytes() == payload

    def test_opens_temp_file_with_o_binary(self, monkeypatch, tmp_path):
        # Simulate the Windows-only O_BINARY flag so the flag wiring is
        # checked on every platform, not just where it changes behavior.
        real_open = os.open
        seen: list[int] = []
        if hasattr(os, "O_BINARY"):
            binary_flag, strip = os.O_BINARY, 0
        else:
            binary_flag = strip = 0x40000000
            monkeypatch.setattr(os, "O_BINARY", binary_flag, raising=False)

        def _open(path, flags, mode=0o777, *args, **kwargs):
            seen.append(flags)
            return real_open(path, flags & ~strip, mode, *args, **kwargs)

        monkeypatch.setattr("neoconv.core.neo_format.os.open", _open)
        p = tmp_path / "flags.neo"
        write_bytes_atomic(p, b"\n")
        assert seen and seen[0] & binary_flag
        assert p.read_bytes() == b"\n"

    def test_preserves_existing_file_mode(self, tmp_path):
        p = tmp_path / "existing.neo"
        p.write_bytes(b"old")
        os.chmod(p, 0o600)
        try:
            write_bytes_atomic(p, b"new")
            assert p.read_bytes() == b"new"
            assert stat.S_IMODE(p.stat().st_mode) == 0o600
        finally:
            os.chmod(p, 0o600)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
    def test_mode_copy_failure_is_best_effort(self, monkeypatch, tmp_path):
        p = tmp_path / "mode-less.neo"
        p.write_bytes(b"old")
        os.chmod(p, 0o600)

        def _fail(*_args, **_kwargs):
            raise OSError("mode-less mount")

        monkeypatch.setattr("neoconv.core.neo_format.os.fchmod", _fail, raising=False)
        monkeypatch.setattr("neoconv.core.neo_format.os.chmod", _fail, raising=False)

        old = os.umask(0)
        try:
            write_bytes_atomic(p, b"new")
        finally:
            os.umask(old)

        assert p.read_bytes() == b"new"
        # Mode preservation failed, so the umask-derived temp mode is kept.
        assert stat.S_IMODE(p.stat().st_mode) == 0o666

    @pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
    def test_new_file_mode_follows_umask(self, tmp_path):
        p = tmp_path / "new-file.neo"
        old = os.umask(0o077)
        try:
            write_bytes_atomic(p, b"x")
        finally:
            os.umask(old)
        assert stat.S_IMODE(p.stat().st_mode) == 0o600

        q = tmp_path / "new-file-umask-zero.neo"
        old = os.umask(0)
        try:
            write_bytes_atomic(q, b"y")
        finally:
            os.umask(old)
        assert stat.S_IMODE(q.stat().st_mode) == 0o666

    def test_does_not_modify_symlink_target(self, tmp_path):
        target = tmp_path / "target.bin"
        target.write_bytes(b"original")
        link = tmp_path / "link.neo"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):  # pragma: no cover - platform
            pytest.skip("symlinks are not available")

        write_bytes_atomic(link, b"new")

        assert target.read_bytes() == b"original"
        assert not link.is_symlink()
        assert link.read_bytes() == b"new"

    def test_cleans_up_temp_file_on_failure(self, tmp_path):
        target_dir = tmp_path / "target.neo"
        target_dir.mkdir()
        with pytest.raises(OSError):
            write_bytes_atomic(target_dir, b"x")
        assert sorted(p.name for p in tmp_path.iterdir()) == ["target.neo"]


class TestPOnlyZipReader:
    def test_p_only_zip(self, tmp_path):
        z = tmp_path / "p_only.zip"
        write_role_zip(z, [("game-p1.bin", b"PROGRAM")])
        assert read_p_rom_from_zip(z) == b"PROGRAM"

    def test_concatenates_p1_and_p2_in_order(self, tmp_path):
        z = tmp_path / "full.zip"
        write_role_zip(
            z,
            [
                ("game-s1.bin", b"TEXT"),
                ("game-p2.bin", b"SECOND"),
                ("game-p1.bin", b"FIRST"),
                ("game-m1.bin", b"Z80"),
            ],
        )
        assert read_p_rom_from_zip(z) == b"FIRSTSECOND"

    def test_bypasses_denylist_and_missing_other_roms(self, tmp_path):
        z = tmp_path / "kotm2p.zip"
        write_role_zip(z, [("kotm2p-p1.bin", b"P")])
        assert read_p_rom_from_zip(z) == b"P"

    def test_missing_p_raises_typed_error(self, tmp_path):
        z = tmp_path / "no_p.zip"
        write_role_zip(z, [("game-s1.bin", b"S"), ("game-m1.bin", b"M")])
        with pytest.raises(InvalidRomLayoutError, match="No P \\(program\\) ROM"):
            read_p_rom_from_zip(z)

    def test_bad_zip_raises_typed_error(self, tmp_path):
        z = tmp_path / "not.zip"
        z.write_bytes(b"not a zip")
        with pytest.raises(InvalidRomLayoutError, match="Cannot open ZIP file"):
            read_p_rom_from_zip(z)

    @pytest.mark.parametrize("role", ["p1", "p2"])
    def test_duplicate_role_members_raise_clear_error(self, tmp_path, role):
        z = tmp_path / "duplicate.zip"
        write_role_zip(
            z,
            [
                (f"game-{role}.bin", b"FIRST"),
                (f"folder/game-{role}.bin", b"SECOND"),
            ],
        )
        with pytest.raises(InvalidRomLayoutError, match="Duplicate"):
            read_p_rom_from_zip(z)

    def test_duplicate_member_names_do_not_inflate_data(self, tmp_path):
        z = tmp_path / "same-name.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("game-p1.bin", b"FIRST")
            with pytest.warns(UserWarning, match="Duplicate name"):
                zf.writestr("game-p1.bin", b"SECOND")

        with pytest.raises(InvalidRomLayoutError, match="Duplicate P ROM"):
            read_p_rom_from_zip(z)

    def test_corrupt_member_raises_typed_error(self, tmp_path):
        z = tmp_path / "corrupt.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("game-p1.bin", b"PROGRAM ROM " * 2048)
        corrupt_zip_member_data(z)

        with pytest.raises(InvalidRomLayoutError, match="Cannot open ZIP file"):
            read_p_rom_from_zip(z)
        with pytest.raises(InvalidRomLayoutError, match="Cannot open ZIP file"):
            parse_mame_zip(z)

    def test_parse_mame_zip_duplicate_p_members_raise(self, tmp_path):
        z = tmp_path / "duplicate-set.zip"
        write_role_zip(
            z,
            [
                ("game-p1.bin", b"P"),
                ("folder/game-p1.bin", b"P"),
                ("game-s1.bin", b"S"),
                ("game-m1.bin", b"M"),
                ("game-v1.bin", b"V"),
                ("game-c1.bin", b"C"),
                ("game-c2.bin", b"C"),
            ],
        )
        with pytest.raises(InvalidRomLayoutError, match="Duplicate ROM role 'P'"):
            parse_mame_zip(z)


class TestParseUint32:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("0", 0),
            ("4294967295", 0xFFFFFFFF),
            (" 1994 ", 1994),
            ("0x0FFFFFFFF", 0xFFFFFFFF),
            ("0XFF", 0xFF),
            ("0o777", 0o777),
            ("0b1010", 10),
            ("0042", 42),
        ],
    )
    def test_accepts(self, text, expected):
        assert parse_uint32(text) == expected

    @pytest.mark.parametrize(
        "text", ["", "-1", "4294967296", "0x100000000", "abc", "0x", "1e3", "-0x1"]
    )
    def test_rejects(self, text):
        with pytest.raises(ValueError, match="between 0 and 4294967295"):
            parse_uint32(text)
