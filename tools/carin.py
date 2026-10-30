#!/usr/bin/env python3
"""Build and run the CARiN emulator (MAME driver philips/carin.cpp).

  tools/carin.py build                 compile mame/ (only the CARiN driver)
  tools/carin.py run [options]         headless run, prints a report
  tools/carin.py gui [options]         windowed run in real time
  tools/carin.py chd [NAME]            make cd/NAME.chd from cd/NAME.cue (default: carin_nav_sw)
  tools/carin.py report <log dir>      reprint the report of an earlier run

Machine state (NV + flash) lives in state/<name>/ (default: state/default/). Every run gets its
own log directory logs/<date_time>_<mode>_<state>/, and logs/latest points at the last one.
See README.md for the typical flows.
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAME_DIR = ROOT / "mame"
MAME_BIN = MAME_DIR / "mame"
DRIVER_SOURCE = "src/mame/philips/carin.cpp"
ROM_DIR = ROOT / "roms"
CD_DIR = ROOT / "cd"
CD_NAME = "carin_nav_sw"
STATE_ROOT = ROOT / "state"
LOG_ROOT = ROOT / "logs"
MAME_CFG_DIR = STATE_ROOT / "_mame_cfg"
# OpenStreetMap tiles behind the car simulator (plugin carsim), at most 1 GB.
TILE_DIR = ROOT / "temp" / "osm_tiles"
TILE_CACHE_LIMIT = 1 << 30
# Hardware variant -> MAME system. The NAV_SW disc carries software for both (Mk2IC/0109, Mk2IC/0209);
# the variant is remembered in state/<name>/hw.
SYSTEMS = {"0209": "carin", "0109": "carin0109"}
DEFAULT_HW = "0209"

# Files MAME keeps per machine: nv (8 KB NV), flash0..3 (main flash), bootflash and bootflash2
# (the two boot flash chips: bootrom, voice data, slave flash) and mk48t08 (timekeeper). A missing file means "first boot": NV comes from roms/carin/nv.img,
# the boot flash from the bootrom, the main flash is erased.
STATE_FILES = ("nv", "flash0", "flash1", "flash2", "flash3", "bootflash", "bootflash2", "mk48t08")


def die(message):
    sys.exit(f"error: {message}")


# ---------------------------------------------------------------------------------------------
# state handling

def state_dir(name):
    """A bare name means state/<name>, anything with a slash is a path."""
    if "/" in name or name in (".", ".."):
        return Path(name).resolve()
    return STATE_ROOT / name


def seed_state(directory):
    """Forget the machine state: empty flash, NV from the seed image roms/carin/nv.img."""
    for f in STATE_FILES:
        (directory / f).unlink(missing_ok=True)


def copy_state(src, dst):
    src = Path(src)
    for system in SYSTEMS.values():   # also accept a MAME nvram directory
        if (src / system).is_dir():
            src = src / system
            break
    found = [f for f in STATE_FILES if (src / f).is_file()]
    if not found:
        die(f"{src} holds no state files ({', '.join(STATE_FILES)})")
    dst.mkdir(parents=True, exist_ok=True)
    for f in found:
        shutil.copy2(src / f, dst / f)
    if (src / "hw").is_file():
        shutil.copy2(src / "hw", dst / "hw")
    return found


def state_hw(directory, wanted):
    """The hardware variant of a state: --hw, else what the state remembers, else 0209."""
    stored = (directory / "hw").read_text().strip() if (directory / "hw").is_file() else None
    if wanted and stored and wanted != stored and any((directory / f).exists() for f in STATE_FILES):
        print(f"warning: state {directory.name} was made on hardware {stored}, running it as {wanted}")
    hw = wanted or stored or DEFAULT_HW
    (directory / "hw").write_text(hw + "\n")
    return hw


def prepare_state(args):
    directory = state_dir(args.state)
    directory.mkdir(parents=True, exist_ok=True)
    if args.seed:
        seed_state(directory)
        print(f"state {directory}: seeded (empty flash, NV from roms/carin/nv.img)")
    elif args.load:
        seed_state(directory)
        found = copy_state(args.load, directory)
        print(f"state {directory}: loaded {', '.join(found)} from {args.load}")
    elif not any((directory / f).exists() for f in STATE_FILES):
        print(f"state {directory}: empty, first boot from seed")
    else:
        print(f"state {directory}: continuing")
    args.system = SYSTEMS[state_hw(directory, args.hw)]
    if args.system != SYSTEMS[DEFAULT_HW]:
        print(f"hardware: {args.system}")
    return directory


# ---------------------------------------------------------------------------------------------
# build

def build(jobs):
    if shutil.which("make") is None:
        die("make not found")
    LOG_ROOT.mkdir(exist_ok=True)
    log = LOG_ROOT / "build.log"
    cmd = ["make", "-C", str(MAME_DIR), f"-j{jobs}", "SUBTARGET=mame", f"SOURCES={DRIVER_SOURCE}"]
    print(f"building MAME ({' '.join(cmd[3:])}), log: {log}")
    with open(log, "w") as out:
        result = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        errors = [l for l in log.read_text(errors="replace").splitlines() if "error" in l.lower()]
        print("\n".join(l[:200] for l in errors[:15]))
        die(f"build failed, see {log}")
    print(f"built {MAME_BIN}")


# ---------------------------------------------------------------------------------------------
# running

def cd_image(args):
    """The disc in the drive: --cd PATH, none with --no-cd; by default the nav software disc with --seed
    (the bootrom installs from it) and an empty drive otherwise: with the software disc in the drive
    the bootrom boots from CD and the installer reprograms the flash."""
    if getattr(args, "no_cd", False):
        return None
    if not getattr(args, "cd", None) and not getattr(args, "seed", False):
        return None
    if getattr(args, "cd", None):
        # A bare name means cd/NAME.chd or cd/NAME.cue; anything else is a path to an image.
        for candidate in (CD_DIR / f"{args.cd}.chd", CD_DIR / f"{args.cd}.cue"):
            if "/" not in args.cd and candidate.is_file():
                return candidate
        path = Path(args.cd).expanduser().resolve()
        if not path.is_file():
            die(f"CD image {args.cd} not found (neither cd/{args.cd}.chd/.cue nor a file)")
        return path
    chd = CD_DIR / f"{CD_NAME}.chd"
    if chd.exists():
        return chd
    cue = CD_DIR / f"{CD_NAME}.cue"
    if cue.exists():
        print(f"note: {chd.name} missing, using {cue.name} (tools/carin.py chd makes the CHD)")
        return cue
    die(f"no CD image in {CD_DIR} (expected {CD_NAME}.chd or {CD_NAME}.cue + .img)")


def new_log_dir(mode, state):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    directory = LOG_ROOT / f"{stamp}_{mode}_{state.name}"
    directory.mkdir(parents=True)
    latest = LOG_ROOT / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(directory.name)
    return directory


def mame_command(state, log_dir, cdrom, system):
    # MAME runs inside the log directory: the driver writes uart_a.txt, uart_b.txt and trace/ to
    # its working directory. The machine state is reached through nvram/<system> -> state/<name>.
    nvram = log_dir / "nvram"
    nvram.mkdir()
    (nvram / system).symlink_to(state)
    MAME_CFG_DIR.mkdir(parents=True, exist_ok=True)
    return [
        str(MAME_BIN), system,
        "-rompath", str(ROM_DIR),
        "-hashpath", str(MAME_DIR / "hash"),
        "-pluginspath", str(MAME_DIR / "plugins"),
        "-artpath", str(MAME_DIR / "artwork"),
        "-languagepath", str(MAME_DIR / "language"),
        "-cfg_directory", str(MAME_CFG_DIR),
        "-nvram_directory", str(nvram),
        "-snapshot_directory", str(log_dir / "snap"),
        "-skip_gameinfo",
    ] + (["-cdrom", str(cdrom)] if cdrom else [])


def ram_options(args):
    """--no-ext-ram: a unit without the 2 MB Extension RAM at 0xA00000 (the RAM slot set to 2m)."""
    return ["-ram", "2m"] if args.no_ext_ram else []


def speed_options(args):
    """Full speed by default; --realtime throttles to the real machine's speed, --speed X to X
    times that (MAME -speed)."""
    if args.speed is not None:
        if not 0.01 <= args.speed <= 100:
            sys.exit("--speed must be between 0.01 and 100")
        return ["-speed", f"{args.speed:g}"]
    return [] if args.realtime else ["-nothrottle"]


def trace_env(args):
    env = dict(os.environ)
    env.pop("CARIN_TRACE", None)
    env.pop("CARIN_TRACE_CAP", None)
    if args.trace:
        env["CARIN_TRACE"] = args.trace
    if args.trace_cap:
        env["CARIN_TRACE_CAP"] = str(args.trace_cap)
    return env


def probe_env(args, env):
    """The Lua probe is configured through PROBE_* variables; they come from the command line only."""
    for key in [k for k in env if k.startswith("PROBE_")]:
        del env[key]
    values = {
        "PROBE_AT": args.probe_at,
        "PROBE_MEM": args.probe_mem,
        "PROBE_WTAP": args.probe_wtap,
        "PROBE_RTAP": args.probe_rtap,
        "PROBE_BP": args.probe_bp,
        "PROBE_EXIT": "1" if args.probe_exit else None,
        "PROBE_REGS": "1" if args.probe_regs else None,
        "PROBE_STACK": "1" if args.probe_stack else None,
    }
    values = {k: str(v) for k, v in values.items() if v is not None}
    env.update(values)
    return bool(values)


def finish_run(state, args, log_dir, quiet=False):
    if args.save_to:
        found = copy_state(state, Path(args.save_to).resolve())
        print(f"state saved to {args.save_to} ({', '.join(found)})")
    run_summary(log_dir, quiet)
    print(f"logs: {log_dir}")


def run_summary(log_dir, quiet=False):
    cmd = [sys.executable, str(ROOT / "tools" / "carin_summary.py"), str(log_dir)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL if quiet else None)


def check_binary():
    if not MAME_BIN.exists():
        die(f"{MAME_BIN} not built yet, run: tools/carin.py build")


def cmd_run(args):
    if args.build:
        build(args.jobs)
    check_binary()
    state = prepare_state(args)
    log_dir = new_log_dir("run", state)
    cmd = mame_command(state, log_dir, cd_image(args), args.system)
    cmd += ["-seconds_to_run", str(args.seconds), "-video", "none", "-sound", "none"]
    cmd += ram_options(args) + speed_options(args)
    env = trace_env(args)
    if probe_env(args, env):
        cmd += ["-autoboot_script", str(ROOT / "tools" / "carin_probe.lua")]
        if args.probe_bp:
            cmd += ["-debug", "-debugger", "none"]
    cmd += args.mame_args
    print(f"running {args.seconds} s of emulation headless...")
    with open(log_dir / "mame.log", "w") as out:
        result = subprocess.run(cmd, cwd=log_dir, env=env, stdout=out, stderr=subprocess.STDOUT)
    print(f"mame exit={result.returncode}")
    finish_run(state, args, log_dir)
    probe = log_dir / "trace" / "probe.log"
    if probe.exists() and probe.stat().st_size:
        print("## probe.log (first 60 lines)")
        for line in probe.read_text(errors="replace").splitlines()[:60]:
            print(line[:200])


def trim_tile_cache():
    """The car window's OpenStreetMap tile cache (TILE_DIR, plugin carsim) stays under
    TILE_CACHE_LIMIT: the tiles not used for the longest time go first."""
    stats = [(p, p.stat()) for p in TILE_DIR.rglob("*.png")]
    files = [(max(s.st_atime, s.st_mtime), s.st_size, p) for p, s in stats]
    total = sum(size for _, size, _ in files)
    for _, size, path in sorted(files):
        if total <= TILE_CACHE_LIMIT:
            break
        path.unlink(missing_ok=True)
        total -= size


def cmd_gui(args):
    if args.build:
        build(args.jobs)
    check_binary()
    state = prepare_state(args)
    log_dir = new_log_dir("gui", state)
    # One window (layout carin.lay): navigation video, the clickable front panel, the OS-9 console
    # on terminal A and, on the right, the car simulator (plugin carsim, mame/plugins/carsim).
    # Port B only goes to uart_b.txt.
    cmd = mame_command(state, log_dir, cd_image(args), args.system)
    # -ui_active: the console has an emulated keyboard, which would otherwise take every key
    # (Tab included) until the UI toggle key (Scroll Lock) is pressed.
    cmd += ["-window", "-nomaximize", "-ui_active"]
    env = trace_env(args)
    for key in ("CARIN_CAR_AT", "CARIN_TILE_DIR", "CARIN_TILES"):
        env.pop(key, None)
    if args.no_car:
        cmd += ["-view", "Navigation, panel and console"]
    else:
        cmd += ["-view", "Navigation, panel, console and car", "-resolution", "1440x598", "-plugin", "carsim"]
        if args.car_at:
            env["CARIN_CAR_AT"] = args.car_at
        if args.no_tiles:
            env["CARIN_TILES"] = "0"
        else:
            TILE_DIR.mkdir(parents=True, exist_ok=True)
            env["CARIN_TILE_DIR"] = str(TILE_DIR)
            trim_tile_cache()
    cmd += ram_options(args) + speed_options(args)
    if args.debug:
        cmd += ["-debug"]
    cmd += args.mame_args
    with open(log_dir / "mame.log", "w") as out:
        proc = subprocess.Popen(cmd, cwd=log_dir, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in proc.stdout:
            sys.stdout.write(line)
            out.write(line)
        proc.wait()
    finish_run(state, args, log_dir, quiet=True)


def cmd_chd(args):
    chdman = shutil.which("chdman") or (str(MAME_DIR / "chdman") if (MAME_DIR / "chdman").exists() else None)
    if not chdman:
        die("chdman not found (package mame-tools, or: make -C mame TOOLS=1 ...)")
    cue = CD_DIR / f"{args.name}.cue"
    chd = CD_DIR / f"{args.name}.chd"
    if not cue.exists():
        die(f"{cue} missing")
    subprocess.run([chdman, "createcd", "-i", str(cue), "-o", str(chd), "--force"], check=True)


def cmd_report(args):
    run_summary(Path(args.log_dir).resolve())


# ---------------------------------------------------------------------------------------------

def add_state_options(p):
    g = p.add_argument_group("machine state")
    g.add_argument("--state", default="default", metavar="NAME",
                   help="state to use: state/NAME, or a path (default: %(default)s)")
    mode = g.add_mutually_exclusive_group()
    mode.add_argument("--seed", action="store_true",
                      help="start from the seed: empty flash, NV from roms/carin/nv.img (installs from CD)")
    mode.add_argument("--load", metavar="DIR",
                      help="replace the state with the snapshot in DIR (your own seed), then start")
    g.add_argument("--save-to", metavar="DIR", help="copy the state to DIR after the run")
    g.add_argument("--hw", choices=sorted(SYSTEMS), help="hardware variant (default: the state's, else 0209)")
    g.add_argument("--no-ext-ram", action="store_true",
                   help="no Extension RAM at 0xA00000 (2 MB less), like a real 0209 unit; maps need it")
    c = p.add_argument_group("disc").add_mutually_exclusive_group()
    c.add_argument("--cd", metavar="PATH",
                   help=f"disc in the drive: a name from cd/ (NAME.chd or NAME.cue) or a path to an image "
                        f"(default: {CD_NAME} with --seed, else empty)")
    c.add_argument("--no-cd", action="store_true", help="run with an empty drive (also with --seed)")
    t = p.add_argument_group("tracing")
    t.add_argument("--trace", metavar="CHANNELS",
                   help="'off', or a comma list of channels (ipc,mailbox,mcasic,arcnet,duart,nv,irq,cdrom,video)")
    t.add_argument("--trace-cap", type=int, metavar="BYTES", help="size cap of each trace file")
    s = p.add_mutually_exclusive_group()
    s.add_argument("--realtime", action="store_true",
                   help="run at the real machine's speed (default: as fast as possible, -nothrottle)")
    s.add_argument("--speed", type=float, metavar="X",
                   help="run at X times the real machine's speed, e.g. 2 or 0.5 (1 = --realtime)")
    p.add_argument("-b", "--build", action="store_true", help="build MAME first")
    p.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 2, help="build jobs")
    p.add_argument("mame_args", nargs="*", help="extra MAME options (after --)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="compile MAME with the CARiN driver")
    p.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 2)
    p.set_defaults(func=lambda a: build(a.jobs))

    p = sub.add_parser("run", help="headless run with a report")
    p.add_argument("seconds", nargs="?", type=float, default=30, help="emulated seconds (default: 30)")
    add_state_options(p)
    g = p.add_argument_group("probe (tools/carin_probe.lua)")
    g.add_argument("--probe-at", type=float, metavar="SEC", help="dump registers and memory at this time")
    g.add_argument("--probe-mem", metavar="ADDR:LEN,...", help="hex memory ranges dumped at --probe-at")
    g.add_argument("--probe-wtap", metavar="FROM-TO,...", help="log CPU writes to these ranges")
    g.add_argument("--probe-rtap", metavar="FROM-TO,...", help="log CPU reads from these ranges")
    g.add_argument("--probe-bp", metavar="ADDR:EXPR;...", help="breakpoints that log expressions")
    g.add_argument("--probe-exit", action="store_true", help="quit right after the --probe-at dump")
    g.add_argument("--probe-regs", action="store_true", help="dump registers at breakpoints")
    g.add_argument("--probe-stack", action="store_true", help="dump the stack at the first breakpoint hit")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("gui", help="windowed run in real time")
    add_state_options(p)
    p.add_argument("--debug", action="store_true", help="open the MAME debugger")
    p.add_argument("--no-car", action="store_true", help="no car simulator window")
    p.add_argument("--car-at", metavar="LAT,LON", help="move the simulated car here at start (degrees)")
    p.add_argument("--no-tiles", action="store_true", help="no OpenStreetMap tiles behind the car")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("chd", help="make cd/NAME.chd from cd/NAME.cue (+ .img)")
    p.add_argument("name", nargs="?", default=CD_NAME, help="disc name in cd/ (default: %(default)s)")
    p.set_defaults(func=cmd_chd)

    p = sub.add_parser("report", help="print the report of a log directory")
    p.add_argument("log_dir")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    args.func(args)


if __name__ == "__main__":
    main()
