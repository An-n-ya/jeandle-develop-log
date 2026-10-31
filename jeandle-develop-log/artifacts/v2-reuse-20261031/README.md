# V2 reuse microbenchmarks (2026-10-31)

Server directory: /home/annya/playground/jeandle/jeandle/benchmarks/v2-reuse-20261031
Production source stays unmodified. V2 commit: ad38f632672c881708d0894acf56b72414c095f2.

## Inputs and sequence

The existing JavaTypeCacheReuseTestSupport.h creates a guard fixture: untyped obj,
check_instanceof(22,obj), 32 prefix blocks and 16 contexts. It is emitted as four
.ll files; every mode parses the corresponding .ll before measurement.

Each independent batch resets JavaType cache and LVI, then performs 32 queries.
- same: repeatedly query obj at path32 terminator. One cold, 31 warm queries.
- cross: query path32..path47 twice, without any mutation.
- same-edit: query path32 repeatedly; before queries 2..32 notify and change the
  operand of an unrelated add in path32, then clear LVI.
- other-edit: same sequence but edit a separate add in the fail block, outside
  the queried true-path ancestor region. CFG and DT do not change.

Each .ll is a fixture input, not a transformation pipeline. The native driver
controls query/invalidation ordering explicitly. The reference mode executes the
original getJavaType, not old V1 cache. All modes must produce klass 22; diagnostic
runs compare full JavaType equality with original getJavaType using fresh DT,
AssumptionCache and LVI for every query. Counters and differential checks are off
in timed runs. All diagnostic modes run before that scenario's timed samples.

Modes:
- cached: V2 default StableOracleEpoch and selective invalidation.
- nofinal: same V2 solver, Final disabled.
- full: V2 with full aggregate cache clear instead of selective notification on
  edits. For no-edit scenarios it is intentionally identical to cached.
- reference: original noncached getJavaType, same LVI maintenance on edits.

## Build

Use the server tools/bin/g++ and the existing V2 static libs. The existing
libLLVM.so is stale and does not contain V2 symbols; do not link this driver to it.

```sh
src=/home/annya/playground/jeandle/jeandle/jeandle-llvm
b=$src/build/build-ninja-release
/home/annya/playground/jeandle/jeandle/tools/bin/g++ driver.cpp \
  -I$src/llvm/unittests/IR $($b/bin/llvm-config --cxxflags) -O3 -DNDEBUG \
  $($b/bin/llvm-config --ldflags --link-static --libs analysis asmparser core --system-libs) \
  -o replay
./replay same cached 2 diagnostic
python3 run.py
```

run.py requires a fresh results/ directory. It runs diagnostic generation before
pilot/timing so each .ll input exists. replay can then consume those .ll files
independently, e.g. ./replay other-edit cached 1000 timing.

## Measurement

Adapted from codex/null-edge-benchmark, not a direct execution of its opt-only
harness. Reuses its interval() bootstrap implementation (4000 resamples).
CPU affinity 8, SMT sibling 9; no system settings changed. Serial randomized A/B
order, 3 warmup pairs, 31 measured pairs, cached/cached A/A per scenario. Judge
95% CI against A/A absolute paired-change P95 and require all native CPU samples
>=200ms. Raw observations, source/binary/input hashes, batch counts, diagnostics,
summaries and SUCCESS are retained in results/.

Native getrusage CPU interval excludes IR creation/parsing and includes batch
cache reset, queries, edit notifications, edits and LVI clears. Modes use separately
calibrated batch counts to achieve ~360ms samples, and results compare CPU per
identical 32-query batch. This is normalized query-sequence throughput, NOT paired
whole-opt CPU on equal-sized modules and NOT JVM end-to-end performance.

The fixture is reused within a process, with caches reset each batch. This
controls the query sequence and warm fraction but does not model fresh function
allocation/cache locality. Only one depth/width and one placement of unrelated
edits are tested. Mock VM callbacks use a simple hierarchy. Results cannot be
extrapolated to general JVM workloads.

results-generator-only-discarded/ contains an aborted initial prototype which
used generated IR directly rather than reparsing .ll. It is excluded from all
final results. Self A/A detects local noise, not exclusive CPU ownership.

## Unique-context supplement

`driver-unique.cpp` adds `cross-unique`: 32 distinct contexts, each queried once.
Build with the same flags to `replay-unique`, then run `python3 run-unique.py`
after the primary suite finishes. It has independent A/A calibration and writes
`results-unique/`. Both result directories must be fresh on rerun.
