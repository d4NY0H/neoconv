"""
Unit tests for neoconv.cli
~~~~~~~~~~~~~~~~~~~~~~~~~~
Focused on command output and exit behavior without full end-to-end I/O.
"""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

import pytest

from neoconv import cli
from neoconv.core import parse_neo


def _mini_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game-p1.bin", b"rom")
    return buf.getvalue()


class _FakeRomset:
    def __init__(self, p: bytes = b"\x00" * 1024):
        self.p = p


def _exit_raiser(code: int = 0):
    raise SystemExit(code)


def _pack_namespace(src: Path, out: Path, **over) -> argparse.Namespace:
    base = {
        "input": str(src),
        "out": str(out),
        "name": "N",
        "manufacturer": "M",
        "year": 1994,
        "genre": "Other",
        "ngh": 1,
        "screenshot": 0,
        "swap_p": "auto",
        "diagnostic": False,
    }
    base.update(over)
    return argparse.Namespace(**base)


def test_cmd_extract_writes_zip(monkeypatch, tmp_path, capsys):
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"fakedata")
    out_zip = tmp_path / "out.zip"
    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    monkeypatch.setattr(cli, "extract_neo_to_zip", lambda *_a, **_kw: _mini_zip_bytes())
    args = argparse.Namespace(
        neo_file=str(neo),
        prefix="zin",
        format="mame",
        out=str(out_zip),
        out_dir="",
        c_chip_size=2_097_152,
    )
    cli.cmd_extract(args)
    assert out_zip.exists()
    out = capsys.readouterr().out
    assert "Written:" in out
    assert "game-p1.bin" in out


def test_cmd_extract_out_dir_lists_files(monkeypatch, tmp_path, capsys):
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"fakedata")
    out_dir = tmp_path / "roms"
    out_dir.mkdir()

    def _fake_extract(*_a, **_kw):
        p = out_dir / "game-p1.bin"
        p.write_bytes(b"abc")
        return {"p": p}

    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    monkeypatch.setattr(cli, "extract_neo", _fake_extract)
    args = argparse.Namespace(
        neo_file=str(neo),
        prefix="zin",
        format="mame",
        out="",
        out_dir=str(out_dir),
        c_chip_size=2_097_152,
    )
    cli.cmd_extract(args)
    out = capsys.readouterr().out
    assert "Extracted 1 files" in out
    assert "game-p1.bin" in out


def test_cmd_extract_auto_c_chip_size(monkeypatch, tmp_path, capsys):
    class _RS:
        c = b"abcd" * 2  # len 8 -> c_chip_size 4

    neo = tmp_path / "game.neo"
    neo.write_bytes(b"fakedata")
    monkeypatch.setattr("neoconv.core.parse_neo", lambda _d: _RS())
    monkeypatch.setattr(cli, "_print_neo_info", lambda _d: _RS())
    monkeypatch.setattr(cli, "extract_neo_to_zip", lambda *_a, **_kw: _mini_zip_bytes())
    out_zip = tmp_path / "out.zip"
    args = argparse.Namespace(
        neo_file=str(neo),
        prefix="x",
        format="mame",
        out=str(out_zip),
        out_dir="",
        c_chip_size=0,
    )
    cli.cmd_extract(args)
    assert out_zip.exists()


def test_cmd_extract_missing_file_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    args = argparse.Namespace(
        neo_file=str(tmp_path / "missing.neo"),
        prefix="",
        format="mame",
        out="",
        out_dir="",
        c_chip_size=2_097_152,
    )
    with pytest.raises(SystemExit) as exc:
        cli.cmd_extract(args)
    assert exc.value.code == 1


def test_cmd_pack_from_directory(monkeypatch, tmp_path, capsys):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "dummy.bin").write_bytes(b"x")
    out_neo = tmp_path / "packed.neo"
    monkeypatch.setattr(cli, "mame_dir_to_neo", lambda *_a, **_k: b"NEO" * 20)
    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    cli.cmd_pack(_pack_namespace(roms, out_neo))
    assert out_neo.read_bytes().startswith(b"NEO")
    assert "Packing directory:" in capsys.readouterr().out


