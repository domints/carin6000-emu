"""Background (map picture) from OpenStreetMap, 6 levels, for the encoder (docs/format.md section 5).

Areas (slot 1): 3 forest / park, 5 built-up, 6 cemetery, 8 land (islands), 1 water, drawn in this
order; only towns (built-up areas of places) and water are named, as on the original (parks and
nature reserves would label the map instead of the towns). Lines (slot 2): 101 rivers and canals,
102 railways, 104 / 105 / 106 roads by class (our road network: class 0-1 / 2 / 3), named by
their road number. Every level has fixed unit sizes and point steps as in the original; shapes
are simplified, small areas dropped and everything clipped to the unit box. Units are written as
pbp leaves them in RAM (bgfmt).
"""
import math
from collections import Counter
import sqlite3
import struct
from dataclasses import dataclass

from . import bgfmt
from .carindb import BLOCK
from .levels import simplify
from .par import pmap
from .osmnet import fold, hstore
from .osmplaces import _polygons, _env
from .osmnet import gps

KIND = {0: 0x16, 1: 0x15, 2: 0x1C, 3: 0x14, 4: 0x1D, 5: 0x1E}
TABLE = {0: 6, 1: 0x16, 2: 0x15, 3: 0x1C, 4: 0x14, 5: 0x1D}
UNIT = {0: 1 << 21, 1: 1 << 22, 2: 1 << 23, 3: 1 << 24, 4: 1 << 25, 5: 1 << 26}
MIN_UNIT = {0: 1 << 18, 1: 1 << 18, 2: 1 << 18, 3: 1 << 24, 4: 1 << 25, 5: 1 << 26}   # levels 3-5: one
                                # unit size only (as the original); a full unit drops shapes (_weight)
MIN_AREA = {0: 2e4, 1: 5e5, 2: 2e6, 3: 3e6, 4: 2e7, 5: 1e8}          # m2 (the original: 2e4, 4e5, 2e6)
TOLERANCE = {0: 6, 1: 40, 2: 100, 3: 200, 4: 600, 5: 2000}          # metres
AREA_ORDER = (3, 5, 6, 8, 1)
AREA_LEVELS = {5: (0, 1), 3: (0, 2), 6: (0, 1)}  # landuse built-up, forest / park, cemetery (as the
                                                # original: towns, water and main roads above)
RIVER_NAME_KM = 20                              # shorter rivers and canals stay unnamed
LINES = {0: (101, 102, 104, 105, 106), 1: (101, 104, 105, 106), 2: (101, 104, 105), 3: (101, 104),
         4: (101, 104), 5: ()}
ROAD_TYPE = {0: 104, 1: 105, 2: 106}            # routing class -> line type, as the original (checked on
                                                # Warsaw: 104 = class 0, 105 = 1, 106 = 2, no class 3;
                                                # the device leaves some types out on some zooms)
ROAD_CLASSES = {0: 2, 1: 2, 2: 1, 3: 0, 4: 0}     # highest road class drawn per level (the original:
                                                # 104-106 on levels 0-1, 104-105 on 2, 104 on 3-4)
ROAD_CELL = {0: 25, 1: 60, 2: 150, 3: 400, 4: 1000}   # metres: a road along an earlier one (the other
                                                    # carriageway, a parallel service road) is left out
LINK_FOWS = (1, 3, 10)                          # slip roads are not drawn
MAX_UNIT = 8 * BLOCK - 256
INDEX_CELL = {0: 1 << 22, 1: 1 << 22, 2: 1 << 22, 3: 1 << 29, 4: 1 << 29, 5: 1 << 29}   # spatial index
                                # cell (N 128 / 1, encoder.BACKGROUND)
INDEX_UNITS = 500               # units named in one index cell: its kind 9 unit then stays within 5
                                # blocks (as the original's largest); with ~1000 (up to 9 blocks, more
                                # than a unit may have) the device read the index and drew no level 0


@dataclass(eq=False, slots=True)
class Shape:
    kind: int            # area or line type
    name: str
    points: list         # GPS units; areas: one ring, not closed
    area: float = 0.0    # m2 (areas)
    label: tuple = None
    levels: tuple = (0, 5)   # first and last level the shape is drawn on
    bbox: tuple = None       # (x0, y0, x1, y1), set by _box()


