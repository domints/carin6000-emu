/*
 * Shared between the loader (ui_handler module on the disc) and the Doom image it starts.
 */
#ifndef CARMINAT_H
#define CARMINAT_H

/* The Doom image file (tools/mkflat.py): this header, the image (text, rodata, data) linked at 0,
 * then reloc_count big-endian offsets of the 32-bit words to add the load address to. The bss
 * follows the image in memory and is cleared by the loader. */
#define FLAT_MAGIC 0x43444f4d	/* "CDOM" */
struct flat_header {
	unsigned magic;
	unsigned image_size;
	unsigned bss_size;
	unsigned entry;
	unsigned reloc_count;
};

/* What the loader hands to Doom's entry point. */
struct scrlog;

#define ZONE_REGIONS 8

struct carminat_env {
	struct {			/* the zone heap: the RAM blocks the loader could get */
		unsigned char *base;
		unsigned size;
	} zone[ZONE_REGIONS];
	unsigned zone_count;
	unsigned char *heap;		/* malloc arena after the image and bss */
	unsigned char *heap_end;	/* also the bottom of the stack */
	unsigned char *stack_top;
	volatile unsigned char *fb;	/* frame buffer, 384 x 240, RRRGGGBB */
	int nav;			/* path of /nav_bus, opened by the loader */
	const char *wad;		/* WAD path on the disc */
	struct scrlog *log;		/* the loader's on-screen log, Doom carries on with it */
};

/* SCC66470 DRAM as seen by the CPU; videodr's display program starts at DRAM 0x3ec. */
#define VSC_DRAM ((volatile unsigned char *)0x600000)
#define VSC_DCP 0x3ec
#define FB_W 384
#define FB_H 240

/* Doom side: set by crt0 from the loader's argument. */
extern struct carminat_env *carminat_env;

#define STACK_FILL 0x5a		/* the loader's fill of the stack, to measure its use */
unsigned carminat_heap_used(void);
void carminat_log_memory(const char *when);

int os9_open(const char *name, int mode);
int os9_close(int path);
int os9_read(int path, void *buf, int count);
int os9_write(int path, const void *buf, int count);
int os9_writeln(int path, const void *buf, int count);
int os9_seek(int path, unsigned position);
int os9_size(int path);
int os9_ready(int path);
int os9_sleep(int ticks);
int os9_srqmem(unsigned size, void **block);
int os9_srtmem(unsigned size, void *block);
int os9_gblkmp(void *map, unsigned size, unsigned *out);
unsigned os9_ticks(unsigned *rate);
void os9_exit(int status) __attribute__((noreturn));

#define E_NOTRDY 0xf6

#endif
