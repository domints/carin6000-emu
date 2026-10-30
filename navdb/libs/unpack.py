"""Unpacking of map parcel units (table 1 of carindb), ported from the OS-9 module pbp (flash
0209): FUN_00003508 (dispatch), FUN_00003eb2 (parcel), the slot expanders FUN_000035de ...
FUN_00003e06, the text decoder FUN_00004abc and the bit reader FUN_00004c16.

A compressed unit (byte +6 bit 0 set) is expanded into a buffer of (byte +7) blocks: the parcel
header (record type 0x0b, 116 bytes here) and some slots are copied as they are, the other slots
are rebuilt from an MSB-first bit stream, then the text area is decoded. Field meanings are in
../docs/format.md; this module only reproduces the layout pbp builds.
"""
import struct

BLOCK = 2048
UNIT_HDR = 0x05     # record type of the unit header (8 bytes); the parcel header (type 0x11) follows


def bits_for(v):
    """FUN_00004cc2: bits needed for values 0..v-1 (1 for v == 1; 16-bit arithmetic)."""
    if v == 1:
        return 1
    n, u = 0, (v - 1) & 0xFFFF
    while u:
        n += 1
        u >>= 1
    return n


class BitReader:
    """FUN_00004c16 & co: bfextu from a base pointer, MSB first."""

    def __init__(self, data, start):
        self.data = data
        self.base = start
        self.pos = 0

    def read(self, n):
        """n bits; n == 0 extracts 32 bits without moving (FUN_00004c16 adds the width to the
        position, then bfextu with width 0 means 32)."""
        width = n or 32
        byte, bit = self.base + (self.pos >> 3), self.pos & 7
        chunk = int.from_bytes(self.data[byte:byte + 5].ljust(5, b"\0"), "big")
        self.pos += n
        return (chunk >> (40 - bit - width)) & ((1 << width) - 1)


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class Unpacker:
    def __init__(self, recsize, release, text_tables):
        self.size = recsize          # record type -> size in bytes (block 0 table)
        self.release = release       # block 0 offset 0x1a (FUN_000034c0 returns it)
        self.text = text_tables      # (A, B, C, D) byte tables of the text decoder

    # -- helpers on the output buffer ---------------------------------------------------------
    def w(self, off):
        return struct.unpack_from(">H", self.dst, off)[0]

    def put_w(self, off, v):
        struct.pack_into(">H", self.dst, off, v & 0xFFFF)

    def put_b(self, off, v):
        self.dst[off] = v & 0xFF

    def copy(self, off, n):
        """FUN_00004a34: n bytes from the source cursor to dst+off."""
        self.dst[off:off + n] = self.src[self.cur:self.cur + n]
        self.cur += n

    def copy_slot(self, slot_off, rec, extra):
        """FUN_00004a5a: a slot copied as it is (count records, one more if extra)."""
        off, count = self.w(slot_off), self.w(slot_off + 2)
        self.copy(off, count * self.size[rec] + (self.size[rec] if extra else 0))

    # -- entry ---------------------------------------------------------------------------------
    def unpack(self, unit):
        """FUN_00003508. Returns the expanded unit (bytearray) or None for kinds not ported yet."""
        self.src = unit
        length = unit[3]
        if not unit[6] & 1:
            return bytearray(unit[:length * BLOCK])
        self.dst = bytearray(unit[7] * BLOCK)
        self.n = bits_for(unit[7] * BLOCK)            # FUN_000049f2
        self.cur = 0
        kind = struct.unpack_from(">H", unit, 4)[0]
        if kind == 0:
            self.parcel()
        elif kind in (0x14, 0x15, 0x16, 0x1C, 0x1D, 0x1E):
            # pbp (release 14..21) zeroes compressed 0x1c..0x1e units; they share the background
            # layout and unpack correctly with FUN_00004840
            self.shapes()
        else:
            return None                               # 0x0e: not ported yet
        struct.pack_into(">H", self.dst, 6, 0)
        return self.dst

    def parcel(self):
        """FUN_00003eb2."""
        z = self.size
        t = z[UNIT_HDR]                               # parcel header (type 0x11) at dst+8
        self.copy(0, z[0x0B])
        self.w51 = bits_for(self.w(t + 0x0A))
        self.w53 = bits_for(self.w(t + 0x12) + 1)
        self.w55 = bits_for(self.w(t + 0x1E) + 1)
        self.w59 = bits_for(self.w(t + 0x2A) + 1)
        self.w57 = bits_for(self.w(t + 0x2E) + 1)
        self.w5b = bits_for(self.w(t + 0x32) + 1)
        self.d98 = self.src[self.cur]                 # 2 bytes into globals 0x0d98/0x0d99
        self.d99 = self.src[self.cur + 1]
        self.cur += 2
        self.copy_slot(t + 0x0C, 0x12, True)
        self.copy_slot(t + 0x24, 0x0F, False)
        self.copy_slot(t + 0x28, 0x14, False)
        if self.w(t + 0x32):
            self.copy_slot(t + 0x30, 0x15, False)
        self.bits = BitReader(self.src, self.cur)     # FUN_00004bee
        self.slot0(t, 0x14)
        self.slot12(t + 4)
        self.slot12(t + 8)
        self.segments(t, 0x14)
        self.points8(t + 0x14)
        self.points16(t + 0x18)
        self.points6(t + 0x1C)
        if self.w(t + 0x2E):
            self.slot11(t + 0x2C)
        self.texts()
        if self.release > 0x14:
            self.w5d = bits_for(self.w(t + 0x36) + 1)
            self.slot0(t, 0x15)
            self.segments(t, 0x15)
            self.put_w(t + 0x34, 0)                   # FUN_00003e8a
            self.put_w(t + 0x36, 0)

    def shapes(self):
        """FUN_00004840: units of kind 0x14..0x16 (tables 1c, 16, 6): records whose shapes are runs
        of points in slot 3, then the text area. Generic slot expander FUN_000044a2."""
        z = self.size
        t = z[UNIT_HDR]
        self.copy(0, z[0x3D])
        self.wca = bits_for(self.w(t + 0x0E) + 1)
        self.dce, self.dcf, self.dd0, self.dd1 = self.src[self.cur:self.cur + 4]
        self.cur += 4
        self.bits = BitReader(self.src, self.cur)
        wide = self.w(t + 0x10 + z[0x3F]) == 0        # slot 3: 8-byte absolute points, else 4-byte deltas
        self.generic(t, z[0x3B], 0x25, 0x0E, wide)
        self.generic(t + 4, z[0x3A], 0x26, 0x0E, wide)
        self.generic(t + 8, z[0x3C], 0x27, 0x0E, wide)
        self.generic(t + 0x0C, 8 if wide else 4, 0x0B if wide else 0x0A, 0x0E, wide)
        self.texts()
        if self.release > 0x13:
            self.dd2, self.dd3, self.dd4, self.dd5, self.dd6 = (self.bits.read(8) for _ in range(5))
            self.generic(t + 0x10, z[0x15], 0x28, 0x14, wide)
            self.generic(t + 4, z[0x3A], 0x26, 0x14, wide)
            self.generic(t + 8, z[0x3C], 0x27, 0x14, wide)

    def generic(self, slot, rs, code, mode, wide):
        """FUN_000044a2."""
        b, t = self.bits, self.size[UNIT_HDR]
        off, count = self.w(slot), self.w(slot + 2)
        if not count:
            return
        last = off + (count - 1) * rs + (rs if code in (0x25, 0x26, 0x27) else 0)
        step = 8 if wide else 4
        pt_base = self.w(t + 0x0C)
        prev = None
        r = off
        while r <= last:
            if code == 0x26:
                if mode == 0x0E:
                    self.put_w(r, b.read(self.n))
                    self.put_w(r + 2, step * b.read(self.wca) + pt_base)
                    struct.pack_into(">I", self.dst, r + 4, b.read(32 if b.read(1) else self.dcf))
                    struct.pack_into(">I", self.dst, r + 8, b.read(32))
                    struct.pack_into(">I", self.dst, r + 12, b.read(32))
                else:
                    self.put_w(r + 16, b.read(self.n - 1) << 1)
                    self.put_w(r + 18, b.read(16 if b.read(1) else self.dd2))
            elif code == 0x0B:
                struct.pack_into(">I", self.dst, r, b.read(32))
                struct.pack_into(">I", self.dst, r + 4, b.read(32))
            elif code == 0x0A:
                self._xy_width(r, prev, r == off, self.dd0)
                prev = r
            elif code == 0x25:
                self.put_b(r, b.read(7))
                self.put_b(r + 1, b.read(1))
                self.put_w(r + 2, b.read(self.n - 1) << 1)
            elif code == 0x28:
                for k in (0, 2, 4):
                    width = 16 if b.read(1) else (self.dd4, self.dd5, self.dd6)[k // 2]
                    self.put_w(r + k, b.read(width))
            elif code == 0x27:
                if mode == 0x0E:
                    self.put_w(r, b.read(self.n))
                    self.put_w(r + 2, step * b.read(self.wca) + pt_base)
                    struct.pack_into(">I", self.dst, r + 4, b.read(32 if b.read(1) else self.dce))
                else:
                    self.put_w(r + 8, b.read(self.n - 1) << 1)
                    b.read(16 if b.read(1) else self.dd3)
                    self.put_w(r + 10, 0)
            r += rs

    def _xy_width(self, r, prev, first, width):
        """Delta-coded x/y pair (as _xy) with a given delta width."""
        b = self.bits
        if first:
            self.put_w(r, b.read(16))
            self.put_w(r + 2, b.read(16))
            return
        for k in (0, 2):
            if b.read(1) == 0:
                v = self.w(prev + k) + b.read(width)
            elif b.read(1) == 0:
                v = self.w(prev + k) - b.read(width)
            else:
                v = b.read(16)
            self.put_w(r + k, v)

    # -- slot expanders ------------------------------------------------------------------------
    def slot0(self, t, mode):
        """FUN_000035de: slot 0, records of type 0x40."""
        b, rs = self.bits, self.size[0x40]
        off, count = self.w(t), self.w(t + 2)
        prev = None
        for r in range(off, off + count * rs, rs):
            if mode == 0x14:
                if b.read(1):
                    b.read(self.n)
                    b.read(self.n - 1)
                self.put_w(r, b.read(self.n))
            else:
                if b.read(1):
                    v = b.read(16)
                else:
                    v = 0 if self.release < 0x15 else self.w(prev + 2)
                self.put_w(r + 2, v)
            prev = r

    def slot12(self, slot):
        """FUN_00003692 / FUN_00003718: slots 1 and 2, records of type 0x40."""
        b, rs = self.bits, self.size[0x40]
        off, count = self.w(slot), self.w(slot + 2)
        prev = None
        for r in range(off, off + count * rs, rs):
            if b.read(1) == 0:
                self.put_w(r + 2, self.w(prev + 2))
                self.put_w(r + 4, self.w(prev + 4))
            else:
                self.put_w(r + 2, b.read(self.n))
                self.put_w(r + 4, b.read(self.n - 1) << 1)
            self.put_w(r, b.read(self.n))
            prev = r

    def segments(self, t, mode):
        """FUN_0000379e: slot 4, records of type 0x08."""
        b, z = self.bits, self.size
        rs, r09 = z[0x08], z[0x09]
        start = self.w(t + 0x10)
        end = start + self.w(t + 0x12) * rs
        st1 = st2 = 1                                  # globals 0x0d94, 0x0d96
        prev = None
        r = start
        while r < end:
            if mode == 0x14:
                if r != start:
                    self.dst[r:r + rs] = self.dst[prev:prev + rs]
                if b.read(1):
                    self.put_w(r + 18, self.w(t + 0x28) + z[0x14] * b.read(self.w59))
                    self.put_w(r + 20, self.w(t + 0x30) + z[0x15] * b.read(self.w5b))
                    self.put_w(r + r09 + 4, self.w(t + 0x2C) + z[0x13] * b.read(self.w57))
                if b.read(1):
                    self.put_b(r + 10, b.read(8))
                    self.put_b(r + 11, b.read(8))
                    self.put_b(r + 16, b.read(8))
                    self.put_b(r + 17, b.read(8))
                    self.put_w(r + r09 + 2, b.read(16))
                self.put_w(r + 0, b.read(self.n - 1) << 1)
                self.put_w(r + 2, b.read(self.n - 1) << 1)
                if b.read(1):
                    st1 = self.w(t + 0x1C) + z[0x0C] * b.read(self.w55)
                self.put_w(r + 4, st1)
                for k in (6, 8):
                    v = b.read(self.w53)
                    self.put_w(r + k, 0 if v == self.w(t + 0x12) else v * rs + self.w(t + 0x10))
                width = 16 if b.read(1) else self.d98
                self.put_w(r + 12, b.read(width))
                self.put_b(r + 14, b.read(8))
                self.put_b(r + 15, b.read(8))
                if b.read(1):
                    st2 = self.w(t + 8) + z[0x40] * b.read(self.w51)
                self.put_w(r + r09, st2)
            else:
                self.put_w(r + 22, 0)
            prev = r
            r += rs
        if mode == 0x14:
            # After the loop the record pointer is one past the last record: a sentinel record
            # (the slot holds count + 1 of them) gets the reference fields and the node state.
            if b.read(1) == 0:
                if prev is not None:
                    for k in (18, 20, r09 + 4):
                        self.put_w(r + k, self.w(prev + k))
            else:
                self.put_w(r + 18, self.w(t + 0x28) + z[0x14] * b.read(self.w59))
                self.put_w(r + 20, self.w(t + 0x30) + z[0x15] * b.read(self.w5b))
                self.put_w(r + r09 + 4, self.w(t + 0x2C) + z[0x13] * b.read(self.w57))
            if b.read(1):
                st1 = self.w(t + 0x1C) + z[0x0C] * b.read(self.w55)
            self.put_w(r + 4, st1)

    def _xy(self, r, prev, first):
        """The x/y pair of the point slots: absolute 16 bits first, then deltas of d99 bits:
        0 = previous + d, 10 = previous - d, 11 = absolute 16 bits."""
        b = self.bits
        if first:
            self.put_w(r, b.read(16))
            self.put_w(r + 2, b.read(16))
            return
        for k in (0, 2):
            if b.read(1) == 0:
                v = self.w(prev + k) + b.read(self.d99)
            elif b.read(1) == 0:
                v = self.w(prev + k) - b.read(self.d99)
            else:
                v = b.read(16)
            self.put_w(r + k, v)

    def points8(self, slot):
        """FUN_00003abe: slot 5, records of type 0x10."""
        b, rs = self.bits, self.size[0x10]
        off, count = self.w(slot), self.w(slot + 2)
        prev = None
        for r in range(off, off + count * rs, rs):
            if b.read(1) == 0:
                self.dst[r + 6], self.dst[r + 7] = self.dst[prev + 6], self.dst[prev + 7]
            else:
                self.put_b(r + 6, b.read(8))
                self.put_b(r + 7, b.read(3))
            self._xy(r, prev, r == off)
            self.put_w(r + 4, self.w(8 + 0x10) + self.size[0x08] * b.read(self.w53))
            prev = r

    def points16(self, slot):
        """FUN_00003be4: slot 6, records of type 0x06 (a point record of type 0x10 plus 6 bytes)."""
        b, rs, p = self.bits, self.size[0x06], self.size[0x10]
        off, count = self.w(slot), self.w(slot + 2)
        prev = None
        for r in range(off, off + count * rs, rs):
            if b.read(1) == 0:
                self.dst[r + 6], self.dst[r + 7] = self.dst[prev + 6], self.dst[prev + 7]
            else:
                self.put_b(r + 6, b.read(8))
                self.put_b(r + 7, b.read(3))
            self._xy(r, prev, r == off)
            self.put_w(r + 4, self.w(8 + 0x10) + self.size[0x08] * b.read(self.w53))
            struct.pack_into(">I", self.dst, r + p, b.read(32))
            self.put_w(r + p + 4, b.read(14))
            prev = r

    def points6(self, slot):
        """FUN_00003d28: slot 7, records of type 0x0c."""
        b, rs = self.bits, self.size[0x0C]
        off, count = self.w(slot), self.w(slot + 2)
        prev = None
        for r in range(off, off + count * rs, rs):
            self._xy(r, prev, r == off)
            self.put_b(r + 4, b.read(3))
            prev = r

    def slot11(self, slot):
        """FUN_00003e06: slot 11, records of type 0x13."""
        b, rs = self.bits, self.size[0x13]
        off, count = self.w(slot), self.w(slot + 2)
        for r in range(off, off + count * rs, rs):
            self.put_w(r, b.read(self.n))
            self.put_w(r + 2, b.read(self.n))
            self.put_w(r + 4, b.read(1))

    def texts(self):
        """FUN_00004abc: the text area, a byte code tuned for names."""
        b = self.bits
        A, B, C, D = self.text
        first, last = b.read(self.n), b.read(self.n)
        if not first and not last:
            return
        phrases = []
        for _ in range(6):
            n = b.read(5)
            phrases.append(bytes(b.read(7) for _ in range(n)))
        p = first
        while p <= last:
            code = b.read(2)
            if code == 0:
                self.dst[p] = A[b.read(1)]
            elif code == 1:
                self.dst[p] = B[b.read(2)]
            elif code == 2:
                self.dst[p] = C[b.read(3)]
            else:
                v = b.read(7)
                if v > 0x26:
                    self.dst[p] = v
                elif v <= 0x1B:
                    self.dst[p] = D[v]
                else:
                    ph = phrases[v - 0x21] if 0 <= v - 0x21 < 6 else b""
                    self.dst[p:p + len(ph)] = ph
                    p += len(ph) - 1
            p += 1
