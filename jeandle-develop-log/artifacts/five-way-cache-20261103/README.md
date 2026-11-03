# Five-way JavaType cache retest, 2026-11-03

Extends four-way-cache-20261031 without replacing old data. Server:
annya@100.122.220.40:/home/annya/playground/jeandle/jeandle/benchmarks/five-way-cache-20261103

raw/base/null/v2 retain EXACT historical replay and opt binaries (manifest asserts
all four version records against the previous experiment before sampling).
new: feat/javatype-final-cache, 616395cc384863d38fb6bb993b4b10a10f599dce,
verified against origin branch before starting. Separate detached worktree:
jeandle-llvm-final-cache-bench-20261103, Release/O3/NDEBUG, same GCC toolchain,
assertions OFF, static linking, X86. See build.log and build metadata.
The intervening PEA sync is included in the branch, but no measured pipeline runs PEA.

Adaptation for new API ONLY: driver-new.cpp uses JavaTypeCache and
getCachedJavaType; constructor StableOracleEpoch and notification sequence unchanged.
JavaTypeCacheReuseTestSupportNew.h retains fixture construction exactly, removes
unused legacy cache members/helper methods because their API was deleted.
Native input SHA256 must match 2026-10-31 fixtures for all versions.
Full JavaType differential verification uses fresh DT/AC/LVI and the corresponding
version's uncached getJavaType, requires class 22, 2 batches x 32 queries per case.
Five opt versions must produce byte-identical output IR, and each version's
verification and diagnostic IR must be byte-identical. No diagnostics in timing.

Same CPU 8 / sibling 9, no system settings changed. Per scenario: 3 warmup A/A
pairs, 15 measured base/base pairs; 3 warmup five-way rounds, 31 measured rounds,
randomized serial order, seed 20261103. Native separately calibrates batch counts
to ~360ms CPU; all formal CPU samples must be >=200ms. 4000-resample bootstrap
95% CI must exceed same-case A/A absolute-change P95 for a performance verdict.
10 cases, 1850 formal samples. 5 opt full-process cases measured in ms;
5 native query cases in microseconds per identical 32-query batch. Never combine.

Reproduce after building the isolated opt/llvm-config: copy the four historical
replay binaries into this folder; python3 build.py; python3 run.py; python3 audit.py.
results/ must not exist when starting. New engine is measured against all four
controls in this session; do not splice medians from the previous report.
SUCCESS means runner completed; audit.json records post-run validation.
Large opt diagnostic and verification outputs and binaries remain on server.

Archived original opt inputs: opt-inputs/ on server; opt-inputs.tgz locally.
The archive contains the opt-inputs/ directory. Restore its contents to
/tmp/null-edge-workloads-20261030/ before reproducing, or change run.py's
cases.json path and update the absolute input/callback paths in that JSON.
To rerun without overwriting data, copy scripts, fixtures and replay binaries
into a fresh sibling benchmark directory; do not copy results/.
Local results have also been checked independently against samples.jsonl:
all 10 cost medians, all 100 paired median changes, sample count/min duration,
and runner/driver/fixture hashes agree.
