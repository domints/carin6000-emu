/*
 * Carminat Doom loader: runs from the disc in place of the installer's UI ("ui_handler"; the
 * installer "il" is the PoC's sleeping stub, so nothing touches the flash).
 *
 * Takes RAM for the image (text, data, bss, malloc arena, stack) and then as much as it can for
 * Doom's zone, in up to ZONE_REGIONS blocks: the 2 MB Extension RAM where fitted, else the VSC's
 * "Development RAM" (0x680000, 512 KB) and what is left of the system RAM (a real 0209 unit has no
 * Extension RAM). Reads the Doom image from the disc, relocates it and calls it.
 *
 * The free list also shows the video RAM (0x600500, the frame buffer lives there unallocated) and
 * the slave's shared RAM (0x9F0100) as free: a block the kernel hands out there is held until the
 * end (so that the next request gets another block) and then given back, never used. RESERVE bytes
 * are left for the system (path buffers when Doom opens the WAD, other processes).
 *
 * Built like the PoC: position independent, no writable globals, state on the stack.
 */
#include "../src/carminat.h"
#include "../src/scrlog.h"

#define DOOM_IMAGE "/cd/language_cd/d_f.csf"
#define DOOM_WAD "/cd/language_cd/e_f.csf"
#define ZONE_MAX (2048 * 1024 - 64)	/* the Extension RAM block minus the allocator's rounding */
#define ZONE_MIN (512 * 1024)		/* the least zone Doom starts with */
#define CHUNK_MIN (16 * 1024)		/* smaller free blocks are not worth a zone region */
#define CHUNK_STEP (16 * 1024)
#define RESERVE (48 * 1024)
#define HEAP_SIZE (64 * 1024)		/* newlib malloc: file buffers, the WAD directory (50 KB used) */
#define STACK_SIZE (32 * 1024)
#define STDOUT 1

void run_image(void (*entry)(struct carminat_env *), struct carminat_env *env, void *stack_top);

/* Every step goes to the console (UART A) and to the screen. */
static void log_line(struct scrlog *lg, const char *s)
{
	scrlog_puts(lg, s);
	scrlog_putc(lg, '\n');
	char line[96];
	int n = 0;
	while (s[n] && n < (int)sizeof(line) - 1) {
		line[n] = s[n];
		n++;
	}
	line[n++] = '\r';
	os9_writeln(STDOUT, line, n);
}

static char *str_cat(char *p, const char *s)
{
	while (*s)
		*p++ = *s++;
	*p = 0;
	return p;
}

static char *fmt_hex(char *p, unsigned v, int digits)
{
	for (int i = digits - 1; i >= 0; i--) {
		unsigned d = (v >> (i * 4)) & 0xf;
		*p++ = d < 10 ? '0' + d : 'A' + d - 10;
	}
	*p = 0;
	return p;
}

static char *fmt_dec(char *p, unsigned v)
{
	char tmp[10];
	int n = 0;
	do
		tmp[n++] = '0' + v % 10;
	while (v /= 10);
	while (n)
		*p++ = tmp[--n];
	*p = 0;
	return p;
}

/*
 * The free memory map (F$GBlkMp), taken before the loader allocates anything: it shows what the
 * other processes hold. Read once at the start, because F$GBlkMp hangs once the Extension RAM has no
 * free block left (seen in the emulator, with the whole 2 MB taken for the zone).
 */
struct free_map {
	unsigned map[2 * 32];
	unsigned info[3];	/* fragments, total RAM, free RAM */
	int ok;
};

static void log_free_ram(struct scrlog *lg, const struct free_map *fm)
{
	char line[80];
	if (!fm->ok)
		return;
	char *p = fmt_dec(str_cat(line, "free RAM at start "), fm->info[2] >> 10);
	str_cat(fmt_dec(str_cat(p, "K in "), fm->info[0]), " blocks:");
	log_line(lg, line);
	for (unsigned i = 0; i < fm->info[0] && i < 32; i++) {
		if (fm->map[2 * i + 1] < 0x4000)	/* only blocks of 16 KB and more */
			continue;
		p = fmt_hex(str_cat(line, "  "), fm->map[2 * i], 8);
		str_cat(fmt_dec(str_cat(p, " "), fm->map[2 * i + 1] >> 10), "K");
		log_line(lg, line);
	}
}

