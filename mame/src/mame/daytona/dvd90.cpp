// license:BSD-3-Clause
// copyright-holders:The MAME Team
/***************************************************************************

    Opel DVD90 navigation radio (Siemens VDO EHU4C, NAV-DVD production)

    The navigation CPU is a Toshiba R3900 core (TMPR3903F class: R3000A plus
    the TX39 extensions, 4 KB instruction cache, 1 KB data cache), running
    OS-9000. BC0F/BC0T test the write buffer: the condition is true when the
    buffer is empty. Addresses below are physical, which is what the MIPS
    core's address map sees:

        00000000-01ffffff  32 MB DRAM          (kseg0 80000000)
        40000000-41ffffff  same DRAM, kuseg image (user virtual 00000000)
        10000000-10001fff  8 KB SRAM           (kseg1 b0000000)
        1fc00000-          boot image lowboot  (kseg1 bfc00000, reset vector)
        ff800000-ff80ffff  display controller (cgdc), driver dr_video
        ff900000-ff90ffff  RoadRunner peripherals (IDE glue, I2C, GPIO,
                           timers, system control, interrupt controller)
        ff904100-ff9044ff  four UARTs, 0x100 apart. +08 status
                           (bit 1 rx ready, bit 12 tx empty), +10 data
        ff910000-ff91ffff  interrupt sub-controller, 16550 debug UART
        ffc00000-ffc0007f  ATA task file, 4-byte stride (cdboot)
        fffe6000-fffe601f  NAND (SmartMedia) controller
        fffeb000-fffeb0ff  DMA controller

    The first-stage ROM is not on the update CD. lowboot from
    V_3/HVM0/0104/EHU4C is the OS-9 bootstrap (edition 65) linked to run at
    the reset vector, so it stands in for that ROM. lowboot is built with
    MIPS II branch-likely instructions, so the core runs with those enabled.

    NAND controller (fffe6000), as driven by lowboot:
        +00  data port. Reads have one access of latency: the first read
             after a mode change returns a dummy byte.
        +04  control. 0x15 command, 0x16 address, 0x14 data, 0x34 data with
             ECC accumulation, 0x54 read back the six ECC bytes, 0x04 idle.
        +08  status, bit 7 busy.
    Pages are 512 bytes plus a 16-byte spare area with SmartMedia ECC
    (bytes 8-10 for the second half, 13-15 for the first half).

    DMA channel at fffeb020: +00 control, +04 start, +08 source,
    +0c destination (physical), +10 byte count, +14 mode, +18 status
    (bit 23 done, bits 19-22 error).

    The map disc (cd/NAV_DB_21709.iso) belongs on the ASIC's ATAPI port,
    which is not wired up yet. The TLCS-900 radio CPU sits on the other side
    of a UART / DIPC link and is not emulated.

***************************************************************************/

#include "emu.h"
#include "cpu/mips/mips1.h"
#include "imagedev/cdromimg.h"
#include "screen.h"

#include <bit>
#include <cstdlib>
#include <fstream>
#include <string>
#include <unordered_map>
#include <vector>


namespace {

constexpr uint32_t NAND_PAGE = 512;
constexpr uint32_t NAND_SPARE = 16;
constexpr uint32_t NAND_RAW_PAGE = NAND_PAGE + NAND_SPARE;
constexpr uint32_t NAND_PAGES = 64 * 1024 * 1024 / NAND_PAGE; // 64 MB, 4 address cycles
constexpr uint32_t NAND_PAGES_PER_BLOCK = 32;
constexpr uint8_t NAND_MAKER = 0xec;  // Samsung
constexpr uint8_t NAND_DEVICE = 0x76; // K9F1208, 64 MB

constexpr offs_t NAND_BASE = 0xfffe6000;
constexpr offs_t DMA_BASE = 0xfffeb000;

// SmartMedia (SSFDC) ECC over 256 bytes: two bytes of line parity and one of column parity.
void smartmedia_ecc(const uint8_t *data, uint8_t ecc[3])
{
	uint8_t col = 0;
	uint16_t line_even = 0, line_odd = 0;
	for (int i = 0; i < 256; i++)
	{
		uint8_t const b = data[i];
		col ^= b;
		if (std::popcount(b) & 1)
		{
			line_odd ^= i;
			line_even ^= ~i & 0xff;
		}
	}

	// interleave the line parities: bit pairs (odd, even) per address bit
	uint16_t line = 0;
	for (int bit = 0; bit < 8; bit++)
	{
		line |= BIT(line_even, bit) << (bit * 2);
		line |= BIT(line_odd, bit) << (bit * 2 + 1);
	}
	uint8_t cp = 0;
	cp |= (BIT(col, 0) ^ BIT(col, 2) ^ BIT(col, 4) ^ BIT(col, 6)) << 2; // CP0
	cp |= (BIT(col, 1) ^ BIT(col, 3) ^ BIT(col, 5) ^ BIT(col, 7)) << 3; // CP1
	cp |= (BIT(col, 0) ^ BIT(col, 1) ^ BIT(col, 4) ^ BIT(col, 5)) << 4; // CP2
	cp |= (BIT(col, 2) ^ BIT(col, 3) ^ BIT(col, 6) ^ BIT(col, 7)) << 5; // CP3
	cp |= (BIT(col, 0) ^ BIT(col, 1) ^ BIT(col, 2) ^ BIT(col, 3)) << 6; // CP4
	cp |= (BIT(col, 4) ^ BIT(col, 5) ^ BIT(col, 6) ^ BIT(col, 7)) << 7; // CP5

	// stored inverted, so an erased page (all 0xff) carries ff ff ff
	ecc[0] = ~uint8_t(line);
	ecc[1] = ~uint8_t(line >> 8);
	ecc[2] = ~cp | 0x03;
}


class opel_dvd90_state : public driver_device
{
public:
	opel_dvd90_state(const machine_config &mconfig, device_type type, const char *tag)
		: driver_device(mconfig, type, tag)
		, m_navcpu(*this, "navcpu")
		, m_cdrom(*this, "cdrom")
	{ }

	void opel_dvd90(machine_config &config);
	uint32_t screen_update(screen_device &screen, bitmap_rgb32 &bitmap, const rectangle &cliprect);

protected:
	virtual void machine_start() override ATTR_COLD;
	virtual void machine_reset() override ATTR_COLD;
	void machine_stop();

private:
	void navcpu_map(address_map &map) ATTR_COLD;

