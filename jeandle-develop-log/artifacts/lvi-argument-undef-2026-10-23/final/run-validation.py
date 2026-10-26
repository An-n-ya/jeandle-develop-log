from pathlib import Path
import json, subprocess, hashlib, os, time, random, statistics, csv
root=Path("/home/annya/playground/jeandle/jeandle/jeandle-llvm")
out=Path("/home/annya/playground/jeandle/perf-results/2026-10-23-lvi-argument-undef")
old=Path("/home/annya/playground/jeandle/perf-results/2026-10-23-javatype-perf/run")
manifest=json.loads((old/"manifest.json").read_text())
cases=dict(manifest["cases"])
cases.update(manifest["l2"])
bins={"baseline":str(out/"baseline-opt"),"candidate":str(out/"candidate-opt")}
def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
identity={"base":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),
"branch":subprocess.check_output(["git","branch","--show-current"],cwd=root,text=True).strip(),
"binaries":{k:{"path":v,"sha256":sha(v)} for k,v in bins.items()},
"inputs":{k:{"ir":v["ir"],"ir_sha256":sha(v["ir"]),"cblog_sha256":sha(v["cblog"]),"passes":v["passes"]} for k,v in cases.items()},
"cpu":16,"rounds":10,"warmups":1,"seed":20261023,"timing_verify_each":False}
(out/"identity.json").write_text(json.dumps(identity,indent=2))
subprocess.run(["git","diff","--binary"],cwd=root,stdout=(out/"candidate.patch").open("w"),check=True)
def cmd(case,variant,verify=False):
    v=cases[case]
    return ["taskset","-c","16",bins[variant],"-S" if verify else "-disable-output",f"-passes=function({v['passes']})",*(["-verify-each"] if verify else []),f"-jeandle-vm-callback-log={v['cblog']}","-jeandle-java-type-stats=false","-jeandle-verify-java-type-cache=false",v["ir"]]
checks={}
for case in cases:
    hashes={}
    for variant in bins:
        path=out/"verify-output.tmp"
        with path.open("wb") as f, (out/f"verify-{case}-{variant}.stderr").open("wb") as e:
            subprocess.run(cmd(case,variant,True),stdout=f,stderr=e,check=True)
        hashes[variant]=sha(path)
        path.unlink()
    assert hashes["baseline"]==hashes["candidate"], (case,hashes)
    checks[case]=hashes
    (out/"output-equality.json").write_text(json.dumps(checks,indent=2))
    print("OUTPUT_EQUAL",case,flush=True)
test=root/"llvm/test/Transforms/CorrelatedValuePropagation/select-demand-undef.ll"
candidate=subprocess.check_output([bins["candidate"],str(test),"-passes=correlated-propagation","-verify-each","-S"])
assert candidate==(out/"select-demand-undef.baseline.ll").read_bytes()
print("NEW_TEST_OUTPUT_EQUAL",flush=True)
for case in cases:
    for variant in bins:
        subprocess.run(cmd(case,variant),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
    print("WARMED",case,flush=True)
rows=[]
rng=random.Random(20261023)
def measure(command,stderr):
    with stderr.open("wb") as e:
        start=time.perf_counter()
        p=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=e)
        _,status,r=os.wait4(p.pid,0)
        wall=time.perf_counter()-start
        p.returncode=os.waitstatus_to_exitcode(status)
    assert p.returncode==0,(p.returncode,command)
    return {"user":r.ru_utime,"system":r.ru_stime,"wall":wall,"rss_kib":r.ru_maxrss,"voluntary_cs":r.ru_nvcsw,"involuntary_cs":r.ru_nivcsw}
for round in range(10):
    names=list(cases)
    rng.shuffle(names)
    for case in names:
        order=list(bins)
        rng.shuffle(order)
        for variant in order:
            row={"round":round,"case":case,"variant":variant,"order":order.index(variant),"argv":cmd(case,variant)}
            row.update(measure(row["argv"],out/f"time-{case}-{round}-{variant}.stderr"))
            rows.append(row)
            (out/"timings.json").write_text(json.dumps(rows,indent=2))
        pair={r["variant"]:r["user"] for r in rows if r["round"]==round and r["case"]==case}
        print("PAIR",round,case,pair,flush=True)
    summary={}
    for case in cases:
        cr=[r for r in rows if r["case"]==case]
        b=[r["user"] for r in cr if r["variant"]=="baseline"]
        c=[r["user"] for r in cr if r["variant"]=="candidate"]
        reductions=[]
        for i in range(round+1):
            p={r["variant"]:r["user"] for r in cr if r["round"]==i}
            reductions.append(100*(1-p["candidate"]/p["baseline"]))
        summary[case]={"rounds":round+1,"baseline_user_median":statistics.median(b),"candidate_user_median":statistics.median(c),"paired_reduction_pct_median":statistics.median(reductions),"paired_reductions_pct":reductions}
    (out/"summary.json").write_text(json.dumps(summary,indent=2))
    print("ROUND_DONE",round,flush=True)
assert all(sha(v["path"])==v["sha256"] for v in identity["binaries"].values())
print("COMPLETE",json.dumps(summary),flush=True)

