"""CORE suite: shifts, unary, compares, moves, bit ops, branches, calls.

Everything here runs with the reset-time PSW and no peripheral set up, so it
needs only RAM at F900..FDFF and the bit area.
"""

from .common import (Suite, base, finish, after_srst, add_w, add_b, sub_w,
                     sub_b, logic_w, logic_b, do_shift, N, C, V, Z, E)

def shifts(s):
    """Shifts and rotates, register and immediate, zero and nonzero counts."""
    names = {0: ("SHL", "SHL"), 1: ("SHR", "SHR"), 2: ("ASHR", "ASHR"),
             3: ("ROL", "ROL"), 4: ("ROR", "ROR")}
    samples = {
        0: ((0x4000, 1), (0x4000, 0)),
        1: ((0x0003, 1), (0x0007, 2)),
        2: ((0x8000, 1), (0x8001, 0)),
        3: ((0x8001, 1), (0x0001, 0)),
        4: ((0x8001, 1), (0x0001, 0)),
    }
    for kind, (rr_name, _) in names.items():
        for value, count in samples[kind]:
            got, flags = do_shift(value, count, kind)
            s.mov(0, value)
            s.mov(1, count)
            s.ins(f"{rr_name}\tR0,R1")
            s.check(0, got, flags)
            s.mov(0, value)
            s.ins(f"{rr_name}\tR0,#{count & 15}")
            s.check(0, got, flags)


def unary_compare(s):
    """NEG, NEGB, CPL, CPLB, PRIOR, CMPD1/CMPD2/CMPI1/CMPI2."""
    s.mov(0, 1)
    s.ins("NEG\tR0")
    got, flags = sub_w(0, 1)
    s.check(0, got, flags)
    s.mov(0, 0x8000)
    s.ins("NEG\tR0")
    got, flags = sub_w(0, 0x8000)
    s.check(0, got, flags)
    s.mov(0, 0)
    s.ins("NEGB\tRL0")
    s.check(0, 0, Z)
    s.mov(0, 0x1234)
    s.ins("CPL\tR0")
    s.check(0, 0xedcb, N | C)
    s.mov(0, 0x12)
    s.ins("CPLB\tRL0")
    s.check(0, 0xed, N | C)

    s.mov(1, 0)
    s.mov(0, 0x1234)
    s.ins("PRIOR\tR0,R1")
    s.check(0, 0, Z)
    s.mov(1, 1)
    s.ins("PRIOR\tR0,R1")
    s.check(0, 15, 0)
    s.check(1, 1, None)
    s.mov(1, 0x8000)
    s.ins("PRIOR\tR0,R1")
    s.check(0, 0, Z)

    # Compare-with-step: CMPD1 and CMPD2 decrement, CMPI1 and CMPI2 increment.
    s.mov(0, 5)
    s.ins("CMPD1\tR0,#1")
    s.check(0, 4, sub_w(5, 1)[1])
    s.mov(0, 5)
    s.ins("CMPD2\tR0,#1")
    s.check(0, 3, sub_w(5, 1)[1])
    s.mov(0, 5)
    s.ins("CMPI1\tR0,#1")
    s.check(0, 6, sub_w(5, 1)[1])
    s.mov(0, 5)
    s.ins("CMPI2\tR0,#1")
    s.check(0, 7, sub_w(5, 1)[1])
    s.mov(0, 5)
    s.ins("CMPD1\tR0,#0100H")
    s.check(0, 4, sub_w(5, 0x100)[1])
    s.mov(1, 5)
    s.store(0xf900, 1)
    s.mov(0, 5)
    s.ins("CMPD1\tR0,0F900H")
    s.check(0, 4, sub_w(5, 5)[1])


