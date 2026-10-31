import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
sys.path.insert(0,'/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-benchmark/llvm/utils/jeandle-null-edge-bench')
from benchmark import counters, interval
p=argparse.ArgumentParser();p.add_argument('--cases',required=True);p.add_argument('--a',required=True);p.add_argument('--b',required=True);p.add_argument('--out',required=True);p.add_argument('--repeats',type=int,default=15)
a=p.parse_args();os.sched_setaffinity(0,{8});out=Path(a.out);out.mkdir(exist_ok=False)
rng=random.Random(20261031);raw=(out/'samples.jsonl').open('w',buffering=1);summary={}
env=dict(os.environ);env.pop('LD_LIBRARY_PATH',None)
for case in json.loads(Path(a.cases).read_text()):
 pairs=[]
 for i in range(-2,a.repeats):
  modes=['a','b'];rng.shuffle(modes);pair={};irs=[]
  for m in modes:
   cmd=[getattr(a,m),'-S','-jeandle-java-type-stats','-passes='+case['passes']+',print<java-type-analysis-summary>','-jeandle-vm-callback-log='+case['callback'],case['input']]
   proc=subprocess.run(cmd,capture_output=True,env=env,timeout=120,check=True)
   c=counters(proc.stderr.decode());irs.append(hashlib.sha256(proc.stdout).hexdigest())
   pair[m]=c;raw.write(json.dumps(dict(case=case['name'],round=i,mode=m,counters=c,command=cmd,ir_sha256=irs[-1]))+'\n')
  if len(set(irs))!=1:raise RuntimeError('diagnostic IR mismatch')
  if i>=0:pairs.append(pair)
 changes=[100*(r['b']['total query time (ns)']/r['a']['total query time (ns)']-1) for r in pairs]
 summary[case['name']]=dict(a_query_median_ns=statistics.median(r['a']['total query time (ns)'] for r in pairs),b_query_median_ns=statistics.median(r['b']['total query time (ns)'] for r in pairs),paired_change_pct=statistics.median(changes),bootstrap_95pct=interval(changes,20261031),a_counters={k:statistics.median(r['a'][k] for r in pairs) for k in pairs[0]['a']},b_counters={k:statistics.median(r['b'][k] for r in pairs) for k in pairs[0]['b']})
 (out/'summary.json').write_text(json.dumps(summary,indent=2));print(case['name'],summary[case['name']]['paired_change_pct'],flush=True)
(out/'SUCCESS').touch()
