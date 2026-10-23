"""Routing parcels from a road network (encoder side of ../docs/format.md section 4).

1. tile(): a quadtree of parcel boxes on the global grid (origin and extent from the block 2 index
   directory), split while a box would hold too much;
2. clip(): edges are cut where they cross a parcel border; the cut point becomes an edge point
   (slot 6) in both parcels;
3. Parcel.regions(): the slot regions of one parcel as pbp leaves an unpacked unit in RAM.

Unit pointers between parcels (neighbours, parents) are filled in by the caller through
`ptr_of(parcel)` once the units have blocks.
"""
import math
import struct
from dataclasses import dataclass, field

from .carindb import POINT_STEP
from .osmnet import CLASS_DEFAULTS, DEFAULTS, metres

ORIGIN = (-34998272, -59092992)    # grid origin of every index (block 2 directory), GPS units
EXTENT = 1 << 29
MIN_SIZE = 1 << 15                 # smallest parcel side in the original (32768 units)
MAX_SIZE = 1 << 21                 # largest level 0 parcel side (points are u16 steps of 64)
MAX_BYTES = 12000                  # estimated parcel size limit (units are at most 8 blocks)
SEG = 32                           # level 0 segment record (type 0x08)


def heading(p, q):
    """Bearing p -> q, clockwise from north, 256 steps per turn."""
    lat = math.radians(p[1] * 1.8e-7)
    a = math.atan2((q[0] - p[0]) * math.cos(lat), q[1] - p[1])
    return round(math.degrees(a) % 360 * 256 / 360) & 0xFF


@dataclass(eq=False, slots=True)
class Box:
    x: int
    y: int
    size: int

    def contains(self, p):
        return self.x <= p[0] < self.x + self.size and self.y <= p[1] < self.y + self.size

    def on_border(self, p):
        return p[0] in (self.x, self.x + self.size) or p[1] in (self.y, self.y + self.size)


