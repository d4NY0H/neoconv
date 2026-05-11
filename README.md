# neoconv

> A preservation-focused utility for converting between **TerraOnion `.neo` containers** and **MAME / Darksoft Neo Geo ROM sets** with bit-perfect verification.

`neoconv` handles C-ROM byte-interleaving, **P-ROM half-swap** (default: **auto-detect** from the M68000 vector table, with `yes` / `no` overrides), V-ROM chunking, metadata, and lossless roundtrip verification. It is designed for commercial dumps, hacks, CD conversions, and homebrew.

---

## Why neoconv?

Most Neo Geo conversion tools are one-way, outdated, or fragile with non-standard sets. `neoconv` focuses on correctness and transparency.

| Property | Description |
|----------|-------------|
| **Reliable** | Integrated `verify` checks your exact ROM data, not a global CRC database |
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
| Bit-perfect roundtrip verify | ✅ | ✅ |
| View `.neo` metadata and region sizes | ✅ | ✅ |
| P-ROM bank swap (auto-detect + manual override) | ✅ | ✅ |
| Inspect P-ROM and report swap recommendation | ✅ | — |
| Diagnostic mode for unrecognized files | ✅ | ✅ |

---

## Requirements

- Python **3.9+**
- For **GUI only**: Tk (`tkinter`)

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

## Installation (project)

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
```

- If the last command fails, CLI still works, but GUI prerequisites are missing.

---

## GUI usage

Start GUI:

```bash
neoconv-gui
# or
python3 -m neoconv.gui
```

Tabs:

| Tab | Description |
|-----|-------------|
| **Extract** | Convert `.neo` to MAME or Darksoft ZIP/directory, including C chip size selection |
| **Pack** | Build `.neo` from ZIP/folder with metadata, optional P swap, and diagnostics |
| **Verify** | Run full roundtrip verification with selectable format and C chip size |
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
neoconv extract game.neo --prefix zin --format mame --out zintrckbp.zip

# Darksoft ZIP
neoconv extract game.neo --prefix zin --format darksoft --out zin_darksoft.zip

# Output directory
neoconv extract game.neo --prefix zin --format mame --out-dir ./roms/

# Explicit C chip size (example: 4 MB chips)
neoconv extract turfmast.neo --prefix 200 --c-chip-size 4194304 --out turfmast.zip
```

| Option | Default | Description |
|--------|---------|-------------|
| `--prefix`, `-p` | *(input stem)* | Filename prefix for output files |
| `--format`, `-f` | `mame` | Output format: `mame` (`.bin`) or `darksoft` (`.rom`) |
| `--out`, `-o` | *(auto)* | Output ZIP path |
| `--out-dir`, `-d` | — | Extract to directory instead of ZIP |
| `--c-chip-size` | `0` (auto) | C chip size in bytes; `0` auto-derives from total C region |

### `pack` - ROM files -> `.neo`

```bash
# From MAME ZIP
neoconv pack zintrckbp.zip \
  --name "Zintrick CD Conversion" \
  --manufacturer "ADK" \
  --year 1996 \
  --genre Sports \
  --ngh 224 \
  --out zintrick.neo

# From directory
neoconv pack ./roms/ \
  --name "My Game" \
  --manufacturer "SNK" \
  --year 1994 \
  --genre Fighting \
  --ngh 149 \
  --out mygame.neo

# With P-ROM bank swap auto-detect (default — recommended)
neoconv pack kof94.zip --name "KOF 94" --ngh 55 --out kof94.neo

# Force swap (explicit override)
neoconv pack kof94.zip --name "KOF 94" --ngh 55 --swap-p yes --out kof94.neo

# Never swap (opt out of auto-detect)
neoconv pack mygame.zip --name "My Game" --ngh 200 --swap-p no --out mygame.neo

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

### `verify` - lossless roundtrip check

```bash
neoconv verify game.neo --prefix zin
# Exit code: 0 = PASS, 1 = FAIL
```

| Option | Default | Description |
|--------|---------|-------------|
| `--prefix`, `-p` | *(input stem)* | Prefix for intermediate extraction |
| `--format`, `-f` | `mame` | Intermediate format: `mame` or `darksoft` |

### `detect-swap` - inspect P-ROM swap requirement

```bash
neoconv detect-swap kof94te.zip
neoconv detect-swap turfmast.zip
```

Inspects the M68000 vector table in both 1 MB halves of a 2 MB P-ROM and reports whether `--swap-p yes` is needed. Works with raw P-ROM files or MAME ZIPs.

Example output:

```
Inspecting P-ROM from ZIP: kof94te.zip  (2,097,152 bytes)
  Result  : --swap-p yes  ← required
  Reason  : Second half has valid vectors (SP=0x0010F300, Reset=0x00C00402) — swap required.
