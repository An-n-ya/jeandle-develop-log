#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/zjj/jeandle
LLVM_BUILD="$ROOT/jeandle-llvm/build/build-ninja-release"
JDK_SRC="$ROOT/jeandle-jdk"
JDK_CONF=linux-x86_64-server-release
JOBS="${JOBS:-4}"
SUITE="${1:-java-type}"
SIDE="${2:-both}"

usage() {
  printf '%s\n' \
    '用法: test.sh [java-type|all] [llvm|jdk|both]' \
    '默认: java-type both；all 表示全部 Jeandle 专项测试。' \
    '并发数: JOBS=4；可用 JT_HOME=/path/to/jtreg 指定 jtreg。' \
    '运行 JDK 测试前，请先执行 build.sh 更新 LLVM 安装和 JDK。'
}

if [[ "$SUITE" == --help || "$SUITE" == -h ]]; then
  usage
  exit 0
fi
if [[ $# -gt 2 || ! "$SUITE" =~ ^(java-type|all)$ || ! "$SIDE" =~ ^(llvm|jdk|both)$ ]]; then
  usage >&2
  exit 2
fi
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || { echo 'JOBS 必须为正整数。' >&2; exit 2; }

# Check prerequisites before starting any build or test.
if [[ "$SIDE" != jdk ]]; then
  [[ -f "$LLVM_BUILD/build.ninja" ]] || {
    echo "缺少 Ninja 构建目录，请先运行 build.sh: $LLVM_BUILD" >&2
    exit 1
  }
fi
if [[ "$SIDE" != llvm ]]; then
  spec="$JDK_SRC/build/$JDK_CONF/spec.gmk"
  [[ -f "$spec" ]] || { echo 'JDK 尚未配置，请先运行 build.sh。' >&2; exit 1; }
  jtreg_home="${JT_HOME:-$(sed -n 's/^JT_HOME[[:space:]]*:=[[:space:]]*//p' "$spec")}"
  [[ -n "$jtreg_home" && -f "$jtreg_home/lib/jtreg.jar" ]] || {
    echo '未找到 jtreg。请准备 jtreg 后使用 JT_HOME=/path/to/jtreg ./test.sh。' >&2
    exit 1
  }
  jtreg_home="$(cd "$jtreg_home" && pwd -P)"
fi

if [[ "$SIDE" != jdk ]]; then
  cd "$ROOT/jeandle-llvm"
  if [[ "$SUITE" == java-type ]]; then
    targets=(opt FileCheck)
    tests=(llvm/test/Jeandle/java-type-metadata-recovery
           llvm/test/Jeandle/type-check-elimination
           llvm/test/Jeandle/cha-devirtualization)
  else
    targets=(opt llc llvm-extract FileCheck not count split-file)
    tests=(llvm/test/Jeandle)
  fi
  cmake --build "$LLVM_BUILD" --target "${targets[@]}" --parallel "$JOBS"
  "$LLVM_BUILD/bin/llvm-lit" -v -j "$JOBS" "${tests[@]}"
fi

if [[ "$SIDE" != llvm ]]; then
  cd "$JDK_SRC"
  if [[ "$SUITE" == java-type ]]; then
    tests='hotspot/jtreg/compiler/jeandle/typeMetadataRecovery hotspot/jtreg/compiler/jeandle/typeCheckElimination'
  else
    tests='hotspot/jtreg/compiler/jeandle'
  fi
  make CONF="$JDK_CONF" JOBS="$JOBS" test \
    TEST="$tests" JTREG="JOBS=$JOBS" JT_HOME="$jtreg_home"
fi
