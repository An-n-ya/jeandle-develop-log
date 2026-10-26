from pathlib import Path
import subprocess, json, random, os, time, statistics, hashlib
out=Path("/home/annya/playground/jeandle/perf-results/2026-10-23-lvi-argument-undef")
bins={k:str(out/(k+"-opt")) for k in ("baseline","candidate")}
cases={}
for kind in ("related-may-undef","related-noundef","unrelated-may-undef","shared-boolean-may-undef"):
    lines=[]
    attr=" noundef" if kind=="related-noundef" else ""
    for f in range(4096):
        lines.append(f"define i64 @f{f}(i32{attr} %x, i32{attr} %y, i32{attr} %z) {{")
        previous="0"
        for i in range(32):
            lhs="%y" if kind=="unrelated-may-undef" else "%x"
            rhs="%z" if kind=="unrelated-may-undef" else "%x"
            lines.extend([f"  %lo{i} = icmp sgt i32 {lhs}, {i}",
                f"  %hi{i} = icmp slt i32 {rhs}, {100-i}",
                f"  %c{i} = and i1 %lo{i}, %hi{i}"])
            cond=f"%c{i}"
            if kind=="shared-boolean-may-undef":
                for j in range(4):
                    lines.append(f"  %d{i}_{j} = and i1 {cond}, {cond}")
                    cond=f"%d{i}_{j}"
            lines.append(f"  %s{i} = select i1 {cond}, i32 %x, i32 {previous}")
            previous=f"%s{i}"
        lines.extend([f"  %r = sext i32 {previous} to i64","  ret i64 %r","}"])
    p=out/(kind+".ll")
    p.write_text("\n".join(lines)+"\n")
    cases[kind]=p
def cmd(k,v,verify=False):
    return ["taskset","-c","16",bins[v],str(cases[k]),"-passes=correlated-propagation",*(["-verify-each"] if verify else []),"-S" if verify else "-disable-output"]
def output_hash(k,v):
    h=hashlib.sha256()
    p=subprocess.Popen(cmd(k,v,True),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    for b in iter(lambda:p.stdout.read(1024*1024),b""):h.update(b)
    e=p.stderr.read()
    assert p.wait()==0,e
    return h.hexdigest()
checks={}
for k in cases:
    checks[k]={v:output_hash(k,v) for v in bins}
    assert len(set(checks[k].values()))==1
    print("STRESS_OUTPUT_EQUAL",k,flush=True)
    for v in bins:subprocess.run(cmd(k,v),check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
(out/"stress-output-equality.json").write_text(json.dumps(checks,indent=2))
rows=[]
rng=random.Random(20261024)
for round in range(10):
    names=list(cases);rng.shuffle(names)
    for k in names:
        variants=list(bins);rng.shuffle(variants)
        for v in variants:
            start=time.perf_counter()
            p=subprocess.Popen(cmd(k,v),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            _,status,r=os.wait4(p.pid,0)
            p.returncode=os.waitstatus_to_exitcode(status)
            assert p.returncode==0,p.stderr.read()
            rows.append({"round":round,"case":k,"variant":v,"wall":time.perf_counter()-start,"user":r.ru_utime,"system":r.ru_stime})
    (out/"stress-timings.json").write_text(json.dumps(rows,indent=2))
    print("STRESS_ROUND",round,flush=True)
summary={}
for k in cases:
    rr=[r for r in rows if r["case"]==k]
    paired=[]
    for i in range(10):
        p={r["variant"]:r["user"] for r in rr if r["round"]==i}
        paired.append(100*(1-p["candidate"]/p["baseline"]))
    summary[k]={"baseline_user_median":statistics.median([r["user"] for r in rr if r["variant"]=="baseline"]),"candidate_user_median":statistics.median([r["user"] for r in rr if r["variant"]=="candidate"]),"paired_reduction_pct_median":statistics.median(paired),"paired_reductions_pct":paired}
(out/"stress-summary.json").write_text(json.dumps(summary,indent=2))
print("STRESS_COMPLETE",json.dumps(summary),flush=True)

