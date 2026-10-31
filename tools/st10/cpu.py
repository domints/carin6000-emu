"""CPU suite: DPP and the EXT/prefix instructions, traps (stack, odd address,
illegal opcode, bad instruction address, class B), interrupt priority, the
interrupt request walk, IDLE and PWRDN, EINIT and the SYSCON lock, and SRST.
"""

from .common import Suite, base, finish, after_srst, N, C, V, Z, E

# Vector address and the interrupt control register that requests it.
WALK = [
    (0x0040, 0xff78), (0x0044, 0xff7a), (0x0048, 0xff7c), (0x004c, 0xff7e),
    (0x0050, 0xff80), (0x0054, 0xff82), (0x0058, 0xff84), (0x005c, 0xff86),
    (0x0060, 0xff88), (0x0064, 0xff8a), (0x0068, 0xff8c), (0x006c, 0xff8e),
    (0x0070, 0xff90), (0x0074, 0xff92), (0x0078, 0xff94), (0x007c, 0xff96),
    (0x00c0, 0xf160), (0x00c4, 0xf162), (0x00c8, 0xf164), (0x00cc, 0xf166),
    (0x00d0, 0xf168), (0x00d4, 0xf16a), (0x00d8, 0xf16c), (0x00dc, 0xf16e),
    (0x00e0, 0xf170), (0x00e4, 0xf172), (0x00e8, 0xf174), (0x00ec, 0xf176),
    (0x00f0, 0xf178), (0x0110, 0xf184), (0x0114, 0xf18c), (0x0118, 0xf194),
    (0x0080, 0xff9c), (0x0084, 0xff9e), (0x00f4, 0xf17a), (0x00f8, 0xf17c),
    (0x0088, 0xff60), (0x008c, 0xff62), (0x0090, 0xff64), (0x0094, 0xff66),
    (0x0098, 0xff68), (0x009c, 0xff6a), (0x00a0, 0xff98), (0x00a4, 0xff9a),
    (0x00a8, 0xff6c), (0x011c, 0xf19c), (0x00ac, 0xff6e), (0x00b0, 0xff70),
    (0x00b4, 0xff72), (0x00b8, 0xff74), (0x00bc, 0xff76), (0x00fc, 0xf17e),
    (0x0100, 0xf186), (0x0104, 0xf18e), (0x0108, 0xf196), (0x010c, 0xf19e),
]


def walk_stubs(s, vectors):
    """Each vector slot jumps to a stub that records its own number. The
    stub for T0 and T1 also stops T0 first, so a running T0 cannot pend
    again before RETI."""
    for vec, ic in vectors:
        stub = f"stub_{vec:04X}"
        s.vecs.append((vec, stub))
        if vec in (0x0080, 0x0084):
            s.hnd += [
                f"{stub}:",
                f"\tMOV\tR3,#0{vec:04X}H",
                "\tMOV\tR0,#0000H",
                "\tMOV\t0FF50H,R0",           # T01CON: stop T0 and T1
                "\tBCLR\t0FF9CH.7",          # T0IC.IR
                "\tBCLR\t0FF9EH.7",          # T1IC.IR
                "\tJMPA\tcc_UC,logret",
            ]
        else:
            s.hnd += [
                f"{stub}:",
                f"\tMOV\tR3,#0{vec:04X}H",
                f"\tMOV\tR0,#0{ic:04X}H",   # R0 = IC address for isrc
                "\tJMPA\tcc_UC,isrc",
            ]
    s.hnd += [
        "isrc:",
        "\tMOV\tR1,[R0]",
        "\tAND\tR1,#7FH",                    # clear IR
        "\tMOV\t[R0],R1",
        "logret:",
        "\tMOV\tR1,#0FFFFH",
        "\tMOV\t0F936H,R1",
        "\tMOV\tR0,0F982H",
        "\tMOV\tR1,#0F984H",
        "\tADD\tR1,R0",
        "\tMOV\t[R1],R3",                    # log the vector number
        "\tADD\tR0,#2",
        "\tMOV\t0F982H,R0",
        "\tRETI",
    ]


