// license:BSD-3-Clause
// copyright-holders:The MAME Team

#ifndef MAME_CPU_C166_C166DASM_H
#define MAME_CPU_C166_C166DASM_H

#pragma once

class c166_disassembler : public util::disasm_interface
{
public:
	c166_disassembler() = default;
	virtual ~c166_disassembler() = default;

	virtual u32 opcode_alignment() const override;
	virtual offs_t disassemble(std::ostream &stream, offs_t pc, const data_buffer &opcodes, const data_buffer &params) override;
};

#endif
