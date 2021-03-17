#!/usr/bin/env python3

from pathlib import Path
import subprocess
import time
from schema import Schema, Optional, Or
from .helpers import assert_allowed_keys, must_run, string_with_one_format_placeholder
import contextlib

def flagdict_to_argv(flag: str, flagdict: dict):
    argv = []
    for k, v in flagdict.items():
        argv += [flag, f"{k}={v}"]
    return argv


ConfigSchema = Schema({
    "builddir": Path,
    Optional("module_args", default={}): {
        str: Or({},{
            str: str
        }),
    },
    "poolname": str,
    Optional("pool_properties", default={}): Or({}, { str: str }),
    Optional("filesystem_properties", default={}): Or({}, {
        lambda prop: prop != "mountpoint": str
    }),
    "mountpoint": Path,
    "vdevs": [str],
    Optional("create_child_datasets", default=None): Or(None, {
        "dirname_format_str": string_with_one_format_placeholder,
        "name_format_str": string_with_one_format_placeholder,
        "count": int,
    }),
    Optional("create_child_zvols", default=None): Or(None,{
        "name_format_str": string_with_one_format_placeholder,
        "count": int,
        "size": str,
        "volblocksize": int,
    })
})

# Driver: OpenZFS 0.8 and forward-compatible driver
@contextlib.contextmanager
def setup_openzfs(config):
    config = ConfigSchema.validate(config)

    builddir = config["builddir"]
    assert builddir.is_dir()
    assert (builddir / "zfs_config.h").exists()
    assert (builddir / "Makefile").exists()
    assert (builddir / ".git").exists() # don't assert .is_dir() so that git worktrees work
    zfs_binary = builddir / "cmd" / "zfs" / "zfs"
    assert zfs_binary.exists()
    zpool_binary = builddir / "cmd" / "zpool" / "zpool"
    assert zpool_binary.exists()
    mountzfs_binary = builddir / "cmd" / "mount_zfs" / "mount.zfs"
    assert mountzfs_binary.exists()

    mountpoint = config["mountpoint"]
    assert mountpoint.is_dir()

    poolname = config["poolname"]
    assert type(poolname) is str and len(poolname) > 0

    # unload + reload module with correct module params
    mods_in_topo_order = [
            ("spl","module/spl/spl.ko"),
            ("zavl","module/avl/zavl.ko"),
            ("znvpair","module/nvpair/znvpair.ko"),
            ("zunicode","module/unicode/zunicode.ko"),
            ("zcommon","module/zcommon/zcommon.ko"),
            ("zlua","module/lua/zlua.ko"),
            ("zzstd","module/zstd/zzstd.ko"),
            ("icp","module/icp/icp.ko"),
            ("zfs","module/zfs/zfs.ko"),
    ]
    module_args = config.get("module_args", {})
    assert_allowed_keys(module_args, map(lambda p: p[0], mods_in_topo_order))
    def unload_modules():
        for mod, _ in reversed(mods_in_topo_order):
            print(f"removing module {mod}")
            if not (Path("/sys/module") / mod).exists():
                continue
            must_run(["rmmod",  mod])
            assert not (Path("/sys/module") / mod).exists()
    unload_modules()
    for mod, modrelpath in mods_in_topo_order:
        modparams = [f"{k}={v}" for k,v in module_args.get(mod, {}).items()]
        must_run(["insmod", builddir / Path(modrelpath) , *modparams])

    # create pool
    vdevs = config["vdevs"]
    assert type(vdevs) is list and len(vdevs) > 0
    filesystem_properties = config["filesystem_properties"]
    assert "mountpoint" not in filesystem_properties.keys()
    filesystem_properties["mountpoint"] = "legacy"
    zpool_create_cmd = [zpool_binary, "create", "-f",
        *flagdict_to_argv("-O", filesystem_properties),
        *flagdict_to_argv("-o", config["pool_properties"]),
        poolname, *vdevs]
    must_run(zpool_create_cmd)

    # get pool metadata
    def get_pool_guid(poolname):
        guid = str(must_run([zpool_binary, "get", "-H", "-p", "-o", "value",  "guid", poolname]).stdout).strip()
        return guid

    guid = get_pool_guid(poolname)

    # mount pool (child datasets need it mounted)
    must_run([mountzfs_binary, poolname, mountpoint])

    # create child datasets if requested
    create_child_datasets = config["create_child_datasets"]
    if create_child_datasets:
        assert_allowed_keys(create_child_datasets, ["name_format_str", "dirname_format_str", "count"])
        name_format_str = create_child_datasets["name_format_str"]
        assert name_format_str.count("{}") == 1
        dirname_format_str = create_child_datasets["dirname_format_str"]
        assert dirname_format_str.count("{}") == 1
        assert dirname_format_str.count("/") == 0
        count = int(create_child_datasets["count"])
        assert count >= 0

        for i in range(0, count):
            ds = poolname + "/" + name_format_str.format(i)
            must_run([zfs_binary, "create", "-o", "mountpoint=legacy", ds])
            ds_mp = mountpoint / dirname_format_str.format(i)
            ds_mp.mkdir()
            must_run([mountzfs_binary, ds, ds_mp])

    # create child zvols if requested
    create_child_zvols = config["create_child_zvols"]
    if create_child_zvols:
        name_format_str = create_child_zvols["name_format_str"]
        assert name_format_str.count("{}") == 1
        assert name_format_str.count("/") == 0
        count = int(create_child_zvols["count"])
        assert count >= 0
        size = create_child_zvols["size"]

        zvol_paths = []
        for i in range(0, count):
            ds = poolname + "/" + name_format_str.format(i)
            must_run([zfs_binary, "create", "-V", size, "-o", f"volblocksize={create_child_zvols['volblocksize']}", ds])
            zvol_paths += [Path(f"/dev/zvol/{ds}")]
        for p in zvol_paths:
            while True:
                if p.is_block_device():
                    break
                else:
                    time.sleep(0.1)

    try:
        yield { "pool_guid": guid }
    finally:
        # check pool guid to ensure that we only destroy pools that we created
        currentguid = get_pool_guid(poolname)
        if currentguid == guid:
            must_run([zpool_binary, "destroy", poolname]) # takes care of unmounting
        else:
            raise Exception("expecting to destroy pool {poolname} with guid {guid} but has guid {currentguid}")
        unload_modules() # always


