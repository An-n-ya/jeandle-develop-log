"""Replicate independent function definitions, preserving module metadata IDs."""
import ast
import json
from pathlib import Path
import re
import shlex
root=Path('/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-benchmark')
files=['llvm/test/Jeandle/java-type-metadata-recovery/recover-null-arm-vacuous.ll', 'llvm/test/Jeandle/type-check-elimination/checkcast-expanded-phi.ll', 'llvm/test/Jeandle/type-check-elimination/frozen-null-edge.ll', 'llvm/test/Jeandle/type-check-elimination/null-arm-type.ll', 'llvm/test/Jeandle/type-check-elimination/null-both-edges.ll', 'llvm/test/Jeandle/type-check-elimination/null-guard-forms.ll', 'llvm/test/Jeandle/type-check-elimination/null-threaded-edge.ll', 'llvm/test/Jeandle/type-check-elimination/checkcast-dissolved.ll', 'llvm/test/Jeandle/type-check-elimination/condition-value-domain.ll', 'llvm/test/Jeandle/java-type-metadata-recovery/recover-osr-checkcast-edge.ll', 'llvm/test/Jeandle/cha-devirtualization/method-handle-link-to-virtual.ll']
out=Path('/tmp/null-edge-requant-inputs');out.mkdir(exist_ok=False)
cases=[]
for relative in files:
 p=root/relative
 s=p.read_text()
 run=next(x.split('RUN:',1)[1].strip() for x in s.splitlines() if x.startswith('; RUN:'))
 parts=shlex.split(run.replace('%S',str(p.parent)).replace('%s',str(p)))
 passes=next(x[len('-passes='):] for x in parts if x.startswith('-passes='))
 callback=next(x[len('-jeandle-vm-callback-log='):] for x in parts if x.startswith('-jeandle-vm-callback-log='))
 functions=list(re.finditer(r'^define\b.*?^}\s*$',s,re.M|re.S))
 # No function body is modified; copied functions refer to the same module
 # constants/metadata and original helper definitions. Cache lifetime is per F.
 replicas=[]
 for i in range(1,4096):
  for f in functions:
   body=f.group()
   body=re.sub(r'(@[A-Za-z0-9_.$-]+)(?=\()',lambda m:m[1]+'_rep'+str(i),body,count=1)
   replicas.append(body)
 dst=out/(p.stem+'.ll');dst.write_text(s+'\n'+'\n'.join(replicas)+'\n')
 cases.append(dict(name=p.stem,input=str(dst),callback=callback,passes='function('+passes+')',original=str(p),replicas=4096))
(out/'cases.json').write_text(json.dumps(cases,indent=2))
