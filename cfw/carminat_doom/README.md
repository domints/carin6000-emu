# Carminat Doom

Doom (doomgeneric, GPL-2) on the CARiN / Renault Carminat navigation unit: 68EC030 @ 16 MHz, OS-9, an SCC66470 screen of 384×240 in RRRGGGBB colours. It starts from the disc and leaves the flash untouched. The WAD is Freedoom: Phase 1 (BSD license) cut down to one map.

Status: the game runs in the emulator (E1M1, panel controls, colours, status bar) at about 2–3 frames/s (emulator timing; real hardware will show in the benchmark from `../poc`).

## Building

```bash
make -C cfw/carminat_doom chd      # cd/carminat_doom.img + .cue + .chd
tools/carin.py gui --state doom --seed --cd cd/carminat_doom.cue   # empty flash: straight from the disc
```

Needs `m68k-elf-gcc` with `m68k-elf-newlib`, `chdman` and `cd/carin_nav_sw.img`. The Freedoom zip is downloaded to `build/dl/` automatically. Binaries (`build/`, the image, the WAD) are outside git.

Burn it like the PoC: `cd cd && cdrdao write --device /dev/sr0 carminat_doom.cue`. The disc works on both hardware variants (0109 and 0209).

## How it works

1. **Disc** (`tools/cdfile.py` + `../poc/tools/mkdisc.py`): a copy of NAV_SW in which:
   - `ui_handler` (the installer UI) is the program that loads Doom (`loader/`);
   - `il` (the installer) is the stub from the PoC that only sleeps;
   - the Doom image and the WAD are appended to the end of the disc as new sectors, and the directory entries `language_cd/d_f.csf` and `e_f.csf` point to them (LBN and size, plus the volume size in the label). The CD-i file system is not rebuilt.
2. **Loader** (`loader/loader.c`, an OS-9 module without global variables, like the PoC):
   - first takes a block for the image, bss, the malloc heap (64 KB) and the stack (32 KB), then the rest of the free memory for Doom's zone, in at most 8 blocks: Extension RAM (2 MB, if present), the VSC Development RAM (0x680000, 512 KB), what is left of system RAM and of the USW area. It leaves 48 KB to the system. Blocks from video RAM and from the memory shared with the slave, which the free memory list also shows, are held until allocation is done and then returned, never used. Fast system RAM goes to the start of the zone, so the level data lands there and not in the slower VSC memory;
   - the real 0209 unit has no Extension RAM (the first version died with `no RAM for the zone, error 0ED`, i.e. E$NoRAM). Free there were 952K of system RAM, 512K Development RAM, 64K USW. The emulator reproduces this with `tools/carin.py ... --no-ext-ram`;
   - for a zone made of several blocks, or on an error, it prints the free memory map from before its own allocations (`F$GBlkMp`; not possible later, because this call hangs when the memory area is completely used). A zone smaller than 512 KB is an error;
   - loads `/cd/language_cd/d_f.csf`, applies the R_68K_32 relocations, clears bss and jumps to Doom on a new stack.
3. **Doom image** (`tools/mkflat.py`): an ELF linked at address 0 (`doom.ld`, `--emit-relocs`), turned into a flat image with a relocation table. Doom is plain C with global variables and newlib.
4. **System calls** (`src/syscalls.c`, `src/os9.S`): files are OS-9 paths (read only, I$Seek/SS_Size), the console is UART A, `sbrk` hands out the heap from the loader.
5. **Backend** (`src/dg_carminat.c`):
   - `DG_ScreenBuffer` is the screen buffer itself (384×240), so a 320×200 frame reaches the screen with one copy;
   - colours: a PLAYPAL → RGB332 table is put into `COLORMAP` on every palette change (flashes work), and patch drawing (status bar, menu, HUD), the automap and the border go through the same table.
