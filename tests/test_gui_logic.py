"""
Unit tests for non-visual GUI logic in neoconv.gui.
"""

from __future__ import annotations

import tkinter as tk
import zipfile

import pytest

from neoconv import gui
from neoconv.core import InvalidNeoError


def test_enforce_latin1_byte_limit_truncates_hard():
    tcl = tk.Tcl()
    var = tk.StringVar(master=tcl, value="")
    gui._enforce_latin1_byte_limit(var, 4)
    var.set("ABCDE")
    assert len(var.get().encode("latin-1", errors="replace")) == 4
    assert var.get() == "ABCD"


def test_name_to_required_role_matches_known_patterns():
    assert gui._name_to_required_role("game-p1.bin") == "P"
    assert gui._name_to_required_role("game_s1.bin") == "S"
    assert gui._name_to_required_role("game.m1") == "M"
    assert gui._name_to_required_role("other.txt") is None


def test_scan_pack_preflight_for_directory(tmp_path):
    (tmp_path / "game-p1.bin").write_bytes(b"p")
    (tmp_path / "game-s1.bin").write_bytes(b"s")
    (tmp_path / "game-m1.bin").write_bytes(b"m")
    roles, issues = gui._scan_pack_preflight(tmp_path)
    assert roles == {"P", "S", "M"}
    assert issues == []


def test_scan_pack_preflight_for_zip(tmp_path):
    zip_path = tmp_path / "set.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("folder/game-p1.bin", b"p")
        zf.writestr("folder/game-s1.bin", b"s")
        zf.writestr("folder/game-m1.bin", b"m")
    roles, issues = gui._scan_pack_preflight(zip_path)
    assert roles == {"P", "S", "M"}
    assert issues == []


def test_scan_pack_preflight_detects_v_gap(tmp_path):
    (tmp_path / "game-p1.bin").write_bytes(b"p")
    (tmp_path / "game-s1.bin").write_bytes(b"s")
    (tmp_path / "game-m1.bin").write_bytes(b"m")
    (tmp_path / "game-v1.bin").write_bytes(b"v")
    (tmp_path / "game-v3.bin").write_bytes(b"v")
    roles, issues = gui._scan_pack_preflight(tmp_path)
    assert roles == {"P", "S", "M"}
    assert any("V2" in i for i in issues)


def test_c_chip_size_from_str_default_label():
    from neoconv.core import C_CHIP_SIZE_DEFAULT

    label = gui._C_CHIP_SIZES[0][0]
    assert gui._c_chip_size_from_str(label) == C_CHIP_SIZE_DEFAULT


def test_c_chip_size_from_str_4mb():
    four_mb = 4 * 1024 * 1024
    label = next(l for l, v in gui._C_CHIP_SIZES if v == four_mb)
    assert gui._c_chip_size_from_str(label) == four_mb


def test_c_chip_size_from_str_unknown_falls_back_to_default():
    from neoconv.core import C_CHIP_SIZE_DEFAULT

    assert gui._c_chip_size_from_str("__no_such_label__") == C_CHIP_SIZE_DEFAULT


def test_v_bank_size_from_str_default_label():
    from neoconv.core import V_BANK_SIZE

    label = gui._V_CHUNK_SIZES[0][0]
    assert gui._v_bank_size_from_str(label) == V_BANK_SIZE


def test_v_bank_size_from_str_4mb():
    four_mb = 4 * 1024 * 1024
    label = next(l for l, v in gui._V_CHUNK_SIZES if v == four_mb)
    assert gui._v_bank_size_from_str(label) == four_mb


def test_v_bank_size_from_str_unknown_falls_back_to_default():
    from neoconv.core import V_BANK_SIZE

    assert gui._v_bank_size_from_str("__no_such_label__") == V_BANK_SIZE


def test_set_controls_state_toggles_widget():
    class _Stub:
        def __init__(self) -> None:
            self.state = "normal"

        def config(self, *, state: str, **_kw) -> None:
            self.state = state

    w = _Stub()
    gui._set_controls_state([w], False)
    assert w.state == "disabled"
    gui._set_controls_state([w], True)
    assert w.state == "normal"


def test_resolve_genre_rejects_unknown_label():
    from neoconv.core import resolve_genre

    with pytest.raises(ValueError, match="unknown genre"):
        resolve_genre("NotARealGenre")


def test_format_neoconv_error_includes_hint():
    exc = InvalidNeoError("bad header", hint="check file size")
    assert gui._format_neoconv_error(exc) == "bad header — check file size"
    assert gui._format_neoconv_error(InvalidNeoError("only message")) == "only message"


def test_app_icon_png_is_packaged():
    from importlib.resources import files

    icon = files("neoconv.assets").joinpath("neoconv.png")
    assert icon.is_file()


def test_apply_window_icon_sets_photo_or_fails_soft():
    root = tk.Tk()
    root.withdraw()
    try:
        gui._apply_window_icon(root)
        # Soft-fail leaves no icon; success stores a PhotoImage reference.
        icon = getattr(root, "_neoconv_icon", None)
        if icon is not None:
            assert isinstance(icon, tk.PhotoImage)
    finally:
        root.destroy()


def test_apply_window_icon_swallows_lookup_errors(monkeypatch):
    root = tk.Tk()
    root.withdraw()
    try:

        def _boom(*_a, **_k):
            raise FileNotFoundError("missing icon")

        monkeypatch.setattr("importlib.resources.files", _boom)
        gui._apply_window_icon(root)  # must not raise
        assert not hasattr(root, "_neoconv_icon")
    finally:
        root.destroy()
