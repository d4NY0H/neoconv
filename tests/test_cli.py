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

from neoconv.core import InvalidRomLayoutError, SwapMode
from neoconv import cli
from neoconv.core import parse_neo, write_bytes_atomic as _write_bytes_atomic


def _mini_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game-p1.bin", b"rom")
    return buf.getvalue()


def _write_complete_dir(root: Path, *, include_s: bool = True) -> None:
    """Small complete P/S/M/V/C set; optional s1 omission for synthetic-S tests."""
    root.mkdir(exist_ok=True)
    (root / "game-p1.bin").write_bytes(b"p" * 1024)
    if include_s:
        (root / "game-s1.bin").write_bytes(b"s" * 1024)
    (root / "game-m1.bin").write_bytes(b"m" * 1024)
    (root / "game-v1.bin").write_bytes(b"v" * 1024)
    (root / "game-c1.bin").write_bytes(b"\x11" * (512 * 1024))
    (root / "game-c2.bin").write_bytes(b"\x22" * (512 * 1024))


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
        "genre": 0,
        "ngh": 1,
        "screenshot": 0,
        "swap_p": "auto",
        "diagnostic": False,
        "v2_size": None,
        "allow_extra_files": False,
        "allow_synthetic_s": False,
    }
    base.update(over)
    return argparse.Namespace(**base)


def test_cmd_extract_writes_zip(monkeypatch, tmp_path, capsys):
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"fakedata")
    out_zip = tmp_path / "out.zip"
    atomic_calls: list[tuple[Path, bytes]] = []

    def _atomic(path, data):
        atomic_calls.append((Path(path), data))
        _write_bytes_atomic(path, data)

    monkeypatch.setattr(cli, "write_bytes_atomic", _atomic)
    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    monkeypatch.setattr(cli, "extract_neo_to_zip", lambda *_a, **_kw: _mini_zip_bytes())
    args = argparse.Namespace(
        neo_file=str(neo),
        prefix="zin",
        format="mame",
        out=str(out_zip),
        out_dir="",
        c_chip_size=2_097_152,
        v_bank_size=0,
        c_chip_sizes=None,
        v_bank_sizes=None,
        p_chip_size=0,
        p_chip_sizes=None,
    )
    cli.cmd_extract(args)
    assert len(atomic_calls) == 1
    assert atomic_calls[0][0] == out_zip
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
        v_bank_size=0,
        c_chip_sizes=None,
        v_bank_sizes=None,
        p_chip_size=0,
        p_chip_sizes=None,
    )
    cli.cmd_extract(args)
    out = capsys.readouterr().out
    assert "Extracted 1 files" in out
    assert "game-p1.bin" in out


def test_cmd_extract_default_c_chip_size(monkeypatch, tmp_path, capsys):
    from neoconv.core import C_CHIP_SIZE_DEFAULT

    class _RS:
        c = b"abcd" * 2

    neo = tmp_path / "game.neo"
    neo.write_bytes(b"fakedata")
    captured: dict = {}

    def _capture(*_a, **kw):
        captured.update(kw)
        return _mini_zip_bytes()

    monkeypatch.setattr("neoconv.core.parse_neo", lambda _d: _RS())
    monkeypatch.setattr(cli, "_print_neo_info", lambda _d: _RS())
    monkeypatch.setattr(cli, "extract_neo_to_zip", _capture)
    out_zip = tmp_path / "out.zip"
    args = argparse.Namespace(
        neo_file=str(neo),
        prefix="x",
        format="mame",
        out=str(out_zip),
        out_dir="",
        c_chip_size=0,
        v_bank_size=0,
        c_chip_sizes=None,
        v_bank_sizes=None,
        p_chip_size=0,
        p_chip_sizes=None,
    )
    cli.cmd_extract(args)
    assert out_zip.exists()
    assert captured["c_chip_size"] == C_CHIP_SIZE_DEFAULT


def test_cmd_extract_v_bank_size_passed_to_zip(monkeypatch, tmp_path, capsys):
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"fakedata")
    captured: dict = {}

    def _capture(*_a, **kw):
        captured.update(kw)
        return _mini_zip_bytes()

    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    monkeypatch.setattr(cli, "extract_neo_to_zip", _capture)
    cli.cmd_extract(
        argparse.Namespace(
            neo_file=str(neo),
            prefix="x",
            format="mame",
            out=str(tmp_path / "out.zip"),
            out_dir="",
            c_chip_size=2_097_152,
            v_bank_size=4_194_304,
            c_chip_sizes=None,
            v_bank_sizes=None,
            p_chip_size=0,
            p_chip_sizes=None,
        )
    )
    assert captured.get("v_bank_size") == 4_194_304
    assert "V bank size: 4,194,304" in capsys.readouterr().out


