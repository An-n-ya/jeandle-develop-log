#!/usr/bin/env python3
"""Produce compact report tables from frozen profiling analysis outputs."""
import argparse,csv,collections,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--artifact',type=Path,required=True);args=p.parse_args();a=args.artifact
baseline=json.loads((a/'analysis/baseline-summary.json').read_text())['metrics']
stat=json.loads((a/'analysis/stat-summary.json').read_text())['metrics']
if (a/'l2-analysis/baseline-summary.json').exists():
 baseline.update(json.loads((a/'l2-analysis/baseline-summary.json').read_text())['metrics'])
 stat.update(json.loads((a/'l2-analysis/stat-summary.json').read_text())['metrics'])
profiles=json.loads((a/'attribution/summary.json').read_text())
bycase=collections.defaultdict(dict)
for r in profiles['summary']:bycase[r['case']][r['mode']]=r
parts=collections.defaultdict(lambda:collections.defaultdict(int))
totals=collections.defaultdict(int)
for r in csv.DictReader((a/'attribution/profile-runs.csv').open()):totals[r['case'],r['mode']]+=int(r['period_sum'])
for r in csv.DictReader((a/'attribution/attribution.csv').open()):parts[r['case'],r['mode']][r['category']]+=int(r['period_sum'])
modes=['origin','full','s0','s1']
out=[]
def title(s):out.append('\n'+s+'\n')
def table(headers,rows):
 out.append('| '+' | '.join(headers)+' |')
 out.append('| '+' | '.join('---' for h in headers)+' |')
 out.extend('| '+' | '.join(map(str,row))+' |' for row in rows)
caseorder=['deep-static','wide-static','leaf-static','tce-cha','virtual-cfg','cff-cache-reuse']
title('无采样中位数：user / wall 秒')
table(['场景','ORIGIN','FULL','S0','S1'],[[c]+[f"{baseline[c][m]['user_s']['median']:.4f} / {baseline[c][m]['wall_s']['median']:.4f}" for m in modes] for c in caseorder if c in baseline])
title('硬件事件：G cycles / IPC / branch miss %')
table(['场景','ORIGIN','FULL','S0','S1'],[[c]+[f"{stat[c][m]['cpu_atom']['cpu_atom/cycles/u']['median']/1e9:.3f} / {stat[c][m]['ipc']['median']:.3f} / {stat[c][m]['branch_misses_per_1000_branches']['median']/10:.3f}%" for m in modes] for c in caseorder if c in stat])
title('采样中位数：JavaType inclusive % / JavaType 内 LVI inclusive 占整进程 %')
table(['场景','ORIGIN','FULL','S0','S1'],[[c]+[f"{bycase[c][m]['jt_pct_median']:.2f} / {bycase[c][m]['jt_lvi_pct_median']:.2f}" for m in modes] for c in caseorder if c in bycase])
title('失效 inclusive 占整进程 cycles %，样本稀少时仅作量级参考')
table(['场景','ORIGIN','FULL','S0','S1'],[[c]+[f"{bycase[c][m]['invalid_pct_median']:.2f}" for m in modes] for c in caseorder if c in bycase])
title('样本数量：总样本 / JavaType 相关样本（三份累计）')
table(['场景','ORIGIN','FULL','S0','S1'],[[c]+[f"{bycase[c][m]['total_samples']} / {bycase[c][m]['total_jt_samples']}" for m in modes] for c in caseorder if c in bycase])
title('S1 排他分组，分母为整进程 period 权重，三份合并')
cats=['javatype/query_lvi','javatype/query_base','javatype/invalidation','javatype/lifecycle','external/parse','external/callback','external/lvi','external/dt']
rows=[]
for c in caseorder:
 if (c,'s1') not in parts:continue
 den=totals[c,'s1'];d=parts[c,'s1'];values=[100*d[k]/den for k in cats]
 rows.append([c]+[f'{v:.2f}' for v in values]+[f'{100-sum(values):.2f}'])
table(['场景','查询 LVI','基础类型','失效','JavaType 回收','解析','外部 replay','外部 LVI','外部 DT','其余/未细分'],rows)
title('采样质量：未知叶帧与 profile wall 开销')
rows=[]
for c in caseorder:
 if c not in bycase:continue
 r=bycase[c]['s1'];b=baseline[c]['s1']['wall_s']['median']
 rows.append([c,f"{r['unknown_pct_median']:.2f}%",f"{r['unknown_within_jt_pct_median']:.2f}%",f"{100*(r['elapsed_s_median']/b-1):.2f}%",f"{r['root_complete_pct_median']:.2f}%"])
table(['场景','全部未知叶帧','JavaType 内未知叶帧','wall 开销','栈到达 libc/start'],rows)
(a/'report-tables.md').write_text('\n'.join(out)+'\n')
print('tables written')