def _box(s):
    if s.bbox is None:
        xs = [p[0] for p in s.points]
        ys = [p[1] for p in s.points]
        s.bbox = (min(xs), min(ys), max(xs), max(ys))
    return s.bbox


def _metres_area(ring):
    if len(ring) < 3:
        return 0.0
    lat = math.radians(sum(p[1] for p in ring) / len(ring) * 1.8e-7)
    sx, sy = 1.8e-7 * 111320 * math.cos(lat), 1.8e-7 * 110574
    a = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2 * sx * sy


def _area_kind(tags):
    nat, land, leis, amen, place = (tags.get(k) for k in ("natural", "landuse", "leisure", "amenity", "place"))
    if nat == "water" or land in ("reservoir", "basin") or tags.get("waterway") == "riverbank":
        return 1
    if land in ("forest",) or nat in ("wood",) or leis in ("park", "nature_reserve", "garden"):
        return 3
    if land in ("cemetery",) or amen == "grave_yard":
        return 6
    if place in ("island", "islet"):
        return 8
    if land in ("residential", "commercial", "retail", "industrial"):
        return 5
    return None


def _all_rings(blob):
    """Outer and inner rings of a (multi)polygon blob: [(outer, [inner...])]"""
    wkb = blob[8 + _env(blob):]
    out = []

    def poly(p):
        order = "<" if wkb[p] == 1 else ">"
        n_rings, = struct.unpack_from(order + "I", wkb, p + 5)
        p += 9
        rings = []
        for _ in range(n_rings):
            n, = struct.unpack_from(order + "I", wkb, p)
            rings.append([gps(*struct.unpack_from(order + "dd", wkb, p + 4 + 16 * i)) for i in range(n)])
            p += 4 + 16 * n
        if rings:
            out.append((rings[0], rings[1:]))
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
    return out


def load(gpkg, bbox, edges, towns):
    """Shapes of the area: OSM areas and lines, our road edges (class <= 3), town areas (admin
    level 8 areas of places that are towns: [(name, ring)])."""
    from .osmsrc import prows
    q = ("SELECT coalesce('r' || m.osm_id, 'w' || m.osm_way_id), m.name, m.natural, m.landuse, m.leisure, m.amenity, m.place, m.other_tags, m.geom "
         "FROM multipolygons m JOIN rtree_multipolygons_geom r ON m.fid = r.id "
         "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND "
         "(m.natural IN ('water', 'wood') OR m.landuse IN ('forest', 'reservoir', 'basin', 'cemetery', "
         "'residential', 'commercial', 'retail', 'industrial') OR m.leisure IN ('park', 'nature_reserve', "
         "'garden') OR m.amenity = 'grave_yard' OR m.place IN ('island', 'islet') OR "
         "m.other_tags LIKE '%riverbank%')")
    shapes = prows(gpkg, q, (bbox[0], bbox[2], bbox[1], bbox[3]), _areas)
    for name, ring in towns:                    # towns as named built-up areas on the coarse levels
        shapes.append(Shape(5, name, ring, _metres_area(ring), _centre(ring), (1, 5)))
    shapes += prows(gpkg,
            "SELECT l.osm_id, l.name, l.waterway, l.railway, l.geom FROM lines l JOIN rtree_lines_geom r ON l.fid = r.id "
            "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND "
            "(l.waterway IN ('river', 'canal') OR l.railway = 'rail')", (bbox[0], bbox[2], bbox[1], bbox[3]), _lines)
    return _finish(shapes, edges)


def _lines(rows):
    """River, canal and railway shapes of the rows (in a worker)."""
    from .osmnet import _linestring
    out = []
    for _, name, waterway, railway, geom in rows:
        pts = simplify([gps(*p) for p in _linestring(geom)], TOLERANCE[0])
        if len(pts) >= 2:
            out.append(Shape(101 if waterway else 102, fold(name) if waterway else None, pts))
    return out


