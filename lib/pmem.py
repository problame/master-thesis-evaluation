import subprocess
import xmltodict
import json
from schema import Schema, Or, Optional, And
import ctypes
from pathlib import Path

# ipmctl show -a -o nvmxml -region
ref_ipmctl_output = """
<RegionList>
  <Region>
   <SocketID>0x0000</SocketID>
   <PersistentMemoryType>AppDirectNotInterleaved</PersistentMemoryType>
   <Capacity>126.000 GiB</Capacity>
   <FreeCapacity>0.000 GiB</FreeCapacity>
   <HealthState>Healthy</HealthState>
   <DimmID>0x0020</DimmID>
   <RegionID>0x0001</RegionID>
   <ISetID>0xfccfda90b94a8a22</ISetID>
  </Region>
  <Region>
   <SocketID>0x0000</SocketID>
   <PersistentMemoryType>AppDirectNotInterleaved</PersistentMemoryType>
   <Capacity>126.000 GiB</Capacity>
   <FreeCapacity>0.000 GiB</FreeCapacity>
   <HealthState>Healthy</HealthState>
   <DimmID>0x0120</DimmID>
   <RegionID>0x0002</RegionID>
   <ISetID>0x2acfda90a44a8a22</ISetID>
  </Region>
  <Region>
   <SocketID>0x0001</SocketID>
   <PersistentMemoryType>AppDirectNotInterleaved</PersistentMemoryType>
   <Capacity>126.000 GiB</Capacity>
   <FreeCapacity>0.000 GiB</FreeCapacity>
   <HealthState>Healthy</HealthState>
   <DimmID>0x1020</DimmID>
   <RegionID>0x0003</RegionID>
   <ISetID>0x7acfda90ac4a8a22</ISetID>
  </Region>
  <Region>
   <SocketID>0x0001</SocketID>
   <PersistentMemoryType>AppDirectNotInterleaved</PersistentMemoryType>
   <Capacity>126.000 GiB</Capacity>
   <FreeCapacity>0.000 GiB</FreeCapacity>
   <HealthState>Healthy</HealthState>
   <DimmID>0x1120</DimmID>
   <RegionID>0x0004</RegionID>
   <ISetID>0xd2b1da9068478a22</ISetID>
  </Region>
 </RegionList>
"""

IpmctlSchema = Schema({
	"RegionList": {
		"Region": [
			{
				"SocketID": str,
				"ISetID": str,
				"PersistentMemoryType": str,
				str: str,
			}
		]
	}
})

def ipmctl_parse_validate(output):
	d = xmltodict.parse(ref_ipmctl_output)
	#print(json.dumps(ref_ipmctl_output_as_dict))
	return IpmctlSchema.validate(d)

ipmctl_parse_validate(ref_ipmctl_output) # test

# ndctl list -RN
ref_ndctl_list_output = """
{
  "regions":[
    {
      "dev":"region1",
      "size":135291469824,
      "align":16777216,
      "available_size":0,
      "max_available_extent":0,
      "type":"pmem",
      "iset_id":3084924584538573346,
      "persistence_domain":"memory_controller",
      "namespaces":[
        {
          "dev":"namespace1.0",
          "mode":"devdax",
          "map":"dev",
          "size":133175443456,
          "uuid":"8879894b-8627-45d6-8926-494202f2d2b8",
          "chardev":"dax1.0",
          "align":2097152
        }
      ]
    },
    {
      "dev":"region3",
      "size":135291469824,
      "align":16777216,
      "available_size":0,
      "max_available_extent":0,
      "type":"pmem",
      "iset_id":-3264587941107234270,
      "persistence_domain":"memory_controller",
      "namespaces":[
        {
          "dev":"namespace3.0",
          "mode":"fsdax",
          "map":"dev",
          "size":133175443456,
          "uuid":"707cee66-f0b6-4a20-8bba-8e84da717a06",
          "sector_size":512,
          "align":2097152,
          "blockdev":"pmem3"
        }
      ]
    },
    {
      "dev":"region0",
      "size":135291469824,
      "align":16777216,
      "available_size":0,
      "max_available_extent":0,
      "type":"pmem",
      "iset_id":-229724740853790174,
      "persistence_domain":"memory_controller",
      "namespaces":[
        {
          "dev":"namespace0.0",
          "mode":"fsdax",
          "map":"dev",
          "size":133175443456,
          "uuid":"fb716272-4401-4e31-8e50-ee57345d1d1d",
          "sector_size":512,
          "align":2097152,
          "blockdev":"pmem0"
        }
      ]
    },
    {
      "dev":"region2",
      "size":135291469824,
      "align":16777216,
      "available_size":0,
      "max_available_extent":0,
      "type":"pmem",
      "iset_id":8849532107707025954,
      "persistence_domain":"memory_controller",
      "namespaces":[
        {
          "dev":"namespace2.0",
          "mode":"fsdax",
          "map":"dev",
          "size":133175443456,
          "uuid":"10a59700-1989-4494-a58b-3389a05fefe4",
          "sector_size":512,
          "align":2097152,
          "blockdev":"pmem2"
        }
      ]
    }
  ]
}
"""

