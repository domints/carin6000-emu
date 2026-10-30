"""Places for the encoder, the way the original (Navteq) names them (docs/format.md section 4,
place hierarchy), with the OSM admin levels of each country (libs/countries.py); the country at
a point comes from the countries' boundaries (Borders, Atlas). Poland: city =
gmina (admin_level 7, without "gmina"), its municipality = powiat (admin_level 6); a street's
second text = the settlement it lies in (admin_level 8 area, or the nearest place node), none in
the gmina's own town. Polish street names get "ulica " unless they start with another street word,
as the original's do ("ulica adama mickiewicza").
"""
import math
import re
import sqlite3
import struct

from .carindb import lat, lon
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
    with a street word; other countries keep the OSM name. Bilingual names ("a / b") keep the
    first."""
    if not name:
        return None
    name = name.split(" / ")[0]
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


def _polygons(blob, holes=False):
    """GeoPackage (multi)polygon -> list of outer rings (and inner ones with holes) in GPS units."""
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
            if r == 0 or holes:
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


QUALIFIERS = {"selo", "varos", "varosica", "naselje", "grad",       # "Лучани (село)": village / town
              "rs", "fbih"}                                     # Bosnia: "Ново Село (РС)" (entity)
BILINGUAL = re.compile(r" / | - ")


def _name(raw):
    """(folded name, folded base, folded bracket) of "Base (bracket)" names (Serbia: "Београд
    (Вождовац)", "Лучани (село)"); of bilingual names ("Koper / Capodistria (naselje)",
    "Opština Ulcinj - Komuna e Ulqinit") the first."""
    raw = BILINGUAL.split(raw)[0]
    m = re.match(r"^(.*?)\s*\((.*)\)$", raw)
    if not m:
        return fold(raw), None, None
    return fold(raw), fold(m.group(1)), fold(m.group(2))


def _admin_areas(rows):
    """(name, level, outer rings simplified to 10 m) of admin area rows (in a worker)."""
    from .levels import simplify
    out = []
    for _, name, level, geom in rows:
        if not name or not fold(name):
            continue
        rings = [r for r in (simplify(ring, 10) for ring in _polygons(geom)) if len(r) >= 4]
        if rings:
            out.append((name, int(level), rings))
    return out


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
    """Cities and settlements of one country (bbox: its box in degrees; borders: the place nodes
    of other countries are left out)."""

    def __init__(self, gpkg, bbox, country, borders=None):
        from .osmsrc import prows, rows
        self.country = country
        lv = {*country.levels[0], *country.levels[1:]} - {None}    # OSM admin levels: city, municipality, settlement, district
        self.levels = {k: [] for k in lv}
        self.grids = {k: Grid() for k in lv}
        for name, level, rings in prows(gpkg,
                "SELECT coalesce('r' || m.osm_id, 'w' || m.osm_way_id), m.name, m.admin_level, m.geom FROM multipolygons m JOIN rtree_multipolygons_geom r "
                "ON m.fid = r.id WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND "
                "m.boundary = 'administrative' AND m.admin_level IN (%s)" % ",".join("'%d'" % k for k in set(lv)),
                (bbox[0], bbox[2], bbox[1], bbox[3]), _admin_areas):
            a = Area(name, rings)
            self.levels[level].append(a)
            self.grids[level].add(a.box, a)
        self.nodes = Grid()
        for _, name, place, geom in rows(gpkg,
                "SELECT p.osm_id, p.name, p.place, p.geom FROM points p JOIN rtree_points_geom r ON p.fid = r.id "
                "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND p.place IN (%s)"
                % ",".join("?" * len(VILLAGES)),
                (bbox[0] - 0.05, bbox[2] + 0.05, bbox[1] - 0.05, bbox[3] + 0.05, *VILLAGES)):
            if name:
                lon, lat = struct.unpack_from("<dd", geom, 8 + _env(geom) + 5)     # WKB point
                q = gps(lon, lat)
                if fold(name) and (borders is None or borders.at(q) == country.iso):
                    self.nodes.add((q[0], q[1], q[0], q[1]), (q, fold(BILINGUAL.split(name)[0])))
        self.cache = {}

    def _area(self, level, pt, city=None):
        """Name of the area of that level at a point; "City (District)" gives the district,
        "Village (village)" the village."""
        if level is None:
            return None
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
                name = name[len(prefix):]
                for end, new in self.country.genitive:      # "komuna e prishtines" -> "prishtine"
                    if name.endswith(end):
                        return name[:len(name) - len(end)] + new
                return name
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


STRIP = 1 << 12     # GPS units (~80 m): horizontal strips of the boundary edges


class Borders:
    """The country at a point: the countries' OSM admin_level 2 boundaries (ISO3166-1 code),
    simplified to 20 m. A horizontal ray test over the boundary edges of the point's strip; cells
    no boundary passes keep their answer."""

    def __init__(self, gpkg, countries):
        from .levels import simplify
        from .osmsrc import rows
        self.isos = [c.iso for c in countries]
        self.strips, self.near, self.cache = {}, set(), {}
        self.boxes = {}                     # iso -> box in degrees
        for k, c in enumerate(countries):
            rings = []
            for _, geom in rows(gpkg,
                    "SELECT coalesce('r' || osm_id, 'w' || osm_way_id), geom FROM multipolygons WHERE "
                    "boundary = 'administrative' AND admin_level = '2' AND other_tags LIKE ?",
                    (f'%"ISO3166-1"=>"{c.iso.upper()}"%',)):
                rings += [simplify(r, 20) for r in _polygons(geom, holes=True)]
            if not rings:
                raise SystemExit(f"no admin_level 2 boundary of {c.iso.upper()} in {c.extract}")
            xs = [p[0] for r in rings for p in r]
            ys = [p[1] for r in rings for p in r]
            self.boxes[c.iso] = (lon(min(xs)), lat(min(ys)), lon(max(xs)), lat(max(ys)))
            for r in rings:
                for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]):
                    if y0 == y1:
                        continue
                    for s_ in range(min(y0, y1) // STRIP, max(y0, y1) // STRIP + 1):
                        self.strips.setdefault(s_, []).append((k, x0, y0, x1, y1))
                    steps = max(abs(x1 - x0), abs(y1 - y0)) // CELL + 1
                    for i in range(steps + 1):
                        cx = (x0 + (x1 - x0) * i // steps) // CELL
                        cy = (y0 + (y1 - y0) * i // steps) // CELL
                        for dx in (-1, 0, 1):
                            for dy in (-1, 0, 1):
                                self.near.add((cx + dx, cy + dy))
        boxes = self.boxes.values()
        self.bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                     max(b[2] for b in boxes), max(b[3] for b in boxes))

    def at(self, pt):
        """ISO code of the country at a point, None outside them all."""
        cell = (pt[0] // CELL, pt[1] // CELL)
        if cell in self.cache:
            return self.cache[cell]
        x, y = pt
        inside = 0
        for k, x0, y0, x1, y1 in self.strips.get(y // STRIP, ()):
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside ^= 1 << k
        iso = next((c for k, c in enumerate(self.isos) if inside >> k & 1), None)
        if cell not in self.near:
            self.cache[cell] = iso
        return iso


class Atlas:
    """The places of a disc's countries: the country at a point (Borders), then its Places."""

    def __init__(self, gpkg, countries):
        self.borders = Borders(gpkg, countries)
        self.bbox = self.borders.bbox
        self.countries = {c.iso: c for c in countries}
        self.places = {c.iso: Places(gpkg, self.borders.boxes[c.iso], c, self.borders) for c in countries}

    def country_at(self, pt):
        return self.countries.get(self.borders.at(pt))

    def clear(self):
        """Forget the cached answers (they must not depend on earlier lookups)."""
        for p in self.places.values():
            p.cache.clear()
