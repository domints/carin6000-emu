// license:BSD-3-Clause
// copyright-holders:The MAME Team
/*******************************************************************

    STMicroelectronics ST10F269

    Flat 16 MB of RAM with the internal flash image copied into
    the real flash blocks, and the external AM29F800 image copied
    at 100000. SFR and ESFR accesses are peeled off by the memory
    handler. The core registers (DPP, SP, PSW, the multiply unit)
    live in the C166 base class.

    Timers count once per eight CPU clocks while their run bit is
    set. That is coarse, and it is enough to see a GPT overflow
    without modelling every prescaler. ASC0 accepts a byte on any
    write of S0TBUF and queues received bytes until S0RBUF is read.

*******************************************************************/

#include "emu.h"
#include "st10f269.h"

#include <algorithm>


DEFINE_DEVICE_TYPE(ST10F269, st10f269_device, "st10f269", "STMicroelectronics ST10F269")


namespace {

constexpr uint32_t MEM_BYTES = 0x1000000;

void put_word(uint8_t *base, uint16_t value)
{
	base[0] = value & 0xff;
	base[1] = value >> 8;
}

} // anonymous namespace


st10f269_device::st10f269_device(const machine_config &mconfig, const char *tag, device_t *owner, uint32_t clock)
	: c166_cpu_device(mconfig, ST10F269, tag, owner, clock)
	, m_asc_tx(*this)
	, m_sfr{ }
	, m_esfr{ }
	, m_sfr_seen{ }
	, m_esfr_seen{ }
	, m_line_log(0)
	, m_sfr_log(0)
	, m_wdt(0)
	, m_wdt_hits(0)
	, m_presc(0)
	, m_has_image(false)
	, m_logged_image(false)
	, m_xram1{ }
	, m_xram2{ }
	, m_can1{ }
	, m_can2{ }
	, m_rtc{ }
	, m_pin{ }
	, m_cc_shadow{ }
	, m_flash_state(0)
	, m_flash_status(0x80)
	, m_flash_lock(false)
	, m_bootstrap_arm(false)
	, m_boot_wait(false)
	, m_boot_left(0)
	, m_boot_at(0xfa40)
	, m_adc_left(0)
	, m_adc_busy(false)
	, m_adc_held(false)
	, m_rtc_div(0)
	, m_last_bus(0)
	, m_gpt_prev(0)
{
}

void st10f269_device::device_config_complete()
{
	m_program_config = address_space_config("program", ENDIANNESS_LITTLE, 8, 24, 0, address_map_constructor(FUNC(st10f269_device::internal_map), this));
}

void st10f269_device::internal_map(address_map &map)
{
	map(0x000000, 0xffffff).rw(FUNC(st10f269_device::mem_r), FUNC(st10f269_device::mem_w));
}

void st10f269_device::device_start()
{
	m_mem.assign(MEM_BYTES, 0);
	c166_cpu_device::device_start();

	save_item(NAME(m_sfr));
	save_item(NAME(m_esfr));
	save_item(NAME(m_wdt));
	save_item(NAME(m_wdt_hits));
	save_item(NAME(m_presc));
}

void st10f269_device::load_internal(uint8_t const *data, uint32_t size)
{
	m_int.assign(data, data + size);
}

void st10f269_device::load_external(uint8_t const *data, uint32_t size)
{
	m_ext.assign(data, data + size);
}

void st10f269_device::device_reset()
{
	if (!m_soft_reset)
	{
		std::fill(m_mem.begin(), m_mem.end(), 0);
		if (!m_int.empty())
		{
			uint32_t const low = std::min<uint32_t>(m_int.size(), 0x8000);
			std::copy_n(m_int.begin(), low, m_mem.begin());
			if (m_int.size() > 0x18000)
			{
				uint32_t const end = std::min<uint32_t>(m_int.size(), 0x50000);
				std::copy_n(m_int.begin() + 0x18000, end - 0x18000, m_mem.begin() + 0x18000);
			}
		}
		if (!m_ext.empty())
		{
			uint32_t const n = std::min<uint32_t>(m_ext.size(), 0x100000);
			std::copy_n(m_ext.begin(), n, m_mem.begin() + 0x100000);
		}
		std::fill(std::begin(m_xram1), std::end(m_xram1), 0);
		std::fill(std::begin(m_xram2), std::end(m_xram2), 0);
	}

	std::fill(std::begin(m_sfr), std::end(m_sfr), 0);
	std::fill(std::begin(m_esfr), std::end(m_esfr), 0);
	std::fill(std::begin(m_sfr_seen), std::end(m_sfr_seen), 0);
	std::fill(std::begin(m_esfr_seen), std::end(m_esfr_seen), 0);
	put_word(m_esfr + 0x024, 0x0005); // XPERCON
	put_word(m_esfr + 0x078, 0x0040); // IDPROG
	put_word(m_esfr + 0x07a, 0x3040); // IDMEM
	put_word(m_esfr + 0x07c, 0x10d0); // IDCHIP
	put_word(m_esfr + 0x07e, 0x0401); // IDMANUF

	std::fill(std::begin(m_can1), std::end(m_can1), 0);
	std::fill(std::begin(m_can2), std::end(m_can2), 0);
	m_flash_state = 0;
	m_flash_status = 0x80;
	m_flash_lock = false;
	m_adc_left = 0;
	m_adc_busy = false;
	m_adc_held = false;
	m_last_bus = 0;
	m_gpt_prev = 0;
	m_boot_wait = false;

	m_rx.clear();
	m_line.clear();
	m_wdt = 0;
	m_presc = 0;
	m_has_image = !m_int.empty();
	if (!m_logged_image)
	{
		m_logged_image = true;
		if (m_has_image)
			logerror("ST10 reset vector %02X %02X %02X %02X\n", m_mem[0], m_mem[1], m_mem[2], m_mem[3]);
		else
			logerror("ST10 internal image missing\n");
	}

	c166_cpu_device::device_reset();
	if (!m_soft_reset && m_bootstrap_arm && (m_pin[0] & 0x10) == 0)
	{
		m_wdt_disable = true;
		m_sfr[0x112] = 0x00;
		m_sfr[0x113] = 0x0e;
		m_boot_wait = true;
		m_boot_left = 32;
		m_boot_at = 0xfa40;
		m_halt = true;
		logerror("ST10 bootstrap waiting on ASC0\n");
	}
}

