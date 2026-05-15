# neoconv

> A preservation-focused utility to **convert** between **TerraOnion `.neo` containers** and **MAME / Darksoft Neo Geo ROM sets**, and to **edit `.neo` header metadata** (name, manufacturer, year, genre, NGH, screenshot index) **without repacking** ROM data.

`neoconv` **packs** directories or MAME ZIPs into `.neo`, **extracts** `.neo` back to ROM files, and **rewrites** `.neo` headers when you only need metadata changes. It handles C-ROM byte-interleaving, **P-ROM half-swap** (default: **auto-detect** from the M68000 vector table, with `yes` / `no` overrides), V-ROM chunking, and TerraOnion header fields. It is designed for commercial dumps, hacks, CD conversions, and homebrew.

---

## Why neoconv?

Most Neo Geo tools only handle one direction or break on non-standard sets. `neoconv` focuses on correct **conversion** and transparent **metadata edits** for `.neo` files.

| Property | Description |
|----------|-------------|
| **Reliable** | Deterministic conversions with automated tests for core roundtrip behaviour |
| **Universal** | Handles commercial sets, hacks, CD conversions, and homebrew |
| **Transparent** | C interleaving, P-ROM swap (auto or manual), and V chunking are explicit and documented |
| **Configurable** | Selectable C chip size per title (2 MB default, 4 MB for some games) |
| **Dual interface** | CLI and GUI expose the same core workflows |

---

## Feature parity: CLI and GUI

Both interfaces support the same core workflows:

| Workflow | CLI | GUI |
|----------|-----|-----|
| Extract `.neo` to MAME / Darksoft files | ✅ | ✅ |
| Pack MAME ZIP or directory to `.neo` | ✅ | ✅ |
| Edit `.neo` header metadata (no repack) | ✅ | ✅ |
| View `.neo` metadata and region sizes | ✅ | ✅ |
| P-ROM bank swap (auto-detect + manual override) | ✅ | ✅ |
| Inspect P-ROM and report swap recommendation | ✅ | — |
| Diagnostic mode for unrecognized files | ✅ | ✅ |

---

## Requirements

