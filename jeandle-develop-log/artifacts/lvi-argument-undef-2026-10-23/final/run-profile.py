from pathlib import Path
import json, subprocess, random
root=Path("/home/annya/playground/jeandle/jeandle/jeandle-llvm")
out=Path("/home/annya/playground/jeandle/perf-results/2026-10-23-lvi-argument-undef")
m=json.loads((Path("/home/annya/playground/jeandle/perf-results/2026-10-23-javatype-perf/run/manifest.json")).read_text())
case=m["cases"]["deep-static"]
records=[]
rng=random.Random(20261025)
for run in range(2):
    variants=["baseline","candidate"];rng.shuffle(variants)
    for variant in variants:
        stem=out/f"profile-deep-{run}-{variant}"
        command=["taskset","-c","16",str(out/(variant+"-opt")),"-disable-output",f"-passes=function({case['passes']})","-jeandle-java-type-stats=false","-jeandle-verify-java-type-cache=false",f"-jeandle-vm-callback-log={case['cblog']}",case["ir"]]
        rec=["perf","record","-e","cycles:u","-F","199","--call-graph","dwarf,8192","-o",str(stem)+".data","--",*command]
        with Path(str(stem)+".record.stderr").open("w") as e:
            subprocess.run(rec,stdout=subprocess.DEVNULL,stderr=e,check=True)
        for name,cmd in [
            ("self.txt",["perf","report","--stdio","--no-children","--no-inline","-n","--percent-limit","0","--sort","symbol","-i",str(stem)+".data"]),
            ("stacks.txt",["perf","script","--no-inline","-F","+period","-i",str(stem)+".data"]),
            ("header.txt",["perf","report","--header-only","-i",str(stem)+".data"])]:
            with Path(str(stem)+"."+name).open("w") as f,Path(str(stem)+"."+name+".stderr").open("w") as e:
                subprocess.run(cmd,stdout=f,stderr=e,check=True)
        records.append({"run":run,"variant":variant,"record_argv":rec})
        (out/"profile-commands.json").write_text(json.dumps(records,indent=2))
        print("PROFILE_COMPLETE",run,variant,flush=True)

