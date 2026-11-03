#!/bin/sh
set -eu
cd /home/annya/playground/jeandle/jeandle/benchmarks/five-way-cache-20261103
trap 'printf "pipeline failed\n" > FAILURE' EXIT
printf 'waiting for independent build\n'
while [ ! -f BUILD_SUCCESS ]; do sleep 5; done
printf 'build complete; preparing drivers\n'
for version in raw base null v2; do cp -p ../four-way-cache-20261031/replay-$version .; done
cp ../../jeandle-llvm/build/build-ninja-release/CMakeCache.txt old-CMakeCache.txt
cp ../../jeandle-llvm-final-cache-bench-20261103/build/CMakeCache.txt new-CMakeCache.txt
../../tools/bin/g++ --version > compiler-version.txt
lscpu > cpu-info.txt
python3 build.py
printf 'driver complete; allowing build activity to settle\n'
sleep 20
python3 run.py
python3 audit.py
printf 'complete\n' > PIPELINE_SUCCESS
trap - EXIT
