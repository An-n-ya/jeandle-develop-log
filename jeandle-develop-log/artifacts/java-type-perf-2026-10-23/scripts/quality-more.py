import hashlib,importlib.util,json,time
from pathlib import Path
ROOT=Path('/home/annya/playground/jeandle/perf-results/2026-10-23-javatype-perf')
RUN=ROOT/'run';REPO=Path('/home/annya/playground/jeandle/jeandle/jeandle-llvm')
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
start=time.monotonic()
while not (ROOT/'DIAGNOSTICS_COMPLETE').exists():
    if time.monotonic()-start>7200:raise SystemExit('diagnostics completion timeout')
    time.sleep(10)
time.sleep(10)
spec=importlib.util.spec_from_file_location('profiler',REPO/'llvm/utils/jeandle/profile-java-type-cache.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);helper.sha256=digest
manifest=helper.load_manifest(RUN);helper.ensure_identity(manifest,'additional unwind checks')
for case in ['virtual-cfg','wide-static']:
    dest=RUN/'diagnostics/quality'/f'{case}-199-32k';dest.mkdir(parents=True,exist_ok=True)
    if (dest/'SUCCESS').exists():continue
    command=['perf','record','-e','cycles:u','-F','199','--call-graph','dwarf,32768',
        '-o',str(dest/'perf.data'),'--','taskset','-c','16',*helper.case_command(manifest,case,'s1')]
    result,elapsed=helper.run(command,dest/'record.stderr')
    helper.run(['perf','script','--no-inline','-i',str(dest/'perf.data')],dest/'stacks.stderr',dest/'stacks.txt')
    helper.write_json(dest/'run.json',dict(case=case,mode='s1',frequency=199,stack_bytes=32768,
        elapsed_ns=elapsed,perf_data_bytes=(dest/'perf.data').stat().st_size,
        perf_data_sha256=digest(dest/'perf.data'),command=helper.command_record(command),record_stderr=result.stderr.decode()))
    (dest/'SUCCESS').write_text('additional unwind check completed\n')
    print('additional unwind '+case,flush=True)
ledger=[]
for path in sorted(RUN.rglob('perf.data')):
    dest=path.parent
    for stats in [False,True]:
        name='native-stats' if stats else 'native-self'
        command=['perf','report','-i',str(path),'--stdio','--no-inline','--no-children',
            '-g','none','--sort','dso,symbol','--percent-limit','0','--show-nr-samples']
        if stats:command.append('--stats')
        helper.run(command,dest/(name+'.stderr'),dest/(name+'.txt'))
    ledger.append(dict(path=str(path),bytes=path.stat().st_size,sha256=digest(path)))
helper.write_json(RUN/'perf-data-ledger.json',ledger)
helper.ensure_identity(manifest,'additional unwind completion')
(ROOT/'ALL_COMPLETE').write_text('profiles, annotations, scheduling and unwind checks complete\n')
