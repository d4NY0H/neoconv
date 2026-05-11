"""
Unit tests for non-visual GUI logic in neoconv.gui.
"""

from __future__ import annotations

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
