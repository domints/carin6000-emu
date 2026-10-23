// license:BSD-3-Clause
// copyright-holders:Ryan Holtz
/******************************************************************************

    Philips CARiN Mk1/Mk2 navigation system (Renault Carminat)

    68EC030 host running OS-9 with an SCC66470 video controller (VSC) and a CD
    drive behind the slave controller. Split out of the CD-i driver (philips/cdi.cpp); the CD-i consoles
    and Quizard sets are not part of this tree.

*******************************************************************************/


#include "emu.h"
#include "carin.h"

#include "bus/rs232/rs232.h"
#include "cpu/m6805/m6805.h"
#include "imagedev/cdromimg.h"

#include <string>
#include "machine/mc68681.h"
#include "machine/nvram.h"
#include "machine/timekpr.h"
#include "sound/cdda.h"

#include "multibyte.h"

#include <cmath>
#include <cstdio>

#include "emupal.h"
#include "screen.h"
#include "softlist.h"
#include "speaker.h"

#include "cdrom.h"


#include "carin.lh"

#define CLOCK_A 30_MHz_XTAL         // PAL system clock

#define VERBOSE         (0)
#include "logmacro.h"


/*************************
*      Input ports       *
*************************/

// Car side panel keys: codes of the 3A->3B fn 0x48 message (recv_ibus handler +0x64C). Only these
// nine codes do something in the 0209 software. Names from the system diagnosis key check: 0 mute nav,
// 1 last message, 2/3 volume +/-, 4 knob push, 8 stand by, 9 address book; 7 and 12 start the diagnosis auto test (no key on the
// panel, probably service inputs) (6 keys + knob, 9 wires; the intermediate module takes 11 inputs). Codes 5, 6, 10 and 11
// are ignored by recv_ibus; they are here to try them in the diagnosis key check.
const uint8_t carin_state::s_car_key_codes[] = { 0, 1, 2, 3, 4, 7, 8, 9, 12, 5, 6, 10, 11 };

static INPUT_PORTS_START( carin )
	PORT_START("CAR_KEYS")
	PORT_BIT(0x0001, IP_ACTIVE_HIGH, IPT_BUTTON1) PORT_NAME("Mute nav") PORT_CODE(KEYCODE_1)
	PORT_BIT(0x0002, IP_ACTIVE_HIGH, IPT_BUTTON2) PORT_NAME("Last message") PORT_CODE(KEYCODE_2)
	PORT_BIT(0x0004, IP_ACTIVE_HIGH, IPT_BUTTON3) PORT_NAME("Volume +") PORT_CODE(KEYCODE_3)
	PORT_BIT(0x0008, IP_ACTIVE_HIGH, IPT_BUTTON4) PORT_NAME("Volume -") PORT_CODE(KEYCODE_4)
	PORT_BIT(0x0010, IP_ACTIVE_HIGH, IPT_BUTTON5) PORT_NAME("Knob push") PORT_CODE(KEYCODE_5)
	PORT_BIT(0x0020, IP_ACTIVE_HIGH, IPT_BUTTON6) PORT_NAME("Auto test (key 7)") PORT_CODE(KEYCODE_6)
	PORT_BIT(0x0040, IP_ACTIVE_HIGH, IPT_BUTTON7) PORT_NAME("Stand by") PORT_CODE(KEYCODE_7)
	PORT_BIT(0x0080, IP_ACTIVE_HIGH, IPT_BUTTON8) PORT_NAME("Address book") PORT_CODE(KEYCODE_8)
	PORT_BIT(0x0100, IP_ACTIVE_HIGH, IPT_BUTTON9) PORT_NAME("Auto test (key 12)") PORT_CODE(KEYCODE_9)
	PORT_BIT(0x0200, IP_ACTIVE_HIGH, IPT_BUTTON10) PORT_NAME("Key 5 (unused)") PORT_CODE(KEYCODE_Q)
	PORT_BIT(0x0400, IP_ACTIVE_HIGH, IPT_BUTTON11) PORT_NAME("Key 6 (unused)") PORT_CODE(KEYCODE_W)
	PORT_BIT(0x0800, IP_ACTIVE_HIGH, IPT_BUTTON12) PORT_NAME("Key 10 (unused)") PORT_CODE(KEYCODE_E)
	PORT_BIT(0x1000, IP_ACTIVE_HIGH, IPT_BUTTON13) PORT_NAME("Key 11 (unused)") PORT_CODE(KEYCODE_R)
	PORT_BIT(0x2000, IP_ACTIVE_HIGH, IPT_JOYSTICK_LEFT) PORT_NAME("Knob left") PORT_CODE(KEYCODE_LEFT)
	PORT_BIT(0x4000, IP_ACTIVE_HIGH, IPT_JOYSTICK_RIGHT) PORT_NAME("Knob right") PORT_CODE(KEYCODE_RIGHT)

	PORT_START("MOUSEX")
	PORT_BIT(0xffff, 0x000, IPT_MOUSE_X) PORT_SENSITIVITY(100) PORT_KEYDELTA(2)

	PORT_START("MOUSEY")
	PORT_BIT(0xffff, 0x000, IPT_MOUSE_Y) PORT_SENSITIVITY(100) PORT_KEYDELTA(2)

	PORT_START("MOUSEBTN")
	PORT_BIT(0x01, IP_ACTIVE_HIGH, IPT_BUTTON1) PORT_CODE(MOUSECODE_BUTTON1) PORT_NAME("Button 1")
	PORT_BIT(0x02, IP_ACTIVE_HIGH, IPT_BUTTON2) PORT_CODE(MOUSECODE_BUTTON2) PORT_NAME("Button 2")
	PORT_BIT(0x04, IP_ACTIVE_HIGH, IPT_BUTTON3) PORT_CODE(MOUSECODE_BUTTON3) PORT_NAME("Button 3")
	PORT_BIT(0xf8, IP_ACTIVE_HIGH, IPT_UNUSED)

	// Car side: key switch. Each press turns the ignition over (on at start-up, see car_input_poll).
	PORT_START("CAR")
	PORT_BIT(0x01, IP_ACTIVE_HIGH, IPT_OTHER) PORT_NAME("Ignition on/off") PORT_CODE(KEYCODE_I)

	PORT_START("SERVICE")
	PORT_CONFNAME( 0x01, 0x00, "Service mode" )
	PORT_CONFSETTING(    0x00, DEF_STR( None ) )
	PORT_CONFSETTING(    0x01, "Test plug (service shell)" )
INPUT_PORTS_END