def test_cmd_extract_missing_file_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    args = argparse.Namespace(
        neo_file=str(tmp_path / "missing.neo"),
        prefix="",
        format="mame",
        out="",
        out_dir="",
        c_chip_size=2_097_152,
        v_bank_size=0,
        c_chip_sizes=None,
        v_bank_sizes=None,
        p_chip_size=0,
        p_chip_sizes=None,
    )
    with pytest.raises(SystemExit) as exc:
        cli.cmd_extract(args)
    assert exc.value.code == 1


def test_build_parser_extract_v_bank_size():
    parser = cli.build_parser()
    args = parser.parse_args(["extract", "game.neo", "--v-bank-size", "4194304"])
    assert args.v_bank_size == 4_194_304


def test_build_parser_extract_size_lists():
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "extract",
            "game.neo",
            "--c-chip-sizes",
            "1048576,1048576,524288,524288",
            "--v-bank-sizes",
            "1048576,524288",
            "--p-chip-sizes",
            "524288,524288",
        ]
    )
    assert args.c_chip_sizes == [1048576, 1048576, 524288, 524288]
    assert args.v_bank_sizes == [1048576, 524288]
    assert args.p_chip_sizes == [524288, 524288]


def test_cmd_extract_passes_size_lists(monkeypatch, tmp_path, capsys):
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"fakedata")
    captured: dict = {}

    def _capture(*_a, **kw):
        captured.update(kw)
        return _mini_zip_bytes()

    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    monkeypatch.setattr(cli, "extract_neo_to_zip", _capture)
    cli.cmd_extract(
        argparse.Namespace(
            neo_file=str(neo),
            prefix="x",
            format="mame",
            out=str(tmp_path / "out.zip"),
            out_dir="",
            c_chip_size=0,
            v_bank_size=0,
            c_chip_sizes=[1048576, 1048576, 524288, 524288],
            v_bank_sizes=[1048576, 524288],
            p_chip_size=0,
            p_chip_sizes=[524288, 524288],
        )
    )
    assert captured["c_chip_sizes"] == [1048576, 1048576, 524288, 524288]
    assert captured["v_bank_sizes"] == [1048576, 524288]
    assert captured["p_chip_sizes"] == [524288, 524288]
    assert "c_chip_size" not in captured
    assert "v_bank_size" not in captured
    assert "p_chip_size" not in captured
    out = capsys.readouterr().out
    assert "C chip sizes:" in out
    assert "V bank sizes:" in out
    assert "P chip sizes:" in out


def test_cmd_extract_passes_uniform_p_chip_size(monkeypatch, tmp_path, capsys):
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"fakedata")
    captured: dict = {}

    def _capture(*_a, **kw):
        captured.update(kw)
        return _mini_zip_bytes()

    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    monkeypatch.setattr(cli, "extract_neo_to_zip", _capture)
    cli.cmd_extract(
        argparse.Namespace(
            neo_file=str(neo),
            prefix="x",
            format="mame",
            out=str(tmp_path / "out.zip"),
            out_dir="",
            c_chip_size=0,
            v_bank_size=0,
            c_chip_sizes=None,
            v_bank_sizes=None,
            p_chip_size=524288,
            p_chip_sizes=None,
        )
    )
    assert captured["p_chip_size"] == 524288
    assert captured["p_chip_sizes"] is None
    out = capsys.readouterr().out
    assert "P chip size: 524,288 bytes" in out


