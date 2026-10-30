# navdb — CARiN / Carminat maps

Tools for the maps of the Philips CARiN / Renault Carminat (Mk2) navigation:

- **decoder**: the original map database (`carindb` from the `NAV_DB` disc) → GeoPackage to view in QGIS;
- **encoder**: OpenStreetMap → your own map database and a disc image for the unit (and the emulator).

The database format was worked out statically, from the file and from the code of the OS-9 modules that read it. Format description: [docs/format.md](docs/format.md).

Only Python 3 is required. The encoder also needs `ogr2ogr` (the GDAL package).

## What do you want to do?

### A. View the original map in QGIS

```bash
python3 navdb/tools/extract_navdb.py          # once: disc image cd/carin_maps_pl_2012_2013.img -> temp/navdb/carindb
python3 navdb/decoder.py --info               # what is in the database
python3 navdb/decoder.py --area warszawa      # Warsaw -> temp/navdb/warszawa.gpkg (a few seconds)
python3 navdb/decoder.py                      # the whole database -> temp/navdb/carindb.gpkg (~20 min, 2.8 GB)
```

Open the `.gpkg` file in QGIS. The styles load automatically.

### B. Make your own map disc from OpenStreetMap

```bash
python3 navdb/encoder.py poland         # Poland (~15 min, 10 GB RAM, ~400 MB disc) -> cd/carin_poland.img + .cue
python3 navdb/encoder.py exyugoslavia   # 8 countries of former Yugoslavia + Albania -> cd/carin_exyugoslavia.img + .cue
```

Run from the repository root. One disc = one package of countries. The encoder downloads the data from Geofabrik itself (one extract per country), converts it with `ogr2ogr` and builds the disc image `cd/carin_PACKAGE.img` + `.cue`.

Checking the result:

```bash
python3 navdb/tests/check_db.py temp/navdb/poland/carindb --every 200     # every 200th parcel, ~5 min
python3 navdb/tests/check_search.py temp/navdb/poland/carindb
python3 navdb/tests/check_db.py temp/navdb/exyugoslavia/carindb --every 200
python3 navdb/tests/check_search.py temp/navdb/exyugoslavia/carindb
```

The disc is used like the original map disc: in the unit (burn it with `cd cd && cdrdao write --device /dev/sr0 carin_poland.cue`) or in the emulator; both are described in the [main README](../README.md). navdb itself never runs the emulator.

### C. Check what the encoder made

```bash
python3 navdb/decoder.py temp/navdb/poland/carindb --area warszawa -o temp/navdb/poland/check.gpkg   # for QGIS
python3 navdb/decoder.py temp/navdb/poland/carindb --info                                            # when and where it was made
python3 navdb/tests/compare_osm.py temp/navdb/poland/check.gpkg 20.85,52.10,21.27,52.37                # road lengths vs OSM
```

## Decoder

```
python3 navdb/decoder.py [carindb] [-o file.gpkg] [--area NAME | --bbox LON0,LAT0,LON1,LAT1]
                         [--layers roads,background,poi,cities] [--info] [-q]
```

- Areas: `warszawa`, `mazowieckie`, `polska`. Without `--area` and `--bbox` the whole database is decoded.
- `--layers` replaces only the selected layers in an existing file; the others stay.
- `--info` shows the data, the countries, the conversion date and place, and the tables.

Layers in the GeoPackage:

