// license:BSD-3-Clause
// copyright-holders:The MAME Team
/*******************************************************************

    Toshiba TMP92FD54A / TMP92FD54AIF

    The 900/H1 core is the existing tlcs900h_device. This file is the
    single-chip memory map and the I/O the radio firmware touches on
    the way out of reset: ports, the 8-bit and 16-bit timers, the two
    SIO channels, the interrupt controller, and the watchdog.

    SFR addresses are the TMP92CD54I map (section 5 of that manual).
    The FD54 is that chip with 512 KB of flash in place of the mask
    ROM. Flash block programming is not implemented; the image is
    read-only. Vector numbers past INT7 follow the 900/H1 order
    (eight 8-bit timers, then SIO0/SIO1, then the 16-bit timers).

*******************************************************************/

#include "emu.h"
#include "tmp92fd54.h"
#include "dasm900.h"

#include <algorithm>


DEFINE_DEVICE_TYPE(TMP92FD54, tmp92fd54_device, "tmp92fd54", "Toshiba TMP92FD54AIF")


namespace {

constexpr uint32_t FLASH_BYTES = 0x80000;
constexpr uint32_t RAM_BYTES = 0x8000;

// Cause bit sits above the 3-bit priority. shift 0 is the low nibble, 4 the high.
struct irq_src
{
	uint16_t inte;
	uint8_t cause;
	uint8_t shift;
	uint8_t vector;
	int16_t mk;       // INTMK register, or -1
	uint8_t mk_bit;
};

irq_src const s_irq[] = {
	{ 0x0f0, 0x08, 0, 0x28, -1, 0 }, // INT0
	{ 0x0d0, 0x08, 0, 0x2c, -1, 0 }, // INT1
	{ 0x0d0, 0x80, 4, 0x30, -1, 0 }, // INT2
	{ 0x0d1, 0x08, 0, 0x34, -1, 0 }, // INT3
	{ 0x0d1, 0x80, 4, 0x38, -1, 0 }, // INT4
	{ 0x0d2, 0x08, 0, 0x3c, -1, 0 }, // INT5
	{ 0x0d2, 0x80, 4, 0x40, -1, 0 }, // INT6
	{ 0x0d3, 0x08, 0, 0x44, -1, 0 }, // INT7
	{ 0x0d4, 0x08, 0, 0x48, -1, 0 }, // INTT0
	{ 0x0d4, 0x80, 4, 0x4c, -1, 0 }, // INTT1
	{ 0x0d5, 0x08, 0, 0x50, -1, 0 }, // INTT2
	{ 0x0d5, 0x80, 4, 0x54, -1, 0 }, // INTT3
	{ 0x0d6, 0x08, 0, 0x58, -1, 0 }, // INTT4
	{ 0x0d6, 0x80, 4, 0x5c, -1, 0 }, // INTT5
	{ 0x0d7, 0x08, 0, 0x60, -1, 0 }, // INTT6
	{ 0x0d7, 0x80, 4, 0x64, -1, 0 }, // INTT7
	{ 0x0db, 0x08, 0, 0x68, 0x0e8, 0x01 }, // INTRX0  INTMK3 bit 0
	{ 0x0db, 0x80, 4, 0x6c, 0x0e8, 0x02 }, // INTTX0  INTMK3 bit 1
	{ 0x0dc, 0x08, 0, 0x70, 0x0e8, 0x04 }, // INTRX1
	{ 0x0dc, 0x80, 4, 0x74, 0x0e8, 0x08 }, // INTTX1
	{ 0x0d8, 0x08, 0, 0x78, -1, 0 }, // INTTR8
	{ 0x0d8, 0x80, 4, 0x7c, -1, 0 }, // INTTR9
	{ 0x0d9, 0x08, 0, 0x80, -1, 0 }, // INTTRA
	{ 0x0d9, 0x80, 4, 0x84, -1, 0 }, // INTTRB
};

std::pair<u16, char const *> const s_syms[] = {
	{ 0x0000, "P0" }, { 0x0002, "P0CR" }, { 0x0003, "P0FC" },
	{ 0x0010, "P4" }, { 0x0012, "P4CR" }, { 0x0013, "P4FC" },
	{ 0x001c, "P7" }, { 0x001e, "P7CR" }, { 0x001f, "P7FC" },
	{ 0x0030, "PC" }, { 0x0032, "PCCR" }, { 0x0033, "PCFC" },
	{ 0x0034, "PD" }, { 0x0036, "PDCR" }, { 0x0037, "PDFC" },
	{ 0x003c, "PF" }, { 0x003e, "PFCR" }, { 0x003f, "PFFC" },
	{ 0x0040, "PG" }, { 0x0054, "PL" },
	{ 0x0058, "PM" }, { 0x0059, "PMODE" }, { 0x005a, "PMCR" }, { 0x005b, "PMFC" },
	{ 0x005c, "PN" }, { 0x005d, "PNODE" }, { 0x005e, "PNCR" }, { 0x005f, "PNFC" },
	{ 0x0060, "SECR0" }, { 0x0061, "SESR0" }, { 0x0062, "SEDR0" },
	{ 0x0080, "TRUN01" }, { 0x0082, "TREG0" }, { 0x0083, "TREG1" }, { 0x0084, "TMOD01" }, { 0x0085, "TFFCR1" },
	{ 0x0088, "TRUN23" }, { 0x008a, "TREG2" }, { 0x008b, "TREG3" }, { 0x008c, "TMOD23" }, { 0x008d, "TFFCR3" },
	{ 0x0090, "TRUN45" }, { 0x0092, "TREG4" }, { 0x0093, "TREG5" }, { 0x0094, "TMOD45" }, { 0x0095, "TFFCR5" },
	{ 0x0098, "TRUN67" }, { 0x009a, "TREG6" }, { 0x009b, "TREG7" }, { 0x009c, "TMOD67" }, { 0x009d, "TFFCR7" },
	{ 0x00a0, "TRUN8" }, { 0x00a2, "TMOD8" }, { 0x00a3, "TFFCR8" },
	{ 0x00a8, "TREG8L" }, { 0x00a9, "TREG8H" }, { 0x00aa, "TREG9L" }, { 0x00ab, "TREG9H" },
	{ 0x00ac, "CAP8L" }, { 0x00ad, "CAP8H" }, { 0x00ae, "CAP9L" }, { 0x00af, "CAP9H" },
	{ 0x00b0, "TRUNA" }, { 0x00b2, "TMODA" }, { 0x00b3, "TFFCRA" },
	{ 0x00b8, "TREGAL" }, { 0x00b9, "TREGAH" }, { 0x00ba, "TREGBL" }, { 0x00bb, "TREGBH" },
	{ 0x00c0, "SC0BUF" }, { 0x00c1, "SC0CR" }, { 0x00c2, "SC0MOD0" }, { 0x00c3, "BR0CR" }, { 0x00c4, "BR0ADD" }, { 0x00c5, "SC0MOD1" },
	{ 0x00c8, "SC1BUF" }, { 0x00c9, "SC1CR" }, { 0x00ca, "SC1MOD0" }, { 0x00cb, "BR1CR" }, { 0x00cc, "BR1ADD" }, { 0x00cd, "SC1MOD1" },
	{ 0x00d0, "INTE12" }, { 0x00d1, "INTE34" }, { 0x00d2, "INTE56" }, { 0x00d3, "INTE7" },
	{ 0x00d4, "INTET01" }, { 0x00d5, "INTET23" }, { 0x00d6, "INTET45" }, { 0x00d7, "INTET67" },
	{ 0x00d8, "INTET89" }, { 0x00d9, "INTETAB" }, { 0x00da, "INTETO8A" },
	{ 0x00db, "INTES0" }, { 0x00dc, "INTES1" },
	{ 0x00e5, "INTMK0" }, { 0x00e6, "INTMK1" }, { 0x00e7, "INTMK2" },
	{ 0x00e8, "INTMK3" }, { 0x00e9, "INTMK4" }, { 0x00ea, "INTMK5" },
	{ 0x00f0, "INTE0AD" }, { 0x00f6, "IIMC" }, { 0x00f7, "INTNMWDT" }, { 0x00f8, "INTCLR" },
	{ 0x0100, "DMA0V" }, { 0x010a, "CLKMOD" },
	{ 0x0110, "WDMOD" }, { 0x0111, "WDCR" },
	{ 0x0118, "RTCCR" },
	{ 0x0138, "ADMOD0" }, { 0x0139, "ADMOD1" },
	{ 0x0148, "BCSL" }, { 0x0149, "BCSH" }, { 0x014a, "MAMR" }, { 0x014b, "MSAR" },
	{ 0x016b, "FSWE" }, { 0x016d, "RAMCR" }, { 0x016e, "FLSR" },
	{ 0x0170, "SBI0CR1" }, { 0x0171, "SBI0DBR" }, { 0x0178, "SBI1CR1" }, { 0x0179, "SBI1DBR" },
	{ 0x0180, "SBI2CR1" }, { 0x0181, "SBI2DBR" },
};

char const *sfr_name(offs_t offset)
{
	auto const found = std::lower_bound(
			std::begin(s_syms), std::end(s_syms), uint16_t(offset),
			[] (auto const &sym, uint16_t addr) { return sym.first < addr; });
	if (found != std::end(s_syms) && found->first == offset)
		return found->second;
	return nullptr;
}

int port_cr(offs_t data)
{
	switch (data)
	{
	case 0x00: return 0x02;
	case 0x10: return 0x12;
	case 0x1c: return 0x1e;
	case 0x30: return 0x32;
	case 0x34: return 0x36;
	case 0x3c: return 0x3e;
	case 0x58: return 0x5a;
	case 0x5c: return 0x5e;
	default: return -1;
	}
}

uint8_t cause_mask(offs_t offset)
{
	uint8_t mask = 0;
	for (irq_src const &src : s_irq)
		if (src.inte == offset)
			mask |= src.cause;
	return mask;
}

} // anonymous namespace


