import mergedict
import subprocess
import copy
import time
from pathlib import Path
import os
import functools
import json
import itertools

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


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self

def poll_wait(sleeptime, check, what="<unspecified>", timeout=None):
    start = time.monotonic()
    while check() == False:
        print(f"poll_wait for: {what}")
        time.sleep(sleeptime)
        if timeout and time.monotonic() - start > timeout:
            raise Exception(f"poll_wait timeout {timeout}s waiting for {what}")
    print(f"poll_wait done: {what}")

def zero_out_first_sector(blockdev):
    assert Path(blockdev).is_block_device()
    assert "nvme0" not in str(blockdev)
    fd = os.open(blockdev, os.O_WRONLY)
    try:
        os.pwrite(fd, bytearray(512), 0) #512 is the linux sector size
        os.fsync(fd)
    finally:
        os.close(fd)


# https://hynek.me/articles/serialization/
@functools.singledispatch
def json_dump_default_to_str(val):
    return str(val)

# https://stackoverflow.com/a/5228294/305410
def product_dict(kwargs):
    keys = kwargs.keys()
    vals = kwargs.values()
    for instance in itertools.product(*vals):
        yield dict(zip(keys, instance))
def _test_product_dict():
    p = list(product_dict({"a": {23, 42}, "b": {"x", "y"}}))
    found = [
        {"a": 23, "b": "x"},
        {"a": 42, "b": "x"},
        {"a": 23, "b": "y"},
        {"a": 42, "b": "y"},
    ]
    found = list(map(lambda expect: [expect, False], found))

    for pi in p:
        for f in found:
            # https://stackoverflow.com/a/31978554/305410
            if f[0] == pi:
                f[1] = True

    for f in found:
        assert f[1]
_test_product_dict()
