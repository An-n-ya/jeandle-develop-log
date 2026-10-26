#!/usr/bin/env python3
"""Summarize the frozen JavaType profiling run without decoding DWARF again."""

import argparse
import collections
import csv
import hashlib
import json
import math
import random
import re
import statistics
from pathlib import Path


MODES = ("origin", "full", "s0", "s1")
HEADER_RE = re.compile(
    r"^(?P<comm>\S+)\s+(?P<pid>\d+)\s+(?P<time>[\d.]+):\s+"
    r"(?P<period>\d+)\s+(?P<event>.+):\s*$"
)
FRAME_RE = re.compile(r"^\s+(?P<address>[0-9a-fA-F]+)\s+(?P<symbol>.+)$")

JAVATYPE_MARKERS = (
    "getJavaType",
    "getCachedJavaType",
    "JavaTypeAnalysis",
    "JavaTypeCache",
    "getBaseJavaType",
    "valueDimension",
    "phiValueType",
    "factsAt",
    "edgeGuard",
    "mergePathFacts",
    "typeUnion",
    "typeIntersect",
)

INVALIDATION_MARKERS = (
    "JavaTypeCache::invalidate",
    "JavaTypeAnalysisResult::invalidateImpl",
    "JavaTypeAnalysisResult::invalidate(",
)

LVI_MARKERS = (
    "LazyValueInfo",
    "solveBlockValue",
    "solveBlockValueImpl",
    "solveBlockValueSelect",
    "solve(",
    "getValueOnEdge",
    "getPredicateOnEdge",
    "programUndefinedIfUndefOrPoison",
    "isGuaranteedNotToBeUndefOrPoison",
    "isNullEdge",
)

TYPEOPS_MARKERS = (
    "typeIntersect",
    "typeUnion",
    "mergePathFacts",
    "isExcludedBy",
    "IsSubtype",
)

CONTAINER_MARKERS = (
    "DenseMap",
    "DenseMapBase",
    "SmallDenseMap",
    "SmallDenseSet",
    "DenseSet",
    "SmallPtrSet",
    "SmallVector",
    "try_emplace",
    "MapBase::erase",
    "DenseMapBase::erase",
    "rehash",
    "grow",
)

ALLOCATION_MARKERS = (
    "malloc",
    "calloc",
    "realloc",
    "free",
    "operator new",
    "operator delete",
    "allocate",
    "deallocate",
    "Allocator",
)

LIFECYCLE_MARKERS = (
    "~AnalysisResultModel",
    "~JavaTypeAnalysisResult",
    "~JavaTypeCache",
    "AnalysisResultModel<llvm::Function, llvm::jeandle::JavaTypeAnalysis",
)

CFF_MARKERS = (
    "ConstantFieldFolding",
    "foldFieldLoad",
    "foldLoadKlassCall",
    "foldLoadMirrorKlassCall",
    "foldGetClassCall",
    "foldLayoutHelperCall",
    "foldKlassInitializedCall",
)

CHA_MARKERS = (
    "CHADevirtualization",
    "optimizeCallSite",
    "optimizeMhIntrinsic",
    "tryNarrowJavaObjType",
)

OTHER_ANALYSIS_MARKERS = (
    "RecoverTypeInfo",
    "ArrayCopySpecialization",
)

PARSER_MARKERS = (
    "parseIR",
    "parseAssembly",
    "parseBitcode",
)


