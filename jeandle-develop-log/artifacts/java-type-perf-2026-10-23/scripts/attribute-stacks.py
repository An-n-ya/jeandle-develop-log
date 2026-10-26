#!/usr/bin/env python3
"""Attribute cycle-weighted perf script stacks, enriched with native symbols.

Each sample contributes exactly once to the process partition. Inclusive views
are separate, de-duplicate recursion, and must never be added to the partition.
Only opt cpu_atom/cycles/u samples enter the denominator. Missing libc symbols
remain unknown even when a resolved ancestor permits subtree attribution.
"""
import argparse
import bisect
import collections
import csv
import gzip
import json
import re
import statistics
from pathlib import Path


HEADER = re.compile(r"^(\S+)\s+(\d+)\s+([\d.]+):\s+(\d+)\s+(.+):\s*$")
FRAME = re.compile(r"^\s+([a-fA-F0-9]+)\s+(.+)$")


class Symbols:
    def __init__(self, path):
        self.rows = []
        with gzip.open(path, 'rt') as stream:
            for line in stream:
                match = re.match(r'([0-9a-f]+) ([0-9a-f]+) ([tTwW]) (.*)', line)
                if match:
                    self.rows.append((int(match[1],16), int(match[2],16),match[4]))
        self.rows.sort()
        self.addresses = [row[0] for row in self.rows]
        self.start = next(row[0] for row in self.rows if row[2] == '_start')

    def lookup(self, address):
        index = bisect.bisect_right(self.addresses, address)-1
        if index < 0:
            return ''
        start, size, name = self.rows[index]
        return name if start <= address < start+size else ''


def parse(path, symbols):
    result, sample = [], None
    with path.open(errors='replace') as stream:
        for line in stream:
            match = HEADER.match(line.rstrip())
            if match:
                if sample:
                    result.append(sample)
                sample = {'comm': match[1], 'event': match[5],
                          'period': int(match[4]), 'frames': []}
            elif sample:
                match = FRAME.match(line.rstrip())
                if match:
                    address, raw = int(match[1],16), match[2]
                    inline = raw.endswith(' (inlined)')
                    raw = re.sub(r' \((?:inlined|/.*|\[.*)\)$','',raw)
                    offset = re.search(r'\+0x([0-9a-f]+)$',raw)
                    offset = int(offset[1],16) if offset else 0
                    name = re.sub(r'\+0x[0-9a-f]+$','',raw)
                    sample['frames'].append({'ip':address,'name':name,
                                              'offset':offset,'inline':inline})
    if sample:
        result.append(sample)
    roots = [frame['ip']-frame['offset']-symbols.start
             for sample in result for frame in sample['frames']
             if frame['name']=='_start']
    base = collections.Counter(roots).most_common(1)[0][0] if roots else None
    for sample in result:
        for frame in sample['frames']:
            frame['native'] = symbols.lookup(frame['ip']-base) if base is not None else ''
    return result, base


def contains(frames, needles):
    return any(needle in name for name in frames for needle in needles)


