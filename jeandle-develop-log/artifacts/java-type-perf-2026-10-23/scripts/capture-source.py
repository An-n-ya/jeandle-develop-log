import pathlib,json,hashlib
root=pathlib.Path('/home/annya/playground/jeandle/jeandle/jeandle-llvm')
specs={
'llvm/lib/Analysis/Jeandle/CachedJavaType.cpp':[(43,151),(1274,1373),(1450,1507)],
'llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp':[(119,143),(200,256)],
'llvm/lib/Analysis/Jeandle/LVINullEdgeOracle.cpp':[(1,43)],
'llvm/lib/Transforms/Jeandle/CHADevirtualization.cpp':[(320,353),(448,487),(607,622)],
'llvm/lib/Transforms/Jeandle/ConstantFieldFolding.cpp':[(735,770)],
'llvm/lib/Analysis/LazyValueInfo.cpp':[(869,973)],
'llvm/lib/Analysis/ValueTracking.cpp':[(8270,8359)]}
result=[]
for name,ranges in specs.items():
 data=(root/name).read_bytes();lines=data.decode().splitlines()
 result.append(dict(path=str(root/name),sha256=hashlib.sha256(data).hexdigest(),snippets=[dict(first=first,last=last,text='\n'.join(f'{i+1}: {lines[i]}' for i in range(first-1,min(last,len(lines))))) for first,last in ranges]))
print(json.dumps(result,indent=2))
