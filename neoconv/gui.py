"""
neoconv GUI
~~~~~~~~~~~
Tkinter GUI for neoconv. Feature-complete with the CLI.
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class NeoConvApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"neoconv {__version__}")
        self.resizable(False, False)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        for tab, label in [
            (ExtractTab(nb), "Extract (.neo → files)"),
            (PackTab(nb),    "Pack (files → .neo)"),
            (VerifyTab(nb),  "Verify (Roundtrip)"),
            (InfoTab(nb),    "Info (.neo)"),
        ]:
            nb.add(tab, text=label)


# ---------------------------------------------------------------------------
# Shared widgets
# ---------------------------------------------------------------------------

class _FileRow(ttk.Frame):
    def __init__(self, parent, label: str, mode: str = "open",
                 filetypes=None, label_width: int = 14, **kw):
        super().__init__(parent, **kw)
        self._mode = mode
        self._ft   = filetypes or []
        self.label = ttk.Label(self, text=label, width=label_width, anchor="w")
        self.label.pack(side="left")
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=42)
        self.entry.pack(side="left", padx=4)
        self.button = ttk.Button(self, text="Browse…", command=self._browse)
        self.button.pack(side="left")

    def _browse(self):
        p = (filedialog.askopenfilename(filetypes=self._ft) if self._mode == "open"
             else filedialog.askdirectory() if self._mode == "opendir"
             else filedialog.asksaveasfilename(filetypes=self._ft))
        if p:
            self.var.set(p)

    @property
    def value(self) -> str:
        return self.var.get().strip()


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

        self._out_dir_var = tk.StringVar()
        dir_row = ttk.Frame(out_frame)
        dir_row.grid(row=1, column=1, sticky="ew", padx=4)
        self._out_dir_entry = ttk.Entry(dir_row, textvariable=self._out_dir_var, width=38)
        self._out_dir_entry.pack(side="left", padx=4)
        self._out_dir_button = ttk.Button(
            dir_row, text="Browse…",
            command=lambda: self._out_dir_var.set(
                filedialog.askdirectory() or self._out_dir_var.get()
            ),
        )
        self._out_dir_button.pack(side="left")
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

        self._run_btn = ttk.Button(self, text="Extract", command=self._run)
        self._run_btn.pack(**pad)
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

        def work():
            try:
                neo_data    = neo_path.read_bytes()
                romset      = parse_neo(neo_data)
                c_chip_size = _c_chip_size_from_str(self._c_size.value_str, len(romset.c))
                self._log.append(f"Reading: {neo_path}")
                self._log.append(f"C chip size: {c_chip_size:,} bytes")

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
                self._log.append("✅ Done.")
            except Exception as e:
                self._log.append(f"❌ Error: {e}")
            finally:
                self.after(0, self._finish_run)

        _run_in_thread(work)

    def _finish_run(self):
        self._is_running = False
        self._run_btn.config(state="normal")


# ---------------------------------------------------------------------------
# Pack tab
# ---------------------------------------------------------------------------

class PackTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._is_running = False
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 3}

        self._inp = _FileRow(self, "Input ZIP/Dir:",
                             filetypes=[("ZIP files", "*.zip"), ("All", "*.*")])
        self._inp.pack(fill="x", **pad)
        ttk.Button(self, text="…or pick directory",
                   command=lambda: self._inp.var.set(
                       filedialog.askdirectory() or self._inp.value)
                   ).pack(anchor="w", padx=80)

        self._out = _FileRow(self, "Output .neo:", mode="save",
                             filetypes=[("NEO files", "*.neo"), ("All", "*.*")])
        self._out.pack(fill="x", **pad)

        # Metadata
        meta_frame = ttk.LabelFrame(self, text="Metadata")
        meta_frame.pack(fill="x", padx=8, pady=4)
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
            ttk.Entry(meta_frame, textvariable=v, width=30).grid(
                row=i, column=1, sticky="w", padx=4)
        gr = len(fields)
        ttk.Label(meta_frame, text="Genre:", width=14, anchor="w").grid(
            row=gr, column=0, sticky="w", padx=4, pady=2)
        self._genre = tk.StringVar(value="Other")
        ttk.Combobox(meta_frame, textvariable=self._genre,
                     values=list(GENRES.values()), state="readonly", width=16
                     ).grid(row=gr, column=1, sticky="w", padx=4)

        # Options
        opt_frame = ttk.LabelFrame(self, text="Options")
        opt_frame.pack(fill="x", padx=8, pady=4)

        # P-ROM swap: 3-way radio (no / auto / yes)
        swap_row = ttk.Frame(opt_frame)
        swap_row.pack(anchor="w", padx=4, pady=2)
        ttk.Label(swap_row, text="P-ROM Bank Swap:", width=18, anchor="w").pack(side="left")
        self._swap_p = tk.StringVar(value="auto")
        for val, label in [
            ("no",   "No  (never swap)"),
            ("auto", "Auto-detect  (default)"),
            ("yes",  "Yes  (always swap)"),
        ]:
            ttk.Radiobutton(swap_row, text=label, variable=self._swap_p,
                            value=val).pack(side="left", padx=(0, 10))

        self._diagnostic = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt_frame,
            text="Diagnostic mode  (log warnings for unrecognized files)",
            variable=self._diagnostic,
        ).pack(anchor="w", padx=4, pady=2)

        self._run_btn = ttk.Button(self, text="Pack → .neo", command=self._run)
        self._run_btn.pack(**pad)
        self._log = _LogBox(self)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

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

        def work():
            try:
                self._log.append(f"Packing: {src}")

                # Auto-swap: Diagnose ins Log (nicht nochmal auf stdout)
                if swap_p == "auto":
                    from .core import parse_mame_dir, parse_mame_zip

                    rs_probe = (parse_mame_dir if src.is_dir() else parse_mame_zip)(src)
                    needed, reason = detect_swap_p_needed(rs_probe.p)
                    tag = "auto-swap: YES —" if needed else "auto-swap: no  —"
                    self._log.append(f"  {tag} {reason}")

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
                for warning_msg in captured:
                    msg = str(warning_msg.message)
                    self._log.append(f"⚠️  {msg}")
                dest = out or src.with_suffix(".neo")
                dest.write_bytes(neo_data)
                self._log.append(f"Written: {dest}  ({len(neo_data)/1024/1024:.2f} MB)")
                self._log.append("✅ Done.")
            except Exception as e:
                self._log.append(f"❌ Error: {e}")
            finally:
                self.after(0, self._finish_run)

        _run_in_thread(work)

    def _finish_run(self):
        self._is_running = False
        self._run_btn.config(state="normal")


# ---------------------------------------------------------------------------
# Verify tab
# ---------------------------------------------------------------------------

class VerifyTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._is_running = False
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 4}

        self._neo = _FileRow(self, "Input .neo:",
                             filetypes=[("NEO files", "*.neo"), ("All", "*.*")])
        self._neo.pack(fill="x", **pad)

        row = ttk.Frame(self)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Prefix:", width=14, anchor="w").pack(side="left")
        self._prefix = tk.StringVar()
        ttk.Entry(row, textvariable=self._prefix, width=14).pack(side="left", padx=4)
        ttk.Label(row, text="Format:", width=8).pack(side="left", padx=(12, 0))
        self._fmt = tk.StringVar(value="mame")
        ttk.Radiobutton(row, text="MAME",     variable=self._fmt, value="mame").pack(side="left")
        ttk.Radiobutton(row, text="Darksoft", variable=self._fmt, value="darksoft").pack(side="left")

        row2 = ttk.Frame(self)
        row2.pack(fill="x", **pad)
        self._c_size = _SizeCombo(row2, "C Chip Size:", _C_CHIP_SIZES, "auto (C_total ÷ 2)")
        self._c_size.pack(side="left")

        self._run_btn = ttk.Button(self, text="Verify Roundtrip", command=self._run)
        self._run_btn.pack(**pad)
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

        def work():
            try:
                original    = neo_path.read_bytes()
                original_rs = parse_neo(original)
                c_chip_size = _c_chip_size_from_str(self._c_size.value_str, len(original_rs.c))
                self._log.append(f"Reading: {neo_path}")
                self._log.append("Step 1: Extracting ROM data…")
                zip_data = extract_romset_to_zip(original_rs, name_prefix=prefix,
                                                 fmt=fmt, c_chip_size=c_chip_size)
                self._log.append("Step 2: Repacking to .neo…")
                meta = original_rs.meta
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
                    tf.write(zip_data)
                    tmp_zip = Path(tf.name)
                try:
                    rebuilt = mame_zip_to_neo(tmp_zip, meta)
                finally:
                    tmp_zip.unlink(missing_ok=True)
                self._log.append("Step 3: Comparing ROM data regions…")
                result = verify_roundtrip(original, rebuilt)
                self._log.append("")
                self._log.append("✅ PASS — extraction is lossless." if result.ok
                                 else "❌ FAIL — ROM data mismatch!")
                self._log.append(f"  Original ROM MD5 : {result.original_rom_md5}")
                self._log.append(f"  Rebuilt  ROM MD5 : {result.rebuilt_rom_md5}")
                self._log.append(f"  File size match  : {result.file_size_match}")
                self._log.append(f"  Details          : {result.details}")
            except Exception as e:
                self._log.append(f"❌ Error: {e}")
            finally:
                self.after(0, self._finish_run)

        _run_in_thread(work)

    def _finish_run(self):
        self._is_running = False
        self._run_btn.config(state="normal")


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
        ttk.Button(self, text="Show Info", command=self._run).pack(**pad)
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
            self._log.append(f"❌ Invalid .neo file: {e}")
        except OSError as e:
            self._log.append(f"❌ Could not read file: {e}")
        except Exception as e:
            self._log.append(f"❌ Unexpected error: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = NeoConvApp()
    app.mainloop()


if __name__ == "__main__":
    main()