def test_cmd_pack_from_zip(monkeypatch, tmp_path, capsys):
    zpath = tmp_path / "set.zip"
    zpath.write_bytes(_mini_zip_bytes())
    out_neo = tmp_path / "out.neo"
    monkeypatch.setattr(cli, "mame_zip_to_neo", lambda *_a, **_k: b"NEOZIP" * 10)
    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    cli.cmd_pack(
        _pack_namespace(
            zpath,
            out_neo,
            swap_p="yes",
            diagnostic=True,
        )
    )
    out = capsys.readouterr().out
    assert "Packing ZIP:" in out
    assert out_neo.exists()


def test_cmd_pack_swap_no_branch(monkeypatch, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "f.bin").write_bytes(b"y")
    captured: dict[str, object] = {}

    def _capture(_src, _meta, swap_p=None, diagnostic=False):
        captured["swap_p"] = swap_p
        captured["diagnostic"] = diagnostic
        return b"neo"

    monkeypatch.setattr(cli, "mame_dir_to_neo", _capture)
    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    cli.cmd_pack(_pack_namespace(roms, tmp_path / "o.neo", swap_p="no"))
    assert captured["swap_p"] is False


def test_cmd_pack_invalid_input_exits(monkeypatch, tmp_path):
    bad = tmp_path / "plain.txt"
    bad.write_text("not a zip", encoding="utf-8")
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_pack(_pack_namespace(bad, tmp_path / "o.neo"))
    assert exc.value.code == 1


def test_cmd_pack_missing_input_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    missing = tmp_path / "nope.zip"
    with pytest.raises(SystemExit) as exc:
        cli.cmd_pack(_pack_namespace(missing, tmp_path / "o.neo"))
    assert exc.value.code == 1


def test_cmd_pack_unknown_genre_exits(monkeypatch, tmp_path):
    # Genre validation now happens in argparse via _genre_type, not inside cmd_pack.
    # Verify that _genre_type raises ArgumentTypeError for an unknown genre string.
    with pytest.raises(argparse.ArgumentTypeError):
        cli._genre_type("__bad_genre__")


def test_cmd_detect_swap_from_zip(monkeypatch, tmp_path, capsys):
    zpath = tmp_path / "set.zip"
    zpath.write_bytes(_mini_zip_bytes())
    monkeypatch.setattr(cli, "parse_mame_zip", lambda _p: _FakeRomset())
    monkeypatch.setattr(cli, "detect_swap_p_needed", lambda _p: (False, "ok heuristic"))
    cli.cmd_detect_swap(argparse.Namespace(input=str(zpath)))
    out = capsys.readouterr().out
    assert "Inspecting P-ROM from ZIP:" in out
    assert "default" in out
    assert "ok heuristic" in out


def test_cmd_detect_swap_raw_file(monkeypatch, tmp_path, capsys):
    prom = tmp_path / "prom.bin"
    prom.write_bytes(b"\xff" * 512)
    monkeypatch.setattr(cli, "detect_swap_p_needed", lambda p: (True, "vectors"))
    cli.cmd_detect_swap(argparse.Namespace(input=str(prom)))
    out = capsys.readouterr().out
    assert "Inspecting P-ROM file:" in out
    assert "required" in out


def test_cmd_detect_swap_missing_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_detect_swap(argparse.Namespace(input=str(tmp_path / "missing.bin")))
    assert exc.value.code == 1


def test_cmd_info(monkeypatch, tmp_path, capsys):
    neo = tmp_path / "x.neo"
    neo.write_bytes(b"data")
    monkeypatch.setattr(cli, "_print_neo_info", lambda _d: print("META_BLOCK"))
    cli.cmd_info(argparse.Namespace(neo_file=str(neo)))
    out = capsys.readouterr().out
    assert ".neo info:" in out
    assert "META_BLOCK" in out


def test_resolve_genre_other_and_numeric():
    from neoconv.core import GENRES

    other_id = next(k for k, v in GENRES.items() if v == "Other")
    assert cli._resolve_genre("Other") == other_id
    assert cli._resolve_genre("other") == other_id
    assert cli._resolve_genre(str(other_id)) == other_id