uint16_t st10f269_device::sfr_word(uint32_t addr) const
{
	uint32_t const off = addr - 0xfe00;
	return m_sfr[off] | (uint16_t(m_sfr[off + 1]) << 8);
}

void st10f269_device::sfr_word_set(uint32_t addr, uint16_t data)
{
	uint32_t const off = addr - 0xfe00;
	m_sfr[off] = data & 0xff;
	m_sfr[off + 1] = data >> 8;
}

void st10f269_device::note_write(uint32_t addr, uint8_t data)
{
	if (addr >= 0xfe40 && addr <= 0xfe5f)
		return;
	if (addr >= 0xff40 && addr <= 0xff6f)
		return;
	if (addr == 0xfeb0 || addr == 0xfeb1)
		return;
	bool const esfr = addr >= 0xf000 && addr <= 0xf1ff;
	bool const sfr = addr >= 0xfe00 && addr <= 0xffff;
	if (!esfr && !sfr)
		return;
	uint8_t *seen = esfr ? m_esfr_seen : m_sfr_seen;
	uint32_t const off = addr - (esfr ? 0xf000 : 0xfe00);
	if (seen[off])
		return;
	seen[off] = 1;
	if (m_sfr_log >= 80)
		return;
	m_sfr_log++;
	logerror("ST10 %s W %04X=%02X\n", esfr ? "ESFR" : "SFR", addr, data);
}

uint8_t st10f269_device::sfr_read(uint32_t addr)
{
	if (addr >= 0xf000 && addr <= 0xf1ff)
		return m_esfr[addr - 0xf000];
	if ((addr & ~1u) == 0xfeb2)
	{
		if (addr & 1)
			return 0;
		if (m_rx.empty())
			return 0;
		if (machine().side_effects_disabled())
			return m_rx.front();
		uint8_t const byte = m_rx.front();
		m_rx.pop_front();
		return byte;
	}
	switch (addr & ~1u)
	{
	case 0xff00: case 0xff02: case 0xff04: case 0xff06:
	case 0xffc0: case 0xffc4: case 0xffc8: case 0xffa2:
	case 0xffcc: case 0xffd0: case 0xffd4:
	{
		uint16_t const merged = port_read(addr & ~1u);
		return (addr & 1) ? (merged >> 8) : (merged & 0xff);
	}
	default:
		break;
	}
	if ((addr & ~1u) == 0xfea0 && !(addr & 1) && !machine().side_effects_disabled())
		m_adc_held = false;
	return m_sfr[addr - 0xfe00];
}