def classify(sample):
    frames = sample['frames']
    names = [frame['name'] for frame in frames]
    native = [re.sub(r' \[clone .*?\]', '', frame['native']).replace('(anonymous namespace)::', '').split('(', 1)[0] for frame in frames if frame['native']]
    function_names = [re.sub(r' \[clone .*?\]', '', name).replace('(anonymous namespace)::', '').split('(', 1)[0] for name in names]
    allnames = function_names+native
    invalid = contains(allnames, ('JavaTypeCache::invalidate',
                                  'JavaTypeAnalysisResult::invalidateImpl'))
    lifecycle = contains(allnames, ('~JavaTypeCache', '~JavaTypeAnalysisResult',
        'AnalysisResultModel<llvm::Function, llvm::jeandle::JavaTypeAnalysis'))
    query = contains(allnames, ('getJavaType', 'getCachedJavaType',
                              'getBaseJavaType', 'phiValueType', 'factsAt'))
    lvi = contains(allnames, ('LazyValueInfo', 'getPredicateOnEdge', 'getValueOnEdge',
                              'solveBlockValue', 'isNullEdge'))
    callback = contains(allnames, ('VMCallbacksLog', 'VMCallbacksRecorder',
                                   'vmCallbacksLog', 'Replay', 'replay', 'CallbackLog'))
    dt = contains(allnames, ('DominatorTree', 'DomTreeBuilder', 'SemiNCAInfo'))
    parser = contains(allnames, ('parseIR', 'parseAssembly', 'LLParser::',
                                 'LLLexer::', 'parseBitcode'))
    base = contains(allnames, ('getBaseJavaType','valueDimension','phiValueType'))
    facts = contains(allnames, ('factsAt','edgeGuard','traceToCheckInstanceof'))
    leaf = names[0] if names else '[missing]'
    alloc = contains([leaf], ('malloc','free','realloc','calloc', 'operator new',
                             'operator delete','allocate_buffer', 'deallocate'))
    container = contains([leaf], ('DenseMap','DenseSet','SmallPtrSet','SmallVector',
                                  'try_emplace','LookupBucket','FindAndConstruct',
                                  'getHashValue','grow','insertIntoBucket'))
    typeops = contains(allnames, ('typeUnion','typeIntersect','mergePathFacts',
                                  'unionExcludedKlasses', 'isExcludedBy'))
    unknown = '[unknown]' in leaf or leaf == '[missing]'
    value_transfer = contains(allnames, ('JavaType::JavaType', 'JavaType::~JavaType', 'JavaType::operator='))
    heap = contains(allnames, ('malloc', 'calloc', 'realloc', 'cfree', 'operator new', 'operator delete', 'allocate_buffer', 'deallocate_buffer'))
    # Primary partition uses the most specific resolved semantic subtree.
    if invalid:
        group = 'javatype/invalidation'
    elif lifecycle:
        group = 'javatype/lifecycle'
    elif query:
        if lvi:
            group = 'javatype/query_lvi'
        elif callback:
            group = 'javatype/query_callback'
        elif alloc:
            group = 'javatype/query_allocation'
        elif container:
            group = 'javatype/query_container'
        elif base:
            group = 'javatype/query_base'
        elif facts:
            group = 'javatype/query_facts_other'
        elif typeops:
            group = 'javatype/query_type_operations'
        else:
            group = 'javatype/query_other'
    elif parser:
        group = 'external/parse'
    elif callback:
        group = 'external/callback'
    elif lvi:
        group = 'external/lvi'
    elif dt:
        group = 'external/dt'
    elif alloc:
        group = 'external/allocation'
    elif unknown:
        group = 'external/unknown'
    else:
        group = 'external/other'
    jt = invalid or lifecycle or query
    if contains(allnames, ('TypeCheckElimination::', 'tryEliminateTypeCheck')):
        consumer = 'TCE'
    elif contains(allnames, ('ConstantFieldFolding::','foldFieldLoad',
            'foldLoadKlassCall','foldLoadMirrorKlassCall','foldGetClassCall',
            'foldLayoutHelperCall','foldKlassInitializedCall')):
        consumer = 'CFF'
    elif contains(allnames, ('CHADevirtualization::','optimizeCallSite',
                             'optimizeMhIntrinsic','tryNarrowJavaObjType')):
        consumer = 'CHA'
    elif contains(allnames, ('RecoverTypeInfo',)):
        consumer = 'RecoverTypeInfo'
    elif lifecycle:
        consumer = 'FAM lifecycle'
    else:
        consumer = 'unresolved consumer'
    return dict(group=group,jt=jt,query=query,invalid=invalid,lifecycle=lifecycle,
                lvi=lvi,callback=callback,dt=dt,unknown=unknown,consumer=consumer,
                value_transfer=value_transfer,heap=heap,
                root_complete=contains(names, ('_start', '__libc_start_main')),
                query_boundary=contains(names,('getJavaType','getCachedJavaType')))


