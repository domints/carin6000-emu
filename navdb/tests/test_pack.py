#!/usr/bin/env python3
"""Round trip of the parcel compressor: unpack an original level 0 parcel (its RAM image), compress
it with libs/pack.py, unpack the result with the pbp port, compare (all but the block count of the
unit pointer). Also compares the compressed size with the original's.
usage: test_pack.py [carindb] [every-nth-parcel] (default: the original, every 40th)"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from libs.carindb import TEXT_TABLES, header_info, read_unit, table_directory, units
from libs.pack import Packer
from libs.unpack import Unpacker

ROOT = Path(__file__).resolve().parents[2]


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "temp/navdb/carindb"
    step = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    f = open(path, "rb")
    tables = table_directory(f)
    sizes, release = header_info(f)
    unpacker, packer = Unpacker(sizes, release, TEXT_TABLES), Packer(sizes, release, TEXT_TABLES)
    res, bad = Counter(), []
    ours = orig = raw = 0
    (_, _), (data, _), (end, _) = tables[1]
    for k, (b, length, head) in enumerate(units(f, data, end)):
        if k % step or not head[6] & 1:         # only compressed originals are RAM images of the format
            continue
        unit = read_unit(f, (b << 8) | length)
        d = bytes(unpacker.unpack(unit))
        c = packer.parcel(d)
        if c is None:
            res["not smaller"] += 1
            continue
        back = bytes(unpacker.unpack(c))
        same = back[:3] == d[:3] and back[4:] == d[4:]
        res["identical" if same else "DIFFERENT"] += 1
        ours += len(c) // 2048
        orig += length
        raw += len(d) // 2048
        if not same and len(bad) < 5:
            i = next(i for i in range(4, len(d)) if back[i] != d[i])
            bad.append(f"unit {b:#x}: first difference at {i:#x}")
    print(dict(res))
    print(f"blocks: unpacked {raw}, original stored {orig}, ours {ours} ({raw / max(ours, 1):.2f}x)")
    print("\n".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
