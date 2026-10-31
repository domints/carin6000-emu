"""Peripheral suite: flash, the external bus, PEC, a CAPCOM compare, GPT,
PWM, P8, the ADC, ASC0 loopback, SSC loopback, CAN1 to CAN2, and the RTC.

X-peripherals stay visible: SYSCON.XPEN is set and XPERCON enables CAN1,
CAN2, XRAM1 and the RTC. EINIT is not executed, so the window stays writable.
"""

from .common import Suite, base, finish, after_srst


def nz(s, addr, label):
    """Leave R2 = 1 when the word at addr is not zero. The load sets Z."""
    s.mov(2, 1)
    s.load(0, addr)
    s.ins(f"JMPR\tcc_NZ,{label}")
    s.mov(2, 0)
    s.lab(label)
    s.check(2, 1, None)


def delay(s, n):
    s.mov(1, n)
    lab = s.new("dly")
    s.lab(lab)
    s.ins("SUB\tR1,#1")
    s.ins(f"JMPR\tcc_NZ,{lab}")


def stb(s, addr, value):
    s.mov(1, value & 0xff)
    s.ins(f"MOVB\t0{addr & 0xffff:04X}H,RL1")


def body(s):
    # XPERCON freezes once SYSCON.XPEN is set, so the enables go first.
    s.mov(12, 0x0017)                    # CAN1, CAN2, XRAM1, RTC
    s.ins("EXTR\t#1")
    s.ins("MOV\t0F024H,R12")
    s.sfr_imm(0xff12, 0x0004)
    s.ins("EXTR\t#1")
    s.load(0, 0xf024)
    s.check(0, 0x0017, None)

    # Program one byte of the 128 KB block at 20000H. The command sequence
    # is the ST10 flash unlock, and a program only clears bits.
    stb(s, 0x1554, 0xaa)
    stb(s, 0x0aaa, 0x55)
    stb(s, 0x1554, 0xa0)
    s.mov(1, 0xa5)
    s.ins("EXTS\t#2,#1")
    s.ins("MOVB\t0000H,RL1")
    s.mov(0, 0)
    s.ins("EXTS\t#2,#1")
    s.ins("MOVB\tRL0,0000H")
    s.check(0, 0x00a5, None)
    s.load(0, 0x1554)
    s.check(0, 0x0080, None)

    # ADDRSEL2 = 1008H is the DVD90 window at 100000H. A data read there
    # latches the chip-select status, which the following read returns.
    s.sfr_imm(0xfe1a, 0x1008)
    s.sfr_imm(0xff16, 0x0400)
    s.ins("EXTS\t#10H,#1")
    s.load(0, 0x0000)
    s.load(0, 0x1558)
    s.check(0, 0xff4a, None)

    # One PEC word from F800 to F810, triggered by T0IR.
    s.mov(0, 0x1111)
    s.store(0xf800, 0)
    s.mov(0, 0)
    s.store(0xf810, 0)
    s.mov(0, 0xf800)
    s.store(0xfce0, 0)
    s.mov(0, 0xf810)
    s.store(0xfde0, 0)
    s.sfr_imm(0xfec0, 0x0104)            # count 1, source T0, increment dest
    s.sfr_imm(0xff9c, 0x0080)
    s.ins("NOP")
    s.load(0, 0xf810)
    s.check(0, 0x1111, None)
    s.load(0, 0xfec0)
    s.check(0, 0x0004, None)             # count consumed

    # CC16 compare drives P8.0 when that pin is an output.
    s.sfr_imm(0xff50, 0)
    s.sfr_imm(0xfe50, 0x0010)
    s.sfr_imm(0xfe60, 0x0010)
    s.sfr_imm(0xff20, 0x0002)
    s.sfr_imm(0xffd4, 0)
    s.sfr_imm(0xffd6, 0x0001)
    s.ins("NOP")
    s.load(0, 0xffd4)
    s.check(0, 0x0001, None)

    # P8 as an input returns the external pin, not the latch.
    s.sfr_imm(0xffd6, 0)
    s.sfr_imm(0xffd4, 0x00ff)
    s.load(0, 0xffd4)
    s.check(0, 0x0001, None)

    # T2 runs in timer mode. A short loop is enough for it to leave zero.
    s.sfr_imm(0xfe40, 0)
    s.sfr_imm(0xff40, 0x0040)
    delay(s, 40)
    s.sfr_imm(0xff40, 0)
    nz(s, 0xfe40, "t2nz")

    # PWM channel 0 counts while PWMCON.0 is set.
    s.mov(12, 0)
    s.ins("EXTR\t#1")
    s.ins("MOV\t0F030H,R12")
    s.mov(12, 0x1000)
    s.ins("EXTR\t#1")
    s.ins("MOV\t0F038H,R12")
    s.sfr_imm(0xff30, 0x0001)
    delay(s, 40)
    s.sfr_imm(0xff30, 0)
    s.ins("EXTR\t#1")
    nz(s, 0xf030, "pwmnz")

    # Channel 1 converts to channel*64+7.
    s.sfr_imm(0xffa0, 0x0081)
    delay(s, 80)
    s.load(0, 0xfea0)
    s.check(0, 0x0047, None)

    # ASC0 loopback returns the transmitted byte in S0RBUF.
    s.sfr_imm(0xffb0, 0x4000)
    stb(s, 0xfeb0, 0x41)
    s.mov(0, 0)
    s.ins("MOVB\tRL0,0FEB2H")
    s.check(0, 0x0041, None)

    # SSC loopback echoes SSCTB into SSCRB.
    s.sfr_imm(0xffb2, 0x0003)
    stb(s, 0xf0b0, 0x34)
    s.ins("EXTR\t#1")
    s.load(0, 0xf0b2)
    s.check(0, 0x0034, None)

    # CAN1 transmits one data byte and CAN2's object 0 receives it.
    # Both modules are out of init. The global mask is open.
    s.mov(12, 0x8000)                    # CAN2 object 0: valid, receive
    s.ins("MOV\t0EE10H,R12")
    s.mov(12, 0)
    s.ins("MOV\t0EE16H,R12")             # standard id, receive, dlc 0
    s.ins("MOV\t0EE08H,R12")             # standard global mask
    s.mov(12, 0x005a)
    s.ins("MOV\t0EF18H,R12")             # CAN1 data
    s.mov(12, 0x0011)                    # transmit, one byte
    s.ins("MOV\t0EF16H,R12")
    s.mov(12, 0x8400)                    # valid + transmit request
    s.ins("MOV\t0EF10H,R12")
    s.load(0, 0xee18)
    s.check(0, 0x005a, None)
    s.load(0, 0xef02)
    s.ins("AND\tR0,#0001H")
    s.check(0, 0x0001, None)             # TXOK

    # The RTC counter can be written while RTCOFF is set, and it stays.
    s.mov(12, 0x0080)
    s.ins("MOV\t0EC00H,R12")
    s.mov(12, 0x1234)
    s.ins("MOV\t0EC0EH,R12")
    s.load(0, 0xec0e)
    s.check(0, 0x1234, None)


def build():
    s = Suite("PERIPH")
    base(s)
    body(s)
    finish(s)
    after_srst(s)
    return s
