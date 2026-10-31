# CD70 navi NAND dump (K9F5608U0C)

Local file: `state/CD70NAVI_K9F5608U0C@TSOP48.BIN` (34,603,008 bytes). `state/` is gitignored, so the binary is not in the repo. This note is the decode; do not re-derive the spare map, the FAT, or the file list.

The image is a SmartMedia (SSFDC) volume. Spare ECC is clean, there are no bad blocks, and the logical map is complete. On top is one FAT12 partition. The software identifies as Siemens VDO EHU4C / HVM0 (same board family as the Opel DVD90 driver in `mame/src/mame/daytona/dvd90.cpp`, which already implements this NAND and its ECC). The NVR version string calls the build **Opel GSW V36P1**, hardware id **0101** (the DVD90 notes use hw id 0104).

## Chip geometry

Samsung K9F5608U0C, 32 MiB plus spare. The dump includes spare.

| | |
|---|---|
| Page | 512 data + 16 spare = 528 bytes |
| Block | 32 pages = 16,896 raw bytes (16 KiB data) |
| Blocks | 2048 |
| Raw size | 2048 × 32 × 528 = 34,603,008 |

Spare layout (same on every page of a block):

| Bytes | Contents |
|---|---|
| 0–3 | `FF FF FF FF` |
| 4 | Data status, `FF` = valid. None other. |
| 5 | Block status, `FF` = good. No factory-bad or worn-out blocks. |
| 6–7 | Logical block address (big-endian) |
| 8–10 | ECC of data bytes 256–511 |
| 11–12 | Copy of the logical block address |
| 13–15 | ECC of data bytes 0–255 |

ECC is the standard SmartMedia 3-byte code over 256 bytes, stored inverted. The routine is `smartmedia_ecc()` in `mame/src/mame/daytona/dvd90.cpp`. Every non-blank page matched. 0 mismatches.

## Logical block map

Block 0 is the CIS, not part of the disk. Its spare address field is `0000`, and page 0 starts with the usual SmartMedia tuples (`01 03 D9 01 FF …`, `CISTPL_VERS_1` strings blank / `0.0`). Do not treat block 0 as FAT.

The other blocks use the SSFDC address in spare bytes 6–7 (byte 11–12 is the copy):

```text
ba = (spare[6] << 8) | spare[7]
valid when (ba & ~0x7FF) == 0x1000
         and odd parity over the low 11 bits
         (Linux ssfdc get_parity(ba & 0x7FF, 11) == 0)
logical = (ba & 0x7FF) >> 1     # 0..999 inside the zone
zone    = physical_block // 1024
```

Two zones of 1024 physical blocks. Each zone has logical blocks 0–999 exactly once (no duplicates, no holes).

| Zone | Physical blocks | Mapped | Erased spares |
|---|---|---|---|
| 0 | 0–1023 | 1000 (block 0 is the CIS, so only 23 erased) | 23 |
| 1 | 1024–2047 | 1000 | 24 |

47 erased blocks total, all `FF` including spare. That is the spare pool, not free FAT space.

Logical disk = 2 × 1000 blocks × 32 × 512 = **32,768,000 bytes = 64,000 sectors**. Pages inside a block are in order. One cluster below is one logical block.

## Partition and FAT12

Sector 0 is an MBR. The only non-zero pre-partition sector is that MBR (sectors 1–30 are zeros). One entry:

| | |
|---|---|
| Bootable | yes (`0x80`) |
| Type | `0x01` FAT12 |
| Start CHS | cyl 0, head 1, sector 16 |
| End CHS | cyl 499, head 7, sector 16 |
| LBA / count | 31 / 63,969 (31 + 63,969 = 64,000, fills the disk) |
| Disk signature | 0 |

BPB at sector 31 (partition start). Jump `E9 00 00`, OEM `uida1186`, type string `FAT12   `, no volume label, volume id 0, boot signature byte 0.

| Field | Value |
|---|---|
| Bytes/sector | 512 |
| Sectors/cluster | 32 (16,384 bytes = one logical NAND block) |
| Reserved sectors | 1 |
| FATs | 2 × 32 sectors, identical |
| Root entries | 512 (32 sectors) |
| Total sectors | 63,969 (`totshort`; `totlong` is 0) |
| Media | `0xF8` |
| Hidden sectors | 31 |
| Geometry | 16 sectors/track, 8 heads |
| FAT start / root / data | sectors 32 / 96 / 128 (absolute) |
| Clusters | 1996. Free 950, in-chain 999, end-of-chain 47, bad 0, reserved 0 |