def _areas(rows):
    """Area shapes of the rows (in a worker)."""
    shapes = []
    for _, name, nat, land, leis, amen, place, other, geom in rows:
        tags = hstore(other)
        tags.update({k: v for k, v in (("natural", nat), ("landuse", land), ("leisure", leis),
                                       ("amenity", amen), ("place", place)) if v})
        kind = _area_kind(tags)
        if kind is None:
            continue
        for outer, inners in _all_rings(geom):
            outer = simplify(outer, TOLERANCE[0])          # full OSM detail is never drawn
            ring = outer[:-1] if outer[0] == outer[-1] else outer
            if len(ring) < 3:
                continue
            shapes.append(Shape(kind, fold(name) if kind == 1 else None, ring, _metres_area(ring), _centre(ring),
                                AREA_LEVELS.get(kind, (0, 5))))
            if kind == 1:                       # islands in water: land drawn over it
                for inner in inners:
                    inner = simplify(inner, TOLERANCE[0])
                    r = inner[:-1] if inner[0] == inner[-1] else inner
                    if len(r) < 3:
                        continue
                    shapes.append(Shape(8, None, r, _metres_area(r), _centre(r)))
    return shapes


def _finish(shapes, edges):
    """Rivers get their levels by length; our roads (class <= 3) are added."""
    river_len = {}
    for s in shapes:
        if s.kind == 101 and s.name:
            river_len[s.name] = river_len.get(s.name, 0) + sum(
                math.hypot((s.points[i + 1][0] - s.points[i][0]) * 0.62, s.points[i + 1][1] - s.points[i][1])
                for i in range(len(s.points) - 1)) * 1.8e-7 * 110574
    for s in shapes:                            # rivers on the coarse levels by their length here
        if s.kind == 101:
            km = river_len.get(s.name, 0) / 1000 if s.name else 0
            s.levels = (0, 0 if km < 5 else 1 if km < 20 else 2 if km < 150 else 4)
            if km < RIVER_NAME_KM:
                s.name = None
    edges = [e for e in edges if e.road.cls <= 2 and e.road.kind != 5 and e.road.fow not in LINK_FOWS]
    for part in pmap(lambda level: road_lines(edges, level), sorted(ROAD_CELL), 2):
        shapes += part
    return shapes


def road_lines(edges, level):
    """The roads of a level as lines: classes up to ROAD_CLASSES, edges of one road (class, number)
    joined into chains first, then main roads and long chains first; a stretch that runs along roads
    already taken (its sample points within a ROAD_CELL cell of them, at an end or for at least 5 cells: the other
    carriageway, a parallel road) is left out, as the original draws one line per road. Every
    carriageway as its own line, in edge-long pieces, filled the units with roads."""
    k = 1.8e-7 * 110574 / ROAD_CELL[level]          # GPS units -> cells
    taken = set()
    out = []

    def cell(x, y):
        return int(x * 0.62 * k), int(y * k)

    groups = {}
    for e in edges:
        if e.road.cls <= ROAD_CLASSES[level]:
            groups.setdefault((e.road.cls, e.road.ref), []).append(e.points())
    chains = [(cls, ref, pts) for (cls, ref), lines in groups.items() for pts in _chains(lines)]
    for cls, ref, pts in sorted(chains, key=lambda c: (c[0], -sum(
            math.hypot((c[2][i + 1][0] - c[2][i][0]) * 0.62, c[2][i + 1][1] - c[2][i][1]) for i in range(len(c[2]) - 1)))):
        segs = []                                   # per segment: its cells, covered or not
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            cells_long = math.hypot((bx - ax) * 0.62, by - ay) * k
            n = max(1, int(cells_long))
            cs = [cell(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n + 1)]
            near = sum(1 for cx, cy in cs if any((cx + dx, cy + dy) in taken for dx in (-1, 0, 1) for dy in (-1, 0, 1)))
            segs.append((cs, near >= 0.8 * len(cs), cells_long))
        drop = [False] * len(segs)
        i = 0
        while i < len(segs):                        # covered runs at an end of the chain, or of at least
            j = i                                   # 5 cells, are left out (a crossing covers 3)
            while j < len(segs) and segs[j][1]:
                j += 1
            if j > i and (i == 0 or j == len(segs) or sum(segs[m][2] for m in range(i, j)) >= 5):
                drop[i:j] = [True] * (j - i)
            i = max(j, i + 1)
        piece = [pts[0]]
        for m, (cs, _, _) in enumerate(segs):
            if drop[m]:
                if len(piece) > 1:
                    out.append(Shape(ROAD_TYPE[cls], ref, piece, levels=(level, level)))
                piece = [pts[m + 1]]
            else:
                taken.update(cs)
                piece.append(pts[m + 1])
        if len(piece) > 1:
            out.append(Shape(ROAD_TYPE[cls], ref, piece, levels=(level, level)))
    return out


