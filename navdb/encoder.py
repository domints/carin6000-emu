#!/usr/bin/env python3
"""OpenStreetMap -> CARiN / Carminat map disc (one country per disc).

Examples:
  navdb/encoder.py warszawa          Warsaw -> cd/carin_warszawa.img + .cue
  navdb/encoder.py polska            all of Poland
  navdb/encoder.py serbia            all of Serbia
  navdb/encoder.py beograd -t /tmp/carin    Belgrade, cache and work files in /tmp/carin

The OSM extract is downloaded from Geofabrik and kept in TEMP/osm (asked to refresh after 7
days, refreshed after 30); the database is built in TEMP/navdb/REGION/carindb. The original
carindb (temp/navdb/carindb) and disc are the templates for the metadata. Check the result with
  navdb/tests/check_db.py temp/navdb/REGION/carindb
  navdb/tests/check_search.py temp/navdb/REGION/carindb
"""
import argparse
import builtins
import gc
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "navdb/tools"))
import mkdisc  # noqa: E402
TABLES = {0: 1, 1: 0x1E, 2: 3, 3: 2}         # routing level -> table id
GRIDS = {0: 512, 1: 32, 2: 32, 3: 8}         # spatial index grid N per level (as the original)
BACKGROUND = {6: 32, 0x16: 32, 0x15: 32, 0x1C: 1, 0x14: 1, 0x1D: 1}     # table: index grid N
# the router's default speeds in m/s (rpmod data 0x18ca): form of way 0 (motorway), 3, others; by class
SPEEDS = {0: (36, 36, 36, 36, 7.5, 4.5, 3), 3: (28, 28, 16.5, 12, 7.5, 4.5, 3),
          -1: (24, 24, 16.5, 12, 7.5, 4.5, 3)}


class Context:
    """What the parcel builders ask: places, node codes and unit pointers."""

    def __init__(self, db, keys, top, country):
        self.db, self.keys, self.top = db, keys, top
        self.country = (country.name, country.number)

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
    gc.collect()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    builtins.print(*a, f"[{time.monotonic() - T0:.0f} s, {peak:.1f} GB]", **kw)


T0 = time.monotonic()


