```bash

# install dependencies
# ./requirements.txt
# ipmctl
# ndctl
# bpftrace

# read through ./intermediate_presentation
#
# => build the ZFS tree in the locations specified in the 'config' dicts
#
# Debian:
# ./autogen.sh
# ./configure --with-linux=/lib/modules/$(uname -r)/source --with-linux-obj=/lib/modules/$(uname -r)/build
# make -j$(nproc)
#
# => adjust hardware in the config structs to match your device names / setup

# execute benchmarks & collect results in ./results
# (pdb to get some context if it crashes, logging isn't where it should be yet)
python3 -m pdb intermediate_presentation

# postpocessing
jupyter-notebook
# => execute the 'intermediate_presentation*' ipynvb books, they render into ./postprocess_results

```
