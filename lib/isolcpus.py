from pathlib import Path



def parse_cpu_mask_string(cms):
    class ParseError(Exception):
        def __init__(self, msg):
            super().__init__(f"error parsing cpu mask string {cms!r}: {msg}")

    def try_int(tok):
       try:
           return int(tok)
       except ValueError:
           return None

    cpus = set()
    if len(cms) == 0:
        return cpus

    def add_nonexistent(c):
        if c in cpus:
            raise ParseError(f"cpu {c} already in set: {cpus!r}")
        cpus.add(c)

    for token in cms.split(","):
        i = try_int(token)
        if i is not None and i >= 0:
            add_nonexistent(i)
            continue

        rng = token.split("-")
        if len(rng) != 2:
            raise ParseError(f"invalid token {token!r}")
        l = try_int(rng[0])
        if l is None:
            raise ParseError(f"invalid lower bound {rng[0]!r} in {token!r}")
        r = try_int(rng[1])
        if r is None:
            raise ParseError(f"invalid upper bound {rng[1]!r} in {token!r}")
        for i in range(l, r+1):
            try:
                add_nonexistent(i)
            except ParseError as e:
                raise ParseError(f"range {token!r} contains duplicate cpu {i}") from e

    return cpus

def _test_parse_cpu_mask_string():
    input1 = "8-15,24-31"
    input2 = "8,9,10,11,12,13,14,15,24,25,26,27,28,29,30,31"
    input3 = "8,9,10-15"

    cpus = parse_cpu_mask_string(input1)
    assert cpus == {8,9,10,11,12,13,14,15,24,25,26,27,28,29,30,31}
    cpus = parse_cpu_mask_string(input2)
    assert cpus == {8,9,10,11,12,13,14,15,24,25,26,27,28,29,30,31}
    cpus = parse_cpu_mask_string(input3)
    assert cpus == {8,9,10,11,12,13,14,15}
    cpus = parse_cpu_mask_string("7,8,6")
    assert cpus == {7,8,6}
    cpus = parse_cpu_mask_string("0")
    assert cpus == {0}
    cpus = parse_cpu_mask_string("")
    assert cpus == set()

    try:
        parse_cpu_mask_string("1,0,1")
        assert False
    except:
        pass
_test_parse_cpu_mask_string()



def assert_effectively_singlesocket_system(numanode):
    try:
        node_cpulist_path = Path("/sys/devices/system/node") / f"node{numanode}" / "cpulist"
        node_cpulist = node_cpulist_path.read_text()
        node_cpus = parse_cpu_mask_string(node_cpulist)
    except Exception as e:
        raise Exception(f"read cpu list for path {node_cpulist_path}") from e

    try:
        isolated_cpus_path = Path("/sys/devices/system/cpu/isolated")
        isolated_cpus = isolated_cpus_path.read_text()
        isolated_cpus = parse_cpu_mask_string(isolated_cpus)
    except Exception as e:
        raise Exception(f"read isolated cpu list from path {isolated_cpus_path}") from e

    try:
        possible_cpus_path = Path("/sys/devices/system/cpu/possible")
        possible_cpus = possible_cpus_path.read_text()
        possible_cpus = parse_cpu_mask_string(possible_cpus)
    except Exception as e:
        raise Exception(f"read possible cpu list from path {possible_cpus_path}") from e


    assert isolated_cpus.issubset(possible_cpus)
    desired = possible_cpus - node_cpus
    current = isolated_cpus
    if desired != current:
        isolcpus = sorted(list(map(lambda x: f"{x}", desired)))
        cmdline = ",".join(isolcpus)
        raise Exception(f"use kernel command line isolcpus={cmdline}\n\n  desired: {desired}\n  current: {current}")

    return {
        "possible_cpus": possible_cpus,
        "isolated_cpus": isolated_cpus,
        "node_cpus": node_cpus,
        "node_number": numanode,
        "node_path": node_cpulist_path,
    }
