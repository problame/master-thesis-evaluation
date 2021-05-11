import functools
import json
import dotted
from lib.helpers import string_with_one_format_placeholder
import uuid

def find_unused_random_filename_in_dir(d, pattern):
    assert string_with_one_format_placeholder(pattern)
    while True:
        p = d / pattern.format(uuid.uuid4())
        if not p.exists():
            return p

class ResultStorage:
    def __init__(self, resultdir):
        if not resultdir.is_dir():
            raise Exception(f"resultdir={resultdir} must be a directory")
        self.resultdir = resultdir

    def save_json_result(self, prefix, result_dict):
        # https://hynek.me/articles/serialization/
        @functools.singledispatch
        def to_serializable(val):
            return str(val)
        ## actually we don't need custom serializers for anything, str(Path) is all we need and that's covered by the default case
        outpath = find_unused_random_filename_in_dir(self.resultdir, prefix + "-{}.json")
        with open(outpath, "w") as f:
            json.dump(result_dict, f, default=to_serializable)
    
            
    def iter_results(self, prefix):
        for filepath in self.resultdir.glob(f"{prefix}-*.json"):
            with open(filepath, "r") as f:
                try:
                    d = json.load(f)
                except e:
                    raise Exception(f"cannot process result file {filepath}") from e
                d["file"] = str(filepath)
                d['file_ctime'] = filepath.stat().st_ctime
                yield d
            