void carin_state::carin_mem(address_map &map)
{
    // CARiN ROM z Renault Safrane (0x000000..0x00ffff)
	// Boot flash: two byte-wide 1 MB chips, 2 MB at 0x000000 (flsh_boot and flsh_voice span
	// 0-0x1fffff; flshdr knows no 2 MB part). Bootrom at the bottom, voice/language data from 0x10000
	// on, the slave application (flsh_slave2) and flsh_hdr (0x1efbe0, read by nonvol_dr) at the top of
	// the second chip.
	map(0x000000, 0x0fffff).rw(m_bootflash, FUNC(amd_29f080_device::read), FUNC(amd_29f080_device::write));
	map(0x100000, 0x1fffff).rw(m_bootflash2, FUNC(amd_29f080_device::read), FUNC(amd_29f080_device::write));

    // CDIC & Slave HLE
    map(0x300000, 0x303bff).rw(m_cdic, FUNC(cdicdic_device::ram_r), FUNC(cdicdic_device::ram_w));
    map(0x303c00, 0x303fff).rw(m_cdic, FUNC(cdicdic_device::regs_r), FUNC(cdicdic_device::regs_w));
    map(0x310000, 0x317fff).rw(m_slave_hle, FUNC(cdislave_hle_device::slave_r), FUNC(cdislave_hle_device::slave_w));
    map(0x320000, 0x323fff).rw("mk48t08", FUNC(timekeeper_device::read), FUNC(timekeeper_device::write)).umask16(0xff00);

	// VSC (SCC66470): its 2 MB space sits at 0x600000 with the registers at the top (0x7fffe0);
	// 1 MB of DRAM at 0x600000. The first 512 KB is the init module's "Video RAM" (display program
	// at 0x6003ec, frame buffer allocated by videodr), the second its "Development RAM" (0x680000),
	// which a real unit (hardware 0209 without Extension RAM) lists as free memory.
	// The pixel accelerator window mirrors the DRAM 16 MB higher (videodr reports the offset).
	map(0x600000, 0x7fffff).m(m_vsc, FUNC(scc66470_device::map));
	map(0x600000, 0x6fffff).rw(FUNC(carin_state::vsc_dram_r), FUNC(carin_state::vsc_dram_w));
	map(0x1600000, 0x16fffff).rw(m_vsc, FUNC(scc66470_device::ipa_r), FUNC(scc66470_device::ipa_w));

	// Main system RAM (0x800000-0x9effff) and the "Extension RAM" (0xa00000-0xbfffff) come from the
	// RAM device, installed in machine_start: the RAM slot at 4m fits both, -ram 2m only the system RAM.
	map(0x9f0000, 0x9fffff).rw(FUNC(carin_state::carin_slave_r), FUNC(carin_state::carin_slave_w));
	map(0xf00000, 0xf0003f).rw(FUNC(carin_state::carin_arcnet_r), FUNC(carin_state::carin_arcnet_w));

	map(0xc00000, 0xc0003f).rw(FUNC(carin_state::mcasic_r), FUNC(carin_state::mcasic_w));

	// 8 KB byte-wide non-volatile memory holding the product ID block and the NVR disk; kept in nvram/carin/nv.
	map(0xd00000, 0xd01fff).mirror(0xfe000).lrw8(
			NAME([this] (offs_t offset)
			{
				if (m_maincpu->pc() >= 0x800000 && !machine().side_effects_disabled())
					m_trace.nv(trace_time(), 'R', offset, m_nv[offset], m_maincpu->pc());
				return m_nv[offset];
			}),
			NAME([this] (offs_t offset, uint8_t data)
			{
				if (m_maincpu->pc() >= 0x800000)
					m_trace.nv(trace_time(), 'W', offset, data, m_maincpu->pc());
				m_nv[offset] = data;
			}));

	// The 68EC030 accesses the DUART's 16 registers at byte stride.
	map(0xe00000, 0xe0003f).rw(FUNC(carin_state::duart_r), FUNC(carin_state::duart_w));

	// Main flash (OS-9 "flsh", 0x1200000-0x13fffff): flshdr detects four interleaved AMD 29F040.
	for (unsigned i = 0; i < 4; i++)
		map(0x1200000, 0x13fffff).rw(m_flash[i], FUNC(amd_29f040_device::read), FUNC(amd_29f040_device::write)).umask32(0xff000000 >> (8 * i));

	// nonvol_dr probes for an optional NV extension here and catches the bus error when it is absent.
	// Unmapped reads returning 0 make it mount a 32 KB blank partition that fails the NVR-DISK check.
	map(0x1d00000, 0x1dfffff).lrw8(
			NAME([this] (offs_t offset) -> uint8_t
			{
				if (!machine().side_effects_disabled())
				{
					m_maincpu->set_input_line(M68K_LINE_BUSERROR, ASSERT_LINE);
					m_maincpu->set_input_line(M68K_LINE_BUSERROR, CLEAR_LINE);
				}
				return 0xff;
			}),
			NAME([this] (offs_t offset, uint8_t data)
			{
				m_maincpu->set_input_line(M68K_LINE_BUSERROR, ASSERT_LINE);
				m_maincpu->set_input_line(M68K_LINE_BUSERROR, CLEAR_LINE);
			}));
}

void carin_state::machine_start()
{
	m_vram = std::make_unique<uint16_t[]>(0x100000 / 2);
	save_pointer(NAME(m_vram), 0x100000 / 2);

	// The Extension RAM is an option: some units have none (seen on a real 0209), and the OS-9
	// memory probe then finds nothing at 0xa00000. The navigation with a map disc needs it (without it
	// device_dialog cannot be forked and dbd runs out of heap).
	address_space &program = m_maincpu->space(AS_PROGRAM);
	program.install_ram(0x800000, 0x9effff, m_ram->pointer());
	if (m_ram->size() > 0x200000)
		program.install_ram(0xa00000, 0xbfffff, m_ram->pointer() + 0x200000);
	save_item(NAME(m_mcasic_regs));
	save_item(NAME(m_mcasic_reg12));
	save_item(NAME(m_mcasic_mock_pending));
	save_item(NAME(m_mcasic_mock_armed));
	save_item(NAME(m_mcasic_mock_status));
	save_item(NAME(m_mcasic_mock_phase));
	save_item(NAME(m_mcasic_boot_status));
	save_item(NAME(m_mcasic_boot_irq_pending));
	save_item(NAME(m_slave_shared_ram));
	save_item(NAME(m_nv));


	// Channel A/B transmit output goes to uart_a.txt / uart_b.txt in the working directory, truncated every run.
	m_uart_out[0].open("uart_a.txt", std::ios::binary | std::ios::trunc);
	m_uart_out[1].open("uart_b.txt", std::ios::binary | std::ios::trunc);
	m_trace.open();

	m_pc_watch_timer = timer_alloc(FUNC(carin_state::pc_watch_tick), this);
	m_pc_watch_timer->adjust(attotime::from_msec(250), 0, attotime::from_msec(250));

	m_i2c_timer = timer_alloc(FUNC(carin_state::i2c_done), this);
	save_item(NAME(m_i2c_result));
	save_item(NAME(m_i2c_pending));
	save_item(NAME(m_i2c_write_address));
	save_item(NAME(m_cdic_irq));
	save_item(NAME(m_powered_off));
	save_item(NAME(m_ignition_on));
	save_item(NAME(m_car_controls_last));
	m_ignition_led = m_ignition_on ? 1 : 0;
	save_item(NAME(m_car_navbus_attention));
	save_item(NAME(m_mbox_irq_channel));

	m_car_input_timer = timer_alloc(FUNC(carin_state::car_input_poll), this);
	m_car_input_timer->adjust(attotime::from_msec(20), 0, attotime::from_msec(20));
	save_item(NAME(m_car_input_last));
	m_mbox_reply_timer = timer_alloc(FUNC(carin_state::mbox_reply_irq), this);
	m_master_reset_timer = timer_alloc(FUNC(carin_state::master_reset), this);
	m_dr_timer = timer_alloc(FUNC(carin_state::slave_dr_tick), this);
	m_car_notify_timer = timer_alloc(FUNC(carin_state::car_notify_tick), this);
	m_car_notify_timer->adjust(attotime::from_msec(2), 0, attotime::from_msec(2));
	save_item(NAME(m_car_notifies));
	save_item(NAME(m_cd_driver_ready));
	save_item(NAME(m_cd_reported));

	m_tick_timer = timer_alloc(FUNC(carin_state::system_tick), this);
	m_tick_timer->adjust(attotime::from_hz(100), 0, attotime::from_hz(100));
	save_item(NAME(m_tick_enabled));

	address_space &space = m_maincpu->space(AS_PROGRAM);
	space.install_write_tap(0x7fffe0, 0x7fffff, "carin_vsc_regs_w",
		[this](offs_t offset, uint32_t &data, uint32_t mem_mask)
		{
			m_trace.line(carin_trace::VIDEO, trace_time(), "W %06X=%08X mask=%08X pc=%06X", unsigned(offset * 4), data, mem_mask, m_maincpu->pc());
		});
	space.install_read_tap(0x7fffe0, 0x7fffff, "carin_vsc_regs_r",
		[this](offs_t offset, uint32_t &data, uint32_t mem_mask)
		{
			m_trace.line(carin_trace::VIDEO, trace_time(), "R %06X=%08X mask=%08X pc=%06X", unsigned(offset * 4), data, mem_mask, m_maincpu->pc());
		});
}

TIMER_CALLBACK_MEMBER(carin_state::system_tick)
{
	if (m_tick_enabled)
		m_maincpu->set_input_line(M68K_IRQ_6, ASSERT_LINE);
}

TIMER_CALLBACK_MEMBER(carin_state::pc_watch_tick)
{
	m_trace.pc_sample(m_maincpu->pc());
	m_trace.tick(trace_time());
}

uint32_t carin_state::mcasic_r(offs_t offset)
{
	if (offset == 0)
	{
		uint32_t value = m_mcasic_regs[0];
		if (m_mcasic_boot_status)
			value = (value & 0x00ffffff) | (uint32_t(m_mcasic_boot_status) << 24);
		if (m_mbox_irq_channel)
		{
			// The mailbox ISRs (cddr_ipc, h_itc_dr...) read the channel here and latch it in 0x9F0000.
			value = (value & 0x00ffffff) | (uint32_t(m_mbox_irq_channel) << 24);
			if (!machine().side_effects_disabled())
			{
				m_mbox_irq_channel = 0;
				update_level3_irq();
			}
		}
		m_trace.count("mcasic_boot_status_reads");
		return value;
	}

	if (offset == 3)
		m_trace.count("mcasic_control_reads");

	// C0001B: interrupt pending bits, bit 1 is the I2C controller.
	if (offset == 6)
		return m_mcasic_regs[6] | (m_i2c_pending ? 0x02 : 0x00);

	if (offset == 9 && m_mcasic_mock_pending)
	{
		const uint32_t value = (m_mcasic_regs[9] & 0xffff0000) | m_mcasic_mock_status;
		m_trace.line(carin_trace::MCASIC, trace_time(), "R C00026 mock status=%04X pc=%06X", m_mcasic_mock_status, m_maincpu->pc());
		if (m_mcasic_mock_status != 0x0063)
			m_mcasic_mock_pending = false;
		return value;
	}
	if (offset == 10 && m_mcasic_mock_pending && m_mcasic_mock_status == 0x0063)
	{
		m_trace.line(carin_trace::MCASIC, trace_time(), "R C00028 mock response=01 pc=%06X", m_maincpu->pc());
		m_mcasic_mock_pending = false;
		return 1;
	}

	const uint32_t value = (offset == 4) ? (uint32_t(m_mcasic_reg12 | 0x10) << 8) : m_mcasic_regs[offset & 0x0f];
	if (offset == 9)
		m_trace.line(carin_trace::MCASIC, trace_time(), "R C00026 status=%04X pc=%06X", uint16_t(value), m_maincpu->pc());
	return value;
}

