"""Shared pieces for the ST10F269 test suites.

Each suite is generated as Keil A166 source (see st10_test.py for the build).
The expected values here are the reference model. The encodings come from
A166, not from this file.

Check convention: the expected value follows the CALLA in the code stream.

    MOV   R0,<reg>        ; only when the register is not R0
    CALLA cc_UC,checker
    DW    <value>         ; expected R0
    DW    <flags>         ; expected PSW & 1Fh, or 0FFFFH to skip

The checker reads the PSW that is live at the call (CALLA and MOV do not
change flags), pops the return address to reach the data, and returns past
it. R13 counts checks, R14 passes, R15 failures.
"""

N, C, V, Z, E = 1, 2, 4, 8, 16
MASK = N | C | V | Z | E
SKIP = 0xFFFF


def add_w(a, b, cin=0, sticky=False, oldz=False):
    r = (a + b + cin) & 0x1ffff
    flags = 0
    if r & 0x8000:
        flags |= N
    if (r & 0xffff) == 0 and (not sticky or oldz):
        flags |= Z
    if r > 0xffff:
        flags |= C
    if (~(a ^ b) & (a ^ (r & 0xffff)) & 0x8000):
        flags |= V
    if (b & 0xffff) == 0x8000:
        flags |= E
    return r & 0xffff, flags


def add_b(a, b, cin=0, sticky=False, oldz=False):
    r = (a + b + cin) & 0x1ff
    flags = 0
    if r & 0x80:
        flags |= N
    if (r & 0xff) == 0 and (not sticky or oldz):
        flags |= Z
    if r > 0xff:
        flags |= C
    if (~(a ^ b) & (a ^ (r & 0xff)) & 0x80):
        flags |= V
    if (b & 0xff) == 0x80:
        flags |= E
    return r & 0xff, flags


def sub_w(a, b, cin=0, sticky=False, oldz=False):
    r = (a - b - cin) & 0x1ffff
    flags = 0
    if r & 0x8000:
        flags |= N
    if (r & 0xffff) == 0 and (not sticky or oldz):
        flags |= Z
    if (a & 0xffff) < (b & 0xffff) + cin:
        flags |= C
    if ((a ^ b) & (a ^ (r & 0xffff)) & 0x8000):
        flags |= V
    if (b & 0xffff) == 0x8000:
        flags |= E
    return r & 0xffff, flags


def sub_b(a, b, cin=0, sticky=False, oldz=False):
    r = (a - b - cin) & 0x1ff
    flags = 0
    if r & 0x80:
        flags |= N
    if (r & 0xff) == 0 and (not sticky or oldz):
        flags |= Z
    if (a & 0xff) < (b & 0xff) + cin:
        flags |= C
    if ((a ^ b) & (a ^ (r & 0xff)) & 0x80):
        flags |= V
    if (b & 0xff) == 0x80:
        flags |= E
    return r & 0xff, flags


def logic_w(r, src):
    flags = 0
    if r & 0x8000:
        flags |= N
    if r == 0:
        flags |= Z
    if src == 0x8000:
        flags |= E
    return r & 0xffff, flags


def logic_b(r, src):
    flags = 0
    if r & 0x80:
        flags |= N
    if r == 0:
        flags |= Z
    if (src & 0xff) == 0x80:
        flags |= E
    return r & 0xff, flags


def do_shift(v, count, kind):
    """kind: 0 SHL, 1 SHR, 2 ASHR, 3 ROL, 4 ROR (count is 4 bits)."""
    v &= 0xffff
    count &= 15
    carry = 0
    overflow = False
    for _ in range(count):
        if kind in (1, 2) and carry:
            overflow = True
        if kind == 0:
            carry = 1 if v & 0x8000 else 0
            v = (v << 1) & 0xffff
        elif kind == 3:
            carry = 1 if v & 0x8000 else 0
            v = ((v << 1) | carry) & 0xffff
        elif kind == 4:
            carry = v & 1
            v = (v >> 1) | (0x8000 if carry else 0)
        elif kind == 2:
            carry = v & 1
            v = (v >> 1) | (v & 0x8000)
        else:
            carry = v & 1
            v >>= 1
    flags = 0
    if carry:
        flags |= C
    if kind in (1, 2) and overflow:
        flags |= V
    if v == 0:
        flags |= Z
    if v & 0x8000:
        flags |= N
    return v, flags


