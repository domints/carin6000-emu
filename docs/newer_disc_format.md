# CARiN nav database — newer disc format notes (Opel Astra H / BMW e46 nav generation)

This document captures everything learned while adapting the decoder (`navdb/decoder.py`,
`navdb/libs/`) to a newer NAV_DB map disc (CD 21709, 2015-08-04, HERE 14Q4 "eur_hw_her_bmw", files
`DB/DB_0` + `DB/DB_1`; the decoder expects them in `temp/navdb/`, which may be a symlink to the
disc's `DB` directory). The reference
decoder was written against the `NAV_DB` disc (ISO9660, MapScape/Continental, CD 21435, 2013-04-08,
Eastern Europe, db release 34, 2048-byte blocks). The newer disc uses the same overall structure
but differs in several significant ways.

## 1. Block size

| Field | Reference NAV_DB | Newer disc |
|-------|-----------------|------------|
| Header offset `0x2c` (block size) | `0x0800` = 2048 | `0x0200` = 512 |

The decoder previously hardcoded `BLOCK = 2048`. On the newer disc the block size **must** be read
from the header at offset `0x2c`. Block 0 (the header) is still at byte offset 0 regardless of block
size, so block 0 can be read first to determine the real block size.

## 2. File layout: DB_0 + DB_1 split at 2 GiB

The database is split across two files:

- `DB_0` — exactly 2 GiB (2,147,443,712 bytes = `0x40000000`)
- `DB_1` — the remainder (799,758,336 bytes)

Logical block numbering continues across the split. With 512-byte blocks, `DB_1` resumes at logical
block `0x400000` (2 GiB ÷ 512). This was confirmed by reading DB_1's first unit header: its upper 24
bits (`hi` field of the unit pointer) equal `0x400000`.

`DB_0`'s actual file size is 39,936 bytes short of a full 2 GiB (it holds `0x3fffb2` blocks of 512
instead of `0x400000`), leaving a 78-block zero gap (`0x3fffb2` .. `0x3fffff`) that is never
referenced by the table directory. Reads in that gap must return zero-filled blocks.

All unit pointers are self-consistent when blocks are addressed this way:
- `ptr >> 8` == logical block number
- `ptr & 0xFF` == unit length in blocks (1..255)

### Verified examples

| Table | Logical block | File | Pointer | Kind |
|-------|--------------|------|---------|------|
| 7 (POI) | `0x219322` | DB_0 | `21932201` | `0x06` |
| 1 (parcels) | `0x22ef7a` | DB_0 | `22ef7a0d` | `0x00` (compressed, len=13) |
| 6 (background) | `0x500922` | DB_1 | `50092201` | `0x16` |
| 16 (background) | `0x5593c0` | DB_1 | `5593c001` | `0x15` |
| 18 (names) | `0x57c8c7` | DB_1 | `57c8c70e` | `0x17` |
| f (street index) | `0x37009` | DB_0 | `0370091f` | `0x0e` |

## 3. Unit length can exceed 8 blocks

The reference decoder rejected unit lengths outside `1..8`. On the newer disc, lengths up to 255 are
used (e.g. table 1 parcels use 13 compressed blocks; table f uses 31 blocks). The check was relaxed
to `1 <= length <= 255`.

## 4. Zlib-compressed units (unit byte `+6` == 2)

Unit header byte 6 (`unit[6]`) is a compression method flag:

| Value | Meaning |
|-------|---------|
| `0` | raw / uncompressed |
| `1` | pbp bit-level compression (bit 0 of byte 6 set) |
| `2` | zlib: 8-byte raw header + zlib-compressed payload starting at byte 8 |

For kind-2 units, `unit[7]` holds the uncompressed block count. Decompressing `unit[8:]` with zlib
yields a valid parcel unit whose box (at offset `0x44`) is only correct after decompression.

~4,600 parcel units on this disc are zlib-compressed. The unpacker in `parcel.py` was extended to
detect `unit[6] == 2`, decompress the payload, and prepend the original 8-byte header.

## 5. Table f (street index) is zlib-compressed

On the reference disc, table `f` (kind `0x0e`, 21% of file) was uncompressed but undecoded. On this
disc, table `f` units are zlib-compressed starting at byte 8. Decompression yields ~49 KB of sorted
street-name data per unit. The table is still not decoded (marked "work in progress" in format.md);
the decoder now returns an empty house-number index instead of crashing.

## 6. POI (table 7) format differs

Table 7 units on this disc are uncompressed (byte `+6` == 0) and kind `0x06`, but the slot/record
layout at offset 8 differs from the reference: the `count` field claims far more records than fit in
the unit (e.g. 60,797 records in a 19,968-byte unit). The decoder clamps the count to what fits in
the buffer. POI coordinates decode to valid GPS values, but house numbers / name lookups via table 11
are not yet wired up.

## 7. Segment point encoding (unresolved)