void carin_state::mcasic_w(offs_t offset, uint32_t data, uint32_t mem_mask)
{
	const uint32_t byte_addr = uint32_t(offset & 0x0f) * 4;
	if (offset == 4 && ACCESSING_BITS_8_15)
	{
		m_mcasic_reg12 = uint8_t(data >> 8) | 0x10;
		// Any write acknowledges the tick; only OS-9 code (not the ROM) may enable it with bit 0.
		m_maincpu->set_input_line(M68K_IRQ_6, CLEAR_LINE);
		if (m_maincpu->pc() >= 0x800000)
			m_tick_enabled = BIT(m_mcasic_reg12, 0);
		m_trace.count("mcasic_tick_acks");
		if (m_mcasic_reg12 & 0x03)
			m_trace.count("mcasic_reg12_enable_writes");
	}
	else if (offset == 9 && ACCESSING_BITS_16_31 && m_maincpu->pc() >= 0x800000)
		i2c_control_w(uint16_t(data >> 16));
	else if (offset != 4)
	{
		const uint32_t old_value = m_mcasic_regs[offset & 0x0f];
		COMBINE_DATA(&m_mcasic_regs[offset & 0x0f]);
		// Byte +2 is the mailbox-busy flag: the master sets it, the slave clears it once the message is consumed.
		if (offset == 0 && ACCESSING_BITS_8_15 && (m_mcasic_regs[0] & 0x0000ff00))
		{
			const uint8_t page = uint8_t(m_mcasic_regs[0] >> 8);
			m_trace.line(carin_trace::MCASIC, trace_time(), "kick ch=%02X pc=%06X", page, m_maincpu->pc());
			m_mcasic_regs[0] &= ~0x0000ff00;
			carin_mailbox_kick(page);
		}
		if (offset == 3 && ACCESSING_BITS_0_7 && (uint8_t(m_mcasic_regs[3]) & 0x80))
		{
			// C0000F bit 7: the master asks the slave to switch it off (ignition off, after accepting a
			// software disc, at the end of a software load, ...). See master_reset; the delay lets the
			// master finish its NV writes (the sw-load flag follows the request by a few ms). While
			// waiting the master repeats the request every 3 s.
			if (m_maincpu->pc() >= 0x800000 && m_master_reset_timer->remaining().is_never())
			{
				m_trace.line(carin_trace::EVENTS, trace_time(), "master asks to be switched off: slave acts in 2 s (restart, or power off with the ignition off)");
				m_master_reset_timer->adjust(attotime::from_seconds(2));
			}
		}
		if (offset == 3 && ACCESSING_BITS_0_7)
		{
			const bool irq_pulse = (uint8_t(m_mcasic_regs[3]) & 0x40) != 0;
			if (!(uint8_t(old_value) & 0x40) && irq_pulse)
				m_mcasic_boot_irq_pending = true;
			else if ((uint8_t(old_value) & 0x40) && !irq_pulse && m_mcasic_boot_irq_pending)
			{
				m_mcasic_boot_status = 3;
				m_mcasic_boot_irq_pending = false;
				m_trace.line(carin_trace::MCASIC, trace_time(), "boot status -> 03 after control IRQ pulse pc=%06X", m_maincpu->pc());
			}
		}
		if (offset == 8 || offset == 10)
			m_mcasic_mock_armed = true;
		if (offset == 9 && m_mcasic_mock_armed && m_maincpu->pc() < 0x800000)
		{
			uint16_t response_status = 0;
			if (m_mcasic_mock_phase == 0 && (m_mcasic_regs[9] & 0x00200000))
				response_status = 0x0063;
			else if (m_mcasic_mock_phase >= 1 && (m_mcasic_regs[9] & 0x00800000))
				// After the first exchange every transfer completes: odd addresses read (0x283), even write (0x383).
				response_status = BIT(m_mcasic_regs[10], 8) ? 0x0283 : 0x0383;

			if (response_status)
			{
				m_mcasic_mock_pending = true;
				m_mcasic_mock_armed = false;
				m_mcasic_mock_status = response_status;
				if (m_mcasic_mock_phase < 2)
					m_mcasic_mock_phase++;

				if (response_status == 0x0283)
				{
					const uint32_t buffer_address = m_mcasic_regs[8];
					const bool low_ram = buffer_address >= 0x010000 && buffer_address < 0x080000;
					const bool system_ram = buffer_address >= 0x800000 && buffer_address < 0xa00000;
					// Reads here are the I/O expander at 0x44/0x45. Bit 1 low would make the bootrom load from
					// CD even with valid software in flash (bootrom $44a8); kept high, so like in the car the
					// bootrom boots the flash unless the software set the sw-load flag ('G' in NV) for a
					// software disc.
					if (low_ram || system_ram)
						m_maincpu->space(AS_PROGRAM).write_byte(buffer_address, 0xff);
				}

				m_trace.line(carin_trace::MCASIC, trace_time(), "mock transaction phase=%u status=%04X pc=%06X",
					m_mcasic_mock_phase, response_status, m_maincpu->pc());
			}
		}
		if (offset == 7)
		{
			update_level3_irq();
			update_level4_irq();
		}
		if ((byte_addr == 0x1c) && (m_mcasic_regs[offset & 0x0f] != old_value))
		{
			m_trace.line(carin_trace::MCASIC, trace_time(), "W C0001C=%02X pc=%06X",
				uint8_t(m_mcasic_regs[offset & 0x0f] >> 24), m_maincpu->pc());
		}
		else if (byte_addr >= 0x20 && byte_addr <= 0x2c)
		{
			m_trace.line(carin_trace::MCASIC, trace_time(), "W C000%02X=%08X mask=%08X", byte_addr, data, mem_mask);
		}
		if (offset == 3 && ACCESSING_BITS_0_7)
			m_trace.line(carin_trace::MCASIC, trace_time(), "W C0000F=%02X pc=%06X", uint8_t(m_mcasic_regs[3]), m_maincpu->pc());
	}
}

// HLE of the MCASIC I2C master used by vbi2csp2 (OS-9 only; the bootrom keeps the mock above).
// C00020 DMA buffer, C00024 control, C00026 status, C00028 byte count, C0002A slave address.
// Control bit 7 starts a write, bit 5 a read, bit 6 aborts and bit 2 acknowledges the interrupt;
// these bits do not stick. Completion sets C0001B bit 1 and raises level 3 while C0001C bit 1 is set.
// The address byte holds the R/W bit (odd = read). Every address ACKs; apart from the nav bus
// display at 0x50 (see the car side below) writes are dropped and reads return zeros. Control bit 5
// (read into the internal buffer) is not used by OS-9 here and also returns zeros.
void carin_state::i2c_control_w(uint16_t data)
{
	if (BIT(data, 2))
	{
		m_i2c_pending = false;
		update_level3_irq();
	}
	if (BIT(data, 6))
		m_i2c_timer->adjust(attotime::never);

	const uint32_t buffer = m_mcasic_regs[8];
	const uint8_t count = uint8_t(m_mcasic_regs[10] >> 24);
	const uint8_t address = uint8_t(m_mcasic_regs[10] >> 8);
	address_space &space = m_maincpu->space(AS_PROGRAM);
	if (BIT(data, 7) && BIT(address, 0))
	{
		// The address byte carries the R/W bit: an odd address reads count bytes into the buffer.
		for (unsigned i = 0; i < count; i++)
			space.write_byte(buffer + i, 0x00);
		if (address == 0x51 && count == 1)
		{
			// Car side: the intermediate module answers vbnavi2c's status read with one nibble per
			// message slot (slot 0 high), bit 0 = message taken, bit 1 = message for the unit (slot 1).
			space.write_byte(buffer, m_navbus_frames.empty() ? 0x11 : 0x13);
			m_car_navbus_attention = false;
			update_level4_irq();
		}
		else if (address == 0x51 && count && !m_navbus_frames.empty())
		{
			// Car side: the slot 1 fetch (after the 01 01 write) gets the next queued frame.
			const std::vector<uint8_t> &frame = m_navbus_frames.front();
			for (unsigned i = 0; i < count && i < frame.size(); i++)
				space.write_byte(buffer + i, frame[i]);
			m_navbus_frames.pop_front();
		}
		m_trace.line(carin_trace::MCASIC, trace_time(), "I2C read addr=%02X n=%u first=%02X ctrl=%04X pc=%06X", address, count, space.read_byte(buffer), data, m_maincpu->pc());
		// 0x283: read done; vbi2csp2 only copies its DMA buffer to the caller on this status.
		m_i2c_result = 0x0283;
		m_i2c_write_address = -1;
		m_i2c_timer->adjust(attotime::from_usec(100 * (count + 1)));
	}
	else if (BIT(data, 7))
	{
		char dump[2 * 16 + 1] = {};
		for (unsigned i = 0; i < count && i < 16; i++)
			std::snprintf(dump + i * 2, 3, "%02X", space.read_byte(buffer + i));
		m_trace.line(carin_trace::MCASIC, trace_time(), "I2C write addr=%02X n=%u data=%s ctrl=%04X pc=%06X", address, count, dump, data, m_maincpu->pc());
		// 0x383: write done with ACK; bit 8 asks for a repeated start, which completes as 0x283.
		m_i2c_result = BIT(data, 8) ? 0x0283 : 0x0383;
		m_i2c_write_address = address;
		m_i2c_timer->adjust(attotime::from_usec(100 * (count + 1)));
	}
	else if (BIT(data, 5))
	{
		for (unsigned i = 0; i < count; i++)
			space.write_byte(buffer + i, 0x00);
		m_i2c_write_address = -1;
		m_trace.line(carin_trace::MCASIC, trace_time(), "I2C read addr=%02X n=%u ctrl=%04X pc=%06X", address, count, data, m_maincpu->pc());
		m_i2c_result = 0x0042;
		m_i2c_timer->adjust(attotime::from_usec(100 * (count + 1)));
	}

	m_mcasic_regs[9] = (m_mcasic_regs[9] & 0x0000ffff) | (uint32_t(data & ~0x00e4) << 16);
}

