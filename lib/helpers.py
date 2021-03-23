import mergedict
import subprocess
import copy

def must_run(*args, **kwargs):
    print(f"running command {args[0]}")
    try:
        mykwargs = {
                "capture_output": True,
                "check": True,
                **kwargs
                }
        output = subprocess.run(*args, **mykwargs)
        print(f"stdout:\n{output.stdout}\nstderr:{output.stderr}")
        return output
    except subprocess.CalledProcessError as e:
        print(f"{e}\nstdout:\n{e.stdout}\nstderr:\n{e.stderr}")
        raise e

def assert_allowed_keys(dic, must_subset):
    ok = set(dic.keys()).issubset(set(must_subset))
    if ok:
        return
    invalid = set(dic.keys()) - set(must_subset)
    raise Exception(f"{invalid} are invalid keys in dict")


def is_p2(n):
    return (n & (n-1) == 0) and n != 0

def string_with_one_format_placeholder(s):
    return isinstance(s, str) and s.count("{}") == 1

import deepmerge

def merge_dicts(d, updates):
    deepmerge.always_merger(d, updates)

def merge_dicts(d, updates):
    d = copy.deepcopy(d)
    deepmerge.always_merger.merge(d, updates)
    return d

def _merge_dicts_tests():
    # merge works on second level
    a = {
        "shared": {
            "shared": {
                "a": "foo",
                "shared": "a",
            }
        }
    }
    b = {
        "shared": {
            "shared": {
                "b": "bar",
                "shared": "b",
            }
        }
    }
    a_orig = copy.deepcopy(a)
    b_orig = copy.deepcopy(b)
    res = merge_dicts(a, b)
    import json
    assert json.dumps(a) == json.dumps(a_orig) # deep equals
    assert json.dumps(b) == json.dumps(b_orig) # deep equals

    assert res["shared"]["shared"]["a"] == "foo"
    assert res["shared"]["shared"]["b"] == "bar"
    assert res["shared"]["shared"]["shared"] == "b"

_merge_dicts_tests()
