from .helpers import string_with_one_format_placeholder, is_p2, merge_dicts, must_run
from schema import Schema, And, Or
from pathlib import Path
import dictlib
import json
import tempfile
import threading
import time
import concurrent.futures
from contextlib import ExitStack

TargetFsConfigSchema = Schema({
    "type": "fs",
    "filename_format_str": And(string_with_one_format_placeholder, lambda s: "$" not in s),
    "require_filename_format_str_parent_is_mountpoint": bool,
    "prewrite_mode": Or("delete", "prewrite")
})

TargetDevdaxConfigSchema = Schema({
    "type": "devdax",
    "devdax_path": Path,
})

TargetBlockdevConfigSchema = Schema({
    "type": "blockdev",
    "blockdev_path": Path,
})
FioBenchmarkConfig = Schema({
    "fio_binary": Path,
    "blocksize": And(int, is_p2),
    "size": And(int),
    "sync": Or(0, 1),
    "fsync_every": And(int, lambda n: n >= 0),
    "numjobs": And(int, lambda n: n > 0),
    "runtime_seconds": And(int, lambda n: n > 0),
    "ramp_seconds": And(int, lambda n: n >= 0),
    "target": Or(TargetFsConfigSchema, TargetBlockdevConfigSchema, TargetDevdaxConfigSchema),
})

def _run_fio(config, config_overrides, append_cmdline, call_after_rampup=None, call_after_fio_exit=None):
    config = merge_dicts(config, config_overrides)

    output_filename = "fio-output.json"

    args = [
        config["fio_binary"],
        "--name", "run_fio_benchmark",
        f"--ioengine={config['ioengine']}",
        "--end_fsync=1", # XXX does this make sense in a time-based benchmark?

        f"--size={config['size']}",
        f"--blocksize={config['blocksize']}",
        "--rw=randwrite",

        "--time_based=1",
        f"--runtime={config['runtime_seconds']}",
        f"--ramp_time={config['ramp_seconds']}",

        f"--sync={config['sync']}",
        f"--direct={config['direct']}",

        f"--fsync={config['fsync_every']}",

        f"--numjobs={config['numjobs']}",
        "--group_reporting=1",

        "--output-format=json+",
        f"--output={output_filename}",

        *append_cmdline
        # TODO
        # write_bw_logs
        # write_iops_logs
    ]

    starting_fio_event = threading.Event()
    fio_exited_or_panicked = threading.Event()

    def run_fio_thread():
        tempdir = tempfile.TemporaryDirectory(prefix="run_fio_benchmark_", suffix="__run_fio")
        d = Path(tempdir.name)
        assert len(list(d.iterdir())) == 0

        print("setup files")
        must_run(args + ["--create_only=1"], cwd=d)

        print("starting fio")
        starting_fio_event.set()
        try:
            must_run(args, cwd=d)
        except:
            raise
        finally:
            fio_exited_or_panicked.set()

        output_filepath = d / output_filename
        assert output_filepath.exists()
        with open(output_filepath, "r") as f:
            ret = json.load(f)
        tempdir.cleanup()
        return ret

    # dirty but will work...
    with concurrent.futures.ThreadPoolExecutor() as executor:
        fio = executor.submit(run_fio_thread)
        try:
            # wait for fio to start
            starting_fio_event.wait()
            # now wait for rampup time to pass
            # (this is somewhat accurate because we
            # run fio with --create_only before
            # we trigger the event)
            time.sleep(config["ramp_seconds"])

            with ExitStack() as stack:
                # now invoke the post-rampup pre exec callback
                call_after_rampup()
                # and queue the post-exit callback
                stack.callback(call_after_fio_exit)
                # then wait for fio to exit
                fio_exited_or_panicked.wait() # this is guaranteed to bet set, see above

            return fio.result()
        except:
            print("exception while running fio, waiting for fio to finish")
            fio.result()
            raise

