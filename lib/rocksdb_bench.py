from schema import Schema, Or, And
from .helpers import AttrDict
import re
from pathlib import Path
import subprocess

# Example Run:
#./db_bench --benchmarks="fillsync" --db /mnt --wal_dir /mnt  --num=100000 --threads=3 --report_file_operations --report_bg_io_stats 2>/dev/null
example_run_output = """Initializing RocksDB Options from the specified file
Initializing RocksDB Options from command-line flags
Keys:       16 bytes each (+ 0 bytes user-defined timestamp)
Values:     100 bytes each (50 bytes after compression)
Entries:    100000
Prefix:    0 bytes
Keys per prefix:    0
RawSize:    11.1 MB (estimated)
FileSize:   6.3 MB (estimated)
Write rate: 0 bytes/second
Read rate: 0 ops/second
Compression: Snappy
Compression sampling rate: 0
Memtablerep: skip_list
Perf Level: 1
------------------------------------------------
Initializing RocksDB Options from the specified file
Initializing RocksDB Options from command-line flags
DB path: [/mnt]
fillsync     :      78.309 micros/op 38306 ops/sec;    4.2 MB/s (100 ops)
Num files opened: 24
Num Read(): 12
Num Append(): 199907
Num bytes read: 12380
Num bytes written: 39518460
"""

known_benchmarks = ["fillsync", "overwrite"]

# from db_bench_tool.cc
#    fprintf(stdout, "%-12s : %11.3f micros/op %ld ops/sec;%s%s\n",
#            name.ToString().c_str(),
#            seconds_ * 1e6 / done_,
#            (long)throughput,
#            (extra.empty() ? "" : " "),
#            extra.c_str());
#
benchmark_result_line_re = re.compile(r"^(?P<bench>\S+)\s+:\s+(?P<microsperop>\d+\.\d+) micros/op (?P<opspersec>\d+) ops/sec")

def extract_benchmark_results(output):

    results = {}
    for line in output.splitlines():
        m = benchmark_result_line_re.match(line)
        if m:
            if m['bench'] in results:
                raise Exception(f"duplicate benchmark result for benchmark {m['bench']} in output:\n{output}")
            results[m['bench']] = {
                "micros_per_op": float(m['microsperop']),
                "ops_per_sec": int(m['opspersec']),
            }

    return results

# test
def _test_extract_benchmark_results():
    r = extract_benchmark_results(example_run_output)
    assert r["fillsync"]["micros_per_op"] == 78.309
    assert r["fillsync"]["ops_per_sec"] == 38306
_test_extract_benchmark_results()

ConfigSchema = Schema({
    "rocksdb_dir": And(Path, Path.is_dir),
    "db_dir": And(Path, Path.is_dir),
    "wal_dir": And(Path, Path.is_dir),
    "num": int,
    "threads": int,
    "benchmark": Or(*known_benchmarks),
    "sync": True,
})

def run(config):
    config = AttrDict(ConfigSchema.validate(config))

    try:
        git_describe = subprocess.run(["git", "describe", "--always", "--long", "--tags"], cwd=config.rocksdb_dir, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"cannot git-describe {config.rocksdb_dir} - is it a git checkout?") from e

    # TODO validate it was built with `make release`
    db_bench_binary = config.rocksdb_dir / "db_bench"
    if not db_bench_binary.is_file():
        raise Exception(f"{db_bench_binary} does not exist, build it with `make -C {config.rocksdb_dir} release`")

    args = [
        db_bench_binary,
        "--benchmarks", config.benchmark,
        "--db", config.db_dir,
        "--wal_dir", config.wal_dir,
        "--sync",
        "--num", str(config.num),
        "--threads", str(config.threads),
        "--report_file_operations",
        "--report_bg_io_stats",
    ]

    print(f"running db_bench: {args}")
    try:
        cp = subprocess.run(args, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"error running db_bench:\n{e.stderr}") from e

    metrics = extract_benchmark_results(cp.stdout)

    return {
        "stdout": cp.stdout,
        "metrics": metrics,
    }

