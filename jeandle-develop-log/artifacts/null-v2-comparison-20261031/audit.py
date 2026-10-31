import subprocess,json,hashlib
from pathlib import Path
r=Path('results');m=json.loads((r/'manifest.json').read_text());checks=[]
for s in ['same','cross-unique','cross','same-edit','other-edit']:
 for v in ['base','null','v2']:
  p=subprocess.run(['./replay-'+v,s,'cached','2','diagnostic'],capture_output=True,text=True,check=True)
  digest=hashlib.sha256(Path(s+'.ll').read_bytes()).hexdigest()
  assert digest==m['input_hashes'][s],(s,v,'input differs')
  checks.append({'scenario':s,'version':v,'input_sha256':digest,'diagnostic':json.loads(p.stdout)})
for v in ['base','null','v2']:
 s=m['versions'][v];assert hashlib.sha256(Path('replay-'+v).read_bytes()).hexdigest()==s['replay_sha256']
rows=[json.loads(s) for s in (r/'samples.jsonl').read_text().splitlines()];formal=[x for x in rows if not x['warmup']]
assert all(x['cpu_s']>=.2 for x in formal)
assert len(json.loads((r/'summary.json').read_text()))==10
(r/'audit.json').write_text(json.dumps({'checks':checks,'formal_samples':len(formal),'min_cpu_s':min(x['cpu_s'] for x in formal)},indent=2))
print('audit passed:',len(checks),'input/diagnostic checks;',len(formal),'formal samples')
