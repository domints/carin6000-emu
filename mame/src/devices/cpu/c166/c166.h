// license:BSD-3-Clause
// copyright-holders:The MAME Team
/*******************************************************************

    Siemens / Infineon C166 (C167, ST10 classic core)

    16 MB unified little-endian space. Code is addressed as
    CSP:IP. Data addresses are translated through DPP0-DPP3,
    16 KB pages, unless an EXTP or EXTS window is open. The
    register bank, the system stack, and SFR short addresses
    are absolute: they do not go through the DPPs.

    One instruction cycle is two CPU clocks. The MAC coprocessor
    (CoMUL and the rest of the ST10 extension) executes the
    encodings in the ST10 programming manual: opcode 83/93/A3,
    function code in the third byte.

*******************************************************************/

#ifndef MAME_CPU_C166_C166_H
#define MAME_CPU_C166_C166_H

#pragma once


class c166_cpu_device : public cpu_device
{
public:
	enum {
		C166_CSP = 1, C166_IP, C166_PSW, C166_SP, C166_CP,
		C166_STKOV, C166_STKUN, C166_MDL, C166_MDH, C166_MDC,
		C166_DPP0, C166_DPP1, C166_DPP2, C166_DPP3
	};

protected:
	c166_cpu_device(const machine_config &mconfig, device_type type, const char *tag, device_t *owner, uint32_t clock);

	virtual void device_start() override ATTR_COLD;
	virtual void device_reset() override ATTR_COLD;

	virtual uint32_t execute_min_cycles() const noexcept override { return 2; }
	virtual uint32_t execute_max_cycles() const noexcept override { return 40; }
	virtual void execute_run() override;
	virtual void execute_set_input(int inputnum, int state) override;

	virtual space_config_vector memory_space_config() const override;
	virtual void state_import(const device_state_entry &entry) override;
	virtual std::unique_ptr<util::disasm_interface> create_disassembler() override;

	// Core SFRs (DPP, CP, SP, PSW, the multiply registers, ONES/ZEROS).
	// Peripheral SFRs stay in the subclass memory handler.
	bool cpu_sfr_r(uint32_t addr, uint8_t &data);
	bool cpu_sfr_w(uint32_t addr, uint8_t data);

	virtual bool image_present() const { return true; }
	virtual void burn_cycles(int cycles) { }
	virtual void poll_peripherals() { }
	virtual bool pick_irq(int cpu_ilvl, uint16_t &vector, int &level) { return false; }
	virtual void on_einit() { }
	virtual void on_srvwdt() { }

	// A data operand access (not a code fetch) is in progress.
	bool bus_data() const { return m_bus_data; }
	void add_waits(int n);

	address_space_config m_program_config;

	uint8_t m_csp;
	uint16_t m_ip;
	uint16_t m_psw;
	uint16_t m_sp;
	uint16_t m_cp;
	uint16_t m_stkov;
	uint16_t m_stkun;
	uint16_t m_mdl;
	uint16_t m_mdh;
	uint16_t m_mdc;
	uint16_t m_dpp[4];

	bool m_einit;
	bool m_wdt_disable;
	bool m_halt;
	bool m_reset_pending;
	// Set around a software or watchdog reset so RAM survives it.
	bool m_soft_reset;
	bool m_pwrdn;

private:
	void execute();
	void close_prefix();
	uint8_t fetch();
	uint16_t fetch_w();
	uint32_t data_addr(uint16_t addr) const;
	uint32_t sfr_base() const;
	uint16_t rreg(unsigned n);
	void wreg(unsigned n, uint16_t v);
	uint8_t rrb(uint8_t nib);
	void wrb(uint8_t nib, uint8_t v);
	uint16_t rrw(uint8_t rr);
	void wrw(uint8_t rr, uint16_t v);
	uint8_t rrb_sfr(uint8_t rr);
	void wrb_sfr(uint8_t rr, uint8_t v);
	uint16_t read_dw(uint16_t addr);
	void write_dw(uint16_t addr, uint16_t v);
	uint8_t read_db(uint16_t addr);
	void write_db(uint16_t addr, uint8_t v);
	uint16_t ptr_use(unsigned rn, int adj, bool byte_op);
	void push(uint16_t v);
	void push_raw(uint16_t v);
	uint16_t pop();
	void enter_trap(uint16_t vector, int new_ilvl);
	void trap_b(uint8_t op);
	bool check_irq();
	bool cc_true(int cc) const;
	void branch_rel(int8_t rel);

	void flags_mov_w(uint16_t src);
	void flags_mov_b(uint8_t src);
	uint16_t add_w(uint16_t a, uint16_t b, int cin, bool sticky = false);
	uint8_t add_b(uint8_t a, uint8_t b, int cin, bool sticky = false);
	uint16_t sub_w(uint16_t a, uint16_t b, int cin, bool sticky = false);
	uint8_t sub_b(uint8_t a, uint8_t b, int cin, bool sticky = false);
	uint16_t logic_w(uint16_t r, uint16_t src);
	uint8_t logic_b(uint8_t r, uint8_t src);
	uint16_t apply_w(int alu, uint16_t a, uint16_t b);
	uint8_t apply_b(int alu, uint8_t a, uint8_t b);
	void do_alu(int alu, int form);
	void decode(uint8_t op);
	void exec_mac(uint8_t op);
	int64_t mac_acc() const;
	void mac_commit(int64_t value, bool saturate, int carry, bool overflow);
	uint16_t mac_coreg(unsigned id) const;
	uint16_t do_shift(uint16_t v, int count, int kind);
	void bit_set(uint8_t q, int bit, bool value);
	bool bit_get(uint8_t q, int bit);
	uint32_t bit_word(uint8_t q);
	bool protected_seq(uint8_t a, uint8_t b, uint8_t c);

	memory_access<24, 0, 0, ENDIANNESS_LITTLE>::specific m_program;

	int m_icount;
	int m_cycles;
	uint32_t m_pc;
	uint32_t m_ppc;

	int m_extr;
	int m_atomic;
	int m_page_n;
	uint16_t m_page_val;
	bool m_page_seg;
	bool m_page_lock;
	bool m_hold_extr;
	bool m_hold_atomic;
	bool m_hold_page;

	bool m_idle;
	bool m_nmi_pending;
	int m_nmi_line;
	bool m_in_trap;
	bool m_abort;

	uint32_t m_trace;
	uint32_t m_call_log;
	uint32_t m_ill_log;
	uint32_t m_insn;
	uint32_t m_beat;
	bool m_seg_e;
	bool m_seg2;
	bool m_logged_einit;
	bool m_logged_idle;
	uint8_t m_op0_csp;
	uint16_t m_op0_ip;

	bool m_bus_data;

	// MAC. MSW bit 9 reads as 1 (reset value 0200). N Z C SV E SL sit in bits 15..10.
	// MCW bit 15 is MS, bit 14 is MP, bit 13 requests a class B trap when a repeat ends.
	uint16_t m_msw;
	uint16_t m_mah;
	uint16_t m_mal;
	uint16_t m_mcw;
	uint16_t m_mrw;
	uint16_t m_idx0;
	uint16_t m_idx1;
	uint16_t m_qx0;
	uint16_t m_qx1;
	uint16_t m_qr0;
	uint16_t m_qr1;
};

#endif // MAME_CPU_C166_C166_H