void st10f269_device::sfr_write(uint32_t addr, uint8_t data)
{
	if ((addr & ~1u) == 0xf024)
	{
		// XPERCON is frozen once SYSCON.XPEN (bit 2) is set.
		if (sfr_word(0xff12) & 0x0004)
			return;
		m_esfr[addr - 0xf000] = data;
		return;
	}
	if ((addr & ~1u) == 0xff12 && m_einit)
		return;
	if (addr >= 0xf000 && addr <= 0xf1ff)
	{
		m_esfr[addr - 0xf000] = data;
		if ((addr & ~1u) == 0xf0b0 && !(addr & 1))
		{
			// SSCTB write. Bit 0 of SSCCON enables the transfer, bit 1 loops it back.
			if (m_sfr[0x1b2] & 0x01)
			{
				uint8_t const other = m_esfr[0x0b0 + ((addr & 1) ^ 1)];
				uint16_t const word = (addr & 1) ? uint16_t(other | (uint16_t(data) << 8)) : uint16_t(data | (uint16_t(other) << 8));
				uint16_t const echoed = (m_sfr[0x1b2] & 0x02) ? word : 0xffff;
				m_esfr[0x0b2] = echoed & 0xff;
				m_esfr[0x0b3] = echoed >> 8;
				m_sfr[0x174] |= 0x80; // SSCRIC.IR
				m_sfr[0x172] |= 0x80; // SSCTIC.IR
				if (!(m_sfr[0x1b2] & 0x02))
					m_sfr[0x176] |= 0x80; // SSCEIC.IR
			}
		}
		return;
	}
	if ((addr & ~1u) == 0xfeb0)
	{
		m_sfr[addr - 0xfe00] = data;
		if (!(addr & 1))
			tx_byte(data);
		return;
	}
	if (addr >= 0xfe80 && addr < 0xfe88)
	{
		int const ch = (addr - 0xfe80) >> 1;
		if (((sfr_word(0xff52) >> (ch * 4)) & 3) == 3)
		{
			uint16_t shadow = m_cc_shadow[ch];
			if (addr & 1)
				shadow = (shadow & 0x00ff) | (uint16_t(data) << 8);
			else
				shadow = (shadow & 0xff00) | data;
			m_cc_shadow[ch] = shadow;
			return;
		}
	}
	if ((addr & ~1u) == 0xff50)
		m_presc = 0;
	if ((addr & ~1u) == 0xffa0 && !(addr & 1) && (data & 0x80))
	{
		m_adc_busy = true;
		m_adc_left = 200;
	}
	if ((addr & ~1u) == 0xffa2)
		return;
	m_sfr[addr - 0xfe00] = data;
	if ((addr & ~1u) == 0xffc4 && !(addr & 1))
	{
		uint8_t const rose = data & ~m_gpt_prev;
		m_gpt_prev = data;
		if (rose & 1)
		{
			for (int n = 0; n < 5; n++)
			{
				uint8_t const con = m_sfr[0x140 + n * 2];
				int const mode = con & 7;
				if (!(con & 0x40) || (mode != 1 && mode != 3))
					continue;
				uint16_t count = sfr_word(0xfe40 + n * 2);
				count = uint16_t(count + ((mode == 3) ? 2 : 1));
				sfr_word_set(0xfe40 + n * 2, count);
				if (count == 0)
					m_sfr[0x160 + n * 2] |= 0x80;
			}
		}
	}
}

uint8_t st10f269_device::mem_r(offs_t offset)
{
	uint32_t const addr = offset & 0xffffff;
	uint8_t data = 0;
	if (cpu_sfr_r(addr, data))
		return data;
	// Status registers sit in the low flash block. Only a data read sees
	// them; an instruction fetch has to see the programmed byte.
	if (bus_data() && addr == 0x1554)
		return m_flash_status;
	if (bus_data() && addr == 0x1555)
		return 0;
	if (bus_data() && addr == 0x1558)
		return m_last_bus;
	if (xper_on(2) && addr >= 0xe000 && addr < 0xe800)
		return m_xram1[addr - 0xe000];
	if (xper_on(3) && addr >= 0xc000 && addr < 0xe000)
		return m_xram2[addr - 0xc000];
	if (xper_on(0) && addr >= 0xef00 && addr < 0xf000)
		return m_can1[addr - 0xef00];
	if (xper_on(1) && addr >= 0xee00 && addr < 0xef00)
		return m_can2[addr - 0xee00];
	if (xper_on(4) && addr >= 0xec00 && addr < 0xec20)
		return m_rtc[addr - 0xec00];
	if ((addr >= 0xf000 && addr <= 0xf1ff) || (addr >= 0xfe00 && addr <= 0xffff))
		return sfr_read(addr);
	if (bus_data())
		note_bus(addr);
	return m_mem[addr];
}

void st10f269_device::mem_w(offs_t offset, uint8_t data)
{
	uint32_t const addr = offset & 0xffffff;
	if ((addr >= 0xf000 && addr <= 0xf1ff) || (addr >= 0xfe00 && addr <= 0xffff))
		note_write(addr, data);
	if (cpu_sfr_w(addr, data))
		return;
	if (addr == 0x1554 || addr == 0x0aaa || addr == 0x1556)
	{
		if (addr == 0x1556)
			m_flash_lock = data == 0xa5;
		else if (addr == 0x1554 && data == 0xaa && m_flash_state == 0)
			m_flash_state = 1;
		else if (addr == 0x0aaa && data == 0x55 && m_flash_state == 1)
			m_flash_state = 2;
		else if (addr == 0x1554 && data == 0xa0 && m_flash_state == 2)
			m_flash_state = 3;
		else if (addr == 0x1554 && data == 0x80 && m_flash_state == 2)
			m_flash_state = 4;
		else if (addr == 0x1554 && data == 0xaa && m_flash_state == 4)
			m_flash_state = 5;
		else if (addr == 0x0aaa && data == 0x55 && m_flash_state == 5)
			m_flash_state = 6;
		else
			m_flash_state = 0;
		// Command writes are swallowed by the flash state machine. They must
		// not modify the array: 0AAA and 1554 sit inside the first code block.
		return;
	}
	// A program or erase command is consumed by the next write into a flash
	// block. GPR, stack and SFR writes in between are ordinary memory traffic.
	if (m_flash_state == 3 && flash_block(addr) >= 0)
	{
		m_flash_state = 0;
		if (!flash_program(addr, data))
			m_flash_status = 0x81;
		else
			m_flash_status = 0x80;
		return;
	}
	if (m_flash_state == 6 && data == 0x30 && flash_block(addr) >= 0)
	{
		m_flash_state = 0;
		if (m_flash_lock && addr >= 0x20000)
			m_flash_status = 0x81;
		else
		{
			flash_erase(flash_block(addr));
			m_flash_status = 0x80;
		}
		return;
	}
	if (xper_on(2) && addr >= 0xe000 && addr < 0xe800)
	{
		m_xram1[addr - 0xe000] = data;
		return;
	}
	if (xper_on(3) && addr >= 0xc000 && addr < 0xe000)
	{
		m_xram2[addr - 0xc000] = data;
		return;
	}
	if (xper_on(0) && addr >= 0xef00 && addr < 0xf000)
	{
		if ((addr & ~1u) == 0xef06 && (m_can1[0] & 0x41) == 0)
			return;
		m_can1[addr - 0xef00] = data;
		service_can(0);
		return;
	}
	if (xper_on(1) && addr >= 0xee00 && addr < 0xef00)
	{
		if ((addr & ~1u) == 0xee06 && (m_can2[0] & 0x41) == 0)
			return;
		m_can2[addr - 0xee00] = data;
		service_can(1);
		return;
	}
	if (xper_on(4) && addr >= 0xec00 && addr < 0xec20)
	{
		bool const off = (m_rtc[0] & 0x80) != 0;
		bool const writable = off || addr <= 0xec01 || addr >= 0xec12;
		if (writable)
		{
			m_rtc[addr - 0xec00] = data;
			// A new prescale or a stopped counter starts the divider clean.
			if ((addr >= 0xec06 && addr <= 0xec09) || (addr <= 0xec01 && (data & 0x80)))
				m_rtc_div = 0;
		}
		return;
	}
	if ((addr >= 0xf000 && addr <= 0xf1ff) || (addr >= 0xfe00 && addr <= 0xffff))
	{
		sfr_write(addr, data);
		return;
	}
	if (bus_data())
		note_bus(addr);
	m_mem[addr] = data;
}