Free space is 950 × 16 KiB ≈ 15.2 MiB. Allocated clusters are 1046 × 16 KiB. `CHKDSKOK` (empty file) is present, so the volume was checked.

The other two `FAT12   ` signatures in the image are not extra partitions. They are the boot sectors of the nested NVR images, one sector into `nvrimga` (cluster 34) and `nvrimgb` (cluster 42).

## File tree

Only top-level directory is `compunit`. Names below are the long names; 8.3 short names are the usual truncations (`USW_BSIP`, `SPOKENTE`, `SSP_SW~1.LOG`, …). Sizes are file sizes, not allocated size. A blank date means the directory entry timestamp is 0.

```text
compunit/                                          2003-12-10 14:49
  boot/
    code/lowboot                         417,024   1998-01-01 12:01   OS-9000 bootstrap
    data/boot.tib                            230
  test/
    code/testboot                        662,856   2003-12-10 14:49   RoadRunner test image
    data/test.tib                             58
  nav/
    code/navboot                       3,380,272   1998-01-01 12:01   kernel + nav
    code/usw_bsiprocs                  2,135,496   1998-01-01 12:01
    code/usw_stdprocs                  2,836,272   1998-01-01 12:01
    code/usw_modules                     338,804   1998-01-01 12:02
    code/usw_tools                       516,528   1998-01-01 12:02
    code/bsw2                          3,442,352   1998-01-01 12:02
    code/permis.tib                          751   1998-01-01 12:02
    data/nav.tib                             205   2003-12-10 14:49
    data/nav_db.tib                          155   2003-12-10 14:49
    data/nav_ssw.tib                         366   2003-12-10 14:49
    data/nav_mm.tib                          525   2003-12-10 14:49
    data/db_cdinf                            744   1998-01-01 12:00   binary, marker "Tm"
    data/usw_error                         5,604   1998-01-01 12:00   runtime error log
    data/db_id                               180   1998-01-01 12:00   mostly zeros, marker "Tm"
    data/nav_gd.tib                        1,734   1998-01-01 12:01
    data/nav_rp.tib                          168   1998-01-01 12:01
    data/mm_ddb_file                           0   2007-05-20 19:23
    tools/                                                    1998-01-01 12:10   empty
  NVR3/
    nvrimga                              131,072   1998-01-01 13:00   nested FAT12, copy A
    nvrimgb                              131,072   1998-01-01 12:03   nested FAT12, copy B
  swl/
    code/                                                            empty
    data/swl.tib                             261   2003-12-10 14:49
    data/tftp.log                              0   1998-01-01 12:00
    data/ssp_swl_verify.log                1,051   1998-01-01 12:00
    data/ssp_swl_update.log                4,127   1998-01-01 12:00
  data/
    spokentext/gb_f                    2,465,796   1998-01-01 12:00   English voice
    speechrecognition/                                           empty
    compunit.tib                             450
    prodstamp                                480                    mostly 0xFF
    CHKDSKOK                                   0
  code/                                                              empty
```

Deleted directory entries (first character was `0xE5`), left from the software load:

| Where | Name | Size |
|---|---|---|
| `boot/code` | `lowboot.tmp` | 417,024 |
| `boot/code` | `lowboo1` | 417,024 |
| `nav/code` | `nav_db.tio` | 152 |
| `nav/code` | `nav_mm.tio` | 527 |
| `nav/code` | `nav_gd.tio` | 1,734 |
| `nav/code` | `nav_rp.tio` | 168 |
| `nav/code` | `nav.tio` | 171 |
| `NVR3` | `savingnv` | 0 |

The `.tio` files were the pre-merge configs. The update log says their CRC/module sync was wrong and the load wrote the `.tib` files instead. `lowboot.tmp` / `lowboo1` were the staging and reserve copies of the bootstrap.

## What the software says it is

`compunit/data/compunit.tib`:

```ini
[CompUnit]
HWid=0101
ComputerType=HVM0
ApplId=EHU4C
SerialNr=00000000
ATCNumber=10055464FIL00A

[Production]
ProdYear=2004
ProdWeek=42

[Drive]
Type=CDM-M3
FirmwareVersion=CM30430 36
```

