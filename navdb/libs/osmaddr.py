"""House numbers for the encoder: OSM addresses (points and buildings with addr:housenumber and
addr:street) are put on the nearest segment piece of the same street; per piece and side the
number nearest the start node is "from", the one nearest the end node "to" (docs/format.md,
house number units: left / right for travelling start -> end).
"""
import math
import re
import sqlite3
import struct

from .osmnet import fold, gps, hstore
from .osmplaces import _polygons, street_name

MAX_DIST = 120 / 1.8e-7 / 111320     # metres -> GPS units (latitude scale)
CELL = 1 << 13


def load(gpkg, bbox, country=None):
    """[(point, street name as the encoder writes it, number)]"""
    from .osmsrc import rows
    out = []
    for layer in ("points", "multipolygons"):
        key = "'p' || l.osm_id" if layer == "points" else "coalesce('r' || l.osm_id, 'w' || l.osm_way_id)"
        for _, other, geom in rows(gpkg,
                f"SELECT {key}, l.other_tags, l.geom FROM {layer} l JOIN rtree_{layer}_geom r ON l.fid = r.id "
                "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? "
                "AND l.other_tags LIKE '%addr:housenumber%'", (bbox[0], bbox[2], bbox[1], bbox[3])):
            tags = hstore(other)
            m = re.match(r"\d+", tags.get("addr:housenumber", ""))
            street = street_name(fold(tags.get("addr:street")), country)
            if not m or not street or int(m.group()) >= 32767:
                continue
            if layer == "points":
                env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(geom[3] >> 1) & 7]
                pt = gps(*struct.unpack_from("<dd", geom, 8 + env + 5))
            else:
                rings = _polygons(geom)
                if not rings:
                    continue
                ring = rings[0]
                pt = (sum(p[0] for p in ring) // len(ring), sum(p[1] for p in ring) // len(ring))
            out.append((pt, street, int(m.group())))
    return out


def _project(pt, a, b):
    """(distance, t along a-b 0..1, side: >0 left of a->b)"""
    cos = 0.62
    ax, ay, bx, by, px, py = a[0] * cos, a[1], b[0] * cos, b[1], pt[0] * cos, pt[1]
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    t = 0 if not ll else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / ll))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy), t, dx * (py - ay) - dy * (px - ax)


def assign(parcels, addresses):
    """Sets piece.hn = (left from, left to, right from, right to, scheme) on numbered pieces."""
    grid = {}
    for pc in parcels:
        for piece in pc.pieces:
            if not piece.road.name:
                continue
            pts = piece.points
            done = 0.0
            for i in range(len(pts) - 1):
                seg_len = math.hypot((pts[i + 1][0] - pts[i][0]) * 0.62, pts[i + 1][1] - pts[i][1])
                for cx in range(min(pts[i][0], pts[i + 1][0]) // CELL - 1, max(pts[i][0], pts[i + 1][0]) // CELL + 2):
                    for cy in range(min(pts[i][1], pts[i + 1][1]) // CELL - 1, max(pts[i][1], pts[i + 1][1]) // CELL + 2):
                        grid.setdefault((cx, cy), []).append((piece, i, done, seg_len))
                done += seg_len
    found = {}
    for pt, street, number in addresses:
        best = None
        for piece, i, done, seg_len in grid.get((pt[0] // CELL, pt[1] // CELL), ()):
            if piece.road.name != street:
                continue
            dist, t, side = _project(pt, piece.points[i], piece.points[i + 1])
            if dist < MAX_DIST and (best is None or dist < best[0]):
                best = (dist, piece, done + t * seg_len, side)
        if best:
            _, piece, pos, side = best
            found.setdefault(id(piece), (piece, [], []))[1 if side > 0 else 2].append((pos, number))
    n = 0
    for piece, left, right in found.values():
        def ends(side):
            if not side:
                return 32767, 32767
            side.sort()
            return side[0][1], side[-1][1]
        lf, lt = ends(left)
        rf, rt = ends(right)
        mixed = any(len({x % 2 for _, x in s}) > 1 for s in (left, right) if s)
        piece.hn = (lf, lt, rf, rt, 1 if mixed else 2)
        n += 1
    return n


def unit(parcel_ptr, own_ptr, pieces, blocks=None):
    """Kind 4 house number unit for a parcel's pieces (in the parcel's segment order)."""
    d = bytearray(16 + 10 * len(pieces))
    struct.pack_into(">IHHHHI", d, 0, own_ptr, 4, 0, 0x10, len(pieces), parcel_ptr)
    for i, piece in enumerate(pieces):
        hn = getattr(piece, "hn", None)
        lf, lt, rf, rt, scheme = hn if hn else (32767, 32767, 32767, 32767, 0)
        struct.pack_into(">5H", d, 16 + 10 * i, lf, rf, lt, rt, scheme)
    n = blocks or -(-len(d) // 2048)
    return bytes(d + bytes(n * 2048 - len(d)))
