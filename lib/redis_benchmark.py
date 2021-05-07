from schema import Schema, And, Or
from pathlib import Path
import subprocess
import contextlib
import shutil
import os
import psutil
from .helpers import poll_wait
import csv
import io
import time

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
    "nrequests": Or(
        {
            "type": "estimate",
            "estimate_nrequests": int,
            "target_runtime_secs": int,
            "actual_runtime_tolerance_bounds": (int, int),
        },
        {
            "type": "fixed",
            "nrequests": int,
        },
    ),
    "keyspacelen": Or("nrequests", int), # default 1 (=> contention?)
    "datasize": int, # default 3 (SplitFS uses 1024)
    "pipeline_numreq": int, # default 1, increase for throughput (needs keyspacelen > 1)
    "threads": int,
    "clients": int, # per thread
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
        poll_wait(0.1, daemon_ready, "redis server to become ready", 30)

        assert redis_sock.exists()

        def do_run(ctx, nrequests):
            assert isinstance(nrequests, int)

            keyspacelen = config['keyspacelen']
            if keyspacelen == 'nrequests':
                keyspacelen = nrequests

            args = [
                redis_benchmark,
                "-t", "set",
                "-n", str(nrequests),
                "-r", str(keyspacelen),
                "-P", str(config['pipeline_numreq']),
                "-s", redis_sock,
                "--csv",
                "--threads", str(config['threads']),
                "-c", str(config['clients']),
                "-d", str(config['datasize']),
            ]
            print(f"running ({ctx}) {args}")

            print("actual run")
            try:
                start = time.monotonic()
                st = subprocess.run(args, check=True, capture_output=True, text=True)
                runtime = time.monotonic() - start
            except subprocess.CalledProcessError as e:
                raise Exception(f"error running redis-benchmark: {' '.join(args)}\n{e!r}") from e

            return {
                "stdout": st.stdout,
                "metrics": parse_output(st.stdout),
                "runtime_secs": runtime,
                "nrequests": nrequests,
                "keyspacelen": keyspacelen,
            }

        def determine_nrequests():
            if config['nrequests']['type'] == 'fixed':
                return config['nrequests']['nrequests'], (None, None), None
            else:
                assert config['nrequests']['type'] == 'estimate'
                est_config['nrequests']
                estimate_nrequests = est_config['estimate_nrequests']
                estimate = do_run("estimate nrequests", estimate_nrequests)
                print(f"estimate results: {estimate}")
                avg_latency_ms = estimate['metrics']['avg_latency_ms']
                # runtime_secs = nrequests * (avg_latency_ms / 1000)
                # <=>
                # nrequests = runtime_secs * 1000 / avg_latency_ms
                nrequests = est_config['target_runtime_secs'] * 1000 / avg_latency_ms
                nrequests = int(nrequests)
                print(f"estimated nrequests={nrequests}")
                # TODO validate our model by comparing actual and estimated avg latency
                allowed = est_config['actual_runtime_tolerance_bounds']
                return nrequests, allowed, estimate
        nrequests, rt_bounds, estimate = determine_nrequests()

        # do the actual run
        main_run = do_run("actual run", nrequests)

        # validate that we are within allowed bounds
        rt =  main_run['runtime_secs']
        if rt_bounds[0] and not (rt_bounds[0] < rt):
            raise Exception(f"lower runtime bound violated: rt={rt}, bounds={rt_bounds}")
        if rt_bounds[1] and not (rt < rt_bounds[1]):
            raise Exception(f"upper runtime bound violated: rt={rt}, bounds={rt_bounds}")

        return {
            "estimate": estimate,
            "main": main_run,
        }