`compunit/boot/data/boot.tib`: selected application is `nav`. Paths point at `testboot`, `navboot`, and the CD loader `/V_3/HVM0/0101/EHU4C/loader.ini`.

`compunit/nav/data/nav.tib`: `SwVersion=0101`, `LaVersion=0530`, voice dir `Voices/0530/`.

`compunit/swl/data/swl.tib`: previous software version `0076`, required spoken-text file `d_f.csf` (German). The voice file actually stored is `gb_f` (see below), so this config and the voice file disagree.

`compunit/test/data/test.tib`: `DisplayType=16x9`.

`ssp_swl_update.log` / `ssp_swl_verify.log` are the load from CD. Verify says success. The load was:

- Computer `HVM0`, hw `0101`, application `EHU4C`, load version `V_3`
- Application version on the unit before the load: `0076`. CD application version: `0101`. CD language version: `0540`
- CD path `/cd/V_3/HVM0/0101/EHU4C/`, components `navboot`, `usw_bsiprocs`, `usw_stdprocs`, `usw_modules`, `usw_tools`, `bsw2`, then the `.tio` files and `permis.tib`
- Voices on that CD: `d_f`, `gb_f`, `e_f`, `nl_f`, `f_f`, `i_f`, `s_f`, `dk_f`. The log records copying `d_f.csf` onto `spokentext/d_f`. That file is no longer in the directory.

Code-file headers:

- `lowboot` starts `10 00 00 62 …`. It is the raw bootstrap, not the `4D AD` container. Strings include `OS-9000 Kernel` and `valid OS9000 kernel bootfile`.
- `navboot`, `testboot`, `bsw2`, `usw_*` start with `4D AD` and are OS-9000 bootfiles (a kernel plus modules), not a directory of separate modules. `navboot` carries `kernel`, `OS-9000/MIPS V3.0`, `Copyright (c) 1997-2000 by Microware Systems Corp.`, and `Copyright: 2001 Siemens VDO Automotive`.
- `testboot` carries `VDO Dayton RoadRunner TSW [date: Jun 11 2003, release: 1.81]` and `Siemens VDO Automotive RoadRunner`.

`spokentext/gb_f` header contains `gb_f.csf`, `english`, `0540`, `CSF OKI MSM6585`, `0002`.

`usw_error` is a small binary log. The readable records are `ERROR: OPA NOT AVAILABLE` through Sep–Dec 2011 and `ERROR: No lifesign` on 28 Mar 2012. `mm_ddb_file` was touched 20 May 2007 and is empty. Directory timestamps on the tree are 10 Dec 2003, which matches the USW build date in NVR.

## NVR images

`nvrimga` and `nvrimgb` are 131,072 bytes = 256 sectors. They are not byte-identical (1423 bytes differ). Layout of each:

| Sector | Contents |
|---|---|
| 0 | MBR, one bootable FAT12 partition, start LBA 1, 255 sectors, ends with `55 AA` |
| 1 | FAT12 boot sector, OEM `uida1186`, 512 bytes/sector, 1 sector/cluster, 2 FATs of 1 sector, 512 root entries, 255 total sectors, media `0xF8` |
| data | 220 clusters, 101 used, 119 free |

8.3 names in both copies (same set; a few start clusters differ):

| Name | Size | Note |
|---|---|---|
| `PSTARTUP` | 0 | |
| `SW_VERSI` | 107 | version text, identical in A and B |
| `CD_STATI` | 128 | empty |
| `CONFIG_D` | 2,928 | |
| `COLOUR_D` | 410 | |
| `STATISTI` | 36 | |
| `ERROR_LO` | 801 | |
| `ADDRESSB` | 20,000 | address book, not decoded |
| `FASTSTAR.CFG` | 58 | |
| `NV_GD` | 304 | |
| `ADDRESSE` | 4,054 | |
| `CURSORS` | 101 | |
| `ERROR_MA` | 40 | |
| `NV_DP_RR` | 1,500 | |
| `NV_DP_HB` | 11,112 | |
| `USW_ERR_` | 4,000 | |
| `TOUR_HDL` | 89 | |
| `APDATA` | 1,226 | |
| `?CD` (deleted) | 2,816 | |

`SW_VERSI` in both copies:

```text
0053 USW  (2003.12.10)
30 GSW OPEL V36P1 (2003.12.01)
10.4 BSW (2003.11.24)
1.0 HVM V2.52.1 (2003.11.24)
```
