// license:BSD-3-Clause
// copyright-holders:The MAME Team
/*******************************************************************

    ST10F269 instruction and peripheral test machine.

    The ROM comes from ST10_TEST (a generated image of the internal
    map). ST10_BOOT, when set, is 32 bytes fed to ASC0 after a
    bootstrap reset: P0L.4 is held low and the CPU waits in halt
    until those bytes have been written at FA40.

*******************************************************************/

#include "emu.h"
#include "cpu/c166/st10f269.h"

#include <cstdlib>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>


namespace {

class st10test_state : public driver_device
{
public:
	st10test_state(const machine_config &mconfig, device_type type, const char *tag)
		: driver_device(mconfig, type, tag)
		, m_cpu(*this, "maincpu")
	{
	}

	void st10test(machine_config &config);

protected:
	virtual void machine_start() override;

private:
	void tick(int param);
	std::vector<uint8_t> load_file(char const *path) const;

	required_device<st10f269_device> m_cpu;
	emu_timer *m_tick;
	std::vector<uint8_t> m_feed;
	unsigned m_feed_at;
};


std::vector<uint8_t> st10test_state::load_file(char const *path) const
{
	std::ifstream in(path, std::ios::binary);
	if (!in)
	{
		logerror("st10test: cannot open %s\n", path);
		return {};
	}
	return std::vector<uint8_t>(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}

void st10test_state::machine_start()
{
	m_feed_at = 0;
	m_tick = timer_alloc(FUNC(st10test_state::tick), this);
	char const *boot = std::getenv("ST10_BOOT");
	char const *image = std::getenv("ST10_TEST");
	if (boot && *boot)
	{
		m_feed = load_file(boot);
		m_cpu->bootstrap_arm(true);
		m_cpu->set_pin(0, 0);
	}
	if (image && *image)
	{
		std::vector<uint8_t> const data = load_file(image);
		if (!data.empty())
			m_cpu->load_internal(data.data(), uint32_t(data.size()));
	}
	else if (!m_feed.empty())
	{
		uint8_t const dummy[4] = { 0xcc, 0x00, 0xcc, 0x00 };
		m_cpu->load_internal(dummy, 4);
	}
	// P8.0 is an external input. P3.1 is the HOLD request the bus test reads back as HLDA.
	m_cpu->set_pin(8, 0x0001);
	m_cpu->set_pin(3, 0x0002);
	m_tick->adjust(attotime::from_usec(20), 0, attotime::from_usec(20));
}

void st10test_state::tick(int param)
{
	(void)param;
	if (m_feed_at < m_feed.size())
		m_cpu->asc_rx(m_feed[m_feed_at++]);
	uint8_t const flag = m_cpu->space(AS_PROGRAM).read_byte(0xf908);
	if (flag == 1)
	{
		m_cpu->space(AS_PROGRAM).write_byte(0xf908, 0);
		m_cpu->set_input_line(INPUT_LINE_NMI, ASSERT_LINE);
		m_cpu->set_input_line(INPUT_LINE_NMI, CLEAR_LINE);
	}
}

void st10test_state::st10test(machine_config &config)
{
	ST10F269(config, m_cpu, 40_MHz_XTAL);
}

} // anonymous namespace

ROM_START(st10test)
	ROM_REGION(0x10, "dummy", ROMREGION_ERASEFF)
ROM_END

INPUT_PORTS_START(st10test)
INPUT_PORTS_END

GAME(2002, st10test, 0, st10test, st10test, st10test_state, empty_init, ROT0, "STMicroelectronics", "ST10F269 test machine", MACHINE_NO_SOUND_HW | MACHINE_SUPPORTS_SAVE)
