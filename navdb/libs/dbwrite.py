"""Assembles a carindb file (encoder side of ../docs/format.md section 2).

Blocks 0-4 come from the original database as templates (header with the record size table,
info texts, index directory, country trie, countries) with their pointers and boxes replaced.
Every table is a list of units in the original order: spatial index part (kind 8 / 9) first,
then the data units. A unit is built twice: once to learn its size, once more with the final
unit pointers (sizes do not depend on pointer values). Both passes run in worker processes
(fork: the workers see the parent's data; a build must not leave results other builds need).
"""
import struct

from .carindb import BLOCK, table_directory
from .par import pmap

# table ids in file order after block 4 (the original layout); the house number units (kind 4,
# outside the directory) follow table 1
FILE_ORDER = (0x0E, 0x0D, 0x10, 0x0F, 0x12, 0x11, 0x07, 0x01, "hn", 0x1E, 0x03, 0x02, 0x06, 0x16,
              0x15, 0x1C, 0x14, 0x1D, 0x00, 0x18)


def build_all(units, resolve, size_only=False):
    """The units' bytes (or sizes), in order, built in worker processes when there are many."""
    if size_only:
        return pmap(lambda u: len(u.build(resolve)), units, 64)
    return pmap(lambda u: u.build(resolve), units, 64)


class Unit:
    """A data unit: key (any hashable), build(resolve) -> bytes, where resolve(key) gives the
    unit pointer of any unit."""

    def __init__(self, key, build):
        self.key, self.build = key, build
        self.blocks = None


def _zero(key):
    return 0


class Table:
    def __init__(self, tid, units=(), index=None):
        self.tid, self.units, self.index = tid, list(units), index


class Database:
    def __init__(self, template):
        with open(template, "rb") as f:
            self.template = [f.read(BLOCK) for _ in range(5)]
            self.template_dir = table_directory(f)
        self.tables = {}
        self.ptr = {}
        self.blocks = {}                # block number 1-4 -> build(resolve), replaces the template
        self.country_roots = None       # number of root nodes of the country trie (block 3)
        self.country_numbers = None     # block 2's per-country slot: {our number: template number
                                        # whose settings are copied} (None = the template's)

    def add(self, table):
        self.tables[table.tid] = table

    def resolve(self, key):
        return self.ptr.get(key, 0)

    def layout(self):
        """Blocks for every unit: sizes from a first build with zero pointers."""
        for t in self.tables.values():
            for u, size in zip(t.units, build_all(t.units, _zero, size_only=True)):
                u.blocks = size // BLOCK
                if not 1 <= u.blocks <= 8 or size % BLOCK:
                    raise ValueError(f"unit {u.key}: {size} bytes")
        block = 5
        self.where = {}
        for tid in FILE_ORDER:
            t = self.tables.get(tid)
            if t is None or not t.units:
                continue
            start = block
            if t.index is not None:
                block += sum(t.index.unit_blocks())
            data = block
            for u in t.units:
                self.ptr[u.key] = (block << 8) | u.blocks
                block += u.blocks
            last = t.units[-1]
            self.where[tid] = (start if t.index is not None else 0, data, self.ptr[last.key])
        self.total = block

    def header(self, bbox):
        """Block 0: the template with the boxes and the table directory replaced."""
        h = bytearray(self.template[0])
        for o in (0x34, 0x50):
            struct.pack_into(">4I", h, o, *bbox)
        if self.country_roots is not None:      # (block 3 pointer, offset, count) at 0x0c and 0x44
            for o in (0x0C, 0x44):
                struct.pack_into(">IHH", h, o, 3 << 8 | 1, 0x0C, self.country_roots)
        rt_off, rt_n = struct.unpack_from(">HH", h, 0x28)
        o = (rt_off + 4 * rt_n + 15) & ~15
        while o + 16 <= BLOCK:
            a, b, c, tid = struct.unpack_from(">IIIH", h, o)
            if not (a or b or c or tid):
                break
            if tid in self.where:
                start, data, last = self.where[tid]
                first = self.tables[tid].units[0]
                a = (start << 8) | (self.tables[tid].index.unit_blocks()[0] if start else 0)
                b, c = self.ptr[first.key], last
            elif tid in (0x04, 0x0B, 0x0C, 0x13, 0x17):     # single-unit tables in blocks 0-4
                pass
            else:
                a = b = c = 0
            struct.pack_into(">IIIH", h, o, a, b, c, tid)
            o += 16
        return bytes(h)

    def index_directory(self):
        """Block 2: the template records, each pointed at our index part of the same table."""
        d = bytearray(self.template[2])
        by_ptr = {(a << 8) | n: tid for tid, ((a, n), _, _) in self.template_dir.items() if a}
        for o in range(0x14, BLOCK - 28, 28):
            ptr, = struct.unpack_from(">I", d, o)
            if ptr in by_ptr:
                tid = by_ptr[ptr]
                new = 0
                if tid in self.where and self.where[tid][0]:
                    new = (self.where[tid][0] << 8) | self.tables[tid].index.unit_blocks()[0]
                struct.pack_into(">I", d, o, new)
        # slot 1 (22 bytes after the descriptors): starts with the pointer of TMC table 0
        w = lambda o: struct.unpack_from(">H", d, o)[0]
        s1, s2, n2 = w(12), w(16), w(18)
        old0 = self.template_dir[0][1]
        if struct.unpack_from(">I", d, s1)[0] == (old0[0] << 8 | old0[1]):
            t0 = self.tables.get(0)
            struct.pack_into(">I", d, s1, self.ptr[t0.units[0].key] if t0 and t0.units else 0)
        # slot 2: 22-byte settings per country, by country number
        if self.country_numbers is not None:
            old = {w(s2 + 22 * i): bytes(d[s2 + 22 * i:s2 + 22 * i + 22]) for i in range(n2)}
            keep = [struct.pack(">H", ours) + old[src][2:] for ours, src in sorted(self.country_numbers.items())]
            for i, rec in enumerate(keep):
                d[s2 + 22 * i:s2 + 22 * i + 22] = rec
            struct.pack_into(">H", d, 18, len(keep))
        return bytes(d)

    def write(self, path, bbox):
        self.layout()
        with open(path, "wb") as f:
            f.write(self.header(bbox))
            for n in (1, 2, 3, 4):
                if n in self.blocks:
                    f.write(self.blocks[n](self.resolve))
                else:
                    f.write(self.index_directory() if n == 2 else self.template[n])
            for tid in FILE_ORDER:
                t = self.tables.get(tid)
                if t is None or not t.units:
                    continue
                if t.index is not None:
                    for data in t.index.units(self.where[tid][0], self.resolve):
                        f.write(data)
                for u, data in zip(t.units, build_all(t.units, self.resolve)):
                    if len(data) != u.blocks * BLOCK:
                        raise ValueError(f"unit {u.key} changed size")
                    f.write(data)
        return self.total
