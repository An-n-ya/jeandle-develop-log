#!/usr/bin/env python3
"""Record profiling data and one complete user stack dump per run.

This is an out-of-tree execution helper for the frozen profiling runner.  It
keeps the same command construction and identity checks, but defers the three
expensive derived perf reports until after all raw samples have been captured.
"""

import argparse
import hashlib
import importlib.util
import json
import shlex
import subprocess
import time
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def command_record(command):
    return {
        "argv": [str(item) for item in command],
        "shell": shlex.join(str(item) for item in command),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--opt", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--case", action="append")
    parser.add_argument("--mode", action="append")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    spec = importlib.util.spec_from_file_location("frozen_profiler", args.runner)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import runner: {args.runner}")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    out = args.out.resolve()
    manifest = helper.load_manifest(out)
    helper.ensure_identity(manifest, "script-only record setup")
    cases = args.case or list(manifest["cases"])
    modes = args.mode or list(helper.MODES)

    for case in cases:
        for run_index in range(args.repeats):
            for mode in modes:
                dest = out / "profiles" / case / mode / f"run-{run_index:02d}"
                if (dest / "SUCCESS").exists():
                    continue
                dest.mkdir(parents=True, exist_ok=True)
                perf_data = dest / "perf.data"
                record_command = [
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
                    "taskset",
                    "-c",
                    str(args.cpu),
                    *helper.case_command(manifest, case, mode),
                ]
                record_result, elapsed_ns = run(
                    record_command, dest / "record.stderr"
                )
                (dest / "record.command.json").write_text(
                    json.dumps(command_record(record_command), indent=2) + "\n"
                )
                script_command = ["perf", "script", "-i", perf_data]
                run(
                    script_command,
                    dest / "stacks.txt.stderr",
                    dest / "stacks.txt",
                )
                (dest / "script.command.json").write_text(
                    json.dumps(command_record(script_command), indent=2) + "\n"
                )
                if not perf_data.exists() or not (dest / "stacks.txt").exists():
                    raise RuntimeError(f"missing raw output for {case}/{mode}")
                (dest / "run.json").write_text(
                    json.dumps(
                        {
                            "case": case,
                            "mode": mode,
                            "run": run_index,
                            "elapsed_ns": elapsed_ns,
                            "perf_data_bytes": perf_data.stat().st_size,
                            "perf_data_sha256": sha256(perf_data),
                            "stacks_sha256": sha256(dest / "stacks.txt"),
                            "event": "cycles:u",
                            "frequency_hz": 199,
                            "call_graph": "dwarf,8192",
                            "command": command_record(record_command),
                            "record_stderr": record_result.stderr.decode(
                                errors="replace"
                            ),
                            "derived_reports": "deferred",
                        },
                        indent=2,
                    )
                    + "\n"
                )
                (dest / "SUCCESS").write_text(
                    "raw profile and complete stack dump captured\n"
                )
                print(f"record-script {case}/{mode}/run-{run_index:02d}", flush=True)
    helper.ensure_identity(manifest, "script-only record")


if __name__ == "__main__":
    main()
