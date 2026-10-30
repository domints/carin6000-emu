#!/usr/bin/env python3
"""OpenStreetMap -> CARiN / Carminat map disc (a package: one or more countries per disc).

Examples:
  navdb/encoder.py poland            Poland -> cd/carin_poland.img + .cue
  navdb/encoder.py exyugoslavia      Slovenia ... Albania (8 countries) -> cd/carin_exyugoslavia.img
  navdb/encoder.py poland -t /tmp/carin    cache and work files in /tmp/carin

The OSM extracts (one per country) are downloaded from Geofabrik and kept in TEMP/osm (asked to
refresh after 7 days, refreshed after 30); the database is built in TEMP/navdb/PACKAGE/carindb.
The original carindb (temp/navdb/carindb) and disc are the templates for the metadata. Check the
result with
  navdb/tests/check_db.py temp/navdb/PACKAGE/carindb
  navdb/tests/check_search.py temp/navdb/PACKAGE/carindb
"""
import argparse
import builtins
from collections import Counter
import heapq
import resource
import sys
import time
from pathlib import Path

import datetime
import socket
import sqlite3
import struct

from libs import (countries, dbwrite, levels, osmaddr, osmbg, osmnet, osmplaces, osmpoi, osmsrc, osmturns, pack, parcelbuild,
                  parcelfmt, search, spindex)
from libs.carindb import TEXT_TABLES, header_info
from libs.osmnet import gps
from libs.par import pmap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "navdb/tools"))
import mkdisc  # noqa: E402
TABLES = {0: 1, 1: 0x1E, 2: 3, 3: 2}         # routing level -> table id
GRIDS = {0: 512, 1: 32, 2: 32, 3: 8}         # spatial index grid N per level (as the original)
BACKGROUND = {6: 128, 0x16: 128, 0x15: 128, 0x1C: 1, 0x14: 1, 0x1D: 1}   # table: index grid N (the original:
             # 32 for 6 / 16 / 15; 128 keeps our small units few per index cell, see osmbg.INDEX_UNITS)
# the router's default speeds in m/s (rpmod data 0x18ca): form of way 0 (motorway), 3, others; by class
SPEEDS = {0: (36, 36, 36, 36, 7.5, 4.5, 3), 3: (28, 28, 16.5, 12, 7.5, 4.5, 3),
          -1: (24, 24, 16.5, 12, 7.5, 4.5, 3)}


class Context:
    """What the parcel builders ask: places, node codes and unit pointers."""

    def __init__(self, db, keys, top, countries):
        self.db, self.keys, self.top = db, keys, top
        self.countries = {c.iso: (c.name, c.number) for c in countries}

    def country_of(self, road):
        return self.countries[road.country]

    def city_of(self, road):
        return road.city, road.muni

    def district_of(self, road):
        return road.settlement

    def code(self, point):
        return 3 - self.top.get(point, 0)

    def ptr(self, parcel):
        return self.db.resolve(self.keys[id(parcel)])

    def hn_ptr(self, parcel):
        key = self.keys.get(("hn", id(parcel)))
        return self.db.resolve(key) if key else 0


CONVERTED = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def conversion_stamp():
    """When and where this conversion ran: ISO 8601 UTC with seconds, host name."""
    return CONVERTED.strftime("%Y-%m-%dT%H:%M:%SZ"), socket.gethostname()


def info_block(args, bbox, gbox):
    """Block 1 (table 17): the template's layout with our conversion report and box."""
    with open(args.template, "rb") as t:
        t.seek(2048)
        d = bytearray(t.read(2048))
    when, host = conversion_stamp()
    area = args.name
    report = (f"\n1.  name:                     osm_{area.replace(' ', '_')}_{CONVERTED:%Y%m%dT%H%M%SZ}.\n"
              f"2.  content:                  {area}, {args.country} (openstreetmap)\n"
              f"3.  oem:                      osm\n"
              f"4.  supplier:                 openstreetmap contributors (odbl 1.0)\n"
              f"7.  conv tool version:        carin6000-emu navdb encoder\n"
              f"8.  conv input files:         {args.source}\n"
              f"9.  conversion date:          {when}\n"
              f"10. db release number:        34\n"
              f"11. conversion remarks:       map data (c) openstreetmap contributors\n"
              f"12. conversion by:            {host}\n"
              f"13. conditional access:       false\n\n").encode("latin1")
    off, = struct.unpack_from(">H", d, 0x32)
    d[off:] = bytes(len(d) - off)
    d[off:off + len(report)] = report
    struct.pack_into(">H", d, 0x34, len(report) + 1)
    struct.pack_into(">4I", d, 0x1C, *gbox)
    return bytes(d)


