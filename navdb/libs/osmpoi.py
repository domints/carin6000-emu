"""Points of interest for the encoder (docs/format.md section 7): a basic set from OSM (fuel,
car dealers and repair, P&R, hotels, hospitals, police, railway and bus stations, airports,
museums), written as the original's tables:

  7     POI points in spatial units (28-byte records: table 11 entry, x / y, category, brand)
  11    name units per (city, category) list: 8-byte name entries sorted by name, 40-byte detail
        records (position, access segment, brand, street, city, municipality, country, house
        number, id, phone, postcode), 8-byte access records (parcel, segment, side)
  12    one trie per list (first letters -> table 11 entries), reached from the city records'
        category lists (table d slot 3) and the countries' (block 4 slot 3; airports, museums)

A POI belongs to the gmina (city record) it lies in; POIs of other cities and outside the disc's
countries are not listed.
"""
import math
import struct
from dataclasses import dataclass

from .carindb import BLOCK, lat, lon
from .osmnet import fold, gps, hstore
from .osmplaces import _env, _polygons, street_name
from .search import _a4, Texts, leaves, node_lists, trie, trie_unit_bytes

FUEL, DEALER, RENTAL, PARK_RIDE, HOTEL, MUSEUM, HOSPITAL, POLICE, RAILWAY, AIRPORT, BUS, REPAIR = \
    12, 11, 13, 15, 21, 32, 41, 42, 51, 52, 54, 59
COUNTRY_WIDE = (MUSEUM, AIRPORT)          # also listed for the whole country, as in the original
UNIT_MAX = 8 * BLOCK
POINTS_MAX = 400                          # records per table 7 unit
POINT_STEP = 64
LEAF_MAX = 120                            # names per trie leaf (a leaf stays in one unit)
ACCESS_DIST = 600 / 1.8e-7 / 111320       # metres -> GPS units: no access segment farther away
TEXT_MAX = 48


def category(tags):
    a, t, s = tags.get("amenity"), tags.get("tourism"), tags.get("shop")
    if a == "fuel":
        return FUEL
    if a == "hospital":
        return HOSPITAL
    if a == "police":
        return POLICE
    if a == "bus_station":
        return BUS
    if a == "car_rental":
        return RENTAL
    if a == "parking" and tags.get("park_ride", "no") != "no":
        return PARK_RIDE
    if t in ("hotel", "motel"):
        return HOTEL
    if t == "museum":
        return MUSEUM
    if s == "car":
        return DEALER
    if s == "car_repair":
        return REPAIR
    if tags.get("railway") in ("station", "halt") and tags.get("station") not in ("subway", "light_rail", "miniature", "funicular"):
        return RAILWAY
    if tags.get("aeroway") == "aerodrome" and (tags.get("iata") or tags.get("aerodrome:type") in ("international", "public")):
        return AIRPORT
    return None


@dataclass(eq=False, slots=True)
class Poi:
    pt: tuple
    cat: int
    name: str
    brand: str
    street: str
    housenumber: str
    postcode: str
    phone: str
    city: str = None
    muni: str = None
    district: str = None
    country: object = None        # libs/countries.Country
    access: tuple = None          # (parcel, segment index, side)
    ident: int = 0


def _text(v):
    v = fold(v)
    return v[:TEXT_MAX] if v else None


