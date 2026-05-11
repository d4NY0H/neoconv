"""
neoconv GUI
~~~~~~~~~~~
Tkinter GUI for neoconv. Feature-complete with the CLI.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import tkinter as tk
import warnings
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from . import __version__
from .core import (
    C_CHIP_SIZE_DEFAULT,
    GENRE_BY_NAME,
    GENRES,
    NeoMeta,
    detect_swap_p_needed,
    extract_romset,
    extract_romset_to_zip,
    mame_dir_to_neo,
    mame_zip_to_neo,
    parse_neo,
    verify_roundtrip,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    _DND_AVAILABLE = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    _DND_AVAILABLE = False


# ---------------------------------------------------------------------------
# Size option tables (derived from MAME neogeo.xml statistics)
# ---------------------------------------------------------------------------

_C_CHIP_SIZES = [
    ("auto (C_total ÷ 2)",  0),
    ("512 KB",               512 * 1024),
    ("1 MB",               1 * 1024 * 1024),
    ("2 MB",               2 * 1024 * 1024),
    ("4 MB",               4 * 1024 * 1024),
    ("8 MB",               8 * 1024 * 1024),
    ("16 MB",             16 * 1024 * 1024),
    ("20 MB",             20 * 1024 * 1024),
]

_V_CHUNK_SIZES = [
    ("2 MB (default)",     2 * 1024 * 1024),
    ("512 KB",             512 * 1024),
    ("1 MB",               1 * 1024 * 1024),
    ("4 MB",               4 * 1024 * 1024),
    ("8 MB",               8 * 1024 * 1024),
    ("16 MB",             16 * 1024 * 1024),
]

if os.name == "nt":
    _SETTINGS_PATH = Path.home() / "AppData" / "Roaming" / "neoconv" / "config.json"
elif os.name == "posix" and "darwin" in sys.platform:
    _SETTINGS_PATH = Path.home() / "Library" / "Application Support" / "neoconv" / "config.json"
else:
    _SETTINGS_PATH = Path.home() / ".config" / "neoconv" / "config.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_in_thread(fn, *args):
    t = threading.Thread(target=fn, args=args, daemon=True)
    t.start()


def _c_chip_size_from_str(s: str, c_total: int | None = None) -> int:
    for label, val in _C_CHIP_SIZES:
        if s == label:
            if val == 0 and c_total is not None:
                return c_total // 2 if c_total else C_CHIP_SIZE_DEFAULT
            return val if val != 0 else C_CHIP_SIZE_DEFAULT
    return C_CHIP_SIZE_DEFAULT


def _set_controls_state(controls: list[tk.Widget], enabled: bool) -> None:
    state = "normal" if enabled else "disabled"
    for ctrl in controls:
        ctrl.config(state=state)


def _enforce_latin1_byte_limit(var: tk.StringVar, max_bytes: int) -> None:
    """
    Hard-limit a StringVar to *max_bytes* when encoded as latin-1 with
    errors="replace", matching the .neo header packing logic.

    This truncates the value immediately (prevents typing past the limit),
    rather than allowing the user to enter longer strings that would be
    silently truncated later.
    """
    in_callback = False

    def _on_write(*_args) -> None:
        nonlocal in_callback
        if in_callback:
            return

        s = var.get()
        b = s.encode("latin-1", errors="replace")
        if len(b) <= max_bytes:
            return

        # Truncate by bytes but keep a valid string for the widget
        truncated = b[:max_bytes].decode("latin-1", errors="ignore")
        in_callback = True
        try:
            var.set(truncated)
        finally:
            in_callback = False

    var.trace_add("write", _on_write)


def _load_settings() -> dict:
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(data: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _name_to_required_role(filename: str) -> str | None:
    fn = Path(filename).name.lower()
    ext = Path(fn).suffix.lstrip(".")
    stem = Path(fn).stem
    ext_map = {"p1": "P", "p2": "P", "s1": "S", "m1": "M"}
    if ext in ext_map:
        return ext_map[ext]
    for key, role in ext_map.items():
        if fn.endswith(f"-{key}.bin") or fn.endswith(f"_{key}.bin") \
                or stem.endswith(f"-{key}") or stem.endswith(f"_{key}"):
            return role
    return None


def _scan_required_roles(src: Path) -> set[str]:
    roles: set[str] = set()
    if src.is_dir():
        for f in src.iterdir():
            if f.is_file():
                role = _name_to_required_role(f.name)
                if role:
                    roles.add(role)
    elif zipfile.is_zipfile(src):
        with zipfile.ZipFile(src, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                role = _name_to_required_role(info.filename)
                if role:
                    roles.add(role)
    return roles


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class NeoConvApp(TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"neoconv {__version__}")
        # Allow resizing so the log area can grow on demand.
        self.resizable(True, True)
        self._settings = _load_settings()
        self._tabs: dict[str, tk.Widget] = {}
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Button(toolbar, text="Reset all tabs", command=self._reset_all_tabs).pack(side="right")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        for key, tab, label in [
            ("extract", ExtractTab(nb), "Extract (.neo → files)"),
            ("pack",    PackTab(nb),    "Pack (files → .neo)"),
            ("verify",  VerifyTab(nb),  "Verify (Roundtrip)"),
            ("info",    InfoTab(nb),    "Info (.neo)"),
        ]:
            self._tabs[key] = tab
            nb.add(tab, text=label)
            if hasattr(tab, "apply_settings"):
                tab.apply_settings(self._settings.get(key, {}))
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        data = {}
        for key, tab in self._tabs.items():
            if hasattr(tab, "export_settings"):
                data[key] = tab.export_settings()
        try:
            _save_settings(data)
        except Exception:
            pass
        self.destroy()

    def _reset_all_tabs(self):
        if any(getattr(tab, "_is_running", False) for tab in self._tabs.values()):
            messagebox.showwarning(
                "Reset blocked",
                "At least one operation is still running. "
                "Please wait for completion (or cancel first) before resetting.",
            )
            return
        for tab in self._tabs.values():
            if hasattr(tab, "reset_defaults"):
                tab.reset_defaults()


# ---------------------------------------------------------------------------
# Shared widgets
# ---------------------------------------------------------------------------

class _FileRow(ttk.Frame):
    def __init__(
        self,
        parent,
        label: str,
        mode: str = "open",
        filetypes=None,
        label_width: int = 14,
        entry_width: int = 42,
        extra_buttons: list[tuple[str, callable]] | None = None,
        **kw,
    ):
        super().__init__(parent, **kw)
        self._mode = mode
        self._ft   = filetypes or []

        # Grid-based layout for consistent alignment and better resizing
        self.columnconfigure(1, weight=1)

        self.label = ttk.Label(self, text=label, width=label_width, anchor="w")
        self.label.grid(row=0, column=0, sticky="w")
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=entry_width)
        self.entry.grid(row=0, column=1, sticky="ew", padx=4)
        self.button = ttk.Button(self, text="Browse…", command=self._browse)
        self.button.grid(row=0, column=2, sticky="w")

        self._extra_buttons: list[ttk.Button] = []
        for i, (text, cmd) in enumerate(extra_buttons or []):
            b = ttk.Button(self, text=text, command=cmd)
            b.grid(row=0, column=3 + i, sticky="w", padx=(6 if i == 0 else 4, 0))
            self._extra_buttons.append(b)
        self._enable_drop()

    def _browse(self):
        p = (filedialog.askopenfilename(filetypes=self._ft) if self._mode == "open"
             else filedialog.askdirectory() if self._mode == "opendir"
             else filedialog.asksaveasfilename(filetypes=self._ft))
        if p:
            self.var.set(p)

    @property
    def value(self) -> str:
        return self.var.get().strip()

    def _enable_drop(self) -> None:
        if not _DND_AVAILABLE:
            return
        try:
            self.entry.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            self.entry.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
        except Exception:
            # Drag-and-drop depends on TkDND availability at runtime.
            pass

    def _on_drop(self, event) -> None:
        try:
            paths = self.tk.splitlist(event.data)
            if paths:
                self.var.set(paths[0])
        except Exception:
            pass


class _LogBox(scrolledtext.ScrolledText):
    def __init__(self, parent, **kw):
        kw.setdefault("height", 8)
        kw.setdefault("state", "disabled")
        kw.setdefault("font", ("Courier", 9))
        super().__init__(parent, **kw)

    def clear(self):
        self.config(state="normal"); self.delete("1.0", "end"); self.config(state="disabled")

    def append(self, text: str):
        self.config(state="normal")
        self.insert("end", text + "\n")
        self.see("end")
        self.config(state="disabled")


class _SizeCombo(ttk.Frame):
    def __init__(self, parent, label: str, options: list[tuple[str, int]],
                 default_label: str, **kw):
        super().__init__(parent, **kw)
        ttk.Label(self, text=label, width=14, anchor="w").pack(side="left")
        self.var = tk.StringVar(value=default_label)
        ttk.Combobox(self, textvariable=self.var,
                     values=[l for l, _ in options],
                     state="readonly", width=22).pack(side="left", padx=4)

    @property
    def value_str(self) -> str:
        return self.var.get()


# ---------------------------------------------------------------------------
# Extract tab
# ---------------------------------------------------------------------------

class ExtractTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._is_running = False
        self._cancel_event = threading.Event()
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 3}

        self._neo = _FileRow(self, "Input .neo:",
                             filetypes=[("NEO files", "*.neo"), ("All", "*.*")])
        self._neo.pack(fill="x", **pad)

        # Output mode: ZIP or directory
        out_frame = ttk.LabelFrame(self, text="Output")
        out_frame.pack(fill="x", padx=8, pady=4)
        self._out_mode = tk.StringVar(value="zip")
        ttk.Radiobutton(out_frame, text="ZIP file",  variable=self._out_mode,
                        value="zip", command=self._toggle_out).grid(
            row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Radiobutton(out_frame, text="Directory", variable=self._out_mode,
                        value="dir", command=self._toggle_out).grid(
            row=1, column=0, sticky="w", padx=4)

        self._out_zip = _FileRow(out_frame, "", mode="save",
                                 filetypes=[("ZIP", "*.zip")], label_width=1)
        self._out_zip.grid(row=0, column=1, sticky="ew", padx=4)

        self._out_dir = _FileRow(out_frame, "", mode="opendir", label_width=1)
        self._out_dir.grid(row=1, column=1, sticky="ew", padx=4)
        self._out_dir_var = self._out_dir.var
        self._out_dir_entry = self._out_dir.entry
        self._out_dir_button = self._out_dir.button
        out_frame.columnconfigure(1, weight=1)

        # Prefix + format
        row1 = ttk.Frame(self)
        row1.pack(fill="x", **pad)
        ttk.Label(row1, text="Prefix:", width=14, anchor="w").pack(side="left")
        self._prefix = tk.StringVar()
        ttk.Entry(row1, textvariable=self._prefix, width=14).pack(side="left", padx=4)
        ttk.Label(row1, text="Format:", width=8).pack(side="left", padx=(12, 0))
        self._fmt = tk.StringVar(value="mame")
        ttk.Radiobutton(row1, text="MAME (.bin)",     variable=self._fmt, value="mame").pack(side="left")
        ttk.Radiobutton(row1, text="Darksoft (.rom)", variable=self._fmt, value="darksoft").pack(side="left")

        # C chip size
        row2 = ttk.Frame(self)
        row2.pack(fill="x", **pad)
        self._c_size = _SizeCombo(row2, "C Chip Size:", _C_CHIP_SIZES, "auto (C_total ÷ 2)")
        self._c_size.pack(side="left")

        ctrl_row = ttk.Frame(self)
        ctrl_row.pack(fill="x", padx=8, pady=3)
        self._run_btn = ttk.Button(ctrl_row, text="Extract", command=self._run)
        self._run_btn.grid(row=0, column=0, padx=(0, 8))
        self._cancel_btn = ttk.Button(ctrl_row, text="Cancel", command=self._request_cancel, state="disabled")
        self._cancel_btn.grid(row=0, column=1, padx=(0, 8))
        self._progress = ttk.Progressbar(ctrl_row, mode="indeterminate", length=180)
        self._progress.grid(row=0, column=2, sticky="w")
        ctrl_row.columnconfigure(3, weight=1)
        self._log = _LogBox(self)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)
        self._toggle_out()

    def _toggle_out(self):
        is_zip = self._out_mode.get() == "zip"
        _set_controls_state([self._out_zip.entry, self._out_zip.button], enabled=is_zip)
        _set_controls_state([self._out_dir_entry, self._out_dir_button], enabled=not is_zip)

    def _run(self):
        if self._is_running:
            return
        neo_path = Path(self._neo.value)
        if not neo_path.exists():
            messagebox.showerror("Error", f"File not found: {neo_path}"); return

        mode   = self._out_mode.get()
        prefix = self._prefix.get().strip() or neo_path.stem
        fmt    = self._fmt.get()
        self._log.clear()
        self._is_running = True
        self._run_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._cancel_event.clear()
        self._progress.start(10)

        def work():
            try:
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                neo_data    = neo_path.read_bytes()
                romset      = parse_neo(neo_data)
                c_chip_size = _c_chip_size_from_str(self._c_size.value_str, len(romset.c))
                self._log.append(f"Reading: {neo_path}")
                self._log.append(f"C chip size: {c_chip_size:,} bytes")
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")

                if mode == "dir":
                    out_dir = Path(self._out_dir_var.get()) if self._out_dir_var.get() \
                              else neo_path.parent / neo_path.stem
                    written = extract_romset(romset, out_dir, name_prefix=prefix,
                                             fmt=fmt, c_chip_size=c_chip_size)
                    self._log.append(f"Extracted {len(written)} files to: {out_dir}")
                    for _, p in sorted(written.items()):
                        self._log.append(f"  {p.name:<30} {p.stat().st_size:>10,} bytes")
                else:
                    dest = Path(self._out_zip.value) if self._out_zip.value \
                           else neo_path.with_suffix(f".{fmt}.zip")
                    zip_data = extract_romset_to_zip(romset, name_prefix=prefix,
                                                     fmt=fmt, c_chip_size=c_chip_size)
                    dest.write_bytes(zip_data)
                    self._log.append(f"Written: {dest}  ({len(zip_data)/1024/1024:.2f} MB)")
                    with zipfile.ZipFile(dest) as zf:
                        for info in zf.infolist():
                            self._log.append(f"  {info.filename:<30} {info.file_size:>10,} bytes")
                self._log.append("[OK] Done.")
            except Exception as e:
                self._log.append(f"[ERROR] {e}")
            finally:
                self.after(0, self._finish_run)

        _run_in_thread(work)

    def _finish_run(self):
        self._is_running = False
        self._run_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")
        self._progress.stop()

    def _request_cancel(self):
        self._cancel_event.set()
        self._log.append("[WARN] Cancellation requested... waiting for safe stop.")

    def export_settings(self) -> dict:
        return {
            "input": self._neo.value,
            "output_mode": self._out_mode.get(),
            "output_zip": self._out_zip.value,
            "output_dir": self._out_dir_var.get(),
            "prefix": self._prefix.get(),
            "format": self._fmt.get(),
            "c_chip_size": self._c_size.value_str,
        }

    def apply_settings(self, data: dict) -> None:
        if not data:
            return
        self._neo.var.set(data.get("input", self._neo.var.get()))
        self._out_mode.set(data.get("output_mode", self._out_mode.get()))
        self._out_zip.var.set(data.get("output_zip", self._out_zip.var.get()))
        self._out_dir_var.set(data.get("output_dir", self._out_dir_var.get()))
        self._prefix.set(data.get("prefix", self._prefix.get()))
        self._fmt.set(data.get("format", self._fmt.get()))
        if data.get("c_chip_size"):
            self._c_size.var.set(data["c_chip_size"])
        self._toggle_out()

    def reset_defaults(self):
        self._neo.var.set("")
        self._out_mode.set("zip")
        self._out_zip.var.set("")
        self._out_dir_var.set("")
        self._prefix.set("")
        self._fmt.set("mame")
        self._c_size.var.set("auto (C_total ÷ 2)")
        self._progress.config(value=0)
        self._toggle_out()


# ---------------------------------------------------------------------------
# Pack tab
# ---------------------------------------------------------------------------

class PackTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._is_running = False
        self._cancel_event = threading.Event()
        self._validate_after_id: str | None = None
        self._roles_src_key: tuple | None = None
        self._roles_missing: list[str] | None = None
        self._roles_scan_error: str | None = None
        self._roles_scan_token = 0
        self._roles_scan_running_token: int | None = None
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 3}

        self._inp = _FileRow(
            self,
            "Input ZIP/Dir:",
            filetypes=[("ZIP files", "*.zip"), ("All", "*.*")],
            extra_buttons=[
                (
                    "Pick dir…",
                    lambda: self._inp.var.set(
                        filedialog.askdirectory() or self._inp.value
                    ),
                )
            ],
        )
        self._inp.pack(fill="x", **pad)
        self._inp.var.trace_add("write", lambda *_: self._schedule_validation())

        self._out = _FileRow(self, "Output .neo:", mode="save",
                             filetypes=[("NEO files", "*.neo"), ("All", "*.*")])
        self._out.pack(fill="x", **pad)
        self._out.var.trace_add("write", lambda *_: self._schedule_validation())

        # Metadata
        meta_frame = ttk.LabelFrame(self, text="Metadata")
        meta_frame.pack(fill="x", padx=8, pady=4)
        meta_frame.columnconfigure(1, weight=1)
        fields = [
            ("Name:",         "name",       "Unknown"),
            ("Manufacturer:", "mfr",        "Unknown"),
            ("Year:",         "year",       "0"),
            ("NGH #:",        "ngh",        "0"),
            ("Screenshot #:", "screenshot", "0"),
        ]
        self._vars: dict[str, tk.StringVar] = {}
        for i, (lbl, key, default) in enumerate(fields):
            ttk.Label(meta_frame, text=lbl, width=14, anchor="w").grid(
                row=i, column=0, sticky="w", padx=4, pady=2)
            v = tk.StringVar(value=default)
            self._vars[key] = v
            v.trace_add("write", lambda *_: self._schedule_validation())
            if key == "name":
                _enforce_latin1_byte_limit(v, 32)
            elif key == "mfr":
                _enforce_latin1_byte_limit(v, 16)
            ttk.Entry(meta_frame, textvariable=v).grid(
                row=i, column=1, sticky="ew", padx=4)
        gr = len(fields)
        ttk.Label(meta_frame, text="Genre:", width=14, anchor="w").grid(
            row=gr, column=0, sticky="w", padx=4, pady=2)
        self._genre = tk.StringVar(value="Other")
        self._genre.trace_add("write", lambda *_: self._schedule_validation())
        ttk.Combobox(meta_frame, textvariable=self._genre,
                     values=list(GENRES.values()), state="readonly", width=16
                     ).grid(row=gr, column=1, sticky="w", padx=4)

        # Options
        opt_frame = ttk.LabelFrame(self, text="Options")
        opt_frame.pack(fill="x", padx=8, pady=4)
        opt_frame.columnconfigure(1, weight=1)

        # P-ROM swap: keep label aligned; radios wrapped into two lines
        ttk.Label(opt_frame, text="P-ROM Bank Swap:", width=18, anchor="w").grid(
            row=0, column=0, sticky="w", padx=4, pady=2
        )
        self._swap_p = tk.StringVar(value="auto")
        self._swap_p.trace_add("write", lambda *_: self._schedule_validation())
        radios = ttk.Frame(opt_frame)
        radios.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        ttk.Radiobutton(
            radios, text="No  (never swap)", variable=self._swap_p, value="no"
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Radiobutton(
            radios, text="Auto-detect  (default)", variable=self._swap_p, value="auto"
        ).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(
            radios, text="Yes  (always swap)", variable=self._swap_p, value="yes"
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        self._diagnostic = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt_frame,
            text="Diagnostic mode  (log warnings for unrecognized files)",
            variable=self._diagnostic,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=2)

        ctrl_row = ttk.Frame(self)
        ctrl_row.pack(fill="x", padx=8, pady=3)
        self._run_btn = ttk.Button(ctrl_row, text="Pack → .neo", command=self._run)
        self._run_btn.grid(row=0, column=0, padx=(0, 8))
        self._cancel_btn = ttk.Button(ctrl_row, text="Cancel", command=self._request_cancel, state="disabled")
        self._cancel_btn.grid(row=0, column=1, padx=(0, 8))
        self._progress = ttk.Progressbar(ctrl_row, mode="determinate", length=220, maximum=4, value=0)
        self._progress.grid(row=0, column=2, sticky="w")
        self._status_var = tk.StringVar(value="Status: waiting for input")
        self._status_label = tk.Label(ctrl_row, textvariable=self._status_var, anchor="w")
        self._status_label.grid(row=0, column=3, sticky="w", padx=(10, 0))
        ctrl_row.columnconfigure(3, weight=1)
        self._log = _LogBox(self)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)
        self._schedule_validation()

    def _run(self):
        if self._is_running:
            return
        src = Path(self._inp.value)
        out = Path(self._out.value) if self._out.value else None
        if not src.exists():
            messagebox.showerror("Error", f"Not found: {src}"); return
        try:
            year       = int(self._vars["year"].get())
            ngh        = int(self._vars["ngh"].get())
            screenshot = int(self._vars["screenshot"].get())
        except ValueError:
            messagebox.showerror("Error", "Year, NGH and Screenshot must be integers.")
            return

        meta = NeoMeta(
            name=self._vars["name"].get(),
            manufacturer=self._vars["mfr"].get(),
            year=year,
            genre=GENRE_BY_NAME.get(self._genre.get().lower(), 0),
            ngh=ngh,
            screenshot=screenshot,
        )
        swap_p_raw = self._swap_p.get()          # "no" | "auto" | "yes"
        swap_p: bool | str = (
            True  if swap_p_raw == "yes"  else
            "auto" if swap_p_raw == "auto" else
            False
        )
        diagnostic = self._diagnostic.get()
        self._log.clear()
        self._is_running = True
        self._run_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._cancel_event.clear()
        self._progress.config(mode="determinate", maximum=4, value=0)

        def work():
            try:
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                self._log.append(f"Packing: {src}")
                self.after(0, lambda: self._progress.config(value=1))

                # Auto-swap: Diagnose ins Log (nicht nochmal auf stdout)
                if swap_p == "auto":
                    from .core import parse_mame_dir, parse_mame_zip

                    rs_probe = (parse_mame_dir if src.is_dir() else parse_mame_zip)(src)
                    needed, reason = detect_swap_p_needed(rs_probe.p)
                    tag = "auto-swap: YES -" if needed else "auto-swap: no -"
                    self._log.append(f"  {tag} {reason}")
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")

                fn = mame_dir_to_neo if src.is_dir() else mame_zip_to_neo
                swap_verbose = swap_p != "auto"
                captured: list[warnings.WarningMessage] = []
                if diagnostic:
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        neo_data = fn(
                            src,
                            meta,
                            swap_p=swap_p,
                            diagnostic=True,
                            swap_verbose=swap_verbose,
                        )
                    captured = list(caught)
                else:
                    neo_data = fn(
                        src,
                        meta,
                        swap_p=swap_p,
                        diagnostic=False,
                        swap_verbose=swap_verbose,
                    )
                self.after(0, lambda: self._progress.config(value=2))
                for warning_msg in captured:
                    msg = str(warning_msg.message)
                    self._log.append(f"[WARN] {msg}")
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                dest = out or src.with_suffix(".neo")
                dest.write_bytes(neo_data)
                self.after(0, lambda: self._progress.config(value=3))
                self._log.append(f"Written: {dest}  ({len(neo_data)/1024/1024:.2f} MB)")
                self._log.append("[OK] Done.")
                self.after(0, lambda: self._progress.config(value=4))
            except Exception as e:
                self._log.append(f"[ERROR] {e}")
            finally:
                self.after(0, self._finish_run)

        _run_in_thread(work)

    def _finish_run(self):
        self._is_running = False
        self._run_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")
        self._schedule_validation()

    def _request_cancel(self):
        self._cancel_event.set()
        self._log.append("[WARN] Cancellation requested... waiting for safe stop.")

    def _set_status(self, level: str, text: str):
        colors = {"ok": "#2e7d32", "warn": "#8a6d3b", "error": "#b71c1c"}
        self._status_var.set(f"Status: {text}")
        self._status_label.config(fg=colors.get(level, "#444444"))

    def _schedule_validation(self):
        if self._validate_after_id:
            self.after_cancel(self._validate_after_id)
        self._validate_after_id = self.after(250, self._validate_inputs)

    def _validate_inputs(self):
        self._validate_after_id = None
        src_text = self._inp.value
        if not src_text:
            self._set_status("warn", "input ZIP or directory is empty")
            return

        src = Path(src_text)
        if not src.exists():
            self._set_status("error", "input path does not exist")
            return
        if not (src.is_dir() or zipfile.is_zipfile(src)):
            self._set_status("error", "input must be a directory or ZIP file")
            return

        for k in ("year", "ngh", "screenshot"):
            v = self._vars[k].get().strip()
            if not v:
                self._set_status("warn", f"{k} is empty")
                return
            try:
                n = int(v)
            except ValueError:
                self._set_status("error", f"{k} must be an integer")
                return
            if n < 0:
                self._set_status("error", f"{k} must be >= 0")
                return

        if not self._vars["name"].get().strip():
            self._set_status("warn", "name is empty")
            return
        if not self._vars["mfr"].get().strip():
            self._set_status("warn", "manufacturer is empty")
            return

        src_key = self._source_key(src)
        if src_key != self._roles_src_key:
            self._roles_src_key = src_key
            self._roles_missing = None
            self._roles_scan_error = None
            self._roles_scan_token += 1
            self._start_roles_scan(src, src_key, self._roles_scan_token)
            self._set_status("warn", "inspecting input roles...")
            return

        if self._roles_scan_running_token is not None:
            self._set_status("warn", "inspecting input roles...")
            return

        if self._roles_scan_error is not None:
            self._set_status("warn", "could not inspect input roles yet")
            return

        if self._roles_missing:
            self._set_status(
                "warn",
                f"missing required ROM role(s): {', '.join(self._roles_missing)} "
                "(expect p1/s1/m1 naming)",
            )
            return

        self._set_status("ok", "ready to pack")

    def _source_key(self, src: Path) -> tuple:
        st = src.stat()
        return (str(src.resolve()), src.is_dir(), st.st_mtime_ns, st.st_size)

    def _start_roles_scan(self, src: Path, src_key: tuple, token: int) -> None:
        self._roles_scan_running_token = token

        def work() -> None:
            missing: list[str] = []
            error: str | None = None
            try:
                roles = _scan_required_roles(src)
                missing = [r for r in ("P", "S", "M") if r not in roles]
            except Exception as e:
                error = str(e)

            def finish() -> None:
                if token != self._roles_scan_token or src_key != self._roles_src_key:
                    return
                self._roles_scan_running_token = None
                self._roles_scan_error = error
                self._roles_missing = None if error else missing
                self._schedule_validation()

            self.after(0, finish)

        _run_in_thread(work)

    def export_settings(self) -> dict:
        return {
            "input": self._inp.value,
            "output": self._out.value,
            "name": self._vars["name"].get(),
            "manufacturer": self._vars["mfr"].get(),
            "year": self._vars["year"].get(),
            "ngh": self._vars["ngh"].get(),
            "screenshot": self._vars["screenshot"].get(),
            "genre": self._genre.get(),
            "swap_mode": self._swap_p.get(),
            "diagnostic": bool(self._diagnostic.get()),
        }

    def apply_settings(self, data: dict) -> None:
        if not data:
            return
        self._inp.var.set(data.get("input", self._inp.var.get()))
        self._out.var.set(data.get("output", self._out.var.get()))
        self._vars["name"].set(data.get("name", self._vars["name"].get()))
        self._vars["mfr"].set(data.get("manufacturer", self._vars["mfr"].get()))
        self._vars["year"].set(data.get("year", self._vars["year"].get()))
        self._vars["ngh"].set(data.get("ngh", self._vars["ngh"].get()))
        self._vars["screenshot"].set(data.get("screenshot", self._vars["screenshot"].get()))
        self._genre.set(data.get("genre", self._genre.get()))
        self._swap_p.set(data.get("swap_mode", self._swap_p.get()))
        self._diagnostic.set(bool(data.get("diagnostic", self._diagnostic.get())))
        self._schedule_validation()

    def reset_defaults(self):
        self._inp.var.set("")
        self._out.var.set("")
        self._vars["name"].set("Unknown")
        self._vars["mfr"].set("Unknown")
        self._vars["year"].set("0")
        self._vars["ngh"].set("0")
        self._vars["screenshot"].set("0")
        self._genre.set("Other")
        self._swap_p.set("auto")
        self._diagnostic.set(False)
        self._progress.config(value=0)
        self._roles_src_key = None
        self._roles_missing = None
        self._roles_scan_error = None
        self._roles_scan_token += 1
        self._roles_scan_running_token = None
        self._schedule_validation()


# ---------------------------------------------------------------------------
# Verify tab
# ---------------------------------------------------------------------------

class VerifyTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._is_running = False
        self._cancel_event = threading.Event()
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 4}

        self._neo = _FileRow(self, "Input .neo:",
                             filetypes=[("NEO files", "*.neo"), ("All", "*.*")])
        self._neo.pack(fill="x", **pad)

        row = ttk.Frame(self)
        row.pack(fill="x", **pad)
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text="Prefix:", width=14, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        self._prefix = tk.StringVar()
        ttk.Entry(row, textvariable=self._prefix, width=14).grid(
            row=0, column=1, sticky="w", padx=4
        )
        ttk.Label(row, text="Format:", width=8).grid(
            row=0, column=2, sticky="w", padx=(12, 0)
        )
        self._fmt = tk.StringVar(value="mame")
        ttk.Radiobutton(row, text="MAME", variable=self._fmt, value="mame").grid(
            row=0, column=3, sticky="w"
        )
        ttk.Radiobutton(row, text="Darksoft", variable=self._fmt, value="darksoft").grid(
            row=0, column=4, sticky="w"
        )

        row2 = ttk.Frame(self)
        row2.pack(fill="x", **pad)
        row2.columnconfigure(1, weight=1)
        self._c_size = _SizeCombo(row2, "C Chip Size:", _C_CHIP_SIZES, "auto (C_total ÷ 2)")
        self._c_size.grid(row=0, column=0, sticky="w")

        ctrl_row = ttk.Frame(self)
        ctrl_row.pack(fill="x", padx=8, pady=3)
        self._run_btn = ttk.Button(ctrl_row, text="Verify Roundtrip", command=self._run)
        self._run_btn.grid(row=0, column=0, padx=(0, 8))
        self._cancel_btn = ttk.Button(ctrl_row, text="Cancel", command=self._request_cancel, state="disabled")
        self._cancel_btn.grid(row=0, column=1, padx=(0, 8))
        self._progress = ttk.Progressbar(ctrl_row, mode="determinate", length=220, maximum=4, value=0)
        self._progress.grid(row=0, column=2, sticky="w")
        ctrl_row.columnconfigure(3, weight=1)
        self._log = _LogBox(self, height=12)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

    def _run(self):
        if self._is_running:
            return
        neo_path = Path(self._neo.value)
        if not neo_path.exists():
            messagebox.showerror("Error", f"File not found: {neo_path}"); return

        prefix = self._prefix.get().strip() or neo_path.stem
        fmt    = self._fmt.get()
        self._log.clear()
        self._is_running = True
        self._run_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._cancel_event.clear()
        self._progress.config(mode="determinate", maximum=4, value=0)

        def work():
            try:
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                original    = neo_path.read_bytes()
                original_rs = parse_neo(original)
                c_chip_size = _c_chip_size_from_str(self._c_size.value_str, len(original_rs.c))
                self._log.append(f"Reading: {neo_path}")
                self.after(0, lambda: self._progress.config(value=1))
                self._log.append("Step 1: Extracting ROM data…")
                zip_data = extract_romset_to_zip(original_rs, name_prefix=prefix,
                                                 fmt=fmt, c_chip_size=c_chip_size)
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                self.after(0, lambda: self._progress.config(value=2))
                self._log.append("Step 2: Repacking to .neo…")
                meta = original_rs.meta
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
                    tf.write(zip_data)
                    tmp_zip = Path(tf.name)
                try:
                    rebuilt = mame_zip_to_neo(tmp_zip, meta)
                finally:
                    tmp_zip.unlink(missing_ok=True)
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                self.after(0, lambda: self._progress.config(value=3))
                self._log.append("Step 3: Comparing ROM data regions...")
                result = verify_roundtrip(original, rebuilt)
                self._log.append("")
                self._log.append("[OK] PASS - extraction is lossless." if result.ok
                                 else "[ERROR] FAIL - ROM data mismatch!")
                self._log.append(f"  Original ROM MD5 : {result.original_rom_md5}")
                self._log.append(f"  Rebuilt  ROM MD5 : {result.rebuilt_rom_md5}")
                self._log.append(f"  File size match  : {result.file_size_match}")
                self._log.append(f"  Details          : {result.details}")
                self.after(0, lambda: self._progress.config(value=4))
            except Exception as e:
                self._log.append(f"[ERROR] {e}")
            finally:
                self.after(0, self._finish_run)

        _run_in_thread(work)

    def _finish_run(self):
        self._is_running = False
        self._run_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")

    def _request_cancel(self):
        self._cancel_event.set()
        self._log.append("[WARN] Cancellation requested... waiting for safe stop.")

    def export_settings(self) -> dict:
        return {
            "input": self._neo.value,
            "prefix": self._prefix.get(),
            "format": self._fmt.get(),
            "c_chip_size": self._c_size.value_str,
        }

    def apply_settings(self, data: dict) -> None:
        if not data:
            return
        self._neo.var.set(data.get("input", self._neo.var.get()))
        self._prefix.set(data.get("prefix", self._prefix.get()))
        self._fmt.set(data.get("format", self._fmt.get()))
        if data.get("c_chip_size"):
            self._c_size.var.set(data["c_chip_size"])

    def reset_defaults(self):
        self._neo.var.set("")
        self._prefix.set("")
        self._fmt.set("mame")
        self._c_size.var.set("auto (C_total ÷ 2)")
        self._progress.config(value=0)


# ---------------------------------------------------------------------------
# Info tab
# ---------------------------------------------------------------------------

class InfoTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        self._neo = _FileRow(self, "Input .neo:",
                             filetypes=[("NEO files", "*.neo"), ("All", "*.*")])
        self._neo.pack(fill="x", **pad)
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", **pad)
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(2, weight=1)
        ttk.Button(btn_row, text="Show Info", command=self._run).grid(row=0, column=1)
        self._log = _LogBox(self, height=14)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

    def _run(self):
        neo_path = Path(self._neo.value)
        if not neo_path.exists():
            messagebox.showerror("Error", f"File not found: {neo_path}"); return
        self._log.clear()
        try:
            neo_data = neo_path.read_bytes()
            romset   = parse_neo(neo_data)
            self._log.append(f"File : {neo_path}")
            self._log.append(romset.meta.format_info(romset))
        except ValueError as e:
            self._log.append(f"[ERROR] Invalid .neo file: {e}")
        except OSError as e:
            self._log.append(f"[ERROR] Could not read file: {e}")
        except Exception as e:
            self._log.append(f"[ERROR] Unexpected error: {type(e).__name__}: {e}")

    def export_settings(self) -> dict:
        return {
            "input": self._neo.value,
        }

    def apply_settings(self, data: dict) -> None:
        if not data:
            return
        self._neo.var.set(data.get("input", self._neo.var.get()))

    def reset_defaults(self):
        self._neo.var.set("")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = NeoConvApp()
    app.mainloop()


if __name__ == "__main__":
    main()
