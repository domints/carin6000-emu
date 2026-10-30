"""Spatial index parts of the map tables (units of kind 8 and 9 between a table's index start and its
data start) and the index directory in block 2, which gives every indexed table its grid extent and
zoom range.

Index directory (table 4, block 2): 28-byte records from 0x14: u32 index start pointer, i32 x0, y0,
x1, y1 (the grid extent, 2^29 units square, the same for all tables), u16 a (meaning open), u16 zoom
from, u16 zoom to, u16 0.

Kind 8 units: slot 0 (word 8 offset, word 10 count) holds u32 pointers to kind 9 units, 0 = empty,
u32 0x0c = top cell size;
all kind 8 units of a table together form an N x N grid over the extent, cell i = column i // N
(x, west to east), row i % N (y, south to north). Kind 9 units (u32 0x10 = subcell size): slot 0 holds n x n u16 offsets
(subcells in the same order), slot 1 the unit pointers; an offset is the byte position of a pointer
in this unit (0 = no data there). Every subcell points to the one data unit covering it.
"""
import math
import struct

from .carindb import BLOCK, read_unit


def directory(f):
    """{index start pointer: (x0, y0, x1, y1, a, zoom_from, zoom_to)} from block 2."""
    f.seek(2 * BLOCK)
    d = f.read(BLOCK)
    out = {}
    for o in range(0x14, BLOCK - 28, 28):
        ptr, x0, y0, x1, y1, a, z0, z1, pad = struct.unpack_from(">I4i4H", d, o)
        if x1 - x0 != 1 << 29:
            if ptr or x0 or y0 or x1 or y1:
                break
            continue                    # an all-zero record
        if ptr:                         # ptr 0: the table is empty (encoder output)
            out[ptr] = (x0, y0, x1, y1, a, z0, z1)
    return out


def cells(f, first, data):
    """Yield (x0, y0, size, unit pointer) for every subcell of the index between block first and the
    data start, using the extent from the block 2 directory."""
    f.seek(first * BLOCK)
    ptr0, = struct.unpack_from(">I", f.read(4), 0)
    ext = directory(f)[ptr0]
    top, b = [], first
    while b < data:
        u = read_unit(f, (b << 8) | 8)
        n = u[3]
        if struct.unpack_from(">H", u, 4)[0] != 8:
            break
        off, cnt = struct.unpack_from(">HH", u, 8)
        top += struct.unpack_from(f">{cnt}I", u, off)
        b += n
    grid = math.isqrt(len(top))
    leaf = (ext[2] - ext[0]) // grid
    for i, p in enumerate(top):
        if not p:
            continue
        u = read_unit(f, p)
        off, cnt = struct.unpack_from(">HH", u, 8)
        sub = math.isqrt(cnt)
        size = leaf // sub
        lx, ly = ext[0] + (i // grid) * leaf, ext[1] + (i % grid) * leaf
        for k, o in enumerate(struct.unpack_from(f">{cnt}H", u, off)):
            if o:
                yield lx + (k // sub) * size, ly + (k % sub) * size, size, struct.unpack_from(">I", u, o)[0]


# --- writing (encoder) ---

ORIGIN = (-34998272, -59092992)
EXTENT = 1 << 29
TOP_PER_UNIT = (8 * BLOCK - 16) // 4          # 4092 cell pointers in an 8-block kind 8 unit


class IndexPart:
    """The kind 8 / 9 units of one table for data units with boxes. `grid` is N (the original
    uses 512 for table 1, 256 for 7, 32 for 1e/3/6/16/15, 8 for 2, 1 for 1c/14/1d)."""

    def __init__(self, grid, items):
        """items: [(x0, y0, x1, y1, key)]; a subcell maps to the item whose box holds its centre."""
        self.grid = grid
        self.leaf = EXTENT // grid
        self.cells = {}
        for x0, y0, x1, y1, key in items:
            for cx in range((x0 - ORIGIN[0]) // self.leaf, (x1 - 1 - ORIGIN[0]) // self.leaf + 1):
                for cy in range((y0 - ORIGIN[1]) // self.leaf, (y1 - 1 - ORIGIN[1]) // self.leaf + 1):
                    self.cells.setdefault(cx * grid + cy, []).append((x0, y0, x1, y1, key))
        self.leaves = []
        for cell in sorted(self.cells):
            self.leaves.append((cell, self._subcells(cell, self.cells[cell])))
        n_top = grid * grid
        self.top_units = [min(TOP_PER_UNIT, n_top - i) for i in range(0, n_top, TOP_PER_UNIT)]

    def _subcells(self, cell, items):
        lx = ORIGIN[0] + (cell // self.grid) * self.leaf
        ly = ORIGIN[1] + (cell % self.grid) * self.leaf
        for n in (1, 2, 4, 8, 16, 32, 64):
            size = self.leaf // n
            keys, ok = [], True
            for k in range(n * n):
                sx, sy = lx + (k // n) * size, ly + (k % n) * size
                hits = [it for it in items if it[0] <= sx and sx + size <= it[2] and it[1] <= sy and sy + size <= it[3]]
                part = [it for it in items if it[0] < sx + size and sx < it[2] and it[1] < sy + size and sy < it[3]]
                if hits:
                    keys.append(hits[0][4])
                elif part:
                    ok = False
                    break
                else:
                    keys.append(None)
            if ok:
                return n, keys
        raise ValueError("data units smaller than 1/64 of an index cell")

    def unit_blocks(self):
        """Block counts of the units in file order (kind 8 units, then the kind 9 leaves)."""
        out = [-(-(16 + 4 * c) // BLOCK) for c in self.top_units]
        for _, (n, keys) in self.leaves:
            distinct = len({k for k in keys if k is not None})
            out.append(-(-(((0x14 + 2 * n * n + 3) & ~3) + 4 * distinct) // BLOCK))
        return out

    def units(self, first_block, ptr):
        """Unit bytes; first_block = where the part starts, ptr(key) = data unit pointer."""
        blocks = self.unit_blocks()
        starts = []
        b = first_block
        for n in blocks:
            starts.append(b)
            b += n
        n_top = len(self.top_units)
        leaf_ptr = {cell: (starts[n_top + i] << 8) | blocks[n_top + i] for i, (cell, _) in enumerate(self.leaves)}
        out = []
        for u, count in enumerate(self.top_units):
            d = bytearray(blocks[u] * BLOCK)
            struct.pack_into(">IHHHHI", d, 0, (starts[u] << 8) | blocks[u], 8, 0, 0x10, count, self.leaf)
            for i in range(count):
                cell = u * TOP_PER_UNIT + i
                if cell in leaf_ptr:
                    struct.pack_into(">I", d, 0x10 + 4 * i, leaf_ptr[cell])
            out.append(bytes(d))
        for i, (cell, (n, keys)) in enumerate(self.leaves):
            u = n_top + i
            d = bytearray(blocks[u] * BLOCK)
            distinct = []
            for k in keys:
                if k is not None and k not in distinct:
                    distinct.append(k)
            s1 = (0x14 + 2 * n * n + 3) & ~3
            struct.pack_into(">IHHHHHHI", d, 0, (starts[u] << 8) | blocks[u], 9, 0, 0x14, n * n, s1,
                             len(distinct), self.leaf // n)
            for k, key in enumerate(keys):
                if key is not None:
                    struct.pack_into(">H", d, 0x14 + 2 * k, s1 + 4 * distinct.index(key))
            for j, key in enumerate(distinct):
                struct.pack_into(">I", d, s1 + 4 * j, ptr(key))
            out.append(bytes(d))
        return out
