#!/usr/bin/env python3
import sys
import os
import struct

def unpack_file(filepath, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(filepath, "rb") as f:
        data = f.read()

    offset = 0
    mod_count = 0

    while offset < len(data):
        # Look for the OS-9/68k module sync code: 0x4AFC
        if offset + 48 > len(data):
            break

        sync = struct.unpack(">H", data[offset:offset+2])[0]
        if sync != 0x4AFC:
            offset += 2
            continue

        mod_size = struct.unpack(">I", data[offset+4:offset+8])[0]
        name_off = struct.unpack(">I", data[offset+12:offset+16])[0]
        mod_type = data[offset+18]
        mod_lang = data[offset+19]
        exec_off = struct.unpack(">I", data[offset+44:offset+48])[0]

        if mod_size == 0 or offset + mod_size > len(data):
            offset += 2
            continue

        # Module name (ASCII string ending with a zero or with bit 7 set)
        raw_name = bytearray()
        np = offset + name_off
        while np < len(data) and np < offset + mod_size:
            b = data[np]
            if b == 0:
                break
            raw_name.append(b & 0x7F)  # OS-9 marks the last character with bit 7 = 1
            if b & 0x80:
                break
            np += 1

        name = raw_name.decode("ascii", errors="replace").strip()
        if not name:
            name = f"mod_{mod_count:02d}"

        # Make the name safe as a file name
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        filename = f"{mod_count:02d}_{safe_name}.mod"
        target_path = os.path.join(out_dir, filename)

        mod_bytes = data[offset : offset + mod_size]
        with open(target_path, "wb") as out:
            out.write(mod_bytes)

        types = {1: "Prog", 2: "Subr", 3: "Multi", 4: "Data", 12: "Device", 13: "Driver", 14: "Desc"}
        t_str = types.get(mod_type, f"0x{mod_type:02X}")

        print(f"[{mod_count:02d}] {name:<20} Type: {t_str:<8} Size: {mod_size:<8} Entry: 0x{exec_off:06X}")

        offset += mod_size
        mod_count += 1

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"usage: {sys.argv[0]} <input file> <output directory>")
        sys.exit(1)
    unpack_file(sys.argv[1], sys.argv[2])
    