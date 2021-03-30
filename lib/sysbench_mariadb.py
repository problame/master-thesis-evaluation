from schema import Schema, And, Optional
from pathlib import Path
import docker
import subprocess
import shutil
import contextlib
from .helpers import must_run, poll_wait, AttrDict
import time
import re

#root@i30pc61:[~/src/sysbench]: src/sysbench oltp_insert --db-driver=mysql --mysql-db=sysbench --mysql-user=root --mysql-password=root --mysql-host=127.0.0.1 --mysql-port=3306 --time=10 --threads=32 run 2>/dev/null
example_output = """sysbench 1.0.20-ebf1c90 (using bundled LuaJIT 2.1.0-beta2)

Running the test with following options:
Number of threads: 32
Initializing random number generator from current time


Initializing worker threads...

Threads started!

SQL statistics:
    queries performed:
        read:                            0
        write:                           875664
        other:                           0
        total:                           875664
    transactions:                        875664 (87534.18 per sec.)
    queries:                             875664 (87534.18 per sec.)
    ignored errors:                      0      (0.00 per sec.)
    reconnects:                          0      (0.00 per sec.)

General statistics:
    total time:                          10.0023s
    total number of events:              875664

Latency (ms):
         min:                                    0.05
         avg:                                    0.36
         max:                                  102.20
         95th percentile:                        1.12
         sum:                               318131.33

Threads fairness:
    events (avg/stddev):           27364.5000/429.34
    execution time (avg/stddev):   9.9416/0.00
"""

section_re = re.compile(r"^(\S[^\d]*):\s*$")
metric_re = re.compile(r"\s*(?P<name>.+):\s*(?P<total>\d+(\.\d*)?)(\s*\((?P<persec>\d+\.\d+) per sec.\))?")

def extract_metrics(output):

    def iter_flattened_matched():
        section = None
        for line in output.splitlines():
            sm = section_re.match(line)
            if sm:
                print(f"started new section {sm[1]}")
                section = sm
            if section is None:
                print(f"line not in any section, skipping {line!r}")
                continue
            print(f"section {section!r} line: {line!r}")
            m = metric_re.match(line)
            if not m:
                print("  does not match metric re, skipping line and resetting section")
                continue
            try:
                metrics = {
                    "name": m['name'],
                    "total": float(m['total']),
                }
                if m['persec']:
                    metrics['persec'] = float(m['persec'])
            except ValueError as e:
                raise Exception(f"cannot parse line {line}") from e

            t = (section[1], metrics)
            print(f"  yielding: {t!r}")
            yield t

    d = {}
    for section, metric in iter_flattened_matched():
        sd = d.get(section, {})
        if metric['name'] in sd:
            raise Exception(f"duplciate metric {metrics['name']} in section {section}")
        if 'persec' in metric:
            sd[metric['name'] + "_total"] = metric['total']
            sd[metric['name'] + "_per_sec"] = metric['persec']
        else:
            sd[metric['name']] = metric['total']
        d[section] = sd

    expect_sections = {
        "SQL statistics": ["transactions_total", "transactions_per_sec"],
        "Latency (ms)": ["min", "avg", "95th percentile"],
    }
    found_sections = set(d.keys())
    missing_sections = set(expect_sections.keys()) - found_sections
    if len(missing_sections) > 0:
        raise Exception(f"missing sections {missing_sections}\ngot sections: {found_sections}")
    for sec, sec_expect_keys in expect_sections.items():
        found_keys = set(d[sec].keys())
        expect_keys = set(sec_expect_keys)
        missing = expect_keys - found_keys
        if len(missing) > 0:
            raise Exception(f"missing keys in section {sec}: {missing}\ngot keys: {found_keys}")

    return d

def _test_extract_metrics():
    m = extract_metrics(example_output)
    assert "SQL statistics" in m
    assert "transactions_per_sec" in m["SQL statistics"]
    assert "transactions_total" in m["SQL statistics"]
    assert m["SQL statistics"]["transactions_per_sec"] == 87534.18

    assert "Latency (ms)" in m
    assert "min" in m['Latency (ms)']
    assert m['Latency (ms)']["min"] == 0.05

_test_extract_metrics()

ConfigSchema = Schema({
    "dir": And(Path, Path.is_dir),
    "mariadb": {
        "docker_image": {
            "repository": str,
            "tag": str, # tested with 10.5.9
        }
    },
    "sysbench_checkout": And(Path, Path.is_dir),
    Optional("mariadb_container_name", default="evaluation-sysbench-mariadb-container"): str,
    "threads": int,
    "runtime_secs": int,
})

