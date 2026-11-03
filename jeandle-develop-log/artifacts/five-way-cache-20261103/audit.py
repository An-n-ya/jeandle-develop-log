import json,hashlib,subprocess,re,collections
from pathlib import Path
r=Path('results');m=json.loads((r/'manifest.json').read_text());checks=[]
for s in ['same','cross-unique','cross','same-edit','other-edit']:
 for v in m['versions']:
  p=subprocess.run(['./replay-'+v,s,'cached','2','diagnostic'],capture_output=True,text=True,check=True)
  d=json.loads(p.stdout)
  assert d['queries']==64 and d['checksum']==1408
  assert hashlib.sha256(Path(s+'.ll').read_bytes()).hexdigest()==m['input_hashes'][s],(s,v)
  if v=='raw':assert d['final_hits']==0 and d['facts_hits']==0
  checks.append({'scenario':s,'version':v,'diagnostic':d})
for v in m['versions']:
 assert hashlib.sha256(Path('replay-'+v).read_bytes()).hexdigest()==m['versions'][v]['replay_sha256']
for s in ['deep-static','wide-static','leaf-static','tce-cha','virtual-cfg']:
 text=(r/(s+'-raw-diagnostic.stderr')).read_text()
 hits=re.findall(r'^  bypasses: (\d+)$',text,re.M);assert hits and int(hits[-1])>0
 ir=[]
 for v in m['versions']:
  a=(r/(s+'-'+v+'-diagnostic.ll')).read_bytes()
  assert a==(r/(s+'-'+v+'-verification.ll')).read_bytes()
  ir.append(a)
 assert all(a==ir[0] for a in ir)
rows=[json.loads(s) for s in (r/'samples.jsonl').read_text().splitlines()];formal=[x for x in rows if not x['warmup']]
assert all(x['cpu_s']>=.2 for x in formal)
counts=collections.Counter((x['case'],x['phase'],x['version']) for x in formal)
for case in m['input_hashes']:
 assert counts[case,'aa','base']==30
 for v in m['versions']:assert counts[case,'comparison',v]==31
for x in rows:
 if x['kind']=='opt' and x['phase']=='comparison':assert ('-jeandle-disable-java-type-cache=true' in x['command'])==(x['version']=='raw')
assert len(json.loads((r/'summary.json').read_text()))==10 and (r/'SUCCESS').exists()
assert len(formal)==1850
(r/'audit.json').write_text(json.dumps({'checks':checks,'formal_samples':len(formal),'min_cpu_s':min(x['cpu_s'] for x in formal),'raw_opt_bypass_checked':True,'all_opt_ir_byte_identical':True,'all_native_ir_byte_identical':True},indent=2))
print('audit passed',len(checks),'diagnostic/input checks;',len(formal),'formal samples')