- Python **3.9+**
- **GUI only**: Tk (`tkinter`) — usually bundled with Python; on Linux install `python3-tk` via your package manager
- **GUI drag & drop**: `tkinterdnd2` (optional, see [GUI usage](#gui-usage))

CLI-only use remains pure Python stdlib (plus optional `pytest` for development tests).

---

## OS-specific environment setup

### Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv python3-tk
```

### Fedora

```bash
sudo dnf install -y python3 python3-pip python3-tkinter
```

### Arch Linux

```bash
sudo pacman -S --needed python python-pip tk
```

### macOS

- Install Python 3.9+ (python.org installer or Homebrew).
- If `tkinter` is missing with Homebrew Python, install Tk:

```bash
brew install python tcl-tk
```

### Windows

- Install Python 3.9+ from python.org.
- Keep the default Tcl/Tk component enabled in the installer.

---

## Installation

### Prebuilt GUI binaries (Windows, macOS, Linux)

Download the latest binary from the [Releases](https://github.com/d4NY0H/neoconv/releases) page — no Python installation required.

| Platform | File |
|----------|------|
| Windows | `neoconv-gui-x.y.z-windows.exe` — run directly |
| macOS | `neoconv-gui-x.y.z-macos.zip` — unzip, then double-click `neoconv-gui.app` (first launch: right-click → Open to bypass Gatekeeper) |
| Linux | `neoconv-gui-x.y.z-linux` — `chmod +x`, then run |

### Installation (project)

```bash
git clone https://github.com/d4NY0H/neoconv
cd neoconv
python3 -m pip install .
```

For development (editable install + test runner):

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest tests/ -v
```

---

## Quick verification (environment health check)

```bash
python3 -m neoconv --version
python3 -m neoconv --help
python3 -c "import tkinter as tk; print('tkinter', tk.TkVersion)"
python3 -c "import tkinterdnd2; print('tkinterdnd2 OK')"
```

- If the `tkinter` check fails, the CLI still works, but the GUI needs a Python build with Tk.
- If the `tkinterdnd2` check fails, the GUI works normally — only drag & drop onto file path fields is disabled.

---

## GUI usage

Start GUI:

```bash
neoconv-gui
# or
python3 -m neoconv.gui
```

Each **file path** row supports **drag & drop** onto its text entry field (next to "Browse…"): drop a `.neo`, a MAME ZIP, or a folder where the UI expects a directory. Drag & drop requires `tkinterdnd2` — install it once if needed:

```bash
pip install tkinterdnd2>=0.4.0
```

Without it the GUI works normally; only drag & drop is disabled.

Tabs:

| Tab | Description |
|-----|-------------|
| **Pack** | Build `.neo` from ZIP/folder with metadata; P-ROM swap mode selectable via radio (`auto` / `yes` / `no`) |
| **Extract** | Convert `.neo` to MAME or Darksoft ZIP/directory, including C chip size selection |
| **Edit** | Load header fields from a `.neo`, adjust metadata, write back (optional separate output path) |
| **Info** | Inspect metadata and ROM region sizes from a `.neo` file |

---

## CLI usage

```bash
neoconv <command> [options]
# or
python3 -m neoconv <command> [options]
```

### `extract` - `.neo` -> ROM files

```bash
# MAME ZIP
neoconv extract input.neo --prefix game --format mame --out game_mame.zip

# Darksoft ZIP
neoconv extract input.neo --prefix game --format darksoft --out game_darksoft.zip

# Output directory
neoconv extract input.neo --prefix game --format mame --out-dir ./roms/

# Explicit C chip size (example: 4 MB chips)
neoconv extract input.neo --prefix game --c-chip-size 4194304 --out game_customc.zip
```

| Option | Default | Description |
|--------|---------|-------------|
| `--prefix`, `-p` | *(input stem)* | Filename prefix for output files |
| `--format`, `-f` | `mame` | Output format: `mame` (`.bin`) or `darksoft` (`.rom`) |
| `--out`, `-o` | *(auto)* | Output ZIP path |
| `--out-dir`, `-d` | — | Extract to directory instead of ZIP |
| `--c-chip-size` | `0` (auto) | C chip size in bytes; `0` = auto (derives `C_total / 2`). Use `2097152` (2 MB) for most games, `4194304` (4 MB) for games with larger chips (e.g. Neo Turf Masters) |

### `pack` - ROM files -> `.neo`

```bash
# From MAME ZIP
neoconv pack input.zip \
  --name "Example Game" \
  --manufacturer "Example Studio" \
  --year 1995 \
  --genre Sports \
  --ngh 100 \
  --out output.neo

# From directory
neoconv pack ./roms/ \
  --name "My Game" \
  --manufacturer "Example Studio" \
  --year 1994 \
  --genre Fighting \
  --ngh 149 \
  --out mygame.neo

# With P-ROM bank swap auto-detect (default — recommended)
neoconv pack input.zip --name "Example Game" --ngh 100 --out output_auto.neo

# Force swap (explicit override)
neoconv pack input.zip --name "Example Game" --ngh 100 --swap-p yes --out output_swap_yes.neo

# Never swap (opt out of auto-detect)
neoconv pack input.zip --name "Example Game" --ngh 100 --swap-p no --out output_swap_no.neo

# Diagnostic output for unrecognized files
neoconv pack ./roms/ --name "Test" --diagnostic --out test.neo
```

| Option | Default | Description |
|--------|---------|-------------|
| `--name`, `-n` | `Unknown` | Game name stored in `.neo` header |
| `--manufacturer`, `-m` | `Unknown` | Manufacturer string |
| `--year`, `-y` | `0` | Release year |
| `--genre`, `-g` | `Other` | Genre name or genre ID |
| `--ngh` | `0` | NGH number (decimal integer) |
| `--screenshot` | `0` | TerraOnion screenshot index |
| `--out`, `-o` | *(input stem + `.neo`)* | Output `.neo` path |
| `--swap-p` | `auto` | P-ROM half-swap mode: `auto` (heuristic, default), `yes` (always), `no` (never) |
| `--diagnostic` | off | Warn on unrecognized filenames |

Available genres: `Other`, `Action`, `BeatEmUp`, `Sports`, `Driving`, `Platformer`, `Mahjong`, `Shooter`, `Quiz`, `Fighting`, `Puzzle`

### `edit` - change `.neo` header metadata (no repack)

Updates TerraOnion header fields **without** touching P/S/M/V/C payload. At least one of the metadata flags below is required.

```bash
# Correct title in place (overwrites the file atomically)
neoconv edit game.neo --name "Windjammers"

# Multiple fields; write a new file (input unchanged)
neoconv edit game.neo --genre Fighting --year 1994 --ngh 65 --out game_fixed.neo
```

| Option | Default | Description |
|--------|---------|-------------|
| `--out`, `-o` | *(overwrite input)* | Output `.neo` path |
| `--name`, `-n` | — | Game name |
| `--manufacturer`, `-m` | — | Manufacturer |
| `--year`, `-y` | — | Release year |
| `--genre`, `-g` | — | Genre name or numeric id (same set as `pack`) |
| `--ngh` | — | NGH number |
| `--screenshot` | — | TerraOnion screenshot index |

### `detect-swap` - inspect P-ROM swap requirement

```bash
neoconv detect-swap input.zip
neoconv detect-swap input-p1.bin
```

Inspects the M68000 vector table in both 1 MB halves of a 2 MB P-ROM and reports whether `--swap-p yes` is needed. Works with raw P-ROM files or MAME ZIPs.

Example output:

```
Inspecting P-ROM from ZIP: input.zip  (2,097,152 bytes)
  Result  : --swap-p yes  ← required
  Reason  : Second half has valid vectors (SP=0x0010F300, Reset=0x00C00402) — swap required.
```

### `info` - display `.neo` metadata

Prints header metadata, ROM region sizes, and **MD5 per region** (P, S, M, V, C) when a full `.neo` is loaded — useful to compare two files that differ only in the header.

```bash
neoconv info input.neo
```

---

## Technical details

### ROM role detection (MAME naming)

The table below matches the primary rules in `_name_to_role`: extension (e.g. `.p1`, `.c1`) **or** basename suffix patterns such as `-p1.bin`, `_m1.bin`, or a stem ending in `-v3` / `_c2` (same keys as MAME-style `p1`…`c8`).

| Role | Recognized patterns |
|------|---------------------|
| **P ROM** | `.p1`, `.p2`, `-p1.bin`, `_p1.bin`, `-p2.bin` |
| **S ROM** | `.s1`, `-s1.bin`, `_s1.bin` |
| **M ROM** | `.m1`, `-m1.bin`, `_m1.bin` |
| **V ROMs** | `.v1`-`.v8`, `-v1.bin`-`-v8.bin`, `_v1.bin`-`_v8.bin` |
| **C ROMs** | `.c1`-`.c8`, `-c1.bin`-`-c8.bin`, `_c1.bin`-`_c8.bin` |

Not every MAME filename variant is mapped here (for example some `*-c1a.bin`-style names are **not** assigned a **C** role by this table). Those files may still be listed in the archive and participate in **other** logic (see below).

**Synthetic S-ROM (no physical `s1`):** Some MAME parents (e.g. PVC / encrypted boards) ship without a separate text-layer `s1`; the driver uses a zero-filled "fixed" region. If **P** and **M** are present, there is **no** `s1`, but filenames look like a Neo Geo **C1** sprite set, `neoconv` may **inject** a zero-filled `S` region and emit a `UserWarning`. The fill size is chosen from filename heuristics aligned with `neogeo.xml`: basenames starting with `kf10-` (KOF2002 bootleg) → 256 KiB; ``-c1r.`` / ``-c2r.`` sprite chip names (e.g. `269-c1r.c1`) → 512 KiB; certain **three-digit MAME set IDs** in `NNN-p1.` / `NNN-m1.` / `NNN-c1….c1` patterns (see `_SYNTH_S_MAME_512K_SET_IDS` in `neoconv/core/constants.py`) → 512 KiB; otherwise → 128 KiB. This uses **digits in ROM filenames**.

Standard BIOS files (`000-lo.lo`, `sfix.sfix`, etc.) are ignored. Unknown files are also ignored unless `--diagnostic` is enabled.

### C-ROM interleaving

C-ROM graphics are byte-interleaved in `.neo`:

- even bytes -> odd chips (`c1`, `c3`, ...)
- odd bytes -> even chips (`c2`, `c4`, ...)

C chips always come in pairs. Interleaved bank size is `chip_size * 2`.

### P-ROM bank swap (`--swap-p`)

Some Neo Geo titles and hacks store their 2 MB P-ROM with the two 1 MB halves in reversed order relative to what TerraOnion NeoSD / MiSTer expect.

`neoconv` detects this automatically by inspecting the M68000 exception-vector table (initial Stack Pointer + Reset PC) in both halves. The half carrying valid values — SP in Work RAM (`0x100000–0x10FFFF`), Reset PC in ROM or BIOS (`0x000100–0x1FFFFF` or `0xC00000–0xC7FFFF`) — determines whether a swap is applied.

| Mode | Behaviour |
|------|-----------|
| `auto` (default) | Detect from vector table; prints a diagnostic line |
| `yes` | Always swap — for titles where auto-detect is ambiguous |
| `no` | Never swap — to opt out explicitly |

Use `neoconv detect-swap <zip>` to inspect a dump without packing it.

### V-ROM chunking

V-ROM data is contiguous in `.neo` and split to files on extract. Default chunk size is 2 MB (`v1`, `v2`, ...).

### V1 / V2 header fields (read vs write)

Some `.neo` files split the **total V ROM payload** across the **V1** and **V2** size fields at offsets `0x010` and `0x014`. **neoconv** reads both and merges the bytes in memory. On **output** (`pack`, `build_neo`, `replace_neo_metadata`, `extract` after repack), the header is **normalised**: all V length is stored in **V1** and **V2 is set to 0** (TerraOnion-style layout). Loading or rewriting such a file may emit a **`UserWarning`** so this header normalisation is visible.

### `.neo` container format

```text
Offset 0x000   Magic         b'NEO\x01'  (4 bytes)
Offset 0x004   P ROM size    uint32 LE
Offset 0x008   S ROM size    uint32 LE
Offset 0x00C   M ROM size    uint32 LE
Offset 0x010   V1 ROM size   uint32 LE   (all V data merged here on write; read accepts split V1/V2)
Offset 0x014   V2 ROM size   uint32 LE   (0 when written by neoconv; non-zero allowed on read)
Offset 0x018   C ROM size    uint32 LE   (total, interleaved)
Offset 0x01C   Year          uint16 LE
Offset 0x01E   Genre         uint16 LE
Offset 0x020   Screenshot    uint32 LE
Offset 0x024   NGH number    uint32 LE
Offset 0x02C   Name          33 bytes, null-terminated, latin-1
Offset 0x04D   Manufacturer  17 bytes, null-terminated, latin-1
Offset 0x200-0xFFF  (padding, header is always 4096 bytes)
Data:  P, S, M, V, C   (sequentially, sizes from header)
```

### About CRC mismatches

For hacks and CD conversions, MAME `verifyroms` may report CRC mismatches because data differs from known dumps. This is expected when the dump is intentionally different from MAME's reference set.

### Out of scope

- Caching MD5 checksums inside `NeoMeta.format_info()` for repeated calls on large ROM sets: negligible benefit for typical CLI or GUI use, so it is not planned.

### Planned

- **`--c-chip-size` improvement** (`extract` command and GUI): the current auto mode derives chip size as `c_total / 2`, which is correct for games with exactly one C chip pair. Games with more than two chips (e.g. Neo Turf Masters with 4 MB chips) require `--c-chip-size` to be set manually. A smarter default may be added in a future release.
- **`--v-bank-size` option** (`extract` command and GUI): V-ROM is currently always split into fixed 2 MB chunks (`V_BANK_SIZE`). Games with non-standard V chip sizes (e.g. 512 KB, 4 MB, 16 MB) require manual renaming after extraction. A `--v-bank-size` flag analogous to `--c-chip-size` is planned.
- **Internal API cleanup**: helper functions `_apply_swap_p`, `_check_m68k_vectors`, `_interleave_c_chips`, `_name_to_role`, and `_roles_to_romset` are currently exported with a leading underscore despite being part of the semi-public API (used by tests and the GUI). The underscores will be removed in a future release.

---

## License

MIT - see [LICENSE](LICENSE).
