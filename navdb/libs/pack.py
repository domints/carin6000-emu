"""Compression of routing parcels: the exact inverse of pbp's FUN_00003eb2 (libs/unpack.py). Takes
the unpacked RAM image of a level 0 parcel and returns a compressed unit that unpack() turns back
into the same image (docs/format.md section 3).

Stream: the 116-byte header (slot descriptors already final), 2 width bytes (segment length,
point delta), raw slots 3, 9, 10, 12, then an MSB-first bit stream: slots 0, 1, 2, segments, slots
5, 6, 7, 11, text, and for db release > 0x14 the second pass over slots 0 and 4.
"""
import struct

from .carindb import BLOCK
from .unpack import UNIT_HDR, bits_for


class BitWriter:
    def __init__(self):
        self.acc, self.n, self.out = 0, 0, bytearray()

    def write(self, value, width):
        if width <= 0:
            raise ValueError("width 0 has a special meaning for the reader")
        if value < 0 or value >> width:
            raise ValueError(f"{value} does not fit {width} bits")
        self.acc = (self.acc << width) | value
        self.n += width
        while self.n >= 8:
            self.n -= 8
            self.out.append((self.acc >> self.n) & 0xFF)
            self.acc &= (1 << self.n) - 1

    def flag(self, v):
        self.write(1 if v else 0, 1)

    def bytes(self):
        tail = bytes([(self.acc << (8 - self.n)) & 0xFF]) if self.n else b""
        return bytes(self.out) + tail + b"\0" * 5     # the reader fetches 5 bytes at a time


