#!/usr/bin/env python3
"""Summarize the raw JavaType cache reuse diagnostics into JSON/CSV."""

import csv
import json
import re
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "remote-results"
SUMMARY = ROOT / "summary"

QUERY_RE = re.compile(
    r"^JavaTypeQuery function: (?P<function>\S+) ordinal: (?P<ordinal>\d+) "
    r"value: (?P<value>\S+) context: (?P<context>\S+) "
    r"base_hits: (?P<base_hits>\d+) base_misses: (?P<base_misses>\d+) "
    r"facts_hits: (?P<facts_hits>\d+) facts_misses: (?P<facts_misses>\d+) "
    r"final_hits: (?P<final_hits>\d+) final_misses: (?P<final_misses>\d+) "
    r"base_insertions: (?P<base_insertions>\d+)$"
)

CASES = [
    {
        "key": "p1-tce-same-block",
        "phase": "P1",
        "case_id": "T01-same-block",
        "input": "tce-same-block.ll",
        "pipeline": "type-check-elimination,print<java-type-analysis>",
        "mode": "IN-PASS",
        "diagnostic": "tce-same-block",
        "verification": "tce-same-block",
        "result": "4 queries; 3 Final hits; 1 Base insertion; 4 checks remain",
    },
    {
        "key": "p1-tce-shallow",
        "phase": "P1",
        "case_id": "T01-shallow",
        "input": "tce-shallow.ll",
        "pipeline": "type-check-elimination,print<java-type-analysis>",
        "mode": "IN-PASS",
        "diagnostic": "tce-shallow",
        "verification": "tce-shallow",
        "result": "4 sibling-block queries; 0 Final/PathFacts hits; Base reused",
    },
    {
        "key": "p1-tce-deep",
        "phase": "P1",
        "case_id": "T01-deep",
        "input": "tce-deep.ll",
        "pipeline": "type-check-elimination,print<java-type-analysis>",
        "mode": "IN-PASS",
        "diagnostic": "tce-deep",
        "verification": "tce-deep",
        "result": "4 queries; first check remains; 3 fold; Final dropped, Base retained",
    },
    {
        "key": "p4-zero-overlap",
        "phase": "P4",
        "case_id": "NEG-zero-overlap",
        "input": "tce-zero-overlap.ll",
        "pipeline": "type-check-elimination,print<java-type-analysis>",
        "mode": "IN-PASS",
        "diagnostic": "tce-zero-overlap",
        "verification": "tce-zero-overlap",
        "result": "negative control; 4 queries, 0 hits, 4 Base insertions",
    },
    {
        "key": "p1-recover-shallow",
        "phase": "P1",
        "case_id": "T02-shallow",
        "input": "recover-shallow.ll",
        "pipeline": "recover-type-info,print<java-type-analysis>",
        "mode": "IN-PASS",
        "diagnostic": "recover-shallow",
        "verification": "recover-shallow",
        "result": "2 field loads share one Base; Final 0/2; metadata 7 and 9",
    },
    {
        "key": "p2-x01-cross-pass",
        "phase": "P2",
        "case_id": "X01-CROSS-PASS",
        "input": "tce-recover-cross-pass.ll",
        "pipeline": "type-check-elimination,recover-type-info,print<java-type-analysis>",
        "mode": "CROSS-PASS",
        "diagnostic": "x01-cross",
        "verification": "x01-cross",
        "result": "downstream ordinals 3-4 are Final hits on TCE entries; Base insertions stay 1",
    },
    {
        "key": "p2-x01-pass-local",
        "phase": "P2",
        "case_id": "X01-PASS-LOCAL",
        "input": "tce-recover-cross-pass.ll",
        "pipeline": "type-check-elimination,boundary,recover-type-info,print<java-type-analysis>",
        "mode": "PASS-LOCAL",
        "diagnostic": "x01-local",
        "verification": "x01-local",
        "result": "boundary clears existing analysis; downstream first query misses; Base insertions become 2",
    },
    {
        "key": "p2-x03-cross-pass",
        "phase": "P2",
        "case_id": "X03-CROSS-PASS",
        "input": "tce-fold-recover.ll",
        "pipeline": "type-check-elimination,recover-type-info,print<java-type-analysis>",
        "mode": "CROSS-PASS",
        "diagnostic": "x03-cross",
        "verification": "x03-cross",
        "result": "fold drops Final but retains Base; downstream reuses Base with no new insertion",
    },
    {
        "key": "p2-x03-pass-local",
        "phase": "P2",
        "case_id": "X03-PASS-LOCAL",
        "input": "tce-fold-recover.ll",
        "pipeline": "type-check-elimination,boundary,recover-type-info,print<java-type-analysis>",
        "mode": "PASS-LOCAL",
        "diagnostic": "x03-local",
        "verification": "x03-local",
        "result": "boundary clears surviving Base; downstream Base insertions become 2",
    },
    {
        "key": "p3-x02-tce-cff",
        "phase": "P3",
        "case_id": "X02-TCE-to-CFF",
        "input": "tce-cff-cross-pass.ll",
        "pipeline": "type-check-elimination,constant-field-folding,print<java-type-analysis>",
        "mode": "CROSS-PASS",
        "diagnostic": "x02-tce-cff",
        "verification": "x02-tce-cff",
        "result": "second consumer's first query is a Final hit; Base insertions stay 1",
    },
    {
        "key": "p3-x04-cff-tce",
        "phase": "P3",
        "case_id": "X04-CFF-to-TCE",
        "input": "tce-cff-cross-pass.ll",
        "pipeline": "constant-field-folding,type-check-elimination,print<java-type-analysis>",
        "mode": "CROSS-PASS",
        "diagnostic": "x04-cff-tce",
        "verification": "x04-cff-tce",
        "result": "second consumer's first query is a Final hit; Base insertions stay 1",
    },
    {
        "key": "p3-cff-nonexact",
        "phase": "P3",
        "case_id": "T03-CFF-nonexact",
        "input": "cff-nonexact.ll",
        "pipeline": "constant-field-folding,print<java-type-analysis>",
        "mode": "IN-PASS",
        "diagnostic": "cff-nonexact",
        "verification": "cff-nonexact",
        "result": "2 getJavaType queries, 1 Final hit, no fold",
    },
    {
        "key": "p3-cha-shallow",
        "phase": "P3",
        "case_id": "T04-CHA-shallow",
        "input": "cha-shallow.ll",
        "pipeline": "cha-devirtualization,print<java-type-analysis>",
        "mode": "IN-PASS",
        "diagnostic": "cha-shallow",
        "verification": "cha-shallow",
        "result": "4 queries/rewrites; 4 CFG invalidations; Final dropped, Base retained",
    },
    {
        "key": "p3-cha-deep",
        "phase": "P3",
        "case_id": "T04-CHA-deep",
        "input": "cha-deep.ll",
        "pipeline": "cha-devirtualization,print<java-type-analysis>",
        "mode": "IN-PASS",
        "diagnostic": "cha-deep",
        "verification": "cha-deep",
        "result": "4 queries/rewrites; 4 CFG invalidations; Final dropped, Base retained",
    },
    {
        "key": "p3-x05-recover-cha",
        "phase": "P3",
        "case_id": "X05-Recover-to-CHA",
        "input": "recover-cha-boundary.ll",
        "pipeline": "recover-type-info,boundary,cha-devirtualization,print<java-type-analysis>",
        "mode": "LIFECYCLE-BOUNDARY",
        "diagnostic": "x05-recover-cha",
        "verification": "x05-recover-cha",
        "result": "boundary existing_analysis=0; CHA starts cold and reads recovered metadata",
    },
    {
        "key": "p3-x06-cff-modify-tce",
        "phase": "P3",
        "case_id": "X06-CFF-modify-to-TCE",
        "input": "cff-modify-tce.ll",
        "pipeline": "constant-field-folding,boundary,type-check-elimination,print<java-type-analysis>",
        "mode": "LIFECYCLE-BOUNDARY",
        "diagnostic": "x06-cff-modify-tce",
        "verification": "x06-cff-modify-tce",
        "result": "boundary existing_analysis=0; TCE starts cold; no old-cache hit claimed",
    },
    {
        "key": "p4-x07-production-pea-off",
        "phase": "P4",
        "case_id": "X07-production-PEA-off",
        "input": "x07-production-pipeline.ll",
        "pipeline": "--jeandle --jeandle-pea-iterations=0",
        "mode": "ACTUAL-PIPELINE-PARTIAL",
        "diagnostic": "x07-production-pea-off",
        "verification": "x07-production-pea-off",
        "result": "actual Jeandle pipeline with PEA off; 5 queries, 3 Final hits/2 insertions",
    },
    {
        "key": "p4-existing-cff",
        "phase": "P4",
        "case_id": "EXISTING-CFF-REUSE",
        "input": "existing cache-reuse.ll",
        "pipeline": "function(constant-field-folding,print<java-type-analysis>)",
        "mode": "IN-PASS",
        "diagnostic": "existing-cff-cache-reuse",
        "verification": None,
        "result": "6 queries; 3 Final hits; 1 Base insertion; 2 selective invalidations",
    },
    {
        "key": "p4-selective",
        "phase": "P4",
        "case_id": "SELECTIVE-vs-FULL",
        "input": "existing selective-invalidation.ll",
        "pipeline": "function(type-check-elimination,cha-devirtualization)",
        "mode": "ORACLE-MODE",
        "diagnostic": "selective-invalidation-selective",
        "verification": None,
        "result": "selective: 4 Base insertions/5 selective invalidations; full: 12 insertions/5 clears",
        "comparison_diagnostic": "selective-invalidation-full",
    },
]