def aligned_root(bbox_gps):
    """The smallest grid-aligned square box holding the area."""
    size = MIN_SIZE
    while True:
        ax = ORIGIN[0] + ((bbox_gps[0] - ORIGIN[0]) // size) * size
        ay = ORIGIN[1] + ((bbox_gps[1] - ORIGIN[1]) // size) * size
        if ax + size >= bbox_gps[2] and ay + size >= bbox_gps[3]:
            return Box(ax, ay, size)
        size *= 2


def tile(edges, bbox_gps):
    """Leaf boxes covering the edges: start from the smallest aligned box holding the area and
    split while the estimated parcel size exceeds MAX_BYTES."""
    root = aligned_root(bbox_gps)
    ax, ay, size = root.x, root.y, root.size
    load = [(e.points(), 48 + 6 * len(e.shape) + 2 * len(e.road.name or "")) for e in edges]

    def split(box, items):
        if box.size > MAX_SIZE or (box.size > MIN_SIZE and sum(c for _, c in items) > MAX_BYTES):
            h = box.size // 2
            leaves = []
            for dx in (0, h):
                for dy in (0, h):
                    b = Box(box.x + dx, box.y + dy, h)
                    sub = [(pts, c) for pts, c in items if _touches(b, pts)]
                    leaves += split(b, sub)
            return leaves
        return [box] if items else []

    return split(Box(ax, ay, size), load)


def _touches(box, pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs) < box.x + box.size and max(xs) >= box.x and min(ys) < box.y + box.size and max(ys) >= box.y


class Grid:
    """Point -> leaf lookup over the quadtree leaves."""

    def __init__(self, leaves):
        self.leaves = leaves
        self.cell = min(b.size for b in leaves)
        self.index = {}
        for b in leaves:
            for i in range(b.size // self.cell):
                for j in range(b.size // self.cell):
                    self.index[(b.x + i * self.cell, b.y + j * self.cell)] = b

    def leaf(self, p):
        key = (ORIGIN[0] + ((p[0] - ORIGIN[0]) // self.cell) * self.cell,
               ORIGIN[1] + ((p[1] - ORIGIN[1]) // self.cell) * self.cell)
        return self.index.get(key)


@dataclass(eq=False, slots=True)
class Piece:
    """A part of an edge inside one parcel."""
    points: list
    road: object
    length: int
    border: tuple = (False, False)     # start / end is an edge point
    hn: tuple = None                   # house numbers (osmaddr.assign)


@dataclass(eq=False, slots=True)
class Parcel:
    box: Box
    level: int = 0
    pieces: list = field(default_factory=list)
    borders: dict = field(default_factory=dict)     # point -> neighbour Parcel
    parent: object = None
    children: list = field(default_factory=list)
    times: tuple = (0, 0, 0)                         # header 0x60/0x64/0x68
    offsets: dict = field(default_factory=dict)      # point -> offset of its record (after layout)
    seg_base: int = 0                                # offset of slot 4 (after layout)
    turns: dict = None                               # prohibited turns (osmturns.assign)


def _nudge(p, box):
    """Move a vertex lying on its parcel's border one step inside."""
    x, y = p
    if x == box.x:
        x += POINT_STEP
    elif x == box.x + box.size:
        x -= POINT_STEP
    if y == box.y:
        y += POINT_STEP
    elif y == box.y + box.size:
        y -= POINT_STEP
    return x, y


def _exit(p, q, box):
    """Where p -> q leaves box (p inside): point on the border, snapped to the grid, not a corner."""
    t_best, axis = 2.0, None
    for i, lo, hi in ((0, box.x, box.x + box.size), (1, box.y, box.y + box.size)):
        d = q[i] - p[i]
        for edge in (lo, hi):
            if d and 0 < (edge - p[i]) / d < t_best:
                t_best, axis, val = (edge - p[i]) / d, i, edge
    other = 1 - axis
    o = p[other] + t_best * (q[other] - p[other])
    lo = (box.y if other else box.x) + POINT_STEP
    hi = (box.y if other else box.x) + box.size - POINT_STEP
    o = min(max(round(o / POINT_STEP) * POINT_STEP, lo), hi)
    pt = [0, 0]
    pt[axis], pt[other] = val, o
    step = [0, 0]
    step[axis] = 1 if q[axis] > p[axis] else -1
    return tuple(pt), tuple(step)


def nudge_edges(edges, leaves):
    """Moves vertices lying on a parcel border one step inside (once, before clipping and before
    the routing levels are made, so every level sees the same node coordinates)."""
    grid = Grid(leaves)

    def inside(p):
        leaf = grid.leaf(p)
        return _nudge(p, leaf) if leaf and leaf.on_border(p) else p
    for e in edges:
        e.a, e.b, e.shape = inside(e.a), inside(e.b), [inside(p) for p in e.shape]


def clip(edges, leaves):
    """Parcels with the edge pieces inside them. Every line segment is split where it crosses a
    parcel border line, each part goes to the parcel holding its middle, and where the parcel
    changes the crossing point becomes an edge point pair (on the grid, unique per parcel)."""
    import bisect
    grid = Grid(leaves)
    parcels = {id(b): Parcel(b) for b in leaves}
    xs = sorted({v for b in leaves for v in (b.x, b.x + b.size)})
    ys = sorted({v for b in leaves for v in (b.y, b.y + b.size)})
    used = set()
    vertices = {p for e in edges for p in e.points()}    # a cut point must not merge with a vertex

    def crossings(p, q):
        ts = set()
        for lines, i in ((xs, 0), (ys, 1)):
            lo, hi = sorted((p[i], q[i]))
            for v in lines[bisect.bisect_right(lines, lo):bisect.bisect_left(lines, hi)]:
                ts.add((v - p[i]) / (q[i] - p[i]))
        return sorted(t for t in ts if 0 < t < 1)

    def leaf_at(p, q):
        return grid.leaf(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))

    def cut_point(p, q, t, a, b):
        x, y = p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])
        # on the border line shared by a and b: snap the other coordinate to the grid inside both
        if a.x + a.size == b.x or b.x + b.size == a.x:
            bx = b.x if a.x + a.size == b.x else a.x
            lo, hi = max(a.y, b.y) + POINT_STEP, min(a.y + a.size, b.y + b.size) - POINT_STEP
            pt, axis = [bx, min(max(round(y / POINT_STEP) * POINT_STEP, lo), hi)], 1
        else:
            by = b.y if a.y + a.size == b.y else a.y
            lo, hi = max(a.x, b.x) + POINT_STEP, min(a.x + a.size, b.x + b.size) - POINT_STEP
            pt, axis = [min(max(round(x / POINT_STEP) * POINT_STEP, lo), hi), by], 0
        k = 0
        while (id(a), tuple(pt)) in used or (id(b), tuple(pt)) in used or tuple(pt) in vertices:
            k += 1
            pt[axis] += POINT_STEP * k * (-1) ** k
            if not lo <= pt[axis] <= hi:
                return None
        return tuple(pt)

    for e in edges:
        pts = e.points()
        parts = []                               # (point, leaf of the part ending at point)
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            ts = [0.0] + crossings(p, q) + [1.0]
            for k in range(len(ts) - 1):
                a = (p[0] + ts[k] * (q[0] - p[0]), p[1] + ts[k] * (q[1] - p[1]))
                b = (p[0] + ts[k + 1] * (q[0] - p[0]), p[1] + ts[k + 1] * (q[1] - p[1]))
                parts.append((p, q, ts[k + 1], leaf_at(a, b), k + 1 == len(ts) - 1))
        cur = parts[0][3] if parts else None
        piece, start_border = [pts[0]], False
        for n, (p, q, t, leaf, at_vertex) in enumerate(parts):
            if leaf is None:
                cur, piece = None, None
                continue
            if cur is None:                      # coming back into the tiled area: start over
                cur, piece, start_border = leaf, [q if at_vertex else p], False
                continue
            if leaf is not cur:
                # the previous part ended on a border between cur and leaf
                pp, pq, pt_t = parts[n - 1][0], parts[n - 1][1], parts[n - 1][2]
                c = cut_point(pp, pq, pt_t, cur, leaf) if _adjacent(cur, leaf) else None
                if c is None:                    # corner or no shared border: drop this piece
                    cur, piece, start_border = leaf, [q if at_vertex else p], False
                    continue
                if piece[-1] != c:
                    piece.append(c)
                if len(piece) >= 2:
                    pa, pb = parcels[id(cur)], parcels[id(leaf)]
                    used.add((id(cur), c))
                    used.add((id(leaf), c))
                    _emit(pa, piece, e.road, (start_border, True))
                    pa.borders[c], pb.borders[c] = pb, pa
                    cur, piece, start_border = leaf, [c], True
                else:
                    cur, piece, start_border = leaf, [c], False
            if at_vertex and piece[-1] != q:
                piece.append(q)
        if cur is not None and piece and len(piece) >= 2:
            _emit(parcels[id(cur)], piece, e.road, (start_border, False))
    # a border pair needs a piece ending at the point on both sides (a side may have been dropped)
    ends = {id(pc): {p for piece in pc.pieces for p in (piece.points[0], piece.points[-1])}
            for pc in parcels.values()}
    for pc in parcels.values():
        for pt, nb in list(pc.borders.items()):
            if pt not in ends[id(pc)] or pt not in ends[id(nb)]:
                pc.borders.pop(pt, None)
                nb.borders.pop(pt, None)
    return [p for p in parcels.values() if p.pieces]


def _adjacent(a, b):
    """Boxes sharing a border segment (not only a corner)."""
    touch_x = a.x + a.size == b.x or b.x + b.size == a.x
    touch_y = a.y + a.size == b.y or b.y + b.size == a.y
    overlap_y = min(a.y + a.size, b.y + b.size) > max(a.y, b.y)
    overlap_x = min(a.x + a.size, b.x + b.size) > max(a.x, b.x)
    return (touch_x and overlap_y) or (touch_y and overlap_x)


def _emit(parcel, pts, road, border):
    length = sum(metres(pts[k], pts[k + 1]) for k in range(len(pts) - 1))
    parcel.pieces.append(Piece(pts, road, max(1, round(length)), border))


def segment_defaults(road):
    return DEFAULTS.get((road.cls, road.fow), CLASS_DEFAULTS[road.cls])


class Strings:
    """The text area: names once each, after a zero name table (as pbp leaves it)."""

    def __init__(self):
        self.order = []

    def add(self, text):
        if text and text not in self.order:
            self.order.append(text)

    def layout(self, start):
        self.offset = {}
        pos = start + 4 * len(self.order)
        for t in self.order:
            self.offset[t] = pos
            pos += len(t.encode("latin1")) + 1
        return bytes(4 * len(self.order)) + b"".join(t.encode("latin1") + b"\0" for t in self.order)

    def __getitem__(self, text):
        return self.offset[text] if text else 0


def sorted_pieces(parcel):
    """Segment order in the parcel (by class, as the class index needs), shared with the house
    number unit."""
    return sorted(parcel.pieces, key=lambda p: (p.road.cls, p.road.name or "", p.points[0]))


def node_type(degree):
    return 1 if degree == 1 else 5 if degree == 2 else 0


def build_level0(parcel, ctx):
    """RawParcel of a level 0 parcel. ctx: country (name, number), city_of(road) -> (city,
    municipality), district_of(road) -> text or None, code(point) -> node byte bits 6-7 (3 - top
    level), ptr(parcel) -> unit pointer, hn_ptr(parcel) -> house number unit pointer or 0."""
    from . import parcelfmt
    box = parcel.box
    pieces = sorted_pieces(parcel)
    # nodes and their incident piece ends
    ends = {}
    for i, pc in enumerate(pieces):
        ends.setdefault(pc.points[0], []).append((i, 0))
        ends.setdefault(pc.points[-1], []).append((i, 2))
    border = set(parcel.borders)
    best = {pt: min(pieces[i].road.cls for i, _ in inc) for pt, inc in ends.items()}
    inner = sorted((pt for pt in ends if pt not in border), key=lambda pt: (best[pt], pt))
    edge_pts = sorted((pt for pt in ends if pt in border), key=lambda pt: (best[pt], pt))

    # places
    strings = Strings()
    country, number = ctx.country
    cities = {}
    streets = {}
    for pc in pieces:
        city, muni = ctx.city_of(pc.road)
        cities[(city, muni)] = None
        streets[(pc.road.name, ctx.district_of(pc.road), city, muni)] = None
    city_list = sorted(cities, key=lambda c: (c[0] or "", c[1] or ""))
    street_list = sorted(streets, key=lambda s: (s[0] or "", s[1] or "", s[2] or ""))
    for t in [country] + [c for cm in city_list for c in cm] + [x for st in street_list for x in st[:2]]:
        strings.add(t)

    # sizes and offsets (memory order 0-7, 9, 8, 10-12, text)
    def a4(n):
        return (n + 3) & ~3
    n0, n1, n2 = 3, len(city_list) + 2, len(street_list) + 2
    o0 = parcelfmt.HEADER
    o1 = a4(o0 + 10 * n0)
    o2 = a4(o1 + 10 * n1)
    o3 = a4(o2 + 10 * n2)
    o4 = a4(o3 + 4 * 8)
    o5 = a4(o4 + SEG * (len(pieces) + 1))
    o6 = a4(o5 + 8 * len(inner))
    o7 = a4(o6 + 16 * len(edge_pts))
    n_shape = sum(len(pc.points) - 2 for pc in pieces)
    o9 = a4(o7 + 6 * n_shape)
    neighbours = sorted({id(n): n for n in parcel.borders.values()}.values(), key=lambda n: (n.box.x, n.box.y))
    o8 = a4(o9 + 8 * len(neighbours))
    turns = parcel.turns or {}
    n10 = sum(len(v) for v in turns.values())
    o10 = o8
    o11 = o12 = otext = o10 + 8 * n10
    text = strings.layout(otext)

    node_off = {pt: o5 + 8 * k for k, pt in enumerate(inner)}
    node_off.update({pt: o6 + 16 * k for k, pt in enumerate(edge_pts)})
    parcel.offsets = node_off
    seg_off = [o4 + SEG * i for i in range(len(pieces))]
    parcel.seg_base = o4
    city_rec = {c: o1 + 10 * (k + 1) for k, c in enumerate(city_list)}
    street_rec = {st: o2 + 10 * (k + 1) for k, st in enumerate(street_list)}

    def place(off, name, second, parent):
        return struct.pack(">HHHHH", strings[name], second, parent, 0, 0)

    r0 = bytes(10) + struct.pack(">HHHHH", strings[country], number, 0, 0, 0) + bytes(10)
    r1 = place(0, None, 0, o0) + b"".join(
        place(0, c, strings[m], o0 + 10) for c, m in city_list) + place(0, None, 0, o0 + 20)
    r2 = place(0, None, 0, o1) + b"".join(
        place(0, s[0], strings[s[1]], city_rec[(s[2], s[3])]) for s in street_list) +         place(0, None, 0, o1 + 10 * (n1 - 1))

    # class index
    r3 = b""
    for k in range(7):
        si = next((i for i, pc in enumerate(pieces) if pc.road.cls >= k), len(pieces))
        ni = next((j for j, pt in enumerate(inner) if best[pt] >= k), len(inner))
        r3 += struct.pack(">HH", o4 + SEG * si, o5 + 8 * ni)
    r3 += struct.pack(">HH", o4 + SEG * len(pieces), o5 + 8 * len(inner))

    # segments with node rings and shape points
    ring = {}
    for pt, inc in ends.items():
        if pt in border and len(inc) == 1:
            ring[inc[0]] = 0
            continue
        for k, (i, end) in enumerate(inc):
            ring[(i, end)] = seg_off[inc[(k + 1) % len(inc)][0]]
    r4, r7, r10 = b"", b"", b""
    shape_pos = o7
    turn_pos = o10
    for i, pc in enumerate(pieces):
        rd = pc.road
        speed, b6, b7, b17, w28 = segment_defaults(rd)
        b17 = (rd.access << 4) | rd.figure if (rd.figure or rd.access != 2) else b17
        pts = pc.points
        r4 += struct.pack(">HHHHHBBHBBBBHHHHHHH",
                          node_off[pts[0]], node_off[pts[-1]], shape_pos,
                          ring[(i, 0)], ring[(i, 2)],
                          (rd.paved << 7) | speed, (b6 << 6) | (rd.oneway << 4) | rd.fow,
                          min(pc.length, 0xFFFF), heading(pts[0], pts[1]), heading(pts[-1], pts[-2]),
                          (b7 << 7) | (rd.kind << 4) | rd.cls, b17,
                          turn_pos, o12, 0, 0,
                          street_rec[(rd.name, ctx.district_of(rd)) + tuple(ctx.city_of(rd))], w28, o11)
        for q in pts[1:-1]:
            r7 += struct.pack(">HHBB", (q[0] - box.x) // POINT_STEP, (q[1] - box.y) // POINT_STEP, 0, 0)
            shape_pos += 6
        for j, bit in sorted(turns.get(i, ())):     # prohibited turns from this segment
            r10 += struct.pack(">IHH", ctx.ptr(parcel), seg_off[j], bit)
            turn_pos += 8
    r4 += struct.pack(">HHH", 0, 0, shape_pos) + bytes(12) + struct.pack(">HHHH", turn_pos, o12, 0, 0) + \
        bytes(4) + struct.pack(">H", o11)

    first_seg = {}
    for pt, inc in ends.items():
        first_seg[pt] = seg_off[inc[0][0]]
    r5 = b""
    for pt in inner:
        byte = (ctx.code(pt) << 6) | 0x10 | node_type(len(ends[pt]))
        r5 += struct.pack(">HHHBB", (pt[0] - box.x) // POINT_STEP, (pt[1] - box.y) // POINT_STEP,
                          first_seg[pt], byte, 0)
    r6 = b""
    for pt in edge_pts:
        nb = parcel.borders[pt]
        byte = (ctx.code(pt) << 6) | 0x20 | 5
        r6 += struct.pack(">HHHBBIHH", (pt[0] - box.x) // POINT_STEP, (pt[1] - box.y) // POINT_STEP,
                          first_seg[pt], byte, 0, ctx.ptr(nb), nb.offsets.get(pt, 0), 0)
    r9 = b""
    for nb in neighbours:
        mx, my = _shared_mid(box, nb.box)
        r9 += struct.pack(">IHH", ctx.ptr(nb), (mx - box.x) // POINT_STEP, (my - box.y) // POINT_STEP)

    def pad(b):
        return b + bytes(a4(len(b)) - len(b))

    hn = ctx.hn_ptr(parcel)
    header = bytearray(parcelfmt.HEADER)
    struct.pack_into(">IHBB", header, 0, ctx.ptr(parcel), 0, 0, 0)
    struct.pack_into(">4i", header, 0x44, box.x, box.y, box.x + box.size, box.y + box.size)
    struct.pack_into(">IIIIIIII", header, 0x54, hn, ctx.ptr(parcel.parent) if parcel.parent else 0, 0,
                     *parcel.times, 10, (1 if hn else 0) << 24 | 1 << 16)
    regions = {0: pad(r0), 1: pad(r1), 2: pad(r2), 3: r3, 4: r4, 5: r5, 6: r6, 7: pad(r7), 9: r9,
               8: b"", 10: r10, 11: b"", 12: b"", 13: None}
    counts = {0: n0, 1: n1, 2: n2, 3: 7, 4: len(pieces), 5: len(inner), 6: len(edge_pts),
              7: n_shape, 8: 0, 9: len(neighbours), 10: n10, 11: 0, 12: 0, 13: 0,
              14: len(strings.order)}
    return parcelfmt.RawParcel(header, counts, regions, text)


def _shared_mid(a, b):
    """Middle of the border two boxes share (GPS units)."""
    x0, x1 = max(a.x, b.x), min(a.x + a.size, b.x + b.size)
    y0, y1 = max(a.y, b.y), min(a.y + a.size, b.y + b.size)
    return ((x0 + x1) // 2 // POINT_STEP) * POINT_STEP, ((y0 + y1) // 2 // POINT_STEP) * POINT_STEP