def travel_times(edges, top, parcels):
    """Header 0x60 / 0x64 / 0x68 of the level 0 parcels: mean time (0.1 s) from a parcel's nodes to
    the nearest node of level 3 / 2 / 1, with the router's default speeds."""
    back = {}
    for e in edges:
        t = 10 * e.length / SPEEDS.get(e.road.fow if e.road.fow in (0, 3) else -1)[e.road.cls]
        if e.road.oneway in (0, 1):
            back.setdefault(e.b, []).append((e.a, t))
        if e.road.oneway in (0, 2):
            back.setdefault(e.a, []).append((e.b, t))
    result = {}
    for k in (3, 2, 1):
        dist = {p: 0.0 for p, lv in top.items() if lv >= k}
        heap = [(0.0, p) for p in dist]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            for v, t in back.get(u, ()):
                if d + t < dist.get(v, 1e18):
                    dist[v] = d + t
                    heapq.heappush(heap, (d + t, v))
        result[k] = dist
    for pc in parcels:
        nodes = {p for piece in pc.pieces for p in (piece.points[0], piece.points[-1]) if p not in pc.borders}
        times = []
        for k in (3, 2, 1):
            ts = [result[k][p] for p in nodes if p in result[k]]
            times.append(round(sum(ts) / len(ts)) if ts else levels.INFINITE)
        pc.times = tuple(times)