tmp92fd54_device::tmp92fd54_device(const machine_config &mconfig, const char *tag, device_t *owner, uint32_t clock)
	: tlcs900h_device(mconfig, TMP92FD54, tag, owner, clock)
	, m_tx0(*this)
	, m_tx1(*this)
	, m_sfr{ }
	, m_rx{ 0, 0 }
	, m_rx_full{ false, false }
	, m_pre{ }
	, m_tcount{ }
	, m_t16{ }
	, m_t16pre{ }
	, m_wd_count(0)
	, m_sfr_log(0)
	, m_seen{ }
	, m_ext_seen{ }
	, m_ext_n(0)
	, m_irq_seen(0)
	, m_trace(nullptr)
{
}

void tmp92fd54_device::device_config_complete()
{
	// External data bus is 8-bit. The core accesses memory a byte at a time.
	m_program_config = address_space_config("program", ENDIANNESS_LITTLE, 8, 24, 0, address_map_constructor(FUNC(tmp92fd54_device::internal_map), this));
}

void tmp92fd54_device::internal_map(address_map &map)
{
	map(0x000000, 0xffffff).rw(FUNC(tmp92fd54_device::ext_r), FUNC(tmp92fd54_device::ext_w));
	map(0x000000, 0x0003ff).rw(FUNC(tmp92fd54_device::sfr_r), FUNC(tmp92fd54_device::sfr_w));
	map(0x000400, 0x000400 + RAM_BYTES - 1).ram();
	map(0xf80000, 0xffffff).rw(FUNC(tmp92fd54_device::flash_r), FUNC(tmp92fd54_device::flash_w));
}

