// license:BSD-3-Clause
// copyright-holders:The MAME Team
/*******************************************************************

    Siemens / Infineon C166 disassembler.

    Classic encodings only. The MAC extension is printed as data
    until the interpreter grows it.

*******************************************************************/

#include "emu.h"
#include "c166dasm.h"


namespace {

char const *const CC[16] = {
	"uc", "net", "z", "nz", "v", "nv", "n", "nn",
	"c", "nc", "sgt", "sle", "slt", "sge", "ugt", "ule"
};

char const *const ALU[8] = { "add", "addc", "sub", "subc", "cmp", "xor", "and", "or" };

char const *rw_name(unsigned n)
{
	static char const *const names[16] = {
		"r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
		"r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"
	};
	return names[n & 15];
}

std::string rb_name(unsigned nib)
{
	return util::string_format("r%u%c", (nib >> 1) & 7, (nib & 1) ? 'h' : 'l');
}

std::string reg_w(uint8_t rr)
{
	if ((rr & 0xf0) == 0xf0)
		return rw_name(rr & 15);
	return util::string_format("sfr:%02X", rr);
}

std::string reg_b(uint8_t rr)
{
	if ((rr & 0xf0) == 0xf0)
		return rb_name(rr & 15);
	return util::string_format("sfrb:%02X", rr);
}

} // anonymous namespace


u32 c166_disassembler::opcode_alignment() const
{
	return 2;
}

