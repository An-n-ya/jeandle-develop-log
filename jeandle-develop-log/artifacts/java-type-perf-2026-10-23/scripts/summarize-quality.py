#!/usr/bin/env python3
"""Collect raw loss/throttle, stack-depth checks, and corrected scheduling data."""
import argparse,collections,csv,importlib.util,json,re,statistics
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--artifact',type=Path,required=True)
    args=parser.parse_args();a=args.artifact
    spec=importlib.util.spec_from_file_location('attribute',Path(__file__).with_name('attribute-stacks.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    symbols=m.Symbols(a/'opt-symbols.gz')
    loss=[]
    for path in sorted(args.run.rglob('native-stats.txt')):
        text=path.read_text()
        events={key:int(value) for key,value in re.findall(r'^\s*(\w+) events:\s*(\d+)',text,re.M)}
        loss.append(dict(path=str(path),lost_records=events.get('LOST',0),
            lost_sample_records=events.get('LOST_SAMPLES',0),
            throttle_records=events.get('THROTTLE',0),unthrottle_records=events.get('UNTHROTTLE',0)))
    quality=[]
    for path in sorted((args.run/'diagnostics/quality').glob('*/stacks.txt')):
        meta=json.loads((path.parent/'run.json').read_text())
        samples,base=m.parse(path,symbols)
        samples=[s for s in samples if s['comm']=='opt' and s['event']=='cpu_atom/cycles/u']
        total=sum(s['period'] for s in samples);weight=collections.Counter();counts=collections.Counter()
        who=collections.Counter();groups=collections.Counter();self_native=collections.Counter()
        for sample in samples:
            info=m.classify(sample);period=sample['period']
            for key in ('jt','lvi','unknown','root_complete'):
                if info[key]:weight[key]+=period;counts[key]+=1
            if info['jt']:
                who[info['consumer']]+=period
                if info['lvi']:weight['jt_lvi']+=period
            groups[info['group']]+=period
            frame=sample['frames'][0]
            self_native[frame['native'] or frame['name']]+=period
        row=dict(tag=path.parent.name,case=meta['case'],samples=len(samples),
            frequency=meta['frequency'],stack_bytes=meta['stack_bytes'],
            elapsed_s=meta['elapsed_ns']/1e9,jt_samples=counts['jt'],
            pct={key:100*value/total for key,value in weight.items()},
            groups={key:100*value/total for key,value in groups.items()},
            consumer_pct_jt={key:100*value/weight['jt'] for key,value in who.items()},
            native_self_top=[dict(symbol=key,pct_process=100*value/total) for key,value in self_native.most_common(12)])
        quality.append(row)
    scheduling=[]
    rows=[json.loads(p.read_text()) for p in (args.run/'diagnostics/scheduling').glob('*/*.json')]
    for case,mode in sorted({(r['case'],r['mode']) for r in rows}):
        items=[r for r in rows if r['case']==case and r['mode']==mode]
        result=dict(case=case,mode=mode,repeats=len(items))
        for metric in ('max_rss_kb','voluntary_context_switches','involuntary_context_switches','user_s','system_s'):
            result[metric+'_median']=statistics.median(r['opt_rusage'][metric] for r in items)
        for metric in ('task-clock','context-switches','cpu-migrations','page-faults'):
            actual=[(key,entry) for r in items for key,entry in r['metrics'].items() if key.split(':')[0]==metric]
            result[metric+'_event_names']=sorted({key for key,entry in actual})
            result[metric+'_median']=statistics.median(entry['value'] for key,entry in actual)
        result['switches_source']='opt child wait4, not zero-valued perf :u switch events'
        scheduling.append(result)
    output=dict(native_stats_profiles=len(loss),raw_event_stats=loss,
        lost_record_count=sum(r['lost_records'] for r in loss),
        lost_sample_record_count=sum(r['lost_sample_records'] for r in loss),
        throttle_record_count=sum(r['throttle_records'] for r in loss),
        quality_checks=quality,scheduling=scheduling,
        scope_note='Requested unqualified software events were still reported with :u under perf_event_paranoid=2. Switches and opt RSS use wait4. Affinity is fixed; migrations are not established by zero perf values.')
    (a/'quality-summary.json').write_text(json.dumps(output,indent=2)+'\n')
    m.write_csv(a/'scheduling-summary.csv',scheduling)
    print(json.dumps({key:output[key] for key in ['native_stats_profiles','lost_record_count','lost_sample_record_count','throttle_record_count']},indent=2))


if __name__=='__main__':main()