## Driver common entry point
#def setup(cda: CommonDriverArgs, specific_driver_args: dict):
#
#    mountpoint = cda.mountpoint
#    # driver impl pre-conditions
#    assert mountpoint.is_dir()
#    assert len(list(mountpoint.iterdir())) == 0
#    assert not mountpoint.is_mount()
#
#    # invoke driver
#    drivers = {
#        "zpool-openzfs": setup_openzfs,
#        "zpool-openzfs-zilpmem": lambda cda, descr: setup_openzfs_common(cda, descr, builddir=Path("/root/zil-pmem/zil-pmem")),
#        "ext4": setup_ext4,
#    }
#    drive_metadata = None
#    assert len(specific_driver_args) == 1
#    driver_name, params = list(specific_driver_args.items())[0]
#    print(f"driver={driver_name}")
#    driver = drivers[driver_name]
#    driver_metadata, dtor = driver(cda, params)
#
#    # driver postconditions
#    assert mountpoint.is_mount()
#
#    def dtor_wrapper():
#        print(f"running dtor for driver {driver_name}")
#        dtor()
#        assert not mountpoint.is_mount()
#
#    setup_metadata = {
#        "driver_name": driver_name,
#        driver_name : { "setup_args": specific_driver_args,  "metadata": driver_metadata},
#    }
#    return setup_metadata, dtor_wrapper
#
#################################################################################
## Layout Definitions
#################################################################################
#
#import argparse
#
#LAYOUTS = {}
#def layout(func):
#    """decorator that registers a layout"""
#    assert func.__name__ not in LAYOUTS.keys()
#    def invoke(*args, **kwargs):
#        return func(*args, **kwargs)
#    LAYOUTS[func.__name__] = invoke
#
#@layout
#def layout_zpool_nvme_drives_pmem_slog(cda: CommonDriverArgs, args):
#    assert len(args) == 0
#    return setup(cda, {
#        "zpool-openzfs-zilpmem": {
#            "module_args": {
#                "zfs": {
#                    #"zfs_nocacheflush": "0",
#                    #"zfs_zio_taskq_batch_cpu_pct": "1",
#                    "zil_default_kind": "2",
#                    "zfs_zil_pmem_prb_ncommitters": "8",
#                    "zvol_request_sync": "1",
#                },
#            },
#            "pool_properties": {},
#            "filesystem_properties": {
#                "recordsize": "4k",
#            },
#            "poolname":"dut",
#            "vdevs": [
#                #*partition_disk("/dev/nvme1n1", count_and_size=(2, 10 * 1<<30)),
#                #*partition_disk("/dev/nvme2n1", count_and_size=(2, 10 * 1<<30)),
#                #*partition_disk("/dev/nvme3n1", count_and_size=(2, 10 * 1<<30)),
#                *partition_disk("/dev/nvme1n1", nparts=10),
#                *partition_disk("/dev/nvme2n1", nparts=10),
#                *partition_disk("/dev/nvme3n1", nparts=10),
#                #*partition_disk("/dev/pmem0", nparts=2),
#                #*partition_disk("/dev/pmem1", nparts=2),
#                #*partition_disk("/dev/pmem2", nparts=2),
#                "log",
#                "dax:/dev/pmem0",
#                #*partition_disk("/dev/pmem0", nparts=1),
#                #*partition_disk("/dev/pmem1", nparts=1),
#                #*partition_disk("/dev/pmem2", nparts=2),
#            ],
#            "create_child_datasets": {
#                "dirname_format_str": "ds{}",
#                "name_format_str": "ds{}",
#                "count": 32,
#            },
#            "create_child_zvols": {
#                "name_format_str": "zv{}",
#                "count": 4,
#                "size": "4G",
#            },
#         }
#    })
#
#@layout
#def layout_ext4_pmem(cda: CommonDriverArgs, args):
#    assert len(args) == 0
#    return setup(cda, {
#        "ext4": {
#            "dev": partition_disk("/dev/pmem1", nparts=1)[0],
#            #"dev": partition_disk("/dev/nvme1n1", nparts=1)[0],
#            "dax": False,
#        }
#    })
#
#import json
#import dill # pip install dill 0.3.2
#
#def main():
#    parser = argparse.ArgumentParser(description="declaratively configure partitioning and filesystem")
#    parser.add_argument("--metadata-out", required=True, type=argparse.FileType('w', encoding='utf-8'), help="where to write the metadata")
#    parser.add_argument("--mountpoint", required=True, type=str, help="where the filesystem should be mounted")
#    parser.add_argument("--dtor-pickle", type=str, default="/setup_fs.dtor.pickle")
#    parser.add_argument("layout", type=str, choices=LAYOUTS.keys(), help="select which pre-defined layout should be configured")
#    parser.add_argument("layout_args", nargs=argparse.REMAINDER, help="arguments passed to the layout function")
#    args = parser.parse_args()
#    print(args.layout_args)
#
#    dtor_pickle_file_path = Path(args.dtor_pickle)
#    if dtor_pickle_file_path.exists():
#        assert dtor_pickle_file_path.is_file()
#        print(f"found pickled layout dtor {dtor_pickle_file_path}, running it")
#        with open(dtor_pickle_file_path, "rb") as dtor_pickle_file:
#            # de-pickle and run the dtorrun the
#            dtor = dill.load(dtor_pickle_file)
#            # dtor is not required to be idempotent => once opening + unpickling succeeds, remove the file so future attempts don't find it
#            dtor_pickle_file_path.unlink()
#            dtor()
#    assert not dtor_pickle_file_path.exists()
#
#    mountpoint = Path(args.mountpoint)
#    assert not mountpoint.exists() or (mountpoint.is_dir() and len(list(mountpoint.iterdir())) == 0)
#    mountpoint.mkdir(exist_ok=True)
#
#    common_driver_args = CommonDriverArgs(mountpoint=mountpoint)
#    # invoke the layout method
#    setup_metadata, dtor = LAYOUTS[args.layout](common_driver_args, args.layout_args)
#
#    metadata = {
#        "common": common_driver_args.json_serializable_metadata_dict(),
#        "driver": setup_metadata,
#    }
#
#    json.dump(metadata, args.metadata_out)
#    print(json.dumps(metadata, sort_keys=True, indent=4))
#
#    # pickle dtor for next invocation
#    with open(dtor_pickle_file_path, "wb") as f:
#        dill.dump(dtor, f)
#
#if __name__ == "__main__":
#    main()
#
