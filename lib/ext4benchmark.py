from .helpers import assert_allowed_keys, must_run

def setup_ext4(mountpoint, descr: dict):

    assert_allowed_keys(descr, ["dev", "dax"])
    dev = Path(descr["dev"])
    time.sleep(1) # apparently partition scanning is async? XXX shell out to partprobe?
    assert dev.is_block_device()

    dax = descr["dax"]
    assert type(dax) is bool

    # mkfs
    mkfs_eopts = {
        "lazy_itable_init":"0",
        "lazy_journal_init":"0",
    }
    must_run(["mkfs.ext4", "-E", ",".join([f"{k}={v}" for k,v in mkfs_eopts.items()]), dev])
    # mount
    mount_opts = [
        *([ "dax" ] if dax  else [])
    ]
    must_run(["mount", "-t", "ext4", *(["-o", ",".join(mount_opts)] if len(mount_opts) > 0 else []), dev, mountpoint])

    def dtor():
        must_run(["umount", mountpoint])
        #must_run(["wipefs", "-a", dev])

    return { "mkfs_eopts": mkfs_eopts, "mount_opts": mount_opts }, dtor


