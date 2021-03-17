from schema import Schema, Or
import contextlib
import subprocess
from pathlib import Path
import threading
import json
import signal
import copy

ConfigSchema = Schema({
    "zfs_log_write_kind": Or("upstream", "zil-pmem"),
})

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
            ret[k] = self.d[k] = o.d[k]
        return Update(ret)

class Bpftrace:

    def __init__(self):
        self.lock = threading.Lock()
        self.update_cv = threading.Condition(lock=self.lock)
        self.last_update = None
        self.started_measuring_at = None
        self.stopped_measuring_at = None

    def start(self):
        args = [
            #"unbuffer", # https://stackoverflow.com/a/54010626/305410
            "bpftrace", "-f", "json",
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

    def start_measuring(self):
        print("call to start_measuring()")
        with self.update_cv:
            if self.started_measuring_at:
                raise Exception("can start measuring only once")
            if self.reader_thread == None:
                raise Exception("must call start() before calling this function")
            while not self.last_update:
                self.update_cv.wait()
            print("start_measuring() got update, starting measuring")
            self.started_measuring_at = self.last_update.copy()

    def stop_measuring(self):
        print("call to stop_measuring()")
        with self.update_cv:
            print("stop_measuring() got lock")
            if self.stopped_measuring_at:
                raise Exception("can stop measuring only once")
            if not self.started_measuring_at:
                raise Exception("must call start_measuring() before calling this function")
            self.stopped_measuring_at = self.last_update.copy()

        return self._measurement().d # without cv held, _measurement() locks again


    def _measurement(self):
        with self.update_cv:
            if not self.stopped_measuring_at:
                raise Exception("have not called stop_measuring() yet")
            return self.stopped_measuring_at - self.started_measuring_at

    def stop(self):
        with self.update_cv:
            if not self.stopped_measuring_at:
                raise Exception("must only stop() after calling stop_measuring()")
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
                            print(f"discarding incomplete update, missing keys: {missing}")
                        else:
                            if self.last_update:
                                self.last_update.update(current)
                            else:
                                self.last_update = Update(current)
                            self.update_cv.notify_all()

                elif ev["type"] == "map":
                    for k, v in ev["data"].items():
                        assert not k in current # bpftrace script behaves incorrectly
                        current[k] = v
                else:
                    print(f"discarding line")

        print("read_output() returning")

class BpftraceUpstream(Bpftrace):
    script = Path(__file__).parent / "zfs_write_latencyanalysis.upstream.bpftrace"
    pass

class BpftraceZilPmem(Bpftrace):
    script = Path(__file__).parent / "zfs_write_latencyanalysis.zil-pmem.bpftrace"
    update_map_values = {
        "@zfs_write",
        "@zfs_write_count",
        "@zil_commit",
        "@zfs_log_write_begin",
        "@zfs_log_write_finish",
        "@zillwb_commit_waiter__issue",
        "@zillwb_commit_waiter__timeout",
        "@pmem_submit_bio",
    }
    pass

@contextlib.contextmanager
def with_bpftrace(config):
    config = ConfigSchema.validate(config)

    bpft = {
        "upstream": BpftraceUpstream,
        "zil-pmem": BpftraceZilPmem,
    }[config['zfs_log_write_kind']]()

    bpft.start()
    try:
        yield bpft
    finally:
        bpft.stop()

