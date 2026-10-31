#!/usr/bin/env python3
import os,json,time,hashlib,subprocess,statistics as st,random,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.chdir(ROOT);os.sched_setaffinity(0,{8})
spec=importlib.util.spec_from_file_location('oldbench','/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-benchmark/llvm/utils/jeandle-null-edge-bench/benchmark.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
scenarios=['cross-unique'];modes=['cached','reference','nofinal','full'];rng=random.Random(20261031)
out=ROOT/'results-unique';out.mkdir(exist_ok=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(s,m,n,kind='timing'):
 p=subprocess.run([str(ROOT/'replay-unique'),s,m,str(n),kind],capture_output=True,text=True,timeout=120)
 if p.returncode:raise RuntimeError(p.stderr)
 a=json.loads(p.stdout);assert a['queries']==32*n and a['checksum']==22*32*n
 return a
manifest={'date':'2026-10-31','cpu':8,'affinity':list(os.sched_getaffinity(0)),'siblings':Path('/sys/devices/system/cpu/cpu8/topology/thread_siblings_list').read_text().strip(),'source':subprocess.check_output(['git','-C','../../jeandle-llvm','rev-parse','HEAD'],text=True).strip(),'replay_sha256':sha('replay-unique'),'driver_sha256':sha('driver-unique.cpp'),'runner_sha256':sha(__file__),'support_sha256':sha('../../jeandle-llvm/llvm/unittests/IR/JavaTypeCacheReuseTestSupport.h'),'rounds':31,'warmups':3,'interval':'native process user+system CPU; excludes IR creation/parsing, includes cache reset and edits','normalization':'mode-specific batches; each batch identical 32-query sequence; compare CPU per batch','target_cpu_s':0.30,'comparisons':['cached A/A','reference -> cached','nofinal -> cached','full -> cached']}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
diags={};batches={};samples=open(out/'samples.jsonl','w',buffering=1);summaries=[]
for s in scenarios:
 for m in modes:
  diags[s+':'+m]=run(s,m,2,'diagnostic')
  (out/'diagnostics.json').write_text(json.dumps(diags,indent=2))
  n=4
  while True:
   a=run(s,m,n)
   if a['cpu_s']>=.15:break
   n*=4
  n=max(n,int(n*.36/a['cpu_s'])+1);batches[s+':'+m]=n
  print('prepared',s,m,n,flush=True)
 for base in ['cached','reference','nofinal','full']:
  pairs=[];durations=[]
  for i in range(34):
   order=['a','b'];rng.shuffle(order);pair={}
   for arm in order:
    m=base if arm=='a' else 'cached';n=batches[s+':'+m]
    a=run(s,m,n);a.update(scenario=s,base=base,arm=arm,round=i,warmup=i<3,batches=n,cpu_per_batch=a['cpu_s']/n)
    samples.write(json.dumps(a)+'\n');pair[arm]=a
   if i>=3:
    pairs.append(100*(pair['b']['cpu_per_batch']/pair['a']['cpu_per_batch']-1));durations.extend([pair['a']['cpu_s'],pair['b']['cpu_s']])
  if base=='cached':floor=sorted(abs(x) for x in pairs)[int(.95*(len(pairs)-1))]
  ci=h.interval(pairs,20261031);delta=st.median(pairs);long=min(durations)>=.2
  verdict='inconclusive'
  if base!='cached' and long:
   if ci[1]<-floor:verdict='improvement'
   elif ci[0]>floor:verdict='regression'
  summaries.append(dict(scenario=s,baseline=base,candidate='cached',change_pct=delta,ci95=ci,noise_p95=floor,min_sample_cpu_s=min(durations),duration_ok=long,verdict=verdict))
  (out/'summary.json').write_text(json.dumps(summaries,indent=2));print(summaries[-1],flush=True)
assert manifest['replay_sha256']==sha('replay-unique')
manifest['batches']=batches;manifest['input_sha256']={s:sha(s+'.ll') for s in scenarios};(out/'manifest.json').write_text(json.dumps(manifest,indent=2));(out/'SUCCESS').write_text('complete\n')