```

### `info` - display `.neo` metadata

```bash
neoconv info game.neo
```

---

## Bit-perfect guarantee (`verify`)

`verify` proves data integrity with a full roundtrip:

1. Extract ROM regions from `.neo`.
2. Repack regions to a new `.neo`.
3. Compare ROM data byte-by-byte.

The metadata header is intentionally excluded; only ROM payload integrity is compared.

Example output:

```bash
$ neoconv verify zintrick.neo --prefix zin
Verifying: zintrick.neo
Step 1: Extract -> mame ZIP
Step 2: Repack ZIP -> .neo
Step 3: Compare ROM data regions

✅ PASS — extraction is lossless.
  Original ROM MD5 : aed6010ef6d15d2dba1a4422e70fc822
  Rebuilt  ROM MD5 : aed6010ef6d15d2dba1a4422e70fc822
```

---

## Technical details

### ROM role detection (MAME naming)

`neoconv` identifies ROM roles by extension and common name patterns inside ZIPs/directories:

| Role | Recognized patterns |
|------|---------------------|
| **P ROM** | `.p1`, `.p2`, `-p1.bin`, `_p1.bin`, `-p2.bin` |
| **S ROM** | `.s1`, `-s1.bin`, `_s1.bin` |
| **M ROM** | `.m1`, `-m1.bin`, `_m1.bin` |
| **V ROMs** | `.v1`-`.v8`, `-v1.bin`-`-v8.bin`, `_v1.bin`-`_v8.bin` |
| **C ROMs** | `.c1`-`.c8`, `-c1.bin`-`-c8.bin`, `_c1.bin`-`_c8.bin` |

Standard BIOS files (`000-lo.lo`, `sfix.sfix`, etc.) are ignored. Unknown files are also ignored unless `--diagnostic` is enabled.

### C-ROM interleaving

C-ROM graphics are byte-interleaved in `.neo`:

- even bytes -> odd chips (`c1`, `c3`, ...)
- odd bytes -> even chips (`c2`, `c4`, ...)

C chips always come in pairs. Interleaved bank size is `chip_size * 2`.

### P-ROM bank swap (`--swap-p`)

Some early SNK titles (KOF94, Neo Turf Masters, and their hacks) store their 2 MB P-ROM with the two 1 MB halves in reversed order relative to what TerraOnion NeoSD / MiSTer expect.

`neoconv` detects this automatically by inspecting the M68000 exception-vector table (initial Stack Pointer + Reset PC) in both halves. The half carrying valid values — SP in Work RAM (`0x100000–0x10FFFF`), Reset PC in ROM or BIOS (`0x000100–0x1FFFFF` or `0xC00000–0xC7FFFF`) — determines whether a swap is applied.

| Mode | Behaviour |
|------|-----------|
| `auto` (default) | Detect from vector table; prints a diagnostic line |
| `yes` | Always swap — for titles where auto-detect is ambiguous |
| `no` | Never swap — to opt out explicitly |

Use `neoconv detect-swap <zip>` to inspect a dump without packing it.

### V-ROM chunking

V-ROM data is contiguous in `.neo` and split to files on extract. Default chunk size is 2 MB (`v1`, `v2`, ...).

### `.neo` container format

```text
Offset 0x000   Magic         b'NEO\x01'  (4 bytes)
Offset 0x004   P ROM size    uint32 LE
Offset 0x008   S ROM size    uint32 LE
Offset 0x00C   M ROM size    uint32 LE
Offset 0x010   V1 ROM size   uint32 LE   (all V data merged here)
Offset 0x014   V2 ROM size   uint32 LE   (always 0 in neoconv output)
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

For hacks and CD conversions, MAME `verifyroms` may report CRC mismatches because data differs from known dumps. This is expected. Use `neoconv verify` for source-vs-output integrity in your own pipeline.

---

## License

MIT - see [LICENSE](LICENSE).
