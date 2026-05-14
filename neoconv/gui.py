"""
neoconv GUI
~~~~~~~~~~~
Tkinter GUI for neoconv.
"""

from __future__ import annotations

import os
import sys
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
    NEO_HEADER_SIZE,
    NeoMeta,
    collect_pack_psm_roles_for_validation,
    detect_swap_p_needed,
    extract_romset,
    extract_romset_to_zip,
    mame_dir_to_neo,
    mame_zip_to_neo,
    pack_psm_role_from_basename,
    parse_neo,
    parse_neo_header_metadata,
    replace_neo_metadata,
    write_bytes_atomic,
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


def _name_to_required_role(filename: str) -> str | None:
    return pack_psm_role_from_basename(filename)


def _scan_required_roles(src: Path) -> set[str]:
    if src.is_dir():
        names = [str(p) for p in src.iterdir() if p.is_file()]
    elif zipfile.is_zipfile(src):
        with zipfile.ZipFile(src, "r") as zf:
            names = [e.filename for e in zf.infolist() if not e.is_dir()]
    else:
        return set()
    return collect_pack_psm_roles_for_validation(names)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class NeoConvApp(TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"neoconv {__version__}")
        # Allow resizing so the log area can grow on demand.
        self.resizable(True, True)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        for tab, label in [
            (PackTab(nb),    "Pack (files → .neo)"),
            (ExtractTab(nb), "Extract (.neo → files)"),
            (EditTab(nb),    "Edit (.neo)"),
            (InfoTab(nb),    "Info (.neo)"),
        ]:
            nb.add(tab, text=label)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self.destroy()


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
        show_label: bool = True,
        **kw,
    ):
        super().__init__(parent, **kw)
        self._mode = mode
        self._ft   = filetypes or []

        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=entry_width)
        self.button = ttk.Button(self, text="Browse…", command=self._browse)

        if show_label:
            self.columnconfigure(1, weight=1)
            self.label: ttk.Label | None = ttk.Label(
                self, text=label, width=label_width, anchor="w"
            )
            self.label.grid(row=0, column=0, sticky="w")
            ec = 1
        else:
            self.columnconfigure(0, weight=1)
            self.label = None
            ec = 0

        self.entry.grid(row=0, column=ec, sticky="ew", padx=4)
        self.button.grid(row=0, column=ec + 1, sticky="w")

        self._extra_buttons: list[ttk.Button] = []
        for i, (text, cmd) in enumerate(extra_buttons or []):
            b = ttk.Button(self, text=text, command=cmd)
            b.grid(row=0, column=ec + 2 + i, sticky="w", padx=(6 if i == 0 else 4, 0))
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


# Readable monospaced log font (Courier 9 was too small on HiDPI / dark UI).
_LOG_BOX_FONT: tuple[str, int] = (
    ("Menlo", 13)
    if sys.platform == "darwin"
    else ("Consolas", 12)
    if os.name == "nt"
    else ("DejaVu Sans Mono", 12)
)


# Shared label width (chars) for Pack / Extract section grids.
_SECTION_LABEL_WIDTH = 18


class _LogBox(scrolledtext.ScrolledText):
    def __init__(self, parent, **kw):
        kw.setdefault("height", 8)
        kw.setdefault("state", "disabled")
        kw.setdefault("font", _LOG_BOX_FONT)
        super().__init__(parent, **kw)

    def clear(self):
        self.config(state="normal"); self.delete("1.0", "end"); self.config(state="disabled")

    def append(self, text: str):
        self.config(state="normal")
        self.insert("end", text + "\n")
        self.see("end")
        self.config(state="disabled")


class _SizeCombo(ttk.Frame):
    def __init__(
        self,
        parent,
        label: str,
        options: list[tuple[str, int]],
        default_label: str,
        label_width: int = 14,
        **kw,
    ):
        super().__init__(parent, **kw)
        ttk.Label(self, text=label, width=label_width, anchor="w").pack(side="left")
        self.var = tk.StringVar(value=default_label)
        ttk.Combobox(self, textvariable=self.var,
                     values=[l for l, _ in options],
                     state="readonly", width=22).pack(side="left", padx=4)

    @property
    def value_str(self) -> str:
        return self.var.get()


