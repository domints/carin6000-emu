"""Places for the encoder, the way the original (Navteq) names them (docs/format.md section 4,
place hierarchy), with the OSM admin levels of the country (libs/countries.py). Poland: city =
gmina (admin_level 7, without "gmina"), its municipality = powiat (admin_level 6); a street's
second text = the settlement it lies in (admin_level 8 area, or the nearest place node), none in
the gmina's own town. Polish street names get "ulica " unless they start with another street word,
as the original's do ("ulica adama mickiewicza").
"""
import math
import re
import sqlite3
import struct

from .osmnet import fold, gps

STREET_WORDS = ("ulica", "aleja", "al.", "plac", "rondo", "osiedle", "skwer", "bulwar", "most",
                "wybrzeze", "trakt", "droga", "sciezka", "pasaz", "park", "zaulek", "szosa",
                "rynek", "deptak", "wal", "estakada", "tunel", "wiadukt", "przejscie", "podworze")
VILLAGES = ("village", "hamlet", "suburb", "quarter", "neighbourhood", "isolated_dwelling", "locality")
NEAR = 2500       # metres: a street belongs to the nearest place node within this distance
NEAR_GPS = NEAR / 1.8e-7 / 111320
CELL = 1 << 17    # grid of the areas and place nodes (~2.6 km north-south)


def street_name(name, country=None):
    """The street name as written in the database: Polish names get "ulica " unless they start
    with a street word; other countries keep the OSM name."""
    if not name:
        return None
    if country is not None and not country.street_prefix:
        return name
    first = name.split(" ", 1)[0]
    return name if first in STREET_WORDS else "ulica " + name


