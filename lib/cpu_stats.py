import contextlib
import psutil
import pandas as pd
import threading

PSUTIL_KEYS = [
    'user',
    'nice',
    'system',
    'idle',
    'iowait',
    'irq',
    'softirq',
    'steal',
    'guest',
    'guest_nice',
]

CPU_NUMBER_KEY = "cpu_number"

assert CPU_NUMBER_KEY not in PSUTIL_KEYS # otherwise we'd overwrite the key in sample_percpu()

def cpu_time_to_dict(ct):
    d = ct._asdict() # psutil uses namedtuple
    d_keys = set(d.keys())
    expect_keys = set(PSUTIL_KEYS)
    if not d_keys == expect_keys:
        raise Exception(f"psutil.cpu_times misses expected keys {expected_keys - d_keys}")
    return d

class CPUTimeMeasurement:

    def sample_allcpu(self):
        allcpu = psutil.cpu_times(percpu=False)
        allcpu = cpu_time_to_dict(allcpu)
        return pd.Series(allcpu)

    def sample_percpu(self):
        percpu = psutil.cpu_times(percpu=True)
        percpu = [{ CPU_NUMBER_KEY: ncpu,  **cpu_time_to_dict(d)} for ncpu, d in enumerate(percpu)]
        return pd.DataFrame(percpu)

    def __init__(self):
        self.mtx = threading.Lock()
        self._allcpu = None
        self._percpu = None
        self._end_allcpu = None
        self._end_percpu = None

    def start(self):
        with self.mtx:
            print("starting CPU time measurement")
            self._allcpu = self.sample_allcpu()
            self._percpu = self.sample_percpu()

    def until_now(self):
        with self.mtx:
            allcpu = self.sample_allcpu() - self._allcpu
            percpu = self.sample_percpu() - self._percpu
            return (allcpu, percpu)

    def stop(self):
        allcpu = self.sample_allcpu()
        percpu = self.sample_percpu()
        with self.mtx:
            print("stopping CPU time measurement")
            assert self._allcpu is not None
            assert self._percpu is not None
            assert self._end_allcpu is None
            assert self._end_percpu is None
            self._end_allcpu = allcpu
            self._end_percpu = percpu

    def allcpu(self):
        with self.mtx:
            assert self._allcpu is not None
            assert self._percpu is not None
            assert self._end_allcpu is not None
            assert self._end_percpu is not None
            return self._end_allcpu - self._allcpu
    def percpu(self):
        with self.mtx:
            assert self._allcpu is not None
            assert self._percpu is not None
            assert self._end_allcpu is not None
            assert self._end_percpu is not None
            return self._end_percpu - self._percpu

@contextlib.contextmanager
def with_cpu_utilization_measurement():
    yield CPUTimeMeasurement()
