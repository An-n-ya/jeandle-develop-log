# V2 null-edge optimization and four-way performance retest

Parent: feat/javatype-final-cache, 31bdeb46178c952ff5b471d5f49ee2358e3dd0de.
Server source: /home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-v2-20261103
Published to feat/javatype-final-cache as 6ec57ff43381edf405ba11cdf3ff3a2b5c3b6e7e.
Working branch: codex/javatype-null-edge. See publication.json and candidate-commit.txt.

The optional LVINullEdgeQuery state is scoped to one top-level query. The typed
LVINullEdgeOracle alone uses it; generic/custom callbacks and existing one-arg
oracles remain unfiltered. JavaTypeAnalysis explicitly opts in. No IR/oracle
invalidation rule changes. Uncertain definitions/uses, cycles, work/depth limits
fall back to the original LVI edge predicate. PHI/select use a conservative OR
of possible null sources, preserving cases the old filter could miss. Unsafe
freeze normalization is unchanged. No block-level LVI or new oracle-call cap.
The shared facts solver also short-circuits an absorbing unknown union.
See after/JeandleNullEdgePrefilter.md for the full scope and contract.

Seven new unit tests cover negative argument/select cases, structural/indirect
null proofs, select/PHI fallbacks, returned aliases and integer tests, unproven
freeze, scan/depth limits, and fresh query state after IR/LVI maintenance.
91 unit tests passed. Expanded lit scope: 145 passed, one unsupported test
(recover-fixpoint-oscillation.ll requires asserts, disabled in Release); see lit-tests.log for the exact result.
The backend-dependent clone-expansion test and OSR null-edge regressions passed.
Cache verification uses an unfiltered oracle, and native differential checks
use fresh DT/AC/LVI with the unfiltered reference engine.

Four arms: base=V1, null=old V1+null-edge, prior=previous V2 path reuse,
candidate=this optimization. prior reuses the exact measured 7425b617 binary;
its code tree is identical to published 31bdeb46 (publication.json in the prior
optimization artifact records that verification). All three controls are checked
against the prior run's manifest; all input hashes must remain identical.

31 randomized serial rounds per case plus 3 warmups. 15 base/base A/A pairs plus
3 warmup pairs. CPU 8, sibling 9, unchanged governor/services, no LD_LIBRARY_PATH.
Native calibrates batch counts to ~360ms and measures CPU cost per fixed 32
queries, excluding fixture construction/parse. Opt measures a full fresh process.
Do not combine those metrics. 4000-resample bootstrap CI must exceed the case's
A/A absolute-change P95 and every formal CPU sample must be >=200ms for a verdict.
Ten cases, 1540 formal samples. Diagnostics/verification are outside timing.

The native driver explicitly opts in with one LVINullEdgeQuery per query,
matching production JavaTypeAnalysis. Only the candidate has that API. Outer
oracle callback counts are not actual LVI calls: lvi_calls/prefilter_skips report
the latter mechanism, and counters are disabled in timing. Production diagnostic
summaries expose the same requests/structural/filter/LVI/limit counters.

benchmark/ stores build/run/audit/ablation scripts and identical fixtures. On
server they live directly in benchmarks/v2-null-edge-optimization-20261103.
results/ contains final samples, manifest, summary, diagnostics and audit.
ablate.py runs AFTER measurement, comparing filtered and unfiltered opt IR and
LVI calls with the same candidate binary; its data is excluded from timing.
Large opt output IR/stderr and replay binaries remain on server. Original opt
inputs remain at /tmp/null-edge-workloads-20261030 and are archived in the earlier
five-way-cache-20261103/opt-inputs.tgz. Reproduce in a fresh sibling directory,
without copying results/, then build.py, run.py, audit.py and ablate.py.
