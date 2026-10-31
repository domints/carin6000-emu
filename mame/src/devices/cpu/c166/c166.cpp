// license:BSD-3-Clause
// copyright-holders:The MAME Team
/*******************************************************************

    Siemens / Infineon C166 interpreter.

    Encodings follow the C166 Family Instruction Set Manual (the
    opcode is the first memory byte, little-endian immediates).
    There is no C166 core in upstream MAME; this one was written
    for the ST10F269 on the DVD90 / CD70.

*******************************************************************/

#include "emu.h"
#include "c166.h"
#include "c166dasm.h"

namespace {

constexpr uint16_t FN = 1 << 0;
constexpr uint16_t FC = 1 << 1;
constexpr uint16_t FV = 1 << 2;
constexpr uint16_t FZ = 1 << 3;
constexpr uint16_t FE = 1 << 4;
constexpr uint16_t FM = 1 << 5;
constexpr uint16_t FI = 1 << 11;

} // anonymous namespace


c166_cpu_device::c166_cpu_device(const machine_config &mconfig, device_type type, const char *tag, device_t *owner, uint32_t clock)
	: cpu_device(mconfig, type, tag, owner, clock)
	, m_program_config("program", ENDIANNESS_LITTLE, 8, 24, 0)
	, m_csp(0)
	, m_ip(0)
	, m_psw(0)
	, m_sp(0)
	, m_cp(0)
	, m_stkov(0)
	, m_stkun(0)
	, m_mdl(0)
	, m_mdh(0)
	, m_mdc(0)
	, m_dpp{ 0, 1, 2, 3 }
	, m_einit(false)
	, m_wdt_disable(false)
	, m_halt(false)
	, m_reset_pending(false)
	, m_soft_reset(false)
	, m_pwrdn(false)
	, m_icount(0)
	, m_cycles(2)
	, m_pc(0)
	, m_ppc(0)
	, m_extr(0)
	, m_atomic(0)
	, m_page_n(0)
	, m_page_val(0)
	, m_page_seg(false)
	, m_page_lock(false)
	, m_hold_extr(false)
	, m_hold_atomic(false)
	, m_hold_page(false)
	, m_idle(false)
	, m_nmi_pending(false)
	, m_nmi_line(0)
	, m_in_trap(false)
	, m_abort(false)
	, m_trace(0)
	, m_call_log(0)
	, m_ill_log(0)
	, m_insn(0)
	, m_beat(0)
	, m_seg_e(false)
	, m_seg2(false)
	, m_logged_einit(false)
	, m_logged_idle(false)
	, m_op0_csp(0)
	, m_op0_ip(0)
	, m_bus_data(false)
	, m_msw(0x0200)
	, m_mah(0)
	, m_mal(0)
	, m_mcw(0)
	, m_mrw(0)
	, m_idx0(0)
	, m_idx1(0)
	, m_qx0(0)
	, m_qx1(0)
	, m_qr0(0)
	, m_qr1(0)
{
	set_icountptr(m_icount);
}

void c166_cpu_device::device_start()
{
	space(AS_PROGRAM).specific(m_program);

	state_add(C166_CSP, "CSP", m_csp).mask(0xff);
	state_add(C166_IP, "IP", m_ip);
	state_add(C166_PSW, "PSW", m_psw);
	state_add(C166_SP, "SP", m_sp);
	state_add(C166_CP, "CP", m_cp);
	state_add(C166_STKOV, "STKOV", m_stkov);
	state_add(C166_STKUN, "STKUN", m_stkun);
	state_add(C166_MDL, "MDL", m_mdl);
	state_add(C166_MDH, "MDH", m_mdh);
	state_add(C166_MDC, "MDC", m_mdc);
	state_add(C166_DPP0, "DPP0", m_dpp[0]).mask(0x3ff);
	state_add(C166_DPP1, "DPP1", m_dpp[1]).mask(0x3ff);
	state_add(C166_DPP2, "DPP2", m_dpp[2]).mask(0x3ff);
	state_add(C166_DPP3, "DPP3", m_dpp[3]).mask(0x3ff);
	state_add(STATE_GENPC, "GENPC", m_pc).mask(0xffffff).noshow().callimport();
	state_add(STATE_GENPCBASE, "CURPC", m_ppc).mask(0xffffff).noshow();
	state_add(STATE_GENFLAGS, "GENFLAGS", m_psw).formatstr("%04X").noshow();

	save_item(NAME(m_csp));
	save_item(NAME(m_ip));
	save_item(NAME(m_psw));
	save_item(NAME(m_sp));
	save_item(NAME(m_cp));
	save_item(NAME(m_stkov));
	save_item(NAME(m_stkun));
	save_item(NAME(m_mdl));
	save_item(NAME(m_mdh));
	save_item(NAME(m_mdc));
	save_item(NAME(m_dpp));
	save_item(NAME(m_einit));
	save_item(NAME(m_wdt_disable));
	save_item(NAME(m_msw));
	save_item(NAME(m_mah));
	save_item(NAME(m_mal));
	save_item(NAME(m_mcw));
	save_item(NAME(m_mrw));
	save_item(NAME(m_idx0));
	save_item(NAME(m_idx1));
	save_item(NAME(m_qx0));
	save_item(NAME(m_qx1));
	save_item(NAME(m_qr0));
	save_item(NAME(m_qr1));
}

void c166_cpu_device::device_reset()
{
	m_csp = 0;
	m_ip = 0;
	m_psw = 0;
	m_cp = 0xfc00;
	m_sp = 0xfc00;
	m_stkov = 0xfa00;
	m_stkun = 0xfc00;
	m_mdl = m_mdh = m_mdc = 0;
	m_dpp[0] = 0;
	m_dpp[1] = 1;
	m_dpp[2] = 2;
	m_dpp[3] = 3;
	m_extr = m_atomic = m_page_n = 0;
	m_page_val = 0;
	m_page_seg = m_page_lock = false;
	m_einit = false;
	m_wdt_disable = false;
	m_idle = false;
	m_pwrdn = false;
	m_nmi_pending = false;
	m_in_trap = false;
	m_abort = false;
	m_reset_pending = false;
	m_msw = 0x0200;
	m_mah = m_mal = m_mcw = m_mrw = 0;
	m_idx0 = m_idx1 = 0;
	m_qx0 = m_qx1 = m_qr0 = m_qr1 = 0;
}

device_memory_interface::space_config_vector c166_cpu_device::memory_space_config() const
{
	return space_config_vector {
		std::make_pair(AS_PROGRAM, &m_program_config)
	};
}

void c166_cpu_device::state_import(const device_state_entry &entry)
{
	if (entry.index() == STATE_GENPC)
	{
		m_csp = (m_pc >> 16) & 0xff;
		m_ip = m_pc & 0xffff;
	}
}

std::unique_ptr<util::disasm_interface> c166_cpu_device::create_disassembler()
{
	return std::make_unique<c166_disassembler>();
}

void c166_cpu_device::execute_set_input(int inputnum, int state)
{
	if (inputnum == INPUT_LINE_NMI)
	{
		if (state && !m_nmi_line)
			m_nmi_pending = true;
		m_nmi_line = state;
	}
	else if (inputnum == INPUT_LINE_RESET && state)
		m_reset_pending = true;
}

void c166_cpu_device::execute_run()
{
	if (!image_present())
	{
		m_icount = 0;
		return;
	}

	while (m_icount > 0)
	{
		if (m_pwrdn)
		{
			if (m_nmi_pending)
				m_pwrdn = false;
			else
			{
				m_icount = 0;
				return;
			}
		}
		if (m_reset_pending)
		{
			m_reset_pending = false;
			bool const halt = m_halt;
			m_soft_reset = true;
			device_reset();
			m_soft_reset = false;
			m_halt = halt;
		}
		if (m_halt || !image_present())
		{
			m_icount = 0;
			return;
		}
		if (check_irq())
		{
			m_idle = false;
			m_icount -= 4;
			burn_cycles(4);
			continue;
		}
		if (m_idle)
		{
			while (m_icount > 0 && m_idle && !m_reset_pending)
			{
				int const step = (m_icount > 256) ? 256 : m_icount;
				burn_cycles(step);
				m_icount -= step;
				if (m_reset_pending)
					break;
				if (check_irq())
				{
					m_idle = false;
					m_icount -= 4;
					burn_cycles(4);
				}
			}
			continue;
		}

		m_abort = false;
		execute();
		if (m_cycles < 2)
			m_cycles = 2;
		m_icount -= m_cycles;
		burn_cycles(m_cycles);
	}
}

bool c166_cpu_device::cpu_sfr_r(uint32_t addr, uint8_t &data)
{
	uint16_t value = 0;
	bool md = false;
	switch (addr & ~1u)
	{
	case 0xfe00: value = m_dpp[0]; break;
	case 0xfe02: value = m_dpp[1]; break;
	case 0xfe04: value = m_dpp[2]; break;
	case 0xfe06: value = m_dpp[3]; break;
	case 0xfe08: value = m_csp; break;
	case 0xfe0c: value = m_mdh; md = true; break;
	case 0xfe0e: value = m_mdl; md = true; break;
	case 0xfe10: value = m_cp; break;
	case 0xfe12: value = m_sp; break;
	case 0xfe14: value = m_stkov; break;
	case 0xfe16: value = m_stkun; break;
	case 0xff0e: value = m_mdc; md = true; break;
	case 0xff10: value = m_psw; break;
	case 0xff1c: value = 0; break;
	case 0xff1e: value = 0xffff; break;
	case 0xfe5c: value = m_mal; break;
	case 0xfe5e: value = m_mah; break;
	case 0xff08: value = m_idx0; break;
	case 0xff0a: value = m_idx1; break;
	case 0xffda: value = m_mrw; break;
	case 0xffdc: value = m_mcw; break;
	case 0xffde: value = m_msw; break;
	case 0xf000: value = m_qx0; break;
	case 0xf002: value = m_qx1; break;
	case 0xf004: value = m_qr0; break;
	case 0xf006: value = m_qr1; break;
	default: return false;
	}
	if (md && !(addr & 1) && !machine().side_effects_disabled())
		m_psw &= ~FM;
	data = (addr & 1) ? (value >> 8) : (value & 0xff);
	return true;
}

