# carin6000-emu

A MAME-based emulator of the Philips CARiN navigation system (Renault Carminat, Mk2): a 68EC030 running OS-9, with video and CD drive from the CD-i family (MCD212, CDIC).

Status: installing the software from CD into flash works, and booting from flash starts the whole MMI application without a power down (ignition and the display on the nav bus are emulated as fixed values). The video screen works (the start screen with the warning and the OK button); input from the remote control / car is still missing (details in [docs/carin_testing.md](docs/carin_testing.md), section "Where we are").

## License

Released under the "DO WHAT THE FUCK YOU WANT TO" license.
In other words: do what you want, it's just AI slop.

## Repository contents

| Directory | What is inside |
|---|---|
| `mame/` | MAME source tree trimmed to one driver: `src/mame/philips/carin.cpp` (+ `carin.h`, `carin_trace.h`) and the devices it uses. Based on upstream MAME, commit `b1f71f8f`. |
| `roms/carin/` | `bootrom_0209.bin` (bootrom 2.21, hardware 0209) and `nv.img` (NV memory seed). |
| `roms/carin0109/` | `bootrom_0109.bin` (bootrom 1.21 from the NAV_SW disc, `Mk2IC/0109`) and `nv.img` (NV seed with the identifier `Mk2IC0109`). |
| `cd/` | Disc images, not in the repository (`.gitignore`): the `carin_nav_sw` software and maps, e.g. `carin_maps_pl_2012_2013` (`.chd` or `.cue` + `.img`). Described in [cd/README.md](cd/README.md). |
| `tools/` | `carin.py` (build and run) and analysis tools. |
| `navdb/` | Maps: a decoder of the original map database to GeoPackage (QGIS) and an OpenStreetMap encoder → your own map disc. Described in [navdb/README.md](navdb/README.md), format in [navdb/docs/format.md](navdb/docs/format.md). |
| `cfw/` | Custom firmware discs: [`cfw/poc`](cfw/poc/README.md) (hello world, buttons, π, RAM / video benchmark for real hardware) and [`cfw/carminat_doom`](cfw/carminat_doom/README.md) (a Doom port, work in progress). Binaries (`build/`, modules, images, WADs) are outside git. |
| `docs/` | Reverse engineering notes. |
| `state/` | Machine states (NV + flash). Ignored by git. |
| `logs/` | The build log and the logs of each run. Ignored by git. |
| `temp/` | Scratch space: extracted files, Ghidra projects etc. Ignored by git. |

## Requirements

- a C++ compiler (GCC or Clang), `make`, Python 3.9+
- MAME's Linux development libraries: SDL2, SDL2_ttf, fontconfig, ALSA/PulseAudio, Qt 6 (debugger) and X11
  - Arch: `pacman -S base-devel sdl2 sdl2_ttf fontconfig libpulse alsa-lib qt6-base libxinerama`
  - Debian/Ubuntu: `apt install build-essential libsdl2-dev libsdl2-ttf-dev libfontconfig-dev libpulse-dev libasound2-dev qt6-base-dev libxinerama-dev`
- `chdman` (package `mame-tools` or `mame`) to make CHD images

## Quick start

```bash
# 1. Build (the first time takes several to a dozen or so minutes, depending on the number of cores)
tools/carin.py build

# 2. Disc: put carin_nav_sw.chd into cd/, or carin_nav_sw.cue + .img and make a CHD from them:
tools/carin.py chd                # any other one: tools/carin.py chd NAME

# 3. First run: installation from CD into flash (about 150 s of emulated time, a few seconds
#    with the default -nothrottle; the console shows "il: Release loaded correctly",
#    then close MAME)
tools/carin.py gui --seed --state installed

# 4. Later runs: start from the installed software
tools/carin.py gui --state installed
```

The installation can also run without a window, in a few seconds: `tools/carin.py run 200 --seed --state installed`.

All options: `tools/carin.py --help` and `tools/carin.py run --help` / `gui --help`. The script does not read environment variables.

## Disc in the drive

Installing and changing the language need the software disc; driving needs a map disc. The disc is chosen on every start (`run` and `gui`):

| Option | Effect |
|---|---|
| (none) | empty drive; with `--seed` the disc `cd/carin_nav_sw` (installation) |
| `--cd NAME` | `cd/NAME.chd` or `cd/NAME.cue`, e.g. `--cd carin_maps_pl_2012_2013` |
| `--cd PATH` | any image (`.chd`, `.cue`, `.iso`…) |
| `--no-cd` | empty drive |

