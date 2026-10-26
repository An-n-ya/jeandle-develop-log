import argparse
import hashlib
import importlib.util
import json
import random
import subprocess
import time
from pathlib import Path

ROOT=Path('/home/annya/playground/jeandle/perf-results/2026-10-23-javatype-perf')
RUN=ROOT/'run'
REPO=Path('/home/annya/playground/jeandle/jeandle/jeandle-llvm')

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''): h.update(data)
    return h.hexdigest()

def main():
    started=time.monotonic()
    while not (ROOT/'L2_COMPLETE').exists():
        if time.monotonic()-started>7200:raise SystemExit('L2 completion timeout')
        time.sleep(10)
    spec=importlib.util.spec_from_file_location('frozen_profiler',REPO/'llvm/utils/jeandle/profile-java-type-cache.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    helper.sha256=digest
    manifest=helper.load_manifest(RUN)
    helper.ensure_identity(manifest,'final diagnostics setup')
    cases=dict(manifest['cases']);cases.update(manifest['l2'])
    rng=random.Random(20261023)
    # :u filters software context-switch records to zero on this host. Correct
    # this diagnostic separately, without changing the original raw records.
    for case,item in cases.items():
        for repeat in range(3):
            modes=list(helper.MODES);rng.shuffle(modes)
            for mode in modes:
                dest=RUN/'diagnostics/scheduling'/case/f'{repeat:03d}-{mode}.json'
                if dest.exists():continue
                command=['perf','stat','-x',';','-e',
                    'task-clock,context-switches,cpu-migrations,page-faults','--',
                    'taskset','-c','16','python3',str(ROOT/'rss-launch.py'),*helper.item_command(manifest,item,mode)]
                result,elapsed=helper.run(command,dest.with_suffix('.stderr'))
                helper.write_json(dest,dict(case=case,mode=mode,round=repeat,
                    elapsed_ns=elapsed,metrics=helper.parse_semicolon_metrics(result.stderr.decode()),
                    opt_rusage=json.loads(__import__('re').search(r'\[javatype-rusage\] (.+)',result.stderr.decode()).group(1)),
                    command=helper.command_record(command),scope='whole-process user+kernel software events'))
        print('corrected scheduling '+case,flush=True)
    item=manifest['cases']['deep-static']
    for tag,frequency,stack in [('low-49-8k',49,8192),('high-399-8k',399,8192),('deep-199-32k',199,32768)]:
        dest=RUN/'diagnostics/quality'/tag
        if (dest/'SUCCESS').exists():continue
        dest.mkdir(parents=True,exist_ok=True)
        command=['perf','record','-e','cycles:u','-F',str(frequency),
            '--call-graph',f'dwarf,{stack}','-o',str(dest/'perf.data'),'--',
            'taskset','-c','16',*helper.item_command(manifest,item,'s1')]
        result,elapsed=helper.run(command,dest/'record.stderr')
        helper.run(['perf','script','-i',str(dest/'perf.data')],dest/'stacks.stderr',dest/'stacks.txt')
        helper.write_json(dest/'run.json',dict(case='deep-static',mode='s1',tag=tag,
            frequency=frequency,stack_bytes=stack,elapsed_ns=elapsed,
            perf_data_sha256=digest(dest/'perf.data'),perf_data_bytes=(dest/'perf.data').stat().st_size,
            command=helper.command_record(command),record_stderr=result.stderr.decode()))
        (dest/'SUCCESS').write_text('quality check captured\n')
        print('quality '+tag,flush=True)
    ledger=[]
    for path in sorted(RUN.rglob('perf.data')):
        dest=path.parent
        command=['perf','report','-i',str(path),'--stdio','--stats','--no-inline',
            '--no-children','-g','none','--sort','dso,symbol','--percent-limit','0','--show-nr-samples']
        if not (dest/'native-self-stats.txt').exists():
            helper.run(command,dest/'native-self-stats.stderr',dest/'native-self-stats.txt')
        ledger.append(dict(path=str(path),bytes=path.stat().st_size,sha256=digest(path)))
    helper.write_json(RUN/'perf-data-ledger.json',ledger)
    pilot=RUN/'profiles/deep-static/s1/run-00/perf.data'
    for tag,symbol in [('poison','programUndefinedIfUndefOrPoison(llvm::Value const*, bool)'),
        ('lvi-select','llvm::LazyValueInfoImpl::solveBlockValueSelect(llvm::SelectInst*, llvm::BasicBlock*)'),
        ('invalidate','llvm::jeandle::JavaTypeCache::invalidate(llvm::ArrayRef<llvm::Value*>, bool, llvm::jeandle::JavaTypeBaseInvalidationMode)')]:
        dest=RUN/'diagnostics/annotate'/f'{tag}.txt'
        if dest.exists():continue
        command=['perf','annotate','-i',str(pilot),'--stdio','--stdio-color','never','--source','-l','-s',symbol]
        try:helper.run(command,dest.with_suffix('.stderr'),dest)
        except RuntimeError as error:print(str(error),flush=True)
        print('annotate '+tag,flush=True)
    environment={}
    for label,command in [('uname',['uname','-a']),('perf-version',['perf','--version']),
        ('perf-build-options',['perf','version','--build-options']),
        ('lscpu',['lscpu']),('topology',['lscpu','-e=CPU,NODE,SOCKET,CORE,ONLINE']),
        ('affinity',['taskset','-pc',str(__import__('os').getpid())]),
        ('load',['cat','/proc/loadavg']),('paranoid',['cat','/proc/sys/kernel/perf_event_paranoid']),
        ('governor',['cat','/sys/devices/system/cpu/cpu16/cpufreq/scaling_governor']),
        ('siblings',['cat','/sys/devices/system/cpu/cpu16/topology/thread_siblings_list'])]:
        result=subprocess.run(command,text=True,capture_output=True)
        environment[label]=dict(command=command,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
    helper.write_json(RUN/'environment-post.json',environment)
    identity={}
    for name,item in cases.items():
        identity[name]={key:dict(expected=item[key+'_sha256'],actual=digest(Path(item[key])))
                        for key in ('ir','cblog')}
    if any(v['actual']!=v['expected'] for item in identity.values() for v in item.values()):
        raise RuntimeError('input identity changed')
    helper.write_json(RUN/'input-identity-post.json',identity)
    helper.ensure_identity(manifest,'final diagnostics completion')
    helper.write_json(RUN/'identity-post.json',helper.source_identity(REPO,Path(manifest['opt']))[0])
    (ROOT/'DIAGNOSTICS_COMPLETE').write_text('all final diagnostics completed\n')

if __name__=='__main__':main()