def _chains(lines):
    """Polylines that meet end to end (not at a junction of three or more) joined into one."""
    ends = {}
    for i, pts in enumerate(lines):
        ends.setdefault(pts[0], []).append(i)
        ends.setdefault(pts[-1], []).append(i)
    used = set()
    out = []
    for i in range(len(lines)):
        if i in used:
            continue
        used.add(i)
        chain = list(lines[i])
        for forward in (True, False):        # grow at the end, then at the start
            while True:
                tip = chain[-1] if forward else chain[0]
                cands = [k for k in ends.get(tip, ()) if k not in used]
                if not cands or len(ends[tip]) > 2:  # nothing to add, or a junction
                    break
                k = cands[0]
                used.add(k)
                seg = lines[k]
                if forward:
                    seg = seg if seg[0] == tip else seg[::-1]
                    chain = chain + seg[1:]
                else:
                    seg = seg if seg[-1] == tip else seg[::-1]
                    chain = seg[:-1] + chain
        out.append(chain)
    return out


def merge_lines(shapes):
    """Lines of the same type and name that meet end to end become one polyline (short road
    edges would vanish on the coarse point grids)."""
    groups = {}
    for s in shapes:
        if s.kind >= 100:
            groups.setdefault((s.kind, s.name, s.levels), []).append(s.points)
    out = [s for s in shapes if s.kind < 100]
    for (kind, name, lv), lines in groups.items():
        out += [Shape(kind, name, chain, levels=lv) for chain in _chains(lines)]
    return out


def _weight(s, level):
    """Importance for dropping, kept longest first: main roads (104) and big towns (20 x the
    level's smallest area); roads 105, big water and named rivers; roads 106 and areas of 5 x the
    smallest; the rest. Within a group areas by m2, lines by length squared (m2). The map draws the
    roads from the background on every level (not from the routing parcels): a unit without its
    roads shows a square without roads."""
    town = s.kind == 5 and s.name and s.area >= 20 * MIN_AREA[level]
    water = s.kind == 1 and s.area >= 20 * MIN_AREA[level]
    rank = (3 if s.kind == 104 or town else 2 if s.kind == 105 or water or (s.kind == 101 and s.name) else
            1 if s.kind == 106 or (s.kind < 100 and s.area >= 5 * MIN_AREA[level]) else 0)
    if s.kind < 100:
        return rank, s.area
    length = sum(math.hypot((s.points[i + 1][0] - s.points[i][0]) * 0.62, s.points[i + 1][1] - s.points[i][1])
                 for i in range(len(s.points) - 1)) * 1.8e-7 * 110574
    return rank, length * length


def name_builtup(shapes, place_of, towns):
    """Built-up areas of the fine levels get the name of the place at their label point (a village,
    a town's district): only the largest area of each place, so one label each, as the original;
    not the towns (their own areas are named from level 1)."""
    best = {}
    for s in shapes:
        if s.kind == 5 and s.name is None and s.levels == AREA_LEVELS[5]:
            name = place_of(s.label)
            if name and name not in towns and (name not in best or s.area > best[name].area):
                best[name] = s
    for name, s in best.items():
        s.name = name