void st10f269_device::tx_byte(uint8_t data)
{
	// S0LB is S0CON.14. A looped byte also joins the receive queue.
	if (m_sfr[0x1b1] & 0x40)
		asc_rx(data);
	if (!m_asc_tx.isunset())
		m_asc_tx(data);
	m_sfr[0x16c] |= 0x80;  // S0TIC.IR
	m_esfr[0x19c] |= 0x80; // S0TBIC.IR

	if (m_line_log >= 400)
		return;
	if (data == '\n' || data == '\r' || m_line.size() >= 80)
	{
		if (!m_line.empty())
		{
			m_line_log++;
			logerror("ST10 ASC0: %s\n", m_line);
			m_line.clear();
		}
		return;
	}
	if (data >= 0x20 && data < 0x7f)
		m_line.push_back(char(data));
	else
		m_line += util::string_format("<%02X>", data);
}

void st10f269_device::asc_rx(uint8_t data)
{
	if (m_boot_wait)
	{
		if (m_boot_at < m_mem.size())
			m_mem[m_boot_at++] = data;
		if (--m_boot_left <= 0)
		{
			m_boot_wait = false;
			m_halt = false;
			m_csp = 0;
			m_ip = 0xfa40;
			logerror("ST10 bootstrap jump FA40\n");
		}
		return;
	}
	if (m_rx.size() >= 64)
	{
		m_sfr[0x1b1] |= 0x08; // S0OE
		return;
	}
	m_rx.push_back(data);
}

void st10f269_device::tick_timer(uint32_t count_addr, uint32_t reload_addr, uint32_t ic_addr, bool run, int ticks)
{
	if (!run || ticks <= 0)
		return;
	uint16_t count = sfr_word(count_addr);
	uint16_t const reload = reload_addr ? sfr_word(reload_addr) : 0;
	uint32_t left = ticks;
	uint32_t const period = 0x10000u - reload;
	if (uint32_t(count) + left < 0x10000u)
		count = uint16_t(count + left);
	else
	{
		uint32_t const past = uint32_t(count) + left - 0x10000u;
		uint32_t const step = period ? period : 0x10000u;
		count = uint16_t(reload + (past % step));
		m_sfr[ic_addr - 0xfe00] |= 0x80;
	}
	sfr_word_set(count_addr, count);
}

void st10f269_device::burn_cycles(int cycles)
{
	if (!m_wdt_disable)
	{
		m_wdt += cycles;
		uint32_t const rel = m_sfr[0x1af];
		uint32_t const period = 512u * (256u - rel);
		if (m_wdt >= period)
		{
			m_wdt = 0;
			m_wdt_hits++;
			logerror("ST10 watchdog reset %u\n", m_wdt_hits);
			if (m_wdt_hits > 6)
				m_halt = true;
			m_reset_pending = true;
		}
	}

	if (!m_pwrdn)
		tick_rtc(cycles);
	tick_adc(cycles);

	m_presc += cycles;
	int const ticks = m_presc / 8;
	m_presc %= 8;
	if (ticks > 0)
	{
		tick_pwm(ticks);
		bool const t0run = m_sfr[0x150] & 0x40;
		bool const t1run = m_sfr[0x151] & 0x40;
		tick_timer(0xfe50, 0xfe54, 0xff9c, t0run, ticks);
		tick_timer(0xfe52, 0xfe56, 0xff9e, t1run, ticks);
		for (int n = 0; n < 5; n++)
		{
			uint8_t const con = m_sfr[0x140 + n * 2];
			bool const run = con & 0x40;
			int const mode = con & 7;
			bool const gate = (m_pin[3] & 1) || (m_sfr[0x1c4] & 1);
			if (mode == 0 || (mode == 2 && gate))
				tick_timer(0xfe40 + n * 2, 0, 0xff60 + n * 2, run, ticks);
		}
		// Compare against the count after it has stepped.
		tick_capcom(ticks);
	}
	// PEC follows the request flag and does not wait for a timer tick or IEN.
	service_pec();
}

