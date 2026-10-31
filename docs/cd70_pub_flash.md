# CD70 pub update (EHU4 gateway + radio)

Local tree: `cd/Radio-Update-Software-10-10-2007/pub` (128 files, CD dated 10 Oct 2007). The matching external-flash dump is `state/CD70_AM29F800BB@TSOP48.BIN` (1,048,576 bytes). `state/` is gitignored. This note is the decode; do not re-derive the container header, the sector map, or the dump compare.

`pub` is the Siemens VDO EHU4 software-loader update for two processors on the radio side of the set. It is not the nav-computer NAND (`docs/cd70navi_flash.md`). Version files call the two loads **Ehu4 GatewaySw** and **Ehu4 RadioSw**.

Three images, three chips:

| Image | Chip | Where it runs |
|---|---|---|
| `boot0000.gld`, `int*.gld` | ST10F269 internal flash, 256 KB | ST10, on-chip, segments 0–4 |
| `ext*.gld`, and 512 bytes of `swl2100.gld` | AM29F800BB, 1 MB, on the ST10 external bus | ST10 segment `0x10`, CPU `0x100000`–`0x1FFFFF` |
| `radu*.rld` or `ramp*.rld` | TMP92FD54AIF internal flash, 512 KB | Toshiba TLCS-900/H1, single-chip window `0xF80000`–`0xFFFFFF` |

`int*` code is C166. `CALLS` from it land in segments 0, 2, 3, 4 (the ST10 flash) and segment `0x10` (the AM29F800). `radu*` / `ramp*` end in a TLCS-900 vector table of little-endian pointers into `0xF8xxxx` / `0xFAxxxx`.

## Container

Every file in `pub` has the same 14-byte header. Payload starts at offset 14. Bytes 8–9 are the big-endian size of the whole file.

| Offset | Bytes | Meaning |
|---|---|---|
| 0 | 2 | Magic: `2B` `.gld`, `!#` `.rld`, `CE` `.cmd`, `TV` `.ver` |
| 2 | 4 | `00 01 00 01` |
| 6 | 2 | `00 00` |
| 8 | 2 | File size, big-endian |
| 10 | 2 | `00 0E` (header is 14 bytes) |
| 12 | 2 | Checksum. Not decoded. |
| 14 | rest | Payload |

A `.txt` next to a `.cmd` is the same script printed as `eSwlc*` commands. The loader runs the `.cmd`.

## Gateway command order

The software loader (`swl*`) is what actually runs the update. Its strings name `gwys0000.cmd`, `gwyu0000.cmd`, `radu0000.cmd`, `ramp0000.cmd`, TFTP, and `COM1,19200`.

| Script | Role |
|---|---|
| `gwys0000.cmd` / `gwys0000.txt` | Gateway setup. Loads `swl2100`–`swl2500` into RAM and sets the magic byte. |
| `gwyi0000.cmd` / `gwyi0000.txt` | Same SWL load, under the name `GWYINI`. Also RAM only. |
| `gwyu0000.cmd` + `gwyu0001.cmd` | `GwyAppUpdFull`. Patches the AM29F800 boot sector, then writes `int*` and `ext*`. Ends with `GwyBootUpdNone`. |
| `radu0000.cmd` + `radu0001.cmd` | `RadAppUpdFull` for one radio build. |
| `ramp0000.cmd` + `ramp0001.cmd` | Same procedure, the other radio build. |

`gwyu` in order:

1. `ActivateSwlBackupPartition` for blocks 21–25, size `0x043DF8`. That is the byte size of `swl2100`–`swl2500` concatenated.
2. Read AM29F800 block 7 (16 KB boot sector) to RAM, erase it, overlay the first 512 bytes of the SWL image, write the 16 KB back.
3. Erase and write ST10 blocks 1–6 from `int*`.
4. Erase and write AM29F800 blocks 8–19 from `ext*`.
5. CRC the two ranges, write a 14-byte partition record for each, clear the magic byte, `ConvertEeprom`.

CRCs the script checks:

| Range | Start | Length | CRC |
|---|---|---|---|
| ST10 blocks 1–6 | `0x004000` | `0x03BFFC` | `0x253A` |
| AM29F800 blocks 8–19 | `0x104000` | `0x09A2D6` | `0xF914` |

The external length ends at `0x19E2D6`, the last byte of `ext1901.gld`. The boot sector is outside that CRC.

## ST10F269 internal flash

256 KB, seven blocks. The gap `00'8000`–`01'7FFF` is not flash. Block 0 can also be mirrored at `01'0000` when `ROMS1` is set; the files are linked for the segment-0 mapping. Reset fetches `00'0000`.