6. **WAD** (`tools/wadstrip.py`): one map is kept (`MAP=E1M1`). Plus the textures of its sidedefs (TEXTURE1 and TEXTURE2 merged, PNAMES rebuilt), its flats and the sprites of everything that can appear on it: the list is computed from the engine's state tables (`info.c`, `d_items.c`), with projectiles, dropped items and the player's weapons. Plus the graphics of the status bar, menu and intermission. No sound, music or demos.
   By default (`--lite`; `--full` turns it off) the game graphics are cut so that all of it fits in the RAM of a unit without Extension RAM and nothing is read from CD during play (every read is a seek, and that is exactly how the first version on hardware slowed down to several seconds per frame):
   - **wall textures:** the most used ones that fit a 64 KB budget are kept (`--tex-budget`); every other one becomes a kept texture of the same height with the closest average colour;
   - **flats:** the 6 most used are kept (`--flats`), without animation. A kept animation frame gets a new name (e.g. CFLAT), because the engine would then also require the last frame;
   - **sky:** a vertical gradient 8 pixels wide, built from the average colours of the original sky's rows;
   - **things on the map:** zombies and imps (the other monsters are replaced by them), the shotgun, ammo, medikits and keys. No decorations, barrels, armour, bonuses or heavy weapons;
   - **sprites:** only the front view instead of 8 rotations, and only the frames used by the states. No gibbing deaths (patched in `P_KillMobj`) and no player sprite.

   Result for E1M1: about 219 KB of graphics instead of about 2 MB. The `memory` line in the log also shows the number of CD reads since the previous line; during play it should be 0.

The engine patches (`third_party/doomgeneric`) are marked `CARMINAT`:
- the zone made of blocks from the loader (`Z_Init` joins them into one list; a used fence block sits between regions, so freeing does not merge blocks that are not adjacent);
- the 320×200 screen buffer in bss instead of in the zone (a zone of small blocks may not have 64 KB in one piece);
- colours in `R_InitColormaps`, `I_SetPalette`, `V_DrawPatch*`, the automap and `R_FillBackScreen`;
- missing switch textures are skipped;
- no gibbing deaths (the lite WAD lacks those frames);
- a counter of lump reads from the disc (`W_ReadLump`);
- `.csf` counts as a WAD;
- no music;
- no wipe effect (melt);
- waiting for a button before the game starts (`D_DoomLoop`);
- `FixedMul`/`FixedDiv` with the 68030's `muls.l`/`divs.l`, inline;
- `R_DrawColumnLow` in assembly (`src/r_draw68k.S`);
- a fast `memcpy` (`src/fastmem.S`).

Compiled with `-msoft-float`, because the 68EC030 has no FPU. The Makefile rejects an image with FPU instructions.

## Start-up and the on-screen log

The whole start-up is visible on the screen, without a UART cable (`src/scrlog.c`: 5×7 font, 64 columns, 28 lines, scrolling from its own copy of the text):
- the loader prints every step: screen buffer, zone, opening the image, address, relocations, `/nav_bus`. An error is shown in red and the program stops there;
- Doom redirects everything it writes to the console (`W_Init`, `R_Init`…) to the screen, and `stderr` (e.g. `I_Error`) always, also during play.

At READY and every 30 s of play a `memory ...` line goes to UART A: the zone (static data, cache, free), heap use and the deepest stack use (the loader fills the stack with a pattern). For E1M1: static about 455K, heap 50K.

After the level loads, a green **READY – PRESS ANY BUTTON** appears. The game (clock, screen) only starts after any button or a turn of the knob. If something gets stuck, the last line on the screen shows where. Everything also goes to UART A.

## Controls

The panel only sends presses (no releases), so movement latches.

| Button | In the game | In the menu |
|---|---|---|
| VOL+ | forward: press to walk, press to stop | up |
| VOL− | backward, latched as above | down |
| Knob ←/→ | turn, about 4° per step (with strafe: a step sideways) | up/down |
| Knob push | fire | Enter |
| Last message | use (doors, switches, respawn) | |
| Address book | next weapon | |
| Mute nav | strafe: latched | |
| Stand by | menu (Esc) | |

Defaults: low detail, view `screenblocks 8`, always run. Everything can be changed in the menu.

## Performance (emulator)

| Step | ms per frame |
|---|---|
| C, full screen | ~1100 |
| low detail, smaller view | ~505 |
| 68030 `FixedMul`/`FixedDiv`, `memcpy` | ~390–450 |
| `R_DrawColumnLow` in asm | ~350–400 |

Profile: a Lua script samples the PC every emulated frame, and the samples are mapped to symbols from `build/doom.elf`. Next in line:
- `R_RenderSegLoop` (11%);
- copying to video RAM (6%): copy only the view, the status bar only when it changes;
- `V_DrawPatch` (5%);
- `R_DrawSpanLow` in asm;
- 14 ready-made colormaps instead of recomputing on a flash.

## Licenses

- doomgeneric: GPL-2 (`third_party/doomgeneric/LICENSE`).
- Freedoom: BSD (`build/dl/COPYING.txt`).
- The disc is not published, because it contains OS-9 and Philips / Renault software. The sources are published; users build the disc from their own NAV_SW image.