/* RAM that is listed as free but must not be used: video RAM and the slave's shared RAM. */
static int forbidden(unsigned addr, unsigned size)
{
	return (addr < 0x680000 && addr + size > 0x600000) || (addr < 0xa00000 && addr + size > 0x9f0000);
}

struct held {
	void *block[8];
	unsigned size[8];
	unsigned n;
};

/* F$SRqMem, skipping (and holding) blocks in the forbidden areas. Returns the size or -error. */
static int request(struct held *hd, unsigned size, void **block)
{
	for (;;) {
		int got = os9_srqmem(size, block);
		if (got < 0 || !forbidden((unsigned)*block, got))
			return got;
		if (hd->n == 8) {
			os9_srtmem(got, *block);
			return -0xed;	/* E$NoRAM */
		}
		hd->block[hd->n] = *block;
		hd->size[hd->n++] = got;
	}
}

static unsigned free_allowed(const struct free_map *fm)
{
	unsigned sum = 0;
	for (unsigned i = 0; i < fm->info[0] && i < 32; i++)
		if (!forbidden(fm->map[2 * i], fm->map[2 * i + 1]))
			sum += fm->map[2 * i + 1];
	return sum;
}

static void fail(struct scrlog *lg, const char *what, int err)
{
	char line[80];
	fmt_hex(str_cat(str_cat(str_cat(line, "doom loader: "), what), ", error "), -err, 3);
	lg->color = SCRLOG_RED;
	log_line(lg, line);
	for (;;)
		os9_sleep(0);
}

/* The frame buffer: the first "load VSR" instruction of videodr's display program. */
static unsigned find_vsr(void)
{
	for (unsigned a = VSC_DCP; a < VSC_DCP + 0x40; a += 4) {
		unsigned cmd = (VSC_DRAM[a] << 8) | VSC_DRAM[a + 1];
		unsigned data = (VSC_DRAM[a + 2] << 8) | VSC_DRAM[a + 3];
		unsigned op = cmd >> 12;
		if (op == 4 || op == 5)		/* LOAD_VSR: address bits 16-19 in the command */
			return ((cmd & 0xf) << 16) | data;
	}
	return 0x500;
}

static int read_all(int path, void *buf, unsigned size)
{
	unsigned char *p = buf;
	while (size) {
		int n = os9_read(path, p, size > 0x10000 ? 0x10000 : size);
		if (n <= 0)
			return n < 0 ? n : -0xd3;	/* E$EOF */
		p += n;
		size -= n;
	}
	return 0;
}