On the reference disc, segment record `+0`/`+2` are buffer offsets into point records in the
unpacked unit, multiplied by `POINT_STEP` (64 GPS units). On this disc, the same fields appear to
contain raw GPS-unit deltas from the parcel box corner rather than buffer offsets. Using `step=1`
GPS unit gives correct coordinates (within ~27 m of known positions); larger steps cluster roads in
the SW corner of parcels. This was not fully resolved before reverting to legacy mode.

## 8. Disc contents

```
/Volumes/NAV_DB_21709/
├── ABSTRACT
├── BIBLIOGR
├── CARINET      (TMC event texts, 750 KB)
├── COPYRIGH
├── DB/
│   ├── DB_0     (2 GiB, logical blocks 0..0x3fffb1)
│   └── DB_1     (763 MiB, logical blocks 0x400000..0x57d55d)
├── DVD9
└── TPD
```

The bounding box in block 0 (offset `0x34`) covers roughly lon -9.16..150.00, lat 34.82..71.97 —
much wider than a single country, suggesting pan-European coverage on this disc.

## 9. Known working decode

With the patched decoder, the Krakow area (bbox 19.8,49.9 → 20.2,50.15) decodes as:

| Layer | Count |
|-------|-------|
| parcels (level 0) | 71 |
| road segments (level 0) | 41,949 |
| parcels (level 1) | 6 |
| road segments (level 1) | 2,090 |
| parcels (level 2) | 2 |
| road segments (level 2) | 787 |
| parcels (level 3) | 2 |
| road segments (level 3) | 204 |
| areas (table 6) | 1,124 |
| overview roads (table 6) | 488 |
| areas (table 16) | 382 |
| overview roads (table 16) | 514 |
| areas (table 1c) | 180 |
| overview roads (table 1c) | 909 |

All road coordinates are valid WGS84 within Poland; none fall in the Czech Republic.

(Counts from before §10-11; with the index lookup and the text area fix level 0 gives 105 parcels /
62 795 segments, 65 % of them named.)

## 10. Index directory and spatial index

- **Table 4** (index directory, kind 7) is no longer block 2 (that is table 17 now) but blocks 3-6
  (4 × 512 bytes): find it through the table directory. Same 28-byte records from 0x14.
- The **grid extent** is a square of **3 × 2^29** units (x −249 987 072 .. 1 360 625 664, y
  −1 132 834 816 .. 477 777 920) instead of 2^29. The record of table 18 (TMC) has a pointer but an
  all-zero extent: skip it, the list continues after it.
- Grid sizes N (kind 8 cells): table 1 1024 (cells of 1 572 864 units ≈ 0.28°), 7 256, 1e/6/16 64,
  3/15 32, 2 16, 1c/14 2, 1d 1. u32 0x0c of every kind 8 unit = extent / N (checked on all 11).
- Kind 8 units are raw; **kind 9 leaves may be zlib units** (+6 == 2, ~10 % in table 1, most of
  them in the coarse tables).
- Position → unit lookup (`spindex.Index`): kind 8 headers only → the kind 8 units holding the top
  cells under the box → their kind 9 leaves → subcells → data unit pointers. **Checked**: for the
  Kraków box it returns exactly the units a full table scan finds by box overlap, on all 11
  tables (table 1: 105 of 103 572 units, 2 ms instead of a scan). `decoder.py --area / --bbox`
  decodes only those units, like the device loads pieces of the disc while driving.

## 11. Edge points: the back-offset is 16 bits

pbp parcels (+6 == 1; Kraków, most of Warsaw, about half of Berlin; Paris is zlib and skips this)
match the reference unpacker except for one field. Slot 6 (edge points, `FUN_00003be4`) ends with
the byte offset of the same point in the neighbour parcel. The reference pbp reads **14 bits**,
enough for a unit of at most 8 × 2048 bytes. On this disc the field is **16 bits** (units run well
past 16 KB). Reading 14 bits leaves the bit stream 2 bits early per edge point, so every later
edge point, the shape points and the text area land on the wrong bits: roads that cross a parcel
border spike across the map, and the street names come out empty or garbage.

`points16` reads 16 bits when the block size is not 2048. Checked on parcels from 1 KB to 48 KB
unpacked: every edge point sits on the parcel border, its neighbour pointer is one of the slot 9
neighbours, and the back-offset is reciprocal (same coordinates in the neighbour). Shape points
then all lie inside the box, and the text area follows slot 7 directly, as on the reference disc.
The reference disc (2048-byte blocks) still reads 14 bits.

## 12. Still open on this disc

- POI (table 7): `--area krakow` gives 0 POI, Paris 1: the record layout differs (§6).
- (Resolved) Table `a` (0x4b6e15 .. 0x4e6181, after table 1) = the kind 4 **house number units**,
  in the directory now (outside it on the reference disc) and **zlib-compressed**. Parcel word
  0x54 points at them as before; decompressed, +12 points back at the parcel. Kraków: ulica
  Floriańska 1-57.
- `cities` still walks the whole of table d (names have no spatial index; the device finds cities
  by name through the tries).
