"""Basics of the CARiN map database (carindb) file, see ../docs/format.md sections 1-2: coordinates,
blocks and units, the block 0 header (record sizes, db release) and the table directory."""
import struct

BLOCK = 2048
GPS_UNIT = 1.8e-7     # degrees per unit; longitudes carry +30 degrees
POINT_STEP = 64       # GPS units per point coordinate step in parcels and POI units
HN_NONE = 32767       # "no house number"

# Byte tables of the text code (pbp data offsets 0x1342.., set up from its M$IData): 1, 2, 3 and
# 7 bit codes for the most frequent letters.
TEXT_TABLES = (b"ae", b"str\0", b" dghilno",
               bytes.fromhex("e0e1e2e3e4e5e7e8e9eaebecedeeeff1f2f3f4f5f6f8f9fafbfcfdac"))


def lon(v):
    return v * GPS_UNIT - 30


def lat(v):
    return v * GPS_UNIT


def header_info(f):
    """Record sizes (block 0 table at 0x28/0x2a) and the db release (0x1a)."""
    f.seek(0)
    d = f.read(BLOCK)
    rt_off, rt_n = struct.unpack_from(">HH", d, 0x28)
    sizes = {}
    for i in range(rt_n):
        t, size = struct.unpack_from(">HH", d, rt_off + 4 * i)
        sizes[t] = size
    return sizes, struct.unpack_from(">H", d, 0x1a)[0]


def table_directory(f):
    """{table id: (a, b, c)} from block 0, pointers as (block, unit length): a = index part start
    (0 = none), b = data start, c = last unit (inclusive)."""
    f.seek(0)
    d = f.read(BLOCK)
    rt_off, rt_n = struct.unpack_from(">HH", d, 0x28)
    o = (rt_off + 4 * rt_n + 15) & ~15
    tables = {}
    while o + 16 <= BLOCK:
        a, b, c, tid = struct.unpack_from(">IIIH", d, o)
        if not (a or b or c or tid):
            break
        tables[tid] = tuple((v >> 8, v & 0xFF) for v in (a, b, c))
        o += 16
    return tables


def units(f, first, last):
    """(block, length, first 2 KB) of the units from block first up to and including the unit at
    block last (the directory's third pointer is the table's last unit); a unit starts with its own
    pointer (block << 8 | length in blocks)."""
    b = first
    while b <= last:
        f.seek(b * BLOCK)
        head = f.read(BLOCK)
        ptr, = struct.unpack_from(">I", head, 0)
        if ptr >> 8 != b or not 1 <= ptr & 0xFF <= 8:
            raise ValueError(f"block {b:#x}: no unit header ({ptr:08x})")
        yield b, ptr & 0xFF, head
        b += ptr & 0xFF


def read_unit(f, ptr):
    """The whole unit at a unit pointer (block << 8 | blocks)."""
    f.seek((ptr >> 8) * BLOCK)
    return f.read((ptr & 0xFF) * BLOCK)


class UnitCache:
    """Units read by pointer, for cross-table references."""

    def __init__(self, f, size=256):
        self.f, self.size, self.cache = f, size, {}

    def get(self, ptr):
        if ptr not in self.cache:
            if len(self.cache) >= self.size:
                self.cache.pop(next(iter(self.cache)))
            self.cache[ptr] = read_unit(self.f, ptr)
        return self.cache[ptr]


def cstring(d, o):
    """The 0-terminated Latin-1 text at offset o (0 = none)."""
    if not o or o >= len(d):
        return None
    e = d.find(b"\0", o)
    return d[o:e].decode("latin1") if e > o else None