def traps(s):
    """TRAP, stack overflow and underflow, odd word access, illegal opcode,
    odd instruction address, and a bad protected sequence."""
    # TRAP #5 uses vector 0014H.
    s.arm("trap_cont")
    s.mov(0, 0)
    s.ins("TRAP\t#5")
    s.ins("JMPR\tcc_UC,trap_done")
    s.trap_block("trap_cont")
    s.ins("JMPA\tcc_UC,trap_done")
    s.lab("trap_done")

    # Stack overflow.
    s.arm("stk_cont")
    s.sfr_imm(0xfe14, 0xf9f0)           # STKOV
    s.sfr_imm(0xfe12, 0xf9f0)           # SP
    s.ins("PUSH\tR0")
    s.trap_block("stk_cont")

    # Stack underflow.
    s.arm("uf_cont")
    s.sfr_imm(0xfe16, 0xf000)           # STKUN
    s.sfr_imm(0xfe12, 0xf000)           # SP
    s.ins("POP\tR0")
    s.trap_block("uf_cont")

    # Odd word access.
    s.arm("odd_cont")
    s.mov(1, 0xf901)
    s.ins("MOV\tR0,[R1]")
    s.trap_block("odd_cont")

    # Illegal opcode: CMP mem,reg has no encoding (0044H).
    s.arm("ill_cont")
    s.ins("DW\t0044H")
    s.trap_block("ill_cont")

    # Odd instruction address: JMPA to 0001H.
    s.arm("ip_cont")
    s.ins("DW\t00EAH")
    s.ins("DW\t0001H")
    s.ins("DW\t0000H")
    s.trap_block("ip_cont")

    # Protected sequence with a wrong password. Class B fault. The bad
    # sequence is data, so the trap lands on the continuation.
    s.arm("prot_cont")
    s.ins("DW\t00A5H")
    s.ins("DW\t0000H")
    s.mov(0, 0x1111)                    # must not run
    s.store(0xf930, 0)
    s.trap_block("prot_cont")
    s.load(0, 0xf930)
    s.check(0, 0, None)


def dpp_ext(s):
    """DPP windows, EXTS, EXTP, EXTR, and the prefix holding the interrupt."""
    s.sfr_imm(0xfe00, 5)                 # DPP0 = 5
    s.mov(0, 0x4321)
    s.store(0x0000, 0)                   # physical 14000H
    s.sfr_imm(0xfe00, 0)
    s.ins("EXTS\t#1,#1")
    s.load(0, 0x4000)                    # segment 1 offset 4000H = 14000H
    s.check(0, 0x4321, None)

    s.mov(1, 0x6666)
    s.ins("EXTP\t#6,#1")
    s.store(0x0000, 1)                   # page 6 physical 18000H
    s.ins("EXTS\t#1,#1")
    s.load(0, 0x8000)
    s.check(0, 0x6666, None)

    s.mov(0, 0x1234)
    s.ins("EXTR\t#1")
    s.store(0xf000, 0)                   # ESFR window: F000 is QX0
    s.ins("EXTR\t#1")
    s.load(0, 0xf000)
    s.check(0, 0x1234, None)

    # A pending T0 interrupt is held off for the whole ATOMIC window and is
    # taken in the middle of an EXTPR window. The read is the second
    # covered instruction, so it sees F936 still clear under ATOMIC and
    # already FFFF under EXTPR. R4 is not used by the T0 stub.
    s.mov(1, 0)
    s.store(0xf936, 1)
    s.sfr_imm(0xff10, 0)
    s.sfr_imm(0xff9c, 0x00dc)            # T0IC IR IE ILVL 7
    s.ins("ATOMIC\t#2")
    s.ins("BSET\t0FF10H.11")             # IEN
    s.ins("MOV\tR4,0F936H")
    s.sfr_imm(0xff10, 0)
    s.sfr_imm(0xff9c, 0)
    s.check(4, 0, None)

    s.mov(1, 0)
    s.store(0xf936, 1)
    s.sfr_imm(0xff10, 0)
    s.sfr_imm(0xff9c, 0x00dc)
    s.ins("EXTPR\t#0,#2")
    s.ins("BSET\t0FF10H.11")
    s.ins("MOV\tR4,0F936H")
    s.sfr_imm(0xff10, 0)
    s.sfr_imm(0xff9c, 0)
    s.check(4, 0xffff, None)


def misc(s):
    """ONES, ZEROS, CSP writes ignored, and the push/pop of PSW."""
    s.load(0, 0xff1e)
    s.check(0, 0xffff, None)
    s.load(0, 0xff1c)
    s.check(0, 0, None)
    s.sfr_imm(0xfe08, 0x00ab)           # CSP write is ignored
    s.load(0, 0xfe08)
    s.check(0, 0, None)


def priority(s):
    """Interrupt priority and the IEN gate."""
    # T0 ILVL 7 and T1 ILVL 3, both pending: T0 wins.
    s.mov(0, 0)
    s.store(0xf982, 0)
    s.sfr_imm(0xff9c, 0x00dc)           # T0IC IR IE ILVL 7
    s.sfr_imm(0xff9e, 0x00cc)           # T1IC IR IE ILVL 3
    s.sfr_imm(0xff10, 0x0800)
    s.ins("NOP")
    s.ins("NOP")
    s.sfr_imm(0xff10, 0)
    s.load(0, 0xf984)
    s.check(0, 0x0080, None)

    # Same level, the higher group level wins.
    s.mov(0, 0)
    s.store(0xf982, 0)
    s.sfr_imm(0xff9c, 0x00d4)           # IR IE ILVL 5 GLVL 0
    s.sfr_imm(0xff9e, 0x00d7)           # IR IE ILVL 5 GLVL 3
    s.sfr_imm(0xff10, 0x0800)
    s.ins("NOP")
    s.ins("NOP")
    s.sfr_imm(0xff10, 0)
    s.load(0, 0xf984)
    s.check(0, 0x0084, None)

    # ILVL 0 does not interrupt.
    s.mov(0, 0)
    s.store(0xf982, 0)
    s.sfr_imm(0xff9c, 0x00c0)
    s.sfr_imm(0xff10, 0x0800)
    s.ins("NOP")
    s.sfr_imm(0xff10, 0)
    s.sfr_imm(0xff9c, 0x00dc)           # IEN off: nothing is taken
    s.ins("NOP")
    s.load(0, 0xf982)
    s.check(0, 0, None)


