#!/usr/bin/env python3
"""Build a SmartMedia NAND image for the opel_dvd90 driver.

  tools/opel_nand.py [--hw 0104] [--out state/opel_dvd90/nand.bin]

The image is a 64 MB SmartMedia (SSFDC) card as the RoadRunner NAND
controller sees it: 4096 blocks of 32 pages, each page 512 data bytes plus a
16-byte spare area. Block 0 holds the CIS; the other blocks carry logical
block numbers in their spare areas. On top sits a partition table and a FAT12
volume with the files lowboot looks for:

  /COMPUNIT/BOOT/CODE/LOWBOOT     second-stage target (boot_st2 loads it)
  /COMPUNIT/BOOT/DATA/BOOT.TIB    boot selection read by lowboot
  /COMPUNIT/NAV/CODE/NAVBOOT      OS-9000 bootfile of the navigation system
  /COMPUNIT/NAV/CODE/BSW2         basic software the supervisor modloads
  /COMPUNIT/NAV/CODE/PERMIS.TIB
  /COMPUNIT/NAV/CODE/usw_modules  fonts, including the one the MMI prints with
  /COMPUNIT/NAV/CODE/usw_stdprocs screen builder and the other MMI processes
  /COMPUNIT/NAV/CODE/usw_bsiprocs map and guidance processes
  /COMPUNIT/NAV/CODE/usw_tools
  /COMPUNIT/NAV/CODE/USW_LOAD.CFG catalog that maps those processes to the files
  /COMPUNIT/NAV/DATA/NAV_SSW.TIB  DIPC startup arguments read by sysgo
  /COMPUNIT/NVR3/NVRIMGA,B        NVR backing files expected by sysgo
  /COMPUNIT/DATA/COMPUNIT.TIB     I2C routing table read by dr_i2cnal
"""
import argparse
import pathlib
import struct

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIRMWARE = ROOT / "cd" / "Radio-Update-Software-10-10-2007" / "V_3" / "HVM0"

