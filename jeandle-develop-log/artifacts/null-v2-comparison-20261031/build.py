import subprocess,shlex
from pathlib import Path
root=Path('/home/annya/playground/jeandle/jeandle');v2=root/'jeandle-llvm';vb=v2/'build/build-ninja-release';config=vb/'bin/llvm-config'
for name,src,b in [('base',root/'jeandle-llvm-null-edge-baseline',root/'jeandle-llvm-null-edge-baseline/build'),('null',root/'jeandle-llvm-null-edge-benchmark',root/'jeandle-llvm-null-edge-benchmark/build'),('v2',v2,vb)]:
 def flags(*args):
  s=subprocess.check_output([str(config),*args],text=True).replace(str(vb),str(b)).replace(str(v2/'llvm/include'),str(src/'llvm/include'))
  return shlex.split(s)
 cmd=[str(root/'tools/bin/g++'),'driver.cpp','-I.']+(['-DBENCH_USE_V2'] if name=='v2' else [])+flags('--cxxflags')+['-O3','-DNDEBUG']+flags('--ldflags','--link-static','--libs','analysis','asmparser','core','--system-libs')+['-o','replay-'+name]
 subprocess.run(cmd,check=True)
 print('built',name,flush=True)