def _centre(ring):
    return (sum(p[0] for p in ring) // len(ring), sum(p[1] for p in ring) // len(ring))


def _clip_polygon(ring, box):
    x0, y0, x1, y1 = box
    pts = ring
    for axis, edge, keep_ge in ((0, x0, True), (0, x1, False), (1, y0, True), (1, y1, False)):
        out = []
        if not pts:
            break
        for i in range(len(pts)):
            a, b = pts[i - 1], pts[i]
            ina = a[axis] >= edge if keep_ge else a[axis] <= edge
            inb = b[axis] >= edge if keep_ge else b[axis] <= edge
            if inb:
                if not ina:
                    out.append(_cut(a, b, axis, edge))
                out.append(b)
            elif ina:
                out.append(_cut(a, b, axis, edge))
        pts = out
    return pts


def _cut(a, b, axis, edge):
    t = (edge - a[axis]) / (b[axis] - a[axis])
    p = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]
    p[axis] = edge
    return (round(p[0]), round(p[1]))


def _clip_line(pts, box):
    """Parts of a polyline inside box."""
    x0, y0, x1, y1 = box
    parts, cur = [], []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        t0, t1 = 0.0, 1.0
        dx, dy = b[0] - a[0], b[1] - a[1]
        ok = True
        for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
            if p == 0:
                if q < 0:
                    ok = False
                    break
            else:
                t = q / p
                if p < 0:
                    t0 = max(t0, t)
                else:
                    t1 = min(t1, t)
        if not ok or t0 > t1:
            if len(cur) >= 2:
                parts.append(cur)
            cur = []
            continue
        pa = (round(a[0] + t0 * dx), round(a[1] + t0 * dy))
        pb = (round(a[0] + t1 * dx), round(a[1] + t1 * dy))
        if not cur or cur[-1] != pa:
            if len(cur) >= 2:
                parts.append(cur)
            cur = [pa]
        cur.append(pb)
        if t1 < 1.0:
            parts.append(cur)
            cur = []
    if len(cur) >= 2:
        parts.append(cur)
    return parts


def clip_to_area(shapes, box):
    """Only the encoded area gets a background: every shape is cut to its box."""
    out = []
    for s in shapes:
        if s.kind < 100:
            ring = _clip_polygon(s.points, box)
            if len(ring) >= 3:
                out.append(Shape(s.kind, s.name, ring, s.area, s.label, s.levels))
        else:
            out += [Shape(s.kind, s.name, part, levels=s.levels) for part in _clip_line(s.points, box)]
    return out


def level_shapes(shapes, level):
    """Shapes kept on a level (simplified later, per unit cell: tiles())."""
    return [s for s in shapes if s.levels[0] <= level <= s.levels[1] and
            (s.area >= MIN_AREA[level] if s.kind < 100 else s.kind in LINES[level])]


def _simplified(shapes, level, factor=1):
    out = []
    for s in shapes:
        if s.kind < 100:
            pts = simplify(s.points + [s.points[0]], TOLERANCE[level] * factor)[:-1]
            if len(pts) >= 3:
                out.append(Shape(s.kind, s.name, pts, s.area, s.label, s.levels))
        else:
            out.append(Shape(s.kind, s.name, simplify(s.points, TOLERANCE[level] * factor), levels=s.levels))
    return out


