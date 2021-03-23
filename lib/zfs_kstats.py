from .abstract_pre_post_measurement import AbstractPandasSeriesMeasurement, test_impl_with_inputs
from pathlib import Path

class KstatPandasSeriesMeasurement(AbstractPandasSeriesMeasurement):

    def __init__(self, name, kstat_path, separator):
        super().__init__(name)
        self.kstat_path = kstat_path
        self.separator = separator

    def _get_output(self):
        return self.kstat_path.read_text()

    def _parse_dict(self, output):
        lines = output.splitlines()
        if not len(lines) == 2:
            raise Exception(f"unexpected number of lines ({len(lines)} from {kstat_path}:\n{output}")

        def fields(line):
            return [c.strip() for c in line.split(self.separator)]

        header = fields(lines[0])
        data = fields(lines[1])
        if not len(header) == len(data):
            raise Exception(f"number of header and data colums does not match: {len(header)} != {len(data)}\nheader = {header}\ndata={data}")

        try:
            data = [int(c) for c in data]
        except e:
            raise Exception(f"error while converting data to ints: data={data}") from e

        return dict(zip(header, data))

###########################################################

class ZilItxgBypassMeasurement(KstatPandasSeriesMeasurement):
    def __init__(self):
        kstat_path = Path("/proc/spl/kstat/zfs/zil_itxg_bypass")
        super().__init__(str(kstat_path), kstat_path, separator="|")

def _test_zil_itxg_bypass_measurement():
    example = """write_upgrade | downgrade | aquisition_total | vtable | exit | total
256882787 | 4468 | 384192061 | 39687812 | 641698 | 42476661
"""
    r = test_impl_with_inputs(ZilItxgBypassMeasurement, example, example)
    assert "vtable" in r
    assert r["vtable"] == 0
_test_zil_itxg_bypass_measurement()

###########################################################

class ZvolOsLinuxMeasurement(KstatPandasSeriesMeasurement):
    def __init__(self):
        kstat_path = Path("/proc/spl/kstat/zfs/zvol_os_linux")
        super().__init__(str(kstat_path), kstat_path, separator="|")

def _test_zvol_os_linux_measurement():
    example = """submit_bio__zvol_write(with_taskq_if_enabled) | zvol_write__taskq_qdelay | zvol_write__1zil_commit | zvol_write__zvol_log_write_finish | zvol_write__2zil_commit
2703667285 | 2430813031 | 43746 | 114887960 | 126807724
"""
    r = test_impl_with_inputs(ZvolOsLinuxMeasurement, example, example)
    assert "zvol_write__2zil_commit" in r
    assert r["zvol_write__2zil_commit"] == 0
_test_zvol_os_linux_measurement()

class ZilPmemMeasurement(KstatPandasSeriesMeasurement):
    def __init__(self):
        kstat_path = Path("/proc/spl/kstat/zfs/zil_pmem")
        super().__init__(str(kstat_path), kstat_path, separator="|")

class ZilPmemRingbufMeasurement(KstatPandasSeriesMeasurement):
    def __init__(self):
        kstat_path = Path("/proc/spl/kstat/zfs/zil_pmem_ringbuf")
        super().__init__(str(kstat_path), kstat_path, separator="|")