# Braille-pattern spinner (compact; works on macOS / most modern systems).
_BUSY_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class _BusySpinner(ttk.Frame):
    """Minimal busy indicator while a worker thread runs."""

    def __init__(self, parent: tk.Misc, interval_ms: int = 80, **kw):
        super().__init__(parent, **kw)
        self._interval_ms = interval_ms
        self._label = ttk.Label(self, text="", width=2, anchor="center")
        self._label.pack()
        self._after_id: str | None = None
        self._frame = 0

    def start(self) -> None:
        self.stop()
        self._frame = 0
        self._tick()

    def stop(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._label.configure(text="")

    def _tick(self) -> None:
        self._label.configure(text=_BUSY_SPINNER_FRAMES[self._frame])
        self._frame = (self._frame + 1) % len(_BUSY_SPINNER_FRAMES)
        self._after_id = self.after(self._interval_ms, self._tick)


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
        lw = _SECTION_LABEL_WIDTH
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0

        files_frame = ttk.LabelFrame(self, text="Files", padding=(8, 6))
        files_frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        # One grid: column 0 is label / radios, column 1 is paths. Tk sizes column 0
        # to the widest cell in one pass — no idle-time minsize bump on the window.
        files_frame.columnconfigure(1, weight=1)

        ttk.Label(files_frame, text="Input .neo:", width=lw, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, 2)
        )
        self._neo = _FileRow(
            files_frame,
            "",
            filetypes=[("NEO files", "*.neo"), ("All", "*.*")],
            label_width=lw,
            show_label=False,
        )
        self._neo.grid(row=0, column=1, sticky="wen", pady=(0, 2))

        self._out_mode = tk.StringVar(value="zip")

        self._rb_zip = ttk.Radiobutton(
            files_frame,
            text="Output ZIP file",
            variable=self._out_mode,
            value="zip",
            command=self._toggle_out,
        )
        # Same right pad as _FileRow label→entry (4) so column 0 matches a full _FileRow row.
        self._rb_zip.grid(row=1, column=0, sticky="w", padx=(0, 4), pady=2)
        self._out_zip = _FileRow(
            files_frame,
            "",
            mode="save",
            filetypes=[("ZIP", "*.zip")],
            show_label=False,
        )
        self._out_zip.grid(row=1, column=1, sticky="wen", pady=2)

        self._rb_dir = ttk.Radiobutton(
            files_frame,
            text="Output Directory",
            variable=self._out_mode,
            value="dir",
            command=self._toggle_out,
        )
        self._rb_dir.grid(row=2, column=0, sticky="w", padx=(0, 4), pady=2)
        self._out_dir = _FileRow(
            files_frame,
            "",
            mode="opendir",
            filetypes=[],
            show_label=False,
        )
        self._out_dir.grid(row=2, column=1, sticky="wen", pady=2)
        self._out_dir_var = self._out_dir.var
        self._out_dir_entry = self._out_dir.entry
        self._out_dir_button = self._out_dir.button
        row += 1

        opt_frame = ttk.LabelFrame(self, text="Options", padding=(8, 6))
        opt_frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        opt_frame.columnconfigure(1, weight=1)

        self._fmt = tk.StringVar(value="mame")
        ttk.Label(opt_frame, text="Format:", width=lw, anchor="w").grid(
            row=0, column=0, sticky="w", pady=2
        )
        fmt_inner = ttk.Frame(opt_frame)
        fmt_inner.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        ttk.Radiobutton(
            fmt_inner, text="MAME (.bin)", variable=self._fmt, value="mame"
        ).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(
            fmt_inner, text="Darksoft (.rom)", variable=self._fmt, value="darksoft"
        ).pack(side="left")

        self._prefix = tk.StringVar()
        ttk.Label(opt_frame, text="Prefix:", width=lw, anchor="w").grid(
            row=1, column=0, sticky="w", pady=2
        )
        ttk.Entry(opt_frame, textvariable=self._prefix, width=12).grid(
            row=1, column=1, sticky="w", padx=4, pady=2
        )

        self._c_size = _SizeCombo(
            opt_frame,
            "C Chip Size:",
            _C_CHIP_SIZES,
            "auto (C_total ÷ 2)",
            label_width=lw,
        )
        self._c_size.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1

        ctrl_row = ttk.Frame(self)
        ctrl_row.grid(row=row, column=0, sticky="ew", padx=8, pady=3)
        self._run_btn = ttk.Button(ctrl_row, text="Extract", command=self._run)
        self._run_btn.grid(row=0, column=0, padx=(0, 8))
        self._cancel_btn = ttk.Button(
            ctrl_row, text="Cancel", command=self._request_cancel, state="disabled"
        )
        self._cancel_btn.grid(row=0, column=1, padx=(0, 8))
        self._busy = _BusySpinner(ctrl_row)
        self._busy.grid(row=0, column=2, sticky="w")
        ctrl_row.columnconfigure(3, weight=1)
        row += 1

        self._log = _LogBox(self, height=16)
        self._log.grid(row=row, column=0, sticky="nsew", padx=8, pady=(4, 8))
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
        self._busy.start()

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
        self._busy.stop()

    def _request_cancel(self):
        self._cancel_event.set()
        self._log.append("[WARN] Cancellation requested... waiting for safe stop.")


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
        lw = _SECTION_LABEL_WIDTH

        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        row = 0

        files_frame = ttk.LabelFrame(self, text="Files", padding=(8, 6))
        files_frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        files_frame.columnconfigure(0, weight=1)

        self._inp = _FileRow(
            files_frame,
            "Input ZIP/Dir:",
            filetypes=[("ZIP files", "*.zip"), ("All", "*.*")],
            label_width=lw,
            extra_buttons=[
                (
                    "Pick dir…",
                    lambda: self._inp.var.set(
                        filedialog.askdirectory() or self._inp.value
                    ),
                )
            ],
        )
        self._inp.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        self._inp.var.trace_add("write", lambda *_: self._schedule_validation())

        self._out = _FileRow(
            files_frame,
            "Output .neo:",
            mode="save",
            filetypes=[("NEO files", "*.neo"), ("All", "*.*")],
            label_width=lw,
        )
        self._out.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self._out.var.trace_add("write", lambda *_: self._schedule_validation())
        row += 1

        meta_frame = ttk.LabelFrame(self, text="Metadata", padding=(8, 6))
        meta_frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
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
            ttk.Label(meta_frame, text=lbl, width=lw, anchor="w").grid(
                row=i, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=default)
            self._vars[key] = v
            v.trace_add("write", lambda *_: self._schedule_validation())
            if key == "name":
                _enforce_latin1_byte_limit(v, 32)
            elif key == "mfr":
                _enforce_latin1_byte_limit(v, 16)
            ent_w = 11 if key in ("year", "ngh", "screenshot") else None
            ent = ttk.Entry(
                meta_frame,
                textvariable=v,
                width=(ent_w if ent_w else 24),
            )
            sticky = "w" if ent_w else "ew"
            ent.grid(row=i, column=1, sticky=sticky, padx=4, pady=2)
        gr = len(fields)
        ttk.Label(meta_frame, text="Genre:", width=lw, anchor="w").grid(
            row=gr, column=0, sticky="w", pady=2)
        self._genre = tk.StringVar(value="Other")
        self._genre.trace_add("write", lambda *_: self._schedule_validation())
        ttk.Combobox(
            meta_frame,
            textvariable=self._genre,
            values=list(GENRES.values()),
            state="readonly",
            width=max(18, lw),
        ).grid(row=gr, column=1, sticky="w", padx=4, pady=2)
        row += 1

        opt_frame = ttk.LabelFrame(self, text="Options", padding=(8, 6))
        opt_frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        opt_frame.columnconfigure(1, weight=1)

        ttk.Label(opt_frame, text="P-ROM Bank Swap:", width=lw, anchor="w").grid(
            row=0, column=0, rowspan=3, sticky="nw", pady=2
        )
        self._swap_p = tk.StringVar(value="auto")
        self._swap_p.trace_add("write", lambda *_: self._schedule_validation())
        ttk.Radiobutton(
            opt_frame,
            text="Auto-detect  (default)",
            variable=self._swap_p,
            value="auto",
        ).grid(row=0, column=1, sticky="w", padx=4, pady=1)
        ttk.Radiobutton(
            opt_frame,
            text="No  (never swap)",
            variable=self._swap_p,
            value="no",
        ).grid(row=1, column=1, sticky="w", padx=4, pady=1)
        ttk.Radiobutton(
            opt_frame,
            text="Yes  (always swap)",
            variable=self._swap_p,
            value="yes",
        ).grid(row=2, column=1, sticky="w", padx=4, pady=1)

        self._diagnostic = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt_frame,
            text="Diagnostic mode  (log warnings for unrecognized files)",
            variable=self._diagnostic,
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=4, pady=(6, 2))
        row += 1

        ctrl_row = ttk.Frame(self)
        ctrl_row.grid(row=row, column=0, sticky="ew", padx=8, pady=3)
        self._run_btn = ttk.Button(ctrl_row, text="Pack → .neo", command=self._run)
        self._run_btn.grid(row=0, column=0, padx=(0, 8))
        self._cancel_btn = ttk.Button(
            ctrl_row, text="Cancel", command=self._request_cancel, state="disabled"
        )
        self._cancel_btn.grid(row=0, column=1, padx=(0, 8))
        self._busy = _BusySpinner(ctrl_row)
        self._busy.grid(row=0, column=2, sticky="w")
        self._status_wrap = tk.Frame(ctrl_row, highlightthickness=0, bd=0)
        self._status_wrap.grid(row=0, column=3, sticky="nsew", padx=(10, 0))
        ctrl_row.columnconfigure(3, weight=1)
        self._status_var = tk.StringVar(value="Status: waiting for input")
        # wraplength tracks allocated width so longer status text wraps instead of
        # widening the toplevel (fixed ``width=…`` in chars made the default window wider).
        self._status_label = tk.Label(
            self._status_wrap,
            textvariable=self._status_var,
            anchor="nw",
            justify="left",
            wraplength=280,
        )
        self._status_label.pack(fill="x", anchor="nw")
        self._status_wrap.bind("<Configure>", self._sync_pack_status_wraplength)
        row += 1

        self._log = _LogBox(self, height=16)
        self._log.grid(row=row, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self._schedule_validation()

    def _sync_pack_status_wraplength(self, event: tk.Event) -> None:
        if event.widget is not self._status_wrap:
            return
        tw = int(event.width)
        if tw < 8:
            return
        self._status_label.configure(wraplength=max(1, tw - 8))

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
        self._busy.start()

        def work():
            try:
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                self._log.append(f"Packing: {src}")

                pack_warnings: list[warnings.WarningMessage] = []

                # Auto-swap: Diagnose ins Log (nicht nochmal auf stdout)
                if swap_p == "auto":
                    from .core import parse_mame_dir, parse_mame_zip

                    with warnings.catch_warnings(record=True) as wprobe:
                        warnings.simplefilter("always")
                        rs_probe = (parse_mame_dir if src.is_dir() else parse_mame_zip)(src)
                    pack_warnings.extend(wprobe)

                    needed, reason = detect_swap_p_needed(rs_probe.p)
                    tag = "auto-swap: YES -" if needed else "auto-swap: no -"
                    self._log.append(f"  {tag} {reason}")
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")

                fn = mame_dir_to_neo if src.is_dir() else mame_zip_to_neo
                swap_verbose = swap_p != "auto"
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
                    pack_warnings.extend(caught)
                else:
                    with warnings.catch_warnings(record=True) as caught_nd:
                        warnings.simplefilter("always")
                        neo_data = fn(
                            src,
                            meta,
                            swap_p=swap_p,
                            diagnostic=False,
                            swap_verbose=swap_verbose,
                        )
                    pack_warnings.extend(caught_nd)

                _seen_warn: set[str] = set()
                for wm in pack_warnings:
                    msg = str(wm.message)
                    if msg not in _seen_warn:
                        _seen_warn.add(msg)
                        self._log.append(f"[WARN] {msg}")
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                dest = out or src.with_suffix(".neo")
                dest.write_bytes(neo_data)
                self._log.append(f"Written: {dest}  ({len(neo_data)/1024/1024:.2f} MB)")
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
        self._busy.stop()
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


# ---------------------------------------------------------------------------
# Edit tab
# ---------------------------------------------------------------------------

class EditTab(ttk.Frame):
    """Rewrite .neo header metadata from form fields (ROM data unchanged)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._is_running = False
        self._cancel_event = threading.Event()
        self._load_after_id: str | None = None
        self._suppress_meta_fill = False
        self._build()

    def _build(self):
        lw = _SECTION_LABEL_WIDTH
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0
        files_frame = ttk.LabelFrame(self, text="File", padding=(8, 6))
        files_frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        files_frame.columnconfigure(0, weight=1)

        self._neo = _FileRow(
            files_frame,
            "Input .neo:",
            filetypes=[("NEO files", "*.neo"), ("All", "*.*")],
            label_width=lw,
        )
        self._neo.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        self._neo.var.trace_add("write", lambda *_: self._schedule_meta_load())

        self._out = _FileRow(
            files_frame,
            "Output .neo (optional):",
            mode="save",
            filetypes=[("NEO files", "*.neo"), ("All", "*.*")],
            label_width=lw,
        )
        self._out.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        row += 1

        meta_frame = ttk.LabelFrame(self, text="Metadata", padding=(8, 6))
        meta_frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
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
            ttk.Label(meta_frame, text=lbl, width=lw, anchor="w").grid(
                row=i, column=0, sticky="w", pady=2
            )
            v = tk.StringVar(value=default)
            self._vars[key] = v
            if key == "name":
                _enforce_latin1_byte_limit(v, 32)
            elif key == "mfr":
                _enforce_latin1_byte_limit(v, 16)
            ent_w = 11 if key in ("year", "ngh", "screenshot") else None
            ent = ttk.Entry(
                meta_frame,
                textvariable=v,
                width=(ent_w if ent_w else 24),
            )
            sticky = "w" if ent_w else "ew"
            ent.grid(row=i, column=1, sticky=sticky, padx=4, pady=2)
        gr = len(fields)
        ttk.Label(meta_frame, text="Genre:", width=lw, anchor="w").grid(
            row=gr, column=0, sticky="w", pady=2
        )
        self._genre = tk.StringVar(value="Other")
        ttk.Combobox(
            meta_frame,
            textvariable=self._genre,
            values=list(GENRES.values()),
            state="readonly",
            width=max(18, lw),
        ).grid(row=gr, column=1, sticky="w", padx=4, pady=2)
        row += 1

        ctrl_row = ttk.Frame(self)
        ctrl_row.grid(row=row, column=0, sticky="ew", padx=8, pady=3)
        self._run_btn = ttk.Button(
            ctrl_row, text="Write metadata", command=self._run
        )
        self._run_btn.grid(row=0, column=0, padx=(0, 8))
        self._cancel_btn = ttk.Button(
            ctrl_row, text="Cancel", command=self._request_cancel, state="disabled"
        )
        self._cancel_btn.grid(row=0, column=1, padx=(0, 8))
        self._busy = _BusySpinner(ctrl_row)
        self._busy.grid(row=0, column=2, sticky="w")
        ctrl_row.columnconfigure(3, weight=1)
        row += 1

        self._log = _LogBox(self, height=16)
        self._log.grid(row=row, column=0, sticky="nsew", padx=8, pady=(4, 8))

    def _schedule_meta_load(self, *_args) -> None:
        if self._suppress_meta_fill:
            return
        if self._load_after_id is not None:
            try:
                self.after_cancel(self._load_after_id)
            except tk.TclError:
                pass
        self._load_after_id = self.after(400, self._load_metadata_from_file)

    def _load_metadata_from_file(self) -> None:
        self._load_after_id = None
        path = Path(self._neo.var.get().strip())
        if not path.is_file():
            return
        try:
            with path.open("rb") as f:
                hdr = f.read(NEO_HEADER_SIZE)
            meta = parse_neo_header_metadata(hdr)
        except (OSError, ValueError):
            return
        self._suppress_meta_fill = True
        try:
            self._vars["name"].set(meta.name)
            self._vars["mfr"].set(meta.manufacturer)
            self._vars["year"].set(str(meta.year))
            self._vars["ngh"].set(str(meta.ngh))
            self._vars["screenshot"].set(str(meta.screenshot))
            self._genre.set(GENRES.get(meta.genre) or "Other")
        finally:
            self._suppress_meta_fill = False

    def _run(self) -> None:
        if self._is_running:
            return
        inp = Path(self._neo.value)
        if not inp.exists():
            messagebox.showerror("Error", f"File not found: {inp}")
            return
        try:
            year = int(self._vars["year"].get())
            ngh = int(self._vars["ngh"].get())
            screenshot = int(self._vars["screenshot"].get())
        except ValueError:
            messagebox.showerror(
                "Error", "Year, NGH and Screenshot must be integers."
            )
            return
        genre_id = GENRE_BY_NAME.get(self._genre.get().lower(), 0)
        out_raw = self._out.value.strip()
        dest = Path(out_raw) if out_raw else inp

        self._log.clear()
        self._is_running = True
        self._run_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._cancel_event.clear()
        self._busy.start()

        def work() -> None:
            try:
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                self._log.append(f"Reading: {inp}")
                data = inp.read_bytes()
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                new_data = replace_neo_metadata(
                    data,
                    name=self._vars["name"].get(),
                    manufacturer=self._vars["mfr"].get(),
                    year=year,
                    genre=genre_id,
                    ngh=ngh,
                    screenshot=screenshot,
                )
                if self._cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")
                write_bytes_atomic(dest, new_data)
                self._log.append(f"Written: {dest}")
                rs = parse_neo(new_data)
                self._log.append(rs.meta.format_info(rs))
                self._log.append("[OK] Metadata updated.")
            except Exception as e:
                self._log.append(f"[ERROR] {e}")
            finally:
                self.after(0, self._finish_run)

        _run_in_thread(work)

    def _finish_run(self) -> None:
        self._is_running = False
        self._run_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")
        self._busy.stop()

    def _request_cancel(self) -> None:
        self._cancel_event.set()
        self._log.append("[WARN] Cancellation requested... waiting for safe stop.")


# ---------------------------------------------------------------------------
# Info tab
# ---------------------------------------------------------------------------

class InfoTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build()

    def _build(self):
        lw = _SECTION_LABEL_WIDTH
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        row = 0
        file_frame = ttk.LabelFrame(self, text="File", padding=(8, 6))
        file_frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        file_frame.columnconfigure(0, weight=1)
        self._neo = _FileRow(
            file_frame,
            "Input .neo:",
            filetypes=[("NEO files", "*.neo"), ("All", "*.*")],
            label_width=lw,
        )
        self._neo.grid(row=0, column=0, sticky="ew")
        row += 1

        ctrl_row = ttk.Frame(self)
        ctrl_row.grid(row=row, column=0, sticky="ew", padx=8, pady=3)
        ttk.Button(ctrl_row, text="Show Info", command=self._run).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ctrl_row.columnconfigure(1, weight=1)
        row += 1

        self._log = _LogBox(self, height=16)
        self._log.grid(row=row, column=0, sticky="nsew", padx=8, pady=(4, 8))

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = NeoConvApp()
    app.mainloop()


if __name__ == "__main__":
    main()