def write_csv(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:
        return
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--symbols',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    symbols=Symbols(args.symbols)
    args.out.mkdir(parents=True,exist_ok=True)
    runs,partitions,consumers,inclusive_rows,top_rows = [],[],[],[],[]
    folded = collections.Counter()
    for path in sorted(args.run.glob('**/profiles/*/*/run-*/stacks.txt')):
        case,mode,run = path.parts[-4:-1]
        samples,image_base=parse(path,symbols)
        samples=[s for s in samples if s['comm']=='opt' and s['event']=='cpu_atom/cycles/u']
        total=sum(s['period'] for s in samples)
        if not total:
            continue
        groups=collections.Counter();counts=collections.Counter()
        who=collections.Counter();inc=collections.Counter();incn=collections.Counter()
        self_symbols=collections.Counter();jt_symbols=collections.Counter()
        for sample in samples:
            info=classify(sample);period=sample['period']
            groups[info['group']]+=period;counts[info['group']]+=1
            for key in ('jt','query','invalid','lifecycle','unknown','root_complete'):
                if info[key]:inc[key]+=period;incn[key]+=1
            if info['jt']:
                who[info['consumer']]+=period
                for key in ('lvi','callback','dt','unknown','query_boundary','value_transfer','heap'):
                    if info[key]:inc['jt_'+key]+=period;incn['jt_'+key]+=1
            frames=sample['frames']
            leaf=frames[0]['name'] if frames else '[missing]'
            self_symbols[leaf]+=period
            if info['jt']: jt_symbols[leaf]+=period
            # One recursion-deduplicated folded path; native symbols add clarity
            # only for ambiguous generic inline names, never create extra samples.
            if case=='deep-static' and mode=='s1':
                display=[]
                for frame in reversed(frames):
                    name=frame['name']
                    if name in ('run','invalidate','clear','operator()'):
                        name=frame['native'] or name
                    name=name.replace(';',':')
                    if name not in display:display.append(name)
                folded[';'.join(display)]+=period
        metadata=json.loads((path.parent/'run.json').read_text())
        row=dict(case=case,mode=mode,run=run,samples=len(samples),period_sum=total,
                 elapsed_s=metadata['elapsed_ns']/1e9,image_base_known=image_base is not None)
        for key in ('jt','query','invalid','lifecycle','unknown','root_complete',
                    'jt_lvi','jt_callback','jt_dt','jt_unknown','jt_query_boundary','jt_value_transfer','jt_heap'):
            row[key+'_samples']=incn[key];row[key+'_pct']=100*inc[key]/total
        row['unknown_within_jt_pct']=100*inc['jt_unknown']/inc['jt'] if inc['jt'] else 0
        row['full_entry_within_jt_pct']=100*inc['jt_query_boundary']/inc['jt'] if inc['jt'] else 0
        runs.append(row)
        for group,weight in groups.items():
            partitions.append(dict(case=case,mode=mode,run=run,category=group,
                samples=counts[group],period_sum=weight,pct_process=100*weight/total,
                pct_javatype=100*weight/inc['jt'] if group.startswith('javatype/') and inc['jt'] else ''))
        for name,weight in who.items():
            consumers.append(dict(case=case,mode=mode,run=run,consumer=name,
                period_sum=weight,pct_process=100*weight/total,pct_javatype=100*weight/inc['jt']))
        for category,key in [('process','all'),('javatype','jt')]:
            for name,weight in (self_symbols if key=='all' else jt_symbols).most_common(30):
                top_rows.append(dict(case=case,mode=mode,run=run,scope=category,
                    leaf_symbol=name,period_sum=weight,pct_process=100*weight/total))
    write_csv(args.out/'profile-runs.csv',runs)
    write_csv(args.out/'attribution.csv',partitions)
    write_csv(args.out/'consumers.csv',consumers)
    write_csv(args.out/'self-top.csv',top_rows)
    summary=[]
    for case,mode in sorted({(r['case'],r['mode']) for r in runs}):
        rows=[r for r in runs if r['case']==case and r['mode']==mode]
        item={'case':case,'mode':mode,'runs':len(rows),
              'total_samples':sum(r['samples'] for r in rows),
              'total_jt_samples':sum(r['jt_samples'] for r in rows)}
        for key in ('jt_pct','query_pct','invalid_pct','lifecycle_pct','unknown_pct',
                    'jt_lvi_pct','jt_callback_pct','jt_unknown_pct','jt_value_transfer_pct','jt_heap_pct',
                    'unknown_within_jt_pct','root_complete_pct','elapsed_s'):
            values=[r[key] for r in rows]
            item[key+'_median']=statistics.median(values)
            item[key+'_min']=min(values);item[key+'_max']=max(values)
        summary.append(item)
    write_csv(args.out/'profile-summary.csv',summary)
    (args.out/'summary.json').write_text(json.dumps({'profiles':runs,'summary':summary},indent=2)+'\n')
    (args.out/'deep-static-s1.folded').write_text(''.join(f'{path} {period}\n' for path,period in folded.items()))
    print(f'{len(runs)} profiles, {len(summary)} case/modes')


if __name__=='__main__':
    main()