def putc(ch):
    """Send one character on ASC0. A166 has no MOVB mem,#data for the SFR
    address, so the character goes through R1 and its low byte is stored.
    ST10 has byte registers only for R0-R7, hence RL1."""
    return [f"\tMOV\tR1,#00{ch:02X}H", "\tMOVB\t0FEB0H,RL1"]


def putc_hnd():
    return putc_lines_hnd()


def putc_lines_hnd():
    return ["\tMOVB\t0FEB0H,RL1"]


class Suite:
    """One suite's A166 text. `main` is the test body, `hnd` holds the
    checker, trap landing and interrupt stubs. Every instruction sits inside
    a PROC block, which A166 requires."""

    main_base = 0x0800   # where the test body starts; the handlers sit at 0200H

    def __init__(self, name):
        self.name = name
        self.model = "167"
        self.main = []
        self.hnd = []
        self.vecs = []       # (vector address, label to JMPA to)
        self.uniq = 0

    def new(self, prefix):
        self.uniq += 1
        return f"{prefix}_{self.uniq}"

    # --- emitters -----------------------------------------------------------
    def ins(self, text):
        self.main.append(f"\t{text}")

    def lab(self, name):
        self.main.append(f"{name}:")

    def mov(self, reg, imm):
        self.ins(f"MOV\tR{reg},#0{imm & 0xffff:04X}H")

    def store(self, addr, reg):
        """MOV mem,Rn (word)."""
        self.ins(f"MOV\t0{addr & 0xffff:04X}H,R{reg}")

    def load(self, reg, addr):
        self.ins(f"MOV\tR{reg},0{addr & 0xffff:04X}H")

    def sfr_imm(self, addr, imm):
        """Store an immediate to a word address. ST10 has no MOV mem,#data
        for long addresses, so go through R12, which the tests never use."""
        self.ins(f"MOV\tR12,#0{imm & 0xffff:04X}H")
        self.ins(f"MOV\t0{addr & 0xffff:04X}H,R12")

    def stack(self):
        # STKOV F600, SP FA00, STKUN FA00 (SFR addresses FE14, FE12, FE16).
        self.sfr_imm(0xfe14, 0xf600)
        self.sfr_imm(0xfe12, 0xfa00)
        self.sfr_imm(0xfe16, 0xfa00)

    def recover(self):
        """Clear PSW (trap cleanup) and reset the stack."""
        self.sfr_imm(0xff10, 0)
        self.stack()

    def arm(self, label):
        """Point the trap landing at `label` and clear the trap flag F906."""
        self.ins(f"MOV\tR0,#{label}")
        self.ins("MOV\t0F904H,R0")
        self.ins("MOV\tR1,#0")
        self.ins("MOV\t0F906H,R1")

    def check(self, reg, value, flags=None):
        """Check Rreg against `value`. flags=None skips the PSW check."""
        if reg != 0:
            self.ins(f"MOV\tR0,R{reg}")
        self.ins("CALLA\tcc_UC,checker")
        self.main.append(f"\tDW\t0{value & 0xffff:04X}H")
        self.main.append(f"\tDW\t0{(SKIP if flags is None else flags & MASK):04X}H")

    def check_r2(self, value, flags=None):
        """Like check() but compares R2 and emits no MOV, so the flags are
        exactly those the test left. Used where the flags are under test."""
        self.ins("CALLA\tcc_UC,checker2")
        self.main.append(f"\tDW\t0{value & 0xffff:04X}H")
        self.main.append(f"\tDW\t0{(SKIP if flags is None else flags & MASK):04X}H")

    def trap_block(self, label):
        """Trap continuation: F906 must be 1 (the landing set it), then
        the stack is reset and PSW cleared."""
        self.lab(label)
        self.recover()
        self.load(0, 0xf906)
        self.check(0, 1, None)

    def check_mem(self, addr, value, flags=None):
        self.load(0, addr)
        self.check(0, value, flags)

    def prints(self, text):
        for ch in text:
            for line in putc(ord(ch)):
                self.ins(line.strip())

    def bit_label(self, name):
        self.lab(name)

    # --- output ---------------------------------------------------------------
    def emit(self):
        out = [
            f"$MOD{self.model}",
            "$CASE",
            "$SEGMENTED",
            f"NAME {self.name}",
            "",
        ]
        for addr, target in sorted(self.vecs):
            sec = f"VEC{addr:04X}"
            out += [
                f"{sec} SECTION CODE AT 0{addr:04X}H",
                f"{sec}_P PROC NEAR",
                f"\tJMPA\tcc_UC,{target}",
                f"{sec}_P ENDP",
                f"{sec} ENDS",
                "",
            ]
        out += [
            "HNDSEC SECTION CODE AT 0200H",
            "HND_P PROC NEAR",
            *self.hnd,
            "HND_P ENDP",
            "HNDSEC ENDS",
            "",
            f"MAINSEC SECTION CODE AT 0{self.main_base:04X}H",
            "MAIN_P PROC NEAR",
            *self.main,
            "MAIN_P ENDP",
            "MAINSEC ENDS",
            "",
            "\tEND",
        ]
        return "\n".join(out) + "\n"



