#!/usr/bin/env python3
"""CARiN / Carminat map database (carindb) -> GeoPackage for QGIS.

Examples:
  navdb/decoder.py --info                       what is in the database
  navdb/decoder.py --area warszawa              Warsaw only (seconds)
  navdb/decoder.py                              everything (about 20 minutes, 2.8 GB)
  navdb/decoder.py --area mazowieckie --layers roads,poi
  navdb/decoder.py --bbox 20.85,52.10,21.27,52.37 -o /tmp/centrum.gpkg

The format is described in navdb/docs/format.md.
"""
import argparse
import struct
import sys
import time
from pathlib import Path

from libs import layers
from libs.carindb import BLOCK, cstring, header_info, lat, lon, table_directory
from libs.gpkg import GeoPackage

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "temp/navdb/carindb"

AREAS = {   # name: (min lon, min lat, max lon, max lat)
    "warszawa": (20.85, 52.10, 21.27, 52.37),
    "mazowieckie": (19.25, 51.00, 23.15, 53.50),
    "polska": (14.05, 48.95, 24.20, 54.90),
}
LAYERS = {   # option name: what it writes
    "roads": "parcels, roads (routing levels 0-3)",
    "background": "areas, overview_roads (6 levels)",
    "poi": "poi",
    "cities": "cities",
}


class Progress:
    """One status line on stderr, rewritten in place on a terminal; quiet = summaries only."""

    def __init__(self, quiet):
        self.quiet = quiet
        self.tty = sys.stderr.isatty()
        self.start = self.last = time.monotonic()

    def step(self, text, done, total):
        now = time.monotonic()
        if self.quiet or not self.tty or now - self.last < 0.2:
            return
        self.last = now
        pct = 100 * done // total if total else 0
        print(f"\r  {text}: {pct:3d}%  [{self.clock()}]\033[K", end="", file=sys.stderr, flush=True)

    def finish(self, text):
        if self.tty and not self.quiet:
            print("\r\033[K", end="", file=sys.stderr)
        print(f"  {text}  [{self.clock()}]", flush=True)

    def clock(self):
        s = int(time.monotonic() - self.start)
        return f"{s // 60}:{s % 60:02d}"


def info(f):
    """Header, countries and table directory."""
    sizes, release = header_info(f)
    f.seek(0)
    h = f.read(BLOCK)
    x0, y0, x1, y1 = struct.unpack_from(">4I", h, 0x34)
    size = f.seek(0, 2)
    print(f"file      {f.name} ({size / 1e6:.0f} MB, {size // BLOCK} blocks)")
    print(f"release   {release}, CD {h[3]}")
    print(f"extent    lon {lon(x0):.3f} .. {lon(x1):.3f}, lat {lat(y0):.3f} .. {lat(y1):.3f}")
    f.seek(1 * BLOCK)     # table 17: key / value texts
    report = next((t.decode("latin1") for t in f.read(BLOCK).split(b"\0") if b"name:" in t), "")
    for line in report.splitlines():     # "1.  name:   eeu_nok_nok_12q4_20130205p."
        key, _, value = line.partition(":")
        key = key.split(".", 1)[-1].strip()
        label = {"name": "data", "content": "content", "conversion date": "converted"}.get(key)
        if label and value.strip():
            print(f"{label:<9} {value.strip().rstrip('.')}")
    f.seek(4 * BLOCK)     # table b: countries
    u = f.read(BLOCK)
    off, count = struct.unpack_from(">HH", u, 8)
    names = []
    for i in range(count):
        name, _, _, rec = struct.unpack_from(">HHHH", u, off + 8 * i)
        names.append(f"{cstring(u, name)} ({u[rec + 46:rec + 48].decode('latin1')})")
    print(f"countries {', '.join(names)}")
    print("tables    id: data blocks")
    for tid, (_, (b, _), (c, n)) in sorted(table_directory(f).items(), key=lambda kv: kv[1][1][0]):
        if b or c:
            print(f"          {tid:2x}: {b:#07x} .. {c + n - 1:#07x}")
            if tid == 1:
                print("          (house numbers, kind 4 units outside the directory, follow table 1)")


