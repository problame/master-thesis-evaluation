import parted
import math
from .helpers import must_run
import subprocess
from schema import Schema, Optional
from pathlib import Path

ConfigSchema = Schema({
    "devfspath": str,
    "configlabel": str,
    Optional("noparts", default=False): True,
    Optional("nparts", default=0): int,
    Optional("count_and_size", default=(None,None)): (int, int),
})

def partition_disk(config, store):
    config = ConfigSchema.validate(config)

    devfspath = config["devfspath"]

    assert devfspath.startswith("/dev/")
    assert not devfspath.startswith("/dev/nvme0")

    noparts= config["noparts"]
    nparts = config["nparts"]
    count_and_size = config["count_and_size"]

    assert int(nparts > 0) + int((count_and_size != (None,None))) + int(noparts == True) == 1

    if noparts:
        must_run(["wipefs", "-a", devfspath], check=True)
        return

    device = parted.getDevice(devfspath)
    disk = parted.freshDisk(device, "gpt")

    print(f"sectorSize={device.sectorSize}")
    print(f"physicalSectorSize={device.physicalSectorSize}")
    #assert device.sectorSize == device.physicalSectorSize

    sectors = device.length
    disksize = sectors * device.sectorSize
    assert disksize == device.getSize("b")

    assert math.log2(device.sectorSize).is_integer
    sectorshift = int(math.log2(device.sectorSize))
    twomibsector = (1<<21) >> sectorshift

    print(sectors)
    print(disksize)

    offset = 1<<21
    if nparts != None:
        partsize = int(math.floor( (disksize - (1<<30)) / nparts ))
        partsize = int(partsize >> 21) << 21
        print(f"partsize={partsize}")
        assert offset + partsize * nparts > disksize - 2*(1<<30) # we want to saturate the disk with this allocation scheme
    elif count_and_size != (None, None):
        nparts, partsize = count_and_size
        # user defines how much of the disk they want to use
    else:
        raise NotImplementedError()

    print(f"offset={offset} nparts={nparts} partsize={partsize} disksize={disksize}")
    assert nparts > 0
    assert partsize % (1<<21) == 0
    assert offset + partsize * nparts < disksize

    #constraint = parted.Constraint(startAlign=2*(2**20), endAlign=2*(2**20), minSize=0, maxSize=0, startRange=0, endRange=0)

    partitions = []
    for i in range(0, nparts):
        start = offset + i*partsize
        assert start % (1<<21) == 0
        geom = parted.Geometry(device=device, start=start >> sectorshift, length=partsize >> sectorshift)
        partition = parted.Partition(disk=disk, type=parted.PARTITION_NORMAL, geometry=geom)
        disk.addPartition(partition=partition, constraint=device.optimalAlignedConstraint)
        partitions.append(partition)

    disk.commit()

    for p in partitions:
        must_run(["wipefs", "-a", p.path], check=False) # best-effort since this doesn't work on nvme
        store.add(config["configlabel"], p.path)
    return [p.path for p in partitions]