def _syncwrite_benchmark_fs(config, **kwargs):

    filename_format = config['target']['filename_format_str']
    # setup the fio workfiles according to config
    for i in range(0, config['numjobs']):
        workfile_path = Path(filename_format.format(i))
        if not workfile_path.parent.is_dir():
            raise Exception(f"filename_format_str={filename_format} invalid: parent dir {workfile_path.parent} must be a directory")
        if config['target']['require_filename_format_str_parent_is_mountpoint'] and not workfile_path.parent.is_mount():
            raise Exception(f"filename_format_str={filename_format} invalid: parent dir {workfile_path.parent} must be a mountpoint")

        if workfile_path.exists() and not workfile_path.is_file():
            raise Exception(f"filename_format_str expanded to workfile_path={workfile_path} must be a file or not exist")

        if workfile_path.exists():
            workfile_path.unlink()
        assert not workfile_path.exists()

        if config['target']['prewrite_mode'] == "prewrite":
            subprocess.run([
                "dd",
                "if=/dev/urandom", f"of={workfile_path}",
                f"bs={config['blocksize']}",
                f"count={config['size'] >> math.log2(config['blocksize'])}",
                "conv=fsync",
            ], check=True)
            assert workfile_path.exists()
            assert workfile_path.stat().st_size == config['size']
        else:
            assert config['target']['prewrite_mode'] == "delete"

    return _run_fio(
            config,
            {"ioengine": "sync", "direct": 0},
            [ f"--filename_format=" + filename_format.format("$jobnum") ],
            **kwargs,
            )

def _syncwrite_benchmark_devdax(config, **kwargs):
    return _run_fio(
        config,
        {"ioengine":"dev-dax", "direct": 0},
        [ f"--filename={config['target']['devdax_path']}" ],
        **kwargs
    )

def _syncwrite_benchmark_blockdev(config, **kwargs):
    return _run_fio(
        config,
        {"ioengine":"sync", "direct": 1},
        [
            f"--filename={config['target']['blockdev_path']}",
            "--allow_file_create=0",
        ]
        ,
        **kwargs
    )


def run(config, **kwargs):
    # validate once on entry, then add values to it
    config = FioBenchmarkConfig.validate(config)

    bytarget = {
        "blockdev": _syncwrite_benchmark_blockdev,
        "fs": _syncwrite_benchmark_fs,
        "devdax": _syncwrite_benchmark_devdax,
    }
    return bytarget[config['target']['type']](config, **kwargs)



