// license:BSD-3-Clause
// copyright-holders:Ryan Holtz

#ifndef MAME_PHILIPS_CARIN_H
#define MAME_PHILIPS_CARIN_H

#include "machine/mc68681.h"
#include "machine/intelfsh.h"
#include "machine/ram.h"
#include "cpu/m68000/m68030.h"
#include "cdislavehle.h"
#include "cdicdic.h"
#include "cdi220_lcd.h"
#include "sound/dmadac.h"
#include "machine/scc66470.h"
#include "emupal.h"
#include "bus/rs232/rs232.h"
#include "screen.h"

#include "carin_trace.h"

#include <deque>
#include <vector>
#include <fstream>

class carin_state : public driver_device
{
public:
	carin_state(const machine_config &mconfig, device_type type, const char *tag)
		: driver_device(mconfig, type, tag)
		, m_maincpu(*this, "maincpu")
		, m_lcd(*this, "lcd")
		, m_slave_hle(*this, "slave_hle")
		, m_cdic(*this, "cdic")
		, m_cdrom(*this, "cdrom")
		, m_vsc(*this, "vsc")
		, m_palette(*this, "palette")
		, m_duart(*this, "duart")
		, m_dmadac(*this, "dac%u", 1U)
		, m_flash(*this, "flash%u", 0U)
		, m_bootflash(*this, "bootflash")
		, m_bootflash2(*this, "bootflash2")
		, m_ram(*this, "ram")
		, m_car_controls(*this, "CAR")
		, m_ignition_led(*this, "ignition")
		, m_car_input(*this, "CAR_KEYS")
		, m_car_drive(*this, "CAR_DRIVE")
		, m_car_view(*this, "car_view%u", 0U)
		, m_car_cmd(*this, "car_cmd%u", 0U)
	{ }

	void carin(machine_config &config);

private:
	virtual void machine_start() override ATTR_COLD;
	virtual void machine_reset() override ATTR_COLD;

