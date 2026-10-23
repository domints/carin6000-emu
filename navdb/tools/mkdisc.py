#!/usr/bin/env python3
"""Builds a NAV_DB map disc image (MODE2/2352, .img + .cue, optionally .chd) with our carindb.

The original map disc is the template: sectors 0-394 (system area, volume descriptors, path
tables, root directory, BIBLIOGR, COPYRIGH, ABSTRACT, CARINET) are kept, with ABSTRACT and
COPYRIGH replaced and the sizes updated; carindb starts at LBA 395 as on the original. BIBLIOGR
(CD id, db release, compatible software releases) stays unchanged, the device may check it.

usage: mkdisc.py [carindb] [-o cd/carin_osm.img] [--template cd/carin_maps_pl_2012_2013.img] [--chd]
"""
import argparse
import datetime
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cfw/poc/tools"))
import cdsector  # noqa: E402  (EDC / ECC of Mode 2 Form 1 sectors)

SECTOR, USER = 2352, 2048
DATA_LBA = 395                  # carindb on the original disc
SUBHEADER = bytes.fromhex("0000080000000800")

ABSTRACT = """This medium contains a digital road map database for the CARiN- and VDODayton navigation compatible systems.
The road network, addresses and places come from OpenStreetMap (https://www.openstreetmap.org),
converted with the carin6000-emu navdb encoder. Not for safety-relevant navigation.

Content              :{content}
Tool                 :5001
Date                 :{date}
CD number            :21435
Converted            :{when}
Converted on         :{host}
"""
COPYRIGHT = """COPYRIGHT

Map data (c) OpenStreetMap contributors, available under the Open Database License (ODbL 1.0),
https://www.openstreetmap.org/copyright.

Database format by Continental Automotive GmbH / Philips CARiN; this disc was written by the
carin6000-emu navdb encoder for hobby use with the user's own device.
"""


def conversion_info(path):
    """Conversion time and host from the database's info block (block 1), as the encoder wrote them."""
    with open(path, "rb") as f:
        f.seek(2048)
        text = f.read(2048).decode("latin1")
    get = lambda key: next((l.split(":", 1)[1].strip() for l in text.splitlines() if key in l), "?")
    return get("conversion date"), get("conversion by"), get("content:")


def bcd(v):
    return (v // 10) << 4 | v % 10


def raw_sector(lba, data):
    s = bytearray(SECTOR)
    s[0:12] = b"\x00" + b"\xff" * 10 + b"\x00"
    m, rest = divmod(lba + 150, 75 * 60)
    sec, frame = divmod(rest, 75)
    s[12:16] = bytes((bcd(m), bcd(sec), bcd(frame), 2))
    s[16:24] = SUBHEADER
    s[24:24 + USER] = data.ljust(USER, b"\0")
    cdsector.fix_mode2_form1(s)
    return s


def dir_entries(sector):
    p = 0
    while p < USER and sector[p]:
        yield p, sector[p:p + sector[p]]
        p += sector[p]


def build(carindb, output, template, chd=False, log=print):
    """Writes output (.img) and its .cue (and .chd with chd) for the database file carindb."""
    db = Path(carindb).read_bytes()
    output = Path(output)
    tpl = open(template, "rb")
    head = []
    for lba in range(DATA_LBA):
        tpl.seek(lba * SECTOR + 24)
        head.append(bytearray(tpl.read(USER)))
    total = DATA_LBA + -(-len(db) // USER)
    today = datetime.date.today()
    when, host, content = conversion_info(carindb)
    texts = {"ABSTRACT": ABSTRACT.format(date=today.isoformat(), when=when, host=host, content=content).encode("latin1"),
             "COPYRIGH": COPYRIGHT.encode("latin1")}

    pvd = head[16]
    root_lba, = struct.unpack_from("<I", pvd, 156 + 2)
    for p, rec in dir_entries(head[root_lba]):
        name = rec[33:33 + rec[32]].decode("latin1")
        lba, = struct.unpack_from("<I", rec, 2)
        size = None
        if name in texts:
            if len(texts[name]) > USER:
                sys.exit(f"{name} longer than one sector")
            head[lba][:] = texts[name].ljust(USER, b"\0")
            size = len(texts[name])
        elif name == "carindb":
            if lba != DATA_LBA:
                sys.exit("unexpected template layout")
            size = len(db)
        if size is not None:
            struct.pack_into("<I", head[root_lba], p + 10, size)
            struct.pack_into(">I", head[root_lba], p + 14, size)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S00").encode() + b"\x00"
    for d in (head[16], head[17]):               # both volume descriptors
        struct.pack_into("<I", d, 80, total)
        struct.pack_into(">I", d, 84, total)
        d[813:830] = stamp                        # creation and modification date
        d[830:847] = stamp

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as out:
        for lba, data in enumerate(head):
            out.write(raw_sector(lba, bytes(data)))
        for k in range(total - DATA_LBA):
            out.write(raw_sector(DATA_LBA + k, db[k * USER:(k + 1) * USER]))
    cue = output.with_suffix(".cue")
    cue.write_text(f'FILE "{output.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    log(f"disc: {output} ({total} sectors, {total * SECTOR / 1e6:.0f} MB) and {cue.name}")
    if total > 333000:
        log("warning: more than a 74-minute CD-R holds (333 000 sectors)")
    if chd:
        path = output.with_suffix(".chd")
        subprocess.run(["chdman", "createcd", "-f", "-i", str(cue), "-o", str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"disc: {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("carindb", nargs="?", type=Path, default=ROOT / "temp/navdb/warszawa/carindb")
    ap.add_argument("-o", "--output", type=Path, default=ROOT / "cd/carin_osm.img")
    ap.add_argument("--template", type=Path, default=ROOT / "cd/carin_maps_pl_2012_2013.img")
    ap.add_argument("--chd", action="store_true", help="also make a .chd for MAME (chdman)")
    args = ap.parse_args()
    for path in (args.carindb, args.template):
        if not path.is_file():
            ap.error(f"{path} not found")
    build(args.carindb, args.output, args.template, args.chd)


if __name__ == "__main__":
    main()
