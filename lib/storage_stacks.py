from pathlib import Path
import lib.zfssetup
import contextlib
from .helpers import must_run, poll_wait
import subprocess

class ZFS:
    def __init__(self, store, identity):
        self.store = store
        self.identity = identity
        self.open_setup = None

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

    def _make_config(self):
        return {
            "builddir": Path("/root/zil-pmem/zil-pmem"),
            "module_args": {
                "zfs": self._config__zfs_module_args(),
            },
            "pool_properties": {},
            "filesystem_properties": {
                "recordsize": "4k",
                "compression": "off",
            },
            "poolname":"dut",
            "mountpoint": Path("/dut"),
            "vdevs": [
                *self.store.get_all("nvmepart"), # TODO parametrize?
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

class DmWritecache:

    def __init__(self, store):
        self.stack = None
        self.dm_wc = None
        self.store = store

    def cli_name(self):
        return f"dm-writecache"

    def as_dict(self):
        return {
            "identity": self.cli_name(),
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
        self.stack = contextlib.ExitStack()
        dm_pmem = self.stack.enter_context(lib.devicemapper.Target(name="pmem", table=lib.devicemapper.simple_linear_table({
            "size": 10*(1<<30),
            "device": Path(self.store.get_one("fsdax"))})))
        self.dm_wc = self.stack.enter_context(lib.devicemapper.WritecachePmem({
                "name": "wc",
                "size": 40*(1<<30),
                "blocksize": 4096,
                "origin_device": Path(self.store.get_first("nvmepart")),
                "cache_device": dm_pmem.path,
                # always do writeback so that it approximates the zvol
                "options": {
                    "low_watermark": 0,
                    "high_watermark": 0,
                }
            }))

        return self

    def __exit__(self, type, val, bt):
        self.stack.__exit__(type, val, bt)
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