def parse_args():
    p = argparse.ArgumentParser(
        prog="decoder.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Decodes the CARiN / Carminat map database (carindb) into a GeoPackage for QGIS.",
        epilog="areas: " + ", ".join(AREAS) + "\nlayers: " +
               "; ".join(f"{k} = {v}" for k, v in LAYERS.items()) +
               "\n\nWithout --area / --bbox the whole database is decoded. Only the chosen layers are\n"
               "replaced in an existing output file, the others stay.")
    p.add_argument("carindb", nargs="?", type=Path, default=DEFAULT_DB,
                   help=f"database file (default: {DEFAULT_DB.relative_to(ROOT)})")
    p.add_argument("-o", "--output", type=Path,
                   help="GeoPackage to write, or a directory to write it into (default: temp/navdb/<area>.gpkg)")
    where = p.add_mutually_exclusive_group()
    where.add_argument("-a", "--area", choices=AREAS, help="a named area")
    where.add_argument("-b", "--bbox", metavar="LON0,LAT0,LON1,LAT1", help="a box in degrees")
    p.add_argument("-l", "--layers", default=",".join(LAYERS),
                   help="comma separated, from: " + ", ".join(LAYERS) + " (default: all)")
    p.add_argument("-i", "--info", action="store_true", help="show what is in the database and stop")
    p.add_argument("-q", "--quiet", action="store_true", help="no progress line, only summaries")
    args = p.parse_args()

    if not args.carindb.is_file():
        p.error(f"{args.carindb} not found; extract it from the map disc image first:\n"
                f"  python3 navdb/tools/extract_navdb.py")
    args.box = None
    if args.area:
        args.box = AREAS[args.area]
    elif args.bbox:
        try:
            args.box = tuple(float(v) for v in args.bbox.split(","))
            assert len(args.box) == 4 and args.box[0] < args.box[2] and args.box[1] < args.box[3]
        except (ValueError, AssertionError):
            p.error("--bbox needs four numbers: min lon, min lat, max lon, max lat")
    args.layer_list = [x.strip() for x in args.layers.split(",") if x.strip()]
    unknown = [x for x in args.layer_list if x not in LAYERS]
    if unknown:
        p.error(f"unknown layer {', '.join(unknown)}; choose from {', '.join(LAYERS)}")
    if args.info:                            # nothing is written
        return args
    name = f"{args.area or ('bbox' if args.box else 'carindb')}.gpkg"
    if not args.output:
        args.output = ROOT / "temp/navdb" / name
    elif args.output.is_dir():
        args.output = args.output / name     # a directory: the file goes inside it
    elif args.output.suffix.lower() != ".gpkg":
        p.error(f"{args.output}: the output must be a .gpkg file or a directory")
    if args.output.exists() and not args.output.is_file():
        p.error(f"{args.output} exists and is not a file")
    if args.output.resolve() == args.carindb.resolve():
        p.error("the output would overwrite the database")
    if args.output.is_file():
        with open(args.output, "rb") as f:
            if f.read(16) != b"SQLite format 3\0":
                p.error(f"{args.output} exists and is not a GeoPackage; choose another output")
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        p.error(f"cannot create {args.output.parent}: {e.strerror}")
    return args


def main():
    args = parse_args()
    with open(args.carindb, "rb") as f:
        if args.info:
            info(f)
            return
        tables = table_directory(f)
        sizes, release = header_info(f)
        where = args.area or (args.bbox if args.box else "whole database")
        print(f"decoding {args.carindb.name} ({where}): {', '.join(args.layer_list)} -> {args.output}")
        progress = Progress(args.quiet)
        gp = GeoPackage(args.output)
        try:
            if "roads" in args.layer_list:
                layers.parcels(f, gp, tables, args.box, sizes, release, progress)
            if "background" in args.layer_list:
                layers.background(f, gp, tables, args.box, sizes, release, progress)
            if "poi" in args.layer_list:
                layers.poi(f, gp, tables, args.box, progress)
            if "cities" in args.layer_list:
                layers.cities(f, gp, tables, args.box, sizes, release, progress)
        except KeyboardInterrupt:
            print("\ninterrupted; nothing written", file=sys.stderr)
            sys.exit(130)
        gp.close()
    print(f"done in {progress.clock()}: open {args.output} in QGIS (styles load automatically)")


if __name__ == "__main__":
    main()