void st10f269_device::poll_peripherals()
{
	if (!m_rx.empty() && !(m_sfr[0x16e] & 0x80))
		m_sfr[0x16e] |= 0x80;
	service_pec();
}

bool st10f269_device::pick_irq(int cpu_ilvl, uint16_t &vector, int &level)
{
	struct source { uint16_t ic; uint16_t vec; bool esfr; };
	// Datasheet table 7, all 56 request nodes.
	static source const sources[] = {
		{ 0xff78, 0x0040, false }, { 0xff7a, 0x0044, false }, { 0xff7c, 0x0048, false }, { 0xff7e, 0x004c, false },
		{ 0xff80, 0x0050, false }, { 0xff82, 0x0054, false }, { 0xff84, 0x0058, false }, { 0xff86, 0x005c, false },
		{ 0xff88, 0x0060, false }, { 0xff8a, 0x0064, false }, { 0xff8c, 0x0068, false }, { 0xff8e, 0x006c, false },
		{ 0xff90, 0x0070, false }, { 0xff92, 0x0074, false }, { 0xff94, 0x0078, false }, { 0xff96, 0x007c, false },
		{ 0xf160, 0x00c0, true }, { 0xf162, 0x00c4, true }, { 0xf164, 0x00c8, true }, { 0xf166, 0x00cc, true },
		{ 0xf168, 0x00d0, true }, { 0xf16a, 0x00d4, true }, { 0xf16c, 0x00d8, true }, { 0xf16e, 0x00dc, true },
		{ 0xf170, 0x00e0, true }, { 0xf172, 0x00e4, true }, { 0xf174, 0x00e8, true }, { 0xf176, 0x00ec, true },
		{ 0xf178, 0x00f0, true },
		{ 0xf184, 0x0110, true }, { 0xf18c, 0x0114, true }, { 0xf194, 0x0118, true },
		{ 0xff9c, 0x0080, false }, { 0xff9e, 0x0084, false },
		{ 0xf17a, 0x00f4, true }, { 0xf17c, 0x00f8, true },
		{ 0xff60, 0x0088, false }, { 0xff62, 0x008c, false }, { 0xff64, 0x0090, false },
		{ 0xff66, 0x0094, false }, { 0xff68, 0x0098, false },
		{ 0xff6a, 0x009c, false },
		{ 0xff98, 0x00a0, false }, { 0xff9a, 0x00a4, false },
		{ 0xff6c, 0x00a8, false }, { 0xf19c, 0x011c, true }, { 0xff6e, 0x00ac, false }, { 0xff70, 0x00b0, false },
		{ 0xff72, 0x00b4, false }, { 0xff74, 0x00b8, false }, { 0xff76, 0x00bc, false },
		{ 0xf17e, 0x00fc, true },
		{ 0xf186, 0x0100, true }, { 0xf18e, 0x0104, true }, { 0xf196, 0x0108, true }, { 0xf19e, 0x010c, true },
	};

	bool found = false;
	int best_ilvl = cpu_ilvl;
	int best_glvl = -1;
	for (source const &src : sources)
	{
		uint8_t const low = src.esfr ? m_esfr[src.ic - 0xf000] : m_sfr[src.ic - 0xfe00];
		if ((low & 0xc0) != 0xc0)
			continue;
		int const ilvl = (low >> 2) & 15;
		int const glvl = low & 3;
		if (ilvl == 0 || ilvl <= cpu_ilvl)
			continue;
		if (found && (ilvl < best_ilvl || (ilvl == best_ilvl && glvl <= best_glvl)))
			continue;
		found = true;
		best_ilvl = ilvl;
		best_glvl = glvl;
		vector = src.vec;
		level = ilvl;
	}
	return found;
}

void st10f269_device::on_einit()
{
	auto word = [this](uint32_t addr)
	{
		if (addr >= 0xf000 && addr <= 0xf1ff)
			return uint16_t(m_esfr[addr - 0xf000] | (uint16_t(m_esfr[addr - 0xf000 + 1]) << 8));
		return sfr_word(addr);
	};
	logerror("ST10 SYSCON=%04X BUSCON0=%04X BUSCON1=%04X BUSCON2=%04X ADDRSEL1=%04X ADDRSEL2=%04X XPERCON=%04X\n",
		word(0xff12), word(0xff0c), word(0xff14), word(0xff16), word(0xfe18), word(0xfe1a), word(0xf024));
}

void st10f269_device::on_srvwdt()
{
	m_wdt = 0;
}

void st10f269_device::set_pin(unsigned port, uint16_t value)
{
	if (port < 9)
		m_pin[port] = value;
}

uint16_t st10f269_device::esfr_word(uint32_t addr) const
{
	uint32_t const off = addr - 0xf000;
	return m_esfr[off] | (uint16_t(m_esfr[off + 1]) << 8);
}