bool c166_cpu_device::cpu_sfr_w(uint32_t addr, uint8_t data)
{
	uint16_t *reg = nullptr;
	uint16_t mask = 0xffff;
	switch (addr & ~1u)
	{
	case 0xfe00: reg = &m_dpp[0]; mask = 0x3ff; break;
	case 0xfe02: reg = &m_dpp[1]; mask = 0x3ff; break;
	case 0xfe04: reg = &m_dpp[2]; mask = 0x3ff; break;
	case 0xfe06: reg = &m_dpp[3]; mask = 0x3ff; break;
	case 0xfe08: return true;
	case 0xfe0c: reg = &m_mdh; break;
	case 0xfe0e: reg = &m_mdl; break;
	case 0xfe10: reg = &m_cp; mask = 0xfffe; break;
	case 0xfe12: reg = &m_sp; mask = 0xfffe; break;
	case 0xfe14: reg = &m_stkov; mask = 0xfffe; break;
	case 0xfe16: reg = &m_stkun; mask = 0xfffe; break;
	case 0xff0e: reg = &m_mdc; break;
	case 0xff10: reg = &m_psw; break;
	case 0xff1c:
	case 0xff1e: return true;
	case 0xfe5c: reg = &m_mal; break;
	case 0xfe5e: reg = &m_mah; break;
	case 0xff08: reg = &m_idx0; mask = 0xfffe; break;
	case 0xff0a: reg = &m_idx1; mask = 0xfffe; break;
	case 0xffda: reg = &m_mrw; break;
	case 0xffdc: reg = &m_mcw; break;
	case 0xffde: reg = &m_msw; break;
	case 0xf000: reg = &m_qx0; break;
	case 0xf002: reg = &m_qx1; break;
	case 0xf004: reg = &m_qr0; break;
	case 0xf006: reg = &m_qr1; break;
	default: return false;
	}
	uint16_t value = *reg;
	if (addr & 1)
		value = (value & 0x00ff) | (uint16_t(data) << 8);
	else
		value = (value & 0xff00) | data;
	*reg = value & mask;
	if ((addr & ~1u) == 0xff10)
		m_psw &= ~FM;
	if ((addr & ~1u) == 0xffde)
		m_msw |= 0x0200;
	return true;
}

void c166_cpu_device::close_prefix()
{
	if (m_abort)
		return;
	if (!m_hold_extr && m_extr)
		m_extr--;
	if (!m_hold_atomic && m_atomic)
		m_atomic--;
	if (!m_hold_page && m_page_n)
		m_page_n--;
}

uint8_t c166_cpu_device::fetch()
{
	uint32_t const pc = (uint32_t(m_csp) << 16) | m_ip;
	uint8_t const byte = m_program.read_byte(pc);
	m_ip++;
	return byte;
}

uint16_t c166_cpu_device::fetch_w()
{
	uint8_t const lo = fetch();
	uint8_t const hi = fetch();
	return lo | (uint16_t(hi) << 8);
}

uint32_t c166_cpu_device::data_addr(uint16_t addr) const
{
	if (m_page_n)
	{
		if (m_page_seg)
			return (uint32_t(m_page_val & 0xff) << 16) | addr;
		return (uint32_t(m_page_val & 0x3ff) << 14) | (addr & 0x3fff);
	}
	unsigned const page = addr >> 14;
	return (uint32_t(m_dpp[page] & 0x3ff) << 14) | (addr & 0x3fff);
}

uint32_t c166_cpu_device::sfr_base() const
{
	return m_extr ? 0xf000 : 0xfe00;
}

uint16_t c166_cpu_device::rreg(unsigned n)
{
	return m_program.read_word((m_cp + ((n & 15) << 1)) & 0xffff);
}

void c166_cpu_device::wreg(unsigned n, uint16_t v)
{
	m_program.write_word((m_cp + ((n & 15) << 1)) & 0xffff, v);
}

uint8_t c166_cpu_device::rrb(uint8_t nib)
{
	uint16_t const w = rreg((nib >> 1) & 7);
	return (nib & 1) ? (w >> 8) : (w & 0xff);
}

void c166_cpu_device::wrb(uint8_t nib, uint8_t v)
{
	unsigned const reg = (nib >> 1) & 7;
	uint16_t w = rreg(reg);
	if (nib & 1)
		w = (w & 0x00ff) | (uint16_t(v) << 8);
	else
		w = (w & 0xff00) | v;
	wreg(reg, w);
}

uint16_t c166_cpu_device::rrw(uint8_t rr)
{
	if ((rr & 0xf0) == 0xf0)
		return rreg(rr & 0x0f);
	return m_program.read_word(sfr_base() + (uint32_t(rr) << 1));
}

void c166_cpu_device::wrw(uint8_t rr, uint16_t v)
{
	if ((rr & 0xf0) == 0xf0)
		wreg(rr & 0x0f, v);
	else
		m_program.write_word(sfr_base() + (uint32_t(rr) << 1), v);
}

uint8_t c166_cpu_device::rrb_sfr(uint8_t rr)
{
	if ((rr & 0xf0) == 0xf0)
		return rrb(rr & 0x0f);
	return m_program.read_byte(sfr_base() + rr);
}

void c166_cpu_device::wrb_sfr(uint8_t rr, uint8_t v)
{
	if ((rr & 0xf0) == 0xf0)
		wrb(rr & 0x0f, v);
	else
		m_program.write_byte(sfr_base() + rr, v);
}

uint16_t c166_cpu_device::read_dw(uint16_t addr)
{
	if (addr & 1)
	{
		trap_b(0);
		return 0;
	}
	m_bus_data = true;
	uint16_t const v = m_program.read_word(data_addr(addr));
	m_bus_data = false;
	return v;
}

void c166_cpu_device::write_dw(uint16_t addr, uint16_t v)
{
	if (addr & 1)
	{
		trap_b(0);
		return;
	}
	m_bus_data = true;
	m_program.write_word(data_addr(addr), v);
	m_bus_data = false;
}

uint8_t c166_cpu_device::read_db(uint16_t addr)
{
	m_bus_data = true;
	uint8_t const v = m_program.read_byte(data_addr(addr));
	m_bus_data = false;
	return v;
}

void c166_cpu_device::write_db(uint16_t addr, uint8_t v)
{
	m_bus_data = true;
	m_program.write_byte(data_addr(addr), v);
	m_bus_data = false;
}

void c166_cpu_device::add_waits(int n)
{
	if (n > 0)
		m_cycles += n;
}

uint16_t c166_cpu_device::ptr_use(unsigned rn, int adj, bool byte_op)
{
	uint16_t p = rreg(rn);
	unsigned const step = byte_op ? 1 : 2;
	if (adj < 0)
	{
		p -= step;
		wreg(rn, p);
	}
	uint16_t const used = p;
	if (adj > 0)
		wreg(rn, uint16_t(p + step));
	return used;
}

void c166_cpu_device::push_raw(uint16_t v)
{
	m_sp -= 2;
	m_program.write_word(m_sp, v);
}

void c166_cpu_device::push(uint16_t v)
{
	m_sp -= 2;
	m_program.write_word(m_sp, v);
	if (!m_in_trap && m_sp < m_stkov)
		enter_trap(0x0010, 15);
}

uint16_t c166_cpu_device::pop()
{
	uint16_t const v = m_program.read_word(m_sp);
	m_sp += 2;
	if (!m_in_trap && m_sp > m_stkun)
		enter_trap(0x0018, 15);
	return v;
}

void c166_cpu_device::enter_trap(uint16_t vector, int new_ilvl)
{
	if (m_in_trap)
	{
		m_abort = true;
		return;
	}
	m_in_trap = true;
	m_abort = true;
	uint16_t const psw = m_psw;
	uint16_t const csp = m_csp;
	uint16_t const ip = m_ip;
	m_extr = 0;
	m_atomic = 0;
	m_page_n = 0;
	push_raw(psw);
	push_raw(csp);
	push_raw(ip);
	if (new_ilvl >= 0)
		m_psw = (m_psw & 0x0fff) | (uint16_t(new_ilvl) << 12);
	m_csp = 0;
	m_ip = vector;
	m_idle = false;
	m_in_trap = false;
}

void c166_cpu_device::trap_b(uint8_t op)
{
	if (m_ill_log < 16)
	{
		m_ill_log++;
		logerror("ST10 illegal %02X at %02X:%04X\n", op, m_op0_csp, m_op0_ip);
	}
	enter_trap(0x0028, 15);
}

bool c166_cpu_device::check_irq()
{
	if (m_nmi_pending)
	{
		m_nmi_pending = false;
		enter_trap(0x0008, 15);
		return true;
	}
	if (m_atomic || m_extr || (m_page_n && m_page_lock))
		return false;
	if (!(m_psw & FI))
		return false;
	poll_peripherals();
	uint16_t vector = 0;
	int level = 0;
	if (!pick_irq((m_psw >> 12) & 15, vector, level))
		return false;
	enter_trap(vector, level);
	return true;
}

