## Python3 Venv Dependencies

(Haven't gone through the effort of splitting them up yet)


```
# Fedora
sudo dnf install parted-devel
```

```
python3 -m venv .venv && \
    source .venv/bin/activate && \
    pip install -r ./requirements.txt
```

## Plots

We use Jupyter notebooks.

**Interactive / Modification**

```
cd .
jupyter-notebook
# => web browser opens, start opening notebooks, all committed ones should work
# => check Makefile for the one we use to produce the plots in the thesis
```

**Batch / Building**

We use `papermill` (installed via `requirements.txg`) to batch-execute the Jupyter notebooks.

```bash
make plots
```

PDFs are available in`./postprocess_results`.


## Running Benchmarks / Producing new `./results`

TODO version / dependency pinning

```bash
# install dependencies
# ipmctl
# ndctl
# bpftrace

 Build the ZFS tree in the locations specified in the 'config' dicts
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
```
