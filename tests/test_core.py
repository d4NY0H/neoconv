"""
Unit tests for neoconv.core
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Run with:  python -m pytest tests/ -v
"""

import hashlib
import io
import struct
import zipfile
from pathlib import Path

import pytest

from neoconv.core import (
    C_BANK_SIZE,
    NEO_HEADER_SIZE,
    NEO_MAGIC,
    GENRES,
    NeoMeta,
    RomSet,
    _interleave_c_chips,
    _name_to_role,
    _roles_to_romset,
    build_neo,
    extract_neo_to_zip,
    parse_neo,
    verify_roundtrip,
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
    c_interleaved = _interleave_c_chips(c_chips[:2])  # one bank for simplicity

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


# ---------------------------------------------------------------------------
# _name_to_role
# ---------------------------------------------------------------------------

class TestNameToRole:
    def test_extension_based(self):
        assert _name_to_role("054-p1.p1") == "P"
        assert _name_to_role("054-s1.s1") == "S"
        assert _name_to_role("054-m1.m1") == "M"
        assert _name_to_role("054-v1.v1") == "V1"
        assert _name_to_role("054-v4.v4") == "V4"
        assert _name_to_role("054-c1.c1") == "C1"
        assert _name_to_role("054-c2.c2") == "C2"

    def test_bin_suffix(self):
        assert _name_to_role("zin-p1.bin") == "P"
        assert _name_to_role("zin-s1.bin") == "S"
        assert _name_to_role("zin-m1.bin") == "M"
        assert _name_to_role("zin-v2.bin") == "V2"
        assert _name_to_role("zin-c1.bin") == "C1"
        assert _name_to_role("zin-c2.bin") == "C2"

    def test_rom_suffix(self):
        assert _name_to_role("zin-p1.rom") == "P"
        assert _name_to_role("zin-c4.rom") == "C4"

    def test_unknown(self):
        assert _name_to_role("neogeo.zip") is None
        assert _name_to_role("000-lo.lo") is None
        assert _name_to_role("sfix.sfix") is None

    def test_case_insensitive(self):
        assert _name_to_role("ZIN-P1.BIN") == "P"
        assert _name_to_role("ZIN-C1.C1") == "C1"


# ---------------------------------------------------------------------------
# C ROM interleaving / de-interleaving
# ---------------------------------------------------------------------------

class TestCRomInterleaving:
    def test_roundtrip_single_bank(self):
        """De-interleave then re-interleave must produce identical bytes."""
        c1 = make_rom(C_BANK_SIZE, 0x11)
        c2 = make_rom(C_BANK_SIZE, 0x22)
        interleaved = _interleave_c_chips([c1, c2])

        assert len(interleaved) == C_BANK_SIZE * 2
        # Even bytes = c1, odd bytes = c2
        assert bytes(interleaved[0::2]) == c1
        assert bytes(interleaved[1::2]) == c2

        # RomSet.c_chips() de-interleaves back
        rs = RomSet(c=interleaved)
        chips = rs.c_chips()
        assert chips[0] == c1
        assert chips[1] == c2

    def test_roundtrip_two_banks(self):
        c1 = make_rom(C_BANK_SIZE, 0x11)
        c2 = make_rom(C_BANK_SIZE, 0x22)
        c3 = make_rom(C_BANK_SIZE, 0x33)
        c4 = make_rom(C_BANK_SIZE, 0x44)
        interleaved = _interleave_c_chips([c1, c2, c3, c4])

        rs = RomSet(c=interleaved)
        chips = rs.c_chips()
        assert chips == [c1, c2, c3, c4]

    def test_size_mismatch_raises(self):
        with pytest.raises(ValueError, match="size mismatch"):
            _interleave_c_chips([make_rom(C_BANK_SIZE), make_rom(C_BANK_SIZE // 2)])

    def test_odd_chip_count_raises(self):
        with pytest.raises(ValueError, match="[Oo]dd"):
            _roles_to_romset({
                "P": make_rom(512 * 1024),
                "S": make_rom(128 * 1024),
                "M": make_rom(128 * 1024),
                "C1": make_rom(C_BANK_SIZE),
                # C2 intentionally missing
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
        with pytest.raises(ValueError, match="Not a valid .neo"):
            parse_neo(b"BAD!" + bytes(NEO_HEADER_SIZE))

    def test_truncated_file_raises(self):
        rs = make_romset()
        neo = make_neo(rs)
        with pytest.raises(ValueError):
            parse_neo(neo[:-100])  # truncate last 100 bytes


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
        """8 MB V ROM should produce v1 + v2."""
        rs = make_romset(v_size=8 * 1024 * 1024)
        neo = make_neo(rs)
        zip_bytes = extract_neo_to_zip(neo, name_prefix="x", fmt="mame")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert "x-v1.bin" in names
        assert "x-v2.bin" in names
        assert "x-v3.bin" not in names


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
        meta = NeoMeta(name="Test Game", manufacturer="SNK", year=1994, ngh=42, genre=9)
        info = meta.format_info()
        assert "Test Game" in info
        assert "SNK" in info
        assert "1994" in info
        assert "0x002A" in info
        assert "Fighting" in info  # genre 9

    def test_with_romset_includes_sizes(self):
        rs   = make_romset()
        meta = NeoMeta(name="Test")
        info = meta.format_info(rs)
        assert "P ROM" in info
        assert "C ROM" in info
        assert "Total" in info

    def test_all_genres_present(self):
        for genre_id, genre_name in GENRES.items():
            meta = NeoMeta(genre=genre_id)
            assert genre_name in meta.format_info()
