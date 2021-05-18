from pathlib import Path
import lib.zfssetup
import lib.devicemapper
import contextlib
from .helpers import must_run, poll_wait, deep_copy_dict
import subprocess
from schema import Schema

class ZFS:
    def __init__(self, store, identity):
        self.store = store
        self.identity = identity
        self.open_setup = None
        self._filesystem_properties = {
            "recordsize": "4k",
            "compression": "off",
            "sync": "standard",
        }

    def is_dax_bdev(self):
        return False

    def __enter__(self):
        config = self._make_config()
        assert self.blockdev_path is None
        assert self.open_setup is None
        self.open_setup = lib.zfssetup.setup_openzfs(config)
        self.open_setup.__enter__()
        return self

    def __exit__(self, type, val, bt):
        self.open_setup.__exit__(type, val, bt)
        self.open_setup = None

    def _set_zfs_property(self, **kwargs):
        kwargs = Schema({"prop": str, "value": str}).validate(kwargs)
        self._filesystem_properties[kwargs["prop"]] = kwargs["value"]

    def _make_config(self):
        return {
            "builddir": Path(self.store.get_one('zil_pmem_builddir')),
            "module_args": {
                "zfs": self._config__zfs_module_args(),
            },
            "pool_properties": {},
            "filesystem_properties": deep_copy_dict(self._filesystem_properties),
            "poolname":"dut",
            "mountpoint": Path("/dut"),
            "vdevs": [
                *[f"nodax:{d}" for d in self.store.get_all("blockdevice")],
                 "log",
                 self._config__log_vdev(),
            ],
            "create_child_datasets": {
                "dirname_format_str": "ds{}",
                "name_format_str": "ds{}",
                "count": 32,
            },
            "create_child_zvols": {
                "name_format_str": "zv{}",
                "count": 4,
                "size": "4G", # TODO parametrize?
                "volblocksize": 4096, # TODO this causes warnings about excessive metadata space usage but it's what we write in the benchmarks...
            },
        }

    @property
    def blockdev_path(self):
        if not self.open_setup:
            return None
        # keep in sync with config above!
        return Path("/dev/zvol/dut/zv0")

    @property
    def fsstack_mountpoint(self):
        if not self.open_setup:
            return None
        # keep in sync with config above!
        return Path("/dut/ds0")

    @property
    def dataset_mountpoint_format_string(self):
        return "/dut/ds{}"

    def as_dict(self):
        return {
            "config": self._make_config(),
            "identity": self.cli_name(),
        }

class ZFSLwb(ZFS):

    def __init__(self, store, identity, zvol_request_sync):
        super().__init__(store, identity)
        self.zvol_request_sync = zvol_request_sync

    def cli_name(self):
        return f"{self.identity}-lwb-rs_{self.zvol_request_sync}"

    def _config__zfs_module_args(self):
        return {
            "zil_default_kind": "1",
            "zvol_request_sync": self.zvol_request_sync,
        }

    def _config__log_vdev(self):
        # "nodax:" prefix needs to go if we switch this to mainline openzfs
        return "nodax:" + self.store.get_one('fsdax')

class ZFSSyncDisabled(ZFSLwb):
    def __init__(self, store, identity, zvol_request_sync):
        super().__init__(store, identity, zvol_request_sync)
        self._set_zfs_property(prop="sync", value="disabled")

    def cli_name(self):
        return f"{self.identity}-sync_disabled-rs_{self.zvol_request_sync}"

class ZFSPmem(ZFS):

    def __init__(self, store, identity, zvol_request_sync, itxg_bypass, ncommitters):
        super().__init__(store, identity)
        self.zvol_request_sync = zvol_request_sync
        self.ncommitters = ncommitters
        self.zfs_zil_itxg_bypass = itxg_bypass

    def cli_name(self):
        return f"{self.identity}-pmem-rs_{self.zvol_request_sync}-byp_{self.zfs_zil_itxg_bypass}-nc_{self.ncommitters}"

    def _config__zfs_module_args(self):
        return {
            "zil_default_kind": "2",
            "zfs_zil_pmem_prb_ncommitters": self.ncommitters,
            "zvol_request_sync": self.zvol_request_sync,
            "zfs_zil_itxg_bypass": self.zfs_zil_itxg_bypass,
        }

    def _config__log_vdev(self):
        return "dax:" + self.store.get_one('fsdax')