	uint32_t asic_r(offs_t offset, uint32_t mem_mask);
	void asic_w(offs_t offset, uint32_t data, uint32_t mem_mask);
	bool uart_r(offs_t address, uint32_t &data);
	bool uart_w(offs_t address, uint32_t data, uint32_t mem_mask);
	void uart_flush(unsigned channel);
	void log_asic(const char *dir, offs_t address, uint32_t data, uint32_t mem_mask);
	uint32_t unmapped_r(offs_t offset, uint32_t mem_mask);
	void unmapped_w(offs_t offset, uint32_t data, uint32_t mem_mask);
	void heartbeat(int param);
	std::string backtrace();

	bool timer_r(offs_t address, uint32_t &data);
	bool timer_w(offs_t address, uint32_t data, uint32_t mem_mask);
	void timer_schedule(int channel);
	void timer_tick(int channel);
	void tick_schedule();
	void tick_fire(int param);
	void cd_irq_drop(int param);
	bool irq_r(offs_t address, uint32_t &data);
	bool irq_w(offs_t address, uint32_t data, uint32_t mem_mask);
	void irq_sync();

	bool cd_r(offs_t address, uint32_t &data);
	bool cd_w(offs_t address, uint32_t data, uint32_t mem_mask);
	void cd_command(uint8_t command);
	void cd_packet();
	uint8_t cd_byte(uint32_t index);
	uint32_t timer_now() const;

	uint32_t nand_r(offs_t reg);
	void nand_w(offs_t reg, uint32_t data);
	uint8_t nand_data_read();
	void nand_data_write(uint8_t data);
	void nand_command(uint8_t command);
	void nand_address(uint8_t data);
	uint8_t nand_fetch();
	void nand_ecc_reset();

	void dma_w(offs_t reg, uint32_t data);
	void dma_run(unsigned channel);

	required_device<r3041_device> m_navcpu;
	required_device<cdrom_image_device> m_cdrom;

	emu_timer *m_heartbeat = nullptr;
	emu_timer *m_pit[8] = { };
	emu_timer *m_tick = nullptr;
	emu_timer *m_cd_irq_timer = nullptr;
	uint32_t m_timer_ctrl[8] = { };
	uint32_t m_timer_cmp[8] = { };
	uint32_t m_timer_pending = 0;
	uint32_t m_timer_log = 0;
	uint32_t m_tcu_ctrl = 0;
	uint32_t m_tcu_scale = 0;
	uint32_t m_tcu_period = 0;
	uint32_t m_tcu_status = 0;

	uint32_t m_cd_reg[32] = { };
	uint8_t m_cd_buf[512] = { };
	uint8_t m_cd_cache[2048] = { };
	uint8_t m_cd_cdb[16] = { };
	uint32_t m_cd_cached = 0xffffffff;
	uint32_t m_cd_lba = 0xffffffff;
	uint32_t m_cd_count = 0;
	uint32_t m_cd_pos = 0;
	uint32_t m_cd_cdb_pos = 0;
	uint32_t m_cd_log = 0;
	uint32_t m_cd_irq = 0;
	uint32_t m_cd_vector = 0;
	uint8_t m_cd_status = 0x50;
	uint32_t m_irq_mask0 = 0;
	uint32_t m_irq_mask1 = 0;
	uint32_t m_irq_pair = 0;
	uint32_t m_irq_status = 0;
	uint32_t m_irq_index = 0;
	uint32_t m_asic_log = 0;
	uint32_t m_unmapped_log = 0;
	uint32_t m_nand_log = 0;
	std::unordered_map<offs_t, uint32_t> m_regs;

	// NAND
	std::vector<uint8_t> m_nand;
	std::string m_nand_path;
	bool m_nand_dirty = false;
	uint8_t m_nand_ctrl = 0;
	uint8_t m_nand_cmd = 0;
	uint8_t m_nand_addr[4] = { };
	unsigned m_nand_addr_count = 0;
	uint32_t m_nand_page = 0;
	uint32_t m_nand_col = 0;
	bool m_nand_id_mode = false;
	unsigned m_nand_id_pos = 0;
	bool m_nand_status_mode = false;
	uint8_t m_nand_latch = 0xff;
	bool m_nand_primed = false;
	uint8_t m_nand_ecc_buf[NAND_PAGE] = { };
	unsigned m_nand_ecc_pos = 0;
	unsigned m_nand_ecc_read = 0;
	uint8_t m_nand_prog[NAND_RAW_PAGE] = { };

	// DMA
	uint32_t m_dma[8][8] = { };