bool c166_cpu_device::cc_true(int cc) const
{
	bool const n = m_psw & FN;
	bool const c = m_psw & FC;
	bool const v = m_psw & FV;
	bool const z = m_psw & FZ;
	bool const e = m_psw & FE;
	switch (cc & 15)
	{
	case 0: return true;
	case 1: return !z && !e;
	case 2: return z;
	case 3: return !z;
	case 4: return v;
	case 5: return !v;
	case 6: return n;
	case 7: return !n;
	case 8: return c;
	case 9: return !c;
	case 10: return !z && (n == v);
	case 11: return z || (n != v);
	case 12: return n != v;
	case 13: return n == v;
	case 14: return !z && !c;
	default: return z || c;
	}
}

void c166_cpu_device::branch_rel(int8_t rel)
{
	m_ip = uint16_t(int32_t(m_ip) + 2 * int32_t(rel));
}

void c166_cpu_device::flags_mov_w(uint16_t src)
{
	m_psw &= ~(FN | FZ | FE);
	if (src & 0x8000)
		m_psw |= FN;
	if (src == 0)
		m_psw |= FZ;
	if (src == 0x8000)
		m_psw |= FE;
}

void c166_cpu_device::flags_mov_b(uint8_t src)
{
	m_psw &= ~(FN | FZ | FE);
	if (src & 0x80)
		m_psw |= FN;
	if (src == 0)
		m_psw |= FZ;
	if (src == 0x80)
		m_psw |= FE;
}

uint16_t c166_cpu_device::add_w(uint16_t a, uint16_t b, int cin, bool sticky)
{
	bool const oldz = (m_psw & FZ) != 0;
	uint32_t const r = uint32_t(a) + b + cin;
	m_psw &= ~(FN | FZ | FV | FC | FE);
	if (r & 0x8000)
		m_psw |= FN;
	if ((r & 0xffff) == 0 && (!sticky || oldz))
		m_psw |= FZ;
	if (r > 0xffff)
		m_psw |= FC;
	if ((~(a ^ b) & (a ^ uint16_t(r)) & 0x8000) != 0)
		m_psw |= FV;
	if (b == 0x8000)
		m_psw |= FE;
	return uint16_t(r);
}

uint8_t c166_cpu_device::add_b(uint8_t a, uint8_t b, int cin, bool sticky)
{
	bool const oldz = (m_psw & FZ) != 0;
	uint16_t const r = uint16_t(a) + b + cin;
	m_psw &= ~(FN | FZ | FV | FC | FE);
	if (r & 0x80)
		m_psw |= FN;
	if ((r & 0xff) == 0 && (!sticky || oldz))
		m_psw |= FZ;
	if (r > 0xff)
		m_psw |= FC;
	if ((~(a ^ b) & (a ^ uint8_t(r)) & 0x80) != 0)
		m_psw |= FV;
	if (b == 0x80)
		m_psw |= FE;
	return uint8_t(r);
}

uint16_t c166_cpu_device::sub_w(uint16_t a, uint16_t b, int cin, bool sticky)
{
	bool const oldz = (m_psw & FZ) != 0;
	uint32_t const r = uint32_t(a) - b - cin;
	m_psw &= ~(FN | FZ | FV | FC | FE);
	if (r & 0x8000)
		m_psw |= FN;
	if ((r & 0xffff) == 0 && (!sticky || oldz))
		m_psw |= FZ;
	if (uint32_t(a) < uint32_t(b) + uint32_t(cin))
		m_psw |= FC;
	if (((a ^ b) & (a ^ uint16_t(r)) & 0x8000) != 0)
		m_psw |= FV;
	if (b == 0x8000)
		m_psw |= FE;
	return uint16_t(r);
}

uint8_t c166_cpu_device::sub_b(uint8_t a, uint8_t b, int cin, bool sticky)
{
	bool const oldz = (m_psw & FZ) != 0;
	uint16_t const r = uint16_t(a) - b - cin;
	m_psw &= ~(FN | FZ | FV | FC | FE);
	if (r & 0x80)
		m_psw |= FN;
	if ((r & 0xff) == 0 && (!sticky || oldz))
		m_psw |= FZ;
	if (uint16_t(a) < uint16_t(b) + uint16_t(cin))
		m_psw |= FC;
	if (((a ^ b) & (a ^ uint8_t(r)) & 0x80) != 0)
		m_psw |= FV;
	if (b == 0x80)
		m_psw |= FE;
	return uint8_t(r);
}

uint16_t c166_cpu_device::logic_w(uint16_t r, uint16_t src)
{
	m_psw &= ~(FN | FZ | FV | FC | FE);
	if (r & 0x8000)
		m_psw |= FN;
	if (r == 0)
		m_psw |= FZ;
	if (src == 0x8000)
		m_psw |= FE;
	return r;
}

uint8_t c166_cpu_device::logic_b(uint8_t r, uint8_t src)
{
	m_psw &= ~(FN | FZ | FV | FC | FE);
	if (r & 0x80)
		m_psw |= FN;
	if (r == 0)
		m_psw |= FZ;
	if (src == 0x80)
		m_psw |= FE;
	return r;
}

uint16_t c166_cpu_device::apply_w(int alu, uint16_t a, uint16_t b)
{
	switch (alu)
	{
	case 0: return add_w(a, b, 0);
	case 1: return add_w(a, b, (m_psw & FC) ? 1 : 0, true);
	case 2: return sub_w(a, b, 0);
	case 3: return sub_w(a, b, (m_psw & FC) ? 1 : 0, true);
	case 4: sub_w(a, b, 0); return a;
	case 5: return logic_w(a ^ b, b);
	case 6: return logic_w(a & b, b);
	default: return logic_w(a | b, b);
	}
}

uint8_t c166_cpu_device::apply_b(int alu, uint8_t a, uint8_t b)
{
	switch (alu)
	{
	case 0: return add_b(a, b, 0);
	case 1: return add_b(a, b, (m_psw & FC) ? 1 : 0, true);
	case 2: return sub_b(a, b, 0);
	case 3: return sub_b(a, b, (m_psw & FC) ? 1 : 0, true);
	case 4: sub_b(a, b, 0); return a;
	case 5: return logic_b(a ^ b, b);
	case 6: return logic_b(a & b, b);
	default: return logic_b(a | b, b);
	}
}

void c166_cpu_device::do_alu(int alu, int form)
{
	bool const byte = form & 1;
	bool const cmp = alu == 4;
	if (form <= 1)
	{
		uint8_t const b1 = fetch();
		if (byte)
		{
			uint8_t const r = apply_b(alu, rrb(b1 >> 4), rrb(b1 & 15));
			if (!cmp)
				wrb(b1 >> 4, r);
		}
		else
		{
			uint16_t const r = apply_w(alu, rreg(b1 >> 4), rreg(b1 & 15));
			if (!cmp)
				wreg(b1 >> 4, r);
		}
		return;
	}
	if (form == 8 || form == 9)
	{
		uint8_t const b1 = fetch();
		unsigned const dest = b1 >> 4;
		unsigned const low = b1 & 15;
		uint16_t srcw = 0;
		uint8_t srcb = 0;
		if (low < 8)
		{
			srcw = low;
			srcb = uint8_t(low);
		}
		else
		{
			uint16_t const a = ptr_use(low & 3, (low >= 12) ? 1 : 0, byte);
			if (byte)
				srcb = read_db(a);
			else
				srcw = read_dw(a);
			if (m_abort)
				return;
		}
		if (byte)
		{
			uint8_t const r = apply_b(alu, rrb(dest), srcb);
			if (!cmp)
				wrb(dest, r);
		}
		else
		{
			uint16_t const r = apply_w(alu, rreg(dest), srcw);
			if (!cmp)
				wreg(dest, r);
		}
		return;
	}

	uint8_t const rr = fetch();
	uint16_t const imm_or_addr = fetch_w();
	if (m_abort)
		return;
	if (form == 6 || form == 7)
	{
		if (byte)
		{
			uint8_t const r = apply_b(alu, rrb_sfr(rr), imm_or_addr & 0xff);
			if (!cmp)
				wrb_sfr(rr, r);
		}
		else
		{
			uint16_t const r = apply_w(alu, rrw(rr), imm_or_addr);
			if (!cmp)
				wrw(rr, r);
		}
		return;
	}
	if (form == 2 || form == 3)
	{
		if (byte)
		{
			uint8_t const r = apply_b(alu, rrb_sfr(rr), read_db(imm_or_addr));
			if (!cmp && !m_abort)
				wrb_sfr(rr, r);
		}
		else
		{
			uint16_t const mem = read_dw(imm_or_addr);
			if (m_abort)
				return;
			uint16_t const r = apply_w(alu, rrw(rr), mem);
			if (!cmp)
				wrw(rr, r);
		}
		return;
	}
	// mem, reg
	if (byte)
	{
		uint8_t const mem = read_db(imm_or_addr);
		uint8_t const r = apply_b(alu, mem, rrb_sfr(rr));
		if (!m_abort)
			write_db(imm_or_addr, r);
	}
	else
	{
		uint16_t const mem = read_dw(imm_or_addr);
		if (m_abort)
			return;
		uint16_t const r = apply_w(alu, mem, rrw(rr));
		write_dw(imm_or_addr, r);
	}
}

uint32_t c166_cpu_device::bit_word(uint8_t q)
{
	if (q >= 0xf0)
		return (m_cp + ((q & 0x0f) << 1)) & 0xffff;
	if (m_extr || q >= 0x80)
		return sfr_base() + (uint32_t(q) << 1);
	return 0xfd00 + (uint32_t(q) << 1);
}

bool c166_cpu_device::bit_get(uint8_t q, int bit)
{
	uint16_t const w = m_program.read_word(bit_word(q));
	return (w >> (bit & 15)) & 1;
}

void c166_cpu_device::bit_set(uint8_t q, int bit, bool value)
{
	uint32_t const a = bit_word(q);
	uint16_t w = m_program.read_word(a);
	uint16_t const mask = uint16_t(1) << (bit & 15);
	if (value)
		w |= mask;
	else
		w &= ~mask;
	m_program.write_word(a, w);
}

