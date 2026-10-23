# CARiN map database (`carindb`) — format reference

State: 2026-10-23. Decoder: `navdb/decoder.py` (CLI) with the library in `navdb/libs/` (`carindb.py`, `unpack.py`, `spindex.py`, `layers.py`, `gpkg.py`, `qgis_style.py`).
Source disc: `NAV_DB` (ISO9660, MapScape / Continental, CD 21435, 2013-04-08), Eastern Europe
(PL, CZ, SK, HU, SI, HR, BG, LT, LV), built by `dbconv` from GDF 2.1 (Nokia/Navteq 2012 Q4),
db release 34, "reduced_hnr.cpr".

Everything here comes from the file and from the OS-9 modules that read it (flash 0209: `pbp`,
`dbq`, `dbc`, `dbd`, `dbpa`), by static analysis (Ghidra, see the end). No emulator traces.
**Confirmed** = seen in code (function given); **checked** = verified on decoded data; **seen** =
pattern in the data only.

## 1. Conventions

- Big-endian everywhere.
- **Coordinates** (GPS units): 1 unit = 1.8e-7 degree (1e-9 semicircles). Latitude = v × 1.8e-7;
  longitude = v × 1.8e-7 − 30 (stored with +30°, so all values are positive). The GPS receiver
  record and the map use the same units (`carin-gps-dr-chain` memory).
- **Blocks**: 2048 bytes. **Units**: 1..8 consecutive blocks (max 16 KB). A **unit pointer** is a
  u32: upper 24 bits = first block, low byte = length in blocks. Every unit starts with its own
  pointer (checked on all 49 031 parcels).
- **Point steps**: positions inside parcels / POI units / background units are u16 steps of
  **64 GPS units** (≈ 1 m north-south) from the unit box corner (checked: the maximum coordinate is
  box width / 64 for every parcel size). Background units store the step as a power of two in byte
  0x33 (6 = 64 at level 0, up to 11 = 2048 at level 5; **checked**: the shapes join across units).
- **Signed values**: boxes of the coarse levels and the index grid start west of the +30° offset
  (x < 0), so box words are read as signed i32.
- **Text**: lower case Latin-1, 0-terminated, in a text area of the unit; referenced by u16 offsets
  (0 = none). Names keep the language's letters (ä, ö, …) but are mostly ASCII-folded ("zlota").
- **Record sizes**: 93 record types with fixed sizes, from the block 0 table (`RECSIZE[type]`).
  Both `dbq` (globals 0x0ef8 + 2·type, `FUN_00014dc4` defaults, `FUN_00014f60` load) and `pbp`
  (0x0cf8 + 2·type, `FUN_0000325c` defaults) load it for types < 0x4e (**confirmed**).
- Success code of the db functions: 499 (0x1f3).

## 2. File layout

### Block 0 (header)

| Offset | Value | Meaning |
|---|---|---|
| 0x02 | 0x0001 | low byte: CD number (**confirmed** pbp) |
| 0x08 | 0x0060 | offset of a section at 0x60 (seen) |
| 0x0c, 0x44 | u32 0x301, u16 0x0c, u16 count | **root of the country trie** (table c, block 3): offset and number of root nodes (9 on the original: b c e h l m p r s). **Confirmed** by the device: with the original count and a one-country trie the Country menu stays empty |
| 0x1a | 34 | db release (**confirmed** pbp: warns unless 14..21; `FUN_000034c0` returns it to the unpackers) |
| 0x24 / 0x26 | 0x68 / 31 | offset / count of the table id list (seen) |
| 0x28 / 0x2a | 0xa6 / 93 | offset / count of the record size table, (u16 type, u16 size) pairs (**confirmed**) |
| 0x2c | 0x0800 | block size (seen) |
| 0x34 | 4 × u32 | bounding box min lon, min lat, max lon, max lat (checked: equals the extent of all decoded roads) |
| 0x50 | 4 × u32 | the same box again, last value differs |
| 0x220 | 16-byte entries | table directory (start = end of the size table padded to 16; seen) |
| 0x838 | text | "no label", "no description", the conversion report |
| 0x13b0, 0x25fc | text | country names |

Block 1 has a similar header with a filler box (111111111, 222222222, …).

### Table directory

Entry: `u32 a, u32 b, u32 c, u16 id, u16 0`, unit pointers. `a` = index part start (0 = none),
`b` = data start, `c` = **last unit, inclusive** (checked: c + its length = the next table's
start, and the spatial index references that unit). Tables lie back to back. Unit kind = word +4
of each unit.

