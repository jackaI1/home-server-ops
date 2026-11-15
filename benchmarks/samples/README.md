# Saved sample output

`mac-psync-smoke/` is real output from `python -m benchmarks run`, run on a Mac
with fio 3.43, the `psync` engine, buffered I/O and a 16 MB test file for one
second per run. It is only there so the tests can parse and plot real fio JSON
without a Linux disk. It is not a measurement of any disk I own.

The `raw/` files are the wrapped fio results. The path to the test file was
changed to `/srv/bench/` so that no home folder name is stored in the repository.
