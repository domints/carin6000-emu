# CARiN map database (`carindb`) — format reference

The map file of the Philips CARiN / Renault Carminat (Mk2) navigation, as far as it is known,
written so that a decoder (`navdb/decoder.py`) and an encoder (`navdb/encoder.py`) can be built
from it. Everything comes from the file itself and from the OS-9 modules that read it (`pbp`
unpacks, `dbq` searches, `rpmod` routes), by static analysis. State: 2026-10-23.

**Marks used below:** **confirmed** = seen in the device's code (function named); **checked** =
verified on the data (counts given); **seen** = a pattern in the data only; *open* = not known.

Source of the reference data: the `NAV_DB` disc "carin_maps_pl_2012_2013" (CD 21435,
MapScape / Continental, 2013-04-08): 11 Eastern European countries, Navteq 2012 Q4 data
converted by `dbconv` from GDF 2.1, db release 34.

## Contents

0. [The big picture](#0-the-big-picture)
1. [Conventions](#1-conventions)
2. [File layout](#2-file-layout)
3. [Unit compression](#3-unit-compression-pbp)
4. [Routing parcels](#4-routing-parcels-tables-1-1e-3-2)
5. [House numbers](#5-house-numbers-kind-4-units)
6. [Background](#6-background-tables-6-16-15-1c-14-1d)
7. [POI](#7-poi-tables-7-11-12)
8. [Search](#8-search-tables-b-c-e-d-10-f)
9. [Metadata and TMC](#9-metadata-and-tmc)
10. [Writing a database (encoder rules)](#10-writing-a-database-encoder-rules)
11. [Open questions](#11-open-questions)
12. [Tools and reverse engineering](#12-tools-and-reverse-engineering)

## 0. The big picture

The file is a sequence of 2 KB blocks grouped into **units** (1-8 blocks). Units belong to
**tables**; block 0 lists the tables. What the device does with them:

```
 map display        background units (6 zoom levels: water, forest, built-up, rivers, main roads)
                    + routing parcels (the streets) when zoomed in
 position -> map    spatial index of a table: grid cell -> leaf -> the unit covering the point
 routing            parcels of routing level 0 (all roads) ... level 3 (motorways only):
                    nodes, segments, rings of segments around nodes, links between parcels,
                    a node existing on a higher level is the way up
 address search     block 0 -> country trie (c) -> country (b) -> city trie (e) -> city (d)
                    -> street trie (10) -> street entry (f) -> parcel segments
                    -> house number unit (kind 4) -> exact segment and side
 POI                POI units (7) -> names and details (11), lists per city / category (12)
```

| Table | Content | Section |
|---|---|---|
| 1, 1e, 3, 2 | routing parcels, levels 0-3 | 4 |
| (no id) | per-segment house numbers, after table 1 | 5 |
| 6, 16, 15, 1c, 14, 1d | background, levels 0-5 | 6 |
| 7, 11, 12 | POI points, names / details, letter lists | 7 |
| b, c, e, d, 10, f | countries, city and street search | 8 |
| 17, 4, 0, 18 | info texts, index directory, TMC | 2, 9 |

## 1. Conventions

- **Byte order**: big-endian everywhere.
- **Coordinates** (GPS units): 1 unit = 1.8e-7 degree. Latitude = v × 1.8e-7; longitude =
  v × 1.8e-7 − 30 (stored with +30°). The GPS receiver record uses the same units. Boxes of the
  coarse levels and the index grid start west of the offset, so boxes are signed i32.
- **Blocks**: 2048 bytes. **Units**: 1-8 consecutive blocks (max 16 KB). A **unit pointer** is a
  u32: upper 24 bits = first block, low byte = length in blocks. Every unit starts with its own
  pointer (**checked** on all units); word +4 = unit kind, byte +6 bit 0 = compressed, byte +7 =
  blocks after unpacking.
- **Slots**: most units start with descriptors `(u16 offset, u16 count)` at 8 + 4k that locate
  record arrays ("slot k") inside the (unpacked) unit.
- **Points**: positions inside units are u16 steps from the unit box corner: 64 GPS units (≈ 1 m)
  in parcels and POI units; 2^(6 + level) in background units (byte 0x33).
- **Text**: lower case, Latin-1, 0-terminated, inside the unit, referenced by u16 offsets (0 =
  none). Names are mostly folded to ASCII ("zlota", "lodz").
- **Record sizes**: 93 record types with fixed sizes, from the table in block 0 (`RECSIZE[type]`;
  **confirmed**: `dbq` globals 0x0ef8 + 2·type, `pbp` 0x0cf8, `rpmod` 0x168). The types used here:
  0x05 unit header 8, 0x08 segment 32, 0x09 segment 26, 0x10 node 8, 0x06 edge point 16, 0x0c shape
  point 6, 0x0f neighbour 8, 0x12 class index 4, 0x13 signpost 6, 0x14 prohibited turn 8, 0x15
  attribute 6, 0x37 house numbers 10, 0x3a area 20, 0x3c line 16, 0x40 place 10.
- Success code of the db functions: 499 (0x1f3).

## 2. File layout

### Block 0 (header, table 13)

| Offset | Value | Meaning |
|---|---|---|
| 0x02 | 0x0001 | low byte: CD number (**confirmed** pbp) |
| 0x0c, 0x44 | u32 0x301, u16 0x0c, u16 n | **root of the country trie**: unit (table c, block 3), offset, number of root nodes (9 on the original). **Confirmed on the device**: a wrong count leaves the Country menu empty |
| 0x1a | 34 | db release (pbp warns unless 14-21, works anyway) |
| 0x24 / 0x26 | 0x68 / 31 | offset / count of the table id list |
| 0x28 / 0x2a | 0xa6 / 93 | offset / count of the record size table, (u16 type, u16 size) pairs (**confirmed**) |
| 0x2c | 0x0800 | block size |
| 0x34, 0x50 | 4 × u32 | bounding box of the data (min lon, min lat, max lon, max lat); twice |
| 0x60 | u32 0x201 | pointer to block 2 (index directory) |
| 0x220 | 16-byte entries | **table directory** (after the size table, padded to 16) |

### Table directory

Entry: `u32 a, u32 b, u32 c, u16 id, u16 0` (unit pointers): `a` = start of the table's spatial
index part (0 = none), `b` = first data unit, `c` = **last data unit, inclusive** (**checked**).
An empty table is (0, 0, 0) (table a on the original). Tables lie back to back:

| Table | Kind | Content (original: blocks, share of the file, compressed units) |
|---|---|---|
| 17 | 0x13 | block 1: info texts (section 9) |
| 4 | 7 | block 2: index directory (below) |
| c | 0x0b | block 3: country name trie |
| b | 0x0a | block 4: countries |
| e | 0x0d | city name trie (5-1d) |
| d | 0x0c | cities (24-17e9, 1.7 %) |
| 10 | 0x0f | street name tries per city (17ee-2326, 0.8 %) |
| f | 0x0e | streets with house number ranges (232d-14d84, 21.3 %) |
| 12 | 0x11 | POI letter lists (14d8c-15a4c, 0.9 %) |
| 11 | 0x10 | POI names and details (15a54-1f98e, 11.4 %) |
| 7 | 6 | POI points (1fee4-22a61, 3.1 %, index at 1f990) |
| 1 | 0 | routing level 0, all roads (23fab-45871, 38.4 %, 97 % compressed, index at 22a67) |
| — | 4 | **per-segment house numbers** (45872-4ee77, ≈ 10 %), not in the directory (section 5) |
| 1e, 3, 2 | 3, 2, 1 | routing levels 1, 2, 3 (never compressed) |
| 6, 16, 15, 1c, 14, 1d | 0x16, 0x15, 0x1c, 0x14, 0x1d, 0x1e | background levels 0-5 (mostly compressed) |
| 0, 18 | 0x18, 0x17 | TMC (section 9) |
| a | — | empty |

### Index directory (table 4, block 2; **checked**, `libs/spindex.py`)

Unit kind 7, three slots. Slot 0 from 0x14: 28-byte records `u32 index start pointer, i32 x0,
y0, x1, y1, u16 a, u16 zoom from, u16 zoom to, u16 0`, one per indexed table (pointer 0 = table
empty; an all-zero record is skipped; the list ends at the first record without a 2^29 extent).
The extent is the same for all: x −34 998 272 .. 501 872 640, y −59 092 992 .. 477 777 920 (lon
−36.30°..60.34°, lat −10.64°..86.00°).

| Index of | a | zoom from–to |
|---|---|---|
| 1 (routing 0) | 6 | 0–1 |
| 1e (routing 1) | 2 | 1–120 |
| 3 (routing 2) | 1 | 120–1200 |
| 2 (routing 3) | 0 | 1200–3000 |
| 7 (POI) | 0 | 0–0 |
| 6 (background 0) | 2 | 1–40 |
| 16 (background 1) | 2 | 40–120 |
| 15 (background 2) | 1 | 120–320 |
| 1c (background 3) | 0 | 320–1200 |
| 14 (background 4) | 0 | 1200–3000 |
| 1d (background 5) | 0xffff | 3000–65535 |

Slot 1 (22 bytes) starts with the **unit pointer of TMC table 0** (then *open* offsets / counts;
+8 = a text offset, "ceska republika"). Slot 2 = **22-byte settings per country**, sorted by the
country number (u16 number as in table b +40, then 500, 300, 1000, 0xf401 …); an encoder keeps
only its countries.

### Spatial index (**checked** on all 11 indexed tables, `libs/spindex.py`)

Finds the data unit covering a position. The blocks from a table's index start `a` to its data
start `b` hold kind 8 units, then kind 9 units.

- **Kind 8** (8 blocks, 4092 cells each; the last one shorter): u32 at 0x0c = top cell size;
  slot 0 = u32 pointers to kind 9 units (0 = empty). Together they form an **N × N grid** over
  the directory extent, cell i = column i // N (x), row i mod N (y). N: table 1 512 (2^20 units ≈
  0.19°), 7 256, 1e / 3 / 6 / 16 / 15 32, 2 8, 1c / 14 / 1d 1.
- **Kind 9** (one per non-empty top cell): u32 at 0x10 = subcell size; slot 0 = n × n u16 (n = 1,
  2, 4 … 64, the smallest n whose subcells each lie inside one data unit), column-major; each is
  the byte offset of a u32 unit pointer in slot 1 (4-aligned) of the same unit, 0 = no data.
- Every subcell points to the data unit whose box contains it. `libs/spindex.py` rebuilds all 11
  original index parts **byte for byte** (`tests/test_spindex.py`).

## 3. Unit compression (pbp)

`pbp` reads a unit and, when byte +6 bit 0 is set, `FUN_00003508` expands it into (byte +7)
blocks; otherwise it is copied. By kind: 0 → `FUN_00003eb2` (parcel), 0x14-0x16 and 0x1c-0x1e →
`FUN_00004840` (background; this pbp zeroes compressed 0x1c-0x1e units, but they unpack with the
same code), 0x0e → `FUN_000043a8` (*not ported*; table f is not compressed). Word +6 is cleared
afterwards. Ported 1:1 in `libs/unpack.py`.

**The encoder does not compress.** It writes every unit as the image pbp leaves in RAM, with the
compressed flag clear. The format allows it (all routing parcels of levels 1-3, ≈ 1 240 level 0
parcels and ≈ 10 % of the background units are stored uncompressed on the original); the cost is
only size.

- **Bit reader** (`FUN_00004c16`): MSB-first bitfields (`bfextu`); **width 0 reads 32 bits and
  does not advance**. `bits_for(v)` (`FUN_00004cc2`) = bits for 0..v−1 (1 for v = 1).
- **Text code** (`FUN_00004abc`): `first`, `last` (N bits each), 6 phrases (5-bit length, 7-bit
  bytes), then per byte a 2-bit code: 0 → 1 bit into `ae`, 1 → 2 bits into `str\0`, 2 → 3 bits
  into ` dghilno`, 3 → 7 bits v: v > 0x26 literal, v ≤ 0x1b one of `e0 e1 e2 e3 e4 e5 e7 e8 e9 ea
  eb ec ed ee ef f1 f2 f3 f4 f5 f6 f8 f9 fa fb fc fd ac`, 0x21-0x26 phrase v − 0x21.
- **Delta points**: first x, y 16 bits; then per axis `0` → +d, `10` → −d, `11` → 16 bits.
- **Parcel** (`FUN_00003eb2`): copy 116 bytes; 2 raw bytes (widths); raw copies of slots 3, 9, 10,
  12; bit-coded slots 0, 1, 2, 4 (with a sentinel record), 5, 6, 7, 11, text; for release > 0x14 a
  second pass over slots 0 and 4 and slot 13 cleared. Field order: `libs/unpack.py`.
- **Background** (`FUN_00004840`, `FUN_000044a2`): copy 52 bytes, 4 width bytes, generic expander
  for slots 0, 1, 2 (count + 1 records), 3, text; release > 0x13: slot 4 and second passes.

## 4. Routing parcels (tables 1, 1e, 3, 2)

A parcel is a square piece of the road network. Level 0 (table 1) has every road; levels 1, 2, 3
(tables 1e, 3, 2) only roads of class ≤ 2, ≤ 1, 0, for long-distance routing. Parcel sides are
32 768 · 2^k units on a quadtree aligned to the index grid (level 0: 2^15-2^21; levels 1-3:
2^18-2^21).

### Header (116 bytes)

| Offset | Level 0 | Levels 1-3 |
|---|---|---|
| 0x00 | unit header (kind 0) | unit header (kind 3 / 2 / 1) |
| 0x08 | 15 slot descriptors | same |
| 0x44 | box: i32 x0, y0, x1, y1 | same |
| 0x54 | u32 pointer of the **house number unit** (section 5), 0 = none | 0 |
| 0x58 | u32 **parent parcel** one level up (0 at the top) | same |
| 0x5c | 0 | **child grid cell size** (slot 8) |
| 0x60, 0x64, 0x68 | **travel time to the level 3 / 2 / 1 network** in 0.1 s (below) | 0x20c49b each ("infinite") |
| 0x6c | 10 | 0 |
| 0x70 | byte 0x70 = 1: **has a house number unit**; byte 0x71 = 1 (*open*) | 0x00010000 |

0x60-0x68 (**confirmed** rpmod `FUN_000195e2`, `FUN_000012a4`): the router multiplies them by 100
and sets its search radius per level from them. **Checked** against Dijkstra with the router's
default speeds: ≈ the mean forward time from the parcel's nodes to the nearest node of that level.

### Layout (**checked**, `libs/parcelfmt.py`, `tests/test_parcelfmt.py`: every original parcel byte for byte)

Header, then the slot regions in memory order **0-7, 9, 8, 10-13**, each 4-aligned, then the text
area. An empty slot points at the current position; a descriptor (0, 0) = slot absent (slot 13
after pbp's second pass, slot 14 on levels 1-3).

### Slots

| Slot | Record | Content |
|---|---|---|
| 0, 1, 2 | 0x40 (10 B) | **places**. Slot 0 countries: +0 name, +2 country number (table b +40). Slot 1 cities: +0 name, +2 municipality text, +4 parent country record. Slot 2 streets: +0 street name or 0, +2 settlement / district text or 0, +4 parent city record. +6, +8 0. Each slot starts and ends with an empty record (+4 = the first / last record of the slot above); records sorted by name. Levels 1-3: two empty records each |
| 3 | 0x12 (4 B) | **class index**, 7 + 1 records: record k = (first segment of class ≥ k, first slot 5 node whose best incident class ≥ k); record 7 = ends. Segments are sorted by class, nodes by best class (**checked**) |
| 4 | 0x08 (32 B), 0x09 (26 B) on levels 1-3 | **segments** (below) + a sentinel record (+4, +18, +20, +30 = the ends of slots 7, 10, 12, 11) |
| 5 | 0x10 (8 B) | **nodes**: x, y, +4 a segment at the node (entry into its ring), +6 node byte, +7 0 |
| 6 | 0x06 (16 B) | **edge points** (on the parcel border): x, y, +4 segment, +6 node byte, +7 0, +8 u32 **neighbour parcel**, +12 offset of the same point's edge record there, +14 0 (**checked**: reciprocal) |
| 7 | 0x0c (6 B) | **shape points**: x, y, 0, 0; a segment's shape runs from its +4 to the next segment's +4, start → end (**confirmed** dbq `FUN_000149ba`) |
| 8 | 4 B | levels 1-3: **child grid**: n × n pointers to parcels of the level below, column-major, cell = word 0x5c = the smallest child, at least box / 16; each = the child holding the cell centre, 0 = none |
| 9 | 0x0f (8 B) | **neighbour parcels**: u32 pointer, u16 x, u16 y (a point on the shared border, 64-unit steps) |
| 10 | 0x14 (8 B) | **prohibited turns** (**confirmed** rpmod `FUN_0000bb24`): u32 parcel of the target, u16 target segment, u16 flags; bit 0 = direction on the source (0 = end → start, via its start node; 1 = start → end, via its end node); bit 1 *unused*. A segment's entries run from its +18 to the next segment's +18; the router keeps 8 per direction |
| 11 | 0x13 (6 B) | **signposts** (guidance only): text (destination "krakow"), text (route "e77"), u16 direction; from the segment's +30 |
| 12 | 0x15 (6 B) | **attributes**: u16 type, u16 value, u16 bits; from the segment's +20. Type 5 = **ferry time in minutes**; 6 / 7 / 8 = TMC location (not needed) |
| 13 | — | consumed and cleared by pbp's second pass on level 0 |
| 14 | text | `count × 4` bytes of a name table (zero after pbp unpacks), then the names |

### Segment record (type 0x08; type 0x09 = the first 26 bytes)

How the router reads a segment: rpmod `FUN_0000ce00` (**confirmed** for every field it uses).

| Offset | Content |
|---|---|
| +0, +2 | start / end node (offset of a slot 5 or slot 6 record) |
| +4 | first shape point (slot 7) |
| +6, +8 | **next segment around the start / end node** (0 at an edge point; **checked**: the rings close with length = node degree) |
| +10 | bit 7: **paved** (in the cost key); bits 0-6: speed category, ≈ km/h / 4 (31 motorway, 22 national, 11 street, 5 residential, 2 walkway; not read by the router) |
| +11 | bits 0-3 **form of way** (below), bits 4-5 **one-way** (0 both, 1 start → end, 2 end → start, 3 closed), bit 6 flag (1 on motorways / dual carriageways; use *open*) |
| +12 | **length in metres** |
| +14, +15 | **headings** at start (towards the next point) and end (back towards the previous point), clockwise from north, 256 steps per turn |
| +16 | bits 0-3 **road class** (FRC 0 motorway … 6 minor), bits 4-6 **kind** (5 = not routable; class 6 is usually 1), bit 7 flag (*open*) |
| +17 | low nibble **figure**: 0 none, 2 traffic square, 3 restricted, 5 junction piece, 6 **roundabout**, 9 connector; high nibble **access**: 2 normal, with figure 3: 1 = never entered, 4 = destination only |
| +18, +20 | start of the segment's slot 10 / slot 12 entries |
| +22 | start of slot 13 entries (0 in a level 0 RAM image); +24 0 |
| +26 | level 0: **street record** (slot 2): name, settlement, city, country through the parents |
| +28 | level 0: bits 4-6 **access code** (router: forward search forbids 1, 4, and 3 / 6 from a more important class; backward forbids 2, 3, 5, 6); bit 7 = the paved flag for db releases < 0x15 (usually set); bit 12 always set; bits 0-2 and 11 *open* |
| +30 | level 0: start of the segment's slot 11 entries |

**Form of way** (+11 bits 0-3, **checked** nationwide): 0 motorway, 1-3 motorway junction ramps,
4 dual carriageway (S7, S8), 7 single-carriageway trunk, 8-10 other junction ramps, 11 numbered
road, 12 ordinary road / street, 14 ferry, 15 ferry-like.

### Nodes and topology

Node byte (point +6): bits 0-2 type by degree (1 dead end, 5 pseudo node = degree 2, 0 junction);
bits 4-5: 1 inside (slot 5), 2 edge point (slot 6); bits 6-7: **c = 3 − the highest routing
level the node exists on** (**confirmed** rpmod `FUN_00015eb6`, **checked**: exactly the nodes
with c + level < 3 exist in the parent parcel at the same coordinates). Edge points have c = 3 −
their own level.

- The segments at a node form a **ring** through +6 (node is the start) / +8 (node is the end).
- Where a road crosses into the next parcel both parcels hold an **edge point** at the same
  position, pointing at each other; the router continues there.
- **Levels**: a level L + 1 segment joins two nodes that also exist on level L and stands for the
  level L path between them (**checked**: same length). Up: parent pointer + same coordinates;
  down: the child grid. The router searches level 0 near start and destination until it reaches
  nodes that go up, continues on the coarse levels and comes down again.

### Router cost model (rpmod)

- Cost key = class + 8 × form of way + 128 × paved; travel time = length × table[key]
  (`FUN_0000b148`), ferries: slot 12 type 5 minutes.
- Default speeds (rpmod data 0x18ca, `speed[paved][form of way][class]`, m/s): form of way 0:
  36 (130 km/h) for classes 0-3; 3: 28 for classes 0-1; otherwise 24, 24, 16.5, 12, 7.5, 4.5, 3
  for classes 0-6. Four route profiles (weights at data 0x10aa).
- Turn costs by class pair and turn type (`FUN_0000b2d6`), extra for leaving roundabouts and
  junction pieces, none at pseudo nodes. A route may not use prohibited turns, closed or
  destination-only segments (except from such segments) and access codes as above.

Original counts: level 0 49 031 parcels / 8.6 M segments; level 1 3 278 / 190 k; level 2 1 056 /
70 k; level 3 715 / 22 k.

## 5. House numbers (kind 4 units)

Not in the table directory: the units right after table 1, one per level 0 parcel that has
numbers, pointed at by the parcel's word 0x54 (byte 0x70 = 1) (**confirmed** rpmod
`FUN_000151cc`, the house number search).

Unit: 8-byte header (kind 4), slot 0 (0x10, count = the parcel's segment count), +12 = u32
pointer back to the parcel, then one 10-byte record per segment in segment order:
`left from, right from, left to, right to, scheme`. Left / right for travelling start → end,
"from" at the start node, 32767 = none; scheme 2 normal, 1 mixed (*seen*), 0 none. Sides
**checked** with POI positions (≈ 91 %).

## 6. Background (tables 6, 16, 15, 1c, 14, 1d)

The map picture on 6 levels, fine to coarse (zoom ranges in the index directory): areas (water,
forest, built-up …) and lines (rivers, railways, main roads).

| Level | Table | Kind | Unit side | Point step |
|---|---|---|---|---|
| 0 | 6 | 0x16 | 2^19-2^21 | 64 |
| 1 | 16 | 0x15 | 2^21-2^22 | 128 |
| 2 | 15 | 0x1c | 2^22-2^23 | 256 |
| 3 | 1c | 0x14 | 2^24 | 512 |
| 4 | 14 | 0x1d | 2^25 | 1024 |
| 5 | 1d | 0x1e | 2^26 | 2048 |

Layout (**checked**, `libs/bgfmt.py`, `tests/test_bgfmt.py`: all 6 356 original units byte for
byte): 52-byte header (unit header, slot descriptors 0-5, box at 0x20, word 0x30 = 1, byte 0x33 =
step as a power of two), then the slot regions back to back in order 0-5, no padding; a missing
slot has offset 0.

| Slot | Record | Content |
|---|---|---|
| 0 | 4 B | **groups**: u8 type, u8 kind (0 = areas, 1 = lines), u16 offset of the first record; + an end record (offset = end of the last record region). The order is the **drawing order**: areas 3, 5, 6, 8, 1, then lines 101-106 |
| 1 | 0x3a (20 B) | **areas** + end record (+2 = end of the points): +0 name, +2 first point, +4 area in m², +8 / +12 label position (absolute), +16 0, +18 its slot 5 entry |
| 2 | 0x3c (16 B) | **lines** + end record: +0 name (road number, river), +2 first point, +4 length in metres, +8 its slot 5 entry, +10, +12 0 |
| 3 | 4 B | **points**: u16 x, y steps from the box corner; a record's shape runs to the next record's first point; rings are not closed |
| 4 | 6 B | three u16 (names), only in some units; not needed |
| 5 | 4 B + text | name table, one entry per record (zero in RAM), then the names |

**Area types**: 1 water, 3 forest / park, 5 built-up (named after the town on coarse levels), 6
cemetery, 8 land / island. **Line types** (**checked**): 101 rivers and canals, 102 railways
(level 0), 103 probably borders (levels 3-5), 104 main roads (A, S, main national), 105 other
national roads, 106 voivodeship roads. The original drops 106 above level 1 and 105 above level 2.

## 7. POI (tables 7, 11, 12)

- **Table 7** (kind 6): +8 slot of 28-byte records (+0x0c slot empty), +0x10 box (u32 x0, y0,
  x1, y1; 2^21 square on the original), records at 0x20, then the brand texts. Record: +0 u32
  table 11 unit, +4 offset of the name entry there, +6 / +8 x, y (steps of 64 from the box
  corner), +10 **category**, +12 brand text, +14 0, +16 u32 **POI id** (the same as the detail
  record's +28), +20..+27 0. Spatial index grid 256 (section 2). Categories (named from the data): 11 car dealer, 12 fuel, 13 car rental, 14
  parking, 15 P&R, 20 sight, 21 hotel, 22 restaurant, 23 bank, 24 culture centre, 25 library, 26
  court, 29 embassy, 30 ATM, 31 tourist info, 32 museum, 33 theatre, 35 sport, 36 church, 37
  cemetery, 38 racing, 39 park, 40 exhibition, 41 hospital, 42 police, 43 town hall, 44 post, 45
  clinic, 46 pharmacy, 47 shop, 48 locality, 49 cinema, 50 golf, 51 railway station, 52 airport,
  54 bus station, 56 school, 57 nightlife, 59 car service, 61 company.
- **Table 11** (kind 0x10): name units (section 8 frame, next / previous unit at 0x28 / 0x2c):
  slot 0 = 8-byte name entries (name, flags, second text = district, detail offset), sorted by
  name per list; slot 1 = 40-byte **detail records**; slot 4 = 8-byte **access records** (u32
  level 0 parcel, u16 segment offset in the parcel, u16 side 0 left / 1 right); then the texts.
  Detail: +0 / +4 i32 lon, lat; +8 / +10 offset / count of its access records; texts +12 brand,
  +14 street, +16 city, +18 municipality ("sibensko kninska zupanija"), +20 country, +26 house
  number, +32 phone, +34 postcode; +28 u32 POI id; +22, +24, +36, +38 0.
- **Table 12** (kind 0x11): tries (section 8 frame, 12-byte nodes) into table 11, mostly one
  level (a node per first letter; 444 of 556 769 nodes are inner nodes); a leaf never leaves its
  unit (up to 236 names).
- **Lists**: a list = one category of one city (table d slot 3) or of the whole country (block 4
  slot 3: the original lists 20, 32, 35, 37-40, 52, 53, 58 country-wide). Category record (12 B):
  u32 table 12 unit, u16 offset, u16 count of the trie root, u16 category, u16 offset of the
  category's **brand list** in the same unit (slot 5: 12-byte records u32 table 12 unit, u16
  offset, u16 count, u16 brand text). A brand list runs to the next category's offset; empty
  lists all point at the same place (the text start on the original's block 4).

## 8. Search (tables b, c, e, d, 10, f)

Address entry goes **country → city → street → house number**. Every step is a trie of names
(fast typing) leading to a sorted list of name entries.

### Building blocks

- **Name units** (tables d, f, 11; b in block 4): 0x30-byte header (slots at 8, next / previous
  unit of the list at 0x28 / 0x2c), slot 0 at 0x30 = 8-byte **name entries** `+0 name, +2 flags,
  +4 second text, +6 offset of the entry's record`, sorted; then the records and the texts.
- **Flags**: low byte = language of the name (0x12 Polish, 0x13 Czech, 0x14 Slovak, 0x17
  Slovenian, 0x18 Lithuanian, 0x1a Croatian, 0x1b Latvian, 0xff none); high byte = variant: 0x10
  **rotated words**, 0x02 foreign spelling, 0x01 alternative name. Each variant is its own entry.
- **Rotations** (**checked**): "ulica adama mickiewicza" (0x12) also appears as "adama mickiewicza
  ulica" and "mickiewicza ulica adama" (0x1012): the street word moves to the cut, no rotation
  starts with a number. Multi-word city names rotate the same way without the street word.
- **Tries** (tables c, e, 10, 12): 12-byte header (pointer, kind, 0, slot 0 = nodes at 0x0c),
  12-byte nodes `u32 unit, u8 character, u8 leaf, u16 offset, u16 count, u16 0`; leaf 0 = a list
  of child nodes (in the same unit), leaf 1 = `count` consecutive name entries at offset in a name
  unit. Every name under a node starts with its characters (**checked**).

### The chain

| Step | Where | What |
|---|---|---|
| countries | block 0 0x0c → table c (block 3) → table b (block 4) | b's 56-byte country record: +0 / +4 / +6 table e unit / offset / count = **the country's city trie root**; +24 / +26 country-wide POI categories; +40 **country number**; +46 ISO code ("pl"); +8..+38 constants (*open*) |
| cities | table e → table d | d's 24-byte **city record**: +0 / +4 / +6 table 10 unit / offset / count = **the city's street trie root**; +8 / +10 the city's POI categories (slot 3); +12 parcel and +16 segment offset = the city's destination |
| streets | table 10 → table f | f's entry: +4 = settlement text (0 = the whole city), +6 = a 6-byte **run** `u16 first item, u8 count, u8 1, u16 0` |
| items | table f slot 2 | 24-byte **item**: u32 lon, lat of the settlement, **even from / to, odd from / to** (32767 none), u32 parcel, u16 offset of the first segment, u16 number of consecutive segments |
| number | parcel → house number unit | the exact segment and side (section 5) |

**Cities** in Poland (as Navteq made them): the gminas (municipality = powiat: "piaseczno" /
"powiat piaseczynski", "warszawa" / "warszawa") and the settlements and districts (municipality =
their gmina: "nowa iwiczna" / "lesznowola", "wola" / "warszawa"), each with its own street trie.
A gmina has for every street one entry for the whole gmina plus one per settlement.

City POI lists (table d slot 3, 12 B): u32 table 12 unit, u16 offset, u16 count, u16 category,
u16 offset of the category's brand list (slot 5: 12 B, table 12 unit / offset / count, brand text).

**Country numbers** index the firmware's **country table** (NAV_SW disc; number − 1 = record,
6-byte records: u8 index, 5-byte car registration code, the code the menus show): an
alphabetical English list of 240 countries (1 AFG, 33 BG, 53 HR, 56 CZ, 81 D, 97 H, 171 PL, 176
RO, 188 WAL, 190 SK, 191 SLO, 237 YU, 240 ZW; gaps have no code). Without a map the menus show
D (81). The country name comes from the disc. Serbia has no code of its own: the encoder uses
237 YU, with Croatia's record constants, settings and language byte.

`tests/check_search.py` walks the chain like the device (the original passes 92-99.9 %: names in
other languages; the encoder output 100 %).

## 9. Metadata and TMC

- **Block 1** (table 17, kind 0x13): info texts ("no label", "no description") and the
  **conversion report** at 0x50 (offset at 0x32, length incl. the 0 at 0x34): "1. name:
  eeu_nok_nok_12q4_20130205p", "2. content: eastern-europe", "9. conversion date", "12.
  conversion by" …; box at 0x1c. The encoder writes its own report there (OSM source, conversion
  time in ISO 8601 UTC, host name).
- **TMC** (traffic messages over RDS, not used): table 18 (kind 0x17) = location table (Czech),
  table 0 (kind 0x18) = list of its units (u32 pointer, u16 first record, u16 0); slot 12 types
  6-8 in the parcels; the `CARINET` file on the disc (event texts). The encoder leaves tables 0
  and 18 empty.
- **Disc**: ISO 9660 in MODE2 Form 1 sectors with CD-XA attributes, volume `NAV_DB`, files
  BIBLIOGR (CD id, db release and the **compatible software releases**: kept unchanged), COPYRIGH,
  ABSTRACT, CARINET, carindb at LBA 395 (`tools/mkdisc.py`).

## 10. Writing a database (encoder rules)

What `navdb/encoder.py` does, as rules any writer must follow:

1. **Units as RAM images** (section 3): parcels with slot 13 = (0, 0), segment +22 / +24 = 0
   and zero name tables; background units with zero name tables. Level 0 parcels are then
   compressed (`libs/pack.py`, the inverse of pbp; about 2x), everything else stays uncompressed.
2. **Parcels** on a quadtree aligned to the index grid, at most 8 blocks each. A road becomes
   segments between nodes (junctions, attribute changes, parcel borders); bends are shape points.
   Roads crossing a parcel border are cut; the cut point is an edge point pair (never at a corner,
   never on another vertex, one per pair of parcels). Segments sorted by class, nodes by best
   class, class index, node rings, node bytes, neighbour list.
3. **Levels 1-3**: roads of class ≤ 2 / ≤ 1 / 0, chains through degree-2 nodes joined into one
   segment (length = sum; loops cut in two), shapes simplified; a node kept on a level is kept on
   every level below, node byte c = 3 − its top level; parcels are quadtree ancestors of the level
   below (≥ 2^18 for levels 1-2, ≥ 2^20 for level 3, ≤ 2^21), parent pointers and child grids.
   Level 0 header 0x60-0x68 = mean travel time to each level's network.
4. **House number units** per parcel with numbers (0x54, byte 0x70).
5. **Background**: only for the encoded area, 6 levels with the original unit sizes, groups in
   drawing order, end records, shapes simplified and cut to the area and the unit box; every
   background table gets at least one unit.
6. **Search**: country, cities (gminas + settlements), streets with rotations, tries whose
   leaves stay inside one name unit, linked lists, city destinations; block 0 0x0c / 0x44 = the
   country trie root count; block 2 slot 2 = only our country (settings of its template country).
   Trie leaves are split by size too (big cities' street lists).
7. **POI** (basic set): table 7 points in quadtree tiles (≤ 2^21, ≤ 400 points), table 11 lists
   per (gmina, category) with one access segment each (the nearest road, motorways avoided),
   table 12 tries; city records list their categories, the country record airports and museums;
   brand lists empty.
8. **Spatial indexes** for every indexed table (grid N as the original) and the index directory.
9. **Taken from the original as metadata only**: the record size table and the layout of blocks
   0-2 (with the zoom ranges), the 56-byte country record constants, the disc structure,
   BIBLIOGR and CARINET. No map data.

Verification: `tests/check_db.py` (structure rules; the original passes them too),
`tests/check_search.py` (the address search chain), `tests/compare_osm.py` (road lengths per
attribute group against OSM), decoding with `decoder.py`, and finally the device / emulator.

**OSM mapping** (`libs/osmnet.py`, `osmplaces.py`, `osmaddr.py`, `osmbg.py`, `osmpoi.py`; one
country per disc, `libs/countries.py`):

| OSM | CARiN |
|---|---|
| highway motorway / trunk / primary / secondary / tertiary / unclassified / residential / living_street, service, track | class 0 / 0 / 1 / 2 / 3 / 4 / 5 / 6, 6, 6 (track not routable) |
| motorway, trunk + oneway, \*_link, ref | form of way 0, 4, ramps 1 / 3 / 10, 11 |
| oneway, junction=roundabout, access / motor_vehicle private / destination / no | one-way, figure 6, figure 3 + access 4 / 1 |
| surface unpaved | paved bit 0 |
| name (Poland: + "ulica " unless it starts with a street word), ref; Cyrillic → Latin (đ = dj), then ASCII | street name |
| Poland admin_level 7 / 6 / 8 / 9, place nodes | city (gmina) / municipality (powiat) / settlement / district |
| Serbia admin_level 7 else 8 / 6 / 9 / 8; "Град (Кварт)" → district, "(село)" dropped | city (grad, opština) / municipality (okrug) / settlement (naselje) / district (gradska opština) |
| addr:housenumber + addr:street | house numbers on the nearest segment of the street, by side |
| amenity fuel / hospital / police / bus_station / car_rental / parking + park_ride, tourism hotel / motel / museum, shop car / car_repair, railway station / halt, aeroway aerodrome (iata or public) | POI 12 / 41 / 42 / 54 / 13 / 15, 21 / 32, 11 / 59, 51, 52 |
| natural water, landuse forest, leisure park, landuse cemetery, landuse residential …, place island, waterway river / canal, railway rail | background areas 1, 3, 3, 6, 5, 8 and lines 101, 102 |

## 11. Open questions

None of these blocks map display, routing or address search as far as the device code shows:
the exact meaning of the access codes 1-6 and of figures 5 / 7 / 9 (the router's handling is
known); segment +10 speed category, +11 bit 6, +16 bit 7, +28 bits 0-2 (not used by the router);
parcel byte 0x71; house number scheme 1; country record +8..+38; table 11 detail +22 / +24;
how the device ends the last brand list of a city; the index directory's `a` field and the zoom unit; background slot 4 and line type 103;
TMC tables (not needed); the compression encoder (not needed).

## 12. Tools and reverse engineering

- `tools/extract_navdb.py`: disc image → `temp/navdb/` (carindb, CARINET, …).
- `tools/carindb_header.py`: block 0 dump.
- `decoder.py`, `encoder.py`, `tools/mkdisc.py` and `tests/*`: see `../README.md`.
- `decoder.py [carindb] [-o out.gpkg] [--area NAME | --bbox lon0,lat0,lon1,lat1] [--layers …] [--info]`: layers `parcels`,
  `roads`, `areas`, `overview_roads`, `poi` (with address / phone / postcode), `cities`; RTree
  index; QGIS styles in `layer_styles`.
- `libs/spindex.py`: table 4 index directory and the kind 8 / 9 spatial index (`Index(f, a, b)`:
  `cells(box)` yields the subcells with their data units, `pointers(box)` the data units under a
  box, reading only the index units needed). With `--area` / `--bbox` the decoder reads only those
  units (roads, background, POI), not whole tables.
  Whole database ≈ 20 min, 2.8 GB.
- Newer discs (DB_0 + DB_1, 512-byte blocks, zlib units, other index extent):
  `../../docs/newer_disc_format.md`.
- Ghidra (headless, Java script): `analyzeHeadless temp/navdb/ghidra navdb_db -import
  temp/navdb/mods/*.mod -processor 68000:BE:32:MC68030 -postScript ExportOS9Modules.java
  $PWD/temp/navdb/ghidra_out -scriptPath $PWD/tools/ghidra -overwrite`, then
  `tools/ghidra/resolve_a6.py MODULE.mod EXPORT.md OUT.md` (A6 jump table and globals) and
  `navdb/tools/annotate_dbq.py IN OUT INDEX --base 0x0ef8|0x0cf8` (RECSIZE names for dbq|pbp).
  The script creates functions from `link a5` prologues and sets the Microware calling convention
  (D0, D1, then stack). Module files: `re-safrane/extracted/flash_0209/*.mod`; copies in
  `temp/navdb/mods/`. Do not use `export_os9_modules.py` there: it deletes
  `temp/ghidra/OS9_Batch_Project`. Ghidra stops at the math trap (`trap #15` + a function word);
  `tools/ghidra/dis68k.py` disassembles such ranges with capstone.
- Router: `rpmod` (`temp/extracted/flash_0209/065_rpmod.mod`, copy in `temp/navdb/mods/`) has
  its own copy of the db access library; record size table at data 0x168 (`annotate_dbq.py
  --base 0x168` → `ghidra_out/065_rpmod.annotated.md`, index `rpmod_index.txt`). Key functions:
  `FUN_0000ce00` segment → edge record, `FUN_0000c58e` node ring / edge point walk,
  `FUN_0000b93a` / `FUN_0000b8ae` successors, `FUN_0000bb24` prohibited turn check, `FUN_0000bd04`
  access check, `FUN_0000b148` travel time, `FUN_0000b2d6` turn cost, `FUN_00001d02` cost tables,
  `FUN_00015eb6` node goes up a level, `FUN_000151cc` house number search, `FUN_000195e2` header
  travel times, `FUN_0001d28a` / `FUN_0001d2e4` / `FUN_0001d364` slot 10 / 12 / 11 ranges. dbq is a
  server: request dispatcher `FUN_00006dbc` (codes 0xc8.. → handlers; 0xc8 = slot 10 of a segment,
  0xd5 = segment walk).
- Key functions: pbp `FUN_00003508` dispatch, `FUN_00003eb2` parcel, `FUN_000035de`..`FUN_00003e8a`
  parcel slots, `FUN_00004840`/`FUN_000044a2` background, `FUN_00004abc` text, `FUN_00004c16` bit
  reader, `FUN_000049f2` setup, `FUN_00004a34`/`FUN_00004a5a` raw copies, `FUN_0000325c` record
  sizes, read loop at 0x11fc; dbq `FUN_000128d4` get unit (via pbp), `FUN_00012834` release,
  `FUN_00001890` segment walk, `FUN_000149ba` shape points, `FUN_00004cfc` signposts,
  `FUN_00014dc4`/`FUN_00014f60` record sizes, `FUN_0000c5fa`/`c74c` record search by letter.
