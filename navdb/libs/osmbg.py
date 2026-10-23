"""Background (map picture) from OpenStreetMap, 6 levels, for the encoder (docs/format.md section 5).

Areas (slot 1): 3 forest / park, 5 built-up, 6 cemetery, 8 land (islands), 1 water, drawn in this
order; lines (slot 2): 101 rivers and canals, 102 railways, 104 / 105 / 106 roads by class (our
road network: class 0-1 / 2 / 3), named by their road number. Every level has fixed unit sizes and
point steps as in the original; shapes are simplified, small areas dropped and everything clipped
to the unit box. Units are written as pbp leaves them in RAM (bgfmt).
"""
import math
import sqlite3
import struct
from dataclasses import dataclass

from . import bgfmt
from .carindb import BLOCK
from .levels import simplify
from .osmnet import fold, hstore
from .osmplaces import _polygons, _env
from .osmnet import gps

KIND = {0: 0x16, 1: 0x15, 2: 0x1C, 3: 0x14, 4: 0x1D, 5: 0x1E}
TABLE = {0: 6, 1: 0x16, 2: 0x15, 3: 0x1C, 4: 0x14, 5: 0x1D}
UNIT = {0: 1 << 20, 1: 1 << 21, 2: 1 << 22, 3: 1 << 24, 4: 1 << 25, 5: 1 << 26}
MIN_UNIT = {0: 1 << 18, 1: 1 << 18, 2: 1 << 18, 3: 1 << 24, 4: 1 << 25, 5: 1 << 26}
MIN_AREA = {0: 1e4, 1: 1e5, 2: 5e5, 3: 3e6, 4: 2e7, 5: 1e8}          # m2
TOLERANCE = {0: 6, 1: 25, 2: 60, 3: 200, 4: 600, 5: 2000}           # metres
AREA_ORDER = (3, 5, 6, 8, 1)
LINES = {0: (101, 102, 104, 105, 106), 1: (101, 104, 105, 106), 2: (101, 104, 105), 3: (101, 104),
         4: (101, 104), 5: ()}
ROAD_TYPE = {0: 104, 1: 104, 2: 105, 3: 106}
MAX_UNIT = 8 * BLOCK - 256


@dataclass(eq=False, slots=True)
class Shape:
    kind: int            # area or line type
    name: str
    points: list         # GPS units; areas: one ring, not closed
    area: float = 0.0    # m2 (areas)
    label: tuple = None
    levels: tuple = (0, 5)   # first and last level the shape is drawn on


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
    from .osmsrc import rows
    shapes = []
    q = ("SELECT coalesce('r' || m.osm_id, 'w' || m.osm_way_id), m.name, m.natural, m.landuse, m.leisure, m.amenity, m.place, m.other_tags, m.geom "
         "FROM multipolygons m JOIN rtree_multipolygons_geom r ON m.fid = r.id "
         "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND "
         "(m.natural IN ('water', 'wood') OR m.landuse IN ('forest', 'reservoir', 'basin', 'cemetery', "
         "'residential', 'commercial', 'retail', 'industrial') OR m.leisure IN ('park', 'nature_reserve', "
         "'garden') OR m.amenity = 'grave_yard' OR m.place IN ('island', 'islet') OR "
         "m.other_tags LIKE '%riverbank%')")
    for _, name, nat, land, leis, amen, place, other, geom in rows(gpkg, q, (bbox[0], bbox[2], bbox[1], bbox[3])):
        tags = hstore(other)
        tags.update({k: v for k, v in (("natural", nat), ("landuse", land), ("leisure", leis),
                                       ("amenity", amen), ("place", place)) if v})
        kind = _area_kind(tags)
        if kind is None:
            continue
        for outer, inners in _all_rings(geom):
            ring = outer[:-1] if outer[0] == outer[-1] else outer
            shapes.append(Shape(kind, fold(name) if kind != 5 else None, ring, _metres_area(ring), _centre(ring),
                                (0, 1) if kind == 5 else (0, 5)))     # landuse built-up: fine levels only
            if kind == 1:                       # islands in water: land drawn over it
                for inner in inners:
                    r = inner[:-1] if inner[0] == inner[-1] else inner
                    shapes.append(Shape(8, None, r, _metres_area(r), _centre(r)))
    for name, ring in towns:                    # towns as named built-up areas on the coarse levels
        shapes.append(Shape(5, name, ring, _metres_area(ring), _centre(ring), (2, 5)))
    for _, name, waterway, railway, geom in rows(gpkg,
            "SELECT l.osm_id, l.name, l.waterway, l.railway, l.geom FROM lines l JOIN rtree_lines_geom r ON l.fid = r.id "
            "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? AND "
            "(l.waterway IN ('river', 'canal') OR l.railway = 'rail')", (bbox[0], bbox[2], bbox[1], bbox[3])):
        from .osmnet import _linestring
        pts = [gps(*p) for p in _linestring(geom)]
        if len(pts) >= 2:
            shapes.append(Shape(101 if waterway else 102, fold(name) if waterway else None, pts))
    river_len = {}
    for s in shapes:
        if s.kind == 101 and s.name:
            river_len[s.name] = river_len.get(s.name, 0) + sum(
                math.hypot((s.points[i + 1][0] - s.points[i][0]) * 0.62, s.points[i + 1][1] - s.points[i][1])
                for i in range(len(s.points) - 1)) * 1.8e-7 * 110574
    for s in shapes:                            # rivers on the coarse levels by their length here
        if s.kind == 101:
            km = river_len.get(s.name, 0) / 1000 if s.name else 0
            s.levels = (0, 0 if km < 5 else 1 if km < 20 else 2 if km < 50 else 4)
    for e in edges:
        if e.road.cls <= 3 and e.road.kind != 5:
            shapes.append(Shape(ROAD_TYPE[e.road.cls], e.road.ref, e.points()))
    return shapes


