"""Road network from OpenStreetMap for the encoder: reads the `lines` layer of a GeoPackage made
by ogr2ogr from a .osm.pbf (see ../README.md), keeps the roads, maps OSM tags to CARiN segment
attributes (../docs/format.md section 4) and splits ways into edges between nodes.

Coordinates are GPS units (1.8e-7 degree, longitude + 30 degrees) snapped to the 64-unit grid the
parcels store points on. A node is a vertex shared by two or more ways or a way end; the vertices
in between are the edge's shape points.
"""
import math
import re
import sqlite3
import struct
import unicodedata
from dataclasses import dataclass, field

from .carindb import GPS_UNIT, POINT_STEP

# OSM highway -> (class (FRC 0-6), form of way); links and roundabouts are adjusted in road_attrs()
HIGHWAYS = {
    "motorway": (0, 0), "trunk": (0, 4), "primary": (1, 11), "secondary": (2, 11),
    "tertiary": (3, 11), "unclassified": (4, 12), "residential": (5, 12),
    "living_street": (6, 12), "service": (6, 12), "track": (6, 12),
    "motorway_link": (0, 1), "trunk_link": (0, 3), "primary_link": (1, 10),
    "secondary_link": (2, 10), "tertiary_link": (3, 10),
}
SKIP_SERVICE = {"parking_aisle", "driveway", "drive-through", "emergency_access"}
UNPAVED = {"unpaved", "gravel", "dirt", "ground", "grass", "sand", "earth", "mud", "fine_gravel",
           "compacted", "pebblestone", "woodchips"}

# The fields whose meaning is not known (or not needed) take the most common value of the original
# Polish data for the same (class, form of way): +10 bits 0-6 (speed / 4 km/h?), +11 bit 6, +16 bit 7,
# +17, word +28 without the access code (bits 4-6). See docs/format.md section 4.
DEFAULTS = {
    (0, 0): (31, 1, 0, 0x20, 0x1004), (0, 1): (31, 1, 0, 0x20, 0x1002), (0, 3): (22, 1, 0, 0x20, 0x1000),
    (0, 4): (31, 1, 0, 0x20, 0x1002), (1, 4): (31, 1, 0, 0x20, 0x1002), (1, 10): (31, 1, 0, 0x20, 0x1002),
    (1, 11): (22, 0, 0, 0x20, 0x1006), (1, 12): (11, 0, 0, 0x20, 0x1082), (2, 10): (22, 1, 0, 0x20, 0x1002),
    (2, 11): (22, 0, 0, 0x20, 0x1006), (2, 12): (11, 0, 0, 0x20, 0x1082), (3, 10): (22, 0, 0, 0x20, 0x1002),
    (3, 11): (22, 0, 0, 0x20, 0x1006), (3, 12): (11, 0, 0, 0x20, 0x1082), (4, 11): (22, 0, 0, 0x20, 0x1006),
    (4, 12): (11, 0, 0, 0x20, 0x1082), (5, 12): (5, 0, 0, 0x20, 0x1082), (6, 12): (5, 0, 0, 0x20, 0x1002),
}
CLASS_DEFAULTS = {0: (31, 1, 0, 0x20, 0x1002), 1: (22, 0, 0, 0x20, 0x1006), 2: (22, 0, 0, 0x20, 0x1006),
                  3: (11, 0, 0, 0x20, 0x1082), 4: (11, 0, 0, 0x20, 0x1082), 5: (5, 0, 0, 0x20, 0x1082),
                  6: (5, 0, 0, 0x20, 0x1002)}


def gps(lon, lat):
    """Degrees -> GPS units on the 64-unit grid."""
    return (round((lon + 30) / GPS_UNIT / POINT_STEP) * POINT_STEP,
            round(lat / GPS_UNIT / POINT_STEP) * POINT_STEP)


# Serbian Cyrillic -> Latin (Gaj), then folded like the rest; đ as "dj", as the original's
# Croatian names ("djelo")
CYRILLIC = dict(zip("абвгдђежзијклљмнњопрстћуфхцчџш",
                    "a b v g d dj e z z i j k l lj m n nj o p r s t c u f h c c dz s".split()))
LATIN = {"đ": "dj", "Đ": "Dj", "ł": "l", "Ł": "L"}


def fold(text):
    """Names as the original stores them: lower case ASCII ("Złota" -> "zlota", "Кнеза Милоша"
    -> "kneza milosa")."""
    if not text:
        return None
    text = "".join(LATIN.get(ch) or CYRILLIC.get(ch.lower(), ch) for ch in text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r" +", " ", re.sub(r"[^a-z0-9 ./]", " ", text.lower())).strip() or None