uint16_t c166_cpu_device::do_shift(uint16_t v, int count, int kind)
{
	count &= 15;
	m_psw &= ~(FE | FZ | FV | FC | FN);
	uint16_t carry = 0;
	bool overflow = false;
	for (int i = 0; i < count; i++)
	{
		if (kind == 1 || kind == 2)
			if (carry)
				overflow = true;
		if (kind == 0 || kind == 3)
		{
			carry = (v & 0x8000) ? 1 : 0;
			v = uint16_t((v << 1) | ((kind == 3) ? carry : 0));
		}
		else if (kind == 4)
		{
			carry = v & 1;
			v = uint16_t((v >> 1) | (carry ? 0x8000 : 0));
		}
		else if (kind == 2)
		{
			carry = v & 1;
			v = uint16_t((v >> 1) | (v & 0x8000));
		}
		else
		{
			carry = v & 1;
			v = uint16_t(v >> 1);
		}
	}
	if (carry)
		m_psw |= FC;
	if ((kind == 1 || kind == 2) && overflow)
		m_psw |= FV;
	if (v == 0)
		m_psw |= FZ;
	if (v & 0x8000)
		m_psw |= FN;
	return v;
}

bool c166_cpu_device::protected_seq(uint8_t a, uint8_t b, uint8_t c)
{
	uint8_t const x = fetch();
	uint8_t const y = fetch();
	uint8_t const z = fetch();
	return x == a && y == b && z == c;
}

void c166_cpu_device::execute()
{
	struct guard
	{
		c166_cpu_device *cpu;
		~guard() { cpu->close_prefix(); }
	} guard{ this };

	m_hold_extr = m_hold_atomic = m_hold_page = false;
	m_cycles = 2;
	m_op0_csp = m_csp;
	m_op0_ip = m_ip;
	m_ppc = m_pc = (uint32_t(m_op0_csp) << 16) | m_op0_ip;

	if (m_csp == 0x0e && !m_seg_e)
	{
		m_seg_e = true;
		logerror("ST10 entered segment 0E at %04X\n", m_ip);
	}
	if (m_csp == 0x02 && !m_seg2)
	{
		m_seg2 = true;
		logerror("ST10 entered segment 02 at %04X\n", m_ip);
	}
	if (m_trace < 48)
	{
		m_trace++;
		logerror("ST10 %02X:%04X %02X %02X %02X %02X\n", m_op0_csp, m_op0_ip,
			m_program.read_byte(m_pc), m_program.read_byte(m_pc + 1),
			m_program.read_byte(m_pc + 2), m_program.read_byte(m_pc + 3));
	}
	m_insn++;
	if ((m_insn & 0x3fffff) == 0 && m_beat < 12)
	{
		m_beat++;
		logerror("ST10 run %02X:%04X after %u insns\n", m_op0_csp, m_op0_ip, m_insn);
	}
	if (debugger_enabled())
		debugger_instruction_hook(m_pc);

	if (m_ip & 1)
	{
		trap_b(0);
		return;
	}

	uint8_t const op = fetch();
	unsigned const alu = op >> 4;
	unsigned const form = op & 0x0f;

	if (alu <= 7 && form <= 9 && !(alu == 4 && (form == 4 || form == 5)))
	{
		do_alu(int(alu), int(form));
		return;
	}
	if (form == 0x0d)
	{
		int8_t const rel = int8_t(fetch());
		if (cc_true(alu))
		{
			branch_rel(rel);
			m_cycles = 4;
		}
		return;
	}
	if (form == 0x0e || form == 0x0f)
	{
		uint8_t const q = fetch();
		bool const prev = bit_get(q, alu);
		bit_set(q, alu, form == 0x0f);
		m_psw &= ~(FE | FZ | FV | FC | FN);
		if (!prev)
			m_psw |= FZ;
		if (prev)
			m_psw |= FN;
		return;
	}

	decode(op);
}

namespace {

constexpr uint64_t MAC40 = (uint64_t(1) << 40) - 1;

int64_t sign40(uint64_t bits)
{
	bits &= MAC40;
	if (bits & (uint64_t(1) << 39))
		bits |= ~MAC40;
	return int64_t(bits);
}

struct mac_mul {
	int kind; // 0 multiply, 1 accumulate, 2 reverse accumulate
	int sign; // 0 signed, 1 unsigned, 2 op1 unsigned, 3 op2 unsigned
	bool rnd;
	bool neg;
};

// Kept out of line so the product sign and the round cannot share one
// conditional move. A combined test was negating the product whenever
// the round was requested.
__attribute__((noinline)) int64_t mac_adjust(int64_t p, int neg, int rnd)
{
	if (neg)
		p = int64_t(0) - p;
	if (rnd)
		p = (p + int64_t(0x8000)) & ~int64_t(0xffff);
	return p;
}

__attribute__((noinline)) bool mac_mul_info(uint8_t func, mac_mul &out)
{
	switch (func)
	{
	case 0xc0: out = { 0, 0, false, false }; return true;
	case 0xc1: out = { 0, 0, true, false }; return true;
	case 0xc8: out = { 0, 0, false, true }; return true;
	case 0x00: out = { 0, 1, false, false }; return true;
	case 0x01: out = { 0, 1, true, false }; return true;
	case 0x08: out = { 0, 1, false, true }; return true;
	case 0x80: out = { 0, 2, false, false }; return true;
	case 0x81: out = { 0, 2, true, false }; return true;
	case 0x88: out = { 0, 2, false, true }; return true;
	case 0x40: out = { 0, 3, false, false }; return true;
	case 0x41: out = { 0, 3, true, false }; return true;
	case 0x48: out = { 0, 3, false, true }; return true;
	case 0xd0: case 0xd8: out = { 1, 0, false, false }; return true;
	case 0xd1: case 0xd9: out = { 1, 0, true, false }; return true;
	case 0xe0: case 0xe8: out = { 1, 0, false, true }; return true;
	case 0x10: case 0x18: out = { 1, 1, false, false }; return true;
	case 0x11: case 0x19: out = { 1, 1, true, false }; return true;
	case 0x20: case 0x28: out = { 1, 1, false, true }; return true;
	case 0x90: case 0x98: out = { 1, 2, false, false }; return true;
	case 0x91: case 0x99: out = { 1, 2, true, false }; return true;
	case 0xa0: case 0xa8: out = { 1, 2, false, true }; return true;
	case 0x50: case 0x58: out = { 1, 3, false, false }; return true;
	case 0x51: case 0x59: out = { 1, 3, true, false }; return true;
	case 0x60: case 0x68: out = { 1, 3, false, true }; return true;
	case 0xf0: case 0xf8: out = { 2, 0, false, false }; return true;
	case 0xf1: case 0xf9: out = { 2, 0, true, false }; return true;
	case 0x30: case 0x38: out = { 2, 1, false, false }; return true;
	case 0x31: case 0x39: out = { 2, 1, true, false }; return true;
	case 0xb0: case 0xb8: out = { 2, 2, false, false }; return true;
	case 0xb1: case 0xb9: out = { 2, 2, true, false }; return true;
	case 0x70: case 0x78: out = { 2, 3, false, false }; return true;
	case 0x71: case 0x79: out = { 2, 3, true, false }; return true;
	default: return false;
	}
}

} // anonymous namespace


int64_t c166_cpu_device::mac_acc() const
{
	uint64_t const bits = uint64_t(m_mal) | (uint64_t(m_mah) << 16) | (uint64_t(m_msw & 0xff) << 32);
	return sign40(bits);
}

void c166_cpu_device::mac_commit(int64_t value, bool saturate, int carry, bool overflow)
{
	bool sl = false;
	if (saturate && (m_mcw & 0x8000))
	{
		if (value > int64_t(0x7fffffff))
		{
			value = int64_t(0x7fffffff);
			sl = true;
		}
		else if (value < -int64_t(0x80000000))
		{
			value = -int64_t(0x80000000);
			sl = true;
		}
	}
	uint64_t const bits = uint64_t(value) & MAC40;
	uint32_t const top9 = uint32_t((bits >> 31) & 0x1ff);
	bool const extension = !(top9 == 0 || top9 == 0x1ff);
	m_mal = uint16_t(bits);
	m_mah = uint16_t(bits >> 16);
	uint16_t msw = 0x0200 | uint16_t((bits >> 32) & 0xff);
	if (bits & (uint64_t(1) << 39))
		msw |= 0x8000;
	if (bits == 0)
		msw |= 0x4000;
	if (carry)
		msw |= 0x2000;
	if (overflow)
		msw |= 0x1000;
	if (extension)
		msw |= 0x0800;
	if (sl)
		msw |= 0x0400;
	m_msw = msw;
}

uint16_t c166_cpu_device::mac_coreg(unsigned id) const
{
	switch (id & 31)
	{
	case 0: return m_msw;
	case 1: return m_mah;
	case 2:
	{
		uint64_t const bits = uint64_t(m_mal) | (uint64_t(m_mah) << 16) | (uint64_t(m_msw & 0xff) << 32);
		uint32_t const top9 = uint32_t((bits >> 31) & 0x1ff);
		if (top9 == 0 || top9 == 0x1ff)
			return m_mah;
		return (bits & (uint64_t(1) << 39)) ? 0x8000 : 0x7fff;
	}
	case 4: return m_mal;
	case 5: return m_mcw;
	case 6: return m_mrw;
	default: return 0;
	}
}