TIMER_CALLBACK_MEMBER(carin_state::i2c_done)
{
	// Status in C00026, nothing left in the byte counter.
	m_mcasic_regs[9] = (m_mcasic_regs[9] & 0xffff0000) | m_i2c_result;
	m_mcasic_regs[10] &= 0x00ffffff;
	m_i2c_pending = true;
	m_trace.line(carin_trace::MCASIC, trace_time(), "I2C done status=%04X", m_i2c_result);
	update_level3_irq();

	// Car side: every message written to the intermediate module (recv_ibus/nav_bus via vbnavi2c) is
	// taken at once, and the module raises its attention line so the unit reads the slot status. The
	// slot 1 fetch request (01 01) does the same, which brings the next queued frame, if any.
	if (m_i2c_write_address == 0x50)
	{
		m_car_navbus_attention = true;
		update_level4_irq();
	}
	m_i2c_write_address = -1;
}

// Level 3 is shared by the I2C controller (gated by C0001C bit 1) and the slave mailbox, which
// raises it with the channel number in C00000 until that register is read.
void carin_state::update_level3_irq()
{
	const bool i2c = m_i2c_pending && BIT(m_mcasic_regs[7], 25);
	m_maincpu->set_input_line(M68K_IRQ_3, (i2c || m_mbox_irq_channel) ? ASSERT_LINE : CLEAR_LINE);
}

// Level 4 (autovector 28): the nav bus attention line, gated by C0001C bit 2 (vbnavi2c clears it in
// its ISR and sets it again once the status read is done); the CDIC line is unused by CARiN.
void carin_state::update_level4_irq()
{
	const bool navbus = m_car_navbus_attention && BIT(m_mcasic_regs[7], 26);
	m_maincpu->set_input_line(M68K_IRQ_4, (navbus || m_cdic_irq) ? ASSERT_LINE : CLEAR_LINE);
}

