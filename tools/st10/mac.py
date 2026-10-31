"""MAC suite. Mnemonics are the ones A166 accepts under $MODV2.

The accumulator is the 40-bit MAH:MAL value with the extension in MSW.
MSW bit 9 is always set. N is bit 15, Z is bit 14, C is bit 13.
"""

from .common import Suite, base, finish, after_srst

MASK40 = (1 << 40) - 1


def sex16(v):
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def pack(value, carry=0):
    bits = value & MASK40
    mal = bits & 0xffff
    mah = (bits >> 16) & 0xffff
    msw = 0x0200 | ((bits >> 32) & 0xff)
    if bits & (1 << 39):
        msw |= 0x8000
    if bits == 0:
        msw |= 0x4000
    if carry:
        msw |= 0x2000
    return mal, mah, msw


def acc(s, mal, mah, msw):
    s.load(0, 0xfe5c)
    s.check(0, mal, None)
    s.load(0, 0xfe5e)
    s.check(0, mah, None)
    s.load(0, 0xffde)
    s.check(0, msw, None)


def pair(s, lo, hi):
    s.mov(1, lo)
    s.mov(2, hi)


def body(s):
    # Signed, unsigned, mixed and negated products. MCW starts clear, so
    # the product is not shifted and saturation is off.
    s.sfr_imm(0xffdc, 0)
    pair(s, 2, 3)
    s.ins("CoMUL\tR1,R2")
    acc(s, *pack(2 * 3))

    pair(s, 0xfffc, 3)                 # -4 * 3
    s.ins("CoMUL\tR1,R2")
    acc(s, *pack(sex16(0xfffc) * 3))

    pair(s, 0x8000, 2)
    s.ins("CoMULu\tR1,R2")
    acc(s, *pack(0x8000 * 2))

    pair(s, 0x8000, 0xfffe)            # unsigned * signed(-2)
    s.ins("CoMULus\tR1,R2")
    acc(s, *pack(0x8000 * sex16(0xfffe)))

    pair(s, 2, 3)
    s.ins("CoMUL-\tR1,R2")
    acc(s, *pack(-(2 * 3)))

    # MP shifts the product left by one.
    s.sfr_imm(0xffdc, 0x4000)
    pair(s, 3, 4)
    s.ins("CoMUL\tR1,R2")
    acc(s, *pack((3 * 4) << 1))
    s.sfr_imm(0xffdc, 0)

    # Accumulate and reverse accumulate.
    pair(s, 5, 1)
    s.ins("CoMUL\tR1,R2")              # acc = 5
    pair(s, 7, 1)
    s.ins("CoMAC\tR1,R2")              # 5 + 7
    acc(s, *pack(12))
    pair(s, 4, 1)
    s.ins("CoMACR\tR1,R2")             # 4 - 12, borrow sets C
    acc(s, *pack(4 - 12, carry=1))

    # 32-bit load and arithmetic. CoLOAD/CoADD take the low half in R1.
    pair(s, 0x0010, 0x0001)
    s.ins("CoLOAD\tR1,R2")
    acc(s, *pack(0x00010010))
    pair(s, 0x0001, 0)
    s.ins("CoADD\tR1,R2")
    acc(s, *pack(0x00010011))
    pair(s, 0x0002, 0)
    s.ins("CoADD2\tR1,R2")             # add the operand twice
    acc(s, *pack(0x00010011 + 4))
    pair(s, 0x0004, 0)
    s.ins("CoSUB\tR1,R2")
    acc(s, *pack(0x00010011))
    pair(s, 0x0010, 0)
    s.ins("CoLOAD\tR1,R2")             # known value for the compares
    pair(s, 0x0030, 0)
    s.ins("CoMAX\tR1,R2")
    acc(s, *pack(0x30))
    pair(s, 0x0005, 0)
    s.ins("CoMIN\tR1,R2")
    acc(s, *pack(5))

    # CoCMP leaves MAL and MAH alone.
    pair(s, 0x0005, 0)
    s.ins("CoCMP\tR1,R2")
    # The checker overwrites R3 and R4, so the two halves go in R1 and R2.
    s.load(1, 0xfe5c)
    s.load(2, 0xfe5e)
    s.check(1, 5, None)
    s.check(2, 0, None)

    # Negate the accumulator, then absolute value of the same 32-bit word.
    s.ins("CoNEG")
    acc(s, *pack(-5))
    pair(s, 0xfffb, 0xffff)
    s.ins("CoABS\tR1,R2")
    acc(s, *pack(5))
    pair(s, 0x8000, 0)
    s.ins("CoLOAD\tR1,R2")
    s.ins("CoRND")
    acc(s, *pack(0x10000))
    s.ins("CoSHL\t#1")
    acc(s, *pack(0x20000))
    s.ins("CoSHR\t#1")
    acc(s, *pack(0x10000))
    pair(s, 2, 0)
    s.ins("CoSHL\tR1")                 # count is R1
    acc(s, *pack(0x40000))
    pair(s, 0xfffc, 1)                 # -4
    s.ins("CoMUL\tR1,R2")
    s.mov(1, 1)
    s.ins("CoASHR\tR1")
    acc(s, *pack(-2))

    # CoSTORE writes a coregister. -2 has MAH FFFF and MAL FFFE.
    s.ins("CoSTORE\tR3,MAH")
    s.check(3, 0xffff, None)
    s.ins("CoSTORE\tR3,MAL")
    s.check(3, 0xfffe, None)

    # Memory operand with post-increment, then a copy through IDX0.
    s.mov(0, 4)
    s.store(0xf800, 0)
    s.mov(0, 0)
    s.ins("CoMUL\tR0,R0")
    s.mov(1, 5)
    s.mov(2, 0xf800)
    s.ins("CoMAC\tR1,[R2+]")
    acc(s, *pack(20))
    s.check(2, 0xf802, None)

    s.sfr_imm(0xff08, 0xf810)          # IDX0
    s.mov(2, 0xf800)
    s.ins("CoMOV\t[IDX0+],[R2+]")
    s.load(0, 0xf810)
    s.check(0, 4, None)
    s.load(0, 0xff08)
    s.check(0, 0xf812, None)
    s.check(2, 0xf802, None)

    # CoNOP reads but does not change the accumulator.
    s.mov(2, 0xf800)
    s.ins("CoNOP\t[IDX0],[R2]")
    acc(s, *pack(20))

    # "- USR0" repeats MRW+1 times. Three passes of 2 * (3, 4, 5).
    for i, v in enumerate((3, 4, 5)):
        s.mov(0, v)
        s.store(0xf820 + 2 * i, 0)
    s.sfr_imm(0xffda, 2)               # three iterations
    s.mov(0, 0)
    s.ins("CoMUL\tR0,R0")
    s.mov(1, 2)
    s.mov(2, 0xf820)
    s.ins("-\tUSR0\tCoMAC\tR1,[R2+]")
    acc(s, *pack(2 * (3 + 4 + 5)))
    s.check(2, 0xf826, None)


def build():
    s = Suite("MAC")
    s.model = "V2"
    base(s)
    body(s)
    finish(s)
    after_srst(s)
    return s
