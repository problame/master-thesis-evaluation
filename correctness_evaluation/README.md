This file describes how to run the code coverage measurement.
The data used for the table in the thesis is in `coverage_data.tar.bz2`.

---

* make sure the udev rules and `zvol_id` is installed
    * `scripts/zfs-helpers.sh -i` is your friend
    * we didn't change anything about that, so it's fie
      to reuse the tools between our tree and upstream

* provision two 1GiB sized /dev/pmem0 and /dev/pmem1 namespaces

* checkout two git worktrees:
    * `~/zil-pmem/upstream-gcov` pointing to the branch `problame/master-thesis-archive/evaluation/coverage/zil-pmem-mergebase-plus-gcov_bash`
    * `~/zil-pmem/gcov-kernel` pointing to the branch   `problame/master-thesis-archive/evaluation/coverage/zil-pmem`

Run the following script (never tested, ran them manually)

```bash
for checkout in ~/zil-pmem/upstream-gcov ~/zil-pmem/gcov; do

    pushd $checkout

    ./autogen.sh
    ./configure --with-linux=/home/cs/linux-5.10.38 --enable-code-coverage
    make -j$(nproc)

    mkdir ./gcov_out
    ./gcov.bash userspace ./gcov_out
    ./gcov.bash kernel ./gcov_out

    popd

done
```

* manually inspect `~/zil-pmem/*/gcov_out/*/log.txt`
    * there is one ZIL-PMEM-specific crash (SIGSEGV) that happens when debug assertions are enabled.
      (ensuring ZIL header is zero)
      Most likely due to stack overflow, haven't had time to investigate yet.

* manually extract the line coverage data from the lcov html report in `~/zil-pmem/*/gcov_out/*/zfs*-coverage/index.html


