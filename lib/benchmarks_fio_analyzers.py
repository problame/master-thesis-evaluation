import lib.benchmarks
import lib.zfs_kstats
import lib.cpu_stats
from contextlib import ExitStack
import threading

class AbstractSetupTeardown:
    def __init__(self, cls, args, kwargs):
        self._abstract_teardown_mtx = threading.Lock()
        self._abstract_teardown_obj = None

    def __enter__(self):
        with self._abstract_teardown_mtx:
            assert not self._abstract_teardown_obj
            self._abstract_teardown_obj = self._setup()

    def __exit__(self):
        with self._abstract_teardown_mtx:
            assert self._abstract_teardown_obj
            self._abstract_teardown_obj = None

    def _setup(self):
        raise NotImplementedError

class Dummy(AbstractSetupTeardown):

    def measurement_start(self):
        print("STARTING")
    def measurement_end(self):
        print("STOPPING")
    def result(self):
        class DummyResult:
            def to_dict(self):
                return {"some":"result"}
        return DummyResult()

def zil_pmem_only_kstats():
    return {
        "itxg_bypass_stats": lib.zfs_kstats.ZilItxgBypassMeasurement(),
        "zvol_stats": lib.zfs_kstats.ZvolOsLinuxMeasurement(),
        "zil_pmem_stats": lib.zfs_kstats.ZilPmemMeasurement(),
        "zil_pmem_ringbuf_stats": lib.zfs_kstats.ZilPmemRingbufMeasurement(),
    }

class DictBased(lib.benchmarks.FioAnalyzer):
    def __init__(self, d):
        self.d = d
        self.stop_stack = ExitStack()
    def start(self):
        with ExitStack() as stack:
            for name, an in self.d.items():
                an.start()
                stack.callback(lambda an: an.end(), an)
            self.stop_stack.push(stack.pop_all())
    def end(self):
        self.stop_stack.close()
    def result(self):
        return {name: an.result() for name, an in self.d.items()}

def cpu_time_measurements():
    return DictBased({
        "allcpu": lib.cpu_stats.CPUTimeMeasurementAllcpu(),
        "percpu": lib.cpu_stats.CPUTimeMeasurementPercpu(),
    })



