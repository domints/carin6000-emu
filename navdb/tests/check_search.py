#!/usr/bin/env python3
"""Walks the address search of a carindb the way the device does: country (block 4) -> city trie
(e) -> city (d) -> street trie (10) -> street entry (f) -> items -> parcel segments, and the
POI: city and country category lists -> trie (12) -> name entries and details (11) -> access
segment; table 7 points -> their name entries. Checks every step (docs/format.md sections 7, 8).

usage: check_search.py [carindb] [--country pl] [--cities N]   (default: temp/navdb/warszawa/carindb)
"""
import argparse
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from libs.carindb import TEXT_TABLES, cstring, header_info, read_unit, table_directory, units as table_units
from libs.unpack import Unpacker

ROOT = Path(__file__).resolve().parents[2]


def w(d, o):
    return struct.unpack_from(">H", d, o)[0]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("carindb", nargs="?", type=Path, default=ROOT / "temp/navdb/warszawa/carindb")
    p.add_argument("--country", help="ISO code (default: the first country)")
    p.add_argument("--cities", type=int, default=0, help="check only the first N cities (0 = all)")
    args = p.parse_args()
    f = open(args.carindb, "rb")
    sizes, release = header_info(f)
    unpacker = Unpacker(sizes, release, TEXT_TABLES)
    units, parcels = {}, {}

    def unit(ptr):
        if ptr not in units:
            units[ptr] = read_unit(f, ptr)
        return units[ptr]

    def parcel(ptr):
        if ptr not in parcels:
            if len(parcels) > 300:
                parcels.clear()
            parcels[ptr] = bytes(unpacker.unpack(read_unit(f, ptr)))
        return parcels[ptr]

    res = {k: Counter() for k in ("block 0 country trie -> countries", "trie prefix", "city segment is a segment", "street item -> segments of that street",
                                  "item numbers in the segments' ranges", "poi list -> names of that category",
                                  "poi detail in its unit", "poi access -> a segment", "poi point -> its name entry")}

    def poi_list(d, off, count):
        """Category records (12 B) -> trie -> table 11 entries; checks the details."""
        for k in range(count):
            t12, o12, n12, cat, _ = struct.unpack_from(">IHHHH", d, off + 12 * k)
            names = []
            walk(t12, o12, n12, "", names)
            res["poi list -> names of that category"][bool(names)] += 1
            for g, entry, _ in names:
                rec = entry[3]
                ok = 0x30 <= rec and rec + 40 <= len(g)
                res["poi detail in its unit"][ok] += 1
                if not ok:
                    continue
                a_off, a_n = struct.unpack_from(">HH", g, rec + 8)
                for a in range(a_n):
                    pp, so, side = struct.unpack_from(">IHH", g, a_off + 8 * a)
                    dd = parcel(pp)
                    s4, c4 = w(dd, 0x18), w(dd, 0x1a)
                    res["poi access -> a segment"][s4 <= so < s4 + 32 * c4 and (so - s4) % 32 == 0 and side < 2] += 1

    def walk(ptr, off, count, prefix, out):
        t = unit(ptr)
        for j in range(count):
            q, ch, leaf, o, n, _ = struct.unpack_from(">IBBHHH", t, off + 12 * j)
            pre = prefix + chr(ch)
            if leaf:
                g = unit(q)
                for e in range(n):
                    entry = struct.unpack_from(">HHHH", g, o + 8 * e)
                    name = cstring(g, entry[0]) or ""
                    res["trie prefix"][name.startswith(pre.rstrip()) or len(name) < len(pre)] += 1
                    out.append((g, entry, name))
            else:
                walk(q, o, n, pre, out)

    # block 0 -> country trie (block 3) -> countries (block 4), as the device starts
    f.seek(0)
    h = f.read(2048)
    countries = []
    for o in (0x0C, 0x44):
        c_ptr, c_off, c_n = struct.unpack_from(">IHH", h, o)
        found = []
        walk(c_ptr, c_off, c_n, "", found)
        res["block 0 country trie -> countries"][bool(found) and all(g[0:4] == b"\0\0\4\1" for g, _, _ in found)] += 1
        countries = countries or found
    print("countries:", ", ".join(name for _, _, name in countries))
    for b4, entry, _ in countries:
        rec = entry[3]
        args.country = args.country or b4[rec + 46:rec + 48].decode()
        if b4[rec + 46:rec + 48].decode() != args.country:
            continue
        poi_list(b4, w(b4, rec + 24), w(b4, rec + 26))
        e_ptr, e_off, e_n = struct.unpack_from(">IHH", b4, rec)
        cities = []
        walk(e_ptr, e_off, e_n, "", cities)
        print(f"country {args.country}: {len(cities)} city entries")
        for k, (g, entry, cname) in enumerate(cities):
            if args.cities and k >= args.cities:
                break
            r = entry[3]
            t10, o10, n10, s3, n3, cp, co = struct.unpack_from(">IHHHHIH", g, r)
            poi_list(g, s3, n3)
            if cp:
                d = parcel(cp)
                s4, c4 = w(d, 0x18), w(d, 0x1a)
                res["city segment is a segment"][s4 <= co < s4 + 32 * c4 and (co - s4) % 32 == 0] += 1
            streets = []
            if n10:
                walk(t10, o10, n10, "", streets)
            for sg, se, sname in streets:
                run = se[3]
                item_off, n_items = w(sg, run), sg[run + 2]
                words = set(sname.split())
                for it in range(n_items):
                    io = item_off + 24 * it
                    nums = struct.unpack_from(">4H", sg, io + 8)
                    pp, so, sc = struct.unpack_from(">IHH", sg, io + 16)
                    d = parcel(pp)
                    ts = w(d, 8 + 56)
                    ok = True
                    for s in range(sc):
                        seg = so + 32 * s
                        prec = w(d, seg + 26)
                        nm = cstring(d, w(d, prec)) if prec and ts else None
                        ok &= nm is not None and set(nm.split()) == words
                    res["street item -> segments of that street"][ok] += 1
    # table 7: every point names an entry whose detail lies at the point
    tables = table_directory(f)
    (_, _), (first, _), (last, _) = tables[7]
    for b, length, _ in table_units(f, first, last) if first else ():
        f.seek(b * 2048)
        u = f.read(length * 2048)
        off, count = struct.unpack_from(">HH", u, 8)
        x0, y0 = struct.unpack_from(">ii", u, 0x10)
        for i in range(count):
            ptr, noff, x, y = struct.unpack_from(">IHHH", u, off + 28 * i)
            g = unit(ptr)
            rec = w(g, noff + 6)
            px, py = struct.unpack_from(">ii", g, rec)
            res["poi point -> its name entry"][abs(x0 + 64 * x - px) < 128 and abs(y0 + 64 * y - py) < 128] += 1
    failed = 0
    for name, c in res.items():
        if c:
            status = "ok" if not c[False] else "FAILED"
            failed += bool(c[False])
            print(f"{status:6} {name}: {c[True]} passed, {c[False]} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
