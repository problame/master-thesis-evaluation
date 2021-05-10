import threading

class AbstractPrePostMeasurement:

    def __init__(self, name):
        self.mtx = threading.Lock()
        self._start = None
        self._end = None
        self._name = name

    def _get_output(self):
        raise NotImplementedError

    def _parse_output(self):
        raise NotImplementedError

    def _sample(self):
        output = self._get_output()
        return self._parse_output(output)

    def start(self):
        print(f"starting {self._name} measurement")
        s = self._sample()
        with self.mtx:
            self._start = s

    def end(self):
        print(f"ending {self._name} measurement")
        s = self._sample()
        with self.mtx:
            assert self._end is None # can only measure once
            assert self._start is not None
            self._end = s

    def result(self):
        with self.mtx:
            assert self._start is not None
            assert self._end is not None
            return self._result_dict(self._start, self._end)

import pandas as pd
class AbstractPandasSeriesMeasurement(AbstractPrePostMeasurement):
    def _parse_dict(self, output):
        raise NotImplementedError

    def _parse_output(self, output):
        d = self._parse_dict(output)
        return pd.Series(d)

    def _result_dict(self, start, end):
        return (end - start).to_dict()

def test_impl_with_inputs(Implclass, start_get_output, end_get_output):
    m = Implclass()
    m._get_output = lambda: start_get_output
    m.start()
    m._get_output = lambda: end_get_output
    m.end()
    res = m.result()
    return res

