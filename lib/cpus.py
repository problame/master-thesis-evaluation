from enum import Enum, auto
from pathlib import Path
import collections
import re
from schema import Schema

cpu_re = re.compile(r"cpu(\d+)")
def sysfs_cpus_by_number():
    cpus = {}
    for p in Path("/sys/devices/system/cpu").glob("cpu*"):
            number = p.name
            m = cpu_re.match(p.name)
            if not m:
                continue
            number = m[1]
            number = int(number)
            assert number not in cpus
            cpus[number] = p
    return cpus

ConfigSchema = Schema({
    int: {
        "online": bool,
    }
})
def online_offline_cpus(sysfs_cpus, config):
    config = ConfigSchema.validate(config)
    assert set(config.keys()) == set(sysfs_cpus.keys())
    for cpu_number, cpu_state in config.items():
        cpu = sysfs_cpus[cpu_number]
        if cpu_number == 0:
            assert not (cpu / "online").exists()
            if not cpu_state["online"]:
                raise Exception("CPU 0 zero cannot be offlined")
        else:
            (cpu / "online").write_text("1" if cpu_state["online"] else "0")