class Packer:
    def __init__(self, recsize, release, text_tables):
        self.size, self.release, self.text = recsize, release, text_tables
        a, b, c, d = text_tables
        self.code = {}
        for table, width, tag in ((d, 7, 3), (c, 3, 2), (b, 2, 1), (a, 1, 0)):   # shortest wins
            for i, ch in enumerate(table):
                self.code[ch] = (tag, width, i)

    def w(self, off):
        return struct.unpack_from(">H", self.d, off)[0]

    def parcel(self, d, d98=None, d99=None):
        """Compressed unit bytes for the RAM image d (a level 0 parcel). The widths d98 (segment
        length) and d99 (point delta) are chosen when not given."""
        self.d = bytes(d)
        z = self.size
        t = z[UNIT_HDR]
        if d98 is None or d99 is None:
            d98, d99 = self.widths(t)
        self.n = bits_for(len(self.d))
        self.w51 = bits_for(self.w(t + 0x0A))
        self.w53 = bits_for(self.w(t + 0x12) + 1)
        self.w55 = bits_for(self.w(t + 0x1E) + 1)
        self.w59 = bits_for(self.w(t + 0x2A) + 1)
        self.w57 = bits_for(self.w(t + 0x2E) + 1)
        self.w5b = bits_for(self.w(t + 0x32) + 1)
        self.d98, self.d99 = d98, d99
        out = bytearray(self.d[:z[0x0B]])
        out += bytes((d98, d99))
        for slot_off, rec, extra in ((t + 0x0C, 0x12, True), (t + 0x24, 0x0F, False), (t + 0x28, 0x14, False)):
            off, count = self.w(slot_off), self.w(slot_off + 2)
            out += self.d[off:off + count * z[rec] + (z[rec] if extra else 0)]
        if self.w(t + 0x32):
            off, count = self.w(t + 0x30), self.w(t + 0x32)
            out += self.d[off:off + count * z[0x15]]
        self.bits = BitWriter()
        self.slot0(t, 0x14)
        self.slot12(t + 4)
        self.slot12(t + 8)
        self.segments(t)
        self.points(t + 0x14, z[0x10], extra=False)
        self.points(t + 0x18, z[0x06], extra=True)
        self.points6(t + 0x1C)
        if self.w(t + 0x2E):
            self.slot11(t + 0x2C)
        self.texts()
        if self.release > 0x14:
            self.slot0(t, 0x15)
        out += self.bits.bytes()
        blocks = -(-len(out) // BLOCK)
        if blocks >= len(self.d) // BLOCK:
            return None                        # does not get smaller
        struct.pack_into(">I", out, 0, (struct.unpack_from(">I", out, 0)[0] & ~0xFF) | blocks)
        out[6], out[7] = 1, len(self.d) // BLOCK
        return bytes(out + bytes(blocks * BLOCK - len(out)))

    def widths(self, t):
        """The segment length width and point delta width that give the fewest bits."""
        z = self.size
        start, count = self.w(t + 0x10), self.w(t + 0x12)
        lengths = [self.w(start + i * z[0x08] + 12) for i in range(count)]
        d98 = min(range(6, 16), key=lambda w: sum(w if v >> w == 0 else 17 for v in lengths) + w)
        deltas = []
        for slot, rs in ((t + 0x14, z[0x10]), (t + 0x18, z[0x06]), (t + 0x1C, z[0x0C])):
            off, n = self.w(slot), self.w(slot + 2)
            for i in range(1, n):
                for k in (0, 2):
                    deltas.append(self.w(off + i * rs + k) - self.w(off + (i - 1) * rs + k))

        def cost(w):
            lim = 1 << w
            return sum(1 + w if 0 <= v < lim else (2 + w if 0 < -v < lim else 18) for v in deltas)
        d99 = min(range(3, 15), key=cost)
        return d98, d99

    def slot0(self, t, mode):
        b, rs = self.bits, self.size[0x40]
        off, count = self.w(t), self.w(t + 2)
        prev = None
        for r in range(off, off + count * rs, rs):
            if mode == 0x14:
                b.flag(0)
                b.write(self.w(r), self.n)
            else:
                same = prev is not None and self.w(r + 2) == self.w(prev + 2)
                b.flag(not same)
                if not same:
                    b.write(self.w(r + 2), 16)
            prev = r

    def slot12(self, slot):
        b, rs = self.bits, self.size[0x40]
        off, count = self.w(slot), self.w(slot + 2)
        prev = None
        for r in range(off, off + count * rs, rs):
            same = prev is not None and self.d[r + 2:r + 6] == self.d[prev + 2:prev + 6]
            b.flag(not same)
            if not same:
                b.write(self.w(r + 2), self.n)
                b.write(self.w(r + 4) >> 1, self.n - 1)
            b.write(self.w(r), self.n)
            prev = r

    def segments(self, t):
        b, z = self.bits, self.size
        rs, r09 = z[0x08], z[0x09]
        start = self.w(t + 0x10)
        count = self.w(t + 0x12)
        s7, s10, s11, s12, s2 = self.w(t + 0x1C), self.w(t + 0x28), self.w(t + 0x2C), self.w(t + 0x30), self.w(t + 8)
        st1 = st2 = 1
        prev = None

        def refs(r):
            b.write((self.w(r + 18) - s10) // z[0x14], self.w59)
            b.write((self.w(r + 20) - s12) // z[0x15], self.w5b)
            b.write((self.w(r + r09 + 4) - s11) // z[0x13], self.w57)

        ref = lambda r: (self.w(r + 18), self.w(r + 20), self.w(r + r09 + 4))
        attr = lambda r: self.d[r + 10:r + 12] + self.d[r + 16:r + 18] + self.d[r + r09 + 2:r + r09 + 4]
        for i in range(count):
            r = start + i * rs
            base = ref(prev) if prev is not None else (0, 0, 0)
            b.flag(ref(r) != base)
            if ref(r) != base:
                refs(r)
            abase = attr(prev) if prev is not None else bytes(6)
            b.flag(attr(r) != abase)
            if attr(r) != abase:
                for k in (10, 11, 16, 17):
                    b.write(self.d[r + k], 8)
                b.write(self.w(r + r09 + 2), 16)
            b.write(self.w(r) >> 1, self.n - 1)
            b.write(self.w(r + 2) >> 1, self.n - 1)
            b.flag(self.w(r + 4) != st1)
            if self.w(r + 4) != st1:
                st1 = self.w(r + 4)
                b.write((st1 - s7) // z[0x0C], self.w55)
            for k in (6, 8):
                v = self.w(r + k)
                b.write(count if v == 0 else (v - start) // rs, self.w53)
            length = self.w(r + 12)
            wide = length >> self.d98 != 0
            b.flag(wide)
            b.write(length, 16 if wide else self.d98)
            b.write(self.d[r + 14], 8)
            b.write(self.d[r + 15], 8)
            b.flag(self.w(r + r09) != st2)
            if self.w(r + r09) != st2:
                st2 = self.w(r + r09)
                b.write((st2 - s2) // z[0x40], self.w51)
            prev = r
        r = start + count * rs                   # the sentinel record
        same = prev is not None and ref(r) == ref(prev)
        b.flag(not same)
        if not same:
            refs(r)
        b.flag(self.w(r + 4) != st1)
        if self.w(r + 4) != st1:
            b.write((self.w(r + 4) - s7) // z[0x0C], self.w55)

    def _xy(self, r, prev):
        b = self.bits
        if prev is None:
            b.write(self.w(r), 16)
            b.write(self.w(r + 2), 16)
            return
        for k in (0, 2):
            v, p = self.w(r + k), self.w(prev + k)
            if 0 <= v - p < 1 << self.d99:
                b.write(0, 1)
                b.write(v - p, self.d99)
            elif 0 < p - v < 1 << self.d99:
                b.write(0b10, 2)
                b.write(p - v, self.d99)
            else:
                b.write(0b11, 2)
                b.write(v, 16)

    def points(self, slot, rs, extra):
        b, p = self.bits, self.size[0x10]
        off, count = self.w(slot), self.w(slot + 2)
        s4 = self.w(8 + 0x10)
        prev = None
        for r in range(off, off + count * rs, rs):
            same = prev is not None and self.d[r + 6:r + 8] == self.d[prev + 6:prev + 8]
            b.flag(not same)
            if not same:
                b.write(self.d[r + 6], 8)
                b.write(self.d[r + 7], 3)
            self._xy(r, prev)
            b.write((self.w(r + 4) - s4) // self.size[0x08], self.w53)
            if extra:
                b.write(struct.unpack_from(">I", self.d, r + p)[0], 32)
                b.write(self.w(r + p + 4), 14)
            prev = r

    def points6(self, slot):
        b, rs = self.bits, self.size[0x0C]
        off, count = self.w(slot), self.w(slot + 2)
        prev = None
        for r in range(off, off + count * rs, rs):
            self._xy(r, prev)
            b.write(self.d[r + 4], 3)
            prev = r

    def slot11(self, slot):
        b, rs = self.bits, self.size[0x13]
        off, count = self.w(slot), self.w(slot + 2)
        for r in range(off, off + count * rs, rs):
            b.write(self.w(r), self.n)
            b.write(self.w(r + 2), self.n)
            b.write(self.w(r + 4), 1)

    def texts(self):
        """The text area from the first name to the last 0 (the zero name table before it is not
        coded; pbp leaves zeros there)."""
        b = self.bits
        t = self.size[UNIT_HDR]
        start, count = self.w(t + 0x38), self.w(t + 0x3A)
        if not start:
            b.write(0, self.n)
            b.write(0, self.n)
            return
        first = start + 4 * count
        end = len(self.d.rstrip(b"\0"))
        last = end                               # the 0 ending the last name
        if last < first:
            b.write(0, self.n)
            b.write(0, self.n)
            return
        b.write(first, self.n)
        b.write(last, self.n)
        # bytes the code has no place for (e.g. '"') become one-byte phrases (at most 6)
        odd = sorted({ch for ch in self.d[first:last + 1] if ch not in self.code and not 0x26 < ch < 0x80})
        if len(odd) > 6 or any(ch >= 0x80 for ch in odd):
            raise ValueError(f"text bytes {[hex(c) for c in odd]} cannot be coded")
        for k in range(6):
            if k < len(odd):
                b.write(1, 5)
                b.write(odd[k], 7)
            else:
                b.write(0, 5)
        for p in range(first, last + 1):
            ch = self.d[p]
            if ch in self.code:
                tag, width, i = self.code[ch]
            elif 0x26 < ch < 0x80:
                tag, width, i = 3, 7, ch
            else:
                tag, width, i = 3, 7, 0x21 + odd.index(ch)
            b.write(tag, 2)
            b.write(i, width)
