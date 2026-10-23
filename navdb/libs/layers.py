"""Decoding of the map layers into a GeoPackage (used by ../decoder.py). Grows with
../docs/format.md.

Layers:
  parcels  routing parcels of every level: bounding box, first block, length in blocks, parent
  roads    the segment records of the parcels (slot 4, type 08) as lines through their end points
           and shape points (slot 7), for every routing level (level 0 = table 1, the full network;
           1, 2, 3 = tables 1e, 3, 2, each with only the more important roads): street name,
           district, city, country (segment +26 -> slot 2 -> slot 1 -> slot 0), road class (FRC,
           byte +16 bits 0-3), kind (+16 bits 4-6; 5 = not routable), length in metres (+12),
           headings at both ends (+14/+15, 256 steps), one-way (+11 bits 4-5: 0 both ways, 1 only
           start -> end, 2 only end -> start, 3 closed both ways), form of way (+11 bits 0-3),
           figure (+17 low: 2 square, 6 roundabout …), access (+17 high), paved (+10 bit 7),
           access code (+28 bits 4-6), prohibited turns (slot 10 count), ferry minutes (slot 12
           type 5), house numbers left / right (kind 4 units), raw bytes
  areas    background areas (tables 6, 16, 15, 1c, 14, 1d = levels 0-5, finer to coarser, zoom
           ranges in the block 2 index directory; slot 1 records): type (slot 0 groups), name,
           area in m2 (+4)
  overview_roads  the generalised road network of the same tables (slot 2 records), name = road number
  poi      table 7 units (28-byte records): position (16-bit steps of 64 GPS units from the unit box),
           category (+10), brand (+12, text in the unit), name (+0 unit pointer, +4 offset of an
           8-byte name entry in table 11); street, house number, district, city, postcode and phone
           from the table 11 detail record
  cities   table d city records: point at the start of the city's segment (+12/+16), name,
           municipality, language code, other spellings, number of street trie root nodes (trie_roots)

Every function takes `progress`, an object with step(text, done, total) and finish(text).
"""
import struct

from .carindb import (GPS_UNIT, HN_NONE, POINT_STEP, TEXT_TABLES, UnitCache, block_size, cstring,
                      lat, lon, read_blocks, read_unit, units)
from .unpack import Unpacker

ROUTING_LEVELS = ((1, 0), (0x1E, 1), (3, 2), (2, 3))


def parcels(f, gp, tables, bbox, sizes, release, progress):
    """Table 1. The parcel box is the record at 0x44 (after the 8-byte unit header, type 05, and
    the 60-byte parcel header, type 11): min lon, min lat, max lon, max lat. Points inside a
    parcel are steps of 64 GPS units (~1 m) from the box corner (0..512 in the smallest parcels)."""
    gp.layer("parcels", "POLYGON", [("level", "INTEGER"), ("block", "INTEGER"), ("blocks", "INTEGER"),
                                    ("compressed", "INTEGER"), ("parent", "INTEGER")])
    gp.layer("roads", "LINESTRING", [("level", "INTEGER"), ("block", "INTEGER"), ("segment", "INTEGER"), ("name", "TEXT"),
                                     ("district", "TEXT"), ("city", "TEXT"), ("country", "TEXT"),
                                     ("class", "INTEGER"), ("kind", "INTEGER"), ("oneway", "INTEGER"),
                                     ("length_m", "INTEGER"),
                                     ("heading_a", "REAL"), ("heading_b", "REAL"),
                                     ("hn_left_from", "INTEGER"), ("hn_left_to", "INTEGER"),
                                     ("hn_right_from", "INTEGER"), ("hn_right_to", "INTEGER"),
                                     ("hn_scheme", "INTEGER"), ("fow", "INTEGER"), ("figure", "INTEGER"),
                                     ("access", "INTEGER"), ("paved", "INTEGER"), ("access_code", "INTEGER"),
                                     ("no_turns", "INTEGER"), ("ferry_min", "INTEGER"),
                                     ("b10", "INTEGER"), ("b11", "INTEGER"), ("b16", "INTEGER"), ("b17", "INTEGER")])
    unpacker = Unpacker(sizes, release, TEXT_TABLES, block_size(f))
    for tid, level in ROUTING_LEVELS:
        parcel_level(f, gp, tables.get(tid, ((0, 0), (0, 0), (0, 0))), level, bbox, sizes, unpacker, progress)