class DevBlockdev:

    def __init__(self, path):
        assert "nvme0" not in str(path)
        self.path = path
        self.open = False

    def cli_name(self):
        return f"{self.path}"

    def as_dict(self):
        return {
            "identity": self.cli_name(),
        }

    @property
    def blockdev_path(self):
        if self.open:
            return self.path
        return None

    def is_dax_bdev(self):
        return False

    def __enter__(self):
        assert self.path.is_block_device()
        assert self.open is False
        self.open = True
        return self

    def __exit__(self, type, val, bt):
        assert self.open
        self.open = False

class DevPmem:

    def __init__(self, store):
        self.dev = None
        self.store = store

    def cli_name(self):
        return f"devpmem"

    def as_dict(self):
        return {
            "identity": self.cli_name(),
        }

    @property
    def blockdev_path(self):
        if self.dev:
            return self.dev
        return None

    def is_dax_bdev(self):
        return True

    def __enter__(self):
        assert self.dev is None
        self.dev = Path(self.store.get_first("fsdax"))
        assert self.dev.is_block_device()
        return self

    def __exit__(self, type, val, bt):
        assert self.dev is not None
        self.dev = None

class DevDax:

    def __init__(self, store):
        self.dev = None
        self.store = store

    def __enter__(self):
        assert self.dev is None
        self.dev = Path(self.store.get_one("devdax"))
        assert self.dev.is_char_device()
        return self

    def __exit__(self, type, val, bt):
        assert self.dev is not None
        self.dev = None

    @property
    def devdax_path(self):
        return self.dev

    def cli_name(self):
        return f"devdax"

    def as_dict(self):
        return {
            "identity": self.cli_name(),
        }

class DmStripe:

    def __init__(self, blockdevs):
        self.blockdevs = blockdevs
        self.stack = None
        self.dm_stripe = None

    def cli_name(self):
        return f"dm-stripe({len(self.blockdevs)})"

    def as_dict(self):
        return {
                "identity": self.cli_name(),
                "blockdevs": list(map(lambda bd: bd.as_dict(), self.blockdevs)),
        }

    @property
    def blockdev_path(self):
        return self.dm_stripe.path

    def is_dax_bdev(self):
        return False

    def __enter__(self):
        assert self.stack is None
        assert self.dm_stripe is None
        stack = contextlib.ExitStack()

        with stack:

            bds_opened = []
            for bds in self.blockdevs:
                bds_opened += [stack.enter_context(bds)]

            self.dm_stripe = stack.enter_context(lib.devicemapper.Stripe({
                "name": "bench_stripe",
                "blockdevs": list(map(lambda bd: bd.blockdev_path, bds_opened)),
            }))

            self.stack = stack.pop_all()

            return self

    def __exit__(self, type, val, bt):
        self.stack.close()
        self.stack = None
        self.dm_stripe = None