class Grid:
    """Objects by the grid cells their box touches."""

    def __init__(self):
        self.cells = {}

    def add(self, box, obj):
        for cx in range(box[0] // CELL, box[2] // CELL + 1):
            for cy in range(box[1] // CELL, box[3] // CELL + 1):
                self.cells.setdefault((cx, cy), []).append(obj)

    def at(self, pt):
        return self.cells.get((pt[0] // CELL, pt[1] // CELL), ())


def _polygons(blob):
    """GeoPackage (multi)polygon -> list of outer rings in GPS units."""
    flags = blob[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    wkb, pos = blob[8 + env:], 0
    rings = []

    def poly(p):
        order = "<" if wkb[p] == 1 else ">"
        n_rings, = struct.unpack_from(order + "I", wkb, p + 5)
        p += 9
        for r in range(n_rings):
            n, = struct.unpack_from(order + "I", wkb, p)
            pts = [gps(*struct.unpack_from(order + "dd", wkb, p + 4 + 16 * i)) for i in range(n)]
            if r == 0:
                rings.append(pts)
            p += 4 + 16 * n
        return p

    order = "<" if wkb[0] == 1 else ">"
    kind, = struct.unpack_from(order + "I", wkb, 1)
    if kind == 3:
        poly(0)
    elif kind == 6:
        n, = struct.unpack_from(order + "I", wkb, 5)
        p = 9
        for _ in range(n):
            p = poly(p)
    return rings


def _inside(pt, ring):
    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


QUALIFIERS = {"selo", "varos", "varosica", "naselje", "grad"}   # "Лучани (село)": village / town


def _name(raw):
    """(folded name, folded base, folded bracket) of "Base (bracket)" names (Serbia: "Београд
    (Вождовац)", "Лучани (село)")."""
    m = re.match(r"^(.*?)\s*\((.*)\)$", raw)
    if not m:
        return fold(raw), None, None
    return fold(raw), fold(m.group(1)), fold(m.group(2))


class Area:
    def __init__(self, raw, rings):
        self.name, self.base, self.qual = _name(raw)
        self.rings = rings
        xs = [p[0] for r in rings for p in r]
        ys = [p[1] for r in rings for p in r]
        self.box = (min(xs), min(ys), max(xs), max(ys))

    def contains(self, pt):
        b = self.box
        return b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3] and any(_inside(pt, r) for r in self.rings)


class Places:
    def __init__(self, gpkg, bbox, country):
        from .osmsrc import rows
        self.country = country
        lv = {*country.levels[0], *country.levels[1:]}   # OSM admin levels: city, municipality, settlement, district
        self.levels = {k: [] for k in lv}
        self.grids = {k: Grid() for k in lv}
        for _, name, level, geom in rows(gpkg,
                "SELECT coalesce('r' || m.osm_id, 'w' || m.osm_way_id), m.name, m.admin_level, m.geom FROM multipolygons m JOIN rtree_multipolygons_geom r "
                "ON m.fid = r.id WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND "
                "m.boundary = 'administrative' AND m.admin_level IN (%s)" % ",".join("'%d'" % k for k in set(lv)),
                (bbox[0], bbox[2], bbox[1], bbox[3])):
            rings = _polygons(geom)
            if rings and name and fold(name):
                a = Area(name, rings)
                self.levels[int(level)].append(a)
                self.grids[int(level)].add(a.box, a)
        self.nodes = Grid()
        for _, name, place, geom in rows(gpkg,
                "SELECT p.osm_id, p.name, p.place, p.geom FROM points p JOIN rtree_points_geom r ON p.fid = r.id "
                "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND p.place IN (%s)"
                % ",".join("?" * len(VILLAGES)),
                (bbox[0] - 0.05, bbox[2] + 0.05, bbox[1] - 0.05, bbox[3] + 0.05, *VILLAGES)):
            if name:
                lon, lat = struct.unpack_from("<dd", geom, 8 + _env(geom) + 5)     # WKB point
                q = gps(lon, lat)
                if fold(name):
                    self.nodes.add((q[0], q[1], q[0], q[1]), (q, fold(name)))
        self.cache = {}

    def _area(self, level, pt, city=None):
        """Name of the area of that level at a point; "City (District)" gives the district,
        "Village (village)" the village."""
        for a in self.grids[level].at(pt):
            if a.contains(pt):
                if a.base and city and self._strip(a.base) == city and a.qual:
                    return a.qual
                if a.base and a.qual in QUALIFIERS:
                    return a.base
                return a.name
        return None

    def _strip(self, name):
        for prefix in self.country.city_prefixes:
            if name and name.startswith(prefix):
                return name[len(prefix):]
        return name

    def city_of(self, pt):
        """(city, municipality) at a point: (gmina, powiat) in Poland."""
        key = (pt[0] >> 14, pt[1] >> 14)      # ~300 m cells: neighbours share the answer
        if key not in self.cache:
            lv_city, lv_muni, lv_town, lv_district = self.country.levels
            city = next(filter(None, (self._strip(self._area(k, pt)) for k in lv_city)), None)
            muni = self._strip(self._area(lv_muni, pt))
            town = self._strip(self._area(lv_town, pt, city))
            if town == city:                # the gmina's own town: its district if it has any (Warsaw)
                town = self._strip(self._area(lv_district, pt)) or town
            self.cache[key] = (city or town or "?", muni or city or "?", town)
        return self.cache[key][:2]

    def settlement_of(self, pt):
        """The settlement a street lies in (admin_level 8: towns and, in Poland, villages too);
        none in the town the gmina is named after, as in the original. Without an admin_level 8
        area: the nearest place node."""
        city = self.city_of(pt)[0]
        place = self.cache[(pt[0] >> 14, pt[1] >> 14)][2]
        if place:
            return None if place == city else place
        best, name = NEAR_GPS, None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for q, n in self.nodes.at((pt[0] + dx * CELL, pt[1] + dy * CELL)):
                    d = math.hypot((q[0] - pt[0]) * 0.62, q[1] - pt[1])
                    if d < best:
                        best, name = d, n
        return name


def _env(blob):
    return {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(blob[3] >> 1) & 7]
