#!/bin/sh
set -eu
TOP=/home/annya/playground/jeandle/jeandle
RUN=$TOP/benchmarks/v2-null-edge-optimization-20261103
SRC=$TOP/jeandle-llvm-null-edge-v2-20261103
cd "$RUN"
trap 'printf "pipeline failed\n" > "$RUN/FAILURE"' EXIT
test -f TEST_SUCCESS
cd "$SRC"
git diff --check
git add llvm/include/llvm/Analysis/Jeandle/LVINullEdgeOracle.h llvm/lib/Analysis/Jeandle/LVINullEdgeOracle.cpp llvm/include/llvm/Analysis/Jeandle/JavaTypeAnalysis.h llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp llvm/include/llvm/Analysis/Jeandle/JavaTypeAnalysisStats.h llvm/lib/Analysis/Jeandle/JavaTypeAnalysisStats.cpp llvm/lib/IR/Jeandle/JavaType.cpp llvm/unittests/IR/JavaTypeQueryTest.cpp llvm/docs/JeandleNullEdgePrefilter.md
git commit -F "$RUN/commit-message.txt"
git diff 31bdeb46178c952ff5b471d5f49ee2358e3dd0de HEAD > "$RUN/optimization.patch"
git rev-parse HEAD > "$RUN/candidate-commit.txt"
cd "$RUN"
for version in base null; do cp -p ../v1-reuse-optimization-20261103/replay-$version .; done
cp -p ../v1-reuse-optimization-20261103/replay-candidate replay-prior
python3 build.py
for scenario in same cross-unique cross same-edit other-edit; do ./replay-candidate "$scenario" cached 2 diagnostic; done
printf 'tests and native smoke passed; settling before serial sampling\n'
sleep 20
python3 run.py
python3 audit.py
printf 'complete\n' > PIPELINE_SUCCESS
trap - EXIT