def parse_stats(log_path):
    if not log_path or not log_path.exists():
        return None
    blocks = []
    current = None
    for line in log_path.read_text(errors="replace").splitlines():
        if line.startswith("JavaTypeAnalysis for function: ") or line.startswith(
            "JavaTypeAnalysis process summary after module: "
        ):
            if current:
                blocks.append(current)
            current = {"function": line.split(": ", 1)[1], "fields": {}}
            continue
        if current is None:
            continue
        match = re.match(r"^  ([^:]+):\s*(.+)$", line)
        if not match:
            continue
        key, value = match.groups()
        key = key.strip()
        value = value.strip()
        current["fields"][key] = int(value) if value.isdigit() else value
    if current:
        blocks.append(current)
    return blocks or None


def parse_trace(log_path):
    if not log_path or not log_path.exists():
        return []
    events = []
    for line in log_path.read_text(errors="replace").splitlines():
        match = QUERY_RE.match(line)
        if match:
            event = match.groupdict()
            for key in event:
                if key not in {"function", "value", "context"}:
                    event[key] = int(event[key])
            events.append(event)
    return events


def parse_rc(path):
    if not path.exists():
        return None
    return int(path.read_text().strip())


def parse_timing():
    rows = []
    summaries = {}
    timing_dir = RESULTS / "timing"
    for csv_path in sorted(timing_dir.glob("*.csv")):
        with csv_path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                row["elapsed_ns"] = int(row["elapsed_ns"])
                row["round"] = int(row["round"])
                row["sequence"] = int(row["sequence"])
                row["returncode"] = int(row["returncode"])
                row["summary_csv"] = str(csv_path.relative_to(ROOT))
                rows.append(row)
    for summary_path in sorted(timing_dir.glob("*-summary.json")):
        label = summary_path.name.removesuffix("-summary.json")
        data = json.loads(summary_path.read_text())
        cross = statistics.median(data["CROSS-PASS"]["samples_ns"])
        local = statistics.median(data["PASS-LOCAL"]["samples_ns"])
        data["median_delta_pass_local_minus_cross_ns"] = local - cross
        data["median_ratio_pass_local_over_cross"] = local / cross
        data["_summary_path"] = str(summary_path.relative_to(ROOT))
        summaries[label] = data
    return rows, summaries


