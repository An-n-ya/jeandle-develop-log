import json,os,re,resource,subprocess,math
from pathlib import Path
os.sched_setaffinity(0,{8})
root=Path('/tmp/null-edge-requant-inputs');cases=json.loads((root/'cases.json').read_text())
a='/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-baseline/build/bin/opt'
b='/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-benchmark/build/bin/opt'
env=dict(os.environ);env.pop('LD_LIBRARY_PATH',None)
audit=[];accepted=[];logs=root/'audit';logs.mkdir(exist_ok=True)
for c in cases:
 row={'name':c['name']};outputs=[];valid=True
 for mode,binary in [('a',a),('b',b)]:
  cmd=[binary,'-S','-verify-each','-passes='+c['passes'],'-jeandle-vm-callback-log='+c['callback'],c['original']]
  r=subprocess.run(cmd,capture_output=True,env=env,timeout=120)
  (logs/(c['name']+'-'+mode+'.ll')).write_bytes(r.stdout)
  (logs/(c['name']+'-'+mode+'.stderr')).write_bytes(r.stderr)
  outputs.append(r.stdout);row[mode+'_exit']=r.returncode
  v=subprocess.run(cmd+['-jeandle-verify-java-type-cache'],capture_output=True,env=env,timeout=120)
  (logs/(c['name']+'-'+mode+'-verification.stderr')).write_bytes(v.stderr)
  row[mode+'_verification_exit']=v.returncode
  valid=valid and r.returncode==0 and v.returncode==0
 row['same_ir']=outputs[0]==outputs[1]
 if valid and row['same_ir']:
  cmd=[b,'-disable-output','-passes='+c['passes'],'-jeandle-vm-callback-log='+c['callback'],c['input']]
  before=resource.getrusage(resource.RUSAGE_CHILDREN)
  subprocess.run(cmd,env=env,capture_output=True,timeout=120,check=True)
  after=resource.getrusage(resource.RUSAGE_CHILDREN)
  duration=(after.ru_utime-before.ru_utime)+(after.ru_stime-before.ru_stime)
  count=max(4096,4096*math.ceil(.35/duration))
  original=Path(c['original']).read_text();funcs=list(re.finditer(r'^define\b.*?^}\s*$',original,re.M|re.S))
  with Path(c['input']).open('w') as f:
   f.write(original+'\n')
   for i in range(1,count):
    for m in funcs:
     f.write(re.sub(r'(@[A-Za-z0-9_.$-]+)(?=\()',lambda n:n[1]+'_rep'+str(i),m.group(),count=1)+'\n')
  c['replicas']=count;accepted.append(c);row['replicas']=count;row['pilot_cpu_seconds']=duration
 audit.append(row);print(row,flush=True)
(root/'audit.json').write_text(json.dumps(audit,indent=2));(root/'corpus-cases.json').write_text(json.dumps(accepted,indent=2))
