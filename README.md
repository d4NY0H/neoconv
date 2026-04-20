# neoconv

> A preservation-focused utility for converting between **TerraOnion `.neo` containers** and **MAME / Darksoft Neo Geo ROM sets** — with bit-perfect integrity guaranteed.

`neoconv` handles the complete conversion pipeline: C-ROM byte-interleaving, P-ROM bank swapping, V-ROM chunking, full metadata control, and an integrated lossless roundtrip verification. It works with commercial releases, ROM hacks, CD conversions, and homebrew — no CRC database required.

---

## Why neoconv?

Most Neo Geo conversion tools are one-way, poorly maintained, or fail silently on non-standard ROM sets. `neoconv` was built to be different:

| Property | Description |
|----------|-------------|
| **Reliable** | Integrated Verify proves bit-perfect accuracy for your specific ROM, not just known sets |
| **Universal** | Works with any Neo Geo ROM: commercial releases, ROM hacks, CD conversions, homebrew |
| **Transparent** | Handles C-ROM byte-interleaving, P-ROM bank swapping, and V-ROM chunking automatically |
| **Configurable** | C chip size selectable per game (2 MB default, 4 MB for titles like Neo Turf Masters) |
| **Lightweight** | Pure Python stdlib — no external dependencies, no CRC database |
| **Dual interface** | Full-featured GUI and CLI with identical feature sets |

---

## Features

- **Extract** — Convert `.neo` files to MAME-compatible (`.bin`) or Darksoft (`.rom`) ZIP archives or directories.
- **Pack** — Build `.neo` files from MAME ZIP archives or directories, with full metadata control.
- **Verify** — Automated lossless roundtrip check to guarantee bit-perfect data integrity.
- **Info** — Display header metadata and ROM region sizes from any `.neo` file.
- **P-ROM Bank Swap** — Optional swap of the two 1 MB halves for early SNK titles with P-ROM banking.
- **Diagnostic Mode** — Logs unrecognized files during pack to help diagnose naming issues.

---

## Installation

**Requirements:** Python 3.9 or newer. No additional dependencies.

```bash
git clone https://github.com/d4NY0H/neoconv
cd neoconv
pip install .
```

For development (includes test runner):

```bash
pip install ".[dev]"
python -m pytest tests/ -v
```

---

## Graphical User Interface

```bash
neoconv-gui
```

The GUI provides full access to all features through a tabbed interface:

| Tab | Description |
|-----|-------------|
| **Extract** | Convert a `.neo` file to a MAME or Darksoft ZIP or directory; configurable C chip size |
| **Pack** | Build a `.neo` file from a ZIP or folder with metadata editor, P-ROM swap, and diagnostic mode |
| **Verify** | Full bit-perfect roundtrip check with configurable format and C chip size |
| **Info** | Inspect header metadata: name, manufacturer, NGH number, genre, ROM region sizes |

---

## Command Line Interface

```bash
neoconv <command> [options]
# or
python -m neoconv <command> [options]
```

### `extract` — `.neo` → ROM files

```bash
# To MAME ZIP
neoconv extract game.neo --prefix zin --format mame --out zintrckbp.zip

# To Darksoft ZIP
neoconv extract game.neo --prefix zin --format darksoft --out zin_darksoft.zip

# To directory
neoconv extract game.neo --prefix zin --format mame --out-dir ./roms/

# With explicit C chip size (e.g. Neo Turf Masters: 4 MB chips)
neoconv extract turfmast.neo --prefix 200 --c-chip-size 4194304 --out turfmast.zip
```

| Option | Default | Description |
|--------|---------|-------------|
| `--prefix`, `-p` | *(stem of input filename)* | Filename prefix for output files |
| `--format`, `-f` | `mame` | Output format: `mame` (`.bin`) or `darksoft` (`.rom`) |
| `--out`, `-o` | *(auto)* | Output ZIP path |
| `--out-dir`, `-d` | — | Extract to directory instead of ZIP |
| `--c-chip-size` | `0` (auto) | C chip size in bytes. `0` = auto (`C_total / 2`). Use `2097152` for most games, `4194304` for games with larger chips (e.g. Neo Turf Masters). |

### `pack` — ROM files → `.neo`

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
    --name "My Game" --manufacturer SNK --year 1994 \
    --genre Fighting --ngh 0x95 --out mygame.neo

# With P-ROM bank swap (early SNK titles, exactly 2 MB P-ROM only)
neoconv pack kof94.zip --name "KOF 94" --ngh 0x95 --swap-p --out kof94.neo