def moves(s):
    """MOV addressing modes, MOVBZ/MOVBS, and the flags MOV leaves alone."""
    s.mov(1, 0x1111)
    s.store(0xf900, 1)
    s.mov(1, 0xf900)
    s.ins("MOV\tR2,[R1+]")
    s.check(2, 0x1111, None)
    s.check(1, 0xf902, None)

    s.mov(1, 0x2222)
    s.store(0xf900, 1)
    s.mov(1, 0xf900)
    s.ins("MOV\tR1,[R1+]")      # overwrites the pointer
    s.check(1, 0x2222, None)

    s.mov(1, 0xf910)
    s.ins("MOV\t[-R1],R1")      # stores the old value at F90E
    s.load(0, 0xf90e)
    s.check(0, 0xf910, None)
    s.check(1, 0xf90e, None)

    s.mov(1, 0x3333)
    s.store(0xf900, 1)
    s.mov(1, 0xf900)
    s.mov(2, 0xf910)
    s.ins("MOV\t[R2],[R1]")
    s.load(0, 0xf910)
    s.check(0, 0x3333, None)

    s.mov(1, 0x4444)
    s.store(0xf902, 1)
    s.mov(1, 0xf900)
    s.ins("MOV\tR0,[R1+#2]")
    s.check(0, 0x4444, None)
    s.mov(0, 0x5555)
    s.mov(1, 0xf900)
    s.ins("MOV\t[R1+#4],R0")
    s.load(2, 0xf904)
    s.check(2, 0x5555, None)

    # MOV Rw,Rw sets N and E from the source and leaves V and C alone.
    s.mov(0, 0x7fff)
    s.ins("ADD\tR0,#1")          # 8000, V and C
    s.mov(1, 0x8000)
    s.ins("MOV\tR0,R1")
    s.check(0, 0x8000, N | V | E)

    s.mov(0, 0x1280)            # RL0 = 80, RH0 = 12
    s.ins("MOVBZ\tR2,RL0")
    s.check(2, 0x0080, 0)
    s.ins("MOVBS\tR2,RL0")
    s.check(2, 0xff80, N)
    s.mov(0, 0x0080)
    s.store(0xf900, 0)
    s.ins("MOVBZ\tR2,0F900H")
    s.check(2, 0x0080, 0)
    s.ins("MOVBS\tR2,0F900H")
    s.check(2, 0xff80, N)
    s.mov(0, 0x0034)
    s.ins("MOVBZ\tR2,RL0")
    s.check(2, 0x0034, 0)


def bits(s):
    """Bit operations on the bit area (FD00, FD02). Each flag check runs with
    R0 preset before the operation, so the flags are the operation's own; the
    memory result is read back afterwards with MOV."""
    # BSET: Z = !prior bit, N = prior bit, E V C cleared.
    s.mov(1, 0)
    s.store(0xfd00, 1)
    s.mov(0, 0x1234)
    s.ins("BSET\t0FD00H.0")
    s.check(0, 0x1234, Z)
    s.load(0, 0xfd00)
    s.check(0, 1, None)

    # BCLR on a set bit: Z = 0, N = 1.
    s.mov(0, 0x1234)
    s.ins("BCLR\t0FD00H.0")
    s.check(0, 0x1234, N)
    s.load(0, 0xfd00)
    s.check(0, 0, None)

    # BMOV and BMOVN: Z = !source, N = source.
    s.mov(1, 1)
    s.store(0xfd00, 1)
    s.mov(1, 0)
    s.store(0xfd02, 1)
    s.mov(0, 0x1234)
    s.ins("BMOV\t0FD02H.0,0FD00H.0")
    s.check(0, 0x1234, N)
    s.load(0, 0xfd02)
    s.check(0, 1, None)
    s.mov(0, 0x1234)
    s.ins("BMOVN\t0FD02H.0,0FD00H.0")
    s.check(0, 0x1234, N)
    s.load(0, 0xfd02)
    s.check(0, 0, None)

    # BAND, BOR, BXOR: Z = NOR, V = OR, C = AND, N = XOR of the two bits.
    s.mov(1, 1)
    s.store(0xfd00, 1)
    s.mov(1, 1)
    s.store(0xfd02, 1)
    s.mov(0, 0x1234)
    s.ins("BAND\t0FD02H.0,0FD00H.0")       # 1 & 1 = 1
    s.check(0, 0x1234, V | C)
    s.load(0, 0xfd02)
    s.check(0, 1, None)
    s.mov(1, 0)
    s.store(0xfd02, 1)
    s.mov(0, 0x1234)
    s.ins("BOR\t0FD02H.0,0FD00H.0")        # 0 | 1 = 1, with the source 1
    s.check(0, 0x1234, V | N)
    s.load(0, 0xfd02)
    s.check(0, 1, None)
    s.mov(0, 0x1234)
    s.ins("BXOR\t0FD02H.0,0FD00H.0")       # 1 ^ 1 = 0
    s.check(0, 0x1234, V | C)
    s.load(0, 0xfd02)
    s.check(0, 0, None)

    # BCMP with both bits set: Z = 0, V = 1, C = 1, N = 0.
    s.mov(1, 1)
    s.store(0xfd00, 1)
    s.store(0xfd02, 1)
    s.mov(0, 0x1234)
    s.ins("BCMP\t0FD00H.0,0FD02H.0")
    s.check(0, 0x1234, V | C)

    # BFLDL and BFLDH: the first immediate is the AND mask, the second the OR
    # data. Z and N follow the word result, V and C are cleared.
    s.mov(1, 0x00ff)
    s.store(0xfd00, 1)
    s.mov(0, 0xffff)
    s.ins("ADD\tR0,#1")                      # sets Z and C
    s.ins("BFLDL\t0FD00H,#0F0H,#0FH")        # low 0xFF -> 0x0F
    s.check(0, 0, 0)
    s.load(0, 0xfd00)
    s.check(0, 0x000f, None)
    s.mov(1, 0xff00)
    s.store(0xfd00, 1)
    s.mov(0, 0xffff)
    s.ins("ADD\tR0,#1")
    s.ins("BFLDH\t0FD00H,#0F0H,#0FH")        # high 0xFF -> 0x0F
    s.check(0, 0, 0)
    s.load(0, 0xfd00)
    s.check(0, 0x0f00, None)