void tmp92fd54_device::device_start()
{
	m_flash.assign(FLASH_BYTES, 0xff);

	tlcs900h_device::device_start();

	m_nmi_state = CLEAR_LINE;
	std::fill(std::begin(m_level), std::end(m_level), int(CLEAR_LINE));

	m_trace = timer_alloc(FUNC(tmp92fd54_device::trace_pc), this);

	save_item(NAME(m_sfr));
	save_item(NAME(m_rx));
	save_item(NAME(m_rx_full));
	save_item(NAME(m_pre));
	save_item(NAME(m_tcount));
	save_item(NAME(m_t16));
	save_item(NAME(m_t16pre));
	save_item(NAME(m_wd_count));
}

void tmp92fd54_device::load_flash(uint8_t const *data, uint32_t size)
{
	if (m_flash.size() != FLASH_BYTES)
		m_flash.assign(FLASH_BYTES, 0xff);
	uint32_t const n = std::min(size, FLASH_BYTES);
	std::copy_n(data, n, m_flash.begin());
	if (n < FLASH_BYTES)
		std::fill(m_flash.begin() + n, m_flash.end(), 0xff);
}

void tmp92fd54_device::device_reset()
{
	std::fill(std::begin(m_sfr), std::end(m_sfr), 0);
	// Watchdog runs out of reset until the firmware clears WDMOD bit 7.
	m_sfr[0x110] = 0x80;
	// BCSL after reset: BWW = 010, BWR = 010. BCSH: chip select enabled.
	m_sfr[0x148] = 0x42;
	m_sfr[0x149] = 0x80;
	// TMOD8 bit 5 reads as 1.
	m_sfr[0x0a2] = 0x20;
	m_sfr[0x0b2] = 0x20;
	// INTMK3-5 reset to "enabled". The earlier masks follow that.
	for (offs_t reg = 0x0e5; reg <= 0x0ea; reg++)
		m_sfr[reg] = 0xff;

	std::fill(std::begin(m_pre), std::end(m_pre), 0);
	std::fill(std::begin(m_tcount), std::end(m_tcount), 0);
	std::fill(std::begin(m_t16), std::end(m_t16), 0);
	std::fill(std::begin(m_t16pre), std::end(m_t16pre), 0);
	m_rx[0] = m_rx[1] = 0;
	m_rx_full[0] = m_rx_full[1] = false;
	m_wd_count = 0;
	m_sfr_log = 0;
	std::fill(std::begin(m_seen), std::end(m_seen), 0);
	m_ext_n = 0;
	m_irq_seen = 0;

	tlcs900h_device::device_reset();

	// An unprogrammed image vectors into 0xffffff and would spin on SWI.
	if ((m_pc.d & 0x00ffffff) == 0x00ffffff)
	{
		m_halted = 1;
		m_sfr[0x110] = 0;
		logerror("reset with empty flash, halted\n");
	}
	else
	{
		logerror("reset PC=%06X\n", m_pc.d & 0x00ffffff);
		m_trace->adjust(attotime::from_msec(200), 0, attotime::from_msec(200));
	}
}