uint32_t carin_state::carin_slave_r(offs_t offset, uint32_t mem_mask)
{
	const uint32_t byte_addr = 0x009f0000 + uint32_t(offset) * 4;
	const uint32_t pc = m_maincpu->pc();
	if (byte_addr >= 0x009fb6e0 && byte_addr <= 0x009fb700)
	{
		m_trace.count("shared_ram_handshake_reads");
		return 0;
	}

	uint32_t response = m_slave_shared_ram[offset];
	// Car side: slave I/O state block at 0x9FA000, read bytewise by syscondr. Byte 8 is the key switch
	// (ignition +12V), 1 = on; with 0 syscondr counts down and signals sysgo to power down (0x13F).
	if (byte_addr == 0x009fa008)
		response = (response & 0x00ffffff) | (uint32_t(car_ignition() ? 1 : 0) << 24);
	// HLE of the status page the slave application keeps for subsystem 0x88 (h_itc page 0x88):
	// +2 service 0x81, +4 bit 1 "alive", +5 data length, data from +6. sysgo and start_slave poll
	// data byte 0x14 until it reads 2 ("synchronised"); each failed poll leaks an h_itc path.
	if (byte_addr >= 0x009f8800 && byte_addr < 0x009f8800 + 6 + 0x20)
	{
		static const uint8_t status_page[6 + 0x20] = {
				0x00, 0x00, 0x81, 0x00, 0x02, 0x20,
				0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
				0, 0, 0, 0, 0x02, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
		const unsigned base = byte_addr - 0x009f8800;
		for (unsigned i = 0; i < 4; i++)
		{
			const unsigned shift = 24 - 8 * i;
			if (base + i < sizeof(status_page) && status_page[base + i])
				response = (response & ~(uint32_t(0xff) << shift)) | (uint32_t(status_page[base + i]) << shift);
		}
	}
	if (!machine().side_effects_disabled())
		m_trace.ipc(trace_time(), 'R', byte_addr, response, pc);
	return response;
}

void carin_state::carin_slave_w(offs_t offset, uint32_t data, uint32_t mem_mask)
{
	const uint32_t byte_addr = 0x009f0000 + uint32_t(offset) * 4;
	const uint32_t pc = m_maincpu->pc();
	COMBINE_DATA(&m_slave_shared_ram[offset]);
	m_trace.ipc(trace_time(), 'W', byte_addr, m_slave_shared_ram[offset], pc);
}

// Minimal SMSC COM20020 (ARCNET) host interface; the remote node is answered by HLE in carin_arcnet_transmit().
uint8_t carin_state::shared_byte(uint32_t offset) const
{
	return uint8_t(m_slave_shared_ram[(offset & 0xffff) >> 2] >> (24 - 8 * (offset & 3)));
}

void carin_state::set_shared_byte(uint32_t offset, uint8_t value)
{
	const unsigned shift = 24 - 8 * (offset & 3);
	uint32_t &word = m_slave_shared_ram[(offset & 0xffff) >> 2];
	word = (word & ~(uint32_t(0xff) << shift)) | (uint32_t(value) << shift);
}

// Slave side of the shared-RAM mailbox: the kick value is the channel; the channel table on page 0 gives its TX and RX pages.
void carin_state::carin_mailbox_kick(uint8_t channel)
{
	const unsigned entry = 2 + unsigned(channel) * 6;
	const uint32_t tx = shared_byte(entry + 1) * 0x100;
	const uint32_t rx = shared_byte(entry + 3) * 0x100;
	if (!tx || !rx || shared_byte(tx + 1) != 3)
	{
		m_trace.line(carin_trace::MAILBOX, trace_time(), "kick ch=%u nothing to serve tx=%04X rx=%04X", channel, tx, rx);
		return;
	}

	const uint8_t type = shared_byte(tx + 2);
	char dump[2 * 16 + 1] = {};
	for (unsigned i = 0; i < 16; i++)
		std::snprintf(dump + i * 2, 3, "%02X", shared_byte(tx + i));
	m_trace.line(carin_trace::MAILBOX, trace_time(), "req ch=%u type=%u hdr+payload=%s dma=%08X len=%08X", channel, type, dump, m_mcasic_regs[1], m_mcasic_regs[2]);
	m_trace.line(carin_trace::EVENTS, trace_time(), "mailbox req ch=%u type=%u", channel, type);

	// The request is consumed; the master refuses to reuse the page until its state returns to 0.
	set_shared_byte(tx + 1, 0);

	auto reply = [this, channel, rx](uint8_t reply_type, const uint8_t *payload, unsigned length)
	{
		set_shared_byte(rx + 0, channel);
		set_shared_byte(rx + 2, reply_type);
		set_shared_byte(rx + 6, length >> 8);
		set_shared_byte(rx + 7, length);
		for (unsigned i = 0; i < length; i++)
			set_shared_byte(rx + 8 + i, payload[i]);
		// State 3 = ready for the master; h_ibus_dr sets it to 2 while it takes the message.
		set_shared_byte(rx + 1, 3);
		m_trace.line(carin_trace::MAILBOX, trace_time(), "reply ch=%u type=%u len=%u", channel, reply_type, length);
		// OS-9 drivers sleep until the slave interrupts; the bootrom polls instead. The interrupt comes a
		// little later, like from the real slave: h_ibus_dr only arms its wait flag after the request.
		if (m_maincpu->pc() >= 0x800000)
			m_mbox_reply_timer->adjust(attotime::from_usec(200), channel);
	};

	// Channel 8 is h_ibus_dr (/ibus, /rc5): each read (type 2) gets the next queued chunk, see car_rc5().
	if (channel == 8 && type == 2)
	{
		std::vector<uint8_t> chunk;
		if (!m_car_chunks.empty())
		{
			chunk = std::move(m_car_chunks.front());
			m_car_chunks.pop_front();
		}
		m_trace.line(carin_trace::EVENTS, trace_time(), "ibus read -> %u bytes", unsigned(chunk.size()));
		reply(0, chunk.data(), chunk.size());
		return;
	}

	// Channel 6, type 6 from the master: an h_itc command byte for the slave (h_itc_dr SetStat).
	// 0xF5 follows dp's first position record on subsystem 0xB2: start the position service.
	if (channel == 6 && type == 6 && shared_byte(tx + 7) >= 1 && shared_byte(tx + 8) == 0xf5 && m_dr_timer->remaining().is_never())
	{
		m_trace.line(carin_trace::EVENTS, trace_time(), "h_itc command F5: position service on (subsystem B2)");
		m_dr_timer->adjust(attotime::from_seconds(1), 0, attotime::from_seconds(1));
	}

	// Only channel 3 is the CD drive (bootrom and cddr_ipc); 8 is h_ibus_dr and 9 is dc_dr, whose protocols are unknown.
	if (channel != 3)
	{
		m_trace.line(carin_trace::EVENTS, trace_time(), "mailbox ch=%u type=%u acked without HLE", channel, type);
		static const uint8_t status[2] = { 0x00, 0x00 };
		reply(0, status, sizeof(status));
	}
	else if (type == 6)
	{
		// Drive status query: payload byte 2 in 0x0A..0x11 means "disc ready", which makes the ROM load nav_sw_load.
		// With no image loaded report 0 there; the real "no disc" code is not known.
		const uint8_t status[4] = { 0x00, 0x00, uint8_t(m_cdrom->exists() ? 0x0a : 0x00), 0x00 };
		reply(type, status, sizeof(status));
	}
	else if (type == 2)
	{
		// Read request: [LBA][block count], data is DMAed by MCASIC to the address in +4 and the register is advanced.
		const auto be32 = [this, tx](unsigned at)
		{
			return (uint32_t(shared_byte(tx + at)) << 24) | (uint32_t(shared_byte(tx + at + 1)) << 16)
					| (uint32_t(shared_byte(tx + at + 2)) << 8) | shared_byte(tx + at + 3);
		};
		const uint32_t lba = be32(8);
		const uint32_t count = be32(12);

		uint32_t dest = m_mcasic_regs[1];
		address_space &space = m_maincpu->space(AS_PROGRAM);
		bool ok = true;

		for (uint32_t block = 0; block < count && ok; block++)
		{
			uint8_t raw[2560] = {};
			ok = m_cdrom->read_data(lba + block, raw, cdrom_file::CD_TRACK_RAW_DONTCARE);
			const unsigned data_offset = (raw[15] == 1) ? 16 : 24;
			for (unsigned i = 0; ok && i < 2048; i++)
				space.write_byte(dest++, raw[data_offset + i]);
		}

		m_mcasic_regs[1] = dest;
		m_trace.line(carin_trace::CDROM, trace_time(), "read lba=%u n=%u ok=%d dma_end=%08X", lba, count, ok, dest);
		m_trace.line(carin_trace::EVENTS, trace_time(), "cd read lba=%u n=%u ok=%d", lba, count, ok);

		const uint8_t status[2] = { uint8_t(ok ? 0x00 : 0x08), uint8_t(ok ? 0x00 : 0x03) };
		reply(0, status, sizeof(status));
	}
	else if (type == 7 || type == 4)
	{
		// 7 is sent by cddr_ipc at start-up. 4 carries a SetStat code of /cd (0x03, 0x34, 0x38, 0x39
		// seen); only 0x34 (eject) is known, the others are acknowledged as OK.
		m_trace.line(carin_trace::EVENTS, trace_time(), "cd type=%u param=%02X%02X acked", type, shared_byte(tx + 8), shared_byte(tx + 9));
		if (type == 4 && shared_byte(tx + 8) == 0x00 && shared_byte(tx + 9) == 0x34 && m_cdrom->exists())
		{
			// 0x34 ejects the disc (il at the end of a software load); the state event follows.
			m_trace.line(carin_trace::EVENTS, trace_time(), "cd eject");
			m_cdrom->unload();
		}
		if (type == 7 && m_maincpu->pc() >= 0x800000)
		{
			// cddr_ipc has started: report the drive state to it (car_notify_tick).
			m_cd_driver_ready = true;
			m_cd_reported = -1;
			m_cd_spinup_until = attotime::zero;
		}
		static const uint8_t status[2] = { 0x00, 0x00 };
		reply(0, status, sizeof(status));
	}
	else
		m_trace.line(carin_trace::EVENTS, trace_time(), "mailbox type=%u NOT HANDLED", type);
}

// Car side: a message from the intermediate module to the unit, [src][dst][fn][data]. The module
// queues it in its nav bus slot 1 (I2C 0x50) and raises the attention line; vbnavi2c reads the slot
// status, fetches the slot and hands the frame to recv_ibus (nav_bus in raw mode keeps the source).
// On the bus the frame is [src][len][dst][fn][data], len counting itself and the bytes after it.
void carin_state::car_frame(uint8_t src, uint8_t dst, uint8_t fn, uint8_t data)
{
	m_navbus_frames.push_back({ src, 4, dst, fn, data });
	m_trace.line(carin_trace::EVENTS, trace_time(), "car frame %02X %02X %02X %02X", src, dst, fn, data);
	m_car_navbus_attention = true;
	update_level4_irq();
}

// Car side: a remote control (RC5) code, delivered by the slave on channel 8 (/rc5). recv_ibus turns
// it into an F0 3B 48/49 message; the routing table has no F0 3B 48/49 entry in this configuration,
// so it is not wired to an input yet. The slave announces each byte with an unsolicited type 6
// message (payload 1 = data available) and h_ibus_dr reads it with a type 2 request.
void carin_state::car_rc5(uint8_t code)
{
	m_car_chunks.push_back({ code });
	m_car_notifies++;
	m_trace.line(carin_trace::EVENTS, trace_time(), "car rc5 %02X", code);
}

// Car side: the GPS antenna position, in the receiver's units (1e-9 semicircles = 1.8e-7 degree, as
// "Read GPS data" in the diagnosis shows them). The diagnosis shows the longitude 30 degrees lower
// than the raw value (0 = 390 West), so the receiver's longitude carries a 30 degree offset.
int32_t carin_state::gps_latitude() const { return int32_t(std::lround(m_car_latitude / 1.8e-7)); }
int32_t carin_state::gps_longitude() const { return int32_t(std::lround((m_car_longitude + 30.0) / 1.8e-7)); }

// Slave HLE, h_itc subsystem 0xB2 = dead reckoning: every second the slave answers dp with a service
// 0x83 record (19 little-endian longs, the layout dp sent) in the subsystem page 0x9FB200 and announces
// it on channel 6 (type 6, data = event 0xF5). The slave keeps the sensor part of the last record dp
// wrote (service 2) and puts in the position (L3 longitude, L4 latitude, the GPS units) with the valid
// bit. dp maps L3/L4 straight into its position; with a position the status line satellite turns green.
TIMER_CALLBACK_MEMBER(carin_state::slave_dr_tick)
{
	const uint32_t page = 0xb200;
	if (shared_byte(page + 0))   // the master holds the page
		return;
	// A new record from dp (service 2: start-up state, relocation, ...): take it over.
	if (shared_byte(page + 2) == 2)
	{
		char dump[2 * sizeof(m_dr_record) + 1] = {};
		for (unsigned i = 0; i < sizeof(m_dr_record); i++)
		{
			m_dr_record[i] = shared_byte(page + 6 + i);
			std::snprintf(dump + 2 * i, 3, "%02X", m_dr_record[i]);
		}
		m_trace.line(carin_trace::EVENTS, trace_time(), "dp position record %s", dump);
	}
	put_u32le(&m_dr_record[0x0c], gps_longitude());
	put_u32le(&m_dr_record[0x10], gps_latitude());
	set_shared_byte(page + 1, 1);
	set_shared_byte(page + 2, 0x83);
	set_shared_byte(page + 3, shared_byte(page + 3) + 1);   // update counter (GetStat 0x802 "new data")
	set_shared_byte(page + 4, 0x02);
	set_shared_byte(page + 5, sizeof(m_dr_record));
	for (unsigned i = 0; i < sizeof(m_dr_record); i++)
		set_shared_byte(page + 6 + i, m_dr_record[i]);
	set_shared_byte(page + 6 + 0x3e, m_dr_record[0x3e] | 0x80);   // struct word 0x2a bit 15: valid
	set_shared_byte(page + 1, 0);
	// The announcement is an h_itc event code, not the subsystem: dp subscribes event 0xF5 on /h_itc/e
	// and reads the B2 record when it arrives.
	static const uint8_t notify[1] = { 0xf5 };
	if (mbox_post(6, 6, notify, sizeof(notify)))
		m_trace.line(carin_trace::EVENTS, trace_time(), "slave position record (B2/83)");
	m_gps_pending = true;
}

// Slave HLE, h_itc subsystem 0xB3 = GPS receiver: a new record after each position record, announced
// with event 0xF6 (dp turns it into /pack/gps_info).
void carin_state::slave_gps_tick()
{
	if (!slave_gps_record())
		return;
	static const uint8_t notify[1] = { 0xf6 };
	if (mbox_post(6, 6, notify, sizeof(notify)))
		m_trace.line(carin_trace::EVENTS, trace_time(), "slave GPS record (B3)");
}

// The record in the subsystem page 0x9FB300. h_itc only opens a service whose page has data (flags
// bit 1), and sysmon, mmi_root and dp open B3 once at start-up, so the slave keeps the page filled from
// power-on (the master clears the shared RAM while it boots, car_notify_tick fills it again).
bool carin_state::slave_gps_record()
{
	const uint32_t page = 0xb300;
	if (shared_byte(page + 0))
		return false;
	// One record for both services: service 0x83 reads longs 0-6, service 0x82 longs 7-35 (dp and the
	// diagnosis map them into one struct). Bytes go through unswapped, so the longs are big-endian.
	// long 3 latitude, 4 longitude, 5 height (dm); long 8 bits 0-15 satellites tracked (dp: "TRK"
	// without a fix), long 9 bits 16-31 satellites used (?); long 20 bits 16-31 fix (2 = 2D, 3 = 3D);
	// long 21 bits 16-23 flags (bit 6 receiver answers, bit 0 almanac (?), bit 2 position valid, bit 3 fix).
	uint32_t longs[36] = {};
	longs[3] = gps_latitude();
	longs[4] = gps_longitude();
	longs[5] = 1000;
	longs[8] = 6;
	longs[9] = 6u << 16;
	longs[20] = 3u << 16;
	longs[21] = 0x4du << 16;
	set_shared_byte(page + 1, 1);
	set_shared_byte(page + 2, 0x82);
	set_shared_byte(page + 3, shared_byte(page + 3) + 1);
	set_shared_byte(page + 4, 0x02);
	set_shared_byte(page + 5, sizeof(longs));
	for (unsigned i = 0; i < sizeof(longs); i++)
		set_shared_byte(page + 6 + i, uint8_t(longs[i / 4] >> (24 - 8 * (i & 3))));
	set_shared_byte(page + 1, 0);
	return true;
}

TIMER_CALLBACK_MEMBER(carin_state::master_reset)
{
	// With the ignition off the slave cuts the power instead (the unit stays off until the ignition
	// comes back, see car_input_poll); with it on it restarts the master. NV and flash keep their
	// contents, everything else starts over (machine_reset).
	if (!car_ignition())
	{
		m_trace.line(carin_trace::EVENTS, trace_time(), "ignition off: slave switches the unit off");
		m_powered_off = true;
		m_maincpu->set_input_line(INPUT_LINE_RESET, ASSERT_LINE);
		return;
	}
	m_trace.line(carin_trace::EVENTS, trace_time(), "master reset by the slave");
	machine().schedule_soft_reset();
}

// Power-on state of the glue logic and of the slave side; also used when the slave restarts the master.
void carin_state::machine_reset()
{
	std::fill(std::begin(m_mcasic_regs), std::end(m_mcasic_regs), 0);
	m_mcasic_regs[9] = 0x00000040;
	m_mcasic_reg12 = 0x10;
	m_mcasic_mock_pending = false;
	m_mcasic_mock_armed = false;
	m_mcasic_mock_status = 0x0040;
	m_mcasic_mock_phase = 0;
	m_mcasic_boot_status = 0;
	m_mcasic_boot_irq_pending = false;
	m_i2c_timer->adjust(attotime::never);
	m_i2c_result = 0;
	m_i2c_pending = false;
	m_i2c_write_address = -1;
	m_mbox_reply_timer->adjust(attotime::never);
	m_master_reset_timer->adjust(attotime::never);
	m_dr_timer->adjust(attotime::never);
	m_mbox_irq_channel = 0;
	m_cdic_irq = false;
	m_car_navbus_attention = false;
	m_navbus_frames.clear();
	m_car_chunks.clear();
	m_car_notifies = 0;
	m_cd_driver_ready = false;
	m_cd_reported = -1;
	std::fill(std::begin(m_slave_shared_ram), std::end(m_slave_shared_ram), 0);
	std::fill(std::begin(m_arc_ram), std::end(m_arc_ram), 0);
	m_arc_status = 0x91;
	m_arc_imr = m_arc_config = m_arc_subadr = m_arc_nodeid = m_arc_ptr_hi = 0;
	m_arc_address = 0;
	m_arc_rx_page = 2;
	m_tick_enabled = false;
	for (int line = M68K_IRQ_1; line <= M68K_IRQ_7; line++)
		m_maincpu->set_input_line(line, CLEAR_LINE);
}

TIMER_CALLBACK_MEMBER(carin_state::mbox_reply_irq)
{
	m_mbox_irq_channel = uint8_t(param);
	update_level3_irq();
}

// An unsolicited message from the slave on a mailbox channel, when its reply page is free and no
// other slave interrupt is pending. Returns false when it has to wait.
bool carin_state::mbox_post(uint8_t channel, uint8_t type, const uint8_t *payload, unsigned length)
{
	const uint32_t rx = shared_byte(2 + channel * 6 + 3) * 0x100;
	if (!rx || m_mbox_irq_channel || m_mbox_reply_timer->enabled() || shared_byte(rx + 1) == 3)
		return false;
	set_shared_byte(rx + 0, channel);
	set_shared_byte(rx + 2, type);
	set_shared_byte(rx + 6, length >> 8);
	set_shared_byte(rx + 7, length);
	for (unsigned i = 0; i < length; i++)
		set_shared_byte(rx + 8 + i, payload[i]);
	set_shared_byte(rx + 1, 3);
	m_mbox_irq_channel = channel;
	update_level3_irq();
	return true;
}

TIMER_CALLBACK_MEMBER(carin_state::car_notify_tick)
{
	// CD drive state (channel 3, type 6, byte 2: 0x0A and up = disc ready, 2 and below = no disc).
	// cddr_ipc only learns about the disc from these events: once after its start-up request
	// (type 7) and again whenever a disc is loaded or unloaded.
	// A disc first reports spinning up (0x05) and is ready 1.5 s later: when it is loaded while
	// running, and at start-up when the disc is already in the drive.
	const int present = m_cdrom->exists() ? 1 : 0;
	if (m_cd_driver_ready && present && m_cd_reported <= 0 && m_cd_spinup_until == attotime::zero)
		m_cd_spinup_until = machine().time() + attotime::from_msec(1500);
	const bool spinning = present && m_cd_spinup_until != attotime::zero && machine().time() < m_cd_spinup_until;
	const int state = !present ? 0 : spinning ? 2 : 1;
	// The GPS page has to hold data before anybody opens it, see slave_gps_record().
	if (!(shared_byte(0xb300 + 4) & 0x02))
		slave_gps_record();

	if (m_cd_driver_ready && state != m_cd_reported)
	{
		const uint8_t status[4] = { 0x00, 0x00, uint8_t(state == 1 ? 0x0a : state == 2 ? 0x05 : 0x00), 0x00 };
		if (mbox_post(3, 6, status, sizeof(status)))
		{
			m_trace.line(carin_trace::EVENTS, trace_time(), "cd status event: %s", state == 1 ? "disc ready" : state == 2 ? "spinning up" : "no disc");
			m_cd_reported = state;
			if (state != 2)
				m_cd_spinup_until = attotime::zero;
		}
		return;
	}

	// GPS record after the position record, once the mailbox is free again.
	if (m_gps_pending && !m_mbox_irq_channel && m_mbox_reply_timer->remaining().is_never())
	{
		m_gps_pending = false;
		slave_gps_tick();
		return;
	}

	// Channel 8 (/rc5): one "data available" announcement per queued chunk, see car_rc5().
	static const uint8_t available[1] = { 1 };
	if (m_car_notifies && mbox_post(8, 6, available, sizeof(available)))
		m_car_notifies--;
}

TIMER_CALLBACK_MEMBER(carin_state::car_input_poll)
{
	// The ignition key: every press turns it over; the layout shows it through the "ignition" output.
	const uint32_t controls = m_car_controls->read();
	if (BIT(controls & ~m_car_controls_last, 0))
	{
		m_ignition_on = !m_ignition_on;
		m_ignition_led = m_ignition_on ? 1 : 0;
		m_trace.line(carin_trace::EVENTS, trace_time(), "ignition %s", m_ignition_on ? "on" : "off");
	}
	m_car_controls_last = controls;

	// Ignition back on while the unit is switched off: the slave powers it up again.
	if (m_powered_off && car_ignition())
	{
		m_trace.line(carin_trace::EVENTS, trace_time(), "ignition on: slave switches the unit on");
		m_powered_off = false;
		m_maincpu->set_input_line(INPUT_LINE_RESET, CLEAR_LINE);
		machine().schedule_soft_reset();
		return;
	}

	// Panel keys send 3A->3B fn 0x48 <code> when pressed; the knob sends fn 0x49 with one step,
	// bit 6 set for the negative direction.
	const uint32_t keys = m_car_input->read();
	const uint32_t pressed = keys & ~m_car_input_last;
	m_car_input_last = keys;
	for (unsigned bit = 0; bit < std::size(s_car_key_codes); bit++)
		if (BIT(pressed, bit))
			car_frame(0x3a, 0x3b, 0x48, s_car_key_codes[bit]);
	if (BIT(pressed, 13))
		car_frame(0x3a, 0x3b, 0x49, 0x40 | 1);
	if (BIT(pressed, 14))
		car_frame(0x3a, 0x3b, 0x49, 1);
}

uint8_t carin_state::carin_arcnet_r(offs_t offset)
{
	switch (offset & 7)
	{
	case 0: return m_arc_status;
	case 1: return 0;
	case 2: return (m_arc_ptr_hi & 0xc0) | (m_arc_address >> 8);
	case 3: return m_arc_address & 0xff;
	case 4:
	{
		const uint8_t data = m_arc_ram[m_arc_address];
		if (!machine().side_effects_disabled() && (m_arc_ptr_hi & 0x40))
			m_arc_address = (m_arc_address + 1) & 0x7ff;
		return data;
	}
	case 5: return m_arc_subadr;
	case 6: return m_arc_config;
	default: return (m_arc_subadr == 1) ? m_arc_nodeid : 0;
	}
}

void carin_state::carin_arcnet_w(offs_t offset, uint8_t data)
{
	switch (offset & 7)
	{
	case 0: m_arc_imr = data; break;
	case 1: carin_arcnet_command(data); break;
	case 2: m_arc_ptr_hi = data; break;
	case 3: m_arc_address = ((m_arc_ptr_hi & 0x07) << 8) | data; break;
	case 4:
		m_arc_ram[m_arc_address] = data;
		if (m_arc_ptr_hi & 0x40)
			m_arc_address = (m_arc_address + 1) & 0x7ff;
		break;
	case 5: m_arc_subadr = data & 0x07; break;
	case 6:
		if (data & 0x80)
			m_arc_status = 0x91;
		m_arc_config = data;
		m_arc_subadr = data & 0x03;
		break;
	default:
		if (m_arc_subadr == 1)
			m_arc_nodeid = data;
		break;
	}
}

void carin_state::carin_arcnet_command(uint8_t data)
{
	if ((data & 0x07) == 0x03)
	{
		m_arc_status &= ~0x03;
		carin_arcnet_transmit((data >> 3) & 7);
	}
	else if ((data & 0x07) == 0x04)
	{
		m_arc_status &= ~0x80;
		m_arc_rx_page = (data >> 3) & 7;
	}
	else if ((data & 0x07) == 0x06)
	{
		if (BIT(data, 3))
			m_arc_status &= ~0x10;
		if (BIT(data, 4))
			m_arc_status &= ~0x04;
	}
}

void carin_state::carin_arcnet_transmit(unsigned page)
{
	const unsigned base = page << 9;
	const bool is_short = m_arc_ram[base + 2] != 0;
	if (base + (is_short ? 0x100 : 0x200) > sizeof(m_arc_ram))
		return;

	const unsigned offset = is_short ? m_arc_ram[base + 2] : m_arc_ram[base + 3];
	const unsigned length = (is_short ? 0x100 : 0x200) - offset;
	const uint8_t *data = &m_arc_ram[base + offset];

	char dump[2 * 40 + 1] = {};
	for (unsigned i = 0; i < length && i < 40; i++)
		std::snprintf(dump + i * 2, 3, "%02X", data[i]);
	m_trace.line(carin_trace::ARCNET, trace_time(), "TX page=%u sid=%02X did=%02X len=%u data=%s pc=%06X",
		page, m_arc_ram[base], m_arc_ram[base + 1], length, dump, m_maincpu->pc());

	// The remote node always acknowledges.
	m_arc_status |= 0x03;

	// Frame type 0 is a request: answer with a final type 1 frame (header + error code + result, all success).
	if (length < 8 || (data[0] >> 6) != 0 || (m_arc_status & 0x80))
		return;

	const unsigned rx_base = m_arc_rx_page << 9;
	uint8_t *reply = &m_arc_ram[rx_base + 0x100 - 16];
	m_arc_ram[rx_base + 0] = 0;
	m_arc_ram[rx_base + 1] = m_arc_nodeid;
	m_arc_ram[rx_base + 2] = 0x100 - 16;
	std::fill_n(reply, 16, 0);
	reply[0] = 0x60 | (data[0] & 0x0f);
	reply[1] = data[1];
	m_arc_status |= 0x80;
	m_trace.line(carin_trace::ARCNET, trace_time(), "RX page=%u reply id=%02X", m_arc_rx_page, data[1]);
}

void carin_state::duart_w(offs_t offset, uint8_t data)
{
	offset &= 0x0f;
	if (offset == 0x03 || offset == 0x0b)
	{
		const unsigned channel = (offset == 0x0b) ? 1 : 0;
		static std::string tx_text[2];
		tx_text[channel].push_back(char(data));
		if (tx_text[channel].size() > 96)
			tx_text[channel].erase(0, tx_text[channel].size() - 96);

		if (tx_text[channel].find("Received unexpected request from node ") != std::string::npos)
		{
			const offs_t stack = m_maincpu->state_int(M68K_SP);
			address_space &space = m_maincpu->space(AS_PROGRAM);
			char stack_words[161];
			for (unsigned index = 0; index < 32; index++)
				std::snprintf(stack_words + index * 5, sizeof(stack_words) - index * 5,
					"%04X%s", space.read_word(stack + index * 2), index == 31 ? "" : "/");
			m_trace.line(carin_trace::EVENTS, trace_time(), "IPC error text seen pc=%06X sp=%08X stack=%s",
				m_maincpu->pc(), uint32_t(stack), stack_words);
			tx_text[channel].clear();
		}

		m_uart_out[channel].put(char(data));
		m_uart_out[channel].flush();
	}

	if (offset != 0x03 && offset != 0x0b)
	{
		// IMR is rewritten on every character, so it is only counted.
		if (offset == 0x05)
			m_trace.count("duart_imr_writes");
		else
			m_trace.line(carin_trace::DUART, trace_time(), "W reg=%X val=%02X pc=%06X", offset, data, m_maincpu->pc());
	}

	m_duart->write(offset, data);
}

uint8_t carin_state::duart_r(offs_t offset)
{
	const uint8_t data = m_duart->read(offset & 0x0f);
	if (!machine().side_effects_disabled())
	{
		static const char *const names[16] = { "duart_r0", "duart_r1_sra", "duart_r2", "duart_r3_rx", "duart_r4", "duart_r5_isr", "duart_r6", "duart_r7",
			"duart_r8", "duart_r9", "duart_r10", "duart_r11", "duart_r12", "duart_r13", "duart_r14", "duart_r15" };
		m_trace.count(names[offset & 0x0f]);
	}
	return data;
}

void carin_state::log_irq(const char *source, unsigned level, int state)
{
	static unsigned counts[8] = {};
	if (!state)
		return;
	m_trace.count(source);
	if (counts[level & 7]++ < 12)
		m_trace.line(carin_trace::IRQ, trace_time(), "IRQ%u %s asserted pc=%06X", level, source, m_maincpu->pc());
}

void carin_state::duart_irq_w(int state)
{
	// The OS-9 term/console descriptors declare the DUART on level 2, autovector 26.
	log_irq("duart", 2, state);
	m_maincpu->set_input_line(M68K_IRQ_2, state ? ASSERT_LINE : CLEAR_LINE);
}

void carin_state::vsc_irq_w(int state)
{
	log_irq("vsc", 1, state);
	m_maincpu->set_input_line(M68K_IRQ_1, state ? ASSERT_LINE : CLEAR_LINE);
}

void carin_state::cdic_irq_w(int state)
{
	m_trace.count("irq4_cdic_unused");
	m_cdic_irq = state;
	update_level4_irq();
}

// CPU access to the VSC DRAM goes through the VSC, which arbitrates it against the display.
uint16_t carin_state::vsc_dram_r(offs_t offset, uint16_t mem_mask)
{
	if (!machine().side_effects_disabled())
		m_maincpu->eat_cycles(m_maincpu->attotime_to_cycles(attotime::from_ticks(m_vsc->dram_dtack_cycles(), m_vsc->clock())));
	return m_vsc->dram_r(offset, mem_mask);
}

void carin_state::vsc_dram_w(offs_t offset, uint16_t data, uint16_t mem_mask)
{
	if (!machine().side_effects_disabled())
		m_maincpu->eat_cycles(m_maincpu->attotime_to_cycles(attotime::from_ticks(m_vsc->dram_dtack_cycles(), m_vsc->clock())));
	m_vsc->dram_w(offset, data, mem_mask);
}

// The VSC's own view of its DRAM.
uint16_t carin_state::vram_r(offs_t offset, uint16_t mem_mask)
{
	return m_vram[offset] & mem_mask;
}

void carin_state::vram_w(offs_t offset, uint16_t data, uint16_t mem_mask)
{
	COMBINE_DATA(&m_vram[offset]);
}

void carin_state::vsc_map(address_map &map)
{
	map(0x00000, 0xfffff).rw(FUNC(carin_state::vram_r), FUNC(carin_state::vram_w));
}

void carin_state::placeholder_palette(palette_device &palette) const
{
	for (unsigned i = 0; i < 0x100; i++)
		palette.set_pen_color(i, pal3bit(i >> 5), pal3bit(i >> 2), pal2bit(i));
}

uint32_t carin_state::screen_update(screen_device &screen, bitmap_rgb32 &bitmap, const rectangle &cliprect)
{
	if (m_powered_off)
	{
		bitmap.fill(0, cliprect);
		return 0;
	}
	const unsigned width = std::min<unsigned>(m_vsc->width(), 768);
	uint8_t buffer[768];
	for (int y = cliprect.min_y; y <= cliprect.max_y; y++)
	{
		uint32_t *dest = &bitmap.pix(y);
		if (width == 0 || m_vsc->width() > 768)
		{
			std::fill_n(dest + cliprect.min_x, cliprect.width(), 0);
			continue;
		}
		m_vsc->line(y, buffer, width);
		for (int x = cliprect.min_x; x <= cliprect.max_x; x++)
			dest[x] = (unsigned(x) < width) ? m_palette->pen(buffer[x]) : 0;
	}
	return 0;
}

// MAME models the 68EC030 with a 32-bit address bus, so the interrupt acknowledge space ends at 0xffffffff.
// Every source is autovectored: DUART/ARCNET level 2 (26), MCASIC I2C/h_itc/dc level 3 (27),
// nav bus attention level 4 (28), tick level 6.
void carin_state::carin_cpu_space(address_map &map)
{
	map(0xfffffff0, 0xffffffff).m(m_maincpu, FUNC(m68ec030_device::autovectors_map));
}

void carin_state::carin(machine_config &config)
{
	M68EC030(config, m_maincpu, 16_MHz_XTAL);
	m_maincpu->set_addrmap(AS_PROGRAM, &carin_state::carin_mem);
	m_maincpu->set_addrmap(m68000_base_device::AS_CPU_SPACE, &carin_state::carin_cpu_space);

	screen_device &screen(SCREEN(config, "screen"));
	screen.set_raw(CLOCK_A / 2, 960, 0, 768, 312, 32, 312);
	screen.set_video_attributes(VIDEO_UPDATE_SCANLINE);
	screen.set_screen_update(FUNC(carin_state::screen_update));

	SCC66470(config, m_vsc, CLOCK_A);
	m_vsc->set_addrmap(0, &carin_state::vsc_map);
	m_vsc->set_screen("screen");
	m_vsc->irq().set(FUNC(carin_state::vsc_irq_w));

	CDI220_LCD(config, m_lcd);
	// The VSC outputs 8-bit colour indexes; where CARiN keeps its colour table is not known yet, so this
	// is a placeholder RRRGGGBB palette.
	PALETTE(config, m_palette, FUNC(carin_state::placeholder_palette), 0x100);
	config.set_default_layout(layout_carin);

	CDI_CDIC(config, m_cdic, 45.1584_MHz_XTAL / 2);
	m_cdic->set_clock2(45.1584_MHz_XTAL * 3 / 7);
	m_cdic->intreq_callback().set(FUNC(carin_state::cdic_irq_w));

	mc68681_device &duart(MC68681(config, m_duart, 3'686'400));
	duart.irq_cb().set(FUNC(carin_state::duart_irq_w));
	rs232_port_device &terminal_a(RS232_PORT(config, "terminal_a", default_rs232_devices, "terminal"));
	// Port B carries nothing useful; its output still goes to uart_b.txt.
	rs232_port_device &terminal_b(RS232_PORT(config, "terminal_b", default_rs232_devices, nullptr));
	terminal_a.rxd_handler().set(m_duart, FUNC(mc68681_device::rx_a_w));
	duart.a_tx_cb().set(terminal_a, FUNC(rs232_port_device::write_txd));
	terminal_b.rxd_handler().set(m_duart, FUNC(mc68681_device::rx_b_w));
	duart.b_tx_cb().set(terminal_b, FUNC(rs232_port_device::write_txd));
	CDI_SLAVE_HLE(config, m_slave_hle);
	// The CD-i slave HLE is unused by CARiN; its stuck IRQ2 would otherwise starve the OS-9 kernel.
	m_slave_hle->atten_callback().set(m_cdic, FUNC(cdicdic_device::atten_w));
	m_slave_hle->lcd_callback().set(m_lcd, FUNC(cdi220_lcd::state_w));
	m_slave_hle->read_mousex().set_ioport("MOUSEX");
	m_slave_hle->read_mousey().set_ioport("MOUSEY");
	m_slave_hle->read_mousebtn().set_ioport("MOUSEBTN");
	m_slave_hle->testplug_callback().set_ioport("SERVICE").bit(0);

	CDROM(config, m_cdrom).set_interface("cdrom");
	SOFTWARE_LIST(config, "cd_list").set_original("cdi");

	SPEAKER(config, "speaker", 2).front();
	DMADAC(config, m_dmadac[0]);
	m_dmadac[0]->add_route(ALL_OUTPUTS, "speaker", 1.0, 0);
	DMADAC(config, m_dmadac[1]);
	m_dmadac[1]->add_route(ALL_OUTPUTS, "speaker", 1.0, 1);
	MK48T08(config, "mk48t08");
	NVRAM(config, "nv", nvram_device::DEFAULT_NONE).set_base(m_nv, sizeof(m_nv));
	for (unsigned i = 0; i < 4; i++)
		AMD_29F040(config, m_flash[i]);
	AMD_29F080(config, m_bootflash);
	AMD_29F080(config, m_bootflash2);
	RAM(config, m_ram).set_default_size("4M").set_extra_options("2M").set_default_value(0);
}

ROM_START( carin )
	// First-boot contents of the boot flash; later writes persist in nvram/carin/bootflash.
	ROM_REGION( 0x100000, "bootflash", ROMREGION_ERASEFF )
	ROM_LOAD( "bootrom_0209.bin", 0x000000, 0x10000, CRC(f8d1cd01) SHA1(a4fc348047a3c6ac5536403e979e09478d8c1dec) )

	ROM_REGION( 0x2000, "nv", 0 )
	ROM_LOAD( "nv.img", 0x0000, 0x2000, CRC(a7e7e5d6) SHA1(b1781f406936aab1a7db6c1f5d22ead08394c999) )

ROM_END

// The other hardware variant on the NAV_SW disc (Mk2IC/0109, bootrom "121198,1.21"; 0209 is "2.21").
// The variant is the factory product id in NV (phil_id at 0 and its copy at 0x400: "Mk2IC0109"), from
// which the bootrom and IL build the release path on the disc; its own loader.ini and slave.apl there,
// the application software is shared. nv.img is the 0209 image with that id changed (and the
// block checksum at +0x0a, the byte sum of the 0x1e bytes).
ROM_START( carin0109 )
	ROM_REGION( 0x100000, "bootflash", ROMREGION_ERASEFF )
	ROM_LOAD( "bootrom_0109.bin", 0x000000, 0x10000, CRC(aac618fc) SHA1(0bff690eb161524a1c6c9368525b41fc664b2ad5) )

	ROM_REGION( 0x2000, "nv", 0 )
	ROM_LOAD( "nv.img", 0x0000, 0x2000, CRC(aeb509aa) SHA1(851582fe852f14eaaefaf5210046fab1ba385782) )
ROM_END


/*    YEAR  NAME       PARENT  COMPAT  MACHINE  INPUT  CLASS        INIT        COMPANY    FULLNAME */
CONS( 1995, carin,     0,      0,      carin,   carin, carin_state, empty_init, "Philips", "CARiN Mk1/Mk2 Navigation System (Renault)", MACHINE_NOT_WORKING | MACHINE_IMPERFECT_GRAPHICS | MACHINE_IMPERFECT_SOUND )
CONS( 1995, carin0109, carin,  0,      carin,   carin, carin_state, empty_init, "Philips", "CARiN Mk2 Navigation System (Renault, hardware 0109)", MACHINE_NOT_WORKING | MACHINE_IMPERFECT_GRAPHICS | MACHINE_IMPERFECT_SOUND )
