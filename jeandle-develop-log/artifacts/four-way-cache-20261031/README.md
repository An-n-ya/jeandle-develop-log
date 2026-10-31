# Four-way JavaType cache comparison

Directory: /home/annya/playground/jeandle/jeandle/benchmarks/four-way-cache-20261031
Extends null-v2-comparison-20261031 with a truly noncached JavaType reference.

Versions:
raw: original V1 commit ac545bb21e8931152ad9149e01f8304b214dbd91, no cross-query
     JavaType cache. opt uses -jeandle-disable-java-type-cache=true; native
     BENCH_REFERENCE calls original getJavaType directly, not a cache wrapper.
base: same commit, existing V1 CachedJavaType enabled.
null: old CachedJavaType + default null-edge optimization on
      codex/null-edge-benchmark, e5475bb0df4671302665c6986e762bf892c3c98a.
      Optional block-level LVI remains OFF.
v2: feat/javatype-selective-invalidation, ad38f632672c881708d0894acf56b72414c095f2.

All production worktrees remain unchanged. Source driver selects API via
BENCH_REFERENCE or BENCH_USE_V2, linked separately to each version's static libs.
CLI positional mode stays 'cached' for compatibility with the runner; this word
DOES NOT enable a JavaType cache in the BENCH_REFERENCE binary.

Raw still uses ordinary DT/LVI analysis. Raw native has no JavaType cache
invalidation; edits maintain LVI identically. Timed intervals include per-batch
resets, queries, notifications where applicable, edits and LVI maintenance.
Correctness mode checks each full JavaType against original getJavaType with
fresh DT/AC/LVI and requires class 22. V1 SkipVerification is a failure.

Inputs: same, cross-unique, cross, same-edit, other-edit .ll fixtures, respectively
32 same-key queries; 32 distinct contexts once; 16 contexts twice; same-block
unrelated add edits; other-block unrelated add edits. Fixed class-22 guard,
32 prefix blocks. Every batch starts with cleared JavaType/LVI caches. Inputs
are parsed before native timing. Each version calibrates batch count to ~360ms
and reports CPU per identical 32-query batch. IR allocation is reused across
batches; this is a microbenchmark, not end-to-end production performance.

The original five 1024-function opt workloads are also rerun on all four modes.
They measure entire process CPU including fresh parsing and startup, not native
query intervals. Three cached opt binaries and the baseline opt with bypass flag
must produce identical optimized IR; separate diagnostic/verification IR must
also agree. Timed opt runs have no output, statistics or verification flags.

Fixed CPU 8, sibling 9, no system setting changes, LD_LIBRARY_PATH removed.
Per workload: 3 warmups + 15 V1/V1 A/A pairs; 3 warmups + 31 randomized four-way
rounds, all serial. Pairwise median changes and 95% CI use the old benchmark's
4000-bootstrap implementation. CI must cross beyond the row's A/A absolute
change P95 and all CPU samples must be >=200ms to make a performance verdict.
All four versions are measured in this session, not spliced from old medians.

Reproduce: python3 build.py; python3 run.py. results/ must be a fresh directory.
Uses existing /tmp/null-edge-workloads-20261030/cases.json and callback inputs,
plus the baseline/native .ll fixtures present in this directory. See build.py
for exact compiler commands (tools/bin/g++, Release O3/NDEBUG, static linking).
Do not compile or run other benchmark jobs during measurement.

results/ contains manifest (versions, hashes, input hashes, CPU settings, batch
counts), raw AA/warmup/comparison samples, diagnostic data, opt IR/stderr,
summary.json and SUCCESS. Binary hashes are rechecked at completion.

Do not sum or average native and opt time. raw is original uncached V1 engine,
not V2 with caches disabled and not V2 with Final disabled. The old versions have
known unrelated precision/correctness tests that V2 fixes; performance here does
not justify blindly restoring old semantics.