void tmp92fd54_device::trace_pc(int param)
{
	if (param >= 12)
	{
		m_trace->enable(false);
		return;
	}
	m_trace->adjust(attotime::from_msec(200), param + 1, attotime::from_msec(200));
	logerror("PC=%06X SP=%06X SR=%04X\n", m_pc.d & 0x00ffffff, m_xssp.d & 0x00ffffff, m_sr.w.l);
}

void tmp92fd54_device::rx_w(unsigned channel, uint8_t data)
{
	if (channel > 1)
		return;
	if (m_rx_full[channel])
		m_sfr[channel ? 0x0c9 : 0x0c1] |= 0x10; // OERR
	m_rx[channel] = data;
	m_rx_full[channel] = true;
	raise_cause(channel ? 0x0dc : 0x0db, 0x08);
}


uint8_t tmp92fd54_device::flash_r(offs_t offset)
{
	return offset < m_flash.size() ? m_flash[offset] : 0xff;
}

void tmp92fd54_device::flash_w(offs_t offset, uint8_t data)
{
	if (m_sfr_log < 8)
	{
		m_sfr_log++;
		logerror("%06X flash W %06X=%02X ignored\n", m_pc.d & 0x00ffffff, 0xf80000 + offset, data);
	}
}

uint8_t tmp92fd54_device::ext_r(offs_t offset)
{
	if (!machine().side_effects_disabled() && m_ext_n < 32)
	{
		bool seen = false;
		for (int i = 0; i < m_ext_n; i++)
			seen = seen || m_ext_seen[i] == offset;
		if (!seen)
		{
			m_ext_seen[m_ext_n++] = offset;
			logerror("%06X external R %06X\n", m_pc.d & 0x00ffffff, offset);
		}
	}
	return 0xff;
}