	// UART transmit capture, one line per channel, and a receive queue
	std::string m_uart_line[4];
	std::string m_uart_rx[4];
	uint32_t m_uart_log = 0;
};

void opel_dvd90_state::navcpu_map(address_map &map)
{
	// Installed first so the ranges below replace it. Stops MAME logging every miss.
	map(0x00000000, 0xffffffff).rw(FUNC(opel_dvd90_state::unmapped_r), FUNC(opel_dvd90_state::unmapped_w));
	// DRAM is visible twice: kseg0 strips to physical 0, kuseg adds 0x40000000.
	map(0x00000000, 0x01ffffff).ram().share("dram");
	map(0x40000000, 0x41ffffff).ram().share("dram");
	map(0x10000000, 0x10001fff).ram();
	map(0x1fc00000, 0x1fc65fff).rom().region("boot", 0);
	// kseg2 is not translated by the TLB-less core, so these stay at 0xff......
	map(0xff000000, 0xffffffff).rw(FUNC(opel_dvd90_state::asic_r), FUNC(opel_dvd90_state::asic_w));
}

void opel_dvd90_state::log_asic(const char *dir, offs_t address, uint32_t data, uint32_t mem_mask)
{
	if (machine().side_effects_disabled())
		return;
	if (m_asic_log >= 3000)
	{
		if (m_asic_log == 3000)
			logerror("RoadRunner: further register log suppressed\n");
		m_asic_log++;
		return;
	}
	m_asic_log++;
	logerror("%s RR %s %08X = %08X mask=%08X\n", machine().describe_context(), dir, address, data, mem_mask);
}

uint32_t opel_dvd90_state::asic_r(offs_t offset, uint32_t mem_mask)
{
	offs_t const address = 0xff000000 + (offset << 2);
	if (address >= NAND_BASE && address < NAND_BASE + 0x20)
		return nand_r((address - NAND_BASE) >> 2);

	uint32_t block_data = 0;
	if (timer_r(address, block_data) || irq_r(address, block_data))
		return block_data;

	uint32_t uart_data = 0;
	if (uart_r(address, uart_data))
		return uart_data;

	uint32_t cd_data = 0;
	if (cd_r(address, cd_data))
		return cd_data;

	uint32_t data = 0;
	if (address >= DMA_BASE && address < DMA_BASE + 0x100)
	{
		offs_t const index = (address - DMA_BASE) >> 2;
		return m_dma[index >> 3][index & 7];
	}
	else
	{
		auto const found = m_regs.find(address);
		if (found != m_regs.end())
			data = found->second;
	}
	log_asic("R", address, data, mem_mask);
	return data;
}

void opel_dvd90_state::asic_w(offs_t offset, uint32_t data, uint32_t mem_mask)
{
	offs_t const address = 0xff000000 + (offset << 2);
	if (address >= NAND_BASE && address < NAND_BASE + 0x20)
	{
		nand_w((address - NAND_BASE) >> 2, data);
		return;
	}
	if (address >= DMA_BASE && address < DMA_BASE + 0x100)
	{
		dma_w((address - DMA_BASE) >> 2, data);
		return;
	}
	if (uart_w(address, data, mem_mask) || timer_w(address, data, mem_mask) || irq_w(address, data, mem_mask) || cd_w(address, data, mem_mask))
		return;
	log_asic("W", address, data, mem_mask);
	uint32_t &reg = m_regs[address];
	reg = (reg & ~mem_mask) | (data & mem_mask);
}

// lowboot's console driver. Four channels at ff904100, ff904200, ff904300 and
// ff904400. Status +08: bit 1 is "rx byte waiting", bit 12 is "tx holding
// register empty". The data register is a byte at +10.
bool opel_dvd90_state::uart_r(offs_t address, uint32_t &data)
{
	if (address < 0xff904100 || address >= 0xff904500)
		return false;
	offs_t const reg = (address - 0xff904100) & 0xff;
	unsigned const channel = (address - 0xff904100) >> 8;
	if (reg == 0x08)
	{
		// Bit 12 is the transmit holding register empty. Bit 0 makes the
		// scspiluart ISR claim the interrupt, bit 1 says a byte is waiting
		// in +0x10.
		data = 0x00001000;
		if (!m_uart_rx[channel].empty())
			data |= 0x00000003;
		return true;
	}
	if (reg == 0x10)
	{
		data = 0;
		if (!m_uart_rx[channel].empty())
		{
			// The driver reads one byte. Repeat it in every lane so the
			// access lands regardless of which byte the core extracts.
			uint8_t const byte = m_uart_rx[channel].front();
			data = byte * 0x01010101;
			if (!machine().side_effects_disabled())
			{
				m_uart_rx[channel].erase(m_uart_rx[channel].begin());
				irq_sync();
			}
		}
		return true;
	}
	return false;
}

bool opel_dvd90_state::uart_w(offs_t address, uint32_t data, uint32_t mem_mask)
{
	if (address < 0xff904100 || address >= 0xff904500)
		return false;
	offs_t const reg = (address - 0xff904100) & 0xff;
	if (reg != 0x10)
		return false;

	unsigned const channel = (address - 0xff904100) >> 8;
	uint8_t byte = data & 0xff;
	for (int shift = 24; shift >= 0; shift -= 8)
		if (mem_mask & (0xffu << shift))
		{
			byte = (data >> shift) & 0xff;
			break;
		}
	if (byte == '\n' || byte == '\r')
		uart_flush(channel);
	else if (byte >= 0x20 && byte < 0x7f)
		m_uart_line[channel].push_back(char(byte));
	else
		m_uart_line[channel] += util::string_format("<%02X>", byte);
	if (m_uart_line[channel].size() >= 160)
		uart_flush(channel);
	return true;
}

void opel_dvd90_state::uart_flush(unsigned channel)
{
	if (m_uart_line[channel].empty())
		return;
	// The guest repeats "DIPC init failed" once per tick. Keep the first copy
	// so the later console lines stay inside the log cap.
	static std::string previous[4];
	if (m_uart_line[channel] == previous[channel])
	{
		m_uart_line[channel].clear();
		return;
	}
	previous[channel] = m_uart_line[channel];
	// The development shell blocks on a read straight after this line, and
	// sysgo waits for the shell. The prompt itself carries no newline, so
	// answer here, while the line is being flushed.
	if (channel == 0 && m_uart_line[channel].compare(0, 14, "Starting shell") == 0 && m_uart_rx[channel].empty())
	{
		m_uart_rx[channel] = "logout\r";
		irq_sync();
	}
	if (m_uart_log < 400)
	{
		m_uart_log++;
		logerror("UART%u: %s\n", channel, m_uart_line[channel]);
	}
	m_uart_line[channel].clear();
}

uint32_t opel_dvd90_state::unmapped_r(offs_t offset, uint32_t mem_mask)
{
	if (!machine().side_effects_disabled() && m_unmapped_log < 40)
	{
		m_unmapped_log++;
		logerror("%s unmapped R %08X mask=%08X\n", machine().describe_context(), offset << 2, mem_mask);
	}
	return 0;
}

void opel_dvd90_state::unmapped_w(offs_t offset, uint32_t data, uint32_t mem_mask)
{
	if (!machine().side_effects_disabled() && m_unmapped_log < 40)
	{
		m_unmapped_log++;
		logerror("%s unmapped W %08X = %08X mask=%08X\n", machine().describe_context(), offset << 2, data, mem_mask);
	}
}

//--------------------------------------------------------------------------
//  NAND controller
//--------------------------------------------------------------------------

void opel_dvd90_state::nand_ecc_reset()
{
	m_nand_ecc_pos = 0;
	m_nand_ecc_read = 0;
}

uint8_t opel_dvd90_state::nand_fetch()
{
	if (m_nand_status_mode)
		return 0xc0; // ready, not write protected
	if (m_nand_id_mode)
	{
		static const uint8_t id[4] = { NAND_MAKER, NAND_DEVICE, 0xa5, 0xc0 };
		uint8_t const value = id[m_nand_id_pos & 3];
		m_nand_id_pos++;
		return value;
	}
	if (m_nand_page >= NAND_PAGES || m_nand_col >= NAND_RAW_PAGE)
		return 0xff;
	uint8_t const value = m_nand[m_nand_page * NAND_RAW_PAGE + m_nand_col];
	if (m_nand_col < NAND_PAGE && m_nand_ecc_pos < NAND_PAGE)
		m_nand_ecc_buf[m_nand_ecc_pos++] = value;
	m_nand_col++;
	if (m_nand_col == NAND_RAW_PAGE)
	{
		// sequential read continues into the next page, area A
		m_nand_col = 0;
		m_nand_page++;
	}
	return value;
}

uint8_t opel_dvd90_state::nand_data_read()
{
	if ((m_nand_ctrl & 0x40) && !(m_nand_ctrl & 0x20))
	{
		// ECC readback: first half (3 bytes), then second half
		uint8_t ecc[6];
		smartmedia_ecc(m_nand_ecc_buf, ecc);
		smartmedia_ecc(m_nand_ecc_buf + 256, ecc + 3);
		uint8_t const value = ecc[m_nand_ecc_read % 6];
		m_nand_ecc_read++;
		return value;
	}
	// Status is valid on the first read: the program path checks bit 0 of that
	// byte and treats it as the fail flag. Page data has one byte of latency,
	// which the read path absorbs with a dummy read before the burst.
	if (m_nand_status_mode)
		return nand_fetch();
	// one access of latency
	uint8_t const value = m_nand_primed ? m_nand_latch : 0xff;
	m_nand_latch = nand_fetch();
	m_nand_primed = true;
	return value;
}

void opel_dvd90_state::nand_data_write(uint8_t data)
{
	if (m_nand_cmd == 0x80 && m_nand_col < NAND_RAW_PAGE)
	{
		// The program sequence reads the controller's ECC back and stores it
		// in the spare, so the written data has to feed the same accumulator
		// the read path uses.
		if (m_nand_col < NAND_PAGE && m_nand_ecc_pos < NAND_PAGE)
			m_nand_ecc_buf[m_nand_ecc_pos++] = data;
		m_nand_prog[m_nand_col++] = data;
	}
}

void opel_dvd90_state::nand_command(uint8_t command)
{
	if (m_nand_log < 20000 && command != 0xff && command != 0x00 && command != 0x01 && command != 0x50)
	{
		m_nand_log++;
		logerror("NAND cmd %02X\n", command);
	}
	m_nand_addr_count = 0;
	switch (command)
	{
	case 0xff: // reset
		m_nand_cmd = 0;
		m_nand_id_mode = false;
		m_nand_status_mode = false;
		break;
	case 0x90: // read ID
		m_nand_cmd = command;
		m_nand_id_mode = true;
		m_nand_status_mode = false;
		m_nand_id_pos = 0;
		break;
	case 0x70: // read status
		m_nand_status_mode = true;
		m_nand_id_mode = false;
		break;
	case 0x00: // read area A
	case 0x01: // read area B
	case 0x50: // read spare area
	case 0x80: // program setup
	case 0x60: // erase setup
		m_nand_cmd = command;
		m_nand_id_mode = false;
		m_nand_status_mode = false;
		if (command == 0x80)
			std::fill(std::begin(m_nand_prog), std::end(m_nand_prog), 0xff);
		break;
	case 0x10: // program confirm
		if (m_nand_cmd == 0x80 && m_nand_page < NAND_PAGES)
		{
			uint8_t *dst = &m_nand[m_nand_page * NAND_RAW_PAGE];
			for (uint32_t i = 0; i < NAND_RAW_PAGE; i++)
				dst[i] &= m_nand_prog[i];
			m_nand_dirty = true;
		}
		m_nand_cmd = 0;
		break;
	case 0xd0: // erase confirm
		if (m_nand_cmd == 0x60)
		{
			uint32_t const block = m_nand_page / NAND_PAGES_PER_BLOCK;
			if (block * NAND_PAGES_PER_BLOCK < NAND_PAGES)
			{
				std::fill_n(&m_nand[block * NAND_PAGES_PER_BLOCK * NAND_RAW_PAGE], NAND_PAGES_PER_BLOCK * NAND_RAW_PAGE, 0xff);
				m_nand_dirty = true;
			}
		}
		m_nand_cmd = 0;
		break;
	default:
		logerror("NAND: unknown command %02X\n", command);
		break;
	}
	m_nand_primed = false;
}

void opel_dvd90_state::nand_address(uint8_t data)
{
	if (m_nand_addr_count < 4)
		m_nand_addr[m_nand_addr_count] = data;
	m_nand_addr_count++;

	if (m_nand_cmd == 0x60)
	{
		// erase takes the three row bytes only
		if (m_nand_addr_count == 3)
			m_nand_page = m_nand_addr[0] | (m_nand_addr[1] << 8) | (m_nand_addr[2] << 16);
		return;
	}
	if (m_nand_addr_count == 4)
	{
		uint32_t base = 0;
		if (m_nand_cmd == 0x01)
			base = 256;
		else if (m_nand_cmd == 0x50)
			base = NAND_PAGE;
		m_nand_col = base + m_nand_addr[0];
		m_nand_page = m_nand_addr[1] | (m_nand_addr[2] << 8) | (m_nand_addr[3] << 16);
		m_nand_primed = false;
		nand_ecc_reset();
		if (m_nand_log < 20000)
		{
			m_nand_log++;
			logerror("NAND %02X blk %X pg %02X col %X%s\n", m_nand_cmd, m_nand_page / NAND_PAGES_PER_BLOCK, m_nand_page % NAND_PAGES_PER_BLOCK, m_nand_col,
					(m_nand_cmd == 0x50) ? "" : backtrace().c_str());
		}
	}
}

uint32_t opel_dvd90_state::nand_r(offs_t reg)
{
	if (machine().side_effects_disabled())
		return 0;
	switch (reg)
	{
	case 0: // data
		return nand_data_read();
	case 2: // status: never busy
		return 0;
	default:
		{
			auto const found = m_regs.find(NAND_BASE + (reg << 2));
			return (found != m_regs.end()) ? found->second : 0;
		}
	}
}

void opel_dvd90_state::nand_w(offs_t reg, uint32_t data)
{
	switch (reg)
	{
	case 0: // data
		switch (m_nand_ctrl & 0x03)
		{
		case 0x01:
			nand_command(uint8_t(data));
			break;
		case 0x02:
			nand_address(uint8_t(data));
			break;
		default:
			nand_data_write(uint8_t(data));
			break;
		}
		break;
	case 1: // control
		if ((data & 0x60) != (m_nand_ctrl & 0x60) || (data & 0x03) != (m_nand_ctrl & 0x03))
		{
			// a new data phase restarts the read pipeline
			m_nand_primed = false;
			if ((data & 0x20) && !(m_nand_ctrl & 0x20))
				nand_ecc_reset();
			if ((data & 0x40) && !(m_nand_ctrl & 0x40))
				m_nand_ecc_read = 0;
		}
		m_nand_ctrl = uint8_t(data);
		break;
	default:
		m_regs[NAND_BASE + (reg << 2)] = data;
		break;
	}
}

//--------------------------------------------------------------------------
//  DMA controller
//--------------------------------------------------------------------------

void opel_dvd90_state::dma_w(offs_t reg, uint32_t data)
{
	unsigned const channel = reg >> 3;
	unsigned const index = reg & 7;
	m_dma[channel][index] = data;
	if (index == 1 && BIT(data, 31))
		dma_run(channel);
}

void opel_dvd90_state::dma_run(unsigned channel)
{
	uint32_t *const ch = m_dma[channel];
	uint32_t const src = ch[2];
	uint32_t const dst = ch[3];
	uint32_t const count = ch[4];
	address_space &space = m_navcpu->space(AS_PROGRAM);

	bool const from_nand = (src & ~0x1f) == NAND_BASE;
	bool const to_nand = (dst & ~0x1f) == NAND_BASE;
	for (uint32_t i = 0; i < count; i++)
	{
		uint8_t value;
		if (from_nand)
			value = nand_data_read();
		else
			value = space.read_byte((src & 0x1fffffff) + i);

		if (to_nand)
			nand_data_write(value);
		else
			space.write_byte((dst & 0x1fffffff) + i, value);
	}
	ch[1] &= ~0x80000000U;
	ch[6] = (ch[6] & ~0x00f80000U) | 0x00800000U;
	if (m_nand_log < 20000 && !(from_nand && count == NAND_SPARE))
	{
		m_nand_log++;
		logerror("DMA%u %08X -> %08X n=%X mode=%08X\n", channel, src, dst, count, ch[5]);
	}
}

//--------------------------------------------------------------------------

// lowboot frames are linked: each prologue stores ra at 0(caller sp) and the caller sp at 4(sp)
std::string opel_dvd90_state::backtrace()
{
	address_space &space = m_navcpu->space(AS_PROGRAM);
	std::string result = util::string_format(" bt %08X", u32(m_navcpu->state_int(31)));
	uint32_t frame = u32(m_navcpu->state_int(29));
	for (int depth = 0; depth < 10; depth++)
	{
		if ((frame & 0xe0000003) != 0x80000000)
			break;
		uint32_t const caller = space.read_dword((frame & 0x1fffffff) + 4);
		if ((caller & 0xe0000003) != 0x80000000 || caller <= frame)
			break;
		result += util::string_format(" %08X", space.read_dword(caller & 0x1fffffff));
		frame = caller;
	}
	return result;
}

void opel_dvd90_state::heartbeat(int param)
{
	logerror("pc=%08X asic=%u irq=%X\n", m_navcpu->pc(), m_asic_log, m_irq_index);
}

// Eight one-shot timers. Control is FF905200 + n*4 (bit 0 armed, bit 1 left set
// by the boot code), compare is FF905220 + n*4, and the free-running counter
// at FF905248 counts microseconds. The tick ISR disarms by clearing bit 0,
// then writes the next deadline and sets the bit again.
uint32_t opel_dvd90_state::timer_now() const
{
	return uint32_t(machine().time().as_ticks(1'000'000));
}

bool opel_dvd90_state::timer_r(offs_t address, uint32_t &data)
{
	if (address == 0xff905248)
	{
		data = timer_now();
		return true;
	}
	switch (address)
	{
	case 0xff905100: data = m_tcu_ctrl; break;
	case 0xff905104: data = m_tcu_status; break;
	case 0xff905108: data = m_tcu_scale; break;
	case 0xff90510c: data = m_tcu_period; break;
	default:
		break;
	}
	if (address >= 0xff905100 && address <= 0xff90510c)
		return true;
	if (address < 0xff905200 || address >= 0xff905240)
		return false;
	unsigned const index = (address - 0xff905200) >> 2;
	data = index < 8 ? m_timer_ctrl[index] : m_timer_cmp[index - 8];
	log_asic("R", address, data, 0xffffffff);
	return true;
}

bool opel_dvd90_state::timer_w(offs_t address, uint32_t data, uint32_t mem_mask)
{
	if (address >= 0xff905100 && address <= 0xff90510c)
	{
		if (address != 0xff905100)
			log_asic("W", address, data, mem_mask);
		switch (address)
		{
		case 0xff905100:
			// Bit 0 runs the divider. Bit 2 is the acknowledge: the service
			// routine reads the control word, sets it, and writes it back.
			m_tcu_ctrl = ((m_tcu_ctrl & ~mem_mask) | (data & mem_mask)) & ~4u;
			if (data & mem_mask & 4)
				m_tcu_status &= ~1u;
			tick_schedule();
			irq_sync();
			break;
		case 0xff905108:
			m_tcu_scale = (m_tcu_scale & ~mem_mask) | (data & mem_mask);
			tick_schedule();
			break;
		case 0xff90510c:
			m_tcu_period = (m_tcu_period & ~mem_mask) | (data & mem_mask);
			tick_schedule();
			break;
		default:
			break;
		}
		return true;
	}
	if (address < 0xff905200 || address >= 0xff905240)
		return false;
	log_asic("W", address, data, mem_mask);
	unsigned const index = (address - 0xff905200) >> 2;
	uint32_t &reg = index < 8 ? m_timer_ctrl[index] : m_timer_cmp[index - 8];
	reg = (reg & ~mem_mask) | (data & mem_mask);
	if (index < 8 && !(reg & 1))
		m_timer_pending &= ~(1u << index);
	timer_schedule(index < 8 ? index : index - 8);
	irq_sync();
	return true;
}

void opel_dvd90_state::timer_schedule(int channel)
{
	if (!(m_timer_ctrl[channel] & 1))
	{
		m_pit[channel]->enable(false);
		return;
	}
	// Compare values are absolute counter timestamps. The guest computes them as
	// counter + delay, so the unsigned distance is the wait. A zero distance
	// still has to be delivered after the write that armed the channel.
	uint32_t const delta = m_timer_cmp[channel] - timer_now();
	m_pit[channel]->adjust(attotime::from_usec(delta == 0 ? 1 : delta), channel);
}

void opel_dvd90_state::timer_tick(int channel)
{
	if (!(m_timer_ctrl[channel] & 1))
		return;
	// Source 0x6c is the tick. Its service routine arms channel 0 itself, so
	// the first request has to come from whichever compare elapses first.
	// Later channel 0 carries the tick. Other channels are one-shot.
	// The tick service routine (source 0x6c, channel 0) follows the deadline
	// pointer before testing it. An empty list therefore has to stay quiet:
	// raising the line makes it treat the vector page as a deadline and kill
	// the process that was running. Other channels are one-shot compares; their
	// service routines are selected by source index and are not wired yet.
	if (channel != 0)
	{
		if (m_timer_log < 8)
		{
			m_timer_log++;
			logerror("timer %d elapsed at %08X\n", channel, timer_now());
		}
		m_pit[channel]->enable(false);
		return;
	}
	address_space &space = m_navcpu->space(AS_PROGRAM);
	auto rd = [&](uint32_t addr) { return space.read_dword(addr & 0x1fffffff); };
	uint32_t const desc = rd(0x80090b10 + 0x6c * 4);
	uint32_t const head = rd(rd(rd(desc + 4) + 0x124));
	if ((desc >> 28) != 0x8 || head == 0)
		return;
	m_timer_pending |= 1;
	m_irq_status |= 1;
	irq_sync();
}

// tim0, irq 0x67. tkspil programs a period of 27000 and a scale of 10 against
// a 27 MHz input, which is a 10 ms system tick, and acknowledges by setting
// bit 2 of the control word. Status bit 0 is what the service routine claims.
void opel_dvd90_state::tick_schedule()
{
	uint32_t const scale = m_tcu_scale == 0 ? 1 : m_tcu_scale;
	if (!(m_tcu_ctrl & 1) || m_tcu_period == 0)
	{
		m_tick->enable(false);
		return;
	}
	attotime const interval = attotime::from_ticks(uint64_t(scale) * m_tcu_period, 27'000'000);
	m_tick->adjust(interval, 0, interval);
}

void opel_dvd90_state::tick_fire(int param)
{
	m_tcu_status |= 1;
	irq_sync();
}

void opel_dvd90_state::cd_irq_drop(int param)
{
	m_cd_irq = 0;
	irq_sync();
}

// gpic: FF908000 and FF908004 are the two enable words, FF908008 is the
// two-bits-per-source mask, FF90800C is the pending word the ISR scans,
// and a write of a bit to FF908010 acknowledges it. Lowboot writes 8 to
// FF908000 and requires bit 1 of the read-back to stay clear.
bool opel_dvd90_state::irq_r(offs_t address, uint32_t &data)
{
	switch (address)
	{
	case 0xff908000: data = m_irq_mask0; break;
	case 0xff908004: data = m_irq_mask1; break;
	case 0xff908008: data = m_irq_pair; break;
	case 0xff90800c: data = m_irq_status; break;
	default:
		return false;
	}
	log_asic("R", address, data, 0xffffffff);
	return true;
}

bool opel_dvd90_state::irq_w(offs_t address, uint32_t data, uint32_t mem_mask)
{
	uint32_t *reg = nullptr;
	switch (address)
	{
	case 0xff908000: reg = &m_irq_mask0; break;
	case 0xff908004: reg = &m_irq_mask1; break;
	case 0xff908008: reg = &m_irq_pair; break;
	case 0xff908010:
		log_asic("W", address, data, mem_mask);
		m_irq_status &= ~data;
		irq_sync();
		return true;
	default:
		break;
	}
	if (reg)
	{
		log_asic("W", address, data, mem_mask);
		*reg = (*reg & ~mem_mask) | (data & mem_mask);
		irq_sync();
		return true;
	}
	// picsub enable bytes. Four sources per word, irq 0x6c lands in the low
	// byte of FFFEC02C. Writing it is what publishes the tick handler.
	if (address < 0xfffec010 || address >= 0xfffec040)
		return false;
	log_asic("W", address, data, mem_mask);
	uint32_t &stored = m_regs[address];
	stored = (stored & ~mem_mask) | (data & mem_mask);
	return true;
}

void opel_dvd90_state::irq_sync()
{
	// Cause bits 10-15 are the source index (irq number minus 0x50), not a
	// one-hot mask. tim0 is irq 0x67. The software timer is irq 0x6c.
	uint32_t index = 0;
	if (m_cd_irq)
		index = m_cd_irq;
	else if (m_tcu_status & 1)
		index = 0x17;
	else if (m_timer_pending & 1)
		index = 0x1c;
	else if (!m_uart_rx[0].empty())
		// scspiluart's console sits on the first port, dispatch slot 0x60.
		index = 0x10;
	if (index == m_irq_index)
		return;
	m_irq_index = index;
	for (int line = 0; line < 6; line++)
		m_navcpu->set_input_line(line, (index & (1u << line)) ? ASSERT_LINE : CLEAR_LINE);
}

// ATAPI task file at FFC00000, one register per word. +0x1C is the command
// written and the status read back (bit 7 busy, bit 6 ready, bit 3 data
// request). +0x38 mirrors that status. +0x10/+0x14 hold the ATAPI signature
// 0x14/0xEB while the drive is idle. PIO data moves through +0x00, 16 bits
// little-endian per access.
bool opel_dvd90_state::cd_r(offs_t address, uint32_t &data)
{
	if (address < 0xffc00000 || address >= 0xffc00100)
		return false;
	unsigned const offset = address - 0xffc00000;
	if (offset == 0)
	{
		uint8_t const lo = cd_byte(m_cd_pos);
		uint8_t const hi = cd_byte(m_cd_pos + 1);
		data = lo | (uint32_t(hi) << 8);
		if (m_cd_pos < m_cd_count)
			m_cd_pos += 2;
		if (m_cd_pos >= m_cd_count)
			m_cd_status = 0x50;
		return true;
	}
	if (offset == 0x1c || offset == 0x38)
	{
		data = m_cd_status;
		return true;
	}
	data = m_cd_reg[offset >> 2];
	if (offset != 0x70)
		log_asic("R", address, data, 0xffffffff);
	return true;
}

bool opel_dvd90_state::cd_w(offs_t address, uint32_t data, uint32_t mem_mask)
{
	if (address < 0xffc00000 || address >= 0xffc00100)
		return false;
	unsigned const offset = address - 0xffc00000;
	if (offset != 0)
		log_asic("W", address, data, mem_mask);
	if (offset == 0)
	{
		if (m_cd_cdb_pos < 16)
			m_cd_cdb[m_cd_cdb_pos++] = data & 0xff;
		if (m_cd_cdb_pos < 16)
			m_cd_cdb[m_cd_cdb_pos++] = (data >> 8) & 0xff;
		if (m_cd_cdb_pos >= 12 && (m_cd_status & 0x08))
			cd_packet();
		return true;
	}
	if (offset == 0x1c)
	{
		cd_command(data & 0xff);
		return true;
	}
	if (offset == 0x6c && (data & mem_mask & 1))
		m_cd_reg[0x70 >> 2] &= ~1u;
	if (offset == 0x58)
	{
		uint32_t const previous = m_cd_reg[0x58 >> 2];
		uint32_t const value = (previous & ~mem_mask) | (data & mem_mask);
		m_cd_reg[0x58 >> 2] = value;
		if ((value & 1) && !(previous & 1))
		{
			uint32_t const dest = m_cd_reg[0x50 >> 2];
			if (dest < 0x02000000 && m_cd_count != 0)
			{
				address_space &space = m_navcpu->space(AS_PROGRAM);
				for (uint32_t i = 0; i < m_cd_count && dest + i < 0x02000000; i++)
					space.write_byte(dest + i, cd_byte(i));
			}
			m_cd_reg[0x70 >> 2] |= 1;
			m_cd_status = 0x50;
			if (m_cd_vector != 0)
			{
				m_cd_irq = m_cd_vector;
				irq_sync();
				m_cd_irq_timer->adjust(attotime::from_usec(200));
			}
		}
		return true;
	}
	if (offset == 0x4c)
	{
		uint32_t const previous = m_cd_reg[0x4c >> 2];
		m_cd_reg[0x4c >> 2] = (previous & ~mem_mask) | (data & mem_mask);
		if (!(previous & 1) && (m_cd_reg[0x4c >> 2] & 1))
		{
			m_cd_reg[0x10 >> 2] = 0x14;
			m_cd_reg[0x14 >> 2] = 0xeb;
			m_cd_status = 0x50;
			m_cd_count = 0;
			m_cd_pos = 0;
			m_cd_cdb_pos = 0;
		}
		return true;
	}
	if (offset != 0x38)
	{
		uint32_t &reg = m_cd_reg[offset >> 2];
		reg = (reg & ~mem_mask) | (data & mem_mask);
	}
	return true;
}

void opel_dvd90_state::cd_command(uint8_t command)
{
	if (m_cd_log < 40)
	{
		m_cd_log++;
		logerror("cd cmd %02X\n", command);
	}
	m_cd_pos = 0;
	m_cd_count = 0;
	m_cd_lba = 0xffffffff;
	m_cd_cdb_pos = 0;
	m_cd_reg[0x70 >> 2] |= 1;
	std::fill(std::begin(m_cd_buf), std::end(m_cd_buf), 0);
	if (command == 0xa0)
	{
		m_cd_status = 0x58;
		return;
	}
	if (command == 0xa1 || command == 0xec)
	{
		m_cd_buf[0] = 0x80;
		m_cd_buf[1] = 0x85;
		std::memcpy(m_cd_buf + 54, "OPL DVD90          ", 20);
		m_cd_count = 512;
		m_cd_status = 0x58;
		return;
	}
	m_cd_status = 0x50;
}

void opel_dvd90_state::cd_packet()
{
	uint8_t const op = m_cd_cdb[0];
	uint32_t const lba = (uint32_t(m_cd_cdb[2]) << 24) | (uint32_t(m_cd_cdb[3]) << 16) | (uint32_t(m_cd_cdb[4]) << 8) | m_cd_cdb[5];
	uint32_t length = 0;
	if (op == 0x28)
		length = (uint32_t(m_cd_cdb[7]) << 8) | m_cd_cdb[8];
	else if (op == 0xa8)
		length = (uint32_t(m_cd_cdb[6]) << 24) | (uint32_t(m_cd_cdb[7]) << 16) | (uint32_t(m_cd_cdb[8]) << 8) | m_cd_cdb[9];
	if (m_cd_log < 40)
	{
		m_cd_log++;
		logerror("cd cdb %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X\n",
			m_cd_cdb[0], m_cd_cdb[1], m_cd_cdb[2], m_cd_cdb[3], m_cd_cdb[4], m_cd_cdb[5],
			m_cd_cdb[6], m_cd_cdb[7], m_cd_cdb[8], m_cd_cdb[9], m_cd_cdb[10], m_cd_cdb[11]);
	}
	m_cd_pos = 0;
	m_cd_count = 0;
	m_cd_lba = 0xffffffff;
	std::fill(std::begin(m_cd_buf), std::end(m_cd_buf), 0);
	m_cd_status = 0x50;
	switch (op)
	{
	case 0x00:
	case 0x1b:
	case 0x1e:
	case 0x2b:
	case 0xfb:
		m_cd_count = 16;
		m_cd_status = 0x58;
		break;
	case 0x03:
		m_cd_buf[0] = 0x70;
		m_cd_buf[7] = 10;
		m_cd_count = 18;
		m_cd_status = 0x58;
		break;
	case 0x12:
		m_cd_buf[0] = 0x05;
		m_cd_buf[4] = 31;
		std::memcpy(m_cd_buf + 8, "OPL     DVD90           1.00", 28);
		m_cd_count = 36;
		m_cd_status = 0x58;
		break;
	case 0x25:
	{
		uint32_t const last = m_cdrom->exists() ? m_cdrom->get_track_start(0xaa) - 1 : 0;
		m_cd_buf[0] = last >> 24;
		m_cd_buf[1] = last >> 16;
		m_cd_buf[2] = last >> 8;
		m_cd_buf[3] = last;
		m_cd_buf[6] = 2048 >> 8;
		m_cd_count = 8;
		m_cd_status = 0x58;
		break;
	}
	case 0x28:
	case 0xa8:
		if (length != 0 && m_cdrom->exists())
		{
			m_cd_lba = lba;
			m_cd_count = length * 2048;
			m_cd_cached = 0xffffffff;
			m_cd_status = 0x58;
			if (lba <= 16 && lba + length > 16)
				logerror("cd volume descriptor\n");
		}
		break;
	case 0x43:
		m_cd_buf[0] = 0;
		m_cd_buf[1] = 0x0a;
		m_cd_buf[3] = 1;
		m_cd_buf[5] = 0x14;
		m_cd_count = 12;
		m_cd_status = 0x58;
		break;
	case 0x5a:
		m_cd_count = std::min<uint32_t>((uint32_t(m_cd_cdb[7]) << 8) | m_cd_cdb[8], 512);
		m_cd_status = m_cd_count ? 0x58 : 0x50;
		break;
	default:
		break;
	}
	m_cd_cdb_pos = 0;
	m_cd_reg[0x70 >> 2] |= 1;
}

uint8_t opel_dvd90_state::cd_byte(uint32_t index)
{
	if (m_cd_lba != 0xffffffff)
	{
		uint32_t const lba = m_cd_lba + index / 2048;
		if (lba != m_cd_cached)
		{
			uint8_t raw[2448] = { };
			bool ok = m_cdrom->exists() && m_cdrom->read_data(lba, raw, cdrom_file::CD_TRACK_MODE1);
			if (!ok && m_cdrom->exists())
				ok = m_cdrom->read_data(lba, raw, cdrom_file::CD_TRACK_RAW_DONTCARE);
			if (ok)
				std::copy_n(raw, 2048, m_cd_cache);
			else
				std::fill_n(m_cd_cache, 2048, 0);
			m_cd_cached = lba;
		}
		return m_cd_cache[index % 2048];
	}
	return index < sizeof(m_cd_buf) ? m_cd_buf[index] : 0;
}

void opel_dvd90_state::machine_start()
{
	m_nand.assign(size_t(NAND_PAGES) * NAND_RAW_PAGE, 0xff);
	if (const char *path = std::getenv("OPEL_NAND"))
	{
		m_nand_path = path;
		std::ifstream in(m_nand_path, std::ios::binary);
		if (in)
		{
			in.read(reinterpret_cast<char *>(m_nand.data()), m_nand.size());
			logerror("NAND: loaded %s (%u bytes)\n", m_nand_path, unsigned(in.gcount()));
		}
	}

	machine().add_notifier(MACHINE_NOTIFY_EXIT, machine_notify_delegate(&opel_dvd90_state::machine_stop, this));

	save_item(NAME(m_asic_log));
	save_item(NAME(m_unmapped_log));
	m_heartbeat = timer_alloc(FUNC(opel_dvd90_state::heartbeat), this);
	m_heartbeat->adjust(attotime::from_msec(500), 0, attotime::from_msec(500));
	for (int channel = 0; channel < 8; channel++)
		m_pit[channel] = timer_alloc(FUNC(opel_dvd90_state::timer_tick), this);
	m_tick = timer_alloc(FUNC(opel_dvd90_state::tick_fire), this);
	m_cd_irq_timer = timer_alloc(FUNC(opel_dvd90_state::cd_irq_drop), this);
}

void opel_dvd90_state::machine_reset()
{
	m_asic_log = 0;
	m_unmapped_log = 0;
	m_nand_log = 0;
	m_uart_log = 0;
	m_timer_pending = 0;
	m_timer_log = 0;
	m_irq_mask0 = 0;
	m_irq_mask1 = 0;
	m_irq_pair = 0;
	m_irq_status = 0;
	m_irq_index = 0;
	m_tcu_ctrl = 0;
	m_tcu_scale = 0;
	m_tcu_period = 0;
	m_tcu_status = 0;
	if (m_tick)
		m_tick->enable(false);
	std::fill(std::begin(m_cd_reg), std::end(m_cd_reg), 0);
	m_cd_reg[0x10 >> 2] = 0x14;
	m_cd_reg[0x14 >> 2] = 0xeb;
	m_cd_status = 0x50;
	m_cd_count = 0;
	m_cd_pos = 0;
	m_cd_cdb_pos = 0;
	m_cd_lba = 0xffffffff;
	m_cd_cached = 0xffffffff;
	m_cd_log = 0;
	m_cd_irq = 0;
	// Dispatch slot 0x5b, installed with the packet transfer. Cause index 0x0b.
	m_cd_vector = 0x0b;
	for (int channel = 0; channel < 8; channel++)
	{
		m_timer_ctrl[channel] = 0;
		m_timer_cmp[channel] = 0;
		if (m_pit[channel])
			m_pit[channel]->enable(false);
	}
	for (std::string &line : m_uart_line)
		line.clear();
	for (std::string &rx : m_uart_rx)
		rx.clear();
	m_regs.clear();
	m_nand_ctrl = 0;
	m_nand_cmd = 0;
	m_nand_addr_count = 0;
	m_nand_id_mode = false;
	m_nand_status_mode = false;
	m_nand_primed = false;
	nand_ecc_reset();
	for (auto &ch : m_dma)
		std::fill(std::begin(ch), std::end(ch), 0);
}

void opel_dvd90_state::machine_stop()
{
	for (unsigned channel = 0; channel < 4; channel++)
		uart_flush(channel);
	if (m_nand_dirty && !m_nand_path.empty())
	{
		std::ofstream out(m_nand_path, std::ios::binary);
		out.write(reinterpret_cast<const char *>(m_nand.data()), m_nand.size());
	}
}

uint32_t opel_dvd90_state::screen_update(screen_device &screen, bitmap_rgb32 &bitmap, const rectangle &cliprect)
{
	bitmap.fill(rgb_t::black(), cliprect);
	return 0;
}

static INPUT_PORTS_START(opel_dvd90)
INPUT_PORTS_END

void opel_dvd90_state::opel_dvd90(machine_config &config)
{
	// Stand-in for the R3900 core. The R3041 is the TLB-less MIPS I device in this
	// tree; the TX39 behaviour lowboot and the kernel use is enabled on it.
	// Clock is a guess. Writes complete immediately, so the write buffer is empty.
	R3041(config, m_navcpu, 25_MHz_XTAL);
	m_navcpu->set_branch_likely(true);
	m_navcpu->set_no_cache(true);
	m_navcpu->set_mult_rd(true);
	m_navcpu->set_user_kseg(true);
	m_navcpu->in_brcond<0>().set_constant(1);
	m_navcpu->set_addrmap(AS_PROGRAM, &opel_dvd90_state::navcpu_map);

	screen_device &screen(SCREEN(config, "screen"));
	screen.set_refresh_hz(50);
	screen.set_vblank_time(ATTOSECONDS_IN_USEC(2500));
	screen.set_size(320, 240);
	screen.set_visarea(0, 319, 0, 239);
	screen.set_screen_update(FUNC(opel_dvd90_state::screen_update));

	// Map DVD. The ASIC ATAPI port is not emulated yet; the image is only mounted.
	CDROM(config, m_cdrom).set_interface("cdrom");
}

ROM_START(opel_dvd90)
	// OS-9 bootstrap, V_3/HVM0/0104/EHU4C/lowboot (NAV-DVD production). Runs at the reset vector.
	ROM_REGION32_BE(0x66000, "boot", 0)
	ROM_LOAD("lowboot", 0x000000, 0x65d00, CRC(ecf4bb01) SHA1(d77e73ab7dad25c8b63a23fcba60b45fd3113ff2))
ROM_END

} // anonymous namespace

GAME(1999, opel_dvd90, 0, opel_dvd90, opel_dvd90, opel_dvd90_state, empty_init, ROT0, "Opel", "DVD90 Navigation Radio", MACHINE_NOT_WORKING | MACHINE_NO_SOUND_HW)
