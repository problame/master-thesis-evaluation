import collections
from .helpers import product_dict
from pathlib import Path

class Dummy():
    """dummy benchmark, useful for verifying all storage stack impls work"""

    def run(self, rootdir, emit_result):
        dummyfile = rootdir / "dummy.txt"
        assert not dummyfile.exists()
        assert dummyfile.parent.is_dir()
        dummyfile.write_text("dummy")
        emit_result({"dummy": "dummy"})

class Filebench(collections.namedtuple("FilebenchT", ["identity", "workload", "vars"])):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        assert isinstance(self.vars, dict)
        for v in self.vars.values():
            assert isinstance(v, set)

    def run(self, dir, emit_result):
        for vars in product_dict(self.vars):
            config = {
                "filebench_binary": Path("/usr/local/bin/filebench"),
                "name": self.workload,
                "dir": dir,
                "runtime_secs": 10, # FIXME
                "vars": vars,
            }
            res = lib.filebench.run(config)
            emit_result({
                "_asdict": self._asdict(),
                "identity": self.identity,  # in case it can't be reconstructed from config
                "config": config,
                "result": res,
            })


class SqliteBench(collections.namedtuple("SqliteBenchT", ["num"])):

    def run(self, dir, emit_result):
        config = {
            "sqlitebench_checkout": Path("/root/src/sqlite-bench"),
            "db_dir": dir,
            "benchmark": "fillrandsync",
            "num": self.num, #10_000_000
        }
        res = lib.sqlite_bench.run(config)
        emit_result({
            "identity": "sqlite-bench",
            "config": config,
            "result": res,
        })

class RocksdbBench(collections.namedtuple("RocksdbBenchT", ["num", "nthreads"])):

    def run(self, dir, emit_result):
        for nthreads in self.nthreads:
            config = {
                "rocksdb_dir": Path("/root/src/rocksdb"),
                "db_dir": dir,
                "wal_dir": dir,
                "num": self.num, #400_000
                "threads": nthreads,
                "benchmark": "fillsync",
                "sync": True,
            }
            res = lib.rocksdb_bench.run(config)
            emit_result({
                "identity": "rocksdb-fillsync",
                "config": config,
                "result": res,
            })


class RedisSetBench(collections.namedtuple("RedisSetBenchT", ["nthreads_nclients"])):

    def run(self, dir, emit_result):
        for nthreads_nclients in self.nthreads_nclients:
            config = {
                "redis6_checkout": Path("/root/src/redis"),
                "dir": mountpoint,
                #"nrequests": {
                #    "type": "estimate",
                #    "target_runtime_secs": 20,
                #    "estimate_nrequests": 100_000,
                #    "actual_runtime_tolerance_bounds": (15, 40),
                #},
                "nrequests": {
                    "type": "fixed",
                    "nrequests": 1_000_000, # high enough for xfs + /dev/pmem and nthreads_nclients == 16 (we should switch to the estimation strategy iff all the other benchmarks do as well, until then we'll do a first run, see whether the min runtime is ok and adjust based on that
                },
                "keyspacelen": 'nrequests', # needs to be wide so that clients don't interfere on the same key; nrequests seemed to be a good value for that
                "pipeline_numreq": 1, # don't care about throughput
                "datasize": 3, # don't care about throughput
                "clients": nthreads_nclients,
                "threads": nthreads_nclients,
            }
            res = lib.redis_benchmark.run(config)
            emit_result({
                "identity": "redis-SET",
                "config": config,
                "result": res,
            })


class MariaDbSysbenchOltpInsert(collections.namedtuple("MariaDbSysbenchOltpInsertT", ["nthreads"])):

    def run(self, dir, emit_result):
        for nthreads in self.nthreads:
            config = {
                "dir": mountpoint,
                "mariadb": {
                    "docker_image": {
                        "repository": "mariadb",
                        "tag": "10.5.9",
                    },
                },
                "sysbench_checkout": Path("/root/src/sysbench"),
                "threads": 1,
                "runtime_secs": 10,
            }
            res = lib.sysbench_mariadb.run(config)
            emit_result({
                "identity": "mariadb-sysbench-oltp_insert",
                "config": config,
                "result": res,
            })

