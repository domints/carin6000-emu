# CARiN nav database — newer disc format notes (Opel Astra H / BMW e46 nav generation)

This document captures everything learned while adapting the `carindb2gpkg.py` decoder to a newer
NAV_DB map disc (mounted at `/Volumes/NAV_DB_21709`, files `DB/DB_0` + `DB/DB_1`). The reference
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
