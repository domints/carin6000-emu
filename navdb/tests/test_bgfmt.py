#!/usr/bin/env python3
"""Round trip of the background unit layout: unpack every original background unit, read it into
RawBackground, write it again, compare byte for byte."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from libs import bgfmt
from libs.carindb import TEXT_TABLES, header_info, read_unit, table_directory, units
from libs.unpack import Unpacker

ROOT = Path(__file__).resolve().parents[2]


def main():
    f = open(ROOT / "temp/navdb/carindb", "rb")
    tables = table_directory(f)
    sizes, release = header_info(f)
    unpacker = Unpacker(sizes, release, TEXT_TABLES)
    result, bad = Counter(), []
    for tid in (6, 0x16, 0x15, 0x1C, 0x14, 0x1D):
        (_, _), (data, _), (end, _) = tables[tid]
        for b, length, head in units(f, data, end):
            d = bytes(unpacker.unpack(read_unit(f, (b << 8) | length)))
            out = bgfmt.write(bgfmt.read(d), len(d) // 2048)
            result[tid, out == d] += 1
            if out != d and len(bad) < 5:
                i = next(i for i in range(len(d)) if out[i] != d[i])
                bad.append(f"table {tid:x} unit {b:#x}: first difference at {i:#x}")
    for (tid, ok), n in sorted(result.items()):
        print(f"table {tid:x}: {n} {'identical' if ok else 'DIFFERENT'}")
    print("\n".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