def unit_bytes(level, box, shapes, own, force=False):
    """A background unit (bgfmt image) for the shapes clipped to box; None if empty (an empty
    unit when force)."""
    step = 6 + level
    x0, y0 = box[0], box[1]
    areas, lines = [], []
    for s in shapes:
        if s.kind < 100:
            ring = _clip_polygon(s.points, box)
            ring = _grid(ring, x0, y0, step)
            if len(ring) >= 3:
                areas.append((s, ring))
        else:
            for part in _clip_line(s.points, box):
                part = _grid(part, x0, y0, step)
                if len(part) >= 2:
                    lines.append((s, part))
    if not areas and not lines and not force:
        return None
    areas.sort(key=lambda a: (AREA_ORDER.index(a[0].kind), -a[0].area))
    lines.sort(key=lambda l: l[0].kind)
    groups = []
    texts = []
    for s, _ in areas + lines:
        if s.name and s.name not in texts:
            texts.append(s.name)
    n_groups = len({(0, s.kind) for s, _ in areas} | {(1, s.kind) for s, _ in lines})
    o0 = bgfmt.HEADER
    o1 = o0 + 4 * (n_groups + 1)
    o2 = o1 + 20 * (len(areas) + 1)
    o3 = o2 + 16 * (len(lines) + 1) if lines else o2
    n_pts = sum(len(p) for _, p in areas + lines)
    o5 = o3 + 4 * n_pts
    n_rec = len(areas) + len(lines)
    text_at, pos = {}, o5 + 4 * n_rec
    for t in texts:
        text_at[t] = pos
        pos += len(t) + 1
    r0, r1, r2, r3 = b"", b"", b"", b""
    p = o3
    last = None
    for i, (s, ring) in enumerate(areas):
        if last != (0, s.kind):
            r0 += struct.pack(">BBH", s.kind, 0, o1 + 20 * i)
            last = (0, s.kind)
        r1 += struct.pack(">HHIiiHH", text_at.get(s.name, 0), p, min(int(s.area), 0xFFFFFFFF), s.label[0], s.label[1],
                          0, o5 + 4 * i)
        r3 += b"".join(struct.pack(">HH", x, y) for x, y in ring)
        p += 4 * len(ring)
    r1 += struct.pack(">HHIiiHH", 0, p, 0, 0, 0, 0, 0)
    for i, (s, part) in enumerate(lines):
        if last != (1, s.kind):
            r0 += struct.pack(">BBH", s.kind, 1, o2 + 16 * i)
            last = (1, s.kind)
        length = sum(math.hypot((part[k + 1][0] - part[k][0]) * 0.62, part[k + 1][1] - part[k][1])
                     for k in range(len(part) - 1)) * (1 << step) * 1.8e-7 * 110574
        r2 += struct.pack(">HHIHHI", text_at.get(s.name, 0), p, int(length), o5 + 4 * (len(areas) + i), 0, 0)
        r3 += b"".join(struct.pack(">HH", x, y) for x, y in part)
        p += 4 * len(part)
    if lines:
        r2 += struct.pack(">HHIHHI", 0, p, 0, 0, 0, 0)
    r0 += struct.pack(">BBH", 0, 0, (o2 + 16 * len(lines)) if lines else (o1 + 20 * len(areas)))
    r5 = bytes(4 * n_rec) + b"".join(t.encode("latin1") + b"\0" for t in texts)
    header = bytearray(bgfmt.HEADER)
    struct.pack_into(">IHBB", header, 0, own, KIND[level], 0, 0)
    struct.pack_into(">4i", header, 0x20, *box)
    struct.pack_into(">HBB", header, 0x30, 1, 0, step)
    regions = {0: r0, 1: r1, 2: r2 if lines else None, 3: r3 if n_pts else None, 4: None, 5: r5 if n_rec else None}
    counts = {0: n_groups, 1: len(areas), 2: len(lines), 3: n_pts, 4: 0, 5: n_rec}
    raw = bgfmt.RawBackground(header, counts, regions)
    return bgfmt.write(raw)


