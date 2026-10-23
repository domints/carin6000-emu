# Changes to navdb decoder tools for the newer disc format

This document lists every change made to `navdb/tools/carindb2gpkg.py` and
`navdb/tools/parcel.py` to support the newer NAV_DB disc generation
(Opel Astra H / BMW e46 nav module, mounted at `/Volumes/NAV_DB_21709`).

The reference decoder was written against the `NAV_DB` disc
(ISO9660, MapScape/Continental, CD 21435, 2013-04-08, Eastern Europe,
db release 34, 2048-byte blocks). All changes are backward compatible:
on the reference disc behavior is unchanged.

---

## File: `navdb/tools/carindb2gpkg.py`

### 1. Block size read from header instead of hardcoded 2048

**Before:** `BLOCK = 2048` (module-level constant).

**After:** Block size is read from the carindb header at offset `0x2c`.
A new `open_database(path0)` function opens `DB_0`, reads block 0 with a
temporary 2048-byte view (block 0 is at byte offset 0 regardless of block
size), extracts `u16(header, 0x2c)`, then re-opens with the correct block
size. Defaults to 2048 if the header field is 0.

### 2. New `BlockFile` class: presents DB_0 + DB_1 as one logical block stream

The newer disc splits the database at 2 GiB: `DB_0` holds logical blocks
`0..n-1`, `DB_1` continues at logical block `2 GiB ÷ BLOCK` (= `0x400000`
for BLOCK=512). There is a 78-block zero gap in DB_0 (file is trimmed
short of a full 2 GiB) that must read as zeros.

`BlockFile` provides:
- `read_block(blk)` — returns one logical block, zero-filled for gaps/EOF
- `read_blocks(blk, count)` — reads a contiguous run, crossing the DB_0/DB_1
  boundary and gap correctly
- `close()` — closes both file handles

`DB_1` is auto-detected as the sibling file named `DB_1` in the same
directory as `DB_0`.

### 3. Unit length limit raised from 8 to 255

**Before:** `units()` rejected units where `ptr & 0xFF` was not in `1..8`.

**After:** Limit raised to `1..255`. The newer disc uses lengths up to 39
(e.g. table 1 parcels = 13 compressed blocks; table f = 31 blocks).

### 4. `header_info()` and `table_directory()` use BlockFile

Both functions now take `(bf, block_size)` instead of a plain file object.
They read `bf.read_blocks(0, ceil(2048 / block_size))` to cover the full
header structures (record size table at `0xa6`..`0x21d`, table directory at
`0x220`..), which span multiple 512-byte blocks.

### 5. `units()` yields from BlockFile and skips zero gap blocks

**Before:** `f.seek(b * BLOCK); f.read(BLOCK)` per unit; raised `SystemExit`
on any non-self-consistent block.

**After:** Uses `bf.read_block(b)`. Blocks with pointer `0` (the gap between
DB_0 and DB_1) are skipped. The self-consistency check (`ptr >> 8 == b`)
is preserved for non-zero blocks.

### 6. All `f.seek(b * BLOCK); f.read(length * BLOCK)` replaced with `bf.read_blocks(b, length)`

Occurrences in:
- `street_index()` (table f)
- `parcel_level()` (table 1 parcels)
- `background()` (tables 6, 16, 1c)
- `poi()` (table 7)
- `UnitCache.get()` (cross-table unit references)

### 7. `UnitCache` takes `(bf, block_size)` instead of a file object

**Before:** `UnitCache(f)` with `f.seek((ptr >> 8) * BLOCK)`.

**After:** `UnitCache(bf, block_size)` with `bf.read_blocks(ptr >> 8, ptr & 0xFF)`.

### 8. Parcel box read from unpacked unit data, not raw head block

**Before:** Box coordinates read from `head` (the first block read from disk).

**After:** Box coordinates read from `d` (the unpacked unit). For plain/uncompressed
units `head == d`, so behavior is identical on the reference disc. For
zlib-compressed units the box is only valid after decompression, so this is
required.

### 9. Defensive bounds clamps

Added guards so edge-case units don't abort the whole run:
- `street_index()`: wrapped in try/except; returns `{}` on failure (table f
  is zlib-compressed on this disc and not yet decoded).
- `parcel_level()`: `seg_n` clamped to `(len(d) - seg_off) // rs`; unpack call
  wrapped in try/except.
- `background()`: unpack wrapped in try/except; bounds checks on group table
  offsets, record loops, and shape point ranges.
- `poi()`: record count clamped to `(len(u) - off) // 28`; record loop checks
  `r + 28 > len(u)`.

### 10. CLI argument handling updated

`main()` now calls `open_database(src)` instead of `open(src, "rb")`. The
`step_lon`/`step_lat`/`direct_delta` experiment code and CLI flags
(`--step-lon`, `--step-lat`, `--direct-delta`) were removed; decoding always
uses legacy mode (`POINT_STEP = 64`, buffer offsets).

---

## File: `navdb/tools/parcel.py`

### 1. `Unpacker.__init__` takes `block` parameter

**Before:** `Unpacker(recsize, release, text_tables)`.

**After:** `Unpacker(recsize, release, text_tables, block=2048)`. The block
size is stored as `self.block` and used instead of the module-level `BLOCK`
constant.

### 2. `unpack()` handles zlib-compressed units (unit byte `+6` == 2)

**Before:** Only handled raw (`unit[6] & 1 == 0`) and pbp bit-level
compression (`unit[6] & 1 == 1`).

**After:** New first branch:
```python
if unit[6] == 2:                           # newer disc: 8-byte raw header + zlib payload
    payload = zlib.decompress(unit[8:])
    nbytes = unit[7] * self.block
    dst = bytearray(nbytes)
    dst[0:8] = unit[0:8]                   # unit header
    dst[8:8 + len(payload)] = payload
    return dst
```
Added `import zlib` at the top of the file.

### 3. Removed module-level `BLOCK = 2048`

The constant is no longer used; block size comes from `self.block`.

---

## Summary of changed files

| File | Changes |
|------|---------|
| `navdb/tools/carindb2gpkg.py` | Block size from header; `BlockFile` class; `open_database()`; `header_info()`/`table_directory()` take `(bf, block_size)`; `units()` uses `BlockFile` and skips gap blocks; all `seek`/`read` replaced with `read_blocks()`; `UnitCache` takes `(bf, block_size)`; parcel box read from unpacked data; defensive bounds clamps; `street_index()` returns `{}` on failure |
| `navdb/tools/parcel.py` | `Unpacker` takes `block` param; `unpack()` handles zlib units (`unit[6] == 2`); `import zlib` added; module-level `BLOCK` removed |

## Behavior on reference disc

On the reference `NAV_DB` disc (2048-byte blocks, single file):
- `open_database()` reads block size `0x0800` = 2048, creates a single-file `BlockFile`
- `BlockFile` reads only from `DB_0` (no `DB_1` sibling exists)
- All `seek`/`read` behavior is identical to the original
- Segment decoding uses legacy `POINT_STEP = 64` buffer offsets
- Output matches the original decoder exactly