def main():
    p = argparse.ArgumentParser(prog="encoder.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                                description=__doc__.split("\n")[0],
                                epilog="\n".join(__doc__.split("\n")[2:]) + "\nStatus and limits: navdb/README.md.")
    p.add_argument("region", choices=countries.REGIONS, metavar="REGION",
                   help="what to encode: " + ", ".join(countries.REGIONS))
    p.add_argument("-t", "--temp", type=Path, default=ROOT / "temp",
                   help="folder for the OSM cache (TEMP/osm) and work files (TEMP/navdb/REGION); default: temp")
    p.add_argument("-o", "--output", type=Path, help="disc image .img (+ .cue next to it); default: cd/carin_REGION.img")
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
    iso, extract, box = countries.REGIONS[args.region]
    country = countries.COUNTRIES[iso]
    search.set_language(country.lang, country.street_prefix)
    osm = [osmsrc.fetch(extract, args.temp / "osm")]
    args.source = f"{extract} (geofabrik)"
    args.name = args.region
    args.country = country.name
    bbox = box or osmsrc.extent(osm)
    work = args.temp / "navdb" / args.region
    work.mkdir(parents=True, exist_ok=True)
    args.database = work / "carindb"
    args.output = args.output or ROOT / f"cd/carin_{args.region}.img"
    print(f"{args.region} ({country.name}): lon {bbox[0]:.3f}..{bbox[2]:.3f}, lat {bbox[1]:.3f}..{bbox[3]:.3f}")

    # network and places
    net = osmnet.load(osm, bbox, args.detail)
    places = osmplaces.Places(osm, bbox, country)
    roads = {}
    for e in net.edges:
        r = e.road
        if id(r) not in roads:
            mid = e.points()[len(e.points()) // 2]
            r.city, r.muni = places.city_of(mid)
            r.settlement = places.settlement_of(mid)
            r.name = osmplaces.street_name(r.name, country) or r.ref
            roads[id(r)] = r
    print(f"roads: {len(net.edges)} edges, {len(net.nodes)} nodes; "
          f"{len({(r.city, r.muni) for r in roads.values()})} cities, "
          f"{len({r.settlement for r in roads.values()} - {None})} settlements")

    # level 0 parcels and house numbers
    gbox = (*gps(bbox[0], bbox[1]), *gps(bbox[2], bbox[3]))
    leaves = parcelbuild.tile(net.edges, gbox)
    parcelbuild.nudge_edges(net.edges, leaves)
    by_level = {0: parcelbuild.clip(net.edges, leaves)}
    addresses = osmaddr.load(osm, bbox, country)
    numbered = osmaddr.assign(by_level[0], addresses)
    rules = osmturns.restrictions(args.temp / "osm" / f"{extract}-latest.osm.pbf")
    n_turns = osmturns.assign(by_level[0], parcelbuild.sorted_pieces, rules)
    n_addresses = len(addresses)
    del addresses                           # millions of tuples for a country

    # routing levels 1-3
    top, keep_by, inc_by = levels.tops(net.edges)
    for k in (1, 2, 3):
        edges = levels.join(net.edges, levels.CLASSES[k], keep_by[k], inc_by[k], levels.TOLERANCE[k],
                            net.nodes, top, k)
        lower = by_level[k - 1]
        if not edges or not lower:
            by_level[k] = []
            continue
        by_level[k] = parcelbuild.clip(edges, levels.upper_tiles(lower, edges, k))
        for child in lower:
            child.parent = next((pc for pc in by_level[k] if levels._inside(child.box, pc.box)), None)
            if child.parent:
                child.parent.children.append(child)
    travel_times(net.edges, top, by_level[0])
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
    ctx = Context(db, keys, top, country)
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
        index = spindex.IndexPart(GRIDS[k], [(pc.box.x, pc.box.y, pc.box.x + pc.box.size,
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
    for pc in by_level[0]:                  # lays the parcels out (segment offsets for table f)
        parcelbuild.build_level0(pc, ctx)
    for k in (1, 2, 3):                     # and the upper levels (edge point offsets their
        for pc in by_level[k]:              # neighbours read; the units are built in workers)
            levels.build_upper(pc, k, ctx)
    sums = {}
    for pc in by_level[0]:
        for piece in pc.pieces:
            rd = piece.road
            mid = piece.points[len(piece.points) // 2]
            for key in ((rd.settlement or rd.city, rd.city), (rd.city, None)):
                s_ = sums.setdefault(key, [0, 0, 0])
                s_[0] += mid[0]
                s_[1] += mid[1]
                s_[2] += 1

    def settlement_pos(name, city):
        s_ = sums.get((name, city)) or sums.get((name, None)) or sums.get((name, name))
        return (s_[0] // s_[2], s_[1] // s_[2]) if s_ else (0, 0)

    cities = search.collect(by_level[0], parcelbuild.sorted_pieces, settlement_pos)
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
    template_country = next(b4[r:r + 56] for i in range(count)
                            for n, _, _, r in [struct.unpack_from(">HHHH", b4, off + 8 * i)]
                            if b4[r + 46:r + 48] == country.template.encode())

    # POI: basic categories, listed under their gmina's city record and (airports, museums) the country
    pois = osmpoi.load(osm, bbox, country)
    osmpoi.place(pois, places, by_level[0], parcelbuild.sorted_pieces)
    poi = osmpoi.PoiTables(pois, {(c.name, c.muni) for c in cities}, country.name, country.lang)
    for c in cities:
        c.poi = poi.city_lists.get((c.name, c.muni), [])
    parcel_ptr = lambda pc: db.resolve(keys[id(pc)])
    search.add_tables(db, cities, (country.name, country.number, country.iso), template_country, dbwrite.Unit,
                      dbwrite.Table, parcel_ptr, lambda key: poi.list_ref(db.resolve, key), poi.country_lists)
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
    towns = [(a.name, ring) for a in places.levels[country.levels[2]] if (a.base or a.name) in town_names
             for ring in a.rings]
    shapes = osmbg.merge_lines(osmbg.clip_to_area(osmbg.load(osm, bbox, net.edges, towns), gbox))
    for level in range(6):
        tiles = osmbg.tiles(level, gbox, osmbg.level_shapes(shapes, level), parcelbuild.ORIGIN)
        bkeys = [("bg", level, n) for n in range(len(tiles))]
        units = [dbwrite.Unit(bkeys[n], lambda resolve, data=data, key=bkeys[n]:
                              osmbg.with_pointer(data, resolve(key)))
                 for n, (box, data) in enumerate(tiles)]
        db.add(dbwrite.Table(osmbg.TABLE[level], units,
                             spindex.IndexPart(BACKGROUND[osmbg.TABLE[level]], [(*box, bkeys[n]) for n, (box, _) in enumerate(tiles)])))
        print(f"background level {level}: {len(tiles)} units")
    del shapes

    # block 1: database info with this conversion (ISO 8601 UTC time, host)
    db.blocks[1] = lambda resolve: info_block(args, bbox, gbox)

    blocks = db.write(args.database, gbox)
    print(f"database: {args.database}: {blocks} blocks ({blocks * 2048 / 1e6:.1f} MB)")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mkdisc.build(args.database, args.output, args.template_disc, False)
    print(f"disc: {args.output} + .cue in {time.monotonic() - t0:.0f} s")
    print(f"test: tools/carin.py gui --state installed --cd {args.output.with_suffix('.cue')}")


if __name__ == "__main__":
    sys.exit(main())
