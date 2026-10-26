#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/zjj/jeandle
BOOT_JDK=/usr/lib/jvm/java-21-openjdk-amd64
JOBS="${JOBS:-4}"
MODE="${1:-release}"

if [[ $# -gt 1 ]]; then
  echo '用法: build.sh [release|debug]' >&2
  exit 2
fi
case "$MODE" in
  release)
    LLVM_BUILD_TYPE=Release
    JDK_DEBUG_LEVEL=release
    ;;
  debug)
    LLVM_BUILD_TYPE=Debug
    JDK_DEBUG_LEVEL=slowdebug
    ;;
  -h|--help)
    echo '用法: build.sh [release|debug]，默认 release；可用 JOBS=8 设置并发数。'
    exit 0
    ;;
  *)
    echo '用法: build.sh [release|debug]' >&2
    exit 2
    ;;
esac

LLVM_BUILD="$ROOT/jeandle-llvm/build/build-ninja-$MODE"
LLVM_INSTALL="/home/zjj/jeandle-llvm-$MODE"
JDK_CONF="linux-x86_64-server-$JDK_DEBUG_LEVEL"

printf '构建模式: %s (LLVM %s / JDK %s)\n' "$MODE" "$LLVM_BUILD_TYPE" "$JDK_DEBUG_LEVEL"

# LLVM: first run builds from scratch; subsequent runs build changed files.
cmake -S "$ROOT/jeandle-llvm/llvm" -B "$LLVM_BUILD" \
  -G Ninja \
  -DLLVM_TARGETS_TO_BUILD=X86 \
  -DCMAKE_BUILD_TYPE="$LLVM_BUILD_TYPE" \
  -DCMAKE_INSTALL_PREFIX="$LLVM_INSTALL" \
  -DLLVM_BUILD_LLVM_DYLIB=ON \
  -DLLVM_DYLIB_COMPONENTS=all

cmake --build "$LLVM_BUILD" --parallel "$JOBS"
cmake --install "$LLVM_BUILD"

# JDK uses its own Make build system, which also supports incremental builds.
cd "$ROOT/jeandle-jdk"
bash configure \
  --build=x86_64-unknown-linux-gnu \
  --openjdk-target=x86_64-unknown-linux-gnu \
  --with-boot-jdk="$BOOT_JDK" \
  --with-debug-level="$JDK_DEBUG_LEVEL" \
  --with-jeandle-llvm="$LLVM_INSTALL"

make CONF="$JDK_CONF" JOBS="$JOBS" images
