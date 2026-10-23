| OS-9/68k system calls for the loader and for Doom (C calling convention: arguments on the stack,
| result in d0). A call is "trap #0" followed by the function code; carry set means error, code in
| d1.w. Every wrapper returns the result (>= 0) or -error. d2-d7/a2-a6 are preserved.

	.text

| int os9_open(const char *name, int mode) -> path
	.globl	os9_open
os9_open:
	move.l	4(%sp),%a0
	move.l	8(%sp),%d0
	trap	#0
	.short	0x0084			| I$Open
	bcs.w	error
	ext.l	%d0
	rts

| int os9_close(int path)
	.globl	os9_close
os9_close:
	move.l	4(%sp),%d0
	trap	#0
	.short	0x008f			| I$Close
	bcs.w	error
	moveq	#0,%d0
	rts

| int os9_read(int path, void *buf, int count) -> bytes read
	.globl	os9_read
os9_read:
	move.l	4(%sp),%d0
	move.l	8(%sp),%a0
	move.l	12(%sp),%d1
	trap	#0
	.short	0x0089			| I$Read
	bcs.w	error
	move.l	%d1,%d0
	rts

| int os9_write(int path, const void *buf, int count) -> bytes written (raw, no line editing)
	.globl	os9_write
os9_write:
	move.l	4(%sp),%d0
	move.l	8(%sp),%a0
	move.l	12(%sp),%d1
	trap	#0
	.short	0x008a			| I$Write
	bcs.w	error
	move.l	%d1,%d0
	rts

| int os9_writeln(int path, const void *buf, int count) -> bytes written (up to the first CR)
	.globl	os9_writeln
os9_writeln:
	move.l	4(%sp),%d0
	move.l	8(%sp),%a0
	move.l	12(%sp),%d1
	trap	#0
	.short	0x008c			| I$WritLn
	bcs.w	error
	move.l	%d1,%d0
	rts

| int os9_seek(int path, unsigned position): absolute file position
	.globl	os9_seek
os9_seek:
	move.l	4(%sp),%d0
	move.l	8(%sp),%d1
	trap	#0
	.short	0x0088			| I$Seek
	bcs.w	error
	moveq	#0,%d0
	rts

| int os9_size(int path) -> file size (SS_Size)
	.globl	os9_size
os9_size:
	move.l	%d2,-(%sp)
	move.l	8(%sp),%d0
	moveq	#2,%d1			| SS_Size
	trap	#0
	.short	0x008d			| I$GetStt
	bcs.s	1f
	move.l	%d2,%d0
	move.l	(%sp)+,%d2
	rts
1:	move.l	(%sp)+,%d2
	bra.w	error

| int os9_ready(int path) -> bytes waiting (SS_Ready), -E_NOTRDY when none
	.globl	os9_ready
os9_ready:
	move.l	4(%sp),%d0
	moveq	#1,%d1			| SS_Ready
	trap	#0
	.short	0x008d			| I$GetStt
	bcs.w	error
	move.l	%d1,%d0
	rts

| int os9_sleep(int ticks): 0 sleeps until a signal, 1 gives up the rest of the time slice
	.globl	os9_sleep
os9_sleep:
	move.l	4(%sp),%d0
	trap	#0
	.short	0x000a			| F$Sleep
	bcs.w	error
	moveq	#0,%d0
	rts

| int os9_srqmem(unsigned size, void **block) -> bytes granted
	.globl	os9_srqmem
os9_srqmem:
	move.l	%a2,-(%sp)
	move.l	8(%sp),%d0
	trap	#0
	.short	0x0028			| F$SRqMem
	bcs.s	1f
	move.l	12(%sp),%a0
	move.l	%a2,(%a0)
	move.l	(%sp)+,%a2
	rts
1:	move.l	(%sp)+,%a2
	bra.w	error

| int os9_srtmem(unsigned size, void *block): gives back a block from os9_srqmem
	.globl	os9_srtmem
os9_srtmem:
	move.l	%a2,-(%sp)
	move.l	8(%sp),%d0
	move.l	12(%sp),%a2
	trap	#0
	.short	0x0029			| F$SRtMem
	move.l	(%sp)+,%a2
	bcs.w	error
	moveq	#0,%d0
	rts

| int os9_gblkmp(void *map, unsigned size, unsigned *out): free memory map (address, size pairs)
| without allocating; out[0] fragments, out[1] total RAM, out[2] free RAM. Returns 0 or -error.
	.globl	os9_gblkmp
os9_gblkmp:
	movem.l	%d2-%d3,-(%sp)
	move.l	12(%sp),%a0
	move.l	16(%sp),%d1
	moveq	#0,%d0			| from address 0
	trap	#0
	.short	0x0019			| F$GBlkMp
	bcs.s	1f
	move.l	20(%sp),%a0
	move.l	%d1,(%a0)+
	move.l	%d2,(%a0)+
	move.l	%d3,(%a0)
	movem.l	(%sp)+,%d2-%d3
	moveq	#0,%d0
	rts
1:	movem.l	(%sp)+,%d2-%d3
	bra.w	error

| unsigned os9_ticks(unsigned *rate): ticks since midnight (F$Time, Julian with ticks), *rate per second
	.globl	os9_ticks
os9_ticks:
	movem.l	%d2-%d3,-(%sp)
	moveq	#3,%d0
	trap	#0
	.short	0x0015			| F$Time
	bcs.s	1f
	moveq	#0,%d1
	move.w	%d3,%d1			| current tick within the second
	swap	%d3
	and.l	#0xffff,%d3		| ticks per second
	move.l	12(%sp),%a0
	move.l	%d3,(%a0)
	mulu.l	%d3,%d0			| seconds since midnight * rate
	add.l	%d1,%d0
	movem.l	(%sp)+,%d2-%d3
	rts
1:	movem.l	(%sp)+,%d2-%d3
	bra.w	error

| void os9_exit(int status)
	.globl	os9_exit
os9_exit:
	move.l	4(%sp),%d1
	trap	#0
	.short	0x0006			| F$Exit
	bra.s	os9_exit

error:
	moveq	#0,%d0
	move.w	%d1,%d0
	neg.l	%d0
	rts
