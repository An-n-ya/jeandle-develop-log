import json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
results=root/'results'
assert (results/'SUCCESS').exists()
opt=root.parent.parent/'jeandle-llvm-null-edge-v2-20261103/build/bin/opt'
cases=json.loads(Path('/tmp/null-edge-workloads-20261030/cases.json').read_text())
def counters(text):
 d={}
 for line in text.rsplit('JavaTypeAnalysis process summary after module:',1)[-1].splitlines():
  key,sep,val=line.strip().partition(': ')
  if sep and val.isdigit():d[key]=int(val)
 return d
summary=[]
for c in cases:
 cmd=[str(opt),'-S','-passes='+c['passes']+',print<java-type-analysis-summary>','-jeandle-vm-callback-log='+c['callback'],c['input'],'-jeandle-java-type-stats=true','-verify-each','-jeandle-disable-null-edge-prefilter=true']
 p=subprocess.run(cmd,capture_output=True,check=True)
 expected=(results/(c['name']+'-candidate-diagnostic.ll')).read_bytes()
 assert p.stdout==expected,c['name']+' prefilter changed IR'
 (results/(c['name']+'-candidate-unfiltered-diagnostic.stderr')).write_bytes(p.stderr)
 before=counters(p.stderr.decode());after=counters((results/(c['name']+'-candidate-diagnostic.stderr')).read_text())
 assert before['null oracle LVI calls']>0
 assert after['null oracle LVI calls']==0
 assert before['null oracle filtered']==0 and after['null oracle filtered']>0
 summary.append({'case':c['name'],'unfiltered':before,'filtered':after,'IR_byte_identical':True,'excluded_from_timing':True})
(results/'prefilter-ablation.json').write_text(json.dumps(summary,indent=2))
print('prefilter ablation passed: same IR; nonzero LVI calls -> zero in all five opt cases')
