"""
neoconv GUI
~~~~~~~~~~~
A simple Tkinter GUI for neoconv.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from pathlib import Path

from .core import (
    GENRES,
    GENRE_BY_NAME,
    NeoMeta,
    extract_neo_to_zip,
    mame_zip_to_neo,
    mame_dir_to_neo,
    parse_neo,
    verify_roundtrip,
)
from . import __version__

import tempfile
import zipfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_in_thread(fn, *args):
    t = threading.Thread(target=fn, args=args, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class NeoConvApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"neoconv {__version__}")
        self.resizable(False, False)
        self._build_ui()

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._tab_extract = ExtractTab(nb)
        self._tab_pack    = PackTab(nb)
        self._tab_verify  = VerifyTab(nb)
        self._tab_info    = InfoTab(nb)

        nb.add(self._tab_extract, text="Extract (.neo → ROM ZIP)")
        nb.add(self._tab_pack,    text="Pack (ROM ZIP → .neo)")
        nb.add(self._tab_verify,  text="Verify (Roundtrip)")
        nb.add(self._tab_info,    text="Info (.neo)")


# ---------------------------------------------------------------------------
# Shared widgets
# ---------------------------------------------------------------------------

class _FileRow(ttk.Frame):
    """A label + entry + browse button row."""

    def __init__(self, parent, label: str, mode: str = "open", filetypes=None, **kw):
        super().__init__(parent, **kw)
        self._mode = mode
        self._ft   = filetypes or []
        ttk.Label(self, text=label, width=14, anchor="w").pack(side="left")
        self.var = tk.StringVar()
        ttk.Entry(self, textvariable=self.var, width=42).pack(side="left", padx=4)
        ttk.Button(self, text="Browse…", command=self._browse).pack(side="left")

    def _browse(self):
        if self._mode == "open":
            p = filedialog.askopenfilename(filetypes=self._ft)
        elif self._mode == "opendir":
            p = filedialog.askdirectory()
        else:
            p = filedialog.asksaveasfilename(filetypes=self._ft)
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
        self.config(state="normal")
        self.delete("1.0", "end")
        self.config(state="disabled")

    def append(self, text: str):
        self.config(state="normal")
        self.insert("end", text + "\n")
        self.see("end")
        self.config(state="disabled")


# ---------------------------------------------------------------------------
# Extract tab
# ---------------------------------------------------------------------------

class ExtractTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 4}

        self._neo = _FileRow(
            self, "Input .neo:", filetypes=[("NEO files", "*.neo"), ("All", "*.*")]
        )
        self._neo.pack(fill="x", **pad)

        self._out = _FileRow(
            self, "Output ZIP:", mode="save",
            filetypes=[("ZIP files", "*.zip"), ("All", "*.*")]
        )
        self._out.pack(fill="x", **pad)

        row = ttk.Frame(self)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Prefix:", width=14, anchor="w").pack(side="left")
        self._prefix = tk.StringVar()
        ttk.Entry(row, textvariable=self._prefix, width=16).pack(side="left", padx=4)

        ttk.Label(row, text="Format:", width=8).pack(side="left", padx=(16, 0))
        self._fmt = tk.StringVar(value="mame")
        ttk.Radiobutton(row, text="MAME (.bin)", variable=self._fmt, value="mame").pack(side="left")
        ttk.Radiobutton(row, text="Darksoft (.rom)", variable=self._fmt, value="darksoft").pack(side="left")

        ttk.Button(self, text="Extract", command=self._run).pack(**pad)

        self._log = _LogBox(self)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

    def _run(self):
        neo_path = Path(self._neo.value)
        out_path = Path(self._out.value) if self._out.value else None
        prefix   = self._prefix.get().strip()
        fmt      = self._fmt.get()

        if not neo_path.exists():
            messagebox.showerror("Error", f"File not found: {neo_path}")
            return

        self._log.clear()

        def work():
            try:
                neo_data = neo_path.read_bytes()
                pfx = prefix or neo_path.stem
                self._log.append(f"Reading: {neo_path}")

                zip_data = extract_neo_to_zip(neo_data, name_prefix=pfx, fmt=fmt)

                dest = out_path or neo_path.with_suffix(
                    f".{'mame' if fmt == 'mame' else 'darksoft'}.zip"
                )
                dest.write_bytes(zip_data)
                self._log.append(f"Written: {dest}  ({len(zip_data)/1024/1024:.2f} MB)")

                with zipfile.ZipFile(dest) as zf:
                    for info in zf.infolist():
                        self._log.append(f"  {info.filename:<28} {info.file_size:>10,} bytes")

                self._log.append("✅ Done.")
            except Exception as e:
                self._log.append(f"❌ Error: {e}")

        _run_in_thread(work)


# ---------------------------------------------------------------------------
# Pack tab
# ---------------------------------------------------------------------------

class PackTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 3}

        self._inp = _FileRow(
            self, "Input ZIP/Dir:", filetypes=[("ZIP files", "*.zip"), ("All", "*.*")]
        )
        self._inp.pack(fill="x", **pad)
        ttk.Button(
            self, text="…or pick directory",
            command=lambda: self._inp.var.set(filedialog.askdirectory() or self._inp.value)
        ).pack(anchor="w", padx=80)

        self._out = _FileRow(
            self, "Output .neo:", mode="save",
            filetypes=[("NEO files", "*.neo"), ("All", "*.*")]
        )
        self._out.pack(fill="x", **pad)

        # Metadata fields
        meta_frame = ttk.LabelFrame(self, text="Metadata")
        meta_frame.pack(fill="x", padx=8, pady=4)

        fields = [
            ("Name:",         "name",  "Unknown"),
            ("Manufacturer:", "mfr",   "Unknown"),
            ("Year:",         "year",  "0"),
            ("NGH #:",        "ngh",   "0"),
        ]
        self._vars: dict[str, tk.StringVar] = {}
        for row_i, (lbl, key, default) in enumerate(fields):
            ttk.Label(meta_frame, text=lbl, width=14, anchor="w").grid(
                row=row_i, column=0, sticky="w", padx=4, pady=2
            )
            v = tk.StringVar(value=default)
            self._vars[key] = v
            ttk.Entry(meta_frame, textvariable=v, width=30).grid(
                row=row_i, column=1, sticky="w", padx=4
            )

        ttk.Label(meta_frame, text="Genre:", width=14, anchor="w").grid(
            row=len(fields), column=0, sticky="w", padx=4, pady=2
        )
        self._genre = tk.StringVar(value="Other")
        genre_combo = ttk.Combobox(
            meta_frame, textvariable=self._genre,
            values=list(GENRES.values()), state="readonly", width=16
        )
        genre_combo.grid(row=len(fields), column=1, sticky="w", padx=4)

        ttk.Button(self, text="Pack → .neo", command=self._run).pack(**pad)

        self._log = _LogBox(self)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

    def _run(self):
        src = Path(self._inp.value)
        out = Path(self._out.value) if self._out.value else None

        if not src.exists():
            messagebox.showerror("Error", f"Not found: {src}")
            return

        try:
            year = int(self._vars["year"].get())
            ngh  = int(self._vars["ngh"].get())
        except ValueError:
            messagebox.showerror("Error", "Year and NGH must be integers.")
            return

        genre_name = self._genre.get().lower()
        genre_id   = GENRE_BY_NAME.get(genre_name, 0)

        meta = NeoMeta(
            name=self._vars["name"].get(),
            manufacturer=self._vars["mfr"].get(),
            year=year,
            genre=genre_id,
            ngh=ngh,
        )

        self._log.clear()

        def work():
            try:
                self._log.append(f"Packing: {src}")
                if src.is_dir():
                    neo_data = mame_dir_to_neo(src, meta)
                else:
                    neo_data = mame_zip_to_neo(src, meta)

                dest = out or src.with_suffix(".neo")
                dest.write_bytes(neo_data)
                self._log.append(f"Written: {dest}  ({len(neo_data)/1024/1024:.2f} MB)")
                self._log.append("✅ Done.")
            except Exception as e:
                self._log.append(f"❌ Error: {e}")

        _run_in_thread(work)


# ---------------------------------------------------------------------------
# Verify tab
# ---------------------------------------------------------------------------

class VerifyTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 4}

        self._neo = _FileRow(
            self, "Input .neo:", filetypes=[("NEO files", "*.neo"), ("All", "*.*")]
        )
        self._neo.pack(fill="x", **pad)

        row = ttk.Frame(self)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Prefix:", width=14, anchor="w").pack(side="left")
        self._prefix = tk.StringVar()
        ttk.Entry(row, textvariable=self._prefix, width=16).pack(side="left", padx=4)

        ttk.Button(self, text="Verify Roundtrip", command=self._run).pack(**pad)

        self._log = _LogBox(self, height=12)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

    def _run(self):
        neo_path = Path(self._neo.value)
        if not neo_path.exists():
            messagebox.showerror("Error", f"File not found: {neo_path}")
            return

        prefix = self._prefix.get().strip() or neo_path.stem
        self._log.clear()

        def work():
            try:
                original = neo_path.read_bytes()
                self._log.append(f"Reading: {neo_path}")
                self._log.append("Step 1: Extracting ROM data…")

                zip_data = extract_neo_to_zip(original, name_prefix=prefix, fmt="mame")

                self._log.append("Step 2: Repacking to .neo…")
                meta = parse_neo(original).meta
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
                    tf.write(zip_data)
                    tmp_zip = Path(tf.name)

                from .core import mame_zip_to_neo
                rebuilt = mame_zip_to_neo(tmp_zip, meta)
                tmp_zip.unlink()

                self._log.append("Step 3: Comparing ROM data regions…")
                result = verify_roundtrip(original, rebuilt)

                self._log.append("")
                if result.ok:
                    self._log.append("✅ PASS — extraction is lossless.")
                else:
                    self._log.append("❌ FAIL — ROM data mismatch!")
                self._log.append(f"  Original ROM MD5 : {result.original_rom_md5}")
                self._log.append(f"  Rebuilt  ROM MD5 : {result.rebuilt_rom_md5}")
                self._log.append(f"  File size match  : {result.file_size_match}")
                self._log.append(f"  Details          : {result.details}")

            except Exception as e:
                self._log.append(f"❌ Error: {e}")

        _run_in_thread(work)


# ---------------------------------------------------------------------------
# Info tab
# ---------------------------------------------------------------------------

class InfoTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 4}

        self._neo = _FileRow(
            self, "Input .neo:", filetypes=[("NEO files", "*.neo"), ("All", "*.*")]
        )
        self._neo.pack(fill="x", **pad)
        ttk.Button(self, text="Show Info", command=self._run).pack(**pad)
        self._log = _LogBox(self, height=14)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

    def _run(self):
        neo_path = Path(self._neo.value)
        if not neo_path.exists():
            messagebox.showerror("Error", f"File not found: {neo_path}")
            return

        self._log.clear()
        try:
            from .core import parse_neo
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