class DmWritecache:

    def __init__(self, pmem, origin):
        self.stack = None
        self.dm_wc = None
        self.pmem = pmem
        self.origin = origin

    def cli_name(self):
        return f"dm-writecache"

    def as_dict(self):
        return {
            "identity": self.cli_name(),
            "origin": self.origin.as_dict(),
            "pmem": self.pmem.as_dict(),
        }

    @property
    def blockdev_path(self):
        if not self.dm_wc:
            return None
        return self.dm_wc.path

    def is_dax_bdev(self):
        return False

    def __enter__(self):
        assert self.stack is None
        assert self.dm_wc is None
        stack = contextlib.ExitStack()

        with stack:

            pmem_stack = stack.enter_context(self.pmem)
            origin_stack = stack.enter_context(self.origin)

            dm_pmem = stack.enter_context(lib.devicemapper.Target(name="pmem", table=lib.devicemapper.simple_linear_table({
                "size": 10*(1<<30), # FIXME hard-coded
                "device": pmem_stack.blockdev_path, #Path(self.store.get_one("fsdax"))
            })))
            self.dm_wc = stack.enter_context(lib.devicemapper.WritecachePmem({
                    "name": "wc",
                    "size": 40*(1<<30), # FIXME hard-coded
                    "blocksize": 4096,
                    "origin_device": origin_stack.blockdev_path, #Path(self.store.get_first("blockdevice")),
                    "cache_device": dm_pmem.path,
                    # pretty frequent periodic writeback to approximate what a zvol would be doing
                    # we verified with fio that this works well
                    "options": {
                        "low_watermark": 0,
                        "high_watermark": 1,
                    }
                }))

            self.stack = stack.pop_all()

        return self

    def __exit__(self, type, val, bt):
        self.stack.close()
        self.stack = None
        self.dm_wc = None


class LinuxFilesystem:

    def __init__(self, blockdev_stack, mountpoint, mount_dax=False):
        self.blockdev_stack = blockdev_stack
        self.mountpoint = mountpoint
        self.mount_dax = mount_dax
        self.exit_stack = None
        self.on_exit = None
        self.entered_blockdev_stack = None

    def as_dict(self):
        return {
            "fstyp": self.fstyp,
            "mount_dax": self.mount_dax,
            "blockdev_stack": self.blockdev_stack.as_dict(),
        }

    def wipefs(self):
        must_run(["wipefs", "-a", self.entered_blockdev_stack.blockdev_path])

    def mkfs_args(self):
        return []

    def mkfs(self):
        self.wipefs()
        cmd = [self.mkfs_binary, *self.mkfs_args(), self.entered_blockdev_stack.blockdev_path]
        must_run(cmd)

    def has_o_dax():
        raise NotImplementedError

    def mount(self):
        if not self.mountpoint.is_dir():
            raise Exception(f"mountpoint={self.config.mountpoint} must be a directory")
        odax  = "dax" if self.mount_dax else ""
        cmd = ["mount", "-t", self.fstyp, "-o", odax, self.entered_blockdev_stack.blockdev_path, self.mountpoint]
        must_run(cmd)

    @property
    def fsstack_mountpoint(self):
        if self.on_exit:
            return self.mountpoint
        return None

    def unmount(self):
        # poll unmount so that when SIGINT'ing python a child process that uses the mountpoint has some time to quit
        def do_unmount():
            st = subprocess.run(["umount", self.mountpoint])
            return st.returncode == 0
        poll_wait(0.2, do_unmount, "unmount", timeout=5)

    def __enter__(self):
        assert self.exit_stack is None # this storage stack is single-use
        self.exit_stack = contextlib.ExitStack()
        with self.exit_stack: # see https://docs.python.org/3/library/contextlib.html for this pattern

            self.entered_blockdev_stack = self.exit_stack.enter_context(self.blockdev_stack)

            self.wipefs()
            self.mkfs()
            self.exit_stack.callback(self.wipefs)

            self.mount()
            self.exit_stack.callback(self.unmount)

            # setup went fine, stash away exit stack for __exit__
            self.on_exit = self.exit_stack.pop_all()
            return self

    def __exit__(self, type, value, traceback):
        self.on_exit.close()

class XFS(LinuxFilesystem):
    mkfs_binary = "mkfs.xfs"
    fstyp = "xfs"

    def has_o_dax():
        return True

class Ext4(LinuxFilesystem):
    mkfs_binary = "mkfs.ext4"
    fstyp = "ext4"

    def mkfs_args(self):
        mkfs_eopts = {
            "lazy_itable_init":"0",
            "lazy_journal_init":"0",
        }
        return ["-E", ",".join([f"{k}={v}" for k,v in mkfs_eopts.items()])]

    def has_o_dax():
        return True

