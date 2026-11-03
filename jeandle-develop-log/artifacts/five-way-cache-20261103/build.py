import subprocess,shlex,os
from pathlib import Path
root=Path('/home/annya/playground/jeandle/jeandle')
os.chdir(Path(__file__).resolve().parent)
config=root/'jeandle-llvm-final-cache-bench-20261103/build/bin/llvm-config'
def flags(*args):
 return shlex.split(subprocess.check_output([str(config),*args],text=True))
cmd=[str(root/'tools/bin/g++'),'driver-new.cpp','-I.','-DBENCH_USE_NEW']+flags('--cxxflags')+['-O3','-DNDEBUG']+flags('--ldflags','--link-static','--libs','analysis','asmparser','core','--system-libs')+['-o','replay-new']
Path('new-driver-command.txt').write_text(shlex.join(cmd)+'\n')
subprocess.run(cmd,check=True)
print('built new',flush=True)
