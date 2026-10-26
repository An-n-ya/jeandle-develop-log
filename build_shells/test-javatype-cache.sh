#!/usr/bin/env bash
# Reproduce the JavaType cache experiment without changing the checkout.
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: test-javatype-cache.sh [--help]
Environment:
  LLVM_SRC   Source root (default /home/zjj/jeandle/jeandle-llvm)
  LLVM_BUILD Configured build directory (default $LLVM_SRC/build/build-ninja-release)
  JOBS       Build/lit parallelism (default 2)
  RESULT_DIR New output directory (default a unique directory under $LLVM_BUILD/javatype-experiments)
Requires bash, cmake, git, python3 and an existing LLVM build with tests enabled.
Builds current sources first; any failure stops the experiment. Does not install
LLVM, run JDK tests, reset Git, or overwrite existing result directories.
HELP
}
if [[ ${1:-} == --help || ${1:-} == -h ]]; then usage; exit 0; fi
if [[ $# -ne 0 ]]; then usage >&2; exit 2; fi
LLVM_SRC=${LLVM_SRC:-/home/zjj/jeandle/jeandle-llvm}
LLVM_BUILD=${LLVM_BUILD:-$LLVM_SRC/build/build-ninja-release}
JOBS=${JOBS:-2}
[[ $JOBS =~ ^[1-9][0-9]*$ ]] || { echo 'JOBS must be a positive integer.' >&2; exit 2; }
for tool in cmake git python3; do command -v "$tool" >/dev/null; done
LLVM_SRC=$(cd "$LLVM_SRC" && pwd -P)
LLVM_BUILD=$(cd "$LLVM_BUILD" && pwd -P)
[[ -f "$LLVM_BUILD/CMakeCache.txt" ]] || { echo 'Missing CMakeCache.txt' >&2; exit 2; }
if [[ -n ${RESULT_DIR:-} ]]; then
  mkdir -p "$(dirname "$RESULT_DIR")"
  mkdir "$RESULT_DIR" # Refuse to overwrite previous evidence.
else
  mkdir -p "$LLVM_BUILD/javatype-experiments"
  RESULT_DIR=$(mktemp -d "$LLVM_BUILD/javatype-experiments/run-$(date +%Y%m%d-%H%M%S)-XXXXXX")
fi
RESULT_DIR=$(cd "$RESULT_DIR" && pwd -P)
export LLVM_SRC LLVM_BUILD RESULT_DIR
trap 'rc=$?; if ((rc != 0)); then printf "FAILED (exit %s); evidence: %s\n" "$rc" "$RESULT_DIR" >&2; fi' EXIT
cp -- "${BASH_SOURCE[0]}" "$RESULT_DIR/reproduce.sh"
cd "$LLVM_SRC"
git diff HEAD --binary > "$RESULT_DIR/worktree.patch"
git status --short > "$RESULT_DIR/git-status.txt"
cp "$LLVM_BUILD/CMakeCache.txt" "$RESULT_DIR/CMakeCache.txt"
python3 - <<'PY'
import os, json, hashlib, subprocess, platform
from pathlib import Path
from datetime import datetime
root=Path(os.environ['LLVM_SRC']); out=Path(os.environ['RESULT_DIR'])
paths=['llvm/include/llvm/IR/Jeandle/JavaType.h','llvm/lib/IR/Jeandle/JavaType.cpp',
'llvm/include/llvm/Analysis/Jeandle/CachedJavaType.h','llvm/lib/Analysis/Jeandle/CachedJavaType.cpp',
'llvm/include/llvm/Analysis/Jeandle/JavaTypeAnalysis.h','llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp',
'llvm/lib/Analysis/Jeandle/LVINullEdgeOracle.cpp','llvm/lib/Transforms/Jeandle/TypeCheckElimination.cpp',
'llvm/lib/Transforms/Jeandle/CHADevirtualization.cpp','llvm/unittests/IR/JavaTypeQueryTest.cpp']
manifest={'time':datetime.now().astimezone().isoformat(),'platform':platform.platform(),
'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
'source':str(root),'build':os.environ['LLVM_BUILD'],
'source_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},
'note':'worktree.patch records tracked staged and unstaged changes against HEAD; untracked files are listed by git-status.txt but not archived.'}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
PY
cmake --build "$LLVM_BUILD" --target opt FileCheck JavaTypeQueryTests --parallel "$JOBS" 2>&1 | tee "$RESULT_DIR/build.log"
"$LLVM_BUILD/bin/opt" --version > "$RESULT_DIR/opt-version.txt"
"$LLVM_BUILD/unittests/IR/JavaTypeQueryTests" --gtest_filter='JavaTypeQueryTest.*' \
  --gtest_output="xml:$RESULT_DIR/unit.xml" 2>&1 | tee "$RESULT_DIR/unit.log"
"$LLVM_BUILD/bin/llvm-lit" -sv -j "$JOBS" -o "$RESULT_DIR/lit.json" \
  llvm/test/Jeandle/type-check-elimination \
  llvm/test/Jeandle/cha-devirtualization \
  llvm/test/Jeandle/java-type-metadata-recovery \
  llvm/test/Jeandle/constant-field-folding \
  llvm/test/Jeandle/arraycopy-specialization 2>&1 | tee "$RESULT_DIR/lit.log"
python3 - <<'PY' 2>&1 | tee "$RESULT_DIR/matrix.log"
import os, re, json, shlex, subprocess, hashlib
from pathlib import Path
root=Path(os.environ['LLVM_SRC']); build=Path(os.environ['LLVM_BUILD']); out=Path(os.environ['RESULT_DIR'])
opt=build/'bin/opt'; check=build/'bin/FileCheck'
modes={'default':[], 'original':['-jeandle-disable-java-type-cache'], 'verify':['-jeandle-verify-java-type-cache']}
rows=[]
# Deliberately narrow adapter: execute every existing RUN line in these two
# directories with opt flags added. Fail loudly on unsupported test syntax.
for mode,flags in modes.items():
    dest=out/'matrix'/mode; dest.mkdir(parents=True)
    for directory in ['type-check-elimination','cha-devirtualization']:
        for path in sorted((root/'llvm/test/Jeandle'/directory).glob('*.ll')):
            runs=[line.split('; RUN: ',1)[1] for line in path.read_text().splitlines() if line.startswith('; RUN: ')]
            if not runs: raise RuntimeError(f'No RUN lines: {path}')
            for index,command in enumerate(runs,1):
                if not command.startswith('opt ') or command.endswith('\\'):
                    raise RuntimeError(f'Unsupported RUN syntax; use lit for this fixture: {path}: {command}')
                command=shlex.join([str(opt),*flags])+' '+command[4:]
                command=command.replace('%S',shlex.quote(str(path.parent))).replace('%s',shlex.quote(str(path)))
                if re.search(r'%[A-Za-z{]',command): raise RuntimeError(f'Unsupported lit substitution: {command}')
                command=re.sub(r'\bFileCheck\b',lambda _:shlex.quote(str(check)),command)
                name=f'{directory}-{path.stem}-{index}'
                (dest/(name+'.command')).write_text(command+'\n')
                result=subprocess.run(['bash','-o','pipefail','-c',command],cwd=root,capture_output=True,text=True)
                (dest/(name+'.log')).write_text(result.stdout+result.stderr)
                rows.append({'mode':mode,'fixture':str(path.relative_to(root)),'run':index,'exit_code':result.returncode})
                if result.returncode:
                    (out/'matrix.json').write_text(json.dumps(rows,indent=2)+'\n')
                    raise RuntimeError(f'Failed: {mode} {name}; see saved log')
    print(f'{mode}: {sum(r["mode"]==mode for r in rows)} RUN commands passed',flush=True)
(out/'matrix.json').write_text(json.dumps(rows,indent=2)+'\n')

fixture=root/'llvm/test/Jeandle/type-check-elimination/merge-direct-use.ll'
callback=fixture.parent/'Inputs/merge-direct-use.cblog'
observed={}; outputs={}
for mode,flags in modes.items():
    command=[str(opt),'-S','-passes=function(type-check-elimination),print<java-type-analysis-summary>',
             *flags,f'-jeandle-vm-callback-log={callback}',str(fixture)]
    result=subprocess.run(command,capture_output=True,text=True,check=True)
    (out/f'stats-{mode}.command').write_text(shlex.join(command)+'\n')
    (out/f'stats-{mode}.log').write_text(result.stderr)
    (out/f'output-{mode}.ll').write_text(result.stdout)
    subprocess.run([str(check),str(fixture)],input=result.stdout,text=True,check=True)
    observed[mode]={key:int(value) for key,value in re.findall(r'^  ([^:\n]+): (\d+)$',result.stderr,re.M)}
    outputs[mode]=result.stdout
expected={'default':{'queries':3,'path facts hits':2,'final type misses':3,'base insertions':1,'clears':1,'bypasses':0},
          'original':{'queries':3,'path facts hits':0,'final type misses':0,'base insertions':0,'clears':1,'bypasses':3},
          'verify':{'queries':3,'bypasses':0,'verifications':3,'verification skips':0}}
for mode,fields in expected.items():
    for key,value in fields.items():
        if observed[mode].get(key)!=value: raise RuntimeError(f'Statistic changed: {mode} {key}: {observed[mode].get(key)} != {value}; review fixture/implementation')
if len(set(outputs.values()))!=1: raise RuntimeError('merge-direct-use output IR differs across modes')
(out/'stats.json').write_text(json.dumps(observed,indent=2)+'\n')
print('FAM/cache evidence: default path-facts hits=2, bypasses=0; original bypasses=3; verify comparisons=3, skips=0')
print('merge-direct-use: FileCheck passed in all modes; three output IR files are byte-identical')
if (out/'worktree.patch').read_bytes()!=subprocess.check_output(['git','diff','HEAD','--binary']):
    raise RuntimeError('Tracked working tree changed during experiment; rerun')
manifest=json.loads((out/'manifest.json').read_text())
if manifest['commit']!=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip():
    raise RuntimeError('HEAD changed during experiment; rerun')
for p,digest in manifest['source_sha256'].items():
    if hashlib.sha256((root/p).read_bytes()).hexdigest()!=digest: raise RuntimeError(f'Source changed during experiment: {p}')
PY
printf 'PASS: build, JavaType unit tests, five lit directories, three-mode TCE/CHA matrix, FAM/cache counters, and sample IR comparison.\n' | tee "$RESULT_DIR/SUCCESS.txt"
printf 'Evidence: %s\n' "$RESULT_DIR"
