from pathlib import Path
import re, json
out=Path("/home/annya/playground/jeandle/perf-results/2026-10-23-lvi-argument-undef")
proof_re=re.compile(r"(?:isGuaranteedNotToBeUndef(?:OrPoison)?|programUndefinedIfUndefOrPoison)\(")
lvi_re=re.compile(r"LazyValueInfo(?:Impl)?::[A-Za-z_][^( ]*\(")
rows=[]
for p in sorted(out.glob("profile-deep-*.stacks.txt")):
    name=p.name
    variant="candidate" if "candidate" in name else "baseline"
    row={"file":name,"variant":variant,"samples":0,"total_period":0,"lvi_period":0,"proof_period":0,"select_proof_period":0}
    for block in p.read_text().split("\n\n"):
        lines=block.splitlines()
        if not lines:continue
        m=re.search(r"\s(\d+)\s+\S*cycles\S*:\s*$",lines[0])
        if not m:continue
        period=int(m.group(1));row["samples"]+=1;row["total_period"]+=period
        stack="\n".join(lines[1:])
        isproof=bool(proof_re.search(stack))
        if lvi_re.search(stack):row["lvi_period"]+=period
        if isproof:row["proof_period"]+=period
        if isproof and "solveBlockValueSelect(" in stack:row["select_proof_period"]+=period
    assert row["samples"]>0,name
    for category in ("lvi","proof","select_proof"):
        row[category+"_inclusive_pct"]=100*row[category+"_period"]/row["total_period"]
    rows.append(row)
assert len(rows)==4,len(rows)
aggregate={}
for variant in ("baseline","candidate"):
    group=[r for r in rows if r["variant"]==variant]
    total=sum(r["total_period"] for r in group)
    aggregate[variant]={"samples":sum(r["samples"] for r in group),"total_period":total,
      **{cat+"_inclusive_pct":100*sum(r[cat+"_period"] for r in group)/total for cat in ("lvi","proof","select_proof")}}
result={"method":"period-weighted native stack membership; inclusive categories overlap; two deep-static profiles per variant; 199 Hz DWARF 8192","runs":rows,"aggregate":aggregate}
(out/"profile-summary.json").write_text(json.dumps(result,indent=2))
print(json.dumps(aggregate,indent=2))