def _grid(pts, x0, y0, step):
    out = []
    for x, y in pts:
        q = ((x - x0) >> step, (y - y0) >> step)
        q = (min(max(q[0], 0), 0xFFFF), min(max(q[1], 0), 0xFFFF))
        if not out or out[-1] != q:
            out.append(q)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def tiles(level, area_box, shapes, origin, dropped=None):
    """[(box, unit bytes with pointer 0)] of a level: fixed unit size, split while a unit gets
    too big, then simplified harder, then the least important shapes are dropped (dropped: a
    Counter that gets the number of dropped shapes and roads)."""
    size = UNIT[level]
    ox, oy = origin
    cells = {}                  # unit cell -> shapes whose box reaches into it
    for s in shapes:
        b = _box(s)
        for cx in range((b[0] - ox) // size, (b[2] - ox) // size + 1):
            for cy in range((b[1] - oy) // size, (b[3] - oy) // size + 1):
                cells.setdefault((cx, cy), []).append(s)
    boxes = []
    for cx, cy in sorted(cells):
        x, y = ox + cx * size, oy + cy * size
        if x + size > area_box[0] and x < area_box[2] and y + size > area_box[1] and y < area_box[3]:
            boxes.append(((x, y, x + size, y + size), cells[(cx, cy)]))
    # an index cell (spindex) may name at most INDEX_UNITS units: where more come out, the unit
    # cells of that index cell are made again with a larger smallest unit
    smallest = [MIN_UNIT[level]] * len(boxes)
    parts = [None] * len(boxes)
    todo = list(range(len(boxes)))
    while todo:
        for i, part in zip(todo, pmap(lambda i: _fit(level, boxes[i][0], _simplified(boxes[i][1], level),
                                                     smallest[i]), todo, 4)):
            parts[i] = part
        per_cell = {}
        for i, part in enumerate(parts):
            per_cell.setdefault(_index_cell(boxes[i][0], level, origin), []).append(i)
        todo = []
        for idx in per_cell.values():
            if sum(len(parts[i]) for i in idx) > INDEX_UNITS:
                todo += [i for i in idx if smallest[i] < UNIT[level]]
        for i in todo:
            smallest[i] *= 2
    out = []
    for part in parts:
        for box, data, lost in part:
            out.append((box, data))
            if dropped is not None:
                dropped.update(lost)
    if not out:          # every level gets a unit, so no background table is empty
        x = ox + (area_box[0] - ox) // size * size
        y = oy + (area_box[1] - oy) // size * size
        box = (x, y, x + size, y + size)
        out = [(box, unit_bytes(level, box, [], 0, force=True))]
    return out


def with_pointer(data, own):
    """A unit from tiles() with its own unit pointer."""
    return struct.pack(">I", own) + data[4:]


def _size(level, box, shapes):
    """(used bytes, unit bytes) of the unit; a large number when the offsets overflow."""
    try:
        data = unit_bytes(level, box, shapes, 0)
    except (struct.error, ValueError):
        return 1 << 30, None
    return (0, None) if data is None else (len(data.rstrip(b"\0")), data)


def _index_cell(box, level, origin):
    cell = INDEX_CELL[level]
    return (box[0] - origin[0]) // cell, (box[1] - origin[1]) // cell


def _fit(level, box, shapes, smallest):
    inside = [s for s in shapes if _overlaps(s, box)]
    if not inside:
        return []
    used, data = _size(level, box, inside)
    if used == 0:
        return []
    if used <= MAX_UNIT:
        return [(box, data, ())]
    size = box[2] - box[0]
    if size // 2 >= smallest:
        h = size // 2
        return [t for dx in (0, h) for dy in (0, h)
                for t in _fit(level, (box[0] + dx, box[1] + dy, box[0] + dx + h, box[1] + dy + h), inside, smallest)]
    for factor in (2, 4):                   # lines and rings simplified harder before dropping
        simpler = _simplified(inside, level, factor)
        used, data = _size(level, box, simpler)
        if used <= MAX_UNIT:
            return [(box, data, ())]
    keep = sorted(simpler, key=lambda s: _weight(s, level), reverse=True)
    hi = len(keep)                          # hi does not fit; shrink until n fits, then search
    n = hi
    while n:
        share = MAX_UNIT / used if used < 1 << 30 else 0.5      # 1 << 30: the offsets overflow
        n = min(int(n * 0.9), int(n * share)) if n > 1 else 0
        used, data = _size(level, box, keep[:n])
        if used <= MAX_UNIT:
            break
        hi = n
    best = (n, data)
    lo = n
    while hi - lo > 1:
        mid = (lo + hi) // 2
        used, data = _size(level, box, keep[:mid])
        if used <= MAX_UNIT:
            lo, best = mid, (mid, data)
        else:
            hi = mid
    n, data = best
    if not n:
        return []
    lost = Counter(shapes=len(keep) - n, roads=sum(1 for s in keep[n:] if s.kind in (104, 105, 106)))
    return [(box, data, lost)]


def _overlaps(s, box):
    b = _box(s)
    return b[0] < box[2] and b[2] > box[0] and b[1] < box[3] and b[3] > box[1]