void tmp92fd54_device::ext_w(offs_t offset, uint8_t data)
{
	if (!machine().side_effects_disabled() && m_ext_n < 32)
	{
		bool seen = false;
		for (int i = 0; i < m_ext_n; i++)
			seen = seen || m_ext_seen[i] == offset;
		if (!seen)
		{
			m_ext_seen[m_ext_n++] = offset;
			logerror("%06X external W %06X=%02X\n", m_pc.d & 0x00ffffff, offset, data);
		}
	}
}

void tmp92fd54_device::note_sfr(char dir, offs_t offset, uint8_t data)
{
	if (machine().side_effects_disabled() || offset >= 0x400 || m_sfr_log >= 160)
		return;
	uint8_t const bit = dir == 'W' ? 0x02 : 0x01;
	if (m_seen[offset] & bit)
		return;
	m_seen[offset] |= bit;
	m_sfr_log++;
	char const *name = sfr_name(offset);
	if (name)
		logerror("%06X %c %s=%02X\n", m_pc.d & 0x00ffffff, dir, name, data);
	else
		logerror("%06X %c %03X=%02X\n", m_pc.d & 0x00ffffff, dir, offset, data);
}

uint8_t tmp92fd54_device::sfr_r(offs_t offset)
{
	uint8_t data = m_sfr[offset];
	int const cr = port_cr(offset);
	if (cr >= 0)
	{
		// Output bits read the latch. Input bits idle high until something drives them.
		uint8_t const dir = m_sfr[cr];
		data = (m_sfr[offset] & dir) | (0xff & ~dir);
	}
	else if (offset == 0x00c0 || offset == 0x00c8)
	{
		unsigned const channel = offset == 0x00c8;
		data = m_rx[channel];
		// INTRX is cleared by reading the receive buffer, not by INTCLR.
		if (!machine().side_effects_disabled() && m_rx_full[channel])
		{
			m_rx_full[channel] = false;
			m_sfr[channel ? 0x0dc : 0x0db] &= ~0x08;
		}
	}
	else if (offset == 0x00c1 || offset == 0x00c9)
	{
		// OERR, PERR and FERR clear on read.
		if (!machine().side_effects_disabled())
			m_sfr[offset] &= ~0x1c;
	}

	note_sfr('R', offset, data);
	return data;
}

void tmp92fd54_device::raise_cause(offs_t inte, uint8_t bit)
{
	if (m_sfr[inte] & bit)
		return;
	m_sfr[inte] |= bit;
	m_check_irqs = 1;
}

void tmp92fd54_device::tx_byte(unsigned channel, uint8_t data)
{
	if (channel == 0)
		m_tx0(data);
	else
		m_tx1(data);
	// The buffer is empty again on the next poll. INTTX is the "done" flag.
	raise_cause(channel ? 0x0dc : 0x0db, 0x80);
}

