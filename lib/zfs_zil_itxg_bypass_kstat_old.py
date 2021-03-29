from pathlib import Path
import pandas as pd
import threading

kstat_path = Path("/proc/spl/kstat/zfs/zil_itxg_bypass")
kstat_example_output = """16 0 0x01 -1 0 244296201011881 244325769660233
write_upgrade | downgrade | aquisition_total | vtable | exit | total
256882787 | 4468 | 384192061 | 39687812 | 641698 | 42476661
"""

def parse_dict(output):
    lines = output.splitlines()
    if not len(lines) == 3:
        raise Exception(f"unexpected number of lines ({len(lines)} from {kstat_path}:\n{output}")

    def fields(line):
        return [c.strip() for c in line.split("|")]

    header = fields(lines[1])
    data = fields(lines[2])
    if not len(header) == len(data):
        raise Exception(f"number of header and data colums does not match: {len(header)} != {len(data)}\nheader = {header}\ndata={data}")

    try:
        data = [int(c) for c in data]
    except e:
        raise Exception(f"error while converting data to ints: data={data}") from e

    return dict(zip(header, data))

def _test_parse_dict():
    d = parse_dict(kstat_example_output)
    assert d["vtable"] == 39687812
    assert d["total"] == 42476661

_test_parse_dict()

class Measurement:
    def __init__(self):
        self.mtx = threading.Lock()
        self._start = None
        self._end = None

    def _get_output(self):
        return kstat_path.read_text()

    def _sample(self):
        output = self._get_output()
        output_d = parse_dict(output)
        return pd.Series(output_d)

    def start(self):
        print(f"starting {kstat_path} measurement")
        s = self._sample()
        with self.mtx:
            self._start = s

    def end(self):
        print(f"ending {kstat_path} measurement")
        s = self._sample()
        with self.mtx:
            assert self._end is None # can only measure once
            assert self._start is not None
            self._end = s

    def result(self):
        with self.mtx:
            assert self._start is not None
            assert self._end is not None
            return self._end - self._start

def _test_class():
    m = Measurement()
    m._get_output = lambda: kstat_example_output
    m.start()
    m.end()
    res = m.result()
_test_class()
