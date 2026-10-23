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
import os
import struct
import sys
import time
from pathlib import Path

from libs import layers
from libs.carindb import (BlockFile, cstring, head_bytes, header_info, lat, lon,
                          open_database, read_blocks, read_unit, table_directory)
from libs.gpkg import GeoPackage
from libs.unpack import zlib_unit

ROOT = Path(__file__).resolve().parents[1]
NAVDB = ROOT / "temp/navdb"                 # may be a symlink to the disc's DB directory (read-only)
DEFAULT_DBS = (NAVDB / "DB_0",              # newer disc: DB_0 (+ DB_1 next to it)
               NAVDB / "carindb")           # reference NAV_DB CD: a single file
DEFAULT_DB = next((p for p in DEFAULT_DBS if p.is_file()), DEFAULT_DBS[0])
OUT_DIR = NAVDB if os.access(NAVDB, os.W_OK) else ROOT / "temp"

AREAS = {   # name: (min lon, min lat, max lon, max lat)
    "krakow": (19.6170, 49.9093, 20.2464, 50.1895),
    "warszawa": (20.85, 52.10, 21.27, 52.37),
    "malopolskie": (18.8404, 49.1646, 21.5254, 50.5196),
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
    tables = table_directory(f)
    h = head_bytes(f)
    siz1 = f.f1.seek(0, 2) if getattr(f, "f1", None) else 0
    f.f1 and f.f1.seek(0)
    blocks = (f.size + siz1) // f.block
    print(f"file      {f.name} ({f.size / 1e6:.0f} MB" +
          (f" + DB_1 {siz1 / 1e6:.0f} MB" if siz1 else "") + f", {blocks} blocks of {f.block})")
    print(f"release   {release}, CD {h[3]}")
    x0, y0, x1, y1 = struct.unpack_from(">4I", h, 0x34)
    print(f"extent    lon {lon(x0):.3f} .. {lon(x1):.3f}, lat {lat(y0):.3f} .. {lat(y1):.3f}")
    blk, ln = tables.get(0x11, ((0, 0), (1, 1), (1, 1)))[1]    # table 17: key / value texts
    t17 = read_unit(f, (blk << 8) | max(ln, 1))
    if t17[6] == 2:                                            # zlib units on the newer discs
        t17 = zlib_unit(t17, f.block)
    report = next((t.decode("latin1") for t in t17.split(b"\0") if b"name:" in t), "")
    for line in report.splitlines():     # "1.  name:   eeu_nok_nok_12q4_20130205p."
        key, _, value = line.partition(":")
        key = key.split(".", 1)[-1].strip()
        label = {"name": "data", "content": "content", "conversion date": "converted"}.get(key)
        if label and value.strip():
            print(f"{label:<9} {value.strip().rstrip('.')}")
    tb = tables.get(0x0B)                                       # table b: countries
    if not tb:
        print("countries (table b missing from the directory)")
    else:
        blk, ln = tb[1]
        u = read_unit(f, (blk << 8) | max(ln, 1))
        if u[6] == 2:
            u = zlib_unit(u, f.block)
        try:
            off, count = struct.unpack_from(">HH", u, 8)
            names = []
            for i in range(count):
                name, _, _, rec = struct.unpack_from(">HHHH", u, off + 8 * i)
                names.append(f"{cstring(u, name)} ({u[rec + 46:rec + 48].decode('latin1')})")
            print(f"countries {', '.join(names)}")
        except (struct.error, IndexError):
            print("countries (not readable on this disc generation)")
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
                   help=f"database: the DB_0 (or carindb) file, or the directory holding it; a DB_1"
                        f" next to DB_0 is picked up automatically (default: {DEFAULT_DB})")
    p.add_argument("-o", "--output", type=Path,
                   help=f"GeoPackage to write (default: {OUT_DIR.relative_to(ROOT)}/<area>.gpkg)")
    where = p.add_mutually_exclusive_group()
    where.add_argument("-a", "--area", choices=AREAS, help="a named area")
    where.add_argument("-b", "--bbox", metavar="LON0,LAT0,LON1,LAT1", help="a box in degrees")
    p.add_argument("-l", "--layers", default=",".join(LAYERS),
                   help="comma separated, from: " + ", ".join(LAYERS) + " (default: all)")
    p.add_argument("-i", "--info", action="store_true", help="show what is in the database and stop")
    p.add_argument("-q", "--quiet", action="store_true", help="no progress line, only summaries")
    args = p.parse_args()

    args.carindb = locate_db(p, args.carindb)
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
    if not args.output:
        args.output = OUT_DIR / f"{args.area or ('bbox' if args.box else 'carindb')}.gpkg"
    return args


def locate_db(p, path):
    """The database to open: a DB_0 / carindb file, or the directory holding it."""
    if path.is_file():
        return path
    if path.is_dir():
        for cand in (path / "DB_0", path / "carindb"):
            if cand.is_file():
                return cand
        p.error(f"no DB_0 or carindb in {path}")
    p.error(f"{path} not found; extract it from the map disc image first:\n"
            f"  python3 navdb/tools/extract_navdb.py")


def main():
    args = parse_args()
    try:
        db = open_database(args.carindb)
    except ValueError as e:
        sys.exit(str(e))
    with db:
        if args.info:
            info(db)
            return
        tables = table_directory(db)
        sizes, release = header_info(db)
        where = args.area or (args.bbox if args.box else "whole database")
        print(f"decoding {db.name} ({where}): {', '.join(args.layer_list)} -> {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        progress = Progress(args.quiet)
        gp = GeoPackage(args.output)
        try:
            if "roads" in args.layer_list:
                layers.parcels(db, gp, tables, args.box, sizes, release, progress)
            if "background" in args.layer_list:
                layers.background(db, gp, tables, args.box, sizes, release, progress)
            if "poi" in args.layer_list:
                layers.poi(db, gp, tables, args.box, progress)
            if "cities" in args.layer_list:
                layers.cities(db, gp, tables, args.box, sizes, release, progress)
        except KeyboardInterrupt:
            print("\ninterrupted; nothing written", file=sys.stderr)
            sys.exit(130)
        gp.close()
    print(f"done in {progress.clock()}: open {args.output} in QGIS (styles load automatically)")


if __name__ == "__main__":
    main()