def parse_named_tests(log_path):
    text = log_path.read_text(errors="replace") if log_path.exists() else ""
    return sorted(
        line.strip()
        for line in text.splitlines()
        if line.startswith("  LLVM :: Jeandle/")
        or line.startswith("[  FAILED  ] JavaType")
    )


def main():
    SUMMARY.mkdir(exist_ok=True)
    case_rows = []
    result_cases = {}

    for case in CASES:
        diag_log = RESULTS / "diagnostics" / f"{case['diagnostic']}.log"
        diag_stats = parse_stats(diag_log)
        trace = parse_trace(diag_log)
        verification_stats = None
        if case["verification"]:
            verification_log = (
                RESULTS / "verification" / f"{case['verification']}.log"
            )
            verification_stats = parse_stats(verification_log)

        enrichment = {
            "diagnostic_rc": parse_rc(
                RESULTS / "diagnostics" / f"{case['diagnostic']}.rc"
            ),
            "diagnostic_log": str(diag_log.relative_to(ROOT)),
            "query_trace": trace,
            "statistics_blocks": diag_stats,
            "verification_blocks": verification_stats,
            "verification_log": (
                str(
                    (
                        RESULTS
                        / "verification"
                        / f"{case['verification']}.log"
                    ).relative_to(ROOT)
                )
                if case["verification"]
                else None
            ),
            "verification_rc": (
                parse_rc(
                    RESULTS
                    / "verification"
                    / f"{case['verification']}.rc"
                )
                if case["verification"]
                else None
            ),
        }
        if not diag_stats and trace:
            enrichment["trace_derived_stats"] = {
                "queries": len(trace),
                "final type hits": sum(e["final_hits"] for e in trace),
                "final type misses": sum(e["final_misses"] for e in trace),
                "base insertions": sum(e["base_insertions"] for e in trace),
            }
        result_cases[case["key"]] = {**case, **enrichment}

        if case.get("comparison_diagnostic"):
            comparison = case["comparison_diagnostic"]
            result_cases[case["key"]]["comparison"] = {
                "diagnostic": comparison,
                "diagnostic_log": str(
                    (
                        RESULTS / "diagnostics" / f"{comparison}.log"
                    ).relative_to(ROOT)
                ),
                "diagnostic_rc": parse_rc(
                    RESULTS / "diagnostics" / f"{comparison}.rc"
                ),
                "statistics_blocks": parse_stats(
                    RESULTS / "diagnostics" / f"{comparison}.log"
                ),
            }

        last_stats = diag_stats[-1]["fields"] if diag_stats else {}
        if not last_stats:
            last_stats = enrichment.get("trace_derived_stats", {})
        verification_fields = (
            verification_stats[-1]["fields"] if verification_stats else last_stats
        )
        case_rows.append(
            {
                "phase": case["phase"],
                "case_id": case["case_id"],
                "input": case["input"],
                "pipeline": case["pipeline"],
                "mode": case["mode"],
                "diagnostic_rc": enrichment["diagnostic_rc"],
                "queries": last_stats.get("queries", ""),
                "path_facts_hits": last_stats.get("path facts hits", ""),
                "path_facts_misses": last_stats.get("path facts misses", ""),
                "final_hits": last_stats.get("final type hits", ""),
                "final_misses": last_stats.get("final type misses", ""),
                "base_insertions": last_stats.get("base insertions", ""),
                "clears": last_stats.get("clears", ""),
                "invalidations": last_stats.get("invalidation requests", ""),
                "selective_invalidations": last_stats.get(
                    "selective invalidations", ""
                ),
                "cfg_invalidations": last_stats.get("CFG invalidations", ""),
                "base_invalidated": last_stats.get(
                    "base entries invalidated", ""
                ),
                "facts_invalidated": last_stats.get(
                    "path facts entries invalidated", ""
                ),
                "final_invalidated": last_stats.get(
                    "final type entries invalidated", ""
                ),
                "query_time_ns_single_run": last_stats.get(
                    "total query time (ns)", ""
                ),
                "invalidation_time_ns_single_run": last_stats.get(
                    "total invalidation time (ns)", ""
                ),
                "verifications": verification_fields.get("verifications", ""),
                "verification_skips": verification_fields.get(
                    "verification skips", ""
                ),
                "trace_events": len(trace),
                "observed_result": case["result"],
                "diagnostic_log": enrichment["diagnostic_log"],
            }
        )

    timing_rows, timing_summaries = parse_timing()
    trace_rows = []
    for key, case in result_cases.items():
        for event in case["query_trace"]:
            trace_rows.append({"case": key, **event})

    verification_summary = {}
    for path in sorted((RESULTS / "verification").glob("*.log")):
        blocks = parse_stats(path)
        verification_summary[path.stem] = (
            blocks[-1]["fields"] if blocks else {"note": "no statistics block"}
        )

    tests = {
        "new_lit": {
            "command": (
                RESULTS / "new-lit-final-14.command"
            ).read_text().strip(),
            "rc": parse_rc(RESULTS / "new-lit-final-14.rc"),
            "summary": {
                "tests": 14,
                "passed": 14,
                "failed": 0,
            },
        },
        "unit": {
            "command": (RESULTS / "unit-tests-final.command").read_text().strip(),
            "rc": parse_rc(RESULTS / "unit-tests-final.rc"),
            "summary": {"tests": 47, "passed": 46, "failed": 1},
        },
        "jeandle_lit": {
            "command": (
                RESULTS / "jeandle-lit-final-807.command"
            ).read_text().strip(),
            "rc": parse_rc(RESULTS / "jeandle-lit-final-807.rc"),
            "summary": {
                "tests": 807,
                "passed": 765,
                "unsupported": 25,
                "failed": 17,
            },
            "failures": parse_named_tests(
                RESULTS / "jeandle-lit-final-807.log"
            ),
        },
    }

    payload = {
        "scope": (
            "JavaType cache reuse mechanism tests and measurements; "
            "task 8 production preserve changes were not performed"
        ),
        "cases": result_cases,
        "timing": {
            "samples": timing_rows,
            "summaries": timing_summaries,
            "interpretation": (
                "Five-round pilot with warmup. Timings include process startup "
                "and IR parsing and have broad within-mode spread; they do not "
                "establish a performance improvement."
            ),
        },
        "verification_summary": verification_summary,
        "tests": tests,
        "uncovered": [
            "LVI oracle call count was not separately instrumented.",
            "Pass invocation IDs and cache-entry generations were not separately instrumented.",
            "No stable end-to-end performance claim; the timing is a noisy pilot.",
            "X07 covers --jeandle with PEA disabled, not the complete production pipeline.",
            "The full production pipeline with PEA enabled was blocked by incomplete VM callback fixtures.",
            "No cheap-leaf versus medium-DAG paired timing control was completed.",
            "No JVM application replay or application-level JVM performance measurement.",
            "CFF/RecoverTypeInfo production preserve support (task 8) was not implemented.",
        ],
    }

    (SUMMARY / "results.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )

    with (SUMMARY / "cases.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=case_rows[0].keys())
        writer.writeheader()
        writer.writerows(case_rows)

    with (SUMMARY / "query-trace.csv").open(
        "w", newline="", encoding="utf-8"
    ) as out:
        fieldnames = [
            "case",
            "function",
            "ordinal",
            "value",
            "context",
            "base_hits",
            "base_misses",
            "facts_hits",
            "facts_misses",
            "final_hits",
            "final_misses",
            "base_insertions",
        ]
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trace_rows)

    print(f"wrote {SUMMARY / 'results.json'}")
    print(f"wrote {SUMMARY / 'cases.csv'} ({len(case_rows)} cases)")
    print(f"wrote {SUMMARY / 'query-trace.csv'} ({len(trace_rows)} events)")


if __name__ == "__main__":
    main()