PAGE = 512
SPARE = 16
PAGES_PER_BLOCK = 32
BLOCKS = 4096
ZONE_BLOCKS = 1024
ZONE_LOGICAL = 1000
LOGICAL_BLOCKS = ZONE_LOGICAL * (BLOCKS // ZONE_BLOCKS)
SECTORS = LOGICAL_BLOCKS * PAGES_PER_BLOCK          # 128000

# Partition and FAT12 geometry. The data area starts on an erase-block
# boundary: 39 hidden + 1 reserved + 2 x 12 FAT + 32 root = 96 sectors.
HEADS, SECTORS_PER_TRACK = 8, 32
HIDDEN = 39
SECTORS_PER_CLUSTER = 32
RESERVED = 1
FAT_SECTORS = 12
ROOT_ENTRIES = 512
ROOT_SECTORS = ROOT_ENTRIES * 32 // PAGE
PART_SECTORS = SECTORS - HIDDEN
DATA_START = RESERVED + 2 * FAT_SECTORS + ROOT_SECTORS  # relative to the partition
CLUSTERS = (PART_SECTORS - DATA_START) // SECTORS_PER_CLUSTER
CLUSTER_BYTES = SECTORS_PER_CLUSTER * PAGE

CIS = bytes.fromhex("0103d901ff1802df0120")


def ecc256(data):
    """SmartMedia ECC of 256 bytes, same layout as the driver's controller model."""
    col = 0
    line_even = 0
    line_odd = 0
    for i, b in enumerate(data):
        col ^= b
        if bin(b).count("1") & 1:
            line_odd ^= i
            line_even ^= ~i & 0xff
    line = 0
    for bit in range(8):
        line |= ((line_even >> bit) & 1) << (bit * 2)
        line |= ((line_odd >> bit) & 1) << (bit * 2 + 1)

    def b(n):
        return (col >> n) & 1
    cp = 0
    cp |= (b(0) ^ b(2) ^ b(4) ^ b(6)) << 2
    cp |= (b(1) ^ b(3) ^ b(5) ^ b(7)) << 3
    cp |= (b(0) ^ b(1) ^ b(4) ^ b(5)) << 4
    cp |= (b(2) ^ b(3) ^ b(6) ^ b(7)) << 5
    cp |= (b(0) ^ b(1) ^ b(2) ^ b(3)) << 6
    cp |= (b(4) ^ b(5) ^ b(6) ^ b(7)) << 7
    return bytes([~line & 0xff, ~(line >> 8) & 0xff, (~cp & 0xff) | 0x03])


def block_address_field(logical):
    value = 0x1000 | ((logical % ZONE_LOGICAL) << 1)
    if bin(value).count("1") & 1:
        value |= 1
    return value


def spare(data, ba):
    s = bytearray(b"\xff" * SPARE)
    s[6:8] = struct.pack(">H", ba)
    s[11:13] = struct.pack(">H", ba)
    s[8:11] = ecc256(data[256:])
    s[13:16] = ecc256(data[:256])
    return bytes(s)


# ---------------------------------------------------------------------------
# FAT12 volume

class Fat12:
    def __init__(self):
        self.fat = [0] * (CLUSTERS + 2)
        self.fat[0] = 0xff8
        self.fat[1] = 0xfff
        self.next_cluster = 2
        self.clusters = {}
        self.root = []

    def alloc(self, data):
        if not data:
            return 0
        count = (len(data) + CLUSTER_BYTES - 1) // CLUSTER_BYTES
        first = self.next_cluster
        if first + count > CLUSTERS + 2:
            raise SystemExit("NAND image full")
        for i in range(count):
            c = first + i
            self.fat[c] = c + 1 if i + 1 < count else 0xfff
            self.clusters[c] = data[i * CLUSTER_BYTES:(i + 1) * CLUSTER_BYTES]
        self.next_cluster += count
        return first

    @staticmethod
    def name83(name):
        name = name.upper()
        base, dot, ext = name.partition(".")
        if not base or len(base) > 8 or len(ext) > 3 or (dot and "." in ext):
            return None
        return base.ljust(8).encode() + ext.ljust(3).encode()

    def alias83(self, name, used):
        """8.3 stand-in for a long name. The long name itself is stored in VFAT entries."""
        upper = name.upper()
        base, _, ext = upper.partition(".")
        stem = "".join(ch for ch in base if ch not in " .+,;=[]")[:6]
        tail = "".join(ch for ch in ext if ch not in " .+,;=[]")[:3]
        number = 1
        while True:
            short = f"{stem}~{number}".ljust(8).encode()[:8] + tail.ljust(3).encode()
            if short not in used:
                used.add(short)
                return short
            number += 1

    @staticmethod
    def lfn_checksum(name11):
        total = 0
        for byte in name11:
            total = (((total & 1) << 7) + (total >> 1) + byte) & 0xFF
        return total

    @staticmethod
    def lfn_entries(name, name11):
        """VFAT long-name slots, last slot first, each holding 13 UTF-16 characters."""
        chars = [ord(ch) for ch in name]
        chars.append(0)
        while len(chars) % 13:
            chars.append(0xFFFF)
        checksum = Fat12.lfn_checksum(name11)
        slots = []
        count = len(chars) // 13
        for seq in range(count, 0, -1):
            chunk = chars[(seq - 1) * 13:seq * 13]
            entry = bytearray(32)
            entry[0] = seq | (0x40 if seq == count else 0)
            for index, offset in enumerate((1, 3, 5, 7, 9)):
                struct.pack_into("<H", entry, offset, chunk[index])
            entry[11] = 0x0F
            entry[13] = checksum
            for index, offset in enumerate((14, 16, 18, 20, 22, 24)):
                struct.pack_into("<H", entry, offset, chunk[5 + index])
            struct.pack_into("<HH", entry, 28, chunk[11], chunk[12])
            slots.append(bytes(entry))
        return slots

    @staticmethod
    def entry(name83, attr, cluster, size):
        # 2007-10-10 12:00
        time = (12 << 11)
        date = ((2007 - 1980) << 9) | (10 << 5) | 10
        return struct.pack("<11sBBBHHHHHHHI", name83, attr, 0, 0, time, date, date, 0, time, date, cluster, size)

    def build_dir(self, tree, parent_cluster, self_cluster_holder):
        """tree: dict name -> bytes (file) or dict (directory). Returns entries for this level."""
        entries = []
        used = set()
        for name, node in tree.items():
            short = self.name83(name)
            if short is None:
                short = self.alias83(name, used)
                prelude = self.lfn_entries(name, short)
            else:
                if short in used:
                    raise SystemExit(f"{name}: short name already used")
                used.add(short)
                prelude = []
            if isinstance(node, dict):
                holder = [0]
                # reserve a cluster for the directory first, fill it afterwards
                cluster = self.alloc(b"\0" * CLUSTER_BYTES)
                holder[0] = cluster
                sub = [self.entry(b".          ", 0x10, cluster, 0),
                       self.entry(b"..         ", 0x10, parent_cluster, 0)]
                sub += self.build_dir(node, cluster, holder)
                blob = b"".join(sub)
                if len(blob) > CLUSTER_BYTES:
                    raise SystemExit(f"directory {name} too large")
                self.clusters[cluster] = blob.ljust(CLUSTER_BYTES, b"\0")
                entries += prelude
                entries.append(self.entry(short, 0x10, cluster, 0))
            else:
                cluster = self.alloc(node)
                entries += prelude
                entries.append(self.entry(short, 0x20, cluster, len(node)))
        return entries

    def image(self, tree):
        self.root = self.build_dir(tree, 0, [0])
        if len(self.root) > ROOT_ENTRIES:
            raise SystemExit("root directory full")

        boot = bytearray(PAGE)
        boot[0:3] = b"\xe9\x00\x00"
        boot[3:11] = b"OPELNAVI"
        struct.pack_into("<HBHBHHBHHHI", boot, 11,
                         PAGE, SECTORS_PER_CLUSTER, RESERVED, 2, ROOT_ENTRIES,
                         0, 0xf8, FAT_SECTORS, SECTORS_PER_TRACK, HEADS, HIDDEN)
        struct.pack_into("<I", boot, 32, PART_SECTORS)
        boot[36] = 0x00             # drive number
        boot[38] = 0x29             # extended boot signature
        struct.pack_into("<I", boot, 39, 0x20071010)
        boot[43:54] = b"NO NAME    "
        boot[54:62] = b"FAT12   "
        boot[510:512] = b"\x55\xaa"

        fat = bytearray(FAT_SECTORS * PAGE)
        for i, value in enumerate(self.fat):
            off = i * 3 // 2
            if i & 1:
                fat[off] = (fat[off] & 0x0f) | ((value << 4) & 0xf0)
                fat[off + 1] = (value >> 4) & 0xff
            else:
                fat[off] = value & 0xff
                fat[off + 1] = (fat[off + 1] & 0xf0) | ((value >> 8) & 0x0f)

        root = b"".join(self.root).ljust(ROOT_SECTORS * PAGE, b"\0")
        volume = bytearray(PART_SECTORS * PAGE)
        volume[0:PAGE] = boot
        off = RESERVED * PAGE
        volume[off:off + len(fat)] = fat
        volume[off + len(fat):off + 2 * len(fat)] = fat
        off = (RESERVED + 2 * FAT_SECTORS) * PAGE
        volume[off:off + len(root)] = root
        for cluster, data in self.clusters.items():
            off = (DATA_START + (cluster - 2) * SECTORS_PER_CLUSTER) * PAGE
            volume[off:off + len(data)] = data
        return volume


def chs(lba):
    cyl = lba // (HEADS * SECTORS_PER_TRACK)
    rem = lba % (HEADS * SECTORS_PER_TRACK)
    head = rem // SECTORS_PER_TRACK
    sector = rem % SECTORS_PER_TRACK + 1
    return bytes([head, sector | ((cyl >> 2) & 0xc0), cyl & 0xff])


def logical_disk(volume):
    disk = bytearray(SECTORS * PAGE)
    mbr = bytearray(PAGE)
    entry = bytearray(16)
    entry[0] = 0x80
    entry[1:4] = chs(HIDDEN)
    entry[4] = 0x01             # FAT12
    entry[5:8] = chs(SECTORS - 1)
    struct.pack_into("<II", entry, 8, HIDDEN, PART_SECTORS)
    mbr[446:462] = entry
    mbr[510:512] = b"\x55\xaa"
    disk[0:PAGE] = mbr
    disk[HIDDEN * PAGE:HIDDEN * PAGE + len(volume)] = volume
    return disk


def nand_image(disk):
    raw_page = PAGE + SPARE
    image = bytearray(b"\xff" * (BLOCKS * PAGES_PER_BLOCK * raw_page))

    def put(block, page, data, ba):
        off = (block * PAGES_PER_BLOCK + page) * raw_page
        image[off:off + PAGE] = data
        image[off + PAGE:off + raw_page] = spare(data, ba)

    cis_page = bytearray(b"\x00" * PAGE)
    cis_page[0:len(CIS)] = CIS
    cis_page[256:256 + len(CIS)] = CIS
    for page in range(PAGES_PER_BLOCK):
        put(0, page, bytes(cis_page) if page < 2 else b"\xff" * PAGE, 0x0000)

    for logical in range(LOGICAL_BLOCKS):
        zone, index = divmod(logical, ZONE_LOGICAL)
        physical = zone * ZONE_BLOCKS + index + (1 if zone == 0 else 0)
        base = logical * PAGES_PER_BLOCK * PAGE
        chunk = disk[base:base + PAGES_PER_BLOCK * PAGE]
        if not any(chunk):
            continue   # leave unused blocks erased; the FTL treats them as free
        ba = block_address_field(logical)
        for page in range(PAGES_PER_BLOCK):
            put(physical, page, bytes(chunk[page * PAGE:(page + 1) * PAGE]), ba)
    return image


def boot_tib():
    text = "\n".join([
        "TIB_v1",
        "Version=v1",
        "",
        "[LowBoot]",
        "ApplSelected=nav",
        "ApplSelectedPrev=nav",
        "NavApplFile=/compunit/nav/code/navboot",
        "SwlApplFile=/cd/V_3/HVM0/0104/EHU4C/loader.ini",
        "TestApplFile=/compunit/test/code/testboot",
        "EjectEnabled=0",
        "NoTbxBootConsoleT1=0",
        "DownloadAreaActive=0",
        "",
    ])
    return text.replace("\n", "\r\n").encode()


def compunit_tib():
    """Component-unit descriptor read by dr_i2cnal.

    permis.tib shows the text convention: LF line endings, a TIB_v1 header,
    then [section] and key=value lines.  i2cnal rejects a count of zero.  Each
    I2CAR_EntryN value is "<id>,<address>", with id in 1..127.
    """
    return (
        "TIB_v1\n"
        "Version=v1\n"
        "\n"
        "[I2CAR_Table]\n"
        "I2CAR_TableCount=1\n"
        "I2CAR_Entry1=1,16\n"
    ).encode()


def nav_ssw_tib():
    """Navigation system-software parameters read by sysgo.

    sysgo looks up [DipcRuntime] StartupParams in nav_ssw.tib and passes the
    comma-separated value as the argument vector of the ssp_dipc runtime.
    The runtime prints its usage and exits unless it gets at least one option,
    and the DIPC servers then fail to open the pipe it would have created.
    -n keeps it running without waiting for a network connection.

    ShellExecEnabled and DevelopmentMode are left unset. A set ShellExecEnabled
    makes sysgo take the development path, and that path jumps over the fork of
    mmi_root. With the keys absent the lookup returns 0 and sysgo forks the MMI.
    """
    return (
        "TIB_v1\n"
        "Version=v1\n"
        "\n"
        "[DipcRuntime]\n"
        "StartupParams=-n\n"
    ).encode()


def nvr_image():
    """Partitioned FAT volume used as an NVR container.

    fm_sm reads the MBR, takes the first partition LBA, then requires a boot
    sector with a 55 AA signature, 512-byte sectors, two FATs, a non-zero root
    directory and a FAT of 1..127 sectors.
    """
    # config_tool writes a 2928-byte file here. At one sector per cluster the
    # old 8-sector partition had four data clusters, three of them free, so the
    # allocation search wrapped forever instead of returning disk-full.
    sectors = CLUSTER_BYTES // PAGE - 1
    image = bytearray(CLUSTER_BYTES)
    entry = bytearray(16)
    entry[0] = 0x80
    entry[4] = 0x01
    struct.pack_into("<II", entry, 8, 1, sectors)
    image[446:462] = entry
    image[510:512] = b"\x55\xaa"

    boot = bytearray(PAGE)
    boot[0:3] = b"\xeb\x3c\x90"
    boot[3:11] = b"NVRIMG  "
    struct.pack_into("<HBHBHHBHHH", boot, 11, PAGE, 1, 1, 2, 16, sectors, 0xf8, 1, 1, 1)
    boot[510:512] = b"\x55\xaa"
    image[PAGE:PAGE * 2] = boot
    fat = bytearray(PAGE)
    fat[0:3] = b"\xf8\xff\xff"
    # Cluster 2 holds /nvr/startup. After the banner, sysgo feeds this file to
    # a shell and waits for that shell to exit. The shell only exits on the
    # logout command, so the script is just that.
    startup = b"logout\n"
    fat[3] = 0xff
    fat[4] = 0x0f
    image[PAGE * 2:PAGE * 3] = fat
    image[PAGE * 3:PAGE * 4] = fat
    name = b"STARTUP    "
    # 2007-10-10 12:00, same stamp as the main volume
    image[PAGE * 4:PAGE * 4 + 32] = struct.pack(
        "<11sBBBHHHHHHHI", name, 0x20, 0, 0, 12 << 11, ((2007 - 1980) << 9) | (10 << 5) | 10,
        ((2007 - 1980) << 9) | (10 << 5) | 10, 0, 12 << 11, ((2007 - 1980) << 9) | (10 << 5) | 10, 2, len(startup))
    image[PAGE * 5:PAGE * 5 + len(startup)] = startup
    return bytes(image)


def os9_module(blob, name):
    """Return one OS-9000 module, located by the name in its header."""
    want = name.encode() + b"\x00"
    offset = 0
    while True:
        start = blob.find(b"\x4d\xad", offset)
        if start < 0:
            raise SystemExit(f"{name}: module not found")
        name_at = int.from_bytes(blob[start + 0x0C:start + 0x10], "big")
        size = int.from_bytes(blob[start + 4:start + 8], "big")
        if 0 < name_at < 0x400 and 0 < size <= len(blob) - start and blob[start + name_at:start + name_at + len(want)] == want:
            return blob[start:start + size]
        offset = start + 2


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hw", default="0104", help="HVM0 hardware directory (default 0104, NAV-DVD production)")
    parser.add_argument("--out", default=str(ROOT / "state" / "opel_dvd90" / "nand.bin"))
    args = parser.parse_args()

    src = FIRMWARE / args.hw / "EHU4C"
    app = src / "app_sw"
    navboot = (app / "navboot").read_bytes()
    # mmi_root opens this catalog by its bare name, so it has to sit in whichever
    # directory ends up being current. The long names are the paths the catalog lists.
    load_cfg = os9_module(navboot, "usw_load.cfg")
    tree = {
        "USW_LOAD.CFG": load_cfg,
        "COMPUNIT": {
            "USW_LOAD.CFG": load_cfg,
            "BOOT": {
                "CODE": {"LOWBOOT": (src / "lowboot").read_bytes()},
                "DATA": {"BOOT.TIB": boot_tib()},
            },
            "NAV": {
                "USW_LOAD.CFG": load_cfg,
                "CODE": {
                    "NAVBOOT": navboot,
                    "BSW2": (app / "bsw2").read_bytes(),
                    "PERMIS.TIB": (app / "permis.tib").read_bytes(),
                    "USW_LOAD.CFG": load_cfg,
                    "usw_modules": (app / "usw_modules").read_bytes(),
                    "usw_stdprocs": (app / "usw_stdprocs").read_bytes(),
                    "usw_bsiprocs": (app / "usw_bsiprocs").read_bytes(),
                    "usw_tools": (app / "usw_tools").read_bytes(),
                },
                "DATA": {
                    "NAV_SSW.TIB": nav_ssw_tib(),
                    "USW_LOAD.CFG": load_cfg,
                },
            },
            "NVR3": {
                "NVRIMGA": nvr_image(),
                "NVRIMGB": nvr_image(),
            },
            "DATA": {"COMPUNIT.TIB": compunit_tib()},
        },
    }
    volume = Fat12().image(tree)
    image = nand_image(logical_disk(volume))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(image)
    print(f"{out}: {len(image)} bytes, FAT12 {CLUSTERS} clusters of {CLUSTER_BYTES} bytes")


if __name__ == "__main__":
    main()
