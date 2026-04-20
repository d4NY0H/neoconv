# neoconv

A professional utility for converting between **TerraOnion `.neo` containers** and **MAME / Darksoft Neo Geo ROM sets**.

`neoconv` ensures precise handling of ROM data, supports automatic byte-interleaving for C-ROMs, and provides lossless roundtrip verification — via both CLI and GUI.

---

## Features

- **Extract** — Convert `.neo` files to MAME-compatible (`.bin`) or Darksoft (`.rom`) ZIP archives.
- **Pack** — Build `.neo` files from MAME ZIP archives or directories, with full metadata control.
- **Verify** — Automated roundtrip check (Extract → Repack → byte-comparison) to guarantee data integrity.
- **Info** — Display header metadata and ROM region sizes from any `.neo` file.
- **Dual Interface** — Full-featured GUI and CLI; both expose identical functionality.

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

The GUI provides access to all features through a tabbed interface:

| Tab | Description |
|-----|-------------|
| **Extract** | Convert a `.neo` file into a MAME or Darksoft ZIP archive |
| **Pack** | Build a `.neo` file from a folder or ZIP with an integrated metadata editor |
| **Verify** | Perform a full bit-perfect roundtrip check on any `.neo` file |
| **Info** | Inspect header metadata: name, manufacturer, NGH number, ROM region sizes |

---

## Command Line Interface

The tool can be invoked as a command or as a Python module:

```bash
neoconv <command> [options]
# or
python -m neoconv <command> [options]
```

### Extract `.neo` → MAME ZIP

```bash
neoconv extract game.neo --prefix zin --format mame --out zintrckbp.zip
```

### Extract `.neo` → Darksoft ZIP

```bash
neoconv extract game.neo --prefix zin --format darksoft --out zin_darksoft.zip
```

### Extract `.neo` → directory

```bash
neoconv extract game.neo --prefix zin --format mame --out-dir ./roms/
```

### Pack MAME ZIP → `.neo`

```bash
neoconv pack zintrckbp.zip \
    --name "Zintrick CD Conversion" \
    --manufacturer "ADK" \
    --year 1996 \
    --genre Sports \
    --ngh 224 \
    --out zintrick.neo
```

### Pack directory → `.neo`

```bash
neoconv pack ./roms/ --name "My Game" --manufacturer SNK --year 1994 --genre Fighting --ngh 95 --out mygame.neo
```

### Verify lossless roundtrip

```bash
neoconv verify game.neo --prefix zin
# Exit code 0 = pass, 1 = fail
```

### Show `.neo` metadata

```bash
neoconv info game.neo
```

Available genres: `Other`, `Action`, `BeatEmUp`, `Sports`, `Driving`, `Platformer`, `Mahjong`, `Shooter`, `Quiz`, `Fighting`, `Puzzle`

---

## Technical Details

### Supported File Naming (MAME)

`neoconv` identifies ROM roles automatically based on file extension and naming patterns:

| Role | Recognized patterns |
|------|---------------------|
| **P ROM** | `.p1`, `-p1.bin`, `_p1.bin` |
| **S ROM** | `.s1`, `-s1.bin` |
| **M ROM** | `.m1`, `-m1.bin`, `-m1.M1` |
| **V ROMs** | `.v1`–`.v8`, `-v1.bin`–`-v8.bin` |
| **C ROMs** | `.c1`–`.c8`, `-c1.bin`–`-c8.bin` |

### C-ROM Interleaving

C-ROMs (graphics data) are stored byte-interleaved in `.neo` files — even bytes map to the odd chip (c1, c3, …), odd bytes to the even chip (c2, c4, …). `neoconv` handles de-interleaving on extract and re-interleaving on pack automatically and transparently.

### `.neo` Container Format

```
Offset 0x000   Magic         b'NEO\x01'  (4 bytes)
Offset 0x004   P ROM size    uint32 LE
Offset 0x008   S ROM size    uint32 LE
Offset 0x00C   M ROM size    uint32 LE
Offset 0x010   V1 ROM size   uint32 LE
Offset 0x014   V2 ROM size   uint32 LE
Offset 0x018   C ROM size    uint32 LE   (total, interleaved)
Offset 0x01C   Year          uint16 LE
Offset 0x01E   Genre         uint16 LE
Offset 0x020   Screenshot    uint32 LE
Offset 0x024   NGH number    uint32 LE
Offset 0x02C   Name          33 bytes, null-terminated, latin-1
Offset 0x04D   Manufacturer  17 bytes, null-terminated, latin-1
Offset 0x200–0xFFF  (filler, header padded to 4096 bytes)
Data: P, S, M, V1, [V2], C   (sequentially, sizes from header)
```

### A Note on CRC Mismatches

For ROM hacks and CD conversions, MAME's `verifyroms` will report CRC mismatches because the data differs from known dumps. This is expected — `neoconv` matches files by name and extension, not by CRC. Use `neoconv verify` to confirm data integrity independently of any external database.

---

## License

MIT — see [LICENSE](LICENSE).