offs_t c166_disassembler::disassemble(std::ostream &stream, offs_t pc, const data_buffer &opcodes, const data_buffer &params)
{
	(void)params;
	u8 const op = opcodes.r8(pc);
	u8 const b1 = opcodes.r8(pc + 1);
	u8 const b2 = opcodes.r8(pc + 2);
	u8 const b3 = opcodes.r8(pc + 3);
	auto u16at = [&](unsigned at)
	{
		return u16(opcodes.r8(pc + at) | (opcodes.r8(pc + at + 1) << 8));
	};
	u32 flags = SUPPORTED;
	u32 len = 2;
	unsigned const alu = op >> 4;
	unsigned const form = op & 15;

	if (alu <= 7 && form <= 9 && !(alu == 4 && (form == 4 || form == 5)))
	{
		bool const byteop = form & 1;
		char const *name = ALU[alu];
		if (form <= 1)
		{
			if (byteop)
				util::stream_format(stream, "%sb %s, %s", name, rb_name(b1 >> 4), rb_name(b1 & 15));
			else
				util::stream_format(stream, "%s %s, %s", name, rw_name(b1 >> 4), rw_name(b1 & 15));
		}
		else if (form == 8 || form == 9)
		{
			unsigned const low = b1 & 15;
			std::string src = (low < 8) ? util::string_format("#%X", low) : util::string_format("[%s%s]", rw_name(low & 3), (low >= 12) ? "+" : "");
			if (byteop)
				util::stream_format(stream, "%sb %s, %s", name, rb_name(b1 >> 4), src);
			else
				util::stream_format(stream, "%s %s, %s", name, rw_name(b1 >> 4), src);
		}
		else
		{
			len = 4;
			u16 const extra = u16at(2);
			std::string dest = byteop ? reg_b(b1) : reg_w(b1);
			if (form == 6 || form == 7)
				util::stream_format(stream, "%s%s %s, #%04X", name, byteop ? "b" : "", dest, byteop ? (extra & 0xff) : extra);
			else if (form == 2 || form == 3)
				util::stream_format(stream, "%s%s %s, %04X", name, byteop ? "b" : "", dest, extra);
			else
				util::stream_format(stream, "%s%s %04X, %s", name, byteop ? "b" : "", extra, dest);
		}
		return len | flags;
	}

	if (form == 0x0d)
	{
		util::stream_format(stream, "jmpr %s, %04X", CC[alu], (pc + 2 + 2 * s8(b1)) & 0xffffff);
		return 2 | flags | STEP_COND;
	}
	if (form == 0x0e || form == 0x0f)
	{
		util::stream_format(stream, "%s %02X.%X", (form == 0x0f) ? "bset" : "bclr", b1, alu);
		return 2 | flags;
	}

	switch (op)
	{
	case 0x0a:
	case 0x1a:
		util::stream_format(stream, "%s %02X, #%02X, #%02X", (op == 0x0a) ? "bfldl" : "bfldh", b1, b2, b3);
		return 4 | flags;
	case 0x2a: case 0x3a: case 0x4a: case 0x5a: case 0x6a: case 0x7a:
	{
		char const *name = (op == 0x2a) ? "bcmp" : (op == 0x3a) ? "bmovn" : (op == 0x4a) ? "bmov" : (op == 0x5a) ? "bor" : (op == 0x6a) ? "band" : "bxor";
		util::stream_format(stream, "%s %02X.%X, %02X.%X", name, b2, b3 & 15, b1, b3 >> 4);
		return 4 | flags;
	}
	case 0x8a: case 0x9a: case 0xaa: case 0xba:
	{
		char const *name = (op == 0x8a) ? "jb" : (op == 0x9a) ? "jnb" : (op == 0xaa) ? "jbc" : "jnbs";
		util::stream_format(stream, "%s %02X.%X, %04X", name, b1, b3 >> 4, (pc + 4 + 2 * s8(b2)) & 0xffffff);
		return 4 | flags | STEP_COND;
	}
	case 0x0b:
	case 0x1b:
		util::stream_format(stream, "%s %s, %s", (op == 0x0b) ? "mul" : "mulu", rw_name(b1 >> 4), rw_name(b1 & 15));
		return 2 | flags;
	case 0x2b:
		util::stream_format(stream, "prior %s, %s", rw_name(b1 >> 4), rw_name(b1 & 15));
		return 2 | flags;
	case 0x4b: case 0x5b: case 0x6b: case 0x7b:
		util::stream_format(stream, "%s %s", (op == 0x4b) ? "div" : (op == 0x5b) ? "divu" : (op == 0x6b) ? "divl" : "divlu", rw_name(b1 & 15));
		return 2 | flags;
	case 0x0c: case 0x2c: case 0x4c: case 0x6c: case 0xac:
		util::stream_format(stream, "%s %s, %s", (op == 0x0c) ? "rol" : (op == 0x2c) ? "ror" : (op == 0x4c) ? "shl" : (op == 0x6c) ? "shr" : "ashr", rw_name(b1 >> 4), rw_name(b1 & 15));
		return 2 | flags;
	case 0x1c: case 0x3c: case 0x5c: case 0x7c: case 0xbc:
		util::stream_format(stream, "%s %s, #%X", (op == 0x1c) ? "rol" : (op == 0x3c) ? "ror" : (op == 0x5c) ? "shl" : (op == 0x7c) ? "shr" : "ashr", rw_name(b1 & 15), b1 >> 4);
		return 2 | flags;
	case 0x80: case 0x90: case 0xa0: case 0xb0:
		util::stream_format(stream, "%s %s, #%X", (op == 0xa0) ? "cmpd1" : (op == 0xb0) ? "cmpd2" : (op == 0x80) ? "cmpi1" : "cmpi2", rw_name(b1 & 15), b1 >> 4);
		return 2 | flags;
	case 0x86: case 0x96: case 0xa6: case 0xb6:
		util::stream_format(stream, "%s %s, #%04X", (op == 0xa6) ? "cmpd1" : (op == 0xb6) ? "cmpd2" : (op == 0x86) ? "cmpi1" : "cmpi2", rw_name(b1 & 15), u16at(2));
		return 4 | flags;
	case 0x82: case 0x92: case 0xa2: case 0xb2:
		util::stream_format(stream, "%s %s, %04X", (op == 0xa2) ? "cmpd1" : (op == 0xb2) ? "cmpd2" : (op == 0x82) ? "cmpi1" : "cmpi2", rw_name(b1 & 15), u16at(2));
		return 4 | flags;
	case 0x81: case 0x91: case 0xa1: case 0xb1:
		if (op == 0x81 || op == 0x91)
			util::stream_format(stream, "%s %s", (op == 0x81) ? "neg" : "cpl", rw_name(b1 >> 4));
		else
			util::stream_format(stream, "%s %s", (op == 0xa1) ? "negb" : "cplb", rb_name(b1 >> 4));
		return 2 | flags;
	case 0xa5: stream << "diswdt"; return 4 | flags;
	case 0xb5: stream << "einit"; return 4 | flags;
	case 0x87: stream << "idle"; return 4 | flags;
	case 0x97: stream << "pwrdn"; return 4 | flags;
	case 0xa7: stream << "srvwdt"; return 4 | flags;
	case 0xb7: stream << "srst"; return 4 | flags;
	case 0xcc: stream << "nop"; return 2 | flags;
	case 0xd1:
		util::stream_format(stream, "%s #%u", (b1 & 0x80) ? "extr" : "atomic", ((b1 >> 4) & 3) + 1);
		return 2 | flags;
	case 0xdc:
	{
		unsigned const kind = b1 >> 6;
		char const *name = (kind == 0) ? "exts" : (kind == 1) ? "extp" : (kind == 2) ? "extsr" : "extpr";
		util::stream_format(stream, "%s %s, #%u", name, rw_name(b1 & 15), ((b1 >> 4) & 3) + 1);
		return 2 | flags;
	}
	case 0xd7:
	{
		unsigned const kind = b1 >> 6;
		bool const seg = (kind & 1) == 0;
		unsigned const imm = seg ? b2 : u16at(2);
		char const *name = (kind == 0) ? "exts" : (kind == 1) ? "extp" : (kind == 2) ? "extsr" : "extpr";
		util::stream_format(stream, "%s #%X, #%u", name, imm, ((b1 >> 4) & 3) + 1);
		return 4 | flags;
	}
	case 0xcb: stream << "ret"; return 2 | flags | STEP_OUT;
	case 0xdb: stream << "rets"; return 2 | flags | STEP_OUT;
	case 0xfb: stream << "reti"; return 2 | flags | STEP_OUT;
	case 0xbb:
		util::stream_format(stream, "callr %04X", (pc + 2 + 2 * s8(b1)) & 0xffffff);
		return 2 | flags | STEP_OVER;
	case 0xca:
	case 0xea:
		util::stream_format(stream, "%s %s, %04X", (op == 0xca) ? "calla" : "jmpa", CC[b1 >> 4], u16at(2));
		return 4 | flags | ((op == 0xca) ? STEP_OVER : STEP_COND);
	case 0xda:
	case 0xfa:
		util::stream_format(stream, "%s %02X:%04X", (op == 0xda) ? "calls" : "jmps", b1, u16at(2));
		return 4 | flags | ((op == 0xda) ? STEP_OVER : 0);
	case 0xab:
	case 0x9c:
		util::stream_format(stream, "%s %s, [%s]", (op == 0xab) ? "calli" : "jmpi", CC[b1 >> 4], rw_name(b1 & 15));
		return 2 | flags | ((op == 0xab) ? STEP_OVER : STEP_COND);
	case 0x9b:
		util::stream_format(stream, "trap #%02X", b1 >> 1);
		return 2 | flags | STEP_OVER;
	case 0xe2:
		util::stream_format(stream, "pcall %s, %04X", reg_w(b1), u16at(2));
		return 4 | flags | STEP_OVER;
	case 0xeb:
		util::stream_format(stream, "retp %s", reg_w(b1));
		return 2 | flags | STEP_OUT;
	case 0xec:
		util::stream_format(stream, "push %s", reg_w(b1));
		return 2 | flags;
	case 0xfc:
		util::stream_format(stream, "pop %s", reg_w(b1));
		return 2 | flags;
	case 0xc6:
		util::stream_format(stream, "scxt %s, #%04X", reg_w(b1), u16at(2));
		return 4 | flags;
	case 0xd6:
		util::stream_format(stream, "scxt %s, %04X", reg_w(b1), u16at(2));
		return 4 | flags;
	case 0xf0:
		util::stream_format(stream, "mov %s, %s", rw_name(b1 >> 4), rw_name(b1 & 15));
		return 2 | flags;
	case 0xe0:
		util::stream_format(stream, "mov %s, #%X", rw_name(b1 & 15), b1 >> 4);
		return 2 | flags;
	case 0xe6:
		util::stream_format(stream, "mov %s, #%04X", reg_w(b1), u16at(2));
		return 4 | flags;
	case 0xf2:
		util::stream_format(stream, "mov %s, %04X", reg_w(b1), u16at(2));
		return 4 | flags;
	case 0xf6:
		util::stream_format(stream, "mov %04X, %s", u16at(2), reg_w(b1));
		return 4 | flags;
	case 0xa8: case 0x98:
		util::stream_format(stream, "mov %s, [%s%s]", rw_name(b1 >> 4), rw_name(b1 & 15), (op == 0x98) ? "+" : "");
		return 2 | flags;
	case 0xb8: case 0x88:
		util::stream_format(stream, "mov [%s%s], %s", rw_name(b1 & 15), (op == 0x88) ? "-" : "", rw_name(b1 >> 4));
		return 2 | flags;
	case 0xc8: case 0xd8: case 0xe8:
		util::stream_format(stream, "mov [%s%s], [%s%s]", rw_name(b1 >> 4), (op == 0xd8) ? "+" : "", rw_name(b1 & 15), (op == 0xe8) ? "+" : "");
		return 2 | flags;
	case 0xd4:
		util::stream_format(stream, "mov %s, [%s+#%04X]", rw_name(b1 >> 4), rw_name(b1 & 15), u16at(2));
		return 4 | flags;
	case 0xc4:
		util::stream_format(stream, "mov [%s+#%04X], %s", rw_name(b1 & 15), u16at(2), rw_name(b1 >> 4));
		return 4 | flags;
	case 0x84:
		util::stream_format(stream, "mov [%s], %04X", rw_name(b1 & 15), u16at(2));
		return 4 | flags;
	case 0x94:
		util::stream_format(stream, "mov %04X, [%s]", u16at(2), rw_name(b1 & 15));
		return 4 | flags;
	case 0xf1:
		util::stream_format(stream, "movb %s, %s", rb_name(b1 >> 4), rb_name(b1 & 15));
		return 2 | flags;
	case 0xe1:
		util::stream_format(stream, "movb %s, #%X", rb_name(b1 & 15), b1 >> 4);
		return 2 | flags;
	case 0xe7:
		util::stream_format(stream, "movb %s, #%02X", reg_b(b1), b2);
		return 4 | flags;
	case 0xf3:
		util::stream_format(stream, "movb %s, %04X", reg_b(b1), u16at(2));
		return 4 | flags;
	case 0xf7:
		util::stream_format(stream, "movb %04X, %s", u16at(2), reg_b(b1));
		return 4 | flags;
	case 0xa9: case 0x99:
		util::stream_format(stream, "movb %s, [%s%s]", rb_name(b1 >> 4), rw_name(b1 & 15), (op == 0x99) ? "+" : "");
		return 2 | flags;
	case 0xb9: case 0x89:
		util::stream_format(stream, "movb [%s%s], %s", rw_name(b1 & 15), (op == 0x89) ? "-" : "", rb_name(b1 >> 4));
		return 2 | flags;
	case 0xc9: case 0xd9: case 0xe9:
		util::stream_format(stream, "movb [%s%s], [%s%s]", rw_name(b1 >> 4), (op == 0xd9) ? "+" : "", rw_name(b1 & 15), (op == 0xe9) ? "+" : "");
		return 2 | flags;
	case 0xf4:
		util::stream_format(stream, "movb %s, [%s+#%04X]", rb_name(b1 >> 4), rw_name(b1 & 15), u16at(2));
		return 4 | flags;
	case 0xe4:
		util::stream_format(stream, "movb [%s+#%04X], %s", rw_name(b1 & 15), u16at(2), rb_name(b1 >> 4));
		return 4 | flags;
	case 0xa4:
		util::stream_format(stream, "movb [%s], %04X", rw_name(b1 & 15), u16at(2));
		return 4 | flags;
	case 0xb4:
		util::stream_format(stream, "movb %04X, [%s]", u16at(2), rw_name(b1 & 15));
		return 4 | flags;
	case 0xc0:
	case 0xd0:
		util::stream_format(stream, "%s %s, %s", (op == 0xc0) ? "movbz" : "movbs", rw_name(b1 & 15), rb_name(b1 >> 4));
		return 2 | flags;
	case 0xc2:
	case 0xd2:
		util::stream_format(stream, "%s %s, %04X", (op == 0xc2) ? "movbz" : "movbs", reg_w(b1), u16at(2));
		return 4 | flags;
	case 0xc5:
	case 0xd5:
		util::stream_format(stream, "%s %04X, %s", (op == 0xc5) ? "movbz" : "movbs", u16at(2), reg_b(b1));
		return 4 | flags;
	default:
		util::stream_format(stream, ".byte %02X", op);
		return 2 | flags;
	}
}