NdctlNamespaceSchema = Schema({
	"dev": str,	
	"mode": Or("fsdax", "devdax", "raw"),
	"size": int,
	str: object,
}) # factored out for usage by ndctl create-namespace call

NdctlSchema = Schema({
	"regions": [
		{
			"dev": str,
			"iset_id": int,
			Optional("namespaces", default=[]): [NdctlNamespaceSchema],
			str: object,
		},
	]
})

NdctlSchema.validate(json.loads(ref_ndctl_list_output))

def ipmctl_regions():
	o = subprocess.run(["ipmctl", "show", "-a", "-o", "nvmxml", "-region"], check=True, text=True, capture_output=True).stdout
	return ipmctl_parse_validate(o)	

def ndctl_regions_and_namespaces(filter_namespace=None):
	cmd = ["ndctl", "list", "-RN"]
	if filter_namespace:
		assert isinstance(filter_namespace, str)
		cmd += ["--namespace", filter_namespace]
	o = subprocess.run(cmd, check=True, text=True, capture_output=True).stdout
	o = json.loads(o)
	return  NdctlSchema.validate(o)

#if __name__ == "__main__":
#	print(ipmctl_regions())
#	print(ndctl_regions_and_namespaces())

def ipmctl_parse_iset_id_hex_representation(s):
	i = int(s, 16)
	return ctypes.c_int64(i).value

def join_impctl_and_pmem_by_iset_id(ipmctl, ndctl):
	ipmctl_ids = set()
	join = {}
	for r in ipmctl["RegionList"]["Region"]:
		i = ipmctl_parse_iset_id_hex_representation(r["ISetID"])
		d = join.get(i, {})
		assert "ipmctl" not in d # detect duplicate iset_id
		d["ipmctl"] = r
		join[i] = d	
		ipmctl_ids.add(i)

	ndctl_ids = set()
	for r in ndctl["regions"]:
		i = r["iset_id"]
		d = join.get(i, {})
		assert "ndctl" not in d # detect duplicate iset_id
		d["ndctl"] = r	
		join[i] = d
		ndctl_ids.add(i)

	assert ndctl_ids == ipmctl_ids

	return join


ref_join = join_impctl_and_pmem_by_iset_id(ipmctl_regions(), ndctl_regions_and_namespaces())
assert len(ref_join) == 4

#if __name__ == "__main__":
#	i = ipmctl_regions()
#	n = ndctl_regions_and_namespaces()
#	j = join_impctl_and_pmem_by_iset_id(i, n)
#	print(json.dumps(j))

