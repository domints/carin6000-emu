/*
 * newlib system calls on OS-9: files are OS-9 paths (read only, the disc), stdout/stderr go to
 * the console (UART A), malloc gets the arena the loader set aside after the image.
 */
#include <errno.h>
#include <stdio.h>
#include <fcntl.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/times.h>
#include <unistd.h>

#include "carminat.h"
#include "scrlog.h"

extern struct scrlog carminat_log;
extern int carminat_log_on;

#undef errno
extern int errno;

#define MAX_FILES 16
#define FD_BASE 3
/* Our own position per descriptor: I$Seek is absolute only, SEEK_CUR/SEEK_END need it. */
static struct {
	int path;
	unsigned pos;
} files[MAX_FILES];

static int fail(int err)
{
	errno = err;
	return -1;
}

int open(const char *name, int flags, ...)
{
	if ((flags & 3) != O_RDONLY)
		return fail(EROFS);
	for (int i = 0; i < MAX_FILES; i++) {
		if (files[i].path)
			continue;
		int path = os9_open(name, 1);
		if (path < 0)
			return fail(ENOENT);
		files[i].path = path + 1;	/* 0 marks a free slot */
		files[i].pos = 0;
		return i + FD_BASE;
	}
	return fail(EMFILE);
}

static int slot(int fd)
{
	int i = fd - FD_BASE;
	return (i >= 0 && i < MAX_FILES && files[i].path) ? i : -1;
}

int close(int fd)
{
	int i = slot(fd);
	if (i < 0)
		return fd < FD_BASE ? 0 : fail(EBADF);
	os9_close(files[i].path - 1);
	files[i].path = 0;
	return 0;
}

ssize_t read(int fd, void *buf, size_t count)
{
	int i = slot(fd);
	if (i < 0)
		return fail(EBADF);
	int n = os9_read(files[i].path - 1, buf, count);
	if (n < 0)
		return n == -0xd3 ? 0 : fail(EIO);	/* E$EOF is the end of the file */
	files[i].pos += n;
	return n;
}

/* Console output: OS-9 ends lines with CR. */
ssize_t write(int fd, const void *buf, size_t count)
{
	const char *s = buf;
	char line[128];
	size_t done = 0;
	if (fd != 1 && fd != 2)
		return fail(EBADF);
	/* On the screen too: everything until the game starts, errors (stderr) always. */
	if (carminat_log_on || fd == 2) {
		if (fd == 2)
			carminat_log.color = SCRLOG_RED;
		for (size_t i = 0; i < count; i++)
			scrlog_putc(&carminat_log, s[i]);
		carminat_log.color = SCRLOG_TEXT;
	}
	while (done < count) {
		size_t n = 0;
		while (done < count && n < sizeof(line) - 2) {
			char c = s[done++];
			if (c == '\n')
				line[n++] = '\r';	/* raw I$Write: the terminal needs CR LF */
			line[n++] = c;
		}
		os9_write(1, line, n);
	}
	return count;
}

off_t lseek(int fd, off_t offset, int whence)
{
	int i = slot(fd);
	if (i < 0)
		return fail(EBADF);
	long pos = offset;
	if (whence == SEEK_CUR)
		pos += files[i].pos;
	else if (whence == SEEK_END)
		pos += os9_size(files[i].path - 1);
	if (pos < 0 || os9_seek(files[i].path - 1, pos) < 0)
		return fail(EINVAL);
	files[i].pos = pos;
	return pos;
}

int fstat(int fd, struct stat *st)
{
	memset(st, 0, sizeof(*st));
	int i = slot(fd);
	if (i < 0) {
		st->st_mode = S_IFCHR;
		return fd < FD_BASE ? 0 : fail(EBADF);
	}
	st->st_mode = S_IFREG;
	st->st_size = os9_size(files[i].path - 1);
	return 0;
}

int stat(const char *name, struct stat *st)
{
	int fd = open(name, O_RDONLY);
	if (fd < 0)
		return -1;
	fstat(fd, st);
	close(fd);
	return 0;
}

int isatty(int fd)
{
	return fd < FD_BASE;
}

static unsigned char *brk;

/* Bytes of the malloc arena handed out so far (malloc never gives memory back to sbrk). */
unsigned carminat_heap_used(void)
{
	return brk ? (unsigned)(brk - carminat_env->heap) : 0;
}

void *sbrk(ptrdiff_t increment)
{
	if (!brk)
		brk = carminat_env->heap;
	if (brk + increment > carminat_env->heap_end) {
		errno = ENOMEM;
		return (void *)-1;
	}
	unsigned char *old = brk;
	brk += increment;
	return old;
}

void _exit(int status)
{
	os9_exit(status);
}

int kill(pid_t pid, int sig)
{
	(void)pid;
	(void)sig;
	return fail(EINVAL);
}

pid_t getpid(void)
{
	return 1;
}

int gettimeofday(struct timeval *tv, void *tz)
{
	(void)tz;
	unsigned rate;
	unsigned t = os9_ticks(&rate);
	if (!rate)
		rate = 100;
	tv->tv_sec = t / rate;
	tv->tv_usec = (t % rate) * (1000000 / rate);
	return 0;
}

clock_t times(struct tms *buf)
{
	unsigned rate;
	unsigned t = os9_ticks(&rate);
	memset(buf, 0, sizeof(*buf));
	return t;
}

int unlink(const char *name)
{
	(void)name;
	return fail(EROFS);
}

int link(const char *a, const char *b)
{
	(void)a;
	(void)b;
	return fail(EROFS);
}

int mkdir(const char *name, mode_t mode)
{
	(void)name;
	(void)mode;
	return fail(EROFS);
}

int rename(const char *a, const char *b)
{
	(void)a;
	(void)b;
	return fail(EROFS);
}

int _system(const char *command)
{
	(void)command;
	return fail(ENOSYS);
}
