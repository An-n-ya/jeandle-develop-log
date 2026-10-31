# V1 / V1 NullEdge / V2 unified comparison

Server: /home/annya/playground/jeandle/jeandle/benchmarks/null-v2-comparison-20261031

Versions:
- base: codex/null-edge-baseline, ac545bb21e8931152ad9149e01f8304b214dbd91.
- null: codex/null-edge-benchmark, e5475bb0df4671302665c6986e762bf892c3c98a.
  Default S1/S2/S3/S4-level1/S5 implementation. Optional block-level LVI stays OFF.
- v2: feat/javatype-selective-invalidation, ad38f632672c881708d0894acf56b72414c095f2.

No production branch is edited. Standalone static drivers are built separately
against each version's include trees and libraries. Common fixture header is a
snapshot of the existing V2 JavaTypeCacheReuseTestSupport.h. All versions run the
same sequence and source driver with only the cache API selected at compile time.

## Reproduce

python3 build.py
python3 run.py

run.py needs a fresh results directory and existing five native .ll fixtures and
/tmp/null-edge-workloads-20261030/cases.json (including input/callback paths).
It imports interval() from the benchmark branch's benchmark.py. Do not run
compilation or other tests concurrently with timing. Full run takes several
minutes. Before rerunning, preserve old results rather than overwriting them.

build.py uses V2 llvm-config (the baseline did not build llvm-config), rewrites
include/library directories for each build, and links that build's own static
libraries. Compiler is the shared tools/bin/g++, Release O3/NDEBUG, no RTTI.
BENCH_USE_V2 only selects the production cache API. No optional null-edge flags
are overridden. LD_LIBRARY_PATH is removed by run.py.

## Two separate metrics

1. native cases: same, cross-unique, cross, same-edit, other-edit.
   Fixed fixture: class-22 guard, 32 prefix blocks, 16 contexts (32 for unique).
   Each batch resets JavaType and LVI caches, performs 32 queries, and optionally
   notifies/edits unrelated add operands before queries 2..32. Same-edit's add
   is in the queried block. Other-edit's add is in the fail block outside the
   queried ancestor region. No CFG changes. cross visits 16 contexts twice;
   cross-unique visits 32 distinct contexts once. Outputs are expected class 22.
   Every mode parses its .ll before the measured interval. Diagnostics compare
   full types with original getJavaType using fresh DT/AC/LVI for each query;
   V1's SkipVerification must be false. Timed runs disable optional counters and
   reference recomputation. Native user+system CPU per identical 32-query batch
   includes cache resets, invalidations, edits and LVI clears, excludes IR setup.
   Mode-specific batch counts target ~360ms samples, so this is normalized
   throughput, not equal-sized whole-process CPU or production JVM performance.

2. opt cases: original deep-static, wide-static, leaf-static, tce-cha, virtual-cfg,
   1024 independent functions each. The three original opt binaries are run
   directly, fresh process/IR each sample. Measurement is whole-process CPU
   user+system including parsing/startup/exit, with output, stats and verification
   off. Separate verification and stats phases precede timing; each version's
   verification IR must match its diagnostic IR, and all three optimized IR
   outputs must match byte-for-byte.

Never sum or average native and opt milliseconds. Table rows are comparable
within a workload; percentages are paired within the same measurement protocol.
Original getJavaType (uncached reference) is used only as a correctness oracle;
it is NOT the base column. base is old CachedJavaType with its existing caches.

## Statistics and provenance

CPU 8, sibling 9; no governor or system settings changed. Per workload 15 measured
A/A pairs on base, 3 warmups; then 31 measured randomized triples (base/null/v2),
3 warmups. Pairwise median percentage changes and bootstrap 95% CI reuse the
existing 4000-bootstrap interval implementation. A/A absolute change P95 is the
noise floor for that row. All AA/comparison CPU samples must be >=200ms for a
performance verdict. Short runs are explicitly inconclusive, not discarded.

results contains manifest (commits, binary/input hashes, batch counts, affinity,
governor), samples.jsonl (including warmups), diagnostics.json, opt IR/stderr,
summary.json and SUCCESS. End-of-run binary hashes are checked. Source trees,
old results and system services remain unchanged.

Limits: one synthetic guard/depth/placement, mock VM hierarchy; repeated fixture
allocation locality differs from production. V2 includes semantic/precision
changes and old versions have known unrelated regression-test failures, so
speed alone is not a reason to restore all old implementation behavior.
