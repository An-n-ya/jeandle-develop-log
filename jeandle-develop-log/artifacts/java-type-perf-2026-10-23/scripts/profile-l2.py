#!/usr/bin/env python3
"""Run baseline, perf stat, and raw stack profiles for the prepared L2 CFF input."""

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import random
import shlex
import statistics
import subprocess
import time
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_record(command):
    return {
        "argv": [str(item) for item in command],
        "shell": shlex.join(str(item) for item in command),
    }


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run(command, stderr_path: Path, stdout_path: Path | None = None):
    started = time.perf_counter_ns()
    completed = subprocess.run(
        [str(item) for item in command],
        stdout=subprocess.PIPE if stdout_path else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    elapsed_ns = time.perf_counter_ns() - started
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.write_bytes(completed.stderr)
    if stdout_path:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_bytes(completed.stdout)
    if completed.returncode:
        raise RuntimeError(
            f"command failed with {completed.returncode}; see {stderr_path}: "
            + shlex.join(str(item) for item in command)
        )
    return completed, elapsed_ns


def measure(command, stderr_path: Path):
    started = time.perf_counter_ns()
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            [str(item) for item in command],
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    elapsed_ns = time.perf_counter_ns() - started
    if process.returncode:
        raise RuntimeError(
            f"command failed with {process.returncode}; see {stderr_path}: "
            + shlex.join(str(item) for item in command)
        )
    return elapsed_ns, usage


def load_helper(path: Path):
    spec = importlib.util.spec_from_file_location("frozen_profiler", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def l2_command(helper, manifest, l2_case, mode, cpu):
    item = manifest["l2"][l2_case]
    return [
        "taskset",
        "-c",
        str(cpu),
        *helper.item_command(
            manifest, item, mode, verify=False, stats=False, output=False
        ),
    ]


def baseline(args, helper, manifest):
    root = args.out / "l2" / "baseline"
    rows = []
    rng = random.Random(args.seed)
    for round_index in range(-args.warmups, args.repeats):
        order = list(helper.MODES)
        rng.shuffle(order)
        for mode in order:
            stem = root / args.case / f"{round_index:03d}-{mode}"
            if stem.with_suffix(".json").exists():
                rows.append(
                    json.loads(stem.with_suffix(".json").read_text())
                )
                continue
            command = l2_command(
                helper, manifest, args.case, mode, args.cpu
            )
            elapsed_ns, usage = measure(
                command, stem.with_suffix(".stderr")
            )
            row = {
                "case": args.case,
                "round": round_index,
                "mode": mode,
                "wall_s": elapsed_ns / 1e9,
                "user_s": usage.ru_utime,
                "system_s": usage.ru_stime,
                "max_rss_kb": usage.ru_maxrss,
                "command": command_record(command),
            }
            write_json(stem.with_suffix(".json"), row)
            rows.append(row)
        measured = [row for row in rows if row["round"] >= 0]
        print(
            f"L2 baseline round {round_index}: "
            + ", ".join(
                f"{mode}={statistics.median(r['user_s'] for r in measured if r['mode'] == mode):.3f}s"
                for mode in helper.MODES
                if any(r["mode"] == mode for r in measured)
            ),
            flush=True,
        )
    root.mkdir(parents=True, exist_ok=True)
    with (root / "samples.csv").open("w", newline="") as handle:
        fields = ["case", "round", "mode", "wall_s", "user_s", "system_s", "max_rss_kb"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fields})


def stat(args, helper, manifest):
    root = args.out / "l2" / "stat"
    groups = [
        ("software", "task-clock:u,context-switches:u,cpu-migrations:u,page-faults:u"),
        ("core", "cycles:u,instructions:u,branches:u,branch-misses:u"),
    ]
    for round_index in range(args.repeats):
        for group, events in groups:
            for mode in helper.MODES:
                stem = root / args.case / f"{round_index:03d}-{mode}-{group}"
                if stem.with_suffix(".json").exists():
                    continue
                command = [
                    "perf",
                    "stat",
                    "-x",
                    ";",
                    "-e",
                    events,
                    "--",
                    *l2_command(helper, manifest, args.case, mode, args.cpu),
                ]
                result, _ = run(command, stem.with_suffix(".stderr"))
                row = {
                    "case": args.case,
                    "round": round_index,
                    "mode": mode,
                    "group": group,
                    "events": events,
                    "metrics": helper.parse_semicolon_metrics(
                        result.stderr.decode(errors="replace")
                    ),
                    "command": command_record(command),
                }
                write_json(stem.with_suffix(".json"), row)
        print(f"L2 stat round {round_index}: complete", flush=True)


def record(args, helper, manifest):
    root = args.out / "l2" / "profiles"
    rng = random.Random(args.seed)
    for run_index in range(args.repeats):
        order = list(helper.MODES)
        rng.shuffle(order)
        for mode in order:
            dest = root / args.case / mode / f"run-{run_index:02d}"
            if (dest / "SUCCESS").exists():
                continue
            dest.mkdir(parents=True, exist_ok=True)
            perf_data = dest / "perf.data"
            command = [
                "perf",
                "record",
                "-e",
                "cycles:u",
                "-F",
                "199",
                "--call-graph",
                "dwarf,8192",
                "-o",
                perf_data,
                "--",
                *l2_command(helper, manifest, args.case, mode, args.cpu),
            ]
            result, elapsed_ns = run(command, dest / "record.stderr")
            (dest / "record.command.json").write_text(
                json.dumps(command_record(command), indent=2) + "\n"
            )
            script_command = ["perf", "script", "--no-inline", "-i", perf_data]
            run(
                script_command,
                dest / "stacks.txt.stderr",
                dest / "stacks.txt",
            )
            (dest / "script.command.json").write_text(
                json.dumps(command_record(script_command), indent=2) + "\n"
            )
            write_json(
                dest / "run.json",
                {
                    "case": args.case,
                    "mode": mode,
                    "run": run_index,
                    "elapsed_ns": elapsed_ns,
                    "perf_data_bytes": perf_data.stat().st_size,
                    "perf_data_sha256": sha256(perf_data),
                    "stacks_sha256": sha256(dest / "stacks.txt"),
                    "event": "cycles:u",
                    "frequency_hz": 199,
                    "call_graph": "dwarf,8192",
                    "command": command_record(command),
                    "record_stderr": result.stderr.decode(errors="replace"),
                    "derived_reports": "deferred",
                },
            )
            (dest / "SUCCESS").write_text(
                "raw profile and complete stack dump captured\n"
            )
            print(
                f"L2 record {args.case}/{mode}/run-{run_index:02d}",
                flush=True,
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("baseline", "stat", "record"))
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--opt", type=Path, required=True)
    parser.add_argument("--case", default="cff-cache-reuse")
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=3)
    args = parser.parse_args()
    args.out = args.out.resolve()
    helper = load_helper(args.runner.resolve())
    # Preserve identical hashes without loading the 1.8 GiB opt into parent RSS.
    helper.sha256 = sha256
    manifest = helper.load_manifest(args.out)
    if (
        Path(manifest["opt"]).resolve() != args.opt.resolve()
        or Path(manifest["source"]["root"]).resolve()
        != args.source_root.resolve()
    ):
        raise RuntimeError("L2 command arguments disagree with manifest")
    helper.ensure_identity(manifest, f"L2 {args.phase} setup")
    {
        "baseline": baseline,
        "stat": stat,
        "record": record,
    }[args.phase](args, helper, manifest)
    helper.ensure_identity(manifest, f"L2 {args.phase}")


if __name__ == "__main__":
    main()
