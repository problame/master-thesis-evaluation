
def system_setup__manual():
    lib.isolcpus.assert_effectively_singlesocket_system(0)

    store.add("fsdax", "/dev/pmem0")
    for i in [1,2,3,4]:
        store.add("blockdevice", f"/dev/pmem{i}")

def system_setup__i30pc61_single_dimm():
    lib.isolcpus.assert_effectively_singlesocket_system(0)

    lib.pmem.setup_pmem({
    	"regions": [
    		{
    			"PersistentMemoryType": "AppDirectNotInterleaved",
    			"SocketID": "0x0000",
    			"DimmID": "0x0020",
    			"namespaces": [
    				{
    					"mode": "devdax",
    					"size": 10 * (1<<30),
    					"configlabel": "devdax",
    				},
    				{
    					"mode": "fsdax",
    					"size": 10 * (1<<30),
    					"configlabel": "fsdax",
    				},
    			]	
    		}
    	]
    }, store)

    partitioning = {
        store.get_one("fsdax"): { "noparts": True, "configlabel": "pmemdevice" }, # why?
        "/dev/nvme1n1": { "nparts": 10, "configlabel": "blockdevice" },
        "/dev/nvme2n1": { "nparts": 10, "configlabel": "blockdevice" },
        "/dev/nvme3n1": { "nparts": 10, "configlabel": "blockdevice" },
    }
    for dev, config in partitioning.items():
        lib.partitioning.partition_disk({"devfspath": dev, **config}, store)

def system_setup__i30pc62(DimmID):
    isolcpus_data = lib.isolcpus.assert_effectively_singlesocket_system(0)

    pmem_config = {
    	"regions": [
            # the dimms on socket 0 are interleaved
    		{
    			"PersistentMemoryType": "AppDirect",
    			"SocketID": "0x0000",
    			"DimmID": DimmID, #"0x0001, 0x0011, 0x0101, 0x0111",
    			"namespaces": [
    				{
    					"mode": "devdax",
    					"size": 10 * (1<<30),
    					"configlabel": "devdax",
    				},
    				{
    					"mode": "fsdax",
    					"size": 10 * (1<<30),
    					"configlabel": "fsdax",
    				},
    			]	
    		},
            # all the dimms on the disabled socket are treated as block devices (the machine has no other nvmes)
            *[{
         		"PersistentMemoryType": "AppDirectNotInterleaved",
    			"SocketID": "0x0001",
    			"DimmID": dimmid,
    			"namespaces": [
    				{
    					"mode": "fsdax",
    					"size": 100 * (1<<30),
    					"configlabel": "blockdevice", #!!!!!!!!!
    				},
    			]	
            } for dimmid in ["0x1011", "0x1101", "0x1111"]],
    	]
    }
    lib.pmem.setup_pmem(pmem_config, store)
    return {
        "pmem_config": pmem_config,
        "isolcpus_data": isolcpus_data,
    }