void c166_cpu_device::exec_mac(uint8_t op)
{
	uint8_t const b1 = fetch();
	uint8_t const func = fetch();
	uint8_t const b3 = fetch();
	if (m_abort)
		return;

	bool const imm_shift = func == 0x82 || func == 0x92 || func == 0xa2 || (func == 0xb2 && op == 0xa3 && b1 == 0 && b3 != 0);
	int const rep_field = imm_shift ? 0 : (b3 >> 3);
	int const qqq = b3 & 7;
	// Keil encodes "- USR0" / "- USR1" as bit 6 of the address byte. That
	// repeat runs MRW+1 times. A repeat field of 1 is the same count.
	bool const mrw_rep = !imm_shift && ((b3 & 0x40) != 0 || rep_field == 1);
	int times = 1;
	if (mrw_rep)
		times = int(m_mrw & 0x1fff) + 1;
	else if (rep_field > 1)
		times = rep_field;
	if (times < 1)
		times = 1;
	if (times > 8192)
		times = 8192;

	auto bump_gpr = [this](unsigned rn, int mode)
	{
		int delta = 0;
		if (mode == 2)
			delta = 2;
		else if (mode == 3)
			delta = -2;
		else if (mode == 4)
			delta = int16_t(m_qr0);
		else if (mode == 5)
			delta = -int16_t(m_qr0);
		else if (mode == 6)
			delta = int16_t(m_qr1);
		else if (mode == 7)
			delta = -int16_t(m_qr1);
		else
			return;
		wreg(rn, uint16_t(int16_t(rreg(rn)) + delta));
	};
	auto bump_idx = [this](int which, int mode)
	{
		int const m = mode & 7;
		int delta = 0;
		if (m == 2)
			delta = 2;
		else if (m == 3)
			delta = -2;
		else if (m == 4)
			delta = int16_t(m_qx0);
		else if (m == 5)
			delta = -int16_t(m_qx0);
		else if (m == 6)
			delta = int16_t(m_qx1);
		else if (m == 7)
			delta = -int16_t(m_qx1);
		else
			return;
		uint16_t &idx = which ? m_idx1 : m_idx0;
		idx = uint16_t(int16_t(idx) + delta) & 0xfffe;
	};
	auto loadw = [this](uint16_t addr) -> uint16_t
	{
		if (addr & 1)
		{
			trap_b(0);
			return 0;
		}
		m_bus_data = true;
		uint16_t const v = m_program.read_word(data_addr(addr));
		m_bus_data = false;
		return v;
	};
	auto storew = [this](uint16_t addr, uint16_t v)
	{
		if (addr & 1)
		{
			trap_b(0);
			return;
		}
		m_bus_data = true;
		m_program.write_word(data_addr(addr), v);
		m_bus_data = false;
	};

	int done = 0;
	for (int i = 0; i < times; i++)
	{
		if (i > 0 && (m_psw & FI) && !m_atomic && !m_extr && !(m_page_n && m_page_lock))
		{
			poll_peripherals();
			uint16_t vector = 0;
			int level = 0;
			if (pick_irq((m_psw >> 12) & 15, vector, level))
				break;
		}

		unsigned const n = b1 >> 4;
		unsigned const m = b1 & 15;
		uint16_t op1 = 0;
		uint16_t op2 = 0;
		bool pair = false;
		uint16_t unary = 0;
		bool have_unary = false;

		if (op == 0xc3 || op == 0xb3)
		{
			uint16_t const value = mac_coreg(func >> 3);
			if (op == 0xc3)
				wreg(n, value);
			else
			{
				uint16_t const ptr = rreg(n);
				storew(ptr, value);
				if (m_abort)
					return;
				bump_gpr(n, qqq);
			}
			done++;
			burn_cycles(8);
			continue;
		}
		if (op == 0xd3)
		{
			int const which = (n & 8) ? 1 : 0;
			uint16_t const ia = which ? m_idx1 : m_idx0;
			uint16_t const pa = rreg(m);
			uint16_t const src = loadw(pa);
			if (m_abort)
				return;
			storew(ia, src);
			if (m_abort)
				return;
			bump_idx(which, n);
			bump_gpr(m, qqq);
			flags_mov_w(src);
			done++;
			burn_cycles(8);
			continue;
		}
		if (op == 0xa3)
		{
			op1 = rreg(n);
			op2 = rreg(m);
			pair = true;
			unary = op1;
			have_unary = true;
		}
		else if (op == 0x83)
		{
			uint16_t const ptr = rreg(m);
			uint16_t const mem = loadw(ptr);
			if (m_abort)
				return;
			bump_gpr(m, qqq);
			op1 = rreg(n);
			op2 = mem;
			pair = true;
			unary = mem;
			have_unary = true;
		}
		else if (op == 0x93)
		{
			int const which = (n & 8) ? 1 : 0;
			uint16_t const ia = which ? m_idx1 : m_idx0;
			uint16_t const pa = rreg(m);
			uint16_t const vi = loadw(ia);
			if (m_abort)
				return;
			uint16_t const vp = loadw(pa);
			if (m_abort)
				return;
			bump_idx(which, n);
			bump_gpr(m, qqq);
			op1 = vi;
			op2 = vp;
			pair = true;
		}

		if (func == 0x5a)
		{
			done++;
			burn_cycles(8);
			continue;
		}

		auto concat = [](uint16_t lo, uint16_t hi) -> int64_t
		{
			return int64_t(int32_t(uint32_t(lo) | (uint32_t(hi) << 16)));
		};
		auto bits40 = [](int64_t v) -> uint64_t
		{
			return uint64_t(v) & MAC40;
		};
		int64_t acc = mac_acc();
		int64_t result = acc;
		int carry = 0;
		bool sv = false;
		bool sat = false;
		bool write = true;
		bool old_sv = (m_msw & 0x1000) != 0;

		mac_mul mul;
		if (mac_mul_info(func, mul) && pair)
		{
			int64_t p = 0;
			if (mul.sign == 0)
				p = int64_t(int16_t(op1)) * int64_t(int16_t(op2));
			else if (mul.sign == 1)
				p = int64_t(uint32_t(op1) * uint32_t(op2));
			else if (mul.sign == 2)
				p = int64_t(uint32_t(op1)) * int64_t(int16_t(op2));
			else
				p = int64_t(int16_t(op1)) * int64_t(uint32_t(op2));
			bool const mp = (m_mcw & 0x4000) != 0;
			bool const ms = (m_mcw & 0x8000) != 0;
			bool const special = mul.sign == 0 && op1 == 0x8000 && op2 == 0x8000;
			if (mp)
				p <<= 1;
			p = mac_adjust(p, mul.neg ? 1 : 0, mul.rnd ? 1 : 0);
			if (mul.kind == 1)
				result = acc + p;
			else if (mul.kind == 2)
				result = p - acc;
			else
				result = p;
			uint64_t const ua = bits40(acc);
			uint64_t const up = bits40(p);
			if (mul.kind == 0)
			{
				carry = 0;
				sv = old_sv;
			}
			else if (mul.kind == 1)
			{
				uint64_t const sum = ua + up;
				carry = int(sum >> 40);
				int64_t const sa = sign40(ua);
				int64_t const sp = sign40(up);
				bool const rn = (bits40(sa + sp) & (uint64_t(1) << 39)) != 0;
				sv = (sa > 0 && sp > 0 && rn) || (sa < 0 && sp < 0 && !rn);
			}
			else
			{
				carry = up < ua ? 1 : 0;
				int64_t const sa = sign40(ua);
				int64_t const sp = sign40(up);
				bool const rn = (bits40(sp - sa) & (uint64_t(1) << 39)) != 0;
				sv = (sp >= 0 && sa < 0 && !rn) || (sp < 0 && sa > 0 && rn);
			}
			sat = false;
			mac_commit(result, sat, carry, sv);
			if (mul.kind == 0)
			{
				m_msw &= ~0x0800;
				if (special && mp)
					m_msw |= 0x0800;
				if (special && mp && ms)
					m_msw |= 0x0400;
				if (old_sv)
					m_msw |= 0x1000;
				else
					m_msw &= ~0x1000;
			}
			done++;
			burn_cycles(8);
			continue;
		}

		int shift = 0;
		bool is_shift = false;
		bool shift_rnd = false;
		bool arith = false;
		if (func == 0x82 || func == 0x92 || func == 0xa2 || (func == 0xb2 && imm_shift))
		{
			// Keil puts the immediate count in the low bits: #1 is 01, #8 is 08.
			shift = b3 & 15;
			is_shift = true;
			shift_rnd = func == 0xb2;
			if (shift > 8)
				shift = 8;
		}
		else if (func == 0x8a || func == 0x9a || func == 0xaa || func == 0xba)
		{
			shift = have_unary ? (unary & 31) : 0;
			if (shift > 8)
				shift = 8;
			is_shift = true;
			shift_rnd = func == 0xba;
		}

		if (is_shift)
		{
			uint64_t bits = bits40(acc);
			if (func == 0x82 || func == 0x8a)
			{
				for (int s = 0; s < shift; s++)
				{
					carry = int((bits >> 39) & 1);
					bits = (bits << 1) & MAC40;
				}
				result = sign40(bits);
				sat = true;
			}
			else if (func == 0x92 || func == 0x9a)
			{
				for (int s = 0; s < shift; s++)
				{
					carry = int(bits & 1);
					bits >>= 1;
				}
				result = sign40(bits);
				sat = false;
			}
			else
			{
				for (int s = 0; s < shift; s++)
				{
					carry = int(bits & 1);
					uint64_t const sign = bits & (uint64_t(1) << 39);
					bits = (bits >> 1) | sign;
				}
				result = sign40(bits);
				sat = false;
			}
			if (shift == 0)
				carry = 0;
			if (shift_rnd)
			{
				result += 0x8000;
				result = int64_t(uint64_t(result) & ~uint64_t(0xffff));
			}
			sv = old_sv;
			mac_commit(result, sat, carry, sv);
			done++;
			burn_cycles(8);
			continue;
		}

		if (func == 0x1a)
		{
			result = acc < 0 ? -acc : acc;
			sat = true;
			arith = true;
		}
		else if (func == 0xca && pair)
		{
			int64_t const tmp = concat(op1, op2);
			result = tmp < 0 ? -tmp : tmp;
			sat = true;
			arith = true;
		}
		else if (func == 0x32 || func == 0x72)
		{
			result = -acc;
			if (func == 0x72)
				result = (result + 0x8000) & ~int64_t(0xffff);
			sat = true;
			arith = true;
		}
		else if (func == 0xb2)
		{
			result = (acc + 0x8000) & ~int64_t(0xffff);
			sat = true;
			arith = true;
		}
		else if (pair && (func == 0x02 || func == 0x42 || func == 0x0a || func == 0x4a || func == 0x12 || func == 0x52 || func == 0x22 || func == 0x2a || func == 0x62 || func == 0x6a || func == 0xc2 || func == 0x3a || func == 0x7a))
		{
			int64_t tmp = concat(op1, op2);
			if (func == 0x42 || func == 0x4a || func == 0x52 || func == 0x62 || func == 0x6a)
				tmp *= 2;
			if (func == 0x2a || func == 0x6a)
				tmp = -tmp;
			uint64_t const ut = bits40(tmp);
			uint64_t const ua = bits40(acc);
			if (func == 0x22 || func == 0x2a || func == 0x62 || func == 0x6a)
			{
				result = tmp;
				sat = true;
			}
			else if (func == 0x02 || func == 0x42)
			{
				result = acc + tmp;
				carry = int((ua + ut) >> 40);
				bool const rn = (bits40(result) & (uint64_t(1) << 39)) != 0;
				sv = (sign40(ua) > 0 && sign40(ut) > 0 && rn) || (sign40(ua) < 0 && sign40(ut) < 0 && !rn);
				sat = true;
			}
			else if (func == 0x0a || func == 0x4a)
			{
				result = acc - tmp;
				carry = ua < ut ? 1 : 0;
				bool const rn = (bits40(result) & (uint64_t(1) << 39)) != 0;
				sv = (sign40(ua) >= 0 && sign40(ut) < 0 && !rn) || (sign40(ua) < 0 && sign40(ut) > 0 && rn);
				sat = true;
			}
			else if (func == 0x12 || func == 0x52)
			{
				result = tmp - acc;
				carry = ut < ua ? 1 : 0;
				bool const rn = (bits40(result) & (uint64_t(1) << 39)) != 0;
				sv = (sign40(ut) >= 0 && sign40(ua) < 0 && !rn) || (sign40(ut) < 0 && sign40(ua) > 0 && rn);
				sat = true;
			}
			else if (func == 0xc2)
			{
				result = acc - tmp;
				carry = ua < ut ? 1 : 0;
				write = false;
				sat = false;
			}
			else if (func == 0x3a)
			{
				result = acc > tmp ? acc : tmp;
				sat = false;
			}
			else
			{
				result = acc > tmp ? tmp : acc;
				sat = false;
			}
			arith = true;
		}

		if (arith)
		{
			uint16_t const keep_l = m_mal;
			uint16_t const keep_h = m_mah;
			uint16_t const keep_s = m_msw;
			mac_commit(result, sat, carry, sv);
			if (!write)
				m_msw = (m_msw & 0xff00) | (keep_s & 0x00ff);
			if (!write)
			{
				m_mal = keep_l;
				m_mah = keep_h;
				m_msw |= 0x0200;
			}
		}
		done++;
		burn_cycles(8);
		if (m_abort)
			return;
	}

	m_cycles = 2;
	if ((mrw_rep || rep_field > 0) && done == times && (m_mcw & 0x2000))
		enter_trap(0x0028, 15);
	else if (mrw_rep && done < times)
		m_mrw = uint16_t((times - done) & 0x1fff);
}

