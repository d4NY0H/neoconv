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

Verify roundtrip (extract then repack, compare ROM data):
    neoconv verify game.neo --prefix zin
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path

from . import __version__
from .core import (
    GENRES,
    GENRE_BY_NAME,
    NeoMeta,
    build_neo,
    extract_neo,
    extract_neo_to_zip,
    mame_dir_to_neo,
    mame_zip_to_neo,
    parse_mame_dir,
    parse_mame_zip,
    parse_neo,
    verify_roundtrip,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_genre(value: str) -> int:
    try:
        n = int(value)
        if n not in GENRES:
            raise ValueError
        return n
    except ValueError:
        key = value.lower()
        if key not in GENRE_BY_NAME:
            valid = ", ".join(GENRES.values())
            print(f"Error: unknown genre '{value}'. Valid genres: {valid}", file=sys.stderr)
            sys.exit(1)
        return GENRE_BY_NAME[key]


def _meta_from_args(args: argparse.Namespace) -> NeoMeta:
    return NeoMeta(
        name=args.name,
        manufacturer=args.manufacturer,
        year=args.year,
        genre=_resolve_genre(args.genre),
        ngh=args.ngh,
        screenshot=getattr(args, "screenshot", 0),
    )


def _print_neo_info(neo_data: bytes) -> None:
    romset = parse_neo(neo_data)
    print(romset.meta.format_info(romset))


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
    _print_neo_info(neo_data)
    print()

    prefix = args.prefix or neo_path.stem
    fmt    = args.format  # 'mame' or 'darksoft'

    if args.out_dir:
        out_dir = Path(args.out_dir)
        written = extract_neo(neo_data, out_dir, name_prefix=prefix, fmt=fmt)
        print(f"Extracted {len(written)} files to: {out_dir}")
        for role, p in sorted(written.items()):
            print(f"  {p.name:<30} {p.stat().st_size:>10,} bytes")
    else:
        out_path = Path(args.out) if args.out else neo_path.with_suffix(
            f".{'mame' if fmt == 'mame' else 'darksoft'}.zip"
        )
        zip_data = extract_neo_to_zip(neo_data, name_prefix=prefix, fmt=fmt)
        out_path.write_bytes(zip_data)
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

    if src.is_dir():
        print(f"Packing directory: {src}")
        neo_data = mame_dir_to_neo(src, meta, swap_p=args.swap_p, diagnostic=args.diagnostic)
    elif zipfile.is_zipfile(src):
        print(f"Packing ZIP: {src}")
        neo_data = mame_zip_to_neo(src, meta, swap_p=args.swap_p, diagnostic=args.diagnostic)
    else:
        print(f"Error: input must be a directory or ZIP file.", file=sys.stderr)
        sys.exit(1)

    out_path.write_bytes(neo_data)
    print(f"Written: {out_path}")
    _print_neo_info(neo_data)


# ---------------------------------------------------------------------------
# Subcommand: verify
# ---------------------------------------------------------------------------

def cmd_verify(args: argparse.Namespace) -> None:
    neo_path = Path(args.neo_file)
    if not neo_path.exists():
        print(f"Error: file not found: {neo_path}", file=sys.stderr)
        sys.exit(1)

    original = neo_path.read_bytes()
    prefix   = args.prefix or neo_path.stem
    fmt      = getattr(args, "format", "mame")

    print(f"Verifying: {neo_path}")
    print(f"Step 1: Extract -> {fmt} ZIP")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        zip_data = extract_neo_to_zip(original, name_prefix=prefix, fmt=fmt)
        zip_path = tmp / f"{prefix}.zip"
        zip_path.write_bytes(zip_data)

        print(f"Step 2: Repack ZIP -> .neo")
        meta = parse_neo(original).meta
        rebuilt = mame_zip_to_neo(zip_path, meta)

    print(f"Step 3: Compare ROM data regions")
    result = verify_roundtrip(original, rebuilt)

    print()
    if result.ok:
        print("✅ PASS — extraction is lossless.")
    else:
        print("❌ FAIL — ROM data mismatch!")
    print(f"  Original ROM MD5 : {result.original_rom_md5}")
    print(f"  Rebuilt  ROM MD5 : {result.rebuilt_rom_md5}")
    print(f"  File size match  : {result.file_size_match}")
    print(f"  Details          : {result.details}")

    sys.exit(0 if result.ok else 1)


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
    p_extract.set_defaults(func=cmd_extract)

    # -- pack --
    p_pack = sub.add_parser("pack", help="Pack MAME ROM zip or directory into a .neo file.")
    p_pack.add_argument("input", help="Input: MAME ZIP file or directory of ROM files")
    p_pack.add_argument("--out", "-o", default="", help="Output .neo path")
    p_pack.add_argument("--name", "-n", default="Unknown", help="Game name")
    p_pack.add_argument("--manufacturer", "-m", default="Unknown", help="Manufacturer")
    p_pack.add_argument("--year", "-y", type=int, default=0, help="Release year")
    p_pack.add_argument(
        "--genre", "-g", default="Other",
        help=f"Genre: {', '.join(GENRES.values())}"
    )
    p_pack.add_argument("--ngh", type=int, default=0, help="NGH number")
    p_pack.add_argument("--screenshot", type=int, default=0, help="Screenshot number (TerraOnion)")
    p_pack.add_argument(
        "--swap-p", action="store_true", default=False,
        help=(
            "Swap the two 1 MB halves of a 2 MB P-ROM before packing. "
            "Required for some early SNK titles with P-ROM banking (e.g. early KOF). "
            "Only valid for exactly 2 MB P-ROMs. Do NOT use unless you know the game needs it."
        )
    )
    p_pack.add_argument(
        "--diagnostic", action="store_true", default=False,
        help="Print a warning for every file that was not recognized, to help diagnose naming issues."
    )
    p_pack.set_defaults(func=cmd_pack)

    # -- verify --
    p_verify = sub.add_parser(
        "verify",
        help="Verify lossless roundtrip: extract .neo -> repack -> compare ROM data."
    )
    p_verify.add_argument("neo_file", help="Input .neo file")
    p_verify.add_argument("--prefix", "-p", default="", help="Filename prefix")
    p_verify.add_argument(
        "--format", "-f", choices=["mame", "darksoft"], default="mame",
        help="Intermediate format to use for roundtrip. Default: mame"
    )
    p_verify.set_defaults(func=cmd_verify)

    # -- info --
    p_info = sub.add_parser("info", help="Show metadata from a .neo file.")
    p_info.add_argument("neo_file", help="Input .neo file")
    p_info.set_defaults(func=cmd_info)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