```bash
tools/carin.py gui --state installed --cd carin_maps_pl_2012_2013   # navigation with maps
tools/carin.py gui --state installed --cd ~/images/other_disc.cue
```

As in the car: with the software installed, the unit boots from flash even with a disc in the drive, and the software itself decides whether to start from the disc. The running system recognises the software disc (NAV_SW, language change): it sets the sw-load flag in NV and powers off after the "Attention!" screen is closed. When the master is done and keeps asking to be switched off (MCASIC C0000F bit 7), the slave restarts it (the emulator then resets the master side), and the bootrom sees the flag and loads the installer from the disc. At the end IL ejects the disc and asks for OK, then another restart and a boot from flash.

Note: with flash installed, the bootrom currently always boots from flash, even with the `NAV_SW` disc in the drive. On real hardware the disc takes precedence, so this is still to be fixed.

### Burning a real disc

Write the `.cue` file with `cdrdao` (the image is one MODE2/2352 track, so plain ISO burning will not work), from the `cd/` directory. `cdrdao` looks for the `.img` named in the `.cue` relative to the current directory:

```bash
sudo pacman -S cdrdao
cd cd
cdrdao write --device /dev/sr0 NAME.cue
```

Only have a CHD? First `chdman extractcd -i NAME.chd -o NAME.cue -ob NAME.img`. Use a blank disc: a failed write ruins a CD-R.

## Machine state: seed or your own seed