void st10f269_device::esfr_word_set(uint32_t addr, uint16_t data)
{
	uint32_t const off = addr - 0xf000;
	m_esfr[off] = data & 0xff;
	m_esfr[off + 1] = data >> 8;
}

bool st10f269_device::xper_on(int bit) const
{
	return (sfr_word(0xff12) & 0x0004) && (esfr_word(0xf024) & (1u << bit));
}

uint16_t st10f269_device::port_read(uint32_t addr)
{
	struct map { uint32_t data; uint32_t dir; uint32_t odp; int pin; bool wide; bool esfr_dir; bool esfr_odp; };
	static map const ports[] = {
		{ 0xff00, 0xf100, 0, 0, false, true, true },
		{ 0xff02, 0xf102, 0, 0, false, true, true },
		{ 0xff04, 0xf104, 0, 1, false, true, true },
		{ 0xff06, 0xf106, 0, 1, false, true, true },
		{ 0xffc0, 0xffc2, 0xf1c2, 2, true, false, true },
		{ 0xffc4, 0xffc6, 0xf1c6, 3, true, false, true },
		{ 0xffc8, 0xffca, 0xf1ca, 4, false, false, true },
		{ 0xffa2, 0, 0, 5, true, false, false },
		{ 0xffcc, 0xffce, 0xf1ce, 6, false, false, true },
		{ 0xffd0, 0xffd2, 0xf1d2, 7, false, false, true },
		{ 0xffd4, 0xffd6, 0xf1d6, 8, false, false, true },
	};
	for (map const &p : ports)
	{
		if (p.data != addr)
			continue;
		if (p.dir == 0)
			return m_pin[p.pin];
		uint16_t const latch = sfr_word(p.data);
		uint16_t const dir = p.esfr_dir ? esfr_word(p.dir) : sfr_word(p.dir);
		uint16_t const odp = p.odp ? esfr_word(p.odp) : 0;
		uint16_t const pin = m_pin[p.pin];
		uint16_t const driven = dir & ~odp;
		uint16_t const value = (latch & driven) | (pin & ~driven);
		return p.wide ? value : (value & 0xff);
	}
	return sfr_word(addr);
}

void st10f269_device::note_bus(uint32_t addr)
{
	int cs = 0;
	uint16_t con = 0;
	for (int i = 1; i <= 4; i++)
	{
		uint16_t const sel = sfr_word(0xfe18 + (i - 1) * 2);
		con = sfr_word(0xff14 + (i - 1) * 2);
		if (!(con & 0x0400))
			continue;
		uint32_t const start = uint32_t(sel & 0xfff0) << 8;
		uint32_t const size = 0x1000u << (sel & 0x0f);
		if (addr >= start && addr < start + size)
		{
			cs = i;
			break;
		}
	}
	if (!cs)
		return;
	int waits = (con >> 4) & 0x0f;
	bool const ready = (con & 0x1000) != 0;
	if (ready)
		waits += 3;
	if ((addr & 1) == 0)
		add_waits(waits);
	uint8_t status = uint8_t(cs & 7);
	if (((con >> 14) & 3) < 2)
		status |= 0x08;
	if (ready)
		status |= 0x80;
	if (m_pin[3] & 0x0002)
		status |= 0x40;
	m_last_bus = status;
}

int st10f269_device::flash_block(uint32_t addr) const
{
	static uint32_t const start[] = { 0x00000, 0x04000, 0x06000, 0x18000, 0x20000, 0x30000, 0x40000 };
	static uint32_t const end[] = { 0x04000, 0x06000, 0x08000, 0x20000, 0x30000, 0x40000, 0x50000 };
	for (int i = 0; i < 7; i++)
		if (addr >= start[i] && addr < end[i])
			return i;
	return -1;
}

void st10f269_device::flash_erase(int block)
{
	static uint32_t const start[] = { 0x00000, 0x04000, 0x06000, 0x18000, 0x20000, 0x30000, 0x40000 };
	static uint32_t const end[] = { 0x04000, 0x06000, 0x08000, 0x20000, 0x30000, 0x40000, 0x50000 };
	if (block < 0 || block > 6)
		return;
	for (uint32_t a = start[block]; a < end[block] && a < m_mem.size(); a++)
		m_mem[a] = 0xff;
}

bool st10f269_device::flash_program(uint32_t addr, uint8_t data)
{
	if (flash_block(addr) < 0)
		return false;
	if (m_flash_lock && addr >= 0x20000)
		return false;
	if (addr >= m_mem.size())
		return false;
	m_mem[addr] &= data;
	return true;
}