int main(void)
{
	char line[80];
	struct flat_header h;
	struct carminat_env env;
	struct scrlog log, *lg = &log;
	struct free_map fm;
	void *block;

	fm.ok = os9_gblkmp(fm.map, sizeof(fm.map), fm.info) == 0;

	env.fb = VSC_DRAM + find_vsr();
	scrlog_init(lg, env.fb, 0);
	lg->color = SCRLOG_YELLOW;
	log_line(lg, "");
	log_line(lg, "*** Carminat Doom loader ***");
	lg->color = SCRLOG_TEXT;
	fmt_hex(str_cat(line, "frame buffer at DRAM "), (unsigned)(env.fb - VSC_DRAM), 5);
	log_line(lg, line);

	log_line(lg, "opening " DOOM_IMAGE);
	int path = os9_open(DOOM_IMAGE, 1);
	if (path < 0)
		fail(lg, "cannot open " DOOM_IMAGE, path);
	int err = read_all(path, &h, sizeof(h));
	if (err < 0 || h.magic != FLAT_MAGIC)
		fail(lg, "bad image header", err ? err : -1);

	env.nav = os9_open("/nav_bus", 3);
	if (env.nav < 0)
		fail(lg, "cannot open /nav_bus", env.nav);

	/* The image block first: it is the biggest single piece, and only the system RAM has room. */
	struct held hd;
	hd.n = 0;
	unsigned need = h.image_size + h.bss_size + HEAP_SIZE + STACK_SIZE;
	int got = request(&hd, need, &block);
	if (got < 0) {
		log_free_ram(lg, &fm);
		fail(lg, "no RAM for the image", got);
	}
	unsigned char *base = block;
	fmt_hex(str_cat(fmt_hex(str_cat(line, "image at "), (unsigned)base, 8), " size "), need, 6);
	log_line(lg, line);

	/* Then the zone, the biggest blocks first, until all but RESERVE of the free RAM is taken. */
	unsigned budget = free_allowed(&fm);
	budget = budget > need + RESERVE ? budget - need - RESERVE : 0;
	unsigned zone = 0, size = budget < ZONE_MAX ? budget : ZONE_MAX;
	env.zone_count = 0;
	while (size >= CHUNK_MIN && env.zone_count < ZONE_REGIONS) {
		got = request(&hd, size, &block);
		if (got < 0) {
			size = (size - 1) & ~(CHUNK_STEP - 1);
			continue;
		}
		env.zone[env.zone_count].base = block;
		env.zone[env.zone_count++].size = got;
		zone += got;
		fmt_hex(str_cat(fmt_hex(str_cat(line, "zone "), got, 6), " bytes at "), (unsigned)block, 8);
		log_line(lg, line);
		budget = budget > (unsigned)got ? budget - got : 0;
		if (size > budget)
			size = budget;
	}
	/* Fast system RAM first: Doom fills the zone from the start, and what it loads first (the static
	 * data, the level) is read every frame. The VSC DRAM waits for the display. */
	for (unsigned i = 1; i < env.zone_count; i++)
		for (unsigned j = i; j > 0 && (unsigned)env.zone[j - 1].base < 0x700000 &&
				     (unsigned)env.zone[j].base >= 0x700000; j--) {
			unsigned char *b = env.zone[j].base;
			unsigned sz = env.zone[j].size;
			env.zone[j] = env.zone[j - 1];
			env.zone[j - 1].base = b;
			env.zone[j - 1].size = sz;
		}
	while (hd.n) {
		hd.n--;
		os9_srtmem(hd.size[hd.n], hd.block[hd.n]);
	}
	if (zone < ZONE_MIN || env.zone_count > 1)
		log_free_ram(lg, &fm);
	if (zone < ZONE_MIN)
		fail(lg, "not enough RAM for the zone", -0xed);

	log_line(lg, "reading the image");
	err = read_all(path, base, h.image_size);
	if (err < 0)
		fail(lg, "reading the image", err);
	fmt_hex(str_cat(line, "relocating, count "), h.reloc_count, 5);
	log_line(lg, line);
	/* Relocations, a chunk at a time (they can be a few hundred KB). */
	unsigned chunk[256];
	unsigned left = h.reloc_count;
	while (left) {
		unsigned n = left > 256 ? 256 : left;
		err = read_all(path, chunk, n * 4);
		if (err < 0)
			fail(lg, "reading relocations", err);
		for (unsigned i = 0; i < n; i++) {
			unsigned *word = (unsigned *)(base + chunk[i]);
			*word += (unsigned)base;
		}
		left -= n;
	}
	os9_close(path);
	for (unsigned i = 0; i < h.bss_size; i++)
		base[h.image_size + i] = 0;

	env.heap = base + h.image_size + h.bss_size;
	env.heap_end = env.heap + HEAP_SIZE;
	env.stack_top = base + need;
	for (unsigned char *p = env.heap_end; p < env.stack_top; p++)
		*p = STACK_FILL;
	env.wad = DOOM_WAD;

	log_line(lg, "starting doom");
	env.log = lg;	/* stays valid: Doom runs on its own stack */
	run_image((void (*)(struct carminat_env *))(base + h.entry), &env, env.stack_top);
	return 0;
}
