"""Several independent Windows-safe process pools, without a global 61-worker cap."""
from concurrent.futures import ProcessPoolExecutor
import ctypes
import math
import os
import threading


def cpu_info():
    count = os.cpu_count() or 1
    groups = None
    source = 'os.cpu_count'
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        active = kernel.GetActiveProcessorCount
        active.argtypes = [ctypes.c_ushort]
        active.restype = ctypes.c_ulong
        total = active(0xffff)  # ALL_PROCESSOR_GROUPS, not the environment variable.
        if total:
            count, source = int(total), 'GetActiveProcessorCount(ALL_PROCESSOR_GROUPS)'
        group_count = kernel.GetActiveProcessorGroupCount
        group_count.argtypes = []
        group_count.restype = ctypes.c_ushort
        groups = int(group_count())
    return {'logical_processors': count, 'processor_groups': groups, 'source': source}


def pool_layout(workers, pool_limit=48):
    if type(workers) is not int or workers < 1 or not 1 <= pool_limit <= 61:
        raise ValueError('workers must be positive; pool-limit must be between 1 and 61')
    groups = math.ceil(workers / pool_limit)
    base, extra = divmod(workers, groups)
    return [base + (i < extra) for i in range(groups)]


class ShardedExecutor:
    def __init__(self, max_workers, mp_context, initializer, initargs, pool_limit=48):
        self.sizes = pool_layout(max_workers, pool_limit)
        self.lock = threading.Lock()
        self.outstanding = [0] * len(self.sizes)
        self.pools = []
        try:
            for size in self.sizes:
                self.pools.append(ProcessPoolExecutor(max_workers=size, mp_context=mp_context,
                                                      initializer=initializer, initargs=initargs))
        except BaseException:
            self.shutdown(wait=True, cancel_futures=True)
            raise

    def submit(self, fn, *args):
        with self.lock:
            selected = min(range(len(self.pools)), key=lambda i: self.outstanding[i] / self.sizes[i])
            self.outstanding[selected] += 1
        try:
            future = self.pools[selected].submit(fn, *args)
        except BaseException:
            with self.lock:
                self.outstanding[selected] -= 1
            raise

        def completed(_):
            with self.lock:
                self.outstanding[selected] -= 1
        future.add_done_callback(completed)
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        for pool in self.pools:
            pool.shutdown(wait=wait, cancel_futures=cancel_futures)
