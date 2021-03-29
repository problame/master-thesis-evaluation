import contextlib
from schema import Schema, Or
import re
from pathlib import Path
import subprocess
import tempfile
import lib.simpletemplate as simpletemplate

####
# The workload files in this directory were copied
# from the filebench repo and subsequently (nothing but) templatized.
#  git describe: 1.5-alpha1-33-g22620e6
####

@contextlib.contextmanager
def with_aslr_disabled():
    # https://github.com/filebench/filebench/blob/22620e602cbbebad90c0bd041896ebccf70dbf5f/aslr.c#L47
    p = Path("/proc/sys/kernel/randomize_va_space")
    assert p.exists()

    preval = p.read_text()
    print(f"disabling ASLR (value was {preval!r})")
    try:
        p.write_text("0")
        yield
    finally:
        print(f"restoring ASLR config to previous value {preval!r}")
        try:
            p.write_text(preval)
        except Exception as e:
            raise Exception("could not restore ASLR config\n{p}\n{write value: {preval!r}") from e


# root@i30pc61:[~/src/filebench/workloads]: filebench -f varmail.f 2>/dev/null | cat
example_output="""Filebench Version 1.5-alpha3
0.000: Allocated 177MB of shared memory
0.001: Varmail Version 3.0 personality successfully loaded
0.001: Populating and pre-allocating filesets
0.082: bigfileset populated: 100000 files, avg. dir. width = 1000000, avg. dir. depth = 0.8, 0 leafdirs, 3126.206MB total size
0.082: Removing bigfileset tree (if exists)
0.088: Pre-allocating directories in bigfileset tree
0.088: Pre-allocating files in bigfileset tree
7.903: Waiting for pre-allocation to finish (in case of a parallel pre-allocation)
7.903: Population and pre-allocation of filesets completed
7.903: Starting 1 filereader instances
8.906: Running...
28.933: Run took 20 seconds...
28.936: Per-Operation Breakdown
closefile4           148304ops     7406ops/s   0.0mb/s    0.001ms/op [0.000ms - 21.255ms]
readfile4            148304ops     7406ops/s 163.2mb/s    0.222ms/op [0.001ms - 104.925ms]
openfile4            148304ops     7406ops/s   0.0mb/s    0.015ms/op [0.002ms - 36.633ms]
closefile3           148304ops     7406ops/s   0.0mb/s    0.001ms/op [0.000ms - 24.315ms]
fsyncfile3           148313ops     7406ops/s   0.0mb/s    0.282ms/op [0.002ms - 160.967ms]
appendfilerand3      148316ops     7406ops/s  58.0mb/s    0.064ms/op [0.006ms - 94.228ms]
readfile3            148318ops     7406ops/s 163.9mb/s    0.264ms/op [0.005ms - 114.698ms]
openfile3            148318ops     7406ops/s   0.0mb/s    0.019ms/op [0.002ms - 92.350ms]
closefile2           148318ops     7406ops/s   0.0mb/s    0.002ms/op [0.000ms - 43.669ms]
fsyncfile2           148335ops     7407ops/s   0.0mb/s    0.695ms/op [0.005ms - 118.621ms]
appendfilerand2      148342ops     7408ops/s  57.8mb/s    0.051ms/op [0.009ms - 57.543ms]
createfile2          148346ops     7408ops/s   0.0mb/s    1.770ms/op [0.023ms - 168.695ms]
deletefile1          148352ops     7408ops/s   0.0mb/s    3.140ms/op [0.030ms - 161.650ms]
28.936: IO Summary: 1928174 ops 96284.565 ops/s 14812/14814 rd/wr 442.9mb/s 0.502ms/op
28.936: Shutting down processes
"""

summary_re = re.compile(r".*IO Summary:\s+(?P<ops>\d+)\s+ops\s+(?P<ops_per_sec>\d+\.\d+)\s+ops")

def extract_metrics(output):
    res = {
        "summary_ops": None,
        "summary_ops_per_sec": None,
    }
    def assign_res(k, v):
        if res[k] != None:
            raise Exception(f"already have result for {k!r}\noutput:\n{output}")
        res[k] = v

    for line in output.splitlines():
        m = summary_re.match(line)
        if m:
            print(summary_re.pattern, line)
            assign_res('summary_ops', int(m['ops']))
            assign_res('summary_ops_per_sec', float(m['ops_per_sec']))

    unparsed = { name for name, value in filter(lambda p: p[1] is None, res.items()) }
    if len(unparsed) > 0:
        raise Exception(f"unparsed metrics found: {unparsed}")

    return res

def _test_extract_metrics():
    res = extract_metrics(example_output)
    assert res['summary_ops'] == 1928174
    assert res['summary_ops_per_sec'] == 96284.565
_test_extract_metrics()

ConfigSchema = Schema({
    "filebench_binary": Path,
    "name": str,
    "dir": Path,
    "runtime_secs": int,
    "vars": Or({}, { str: object }),
})
def run(config):
    config = ConfigSchema.validate(config)

    template_file = Path(__file__).parent / f"{config['name']}.f"
    template = template_file.read_text()
    autovars = ["runtime_secs", "dir"]
    overlap = set(config['vars'].keys()) & set(autovars)
    if len(overlap) > 0:
        raise Exception(f"vars {autovars} are automatic, the following vars are invalid: {overlap}")
    env = {
        **{ v: config[v] for v in autovars },
        **config['vars'],
    }
    workload_str = simpletemplate.eval_template(template, env)

    with contextlib.ExitStack() as stack:
        td = stack.enter_context(tempfile.TemporaryDirectory("run_filebench_benchmark_"))
        td = Path(td)
        workload_filepath = td / "workload.f"
        with open(workload_filepath, 'w') as f:
            f.write(workload_str)

        # !
        stack.enter_context(with_aslr_disabled())

        args = [
            config['filebench_binary'],
            "-f", workload_filepath,
        ]
        try:
            print(f"running filebench: {args}")
            st = subprocess.run(args, check=True, capture_output=True, text=True) # FIXME timeout
        except subprocess.CalledProcessError as e:
            raise Exception(f"failed to run filebench") from e

        metrics = extract_metrics(st.stdout)

        return {
            "stdout": st.stdout,
            "stderr": st.stderr,
            "metrics": metrics,
        }

