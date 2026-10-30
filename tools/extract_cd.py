#!/usr/bin/env python3
"""Extract the files of the CARiN CD-i disc (raw MODE2/2352 image).

Usage: extract_cd.py [image] [output dir]
Defaults: cd/carin_nav_sw.img -> temp/extracted_cd
"""
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "cd" / "carin_nav_sw.img")
OUT = sys.argv[2] if len(sys.argv) > 2 else str(ROOT / "temp" / "extracted_cd")

RAW_SECTOR = 2352
DATA_OFFSET = 24
DATA_SIZE = 2048

def read_lba(f, lba, count=1):
    f.seek((lba * RAW_SECTOR) + DATA_OFFSET)
    return f.read(count * DATA_SIZE)

with open(IMAGE, "rb") as f:
    pvd = read_lba(f, 16)
    pt_size = struct.unpack(">I", pvd[136:140])[0]
    pt_lba  = struct.unpack(">I", pvd[148:152])[0]

    f.seek((pt_lba * RAW_SECTOR) + DATA_OFFSET)
    pt_data = f.read(pt_size)

    directories = []
    dir_lbas = set()
    idx = 0
    dir_num = 1

    # 1. Parse the Type M path table
    while idx < len(pt_data):
        len_di = pt_data[idx]
        if len_di == 0:
            break
        dir_lba = struct.unpack(">I", pt_data[idx + 2 : idx + 6])[0]
        parent  = struct.unpack(">H", pt_data[idx + 6 : idx + 8])[0]
        raw_name = pt_data[idx + 8 : idx + 8 + len_di]
        name = "." if dir_num == 1 else raw_name.decode("ascii", errors="replace")
        
        directories.append({"id": dir_num, "name": name, "lba": dir_lba, "parent": parent})
        dir_lbas.add(dir_lba)
        
        idx += 8 + len_di + (len_di % 2)
        dir_num += 1

    # 2. Create the whole directory tree on disk
    paths = {1: OUT}
    for d in directories[1:]:
        parent_path = paths[d["parent"]]
        full = os.path.join(parent_path, d["name"])
        paths[d["id"]] = full
        os.makedirs(full, exist_ok=True)

    os.makedirs(OUT, exist_ok=True)

    # 3. Dump the files
    for d in directories:
        dir_sector = read_lba(f, d["lba"])
        offset = 0

        while offset < len(dir_sector):
            rec_len = dir_sector[offset]
            if rec_len == 0:
                break

            record = dir_sector[offset : offset + rec_len]
            file_lba  = struct.unpack(">I", record[6:10])[0]
            file_size = struct.unpack(">I", record[14:18])[0]
            
            # Flags: offset 24 for CD-i Green Book, offset 25 for ISO 9660
            is_directory_flag = bool((record[24] & 2) or (record[25] & 2))
            name_len  = record[32]
            raw_name  = record[33 : 33 + name_len]

            # Skip the . and .. entries and directories
            if raw_name not in (b"\x00", b"\x01") and not is_directory_flag and (file_lba not in dir_lbas):
                fname = raw_name.decode("ascii", errors="replace").split(";")[0]
                target_path = os.path.join(paths[d["id"]], fname)

                if os.path.isdir(target_path):
                    offset += rec_len
                    continue

                sectors_needed = (file_size + DATA_SIZE - 1) // DATA_SIZE
                file_bytes = bytearray()
                for s in range(sectors_needed):
                    file_bytes.extend(read_lba(f, file_lba + s))

                with open(target_path, "wb") as out:
                    out.write(file_bytes[:file_size])
                print(f"[+] Written: {target_path} ({file_size} B)")

            offset += rec_len

print("\n[OK] Extraction finished.")