def hstore(s):
    return dict(re.findall(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"', s or ""))


def metres(a, b):
    """Distance between two GPS-unit points."""
    lat = (a[1] + b[1]) / 2 * GPS_UNIT
    dx = (a[0] - b[0]) * GPS_UNIT * 111320 * math.cos(math.radians(lat))
    dy = (a[1] - b[1]) * GPS_UNIT * 110574
    return math.hypot(dx, dy)


@dataclass(slots=True)
class Road:
    """Segment attributes (one OSM way)."""
    name: str
    cls: int
    fow: int
    oneway: int          # 0 both, 1 start -> end (OSM way direction), 2 end -> start, 3 closed
    kind: int = 0        # 5 = not routable
    figure: int = 0      # +17 low nibble: 6 roundabout, 3 restricted
    access: int = 2      # +17 high nibble: 2 normal, 4 destination only, 1 never
    paved: int = 1
    osm_id: str = ""
    ref: str = None
    city: str = None
    muni: str = None
    settlement: str = None


@dataclass(slots=True)
class Edge:
    a: tuple             # start node (GPS units)
    b: tuple             # end node
    shape: list          # points between a and b
    road: Road
    length: int = 0      # metres

    def points(self):
        return [self.a, *self.shape, self.b]


@dataclass
class Network:
    edges: list = field(default_factory=list)
    nodes: dict = field(default_factory=dict)    # point -> list of edge indexes


def road_attrs(highway, tags, name, detail="normal"):
    """CARiN attributes of an OSM road, None if it is left out. detail "normal" also leaves out
    tracks and unnamed service roads (about half of all OSM roads; Navteq had few of them)."""
    if highway not in HIGHWAYS or (highway == "service" and tags.get("service") in SKIP_SERVICE):
        return None
    if detail == "normal" and (highway == "track" or (highway == "service" and not name)):
        return None
    cls, fow = HIGHWAYS[highway]
    oneway = {"yes": 1, "true": 1, "1": 1, "-1": 2, "reverse": 2}.get(tags.get("oneway"), 0)
    if highway in ("motorway", "motorway_link") and tags.get("oneway") != "no":
        oneway = oneway or 1
    figure, access, kind = 0, 2, 0
    if tags.get("junction") in ("roundabout", "circular"):
        figure, oneway = 6, oneway or 1
    if highway == "trunk" and oneway:
        fow = 4                                  # dual carriageway
    elif highway in ("primary", "secondary") and oneway and _int(tags.get("lanes")) >= 2:
        fow = 4
    if tags.get("access") in ("private", "destination", "delivery", "customers") or \
            tags.get("motor_vehicle") in ("private", "destination"):
        figure, access = 3, 4
    if tags.get("access") == "no" or tags.get("motor_vehicle") == "no":
        figure, access = 3, 1
    if highway == "track" and tags.get("tracktype", "grade2") not in ("grade1",):
        kind = 5
    if not tags.get("ref") is None and fow == 12:
        fow = 11
    paved = 0 if tags.get("surface") in UNPAVED or highway == "track" else 1
    return Road(fold(name), cls, fow, oneway, kind, figure, access, paved, ref=fold(tags.get("ref")))


def _int(v, default=0):
    try:
        return int(str(v).split(";")[0])
    except ValueError:
        return default


def _linestring(blob):
    """GeoPackage geometry blob -> list of (lon, lat)."""
    flags = blob[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    wkb = blob[8 + env:]
    order = "<" if wkb[0] == 1 else ">"
    kind, n = struct.unpack_from(order + "II", wkb, 1)
    if kind != 2:
        return []
    return [struct.unpack_from(order + "dd", wkb, 9 + 16 * i) for i in range(n)]


def load(gpkg, bbox, detail="normal"):
    """Network of the roads whose bounding box lies in bbox (lon0, lat0, lon1, lat1); gpkg = one
    GeoPackage or a list (rows deduplicated by OSM id)."""
    from .osmsrc import rows as osm_rows
    rows = osm_rows(gpkg,
        "SELECT l.osm_id, l.name, l.highway, l.other_tags, l.geom FROM lines l "
        "JOIN rtree_lines_geom r ON l.fid = r.id WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? "
        "AND r.miny <= ? AND l.highway IS NOT NULL", (bbox[0], bbox[2], bbox[1], bbox[3]))
    ways = []
    for osm_id, name, highway, other, geom in rows:
        tags = hstore(other)
        road = road_attrs(highway, tags, name, detail)
        if road is None:
            continue
        road.osm_id = osm_id
        pts = []
        for lon, lat in _linestring(geom):
            if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                if pts:              # cut the way where it leaves the box
                    ways.append((road, pts))
                    pts = []
                continue
            p = gps(lon, lat)
            if not pts or pts[-1] != p:
                pts.append(p)
        if len(pts) >= 2:
            ways.append((road, pts))
    return build(ways)


def build(ways):
    """Edges between nodes: way ends and vertices used by more than one way (or twice by one)."""
    use = {}
    for _, pts in ways:
        for p in pts:
            use[p] = use.get(p, 0) + 1
    net = Network()
    for road, pts in ways:
        start = 0
        for i in range(1, len(pts)):
            if i == len(pts) - 1 or use[pts[i]] > 1:
                seg = pts[start:i + 1]
                if len(set(seg)) >= 2:
                    _add(net, road, seg)
                start = i
    return net


MAX_LENGTH = 30000      # metres; +12 is a u16, long edges are split


def _add(net, road, seg):
    length = sum(metres(seg[i], seg[i + 1]) for i in range(len(seg) - 1))
    if (length > MAX_LENGTH or seg[0] == seg[-1]) and len(seg) > 2:     # long edges and loops
        mid = len(seg) // 2
        _add(net, road, seg[:mid + 1])
        _add(net, road, seg[mid:])
        return
    e = Edge(seg[0], seg[-1], seg[1:-1], road, max(1, round(length)))
    net.edges.append(e)
    for p in (e.a, e.b):
        net.nodes.setdefault(p, []).append(len(net.edges) - 1)