def print(*a, **kw):
    """Progress lines with time and peak memory."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    builtins.print(*a, f"[{time.monotonic() - T0:.0f} s, {peak:.1f} GB]", **kw)


T0 = time.monotonic()


def main():
    p = argparse.ArgumentParser(prog="encoder.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                                description=__doc__.split("\n")[0],
                                epilog="\n".join(__doc__.split("\n")[2:]) + "\nStatus and limits: navdb/README.md.")
    p.add_argument("package", choices=countries.PACKAGES, metavar="PACKAGE",
                   help="what to encode: " + ", ".join(f"{k} ({' '.join(v)})" for k, v in countries.PACKAGES.items()))
    p.add_argument("-t", "--temp", type=Path, default=ROOT / "temp",
                   help="folder for the OSM cache (TEMP/osm) and work files (TEMP/navdb/PACKAGE); default: temp")
    p.add_argument("-o", "--output", type=Path, help="disc image .img (+ .cue next to it); default: cd/carin_PACKAGE.img")
    p.add_argument("--no-compress", action="store_true", help="store the parcels uncompressed")
    p.add_argument("--detail", choices=("normal", "full"), default="normal",
                   help="normal (default): without tracks and unnamed service roads; full: all OSM roads")
    p.add_argument("--template", type=Path, default=ROOT / "temp/navdb/carindb", help=argparse.SUPPRESS)
    p.add_argument("--template-disc", type=Path, default=ROOT / "cd/carin_maps_pl_2012_2013.img",
                   help=argparse.SUPPRESS)
    args = p.parse_args()
    if not args.template.is_file():
        p.error(f"template carindb {args.template} not found: run navdb/tools/extract_navdb.py first")
    if not args.template_disc.is_file():
        p.error(f"template disc {args.template_disc} not found (the original map disc)")
    t0 = time.monotonic()
    package = [countries.COUNTRIES[iso] for iso in countries.PACKAGES[args.package]]
    by_iso = {c.iso: c for c in package}
    extracts = list(dict.fromkeys(c.extract for c in package))
    osm = [osmsrc.fetch(x, args.temp / "osm") for x in extracts]
    args.source = ", ".join(extracts) + " (geofabrik)"
    args.name = args.package
    args.country = ", ".join(c.name for c in package)
    atlas = osmplaces.Atlas(osm, package)
    bbox = atlas.bbox
    work = args.temp / "navdb" / args.package
    work.mkdir(parents=True, exist_ok=True)
    args.database = work / "carindb"
    args.output = args.output or ROOT / f"cd/carin_{args.package}.img"
    print(f"{args.package} ({args.country}): lon {bbox[0]:.3f}..{bbox[2]:.3f}, lat {bbox[1]:.3f}..{bbox[3]:.3f}")

    # network and places: a road (OSM way) belongs to the country at its middle; roads outside
    # every country of the package are left out
    net = osmnet.load(osm, bbox, args.detail)
    roads, mids = {}, []
    for e in net.edges:
        r = e.road
        if id(r) not in roads:
            roads[id(r)] = r
            mids.append(e.points()[len(e.points()) // 2])
    step = 20000                            # country, city, settlement of every road, in worker processes
    def where(chunk):                       # city_of caches per cell: a fresh cache per chunk
        atlas.clear()                       # keeps the result independent of the workers
        out = []
        for p in chunk:
            c = atlas.country_at(p)
            pl = c and atlas.places[c.iso]
            out.append((c.iso, *pl.city_of(p), pl.settlement_of(p)) if c else None)
        return out
    found = [w for part in pmap(where, [mids[i:i + step] for i in range(0, len(mids), step)], 2) for w in part]
    for r, w in zip(roads.values(), found):
        if w:
            r.country, r.city, r.muni, r.settlement = w
            r.name = osmplaces.street_name(r.name, by_iso[r.country]) or r.ref
    del mids, found
    outside = sum(1 for e in net.edges if not e.road.country)
    net = osmnet.Network([e for e in net.edges if e.road.country])
    for i, e in enumerate(net.edges):
        for pt in (e.a, e.b):
            net.nodes.setdefault(pt, []).append(i)
    print(f"roads: {len(net.edges)} edges ({outside} outside the countries left out), {len(net.nodes)} nodes; "
          f"{len({(r.country, r.city, r.muni) for r in roads.values() if r.country})} cities, "
          f"{len({(r.country, r.settlement) for r in roads.values() if r.settlement and r.country})} settlements")
    del roads

    # level 0 parcels and house numbers; shapes simplified first (lengths stay those of the OSM shape)
    step = 20000
    shapes = [s for part in pmap(lambda chunk: [levels.simplify(e.points(), levels.TOLERANCE[0])[1:-1] for e in chunk],
                                 [net.edges[i:i + step] for i in range(0, len(net.edges), step)], 2) for s in part]
    for e, s in zip(net.edges, shapes):
        e.shape = s
    del shapes
    gbox = (*gps(bbox[0], bbox[1]), *gps(bbox[2], bbox[3]))
    leaves = parcelbuild.tile(net.edges, gbox)
    parcelbuild.nudge_edges(net.edges, leaves)
    by_level = {0: parcelbuild.clip(net.edges, leaves, record=True)}
    addresses = osmaddr.load(osm, bbox, package[0])      # one street rule per package (countries.py)
    numbered = osmaddr.assign(by_level[0], addresses)
    rules = list(dict.fromkeys(r for x in extracts for r in osmturns.restrictions(args.temp / "osm" / f"{x}-latest.osm.pbf")))
    n_turns = osmturns.assign(by_level[0], parcelbuild.sorted_pieces, rules)
    n_addresses = len(addresses)
    del addresses                           # millions of tuples for a country

    # routing levels 1-3
    top, keep_by, inc_by = levels.tops(net.edges)
    fixed = {pt for pc in by_level[0] for pt in pc.borders}     # upper edge points = level 0 ones
    for k in (1, 2, 3):
        edges = levels.join(net.edges, levels.CLASSES[k], keep_by[k], inc_by[k], levels.TOLERANCE[k],
                            net.nodes, top, k, fixed)
        lower = by_level[k - 1]
        if not edges or not lower:
            by_level[k] = []
            continue
        by_level[k] = parcelbuild.clip(edges, levels.upper_tiles(lower, edges, k), fixed)
        for child in lower:
            child.parent = next((pc for pc in by_level[k] if levels._inside(child.box, pc.box)), None)
            if child.parent:
                child.parent.children.append(child)
    travel_times(net.edges, top, by_level[0])
    bg_roads = [e for e in net.edges if e.road.cls <= 2 and e.road.kind != 5]     # for the background
    del net, keep_by, inc_by, edges, fixed   # the network lives on in the parcels
    for k, pcs in by_level.items():
        print(f"level {k}: {len(pcs)} parcels, {sum(len(pc.pieces) for pc in pcs)} segments, "
              f"{sum(len(pc.borders) for pc in pcs) // 2} border crossings"
              + (f", {n_addresses} addresses on {numbered} segments, {n_turns} of {len(rules)} turn "
                 f"restrictions" if k == 0 else ""))

    # tables
    db = dbwrite.Database(args.template)
    keys = {}
    for k, pcs in by_level.items():
        for n, pc in enumerate(pcs):
            keys[id(pc)] = (f"p{k}", n)
    ctx = Context(db, keys, top, package)
    with open(args.template, "rb") as t:
        packer = pack.Packer(*header_info(t), TEXT_TABLES)

    def compress(image):
        """Level 0 parcels compressed like the original (about 2x); kept as they are when that
        does not save a block."""
        if args.no_compress:
            return image
        return packer.parcel(image) or image
    for k, pcs in by_level.items():
        if k == 0:
            build = lambda pc: compress(parcelfmt.write(parcelbuild.build_level0(pc, ctx)))
        else:
            build = lambda pc, k=k: parcelfmt.write(levels.build_upper(pc, k, ctx))
        units = [dbwrite.Unit(keys[id(pc)], lambda resolve, pc=pc, build=build: build(pc)) for pc in pcs]
        grid = max(GRIDS[k], spindex.EXTENT // (64 * min((pc.box.size for pc in pcs), default=spindex.EXTENT)))
        index = spindex.IndexPart(grid, [(pc.box.x, pc.box.y, pc.box.x + pc.box.size,
                                              pc.box.y + pc.box.size, keys[id(pc)]) for pc in pcs])
        db.add(dbwrite.Table(TABLES[k], units, index))
    hn_units = []
    for n, pc in enumerate(by_level[0]):
        if any(getattr(piece, "hn", None) for piece in pc.pieces):
            keys[("hn", id(pc))] = ("hn", n)
            hn_units.append(dbwrite.Unit(("hn", n), lambda resolve, pc=pc, n=n: osmaddr.unit(
                resolve(keys[id(pc)]), resolve(("hn", n)), parcelbuild.sorted_pieces(pc))))
    db.add(dbwrite.Table("hn", hn_units))

    # search: cities and streets (positions = middle of their segments)
    # lay the parcels out (segment offsets for table f, edge point offsets the neighbours read),
    # in workers that hand the offsets back; the units themselves are built later, in workers too
    def lay_out(job):
        k, pc = job
        if k == 0:
            parcelbuild.build_level0(pc, ctx)
        else:
            levels.build_upper(pc, k, ctx)
        return pc.offsets, pc.seg_base
    jobs = [(k, pc) for k in (0, 1, 2, 3) for pc in by_level[k]]
    for (_, pc), (offsets, base) in zip(jobs, pmap(lay_out, jobs)):
        pc.offsets, pc.seg_base = offsets, base
    del jobs
    sums = {}
    for pc in by_level[0]:
        for piece in pc.pieces:
            rd = piece.road
            mid = piece.points[len(piece.points) // 2]
            for key in ((rd.country, rd.settlement or rd.city, rd.city), (rd.country, rd.city, None)):
                s_ = sums.setdefault(key, [0, 0, 0])
                s_[0] += mid[0]
                s_[1] += mid[1]
                s_[2] += 1

    def settlement_pos(iso, name, city):
        s_ = sums.get((iso, name, city)) or sums.get((iso, name, None)) or sums.get((iso, name, name))
        return (s_[0] // s_[2], s_[1] // s_[2]) if s_ else (0, 0)

    cities = search.collect(by_level[0], parcelbuild.sorted_pieces, settlement_pos, by_iso)
    for c in cities:                        # destination segment: the city's segment nearest its middle
        best = None
        for _, _, _, items in c.entries:
            for it in items:
                pc = it.parcel
                piece = parcelbuild.sorted_pieces(pc)[it.seg_index]
                p0 = piece.points[0]
                dist = abs(p0[0] - c.pos[0]) * 0.62 + abs(p0[1] - c.pos[1])
                if best is None or dist < best[0]:
                    best = (dist, (pc, it.seg_index))
        c.seg = best[1] if best else None
    cities = [c for c in cities if c.seg]
    with open(args.template, "rb") as t:
        t.seek(4 * 2048)
        b4 = t.read(2048)
    off, count = struct.unpack_from(">HH", b4, 8)
    template_records = {b4[r + 46:r + 48].decode(): b4[r:r + 56] for i in range(count)
                        for n, _, _, r in [struct.unpack_from(">HHHH", b4, off + 8 * i)]}

    # POI: basic categories, listed under their gmina's city record and (airports, museums) the country
    pois = osmpoi.load(osm, bbox, package[0])
    osmpoi.place(pois, atlas, by_level[0], parcelbuild.sorted_pieces)
    poi = osmpoi.PoiTables(pois, {(c.country.iso, c.name, c.muni) for c in cities})
    for c in cities:
        c.poi = poi.city_lists.get((c.country.iso, c.name, c.muni), [])
    parcel_ptr = lambda pc: db.resolve(keys[id(pc)])
    search.add_tables(db, cities, [(c, template_records[c.template], poi.country_lists.get(c.iso, []))
                                   for c in package], dbwrite.Unit, dbwrite.Table, parcel_ptr,
                      lambda key: poi.list_ref(db.resolve, key))
    print(f"search: {len(cities)} cities, {sum(len(c.entries) for c in cities)} street entries")
    n11 = len(poi.units)
    db.add(dbwrite.Table(0x11, [dbwrite.Unit(("p11", i), lambda resolve, i=i: poi.name_unit(
        i, resolve(("p11", i)), resolve(("p11", i + 1)) if i + 1 < n11 else 0, resolve(("p11", i - 1)) if i else 0,
        parcel_ptr)) for i in range(n11)]))
    db.add(dbwrite.Table(0x12, [dbwrite.Unit(("t12", i), lambda resolve, i=i: poi.trie_unit(i, resolve))
                                for i in range(len(poi.trie_units))]))
    root = parcelbuild.aligned_root(gbox)
    poi_tiles = poi.tiles(root) or [((root.x, root.y, root.x + (1 << 21), root.y + (1 << 21)), [])]
    db.add(dbwrite.Table(7, [dbwrite.Unit(("poi", n), lambda resolve, n=n, box=box, items=items:
                                          poi.point_unit(box, items, resolve(("poi", n)), resolve))
                             for n, (box, items) in enumerate(poi_tiles)],
                         spindex.IndexPart(256, [(*box, ("poi", n)) for n, (box, _) in enumerate(poi_tiles)])))
    print(f"poi: {len(poi.pois)} of {len(pois)} in {len(poi.lists)} lists, {len(poi_tiles)} point units")

    # background from OSM: 6 levels; TMC tables stay empty (not used, nothing copied)
    town_names = {osmnet.fold(n) for _, n in osmsrc.rows(osm,
        "SELECT p.osm_id, p.name FROM points p JOIN rtree_points_geom r ON p.fid = r.id WHERE r.maxx >= ? AND "
        "r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND p.place IN ('city', 'town')",
        (bbox[0], bbox[2], bbox[1], bbox[3])) if n}
    towns = [(a.name, ring) for c in package for a in atlas.places[c.iso].levels[c.levels[2]]
             if (a.base or a.name) in town_names for ring in a.rings]
    shapes = osmbg.load(osm, bbox, bg_roads, towns)
    def place_of(p):                        # the village / town district a built-up area lies in
        c = atlas.country_at(p)
        pl = c and atlas.places[c.iso]
        return pl and (pl.settlement_of(p) or pl.city_of(p)[0].replace("?", "") or None)
    atlas.clear()
    osmbg.name_builtup(shapes, place_of, {n for n, _ in towns})
    shapes = osmbg.merge_lines(osmbg.clip_to_area(shapes, gbox))
    for level in range(6):
        dropped = Counter()
        tiles = osmbg.tiles(level, gbox, osmbg.level_shapes(shapes, level), parcelbuild.ORIGIN, dropped)
        bkeys = [("bg", level, n) for n in range(len(tiles))]
        units = [dbwrite.Unit(bkeys[n], lambda resolve, data=data, key=bkeys[n]:
                              osmbg.with_pointer(data, resolve(key)))
                 for n, (box, data) in enumerate(tiles)]
        db.add(dbwrite.Table(osmbg.TABLE[level], units,
                             spindex.IndexPart(BACKGROUND[osmbg.TABLE[level]], [(*box, bkeys[n]) for n, (box, _) in enumerate(tiles)])))
        print(f"background level {level}: {len(tiles)} units, {dropped['shapes']} shapes left out of full "
              f"units ({dropped['roads']} roads)")
    del shapes

    # block 1: database info with this conversion (ISO 8601 UTC time, host)
    db.blocks[1] = lambda resolve: info_block(args, bbox, gbox)

    blocks = db.write(args.database, gbox)
    print(f"database: {args.database}: {blocks} blocks ({blocks * 2048 / 1e6:.1f} MB)")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mkdisc.build(args.database, args.output, args.template_disc, False)
    print(f"disc: {args.output} + .cue in {time.monotonic() - t0:.0f} s")
    if len(package) > 1:                    # what each country takes, by its share of the level 0 segments
        segs = Counter(piece.road.country for pc in by_level[0] for piece in pc.pieces)
        n_city = Counter(c.country.iso for c in cities)
        n_poi = Counter(p.country.iso for p in poi.pois)
        for c in package:
            share = segs[c.iso] / max(1, sum(segs.values()))
            print(f"  {c.iso} {c.name}: {segs[c.iso]} segments, {n_city[c.iso]} cities, {n_poi[c.iso]} poi, "
                  f"~{share * blocks * 2048 / 1e6:.0f} MB")


if __name__ == "__main__":
    sys.exit(main())
