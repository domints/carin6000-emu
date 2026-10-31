// license:BSD-3-Clause
// copyright-holders:The MAME Team
/*******************************************************************

    STMicroelectronics ST10F269

    C166 core with 256 KB internal flash and the usual C167-class
    peripherals. The on-chip flash is a 320 KB linear image: the
    real blocks live at 00000-07FFF and 18000-4FFFF, and the gap
    between them is not flash. External flash (the AM29F800 on
    the CD70) is mapped at 100000-1FFFFF, which is the window
    ADDRSEL2 opens during reset.

    The CPU clock is 40 MHz. Pass that as the device clock; a
    simple instruction then takes two clocks, 20 MIPS.

*******************************************************************/

#ifndef MAME_CPU_C166_ST10F269_H
#define MAME_CPU_C166_ST10F269_H

#pragma once

#include "c166.h"

#include <deque>
#include <vector>


DECLARE_DEVICE_TYPE(ST10F269, st10f269_device)


class st10f269_device : public c166_cpu_device
{
public:
	st10f269_device(const machine_config &mconfig, const char *tag, device_t *owner, uint32_t clock);

	// Linear image of the internal map, 0x00000-0x4FFFF (320 KB).
	void load_internal(uint8_t const *data, uint32_t size);
	// External flash placed at CPU address 0x100000.
	void load_external(uint8_t const *data, uint32_t size);

	auto asc_tx_cb() { return m_asc_tx.bind(); }
	void asc_rx(uint8_t data);

	// External pin level. A pin programmed as an input reads this, not the latch.
	void set_pin(unsigned port, uint16_t value);
	// Sampled at reset together with P0L.4 low: bootstrap loader instead of the flash vector.
	void bootstrap_arm(bool arm) { m_bootstrap_arm = arm; }

protected:
	virtual void device_config_complete() override;
	virtual void device_start() override ATTR_COLD;
	virtual void device_reset() override ATTR_COLD;

	virtual bool image_present() const override { return m_has_image; }
	virtual void burn_cycles(int cycles) override;
	virtual void poll_peripherals() override;
	virtual bool pick_irq(int cpu_ilvl, uint16_t &vector, int &level) override;
	virtual void on_einit() override;
	virtual void on_srvwdt() override;

private:
	void internal_map(address_map &map) ATTR_COLD;

	uint8_t mem_r(offs_t offset);
	void mem_w(offs_t offset, uint8_t data);
	uint8_t sfr_read(uint32_t addr);
	void sfr_write(uint32_t addr, uint8_t data);
	uint16_t sfr_word(uint32_t addr) const;
	void sfr_word_set(uint32_t addr, uint16_t data);
	void tx_byte(uint8_t data);
	void tick_timer(uint32_t count_addr, uint32_t reload_addr, uint32_t ic_addr, bool run, int ticks);
	void note_write(uint32_t addr, uint8_t data);
	void note_bus(uint32_t addr);
	bool xper_on(int bit) const;
	uint16_t esfr_word(uint32_t addr) const;
	void esfr_word_set(uint32_t addr, uint16_t data);
	uint16_t port_read(uint32_t addr);
	void service_pec();
	void service_can(int which);
	void deliver_can(int src, uint32_t id, bool extended, uint8_t dlc, uint8_t const *data);
	void tick_rtc(int cycles);
	void tick_pwm(int ticks);
	void tick_capcom(int ticks);
	void tick_adc(int cycles);
	int flash_block(uint32_t addr) const;
	void flash_erase(int block);
	bool flash_program(uint32_t addr, uint8_t data);

	devcb_write8 m_asc_tx;

	std::vector<uint8_t> m_mem;
	std::vector<uint8_t> m_int;
	std::vector<uint8_t> m_ext;
	uint8_t m_sfr[0x200];
	uint8_t m_esfr[0x200];
	uint8_t m_sfr_seen[0x200];
	uint8_t m_esfr_seen[0x200];

	std::deque<uint8_t> m_rx;
	std::string m_line;
	uint32_t m_line_log;
	uint32_t m_sfr_log;

	uint32_t m_wdt;
	uint32_t m_wdt_hits;
	int m_presc;
	bool m_has_image;
	bool m_logged_image;

	uint8_t m_xram1[0x800];
	uint8_t m_xram2[0x2000];
	uint8_t m_can1[0x100];
	uint8_t m_can2[0x100];
	uint8_t m_rtc[0x20];
	uint16_t m_pin[9];
	uint16_t m_cc_shadow[16];
	uint8_t m_flash_state;
	uint8_t m_flash_status;
	bool m_flash_lock;
	bool m_bootstrap_arm;
	bool m_boot_wait;
	int m_boot_left;
	uint32_t m_boot_at;
	int m_adc_left;
	bool m_adc_busy;
	bool m_adc_held;
	uint32_t m_rtc_div;
	uint8_t m_last_bus;
	uint8_t m_gpt_prev;
};

#endif