##!/usr/bin/env bash
#set -x
#set -euo pipefail
#
#SETUP_FS_JSON="$1"
#BLOCKSIZE=$2
#SYNC=$3
#NUMJOBS=$4
#OUTDIR="$5"
#
#test -d "$OUTDIR" || exit 23
#
#MOUNTPOINT="$(jq --raw-output ".common.mountpoint" "$SETUP_FS_JSON")"
#mountpoint "$MOUNTPOINT" || exit 23
#
#start_date="$(date --rfc-3339=seconds)"
#
#CMDLINE_COMMON="/usr/local/bin/fio --name benchmark1 --randrepeat=0 --group_reporting=1 --size=1G --end_fsync=1 --ioengine=sync \
#    --bs=$BLOCKSIZE\
#    --filename_format=$MOUNTPOINT/ds\$jobnum/benchmark \
#    "
#
#get_file_system_of_file() {
#    local FILE="$1"
#    test -e "$FILE" || exit 23
#    df -P -T "$FILE" | awk 'NR==2{print $2}'
#}
#
#get_zfs_dataset_of_mountpoint() {
#    local FILE="$1"
#    test -e "$FILE" || exit 23
#    df -P -T "$FILE" | awk 'NR==2{print $1}'
#}
#
#prewrite_benchmark_files() {
#    # if a file with contents MARKER_FILE_VAL is not present in exactly NUMJOBS dir, delete them all and re-create the files
#    # - include blocksize because the filesystem allocator might allocate differently depending on blocksize used
#    # - no need to include numjobs because we check the marker file count against NUMJOBS
#    local MARKER_FILE_VAL="v1-$BLOCKSIZE"
#    local markerfiles=("$MOUNTPOINT"/*/run_fio.setup.marker)
#    if test "${#markerfiles[@]}" == "$NUMJOBS" && ( for m in "${markerfiles[@]}"; do test "$(cat "$m")" == "$MARKER_FILE_VAL"; done ); then
#        echo "benchmark files already pre-written"
#    else
#        rm -f "$MOUNTPOINT"/*/{benchmark,run_fio.setup.marker}
#        $CMDLINE_COMMON --sync=0 --rw=write --numjobs=$NUMJOBS >/dev/null
#        sync --file-system  "$MOUNTPOINT"/*/benchmark
#        for i in $(seq 0 $(( NUMJOBS - 1 )) ); do echo -n "$MARKER_FILE_VAL" > "$MOUNTPOINT/ds$i/run_fio.setup.marker"; done
#        prewrite_benchmark_files # should always hit the first case, otherwise impl error
#    fi
#}
#prewrite_benchmark_files
#
#tmpfiles=()
#
#jq_add_args=()
#jq_slurpfile_cmd() {
#    local var="$1"
#    shift
#    local cmd=("$@")
#    tmpfile="$(mktemp)" #must not be local in order to be added to tmpfiles array, apparently
#    tmpfiles+=("$tmpfile")
#    "${cmd[@]}" | jq --raw-input --slurp > "$tmpfile"
#    jq_add_args+=(--slurpfile "$var" "$tmpfile")
#}
#
#echo "collecting pre-benchmark metadata"
#jq_slurpfile_cmd proc_stat_pre cat /proc/stat
#
#echo "running benchmark"
#FIO_OUTPUT_TMP="$(mktemp)"
#tmpfiles+=("$FIO_OUTPUT_TMP")
#$CMDLINE_COMMON --rw=randwrite --time_based=1 --runtime 20s --sync=$SYNC --numjobs=$NUMJOBS --output-format=json+ --output "$FIO_OUTPUT_TMP"
#
#echo "collecting post-benchmark metadata"
#jq_slurpfile_cmd proc_stat_post cat /proc/stat
#
#MOUNTPOINT_FS="$(get_file_system_of_file "$MOUNTPOINT")"
#case "$MOUNTPOINT_FS" in
#    zfs)
#        POOL="$(get_zfs_dataset_of_mountpoint "$MOUNTPOINT")"
#        jq_slurpfile_cmd zpool_status zpool status -p -P -v "$POOL"
#        jq_slurpfile_cmd zpool_list zpool list -Hv "$POOL"
#        jq_slurpfile_cmd zpool_get_all zpool get all -H "$POOL"
#        jq_slurpfile_cmd zfs_get_all zfs get all -H -r -p "$POOL"
#        jq_slurpfile_cmd zfs_version zfs version
#        ;;
#    ext4)
#        ;;
#    *)
#        echo "unexpected filesystem type for mountpoint=$MOUNTPOINT: $MOUNTPOINT_FS"
#        exit 23
#esac
#
#jq_slurpfile_cmd ndctl_list_human ndctl list --regions --namespaces --human
#jq_slurpfile_cmd ndctl_list ndctl list --regions --namespaces
#jq_slurpfile_cmd ipmctl_show_region_text ipmctl show -a -o text -region
#jq_slurpfile_cmd ipmctl_show_region_nvmxml ipmctl show -a  -o nvmxml -region
#jq_slurpfile_cmd ipmctl_show_topology_text ipmctl show -a -o text -topology
#jq_slurpfile_cmd ipmctl_show_topology_nvmxml ipmctl show -a -o nvmxml -topology
#jq_slurpfile_cmd proc_cpuinfo cat /proc/cpuinfo
#jq_slurpfile_cmd uname_a uname -a
#
#metadata_file="$(mktemp)"
#tmpfiles+=("$metadata_file")
#echo '{}' | jq \
#    --argfile setup_fs "$SETUP_FS_JSON" \
#    --arg blocksize $BLOCKSIZE \
#    --arg sync $SYNC \
#    --arg numjobs $NUMJOBS \
#    --arg start_date  "$start_date" \
#    --arg finish_date "$(date --rfc-3339=seconds)" \
#    "${jq_add_args[@]}" \
#    '$ARGS.named' \
#    > "$metadata_file"
#
#OUTFILE="$OUTDIR/$(cat "$metadata_file" | sha256sum  | awk '{ print $1 }').json"
#jq \
#    --slurpfile metadata "$metadata_file" \
#    '{ "metadata": $metadata, "fio_jsonplus": . } ' \
#    "$FIO_OUTPUT_TMP" \
#    > "$OUTFILE"
#
#for tmpfile in "${tmpfiles[@]}"; do
#    rm "$tmpfile" || echo failed to delete tmpfile "$tmpfile"
#done