| Table | Data blocks | Index | Share | Kind | Compr. | Content | Decoded |
|---|---|---|---|---|---|---|---|
| 1 | 23fab–45871 | 22a67 | 38.4 % | 0 | 97 % | routing level 0 = full road network (parcels) | yes |
| 1e | 4eed8–5092d | 4ee78 | 1.9 % | 3 | no | routing level 1 | yes |
| 3 | 5095d–5118b | 5092e | 0.6 % | 2 | no | routing level 2 | yes |
| 2 | 51198–51549 | 5118c | 0.3 % | 1 | no | routing level 3 | yes |
| 6 | 515a4–55d72 | 5154a | 5.1 % | 0x16 | 90 % | background level 0 (fine) | yes |
| 16 | 55dad–56d67 | 55d73 | 1.1 % | 0x15 | 85 % | background level 1 | yes |
| 15 | 56da5–570e5 | 56d68 | 0.2 % | 0x1c | 69 % | background level 2 | yes |
| 1c | 570ec–571a7 | 570e6 | 0.1 % | 0x14 | 53 % | background level 3 (Central and Eastern Europe) | yes |
| 14 | 571ab–5725e | 571a8 | – | 0x1d | 41 % | background level 4 | yes |
| 1d | 57261–5728d | 5725f | – | 0x1e | 7 % | background level 5 (all Europe, Atlantic, Greenland) | yes |
| 7 | 1fee4–22a61 | 1f990 | 3.1 % | 6 | no | POI | yes |
| 11 | 15a54–1f98e | – | 11.4 % | 0x10 | no | POI names, address, phone, postcode, access segments | yes |
| f | 232d–14d84 | – | 21.3 % | 0x0e | no | street name index with house number ranges | yes (house numbers) |
| d | 24–17e9 | – | 1.7 % | 0x0c | no | cities: names, street trie root, centre segment, POI per category / brand | yes |
| e | 5–1d | – | – | 0x0d | no | city name trie into d | yes |
| 10 | 17ee–2326 | – | 0.8 % | 0x0f | no | street name tries per city, into f | yes |
| 12 | 14d8c–15a4c | – | 0.9 % | 0x11 | no | POI letter lists per city / category / brand, into 11 | yes |
| 18 | 5728f–576f7 | – | 0.3 % | 0x17 | no | TMC location table (Czech), not needed | no |
| 4 | block 2 | – | – | 7 | no | index directory (grid extent + zoom range per indexed table) | yes |
| b | block 4 | – | – | 0x0a | no | countries: city trie root, POI categories, ISO code | yes |
| c | block 3 | – | – | 0x0b | no | country name trie into b | yes |
| 17 | block 1 | – | – | 0x13 | no | database info texts (Navteq 2012 Q4, GDF 2.1) | yes |
| 0 | block 5728e | – | – | 0x18 | no | index of table 18 units (u32 pointer, u16 first record number, u16 0; 143 entries), TMC only | yes |
| a, 13 | – | – | – | – | – | a empty; 13 = block 0 (the header) | – |

