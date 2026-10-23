/*
 * doomgeneric backend for the CARiN / Carminat (68EC030, OS-9, SCC66470 384x240 RRRGGGBB).
 *
 * Video: DG_ScreenBuffer is the frame buffer itself (DOOMGENERIC_RESX/Y = 384x240), so
 * I_FinishUpdate copies Doom's 320x200 straight to the screen, centred.
 * Colour: the screen is RRRGGGBB, not a palette. carminat_pal2dev maps Doom's palette indexes to
 * it; the colormaps (walls, flats, sprites) get it folded in once per palette change, the patch
 * drawers (status bar, menus, HUD) and the automap look it up (engine patches marked CARMINAT).
 * Input: the panel only reports presses, so movement is latched (press: go, press again: stop).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "carminat.h"
#include "scrlog.h"
#include "d_event.h"
#include "doomgeneric.h"
#include "doomkeys.h"
#include "doomtype.h"
#include "z_zone.h"

struct carminat_env *carminat_env;
/* The start is logged on the screen (no serial cable needed) until the player presses a button. */
struct scrlog carminat_log;
int carminat_log_on;

extern boolean menuactive;
extern int key_nextweapon;
extern int joybspeed;
extern int usemouse;
extern int screenblocks;
extern int detailLevel;

unsigned char carminat_pal2dev[256];
static unsigned char *colormaps_doom;	/* COLORMAP as in the WAD */
static unsigned char *colormaps_live;	/* the engine's copy, in screen colours */
static int colormaps_size;
static unsigned tick_rate = 100;

/* ---------------------------------------------------------------------------------------- */
/* colour */

static unsigned char rgb332(unsigned r, unsigned g, unsigned b)
{
	r = (r * 7 + 127) / 255;
	g = (g * 7 + 127) / 255;
	b = (b * 3 + 127) / 255;
	return (r << 5) | (g << 2) | b;
}

static void remap_colormaps(void)
{
	if (!colormaps_doom)
		return;
	for (int i = 0; i < colormaps_size; i++)
		colormaps_live[i] = carminat_pal2dev[colormaps_doom[i]];
}

/* r_data.c, after COLORMAP is loaded (CARMINAT patch). */
void carminat_colormaps_loaded(unsigned char *colormaps, int size)
{
	colormaps_live = colormaps;
	colormaps_size = size;
	colormaps_doom = malloc(size);
	memcpy(colormaps_doom, colormaps, size);
	remap_colormaps();
}

/* i_video.c I_SetPalette (CARMINAT patch): 768 bytes, gamma already applied. */
void carminat_set_palette(const unsigned char *rgb)
{
	for (int i = 0; i < 256; i++, rgb += 3)
		carminat_pal2dev[i] = rgb332(rgb[0], rgb[1], rgb[2]);
	remap_colormaps();
}

/* ---------------------------------------------------------------------------------------- */
/* input */

#define KEY_QUEUE 32
static struct {
	int pressed;
	unsigned char key;
} queue[KEY_QUEUE];
static int q_head, q_tail;
/* Keys to release later: a tap is down now, up a frame later. */
static unsigned char tap_keys[8];
static int taps;
static int latch_forward, latch_back, latch_strafe;

static void push_key(int pressed, unsigned char key)
{
	int next = (q_head + 1) % KEY_QUEUE;
	if (next == q_tail)
		return;
	queue[q_head].pressed = pressed;
	queue[q_head].key = key;
	q_head = next;
}

static void tap(unsigned char key)
{
	push_key(1, key);
	if (taps < (int)sizeof(tap_keys))
		tap_keys[taps++] = key;
}

static void latch(int *state, unsigned char key)
{
	*state = !*state;
	push_key(*state, key);
}

/* Knob steps turn (or strafe, with the strafe latch on) through the mouse path of G_Responder:
 * one step is MOUSE_STEP mouse units, about 4 degrees. */
#define MOUSE_STEP 91

static void knob(int steps)
{
	if (menuactive) {
		while (steps > 0) {
			tap(KEY_DOWNARROW);
			steps--;
		}
		while (steps < 0) {
			tap(KEY_UPARROW);
			steps++;
		}
		return;
	}
	event_t ev = { .type = ev_mouse, .data2 = steps * MOUSE_STEP };
	D_PostEvent(&ev);
}

/* Panel keys (nav_bus 3A 3B 48 code). */
static void panel_key(int code)
{
	switch (code) {
	case 2:		/* VOL+: forward on/off */
		if (menuactive)
			tap(KEY_UPARROW);
		else {
			if (latch_back)
				latch(&latch_back, KEY_DOWNARROW);
			latch(&latch_forward, KEY_UPARROW);
		}
		break;
	case 3:		/* VOL-: backward on/off */
		if (menuactive)
			tap(KEY_DOWNARROW);
		else {
			if (latch_forward)
				latch(&latch_forward, KEY_UPARROW);
			latch(&latch_back, KEY_DOWNARROW);
		}
		break;
	case 4:		/* knob push: fire, or select in the menu */
		tap(menuactive ? KEY_ENTER : KEY_FIRE);
		break;
	case 1:		/* Last message: use (doors, switches, respawn) */
		tap(KEY_USE);
		break;
	case 9:		/* Address book: next weapon */
		tap('n');
		break;
	case 0:		/* Mute nav: strafe on/off (the knob then moves sideways) */
		latch(&latch_strafe, KEY_RALT);
		break;
	case 8:		/* Stand by: menu */
		tap(KEY_ESCAPE);
		break;
	default:
		break;
	}
}

