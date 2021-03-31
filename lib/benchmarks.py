import collections
from .helpers import product_dict
from pathlib import Path

class Dummy():
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


