# neoconv

> A preservation-focused **CLI and GUI** tool to **convert** between **TerraOnion `.neo` containers** and **MAME / Darksoft Neo Geo ROM sets**, and to **edit `.neo` header metadata** (name, manufacturer, year, genre, NGH, screenshot index) **without repacking** ROM data.

Use **`neoconv`** on the command line or via **`neoconv-gui`** (same core engine). It **packs** MAME ZIPs or ROM folders into `.neo`, **extracts** `.neo` back to individual ROM files, and **rewrites** headers when only metadata needs to change. It handles C-ROM byte-interleaving, **P-ROM half-swap** (default: **auto-detect** from the M68000 vector table, with `yes` / `no` overrides), V-ROM chunking, and TerraOnion header fields — for commercial dumps, hacks, CD conversions, and homebrew.

### Getting started

| Goal | Command / tab |
|------|----------------|
| MAME ZIP or ROM folder → `.neo` | `neoconv pack …` or GUI **Pack** |
| `.neo` → MAME / Darksoft ROM files | `neoconv extract …` or GUI **Extract** |
| Fix title, genre, NGH, … without repacking | `neoconv edit …` or GUI **Edit** |
| Inspect metadata, sizes, and MD5 hashes | `neoconv info …` or GUI **Info** |

---

## Why neoconv?

Most Neo Geo tools only handle one direction or break on non-standard sets. `neoconv` focuses on correct **conversion** and transparent **metadata edits** for `.neo` files.

| Property | Description |
|----------|-------------|
| **Reliable** | Deterministic conversions with automated tests for core roundtrip behaviour |
| **Universal** | Handles commercial sets, hacks, CD conversions, and homebrew |
| **Transparent** | C interleaving, P-ROM swap (auto or manual), and V chunking are explicit and documented |
| **Configurable** | On **extract**: `--c-chip-size` and `--v-bank-size` in bytes. **neoconv** falls back to **2 MB** (`2097152`) when unset; the correct value per game comes from the MAME ROM set (e.g. 4 MB / `4194304` C chips for Neo Turf Masters), not from the `.neo` header alone |
| **Dual interface** | Same pack / extract / edit / info workflows in CLI and GUI |

---

## Feature parity: CLI and GUI

Both interfaces support the same core workflows:

| Workflow | CLI | GUI |
|----------|-----|-----|
| Extract `.neo` to MAME / Darksoft files | ✅ | ✅ |
| Pack MAME ZIP or directory to `.neo` | ✅ | ✅ |
| Edit `.neo` header metadata (no repack) | ✅ | ✅ |
| View `.neo` metadata, region sizes, and per-region MD5 | ✅ | ✅ |
| P-ROM bank swap (auto-detect + manual override) | ✅ | ✅ |
| Standalone `detect-swap` (inspect P-ROM without packing) | ✅ | — *(Pack with **Auto-detect** logs the same check in the GUI)* |
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