def cc_test(s, jump, expect, setup=None):
    """Branch test. R2 holds the expected outcome before the setup, and the
    taken and not-taken paths each check R2 against their own value. The path
    that actually runs passes; a wrong branch runs the other path and fails.
    Flags are whatever the setup and the jump left (checked as None)."""
    s.ins(f"MOV\tR2,#{1 if expect else 0}")
    if setup:
        setup()
    taken, end = s.new("bt"), s.new("be")
    s.ins(f"{jump},{taken}")
    s.check_r2(0, None)
    s.ins(f"JMPR\tcc_UC,{end}")
    s.lab(taken)
    s.check_r2(1, None)
    s.lab(end)


def f_z(s):
    s.mov(0, 1)
    s.ins("CMP\tR0,#1")


def f_nz(s):
    s.mov(0, 1)
    s.ins("CMP\tR0,#2")


def f_c(s):
    s.mov(0, 0xffff)
    s.ins("ADD\tR0,#1")


def f_nc(s):
    s.mov(0, 1)
    s.ins("ADD\tR0,#1")


def f_v(s):
    s.mov(0, 0x7fff)
    s.ins("ADD\tR0,#1")


def f_n(s):
    s.mov(0, 0x8000)
    s.ins("MOV\tR0,R0")


def f_pos(s):
    s.mov(0, 2)
    s.mov(1, 1)
    s.ins("CMP\tR0,R1")


def f_lt(s):
    s.mov(0, 1)
    s.mov(1, 2)
    s.ins("CMP\tR0,R1")


def branches(s):
    """Every condition code, taken and not taken, and the NET case."""
    cases = [
        ("cc_UC", None, None),
        ("cc_Z", f_z, f_nz),
        ("cc_NZ", f_nz, f_z),
        ("cc_C", f_c, f_nc),
        ("cc_NC", f_nc, f_c),
        ("cc_V", f_v, f_nc),
        ("cc_NV", f_nc, f_v),
        ("cc_N", f_n, f_nc),
        ("cc_NN", f_nc, f_n),
        ("cc_SGT", f_pos, f_lt),
        ("cc_SLE", f_lt, f_pos),
        ("cc_SLT", f_lt, f_pos),
        ("cc_SGE", f_pos, f_lt),
        ("cc_UGT", f_pos, f_c),
        ("cc_ULE", f_c, f_pos),
    ]
    for cc, yes, no in cases:
        if yes is None:
            cc_test(s, f"JMPR\t{cc}", True)     # cc_UC is always taken
            continue
        cc_test(s, f"JMPR\t{cc}", True, lambda: yes(s))
        cc_test(s, f"JMPR\t{cc}", False, lambda: no(s))

    # NET: taken when neither Z nor E is set.
    def net_setup():
        s.mov(0, 2)
        s.mov(1, 1)
        s.ins("CMP\tR0,R1")
    cc_test(s, "JMPR\tcc_NET", True, net_setup)