| Layer | Contents |
|---|---|
| `roads` | road segments on the 4 routing levels (`level` 0 = all roads): shape, name, district, city, country, class, direction, length, form of way (`fow`: motorway, ramp, ferry…), roundabout / square (`figure`), access, prohibited turns, ferry time, house numbers on the left and right |
| `parcels` | parcel rectangles (the map's tiling) |
| `areas` | background on 6 levels: water, forests and parks, built-up areas, cemeteries, land |
| `overview_roads` | background lines: rivers, railways, main, national and regional roads (`type`) |
| `poi` | points: name, brand, category, street, number, district, city, postcode, phone |
| `cities` | places: name, municipality, other spellings |

**An address in QGIS.** On the `roads` layer use "Select Features by Expression", e.g. for Nowy Świat 29:

```
"level" = 0 AND "name" LIKE '%nowy swiat%' AND "city" = 'warszawa' AND (
  (29 BETWEEN min("hn_left_from","hn_left_to") AND max("hn_left_from","hn_left_to") AND 29 % 2 = "hn_left_from" % 2)
  OR (29 BETWEEN min("hn_right_from","hn_right_to") AND max("hn_right_from","hn_right_to") AND 29 % 2 = "hn_right_from" % 2))
```

Names are stored in lower case, without diacritics and with "ulica" / "aleja" in the name, hence `LIKE '%…%'`.

## Encoder

```
python3 navdb/encoder.py PACKAGE [-t TEMP] [-o DISC.img] [--no-compress] [--detail normal|full]
```

| Package | Countries (Country menu) |
|---|---|
| `poland` | polska |
| `exyugoslavia` | slovenija, hrvatska, bosna i hercegovina, crna gora, srbija, kosovo, makedonija, shqiperia |

Each country is a separate entry in the Country menu, with its own cities. A country's area is its OSM border (admin_level 2); roads, POIs and places outside every country of the package are left out. Routing goes across the borders. ExYugoslavia by country (share of the database): si ~51 MB, hr ~67, ba ~61, me ~14, rs ~107, xk ~33, mk ~24, al ~35.

- `-t TEMP` (default `temp`): the working folder. The downloaded OSM data is in `TEMP/osm` (cache), the database and intermediate files in `TEMP/navdb/PACKAGE/`.
- **OSM cache**: a file older than 7 days — the encoder asks whether to download a fresh one (without a terminal it uses the old one). Older than 30 days — it downloads a new one without asking.
- `-o` (default `cd/carin_PACKAGE.img`): the disc image, with the `.cue` next to it.
- `--no-compress`: road parcels without compression (a bigger disc, useful for debugging).
- `--detail normal` (default) leaves out tracks and unnamed service roads. That is about half of the roads in OSM, and Navteq hardly had them either. `--detail full` takes everything.

What goes into the database (all from OSM and only for the package's countries):

- **Roads** on 4 routing levels, as in the original: from every street down to only the motorways. Each has a shape, class, form of way (motorway, expressway, ramp, ferry), direction, roundabouts and access restrictions.
- **Routing topology**: junctions, crossings between parcels, links between levels, travel times to the fast roads.
- **Prohibited turns** from OSM `restriction` relations (`no_*` and `only_*` via a node; read directly from the `.osm.pbf` file). Restrictions via a way and those for other vehicles only are left out. In Poland about 70 % of the restrictions get in.
- **House numbers** from OSM addresses, assigned to the segments on the left and right side.
- **Address search**: country → municipalities, settlements and districts → streets (by any word of the name, e.g. "mickiewicza") → number.
- **POI** (basic): fuel stations, car dealers and repair shops, car rental, P&R, hotels, hospitals, police, railway and bus stations, airports, museums. They are on the map, in the POI search per city (municipality) and — airports and museums — country-wide. Every POI has a name, brand, address, phone and an access segment for navigation. Warsaw: about 1600 POIs.
- **Background** on 6 zoom levels: water, forests, parks, built-up areas, cemeteries, rivers, railways and overview roads (motorways, expressways, national, regional).
- **Conversion metadata**: the time in ISO 8601 (UTC, with seconds) and the computer's host name. They are in the database (block 1, `decoder.py --info`) and in the ABSTRACT file on the disc.

Not there yet:
- **POI brand lists** (the "brand" menu in the POI search is empty; the brand is on the POI itself);
- **prohibited turns via a way** and time-dependent ones;
- **signposts** (directions on signs).

TMC (traffic messages over RDS) is empty on purpose, as it is not used.

The map data comes only from OSM. From the original disc the encoder takes only metadata: the record size table, the layout of the header blocks with the zoom ranges, the constant country settings, and for the disc image the ISO structure, BIBLIOGR (the list of compatible software versions) and CARINET.

**Countries.** The original disc has 11 countries (bg, cz, ee, hr, hu, lt, lv, pl, ro, si, sk). The country number is an index into the country table of the software (NAV_SW disc): an alphabetical English list of 240 countries with the car registration codes the menus show (171 = PL, 190 = SK, 81 = D…). Every country gets a number of its own (the firmware may pick a country by number alone): the real one where the table has it (si 191 SLO, hr 53 HR, ba 27 BHI, mk 126 MK, al 2 AL), Serbia **237 = YU** (Yugoslavia), Montenegro 235 and Kosovo 236 (unused entries without a code). Full list: [docs/country_table.md](docs/country_table.md). The country names come from the disc. The country settings are taken from Croatia (Slovenia from Slovenia; both are identical on the original), the language byte of the names is Slovenian for si, Croatian for hr / ba / me / rs and "none" (0xff, as the original's bg, hu, ro) for xk / mk / al. What the menus show for a number without a code (me, xk) is not known: check on the device. Cyrillic names are transliterated to Latin without diacritics ("Кнеза Милоша" → "kneza milosa", đ → dj, Macedonian ѓ / ќ / ѕ → gj / kj / dz); bilingual names ("Koper / Capodistria") keep the first part. A new country is added in `libs/countries.py` (number, language, OSM admin levels, package) and its Geofabrik extract in `libs/osmsrc.py`.

**Compression.** Road parcels (the largest part of the database) are compressed with the same bit code as the original. The compressor is the exact inverse of the unit's decompression; on the original parcels it gives an identical result after decompression and about 2× smaller data. The other units are stored uncompressed, which the format allows.

Sizes (with the diet and compression): Poland 553 MB, ExYugoslavia 451 MB (both fit a 74-minute CD-R); the encoder warns if the image is too big. The encoder uses all cores (up to 16). The result does not depend on their number, and `NAVDB_WORKERS=1` turns parallel work off. All of Poland on 20 cores takes about 11 min and 10 GB RAM.

The OSM data is licensed under the ODbL: © OpenStreetMap contributors. The disc carries this notice in COPYRIGH.

## How correctness is checked

Without the emulator, in three layers:

1. **Writer against the original.** Every format writer is checked with a round trip test. An original unit is read into the model and written again, and the result must be identical byte for byte:

   | Test | Scope |
   |---|---|
   | `tests/test_parcelfmt.py` | parcels |
   | `tests/test_bgfmt.py` | 6356 background units |
   | `tests/test_spindex.py` | 11 spatial indexes |
   | `tests/test_pack.py` | parcel compression: original image → our compression → decompression as on the unit |

2. **Structure rules.** `tests/check_db.py` checks the rules found on the original:
   - node rings and edge points;
   - the class index;
   - routing levels and child grids;
   - house numbers and prohibited turns;
   - indexes, background.

   `tests/check_search.py` walks the address and POI search the way the unit does. Both also pass on the original, so the rules themselves are checked too.
3. **Content.** `tests/compare_osm.py` compares the total road lengths (per class, form of way, direction and name) with OSM.

## Directory structure

```
navdb/
  decoder.py           database -> GeoPackage
  encoder.py           OSM -> database
  libs/                the format library (shared)
  tests/               round trip tests and validators
  tools/               disc extraction, disc image, header dump, Ghidra annotations
  docs/format.md       the format description
```

| `libs/` module | What it does |
|---|---|
| `carindb.py` | file basics: blocks, units, coordinates, header, table directory |
| `unpack.py` | unit decompression (a 1:1 port of `pbp`) |
| `parcelfmt.py`, `bgfmt.py` | byte layout of parcels and background units (read and write) |
| `spindex.py` | spatial indexes (read and write) |
| `layers.py`, `gpkg.py`, `qgis_style.py` | decoder: layers, GeoPackage writing, QGIS styles |
| `osmsrc.py` | encoder: downloading and converting Geofabrik regions, reading from several files |
| `countries.py` | encoder: countries (number, language, OSM admin levels) and regions |
| `osmturns.py` | encoder: prohibited turns from OSM relations (`.osm.pbf` reader) |
| `par.py` | encoder: parallel work in processes (fork); `NAVDB_WORKERS=1` turns it off |
| `osmnet.py`, `osmplaces.py`, `osmaddr.py`, `osmbg.py`, `osmpoi.py` | encoder: roads, places, addresses, background and POI from OSM |
| `pack.py` | parcel compression (the inverse of `pbp`) |
| `parcelbuild.py`, `levels.py`, `search.py`, `dbwrite.py` | encoder: parcels, routing levels, search, assembling the file |

| `tools/` tool | What it does |
|---|---|
| `extract_navdb.py [image] [dir]` | extracts the files of the NAV_DB disc to `temp/navdb/` |
| `mkdisc.py [carindb] [-o image] [--chd]` | a disc image with our database (template: the original disc) |
| `carindb_header.py [carindb]` | dumps the database header |
| `annotate_dbq.py IN OUT INDEX --base ADDR` | labels a Ghidra export with record type names |

Data, results and OSM files live in `temp/` (ignored by git), disc images in `cd/`.

## Reverse engineering

The format was read from the code of the OS-9 modules in the unit's flash, decompiled in headless Ghidra:
- `pbp`: decompression;
- `dbq`: search;
- `rpmod`: routing.

How to repeat this and which functions are key is described in [docs/format.md](docs/format.md), section 12.