Download the latest binary from the [Releases](https://github.com/d4NY0H/neoconv/releases) page — no Python installation required. Prebuilt assets are **GUI only**; install from source (below) for the **`neoconv`** CLI.

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
| **Pack** | Build `.neo` from ZIP/folder with metadata; P-ROM swap via radio (`auto` / `yes` / `no`). Status line checks mandatory P/S/M roles and warns on **V/C filename gaps** before pack |
| **Extract** | Convert `.neo` to MAME or Darksoft ZIP/directory; **C Chip Size** / **V Bank Size** dropdowns (presets 512 KB–20 MB / 16 MB). Arbitrary byte sizes: CLI only (`--c-chip-size`, `--v-bank-size`) |
| **Edit** | Load header fields from a `.neo`, adjust metadata (name/manufacturer truncated to header limits), write back (optional separate output path) |
| **Info** | Inspect metadata, ROM region sizes, and **MD5 per region** (P, S, M, V, C) |

---

## CLI usage

```bash
neoconv <command> [options]
# or
python3 -m neoconv <command> [options]
```

Commands: **`extract`**, **`pack`**, **`edit`**, **`detect-swap`**, **`info`**.

On failure, the CLI prints `Error: …` to **stderr** and exits with code **1** (missing ROMs, invalid options, bad `.neo`, and similar cases) instead of a Python traceback.

---

### `extract` — `.neo` → ROM files

```bash
# MAME ZIP
neoconv extract input.neo --prefix game --format mame --out game_mame.zip

# Darksoft ZIP
neoconv extract input.neo --prefix game --format darksoft --out game_darksoft.zip

# Output directory
neoconv extract input.neo --prefix game --format mame --out-dir ./roms/

# Explicit C chip size (example: 4 MB chips)
neoconv extract input.neo --prefix game --c-chip-size 4194304 --out game_customc.zip

# Explicit V bank size (example: 4 MB v1/v2 chunks)
neoconv extract input.neo --prefix game --v-bank-size 4194304 --out game_v4m.zip
```

| Option | Default | Description |
|--------|---------|-------------|
| `--prefix`, `-p` | *(input stem)* | Filename prefix for output files |
| `--format`, `-f` | `mame` | Output format: `mame` (`.bin`) or `darksoft` (`.rom`) |
| `--out`, `-o` | *(auto)* | Output ZIP path (ignored if `--out-dir` is set) |
| `--out-dir`, `-d` | — | Extract to directory instead of ZIP; **wins over `--out`** when both are given |
| `--c-chip-size` | `0` (= `2097152`) | Size of **each C chip** in **bytes** before interleaving. `0` = 2 MB. GUI presets match [common sizes](#common-extract-sizes-cli-bytes). **CLI:** any positive byte value. See [C-ROM interleaving](#c-rom-interleaving) |
| `--v-bank-size` | `0` (= `2097152`) | Size of **each V file** (`v1`, `v2`, …) in **bytes**. `0` = 2 MB. GUI presets match [common sizes](#common-extract-sizes-cli-bytes). See [V-ROM chunking](#v-rom-chunking) |

**Overwrite behaviour:** Existing output files are replaced without prompting. A **warning** is printed (CLI: stderr; GUI: log) for each path that already exists. Directory extract updates files in place; ZIP output is replaced atomically (see [Atomic file writes](#atomic-file-writes)).

---

### `pack` — ROM files → `.neo`

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
| `--name`, `-n` | `Unknown` | Game title in the `.neo` header: **latin-1**, max **32** content bytes (33-byte field incl. NUL). The GUI truncates to this limit. |
| `--manufacturer`, `-m` | `Unknown` | Manufacturer string: **latin-1**, max **16** content bytes (17-byte field incl. NUL). The GUI truncates to this limit. |
| `--year`, `-y` | `0` | Release year: **uint16** (0–65535). |
| `--genre`, `-g` | `Other` | Genre **name** or numeric **uint16** id (see list below). |
| `--ngh` | `0` | NGH catalogue number: **uint32** (non-negative integer). |
| `--screenshot` | `0` | TerraOnion screenshot index: **uint32** (non-negative integer). |
| `--out`, `-o` | *(input stem + `.neo`)* | Output `.neo` path |
| `--swap-p` | `auto` | P-ROM half-swap mode: `auto` (heuristic, default), `yes` (always), `no` (never) |
| `--diagnostic` | off | Warn on unrecognized filenames |

**Genres** (`--genre` name or numeric id):

| ID | Name |
|----|------|
| 0 | Other |
| 1 | Action |
| 2 | BeatEmUp |
| 3 | Sports |
| 4 | Driving |
| 5 | Platformer |
| 6 | Mahjong |
| 7 | Shooter |
| 8 | Quiz |
| 9 | Fighting |
| 10 | Puzzle |

See also: [P-ROM bank swap](#p-rom-bank-swap---swap-p), [ROM file naming](#pack-input-rom-file-naming).

---

### `edit` — change `.neo` header metadata (no repack)

Updates TerraOnion header fields **without** touching P/S/M/V/C payload. At least one metadata option is required.

```bash
# Correct title in place (overwrites the input file atomically)
neoconv edit game.neo --name "Windjammers"

# Multiple fields; write a new file (input unchanged)
neoconv edit game.neo --genre Fighting --year 1994 --ngh 65 --out game_fixed.neo
```

| Option | Default | Description |
|--------|---------|-------------|
| `--out`, `-o` | *(overwrite input)* | Output `.neo` path |
| `--name`, `-n` | — | Same limits as `pack`: latin-1, max **32** content bytes |
| `--manufacturer`, `-m` | — | Same limits as `pack`: latin-1, max **16** content bytes |
| `--year`, `-y` | — | **uint16** year |
| `--genre`, `-g` | — | Genre name or **uint16** id (same set as `pack`) |
| `--ngh` | — | **uint32** NGH number |
| `--screenshot` | — | **uint32** screenshot index |

---

### `detect-swap` — inspect P-ROM swap requirement

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

See [P-ROM bank swap](#p-rom-bank-swap---swap-p) for `--swap-p` modes when packing.

---

### `info` — display `.neo` metadata

Prints header metadata, ROM region sizes, and **MD5 per region** (P, S, M, V, C) when a full `.neo` is loaded — useful to compare two files that differ only in the header.

```bash
neoconv info input.neo
```

---

## Technical details

Background on pack/extract behaviour, ROM naming, and the on-disk `.neo` layout.

| Section | Topics |
|---------|--------|
| [Pack input](#pack-input-rom-file-naming) | MAME filenames, directory layout, synthetic S-ROM |
| [Extract sizing](#extract-c-and-v-rom-sizing) | Byte presets, C interleaving, V chunking |
| [P-ROM swap](#p-rom-bank-swap---swap-p) | `--swap-p` / auto-detect |
| [`.neo` format](#neo-container-format) | Header layout, V1/V2 fields |
| [Notes](#notes) | CRC mismatches, out-of-scope items |

---

### Pack input: ROM file naming

The table below matches the primary rules in `name_to_role`: extension (e.g. `.p1`, `.c1`) **or** basename suffix patterns such as `-p1.bin`, `_m1.bin`, or a stem ending in `-v3` / `_c2`.

| Role | Recognized patterns |
|------|---------------------|
| **P ROM** | `.p1`, `.p2`, `-p1.bin`, `_p1.bin`, `-p2.bin` |
| **S ROM** | `.s1`, `-s1.bin`, `_s1.bin` |
| **M ROM** | `.m1`, `-m1.bin`, `_m1.bin` |
| **V ROMs** | `.v1`-`.v8`, `-v1.bin`-`-v8.bin`, `_v1.bin`-`_v8.bin` |
| **C ROMs** | `.c1`-`.c16`, `-c1.bin`-`-c16.bin`, `_c1.bin`-`_c16.bin` (C9–C16 for extended / hack sets) |

#### Directory layout and sequence gaps

`pack` reads ROM files in the chosen folder **and one level of subfolders** (typical after unzipping).

**Gaps** in the V or C sequence (e.g. `v1` + `v3` without `v2`) cause pack to **abort** with an error instead of producing a broken `.neo`.

Not every MAME filename variant is mapped (for example some `*-c1a.bin`-style names are **not** assigned a **C** role). Those files may still participate in other logic (see below).

#### Synthetic S-ROM (no physical `s1`)

Some MAME parents (e.g. PVC / encrypted boards) ship without a separate text-layer `s1`; the driver uses a zero-filled "fixed" region. If **P** and **M** are present, there is **no** `s1`, but filenames look like a Neo Geo **C1** sprite set, `neoconv` may **inject** a zero-filled `S` region and emit a `UserWarning`. The fill size is chosen from filename heuristics aligned with `neogeo.xml`:

| Pattern | Synthetic S size |
|---------|------------------|
| Basenames starting with `kf10-` (KOF2002 bootleg) | 256 KiB |
| ``-c1r.`` / ``-c2r.`` sprite chip names (e.g. `269-c1r.c1`) | 512 KiB |
| Certain **three-digit MAME set IDs** in `NNN-p1.` / `NNN-m1.` / `NNN-c1….c1` (see `_SYNTH_S_MAME_512K_SET_IDS` in `neoconv/core/constants.py`) | 512 KiB |
| Default | 128 KiB |

#### FBNeo compatibility

FBNeo Neo Geo sets use the same ROM naming conventions as MAME and are supported out of the box. BIOS-related files (`000-lo.lo`, `sfix.sfix`, `sm1.sm1`, `sp-s2.sp1`, etc.) are ignored automatically.

Sets where C-chip filenames carry a suffix in the **stem** but use native extensions (e.g. `263-c1d.c1`, `269-c1r.c1`, `268-c1c.c1`) are recognised correctly — the extension `.c1` / `.c2` match takes priority.

**Exception — split C chips (`c1a` + `c1b` style):** Four hack/homebrew sets use a two-file split for individual C chips with `.bin` extension:

| Set | Files | Fix |
|-----|-------|-----|
| `kog`, `kogplus` | `5232-c1a.bin` + `5232-c1b.bin` → `c1`, etc. | `cat 5232-c1a.bin 5232-c1b.bin > 5232-c1.bin` |
| `kof10th` and variants | `kf10-c1a.bin` + `kf10-c1b.bin` → `c1`, etc. | `cat kf10-c1a.bin kf10-c1b.bin > kf10-c1.bin` |

Merge each split pair with `cat` (Linux/macOS) before packing. All official SNK titles and the vast majority of hacks work without any preparation.

#### Ignored files

Standard BIOS files (`000-lo.lo`, `sfix.sfix`, etc.) are ignored. Unknown files are also ignored unless `--diagnostic` is enabled.

---

### Extract: C and V ROM sizing

#### Why you need to specify chip sizes at all

The `.neo` header stores only the **total byte count** for the C-ROM block and the V-ROM block — it does not record how many chips those blocks were split across, or how large each individual chip was. That information existed in the original MAME ROM set but is lost when the files are merged into the `.neo` container.

When **neoconv** extracts, it must re-split those blocks into individual files. The split is purely mechanical — any size that divides the total evenly is accepted without error. The question is only whether the resulting files **match what MAME or Darksoft expect**.

For example, 8 MB of C-ROM data could legitimately be split as `c1(4 MB)+c2(4 MB)` or as `c1(2 MB)+c2(2 MB)+c3(2 MB)+c4(2 MB)`. Both extractions succeed, but only one matches the MAME `neogeo.xml` entry for that title. Using the wrong split means MAME's ROM verification (`verifyroms`) will report missing or mismatched files. The ROM data itself is intact — if you correct the XML to match the actual file layout, the game will run.

The **2 MB default covers the majority of titles**. Always cross-check against the MAME `neogeo.xml` or FBNeo ROM database for any title you are unsure about.

#### Common extract sizes (CLI bytes)

The CLI flags `--c-chip-size` and `--v-bank-size` take **bytes** (not megabytes). The GUI dropdown labels use MB/KB; values map to the same byte counts.

| Label | CLI value (`--c-chip-size` / `--v-bank-size`) | C GUI | V GUI |
|-------|-----------------------------------------------|-------|-------|
| 512 KB | `524288` | ✅ | ✅ |
| 1 MB | `1048576` | ✅ | ✅ |
| 2 MB (unset / `0`) | `2097152` | ✅ | ✅ |
| 4 MB | `4194304` | ✅ | ✅ |
| 8 MB | `8388608` | ✅ | ✅ |
| 16 MB | `16777216` | ✅ | ✅ |
| 20 MB | `20971520` | ✅ (C only) | — |

`0` for either flag is **neoconv’s fallback** (`2097152`, 2 MB), not necessarily the correct size for every game. Any other positive integer is accepted on the CLI.

#### C-ROM interleaving

C-ROM graphics are byte-interleaved in `.neo`:

- even bytes → odd chips (`c1`, `c3`, …)
- odd bytes → even chips (`c2`, `c4`, …)

C chips always come in pairs. Interleaved bank size is `chip_size × 2`.

On **extract**, if unset, **neoconv** assumes **2 MB** per chip (`2097152` bytes; CLI `0` / GUI “2 MB”). Larger chips (e.g. **4 MB** / `4194304` for Neo Turf Masters) must match the MAME set — total C size in the `.neo` header does not uniquely determine per-chip size.

| | When unset | GUI presets | CLI |
|---|------------|-------------|-----|
| **C chip** (`c1`, `c2`, …) | 2 MB (`2097152`) | 512 KB – 20 MB | any positive byte value; `0` = `2097152` |

**Choosing the right size:** For a known title, open MAME’s **`neogeo.xml`** (or the FBNeo ROM database) and check each `c1`, `c2`, … entry. The `size="…"` attribute is the per-chip size in bytes (e.g. `size="4194304"` → `--c-chip-size 4194304`). If extract fails with “not a multiple of chip_size×2”, try another size from that list.

#### V-ROM chunking

V-ROM data is contiguous in `.neo` and split to `v1`, `v2`, … on extract. When unset, chunk size is **2 MB** (`2097152`; `--v-bank-size 0` or GUI **V Bank Size**).

| | When unset | GUI presets | CLI |
|---|------------|-------------|-----|
| **V bank** (`v1`, `v2`, …) | 2 MB (`2097152`) | 512 KB – 16 MB | any positive byte value; `0` = `2097152` |

**Choosing the right size:** In MAME **`neogeo.xml`**, check each `v1`, `v2`, … entry — the file `size` is the bank size for `--v-bank-size` (often 2 MB / `2097152`; some sets use 4 MB / `4194304`). Match what the MAME ZIP contains so filenames and lengths align after extract.

If total V size is not a multiple of the bank size, the last file is shorter and a warning is emitted.

---

### P-ROM bank swap (`--swap-p`)

Some Neo Geo titles and hacks store their 2 MB P-ROM with the two 1 MB halves in reversed order relative to what TerraOnion NeoSD / MiSTer expect.

`neoconv` detects this automatically by inspecting the M68000 exception-vector table (initial Stack Pointer + Reset PC) in both halves. The half carrying valid values — SP in Work RAM (`0x100000–0x10FFFF`), Reset PC in ROM or BIOS (`0x000100–0x1FFFFF` or `0xC00000–0xC7FFFF`) — determines whether a swap is applied.

| Mode | Behaviour |
|------|-----------|
| `auto` (default) | Detect from vector table; prints a diagnostic line |
| `yes` | Always swap — for titles where auto-detect is ambiguous |
| `no` | Never swap — to opt out explicitly |

When auto-detect is **inconclusive** (neither half has plausible M68k vectors), pack continues **without** swap but prints **`[WARN]`** and emits a warning — run `neoconv detect-swap <zip>` or set `--swap-p yes` / `no` explicitly.

---

### `.neo` container format

#### V1 / V2 size fields (read vs write)

Some `.neo` files split the **total V ROM payload** across the **V1** and **V2** size fields at offsets `0x010` and `0x014`. **neoconv** reads both and merges the bytes in memory. On **output** (`pack`, `build_neo`, `replace_neo_metadata`), the header is **normalised**: all V length is stored in **V1** and **V2 is set to 0** (TerraOnion-style layout). Loading or rewriting such a file may emit a **`UserWarning`**.

#### Header and payload layout

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

#### Atomic file writes

`pack` (output `.neo`), `extract` (output ZIP), and `edit` write via a temporary file in the same directory and **`os.replace`**, so an interrupted run is less likely to leave a truncated file. **Directory extract** still overwrites individual ROM files in place (with warnings).

---

### Notes

#### About CRC mismatches

For hacks and CD conversions, MAME `verifyroms` may report CRC mismatches because data differs from known dumps. This is expected when the dump is intentionally different from MAME's reference set.

#### Out of scope

- **`detect-swap` on `.neo` files:** not useful — the P-ROM swap is applied during `pack` and already encoded in the `.neo` payload. There is nothing left to detect.
- **`verify` CLI subcommand:** `verify_roundtrip` exists in `neoconv.core` as a testing utility. Exposing it as a CLI command would only confirm that neoconv round-trips its own output correctly, which is covered by the test suite. It is not a user-facing feature.
- **Directory traversal deeper than one level** in `pack`: the one-level limit (top-level files + one subdirectory) covers all known MAME unzip layouts. Recursive traversal would risk picking up unrelated files from nested archives or build artefacts.
- **Automatic merging of split C chips** (`c1a`+`c1b` style): see [FBNeo compatibility](#fbneo-compatibility).
- **FBNeo as a separate input format:** FBNeo Neo Geo sets use the same naming conventions as MAME and are supported out of the box — see [FBNeo compatibility](#fbneo-compatibility).

---

## License

MIT - see [LICENSE](LICENSE).
