import pathlib,subprocess,time,sys
root=pathlib.Path('/home/annya/playground/jeandle/perf-results/2026-10-23-javatype-perf')
start=time.monotonic()
while len(list((root/'run/profiles').glob('*/*/run-*/SUCCESS')))<60:
 if time.monotonic()-start>3600: raise SystemExit('L1 profiles incomplete after timeout')
 time.sleep(10)
time.sleep(10)
base=['python3',str(root/'profile-l2.py'),'--runner','/home/annya/playground/jeandle/jeandle/jeandle-llvm/llvm/utils/jeandle/profile-java-type-cache.py','--out',str(root/'run'),'--source-root','/home/annya/playground/jeandle/jeandle/jeandle-llvm','--opt','/home/annya/playground/jeandle/jeandle/jeandle-llvm/build/build-ninja-profiling/bin/opt','--cpu','16']
for phase,repeats in [('baseline',10),('stat',3),('record',3)]:
 print('starting L2 '+phase,flush=True)
 subprocess.run(base+[phase,'--repeats',str(repeats),'--warmups','3'],check=True)
(root/'L2_COMPLETE').write_text('baseline10/stat3/record3 completed\n')
