from schema import Schema, And, Optional
import subprocess
from .helpers import AttrDict, must_run, poll_wait, zero_out_first_sector, is_p2
from pathlib import Path

SECTOR_SHIFT = 9

def is_sector_multiple(size):
    return (size % (1<<SECTOR_SHIFT)) == 0

def size_to_sectors(size):
    assert is_sector_multiple(size)
    return size >> SECTOR_SHIFT

class Table:
    def to_dmsetup_table(self):
        raise NotImplementedError

class RawTable(Table):
    def __init__(self, raw):
        self.raw = raw
    def to_dmsetup_table(self):
        return self.raw

class StructuredTable(Table):
    def __init__(self, entries):
        self.entries = entries
    def to_dmsetup_table(self):
        return "\n".join([e.to_dmsetup_table_row() for e in self.entries])

class TableEntry:
    def __init__(self, **kwargs):
        self.config = AttrDict(Schema({
            "start_sector": int,
            "num_sectors": int,
            "constructor": [str],
        }).validate(kwargs))

    def to_dmsetup_table_row(self):
        return " ".join([f"{self.config.start_sector}", f"{self.config.num_sectors}", *self.config.constructor])


class AbstractTarget:
    def __init__(self, **kwargs):
        kwargs = AttrDict(Schema({
              "name": str,
          }).validate(kwargs))
        self.name = kwargs.name

    def _path(self):
        return Path("/dev/mapper") / self.name

    @property
    def path(self):
        return self._path()

    def _setup_pre_create(self):
        pass

    def setup(self):

        cmd = ["dmsetup", "status", self.name]
        st = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if st.returncode == 0 or "Device does not exist" not in st.stdout:
            raise Exception(f"{cmd} indicates that the target already exists: {st.stdout!r}")
        assert not self._path().exists()

        self._setup_pre_create()

        cmd = ["dmsetup", "create", self.name]
        table = self.table.to_dmsetup_table()
        print(f"{cmd} with table:\n{table}")
        try:
            subprocess.run(cmd, check=True, input=table, text=True)
        except subprocess.CalledProcessError as e:
            raise Exception("cannot create target, consider checking dmesg") from e

        poll_wait(0.1, self._path().exists, f"blockdev {self._path()} to appear")

    def teardown(self):
        cmd = ["dmsetup", "remove", "--retry", self.name]
        must_run(cmd)
        poll_wait(0.1, lambda: not self._path().exists(), f"blockdev {self._path()} to disappear")

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, type, value, traceback):
        self.teardown()


# https://www.kernel.org/doc/html/latest/admin-guide/device-mapper/linear.html
def simple_linear_table(config):
    config = AttrDict(Schema({
        "size": And(int, is_sector_multiple),
        "device": And(Path, Path.is_block_device),
    }).validate(config))
    return RawTable(f"0 {size_to_sectors(config.size)} linear {config.device} 0")


class Target(AbstractTarget):
    def __init__(self, **kwargs):
        kwargs = AttrDict(Schema({
            "name": str,
            "table": Table,
        }).validate(kwargs))
        self.table = kwargs.table
        super().__init__(name=kwargs.name)

# https://www.kernel.org/doc/html/latest/admin-guide/device-mapper/writecache.html
class WritecachePmem(AbstractTarget):
    def __init__(self, config):
        config = AttrDict(Schema({
            "name": str,
            "size": And(int, is_sector_multiple),
            "blocksize": And(int, is_p2),
            "origin_device": Path,
            "cache_device": Path,
            Optional("options", default={}): {
                Optional("high_watermark"): int, # percentage
                Optional("low_watermark"): int, # percentage,
                # ...
            }
        }).validate(config))

        assert "nvme0" not in str(config.origin_device)
        assert "nvme0" not in str(config.cache_device)

        num_options = 2*len(config.options) # we don't support fua / nofua which are the only options that take no arguments
        options = " ".join([f"{k} {v}" for k, v in config.options.items()])

        self.table = RawTable(f"0 {size_to_sectors(config.size)} writecache p {config.origin_device} {config.cache_device} {config.blocksize} {num_options} {options}")

        super().__init__(name=config.name)
        self.__prezero = [config.origin_device, config.cache_device]

    def _setup_pre_create(self):
        for d in self.__prezero:
            zero_out_first_sector(d)

class Stripe(AbstractTarget):
    def __init__(self, config):
        config = AttrDict(Schema({
            "name": str,
            "blockdevs": [And(Path, Path.is_block_device)],
        }).validate(config))

        self.blockdevs = config.blockdevs
        for bd in self.blockdevs:
            "nvme0" not in str(bd) # safety
        super().__init__(name=config.name)

    def _setup_pre_create(self):

        script = Path(__file__).parent / "devicemapper.dm_stripe.pl"
        try:
            st = subprocess.run([
                script,
                self.name,
                f"{128*2}", # The default from the script in the kernel docs
                *self.blockdevs,
                ], text=True, capture_output=True, check=True)
            self.table = RawTable(st.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"unable to compute dm_stripe table using the perl script from the kernel docs\nstdout:{e.stdout}\nstderr: {e.stderr}") from e


