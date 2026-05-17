"""
neoconv CLI
~~~~~~~~~~~
Command-line interface for neoconv.

Usage examples
--------------
Extract .neo to MAME zip:
    neoconv extract game.neo --prefix zin --format mame --out zin_mame.zip

Extract .neo to Darksoft zip:
    neoconv extract game.neo --prefix zin --format darksoft --out zin_darksoft.zip

Extract .neo to directory:
    neoconv extract game.neo --prefix zin --format mame --out-dir ./roms/

Pack MAME zip to .neo:
    neoconv pack zintrckbp.zip --prefix zin --name "Zintrick" --year 1996 \
        --manufacturer UPL --ngh 224 --genre Sports --out zintrick.neo

Pack directory to .neo:
    neoconv pack ./roms/ --prefix zin --name "Zintrick" --year 1996 \
        --manufacturer UPL --ngh 224 --genre Sports --out zintrick.neo

Edit .neo metadata (no repack):
    neoconv edit game.neo --name "New Title" --genre Fighting
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from . import __version__
from .core import (
    C_CHIP_SIZE_DEFAULT,
    V_BANK_SIZE,
    GENRES,
    GENRE_BY_NAME,
    NeoMeta,
    RomSet,
    build_neo,
    detect_swap_p_needed,
    extract_neo,
    extract_neo_to_zip,
    mame_dir_to_neo,
    mame_zip_to_neo,
    parse_mame_dir,
    parse_mame_zip,
    parse_neo,
    replace_neo_metadata,
    write_bytes_atomic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_genre(value: str) -> int:
    """Convert a genre name or numeric id string to its integer id.

    Raises :class:`ValueError` for unrecognised values so callers (including
    tests) can catch it without having to intercept ``sys.exit``.
    """
    try:
        n = int(value)
        if n not in GENRES:
            raise ValueError(f"genre id {n} is not valid")
        return n
    except ValueError:
        key = value.lower()
        if key not in GENRE_BY_NAME:
            valid = ", ".join(GENRES.values())
            raise ValueError(f"unknown genre '{value}'. Valid genres: {valid}")
        return GENRE_BY_NAME[key]


def _genre_type(value: str) -> int:
    """argparse ``type=`` adapter for ``--genre``.

    Wraps :func:`_resolve_genre` and converts :class:`ValueError` to
    :class:`argparse.ArgumentTypeError` so argparse prints a clean usage
    error instead of a traceback.
    """
    try:
        return _resolve_genre(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _meta_from_args(args: argparse.Namespace) -> NeoMeta:
    return NeoMeta(
        name=args.name,
        manufacturer=args.manufacturer,
        year=args.year,
        genre=args.genre,  # already an int — resolved by argparse via _genre_type
        ngh=args.ngh,
        screenshot=getattr(args, "screenshot", 0),
    )


def _print_neo_info(neo_data: bytes) -> RomSet:
    romset = parse_neo(neo_data)
    print(romset.meta.format_info(romset))
    return romset


# ---------------------------------------------------------------------------
# Subcommand: extract
# ---------------------------------------------------------------------------

def cmd_extract(args: argparse.Namespace) -> None:
    neo_path = Path(args.neo_file)
    if not neo_path.exists():
        print(f"Error: file not found: {neo_path}", file=sys.stderr)
        sys.exit(1)

    neo_data = neo_path.read_bytes()
    print(f"Reading: {neo_path}")
    _rs = _print_neo_info(neo_data)
    print()

    prefix = args.prefix or neo_path.stem
    fmt    = args.format  # 'mame' or 'darksoft'

    # c_chip_size / v_bank_size: 0 means default 2 MB (MAME standard)
    c_chip_size = args.c_chip_size if args.c_chip_size > 0 else C_CHIP_SIZE_DEFAULT
    v_bank_size = args.v_bank_size if args.v_bank_size > 0 else V_BANK_SIZE
    print(f"V bank size: {v_bank_size:,} bytes")
    print(f"C chip size: {c_chip_size:,} bytes")

    if args.out_dir:
        out_dir = Path(args.out_dir)
        written = extract_neo(
            neo_data,
            out_dir,
            name_prefix=prefix,
            fmt=fmt,
            c_chip_size=c_chip_size,
            v_bank_size=v_bank_size,
        )
        print(f"Extracted {len(written)} files to: {out_dir}")
        for role, p in sorted(written.items()):
            print(f"  {p.name:<30} {p.stat().st_size:>10,} bytes")
    else:
        out_path = Path(args.out) if args.out else neo_path.with_suffix(
            f".{'mame' if fmt == 'mame' else 'darksoft'}.zip"
        )
        zip_data = extract_neo_to_zip(
            neo_data,
            name_prefix=prefix,
            fmt=fmt,
            c_chip_size=c_chip_size,
            v_bank_size=v_bank_size,
        )
        write_bytes_atomic(out_path, zip_data)
        print(f"Written: {out_path}  ({len(zip_data)/1024/1024:.2f} MB)")
        with zipfile.ZipFile(out_path) as zf:
            for info in zf.infolist():
                print(f"  {info.filename:<30} {info.file_size:>10,} bytes")


# ---------------------------------------------------------------------------
# Subcommand: pack
# ---------------------------------------------------------------------------

def cmd_pack(args: argparse.Namespace) -> None:
    src = Path(args.input)
    if not src.exists():
        print(f"Error: not found: {src}", file=sys.stderr)
        sys.exit(1)

    meta = _meta_from_args(args)
    out_path = Path(args.out) if args.out else src.with_suffix(".neo")

    # --swap-p choices: "auto" | "yes" | "no"
    raw = args.swap_p
    if raw == "yes":
        swap_p: "bool | str" = True
    elif raw == "auto":
        swap_p = "auto"
    else:
        swap_p = False

    if src.is_dir():
        print(f"Packing directory: {src}")
        neo_data = mame_dir_to_neo(src, meta, swap_p=swap_p, diagnostic=args.diagnostic)
    elif zipfile.is_zipfile(src):
        print(f"Packing ZIP: {src}")
        neo_data = mame_zip_to_neo(src, meta, swap_p=swap_p, diagnostic=args.diagnostic)
    else:
        print(f"Error: input must be a directory or ZIP file.", file=sys.stderr)
        sys.exit(1)

    write_bytes_atomic(out_path, neo_data)
    print(f"Written: {out_path}")
    _print_neo_info(neo_data)


# ---------------------------------------------------------------------------
# Subcommand: detect-swap
# ---------------------------------------------------------------------------

def cmd_detect_swap(args: argparse.Namespace) -> None:
    """Inspect a P-ROM and report whether --swap-p yes is needed."""
    import zipfile as _zf
    src = Path(args.input)
    if not src.exists():
        print(f"Error: file not found: {src}", file=sys.stderr)
        sys.exit(1)

    if _zf.is_zipfile(src):
        romset = parse_mame_zip(src)
        p_rom = romset.p
        print(f"Inspecting P-ROM from ZIP: {src}  ({len(p_rom):,} bytes)")
    else:
        p_rom = src.read_bytes()
        print(f"Inspecting P-ROM file: {src}  ({len(p_rom):,} bytes)")

    needed, reason = detect_swap_p_needed(p_rom)
    print(f"  Result  : {'--swap-p yes  ← required' if needed else '--swap-p no   (default)'}")
    print(f"  Reason  : {reason}")


# ---------------------------------------------------------------------------
# Subcommand: edit
# ---------------------------------------------------------------------------

def cmd_edit(args: argparse.Namespace) -> None:
    """Rewrite .neo header fields without touching ROM payload."""
    neo_path = Path(args.neo_file)
    if not neo_path.exists():
        print(f"Error: file not found: {neo_path}", file=sys.stderr)
        sys.exit(1)

    updates: dict = {}
    if args.name is not None:
        updates["name"] = args.name
    if args.manufacturer is not None:
        updates["manufacturer"] = args.manufacturer
    if args.year is not None:
        updates["year"] = args.year
    if args.genre is not None:
        updates["genre"] = args.genre  # already int — resolved by argparse via _genre_type
    if args.ngh is not None:
        updates["ngh"] = args.ngh
    if args.screenshot is not None:
        updates["screenshot"] = args.screenshot

    if not updates:
        print(
            "Error: specify at least one of --name, --manufacturer, --year, --genre, "
            "--ngh, --screenshot.",
            file=sys.stderr,
        )
        sys.exit(1)

    neo_data = neo_path.read_bytes()
    new_data = replace_neo_metadata(neo_data, **updates)
    out_path = Path(args.out) if args.out else neo_path

    print(f"Editing: {neo_path}")
    write_bytes_atomic(out_path, new_data)
    print(f"Written: {out_path}")
    _print_neo_info(new_data)


# ---------------------------------------------------------------------------
# Subcommand: info
# ---------------------------------------------------------------------------

def cmd_info(args: argparse.Namespace) -> None:
    neo_path = Path(args.neo_file)
    if not neo_path.exists():
        print(f"Error: file not found: {neo_path}", file=sys.stderr)
        sys.exit(1)
    neo_data = neo_path.read_bytes()
    print(f".neo info: {neo_path}")
    _print_neo_info(neo_data)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neoconv",
        description="Convert between .neo container files and MAME / Darksoft Neo Geo ROM sets.",
    )
    parser.add_argument("--version", action="version", version=f"neoconv {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # -- extract --
    p_extract = sub.add_parser("extract", help="Extract a .neo file to ROM files or ZIP.")
    p_extract.add_argument("neo_file", help="Input .neo file")
    p_extract.add_argument("--prefix", "-p", default="", help="Filename prefix (e.g. 'zin')")
    p_extract.add_argument(
        "--format", "-f", choices=["mame", "darksoft"], default="mame",
        help="Output format: 'mame' (.bin) or 'darksoft' (.rom). Default: mame"
    )
    p_extract.add_argument("--out", "-o", default="", help="Output ZIP path")
    p_extract.add_argument("--out-dir", "-d", default="", help="Output directory (instead of ZIP)")
    p_extract.add_argument(
        "--c-chip-size", type=int, default=0, metavar="BYTES",
        help=(
            "Size of each C chip in bytes for de-interleaving (default: 0 = 2097152 / 2 MB). "
            "Use 4194304 (4 MB) for games with larger chips (e.g. Neo Turf Masters). "
            "Chip size cannot be inferred from the .neo alone — check the MAME ROM set."
        )
    )
    p_extract.add_argument(
        "--v-bank-size", type=int, default=0, metavar="BYTES",
        help=(
            "Size of each V ROM chunk in bytes when splitting to v1, v2, ... "
            "(default: 0 = 2097152 / 2 MB). Use 4194304 (4 MB) or other sizes when "
            "the MAME set uses non-standard V chips."
        ),
    )
    p_extract.set_defaults(func=cmd_extract)

    # -- pack --
    p_pack = sub.add_parser("pack", help="Pack MAME ROM zip or directory into a .neo file.")
    p_pack.add_argument("input", help="Input: MAME ZIP file or directory of ROM files")
    p_pack.add_argument("--out", "-o", default="", help="Output .neo path")
    p_pack.add_argument("--name", "-n", default="Unknown", help="Game name")
    p_pack.add_argument("--manufacturer", "-m", default="Unknown", help="Manufacturer")
    p_pack.add_argument("--year", "-y", type=int, default=0, help="Release year")
    p_pack.add_argument(
        "--genre", "-g", default=_genre_type("Other"), type=_genre_type,
        help=f"Genre: {', '.join(GENRES.values())}"
    )
    p_pack.add_argument("--ngh", type=int, default=0, help="NGH number")
    p_pack.add_argument("--screenshot", type=int, default=0, help="Screenshot number (TerraOnion)")
    p_pack.add_argument(
        "--swap-p",
        choices=["auto", "yes", "no"],
        default="auto",
        dest="swap_p",
        help=(
            "P-ROM half-swap mode for 2 MB P-ROMs. "
            "'auto' = heuristic: inspect the M68k vector table and swap only "
            "when the second half carries valid SP/Reset vectors (default). "
            "'yes'  = always swap (legacy behaviour of the old --swap-p flag). "
            "'no'   = never swap."
        ),
    )
    p_pack.add_argument(
        "--diagnostic", action="store_true", default=False,
        help="Print a warning for every file that was not recognized, to help diagnose naming issues."
    )
    p_pack.set_defaults(func=cmd_pack)

    # -- detect-swap --
    p_detect = sub.add_parser(
        "detect-swap",
        help="Inspect a P-ROM (raw file or inside a MAME ZIP) and report whether --swap-p is needed.",
    )
    p_detect.add_argument("input", help="Raw P-ROM file or MAME ZIP containing a *-p1.* file.")
    p_detect.set_defaults(func=cmd_detect_swap)

    # -- edit --
    p_edit = sub.add_parser(
        "edit",
        help="Rewrite .neo header metadata without repacking ROM data.",
    )
    p_edit.add_argument("neo_file", help="Input .neo file")
    p_edit.add_argument(
        "--out",
        "-o",
        default="",
        help="Output .neo path (default: overwrite neo_file in place).",
    )
    p_edit.add_argument("--name", "-n", default=None, help="Game name")
    p_edit.add_argument("--manufacturer", "-m", default=None, help="Manufacturer")
    p_edit.add_argument("--year", "-y", type=int, default=None, help="Release year")
    p_edit.add_argument(
        "--genre",
        "-g",
        default=None,
        type=_genre_type,
        metavar="NAME_OR_ID",
        help=f"Genre name or id ({', '.join(GENRES.values())})",
    )
    p_edit.add_argument("--ngh", type=int, default=None, help="NGH number")
    p_edit.add_argument("--screenshot", type=int, default=None, help="Screenshot number (TerraOnion)")
    p_edit.set_defaults(func=cmd_edit)

    # -- info --
    p_info = sub.add_parser("info", help="Show metadata from a .neo file.")
    p_info.add_argument("neo_file", help="Input .neo file")
    p_info.set_defaults(func=cmd_info)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError, zipfile.BadZipFile, MemoryError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()  # pragma: no cover
