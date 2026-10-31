import json,subprocess,os
from pathlib import Path
root=Path('/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-benchmark')
a='/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-baseline/build/bin/opt';b=str(root/'build/bin/opt')
harness=str(root/'llvm/utils/jeandle-null-edge-bench/benchmark.py')
out=Path('/tmp/null-edge-requant-results');out.mkdir(exist_ok=False)
env=dict(os.environ);env.pop('LD_LIBRARY_PATH',None)
def run(cmd,label):
 print('START',label,flush=True)
 with (out/(label+'.log')).open('w') as log:
  subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=env,cwd=root,check=True)
 print('DONE',label,flush=True)
for group,cases in [('synthetic','/tmp/null-edge-workloads-20261030/cases.json'),('corpus','/tmp/null-edge-requant-inputs/corpus-cases.json')]:
 for arm,binary in [('a',a),('b',b)]:
  run(['python3',harness,'--cases',cases,'--a',binary,'--b',binary,'--cpu','8','--repeats','15','--warmups','3','--seed',str(20261100+(0 if arm=='a' else 1)),'--out',str(out/(group+'-aa-'+arm))],group+'-aa-'+arm)
 ca=json.loads((out/(group+'-aa-a/summary.json')).read_text());cb=json.loads((out/(group+'-aa-b/summary.json')).read_text())
 for name,v in ca.items():
  for metric in ['cpu_ns','wall_ns']:
   v[metric]['absolute_pair_change_p95']=max(v[metric]['absolute_pair_change_p95'],cb[name][metric]['absolute_pair_change_p95'])
  v['sample_duration_ok']=v['sample_duration_ok'] and cb[name]['sample_duration_ok']
 calibration=out/(group+'-calibration.json');calibration.write_text(json.dumps(ca,indent=2))
 run(['python3',harness,'--cases',cases,'--a',a,'--b',b,'--cpu','8','--repeats','31','--warmups','3','--calibration',str(calibration),'--seed','20261102','--out',str(out/(group+'-ab'))],group+'-ab')
 run(['python3','/tmp/null-edge-requant-query-diagnostics.py','--cases',cases,'--a',a,'--b',b,'--repeats','15','--out',str(out/(group+'-queries'))],group+'-queries')
(out/'SUCCESS').touch()
