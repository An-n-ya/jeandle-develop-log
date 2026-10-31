import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
root=Path('/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-benchmark')
base=Path('/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-baseline')
out=Path('/tmp/null-edge-requant-results')
assert (out/'SUCCESS').exists()
sys.path.insert(0,str(root/'llvm/utils/jeandle-null-edge-bench'))
from benchmark import counters
meta={}
for name,path in [('a',base),('b',root)]:
 meta[name]={'root':str(path),'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=path,text=True).strip(),'status':subprocess.check_output(['git','status','--short'],cwd=path,text=True),'binary_sha256':hashlib.sha256((path/'build/bin/opt').read_bytes()).hexdigest()}
 cache=(path/'build/CMakeCache.txt').read_text()
 meta[name]['build_config']=[l for l in cache.splitlines() if l.startswith(('CMAKE_BUILD_TYPE:','CMAKE_CXX_COMPILER:','CMAKE_C_COMPILER:','LLVM_ENABLE_ASSERTIONS:','LLVM_TARGETS_TO_BUILD:','CMAKE_CXX_FLAGS_RELEASE:'))]
(out/'versions.json').write_text(json.dumps(meta,indent=2))
shutil.copy('/tmp/null-edge-requant-inputs/audit.json',out/'corpus-audit.json')
shutil.copy('/tmp/null-edge-requant-inputs/corpus-cases.json',out/'corpus-cases.json')
shutil.copy('/tmp/null-edge-workloads-20261030/cases.json',out/'synthetic-cases.json')
shutil.copy('/tmp/null-edge-requant-baseline-unit.log',out/'baseline-unit.log')
(out/'baseline-controls.patch').write_bytes(subprocess.check_output(['git','format-patch','-1','--stdout','ac545bb21e89'],cwd=base))
env=dict(os.environ);env.pop('LD_LIBRARY_PATH',None)
rows=[]
corpus_diag=json.loads((out/'corpus-queries/summary.json').read_text())
for c in json.loads((out/'corpus-cases.json').read_text()):
 cmd=[str(root/'build/bin/opt'),'-disable-output','-jeandle-java-type-stats','-passes='+c['passes']+',print<java-type-analysis-summary>','-jeandle-vm-callback-log='+c['callback'],c['original']]
 result=subprocess.run(cmd,capture_output=True,env=env,check=True)
 original=counters(result.stderr.decode());amplified=corpus_diag[c['name']]['b_counters']
 keys=['queries','null-edge oracle calls','null-edge oracle structural hits','null-edge oracle true answers','null-edge prefilter hits','null-edge oracle budget exhausted queries']
 checks={k:original[k]*c['replicas']==amplified[k] for k in keys}
 rows.append(dict(name=c['name'],replicas=c['replicas'],original_counters=original,proportional_checks=checks))
 assert all(checks.values()),(c['name'],checks)
(out/'amplification-checks.json').write_text(json.dumps(rows,indent=2))
repro=out/'scripts';repro.mkdir(exist_ok=True)
shutil.copy(root/'llvm/utils/jeandle-null-edge-bench/benchmark.py',repro/'benchmark.py')
shutil.copy(root/'llvm/utils/jeandle-null-edge-bench/generate.py',repro/'generate.py')
for name in ['amplify','prepare-corpus','query-diagnostics','run-suite']:
 shutil.copy('/tmp/null-edge-requant-'+name+'.py',repro/(name+'.py'))
print('Collected and checked amplification invariants')
