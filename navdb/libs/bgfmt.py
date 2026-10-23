"""Byte layout of a background unit (tables 6, 16, 15, 1c, 14, 1d; docs/format.md section 5) as pbp
leaves it unpacked in RAM, for writing: the 52-byte header (unit header, slot descriptors 0-5 at
8 + 4k, box at 0x20, word 0x30 = 1 (points are steps), byte 0x33 = step as a power of two), then
the slot regions back to back in order 0-5 without padding: 0 type groups + end record, 1 areas
+ end record, 2 roads + end record, 3 points, 4 (6-byte triples), 5 name table + names. A missing
slot has offset 0.
"""
import struct

from .carindb import BLOCK

HEADER = 0x34


class RawBackground:
    def __init__(self, header, counts, regions):
        self.header, self.counts, self.regions = bytearray(header), counts, regions


def read(d):
    w = lambda o: struct.unpack_from(">H", d, o)[0]
    offs = {k: w(8 + 4 * k) for k in range(6)}
    counts = {k: w(10 + 4 * k) for k in range(6)}
    placed = [k for k in range(6) if offs[k]]
    end = len(bytes(d).rstrip(b"\0"))
    regions = {}
    for k in range(6):
        if not offs[k]:
            regions[k] = None
            continue
        nxt = placed.index(k) + 1
        stop = offs[placed[nxt]] if nxt < len(placed) else end
        regions[k] = bytes(d[offs[k]:max(stop, offs[k])])
    return RawBackground(d[:HEADER], counts, regions)


def write(b, blocks=None):
    out = bytearray(b.header)
    for k in range(6):
        if b.regions[k] is None:
            struct.pack_into(">HH", out, 8 + 4 * k, 0, b.counts[k])
            continue
        struct.pack_into(">HH", out, 8 + 4 * k, len(out), b.counts[k])
        out += b.regions[k]
    n = blocks or -(-len(out) // BLOCK)
    if len(out) > n * BLOCK:
        raise ValueError(f"background unit needs {len(out)} bytes, more than {n} blocks")
    return bytes(out + bytes(n * BLOCK - len(out)))
