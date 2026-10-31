#!/usr/bin/env python3
"""Build and run the ST10F269 test suites on the st10test machine.

Each suite is generated as Keil C166 assembler source (tools/st10/*.py), then
built with the real evaluation toolchain under Wine:

    A166.EXE  <suite>.A66 -> <suite>.OBJ      (assembler)
    L166.EXE  <suite>.OBJ -> <suite>.OUT      (linker, prints code size)
    OH166.EXE <suite>.OUT -> <suite>.H86      (Intel HEX)

The toolchain (C166 Evaluation Tools) limits each program to 4 Kbytes of
object code, which is why the test is split into several suites. Each suite
is linked on its own and runs in its own MAME session.

Results come back on ASC0 as "ST10TEST <SUITE> done pass=XXXX fail=YYYY".
"""

import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

MAME = ROOT / "mame" / "mame"
OUT = ROOT / "logs" / "st10"
ASM = OUT / "asm"
C166 = pathlib.Path.home() / "c166" / "bin"
WINE = shutil.which("wine") or "/opt/local/bin/wine"

IMAGE_SIZE = 0x50000
GAP = (0x8000, 0x18000)   # not flash; leave zero


def tool(exe, *args):
    """Run one Keil tool under Wine in the assembly directory."""
    cmd = [WINE, str(C166 / exe), *args]
    proc = subprocess.run(cmd, cwd=ASM, capture_output=True, text=True,
                          errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


def assemble(name, text):
    """A166 -> L166 -> OH166. Returns (code_bytes, hex_path)."""
    ASM.mkdir(parents=True, exist_ok=True)
    src = ASM / f"{name}.A66"
    src.write_text(text)
    for ext in (".OBJ", ".OUT", ".H86", ".LST", ".obj", ".out", ".H86"):
        (ASM / f"{name}{ext}").unlink(missing_ok=True)

    rc, out = tool("A166.EXE", src.name, "DEBUG", f"PRINT({name}.LST)",
                   f"OBJECT({name}.OBJ)", f"INCDIR({ASM})")
    lst = (ASM / f"{name}.LST").read_text(errors="replace") if (ASM / f"{name}.LST").exists() else ""
    # A166 exits 1 when it prints a warning (the RETS in a near procedure), so
    # the error count is the test, not the exit code.
    m = re.search(r"(\d+) ERROR\(S\)", out + lst)
    if not m or m.group(1) != "0" or not (ASM / f"{name}.OBJ").exists():
        raise SystemExit(f"A166 failed for {name}:\n{out}")

    rc, out = tool("L166.EXE", f"{name}.OBJ", "TO", f"{name}.OUT")
    # L166 exits non-zero on FATAL errors, including the 4 Kbyte code limit.
    if rc != 0 or "FATAL" in out:
        raise SystemExit(f"L166 failed for {name} (exit {rc}):\n{out}")
    m = re.search(r"code=(\d+)", out)
    code = int(m.group(1)) if m else -1

    rc, out = tool("OH166.EXE", f"{name}.OUT")
    hexp = ASM / f"{name}.H86"
    if rc != 0 or not hexp.exists():
        raise SystemExit(f"OH166 failed for {name}:\n{out}")
    return code, hexp


def read_hex(path):
    """Intel HEX -> dict of address -> byte."""
    data = {}
    base = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line.startswith(":"):
            continue
        raw = bytes.fromhex(line[1:])
        length, addr, kind = raw[0], (raw[1] << 8) | raw[2], raw[3]
        payload = raw[4:4 + length]
        if kind == 0x00:
            for i, b in enumerate(payload):
                data[base + addr + i] = b
        elif kind == 0x02:
            base = ((payload[0] << 8) | payload[1]) << 4
        elif kind == 0x04:
            base = ((payload[0] << 8) | payload[1]) << 16
        elif kind == 0x01:
            break
    return data


def to_image(hexp):
    image = bytearray(b"\xff" * IMAGE_SIZE)
    for addr, b in read_hex(hexp).items():
        image[addr] = b
    for i in range(*GAP):
        image[i] = 0
    return image


def run(image_name, env, seconds, needles):
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("mame.log", "error.log"):
        (OUT / name).unlink(missing_ok=True)
    full = dict(os.environ)
    full["SDL_VIDEO_DRIVER"] = "dummy"
    full["SDL_AUDIODRIVER"] = "dummy"
    full.update(env)
    cmd = [
        str(MAME), "st10test",
        "-rompath", str(ROOT / "roms"),
        "-hashpath", str(ROOT / "mame" / "hash"),
        "-cfg_directory", str(ROOT / "state" / "_mame_cfg"),
        "-nvram_directory", str(OUT / "nvram"),
        "-skip_gameinfo", "-video", "none", "-sound", "none",
        "-nothrottle", "-log", "-seconds_to_run", str(seconds),
    ]
    with open(OUT / "mame.log", "w") as out:
        proc = subprocess.run(cmd, cwd=OUT, env=full, stdout=out, stderr=subprocess.STDOUT)
    log = ""
    for name in ("error.log", "mame.log"):
        path = OUT / name
        if path.exists():
            log += path.read_text(errors="replace")
    missing = [n for n in needles if n not in log]
    print(f"--- {image_name} exit {proc.returncode} ---")
    for line in log.splitlines():
        if "ASC0" in line or "bootstrap" in line or "watchdog" in line or line.startswith("F"):
            print(line)
    if missing:
        print("missing:", ", ".join(missing))
        print("\n".join(log.splitlines()[-30:]))
        return False
    return proc.returncode == 0


def suites():
    from st10 import alu, core, cpu, mac, periph
    return [alu, core, cpu, mac, periph]


def main():
    from st10 import wdt, boot
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    for mod in suites():
        suite = mod.build()
        name = suite.name
        text = suite.emit()
        code, hexp = assemble(name, text)
        print(f"{name}: object code {code} bytes (limit 4096)")
        if code > 4096:
            raise SystemExit(f"{name} is {code} bytes, over the 4 Kbyte limit")
        image = to_image(hexp)
        (OUT / f"{name.lower()}.bin").write_bytes(image)
        ok = run(name, {"ST10_TEST": str(OUT / f"{name.lower()}.bin")}, 3,
                 [f"ST10TEST {name} done pass=", " fail=0000"]) and ok

    for mod, label, needles in (
        (wdt, "wdt", ["ST10 ASC0: WDT", "watchdog reset"]),
        (boot, "boot", ["ST10 ASC0: BOOT", "bootstrap jump"]),
    ):
        text = mod.build().emit()
        code, hexp = assemble(label, text)
        raw = read_hex(hexp)
        # The watchdog program is linked at 0. The bootstrap payload is
        # linked at FA40, which is where the loader copies and runs it.
        origin = 0 if label == "wdt" else 0xfa40
        length = 256 if label == "wdt" else 32
        image = bytearray(raw.get(origin + i, 0xff) for i in range(length))
        (OUT / f"{label}.bin").write_bytes(bytes(image))
        env = {"ST10_TEST": str(OUT / "wdt.bin")} if label == "wdt" else {"ST10_BOOT": str(OUT / "boot.bin")}
        ok = run(label, env, 2, needles) and ok

    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
