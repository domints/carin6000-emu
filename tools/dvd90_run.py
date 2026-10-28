#!/usr/bin/env python3
"""Headless, size-capped run of the opel_dvd90 driver.

  tools/dvd90_run.py [seconds] [extra mame args...]

No window (SDL dummy video driver), output streamed to logs/dvd90/, and MAME is
killed if a log grows past the cap or the wall-clock limit is reached.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "dvd90"
LOG_CAP = 2 * 1024 * 1024
WALL_LIMIT = 60


def main():
    seconds = sys.argv[1] if len(sys.argv) > 1 else "2"
    extra = sys.argv[2:]
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "trace").mkdir(exist_ok=True)
    for name in ("mame.log", "error.log"):
        (LOG / name).unlink(missing_ok=True)
    env = dict(os.environ, SDL_VIDEO_DRIVER="dummy", SDL_AUDIODRIVER="dummy")
    # Each run starts from a fresh copy of the built NAND image (tools/opel_nand.py).
    seed = ROOT / "state" / "opel_dvd90" / "nand.bin"
    if seed.exists():
        work = LOG / "nand.bin"
        shutil.copyfile(seed, work)
        env["OPEL_NAND"] = str(work)
    cmd = [
        str(ROOT / "mame" / "mame"), "opel_dvd90",
        "-rompath", str(ROOT / "roms"),
        "-hashpath", str(ROOT / "mame" / "hash"),
        "-cfg_directory", str(ROOT / "state" / "_mame_cfg"),
        "-nvram_directory", str(LOG / "nvram"),
        "-skip_gameinfo", "-video", "none", "-sound", "none",
        "-nothrottle", "-log", "-seconds_to_run", seconds,
    ]
    # Opened by the driver on the first READ, not by MAME at startup. The
    # image device parses the whole 4 GB file up front and that misses the
    # wall clock while the NAND image is still being copied.
    iso = ROOT / "cd" / "NAV_DB_21709.iso"
    if iso.exists():
        env["OPEL_CDROM"] = str(iso)
    cmd += extra
    with open(LOG / "mame.log", "w") as out:
        proc = subprocess.Popen(cmd, cwd=LOG, env=env, stdout=out, stderr=subprocess.STDOUT)
        start = time.time()
        reason = None
        while proc.poll() is None:
            if time.time() - start > WALL_LIMIT:
                reason = "wall clock limit"
            for name in ("mame.log", "error.log"):
                path = LOG / name
                if path.exists() and path.stat().st_size > LOG_CAP:
                    reason = f"{name} over {LOG_CAP // 1024} KB"
            if reason:
                proc.kill()
                break
            time.sleep(0.2)
        proc.wait()
    print(f"exit={proc.returncode}" + (f" killed: {reason}" if reason else ""))


if __name__ == "__main__":
    main()
