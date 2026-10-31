import os,json,subprocess,resource,time,statistics as st,random,hashlib,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parent;os.chdir(ROOT);os.environ.pop('LD_LIBRARY_PATH',None);os.sched_setaffinity(0,{8})
TOP=ROOT.parent.parent
spec=importlib.util.spec_from_file_location('bench',TOP/'jeandle-llvm-null-edge-benchmark/llvm/utils/jeandle-null-edge-bench/benchmark.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
versions={'base':TOP/'jeandle-llvm-null-edge-baseline','null':TOP/'jeandle-llvm-null-edge-benchmark','v2':TOP/'jeandle-llvm'}
opts={'base':versions['base']/'build/bin/opt','null':versions['null']/'build/bin/opt','v2':versions['v2']/'build/build-ninja-release/bin/opt'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
out=ROOT/'results';out.mkdir(exist_ok=False);raw=(out/'samples.jsonl').open('w',buffering=1);rng=random.Random(20261031)
manifest={'versions':{v:{'head':subprocess.check_output(['git','-C',p,'rev-parse','HEAD'],text=True).strip(),'opt_sha256':sha(opts[v]),'replay_sha256':sha('replay-'+v)} for v,p in versions.items()},'affinity':list(os.sched_getaffinity(0)),'siblings':Path('/sys/devices/system/cpu/cpu8/topology/thread_siblings_list').read_text().strip(),'governor':Path('/sys/devices/system/cpu/cpu8/cpufreq/scaling_governor').read_text().strip(),'aa_repeats':15,'repeats':31,'warmups':3,'seed':20261031,'input_hashes':{},'batches':{},'driver_sha256':sha('driver.cpp'),'runner_sha256':sha(__file__)}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2));summary=[];diags={}
scenarios=['same','cross-unique','cross','same-edit','other-edit'];optcases=json.loads(Path('/tmp/null-edge-workloads-20261030/cases.json').read_text())
def execute_native(s,v,n,kind='timing'):
 p=subprocess.run([str(ROOT/('replay-'+v)),s,'cached',str(n),kind],capture_output=True,text=True,timeout=120)
 if p.returncode:raise RuntimeError(p.stderr)
 a=json.loads(p.stdout);assert a['queries']==32*n and a['checksum']==22*32*n
 return a

def execute_opt(c,v,phase='timing'):
 diagnostic=phase=='diagnostic';verify=phase=='verification';cmd=[str(opts[v]),'-S' if diagnostic or verify else '-disable-output','-passes='+c['passes']+(',print<java-type-analysis-summary>' if diagnostic else ''),'-jeandle-vm-callback-log='+c['callback'],c['input']]
 if diagnostic:cmd+=['-jeandle-java-type-stats=true','-verify-each']
 if verify:cmd+=['-jeandle-verify-java-type-cache=true','-verify-each']
 before=resource.getrusage(resource.RUSAGE_CHILDREN);t=time.perf_counter();p=subprocess.run(cmd,capture_output=True,timeout=120);after=resource.getrusage(resource.RUSAGE_CHILDREN)
 if p.returncode:raise RuntimeError(p.stderr.decode())
 if diagnostic:h.counters(p.stderr.decode())
 if phase!='timing':
  (out/(c['name']+'-'+v+'-'+phase+'.stderr')).write_bytes(p.stderr)
  (out/(c['name']+'-'+v+'-'+phase+'.ll')).write_bytes(p.stdout)
 elif p.stdout:raise RuntimeError('unexpected timing output')
 return {'cpu_s':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,'wall_s':time.perf_counter()-t,'command':cmd},p.stdout

for kind,cases in [('native',scenarios),('opt',optcases)]:
 for c in cases:
  name=c if kind=='native' else c['name'];batches={}
  if kind=='native':
   for v in versions:
    a=execute_native(c,v,2,'diagnostic');diags[name+':'+v]=a
    n=4
    while True:
     a=execute_native(c,v,n)
     if a['cpu_s']>=.12:break
     n*=4
    batches[v]=max(n,int(n*.36/a['cpu_s'])+1)
   manifest['input_hashes'][name]=sha(name+'.ll');manifest['batches'][name]=batches
  else:
   ir=[]
   for v in versions:
    _,verified=execute_opt(c,v,'verification');a,diagnosed=execute_opt(c,v,'diagnostic')
    assert verified==diagnosed,'verification changed IR'
    ir.append(diagnosed)
   assert ir[0]==ir[1]==ir[2],'cross-version IR differs: '+name
   manifest['input_hashes'][name]={'ir':sha(c['input']),'callback':sha(c['callback'])}
  (out/'diagnostics.json').write_text(json.dumps(diags,indent=2));print('prepared',kind,name,flush=True)
  def measure(v):
   if kind=='native':
    a=execute_native(c,v,batches[v]);a['cost']=a['cpu_s']/batches[v];a['batches']=batches[v]
   else:
    a,_=execute_opt(c,v);a['cost']=a['cpu_s']
   return a
  aa=[];aa_durations=[]
  for i in range(18):
   arms=['a','b'];rng.shuffle(arms);pair={}
   for arm in arms:
    a=measure('base');pair[arm]=a;raw.write(json.dumps(dict(a,phase='aa',kind=kind,case=name,version='base',arm=arm,round=i,warmup=i<3))+'\n')
   if i>=3:aa.append(100*(pair['b']['cost']/pair['a']['cost']-1));aa_durations.extend(x['cpu_s'] for x in pair.values())
  floor=sorted(abs(x) for x in aa)[int(.95*(len(aa)-1))];pairs=[]
  for i in range(34):
   order=list(versions);rng.shuffle(order);pair={}
   for v in order:
    a=measure(v);pair[v]=a;raw.write(json.dumps(dict(a,phase='comparison',kind=kind,case=name,version=v,round=i,warmup=i<3))+'\n')
   if i>=3:pairs.append(pair)
  entry={'kind':kind,'case':name,'metric':'CPU ms / 32-query batch' if kind=='native' else 'opt process CPU ms','aa_noise_p95':floor,'min_cpu_s':min([x['cpu_s'] for p in pairs for x in p.values()]+aa_durations),'cost_ms':{v:st.median(p[v]['cost'] for p in pairs)*1000 for v in versions},'comparisons':{}}
  for left,right in [('base','null'),('base','v2'),('null','v2')]:
   d=[100*(p[right]['cost']/p[left]['cost']-1) for p in pairs];ci=h.interval(d,20261031);verdict='inconclusive'
   if entry['min_cpu_s']>=.2:
    if ci[1]<-floor:verdict='improvement'
    elif ci[0]>floor:verdict='regression'
   entry['comparisons'][left+'->'+right]={'change_pct':st.median(d),'ci95':ci,'verdict':verdict}
  summary.append(entry);(out/'summary.json').write_text(json.dumps(summary,indent=2));(out/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(entry),flush=True)
for v in versions:assert manifest['versions'][v]['opt_sha256']==sha(opts[v]) and manifest['versions'][v]['replay_sha256']==sha('replay-'+v)
(out/'SUCCESS').write_text('complete\n')