def checker_lines(label, reg):
    """Checker that compares Rreg against the DW data after the CALLA.
    "checker" compares R0; "checker2" compares R2 and is used by branch tests
    that must not change the flags before the CALLA (see core.py)."""
    r = f"R{reg}"
    bad, ok = f"{label}_bad", f"{label}_ok"
    return [
        f"{label}:",
        "\tPUSH\tPSW",
        "\tPOP\tR5",          # R5 = PSW at the call
        "\tPOP\tR6",          # R6 = address of the DW data
        "\tADD\tR13,#1",
        "\tMOV\tR3,[R6]",     # expected value
        "\tMOV\tR4,[R6+#2]",  # expected flags or FFFF
        "\tADD\tR6,#4",
        "\tPUSH\tR6",         # RET returns past the data
        f"\tCMP\t{r},R3",
        f"\tJMPR\tcc_NZ,{bad}",
        "\tCMP\tR4,#0FFFFH",
        f"\tJMPR\tcc_Z,{ok}",
        "\tAND\tR5,#1FH",
        "\tCMP\tR5,R4",
        f"\tJMPR\tcc_NZ,{bad}",
        f"{ok}:",
        "\tADD\tR14,#1",
        "\tRET",
        f"{bad}:",
        "\tADD\tR15,#1",
        f"\tMOV\tR6,{r}",     # R6 actual, R7 expected, R5 PSW
        "\tMOV\tR7,R3",
        *putc(0x46),   # F
        "\tMOV\tR2,R13",
        "\tCALLA\tcc_UC,phex",
        *putc(0x3D),   # =
        "\tMOV\tR2,R6",
        "\tCALLA\tcc_UC,phex",
        *putc(0x2F),   # /
        "\tMOV\tR2,R7",
        "\tCALLA\tcc_UC,phex",
        *putc(0x20),
        "\tMOV\tR2,R5",
        "\tCALLA\tcc_UC,phex",
        *putc(0x0A),
        "\tRET",
    ]

