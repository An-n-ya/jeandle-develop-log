#!/usr/bin/env python3
"""Validate attribution invariants and prevent parameter-type false positives."""
import importlib.util
import csv
import collections
import sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('attribute',Path(__file__).with_name('attribute-stacks.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
def f(name,native):return {'name':name,'native':native}
x=a.classify({'frames':[f('getCachedJavaType','llvm::jeandle::getCachedJavaType(llvm::DominatorTree*, llvm::LazyValueInfo&)'),f('optimizeCallSite','optimizeCallSite(llvm::LazyValueInfo&, llvm::DominatorTree&)')]})
assert x['query'] and not x['lvi'] and not x['dt'],x
x=a.classify({'frames':[f('solveBlockValueSelect','llvm::LazyValueInfoImpl::solveBlockValueSelect(llvm::SelectInst*, llvm::BasicBlock*)'),f('getCachedJavaType','llvm::jeandle::getCachedJavaType(llvm::Value*)')]})
assert x['group']=='javatype/query_lvi',x
x=a.classify({'frames':[f('erase','llvm::jeandle::JavaTypeCache::invalidate(llvm::ArrayRef<llvm::Value*>, bool)')]})
assert x['invalid'] and x['group']=='javatype/invalidation',x
if len(sys.argv)>1:
 sums=collections.defaultdict(float)
 for row in csv.DictReader((Path(sys.argv[1])/'attribution.csv').open()):
  sums[row['case'],row['mode'],row['run']]+=float(row['pct_process'])
 assert sums and all(abs(v-100)<1e-7 for v in sums.values()),sums
 print('verified disjoint partition:',len(sums),'profiles')
print('classification checks passed')