def bit_jump(s, jump, bit, expect, setup=None, flags_t=None, flags_nt=None,
             mem_after=None):
    """Jump instruction on FD00.0 holding `bit`. R2 is the expected path as in
    cc_test. flags_t and flags_nt are checked on the taken and not-taken paths.
    mem_after, when given, is the word at FD00 after the jump."""
    s.mov(1, bit)
    s.store(0xfd00, 1)           # sets the bit (MOV also sets flags; setup comes after)
    s.ins(f"MOV\tR2,#{1 if expect else 0}")
    if setup:
        setup()
    taken, end = s.new("bjt"), s.new("bje")
    s.ins(f"{jump},{taken}")
    s.check_r2(0, flags_nt)
    s.ins(f"JMPR\tcc_UC,{end}")
    s.lab(taken)
    s.check_r2(1, flags_t)
    s.lab(end)
    if mem_after is not None:
        s.load(0, 0xfd00)
        s.check(0, mem_after, None)


def jumps_bits(s):
    """JB, JNB, JBC and JNBS on FD00.0. JB and JNB leave the flags alone."""
    bit = "0FD00H.0"
    # JB: flags from the CMP (Z) survive the jump on both paths.
    bit_jump(s, f"JB\t{bit}", 1, True, lambda: f_z(s), Z, Z, 1)
    bit_jump(s, f"JB\t{bit}", 0, False, lambda: f_z(s), Z, Z, 0)
    # JNB: no flags touched.
    bit_jump(s, f"JNB\t{bit}", 0, True, None, None, None, 0)
    bit_jump(s, f"JNB\t{bit}", 1, False, None, None, None, 1)
    # JBC: taken on a set bit and clears it. Flags are from the bit:
    # taken (bit 1): Z = 0, N = 1. Not taken (bit 0): Z = 1, N = 0.
    bit_jump(s, f"JBC\t{bit}", 1, True, None, N, Z, 0)
    bit_jump(s, f"JBC\t{bit}", 0, False, None, N, Z, 0)
    # JNBS: taken on a clear bit and sets it. Taken (bit 0): Z = 1.
    # Not taken (bit 1): N = 1.
    bit_jump(s, f"JNBS\t{bit}", 0, True, None, Z, N, 1)
    bit_jump(s, f"JNBS\t{bit}", 1, False, None, Z, N, 1)


def calls(s):
    """CALLA, CALLR, CALLS/RETS, PCALL/RETP, PUSH/POP, SCXT."""
    s.ins("CALLA\tcc_UC,callee")
    s.check(0, 0x1111, None)

    local, after = s.new("cr"), s.new("cra")
    s.ins(f"CALLR\t{local}")
    s.ins(f"JMPR\tcc_UC,{after}")
    s.lab(local)
    s.mov(0, 0x2222)
    s.ins("RET")
    s.lab(after)
    s.check(0, 0x2222, None)

    s.ins("CALLS\t0,segcallee")
    s.check(0, 0x3333, None)

    s.mov(3, 0x99)
    s.ins("PCALL\tR3,pcallee")
    s.check(4, 0x99, None)

    s.mov(0, 0x4242)
    s.ins("PUSH\tR0")
    s.ins("POP\tR1")
    s.check(1, 0x4242, None)
    s.mov(0, 0x1111)
    s.ins("SCXT\tR0,#2222H")
    s.check(0, 0x2222, None)
    s.ins("POP\tR1")
    s.check(1, 0x1111, None)


def subroutines(s):
    """Subroutines used by calls(). They live in the handler section."""
    s.hnd += [
        "callee:",
        "\tMOV\tR0,#1111H",
        "\tRET",
        "segcallee:",
        "\tMOV\tR0,#3333H",
        "\tRETS",
        "pcallee:",
        "\tRETP\tR4",
    ]


def build():
    s = Suite("CORE")
    base(s)
    shifts(s)
    unary_compare(s)
    moves(s)
    bits(s)
    branches(s)
    jumps_bits(s)
    calls(s)
    subroutines(s)
    finish(s)
    after_srst(s)
    return s