def ensure(path: Path):
    if not path.exists():
        raise SystemExit(f"missing input: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return values[low]
    return values[low] * (high - position) + values[high] * (position - low)


def summary(values):
    return {
        "n": len(values),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "p05": percentile(values, 0.05),
        "p95": percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
    }


def bootstrap_median_ci(values, iterations=10000, seed=20261023):
    values = list(values)
    if not values:
        return None
    rng = random.Random(seed)
    medians = []
    for _ in range(iterations):
        sample = [values[rng.randrange(len(values))] for _ in values]
        medians.append(statistics.median(sample))
    return {
        "estimate": statistics.median(values),
        "low_95": percentile(medians, 0.025),
        "high_95": percentile(medians, 0.975),
        "iterations": iterations,
    }


def clean_symbol(raw: str) -> str:
    value = raw.strip()
    if value.endswith(" (inlined)"):
        value = value[: -len(" (inlined)")]
    match = re.match(r"^(.*?)(?: \((?:/|\[).*\))$", value)
    if match:
        value = match.group(1)
    return re.sub(r"\+0x[0-9a-fA-F]+$", "", value).strip()


def parse_stacks(path: Path):
    samples = []
    current = None
    with path.open(errors="replace") as handle:
        for line in handle:
            header = HEADER_RE.match(line.rstrip("\n"))
            if header:
                if current is not None:
                    samples.append(current)
                current = {
                    "period": int(header.group("period")),
                    "frames": [],
                }
                continue
            if current is None:
                continue
            frame = FRAME_RE.match(line.rstrip("\n"))
            if frame:
                current["frames"].append(clean_symbol(frame.group("symbol")))
    if current is not None:
        samples.append(current)
    return samples


def any_marker(frames, markers):
    return any(marker in frame for frame in frames for marker in markers)


def leaf_category(frames):
    leaf = frames[0] if frames else "[missing]"
    if leaf == "[unknown]" or leaf.startswith("[unknown]"):
        return "unknown"
    if any(marker in leaf for marker in INVALIDATION_MARKERS):
        return "invalidation"
    if any(marker in leaf for marker in LVI_MARKERS):
        return "lvi_edge_facts"
    if any(marker in leaf for marker in TYPEOPS_MARKERS):
        return "type_ops"
    if any(marker in leaf for marker in CONTAINER_MARKERS):
        return "cache_container_access"
    if any(marker in leaf for marker in ALLOCATION_MARKERS):
        return "copy_allocation_free"
    if any(marker in leaf for marker in LIFECYCLE_MARKERS):
        return "analysis_lifecycle"
    if any(marker in leaf for marker in PARSER_MARKERS):
        return "parse_startup"
    return "other_javatype"


def consumer(frames):
    if any(marker in frame for marker in CFF_MARKERS for frame in frames):
        return "cff"
    if any(marker in frame for marker in CHA_MARKERS for frame in frames):
        return "cha"
    if any(marker in frame for marker in OTHER_ANALYSIS_MARKERS for frame in frames):
        return "other_analysis"
    return "javatype_internal_or_other"


def parse_baseline(run: Path):
    samples_path = ensure(run / "baseline" / "samples.csv")
    rows = list(csv.DictReader(samples_path.open()))
    grouped = collections.defaultdict(list)
    for row in rows:
        if int(row["round"]) < 0:
            continue
        grouped[(row["case"], row["mode"])].append(
            {
                "round": int(row["round"]),
                "wall_s": float(row["wall_s"]),
                "user_s": float(row["user_s"]),
                "system_s": float(row["system_s"]),
                "max_rss_kb": float(row["max_rss_kb"]),
            }
        )
    result = {}
    for (case, mode), values in grouped.items():
        result.setdefault(case, {})[mode] = {
            metric: summary([row[metric] for row in values])
            for metric in ("wall_s", "user_s", "system_s", "max_rss_kb")
        }
    comparisons = {}
    for case, modes in result.items():
        by_mode = {
            mode: {row["round"]: row for row in grouped[(case, mode)]}
            for mode in modes
        }
        for other in ("origin", "full", "s0"):
            rounds = sorted(set(by_mode["s1"]) & set(by_mode[other]))
            deltas = [
                by_mode["s1"][round_index]["user_s"]
                - by_mode[other][round_index]["user_s"]
                for round_index in rounds
            ]
            baseline_median = statistics.median(
                by_mode[other][round_index]["user_s"] for round_index in rounds
            )
            comparisons[f"{case}:s1_minus_{other}"] = {
                "delta_s": summary(deltas),
                "median_delta_bootstrap_95": bootstrap_median_ci(deltas),
                "relative_to_other_pct": {
                    "estimate": 100
                    * statistics.median(deltas)
                    / baseline_median,
                },
            }
    return {
        "raw_csv": str(samples_path),
        "raw_sha256": sha256(samples_path),
        "metrics": result,
        "paired_s1_user_delta_s": comparisons,
    }


def parse_stat(run: Path):
    by_mode = collections.defaultdict(lambda: collections.defaultdict(list))
    quality = []
    for path in sorted((run / "stat").glob("*/*.json")):
        item = json.loads(path.read_text())
        case, mode, group = item["case"], item["mode"], item["group"]
        by_mode[(case, mode)][group].append(item)
        for event, metric in item["metrics"].items():
            if event.startswith("cpu_core/"):
                continue
            quality.append(
                {
                    "case": case,
                    "mode": mode,
                    "group": group,
                    "event": event,
                    "running_pct": float(metric.get("running_pct") or 0),
                    "runtime": float(metric.get("enabled_pct") or 0),
                }
            )
    rows = {}
    for (case, mode), groups in by_mode.items():
        software = {}
        core = {}
        for item in groups.get("software", []):
            for event, metric in item["metrics"].items():
                software.setdefault(event, []).append(float(metric["value"]))
        for item in groups.get("core", []):
            for event, metric in item["metrics"].items():
                if event.startswith("cpu_atom/"):
                    core.setdefault(event, []).append(float(metric["value"]))
        cycles = core.get("cpu_atom/cycles/u", [])
        instructions = core.get("cpu_atom/instructions/u", [])
        branches = core.get("cpu_atom/branches/u", [])
        branch_misses = core.get("cpu_atom/branch-misses/u", [])
        row = {
            "software": {
                event: summary(values) for event, values in sorted(software.items())
            },
            "cpu_atom": {
                event: summary(values) for event, values in sorted(core.items())
            },
        }
        if len(cycles) == len(instructions):
            row["ipc"] = summary(
                [instruction / cycle for cycle, instruction in zip(cycles, instructions)]
            )
        if len(branches) == len(branch_misses):
            row["branch_misses_per_1000_branches"] = summary(
                [miss / branch * 1000 for branch, miss in zip(branches, branch_misses)]
            )
        rows.setdefault(case, {})[mode] = row
    minimum_running = min(
        (
            item["running_pct"]
            for item in quality
            if not item["event"].startswith("cpu_core/")
        ),
        default=0,
    )
    return {
        "metrics": rows,
        "quality": {
            "records": len(quality),
            "minimum_running_pct_across_effective_events": minimum_running,
            "note": (
                "cpu_core events are excluded because CPU 16 is an E-core; "
                "perf reported 0% running for them."
            ),
        },
    }


def parse_profiles(run: Path):
    profile_rows = []
    leaf_accumulators = collections.defaultdict(collections.Counter)
    category_accumulators = collections.defaultdict(collections.Counter)
    consumer_accumulators = collections.defaultdict(collections.Counter)
    quality = []
    profile_root = run / "profiles"
    for stack_path in sorted(profile_root.glob("*/*/run-*/stacks.txt")):
        dest = stack_path.parent
        case, mode = dest.parts[-3], dest.parts[-2]
        run_json_path = dest / "run.json"
        run_info = json.loads(run_json_path.read_text()) if run_json_path.exists() else {}
        samples = parse_stacks(stack_path)
        total_count = len(samples)
        total_cycles = sum(sample["period"] for sample in samples)
        leaf_counts = collections.Counter()
        leaf_cycles = collections.Counter()
        category_counts = collections.Counter()
        category_cycles = collections.Counter()
        consumer_counts = collections.Counter()
        consumer_cycles = collections.Counter()
        unknown_count = unknown_cycles = 0
        jt_count = jt_cycles = 0
        invalidation_count = invalidation_cycles = 0
        lifecycle_count = lifecycle_cycles = 0
        for sample in samples:
            frames = sample["frames"]
            period = sample["period"]
            leaf = frames[0] if frames else "[missing]"
            leaf_counts[leaf] += 1
            leaf_cycles[leaf] += period
            in_jt = any_marker(frames, JAVATYPE_MARKERS)
            in_invalidation = any_marker(frames, INVALIDATION_MARKERS)
            in_lifecycle = any_marker(frames, LIFECYCLE_MARKERS)
            if leaf == "[unknown]" or leaf.startswith("[unknown]"):
                unknown_count += 1
                unknown_cycles += period
            if in_jt:
                jt_count += 1
                jt_cycles += period
                category = leaf_category(frames)
                who = consumer(frames)
                category_counts[category] += 1
                category_cycles[category] += period
                consumer_counts[who] += 1
                consumer_cycles[who] += period
            elif in_lifecycle:
                lifecycle_count += 1
                lifecycle_cycles += period
            if in_invalidation:
                invalidation_count += 1
                invalidation_cycles += period
        row = {
            "case": case,
            "mode": mode,
            "run": int(dest.name.removeprefix("run-")),
            "samples": total_count,
            "sample_period_sum": total_cycles,
            "javatype_inclusive_samples": jt_count,
            "javatype_inclusive_sample_pct": (
                100 * jt_count / total_count if total_count else None
            ),
            "javatype_inclusive_period_sum": jt_cycles,
            "javatype_inclusive_period_pct": (
                100 * jt_cycles / total_cycles if total_cycles else None
            ),
            "invalidation_inclusive_samples": invalidation_count,
            "invalidation_inclusive_period_pct": (
                100 * invalidation_cycles / total_cycles if total_cycles else None
            ),
            "lifecycle_inclusive_samples": lifecycle_count,
            "unknown_leaf_samples": unknown_count,
            "unknown_leaf_pct": 100 * unknown_count / total_count if total_count else None,
            "unknown_leaf_period_pct": (
                100 * unknown_cycles / total_cycles if total_cycles else None
            ),
            "elapsed_s": run_info.get("elapsed_ns", 0) / 1e9,
            "perf_data_bytes": run_info.get("perf_data_bytes"),
            "perf_data_sha256": run_info.get("perf_data_sha256"),
            "stacks_sha256": sha256(stack_path),
            "record_stderr": run_info.get("record_stderr", ""),
        }
        profile_rows.append(row)
        quality.append(row)
        leaf_accumulators[(case, mode)].update(leaf_cycles)
        category_accumulators[(case, mode)].update(category_cycles)
        consumer_accumulators[(case, mode)].update(consumer_cycles)

    aggregates = {}
    for case in sorted({row["case"] for row in profile_rows}):
        aggregates[case] = {}
        for mode in MODES:
            rows = [
                row
                for row in profile_rows
                if row["case"] == case and row["mode"] == mode
            ]
            if not rows:
                continue
            def repeated(metric):
                values = [row[metric] for row in rows if row[metric] is not None]
                return summary(values) if values else None
            leaf_counter = leaf_accumulators[(case, mode)]
            total_period = sum(leaf_counter.values())
            category_counter = category_accumulators[(case, mode)]
            consumer_counter = consumer_accumulators[(case, mode)]
            aggregates[case][mode] = {
                "runs": len(rows),
                "samples": repeated("samples"),
                "javatype_inclusive_sample_pct": repeated(
                    "javatype_inclusive_sample_pct"
                ),
                "javatype_inclusive_period_pct": repeated(
                    "javatype_inclusive_period_pct"
                ),
                "invalidation_inclusive_period_pct": repeated(
                    "invalidation_inclusive_period_pct"
                ),
                "unknown_leaf_period_pct": repeated("unknown_leaf_period_pct"),
                "sample_overhead_wall_s": repeated("elapsed_s"),
                "top_self_leaf_by_period_pct": [
                    {
                        "symbol": symbol,
                        "period": period,
                        "pct": 100 * period / total_period,
                    }
                    for symbol, period in leaf_counter.most_common(40)
                ],
                "javatype_category_by_period_pct": [
                    {
                        "category": category,
                        "period": period,
                        "pct_of_javatype": (
                            100 * period / sum(category_counter.values())
                            if sum(category_counter.values())
                            else 0
                        ),
                        "pct_of_process": (
                            100 * period / total_period if total_period else 0
                        ),
                    }
                    for category, period in category_counter.most_common()
                ],
                "consumer_by_period_pct": [
                    {
                        "consumer": consumer_name,
                        "period": period,
                        "pct_of_javatype": (
                            100 * period / sum(consumer_counter.values())
                            if sum(consumer_counter.values())
                            else 0
                        ),
                        "pct_of_process": (
                            100 * period / total_period if total_period else 0
                        ),
                    }
                    for consumer_name, period in consumer_counter.most_common()
                ],
            }
    minimum_samples = min((row["samples"] for row in profile_rows), default=0)
    lost_runs = [
        str(run / "profiles" / row["case"] / row["mode"] / f"run-{row['run']:02d}")
        for row in profile_rows
        if "lost" in row["record_stderr"].lower()
    ]
    return {
        "profiles": profile_rows,
        "aggregates": aggregates,
        "quality": {
            "minimum_samples_in_one_profile": minimum_samples,
            "profiles_with_lost_warning": lost_runs,
            "quality_note": (
                "Unknown percentages use leaf IP periods. Invalidation and "
                "JavaType percentages are inclusive and must not be added."
            ),
        },
    }


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_profile_csv(analysis_dir: Path, profiles):
    rows = []
    for case, modes in profiles["aggregates"].items():
        for mode, item in modes.items():
            rows.append(
                {
                    "case": case,
                    "mode": mode,
                    "runs": item["runs"],
                    "median_samples": item["samples"]["median"],
                    "median_javatype_inclusive_sample_pct": item[
                        "javatype_inclusive_sample_pct"
                    ]["median"],
                    "median_javatype_inclusive_period_pct": item[
                        "javatype_inclusive_period_pct"
                    ]["median"],
                    "median_invalidation_inclusive_period_pct": item[
                        "invalidation_inclusive_period_pct"
                    ]["median"],
                    "median_unknown_leaf_period_pct": item[
                        "unknown_leaf_period_pct"
                    ]["median"],
                    "median_record_elapsed_s": item["sample_overhead_wall_s"][
                        "median"
                    ],
                }
            )
    write_csv(analysis_dir / "profile-summary.csv", rows)
    write_csv(
        analysis_dir / "profile-runs.csv",
        [
            {
                key: value
                for key, value in row.items()
                if key != "record_stderr"
            }
            for row in profiles["profiles"]
        ],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = ensure(args.run.resolve())
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    baseline = parse_baseline(run)
    stat = parse_stat(run)
    profiles = parse_profiles(run)
    write_json(out / "baseline-summary.json", baseline)
    write_json(out / "stat-summary.json", stat)
    write_json(out / "profile-summary.json", profiles)
    write_profile_csv(out, profiles)
    print(json.dumps(
        {
            "baseline_cases": len(baseline["metrics"]),
            "stat_cases": len(stat["metrics"]),
            "profile_runs": len(profiles["profiles"]),
            "profile_quality": profiles["quality"],
        },
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
