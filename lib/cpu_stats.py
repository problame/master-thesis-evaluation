import contextlib
import psutil
import pandas as pd
import threading
import lib.abstract_pre_post_measurement

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

class CPUTimeMeasurementAllcpu(lib.abstract_pre_post_measurement.AbstractPandasSeriesMeasurement):
    def __init__(self):
        super().__init__("CPUTimeMeasurementAllcpu")
    def _get_output(self):
        return psutil.cpu_times(percpu=False)
    def _parse_dict(self, output):
        return cpu_time_to_dict(output)

class CPUTimeMeasurementPercpu(lib.abstract_pre_post_measurement.AbstractPrePostMeasurement):
    def __init__(self):
        super().__init__("CPUTimeMeasurementPercpu")
    def _get_output(self):
        return psutil.cpu_times(percpu=True)
    def _parse_output(self, percpu):
        percpu = [{ CPU_NUMBER_KEY: ncpu,  **cpu_time_to_dict(d)} for ncpu, d in enumerate(percpu)]
        return pd.DataFrame(percpu)
    def _result_dict(self, start, end):
        delta = end - start
        return delta.to_dict(orient='records')

