from schema import Schema, And
from pathlib import Path
import subprocess
import contextlib
import shutil
import os
import psutil
from .helpers import poll_wait
import csv
import io

example_output = """"test","rps","avg_latency_ms","min_latency_ms","p50_latency_ms","p95_latency_ms","p99_latency_ms","max_latency_ms"
"SET","484496.16","33.753","14.432","29.839","45.855","74.879","75.711"
"""

def parse_output(output):
    reader = csv.DictReader(io.StringIO(output), quotechar='"')
    rows = [row for row in reader]
    assert len(rows) == 1
    row = rows[0]
    assert row['test'] == 'SET'
    del row['test']
    row = {metric: float(value) for metric, value in row.items()}
    return row

def _test_parse_output():
    res = parse_output(example_output)
    assert res['rps'] == 484496.16
_test_parse_output()

# https://redis.io/topics/benchmarks

ConfigSchema = Schema({
    "redis6_checkout": And(Path, Path.is_dir),
    "dir": And(Path, Path.is_dir),
    "nrequests": int, # find something that runs long enough
    "keyspacelen": int, # default 1 (=> contention?)
    "pipeline_numreq": int, # default 1, increase for throughput (needs keyspacelen > 1)
})

def run(config):
    config = ConfigSchema.validate(config)

    dir = config['dir'] / "redis_dir"

    if not dir.parent.is_dir():
        raise Exception(f"{dir.parent} must be a directory")


    redis_sock = dir / "redis.sock"
    if redis_sock.exists():
        raise Exception(f"redis_sock={redis_sock} must not exist, we create it in this benchmark")

    redis_server = config['redis6_checkout'] / "src" / "redis-server"
    redis_cli = config['redis6_checkout'] / "src" / "redis-cli"
    redis_benchmark = config['redis6_checkout'] / "src" / "redis-benchmark"

    # safeguard (TODO: limit to the binaries above?)
    redis_processes = list(filter(lambda p: "redis" in p.name(), psutil.process_iter(['pid', 'name', 'exe'])))
    if len(redis_processes) > 0:
        raise Exception(f"redis processes are running, probably unclean shutdown, bailing out:\n{redis_processes}")

    with contextlib.ExitStack() as stack:

        # preemptively clean up previous invocation's mess
        if dir.is_dir():
            shutil.rmtree(dir)
        dir.mkdir()
        os.sync()


        args = [
            redis_server,
            # unixsocket for perf (see article  https://redis.io/topics/benchmarks)
            "--unixsocket", redis_sock,
            "--appendonly", "yes",
            "--appendfsync", "always",
            "--dir", config['dir'],
            # write back rbd every 1 second
            # Is advantageous for ZIL-LWB because the rbd write back is WR_NEED_COPY data?
            "--save", "1", "0",
            # no cheating! (default, but let's be explicit)
            "--no-appendfsync-on-rewrite", "no",
        ]
        print(f"starting server {' '.join(map(str, args))}")
        srv = stack.enter_context(subprocess.Popen(args))

        @contextlib.contextmanager
        def kill_srv():
            try:
                yield
            finally:
                print("terminating redis server")
                srv.terminate()
        stack.enter_context(kill_srv())

        def daemon_ready():
            st = subprocess.run([redis_cli, "-s", redis_sock, "info", "persistence"], text=True, capture_output=True)
            return st.returncode == 0 and "loading:0\n" in st.stdout
        poll_wait(0.1, daemon_ready, "redis server to become ready", 1)

        assert redis_sock.exists()

        args = [
            redis_benchmark,
            "-t", "set",
            "-n", str(config['nrequests']),
            "-r", str(config['keyspacelen']),
            "-P", str(config['pipeline_numreq']),
            "-s", redis_sock,
            "--csv",
        ]
        print(f"running benchmark: {args}")
        print("prewarm")
        try:
            subprocess.run(args, timeout=1)
        except subprocess.TimeoutExpired as e:
            pass

        print("actual run")
        try:
            st = subprocess.run(args, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise Exception(f"error running redis-benchmark: {' '.join(args)}\n{e!r}") from e

        return {
            "stdout": st.stdout,
            "metrics": parse_output(st.stdout),
        }