def test_resolve_genre_unknown_string_raises(monkeypatch):
    with pytest.raises(ValueError, match="not_a_real_genre_label"):
        cli._resolve_genre("not_a_real_genre_label")


def test_resolve_genre_numeric_not_in_genre_table_raises(monkeypatch):
    with pytest.raises(ValueError, match="99999"):
        cli._resolve_genre("99999")


def test_print_neo_info_uses_parse_neo(monkeypatch, capsys):
    class _R:
        meta = type(
            "M",
            (),
            {"format_info": lambda self, romset=None: "FORMATTED_META\n"},
        )()

    monkeypatch.setattr(cli, "parse_neo", lambda _d: _R())
    cli._print_neo_info(b"neo")
    assert "FORMATTED_META" in capsys.readouterr().out


def test_cmd_info_missing_file_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_info(argparse.Namespace(neo_file=str(tmp_path / "missing.neo")))
    assert exc.value.code == 1


def _mini_neo_bytes() -> bytes:
    from neoconv.core import NeoMeta, RomSet, build_neo, interleave_c_chips

    a = bytes([0x11]) * 256
    b = bytes([0x22]) * 256
    c = interleave_c_chips([a, b])
    rs = RomSet(
        p=bytes([0xAA]) * 512,
        s=bytes([0xBB]) * 64,
        m=bytes([0xCC]) * 64,
        v=bytes([0xDD]) * 128,
        c=c,
    )
    return build_neo(
        rs,
        NeoMeta(name="One", manufacturer="Two", year=1999, genre=2, ngh=5, screenshot=1),
    )


def _edit_ns(path: Path, **over) -> argparse.Namespace:
    base = {
        "neo_file": str(path),
        "out": "",
        "name": None,
        "manufacturer": None,
        "year": None,
        "genre": None,
        "ngh": None,
        "screenshot": None,
    }
    base.update(over)
    return argparse.Namespace(**base)


def test_cmd_edit_requires_at_least_one_field(monkeypatch, tmp_path):
    neo = tmp_path / "x.neo"
    neo.write_bytes(_mini_neo_bytes())
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_edit(_edit_ns(neo))
    assert exc.value.code == 1


def test_cmd_edit_name_in_place(tmp_path, capsys):
    neo = tmp_path / "x.neo"
    neo.write_bytes(_mini_neo_bytes())
    cli.cmd_edit(_edit_ns(neo, name="Renamed"))
    assert parse_neo(neo.read_bytes()).meta.name == "Renamed"
    out = capsys.readouterr().out
    assert "Written:" in out
    assert "Renamed" in out


def test_cmd_edit_writes_separate_out(tmp_path):
    neo = tmp_path / "in.neo"
    out = tmp_path / "out.neo"
    neo.write_bytes(_mini_neo_bytes())
    orig = neo.read_bytes()
    cli.cmd_edit(_edit_ns(neo, out=str(out), manufacturer="Acme"))
    assert neo.read_bytes() == orig
    assert parse_neo(out.read_bytes()).meta.manufacturer == "Acme"


def test_build_parser_edit_subcommand():
    parser = cli.build_parser()
    args = parser.parse_args(["edit", "game.neo", "--year", "2000"])
    assert args.command == "edit"
    assert args.year == 2000
    assert args.name is None


def test_build_parser_requires_subcommand():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_main_dispatches_info(monkeypatch, tmp_path, capsys):
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"neo")
    monkeypatch.setattr(cli.sys, "argv", ["neoconv", "info", str(neo)])
    monkeypatch.setattr(cli, "_print_neo_info", lambda _d: print("FROM_MAIN"))
    cli.main()
    assert "FROM_MAIN" in capsys.readouterr().out


def test_neoconv_main_module_invokes_cli_main(monkeypatch):
    called: list[int] = []

    def _mark():
        called.append(1)

    monkeypatch.setattr("neoconv.cli.main", _mark)
    import runpy

    runpy.run_module("neoconv.__main__", run_name="__main__")
    assert called == [1]

