// license:BSD-3-Clause
// copyright-holders:The MAME Team
/*******************************************************************

    Toshiba TMP92FD54A / TMP92FD54AIF

    TLCS-900/H1 single-chip microcontroller. 512 KB internal flash,
    32 KB internal RAM. Same silicon as the TMP92CD54I apart from
    the flash instead of mask ROM.

    Single-chip mode, the way the radio firmware runs:

        000000-0003ff  internal I/O
        000400-0083ff  internal RAM, 32 KB
        f80000-ffffff  internal flash, 512 KB
        ffff00-ffffff  interrupt vectors (last 16 bytes are reserved)

    The crystal on the board is 10 MHz. The on-chip doubler runs the
    core at 20 MHz; the datasheet's 50 ns instruction is quoted at
    fOSC = 10 MHz. Pass 10 MHz * 2 as the device clock.

*******************************************************************/

#ifndef MAME_CPU_TLCS900_TMP92FD54_H
#define MAME_CPU_TLCS900_TMP92FD54_H

#pragma once

#include "tlcs900.h"

DECLARE_DEVICE_TYPE(TMP92FD54, tmp92fd54_device)


class tmp92fd54_device : public tlcs900h_device
{
public:
	tmp92fd54_device(const machine_config &mconfig, const char *tag, device_t *owner, uint32_t clock);

	// Single-chip image, 512 KB, laid out as it executes at f80000.
	void load_flash(uint8_t const *data, uint32_t size);

	auto tx0_handler() { return m_tx0.bind(); }
	auto tx1_handler() { return m_tx1.bind(); }
	void rx_w(unsigned channel, uint8_t data);

protected:
	virtual void device_config_complete() override;
	virtual void device_start() override ATTR_COLD;
	virtual void device_reset() override ATTR_COLD;

	virtual void execute_set_input(int inputnum, int state) override;
	virtual void tlcs900_check_hdma() override;
	virtual void tlcs900_check_irqs() override;
	virtual void tlcs900_handle_ad() override;
	virtual void tlcs900_handle_timers() override;

	virtual std::unique_ptr<util::disasm_interface> create_disassembler() override;

private:
	void internal_map(address_map &map) ATTR_COLD;

	uint8_t sfr_r(offs_t offset);
	void sfr_w(offs_t offset, uint8_t data);
	uint8_t flash_r(offs_t offset);
	void flash_w(offs_t offset, uint8_t data);
	uint8_t ext_r(offs_t offset);
	void ext_w(offs_t offset, uint8_t data);

	void note_sfr(char dir, offs_t offset, uint8_t data);
	void raise_cause(offs_t inte, uint8_t bit);
	void tx_byte(unsigned channel, uint8_t data);
	void trace_pc(int param);

	devcb_write8 m_tx0;
	devcb_write8 m_tx1;

	std::vector<uint8_t> m_flash;
	uint8_t m_sfr[0x400];
	uint8_t m_rx[2];
	bool m_rx_full[2];

	uint32_t m_pre[4];
	uint8_t m_tcount[8];
	uint16_t m_t16[2];
	uint32_t m_t16pre[2];
	uint32_t m_wd_count;

	uint32_t m_sfr_log;
	uint8_t m_seen[0x400];
	uint32_t m_ext_seen[32];
	int m_ext_n;
	uint64_t m_irq_seen;

	emu_timer *m_trace;
};

#endif // MAME_CPU_TLCS900_TMP92FD54_H