def merge_lines(shapes):
    """Lines of the same type and name that meet end to end become one polyline (short road
    edges would vanish on the coarse point grids)."""
    areas = [s for s in shapes if s.kind < 100]
    groups = {}
    for s in shapes:
        if s.kind >= 100:
            groups.setdefault((s.kind, s.name, s.levels), []).append(s.points)
    out = list(areas)
    for (kind, name, lv), lines in groups.items():
        ends = {}
        for i, pts in enumerate(lines):
            ends.setdefault(pts[0], []).append(i)
            ends.setdefault(pts[-1], []).append(i)
        used = set()
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
            out.append(Shape(kind, name, chain, levels=lv))
    return out


def _weight(s):
    """Importance for dropping: areas by m2, lines by length squared (m2)."""
    if s.kind < 100:
        return s.area
    length = sum(math.hypot((s.points[i + 1][0] - s.points[i][0]) * 0.62, s.points[i + 1][1] - s.points[i][1])
                 for i in range(len(s.points) - 1)) * 1.8e-7 * 110574
    return length * length


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
    """Shapes kept on a level, simplified."""
    out = []
    for s in shapes:
        if not s.levels[0] <= level <= s.levels[1]:
            continue
        if s.kind < 100:
            if s.area < MIN_AREA[level]:
                continue
            pts = simplify(s.points + [s.points[0]], TOLERANCE[level])[:-1]
            if len(pts) >= 3:
                out.append(Shape(s.kind, s.name, pts, s.area, s.label, s.levels))
        elif s.kind in LINES[level]:
            pts = simplify(s.points, TOLERANCE[level])
            out.append(Shape(s.kind, s.name, pts, levels=s.levels))
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


def tiles(level, area_box, shapes, origin):
    """[(box, shapes)] of a level: fixed unit size, split while a unit gets too big, then the
    smallest areas are dropped."""
    size = UNIT[level]
    ox, oy = origin
    x = ox + (area_box[0] - ox) // size * size
    out = []
    while x < area_box[2]:
        y = oy + (area_box[1] - oy) // size * size
        while y < area_box[3]:
            out += _fit(level, (x, y, x + size, y + size), shapes)
            y += size
        x += size
    if not out:          # every level gets a unit, so no background table is empty
        x = ox + (area_box[0] - ox) // size * size
        y = oy + (area_box[1] - oy) // size * size
        out = [((x, y, x + size, y + size), [])]
    return out


def _size(level, box, shapes):
    """Used bytes of the unit, or a large number when the offsets overflow."""
    try:
        data = unit_bytes(level, box, shapes, 0)
    except (struct.error, ValueError):
        return 1 << 30
    return 0 if data is None else len(data.rstrip(b"\0"))


def _fit(level, box, shapes):
    inside = [s for s in shapes if _overlaps(s.points, box)]
    if not inside:
        return []
    used = _size(level, box, inside)
    if used == 0:
        return []
    if used <= MAX_UNIT:
        return [(box, inside)]
    size = box[2] - box[0]
    if size // 2 >= MIN_UNIT[level]:
        h = size // 2
        return [t for dx in (0, h) for dy in (0, h)
                for t in _fit(level, (box[0] + dx, box[1] + dy, box[0] + dx + h, box[1] + dy + h), inside)]
    keep = sorted(inside, key=lambda s: -_weight(s))
    while keep and _size(level, box, keep) > MAX_UNIT:
        keep = keep[:int(len(keep) * 0.9)]
    return [(box, keep)] if keep else []


def _overlaps(pts, box):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs) < box[2] and max(xs) > box[0] and min(ys) < box[3] and max(ys) > box[1]