| Block | Address | Size | File | Payload |
|---|---|---|---|---|
| 0 | `00'0000`–`00'3FFF` | 16 KB | `boot0000.gld` covers the first 512 bytes only | 512 |
| 1 | `00'4000`–`00'5FFF` | 8 KB | `int0100.gld` | `0x2000` |
| 2 | `00'6000`–`00'7FFF` | 8 KB | `int0200.gld` | `0x1FFE` (2 bytes left erased) |
| 3 | `01'8000`–`01'FFFF` | 32 KB | `int0300.gld` | `0x8000` |
| 4 | `02'0000`–`02'FFFF` | 64 KB | `int0400.gld` then `int0401.gld` | `0x8000` + `0x7FF4` |
| 5 | `03'0000`–`03'FFFF` | 64 KB | `int0500.gld` then `int0501.gld` | `0x8000` + `0x7FFE` |
| 6 | `04'0000`–`04'FFFF` | 64 KB | `int0600.gld` then `int0601.gld` | `0x8000` + `0x7FFC` |

Short tails are erased flash (`0xFF`) because the script erases the whole block, then writes a prefix. Payload bytes of blocks 1–6 sum to 245,740. Counting the erased tails of blocks 2, 4 and 5 gives the CRC length `0x03BFFC`.

`boot0000.gld` is 128 C166 `JMPS` instructions, the vector table at `00'0000`–`00'01FF`:

- Reset, word 0: `JMPS 00'4188`. That lands in `int0100.gld`.
- The other 127 slots: `JMPS 0E:xxxx` with the same offset, so the trap goes to segment `0x0E`.

No script names `boot0000.gld`. `gwyu` finishes with `GwyBootUpdNone`, so a field update leaves block 0 alone. The other 15.5 KB of block 0 (`00'0200`–`00'3FFF`) is not on the CD.

`int0300.gld` itself opens with `JMPS 00'4188` and `JMPS 02'172A` (absolute `0x02172A`, inside block 4).

## AM29F800BB on the ST10 bus

Bottom-boot 8 Mbit. CPU address = chip offset + `0x100000`. Script block numbers continue after the seven ST10 blocks, so the chip is blocks 7–25.

Sector order: 16 KB, 8 KB, 8 KB, 32 KB, then fifteen 64 KB sectors.

### What the update writes

| Block | CPU address | Chip offset | Size | File | Payload |
|---|---|---|---|---|---|
| 7 | `0x100000` | `0x00000` | 16 KB | first 512 bytes of `swl2100.gld`, rest kept from the chip | `0x200` overlaid |
| 8 | `0x104000` | `0x04000` | 8 KB | `ext0800.gld` | `0x2000` |
| 9 | `0x106000` | `0x06000` | 8 KB | `ext0900.gld` | `0x2000` |
| 10 | `0x108000` | `0x08000` | 32 KB | `ext1000.gld` | `0x7FFE` |
| 11 | `0x110000` | `0x10000` | 64 KB | `ext1100.gld` + `ext1101.gld` | `0x8000` + `0x8000` |
| 12 | `0x120000` | `0x20000` | 64 KB | `ext1200.gld` + `ext1201.gld` | `0x8000` + `0x7FEC` |
| 13 | `0x130000` | `0x30000` | 64 KB | `ext1300.gld` + `ext1301.gld` | `0x8000` + `0x7FF2` |
| 14 | `0x140000` | `0x40000` | 64 KB | `ext1400.gld` + `ext1401.gld` | `0x8000` + `0x7FEA` |
| 15 | `0x150000` | `0x50000` | 64 KB | `ext1500.gld` + `ext1501.gld` | `0x8000` + `0x7FFC` |
| 16 | `0x160000` | `0x60000` | 64 KB | `ext1600.gld` + `ext1601.gld` | `0x8000` + `0x7FFC` |
| 17 | `0x170000` | `0x70000` | 64 KB | `ext1700.gld` + `ext1701.gld` | `0x8000` + `0x7FFC` |
| 18 | `0x180000` | `0x80000` | 64 KB | `ext1800.gld` + `ext1801.gld` | `0x8000` + `0x7FF8` |
| 19 | `0x190000` | `0x90000` | 64 KB | `ext1900.gld` + `ext1901.gld` | `0x8000` + `0x62D6` |
| 20 | `0x1A0000` | `0xA0000` | 64 KB | none | |
| 21 | `0x1B0000` | `0xB0000` | 64 KB | `swl2100.gld` + `swl2101.gld` if the backup partition is programmed | `0x8000` + `0x8000` |
| 22 | `0x1C0000` | `0xC0000` | 64 KB | `swl2200.gld` + `swl2201.gld` | `0x8000` + `0x8000` |
| 23 | `0x1D0000` | `0xD0000` | 64 KB | `swl2300.gld` + `swl2301.gld` | `0x8000` + `0x8000` |
| 24 | `0x1E0000` | `0xE0000` | 64 KB | `swl2400.gld` + `swl2401.gld` | `0x8000` + `0x8000` |
| 25 | `0x1F0000` | `0xF0000` | 64 KB | `swl2500.gld` | `0x3DF8` |

`swl*` is the loader image, 0x43DF8 bytes, which is blocks 21–25 up through `0xF3DF7`. `gwys` / `gwyi` load those files into RAM. `gwyu` does not erase or program blocks 20–25. The only `swl` bytes it stores on the chip are the 512-byte overlay on block 7, taken from the start of the RAM copy (`JMPS 08'1DAA`).

### Dump `CD70_AM29F800BB@TSOP48.BIN`

