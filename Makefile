.PHONY: plots

NOTEBOOKS ?=

NOTEBOOKS += app_benchmarks__v4.1.ipynb
NOTEBOOKS += comparison_zil_overhead_lwb_vs_pmem__v3.2.ipynb
NOTEBOOKS += motivating_fio_benchmark__v3.1.ipynb
NOTEBOOKS += ncommitters_scalability__v5.2.ipynb
NOTEBOOKS += zillwb_latency_analysis__v4.ipynb

plots:
	rm -r postprocess_results
	mkdir postprocess_results
	for nb in $(NOTEBOOKS); do \
		papermill $$nb -; \
	done;
	echo results in $$(readlink -f ./postprocess_results)
