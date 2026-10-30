#!/usr/bin/env python3
"""Checks the structural rules of a carindb (the ones found on the original, docs/format.md) on any
database, the original or one the encoder wrote. Every rule prints passed / failed counts.

usage: check_db.py [carindb] [--every N]   (default: temp/navdb/poland/carindb, every parcel)
"""
import argparse
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from libs import bgfmt, parcelfmt, spindex
from libs.carindb import TEXT_TABLES, header_info, read_unit, table_directory, units
from libs.unpack import Unpacker

ROOT = Path(__file__).resolve().parents[2]
LEVELS = ((1, 0), (0x1E, 1), (3, 2), (2, 3))


def w(d, o):
    return struct.unpack_from(">H", d, o)[0]


read_unit_raw = None


def check_parcel(d, ptr, level, sizes, get, res):
    rs = sizes[0x08] if level == 0 else sizes[0x09]
    sl = {k: (w(d, 8 + 4 * k), w(d, 10 + 4 * k)) for k in range(15)}
    s4, c4 = sl[4]
    s5, c5 = sl[5]
    s6, c6 = sl[6]
    s9, c9 = sl[9]
    res["unit pointer"][struct.unpack_from(">I", d, 0)[0] == ptr] += 1
    res["layout round trip"][parcelfmt.write(parcelfmt.read(d), len(d) // 2048) == bytes(d)] += 1
    segs = [s4 + rs * i for i in range(c4)]
    cls = [d[r + 16] & 15 for r in segs]
    res["segments sorted by class"][cls == sorted(cls)] += 1
    # class index (slot 3)
    s3, c3 = sl[3]
    node_best = {}
    for r, c in zip(segs, cls):
        for e in (0, 2):
            node_best[w(d, r + e)] = min(node_best.get(w(d, r + e), 9), c)
    inner = [s5 + 8 * j for j in range(c5)]
    want = []
    for k in range(c3):
        si = next((i for i, c in enumerate(cls) if c >= k), c4)
        ni = next((j for j, o in enumerate(inner) if node_best.get(o, 9) >= k), c5)
        want.append((s4 + rs * si, s5 + 8 * ni))
    want.append((s4 + rs * c4, s5 + 8 * c5))
    got = [(w(d, s3 + 4 * k), w(d, s3 + 4 * k + 2)) for k in range(c3 + 1)]
    res["class index (slot 3)"][got == want] += 1
    # end points lie in slot 5 / 6, node rings close with length = degree
    pts = {o: [] for o in inner}
    pts.update({s6 + 16 * j: [] for j in range(c6)})
    ok_ends = True
    for r in segs:
        for e in (0, 2):
            o = w(d, r + e)
            if o not in pts:
                ok_ends = False
            else:
                pts[o].append((r, e))
    res["segment ends are nodes"][ok_ends] += 1
    for o, inc in pts.items():
        if not inc:
            res["node used by a segment"][False] += 1
            continue
        edge = o >= s6 and o < s6 + 16 * c6
        start = inc[0]
        cur, n, ok = start, 0, True
        while n <= len(inc) + 1:
            nxt = w(d, cur[0] + 6 + cur[1])
            if nxt == 0:
                ok = edge and len(inc) == 1
                break
            e2 = 0 if w(d, nxt) == o else 2
            if w(d, nxt + e2) != o:
                ok = False
                break
            cur, n = (nxt, e2), n + 1
            if cur == start:
                ok = n == len(inc)
                break
        res["node ring = degree"][ok] += 1
        if not edge:
            t = d[o + 6] & 7
            res["node type by degree"][t == (1 if len(inc) == 1 else 5 if len(inc) == 2 else 0) or t in (2, 4)] += 1
    # edge points are reciprocal
    nbs = set()
    x0, y0 = struct.unpack_from(">ii", d, 0x44)
    for j in range(c6):
        o = s6 + 16 * j
        nb, no = struct.unpack_from(">IH", d, o + 8)
        nbs.add(nb)
        e = get(nb)
        if e is None:
            res["edge point reciprocal"][False] += 1
            continue
        ex0, ey0 = struct.unpack_from(">ii", e, 0x44)
        same = (x0 + w(d, o) * 64, y0 + w(d, o + 2) * 64) == (ex0 + w(e, no) * 64, ey0 + w(e, no + 2) * 64)
        back = struct.unpack_from(">IH", e, no + 8) == (ptr, o)
        res["edge point reciprocal"][same and back] += 1
    res["slot 9 = edge point neighbours"][{struct.unpack_from(">I", d, s9 + 8 * j)[0] for j in range(c9)} == nbs] += 1
    # levels: parent contains the parcel; nodes go up exactly when c + level < 3
    parent = struct.unpack_from(">I", d, 0x58)[0]
    if parent and level < 3:
        pd = get(parent)
        px0, py0, px1, py1 = struct.unpack_from(">4i", pd, 0x44)
        bx0, by0, bx1, by1 = struct.unpack_from(">4i", d, 0x44)
        res["parent contains parcel"][px0 <= bx0 and bx1 <= px1 and py0 <= by0 and by1 <= py1] += 1
        up = {}                         # parent point -> offset of its node record
        for k, size in ((5, 8), (6, 16)):
            so, sc = w(pd, 8 + 4 * k), w(pd, 10 + 4 * k)
            up.update({(px0 + w(pd, so + size * j) * 64, py0 + w(pd, so + size * j + 2) * 64): so + size * j
                       for j in range(sc)})
        p4, pc4 = w(pd, 8 + 16), w(pd, 10 + 16)
        parent_heads = {}               # parent node offset -> headings of its segments there
        for i in range(pc4):
            r = p4 + sizes[0x09] * i
            parent_heads.setdefault(w(pd, r), set()).add(pd[r + 14])
            parent_heads.setdefault(w(pd, r + 2), set()).add(pd[r + 15])
        top_class = {0: 2, 1: 1, 2: 0}[level]
        for j in range(c5):
            o = s5 + 8 * j
            c = d[o + 6] >> 6
            pt = (x0 + w(d, o) * 64, y0 + w(d, o + 2) * 64)
            res["node goes up iff c + level < 3"][(pt in up) == (c + level < 3)] += 1
            if pt not in up:
                continue
            # the router finds the parent's segment by the heading at the node (rpmod FUN_000160d8)
            heads = parent_heads.get(up[pt], set())
            for r in segs:
                if d[r + 16] & 15 <= top_class:
                    for end, h in ((0, 14), (2, 15)):
                        if w(d, r + end) == o:
                            res["heading at an up node exists in the parent"][d[r + h] in heads] += 1
    if level > 0:
        cell = struct.unpack_from(">I", d, 0x5c)[0]
        s8, c8 = w(d, 8 + 32), w(d, 10 + 32)
        n = (struct.unpack_from(">i", d, 0x4c)[0] - x0) // cell if cell else 0
        res["child grid size <= n x n"][0 < c8 <= n * n] += 1
        for k in range(c8):
            i, j = divmod(k, n)
            if True:
                child = struct.unpack_from(">I", d, s8 + 4 * k)[0]
                if not child:
                    continue
                cd = get(child)
                if cd is None:
                    res["child grid -> child at cell centre"][False] += 1
                    continue
                cx, cy = x0 + i * cell + cell // 2, y0 + j * cell + cell // 2
                c0x, c0y, c1x, c1y = struct.unpack_from(">4i", cd, 0x44)
                res["child grid -> child at cell centre"][c0x <= cx < c1x and c0y <= cy < c1y] += 1
        # going down: every node and edge point is in the child at its grid cell, with the
        # headings of the segments there (the router goes down by point and heading)
        crs = sizes[0x08] if level == 1 else sizes[0x09]
        top_class = {1: 2, 2: 1, 3: 0}[level]
        heads = {}
        for r in segs:
            for end, h in ((0, 14), (2, 15)):
                heads.setdefault(w(d, r + end), set()).add(d[r + h])
        for o, hs in heads.items():
            pt = (x0 + w(d, o) * 64, y0 + w(d, o + 2) * 64)
            i, j = (min(max((pt[k] - (x0, y0)[k]) // cell, 0), n - 1) for k in (0, 1))
            cd = get(struct.unpack_from(">I", d, s8 + 4 * (i * n + j))[0]) if n else None
            here = set()
            if cd:
                cx0, cy0 = struct.unpack_from(">ii", cd, 0x44)
                c4, cc4 = w(cd, 8 + 16), w(cd, 10 + 16)
                for q in range(cc4):
                    r = c4 + crs * q
                    if cd[r + 16] & 15 <= top_class:
                        for end, h in ((0, 14), (2, 15)):
                            e = w(cd, r + end)
                            if (cx0 + w(cd, e) * 64, cy0 + w(cd, e + 2) * 64) == pt:
                                here.add(cd[r + h])
            key = "edge point" if s6 <= o < s6 + 16 * c6 else "node"
            res[f"{key} and its headings exist in the child"][hs <= here] += 1
    if level == 0 and d[0x70]:
        hn = read_unit_raw(struct.unpack_from(">I", d, 0x54)[0])
        res["house number unit -> its parcel"][struct.unpack_from(">I", hn, 12)[0] == ptr and w(hn, 10) == c4] += 1
    # prohibited turns (slot 10): the target segment leaves the source's via node
    if level == 0 and sl[10][1]:
        s10, c10 = sl[10]
        ok = True
        for i, r in enumerate(segs):
            end = w(d, s4 + rs * (i + 1) + 18)
            for e in range(w(d, r + 18), end, 8):
                pp, tgt, bit = struct.unpack_from(">IHH", d, e)
                via = w(d, r + (2 if bit & 1 else 0))
                ok &= pp == ptr and tgt in segs and via in (w(d, tgt), w(d, tgt + 2))
        ok &= w(d, s4 + rs * c4 + 18) == s10 + 8 * c10
        res["prohibited turn -> segment at the via node"][ok] += 1
    # shape points: ranges increase
    if level == 0:
        starts = [w(d, r + 4) for r in segs] + [w(d, s4 + rs * c4 + 4)]
        res["shape ranges increase"][all(a <= b for a, b in zip(starts, starts[1:]))] += 1


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("carindb", nargs="?", type=Path, default=ROOT / "temp/navdb/poland/carindb")
    p.add_argument("--every", type=int, default=1, help="check every Nth parcel")
    args = p.parse_args()
    f = open(args.carindb, "rb")
    tables = table_directory(f)
    sizes, release = header_info(f)
    unpacker = Unpacker(sizes, release, TEXT_TABLES)
    cache = {}

    def get(ptr):
        if ptr not in cache:
            if len(cache) > 500:
                cache.clear()
            try:
                cache[ptr] = bytes(unpacker.unpack(read_unit(f, ptr)))
            except Exception:
                cache[ptr] = None
        return cache[ptr]

    global read_unit_raw
    read_unit_raw = lambda p: read_unit(f, p)
    res = {k: Counter() for k in ("parent contains parcel", "node goes up iff c + level < 3",
                                  "child grid -> child at cell centre", "child grid size <= n x n",
                                  "house number unit -> its parcel",
                                  "unit pointer", "layout round trip", "segments sorted by class",
                                  "class index (slot 3)", "segment ends are nodes", "node used by a segment",
                                  "node ring = degree", "node type by degree", "edge point reciprocal",
                                  "slot 9 = edge point neighbours", "shape ranges increase",
                                  "heading at an up node exists in the parent",
                                  "node and its headings exist in the child",
                                  "edge point and its headings exist in the child",
                                  "prohibited turn -> segment at the via node",
                                  "spatial index -> covering unit", "index unit within 5 blocks",
                                  "background layout round trip",
                                  "background groups and end records")}
    for tid, level in LEVELS:
        (a, _), (b, _), (c, _) = tables.get(tid, ((0, 0), (0, 0), (0, 0)))
        if not b:
            print(f"level {level}: table {tid:x} empty")
            continue
        for k, (blk, length, head) in enumerate(units(f, b, c)):
            if k % args.every:
                continue
            ptr = (blk << 8) | length
            check_parcel(get(ptr), ptr, level, sizes, get, res)
        if a:
            for x, y, size, ptr in spindex.cells(f, a, b):
                d = get(ptr)
                x0, y0, x1, y1 = struct.unpack_from(">4i", d, 0x44)
                cx, cy = x + size // 2, y + size // 2
                res["spatial index -> covering unit"][x0 <= cx < x1 and y0 <= cy < y1] += 1
    # background: layout, groups and end records, spatial index
    for tid in (6, 0x16, 0x15, 0x1C, 0x14, 0x1D):
        (a, _), (b, _), (c, _) = tables.get(tid, ((0, 0), (0, 0), (0, 0)))
        if not b:
            print(f"background table {tid:x} empty")
            continue
        for blk, length, head in units(f, b, c):
            d = get((blk << 8) | length)
            res["background layout round trip"][bgfmt.write(bgfmt.read(d), len(d) // 2048) == d] += 1
            g, gc = w(d, 8), w(d, 10)
            o1, c1, o2, c2 = w(d, 12), w(d, 14), w(d, 16), w(d, 18)
            end = (o2 + 16 * c2) if o2 else (o1 + 20 * c1)
            groups = [(d[g + 4 * i], d[g + 4 * i + 1], w(d, g + 4 * i + 2)) for i in range(gc + 1)]
            ok = groups[-1][2] == end and all(groups[i][2] <= groups[i + 1][2] for i in range(gc))
            res["background groups and end records"][ok] += 1
        if a:
            for x, y, size, ptr in spindex.cells(f, a, b):
                d = get(ptr)
                x0, y0, x1, y1 = struct.unpack_from(">4i", d, 0x20)
                res["spatial index -> covering unit"][x0 <= x + size // 2 < x1 and y0 <= y + size // 2 < y1] += 1
    # index units (kind 9) at most 5 blocks, as the original's largest: with up to 9 the device
    # read the level 0 background index and then no unit
    for ptr in spindex.directory(f):
        b = ptr >> 8
        while True:
            u = read_unit(f, (b << 8) | 8)
            if struct.unpack_from(">H", u, 4)[0] != 8:
                break
            off, cnt = struct.unpack_from(">HH", u, 8)
            for leaf in struct.unpack_from(f">{cnt}I", u, off):
                if leaf:
                    res["index unit within 5 blocks"][leaf & 0xFF <= 5] += 1
            b += u[3]
    failed = 0
    for name, c in res.items():
        if c:
            status = "ok" if not c[False] else "FAILED"
            failed += bool(c[False])
            print(f"{status:6} {name}: {c[True]} passed, {c[False]} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
