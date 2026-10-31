"""ALU suite: word and byte ALU in every addressing mode, the flag corners,
and the ADDC/SUBC sticky-zero chains.

The expected results come from the model in common.py. Encodings come from
A166 (the mnemonics below), so a mismatch means the emulator or the model.
"""

from .common import Suite, base, finish, after_srst, add_w, add_b, sub_w, sub_b, logic_w, logic_b

ALU_WORD = [  # (opcode nibble, mnemonic, model, logic?)
    (0, "ADD", lambda a, b: add_w(a, b), False),
    (2, "SUB", lambda a, b: sub_w(a, b), False),
    (4, "CMP", lambda a, b: (a, sub_w(a, b)[1]), False),
    (5, "XOR", lambda a, b: logic_w(a ^ b, b), True),
    (6, "AND", lambda a, b: logic_w(a & b, b), True),
    (7, "OR", lambda a, b: logic_w(a | b, b), True),
]

ALU_BYTE = [
    (0, "ADDB", lambda a, b: add_b(a, b)),
    (1, "ADDCB", lambda a, b: add_b(a, b, 0, True, False)),
    (2, "SUBB", lambda a, b: sub_b(a, b)),
    (3, "SUBCB", lambda a, b: sub_b(a, b, 0, True, False)),
    (4, "CMPB", lambda a, b: (a, sub_b(a, b)[1])),
    (5, "XORB", lambda a, b: logic_b(a ^ b, b)),
    (6, "ANDB", lambda a, b: logic_b(a & b, b)),
    (7, "ORB", lambda a, b: logic_b(a | b, b)),
]


def alu_word(s):
    """Word ALU, one case per addressing mode."""
    for _, name, fn, logic in ALU_WORD:
        for mode in ("rr", "ind", "post", "i3", "i16", "rm", "mr"):
            if name == "CMP" and mode == "mr":
                continue
            dest, src = (0xf0f0, 0x0ff0) if logic else (0x1234, 0x0001)
            if mode == "i3":
                src = 1
            got, flags = fn(dest, src)
            want = dest if name == "CMP" else got
            if mode == "rr":
                s.mov(0, dest)
                s.mov(1, src)
                s.ins(f"{name}\tR0,R1")
                s.check(0, want, flags)
            elif mode == "ind":
                s.mov(1, src)
                s.store(0xf900, 1)
                s.mov(1, 0xf900)
                s.mov(0, dest)
                s.ins(f"{name}\tR0,[R1]")
                s.check(0, want, flags)
            elif mode == "post":
                s.mov(1, src)
                s.store(0xf900, 1)
                s.mov(1, 0xf900)
                s.mov(0, dest)
                s.ins(f"{name}\tR0,[R1+]")
                s.check(0, want, flags)
                s.check(1, 0xf902, None)
            elif mode == "i3":
                s.mov(0, dest)
                s.ins(f"{name}\tR0,#1")
                s.check(0, want, flags)
            elif mode == "i16":
                s.mov(0, dest)
                s.ins(f"{name}\tR0,#0{src:04X}H")
                s.check(0, want, flags)
            elif mode == "rm":
                s.mov(1, src)
                s.store(0xf900, 1)
                s.mov(0, dest)
                s.ins(f"{name}\tR0,0F900H")
                s.check(0, want, flags)
            else:  # mr: memory destination
                s.mov(0, dest)
                s.store(0xf900, 0)
                s.mov(1, src)
                s.ins(f"{name}\t0F900H,R1")
                s.check_mem(0xf900, got, flags)


def word_corners(s):
    """Flag corners on Rw,Rw and the carry/sticky-zero chains."""
    for name, fn, da, db in (
        ("ADD", add_w, 0xffff, 1),
        ("ADD", add_w, 0x7fff, 1),
        ("ADD", add_w, 0x0000, 0x8000),
        ("SUB", sub_w, 0x0001, 0x0002),
        ("SUB", sub_w, 0x8000, 1),
    ):
        s.mov(0, da)
        s.mov(1, db)
        s.ins(f"{name}\tR0,R1")
        got, flags = fn(da, db)
        s.check(0, got, flags)

    # ADDC: Z stays set only when the result is also zero.
    s.mov(1, 0xffff)
    s.mov(0, 0xffff)
    s.ins("ADD\tR0,#1")          # 0, Z and C
    s.ins("ADDC\tR1,R0")         # FFFF + 0 + 1 = 0, sticky Z, C
    got, flags = add_w(0xffff, 0, cin=1, sticky=True, oldz=True)
    s.check(1, got, flags)
    s.mov(0, 0xffff)
    s.ins("ADD\tR0,#1")
    s.ins("ADDC\tR0,#0")         # 1, Z cleared
    got, flags = add_w(0, 0, cin=1, sticky=True, oldz=True)
    s.check(0, got, flags)

    # SUBC sticky.
    s.mov(1, 0)
    s.mov(0, 0xffff)
    s.ins("ADD\tR0,#1")          # Z and C, R0 = 0
    s.ins("SUBC\tR1,R0")         # 0 - 0 - 1 = FFFF
    got, flags = sub_w(0, 0, cin=1, sticky=True, oldz=True)
    s.check(1, got, flags)


def alu_byte(s):
    """Byte ALU: register, indirect, post-increment, #data3, #data8, memory."""
    for alu, name, fn in ALU_BYTE:
        da, db = (0x3c, 0x01) if alu < 5 else (0xf0, 0x0f)
        got, flags = fn(da, db)
        val = da if alu == 4 else got & 0xff

        s.mov(0, da)
        s.mov(1, db)
        s.ins(f"{name}\tRL0,RL1")
        s.check(0, val, flags)

        s.mov(0, da)
        s.mov(2, 0xf900)
        s.store(0xf900, 1)
        s.ins(f"{name}\tRL0,[R2]")
        s.check(0, val, flags)

        s.mov(0, da)
        s.mov(1, 0xf900)
        s.ins(f"{name}\tRL0,[R1+]")
        s.check(0, val, flags)
        s.check(1, 0xf901, None)

        got3, flags3 = fn(da, 1)
        s.mov(0, da)
        s.ins(f"{name}\tRL0,#1")
        s.check(0, da if alu == 4 else got3 & 0xff, flags3)

        s.mov(0, da)
        s.ins(f"{name}\tRL0,#0{db:02X}H")
        s.check(0, val, flags)

        s.mov(1, db)
        s.store(0xf900, 1)
        s.mov(0, da)
        s.ins(f"{name}\tRL0,0F900H")
        s.check(0, val, flags)

        if alu != 4:
            # Memory destination: result stored, then read back with MOVB.
            s.mov(0, da)
            s.mov(1, db)
            s.store(0xf900, 0)
            s.ins(f"{name}\t0F900H,RL1")
            s.ins("MOVB\tRL0,0F900H")
            s.check(0, got & 0xff, None)

    # The byte-sized V and carry corners.
    for x, y in ((0x7f, 0x01), (0x00, 0x80)):
        s.mov(0, x)
        s.mov(1, y)
        s.ins("ADDB\tRL0,RL1")
        got, flags = add_b(x, y)
        s.check(0, got, flags)



def build():
    s = Suite("ALU")
    base(s)
    alu_word(s)
    word_corners(s)
    alu_byte(s)
    finish(s)
    after_srst(s)
    return s
