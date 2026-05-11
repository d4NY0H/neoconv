"""
Unit tests for neoconv.cli
~~~~~~~~~~~~~~~~~~~~~~~~~~
Focused on command output and exit behavior without full end-to-end I/O.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from neoconv import cli
from neoconv.core import NeoMeta


def _exit_raiser(code: int = 0):
    raise SystemExit(code)


class _VerifyResult:
    def __init__(self, ok: bool):
        self.ok = ok
        self.original_rom_md5 = "orig"
        self.rebuilt_rom_md5 = "new"
        self.file_size_match = True
        self.details = "details"


def _verify_args(path: Path) -> argparse.Namespace:
    return argparse.Namespace(neo_file=str(path), prefix="", format="mame")


def test_cmd_verify_success_uses_ascii_markers(monkeypatch, tmp_path, capsys):
    neo_path = tmp_path / "input.neo"
    neo_path.write_bytes(b"neo")

    monkeypatch.setattr(cli, "extract_neo_to_zip", lambda *_args, **_kw: b"zip")
    monkeypatch.setattr(cli, "parse_neo", lambda *_args, **_kw: type("R", (), {"meta": NeoMeta()})())
    monkeypatch.setattr(cli, "mame_zip_to_neo", lambda *_args, **_kw: b"rebuilt")
    monkeypatch.setattr(cli, "verify_roundtrip", lambda *_args, **_kw: _VerifyResult(ok=True))
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)

    with pytest.raises(SystemExit) as exc:
        cli.cmd_verify(_verify_args(neo_path))

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "[OK] PASS - extraction is lossless." in out


def test_cmd_verify_failure_uses_ascii_markers(monkeypatch, tmp_path, capsys):
    neo_path = tmp_path / "input.neo"
    neo_path.write_bytes(b"neo")

    monkeypatch.setattr(cli, "extract_neo_to_zip", lambda *_args, **_kw: b"zip")
    monkeypatch.setattr(cli, "parse_neo", lambda *_args, **_kw: type("R", (), {"meta": NeoMeta()})())
    monkeypatch.setattr(cli, "mame_zip_to_neo", lambda *_args, **_kw: b"rebuilt")
    monkeypatch.setattr(cli, "verify_roundtrip", lambda *_args, **_kw: _VerifyResult(ok=False))
    monkeypatch.setattr(cli.sys, "exit", _exit_raiser)

    with pytest.raises(SystemExit) as exc:
        cli.cmd_verify(_verify_args(neo_path))

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "[ERROR] FAIL - ROM data mismatch!" in out