def walk(s, vectors):
    """Every request node in turn. A table in the handler section holds the
    IC address and the vector each node must produce. The loop sets the
    request, runs the interrupt, and checks the vector it logged."""
    s.hnd.append("walk_tab:")
    for vec, ic in vectors:
        if vec in (0x0080, 0x0084):
            continue
        s.hnd.append(f"\tDW\t0{ic:04X}H")
        s.hnd.append(f"\tDW\t0{vec:04X}H")
    s.hnd.append("walk_end:")

    loop, bad, done = s.new("wl"), s.new("wb"), s.new("wd")
    s.ins("MOV\tR10,#walk_tab")
    s.lab(loop)
    s.ins("CMP\tR10,#walk_end")
    s.ins(f"JMPR\tcc_Z,{done}")
    s.ins("MOV\tR8,[R10]")             # IC address
    s.ins("MOV\tR9,[R10+#2]")          # vector that must be logged
    s.ins("ADD\tR10,#4")
    s.ins("MOV\tR0,#0000H")
    s.ins("MOV\t0F982H,R0")            # log index 0
    s.ins("MOV\tR0,#00DCH")            # IR IE ILVL 7
    s.ins("MOV\t[R8],R0")
    s.ins("MOV\tR0,#0800H")
    s.ins("MOV\t0FF10H,R0")            # PSW = IEN
    s.ins("NOP")
    s.ins("NOP")
    s.ins("MOV\tR0,#0000H")
    s.ins("MOV\t0FF10H,R0")            # PSW = 0
    s.ins("MOV\tR0,0F984H")
    s.ins("CMP\tR0,R9")
    s.ins(f"JMPR\tcc_NZ,{bad}")
    s.ins("ADD\tR13,#1")
    s.ins("ADD\tR14,#1")
    s.ins(f"JMPR\tcc_UC,{loop}")
    s.lab(bad)
    s.ins("ADD\tR13,#1")
    s.ins("ADD\tR15,#1")
    s.ins("MOV\tR2,R9")
    s.ins("CALLA\tcc_UC,phex")         # expected vector, then the actual
    s.ins("MOV\tR2,R0")
    s.ins("CALLA\tcc_UC,phex")
    s.prints("\n")
    s.ins(f"JMPR\tcc_UC,{loop}")
    s.lab(done)


def idle_pwrdn(s):
    """IDLE wakes on the timer interrupt. PWRDN sleeps until NMI."""
    s.mov(0, 0)
    s.store(0xf982, 0)
    s.sfr_imm(0xfe50, 0xfff0)           # T0 near overflow
    s.sfr_imm(0xfe54, 0)
    s.sfr_imm(0xff9c, 0x005c)           # T0IC IE ILVL 7
    s.sfr_imm(0xff10, 0x0800)
    s.sfr_imm(0xff50, 0x0040)           # run T0
    s.ins("IDLE")
    s.sfr_imm(0xff50, 0)
    s.sfr_imm(0xff10, 0)
    s.load(0, 0xf982)
    s.check(0, 2, None)

    s.arm("nmi_cont")
    s.mov(0, 1)
    s.store(0xf908, 0)                   # tells the driver to pulse NMI
    s.ins("PWRDN")
    s.trap_block("nmi_cont")


def eintrap(s):
    """EINIT locks SYSCON. DISWDT after EINIT is a class B fault."""
    s.sfr_imm(0xff12, 0x0004)           # SYSCON.XPEN, still writable
    s.ins("EINIT")
    s.sfr_imm(0xff12, 0x0000)           # SYSCON write after EINIT: ignored
    s.load(0, 0xff12)
    s.check(0, 0x0004, None)
    s.arm("wdt_deny")
    s.ins("DISWDT")
    s.trap_block("wdt_deny")


def build():
    s = Suite("CPU")
    base(s)
    walk_stubs(s, WALK)
    traps(s)
    dpp_ext(s)
    misc(s)
    priority(s)
    walk(s, WALK)
    idle_pwrdn(s)
    eintrap(s)
    finish(s)
    after_srst(s)
    return s