mariadb_auth = AttrDict({
    "user": "root",
    "password": "root",
    "database": "sysbench",
})

def run(config):
    config = ConfigSchema.validate(config)

     # mountpoint=/mnt; chmod 0777 $mountpoint && docker run --rm -it --net=host --name mariadb -v "$(readlink -f my.cnf)":/etc/mysql/my.cnf:ro -v $mountpoint:/var/lib/mysql -v $mountpoint:/innodb-log -e MYSQL_DATABASE=sysbench_db -e MYSQL_USER=root -e MYSQL_ROOT_PASSWORD=root mariadb:10.5.9

    sysbench_binary = config['sysbench_checkout'] / "src" / "sysbench"
    if not sysbench_binary.is_file():
        raise Exception(f"sysbench binary must exist at {sysbench_binary}")

    dir = config['dir']
    datadir = dir / "datadir"
    if datadir.exists():
        shutil.rmtree(datadir)
    datadir.mkdir()

    with contextlib.ExitStack() as stack:

        dck = docker.from_env()
        dck.ping()

        conf_img = config['mariadb']['docker_image']
        try:
            image = dck.images.get(f"{conf_img['repository']}:{conf_img['tag']}")
            assert image is not None
        except docker.errors.ImageNotFound:
            image = None

        if not image:
            print("image does not exist locally, pulling")
            image = dck.images.pull(conf_img['repository'], conf_img['tag'])
            assert image is not None

        print(f"using image {image!r}")
        print(f"  id is {image.id}")

        #docker run --rm -it --net=host --name mariadb -v "$(readlink -f my.cnf)":/etc/mysql/my.cnf:ro -v $mountpoint:/var/lib/mysql -v $mountpoint:/innodb-log -e MYSQL_DATABASE=sysbench_db -e MYSQL_USER=root -e MYSQL_ROOT_PASSWORD=root mariadb:10.5.9
        mariadb_container = dck.containers.run(
            image,
            command=None,
            auto_remove=True,
            network_mode="host", # performance
            volumes = {
                str(datadir): {'bind': '/var/lib/mysql', 'mode': 'rw'},
            },
            environment = {
                "MYSQL_DATABASE": mariadb_auth.database,
                "MYSQL_USER": mariadb_auth.user,
                "MYSQL_ROOT_PASSWORD": mariadb_auth.password,
            },
            name=config['mariadb_container_name'],
            detach=True,
        )

        @contextlib.contextmanager
        def stop_mariadb():
            try:
                yield
            finally:
                try:
                    mariadb_container.remove(force=True)
                except docker.errors.APIError as e:
                    raise Exception(f"cannot force-removing mariadb container {mariadb_container.name!r} to stop it") from e
        stack.enter_context(stop_mariadb())

        print(f"spawned mariadb container named {mariadb_container.name}")

        # src/sysbench oltp_insert --db-driver=mysql --mysql-db=sysbench_db --mysql-user=root --mysql-password=root --mysql-host=127.0.0.1 --mysql-port=3306 --time=10 --threads=32 help
        args_common = [
            sysbench_binary,
            "oltp_insert", # FIXME there are other interesting oltp write-intensive benches
            "--db-driver=mysql",
            f"--mysql-db={mariadb_auth.database}",
            f"--mysql-user={mariadb_auth.user}",
            f"--mysql-password={mariadb_auth.password}",
            "--mysql-host=127.0.0.1",
            "--mysql-port=3306",
            f"--time={config['runtime_secs']}",
            f"--threads={config['threads']}",
        ]

        sysbench_cwd = config['sysbench_checkout']

        def prepare():
            args = args_common.copy()
            args += ["prepare"]
            print(f"running {args}")
            st = subprocess.run(args, cwd=sysbench_cwd)
            return st.returncode == 0

        poll_wait(0.5, prepare, "wait for mariadb container to get ready and to run prepare step of sysbench", timeout=20)

        args = args_common.copy()
        args += ["run"]
        start = time.monotonic()
        st = must_run(args, cwd=sysbench_cwd, text=True)
        runtime = time.monotonic() - start

        metrics = extract_metrics(st.stdout)

        return {
            "stdout": st.stdout,
            "stderr": st.stderr,
            "runtime_secs": runtime,
            "metrics": metrics,
        }