void tmp92fd54_device::sfr_w(offs_t offset, uint8_t data)
{
	note_sfr('W', offset, data);

	if (offset == 0x00c0 || offset == 0x00c8)
	{
		tx_byte(offset == 0x00c8, data);
		return;
	}

	if (offset == 0x0111)
	{
		// WDCR. 0xB1 is the clear code; anything else is ignored.
		if (data == 0xb1)
			m_wd_count = 0;
		return;
	}

	if (offset == 0x00f8)
	{
		// INTCLR is written with vector/4. 0x0A clears INT0 (vector 0x28).
		for (irq_src const &src : s_irq)
			if (src.vector == uint8_t(data << 2))
				m_sfr[src.inte] &= ~src.cause;
		return;
	}

	// Cause bits are read-only. A write updates the priority field only.
	uint8_t const sticky = cause_mask(offset);
	if (sticky)
		m_sfr[offset] = (data & ~sticky) | (m_sfr[offset] & sticky);
	else
		m_sfr[offset] = data;

	if (offset >= 0x00d0 && offset <= 0x00f8)
		m_check_irqs = 1;
}


void tmp92fd54_device::tlcs900_check_hdma()
{
}

void tmp92fd54_device::tlcs900_handle_ad()
{
}

void tmp92fd54_device::execute_set_input(int inputnum, int state)
{
	if (inputnum == INPUT_LINE_NMI || inputnum == TLCS900_NMI)
	{
		if (m_level[TLCS900_NMI] == CLEAR_LINE && state == ASSERT_LINE)
		{
			m_nmi_state = ASSERT_LINE;
			m_check_irqs = 1;
		}
		m_level[TLCS900_NMI] = state;
		return;
	}

	// INT0 is TLCS900_INT0. Rising edge sets the cause bit.
	static int const pins[8] = {
		TLCS900_INT0, TLCS900_INT1, TLCS900_INT2, TLCS900_INT3,
		TLCS900_INT4, TLCS900_INT5, TLCS900_INT6, TLCS900_INT7
	};
	for (int i = 0; i < 8; i++)
	{
		if (inputnum != pins[i])
			continue;
		if (m_level[pins[i]] == CLEAR_LINE && state != CLEAR_LINE)
			raise_cause(s_irq[i].inte, s_irq[i].cause);
		m_level[pins[i]] = state;
		return;
	}
}

void tmp92fd54_device::tlcs900_handle_timers()
{
	// Four 8-bit pairs. Prescaler runs while bit 2 of TRUNxx is set.
	// Clock select 01/10/11 is phiT1 / phiT4 / phiT16, counted the same
	// way as the TMP95C063 (divisors 128, 512, 2048 of the prescaler).
	for (int pair = 0; pair < 4; pair++)
	{
		offs_t const trun_at = 0x80 + pair * 8;
		uint8_t const trun = m_sfr[trun_at];
		uint8_t const tmod = m_sfr[trun_at + 4];
		uint32_t const old = m_pre[pair];
		if (trun & 0x04)
			m_pre[pair] += m_cycles;

		for (int n = 0; n < 2; n++)
		{
			if (!(trun & (1 << n)))
				continue;
			uint8_t const sel = (tmod >> (n * 2)) & 0x03;
			if (sel == 0)
				continue;
			int const shift = n == 0
				? (sel == 1 ? 7 : sel == 2 ? 9 : 11)
				: (sel == 1 ? 7 : sel == 2 ? 11 : 15);
			int ticks = int((m_pre[pair] >> shift) - (old >> shift));
			int const index = pair * 2 + n;
			uint8_t const treg = m_sfr[trun_at + 2 + n];
			for (; ticks > 0; ticks--)
			{
				m_tcount[index]++;
				if (m_tcount[index] == treg)
				{
					m_tcount[index] = 0;
					raise_cause(0x0d4 + pair, n ? 0x80 : 0x08);
				}
			}
		}
	}

	// Timer 8 and timer A. Bit 0 runs the counter; clock select is TMOD bits 1-0.
	for (int channel = 0; channel < 2; channel++)
	{
		offs_t const base = channel ? 0x00b0 : 0x00a0;
		if (!(m_sfr[base] & 0x01))
			continue;
		uint8_t const sel = m_sfr[base + 2] & 0x03;
		if (sel == 0)
			continue;
		int const shift = sel == 1 ? 7 : sel == 2 ? 9 : 11;
		uint32_t const old = m_t16pre[channel];
		m_t16pre[channel] += m_cycles;
		int ticks = int((m_t16pre[channel] >> shift) - (old >> shift));
		uint16_t const treg = m_sfr[base + 8] | (uint16_t(m_sfr[base + 9]) << 8);
		uint16_t const treg2 = m_sfr[base + 0x0a] | (uint16_t(m_sfr[base + 0x0b]) << 8);
		for (; ticks > 0; ticks--)
		{
			m_t16[channel]++;
			// TREG8 is the mid compare. TREG9 is the period. If only TREG8
			// is programmed, that compare reloads the counter.
			if (treg && m_t16[channel] == treg)
				raise_cause(0x0d8 + channel, 0x08);
			if (treg2 && m_t16[channel] == treg2)
			{
				m_t16[channel] = 0;
				raise_cause(0x0d8 + channel, 0x80);
			}
			else if (!treg2 && treg && m_t16[channel] == treg)
				m_t16[channel] = 0;
		}
	}

	// Watchdog starts at reset. A 0xB1 write to WDCR kicks it. Clearing
	// WDMOD bit 7 stops it. 2^24 clocks at 20 MHz is about 0.8 s.
	if (m_sfr[0x110] & 0x80)
	{
		m_wd_count += m_cycles;
		if (m_wd_count >= (1u << 24))
		{
			m_wd_count = 0;
			logerror("watchdog reset\n");
			device_reset();
			return;
		}
	}
}