void st10f269_device::service_pec()
{
	for (int ch = 0; ch < 8; ch++)
	{
		uint16_t pecc = sfr_word(0xfec0 + ch * 2);
		int const count = pecc >> 8;
		if (count == 0)
			continue;
		int const src = (pecc >> 4) & 7;
		static uint16_t const trig[] = { 0xff9c, 0xff9e, 0xff60, 0xff62, 0xff64, 0xff66, 0xff68, 0xff6c };
		uint16_t const ic = trig[src];
		if ((m_sfr[ic - 0xfe00] & 0x80) == 0)
			continue;
		uint16_t const sp = m_mem[0xfce0 + ch * 2] | (uint16_t(m_mem[0xfce1 + ch * 2]) << 8);
		uint16_t const dp = m_mem[0xfde0 + ch * 2] | (uint16_t(m_mem[0xfde1 + ch * 2]) << 8);
		bool const byte = pecc & 1;
		int const inc = (pecc >> 2) & 3;
		int const step = byte ? 1 : 2;
		if (byte)
		{
			if (sp < m_mem.size() && dp < m_mem.size())
				m_mem[dp] = m_mem[sp];
		}
		else if ((sp & 1) == 0 && (dp & 1) == 0 && sp + 1 < m_mem.size() && dp + 1 < m_mem.size())
		{
			m_mem[dp] = m_mem[sp];
			m_mem[dp + 1] = m_mem[sp + 1];
		}
		uint16_t ns = sp;
		uint16_t nd = dp;
		if (inc & 2)
			ns = uint16_t(sp + step);
		if (inc & 1)
			nd = uint16_t(dp + step);
		m_mem[0xfce0 + ch * 2] = ns & 0xff;
		m_mem[0xfce1 + ch * 2] = ns >> 8;
		m_mem[0xfde0 + ch * 2] = nd & 0xff;
		m_mem[0xfde1 + ch * 2] = nd >> 8;
		int const left = count - 1;
		pecc = uint16_t((left << 8) | (pecc & 0x00ff));
		sfr_word_set(0xfec0 + ch * 2, pecc);
		m_sfr[ic - 0xfe00] &= 0x7f;
		if (left == 0)
			m_sfr[ic - 0xfe00] |= 0x80;
	}
}

void st10f269_device::deliver_can(int src, uint32_t id, bool extended, uint8_t dlc, uint8_t const *data)
{
	int const dst = src ^ 1;
	uint8_t *mod = dst ? m_can2 : m_can1;
	if (!xper_on(dst))
		return;
	if (mod[0] & 0x01)
		return;
	uint32_t const mask = extended
		? (uint32_t(mod[0x0a] | (uint16_t(mod[0x0b]) << 8)) << 16) | uint32_t(mod[0x0c] | (uint16_t(mod[0x0d]) << 8))
		: uint32_t(mod[0x08] | (uint16_t(mod[0x09]) << 8)) & 0x7ff;
	for (int n = 0; n < 15; n++)
	{
		uint8_t *obj = mod + 0x10 + n * 0x10;
		uint16_t const mcr = obj[0] | (uint16_t(obj[1]) << 8);
		uint16_t const mcfg = obj[6] | (uint16_t(obj[7]) << 8);
		if ((mcr & 0x8000) == 0 || (mcr & 0x0200) || (mcfg & 0x0010))
			continue;
		bool const xtd = (mcfg & 0x0020) != 0;
		if (xtd != extended)
			continue;
		uint32_t const filter = (uint32_t(obj[2] | (uint16_t(obj[3]) << 8)) << 16) | uint32_t(obj[4] | (uint16_t(obj[5]) << 8));
		uint32_t const cmp_id = extended ? id : (id & 0x7ff);
		uint32_t const cmp_f = extended ? filter : (filter & 0x7ff);
		if (((cmp_id ^ cmp_f) & mask) != 0)
			continue;
		int const nbyte = dlc > 8 ? 8 : dlc;
		for (int b = 0; b < nbyte; b++)
			obj[8 + b] = data[b];
		uint16_t next = (mcr & ~0x0400) | 0x0100;
		if (mcr & 0x2000)
		{
			next |= 0x1000;
			uint32_t const ic = dst ? 0xf18e : 0xf186;
			m_esfr[ic - 0xf000] |= 0x80;
		}
		obj[0] = next & 0xff;
		obj[1] = next >> 8;
		mod[2] |= 0x02;
		return;
	}
}

void st10f269_device::service_can(int which)
{
	uint8_t *mod = which ? m_can2 : m_can1;
	if (mod[0] & 0x01)
		return;
	for (int n = 0; n < 15; n++)
	{
		uint8_t *obj = mod + 0x10 + n * 0x10;
		uint16_t const mcr = obj[0] | (uint16_t(obj[1]) << 8);
		uint16_t const mcfg = obj[6] | (uint16_t(obj[7]) << 8);
		if ((mcr & 0x8400) != 0x8400 || (mcr & 0x0200) || (mcfg & 0x0010) == 0)
			continue;
		bool const extended = (mcfg & 0x0020) != 0;
		uint32_t const id = (uint32_t(obj[2] | (uint16_t(obj[3]) << 8)) << 16) | uint32_t(obj[4] | (uint16_t(obj[5]) << 8));
		uint8_t const dlc = mcfg & 0x0f;
		bool const listener = xper_on(which ^ 1) && ((which ? m_can1 : m_can2)[0] & 0x01) == 0;
		if (!listener)
		{
			int tec = mod[3] + 8;
			if (tec > 255)
				tec = 255;
			mod[3] = uint8_t(tec);
			if (tec >= 96)
				mod[2] |= 0x40;
			if (tec >= 255)
			{
				mod[2] |= 0x80;
				mod[0] |= 0x01;
			}
		}
		else
		{
			deliver_can(which, id, extended, dlc, obj + 8);
			if (mod[3] > 0)
				mod[3]--;
		}
		uint16_t next = (mcr & ~0x0400);
		if (mcr & 0x4000)
		{
			next |= 0x1000;
			uint32_t const ic = which ? 0xf18e : 0xf186;
			m_esfr[ic - 0xf000] |= 0x80;
		}
		obj[0] = next & 0xff;
		obj[1] = next >> 8;
		mod[2] |= 0x01;
		mod[0x0e] = obj[4];
		mod[0x0f] = obj[5];
		return;
	}
}

