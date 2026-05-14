"""
Unit tests for non-visual GUI logic in neoconv.gui.
"""

from __future__ import annotations

import json
import tkinter as tk
import zipfile

from neoconv import gui


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


def test_scan_required_roles_for_directory(tmp_path):
    (tmp_path / "game-p1.bin").write_bytes(b"p")
    (tmp_path / "game-s1.bin").write_bytes(b"s")
    (tmp_path / "game-m1.bin").write_bytes(b"m")
    roles = gui._scan_required_roles(tmp_path)
    assert roles == {"P", "S", "M"}


def test_scan_required_roles_for_zip(tmp_path):
    zip_path = tmp_path / "set.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("folder/game-p1.bin", b"p")
        zf.writestr("folder/game-s1.bin", b"s")
        zf.writestr("folder/game-m1.bin", b"m")
    roles = gui._scan_required_roles(zip_path)
    assert roles == {"P", "S", "M"}


def test_global_reset_is_blocked_when_job_running(monkeypatch):
    calls: list[tuple[str, str]] = []

    class RunningTab:
        _is_running = True

        def reset_defaults(self):
            calls.append(("running", "reset"))

    class IdleTab:
        _is_running = False

        def reset_defaults(self):
            calls.append(("idle", "reset"))

    app = gui.NeoConvApp.__new__(gui.NeoConvApp)
    app._tabs = {"running": RunningTab(), "idle": IdleTab()}

    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, msg: calls.append((title, msg)))
    app._reset_all_tabs()

    # Warning shown, no tab reset executed.
    assert any(c[0] == "Reset blocked" for c in calls)
    assert not any(c[1] == "reset" for c in calls if isinstance(c, tuple) and len(c) == 2)


def test_c_chip_size_from_str_auto_uses_half_total():
    label = gui._C_CHIP_SIZES[0][0]
    assert gui._c_chip_size_from_str(label, c_total=2048) == 1024


def test_c_chip_size_from_str_auto_without_c_total_uses_default():
    from neoconv.core import C_CHIP_SIZE_DEFAULT

    label = gui._C_CHIP_SIZES[0][0]
    assert gui._c_chip_size_from_str(label, c_total=None) == C_CHIP_SIZE_DEFAULT


def test_c_chip_size_from_str_unknown_falls_back_to_default():
    from neoconv.core import C_CHIP_SIZE_DEFAULT

    assert gui._c_chip_size_from_str("__no_such_label__") == C_CHIP_SIZE_DEFAULT


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


def test_save_settings_roundtrip(monkeypatch, tmp_path):
    path = tmp_path / "d" / "cfg.json"
    monkeypatch.setattr(gui, "_SETTINGS_PATH", path)
    gui._save_settings({"a": 1, "b": "x"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "b": "x"}


def test_global_reset_calls_all_tabs_when_idle():
    calls: list[str] = []

    class IdleTab:
        _is_running = False

        def reset_defaults(self):
            calls.append("reset")

    app = gui.NeoConvApp.__new__(gui.NeoConvApp)
    app._tabs = {"a": IdleTab(), "b": IdleTab()}

    app._reset_all_tabs()
    assert calls == ["reset", "reset"]