void tmp92fd54_device::tlcs900_check_irqs()
{
	if (m_nmi_state == ASSERT_LINE)
	{
		tlcs900_intnest_accept();
		m_xssp.d -= 4;
		WRMEML(m_xssp.d, m_pc.d);
		m_xssp.d -= 2;
		WRMEMW(m_xssp.d, m_sr.w.l);
		m_pc.d = RDMEML(0xffff00 + 0x20) & 0x00ffffff;
		m_cycles += 18;
		m_prefetch_clear = true;
		m_halted = 0;
		m_nmi_state = CLEAR_LINE;
		return;
	}

	int const iff = (m_sr.b.h & 0x70) >> 4;
	int best_level = 0;
	int best = -1;
	for (int i = 0; i < int(std::size(s_irq)); i++)
	{
		irq_src const &src = s_irq[i];
		if (!(m_sfr[src.inte] & src.cause))
			continue;
		int const level = (m_sfr[src.inte] >> src.shift) & 0x07;
		// Priority 0 and 7 both mean "masked" on this interrupt controller.
		if (level == 0 || level >= 7 || level < iff)
			continue;
		if (src.mk >= 0 && !(m_sfr[src.mk] & src.mk_bit))
			continue;
		if (best < 0 || level > best_level || (level == best_level && src.vector < s_irq[best].vector))
		{
			best = i;
			best_level = level;
		}
	}
	if (best < 0)
		return;

	irq_src const &src = s_irq[best];
	m_sfr[src.inte] &= ~src.cause;

	tlcs900_intnest_accept();
	m_xssp.d -= 4;
	WRMEML(m_xssp.d, m_pc.d);
	m_xssp.d -= 2;
	WRMEMW(m_xssp.d, m_sr.w.l);

	int const mask = std::min(7, best_level + 1);
	m_sr.b.h = (m_sr.b.h & 0x8f) | (mask << 4);
	m_pc.d = RDMEML(0xffff00 + src.vector) & 0x00ffffff;
	m_cycles += 18;
	m_prefetch_clear = true;
	m_halted = 0;

	if (!(m_irq_seen & (1ull << (src.vector >> 2))))
	{
		m_irq_seen |= 1ull << (src.vector >> 2);
		logerror("irq vector %02X -> %06X\n", src.vector, m_pc.d);
	}
}


std::unique_ptr<util::disasm_interface> tmp92fd54_device::create_disassembler()
{
	return std::make_unique<tlcs900_disassembler>(s_syms);
}