static void poll_nav(void)
{
	unsigned char f[0x26];
	while (os9_ready(carminat_env->nav) > 0) {
		int n = os9_read(carminat_env->nav, f, sizeof(f) - 1);
		if (n < 4 || f[0] != 0x3a || f[1] != 0x3b)
			continue;
		if (f[2] == 0x48)
			panel_key(f[3] & 0x3f);
		else if (f[2] == 0x49)
			knob((f[3] & 0x40) ? -(f[3] & 0x3f) : (f[3] & 0x3f));
	}
}

/* ---------------------------------------------------------------------------------------- */
/* doomgeneric */

void DG_Init(void)
{
	DG_ScreenBuffer = (pixel_t *)carminat_env->fb;
	key_nextweapon = 'n';
	joybspeed = 29;		/* >= MAX_JOY_BUTTONS: always run */
	usemouse = 1;
	/* Speed: low detail (half the columns) and a smaller view; the menu can change both. */
	detailLevel = 1;
	screenblocks = 8;
	unsigned rate;
	os9_ticks(&rate);
	if (rate)
		tick_rate = rate;
}

/* Frame rate on the console every FPS_FRAMES frames. */
#define FPS_FRAMES 8

void DG_DrawFrame(void)
{
	static unsigned frames, since;
	if (++frames == FPS_FRAMES) {
		unsigned now = DG_GetTicksMs();
		if (since)
			printf("fps %u.%u (%u ms/frame)\n", FPS_FRAMES * 10000 / (now - since) / 10,
			       FPS_FRAMES * 10000 / (now - since) % 10, (now - since) / FPS_FRAMES);
		since = now;
		frames = 0;
	}
	/* RAM use on the console every 30 s of play: the peaks of the zone, heap and stack. */
	static unsigned mem_since;
	unsigned t = DG_GetTicksMs();
	if (t - mem_since >= 30000) {
		if (mem_since)
			carminat_log_memory("in game");
		mem_since = t;
	}
	/* Release last frame's taps, then read the panel. */
	while (taps)
		push_key(0, tap_keys[--taps]);
	poll_nav();
}

void DG_SleepMs(uint32_t ms)
{
	unsigned ticks = ms * tick_rate / 1000;
	os9_sleep(ticks ? ticks : 1);
}

uint32_t DG_GetTicksMs(void)
{
	unsigned rate;
	unsigned t = os9_ticks(&rate);
	if (!rate)
		rate = tick_rate;
	return (t / rate) * 1000 + (t % rate) * 1000 / rate;
}

int DG_GetKey(int *pressed, unsigned char *key)
{
	if (q_tail == q_head)
		return 0;
	*pressed = queue[q_tail].pressed;
	*key = queue[q_tail].key;
	q_tail = (q_tail + 1) % KEY_QUEUE;
	return 1;
}

void DG_SetWindowTitle(const char *title)
{
	(void)title;
}

/* What Doom holds of its RAM: the zone (fixed = static and level data, cache = purgeable), the
 * malloc arena and the deepest stack use so far (the loader fills the stack with STACK_FILL). */
void carminat_log_memory(const char *when)
{
	int fixed, cache, free;
	Z_Usage(&fixed, &cache, &free);
	const unsigned char *p = carminat_env->heap_end;
	while (p < carminat_env->stack_top && *p == STACK_FILL)
		p++;
	extern unsigned carminat_lump_reads, carminat_lump_bytes;
	static unsigned reads, bytes;
	printf("memory %s: zone fixed %dK cache %dK free %dK, heap %uK of %uK, stack %uK of %uK, "
	       "CD reads %u (%uK) since the last line\n", when,
	       fixed >> 10, cache >> 10, free >> 10, carminat_heap_used() >> 10,
	       (unsigned)(carminat_env->heap_end - carminat_env->heap) >> 10,
	       (unsigned)(carminat_env->stack_top - p) >> 10,
	       (unsigned)(carminat_env->stack_top - carminat_env->heap_end) >> 10,
	       carminat_lump_reads - reads, (carminat_lump_bytes - bytes) >> 10);
	reads = carminat_lump_reads;
	bytes = carminat_lump_bytes;
}

/* d_main.c D_DoomLoop, just before the game clock starts (CARMINAT patch): the level is loaded;
 * wait for any panel key or knob turn, then hand the screen to the game. */
void carminat_ready(void)
{
	unsigned char f[0x26];
	carminat_log.color = SCRLOG_GREEN;
	scrlog_puts(&carminat_log, "\nREADY - PRESS ANY BUTTON\n");
	carminat_log_memory("at start");
	printf("ready, waiting for a button\n");
	for (;;) {
		if (os9_ready(carminat_env->nav) > 0) {
			int n = os9_read(carminat_env->nav, f, sizeof(f) - 1);
			if (n >= 4 && f[0] == 0x3a && f[1] == 0x3b && (f[2] == 0x48 || f[2] == 0x49))
				break;
		}
		os9_sleep(5);
	}
	carminat_log_on = 0;
	memset((void *)carminat_env->fb, 0, FB_W * FB_H);
}

int carminat_main(void)
{
	static char *argv[] = { "doom", "-iwad", NULL, "-nosound", "-nomusic", "-skill", "3", "-warp", "1", "1", NULL };
	argv[2] = (char *)carminat_env->wad;
	carminat_log = *carminat_env->log;
	carminat_log_on = 1;
	unsigned zone = 0;
	for (unsigned i = 0; i < carminat_env->zone_count; i++)
		zone += carminat_env->zone[i].size;
	printf("Carminat Doom: zone %u KB in %u blocks, heap %u KB\n", zone >> 10, carminat_env->zone_count,
	       (unsigned)(carminat_env->heap_end - carminat_env->heap) >> 10);
	doomgeneric_Create(10, argv);
	for (;;)
		doomgeneric_Tick();
}
