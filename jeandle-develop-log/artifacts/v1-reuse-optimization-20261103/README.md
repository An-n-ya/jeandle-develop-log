# V2 towards V1: safe path reuse and entry-select fast path

Server source: annya@100.122.220.40:/home/annya/playground/jeandle/jeandle/jeandle-llvm-v1-reuse-20261103
Branch: codex/javatype-v1-reuse
Parent: feat/javatype-final-cache, 616395cc384863d38fb6bb993b4b10a10f599dce.
See candidate-commit.txt for the measured final commit.
Published as one commit 31bdeb46178c952ff5b471d5f49ee2358e3dd0de on
feat/javatype-final-cache. The code tree is identical to measured 7425b617.
See publication.json and squashed-commit-message.txt.

Changes:

* Facts additionally retains completed accumulated `(Value,Block)` paths for
  single-value argument and entry-select queries. Admission requires a stable
  oracle epoch and a function whose blocks fit the full facts budget. Uncut
  cycles prevent publication. Tight-budget, PHI and other forwarding queries
  retain their existing query-local traversal and edge caches.
* Entry-block select value typing reuses the base solver's completed result;
  valid SSA puts operand definition points in entry, where CFG facts are empty.
  Non-entry select refinement is unchanged.
* Avoid retaining both constituent edges and their completed path on the same
  query. Edge computations remain counted; path hits have separate counters.
* Cache the block count across unchanged CFG epochs. Any CFG change or clear
  resets admission metadata. Oracle/non-CFG notifications preserve only the
  count, and still invalidate every path/edge/Final type result.

We deliberately retain V2's conservative IR/oracle invalidation: even unrelated
edits can affect bounded LVI reasoning. V1's unrelated-edit retention and unsafe
freeze/cycle shortcuts have not been restored.

Validation: unit-tests.log and unit-results.json; lit-tests.log. The final suite
contains 84 unit tests and 63 lit regressions. A single pre-existing statistics
test was updated for the removed entry-select operand query. recover-shallow.ll
now expects one accumulated-path entry instead of two edge entries per query.
Other original assertions remain, and five new tests cover path prefixes,
budget changes, irreducible cycles, entry/late selects and CFG expansion.

Performance: benchmark/ contains reproducible driver/build/run/audit scripts.
On server these scripts reside directly in:
/home/annya/playground/jeandle/jeandle/benchmarks/v1-reuse-optimization-20261103
Four arms measured in one session: base=V1; null=V1+null-edge; new=616395 V2;
candidate=final optimization commit. Three controls reuse exact historical opt
and replay binaries and check them against five-way-cache-20261103/manifest.
All original native/opt input hashes must match the previous experiment.
31 randomized serial rounds, 3 warmups; 15 base/base A/A pairs plus 3 warmup
pairs per scenario. CPU 8, sibling 9, no system setting changes. Native batch
counts calibrated per version to ~360ms. Opt full-process CPU ms and native
CPU microseconds per identical 32-query batch must never be mixed.
95% bootstrap CI (4000 resamples) must exceed same-case A/A absolute-change P95,
and all formal CPU samples must be at least 200ms, for a performance verdict.
Ten scenarios, 1540 formal samples. Tests, verification and diagnostics run
outside timing. Input/IR and binary-hash audits must pass.

The partial first iteration (bed0f6704352) is retained separately on server;
its samples are NOT mixed into the final measured summary. The final iteration
also caches the block count to eliminate repeated linear Function::size walks.

before/ stores the relevant initial source files; after/ stores the final
source snapshots. optimization.patch applies all commits against 616395cc.
results/ stores only the final iteration. Larger opt IR/stderr and all replay
binaries remain on server. Original opt inputs are archived in the previous
five-way-cache-20261103/opt-inputs.tgz; run.py uses the original /tmp paths.
For a fresh measurement, copy scripts/fixtures/binaries into a new sibling
benchmark directory without results/, then run build.py, run.py and audit.py.
