from schema import Schema, And, Optional
from pathlib import Path
from .helpers import AttrDict, must_run

class LinuxFilesystem:

    def __init__(self, **kwargs):
        self.config = AttrDict(Schema({
            "mountpoint": Path,
            "blockdev": And(Path, Path.is_block_device),
            Optional("mount_args", default=[]): [str],
        }).validate(kwargs))
        # protect the host system
        assert "nvme0" not in str(self.config.blockdev)

    def wipefs(self):
        must_run(["wipefs", "-a", self.config.blockdev])

    def mkfs_args(self):
        return []

    def mkfs(self):
        self.wipefs()
        cmd = [self.mkfs_binary, *self.mkfs_args(), self.config.blockdev]
        must_run(cmd)

    def has_o_dax(self):
        raise NotImplementedError

    def mount(self):
        if not self.config.mountpoint.is_dir():
            raise Exception(f"mountpoint={self.config.mountpoint} must be a directory")
        cmd = ["mount", "-t", self.fstyp, *self.config.mount_args, self.config.blockdev, self.config.mountpoint]
        must_run(cmd)

    def unmount(self):
        must_run(["umount", self.config.mountpoint])


    def __enter__(self):
        self.wipefs()
        self.mkfs()
        self.mount()
        return self

    def __exit__(self, type, value, traceback):
        self.unmount()
        self.wipefs()

class XFS(LinuxFilesystem):
    mkfs_binary = "mkfs.xfs"
    fstyp = "xfs"

    def has_o_dax(self):
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

    def has_o_dax(self):
        return True

