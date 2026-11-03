#!/bin/sh
set -eu
TOP=/home/annya/playground/jeandle/jeandle
RUN=$TOP/benchmarks/v1-reuse-optimization-20261103
SRC=$TOP/jeandle-llvm-v1-reuse-20261103
cd "$RUN"
trap 'printf "pipeline failed\n" > "$RUN/FAILURE"' EXIT
printf 'waiting for independent build\n'
while [ ! -f BUILD_SUCCESS ]; do sleep 5; done
cd "$SRC"
git diff --check
cmake --build build --target opt llvm-config JavaTypeQueryTests FileCheck not count split-file --parallel 12
build/unittests/IR/JavaTypeQueryTests --gtest_output=json:"$RUN/unit-results.json" > "$RUN/unit-tests.log" 2>&1
build/bin/llvm-lit -j 4 -v build/test/Jeandle/java-type-analysis build/test/Jeandle/java-type-cache-reuse build/test/Jeandle/type-check-elimination build/test/Jeandle/cha-devirtualization > "$RUN/lit-tests.log" 2>&1
git add llvm/include/llvm/Analysis/Jeandle/JavaTypeCache.h llvm/lib/Analysis/Jeandle/JavaTypeCache.cpp llvm/lib/IR/Jeandle/JavaType.cpp llvm/unittests/IR/CachedJavaTypeTest.cpp llvm/docs/JeandleJavaTypePathReuse.md llvm/test/Jeandle/java-type-cache-reuse/recover-shallow.ll
git commit -m 'perf(jeandle): reuse bounded path facts and entry select base types'
git diff 616395cc384863d38fb6bb993b4b10a10f599dce HEAD > "$RUN/optimization.patch"
git rev-parse HEAD > "$RUN/candidate-commit.txt"
cd "$RUN"
for version in base null new; do cp -p ../five-way-cache-20261103/replay-$version .; done
python3 build.py
printf 'tests passed; settling before serial sampling\n'
sleep 20
python3 run.py
python3 audit.py
printf 'complete\n' > PIPELINE_SUCCESS
trap - EXIT
