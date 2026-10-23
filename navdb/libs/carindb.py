"""Basics of the CARiN map database (carindb) file, see ../docs/format.md sections 1-2 and
../../docs/newer_disc_format.md: coordinates, blocks and units, the block 0 header (record sizes,
db release, block size) and the table directory.

The newer nav discs (Opel Astra H / BMW e46 generation) split the database at 2 GiB into `DB_0` +
`DB_1` and use 512-byte blocks (read from the header, offset 0x2c); the reference `NAV_DB` disc
holds everything in one file (`carindb`) with 2048-byte blocks. Functions taking a file object work
with both: a `BlockFile` (newer discs) or a plain file (everything else).
"""
import struct
from pathlib import Path

BLOCK = 2048          # block size of the reference discs (newer ones read 0x0200 = 512 from header 0x2c)
SPLIT_BYTES = 2**31   # DB_0 + DB_1 split: DB_1 continues after this many logical bytes (2 GiB)
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


def x_units(deg_long):
    """Degrees longitude -> GPS units (inverse of lon())."""
    return round((deg_long + 30) / GPS_UNIT)


def y_units(deg_lat):
    """Degrees latitude -> GPS units (inverse of lat())."""
    return round(deg_lat / GPS_UNIT)


class BlockFile:
    """DB_0 (+ its DB_1 sibling) as one stream of logical blocks of a fixed size (newer disc layout,
    docs/newer_disc_format.md §2). Logical block numbering continues across DB_1, which resumes at
    byte 2**31; a DB_0 file trimmed short of the full 2 GiB leaves a gap of zero blocks. On the
    reference discs there is no DB_1 and the file ends with the database: reads past its end
    simply return zero blocks (like the old decoders did past EOF)."""

    def __init__(self, f0, block):
        self.block = block
        self.name = f0.name
        self.f0 = f0
        self.size = f0.seek(0, 2)            # DB_0 file size in bytes
        self.blocks0 = self.size // block    # logical blocks held by DB_0
        self.first1 = SPLIT_BYTES // block   # logical block number where DB_1 begins
        sibling = Path(self.name).with_name("DB_1")
        self.f1 = open(sibling, "rb") if sibling.is_file() else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def read_block(self, blk):
        """One logical block, zero-filled over the gap and past the end."""
        if blk < self.blocks0:
            self.f0.seek(blk * self.block)
            return _pad(self.f0.read(self.block), self.block)
        if self.f1 is not None and blk >= self.first1:
            self.f1.seek((blk - self.first1) * self.block)
            return _pad(self.f1.read(self.block), self.block)
        return bytes(self.block)             # the DB_0 gap, or past the end of the database

    def read_blocks(self, blk, count):
        """`count` logical blocks from `blk`, crossing the DB_0 / gap / DB_1 transitions; one file
        read per source run instead of one per block."""
        out, end = [], blk + count
        while blk < end:
            if blk < self.blocks0:
                run = min(end, self.blocks0) - blk
                self.f0.seek(blk * self.block)
                out.append(_pad(self.f0.read(run * self.block), run * self.block))
            elif blk < self.first1 or self.f1 is None:
                run = min(end, self.first1 if self.f1 is not None else end) - blk
                out.append(bytes(run * self.block))
            else:
                run = end - blk
                self.f1.seek((blk - self.first1) * self.block)
                out.append(_pad(self.f1.read(run * self.block), run * self.block))
            blk += run
        return b"".join(out)

    def close(self):
        self.f0.close()
        if self.f1:
            self.f1.close()


def _pad(d, n):
    """Zero-fill a short read (the last block may end inside a trimmed-short DB_0 file)."""
    return d.ljust(n, b"\0") if len(d) < n else d


def open_database(path):
    """Open the database at `path` (DB_0 of a newer disc, or a single-file reference database) with
    the block size from the header at 0x2c (default 2048 when 0; block 0 is at byte 0 regardless of
    the block size, so it can be read with a temporary 2048-byte view)."""
    with open(path, "rb") as f:
        h = f.read(BLOCK)
    block = struct.unpack_from(">H", h, 0x2c)[0] or BLOCK
    if block not in (512, 1024, 2048):
        raise ValueError(f"{path}: unexpected block size {block} in the header at 0x2c")
    return BlockFile(open(path, "rb"), block)


def block_size(f):
    """The logical block size of a database file: BlockFile `.block`, or 2048 for a plain file."""
    return f.block if isinstance(f, BlockFile) else BLOCK


def head_bytes(f, n=BLOCK):
    """The first n bytes of the database (block 0). Bytes beyond the block size come from more
    blocks: the header structures (record size table at 0xa6, table directory at 0x220) span
    several 512-byte blocks on the newer discs."""
    return read_blocks(f, 0, -(-n // block_size(f)))[:n]


def read_blocks(f, blk, count):
    """`count` logical blocks at `blk`: through a BlockFile (newer disc) or by plain seek+read."""
    if isinstance(f, BlockFile):
        return f.read_blocks(blk, count)
    f.seek(blk * BLOCK)
    return f.read(count * BLOCK)


def header_info(f):
    """Record sizes (block 0 table at 0x28/0x2a) and the db release (0x1a)."""
    d = head_bytes(f)
    rt_off, rt_n = struct.unpack_from(">HH", d, 0x28)
    sizes = {}
    for i in range(rt_n):
        t, size = struct.unpack_from(">HH", d, rt_off + 4 * i)
        sizes[t] = size
    return sizes, struct.unpack_from(">H", d, 0x1a)[0]


def table_directory(f):
    """{table id: (a, b, c)} from block 0, pointers as (block, unit length): a = index part start
    (0 = none), b = data start, c = last unit (inclusive)."""
    d = head_bytes(f)
    rt_off, rt_n = struct.unpack_from(">HH", d, 0x28)
    o = (rt_off + 4 * rt_n + 15) & ~15
    tables = {}
    while o + 16 <= len(d):
        a, b, c, tid = struct.unpack_from(">IIIH", d, o)
        if not (a or b or c or tid):
            break
        tables[tid] = tuple((v >> 8, v & 0xFF) for v in (a, b, c))
        o += 16
    return tables


def units(f, first, last):
    """(block, length, first 2 KB) of the units from block first up to and including the unit at
    block last (the directory's third pointer is the table's last unit); a unit starts with its own
    pointer (block << 8 | length in blocks, up to 255 on the newer discs, see §3 there). Zero
    blocks (the trimmed-short DB_0 / DB_1 gap, §2) are skipped."""
    b = first
    head_n = BLOCK // block_size(f)      # as many blocks as cover the 2 KB head of the old code
    while b <= last:
        ptr, = struct.unpack_from(">I", read_blocks(f, b, 1), 0)
        if not ptr:                      # the gap between DB_0 and DB_1
            b += 1
            continue
        length = ptr & 0xFF
        if ptr >> 8 != b or not 1 <= length <= 255:
            raise ValueError(f"block {b:#x}: no unit header ({ptr:08x})")
        yield b, length, read_blocks(f, b, head_n)
        b += length


def read_unit(f, ptr):
    """The whole unit at a unit pointer (block << 8 | blocks)."""
    return read_blocks(f, ptr >> 8, ptr & 0xFF)


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
