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
    P_SWAP_SIZE,
    apply_swap_p,
    check_m68k_vectors,
    interleave_c_chips,
    name_to_role,
    roles_to_romset,
    build_neo,
    extract_neo_to_zip,
    extract_romset,
    extract_romset_to_zip,
    neo_to_darksoft_zip,
    neo_to_mame_zip,
    parse_mame_dir,
    parse_mame_zip,
    parse_neo,
    parse_neo_header_metadata,
    replace_neo_metadata,
    swap_p_banks,
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
        with pytest.raises(ValueError, match="not a multiple"):
            rs.c_chips(chip_size=C_BANK_SIZE + 1)

    def test_size_mismatch_raises(self):
        with pytest.raises(ValueError, match="size mismatch"):
            interleave_c_chips([make_rom(C_BANK_SIZE), make_rom(C_BANK_SIZE // 2)])

    def test_odd_chip_count_raises(self):
        with pytest.raises(ValueError, match="[Oo]dd"):
            roles_to_romset({
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

    def test_file_shorter_than_header_raises(self):
        data = NEO_MAGIC + b"\x00" * 64
        assert len(data) < NEO_HEADER_SIZE
        with pytest.raises(ValueError, match="too small"):
            parse_neo(data)

    def test_parse_neo_appends_optional_v2_region(self):
        """Header may split V data across v1_size and v2_size (uncommon but supported)."""
        h = bytearray(NEO_HEADER_SIZE)
        h[0:4] = NEO_MAGIC
        struct.pack_into("<I", h, 0x04, 0)
        struct.pack_into("<I", h, 0x08, 0)
        struct.pack_into("<I", h, 0x0C, 0)
        struct.pack_into("<I", h, 0x10, 3)
        struct.pack_into("<I", h, 0x14, 2)
        struct.pack_into("<I", h, 0x18, 0)
        struct.pack_into("<H", h, 0x1C, 1999)
        struct.pack_into("<H", h, 0x1E, 0)
        struct.pack_into("<I", h, 0x20, 0)
        struct.pack_into("<I", h, 0x24, 0)
        neo = bytes(h) + b"AAA" + b"bb"
        with pytest.warns(UserWarning, match="splits the V ROM"):
            rs = parse_neo(neo)
        assert rs.v == b"AAAbb"


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
        with pytest.raises(ValueError, match="too small"):
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

    def test_replace_neo_metadata_split_v_header_matches_build_neo(self):
        """Rare V1/V2 split in header must match parse+build reference output."""
        h = bytearray(NEO_HEADER_SIZE)
        h[0:4] = NEO_MAGIC
        struct.pack_into("<I", h, 0x04, 0)
        struct.pack_into("<I", h, 0x08, 0)
        struct.pack_into("<I", h, 0x0C, 0)
        struct.pack_into("<I", h, 0x10, 3)
        struct.pack_into("<I", h, 0x14, 2)
        struct.pack_into("<I", h, 0x18, 0)
        struct.pack_into("<H", h, 0x1C, 1999)
        struct.pack_into("<H", h, 0x1E, 0)
        struct.pack_into("<I", h, 0x20, 0)
        struct.pack_into("<I", h, 0x24, 0)
        neo = bytes(h) + b"AAA" + b"bb"
        with pytest.warns(UserWarning, match="splits the V ROM"):
            rs = parse_neo(neo)
        meta2 = NeoMeta(
            name=rs.meta.name,
            manufacturer=rs.meta.manufacturer,
            year=3333,
            genre=rs.meta.genre,
            screenshot=rs.meta.screenshot,
            ngh=rs.meta.ngh,
        )
        ref = build_neo(rs, meta2)
        with pytest.warns(UserWarning, match="non-zero V2"):
            new = replace_neo_metadata(neo, year=3333)
        assert new == ref

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

        with pytest.raises(ValueError, match="even byte length"):
            _word_swap(b"\x00\x01\x02")
        assert _word_swap(b"\x12\x34") == b"\x34\x12"
        assert _word_swap(b"") == b""

    def test_parse_mame_zip_rejects_corrupt_archive(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"\xffNOT_A_ZIP\xff")
        with pytest.raises(ValueError, match="Cannot open ZIP"):
            parse_mame_zip(bad)

    def test_parse_mame_zip_diagnostic_warns_on_unknown_files(self, tmp_path):
        z = tmp_path / "set.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("game-p1.bin", b"p" * 4096)
            zf.writestr("game-s1.bin", make_rom(128 * 1024, 0x11))
            zf.writestr("game-m1.bin", make_rom(128 * 1024, 0x22))
            zf.writestr("readme.txt", b"x")
        with pytest.warns(UserWarning, match=r"\[diagnostic\]"):
            parse_mame_zip(z, diagnostic=True)

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
        with pytest.warns(UserWarning, match="No text-layer ROM"):
            rs = parse_mame_zip(z)
        assert len(rs.s) == 0x80000
        assert rs.s == b"\x00" * 0x80000

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
            rs = parse_mame_zip(z)
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
            rs = parse_mame_zip(z)
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
            rs = parse_mame_zip(z)
        assert len(rs.s) == 0x40000

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
            rs = parse_mame_zip(z)
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
            rs = parse_mame_zip(z)
        assert len(rs.s) == 0x20000

    def testroles_to_romset_without_filenames_still_requires_physical_s(self):
        with pytest.raises(ValueError, match="S"):
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
            rs = parse_mame_dir(tmp_path)
        assert len(rs.s) == 0x80000

    def test_parse_mame_dir_diagnostic_warns_on_unknown_files(self, tmp_path):
        (tmp_path / "game-p1.bin").write_bytes(b"p" * 4096)
        (tmp_path / "game-s1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-m1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "readme.txt").write_text("x", encoding="utf-8")
        with pytest.warns(UserWarning, match=r"\[diagnostic\]"):
            parse_mame_dir(tmp_path, diagnostic=True)

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
        with pytest.raises(ValueError, match="positive"):
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
        with pytest.raises(ValueError, match="2 MB"):
            swap_p_banks(make_rom(1024 * 1024))  # 1 MB — too small

    def test_wrong_size_4mb_raises(self):
        with pytest.raises(ValueError, match="2 MB"):
            swap_p_banks(make_rom(4 * 1024 * 1024))  # 4 MB — too large


# ---------------------------------------------------------------------------
# diagnostic mode
# ---------------------------------------------------------------------------

class TestDiagnosticMode:
    def test_missing_mandatory_rom_error_has_quick_tips(self, tmp_path):
        from neoconv.core import parse_mame_dir

        # Intentionally omit p1/s1/m1 to verify actionable error text.
        (tmp_path / "readme.txt").write_bytes(b"hello")

        with pytest.raises(ValueError) as exc:
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
        (tmp_path / "readme.txt").write_bytes(b"hello")       # unrecognized
        (tmp_path / "000-lo.lo").write_bytes(make_rom(128 * 1024))  # unrecognized

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            parse_mame_dir(tmp_path, diagnostic=True)

        warned_names = [str(w.message) for w in caught]
        # Both unrecognized files should produce warnings
        assert any("readme.txt" in m for m in warned_names)
        assert any("000-lo.lo" in m for m in warned_names)

    def test_no_warnings_without_diagnostic(self, tmp_path):
        import warnings
        from neoconv.core import parse_mame_dir

        (tmp_path / "game-p1.bin").write_bytes(make_rom(512 * 1024))
        (tmp_path / "game-s1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-m1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "readme.txt").write_bytes(b"hello")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            parse_mame_dir(tmp_path, diagnostic=False)

        assert len(caught) == 0

    def test_duplicate_role_in_directory_raises(self, tmp_path):
        from neoconv.core import parse_mame_dir

        # Both map to role "P" and should be rejected to avoid ambiguity.
        (tmp_path / "game-p1.bin").write_bytes(make_rom(512 * 1024))
        (tmp_path / "alt_p1.bin").write_bytes(make_rom(512 * 1024, 0xAB))
        (tmp_path / "game-s1.bin").write_bytes(make_rom(128 * 1024))
        (tmp_path / "game-m1.bin").write_bytes(make_rom(128 * 1024))

        with pytest.raises(ValueError, match="Duplicate ROM role"):
            parse_mame_dir(tmp_path, diagnostic=False)

    def test_duplicate_role_in_zip_raises(self, tmp_path):
        from neoconv.core import parse_mame_zip

        zip_path = tmp_path / "dupe.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("game-p1.bin", make_rom(512 * 1024))
            zf.writestr("alt_p1.bin", make_rom(512 * 1024, 0xAB))
            zf.writestr("game-s1.bin", make_rom(128 * 1024))
            zf.writestr("game-m1.bin", make_rom(128 * 1024))

        with pytest.raises(ValueError, match="Duplicate ROM role"):
            parse_mame_zip(zip_path, diagnostic=False)


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
        rs_after = apply_swap_p(rs, "auto", verbose=False)
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
        rs_after = apply_swap_p(rs, "auto", verbose=False)
        assert rs_after.p == p_with_valid_first  # unchanged