# With diagnostic output for unrecognized files
neoconv pack ./roms/ --name "Test" --diagnostic --out test.neo
```

| Option | Default | Description |
|--------|---------|-------------|
| `--name`, `-n` | `Unknown` | Game name (stored in `.neo` header) |
| `--manufacturer`, `-m` | `Unknown` | Manufacturer name |
| `--year`, `-y` | `0` | Release year |
| `--genre`, `-g` | `Other` | Genre (see list below) |
| `--ngh` | `0` | NGH number (decimal or hex, e.g. `149` or `0x95`) |
| `--screenshot` | `0` | TerraOnion screenshot index |
| `--out`, `-o` | *(input stem + `.neo`)* | Output `.neo` path |
| `--swap-p` | off | Swap the two 1 MB halves of a 2 MB P-ROM. **Use only for games that require it** — applying this to a game that does not need it will break it. |
| `--diagnostic` | off | Print a warning for every unrecognized file, to help diagnose ROM naming issues |

Available genres: `Other`, `Action`, `BeatEmUp`, `Sports`, `Driving`, `Platformer`, `Mahjong`, `Shooter`, `Quiz`, `Fighting`, `Puzzle`

### `verify` — Lossless roundtrip check

```bash
neoconv verify game.neo --prefix zin
# Exit code 0 = PASS, 1 = FAIL
```

| Option | Default | Description |
|--------|---------|-------------|
| `--prefix`, `-p` | *(stem of input filename)* | Filename prefix for intermediate extraction |
| `--format`, `-f` | `mame` | Intermediate format for roundtrip: `mame` or `darksoft` |

### `info` — Display `.neo` metadata

```bash
neoconv info game.neo
```

---

## 🛡️ Bit-Perfect Guarantee (Verify)

Collectors and EPROM burners need certainty that converted ROM data is identical to the source. The **Verify** feature provides that certainty by performing a full lossless roundtrip:

1. Extracts all ROM regions from the `.neo` file into memory.
2. Repacks those regions back into a new `.neo` container.
3. Compares the ROM data of both files **byte-by-byte**.

If even a single byte differs, the tool reports the exact offset and the differing values.

```
$ neoconv verify zintrick.neo --prefix zin
Reading: zintrick.neo
Step 1: Extract → mame ZIP
Step 2: Repack ZIP → .neo
Step 3: Compare ROM data regions

✅ PASS — extraction is lossless.
  Original ROM MD5 : aed6010ef6d15d2dba1a4422e70fc822
  Rebuilt  ROM MD5 : aed6010ef6d15d2dba1a4422e70fc822
```

> **Note:** The `.neo` header (name, year, NGH, etc.) is intentionally excluded from the comparison — only ROM data matters for correctness.

---

## Technical Details

### ROM Role Detection (MAME naming)

`neoconv` identifies ROM roles automatically from file extension and naming patterns inside ZIPs or directories:

| Role | Recognized patterns |
|------|---------------------|
| **P ROM** | `.p1`, `.p2`, `-p1.bin`, `_p1.bin`, `-p2.bin` |
| **S ROM** | `.s1`, `-s1.bin`, `_s1.bin` |
| **M ROM** | `.m1`, `-m1.bin`, `_m1.bin` |
| **V ROMs** | `.v1`–`.v8`, `-v1.bin`–`-v8.bin`, `_v1.bin`–`_v8.bin` |
| **C ROMs** | `.c1`–`.c8`, `-c1.bin`–`-c8.bin`, `_c1.bin`–`_c8.bin` |

Standard BIOS files (`000-lo.lo`, `sfix.sfix`, etc.) are silently ignored. Files that do not match any pattern are ignored by default; use `--diagnostic` to see them.

### C-ROM Interleaving

C-ROMs (graphics data) are stored byte-interleaved in `.neo` files: even bytes map to odd chips (c1, c3, …), odd bytes to even chips (c2, c4, …). `neoconv` handles de-interleaving on extract and re-interleaving on pack automatically. This is one of the most common sources of corruption in manual conversions.

C chips always come in pairs. The interleaved bank size is `chip_size × 2`. For most games, chips are 2 MB each (4 MB banks). Games like **Neo Turf Masters** use 4 MB chips (8 MB banks) — use `--c-chip-size 4194304` or select "4 MB" in the GUI for those titles.

### P-ROM Bank Swap (`--swap-p`)

Some early SNK titles store their P-ROM data with the upper and lower 1 MB halves in reversed order. NeoSD/MiSTer expects the standard order, so `neoconv` can optionally swap them on pack. This only applies to P-ROMs that are **exactly 2 MB** in size, and only to titles that actually require it — do not use this flag unless you know the game needs it.

### V-ROM Chunking

V-ROM data is stored as a single contiguous block in `.neo` files and split into individual files on extraction. The default chunk size is **2 MB**, which matches the most common MAME V-ROM file size (as confirmed by analysis of the official `hash/neogeo.xml`). This produces files named `v1.bin`, `v2.bin`, etc.

### `.neo` Container Format

```
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
Offset 0x200–0xFFF  (padding, header is always 4096 bytes)
Data:  P, S, M, V, C   (sequentially, sizes from header)
```

### A Note on CRC Mismatches

For ROM hacks and CD conversions, MAME's `verifyroms` will report CRC mismatches because the data differs from known dumps. This is expected — `neoconv` matches files by name and extension, not by CRC. Use `neoconv verify` to confirm data integrity independently of any external database.

---

## License

MIT — see [LICENSE](LICENSE).
