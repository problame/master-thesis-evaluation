from schema import Schema, Or, And
from .helpers import AttrDict
import re
from pathlib import Path
import subprocess
import time
import shutil

# Example Run:
# ./sqlite-bench --benchmarks=fillrandsync --db=/tmp/ --WAL_enabled=1 --use_existing_db=0 --num=100000
example_run_output = """
SQLite:     version 3.25.2
Date:       Tue Mar 30 12:38:43 2021
CPU:        24 * Intel(R) Xeon(R) Silver 4215 CPU @ 2.50GHz
CPUCache:   11264 KB
Keys:       16 bytes each
Values:     100 bytes each
Entries:    100000
RawSize:    11.1 MB (estimated)
------------------------------------------------
fillrandsync :    4200.870 micros/op;
"""

known_benchmarks = ["fillrandsync"]

benchmark_result_line_re = re.compile(r"^(?P<bench>\S+)\s+:\s+(?P<microsperop>\d+\.\d+) micros/op;")

def extract_benchmark_results(output):

    results = {}
    for line in output.splitlines():
        m = benchmark_result_line_re.match(line)
        if m:
            if m['bench'] in results:
                raise Exception(f"duplicate benchmark result for benchmark {m['bench']} in output:\n{output}")
            results[m['bench']] = {
                "micros_per_op": float(m['microsperop']),
            }

    return results

# test
def _test_extract_benchmark_results():
    r = extract_benchmark_results(example_run_output)
    assert r["fillrandsync"]["micros_per_op"] == 4200.870
_test_extract_benchmark_results()

ConfigSchema = Schema({
    "sqlitebench_checkout": And(Path, Path.is_dir),
    "db_dir": And(Path, Path.is_dir),
    "num": int,
    "benchmark": Or(*known_benchmarks),
})

def run(config):
    config = AttrDict(ConfigSchema.validate(config))

    try:
        git_describe = subprocess.run(["git", "describe", "--always", "--long", "--tags"], cwd=config.sqlitebench_checkout, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"cannot git-describe {config.sqlitebench_checkout} - is it a git checkout?") from e

    # TODO validate it was built with `make release`
    bench_binary = config.sqlitebench_checkout/ "sqlite-bench"
    if not bench_binary.is_file():
        raise Exception(f"{bench_binary} does not exist, build it yourself!")

    # use_existing_db=0 requires database to not exist
    dir = config.db_dir / "db"
    if dir.exists():
        assert dir.is_dir()
        shutil.rmtree(dir)
    dir.mkdir()

    args = [
        bench_binary,
        f"--benchmarks={config.benchmark}",
        f"--db={dir}",
        "--WAL_enabled=1",
        "--use_existing_db=0",
        f"--num={config.num}",
    ]

    print(f"running: {args}")
    try:
        start = time.monotonic()
        cp = subprocess.run(args, check=True, capture_output=True, text=True)
        runtime = time.monotonic() - start
    except subprocess.CalledProcessError as e:
        raise Exception(f"error running {args}:\n{e.stderr}") from e

    metrics = extract_benchmark_results(cp.stderr) # yes, stderr, wtf

    return {
        "stdout": cp.stdout,
        "git_describe": git_describe.stdout,
        "runtime": runtime,
        "metrics": metrics,
    }

