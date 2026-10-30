# PoC: a custom program from disc (flash untouched)

A copy of the NAV_SW disc on which `sysgo` starts our program instead of the installer UI (`ui_handler`). The installer `il` itself, the only module that programs the flash, is replaced by a stub that only sleeps (`src/il_stub.S`), so the flash cannot be touched even if the unit gets into a loading loop. The replacement is made in all four `loader.ini` files on the disc: both hardware variants (`Mk2IC/0109` and `Mk2IC/0209`), each in `RENAULT/` and `RENAULT/app_sw/`. So the same disc works on 0109 and 0209. The bootrom starts from the disc as for an update. The program:

- draws HELLO WORLD and a counter in the framebuffer set up by `videodr`;
- reads the buttons from `/nav_bus` (frames `3A 3B 48 code` and `3A 3B 49 steps`): VOL+ +1, VOL− −1, knob ±steps, knob push resets, Last message computes 700 digits of π (Rabinowitz–Wagon spigot, the digits appear as they are computed; the buttons wait in the queue meanwhile);
- logs everything to UART A (the OS-9 console);
- at start, measures whether Doom stands a chance and shows the result in the title bar (and in the log): `RAM` total free memory and `MAX` the largest block (map from `F$GBlkMp`, allocates nothing), `COPY` ms to copy a 320×200 frame from RAM to the screen buffer, `DRAW` ms for a textured 320×200 fill in columns (a loop like `R_DrawColumn`, in C). In the emulator: `RAM 3699K MAX 2048K COPY 60 DRAW 392 MS`. The numbers from a real unit will show how far off the emulator is.

## Building

Needs `m68k-elf-gcc` and `cd/carin_nav_sw.img`.

```bash
make -C cfw/poc      # cfw/poc/build/ui_handler.mod, cfw/poc/build/il.mod (stub), cd/carin_poc.img + .cue
make -C cfw/poc chd  # also cd/carin_poc.chd
```

How it works:

1. `src/start.S`: the process entry point and the system call wrappers (`trap #0`).
2. `src/main.c`: the program. The code is PC-relative only and has no global variables (an OS-9 module is read-only); all state lives on the stack. The Makefile rejects `.data`/`.bss` and absolute relocations.
3. `src/il_stub.S`: the `il` stub, `F$Sleep` in a loop.
4. `tools/mkmod.py`: binary → OS-9 module (header, parity, CRC-24, an empty idata/irefs block, because F$Fork always processes it). The module has exactly the original's length (`ui_handler` 31628 B, `il` 41004 B, the same in both variants), so `loader.ini` keeps its size and offsets.
5. `tools/mkdisc.py`: finds the modules by name (OS-9 header) in every `loader.ini` on the disc, replaces them and recomputes the EDC/ECC of the changed sectors (`tools/cdsector.py`, checked against original sectors). If it does not find exactly four copies or a size does not match, it stops.

## Testing in the emulator

```bash
tools/carin.py gui --state poc --load state/installed --cd carin_poc          # 0209
tools/carin.py gui --state poc0109 --load state/hw0109 --cd carin_poc         # 0109
tools/carin.py gui --state poc_empty --seed --hw 0109 --cd carin_poc          # empty flash: straight from the disc
```

`--load` copies the state, so the original stays untouched. The PoC disc is a copy of NAV_SW, so it works like an update: insert it into a running navigation unit, close "Attention!", the software sets the sw-load flag and restarts, and the bootrom loads the PoC.

## On real hardware

Burning (MODE2/2352 image, raw):

```bash
cd cd && cdrdao write --device /dev/sr0 carin_poc.cue
```

Risks:

1. We do not know what makes the bootrom start from the disc in the car when the flash is valid. In the emulator it is a line from the I/O expander (a guess). First check with a copy of the original NAV_SW whether the unit boots from a CD-R at all.
2. `sysgo` from the disc starts `il_slave` on the slave (as in a normal update). Without commands from `il` (a stub here) it should not program anything, but this has not been checked in RE yet.
3. The palette is unknown, so the colours may differ from the emulator. The program uses the indexes the original software draws with (0x49 background, 0xFF text, 0x92 accent, 0x00).
4. Whether the intermediate module sends the buttons without the handshake with MMI (which does not run here) will only show in the car.

If the program does not start: take the disc out and reset (switch the ignition off), and the unit boots from flash.