def load(gpkg, bbox, country):
    """The basic POIs in the box (points and area centroids), one per OSM object."""
    from .osmsrc import rows
    keys = ("amenity", "tourism", "shop", "railway", "aeroway")
    out = []
    like = " OR ".join(f"l.other_tags LIKE '%\"{k}\"=>%'" for k in keys)
    queries = (
        ("points", "'p' || l.osm_id", "l.other_tags", f"({like})"),
        ("multipolygons", "coalesce('r' || l.osm_id, 'w' || l.osm_way_id)",
         "l.other_tags, l.amenity, l.tourism, l.shop, l.aeroway",
         "(l.amenity IN ('fuel', 'hospital', 'police', 'bus_station', 'car_rental', 'parking') OR "
         "l.tourism IN ('hotel', 'motel', 'museum') OR l.shop IN ('car', 'car_repair') OR "
         "l.aeroway = 'aerodrome' OR l.other_tags LIKE '%\"railway\"=>\"station\"%')"))
    for layer, key, cols, where in queries:
        for row in rows(gpkg,
                f"SELECT {key}, l.name, l.geom, {cols} FROM {layer} l JOIN rtree_{layer}_geom r ON l.fid = r.id "
                f"WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND {where}",
                (bbox[0], bbox[2], bbox[1], bbox[3])):
            _, name, geom, other = row[:4]
            tags = hstore(other)
            if layer == "multipolygons":
                for k, v in zip(("amenity", "tourism", "shop", "aeroway"), row[4:]):
                    if v:
                        tags[k] = v
            cat = category(tags)
            if cat is None:
                continue
            brand = _text(tags.get("brand"))
            label = _text(name) or brand or _text(tags.get("operator"))
            if not label:
                continue
            if layer == "points":
                pt = gps(*struct.unpack_from("<dd", geom, 8 + _env(geom) + 5))
            else:
                rings = _polygons(geom)
                if not rings:
                    continue
                ring = rings[0]
                pt = (sum(p[0] for p in ring) // len(ring), sum(p[1] for p in ring) // len(ring))
            if not (bbox[0] <= lon(pt[0]) <= bbox[2] and bbox[1] <= lat(pt[1]) <= bbox[3]):
                continue
            street = street_name(_text(tags.get("addr:street")), country)
            out.append(Poi(pt, cat, label, brand, street, _text(tags.get("addr:housenumber")),
                           (tags.get("addr:postcode") or "")[:12] or None,
                           (tags.get("phone") or tags.get("contact:phone") or "")[:24] or None))
    return out


def place(pois, atlas, parcels, sorted_pieces):
    """Country, city, district and access segment of every POI; returns those inside the
    countries (atlas: osmplaces.Atlas)."""
    atlas.clear()                           # the answers must not depend on earlier lookups
    for p in pois:
        p.country = atlas.country_at(p.pt)
    pois[:] = [p for p in pois if p.country]
    grid, cell = {}, 1 << 13
    for pc in parcels:
        for idx, piece in enumerate(sorted_pieces(pc)):
            pts = piece.points
            for i in range(len(pts) - 1):
                for cx in range(min(pts[i][0], pts[i + 1][0]) // cell, max(pts[i][0], pts[i + 1][0]) // cell + 1):
                    for cy in range(min(pts[i][1], pts[i + 1][1]) // cell, max(pts[i][1], pts[i + 1][1]) // cell + 1):
                        grid.setdefault((cx, cy), []).append((pc, idx, pts[i], pts[i + 1], piece.road.cls))
    for n, p in enumerate(pois):
        p.ident = n + 1
        places = atlas.places[p.country.iso]
        p.city, p.muni = places.city_of(p.pt)
        p.district = places.settlement_of(p.pt)
        best = None
        for ring in range(0, 6):
            for cx in range(p.pt[0] // cell - ring, p.pt[0] // cell + ring + 1):
                for cy in range(p.pt[1] // cell - ring, p.pt[1] // cell + ring + 1):
                    if max(abs(cx - p.pt[0] // cell), abs(cy - p.pt[1] // cell)) != ring:
                        continue
                    for pc, idx, a, b, cls in grid.get((cx, cy), ()):
                        d, side = _project(p.pt, a, b)
                        d += 300 if cls == 0 else 0          # prefer a road off the motorway
                        if best is None or d < best[0]:
                            best = (d, pc, idx, side)
            if best and best[0] < ring * cell:
                break
        if best and best[0] < ACCESS_DIST:
            p.access = (best[1], best[2], 0 if best[3] > 0 else 1)


def _project(pt, a, b):
    cos = 0.62
    ax, ay, bx, by, px, py = a[0] * cos, a[1], b[0] * cos, b[1], pt[0] * cos, pt[1]
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    t = 0 if not ll else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / ll))
    return math.hypot(px - ax - t * dx, py - ay - t * dy), dx * (py - ay) - dy * (px - ax)


class PoiTables:
    """Tables 7, 11 and 12 for the POIs; lists: city key (country ISO, name, muni) -> [(category,
    list key)] and country ISO -> the country-wide lists, for search.add_tables."""

    def __init__(self, pois, city_keys):
        lists = {}
        for p in pois:
            iso = p.country.iso
            if (iso, p.city, p.muni) in city_keys:
                lists.setdefault(("c", iso, p.city, p.muni, p.cat), []).append(p)
            if p.cat in COUNTRY_WIDE:
                lists.setdefault(("w", iso, p.cat), []).append(p)
        self.lists = {}
        for key, items in sorted(lists.items(), key=lambda kv: str(kv[0])):
            items.sort(key=lambda p: (p.name, p.district or ""))
            same = {}
            items[:] = [p for p in items if same.setdefault(p.name, []).append(p) or len(same[p.name]) <= LEAF_MAX]
            self.lists[key] = (items, trie([p.name for p in items], leaf_max=LEAF_MAX))
        self.city_lists = {}
        for key in self.lists:
            if key[0] == "c":
                self.city_lists.setdefault(key[1:4], []).append((key[4], key))
        self.country_lists = {}
        for key in self.lists:
            if key[0] == "w":
                self.country_lists.setdefault(key[1], []).append((key[2], key))
        self._pack_names()
        self._pack_tries()
        self.pois = [p for p in pois if p in self.home]

    # table 11: groups (trie leaves) packed into units
    def _row_texts(self, p):
        return (p.name, p.district or p.city, p.brand, p.street, p.city, p.muni, p.country.name,
                p.housenumber, p.phone, p.postcode)

    def _pack_names(self):
        self.units = [[]]                   # unit -> rows (poi)
        self.leaf_at = {}                   # id(leaf) -> (unit, first row)
        self.home = {}                      # poi -> (unit, row) of its city list entry
        texts, size = Texts(), 0x30
        for key, (items, nodes) in self.lists.items():
            for leaf in leaves(nodes):
                rows = items[leaf.first:leaf.first + leaf.count]
                add = Texts()
                add.order, add.size = list(texts.order), texts.size
                for p in rows:
                    for t in self._row_texts(p):
                        add.add(t)
                n = len(self.units[-1]) + len(rows)
                if self.units[-1] and _a4(0x30 + 8 * n) + 48 * n + add.size > UNIT_MAX:
                    self.units.append([])
                    texts = Texts()
                    add = Texts()
                    for p in rows:
                        for t in self._row_texts(p):
                            add.add(t)
                    n = len(rows)
                    if _a4(0x30 + 8 * n) + 48 * n + add.size > UNIT_MAX:
                        raise ValueError(f"POI leaf of {n} names does not fit a unit")
                texts = add
                u = len(self.units) - 1
                self.leaf_at[id(leaf)] = (u, len(self.units[u]))
                for p in rows:
                    if key[0] == "c":
                        self.home[p] = (u, len(self.units[u]))
                    self.units[u].append(p)

    def name_unit(self, i, own, nxt, prv, parcel_ptr):
        rows = self.units[i]
        n = len(rows)
        o_rec = _a4(0x30 + 8 * n)
        o_acc = o_rec + 40 * n
        o_text = o_acc + 8 * n
        off, pos = {}, o_text
        for p in rows:
            for t in self._row_texts(p):
                if t and t not in off:
                    off[t] = pos
                    pos += len(t) + 1
        d = bytearray(-(-pos // BLOCK) * BLOCK)
        n_acc = sum(1 for p in rows if p.access)
        struct.pack_into(">IHHHHHHHHHHHHHH", d, 0, own, 0x10, 0, 0x30, n, o_rec, n, 0, 0, 0, 0, o_acc, n_acc, 0, 0)
        struct.pack_into(">II", d, 0x28, nxt, prv)
        t = lambda v: off.get(v, 0)
        acc = o_acc
        for k, p in enumerate(rows):
            rec = o_rec + 40 * k
            struct.pack_into(">HHHH", d, 0x30 + 8 * k, t(p.name), p.country.lang, t(p.district or p.city), rec)
            a_off, a_n = acc, 0
            if p.access:
                pc, idx, side = p.access
                struct.pack_into(">IHH", d, acc, parcel_ptr(pc), pc.seg_base + 32 * idx, side)
                acc += 8
                a_n = 1
            struct.pack_into(">iiHHHHHHHHHHIHHHH", d, rec, p.pt[0], p.pt[1], a_off if a_n else 0, a_n,
                             t(p.brand), t(p.street), t(p.city), t(p.muni), t(p.country.name), 0, 0,
                             t(p.housenumber), p.ident, t(p.phone), t(p.postcode), 0, 0)
        for v, o in off.items():
            d[o:o + len(v)] = v.encode("latin1", "replace")
        return bytes(d)

    # table 12: the tries of many lists share a unit (a list's trie stays in one unit)
    def _pack_tries(self):
        self.trie_units = [[]]
        self.trie_of = {}                   # list key -> (unit, node list)
        size = 0x0C
        for key, (_, nodes) in self.lists.items():
            lists = node_lists(nodes)
            n = 12 * sum(len(lst) for lst in lists)
            if self.trie_units[-1] and size + n > UNIT_MAX:
                self.trie_units.append([])
                size = 0x0C
            self.trie_units[-1].append(lists)
            self.trie_of[key] = (len(self.trie_units) - 1, lists[0])
            size += n
        self.trie_start = [trie_unit_bytes(0, 0x11, [l for ls in g for l in ls], lambda nd: (0, 0, 0))[1]
                           for g in self.trie_units]

    def list_ref(self, resolve, key):
        u, root = self.trie_of[key]
        return resolve(("t12", u)), self.trie_start[u][id(root)], len(root)

    def trie_unit(self, i, resolve):
        lists = [l for ls in self.trie_units[i] for l in ls]

        def place(nd):
            u, row = self.leaf_at[id(nd)]
            return resolve(("p11", u)), 0x30 + 8 * row, nd.count
        return trie_unit_bytes(resolve(("t12", i)), 0x11, lists, place)[0]

    # table 7: points in square tiles
    def tiles(self, root):
        """[(box (x0, y0, x1, y1), [poi])]: quadtree cells of at most 2^21 with POINTS_MAX points."""
        out = []

        def split(x, y, size, items):
            if not items:
                return
            if size > 1 << 21 or (len(items) > POINTS_MAX and size > 1 << 15):
                h = size // 2
                for dx in (0, h):
                    for dy in (0, h):
                        split(x + dx, y + dy, h, [p for p in items if x + dx <= p.pt[0] < x + dx + h
                                                  and y + dy <= p.pt[1] < y + dy + h])
                return
            out.append(((x, y, x + size, y + size), items[:POINTS_MAX]))
        split(root.x, root.y, root.size, [p for p in self.pois if root.contains(p.pt)])
        return out

    def point_unit(self, box, items, own, resolve):
        n = len(items)
        o_text = 0x20 + 28 * n
        off, pos = {}, o_text
        for p in items:
            if p.brand and p.brand not in off:
                off[p.brand] = pos
                pos += len(p.brand) + 1
        d = bytearray(-(-pos // BLOCK) * BLOCK)
        struct.pack_into(">IHHHHHH4i", d, 0, own, 6, 0, 0x20, n, 0, 0, *box)
        for k, p in enumerate(items):
            u, row = self.home[p]
            struct.pack_into(">IHHHHHHI", d, 0x20 + 28 * k, resolve(("p11", u)), 0x30 + 8 * row,
                             (p.pt[0] - box[0]) // POINT_STEP, (p.pt[1] - box[1]) // POINT_STEP, p.cat,
                             off.get(p.brand, 0), 0, p.ident)
        for v, o in off.items():
            d[o:o + len(v)] = v.encode("latin1", "replace")
        return bytes(d)
