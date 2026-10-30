"""Parallel map over worker processes for the encoder. The workers are forked, so they see the
parent's data as it was at the call (nothing is pickled but the indexes and the results); a job
must not leave results in shared objects that the parent needs later.
"""
import gc
import multiprocessing
import os

WORKERS = int(os.environ.get("NAVDB_WORKERS") or min(os.cpu_count() or 1, 16))
_JOB = None


def _run(i):
    func, items = _JOB
    return func(items[i])


def pmap(func, items, min_items=32):
    """func(item) for every item, in order, as a generator."""
    global _JOB
    items = list(items)
    _JOB = (func, items)
    try:
        if WORKERS <= 1 or len(items) < min_items:
            yield from map(_run, range(len(items)))
            return
        gc.collect()
        gc.freeze()             # gc in the workers does not touch (copy) the parent's objects
        try:
            with multiprocessing.get_context("fork").Pool(WORKERS) as pool:
                chunk = max(1, min(64, len(items) // (WORKERS * 4)))
                yield from pool.imap(_run, range(len(items)), chunksize=chunk)
        finally:
            gc.unfreeze()
    finally:
        _JOB = None             # the job's data is not kept alive
