#!/usr/bin/env python3
"""Run alternating CROSS-PASS/PASS-LOCAL pilot measurements."""

import argparse
import csv
import json
import statistics
import subprocess
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opt", type=Path, required=True)
    parser.add_argument("--callback-log", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    pipelines = {
        "CROSS-PASS": "type-check-elimination,recover-type-info",
        "PASS-LOCAL": (
            "type-check-elimination,jeandle-java-type-cache-boundary,"
            "recover-type-info"
        ),
    }

    rows = []
    for mode, pipeline in pipelines.items():
        command = [
            str(args.opt),
            "-disable-output",
            f"-passes={pipeline}",
            f"-jeandle-vm-callback-log={args.callback_log}",
            str(args.input),
        ]
        completed = subprocess.run(command, capture_output=True, text=True)
        (raw_dir / f"warmup-{mode}.stdout").write_text(
            completed.stdout, encoding="utf-8"
        )
        (raw_dir / f"warmup-{mode}.stderr").write_text(
            completed.stderr, encoding="utf-8"
        )
        if completed.returncode != 0:
            raise SystemExit(f"warmup failed for {mode}: {completed.returncode}")

    for round_index in range(1, args.rounds + 1):
        order = ["CROSS-PASS", "PASS-LOCAL"]
        if round_index % 2 == 0:
            order.reverse()
        for sequence, mode in enumerate(order, start=1):
            pipeline = pipelines[mode]
            command = [
                str(args.opt),
                "-disable-output",
                f"-passes={pipeline}",
                f"-jeandle-vm-callback-log={args.callback_log}",
                str(args.input),
            ]
            started = time.perf_counter_ns()
            completed = subprocess.run(command, capture_output=True, text=True)
            elapsed = time.perf_counter_ns() - started

            stem = f"{args.label}-round{round_index}-{sequence}-{mode}"
            (raw_dir / f"{stem}.stdout").write_text(
                completed.stdout, encoding="utf-8"
            )
            (raw_dir / f"{stem}.stderr").write_text(
                completed.stderr, encoding="utf-8"
            )
            rows.append(
                {
                    "label": args.label,
                    "round": round_index,
                    "sequence": sequence,
                    "mode": mode,
                    "elapsed_ns": elapsed,
                    "returncode": completed.returncode,
                    "command": json.dumps(command),
                    "stdout": str(raw_dir / f"{stem}.stdout"),
                    "stderr": str(raw_dir / f"{stem}.stderr"),
                }
            )
            if completed.returncode != 0:
                raise SystemExit(f"timed run failed for {mode}: {completed.returncode}")

    csv_path = args.output_dir / f"{args.label}.csv"
    with csv_path.open("w", newline="", encoding="ascii") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    summary = {}
    for mode in pipelines:
        samples = [row["elapsed_ns"] for row in rows if row["mode"] == mode]
        summary[mode] = {
            "samples_ns": samples,
            "median_ns": statistics.median(samples),
            "min_ns": min(samples),
            "max_ns": max(samples),
        }
    summary_path = args.output_dir / f"{args.label}-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="ascii")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
