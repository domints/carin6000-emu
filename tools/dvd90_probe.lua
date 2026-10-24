-- Register and memory dump of the DVD90 nav CPU at PROBE_AT emulated seconds (default 3).
--   PROBE_MEM=addr:len,...  virtual (kseg0/kseg1) or physical addresses to dump
--   PROBE_LIST=reg          follow a linked list from register reg (next pointer at +0)
local machine = manager.machine
local cpu = machine.devices[":navcpu"]
local space = cpu.spaces["program"]
local out = io.open("trace/probe.log", "w")
local probe_at = tonumber(os.getenv("PROBE_AT") or "3")
local done = false

local function reg(name)
	local ok, value = pcall(function() return cpu.state[name].value end)
	return ok and value or 0
end

local function log(text)
	out:write(text, "\n")
	out:flush()
end

local function phys(addr)
	if addr >= 0x80000000 and addr < 0xc0000000 then
		return addr & 0x1fffffff
	end
	return addr
end

local function word(addr)
	return space:read_u32(phys(addr) & ~3)
end

emu.register_frame_done(function()
	if done or machine.time:as_double() < probe_at then
		return
	end
	done = true
	local parts = {}
	for _, name in ipairs({ "PC", "SR", "Cause", "EPC", "BadVAddr" }) do
		parts[#parts + 1] = string.format("%s=%08X", name, reg(name))
	end
	log(table.concat(parts, " "))
	for row = 0, 31, 8 do
		parts = {}
		for i = row, row + 7 do
			parts[#parts + 1] = string.format("r%-2d=%08X", i, reg("R" .. i))
		end
		log(table.concat(parts, " "))
	end
	for item in string.gmatch(os.getenv("PROBE_MEM") or "", "[^,]+") do
		local address, length = string.match(item, "^(%x+):(%d+)$")
		if address then
			address = tonumber(address, 16)
			for row = 0, tonumber(length) - 1, 16 do
				local words = {}
				for i = 0, 12, 4 do
					words[#words + 1] = string.format("%08X", word(address + row + i))
				end
				log(string.format("MEM %08X %s", address + row, table.concat(words, " ")))
			end
		end
	end
	local list = os.getenv("PROBE_LIST")
	if list then
		local node = reg("R" .. list)
		local seen = {}
		for i = 1, 40 do
			if node == 0 then
				log("LIST end")
				break
			end
			if seen[node] then
				log(string.format("LIST cycle back to %08X", node))
				break
			end
			seen[node] = true
			log(string.format("LIST %08X next=%08X size=%08X", node, word(node), word(node + 4)))
			node = word(node)
		end
	end
	-- return-address chain is not recoverable without frame info; print the stack top instead
	local sp = reg("R29")
	local words = {}
	for i = 0, 23 do
		words[#words + 1] = string.format("%08X", word(sp + i * 4))
	end
	log("STACK " .. table.concat(words, " "))
	out:close()
	machine:exit()
end)