	required_device<m68ec030_device> m_maincpu;
	required_device<cdi220_lcd> m_lcd;
	required_device<cdislave_hle_device> m_slave_hle;
	// Backed by the "nv" nvram device, which takes its first-boot contents from the "nv" region (nv.img).
	uint8_t m_nv[0x2000] = {};
	required_device<cdicdic_device> m_cdic;
	required_device<cdrom_image_device> m_cdrom;
	// Video: an SCC66470 (VSC) with 512 KB DRAM at 0x600000, registers at 0x7fffe0 and the pixel
	// accelerator window (IPA) at 0x1600000; videodr runs a 384x240 8-bit screen on it.
	required_device<scc66470_device> m_vsc;
	required_device<palette_device> m_palette;
	std::unique_ptr<uint16_t[]> m_vram;
	required_device<mc68681_device> m_duart;
	required_device_array<dmadac_sound_device, 2> m_dmadac;
	// Main flash (flsh, nav software): four 29F040 on the byte lanes of the 32-bit bus.
	required_device_array<amd_29f040_device, 4> m_flash;
	// Boot flash (bootrom, flsh_boot, flsh_voice, flsh_slave2): two byte-wide 1 MB chips at 0x000000.
	required_device<amd_29f080_device> m_bootflash;    // 0x000000, bootrom at the bottom
	required_device<amd_29f080_device> m_bootflash2;   // 0x100000, ends with flsh_slave2/flsh_hdr
	required_device<ram_device> m_ram;                  // system RAM, then the Extension RAM if fitted
	uint32_t m_mcasic_regs[16] = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x00000040 };
	uint8_t m_mcasic_reg12 = 0x10;
	bool m_mcasic_mock_pending = false;
	bool m_mcasic_mock_armed = false;
	uint16_t m_mcasic_mock_status = 0x0040;
	uint8_t m_mcasic_mock_phase = 0;
	uint8_t m_mcasic_boot_status = 0;
	bool m_mcasic_boot_irq_pending = false;
	emu_timer *m_i2c_timer = nullptr;
	uint16_t m_i2c_result = 0;
	bool m_i2c_pending = false;
	uint8_t m_mbox_irq_channel = 0;
	int m_i2c_write_address = -1;
	bool m_cdic_irq = false;

	// Car side (HLE): what the car around the unit answers. Fixed for now; meant to be driven by a
	// car emulator window later (ignition, nav bus display, ...).
	required_ioport m_car_controls;        // CAR: ignition key (press to turn it over)
	bool m_ignition_on = true;             // key switch / +12V after ignition, reported by the slave
	uint32_t m_car_controls_last = 0;
	output_finder<> m_ignition_led;        // layout: IGNITION ON/OFF
	bool car_ignition() const { return m_ignition_on; }
	bool m_powered_off = false;            // the slave has cut the power (ignition off)
	bool m_car_navbus_attention = false;   // the nav bus display (I2C 0x50) asks to be read
	required_ioport m_car_input;           // panel keys and knob, see s_car_key_codes
	uint32_t m_car_input_last = 0;
	std::deque<std::vector<uint8_t>> m_navbus_frames;   // module -> unit frames waiting in nav bus slot 1
	std::deque<std::vector<uint8_t>> m_car_chunks;      // /rc5 data waiting for h_ibus_dr reads
	emu_timer *m_car_input_timer = nullptr;
	emu_timer *m_car_notify_timer = nullptr;
	emu_timer *m_mbox_reply_timer = nullptr;
	emu_timer *m_master_reset_timer = nullptr;
	TIMER_CALLBACK_MEMBER(master_reset);
	emu_timer *m_dr_timer = nullptr;
	uint8_t m_dr_record[0x4c] = {};
	TIMER_CALLBACK_MEMBER(slave_dr_tick);
	void slave_gps_tick();
	bool slave_gps_record();
	bool m_gps_pending = false;
	// Car side: the simulated car behind the slave's dead reckoning (B2) and GPS receiver (B3), driven by
	// the CAR_DRIVE keys and by the car window (plugin carsim) through m_car_view / m_car_cmd.
	required_ioport m_car_drive;
	emu_timer *m_car_sim_timer = nullptr;
	TIMER_CALLBACK_MEMBER(car_sim_tick);
	void car_sim_command();
	double m_car_latitude = 52.2297;       // degrees, north positive
	double m_car_longitude = 21.0122;      // degrees, east positive
	double m_car_heading = 0;              // degrees clockwise from north
	double m_car_speed = 0;                // m/s, negative in reverse
	double m_car_odometer = 0;             // m
	bool m_car_gps_fix = true;             // the GPS antenna sees the sky
	double m_dr_distance = 0;              // cm driven since the last B2 record
	double m_dr_turn = 0;                  // 0.01 degree turned since the last B2 record
	double m_dr_error = 0;                 // cm, the slave's position error estimate (B2 L8/L9)
	attotime m_dr_last;                    // time of the last B2 record
	output_finder<8> m_car_view;           // car_view0-7: for the car window, see car_sim_tick
	output_finder<4> m_car_cmd;            // car_cmd0-3: from the car window, see car_sim_command
	int32_t gps_latitude() const;
	int32_t gps_longitude() const;
	unsigned m_car_notifies = 0;           // "data available" announcements still to send
	bool m_cd_driver_ready = false;        // cddr_ipc started (type 7 seen from OS-9)
	int m_cd_reported = -1;                // drive state last reported: -1 not yet, 0 none, 1 ready, 2 spinning
	attotime m_cd_spinup_until = attotime::zero;
	bool mbox_post(uint8_t channel, uint8_t type, const uint8_t *payload, unsigned length);
	static const uint8_t s_car_key_codes[13];
	void car_frame(uint8_t src, uint8_t dst, uint8_t fn, uint8_t data);
	void car_rc5(uint8_t code);
	TIMER_CALLBACK_MEMBER(car_input_poll);
	TIMER_CALLBACK_MEMBER(car_notify_tick);
	TIMER_CALLBACK_MEMBER(mbox_reply_irq);
	uint32_t m_slave_shared_ram[0x10000 / 4] = {};
	std::ofstream m_uart_out[2];
	carin_trace m_trace;
	double trace_time() { return machine().time().as_double(); }
	uint8_t m_arc_ram[0x800] = {};
	uint8_t m_arc_status = 0x91;
	uint8_t m_arc_imr = 0;
	uint8_t m_arc_config = 0;
	uint8_t m_arc_subadr = 0;
	uint8_t m_arc_nodeid = 0;
	uint8_t m_arc_ptr_hi = 0;
	uint16_t m_arc_address = 0;
	uint8_t m_arc_rx_page = 2;
	emu_timer *m_pc_watch_timer = nullptr;
	emu_timer *m_tick_timer = nullptr;
	bool m_tick_enabled = false;

	uint16_t vsc_dram_r(offs_t offset, uint16_t mem_mask = ~0);
	void vsc_dram_w(offs_t offset, uint16_t data, uint16_t mem_mask = ~0);
	uint16_t vram_r(offs_t offset, uint16_t mem_mask = ~0);
	void vram_w(offs_t offset, uint16_t data, uint16_t mem_mask = ~0);
	void vsc_map(address_map &map) ATTR_COLD;
	void placeholder_palette(palette_device &palette) const;
	uint32_t screen_update(screen_device &screen, bitmap_rgb32 &bitmap, const rectangle &cliprect);
	uint32_t carsim_update(screen_device &screen, bitmap_rgb32 &bitmap, const rectangle &cliprect);
	TIMER_CALLBACK_MEMBER(pc_watch_tick);
	TIMER_CALLBACK_MEMBER(system_tick);
	uint32_t mcasic_r(offs_t offset);
	void mcasic_w(offs_t offset, uint32_t data, uint32_t mem_mask = ~0);
	void i2c_control_w(uint16_t data);
	void update_level3_irq();
	void update_level4_irq();
	TIMER_CALLBACK_MEMBER(i2c_done);
	uint32_t carin_slave_r(offs_t offset, uint32_t mem_mask);
	void carin_slave_w(offs_t offset, uint32_t data, uint32_t mem_mask);
	uint8_t carin_arcnet_r(offs_t offset);
	void carin_arcnet_w(offs_t offset, uint8_t data);
	void carin_arcnet_command(uint8_t data);
	void carin_arcnet_transmit(unsigned page);
	void carin_mailbox_kick(uint8_t channel);
	uint8_t shared_byte(uint32_t offset) const;
	void set_shared_byte(uint32_t offset, uint8_t value);
	void cdic_irq_w(int state);
	uint8_t duart_r(offs_t offset);
	void duart_w(offs_t offset, uint8_t data);
	void duart_irq_w(int state);
	void vsc_irq_w(int state);
	void log_irq(const char *source, unsigned level, int state);
	void carin_mem(address_map &map) ATTR_COLD;
	void carin_cpu_space(address_map &map) ATTR_COLD;
};

#endif // MAME_PHILIPS_CARIN_H