A state is the files in `state/<name>/`: `nv` (8 KB NV), `flash0..3` (main flash), `bootflash` and `bootflash2` (the two 1 MB boot flash chips: bootrom, voice / language data, the slave's flash) and `mk48t08`. States installed before `bootflash2` was added have incomplete language data and must be installed again (`--seed` or the NAV_SW disc). The default name is `default`; a path can be given instead of a name. MAME works directly on that directory, so every run continues the previous one.

**From the seed** (`--seed`): flash is empty, NV comes from `roms/carin/nv.img`. The bootrom finds no software in flash, so it loads the installer from CD and programs the flash (about 150 s of emulated time, a few seconds without a window).

```bash
tools/carin.py run 200 --seed                    # install into state/default
tools/carin.py run 200 --seed --state installed  # install into state/installed
```

**From your own seed** (`--load DIR`): the state is replaced with a copy of the files from that directory, e.g. a saved snapshot. The original stays untouched.

```bash
tools/carin.py run 60 --save-to ~/carin_snapshots/after_install --state installed   # make a snapshot
tools/carin.py gui --load ~/carin_snapshots/after_install --state test              # start from it
```

**Without flags** the state is continued; if the directory is empty, the machine starts as from the seed.

**Hardware variant** (`--hw 0209` or `--hw 0109`, default 0209). The NAV_SW disc holds software for two variants, `Mk2IC/0209` and `Mk2IC/0109`, with their own `loader.ini` (installer) and `slave.apl`; the application is shared. The variant follows from the factory identifier in NV (the `phil_id` block: `Mk2IC0209` or `Mk2IC0109`): the bootrom and IL build the path on the disc from it. For 0109 the emulator runs the MAME system `carin0109` with bootrom 1.21 and the NV seed from `roms/carin0109/`. A state remembers its variant in `state/<name>/hw`, so `--hw` is only needed on the first run:

```bash
tools/carin.py run 300 --seed --hw 0109 --state hw0109   # install on 0109 hardware
tools/carin.py gui --state hw0109 --cd carin_maps_pl_2012_2013
```

| Option | Effect |
|---|---|
| `--state NAME\|PATH` | which state (default `state/default`) |
| `--seed` | reset the state: empty flash, NV from `nv.img` |
| `--load DIR` | load the state from a directory (your own seed) |
| `--save-to DIR` | copy the state to a directory when done |
| `--no-ext-ram` | without the 2 MB Extension RAM at 0xA00000 (`-ram 2m`), like the real 0209 unit; map discs need it |

## Without a window (headless)

```bash
tools/carin.py run            # 30 s of emulation
tools/carin.py run 90         # 90 s
tools/carin.py run 90 -b      # rebuild first
```

Emulation runs as fast as possible (`--realtime` slows it to real time), without picture or sound. At the end the script prints a report (~80 lines): events, counters, where the CPU is, the tail of the OS-9 console and of the trace channels.

## With a window (GUI)

```bash
tools/carin.py gui --state installed
tools/carin.py gui --state installed --debug     # with the MAME debugger
tools/carin.py gui --state installed --realtime  # at the real unit's speed
tools/carin.py gui --state installed --speed 2   # twice the real speed (any factor 0.01-100)
tools/carin.py gui -- -resolution 1320x1248      # extra MAME options after "--"
```

One window opens (layout `mame/src/mame/layout/carin.lay`): the navigation screen at the top, next to it a panel with buttons to click with the mouse (PANEL: buttons and the `<` PUSH `>` knob; SERVICE: self-test and unused codes; CAR: room for a car emulator), and the OS-9 console (UART A) below. UART B only goes to `uart_b.txt`. Other views (navigation only, navigation with panel, console only) are in the MAME menu (Tab → Video Options).

Ignition: the IGNITION button in the CAR section of the panel or the **I** key (toggle). After switching it off, the system saves its settings to NV after about 25 s and powers down, and the slave cuts the power (black screen). Switching the ignition on again starts the unit. This is how to force saving the settings before closing MAME.

Keyboard: 1 Mute nav, 2 Last message, 3 VOL+, 4 VOL−, 5 knob push, 7 Stand by, 8 Address book, ←/→ knob; 6 and 9 start the diagnostic self-test; Q/T/E/R are codes the software does not handle. Names and keys can be changed in MAME (Tab → Input). By default emulation runs as fast as possible (`-nothrottle`); `--realtime` slows it to the real unit's speed, `--speed X` runs it at X times that. The MAME menu (Tab) always works; `gui` starts MAME with `-ui_active`. A disc is inserted while running through Tab → File Manager → cdrom (eject: "[empty slot]").

### Car simulator

`gui` shows the car simulator to the right of the unit, in the same window (view `Navigation, panel, console and car`, drawn by the plugin `mame/plugins/carsim`). The driver simulates the car behind the slave: every second the slave reports to `dp` what a real one would, i.e. the dead reckoning record (h_itc B2: distance, heading change, speed, time, position and its error, status) and the GPS receiver (B3). The simulator shows the car on OpenStreetMap tiles (green arrow with a GPS fix, red without one), its trail, a scale bar, its position, speed, heading and odometer.

- Drive with **W/S** (speed up/down; the speed holds when you let go, like cruise control; S below 0 reverses), **A/D** (steer; only while moving) and **Z** (stop).
- Tab → Plugin Options → **Car simulator**: type the coordinates (`52.2297, 21.0122`, `52.2297N 21.0122E`, Backspace and Del edit), then "Move the car there". The same menu sets the speed and heading (←/→), covers the GPS antenna, sets the zoom, turns the tiles on or off and clears the trail.
- `--car-at LAT,LON` moves the car there at start; `--no-tiles` drops the map tiles; `--no-car` runs without the simulator.
- Tiles come from tile.openstreetmap.org (curl in the background, two at a time) and are cached in `temp/osm_tiles/`. A tile older than 30 days is fetched again. At start `carin.py` trims the cache to 1 GB, dropping the tiles unused for the longest time.

When the car is more than 500 m from where the slave last reported it, or from where `dp` thinks it is (stored position at start, manual relocation), the slave flags a position jump, and CARiN moves over at once, even standing still. Smaller differences are corrected while driving with a GPS fix, once CARiN trusts the GPS (about 30 s). Field units and the meaning of the status bits come from analysis of `dp` (static, then checked at run time with breakpoints); see the comment at `slave_dr_tick` in `carin.cpp`. The system diagnosis ("Read I/O state", tacho pulses) asks the slave on a separate channel (h_itc 0x8A), which the HLE does not answer yet.

## Custom discs (cfw)

`cfw/` holds two separate discs with custom firmware. Each is a copy of the NAV_SW disc on which `sysgo` starts our program instead of the installer UI (`ui_handler`), and the installer `il` is replaced by a stub that only sleeps. Flash stays untouched, and the same disc works on both hardware variants (0109 and 0209).

| Disc | Project | What it does |
|---|---|---|
| `cd/carin_poc` | [`cfw/poc`](cfw/poc/README.md) | HELLO WORLD, a counter driven by the buttons, digits of π. A benchmark for real hardware in the title bar: free RAM, copying a frame to video memory, drawing columns. |
| `cd/carminat_doom` | [`cfw/carminat_doom`](cfw/carminat_doom/README.md) | Doom (doomgeneric) with Freedoom E1M1, controlled by the panel with latching. |

**Requirements:** `m68k-elf-gcc`, `m68k-elf-newlib` and `m68k-elf-binutils` (Arch: AUR), `python3`, `chdman` (package `mame-tools`), `curl` and `unzip` (Doom downloads Freedoom itself), and the image `cd/carin_nav_sw.img` + `.cue`.

**Build:**

```bash
make -C cfw            # both discs
make -C cfw poc        # only cd/carin_poc.{img,cue,chd}
make -C cfw doom       # only cd/carminat_doom.{img,cue,chd}
make -C cfw clean
```

**Testing in the emulator.** With empty flash (`--seed`) the bootrom starts from the disc straight away. With an installed state the disc acts like an update: close the "Attention!" screen, the unit restarts and boots from the disc.

```bash
tools/carin.py gui --state poc  --seed --cd cd/carin_poc.cue
tools/carin.py gui --state doom --seed --cd cd/carminat_doom.cue
tools/carin.py gui --state poc0109 --load state/hw0109 --cd cd/carin_poc.cue   # as an update, 0109 hardware
```

**Burning** a CD-R, from the `cd/` directory (details in "Burning a real disc"):

```bash
cd cd && cdrdao write --device /dev/sr0 carin_poc.cue
cd cd && cdrdao write --device /dev/sr0 carminat_doom.cue
```

On real hardware, burn the PoC first and read the benchmark from the title bar. Disc images are not published because they contain OS-9 and Philips / Renault software. Everyone builds them from their own NAV_SW image.

## Maps from OpenStreetMap (navdb)

Your own map disc (one country) is made from OSM data, which the encoder downloads from Geofabrik itself:

```bash
python3 navdb/encoder.py poland               # roads, routing, addresses, POI, background -> cd/carin_poland.img/.cue
python3 navdb/encoder.py exyugoslavia         # 8 countries (si hr ba me rs xk mk al), one disc
tools/carin.py gui --state installed --cd carin_poland
```

Regions, options, limits and verification: [navdb/README.md](navdb/README.md).

## Logs

Every run gets its own directory `logs/<date>_<time>_<run|gui>_<state>/`, and `logs/latest` points to the last one:

- `uart_a.txt`, `uart_b.txt`: the OS-9 consoles (DUART channel A/B)
- `report.txt`: the same report as after `run`
- `mame.log`: MAME output
- `trace/`: `events.log` (read this first), `summary.txt` and the channels `ipc`, `mailbox`, `mcasic`, `arcnet`, `duart`, `nv`, `irq`, `cdrom`, `video`

Options: `--trace off`, `--trace ipc,nv` (selected channels only), `--trace-cap BYTES`. A report for an old directory: `tools/carin.py report logs/<dir>`. The build log: `logs/build.log`.

The log directory of a GUI session is suitable for sending as feedback.

## Probe (state dump, bus watch)

```bash
tools/carin.py run 13 --state installed --probe-at 12.3 --probe-mem 9F8800:64 --probe-wtap 9F8800-9F88FF
```

The result goes to `trace/probe.log` in the log directory. Other options: `--probe-rtap` (reads), `--probe-bp "address:expressions;..."`, `--probe-exit`, `--probe-regs` and `--probe-stack`.

## Tools

| Script | Purpose |
|---|---|
| `tools/carin.py` | build, run, gui, chd [NAME], report |
| `tools/extract_cd.py [image] [dir]` | extracts the files of a disc (by default to `temp/extracted_cd/`); the report uses `loader.ini` from there to name modules |
| `tools/carin_flash_modules.py state/installed [dir]` | lists the OS-9 modules in flash, optionally extracts them to a directory |
| `tools/unpack_os9.py file dir` | extracts OS-9 modules from any file (e.g. `loader.ini`) |
| `tools/ghidra/export_os9_modules.py [modules] [output]` | analyses modules in headless Ghidra and exports them to Markdown |
| `tools/carin_probe.lua` | the probe's Lua script, run by `carin.py run --probe-*` |

## Working on the driver

The driver code is in `mame/src/mame/philips/carin.cpp`. After changes, `tools/carin.py build` or `run -b` is enough. The MAME tree only contains the files needed to build this driver, so adding a device outside the current set means bringing in its sources from upstream (the same commit `b1f71f8f`).

## Legal notes

The bootrom, the NV image and the disc software come from a 1990s device that its manufacturer stopped supporting long ago. We treat them as abandonware of purely hobby interest. MAME is licensed under GPL-2.0+ (the files in `mame/` keep their license headers, see `mame/COPYING`).
