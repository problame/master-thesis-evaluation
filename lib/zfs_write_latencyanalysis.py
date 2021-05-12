from schema import Schema, Or
import contextlib
import subprocess
from pathlib import Path
import threading
import json
import signal
import copy
from lib.helpers import merge_dicts

def keysets(a: dict, b:dict):
    return (set(a.keys()), set(b.keys()))

class Update:
    def __init__(self, d):
        self.d = d

    def _check_keys_match(self, o: dict):
        sk, ok = keysets(self.d, o)
        if not sk == ok:
            raise Exception(f"keys do not match:\nhave: {sk}\no: {ok}")
    def update(self, o: dict):
        if self.d:
            self._check_keys_match(o)
        self.d = o

    def copy(self):
        return Update(copy.deepcopy(self.d))

    def __sub__(self, o):
        self._check_keys_match(o.d)
        ret = {}
        for k in self.d.keys():
            ret[k] = self.d[k] - o.d[k]
        return Update(ret)

class Bpftrace:
    """FioAnalyzer-compatible abstraction for a bpftrace script that periodically emits metrics"""

    def __init__(self):
        self.lock = threading.Lock()
        self.update_cv = threading.Condition(lock=self.lock)
        self.last_update = None
        self.started_measuring_at = None
        self.stopped_measuring_at = None

    def setup(self):
        builddir=Path("/root/zil-pmem/zil-pmem")
        args = [
            #"unbuffer", # https://stackoverflow.com/a/54010626/305410
            "bpftrace", "-f", "json",
             "-I", "/lib/modules/5.9.0-0.bpo.5-amd64/source/include", # FIXME
             "--include", builddir / "zfs_config.h",
             "-I",  builddir / Path("include/spl"),
             "-I", builddir / Path("include"),
             "-I", builddir / Path("include/os/linux/spl"),
             "-I", builddir / Path("include/os/linux/zfs"),
             "-I", builddir / Path("include/os/linux/kernel"),
            self.script
        ]
        print(f"running bpftrace command: {args}")
        self.process = subprocess.Popen(
            args,
            text=True,
            bufsize=1, # so that readlines() works
            stdout=subprocess.PIPE)

        self.reader_thread = threading.Thread(target=self.read_output)
        try:
            self.reader_thread.start()
        except:
            self.process.kill()
            self.process.wait()
            raise

    def start(self):
        print("call to start()")
        with self.update_cv:
            if self.started_measuring_at:
                raise Exception("can start measuring only once")
            if self.reader_thread == None:
                raise Exception("must call start() before calling this function")
            while not self.last_update:
                self.update_cv.wait()
            print("start() got update, starting measuring")
            self.started_measuring_at = self.last_update.copy()

    def end(self):
        print("call to end()")
        with self.update_cv:
            print("end() got lock")
            if self.stopped_measuring_at:
                raise Exception("can stop measuring only once")
            if not self.started_measuring_at:
                raise Exception("must call start() before calling this function")
            self.stopped_measuring_at = self.last_update.copy()

        return self._measurement().d # without cv held, _measurement() locks again


    def _measurement(self):
        with self.update_cv:
            if not self.stopped_measuring_at:
                raise Exception("have not called end() yet")
            return self.stopped_measuring_at - self.started_measuring_at

    def result(self):
        return self._measurement().d

    def teardown(self):
        with self.update_cv:
            if self.started_measuring_at and not self.stopped_measuring_at:
                raise Exception("must only stop() after calling end()")
        self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired as e:
            print("bpftrace did not respond to SIGINT, killing it")
            self.process.kill()
            self.process.wait(timeout=2)

        print("waiting for reader thread")
        self.reader_thread.join(timeout=2)

    def read_output(self):
        UpdateSchema = Schema({
            "type": "printf",
            "data": Or("update", "update_done"),
        })
        MapSchema = Schema({
            "type": "map",
            "data": { str: int },
        })
        EventSchema = Or(UpdateSchema, MapSchema, {str: object})
        current = None
        for line in self.process.stdout:
            print(f"bpftrace line: {line!r}")
            with self.update_cv:
                if self.stopped_measuring_at:
                    print("dropping line, we are post stop_measurement()")
                    continue # crazy things happen after SIGINT, just drop all the output

            try:
                ev = json.loads(line)
                ev = EventSchema.validate(ev)
            except Exception as e:
                print(f"exception while parsing bpftrace script output: {e}\nline: {line!r}")
                raise

            with self.update_cv:
                if ev["type"] == "printf":
                    if ev["data"] == "update_begin":
                        current = {}
                    else:
                        assert ev["data"] == "update_end"
                        curkeys = set(current.keys())
                        if curkeys != self.update_map_values:
                            missing = self.update_map_values - curkeys
                            print(f"discarding incomplete update, missing keys: {missing!r}")
                        else:
                            if self.last_update:
                                self.last_update.update(current)
                            else:
                                self.last_update = Update(current)
                            self.update_cv.notify_all()

                elif ev["type"] in [ "map", "stats" ]:
                    for k, v in ev["data"].items():
                        assert not k in current # bpftrace script behaves incorrectly
                        current[k] = v
                else:
                    print(f"discarding line")

        print("read_output() returning")

class BpftraceZilLwbLatencyBreakdownInZilPmemTree(Bpftrace):
    script = Path(__file__).parent / "zfs_write_latencyanalysis.zil_lwb_detailed.zil-pmem.bpftrace"
    update_map_values = {
        "@zfs_write",
        "@zfs_write_count",
        "@zil_commit",
        "@zfs_log_write",
        "@zil_fill_commit_list",
        "@zillwb_commit_waiter__issue_cv",
        "@zillwb_commit_waiter__timeout_cv",
        "@zillwb_lwb_write_issue",
    }


class BpftraceZilLwbLwbWriteLatencyInZilPmemTree(Bpftrace):
    script = Path(__file__).parent / "zfs_write_latencyanalysis.zil_lwb_lwb_write_latency.zil-pmem.bpftrace"
    update_map_values = {
        "@zfs_write_count",
        "@last_lwb_latency",
        "@lwb_issue_count",
        "@pmem_submit_bio",
    }

class BpftraceComparisonZilLwbZilPmemInZilPmemTree(Bpftrace):
    script = Path(__file__).parent / "zfs_write_latencyanalysis.comparison_zil_lwb_vs_zil_pmem.zil-pmem.bpftrace"
    update_map_values = {
        "@zfs_write",
        "@zfs_write_count",
        "@zil_fill_commit_list",
        "@zil_commit",
        "@zfs_log_write",
    }