def test_cmd_extract_rejects_c_size_and_sizes_together(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        cli.cmd_extract(
            argparse.Namespace(
                neo_file=str(neo),
                prefix="",
                format="mame",
                out="",
                out_dir="",
                c_chip_size=2097152,
                v_bank_size=0,
                c_chip_sizes=[2097152, 2097152],
                v_bank_sizes=None,
                p_chip_size=0,
                p_chip_sizes=None,
            )
        )
    assert exc.value.code == 1


def test_cmd_extract_rejects_v_size_and_sizes_together(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        cli.cmd_extract(
            argparse.Namespace(
                neo_file=str(neo),
                prefix="",
                format="mame",
                out="",
                out_dir="",
                c_chip_size=0,
                v_bank_size=2097152,
                c_chip_sizes=None,
                v_bank_sizes=[2097152],
                p_chip_size=0,
                p_chip_sizes=None,
            )
        )
    assert exc.value.code == 1


def test_cmd_extract_rejects_p_size_and_sizes_together(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        cli.cmd_extract(
            argparse.Namespace(
                neo_file=str(neo),
                prefix="",
                format="mame",
                out="",
                out_dir="",
                c_chip_size=0,
                v_bank_size=0,
                c_chip_sizes=None,
                v_bank_sizes=None,
                p_chip_size=524288,
                p_chip_sizes=[524288, 524288],
            )
        )
    assert exc.value.code == 1


def test_cmd_extract_rejects_negative_p_chip_size(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)
    neo = tmp_path / "game.neo"
    neo.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        cli.cmd_extract(
            argparse.Namespace(
                neo_file=str(neo),
                prefix="",
                format="mame",
                out="",
                out_dir="",
                c_chip_size=0,
                v_bank_size=0,
                c_chip_sizes=None,
                v_bank_sizes=None,
                p_chip_size=-1,
                p_chip_sizes=None,
            )
        )
    assert exc.value.code == 1


def test_parse_size_list_accepts_hex():
    assert cli._parse_size_list("0x100000,0x80000") == [1048576, 524288]


def test_parse_size_list_rejects_empty():
    with pytest.raises(argparse.ArgumentTypeError):
        cli._parse_size_list("  ,  ")


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

    def _capture(_src, _meta, swap_p=None, diagnostic=False, v2_size=None, **_kw):
        captured["swap_p"] = swap_p
        captured["diagnostic"] = diagnostic
        captured["allow_extra_files"] = _kw.get("allow_extra_files")
        captured["allow_synthetic_s"] = _kw.get("allow_synthetic_s")
        return b"neo"

    monkeypatch.setattr(cli, "mame_dir_to_neo", _capture)
    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    cli.cmd_pack(_pack_namespace(roms, tmp_path / "o.neo", swap_p="no"))
    assert captured["swap_p"] is SwapMode.NO


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


def test_pack_parser_new_opt_in_flags_default_off():
    parser = cli.build_parser()
    args = parser.parse_args(["pack", "input.zip"])
    assert args.allow_extra_files is False
    assert args.allow_synthetic_s is False

    args = parser.parse_args([
        "pack", "input.zip", "--allow-extra-files", "--allow-synthetic-s",
    ])
    assert args.allow_extra_files is True
    assert args.allow_synthetic_s is True


def test_cmd_pack_passes_allow_flags(monkeypatch, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "f.bin").write_bytes(b"y")
    captured: dict[str, object] = {}

    def _capture(_src, _meta, **_kw):
        captured.update(_kw)
        return b"neo"

    monkeypatch.setattr(cli, "mame_dir_to_neo", _capture)
    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    cli.cmd_pack(_pack_namespace(
        roms,
        tmp_path / "o.neo",
        swap_p="no",
        allow_extra_files=True,
        allow_synthetic_s=True,
    ))
    assert captured["allow_extra_files"] is True
    assert captured["allow_synthetic_s"] is True


def _run_pack_cli(monkeypatch, src: Path, out: Path, *extra: str) -> int:
    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["neoconv", "pack", str(src), "-o", str(out), "--swap-p", "no", *extra],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return int(exc.value.code)


def test_pack_extra_file_failure_leaves_no_output(monkeypatch, tmp_path, capsys):
    roms = tmp_path / "roms"
    _write_complete_dir(roms)
    (roms / "readme.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "out.neo"

    code = _run_pack_cli(monkeypatch, roms, out)

    assert code == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "readme.txt" in err
    assert "--allow-extra-files" in err


def test_pack_allow_extra_files_writes_output(monkeypatch, tmp_path):
    roms = tmp_path / "roms"
    _write_complete_dir(roms)
    (roms / "readme.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "out.neo"

    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    with pytest.warns(UserWarning, match="Ignoring"):
        cli.cmd_pack(_pack_namespace(
            roms, out, swap_p="no", allow_extra_files=True,
        ))

    assert out.exists()


def test_pack_missing_s_fails_leaves_no_output(monkeypatch, tmp_path, capsys):
    roms = tmp_path / "roms"
    _write_complete_dir(roms, include_s=False)
    out = tmp_path / "out.neo"

    code = _run_pack_cli(monkeypatch, roms, out)

    assert code == 1
    assert not out.exists()
    assert "--allow-synthetic-s" in capsys.readouterr().err


def test_pack_allow_synthetic_s_writes_output(monkeypatch, tmp_path, capsys):
    roms = tmp_path / "roms"
    _write_complete_dir(roms, include_s=False)
    out = tmp_path / "out.neo"

    monkeypatch.setattr(cli, "_print_neo_info", lambda *_: None)
    with pytest.warns(UserWarning, match="No text-layer ROM"):
        cli.cmd_pack(_pack_namespace(
            roms, out, swap_p="no", allow_synthetic_s=True,
        ))

    assert out.exists()


@pytest.mark.parametrize("set_name", ["mslug5", "kof2003", "kotm2p"])
def test_pack_unsupported_set_failure_leaves_no_output(
    monkeypatch, tmp_path, capsys, set_name
):
    src = tmp_path / set_name
    src.mkdir()
    (src / "junk.bin").write_bytes(b"x")
    out = tmp_path / "out.neo"

    code = _run_pack_cli(monkeypatch, src, out)

    assert code == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "not supported" in err
    assert "layout/decrypt" in err


def _patch_pack_romset(monkeypatch, v: bytes = b"V" * 100) -> None:
    from neoconv.core import RomSet

    romset = RomSet(
        p=b"P" * 32,
        s=b"S" * 8,
        m=b"M" * 8,
        v=v,
        c=b"C" * 16,
    )
    monkeypatch.setattr(
        "neoconv.core.pack.parse_mame_dir",
        lambda _p, diagnostic=False, **_kw: romset,
    )


def test_cli_pack_v2_size_writes_split_header(monkeypatch, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "dummy.bin").write_bytes(b"x")
    out = tmp_path / "out.neo"
    _patch_pack_romset(monkeypatch)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "neoconv", "pack", str(roms), "--swap-p", "no",
            "--v2-size", "40", "-o", str(out),
        ],
    )
    cli.main()
    rs = parse_neo(out.read_bytes())
    assert (rs.v1_size, rs.v2_size) == (60, 40)


def test_cli_pack_v2_size_too_large_fails_cleanly(monkeypatch, tmp_path, capsys):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "dummy.bin").write_bytes(b"x")
    out = tmp_path / "out.neo"
    _patch_pack_romset(monkeypatch)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "neoconv", "pack", str(roms), "--swap-p", "no",
            "--v2-size", "200", "-o", str(out),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "--v2-size" in err
    assert "exceeds the total V ROM size" in err
    assert not out.exists()


def test_cli_pack_negative_v2_size_fails_cleanly(monkeypatch, tmp_path, capsys):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "dummy.bin").write_bytes(b"x")
    out = tmp_path / "out.neo"
    _patch_pack_romset(monkeypatch)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "neoconv", "pack", str(roms), "--swap-p", "no",
            "--v2-size", "-1", "-o", str(out),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "must not be negative" in capsys.readouterr().err
    assert not out.exists()


def test_cmd_detect_swap_from_zip(monkeypatch, tmp_path, capsys):
    zpath = tmp_path / "set.zip"
    zpath.write_bytes(_mini_zip_bytes())
    monkeypatch.setattr(cli, "parse_mame_zip", lambda _p, **_kw: _FakeRomset())
    monkeypatch.setattr(cli, "detect_swap_p_needed", lambda _p: (False, "ok heuristic"))
    cli.cmd_detect_swap(argparse.Namespace(input=str(zpath)))
    out = capsys.readouterr().out
    assert "Inspecting P-ROM from ZIP:" in out
    assert "--swap-p no" in out
    assert "not needed" in out
    assert "(default)" not in out
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
    from neoconv.core import GENRES, resolve_genre

    other_id = next(k for k, v in GENRES.items() if v == "Other")
    assert resolve_genre("Other") == other_id
    assert resolve_genre("other") == other_id
    assert resolve_genre(str(other_id)) == other_id


def test_resolve_genre_unknown_string_raises():
    from neoconv.core import resolve_genre

    with pytest.raises(ValueError, match="not_a_real_genre_label"):
        resolve_genre("not_a_real_genre_label")


def test_resolve_genre_numeric_not_in_genre_table_raises():
    from neoconv.core import resolve_genre

    with pytest.raises(ValueError, match="99999"):
        resolve_genre("99999")


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


def test_main_value_error_exits(monkeypatch, tmp_path, capsys):
    roms = tmp_path / "roms"
    roms.mkdir()
    monkeypatch.setattr(
        cli,
        "mame_dir_to_neo",
        lambda *_a, **_kw: (_ for _ in ()).throw(InvalidRomLayoutError("pack failed")),
    )
    monkeypatch.setattr(cli.sys, "argv", ["neoconv", "pack", str(roms), "-o", str(tmp_path / "o.neo")])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "pack failed" in capsys.readouterr().err


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

