#!/usr/bin/env bash
set -u

ROOT=/home/annya/playground/jeandle/jeandle/jeandle-llvm
OUT=/home/annya/playground/jeandle/perf-results/2026-10-26-javatype-cache-reuse/diagnostics
OPT="$ROOT/build/build-ninja-profiling/bin/opt"
TEST="$ROOT/llvm/test/Jeandle/java-type-cache-reuse"

mkdir -p "$OUT"
cd "$ROOT"

run() {
  local name=$1
  shift
  printf '%q ' "$@" >"$OUT/$name.command"
  printf '\n' >>"$OUT/$name.command"
  "$@" >"$OUT/$name.log" 2>&1
  echo $? >"$OUT/$name.rc"
}

run tce-same-block \
  "$OPT" -S -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='type-check-elimination,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce.cblog" \
  "$TEST/tce-same-block.ll"

run tce-shallow \
  "$OPT" -S -jeandle-java-type-stats \
  -passes='type-check-elimination,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce.cblog" \
  "$TEST/tce-shallow.ll"

run tce-zero-overlap \
  "$OPT" -S -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='type-check-elimination,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce.cblog" \
  "$TEST/tce-zero-overlap.ll"

run tce-deep \
  "$OPT" -S -jeandle-java-type-stats \
  -passes='type-check-elimination,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce.cblog" \
  "$TEST/tce-deep.ll"

run recover-shallow \
  "$OPT" -S -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='recover-type-info,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/recover.cblog" \
  "$TEST/recover-shallow.ll"

run x01-cross \
  "$OPT" -disable-output -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='type-check-elimination,print<java-type-analysis>,recover-type-info,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce-recover.cblog" \
  "$TEST/tce-recover-cross-pass.ll"

run x01-local \
  "$OPT" -disable-output -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='type-check-elimination,print<java-type-analysis>,jeandle-java-type-cache-boundary,recover-type-info,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce-recover.cblog" \
  "$TEST/tce-recover-cross-pass.ll"

run x03-cross \
  "$OPT" -disable-output -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='type-check-elimination,print<java-type-analysis>,recover-type-info,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce-recover.cblog" \
  "$TEST/tce-fold-recover.ll"

run x03-local \
  "$OPT" -disable-output -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='type-check-elimination,print<java-type-analysis>,jeandle-java-type-cache-boundary,recover-type-info,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce-recover.cblog" \
  "$TEST/tce-fold-recover.ll"

run x02-tce-cff \
  "$OPT" -disable-output -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='type-check-elimination,print<java-type-analysis>,constant-field-folding,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce.cblog" \
  "$TEST/tce-cff-cross-pass.ll"

run x04-cff-tce \
  "$OPT" -disable-output -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='constant-field-folding,print<java-type-analysis>,type-check-elimination,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/tce.cblog" \
  "$TEST/tce-cff-cross-pass.ll"

run cff-nonexact \
  "$OPT" -S -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='constant-field-folding,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/cff-nonexact.cblog" \
  "$TEST/cff-nonexact.ll"

run x06-cff-modify-tce \
  "$OPT" -disable-output -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='constant-field-folding,jeandle-java-type-cache-boundary,type-check-elimination,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/cff-modify-tce.cblog" \
  "$TEST/cff-modify-tce.ll"

run x05-recover-cha \
  "$OPT" -S -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='recover-type-info,jeandle-java-type-cache-boundary,cha-devirtualization,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/recover-cha.cblog" \
  "$TEST/recover-cha-boundary.ll"

run cha-shallow \
  "$OPT" -S -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -passes='cha-devirtualization,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/cha-reuse.cblog" \
  "$TEST/cha-shallow.ll"

run cha-deep \
  "$OPT" -S -jeandle-java-type-stats \
  -passes='cha-devirtualization,print<java-type-analysis>' \
  -jeandle-vm-callback-log="$TEST/Inputs/cha-reuse.cblog" \
  "$TEST/cha-deep.ll"

run x07-production-pea-off \
  "$OPT" -disable-output --jeandle --jeandle-pea-iterations=0 \
  -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -jeandle-vm-callback-log="$TEST/Inputs/pipeline-tce-cff.cblog" \
  "$TEST/x07-production-pipeline.ll"

run existing-cff-cache-reuse \
  "$OPT" -disable-output -jeandle-java-type-stats -jeandle-verify-java-type-cache \
  -passes='function(constant-field-folding,print<java-type-analysis>)' \
  -jeandle-vm-callback-log="$ROOT/llvm/test/Jeandle/constant-field-folding/Inputs/cache-reuse.cblog" \
  "$ROOT/llvm/test/Jeandle/constant-field-folding/cache-reuse.ll"

run selective-invalidation-selective \
  "$OPT" -disable-output -verify-each -jeandle-java-type-stats \
  -passes='function(type-check-elimination,cha-devirtualization),print<java-type-analysis-summary>' \
  -jeandle-vm-callback-log="$ROOT/llvm/test/Jeandle/java-type-analysis/Inputs/selective-invalidation.cblog" \
  "$ROOT/llvm/test/Jeandle/java-type-analysis/selective-invalidation.ll"

run selective-invalidation-full \
  "$OPT" -disable-output -verify-each -jeandle-java-type-force-full-invalidation \
  -jeandle-java-type-stats \
  -passes='function(type-check-elimination,cha-devirtualization),print<java-type-analysis-summary>' \
  -jeandle-vm-callback-log="$ROOT/llvm/test/Jeandle/java-type-analysis/Inputs/selective-invalidation.cblog" \
  "$ROOT/llvm/test/Jeandle/java-type-analysis/selective-invalidation.ll"