def setup_pmem(desired, store):
	ir = ipmctl_regions()
	nr = ndctl_regions_and_namespaces()
	regions_by_id = join_impctl_and_pmem_by_iset_id(ir, nr)

	# strategy:
	# - ensuring region config: if actual region config != desired error out, let the user mess with ipmctl goals
	# - ensuring namespace config: if namespaces do not match destroy them all and recreate them
	
	ConfigSchema = Schema({
		"regions": [{
			"PersistentMemoryType": str,
			"SocketID": str,
			"DimmID": str,
			"namespaces": [{
				"mode": Or("fsdax", "devdax"),
				"size": int,
				"configlabel": str,
			}],
		}],
	})
	ConfigSchema.validate(desired)

	desired_to_existing_regions_mapping = []
	# => ensure all deisred regions match
	for dr in desired["regions"]:
		check_props = [k for k in filter(lambda k: k != "namespaces", dr.keys())]
		found = 0
		found_er = None
		for _, er in regions_by_id.items():
			eri = er["ipmctl"]
			match = {}
			for p in check_props:
				match[p] = eri[p] == dr[p]
			if all(match.values()):
				found += 1
				found_er = er
		assert found >= 0 and found <= 1 # otherwise ambiguous match
		if found == 0:
			raise Exception(f"reconfiguring regions is not supported, user must configure the region manually: \n{json.dumps(dr)}")
		else:
			assert found_er is not None
			desired_to_existing_regions_mapping += [(dr, found_er)]

	# => realize namespaces by destroying all and recreating them
	for (dr, er) in desired_to_existing_regions_mapping:
		ndctl_er = er["ndctl"]
		for ens in er["ndctl"]["namespaces"]:
			#d = Path("/sys/bus/nd/devices") / ens["dev"]
			#assert d.exists()
			subprocess.run(["ndctl", "destroy-namespace", "-f", ens["dev"]], check=True)
			#assert not d.exists()

		for dns in dr["namespaces"]:
			
			# https://docs.pmem.io/ndctl-user-guide/managing-namespaces#fsdax-and-devdax-capacity-considerations
			assert dns["size"] % 4096 == 0
			pfn_metadata_size = (dns["size"] >> 12) * 64
			additional_undocumented_metadata_requirement_possible_label_space = 1 << 22 # it didn't work without this, the number seems clean
			size_with_metadata = dns["size"] + pfn_metadata_size + additional_undocumented_metadata_requirement_possible_label_space
			align = 1 << 24 # todo get this from the region?
			if size_with_metadata % align != 0:
				size_with_metadata += align - (size_with_metadata % align)
			create_cmd = [
				"ndctl", "create-namespace",
				"--region", ndctl_er["dev"],
				"--mode", dns["mode"],
				"--map", "dev",
				"--size", f"{size_with_metadata}",
				# align is not the --align parameter (that defaults to 2MiB) but it's the alignment requirement of devdax / fsdax namespaces
			]
			st = subprocess.run(create_cmd, capture_output=True, text=True)
			if (st.returncode != 0):
				print(st.stderr)
				print(st.stdout)
			st.check_returncode()
			o = json.loads(st.stdout)
			o = NdctlNamespaceSchema.validate(o)
			assert o["mode"] == dns["mode"]
			assert o["size"] >= dns["size"]
			assert o["size"] < dns["size"] + align
			# for some reason ndctl create-namespace doesn't return exactly the same schema as ndctl list :(
			# => list again to get the /dev/ device
			l = ndctl_regions_and_namespaces(filter_namespace=o["dev"])
			Schema({
				"regions": And(lambda r: len(r) == 1, [{
					"namespaces": And(lambda n: len(n) == 1, [{
						"dev": o["dev"],
						"blockdev" if o["mode"] == "fsdax" else "chardev": str,
						str: object,	
					}]),
					str: object
				}])
			}).validate(l)
			o = l["regions"][0]["namespaces"][0]

			labelvalue = Path("/dev/")
			if o["mode"] == "fsdax":
				labelvalue = labelvalue / o["blockdev"]
				assert labelvalue.is_block_device()
			elif o["mode"] == "devdax":
				labelvalue = labelvalue / o["chardev"]
				assert labelvalue.is_char_device()
			else:
				raise Exception(f"unexpected mode {o['mode']}, schema should have prohibited this")
			
			store.add(dns["configlabel"], str(labelvalue))

