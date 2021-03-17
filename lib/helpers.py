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

# returns a deep copy
def merge_dicts(d, updates):
    # d.merge is mutating `common`!
    d = mergedict.ConfigDict(copy.deepcopy(d))
    d.merge(updates)
    return d