**Outside the directory**: blocks 0x45872-0x4ee77 (26 562 units of kind 4, uncompressed, ≈ 10 %
of the file) between table 1 and the index of table 1e = **per-segment house numbers**, one unit
per level 0 parcel, pointed at by the parcel's word 0x54 (**confirmed** rpmod `FUN_000151cc`, the
house number search). Unit: 8-byte header, slot 0 (0x10, count = the parcel's segment count),
+12 = u32 pointer back to the parcel, then 10-byte records (type 0x37), one per segment in segment
order: `left from, right from, left to, right to, scheme` (sides for travelling start → end,
"from" at the start node; 32767 = none; scheme 0 none, 2 normal, 1 rare (mixed?)). Sides
**checked** with POIs: the number of a POI lies in the left pair when its position is left of the
segment (1 327 / 1 463) and in the right pair when right (1 427 / 1 542); the POI's access side
flag (table 11 slot 4) is 0 = left, 1 = right. Warsaw: Nowy Świat 1-72, Marszałkowska up to 142;
68 % of named segments have numbers. Table f's ranges are per street run (several segments) and
differ from these in 68 % of segments; the decoder uses these.

`CARINET` (separate file) = TMC event texts; not needed (no TMC in use).

### Index directory (table 4, block 2; **checked**, `libs/spindex.py`)

Unit kind 7. From offset 0x14, 28-byte records: `u32 index start pointer, i32 x0, y0, x1, y1,
u16 a, u16 zoom from, u16 zoom to, u16 0`; an all-zero record is skipped, the list ends at the
first record without a 2^29 extent. The extent is the same for every table: x −34 998 272 ..
501 872 640, y −59 092 992 .. 477 777 920 (lon −36.30°..60.34°, lat −10.64°..86.00°), 2^29 units square.

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

The zoom unit is not known yet (it looks like a display scale step); `a` is open (it counts down
towards the coarse end of each family).

Table 4 has two more slots after the directory (descriptors at 0x0c and 0x10): slot 1 (22 bytes)
starts with the **unit pointer of TMC table 0**, then offsets / counts (open; +8 = a text offset,
"ceska republika"); slot 2 = **22-byte settings per country**, sorted by country number (u16
number as in table b +40, then 500, 300, 1000, 0xf401, …, 0xffff; +13 = 1 for cz, sk). An encoder
keeps only its countries there.

### Spatial index parts (**checked** on all 11 indexed tables, `libs/spindex.py`)

The blocks from a table's index start `a` up to its data start `b` hold units of kind 8, then kind 9.

- **Kind 8** (always 8 blocks except the last; 4092 cells each; u32 at 0x0c = top cell size): slot 0 (word 8 offset, word 10 count) = u32 pointers
  to kind 9 units, 0 = empty. All kind 8 units of a table together form an **N × N grid** over the
  directory extent; cell i = column i // N (x, west to east), row i mod N (y, south to north). N:
  table 1 512 (cells of 2^20 units ≈ 0.19°), 7 256, 1e/3/6/16/15 32, 2 8, 1c/14/1d 1.
- **Kind 9** (one leaf per non-empty top cell): slot 0 = n × n u16 offsets (n = 1, 2, 4 … 64, chosen
  per leaf by data density: the smallest n whose subcells each lie inside one data unit), subcells
  in the same column-major order, **u32 at 0x10 = subcell size**; slot 1 starts 4-aligned. Each offset is
  the **byte position of a u32 unit pointer** in slot 1 of the same unit, 0 = no data (sea, outside
  the map). Slot 1 = the distinct unit pointers.
- Every subcell points to the data unit (parcel / background unit / POI unit) whose box contains it:
  100 % of the checked subcells, and every unit of tables 1e, 3, 2, 6, 16, 15, 1c, 14, 1d is
  referenced. A position → unit lookup is thus: top cell → leaf → subcell → pointer.
- For the encoder: the grid is fixed by the directory extent, so the writer only needs the data unit
  boxes; pick n per leaf so that each subcell lies within one unit (units form a quadtree).
  `libs/spindex.py` IndexPart rebuilds all 11 original index parts **byte for byte**
  (`tests/test_spindex.py`).

## 3. Unit unpacking (pbp, ported in `libs/unpack.py`)

`pbp` reads the blocks of a unit (`lseek` block·2048, `read` length·2048, up to 5 tries) and, when
byte +6 bit 0 is set, `FUN_00003508` expands it into a buffer of (byte +7) blocks; uncompressed
units are copied. Kind (word +4): 0 → `FUN_00003eb2` (parcel), 0x14..0x16 → `FUN_00004840`
(background), 0x0e → `FUN_000043a8` (not ported; table f is not compressed anyway), other kinds
are zero-filled. Word +6 is cleared afterwards.

### Bit reader (`FUN_00004c16` and the fixed-width wrappers 0x4c2e.. 0x4caa)

MSB-first from a base pointer (`bfextu (A0){pos:w}`), position in bits. `FUN_00004c16(w)` adds w
to the position, then extracts: **w = 0 extracts 32 bits and does not move** (68k bitfield width 0
= 32). The background units rely on it. `N` = `bits_for(size of the unpacked unit)`;
`bits_for(v)` (`FUN_00004cc2`) = number of bits for 0..v−1 (1 for v = 1, 16-bit arithmetic).

### Text code (`FUN_00004abc`)

Read `first`, `last` (N bits each; both 0 = no text), then 6 phrases (5-bit length, 7-bit bytes).
For each byte from `first` to `last`: 2-bit code; 0 → 1 bit into `ae`; 1 → 2 bits into
`str\0`; 2 → 3 bits into ` dghilno`; 3 → 7 bits v: v > 0x26 literal, v ≤ 0x1b index into
`e0 e1 e2 e3 e4 e5 e7 e8 e9 ea eb ec ed ee ef f1 f2 f3 f4 f5 f6 f8 f9 fa fb fc fd ac`,
0x21..0x26 phrase v − 0x21 (copied, the position advances by its length). Tables from pbp data
offsets 0x1342.. (its M$IData). Checked: the Warsaw parcel gives the real street names.

### Delta-coded points

First record: x = 16 bits, y = 16 bits. Next ones, per axis: `0` → prev + d, `10` → prev − d,
`11` → 16 bits absolute; d has a per-unit width (parcels: global 0x0d99, background: 0x0dd0).

## 4. Parcels (tables 1, 1e, 3, 2)

Unit: 8-byte header (type 05: own pointer, kind, +6 compression flag, +7 unpacked blocks), then
the 60-byte parcel header (type 11) = 15 slots `(u16 offset, u16 count)` at 8 + 4k (offsets
into the unpacked unit), box (4 × u32) at 0x44, then (**checked**, all levels):

| Offset | Level 0 | Levels 1-3 |
|---|---|---|
| 0x54 | u32 pointer of the parcel's **house number unit** (kind 4, see below), 0 = none | 0 |
| 0x58 | u32 **parent parcel** one routing level up (table 1 → 1e → 3 → 2; 0 at the top) | same |
| 0x5c | 0 | **child grid cell size** = box width / 16 (slot 8) |
| 0x60, 0x64, 0x68 | **travel time to the routing level 3 / 2 / 1 network** in 0.1 s (rpmod `FUN_000195e2` ×100, `FUN_000012a4`: search radius per level = max(v × g_22a6, g_229a + v × g_229e), then ≥ previous × profile factor). **Checked** against Dijkstra with the router's default speeds: ≈ the mean over the parcel's nodes of the forward time to the nearest node of that level (within a few % for some parcels, up to ±30 % for others; Navteq's own speed model) | 0x20c49b each (2^31 / 1000, "infinite") |
| 0x6c | 10 | 0 |
| 0x70 | byte 0x70 = 1: **has a house number unit** (0x54; rpmod checks this byte before using 0x54); byte 0x71 = 1 in most parcels (open) | 0x00010000 |

The first 116 bytes (type 0x0b) are never compressed.

### Text area (slot 14)

`count × 4` bytes of a name table (u16 text offset, u8 language, u8 flags: e.g. "spalato" language
5 flag 2 for Split) in uncompressed units; **all zero after pbp unpacks a compressed unit**, so the
software does not need it. The names follow, 0-terminated, unsorted, each once. Levels 1-3 have no
text area (slot 14 = (0, 0)).

### Writing parcels (encoder rule)

Write each parcel as the **image pbp produces in RAM** from a compressed unit, stored uncompressed:
slot 13 = (0, 0), segment +22 / +24 = 0, name table zero. That is the state 97 % of the original
parcels are used in. `libs/parcelfmt.py` reproduces every original parcel byte for byte
(`tests/test_parcelfmt.py`).

### Unpacking (`FUN_00003eb2`)

1. copy 116 bytes; widths: W51 = bits_for(count slot 2), W53 = bits_for(count slot 4 + 1),
   W55 = slot 7 + 1, W59 = slot 10 + 1, W57 = slot 11 + 1, W5b = slot 12 + 1;
2. 2 raw bytes → globals 0x0d98 (default width of segment +12) and 0x0d99 (point delta width);
3. raw copies: slot 3 (type 0x12, count + 1 records), slot 9 (0x0f), slot 10 (0x14), slot 12
   (0x15, if count ≠ 0);
4. bit stream: slot 0 (`FUN_000035de`, mode 0x14), slots 1, 2 (`FUN_00003692`, `FUN_00003718`),
   slot 4 segments (`FUN_0000379e`, mode 0x14, with a sentinel record after the last), slot 5
   (`FUN_00003abe`), slot 6 (`FUN_00003be4`), slot 7 (`FUN_00003d28`), slot 11 (`FUN_00003e06`,
   if count ≠ 0), text; release > 0x14: W5d from slot 13, second passes over slots 0 and 4
   (mode 0x15) and slot 13 cleared (`FUN_00003e8a`).
   The exact field order of every expander is in `libs/unpack.py` (1:1 with the C).

### Slots

| Slot | Record | Content (checked on Warsaw unless noted) |
|---|---|---|
| 0, 1, 2 | 0x40 (10 B) | **place hierarchy**: slot 0 countries (+0 name, +2 **country number** as in table b +40, e.g. 53 hrvatska, 191 slovenija), slot 1 cities (+0 name, +2 municipality text, +4 parent country record), slot 2 streets (+0 street name or 0, +2 settlement / district text or 0, +4 parent city record); +6, +8 0. Each slot starts and ends with an empty record (its +4 = the first / last record of the slot above). Records are sorted by name |
| 3 | 0x12 (4 B) | **class index**, count 7 + 1 records: record k = (offset of the first segment of class ≥ k, offset of the first slot 5 node whose most important incident class is ≥ k); record 7 = ends. Segments are sorted by class, slot 5 nodes by their best incident class (**checked**, 246 / 246) |
| 4 | 0x08 (32 B), 0x09 (26 B) on levels 1-3 | **road segments**, below |
| 5 | 0x10 (8 B) | **nodes** inside the parcel: x, y, +4 a segment at this node (entry into the +6/+8 ring), +6 **node byte** (below), +7 0 (rarely 1, 2) |
| 6 | 0x06 (16 B) | **edge points** (x or y = 0 or max): +0 x, +2 y, +4 owning segment, +6 flags (open), +8 u32 **neighbour parcel**, +12 offset of the **same point's edge record there**, +14 0. **Checked**: 10 220 of 10 220 sampled are reciprocal (same coordinates, pointing back) |
| 7 | 0x0c (6 B) | **shape points**: x, y, u8 flags (0 / 2), u8; a segment's shape points run from its +4 to the next segment's +4 (dbq `FUN_000149ba`), in start → end order. **Checked**: they lie between the end points |
| 8 | 4 B | levels 1-3 only: **grid of child parcel pointers** (the level below) over this parcel's box: cell = word 0x5c = the size of the smallest child but at least 1/16 of the box, n = box / cell, column-major like the spatial index, each cell = the child holding its centre (0 = none). Count n² (sometimes fewer: trailing empty columns dropped) |
| 9 | 0x0f (8 B) | **neighbour parcels**: u32 unit pointer, u16 x, u16 y = a point on the shared border in 64-unit steps from this parcel's corner (often its middle); the set equals the edge points' neighbours (**checked**, 407 parcels) |
| 10 | 0x14 (8 B) | **prohibited turns** (**confirmed**, rpmod `FUN_0000ce00` loads them, `FUN_0000bb24` checks, the successor iterators `FUN_0000b93a` / `FUN_0000b8ae` skip a listed target): u32 parcel of the target (nearly always this one), u16 target segment, u16 flags; a segment's entries run from its +18 to the next segment's +18 (rpmod `FUN_0001d28a`). Bit 0 selects the travel direction on the source: 0 = travelling end → start (via node = start), 1 = start → end (via node = end). The router keeps at most 8 per direction. Bit 1 is read by neither rpmod nor dbq. Entries whose target is not at the via node never match (harmless) |
| 11 | 0x13 (6 B) | **signposts** (dbq `FUN_00004cfc`, used by guidance, not by the router): text (destination, "krakow"), text (route number, "e77"), u16 direction 0 / 1; a segment's entries run from its +30 to the next segment's +30 (level 0) |
| 12 | 0x15 (6 B) | **segment attributes** (rpmod `FUN_0000d34e`, `FUN_000109a4`): u16 type, u16 value, u16 bits; a segment's entries run from its +20 to the next segment's +20. Type 5 = **ferry crossing time in minutes** (router: time = 60 × value s); types 6 / 7 = **TMC location** for travel start → end / end → start (value = location code, bits 4-9 of the third word = location table number, bits 0-3 = country code, bits 2/3 of byte +4 direction flags), 8 = TMC (both); TMC is not needed |
| 13 | – | cleared after release > 0x14 pass |
| 14 | – | text area |

### Routing topology (**checked**)

A node is a point record (slot 5 inside, slot 6 on the edge). The segments at a node form a
circular list through +6 (when the node is the segment's start) and +8 (when it is the end). Where
a road crosses into the next parcel, both parcels hold an edge point at the same position, linked
to each other (slot 6 +8 / +12); the router continues there. So an encoder must split roads at
parcel borders, add the edge point pair and fill both rings.

### Segment record (type 0x08; type 0x09 = the first 26 bytes)

The router's reading of a segment is rpmod `FUN_0000ce00` (edge record: +0x0a length, +0x0e/+0x12
byte +17 nibbles, +0x0f one-way, +0x10 form of way, +0x11 class, +0x13 kind, +0x14 paved flag,
+0x15 through traffic, +0x16 level ≥ 1, +0x17, +0x18 access code, +0x19, +0x1a cost key, +0x22 /
+0x24 headings in 1/100 degree, +0x26..+0x2b node flags, +0x3c.. prohibited turns).

| Offset | Content | Check |
|---|---|---|
| +0, +2 | start / end node (offsets of point records in slot 5 or 6) | the network draws correctly everywhere |
| +4 | first **shape point** (slot 7); the shape runs up to the next segment's +4 | **confirmed** dbq `FUN_000149ba` |
| +6, +8 | **next segment around the start / end node** (0 = the node is an edge point, continued in the neighbour parcel) | **checked**: ring length = node degree, 488 690 of 488 903 nodes; **confirmed** rpmod `FUN_0000c58e` |
| +10 bit 7 | flag in the cost key (rpmod: from +10 for db release ≥ 0x15, from +28 bit 7 before); 1 on nearly all roads, 0 on e.g. unpaved streets (ul. Syta): probably **paved** | default speed tables are equal for 0 and 1 |
| +10 bits 0-6 | not read by the router (139 = 0x8b, i.e. 11 with bit 7, most common; open) | |
| +11 bits 0-3 | **form of way** (router cost key, see below): 0 motorway (A1, D1, M6), 1-3 motorway junction ramps ("wezel …", M0 ramps), 4 dual carriageway (S7, S8, Puławska), 7 single-carriageway trunk road (DN1, "8"), 8-10 ramps of other junctions ("wezel powazki"), 11 numbered road, 12 ordinary road / street, 13 rare, 14 **ferry** (Gdańsk–Nynäshamn), 15 ferry-like (router treats 14/15 alike) | nationwide sample |
| +11 bits 4-5 | **one-way**: 0 both, 1 start → end only, 2 end → start only, 3 closed | **confirmed** rpmod `FUN_0000c870` / `FUN_0000c8bc` |
| +11 bit 6 | flag copied to the edge (+0x19; use open) | |
| +12 | **length in metres** | geometric length / value = 1.00 |
| +14, +15 | **headings** at the ends, 256 steps per turn (router: × 36000 / 256) | |
| +16 bits 0-3 | **road class (FRC)** 0 … 6 | |
| +16 bits 4-6 | **kind**: 5 = not routable; the router never moves from a kind ≠ 5 segment onto a kind 5 one | **confirmed** |
| +16 bit 7 | flag copied to the edge (+0x17; use open) | |
| +17 bits 0-3 | **special figure**: 0 none, 2 traffic square ("plac", "trg", "körönd"), 3 restricted access (with high nibble), 5 junction-internal piece, 6 **roundabout**, 7 (rare), 9 unnamed connector. The router adds a turn penalty when leaving a 6, 5 or 7 piece onto another figure (rpmod `FUN_0000b2d6`, globals 0x2272 / 0x2276 / 0x227a) | nationwide sample |
| +17 bits 4-7 | 2 normally; with low nibble 3 (or 4): 1 = **never entered** by the router, 4 = **destination only** (no through traffic) | **confirmed** `FUN_0000b8ae`, `FUN_0000ce00` |
| +18 | start of the segment's slot 10 prohibited turns | **confirmed** |
| +20 | start of the segment's slot 12 attributes | **confirmed** |
| +22, +24 | type 09: +22 = slot 11 start (empty on levels 1-3), +24 0 | |
| +26 | **slot 2 record**: street name, district, then city and country through the parents (type 08 only) | |
| +28 bits 4-6 | level 0: **access code** checked when entering the segment (rpmod `FUN_0000bd04`): forward search forbids 1 and 4, and 3 / 6 when coming from a more important class; backward search forbids 2, 3, 5, 6. Seen: 3, 6 on minor roads (gates / access restrictions; exact meaning open) | **confirmed** use |
| +28 bit 7 | the paved(?) flag for db releases < 0x15 | |
| +30 | level 0: start of the segment's slot 11 signposts | **confirmed** |

Through traffic (edge +0x15) is false for class 6 and for figure 3 / 4 unless the high nibble is
4; a segment without through traffic (and its closed one-way 3) can only be entered from another
such segment, i.e. destination zones.

### Node byte (point +6)

| Bits | Meaning | Check |
|---|---|---|
| 0-2 | node type by degree: 1 = **dead end** (degree 1), 5 = **pseudo node** (degree 2: attribute change; no turn penalty, rpmod `FUN_0000b2d6`), 0 = **junction** (degree ≥ 3); 4 rare (degree 2), 2 rare | **checked** on 41 000 nodes |
| 4-5 | 1 = inside node (slot 5), 2 = **parcel edge point** (slot 6), 3 (rare) | |
| 6-7 | **c = 3 − highest routing level the node exists on**: a node of level L also exists on level L + 1 iff c + L < 3 (rpmod `FUN_00015eb6`) | **checked**: levels 0, 1, 2: exactly the nodes with c + L < 3 have a node at the same coordinates in the parent parcel (+0x58), none of the others |

### Routing levels (macro / micro) (**checked**)

- Level L+1 is a subset network: its nodes are level L nodes (same coordinates), marked by the node
  byte bits 6-7; its segments join such nodes, and one level L+1 segment stands for the level L
  path between them (**checked**: around Warsaw 164 of 166 level 1 segments have exactly the
  length of the shortest level 0 path between the same two nodes, the other two 0.99 / 0.97).
- Up: parcel +0x58 → parent parcel, find the node at the same coordinates.
- Down: slot 8 of a level ≥ 1 parcel = 16 × 16 grid of child parcels (cell size +0x5c).
- So a router searches level 0 around start and destination until it reaches nodes that go up,
  continues on the coarser levels, and comes down again through the child grid.

### Router cost model (rpmod)

- Edge cost key = class + 8 × form of way + 128 × paved flag (0..255).
- Travel time = length × table[key] (`FUN_0000b148`, doubles at global 0x2286); ferries (form of way
  14 / 15) use the slot 12 type 5 duration (minutes × 60) or a default.
- `FUN_00001d02` builds the tables per route profile (4 profiles, weights at data 0x10aa:
  0, 0.9, 0, 0.2) from the **default speeds** at data 0x18ca, `speed[paved][form of way][class]`
  in m/s: form of way 0 (motorway): 36 (130 km/h) for classes 0-3; 3: 28 for classes 0-1;
  otherwise 24, 24, 16.5, 12, 7.5, 4.5, 3 for classes 0-6 (86 … 11 km/h).
- Turn costs: class-to-class penalty tables (7 × 7 u32 at globals 0x21a6 / 0x20e2) by turn type
  (`FUN_0000b65e`), roundabout exits, none at pseudo nodes.
- For the encoder: class and form of way are what decide the speed; prohibited turns, one-way,
  through-traffic and access codes decide what is allowed.

Counts: level 0 49 031 parcels / 8 613 555 segments; level 1 3 278 / 190 263; level 2 1 056 /
70 107; level 3 715 / 22 228.

## 5. Background (tables 6, 16, 15, 1c, 14, 1d = levels 0–5; `FUN_00004840`, `FUN_000044a2`)

Six levels, finer to coarser, ordered by their zoom ranges in the index directory; unit kinds 0x16,
0x15, 0x1c, 0x14, 0x1d, 0x1e; unit box sizes 2^21 … 2^26 units, point step 2^6 … 2^11 (byte 0x33).
This pbp (made for releases 14..21) zeroes compressed units of kinds 0x1c..0x1e; they have the same
layout and unpack correctly with `FUN_00004840` (checked: the coastlines and roads join up).

Unit: 8-byte header, slots 0-4 at 8 + 4k (a 0x3d = 52-byte header, copied raw), box at **0x20**.
Unpacking: copy 52 bytes; Wca = bits_for(count slot 3 + 1); 4 raw bytes → globals 0x0dce,
0x0dcf, 0x0dd0, 0x0dd1 (widths); bit stream with the generic expander `FUN_000044a2(slot, size,
code, mode)` for slot 0 (code 0x25), 1 (0x26), 2 (0x27), 3 (0x0b wide / 0x0a narrow), text;
release > 0x13: 5 bytes → 0x0dd2..0x0dd6, slot 4 (code 0x28, mode 0x14), second passes over slots
1 and 2. Codes 0x25-0x27 handle count + 1 records (sentinel).

| Slot | Record | Content |
|---|---|---|
| 0 | 0x3b (4 B) | groups of slot 1 records by **area type**: 7-bit type, 1 bit, offset of the first record of the group |
| 1 | 0x3a (20 B) | **areas**: +0 name, +2 first point (pointer into slot 3), +4 **area in m²** (Las Kabacki 9.0 km² = real), +8/+12 label position (GPS units, Warsaw → 21.01 E 52.23 N), +16/+18 second pass |
| 2 | 0x3c (16 B) | **generalised roads**: +0 name = road number ("8", "61", "631"), +2 first point, +4 attribute, +8/+10 second pass |
| 3 | 8 B (wide) / 4 B | **points**: wide = absolute u32 lon, u32 lat; narrow = 16-bit x/y offsets in steps of 1 << byte 0x33 from the box. Wide when word (8 + 0x10 + RECSIZE[0x3f]) is 0 |
| 4 | 0x15 (6 B) | three u16 (second pass); meaning open |

A record's shape = points from its +2 pointer to the next record's +2 pointer. Area types: 1
water (seas, lakes, rivers), 3 forest / park, 5 built-up, 6 cemetery, 8 island. Sea polygons are
cut along unit borders (straight lines in the sea). Type 8 also covers Greenland / large land
masses at level 5, so "land" may be the better name. Counts (areas / roads): table 6 253 656 /
110 019, 16 47 739 / 101 277, 15 12 345 / 20 442, 1c 1 072 / 3 756, 14 919 / 3 691, 1d 191 / 77
(before the last-unit fix, so +1 unit each). Level 1-5 road names include foreign roads (Czech
"d1", "d8").

## 6. POI (table 7, kind 6, uncompressed) and their names (table 11)

Unit: +8 slot (offset, count) of 28-byte records, +0x10 box. Record: +0 u32 unit pointer into
**table 11** and +4 u16 offset of an 8-byte name entry there (+0 = text offset of the name in that
unit); +6/+8 x/y (steps of 64 from the box); +10 **category**; +12 **brand** text offset in this
unit ("lukoil", "pko bank polski"); +16 u32 (?); rest 0. 698 013 POI, 44 categories (names in
`POI_CATEGORIES`, from the names under each code): 11 car dealer, 12 fuel, 13 car rental, 14
parking, 15 P&R, 20 sight, 21 hotel, 22 restaurant, 23 bank, 24 culture centre, 25 library,
26 court, 29 embassy, 30 ATM, 31 tourist info, 32 museum, 33 theatre, 35 sport, 36 church, 37
cemetery, 38 racing, 39 park, 40 exhibition, 41 hospital, 42 police, 43 town hall, 44 post, 45
clinic, 46 pharmacy, 47 shop, 48 locality, 49 cinema, 50 golf, 51 railway station, 52 airport, 54
bus station, 56 school, 57 nightlife, 59 car service, 61 company; 16, 53, 55, 58 not named yet.

Table 11 units (kind 0x10) have the layout of table d: 8-byte name entries (+0 name, +2 0x00ff,
+4 0, +6 offset of a detail record).

## 7. Search indexes

### Table f: streets and house numbers (checked)

10 020 units (kind 0x0e, uncompressed), a doubly linked sorted list (+0x28 next unit, +0x2c
previous). Slot 0 at 0x30: 8-byte entries, 2 819 556 street names, sorted (+0 name, +2 flags:
0xff, 0x10ff, 0x12, 0x1012, 0x13, 0x1b …, +4 0, +6 offset of a slot 1 record). Slot 1: 6-byte runs
(+0 offset into slot 2, +2 count, +3 flag). Slot 2: 3 522 574 items of 24 bytes:

| Offset | Content |
|---|---|
| +0, +4 | u32 lon, u32 lat: the town of the street (same for all items of a street) |
| +8, +10 | **house number range** of the run, first pair (32767 = none); whole-run ranges for the street search, not per segment |
| +12, +14 | second pair |
| +16 | u32 unit pointer of a **table 1 parcel** |
| +20 | offset of the first segment (slot 4) in the unpacked parcel |
| +22 | number of consecutive segments of the street |

Check: the segments pointed at carry the same street name (+26); Warsaw: Nowy Świat 1-72, Złota
up to 83, Puławska up to 623, Marszałkowska 1-142. Per-segment numbers come from the kind 4
units instead (section 2, `roads.hn_left_from` … `hn_right_to`). 1 866 553 distinct runs
(several entries point at the same segments, e.g. names in other languages). Open: what the
flags mean (see the name entries below); the street → city link is the table 10 trie.

### Name entries and flags (tables d, f, 11; **checked**)

Tables d, f and 11 share the unit frame: slot 0 at 0x30 = 8-byte name entries, sorted, `+0 name,
+2 flags, +4 second text (d: municipality, 11: district, f: 0), +6 offset of the entry's record`;
+0x28 / +0x2c = next / previous unit (a doubly linked list). Flags: **low byte = language /
country code** of the name (0x12 Polish, 0x13 Czech, 0x14 Slovak, 0x17 Slovenian, 0x18
Lithuanian, 0x1a Croatian, 0x1b Latvian, 0xff none: Romanian, Bulgarian, Hungarian names);
**high byte = variant bits**: 0x10 words rotated for search ("ablanovo dolno" for "dolno
ablanovo", "ulica marszalkowska" / "marszalkowska ulica"), 0x02 foreign spelling ("bourgas",
"blagoewgrad"), 0x01 alternative name. Each variant is its own entry pointing at the same record.

### Tries (tables e and 10; **checked**)

12-byte nodes: `u32 unit pointer, u8 character, u8 leaf, u16 offset, u16 count, u16 0`. leaf 0:
the next character's node list (count nodes at offset in the unit pointed at, in table 10 / e
itself); leaf 1: a run of `count` consecutive name entries (slot 0) at offset in the unit pointed
at. Prefixes are complete: every name under a node starts with its characters (checked on all 13 459
street entries of Warsaw, depth 1-8).
- **Table 10** (kind 0x0f) = per city **street name trie** into table f; the root list is given by the
  city record (+0/+4/+6). This is the street → city link: a city's streets are reached only
  through it (Warsaw: 33 root nodes, 13 459 entries, 11 175 distinct names).
- **Table e** (kind 0x0d, 4 units) = **city name trie** into table d, one root per country (the
  country record in table b gives it); table d is grouped by country.

### Table d: cities (kind 0x0c; **checked**)

Slot 0 = name entries (second text = municipality / district). Slot 1 = 24-byte **city records**:

| Offset | Content |
|---|---|
| +0 | u32 unit pointer into **table 10** (street trie root) |
| +4, +6 | offset, count of the root nodes |
| +8, +10 | offset, count of the city's **POI category entries** (slot 3) |
| +12 | u32 unit pointer of a **table 1 parcel** |
| +16 | offset of a **segment** (slot 4) in the unpacked parcel: the city's destination point (its place chain holds the city name in 75 %, the municipality in 94 % of sampled cities) |
| +18..+23 | 0 |

Slot 3 = 12-byte **POI category entries**: `u32 table 12 pointer, u16 offset, u16 count` (the
letter list of the POI names of this category in this city), `u16 category` (the table 7 code:
11 dealers, 12 fuel …), `u16 offset into slot 5` (the brand list; the next entry's value ends it).
Slot 5 = 12-byte **brand entries**: `u32 table 12 pointer, u16 offset, u16 count` (letter list of the
POIs of that brand), `u16 brand text offset` in this unit ("audi" … "volvo" for dealers in Warsaw,
"orlen", "bp", "shell" … for fuel), `u16 0`.

### Table 12: POI letter lists (kind 0x11; **checked**)

Trie nodes as above (one level: one node per first letter, leaf 1) into the table 11 name entries.

### Table 11: POI names and details (kind 0x10; **checked**)

Slot 0 = name entries (second text = district, e.g. "bemowo"), +6 = offset of a 40-byte **detail
record** (slot 1). Table 7 POI records point at their name entry (+0 unit, +4 offset).

| Offset | Content |
|---|---|
| +0, +4 | u32 lon, u32 lat (equal to the table 7 position) |
| +8, +10 | offset, count of the **access segments** (slot 4) |
| +12 | text: brand ("suzuki", "kia") |
| +14 | text: street ("ulica powstancow slaskich") |
| +16, +18 | text: city, city again (or municipality) |
| +20 | text: country ("polska") |
| +22, +24 | text, mostly 0 (open) |
| +26 | text: **house number** ("194") |
| +28 | u32, open (unique per POI, maybe an ID) |
| +32 | text: **phone** ("+48-225331111") |
| +34 | text: **postcode** ("01-466") |
| +36, +38 | 0 |

Slot 4 = 8-byte access segments: `u32 table 1 parcel pointer, u16 segment offset, u16 side`
(0 / 1; probably left / right of the segment). Checked: 143 of 147 segments carry the POI's street.

### Street entries in detail (table f; **checked** on Piaseczno)

- Entry `+0 name, +2 flags, +4 settlement text (0 = the whole city), +6 offset of its run`; a gmina
  has for every street one entry for the whole gmina plus one per settlement, a settlement city
  one per street. Every name has **word rotations**: "ulica adama mickiewicza" (flags 0x12),
  "adama mickiewicza ulica" and "mickiewicza ulica adama" (0x1012): the leading street word moves
  to the cut, no rotation starts with a number.
- Run (6 B): `u16 offset of the first item, u8 count, u8 1, u16 0`; runs may share items.
- Item (24 B): `u32 lon, u32 lat` of the settlement / town, **even from / to, odd from / to**
  (32767 none) over its segments, `u32 parcel, u16 offset of the first segment, u16 number of
  consecutive segments` (one street of one class in one parcel).
- Table d holds the gminas (municipality = powiat, "piaseczno" / "powiat piaseczynski") and the
  settlements (municipality = their gmina, "nowa iwiczna" / "lesznowola"), each with its own street
  trie. Units of d / f: 0x30-byte header (slots at 8, next / previous unit at 0x28 / 0x2c).
  Trie units (c, e, 10, 12): 12-byte header (pointer, kind, 0, slot 0 = nodes at 0x0c).
- `tests/check_search.py` walks country -> city -> street -> items like the device: the original
  passes 99.9 % / 92 % (other-language names), the encoder output 100 %.

### Table b: countries (block 4, kind 0x0a; **checked**) and table c (block 3)

Slot 0 = name entries ("balgaria", "ceska republika", "eesti", "hrvatska", "latvija", "lietuva",
"magyarorszag", "polska", "românia", "slovenija", "slovenska republika"; flags = language code as
in d). Slot 1 = 56-byte **country records**:

| Offset | Content |
|---|---|
| +0, +4, +6 | u32 table e pointer, offset, count: **root of the city name trie** of this country (Poland 0xd08 / 0x2514 / 23 nodes; Bulgaria 0x508 / 0x0c / 24) |
| +8..+22 | four u32 11, 22, 33, 44 (same for all; open) |
| +24, +26 | offset, count of the **country-wide POI category entries** (slot 3, the city slot 3 format: attractions 20, museums 32, airports 52 …) |
| +28..+34 | 500, 300, 1000, 500 (same for all; open) |
| +38 | 1 for cz, sk, else 0 (open) |
| +40 | u16 country number (bg 33, cz 56, ee 67, hr 53, lv 117, lt 123, hu 97, pl 171, ro 176, si 191, sk 190; open) |
| +46 | **ISO 3166 code**, 2 characters ("pl") |

Table c (block 3, kind 0x0b) = the country name trie (one node per first letter, into b).

### Table 17: database info (block 1, kind 0x13)

Key / value texts: "content" eastern-europe, "supplier", "conv tool version", "name" eeu_nok_nok_12q4_20130205p
(Navteq 2012 Q4, converted 2013-02-05), "conv tool version" prod_20130205/nok2012q2, "gdf version" 2.1, "tmc included", "conversion by" dbconv, "conditional access"
false. Block 0 holds the same header fields as block 1.

### Table 18: TMC location table (kind 0x17; not decoded)

Czech TMC locations (regions "Jihomoravský kraj", junctions "propojka", "nájezd"): RDS-TMC only,
not needed.

## 8. For the encoder

What a writer must produce, by what we know:
1. Block 0: header fields above, record size table (copy), table directory, texts; block 1-4
   small tables (info, index directory, country trie, countries).
2. Routing level 0 parcels: a quadtree of boxes (64-unit grid, sizes 32 768 · 2^k units). A road
   becomes segments between nodes (junctions, attribute changes, parcel border crossings); the
   bends in between are the segment's shape points (slot 7). Per
   segment: end nodes, shape points, node rings (+6/+8), one-way, length, headings, class, form of
   way, figure / access nibbles, paved flag, access code, prohibited turns (slot 10), attributes
   (slot 12: ferry minutes), signposts (slot 11, optional), place record (slots 0-2). Nodes: node
   byte (type, inside / edge, top level c). Edge points in pairs with the neighbour parcel (slot 6),
   neighbour list (slot 9). House number unit (kind 4) per parcel, pointer at 0x54.
3. Routing levels 1-3: subsets of the level below (nodes at identical coordinates, marked by c in
   the node byte; a coarse segment = the shortest path below, same length), parent pointers
   (0x58), child grid (slot 8, cell size at 0x5c), header constants (0x60-0x70). Simplest start:
   level 1-3 with only class 0-2 / 0-1 / 0 roads, as the original does.
4. Then the bit-level compression (inverse of section 3), or uncompressed units (allowed: 1 240
   parcels are stored uncompressed).
5. Background units (areas, generalised roads) on 6 levels, POI units + table 11 names and details,
   search indexes (countries b/c, cities d/e, street tries 10, streets f, POI letter lists 12),
   the spatial index parts of every table (section 2) and the block 2 index directory.
6. Verification: decode the output with `decoder.py` and compare; then run it in the emulator
   (the map draws when the car position is set manually).

Open items (none of them blocks routing as far as the router code shows): slot 3 (pairs of
offsets), flags of slot 6 (+6), slot 9 (+4, +6) and slot 7 (+4); node type values 1 and 2;
segment +10 bits 0-6, +11 bit 6, +16 bit 7 (copied by the router, use not found), the exact
meaning of figures 5 / 7 / 9 and of the access codes 1-6; parcel +0x60 / 0x64 / 0x68 / 0x70 on
level 0; house number scheme 1; table 11 +22 / +24 / +28; country record +8..+40; POI +16; the
index directory's `a` field and zoom unit. Not needed: tables 0 and 18, slot 12 types 6-8 (TMC).

## 9. Tools and workflow

- `tools/extract_navdb.py`: disc image → `temp/navdb/` (carindb, CARINET, …).
- `tools/carindb_header.py`: block 0 dump.
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
  `temp/ghidra/OS9_Batch_Project`.
- Router: `rpmod` (`temp/extracted/flash_0209/065_rpmod.mod`, copy in `temp/navdb/mods/`) has
  its own copy of the db access library; record size table at data 0x168 (`annotate_dbq.py
  --base 0x168` → `ghidra_out/065_rpmod.annotated.md`, index `rpmod_index.txt`). Key functions:
  `FUN_0000ce00` segment → edge record, `FUN_0000c58e` node ring / edge point walk,
  `FUN_0000b93a` / `FUN_0000b8ae` successors, `FUN_0000bb24` prohibited turn check, `FUN_0000bd04`
  access check, `FUN_0000b148` travel time, `FUN_0000b2d6` turn cost, `FUN_00001d02` cost tables
  (math via `trap #15` + function word: disassemble with capstone, Ghidra stops there),
  `FUN_00015eb6` node goes up a level, `FUN_000151cc` house number search, `FUN_0001d28a` /
  `FUN_0001d2e4` / `FUN_0001d364` slot 10 / 12 / 11 ranges. dbq is a server: request dispatcher
  `FUN_00006dbc` (codes 0xc8.. → handlers; 0xc8 = slot 10 of a segment, 0xd5 = segment walk).
- Key functions: pbp `FUN_00003508` dispatch, `FUN_00003eb2` parcel, `FUN_000035de`..`FUN_00003e8a`
  parcel slots, `FUN_00004840`/`FUN_000044a2` background, `FUN_00004abc` text, `FUN_00004c16` bit
  reader, `FUN_000049f2` setup, `FUN_00004a34`/`FUN_00004a5a` raw copies, `FUN_0000325c` record
  sizes, read loop at 0x11fc; dbq `FUN_000128d4` get unit (via pbp), `FUN_00012834` release,
  `FUN_00001890` segment walk, `FUN_00014dc4`/`FUN_00014f60` record sizes, `FUN_0000c5fa`/`c74c`
  record search by letter.
