import json,hashlib,subprocess,re
from pathlib import Path
r=Path('results');m=json.loads((r/'manifest.json').read_text());checks=[]
for s in ['same','cross-unique','cross','same-edit','other-edit']:
 for v in ['raw','base','null','v2']:
  p=subprocess.run(['./replay-'+v,s,'cached','2','diagnostic'],capture_output=True,text=True,check=True)
  d=json.loads(p.stdout)
  assert hashlib.sha256(Path(s+'.ll').read_bytes()).hexdigest()==m['input_hashes'][s]
  if v=='raw':assert d['final_hits']==0 and d['facts_hits']==0
  checks.append({'scenario':s,'version':v,'diagnostic':d})
for v in m['versions']:
 assert hashlib.sha256(Path('replay-'+v).read_bytes()).hexdigest()==m['versions'][v]['replay_sha256']
for s in ['deep-static','wide-static','leaf-static','tce-cha','virtual-cfg']:
 text=(r/(s+'-raw-diagnostic.stderr')).read_text()
 hits=re.findall(r'^  bypasses: (\d+)$',text,re.M);assert hits and int(hits[-1])>0
rows=[json.loads(s) for s in (r/'samples.jsonl').read_text().splitlines()];formal=[x for x in rows if not x['warmup']]
assert all(x['cpu_s']>=.2 for x in formal)
for x in rows:
 if x['kind']=='opt' and x['phase']=='comparison':assert ('-jeandle-disable-java-type-cache=true' in x['command'])==(x['version']=='raw')
assert len(json.loads((r/'summary.json').read_text()))==10 and (r/'SUCCESS').exists()
(r/'audit.json').write_text(json.dumps({'checks':checks,'formal_samples':len(formal),'min_cpu_s':min(x['cpu_s'] for x in formal),'raw_opt_bypass_checked':True},indent=2))
print('audit passed',len(checks),'diagnostic/input checks;',len(formal),'formal samples')