def base(s, walk=False):
    """Reset, traps, NMI, checker, printers, start block.

    Vectors used by every suite: reset (0000), NMI (0008), the trap landing
    (0010 STKOF, 0014 STKUN, 0018 NMI-less class B, 0028 class B fault).
    """
    s.vecs += [(0x0000, "start"), (0x0008, "nmi"), (0x0010, "land"),
               (0x0014, "land"), (0x0018, "land"), (0x0028, "land")]

    # ---- checkers -----------------------------------------------------------
    s.hnd += checker_lines("checker", 0) + checker_lines("checker2", 2)

    # ---- hex printer: R2 as four digits, clobbers R1 -----------------------
    s.hnd.append("phex:")
    for shift in (12, 8, 4, 0):
        s.hnd += [
            "\tMOV\tR1,R2",
            *([f"\tSHR\tR1,#{shift}"] if shift else []),
            "\tAND\tR1,#0FH",
            "\tCMP\tR1,#10",
            f"\tJMPR\tcc_NC,pa{shift}",
            "\tADD\tR1,#30H",
            f"\tJMPR\tcc_UC,po{shift}",
            f"pa{shift}:",
            "\tADD\tR1,#37H",
            f"po{shift}:",
            *putc_hnd(),
        ]
    s.hnd.append("\tRET")

    # ---- landing for traps and NMI; F904 holds the continuation ------------
    s.hnd += [
        "land:",
        "nmi:",
        "\tMOV\tR1,#1",
        "\tMOV\t0F906H,R1",
        # JMPI cc, [Rw] loads the word at Rw. F904 holds the continuation,
        # so R0 must point at F904, not hold the continuation itself.
        "\tMOV\tR0,#0F904H",
        "\tJMPI\tcc_UC,[R0]",
    ]

    # ---- start block: the first code in the main section --------------------
    # A software reset leaves F600 = 5A, which sends the restart to the summary.
    assert not s.main, "base() must run before the test body"
    s.main = [
        "start:",
        "\tMOV\tR0,0F600H",
        "\tCMP\tR0,#005AH",
        "\tJMPR\tcc_NZ,no_srst",
        "\tJMPA\tcc_UC,after_srst",
        "no_srst:",
        "\tDISWDT",
        "\tMOV\tR12,#0F600H",
        "\tMOV\t0FE14H,R12",
        "\tMOV\tR12,#0FA00H",
        "\tMOV\t0FE12H,R12",
        "\tMOV\t0FE16H,R12",
        "\tMOV\tR13,#0",
        "\tMOV\tR14,#0",
        "\tMOV\tR15,#0",
    ]


def finish(s):
    """Store the counts, set the SRST flag, reset. The restart sees the flag
    and prints the summary (after_srst)."""
    s.ins("MOV\t0F910H,R14")
    s.ins("MOV\t0F912H,R15")
    s.ins("MOV\t0F914H,R13")
    s.ins("MOV\tR12,#005AH")
    s.ins("MOV\t0F600H,R12")
    s.ins("SRST")
    s.lab("after_finish")
    s.ins("JMPR\tcc_UC,after_finish")


def after_srst(s):
    """The reset path that prints the summary and spins."""
    s.lab("after_srst")
    s.ins("DISWDT")
    s.stack()
    s.ins("MOV\tR14,0F910H")
    s.ins("MOV\tR15,0F912H")
    s.ins("MOV\tR13,0F914H")
    s.prints(f"ST10TEST {s.name} done pass=")
    s.ins("MOV\tR2,R14")
    s.ins("CALLA\tcc_UC,phex")
    s.prints(" fail=")
    s.ins("MOV\tR2,R15")
    s.ins("CALLA\tcc_UC,phex")
    s.prints(" calls=")
    s.ins("MOV\tR2,R13")
    s.ins("CALLA\tcc_UC,phex")
    for line in putc(0x0A):
        s.ins(line.strip())
    s.lab("spin_done")
    s.ins("JMPR\tcc_UC,spin_done")