def parcel_level(f, gp, table, level, bbox, sizes, unpacker, progress):
    """One routing level: parcels and their segments. Word 0x58: the parcel of the level above
    (unit pointer, 0 at the top)."""
    (_, _), (data, _), (end, _) = table
    n = roads = 0
    if not data:
        return
    for b, length, head in units(f, data, end):
        progress.step(f"roads, level {level}", b - data, end - data)
        # raw and pbp units keep the 116-byte parcel header (never compressed) on disk: the box
        # allows a cheap bbox pre-filter before unpacking; only zlib units (+6 == 2) need the
        # unpacked image for it
        if head[6] != 2:
            hx1, hy1, hx2, hy2 = struct.unpack_from(">4I", head, 0x44)
            if bbox and (lon(hx2) < bbox[0] or lon(hx1) > bbox[2]
                         or lat(hy2) < bbox[1] or lat(hy1) > bbox[3]):
                continue
        try:
            d = unpacker.unpack(read_blocks(f, b, length))
        except (ValueError, struct.error, IndexError, KeyError):
            continue                      # a unit that will not unpack: skip, like old ones did
        if d is None:
            continue
        x1, y1, x2, y2 = struct.unpack_from(">4I", d, 0x44)   # the box of the *unpacked* unit:
        box = (lon(x1), lat(y1), lon(x2), lat(y2))           # zlib units only have it there
        if bbox and (box[2] < bbox[0] or box[0] > bbox[2] or box[3] < bbox[1] or box[1] > bbox[3]):
            continue
        ring = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]
        gp.add("parcels", ring, (level, b, length, head[6], struct.unpack_from(">I", d, 0x58)[0] >> 8))
        n += 1
        w = lambda o: struct.unpack_from(">H", d, o)[0]
        w = lambda o: struct.unpack_from(">H", d, o)[0]
        sx = sy = POINT_STEP * GPS_UNIT
        text_start = w(8 + 0x38)

        def text(o):
            """A name in the text area (0 = none)."""
            if not o or o < text_start or o >= len(d):
                return None
            e = d.find(b"\0", o)
            return d[o:e].decode("latin1") if e > o else None

        def place(o):
            """Slot 0..2 records (type 0x40): name, second name, parent record."""
            if not o or o + 6 > len(d):
                return None, None, 0
            return text(w(o)), text(w(o + 2)), w(o + 4)
        seg_off, seg_n = w(8 + 0x10), w(8 + 0x12)
        # dbq FUN_00001890: type 08 (32 bytes) in kind 0 units, type 09 (26 bytes, no name
        # reference at +26) in the routing levels
        rs = sizes[0x08] if w(4) == 0 else sizes[0x09]
        seg_n = max(0, min(seg_n, (len(d) - seg_off) // rs))   # defensive: broken slot counts
        # per-segment house numbers (rpmod FUN_000151cc): word 0x54 of a level 0 parcel points to a
        # kind 4 unit outside the table directory (+12 = this parcel), 10-byte records from 0x10,
        # one per segment: left from, right from, left to, right to (sides for travel start ->
        # end, from = at the start node; 32767 = none), scheme (0 none, 1, 2)
        hn_unit, = struct.unpack_from(">I", d, 0x54) if level == 0 else (0,)
        if hn_unit:
            hu = read_unit(f, hn_unit)
            if len(hu) < 0x10:             # defensive: pointer into a gap / outside the database
                hn_unit = 0
        hn_n = (len(hu) - 0x10) // 10 if hn_unit else 0    # one 10 B record per segment
        for i in range(seg_n):
            r = seg_off + i * rs
            numbers = [None] * 5
            if i < hn_n:
                lf, rf, lt, rt, scheme = struct.unpack_from(">5H", hu, 0x10 + 10 * i)
                numbers = [None if v == HN_NONE else v for v in (lf, lt, rf, rt)] + [scheme]
            a, c = w(r), w(r + 2)
            if not (0 < a < len(d) - 4 and 0 < c < len(d) - 4):
                continue
            # shape points between the end points (dbq FUN_000149ba): slot 7 records (type 0x0c,
            # x, y, flags) from this segment's +4 up to the next segment's +4
            s7_end = w(8 + 0x1C) + sizes[0x0C] * w(8 + 0x1E)
            s7_end = min(s7_end, len(d) - sizes[0x0C] + 1)     # defensive: past the buffer end
            nxt = w(r + rs + 4) if i + 1 < seg_n else s7_end
            shape = range(w(r + 4), min(nxt, s7_end), sizes[0x0C]) if w(r + 4) else ()
            pts = [(box[0] + w(o) * sx, box[1] + w(o + 2) * sy) for o in (a, *shape, c)]
            street, district, parent = place(w(r + 26)) if rs >= 28 else (None, None, 0)
            city_a, city_b, parent = place(parent)
            country, _, _ = place(parent)
            # prohibited turns (slot 10, rpmod FUN_0001d28a) and attributes (slot 12, FUN_0001d2e4):
            # a segment's entries run up to the next segment's start word
            last = i + 1 == seg_n
            turns_end = w(8 + 0x28) + sizes[0x14] * w(8 + 0x2A) if last else w(r + rs + 18)
            attrs_end = w(8 + 0x30) + sizes[0x15] * w(8 + 0x32) if last else w(r + rs + 20)
            ferry = None
            for o in range(w(r + 20), min(attrs_end, len(d) - sizes[0x15] + 1), sizes[0x15]):
                if w(o) == 5:
                    ferry = w(o + 2)
            gp.add("roads", pts, (level, b, i, street, district, city_a or city_b, country,
                                  d[r + 16] & 0x0F, (d[r + 16] >> 4) & 7, (d[r + 11] >> 4) & 3, w(r + 12),
                                  d[r + 14] * 360 / 256, d[r + 15] * 360 / 256, *numbers,
                                  d[r + 11] & 0x0F, d[r + 17] & 0x0F, d[r + 17] >> 4, d[r + 10] >> 7,
                                  (w(r + 28) >> 4) & 7 if rs >= 30 else None,
                                  max(0, (turns_end - w(r + 18)) // sizes[0x14]), ferry,
                                  d[r + 10], d[r + 11], d[r + 16], d[r + 17]))
            roads += 1
    progress.finish(f"roads, level {level}: {n} parcels, {roads} segments")


# POI categories (record +10), named from the names found under each code around Warsaw; codes
# not seen there are left unnamed.
POI_CATEGORIES = {
    11: "dealer samochodowy", 12: "stacja paliw", 13: "wypożyczalnia samochodów", 14: "parking",
    15: "park & ride", 20: "atrakcja turystyczna", 21: "hotel / nocleg", 22: "restauracja / kawiarnia",
    23: "bank", 24: "dom kultury", 25: "biblioteka", 26: "sąd / prokuratura", 29: "ambasada",
    30: "bankomat", 31: "informacja turystyczna", 32: "muzeum", 33: "teatr / sala koncertowa",
    35: "obiekt sportowy", 36: "kościół", 37: "cmentarz", 38: "tor / karting", 39: "park / rezerwat",
    40: "centrum wystawowe", 41: "szpital", 42: "policja", 43: "urząd", 44: "poczta",
    45: "przychodnia", 46: "apteka", 47: "sklep / centrum handlowe", 48: "miejscowość",
    49: "kino", 50: "pole golfowe", 51: "stacja kolejowa", 52: "lotnisko", 54: "dworzec autobusowy",
    56: "szkoła / przedszkole", 57: "rozrywka / nocne życie", 59: "serwis samochodowy",
    61: "firma / zakład",
}


AREA_TYPES = {1: "woda", 3: "las / park", 5: "zabudowa", 6: "cmentarz", 8: "wyspa"}
BACKGROUND_LEVELS = ((6, 0), (0x16, 1), (0x15, 2), (0x1C, 3), (0x14, 4), (0x1D, 5))


def background(f, gp, tables, bbox, sizes, release, progress):
    """Tables 6, 16, 15, 1c, 14, 1d (unit kinds 0x16, 0x15, 0x1c, 0x14, 0x1d, 0x1e, unpacked like pbp
    FUN_00004840): the unit box is at 0x20 (signed: the coarse levels reach west of -30 degrees); slot 3 holds the points (8-byte absolute GPS pairs, or 16-bit x/y in steps of 64
    from the box corner when header +0x10+size(0x3f) is set); a record's shape runs from its point
    pointer (+2) to the next record's. Slot 0 groups the slot 1 records by type."""
    gp.layer("areas", "POLYGON", [("level", "INTEGER"), ("type", "INTEGER"), ("type_name", "TEXT"),
                                  ("name", "TEXT"), ("area_m2", "INTEGER"), ("block", "INTEGER")])
    gp.layer("overview_roads", "LINESTRING", [("level", "INTEGER"), ("name", "TEXT"), ("attr", "INTEGER"),
                                              ("block", "INTEGER")])
    unpacker = Unpacker(sizes, release, TEXT_TABLES, block_size(f))
    for tid, level in BACKGROUND_LEVELS:
        (_, _), (data, _), (end, _) = tables.get(tid, ((0, 0), (0, 0), (0, 0)))
        na = nr = 0
        if not data:
            continue
        for b, length, head in units(f, data, end):
            progress.step(f"background, level {level}", b - data, end - data)
            x0, y0, x1, y1 = struct.unpack_from(">4i", head, 0x20)     # the 52-byte header is never compressed
            if bbox and (lon(x1) < bbox[0] or lon(x0) > bbox[2] or lat(y1) < bbox[1] or lat(y0) > bbox[3]):
                continue
            try:
                d = unpacker.unpack(read_blocks(f, b, length))
            except (ValueError, struct.error, IndexError, KeyError):
                continue                      # a unit that will not unpack: skip, like old ones did
            if d is None:
                continue
            w = lambda o: struct.unpack_from(">H", d, o)[0]
            wide = w(8 + 0x10 + sizes[0x3F]) == 0
            step = 8 if wide else 4
            shift = 1 << d[0x33]     # point step: 64 GPS units at level 0, doubling per level

            def shape(r, rs):
                pts = []
                for p in range(w(r + 2), min(w(r + rs + 2), len(d)), step):
                    if p + step > len(d):
                        break
                    if wide:
                        X, Y = struct.unpack_from(">ii", d, p)
                    else:
                        X, Y = x0 + w(p) * shift, y0 + w(p + 2) * shift
                    pts.append((lon(X), lat(Y)))
                return pts

            g_off, g_cnt = w(8), w(10)
            g_cnt = max(0, min(g_cnt, (len(d) - g_off) // 4 - 1))
            groups = [(d[g_off + 4 * i], w(g_off + 4 * i + 2)) for i in range(g_cnt + 1)]
            off, cnt, rs = w(12), w(14), sizes[0x3A]
            cnt = max(0, min(cnt, (len(d) - off) // rs))
            for i in range(cnt):
                r = off + i * rs
                typ = None
                for k in range(g_cnt):
                    if groups[k][1] <= r and (k == g_cnt - 1 or r < groups[k + 1][1]):
                        typ = groups[k][0]
                pts = shape(r, rs)
                if len(pts) >= 3:
                    gp.add("areas", pts, (level, typ, AREA_TYPES.get(typ), cstring(d, w(r)),
                                          struct.unpack_from(">I", d, r + 4)[0], b))
                    na += 1
            off, cnt, rs = w(16), w(18), sizes[0x3C]
            cnt = max(0, min(cnt, (len(d) - off) // rs))
            for i in range(cnt):
                r = off + i * rs
                pts = shape(r, rs)
                if len(pts) >= 2:
                    gp.add("overview_roads", pts, (level, cstring(d, w(r)), struct.unpack_from(">I", d, r + 4)[0], b))
                    nr += 1
        progress.finish(f"background, level {level} (table {tid:x}): {na} areas, {nr} roads")


def poi(f, gp, tables, bbox, progress):
    """Table 7: points of interest."""
    gp.layer("poi", "POINT", [("name", "TEXT"), ("brand", "TEXT"), ("category", "INTEGER"),
                              ("category_name", "TEXT"), ("street", "TEXT"), ("housenumber", "TEXT"),
                              ("district", "TEXT"), ("city", "TEXT"), ("postcode", "TEXT"), ("phone", "TEXT"),
                              ("block", "INTEGER"), ("field16", "INTEGER")])
    refs = UnitCache(f)
    (_, _), (data, _), (end, _) = tables.get(7, ((0, 0), (0, 0), (0, 0)))
    n = 0
    if not data:
        return progress.finish("poi: table empty")
    for b, length, head in units(f, data, end):
        progress.step("poi", b - data, end - data)
        u = read_blocks(f, b, length)
        off, count = struct.unpack_from(">HH", u, 8)
        x0, y0, x1, y1 = struct.unpack_from(">4I", u, 0x10)
        if bbox and (lon(x1) < bbox[0] or lon(x0) > bbox[2] or lat(y1) < bbox[1] or lat(y0) > bbox[3]):
            continue
        count = max(0, min(count, (len(u) - off) // 28))   # defensive: broken slot counts
        for i in range(count):
            r = off + i * 28
            if r + 28 > len(u):
                break
            ptr, noff, x, y, cat, brand = struct.unpack_from(">IHHHHH", u, r)
            name, details = None, [None] * 6
            if ptr:
                t = refs.get(ptr)
                if noff + 8 <= len(t):
                    # table 11 name entry: name, flags, district, offset of the 40-byte detail record
                    nm, _, district, rec = struct.unpack_from(">HHHH", t, noff)
                    name = cstring(t, nm)
                    if rec + 40 <= len(t):
                        tw = lambda o: cstring(t, struct.unpack_from(">H", t, rec + o)[0])
                        details = [tw(14), tw(26), cstring(t, district), tw(16), tw(34), tw(32)]
            pt = (lon(x0 + x * POINT_STEP), lat(y0 + y * POINT_STEP))
            gp.add("poi", [pt], (name, cstring(u, brand), cat, POI_CATEGORIES.get(cat), *details, b,
                                 struct.unpack_from(">I", u, r + 16)[0]))
            n += 1
    progress.finish(f"poi: {n}")


def cities(f, gp, tables, bbox, sizes, release, progress):
    """Table d: one point per city record, at the start of the segment it points at (+12 parcel,
    +16 segment offset); names from the slot 0 entries (variant bits in the flags' high byte:
    0x10 rotated words, 0x02 foreign spelling, 0x01 alternative name; only plain names are kept,
    the others go to alt_names)."""
    gp.layer("cities", "POINT", [("name", "TEXT"), ("municipality", "TEXT"), ("lang", "INTEGER"),
                                 ("alt_names", "TEXT"), ("trie_roots", "INTEGER"), ("block", "INTEGER")])
    unpacker = Unpacker(sizes, release, TEXT_TABLES, block_size(f))
    (_, _), (data, _), (end, _) = tables.get(0x0D, ((0, 0), (0, 0), (0, 0)))
    if not data:
        return progress.finish("cities: table empty")
    found = {}          # (unit block, record offset) -> [name, municipality, lang, alt names, parcel, segment, roots]
    for b, length, head in units(f, data, end):
        progress.step("cities (names)", b - data, end - data)
        u = read_blocks(f, b, length)
        off, count = struct.unpack_from(">HH", u, 8)
        count = max(0, min(count, (len(u) - off) // 8))       # defensive: broken slot counts
        for i in range(count):
            name, flags, muni, rec = struct.unpack_from(">HHHH", u, off + 8 * i)
            if rec + 14 > len(u):          # defensive: a name entry pointing outside its unit
                continue
            c = found.setdefault((b, rec), [None, None, None, [], *struct.unpack_from(">IH", u, rec + 12),
                                            struct.unpack_from(">H", u, rec + 6)[0]])
            if flags >> 8 == 0 and c[0] is None:
                c[0], c[1], c[2] = cstring(u, name), cstring(u, muni), flags & 0xFF
            else:
                c[3].append(cstring(u, name))
    n = 0
    by_parcel = {}
    for (b, _), c in found.items():
        by_parcel.setdefault(c[4], []).append((b, c))
    for k, (ptr, rows) in enumerate(by_parcel.items()):
        progress.step("cities (positions)", k, len(by_parcel))
        if not ptr:                 # a few cities have no segment
            continue
        raw = read_unit(f, ptr)
        bx0, by0, bx1, by1 = struct.unpack_from(">4I", raw, 0x44)    # header is never compressed
        if bbox and (lon(bx1) < bbox[0] or lon(bx0) > bbox[2] or lat(by1) < bbox[1] or lat(by0) > bbox[3]):
            continue
        d = unpacker.unpack(raw)
        if d is None:
            continue
        x0, y0 = struct.unpack_from(">II", d, 0x44)
        for b, (name, muni, lang, alts, _, seg, roots) in rows:
            if not seg + 4 <= len(d):
                continue
            a, = struct.unpack_from(">H", d, seg)
            if not 0 < a < len(d) - 4:
                continue
            px, py = struct.unpack_from(">HH", d, a)
            pt = (lon(x0 + px * POINT_STEP), lat(y0 + py * POINT_STEP))
            if bbox and not (bbox[0] <= pt[0] <= bbox[2] and bbox[1] <= pt[1] <= bbox[3]):
                continue
            gp.add("cities", [pt], (name or (alts[0] if alts else None), muni, lang,
                                    "; ".join(x for x in alts if x) or None, roots, b))
            n += 1
    progress.finish(f"cities: {n}")
