# CARiN: testing and running

All commands run from the repository root. Required in `emu/mame/roms/carin/`: `bootrom_0209.bin` and `nv.img`; disc: `images/52.chd`.

## 1. Building and testing without a window

```bash
tools/carin_run.sh -b 30   # -b = rebuild, 30 = seconds of emulation
tools/carin_run.sh 30      # without building
```

The script runs the emulator without graphics and prints a report (~80 lines, also in `emu/mame/report.txt`). The OS-9 consoles go to `emu/mame/uart_a.txt` and `uart_b.txt`.

## 2. First run = installation from CD

With empty flash the bootrom loads the installer from CD (`loader.ini`), and `il` programs the flash (about 150 s of emulation). Save the result and boot from flash from then on:

```bash
CARIN_STATE_SAVE=nvram/carin_installed tools/carin_run.sh 200   # installation, save the state
CARIN_STATE=nvram/carin_installed tools/carin_run.sh 60         # start from the installed software
```

A ready copy after installation is in `nvram/carin_installed/`.

## 3. Machine state (NV and flash)

The emulator keeps in `emu/mame/nvram/carin/`: `nv` (8 KB NV), `flash0..3` (main flash at 0x1200000) and `bootflash` (bootrom + the slave's flash). `carin_run.sh` starts from scratch by default (nv.img, empty flash), `carin_gui.sh` continues the previous state. Options of both scripts:

| Variable | Effect |
|---|---|
| `CARIN_STATE=<dir>` | start from a saved state (files `nv`, `flash0..3`, `bootflash`) |
| `CARIN_STATE_SAVE=<dir>` | save the state after the run |
| `CARIN_NV=<file>` / `CARIN_NV_SAVE=<file>` | the same for NV only |
| `CARIN_FRESH=1` | start from scratch (nv.img, empty flash) |
| `CARIN_KEEP_NV=1`, `CARIN_KEEP_FLASH=1` | `carin_run.sh`: keep NV / flash from the previous run |

## 4. Running with a window (GUI)

```bash
CARIN_STATE=nvram/carin_installed tools/carin_gui.sh   # start from the installed software
tools/carin_gui.sh                                     # continue the last session
CARIN_FRESH=1 tools/carin_gui.sh                       # from scratch (installation from CD)
CARIN_DEBUG=1 tools/carin_gui.sh                       # with the MAME debugger
tools/carin_gui.sh -b                                  # rebuild first
```

Two windows open: the navigation video and the OS-9 console (terminal A). Emulation runs in real time. The machine state is kept between GUI sessions (unlike `carin_run.sh`). The state options are the same as in section 3. Extra MAME options can be appended at the end.

After MAME closes, the session logs (`uart_a.txt`, `uart_b.txt`, `report.txt`, `trace/`) are copied to `logs/gui/<date_time>/`. You can send that directory as feedback. If keys do not reach the console, toggle the keyboard with Scroll Lock.

Do not run the GUI and `carin_run.sh` at the same time: both use `emu/mame/nvram/carin/` and `emu/mame/trace/`.

## 5. Logs

Files in `emu/mame/trace/` (cleared on every script run):

- `summary.txt`: counters, PC samples, channel tails
- `events.log`: milestones (read this first)
- `ipc`, `mailbox`, `mcasic` (also I2C), `arcnet`, `duart`, `nv`, `irq`, `cdrom`, `video`: one channel each

Variables: `CARIN_TRACE=off` (disables), `CARIN_TRACE=ipc,nv` (selected channels only), `CARIN_TRACE_CAP=<bytes>` (file size limit).

## 6. Probe (state dump, bus watch)

```bash
PROBE_AT=12.3 PROBE_MEM=9F8800:64 PROBE_WTAP=9F8800-9F88FF tools/carin_run.sh 13
```

Result: `emu/mame/trace/probe.log`. `PROBE_RTAP` watches reads, `PROBE_EXIT=1` exits after the dump, `PROBE_BP="address:expressions;..."` sets breakpoints.

## 7. OS-9 modules from flash

```bash
python3 tools/carin_flash_modules.py nvram/carin_installed extracted/flash_0209
```

Lists the module addresses in the main flash and extracts them to a directory.

## 8. Where we are

Installation from CD works, and booting from flash starts the whole MMI application: every process reports ready (0x6E30), `mmi_root` broadcasts the start (0x6E2E) and there is no power down any more. The screen works: after about 100 s of emulation the start screen "Attention! … Highway code has priority." appears with the RENAULT / OK / PHILIPS buttons (screenshot: [first_screen.png](first_screen.png)).

The video chip is an SCC66470 (VSC), not the CD-i MCD212: 512 KB DRAM at 0x600000 (display program at 0x6003EC), registers at 0x7FFFE0, the pixel accelerator (IPA) window at 0x1600000. `videodr` sets up a 384×240 screen with 8 bits per pixel, and `ghandler` draws through the accelerator. The palette is a placeholder (RRRGGGBB), because it is not yet known where CARiN keeps its colour table. The next step is input: the remote control (`rc5`) and the car buttons, to get past the screen with "OK".

The car side is emulated with fixed values in `carin.cpp` (fields `m_car_*`, sections marked "Car side"), eventually to be controlled from a car emulator window:

- ignition (+12 V): byte 0x9FA008 in the slave's status block is 1, otherwise `syscondr` switches the system off after a countdown;
- the display on `nav_bus` (I2C 0x50): accepts every message from `recv_ibus`, raises the attention line (IRQ4, bit 2 in 0xC0001C) and acknowledges both slots (0x11) when the status is read from 0x51. Without this, `recv_ibus` hung on its write to `/nav_bus`, never reported ready, and `mmi_root` reset after 60 s because `build_screen` did not answer the watchdog (0x6E06).