Compared against the payloads above. Chip offsets.

| Chip range | Dump | Source |
|---|---|---|
| `0x00000`–`0x001FF` | exact | `swl2100.gld` payload, first 512 bytes |
| `0x00200`–`0x03FFF` | `0x00` | Rest of block 7. The read-modify-write kept an empty tail. |
| `0x04000`–`0x09E2D5` | exact | `ext0800.gld` through `ext1901.gld` |
| short tails inside blocks 10 and 12–19, and `0x09E2D6`–`0x09FFF` | `0xFF` | Erased, not written |
| `0x0A0000`–`0x0AFFFF` | `0x00` | Block 20. Programmed zeros. Not in any file. Erased flash would be `0xFF`. |
| `0x0B0000`–`0x0FFFFF` | `0xFF` | Blocks 21–25. The `swl*` image is not stored here. |

Of 1,048,576 bytes, 631,944 match a `pub` payload (`ext*` plus the 512-byte `swl` prefix). The other 416,632 bytes are only `0x00` or `0xFF`: 15,872 zeros in the boot sector, 65,536 zeros in block 20, 335,224 erased `0xFF`.

`int*`, `boot0000.gld`, `radu*`, and `ramp*` do not occur in this dump.

Rebuilding this dump from `pub`: lay down `ext*` at the offsets in the table, put the first 512 bytes of `swl2100.gld` at chip 0, fill `0x200`–`0x3FFF` and `0xA0000`–`0xAFFFF` with `0x00`, fill every other hole with `0xFF`. The zero sector at `0xA0000` is the one region the update files do not decide; this unit happens to hold zeros.

## TMP92FD54AIF radio flash

512 KB internal flash, ten blocks: six of 64 KB, two of 56 KB, two of 8 KB. `radu0000.txt` erases at the single-boot addresses. After reset in single-chip mode the same bytes are fetched from `0xF80000`. The last 256 bytes of the image are the interrupt vectors (`0xFFFF00`). `radu0034.rld` / `ramp0034.rld` hold that table; the final 16 bytes are `0xFF` (the emulator reserved area `0xFFFFF0`–`0xFFFFFF`).

`radu0001.rld`–`radu0034.rld` concatenate to exactly 512 KB, and so do `ramp0001.rld`–`ramp0034.rld`. They are two builds of one map, not two halves of one chip. `radu0000.rld` and `ramp0000.rld` are the same 2,405-byte file (payload `0x0965`). The script loads it into RAM and passes it to every radio erase and write. It is not programmed.

| Block | Single-boot (program) | Single-chip (execute) | Size | `radu` / `ramp` files | Payload |
|---|---|---|---|---|---|
| 0 | `0x010000` | `0xF80000` | 64 KB | `0001`–`0004` | 4 × `0x4000` |
| 1 | `0x020000` | `0xF90000` | 64 KB | `0005`–`0008` | 4 × `0x4000` |
| 2 | `0x030000` | `0xFA0000` | 64 KB | `0009`–`0012` | 4 × `0x4000` |
| 3 | `0x040000` | `0xFB0000` | 64 KB | `0013`–`0016` | 4 × `0x4000` |
| 4 | `0x050000` | `0xFC0000` | 64 KB | `0017`–`0020` | 4 × `0x4000` |
| 5 | `0x060000` | `0xFD0000` | 64 KB | `0021`–`0024` | 4 × `0x4000` |
| 6 | `0x070000` | `0xFE0000` | 56 KB | `0025`–`0027`, then `0028` | 3 × `0x4000` + `0x2000` |
| 7 | `0x07E000` | `0xFEE000` | 56 KB | `0029`–`0031`, then `0032` | 3 × `0x4000` + `0x2000` |
| 8 | `0x08C000` | `0xFFC000` | 8 KB | `0033` | `0x2000` (all `0xFF` in both builds) |
| 9 | `0x08E000` | `0xFFE000` | 8 KB | `0034` | `0x2000` (vector table at the end) |

## File index

| Files | Count | What they are |
|---|---|---|
| `boot0000.gld` | 1 | ST10 vector table, first 512 bytes of block 0. Not written by this update. |
| `int0100.gld`–`int0601.gld` | 9 | ST10 blocks 1–6. |
| `ext0800.gld`–`ext1901.gld` | 21 | AM29F800 blocks 8–19. Present in the dump. |
| `swl2100.gld`–`swl2500.gld` | 9 | Loader, sized for AM29F800 blocks 21–25. Loaded to RAM. Only the first 512 bytes of `swl2100.gld` are stored on the chip (block 7). |
| `radu0000.rld`, `ramp0000.rld` | 2 | Identical RAM control block for the radio flasher. |
| `radu0001.rld`–`radu0034.rld` | 34 | One full TMP92FD54 image. |
| `ramp0001.rld`–`ramp0034.rld` | 34 | The other full TMP92FD54 image. |
| `*.cmd` / `*.txt` | 8 + 8 | Update scripts and their text decode. |
| `gateway.ver`, `radio.ver` | 2 | `Ehu4 GatewaySw` / `Ehu4 RadioSw`, date `10102007`. |