void st10f269_device::tick_rtc(int cycles)
{
	if (!xper_on(4))
		return;
	if (m_rtc[0] & 0x80)
		return;
	uint32_t const prescale = uint32_t(m_rtc[6] | (uint16_t(m_rtc[7]) << 8)) | (uint32_t(m_rtc[8] & 0x0f) << 16);
	uint32_t const ratio = 64u * (prescale ? prescale : 1u);
	m_rtc_div += cycles;
	uint32_t ticks = m_rtc_div / ratio;
	m_rtc_div %= ratio;
	if (!ticks)
		return;
	m_rtc[0] |= 0x01;
	uint32_t count = uint32_t(m_rtc[0x0e] | (uint16_t(m_rtc[0x0f]) << 8)) | (uint32_t(m_rtc[0x10] | (uint16_t(m_rtc[0x11]) << 8)) << 16);
	uint32_t const alarm = uint32_t(m_rtc[0x12] | (uint16_t(m_rtc[0x13]) << 8)) | (uint32_t(m_rtc[0x14] | (uint16_t(m_rtc[0x15]) << 8)) << 16);
	count += ticks;
	if ((m_rtc[0] & 0x08) && count == alarm)
		m_rtc[0] |= 0x04;
	m_rtc[0x0e] = count & 0xff;
	m_rtc[0x0f] = (count >> 8) & 0xff;
	m_rtc[0x10] = (count >> 16) & 0xff;
	m_rtc[0x11] = (count >> 24) & 0xff;
	uint16_t const sel = esfr_word(0xf1da);
	// EX2 (CC10IC) alternate source is RTCSI. EX3 (CC11IC) alternate source is RTCAI.
	if (((sel >> 4) & 3) == 1)
		m_sfr[0x18c] |= 0x80;
	if ((m_rtc[0] & 0x0c) == 0x0c && ((sel >> 6) & 3) == 1)
		m_sfr[0x18e] |= 0x80;
}

void st10f269_device::tick_pwm(int ticks)
{
	uint16_t const con = sfr_word(0xff30);
	for (int ch = 0; ch < 4; ch++)
	{
		if ((con & (1u << ch)) == 0)
			continue;
		uint16_t pt = esfr_word(0xf030 + ch * 2);
		uint16_t const pp = esfr_word(0xf038 + ch * 2);
		uint16_t const pw = sfr_word(0xfe30 + ch * 2);
		uint16_t const period = pp ? pp : 1;
		pt = uint16_t((pt + ticks) % period);
		esfr_word_set(0xf030 + ch * 2, pt);
		uint16_t latch = sfr_word(0xffd0);
		if (pt < pw)
			latch |= uint16_t(1u << ch);
		else
			latch &= ~uint16_t(1u << ch);
		sfr_word_set(0xffd0, latch);
		if (pt == 0)
			m_esfr[0x17e] |= 0x80;
	}
}

void st10f269_device::tick_capcom(int ticks)
{
	(void)ticks;
	uint16_t const t0 = sfr_word(0xfe50);
	uint16_t const mode = sfr_word(0xff52);
	for (int ch = 0; ch < 4; ch++)
	{
		int const m = (mode >> (ch * 4)) & 3;
		uint16_t const cc = sfr_word(0xfe80 + ch * 2);
		if (m == 2 && t0 == cc)
			m_sfr[0x178 + ch * 2] |= 0x80;
		if (m == 3 && t0 == cc)
		{
			m_sfr[0x178 + ch * 2] |= 0x80;
			sfr_word_set(0xfe80 + ch * 2, m_cc_shadow[ch]);
		}
	}
	uint16_t const cc16 = sfr_word(0xfe60);
	if (t0 == cc16 && (sfr_word(0xff20) & 0x0003) == 2)
	{
		m_esfr[0x160] |= 0x80;
		if (sfr_word(0xffd6) & 0x0001)
		{
			uint16_t p8 = sfr_word(0xffd4);
			p8 |= 0x0001;
			sfr_word_set(0xffd4, p8);
		}
	}
}

void st10f269_device::tick_adc(int cycles)
{
	if (!m_adc_busy)
		return;
	m_adc_left -= cycles;
	if (m_adc_left > 0)
		return;
	m_adc_busy = false;
	m_adc_left = 0;
	uint16_t const con = sfr_word(0xffa0);
	int const channel = con & 0x0f;
	uint16_t const sample = uint16_t((channel * 64 + 7) & 0x3ff);
	if ((con & 0x40) && m_adc_held)
	{
		m_sfr[0x19a] |= 0x80;
		return;
	}
	sfr_word_set(0xfea0, sample);
	m_adc_held = true;
	m_sfr[0x198] |= 0x80;
	m_sfr[0x1a0] = uint8_t(con & 0x7f);
}