void c166_cpu_device::decode(uint8_t op)
{
	auto cmpdi = [this](unsigned rn, uint16_t src, int mode)
	{
		uint16_t reg = rreg(rn);
		sub_w(reg, src, 0);
		if (mode == 1)
			reg = uint16_t(reg - 1);
		else if (mode == 2)
			reg = uint16_t(reg - 2);
		else if (mode == 3)
			reg = uint16_t(reg + 1);
		else
			reg = uint16_t(reg + 2);
		wreg(rn, reg);
	};
	auto shift_rr = [this](int kind)
	{
		uint8_t const b1 = fetch();
		uint16_t const src = rreg(b1 >> 4);
		uint16_t const cnt = rreg(b1 & 15);
		wreg(b1 >> 4, do_shift(src, cnt, kind));
	};
	auto shift_i = [this](int kind)
	{
		uint8_t const b1 = fetch();
		wreg(b1 & 15, do_shift(rreg(b1 & 15), b1 >> 4, kind));
	};

	switch (op)
	{
	case 0x0a:
	case 0x1a:
	{
		// BFLDL is 0A QQ @@## and BFLDH is 1A QQ ## @@ (ST10 manual): the
		// AND mask comes first in BFLDL and second in BFLDH.
		uint8_t const q = fetch();
		uint8_t const b2 = fetch();
		uint8_t const b3 = fetch();
		uint8_t const mask = (op == 0x0a) ? b2 : b3;
		uint8_t const data = (op == 0x0a) ? b3 : b2;
		uint32_t const a = bit_word(q);
		uint16_t w = m_program.read_word(a);
		if (op == 0x0a)
			w = (w & 0xff00) | uint8_t(((w & 0xff) & ~mask) | data);
		else
		{
			uint8_t const high = uint8_t(((w >> 8) & ~mask) | data);
			w = (w & 0x00ff) | (uint16_t(high) << 8);
		}
		m_program.write_word(a, w);
		// Flags from the word result: Z and N follow it, E V C are cleared.
		m_psw &= ~(FE | FZ | FV | FC | FN);
		if (w == 0)
			m_psw |= FZ;
		if (w & 0x8000)
			m_psw |= FN;
		return;
	}

	case 0x2a: case 0x3a: case 0x4a: case 0x5a: case 0x6a: case 0x7a:
	{
		uint8_t const qs = fetch();
		uint8_t const qd = fetch();
		uint8_t const bits = fetch();
		bool const sb = bit_get(qs, bits >> 4);
		bool const db = bit_get(qd, bits & 15);
		// Flags per the ST10 manual. BMOV/BMOVN: Z = !source, N = source.
		// BCMP/BAND/BOR/BXOR: Z = NOR, V = OR, C = AND, N = XOR of the bits.
		m_psw &= ~(FE | FZ | FV | FC | FN);
		if (op == 0x3a || op == 0x4a)
		{
			if (!sb)
				m_psw |= FZ;
			if (sb)
				m_psw |= FN;
		}
		else
		{
			if (!(sb || db))
				m_psw |= FZ;
			if (sb || db)
				m_psw |= FV;
			if (sb && db)
				m_psw |= FC;
			if (sb != db)
				m_psw |= FN;
		}
		if (op == 0x2a)
			return;
		else if (op == 0x4a)
			bit_set(qd, bits & 15, sb);
		else if (op == 0x3a)
			bit_set(qd, bits & 15, !sb);
		else if (op == 0x6a)
			bit_set(qd, bits & 15, db && sb);
		else if (op == 0x5a)
			bit_set(qd, bits & 15, db || sb);
		else
			bit_set(qd, bits & 15, db != sb);
		return;
	}

	case 0x8a: case 0x9a: case 0xaa: case 0xba:
	{
		uint8_t const q = fetch();
		int8_t const rel = int8_t(fetch());
		int const bit = fetch() >> 4;
		bool const prev = bit_get(q, bit);
		if (op == 0xaa && prev)
			bit_set(q, bit, false);
		if (op == 0xba && !prev)
			bit_set(q, bit, true);
		bool const take = (op == 0x8a || op == 0xaa) ? prev : !prev;
		if (op == 0xaa || op == 0xba)
		{
			m_psw &= ~(FE | FZ | FV | FC | FN);
			if (!prev)
				m_psw |= FZ;
			if (prev)
				m_psw |= FN;
		}
		if (take)
		{
			branch_rel(rel);
			m_cycles = 4;
		}
		return;
	}

	case 0x0b:
	case 0x1b:
	{
		uint8_t const b1 = fetch();
		uint16_t const a = rreg(b1 >> 4);
		uint16_t const b = rreg(b1 & 15);
		uint32_t const p = (op == 0x0b)
			? uint32_t(int32_t(int16_t(a)) * int32_t(int16_t(b)))
			: uint32_t(a) * uint32_t(b);
		m_mdl = p & 0xffff;
		m_mdh = (p >> 16) & 0xffff;
		m_psw &= ~(FN | FZ | FV | FC | FE | FM);
		if (m_mdh & 0x8000)
			m_psw |= FN;
		if (p == 0)
			m_psw |= FZ;
		m_cycles = 10;
		return;
	}

	case 0x2b:
	{
		uint8_t const b1 = fetch();
		uint16_t const src = rreg(b1 & 15);
		uint16_t dst = 0;
		if (src != 0)
		{
			uint16_t t = src;
			while ((t & 0x8000) == 0)
			{
				t = uint16_t(t << 1);
				dst++;
			}
		}
		wreg(b1 >> 4, dst);
		m_psw &= ~(FN | FZ | FV | FC | FE);
		if (dst == 0)
			m_psw |= FZ;
		return;
	}

	case 0x4b: case 0x5b: case 0x6b: case 0x7b:
	{
		uint8_t const b1 = fetch();
		if ((b1 >> 4) != (b1 & 15))
		{
			trap_b(op);
			return;
		}
		uint16_t const rw = rreg(b1 & 15);
		m_psw &= ~(FN | FZ | FV | FC | FE | FM);
		m_cycles = 20;
		if (rw == 0)
		{
			m_psw |= FV;
			return;
		}
		if (op == 0x4b)
		{
			int32_t const dividend = int16_t(m_mdl);
			uint16_t const ext = (dividend < 0) ? 0xffff : 0;
			if (m_mdh != ext || (dividend == -32768 && int16_t(rw) == -1))
			{
				m_psw |= FV;
				return;
			}
			int32_t const q = dividend / int16_t(rw);
			int32_t const r = dividend % int16_t(rw);
			m_mdl = uint16_t(q);
			m_mdh = uint16_t(r);
		}
		else if (op == 0x5b)
		{
			if (m_mdh != 0)
			{
				m_psw |= FV;
				return;
			}
			uint32_t const dividend = m_mdl;
			m_mdl = uint16_t(dividend / rw);
			m_mdh = uint16_t(dividend % rw);
		}
		else if (op == 0x6b)
		{
			uint32_t const bits = (uint32_t(m_mdh) << 16) | m_mdl;
			int32_t const dividend = int32_t(bits);
			int32_t const divisor = int16_t(rw);
			if (dividend == int32_t(0x80000000) && divisor == -1)
			{
				m_psw |= FV;
				return;
			}
			int32_t const q = dividend / divisor;
			if (q < -32768 || q > 32767)
			{
				m_psw |= FV;
				return;
			}
			m_mdh = uint16_t(int16_t(dividend % divisor));
			m_mdl = uint16_t(int16_t(q));
		}
		else
		{
			uint32_t const dividend = (uint32_t(m_mdh) << 16) | m_mdl;
			uint32_t const q = dividend / rw;
			if (q > 0xffff)
			{
				m_psw |= FV;
				return;
			}
			m_mdh = uint16_t(dividend % rw);
			m_mdl = uint16_t(q);
		}
		if (m_mdl & 0x8000)
			m_psw |= FN;
		if (m_mdl == 0)
			m_psw |= FZ;
		return;
	}

	case 0x0c: shift_rr(3); return;
	case 0x2c: shift_rr(4); return;
	case 0x4c: shift_rr(0); return;
	case 0x6c: shift_rr(1); return;
	case 0xac: shift_rr(2); return;
	case 0x1c: shift_i(3); return;
	case 0x3c: shift_i(4); return;
	case 0x5c: shift_i(0); return;
	case 0x7c: shift_i(1); return;
	case 0xbc: shift_i(2); return;

	case 0x80: case 0x90: case 0xa0: case 0xb0:
	{
		uint8_t const b1 = fetch();
		int const mode = (op == 0xa0) ? 1 : (op == 0xb0) ? 2 : (op == 0x80) ? 3 : 4;
		cmpdi(b1 & 15, b1 >> 4, mode);
		return;
	}
	case 0x86: case 0x96: case 0xa6: case 0xb6:
	case 0x82: case 0x92: case 0xa2: case 0xb2:
	{
		uint8_t const b1 = fetch();
		uint16_t const extra = fetch_w();
		if ((b1 & 0xf0) != 0xf0)
		{
			trap_b(op);
			return;
		}
		uint16_t src = extra;
		if (op == 0x82 || op == 0x92 || op == 0xa2 || op == 0xb2)
		{
			src = read_dw(extra);
			if (m_abort)
				return;
		}
		int const mode = (op == 0xa6 || op == 0xa2) ? 1 : (op == 0xb6 || op == 0xb2) ? 2 : (op == 0x86 || op == 0x82) ? 3 : 4;
		cmpdi(b1 & 15, src, mode);
		return;
	}

	case 0x81: case 0x91: case 0xa1: case 0xb1:
	{
		uint8_t const b1 = fetch();
		if (b1 & 0x0f)
		{
			trap_b(op);
			return;
		}
		unsigned const n = b1 >> 4;
		if (op == 0x81)
			wreg(n, sub_w(0, rreg(n), 0));
		else if (op == 0xa1)
			wrb(n, sub_b(0, rrb(n), 0));
		else if (op == 0x91)
		{
			uint16_t const v = uint16_t(~rreg(n));
			wreg(n, v);
			m_psw &= ~(FN | FZ | FV | FE);
			m_psw |= FC;
			if (v & 0x8000)
				m_psw |= FN;
			if (v == 0)
				m_psw |= FZ;
		}
		else
		{
			uint8_t const v = uint8_t(~rrb(n));
			wrb(n, v);
			m_psw &= ~(FN | FZ | FV | FE);
			m_psw |= FC;
			if (v & 0x80)
				m_psw |= FN;
			if (v == 0)
				m_psw |= FZ;
		}
		return;
	}

	case 0xa5:
		if (!protected_seq(0x5a, 0xa5, 0xa5) || m_einit)
		{
			trap_b(op);
			return;
		}
		m_wdt_disable = true;
		logerror("ST10 DISWDT at %02X:%04X\n", m_op0_csp, m_op0_ip);
		return;
	case 0xb5:
		if (!protected_seq(0x4a, 0xb5, 0xb5))
		{
			trap_b(op);
			return;
		}
		m_einit = true;
		if (!m_logged_einit)
		{
			m_logged_einit = true;
			logerror("ST10 EINIT at %02X:%04X\n", m_op0_csp, m_op0_ip);
		}
		on_einit();
		return;
	case 0x87:
		if (!protected_seq(0x78, 0x87, 0x87))
		{
			trap_b(op);
			return;
		}
		m_idle = true;
		if (!m_logged_idle)
		{
			m_logged_idle = true;
			logerror("ST10 IDLE at %02X:%04X\n", m_op0_csp, m_op0_ip);
		}
		return;
	case 0x97:
		if (!protected_seq(0x68, 0x97, 0x97))
		{
			trap_b(op);
			return;
		}
		m_pwrdn = true;
		logerror("ST10 PWRDN at %02X:%04X\n", m_op0_csp, m_op0_ip);
		return;
	case 0xa7:
		if (!protected_seq(0x58, 0xa7, 0xa7))
		{
			trap_b(op);
			return;
		}
		on_srvwdt();
		return;
	case 0xb7:
		if (!protected_seq(0x48, 0xb7, 0xb7))
		{
			trap_b(op);
			return;
		}
		m_reset_pending = true;
		return;
	case 0xcc:
		if (fetch() != 0)
			trap_b(op);
		return;

	case 0xd1:
	{
		uint8_t const b1 = fetch();
		if ((b1 & 0x0f) != 0 || ((b1 & 0xc0) != 0 && (b1 & 0xc0) != 0x80))
		{
			trap_b(op);
			return;
		}
		int const count = ((b1 >> 4) & 3) + 1;
		if (b1 & 0x80)
		{
			m_extr = count;
			m_hold_extr = true;
		}
		else
		{
			m_atomic = count;
			m_hold_atomic = true;
		}
		return;
	}
	case 0xdc:
	case 0xd7:
	{
		uint8_t const b1 = fetch();
		uint16_t page = 0;
		bool seg = false;
		if (op == 0xdc)
		{
			page = rreg(b1 & 15);
			seg = ((b1 >> 6) & 1) == 0;
		}
		else
		{
			uint8_t const b2 = fetch();
			uint8_t const b3 = fetch();
			if (b1 & 0x0f)
			{
				trap_b(op);
				return;
			}
			seg = ((b1 >> 6) & 1) == 0;
			page = seg ? b2 : uint16_t(b2 | (uint16_t(b3) << 8));
		}
		int const kind = b1 >> 6;
		m_page_n = ((b1 >> 4) & 3) + 1;
		m_page_seg = seg;
		m_page_val = seg ? (page & 0xff) : (page & 0x3ff);
		m_page_lock = (kind == 0 || kind == 1);
		m_hold_page = true;
		return;
	}

	case 0xcb:
	{
		if (fetch() != 0)
		{
			trap_b(op);
			return;
		}
		uint16_t const ip = pop();
		if (!m_abort)
			m_ip = ip;
		return;
	}
	case 0xdb:
	{
		if (fetch() != 0)
		{
			trap_b(op);
			return;
		}
		uint16_t const ip = pop();
		if (m_abort)
			return;
		uint16_t const csp = pop();
		if (m_abort)
			return;
		m_ip = ip;
		m_csp = csp & 0xff;
		return;
	}
	case 0xfb:
	{
		if (fetch() != 0x88)
		{
			trap_b(op);
			return;
		}
		uint16_t const ip = pop();
		if (m_abort)
			return;
		uint16_t const csp = pop();
		if (m_abort)
			return;
		uint16_t const psw = pop();
		if (m_abort)
			return;
		m_ip = ip;
		m_csp = csp & 0xff;
		m_psw = psw & ~FM;
		return;
	}
	case 0xbb:
	{
		int8_t const rel = int8_t(fetch());
		uint16_t const next = m_ip;
		push(next);
		if (!m_abort)
			m_ip = uint16_t(int32_t(next) + 2 * int32_t(rel));
		m_cycles = 4;
		return;
	}
	case 0xca:
	case 0xea:
	{
		uint8_t const b1 = fetch();
		uint16_t const ip = fetch_w();
		if (b1 & 0x0f)
		{
			trap_b(op);
			return;
		}
		if (!cc_true(b1 >> 4))
			return;
		if (op == 0xca)
		{
			push(m_ip);
			if (m_abort)
				return;
		}
		m_ip = ip;
		m_cycles = 4;
		return;
	}
	case 0xda:
	case 0xfa:
	{
		uint8_t const seg = fetch();
		uint16_t const ip = fetch_w();
		if (m_call_log < 40)
		{
			m_call_log++;
			logerror("ST10 %s %02X:%04X from %02X:%04X\n", (op == 0xda) ? "CALLS" : "JMPS", seg, ip, m_op0_csp, m_op0_ip);
		}
		if (op == 0xda)
		{
			push(m_csp);
			if (m_abort)
				return;
			push(m_ip);
			if (m_abort)
				return;
		}
		m_csp = seg;
		m_ip = ip;
		m_cycles = 4;
		return;
	}
	case 0xab:
	case 0x9c:
	{
		uint8_t const b1 = fetch();
		if (!cc_true(b1 >> 4))
			return;
		uint16_t const target = read_dw(rreg(b1 & 15));
		if (m_abort)
			return;
		if (op == 0xab)
		{
			push(m_ip);
			if (m_abort)
				return;
		}
		m_ip = target;
		m_cycles = 4;
		return;
	}
	case 0x9b:
	{
		uint8_t const b1 = fetch();
		if (b1 & 1)
		{
			trap_b(op);
			return;
		}
		enter_trap(uint16_t(b1) << 1, -1);
		return;
	}
	case 0xe2:
	{
		uint8_t const rr = fetch();
		uint16_t const addr = fetch_w();
		uint16_t const old = rrw(rr);
		push(old);
		if (m_abort)
			return;
		push(m_ip);
		if (!m_abort)
			m_ip = addr;
		return;
	}
	case 0xeb:
	{
		uint8_t const rr = fetch();
		uint16_t const ip = pop();
		if (m_abort)
			return;
		uint16_t const v = pop();
		if (m_abort)
			return;
		m_ip = ip;
		wrw(rr, v);
		return;
	}
	case 0xec:
	{
		uint8_t const rr = fetch();
		push(rrw(rr));
		return;
	}
	case 0xfc:
	{
		uint8_t const rr = fetch();
		uint16_t const v = pop();
		if (!m_abort)
			wrw(rr, v);
		return;
	}
	case 0xc6:
	case 0xd6:
	{
		uint8_t const rr = fetch();
		uint16_t const extra = fetch_w();
		uint16_t src = extra;
		if (op == 0xd6)
		{
			src = read_dw(extra);
			if (m_abort)
				return;
		}
		uint16_t const old = rrw(rr);
		push(old);
		if (!m_abort)
			wrw(rr, src);
		return;
	}

	case 0xf0:
	case 0xe0:
	{
		uint8_t const b1 = fetch();
		uint16_t const v = (op == 0xf0) ? rreg(b1 & 15) : uint16_t(b1 >> 4);
		wreg((op == 0xf0) ? (b1 >> 4) : (b1 & 15), v);
		flags_mov_w(v);
		return;
	}
	case 0xe6:
	case 0xf2:
	case 0xf6:
	{
		uint8_t const rr = fetch();
		uint16_t const extra = fetch_w();
		uint16_t v = extra;
		if (op == 0xf2)
		{
			v = read_dw(extra);
			if (m_abort)
				return;
			wrw(rr, v);
		}
		else if (op == 0xf6)
		{
			v = rrw(rr);
			write_dw(extra, v);
			if (m_abort)
				return;
		}
		else
			wrw(rr, v);
		flags_mov_w(v);
		return;
	}
	case 0xa8: case 0x98: case 0xb8: case 0x88:
	case 0xc8: case 0xd8: case 0xe8:
	case 0xd4: case 0xc4: case 0x84: case 0x94:
	{
		uint8_t const b1 = fetch();
		uint16_t disp = 0;
		bool const has_disp = (op == 0xd4 || op == 0xc4 || op == 0x84 || op == 0x94);
		if (has_disp)
			disp = fetch_w();
		if ((op == 0x84 || op == 0x94) && (b1 & 0xf0))
		{
			trap_b(op);
			return;
		}
		uint16_t v = 0;
		if (op == 0xa8 || op == 0x98)
		{
			uint16_t const a = ptr_use(b1 & 15, (op == 0x98) ? 1 : 0, false);
			v = read_dw(a);
			if (m_abort)
				return;
			wreg(b1 >> 4, v);
		}
		else if (op == 0xb8 || op == 0x88)
		{
			v = rreg(b1 >> 4);
			uint16_t const a = ptr_use(b1 & 15, (op == 0x88) ? -1 : 0, false);
			write_dw(a, v);
			if (m_abort)
				return;
		}
		else if (op == 0xc8 || op == 0xd8 || op == 0xe8)
		{
			uint16_t const sa = ptr_use(b1 & 15, (op == 0xe8) ? 1 : 0, false);
			v = read_dw(sa);
			if (m_abort)
				return;
			uint16_t const da = ptr_use(b1 >> 4, (op == 0xd8) ? 1 : 0, false);
			write_dw(da, v);
			if (m_abort)
				return;
		}
		else if (op == 0xd4)
		{
			v = read_dw(uint16_t(rreg(b1 & 15) + disp));
			if (m_abort)
				return;
			wreg(b1 >> 4, v);
		}
		else if (op == 0xc4)
		{
			v = rreg(b1 >> 4);
			write_dw(uint16_t(rreg(b1 & 15) + disp), v);
			if (m_abort)
				return;
		}
		else if (op == 0x84)
		{
			v = read_dw(disp);
			if (m_abort)
				return;
			write_dw(rreg(b1 & 15), v);
			if (m_abort)
				return;
		}
		else
		{
			v = read_dw(rreg(b1 & 15));
			if (m_abort)
				return;
			write_dw(disp, v);
			if (m_abort)
				return;
		}
		flags_mov_w(v);
		return;
	}

	case 0xf1:
	case 0xe1:
	{
		uint8_t const b1 = fetch();
		uint8_t const v = (op == 0xf1) ? rrb(b1 & 15) : uint8_t(b1 >> 4);
		wrb((op == 0xf1) ? (b1 >> 4) : (b1 & 15), v);
		flags_mov_b(v);
		return;
	}
	case 0xe7:
	case 0xf3:
	case 0xf7:
	{
		uint8_t const rr = fetch();
		uint16_t const extra = fetch_w();
		uint8_t v = extra & 0xff;
		if (op == 0xf3)
		{
			v = read_db(extra);
			wrb_sfr(rr, v);
		}
		else if (op == 0xf7)
		{
			v = rrb_sfr(rr);
			write_db(extra, v);
		}
		else
			wrb_sfr(rr, v);
		flags_mov_b(v);
		return;
	}
	case 0xa9: case 0x99: case 0xb9: case 0x89:
	case 0xc9: case 0xd9: case 0xe9:
	case 0xf4: case 0xe4: case 0xa4: case 0xb4:
	{
		uint8_t const b1 = fetch();
		uint16_t disp = 0;
		if (op == 0xf4 || op == 0xe4 || op == 0xa4 || op == 0xb4)
			disp = fetch_w();
		if ((op == 0xa4 || op == 0xb4) && (b1 & 0xf0))
		{
			trap_b(op);
			return;
		}
		uint8_t v = 0;
		if (op == 0xa9 || op == 0x99)
		{
			uint16_t const a = ptr_use(b1 & 15, (op == 0x99) ? 1 : 0, true);
			v = read_db(a);
			wrb(b1 >> 4, v);
		}
		else if (op == 0xb9 || op == 0x89)
		{
			v = rrb(b1 >> 4);
			uint16_t const a = ptr_use(b1 & 15, (op == 0x89) ? -1 : 0, true);
			write_db(a, v);
		}
		else if (op == 0xc9 || op == 0xd9 || op == 0xe9)
		{
			uint16_t const sa = ptr_use(b1 & 15, (op == 0xe9) ? 1 : 0, true);
			v = read_db(sa);
			uint16_t const da = ptr_use(b1 >> 4, (op == 0xd9) ? 1 : 0, true);
			write_db(da, v);
		}
		else if (op == 0xf4)
		{
			v = read_db(uint16_t(rreg(b1 & 15) + disp));
			wrb(b1 >> 4, v);
		}
		else if (op == 0xe4)
		{
			v = rrb(b1 >> 4);
			write_db(uint16_t(rreg(b1 & 15) + disp), v);
		}
		else if (op == 0xa4)
		{
			v = read_db(disp);
			write_db(rreg(b1 & 15), v);
		}
		else
		{
			v = read_db(rreg(b1 & 15));
			write_db(disp, v);
		}
		flags_mov_b(v);
		return;
	}

	case 0xc0:
	case 0xd0:
	{
		uint8_t const b1 = fetch();
		uint8_t const src = rrb(b1 >> 4);
		uint16_t const v = (op == 0xd0 && (src & 0x80)) ? uint16_t(0xff00 | src) : src;
		wreg(b1 & 15, v);
		m_psw &= ~(FE | FN | FZ);
		if (src == 0)
			m_psw |= FZ;
		if (op == 0xd0 && (src & 0x80))
			m_psw |= FN;
		return;
	}
	case 0xc2: case 0xd2: case 0xc5: case 0xd5:
	{
		uint8_t const rr = fetch();
		uint16_t const addr = fetch_w();
		uint8_t src = 0;
		if (op == 0xc2 || op == 0xd2)
			src = read_db(addr);
		else
			src = rrb_sfr(rr);
		uint16_t const v = ((op == 0xd2 || op == 0xd5) && (src & 0x80)) ? uint16_t(0xff00 | src) : src;
		if (op == 0xc2 || op == 0xd2)
			wrw(rr, v);
		else
		{
			write_dw(addr, v);
			if (m_abort)
				return;
		}
		m_psw &= ~(FE | FN | FZ);
		if (src == 0)
			m_psw |= FZ;
		if ((op == 0xd2 || op == 0xd5) && (src & 0x80))
			m_psw |= FN;
		return;
	}

	case 0x83: case 0x93: case 0xa3: case 0xb3: case 0xc3: case 0xd3:
		exec_mac(op);
		return;

	default:
		fetch();
		trap_b(op);
		return;
	}
}
